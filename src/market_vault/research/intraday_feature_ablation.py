"""Exhaustive Feature omission refits of one source-verified saved DEV Ridge."""

from __future__ import annotations

from pathlib import Path

from . import intraday_prediction_quality as quality
from . import intraday_research as research
from .intraday_data import digest
from .strategy_experiment import StrategyExperiment


INTRADAY_FEATURE_ABLATION_VERSION = "market-vault-intraday-feature-ablation-v1"
_ERROR_UNITS = {"mae": "RATIO", "mse": "SQUARED_RATIO", "rmse": "RATIO"}


def _paired_error_changes(rows, *, forecast_order):
    """Alternative minus full Ridge errors on the identical COMPLETE pairs."""
    paired = tuple(row for row in rows if row["target_status"] == "COMPLETE")
    actual = tuple(row["target_value"] for row in paired)
    baseline = quality._prediction_metrics(actual, tuple(row["scores"]["RIDGE"] for row in paired))
    changes = []
    for name in forecast_order:
        alternative = quality._prediction_metrics(actual, tuple(row["scores"][name] for row in paired))
        metrics = {}
        for metric, unit in _ERROR_UNITS.items():
            full, ablated = baseline[metric], alternative[metric]
            if full["value"] is None or ablated["value"] is None:
                metrics[metric] = quality._metric(unit=unit,
                    reason=full["unavailable_reason"] or ablated["unavailable_reason"])
            else:
                metrics[metric] = quality._metric(ablated["value"] - full["value"], unit=unit)
        changes.append({"forecast": name, "metrics": metrics})
    return changes


def _ablation_predictions(prepared, candidate):
    rows, folds = quality._paired_prediction_rows(prepared, candidate)
    predictions = {row["observation_key"]: row for row in rows}
    observations = {row["observation_key"]: row for row in prepared.observations}
    features, variants = prepared.context["feature_fields"], []
    for index, omitted in enumerate(features):
        retained = features[:index] + features[index + 1:]
        name, models = f"DROP_{index}", []
        for fold, training, scores in zip(prepared.context["folds"], prepared.fold_rows, folds, strict=True):
            validation = tuple(observations[key] for key in fold["validation_keys"])
            if retained:
                # The selected-candidate cache omits the projection from its
                # key. Each alternative must fit its own projection directly.
                model, values = research.fit_ridge_rows(training, validation, retained,
                    candidate["strategy"]["alpha"], boundary=fold["training_boundary"])
            else:
                mean = scores["training_target_mean"]
                model = {"version": INTRADAY_FEATURE_ABLATION_VERSION,
                         "kind": "INTERCEPT_ONLY_TRAIN_MEAN", "solver_used": False,
                         "feature_fields": [], "training_keys": list(fold["training_keys"]),
                         "training_boundary": fold["training_boundary"], "intercept": mean,
                         "coefficients": [], "means": [], "scales": []}
                model["model_id"] = digest(model)
                values = (mean,) * len(validation)
            models.append({"fold_id": fold["fold_id"], "model": model})
            for observation, value in zip(validation, values, strict=True):
                predictions[observation["observation_key"]]["scores"][name] = value
        variants.append({"forecast": name, "omitted_feature": omitted, "retained_features": retained,
                         "model_kind": "RIDGE_REFIT" if retained else "INTERCEPT_ONLY_TRAIN_MEAN",
                         "fold_models": models})
    alternatives = tuple(variant["forecast"] for variant in variants)
    forecast_order = (*quality._FORECASTS, *alternatives)
    for fold, context in zip(folds, prepared.context["folds"], strict=True):
        paired = [predictions[key] for key in context["validation_keys"]]
        fold["forecasts"] = quality._score_forecasts(paired, forecast_order=forecast_order)
        fold["paired_error_changes"] = _paired_error_changes(paired, forecast_order=alternatives)
    return rows, folds, variants


def analyze_intraday_feature_ablation(snapshot: StrategyExperiment, *, cost_index: int = 0,
                                      candidate_index: int = 0,
                                      intraday_data_file: str | Path | None = None) -> dict:
    """Refit every single-Feature omission without changing rows or alpha."""
    root, candidate, prepared = quality._prepare_selected_ridge(snapshot, cost_index=cost_index,
        candidate_index=candidate_index, intraday_data_file=intraday_data_file)
    rows, folds, variants = _ablation_predictions(prepared, candidate)
    alternatives = tuple(variant["forecast"] for variant in variants)
    forecast_order = (*quality._FORECASTS, *alternatives)
    _, children, _ = research.expand_intraday_plan(root["plan"], recorded=True)
    result = {"version": INTRADAY_FEATURE_ABLATION_VERSION,
              "experiment_id": root["experiment_id"], "data_id": root["dataset_id"],
              "research_id": root["report"]["research_id"], "candidate_id": candidate["candidate_id"],
              "cost_index": cost_index, "candidate_index": candidate_index, "strategy": candidate["strategy"],
              "context": prepared.context,
              "source_locator": {"recorded": children[cost_index]["intraday_data_path"],
                                 "used": str(prepared.data.path.resolve()),
                                 "override_used": quality._data_override(intraday_data_file) is not None},
              "evidence": {"scope": "SOURCE_VERIFIED_SELECTED_RIDGE_RECONSTRUCTION",
                           "context_matches": True, "fold_models_match": True, "predictions_match": True,
                           "prediction_metrics_match": True, "execution_replayed": False},
              "method": {"forecast_order": list(forecast_order), "aggregation": "COMPLETE_TARGET_ROW_WEIGHTED",
                         "bias_definition": "MEAN_PREDICTION_MINUS_MEAN_TARGET",
                         "training_mean": "PURGED_FOLD_TRAINING_TARGETS",
                         "mse_skill_definition": "ONE_MINUS_MODEL_SQUARED_ERROR_OVER_BASELINE_SQUARED_ERROR",
                         "spearman_ties": "AVERAGE_RANK", "inference": "DESCRIPTIVE_ONLY",
                         "evaluation_scope": "DEVELOPMENT_WALK_FORWARD_ONLY",
                         "omission_order": "SAVED_FEATURE_PROJECTION_ORDER",
                         "row_eligibility": "UNCHANGED_ORIGINAL_COMMON_PROJECTION",
                         "alpha_policy": "FIXED_SAVED_ALPHA_FOR_RIDGE_REFITS",
                         "paired_error_difference": "ABLATION_MINUS_FULL_RIDGE",
                         "paired_error_metrics": list(_ERROR_UNITS)},
              "sample": {**quality._coverage(rows), "evaluated_day_count": len(prepared.context["evaluated_days"]),
                         "fold_count": len(folds)},
              "baseline": {"strategy": candidate["strategy"], "fold_models": candidate["fold_models"]},
              "variants": variants, "forecasts": quality._score_forecasts(rows, forecast_order=forecast_order),
              "paired_error_changes": _paired_error_changes(rows, forecast_order=alternatives),
              "folds": folds, "predictions": rows}
    result["feature_ablation_id"] = digest(result)
    return result
