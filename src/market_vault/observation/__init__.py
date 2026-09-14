"""Observation A1: pure semantic models and identities, not verified artifacts."""

from ._validation import ObservationError
from .identity import (
    observation_build_id,
    observation_content_id,
    observation_coverage_id,
    observation_key,
    observation_source_content_id,
    observation_source_snapshot_id,
    observation_value_schema_id,
    observation_version_id,
)
from .models import (
    Observation,
    ObservationBuildIdentityInput,
    ObservationContractPin,
    ObservationCoverage,
    ObservationDimension,
    ObservationScope,
    ObservationSnapshotMember,
    ObservationSourceSnapshotInput,
)
from .schema import (
    OBSERVATION_BUILD_ID_VERSION,
    OBSERVATION_CONTENT_ID_VERSION,
    OBSERVATION_COVERAGE_ID_VERSION,
    OBSERVATION_KEY_VERSION,
    OBSERVATION_NUMERIC_TYPES,
    OBSERVATION_SCHEMA_VERSION,
    OBSERVATION_SOURCE_CONTENT_ID_VERSION,
    OBSERVATION_SOURCE_SNAPSHOT_ID_VERSION,
    OBSERVATION_VALUE_SCHEMA_ID_VERSION,
    OBSERVATION_VALUE_STATUSES,
    OBSERVATION_VERSION_ID_VERSION,
    ObservationValueField,
    ObservationValueSchema,
)

__all__ = [
    "OBSERVATION_BUILD_ID_VERSION", "OBSERVATION_CONTENT_ID_VERSION",
    "OBSERVATION_COVERAGE_ID_VERSION", "OBSERVATION_KEY_VERSION",
    "OBSERVATION_NUMERIC_TYPES", "OBSERVATION_SCHEMA_VERSION",
    "OBSERVATION_SOURCE_CONTENT_ID_VERSION", "OBSERVATION_SOURCE_SNAPSHOT_ID_VERSION",
    "OBSERVATION_VALUE_SCHEMA_ID_VERSION", "OBSERVATION_VALUE_STATUSES",
    "OBSERVATION_VERSION_ID_VERSION", "Observation", "ObservationBuildIdentityInput",
    "ObservationContractPin", "ObservationCoverage", "ObservationDimension",
    "ObservationError", "ObservationScope", "ObservationSnapshotMember",
    "ObservationSourceSnapshotInput", "ObservationValueField", "ObservationValueSchema",
    "observation_build_id", "observation_content_id", "observation_coverage_id",
    "observation_key", "observation_source_content_id", "observation_source_snapshot_id",
    "observation_value_schema_id", "observation_version_id",
]
