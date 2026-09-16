"""Schedule-bound Label association; never reruns Feature PIT selection."""

from dataclasses import dataclass, replace
from datetime import timedelta

from ..dataset.encoding import DatasetError
from ..dataset.spec_models import LabelSpec
from ..dataset.pit_models import PITAssemblyResult
from ..canonical.reader import VerifiedCanonicalBuild
from ._authority import INTERVAL_MINUTES, admit_builds, admit_feature_pit, gap_boundary_rows, reconcile
from ._validation import CrossDayLabelError, instant, require, typed_tuple
from . import identity
from .models import CrossDayLabelDecision, CrossDayLabelGapProof, CrossDayLabelRowReference, CrossDayLabelSlot, CrossDayLabelSampleBinding
from .registry import admit_specs, built_in_cross_day_label_registry
from .schedule import VerifiedTradingDaySchedule, admit_schedule


def _reference(offset, resolved):
    bar = resolved.bar
    return CrossDayLabelRowReference(offset, bar.canonical_bar_key, bar.canonical_row_version_id,
                                    resolved.build_ids, bar.event_time, bar.market_available_at, bar.archive_available_at)


def _proofs(offset, event, request, builds, cutoff):
    grouped = {}
    for build in builds:
        for gap in build.gap_ranges:
            if ((gap.code, gap.interval, gap.adjustment, gap.market_calendar_date, gap.session) !=
                    (request.code, request.interval, request.adjustment, event.date(), "RTH")):
                # event.date() is UTC; all qualified US RTH events share their UTC civil date.
                continue
            nominal = timedelta(minutes=INTERVAL_MINUTES[request.interval])
            if not (gap.missing_from_event_time <= event <= gap.missing_to_event_time
                    and (event - gap.missing_from_event_time) % nominal == timedelta(0)):
                continue
            previous, following = gap_boundary_rows(build, gap)
            archive = max(previous.archive_available_at, following.archive_available_at)
            if cutoff is not None and archive > cutoff:
                continue
            key = (gap.gap_id, previous.canonical_row_version_id, following.canonical_row_version_id,
                   gap.missing_from_event_time, gap.missing_to_event_time, archive)
            grouped.setdefault(key, []).append(build.canonical_build_id)
    result = tuple(CrossDayLabelGapProof(offset, key[0], tuple(sorted(ids)), *key[1:]) for key, ids in grouped.items())
    require(bool(result), "FAIL AUTHORITY: fitting required slot has no exact row or archived internal gap proof")
    return tuple(sorted(result, key=identity.gap_proof_id))


def _facts(pit, feature_builds, label_builds, schedule, specs, cutoff):
    schedule = admit_schedule(schedule, cutoff)
    admitted_specs = admit_specs(specs)
    feature_builds = admit_builds(feature_builds)
    label_builds = admit_builds(label_builds)
    pit, feature_rows = admit_feature_pit(pit, feature_builds, cutoff)
    combined = {b.canonical_build_id: b for b in feature_builds}
    for build in label_builds:
        previous = combined.get(build.canonical_build_id)
        if previous is not None:
            # Descriptive paths do not distinguish the same verified logical build.
            require(previous.canonical_content_id == build.canonical_content_id
                    and previous.gap_ranges == build.gap_ranges, "conflicting repeated build")
        combined[build.canonical_build_id] = build
    builds = tuple(combined[k] for k in sorted(combined))
    rows = reconcile(builds)
    considered = tuple(combined[k].canonical_build_id for k in sorted(combined))
    days = {d.market_calendar_date: d for d in schedule.daily_records}
    schedule_id = identity.schedule_pin_id(schedule.pin)
    decisions, bindings = [], []
    for sample in pit.samples:
        request = sample.request
        day = days.get(request.anchor_market_calendar_date)
        require(day is not None and day.day_status == "TRADING", "anchor date requires schedule TRADING authority")
        nominal = timedelta(minutes=INTERVAL_MINUTES[request.interval])
        event = request.feature_window_close - nominal
        delta = event - day.session_open
        require(delta >= timedelta(0) and delta % nominal == timedelta(0)
                and event + nominal <= day.session_close, "invalid full nominal anchor slot")
        slot = delta // nominal
        targets = tuple(d for d in schedule.daily_records if d.market_calendar_date > day.market_calendar_date
                        and d.day_status == "TRADING")
        selected_anchor = [feature_rows[v] for v in sample.feature_canonical_row_version_ids
                           if feature_rows[v].bar.event_time == event]
        require(len(selected_anchor) <= 1, "ambiguous selected Feature anchor")
        anchor = None if not selected_anchor else _reference(-1, rows[selected_anchor[0].bar.canonical_row_version_id])
        sample_decisions = []
        for spec, contract in admitted_specs:
            n = spec.horizon.value
            require(n <= len(targets), "insufficient complete schedule coverage for horizon")
            offsets = (n - 1,) if contract.offset_shape == "TARGET_ONLY" else range(n)
            slots, eligible, rejected, proofs, missing = [], [], [], [], []
            for offset in offsets:
                target = targets[offset]
                expected = target.session_open + slot * nominal
                fits = expected + nominal <= target.session_close
                require(fits or target.session_profile == "QUALIFIED_EARLY_CLOSE", "normal-session slot mismatch")
                slots.append(CrossDayLabelSlot(offset, target.market_calendar_date, expected,
                                               target.session_open, target.session_close, fits))
                if not fits:
                    continue
                candidates = [r for r in rows.values() if
                    (r.bar.code, r.bar.interval, r.bar.adjustment, r.bar.requested_session, r.bar.session,
                     r.bar.market_calendar_date, r.bar.event_time) ==
                    (request.code, request.interval, request.adjustment, "RTH", "RTH", target.market_calendar_date, expected)]
                require(len(candidates) <= 1, "conflicting required row")
                if candidates:
                    ref = _reference(offset, candidates[0])
                    (rejected if cutoff is not None and ref.archive_available_at > cutoff else eligible).append(ref)
                else:
                    proofs.extend(_proofs(offset, expected, request, builds, cutoff))
                    missing.append(offset)
            reason = ("MISSING_ANCHOR_ROW" if anchor is None else
                      "ALIGNED_SLOT_OUTSIDE_SESSION" if any(not s.slot_fits for s in slots) else
                      "ARCHIVE_FUTURE" if rejected else
                      "MISSING_TARGET_ROW" if n - 1 in missing else
                      "INSUFFICIENT_ROWS" if 0 in missing else
                      "NON_CONTIGUOUS_TRADING_DAY_ROWS" if missing else None)
            selected = tuple(eligible) if anchor is not None else ()
            decision = CrossDayLabelDecision(
                sample.sample_key, sample.sample_version_id, identity.label_spec_pin_id(spec), schedule_id, cutoff,
                request.code, request.interval, request.adjustment, request.requested_session, request.feature_window_close,
                day.market_calendar_date, event, slot, anchor, tuple(slots), considered, selected, tuple(rejected),
                tuple(sorted(proofs, key=lambda p: (p.offset, identity.gap_proof_id(p)))),
                "COMPLETE" if reason is None else "INCOMPLETE", reason, bool(rejected),
                selected[-1].market_available_at if selected else None)
            decisions.append(decision)
            sample_decisions.append(decision.decision_id)
        bindings.append(CrossDayLabelSampleBinding(sample.sample_key, sample.sample_version_id, None,
                                                 schedule_id, tuple(sample_decisions)))
    return (pit, feature_builds, label_builds, schedule, tuple(s for s, _ in admitted_specs),
            tuple(decisions), tuple(bindings), considered)


@dataclass(frozen=True)
class CrossDayLabelAssemblyResult:
    feature_pit: PITAssemblyResult
    feature_builds: tuple[VerifiedCanonicalBuild, ...]
    label_builds: tuple[VerifiedCanonicalBuild, ...]
    schedule: VerifiedTradingDaySchedule
    label_specs: tuple[LabelSpec, ...]
    dataset_as_of: object
    decisions: tuple[CrossDayLabelDecision, ...]
    sample_bindings: tuple[CrossDayLabelSampleBinding, ...]

    def __post_init__(self):
        cutoff = None if self.dataset_as_of is None else instant(self.dataset_as_of, "dataset_as_of")
        facts = _facts(self.feature_pit, self.feature_builds, self.label_builds, self.schedule, self.label_specs, cutoff)
        decisions = typed_tuple(self.decisions, CrossDayLabelDecision, "decisions")
        bindings = typed_tuple(self.sample_bindings, CrossDayLabelSampleBinding, "sample_bindings")
        require(decisions == facts[5] and bindings == facts[6], "association/evidence closure mismatch")
        for name, value in zip(("feature_pit", "feature_builds", "label_builds", "schedule", "label_specs", "decisions", "sample_bindings"), facts):
            object.__setattr__(self, name, value)
        object.__setattr__(self, "dataset_as_of", cutoff)

    @property
    def considered_canonical_build_ids(self):
        return tuple(sorted({b.canonical_build_id for b in self.feature_builds + self.label_builds}))

    @property
    def association_content_id(self):
        return identity.association_content_id(self.schedule.pin, self.label_specs, self.considered_canonical_build_ids,
                                               self.decisions, self.sample_bindings)


def _assemble(pit, feature_builds, label_builds, schedule, label_specs, dataset_as_of):
    cutoff = None if dataset_as_of is None else instant(dataset_as_of, "dataset_as_of")
    facts = _facts(pit, feature_builds, label_builds, schedule, label_specs, cutoff)
    return CrossDayLabelAssemblyResult(*facts[:5], cutoff, facts[5], facts[6])


def assemble_cross_day_labels(pit_result: PITAssemblyResult, feature_builds: tuple,
                             label_builds: tuple, schedule: VerifiedTradingDaySchedule,
                             label_specs: tuple, *, dataset_as_of) -> CrossDayLabelAssemblyResult:
    """Admit explicit Feature closure and separate future evidence into a sidecar."""
    try:
        admit_specs(label_specs, built_in_cross_day_label_registry())
        return _assemble(pit_result, feature_builds, label_builds, schedule, label_specs, dataset_as_of)
    except CrossDayLabelError:
        raise
    except (DatasetError, ValueError, TypeError, OverflowError) as exc:
        raise CrossDayLabelError("Cross-Day association admission failed: " + str(exc)) from exc
