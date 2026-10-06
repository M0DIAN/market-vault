"""Focused mathematical contracts for Feature Research V1."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math

import pytest

from market_vault.research.feature_research import (
    FEATURE_RESEARCH_VERSION,
    FeatureResearchError,
    _average_ranks,
    analyze_features,
)
from market_vault.research.ml import (
    ML_DATASET_ADAPTER_VERSION,
    MLDatasetBundle,
    MLDatasetSplit,
    MLSampleMetadata,
)


UTC = timezone.utc
FEATURES = ("good", "bad", "constant")
LABEL = "forward_return_5d"


def _metadata(count: int):
    start = datetime(2026, 1, 1, 15, tzinfo=UTC)
    return tuple(
        MLSampleMetadata(
            f"{index + 1:064x}",
            "US.AAPL",
            start + timedelta(days=index),
        )
        for index in range(count)
    )


def _split(name: str, X=(), y=()):
    return MLDatasetSplit(
        name,
        FEATURES,
        LABEL,
        "float64",
        tuple(tuple(float(value) for value in row) for row in X),
        tuple(float(value) for value in y),
        _metadata(len(y)),
    )


def _bundle():
    X = (
        (1.0, 5.0, 1.0),
        (2.0, 4.0, 1.0),
        (3.0, 3.0, 1.0),
        (4.0, 2.0, 1.0),
        (5.0, 1.0, 1.0),
    )
    y = (1.0, 2.0, 3.0, 4.0, 5.0)
    return MLDatasetBundle(
        ML_DATASET_ADAPTER_VERSION,
        "a" * 64,
        FEATURES,
        LABEL,
        "float64",
        _split("TRAIN", X, y),
        _split("VALIDATION"),
        _split("TEST"),
    )


def test_perfect_positive_negative_ic_and_tail_spread():
    report = analyze_features(_bundle(), split="TRAIN", quantile_count=5)
    assert report.version == FEATURE_RESEARCH_VERSION
    assert report.dataset_id == "a" * 64
    assert report.label_name == LABEL
    assert report.split == "TRAIN"
    assert report.quantile_count == 5

    metrics = {metric.feature_name: metric for metric in report.metrics}

    good = metrics["good"]
    assert good.sample_count == 5
    assert good.feature_mean == pytest.approx(3.0)
    assert good.feature_std == pytest.approx(math.sqrt(2.0))
    assert good.pearson_ic == pytest.approx(1.0)
    assert good.rank_ic == pytest.approx(1.0)
    assert good.bottom_count == 1
    assert good.top_count == 1
    assert good.bottom_label_mean == pytest.approx(1.0)
    assert good.top_label_mean == pytest.approx(5.0)
    assert good.top_bottom_spread == pytest.approx(4.0)

    bad = metrics["bad"]
    assert bad.pearson_ic == pytest.approx(-1.0)
    assert bad.rank_ic == pytest.approx(-1.0)
    assert bad.bottom_label_mean == pytest.approx(5.0)
    assert bad.top_label_mean == pytest.approx(1.0)
    assert bad.top_bottom_spread == pytest.approx(-4.0)

    constant = metrics["constant"]
    assert constant.feature_mean == pytest.approx(1.0)
    assert constant.feature_std == 0.0
    assert constant.pearson_ic is None
    assert constant.rank_ic is None
    assert constant.bottom_count == 0
    assert constant.top_count == 0
    assert constant.bottom_label_mean is None
    assert constant.top_label_mean is None
    assert constant.top_bottom_spread is None


def test_average_rank_ties_are_deterministic():
    assert _average_ranks((10.0, 10.0, 20.0, 30.0, 30.0)) == (
        1.5,
        1.5,
        3.0,
        4.5,
        4.5,
    )


def test_explicit_feature_subset_preserves_requested_order():
    report = analyze_features(
        _bundle(),
        feature_names=("bad", "good"),
        quantile_count=2,
    )
    assert tuple(metric.feature_name for metric in report.metrics) == (
        "bad",
        "good",
    )
    assert all(metric.sample_count == 5 for metric in report.metrics)


def test_two_quantile_tails_never_overlap_on_odd_sample_count():
    metric = analyze_features(
        _bundle(),
        feature_names=("good",),
        quantile_count=2,
    ).metrics[0]
    assert metric.bottom_count == 2
    assert metric.top_count == 3
    assert metric.bottom_count + metric.top_count == metric.sample_count
    assert metric.bottom_label_mean == pytest.approx(1.5)
    assert metric.top_label_mean == pytest.approx(4.0)
    assert metric.top_bottom_spread == pytest.approx(2.5)


def test_empty_split_reports_no_fabricated_statistics():
    report = analyze_features(_bundle(), split="VALIDATION")
    assert tuple(metric.feature_name for metric in report.metrics) == FEATURES
    for metric in report.metrics:
        assert metric.sample_count == 0
        assert metric.feature_mean is None
        assert metric.feature_std is None
        assert metric.pearson_ic is None
        assert metric.rank_ic is None
        assert metric.bottom_count == metric.top_count == 0
        assert metric.top_bottom_spread is None


@pytest.mark.parametrize("quantiles", [True, 1, 11, 5.0])
def test_invalid_quantile_count_fails_closed(quantiles):
    with pytest.raises(FeatureResearchError, match="quantile_count"):
        analyze_features(_bundle(), quantile_count=quantiles)


@pytest.mark.parametrize(
    "feature_names,match",
    [
        ("good", "iterable of Feature names"),
        ((), "must not be empty"),
        (("good", "good"), "must be unique"),
        (("missing",), "unknown Feature"),
    ],
)
def test_invalid_feature_selection_fails_closed(feature_names, match):
    with pytest.raises(FeatureResearchError, match=match):
        analyze_features(_bundle(), feature_names=feature_names)


def test_invalid_split_and_wrong_input_type_fail_locally():
    with pytest.raises(FeatureResearchError, match="TRAIN, VALIDATION, or TEST"):
        analyze_features(_bundle(), split="ALL")
    with pytest.raises(FeatureResearchError, match="MLDatasetBundle"):
        analyze_features(object())


def test_rank_ic_handles_label_ties_with_average_ranks():
    X = (
        (1.0, 0.0, 0.0),
        (2.0, 0.0, 0.0),
        (3.0, 0.0, 0.0),
        (4.0, 0.0, 0.0),
    )
    y = (0.0, 0.0, 1.0, 1.0)
    bundle = MLDatasetBundle(
        ML_DATASET_ADAPTER_VERSION,
        "b" * 64,
        FEATURES,
        LABEL,
        "float64",
        _split("TRAIN", X, y),
        _split("VALIDATION"),
        _split("TEST"),
    )
    metric = analyze_features(
        bundle,
        feature_names=("good",),
        quantile_count=2,
    ).metrics[0]

    expected = math.sqrt(0.8)
    assert metric.rank_ic == pytest.approx(expected)
    assert metric.pearson_ic == pytest.approx(expected)
