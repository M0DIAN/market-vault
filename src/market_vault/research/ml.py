"""Split-aware ML Dataset Adapter V1 for verified Research Datasets.

This module does not train models, scale Features, shuffle samples, impute
missing values, or perform random train/test splitting.  It consumes one
strictly verified Research Dataset artifact and projects its already-authorized
chronological TRAIN / VALIDATION / TEST assignments into immutable X/y/metadata
tuples.

Pandas conversion is convenience-only and is never part of Dataset authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
import re

from ..cross_day_dataset import (
    VerifiedMultiSourceCrossDayDataset,
    load_verified_multi_source_cross_day_dataset,
)
from ..cross_day_dataset.artifact_models import MultiSourceCrossDayArtifactError


ML_DATASET_ADAPTER_VERSION = "market-vault-ml-dataset-adapter-v1"
ML_SPLITS = ("TRAIN", "VALIDATION", "TEST")
_NUMERIC_TYPES = frozenset(("float64", "int64"))
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class MLDatasetError(ValueError):
    """Fail-closed ML Dataset Adapter V1 input or projection error."""


@dataclass(frozen=True, slots=True)
class MLSampleMetadata:
    sample_key: str
    code: str
    feature_window_close: datetime

    def __post_init__(self) -> None:
        if type(self.sample_key) is not str or _SHA256_RE.fullmatch(self.sample_key) is None:
            raise MLDatasetError("sample_key must be a 64-character lowercase hex identity")
        if type(self.code) is not str or not self.code.startswith("US."):
            raise MLDatasetError("code must be a US market symbol")
        if type(self.feature_window_close) is not datetime or self.feature_window_close.tzinfo is None:
            raise MLDatasetError("feature_window_close must be timezone-aware")


@dataclass(frozen=True, slots=True)
class MLDatasetSplit:
    split: str
    feature_names: tuple[str, ...]
    label_name: str
    label_logical_type: str
    X: tuple[tuple[float, ...], ...]
    y: tuple[float | int, ...]
    metadata: tuple[MLSampleMetadata, ...]

    def __post_init__(self) -> None:
        if self.split not in ML_SPLITS:
            raise MLDatasetError("invalid ML split")
        if type(self.feature_names) is not tuple or not self.feature_names:
            raise MLDatasetError("feature_names must be a non-empty tuple")
        if not all(type(name) is str and name for name in self.feature_names):
            raise MLDatasetError("feature_names must contain non-empty strings")
        if len(set(self.feature_names)) != len(self.feature_names):
            raise MLDatasetError("feature_names must be unique")
        if type(self.label_name) is not str or not self.label_name:
            raise MLDatasetError("label_name must be a non-empty string")
        if self.label_logical_type not in _NUMERIC_TYPES:
            raise MLDatasetError("label_logical_type must be float64 or int64")
        if type(self.X) is not tuple or type(self.y) is not tuple or type(self.metadata) is not tuple:
            raise MLDatasetError("X, y and metadata must be immutable tuples")
        if not len(self.X) == len(self.y) == len(self.metadata):
            raise MLDatasetError("X, y and metadata row counts differ")
        width = len(self.feature_names)
        for row in self.X:
            if type(row) is not tuple or len(row) != width:
                raise MLDatasetError("ML Feature matrix width mismatch")
            if not all(type(value) is float and math.isfinite(value) for value in row):
                raise MLDatasetError("ML Feature matrix must contain finite floats")
        for value in self.y:
            if self.label_logical_type == "int64":
                if type(value) is not int:
                    raise MLDatasetError("int64 ML label must remain an int")
            else:
                if type(value) is not float or not math.isfinite(value):
                    raise MLDatasetError("float64 ML label must remain a finite float")
        if not all(type(item) is MLSampleMetadata for item in self.metadata):
            raise MLDatasetError("metadata must contain MLSampleMetadata")
        ordering = tuple(
            (item.feature_window_close, item.code, item.sample_key)
            for item in self.metadata
        )
        if ordering != tuple(sorted(ordering)):
            raise MLDatasetError("ML split rows must be chronologically ordered")

    @property
    def row_count(self) -> int:
        return len(self.y)

    def to_pandas(self):
        """Return detached pandas X, y, metadata objects.

        Returned objects are convenience copies and are not identity-bearing.
        """
        import pandas as pd

        X = pd.DataFrame(self.X, columns=self.feature_names, dtype="float64")
        y_dtype = "int64" if self.label_logical_type == "int64" else "float64"
        y = pd.Series(self.y, name=self.label_name, dtype=y_dtype)
        metadata = pd.DataFrame({
            "sample_key": tuple(item.sample_key for item in self.metadata),
            "code": tuple(item.code for item in self.metadata),
            "feature_window_close": tuple(
                item.feature_window_close for item in self.metadata
            ),
        })
        return X, y, metadata


@dataclass(frozen=True, slots=True)
class MLDatasetBundle:
    adapter_version: str
    dataset_id: str
    feature_names: tuple[str, ...]
    label_name: str
    label_logical_type: str
    train: MLDatasetSplit
    validation: MLDatasetSplit
    test: MLDatasetSplit

    def __post_init__(self) -> None:
        if self.adapter_version != ML_DATASET_ADAPTER_VERSION:
            raise MLDatasetError("unsupported ML Dataset Adapter version")
        if type(self.dataset_id) is not str or _SHA256_RE.fullmatch(self.dataset_id) is None:
            raise MLDatasetError("dataset_id must be a 64-character lowercase hex identity")
        if tuple(split.split for split in (self.train, self.validation, self.test)) != ML_SPLITS:
            raise MLDatasetError("ML bundle split ordering is invalid")
        for split in (self.train, self.validation, self.test):
            if (
                split.feature_names != self.feature_names
                or split.label_name != self.label_name
                or split.label_logical_type != self.label_logical_type
            ):
                raise MLDatasetError("ML split schema differs from bundle schema")

    @property
    def row_count(self) -> int:
        return self.train.row_count + self.validation.row_count + self.test.row_count

    def split(self, name: str) -> MLDatasetSplit:
        if name == "TRAIN":
            return self.train
        if name == "VALIDATION":
            return self.validation
        if name == "TEST":
            return self.test
        raise MLDatasetError("split must be TRAIN, VALIDATION, or TEST")


def _verified(dataset: VerifiedMultiSourceCrossDayDataset):
    if type(dataset) is not VerifiedMultiSourceCrossDayDataset:
        raise MLDatasetError(
            "ML Dataset Adapter V1 requires a Verified Research Dataset artifact"
        )
    try:
        fresh = load_verified_multi_source_cross_day_dataset(dataset.build_path)
    except (MultiSourceCrossDayArtifactError, OSError, TypeError, ValueError) as exc:
        raise MLDatasetError("verified Research Dataset revalidation failed") from exc
    if fresh.dataset_id != dataset.dataset_id:
        raise MLDatasetError("verified Research Dataset identity changed since load")
    return fresh


def _feature_catalog(dataset) -> tuple[str, ...]:
    names = tuple(spec.name for spec in dataset.ts2_features.feature_specs) + tuple(
        spec.name for spec in dataset.identity_input.observation_feature_specs
    )
    if not names or len(names) != len(set(names)):
        raise MLDatasetError("Research Dataset Feature catalog is empty or ambiguous")
    return names


def _normalize_feature_fields(dataset, feature_fields) -> tuple[str, ...]:
    catalog = _feature_catalog(dataset)
    if feature_fields is None:
        selected = catalog
    else:
        try:
            selected = tuple(feature_fields)
        except TypeError as exc:
            raise MLDatasetError("feature_fields must be an iterable of names") from exc
        if not selected:
            raise MLDatasetError("feature_fields must not be empty")
        if not all(type(name) is str and name for name in selected):
            raise MLDatasetError("feature_fields must contain non-empty strings")
        if len(set(selected)) != len(selected):
            raise MLDatasetError("feature_fields must be unique")
        unknown = tuple(name for name in selected if name not in catalog)
        if unknown:
            raise MLDatasetError(
                "feature_fields contain non-Feature names: " + ", ".join(unknown)
            )
    schema_types = {field.name: field.logical_type for field in dataset.schema.fields}
    for name in selected:
        if schema_types.get(name) not in _NUMERIC_TYPES:
            raise MLDatasetError(f"Feature field must be numeric: {name}")
    return selected


def _label(dataset, label_field: str):
    if type(label_field) is not str or not label_field:
        raise MLDatasetError("label_field must be a non-empty string")
    matches = tuple(
        spec for spec in dataset.cross_day_labels.label_specs
        if spec.name == label_field
    )
    if len(matches) != 1:
        raise MLDatasetError("label_field must select exactly one Dataset Label")
    spec = matches[0]
    if spec.output.logical_type not in _NUMERIC_TYPES:
        raise MLDatasetError("ML label must be float64 or int64")
    return spec


def _float_feature(value, name: str) -> float:
    if type(value) is bool or not isinstance(value, (int, float)):
        raise MLDatasetError(f"Feature value is not numeric: {name}")
    number = float(value)
    if not math.isfinite(number):
        raise MLDatasetError(f"Feature value is not finite: {name}")
    return 0.0 if number == 0.0 else number


def _label_value(value, logical_type: str, name: str):
    if logical_type == "int64":
        if type(value) is not int:
            raise MLDatasetError(f"int64 Label value is not an int: {name}")
        return value
    if type(value) is bool or not isinstance(value, (int, float)):
        raise MLDatasetError(f"float64 Label value is not numeric: {name}")
    number = float(value)
    if not math.isfinite(number):
        raise MLDatasetError(f"float64 Label value is not finite: {name}")
    return 0.0 if number == 0.0 else number


def _project_split(
    dataset,
    *,
    split: str,
    feature_names: tuple[str, ...],
    label_name: str,
    label_logical_type: str,
) -> MLDatasetSplit:
    fields = tuple(field.name for field in dataset.schema.fields)
    if len(fields) != len(set(fields)):
        raise MLDatasetError("Research Dataset schema contains duplicate fields")
    index = {name: position for position, name in enumerate(fields)}
    required = (
        "sample_key",
        "code",
        "feature_window_close",
        "label_status",
        "assignment_status",
        "final_split",
        *feature_names,
        label_name,
    )
    missing = tuple(name for name in required if name not in index)
    if missing:
        raise MLDatasetError("Research Dataset fields are missing: " + ", ".join(missing))

    projected = []
    for row in dataset.rows:
        assignment_status = row[index["assignment_status"]]
        final_split = row[index["final_split"]]
        label_status = row[index["label_status"]]
        if assignment_status != "ASSIGNED" or final_split != split:
            continue
        if label_status != "COMPLETE":
            raise MLDatasetError("ASSIGNED ML row must have COMPLETE Labels")
        metadata = MLSampleMetadata(
            row[index["sample_key"]],
            row[index["code"]],
            row[index["feature_window_close"]],
        )
        X = tuple(_float_feature(row[index[name]], name) for name in feature_names)
        y = _label_value(row[index[label_name]], label_logical_type, label_name)
        projected.append((metadata.feature_window_close, metadata.code, metadata.sample_key, X, y, metadata))

    projected.sort(key=lambda item: item[:3])
    return MLDatasetSplit(
        split,
        feature_names,
        label_name,
        label_logical_type,
        tuple(item[3] for item in projected),
        tuple(item[4] for item in projected),
        tuple(item[5] for item in projected),
    )


def build_ml_dataset(
    dataset: VerifiedMultiSourceCrossDayDataset,
    *,
    label_field: str,
    feature_fields=None,
) -> MLDatasetBundle:
    """Project one verified Research Dataset into chronological ML splits."""
    dataset = _verified(dataset)
    feature_names = _normalize_feature_fields(dataset, feature_fields)
    spec = _label(dataset, label_field)
    if label_field in feature_names:
        raise MLDatasetError("Label leakage: label_field cannot be a Feature field")

    splits = tuple(
        _project_split(
            dataset,
            split=split,
            feature_names=feature_names,
            label_name=label_field,
            label_logical_type=spec.output.logical_type,
        )
        for split in ML_SPLITS
    )
    return MLDatasetBundle(
        ML_DATASET_ADAPTER_VERSION,
        dataset.dataset_id,
        feature_names,
        label_field,
        spec.output.logical_type,
        splits[0],
        splits[1],
        splits[2],
    )
