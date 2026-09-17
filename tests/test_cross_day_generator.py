"""Explicit L3.2 proposals, complete schedule admission and zero-I/O execution."""

import ast
import builtins
import inspect
import io
import os
import socket
import sys
import time
from dataclasses import FrozenInstanceError, fields, replace
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import cross_day_helpers as cd
from cross_day_dataset_helpers import tamper
from market_vault.cross_day_dataset import (
    CrossDayAnchor, MultiSourceCrossDayDatasetError,
    MULTI_SOURCE_CROSS_DAY_SAMPLE_GENERATOR_VERSION, generate_cross_day_feature_requests,
)
from market_vault.dataset.models import DatasetScope
from market_vault.dataset.pit_identity import pit_sample_key
from market_vault.dataset.pit_models import PITSampleRequest


DAY = date(2025, 3, 3)
ANCHOR = CrossDayAnchor("US.AAPL", DAY, 1)
SCOPE = DatasetScope(("US.AAPL",), (DAY,), "NONE", "5m", "RTH")


def inputs(**changes):
    return dict(scope=SCOPE, anchors=(ANCHOR,), feature_window_bars=2, schedule=cd.schedule(),
                label_specs=(cd.spec(),), dataset_as_of=cd.AS_OF) | changes


def generate(**changes):
    return generate_cross_day_feature_requests(**inputs(**changes))


def test_public_signature_and_exact_anchor_fields():
    sig = inspect.signature(generate_cross_day_feature_requests)
    assert tuple(sig.parameters) == ("scope", "anchors", "feature_window_bars", "schedule", "label_specs", "dataset_as_of")
    assert all(p.kind == p.KEYWORD_ONLY and p.default is p.empty for p in sig.parameters.values())
    assert sig.return_annotation == tuple[PITSampleRequest, ...]
    assert [f.name for f in fields(CrossDayAnchor)] == ["code", "market_calendar_date", "anchor_slot"]
    assert MULTI_SOURCE_CROSS_DAY_SAMPLE_GENERATOR_VERSION == "multi-source-cross-day-sample-generator-v1"
    with pytest.raises(TypeError):
        generate_cross_day_feature_requests(**{k: v for k, v in inputs().items() if k != "dataset_as_of"})


def test_exact_feature_only_request_and_existing_identity():
    requests = generate()
    expected = PITSampleRequest("US.AAPL", "5m", "NONE", "RTH", DAY, cd.local(DAY), cd.local(DAY, 9, 40))
    assert type(requests) is tuple and len(requests) == 1
    assert type(requests[0]) is PITSampleRequest and requests[0] == expected
    assert requests[0].label_window_start is requests[0].label_window_close is requests[0].label_window is None
    assert pit_sample_key(requests[0]) == pit_sample_key(expected)
    assert generate(dataset_as_of=None) == requests


def test_multiple_anchors_sorted_and_input_order_independent():
    scope = replace(SCOPE, symbols=("US.MSFT", "US.AAPL"))
    anchors = (CrossDayAnchor("us.msft", DAY, 2), ANCHOR, CrossDayAnchor("US.AAPL", DAY, 3))
    first = generate(scope=scope, anchors=anchors)
    second = generate(scope=scope, anchors=anchors[::-1])
    assert first == second and len(first) == 3
    assert tuple(map(pit_sample_key, first)) == tuple(sorted(map(pit_sample_key, first)))


def test_duplicate_normalized_anchors_rejected():
    with pytest.raises(MultiSourceCrossDayDatasetError, match="DUPLICATE_INPUT"):
        generate(anchors=(ANCHOR, CrossDayAnchor(" us.aapl ", DAY, 1)))


@pytest.mark.parametrize("slot", [True, False, -1, 1.0, "1", None, 2**63])
def test_invalid_anchor_slot_rejected(slot):
    with pytest.raises(MultiSourceCrossDayDatasetError):
        CrossDayAnchor("US.AAPL", DAY, slot)


@pytest.mark.parametrize("code,day", [(1, DAY), ("US.AAPL", "2025-03-03"),
    ("US.AAPL", cd.local(DAY)), ("", DAY), ("US.AAPL\n", DAY)])
def test_anchor_exact_types_and_safe_text(code, day):
    with pytest.raises(MultiSourceCrossDayDatasetError):
        CrossDayAnchor(code, day, 0)


def test_anchor_deep_immutability_and_reverification():
    with pytest.raises((FrozenInstanceError, AttributeError)):
        ANCHOR.anchor_slot = 3
    with pytest.raises(MultiSourceCrossDayDatasetError):
        generate(anchors=(tamper(ANCHOR, anchor_slot=True),))
    with pytest.raises(MultiSourceCrossDayDatasetError):
        generate(anchors=(tamper(ANCHOR, code="us.aapl"),))


@pytest.mark.parametrize("anchor", [CrossDayAnchor("US.MSFT", DAY, 1),
    CrossDayAnchor("US.AAPL", date(2025, 3, 4), 1)])
def test_out_of_scope_anchor_rejected(anchor):
    with pytest.raises(MultiSourceCrossDayDatasetError, match="SCOPE"):
        generate(anchors=(anchor,))


@pytest.mark.parametrize("changes", [dict(symbols=("HK.00700",)), dict(interval="2m"),
    dict(adjustment="QFQ"), dict(requested_session="ETH"), dict(symbols=()), dict(trade_dates=())])
@pytest.mark.parametrize("anchors", [(ANCHOR,), ()])
def test_invalid_scope_including_zero_anchors(changes, anchors):
    with pytest.raises(MultiSourceCrossDayDatasetError):
        generate(scope=tamper(SCOPE, **changes), anchors=anchors)


@pytest.mark.parametrize("interval,minutes", [("1m", 1), ("5m", 5), ("15m", 15), ("30m", 30), ("60m", 60)])
def test_exact_geometry_for_each_supported_interval(interval, minutes):
    request, = generate(scope=replace(SCOPE, interval=interval))
    assert request.feature_window_start == cd.local(DAY)
    assert request.feature_window_close == cd.local(DAY) + timedelta(minutes=2 * minutes)
    last_slot = 390 // minutes - 1
    request, = generate(scope=replace(SCOPE, interval=interval),
                        anchors=(replace(ANCHOR, anchor_slot=last_slot),), feature_window_bars=1)
    assert request.feature_window_close <= cd.local(DAY, 16, 0)
    with pytest.raises(MultiSourceCrossDayDatasetError, match="SCOPE"):
        generate(scope=replace(SCOPE, interval=interval), anchors=(replace(ANCHOR, anchor_slot=last_slot + 1),))


@pytest.mark.parametrize("window", [True, False, 0, -1, 1.0, "2", None, 2**63])
@pytest.mark.parametrize("anchors", [(ANCHOR,), ()])
def test_invalid_window_including_zero_anchors(window, anchors):
    with pytest.raises(MultiSourceCrossDayDatasetError, match="SPEC_CONTRACT"):
        generate(feature_window_bars=window, anchors=anchors)


def test_window_cannot_cross_open_and_huge_counts_fail_boundedly():
    for n in (3, 2**63 - 1):
        with pytest.raises(MultiSourceCrossDayDatasetError, match="SPEC_CONTRACT"):
            generate(feature_window_bars=n)
    with pytest.raises(MultiSourceCrossDayDatasetError, match="SCOPE"):
        generate(anchors=(replace(ANCHOR, anchor_slot=2**63 - 1),))
    with pytest.raises(MultiSourceCrossDayDatasetError, match="SCHEDULE_BINDING"):
        generate(label_specs=(cd.spec(n=2**63 - 1),))
    assert generate(anchors=(), feature_window_bars=2**63 - 1) == ()


def test_closed_day_is_explicit_not_inferred_from_bars():
    schedule = cd.schedule((("2025-03-03", "C"), ("2025-03-04", "N")))
    with pytest.raises(MultiSourceCrossDayDatasetError, match="SCHEDULE_BINDING"):
        generate(schedule=schedule)
    assert generate()  # No bar evidence is an input or a precondition.


def test_missing_anchor_day_and_civil_date_coverage_fail():
    with pytest.raises(MultiSourceCrossDayDatasetError, match="SCHEDULE_BINDING"):
        generate(schedule=cd.schedule((("2025-03-04", "N"), ("2025-03-05", "N"))))
    complete = cd.schedule((("2025-03-03", "N"), ("2025-03-04", "C"), ("2025-03-05", "N")))
    assert generate(schedule=complete)
    for days in (complete.daily_records[::2], complete.daily_records + complete.daily_records[:1]):
        with pytest.raises(MultiSourceCrossDayDatasetError, match="SCHEDULE_BINDING"):
            generate(schedule=tamper(complete, daily_records=days))


def test_missing_future_coverage_and_no_tail_anchor_drop():
    scope = replace(SCOPE, trade_dates=(DAY, date(2025, 3, 4)))
    tail = CrossDayAnchor("US.AAPL", date(2025, 3, 4), 1)
    assert generate(scope=scope)
    for anchors in ((ANCHOR, tail), (tail, ANCHOR)):
        with pytest.raises(MultiSourceCrossDayDatasetError, match="SCHEDULE_BINDING"):
            generate(scope=scope, anchors=anchors)
    with pytest.raises(MultiSourceCrossDayDatasetError, match="SCHEDULE_BINDING"):
        generate(schedule=cd.schedule((("2025-03-03", "N"),)))


def test_all_label_specs_contribute_to_maximum_trading_horizon():
    specs = (cd.spec(), cd.spec(n=2, transform="maximum_favorable_excursion", name="future_mfe"))
    for ordered in (specs, specs[::-1]):
        with pytest.raises(MultiSourceCrossDayDatasetError, match="SCHEDULE_BINDING"):
            generate(label_specs=ordered)
    closed = cd.schedule((("2025-03-03", "N"), ("2025-03-04", "N"), ("2025-03-05", "C")))
    with pytest.raises(MultiSourceCrossDayDatasetError, match="SCHEDULE_BINDING"):
        generate(label_specs=specs, schedule=closed)
    covered = cd.schedule((("2025-03-03", "N"), ("2025-03-04", "N"), ("2025-03-05", "C"), ("2025-03-06", "N")))
    assert generate(label_specs=specs, schedule=covered) == generate(label_specs=specs[::-1], schedule=covered)


def test_qualified_future_early_close_nonfit_left_to_real_l2(tmp_path):
    day = date(2025, 11, 26)
    scope = replace(SCOPE, trade_dates=(day,))
    schedule = cd.schedule((("2025-11-26", "N"), ("2025-11-27", "C"), ("2025-11-28", "E")))
    requests = generate(scope=scope, anchors=(CrossDayAnchor("US.AAPL", day, 48),), schedule=schedule)
    assert requests[0].feature_window_close == cd.local(day) + timedelta(minutes=49 * 5)
    assert requests[0].feature_window_start == cd.local(day) + timedelta(minutes=47 * 5)
    build = cd.build(tmp_path, (cd.bar("2025-11-26", slot=47), cd.bar("2025-11-26", slot=48)))
    pit = cd.pit((build,), requests=requests)
    result = cd.assemble_cross_day_labels(pit, (build,), (), schedule, (cd.spec(),), dataset_as_of=cd.AS_OF)
    assert result.decisions[0].reason_code == "ALIGNED_SLOT_OUTSIDE_SESSION"
    assert result.decisions[0].required_slots[0].slot_fits is False


def test_anchor_early_close_itself_must_fit():
    day = date(2025, 11, 28)
    schedule = cd.schedule((("2025-11-28", "E"), ("2025-11-29", "C"), ("2025-11-30", "C"), ("2025-12-01", "N")))
    scope = replace(SCOPE, trade_dates=(day,))
    assert generate(scope=scope, anchors=(CrossDayAnchor("US.AAPL", day, 41),), schedule=schedule)
    with pytest.raises(MultiSourceCrossDayDatasetError, match="SCOPE"):
        generate(scope=scope, anchors=(CrossDayAnchor("US.AAPL", day, 42),), schedule=schedule)


def test_dst_uses_explicit_same_date_geometry():
    schedule = cd.schedule((("2025-03-07", "N"), ("2025-03-08", "C"), ("2025-03-09", "C"),
                            ("2025-03-10", "N"), ("2025-03-11", "N")))
    dates = (date(2025, 3, 7), date(2025, 3, 10))
    requests = generate(scope=replace(SCOPE, trade_dates=dates),
        anchors=tuple(CrossDayAnchor("US.AAPL", d, 1) for d in dates), schedule=schedule)
    by_day = {r.anchor_market_calendar_date: r for r in requests}
    assert by_day[dates[0]].feature_window_start.hour == 14
    assert by_day[dates[1]].feature_window_start.hour == 13


@pytest.mark.parametrize("anchors", [(ANCHOR,), ()])
def test_schedule_reverification_and_archive_gate(anchors):
    schedule = cd.schedule()
    assert generate(anchors=anchors, dataset_as_of=schedule.archive_available_at) == generate(anchors=anchors)
    with pytest.raises(MultiSourceCrossDayDatasetError, match="SCHEDULE_BINDING"):
        generate(anchors=anchors, dataset_as_of=schedule.archive_available_at - timedelta(microseconds=1))
    for broken in (None, tamper(schedule, market="HK"), tamper(schedule, coverage_complete=False),
                   tamper(schedule, source_content_hash="bad"), tamper(schedule, daily_records=(
                       tamper(schedule.daily_records[0], session_close=cd.local(DAY, 17, 0)), schedule.daily_records[1]))):
        with pytest.raises(MultiSourceCrossDayDatasetError, match="SCHEDULE_BINDING"):
            generate(anchors=anchors, schedule=broken)


@pytest.mark.parametrize("value", [True, "2026-01-01", datetime(2026, 1, 1)])
def test_zero_anchor_cutoff_remains_strict(value):
    with pytest.raises(MultiSourceCrossDayDatasetError, match="CLOCK_AUTHORITY"):
        generate(anchors=(), dataset_as_of=value)


@pytest.mark.parametrize("anchors", [(ANCHOR,), ()])
def test_specs_nonempty_exact_closed_authority_even_with_zero_anchors(anchors):
    good = cd.spec()
    for bad in ((), [good], (None,), (good, good), (cd.spec(schema="10.9"),),
                (replace(good, transform_ref="untrusted.module:callback"),),
                (tamper(good, parameters=("unexpected",)),)):
        with pytest.raises(MultiSourceCrossDayDatasetError):
            generate(anchors=anchors, label_specs=bad)


def test_zero_anchors_and_exact_containers():
    assert generate(anchors=()) == ()
    for anchors in ([], [ANCHOR], None, (object(),)):
        with pytest.raises(MultiSourceCrossDayDatasetError, match="INPUT_TYPE"):
            generate(anchors=anchors)


def test_no_execution_no_io_no_clock(monkeypatch, record_property):
    import market_vault.dataset.pit as pit
    import market_vault.dataset.sample_generation as old_generator
    import market_vault.dataset.sample_generation_core as old_core
    import market_vault.ts2_feature.execution as ts2
    import market_vault.observation.pit as a3
    import market_vault.multi_source.feature_execution as obs
    import market_vault.cross_day.assembly as l2_assembly
    import market_vault.cross_day.execution as l2_execution
    import market_vault.cross_day.registry as registry
    import market_vault.cross_day_dataset.execution as join
    data = inputs()
    denied = []
    def forbidden(*args, **kwargs):
        denied.append("forbidden")
        raise AssertionError("generator performed upstream execution or unauthorized I/O")
    def clock_guard(frame, event, arg):
        if event == "c_call" and getattr(arg, "__name__", "") in ("now", "utcnow", "today"):
            forbidden()
    with monkeypatch.context() as patch:
        for module in (old_generator, old_core, pit, ts2, a3, obs, l2_assembly, l2_execution, join):
            for name in vars(module):
                if name.startswith(("generate_", "assemble_", "execute_", "join_")) and callable(getattr(module, name)):
                    patch.setattr(module, name, forbidden)
        patch.setattr(l2_assembly, "_facts", forbidden)
        patch.setattr(registry, "built_in_cross_day_label_registry", forbidden)
        patch.setattr(inspect, "getsource", forbidden)
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(io, "open", forbidden)
        for name in ("open", "stat", "lstat", "scandir", "listdir", "mkdir", "remove", "unlink", "rename", "replace", "getcwd", "getenv"):
            patch.setattr(os, name, forbidden)
        for name in ("read_text", "read_bytes", "write_text", "write_bytes", "iterdir", "glob", "rglob"):
            patch.setattr(Path, name, forbidden)
        patch.setattr(socket, "socket", forbidden)
        patch.setattr(socket, "create_connection", forbidden)
        patch.setattr(time, "time", forbidden)
        patch.setattr(time, "time_ns", forbidden)
        profile = sys.getprofile()
        sys.setprofile(clock_guard)
        try:
            result = generate_cross_day_feature_requests(**data)
            empty = generate_cross_day_feature_requests(**(data | {"anchors": ()}))
        finally:
            sys.setprofile(profile)
    assert len(result) == 1 and empty == () and denied == []
    record_property("GENERATOR_FILESYSTEM_READ_COUNT", 0)
    record_property("GENERATOR_FILESYSTEM_WRITE_COUNT", 0)
    record_property("GENERATOR_UPSTREAM_EXECUTION_COUNT", 0)


def test_generator_has_no_artifact_or_discovery_api():
    import market_vault.cross_day_dataset as package
    import market_vault.cross_day_dataset.generator as module
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    forbidden = {"open", "read_text", "read_bytes", "write_text", "write_bytes", "getsource", "now", "utcnow", "today",
                 "getenv", "getcwd", "stat", "iterdir", "listdir", "scandir", "rmtree", "rename"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", getattr(node.func, "id", ""))
            assert name not in forbidden
    assert not {"reader.py", "manifest.py", "materialization.py"} & {p.name for p in Path(module.__file__).parent.iterdir()}
    assert not any(any(word in name.lower() for word in ("manifest", "reader", "materializ", "catalog", "provider"))
                   for name in package.__all__)
