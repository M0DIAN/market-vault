"""Validate supplied L2 records without constructing/reassembling an association."""

from datetime import timedelta

from ..cross_day import identity as ids
from ..cross_day._authority import INTERVAL_MINUTES, gap_boundary_rows
from ..cross_day.models import (
    CrossDayLabelDecision, CrossDayLabelGapProof, CrossDayLabelRowReference,
    CrossDayLabelSampleBinding, CrossDayLabelSlot, CrossDayLabelValueResult,
)
from ..dataset.specs import feature_label_spec_pin
from ..dataset.identity import _spec_digest
from ._validation import checked_record, digest, numeric, records, require


def _row_key(bar):
    return (bar.code, bar.interval, bar.adjustment, bar.requested_session, bar.session,
            bar.market_calendar_date, bar.event_time)


def _reference(ref, offset, resolved):
    code = "CROSS_DAY_BINDING"
    checked_record(ref, CrossDayLabelRowReference, code)
    bar = resolved.bar
    require((ref.offset, ref.canonical_bar_key, ref.canonical_row_version_id,
             ref.backing_canonical_build_ids, ref.event_time, ref.market_available_at, ref.archive_available_at) ==
            (offset, bar.canonical_bar_key, bar.canonical_row_version_id, resolved.build_ids,
             bar.event_time, bar.market_available_at, bar.archive_available_at), code,
            "exact row/backing/provenance mismatch")
    digest(ids.row_reference_id(ref))


def _gap_inventory(builds):
    grouped = {}
    for build in builds:
        for gap in build.gap_ranges:
            previous, following = gap_boundary_rows(build, gap)
            key = (gap.code, gap.interval, gap.adjustment, gap.market_calendar_date, gap.session,
                   gap.gap_id, previous.canonical_row_version_id, following.canonical_row_version_id,
                   gap.missing_from_event_time, gap.missing_to_event_time,
                   max(previous.archive_available_at, following.archive_available_at))
            grouped.setdefault(key, set()).add(build.canonical_build_id)
    return tuple((key, tuple(sorted(value))) for key, value in grouped.items())


def _verify_absence(proofs, offset, slot, request, inventory, cutoff, nominal):
    code = "CROSS_DAY_BINDING"
    expected = {}
    for key, backing in inventory:
        if key[:5] != (request.code, request.interval, request.adjustment, slot.market_calendar_date, "RTH"):
            continue
        if (key[8] <= slot.event_time <= key[9]
                and (slot.event_time - key[8]) % nominal == timedelta(0)
                and (cutoff is None or key[10] <= cutoff)):
            expected[(key[5], key[6], key[7], key[8], key[9], key[10], backing)] = True
    require(bool(expected), code, "recorded absence lacks archived exact internal proof")
    actual = []
    for proof in proofs:
        checked_record(proof, CrossDayLabelGapProof, code)
        require(proof.offset == offset, code, "proof/slot offset mismatch")
        actual.append((proof.gap_id, proof.previous_canonical_row_version_id, proof.next_canonical_row_version_id,
                       proof.missing_from_event_time, proof.missing_to_event_time,
                       proof.proof_archive_available_at, proof.backing_canonical_build_ids))
        digest(ids.gap_proof_id(proof))
    require(len(set(actual)) == len(actual), "DUPLICATE_INPUT", "duplicate recorded gap proof")
    require(set(actual) == set(expected), code, "gap proof inventory/backing mismatch")


def verify_labels(association, execution, pit, a3, schedule, builds, rows, admitted_specs, cutoff):
    code = "CROSS_DAY_BINDING"
    require(association.feature_pit == pit and association.observation_pit == a3,
            code, "L2 Feature/A3 recorded closure differs")
    require(execution.association == association, code, "L2 execution has a different association")
    require(association.schedule == schedule and execution.association.schedule == schedule,
            "SCHEDULE_BINDING", "L2 schedule copy mismatch")
    require(association.dataset_as_of == cutoff, "CLOCK_AUTHORITY", "L2 cutoff mismatch")
    specs = tuple(s for s, _ in admitted_specs)
    require(association.label_specs == specs, code, "L2 spec ordering/closure mismatch")
    considered = tuple(b.canonical_build_id for b in builds)
    require(association.considered_canonical_build_ids == considered, code, "L2 considered union mismatch")
    decisions = records(association.decisions, CrossDayLabelDecision,
                        lambda d: (d.sample_key, d.label_spec_pin_id), code)
    expected_keys = tuple((s.sample_key, ids.label_spec_pin_id(spec)) for s in pit.samples for spec in specs)
    require(decisions == association.decisions and tuple((d.sample_key, d.label_spec_pin_id) for d in decisions) ==
            expected_keys, code, "L2 decision cross-product mismatch")
    bindings = records(association.sample_bindings, CrossDayLabelSampleBinding, lambda b: b.sample_key, code)
    require(bindings == association.sample_bindings and tuple(b.sample_key for b in bindings) ==
            tuple(s.sample_key for s in pit.samples), code, "L2 sample set mismatch")
    by_sample = {s.sample_key: s for s in pit.samples}
    versions = {b.sample_key: b.multi_source_sample_version_id for b in a3.sample_bindings}
    by_spec = {ids.label_spec_pin_id(s): (s, reg) for s, reg in admitted_specs}
    row_index = {_row_key(r.bar): r for r in rows.values()}
    require(len(row_index) == len(rows), code, "ambiguous Canonical exact slot")
    gaps = _gap_inventory(builds)
    days = {d.market_calendar_date: d for d in schedule.daily_records}
    schedule_id = ids.schedule_pin_id(schedule.pin)
    for decision in decisions:
        checked_record(decision, CrossDayLabelDecision, code)
        sample = by_sample[decision.sample_key]
        req = sample.request
        spec, reg = by_spec[decision.label_spec_pin_id]
        day = days.get(req.anchor_market_calendar_date)
        require(day is not None and day.day_status == "TRADING", "SCHEDULE_BINDING", "anchor schedule absent")
        nominal = timedelta(minutes=INTERVAL_MINUTES[req.interval])
        event = req.feature_window_close - nominal
        delta = event - day.session_open
        require(delta >= timedelta(0) and delta % nominal == timedelta(0)
                and event + nominal <= day.session_close, "SCHEDULE_BINDING", "invalid nominal anchor slot")
        anchor_slot = delta // nominal
        require((decision.bar_sample_version_id, decision.schedule_pin_id, decision.dataset_as_of,
                 decision.code, decision.interval, decision.adjustment, decision.requested_session,
                 decision.feature_window_close, decision.anchor_market_calendar_date,
                 decision.anchor_event_time, decision.anchor_slot, decision.considered_canonical_build_ids) ==
                (sample.sample_version_id, schedule_id, cutoff, req.code, req.interval, req.adjustment,
                 req.requested_session, req.feature_window_close, req.anchor_market_calendar_date,
                 event, anchor_slot, considered), code, "L2 repeated Feature/scope/considered facts differ")
        anchors = tuple(rows[v] for v in sample.feature_canonical_row_version_ids if rows[v].bar.event_time == event)
        require(len(anchors) <= 1, code, "ambiguous PIT anchor")
        if anchors:
            _reference(decision.anchor, -1, anchors[0])
        else:
            require(decision.anchor is None, code, "unselected anchor supplied")
        targets = tuple(d for d in schedule.daily_records if d.day_status == "TRADING"
                        and d.market_calendar_date > req.anchor_market_calendar_date)
        count = spec.horizon.value
        require(count <= len(targets), "SCHEDULE_BINDING", "insufficient complete future schedule")
        offsets = (count - 1,) if reg.offset_shape == "TARGET_ONLY" else tuple(range(count))
        require(tuple(s.offset for s in decision.required_slots) == offsets, code, "required slot cardinality mismatch")
        selected = {r.offset: r for r in decision.selected_rows}
        rejected = {r.offset: r for r in decision.rejected_archive_rows}
        proofs = {o: tuple(p for p in decision.absence_proofs if p.offset == o) for o in offsets}
        require(set(selected) <= set(offsets) and set(rejected) <= set(offsets)
                and all(p.offset in offsets for p in decision.absence_proofs), code, "extra recorded evidence offset")
        missing, eligible_offsets, future_offsets = [], [], []
        outside = False
        for slot in decision.required_slots:
            checked_record(slot, CrossDayLabelSlot, code)
            target = targets[slot.offset]
            expected_event = target.session_open + anchor_slot * nominal
            fits = expected_event + nominal <= target.session_close
            require((slot.market_calendar_date, slot.event_time, slot.session_open, slot.session_close, slot.slot_fits) ==
                    (target.market_calendar_date, expected_event, target.session_open, target.session_close, fits),
                    "SCHEDULE_BINDING", "recorded target geometry differs")
            require(fits or target.session_profile == "QUALIFIED_EARLY_CLOSE", "SCHEDULE_BINDING", "normal slot does not fit")
            if not fits:
                outside = True
                require(slot.offset not in selected and slot.offset not in rejected and not proofs[slot.offset],
                        code, "non-fitting slot has evidence")
                continue
            resolved = row_index.get((req.code, req.interval, req.adjustment, "RTH", "RTH",
                                      target.market_calendar_date, expected_event))
            if resolved is None:
                _verify_absence(proofs[slot.offset], slot.offset, slot, req, gaps, cutoff, nominal)
                missing.append(slot.offset)
                require(slot.offset not in selected and slot.offset not in rejected, code, "row conflicts with absence")
            else:
                require(not proofs[slot.offset], code, "gap proof conflicts with exact row")
                future = cutoff is not None and resolved.bar.archive_available_at > cutoff
                if future:
                    future_offsets.append(slot.offset)
                    _reference(rejected.get(slot.offset), slot.offset, resolved)
                elif decision.anchor is not None:
                    eligible_offsets.append(slot.offset)
                    _reference(selected.get(slot.offset), slot.offset, resolved)
        require(tuple(selected) == tuple(eligible_offsets) and tuple(rejected) == tuple(future_offsets),
                code, "selected/rejected recorded row membership differs")
        reason = ("MISSING_ANCHOR_ROW" if decision.anchor is None else
                  "ALIGNED_SLOT_OUTSIDE_SESSION" if outside else "ARCHIVE_FUTURE" if rejected else
                  "MISSING_TARGET_ROW" if count - 1 in missing else "INSUFFICIENT_ROWS" if 0 in missing else
                  "NON_CONTIGUOUS_TRADING_DAY_ROWS" if missing else None)
        require((decision.status, decision.reason_code, decision.archive_limited, decision.actual_label_end_time) ==
                ("COMPLETE" if reason is None else "INCOMPLETE", reason, bool(rejected),
                 decision.selected_rows[-1].market_available_at if decision.selected_rows else None),
                code, "L2 reason/end precedence mismatch")
        digest(decision.decision_id)
    for binding in bindings:
        checked_record(binding, CrossDayLabelSampleBinding, code)
        require((binding.bar_sample_version_id, binding.multi_source_sample_version_id,
                 binding.schedule_pin_id, binding.decision_ids) ==
                (by_sample[binding.sample_key].sample_version_id, versions[binding.sample_key], schedule_id,
                 tuple(d.decision_id for d in decisions if d.sample_key == binding.sample_key)),
                code, "L2/A3 binding closure differs")
        digest(binding.sample_binding_id)
    used = {reg.transform_ref: reg for _, reg in admitted_specs}
    require(execution.implementation_pins == tuple(used[k].implementation_pin for k in sorted(used))
            and execution.implementation_source_hashes == tuple((k, used[k].implementation_source_sha256) for k in sorted(used)),
            "IMPLEMENTATION_BINDING", "L2 fixed registry proof differs")
    values = records(execution.values, CrossDayLabelValueResult,
                     lambda v: (v.sample_key, _spec_digest(v.spec_pin)), code)
    require(values == execution.values and len(values) == len(decisions), code, "L2 value cardinality/order differs")
    for value, decision in zip(values, decisions):
        checked_record(value, CrossDayLabelValueResult, code)
        spec, reg = by_spec[decision.label_spec_pin_id]
        require((value.sample_key, value.bar_sample_version_id, value.multi_source_sample_version_id,
                 value.label_name, value.spec_pin, value.implementation_pin, value.schedule_pin_id,
                 value.decision_id, value.anchor_canonical_row_version_id, value.consumed_rows,
                 value.status, value.reason_code, value.actual_label_end_time) ==
                (decision.sample_key, decision.bar_sample_version_id, versions[decision.sample_key],
                 spec.name, feature_label_spec_pin(spec), reg.implementation_pin, schedule_id, decision.decision_id,
                 None if decision.anchor is None else decision.anchor.canonical_row_version_id,
                 decision.selected_rows, decision.status, decision.reason_code, decision.actual_label_end_time),
                code, "L2 value/decision/spec closure differs")
        if value.status == "COMPLETE":
            numeric(value.value, reg.output_logical_type, code)
        else:
            require(value.value is None, code, "incomplete Label must be null")
    digest(association.association_content_id)
    digest(execution.values_content_id)
    return execution.samples
