"""Real verified TS2 fixtures and L2 authority/geometry regression canaries."""

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from market_vault.cross_day import (
    CrossDayLabelError, assemble_cross_day_labels, execute_cross_day_labels, validate_cross_day_execution_result,
)
from market_vault.cross_day import identity as ids
from market_vault.cross_day.registry import built_in_cross_day_label_registry
from cross_day_helpers import AS_OF, ARCHIVE, bar, build, local, pit, run, schedule, spec
from test_cross_day_identity import SCENARIOS


@pytest.fixture
def normal(tmp_path):
    return (build(tmp_path, (bar(),)),), (build(tmp_path, (bar("2025-03-04", close=125.0),)),)


@pytest.mark.parametrize("name,daily,slot,excursion", SCENARIOS)
def test_real_verified_scenarios(tmp_path, name, daily, slot, excursion):
    sched = schedule(daily)
    features = (build(tmp_path, (bar(daily[0][0], slot),)),)
    labels = tuple(build(tmp_path, (bar(d.market_calendar_date, slot, close=125.0),))
                   for d in sched.daily_records[1:] if d.day_status == "TRADING"
                   and local(d.market_calendar_date) + timedelta(minutes=5 * (slot + 1)) <= d.session_close)
    specs = (spec(2, "maximum_favorable_excursion"),) if excursion else (spec(),)
    result = run(features, labels, sched=sched, specs=specs, day=daily[0][0], slot=slot)
    value = result.values[0]
    assert value.value == (None if name == "early_close_outside" else 0.5 if excursion else 0.25)
    assert value.reason_code == ("ALIGNED_SLOT_OUTSIDE_SESSION" if name == "early_close_outside" else None)
    assert result.decisions[0].anchor_slot == slot
    assert len(result.decisions[0].required_slots) == (2 if excursion else 1)
    assert result.association.feature_pit.samples[0].sample_key == pit(features, daily[0][0], slot).samples[0].sample_key
    if name == "dst_forward":
        assert result.decisions[0].anchor_event_time.hour == 14
        assert result.decisions[0].selected_rows[0].event_time.hour == 13
    assert validate_cross_day_execution_result(result) == result


def test_forward_uses_endpoint_only(tmp_path):
    features = (build(tmp_path, (bar(),)),)
    labels = (build(tmp_path, (bar("2025-03-05", close=125.0),)),)
    result = run(features, labels, sched=schedule((("2025-03-03", "N"), ("2025-03-04", "N"), ("2025-03-05", "N"))), specs=(spec(2),))
    assert result.values[0].value == 0.25
    assert tuple(r.offset for r in result.values[0].consumed_rows) == (1,)


@pytest.mark.parametrize("missing,reason", [(0, "INSUFFICIENT_ROWS"), (1, "NON_CONTIGUOUS_TRADING_DAY_ROWS"), (2, "MISSING_TARGET_ROW")])
def test_gap_proofs_and_incomplete_subsets(tmp_path, missing, reason):
    features = (build(tmp_path, (bar(),)),)
    labels = tuple(build(tmp_path, (bar(f"2025-03-0{4 + k}", 0), bar(f"2025-03-0{4 + k}", 2)))
        if k == missing else build(tmp_path, (bar(f"2025-03-0{4 + k}", close=125.0),)) for k in range(3))
    result = run(features, labels, specs=(spec(3, "maximum_favorable_excursion"),),
        sched=schedule(tuple((f"2025-03-0{d}", "N") for d in range(3, 7))))
    value = result.values[0]
    assert value.reason_code == reason and value.value is None
    assert tuple(r.offset for r in value.consumed_rows) == tuple(k for k in range(3) if k != missing)
    assert value.actual_label_end_time == value.consumed_rows[-1].market_available_at
    assert len(result.decisions[0].absence_proofs) == 1
    assert result.samples[0].status == "INCOMPLETE"


def test_forward_gap_endpoint_and_no_interpolation(tmp_path):
    features = (build(tmp_path, (bar(),)),)
    labels = (build(tmp_path, (bar("2025-03-04", 0), bar("2025-03-04", 2))),)
    result = run(features, labels)
    assert result.values[0].reason_code == "MISSING_TARGET_ROW"
    assert result.values[0].consumed_rows == () and result.values[0].actual_label_end_time is None


@pytest.mark.parametrize("kind", ["none", "leading", "trailing", "empty", "future_gap"])
def test_unproved_negative_authority_fails(tmp_path, kind):
    features = (build(tmp_path, (bar(),)),)
    rows = {"none": None, "leading": (bar("2025-03-04", 2),), "trailing": (bar("2025-03-04", 0),),
            "empty": (), "future_gap": (bar("2025-03-04", 0), bar("2025-03-04", 2, archive=AS_OF + timedelta(seconds=1)))}[kind]
    labels = () if rows is None else (build(tmp_path, rows),)
    with pytest.raises(CrossDayLabelError, match="FAIL AUTHORITY"):
        run(features, labels)


def test_missing_anchor_does_not_substitute(tmp_path):
    features = (build(tmp_path, (bar(slot=0),)),)
    labels = (build(tmp_path, (bar("2025-03-04"),)),)
    result = run(features, labels)
    assert result.values[0].reason_code == "MISSING_ANCHOR_ROW"
    assert result.values[0].consumed_rows == () and result.samples[0].actual_label_end_time is None
    with pytest.raises(CrossDayLabelError, match="FAIL AUTHORITY"):
        run(features, ())


@pytest.mark.parametrize("future", [False, True])
def test_archive_equality_and_future(tmp_path, future):
    features = (build(tmp_path, (bar(),)),)
    labels = (build(tmp_path, (bar("2025-03-04", archive=AS_OF + timedelta(microseconds=int(future))),)),)
    result = run(features, labels)
    assert result.values[0].reason_code == ("ARCHIVE_FUTURE" if future else None)
    assert result.decisions[0].archive_limited is future
    assert bool(result.values[0].consumed_rows) is not future
    assert len(result.decisions[0].rejected_archive_rows) == int(future)


def test_market_clock_is_not_feature_or_session_cutoff(tmp_path):
    features = (build(tmp_path, (bar(),)),)
    actual = local("2025-03-05", 19)
    labels = (build(tmp_path, (bar("2025-03-04", market=actual),)),)
    result = run(features, labels)
    assert result.values[0].actual_label_end_time == actual


def test_conflict_fails_before_archive_filter(tmp_path):
    features = (build(tmp_path, (bar(),)),)
    labels = (build(tmp_path, (bar("2025-03-04"),)),
              build(tmp_path, (bar("2025-03-04", source="b", archive=AS_OF + timedelta(days=1)),)))
    with pytest.raises(CrossDayLabelError, match="conflicting Canonical key"):
        run(features, labels)


def test_backing_considered_and_relocation(normal, tmp_path):
    features, labels = normal
    original = run(features, labels)
    unrelated = build(tmp_path, (bar("2025-03-05"),))
    expanded = run(features, labels + (unrelated,))
    old_ref, new_ref = original.decisions[0].selected_rows[0], expanded.decisions[0].selected_rows[0]
    assert ids.row_reference_id(old_ref) == ids.row_reference_id(new_ref)
    assert original.association_content_id != expanded.association_content_id
    assert original.decisions[0].decision_id != expanded.decisions[0].decision_id
    backing = build(tmp_path, labels[0].bars + (bar("2025-03-04", 2),))
    two = run(features, labels + (backing,))
    assert len(two.decisions[0].selected_rows[0].backing_canonical_build_ids) == 2
    assert ids.row_reference_id(old_ref) != ids.row_reference_id(two.decisions[0].selected_rows[0])
    assert original.values[0].value_id != two.values[0].value_id
    assert original.values[0].value == two.values[0].value
    relocated = tuple(replace(b, build_path=Path("relocated") / b.canonical_build_id,
                      bars=tuple(replace(r, snapshot_file="other/location") for r in b.bars)) for b in labels + (backing,))
    permuted = run(features, relocated[::-1], sched=replace(schedule(), daily_records=schedule().daily_records[::-1]))
    assert permuted.association_content_id == two.association_content_id
    assert permuted.values_content_id == two.values_content_id


def test_gap_backings_are_not_considered_set(tmp_path):
    features = (build(tmp_path, (bar(),)),)
    gap = build(tmp_path, (bar("2025-03-04", 0), bar("2025-03-04", 2)))
    gap_two = build(tmp_path, gap.bars + (bar("2025-03-04", 3),))
    one, two = run(features, (gap,)), run(features, (gap, gap_two))
    proof = two.decisions[0].absence_proofs[0]
    assert len(proof.backing_canonical_build_ids) == 2
    assert ids.gap_proof_id(one.decisions[0].absence_proofs[0]) != ids.gap_proof_id(proof)
    assert set(proof.backing_canonical_build_ids) < set(two.association.considered_canonical_build_ids)
    forged = replace(proof, backing_canonical_build_ids=two.association.considered_canonical_build_ids)
    decision = replace(two.decisions[0], absence_proofs=(forged,))
    with pytest.raises(CrossDayLabelError, match="closure"):
        replace(two.association, decisions=(decision,))


@pytest.mark.parametrize("where", ["feature", "label", "spec", "empty"])
def test_legacy_source_rejected(tmp_path, normal, where):
    features, labels = normal
    legacy = build(tmp_path, (bar(schema="10.9"),), schema="10.9")
    if where == "feature":
        features = (legacy,)
    elif where in ("label", "empty"):
        labels += (legacy,)
    with pytest.raises(CrossDayLabelError, match="TS2"):
        run(features, labels, specs=(spec(schema="10.9"),) if where == "spec" else None,
            requests=() if where == "empty" else None)


def test_legacy_early_close_rejected(tmp_path):
    features = (build(tmp_path, (bar("2025-11-26"),)),)
    labels = (build(tmp_path, (bar("2025-11-28", schema="10.9"),), schema="10.9"),)
    sched = schedule((("2025-11-26", "N"), ("2025-11-27", "C"), ("2025-11-28", "E")))
    with pytest.raises(CrossDayLabelError, match="TS2"):
        run(features, labels, sched=sched, day="2025-11-26")


def test_result_tampering_fails(normal):
    result = run(*normal)
    with pytest.raises(CrossDayLabelError, match="cardinality"):
        replace(result, values=())
    with pytest.raises(CrossDayLabelError, match="closure"):
        replace(result.association, sample_bindings=())
    value = replace(result.values[0], decision_id="0" * 64)
    with pytest.raises(CrossDayLabelError, match="linkage"):
        replace(result, values=(value,))
    with pytest.raises(CrossDayLabelError, match="pin mismatch"):
        replace(result, implementation_pins=(replace(result.implementation_pins[0], content_sha256="0" * 64),))
    with pytest.raises(TypeError):
        result.association.feature_pit.association_rows[0]["event_time"] = AS_OF


def test_zero_samples_and_finite_horizon(normal):
    result = run(*normal, requests=())
    assert result.values == () and result.samples == ()
    assert result.values_content_id == ids.values_content_id(())
    with pytest.raises(CrossDayLabelError, match="at least one"):
        run(*normal, specs=(), requests=())
    with pytest.raises(CrossDayLabelError, match="unregistered"):
        run(*normal, specs=(replace(spec(), transform_ref="untrusted.module:transform"),), requests=())
    with pytest.raises(CrossDayLabelError, match="schedule coverage"):
        run(*normal, specs=(spec(10 ** 30),))


def test_fingerprint_failure(normal, monkeypatch):
    import market_vault.cross_day.registry as registry
    def fail(*args):
        raise OSError("no stable source")
    monkeypatch.setattr(registry, "_module_source_sha256", fail)
    with pytest.raises(CrossDayLabelError, match="stable") as caught:
        run(*normal, requests=())
    assert isinstance(caught.value.__cause__, OSError)


def test_selected_revision_identity_even_equal_value(tmp_path, normal):
    features, labels = normal
    changed = (build(tmp_path, (bar("2025-03-04", close=125.0, source="b"),)),)
    one, two = run(features, labels), run(features, changed)
    assert one.values[0].value == two.values[0].value
    assert one.decisions[0].decision_id != two.decisions[0].decision_id
    assert one.values_content_id != two.values_content_id


def test_multi_spec_sample_end_and_order(tmp_path, normal):
    features, labels = normal
    labels += (build(tmp_path, (bar("2025-03-05", close=140.0),)),)
    sched = schedule((("2025-03-03", "N"), ("2025-03-04", "N"), ("2025-03-05", "N")))
    specs = (spec(name="first"), spec(2, name="second"))
    one = run(features, labels, sched=sched, specs=specs)
    two = run(features, labels[::-1], sched=sched, specs=specs[::-1])
    assert one.values_content_id == two.values_content_id
    assert one.association_content_id == two.association_content_id
    assert one.samples[0].actual_label_end_time == max(v.actual_label_end_time for v in one.values)


def test_incomplete_precedence_keeps_proof_obligations(tmp_path):
    features = (build(tmp_path, (bar(slot=0),)),)
    # Missing anchor wins over archive-future, but archive diagnostics remain.
    labels = (build(tmp_path, (bar("2025-03-04", archive=AS_OF + timedelta(days=1)),)),)
    result = run(features, labels)
    assert result.values[0].reason_code == "MISSING_ANCHOR_ROW"
    assert result.decisions[0].archive_limited and not result.values[0].consumed_rows
    features = (build(tmp_path, (bar(),)),)
    labels += (build(tmp_path, (bar("2025-03-05", 0), bar("2025-03-05", 2))),)
    sched = schedule((("2025-03-03", "N"), ("2025-03-04", "N"), ("2025-03-05", "N")))
    result = run(features, labels, sched=sched, specs=(spec(2, "maximum_favorable_excursion"),))
    assert result.values[0].reason_code == "ARCHIVE_FUTURE"
    assert result.decisions[0].absence_proofs
    with pytest.raises(CrossDayLabelError, match="FAIL AUTHORITY"):
        run(features, labels[:1], sched=sched, specs=(spec(2, "maximum_favorable_excursion"),))


def test_split_uses_actual_consumption_only(tmp_path):
    from market_vault.dataset import ChronologicalSplitSample, assign_chronological_splits
    from test_chronological_splits import make_spec
    features = (build(tmp_path, (bar(),)),)
    labels = (build(tmp_path, (bar("2025-03-04", market=local("2025-03-05", 19)),)),)
    result = run(features, labels)
    sample = result.samples[0]
    fact = ChronologicalSplitSample(sample.sample_key, result.values[0].bar_sample_version_id,
        result.decisions[0].feature_window_close, sample.status, sample.actual_label_end_time)
    split_spec = make_spec(train_end_date=date(2025, 3, 4), validation_end_date=date(2025, 3, 6), test_end_date=date(2025, 3, 8))
    split = assign_chronological_splits((fact,), split_spec)
    assert split.assignments[0].assignment_status == "PURGED"
    incomplete = replace(fact, label_status="INCOMPLETE")
    excluded = assign_chronological_splits((incomplete,), split_spec)
    assert excluded.assignments[0].reason_code == "INCOMPLETE_LABEL"
