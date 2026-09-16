"""Frozen A4.1 declarations; A3 remains the sole source-scope authority."""

from dataclasses import dataclass, field, replace
import unicodedata

from ..dataset.models import DatasetField
from ..dataset.spec_models import (
    SpecParameter, SpecValidationError, _normalize_parameters,
    _require_spec_name, _require_spec_version, _require_transform_ref,
)
from ..observation.pit_models import ObservationSourceSpec

OBSERVATION_FEATURE_SPEC_SCHEMA_VERSION = "observation-feature-spec-v1"
OBSERVATION_FEATURE_SPEC_CONTENT_ID_VERSION = "observation-feature-spec-content-v1"
OBSERVATION_FEATURE_SPEC_ARTIFACT_VERSION = "observation-feature-spec-yaml-v1"


@dataclass(frozen=True, slots=True)
class ObservationFeatureSpec:
    spec_schema_version: str
    name: str
    version: str
    output: DatasetField
    source_spec: ObservationSourceSpec
    transform_ref: str
    parameters: tuple[SpecParameter, ...] = ()
    kind: str = field(default="FEATURE", init=False)

    def __post_init__(self):
        if self.spec_schema_version != OBSERVATION_FEATURE_SPEC_SCHEMA_VERSION:
            raise SpecValidationError("unsupported Observation Feature spec schema")
        object.__setattr__(self, "name", _require_spec_name(self.name))
        object.__setattr__(self, "version", _require_spec_version(self.version))
        object.__setattr__(self, "transform_ref", _require_transform_ref(self.transform_ref))
        if type(self.output) is not DatasetField or type(self.source_spec) is not ObservationSourceSpec:
            raise SpecValidationError("requires exact DatasetField and ObservationSourceSpec")
        output, source = replace(self.output), replace(self.source_spec)
        if output.name != self.name or output.logical_type not in ("int64", "float64") or output.nullable:
            raise SpecValidationError("output must be same-name non-nullable int64 or float64")
        object.__setattr__(self, "output", output)
        object.__setattr__(self, "source_spec", source)
        parameters = _normalize_parameters(self.parameters)
        for parameter in parameters:
            for value in (parameter.name, parameter.value):
                if isinstance(value, str) and any(unicodedata.category(c) in ("Cf", "Cs") for c in value):
                    raise SpecValidationError("unsafe Unicode parameter")
        object.__setattr__(self, "parameters", tuple(replace(p) for p in parameters))


def normalize_specs(specs):
    if type(specs) is not tuple or any(type(s) is not ObservationFeatureSpec for s in specs):
        raise SpecValidationError("feature_specs requires an ObservationFeatureSpec tuple")
    result = tuple(replace(s) for s in specs)
    if len({s.name for s in result}) != len(result):
        raise SpecValidationError("duplicate Observation Feature name")
    return tuple(sorted(result, key=lambda s: (s.kind, s.name, s.version)))
