"""Frozen typed models of the deterministic built-in Feature execution
contract (v0.5.0 PR-3).

This module defines the pure in-memory Feature execution core's models:

- the unified fail-closed error :class:`FeatureExecutionError` (a subclass
  of :class:`DatasetError`);
- the version constants of the execution contract and the built-in
  transform invocation contract;
- :class:`FeatureTransformInput` — the frozen invocation input handed to
  every built-in transform (declared canonical field names, the trailing
  contiguous rows the executor selected, and the spec's own validated
  parameters in stable name order);
- the fixed value statuses and exclusion reason codes;
- :class:`FeatureValueResult` / :class:`FeatureSampleResult` — the frozen
  per-feature and per-sample execution results;
- :class:`FeatureExecutionDiagnostics` / :class:`FeatureExecutionResult` —
  the deterministic execution-level result model.

Every model is frozen and validates at construction (fail closed); all
failures raise :class:`FeatureExecutionError`. No Label value is computed
here, no transform is executed here, no PIT row is read here, no Dataset is
built, nothing touches OpenD or the network, and no current time, random
value, filesystem mtime, absolute path, or local timezone ever enters a
result. Results carry no ``built_at`` and define no new execution identity
hash.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from .encoding import DatasetError, normalize_utc_datetime
from .models import ImplementationPin, SpecPin
from .spec_models import SpecParameter

__all__ = [
    "FEATURE_EXECUTION_CONTRACT_VERSION",
    "FEATURE_EXCLUSION_CROSS_MARKET_DATE",
    "FEATURE_EXCLUSION_INSUFFICIENT_ROWS",
    "FEATURE_EXCLUSION_NON_CONTIGUOUS_ROWS",
    "FEATURE_TRANSFORM_CALL_CONTRACT_VERSION",
    "FEATURE_VALUE_STATUS_COMPLETE",
    "FEATURE_VALUE_STATUS_EXCLUDED",
    "FeatureExecutionDiagnostics",
    "FeatureExecutionError",
    "FeatureExecutionResult",
    "FeatureSampleResult",
    "FeatureTransformInput",
    "FeatureValueResult",
]


class FeatureExecutionError(DatasetError):
    """Structured fail-closed failure of the Feature execution layer.

    Raised for invalid execution inputs, provenance mismatches, clock
    violations, spec/registration mismatches, transform invocation failures,
    output type / finite-value violations, and result-model inconsistencies.
    No bare ``KeyError``, ``TypeError``, ``ValueError``, ``ArithmeticError``,
    ``OverflowError``, or transform implementation exception ever leaks past
    this boundary. There is no "warn and continue" path.
    """


#: Version of the Feature execution contract itself. It is carried on every
#: :class:`FeatureExecutionResult` and never enters any existing identity;
#: this PR defines no new execution identity hash.
FEATURE_EXECUTION_CONTRACT_VERSION = "market-vault-feature-execution-v1"

#: Version of the built-in transform invocation contract: a plain
#: module-level function with exactly one positional parameter
#: (``def <name>(input_: FeatureTransformInput) -> float``), no ``*args``,
#: no ``**kwargs``, non-async, non-generator. Any future incompatible change
#: to this signature contract must bump this constant and the affected
#: ``implementation_version`` values.
FEATURE_TRANSFORM_CALL_CONTRACT_VERSION = "market-vault-feature-transform-call-v1"

#: Fixed Feature value statuses.
FEATURE_VALUE_STATUS_COMPLETE = "COMPLETE"
FEATURE_VALUE_STATUS_EXCLUDED = "EXCLUDED"
_FEATURE_VALUE_STATUSES = (FEATURE_VALUE_STATUS_COMPLETE, FEATURE_VALUE_STATUS_EXCLUDED)

#: Fixed Feature exclusion reason codes (no free text).
FEATURE_EXCLUSION_INSUFFICIENT_ROWS = "INSUFFICIENT_ROWS"
FEATURE_EXCLUSION_NON_CONTIGUOUS_ROWS = "NON_CONTIGUOUS_ROWS"
FEATURE_EXCLUSION_CROSS_MARKET_DATE = "CROSS_MARKET_DATE"
_FEATURE_EXCLUSION_REASON_CODES = (
    FEATURE_EXCLUSION_INSUFFICIENT_ROWS,
    FEATURE_EXCLUSION_NON_CONTIGUOUS_ROWS,
    FEATURE_EXCLUSION_CROSS_MARKET_DATE,
)

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def _require_instance(value, cls: type, label: str):
    if not isinstance(value, cls):
        raise FeatureExecutionError(
            f"{label} must be a {cls.__name__}, got {type(value).__name__}"
        )
    return value


def _require_sha256(value, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_HEX_RE.fullmatch(value):
        raise FeatureExecutionError(
            f"{label} must be a 64-character SHA-256 hex string, got {value!r}"
        )
    return value.lower()


def _require_finite_float(value, label: str) -> float:
    """Real finite float; bool, int, NaN, and infinities are never accepted
    as numeric values, and negative zero normalizes to ordinary zero."""
    if type(value) is not float:
        raise FeatureExecutionError(
            f"{label} must be a real finite float64 value, got {type(value).__name__}"
        )
    if value != value or value in (float("inf"), float("-inf")):
        raise FeatureExecutionError(
            f"{label} NaN and positive/negative infinity are rejected, got {value!r}"
        )
    return 0.0 if value == 0.0 else value


def _require_safe_name(value, label: str) -> str:
    """Non-empty safe text name without leading/trailing whitespace."""
    if not isinstance(value, str) or not value:
        raise FeatureExecutionError(f"{label} must be a non-empty string")
    if value != value.strip():
        raise FeatureExecutionError(
            f"{label} must not have leading or trailing whitespace"
        )
    return value


def _normalize_field_names(values) -> tuple[str, ...]:
    """Non-empty unique field names; order is authoritative semantics and is
    preserved exactly (never sorted)."""
    if isinstance(values, (str, bytes)):
        raise FeatureExecutionError(
            "field_names must be an iterable of strings"
        )
    try:
        items = tuple(values)
    except TypeError as exc:
        raise FeatureExecutionError(
            "field_names must be an iterable of strings"
        ) from exc
    if not items:
        raise FeatureExecutionError("field_names must not be empty")
    normalized = tuple(_require_safe_name(item, "field name") for item in items)
    if len(set(normalized)) != len(normalized):
        raise FeatureExecutionError("field_names must not contain duplicates")
    return normalized


def _normalize_rows(rows, field_count: int) -> tuple[tuple[float, ...], ...]:
    """Non-empty tuple of same-length finite float rows; negative zero
    normalizes to ordinary zero."""
    if isinstance(rows, (str, bytes)):
        raise FeatureExecutionError("rows must be an iterable of float tuples")
    try:
        items = tuple(rows)
    except TypeError as exc:
        raise FeatureExecutionError(
            "rows must be an iterable of float tuples"
        ) from exc
    if not items:
        raise FeatureExecutionError("rows must not be empty")
    normalized: list[tuple[float, ...]] = []
    for item in items:
        if isinstance(item, (str, bytes)):
            raise FeatureExecutionError(
                "each row must be a tuple of finite float values"
            )
        try:
            row = tuple(item)
        except TypeError as exc:
            raise FeatureExecutionError(
                "each row must be a tuple of finite float values"
            ) from exc
        if len(row) != field_count:
            raise FeatureExecutionError(
                f"each row must carry exactly {field_count} value(s) matching "
                "field_names, got {len(row)}"
            )
        normalized.append(
            tuple(
                _require_finite_float(value, "input row value") for value in row
            )
        )
    return tuple(normalized)


def _normalize_parameters(values) -> tuple[SpecParameter, ...]:
    """Tuple of SpecParameter in stable name order; unsorted input and
    duplicates fail closed (never silently reordered)."""
    if isinstance(values, (str, bytes)):
        raise FeatureExecutionError(
            "parameters must be an iterable of SpecParameter"
        )
    try:
        items = tuple(values)
    except TypeError as exc:
        raise FeatureExecutionError(
            "parameters must be an iterable of SpecParameter"
        ) from exc
    for item in items:
        _require_instance(item, SpecParameter, "parameter")
    names = [item.name for item in items]
    if names != sorted(names):
        raise FeatureExecutionError(
            "parameters must be sorted by name"
        )
    for previous, current in zip(items, items[1:]):
        if previous.name == current.name:
            raise FeatureExecutionError(
                f"duplicate parameter name {current.name!r}"
            )
    return items


@dataclass(frozen=True)
class FeatureTransformInput:
    """One immutable invocation input of a built-in transform.

    ``field_names`` must equal the registration's ``input_canonical_fields``
    exactly (order is authoritative; the executor guarantees this).
    ``rows`` are the trailing contiguous rows the executor actually
    selected — never more, never fewer — in ascending ``event_time`` order,
    already validated as real finite float64 values; the transform never
    sees Label rows, undeclared Canonical fields, file paths, the network,
    the current time, or any global environment. ``parameters`` are the
    spec's own validated parameters in stable name order. Negative zero is
    normalized to ordinary zero; bool and int are never accepted as numeric
    values.
    """

    field_names: tuple[str, ...]
    rows: tuple[tuple[float, ...], ...]
    parameters: tuple[SpecParameter, ...]

    def __post_init__(self) -> None:
        field_names = _normalize_field_names(self.field_names)
        rows = _normalize_rows(self.rows, len(field_names))
        parameters = _normalize_parameters(self.parameters)
        object.__setattr__(self, "field_names", field_names)
        object.__setattr__(self, "rows", rows)
        object.__setattr__(self, "parameters", parameters)


@dataclass(frozen=True)
class FeatureValueResult:
    """One Feature value result of one sample.

    ``feature_name`` is the spec name; ``spec_pin`` / ``implementation_pin``
    are the existing pins of the spec and its resolved registration (the
    spec pin must carry the spec name). COMPLETE requires a real finite
    float value, a null reason code, and a non-empty tuple of consumed
    canonical row-version IDs. EXCLUDED requires a null value, one of the
    fixed reason codes, and the actually usable row subset (which may be
    empty — an insufficient window consumes nothing). No absolute path,
    ``built_at``, or execution identity hash is ever carried.
    """

    feature_name: str
    spec_pin: SpecPin
    implementation_pin: ImplementationPin
    status: str
    value: float | None
    reason_code: str | None
    consumed_canonical_row_version_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        feature_name = _require_safe_name(self.feature_name, "feature name")
        _require_instance(self.spec_pin, SpecPin, "spec_pin")
        _require_instance(self.implementation_pin, ImplementationPin, "implementation_pin")
        if self.spec_pin.name != feature_name:
            raise FeatureExecutionError(
                f"spec_pin name {self.spec_pin.name!r} must match the feature "
                f"name {feature_name!r}"
            )
        if self.status not in _FEATURE_VALUE_STATUSES:
            raise FeatureExecutionError(
                f"value status must be one of {', '.join(_FEATURE_VALUE_STATUSES)}, "
                f"got {self.status!r}"
            )
        consumed = tuple(
            _require_sha256(value, "consumed canonical row version id")
            for value in self.consumed_canonical_row_version_ids
        )
        if self.status == FEATURE_VALUE_STATUS_COMPLETE:
            if self.reason_code is not None:
                raise FeatureExecutionError(
                    "a COMPLETE value must not carry a reason code"
                )
            if not consumed:
                raise FeatureExecutionError(
                    "a COMPLETE value must record at least one consumed "
                    "canonical row version id"
                )
            if self.value is None:
                raise FeatureExecutionError(
                    "a COMPLETE value must carry a real finite float value"
                )
            value = _require_finite_float(self.value, "feature value")
            object.__setattr__(self, "value", value)
        else:
            if self.value is not None:
                raise FeatureExecutionError(
                    "an EXCLUDED value must carry a null value"
                )
            if self.reason_code not in _FEATURE_EXCLUSION_REASON_CODES:
                raise FeatureExecutionError(
                    f"an EXCLUDED value must carry one of the fixed reason "
                    f"codes {', '.join(_FEATURE_EXCLUSION_REASON_CODES)}, "
                    f"got {self.reason_code!r}"
                )
        object.__setattr__(self, "feature_name", feature_name)
        object.__setattr__(self, "consumed_canonical_row_version_ids", consumed)


@dataclass(frozen=True)
class FeatureSampleResult:
    """One sample's complete Feature execution result.

    ``values`` are ordered by the deterministic spec execution order (stable
    SpecPin order) and their feature names are unique. The sample status is
    COMPLETE when every Feature value is COMPLETE and EXCLUDED when any
    value is EXCLUDED; it is recomputed and verified at construction.
    ``feature_window_close`` is normalized to UTC microseconds.
    """

    sample_key: str
    sample_version_id: str
    code: str
    feature_window_close: datetime
    values: tuple[FeatureValueResult, ...]
    status: str

    def __post_init__(self) -> None:
        sample_key = _require_safe_name(self.sample_key, "sample_key")
        sample_version_id = _require_safe_name(
            self.sample_version_id, "sample_version_id"
        )
        code = _require_safe_name(self.code, "code")
        try:
            feature_window_close = normalize_utc_datetime(
                self.feature_window_close, "feature_window_close"
            )
        except DatasetError as exc:
            raise FeatureExecutionError(str(exc)) from exc
        if isinstance(self.values, (str, bytes)):
            raise FeatureExecutionError(
                "values must be a tuple of FeatureValueResult"
            )
        try:
            values = tuple(self.values)
        except TypeError as exc:
            raise FeatureExecutionError(
                "values must be a tuple of FeatureValueResult"
            ) from exc
        for value in values:
            _require_instance(value, FeatureValueResult, "value")
        names = [value.feature_name for value in values]
        if len(set(names)) != len(names):
            raise FeatureExecutionError(
                "sample Feature values must not contain duplicate feature names"
            )
        if self.status not in _FEATURE_VALUE_STATUSES:
            raise FeatureExecutionError(
                f"sample status must be one of {', '.join(_FEATURE_VALUE_STATUSES)}, "
                f"got {self.status!r}"
            )
        all_complete = all(
            value.status == FEATURE_VALUE_STATUS_COMPLETE for value in values
        )
        any_excluded = any(
            value.status == FEATURE_VALUE_STATUS_EXCLUDED for value in values
        )
        if self.status == FEATURE_VALUE_STATUS_COMPLETE:
            if not all_complete:
                raise FeatureExecutionError(
                    "a COMPLETE sample requires every Feature value COMPLETE"
                )
        else:
            if not any_excluded:
                raise FeatureExecutionError(
                    "an EXCLUDED sample requires at least one EXCLUDED value"
                )
        object.__setattr__(self, "sample_key", sample_key)
        object.__setattr__(self, "sample_version_id", sample_version_id)
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "feature_window_close", feature_window_close)
        object.__setattr__(self, "values", values)


@dataclass(frozen=True)
class FeatureExecutionDiagnostics:
    """Deterministic execution-level counts (no free text)."""

    sample_count: int
    feature_spec_count: int
    complete_sample_count: int
    excluded_sample_count: int
    complete_value_count: int
    excluded_value_count: int
    transform_invocation_count: int

    def __post_init__(self) -> None:
        for name in (
            "sample_count",
            "feature_spec_count",
            "complete_sample_count",
            "excluded_sample_count",
            "complete_value_count",
            "excluded_value_count",
            "transform_invocation_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise FeatureExecutionError(
                    f"{name} must be a non-negative integer, got {value!r}"
                )


def _sorted_unique_pins(pins, label: str, key) -> tuple:
    """Deterministically sorted, duplicate-free tuple of pins."""
    if isinstance(pins, (str, bytes)):
        raise FeatureExecutionError(f"{label} must be an iterable of pins")
    try:
        items = tuple(pins)
    except TypeError as exc:
        raise FeatureExecutionError(f"{label} must be an iterable of pins") from exc
    if not items:
        return ()
    normalized = tuple(
        _require_instance(item, SpecPin if label.startswith("feature") else ImplementationPin, label.rstrip("s"))
        for item in items
    )
    normalized = tuple(sorted(normalized, key=key))
    for previous, current in zip(normalized, normalized[1:]):
        if key(previous) == key(current):
            raise FeatureExecutionError(f"{label} must not contain duplicates")
    return normalized


@dataclass(frozen=True)
class FeatureExecutionResult:
    """Deterministic output of one built-in Feature execution.

    ``samples`` are sorted by ``sample_key``; ``feature_spec_pins`` and
    ``implementation_pins`` are the sorted, deduplicated pins of the
    executed specs and resolved registrations; ``diagnostics`` must equal
    the counts recomputed from the carried samples and pins;
    ``execution_contract_version`` must be the current
    :data:`FEATURE_EXECUTION_CONTRACT_VERSION`. Construction re-verifies
    every invariant (fail closed). The result carries no absolute path, no
    ``built_at``, no ``dataset_id``, and no new execution identity hash.
    """

    samples: tuple[FeatureSampleResult, ...]
    feature_spec_pins: tuple[SpecPin, ...]
    implementation_pins: tuple[ImplementationPin, ...]
    diagnostics: FeatureExecutionDiagnostics
    execution_contract_version: str

    def __post_init__(self) -> None:
        if self.execution_contract_version != FEATURE_EXECUTION_CONTRACT_VERSION:
            raise FeatureExecutionError(
                f"execution_contract_version must be "
                f"{FEATURE_EXECUTION_CONTRACT_VERSION}, got "
                f"{self.execution_contract_version!r}"
            )
        if isinstance(self.samples, (str, bytes)):
            raise FeatureExecutionError(
                "samples must be a tuple of FeatureSampleResult"
            )
        try:
            samples = tuple(self.samples)
        except TypeError as exc:
            raise FeatureExecutionError(
                "samples must be a tuple of FeatureSampleResult"
            ) from exc
        for sample in samples:
            _require_instance(sample, FeatureSampleResult, "sample")
        samples = tuple(sorted(samples, key=lambda sample: sample.sample_key))
        for previous, current in zip(samples, samples[1:]):
            if previous.sample_key == current.sample_key:
                raise FeatureExecutionError(
                    f"duplicate sample_key {current.sample_key!r} in execution result"
                )
        spec_pins = _sorted_unique_pins(
            self.feature_spec_pins,
            "feature_spec_pins",
            key=lambda pin: (pin.kind, pin.name, pin.version, pin.content_sha256),
        )
        implementation_pins = _sorted_unique_pins(
            self.implementation_pins,
            "implementation_pins",
            key=lambda pin: (pin.name, pin.version, pin.content_sha256),
        )
        _require_instance(
            self.diagnostics, FeatureExecutionDiagnostics, "diagnostics"
        )
        complete_samples = sum(
            1 for sample in samples if sample.status == FEATURE_VALUE_STATUS_COMPLETE
        )
        excluded_samples = len(samples) - complete_samples
        complete_values = sum(
            1
            for sample in samples
            for value in sample.values
            if value.status == FEATURE_VALUE_STATUS_COMPLETE
        )
        excluded_values = sum(
            len(sample.values)
            for sample in samples
        ) - complete_values
        expected = FeatureExecutionDiagnostics(
            sample_count=len(samples),
            feature_spec_count=len(spec_pins),
            complete_sample_count=complete_samples,
            excluded_sample_count=excluded_samples,
            complete_value_count=complete_values,
            excluded_value_count=excluded_values,
            transform_invocation_count=complete_values,
        )
        if self.diagnostics != expected:
            raise FeatureExecutionError(
                f"diagnostics {self.diagnostics} do not match the counts "
                f"recomputed from the execution result {expected}"
            )
        used_spec_pins = {value.spec_pin for sample in samples for value in sample.values}
        used_implementation_pins = {
            value.implementation_pin
            for sample in samples
            for value in sample.values
        }
        if not used_spec_pins.issubset(set(spec_pins)):
            raise FeatureExecutionError(
                "every value spec_pin must be among the result feature_spec_pins"
            )
        if not used_implementation_pins.issubset(set(implementation_pins)):
            raise FeatureExecutionError(
                "every value implementation_pin must be among the result "
                "implementation_pins"
            )
        object.__setattr__(self, "samples", samples)
        object.__setattr__(self, "feature_spec_pins", spec_pins)
        object.__setattr__(self, "implementation_pins", implementation_pins)
