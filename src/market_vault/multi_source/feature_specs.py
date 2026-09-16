"""Strict in-memory YAML admission and canonical JSON-as-YAML serialization."""

from dataclasses import asdict, fields, replace
import json
import math
import unicodedata

import yaml

from ..dataset.encoding import DatasetError, normalize_nfc, reject_unsafe_text
from ..dataset.models import DatasetField, SpecPin
from ..dataset.spec_models import SpecParameter, SpecValidationError
from ..dataset.specs import _parse_single_mapping, _require_exact_fields, _require_mapping
from ..observation._validation import ObservationError
from ..observation.models import ObservationDimension
from ..observation.pit_models import ObservationSourceSpec, ObservationPITFeatureBinding
from .feature_spec_models import ObservationFeatureSpec


def _strict_scalars(value):
    if type(value) is dict:
        names = []
        for key, child in value.items():
            reject_unsafe_text(key, "mapping key")
            names.append(normalize_nfc(key))
            _strict_scalars(child)
        if len(set(names)) != len(names):
            raise SpecValidationError("duplicate normalized mapping key")
    elif type(value) is list:
        for child in value:
            _strict_scalars(child)
    elif type(value) is str:
        reject_unsafe_text(value, "scalar")
        if any(unicodedata.category(c) in ("Cf", "Cs") for c in value):
            raise SpecValidationError("unsafe Unicode scalar")
    elif type(value) is float and not math.isfinite(value):
        raise SpecValidationError("non-finite scalar")
    elif value is not None and type(value) not in (str, bool, int, float):
        raise SpecValidationError("unsupported scalar")


def _list(value, name):
    if type(value) is not list:
        raise SpecValidationError(name + " requires a list")
    return value


def _record(value, names, label):
    value = _require_mapping(value, label)
    _require_exact_fields(value, tuple(names), label)
    return value


def parse_observation_feature_spec(document: str | bytes) -> ObservationFeatureSpec:
    """Parse one supplied document; never read a path or execute a reference."""
    try:
        if type(document) is bytes:
            document = document.decode("utf-8", errors="strict")
        if type(document) is not str:
            raise SpecValidationError("document requires text or UTF-8 bytes")
        # Explicit tags are forbidden even when SafeConstructor supports the tag.
        for event in yaml.parse(document):
            if getattr(event, "tag", None) is not None:
                raise SpecValidationError("explicit YAML tags are forbidden")
        data = _parse_single_mapping(document)
        _strict_scalars(data)
        _require_exact_fields(data, tuple(f.name for f in fields(ObservationFeatureSpec)), "spec")
        if data["kind"] != "FEATURE":
            raise SpecValidationError("kind must be FEATURE")
        output = _record(data["output"], ("name", "logical_type", "nullable"), "output")
        source = dict(_record(data["source_spec"], (f.name for f in fields(ObservationSourceSpec)), "source_spec"))
        source["dimensions"] = tuple(ObservationDimension(**_record(
            d, ("name", "logical_type", "value"), "dimension"))
            for d in _list(source["dimensions"], "dimensions"))
        entries = (_record(e, ("code", "entity_id"), "code_entity_map entry")
                   for e in _list(source["code_entity_map"], "code_entity_map"))
        source["code_entity_map"] = tuple((e["code"], e["entity_id"]) for e in entries)
        source["input_field_names"] = tuple(_list(source["input_field_names"], "input_field_names"))
        parameters = _require_mapping(data["parameters"], "parameters")
        return ObservationFeatureSpec(
            data["spec_schema_version"], data["name"], data["version"], DatasetField(**output),
            ObservationSourceSpec(**source), data["transform_ref"],
            tuple(SpecParameter(k, v) for k, v in parameters.items()))
    except SpecValidationError:
        raise
    except (DatasetError, ObservationError, UnicodeError, yaml.YAMLError, TypeError, ValueError) as exc:
        raise SpecValidationError(str(exc)) from exc


def serialize_observation_feature_spec(spec: ObservationFeatureSpec) -> bytes:
    if type(spec) is not ObservationFeatureSpec:
        raise SpecValidationError("requires ObservationFeatureSpec")
    data = asdict(replace(spec))
    data["source_spec"]["code_entity_map"] = [
        {"code": c, "entity_id": e} for c, e in spec.source_spec.code_entity_map]
    data["parameters"] = {p.name: p.value for p in spec.parameters}
    return (json.dumps(data, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")


def observation_feature_spec_pin(spec: ObservationFeatureSpec) -> SpecPin:
    from .feature_identity import observation_feature_spec_content_id
    content = observation_feature_spec_content_id(spec)
    return SpecPin(kind="FEATURE", name=spec.name, version=spec.version, content_sha256=content)


def observation_feature_binding(spec: ObservationFeatureSpec) -> ObservationPITFeatureBinding:
    return ObservationPITFeatureBinding(observation_feature_spec_pin(spec), spec.source_spec)
