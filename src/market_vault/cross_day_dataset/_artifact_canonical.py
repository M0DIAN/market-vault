"""Recorded Canonical and Feature PIT closure, without upstream live objects."""

from dataclasses import dataclass
from datetime import date, timedelta
from types import MappingProxyType
from zoneinfo import ZoneInfo

from ..canonical.gaps import derive_internal_gap_ranges, GAP_POLICY_VERSION
from ..canonical.identity import canonical_bar_key, canonical_row_version_id, canonical_content_id, canonical_build_id, gap_content_id
from ..dataset.content import dataset_schema_id, logical_dataset_content_id
from ..dataset.execution_provenance import expected_canonical_build_pin
from ..dataset.models import CanonicalBuildPin, SourceSnapshotPin, GapReference
from ..dataset.pit import pit_association_schema
from ..dataset.pit_identity import pit_sample_key, pit_sample_version_id
from ._artifact_records import _Recorded, _SCHEMAS, _encode_record
from ._artifact_values import _value
from .artifact_models import _require


_INTERVALS = MappingProxyType({"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60})


@dataclass(frozen=True, slots=True)
class _View:
    """A private recorded view, never a replacement upstream issued result."""

    _facts: object

    def __getattr__(self, name):
        try:
            return self._facts[name]
        except KeyError:
            raise AttributeError(name) from None


def _view(**facts):
    return _View(MappingProxyType(facts))


def _check(condition, message):
    _require(condition, "ARTIFACT_AUTHORITY", message)


def _ordered(values, key, label):
    keys = tuple(key(v) for v in values)
    _check(keys == tuple(sorted(set(keys))), "duplicate/noncanonical " + label)
    return values


def _digest(value):
    _check(type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value), "invalid digest")
    return value


def _canonical_closure(records, scope):
    _ordered(records, lambda b: b.canonical_build_id, "Canonical evidence")
    builds, pins, gaps, versions, keys = [], [], [], {}, {}
    for b in records:
        _encode_record(b, "VerifiedCanonicalBuild")
        req = _value(b.normalized_request)
        _check(req.symbols and req.symbols == tuple(sorted(set(req.symbols)))
               and req.trade_dates and req.trade_dates == tuple(sorted(set(req.trade_dates)))
               and set(req.symbols) <= set(scope.symbols)
               and (req.interval, req.adjustment, req.requested_session) == (scope.interval, "NONE", "RTH")
               and req.interval in _INTERVALS and req.source_schema_version == "10.9-mv-ts2"
               and b.canonical_schema_version == "market-bars-canonical-schema-v1", "Canonical source/scope mismatch")
        sources = tuple(tuple(getattr(s, name) for name, _ in _SCHEMAS["CanonicalSourceRef"])
                        for s in b.source_snapshot_provenance)
        _check(len(sources) == len(set(sources)), "duplicate Canonical source provenance")
        seen = set()
        for bar in b.bars:
            _check((bar.interval, bar.adjustment, bar.requested_session, bar.session, bar.source_schema_version) ==
                   (req.interval, "NONE", "RTH", "RTH", "10.9-mv-ts2")
                   and bar.code in req.symbols and bar.requested_trade_date in req.trade_dates
                   and bar.market_calendar_date == bar.requested_trade_date
                   and bar.canonical_builder_version == b.canonical_builder_version
                   and bar.dataset_kind == "market_bars_canonical", "Canonical row scope mismatch")
            _check(tuple(getattr(bar, name) for name, _ in _SCHEMAS["CanonicalSourceRef"]) in sources,
                   "Canonical row source absent")
            _check(bar.market_available_at > bar.event_time
                   and bar.event_time.astimezone(ZoneInfo("America/New_York")).date() == bar.market_calendar_date,
                   "Canonical clock/date mismatch")
            _digest(bar.physical_snapshot_hash)
            _digest(bar.logical_source_rows_hash)
            _check(bar.canonical_bar_key == canonical_bar_key(dataset_kind=bar.dataset_kind, code=bar.code,
                   interval=bar.interval, adjustment=bar.adjustment, event_time=bar.event_time), "Canonical row key mismatch")
            _check(bar.canonical_row_version_id == canonical_row_version_id(canonical_bar_key=bar.canonical_bar_key,
                   ingestion_run_id=bar.ingestion_run_id, source_snapshot_content_hash=bar.physical_snapshot_hash,
                   source_schema_version=bar.source_schema_version, canonical_builder_version=bar.canonical_builder_version),
                   "Canonical row version mismatch")
            _check(bar.canonical_bar_key not in seen, "duplicate Canonical key in build")
            seen.add(bar.canonical_bar_key)
            previous = versions.get(bar.canonical_row_version_id)
            _check(previous is None or previous[0] == bar, "Canonical version conflict before clocks")
            if previous is None:
                versions[bar.canonical_row_version_id] = (bar, [b.canonical_build_id])
            else:
                previous[1].append(b.canonical_build_id)
            previous_key = keys.get(bar.canonical_bar_key)
            _check(previous_key is None or previous_key == bar, "Canonical key conflict before clocks")
            keys[bar.canonical_bar_key] = bar
        _check(b.canonical_row_version_ids == tuple(sorted(bar.canonical_row_version_id for bar in b.bars)),
               "Canonical row inventory mismatch")
        _check(b.canonical_content_id == canonical_content_id(b.bars), "Canonical content mismatch")
        derived_gaps = derive_internal_gap_ranges(b.bars, _INTERVALS[req.interval] * 60)
        _check(b.gap_policy_version == GAP_POLICY_VERSION and b.gap_count == len(derived_gaps)
               and tuple(_value(g) for g in b.gap_ranges) == derived_gaps
               and b.gap_content_id == gap_content_id(derived_gaps, b.gap_policy_version), "Canonical gap mismatch")
        _check(len(b.gap_boundaries) == len(derived_gaps), "gap boundary count mismatch")
        for gap, boundary in zip(derived_gaps, b.gap_boundaries):
            def at(event):
                matching = tuple(bar for bar in b.bars if
                    (bar.code, bar.interval, bar.adjustment, bar.market_calendar_date, bar.session, bar.event_time) ==
                    (gap.code, gap.interval, gap.adjustment, gap.market_calendar_date, gap.session, event))
                _check(len(matching) == 1, "gap lacks unique same-build boundary")
                return matching[0]
            previous, following = at(gap.previous_event_time), at(gap.next_event_time)
            _check((boundary.gap_id, boundary.previous_archive_available_at, boundary.next_market_available_at,
                    boundary.next_archive_available_at) ==
                   (gap.gap_id, previous.archive_available_at, following.market_available_at, following.archive_available_at),
                   "gap boundary clock mismatch")
        _digest(b.resolution_content_id)
        _check(b.canonical_build_id == canonical_build_id(symbols=list(req.symbols), trade_dates=list(req.trade_dates),
               request_key=req, canonical_content_id=b.canonical_content_id, resolution_content_id=b.resolution_content_id,
               gap_content_id=b.gap_content_id, selected_row_version_ids=list(b.canonical_row_version_ids),
               canonical_builder_version=b.canonical_builder_version, canonical_schema_version=b.canonical_schema_version,
               materializer_version=b.materializer_version, gap_policy_version=b.gap_policy_version), "Canonical build ID mismatch")
        _check(b.status == ("COMPLETE" if b.bars else "EMPTY"), "Canonical status mismatch")
        sources_pins = tuple(SourceSnapshotPin(**dict(s._items)) for s in b.source_snapshot_provenance)
        pins.append(CanonicalBuildPin(b.canonical_build_id, b.canonical_content_id, b.canonical_builder_version,
            b.canonical_schema_version, b.materializer_version, b.gap_policy_version, b.gap_content_id,
            b.status, b.canonical_row_version_ids, sources_pins))
        gaps.append(GapReference(b.canonical_build_id, b.gap_content_id, len(derived_gaps)))
        builds.append(b)
    rows = MappingProxyType({key: _view(bar=bar, build_ids=tuple(backing)) for key, (bar, backing) in versions.items()})
    return tuple(builds), tuple(pins), tuple(gaps), rows


def _pit_closure(record, builds, pins, gaps, rows, scope, cutoff):
    _encode_record(record, "PITAssemblyResult")
    samples = tuple(_value(s) for s in record.samples)
    _ordered(samples, lambda s: s.sample_key, "PIT samples")
    actual_pins = tuple(_value(p) for p in record.canonical_build_pins)
    actual_gaps = tuple(_value(g) for g in record.gap_references)
    selected_versions = {v for s in samples for v in s.feature_canonical_row_version_ids}
    selected_pins = tuple(expected_canonical_build_pin(b, selected_versions, rows) for b in builds)
    _check(actual_pins == selected_pins and actual_gaps == gaps, "PIT Feature build/selected-pin/gap closure mismatch")
    build_ids = tuple(b.canonical_build_id for b in builds)
    expected_rows, selected = [], set()
    for sample in samples:
        req = sample.request
        _check(req.label_window is None and sample.label_canonical_row_version_ids == (), "PIT must be Feature-only")
        _check(req.code in scope.symbols and req.anchor_market_calendar_date in scope.trade_dates
               and (req.interval, req.adjustment, req.requested_session) == (scope.interval, "NONE", "RTH"), "PIT scope mismatch")
        _check(sample.dataset_as_of == cutoff and sample.considered_canonical_build_ids == build_ids, "PIT clocks/build boundary mismatch")
        _check(sample.sample_key == pit_sample_key(req) and sample.sample_version_id == pit_sample_version_id(
            sample_key=sample.sample_key, dataset_as_of=cutoff,
            feature_canonical_row_version_ids=sample.feature_canonical_row_version_ids,
            label_canonical_row_version_ids=(), considered_canonical_build_ids=build_ids), "PIT sample identity mismatch")
        events = []
        for position, version in enumerate(sample.feature_canonical_row_version_ids):
            _check(version in rows, "selected PIT row absent from Feature evidence")
            resolved = rows[version]
            bar = resolved.bar
            _check((bar.code, bar.interval, bar.adjustment, bar.requested_session, bar.market_calendar_date) ==
                   (req.code, req.interval, req.adjustment, req.requested_session, req.anchor_market_calendar_date)
                   and req.feature_window_start <= bar.event_time < req.feature_window_close
                   and bar.market_available_at <= req.feature_window_close
                   and (cutoff is None or bar.archive_available_at <= cutoff), "PIT selected Feature scope/clock mismatch")
            events.append(bar.event_time)
            selected.add(version)
            expected_rows.append(dict(sample_key=sample.sample_key, sample_version_id=sample.sample_version_id,
                role="FEATURE", position=position, canonical_build_id=min(resolved.build_ids),
                canonical_bar_key=bar.canonical_bar_key, canonical_row_version_id=version, code=bar.code,
                event_time=bar.event_time, market_available_at=bar.market_available_at, archive_available_at=bar.archive_available_at))
        _check(events == sorted(set(events)), "PIT selection order/duplicates mismatch")
        _check(sample.diagnostics.feature_selected_count == len(events) and sample.diagnostics.label_selected_count == 0,
               "PIT selected diagnostics mismatch")
    schema = _value(record.association_schema)
    physical_rows = tuple(MappingProxyType(dict(row._items)) for row in record.association_rows)
    _check(tuple(dict(row) for row in physical_rows) == tuple(expected_rows), "PIT association rows differ")
    _check(record.canonical_row_version_ids == tuple(sorted(selected)) and schema == pit_association_schema()
           and dataset_schema_id(schema) == record.association_schema_id
           and logical_dataset_content_id(schema, physical_rows) == record.association_content_id,
           "PIT selected union or association identity differs")
    diagnostics = _value(record.diagnostics)
    _check(diagnostics.sample_count == len(samples)
           and diagnostics.total_feature_rows == sum(len(s.feature_canonical_row_version_ids) for s in samples)
           and diagnostics.total_label_rows == 0 and diagnostics.considered_canonical_build_ids == build_ids,
           "PIT aggregate diagnostics differ")
    return _view(samples=samples, canonical_build_pins=actual_pins, canonical_row_version_ids=record.canonical_row_version_ids,
        gap_references=gaps, association_schema=schema, association_rows=physical_rows,
        association_schema_id=record.association_schema_id, association_content_id=record.association_content_id,
        diagnostics=diagnostics)
