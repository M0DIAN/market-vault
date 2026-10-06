"""Leakage-safe expanding-window Walk-Forward Experiment V1.

Walk-Forward V1 consumes ExperimentDatasetBundle, which already carries the
selected Label's exact actual_label_end_time for every ML-ready sample.

Only the development pool is used:

    TRAIN + VALIDATION

TEST is a permanent holdout and is never consulted when constructing folds.

Fold boundaries are expressed in unique feature_window_close periods rather
than raw row counts.  This prevents a panel Dataset from splitting different
symbols observed at the same instant across TRAIN and VALIDATION.

For each fold:

- validation is a contiguous set of future feature-close periods;
- train candidates are all earlier development samples;
- a candidate is retained only when its selected Label
  actual_label_end_time is strictly before validation_start_time;
- candidates ending at or after the boundary are purged;
- training expands forward across folds;
- validation windows do not overlap in V1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re

from ..dataset.encoding import encode_identity
from .experiment import (
    ExperimentDatasetBundle,
    ExperimentSampleMetadata,
    ExperimentSplit,
)


WALK_FORWARD_VERSION = "market-vault-walk-forward-v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class WalkForwardError(ValueError):
    """Fail-closed Walk-Forward Experiment V1 error."""


def _positive_int(value, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise WalkForwardError(f"{label} must be a positive integer")
    return value


def _digest_members(prefix: str, members: tuple[str, ...]) -> str:
    return encode_identity(
        prefix,
        {
            "count": len(members),
            "members": "".join(members),
        },
    )


@dataclass(frozen=True, slots=True)
class WalkForwardSlice:
    role: str
    feature_names: tuple[str, ...]
    label_name: str
    label_logical_type: str
    X: tuple[tuple[float, ...], ...]
    y: tuple[float | int, ...]
    metadata: tuple[ExperimentSampleMetadata, ...]

    def __post_init__(self) -> None:
        if self.role not in ("TRAIN", "VALIDATION"):
            raise WalkForwardError("WalkForwardSlice role must be TRAIN or VALIDATION")
        if type(self.feature_names) is not tuple or not self.feature_names:
            raise WalkForwardError("WalkForwardSlice feature_names must be non-empty")
        if type(self.label_name) is not str or not self.label_name:
            raise WalkForwardError("WalkForwardSlice label_name must be non-empty")
        if self.label_logical_type not in ("float64", "int64"):
            raise WalkForwardError("WalkForwardSlice Label type must be numeric")
        if not len(self.X) == len(self.y) == len(self.metadata):
            raise WalkForwardError("WalkForwardSlice row counts differ")
        if not all(type(item) is ExperimentSampleMetadata for item in self.metadata):
            raise WalkForwardError(
                "WalkForwardSlice metadata must contain ExperimentSampleMetadata"
            )
        ordering = tuple(
            (item.feature_window_close, item.code, item.sample_key)
            for item in self.metadata
        )
        if ordering != tuple(sorted(ordering)):
            raise WalkForwardError("WalkForwardSlice rows must be chronological")
        if len({item.sample_key for item in self.metadata}) != len(self.metadata):
            raise WalkForwardError("WalkForwardSlice sample keys must be unique")

    @property
    def row_count(self) -> int:
        return len(self.y)

    @property
    def sample_keys(self) -> tuple[str, ...]:
        return tuple(item.sample_key for item in self.metadata)


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    fold_index: int
    fold_id: str
    validation_start_time: datetime
    validation_end_time: datetime
    train_candidate_count: int
    purged_train_count: int
    train: WalkForwardSlice
    validation: WalkForwardSlice

    def __post_init__(self) -> None:
        if type(self.fold_index) is not int or self.fold_index < 0:
            raise WalkForwardError("fold_index must be a non-negative integer")
        if type(self.fold_id) is not str or _SHA256_RE.fullmatch(self.fold_id) is None:
            raise WalkForwardError("fold_id must be a lowercase SHA-256 identity")
        for name in ("validation_start_time", "validation_end_time"):
            value = getattr(self, name)
            if type(value) is not datetime or value.tzinfo is None:
                raise WalkForwardError(f"{name} must be timezone-aware")
        if self.validation_end_time < self.validation_start_time:
            raise WalkForwardError("validation end cannot precede validation start")
        if type(self.train_candidate_count) is not int or self.train_candidate_count < 0:
            raise WalkForwardError("train_candidate_count must be non-negative")
        if type(self.purged_train_count) is not int or self.purged_train_count < 0:
            raise WalkForwardError("purged_train_count must be non-negative")
        if self.purged_train_count != self.train_candidate_count - self.train.row_count:
            raise WalkForwardError("purged_train_count differs from retained train rows")
        if self.train.role != "TRAIN" or self.validation.role != "VALIDATION":
            raise WalkForwardError("fold slice roles are invalid")
        if (
            self.train.feature_names != self.validation.feature_names
            or self.train.label_name != self.validation.label_name
            or self.train.label_logical_type != self.validation.label_logical_type
        ):
            raise WalkForwardError("fold TRAIN/VALIDATION schemas differ")
        if not self.validation.metadata:
            raise WalkForwardError("fold validation slice must not be empty")
        if self.validation.metadata[0].feature_window_close != self.validation_start_time:
            raise WalkForwardError("validation_start_time differs from validation rows")
        if self.validation.metadata[-1].feature_window_close != self.validation_end_time:
            raise WalkForwardError("validation_end_time differs from validation rows")
        if any(
            item.feature_window_close >= self.validation_start_time
            or item.actual_label_end_time >= self.validation_start_time
            for item in self.train.metadata
        ):
            raise WalkForwardError("fold TRAIN contains boundary leakage")
        if any(
            item.feature_window_close < self.validation_start_time
            or item.feature_window_close > self.validation_end_time
            for item in self.validation.metadata
        ):
            raise WalkForwardError("fold VALIDATION rows lie outside its period window")
        if set(self.train.sample_keys) & set(self.validation.sample_keys):
            raise WalkForwardError("fold TRAIN and VALIDATION samples overlap")


@dataclass(frozen=True, slots=True)
class WalkForwardPlan:
    version: str
    walk_forward_id: str
    dataset_id: str
    feature_names: tuple[str, ...]
    label_name: str
    label_logical_type: str
    minimum_train_periods: int
    validation_periods: int
    step_periods: int
    development_period_count: int
    development_sample_count: int
    held_out_test_count: int
    folds: tuple[WalkForwardFold, ...]

    def __post_init__(self) -> None:
        if self.version != WALK_FORWARD_VERSION:
            raise WalkForwardError("unsupported Walk-Forward version")
        for name in ("walk_forward_id", "dataset_id"):
            value = getattr(self, name)
            if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
                raise WalkForwardError(f"{name} must be a lowercase SHA-256 identity")
        if type(self.feature_names) is not tuple or not self.feature_names:
            raise WalkForwardError("Walk-Forward feature_names must be non-empty")
        if type(self.label_name) is not str or not self.label_name:
            raise WalkForwardError("Walk-Forward label_name must be non-empty")
        if self.label_logical_type not in ("float64", "int64"):
            raise WalkForwardError("Walk-Forward Label type must be numeric")
        for name in (
            "minimum_train_periods",
            "validation_periods",
            "step_periods",
        ):
            _positive_int(getattr(self, name), name)
        if self.step_periods < self.validation_periods:
            raise WalkForwardError(
                "step_periods must be >= validation_periods in V1"
            )
        for name in (
            "development_period_count",
            "development_sample_count",
            "held_out_test_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise WalkForwardError(f"{name} must be a non-negative integer")
        if type(self.folds) is not tuple or not self.folds:
            raise WalkForwardError("Walk-Forward plan must contain at least one fold")
        if not all(type(item) is WalkForwardFold for item in self.folds):
            raise WalkForwardError("folds must contain WalkForwardFold")
        if tuple(item.fold_index for item in self.folds) != tuple(range(len(self.folds))):
            raise WalkForwardError("fold indices must be contiguous from zero")
        for fold in self.folds:
            if (
                fold.train.feature_names != self.feature_names
                or fold.train.label_name != self.label_name
                or fold.train.label_logical_type != self.label_logical_type
            ):
                raise WalkForwardError("fold schema differs from plan schema")
        for left, right in zip(self.folds, self.folds[1:]):
            if left.validation_end_time >= right.validation_start_time:
                raise WalkForwardError("Walk-Forward validation windows overlap")


@dataclass(frozen=True, slots=True)
class _Row:
    X: tuple[float, ...]
    y: float | int
    metadata: ExperimentSampleMetadata


def _rows(split: ExperimentSplit) -> tuple[_Row, ...]:
    return tuple(
        _Row(X, y, metadata)
        for X, y, metadata in zip(split.X, split.y, split.metadata)
    )


def _development_rows(bundle: ExperimentDatasetBundle) -> tuple[_Row, ...]:
    rows = _rows(bundle.train) + _rows(bundle.validation)
    ordered = tuple(
        sorted(
            rows,
            key=lambda item: (
                item.metadata.feature_window_close,
                item.metadata.code,
                item.metadata.sample_key,
            ),
        )
    )
    if len({row.metadata.sample_key for row in ordered}) != len(ordered):
        raise WalkForwardError("development pool contains duplicate sample keys")
    return ordered


def _periods(rows: tuple[_Row, ...]) -> tuple[datetime, ...]:
    return tuple(sorted({row.metadata.feature_window_close for row in rows}))


def _slice(
    role: str,
    rows: tuple[_Row, ...],
    bundle: ExperimentDatasetBundle,
) -> WalkForwardSlice:
    return WalkForwardSlice(
        role,
        bundle.feature_names,
        bundle.label_name,
        bundle.label_logical_type,
        tuple(row.X for row in rows),
        tuple(row.y for row in rows),
        tuple(row.metadata for row in rows),
    )


def _fold_id(
    *,
    dataset_id: str,
    fold_index: int,
    validation_start_time: datetime,
    validation_end_time: datetime,
    train_keys: tuple[str, ...],
    validation_keys: tuple[str, ...],
) -> str:
    return encode_identity(
        "market-vault-walk-forward-fold-v1",
        {
            "dataset_id": dataset_id,
            "fold_index": fold_index,
            "validation_start_time": validation_start_time,
            "validation_end_time": validation_end_time,
            "train_keys_digest": _digest_members(
                "market-vault-walk-forward-train-keys-v1",
                train_keys,
            ),
            "validation_keys_digest": _digest_members(
                "market-vault-walk-forward-validation-keys-v1",
                validation_keys,
            ),
        },
    )


def _plan_id(
    *,
    bundle: ExperimentDatasetBundle,
    minimum_train_periods: int,
    validation_periods: int,
    step_periods: int,
    folds: tuple[WalkForwardFold, ...],
) -> str:
    return encode_identity(
        WALK_FORWARD_VERSION,
        {
            "dataset_id": bundle.dataset_id,
            "label_name": bundle.label_name,
            "feature_names_digest": _digest_members(
                "market-vault-walk-forward-feature-names-v1",
                bundle.feature_names,
            ),
            "minimum_train_periods": minimum_train_periods,
            "validation_periods": validation_periods,
            "step_periods": step_periods,
            "fold_ids_digest": _digest_members(
                "market-vault-walk-forward-fold-ids-v1",
                tuple(fold.fold_id for fold in folds),
            ),
        },
    )


def build_walk_forward_plan(
    bundle: ExperimentDatasetBundle,
    *,
    minimum_train_periods: int,
    validation_periods: int,
    step_periods: int | None = None,
) -> WalkForwardPlan:
    """Build leakage-safe expanding TRAIN/VALIDATION folds.

    TEST is never read except for recording its row count in the returned plan.
    """
    if type(bundle) is not ExperimentDatasetBundle:
        raise WalkForwardError(
            "Walk-Forward V1 requires ExperimentDatasetBundle"
        )
    minimum_train_periods = _positive_int(
        minimum_train_periods,
        "minimum_train_periods",
    )
    validation_periods = _positive_int(
        validation_periods,
        "validation_periods",
    )
    if step_periods is None:
        step_periods = validation_periods
    step_periods = _positive_int(step_periods, "step_periods")
    if step_periods < validation_periods:
        raise WalkForwardError(
            "step_periods must be >= validation_periods in V1"
        )

    development = _development_rows(bundle)
    periods = _periods(development)
    if len(periods) < minimum_train_periods + validation_periods:
        raise WalkForwardError(
            "development pool is too short for one full walk-forward fold"
        )

    folds = []
    validation_start_index = minimum_train_periods

    # If selected-Label purge removes too many early candidates, slide the
    # first boundary forward one period at a time until the retained TRAIN
    # meets minimum_train_periods.  Subsequent expanding folds cannot reduce
    # the retained TRAIN size because the purge boundary only moves forward.
    while (
        validation_start_index + validation_periods <= len(periods)
        and not folds
    ):
        validation_start = periods[validation_start_index]
        candidates = tuple(
            row for row in development
            if row.metadata.feature_window_close < validation_start
        )
        retained = tuple(
            row for row in candidates
            if row.metadata.actual_label_end_time < validation_start
        )
        retained_periods = {
            row.metadata.feature_window_close for row in retained
        }
        if len(retained_periods) >= minimum_train_periods:
            break
        validation_start_index += 1

    if validation_start_index + validation_periods > len(periods):
        raise WalkForwardError(
            "selected-Label purge leaves insufficient TRAIN periods"
        )

    fold_index = 0
    while validation_start_index + validation_periods <= len(periods):
        validation_times = periods[
            validation_start_index:
            validation_start_index + validation_periods
        ]
        validation_start = validation_times[0]
        validation_end = validation_times[-1]

        candidates = tuple(
            row for row in development
            if row.metadata.feature_window_close < validation_start
        )
        retained = tuple(
            row for row in candidates
            if row.metadata.actual_label_end_time < validation_start
        )
        if len({
            row.metadata.feature_window_close for row in retained
        }) < minimum_train_periods:
            raise WalkForwardError(
                "walk-forward TRAIN fell below minimum after selected-Label purge"
            )
        validation = tuple(
            row for row in development
            if validation_start
            <= row.metadata.feature_window_close
            <= validation_end
        )
        if not validation:
            raise WalkForwardError("walk-forward validation window is empty")

        train_slice = _slice("TRAIN", retained, bundle)
        validation_slice = _slice("VALIDATION", validation, bundle)
        fold_id = _fold_id(
            dataset_id=bundle.dataset_id,
            fold_index=fold_index,
            validation_start_time=validation_start,
            validation_end_time=validation_end,
            train_keys=train_slice.sample_keys,
            validation_keys=validation_slice.sample_keys,
        )
        folds.append(
            WalkForwardFold(
                fold_index,
                fold_id,
                validation_start,
                validation_end,
                len(candidates),
                len(candidates) - len(retained),
                train_slice,
                validation_slice,
            )
        )
        fold_index += 1
        validation_start_index += step_periods

    if not folds:
        raise WalkForwardError("no complete walk-forward fold was produced")

    fold_tuple = tuple(folds)
    plan_id = _plan_id(
        bundle=bundle,
        minimum_train_periods=minimum_train_periods,
        validation_periods=validation_periods,
        step_periods=step_periods,
        folds=fold_tuple,
    )
    return WalkForwardPlan(
        WALK_FORWARD_VERSION,
        plan_id,
        bundle.dataset_id,
        bundle.feature_names,
        bundle.label_name,
        bundle.label_logical_type,
        minimum_train_periods,
        validation_periods,
        step_periods,
        len(periods),
        len(development),
        bundle.test.row_count,
        fold_tuple,
    )
