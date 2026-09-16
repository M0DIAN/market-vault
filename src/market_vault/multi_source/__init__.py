"""Parallel Observation Features and in-memory multi-source Dataset authority."""

from .feature_spec_models import (
    ObservationFeatureSpec, OBSERVATION_FEATURE_SPEC_SCHEMA_VERSION,
    OBSERVATION_FEATURE_SPEC_CONTENT_ID_VERSION, OBSERVATION_FEATURE_SPEC_ARTIFACT_VERSION,
)
from .feature_specs import (
    parse_observation_feature_spec, serialize_observation_feature_spec,
    observation_feature_spec_pin, observation_feature_binding,
)
from .feature_models import (
    ObservationFeatureExecutionError, ObservationFeatureTransformInput,
    ObservationFeatureValueResult, ObservationFeatureSampleResult, ObservationFeatureExecutionResult,
    OBSERVATION_FEATURE_EXECUTION_CONTRACT_VERSION, OBSERVATION_FEATURE_TRANSFORM_CALL_CONTRACT_VERSION,
)
from .feature_identity import (
    observation_feature_spec_content_id, observation_feature_value_id, observation_feature_values_content_id,
)
from .feature_execution import execute_observation_features
from ._orchestration_validation import MultiSourceDatasetError
from ._audit import MultiSourceSampleAudit, sample_audit_content_id
from ._evidence import observation_evidence_content_id
from .identity import (
    MultiSourceDatasetIdentityInput, multi_source_dataset_id,
    MULTI_SOURCE_DATASET_ID_VERSION, MULTI_SOURCE_DATASET_ORCHESTRATION_CONTRACT_VERSION,
)
from .orchestration_models import MultiSourceDatasetOrchestrationResult
from .orchestration import orchestrate_multi_source_dataset_build
from .artifact_models import (
    MultiSourceDatasetArtifactError, MultiSourceDatasetMaterializationError,
    MultiSourceDatasetOutputFile, VerifiedMultiSourceDatasetBuild, MultiSourceDatasetMaterializationResult,
    MULTI_SOURCE_DATASET_MANIFEST_SCHEMA_VERSION, MULTI_SOURCE_DATASET_SERIALIZATION_FORMAT_VERSION,
    MULTI_SOURCE_DATASET_MATERIALIZER_VERSION, MULTI_SOURCE_DATASET_READER_CONTRACT_VERSION,
    MULTI_SOURCE_DATASET_BUILD_REPORT_VERSION,
)
from .manifest import MultiSourceDatasetManifest, serialize_multi_source_dataset_manifest
from .materialization import materialize_multi_source_dataset_build
from .reader import load_verified_multi_source_dataset

__all__ = [
    "ObservationFeatureSpec", "OBSERVATION_FEATURE_SPEC_SCHEMA_VERSION",
    "OBSERVATION_FEATURE_SPEC_CONTENT_ID_VERSION", "OBSERVATION_FEATURE_SPEC_ARTIFACT_VERSION",
    "parse_observation_feature_spec", "serialize_observation_feature_spec",
    "observation_feature_spec_pin", "observation_feature_binding",
    "ObservationFeatureExecutionError", "ObservationFeatureTransformInput",
    "ObservationFeatureValueResult", "ObservationFeatureSampleResult", "ObservationFeatureExecutionResult",
    "OBSERVATION_FEATURE_EXECUTION_CONTRACT_VERSION", "OBSERVATION_FEATURE_TRANSFORM_CALL_CONTRACT_VERSION",
    "observation_feature_spec_content_id", "observation_feature_value_id", "observation_feature_values_content_id",
    "execute_observation_features",
    "MultiSourceDatasetError", "MultiSourceSampleAudit", "sample_audit_content_id",
    "observation_evidence_content_id", "MultiSourceDatasetIdentityInput", "multi_source_dataset_id",
    "MULTI_SOURCE_DATASET_ID_VERSION", "MULTI_SOURCE_DATASET_ORCHESTRATION_CONTRACT_VERSION",
    "MultiSourceDatasetOrchestrationResult", "orchestrate_multi_source_dataset_build",
    "MultiSourceDatasetArtifactError", "MultiSourceDatasetMaterializationError", "MultiSourceDatasetOutputFile",
    "VerifiedMultiSourceDatasetBuild", "MultiSourceDatasetMaterializationResult", "MultiSourceDatasetManifest",
    "serialize_multi_source_dataset_manifest", "materialize_multi_source_dataset_build", "load_verified_multi_source_dataset",
    "MULTI_SOURCE_DATASET_MANIFEST_SCHEMA_VERSION", "MULTI_SOURCE_DATASET_SERIALIZATION_FORMAT_VERSION",
    "MULTI_SOURCE_DATASET_MATERIALIZER_VERSION", "MULTI_SOURCE_DATASET_READER_CONTRACT_VERSION",
    "MULTI_SOURCE_DATASET_BUILD_REPORT_VERSION",
]
