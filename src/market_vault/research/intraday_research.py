"""Development-only intraday research on one verified common data context.

Trading-day folds, target-aware training and all-READY prediction are separate
from the V2 execution account. TEST prices/targets never enter a development fit.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
import math
from pathlib import Path, PureWindowsPath
import statistics

from ..backtest.intraday import INTRADAY_COST_VERSION, INTRADAY_EXECUTION_VERSION, _inputs, run_intraday_execution
from ..backtest.risk import ZERO_VOLATILITY_TOLERANCE
from .intraday_backtest import execution_views, intraday_data_path, parse_execution_policy, rule_decisions
from .intraday_data import INTRADAY_DATA_VERSION, digest, load_intraday_dataset, object_fields, positive_int
from .intraday_models import (INTRADAY_QUADRATIC_RIDGE_VERSION, QuadraticRidgeStrategy,
                              fit_quadratic_rows, quadratic_terms)
from .ridge_baseline import RIDGE_BASELINE_VERSION, _fit, _metrics, _predict
from .strategy_comparison import COMPOSITE_RULE_VERSION, CompositeRuleStrategy, FeatureRuleStrategy, RidgeStrategy
from .strategy_config import parse_strategy_specs, strategy_plan_fields
from .strategy_diagnostics import MAX_DIAGNOSTIC_EVALUATIONS, normalize_parameter_axes, parameter_variants


INTRADAY_RESEARCH_VERSION = "market-vault-intraday-research-v1"
INTRADAY_RESEARCH_PLAN_VERSION = "market-vault-intraday-research-plan-v1"
INTRADAY_DIAGNOSTICS_PLAN_VERSION = "market-vault-intraday-diagnostics-plan-v1"
INTRADAY_RESEARCH_RESULT_VERSION = "market-vault-intraday-research-result-v1"
INTRADAY_RESEARCH_V2_VERSION = "market-vault-intraday-research-v2"
INTRADAY_RESEARCH_PLAN_V2_VERSION = "market-vault-intraday-research-plan-v2"
INTRADAY_DIAGNOSTICS_PLAN_V2_VERSION = "market-vault-intraday-diagnostics-plan-v2"
INTRADAY_RESEARCH_RESULT_V2_VERSION = "market-vault-intraday-research-result-v2"
INTRADAY_RESEARCH_PLAN_VERSIONS = (INTRADAY_RESEARCH_PLAN_VERSION, INTRADAY_RESEARCH_PLAN_V2_VERSION)
INTRADAY_DIAGNOSTICS_PLAN_VERSIONS = (INTRADAY_DIAGNOSTICS_PLAN_VERSION, INTRADAY_DIAGNOSTICS_PLAN_V2_VERSION)
INTRADAY_WALK_FORWARD_VERSION = "market-vault-intraday-walk-forward-v1"
INTRADAY_DAILY_RISK_VERSION = "market-vault-intraday-daily-risk-v1"
INTRADAY_BENCHMARK_VERSION = "market-vault-intraday-benchmark-v1"
BENCHMARK_DEFINITION = {"entry": "FIRST_ELIGIBLE_READY", "exit": "EOD", "max_hold_rule": "FULL_EVALUATED_SESSION_GRID"}
_PLAN_FIELDS = {"plan_schema_version", "intraday_data_path", "data_id", "feature_fields", "split", "walk_forward", "strategies", "execution"}


def is_intraday_plan_v2(plan):
    return plan["plan_schema_version"] in (INTRADAY_RESEARCH_PLAN_V2_VERSION, INTRADAY_DIAGNOSTICS_PLAN_V2_VERSION)


def intraday_strategy_specs(plan):
    """Only an explicit intraday V2 comparison admits the new learned kind."""
    return parse_strategy_specs(plan["strategies"], allow_quadratic=is_intraday_plan_v2(plan))


def _day(value, label):
    if type(value) is not str or date.fromisoformat(value).isoformat() != value:
        raise ValueError(f"{label} must be an ISO trading day")
    return value


def _identity(value, label):
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 identity")
    return value


def normalize_intraday_research_plan(plan: dict, *, base: Path | None = None, recorded: bool = False) -> dict:
    """Preflight all inputs without source I/O; recorded locators stay portable."""
    object_fields(plan, _PLAN_FIELDS, "intraday research plan")
    if plan["plan_schema_version"] not in INTRADAY_RESEARCH_PLAN_VERSIONS:
        raise ValueError("unsupported intraday research plan version")
    data_id = _identity(plan["data_id"], "data_id")
    fields = plan["feature_fields"]
    if (type(fields) is not list or not fields or any(type(f) is not str or not f or f != f.strip() for f in fields)
            or len(set(fields)) != len(fields)):
        raise ValueError("an explicit unique ordered common Feature projection is required")
    strategies = intraday_strategy_specs(plan)
    if any(type(strategy) is QuadraticRidgeStrategy for strategy in strategies):
        quadratic_terms(fields)  # Dimension bound before source access or fitting.
    for strategy in strategies:
        rules = ((strategy.rule,) if type(strategy) is FeatureRuleStrategy else
                 strategy.conditions if type(strategy) is CompositeRuleStrategy else ())
        if any(rule.signal_field not in fields for rule in rules):
            raise ValueError("every rule must use the explicit common Feature projection")
    split = object_fields(plan["split"], {"train_end_day", "validation_end_day", "test_end_day"}, "day split")
    split = {key: _day(value, key) for key, value in split.items()}
    if not split["train_end_day"] < split["validation_end_day"] < split["test_end_day"]:
        raise ValueError("TRAIN, VALIDATION and TEST boundaries must increase")
    walk = object_fields(plan["walk_forward"], {"minimum_train_days", "validation_days", "step_days"}, "walk-forward")
    walk = {key: positive_int(value, key) for key, value in walk.items()}
    if walk["step_days"] < walk["validation_days"]:
        raise ValueError("step_days must be at least validation_days; validation dates cannot overlap")
    policy = parse_execution_policy(plan["execution"])
    locator = plan["intraday_data_path"]
    if recorded:
        if type(locator) is not str or not (Path(locator).is_absolute() or PureWindowsPath(locator).is_absolute()):
            raise ValueError("a saved intraday data locator must be absolute")
        # Reject dot segments using both host and Windows spelling, without resolving.
        if any(part in (".", "..") for part in locator.replace("\\", "/").split("/")):
            raise ValueError("a saved intraday locator must not contain dot segments")
    else:
        locator = str(intraday_data_path(locator, base=base))
    return {"plan_schema_version": plan["plan_schema_version"], "intraday_data_path": locator,
            "data_id": data_id, "feature_fields": list(fields), "split": split, "walk_forward": walk,
            "strategies": [strategy_plan_fields(s) for s in strategies], "execution": asdict(policy)}


def default_intraday_research_plan(data, *, commission_bps, slippage_bps) -> dict:
    """Propose explicit boundaries before evaluation: floor 70%, floor 15%, rest."""
    report = data.as_dict()["report"]
    days = [s["trading_day"] for s in report["sessions"]]
    train, validation = len(days) * 70 // 100, len(days) * 15 // 100
    if not train or not validation or train + validation >= len(days) or data.path is None:
        raise ValueError("saved data with nonempty TRAIN/VALIDATION/TEST day groups is required")
    feature = "return_2" if "return_2" in report["feature_names"] else report["feature_names"][0]
    from ..backtest.intraday import IntradayExecutionPolicy
    return normalize_intraday_research_plan({
        "plan_schema_version": INTRADAY_RESEARCH_PLAN_VERSION, "intraday_data_path": str(data.path),
        "data_id": data.data_id, "feature_fields": [feature],
        "split": {"train_end_day": days[train - 1], "validation_end_day": days[train + validation - 1], "test_end_day": days[-1]},
        "walk_forward": {"minimum_train_days": 20, "validation_days": 5, "step_days": 5},
        "strategies": [{"kind": "FEATURE_RULE", "name": "Trend", "signal_field": feature, "comparator": "GT", "threshold": 0.0},
                       {"kind": "FEATURE_RULE", "name": "MeanReversion", "signal_field": feature, "comparator": "LT", "threshold": 0.0},
                       {"kind": "RIDGE", "name": "Ridge", "alpha": 1.0, "threshold": 0.0}],
        "execution": asdict(IntradayExecutionPolicy(commission_bps, slippage_bps)),
    })


def expand_intraday_plan(plan: dict, *, base: Path | None = None, recorded: bool = False):
    """Return the normalized root plan, child comparison plans and axis values."""
    if type(plan) is dict and plan.get("plan_schema_version") in INTRADAY_RESEARCH_PLAN_VERSIONS:
        normalized = normalize_intraday_research_plan(plan, base=base, recorded=recorded)
        return normalized, (normalized,), tuple(() for _ in normalized["strategies"])
    object_fields(plan, {"plan_schema_version", "comparison_plan", "strategy_name", "parameter_axes", "cost_scenarios"}, "intraday diagnostics plan")
    if plan["plan_schema_version"] not in INTRADAY_DIAGNOSTICS_PLAN_VERSIONS:
        raise ValueError("unsupported intraday diagnostics plan version")
    comparison = normalize_intraday_research_plan(plan["comparison_plan"], base=base, recorded=recorded)
    if is_intraday_plan_v2(plan) != is_intraday_plan_v2(comparison):
        raise ValueError("diagnostics and comparison plan versions must agree")
    selected = next((s for s in intraday_strategy_specs(comparison) if s.name == plan["strategy_name"]), None)
    if selected is None:
        raise ValueError("diagnostics must select a declared strategy by name")
    axes = normalize_parameter_axes(selected, plan["parameter_axes"], allow_quadratic=is_intraday_plan_v2(plan))
    costs = plan["cost_scenarios"]
    if type(costs) is not list or not costs:
        raise ValueError("explicit cost scenarios are required")
    if len(costs) * math.prod(len(axis["values"]) for axis in axes) > MAX_DIAGNOSTIC_EVALUATIONS:
        raise ValueError("diagnostics is limited to 64 evaluations")
    variants, combinations = parameter_variants(selected, axes)
    normalized_costs, children, seen = [], [], set()
    for cost in costs:
        object_fields(cost, {"commission_bps", "slippage_bps"}, "cost scenario")
        policy = parse_execution_policy({**comparison["execution"], **cost})
        cost = {key: getattr(policy, key) for key in ("commission_bps", "slippage_bps")}
        pair = tuple(cost.values())
        if pair in seen:
            raise ValueError("cost scenarios must be unique after normalization")
        seen.add(pair)
        normalized_costs.append(cost)
        children.append({**comparison, "strategies": [strategy_plan_fields(s) for s in variants], "execution": asdict(policy)})
    return {"plan_schema_version": plan["plan_schema_version"], "comparison_plan": comparison,
            "strategy_name": selected.name, "parameter_axes": axes, "cost_scenarios": normalized_costs}, tuple(children), combinations


def research_algorithm_versions(plan: dict) -> dict:
    _, children, _ = expand_intraday_plan(plan, recorded=True)
    strategies = intraday_strategy_specs(children[0])
    versions = {"data": INTRADAY_DATA_VERSION,
                "research": INTRADAY_RESEARCH_V2_VERSION if is_intraday_plan_v2(plan) else INTRADAY_RESEARCH_VERSION,
                "walk_forward": INTRADAY_WALK_FORWARD_VERSION, "execution": INTRADAY_EXECUTION_VERSION,
                "cost": INTRADAY_COST_VERSION, "daily_risk": INTRADAY_DAILY_RISK_VERSION, "benchmark": INTRADAY_BENCHMARK_VERSION}
    if any(type(s) in (RidgeStrategy, QuadraticRidgeStrategy) for s in strategies):
        versions["ridge"] = RIDGE_BASELINE_VERSION
    if any(type(s) is QuadraticRidgeStrategy for s in strategies):
        versions["quadratic"] = INTRADAY_QUADRATIC_RIDGE_VERSION
    if any(type(s) is CompositeRuleStrategy for s in strategies):
        versions["composite"] = COMPOSITE_RULE_VERSION
    return versions


def training_rows(report: dict, days: tuple[str, ...], boundary: str):
    """Actual target-end purge; never substitute an observation/nominal horizon."""
    targets = {row["observation_key"]: row for row in report["targets"]}
    ready = tuple(row for row in report["observations"] if row["trading_day"] in days and row["status"] == "READY")
    rows, purged = [], []
    for row in ready:
        target = targets.get(row["observation_key"])
        if target is None or target["status"] != "COMPLETE":
            continue
        if datetime.fromisoformat(target["actual_label_end_time"]) >= datetime.fromisoformat(boundary):
            purged.append(row["observation_key"])
        else:
            rows.append((row, target))
    return tuple(rows), tuple(purged)


def day_partitions(report: dict, split: dict) -> dict:
    days = [s["trading_day"] for s in report["sessions"]]
    if any(value not in days for value in split.values()) or split["test_end_day"] != days[-1]:
        raise ValueError("split endpoints must be declared trading days and cover all data sessions")
    first, second = days.index(split["train_end_day"]) + 1, days.index(split["validation_end_day"]) + 1
    return {"TRAIN": days[:first], "VALIDATION": days[first:second], "TEST": days[second:]}


@dataclass(frozen=True, slots=True)
class _PreparedIntradayResearch:
    data: object
    report: dict
    context: dict
    observations: tuple[dict, ...]
    fold_rows: tuple[tuple, ...]


def _prepare_intraday_research(plan: dict, *, data=None, data_file: str | Path | None = None) -> _PreparedIntradayResearch:
    """Internal verified-data context; shared prices are preflighted before fit.

    A supplied data value must come from this action's verified Q5 loader.
    Public entry points never accept this shortcut from an external caller.
    """
    if data is None:
        data = load_intraday_dataset(data_file if data_file is not None else plan["intraday_data_path"])
    if data.data_id != plan["data_id"]:
        raise ValueError("intraday data identity differs from the research plan; no model was fitted")
    report = data.as_dict()["report"]
    if any(f not in report["feature_names"] for f in plan["feature_fields"]):
        raise ValueError("common Feature projection contains an unavailable Feature")
    partitions = day_partitions(report, plan["split"])
    dev = partitions["TRAIN"] + partitions["VALIDATION"]
    walk = plan["walk_forward"]
    folds, row_groups, evaluated = [], [], []
    for start in range(walk["minimum_train_days"], len(dev) - walk["validation_days"] + 1, walk["step_days"]):
        train_days, val_days = dev[:start], dev[start:start + walk["validation_days"]]
        boundary = next(s["open_time"] for s in report["sessions"] if s["trading_day"] == val_days[0])
        rows, purged = training_rows(report, tuple(train_days), boundary)
        validation = [r for r in report["observations"] if r["status"] == "READY" and r["trading_day"] in val_days]
        if not validation:
            raise ValueError("validation fold has no READY observations")
        fold = {"fold_index": len(folds), "training_days": train_days, "validation_days": val_days,
                "training_boundary": boundary, "training_keys": [row[0]["observation_key"] for row in rows],
                "purged_keys": list(purged), "validation_keys": [r["observation_key"] for r in validation]}
        fold["fold_id"] = digest(fold)
        folds.append(fold)
        row_groups.append(rows)
        evaluated.extend(val_days)
    if not folds:
        raise ValueError("development days cannot form one complete walk-forward validation fold")
    observations = tuple(r for r in report["observations"] if r["status"] == "READY" and r["trading_day"] in evaluated)
    sessions, prices = execution_views(report, trading_days=tuple(evaluated))
    _inputs(sessions, prices, (), report["interval"], parse_execution_policy(plan["execution"]))
    context = {"version": INTRADAY_WALK_FORWARD_VERSION, "data_id": data.data_id, "symbol": report["symbol"],
               "interval": report["interval"], "feature_fields": plan["feature_fields"],
               "target_horizon_bars": data.as_dict()["plan"]["target_horizon_bars"],
               "split": partitions, "folds": folds, "evaluated_days": evaluated,
               "unevaluated_development_days": [day for day in dev if day not in evaluated],
               "validation_keys": [r["observation_key"] for r in observations],
               "held_out_test_observation_count": sum(r["status"] == "READY" and r["trading_day"] in partitions["TEST"] for r in report["observations"])}
    context["context_id"] = digest(context)
    return _PreparedIntradayResearch(data, report, context, observations, tuple(row_groups))


def fit_ridge_rows(rows, observations, features, alpha, *, boundary: str) -> tuple[dict, tuple[float, ...]]:
    X = tuple(tuple(row["features"][f] for f in features) for row, target in rows)
    y = tuple(target["value"] for row, target in rows)
    intercept, coefficients, means, scales = _fit(X, y, alpha)
    predictions = _predict(tuple(tuple(row["features"][f] for f in features) for row in observations), intercept, coefficients)
    model = {"version": RIDGE_BASELINE_VERSION, "alpha": alpha, "feature_fields": list(features),
             "training_keys": [row["observation_key"] for row, _ in rows], "training_boundary": boundary,
             "intercept": intercept, "coefficients": list(coefficients), "means": list(means), "scales": list(scales)}
    model["model_id"] = digest(model)
    return model, predictions


def prediction_metrics(predictions: list[dict], report: dict) -> dict:
    targets = {r["observation_key"]: r for r in report["targets"] if r["status"] == "COMPLETE"}
    paired = [(targets[r["observation_key"]]["value"], r["score"]) for r in predictions if r["observation_key"] in targets]
    values = _metrics(tuple(p[0] for p in paired), tuple(p[1] for p in paired)) if paired else (None, None, None)
    return {"prediction_count": len(predictions), "complete_target_count": len(paired),
            "mae": values[0], "rmse": values[1], "r2": values[2],
            "unavailable_reason": None if paired else "NO_COMPLETE_TARGETS"}


def candidate_predictions(prepared: _PreparedIntradayResearch, strategy, cache: dict):
    features = prepared.context["feature_fields"]
    if type(strategy) not in (RidgeStrategy, QuadraticRidgeStrategy):
        return list(rule_decisions(list(prepared.observations), strategy, feature_names=tuple(features))), [], None
    models, predictions = [], []
    for fold, rows in zip(prepared.context["folds"], prepared.fold_rows, strict=True):
        observations = tuple(r for r in prepared.observations if r["trading_day"] in fold["validation_days"])
        key = (fold["fold_index"], type(strategy).__name__, strategy.alpha)
        if key not in cache:
            fit = fit_quadratic_rows if type(strategy) is QuadraticRidgeStrategy else fit_ridge_rows
            cache[key] = fit(rows, observations, features, strategy.alpha, boundary=fold["training_boundary"])
        model, scores = cache[key]
        models.append({"fold_id": fold["fold_id"], "model": model})
        predictions.extend({**{k: row[k] for k in ("observation_key", "trading_day", "slot", "decision_time")},
                            "score": score, "target": "LONG" if score > strategy.threshold else "FLAT"}
                           for row, score in zip(observations, scores, strict=True))
    return predictions, models, prediction_metrics(predictions, prepared.report)


def intraday_daily_risk(execution: dict) -> dict:
    returns = [row["return"] for row in execution["daily"]]
    mean = statistics.mean(returns) if returns else None
    deviation = statistics.stdev(returns) if len(returns) >= 2 else None
    reason = "INSUFFICIENT_DAILY_RETURNS" if deviation is None else "ZERO_VOLATILITY" if deviation <= ZERO_VOLATILITY_TOLERANCE else None
    volatility = None if deviation is None else 0.0 if reason else deviation * math.sqrt(252)
    sharpe = None if reason else mean / deviation * math.sqrt(252)
    result = {"version": INTRADAY_DAILY_RISK_VERSION, "execution_id": execution["execution_id"],
              "annualization_factor": 252, "risk_free_rate": 0.0, "ddof": 1,
              "zero_volatility_tolerance": ZERO_VOLATILITY_TOLERANCE, "return_count": len(returns),
              "mean_daily_return": mean, "annualized_volatility": volatility, "sharpe_ratio": sharpe,
              "unavailable_reason": reason}
    result["risk_id"] = digest(result)
    return result


def benchmark_execution(report: dict, days: tuple[str, ...], policy) -> dict:
    sessions, prices = execution_views(report, trading_days=days)
    policy = replace(policy, max_hold_bars=max(s["bar_count"] for s in sessions))
    _, calendars, _, _ = _inputs(sessions, prices, (), report["interval"], policy)
    decisions = []
    for day in days:
        cal = calendars[day]
        for row in report["observations"]:
            if row["trading_day"] != day or row["status"] != "READY":
                continue
            instant = datetime.fromisoformat(row["decision_time"])
            if cal["first"] <= instant < cal["stop"] and row["slot"] + 1 < cal["flatten_slot"]:
                decisions.append({**{k: row[k] for k in ("observation_key", "trading_day", "slot", "decision_time")}, "target": "LONG"})
                break
    execution = run_intraday_execution(sessions=sessions, prices=prices, decisions=tuple(decisions), interval=report["interval"], policy=policy)
    return {"version": INTRADAY_BENCHMARK_VERSION, "definition": dict(BENCHMARK_DEFINITION),
            "execution": execution, "risk": intraday_daily_risk(execution)}


def fold_cash_contributions(context: dict, execution: dict) -> list[dict]:
    result = [{"fold_id": fold["fold_id"], "fold_index": fold["fold_index"], "validation_days": fold["validation_days"],
               "trade_count": sum(d["trade_count"] for d in execution["daily"] if d["trading_day"] in fold["validation_days"]),
               "cash_contribution": math.fsum(d["cash_close"] - d["cash_open"] for d in execution["daily"] if d["trading_day"] in fold["validation_days"])}
              for fold in context["folds"]]
    if not math.isclose(1 + math.fsum(f["cash_contribution"] for f in result), execution["metrics"]["final_cash"], rel_tol=1e-11, abs_tol=1e-12):
        raise ValueError("fold contributions do not reconcile with the continuous cash account")
    return result


def _evaluate_intraday_research(normalized: dict, children: tuple[dict, ...], axis_values: tuple,
                                prepared: _PreparedIntradayResearch, *, fit_cache: dict | None = None) -> dict:
    """Pure evaluation of an already verified context, shared across all costs."""
    strategies = intraday_strategy_specs(children[0])
    cache = {} if fit_cache is None else fit_cache
    candidates = [candidate_predictions(prepared, strategy, cache) for strategy in strategies]
    days = tuple(prepared.context["evaluated_days"])
    sessions, prices = execution_views(prepared.report, trading_days=days)
    groups = []
    for cost_index, child in enumerate(children):
        policy = parse_execution_policy(child["execution"])
        results = []
        for index, (strategy, (predictions, models, errors)) in enumerate(zip(strategies, candidates, strict=True)):
            execution = run_intraday_execution(sessions=sessions, prices=prices, decisions=tuple(predictions), interval=prepared.report["interval"], policy=policy)
            candidate = {"candidate_index": index, "strategy": strategy_plan_fields(strategy), "axis_values": list(axis_values[index]),
                         "context_id": prepared.context["context_id"], "predictions": predictions, "fold_models": models,
                         "prediction_metrics": errors, "execution": execution, "risk": intraday_daily_risk(execution),
                         "fold_contributions": fold_cash_contributions(prepared.context, execution),
                         "return_change_from_first_cost": 0.0 if cost_index == 0 else
                         execution["metrics"]["total_return"] - groups[0]["results"][index]["execution"]["metrics"]["total_return"]}
            candidate["candidate_id"] = digest(candidate)
            results.append(candidate)
        groups.append({"cost_index": cost_index, "execution_policy": asdict(policy), "results": results,
                       "benchmark": benchmark_execution(prepared.report, days, policy)})
    result = {"result_schema_version": INTRADAY_RESEARCH_RESULT_V2_VERSION if is_intraday_plan_v2(normalized) else INTRADAY_RESEARCH_RESULT_VERSION,
              "version": INTRADAY_RESEARCH_V2_VERSION if is_intraday_plan_v2(normalized) else INTRADAY_RESEARCH_VERSION,
              "status": "SUCCESS", "evaluation_scope": "DEVELOPMENT_WALK_FORWARD_ONLY", "data_id": prepared.data.data_id,
              "plan_sha256": digest(normalized), "context": prepared.context, "groups": groups,
              "evaluation_count": len(groups) * len(strategies)}
    result["research_id"] = digest(result)
    return result


def run_intraday_research(plan: dict, *, base: Path | None = None) -> dict:
    normalized, children, values = expand_intraday_plan(plan, base=base)
    prepared = _prepare_intraday_research(children[0])
    return _evaluate_intraday_research(normalized, children, values, prepared)
