"""Focused tests for leakage-safe Purged Walk-Forward V1."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from market_vault.research.experiment import (
    EXPERIMENT_METADATA_VERSION,
    ExperimentDatasetBundle,
    ExperimentSampleMetadata,
    ExperimentSplit,
)
from market_vault.research.ml import (
    ML_DATASET_ADAPTER_VERSION,
    MLDatasetBundle,
    MLDatasetSplit,
    MLSampleMetadata,
)
from market_vault.research.walk_forward import (
    PURGED_WALK_FORWARD_VERSION,
    PurgedWalkForwardError,
    PurgedWalkForwardSpec,
    build_purged_walk_forward,
)


UTC = timezone.utc
FEATURES = ("f1", "f2")
LABEL = "forward_return_5d"
DATASET_ID = "a" * 64


def _dt(day: int, hour: int = 10) -> datetime:
    return datetime(2026, 1, day, hour, tzinfo=UTC)


def _key(index: int) -> str:
    return f"{index:064x}"


def _ml_split(name, indices):
    metadata = tuple(
        MLSampleMetadata(
            _key(index),
            "US.AAPL",
            _dt(index),
        )
        for index in indices
    )
    return MLDatasetSplit(
        name,
        FEATURES,
        LABEL,
        "float64",
        tuple((float(index), float(index * 10)) for index in indices),
        tuple(float(index) / 100.0 for index in indices),
        metadata,
    )


def _experiment_split(ml_split, label_end_days):
    metadata = tuple(
        ExperimentSampleMetadata(
            ml_meta.sample_key,
            ml_meta.code,
            ml_meta.feature_window_close,
            _dt(end_day),
            f"{1000 + int(ml_meta.sample_key, 16):064x}",
        )
        for ml_meta, end_day in zip(
            ml_split.metadata,
            label_end_days,
        )
    )
    return ExperimentSplit(ml_split.split, ml_split, metadata)


def _bundle():
    train_ml = _ml_split("TRAIN", (1, 2, 3, 4, 5))
    validation_ml = _ml_split("VALIDATION", (6, 7, 8))
    test_ml = _ml_split("TEST", (9,))

    # Fold 0 validation starts at day 4:
    # day 3 label ends exactly day 4 -> purge.
    # Fold 1 validation starts at day 6:
    # day 5 label ends exactly day 6 -> purge, while day 3 has matured.
    train_exp = _experiment_split(
        train_ml,
        (2, 3, 4, 5, 6),
    )
    validation_exp = _experiment_split(
        validation_ml,
        (7, 8, 9),
    )
    test_exp = _experiment_split(
        test_ml,
        (10,),
    )
    ml_bundle = MLDatasetBundle(
        ML_DATASET_ADAPTER_VERSION,
        DATASET_ID,
        FEATURES,
        LABEL,
        "float64",
        train_ml,
        validation_ml,
        test_ml,
    )
    return ExperimentDatasetBundle(
        EXPERIMENT_METADATA_VERSION,
        DATASET_ID,
        FEATURES,
        LABEL,
        "float64",
        ml_bundle,
        train_exp,
        validation_exp,
        test_exp,
    )


def _keys(metadata):
    return tuple(item.sample_key for item in metadata)


def test_purged_walk_forward_exact_boundary_and_expanding_training():
    bundle = _bundle()
    plan = build_purged_walk_forward(
        bundle,
        initial_train_samples=3,
        validation_samples=2,
        step_samples=2,
    )

    assert plan.version == PURGED_WALK_FORWARD_VERSION
    assert plan.dataset_id == DATASET_ID
    assert plan.feature_names == FEATURES
    assert plan.label_name == LABEL
    assert plan.source_train_count == 5
    assert plan.source_validation_count == 3
    assert plan.source_test_count == 1
    assert plan.fold_count == 2
    assert plan.unused_tail_count == 1

    first, second = plan.folds

    assert first.validation_start_time == _dt(4)
    assert first.validation_end_time == _dt(5)
    assert first.train_candidate_count == 3
    assert _keys(first.train.metadata) == (_key(1), _key(2))
    assert _keys(first.purged_metadata) == (_key(3),)
    assert _keys(first.validation.metadata) == (_key(4), _key(5))
    assert first.purged_metadata[0].actual_label_end_time == first.validation_start_time

    assert second.validation_start_time == _dt(6)
    assert second.validation_end_time == _dt(7)
    assert second.train_candidate_count == 5
    assert _keys(second.train.metadata) == (
        _key(1), _key(2), _key(3), _key(4),
    )
    assert _keys(second.purged_metadata) == (_key(5),)
    assert _keys(second.validation.metadata) == (_key(6), _key(7))

    # Day-3 was purged from fold 0, but is valid in fold 1 once its Label
    # has matured before the later validation boundary.
    assert _key(3) in _keys(second.train.metadata)


def test_test_split_is_never_admitted_to_walk_forward_folds():
    plan = build_purged_walk_forward(
        _bundle(),
        initial_train_samples=3,
        validation_samples=2,
        step_samples=2,
    )
    test_key = _key(9)
    for fold in plan.folds:
        assert test_key not in _keys(fold.train.metadata)
        assert test_key not in _keys(fold.validation.metadata)
        assert test_key not in _keys(fold.purged_metadata)


def test_fold_partitions_preserve_exact_X_y_alignment():
    bundle = _bundle()
    plan = build_purged_walk_forward(
        bundle,
        initial_train_samples=3,
        validation_samples=2,
        step_samples=2,
    )
    first = plan.folds[0]

    assert first.train.X == (
        (1.0, 10.0),
        (2.0, 20.0),
    )
    assert first.train.y == (0.01, 0.02)
    assert first.validation.X == (
        (4.0, 40.0),
        (5.0, 50.0),
    )
    assert first.validation.y == (0.04, 0.05)


@pytest.mark.parametrize(
    "kwargs,match",
    [
        (
            {
                "initial_train_samples": 0,
                "validation_samples": 2,
                "step_samples": 2,
            },
            "positive integer",
        ),
        (
            {
                "initial_train_samples": 3,
                "validation_samples": 2,
                "step_samples": 1,
            },
            "step_samples must be >= validation_samples",
        ),
        (
            {
                "initial_train_samples": 7,
                "validation_samples": 2,
                "step_samples": 2,
            },
            "one complete walk-forward fold",
        ),
    ],
)
def test_walk_forward_spec_and_capacity_fail_closed(kwargs, match):
    with pytest.raises(PurgedWalkForwardError, match=match):
        build_purged_walk_forward(_bundle(), **kwargs)


def test_walk_forward_refuses_boundary_that_splits_same_time_cohort():
    bundle = _bundle()

    train_ml = bundle.ml_bundle.train
    ml_metadata = list(train_ml.metadata)
    original = ml_metadata[2]
    ml_metadata[2] = MLSampleMetadata(
        original.sample_key,
        original.code,
        _dt(4),
    )
    changed_train_ml = MLDatasetSplit(
        "TRAIN",
        train_ml.feature_names,
        train_ml.label_name,
        train_ml.label_logical_type,
        train_ml.X,
        train_ml.y,
        tuple(ml_metadata),
    )
    changed_ml_bundle = MLDatasetBundle(
        ML_DATASET_ADAPTER_VERSION,
        bundle.dataset_id,
        bundle.feature_names,
        bundle.label_name,
        bundle.label_logical_type,
        changed_train_ml,
        bundle.ml_bundle.validation,
        bundle.ml_bundle.test,
    )

    exp_metadata = list(bundle.train.metadata)
    exp_original = exp_metadata[2]
    exp_metadata[2] = ExperimentSampleMetadata(
        exp_original.sample_key,
        exp_original.code,
        _dt(4),
        _dt(5),
        exp_original.label_value_id,
    )
    changed_train = ExperimentSplit(
        "TRAIN",
        changed_train_ml,
        tuple(exp_metadata),
    )
    changed_bundle = ExperimentDatasetBundle(
        EXPERIMENT_METADATA_VERSION,
        bundle.dataset_id,
        bundle.feature_names,
        bundle.label_name,
        bundle.label_logical_type,
        changed_ml_bundle,
        changed_train,
        bundle.validation,
        bundle.test,
    )

    with pytest.raises(
        PurgedWalkForwardError,
        match="splits a feature_window_close cohort",
    ):
        build_purged_walk_forward(
            changed_bundle,
            initial_train_samples=3,
            validation_samples=2,
            step_samples=2,
        )


def test_fold_fails_when_purge_removes_every_training_sample():
    bundle = _bundle()
    # First validation starts at day 2. The sole training candidate (day 1)
    # has selected Label end at day 2, so equality must purge it.
    with pytest.raises(
        PurgedWalkForwardError,
        match="purge removed every training sample",
    ):
        build_purged_walk_forward(
            bundle,
            initial_train_samples=1,
            validation_samples=2,
            step_samples=2,
        )


def test_exact_experiment_bundle_type_required():
    with pytest.raises(
        PurgedWalkForwardError,
        match="ExperimentDatasetBundle",
    ):
        build_purged_walk_forward(
            object(),
            initial_train_samples=3,
            validation_samples=2,
            step_samples=2,
        )


def test_spec_is_explicit_and_immutable():
    spec = PurgedWalkForwardSpec(3, 2, 2)
    assert spec.initial_train_samples == 3
    assert spec.validation_samples == 2
    assert spec.step_samples == 2
