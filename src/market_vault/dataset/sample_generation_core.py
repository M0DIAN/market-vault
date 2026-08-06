"""Deterministic Sample Generator core (v0.6.0 PR-3).

:func:`generate_sample_requests` consumes one frozen PR-2
:class:`SampleGenerationPlan` and an explicit ``path_base`` and produces the
frozen :class:`SampleGenerationResult`: the deterministic
:class:`PITSampleRequest` sequence for the plan's scope and BARS-style
generation rule.

The pipeline is pure and fail-closed:

1. every ``canonical_build_dirs`` entry is read through the formal verified
   reader (:func:`market_vault.canonical.reader.load_verified_canonical_build`);
2. every Feature / Label file through the formal spec loaders
   (:func:`market_vault.dataset.specs.load_feature_spec` /
   :func:`market_vault.dataset.specs.load_label_spec`) followed by the
   built-in registry preflight;
3. ``split_spec_file`` through a strict JSON reader into the formal
   :class:`ChronologicalSplitSpec`;
4. the BARS window-coverage preflight (Feature lookbacks and Label horizons
   against ``feature_window_bars`` / ``label_window_bars``);
5. the v1 Generation content identity from the verified normalized inputs;
6. deterministic bar filtering, contiguous-segment traversal, stride-based
   candidate anchors, exact window geometry, and formal
   :class:`PITSampleRequest` construction;
7. the canonical stable request order with duplicate rejection.

Path semantics: ``path_base`` must be an explicit absolute path (an empty
or relative ``path_base``, including ``"."``, fails; the current working
directory never participates in input location). Absolute plan paths are
used as-is; relative plan paths are lexically joined to the absolute
``path_base``. ``path_base`` has no implicit default. ``resolve()`` is
never called, no directory is scanned, no ``latest`` is selected, and
``~``, environment variables, and wildcard patterns are never expanded.
``path_base`` and every path never enter the Generation content identity.

The generator defines request windows only: it never executes PIT
assembly, never selects rows, never computes Feature or Label values, never
claims a sample is COMPLETE, never writes any file, and never orchestrates
or materializes a Dataset build. All documented failures surface as
:class:`SampleGenerationError`; broad ``except Exception`` is never used.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from ..canonical.reader import (
    CanonicalArtifactValidationError,
    VerifiedCanonicalBuild,
    load_verified_canonical_build,
)
from ..intraday_audit import parse_intraday_interval
from .encoding import DatasetError
from .execution_provenance import (
    ExecutionProvenanceError,
    normalize_verified_builds,
    reconcile_canonical_rows,
)
from .feature_registry import built_in_feature_registry
from .label_contract import (
    LabelContractError,
    validate_builtin_label_spec_contract,
)
from .label_registry import built_in_label_registry
from .models import CanonicalBuildPin, DatasetScope, SourceSnapshotPin
from .pit_identity import pit_sample_key
from .pit_models import PITSampleRequest
from .sample_generation import sample_generation_content_id
from .sample_generation_core_models import (
    SAMPLE_GENERATOR_CORE_VERSION,
    SampleGenerationDiagnostics,
    SampleGenerationResult,
    _request_sort_key,
)
from .sample_generation_models import (
    SampleGenerationError,
    SampleGenerationIdentityInput,
    SampleGenerationPlan,
    SampleGenerationRule,
)
from .spec_models import SpecValidationError
from .specs import feature_label_spec_pin, load_feature_spec, load_label_spec
from .split_models import (
    ChronologicalSplitSpec,
    SplitValidationError,
    chronological_split_spec_pin,
)
from .transform_models import (
    WINDOW_SOURCE_FIXED,
    WINDOW_SOURCE_NONE,
    WINDOW_SOURCE_PARAMETER,
    WINDOW_UNIT_BARS,
    TransformRegistryError,
)

__all__ = [
    "generate_sample_requests",
]

#: The exact field set of one strict split-spec JSON document. It mirrors
#: the formal :class:`ChronologicalSplitSpec` model exactly; no second split
#: identity or second schema is introduced.
_SPLIT_FIELDS = frozenset(
    {
        "spec_schema_version",
        "name",
        "version",
        "boundary_timezone",
        "train_end_date",
        "validation_end_date",
        "test_end_date",
        "assignment_rule",
        "purge_rule",
        "incomplete_label_policy",
        "out_of_range_policy",
    }
)

_STRICT_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: Documented failures converted to :class:`SampleGenerationError` at the
#: core boundary. Only the formal public errors of each layer are listed —
#: no broad ``ValueError`` / ``TypeError`` catch exists, so a programming
#: error inside a formal loader can never be disguised as an input error.
#: ``json.JSONDecodeError`` is a ``ValueError`` subclass and is listed
#: explicitly for contract clarity; ``DatasetError`` (and
#: ``SampleGenerationError``) pass through their own path. Broad ``except
#: Exception`` is never used.
_DOCUMENTED_ERRORS = (
    CanonicalArtifactValidationError,
    SpecValidationError,
    TransformRegistryError,
    SplitValidationError,
    ExecutionProvenanceError,
    LabelContractError,
    OSError,
    UnicodeError,
    json.JSONDecodeError,
)


def _as_generation_error(exc, context: str) -> None:
    """Convert a documented failure to :class:`SampleGenerationError`.

    An already-raised :class:`SampleGenerationError` passes through
    unchanged; the contract-listed exceptions (Canonical artifact
    validation, spec validation, registry preflight, split validation, PIT
    model errors, documented input and arithmetic boundaries) are converted
    with a context prefix and their ``__cause__`` preserved. Real
    programming errors pass through and are never disguised as input
    errors.
    """
    if isinstance(exc, SampleGenerationError):
        raise exc
    if isinstance(exc, _DOCUMENTED_ERRORS):
        raise SampleGenerationError(f"{context}: {exc}") from exc
    raise exc


# ---------------------------------------------------------------------------
# Path resolution (explicit; no filesystem semantics beyond the loader).
# ---------------------------------------------------------------------------


def _coerce_path_base(path_base) -> Path:
    """The explicit absolute base directory of every relative plan path.

    Only ``str`` or ``Path`` is accepted; an empty string fails; a relative
    ``path_base`` (including ``"."``) fails with
    ``path_base must be an explicit absolute path``. ``resolve()`` is never
    called, the current working directory is never used implicitly, and
    nothing is completed, expanded, or normalized against the current
    directory. The returned path is lexically absolute.
    """
    if isinstance(path_base, Path):
        value = path_base
    elif isinstance(path_base, str):
        value = Path(path_base)
    else:
        raise SampleGenerationError(
            f"path_base must be a str or Path, got {type(path_base).__name__}"
        )
    if not value.is_absolute():
        raise SampleGenerationError(
            "path_base must be an explicit absolute path"
        )
    return value


def _resolve_path(raw: str, base: Path, label: str) -> Path:
    """Absolute plan paths are used as-is; relative paths are lexically
    joined to the absolute ``base``. ``resolve()`` is never called and
    nothing is expanded. This layer makes no claim about how the operating
    system opens files."""
    path = Path(raw)
    if not path.is_absolute():
        path = base / path
    return path


# ---------------------------------------------------------------------------
# Strict split-spec JSON loading.
# ---------------------------------------------------------------------------


def _no_duplicate_pairs(pairs) -> dict:
    """``object_pairs_hook`` rejecting duplicate JSON keys at any depth."""
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise SampleGenerationError(
                f"duplicate JSON key {key!r} in split spec"
            )
        result[key] = value
    return result


def _require_string(value, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SampleGenerationError(
            f"{label} must be a non-empty string, got {value!r}"
        )
    return value


def _require_date(value, label: str) -> date:
    text = _require_string(value, label)
    if not _STRICT_ISO_DATE_RE.fullmatch(text):
        raise SampleGenerationError(
            f"{label} must be a strict ISO YYYY-MM-DD string, got {value!r}"
        )
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise SampleGenerationError(
            f"{label} must be a valid calendar date, got {value!r}"
        ) from exc


def _load_split_spec(path: Path) -> ChronologicalSplitSpec:
    """Strictly read one split-spec JSON document into the formal
    :class:`ChronologicalSplitSpec`.

    The document must be a single UTF-8 JSON object without BOM; duplicate
    keys fail at any depth; the root must be an object with exactly the
    formal split-spec field set; unknown and missing fields fail; dates are
    strict ``YYYY-MM-DD``. Final semantics (schema version, timezone,
    boundary ordering, fixed rule values) are validated by the formal
    :class:`ChronologicalSplitSpec` construction. The split pin is produced
    by the existing :func:`chronological_split_spec_pin`; no second split
    identity exists.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeError) as exc:
        raise SampleGenerationError(f"cannot read split spec file {path}: {exc}") from exc
    if text.startswith("﻿"):
        raise SampleGenerationError("split spec file must not carry a UTF-8 BOM")
    try:
        data = json.loads(text, object_pairs_hook=_no_duplicate_pairs)
    except json.JSONDecodeError as exc:
        raise SampleGenerationError(f"split spec is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SampleGenerationError(
            f"split spec root must be a JSON object, got {type(data).__name__}"
        )
    unknown = sorted(key for key in data if key not in _SPLIT_FIELDS)
    if unknown:
        raise SampleGenerationError(
            f"unknown field(s) in split spec: {', '.join(unknown)}"
        )
    missing = sorted(_SPLIT_FIELDS - set(data))
    if missing:
        raise SampleGenerationError(
            f"missing required field(s) in split spec: {', '.join(missing)}"
        )
    try:
        spec = ChronologicalSplitSpec(
            spec_schema_version=_require_string(
                data["spec_schema_version"], "split spec spec_schema_version"
            ),
            name=_require_string(data["name"], "split spec name"),
            version=_require_string(data["version"], "split spec version"),
            boundary_timezone=_require_string(
                data["boundary_timezone"], "split spec boundary_timezone"
            ),
            train_end_date=_require_date(
                data["train_end_date"], "split spec train_end_date"
            ),
            validation_end_date=_require_date(
                data["validation_end_date"], "split spec validation_end_date"
            ),
            test_end_date=_require_date(
                data["test_end_date"], "split spec test_end_date"
            ),
            assignment_rule=_require_string(
                data["assignment_rule"], "split spec assignment_rule"
            ),
            purge_rule=_require_string(data["purge_rule"], "split spec purge_rule"),
            incomplete_label_policy=_require_string(
                data["incomplete_label_policy"], "split spec incomplete_label_policy"
            ),
            out_of_range_policy=_require_string(
                data["out_of_range_policy"], "split spec out_of_range_policy"
            ),
        )
    except SplitValidationError:
        raise
    except (DatasetError, TypeError, ValueError, KeyError) as exc:
        raise SampleGenerationError(f"invalid split spec: {exc}") from exc
    return spec


# ---------------------------------------------------------------------------
# Pins from verified inputs (never from paths, mtimes, or created_at).
# ---------------------------------------------------------------------------


def _canonical_build_pin(build: VerifiedCanonicalBuild) -> CanonicalBuildPin:
    """Map one verified build to the existing :class:`CanonicalBuildPin`.

    Only verified fields are mapped; identities are never derived from the
    directory name, paths, mtimes, or the manifest ``created_at``.
    """
    snapshots = tuple(
        SourceSnapshotPin(
            ingestion_run_id=ref.ingestion_run_id,
            physical_snapshot_hash=ref.physical_snapshot_hash,
            logical_source_rows_hash=ref.logical_source_rows_hash,
            source_schema_version=ref.source_schema_version,
            requested_trade_date=ref.requested_trade_date,
            requested_session=ref.requested_session,
        )
        for ref in build.source_snapshot_provenance
    )
    return CanonicalBuildPin(
        canonical_build_id=build.canonical_build_id,
        canonical_content_id=build.canonical_content_id,
        canonical_builder_version=build.canonical_builder_version,
        canonical_schema_version=build.canonical_schema_version,
        materializer_version=build.materializer_version,
        gap_policy_version=build.gap_policy_version,
        gap_content_id=build.gap_content_id,
        status=build.status,
        canonical_row_version_ids=build.canonical_row_version_ids,
        source_snapshots=snapshots,
    )


# ---------------------------------------------------------------------------
# BARS window-coverage preflight (registry contract is the authority).
# ---------------------------------------------------------------------------


def _parameter_value(parameters, name: str, label: str) -> int:
    for parameter in parameters:
        if parameter.name == name:
            value = parameter.value
            if type(value) is not int or value <= 0:
                raise SampleGenerationError(
                    f"{label} parameter {name!r} must be a real positive "
                    f"integer, got {value!r}"
                )
            return value
    raise SampleGenerationError(f"{label} parameter {name!r} is not declared")


def _feature_required_bars(spec, resolved) -> int:
    """Required bars of one resolved Feature transform: NONE -> 1, FIXED ->
    the declared BARS lookback value, PARAMETER -> the spec's declared
    positive int parameter. Only BARS units are supported; other sources or
    units fail closed."""
    lookback = resolved.registration.lookback
    if lookback.source == WINDOW_SOURCE_NONE:
        return 1
    if lookback.source == WINDOW_SOURCE_FIXED:
        if lookback.unit != WINDOW_UNIT_BARS:
            raise SampleGenerationError(
                f"feature transform {spec.transform_ref!r} declares a "
                f"non-BARS fixed lookback unit {lookback.unit!r}"
            )
        return lookback.value
    if lookback.source == WINDOW_SOURCE_PARAMETER:
        if lookback.unit != WINDOW_UNIT_BARS:
            raise SampleGenerationError(
                f"feature transform {spec.transform_ref!r} declares a "
                f"non-BARS parameter lookback unit {lookback.unit!r}"
            )
        return _parameter_value(
            resolved.parameters, lookback.parameter_name, f"feature {spec.name!r}"
        )
    raise SampleGenerationError(
        f"unsupported feature lookback source {lookback.source!r} for "
        f"transform {spec.transform_ref!r}"
    )


def _preflight_feature_coverage(feature_specs, rule: SampleGenerationRule) -> int:
    """Every resolved Feature transform's required bars must be covered by
    ``feature_window_bars``; the maximum requirement wins."""
    registry = built_in_feature_registry()
    required = 0
    for spec in feature_specs:
        resolved = registry.resolve_feature_spec(spec)
        required = max(required, _feature_required_bars(spec, resolved))
    if rule.feature_window_bars < required:
        raise SampleGenerationError(
            f"feature_window_bars {rule.feature_window_bars} is smaller than "
            f"the required feature bars {required} of the Feature specs"
        )
    return required


def _preflight_label_coverage(label_specs, rule: SampleGenerationRule) -> int:
    """Every Label spec must pass the shared built-in Label configuration
    contract (alignment rule, observation-window shape, fixed catalog) and
    use the BARS horizon / observation window with no cross-trading-day
    opt-in; the maximum horizon must be covered by ``label_window_bars``."""
    registry = built_in_label_registry()
    required = 0
    for spec in label_specs:
        resolved = registry.resolve_label_spec(spec)
        validate_builtin_label_spec_contract(spec, resolved.registration)
        if spec.horizon.unit != "BARS":
            raise SampleGenerationError(
                f"label spec {spec.name!r} uses unsupported horizon unit "
                f"{spec.horizon.unit!r}; only BARS is supported"
            )
        if spec.observation_window.unit != "BARS":
            raise SampleGenerationError(
                f"label spec {spec.name!r} uses unsupported observation "
                f"window unit {spec.observation_window.unit!r}; only BARS "
                "is supported"
            )
        if spec.cross_trading_day.allow:
            raise SampleGenerationError(
                f"label spec {spec.name!r} enables cross_trading_day, which "
                "is not supported"
            )
        required = max(required, spec.horizon.value)
    if rule.label_window_bars < required:
        raise SampleGenerationError(
            f"label_window_bars {rule.label_window_bars} is smaller than "
            f"the required label bars {required} of the Label specs"
        )
    return required


# ---------------------------------------------------------------------------
# Bar filtering and contiguous segments.
# ---------------------------------------------------------------------------


def _unique_canonical_rows(reconciled) -> tuple:
    """The unique, conflict-free Canonical bar sequence (hardening).

    Every reconciled row version is a distinct verified fact. The same
    ``canonical_bar_key`` must not resolve to multiple row-version facts,
    and the same logical event slot (code, market_calendar_date, session,
    event_time, interval, adjustment, requested_session) must not retain
    two different Canonical bars. A duplicate event time is therefore a
    fail-closed conflict — never a segment boundary, never a silent
    first/last pick, never a build-time or path-based winner.
    """
    bars = [resolved.bar for resolved in reconciled.values()]
    by_key: dict = {}
    for bar in bars:
        existing = by_key.get(bar.canonical_bar_key)
        if existing is not None and existing is not bar:
            raise SampleGenerationError(
                f"canonical_bar_key {bar.canonical_bar_key!r} resolves to "
                "multiple canonical row-version facts; overlapping builds "
                "conflict"
            )
        by_key[bar.canonical_bar_key] = bar
    by_slot: dict = {}
    for bar in bars:
        slot = (
            bar.code,
            bar.market_calendar_date,
            bar.session,
            bar.event_time,
            bar.interval,
            bar.adjustment,
            bar.requested_session,
        )
        existing = by_slot.get(slot)
        if existing is not None and existing is not bar:
            raise SampleGenerationError(
                f"logical event slot {slot!r} retains two different "
                "Canonical bars; overlapping builds conflict"
            )
        by_slot[slot] = bar
    return tuple(bars)


def _in_scope_bars(rows, scope: DatasetScope) -> list:
    """Bars matching the plan scope exactly (B8).

    Other bars are never candidates and never modified; a scope key with no
    bars simply produces no request (the future Dataset build may still
    record the key as MISSING).
    """
    bars = []
    for bar in rows:
        if (
            bar.code in scope.symbols
            and bar.market_calendar_date is not None
            and bar.market_calendar_date in scope.trade_dates
            and bar.interval == scope.interval
            and bar.adjustment == scope.adjustment
            and bar.requested_session == scope.requested_session
        ):
            bars.append(bar)
    return bars


def _contiguous_segments(bars, interval_delta) -> list:
    """Deterministic contiguous segments (B9).

    The stable order is code, market_calendar_date, session, event_time,
    canonical_bar_key, canonical_row_version_id. A segment continues only
    while code, market_calendar_date, session, interval, adjustment, and
    requested_session are unchanged and the event_time delta equals the
    nominal interval exactly. A market-calendar-date change, a session
    change, a non-nominal delta (including duplicate or out-of-order event
    times), or a known or actual gap terminates the segment. Bars are never
    spliced across gaps, sessions, or market-calendar dates, and no missing
    bar is ever replaced by the Nth existing bar.
    """
    sorted_bars = sorted(
        bars,
        key=lambda bar: (
            bar.code,
            bar.market_calendar_date,
            bar.session,
            bar.event_time,
            bar.canonical_bar_key,
            bar.canonical_row_version_id,
        ),
    )
    segments: list[list] = []
    current: list = []
    for bar in sorted_bars:
        if not current:
            current.append(bar)
            continue
        previous = current[-1]
        if (
            bar.code == previous.code
            and bar.market_calendar_date == previous.market_calendar_date
            and bar.session == previous.session
            and bar.interval == previous.interval
            and bar.adjustment == previous.adjustment
            and bar.requested_session == previous.requested_session
            and bar.event_time - previous.event_time == interval_delta
        ):
            current.append(bar)
        else:
            segments.append(current)
            current = [bar]
    if current:
        segments.append(current)
    return segments


# ---------------------------------------------------------------------------
# Window geometry and request construction.
# ---------------------------------------------------------------------------


def _assert_contiguous(slice_bars, interval_delta) -> None:
    for previous, current in zip(slice_bars, slice_bars[1:]):
        if current.event_time - previous.event_time != interval_delta:
            raise SampleGenerationError(
                "window slice is not strictly contiguous at the nominal interval"
            )


def _build_request(
    feature_slice,
    label_slice,
    rule: SampleGenerationRule,
    scope: DatasetScope,
    interval_delta,
) -> PITSampleRequest:
    """Exact half-open window geometry (B11-B12).

    feature_window_start is the first feature bar's event time;
    feature_window_close is the anchor bar's event time plus one nominal
    interval; label_window_start equals feature_window_close; the label
    window is exactly ``label_window_bars`` nominal intervals. Every
    assertion is re-verified so a gap can never silently move a window
    boundary, and all date arithmetic failures are converted to
    :class:`SampleGenerationError`.
    """
    try:
        _assert_contiguous(feature_slice, interval_delta)
        _assert_contiguous(label_slice, interval_delta)
        anchor_bar = feature_slice[-1]
        feature_window_start = feature_slice[0].event_time
        feature_window_close = anchor_bar.event_time + interval_delta
        label_window_start = feature_window_close
        label_window_close = feature_window_close + (
            rule.label_window_bars * interval_delta
        )
        if label_slice[0].event_time != label_window_start:
            raise SampleGenerationError(
                "label slice does not start exactly at feature_window_close"
            )
        if label_slice[-1].event_time + interval_delta != label_window_close:
            raise SampleGenerationError(
                "label slice does not end exactly at label_window_close"
            )
        for bar in (*feature_slice, *label_slice):
            if bar.market_calendar_date != anchor_bar.market_calendar_date:
                raise SampleGenerationError(
                    "a window bar crosses the anchor market-calendar date"
                )
        return PITSampleRequest(
            code=anchor_bar.code,
            interval=scope.interval,
            adjustment=scope.adjustment,
            requested_session=scope.requested_session,
            anchor_market_calendar_date=anchor_bar.market_calendar_date,
            feature_window_start=feature_window_start,
            feature_window_close=feature_window_close,
            label_window_start=label_window_start,
            label_window_close=label_window_close,
        )
    except SampleGenerationError:
        # An explicitly raised generation error (for example the PIT model
        # conversion) passes through unwrapped; it is never re-wrapped as
        # "window geometry arithmetic failed".
        raise
    except (OverflowError, ValueError, TypeError, ZeroDivisionError) as exc:
        raise SampleGenerationError(
            f"window geometry arithmetic failed: {exc}"
        ) from exc


def _generate_requests(segments, rule: SampleGenerationRule, scope: DatasetScope, interval_delta):
    """Stride-based candidate anchors (B10) with exact window geometry.

    The first usable anchor index of every segment is
    ``feature_window_bars - 1``; anchors then advance by ``stride_bars``,
    so each new contiguous segment establishes its own deterministic stride
    origin. A candidate anchor must be a real bar at that position; a
    segment shorter than ``feature_window_bars`` produces no anchor and is
    counted as insufficient feature history; an anchor whose label slice is
    incomplete is counted as insufficient label future and produces no
    request. Windows are never shortened to force a request.
    """
    generated = []
    candidate_anchor_count = 0
    insufficient_feature_history_count = 0
    insufficient_label_future_count = 0
    for segment in segments:
        first_anchor_index = rule.feature_window_bars - 1
        if first_anchor_index >= len(segment):
            insufficient_feature_history_count += 1
            continue
        for anchor_index in range(first_anchor_index, len(segment), rule.stride_bars):
            candidate_anchor_count += 1
            feature_slice = segment[
                anchor_index - rule.feature_window_bars + 1 : anchor_index + 1
            ]
            label_slice = segment[
                anchor_index + 1 : anchor_index + 1 + rule.label_window_bars
            ]
            if len(label_slice) < rule.label_window_bars:
                insufficient_label_future_count += 1
                continue
            generated.append(
                _build_request(
                    feature_slice, label_slice, rule, scope, interval_delta
                )
            )
    return (
        generated,
        candidate_anchor_count,
        insufficient_feature_history_count,
        insufficient_label_future_count,
    )


def _sort_and_check_requests(requests):
    """Canonical stable request order and duplicate rejection (B13).

    Two outputs with the same ``pit_sample_key`` fail closed; nothing is
    ever silently deduplicated. Input order can never affect the final
    request order.
    """
    ordered = tuple(sorted(requests, key=_request_sort_key))
    seen: set[str] = set()
    for request in ordered:
        key = pit_sample_key(request)
        if key in seen:
            raise SampleGenerationError(
                f"duplicate sample request with pit_sample_key {key}"
            )
        seen.add(key)
    return ordered


# ---------------------------------------------------------------------------
# Public entry point.
# ---------------------------------------------------------------------------


def generate_sample_requests(
    plan: SampleGenerationPlan,
    *,
    path_base,
) -> SampleGenerationResult:
    """Deterministically generate the :class:`PITSampleRequest` sequence of
    one frozen generation plan.

    ``plan`` must be a :class:`SampleGenerationPlan` and ``path_base`` must
    be passed explicitly (there is no implicit default and the current
    working directory is never used as a business input). All plan paths
    are absolute or lexically relative to ``path_base``; the loads go
    through the formal verified Canonical reader, the formal spec loaders,
    the built-in registry preflight, and the strict split-spec reader. The
    output is the frozen :class:`SampleGenerationResult`; no file is ever
    written and no Dataset work is ever executed.
    """
    if not isinstance(plan, SampleGenerationPlan):
        raise SampleGenerationError(
            f"generate_sample_requests requires a SampleGenerationPlan, "
            f"got {type(plan).__name__}"
        )
    base = _coerce_path_base(path_base)
    try:
        loaded_builds = tuple(
            load_verified_canonical_build(_resolve_path(raw, base, "canonical build dir"))
            for raw in plan.canonical_build_dirs
        )
        feature_specs = tuple(
            load_feature_spec(_resolve_path(raw, base, "feature spec file"))
            for raw in plan.feature_spec_files
        )
        label_specs = tuple(
            load_label_spec(_resolve_path(raw, base, "label spec file"))
            for raw in plan.label_spec_files
        )
        split_spec = _load_split_spec(
            _resolve_path(plan.split_spec_file, base, "split spec file")
        )
    except SampleGenerationError:
        raise
    except _DOCUMENTED_ERRORS as exc:
        _as_generation_error(exc, "cannot load generation inputs")

    # Verified-build normalization and row-version reconciliation: builds
    # are deterministically sorted by build id (input order never matters),
    # duplicate build ids fail, identical overlapping rows merge, and
    # conflicting rows fail closed. The segment input is the reconciled
    # unique Canonical bar sequence, never the direct concatenation of all
    # build bars — overlapping rows can therefore never be mistaken for
    # gaps, never silently change a stride origin, and never silently drop
    # generated samples.
    try:
        builds = normalize_verified_builds(loaded_builds)
        reconciled = reconcile_canonical_rows(builds)
        unique_rows = _unique_canonical_rows(reconciled)
    except ExecutionProvenanceError as exc:
        raise SampleGenerationError(str(exc)) from exc

    # BARS window-coverage preflight over the resolved specs (including the
    # shared built-in Label configuration contract).
    try:
        _preflight_feature_coverage(feature_specs, plan.generation_rule)
        _preflight_label_coverage(label_specs, plan.generation_rule)
    except SampleGenerationError:
        raise
    except _DOCUMENTED_ERRORS as exc:
        _as_generation_error(exc, "window coverage preflight failed")

    # Generation identity from the verified normalized inputs (never from
    # paths, ordering, or wall-clock facts).
    identity_input = SampleGenerationIdentityInput(
        canonical_build_pins=tuple(_canonical_build_pin(build) for build in builds),
        feature_spec_pins=tuple(feature_label_spec_pin(spec) for spec in feature_specs),
        label_spec_pins=tuple(feature_label_spec_pin(spec) for spec in label_specs),
        split_spec_pin=chronological_split_spec_pin(split_spec),
        scope=plan.scope,
        generation_rule=plan.generation_rule,
        dataset_as_of=plan.dataset_as_of,
    )
    generation_content_id = sample_generation_content_id(identity_input)

    # Deterministic bar filtering over the reconciled unique Canonical bar
    # sequence, then segments, stride anchors, request generation.
    try:
        interval_delta = parse_intraday_interval(plan.scope.interval)
    except ValueError as exc:
        raise SampleGenerationError(
            f"cannot parse scope interval {plan.scope.interval!r}: {exc}"
        ) from exc
    scope_bars = _in_scope_bars(unique_rows, plan.scope)
    segments = _contiguous_segments(scope_bars, interval_delta)
    generated, candidate_anchors, insufficient_feature, insufficient_label = (
        _generate_requests(segments, plan.generation_rule, plan.scope, interval_delta)
    )
    ordered_requests = _sort_and_check_requests(generated)

    diagnostics = SampleGenerationDiagnostics(
        canonical_build_count=len(builds),
        canonical_bar_count=sum(len(build.bars) for build in builds),
        in_scope_bar_count=len(scope_bars),
        contiguous_segment_count=len(segments),
        candidate_anchor_count=candidate_anchors,
        generated_request_count=len(ordered_requests),
        insufficient_feature_history_count=insufficient_feature,
        insufficient_label_future_count=insufficient_label,
    )
    return SampleGenerationResult(
        generator_core_version=SAMPLE_GENERATOR_CORE_VERSION,
        generation_content_id=generation_content_id,
        requests=ordered_requests,
        canonical_build_pins=identity_input.canonical_build_pins,
        feature_spec_pins=identity_input.feature_spec_pins,
        label_spec_pins=identity_input.label_spec_pins,
        split_spec_pin=identity_input.split_spec_pin,
        scope=plan.scope,
        generation_rule=plan.generation_rule,
        dataset_as_of=plan.dataset_as_of,
        diagnostics=diagnostics,
    )
