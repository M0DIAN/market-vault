"""One fixed joint model/threshold economic procedure on original DEV folds.

Each historical inner window has six fits and 24 independent Q6 accounts.
Only its winning recipe is refitted on the complete purged outer TRAIN.
The final DEV window selects a recipe; it does not fit or evaluate TEST.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from ..backtest.intraday import run_intraday_execution
from . import intraday_research as research
from . import intraday_threshold_selection as threshold
from .intraday_backtest import execution_views, intraday_data_path, parse_execution_policy
from .intraday_data import digest, object_fields
from .intraday_experiment import INTRADAY_EXPERIMENT_VERSIONS, _count
from .intraday_inner_selection import FAMILY as MODEL_FAMILY, _fit, _locator, _recipe
from .intraday_models import INTRADAY_QUADRATIC_RIDGE_VERSION, quadratic_terms
from .strategy_experiment import StrategyExperiment, canonical_json, environment_versions, load_strategy_experiment


INTRADAY_JOINT_SELECTION_VERSION = "market-vault-intraday-joint-selection-v1"
INTRADAY_JOINT_SELECTION_PLAN_VERSION = "market-vault-intraday-joint-selection-plan-v1"
INTRADAY_JOINT_SELECTION_RESULT_VERSION = "market-vault-intraday-joint-selection-result-v1"
THRESHOLDS = threshold.THRESHOLDS
INNER_HOLDOUT_DAYS = threshold.INNER_HOLDOUT_DAYS
MINIMUM_INNER_TRAIN_DAYS = threshold.MINIMUM_INNER_TRAIN_DAYS
FAMILY = tuple({**model, "threshold": value} for model in MODEL_FAMILY for value in THRESHOLDS)
METHOD = {"inner_holdout_days": INNER_HOLDOUT_DAYS, "minimum_inner_train_days": MINIMUM_INNER_TRAIN_DAYS,
    "model_family": list(MODEL_FAMILY), "thresholds": list(THRESHOLDS), "family": list(FAMILY),
    "family_order": "MODEL_OUTER_THRESHOLD_INNER", "selection_metric": "MAXIMUM_INNER_NET_COMPOUNDED_RETURN",
    "tie_break": "FIRST_DECLARED", "decision": "SCORE_STRICTLY_GREATER_THAN_THRESHOLD",
    "inner_fit_count": len(MODEL_FAMILY), "inner_account_count": len(FAMILY),
    "execution_sample": "ALL_READY_FULL_SESSION_PRICE_GRID", "inner_complete_score_labels_required": False,
    "training_label_availability": "ACTUAL_LABEL_END_STRICTLY_BEFORE_TRAINING_BOUNDARY",
    "outer_models": "WINNER_REFIT_ON_COMPLETE_PURGED_OUTER_TRAIN",
    "final_dev_boundary": "FIRST_TEST_SESSION_OPEN"}
RETURN_BASIS = threshold.RETURN_BASIS


def _equal(actual, expected, label):
    if canonical_json(actual) != canonical_json(expected):
        raise ValueError(f"joint selection {label} differs")


def normalize_joint_selection_plan(plan: dict) -> dict:
    object_fields(plan, {"plan_schema_version", "source_experiment", "selection", "intraday_data_path"}, "joint selection plan")
    if plan["plan_schema_version"] != INTRADAY_JOINT_SELECTION_PLAN_VERSION:
        raise ValueError("unsupported joint selection plan version")
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
        raise ValueError("joint selection requires an ordinary saved DEV experiment")
    if source["experiment_id"] != plan["source_experiment"]["experiment_id"]:
        raise ValueError("source experiment differs from the captured identity")
    cost, index = (plan["selection"][key] for key in ("cost_index", "candidate_index"))
    groups = source["report"]["groups"]
    if cost >= len(groups) or index >= len(groups[cost]["results"]):
        raise ValueError("source cost/candidate index is outside the saved experiment")
    candidate = groups[cost]["results"][index]
    if candidate["candidate_id"] != plan["selection"]["candidate_id"]:
        raise ValueError("candidate differs from the captured identity")
    if candidate["strategy"]["kind"] not in ("RIDGE", "QUADRATIC_RIDGE"):
        raise ValueError("joint selection requires a linear or quadratic Ridge reference")
    # All sources enter the same family, which includes quadratic fits.
    quadratic_terms(source["report"]["context"]["feature_fields"])
    return groups[cost], candidate


def joint_selection_versions(source: dict) -> dict:
    return {**research.research_algorithm_versions(source["plan"]),
        "quadratic": INTRADAY_QUADRATIC_RIDGE_VERSION, "joint_selection": INTRADAY_JOINT_SELECTION_VERSION}


def _window(prepared, history_days, history_rows, history_purged, history_boundary, policy):
    # The economic window admits all READY execution rows without requiring
    # COMPLETE inner scoring targets. Reuse its unchanged history/input rules.
    evidence, rows, observations = threshold._window(prepared, history_days, history_rows,
        history_purged, history_boundary, policy)
    evidence.pop("model")
    evidence.pop("predictions")
    evidence["models"] = []
    return evidence, rows, observations


def _select(window, features, source_strategy, interval, policy):
    evidence, rows, observations = window
    models, family = [], []
    for model_index, member in enumerate(MODEL_FAMILY):
        recipe = _recipe(member, source_strategy)
        model, predictions = _fit(rows, observations, features, recipe, evidence["training_boundary"])
        models.append({"model_index": model_index, "strategy": recipe, "model": model, "predictions": predictions})
        for threshold_index, value in enumerate(THRESHOLDS):
            actual_recipe = {**recipe, "threshold": value}
            execution = run_intraday_execution(sessions=tuple(evidence["sessions"]), prices=tuple(evidence["prices"]),
                decisions=tuple(threshold.threshold_predictions(predictions, value)), interval=interval, policy=policy)
            family.append({"candidate_index": len(family), "model_index": model_index,
                "threshold_index": threshold_index, "strategy": actual_recipe, "execution": execution})
    chosen = max(range(len(FAMILY)), key=lambda index: family[index]["execution"]["metrics"]["total_return"])
    evidence.update(models=models, family_results=family, selected_index=chosen,
        selected_recipe=deepcopy(family[chosen]["strategy"]))


def _evaluate(source, plan, *, data_file=None, data=None):
    """One Q5 admission verifies the full source and complete new procedure."""
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
    outer = [{"fold_id": fold["fold_id"], "inner": window[0], "refit": None}
             for fold, window in zip(context["folds"], windows, strict=True)]
    account = None
    if not reasons:
        predictions = []
        for fold, rows, window, record in zip(context["folds"], prepared.fold_rows, windows, outer, strict=True):
            _select(window, context["feature_fields"], reference["strategy"], context["interval"], policy)
            observations = tuple(row for row in prepared.observations if row["trading_day"] in fold["validation_days"])
            recipe = window[0]["selected_recipe"]
            model, values = _fit(rows, observations, context["feature_fields"], recipe, fold["training_boundary"])
            record["refit"] = {"strategy": deepcopy(recipe), "model": model, "predictions": values,
                "prediction_metrics": research.prediction_metrics(values, prepared.report)}
            predictions.extend(values)
        _select(final, context["feature_fields"], reference["strategy"], context["interval"], policy)
        sessions, prices = execution_views(prepared.report, trading_days=tuple(context["evaluated_days"]))
        execution = run_intraday_execution(sessions=sessions, prices=prices, decisions=tuple(predictions),
            interval=context["interval"], policy=policy)
        account = {"predictions": predictions, "prediction_metrics": research.prediction_metrics(predictions, prepared.report),
            "execution": execution, "risk": research.intraday_daily_risk(execution),
            "fold_contributions": research.fold_cash_contributions(context, execution)}
    report = {"result_schema_version": INTRADAY_JOINT_SELECTION_RESULT_VERSION,
        "version": INTRADAY_JOINT_SELECTION_VERSION, "status": "UNAVAILABLE" if reasons else "AVAILABLE",
        "evaluation_scope": "DEVELOPMENT_INNER_JOINT_ECONOMIC_SELECTION_ONLY", "data_id": source["dataset_id"],
        "plan_sha256": digest(plan), "method": deepcopy(METHOD), "source_experiment": deepcopy(source),
        "source_reconstruction": "COMPLETE_REPORT_RECONSTRUCTED", "fixed_reference": deepcopy(plan["selection"]),
        "benchmark": deepcopy(group["benchmark"]), "outer_folds": outer, "final_dev": final[0],
        "selected_account": account, "unavailable_reasons": reasons, "return_basis": deepcopy(RETURN_BASIS)}
    report["joint_selection_id"] = digest(report)
    return report


def run_intraday_joint_selection(source_experiment_path: str | Path, *, expected_experiment_id: str,
                                cost_index: int, candidate_index: int, expected_candidate_id: str,
                                intraday_data_file: str | Path | None = None,
                                name: str = "", notes: str = "") -> StrategyExperiment:
    """Evaluate the fixed 24-member economic rule from an explicit DEV source."""
    if type(name) is not str or type(notes) is not str:
        raise ValueError("experiment name and notes must be strings")
    path = intraday_data_path(str(source_experiment_path))
    source = load_strategy_experiment(path).as_dict()
    comparison = source["plan"].get("comparison_plan", source["plan"])
    plan = normalize_joint_selection_plan({"plan_schema_version": INTRADAY_JOINT_SELECTION_PLAN_VERSION,
        "source_experiment": {"path": str(path), "experiment_id": expected_experiment_id},
        "selection": {"cost_index": cost_index, "candidate_index": candidate_index, "candidate_id": expected_candidate_id},
        "intraday_data_path": str(intraday_data_path(str(intraday_data_file))) if intraday_data_file is not None
                              else comparison.get("intraday_data_path", "")})
    report = _evaluate(source, plan)
    root = {"artifact_schema_version": INTRADAY_JOINT_SELECTION_VERSION, "evaluation_mode": "INTRADAY_JOINT_SELECTION",
        "dataset_id": source["dataset_id"], "plan": plan, "report": report, "algorithm_versions": joint_selection_versions(source),
        "environment": environment_versions(), "name": name, "notes": notes}
    root["experiment_id"] = digest(root)
    return StrategyExperiment(canonical_json(root))


def replay_intraday_joint_selection(snapshot: StrategyExperiment, *, intraday_data_file: str | Path | None = None,
                                   source_experiment_file: str | Path | None = None) -> dict:
    """Reconstruct the embedded ordinary source and study using verified Q5."""
    if type(snapshot) is not StrategyExperiment:
        raise ValueError("an immutable joint-selection study is required")
    root = snapshot.as_dict()
    if root["artifact_schema_version"] != INTRADAY_JOINT_SELECTION_VERSION:
        raise ValueError("a joint-selection study is required")
    source = root["report"]["source_experiment"]
    if root["algorithm_versions"] != joint_selection_versions(source):
        raise ValueError("recorded joint-selection algorithms differ; no Q5 was read or model fitted")
    if source_experiment_file is not None:
        _equal(load_strategy_experiment(source_experiment_file).as_dict(), source, "explicit ordinary source")
    actual = _evaluate(source, root["plan"], data_file=intraday_data_file)
    _equal(actual, root["report"], "complete replay report")
    checksum = digest(actual)
    return {"experiment_id": root["experiment_id"], "data_id": root["dataset_id"],
        "joint_selection_id": actual["joint_selection_id"], "report_matches": True,
        "expected_report_sha256": checksum, "actual_report_sha256": checksum}
