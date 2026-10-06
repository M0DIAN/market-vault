"""Focused leakage and determinism tests for Walk-Forward Experiment V1."""

from __future__ import annotations

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
    build_walk_forward_plan,
)


UTC = timezone.utc
FEATURES = ("f1", "f2")
LABEL = "forward_return_5d"


def _time(period: int) -> datetime:
    return datetime(2026, 1, 1, 15, tzinfo=UTC) + timedelta(days=period)


def _rows_for_periods(
    periods,
    *,
    codes=("US.AAPL",),
    sequence_start=1,
    crossing_ends=None,
    y_shift=0.0,
):
    crossing_ends = crossing_ends or {}
    rows = []
    sequence = sequence_start
    for period in periods:
        for code_index, code in enumerate(codes):
            sample_key = f"{sequence:064x}"
            close = _time(period)
            ml_meta = MLSampleMetadata(sample_key, code, close)
            label_end = crossing_ends.get(
                (period, code),
                close + timedelta(hours=1),
            )
            exp_meta = ExperimentSampleMetadata(
                sample_key,
                code,
                close,
                label_end,
                f"{10_000 + sequence:064x}",
            )
            X = (
                float(period + 1),
                float((period + 1) * 10 + code_index),
            )
            y = float(period) + y_shift
            rows.append((close, code, sample_key, X, y, ml_meta, exp_meta))
            sequence += 1
    rows.sort(key=lambda item: item[:3])
    return tuple(rows), sequence


def _split(name, rows):
    ml = MLDatasetSplit(
        name,
        FEATURES,
        LABEL,
        "float64",
        tuple(item[3] for item in rows),
        tuple(item[4] for item in rows),
        tuple(item[5] for item in rows),
    )
    exp = ExperimentSplit(
        name,
        ml,
        tuple(item[6] for item in rows),
    )
    return ml, exp


def _bundle(
    *,
    train_periods=(0, 1, 2, 3),
    validation_periods=(4, 5, 6, 7),
    test_periods=(8, 9),
    codes=("US.AAPL",),
    crossing_ends=None,
    test_y_shift=0.0,
    dataset_id="a" * 64,
):
    sequence = 1
    train_rows, sequence = _rows_for_periods(
        train_periods,
        codes=codes,
        sequence_start=sequence,
        crossing_ends=crossing_ends,
    )
    validation_rows, sequence = _rows_for_periods(
        validation_periods,
        codes=codes,
        sequence_start=sequence,
        crossing_ends=crossing_ends,
    )
    test_rows, sequence = _rows_for_periods(
        test_periods,
        codes=codes,
        sequence_start=sequence,
        crossing_ends=crossing_ends,
        y_shift=test_y_shift,
    )

    train_ml, train_exp = _split("TRAIN", train_rows)
    validation_ml, validation_exp = _split("VALIDATION", validation_rows)
    test_ml, test_exp = _split("TEST", test_rows)

    ml_bundle = MLDatasetBundle(
        ML_DATASET_ADAPTER_VERSION,
        dataset_id,
        FEATURES,
        LABEL,
        "float64",
        train_ml,
        validation_ml,
        test_ml,
    )
    return ExperimentDatasetBundle(
        EXPERIMENT_METADATA_VERSION,
        dataset_id,
        FEATURES,
        LABEL,
        "float64",
        ml_bundle,
        train_exp,
        validation_exp,
        test_exp,
    )


def test_expanding_folds_purge_selected_label_overlap_and_hold_out_test():
    # Period 2's selected Label ends after period 4 starts. The first proposed
    # boundary (period 3) and the next boundary (period 4) cannot retain the
    # requested three TRAIN periods; V1 slides to period 5. At that boundary
    # period 2 is still purged, leaving periods 0/1/3 as the minimum TRAIN.
    crossing = {
        # Blocks the initial period-3 boundary and still overlaps period 4.
        (2, "US.AAPL"): _time(4) + timedelta(hours=1),
        # Blocks period 4 and is the one sample purged at the first accepted
        # period-5 validation boundary.
        (3, "US.AAPL"): _time(5) + timedelta(hours=1),
    }
    bundle = _bundle(
        validation_periods=(4, 5, 6, 7, 8, 9),
        test_periods=(10, 11),
        crossing_ends=crossing,
    )

    plan = build_walk_forward_plan(
        bundle,
        minimum_train_periods=3,
        validation_periods=2,
        step_periods=2,
    )

    assert plan.version == WALK_FORWARD_VERSION
    assert plan.dataset_id == "a" * 64
    assert plan.feature_names == FEATURES
    assert plan.label_name == LABEL
    assert plan.development_period_count == 10
    assert plan.development_sample_count == 10
    assert plan.held_out_test_count == 2
    assert len(plan.folds) == 2

    first, second = plan.folds
    assert first.validation_start_time == _time(5)
    assert first.validation_end_time == _time(6)
    assert first.train_candidate_count == 5
    assert first.purged_train_count == 1
    assert tuple(
        item.feature_window_close for item in first.train.metadata
    ) == (_time(0), _time(1), _time(2), _time(4))
    assert tuple(
        item.feature_window_close for item in first.validation.metadata
    ) == (_time(5), _time(6))

    assert second.validation_start_time == _time(7)
    assert second.validation_end_time == _time(8)
    assert second.train_candidate_count == 7
    assert second.purged_train_count == 0
    assert second.train.row_count == 7
    assert second.validation.row_count == 2

    test_keys = set(bundle.test.metadata[index].sample_key for index in range(bundle.test.row_count))
    for fold in plan.folds:
        assert not (set(fold.train.sample_keys) & test_keys)
        assert not (set(fold.validation.sample_keys) & test_keys)
        assert all(
            item.actual_label_end_time < fold.validation_start_time
            for item in fold.train.metadata
        )

    again = build_walk_forward_plan(
        bundle,
        minimum_train_periods=3,
        validation_periods=2,
        step_periods=2,
    )
    assert again == plan
    assert len(plan.walk_forward_id) == 64
    assert all(len(fold.fold_id) == 64 for fold in plan.folds)


def test_period_boundaries_keep_same_timestamp_symbols_together():
    codes = ("US.AAPL", "US.MSFT")
    bundle = _bundle(
        train_periods=(0, 1, 2),
        validation_periods=(3, 4, 5),
        test_periods=(6,),
        codes=codes,
    )
    plan = build_walk_forward_plan(
        bundle,
        minimum_train_periods=2,
        validation_periods=1,
        step_periods=1,
    )

    assert len(plan.folds) == 4
    first = plan.folds[0]
    assert first.validation_start_time == _time(2)
    assert first.train.row_count == 4
    assert first.validation.row_count == 2
    assert tuple(item.code for item in first.validation.metadata) == codes
    assert len({
        item.feature_window_close for item in first.validation.metadata
    }) == 1
    for fold in plan.folds:
        train_times = {
            item.feature_window_close for item in fold.train.metadata
        }
        validation_times = {
            item.feature_window_close for item in fold.validation.metadata
        }
        assert train_times.isdisjoint(validation_times)


def test_test_values_never_change_fold_construction_or_identity():
    one = _bundle(test_y_shift=0.0)
    two = _bundle(test_y_shift=9999.0)

    plan_one = build_walk_forward_plan(
        one,
        minimum_train_periods=3,
        validation_periods=2,
    )
    plan_two = build_walk_forward_plan(
        two,
        minimum_train_periods=3,
        validation_periods=2,
    )

    assert plan_one == plan_two
    assert plan_one.walk_forward_id == plan_two.walk_forward_id


def test_label_end_equal_to_validation_boundary_is_purged():
    crossing = {
        (2, "US.AAPL"): _time(4),
    }
    bundle = _bundle(crossing_ends=crossing)
    plan = build_walk_forward_plan(
        bundle,
        minimum_train_periods=3,
        validation_periods=1,
        step_periods=1,
    )
    first = plan.folds[0]
    assert first.validation_start_time == _time(4)
    assert first.purged_train_count == 1
    assert _time(2) not in tuple(
        item.feature_window_close for item in first.train.metadata
    )


@pytest.mark.parametrize(
    "kwargs,match",
    [
        (
            dict(minimum_train_periods=0, validation_periods=1),
            "positive integer",
        ),
        (
            dict(minimum_train_periods=2, validation_periods=2, step_periods=1),
            "step_periods",
        ),
        (
            dict(minimum_train_periods=8, validation_periods=1),
            "too short",
        ),
    ],
)
def test_invalid_walk_forward_configuration_fails_closed(kwargs, match):
    with pytest.raises(WalkForwardError, match=match):
        build_walk_forward_plan(_bundle(), **kwargs)


def test_wrong_input_type_fails_locally():
    with pytest.raises(WalkForwardError, match="ExperimentDatasetBundle"):
        build_walk_forward_plan(
            object(),
            minimum_train_periods=2,
            validation_periods=1,
        )


def test_plan_identity_changes_with_fold_configuration():
    bundle = _bundle()
    one = build_walk_forward_plan(
        bundle,
        minimum_train_periods=2,
        validation_periods=2,
        step_periods=2,
    )
    two = build_walk_forward_plan(
        bundle,
        minimum_train_periods=3,
        validation_periods=2,
        step_periods=2,
    )
    assert one.walk_forward_id != two.walk_forward_id
