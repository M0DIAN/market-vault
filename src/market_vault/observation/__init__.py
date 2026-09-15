"""Observation semantic identities and explicit immutable artifact authority."""

from .artifact_models import (
    ObservationArtifactError, ObservationMaterializationError,
    ObservationMaterializationResult, VerifiedObservationBuild,
)
from .artifact_schema import (
    OBSERVATION_ARTIFACT_MANIFEST_VERSION, OBSERVATION_ARTIFACT_FORMAT_VERSION,
    OBSERVATION_MATERIALIZER_VERSION,
)
from .materialization import materialize_observation_build
from .reader import load_verified_observation_build
from .pit import assemble_observation_pit_sidecar
from .pit_models import (
    ObservationPITError, ObservationSourceSpec, ObservationPITFeatureBinding,
    ObservationSnapshotPin, ObservationBuildPin, ObservationPITDecision,
    ObservationSampleBinding, ObservationDecisionEvidence, ObservationPITAssemblyResult,
    OBSERVATION_ASSOCIATION_SCHEMA_VERSION, OBSERVATION_SOURCE_SPEC_ID_VERSION,
    OBSERVATION_FEATURE_SPEC_PIN_ID_VERSION, OBSERVATION_BINDING_ID_VERSION,
    MULTI_SOURCE_SAMPLE_VERSION_ID_VERSION, MULTI_SOURCE_PIT_CONTRACT_VERSION,
    OBSERVATION_SAMPLE_BINDING_SCHEMA_VERSION, OBSERVATION_SAMPLE_BINDING_CONTENT_ID_VERSION,
    OBSERVATION_ASSOCIATION_CONTENT_ID_VERSION,
)
from .pit_identity import observation_source_spec_id, feature_spec_pin_id

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
    "assemble_observation_pit_sidecar", "ObservationPITError", "ObservationSourceSpec",
    "ObservationPITFeatureBinding", "ObservationSnapshotPin", "ObservationBuildPin",
    "ObservationPITDecision", "ObservationSampleBinding", "ObservationDecisionEvidence",
    "ObservationPITAssemblyResult", "observation_source_spec_id", "feature_spec_pin_id",
    "OBSERVATION_ASSOCIATION_SCHEMA_VERSION", "OBSERVATION_SOURCE_SPEC_ID_VERSION",
    "OBSERVATION_FEATURE_SPEC_PIN_ID_VERSION", "OBSERVATION_BINDING_ID_VERSION",
    "MULTI_SOURCE_SAMPLE_VERSION_ID_VERSION", "MULTI_SOURCE_PIT_CONTRACT_VERSION",
    "OBSERVATION_SAMPLE_BINDING_SCHEMA_VERSION", "OBSERVATION_SAMPLE_BINDING_CONTENT_ID_VERSION",
    "OBSERVATION_ASSOCIATION_CONTENT_ID_VERSION",
    "ObservationArtifactError", "ObservationMaterializationError",
    "ObservationMaterializationResult", "VerifiedObservationBuild",
    "OBSERVATION_ARTIFACT_MANIFEST_VERSION", "OBSERVATION_ARTIFACT_FORMAT_VERSION",
    "OBSERVATION_MATERIALIZER_VERSION", "materialize_observation_build",
    "load_verified_observation_build",
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
