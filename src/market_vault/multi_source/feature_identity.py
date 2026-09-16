"""Frozen A4.1 identity payloads; no Dataset cohort identity is defined here."""

from dataclasses import replace
import hashlib

from ..dataset.encoding import encode_identity
from ..dataset.identity import _implementation_digest
from ..dataset.spec_models import SpecValidationError
from ..observation.pit_identity import feature_spec_pin_id, observation_source_spec_id
from .feature_spec_models import ObservationFeatureSpec, OBSERVATION_FEATURE_SPEC_CONTENT_ID_VERSION
from .feature_models import ObservationFeatureExecutionResult, ObservationFeatureValueResult, ObservationFeatureExecutionError


def observation_feature_spec_content_id(spec: ObservationFeatureSpec) -> str:
    if type(spec) is not ObservationFeatureSpec:
        raise SpecValidationError("identity requires ObservationFeatureSpec")
    spec = replace(spec)
    data = dict(spec_schema_version=spec.spec_schema_version, kind=spec.kind, name=spec.name,
                spec_version=spec.version, output_name=spec.output.name,
                output_logical_type=spec.output.logical_type, output_nullable=spec.output.nullable,
                observation_source_spec_id=observation_source_spec_id(spec.source_spec),
                transform_ref=spec.transform_ref, parameter_count=len(spec.parameters))
    for i, parameter in enumerate(spec.parameters):
        data[f"parameter_{i:04d}_name"] = parameter.name
        data[f"parameter_{i:04d}_value"] = parameter.value
    return encode_identity(OBSERVATION_FEATURE_SPEC_CONTENT_ID_VERSION, data)


def _source_sha256(source: bytes) -> str:
    normalized = source.decode("utf-8", errors="strict").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _implementation_fingerprint(transform_ref, source_sha256, logical_type):
    return encode_identity("observation-feature-implementation-v1", {
        "transform_ref": transform_ref, "implementation_version": "v1",
        "implementation_source_sha256": source_sha256,
        "transform_call_contract_version": "observation-feature-transform-call-v1",
        "observation_schema_version": "observation-schema-v1", "input_arity": 1,
        "input_0000_logical_type": logical_type, "output_logical_type": logical_type,
        "parameter_count": 0})


def observation_feature_value_id(value: ObservationFeatureValueResult) -> str:
    if type(value) is not ObservationFeatureValueResult:
        raise ObservationFeatureExecutionError("identity requires ObservationFeatureValueResult")
    value = replace(value)
    return encode_identity("observation-feature-value-v1", {
        "sample_key": value.sample_key, "multi_source_sample_version_id": value.multi_source_sample_version_id,
        "feature_name": value.feature_name, "feature_spec_pin_id": feature_spec_pin_id(value.spec_pin),
        "implementation_pin_id": _implementation_digest(value.implementation_pin),
        "decision_id": value.decision_id, "status": value.status, "value": value.value,
        "reason_code": value.reason_code, "consumed_observation_version_id": value.consumed_observation_version_id})


def observation_feature_values_content_id(result: ObservationFeatureExecutionResult) -> str:
    if type(result) is not ObservationFeatureExecutionResult:
        raise ObservationFeatureExecutionError("requires ObservationFeatureExecutionResult")
    result = replace(result)
    values = sorted((v for s in result.samples for v in s.values),
                    key=lambda v: (v.sample_key, feature_spec_pin_id(v.spec_pin)))
    ids = tuple(observation_feature_value_id(v) for v in values)
    return encode_identity("observation-feature-values-v1", {"count": len(ids), "members": "".join(ids)})
