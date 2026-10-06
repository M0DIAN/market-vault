"""Leakage-safe Purged Walk-Forward V1 over Experiment Metadata.

V1 is deliberately narrow and deterministic:

- source samples are TRAIN + VALIDATION only; TEST is never admitted;
- training is expanding and always strictly earlier than validation;
- validation windows are contiguous and non-overlapping;
- purge uses the selected Label's exact actual_label_end_time from
  Experiment Metadata, never a nominal horizon and never the Dataset-wide
  latest Label end;
- there is no shuffle, random split, model training, or embargo policy.

Embargo is intentionally a separate later policy so V1 does not overload that
term with an ambiguous gap interpretation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re

from .experiment import (
    ExperimentDatasetBundle,
    ExperimentSampleMetadata,
)


PURGED_WALK_FORWARD_VERSION = "market-vault-purged-walk-forward-v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PurgedWalkForwardError(ValueError):
    """Fail-closed Purged Walk-Forward V1 validation/execution error."""


def _positive_int(value, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise PurgedWalkForwardError(f"{label} must be a positive integer")
    return value


@dataclass(frozen=True, slots=True)
class PurgedWalkForwardSpec:
    initial_train_samples: int
    validation_samples: int
    step_samples: int

    def __post_init__(self) -> None:
        initial = _positive_int(
            self.initial_train_samples,
            "initial_train_samples",
        )
        validation = _positive_int(
            self.validation_samples,
            "validation_samples",
        )
        step = _positive_int(self.step_samples, "step_samples")
        if step < validation:
            raise PurgedWalkForwardError(
                "step_samples must be >= validation_samples in V1"
            )
        object.__setattr__(self, "initial_train_samples", initial)
        object.__setattr__(self, "validation_samples", validation)
        object.__setattr__(self, "step_samples", step)


@dataclass(frozen=True, slots=True)
class WalkForwardPartition:
    feature_names: tuple[str, ...]
    label_name: str
    label_logical_type: str
    X: tuple[tuple[float, ...], ...]
    y: tuple[float | int, ...]
    metadata: tuple[ExperimentSampleMetadata, ...]

    def __post_init__(self) -> None:
        if type(self.feature_names) is not tuple or not self.feature_names:
            raise PurgedWalkForwardError(
                "feature_names must be a non-empty tuple"
            )
        if (
            not all(type(name) is str and name for name in self.feature_names)
            or len(set(self.feature_names)) != len(self.feature_names)
        ):
            raise PurgedWalkForwardError(
                "feature_names must contain unique non-empty strings"
            )
        if type(self.label_name) is not str or not self.label_name:
            raise PurgedWalkForwardError(
                "label_name must be a non-empty string"
            )
        if self.label_logical_type not in ("float64", "int64"):
            raise PurgedWalkForwardError(
                "label_logical_type must be float64 or int64"
            )
        if (
            type(self.X) is not tuple
            or type(self.y) is not tuple
            or type(self.metadata) is not tuple
        ):
            raise PurgedWalkForwardError(
                "X, y and metadata must be immutable tuples"
            )
        if not len(self.X) == len(self.y) == len(self.metadata):
            raise PurgedWalkForwardError(
                "partition X/y/metadata row counts differ"
            )
        width = len(self.feature_names)
        for row in self.X:
            if type(row) is not tuple or len(row) != width:
                raise PurgedWalkForwardError(
                    "partition Feature matrix width differs"
                )
        if not all(
            type(item) is ExperimentSampleMetadata
            for item in self.metadata
        ):
            raise PurgedWalkForwardError(
                "partition metadata must contain ExperimentSampleMetadata"
            )
        ordering = tuple(
            (item.feature_window_close, item.code, item.sample_key)
            for item in self.metadata
        )
        if ordering != tuple(sorted(ordering)):
            raise PurgedWalkForwardError(
                "partition rows must remain chronologically ordered"
            )
        keys = tuple(item.sample_key for item in self.metadata)
        if len(keys) != len(set(keys)):
            raise PurgedWalkForwardError(
                "partition contains duplicate sample keys"
            )

    @property
    def row_count(self) -> int:
        return len(self.metadata)


@dataclass(frozen=True, slots=True)
class PurgedWalkForwardFold:
    fold_index: int
    validation_start_time: datetime
    validation_end_time: datetime
    train_candidate_count: int
    train: WalkForwardPartition
    validation: WalkForwardPartition
    purged_metadata: tuple[ExperimentSampleMetadata, ...]

    def __post_init__(self) -> None:
        if type(self.fold_index) is not int or self.fold_index < 0:
            raise PurgedWalkForwardError(
                "fold_index must be a non-negative integer"
            )
        for name in ("validation_start_time", "validation_end_time"):
            value = getattr(self, name)
            if type(value) is not datetime or value.tzinfo is None:
                raise PurgedWalkForwardError(
                    f"{name} must be timezone-aware"
                )
        if self.validation_end_time < self.validation_start_time:
            raise PurgedWalkForwardError(
                "validation_end_time must not precede validation_start_time"
            )
        if type(self.train_candidate_count) is not int or self.train_candidate_count < 1:
            raise PurgedWalkForwardError(
                "train_candidate_count must be positive"
            )
        if (
            type(self.train) is not WalkForwardPartition
            or type(self.validation) is not WalkForwardPartition
        ):
            raise PurgedWalkForwardError(
                "exact WalkForwardPartition values required"
            )
        if self.train.row_count < 1 or self.validation.row_count < 1:
            raise PurgedWalkForwardError(
                "each fold requires non-empty train and validation partitions"
            )
        if (
            self.train.feature_names != self.validation.feature_names
            or self.train.label_name != self.validation.label_name
            or self.train.label_logical_type != self.validation.label_logical_type
        ):
            raise PurgedWalkForwardError(
                "train and validation schemas differ"
            )
        if (
            self.validation.metadata[0].feature_window_close
            != self.validation_start_time
            or self.validation.metadata[-1].feature_window_close
            != self.validation_end_time
        ):
            raise PurgedWalkForwardError(
                "validation boundaries differ from validation metadata"
            )
        if type(self.purged_metadata) is not tuple or not all(
            type(item) is ExperimentSampleMetadata
            for item in self.purged_metadata
        ):
            raise PurgedWalkForwardError(
                "purged_metadata must be an immutable metadata tuple"
            )
        if self.train_candidate_count != (
            self.train.row_count + len(self.purged_metadata)
        ):
            raise PurgedWalkForwardError(
                "train candidate count differs from retained + purged rows"
            )

        train_keys = {item.sample_key for item in self.train.metadata}
        purged_keys = {item.sample_key for item in self.purged_metadata}
        validation_keys = {
            item.sample_key for item in self.validation.metadata
        }
        if (
            train_keys & purged_keys
            or train_keys & validation_keys
            or purged_keys & validation_keys
        ):
            raise PurgedWalkForwardError(
                "fold train/purged/validation samples overlap"
            )
        if len(purged_keys) != len(self.purged_metadata):
            raise PurgedWalkForwardError(
                "purged_metadata contains duplicate samples"
            )
        for item in self.train.metadata:
            if not item.feature_window_close < self.validation_start_time:
                raise PurgedWalkForwardError(
                    "retained train sample is not earlier than validation"
                )
            if not item.actual_label_end_time < self.validation_start_time:
                raise PurgedWalkForwardError(
                    "retained train Label overlaps validation start"
                )
        for item in self.purged_metadata:
            if not item.feature_window_close < self.validation_start_time:
                raise PurgedWalkForwardError(
                    "purged sample is not an earlier training candidate"
                )
            if item.actual_label_end_time < self.validation_start_time:
                raise PurgedWalkForwardError(
                    "purged sample does not overlap validation start"
                )

    @property
    def purged_count(self) -> int:
        return len(self.purged_metadata)


@dataclass(frozen=True, slots=True)
class PurgedWalkForwardPlan:
    version: str
    dataset_id: str
    feature_names: tuple[str, ...]
    label_name: str
    label_logical_type: str
    spec: PurgedWalkForwardSpec
    source_train_count: int
    source_validation_count: int
    source_test_count: int
    unused_tail_count: int
    folds: tuple[PurgedWalkForwardFold, ...]

    def __post_init__(self) -> None:
        if self.version != PURGED_WALK_FORWARD_VERSION:
            raise PurgedWalkForwardError(
                "unsupported Purged Walk-Forward version"
            )
        if (
            type(self.dataset_id) is not str
            or _SHA256_RE.fullmatch(self.dataset_id) is None
        ):
            raise PurgedWalkForwardError(
                "dataset_id must be a 64-character lowercase hex identity"
            )
        if type(self.spec) is not PurgedWalkForwardSpec:
            raise PurgedWalkForwardError(
                "exact PurgedWalkForwardSpec required"
            )
        for name in (
            "source_train_count",
            "source_validation_count",
            "source_test_count",
            "unused_tail_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise PurgedWalkForwardError(
                    f"{name} must be a non-negative integer"
                )
        if type(self.folds) is not tuple or not self.folds:
            raise PurgedWalkForwardError(
                "folds must be a non-empty immutable tuple"
            )
        if not all(
            type(item) is PurgedWalkForwardFold for item in self.folds
        ):
            raise PurgedWalkForwardError(
                "folds must contain PurgedWalkForwardFold"
            )
        if tuple(item.fold_index for item in self.folds) != tuple(
            range(len(self.folds))
        ):
            raise PurgedWalkForwardError(
                "fold indices must be contiguous from zero"
            )
        for fold in self.folds:
            if (
                fold.train.feature_names != self.feature_names
                or fold.validation.feature_names != self.feature_names
                or fold.train.label_name != self.label_name
                or fold.validation.label_name != self.label_name
                or fold.train.label_logical_type != self.label_logical_type
                or fold.validation.label_logical_type != self.label_logical_type
            ):
                raise PurgedWalkForwardError(
                    "fold schema differs from plan schema"
                )

    @property
    def fold_count(self) -> int:
        return len(self.folds)


@dataclass(frozen=True, slots=True)
class _Row:
    X: tuple[float, ...]
    y: float | int
    metadata: ExperimentSampleMetadata


def _pool(bundle: ExperimentDatasetBundle) -> tuple[_Row, ...]:
    rows = []
    for split in (bundle.train, bundle.validation):
        rows.extend(
            _Row(X, y, metadata)
            for X, y, metadata in zip(
                split.X,
                split.y,
                split.metadata,
            )
        )
    result = tuple(rows)
    keys = tuple(item.metadata.sample_key for item in result)
    if len(keys) != len(set(keys)):
        raise PurgedWalkForwardError(
            "TRAIN + VALIDATION contain duplicate sample keys"
        )
    ordering = tuple(
        (
            item.metadata.feature_window_close,
            item.metadata.code,
            item.metadata.sample_key,
        )
        for item in result
    )
    if ordering != tuple(sorted(ordering)):
        raise PurgedWalkForwardError(
            "TRAIN + VALIDATION are not globally chronological"
        )
    return result


def _partition(
    rows: tuple[_Row, ...],
    bundle: ExperimentDatasetBundle,
) -> WalkForwardPartition:
    return WalkForwardPartition(
        bundle.feature_names,
        bundle.label_name,
        bundle.label_logical_type,
        tuple(item.X for item in rows),
        tuple(item.y for item in rows),
        tuple(item.metadata for item in rows),
    )


def build_purged_walk_forward(
    bundle: ExperimentDatasetBundle,
    *,
    initial_train_samples: int,
    validation_samples: int,
    step_samples: int,
) -> PurgedWalkForwardPlan:
    """Build deterministic expanding purged walk-forward folds.

    TEST is deliberately excluded from fold generation and is reported only as
    source_test_count.
    """
    if type(bundle) is not ExperimentDatasetBundle:
        raise PurgedWalkForwardError(
            "Purged Walk-Forward V1 requires ExperimentDatasetBundle"
        )
    spec = PurgedWalkForwardSpec(
        initial_train_samples,
        validation_samples,
        step_samples,
    )
    pool = _pool(bundle)
    if len(pool) < spec.initial_train_samples + spec.validation_samples:
        raise PurgedWalkForwardError(
            "TRAIN + VALIDATION do not contain one complete walk-forward fold"
        )

    folds = []
    start = spec.initial_train_samples
    fold_index = 0
    last_validation_end = 0
    while start + spec.validation_samples <= len(pool):
        validation_rows = pool[
            start : start + spec.validation_samples
        ]
        validation_start = (
            validation_rows[0].metadata.feature_window_close
        )
        candidates = pool[:start]
        retained = tuple(
            item for item in candidates
            if item.metadata.actual_label_end_time < validation_start
        )
        purged = tuple(
            item for item in candidates
            if item.metadata.actual_label_end_time >= validation_start
        )
        if not retained:
            raise PurgedWalkForwardError(
                f"purge removed every training sample for fold {fold_index}"
            )

        folds.append(
            PurgedWalkForwardFold(
                fold_index,
                validation_start,
                validation_rows[-1].metadata.feature_window_close,
                len(candidates),
                _partition(retained, bundle),
                _partition(validation_rows, bundle),
                tuple(item.metadata for item in purged),
            )
        )
        last_validation_end = start + spec.validation_samples
        fold_index += 1
        start += spec.step_samples

    if not folds:
        raise PurgedWalkForwardError(
            "no complete Purged Walk-Forward folds were generated"
        )

    return PurgedWalkForwardPlan(
        PURGED_WALK_FORWARD_VERSION,
        bundle.dataset_id,
        bundle.feature_names,
        bundle.label_name,
        bundle.label_logical_type,
        spec,
        bundle.train.row_count,
        bundle.validation.row_count,
        bundle.test.row_count,
        len(pool) - last_validation_end,
        tuple(folds),
    )
