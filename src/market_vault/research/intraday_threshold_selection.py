"""Fixed-model, four-threshold selection using historical inner Q6 accounts.

Each window fits once. Only its trading threshold is selected, and the
verified ordinary outer models/scores are reused without refitting. The study
is independent of Q25's six-member MSE procedure and never runs TEST.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path

from ..backtest.intraday import _inputs, run_intraday_execution
from . import intraday_research as research
from .intraday_backtest import execution_views, intraday_data_path, parse_execution_policy
from .intraday_data import digest, object_fields
from .intraday_experiment import INTRADAY_EXPERIMENT_VERSIONS, _count
from .intraday_inner_selection import _fit, _locator
from .intraday_models import quadratic_terms
from .strategy_experiment import StrategyExperiment, canonical_json, environment_versions, load_strategy_experiment


INTRADAY_THRESHOLD_SELECTION_VERSION = "market-vault-intraday-threshold-selection-v1"
INTRADAY_THRESHOLD_SELECTION_PLAN_VERSION = "market-vault-intraday-threshold-selection-plan-v1"
INTRADAY_THRESHOLD_SELECTION_RESULT_VERSION = "market-vault-intraday-threshold-selection-result-v1"
THRESHOLDS = (0.0, 0.0005, 0.001, 0.002)
INNER_HOLDOUT_DAYS = 5
MINIMUM_INNER_TRAIN_DAYS = 10
METHOD = {"inner_holdout_days": INNER_HOLDOUT_DAYS, "minimum_inner_train_days": MINIMUM_INNER_TRAIN_DAYS,
    "thresholds": list(THRESHOLDS), "selection_metric": "MAXIMUM_INNER_NET_COMPOUNDED_RETURN",
    "tie_break": "FIRST_DECLARED", "decision": "SCORE_STRICTLY_GREATER_THAN_THRESHOLD",
    "recipe": "FIXED_SAVED_REPRESENTATION_ALPHA_FEATURES", "inner_fit_count": 1,
    "execution_sample": "ALL_READY_FULL_SESSION_PRICE_GRID", "inner_complete_score_labels_required": False,
    "outer_models": "VERIFIED_ORIGINAL_FIXED_MODELS_AND_SCORES", "final_dev_boundary": "FIRST_TEST_SESSION_OPEN"}
RETURN_BASIS = {"price_basis": "NONE_UNADJUSTED", "split_share_adjustment": "NOT_APPLIED",
    "cash_dividend_accounting": "NOT_APPLIED", "total_return_semantics": "SIMULATED_ACCOUNT_CHANGE",
    "corporate_action_coverage": "UNKNOWN"}
PRICE_FIELDS = ("trading_day", "slot", "event_time", "available_at", "row_version_id", "open", "close")
TARGET_FIELDS = ("observation_key", "trading_day", "actual_label_end_time", "value")


def _equal(actual, expected, label):
    if canonical_json(actual) != canonical_json(expected):
        raise ValueError(f"threshold selection {label} differs")


def normalize_threshold_selection_plan(plan: dict) -> dict:
    object_fields(plan, {"plan_schema_version", "source_experiment", "selection", "intraday_data_path"}, "threshold selection plan")
    if plan["plan_schema_version"] != INTRADAY_THRESHOLD_SELECTION_PLAN_VERSION:
        raise ValueError("unsupported threshold selection plan version")
    source = object_fields(plan["source_experiment"], {"path", "experiment_id"}, "ordinary source reference")
    selected = object_fields(plan["selection"], {"cost_index", "candidate_index", "candidate_id"}, "source candidate")
    _locator(source["path"])
    _locator(plan["intraday_data_path"])
    research._identity(source["experiment_id"], "source experiment ID")
    research._identity(selected["candidate_id"], "source candidate ID")
    for key in ("cost_index", "candidate_index"):
        _count(selected[key], key)
    return deepcopy(plan)


def _selected(source, plan):
    if (source["artifact_schema_version"] not in INTRADAY_EXPERIMENT_VERSIONS
            or source["evaluation_mode"] not in ("INTRADAY_COMPARISON", "INTRADAY_DIAGNOSTICS")):
        raise ValueError("threshold selection requires an ordinary saved DEV experiment")
    if source["experiment_id"] != plan["source_experiment"]["experiment_id"]:
        raise ValueError("source experiment differs from the captured identity")
    cost, index = (plan["selection"][key] for key in ("cost_index", "candidate_index"))
    groups = source["report"]["groups"]
    if cost >= len(groups) or index >= len(groups[cost]["results"]):
        raise ValueError("source cost/candidate index is outside the saved experiment")
    candidate = groups[cost]["results"][index]
    if candidate["candidate_id"] != plan["selection"]["candidate_id"]:
        raise ValueError("candidate differs from the captured identity")
    kind = candidate["strategy"]["kind"]
    if kind not in ("RIDGE", "QUADRATIC_RIDGE"):
        raise ValueError("threshold selection requires a fixed linear or quadratic Ridge candidate")
    if kind == "QUADRATIC_RIDGE":
        quadratic_terms(source["report"]["context"]["feature_fields"])
    return groups[cost], candidate


def threshold_selection_versions(source: dict) -> dict:
    return {**research.research_algorithm_versions(source["plan"]), "threshold_selection": INTRADAY_THRESHOLD_SELECTION_VERSION}


def threshold_predictions(predictions: list[dict], threshold: float) -> list[dict]:
    """Keep every recorded key/score and change only the strict decision."""
    return [{**row, "target": "LONG" if row["score"] > threshold else "FLAT"} for row in predictions]


def _execution_input_status(sessions, prices, interval, policy):
    """Preflight only input coverage/policy after Q5 has passed source admission."""
    try:
        _inputs(tuple(sessions), tuple(prices), (), interval, policy)
    except ValueError as exc:
        # Q5 can be valid while previously unevaluated inner days have gaps or
        # a shorter session that cannot accommodate this saved execution policy.
        # Malformed geometry, clocks, prices and any unexpected kernel failure
        # remain errors rather than being relabelled an unavailable study.
        if str(exc) not in ("incomplete session price flow; execution is invalid",
                            "execution windows do not fit the declared session",
                            "execution windows must precede the rounded forced-flat open"):
            raise
        return {"status": "UNAVAILABLE", "reason": "INNER_EXECUTION_INPUT_UNAVAILABLE", "detail": str(exc)}
    return {"status": "AVAILABLE", "reason": None, "detail": None}


def _window(prepared, history_days, history_rows, history_purged, history_boundary, policy):
    train_days, holdout_days = history_days[:-INNER_HOLDOUT_DAYS], history_days[-INNER_HOLDOUT_DAYS:]
    sessions, prices = execution_views(prepared.report, trading_days=tuple(holdout_days))
    boundary = sessions[0]["open_time"]
    rows = tuple((row, target) for row, target in history_rows if row["trading_day"] in train_days
                 and datetime.fromisoformat(target["actual_label_end_time"]) < datetime.fromisoformat(boundary))
    purged = [row["observation_key"] for row, target in history_rows if row["trading_day"] in train_days
              and datetime.fromisoformat(target["actual_label_end_time"]) >= datetime.fromisoformat(boundary)]
    observations = tuple(row for row in prepared.report["observations"] if row["status"] == "READY"
                         and row["trading_day"] in holdout_days)
    prices = [{key: row[key] for key in PRICE_FIELDS} for row in prices]
    inputs = _execution_input_status(sessions, prices, prepared.report["interval"], policy)
    reason = ("INSUFFICIENT_INNER_HISTORY" if len(holdout_days) != INNER_HOLDOUT_DAYS or len(train_days) < MINIMUM_INNER_TRAIN_DAYS
              else "NO_INNER_TRAINING_ROWS" if not rows else inputs["reason"])
    evidence = {"history_days": list(history_days), "history_boundary": history_boundary,
        "history_training_keys": [row["observation_key"] for row, _ in history_rows], "history_purged_keys": list(history_purged),
        "history_targets": [{"observation_key": row["observation_key"], "trading_day": row["trading_day"],
                             **{key: target[key] for key in ("actual_label_end_time", "value")}} for row, target in history_rows],
        "training_days": list(train_days), "validation_days": list(holdout_days), "training_boundary": boundary,
        "training_keys": [row["observation_key"] for row, _ in rows], "purged_keys": purged,
        "validation_keys": [row["observation_key"] for row in observations],
        "sessions": list(sessions), "prices": prices, "execution_input": inputs, "unavailable_reason": reason,
        "model": None, "predictions": [], "family_results": [], "selected_index": None, "selected_recipe": None}
    return evidence, rows, observations


def _threshold_accounts(predictions, sessions, prices, interval, policy):
    """Four independent normalized accounts; no model fitting or target scoring."""
    family = [{"candidate_index": index, "threshold": threshold,
               "execution": run_intraday_execution(sessions=tuple(sessions), prices=tuple(prices),
                   decisions=tuple(threshold_predictions(predictions, threshold)), interval=interval, policy=policy)}
              for index, threshold in enumerate(THRESHOLDS)]
    selected = max(range(len(THRESHOLDS)), key=lambda index: family[index]["execution"]["metrics"]["total_return"])
    return family, selected


def _select(window, features, source_strategy, interval, policy):
    evidence, rows, observations = window
    model, predictions = _fit(rows, observations, features, source_strategy, evidence["training_boundary"])
    family, chosen = _threshold_accounts(predictions, evidence["sessions"], evidence["prices"], interval, policy)
    evidence.update(model=model, predictions=predictions, family_results=family, selected_index=chosen,
                    selected_recipe={**source_strategy, "threshold": THRESHOLDS[chosen]})


def _evaluate(source, plan, *, data_file=None, data=None):
    """Replay may reuse Q5 verified by this same action; no public data bypass."""
    group, reference = _selected(source, plan)
    if source["algorithm_versions"] != research.research_algorithm_versions(source["plan"]):
        raise ValueError("recorded source algorithms differ; no Q5 data was read or model fitted")
    normalized, children, axes = research.expand_intraday_plan(source["plan"], recorded=True)
    prepared = research._prepare_intraday_research(children[0], data=data, data_file=data_file or plan["intraday_data_path"])
    _equal(prepared.context, source["report"]["context"], "source common context")
    original = research._evaluate_intraday_research(normalized, children, axes, prepared)
    _equal(original, source["report"], "complete ordinary source reconstruction")
    context, policy = prepared.context, parse_execution_policy(group["execution_policy"])
    windows = [_window(prepared, fold["training_days"], rows, fold["purged_keys"], fold["training_boundary"], policy)
               for fold, rows in zip(context["folds"], prepared.fold_rows, strict=True)]
    dev_days = context["split"]["TRAIN"] + context["split"]["VALIDATION"]
    final_boundary = next(row["open_time"] for row in prepared.report["sessions"]
                          if row["trading_day"] == context["split"]["TEST"][0])
    final_rows, final_purged = research.training_rows(prepared.report, tuple(dev_days), final_boundary)
    final = _window(prepared, dev_days, final_rows, final_purged, final_boundary, policy)
    reasons = [{"scope": "OUTER_FOLD", "fold_index": index, "reason": window[0]["unavailable_reason"]}
               for index, window in enumerate(windows) if window[0]["unavailable_reason"]]
    if final[0]["unavailable_reason"]:
        reasons.append({"scope": "FINAL_DEV", "fold_index": None, "reason": final[0]["unavailable_reason"]})
    outer = [{"fold_id": fold["fold_id"], "inner": window[0], "application": None}
             for fold, window in zip(context["folds"], windows, strict=True)]
    account = None
    if not reasons:
        predictions = []
        for fold, model, window, record in zip(context["folds"], reference["fold_models"], windows, outer, strict=True):
            _select(window, context["feature_fields"], reference["strategy"], context["interval"], policy)
            recipe = window[0]["selected_recipe"]
            values = threshold_predictions([row for row in reference["predictions"]
                                            if row["trading_day"] in fold["validation_days"]], recipe["threshold"])
            record["application"] = {"strategy": deepcopy(recipe), "model": deepcopy(model["model"]), "predictions": values,
                                      "prediction_metrics": research.prediction_metrics(values, prepared.report)}
            predictions.extend(values)
        _select(final, context["feature_fields"], reference["strategy"], context["interval"], policy)
        sessions, prices = execution_views(prepared.report, trading_days=tuple(context["evaluated_days"]))
        execution = run_intraday_execution(sessions=sessions, prices=prices, decisions=tuple(predictions),
                                          interval=context["interval"], policy=policy)
        account = {"predictions": predictions, "prediction_metrics": deepcopy(reference["prediction_metrics"]),
                   "execution": execution, "risk": research.intraday_daily_risk(execution),
                   "fold_contributions": research.fold_cash_contributions(context, execution)}
    report = {"result_schema_version": INTRADAY_THRESHOLD_SELECTION_RESULT_VERSION,
        "version": INTRADAY_THRESHOLD_SELECTION_VERSION, "status": "UNAVAILABLE" if reasons else "AVAILABLE",
        "evaluation_scope": "DEVELOPMENT_INNER_ECONOMIC_THRESHOLD_SELECTION_ONLY", "data_id": source["dataset_id"],
        "plan_sha256": digest(plan), "method": deepcopy(METHOD), "source_experiment": deepcopy(source),
        "source_reconstruction": "COMPLETE_REPORT_RECONSTRUCTED", "fixed_reference": deepcopy(plan["selection"]),
        "benchmark": deepcopy(group["benchmark"]), "outer_folds": outer, "final_dev": final[0],
        "selected_account": account, "unavailable_reasons": reasons, "return_basis": deepcopy(RETURN_BASIS)}
    report["threshold_selection_id"] = digest(report)
    return report


def run_intraday_threshold_selection(source_experiment_path: str | Path, *, expected_experiment_id: str,
                                    cost_index: int, candidate_index: int, expected_candidate_id: str,
                                    intraday_data_file: str | Path | None = None,
                                    name: str = "", notes: str = "") -> StrategyExperiment:
    """Select the fixed four-threshold rule from one explicit saved DEV recipe."""
    if type(name) is not str or type(notes) is not str:
        raise ValueError("experiment name and notes must be strings")
    path = intraday_data_path(str(source_experiment_path))
    source = load_strategy_experiment(path).as_dict()
    comparison = source["plan"].get("comparison_plan", source["plan"])
    plan = normalize_threshold_selection_plan({"plan_schema_version": INTRADAY_THRESHOLD_SELECTION_PLAN_VERSION,
        "source_experiment": {"path": str(path), "experiment_id": expected_experiment_id},
        "selection": {"cost_index": cost_index, "candidate_index": candidate_index, "candidate_id": expected_candidate_id},
        "intraday_data_path": str(intraday_data_path(str(intraday_data_file))) if intraday_data_file is not None
                              else comparison.get("intraday_data_path", "")})
    report = _evaluate(source, plan)
    root = {"artifact_schema_version": INTRADAY_THRESHOLD_SELECTION_VERSION, "evaluation_mode": "INTRADAY_THRESHOLD_SELECTION",
        "dataset_id": source["dataset_id"], "plan": plan, "report": report, "algorithm_versions": threshold_selection_versions(source),
        "environment": environment_versions(), "name": name, "notes": notes}
    root["experiment_id"] = digest(root)
    return StrategyExperiment(canonical_json(root))


def replay_intraday_threshold_selection(snapshot: StrategyExperiment, *, intraday_data_file: str | Path | None = None,
                                        source_experiment_file: str | Path | None = None) -> dict:
    """Reconstruct the complete ordinary source and study with one verified Q5."""
    if type(snapshot) is not StrategyExperiment:
        raise ValueError("an immutable threshold-selection study is required")
    root = snapshot.as_dict()
    if root["artifact_schema_version"] != INTRADAY_THRESHOLD_SELECTION_VERSION:
        raise ValueError("a threshold-selection study is required")
    source = root["report"]["source_experiment"]
    if root["algorithm_versions"] != threshold_selection_versions(source):
        raise ValueError("recorded threshold-selection algorithms differ; no Q5 was read or model fitted")
    if source_experiment_file is not None:
        _equal(load_strategy_experiment(source_experiment_file).as_dict(), source, "explicit ordinary source")
    actual = _evaluate(source, root["plan"], data_file=intraday_data_file)
    _equal(actual, root["report"], "complete replay report")
    checksum = digest(actual)
    return {"experiment_id": root["experiment_id"], "data_id": root["dataset_id"],
        "threshold_selection_id": actual["threshold_selection_id"], "report_matches": True,
        "expected_report_sha256": checksum, "actual_report_sha256": checksum}
