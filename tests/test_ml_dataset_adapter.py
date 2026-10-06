"""Focused tests for ML Dataset Adapter V1."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from cross_day_dataset_helpers import fixture
from market_vault.cross_day_dataset import (
    VerifiedMultiSourceCrossDayDataset,
    join_multi_source_cross_day_dataset,
)
from market_vault.research import ml
from market_vault.research.ml import (
    ML_DATASET_ADAPTER_VERSION,
    MLDatasetError,
    build_ml_dataset,
)


def _live_dataset(tmp_path):
    return join_multi_source_cross_day_dataset(
        **fixture(tmp_path / "upstream", case="F")
    )


def _claimed_verified(live, tmp_path):
    claimed = object.__new__(VerifiedMultiSourceCrossDayDataset)
    object.__setattr__(
        claimed,
        "build_path",
        tmp_path / ("dataset_id=" + live.dataset_id),
    )
    object.__setattr__(claimed, "dataset_id", live.dataset_id)
    return claimed


def _admitted(tmp_path, monkeypatch):
    live = _live_dataset(tmp_path)
    claimed = _claimed_verified(live, tmp_path)
    calls = []

    def load(path):
        calls.append(path)
        return live

    monkeypatch.setattr(
        ml,
        "load_verified_multi_source_cross_day_dataset",
        load,
    )
    return live, claimed, calls


def test_default_projection_uses_all_features_and_chronological_split(
    tmp_path, monkeypatch
):
    live, claimed, calls = _admitted(tmp_path, monkeypatch)
    bundle = build_ml_dataset(
        claimed,
        label_field="cd_direction_1d",
    )

    expected_features = tuple(
        spec.name for spec in live.ts2_features.feature_specs
    ) + tuple(
        spec.name for spec in live.identity_input.observation_feature_specs
    )
    assert bundle.adapter_version == ML_DATASET_ADAPTER_VERSION
    assert bundle.dataset_id == live.dataset_id
    assert bundle.feature_names == expected_features
    assert bundle.label_name == "cd_direction_1d"
    assert bundle.label_logical_type == "int64"
    assert bundle.row_count == 1
    assert bundle.train.row_count == 1
    assert bundle.validation.row_count == 0
    assert bundle.test.row_count == 0
    assert calls == [claimed.build_path]

    fields = tuple(field.name for field in live.schema.fields)
    values = dict(zip(fields, live.rows[0]))
    assert bundle.train.X == (
        tuple(float(values[name]) for name in expected_features),
    )
    assert bundle.train.y == (values["cd_direction_1d"],)
    assert type(bundle.train.y[0]) is int
    assert bundle.train.metadata[0].sample_key == values["sample_key"]
    assert bundle.train.metadata[0].code == values["code"]
    assert (
        bundle.train.metadata[0].feature_window_close
        == values["feature_window_close"]
    )


def test_explicit_feature_subset_preserves_caller_order(tmp_path, monkeypatch):
    live, claimed, _ = _admitted(tmp_path, monkeypatch)
    selected = ("obs_count", "ts2_simple_return")
    bundle = build_ml_dataset(
        claimed,
        label_field="cd_return_1d",
        feature_fields=selected,
    )

    fields = tuple(field.name for field in live.schema.fields)
    values = dict(zip(fields, live.rows[0]))
    assert bundle.feature_names == selected
    assert bundle.train.X == ((
        float(values["obs_count"]),
        float(values["ts2_simple_return"]),
    ),)
    assert bundle.train.y == (values["cd_return_1d"],)
    assert type(bundle.train.y[0]) is float
    assert bundle.label_logical_type == "float64"


def test_to_pandas_returns_detached_ml_views(tmp_path, monkeypatch):
    _, claimed, _ = _admitted(tmp_path, monkeypatch)
    bundle = build_ml_dataset(
        claimed,
        label_field="cd_direction_1d",
        feature_fields=("ts2_simple_return", "obs_rate"),
    )
    X, y, metadata = bundle.train.to_pandas()

    assert isinstance(X, pd.DataFrame)
    assert isinstance(y, pd.Series)
    assert isinstance(metadata, pd.DataFrame)
    assert list(X.columns) == ["ts2_simple_return", "obs_rate"]
    assert X.shape == (1, 2)
    assert str(X.dtypes.iloc[0]) == "float64"
    assert y.name == "cd_direction_1d"
    assert str(y.dtype) == "int64"
    assert list(metadata.columns) == [
        "sample_key",
        "code",
        "feature_window_close",
    ]

    original = bundle.train.X[0][0]
    X.iloc[0, 0] = 999.0
    assert bundle.train.X[0][0] == original


def test_verified_artifact_is_reloaded_and_identity_change_fails(
    tmp_path, monkeypatch
):
    live = _live_dataset(tmp_path)
    claimed = _claimed_verified(live, tmp_path)

    changed = type("Fresh", (), {"dataset_id": "b" * 64})()
    monkeypatch.setattr(
        ml,
        "load_verified_multi_source_cross_day_dataset",
        lambda path: changed,
    )
    with pytest.raises(MLDatasetError, match="identity changed"):
        build_ml_dataset(claimed, label_field="cd_direction_1d")


def test_live_logical_dataset_is_not_accepted_as_ml_input(tmp_path):
    live = _live_dataset(tmp_path)
    with pytest.raises(MLDatasetError, match="Verified Research Dataset"):
        build_ml_dataset(live, label_field="cd_direction_1d")


@pytest.mark.parametrize(
    "feature_fields,match",
    [
        ("ts2_simple_return", "iterable of Feature names"),
        ((), "must not be empty"),
        (("ts2_simple_return", "ts2_simple_return"), "must be unique"),
        (("cd_direction_1d",), "non-Feature"),
        (("does_not_exist",), "non-Feature"),
    ],
)
def test_feature_selection_fails_closed(
    tmp_path, monkeypatch, feature_fields, match
):
    _, claimed, _ = _admitted(tmp_path, monkeypatch)
    with pytest.raises(MLDatasetError, match=match):
        build_ml_dataset(
            claimed,
            label_field="cd_direction_1d",
            feature_fields=feature_fields,
        )


@pytest.mark.parametrize("label", ["", "does_not_exist", "ts2_simple_return"])
def test_label_selection_fails_closed(tmp_path, monkeypatch, label):
    _, claimed, _ = _admitted(tmp_path, monkeypatch)
    with pytest.raises(MLDatasetError):
        build_ml_dataset(
            claimed,
            label_field=label,
        )


def test_split_lookup_is_exact(tmp_path, monkeypatch):
    _, claimed, _ = _admitted(tmp_path, monkeypatch)
    bundle = build_ml_dataset(
        claimed,
        label_field="cd_direction_1d",
    )
    assert bundle.split("TRAIN") is bundle.train
    assert bundle.split("VALIDATION") is bundle.validation
    assert bundle.split("TEST") is bundle.test
    with pytest.raises(MLDatasetError, match="TRAIN, VALIDATION, or TEST"):
        bundle.split("ALL")
