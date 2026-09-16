"""Parallel A4.1 Observation Feature declarations, identities and pure execution."""

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
]
