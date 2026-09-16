"""Deeply immutable, self-validating A4.1 invocation and result records."""

from dataclasses import dataclass, replace

from ..dataset.encoding import DatasetError
from ..dataset.models import ImplementationPin, SpecPin
from ..dataset.spec_models import SpecParameter, _normalize_parameters
from ..observation._validation import sha256, text
from .feature_transforms import _scalar

OBSERVATION_FEATURE_EXECUTION_CONTRACT_VERSION = "observation-feature-execution-v1"
OBSERVATION_FEATURE_TRANSFORM_CALL_CONTRACT_VERSION = "observation-feature-transform-call-v1"
_REF_PREFIX = "market_vault.multi_source.feature_transforms:identity_"
_REASONS = ("STALE", "NOT_REPORTED", "WITHDRAWN", "NO_ELIGIBLE_OBSERVATION", "FUTURE_KNOWN", "ARCHIVE_FUTURE")


class ObservationFeatureExecutionError(DatasetError):
    """A4.1 admission or execution failed; never a missing-value result."""


def _tuple(value, cls, label):
    if type(value) is not tuple or any(type(v) is not cls for v in value):
        raise ObservationFeatureExecutionError(label + " requires an exact typed tuple")
    return value


def _pin_key(pin):
    return pin.kind, pin.name, pin.version, pin.content_sha256


def _impl_type(pin):
    if (type(pin) is not ImplementationPin or pin.version != "v1"
            or pin.name not in (_REF_PREFIX + "float64", _REF_PREFIX + "int64")
            or pin.content_sha256 is None):
        raise ObservationFeatureExecutionError("invalid Observation implementation pin")
    return pin.name.removeprefix(_REF_PREFIX)


def _scalar_checked(value, logical_type):
    try:
        return _scalar(value, logical_type)
    except ValueError as exc:
        raise ObservationFeatureExecutionError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class ObservationFeatureTransformInput:
    field_names: tuple[str, ...]
    field_logical_types: tuple[str, ...]
    values: tuple[int | float, ...]
    parameters: tuple[SpecParameter, ...]

    def __post_init__(self):
        names = tuple(text(n, "input field") for n in _tuple(self.field_names, str, "field_names"))
        types = _tuple(self.field_logical_types, str, "field_logical_types")
        if not names or len(set(names)) != len(names) or type(self.values) is not tuple:
            raise ObservationFeatureExecutionError("invalid or duplicate input fields")
        if len(names) != len(types) or len(names) != len(self.values):
            raise ObservationFeatureExecutionError("input cardinality mismatch")
        values = tuple(_scalar_checked(v, t) for v, t in zip(self.values, types))
        parameters = tuple(replace(p) for p in _normalize_parameters(self.parameters))
        object.__setattr__(self, "field_names", names)
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "parameters", parameters)


@dataclass(frozen=True, slots=True)
class ObservationFeatureValueResult:
    sample_key: str
    multi_source_sample_version_id: str
    feature_name: str
    spec_pin: SpecPin
    implementation_pin: ImplementationPin
    decision_id: str
    status: str
    value: int | float | None
    reason_code: str | None
    consumed_observation_version_id: str | None

    def __post_init__(self):
        for name in ("sample_key", "multi_source_sample_version_id", "decision_id"):
            sha256(getattr(self, name), name)
        if type(self.spec_pin) is not SpecPin or self.spec_pin.kind != "FEATURE":
            raise ObservationFeatureExecutionError("requires FEATURE SpecPin")
        pin = replace(self.spec_pin)
        if self.feature_name != pin.name:
            raise ObservationFeatureExecutionError("feature name/pin mismatch")
        logical_type = _impl_type(self.implementation_pin)
        object.__setattr__(self, "spec_pin", pin)
        object.__setattr__(self, "implementation_pin", replace(self.implementation_pin))
        if self.status == "COMPLETE":
            if self.reason_code is not None:
                raise ObservationFeatureExecutionError("COMPLETE requires null reason")
            sha256(self.consumed_observation_version_id, "consumed version")
            object.__setattr__(self, "value", _scalar_checked(self.value, logical_type))
        elif self.status == "EXCLUDED":
            if self.reason_code not in _REASONS or self.value is not None or self.consumed_observation_version_id is not None:
                raise ObservationFeatureExecutionError("EXCLUDED must not consume a value")
        else:
            raise ObservationFeatureExecutionError("unknown value status")


@dataclass(frozen=True, slots=True)
class ObservationFeatureSampleResult:
    sample_key: str
    multi_source_sample_version_id: str
    status: str
    values: tuple[ObservationFeatureValueResult, ...]

    def __post_init__(self):
        sha256(self.sample_key, "sample_key")
        sha256(self.multi_source_sample_version_id, "multi_source_sample_version_id")
        values = tuple(replace(v) for v in _tuple(self.values, ObservationFeatureValueResult, "values"))
        keys = [_pin_key(v.spec_pin) for v in values]
        if keys != sorted(keys) or len({v.feature_name for v in values}) != len(values):
            raise ObservationFeatureExecutionError("value order or duplicate feature")
        if any(v.sample_key != self.sample_key or v.multi_source_sample_version_id != self.multi_source_sample_version_id for v in values):
            raise ObservationFeatureExecutionError("value/sample reference mismatch")
        expected = "COMPLETE" if all(v.status == "COMPLETE" for v in values) else "EXCLUDED"
        if self.status != expected:
            raise ObservationFeatureExecutionError("derived sample status mismatch")
        object.__setattr__(self, "values", values)


@dataclass(frozen=True, slots=True)
class ObservationFeatureExecutionResult:
    samples: tuple[ObservationFeatureSampleResult, ...]
    feature_spec_pins: tuple[SpecPin, ...]
    implementation_pins: tuple[ImplementationPin, ...]
    execution_contract_version: str = OBSERVATION_FEATURE_EXECUTION_CONTRACT_VERSION

    def __post_init__(self):
        if self.execution_contract_version != OBSERVATION_FEATURE_EXECUTION_CONTRACT_VERSION:
            raise ObservationFeatureExecutionError("unsupported execution contract")
        samples = tuple(replace(s) for s in _tuple(self.samples, ObservationFeatureSampleResult, "samples"))
        pins = tuple(replace(p) for p in _tuple(self.feature_spec_pins, SpecPin, "feature_spec_pins"))
        impls = tuple(replace(p) for p in _tuple(self.implementation_pins, ImplementationPin, "implementation_pins"))
        if any(p.kind != "FEATURE" for p in pins) or len({p.name for p in pins}) != len(pins) or pins != tuple(sorted(pins, key=_pin_key)):
            raise ObservationFeatureExecutionError("invalid spec pin set/order")
        for pin in impls:
            _impl_type(pin)
        if len({(p.name, p.version) for p in impls}) != len(impls) or impls != tuple(sorted(impls, key=lambda p: (p.name, p.version, p.content_sha256))):
            raise ObservationFeatureExecutionError("conflicting implementation pins/order")
        keys = [s.sample_key for s in samples]
        if keys != sorted(set(keys)):
            raise ObservationFeatureExecutionError("duplicate or unordered samples")
        used = set()
        per_spec_implementation = {}
        for sample in samples:
            if tuple(v.spec_pin for v in sample.values) != pins:
                raise ObservationFeatureExecutionError("sample spec cardinality mismatch")
            for value in sample.values:
                if value.implementation_pin not in impls:
                    raise ObservationFeatureExecutionError("unlisted implementation pin")
                previous = per_spec_implementation.setdefault(value.spec_pin, value.implementation_pin)
                if previous != value.implementation_pin:
                    raise ObservationFeatureExecutionError("one spec cannot use conflicting implementation pins")
                used.add(value.implementation_pin)
        if samples and used != set(impls):
            raise ObservationFeatureExecutionError("unused implementation pin")
        object.__setattr__(self, "samples", samples)
        object.__setattr__(self, "feature_spec_pins", pins)
        object.__setattr__(self, "implementation_pins", impls)
