"""Exactly two static registrations; source is pinned once, outside execution."""

from dataclasses import dataclass
from pathlib import Path

from ..dataset.models import ImplementationPin
from . import feature_transforms
from .feature_identity import _implementation_fingerprint, _source_sha256
from .feature_models import ObservationFeatureExecutionError


@dataclass(frozen=True, slots=True)
class ObservationFeatureRegistration:
    transform_ref: str
    implementation_version: str
    implementation_content_sha256: str
    transform_call_contract_version: str
    observation_schema_version: str
    input_arity: int
    input_logical_types: tuple[str, ...]
    output_logical_type: str
    parameters: tuple
    implementation: object

    @property
    def implementation_pin(self):
        return ImplementationPin(self.transform_ref, self.implementation_version, self.implementation_content_sha256)


_SOURCE_SHA256 = _source_sha256(Path(feature_transforms.__file__).read_bytes())
_REGISTRATIONS = tuple(ObservationFeatureRegistration(
    f"market_vault.multi_source.feature_transforms:identity_{logical_type}", "v1",
    _implementation_fingerprint(f"market_vault.multi_source.feature_transforms:identity_{logical_type}",
                                _SOURCE_SHA256, logical_type),
    "observation-feature-transform-call-v1", "observation-schema-v1", 1,
    (logical_type,), logical_type, (), implementation)
    for logical_type, implementation in (("float64", feature_transforms.identity_float64),
                                         ("int64", feature_transforms.identity_int64)))


def built_in_observation_feature_registrations() -> tuple[ObservationFeatureRegistration, ...]:
    return _REGISTRATIONS


def _preflight_registry():
    if len(_REGISTRATIONS) != 2:
        raise ObservationFeatureExecutionError("invalid built-in registry cardinality")
    for r, logical_type in zip(_REGISTRATIONS, ("float64", "int64")):
        ref = f"market_vault.multi_source.feature_transforms:identity_{logical_type}"
        if (type(r) is not ObservationFeatureRegistration or r.transform_ref != ref
                or r.implementation_version != "v1" or r.input_arity != 1
                or r.input_logical_types != (logical_type,) or r.output_logical_type != logical_type
                or r.parameters != () or r.transform_call_contract_version != "observation-feature-transform-call-v1"
                or r.observation_schema_version != "observation-schema-v1"
                or r.implementation is not getattr(feature_transforms, "identity_" + logical_type)
                or r.implementation_content_sha256 != _implementation_fingerprint(ref, _SOURCE_SHA256, logical_type)):
            raise ObservationFeatureExecutionError("invalid built-in registry contract/fingerprint")


def _resolve(spec):
    for registration in _REGISTRATIONS:
        if registration.transform_ref == spec.transform_ref:
            if (spec.parameters != () or len(spec.source_spec.input_field_names) != 1
                    or spec.output.logical_type != registration.output_logical_type):
                raise ObservationFeatureExecutionError("spec/transform contract mismatch")
            return registration
    raise ObservationFeatureExecutionError("unknown Observation transform reference")
