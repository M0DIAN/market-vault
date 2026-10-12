"""Outer DEV prediction evidence for fixed and bounded selected ML procedures.

The source grammars remain explicit. Ordinary candidates reconstruct only
their selected forecasts; Q25/Q31/Q36 reconstruct their complete saved procedure.
Neither path turns this derived diagnostic into a selection or TEST artifact.
"""

from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path

from . import intraday_inner_selection as inner
from . import intraday_joint_selection as joint
from . import intraday_research as research
from . import intraday_threshold_selection as threshold
from .intraday_data import digest
from .intraday_experiment import INTRADAY_EXPERIMENT_VERSIONS
from .intraday_prediction_quality import (
    _calculated, _coverage, _data_override, _index, _mean, _metric,
    _prediction_metrics, _score_forecasts,
)
from .ridge_baseline import _training_target_mean
from .strategy_experiment import StrategyExperiment, canonical_json


INTRADAY_ML_PREDICTION_QUALITY_VERSION = "market-vault-intraday-ml-prediction-quality-v1"
SCORE_BOUNDARIES = (0.0, .0005, .001, .002)
FORECAST_ORDER = ("SELECTED", "FIXED_REFERENCE", "ZERO", "TRAIN_MEAN")


def _equal(actual, expected, label):
    if canonical_json(actual) != canonical_json(expected):
        raise ValueError(f"ML diagnostic reconstruction differs: {label}")


def _saved_ml_source(snapshot, *, cost_index=0, candidate_index=0):
    """Select from one validated immutable snapshot, without source I/O.

    This bounded internal view is also useful to recorded-only diagnostics.
    Current algorithm admission belongs to the reconstruction action below.
    """
    _index(cost_index, "cost_index")
    _index(candidate_index, "candidate_index")
    if type(snapshot) is not StrategyExperiment:
        raise ValueError("an immutable StrategyExperiment is required")
    root = snapshot.as_dict()
    schema = root["artifact_schema_version"]
    procedures = {
        inner.INTRADAY_INNER_SELECTION_VERSION: ("INNER_MODEL_SELECTION", inner, "inner_selection_id"),
        threshold.INTRADAY_THRESHOLD_SELECTION_VERSION: ("ECONOMIC_THRESHOLD_SELECTION", threshold, "threshold_selection_id"),
        joint.INTRADAY_JOINT_SELECTION_VERSION: ("JOINT_ECONOMIC_SELECTION", joint, "joint_selection_id"),
    }
    if schema in INTRADAY_EXPERIMENT_VERSIONS and root["evaluation_mode"] in (
            "INTRADAY_COMPARISON", "INTRADAY_DIAGNOSTICS"):
        source, kind, module = root, "ORDINARY", None
        selection = {"cost_index": cost_index, "candidate_index": candidate_index}
        report_key = "research_id"
    elif schema in procedures:
        if cost_index or candidate_index:
            raise ValueError("a selected procedure has one outer account; both indices must be zero")
        source, selection = root["report"]["source_experiment"], root["plan"]["selection"]
        kind, module, report_key = procedures[schema]
    else:
        raise ValueError("ML diagnostics require an ordinary learned DEV candidate or a saved Q25/Q31/Q36 study")
    groups = source["report"]["groups"]
    ci, si = selection["cost_index"], selection["candidate_index"]
    if ci >= len(groups) or si >= len(groups[ci]["results"]):
        raise ValueError("selected cost/candidate index is outside the saved experiment")
    group, reference = groups[ci], groups[ci]["results"][si]
    if reference["strategy"]["kind"] not in ("RIDGE", "QUADRATIC_RIDGE"):
        raise ValueError("ML diagnostics require a linear or quadratic Ridge reference")
    return {"root": root, "source": source, "kind": kind, "module": module, "report_key": report_key,
            "selection": {"cost_index": ci, "candidate_index": si, "candidate_id": reference["candidate_id"]},
            "group": group, "reference": reference, "context": source["report"]["context"]}


def _verified_predictions(selected, locator):
    root, source, module = selected["root"], selected["source"], selected["module"]
    if source["algorithm_versions"] != research.research_algorithm_versions(source["plan"]):
        raise ValueError("recorded source algorithms differ; no Q5 data was read or model fitted")
    if module is not None:
        versions = (joint.joint_selection_versions(source) if module is joint else
                    inner.inner_selection_versions(source) if module is inner else threshold.threshold_selection_versions(source))
        if root["algorithm_versions"] != versions:
            raise ValueError("recorded selection algorithms differ; no Q5 data was read or model fitted")
    _, children, _ = research.expand_intraday_plan(source["plan"], recorded=True)
    ci, si = selected["selection"]["cost_index"], selected["selection"]["candidate_index"]
    recorded_path = root["plan"]["intraday_data_path"] if module is not None else children[ci]["intraday_data_path"]
    prepared = research._prepare_intraday_research(children[ci], data_file=locator or recorded_path)
    _equal(prepared.context, selected["context"], "complete outer context")
    reference = selected["reference"]
    if module is None:
        strategy = research.intraday_strategy_specs(children[ci])[si]
        predictions, models, errors = research.candidate_predictions(prepared, strategy, {})
        for key, actual in (("predictions", predictions), ("fold_models", models), ("prediction_metrics", errors)):
            _equal(actual, reference[key], "selected ordinary " + key)
        records = [{"model": row["model"], "strategy": reference["strategy"]} for row in models]
        scope = "SOURCE_VERIFIED_SELECTED_ML_FORECASTS"
    else:
        # The existing evaluator verifies the embedded ordinary report, every
        # inner choice, outer application and final DEV evidence. Reuse this
        # action's verified Q5 object instead of admitting the file again.
        report = module._evaluate(source, root["plan"], data=prepared.data)
        _equal(report, root["report"], "complete saved selection procedure")
        predictions = report["selected_account"]["predictions"]
        field = "application" if module is threshold else "refit"
        records = [row[field] for row in report["outer_folds"]]
        scope = "SOURCE_VERIFIED_COMPLETE_ML_PROCEDURE"
    return prepared, predictions, records, recorded_path, scope


def _bin_index(score):
    # Upper-inclusive boundaries agree with the existing strict score > t
    # decision rule. The fixed intervals are not estimated from this sample.
    return sum(score > boundary for boundary in SCORE_BOUNDARIES)


def _score_bins(rows):
    bins = []
    for index in range(len(SCORE_BOUNDARIES) + 1):
        selected = [row for row in rows if row["bin_index"] == index]
        pairs = [row for row in selected if row["target_status"] == "COMPLETE"]
        actual = tuple(row["target_value"] for row in pairs)
        predicted = tuple(row["scores"]["SELECTED"] for row in pairs)
        ready_mean = (_calculated(lambda: _mean(tuple(row["scores"]["SELECTED"] for row in selected)), unit="RATIO")
                      if selected else _metric(unit="RATIO", reason="NO_READY_PREDICTIONS"))
        bins.append({"bin_index": index,
            "lower_bps": None if index == 0 else SCORE_BOUNDARIES[index - 1] * 10000,
            "upper_bps": None if index == len(SCORE_BOUNDARIES) else SCORE_BOUNDARIES[index] * 10000,
            "sample": _coverage(selected), "ready_mean_prediction": ready_mean,
            "metrics": _prediction_metrics(actual, predicted),
            "target_sign_counts": {"positive": sum(value > 0 for value in actual),
                                   "zero": sum(value == 0 for value in actual),
                                   "negative": sum(value < 0 for value in actual)}})
    return bins


def _outer_rows(selected, prepared, predictions, records):
    context, reference = selected["context"], selected["reference"]
    actual_predictions = {row["observation_key"]: row for row in predictions}
    fixed = {row["observation_key"]: row for row in reference["predictions"]}
    targets = {row["observation_key"]: row for row in prepared.report["targets"]}
    _equal([row["observation_key"] for row in predictions], context["validation_keys"], "all outer READY keys")
    rows, folds = [], []
    for fold, training, record, original_model in zip(context["folds"], prepared.fold_rows, records,
                                                     reference["fold_models"], strict=True):
        train_mean = _training_target_mean(tuple(target["value"] for _, target in training))
        model, recipe, fold_rows = record["model"], record["strategy"], []
        for key in fold["validation_keys"]:
            prediction, target, old = actual_predictions[key], targets[key], fixed[key]
            row = {name: prediction[name] for name in ("observation_key", "trading_day", "slot", "decision_time")}
            row.update(fold_id=fold["fold_id"], model_id=model["model_id"],
                target_status=target["status"], target_reason=target["reason"], target_value=target["value"],
                actual_label_end_time=target["actual_label_end_time"],
                scores={"SELECTED": prediction["score"], "FIXED_REFERENCE": old["score"],
                        "ZERO": 0.0, "TRAIN_MEAN": train_mean},
                decision=prediction["target"], reference_decision=old["target"], threshold=recipe["threshold"],
                bin_index=_bin_index(prediction["score"]))
            fold_rows.append(row)
        rows.extend(fold_rows)
        folds.append({"fold_index": fold["fold_index"], "fold_id": fold["fold_id"],
            "model_id": model["model_id"], "model": deepcopy(model), "strategy": deepcopy(recipe),
            "reference_model": deepcopy(original_model["model"]), "reference_strategy": deepcopy(reference["strategy"]),
            "training_boundary": fold["training_boundary"], "training_days": fold["training_days"],
            "training_keys": fold["training_keys"], "purged_keys": fold["purged_keys"], "training_count": len(training),
            "training_target_mean": train_mean, "validation_days": fold["validation_days"],
            "validation_keys": fold["validation_keys"], "sample": _coverage(fold_rows),
            "forecasts": _score_forecasts(fold_rows, forecast_order=FORECAST_ORDER), "bins": _score_bins(fold_rows)})
    return rows, folds


def analyze_intraday_ml_prediction_quality(snapshot: StrategyExperiment, *, cost_index: int = 0,
                                           candidate_index: int = 0,
                                           intraday_data_file: str | Path | None = None) -> dict:
    """Verify the saved ML source and describe its original outer DEV scores."""
    locator = _data_override(intraday_data_file)
    selected = _saved_ml_source(snapshot, cost_index=cost_index, candidate_index=candidate_index)
    root, source, module = selected["root"], selected["source"], selected["module"]
    selection_key = selected["report_key"]
    result = {"version": INTRADAY_ML_PREDICTION_QUALITY_VERSION, "status": "AVAILABLE",
        "evaluation_scope": "DEVELOPMENT_OUTER_PREDICTION_DIAGNOSTICS_ONLY",
        "experiment_id": root["experiment_id"], "data_id": root["dataset_id"],
        "source_kind": selected["kind"], "source_schema_version": root["artifact_schema_version"],
        "algorithm_versions": deepcopy(root["algorithm_versions"]),
        "source_evaluation_scope": root["report"]["evaluation_scope"],
        "ordinary_source_id": source["experiment_id"], "selection_id": root["report"][selection_key],
        "cost_index": cost_index, "candidate_index": candidate_index, "source_selection": selected["selection"],
        "context": selected["context"],
        "method": {"forecast_order": list(FORECAST_ORDER), "aggregation": "COMPLETE_TARGET_ROW_WEIGHTED",
            "training_mean": "PURGED_OUTER_TRAINING_TARGETS", "bias_definition": "MEAN_PREDICTION_MINUS_MEAN_TARGET",
            "mse_skill_definition": "ONE_MINUS_MODEL_SQUARED_ERROR_OVER_BASELINE_SQUARED_ERROR",
            "spearman_ties": "AVERAGE_RANK", "score_boundaries_bps": [value * 10000 for value in SCORE_BOUNDARIES],
            "bins": "LOWER_EXCLUSIVE_UPPER_INCLUSIVE", "bin_forecast": "SELECTED",
            "paired_bin_means": "COMPLETE_TARGET_PAIRS_ONLY", "ready_mean": "ALL_READY_SCORES_IN_BIN",
            "fixed_reference": "ORIGINAL_EXPLICIT_SOURCE_CANDIDATE",
            "inference": "DESCRIPTIVE_ONLY_NO_CALIBRATION_FIT_OR_THRESHOLD_SELECTION",
            "evaluation_scope": "OUTER_DEV_ONLY_NO_INNER_FINAL_DEV_OR_TEST_SCORING"}}
    if module is not None and root["report"]["status"] != "AVAILABLE":
        result.update(status="UNAVAILABLE", unavailable_reason="SOURCE_STUDY_UNAVAILABLE",
            unavailable_reasons=deepcopy(root["report"]["unavailable_reasons"]), source_locator=None,
            evidence={"scope": "RECORDED_UNAVAILABLE_SOURCE", "context_matches": False,
                "fold_models_match": False, "predictions_match": False, "prediction_metrics_match": False,
                "execution_replayed": False}, sample=None, forecasts=[], bins=[], folds=[], predictions=[])
    else:
        prepared, predictions, records, recorded_path, scope = _verified_predictions(selected, locator)
        rows, folds = _outer_rows(selected, prepared, predictions, records)
        result.update(unavailable_reason=None, unavailable_reasons=[],
            source_locator={"recorded": recorded_path, "used": str(prepared.data.path.resolve()), "override_used": locator is not None},
            evidence={"scope": scope, "context_matches": True, "fold_models_match": True,
                "predictions_match": True, "prediction_metrics_match": True, "execution_replayed": module is not None},
            sample={**_coverage(rows), "evaluated_day_count": len(prepared.context["evaluated_days"]), "fold_count": len(folds)},
            forecasts=_score_forecasts(rows, forecast_order=FORECAST_ORDER), bins=_score_bins(rows), folds=folds, predictions=rows)
    result["prediction_quality_id"] = digest(result)
    return result
