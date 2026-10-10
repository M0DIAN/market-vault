"""Source-verified out-of-fold forecast quality for one saved DEV Ridge.

The selected fold models and every prediction are reconstructed from Q5 before
target scoring. This is deliberately narrower than a complete experiment
Replay: no execution account is rerun or given new proof by this analysis.
"""

from __future__ import annotations

import math
from pathlib import Path

from . import intraday_research as research
from .feature_research import _average_ranks, _pearson
from .intraday_data import digest
from .intraday_experiment import INTRADAY_EXPERIMENT_VERSIONS
from .strategy_config import parse_strategy_specs
from .strategy_experiment import StrategyExperiment, canonical_json


INTRADAY_PREDICTION_QUALITY_VERSION = "market-vault-intraday-prediction-quality-v1"
_FORECASTS = ("RIDGE", "ZERO", "TRAIN_MEAN")
_UNITS = {"mse": "SQUARED_RATIO", "mae": "RATIO", "rmse": "RATIO", "r2": "NUMBER",
          "mean_pred": "RATIO", "mean_target": "RATIO", "bias": "RATIO",
          "pearson": "NUMBER", "spearman": "NUMBER"}


def _index(value, label):
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return value


def _data_override(value):
    if value is None or (type(value) is str and not value.strip()):
        return None
    if not isinstance(value, (str, Path)):
        raise ValueError("intraday_data_file must be an explicit str or Path")
    return value


def _prepare_selected_ridge(snapshot, *, cost_index, candidate_index, intraday_data_file=None,
                            max_feature_count=None):
    """One action's verified selected folds; never a public source bypass."""
    _index(cost_index, "cost_index")
    _index(candidate_index, "candidate_index")
    locator = _data_override(intraday_data_file)
    if type(snapshot) is not StrategyExperiment:
        raise ValueError("an immutable StrategyExperiment is required")
    root = snapshot.as_dict()
    if (root["artifact_schema_version"] not in INTRADAY_EXPERIMENT_VERSIONS
            or root["evaluation_mode"] not in ("INTRADAY_COMPARISON", "INTRADAY_DIAGNOSTICS")):
        raise ValueError("prediction quality requires an ordinary saved DEV experiment")
    if root["algorithm_versions"] != research.research_algorithm_versions(root["plan"]):
        raise ValueError("recorded intraday algorithm versions differ; no source was read or model fitted")
    groups = root["report"]["groups"]
    if cost_index >= len(groups):
        raise ValueError("cost_index is outside the saved cost groups")
    candidates = groups[cost_index]["results"]
    if candidate_index >= len(candidates):
        raise ValueError("candidate_index is outside the saved candidates")
    candidate = candidates[candidate_index]
    if candidate["strategy"]["kind"] != "RIDGE":
        raise ValueError("prediction quality requires a selected RIDGE candidate")
    _, children, _ = research.expand_intraday_plan(root["plan"], recorded=True)
    if max_feature_count is not None and len(children[cost_index]["feature_fields"]) > max_feature_count:
        raise ValueError(f"selected Ridge projection must contain at most {max_feature_count} Features; "
                         "no source was read or model fitted")
    prepared = research._prepare_intraday_research(children[cost_index], data_file=locator)
    if canonical_json(prepared.context) != canonical_json(root["report"]["context"]):
        raise ValueError("verified source differs from the complete saved context; no model was fitted")
    strategy = parse_strategy_specs([candidate["strategy"]])[0]
    predictions, models, errors = research.candidate_predictions(prepared, strategy, {})
    for label, actual, expected in (
        ("fold models", models, candidate["fold_models"]),
        ("predictions", predictions, candidate["predictions"]),
        ("prediction metrics", errors, candidate["prediction_metrics"]),
    ):
        if canonical_json(actual) != canonical_json(expected):
            raise ValueError(f"selected Ridge reconstruction differs from saved {label}")
    return root, candidate, prepared


def _metric(value=None, *, unit="NUMBER", reason=None):
    if value is not None and not math.isfinite(value):
        value, reason = None, "NONFINITE_RESULT"
    return {"value": 0.0 if value == 0 else value, "unit": unit, "unavailable_reason": reason}


def _calculated(operation, *, unit="NUMBER"):
    try:
        return _metric(operation(), unit=unit)
    except (ArithmeticError, ValueError):
        return _metric(unit=unit, reason="NONFINITE_RESULT")


def _mean(values):
    return math.fsum(value / len(values) for value in values)


def _root_mean_square(values):
    scale = max(abs(value) for value in values)
    if not math.isfinite(scale):
        raise OverflowError("nonfinite forecast error")
    return 0.0 if scale == 0 else scale * math.sqrt(_mean(tuple((value / scale) ** 2 for value in values)))


def _correlation(actual, predicted, *, ranked=False):
    if len(actual) < 2:
        return _metric(reason="INSUFFICIENT_COMPLETE_TARGETS")
    constant_target = all(value == actual[0] for value in actual)
    constant_prediction = all(value == predicted[0] for value in predicted)
    if constant_target or constant_prediction:
        reason = ("CONSTANT_PREDICTIONS_AND_TARGETS" if constant_target and constant_prediction else
                  "CONSTANT_TARGETS" if constant_target else "CONSTANT_PREDICTIONS")
        return _metric(reason=reason)
    if ranked:
        actual, predicted = _average_ranks(actual), _average_ranks(predicted)
    # Scaling preserves correlation and avoids overflow/underflow in the shared
    # Pearson implementation's squared deviations for finite input vectors.
    left, right = max(abs(value) for value in actual), max(abs(value) for value in predicted)
    result = _calculated(lambda: _pearson(tuple(value / left for value in actual),
                                        tuple(value / right for value in predicted)))
    if result["value"] is None:
        result["unavailable_reason"] = "NONFINITE_RESULT"
    return result


def _loss_skill(actual, predicted, baseline, *, zero_reason="ZERO_BASELINE_ERROR"):
    if not actual:
        return _metric(reason="NO_COMPLETE_TARGETS")
    errors = tuple(p - y for y, p in zip(actual, predicted, strict=True))
    reference = tuple(p - y for y, p in zip(actual, baseline, strict=True))
    if not all(math.isfinite(value) for value in (*errors, *reference)):
        return _metric(reason="NONFINITE_RESULT")
    if all(value == 0 for value in reference):
        return _metric(reason=zero_reason)
    scale = max(abs(value) for value in (*errors, *reference))
    # A common scale cancels from the loss ratio, including for tiny nonzero
    # losses whose individual MSE cannot be represented above float zero.
    return _calculated(lambda: 1.0 - math.fsum((value / scale) ** 2 for value in errors)
                       / math.fsum((value / scale) ** 2 for value in reference))


def _prediction_metrics(actual, predicted):
    """Descriptive metrics for one paired vector, with local availability."""
    if not actual:
        return {name: _metric(unit=unit, reason="NO_COMPLETE_TARGETS") for name, unit in _UNITS.items()}
    errors = tuple(p - y for y, p in zip(actual, predicted, strict=True))
    mean_pred = _calculated(lambda: _mean(predicted), unit="RATIO")
    mean_target = _calculated(lambda: _mean(actual), unit="RATIO")
    metrics = {"mse": _calculated(lambda: _root_mean_square(errors) ** 2, unit="SQUARED_RATIO"),
               "mae": _calculated(lambda: _mean(tuple(abs(value) for value in errors)), unit="RATIO"),
               "rmse": _calculated(lambda: _root_mean_square(errors), unit="RATIO"),
               "mean_pred": mean_pred, "mean_target": mean_target,
               "pearson": _correlation(actual, predicted), "spearman": _correlation(actual, predicted, ranked=True)}
    if mean_pred["value"] is None or mean_target["value"] is None:
        metrics["bias"] = _metric(unit="RATIO", reason="NONFINITE_RESULT")
    else:
        metrics["bias"] = _calculated(lambda: mean_pred["value"] - mean_target["value"], unit="RATIO")
    if all(value == actual[0] for value in actual):
        metrics["r2"] = _metric(reason="CONSTANT_TARGETS")
    elif mean_target["value"] is None:
        metrics["r2"] = _metric(reason="NONFINITE_RESULT")
    else:
        metrics["r2"] = _loss_skill(actual, predicted, (mean_target["value"],) * len(actual),
                                    zero_reason="NONFINITE_RESULT")
    return metrics


def _score_forecasts(rows, *, forecast_order=_FORECASTS):
    paired = tuple(row for row in rows if row["target_status"] == "COMPLETE")
    actual = tuple(row["target_value"] for row in paired)
    forecasts = {name: tuple(row["scores"][name] for row in paired) for name in forecast_order}
    results = []
    for name, predicted in forecasts.items():
        metrics = _prediction_metrics(actual, predicted)
        metrics["mse_skill_vs_zero"] = _loss_skill(actual, predicted, forecasts["ZERO"])
        metrics["mse_skill_vs_train_mean"] = _loss_skill(actual, predicted, forecasts["TRAIN_MEAN"])
        results.append({"forecast": name, "metrics": metrics})
    return results


def _coverage(rows):
    paired = [row for row in rows if row["target_status"] == "COMPLETE"]
    return {"prediction_count": len(rows), "complete_target_count": len(paired),
            "incomplete_target_count": len(rows) - len(paired),
            "scored_day_count": len({row["trading_day"] for row in paired})}


def _paired_prediction_rows(prepared, candidate):
    keys = set(prepared.context["validation_keys"])
    targets = {row["observation_key"]: row for row in prepared.report["targets"] if row["observation_key"] in keys}
    predictions = {row["observation_key"]: row for row in candidate["predictions"]}
    rows, folds = [], []
    for fold, training, record in zip(prepared.context["folds"], prepared.fold_rows, candidate["fold_models"], strict=True):
        # Match the existing fitter's target-mean arithmetic on the actual
        # retained training rows, rather than estimating it from coefficients.
        train_mean = math.fsum(target["value"] for _, target in training) / len(training)
        model_id, fold_rows = record["model"]["model_id"], []
        for key in fold["validation_keys"]:
            prediction, target = predictions[key], targets[key]
            row = {name: prediction[name] for name in ("observation_key", "trading_day", "slot", "decision_time")}
            row.update(fold_id=fold["fold_id"], model_id=model_id, target_status=target["status"],
                       target_reason=target["reason"], target_value=target["value"],
                       actual_label_end_time=target["actual_label_end_time"],
                       scores={"RIDGE": prediction["score"], "ZERO": 0.0, "TRAIN_MEAN": train_mean})
            fold_rows.append(row)
        rows.extend(fold_rows)
        folds.append({"fold_index": fold["fold_index"], "fold_id": fold["fold_id"], "model_id": model_id,
                      "training_boundary": fold["training_boundary"], "training_count": len(training),
                      "training_target_mean": train_mean, "validation_days": fold["validation_days"],
                      "sample": _coverage(fold_rows), "forecasts": _score_forecasts(fold_rows)})
    return rows, folds


def analyze_intraday_prediction_quality(snapshot: StrategyExperiment, *, cost_index: int = 0,
                                        candidate_index: int = 0,
                                        intraday_data_file: str | Path | None = None) -> dict:
    """Refit one saved DEV Ridge and score it against two historical baselines."""
    root, candidate, prepared = _prepare_selected_ridge(snapshot, cost_index=cost_index,
        candidate_index=candidate_index, intraday_data_file=intraday_data_file)
    rows, folds = _paired_prediction_rows(prepared, candidate)
    _, children, _ = research.expand_intraday_plan(root["plan"], recorded=True)
    result = {"version": INTRADAY_PREDICTION_QUALITY_VERSION,
              "experiment_id": root["experiment_id"], "data_id": root["dataset_id"],
              "research_id": root["report"]["research_id"], "candidate_id": candidate["candidate_id"],
              "cost_index": cost_index, "candidate_index": candidate_index, "strategy": candidate["strategy"],
              "context": prepared.context,
              "source_locator": {"recorded": children[cost_index]["intraday_data_path"],
                                 "used": str(prepared.data.path.resolve()),
                                 "override_used": _data_override(intraday_data_file) is not None},
              "evidence": {"scope": "SOURCE_VERIFIED_SELECTED_RIDGE_RECONSTRUCTION",
                           "context_matches": True, "fold_models_match": True, "predictions_match": True,
                           "prediction_metrics_match": True, "execution_replayed": False},
              "method": {"forecast_order": list(_FORECASTS), "aggregation": "COMPLETE_TARGET_ROW_WEIGHTED",
                         "bias_definition": "MEAN_PREDICTION_MINUS_MEAN_TARGET",
                         "training_mean": "PURGED_FOLD_TRAINING_TARGETS",
                         "mse_skill_definition": "ONE_MINUS_MODEL_SQUARED_ERROR_OVER_BASELINE_SQUARED_ERROR",
                         "spearman_ties": "AVERAGE_RANK", "inference": "DESCRIPTIVE_ONLY",
                         "evaluation_scope": "DEVELOPMENT_WALK_FORWARD_ONLY"},
              "sample": {**_coverage(rows), "evaluated_day_count": len(prepared.context["evaluated_days"]),
                         "fold_count": len(folds)},
              "forecasts": _score_forecasts(rows), "folds": folds, "predictions": rows}
    result["prediction_quality_id"] = digest(result)
    return result
