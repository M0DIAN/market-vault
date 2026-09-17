"""Explicit in-memory TS2 Feature execution, without PIT winner selection."""

from dataclasses import dataclass, fields, replace
from datetime import date, datetime, timedelta

from ..canonical.models import CanonicalBar
from ..canonical.reader import VerifiedCanonicalBuild, VerifiedCanonicalRequest, _validate_normalized_request
from ..cross_day import _authority as authority
from ..dataset.feature_models import FeatureTransformInput
from ..dataset.models import DatasetField
from ..dataset.pit_models import PITAssemblyResult, PITSample, PITSampleRequest
from ..dataset.spec_models import FeatureSpec, SpecParameter, SpecVersionRequirements
from ..dataset.specs import feature_label_spec_pin
from ._validation import TS2FeatureError, require, instant, finite_float
from . import identity as ids
from .models import TS2FeatureExecutionResult, TS2FeatureSampleResult, TS2FeatureValueResult
from .registry import (
    _registry, SOURCE_SCHEMA_VERSION, CANONICAL_SCHEMA_VERSION,
    TS2_FEATURE_EXECUTION_CONTRACT_VERSION, TS2_FEATURE_REGISTRY_CONTRACT_VERSION,
)


def _specs(values):
    require(type(values) is tuple, "SPEC_CONTRACT", "explicit FeatureSpec tuple required")
    copies = []
    for spec in values:
        require(type(spec) is FeatureSpec and spec.kind == "FEATURE", "SPEC_CONTRACT", "exact FeatureSpec required")
        require(type(spec.output) is DatasetField and type(spec.requirements) is SpecVersionRequirements
                and type(spec.parameters) is tuple and all(type(p) is SpecParameter for p in spec.parameters),
                "SPEC_CONTRACT", "exact immutable nested spec records required")
        try:
            copy = replace(spec, output=replace(spec.output), requirements=replace(spec.requirements),
                           parameters=tuple(replace(p) for p in spec.parameters))
        except (ValueError, TypeError) as exc:
            raise TS2FeatureError("SPEC_CONTRACT", "invalid FeatureSpec") from exc
        require(copy.requirements.canonical_schema_versions == (CANONICAL_SCHEMA_VERSION,)
                and copy.requirements.source_schema_versions == (SOURCE_SCHEMA_VERSION,),
                "SOURCE_COHORT", "exact TS2 spec requirements required")
        copies.append(copy)
    require(len({s.name for s in copies}) == len(copies), "DUPLICATE_INPUT", "duplicate normalized Feature name")
    return tuple(sorted(copies, key=lambda s: ids.spec_pin_id(feature_label_spec_pin(s))))


def _resolve(specs, registrations):
    by_ref = {r.contract.transform_ref: r for r in registrations}
    resolved = []
    for spec in specs:
        reg = by_ref.get(spec.transform_ref)
        require(reg is not None, "REGISTRY_AUTHORITY", "unknown fixed transform reference")
        contract = reg.contract
        require(spec.input_canonical_fields == contract.fields and spec.output.name == spec.name
                and spec.output.logical_type == "float64" and spec.output.nullable is False,
                "SPEC_CONTRACT", "input/output contract mismatch")
        if contract.minimum is None:
            require(spec.parameters == (), "SPEC_CONTRACT", "fixed N=1 transform has no parameters")
            count = 1
        else:
            require(len(spec.parameters) == 1 and spec.parameters[0].name == "window_bars",
                    "SPEC_CONTRACT", "exact window_bars parameter required")
            count = spec.parameters[0].value
            require(type(count) is int and contract.minimum <= count <= 9223372036854775807,
                    "SPEC_CONTRACT", "window_bars must meet signed int64 bounds")
        resolved.append((spec, reg, count))
    return tuple(resolved)


def _builds(values):
    require(type(values) is tuple and all(type(b) is VerifiedCanonicalBuild for b in values),
            "CANONICAL_AUTHORITY", "exact VerifiedCanonicalBuild tuple required")
    require(len({b.canonical_build_id for b in values}) == len(values), "DUPLICATE_INPUT", "duplicate Canonical build")
    for build in values:
        request = build.normalized_request
        require(type(request) is VerifiedCanonicalRequest and type(build.bars) is tuple
                and all(type(b) is CanonicalBar for b in build.bars),
                "CANONICAL_AUTHORITY", "invalid typed Canonical evidence")
        require(request.source_schema_version == SOURCE_SCHEMA_VERSION
                and build.canonical_schema_version == CANONICAL_SCHEMA_VERSION
                and all(b.source_schema_version == SOURCE_SCHEMA_VERSION for b in build.bars),
                "SOURCE_COHORT", "TS2-only Canonical authority required")
        require(request.interval in authority.INTERVAL_MINUTES and request.requested_session == "RTH"
                and request.adjustment == "NONE" and type(request.symbols) is tuple
                and all(type(s) is str and s.startswith("US.") for s in request.symbols)
                and all(b.session == b.requested_session == "RTH" and b.adjustment == "NONE" for b in build.bars),
                "SCOPE", "unsupported Canonical scope")
        require(type(request.trade_dates) is tuple and all(type(d) is date for d in request.trade_dates),
                "CANONICAL_AUTHORITY", "exact immutable Canonical request dates required")
        try:
            canonical_request = _validate_normalized_request(dict(
                symbols=list(request.symbols), trade_dates=[d.isoformat() for d in request.trade_dates],
                interval=request.interval, requested_session=request.requested_session,
                adjustment=request.adjustment, source_schema_version=request.source_schema_version))
        except (ValueError, TypeError) as exc:
            raise TS2FeatureError("CANONICAL_AUTHORITY", "noncanonical request declaration") from exc
        require(canonical_request == request, "CANONICAL_AUTHORITY", "Canonical request reconstruction mismatch")
    try:
        admitted = authority.admit_builds(values)
    except (ValueError, TypeError, OverflowError) as exc:
        raise TS2FeatureError("CANONICAL_AUTHORITY", "Canonical evidence reconstruction failed") from exc
    try:
        rows = authority.reconcile(admitted)
    except (ValueError, TypeError) as exc:
        raise TS2FeatureError("CANONICAL_CONFLICT", "conflicting supplied candidates before clocks") from exc
    return admitted, rows


def _pit(value, builds, rows, cutoff):
    require(type(value) is PITAssemblyResult and type(value.samples) is tuple,
            "PIT_AUTHORITY", "exact Feature-only PIT required")
    require(all(type(s) is PITSample and type(s.request) is PITSampleRequest for s in value.samples),
            "PIT_AUTHORITY", "exact sample/request records required")
    require(len({s.sample_key for s in value.samples}) == len(value.samples),
            "DUPLICATE_INPUT", "duplicate Feature sample")
    for sample in sorted(value.samples, key=lambda s: s.sample_key):
        req = sample.request
        require(req.label_window is None and sample.label_canonical_row_version_ids == (),
                "PIT_AUTHORITY", "Label selection is forbidden")
        require(req.interval in authority.INTERVAL_MINUTES and req.code.startswith("US.")
                and req.adjustment == "NONE" and req.requested_session == "RTH", "SCOPE", "unsupported Feature scope")
        start, close = instant(req.feature_window_start), instant(req.feature_window_close)
        require((None if sample.dataset_as_of is None else instant(sample.dataset_as_of)) == cutoff,
                "CLOCK_AUTHORITY", "sample/invocation archive cutoff mismatch")
        require(type(sample.feature_canonical_row_version_ids) is tuple
                and len(set(sample.feature_canonical_row_version_ids)) == len(sample.feature_canonical_row_version_ids),
                "PIT_AUTHORITY", "invalid selected version sequence")
        for version in sample.feature_canonical_row_version_ids:
            require(version in rows, "PIT_AUTHORITY", "selected version absent from exact evidence")
            bar = rows[version].bar
            require((bar.code, bar.interval, bar.adjustment, bar.requested_session, bar.market_calendar_date) ==
                    (req.code, req.interval, req.adjustment, req.requested_session, req.anchor_market_calendar_date),
                    "SCOPE", "selected row/request scope mismatch")
            require(start <= instant(bar.event_time) < close and instant(bar.market_available_at) <= close
                    and (cutoff is None or instant(bar.archive_available_at) <= cutoff),
                    "CLOCK_AUTHORITY", "selected Feature row violates clocks")
    try:
        admitted, _ = authority.admit_feature_pit(value, builds, cutoff)
    except (ValueError, TypeError, OverflowError) as exc:
        raise TS2FeatureError("PIT_AUTHORITY", "Feature PIT identity/provenance closure failed") from exc
    return admitted


@dataclass(frozen=True, slots=True)
class _Plan:
    sample: PITSample
    spec: FeatureSpec
    registration: object
    candidates: tuple[str, ...]
    inputs: tuple[tuple[float, ...], ...]
    reason: str | None


def _plans(pit, resolved, rows):
    plans = []
    for sample in sorted(pit.samples, key=lambda s: s.sample_key):
        versions = sample.feature_canonical_row_version_ids
        selected = tuple(rows[v].bar for v in versions)
        for spec, reg, count in resolved:
            # Validate all selected inputs even when the eventual tail is excluded.
            inputs = tuple(tuple(finite_float(getattr(b, name), "CANONICAL_AUTHORITY")
                                 for name in reg.contract.fields) for b in selected)
            available = min(count, len(versions))
            candidates = versions[-available:] if available else ()
            reason = "INSUFFICIENT_ROWS" if len(versions) < count else None
            if reason is None:
                tail = selected[-available:]
                interval = timedelta(minutes=authority.INTERVAL_MINUTES[sample.request.interval])
                if any(b.event_time - a.event_time != interval for a, b in zip(tail, tail[1:])):
                    reason = "NON_CONTIGUOUS_ROWS"
            plans.append(_Plan(sample, spec, reg, candidates, () if reason else inputs[-available:], reason))
    return tuple(plans)


def _invoke(registration, input_):
    return registration.contract.implementation(input_)


def execute_ts2_features(
    builds: tuple[VerifiedCanonicalBuild, ...],
    pit_result: PITAssemblyResult,
    feature_specs: tuple[FeatureSpec, ...],
    *, dataset_as_of: datetime | None,
) -> TS2FeatureExecutionResult:
    """Issue TS2 Feature facts from exact in-memory authority, never re-select PIT."""
    specs = _specs(feature_specs)
    registrations = _registry()
    resolved = _resolve(specs, registrations)
    cutoff = None if dataset_as_of is None else instant(dataset_as_of)
    admitted_builds, rows = _builds(builds)
    pit = _pit(pit_result, admitted_builds, rows, cutoff)
    plans = _plans(pit, resolved, rows)

    # Only this invocation can obtain its context; no issuer/token/factory escapes.
    @dataclass(frozen=True, slots=True)
    class _IssuanceContext:
        builds: tuple
        pit: PITAssemblyResult
        specs: tuple
        registrations: tuple
        plans: tuple
        outcomes: tuple

    context = _IssuanceContext(admitted_builds, pit, specs, registrations, plans, ())
    outcomes = []
    for plan in context.plans:
        value = None
        if plan.reason is None:
            transport = FeatureTransformInput(plan.registration.contract.fields, plan.inputs, plan.spec.parameters)
            try:
                value = _invoke(plan.registration, transport)
            except (ValueError, ArithmeticError) as exc:
                raise TS2FeatureError("TRANSFORM_DOMAIN", plan.spec.transform_ref) from exc
            value = finite_float(value, "TRANSFORM_OUTPUT")
        outcomes.append(value)
    context = replace(context, outcomes=tuple(outcomes))

    def issue(cls, **payload):
        require(set(payload) == {f.name for f in fields(cls)}, "RESULT_AUTHORITY", "issued field set mismatch")
        result = object.__new__(cls)
        for name, value in payload.items():
            object.__setattr__(result, name, value)
        return result

    build_ids = tuple(b.canonical_build_id for b in context.builds)
    values = {}
    for plan, outcome in zip(context.plans, context.outcomes):
        value = issue(TS2FeatureValueResult,
            sample_key=plan.sample.sample_key, bar_sample_version_id=plan.sample.sample_version_id,
            feature_name=plan.spec.name, spec_pin=feature_label_spec_pin(plan.spec), implementation_pin=plan.registration.pin,
            feature_window_close=instant(plan.sample.request.feature_window_close), dataset_as_of=cutoff,
            considered_canonical_build_ids=build_ids, candidate_canonical_row_version_ids=plan.candidates,
            consumed_canonical_row_version_ids=() if plan.reason else plan.candidates,
            status="EXCLUDED" if plan.reason else "COMPLETE", value=outcome, reason_code=plan.reason)
        values.setdefault(plan.sample.sample_key, []).append(value)
    samples = []
    for sample in sorted(context.pit.samples, key=lambda s: s.sample_key):
        entries = tuple(values.get(sample.sample_key, ()))
        samples.append(issue(TS2FeatureSampleResult, sample_key=sample.sample_key,
            bar_sample_version_id=sample.sample_version_id, values=entries,
            status="COMPLETE" if all(v.status == "COMPLETE" for v in entries) else "EXCLUDED"))
    result = issue(TS2FeatureExecutionResult,
        execution_contract_version=TS2_FEATURE_EXECUTION_CONTRACT_VERSION,
        registry_contract_version=TS2_FEATURE_REGISTRY_CONTRACT_VERSION,
        feature_association_content_id=context.pit.association_content_id,
        feature_association_schema_id=context.pit.association_schema_id, dataset_as_of=cutoff,
        considered_canonical_build_ids=build_ids, feature_specs=context.specs,
        feature_spec_pins=tuple(feature_label_spec_pin(s) for s in context.specs),
        registry_implementation_pins=tuple(sorted((r.pin for r in context.registrations), key=ids.implementation_pin_id)),
        samples=tuple(samples), status="EMPTY" if not samples else
            "COMPLETE" if all(s.status == "COMPLETE" for s in samples) else "EXCLUDED")
    result.execution_id
    return result
