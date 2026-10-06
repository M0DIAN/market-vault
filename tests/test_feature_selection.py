"""Focused leakage and policy contracts for Feature Selection V1."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from market_vault.research import feature_selection
from market_vault.research.feature_selection import (
    FEATURE_SELECTION_VERSION,
    REASON_RANK_IC_DRIFT_EXCEEDS_MAXIMUM,
    REASON_RANK_IC_SIGN_MISMATCH,
    REASON_TRAIN_RANK_IC_UNAVAILABLE,
    REASON_VALIDATION_RANK_IC_UNAVAILABLE,
    FeatureSelectionError,
    FeatureSelectionPolicy,
    select_features,
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


def _bundle(*, reverse_test: bool = False):
    y = (1.0, 2.0, 3.0, 4.0)
    train_X = (
        (1.0, 1.0, 5.0),
        (2.0, 2.0, 5.0),
        (3.0, 3.0, 5.0),
        (4.0, 4.0, 5.0),
    )
    validation_X = (
        (10.0, 4.0, 5.0),
        (20.0, 3.0, 5.0),
        (30.0, 2.0, 5.0),
        (40.0, 1.0, 5.0),
    )
    test_stable = (4.0, 3.0, 2.0, 1.0) if reverse_test else (1.0, 2.0, 3.0, 4.0)
    test_X = tuple(
        (test_stable[index], 100.0 + index, 5.0)
        for index in range(4)
    )
    return MLDatasetBundle(
        ML_DATASET_ADAPTER_VERSION,
        "a" * 64,
        FEATURES,
        LABEL,
        "float64",
        _split("TRAIN", train_X, y, start_day=1),
        _split("VALIDATION", validation_X, y, start_day=10),
        _split("TEST", test_X, y, start_day=20),
    )


def _policy(**changes):
    values = dict(
        minimum_train_samples=4,
        minimum_validation_samples=4,
        minimum_abs_train_rank_ic=0.5,
        minimum_abs_validation_rank_ic=0.5,
        maximum_rank_ic_drift=0.5,
        require_same_sign=True,
    )
    values.update(changes)
    return FeatureSelectionPolicy(**values)


def test_train_validation_gate_selects_stable_and_rejects_flip_constant():
    report = select_features(
        _bundle(),
        policy=_policy(),
        quantile_count=2,
    )
    assert report.version == FEATURE_SELECTION_VERSION
    assert report.dataset_id == "a" * 64
    assert report.label_name == LABEL
    assert report.selected_features == ("stable",)
    assert tuple(item.feature_name for item in report.decisions) == FEATURES

    decisions = {item.feature_name: item for item in report.decisions}

    stable = decisions["stable"]
    assert stable.selected is True
    assert stable.reason_codes == ()
    assert stable.train_rank_ic == pytest.approx(1.0)
    assert stable.validation_rank_ic == pytest.approx(1.0)
    assert stable.rank_ic_drift == pytest.approx(0.0)
    assert stable.rank_ic_sign_consistent is True

    flip = decisions["flip"]
    assert flip.selected is False
    assert flip.train_rank_ic == pytest.approx(1.0)
    assert flip.validation_rank_ic == pytest.approx(-1.0)
    assert flip.rank_ic_sign_consistent is False
    assert flip.rank_ic_drift == pytest.approx(2.0)
    assert flip.reason_codes == (
        REASON_RANK_IC_SIGN_MISMATCH,
        REASON_RANK_IC_DRIFT_EXCEEDS_MAXIMUM,
    )

    constant = decisions["constant"]
    assert constant.selected is False
    assert constant.train_rank_ic is None
    assert constant.validation_rank_ic is None
    assert constant.rank_ic_drift is None
    assert constant.rank_ic_sign_consistent is None
    assert constant.reason_codes == (
        REASON_TRAIN_RANK_IC_UNAVAILABLE,
        REASON_VALIDATION_RANK_IC_UNAVAILABLE,
    )


def test_test_split_is_never_consulted_or_used_for_selection(monkeypatch):
    original = feature_selection.analyze_features
    calls = []

    def guarded(bundle, *, split, feature_names=None, quantile_count=5):
        calls.append(split)
        if split == "TEST":
            pytest.fail("Feature Selection V1 consulted TEST")
        return original(
            bundle,
            split=split,
            feature_names=feature_names,
            quantile_count=quantile_count,
        )

    monkeypatch.setattr(feature_selection, "analyze_features", guarded)

    one = select_features(_bundle(reverse_test=False), policy=_policy())
    two = select_features(_bundle(reverse_test=True), policy=_policy())

    assert calls == ["TRAIN", "VALIDATION", "TRAIN", "VALIDATION"]
    assert one.selected_features == two.selected_features == ("stable",)
    assert one.decisions == two.decisions


def test_explicit_feature_subset_preserves_requested_order():
    report = select_features(
        _bundle(),
        policy=_policy(maximum_rank_ic_drift=2.0, require_same_sign=False),
        feature_names=("flip", "stable"),
        quantile_count=2,
    )
    assert tuple(item.feature_name for item in report.decisions) == (
        "flip",
        "stable",
    )
    assert report.selected_features == ("flip", "stable")


def test_sample_thresholds_are_explicit_policy_rejections():
    report = select_features(
        _bundle(),
        policy=_policy(
            minimum_train_samples=5,
            minimum_validation_samples=6,
        ),
        feature_names=("stable",),
    )
    decision = report.decisions[0]
    assert decision.selected is False
    assert decision.reason_codes == (
        "TRAIN_SAMPLE_COUNT_BELOW_MINIMUM",
        "VALIDATION_SAMPLE_COUNT_BELOW_MINIMUM",
    )


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"minimum_train_samples": True}, "non-negative integer"),
        ({"minimum_validation_samples": -1}, "non-negative integer"),
        ({"minimum_abs_train_rank_ic": 1.1}, "within"),
        ({"minimum_abs_validation_rank_ic": float("nan")}, "within"),
        ({"maximum_rank_ic_drift": 2.1}, "within"),
        ({"require_same_sign": 1}, "boolean"),
    ],
)
def test_invalid_policy_fails_closed(changes, match):
    with pytest.raises(FeatureSelectionError, match=match):
        _policy(**changes)


@pytest.mark.parametrize("quantiles", [True, 1, 11, 5.0])
def test_invalid_quantile_count_fails_closed(quantiles):
    with pytest.raises(FeatureSelectionError, match="quantile_count"):
        select_features(
            _bundle(),
            policy=_policy(),
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
def test_invalid_feature_subset_is_wrapped_locally(feature_names, match):
    with pytest.raises(FeatureSelectionError, match=match):
        select_features(
            _bundle(),
            policy=_policy(),
            feature_names=feature_names,
        )


def test_wrong_input_and_policy_types_fail_locally():
    with pytest.raises(FeatureSelectionError, match="MLDatasetBundle"):
        select_features(object(), policy=_policy())
    with pytest.raises(FeatureSelectionError, match="FeatureSelectionPolicy"):
        select_features(_bundle(), policy=object())
