"""One bounded quadratic representation of a source-verified saved DEV Ridge."""

from __future__ import annotations

from pathlib import Path

from . import intraday_prediction_quality as quality
from . import intraday_research as research
from .intraday_data import digest
from .intraday_feature_ablation import _ERROR_UNITS, _paired_error_changes
from .intraday_models import (
    INTRADAY_QUADRATIC_RIDGE_VERSION, MAX_QUADRATIC_INPUT_FEATURES as _MAX_INPUT_FEATURES,
    quadratic_terms as _quadratic_terms, input_values as _input_values,
    input_stats as _input_stats, expanded_observation as _expanded_observation, fit_quadratic_rows,
)
from .strategy_experiment import StrategyExperiment


_FORECAST = "QUADRATIC_RIDGE"
_FORECASTS = (*quality._FORECASTS, _FORECAST)


def _quadratic_predictions(prepared, candidate):
    features = prepared.context["feature_fields"]
    terms = _quadratic_terms(features)
    rows, folds = quality._paired_prediction_rows(prepared, candidate)
    predictions = {row["observation_key"]: row for row in rows}
    observations = {row["observation_key"]: row for row in prepared.observations}
    models = []
    for fold, training, scores in zip(prepared.context["folds"], prepared.fold_rows, folds, strict=True):
        validation = tuple(observations[key] for key in fold["validation_keys"])
        model, values = fit_quadratic_rows(training, validation, features,
            candidate["strategy"]["alpha"], boundary=fold["training_boundary"])
        models.append({"fold_id": fold["fold_id"], "model": model})
        scores["quadratic_model_id"] = model["model_id"]
        for observation, value in zip(validation, values, strict=True):
            row = predictions[observation["observation_key"]]
            row["scores"][_FORECAST] = value
            row["quadratic_model_id"] = model["model_id"]
        paired = [predictions[key] for key in fold["validation_keys"]]
        scores["forecasts"] = quality._score_forecasts(paired, forecast_order=_FORECASTS)
        scores["paired_error_changes"] = _paired_error_changes(paired, forecast_order=(_FORECAST,))
    quadratic = {"forecast": _FORECAST, "degree": 2, "input_features": list(features),
                 "expanded_width": len(terms), "terms": terms, "fold_models": models}
    return rows, folds, quadratic


def analyze_intraday_quadratic_ridge(snapshot: StrategyExperiment, *, cost_index: int = 0,
                                     candidate_index: int = 0,
                                     intraday_data_file: str | Path | None = None) -> dict:
    """Compare one fixed degree-two basis with the original selected Ridge."""
    root, candidate, prepared = quality._prepare_selected_ridge(snapshot, cost_index=cost_index,
        candidate_index=candidate_index, intraday_data_file=intraday_data_file, max_feature_count=_MAX_INPUT_FEATURES)
    rows, folds, quadratic = _quadratic_predictions(prepared, candidate)
    _, children, _ = research.expand_intraday_plan(root["plan"], recorded=True)
    result = {"version": INTRADAY_QUADRATIC_RIDGE_VERSION,
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
              "method": {"forecast_order": list(_FORECASTS), "aggregation": "COMPLETE_TARGET_ROW_WEIGHTED",
                         "bias_definition": "MEAN_PREDICTION_MINUS_MEAN_TARGET",
                         "training_mean": "PURGED_FOLD_TRAINING_TARGETS",
                         "mse_skill_definition": "ONE_MINUS_MODEL_SQUARED_ERROR_OVER_BASELINE_SQUARED_ERROR",
                         "spearman_ties": "AVERAGE_RANK", "inference": "DESCRIPTIVE_ONLY",
                         "evaluation_scope": "DEVELOPMENT_WALK_FORWARD_ONLY",
                         "term_order": "ORIGINALS_THEN_LEXICOGRAPHIC_PRODUCTS_I_LE_J",
                         "input_normalization": "PURGED_FOLD_TRAINING_POPULATION_SCALE",
                         "generated_normalization": "EXISTING_RIDGE_TRAINING_NORMALIZATION_AND_INTERCEPT",
                         "row_eligibility": "UNCHANGED_ORIGINAL_COMMON_PROJECTION",
                         "alpha_policy": "FIXED_SAVED_ALPHA_DIFFERENT_PENALTY_GEOMETRY",
                         "paired_error_difference": "QUADRATIC_MINUS_LINEAR_RIDGE",
                         "paired_error_metrics": list(_ERROR_UNITS)},
              "sample": {**quality._coverage(rows), "evaluated_day_count": len(prepared.context["evaluated_days"]),
                         "fold_count": len(folds)},
              "baseline": {"strategy": candidate["strategy"], "fold_models": candidate["fold_models"]},
              "quadratic": quadratic, "forecasts": quality._score_forecasts(rows, forecast_order=_FORECASTS),
              "paired_error_changes": _paired_error_changes(rows, forecast_order=(_FORECAST,)),
              "folds": folds, "predictions": rows}
    result["quadratic_ridge_id"] = digest(result)
    return result
