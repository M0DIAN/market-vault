"""One fixed chronological inner selection rule, evaluated on original DEV folds.

This is an independent experiment, not an ordinary fixed Q7 strategy. Its
embedded ordinary source is verified completely with the same Q5 load. No TEST
observation is predicted or fitted; final DEV selection records a recipe only.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import math
from pathlib import Path, PureWindowsPath

from ..backtest.intraday import run_intraday_execution
from . import intraday_research as research
from .intraday_backtest import execution_views, intraday_data_path, parse_execution_policy
from .intraday_data import digest, object_fields
from .intraday_experiment import INTRADAY_EXPERIMENT_VERSIONS
from .intraday_models import INTRADAY_QUADRATIC_RIDGE_VERSION, fit_quadratic_rows, quadratic_terms
from .strategy_experiment import StrategyExperiment, canonical_json, environment_versions, load_strategy_experiment


INTRADAY_INNER_SELECTION_VERSION = "market-vault-intraday-inner-selection-v1"
INTRADAY_INNER_SELECTION_PLAN_VERSION = "market-vault-intraday-inner-selection-plan-v1"
INTRADAY_INNER_SELECTION_RESULT_VERSION = "market-vault-intraday-inner-selection-result-v1"
INNER_HOLDOUT_DAYS = 5
MINIMUM_INNER_TRAIN_DAYS = 10
FAMILY = tuple({"kind": kind, "alpha": alpha} for kind in ("RIDGE", "QUADRATIC_RIDGE") for alpha in (0.1, 1.0, 10.0))
METHOD = {"inner_holdout_days": INNER_HOLDOUT_DAYS, "minimum_inner_train_days": MINIMUM_INNER_TRAIN_DAYS,
          "family": list(FAMILY), "selection_metric": "POOLED_COMPLETE_MSE", "tie_break": "FIRST_DECLARED",
          "label_availability": "ACTUAL_LABEL_END_STRICTLY_BEFORE_HISTORY_BOUNDARY",
          "final_dev_boundary": "FIRST_TEST_SESSION_OPEN"}


def _locator(value):
    if (type(value) is not str or not value or value != value.strip()
            or not (Path(value).is_absolute() or PureWindowsPath(value).is_absolute())
            or any(part in (".", "..") for part in value.replace("\\", "/").split("/"))):
        raise ValueError("a recorded source locator must be absolute without dot segments")
    return value


def normalize_inner_selection_plan(plan: dict) -> dict:
    from .intraday_experiment import _count
    object_fields(plan, {"plan_schema_version", "source_experiment", "selection", "intraday_data_path"}, "inner selection plan")
    if plan["plan_schema_version"] != INTRADAY_INNER_SELECTION_PLAN_VERSION:
        raise ValueError("unsupported inner selection plan version")
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
        raise ValueError("inner selection requires an ordinary saved DEV experiment")
    if source["experiment_id"] != plan["source_experiment"]["experiment_id"]:
        raise ValueError("source experiment differs from the captured identity")
    selection = plan["selection"]
    groups = source["report"]["groups"]
    cost, index = selection["cost_index"], selection["candidate_index"]
    if cost >= len(groups) or index >= len(groups[cost]["results"]):
        raise ValueError("source cost/candidate index is outside the saved experiment")
    candidate = groups[cost]["results"][index]
    if candidate["candidate_id"] != selection["candidate_id"]:
        raise ValueError("candidate differs from the captured identity")
    if candidate["strategy"]["kind"] not in ("RIDGE", "QUADRATIC_RIDGE"):
        raise ValueError("inner selection requires a saved linear or quadratic Ridge candidate")
    quadratic_terms(source["report"]["context"]["feature_fields"])
    return groups[cost], candidate


def inner_selection_versions(source: dict) -> dict:
    return {**research.research_algorithm_versions(source["plan"]),
            "quadratic": INTRADAY_QUADRATIC_RIDGE_VERSION, "inner_selection": INTRADAY_INNER_SELECTION_VERSION}


def _equal(actual, expected, label):
    if canonical_json(actual) != canonical_json(expected):
        raise ValueError(f"inner selection {label} differs")


def _recipe(member, source_strategy):
    return {"kind": member["kind"], "name": source_strategy["name"], "alpha": member["alpha"],
            "threshold": source_strategy["threshold"]}


def _fit(rows, observations, features, recipe, boundary):
    fitter = fit_quadratic_rows if recipe["kind"] == "QUADRATIC_RIDGE" else research.fit_ridge_rows
    model, scores = fitter(rows, observations, features, recipe["alpha"], boundary=boundary)
    predictions = [{**{key: row[key] for key in ("observation_key", "trading_day", "slot", "decision_time")},
                    "score": score, "target": "LONG" if score > recipe["threshold"] else "FLAT"}
                   for row, score in zip(observations, scores, strict=True)]
    return model, predictions


def pooled_mse(predictions, targets) -> float:
    """One row-weighted loss on the declared temporally available COMPLETE keys."""
    scores = {row["observation_key"]: row["score"] for row in predictions}
    if not targets:
        raise ValueError("inner selection has no COMPLETE scoring sample")
    loss = math.fsum((scores[row["observation_key"]] - row["value"]) ** 2 / len(targets) for row in targets)
    if not math.isfinite(loss):
        raise ValueError("inner selection pooled MSE is not finite")
    return 0.0 if loss == 0 else loss


def _window(prepared, history_days, history_rows, history_purged, history_boundary):
    train_days, validation_days = history_days[:-INNER_HOLDOUT_DAYS], history_days[-INNER_HOLDOUT_DAYS:]
    sessions = {row["trading_day"]: row for row in prepared.report["sessions"]}
    boundary = sessions[validation_days[0]]["open_time"]
    rows = tuple((row, target) for row, target in history_rows if row["trading_day"] in train_days
                 and datetime.fromisoformat(target["actual_label_end_time"]) < datetime.fromisoformat(boundary))
    purged = [row["observation_key"] for row, target in history_rows if row["trading_day"] in train_days
              and datetime.fromisoformat(target["actual_label_end_time"]) >= datetime.fromisoformat(boundary)]
    observations = tuple(row for row in prepared.report["observations"]
                         if row["status"] == "READY" and row["trading_day"] in validation_days)
    targets = [{"observation_key": row["observation_key"], "trading_day": row["trading_day"],
                "actual_label_end_time": target["actual_label_end_time"], "value": target["value"]}
               for row, target in history_rows if row["trading_day"] in validation_days]
    reason = ("INSUFFICIENT_INNER_HISTORY" if len(validation_days) != INNER_HOLDOUT_DAYS or len(train_days) < MINIMUM_INNER_TRAIN_DAYS
              else "NO_INNER_TRAINING_ROWS" if not rows else "NO_COMPLETE_INNER_SCORE_SAMPLE" if not targets else None)
    evidence = {"history_days": list(history_days), "history_boundary": history_boundary,
        "history_training_keys": [row["observation_key"] for row, _ in history_rows], "history_purged_keys": list(history_purged),
        "training_days": train_days, "validation_days": validation_days, "training_boundary": boundary,
        "training_keys": [row["observation_key"] for row, _ in rows], "purged_keys": purged,
        "validation_keys": [row["observation_key"] for row in observations], "scored_targets": targets,
        "unavailable_reason": reason, "family_results": [], "selected_index": None, "selected_recipe": None}
    return evidence, rows, observations


def _select(window, features, source_strategy):
    evidence, rows, observations = window
    for index, member in enumerate(FAMILY):
        recipe = _recipe(member, source_strategy)
        model, predictions = _fit(rows, observations, features, recipe, evidence["training_boundary"])
        evidence["family_results"].append({"candidate_index": index, "strategy": recipe, "model": model,
            "predictions": predictions, "mse": pooled_mse(predictions, evidence["scored_targets"])})
    index = min(range(len(FAMILY)), key=lambda index: evidence["family_results"][index]["mse"])
    evidence["selected_index"] = index
    evidence["selected_recipe"] = deepcopy(evidence["family_results"][index]["strategy"])


def _evaluate(source, plan, *, data_file=None):
    group, reference = _selected(source, plan)
    if source["algorithm_versions"] != research.research_algorithm_versions(source["plan"]):
        raise ValueError("recorded source algorithms differ; no Q5 data was read or model fitted")
    normalized, children, axes = research.expand_intraday_plan(source["plan"], recorded=True)
    prepared = research._prepare_intraday_research(children[0], data_file=data_file or plan["intraday_data_path"])
    _equal(prepared.context, source["report"]["context"], "source common context")
    # This single Q5 admission is also used for complete source reconstruction.
    original = research._evaluate_intraday_research(normalized, children, axes, prepared)
    _equal(original, source["report"], "complete ordinary source reconstruction")
    context = prepared.context
    windows = [_window(prepared, fold["training_days"], rows, fold["purged_keys"], fold["training_boundary"])
               for fold, rows in zip(context["folds"], prepared.fold_rows, strict=True)]
    dev_days = context["split"]["TRAIN"] + context["split"]["VALIDATION"]
    final_boundary = next(row["open_time"] for row in prepared.report["sessions"]
                          if row["trading_day"] == context["split"]["TEST"][0])
    final_rows, final_purged = research.training_rows(prepared.report, tuple(dev_days), final_boundary)
    final = _window(prepared, dev_days, final_rows, final_purged, final_boundary)
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
            _select(window, context["feature_fields"], reference["strategy"])
            observations = tuple(row for row in prepared.observations if row["trading_day"] in fold["validation_days"])
            recipe = window[0]["selected_recipe"]
            model, values = _fit(rows, observations, context["feature_fields"], recipe, fold["training_boundary"])
            record["refit"] = {"strategy": deepcopy(recipe), "model": model, "predictions": values,
                               "prediction_metrics": research.prediction_metrics(values, prepared.report)}
            predictions.extend(values)
        _select(final, context["feature_fields"], reference["strategy"])
        sessions, prices = execution_views(prepared.report, trading_days=tuple(context["evaluated_days"]))
        execution = run_intraday_execution(sessions=sessions, prices=prices, decisions=tuple(predictions),
            interval=context["interval"], policy=parse_execution_policy(group["execution_policy"]))
        account = {"predictions": predictions, "prediction_metrics": research.prediction_metrics(predictions, prepared.report),
                   "execution": execution, "risk": research.intraday_daily_risk(execution),
                   "fold_contributions": research.fold_cash_contributions(context, execution)}
    report = {"result_schema_version": INTRADAY_INNER_SELECTION_RESULT_VERSION,
        "version": INTRADAY_INNER_SELECTION_VERSION, "status": "UNAVAILABLE" if reasons else "AVAILABLE",
        "evaluation_scope": "DEVELOPMENT_NESTED_HOLDOUT_SELECTION_ONLY", "data_id": source["dataset_id"],
        "plan_sha256": digest(plan), "method": deepcopy(METHOD), "source_experiment": deepcopy(source),
        "source_reconstruction": "COMPLETE_REPORT_RECONSTRUCTED", "fixed_reference": deepcopy(plan["selection"]),
        "benchmark": deepcopy(group["benchmark"]), "outer_folds": outer, "final_dev": final[0],
        "selected_account": account, "unavailable_reasons": reasons}
    report["inner_selection_id"] = digest(report)
    return report


def run_intraday_inner_selection(source_experiment_path: str | Path, *, expected_experiment_id: str,
                                cost_index: int, candidate_index: int, expected_candidate_id: str,
                                intraday_data_file: str | Path | None = None,
                                name: str = "", notes: str = "") -> StrategyExperiment:
    """Run the declared fixed selection rule from one explicitly saved candidate."""
    if type(name) is not str or type(notes) is not str:
        raise ValueError("experiment name and notes must be strings")
    path = intraday_data_path(str(source_experiment_path))
    source = load_strategy_experiment(path).as_dict()
    comparison = source["plan"].get("comparison_plan", source["plan"])
    plan = normalize_inner_selection_plan({"plan_schema_version": INTRADAY_INNER_SELECTION_PLAN_VERSION,
        "source_experiment": {"path": str(path), "experiment_id": expected_experiment_id},
        "selection": {"cost_index": cost_index, "candidate_index": candidate_index, "candidate_id": expected_candidate_id},
        "intraday_data_path": str(intraday_data_path(str(intraday_data_file))) if intraday_data_file is not None
                              else comparison.get("intraday_data_path", "")})
    report = _evaluate(source, plan)
    root = {"artifact_schema_version": INTRADAY_INNER_SELECTION_VERSION, "evaluation_mode": "INTRADAY_INNER_SELECTION",
        "dataset_id": source["dataset_id"], "plan": plan, "report": report,
        "algorithm_versions": inner_selection_versions(source), "environment": environment_versions(), "name": name, "notes": notes}
    root["experiment_id"] = digest(root)
    return StrategyExperiment(canonical_json(root))


def replay_intraday_inner_selection(snapshot: StrategyExperiment, *, intraday_data_file: str | Path | None = None,
                                    source_experiment_file: str | Path | None = None) -> dict:
    """Replay the embedded ordinary source and complete selection with one Q5 load.

    The original ordinary file is not required. An optional explicit replacement
    must match the embedded snapshot exactly; it never changes saved locators.
    """
    root = snapshot.as_dict()
    source = root["report"]["source_experiment"]
    if root["algorithm_versions"] != inner_selection_versions(source):
        raise ValueError("recorded inner selection algorithms differ; no Q5 data was read or model fitted")
    if source_experiment_file is not None:
        _equal(load_strategy_experiment(source_experiment_file).as_dict(), source, "explicit ordinary source")
    actual = _evaluate(source, root["plan"], data_file=intraday_data_file)
    _equal(actual, root["report"], "complete replay report")
    checksum = sha256(canonical_json(actual)).hexdigest()
    return {"experiment_id": root["experiment_id"], "data_id": root["dataset_id"],
            "inner_selection_id": actual["inner_selection_id"], "report_matches": True,
            "expected_report_sha256": checksum, "actual_report_sha256": checksum}
