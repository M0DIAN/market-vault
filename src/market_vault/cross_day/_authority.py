"""Read-free admission of explicit verified Canonical and Feature PIT evidence."""

from dataclasses import replace
from datetime import timedelta
from types import MappingProxyType
from zoneinfo import ZoneInfo

from ..canonical.gaps import derive_internal_gap_ranges, GAP_POLICY_VERSION
from ..canonical.identity import canonical_bar_key, canonical_row_version_id, canonical_content_id, canonical_build_id, gap_content_id
from ..canonical.models import CanonicalBar, CanonicalSourceRef
from ..canonical.reader import VerifiedCanonicalBuild, VerifiedCanonicalRequest, _source_stable_identity
from ..canonical.schema import CANONICAL_SCHEMA_VERSION
from ..dataset.execution_provenance import normalize_verified_builds, reconcile_canonical_rows, verify_pit_pin_binding
from ..dataset.pit import _association_rows, _build_gap_references, _row_comparator
from ..dataset.pit_models import PITAssemblyResult
from ..observation._pit_validation import admit_bar
from ._validation import require, scalar, sha256, instant
from .registry import CROSS_DAY_SOURCE_SCHEMA_VERSION

INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60}


def admit_builds(builds):
    require(type(builds) is tuple, "requires explicit VerifiedCanonicalBuild tuple")
    copies = []
    for build in normalize_verified_builds(builds):
        require(type(build) is VerifiedCanonicalBuild, "exact verified build type required")
        request = build.normalized_request
        require(type(request) is VerifiedCanonicalRequest, "invalid Canonical request")
        require(request.source_schema_version == CROSS_DAY_SOURCE_SCHEMA_VERSION
                and build.canonical_schema_version == CANONICAL_SCHEMA_VERSION,
                "Cross-Day requires TS2 Canonical builds")
        require(request.interval in INTERVAL_MINUTES and request.requested_session == "RTH"
                and request.adjustment == "NONE" and all(s.startswith("US.") for s in request.symbols),
                "unsupported Canonical scope")
        require(request.symbols == tuple(sorted(set(request.symbols))) and bool(request.symbols)
                and request.trade_dates == tuple(sorted(set(request.trade_dates))) and bool(request.trade_dates),
                "noncanonical request scope")
        require(type(build.bars) is tuple and type(build.manifest_payload) is bytes,
                "verified build must be deeply immutable")
        require(type(build.source_snapshot_provenance) is tuple
                and all(type(s) is CanonicalSourceRef for s in build.source_snapshot_provenance)
                and type(build.gap_ranges) is tuple and type(build.gap_boundaries) is tuple,
                "verified provenance collections must be deeply immutable")
        sources = {_source_stable_identity(s) for s in build.source_snapshot_provenance}
        for bar in build.bars:
            require(type(bar) is CanonicalBar and type(bar.extra_fields) is tuple, "invalid Canonical row type")
            require(all(type(p) is tuple and len(p) == 2 and type(p[0]) is str for p in bar.extra_fields),
                    "invalid immutable extra fields")
            for _, value in bar.extra_fields:
                scalar(value, "float64")
            source = CanonicalSourceRef(bar.ingestion_run_id, bar.physical_snapshot_hash,
                bar.logical_source_rows_hash, bar.source_schema_version, bar.snapshot_file,
                bar.requested_trade_date, bar.requested_session)
            require(_source_stable_identity(source) in sources, "row source absent from verified build provenance")
            require((bar.interval, bar.requested_session, bar.adjustment, bar.source_schema_version) ==
                    (request.interval, request.requested_session, request.adjustment, request.source_schema_version)
                    and bar.code in request.symbols and bar.requested_trade_date in request.trade_dates
                    and bar.session == "RTH" and bar.market_calendar_date == bar.requested_trade_date
                    and bar.canonical_builder_version == build.canonical_builder_version,
                    "row/build scope or provenance mismatch")
            require(bar.dataset_kind == "market_bars_canonical", "unsupported Canonical dataset kind")
            event = instant(bar.event_time, "event_time")
            market = instant(bar.market_available_at, "market_available_at")
            instant(bar.archive_available_at, "archive_available_at")
            require(event.astimezone(ZoneInfo("America/New_York")).date() == bar.market_calendar_date
                    and market > event, "invalid Canonical market clock/date")
            for name in ("open", "high", "low", "close"):
                scalar(getattr(bar, name), "float64")
            require(type(bar.volume) in (int, float), "invalid volume type")
            if type(bar.volume) is float:
                scalar(bar.volume, "float64")
            for name in ("physical_snapshot_hash", "logical_source_rows_hash"):
                sha256(getattr(bar, name), name)
            require(bar.canonical_bar_key == canonical_bar_key(dataset_kind=bar.dataset_kind,
                    code=bar.code, interval=bar.interval, adjustment=bar.adjustment, event_time=bar.event_time),
                    "Canonical bar key mismatch")
            require(bar.canonical_row_version_id == canonical_row_version_id(
                canonical_bar_key=bar.canonical_bar_key, ingestion_run_id=bar.ingestion_run_id,
                source_snapshot_content_hash=bar.physical_snapshot_hash, source_schema_version=bar.source_schema_version,
                canonical_builder_version=bar.canonical_builder_version), "Canonical row version mismatch")
        require(len({b.canonical_bar_key for b in build.bars}) == len(build.bars), "duplicate Canonical keys")
        require(build.canonical_row_version_ids == tuple(sorted(b.canonical_row_version_id for b in build.bars)),
                "build row membership mismatch")
        require(build.canonical_content_id == canonical_content_id(build.bars), "Canonical content mismatch")
        require(build.gap_policy_version == GAP_POLICY_VERSION, "unsupported gap authority")
        gaps = derive_internal_gap_ranges(build.bars, INTERVAL_MINUTES[request.interval] * 60)
        require(build.gap_ranges == gaps and build.gap_count == len(gaps), "Canonical gap reconstruction mismatch")
        require(build.gap_content_id == gap_content_id(gaps, build.gap_policy_version), "gap content mismatch")
        require(len(build.gap_boundaries) == len(gaps), "gap boundary cardinality mismatch")
        for gap, boundary in zip(gaps, build.gap_boundaries):
            previous, following = gap_boundary_rows(build, gap)
            require((boundary.gap_id, boundary.previous_archive_available_at, boundary.next_market_available_at,
                     boundary.next_archive_available_at) == (gap.gap_id, previous.archive_available_at,
                     following.market_available_at, following.archive_available_at), "gap boundary provenance mismatch")
        sha256(build.resolution_content_id, "resolution_content_id")
        require(build.canonical_build_id == canonical_build_id(symbols=list(request.symbols),
                trade_dates=list(request.trade_dates), request_key=request,
                canonical_content_id=build.canonical_content_id, resolution_content_id=build.resolution_content_id,
                gap_content_id=build.gap_content_id, selected_row_version_ids=list(build.canonical_row_version_ids),
                canonical_builder_version=build.canonical_builder_version, canonical_schema_version=build.canonical_schema_version,
                materializer_version=build.materializer_version, gap_policy_version=build.gap_policy_version),
                "Canonical build identity mismatch")
        require(build.status == ("COMPLETE" if build.bars else "EMPTY"), "Canonical status mismatch")
        copies.append(replace(build, normalized_request=replace(request),
                              bars=tuple(replace(b) for b in build.bars)))
    return tuple(copies)


def gap_boundary_rows(build, gap):
    def resolve(event):
        rows = [b for b in build.bars if (b.code, b.interval, b.adjustment, b.market_calendar_date, b.session, b.event_time) ==
                (gap.code, gap.interval, gap.adjustment, gap.market_calendar_date, gap.session, event)]
        require(len(rows) == 1, "gap boundary requires one exact same-build row")
        return rows[0]
    return resolve(gap.previous_event_time), resolve(gap.next_event_time)


def reconcile(builds):
    rows = reconcile_canonical_rows(builds)
    keys = {}
    for row in rows.values():
        key = row.bar.canonical_bar_key
        require(key not in keys or _row_comparator(keys[key].bar) == _row_comparator(row.bar),
                "conflicting Canonical key before archive filtering")
        keys[key] = row
    return rows


def admit_feature_pit(pit, builds, dataset_as_of):
    require(type(pit) is PITAssemblyResult, "requires exact PITAssemblyResult")
    samples = admit_bar(pit)
    rows = reconcile(builds)
    verify_pit_pin_binding(pit, {b.canonical_build_id: b for b in builds}, rows)
    require(pit.gap_references == _build_gap_references(builds), "Feature PIT gap reference mismatch")
    expected_rows = _association_rows(samples, {v: {"bar": r.bar, "build_ids": r.build_ids} for v, r in rows.items()})
    require(tuple(dict(r) for r in pit.association_rows) == tuple(expected_rows), "Feature PIT physical row closure mismatch")
    for sample in samples:
        request = sample.request
        require(request.label_window is None and not sample.label_canonical_row_version_ids, "feature-only PIT required")
        require(sample.dataset_as_of == dataset_as_of, "PIT/archive cutoff mismatch")
        require(request.interval in INTERVAL_MINUTES and request.code.startswith("US.")
                and (request.adjustment, request.requested_session) == ("NONE", "RTH"), "unsupported Feature scope")
        selected = [rows[v].bar for v in sample.feature_canonical_row_version_ids]
        require([b.event_time for b in selected] == sorted({b.event_time for b in selected}), "Feature row order mismatch")
        for bar in selected:
            require((bar.code, bar.interval, bar.adjustment, bar.requested_session, bar.market_calendar_date) ==
                    (request.code, request.interval, request.adjustment, request.requested_session, request.anchor_market_calendar_date)
                    and request.feature_window_start <= bar.event_time < request.feature_window_close
                    and bar.market_available_at <= request.feature_window_close
                    and (dataset_as_of is None or bar.archive_available_at <= dataset_as_of), "inadmissible Feature PIT row")
    # Freeze the upstream dictionaries without mutating the caller's PIT result.
    samples = tuple(replace(s, diagnostics=replace(s.diagnostics)) for s in samples)
    return replace(pit, samples=samples,
        canonical_build_pins=tuple(replace(p) for p in pit.canonical_build_pins),
        canonical_row_version_ids=tuple(pit.canonical_row_version_ids),
        gap_references=tuple(replace(g) for g in pit.gap_references),
        association_schema=replace(pit.association_schema), diagnostics=replace(pit.diagnostics),
        association_rows=tuple(MappingProxyType(dict(r)) for r in expected_rows)), rows
