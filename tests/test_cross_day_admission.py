"""Schedule, strict preflight, immutable result and closed I/O boundary tests."""

import builtins
import _io
import inspect
import io
import linecache
import os
import socket
import tokenize
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from market_vault.cross_day import (
    CrossDayLabelError, TradingDayRecord, assemble_cross_day_labels, execute_cross_day_labels,
)
from market_vault.cross_day.registry import built_in_cross_day_label_registry
from market_vault.cross_day.schedule import admit_schedule
from market_vault.cross_day import identity as ids
from market_vault.dataset import LabelHorizon, LabelObservationWindow, CrossTradingDayPolicy
from market_vault.dataset.encoding import DatasetError
from cross_day_helpers import AS_OF, ARCHIVE, bar, build, local, pit, run, schedule, spec


@pytest.fixture
def normal(tmp_path):
    return (build(tmp_path, (bar(),)),), (build(tmp_path, (bar("2025-03-04"),)),)


@pytest.mark.parametrize("change", [
    {"daily_records": ()}, {"coverage_complete": False}, {"market": "HK"},
    {"requested_session": "ALL"}, {"market_timezone": "UTC"},
    {"schedule_schema_version": "unknown"}, {"calendar_contract_version": "unknown"},
    {"normalization_version": "unknown"}, {"source_snapshot_id": "invalid"},
    {"source_content_hash": "invalid"}, {"coverage_completion_evidence_id": "invalid"},
    {"coverage_end_date": date(2025, 3, 2)}, {"coverage_start_date": "2025-03-03"},
    {"archive_available_at": ARCHIVE.replace(tzinfo=None)},
])
def test_schedule_invalid_scalars(change):
    with pytest.raises((CrossDayLabelError, DatasetError)):
        replace(schedule(), **change)


def test_schedule_every_civil_date_and_duplicate_rejection():
    sched = schedule((("2025-03-07", "N"), ("2025-03-08", "C"), ("2025-03-09", "C"), ("2025-03-10", "N")))
    for rows in (sched.daily_records[:1] + sched.daily_records[2:], sched.daily_records + sched.daily_records[:1],
                 sched.daily_records[:1] + sched.daily_records[:1] + sched.daily_records[2:]):
        with pytest.raises(CrossDayLabelError, match="date"):
            replace(sched, daily_records=rows)
    assert replace(sched, daily_records=sched.daily_records[::-1]).schedule_content_id == sched.schedule_content_id


@pytest.mark.parametrize("day,profile,close", [
    ("2025-11-28", "NORMAL", 16), ("2025-12-24", "NORMAL", 16),
    ("2025-03-04", "QUALIFIED_EARLY_CLOSE", 13), ("2025-03-04", "NORMAL", 13),
])
def test_unqualified_geometry_rejected(day, profile, close):
    with pytest.raises(CrossDayLabelError):
        TradingDayRecord(date.fromisoformat(day), "TRADING", local(day), local(day, close, 0), profile)


def test_closed_geometry_and_naive_rejection():
    with pytest.raises(CrossDayLabelError):
        TradingDayRecord(date(2025, 3, 4), "CLOSED", local("2025-03-04"), None, None)
    with pytest.raises(DatasetError):
        replace(schedule().daily_records[0], session_open=local("2025-03-03").replace(tzinfo=None))


def test_schedule_archive_gate_and_identity(normal):
    sched = schedule(archive=AS_OF)
    assert admit_schedule(sched, AS_OF) == sched
    with pytest.raises(CrossDayLabelError, match="archive-future"):
        run(*normal, sched=replace(sched, archive_available_at=AS_OF + timedelta(microseconds=1)), requests=())
    for name in ("source_snapshot_id", "source_content_hash", "coverage_completion_evidence_id"):
        changed = replace(sched, **{name: "9" * 64})
        assert changed.schedule_content_id != sched.schedule_content_id
        assert ids.schedule_pin_id(changed.pin) != ids.schedule_pin_id(sched.pin)
    one, two = run(*normal), run(*normal, sched=replace(schedule(), source_content_hash="9" * 64))
    assert one.values[0].value == two.values[0].value
    assert one.association_content_id != two.association_content_id
    assert one.association.feature_pit == two.association.feature_pit
    changed_clock = replace(schedule(), archive_available_at=ARCHIVE + timedelta(microseconds=1))
    assert changed_clock.schedule_content_id != schedule().schedule_content_id


@pytest.mark.parametrize("change", ["minutes", "bars", "boundary", "inputs", "requirements", "parameters", "output", "unknown", "offset"])
def test_spec_preflight_even_zero_samples(normal, change):
    from market_vault.dataset.models import DatasetField
    from market_vault.dataset.spec_models import SpecVersionRequirements, SpecParameter
    value = spec()
    changes = {
        "minutes": dict(horizon=LabelHorizon("MINUTES", 1), observation_window=LabelObservationWindow("MINUTES", 0, 0)),
        "bars": dict(horizon=LabelHorizon("BARS", 1), observation_window=LabelObservationWindow("BARS", 0, 0)),
        "boundary": dict(cross_trading_day=CrossTradingDayPolicy(True, "OTHER")),
        "inputs": dict(input_canonical_fields=("high",)),
        "requirements": dict(requirements=SpecVersionRequirements(("market-bars-canonical-schema-v1",), ("10.9",))),
        "parameters": dict(parameters=(SpecParameter("unexpected", 1),)),
        "output": dict(output=DatasetField(value.name, "int64", False)),
        "unknown": dict(transform_ref="unknown.transform:unknown"),
        "offset": dict(observation_window=LabelObservationWindow("TRADING_DAYS", 0, 1)),
    }
    with pytest.raises(CrossDayLabelError):
        run(*normal, specs=(replace(value, **changes[change]),), requests=())


def test_explicit_opt_in_bool_and_duplicate_semantics(normal):
    with pytest.raises(DatasetError):
        replace(spec(), cross_trading_day=CrossTradingDayPolicy(False, None))
    with pytest.raises(DatasetError):
        LabelHorizon("TRADING_DAYS", True)
    with pytest.raises(CrossDayLabelError, match="duplicate"):
        run(*normal, specs=(spec(), spec()), requests=())
    bad = replace(spec(name="other"), horizon=LabelHorizon("BARS", 1), observation_window=LabelObservationWindow("BARS", 0, 0))
    with pytest.raises(CrossDayLabelError):
        run(*normal, specs=(spec(), bad))


@pytest.mark.parametrize("close", [local("2025-03-03", 9, 41), local("2025-03-03", 16, 5)])
def test_anchor_geometry_failures(normal, close):
    features, labels = normal
    p = pit(features)
    request = replace(p.samples[0].request, feature_window_close=close)
    p = pit(features, requests=(request,))
    with pytest.raises(CrossDayLabelError, match="anchor slot"):
        assemble_cross_day_labels(p, features, labels, schedule(), (spec(),), dataset_as_of=AS_OF)


def test_wrong_scope_and_pit_evidence_failures(normal):
    features, labels = normal
    p = pit(features)
    for bad_labels in ((replace(labels[0], normalized_request=replace(labels[0].normalized_request, requested_session="ALL")),),
                       (replace(labels[0], canonical_content_id="0" * 64),),
                       (replace(labels[0], normalized_request=replace(labels[0].normalized_request, adjustment="QFQ")),),
                       (replace(labels[0], normalized_request=replace(labels[0].normalized_request, symbols=("HK.00700",))),),
                       (replace(labels[0], normalized_request=replace(labels[0].normalized_request, interval="2m")),)):
        with pytest.raises(CrossDayLabelError):
            assemble_cross_day_labels(p, features, bad_labels, schedule(), (spec(),), dataset_as_of=AS_OF)
    with pytest.raises(CrossDayLabelError, match="pin|build"):
        assemble_cross_day_labels(p, (), labels, schedule(), (spec(),), dataset_as_of=AS_OF)
    with pytest.raises(CrossDayLabelError, match="cutoff"):
        assemble_cross_day_labels(p, features, labels, schedule(), (spec(),), dataset_as_of=None)
    with pytest.raises(CrossDayLabelError, match="duplicate"):
        run(features, labels + labels)


def test_exactly_once_and_never_incomplete(tmp_path, normal, monkeypatch):
    import market_vault.cross_day.execution as execution
    registry = built_in_cross_day_label_registry()
    calls = []
    def instrument(reg):
        def call(value):
            calls.append(reg.transform_ref)
            assert set(value.__dataclass_fields__) == {"field_names", "anchor_row", "rows", "parameters", "alignment_rule"}
            return reg.implementation(value)
        return replace(reg, implementation=call)
    monkeypatch.setattr(execution, "built_in_cross_day_label_registry", lambda: tuple(instrument(r) for r in registry))
    specs = tuple(spec(transform=name, name=name) for name in
                  ("forward_return", "forward_direction", "maximum_favorable_excursion", "maximum_adverse_excursion"))
    result = run(*normal, specs=specs)
    assert len(calls) == 4 and len(set(calls)) == 4
    assert sorted(v.value for v in result.values) == [-0.25, 0, 0.0, 0.5]
    calls.clear()
    labels = (build(tmp_path, (bar("2025-03-04", archive=AS_OF + timedelta(days=1)),)),)
    assert all(v.status == "INCOMPLETE" for v in run(normal[0], labels, specs=specs).values)
    assert calls == []


def test_only_static_fingerprint_reads(normal, monkeypatch):
    import market_vault.cross_day.registry as registry
    original_hash = registry._module_source_sha256
    original_open, original_io_open = builtins.open, io.open
    original_open_code = _io.open_code
    original_tokenize_open = tokenize._builtin_open
    active, reads, fingerprints = [], [], []
    def fingerprint(fn, ref):
        path = os.path.normcase(os.path.abspath(fn.__code__.co_filename))
        fingerprints.append(ref)
        active.append(path)
        try:
            return original_hash(fn, ref)
        finally:
            active.pop()
    def guard(original):
        def read(path, mode="r", *args, **kwargs):
            assert active and os.path.normcase(os.path.abspath(path)) == active[-1]
            assert not any(flag in mode for flag in "wax+")
            reads.append(active[-1])
            return original(path, mode, *args, **kwargs)
        return read
    def forbidden(*args, **kwargs):
        raise AssertionError("unauthorized I/O or external authority")
    def open_code(path):
        assert active and os.path.normcase(os.path.abspath(path)) == active[-1]
        reads.append(active[-1])
        return original_open_code(path)
    # Cold cache proves real source reads rather than a prewarmed bypass.
    linecache.clearcache()
    with monkeypatch.context() as m:
        m.setattr(registry, "_module_source_sha256", fingerprint)
        m.setattr(builtins, "open", guard(original_open))
        m.setattr(io, "open", guard(original_io_open))
        m.setattr(_io, "open_code", open_code)
        m.setattr(tokenize, "_builtin_open", guard(original_tokenize_open))
        for name in ("open", "listdir", "scandir", "getenv"):
            m.setattr(os, name, forbidden)
        m.setattr(socket, "socket", forbidden)
        result = run(*normal)
    assert result.values[0].status == "COMPLETE"
    assert len(fingerprints) == 8 and len(set(fingerprints)) == 4
    assert len(set(reads)) == 4


def test_old_authorities_not_widened():
    from market_vault.dataset.feature_registry import built_in_feature_registry
    from market_vault.dataset.label_registry import built_in_label_registrations
    from market_vault.dataset.feature_registry import built_in_feature_registrations
    old = built_in_label_registrations() + built_in_feature_registrations()
    assert all(r.supported_source_schema_versions == ("10.9",) for r in old)
    new = built_in_cross_day_label_registry()
    old_by_ref = {r.transform_ref: r for r in old}
    from market_vault.dataset.transform_models import transform_implementation_pin
    assert all(r.implementation_pin != transform_implementation_pin(old_by_ref[r.transform_ref]) for r in new)


def test_new_fingerprint_changes_value_identity(normal, monkeypatch):
    import market_vault.cross_day.registry as registry
    one = run(*normal)
    monkeypatch.setattr(registry, "_module_source_sha256", lambda fn, ref: "1" * 64)
    two = run(*normal)
    assert one.values[0].value == two.values[0].value
    assert one.implementation_pins != two.implementation_pins
    assert one.values_content_id != two.values_content_id
    old_pin = one.values[0].implementation_pin
    with pytest.raises(CrossDayLabelError, match="linkage"):
        replace(two, values=(replace(two.values[0], implementation_pin=old_pin),))
