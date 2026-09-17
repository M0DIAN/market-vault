"""Deeply immutable Cross-Day logical references and result records."""

from dataclasses import dataclass, replace
from datetime import date, datetime

from ..dataset.models import SpecPin, ImplementationPin
from ._validation import civil_date, digest_set, instant, integer, require, scalar, sha256, typed_tuple
from . import identity

REASONS = ("MISSING_ANCHOR_ROW", "ALIGNED_SLOT_OUTSIDE_SESSION", "ARCHIVE_FUTURE",
           "MISSING_TARGET_ROW", "INSUFFICIENT_ROWS", "NON_CONTIGUOUS_TRADING_DAY_ROWS")


def _times(value, *names):
    for name in names:
        stamp = getattr(value, name)
        if stamp is not None:
            object.__setattr__(value, name, instant(stamp, name))


def _hashes(value, *names):
    for name in names:
        sha256(getattr(value, name), name)


@dataclass(frozen=True)
class CrossDayLabelSlot:
    offset: int
    market_calendar_date: date
    event_time: datetime
    session_open: datetime
    session_close: datetime
    slot_fits: bool

    def __post_init__(self):
        integer(self.offset, "offset")
        civil_date(self.market_calendar_date, "market_calendar_date")
        _times(self, "event_time", "session_open", "session_close")
        require(self.session_open < self.session_close and self.event_time >= self.session_open,
                "invalid slot geometry")
        require(type(self.slot_fits) is bool, "slot_fits requires bool")


@dataclass(frozen=True)
class CrossDayLabelRowReference:
    offset: int
    canonical_bar_key: str
    canonical_row_version_id: str
    backing_canonical_build_ids: tuple[str, ...]
    event_time: datetime
    market_available_at: datetime
    archive_available_at: datetime

    def __post_init__(self):
        integer(self.offset, "offset", minimum=-1)
        _hashes(self, "canonical_bar_key", "canonical_row_version_id")
        ids = digest_set(self.backing_canonical_build_ids, "backing builds")
        require(bool(ids), "row requires backing evidence")
        object.__setattr__(self, "backing_canonical_build_ids", ids)
        _times(self, "event_time", "market_available_at", "archive_available_at")
        require(self.market_available_at > self.event_time, "invalid row market clock")


@dataclass(frozen=True)
class CrossDayLabelGapProof:
    offset: int
    gap_id: str
    backing_canonical_build_ids: tuple[str, ...]
    previous_canonical_row_version_id: str
    next_canonical_row_version_id: str
    missing_from_event_time: datetime
    missing_to_event_time: datetime
    proof_archive_available_at: datetime

    def __post_init__(self):
        integer(self.offset, "offset")
        _hashes(self, "gap_id", "previous_canonical_row_version_id", "next_canonical_row_version_id")
        ids = digest_set(self.backing_canonical_build_ids, "gap backing builds")
        require(bool(ids), "gap requires backing evidence")
        object.__setattr__(self, "backing_canonical_build_ids", ids)
        _times(self, "missing_from_event_time", "missing_to_event_time", "proof_archive_available_at")
        require(self.missing_from_event_time <= self.missing_to_event_time, "reversed gap")


@dataclass(frozen=True)
class CrossDayLabelDecision:
    sample_key: str
    bar_sample_version_id: str
    label_spec_pin_id: str
    schedule_pin_id: str
    dataset_as_of: datetime | None
    code: str
    interval: str
    adjustment: str
    requested_session: str
    feature_window_close: datetime
    anchor_market_calendar_date: date
    anchor_event_time: datetime
    anchor_slot: int
    anchor: CrossDayLabelRowReference | None
    required_slots: tuple[CrossDayLabelSlot, ...]
    considered_canonical_build_ids: tuple[str, ...]
    selected_rows: tuple[CrossDayLabelRowReference, ...]
    rejected_archive_rows: tuple[CrossDayLabelRowReference, ...]
    absence_proofs: tuple[CrossDayLabelGapProof, ...]
    status: str
    reason_code: str | None
    archive_limited: bool
    actual_label_end_time: datetime | None

    def __post_init__(self):
        _hashes(self, "sample_key", "bar_sample_version_id", "label_spec_pin_id", "schedule_pin_id")
        _times(self, "dataset_as_of", "feature_window_close", "anchor_event_time", "actual_label_end_time")
        civil_date(self.anchor_market_calendar_date, "anchor_market_calendar_date")
        integer(self.anchor_slot, "anchor_slot")
        require(self.code.startswith("US.") and self.interval in ("1m", "5m", "15m", "30m", "60m")
                and (self.adjustment, self.requested_session) == ("NONE", "RTH"), "unsupported decision scope")
        for name, cls in (("required_slots", CrossDayLabelSlot), ("selected_rows", CrossDayLabelRowReference),
                          ("rejected_archive_rows", CrossDayLabelRowReference), ("absence_proofs", CrossDayLabelGapProof)):
            items = typed_tuple(getattr(self, name), cls, name)
            key = (lambda p: (p.offset, identity.gap_proof_id(p))) if name == "absence_proofs" else (lambda r: r.offset)
            require(tuple(sorted(items, key=key)) == items and len({key(r) for r in items}) == len(items),
                    name + " must have unique ordered positions")
            object.__setattr__(self, name, items)
        require(bool(self.required_slots), "decision requires slots")
        ids = digest_set(self.considered_canonical_build_ids, "considered builds")
        object.__setattr__(self, "considered_canonical_build_ids", ids)
        if self.anchor is not None:
            require(type(self.anchor) is CrossDayLabelRowReference, "invalid anchor")
            object.__setattr__(self, "anchor", replace(self.anchor))
            require(self.anchor.offset == -1 and self.anchor.event_time == self.anchor_event_time,
                    "anchor slot mismatch")
        refs = self.selected_rows + self.rejected_archive_rows + self.absence_proofs
        if self.anchor is not None:
            refs += (self.anchor,)
        require(all(set(r.backing_canonical_build_ids) <= set(ids) for r in refs), "unconsidered backing evidence")
        require(type(self.archive_limited) is bool and self.archive_limited == bool(self.rejected_archive_rows),
                "archive_limited mismatch")
        require(self.status in ("COMPLETE", "INCOMPLETE"), "unsupported Label status")
        require((self.reason_code is None) if self.status == "COMPLETE" else self.reason_code in REASONS,
                "status/reason mismatch")
        require((self.anchor is None) == (self.reason_code == "MISSING_ANCHOR_ROW"), "anchor/reason mismatch")
        require(self.anchor is not None or not self.selected_rows, "missing anchor cannot consume rows")
        end = self.selected_rows[-1].market_available_at if self.selected_rows else None
        require(end == self.actual_label_end_time, "end must be last consumed market clock")
        clocks = tuple(r.market_available_at for r in self.selected_rows)
        require(all(a < b for a, b in zip(clocks, clocks[1:])), "nonincreasing consumed market clocks")
        require(end is None or end >= self.feature_window_close, "Label end before Feature close")
        if self.status == "COMPLETE":
            require(end is not None and not self.rejected_archive_rows and not self.absence_proofs
                    and tuple(r.offset for r in self.selected_rows) == tuple(s.offset for s in self.required_slots)
                    and all(s.slot_fits for s in self.required_slots), "incomplete COMPLETE decision")

    @property
    def decision_id(self):
        return identity.decision_id(self)


@dataclass(frozen=True)
class CrossDayLabelSampleBinding:
    sample_key: str
    bar_sample_version_id: str
    multi_source_sample_version_id: str | None
    schedule_pin_id: str
    decision_ids: tuple[str, ...]

    def __post_init__(self):
        _hashes(self, "sample_key", "bar_sample_version_id", "schedule_pin_id")
        if self.multi_source_sample_version_id is not None:
            sha256(self.multi_source_sample_version_id, "multi-source sample version")
        require(type(self.decision_ids) is tuple and bool(self.decision_ids), "binding requires decisions")
        digest_set(self.decision_ids, "decision IDs")

    @property
    def sample_binding_id(self):
        return identity.sample_binding_id(self)


@dataclass(frozen=True)
class CrossDayLabelValueResult:
    sample_key: str
    bar_sample_version_id: str
    multi_source_sample_version_id: str | None
    label_name: str
    spec_pin: SpecPin
    implementation_pin: ImplementationPin
    schedule_pin_id: str
    decision_id: str
    anchor_canonical_row_version_id: str | None
    consumed_rows: tuple[CrossDayLabelRowReference, ...]
    status: str
    value: float | int | None
    reason_code: str | None
    actual_label_end_time: datetime | None

    def __post_init__(self):
        _hashes(self, "sample_key", "bar_sample_version_id", "schedule_pin_id", "decision_id")
        if self.multi_source_sample_version_id is not None:
            sha256(self.multi_source_sample_version_id, "multi-source sample version")
        require(type(self.spec_pin) is SpecPin and type(self.implementation_pin) is ImplementationPin, "typed pins required")
        object.__setattr__(self, "spec_pin", replace(self.spec_pin))
        object.__setattr__(self, "implementation_pin", replace(self.implementation_pin))
        require(self.spec_pin.kind == "LABEL" and self.spec_pin.name == self.label_name, "Label pin mismatch")
        if self.anchor_canonical_row_version_id is not None:
            sha256(self.anchor_canonical_row_version_id, "anchor version")
        rows = typed_tuple(self.consumed_rows, CrossDayLabelRowReference, "consumed rows")
        require(tuple(r.offset for r in rows) == tuple(sorted({r.offset for r in rows})), "consumed order mismatch")
        object.__setattr__(self, "consumed_rows", rows)
        _times(self, "actual_label_end_time")
        require(self.actual_label_end_time == (rows[-1].market_available_at if rows else None), "value end mismatch")
        if self.status == "COMPLETE":
            require(self.reason_code is None and bool(rows) and self.anchor_canonical_row_version_id is not None,
                    "COMPLETE requires anchor, consumption and no reason")
            object.__setattr__(self, "value", scalar(self.value, "int64" if type(self.value) is int else "float64"))
        else:
            require(self.status == "INCOMPLETE" and self.reason_code in REASONS and self.value is None,
                    "invalid incomplete value")

    @property
    def value_id(self):
        return identity.value_id(self)
