"""Experiment Metadata V1 over verified Research Dataset + ML Adapter outputs.

This layer adds the selected Label's exact Cross-Day end-time authority to
ML-ready samples.  It does not create new train/test splits, generate
walk-forward folds, train models, shuffle samples, or compute metrics.

The key distinction is intentional: a Research Dataset row carries a
sample-wide actual_label_end_time spanning all Labels, while experiment
leakage control must use the selected Label's own actual_label_end_time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re

from ..cross_day_dataset import (
    VerifiedMultiSourceCrossDayDataset,
    load_verified_multi_source_cross_day_dataset,
)
from ..cross_day_dataset.artifact_models import MultiSourceCrossDayArtifactError
from .ml import (
    MLDatasetBundle,
    MLDatasetError,
    MLDatasetSplit,
    build_ml_dataset,
)


EXPERIMENT_METADATA_VERSION = "market-vault-experiment-metadata-v1"
_EXPERIMENT_SPLITS = ("TRAIN", "VALIDATION", "TEST")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ExperimentMetadataError(ValueError):
    """Fail-closed Experiment Metadata V1 input/projection error."""


@dataclass(frozen=True, slots=True)
class ExperimentSampleMetadata:
    sample_key: str
    code: str
    feature_window_close: datetime
    actual_label_end_time: datetime
    label_value_id: str

    def __post_init__(self) -> None:
        if (
            type(self.sample_key) is not str
            or _SHA256_RE.fullmatch(self.sample_key) is None
        ):
            raise ExperimentMetadataError(
                "sample_key must be a 64-character lowercase hex identity"
            )
        if type(self.code) is not str or not self.code.startswith("US."):
            raise ExperimentMetadataError("code must be a US market symbol")
        for name in ("feature_window_close", "actual_label_end_time"):
            value = getattr(self, name)
            if type(value) is not datetime or value.tzinfo is None:
                raise ExperimentMetadataError(
                    f"{name} must be a timezone-aware datetime"
                )
        if self.actual_label_end_time <= self.feature_window_close:
            raise ExperimentMetadataError(
                "selected Label must end after feature_window_close"
            )
        if (
            type(self.label_value_id) is not str
            or _SHA256_RE.fullmatch(self.label_value_id) is None
        ):
            raise ExperimentMetadataError(
                "label_value_id must be a 64-character lowercase hex identity"
            )


@dataclass(frozen=True, slots=True)
class ExperimentSplit:
    split: str
    ml_split: MLDatasetSplit
    metadata: tuple[ExperimentSampleMetadata, ...]

    def __post_init__(self) -> None:
        if self.split not in _EXPERIMENT_SPLITS:
            raise ExperimentMetadataError("invalid Experiment split")
        if type(self.ml_split) is not MLDatasetSplit:
            raise ExperimentMetadataError("exact MLDatasetSplit required")
        if self.ml_split.split != self.split:
            raise ExperimentMetadataError("Experiment/ML split name mismatch")
        if type(self.metadata) is not tuple or not all(
            type(item) is ExperimentSampleMetadata for item in self.metadata
        ):
            raise ExperimentMetadataError(
                "metadata must be an immutable ExperimentSampleMetadata tuple"
            )
        if len(self.metadata) != self.ml_split.row_count:
            raise ExperimentMetadataError("Experiment/ML row count mismatch")
        for ml_meta, exp_meta in zip(self.ml_split.metadata, self.metadata):
            if (
                ml_meta.sample_key != exp_meta.sample_key
                or ml_meta.code != exp_meta.code
                or ml_meta.feature_window_close != exp_meta.feature_window_close
            ):
                raise ExperimentMetadataError(
                    "Experiment metadata differs from ML sample identity"
                )

    @property
    def X(self):
        return self.ml_split.X

    @property
    def y(self):
        return self.ml_split.y

    @property
    def feature_names(self):
        return self.ml_split.feature_names

    @property
    def label_name(self):
        return self.ml_split.label_name

    @property
    def row_count(self) -> int:
        return self.ml_split.row_count


@dataclass(frozen=True, slots=True)
class ExperimentDatasetBundle:
    version: str
    dataset_id: str
    feature_names: tuple[str, ...]
    label_name: str
    label_logical_type: str
    ml_bundle: MLDatasetBundle
    train: ExperimentSplit
    validation: ExperimentSplit
    test: ExperimentSplit

    def __post_init__(self) -> None:
        if self.version != EXPERIMENT_METADATA_VERSION:
            raise ExperimentMetadataError(
                "unsupported Experiment Metadata version"
            )
        if (
            type(self.dataset_id) is not str
            or _SHA256_RE.fullmatch(self.dataset_id) is None
        ):
            raise ExperimentMetadataError(
                "dataset_id must be a 64-character lowercase hex identity"
            )
        if type(self.ml_bundle) is not MLDatasetBundle:
            raise ExperimentMetadataError("exact MLDatasetBundle required")
        if (
            self.ml_bundle.dataset_id != self.dataset_id
            or self.ml_bundle.feature_names != self.feature_names
            or self.ml_bundle.label_name != self.label_name
            or self.ml_bundle.label_logical_type != self.label_logical_type
        ):
            raise ExperimentMetadataError(
                "Experiment bundle schema differs from ML bundle"
            )
        if tuple(
            item.split for item in (self.train, self.validation, self.test)
        ) != _EXPERIMENT_SPLITS:
            raise ExperimentMetadataError("Experiment split ordering is invalid")
        for exp_split, ml_split in zip(
            (self.train, self.validation, self.test),
            (
                self.ml_bundle.train,
                self.ml_bundle.validation,
                self.ml_bundle.test,
            ),
        ):
            if exp_split.ml_split is not ml_split:
                raise ExperimentMetadataError(
                    "Experiment split must wrap the bundle's exact ML split"
                )

    @property
    def row_count(self) -> int:
        return self.train.row_count + self.validation.row_count + self.test.row_count

    def split(self, name: str) -> ExperimentSplit:
        if name == "TRAIN":
            return self.train
        if name == "VALIDATION":
            return self.validation
        if name == "TEST":
            return self.test
        raise ExperimentMetadataError(
            "split must be TRAIN, VALIDATION, or TEST"
        )


def _verified(dataset: VerifiedMultiSourceCrossDayDataset):
    if type(dataset) is not VerifiedMultiSourceCrossDayDataset:
        raise ExperimentMetadataError(
            "Experiment Metadata V1 requires a Verified Research Dataset artifact"
        )
    try:
        fresh = load_verified_multi_source_cross_day_dataset(dataset.build_path)
    except (MultiSourceCrossDayArtifactError, OSError, TypeError, ValueError) as exc:
        raise ExperimentMetadataError(
            "verified Research Dataset revalidation failed"
        ) from exc
    if fresh.dataset_id != dataset.dataset_id:
        raise ExperimentMetadataError(
            "verified Research Dataset identity changed since load"
        )
    return fresh


def _selected_label_values(dataset, label_name: str):
    selected = tuple(
        value
        for value in dataset.cross_day_labels.values
        if value.label_name == label_name
    )
    mapping = {}
    for value in selected:
        if value.sample_key in mapping:
            raise ExperimentMetadataError(
                "selected Label values contain duplicate sample keys"
            )
        mapping[value.sample_key] = value
    return mapping


def _experiment_split(
    ml_split: MLDatasetSplit,
    label_values,
) -> ExperimentSplit:
    metadata = []
    for y, ml_meta in zip(ml_split.y, ml_split.metadata):
        value = label_values.get(ml_meta.sample_key)
        if (
            value is None
            or value.status != "COMPLETE"
            or value.actual_label_end_time is None
        ):
            raise ExperimentMetadataError(
                "selected Label value/end-time evidence is missing"
            )
        if value.value != y:
            raise ExperimentMetadataError(
                "ML Label value differs from selected Cross-Day Label value"
            )
        metadata.append(
            ExperimentSampleMetadata(
                ml_meta.sample_key,
                ml_meta.code,
                ml_meta.feature_window_close,
                value.actual_label_end_time,
                value.value_id,
            )
        )
    return ExperimentSplit(
        ml_split.split,
        ml_split,
        tuple(metadata),
    )


def build_experiment_dataset(
    dataset: VerifiedMultiSourceCrossDayDataset,
    *,
    label_field: str,
    feature_fields=None,
) -> ExperimentDatasetBundle:
    """Build ML-ready experiment data with selected-Label end-time authority."""
    fresh = _verified(dataset)
    try:
        ml_bundle = build_ml_dataset(
            fresh,
            label_field=label_field,
            feature_fields=feature_fields,
        )
    except MLDatasetError as exc:
        raise ExperimentMetadataError(str(exc)) from exc

    label_values = _selected_label_values(fresh, ml_bundle.label_name)
    splits = tuple(
        _experiment_split(split, label_values)
        for split in (
            ml_bundle.train,
            ml_bundle.validation,
            ml_bundle.test,
        )
    )
    return ExperimentDatasetBundle(
        EXPERIMENT_METADATA_VERSION,
        fresh.dataset_id,
        ml_bundle.feature_names,
        ml_bundle.label_name,
        ml_bundle.label_logical_type,
        ml_bundle,
        splits[0],
        splits[1],
        splits[2],
    )
