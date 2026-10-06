"""Focused tests for Experiment Metadata V1."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

import cross_day_helpers as cd
from cross_day_dataset_helpers import fixture
from market_vault.cross_day_dataset import (
    join_multi_source_cross_day_dataset,
    materialize_multi_source_cross_day_dataset_build,
)
from market_vault.dataset.split_models import ChronologicalSplitSpec
from market_vault.research.experiment import (
    EXPERIMENT_METADATA_VERSION,
    ExperimentMetadataError,
    ExperimentSampleMetadata,
    build_experiment_dataset,
)


def _materialized(tmp_path, *, case="F", **fixture_kwargs):
    inputs = fixture(tmp_path / "upstream", case=case, **fixture_kwargs)
    logical = join_multi_source_cross_day_dataset(**inputs)
    result = materialize_multi_source_cross_day_dataset_build(
        logical,
        output_root=tmp_path / "artifacts",
        built_at=cd.AS_OF + timedelta(days=30),
    )
    return logical, result.verified


def test_experiment_metadata_binds_selected_label_end_time(tmp_path):
    logical, verified = _materialized(tmp_path)
    experiment = build_experiment_dataset(
        verified,
        label_field="cd_direction_1d",
    )

    assert experiment.version == EXPERIMENT_METADATA_VERSION
    assert experiment.dataset_id == verified.dataset_id == logical.dataset_id
    assert experiment.label_name == "cd_direction_1d"
    assert experiment.row_count == 1
    assert experiment.train.row_count == 1
    assert experiment.validation.row_count == 0
    assert experiment.test.row_count == 0

    ml_meta = experiment.ml_bundle.train.metadata[0]
    exp_meta = experiment.train.metadata[0]
    assert exp_meta.sample_key == ml_meta.sample_key
    assert exp_meta.code == ml_meta.code
    assert exp_meta.feature_window_close == ml_meta.feature_window_close

    selected = next(
        value for value in verified.cross_day_labels.values
        if value.sample_key == exp_meta.sample_key
        and value.label_name == "cd_direction_1d"
    )
    assert selected.status == "COMPLETE"
    assert exp_meta.actual_label_end_time == selected.actual_label_end_time
    assert exp_meta.label_value_id == selected.value_id
    assert exp_meta.actual_label_end_time > exp_meta.feature_window_close

    assert experiment.train.X is experiment.ml_bundle.train.X
    assert experiment.train.y is experiment.ml_bundle.train.y
    assert experiment.split("TRAIN") is experiment.train
    assert experiment.split("VALIDATION") is experiment.validation
    assert experiment.split("TEST") is experiment.test


def test_selected_label_end_not_sample_wide_latest_end(tmp_path):
    labels = (
        cd.spec(
            1,
            "forward_open_to_close_return",
            name="execution_return_1d",
        ),
        cd.spec(
            2,
            "maximum_favorable_excursion",
            name="mfe_2d",
        ),
    )
    label_bars = (
        cd.bar(
            "2025-03-04",
            slot=1,
            open=120.0,
            close=150.0,
            high=160.0,
        ),
        cd.bar(
            "2025-03-05",
            slot=1,
            open=130.0,
            close=140.0,
            high=170.0,
        ),
    )
    schedule = cd.schedule((
        ("2025-03-03", "N"),
        ("2025-03-04", "N"),
        ("2025-03-05", "N"),
    ))
    split_spec = ChronologicalSplitSpec(
        "market-vault-chronological-split-spec-v1",
        "experiment_multi_label",
        "v1",
        "America/New_York",
        date(2025, 3, 6),
        date(2025, 3, 7),
        date(2025, 3, 8),
        "FEATURE_WINDOW_CLOSE_DATE",
        "ACTUAL_LABEL_END",
        "EXCLUDE",
        "EXCLUDE",
    )

    inputs = fixture(
        tmp_path / "upstream",
        label_specs=labels,
        label_bars=label_bars,
        schedule=schedule,
    )
    inputs["split_spec"] = split_spec
    logical = join_multi_source_cross_day_dataset(**inputs)
    materialized = materialize_multi_source_cross_day_dataset_build(
        logical,
        output_root=tmp_path / "artifacts",
        built_at=cd.AS_OF + timedelta(days=30),
    )
    verified = materialized.verified

    fields = tuple(field.name for field in verified.schema.fields)
    row = dict(zip(fields, verified.rows[0]))
    assert row["actual_label_end_time"] == cd.local("2025-03-05", 9, 40)

    experiment = build_experiment_dataset(
        verified,
        label_field="execution_return_1d",
    )
    metadata = experiment.train.metadata[0]
    assert metadata.actual_label_end_time == cd.local("2025-03-04", 9, 40)
    assert metadata.actual_label_end_time < row["actual_label_end_time"]

    selected = next(
        value for value in verified.cross_day_labels.values
        if value.label_name == "execution_return_1d"
    )
    assert metadata.label_value_id == selected.value_id


def test_experiment_requires_verified_artifact(tmp_path):
    logical = join_multi_source_cross_day_dataset(
        **fixture(tmp_path / "upstream", case="F")
    )
    with pytest.raises(
        ExperimentMetadataError,
        match="Verified Research Dataset",
    ):
        build_experiment_dataset(
            logical,
            label_field="cd_direction_1d",
        )


def test_experiment_feature_subset_preserves_ml_projection(tmp_path):
    _, verified = _materialized(tmp_path)
    selected = ("obs_rate", "ts2_simple_return")
    experiment = build_experiment_dataset(
        verified,
        label_field="cd_return_1d",
        feature_fields=selected,
    )
    assert experiment.feature_names == selected
    assert experiment.train.feature_names == selected
    assert experiment.train.ml_split.feature_names == selected
    assert experiment.train.row_count == 1


def test_experiment_metadata_rejects_nonfuture_label_end():
    close = cd.local("2025-03-03", 9, 40)
    with pytest.raises(
        ExperimentMetadataError,
        match="must end after feature_window_close",
    ):
        ExperimentSampleMetadata(
            "a" * 64,
            "US.AAPL",
            close,
            close,
            "b" * 64,
        )


def test_experiment_split_lookup_is_exact(tmp_path):
    _, verified = _materialized(tmp_path)
    experiment = build_experiment_dataset(
        verified,
        label_field="cd_direction_1d",
    )
    with pytest.raises(
        ExperimentMetadataError,
        match="TRAIN, VALIDATION, or TEST",
    ):
        experiment.split("ALL")
