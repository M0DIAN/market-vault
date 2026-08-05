"""Deterministic built-in Label execution core (v0.5.0 PR-4).

:func:`execute_builtin_labels` is the single public entry point: it binds a
:class:`PITAssemblyResult` to its verified Canonical builds, resolves the
LabelSpecs against the immutable built-in Label registry, and computes one
Label value per sample per spec over the exact Feature-close anchor row and
the PIT-selected future Label rows — with strict row binding, clock,
provenance, exact horizon-target alignment, observation-window contiguity,
output-type, and finite-value validation, and explicit COMPLETE /
INCOMPLETE results carrying ``actual_label_end_time``.

The executor never redoes PIT selection, never redefines ``sample_key`` /
``sample_version_id``, never reads rows outside the PIT-selected Feature and
Label row-version lists, never modifies the PIT result or the Canonical
builds, never interpolates or forward-fills, never infers completeness from
"no gap records", never uses the current time, a random value, a local
timezone, a filesystem mtime, or an absolute path, and never accesses OpenD
or the network. Only the built-in registry's function objects are ever
invoked; a caller cannot inject an external registration. Every failure
surfaces as :class:`LabelExecutionError` (fail closed); there is no "warn
and continue" path and no partial "successful" result. The PIT-to-Canonical
binding and provenance verification shared with the Feature executor (PR-3)
lives in the private :mod:`market_vault.dataset.execution_provenance`
module and is reused here unchanged.
"""

from __future__ import annotations

import inspect
import math
import types
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..canonical.reader import VerifiedCanonicalBuild
from ..intraday_audit import parse_intraday_interval
from .encoding import DatasetError, normalize_utc_datetime
from .execution_provenance import (
    ExecutionProvenanceError,
    ResolvedRow,
    normalize_verified_builds,
    reconcile_canonical_rows,
    verify_pit_pin_binding,
)
from .label_models import (
    LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED,
    LABEL_EXECUTION_CONTRACT_VERSION,
    LABEL_INCOMPLETE_INSUFFICIENT_ROWS,
    LABEL_INCOMPLETE_MISSING_ANCHOR_ROW,
    LABEL_INCOMPLETE_MISSING_TARGET_ROW,
    LABEL_INCOMPLETE_NON_CONTIGUOUS_ROWS,
    LabelExecutionDiagnostics,
    LabelExecutionError,
    LabelExecutionResult,
    LabelSampleResult,
    LabelTransformInput,
    LabelValueResult,
)
from .label_registry import built_in_label_registry
from .models import ImplementationPin
from .pit_models import PITAssemblyResult, PITSample
from .spec_models import LabelSpec, SpecValidationError
from .specs import feature_label_spec_pin
from .split_models import LABEL_STATUS_COMPLETE, LABEL_STATUS_INCOMPLETE
from .transform_models import (
    TransformRegistration,
    TransformRegistryError,
)

__all__ = ["execute_builtin_labels"]

#: The Canonical market float fields a built-in Label may consume.
_CANONICAL_INPUT_FIELDS = ("open", "high", "low", "close", "volume")

#: Exact transform_ref values of the four built-in Label transforms; the
#: executor uses them for the fixed observation-window shapes and the
#: forward_direction output range check.
_REF_FORWARD_RETURN = (
    "market_vault.dataset.label_transforms.forward_return:forward_return"
)
_REF_FORWARD_DIRECTION = (
    "market_vault.dataset.label_transforms.forward_direction:forward_direction"
)
_REF_MAXIMUM_FAVORABLE_EXCURSION = (
    "market_vault.dataset.label_transforms."
    "maximum_favorable_excursion:maximum_favorable_excursion"
)
_REF_MAXIMUM_ADVERSE_EXCURSION = (
    "market_vault.dataset.label_transforms."
    "maximum_adverse_excursion:maximum_adverse_excursion"
)
_FORWARD_SHAPE_REFS = (_REF_FORWARD_RETURN, _REF_FORWARD_DIRECTION)
_EXCURSION_SHAPE_REFS = (
    _REF_MAXIMUM_FAVORABLE_EXCURSION,
    _REF_MAXIMUM_ADVERSE_EXCURSION,
)

_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


def execute_builtin_labels(builds, pit_result, label_specs) -> LabelExecutionResult:
    """Execute the built-in Label catalog over one PIT assembly result.

    ``builds`` must be verified Canonical builds (produced by the verified
    reader) whose identities correspond exactly to
    ``pit_result.canonical_build_pins``; input order never matters.
    ``pit_result`` must be a :class:`PITAssemblyResult`; it is never
    modified and PIT selection is never redone. ``label_specs`` must be
    LabelSpecs only (a FeatureSpec is rejected), order-insensitive,
    duplicate-free in name and SpecPin, and non-empty (an execution that
    claims Label completeness requires at least one LabelSpec; an empty
    sample set with non-empty specs is a documented vacuous execution).
    """
    try:
        return _execute_builtin_labels(builds, pit_result, label_specs)
    except ExecutionProvenanceError as exc:
        raise LabelExecutionError(str(exc)) from exc


def _execute_builtin_labels(builds, pit_result, label_specs) -> LabelExecutionResult:
    try:
        registry = built_in_label_registry()
    except TransformRegistryError as exc:
        raise LabelExecutionError(
            f"failed to construct built-in Label registry: {exc}"
        ) from exc
    build_items = normalize_verified_builds(builds)
    if not isinstance(pit_result, PITAssemblyResult):
        raise LabelExecutionError(
            "pit_result must be a PITAssemblyResult, "
            f"got {type(pit_result).__name__}"
        )
    spec_items = _normalize_label_specs(label_specs)
    builds_by_id = {build.canonical_build_id: build for build in build_items}
    # Row reconciliation runs first; the exact Pin verification below
    # reconstructs the expected pins from the reconciled rows.
    rows_by_version = reconcile_canonical_rows(build_items)
    verify_pit_pin_binding(pit_result, builds_by_id, rows_by_version)

    resolved_items = []
    for spec in spec_items:
        try:
            resolved = registry.resolve_label_spec(spec)
        except TransformRegistryError as exc:
            raise LabelExecutionError(
                f"cannot resolve label spec {spec.name!r}: {exc}"
            ) from exc
        resolved_items.append((spec, resolved))
    for _, resolved in resolved_items:
        _validate_callable_contract(resolved.registration)

    samples: list[LabelSampleResult] = []
    invocation_count = 0
    for sample in sorted(pit_result.samples, key=lambda item: item.sample_key):
        _validate_label_window(sample, resolved_items)
        values = []
        for spec, resolved in resolved_items:
            value, invoked = _execute_label_value(
                sample, spec, resolved, rows_by_version, builds_by_id
            )
            values.append(value)
            invocation_count += 1 if invoked else 0
        status = (
            LABEL_STATUS_COMPLETE
            if all(value.status == LABEL_STATUS_COMPLETE for value in values)
            else LABEL_STATUS_INCOMPLETE
        )
        ends = [
            value.actual_label_end_time
            for value in values
            if value.actual_label_end_time is not None
        ]
        samples.append(
            LabelSampleResult(
                sample_key=sample.sample_key,
                sample_version_id=sample.sample_version_id,
                code=sample.request.code,
                feature_window_close=sample.request.feature_window_close,
                values=tuple(values),
                status=status,
                actual_label_end_time=max(ends) if ends else None,
            )
        )

    diagnostics = LabelExecutionDiagnostics(
        sample_count=len(samples),
        label_spec_count=len(spec_items),
        complete_sample_count=sum(
            1 for sample in samples if sample.status == LABEL_STATUS_COMPLETE
        ),
        incomplete_sample_count=sum(
            1 for sample in samples if sample.status == LABEL_STATUS_INCOMPLETE
        ),
        complete_value_count=sum(
            1
            for sample in samples
            for value in sample.values
            if value.status == LABEL_STATUS_COMPLETE
        ),
        incomplete_value_count=sum(
            1
            for sample in samples
            for value in sample.values
            if value.status == LABEL_STATUS_INCOMPLETE
        ),
        transform_invocation_count=invocation_count,
    )
    return LabelExecutionResult(
        samples=tuple(samples),
        label_spec_pins=tuple(_spec_pin(spec) for spec in spec_items),
        implementation_pins=_unique_implementation_pins(resolved_items),
        diagnostics=diagnostics,
        execution_contract_version=LABEL_EXECUTION_CONTRACT_VERSION,
    )


# ---------------------------------------------------------------------------
# Input normalization.
# ---------------------------------------------------------------------------


def _spec_pin(spec: LabelSpec) -> SpecPin:
    """SpecPin generation that always surfaces as LabelExecutionError."""
    try:
        return feature_label_spec_pin(spec)
    except SpecValidationError as exc:
        raise LabelExecutionError(
            f"cannot compute the SpecPin of label spec {spec.name!r}: {exc}"
        ) from exc


def _normalize_label_specs(label_specs) -> tuple[LabelSpec, ...]:
    """LabelSpecs only (FeatureSpecs fail closed), order-insensitive,
    duplicate-free in name and SpecPin, ordered by stable SpecPin key. An
    empty spec set is rejected: Label execution requires at least one
    LabelSpec."""
    try:
        items = tuple(label_specs)
    except TypeError as exc:
        raise LabelExecutionError(
            "label_specs must be an iterable of LabelSpec instances, "
            f"got {type(label_specs).__name__}"
        ) from exc
    if not items:
        raise LabelExecutionError(
            "label_specs must not be empty; Label execution requires at "
            "least one LabelSpec"
        )
    for item in items:
        if not isinstance(item, LabelSpec):
            raise LabelExecutionError(
                "label_specs must contain LabelSpec instances only; "
                f"FeatureSpecs are not executed as labels, got "
                f"{type(item).__name__}"
            )
    names = [spec.name for spec in items]
    if len(set(names)) != len(names):
        raise LabelExecutionError(
            "label_specs must not contain duplicate spec names"
        )
    pins = [_spec_pin(spec) for spec in items]
    pin_keys = [(pin.kind, pin.name, pin.version, pin.content_sha256) for pin in pins]
    if len(set(pin_keys)) != len(pin_keys):
        raise LabelExecutionError(
            "label_specs must not contain duplicate SpecPins"
        )
    ordered = sorted(
        zip(items, pins),
        key=lambda pair: (pair[1].kind, pair[1].name, pair[1].version, pair[1].content_sha256),
    )
    return tuple(item for item, _ in ordered)


def _unique_implementation_pins(resolved_items) -> tuple[ImplementationPin, ...]:
    """Deterministic deduplication of the resolved implementation pins.

    Multiple LabelSpecs may legally share one transform implementation, in
    which case their ResolvedTransforms carry the identical
    ``ImplementationPin``. The result contract records the **unique set of
    implementations actually used**: identical pins (same name, version,
    and content hash) deduplicate deterministically, while the same
    ``(name, version)`` identity with a different content hash is a
    conflict and fails closed. The output is sorted by ``(name, version,
    content_sha256)``.
    """
    by_key: dict[tuple[str, str], ImplementationPin] = {}
    for _, resolved in resolved_items:
        pin = resolved.pin
        if not isinstance(pin, ImplementationPin):
            raise LabelExecutionError(
                "resolved implementation pin must be an ImplementationPin, "
                f"got {type(pin).__name__}"
            )
        if pin.content_sha256 is None:
            raise LabelExecutionError(
                "resolved implementation pin must carry a non-null content hash"
            )
        key = (pin.name, pin.version)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = pin
        elif existing != pin:
            raise LabelExecutionError(
                f"conflicting implementation pins share the identity {key}: "
                "the same name/version with different content hashes fails "
                "closed"
            )
    return tuple(
        sorted(
            by_key.values(),
            key=lambda pin: (pin.name, pin.version, pin.content_sha256),
        )
    )


# ---------------------------------------------------------------------------
# Callable contract.
# ---------------------------------------------------------------------------


def _validate_callable_contract(registration: TransformRegistration) -> None:
    """Validate the v1 Label invocation contract of a built-in transform
    before any invocation: a plain module-level function with exactly one
    positional parameter and no defaults, non-async, non-generator."""
    implementation = registration.implementation
    if not isinstance(implementation, types.FunctionType):
        raise LabelExecutionError(
            f"registration {registration.transform_ref!r} implementation must "
            "be a plain module-level function"
        )
    if (
        inspect.isgeneratorfunction(implementation)
        or inspect.iscoroutinefunction(implementation)
        or inspect.isasyncgenfunction(implementation)
    ):
        raise LabelExecutionError(
            f"registration {registration.transform_ref!r} implementation must "
            "be a plain synchronous non-generator function"
        )
    try:
        signature = inspect.signature(implementation)
    except (TypeError, ValueError) as exc:
        raise LabelExecutionError(
            f"cannot inspect the signature of registration "
            f"{registration.transform_ref!r}: {exc}"
        ) from exc
    parameters = list(signature.parameters.values())
    if len(parameters) != 1:
        raise LabelExecutionError(
            f"registration {registration.transform_ref!r} implementation must "
            f"accept exactly one positional parameter, got {len(parameters)}"
        )
    parameter = parameters[0]
    if parameter.kind not in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    ):
        raise LabelExecutionError(
            f"registration {registration.transform_ref!r} implementation "
            "parameter must be positional"
        )
    if parameter.default is not inspect.Parameter.empty:
        raise LabelExecutionError(
            f"registration {registration.transform_ref!r} implementation "
            "parameter must not carry a default value"
        )


# ---------------------------------------------------------------------------
# Sample / window configuration contracts.
# ---------------------------------------------------------------------------


def _validate_label_window(
    sample: PITSample,
    resolved_items,
) -> None:
    """Every PIT sample request must carry a complete Label window covering
    every LabelSpec's horizon: ``label_window_start == feature_window_close``
    and ``label_window_close >= feature_window_close + horizon.value *
    nominal_interval`` for every spec. A missing or insufficient Label
    window is a builder/request configuration error and fails closed — it
    is never recorded as ordinary INCOMPLETE data."""
    request = sample.request
    if request.label_window_start is None or request.label_window_close is None:
        raise LabelExecutionError(
            f"sample {sample.sample_key!r} carries no complete Label window; "
            "label_window_start and label_window_close are required when "
            "LabelSpecs are executed"
        )
    if request.label_window_start != request.feature_window_close:
        raise LabelExecutionError(
            f"sample {sample.sample_key!r} label_window_start "
            f"{request.label_window_start} must equal the feature window "
            f"close {request.feature_window_close}"
        )
    try:
        interval = parse_intraday_interval(request.interval)
    except ValueError as exc:
        raise LabelExecutionError(
            f"sample {sample.sample_key!r} interval {request.interval!r} is "
            f"not parseable: {exc}"
        ) from exc
    for spec, resolved in resolved_items:
        required_close = request.feature_window_close + (
            spec.horizon.value * interval
        )
        if request.label_window_close < required_close:
            raise LabelExecutionError(
                f"sample {sample.sample_key!r} label_window_close "
                f"{request.label_window_close} does not cover the horizon of "
                f"label spec {spec.name!r}, which requires "
                f"{required_close}"
            )


def _validate_spec_shape(spec: LabelSpec, registration: TransformRegistration) -> None:
    """Fixed LabelSpec shape contracts of this PR's built-in catalog.

    Every built-in LabelSpec must satisfy
    ``observation_window.end_offset == horizon.value - 1``; the forward
    transforms additionally require ``start_offset == end_offset`` (only the
    horizon target row is required) and the excursion transforms require
    ``start_offset == 0`` (the full window from the first future bar). A
    spec violating its transform's shape is a configuration-contract error
    and fails closed — it is never marked INCOMPLETE."""
    horizon = spec.horizon.value
    window = spec.observation_window
    if window.end_offset != horizon - 1:
        raise LabelExecutionError(
            f"label spec {spec.name!r} observation_window.end_offset "
            f"{window.end_offset} must equal horizon.value - 1 ({horizon - 1}) "
            "for every built-in Label transform"
        )
    if registration.transform_ref in _FORWARD_SHAPE_REFS:
        if window.start_offset != horizon - 1:
            raise LabelExecutionError(
                f"label spec {spec.name!r} observation_window.start_offset "
                f"{window.start_offset} must equal horizon.value - 1 "
                f"({horizon - 1}) for the forward transform "
                f"{registration.transform_ref!r}: only the horizon target row "
                "is required"
            )
        return
    if registration.transform_ref in _EXCURSION_SHAPE_REFS:
        if window.start_offset != 0:
            raise LabelExecutionError(
                f"label spec {spec.name!r} observation_window.start_offset "
                f"{window.start_offset} must be 0 for the excursion transform "
                f"{registration.transform_ref!r}: every future bar from "
                "offset 0 to the horizon target is required"
            )
        return
    raise LabelExecutionError(
        f"registration {registration.transform_ref!r} is not a supported "
        "built-in Label transform of this catalog"
    )


# ---------------------------------------------------------------------------
# Row validation.
# ---------------------------------------------------------------------------


def _validate_anchor_row(
    sample: PITSample,
    spec: LabelSpec,
    resolved_row: ResolvedRow,
    builds_by_id: dict,
) -> None:
    """Defensive per-row invariant checks of the exact Feature-close anchor.
    The PIT assembler has already performed the legal selection; any
    violation here is an inconsistency and fails closed."""
    bar = resolved_row.bar
    request = sample.request
    version = bar.canonical_row_version_id
    sample_label = f"sample {sample.sample_key!r}"
    if bar.code != request.code:
        raise LabelExecutionError(
            f"anchor row version {version} of {sample_label} carries code "
            f"{bar.code!r}, expected {request.code!r}"
        )
    if bar.interval != request.interval:
        raise LabelExecutionError(
            f"anchor row version {version} of {sample_label} carries interval "
            f"{bar.interval!r}, expected {request.interval!r}"
        )
    if bar.adjustment != request.adjustment:
        raise LabelExecutionError(
            f"anchor row version {version} of {sample_label} carries "
            f"adjustment {bar.adjustment!r}, expected {request.adjustment!r}"
        )
    if bar.requested_session != request.requested_session:
        raise LabelExecutionError(
            f"anchor row version {version} of {sample_label} carries "
            f"requested session {bar.requested_session!r}, expected "
            f"{request.requested_session!r}"
        )
    if bar.market_calendar_date != request.anchor_market_calendar_date:
        raise LabelExecutionError(
            f"anchor row version {version} of {sample_label} carries market "
            f"calendar date {bar.market_calendar_date}, expected "
            f"{request.anchor_market_calendar_date}"
        )
    if not (
        request.feature_window_start <= bar.event_time < request.feature_window_close
    ):
        raise LabelExecutionError(
            f"anchor row version {version} of {sample_label} has event_time "
            f"{bar.event_time}, outside the feature window "
            f"[{request.feature_window_start}, {request.feature_window_close})"
        )
    if bar.market_available_at > request.feature_window_close:
        raise LabelExecutionError(
            f"anchor row version {version} of {sample_label} has "
            f"market_available_at {bar.market_available_at}, after the "
            f"feature window close {request.feature_window_close}"
        )
    if sample.dataset_as_of is not None and bar.archive_available_at > sample.dataset_as_of:
        raise LabelExecutionError(
            f"anchor row version {version} of {sample_label} has "
            f"archive_available_at {bar.archive_available_at}, after "
            f"dataset_as_of {sample.dataset_as_of}"
        )
    if bar.source_schema_version not in spec.requirements.source_schema_versions:
        raise LabelExecutionError(
            f"anchor row version {version} of {sample_label} carries source "
            f"schema version {bar.source_schema_version!r}, not declared by "
            f"label spec {spec.name!r} requirements"
        )
    for build_id in resolved_row.build_ids:
        build = builds_by_id[build_id]
        if build.canonical_schema_version not in spec.requirements.canonical_schema_versions:
            raise LabelExecutionError(
                f"anchor row version {version} of {sample_label} comes from "
                f"build {build_id} with canonical schema version "
                f"{build.canonical_schema_version!r}, not declared by label "
                f"spec {spec.name!r} requirements"
            )


def _validate_label_row(
    sample: PITSample,
    spec: LabelSpec,
    resolved_row: ResolvedRow,
    builds_by_id: dict,
) -> None:
    """Defensive per-row invariant checks of one PIT-selected Label row. The
    PIT assembler has already performed the legal selection; any violation
    here is an inconsistency and fails closed — including a Label row on a
    different market calendar date, which violates the
    NO_CROSS_TRADING_DAY boundary policy of the built-in registrations."""
    bar = resolved_row.bar
    request = sample.request
    version = bar.canonical_row_version_id
    sample_label = f"sample {sample.sample_key!r}"
    if bar.code != request.code:
        raise LabelExecutionError(
            f"label row version {version} of {sample_label} carries code "
            f"{bar.code!r}, expected {request.code!r}"
        )
    if bar.interval != request.interval:
        raise LabelExecutionError(
            f"label row version {version} of {sample_label} carries interval "
            f"{bar.interval!r}, expected {request.interval!r}"
        )
    if bar.adjustment != request.adjustment:
        raise LabelExecutionError(
            f"label row version {version} of {sample_label} carries "
            f"adjustment {bar.adjustment!r}, expected {request.adjustment!r}"
        )
    if bar.requested_session != request.requested_session:
        raise LabelExecutionError(
            f"label row version {version} of {sample_label} carries "
            f"requested session {bar.requested_session!r}, expected "
            f"{request.requested_session!r}"
        )
    if not (
        request.label_window_start <= bar.event_time < request.label_window_close
    ):
        raise LabelExecutionError(
            f"label row version {version} of {sample_label} has event_time "
            f"{bar.event_time}, outside the label window "
            f"[{request.label_window_start}, {request.label_window_close})"
        )
    if bar.market_available_at > request.label_window_close:
        raise LabelExecutionError(
            f"label row version {version} of {sample_label} has "
            f"market_available_at {bar.market_available_at}, after the label "
            f"window close {request.label_window_close}"
        )
    if sample.dataset_as_of is not None and bar.archive_available_at > sample.dataset_as_of:
        raise LabelExecutionError(
            f"label row version {version} of {sample_label} has "
            f"archive_available_at {bar.archive_available_at}, after "
            f"dataset_as_of {sample.dataset_as_of}"
        )
    if bar.market_calendar_date != request.anchor_market_calendar_date:
        raise LabelExecutionError(
            f"label row version {version} of {sample_label} carries market "
            f"calendar date {bar.market_calendar_date}, but the sample is "
            f"anchored to {request.anchor_market_calendar_date}; a Label row "
            "crossing the market calendar date violates the "
            "NO_CROSS_TRADING_DAY boundary policy"
        )
    if bar.source_schema_version not in spec.requirements.source_schema_versions:
        raise LabelExecutionError(
            f"label row version {version} of {sample_label} carries source "
            f"schema version {bar.source_schema_version!r}, not declared by "
            f"label spec {spec.name!r} requirements"
        )
    for build_id in resolved_row.build_ids:
        build = builds_by_id[build_id]
        if build.canonical_schema_version not in spec.requirements.canonical_schema_versions:
            raise LabelExecutionError(
                f"label row version {version} of {sample_label} comes from "
                f"build {build_id} with canonical schema version "
                f"{build.canonical_schema_version!r}, not declared by label "
                f"spec {spec.name!r} requirements"
            )


def _bar_input_row(bar, field_names: tuple[str, ...]) -> tuple[float, ...]:
    """One row of finite float64 values in the registration's authoritative
    field order; undeclared fields are never exposed to a transform."""
    values = []
    for field in field_names:
        if field not in _CANONICAL_INPUT_FIELDS:
            raise LabelExecutionError(
                f"input canonical field {field!r} is not a consumable "
                "Canonical market float field"
            )
        value = getattr(bar, field)
        if type(value) is not float:
            raise LabelExecutionError(
                f"canonical field {field!r} value of row "
                f"{bar.canonical_row_version_id} is not a real float64 "
                f"value, got {type(value).__name__}"
            )
        values.append(value)
    return tuple(values)


# ---------------------------------------------------------------------------
# Per-value execution.
# ---------------------------------------------------------------------------


def _execute_label_value(
    sample: PITSample,
    spec: LabelSpec,
    resolved,
    rows_by_version: dict,
    builds_by_id: dict,
) -> tuple[LabelValueResult, bool]:
    """Compute one Label value of one sample, returning the value result and
    whether the transform was invoked (exactly once per COMPLETE value,
    never for INCOMPLETE)."""
    registration = resolved.registration
    _validate_spec_shape(spec, registration)
    try:
        interval = parse_intraday_interval(sample.request.interval)
    except ValueError as exc:
        raise LabelExecutionError(
            f"sample {sample.sample_key!r} interval "
            f"{sample.request.interval!r} is not parseable: {exc}"
        ) from exc

    anchor = _resolve_anchor(sample, spec, rows_by_version, builds_by_id, interval)
    if anchor is None:
        return _incomplete(
            sample,
            spec,
            resolved,
            reason=LABEL_INCOMPLETE_MISSING_ANCHOR_ROW,
            anchor_id=None,
            consumed_rows=(),
        )

    future_rows = _resolve_label_rows(sample, spec, rows_by_version, builds_by_id)

    if registration.transform_ref in _FORWARD_SHAPE_REFS:
        outcome = _select_forward_target(sample, spec, interval, future_rows)
    else:
        outcome = _select_excursion_window(sample, spec, interval, future_rows)
    if not outcome.complete:
        return _incomplete(
            sample,
            spec,
            resolved,
            reason=outcome.reason,
            anchor_id=anchor.bar.canonical_row_version_id,
            consumed_rows=outcome.consumed_rows,
        )

    anchor_values = _bar_input_row(anchor.bar, registration.input_canonical_fields)
    input_rows = tuple(
        _bar_input_row(row.bar, registration.input_canonical_fields)
        for row in outcome.consumed_rows
    )
    transform_input = LabelTransformInput(
        field_names=registration.input_canonical_fields,
        anchor_row=anchor_values,
        rows=input_rows,
        parameters=resolved.parameters,
        alignment_rule=LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED,
    )
    try:
        value = registration.implementation(transform_input)
    except Exception as exc:
        raise LabelExecutionError(
            f"transform {registration.transform_ref!r} for spec {spec.name!r} "
            f"of sample {sample.sample_key!r} failed: {exc}"
        ) from exc
    value = _validate_output_value(value, spec, registration)
    actual_end = _actual_end(sample, outcome.consumed_rows[-1].bar)
    return (
        LabelValueResult(
            label_name=spec.name,
            spec_pin=_spec_pin(spec),
            implementation_pin=resolved.pin,
            status=LABEL_STATUS_COMPLETE,
            value=value,
            reason_code=None,
            anchor_canonical_row_version_id=anchor.bar.canonical_row_version_id,
            consumed_label_canonical_row_version_ids=tuple(
                row.bar.canonical_row_version_id for row in outcome.consumed_rows
            ),
            actual_label_end_time=actual_end,
        ),
        True,
    )


def _incomplete(
    sample: PITSample,
    spec: LabelSpec,
    resolved,
    *,
    reason: str,
    anchor_id: str | None,
    consumed_rows: tuple,
) -> tuple[LabelValueResult, bool]:
    """One explicit INCOMPLETE Label result; the transform is never invoked.

    ``consumed_rows`` is the actually required subset in expected position
    order (may be empty); when it is non-empty the value's
    ``actual_label_end_time`` records the last consumed row's market
    availability — it never makes the status COMPLETE."""
    consumed_versions = tuple(
        row.bar.canonical_row_version_id for row in consumed_rows
    )
    actual_end = (
        _actual_end(sample, consumed_rows[-1].bar) if consumed_rows else None
    )
    return (
        LabelValueResult(
            label_name=spec.name,
            spec_pin=_spec_pin(spec),
            implementation_pin=resolved.pin,
            status=LABEL_STATUS_INCOMPLETE,
            value=None,
            reason_code=reason,
            anchor_canonical_row_version_id=anchor_id,
            consumed_label_canonical_row_version_ids=consumed_versions,
            actual_label_end_time=actual_end,
        ),
        False,
    )


@dataclass(frozen=True)
class _Selection:
    """One future-row selection outcome: the consumed rows in expected
    position order, whether the required inputs are complete, and the
    incomplete reason code (None when complete)."""

    consumed_rows: tuple
    complete: bool
    reason: str | None


def _resolve_anchor(
    sample: PITSample,
    spec: LabelSpec,
    rows_by_version: dict,
    builds_by_id: dict,
    interval: timedelta,
) -> ResolvedRow | None:
    """Resolve and validate the exact Feature-close anchor row from
    ``sample.feature_canonical_row_version_ids`` only.

    The anchor's ``event_time`` must be exactly
    ``feature_window_close - nominal_interval``; the Feature row list must
    be strictly ascending (duplicates and inversions are provenance
    inconsistencies and fail closed). When the exact anchor does not exist
    the label is INCOMPLETE (MISSING_ANCHOR_ROW) and no transform is
    invoked; an older Feature row never substitutes."""
    rows: list[ResolvedRow] = []
    for version in sample.feature_canonical_row_version_ids:
        resolved_row = rows_by_version.get(version)
        if resolved_row is None:
            raise LabelExecutionError(
                f"sample {sample.sample_key!r} references canonical row "
                f"version {version}, which no supplied build contains"
            )
        rows.append(resolved_row)
    for previous, current in zip(rows, rows[1:]):
        if current.bar.event_time <= previous.bar.event_time:
            raise LabelExecutionError(
                f"feature rows of sample {sample.sample_key!r} are not in "
                "strictly ascending event_time order"
            )
    anchor_time = sample.request.feature_window_close - interval
    matches = [
        row for row in rows if row.bar.event_time == anchor_time
    ]
    if not matches:
        return None
    if len(matches) > 1:
        raise LabelExecutionError(
            f"sample {sample.sample_key!r} contains duplicate exact Feature "
            "anchor rows"
        )
    anchor = matches[0]
    _validate_anchor_row(sample, spec, anchor, builds_by_id)
    return anchor


def _resolve_label_rows(
    sample: PITSample,
    spec: LabelSpec,
    rows_by_version: dict,
    builds_by_id: dict,
) -> list[ResolvedRow]:
    """Resolve and defensively validate every PIT-selected Label row of the
    sample (position order). Rows outside the PIT Label lists are never
    read, no alternative row is searched for, and any invariant violation
    fails closed."""
    rows: list[ResolvedRow] = []
    for version in sample.label_canonical_row_version_ids:
        resolved_row = rows_by_version.get(version)
        if resolved_row is None:
            raise LabelExecutionError(
                f"sample {sample.sample_key!r} references label canonical "
                f"row version {version}, which no supplied build contains"
            )
        rows.append(resolved_row)
    for previous, current in zip(rows, rows[1:]):
        if current.bar.event_time <= previous.bar.event_time:
            raise LabelExecutionError(
                f"label rows of sample {sample.sample_key!r} are not in "
                "strictly ascending event_time order"
            )
    for row in rows:
        _validate_label_row(sample, spec, row, builds_by_id)
    return rows


def _select_forward_target(
    sample: PITSample,
    spec: LabelSpec,
    interval: timedelta,
    future_rows: list[ResolvedRow],
) -> _Selection:
    """Forward transforms require only the exact horizon target row:
    ``event_time == feature_window_close + (horizon.value - 1) *
    nominal_interval``. Middle future bars are not required inputs; their
    absence never makes a forward target label INCOMPLETE, and a nearby
    other row never substitutes for the exact target."""
    target_time = sample.request.feature_window_close + (
        (spec.horizon.value - 1) * interval
    )
    target = next(
        (row for row in future_rows if row.bar.event_time == target_time),
        None,
    )
    if target is None:
        return _Selection((), False, LABEL_INCOMPLETE_MISSING_TARGET_ROW)
    return _Selection((target,), True, None)


def _select_excursion_window(
    sample: PITSample,
    spec: LabelSpec,
    interval: timedelta,
    future_rows: list[ResolvedRow],
) -> _Selection:
    """Excursion transforms require every expected future bar from offset 0
    to ``horizon.value - 1`` (their exact nominal event times). The target
    row is the horizon target; a missing target is MISSING_TARGET_ROW, a
    missing first row is INSUFFICIENT_ROWS, and a missing interior row with
    the target present is NON_CONTIGUOUS_ROWS. Only exact event times are
    accepted; nothing is interpolated or substituted. The consumed subset
    records every actually present required row in expected position order,
    so an INCOMPLETE excursion still carries the real observed subset and
    its last row's actual availability."""
    horizon = spec.horizon.value
    by_time = {row.bar.event_time: row for row in future_rows}
    present: list[ResolvedRow] = []
    for index in range(horizon):
        row = by_time.get(
            sample.request.feature_window_close + (index * interval)
        )
        if row is not None:
            present.append(row)
    target_time = sample.request.feature_window_close + (
        (horizon - 1) * interval
    )
    if target_time not in by_time:
        return _Selection(
            tuple(present), False, LABEL_INCOMPLETE_MISSING_TARGET_ROW
        )
    for index in range(horizon):
        row = by_time.get(
            sample.request.feature_window_close + (index * interval)
        )
        if row is None:
            reason = (
                LABEL_INCOMPLETE_INSUFFICIENT_ROWS
                if index == 0
                else LABEL_INCOMPLETE_NON_CONTIGUOUS_ROWS
            )
            return _Selection(tuple(present), False, reason)
    return _Selection(tuple(present), True, None)


def _actual_end(sample: PITSample, bar) -> datetime:
    """``actual_label_end_time`` is the market availability instant of the
    last actually consumed Label row — never a nominal horizon, never
    ``label_window_close``, never the target ``event_time``, never the
    current time — normalized to UTC microseconds and never before
    ``feature_window_close``."""
    try:
        end = normalize_utc_datetime(bar.market_available_at, "actual_label_end_time")
    except DatasetError as exc:
        raise LabelExecutionError(str(exc)) from exc
    if end < sample.request.feature_window_close:
        raise LabelExecutionError(
            f"sample {sample.sample_key!r} actual_label_end_time {end} "
            "must not precede the feature window close "
            f"{sample.request.feature_window_close}"
        )
    return end


def _validate_output_value(value, spec: LabelSpec, registration) -> float | int:
    """Output contract validation: the transform must return a real float64
    or real int64 matching the registration and spec output contracts;
    bool never masquerades as a numeric value, NaN / infinities fail,
    negative zero normalizes, and ``forward_direction`` must return one of
    ``-1``, ``0``, ``1``. No automatic conversion or rounding ever
    happens."""
    if registration.output_logical_type == "float64":
        if type(value) is not float:
            raise LabelExecutionError(
                f"transform {registration.transform_ref!r} for spec "
                f"{spec.name!r} returned {type(value).__name__}, expected a "
                "real float64 value"
            )
        if value != value or value in (float("inf"), float("-inf")):
            raise LabelExecutionError(
                f"transform {registration.transform_ref!r} for spec "
                f"{spec.name!r} returned NaN or infinity; non-finite output "
                "fails the build"
            )
        value = 0.0 if value == 0.0 else value
    elif registration.output_logical_type == "int64":
        if type(value) is not int:
            raise LabelExecutionError(
                f"transform {registration.transform_ref!r} for spec "
                f"{spec.name!r} returned {type(value).__name__}, expected a "
                "real int64 value; bool is never accepted"
            )
        if not _INT64_MIN <= value <= _INT64_MAX:
            raise LabelExecutionError(
                f"transform {registration.transform_ref!r} for spec "
                f"{spec.name!r} returned {value}, outside signed int64 range"
            )
        if (
            registration.transform_ref == _REF_FORWARD_DIRECTION
            and value not in (-1, 0, 1)
        ):
            raise LabelExecutionError(
                f"transform {registration.transform_ref!r} for spec "
                f"{spec.name!r} returned {value}, outside the allowed "
                "forward_direction values -1, 0, 1"
            )
    else:
        raise LabelExecutionError(
            f"registration {registration.transform_ref!r} output contract "
            "must be float64 or int64 for built-in Label execution"
        )
    if (
        spec.output.logical_type != registration.output_logical_type
        or spec.output.nullable != registration.output_nullable
    ):
        raise LabelExecutionError(
            f"spec {spec.name!r} output contract does not match registration "
            f"{registration.transform_ref!r}"
        )
    return value
