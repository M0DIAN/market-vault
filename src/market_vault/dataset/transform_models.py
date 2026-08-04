"""Frozen typed models of the Transform Implementation Registry contract
(v0.5.0 PR-2).

The explicit immutable Transform Implementation Registry is the sole
resolution authority for the existing v1 ``transform_ref`` values
(``module.path:function``). This module defines the frozen, strictly
validated, deterministically normalized registration models:

- :class:`TransformParameterContract` — one typed, validated parameter
  contract (bool / int64 / float64 / string, explicit nullability, optional
  numeric bounds, optional allowed values; v1 provides no implicit runtime
  defaults);
- :class:`TransformWindowRequirement` — one typed, version-stable lookback /
  lookforward requirement (source NONE / FIXED / PARAMETER /
  LABEL_OBSERVATION_WINDOW / LABEL_HORIZON, unit NONE / BARS / MINUTES,
  fixed value or parameter name, and the inclusive/exclusive boundary
  semantics);
- :class:`TransformRegistration` — one immutable registration of a
  module-level implementation under its exact ``transform_ref``;
- :class:`ResolvedTransform` — the result of one successful spec resolution;
- the versioned deterministic implementation fingerprint
  (:func:`transform_implementation_fingerprint`) and its conversion to the
  existing :class:`ImplementationPin`
  (:func:`transform_implementation_pin`).

Every model is frozen and validates at construction (fail closed); all
failures raise the unified :class:`TransformRegistryError` (a subclass of
:class:`DatasetError`). No ``transform_ref`` is ever imported, no
implementation callable is ever executed, no Feature or Label value is
computed, and nothing touches OpenD or the network. The only filesystem
access is reading the implementation module's own stable source file for
the fingerprint (via ``inspect``), and even then the fingerprint never
contains absolute paths, checkout directories, filesystem mtimes, memory
addresses, ``repr()``, import order, registry insertion order, or local
newline styles. The fingerprint is a construction-time snapshot: later
edits of the module source file do not change an already-constructed
registration.
"""

from __future__ import annotations

import hashlib
import inspect
import numbers
import re
import sys
import types
from dataclasses import dataclass, field
from typing import Callable

from .encoding import DatasetError, encode_identity, normalize_nfc, reject_unsafe_text
from .models import (
    SPEC_KIND_FEATURE,
    SPEC_KIND_LABEL,
    SUPPORTED_LOGICAL_TYPES,
    ImplementationPin,
)
from .spec_models import FeatureSpec, LabelSpec, SpecParameter

__all__ = [
    "BOUNDARY_POLICY_NO_CROSS_TRADING_DAY",
    "BOUNDARY_POLICY_PIT_WINDOW_ONLY",
    "BOUNDARY_POLICY_SAME_MARKET_CALENDAR_DATE",
    "MISSING_POLICY_EXCLUDE_SAMPLE",
    "MISSING_POLICY_FAIL",
    "MISSING_POLICY_LABEL_INCOMPLETE",
    "PARAMETER_TYPE_BOOL",
    "PARAMETER_TYPE_FLOAT64",
    "PARAMETER_TYPE_INT64",
    "PARAMETER_TYPE_STRING",
    "TRANSFORM_IMPLEMENTATION_FINGERPRINT_VERSION",
    "TRANSFORM_REGISTRY_CONTRACT_VERSION",
    "ResolvedTransform",
    "TransformParameterContract",
    "TransformRegistration",
    "TransformRegistryError",
    "TransformWindowRequirement",
    "WINDOW_BOUNDARY_EXCLUSIVE",
    "WINDOW_BOUNDARY_INCLUSIVE",
    "WINDOW_SOURCE_FIXED",
    "WINDOW_SOURCE_LABEL_HORIZON",
    "WINDOW_SOURCE_LABEL_OBSERVATION_WINDOW",
    "WINDOW_SOURCE_NONE",
    "WINDOW_SOURCE_PARAMETER",
    "WINDOW_UNIT_BARS",
    "WINDOW_UNIT_MINUTES",
    "WINDOW_UNIT_NONE",
    "transform_implementation_fingerprint",
    "transform_implementation_pin",
]


class TransformRegistryError(DatasetError):
    """Structured fail-closed failure of the transform registry layer.

    Raised for invalid registrations, invalid callables, unsupported spec
    combinations, preflight violations, and fingerprint failures. No bare
    ``KeyError``, ``TypeError``, ``ValueError``, or ``inspect`` exception
    ever leaks past this boundary.
    """


#: Version of the explicit immutable registry contract itself. It never
#: enters ``dataset_id`` directly; the registry's ``ImplementationPin``
#: entries are the only identity-bearing artifacts.
TRANSFORM_REGISTRY_CONTRACT_VERSION = "market-vault-transform-registry-v1"

#: Version of the deterministic implementation fingerprint payload contract.
#: The value is part of every fingerprint payload; changing it changes every
#: implementation fingerprint and every ``ImplementationPin``.
TRANSFORM_IMPLEMENTATION_FINGERPRINT_VERSION = (
    "market-vault-transform-implementation-fingerprint-v1"
)

#: Parameter value types; they reuse the canonical scalar names of the
#: existing logical-type set so a parameter contract can be compared with a
#: spec output directly.
PARAMETER_TYPE_BOOL = "bool"
PARAMETER_TYPE_INT64 = "int64"
PARAMETER_TYPE_FLOAT64 = "float64"
PARAMETER_TYPE_STRING = "string"
_PARAMETER_TYPES = (
    PARAMETER_TYPE_BOOL,
    PARAMETER_TYPE_INT64,
    PARAMETER_TYPE_FLOAT64,
    PARAMETER_TYPE_STRING,
)

#: Window requirement sources.
WINDOW_SOURCE_NONE = "NONE"
WINDOW_SOURCE_FIXED = "FIXED"
WINDOW_SOURCE_PARAMETER = "PARAMETER"
WINDOW_SOURCE_LABEL_OBSERVATION_WINDOW = "LABEL_OBSERVATION_WINDOW"
WINDOW_SOURCE_LABEL_HORIZON = "LABEL_HORIZON"
_WINDOW_SOURCES = (
    WINDOW_SOURCE_NONE,
    WINDOW_SOURCE_FIXED,
    WINDOW_SOURCE_PARAMETER,
    WINDOW_SOURCE_LABEL_OBSERVATION_WINDOW,
    WINDOW_SOURCE_LABEL_HORIZON,
)

#: Window requirement units. TRADING_DAYS is not part of the v0.5 execution
#: scope and has no constant: a TRADING_DAYS label fails closed at preflight.
WINDOW_UNIT_NONE = "NONE"
WINDOW_UNIT_BARS = "BARS"
WINDOW_UNIT_MINUTES = "MINUTES"
_WINDOW_UNITS = (WINDOW_UNIT_NONE, WINDOW_UNIT_BARS, WINDOW_UNIT_MINUTES)

#: Window boundary semantics: whether the bar at the window's outer edge is
#: part of the window (INCLUSIVE) or excluded (EXCLUSIVE). Recorded for the
#: future executor; no window is ever computed by this layer.
WINDOW_BOUNDARY_INCLUSIVE = "INCLUSIVE"
WINDOW_BOUNDARY_EXCLUSIVE = "EXCLUSIVE"
_WINDOW_BOUNDARIES = (WINDOW_BOUNDARY_INCLUSIVE, WINDOW_BOUNDARY_EXCLUSIVE)

#: Session / trading-day boundary policies.
BOUNDARY_POLICY_PIT_WINDOW_ONLY = "PIT_WINDOW_ONLY"
BOUNDARY_POLICY_SAME_MARKET_CALENDAR_DATE = "SAME_MARKET_CALENDAR_DATE"
BOUNDARY_POLICY_NO_CROSS_TRADING_DAY = "NO_CROSS_TRADING_DAY"
_BOUNDARY_POLICIES = (
    BOUNDARY_POLICY_PIT_WINDOW_ONLY,
    BOUNDARY_POLICY_SAME_MARKET_CALENDAR_DATE,
    BOUNDARY_POLICY_NO_CROSS_TRADING_DAY,
)

#: Missing / incomplete-data policies.
MISSING_POLICY_FAIL = "FAIL"
MISSING_POLICY_EXCLUDE_SAMPLE = "EXCLUDE_SAMPLE"
MISSING_POLICY_LABEL_INCOMPLETE = "LABEL_INCOMPLETE"
_MISSING_POLICIES = (
    MISSING_POLICY_FAIL,
    MISSING_POLICY_EXCLUDE_SAMPLE,
    MISSING_POLICY_LABEL_INCOMPLETE,
)

#: Signed int64 range (mirrors the spec parameter contract).
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1

#: v1 transform_ref shape; mirrors the FeatureSpec/LabelSpec v1 pattern
#: (``module.path:function``). The exact key identity is additionally
#: enforced by ``transform_ref == implementation.__module__ + ":" +
#: implementation.__name__``.
_TRANSFORM_REF_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*$"
)

def _reject_unsafe_text(value: str, label: str) -> None:
    """Safe-text rejection that always surfaces as TransformRegistryError."""
    try:
        reject_unsafe_text(value, label)
    except DatasetError as exc:
        raise TransformRegistryError(str(exc)) from exc


def _require_safe_text(value, label: str) -> str:
    """Non-empty NFC-normalized safe string without leading/trailing
    whitespace; identity-bearing and never silently changed."""
    if not isinstance(value, str):
        raise TransformRegistryError(
            f"{label} must be a string, got {type(value).__name__}"
        )
    text = normalize_nfc(value)
    if not text or not text.strip():
        raise TransformRegistryError(f"{label} must not be empty")
    if text != text.strip():
        raise TransformRegistryError(
            f"{label} must not have leading or trailing whitespace"
        )
    _reject_unsafe_text(text, label)
    return text


def _require_bool(value, label: str) -> bool:
    """Real bool; int is never accepted in a bool position."""
    if type(value) is not bool:
        raise TransformRegistryError(f"{label} must be a real bool")
    return value


def _require_transform_ref(value) -> str:
    """Exact v1 ``module.path:function`` transform_ref shape; never imported,
    never alias-resolved, never case-folded."""
    if not isinstance(value, str):
        raise TransformRegistryError(
            f"transform_ref must be a string, got {type(value).__name__}"
        )
    text = normalize_nfc(value)
    if not _TRANSFORM_REF_RE.fullmatch(text):
        raise TransformRegistryError(
            f"transform_ref must match module.path:function, got {value!r}"
        )
    return text


def _normalize_input_fields(values) -> tuple[str, ...]:
    """Non-empty unique input canonical fields; order is authoritative
    semantics and preserved exactly (never sorted)."""
    if isinstance(values, (str, bytes)):
        raise TransformRegistryError(
            "input_canonical_fields must be an iterable of strings"
        )
    try:
        items = tuple(values)
    except TypeError as exc:
        raise TransformRegistryError(
            "input_canonical_fields must be an iterable of strings"
        ) from exc
    if not items:
        raise TransformRegistryError("input_canonical_fields must not be empty")
    normalized: list[str] = []
    for item in items:
        if not isinstance(item, str):
            raise TransformRegistryError(
                f"input canonical fields must be strings, got {type(item).__name__}"
            )
        text = normalize_nfc(item)
        if not text or not text.strip():
            raise TransformRegistryError(
                "input canonical field names must not be empty"
            )
        if text != text.strip():
            raise TransformRegistryError(
                "input canonical field names must not have leading or trailing "
                "whitespace"
            )
        _reject_unsafe_text(text, "input canonical field name")
        normalized.append(text)
    if len(set(normalized)) != len(normalized):
        raise TransformRegistryError(
            "input_canonical_fields must not contain duplicates"
        )
    return tuple(normalized)


def _normalize_versions(values, label: str) -> tuple[str, ...]:
    """Non-empty unique safe version strings; order is not semantic and is
    deterministically sorted."""
    if isinstance(values, (str, bytes)):
        raise TransformRegistryError(f"{label} must be an iterable of strings")
    try:
        items = tuple(values)
    except TypeError as exc:
        raise TransformRegistryError(f"{label} must be an iterable of strings") from exc
    if not items:
        raise TransformRegistryError(f"{label} must not be empty")
    normalized: list[str] = []
    for item in items:
        text = _require_safe_text(item, f"{label} entry")
        normalized.append(text)
    if len(set(normalized)) != len(normalized):
        raise TransformRegistryError(f"{label} must not contain duplicates")
    return tuple(sorted(normalized))


def _normalize_numeric_bound(value, label: str) -> int | float:
    """Real int or finite float bound; bool, NaN, and infinities fail;
    negative zero normalizes to ordinary zero."""
    if type(value) is bool or not isinstance(value, numbers.Real):
        raise TransformRegistryError(
            f"{label} must be a real number, got {type(value).__name__}"
        )
    if isinstance(value, numbers.Integral):
        integer = int(value)
        if not _INT64_MIN <= integer <= _INT64_MAX:
            raise TransformRegistryError(
                f"{label} must be within signed int64 range, got {integer}"
            )
        return integer
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise TransformRegistryError(
            f"{label} NaN and positive/negative infinity are rejected, got {number!r}"
        )
    return 0.0 if number == 0.0 else number


def _normalize_allowed_value(value, value_type: str, label: str):
    """One allowed scalar value of exactly the contract's value type."""
    if value_type == PARAMETER_TYPE_BOOL:
        if type(value) is not bool:
            raise TransformRegistryError(
                f"{label} allowed values must be real bools for a bool contract, "
                f"got {type(value).__name__}"
            )
        return value
    if value_type == PARAMETER_TYPE_INT64:
        if type(value) is bool or not isinstance(value, numbers.Integral):
            raise TransformRegistryError(
                f"{label} allowed values must be real int64 integers for an "
                f"int64 contract, got {type(value).__name__}"
            )
        integer = int(value)
        if not _INT64_MIN <= integer <= _INT64_MAX:
            raise TransformRegistryError(
                f"{label} allowed values must be within signed int64 range, "
                f"got {integer}"
            )
        return integer
    if value_type == PARAMETER_TYPE_FLOAT64:
        if type(value) is bool or not isinstance(value, numbers.Real):
            raise TransformRegistryError(
                f"{label} allowed values must be finite float64 numbers for a "
                f"float64 contract, got {type(value).__name__}"
            )
        if isinstance(value, numbers.Integral):
            number = float(int(value))
        else:
            number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            raise TransformRegistryError(
                f"{label} allowed values must be finite; NaN and infinities "
                f"are rejected, got {number!r}"
            )
        return 0.0 if number == 0.0 else number
    text = _require_safe_text(value, f"{label} allowed value")
    return text


def _normalize_allowed_values(values, value_type: str, label: str) -> tuple[object, ...]:
    """None or a non-empty tuple of unique allowed scalar values,
    deterministically sorted; duplicates fail closed (never silently
    deduplicated)."""
    if values is None:
        return ()
    if isinstance(values, (str, bytes)):
        raise TransformRegistryError(
            f"{label} must be an iterable of scalars or None"
        )
    try:
        items = tuple(values)
    except TypeError as exc:
        raise TransformRegistryError(
            f"{label} must be an iterable of scalars or None"
        ) from exc
    if not items:
        raise TransformRegistryError(f"{label} must be non-empty when provided")
    normalized = [_normalize_allowed_value(item, value_type, label) for item in items]
    if len(set(normalized)) != len(normalized):
        raise TransformRegistryError(f"{label} must not contain duplicates")
    return tuple(sorted(normalized))


@dataclass(frozen=True)
class TransformParameterContract:
    """One typed parameter contract of a transform registration.

    The contract declares the exact value type (bool / int64 / float64 /
    string, using the canonical scalar names), explicit nullability (a null
    is allowed only when ``nullable`` is true), optional numeric bounds
    (numeric contracts only; bounds are inclusive), and optional allowed
    scalar values (deterministically sorted; duplicates fail). The v1
    registry provides no implicit runtime defaults: every behavior-affecting
    parameter must exist explicitly in the FeatureSpec / LabelSpec, and the
    spec parameter set must match the registration schema exactly.
    """

    name: str
    value_type: str
    nullable: bool
    lower_bound: int | float | None = None
    upper_bound: int | float | None = None
    allowed_values: tuple[object, ...] | None = None

    def __post_init__(self) -> None:
        name = _require_safe_text(self.name, "parameter contract name")
        if self.value_type not in _PARAMETER_TYPES:
            raise TransformRegistryError(
                f"parameter {name!r} value_type must be one of "
                f"{', '.join(_PARAMETER_TYPES)}, got {self.value_type!r}"
            )
        nullable = _require_bool(self.nullable, f"parameter {name!r} nullable")
        lower = self.lower_bound
        upper = self.upper_bound
        if self.value_type not in (PARAMETER_TYPE_INT64, PARAMETER_TYPE_FLOAT64):
            if lower is not None or upper is not None:
                raise TransformRegistryError(
                    f"parameter {name!r} numeric bounds are only allowed on "
                    "int64 or float64 contracts"
                )
        else:
            if lower is not None:
                lower = _normalize_numeric_bound(
                    lower, f"parameter {name!r} lower_bound"
                )
            if upper is not None:
                upper = _normalize_numeric_bound(
                    upper, f"parameter {name!r} upper_bound"
                )
            if lower is not None and upper is not None and lower > upper:
                raise TransformRegistryError(
                    f"parameter {name!r} lower_bound must not exceed upper_bound, "
                    f"got {lower} > {upper}"
                )
        allowed = _normalize_allowed_values(
            self.allowed_values, self.value_type, f"parameter {name!r}"
        )
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "value_type", self.value_type)
        object.__setattr__(self, "nullable", nullable)
        object.__setattr__(self, "lower_bound", lower)
        object.__setattr__(self, "upper_bound", upper)
        object.__setattr__(
            self, "allowed_values", tuple(allowed) if allowed else None
        )


@dataclass(frozen=True)
class TransformWindowRequirement:
    """One typed, version-stable lookback or lookforward requirement.

    ``source`` is NONE (no requirement), FIXED (a positive integer in
    ``unit``), PARAMETER (the declared int64 parameter named by
    ``parameter_name``), or, for a Label lookforward only,
    LABEL_OBSERVATION_WINDOW / LABEL_HORIZON (the LabelSpec's own declared
    window / horizon, whose unit must match ``unit``). ``unit`` is NONE /
    BARS / MINUTES; TRADING_DAYS is not part of the v0.5 execution scope.
    ``boundary`` records whether the window edge bar is INCLUSIVE (default)
    or EXCLUSIVE. This layer only records and preflights the requirement;
    no window is ever computed and no PIT row is ever read.
    """

    source: str
    unit: str
    value: int | None = None
    parameter_name: str | None = None
    boundary: str = WINDOW_BOUNDARY_INCLUSIVE

    def __post_init__(self) -> None:
        if self.source not in _WINDOW_SOURCES:
            raise TransformRegistryError(
                f"window requirement source must be one of {', '.join(_WINDOW_SOURCES)}, "
                f"got {self.source!r}"
            )
        if self.unit not in _WINDOW_UNITS:
            raise TransformRegistryError(
                f"window requirement unit must be one of {', '.join(_WINDOW_UNITS)}, "
                f"got {self.unit!r}; TRADING_DAYS is unsupported in the v0.5 "
                "execution scope"
            )
        if self.boundary not in _WINDOW_BOUNDARIES:
            raise TransformRegistryError(
                f"window requirement boundary must be one of "
                f"{', '.join(_WINDOW_BOUNDARIES)}, got {self.boundary!r}"
            )
        if self.source == WINDOW_SOURCE_NONE:
            if self.unit != WINDOW_UNIT_NONE:
                raise TransformRegistryError(
                    "a NONE window requirement must use unit NONE"
                )
            if self.value is not None or self.parameter_name is not None:
                raise TransformRegistryError(
                    "a NONE window requirement must not carry a value or "
                    "parameter name"
                )
            return
        if self.unit == WINDOW_UNIT_NONE:
            raise TransformRegistryError(
                "a non-NONE window requirement must use unit BARS or MINUTES"
            )
        if self.source == WINDOW_SOURCE_FIXED:
            if type(self.value) is bool or not isinstance(self.value, numbers.Integral):
                raise TransformRegistryError(
                    "a FIXED window requirement must carry a real positive "
                    "integer value"
                )
            value = int(self.value)
            if value <= 0:
                raise TransformRegistryError(
                    f"a FIXED window requirement value must be a positive "
                    f"integer, got {value}"
                )
            if self.parameter_name is not None:
                raise TransformRegistryError(
                    "a FIXED window requirement must not carry a parameter name"
                )
            object.__setattr__(self, "value", value)
            return
        if self.source == WINDOW_SOURCE_PARAMETER:
            if self.value is not None:
                raise TransformRegistryError(
                    "a PARAMETER window requirement must not carry a fixed value"
                )
            parameter_name = _require_safe_text(
                self.parameter_name, "PARAMETER window requirement parameter name"
            )
            object.__setattr__(self, "parameter_name", parameter_name)
            return
        # LABEL_OBSERVATION_WINDOW / LABEL_HORIZON: the value comes from the
        # LabelSpec at preflight; the declared unit must match the spec.
        if self.value is not None or self.parameter_name is not None:
            raise TransformRegistryError(
                f"a {self.source} window requirement must not carry a value or "
                "parameter name; it derives from the LabelSpec"
            )


@dataclass(frozen=True)
class TransformRegistration:
    """One immutable registration of a module-level implementation under its
    exact v1 ``transform_ref`` (``module.path:function``).

    ``kind`` reuses ``SPEC_KIND_FEATURE`` / ``SPEC_KIND_LABEL`` and must
    equal ``spec.kind`` at resolution. The output contract is structural:
    one output field (``output_arity`` is fixed to 1 by the v1 contract —
    one spec, one output ``DatasetField``, whose name comes from
    ``spec.output.name``, never from the registration), the allowed
    ``output_logical_type``, and the ``output_nullable`` requirement.
    ``input_canonical_fields`` order is authoritative and must match the
    spec exactly. ``parameters`` are sorted by name with duplicates failing
    closed; supported schema versions are sorted (order is not semantic).
    The session / trading-day ``boundary_policy`` and the ``missing_policy``
    use fixed constants; a FEATURE registration never carries
    ``MISSING_POLICY_LABEL_INCOMPLETE`` and never uses a non-NONE lookforward
    or a Label-derived window source.

    ``implementation_fingerprint`` is computed once at construction from the
    normalized module source and the full registration metadata (see
    :func:`transform_implementation_fingerprint`); the registration is then
    frozen with that snapshot. The implementation callable is never executed.
    """

    transform_ref: str
    kind: str
    implementation_version: str
    implementation: Callable[..., object]
    input_canonical_fields: tuple[str, ...]
    supported_canonical_schema_versions: tuple[str, ...]
    supported_source_schema_versions: tuple[str, ...]
    output_logical_type: str
    output_nullable: bool
    parameters: tuple[TransformParameterContract, ...]
    lookback: TransformWindowRequirement
    lookforward: TransformWindowRequirement
    boundary_policy: str
    missing_policy: str
    display_name: str | None = None
    output_arity: int = field(default=1, init=False)
    implementation_fingerprint: str = field(default="", init=False)

    def __post_init__(self) -> None:
        transform_ref = _require_transform_ref(self.transform_ref)
        if self.kind not in (SPEC_KIND_FEATURE, SPEC_KIND_LABEL):
            raise TransformRegistryError(
                f"registration kind must be {SPEC_KIND_FEATURE} or "
                f"{SPEC_KIND_LABEL}, got {self.kind!r}"
            )
        implementation_version = _require_safe_text(
            self.implementation_version, "implementation version"
        )
        source_sha256 = _module_source_sha256(self.implementation, transform_ref)
        inputs = _normalize_input_fields(self.input_canonical_fields)
        canonical_versions = _normalize_versions(
            self.supported_canonical_schema_versions,
            "supported_canonical_schema_versions",
        )
        source_versions = _normalize_versions(
            self.supported_source_schema_versions,
            "supported_source_schema_versions",
        )
        if self.output_logical_type not in SUPPORTED_LOGICAL_TYPES:
            raise TransformRegistryError(
                f"output_logical_type must be one of "
                f"{', '.join(SUPPORTED_LOGICAL_TYPES)}, got {self.output_logical_type!r}"
            )
        output_nullable = _require_bool(self.output_nullable, "output_nullable")
        parameters = _normalize_parameter_contracts(self.parameters)
        lookback = _require_instance(
            self.lookback, TransformWindowRequirement, "lookback"
        )
        lookforward = _require_instance(
            self.lookforward, TransformWindowRequirement, "lookforward"
        )
        if self.boundary_policy not in _BOUNDARY_POLICIES:
            raise TransformRegistryError(
                f"boundary_policy must be one of {', '.join(_BOUNDARY_POLICIES)}, "
                f"got {self.boundary_policy!r}"
            )
        if self.missing_policy not in _MISSING_POLICIES:
            raise TransformRegistryError(
                f"missing_policy must be one of {', '.join(_MISSING_POLICIES)}, "
                f"got {self.missing_policy!r}"
            )
        if self.kind == SPEC_KIND_FEATURE and self.missing_policy == MISSING_POLICY_LABEL_INCOMPLETE:
            raise TransformRegistryError(
                "a FEATURE registration must not use the LABEL_INCOMPLETE "
                "missing policy"
            )
        _validate_window_cross_references(transform_ref, self.kind, lookback, lookforward, parameters)
        display_name = self.display_name
        if display_name is not None:
            display_name = _require_safe_text(display_name, "display name")
        fingerprint = _implementation_fingerprint(
            transform_ref=transform_ref,
            kind=self.kind,
            implementation_version=implementation_version,
            display_name=display_name,
            source_sha256=source_sha256,
            inputs=inputs,
            canonical_versions=canonical_versions,
            source_versions=source_versions,
            output_arity=1,
            output_logical_type=self.output_logical_type,
            output_nullable=output_nullable,
            parameters=parameters,
            lookback=lookback,
            lookforward=lookforward,
            boundary_policy=self.boundary_policy,
            missing_policy=self.missing_policy,
        )
        object.__setattr__(self, "transform_ref", transform_ref)
        object.__setattr__(self, "kind", self.kind)
        object.__setattr__(self, "implementation_version", implementation_version)
        object.__setattr__(self, "input_canonical_fields", inputs)
        object.__setattr__(
            self, "supported_canonical_schema_versions", canonical_versions
        )
        object.__setattr__(self, "supported_source_schema_versions", source_versions)
        object.__setattr__(self, "output_logical_type", self.output_logical_type)
        object.__setattr__(self, "output_nullable", output_nullable)
        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(self, "lookback", lookback)
        object.__setattr__(self, "lookforward", lookforward)
        object.__setattr__(self, "boundary_policy", self.boundary_policy)
        object.__setattr__(self, "missing_policy", self.missing_policy)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "implementation_fingerprint", fingerprint)


@dataclass(frozen=True)
class ResolvedTransform:
    """The result of one successful registry resolution.

    Carries the original frozen spec (never mutated), the immutable
    registration, the spec's own validated parameters in stable name order
    (the v1 registry provides no implicit defaults, so the values are
    exactly the spec's), and the generated :class:`ImplementationPin`.
    Construction is strictly validated (fail closed): the spec must be a
    FeatureSpec or LabelSpec, the registration must match the spec kind and
    ``transform_ref``, the parameters must equal the spec's own parameters
    exactly, and the pin must be exactly
    ``transform_implementation_pin(registration)``. Resolution never
    executes the transform.
    """

    spec: FeatureSpec | LabelSpec
    registration: TransformRegistration
    parameters: tuple[SpecParameter, ...]
    pin: ImplementationPin

    def __post_init__(self) -> None:
        if isinstance(self.spec, FeatureSpec):
            kind = SPEC_KIND_FEATURE
        elif isinstance(self.spec, LabelSpec):
            kind = SPEC_KIND_LABEL
        else:
            raise TransformRegistryError(
                "ResolvedTransform spec must be a FeatureSpec or LabelSpec, "
                f"got {type(self.spec).__name__}"
            )
        if not isinstance(self.registration, TransformRegistration):
            raise TransformRegistryError(
                "ResolvedTransform registration must be a "
                f"TransformRegistration, got {type(self.registration).__name__}"
            )
        if not isinstance(self.parameters, tuple) or not all(
            isinstance(parameter, SpecParameter) for parameter in self.parameters
        ):
            raise TransformRegistryError(
                "ResolvedTransform parameters must be a tuple of SpecParameter"
            )
        if tuple(self.parameters) != self.spec.parameters:
            raise TransformRegistryError(
                "ResolvedTransform parameters must equal the spec parameters "
                "exactly"
            )
        if self.registration.kind != kind:
            raise TransformRegistryError(
                f"ResolvedTransform registration kind {self.registration.kind!r} "
                f"must match the spec kind {kind!r}"
            )
        if self.registration.transform_ref != self.spec.transform_ref:
            raise TransformRegistryError(
                f"ResolvedTransform registration transform_ref "
                f"{self.registration.transform_ref!r} must match the spec "
                f"transform_ref {self.spec.transform_ref!r}"
            )
        if not isinstance(self.pin, ImplementationPin):
            raise TransformRegistryError(
                "ResolvedTransform pin must be an ImplementationPin, "
                f"got {type(self.pin).__name__}"
            )
        if self.pin != transform_implementation_pin(self.registration):
            raise TransformRegistryError(
                "ResolvedTransform pin must equal "
                "transform_implementation_pin(registration)"
            )


# ---------------------------------------------------------------------------
# Callable restrictions and canonical source normalization.
# ---------------------------------------------------------------------------


def _require_instance(value, cls: type, label: str):
    if not isinstance(value, cls):
        raise TransformRegistryError(
            f"{label} must be a {cls.__name__}, got {type(value).__name__}"
        )
    return value


def _normalize_parameter_contracts(
    values,
) -> tuple[TransformParameterContract, ...]:
    """Parameter contracts deterministically sorted by name; duplicates fail
    closed even when byte-identical."""
    if isinstance(values, (str, bytes)):
        raise TransformRegistryError(
            "parameters must be an iterable of TransformParameterContract"
        )
    try:
        items = tuple(values)
    except TypeError as exc:
        raise TransformRegistryError(
            "parameters must be an iterable of TransformParameterContract"
        ) from exc
    for item in items:
        _require_instance(item, TransformParameterContract, "parameter")
    items = tuple(sorted(items, key=lambda item: item.name))
    for previous, current in zip(items, items[1:]):
        if previous.name == current.name:
            raise TransformRegistryError(
                f"duplicate parameter contract name {current.name!r}"
            )
    return items


def _validate_window_cross_references(
    transform_ref: str,
    kind: str,
    lookback: TransformWindowRequirement,
    lookforward: TransformWindowRequirement,
    parameters: tuple[TransformParameterContract, ...],
) -> None:
    """Registration-internal window rules (no spec is involved here)."""
    label_sources = (
        WINDOW_SOURCE_LABEL_OBSERVATION_WINDOW,
        WINDOW_SOURCE_LABEL_HORIZON,
    )
    if lookback.source in label_sources:
        raise TransformRegistryError(
            f"registration {transform_ref!r} lookback must not derive from "
            "LABEL_OBSERVATION_WINDOW or LABEL_HORIZON"
        )
    if lookforward.source in label_sources and kind != SPEC_KIND_LABEL:
        raise TransformRegistryError(
            f"registration {transform_ref!r} lookforward may only derive from "
            "LABEL_OBSERVATION_WINDOW / LABEL_HORIZON on a LABEL registration"
        )
    if kind == SPEC_KIND_FEATURE and lookforward.source != WINDOW_SOURCE_NONE:
        raise TransformRegistryError(
            f"FEATURE registration {transform_ref!r} lookforward must be NONE"
        )
    schema = {contract.name: contract for contract in parameters}
    for requirement in (lookback, lookforward):
        if requirement.source != WINDOW_SOURCE_PARAMETER:
            continue
        contract = schema.get(requirement.parameter_name)
        if contract is None:
            raise TransformRegistryError(
                f"registration {transform_ref!r} window requirement references "
                f"parameter {requirement.parameter_name!r}, which is not "
                "declared in the parameter schema"
            )
        if contract.value_type != PARAMETER_TYPE_INT64:
            raise TransformRegistryError(
                f"registration {transform_ref!r} window requirement parameter "
                f"{requirement.parameter_name!r} must be an int64 parameter, "
                f"got {contract.value_type!r}"
            )
        if contract.nullable:
            raise TransformRegistryError(
                f"registration {transform_ref!r} window requirement parameter "
                f"{requirement.parameter_name!r} must not be nullable"
            )
        # A window size is a positive integer: the referenced contract must
        # declare a lower bound of at least 1, any upper bound must respect
        # it, and any allowed values must all be positive real ints.
        if contract.lower_bound is None:
            raise TransformRegistryError(
                f"registration {transform_ref!r} window requirement parameter "
                f"{requirement.parameter_name!r} must declare a numeric "
                "lower_bound"
            )
        if contract.lower_bound < 1:
            raise TransformRegistryError(
                f"registration {transform_ref!r} window requirement parameter "
                f"{requirement.parameter_name!r} lower_bound must be >= 1, "
                f"got {contract.lower_bound}"
            )
        if contract.upper_bound is not None and contract.upper_bound < contract.lower_bound:
            raise TransformRegistryError(
                f"registration {transform_ref!r} window requirement parameter "
                f"{requirement.parameter_name!r} upper_bound must not be below "
                f"lower_bound, got {contract.upper_bound} < "
                f"{contract.lower_bound}"
            )
        if contract.allowed_values:
            for value in contract.allowed_values:
                if type(value) is not int or value < 1:
                    raise TransformRegistryError(
                        f"registration {transform_ref!r} window requirement "
                        f"parameter {requirement.parameter_name!r} allowed "
                        f"values must all be positive ints, got {value!r}"
                    )


def _validate_callable(implementation) -> None:
    """Function-type restrictions: only a plain, stable, module-level
    function is accepted. The callable is never executed."""
    if not isinstance(implementation, types.FunctionType):
        raise TransformRegistryError(
            "implementation must be a plain Python module-level function, "
            f"got {type(implementation).__name__}"
        )
    if implementation.__name__ == "<lambda>":
        raise TransformRegistryError(
            "lambda implementations are not accepted; a named module-level "
            "function is required"
        )
    if "<locals>" in implementation.__qualname__:
        raise TransformRegistryError(
            "nested or local functions are not accepted; a module-level "
            "function is required"
        )
    if implementation.__closure__ is not None:
        raise TransformRegistryError(
            "closures are not accepted; a module-level function without free "
            "variables is required"
        )
    if inspect.isgeneratorfunction(implementation):
        raise TransformRegistryError(
            "generator functions are not accepted"
        )
    if inspect.iscoroutinefunction(implementation) or inspect.isasyncgenfunction(
        implementation
    ):
        raise TransformRegistryError("async functions are not accepted")


def _module_source_sha256(implementation, transform_ref: str) -> str:
    """Exact-key binding, module resolution, and canonical source digest.

    The registry never imports a module (only the already-loaded module of
    the given function object is looked up in ``sys.modules``), never
    resolves file paths, and never executes the function. The digest is the
    SHA-256 of the normalized UTF-8 module source (see
    ``_normalize_source_text``); file paths, mtimes, memory addresses, and
    local newline styles never enter it.
    """
    _validate_callable(implementation)
    if implementation.__module__ + ":" + implementation.__name__ != transform_ref:
        raise TransformRegistryError(
            "transform_ref must equal implementation.__module__ + ':' + "
            f"implementation.__name__, got {transform_ref!r} for "
            f"{implementation.__module__!r}:{implementation.__name__!r}"
        )
    module = sys.modules.get(implementation.__module__)
    if module is None:
        raise TransformRegistryError(
            f"implementation module {implementation.__module__!r} is not loaded"
        )
    if getattr(module, implementation.__name__, None) is not implementation:
        raise TransformRegistryError(
            f"implementation must be the module attribute "
            f"{implementation.__module__}.{implementation.__name__}"
        )
    try:
        source = inspect.getsource(module)
    except (OSError, TypeError) as exc:
        raise TransformRegistryError(
            f"cannot read stable Python source of module "
            f"{implementation.__module__!r}: {exc}"
        ) from exc
    normalized = _normalize_source_text(source)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _normalize_source_text(text: str) -> str:
    """Deterministic normalization of one module source text.

    Steps: reject non-string input; CRLF / CR normalized to LF; reject NUL
    and unsafe control characters (C0 except tab/newline, DEL, C1 — the
    raw bytes are unlikely but a fail-closed contract is safer than
    guessing); drop leading and trailing blank lines; exactly one final LF.
    No per-line trimming and **no Unicode normalization** is applied: every
    code point of the source, including string-literal contents (where
    composed and decomposed forms stay distinct), is preserved intact — any
    character change of the source content may change the fingerprint. Only
    newline-style, path, and mtime differences are guaranteed to be
    fingerprint-neutral.
    """
    if not isinstance(text, str):
        raise TransformRegistryError(
            f"implementation module source must be text, got {type(text).__name__}"
        )
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for character in text:
        codepoint = ord(character)
        if (
            codepoint == 0x00
            or 0x01 <= codepoint <= 0x08
            or 0x0B <= codepoint <= 0x1F
            or codepoint == 0x7F
            or 0x80 <= codepoint <= 0x9F
        ):
            raise TransformRegistryError(
                f"unsafe control character U+{codepoint:04X} in implementation "
                "module source; fail closed rather than guess"
            )
    lines = text.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        raise TransformRegistryError(
            "implementation module source must contain code text"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Deterministic implementation fingerprint and ImplementationPin mapping.
# ---------------------------------------------------------------------------


def _fingerprint_fields(
    *,
    transform_ref: str,
    kind: str,
    implementation_version: str,
    display_name: str | None,
    source_sha256: str,
    inputs: tuple[str, ...],
    canonical_versions: tuple[str, ...],
    source_versions: tuple[str, ...],
    output_arity: int,
    output_logical_type: str,
    output_nullable: bool,
    parameters: tuple[TransformParameterContract, ...],
    lookback: TransformWindowRequirement,
    lookforward: TransformWindowRequirement,
    boundary_policy: str,
    missing_policy: str,
) -> dict:
    """Flat versioned payload of the implementation fingerprint.

    Arrays are encoded explicitly via count / index / value fields (never
    ambiguous string joins); all values are scalars supported by the
    existing versioned identity encoding. The fingerprint version and the
    registry contract version are part of the payload.
    """
    fields: dict[str, object] = {
        "fingerprint_version": TRANSFORM_IMPLEMENTATION_FINGERPRINT_VERSION,
        "registry_contract_version": TRANSFORM_REGISTRY_CONTRACT_VERSION,
        "transform_ref": transform_ref,
        "kind": kind,
        "implementation_version": implementation_version,
        "display_name": display_name,
        "source_sha256": source_sha256,
        "output_arity": output_arity,
        "output_logical_type": output_logical_type,
        "output_nullable": output_nullable,
        "boundary_policy": boundary_policy,
        "missing_policy": missing_policy,
    }
    fields["input_count"] = len(inputs)
    for index, name in enumerate(inputs):
        fields[f"input_{index:04d}"] = name
    fields["supported_canonical_schema_version_count"] = len(canonical_versions)
    for index, version in enumerate(canonical_versions):
        fields[f"supported_canonical_schema_version_{index:04d}"] = version
    fields["supported_source_schema_version_count"] = len(source_versions)
    for index, version in enumerate(source_versions):
        fields[f"supported_source_schema_version_{index:04d}"] = version
    fields["parameter_count"] = len(parameters)
    for index, contract in enumerate(parameters):
        fields[f"parameter_{index:04d}_name"] = contract.name
        fields[f"parameter_{index:04d}_value_type"] = contract.value_type
        fields[f"parameter_{index:04d}_nullable"] = contract.nullable
        fields[f"parameter_{index:04d}_lower_bound"] = contract.lower_bound
        fields[f"parameter_{index:04d}_upper_bound"] = contract.upper_bound
        allowed = contract.allowed_values or ()
        fields[f"parameter_{index:04d}_allowed_value_count"] = len(allowed)
        for value_index, value in enumerate(allowed):
            fields[f"parameter_{index:04d}_allowed_value_{value_index:04d}"] = value
    for name, requirement in (("lookback", lookback), ("lookforward", lookforward)):
        fields[f"{name}_source"] = requirement.source
        fields[f"{name}_unit"] = requirement.unit
        fields[f"{name}_value"] = requirement.value
        fields[f"{name}_parameter_name"] = requirement.parameter_name
        fields[f"{name}_boundary"] = requirement.boundary
    return fields


def _implementation_fingerprint(
    *,
    transform_ref: str,
    kind: str,
    implementation_version: str,
    display_name: str | None,
    source_sha256: str,
    inputs: tuple[str, ...],
    canonical_versions: tuple[str, ...],
    source_versions: tuple[str, ...],
    output_arity: int,
    output_logical_type: str,
    output_nullable: bool,
    parameters: tuple[TransformParameterContract, ...],
    lookback: TransformWindowRequirement,
    lookforward: TransformWindowRequirement,
    boundary_policy: str,
    missing_policy: str,
) -> str:
    """64-character lowercase SHA-256 over the versioned fingerprint payload.

    Uses the existing versioned identity encoding
    (:func:`market_vault.dataset.encoding.encode_identity`); the versioned
    encoding version, the fingerprint version, the registry contract
    version, the canonical source digest, and every registration metadata
    field participate. Python's process-randomized ``hash()`` and dict
    insertion order never participate.
    """
    fields = _fingerprint_fields(
        transform_ref=transform_ref,
        kind=kind,
        implementation_version=implementation_version,
        display_name=display_name,
        source_sha256=source_sha256,
        inputs=inputs,
        canonical_versions=canonical_versions,
        source_versions=source_versions,
        output_arity=output_arity,
        output_logical_type=output_logical_type,
        output_nullable=output_nullable,
        parameters=parameters,
        lookback=lookback,
        lookforward=lookforward,
        boundary_policy=boundary_policy,
        missing_policy=missing_policy,
    )
    try:
        return encode_identity(TRANSFORM_IMPLEMENTATION_FINGERPRINT_VERSION, fields)
    except DatasetError as exc:
        raise TransformRegistryError(str(exc)) from exc


def transform_implementation_fingerprint(registration: TransformRegistration) -> str:
    """64-character lowercase SHA-256 of one registration's versioned
    implementation fingerprint (its construction-time snapshot)."""
    _require_instance(registration, TransformRegistration, "registration")
    return registration.implementation_fingerprint


def transform_implementation_pin(registration: TransformRegistration) -> ImplementationPin:
    """Map one registration to the existing :class:`ImplementationPin`
    (``name`` = the exact ``transform_ref``, ``version`` = the implementation
    version, ``content_sha256`` = the versioned implementation fingerprint).
    This is the only identity-bearing artifact of the registry; the registry
    contract version itself never enters ``DatasetIdentityInput``. The
    generated pin always carries a non-null content hash."""
    _require_instance(registration, TransformRegistration, "registration")
    return ImplementationPin(
        name=registration.transform_ref,
        version=registration.implementation_version,
        content_sha256=registration.implementation_fingerprint,
    )
