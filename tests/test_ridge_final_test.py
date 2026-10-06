"""Focused leakage and identity tests for Ridge Final TEST Evaluation V1."""

from __future__ import annotations

from dataclasses import replace
import math

import pytest

from market_vault.research.ridge_final_test import (
    RIDGE_FINAL_TEST_VERSION,
    RidgeFinalTestError,
    evaluate_ridge_final_test,
)
from market_vault.research.ridge_selection import select_ridge_alpha
from market_vault.research.walk_forward import build_walk_forward_plan
from test_walk_forward_experiment import FEATURES, LABEL, _bundle, _time


def _plan(bundle, *, minimum_train_periods=3):
    return build_walk_forward_plan(
        bundle,
        minimum_train_periods=minimum_train_periods,
        validation_periods=2,
        step_periods=2,
    )


def _selection(plan):
    return select_ridge_alpha(
        plan,
        alphas=(0.1, 1.0, 10.0),
    )


def test_final_fit_uses_all_purged_development_and_scores_test_once():
    bundle = _bundle()
    plan = _plan(bundle)
    selection = _selection(plan)

    result = evaluate_ridge_final_test(bundle, plan, selection)

    assert result.version == RIDGE_FINAL_TEST_VERSION
    assert result.selection_id == selection.selection_id
    assert result.walk_forward_id == plan.walk_forward_id
    assert result.dataset_id == bundle.dataset_id
    assert result.feature_names == FEATURES
    assert result.label_name == LABEL
    assert result.alpha == selection.selected_alpha
    assert result.test_start_time == _time(8)

    assert result.development_candidate_count == 8
    assert result.development_purged_count == 0
    assert result.development_count == 8
    assert result.test_count == 2
    assert len(result.development_keys_digest) == 64
    assert len(result.model_id) == 64
    assert len(result.final_test_id) == 64

    # The final fit uses all TRAIN+VALIDATION development rows (periods 0..7),
    # not only one walk-forward fold's TRAIN slice.
    assert result.feature_means == pytest.approx((4.5, 45.0))
    assert result.feature_scales == pytest.approx(
        (math.sqrt(5.25), math.sqrt(525.0))
    )
    assert len(result.coefficients) == len(FEATURES)
    assert len(result.predictions) == 2
    assert tuple(
        item.feature_window_close for item in result.predictions
    ) == (_time(8), _time(9))
    assert result.mae >= 0.0
    assert result.rmse >= 0.0


def test_test_targets_change_test_result_but_not_final_model():
    one = _bundle(test_y_shift=0.0)
    two = _bundle(test_y_shift=9999.0)

    plan_one = _plan(one)
    plan_two = _plan(two)
    assert plan_one == plan_two

    selection_one = _selection(plan_one)
    selection_two = _selection(plan_two)
    assert selection_one == selection_two

    left = evaluate_ridge_final_test(one, plan_one, selection_one)
    right = evaluate_ridge_final_test(two, plan_two, selection_two)

    # TEST targets are invisible to alpha selection and final fitting.
    assert left.model_id == right.model_id
    assert left.development_keys_digest == right.development_keys_digest
    assert left.alpha == right.alpha
    assert left.intercept == right.intercept
    assert left.coefficients == right.coefficients
    assert left.feature_means == right.feature_means
    assert left.feature_scales == right.feature_scales

    # TEST evaluation itself must reflect the changed held-out targets.
    assert left.final_test_id != right.final_test_id
    assert left.mae != right.mae
    assert left.rmse != right.rmse
    assert tuple(item.actual for item in left.predictions) != tuple(
        item.actual for item in right.predictions
    )


def test_selected_label_end_equal_to_test_boundary_is_purged():
    bundle = _bundle(
        crossing_ends={
            (7, "US.AAPL"): _time(8),
        },
    )
    plan = _plan(bundle)
    selection = _selection(plan)

    result = evaluate_ridge_final_test(bundle, plan, selection)

    assert result.test_start_time == _time(8)
    assert result.development_candidate_count == 8
    assert result.development_purged_count == 1
    assert result.development_count == 7


def test_plan_is_rebuilt_from_exact_experiment_bundle():
    bundle = _bundle()
    plan = _plan(bundle)
    selection = _selection(plan)

    other = _bundle(dataset_id="b" * 64)
    with pytest.raises(
        RidgeFinalTestError,
        match="WalkForwardPlan differs from the supplied Experiment Dataset",
    ):
        evaluate_ridge_final_test(other, plan, selection)


def test_selection_must_belong_to_exact_walk_forward_plan():
    bundle = _bundle()
    plan = _plan(bundle)
    other_plan = _plan(bundle, minimum_train_periods=2)
    other_selection = _selection(other_plan)

    with pytest.raises(
        RidgeFinalTestError,
        match="alpha selection differs from Walk-Forward schema",
    ):
        evaluate_ridge_final_test(bundle, plan, other_selection)


def test_empty_test_split_fails_closed():
    bundle = _bundle(test_periods=())
    # Walk-Forward can still describe development with a held_out_test_count=0.
    plan = _plan(bundle)
    selection = _selection(plan)

    with pytest.raises(
        RidgeFinalTestError,
        match="held-out TEST split must not be empty",
    ):
        evaluate_ridge_final_test(bundle, plan, selection)


def test_result_identities_reject_tampering():
    bundle = _bundle()
    plan = _plan(bundle)
    selection = _selection(plan)
    result = evaluate_ridge_final_test(bundle, plan, selection)

    with pytest.raises(
        RidgeFinalTestError,
        match="model_id differs",
    ):
        replace(result, model_id="0" * 64)

    with pytest.raises(
        RidgeFinalTestError,
        match="final_test_id differs",
    ):
        replace(result, final_test_id="0" * 64)

    first = result.predictions[0]
    with pytest.raises(
        RidgeFinalTestError,
        match="prediction_id differs",
    ):
        replace(first, predicted=first.predicted + 1.0)


def test_wrong_input_types_fail_locally():
    bundle = _bundle()
    plan = _plan(bundle)
    selection = _selection(plan)

    with pytest.raises(RidgeFinalTestError, match="ExperimentDatasetBundle"):
        evaluate_ridge_final_test(object(), plan, selection)
    with pytest.raises(RidgeFinalTestError, match="WalkForwardPlan"):
        evaluate_ridge_final_test(bundle, object(), selection)
    with pytest.raises(RidgeFinalTestError, match="RidgeAlphaSelectionResult"):
        evaluate_ridge_final_test(bundle, plan, object())
