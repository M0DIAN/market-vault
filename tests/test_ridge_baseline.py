"""Focused numerical and leakage-boundary tests for Ridge Baseline V1."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from fractions import Fraction
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


@pytest.mark.parametrize("alpha", [.1, 1.0, 10.0])
@pytest.mark.parametrize(
    "features,quadratic",
    [
        (("x",), False),
        (("x", "copy", "constant", "negative"), False),
        (("x", "copy", "constant", "negative", "square", "mixed"), True),
    ],
    ids=("width-one", "mixed-duplicate-constant", "quadratic-width-27"),
)
def test_ridge_gram_matches_dense_oracle_with_one_product_per_pair(
    monkeypatch, features, quadratic, alpha,
):
    from market_vault.research import ridge_baseline as ridge
    from market_vault.research.intraday_models import fit_quadratic_rows
    from market_vault.research.intraday_research import fit_ridge_rows
    from market_vault.research.strategy_experiment import canonical_json

    def observation(key, value):
        values = {"x": value, "copy": value, "constant": .1,
                  "negative": -value, "square": value ** 2,
                  "mixed": value ** 3 - 2 * value}
        return {"observation_key": key,
                "features": {name: values[name] for name in features}}

    y = (.03, -.02, .01, 0.0, .04, -.01, .02)
    training = tuple((observation(f"train-{i}", float(i - 3)), {"value": value})
                     for i, value in enumerate(y))
    validation = tuple(observation(f"validation-{i}", value)
                       for i, value in enumerate((-4.0, .5, 5.0)))
    standardize, solve = ridge._standardize, ridge._solve
    captured = {}
    products = 0

    class Counted(float):
        def __mul__(self, other):
            nonlocal products
            if isinstance(other, Counted):
                products += 1
            return float(self) * float(other)

    def counted_standardize(X, means, scales):
        Z = standardize(X, means, scales)
        captured["Z"] = Z
        return tuple(tuple(Counted(value) for value in row) for row in Z)

    def capture_solve(matrix, vector):
        captured["matrix"], captured["vector"] = matrix, vector
        return solve(matrix, vector)

    monkeypatch.setattr(ridge, "_standardize", counted_standardize)
    monkeypatch.setattr(ridge, "_solve", capture_solve)
    fit = fit_quadratic_rows if quadratic else fit_ridge_rows
    options = {"boundary": "2025-03-03T14:30:00+00:00"}
    actual = fit(training, validation, features, alpha, **options)
    Z = captured["Z"]
    width = len(Z[0])
    assert width == (27 if quadratic else len(features))
    assert products == len(Z) * width * (width + 1) // 2

    # Independent full-matrix construction preserves every input row and
    # diagonal penalty; no triangle or fitted-result cache supplies this oracle.
    dense = tuple(tuple(math.fsum(row[left] * row[right] for row in Z)
                        + (alpha if left == right else 0.0)
                        for right in range(width)) for left in range(width))
    mean = math.fsum(y) / len(y)
    vector = tuple(math.fsum(row[column] * (target - mean)
                             for row, target in zip(Z, y)) for column in range(width))
    assert captured["matrix"] == dense
    assert captured["vector"] == vector
    monkeypatch.setattr(ridge, "_standardize", standardize)
    monkeypatch.setattr(ridge, "_solve", lambda matrix, rhs: solve(dense, vector))
    expected = fit(training, validation, features, alpha, **options)
    assert canonical_json(actual) == canonical_json(expected)


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


@pytest.mark.parametrize("constant", [0.1, -0.1])
def test_fractional_constant_feature_cannot_predict_validation_changes(constant):
    # fsum([0.1] * 3) / 3 differs from 0.1 by one ULP. A constant
    # Feature has no predictive direction, including outside its TRAIN value.
    report = evaluate_ridge_baseline(_plan(
        train_X=((constant,),) * 3,
        train_y=(0.01, 0.02, 0.03),
        validation_X=((constant,), (constant + 1.0,)),
        validation_y=(0.02, 0.02),
    ), alpha=1.0)
    fold = report.folds[0]
    assert fold.feature_means == (constant,)
    assert fold.feature_scales == fold.coefficients == (0.0,)
    assert fold.intercept == 0.02
    assert fold.mae == fold.rmse == report.mae == report.rmse == 0.0


def test_adjacent_nonconstant_features_keep_their_training_variation():
    adjacent = math.nextafter(1.0, math.inf)
    report = evaluate_ridge_baseline(_plan(
        train_X=((1.0,), (1.0,), (adjacent,)),
        train_y=(0.0, 0.0, 1.0),
        validation_X=((1.0,), (adjacent,)),
        validation_y=(0.0, 1.0),
    ), alpha=1.0)
    fold = report.folds[0]
    # Exact equality, not an epsilon cutoff, distinguishes this from a
    # constant. The mean rounds to 1, leaving one nonzero squared deviation.
    assert fold.feature_means == (1.0,)
    assert fold.feature_scales == (math.sqrt(math.ulp(1.0) ** 2 / 3),)
    assert fold.feature_scales[0] > 0.0
    assert fold.coefficients[0] > 0.0


def test_validation_features_never_enter_fit_or_standardization():
    one = evaluate_ridge_baseline(
        _plan(
            validation_X=((4.0,), (5.0,)),
            validation_y=(8.0, 10.0),
        ),
        alpha=1.0,
    )
    two = evaluate_ridge_baseline(
        _plan(
            validation_X=((4000.0,), (5000.0,)),
            validation_y=(8.0, 10.0),
        ),
        alpha=1.0,
    )

    left = one.folds[0]
    right = two.folds[0]
    assert left.feature_means == right.feature_means
    assert left.feature_scales == right.feature_scales
    assert left.coefficients == right.coefficients
    assert left.intercept == right.intercept


def test_constant_validation_target_has_no_r2():
    plan = _plan(validation_y=(8.0, 8.0))
    report = evaluate_ridge_baseline(plan, alpha=1.0)
    assert report.folds[0].r2 is None
    assert report.r2 is None


@pytest.mark.parametrize("constant", [0.03, -0.03])
def test_fractional_constant_validation_targets_have_no_r2(constant):
    report = evaluate_ridge_baseline(_plan(
        train_X=((0.0,),) * 3, train_y=(0.0,) * 3,
        validation_X=((0.0,),) * 9, validation_y=(constant,) * 9,
    ))
    assert report.folds[0].r2 is report.r2 is None
    assert report.mae == pytest.approx(abs(constant))
    assert report.rmse == pytest.approx(abs(constant))


def test_low_variance_single_fold_and_pooled_r2_agree():
    report = evaluate_ridge_baseline(_plan(
        train_X=((0.0,),) * 3, train_y=(0.01,) * 3,
        validation_X=((0.0,),) * 2, validation_y=(0.01 - 1e-10, 0.01 + 1e-10),
    ))
    assert report.folds[0].r2 == report.r2 == 0.0
    assert report.mae == report.folds[0].mae
    assert report.rmse == report.folds[0].rmse


def test_pooled_r2_uses_every_target_across_unequal_constant_folds():
    first = _plan(train_X=((0.0,),) * 3, train_y=(0.01,) * 3,
                  validation_X=((0.0,),) * 2, validation_y=(0.01,) * 2)
    second = _plan(train_X=((0.0,),) * 3, train_y=(0.01,) * 3,
                   validation_X=((0.0,),) * 3, validation_y=(0.01 + 1e-10,) * 3).folds[0]
    validation = replace(second.validation, metadata=_metadata(7, 3, sequence_start=201))
    second = replace(second, fold_index=1, fold_id="d" * 64,
                     validation_start_time=validation.metadata[0].feature_window_close,
                     validation_end_time=validation.metadata[-1].feature_window_close,
                     validation=validation)
    plan = replace(first, folds=(first.folds[0], second), development_sample_count=8)
    report = evaluate_ridge_baseline(plan)
    actual = [Fraction(y) for fold in plan.folds for y in fold.validation.y]
    prediction = Fraction(report.folds[0].intercept)
    mean = sum(actual) / len(actual)
    expected = 1 - sum((y - prediction) ** 2 for y in actual) / sum((y - mean) ** 2 for y in actual)
    assert all(fold.r2 is None for fold in report.folds)
    assert report.validation_sample_count == 5
    assert report.r2 == pytest.approx(float(expected), rel=1e-12)


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


@pytest.mark.parametrize("constant", [0.1, -0.1])
def test_constant_training_targets_cannot_create_a_predictive_direction(constant):
    plan = _plan(
        train_X=((1.0,), (1.0,), (math.nextafter(1.0, 2.0),)),
        train_y=(constant,) * 3,
        validation_X=((0.0,), (2.0,)), validation_y=(constant,) * 2,
    )
    report = evaluate_ridge_baseline(plan)
    fold = report.folds[0]
    assert fold.coefficients == (0.0,)
    assert fold.intercept == constant
    assert fold.mae == fold.rmse == report.mae == report.rmse == 0.0
    assert fold.r2 is report.r2 is None


def test_adjacent_nonconstant_training_targets_keep_their_predictive_direction():
    adjacent = math.nextafter(.1, .2)
    plan = _plan(train_y=(.1, .1, adjacent))
    fold = evaluate_ridge_baseline(plan).folds[0]
    # Three centered x values (-1, 0, 1), population variance 2/3,
    # and alpha 1 give slope (last_y - first_y) / (2 + 2/3).
    expected = (adjacent - .1) * 3 / 8
    assert fold.coefficients[0] == pytest.approx(expected, rel=1e-15, abs=0)
    assert fold.coefficients[0] != 0.0


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
