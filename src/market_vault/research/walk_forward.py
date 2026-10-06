"""Leakage-safe expanding Walk-Forward Fold V1.

Walk-Forward V1 consumes Experiment Metadata V1 and operates only inside the
existing TRAIN split.  Final VALIDATION/TEST holdouts remain untouched.

For each fold:

- validation rows are a contiguous future block;
- training candidates are all earlier TRAIN rows (expanding window);
- a candidate is PURGED when its selected Label actual_label_end_time is not
  strictly before the validation start;
- after purge, an optional pre-validation embargo removes candidates whose
  feature_window_close is too close to the validation start;
- validation windows never overlap because step_samples >= validation_samples.

No model fitting, scaling, random shuffle, Dataset rebuilding, or wall-clock
lookup occurs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import re

from .experiment import (
    ExperimentDatasetBundle,
    ExperimentMetadataError,
    ExperimentSplit,
)


WALK_FORWARD_VERSION = "market-vault-walk-forward-v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class WalkForwardError(ValueError):
    """Fail-closed Walk-Forward V1 specification or generation error."""


def _positive_int(value, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise WalkForwardError(f"{label} must be a positive integer")
    return value


def _non_negative_int(value, label: str) -> int:
    if type(value) is not int or value < 0:
        raise WalkForwardError(f"{label} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class WalkForwardSpec:
    minimum_train_samples: int
    validation_samples: int
    step_samples: int
    embargo_seconds: int = 0

    def __post_init__(self) -> None:
        minimum = _positive_int(
            self.minimum_train_samples,
            "minimum_train_samples",
        )
        validation = _positive_int(
            self.validation_samples,
            "validation_samples",
        )
        step = _positive_int(self.step_samples, "step_samples")
        embargo = _non_negative_int(
            self.embargo_seconds,
            "embargo_seconds",
        )
        if step < validation:
            raise WalkForwardError(
                "step_samples must be >= validation_samples "
                "to keep validation windows non-overlapping"
            )
        object.__setattr__(self, "minimum_train_samples", minimum)
        object.__setattr__(self, "validation_samples", validation)
        object.__setattr__(self, "step_samples", step)
        object.__setattr__(self, "embargo_seconds", embargo)


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    fold_index: int
    validation_start_time: datetime
    validation_end_time: datetime
    train_indices: tuple[int, ...]
    validation_indices: tuple[int, ...]
    purged_indices: tuple[int, ...]
    embargoed_indices: tuple[int, ...]
    train_sample_keys: tuple[str, ...]
    validation_sample_keys: tuple[str, ...]
    purged_sample_keys: tuple[str, ...]
    embargoed_sample_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.fold_index) is not int or self.fold_index < 0:
            raise WalkForwardError("fold_index must be a non-negative integer")
        for name in ("validation_start_time", "validation_end_time"):
            value = getattr(self, name)
            if type(value) is not datetime or value.tzinfo is None:
                raise WalkForwardError(
                    f"{name} must be a timezone-aware datetime"
                )
        if self.validation_end_time < self.validation_start_time:
            raise WalkForwardError(
                "validation_end_time must not precede validation_start_time"
            )

        groups = (
            ("train", self.train_indices, self.train_sample_keys),
            (
                "validation",
                self.validation_indices,
                self.validation_sample_keys,
            ),
            ("purged", self.purged_indices, self.purged_sample_keys),
            (
                "embargoed",
                self.embargoed_indices,
                self.embargoed_sample_keys,
            ),
        )
        seen = set()
        for label, indices, keys in groups:
            if type(indices) is not tuple or type(keys) is not tuple:
                raise WalkForwardError(
                    f"{label} indices/keys must be immutable tuples"
                )
            if (
                tuple(sorted(set(indices))) != indices
                or not all(type(index) is int and index >= 0 for index in indices)
            ):
                raise WalkForwardError(
                    f"{label} indices must be unique ascending non-negative integers"
                )
            if len(indices) != len(keys):
                raise WalkForwardError(
                    f"{label} index/sample-key counts differ"
                )
            if not all(
                type(key) is str and _SHA256_RE.fullmatch(key) is not None
                for key in keys
            ):
                raise WalkForwardError(
                    f"{label} sample keys must be lowercase SHA-256 identities"
                )
            overlap = seen.intersection(indices)
            if overlap:
                raise WalkForwardError(
                    "Walk-Forward train/validation/purge/embargo sets overlap"
                )
            seen.update(indices)

        if not self.train_indices:
            raise WalkForwardError("a Walk-Forward fold requires training rows")
        if not self.validation_indices:
            raise WalkForwardError("a Walk-Forward fold requires validation rows")

    @property
    def train_count(self) -> int:
        return len(self.train_indices)

    @property
    def validation_count(self) -> int:
        return len(self.validation_indices)

    @property
    def purged_count(self) -> int:
        return len(self.purged_indices)

    @property
    def embargoed_count(self) -> int:
        return len(self.embargoed_indices)


@dataclass(frozen=True, slots=True)
class WalkForwardPlan:
    version: str
    dataset_id: str
    label_name: str
    feature_names: tuple[str, ...]
    source_split: str
    source_row_count: int
    unused_tail_count: int
    spec: WalkForwardSpec
    folds: tuple[WalkForwardFold, ...]

    def __post_init__(self) -> None:
        if self.version != WALK_FORWARD_VERSION:
            raise WalkForwardError("unsupported Walk-Forward version")
        if (
            type(self.dataset_id) is not str
            or _SHA256_RE.fullmatch(self.dataset_id) is None
        ):
            raise WalkForwardError(
                "dataset_id must be a 64-character lowercase hex identity"
            )
        if type(self.label_name) is not str or not self.label_name:
            raise WalkForwardError("label_name must be non-empty")
        if (
            type(self.feature_names) is not tuple
            or not self.feature_names
            or len(self.feature_names) != len(set(self.feature_names))
        ):
            raise WalkForwardError(
                "feature_names must be a non-empty unique tuple"
            )
        if self.source_split != "TRAIN":
            raise WalkForwardError("Walk-Forward V1 source_split must be TRAIN")
        if (
            type(self.source_row_count) is not int
            or self.source_row_count < 0
            or type(self.unused_tail_count) is not int
            or self.unused_tail_count < 0
            or self.unused_tail_count > self.source_row_count
        ):
            raise WalkForwardError("invalid Walk-Forward source/tail counts")
        if type(self.spec) is not WalkForwardSpec:
            raise WalkForwardError("exact WalkForwardSpec required")
        if type(self.folds) is not tuple or not self.folds or not all(
            type(fold) is WalkForwardFold for fold in self.folds
        ):
            raise WalkForwardError(
                "folds must be a non-empty WalkForwardFold tuple"
            )
        if tuple(fold.fold_index for fold in self.folds) != tuple(
            range(len(self.folds))
        ):
            raise WalkForwardError(
                "Walk-Forward fold indices must be contiguous from zero"
            )

    @property
    def fold_count(self) -> int:
        return len(self.folds)


def _keys(split: ExperimentSplit, indices: tuple[int, ...]) -> tuple[str, ...]:
    return tuple(split.metadata[index].sample_key for index in indices)


def _fold(
    split: ExperimentSplit,
    *,
    fold_index: int,
    validation_start_index: int,
    validation_samples: int,
    embargo_seconds: int,
) -> WalkForwardFold:
    validation_indices = tuple(
        range(
            validation_start_index,
            validation_start_index + validation_samples,
        )
    )
    validation_start_time = split.metadata[
        validation_indices[0]
    ].feature_window_close
    validation_end_time = split.metadata[
        validation_indices[-1]
    ].feature_window_close

    embargo_cutoff = validation_start_time - timedelta(
        seconds=embargo_seconds
    )
    retained = []
    purged = []
    embargoed = []

    for index in range(validation_start_index):
        metadata = split.metadata[index]
        if metadata.actual_label_end_time >= validation_start_time:
            purged.append(index)
        elif metadata.feature_window_close >= embargo_cutoff:
            embargoed.append(index)
        else:
            retained.append(index)

    train_indices = tuple(retained)
    purged_indices = tuple(purged)
    embargoed_indices = tuple(embargoed)
    if not train_indices:
        raise WalkForwardError(
            f"fold {fold_index} has no training rows after purge/embargo"
        )

    return WalkForwardFold(
        fold_index,
        validation_start_time,
        validation_end_time,
        train_indices,
        validation_indices,
        purged_indices,
        embargoed_indices,
        _keys(split, train_indices),
        _keys(split, validation_indices),
        _keys(split, purged_indices),
        _keys(split, embargoed_indices),
    )


def generate_walk_forward_folds(
    experiment: ExperimentDatasetBundle,
    spec: WalkForwardSpec,
) -> WalkForwardPlan:
    """Generate leakage-safe expanding folds inside the TRAIN holdout only."""
    if type(experiment) is not ExperimentDatasetBundle:
        raise WalkForwardError(
            "Walk-Forward V1 requires ExperimentDatasetBundle"
        )
    if type(spec) is not WalkForwardSpec:
        raise WalkForwardError("exact WalkForwardSpec required")

    source = experiment.train
    codes = {item.code for item in source.metadata}
    if len(codes) != 1:
        raise WalkForwardError(
            "Walk-Forward V1 requires exactly one TRAIN symbol"
        )
    closes = tuple(
        item.feature_window_close for item in source.metadata
    )
    if any(
        current <= previous
        for previous, current in zip(closes, closes[1:])
    ):
        raise WalkForwardError(
            "Walk-Forward V1 requires strictly increasing TRAIN times"
        )
    row_count = source.row_count
    required = spec.minimum_train_samples + spec.validation_samples
    if row_count < required:
        raise WalkForwardError(
            "TRAIN split is too small for the requested first fold"
        )

    starts = tuple(
        range(
            spec.minimum_train_samples,
            row_count - spec.validation_samples + 1,
            spec.step_samples,
        )
    )
    if not starts:
        raise WalkForwardError("Walk-Forward specification produced no folds")

    folds = tuple(
        _fold(
            source,
            fold_index=index,
            validation_start_index=start,
            validation_samples=spec.validation_samples,
            embargo_seconds=spec.embargo_seconds,
        )
        for index, start in enumerate(starts)
    )
    last_validation_end = (
        starts[-1] + spec.validation_samples
    )
    unused_tail = row_count - last_validation_end

    return WalkForwardPlan(
        WALK_FORWARD_VERSION,
        experiment.dataset_id,
        experiment.label_name,
        experiment.feature_names,
        "TRAIN",
        row_count,
        unused_tail,
        spec,
        folds,
    )
