"""Frozen numeric semantic schemas; no physical/Parquet schema in Phase A1."""

from __future__ import annotations

from dataclasses import dataclass

from ._validation import ObservationError, items, text

OBSERVATION_SCHEMA_VERSION = "observation-schema-v1"
OBSERVATION_VALUE_SCHEMA_ID_VERSION = "observation-value-schema-v1"
OBSERVATION_KEY_VERSION = "observation-key-v1"
OBSERVATION_VERSION_ID_VERSION = "observation-version-v1"
OBSERVATION_SOURCE_SNAPSHOT_ID_VERSION = "observation-source-snapshot-v1"
OBSERVATION_SOURCE_CONTENT_ID_VERSION = "observation-source-content-v1"
OBSERVATION_COVERAGE_ID_VERSION = "observation-coverage-v1"
OBSERVATION_CONTENT_ID_VERSION = "observation-content-v1"
OBSERVATION_BUILD_ID_VERSION = "observation-build-v1"

OBSERVATION_NUMERIC_TYPES = ("int64", "float64")
OBSERVATION_VALUE_STATUSES = ("VALUE", "NOT_REPORTED", "WITHDRAWN")


@dataclass(frozen=True)
class ObservationValueField:
    """Explicit field unit and representation tokens; no conversion inferred."""

    name: str
    logical_type: str
    unit: str
    representation: str

    def __post_init__(self) -> None:
        for name in ("name", "logical_type", "unit", "representation"):
            object.__setattr__(self, name, text(getattr(self, name), name))
        if self.logical_type not in OBSERVATION_NUMERIC_TYPES:
            raise ObservationError(f"unsupported numeric logical type {self.logical_type!r}")


@dataclass(frozen=True)
class ObservationValueSchema:
    """Nonempty ordered fields; order is part of the logical schema identity."""

    fields: tuple[ObservationValueField, ...]

    def __post_init__(self) -> None:
        fields = items(self.fields, ObservationValueField, "fields", nonempty=True)
        if len({item.name for item in fields}) != len(fields):
            raise ObservationError("duplicate value field names")
        object.__setattr__(self, "fields", fields)
