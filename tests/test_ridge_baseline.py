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


def test_centered_ridge_predictions_preserve_the_fractional_threshold_oracle():
    from types import SimpleNamespace
    from market_vault.research.intraday_research import fit_ridge_rows
    from market_vault.research.ridge_trading_selection import _validation_predictions
    from market_vault.research.strategy_comparison import RidgeStrategy, _strategy_signals

    delta = 2.0 ** -50
    targets = (.99933 / 1.0 - 1.0, 0.0, 1.00067 / 1.0 - 1.0)
    # For symmetric X and population scaling, Z'Z=3. Alpha=1 shrinks
    # the unregularized endpoint forecast by 3/4. Fraction uses the exact
    # admitted binary targets, independently of the production fit/solver.
    exact_mean = sum(map(Fraction, targets)) / 3
    endpoint = exact_mean + Fraction(3, 8) * (Fraction(targets[2]) - Fraction(targets[0]))
    expected = (float(endpoint), float(exact_mean))
    assert expected[0] > .0005
    tolerance = 8 * math.ulp(expected[0])

    for origin in (1.0, 0.0):
        train_X = tuple((origin + value,) for value in (-delta, 0.0, delta))
        validation_X = ((origin + delta,), (origin,))
        plan = _plan(train_X=train_X, train_y=targets,
                     validation_X=validation_X, validation_y=expected)
        report = evaluate_ridge_baseline(plan, alpha=1.0)
        assert report.rmse == pytest.approx(0.0, abs=tolerance)
        fold = report.folds[0]
        assert fold.target_mean == float(exact_mean)

        signals, _ = _strategy_signals(RidgeStrategy("ridge", 1.0, .0005), plan, {})
        assert tuple(signals.values()) == pytest.approx(expected, rel=0.0, abs=tolerance)
        selected = SimpleNamespace(selected_report=report, selected_alpha=1.0)
        trading = _validation_predictions(plan, selected)
        assert tuple(row.predicted for row in trading) == pytest.approx(expected, rel=0.0, abs=tolerance)

        rows = tuple(({"observation_key": f"train-{index}", "features": {"x": values[0]}},
                      {"value": target}) for index, (values, target) in enumerate(zip(train_X, targets)))
        observations = tuple({"observation_key": f"validation-{index}", "features": {"x": values[0]}}
                             for index, values in enumerate(validation_X))
        model, scores = fit_ridge_rows(rows, observations, ["x"], 1.0,
                                      boundary="2025-03-03T14:30:00+00:00")
        assert scores == pytest.approx(expected, rel=0.0, abs=tolerance)
        assert tuple(score > .0005 for score in scores) == (True, False)
        restored = tuple(math.fsum((model["target_mean"], model["target_center_offset"], *(
            coefficient * (((observation["features"][feature] - mean) - offset) / scale if scale else 0.0)
            for feature, coefficient, mean, scale, offset in zip(model["feature_fields"],
                model["standardized_coefficients"], model["means"], model["scales"],
                model["feature_center_offsets"], strict=True))))
            for observation in observations)
        assert restored == scores


@pytest.mark.parametrize("origin", [0.0, 1.0, -1.0])
@pytest.mark.parametrize("alpha", [.1, 1.0, 10.0])
def test_asymmetric_train_centers_preserve_the_linear_threshold_oracle(origin, alpha):
    from market_vault.research.intraday_research import fit_ridge_rows

    unit = math.ulp(1.0)
    training_x = (origin, origin, origin + unit)
    targets = (0.0, 0.0, .003)
    rows = tuple(({"observation_key": f"train-{i}", "features": {"x": x}}, {"value": target})
                 for i, (x, target) in enumerate(zip(training_x, targets, strict=True)))
    observations = tuple({"observation_key": f"validation-{i}", "features": {"x": x}}
                         for i, x in enumerate((origin, origin + unit)))
    # A one-column population-standardized fit has Z'Z=n. Its centered
    # predictions shrink by n/(n+alpha); no fitted production parameter is
    # used to obtain this exact binary-input oracle.
    target_mean = sum(map(Fraction, targets)) / 3
    shrink = Fraction(3) / (3 + Fraction(alpha))
    expected = tuple(float(target_mean + shrink * (Fraction(y) - target_mean))
                     for y in (targets[0], targets[-1]))
    model, scores = fit_ridge_rows(rows, observations, ["x"], alpha,
                                  boundary="2025-03-03T14:30:00+00:00")
    assert scores == pytest.approx(expected, rel=0.0, abs=8 * math.ulp(max(expected)))
    if alpha == 1.0:
        assert tuple(score > .0005 for score in scores) == (False, True)
    exact_center = sum(map(Fraction, training_x)) / len(training_x)
    assert model["means"] == [float(exact_center)]
    assert model["feature_center_offsets"][0] == pytest.approx(
        float(exact_center - Fraction(model["means"][0])), rel=1e-15, abs=0.0)
    reconstructed = tuple(math.fsum((model["target_mean"], model["target_center_offset"],
        model["standardized_coefficients"][0] * (((row["features"]["x"] - model["means"][0])
             - model["feature_center_offsets"][0]) / model["scales"][0]))) for row in observations)
    assert reconstructed == scores


@pytest.mark.parametrize("origin", [0.0, 1.0, -1.0])
def test_asymmetric_quadratic_train_centers_preserve_the_threshold_oracle(origin):
    from market_vault.research.intraday_models import fit_quadratic_rows

    unit = math.ulp(1.0)
    offsets = tuple(map(Fraction, (0, 1, 1, 3)))
    targets = tuple(map(Fraction, (0.0, 0.0, 0.0, .003)))
    mean = sum(offsets) / len(offsets)
    centered = tuple(x - mean for x in offsets)
    variance = sum(x * x for x in centered) / len(centered)
    squared = tuple(x * x - variance for x in centered)
    square_variance = sum(x * x for x in squared) / len(squared)
    target_mean = sum(targets) / len(targets)
    # Eliminate both square roots algebraically: standardizing a column is
    # equivalent to adding alpha * population_variance to its raw Gram
    # diagonal. Solve this two-column system independently with Fractions.
    a = sum(x * x for x in centered) + variance
    b = sum(x * z for x, z in zip(centered, squared, strict=True))
    c = sum(z * z for z in squared) + square_variance
    u = sum(x * (y - target_mean) for x, y in zip(centered, targets, strict=True))
    v = sum(z * (y - target_mean) for z, y in zip(squared, targets, strict=True))
    determinant = a * c - b * b
    slope = (u * c - v * b) / determinant
    curvature = (v * a - u * b) / determinant
    query = Fraction(2) - mean
    expected = float(target_mean + slope * query + curvature * (query * query - variance))
    rows = tuple(({"observation_key": f"train-{i}", "features": {"x": origin + float(x) * unit}},
                  {"value": float(y)}) for i, (x, y) in enumerate(zip(offsets, targets, strict=True)))
    observations = ({"observation_key": "validation", "features": {"x": origin + 2 * unit}},)
    model, scores = fit_quadratic_rows(rows, observations, ["x"], 1.0,
                                      boundary="2025-03-03T14:30:00+00:00")
    assert scores[0] == pytest.approx(expected, rel=0.0, abs=16 * math.ulp(expected))
    assert scores[0] < .001


@pytest.mark.parametrize("constant", [.1, -.1])
def test_nonconstant_train_mean_references_use_the_complete_center(constant):
    from market_vault.research.ridge_baseline import _training_target_mean

    adjacent = math.nextafter(constant, math.copysign(math.inf, constant))
    targets = (constant, constant, adjacent)
    expected = float(sum(map(Fraction, targets)) / len(targets))
    assert _training_target_mean(targets) == expected
    report = evaluate_ridge_baseline(_plan(train_X=((0.0,),) * 3, train_y=targets,
        validation_X=((0.0,),) * 2, validation_y=(expected,) * 2))
    assert report.folds[0].target_mean == expected
    assert report.rmse == 0.0


def test_train_mean_retains_supported_opposite_finite_extremes():
    from market_vault.research.ridge_baseline import _training_target_mean

    assert _training_target_mean((-1e308, 1e308)) == 0.0


@pytest.mark.parametrize("units", [(1, 0), (1, 2), (2, 3), (3, 4), (1, 4), (1, -2),
    (1, 0, 0), (2, 0, 0), (2 ** 52 - 1, 2 ** 52 - 2), (2 ** 52 - 1, 2 ** 52)])
@pytest.mark.parametrize("sign", [1.0, -1.0])
@pytest.mark.parametrize("reverse", [False, True])
def test_subnormal_train_mean_and_zero_threshold_match_fraction(units, sign, reverse):
    from market_vault.research.intraday_research import fit_ridge_rows
    from market_vault.research.ridge_baseline import _training_target_mean

    tiny = math.nextafter(0.0, 1.0)
    targets = tuple(sign * value * tiny for value in units)
    if reverse:
        targets = targets[::-1]
    expected = float(sum(map(Fraction, targets)) / len(targets))
    rows = tuple(({"observation_key": f"train-{i}", "features": {"x": 0.0}}, {"value": target})
                 for i, target in enumerate(targets))
    model, predictions = fit_ridge_rows(rows, ({"features": {"x": 0.0}},), ["x"], 1.0,
                                        boundary="2025-03-03T14:30:00+00:00")
    assert (_training_target_mean(targets), model["target_mean"], predictions) == (
        expected, expected, (expected,))
    assert tuple(score > 0.0 for score in predictions) == (expected > 0.0,)
    assert model["standardized_coefficients"] == model["scales"] == [0.0]
    assert predictions == (math.fsum((model["target_mean"], model["target_center_offset"])),)


@pytest.mark.parametrize("sign", [1.0, -1.0])
@pytest.mark.parametrize("reverse", [False, True])
def test_subnormal_center_tie_after_nonzero_offset_matches_fraction(sign, reverse):
    from market_vault.research.intraday_research import fit_ridge_rows
    from market_vault.research.ridge_baseline import _training_target_mean

    tiny = math.nextafter(0.0, 1.0)
    # The origin-shifted mean is 3*tiny and its first rounded offset is
    # -2*tiny: the half-unit tie remains only after that nonzero feedback.
    targets = tuple(sign * value for value in (5 * tiny, 1.0, -1.0, -3 * tiny))
    if reverse:
        targets = targets[::-1]
    expected = float(sum(map(Fraction, targets)) / len(targets))
    rows = tuple(({"observation_key": f"train-{i}", "features": {"x": 0.0}}, {"value": target})
                 for i, target in enumerate(targets))
    model, predictions = fit_ridge_rows(rows, ({"features": {"x": 0.0}},), ["x"], 1.0,
                                        boundary="2025-03-03T14:30:00+00:00")
    assert (_training_target_mean(targets), model["target_mean"], predictions) == (
        expected, expected, (expected,))
    assert tuple(score > 0.0 for score in predictions) == (False,)
    assert predictions == (math.fsum((model["target_mean"], model["target_center_offset"])),)


@pytest.mark.parametrize("values", [
    (0.0, math.ulp(1.0)), (0.0, 0.0, math.ulp(1.0)),
    (1.0, math.nextafter(1.0, math.inf)),
    (.1, math.nextafter(.1, math.inf)),
    (-.1, math.nextafter(-.1, -math.inf)),
    (.1, math.nextafter(0.0, 1.0), .2),
    (-.1, math.nextafter(0.0, -1.0), -.2),
])
def test_train_center_retains_fraction_mean_and_offset_at_rounding_boundaries(values):
    from market_vault.research.ridge_baseline import _training_center

    exact_mean = sum(map(Fraction, values)) / len(values)
    mean, offset = _training_center(values)
    assert mean == float(exact_mean)
    assert offset == pytest.approx(float(exact_mean - Fraction(mean)), rel=1e-15, abs=0.0)


def test_centered_ridge_prediction_only_reorders_an_overflowing_standardization():
    from market_vault.research.intraday_research import fit_ridge_rows

    unit = 1e-20
    observations = tuple({"observation_key": f"validation-{index}", "features": {"x": value}}
                         for index, value in enumerate((1e300, -1e300)))

    def training(target):
        return tuple(({"observation_key": f"train-{index}", "features": {"x": x}}, {"value": y})
                     for index, (x, y) in enumerate(zip((0.0, unit, 2 * unit), (0.0, target, 2 * target))))

    def oracle(target, x):
        # Three equally spaced samples with population scaling and alpha=1
        # shrink the exact centered slope by 3/4. No production fit supplies it.
        slope = Fraction(3, 4) * Fraction(target) / Fraction(unit)
        return Fraction(target) + slope * (Fraction(x) - Fraction(unit))

    expected = tuple(float(oracle(1e-100, row["features"]["x"])) for row in observations)
    assert all(math.isfinite(value) for value in expected)
    model, scores = fit_ridge_rows(training(1e-100), observations, ["x"], 1.0,
                                  boundary="2025-03-03T14:30:00+00:00")
    assert math.isinf((observations[0]["features"]["x"] - model["means"][0]) / model["scales"][0])
    assert model["standardized_coefficients"][0] != 0.0
    assert scores == pytest.approx(expected, rel=0.0, abs=8 * math.ulp(expected[0]))
    assert oracle(1e100, observations[0]["features"]["x"]) > 2 ** 1024
    with pytest.raises(RidgeBaselineError, match="ridge prediction is not finite"):
        fit_ridge_rows(training(1e100), observations, ["x"], 1.0,
                       boundary="2025-03-03T14:30:00+00:00")


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

    def counted_standardize(X, means, scales, center_offsets):
        Z = standardize(X, means, scales, center_offsets)
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
    mean = sum(map(Fraction, y)) / len(y)
    vector = tuple(math.fsum(row[column] * float(Fraction(target) - mean)
                             for row, target in zip(Z, y)) for column in range(width))
    assert captured["matrix"] == dense
    assert captured["vector"] == pytest.approx(vector, rel=0.0,
        abs=8 * math.ulp(max(abs(value) for value in vector)))
    monkeypatch.setattr(ridge, "_standardize", standardize)
    # The exact byte oracle isolates symmetric Gram reuse; target-centering
    # accuracy is checked independently against the Fraction vector above.
    monkeypatch.setattr(ridge, "_solve", lambda matrix, rhs: solve(dense, captured["vector"]))
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
    # constant. The displayed mean rounds to 1; its saved correction retains
    # the exact center and population variance 2 * ulp**2 / 9.
    assert fold.feature_means == (1.0,)
    assert fold.feature_scales == (math.sqrt(2 * math.ulp(1.0) ** 2 / 9),)
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
    assert left.feature_center_offsets == right.feature_center_offsets
    assert left.target_mean == right.target_mean
    assert left.target_center_offset == right.target_center_offset
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


@pytest.mark.parametrize("origin", [0.01, -0.01])
def test_asymmetric_adjacent_targets_use_the_exact_center_for_r2(origin):
    actual = (origin, origin, math.nextafter(origin, math.inf))
    exact = tuple(map(Fraction, actual))
    mean = sum(exact) / len(exact)
    expected = 1 - sum((value - Fraction(origin)) ** 2 for value in exact) / sum(
        (value - mean) ** 2 for value in exact
    )
    assert expected == Fraction(-1, 2)
    for shift in (0.0, origin):
        report = evaluate_ridge_baseline(_plan(
            train_X=((0.0,),) * 3, train_y=(origin - shift,) * 3,
            validation_X=((0.0,),) * 3,
            validation_y=tuple(value - shift for value in actual),
        ))
        assert report.folds[0].r2 == pytest.approx(float(expected), rel=0.0, abs=1e-15)
        assert report.r2 == pytest.approx(float(expected), rel=0.0, abs=1e-15)
        assert report.rmse > 0.0


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


@pytest.mark.parametrize("changes,message", [
    ({"target_center_offset": math.inf}, "target_center_offset must be finite"),
    ({"target_center_offset": True}, "target_center_offset must be numeric"),
    ({"feature_center_offsets": (math.nan,)}, "feature_center_offsets value must be finite"),
    ({"feature_center_offsets": (0.0, 0.0)}, "parameter vector widths differ"),
])
def test_fold_complete_center_rejects_nonfinite_or_incomplete_parameters(changes, message):
    fold = evaluate_ridge_baseline(_plan()).folds[0]
    with pytest.raises(RidgeBaselineError, match=message):
        replace(fold, **changes)


@pytest.mark.parametrize("constant", [0.1, -0.1])
@pytest.mark.parametrize("validation_X", [((0.0,), (2.0,)), ((-1e308,), (1e308,))])
def test_constant_training_targets_cannot_create_a_predictive_direction(constant, validation_X):
    plan = _plan(
        train_X=((1.0,), (1.0,), (math.nextafter(1.0, 2.0),)),
        train_y=(constant,) * 3,
        validation_X=validation_X, validation_y=(constant,) * 2,
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
