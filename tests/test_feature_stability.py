"""Focused mathematical contracts for Feature Stability V1."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from market_vault.research.feature_stability import (
    FEATURE_STABILITY_VERSION,
    FeatureStabilityError,
    compare_feature_stability,
)
from market_vault.research.ml import (
    ML_DATASET_ADAPTER_VERSION,
    MLDatasetBundle,
    MLDatasetSplit,
    MLSampleMetadata,
)


UTC = timezone.utc
FEATURES = ("stable", "flip", "constant")
LABEL = "forward_return_5d"


def _metadata(count: int, *, start_day: int):
    start = datetime(2026, 1, start_day, 15, tzinfo=UTC)
    return tuple(
        MLSampleMetadata(
            f"{start_day * 100 + index + 1:064x}",
            "US.AAPL",
            start + timedelta(days=index),
        )
        for index in range(count)
    )


def _split(name: str, X=(), y=(), *, start_day: int):
    return MLDatasetSplit(
        name,
        FEATURES,
        LABEL,
        "float64",
        tuple(tuple(float(value) for value in row) for row in X),
        tuple(float(value) for value in y),
        _metadata(len(y), start_day=start_day),
    )


def _bundle_with_flip():
    train_y = (1.0, 2.0, 3.0, 4.0)
    train_X = (
        (1.0, 1.0, 5.0),
        (2.0, 2.0, 5.0),
        (3.0, 3.0, 5.0),
        (4.0, 4.0, 5.0),
    )
    validation_y = (1.0, 2.0, 3.0, 4.0)
    validation_X = (
        (10.0, 4.0, 5.0),
        (20.0, 3.0, 5.0),
        (30.0, 2.0, 5.0),
        (40.0, 1.0, 5.0),
    )
    test_y = (2.0, 4.0, 6.0, 8.0)
    test_X = (
        (2.0, 8.0, 5.0),
        (4.0, 6.0, 5.0),
        (6.0, 4.0, 5.0),
        (8.0, 2.0, 5.0),
    )
    return MLDatasetBundle(
        ML_DATASET_ADAPTER_VERSION,
        "a" * 64,
        FEATURES,
        LABEL,
        "float64",
        _split("TRAIN", train_X, train_y, start_day=1),
        _split("VALIDATION", validation_X, validation_y, start_day=10),
        _split("TEST", test_X, test_y, start_day=20),
    )


def _bundle_train_only():
    X = (
        (1.0, 4.0, 5.0),
        (2.0, 3.0, 5.0),
        (3.0, 2.0, 5.0),
        (4.0, 1.0, 5.0),
    )
    y = (1.0, 2.0, 3.0, 4.0)
    return MLDatasetBundle(
        ML_DATASET_ADAPTER_VERSION,
        "b" * 64,
        FEATURES,
        LABEL,
        "float64",
        _split("TRAIN", X, y, start_day=1),
        _split("VALIDATION", start_day=10),
        _split("TEST", start_day=20),
    )


def test_stable_feature_and_sign_flip_are_reported_without_composite_score():
    report = compare_feature_stability(
        _bundle_with_flip(),
        quantile_count=2,
    )
    assert report.version == FEATURE_STABILITY_VERSION
    assert report.dataset_id == "a" * 64
    assert report.label_name == LABEL
    assert report.quantile_count == 2
    assert tuple(metric.feature_name for metric in report.metrics) == FEATURES

    metrics = {metric.feature_name: metric for metric in report.metrics}

    stable = metrics["stable"]
    assert (
        stable.train_sample_count,
        stable.validation_sample_count,
        stable.test_sample_count,
    ) == (4, 4, 4)
    assert stable.train_pearson_ic == pytest.approx(1.0)
    assert stable.validation_pearson_ic == pytest.approx(1.0)
    assert stable.test_pearson_ic == pytest.approx(1.0)
    assert stable.pearson_available_count == 3
    assert stable.pearson_sign_consistent is True
    assert stable.pearson_range == pytest.approx(0.0)
    assert stable.rank_sign_consistent is True
    assert stable.rank_range == pytest.approx(0.0)
    assert stable.spread_sign_consistent is True
    assert stable.spread_available_count == 3

    flip = metrics["flip"]
    assert flip.train_pearson_ic == pytest.approx(1.0)
    assert flip.validation_pearson_ic == pytest.approx(-1.0)
    assert flip.test_pearson_ic == pytest.approx(-1.0)
    assert flip.pearson_available_count == 3
    assert flip.pearson_sign_consistent is False
    assert flip.pearson_range == pytest.approx(2.0)
    assert flip.rank_sign_consistent is False
    assert flip.rank_range == pytest.approx(2.0)
    assert flip.spread_sign_consistent is False

    constant = metrics["constant"]
    assert constant.pearson_available_count == 0
    assert constant.pearson_sign_consistent is None
    assert constant.pearson_range is None
    assert constant.rank_available_count == 0
    assert constant.rank_sign_consistent is None
    assert constant.rank_range is None
    assert constant.spread_available_count == 0
    assert constant.spread_sign_consistent is None
    assert constant.spread_range is None

    assert not hasattr(stable, "score")
    assert not hasattr(report, "ranking")


def test_one_available_split_does_not_fake_stability():
    report = compare_feature_stability(
        _bundle_train_only(),
        feature_names=("stable", "flip"),
        quantile_count=2,
    )
    stable, flip = report.metrics

    assert tuple(metric.feature_name for metric in report.metrics) == (
        "stable",
        "flip",
    )
    for metric in (stable, flip):
        assert metric.train_sample_count == 4
        assert metric.validation_sample_count == 0
        assert metric.test_sample_count == 0
        assert metric.pearson_available_count == 1
        assert metric.pearson_sign_consistent is None
        assert metric.pearson_range is None
        assert metric.rank_available_count == 1
        assert metric.rank_sign_consistent is None
        assert metric.rank_range is None
        assert metric.spread_available_count == 1
        assert metric.spread_sign_consistent is None
        assert metric.spread_range is None


def test_feature_subset_preserves_requested_order():
    report = compare_feature_stability(
        _bundle_with_flip(),
        feature_names=("flip", "stable"),
        quantile_count=2,
    )
    assert tuple(metric.feature_name for metric in report.metrics) == (
        "flip",
        "stable",
    )


@pytest.mark.parametrize("quantiles", [True, 1, 11, 5.0])
def test_invalid_quantile_count_fails_closed(quantiles):
    with pytest.raises(FeatureStabilityError, match="quantile_count"):
        compare_feature_stability(
            _bundle_with_flip(),
            quantile_count=quantiles,
        )


@pytest.mark.parametrize(
    "feature_names,match",
    [
        ("stable", "iterable of Feature names"),
        ((), "must not be empty"),
        (("stable", "stable"), "must be unique"),
        (("missing",), "unknown Feature"),
    ],
)
def test_invalid_feature_selection_is_wrapped_locally(feature_names, match):
    with pytest.raises(FeatureStabilityError, match=match):
        compare_feature_stability(
            _bundle_with_flip(),
            feature_names=feature_names,
        )


def test_wrong_input_type_fails_locally():
    with pytest.raises(FeatureStabilityError, match="MLDatasetBundle"):
        compare_feature_stability(object())


def test_zero_is_neutral_but_opposite_nonzero_signs_are_not_consistent():
    from market_vault.research.feature_stability import _sign_consistent

    assert _sign_consistent((0.2, 0.0, 0.1)) is True
    assert _sign_consistent((-0.2, 0.0, -0.1)) is True
    assert _sign_consistent((0.2, 0.0, -0.1)) is False
    assert _sign_consistent((0.0, 0.0, None)) is True
    assert _sign_consistent((0.0, None, None)) is None
