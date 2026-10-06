"""Focused leakage and identity tests for final Ridge TEST V1."""

from __future__ import annotations

from dataclasses import replace

import pytest

from market_vault.research.ridge_final_test import (
    RIDGE_FINAL_TEST_VERSION,
    RidgeFinalTestError,
    evaluate_ridge_final_test,
)
from market_vault.research.ridge_selection import select_ridge_alpha
from market_vault.research.walk_forward import build_walk_forward_plan
from test_walk_forward_experiment import _bundle, _time


def _selection(bundle):
    plan = build_walk_forward_plan(
        bundle,
        minimum_train_periods=3,
        validation_periods=2,
        step_periods=2,
    )
    return select_ridge_alpha(
        plan,
        alphas=(0.1, 1.0, 10.0),
    )


def _with_test_feature_shift(bundle, shift: float):
    test_ml = replace(
        bundle.ml_bundle.test,
        X=tuple(
            tuple(value + shift for value in row)
            for row in bundle.ml_bundle.test.X
        ),
    )
    ml_bundle = replace(
        bundle.ml_bundle,
        test=test_ml,
    )
    test_exp = replace(
        bundle.test,
        ml_split=test_ml,
    )
    return replace(
        bundle,
        ml_bundle=ml_bundle,
        test=test_exp,
    )


def test_final_test_fits_development_and_scores_test_once():
    bundle = _bundle()
    selection = _selection(bundle)

    report = evaluate_ridge_final_test(bundle, selection)

    assert report.version == RIDGE_FINAL_TEST_VERSION
    assert report.selection_id == selection.selection_id
    assert report.walk_forward_id == selection.walk_forward_id
    assert report.dataset_id == bundle.dataset_id
    assert report.feature_names == bundle.feature_names
    assert report.label_name == bundle.label_name
    assert report.alpha == selection.selected_alpha
    assert report.test_start_time == _time(8)
    assert report.development_candidate_count == 8
    assert report.purged_development_count == 0
    assert len(report.development_sample_keys) == 8
    assert report.test_count == 2
    assert len(report.predictions) == 2
    assert len(report.model_id) == 64
    assert len(report.final_test_id) == 64
    assert report.mae >= 0.0
    assert report.rmse >= 0.0
    assert tuple(
        item.feature_window_close for item in report.predictions
    ) == (_time(8), _time(9))
    assert tuple(
        item.label_value_id for item in report.predictions
    ) == tuple(
        item.label_value_id for item in bundle.test.metadata
    )
    assert all(
        item.residual == item.actual - item.predicted
        for item in report.predictions
    )

    again = evaluate_ridge_final_test(bundle, selection)
    assert again == report


def test_test_targets_change_final_evaluation_but_never_model_fit():
    original_bundle = _bundle(test_y_shift=0.0)
    changed_test = _bundle(test_y_shift=9999.0)
    selection = _selection(original_bundle)

    original = evaluate_ridge_final_test(
        original_bundle,
        selection,
    )
    changed = evaluate_ridge_final_test(
        changed_test,
        selection,
    )

    assert changed.model_id == original.model_id
    assert changed.intercept == original.intercept
    assert changed.coefficients == original.coefficients
    assert changed.feature_means == original.feature_means
    assert changed.feature_scales == original.feature_scales
    assert changed.final_test_id != original.final_test_id
    assert changed.rmse != original.rmse


def test_test_features_change_predictions_but_never_model_fit():
    bundle = _bundle()
    changed_test = _with_test_feature_shift(bundle, 10_000.0)
    selection = _selection(bundle)

    original = evaluate_ridge_final_test(bundle, selection)
    changed = evaluate_ridge_final_test(
        changed_test,
        selection,
    )

    assert changed.model_id == original.model_id
    assert changed.intercept == original.intercept
    assert changed.coefficients == original.coefficients
    assert changed.feature_means == original.feature_means
    assert changed.feature_scales == original.feature_scales
    assert changed.final_test_id != original.final_test_id
    assert tuple(item.predicted for item in changed.predictions) != tuple(
        item.predicted for item in original.predictions
    )


def test_selected_label_end_equal_test_boundary_is_purged():
    bundle = _bundle(
        crossing_ends={
            (7, "US.AAPL"): _time(8),
        }
    )
    selection = _selection(bundle)

    report = evaluate_ridge_final_test(bundle, selection)

    assert report.development_candidate_count == 8
    assert report.purged_development_count == 1
    assert len(report.development_sample_keys) == 7
    assert bundle.validation.metadata[-1].sample_key not in (
        report.development_sample_keys
    )


def test_selection_must_match_experiment_dataset_schema():
    one = _bundle(dataset_id="a" * 64)
    two = _bundle(dataset_id="b" * 64)
    selection = _selection(one)

    with pytest.raises(
        RidgeFinalTestError,
        match="selection schema differs",
    ):
        evaluate_ridge_final_test(two, selection)


def test_final_test_requires_non_empty_test_split():
    bundle = _bundle(test_periods=())
    selection = _selection(bundle)

    with pytest.raises(
        RidgeFinalTestError,
        match="non-empty TEST",
    ):
        evaluate_ridge_final_test(bundle, selection)


def test_final_test_requires_exact_input_types():
    bundle = _bundle()
    selection = _selection(bundle)

    with pytest.raises(
        RidgeFinalTestError,
        match="ExperimentDatasetBundle",
    ):
        evaluate_ridge_final_test(object(), selection)

    with pytest.raises(
        RidgeFinalTestError,
        match="RidgeAlphaSelectionResult",
    ):
        evaluate_ridge_final_test(bundle, object())


def test_final_report_identity_detects_metric_tampering():
    bundle = _bundle()
    report = evaluate_ridge_final_test(
        bundle,
        _selection(bundle),
    )

    with pytest.raises(
        RidgeFinalTestError,
        match="final_test_id differs",
    ):
        replace(
            report,
            mae=report.mae + 0.125,
        )
