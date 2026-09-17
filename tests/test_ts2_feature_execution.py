"""Real TS2 Canonical/PIT admission, windows and formula canaries."""

from dataclasses import replace
from datetime import timedelta, datetime
import math

import pytest

from ts2_feature_helpers import AS_OF, ARCHIVE, bar, build, pit, local, fixture, spec, execute, tamper
from market_vault.ts2_feature import execute_ts2_features, TS2FeatureError
from market_vault.ts2_feature import execution as engine
from market_vault.dataset.spec_models import SpecParameter


def fails(code, call):
    with pytest.raises(TS2FeatureError) as caught:
        call()
    assert caught.value.reason_code == code


@pytest.mark.parametrize("name,expected", [
    ("simple_return", .25), ("log_return", math.log(1.25)),
    ("rolling_mean", 112.5), ("rolling_std", 12.5),
    ("rolling_volume_mean", 100.0), ("volume_ratio", 1.0),
    ("candle_range", 75.0), ("candle_body", 25.0),
])
def test_eight_real_formulas(tmp_path, monkeypatch, name, expected):
    one, selected = fixture(tmp_path)
    calls = []
    real = engine._invoke
    def invoke(reg, transport):
        calls.append(transport)
        return real(reg, transport)
    monkeypatch.setattr(engine, "_invoke", invoke)
    result = execute(one, selected, (spec(name),))
    value = result.samples[0].values[0]
    assert result.status == value.status == "COMPLETE"
    assert value.value == pytest.approx(expected)
    assert type(value.value) is float
    assert len(calls) == 1
    assert len(calls[0].rows) == (1 if name.startswith("candle_") else 2)
    assert value.candidate_canonical_row_version_ids == value.consumed_canonical_row_version_ids
    assert result.samples[0].bar_sample_version_id == selected.samples[0].sample_version_id
    assert len(result.registry_implementation_pins) == 8
    assert len(result.execution_id) == 64


@pytest.mark.parametrize("schema", ["10.9", "unknown"])
def test_legacy_and_unknown_rejected_even_empty(tmp_path, schema):
    one, selected = fixture(tmp_path)
    bad = tamper(one, normalized_request=tamper(one.normalized_request, source_schema_version=schema))
    fails("SOURCE_COHORT", lambda: execute(bad, selected))
    empty = pit((one,), requests=())
    fails("SOURCE_COHORT", lambda: execute(bad, empty, ()))
    fails("SOURCE_COHORT", lambda: execute(one, empty, (spec(schema=schema),)))


@pytest.mark.parametrize("field,value", [("adjustment", "QFQ"), ("requested_session", "ALL"),
                                         ("interval", "1d"), ("symbols", ("HK.00700",))])
def test_scope_rejected(tmp_path, field, value):
    one, selected = fixture(tmp_path)
    bad = tamper(one, normalized_request=tamper(one.normalized_request, **{field: value}))
    fails("SCOPE", lambda: execute(bad, selected))


def test_duplicate_inputs_and_extra_authority(tmp_path):
    one, selected = fixture(tmp_path)
    fails("DUPLICATE_INPUT", lambda: execute_ts2_features((one, one), selected, (), dataset_as_of=AS_OF))
    fails("DUPLICATE_INPUT", lambda: execute(one, selected, (spec(), spec())))
    fails("DUPLICATE_INPUT", lambda: execute(one, tamper(selected, samples=selected.samples * 2)))
    extra = build(tmp_path / "extra", (bar(day="2025-03-04"),))
    fails("PIT_AUTHORITY", lambda: execute_ts2_features((one, extra), selected, (), dataset_as_of=AS_OF))
    fails("PIT_AUTHORITY", lambda: execute_ts2_features((), selected, (), dataset_as_of=AS_OF))


def test_clocks_equality_null_and_future(tmp_path):
    one, selected = fixture(tmp_path)
    # Last market clock equals T; every archive clock equals A.
    equal = pit((one,), cutoff=ARCHIVE)
    assert execute(one, equal, cutoff=ARCHIVE).status == "COMPLETE"
    assert execute(one, pit((one,), cutoff=None), cutoff=None).status == "COMPLETE"
    fails("CLOCK_AUTHORITY", lambda: execute(one, selected, cutoff=ARCHIVE))
    fails("CLOCK_AUTHORITY", lambda: execute(one, selected, cutoff=datetime(2026, 1, 1)))
    for kind in ("market", "archive"):
        rows = (bar(slot=0), bar(slot=1, **({"market": local("2025-03-03", 9, 41)} if kind == "market"
                                         else {"archive": AS_OF + timedelta(microseconds=1)})))
        future = build(tmp_path / kind, rows)
        # Same row identities, but now the selected evidence violates a clock.
        fails("CLOCK_AUTHORITY", lambda: execute(future, selected))
    request = tamper(selected.samples[0].request, feature_window_close=datetime(2025, 3, 3, 14, 40))
    bad = tamper(selected, samples=(tamper(selected.samples[0], request=request),))
    fails("CLOCK_AUTHORITY", lambda: execute(one, bad))


def test_conflict_precedes_clock_filter(tmp_path, monkeypatch):
    one, selected = fixture(tmp_path)
    two = build(tmp_path / "conflict", (bar(slot=1, close=130.0, source="b", archive=AS_OF + timedelta(days=1)),))
    monkeypatch.setattr(engine, "_invoke", lambda *a: pytest.fail("transform before admission"))
    fails("CANONICAL_CONFLICT", lambda: execute_ts2_features((one, two), selected, (spec(),), dataset_as_of=AS_OF))
    same_version = build(tmp_path / "same-version", (bar(slot=1, close=130.0),))
    fails("CANONICAL_CONFLICT", lambda: execute_ts2_features((one, same_version), selected, (), dataset_as_of=AS_OF))


def test_identical_backing_rows_order_and_context(tmp_path):
    one, selected = fixture(tmp_path)
    two = build(tmp_path / "two", one.bars, dates=["2025-03-03", "2025-03-04"])
    assert one.canonical_build_id != two.canonical_build_id
    both = pit((one, two))
    specs = (spec(), spec("rolling_mean"))
    first = execute_ts2_features((one, two), both, specs, dataset_as_of=AS_OF)
    reverse = execute_ts2_features((two, one), both, specs[::-1], dataset_as_of=AS_OF)
    assert first == reverse
    assert len(first.considered_canonical_build_ids) == 2
    baseline = execute(one, selected, specs)
    assert first.execution_id != baseline.execution_id
    assert [v.value for v in first.samples[0].values] == [v.value for v in baseline.samples[0].values]
    assert first.samples[0].values[0].candidate_canonical_row_version_ids == baseline.samples[0].values[0].candidate_canonical_row_version_ids


@pytest.mark.parametrize("field,value", [("association_content_id", "0" * 64),
                                         ("association_schema_id", "0" * 64),
                                         ("canonical_build_pins", ()),
                                         ("association_rows", ())])
def test_pit_closure_tamper(tmp_path, field, value):
    one, selected = fixture(tmp_path)
    fails("PIT_AUTHORITY", lambda: execute(one, tamper(selected, **{field: value})))


@pytest.mark.parametrize("field,value", [("sample_key", "0" * 64), ("sample_version_id", "0" * 64),
                                         ("feature_canonical_row_version_ids", ("0" * 64,)),
                                         ("label_canonical_row_version_ids", ("0" * 64,))])
def test_sample_identity_tamper(tmp_path, field, value):
    one, selected = fixture(tmp_path)
    sample = tamper(selected.samples[0], **{field: value})
    fails("PIT_AUTHORITY", lambda: execute(one, tamper(selected, samples=(sample,))))


def test_source_pin_gap_and_membership_closure(tmp_path):
    one, selected = fixture(tmp_path, slots=(0, 2, 3))
    pin = tamper(selected.canonical_build_pins[0], source_snapshots=())
    fails("PIT_AUTHORITY", lambda: execute(one, tamper(selected, canonical_build_pins=(pin,))))
    fails("PIT_AUTHORITY", lambda: execute(one, tamper(selected, gap_references=())))
    fails("PIT_AUTHORITY", lambda: execute(one, tamper(selected, canonical_row_version_ids=())))
    fails("CANONICAL_AUTHORITY", lambda: execute(tamper(one, source_snapshot_provenance=()), selected))
    fails("CANONICAL_AUTHORITY", lambda: execute(tamper(one, canonical_row_version_ids=()), selected))


def test_noncanonical_request_rejected_even_with_consistent_build_id(tmp_path):
    from market_vault.canonical.identity import canonical_build_id
    one = build(tmp_path, ())
    request = replace(one.normalized_request, symbols=("US.aapl",))
    forged_id = canonical_build_id(symbols=list(request.symbols), trade_dates=list(request.trade_dates),
        request_key=request, canonical_content_id=one.canonical_content_id, resolution_content_id=one.resolution_content_id,
        gap_content_id=one.gap_content_id, selected_row_version_ids=list(one.canonical_row_version_ids),
        canonical_builder_version=one.canonical_builder_version, canonical_schema_version=one.canonical_schema_version,
        materializer_version=one.materializer_version, gap_policy_version=one.gap_policy_version)
    forged = replace(one, normalized_request=request, canonical_build_id=forged_id)
    fails("CANONICAL_AUTHORITY", lambda: execute(forged, pit((), requests=()), ()))


@pytest.mark.parametrize("bad", [True, 1, float("nan"), float("inf"), float("-inf")])
def test_all_selected_numeric_inputs_fail_closed(tmp_path, monkeypatch, bad):
    one, selected = fixture(tmp_path)
    malformed = tamper(one, bars=(replace(one.bars[0], close=bad), one.bars[1]))
    monkeypatch.setattr(engine, "_invoke", lambda *a: pytest.fail("malformed numeric input invoked formula"))
    fails("CANONICAL_AUTHORITY", lambda: execute(malformed, selected, (spec(n=9223372036854775807),)))


@pytest.mark.parametrize("field,value", [("canonical_build_id", "0" * 64), ("canonical_content_id", "0" * 64),
                                         ("gap_count", 999)])
def test_canonical_identity_tamper(tmp_path, field, value):
    one, selected = fixture(tmp_path)
    fails("CANONICAL_AUTHORITY", lambda: execute(tamper(one, **{field: value}), selected))


@pytest.mark.parametrize("n", [True, 2.0, 0, -1, 9223372036854775808])
def test_window_parameter_types_and_bounds(tmp_path, n):
    one, selected = fixture(tmp_path)
    parameter = tamper(SpecParameter("window_bars", 2), value=n)
    bad = tamper(spec(), parameters=(parameter,))
    fails("SPEC_CONTRACT", lambda: execute(one, selected, (bad,)))


@pytest.mark.parametrize("change", ["fields", "order", "nullable", "int-output", "missing", "extra", "duplicate"])
def test_exact_spec_contract(tmp_path, change):
    one, selected = fixture(tmp_path)
    s = spec("candle_body") if change == "order" else spec()
    if change in ("fields", "order"):
        s = tamper(s, input_canonical_fields=("close", "open"))
    elif change in ("nullable", "int-output"):
        s = tamper(s, output=tamper(s.output, **({"nullable": True} if change == "nullable" else {"logical_type": "int64"})))
    else:
        params = () if change == "missing" else (SpecParameter("unexpected", 2),) if change == "extra" else s.parameters * 2
        s = tamper(s, parameters=params)
    fails("SPEC_CONTRACT", lambda: execute(one, selected, (s,)))


def test_huge_window_and_insufficient_are_bounded(tmp_path, monkeypatch):
    one, selected = fixture(tmp_path)
    monkeypatch.setattr(engine, "_invoke", lambda *a: pytest.fail("excluded transform invoked"))
    for n in (3, 9223372036854775807):
        result = execute(one, selected, (spec(n=n),))
        value = result.samples[0].values[0]
        assert result.status == value.status == "EXCLUDED"
        assert value.reason_code == "INSUFFICIENT_ROWS"
        assert value.value is None and value.consumed_canonical_row_version_ids == ()
        assert value.candidate_canonical_row_version_ids == selected.samples[0].feature_canonical_row_version_ids


def test_noncontiguous_tail_never_searches_older_window(tmp_path, monkeypatch):
    one, selected = fixture(tmp_path, slots=(0, 1, 3))
    monkeypatch.setattr(engine, "_invoke", lambda *a: pytest.fail("must not use old contiguous window"))
    value = execute(one, selected).samples[0].values[0]
    assert value.reason_code == "NON_CONTIGUOUS_ROWS"
    assert value.consumed_canonical_row_version_ids == ()
    assert value.candidate_canonical_row_version_ids == selected.samples[0].feature_canonical_row_version_ids[-2:]


def test_gap_outside_tail_is_not_exclusion(tmp_path):
    one, selected = fixture(tmp_path, slots=(0, 2, 3))
    assert execute(one, selected).status == "COMPLETE"


@pytest.mark.parametrize("day,slot", [("2025-03-07", 1), ("2025-03-10", 1), ("2025-11-28", 41)])
def test_dst_and_qualified_early_close_without_schedule(tmp_path, day, slot):
    one = build(tmp_path, (bar(day, slot - 1), bar(day, slot, close=125.0)))
    result = pit((one,), day, slot)
    assert execute(one, result).samples[0].values[0].value == .25
    bad_request = tamper(result.samples[0].request, anchor_market_calendar_date=local("2025-03-04").date())
    fails("SCOPE", lambda: execute(one, tamper(result, samples=(tamper(result.samples[0], request=bad_request),))))


@pytest.mark.parametrize("name", ["simple_return", "log_return", "volume_ratio"])
def test_formula_domain_errors_are_hard(tmp_path, name):
    rows = [bar(slot=0, close=0.0, low=0.0), bar(slot=1)]
    if name == "volume_ratio":
        rows[0] = replace(rows[0], volume=0.0)
    one = build(tmp_path, rows)
    fails("TRANSFORM_DOMAIN", lambda: execute(one, pit((one,)), (spec(name),)))


@pytest.mark.parametrize("output", [1, True, float("nan"), float("inf")])
def test_exact_output_type(tmp_path, monkeypatch, output):
    one, selected = fixture(tmp_path)
    monkeypatch.setattr(engine, "_invoke", lambda *a: output)
    fails("TRANSFORM_OUTPUT", lambda: execute(one, selected))


def test_negative_zero_and_actual_input_float(tmp_path, monkeypatch):
    one = build(tmp_path, (bar(slot=0), bar(slot=1)))
    result = execute(one, pit((one,)), (spec("candle_body"),))
    assert math.copysign(1, result.samples[0].values[0].value) == 1
    # Canonical allows integer volume; the TS2 formula transport does not.
    integer = tamper(one, bars=tuple(replace(b, volume=100) for b in one.bars))
    fails("CANONICAL_AUTHORITY", lambda: execute(integer, pit((one,)), (spec("rolling_volume_mean"),)))


def test_zero_samples_specs_and_both(tmp_path, monkeypatch):
    one, selected = fixture(tmp_path)
    monkeypatch.setattr(engine, "_invoke", lambda *a: pytest.fail("zero preflight invoked transform"))
    empty = pit((one,), requests=())
    zero_samples = execute(one, empty)
    assert zero_samples.status == "EMPTY" and zero_samples.samples == ()
    zero_specs = execute(one, selected, ())
    assert zero_specs.status == "COMPLETE" and zero_specs.samples[0].values == ()
    both = execute_ts2_features((), pit((), requests=()), (), dataset_as_of=AS_OF)
    assert both.status == "EMPTY" and len(both.registry_implementation_pins) == 8
    assert len({r.execution_id for r in (zero_samples, zero_specs, both)}) == 3
    unknown = tamper(spec(), transform_ref="unknown.module:callback")
    fails("REGISTRY_AUTHORITY", lambda: execute(one, empty, (unknown,)))
    fails("CLOCK_AUTHORITY", lambda: execute(one, empty, (), cutoff=datetime(2026, 1, 1)))


def test_mixed_values_participate_in_identity(tmp_path):
    one, selected = fixture(tmp_path)
    result = execute(one, selected, (spec(), spec(n=3, name="excluded")))
    assert result.status == "EXCLUDED"
    assert {v.status for v in result.samples[0].values} == {"COMPLETE", "EXCLUDED"}
    assert result.values_content_id != execute(one, selected).values_content_id
