"""Deterministic built-in Feature execution core (v0.5.0 PR-3).

:func:`execute_builtin_features` is the single public entry point: it binds
a :class:`PITAssemblyResult` to its verified Canonical builds, resolves the
FeatureSpecs against the immutable built-in Feature registry, and computes
one Feature value per sample per spec over the PIT-selected Feature rows —
with strict row binding, clock, provenance, trailing-window, contiguity,
output-type, and finite-value validation.

The executor never redoes PIT selection, never redefines ``sample_key`` /
``sample_version_id``, never reads Label rows for a Feature, never modifies
the PIT result or the Canonical builds, never interpolates or forward-fills,
never uses the current time, a random value, a local timezone, a filesystem
mtime, or an absolute path, and never accesses OpenD or the network. Only
the built-in registry's function objects are ever invoked; a caller cannot
inject an external registration. Every failure surfaces as
:class:`FeatureExecutionError` (fail closed); there is no "warn and
continue" path and no partial "successful" result.
"""

from __future__ import annotations

import inspect
import types
from dataclasses import dataclass

from ..canonical.reader import VerifiedCanonicalBuild
from ..intraday_audit import parse_intraday_interval
from .feature_models import (
    FEATURE_EXECUTION_CONTRACT_VERSION,
    FEATURE_EXCLUSION_CROSS_MARKET_DATE,
    FEATURE_EXCLUSION_INSUFFICIENT_ROWS,
    FEATURE_EXCLUSION_NON_CONTIGUOUS_ROWS,
    FEATURE_VALUE_STATUS_COMPLETE,
    FEATURE_VALUE_STATUS_EXCLUDED,
    FeatureExecutionDiagnostics,
    FeatureExecutionError,
    FeatureExecutionResult,
    FeatureSampleResult,
    FeatureTransformInput,
    FeatureValueResult,
)
from .feature_registry import built_in_feature_registry
from .pit import _row_comparator
from .pit_models import PITAssemblyResult, PITSample
from .spec_models import FeatureSpec
from .specs import feature_label_spec_pin
from .transform_models import (
    MISSING_POLICY_EXCLUDE_SAMPLE,
    MISSING_POLICY_FAIL,
    TransformRegistration,
    TransformRegistryError,
    WINDOW_SOURCE_FIXED,
    WINDOW_SOURCE_NONE,
    WINDOW_SOURCE_PARAMETER,
)

__all__ = ["execute_builtin_features"]

#: The Canonical market float fields a built-in Feature may consume.
_CANONICAL_INPUT_FIELDS = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class _ResolvedRow:
    """One row-version binding: the reconciled bar and every build that
    carries it (deterministically sorted)."""

    bar: object
    build_ids: tuple[str, ...]


def execute_builtin_features(builds, pit_result, feature_specs) -> FeatureExecutionResult:
    """Execute the built-in Feature catalog over one PIT assembly result.

    ``builds`` must be verified Canonical builds (produced by the verified
    reader) whose identities correspond exactly to
    ``pit_result.canonical_build_pins``; input order never matters.
    ``pit_result`` must be a :class:`PITAssemblyResult`; it is never
    modified and PIT selection is never redone. ``feature_specs`` must be
    FeatureSpecs only (a LabelSpec is rejected), order-insensitive,
    duplicate-free in name and SpecPin. An empty spec set is allowed and
    produces COMPLETE samples with no Feature values (documented decision).
    """
    registry = built_in_feature_registry()
    build_items = _normalize_builds(builds)
    if not isinstance(pit_result, PITAssemblyResult):
        raise FeatureExecutionError(
            "pit_result must be a PITAssemblyResult, "
            f"got {type(pit_result).__name__}"
        )
    spec_items = _normalize_feature_specs(feature_specs)
    builds_by_id = {build.canonical_build_id: build for build in build_items}
    _verify_pin_binding(pit_result, builds_by_id)
    rows_by_version = _reconcile_rows(build_items)

    resolved_items = []
    for spec in spec_items:
        try:
            resolved = registry.resolve_feature_spec(spec)
        except TransformRegistryError as exc:
            raise FeatureExecutionError(
                f"cannot resolve feature spec {spec.name!r}: {exc}"
            ) from exc
        resolved_items.append((spec, resolved))
    for _, resolved in resolved_items:
        _validate_callable_contract(resolved.registration)

    samples: list[FeatureSampleResult] = []
    invocation_count = 0
    for sample in sorted(pit_result.samples, key=lambda item: item.sample_key):
        values = []
        for spec, resolved in resolved_items:
            value, invoked = _execute_feature_value(
                sample, spec, resolved, rows_by_version, builds_by_id
            )
            values.append(value)
            invocation_count += 1 if invoked else 0
        status = (
            FEATURE_VALUE_STATUS_COMPLETE
            if all(value.status == FEATURE_VALUE_STATUS_COMPLETE for value in values)
            else FEATURE_VALUE_STATUS_EXCLUDED
        )
        samples.append(
            FeatureSampleResult(
                sample_key=sample.sample_key,
                sample_version_id=sample.sample_version_id,
                code=sample.request.code,
                feature_window_close=sample.request.feature_window_close,
                values=tuple(values),
                status=status,
            )
        )

    diagnostics = FeatureExecutionDiagnostics(
        sample_count=len(samples),
        feature_spec_count=len(spec_items),
        complete_sample_count=sum(
            1 for sample in samples if sample.status == FEATURE_VALUE_STATUS_COMPLETE
        ),
        excluded_sample_count=sum(
            1 for sample in samples if sample.status == FEATURE_VALUE_STATUS_EXCLUDED
        ),
        complete_value_count=sum(
            1
            for sample in samples
            for value in sample.values
            if value.status == FEATURE_VALUE_STATUS_COMPLETE
        ),
        excluded_value_count=sum(
            1
            for sample in samples
            for value in sample.values
            if value.status == FEATURE_VALUE_STATUS_EXCLUDED
        ),
        transform_invocation_count=invocation_count,
    )
    return FeatureExecutionResult(
        samples=tuple(samples),
        feature_spec_pins=tuple(feature_label_spec_pin(spec) for spec in spec_items),
        implementation_pins=tuple(resolved.pin for _, resolved in resolved_items),
        diagnostics=diagnostics,
        execution_contract_version=FEATURE_EXECUTION_CONTRACT_VERSION,
    )


# ---------------------------------------------------------------------------
# Input normalization.
# ---------------------------------------------------------------------------


def _normalize_builds(builds) -> tuple[VerifiedCanonicalBuild, ...]:
    """Verified builds only, deterministically sorted by build id; duplicate
    build ids fail closed."""
    try:
        items = tuple(builds)
    except TypeError as exc:
        raise FeatureExecutionError(
            "builds must be an iterable of VerifiedCanonicalBuild instances, "
            f"got {type(builds).__name__}"
        ) from exc
    for item in items:
        if not isinstance(item, VerifiedCanonicalBuild):
            raise FeatureExecutionError(
                "builds must contain VerifiedCanonicalBuild instances produced "
                f"by the verified reader, got {type(item).__name__}"
            )
    build_ids = [build.canonical_build_id for build in items]
    if len(set(build_ids)) != len(build_ids):
        raise FeatureExecutionError("duplicate canonical_build_id in builds")
    return tuple(sorted(items, key=lambda build: build.canonical_build_id))


def _normalize_feature_specs(feature_specs) -> tuple[FeatureSpec, ...]:
    """FeatureSpecs only (LabelSpecs fail closed), order-insensitive,
    duplicate-free in name and SpecPin, ordered by stable SpecPin key."""
    try:
        items = tuple(feature_specs)
    except TypeError as exc:
        raise FeatureExecutionError(
            "feature_specs must be an iterable of FeatureSpec instances, "
            f"got {type(feature_specs).__name__}"
        ) from exc
    for item in items:
        if not isinstance(item, FeatureSpec):
            raise FeatureExecutionError(
                "feature_specs must contain FeatureSpec instances only; "
                f"LabelSpecs are not executed by this PR, got "
                f"{type(item).__name__}"
            )
    names = [spec.name for spec in items]
    if len(set(names)) != len(names):
        raise FeatureExecutionError(
            "feature_specs must not contain duplicate spec names"
        )
    pins = [feature_label_spec_pin(spec) for spec in items]
    pin_keys = [(pin.kind, pin.name, pin.version, pin.content_sha256) for pin in pins]
    if len(set(pin_keys)) != len(pin_keys):
        raise FeatureExecutionError(
            "feature_specs must not contain duplicate SpecPins"
        )
    ordered = sorted(zip(items, pins), key=lambda pair: (pair[1].kind, pair[1].name, pair[1].version, pair[1].content_sha256))
    return tuple(item for item, _ in ordered)


def _verify_pin_binding(pit_result: PITAssemblyResult, builds_by_id: dict) -> None:
    """The PIT result's CanonicalBuildPins must correspond exactly to the
    supplied builds: identical build ids, identical identity fields, and
    pin row-version sets covered by the build's declared provenance. No
    "newest build", mtime, or input order ever picks a winner."""
    pins = tuple(pit_result.canonical_build_pins)
    pin_ids = {pin.canonical_build_id for pin in pins}
    build_ids = set(builds_by_id)
    if pin_ids != build_ids:
        raise FeatureExecutionError(
            "pit_result canonical_build_pins must correspond exactly to the "
            f"supplied builds; pinned {sorted(pin_ids)} vs supplied "
            f"{sorted(build_ids)}"
        )
    for pin in pins:
        build = builds_by_id[pin.canonical_build_id]
        for field in (
            "canonical_content_id",
            "canonical_builder_version",
            "canonical_schema_version",
            "materializer_version",
            "gap_policy_version",
            "gap_content_id",
            "status",
        ):
            if getattr(pin, field) != getattr(build, field):
                raise FeatureExecutionError(
                    f"canonical build pin {pin.canonical_build_id} field "
                    f"{field!r} does not match the supplied build"
                )
        if not set(pin.canonical_row_version_ids).issubset(
            set(build.canonical_row_version_ids)
        ):
            raise FeatureExecutionError(
                f"canonical build pin {pin.canonical_build_id} declares row "
                "versions not covered by the supplied build's provenance"
            )


def _reconcile_rows(build_items: tuple) -> dict[str, _ResolvedRow]:
    """Deterministic row-version binding across the supplied builds.

    Every bar must be covered by its build's declared row-version set, and
    every declared version must have a bar. Identical rows across builds
    deduplicate deterministically (the build-id sets are merged); the same
    version id with conflicting content fails closed — the "newest build",
    mtime, and input order never select a winner.
    """
    reconciled: dict[str, _ResolvedRow] = {}
    for build in build_items:
        declared = set(build.canonical_row_version_ids)
        bar_versions = [bar.canonical_row_version_id for bar in build.bars]
        if len(set(bar_versions)) != len(bar_versions):
            raise FeatureExecutionError(
                f"build {build.canonical_build_id} contains duplicate bar "
                "canonical_row_version_id values"
            )
        if set(bar_versions) != declared:
            raise FeatureExecutionError(
                f"build {build.canonical_build_id} bars do not match its "
                "declared canonical row-version provenance exactly"
            )
        for bar in build.bars:
            existing = reconciled.get(bar.canonical_row_version_id)
            if existing is None:
                reconciled[bar.canonical_row_version_id] = _ResolvedRow(
                    bar=bar, build_ids=(build.canonical_build_id,)
                )
            else:
                if _row_comparator(existing.bar) != _row_comparator(bar):
                    raise FeatureExecutionError(
                        f"conflicting canonical rows for row version id "
                        f"{bar.canonical_row_version_id}: identical row "
                        "versions from different builds disagree; no silent "
                        "winner is allowed"
                    )
                reconciled[bar.canonical_row_version_id] = _ResolvedRow(
                    bar=existing.bar,
                    build_ids=tuple(
                        sorted(set(existing.build_ids) | {build.canonical_build_id})
                    ),
                )
    return reconciled


# ---------------------------------------------------------------------------
# Callable contract.
# ---------------------------------------------------------------------------


def _validate_callable_contract(registration: TransformRegistration) -> None:
    """Validate the v1 invocation contract of a built-in transform before
    any invocation: a plain module-level function with exactly one
    positional parameter and no defaults, non-async, non-generator."""
    implementation = registration.implementation
    if not isinstance(implementation, types.FunctionType):
        raise FeatureExecutionError(
            f"registration {registration.transform_ref!r} implementation must "
            "be a plain module-level function"
        )
    if (
        inspect.isgeneratorfunction(implementation)
        or inspect.iscoroutinefunction(implementation)
        or inspect.isasyncgenfunction(implementation)
    ):
        raise FeatureExecutionError(
            f"registration {registration.transform_ref!r} implementation must "
            "be a plain synchronous non-generator function"
        )
    try:
        signature = inspect.signature(implementation)
    except (TypeError, ValueError) as exc:
        raise FeatureExecutionError(
            f"cannot inspect the signature of registration "
            f"{registration.transform_ref!r}: {exc}"
        ) from exc
    parameters = list(signature.parameters.values())
    if len(parameters) != 1:
        raise FeatureExecutionError(
            f"registration {registration.transform_ref!r} implementation must "
            f"accept exactly one positional parameter, got {len(parameters)}"
        )
    parameter = parameters[0]
    if parameter.kind not in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    ):
        raise FeatureExecutionError(
            f"registration {registration.transform_ref!r} implementation "
            "parameter must be positional"
        )
    if parameter.default is not inspect.Parameter.empty:
        raise FeatureExecutionError(
            f"registration {registration.transform_ref!r} implementation "
            "parameter must not carry a default value"
        )


# ---------------------------------------------------------------------------
# Per-value execution.
# ---------------------------------------------------------------------------


def _required_row_count(spec: FeatureSpec, resolved) -> int:
    """The actual row count the transform consumes: the resolved lookback in
    bars (PARAMETER or FIXED), or one row when no lookback is declared."""
    lookback = resolved.registration.lookback
    if lookback.source == WINDOW_SOURCE_NONE:
        return 1
    if lookback.source == WINDOW_SOURCE_FIXED:
        if type(lookback.value) is not int or lookback.value < 1:
            raise FeatureExecutionError(
                f"registration {resolved.registration.transform_ref!r} has an "
                "invalid FIXED lookback"
            )
        return lookback.value
    if lookback.source == WINDOW_SOURCE_PARAMETER:
        for parameter in resolved.parameters:
            if parameter.name == lookback.parameter_name:
                value = parameter.value
                if type(value) is not int or value < 1:
                    raise FeatureExecutionError(
                        f"spec {spec.name!r} window parameter "
                        f"{lookback.parameter_name!r} must be a real positive "
                        f"int, got {value!r}"
                    )
                return value
        raise FeatureExecutionError(
            f"registration {resolved.registration.transform_ref!r} references "
            f"window parameter {lookback.parameter_name!r}, which is absent "
            "from the spec parameters"
        )
    raise FeatureExecutionError(
        f"registration {resolved.registration.transform_ref!r} declares an "
        "unsupported lookback source for Feature execution"
    )


def _validate_row(
    sample: PITSample,
    spec: FeatureSpec,
    resolved_row: _ResolvedRow,
    builds_by_id: dict,
) -> None:
    """Defensive per-row invariant checks. The PIT assembler has already
    performed the legal selection; any violation here is an inconsistency
    and fails closed — it is never treated as a warm-up EXCLUDED."""
    bar = resolved_row.bar
    request = sample.request
    version = bar.canonical_row_version_id
    sample_label = f"sample {sample.sample_key!r}"
    if bar.code != request.code:
        raise FeatureExecutionError(
            f"row version {version} of {sample_label} carries code "
            f"{bar.code!r}, expected {request.code!r}"
        )
    if bar.interval != request.interval:
        raise FeatureExecutionError(
            f"row version {version} of {sample_label} carries interval "
            f"{bar.interval!r}, expected {request.interval!r}"
        )
    if bar.adjustment != request.adjustment:
        raise FeatureExecutionError(
            f"row version {version} of {sample_label} carries adjustment "
            f"{bar.adjustment!r}, expected {request.adjustment!r}"
        )
    if bar.requested_session != request.requested_session:
        raise FeatureExecutionError(
            f"row version {version} of {sample_label} carries requested "
            f"session {bar.requested_session!r}, expected "
            f"{request.requested_session!r}"
        )
    if not (
        request.feature_window_start <= bar.event_time < request.feature_window_close
    ):
        raise FeatureExecutionError(
            f"row version {version} of {sample_label} has event_time "
            f"{bar.event_time}, outside the feature window "
            f"[{request.feature_window_start}, {request.feature_window_close})"
        )
    if bar.market_available_at > request.feature_window_close:
        raise FeatureExecutionError(
            f"row version {version} of {sample_label} has market_available_at "
            f"{bar.market_available_at}, after the feature window close "
            f"{request.feature_window_close}"
        )
    if sample.dataset_as_of is not None and bar.archive_available_at > sample.dataset_as_of:
        raise FeatureExecutionError(
            f"row version {version} of {sample_label} has archive_available_at "
            f"{bar.archive_available_at}, after dataset_as_of "
            f"{sample.dataset_as_of}"
        )
    if bar.source_schema_version not in spec.requirements.source_schema_versions:
        raise FeatureExecutionError(
            f"row version {version} of {sample_label} carries source schema "
            f"version {bar.source_schema_version!r}, not declared by spec "
            f"{spec.name!r} requirements"
        )
    for build_id in resolved_row.build_ids:
        build = builds_by_id[build_id]
        if build.canonical_schema_version not in spec.requirements.canonical_schema_versions:
            raise FeatureExecutionError(
                f"row version {version} of {sample_label} comes from build "
                f"{build_id} with canonical schema version "
                f"{build.canonical_schema_version!r}, not declared by spec "
                f"{spec.name!r} requirements"
            )


def _exclusion(
    registration: TransformRegistration,
    spec_name: str,
    sample_key: str,
    reason: str,
) -> str:
    """missing_policy EXCLUDE_SAMPLE records an explicit EXCLUDED result
    (returning the fixed reason code); missing_policy FAIL fails closed.
    Exclusions are explicit designed outcomes, never silent fabrication."""
    if registration.missing_policy == MISSING_POLICY_FAIL:
        raise FeatureExecutionError(
            f"spec {spec_name!r} of sample {sample_key!r} cannot satisfy its "
            f"window requirement: {reason}"
        )
    if registration.missing_policy != MISSING_POLICY_EXCLUDE_SAMPLE:
        raise FeatureExecutionError(
            f"registration {registration.transform_ref!r} declares unsupported "
            f"missing policy {registration.missing_policy!r} for Feature "
            "execution"
        )
    return reason


def _trailing_window(
    sample: PITSample,
    spec: FeatureSpec,
    resolved,
    rows: list[_ResolvedRow],
    versions: tuple[str, ...],
) -> tuple[list[_ResolvedRow], tuple[str, ...], str | None]:
    """Select the actual trailing ``required_row_count`` rows in the PIT
    position order, enforcing interval contiguity and the
    SAME_MARKET_CALENDAR_DATE boundary policy.

    Returns the consumed rows, their version ids (the available trailing
    subset — recorded as consumed provenance even on exclusion), and the
    exclusion reason code, or None when the window is usable.
    """
    required = _required_row_count(spec, resolved)
    if len(rows) < required:
        reason = _exclusion(
            resolved.registration,
            spec.name,
            sample.sample_key,
            FEATURE_EXCLUSION_INSUFFICIENT_ROWS,
        )
        return [], (), reason
    consumed = rows[-required:]
    consumed_versions = versions[-required:]
    if required > 1:
        try:
            interval = parse_intraday_interval(sample.request.interval)
        except ValueError as exc:
            raise FeatureExecutionError(
                f"sample {sample.sample_key!r} interval "
                f"{sample.request.interval!r} is not parseable: {exc}"
            ) from exc
        previous = consumed[0].bar
        for row in consumed[1:]:
            bar = row.bar
            if bar.event_time - previous.event_time != interval:
                reason = _exclusion(
                    resolved.registration,
                    spec.name,
                    sample.sample_key,
                    FEATURE_EXCLUSION_NON_CONTIGUOUS_ROWS,
                )
                return [], consumed_versions, reason
            previous = bar
    for row in consumed:
        bar = row.bar
        if bar.market_calendar_date != sample.request.anchor_market_calendar_date:
            reason = _exclusion(
                resolved.registration,
                spec.name,
                sample.sample_key,
                FEATURE_EXCLUSION_CROSS_MARKET_DATE,
            )
            return [], consumed_versions, reason
    return consumed, consumed_versions, None


def _bar_input_row(bar, field_names: tuple[str, ...]) -> tuple[float, ...]:
    """One row of finite float64 values in the registration's authoritative
    field order; undeclared fields are never exposed to a transform."""
    values = []
    for field in field_names:
        if field not in _CANONICAL_INPUT_FIELDS:
            raise FeatureExecutionError(
                f"input canonical field {field!r} is not a consumable Canonical "
                "market float field"
            )
        value = getattr(bar, field)
        if type(value) is not float:
            raise FeatureExecutionError(
                f"canonical field {field!r} value of row "
                f"{bar.canonical_row_version_id} is not a real float64 value, "
                f"got {type(value).__name__}"
            )
        values.append(value)
    return tuple(values)


def _validate_output_value(value, spec: FeatureSpec, registration) -> float:
    """Output contract validation: the transform must return a real finite
    float (bool/int never masquerade as float64), normalized so negative
    zero becomes ordinary zero, matching the registration and spec output
    contracts. No automatic conversion or rounding ever happens."""
    if type(value) is not float:
        raise FeatureExecutionError(
            f"transform {registration.transform_ref!r} for spec {spec.name!r} "
            f"returned {type(value).__name__}, expected a real float64 value"
        )
    if value != value or value in (float("inf"), float("-inf")):
        raise FeatureExecutionError(
            f"transform {registration.transform_ref!r} for spec {spec.name!r} "
            "returned NaN or infinity; non-finite output fails the build"
        )
    value = 0.0 if value == 0.0 else value
    if registration.output_logical_type != "float64" or registration.output_nullable:
        raise FeatureExecutionError(
            f"registration {registration.transform_ref!r} output contract "
            "must be non-nullable float64 for built-in Feature execution"
        )
    if (
        spec.output.logical_type != registration.output_logical_type
        or spec.output.nullable != registration.output_nullable
    ):
        raise FeatureExecutionError(
            f"spec {spec.name!r} output contract does not match registration "
            f"{registration.transform_ref!r}"
        )
    return value


def _execute_feature_value(
    sample: PITSample,
    spec: FeatureSpec,
    resolved,
    rows_by_version: dict,
    builds_by_id: dict,
) -> tuple[FeatureValueResult, bool]:
    """Compute one Feature value of one sample, returning the value result
    and whether the transform was invoked (exactly once per COMPLETE value,
    never for EXCLUDED)."""
    registration = resolved.registration
    versions = sample.feature_canonical_row_version_ids
    rows: list[_ResolvedRow] = []
    for version in versions:
        resolved_row = rows_by_version.get(version)
        if resolved_row is None:
            raise FeatureExecutionError(
                f"sample {sample.sample_key!r} references canonical row "
                f"version {version}, which no supplied build contains"
            )
        rows.append(resolved_row)
    for resolved_row in rows:
        _validate_row(sample, spec, resolved_row, builds_by_id)
    # Position binding: the PIT position order must be strictly ascending in
    # event_time; duplicates and inversions are provenance inconsistencies.
    for previous, current in zip(rows, rows[1:]):
        if current.bar.event_time <= previous.bar.event_time:
            raise FeatureExecutionError(
                f"rows of sample {sample.sample_key!r} are not in strictly "
                "ascending event_time order"
            )

    consumed, consumed_versions, reason = _trailing_window(
        sample, spec, resolved, rows, versions
    )
    if reason is not None:
        return (
            FeatureValueResult(
                feature_name=spec.name,
                spec_pin=feature_label_spec_pin(spec),
                implementation_pin=resolved.pin,
                status=FEATURE_VALUE_STATUS_EXCLUDED,
                value=None,
                reason_code=reason,
                consumed_canonical_row_version_ids=consumed_versions,
            ),
            False,
        )

    input_rows = tuple(
        _bar_input_row(row.bar, registration.input_canonical_fields)
        for row in consumed
    )
    transform_input = FeatureTransformInput(
        field_names=registration.input_canonical_fields,
        rows=input_rows,
        parameters=resolved.parameters,
    )
    try:
        value = registration.implementation(transform_input)
    except Exception as exc:
        raise FeatureExecutionError(
            f"transform {registration.transform_ref!r} for spec {spec.name!r} "
            f"of sample {sample.sample_key!r} failed: {exc}"
        ) from exc
    value = _validate_output_value(value, spec, registration)
    return (
        FeatureValueResult(
            feature_name=spec.name,
            spec_pin=feature_label_spec_pin(spec),
            implementation_pin=resolved.pin,
            status=FEATURE_VALUE_STATUS_COMPLETE,
            value=value,
            reason_code=None,
            consumed_canonical_row_version_ids=consumed_versions,
        ),
        True,
    )
