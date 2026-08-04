"""Strict YAML parsing and deterministic semantic content identity for
versioned Feature and Label spec documents.

The public entry points parse one spec document into its frozen typed model,
hash its semantic content deterministically, and convert it to the existing
:class:`SpecPin` of the manifest core. The YAML reader is fail-closed: only
plain YAML 1.1 scalars and collections are accepted; UTF-8 BOMs, duplicate
mapping keys (including nested ones), anchors, aliases, merge keys (``<<``),
custom tags, and multi-document streams are rejected; the root must be a
mapping; unknown and missing fields fail at every level; and the text must be
a single UTF-8 string. File loaders read UTF-8 strictly. File paths never
enter the spec identity.

All PyYAML, Unicode, and model-validation failures surface as
:class:`SpecValidationError`; no un-wrapped ``yaml.YAMLError``, ``KeyError``,
or ``TypeError`` leaks. Environment-variable interpolation, YAML
``include``/``import``, executable tags, implicit filesystem resolution, and
network access are not supported, and ``transform_ref`` is a plain reference
that is never imported or executed here.
"""

from __future__ import annotations

import yaml

from .encoding import DatasetError, encode_identity
from .models import SPEC_KIND_FEATURE, SPEC_KIND_LABEL, DatasetField, SpecPin
from .spec_models import (
    FEATURE_LABEL_SPEC_CONTENT_ID_VERSION,
    CrossTradingDayPolicy,
    FeatureSpec,
    LabelHorizon,
    LabelObservationWindow,
    LabelSpec,
    SpecParameter,
    SpecValidationError,
    SpecVersionRequirements,
)

__all__ = [
    "feature_label_spec_content_id",
    "feature_label_spec_pin",
    "load_feature_spec",
    "load_label_spec",
    "parse_feature_spec",
    "parse_label_spec",
]

#: YAML node tags accepted by the strict reader: plain YAML 1.1 scalars and
#: collections only. Timestamps, merge keys (``<<``), binary blobs, custom
#: tags (``!custom``), and Python tags (``!!python/...``) are rejected.
_SAFE_TAGS = frozenset(
    {
        "tag:yaml.org,2002:str",
        "tag:yaml.org,2002:int",
        "tag:yaml.org,2002:float",
        "tag:yaml.org,2002:bool",
        "tag:yaml.org,2002:null",
        "tag:yaml.org,2002:map",
        "tag:yaml.org,2002:seq",
    }
)

_UTF8_BOM = "﻿"

_FEATURE_TOP_LEVEL = (
    "spec_schema_version",
    "kind",
    "name",
    "version",
    "output",
    "inputs",
    "transform",
    "parameters",
    "requirements",
)
_LABEL_TOP_LEVEL = _FEATURE_TOP_LEVEL + (
    "observation_window",
    "horizon",
    "alignment_rule",
    "missing_data_policy",
    "cross_trading_day",
)
_OUTPUT_FIELDS = ("name", "logical_type", "nullable")
_INPUTS_FIELDS = ("canonical_fields",)
_TRANSFORM_FIELDS = ("ref",)
_REQUIREMENTS_FIELDS = ("canonical_schema_versions", "source_schema_versions")
_OBSERVATION_WINDOW_FIELDS = ("unit", "start_offset", "end_offset")
_HORIZON_FIELDS = ("unit", "value")
_CROSS_TRADING_DAY_FIELDS = ("allow", "boundary_rule")


# ---------------------------------------------------------------------------
# Strict YAML reading.
# ---------------------------------------------------------------------------


def _scan_events(text: str) -> None:
    """Reject anchors and aliases at the event level (they leave no trace on
    composed nodes in PyYAML 6)."""
    try:
        events = yaml.parse(text)
        for event in events:
            if isinstance(event, yaml.events.AliasEvent):
                raise SpecValidationError("YAML aliases are not allowed")
            if getattr(event, "anchor", None) is not None:
                raise SpecValidationError("YAML anchors are not allowed")
    except SpecValidationError:
        raise
    except yaml.YAMLError as exc:
        raise SpecValidationError(f"invalid YAML: {exc}") from exc


def _walk_strict(node, path: str, seen: set) -> None:
    """Reject aliases (shared node objects), unsupported tags, non-string
    mapping keys, and duplicate mapping keys at any depth."""
    if id(node) in seen:
        raise SpecValidationError(f"YAML alias at {path}")
    seen.add(id(node))
    if node.tag not in _SAFE_TAGS:
        raise SpecValidationError(f"unsupported YAML tag {node.tag!r} at {path}")
    if isinstance(node, yaml.nodes.ScalarNode):
        return
    if isinstance(node, yaml.nodes.SequenceNode):
        for index, child in enumerate(node.value):
            _walk_strict(child, f"{path}[{index}]", seen)
        return
    if isinstance(node, yaml.nodes.MappingNode):
        seen_keys: set[str] = set()
        for key_node, value_node in node.value:
            if (
                not isinstance(key_node, yaml.nodes.ScalarNode)
                or key_node.tag != "tag:yaml.org,2002:str"
            ):
                raise SpecValidationError(
                    f"mapping keys must be strings at {path}, got tag {key_node.tag!r}"
                )
            if key_node.value in seen_keys:
                raise SpecValidationError(
                    f"duplicate mapping key {key_node.value!r} at {path}"
                )
            seen_keys.add(key_node.value)
            _walk_strict(value_node, path, seen)
        return
    raise SpecValidationError(f"unsupported YAML node at {path}")


def _compose_strict(text: str):
    """Single-document composition; returns the root node or raises
    :class:`SpecValidationError`."""
    try:
        documents = list(yaml.compose_all(text))
    except yaml.YAMLError as exc:
        raise SpecValidationError(f"invalid YAML: {exc}") from exc
    if len(documents) != 1:
        raise SpecValidationError(
            f"spec must contain exactly one YAML document, got {len(documents)}"
        )
    node = documents[0]
    _walk_strict(node, "root", set())
    return node


def _parse_single_mapping(text: str) -> dict:
    """BOM-checked, strict, single-mapping YAML parse."""
    if not isinstance(text, str):
        raise SpecValidationError(
            f"spec text must be a string, got {type(text).__name__}"
        )
    if text.startswith(_UTF8_BOM):
        raise SpecValidationError("UTF-8 BOM is not accepted in spec text")
    if not text.strip():
        raise SpecValidationError("spec text must not be empty")
    _scan_events(text)
    node = _compose_strict(text)
    try:
        constructor = yaml.constructor.SafeConstructor()
        data = constructor.construct_document(node)
    except yaml.YAMLError as exc:
        raise SpecValidationError(f"invalid YAML: {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise SpecValidationError(f"invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecValidationError(
            f"spec root must be a mapping, got {type(data).__name__}"
        )
    return data


# ---------------------------------------------------------------------------
# Schema-driven field validation.
# ---------------------------------------------------------------------------


def _require_mapping(value, label: str) -> dict:
    if not isinstance(value, dict):
        raise SpecValidationError(f"{label} must be a mapping")
    return value


def _require_exact_fields(mapping: dict, allowed: tuple[str, ...], path: str) -> None:
    unknown = sorted(
        key if isinstance(key, str) else repr(key) for key in set(mapping) - set(allowed)
    )
    if unknown:
        raise SpecValidationError(
            f"unknown field(s) at {path}: {', '.join(unknown)}"
        )
    missing = sorted(set(allowed) - set(mapping))
    if missing:
        raise SpecValidationError(
            f"missing required field(s) at {path}: {', '.join(missing)}"
        )


def _build_output_field(name, logical_type, nullable) -> DatasetField:
    try:
        return DatasetField(name=name, logical_type=logical_type, nullable=nullable)
    except DatasetError as exc:
        raise SpecValidationError(str(exc)) from exc


def _require_string_list(value, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise SpecValidationError(f"{label} must be a list of strings")
    return tuple(value)


def _feature_spec_from_mapping(data: dict) -> FeatureSpec:
    _require_exact_fields(data, _FEATURE_TOP_LEVEL, "spec root")
    if data["kind"] != SPEC_KIND_FEATURE:
        raise SpecValidationError(
            f"kind must be {SPEC_KIND_FEATURE} for a feature spec, got {data['kind']!r}"
        )
    output = _require_mapping(data["output"], "output")
    _require_exact_fields(output, _OUTPUT_FIELDS, "output")
    inputs = _require_mapping(data["inputs"], "inputs")
    _require_exact_fields(inputs, _INPUTS_FIELDS, "inputs")
    transform = _require_mapping(data["transform"], "transform")
    _require_exact_fields(transform, _TRANSFORM_FIELDS, "transform")
    parameters = _require_mapping(data["parameters"], "parameters")
    for key in parameters:
        if not isinstance(key, str):
            raise SpecValidationError(
                f"parameter names must be strings, got {type(key).__name__}"
            )
    requirements = _require_mapping(data["requirements"], "requirements")
    _require_exact_fields(requirements, _REQUIREMENTS_FIELDS, "requirements")
    return FeatureSpec(
        spec_schema_version=data["spec_schema_version"],
        name=data["name"],
        version=data["version"],
        output=_build_output_field(
            output["name"], output["logical_type"], output["nullable"]
        ),
        input_canonical_fields=_require_string_list(
            inputs["canonical_fields"], "inputs.canonical_fields"
        ),
        transform_ref=transform["ref"],
        parameters=tuple(
            SpecParameter(name, value) for name, value in parameters.items()
        ),
        requirements=SpecVersionRequirements(
            _require_string_list(
                requirements["canonical_schema_versions"],
                "requirements.canonical_schema_versions",
            ),
            _require_string_list(
                requirements["source_schema_versions"],
                "requirements.source_schema_versions",
            ),
        ),
    )


def _label_spec_from_mapping(data: dict) -> LabelSpec:
    _require_exact_fields(data, _LABEL_TOP_LEVEL, "spec root")
    if data["kind"] != SPEC_KIND_LABEL:
        raise SpecValidationError(
            f"kind must be {SPEC_KIND_LABEL} for a label spec, got {data['kind']!r}"
        )
    output = _require_mapping(data["output"], "output")
    _require_exact_fields(output, _OUTPUT_FIELDS, "output")
    inputs = _require_mapping(data["inputs"], "inputs")
    _require_exact_fields(inputs, _INPUTS_FIELDS, "inputs")
    transform = _require_mapping(data["transform"], "transform")
    _require_exact_fields(transform, _TRANSFORM_FIELDS, "transform")
    parameters = _require_mapping(data["parameters"], "parameters")
    for key in parameters:
        if not isinstance(key, str):
            raise SpecValidationError(
                f"parameter names must be strings, got {type(key).__name__}"
            )
    requirements = _require_mapping(data["requirements"], "requirements")
    _require_exact_fields(requirements, _REQUIREMENTS_FIELDS, "requirements")
    window = _require_mapping(data["observation_window"], "observation_window")
    _require_exact_fields(window, _OBSERVATION_WINDOW_FIELDS, "observation_window")
    horizon = _require_mapping(data["horizon"], "horizon")
    _require_exact_fields(horizon, _HORIZON_FIELDS, "horizon")
    cross = _require_mapping(data["cross_trading_day"], "cross_trading_day")
    _require_exact_fields(cross, _CROSS_TRADING_DAY_FIELDS, "cross_trading_day")
    return LabelSpec(
        spec_schema_version=data["spec_schema_version"],
        name=data["name"],
        version=data["version"],
        output=_build_output_field(
            output["name"], output["logical_type"], output["nullable"]
        ),
        input_canonical_fields=_require_string_list(
            inputs["canonical_fields"], "inputs.canonical_fields"
        ),
        transform_ref=transform["ref"],
        parameters=tuple(
            SpecParameter(name, value) for name, value in parameters.items()
        ),
        requirements=SpecVersionRequirements(
            _require_string_list(
                requirements["canonical_schema_versions"],
                "requirements.canonical_schema_versions",
            ),
            _require_string_list(
                requirements["source_schema_versions"],
                "requirements.source_schema_versions",
            ),
        ),
        observation_window=LabelObservationWindow(
            window["unit"], window["start_offset"], window["end_offset"]
        ),
        horizon=LabelHorizon(horizon["unit"], horizon["value"]),
        alignment_rule=data["alignment_rule"],
        missing_data_policy=data["missing_data_policy"],
        cross_trading_day=CrossTradingDayPolicy(
            cross["allow"], cross["boundary_rule"]
        ),
    )


# ---------------------------------------------------------------------------
# Public parsing API.
# ---------------------------------------------------------------------------


def parse_feature_spec(text: str) -> FeatureSpec:
    """Parse one strict-YAML Feature spec document into a frozen
    :class:`FeatureSpec`."""
    data = _parse_single_mapping(text)
    try:
        return _feature_spec_from_mapping(data)
    except SpecValidationError:
        raise
    except (DatasetError, TypeError, ValueError) as exc:
        raise SpecValidationError(str(exc)) from exc


def parse_label_spec(text: str) -> LabelSpec:
    """Parse one strict-YAML Label spec document into a frozen
    :class:`LabelSpec`."""
    data = _parse_single_mapping(text)
    try:
        return _label_spec_from_mapping(data)
    except SpecValidationError:
        raise
    except (DatasetError, TypeError, ValueError) as exc:
        raise SpecValidationError(str(exc)) from exc


def load_feature_spec(path) -> FeatureSpec:
    """Load and parse a Feature spec file (strict UTF-8, no BOM). The file
    path never enters the spec identity."""
    return parse_feature_spec(_read_spec_file(path))


def load_label_spec(path) -> LabelSpec:
    """Load and parse a Label spec file (strict UTF-8, no BOM). The file
    path never enters the spec identity."""
    return parse_label_spec(_read_spec_file(path))


def _read_spec_file(path) -> str:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except UnicodeDecodeError as exc:
        raise SpecValidationError(
            f"spec file {path!r} is not valid UTF-8"
        ) from exc
    except OSError as exc:
        raise SpecValidationError(
            f"cannot read spec file {path!r}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Deterministic semantic content identity and SpecPin conversion.
# ---------------------------------------------------------------------------


def _input_fields(inputs: tuple[str, ...]) -> dict:
    """Arrays are encoded explicitly via count / index / value fields so no
    ambiguous string joins are needed."""
    fields = {"input_count": len(inputs)}
    for index, name in enumerate(inputs):
        fields[f"input_{index:04d}"] = name
    return fields


def _parameter_fields(parameters: tuple[SpecParameter, ...]) -> dict:
    fields = {"parameter_count": len(parameters)}
    for index, parameter in enumerate(parameters):
        fields[f"parameter_{index:04d}_name"] = parameter.name
        fields[f"parameter_{index:04d}_value"] = parameter.value
    return fields


def _requirements_fields(requirements: SpecVersionRequirements) -> dict:
    fields = {"canonical_schema_version_count": len(requirements.canonical_schema_versions)}
    for index, version in enumerate(requirements.canonical_schema_versions):
        fields[f"canonical_schema_version_{index:04d}"] = version
    fields["source_schema_version_count"] = len(requirements.source_schema_versions)
    for index, version in enumerate(requirements.source_schema_versions):
        fields[f"source_schema_version_{index:04d}"] = version
    return fields


def _common_fields(spec) -> dict:
    fields = {
        "version": FEATURE_LABEL_SPEC_CONTENT_ID_VERSION,
        "kind": spec.kind,
        "spec_schema_version": spec.spec_schema_version,
        "name": spec.name,
        "spec_version": spec.version,
        "output_name": spec.output.name,
        "output_logical_type": spec.output.logical_type,
        "output_nullable": spec.output.nullable,
        "transform_ref": spec.transform_ref,
    }
    fields.update(_input_fields(spec.input_canonical_fields))
    fields.update(_parameter_fields(spec.parameters))
    fields.update(_requirements_fields(spec.requirements))
    return fields


def _label_fields(spec: LabelSpec) -> dict:
    fields = _common_fields(spec)
    fields.update(
        {
            "observation_window_unit": spec.observation_window.unit,
            "observation_window_start_offset": spec.observation_window.start_offset,
            "observation_window_end_offset": spec.observation_window.end_offset,
            "horizon_unit": spec.horizon.unit,
            "horizon_value": spec.horizon.value,
            "alignment_rule": spec.alignment_rule,
            "missing_data_policy": spec.missing_data_policy,
            "cross_trading_day_allow": spec.cross_trading_day.allow,
            "cross_trading_day_boundary_rule": spec.cross_trading_day.boundary_rule,
        }
    )
    return fields


def feature_label_spec_content_id(spec) -> str:
    """64-character lowercase SHA-256 of the deterministic semantic content
    of a Feature or Label spec.

    The typed model is expanded into a flat mapping of scalar values and
    passed to the existing versioned identity encoding
    (:func:`market_vault.dataset.encoding.encode_identity`); no new or
    unversioned hashing scheme is introduced. The ID contains the content-ID
    version, the spec kind and schema version, and every semantic field; it
    never contains file paths, mtimes, YAML comments, key order, blank lines,
    newline style, local timezone, Python ``repr()``, or dict insertion
    order.
    """
    if isinstance(spec, FeatureSpec):
        fields = _common_fields(spec)
    elif isinstance(spec, LabelSpec):
        fields = _label_fields(spec)
    else:
        raise SpecValidationError(
            f"feature_label_spec_content_id requires a FeatureSpec or LabelSpec, "
            f"got {type(spec).__name__}"
        )
    try:
        return encode_identity(FEATURE_LABEL_SPEC_CONTENT_ID_VERSION, fields)
    except DatasetError as exc:
        raise SpecValidationError(str(exc)) from exc


def feature_label_spec_pin(spec) -> SpecPin:
    """Convert a Feature or Label spec to the existing :class:`SpecPin`
    (kind FEATURE for FeatureSpec, LABEL for LabelSpec) using its semantic
    content ID. No new pin model is introduced and no ImplementationPin is
    ever fabricated: the actual transform implementation stays a separate
    future binding."""
    if not isinstance(spec, (FeatureSpec, LabelSpec)):
        raise SpecValidationError(
            f"feature_label_spec_pin requires a FeatureSpec or LabelSpec, "
            f"got {type(spec).__name__}"
        )
    return SpecPin(
        kind=spec.kind,
        name=spec.name,
        version=spec.version,
        content_sha256=feature_label_spec_content_id(spec),
    )
