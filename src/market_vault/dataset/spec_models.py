"""Frozen typed models of the versioned Feature and Label specification contracts.

Every model is frozen, validates at construction, and normalizes
deterministically at construction (sorting, NFC normalization, negative-zero
normalization), so the deterministic semantic content identity layer can
trust its inputs. All failures raise the unified :class:`SpecValidationError`
(a subclass of :class:`DatasetError`); unknown, future, or old schema
versions fail closed and are never "best-effort" interpreted.

These models only describe computation contracts. They never import or
execute ``transform_ref``, never compute Feature or Label values, never build
samples or datasets, and never touch the network or the filesystem. Model
instances expose only immutable values: tuples instead of lists, frozen
nested models, and no mutable dicts.
"""

from __future__ import annotations

import math
import numbers
import re
from dataclasses import dataclass, field

from .encoding import DatasetError, normalize_nfc, reject_unsafe_text
from .models import SPEC_KIND_FEATURE, SPEC_KIND_LABEL, DatasetField

__all__ = [
    "FEATURE_LABEL_SPEC_CONTENT_ID_VERSION",
    "FEATURE_SPEC_SCHEMA_VERSION",
    "LABEL_SPEC_SCHEMA_VERSION",
    "CrossTradingDayPolicy",
    "FeatureSpec",
    "LabelHorizon",
    "LabelObservationWindow",
    "LabelSpec",
    "SpecParameter",
    "SpecValidationError",
    "SpecVersionRequirements",
]


class SpecValidationError(DatasetError):
    """Structured validation failure of the Feature/Label spec layer (fail-closed)."""


#: Version of the Feature spec schema accepted by the v1 loader.
FEATURE_SPEC_SCHEMA_VERSION = "market-vault-feature-spec-v1"

#: Version of the Label spec schema accepted by the v1 loader.
LABEL_SPEC_SCHEMA_VERSION = "market-vault-label-spec-v1"

#: Version of the deterministic semantic content identity of Feature/Label
#: specs; changing it changes every spec content ID.
FEATURE_LABEL_SPEC_CONTENT_ID_VERSION = "market-vault-feature-label-spec-content-v1"

#: Canonical label horizon / observation-window units (v1).
_HORIZON_UNITS = ("BARS", "MINUTES", "TRADING_DAYS")

#: v1 missing-data policies. Only INCOMPLETE is accepted: gaps are recorded,
#: never filled, interpolated, or forward-filled.
_MISSING_DATA_POLICIES = ("INCOMPLETE",)

_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1

_SPEC_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_SPEC_VERSION_RE = re.compile(r"^v[1-9][0-9]*$")
_TRANSFORM_REF_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*$"
)
_ALIGNMENT_RULE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _reject_unsafe_spec_text(value: str, label: str) -> None:
    """Safe-text rejection that always surfaces as SpecValidationError."""
    try:
        reject_unsafe_text(value, label)
    except DatasetError as exc:
        raise SpecValidationError(str(exc)) from exc


def _require_spec_name(value) -> str:
    """lower_snake_case spec name; identity-bearing, never silently changed."""
    if not isinstance(value, str):
        raise SpecValidationError(
            f"spec name must be a string, got {type(value).__name__}"
        )
    text = normalize_nfc(value)
    if not _SPEC_NAME_RE.fullmatch(text):
        raise SpecValidationError(
            f"spec name must match ^[a-z][a-z0-9_]*$: {value!r}"
        )
    return text


def _require_spec_version(value) -> str:
    """``vN`` spec version; identity-bearing, never silently changed."""
    if not isinstance(value, str):
        raise SpecValidationError(
            f"spec version must be a string, got {type(value).__name__}"
        )
    text = normalize_nfc(value)
    if not _SPEC_VERSION_RE.fullmatch(text):
        raise SpecValidationError(
            f"spec version must match ^v[1-9][0-9]*$: {value!r}"
        )
    return text


def _require_transform_ref(value) -> str:
    """Explicit Python-style function reference ``module.path:function``.

    This PR only validates the reference shape; the reference is never
    imported or executed.
    """
    if not isinstance(value, str):
        raise SpecValidationError(
            f"transform ref must be a string, got {type(value).__name__}"
        )
    text = normalize_nfc(value)
    if not _TRANSFORM_REF_RE.fullmatch(text):
        raise SpecValidationError(
            f"transform ref must match module.path:function, got {value!r}"
        )
    return text


def _require_alignment_rule(value) -> str:
    """Canonical uppercase safe identifier (v1 alignment rules)."""
    if not isinstance(value, str):
        raise SpecValidationError(
            f"alignment_rule must be a canonical uppercase identifier, "
            f"got {type(value).__name__}"
        )
    text = normalize_nfc(value)
    if not _ALIGNMENT_RULE_RE.fullmatch(text):
        raise SpecValidationError(
            f"alignment_rule must match ^[A-Z][A-Z0-9_]*$: {value!r}"
        )
    return text


def _require_horizon_unit(value, label: str) -> str:
    """Canonical uppercase horizon unit (BARS | MINUTES | TRADING_DAYS)."""
    if not isinstance(value, str):
        raise SpecValidationError(
            f"{label} must be one of {', '.join(_HORIZON_UNITS)}, "
            f"got {type(value).__name__}"
        )
    if value not in _HORIZON_UNITS:
        raise SpecValidationError(
            f"{label} must be one of {', '.join(_HORIZON_UNITS)}, got {value!r}"
        )
    return value


def _require_non_negative_int(value, label: str) -> int:
    """Real non-negative int; bool and float are never accepted."""
    if type(value) is bool or not isinstance(value, numbers.Integral):
        raise SpecValidationError(
            f"{label} must be a non-negative real integer, got {type(value).__name__}"
        )
    integer = int(value)
    if integer < 0:
        raise SpecValidationError(f"{label} must be a non-negative integer, got {integer}")
    return integer


def _normalize_parameter_value(value, label: str) -> object:
    """v1 parameter values: None | real bool | int64 | finite float64 | safe
    string. Lists, tuples, dicts, dates, datetimes, bytes, and custom objects
    are rejected; NaN and infinities are rejected; negative zero normalizes
    to ordinary zero."""
    if value is None:
        return None
    if type(value) is bool:
        return value
    if isinstance(value, numbers.Integral):
        integer = int(value)
        if not _INT64_MIN <= integer <= _INT64_MAX:
            raise SpecValidationError(
                f"{label} must be within signed int64 range [-2**63, 2**63-1], "
                f"got {integer}"
            )
        return integer
    if isinstance(value, numbers.Real):
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            raise SpecValidationError(
                f"{label} NaN and positive/negative infinity are rejected, got {number!r}"
            )
        # -0.0 and 0.0 are equivalent in identity; normalize before storing.
        return 0.0 if number == 0.0 else number
    if isinstance(value, str):
        text = normalize_nfc(value)
        _reject_unsafe_spec_text(text, label)
        return text
    raise SpecValidationError(
        f"{label} has an unsupported value type {type(value).__name__}; "
        "v1 parameters support only None, bool, int64, finite float64, and "
        "safe strings"
    )


def _normalize_input_fields(values) -> tuple[str, ...]:
    """Non-empty unique input canonical fields, order authoritative.

    Field order is semantic and preserved exactly (never sorted); text
    follows the safe-text rules (NFC, no leading/trailing whitespace, no
    control characters, no reserved encoding separators).
    """
    if isinstance(values, (str, bytes)):
        raise SpecValidationError(
            "input_canonical_fields must be an iterable of strings"
        )
    try:
        items = tuple(values)
    except TypeError as exc:
        raise SpecValidationError(
            "input_canonical_fields must be an iterable of strings"
        ) from exc
    if not items:
        raise SpecValidationError("input_canonical_fields must not be empty")
    normalized: list[str] = []
    for item in items:
        if not isinstance(item, str):
            raise SpecValidationError(
                f"input canonical fields must be strings, got {type(item).__name__}"
            )
        text = normalize_nfc(item)
        if not text or not text.strip():
            raise SpecValidationError("input canonical field names must not be empty")
        if text != text.strip():
            raise SpecValidationError(
                "input canonical field names must not have leading or trailing "
                "whitespace"
            )
        _reject_unsafe_spec_text(text, "input canonical field name")
        normalized.append(text)
    if len(set(normalized)) != len(normalized):
        raise SpecValidationError("input_canonical_fields must not contain duplicates")
    return tuple(normalized)


def _normalize_parameters(values) -> tuple["SpecParameter", ...]:
    """Parameters deterministically sorted by name; duplicates fail closed."""
    if isinstance(values, (str, bytes)):
        raise SpecValidationError("parameters must be an iterable of SpecParameter")
    try:
        items = tuple(values)
    except TypeError as exc:
        raise SpecValidationError("parameters must be an iterable of SpecParameter") from exc
    for item in items:
        if not isinstance(item, SpecParameter):
            raise SpecValidationError(
                f"parameters must contain SpecParameter instances, "
                f"got {type(item).__name__}"
            )
    items = tuple(sorted(items, key=lambda item: item.name))
    for previous, current in zip(items, items[1:]):
        if previous.name == current.name:
            raise SpecValidationError(
                f"duplicate parameter name {current.name!r}"
            )
    return items


def _normalize_versions(values, label: str) -> tuple[str, ...]:
    """Non-empty unique safe version strings, deterministically sorted."""
    if isinstance(values, (str, bytes)):
        raise SpecValidationError(f"{label} must be an iterable of strings")
    try:
        items = tuple(values)
    except TypeError as exc:
        raise SpecValidationError(f"{label} must be an iterable of strings") from exc
    if not items:
        raise SpecValidationError(f"{label} must not be empty")
    normalized: list[str] = []
    for item in items:
        if not isinstance(item, str):
            raise SpecValidationError(
                f"{label} entries must be strings, got {type(item).__name__}"
            )
        text = normalize_nfc(item)
        if not text:
            raise SpecValidationError(f"{label} entries must not be empty")
        if text != text.strip():
            raise SpecValidationError(
                f"{label} entries must not have leading or trailing whitespace"
            )
        _reject_unsafe_spec_text(text, f"{label} entry")
        normalized.append(text)
    if len(set(normalized)) != len(normalized):
        raise SpecValidationError(f"{label} must not contain duplicates")
    return tuple(sorted(normalized))


def _require_instance(value, cls: type, label: str):
    if not isinstance(value, cls):
        raise SpecValidationError(
            f"{label} must be a {cls.__name__}, got {type(value).__name__}"
        )
    return value


@dataclass(frozen=True)
class SpecParameter:
    """One named v1 parameter: a flat scalar (None | bool | int64 | finite
    float64 | safe string). Names are NFC-normalized, non-empty, free of
    leading/trailing whitespace, and free of control characters and reserved
    encoding separators; bool is never treated as int; int range is strictly
    signed int64; float NaN/Infinity fail; -0.0 normalizes to 0.0."""

    name: str
    value: object

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise SpecValidationError(
                f"parameter name must be a string, got {type(self.name).__name__}"
            )
        name = normalize_nfc(self.name)
        if not name or not name.strip():
            raise SpecValidationError("parameter name must not be empty")
        if name != name.strip():
            raise SpecValidationError(
                "parameter name must not have leading or trailing whitespace"
            )
        _reject_unsafe_spec_text(name, "parameter name")
        object.__setattr__(self, "name", name)
        object.__setattr__(
            self, "value", _normalize_parameter_value(self.value, f"parameter {name!r} value")
        )


@dataclass(frozen=True)
class SpecVersionRequirements:
    """Required canonical and source schema versions.

    Both lists are non-empty; entries are safe, non-empty strings without
    leading/trailing whitespace; duplicates fail; order is not semantic and
    is deterministically sorted at construction.
    """

    canonical_schema_versions: tuple[str, ...]
    source_schema_versions: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "canonical_schema_versions",
            _normalize_versions(self.canonical_schema_versions, "canonical_schema_versions"),
        )
        object.__setattr__(
            self,
            "source_schema_versions",
            _normalize_versions(self.source_schema_versions, "source_schema_versions"),
        )


@dataclass(frozen=True)
class LabelHorizon:
    """Label horizon: a positive integer in one canonical unit."""

    unit: str
    value: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "unit", _require_horizon_unit(self.unit, "horizon unit"))
        if type(self.value) is bool or not isinstance(self.value, numbers.Integral):
            raise SpecValidationError(
                f"horizon value must be a real positive integer, "
                f"got {type(self.value).__name__}"
            )
        value = int(self.value)
        if value <= 0:
            raise SpecValidationError(f"horizon value must be a positive integer, got {value}")
        object.__setattr__(self, "value", value)


@dataclass(frozen=True)
class LabelObservationWindow:
    """Label observation window: offsets within one canonical unit.

    ``start_offset`` and ``end_offset`` are non-negative real ints with
    ``start_offset <= end_offset``; a zero-length window (start == end) is
    allowed.
    """

    unit: str
    start_offset: int
    end_offset: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "unit", _require_horizon_unit(self.unit, "observation window unit")
        )
        start = _require_non_negative_int(self.start_offset, "observation window start_offset")
        end = _require_non_negative_int(self.end_offset, "observation window end_offset")
        if start > end:
            raise SpecValidationError(
                "observation window start_offset must not exceed end_offset, "
                f"got {start} > {end}"
            )
        object.__setattr__(self, "start_offset", start)
        object.__setattr__(self, "end_offset", end)


@dataclass(frozen=True)
class CrossTradingDayPolicy:
    """Explicit cross-trading-day policy; no hidden defaults.

    ``allow == false`` requires a null ``boundary_rule`` (the default policy
    forbids label windows spanning a ``market_calendar_date`` boundary);
    ``allow == true`` requires a non-empty safe boundary rule.
    """

    allow: bool
    boundary_rule: str | None

    def __post_init__(self) -> None:
        if type(self.allow) is not bool:
            raise SpecValidationError(
                f"cross_trading_day.allow must be a real bool, "
                f"got {type(self.allow).__name__}"
            )
        if not self.allow:
            if self.boundary_rule is not None:
                raise SpecValidationError(
                    "cross_trading_day.boundary_rule must be null when allow is false"
                )
            object.__setattr__(self, "boundary_rule", None)
            return
        if not isinstance(self.boundary_rule, str):
            raise SpecValidationError(
                "cross_trading_day.boundary_rule must be a non-empty safe string "
                "when allow is true"
            )
        rule = normalize_nfc(self.boundary_rule)
        if not rule or rule != rule.strip():
            raise SpecValidationError(
                "cross_trading_day.boundary_rule must be a non-empty safe string "
                "when allow is true"
            )
        _reject_unsafe_spec_text(rule, "cross_trading_day.boundary_rule")
        object.__setattr__(self, "boundary_rule", rule)


@dataclass(frozen=True)
class FeatureSpec:
    """Versioned Feature computation contract (v1).

    ``kind`` is fixed to FEATURE and is not constructible or forgeable.
    ``output`` reuses the existing :class:`DatasetField` model and its name
    must equal the spec name; input canonical field order is authoritative
    and identity-bearing; ``transform_ref`` is a reference only and is never
    imported or executed by this layer.
    """

    spec_schema_version: str
    name: str
    version: str
    output: DatasetField
    input_canonical_fields: tuple[str, ...]
    transform_ref: str
    parameters: tuple[SpecParameter, ...]
    requirements: SpecVersionRequirements
    kind: str = field(default=SPEC_KIND_FEATURE, init=False)

    def __post_init__(self) -> None:
        if self.spec_schema_version != FEATURE_SPEC_SCHEMA_VERSION:
            raise SpecValidationError(
                f"unsupported feature spec schema version {self.spec_schema_version!r}; "
                f"only {FEATURE_SPEC_SCHEMA_VERSION} is accepted"
            )
        name = _require_spec_name(self.name)
        version = _require_spec_version(self.version)
        output = _require_instance(self.output, DatasetField, "output")
        if output.name != name:
            raise SpecValidationError(
                f"output field name must match the spec name, got {output.name!r} != {name!r}"
            )
        inputs = _normalize_input_fields(self.input_canonical_fields)
        transform_ref = _require_transform_ref(self.transform_ref)
        parameters = _normalize_parameters(self.parameters)
        requirements = _require_instance(
            self.requirements, SpecVersionRequirements, "requirements"
        )
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "output", output)
        object.__setattr__(self, "input_canonical_fields", inputs)
        object.__setattr__(self, "transform_ref", transform_ref)
        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(self, "requirements", requirements)


@dataclass(frozen=True)
class LabelSpec:
    """Versioned Label computation contract (v1).

    ``kind`` is fixed to LABEL and is not constructible or forgeable.
    ``observation_window.unit`` must equal ``horizon.unit``; v1
    ``missing_data_policy`` accepts only INCOMPLETE (gaps are recorded, never
    filled); a TRADING_DAYS horizon requires an explicit
    ``cross_trading_day.allow: true`` opt-in with a boundary rule.
    """

    spec_schema_version: str
    name: str
    version: str
    output: DatasetField
    input_canonical_fields: tuple[str, ...]
    transform_ref: str
    parameters: tuple[SpecParameter, ...]
    requirements: SpecVersionRequirements
    observation_window: LabelObservationWindow
    horizon: LabelHorizon
    alignment_rule: str
    missing_data_policy: str
    cross_trading_day: CrossTradingDayPolicy
    kind: str = field(default=SPEC_KIND_LABEL, init=False)

    def __post_init__(self) -> None:
        if self.spec_schema_version != LABEL_SPEC_SCHEMA_VERSION:
            raise SpecValidationError(
                f"unsupported label spec schema version {self.spec_schema_version!r}; "
                f"only {LABEL_SPEC_SCHEMA_VERSION} is accepted"
            )
        name = _require_spec_name(self.name)
        version = _require_spec_version(self.version)
        output = _require_instance(self.output, DatasetField, "output")
        if output.name != name:
            raise SpecValidationError(
                f"output field name must match the spec name, got {output.name!r} != {name!r}"
            )
        inputs = _normalize_input_fields(self.input_canonical_fields)
        transform_ref = _require_transform_ref(self.transform_ref)
        parameters = _normalize_parameters(self.parameters)
        requirements = _require_instance(
            self.requirements, SpecVersionRequirements, "requirements"
        )
        window = _require_instance(
            self.observation_window, LabelObservationWindow, "observation_window"
        )
        horizon = _require_instance(self.horizon, LabelHorizon, "horizon")
        if window.unit != horizon.unit:
            raise SpecValidationError(
                f"observation_window.unit must equal horizon.unit, "
                f"got {window.unit!r} != {horizon.unit!r}"
            )
        alignment_rule = _require_alignment_rule(self.alignment_rule)
        if self.missing_data_policy not in _MISSING_DATA_POLICIES:
            raise SpecValidationError(
                f"unsupported missing_data_policy {self.missing_data_policy!r}; "
                f"v1 accepts only {', '.join(_MISSING_DATA_POLICIES)}"
            )
        cross = _require_instance(
            self.cross_trading_day, CrossTradingDayPolicy, "cross_trading_day"
        )
        if horizon.unit == "TRADING_DAYS" and not cross.allow:
            raise SpecValidationError(
                "cross_trading_day.allow must be true when horizon.unit is TRADING_DAYS"
            )
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "output", output)
        object.__setattr__(self, "input_canonical_fields", inputs)
        object.__setattr__(self, "transform_ref", transform_ref)
        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(self, "requirements", requirements)
        object.__setattr__(self, "observation_window", window)
        object.__setattr__(self, "horizon", horizon)
        object.__setattr__(self, "alignment_rule", alignment_rule)
        object.__setattr__(self, "cross_trading_day", cross)
