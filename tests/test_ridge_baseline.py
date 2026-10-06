"""Focused numerical and leakage-boundary tests for Ridge Baseline V1."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math

import pytest

from market_vault.research.experiment import ExperimentSampleMetadata
from market_vault.research.ridge_baseline import (
    RIDGE_BASELINE_VERSION,
    RidgeBaselineError,
    evaluate_ridge_baseline,
)
from market_vault.research.walk_forward import (
    WALK_FORWARD_VERSION,
    WalkForwardFold,
    WalkForwardPlan,
    WalkForwardSlice,
)


UTC = timezone.utc
LABEL = "forward_return_5d"


def _time(day: int) -> datetime:
    return datetime(2026, 1, day, 15, tzinfo=UTC)


def _metadata(start: int, count: int, *, sequence_start: int):
    result = []
    for index in range(count):
        close = _time(start + index)
        result.append(
            ExperimentSampleMetadata(
                f"{sequence_start + index:064x}",
                "US.AAPL",
                close,
                close + timedelta(hours=1),
                f"{20_000 + sequence_start + index:064x}",
            )
        )
    return tuple(result)


def _plan(
    *,
    feature_names=("x",),
    train_X=((1.0,), (2.0,), (3.0,)),
    train_y=(2.0, 4.0, 6.0),
    validation_X=((4.0,), (5.0,)),
    validation_y=(8.0, 10.0),
    label_logical_type="float64",
    held_out_test_count=7,
):
    train = WalkForwardSlice(
        "TRAIN",
        feature_names,
        LABEL,
        label_logical_type,
        tuple(tuple(float(value) for value in row) for row in train_X),
        tuple(
            int(value) if label_logical_type == "int64" else float(value)
            for value in train_y
        ),
        _metadata(1, len(train_y), sequence_start=1),
    )
    validation = WalkForwardSlice(
        "VALIDATION",
        feature_names,
        LABEL,
        label_logical_type,
        tuple(tuple(float(value) for value in row) for row in validation_X),
        tuple(
            int(value) if label_logical_type == "int64" else float(value)
            for value in validation_y
        ),
        _metadata(4, len(validation_y), sequence_start=101),
    )
    fold = WalkForwardFold(
        0,
        "b" * 64,
        validation.metadata[0].feature_window_close,
        validation.metadata[-1].feature_window_close,
        train.row_count,
        0,
        train,
        validation,
    )
    return WalkForwardPlan(
        WALK_FORWARD_VERSION,
        "c" * 64,
        "a" * 64,
        feature_names,
        LABEL,
        label_logical_type,
        3,
        2,
        2,
        5,
        train.row_count + validation.row_count,
        held_out_test_count,
        (fold,),
    )


def test_ridge_baseline_closed_form_shrinkage_and_metrics():
    report = evaluate_ridge_baseline(_plan(), alpha=1.0)

    assert report.version == RIDGE_BASELINE_VERSION
    assert report.walk_forward_id == "c" * 64
    assert report.dataset_id == "a" * 64
    assert report.feature_names == ("x",)
    assert report.label_name == LABEL
    assert report.alpha == 1.0
    assert report.validation_sample_count == 2
    assert len(report.folds) == 1

    fold = report.folds[0]
    assert fold.feature_means == pytest.approx((2.0,))
    assert fold.feature_scales == pytest.approx((math.sqrt(2.0 / 3.0),))
    assert fold.coefficients == pytest.approx((1.5,))
    assert fold.intercept == pytest.approx(1.0)
    assert fold.mae == pytest.approx(1.25)
    assert fold.rmse == pytest.approx(math.sqrt(1.625))
    assert fold.r2 == pytest.approx(-0.625)

    assert report.mae == pytest.approx(1.25)
    assert report.rmse == pytest.approx(math.sqrt(1.625))
    assert report.r2 == pytest.approx(-0.625)


def test_constant_feature_is_zero_weight_after_train_only_standardization():
    plan = _plan(
        feature_names=("x", "constant"),
        train_X=((1.0, 5.0), (2.0, 5.0), (3.0, 5.0)),
        validation_X=((4.0, 5.0), (5.0, 5.0)),
    )
    report = evaluate_ridge_baseline(plan, alpha=1.0)
    fold = report.folds[0]

    assert fold.feature_means == pytest.approx((2.0, 5.0))
    assert fold.feature_scales == pytest.approx(
        (math.sqrt(2.0 / 3.0), 0.0)
    )
    assert fold.coefficients == pytest.approx((1.5, 0.0))
    assert fold.intercept == pytest.approx(1.0)


def test_constant_validation_target_has_no_r2():
    plan = _plan(validation_y=(8.0, 8.0))
    report = evaluate_ridge_baseline(plan, alpha=1.0)
    assert report.folds[0].r2 is None
    assert report.r2 is None


def test_held_out_test_count_cannot_change_model_results():
    one = evaluate_ridge_baseline(
        _plan(held_out_test_count=0),
        alpha=1.0,
    )
    two = evaluate_ridge_baseline(
        _plan(held_out_test_count=999),
        alpha=1.0,
    )
    assert one == two


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf"), True])
def test_invalid_alpha_fails_closed(bad):
    with pytest.raises(RidgeBaselineError):
        evaluate_ridge_baseline(_plan(), alpha=bad)


def test_classifier_label_is_not_silently_treated_as_regression():
    plan = _plan(
        train_y=(1, 0, 1),
        validation_y=(0, 1),
        label_logical_type="int64",
    )
    with pytest.raises(
        RidgeBaselineError,
        match="float64 regression Labels only",
    ):
        evaluate_ridge_baseline(plan)


def test_wrong_input_type_fails_locally():
    with pytest.raises(
        RidgeBaselineError,
        match="WalkForwardPlan",
    ):
        evaluate_ridge_baseline(object())
