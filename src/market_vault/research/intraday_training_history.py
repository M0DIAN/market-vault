"""Fixed-recipe DEV sensitivity to expanding, ten-day and twenty-day history.

One verified Q5 read supplies the source reconstruction and all refits. The
selected saved candidate and benchmark are reproduced before comparisons are
returned. This descriptive report neither chooses a window nor creates a
fixed-strategy experiment eligible for Freeze / TEST.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from . import intraday_research as research
from .intraday_backtest import execution_views, parse_execution_policy
from .intraday_data import digest
from .intraday_experiment import INTRADAY_EXPERIMENT_VERSIONS
from .intraday_prediction_quality import _data_override, _index, _metric, _prediction_metrics
from .intraday_return_uncertainty import _sample_coverage
from .strategy_experiment import StrategyExperiment, canonical_json


INTRADAY_TRAINING_HISTORY_VERSION = "market-vault-intraday-training-history-v1"
HISTORY_VARIANTS = (("EXPANDING", None), ("TRAILING_10_DAYS", 10), ("TRAILING_20_DAYS", 20))


def _equal(actual, expected, label):
    if canonical_json(actual) != canonical_json(expected):
        raise ValueError(f"selected training-history source reconstruction differs: {label}")


def _quality(predictions, report):
    targets = {row["observation_key"]: row for row in report["targets"] if row["status"] == "COMPLETE"}
    pairs = [(targets[row["observation_key"]]["value"], row["score"])
             for row in predictions if row["observation_key"] in targets]
    return _prediction_metrics(tuple(row[0] for row in pairs), tuple(row[1] for row in pairs))


def _history_variant(prepared, strategy, policy, *, variant, window_days, cache):
    """Evaluate one complete original sample, or return no partial account."""
    context, report = prepared.context, prepared.report
    folds, row_groups, reasons = [], [], []
    for original in context["folds"]:
        history = original["training_days"]
        days = list(history if window_days is None else history[-window_days:])
        rows, purged = research.training_rows(report, tuple(days), original["training_boundary"])
        reason = ("INSUFFICIENT_TRAINING_DAYS" if window_days is not None and len(history) < window_days
                  else "NO_TRAINING_ROWS" if not rows else None)
        folds.append({"fold_index": original["fold_index"], "source_fold_id": original["fold_id"],
            "available_history_days": len(history), "training_days": days,
            "training_boundary": original["training_boundary"],
            "training_keys": [row["observation_key"] for row, _ in rows], "purged_keys": list(purged),
            "validation_days": list(original["validation_days"]), "validation_keys": list(original["validation_keys"]),
            "unavailable_reason": reason, "model": None, "prediction_metrics": None, "prediction_quality": None})
        row_groups.append(rows)
        if reason:
            reasons.append({"fold_index": original["fold_index"], "source_fold_id": original["fold_id"],
                "reason": reason, "required_training_days": window_days,
                "available_history_days": len(history)})
    result = {"variant": variant, "window_days": window_days,
              "status": "UNAVAILABLE" if reasons else "AVAILABLE", "unavailable_reasons": reasons,
              "folds": folds, "account": None, "prediction_error_changes": None}
    if reasons:
        return result
    predictions = []
    observations = {row["observation_key"]: row for row in prepared.observations}
    features = context["feature_fields"]
    for fold, rows in zip(folds, row_groups, strict=True):
        validation = tuple(observations[key] for key in fold["validation_keys"])
        # A cache belongs to this one verified action and fixed recipe. Distinct
        # windows cannot share a fit unless their actual keys and cutoff agree.
        key = (type(strategy).__name__, strategy.alpha, tuple(features), fold["training_boundary"],
               tuple(fold["training_keys"]), tuple(fold["validation_keys"]))
        if key not in cache:
            fit = research.fit_quadratic_rows if type(strategy) is research.QuadraticRidgeStrategy else research.fit_ridge_rows
            cache[key] = fit(rows, validation, features, strategy.alpha, boundary=fold["training_boundary"])
        model, scores = cache[key]
        values = [{**{key: row[key] for key in ("observation_key", "trading_day", "slot", "decision_time")},
                   "score": score, "target": "LONG" if score > strategy.threshold else "FLAT"}
                  for row, score in zip(validation, scores, strict=True)]
        fold.update(model=deepcopy(model), prediction_metrics=research.prediction_metrics(values, report),
                    prediction_quality=_quality(values, report))
        predictions.extend(values)
    _equal([row["observation_key"] for row in predictions], context["validation_keys"], "variant READY keys")
    sessions, prices = execution_views(report, trading_days=tuple(context["evaluated_days"]))
    execution = research.run_intraday_execution(sessions=sessions, prices=prices, decisions=tuple(predictions),
        interval=context["interval"], policy=policy)
    result["account"] = {"predictions": predictions, "prediction_metrics": research.prediction_metrics(predictions, report),
        "prediction_quality": _quality(predictions, report), "execution": execution,
        "risk": research.intraday_daily_risk(execution), "fold_contributions": research.fold_cash_contributions(context, execution)}
    return result


def _error_changes(account, baseline):
    changes = {}
    for key, unit in (("mse", "SQUARED_RATIO"), ("mae", "RATIO"), ("rmse", "RATIO")):
        current, original = account["prediction_quality"][key], baseline["prediction_quality"][key]
        reason = current["unavailable_reason"] or original["unavailable_reason"]
        changes[key] = _metric(None if reason else current["value"] - original["value"], unit=unit, reason=reason)
    return changes


def analyze_intraday_training_history(snapshot: StrategyExperiment, *, cost_index: int = 0,
                                      candidate_index: int = 0,
                                      intraday_data_file: str | Path | None = None) -> dict:
    """Compare three declared histories for one source-verified saved DEV recipe."""
    _index(cost_index, "cost_index")
    _index(candidate_index, "candidate_index")
    locator = _data_override(intraday_data_file)
    if type(snapshot) is not StrategyExperiment:
        raise ValueError("an immutable StrategyExperiment is required")
    root = snapshot.as_dict()
    if (root["artifact_schema_version"] not in INTRADAY_EXPERIMENT_VERSIONS
            or root["evaluation_mode"] not in ("INTRADAY_COMPARISON", "INTRADAY_DIAGNOSTICS")):
        raise ValueError("training history requires an ordinary saved DEV experiment")
    if root["algorithm_versions"] != research.research_algorithm_versions(root["plan"]):
        raise ValueError("recorded intraday algorithms differ; no Q5 data was read or model fitted")
    groups = root["report"]["groups"]
    if cost_index >= len(groups) or candidate_index >= len(groups[cost_index]["results"]):
        raise ValueError("selected cost/candidate index is outside the saved experiment")
    group = groups[cost_index]
    candidate = group["results"][candidate_index]
    if candidate["strategy"]["kind"] not in ("RIDGE", "QUADRATIC_RIDGE"):
        raise ValueError("training history requires a selected linear or quadratic Ridge")
    _, children, _ = research.expand_intraday_plan(root["plan"], recorded=True)
    child = children[cost_index]
    strategy = research.intraday_strategy_specs(child)[candidate_index]
    prepared = research._prepare_intraday_research(child, data_file=locator)
    _equal(prepared.context, root["report"]["context"], "complete context")
    policy = parse_execution_policy(group["execution_policy"])
    cache = {}
    baseline = _history_variant(prepared, strategy, policy, variant="EXPANDING", window_days=None, cache=cache)
    if baseline["status"] != "AVAILABLE":
        raise ValueError("selected expanding source has no complete training sample")
    _equal([{"fold_id": fold["source_fold_id"], "model": fold["model"]} for fold in baseline["folds"]],
           candidate["fold_models"], "fold models")
    for key in ("predictions", "prediction_metrics", "execution", "risk", "fold_contributions"):
        _equal(baseline["account"][key], candidate[key], key)
    benchmark = research.benchmark_execution(prepared.report, tuple(prepared.context["evaluated_days"]), policy)
    _equal(benchmark, group["benchmark"], "complete benchmark")
    variants = [baseline] + [_history_variant(prepared, strategy, policy, variant=name, window_days=days, cache=cache)
                             for name, days in HISTORY_VARIANTS[1:]]
    for variant in variants:
        if variant["account"] is not None:
            variant["prediction_error_changes"] = _error_changes(variant["account"], baseline["account"])
    context = prepared.context
    counts = baseline["account"]["prediction_metrics"]
    result = {"version": INTRADAY_TRAINING_HISTORY_VERSION,
        "status": "AVAILABLE" if all(row["status"] == "AVAILABLE" for row in variants) else "PARTIAL",
        "evaluation_scope": "DEVELOPMENT_TRAINING_HISTORY_SENSITIVITY_ONLY",
        "experiment_id": root["experiment_id"], "data_id": root["dataset_id"],
        "research_id": root["report"]["research_id"], "candidate_id": candidate["candidate_id"],
        "cost_index": cost_index, "candidate_index": candidate_index, "strategy": deepcopy(candidate["strategy"]),
        "execution_policy": deepcopy(group["execution_policy"]), "context": context,
        "return_basis": {"price_basis": "NONE_UNADJUSTED", "split_share_adjustment": "NOT_APPLIED",
            "cash_dividend_accounting": "NOT_APPLIED", "total_return_semantics": "SIMULATED_ACCOUNT_CHANGE",
            "corporate_action_coverage": "UNKNOWN"},
        "source_locator": {"recorded": child["intraday_data_path"], "used": str(prepared.data.path.resolve()),
                           "override_used": locator is not None},
        "evidence": {"scope": "SOURCE_VERIFIED_SELECTED_CANDIDATE_AND_BENCHMARK", "context_matches": True,
            "fold_models_match": True, "predictions_match": True, "prediction_metrics_match": True,
            "execution_matches": True, "risk_matches": True, "fold_contributions_match": True,
            "benchmark_matches": True, "complete_experiment_replayed": False},
        "method": {"variants": [{"variant": name, "training_days": days} for name, days in HISTORY_VARIANTS],
            "history_unit": "ORIGINAL_FOLD_TRAINING_TRADING_DAYS", "purge": "ACTUAL_LABEL_END_STRICTLY_BEFORE_VALIDATION_OPEN",
            "preprocessing": "VARIANT_PURGED_TRAINING_ROWS_ONLY", "recipe": "FIXED_SAVED_REPRESENTATION_ALPHA_FEATURES_THRESHOLD",
            "sample": "ALL_ORIGINAL_READY_VALIDATION_KEYS", "error_aggregation": "COMPLETE_TARGET_ROW_WEIGHTED",
            "error_change": "VARIANT_MINUS_EXPANDING", "inference": "DESCRIPTIVE_ONLY", "automatic_selection": False,
            "unavailable_policy": "ANY_UNAVAILABLE_FOLD_REMOVES_THE_ENTIRE_VARIANT_ACCOUNT"},
        "sample": {**_sample_coverage(context), "prediction_count": counts["prediction_count"],
            "complete_target_count": counts["complete_target_count"],
            "incomplete_target_count": counts["prediction_count"] - counts["complete_target_count"]},
        "benchmark": benchmark,
        "benchmark_fold_contributions": research.fold_cash_contributions(context, benchmark["execution"]),
        "variants": variants}
    result["training_history_id"] = digest(result)
    return result
