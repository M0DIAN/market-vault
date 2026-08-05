"""Frozen typed models of the deterministic built-in Label execution
contract (v0.5.0 PR-4).

This module defines the pure in-memory Label execution core's models:

- the unified fail-closed error :class:`LabelExecutionError` (a subclass
  of :class:`DatasetError`);
- the version constants of the execution contract and the built-in Label
  transform invocation contract, plus the fixed
  :data:`LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED` alignment rule;
- the fixed Label incomplete reason codes;
- :class:`LabelTransformInput` — the frozen invocation input handed to
  every built-in Label transform (declared canonical field names, the
  exact Feature-close anchor row, the future observation rows the executor
  proved sufficient for the spec, the spec's own validated parameters in
  stable name order, and the alignment rule);
- :class:`LabelValueResult` / :class:`LabelSampleResult` — the frozen
  per-label and per-sample execution results with explicit COMPLETE /
  INCOMPLETE statuses, reason codes, consumed row provenance, and
  ``actual_label_end_time``;
- :class:`LabelExecutionDiagnostics` / :class:`LabelExecutionResult` — the
  deterministic execution-level result model.

The value statuses reuse the existing :data:`LABEL_STATUS_COMPLETE` /
:data:`LABEL_STATUS_INCOMPLETE` constants of the split layer; no second
status vocabulary is introduced. Every model is frozen and validates at
construction (fail closed); all failures raise
:class:`LabelExecutionError`. No Feature value is computed here, no
transform is executed here, no PIT row is read here, no split is assigned
here, no Dataset is built, nothing touches OpenD or the network, and no
current time, random value, filesystem mtime, absolute path, or local
timezone ever enters a result. Results carry no ``built_at``, no
``dataset_id``, and define no new execution identity hash.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from .encoding import DatasetError, normalize_utc_datetime
from .models import SPEC_KIND_LABEL, ImplementationPin, SpecPin
from .spec_models import SpecParameter
from .split_models import LABEL_STATUS_COMPLETE, LABEL_STATUS_INCOMPLETE

__all__ = [
    "LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED",
    "LABEL_EXECUTION_CONTRACT_VERSION",
    "LABEL_INCOMPLETE_INSUFFICIENT_ROWS",
    "LABEL_INCOMPLETE_MISSING_ANCHOR_ROW",
    "LABEL_INCOMPLETE_MISSING_TARGET_ROW",
    "LABEL_INCOMPLETE_NON_CONTIGUOUS_ROWS",
    "LABEL_TRANSFORM_CALL_CONTRACT_VERSION",
    "LabelExecutionDiagnostics",
    "LabelExecutionError",
    "LabelExecutionResult",
    "LabelSampleResult",
    "LabelTransformInput",
    "LabelValueResult",
]

_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


class LabelExecutionError(DatasetError):
    """Structured fail-closed failure of the Label execution layer.

    Raised for invalid execution inputs, provenance mismatches, clock
    violations, spec/registration mismatches, configuration-contract
    violations, transform invocation failures, output type / finite-value
    violations, and result-model inconsistencies. No bare ``KeyError``,
    ``TypeError``, ``ValueError``, ``ArithmeticError``, ``OverflowError``,
    ``TransformRegistryError``, ``SpecValidationError``, provenance helper
    error, or transform implementation exception ever leaks past this
    boundary. There is no "warn and continue" path.
    """


#: Version of the Label execution contract itself. It is carried on every
#: :class:`LabelExecutionResult` and never enters any existing identity;
#: this PR defines no new execution identity hash.
LABEL_EXECUTION_CONTRACT_VERSION = "market-vault-label-execution-v1"

#: Version of the built-in Label transform invocation contract: a plain
#: module-level function with exactly one positional parameter
#: (``def <name>(input_: LabelTransformInput) -> float | int``), no
#: ``*args``, no ``**kwargs``, non-async, non-generator. Any future
#: incompatible change to this signature contract must bump this constant
#: and the affected ``implementation_version`` values.
LABEL_TRANSFORM_CALL_CONTRACT_VERSION = "market-vault-label-transform-call-v1"

#: The only Label alignment rule this PR executes. The Feature baseline is
#: the bar that completed exactly at ``feature_window_close`` (its
#: ``event_time`` equals ``feature_window_close - nominal_interval`` and it
#: was market-available no later than ``feature_window_close``); the first
#: future Label bar's ``event_time`` equals ``feature_window_close``.
LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED = "FEATURE_CLOSE_ALIGNED"

#: Fixed Label incomplete reason codes (no free text).
LABEL_INCOMPLETE_MISSING_ANCHOR_ROW = "MISSING_ANCHOR_ROW"
LABEL_INCOMPLETE_MISSING_TARGET_ROW = "MISSING_TARGET_ROW"
LABEL_INCOMPLETE_INSUFFICIENT_ROWS = "INSUFFICIENT_ROWS"
LABEL_INCOMPLETE_NON_CONTIGUOUS_ROWS = "NON_CONTIGUOUS_ROWS"
_LABEL_INCOMPLETE_REASON_CODES = (
    LABEL_INCOMPLETE_MISSING_ANCHOR_ROW,
    LABEL_INCOMPLETE_MISSING_TARGET_ROW,
    LABEL_INCOMPLETE_INSUFFICIENT_ROWS,
    LABEL_INCOMPLETE_NON_CONTIGUOUS_ROWS,
)

_LABEL_STATUSES = (LABEL_STATUS_COMPLETE, LABEL_STATUS_INCOMPLETE)


def _require_instance(value, cls: type, label: str):
    if not isinstance(value, cls):
        raise LabelExecutionError(
            f"{label} must be a {cls.__name__}, got {type(value).__name__}"
        )
    return value


def _require_sha256(value, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_HEX_RE.fullmatch(value):
        raise LabelExecutionError(
            f"{label} must be a 64-character SHA-256 hex string, got {value!r}"
        )
    return value.lower()


def _require_safe_name(value, label: str) -> str:
    """Non-empty safe text name without leading/trailing whitespace."""
    if not isinstance(value, str) or not value:
        raise LabelExecutionError(f"{label} must be a non-empty string")
    if value != value.strip():
        raise LabelExecutionError(
            f"{label} must not have leading or trailing whitespace"
        )
    return value


def _require_finite_float(value, label: str) -> float:
    """Real finite float; bool, int, NaN, and infinities are never accepted
    as numeric values, and negative zero normalizes to ordinary zero."""
    if type(value) is not float:
        raise LabelExecutionError(
            f"{label} must be a real finite float64 value, got {type(value).__name__}"
        )
    if value != value or value in (float("inf"), float("-inf")):
        raise LabelExecutionError(
            f"{label} NaN and positive/negative infinity are rejected, got {value!r}"
        )
    return 0.0 if value == 0.0 else value


def _require_output_scalar(value, label: str) -> float | int:
    """One COMPLETE Label value: a real finite float64 or a real signed
    int64; bool is never accepted as a numeric value, negative zero
    normalizes to ordinary zero."""
    if type(value) is bool:
        raise LabelExecutionError(
            f"{label} must be a real float64 or int64 value; bool is never "
            "treated as a numeric value"
        )
    if type(value) is float:
        return _require_finite_float(value, label)
    if type(value) is int:
        if not _INT64_MIN <= value <= _INT64_MAX:
            raise LabelExecutionError(
                f"{label} must be within signed int64 range, got {value}"
            )
        return value
    raise LabelExecutionError(
        f"{label} must be a real float64 or int64 value, got {type(value).__name__}"
    )


def _require_utc_instant(value, label: str) -> datetime:
    try:
        return normalize_utc_datetime(value, label)
    except DatasetError as exc:
        raise LabelExecutionError(str(exc)) from exc


def _normalize_field_names(values) -> tuple[str, ...]:
    """Non-empty unique field names; order is authoritative semantics and is
    preserved exactly (never sorted)."""
    if isinstance(values, (str, bytes)):
        raise LabelExecutionError(
            "field_names must be an iterable of strings"
        )
    try:
        items = tuple(values)
    except TypeError as exc:
        raise LabelExecutionError(
            "field_names must be an iterable of strings"
        ) from exc
    if not items:
        raise LabelExecutionError("field_names must not be empty")
    normalized = tuple(_require_safe_name(item, "field name") for item in items)
    if len(set(normalized)) != len(normalized):
        raise LabelExecutionError("field_names must not contain duplicates")
    return normalized


def _normalize_value_row(row, field_count: int, label: str) -> tuple[float, ...]:
    """One row of exactly ``field_count`` finite float values; bool and int
    are never accepted as numeric values; negative zero normalizes."""
    if isinstance(row, (str, bytes)):
        raise LabelExecutionError(f"{label} must be a tuple of finite float values")
    try:
        values = tuple(row)
    except TypeError as exc:
        raise LabelExecutionError(
            f"{label} must be a tuple of finite float values"
        ) from exc
    if len(values) != field_count:
        raise LabelExecutionError(
            f"{label} must carry exactly {field_count} value(s) matching "
            f"field_names, got {len(values)}"
        )
    return tuple(
        _require_finite_float(value, f"{label} value") for value in values
    )


def _normalize_parameters(values) -> tuple[SpecParameter, ...]:
    """Tuple of SpecParameter in stable name order; unsorted input and
    duplicates fail closed (never silently reordered)."""
    if isinstance(values, (str, bytes)):
        raise LabelExecutionError(
            "parameters must be an iterable of SpecParameter"
        )
    try:
        items = tuple(values)
    except TypeError as exc:
        raise LabelExecutionError(
            "parameters must be an iterable of SpecParameter"
        ) from exc
    for item in items:
        _require_instance(item, SpecParameter, "parameter")
    names = [item.name for item in items]
    if names != sorted(names):
        raise LabelExecutionError(
            "parameters must be sorted by name"
        )
    for previous, current in zip(items, items[1:]):
        if previous.name == current.name:
            raise LabelExecutionError(
                f"duplicate parameter name {current.name!r}"
            )
    return items


@dataclass(frozen=True)
class LabelTransformInput:
    """One immutable invocation input of a built-in Label transform.

    ``field_names`` must equal the registration's ``input_canonical_fields``
    exactly (order is authoritative; the executor guarantees this).
    ``anchor_row`` is the exact Feature-close anchor bar's values (its
    ``event_time`` equals ``feature_window_close - nominal_interval``).
    ``rows`` are the future Label rows the executor proved satisfy the
    LabelSpec's required-input semantics — never more, never fewer — in
    ascending ``event_time`` order, already validated as real finite float64
    values; the transform never sees Feature rows, undeclared Canonical
    fields, file paths, the network, the current time, or any global
    environment. ``parameters`` are the spec's own validated parameters in
    stable name order. ``alignment_rule`` must be
    :data:`LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED` (the only v1 rule).
    Negative zero is normalized to ordinary zero; bool and int are never
    accepted as numeric values.
    """

    field_names: tuple[str, ...]
    anchor_row: tuple[float, ...]
    rows: tuple[tuple[float, ...], ...]
    parameters: tuple[SpecParameter, ...]
    alignment_rule: str

    def __post_init__(self) -> None:
        field_names = _normalize_field_names(self.field_names)
        if self.alignment_rule != LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED:
            raise LabelExecutionError(
                f"alignment_rule must be {LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED}, "
                f"got {self.alignment_rule!r}"
            )
        anchor_row = _normalize_value_row(
            self.anchor_row, len(field_names), "anchor_row"
        )
        if isinstance(self.rows, (str, bytes)):
            raise LabelExecutionError(
                "rows must be an iterable of float tuples"
            )
        try:
            items = tuple(self.rows)
        except TypeError as exc:
            raise LabelExecutionError(
                "rows must be an iterable of float tuples"
            ) from exc
        if not items:
            raise LabelExecutionError("rows must not be empty")
        rows = tuple(
            _normalize_value_row(row, len(field_names), "input row")
            for row in items
        )
        parameters = _normalize_parameters(self.parameters)
        object.__setattr__(self, "field_names", field_names)
        object.__setattr__(self, "anchor_row", anchor_row)
        object.__setattr__(self, "rows", rows)
        object.__setattr__(self, "parameters", parameters)


@dataclass(frozen=True)
class LabelValueResult:
    """One Label value result of one sample.

    ``label_name`` is the spec name; ``spec_pin`` / ``implementation_pin``
    are the existing pins of the spec and its resolved registration (the
    spec pin must carry the spec name and kind LABEL). COMPLETE requires a
    real finite float64 or real int64 value, a null reason code, the exact
    anchor canonical row-version ID, a non-empty tuple of consumed future
    Label row-version IDs, and a non-null ``actual_label_end_time`` (the
    market availability instant of the last actually consumed Label row).
    INCOMPLETE requires a null value, one of the fixed reason codes, and the
    actually required row subset (which may be empty); its
    ``actual_label_end_time`` records the last actually consumed row's
    availability when a required subset exists, and never makes the status
    COMPLETE. No absolute path, ``built_at``, or execution identity hash is
    ever carried.
    """

    label_name: str
    spec_pin: SpecPin
    implementation_pin: ImplementationPin
    status: str
    value: float | int | None
    reason_code: str | None
    anchor_canonical_row_version_id: str | None
    consumed_label_canonical_row_version_ids: tuple[str, ...]
    actual_label_end_time: datetime | None

    def __post_init__(self) -> None:
        label_name = _require_safe_name(self.label_name, "label name")
        _require_instance(self.spec_pin, SpecPin, "spec_pin")
        _require_instance(self.implementation_pin, ImplementationPin, "implementation_pin")
        if self.spec_pin.kind != SPEC_KIND_LABEL:
            raise LabelExecutionError(
                f"Label value spec_pin kind must be {SPEC_KIND_LABEL}, "
                f"got {self.spec_pin.kind!r}"
            )
        if self.spec_pin.name != label_name:
            raise LabelExecutionError(
                f"spec_pin name {self.spec_pin.name!r} must match the label "
                f"name {label_name!r}"
            )
        if self.implementation_pin.content_sha256 is None:
            raise LabelExecutionError(
                "Label value implementation_pin must carry a non-null "
                "content hash"
            )
        if self.status not in _LABEL_STATUSES:
            raise LabelExecutionError(
                f"value status must be one of {', '.join(_LABEL_STATUSES)}, "
                f"got {self.status!r}"
            )
        anchor = (
            None
            if self.anchor_canonical_row_version_id is None
            else _require_sha256(
                self.anchor_canonical_row_version_id, "anchor canonical row version id"
            )
        )
        consumed = tuple(
            _require_sha256(value, "consumed label canonical row version id")
            for value in self.consumed_label_canonical_row_version_ids
        )
        if len(set(consumed)) != len(consumed):
            raise LabelExecutionError(
                "consumed label canonical row version ids must not contain "
                "duplicates; the original consumption order is preserved"
            )
        actual_end = (
            None
            if self.actual_label_end_time is None
            else _require_utc_instant(self.actual_label_end_time, "actual_label_end_time")
        )
        if self.status == LABEL_STATUS_COMPLETE:
            if self.reason_code is not None:
                raise LabelExecutionError(
                    "a COMPLETE label must not carry a reason code"
                )
            if anchor is None:
                raise LabelExecutionError(
                    "a COMPLETE label must record its anchor canonical row "
                    "version id"
                )
            if not consumed:
                raise LabelExecutionError(
                    "a COMPLETE label must record at least one consumed "
                    "Label canonical row version id"
                )
            if actual_end is None:
                raise LabelExecutionError(
                    "a COMPLETE label must carry a non-null "
                    "actual_label_end_time"
                )
            if self.value is None:
                raise LabelExecutionError(
                    "a COMPLETE label must carry a real float64 or int64 value"
                )
            value = _require_output_scalar(self.value, "label value")
            object.__setattr__(self, "value", value)
        else:
            if self.value is not None:
                raise LabelExecutionError(
                    "an INCOMPLETE label must carry a null value"
                )
            if self.reason_code not in _LABEL_INCOMPLETE_REASON_CODES:
                raise LabelExecutionError(
                    f"an INCOMPLETE label must carry one of the fixed reason "
                    f"codes {', '.join(_LABEL_INCOMPLETE_REASON_CODES)}, "
                    f"got {self.reason_code!r}"
                )
            # Consumed rows and the actual end must be coupled: a non-empty
            # consumed set always carries the last row's actual availability
            # and an empty consumed set never does.
            if bool(consumed) != (actual_end is not None):
                raise LabelExecutionError(
                    "an INCOMPLETE label's consumed label canonical row "
                    "version ids and actual_label_end_time must be both "
                    "present or both absent"
                )
            if self.reason_code == LABEL_INCOMPLETE_MISSING_ANCHOR_ROW:
                if anchor is not None:
                    raise LabelExecutionError(
                        "a MISSING_ANCHOR_ROW label must carry a null anchor "
                        "canonical row version id"
                    )
                if consumed:
                    raise LabelExecutionError(
                        "a MISSING_ANCHOR_ROW label must not carry consumed "
                        "label canonical row version ids"
                    )
            else:
                if anchor is None:
                    raise LabelExecutionError(
                        f"an {self.reason_code} label must carry its anchor "
                        "canonical row version id"
                    )
                if self.reason_code in (
                    LABEL_INCOMPLETE_INSUFFICIENT_ROWS,
                    LABEL_INCOMPLETE_NON_CONTIGUOUS_ROWS,
                ) and not consumed:
                    raise LabelExecutionError(
                        f"an {self.reason_code} label must carry at least "
                        "one consumed label canonical row version id"
                    )
        object.__setattr__(self, "label_name", label_name)
        object.__setattr__(self, "anchor_canonical_row_version_id", anchor)
        object.__setattr__(self, "consumed_label_canonical_row_version_ids", consumed)
        object.__setattr__(self, "actual_label_end_time", actual_end)


@dataclass(frozen=True)
class LabelSampleResult:
    """One sample's complete Label execution result.

    ``values`` are ordered by the deterministic spec execution order (stable
    SpecPin order) and their label names are unique. The sample status is
    COMPLETE when every Label value is COMPLETE and INCOMPLETE when any
    value is INCOMPLETE; it is recomputed and verified at construction.
    ``actual_label_end_time`` is the max of the non-null value
    ``actual_label_end_time`` values (None when every value end is null); a
    COMPLETE sample must carry a non-null end, and every non-null value end
    must not precede ``feature_window_close``. ``feature_window_close`` is
    normalized to UTC microseconds.
    """

    sample_key: str
    sample_version_id: str
    code: str
    feature_window_close: datetime
    values: tuple[LabelValueResult, ...]
    status: str
    actual_label_end_time: datetime | None

    def __post_init__(self) -> None:
        sample_key = _require_safe_name(self.sample_key, "sample_key")
        sample_version_id = _require_safe_name(
            self.sample_version_id, "sample_version_id"
        )
        code = _require_safe_name(self.code, "code")
        feature_window_close = _require_utc_instant(
            self.feature_window_close, "feature_window_close"
        )
        if isinstance(self.values, (str, bytes)):
            raise LabelExecutionError(
                "values must be a tuple of LabelValueResult"
            )
        try:
            values = tuple(self.values)
        except TypeError as exc:
            raise LabelExecutionError(
                "values must be a tuple of LabelValueResult"
            ) from exc
        for value in values:
            _require_instance(value, LabelValueResult, "value")
        names = [value.label_name for value in values]
        if len(set(names)) != len(names):
            raise LabelExecutionError(
                "sample Label values must not contain duplicate label names"
            )
        pin_keys = [
            (
                value.spec_pin.kind,
                value.spec_pin.name,
                value.spec_pin.version,
                value.spec_pin.content_sha256,
            )
            for value in values
        ]
        if pin_keys != sorted(pin_keys):
            raise LabelExecutionError(
                "sample Label values must be ordered by their stable "
                "SpecPin key (kind, name, version, content_sha256)"
            )
        pin_identities = [
            (value.spec_pin.kind, value.spec_pin.name, value.spec_pin.version)
            for value in values
        ]
        if len(set(pin_identities)) != len(pin_identities):
            raise LabelExecutionError(
                "sample Label values must not contain duplicate SpecPin "
                "identities"
            )
        if self.status not in _LABEL_STATUSES:
            raise LabelExecutionError(
                f"sample status must be one of {', '.join(_LABEL_STATUSES)}, "
                f"got {self.status!r}"
            )
        all_complete = all(
            value.status == LABEL_STATUS_COMPLETE for value in values
        )
        any_incomplete = any(
            value.status == LABEL_STATUS_INCOMPLETE for value in values
        )
        if self.status == LABEL_STATUS_COMPLETE:
            if not all_complete:
                raise LabelExecutionError(
                    "a COMPLETE sample requires every Label value COMPLETE"
                )
        else:
            if not any_incomplete:
                raise LabelExecutionError(
                    "an INCOMPLETE sample requires at least one INCOMPLETE value"
                )
        ends = [
            value.actual_label_end_time
            for value in values
            if value.actual_label_end_time is not None
        ]
        for end in ends:
            if end < feature_window_close:
                raise LabelExecutionError(
                    f"sample {sample_key!r} has a value actual_label_end_time "
                    f"{end} before the feature window close "
                    f"{feature_window_close}"
                )
        actual_label_end_time = max(ends) if ends else None
        if actual_label_end_time != self.actual_label_end_time:
            raise LabelExecutionError(
                f"sample {sample_key!r} actual_label_end_time "
                f"{self.actual_label_end_time!r} must equal the max of the "
                f"value ends {actual_label_end_time!r}"
            )
        if self.status == LABEL_STATUS_COMPLETE and actual_label_end_time is None:
            raise LabelExecutionError(
                f"a COMPLETE sample {sample_key!r} must carry a non-null "
                "actual_label_end_time"
            )
        object.__setattr__(self, "sample_key", sample_key)
        object.__setattr__(self, "sample_version_id", sample_version_id)
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "feature_window_close", feature_window_close)
        object.__setattr__(self, "values", values)
        object.__setattr__(
            self, "actual_label_end_time", actual_label_end_time
        )


@dataclass(frozen=True)
class LabelExecutionDiagnostics:
    """Deterministic execution-level counts (no free text)."""

    sample_count: int
    label_spec_count: int
    complete_sample_count: int
    incomplete_sample_count: int
    complete_value_count: int
    incomplete_value_count: int
    transform_invocation_count: int

    def __post_init__(self) -> None:
        for name in (
            "sample_count",
            "label_spec_count",
            "complete_sample_count",
            "incomplete_sample_count",
            "complete_value_count",
            "incomplete_value_count",
            "transform_invocation_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise LabelExecutionError(
                    f"{name} must be a non-negative integer, got {value!r}"
                )


def _normalize_label_spec_pins(pins) -> tuple[SpecPin, ...]:
    """Deterministically sorted, duplicate-free Label SpecPins.

    Every pin must be a SpecPin of kind LABEL. Two pins with the same
    ``(kind, name, version)`` identity are a conflict — even when their
    content hashes differ — and fail closed.
    """
    if isinstance(pins, (str, bytes)):
        raise LabelExecutionError(
            "label_spec_pins must be an iterable of SpecPin"
        )
    try:
        items = tuple(pins)
    except TypeError as exc:
        raise LabelExecutionError(
            "label_spec_pins must be an iterable of SpecPin"
        ) from exc
    normalized = tuple(
        _require_instance(item, SpecPin, "label spec pin") for item in items
    )
    for pin in normalized:
        if pin.kind != SPEC_KIND_LABEL:
            raise LabelExecutionError(
                f"label spec pin kind must be {SPEC_KIND_LABEL}, "
                f"got {pin.kind!r}"
            )
    normalized = tuple(
        sorted(
            normalized,
            key=lambda pin: (pin.kind, pin.name, pin.version, pin.content_sha256),
        )
    )
    for previous, current in zip(normalized, normalized[1:]):
        if (
            previous.kind,
            previous.name,
            previous.version,
        ) == (current.kind, current.name, current.version):
            raise LabelExecutionError(
                f"duplicate label SpecPin identity "
                f"{(current.kind, current.name, current.version)}; even "
                "conflicting content hashes are never silently merged"
            )
    return normalized


def _normalize_implementation_pins(pins) -> tuple[ImplementationPin, ...]:
    """Deterministically sorted, duplicate-free ImplementationPins.

    Every pin must carry a non-null content hash. Two pins with the same
    ``(name, version)`` identity are a conflict — even when their content
    hashes differ — and fail closed. Multiple LabelSpecs may legally share
    one implementation; identical pins deduplicate deterministically.
    """
    if isinstance(pins, (str, bytes)):
        raise LabelExecutionError(
            "implementation_pins must be an iterable of ImplementationPin"
        )
    try:
        items = tuple(pins)
    except TypeError as exc:
        raise LabelExecutionError(
            "implementation_pins must be an iterable of ImplementationPin"
        ) from exc
    normalized = tuple(
        _require_instance(item, ImplementationPin, "implementation pin")
        for item in items
    )
    for pin in normalized:
        if pin.content_sha256 is None:
            raise LabelExecutionError(
                "implementation_pins must carry non-null content hashes"
            )
    normalized = tuple(
        sorted(
            normalized,
            key=lambda pin: (pin.name, pin.version, pin.content_sha256),
        )
    )
    for previous, current in zip(normalized, normalized[1:]):
        if (previous.name, previous.version) == (current.name, current.version):
            raise LabelExecutionError(
                f"duplicate implementation pin identity "
                f"{(current.name, current.version)}; even conflicting "
                "content hashes are never silently merged"
            )
    return normalized


@dataclass(frozen=True)
class LabelExecutionResult:
    """Deterministic output of one built-in Label execution.

    ``samples`` are sorted by ``sample_key``; ``label_spec_pins`` and
    ``implementation_pins`` are the sorted, deduplicated pins of the
    executed specs and resolved registrations; ``diagnostics`` must equal
    the counts recomputed from the carried samples and pins;
    ``execution_contract_version`` must be the current
    :data:`LABEL_EXECUTION_CONTRACT_VERSION`. When samples are non-empty,
    construction verifies complete coverage: every sample carries exactly
    the result's ``label_spec_pins`` in the same order, every LabelSpec maps
    to exactly one ImplementationPin across all samples, and the pins
    actually used by the values equal the result pins exactly (no unused or
    undeclared pins). An empty sample set with a non-empty spec set is a
    documented vacuous execution: no value exists, the coverage invariants
    are vacuous, and the result-level pins stay normalized. Construction
    re-verifies every invariant (fail closed). The result carries no
    absolute path, no ``built_at``, no ``dataset_id``, and no new execution
    identity hash.
    """

    samples: tuple[LabelSampleResult, ...]
    label_spec_pins: tuple[SpecPin, ...]
    implementation_pins: tuple[ImplementationPin, ...]
    diagnostics: LabelExecutionDiagnostics
    execution_contract_version: str

    def __post_init__(self) -> None:
        if self.execution_contract_version != LABEL_EXECUTION_CONTRACT_VERSION:
            raise LabelExecutionError(
                f"execution_contract_version must be "
                f"{LABEL_EXECUTION_CONTRACT_VERSION}, got "
                f"{self.execution_contract_version!r}"
            )
        if isinstance(self.samples, (str, bytes)):
            raise LabelExecutionError(
                "samples must be a tuple of LabelSampleResult"
            )
        try:
            samples = tuple(self.samples)
        except TypeError as exc:
            raise LabelExecutionError(
                "samples must be a tuple of LabelSampleResult"
            ) from exc
        for sample in samples:
            _require_instance(sample, LabelSampleResult, "sample")
        samples = tuple(sorted(samples, key=lambda sample: sample.sample_key))
        for previous, current in zip(samples, samples[1:]):
            if previous.sample_key == current.sample_key:
                raise LabelExecutionError(
                    f"duplicate sample_key {current.sample_key!r} in execution result"
                )
        spec_pins = _normalize_label_spec_pins(self.label_spec_pins)
        implementation_pins = _normalize_implementation_pins(
            self.implementation_pins
        )
        # The v1 execution contract requires at least one LabelSpec. Even a
        # directly constructed result model cannot bypass the executor's
        # non-empty spec requirement, and an execution with no implementation
        # is never a valid Label execution result.
        if not spec_pins:
            raise LabelExecutionError(
                "label_spec_pins must not be empty; Label execution requires "
                "at least one LabelSpec"
            )
        if not implementation_pins:
            raise LabelExecutionError(
                "implementation_pins must not be empty; Label execution "
                "requires at least one resolved implementation"
            )
        _require_instance(
            self.diagnostics, LabelExecutionDiagnostics, "diagnostics"
        )
        complete_samples = sum(
            1 for sample in samples if sample.status == LABEL_STATUS_COMPLETE
        )
        incomplete_samples = len(samples) - complete_samples
        complete_values = sum(
            1
            for sample in samples
            for value in sample.values
            if value.status == LABEL_STATUS_COMPLETE
        )
        incomplete_values = sum(
            len(sample.values)
            for sample in samples
        ) - complete_values
        # Diagnostics matrix: every sample carries exactly one value per
        # label spec, so the value count is the sample/spec product, and
        # every COMPLETE value is the result of exactly one invocation.
        if complete_values + incomplete_values != len(samples) * len(spec_pins):
            raise LabelExecutionError(
                "complete_value_count + incomplete_value_count must equal "
                "sample_count * label_spec_count"
            )
        expected = LabelExecutionDiagnostics(
            sample_count=len(samples),
            label_spec_count=len(spec_pins),
            complete_sample_count=complete_samples,
            incomplete_sample_count=incomplete_samples,
            complete_value_count=complete_values,
            incomplete_value_count=incomplete_values,
            transform_invocation_count=complete_values,
        )
        if self.diagnostics != expected:
            raise LabelExecutionError(
                f"diagnostics {self.diagnostics} do not match the counts "
                f"recomputed from the execution result {expected}"
            )
        if samples:
            # Complete coverage: every sample carries exactly the result's
            # label spec pins, in the same order.
            for sample in samples:
                if tuple(
                    value.spec_pin for value in sample.values
                ) != spec_pins:
                    raise LabelExecutionError(
                        f"sample {sample.sample_key!r} Label values must "
                        "cover exactly the result label_spec_pins, in the "
                        "same order; missing, extra, or reordered labels "
                        "fail closed"
                    )
            # One LabelSpec maps to exactly one ImplementationPin across
            # all samples.
            spec_to_implementation: dict = {}
            for sample in samples:
                for value in sample.values:
                    existing = spec_to_implementation.get(value.spec_pin)
                    if existing is None:
                        spec_to_implementation[value.spec_pin] = (
                            value.implementation_pin
                        )
                    elif existing != value.implementation_pin:
                        raise LabelExecutionError(
                            f"label spec {value.spec_pin.name!r} must map "
                            "to exactly one implementation pin across all "
                            "samples"
                        )
            used_spec_pins = {
                value.spec_pin for sample in samples for value in sample.values
            }
            used_implementation_pins = {
                value.implementation_pin
                for sample in samples
                for value in sample.values
            }
            if used_spec_pins != set(spec_pins):
                raise LabelExecutionError(
                    "the used value spec pins must equal the result "
                    "label_spec_pins exactly; unused or undeclared pins "
                    "fail closed"
                )
            if used_implementation_pins != set(implementation_pins):
                raise LabelExecutionError(
                    "the used value implementation pins must equal the "
                    "result implementation_pins exactly; unused or "
                    "undeclared pins fail closed"
                )
        # Documented decision: an empty sample set with a non-empty spec set
        # is a vacuous execution — no sample carries values, so the
        # coverage invariants above are vacuous, while the result-level
        # pins remain normalized and the diagnostics matrix holds
        # (0 == 0 * label_spec_count).
        object.__setattr__(self, "samples", samples)
        object.__setattr__(self, "label_spec_pins", spec_pins)
        object.__setattr__(self, "implementation_pins", implementation_pins)
