"""Focused leakage-safety tests for Walk-Forward Fold V1."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

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
    WALK_FORWARD_VERSION,
    WalkForwardError,
    WalkForwardSpec,
    generate_walk_forward_folds,
)


UTC = timezone.utc
FEATURES = ("signal",)
LABEL = "forward_return_5d"


def _close(index: int):
    return datetime(2026, 1, 1, 10, tzinfo=UTC) + timedelta(days=index)


def _ml_split(name: str, count: int, *, start_index: int = 0):
    metadata = tuple(
        MLSampleMetadata(
            f"{index + 1:064x}",
            "US.AAPL",
            _close(index),
        )
        for index in range(start_index, start_index + count)
    )
    return MLDatasetSplit(
        name,
        FEATURES,
        LABEL,
        "float64",
        tuple((float(index),) for index in range(start_index, start_index + count)),
        tuple(float(index) for index in range(start_index, start_index + count)),
        metadata,
    )


def _experiment(label_ends=None, *, validation_count=0, test_count=0):
    train_ml = _ml_split("TRAIN", 8)
    validation_ml = _ml_split("VALIDATION", validation_count, start_index=20)
    test_ml = _ml_split("TEST", test_count, start_index=40)
    ml_bundle = MLDatasetBundle(
        ML_DATASET_ADAPTER_VERSION,
        "a" * 64,
        FEATURES,
        LABEL,
        "float64",
        train_ml,
        validation_ml,
        test_ml,
    )

    if label_ends is None:
        label_ends = (
            _close(1) - timedelta(hours=10),
            _close(2) - timedelta(hours=10),
            _close(4),  # equal to first validation start -> PURGE
            _close(3) + timedelta(hours=10),
            _close(5) - timedelta(hours=10),
            _close(6),  # equal to second validation start -> PURGE
            _close(7) - timedelta(hours=10),
            _close(8) - timedelta(hours=10),
        )

    train_meta = tuple(
        ExperimentSampleMetadata(
            ml_meta.sample_key,
            ml_meta.code,
            ml_meta.feature_window_close,
            end,
            f"{100 + index:064x}",
        )
        for index, (ml_meta, end) in enumerate(
            zip(train_ml.metadata, label_ends)
        )
    )

    def empty_metadata(ml_split, seed):
        return tuple(
            ExperimentSampleMetadata(
                item.sample_key,
                item.code,
                item.feature_window_close,
                item.feature_window_close + timedelta(hours=1),
                f"{seed + index:064x}",
            )
            for index, item in enumerate(ml_split.metadata)
        )

    train = ExperimentSplit("TRAIN", train_ml, train_meta)
    validation = ExperimentSplit(
        "VALIDATION",
        validation_ml,
        empty_metadata(validation_ml, 200),
    )
    test = ExperimentSplit(
        "TEST",
        test_ml,
        empty_metadata(test_ml, 300),
    )
    return ExperimentDatasetBundle(
        EXPERIMENT_METADATA_VERSION,
        "a" * 64,
        FEATURES,
        LABEL,
        "float64",
        ml_bundle,
        train,
        validation,
        test,
    )


def test_expanding_folds_purge_and_embargo_by_selected_label_end():
    plan = generate_walk_forward_folds(
        _experiment(),
        WalkForwardSpec(
            initial_train_samples=4,
            minimum_retained_train_samples=2,
            validation_samples=2,
            step_samples=2,
            embargo_seconds=86400,
        ),
    )

    assert plan.version == WALK_FORWARD_VERSION
    assert plan.dataset_id == "a" * 64
    assert plan.source_split == "TRAIN"
    assert plan.source_row_count == 8
    assert plan.fold_count == 2
    assert plan.unused_tail_count == 0

    first, second = plan.folds

    assert first.validation_indices == (4, 5)
    assert first.train_indices == (0, 1)
    assert first.purged_indices == (2,)
    assert first.embargoed_indices == (3,)
    assert first.validation_start_time == _close(4)
    assert first.validation_end_time == _close(5)
    assert first.train_sample_keys == (
        f"{1:064x}",
        f"{2:064x}",
    )

    assert second.validation_indices == (6, 7)
    assert second.train_indices == (0, 1, 2, 3, 4)
    assert second.purged_indices == (5,)
    assert second.embargoed_indices == ()
    assert set(first.validation_indices).isdisjoint(second.validation_indices)


def test_zero_embargo_keeps_recent_nonoverlapping_training_sample():
    plan = generate_walk_forward_folds(
        _experiment(),
        WalkForwardSpec(
            initial_train_samples=4,
            minimum_retained_train_samples=2,
            validation_samples=2,
            step_samples=2,
            embargo_seconds=0,
        ),
    )
    first = plan.folds[0]
    assert first.purged_indices == (2,)
    assert first.embargoed_indices == ()
    assert first.train_indices == (0, 1, 3)


def test_label_end_equal_to_validation_start_is_purged():
    first = generate_walk_forward_folds(
        _experiment(),
        WalkForwardSpec(4, 2, 2, 2, 0),
    ).folds[0]
    assert 2 in first.purged_indices
    assert 2 not in first.train_indices


def test_purge_takes_precedence_over_embargo():
    first = generate_walk_forward_folds(
        _experiment(),
        WalkForwardSpec(4, 2, 2, 2, 3 * 86400),
    ).folds[0]
    assert 2 in first.purged_indices
    assert 2 not in first.embargoed_indices


def test_final_validation_and_test_holdouts_are_not_fold_sources():
    experiment = _experiment(validation_count=2, test_count=2)
    plan = generate_walk_forward_folds(
        experiment,
        WalkForwardSpec(4, 2, 2, 2, 0),
    )
    assert plan.source_row_count == experiment.train.row_count == 8
    assert all(
        index < experiment.train.row_count
        for fold in plan.folds
        for index in fold.validation_indices
    )


@pytest.mark.parametrize(
    "args,match",
    [
        ((0, 1, 2, 2, 0), "initial_train_samples"),
        ((4, 0, 2, 2, 0), "minimum_retained_train_samples"),
        ((4, 5, 2, 2, 0), "<= initial_train_samples"),
        ((4, 2, 0, 2, 0), "validation_samples"),
        ((4, 2, 2, 0, 0), "step_samples"),
        ((4, 2, 3, 2, 0), "non-overlapping"),
        ((4, 2, 2, 2, -1), "embargo_seconds"),
        ((True, 2, 2, 2, 0), "initial_train_samples"),
        ((4, True, 2, 2, 0), "minimum_retained_train_samples"),
    ],
)
def test_invalid_walk_forward_spec_fails_closed(args, match):
    with pytest.raises(WalkForwardError, match=match):
        WalkForwardSpec(*args)


def test_retained_minimum_applies_after_purge_and_embargo():
    with pytest.raises(
        WalkForwardError,
        match="minimum_retained_train_samples",
    ):
        generate_walk_forward_folds(
            _experiment(),
            WalkForwardSpec(
                initial_train_samples=4,
                minimum_retained_train_samples=3,
                validation_samples=2,
                step_samples=2,
                embargo_seconds=86400,
            ),
        )


def test_too_small_train_split_fails_closed():
    experiment = _experiment()
    small = ExperimentDatasetBundle(
        experiment.version,
        experiment.dataset_id,
        experiment.feature_names,
        experiment.label_name,
        experiment.label_logical_type,
        MLDatasetBundle(
            ML_DATASET_ADAPTER_VERSION,
            experiment.dataset_id,
            FEATURES,
            LABEL,
            "float64",
            experiment.ml_bundle.train,
            experiment.ml_bundle.validation,
            experiment.ml_bundle.test,
        ),
        experiment.train,
        experiment.validation,
        experiment.test,
    )
    with pytest.raises(WalkForwardError, match="too small"):
        generate_walk_forward_folds(
            small,
            WalkForwardSpec(7, 1, 2, 2, 0),
        )


def test_fold_with_no_retained_training_rows_fails_closed():
    ends = tuple(_close(4) + timedelta(days=10) for _ in range(8))
    with pytest.raises(WalkForwardError, match="no training rows"):
        generate_walk_forward_folds(
            _experiment(ends),
            WalkForwardSpec(4, 2, 2, 2, 0),
        )


def test_duplicate_train_timestamp_fails_closed():
    base = _experiment()
    ml_meta = list(base.ml_bundle.train.metadata)
    previous = ml_meta[-2]
    last = ml_meta[-1]
    ml_meta[-1] = MLSampleMetadata(
        last.sample_key,
        last.code,
        previous.feature_window_close,
    )
    train_ml = MLDatasetSplit(
        "TRAIN",
        FEATURES,
        LABEL,
        "float64",
        base.ml_bundle.train.X,
        base.ml_bundle.train.y,
        tuple(ml_meta),
    )
    ml_bundle = MLDatasetBundle(
        ML_DATASET_ADAPTER_VERSION,
        base.dataset_id,
        FEATURES,
        LABEL,
        "float64",
        train_ml,
        base.ml_bundle.validation,
        base.ml_bundle.test,
    )
    exp_meta = list(base.train.metadata)
    old = exp_meta[-1]
    exp_meta[-1] = ExperimentSampleMetadata(
        old.sample_key,
        old.code,
        previous.feature_window_close,
        old.actual_label_end_time,
        old.label_value_id,
    )
    experiment = ExperimentDatasetBundle(
        EXPERIMENT_METADATA_VERSION,
        base.dataset_id,
        FEATURES,
        LABEL,
        "float64",
        ml_bundle,
        ExperimentSplit("TRAIN", train_ml, tuple(exp_meta)),
        base.validation,
        base.test,
    )
    with pytest.raises(WalkForwardError, match="strictly increasing"):
        generate_walk_forward_folds(
            experiment,
            WalkForwardSpec(4, 2, 2, 2, 0),
        )


def test_multi_symbol_train_split_fails_closed():
    base = _experiment()
    ml_meta = list(base.ml_bundle.train.metadata)
    ml_meta[-1] = MLSampleMetadata(
        ml_meta[-1].sample_key,
        "US.MSFT",
        ml_meta[-1].feature_window_close,
    )
    train_ml = MLDatasetSplit(
        "TRAIN",
        FEATURES,
        LABEL,
        "float64",
        base.ml_bundle.train.X,
        base.ml_bundle.train.y,
        tuple(ml_meta),
    )
    ml_bundle = MLDatasetBundle(
        ML_DATASET_ADAPTER_VERSION,
        base.dataset_id,
        FEATURES,
        LABEL,
        "float64",
        train_ml,
        base.ml_bundle.validation,
        base.ml_bundle.test,
    )
    exp_meta = list(base.train.metadata)
    last = exp_meta[-1]
    exp_meta[-1] = ExperimentSampleMetadata(
        last.sample_key,
        "US.MSFT",
        last.feature_window_close,
        last.actual_label_end_time,
        last.label_value_id,
    )
    experiment = ExperimentDatasetBundle(
        EXPERIMENT_METADATA_VERSION,
        base.dataset_id,
        FEATURES,
        LABEL,
        "float64",
        ml_bundle,
        ExperimentSplit("TRAIN", train_ml, tuple(exp_meta)),
        base.validation,
        base.test,
    )
    with pytest.raises(WalkForwardError, match="exactly one TRAIN symbol"):
        generate_walk_forward_folds(
            experiment,
            WalkForwardSpec(4, 2, 2, 2, 0),
        )


def test_plan_rejects_incomplete_prevalidation_partition():
    plan = generate_walk_forward_folds(
        _experiment(),
        WalkForwardSpec(4, 2, 2, 2, 0),
    )
    first = plan.folds[0]
    bad_first = replace(
        first,
        train_indices=(0,),
        train_sample_keys=(first.train_sample_keys[0],),
    )
    with pytest.raises(WalkForwardError, match="partitioned exactly once"):
        replace(plan, folds=(bad_first,) + plan.folds[1:])


def test_plan_rejects_wrong_unused_tail_count():
    plan = generate_walk_forward_folds(
        _experiment(),
        WalkForwardSpec(4, 2, 2, 2, 0),
    )
    with pytest.raises(WalkForwardError, match="unused_tail_count"):
        replace(plan, unused_tail_count=plan.unused_tail_count + 1)


def test_wrong_input_type_fails_locally():
    with pytest.raises(WalkForwardError, match="ExperimentDatasetBundle"):
        generate_walk_forward_folds(
            object(),
            WalkForwardSpec(4, 2, 2, 2, 0),
        )
