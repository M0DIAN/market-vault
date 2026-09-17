"""Explicit in-memory Cross-Day Feature proposals, without upstream execution."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ..cross_day._authority import INTERVAL_MINUTES
from ..cross_day.registry import admit_specs
from ..cross_day.schedule import VerifiedTradingDaySchedule, admit_schedule, _ZONE
from ..dataset.models import DatasetScope
from ..dataset.pit_identity import pit_sample_key
from ..dataset.pit_models import PITSampleRequest, _normalize_text
from ..dataset.spec_models import LabelSpec
from ._validation import checked_record, cutoff, records, require, stage

MULTI_SOURCE_CROSS_DAY_SAMPLE_GENERATOR_VERSION = "multi-source-cross-day-sample-generator-v1"
_INT64_MAX = 9223372036854775807


def _count(value, name, minimum):
    require(type(value) is int and minimum <= value <= _INT64_MAX,
            "SPEC_CONTRACT", name + " must be an actual int64 in the admitted range")
    return value


@dataclass(frozen=True, slots=True)
class CrossDayAnchor:
    """One explicit proposal in the supplied trading session's nominal slots."""

    code: str
    market_calendar_date: date
    anchor_slot: int

    def __post_init__(self):
        require(type(self.code) is str and type(self.market_calendar_date) is date,
                "INPUT_TYPE", "anchor requires an exact string and civil date")
        with stage("SCOPE"):
            object.__setattr__(self, "code", _normalize_text(self.code, "code", upper=True))
        _count(self.anchor_slot, "anchor_slot", 0)


def generate_cross_day_feature_requests(
    *,
    scope: DatasetScope,
    anchors: tuple[CrossDayAnchor, ...],
    feature_window_bars: int,
    schedule: VerifiedTradingDaySchedule,
    label_specs: tuple[LabelSpec, ...],
    dataset_as_of: datetime | None,
) -> tuple[PITSampleRequest, ...]:
    """Validate the entire proposal, then emit existing Feature-only PIT requests."""
    dataset_as_of = cutoff(dataset_as_of)
    with stage("SCOPE"):
        scope = checked_record(scope, DatasetScope, "INPUT_TYPE")
        require(scope.symbols and scope.trade_dates and all(s.startswith("US.") for s in scope.symbols)
                and scope.interval in INTERVAL_MINUTES and scope.adjustment == "NONE"
                and scope.requested_session == "RTH", "SCOPE", "unsupported Cross-Day scope")
    n = _count(feature_window_bars, "feature_window_bars", 1)
    with stage("SPEC_CONTRACT"):
        require(type(label_specs) is tuple and all(type(s) is LabelSpec for s in label_specs),
                "INPUT_TYPE", "exact LabelSpec tuple required")
        require(len({s.name for s in label_specs}) == len(label_specs),
                "DUPLICATE_INPUT", "duplicate semantic Label name")
        # Default admission uses closed metadata, not the source-reading pin registry.
        admitted_specs = admit_specs(label_specs)
        horizon = max(_count(s.horizon.value, "Label horizon", 1) for s, _ in admitted_specs)
    with stage("SCHEDULE_BINDING"):
        verified = admit_schedule(schedule, dataset_as_of)
        require(verified == schedule, "SCHEDULE_BINDING", "schedule normalization mismatch")
    with stage("INPUT_TYPE"):
        anchors = records(anchors, CrossDayAnchor,
                          lambda a: (a.code, a.market_calendar_date, a.anchor_slot))
        anchors = tuple(checked_record(a, CrossDayAnchor, "INPUT_TYPE") for a in anchors)

    days = {r.market_calendar_date: r for r in verified.daily_records}
    trading = tuple(r.market_calendar_date for r in verified.daily_records if r.day_status == "TRADING")
    trading_index = {day: i for i, day in enumerate(trading)}
    delta = timedelta(minutes=INTERVAL_MINUTES[scope.interval])
    requests = []
    for anchor in anchors:
        require(anchor.code in scope.symbols and anchor.market_calendar_date in scope.trade_dates,
                "SCOPE", "anchor outside declared scope")
        day = days.get(anchor.market_calendar_date)
        require(day is not None and day.day_status == "TRADING",
                "SCHEDULE_BINDING", "anchor requires an explicit TRADING record")
        # Bound multiplication by the supplied session, never by caller-sized ranges.
        slots = (day.session_close - day.session_open) // delta
        require(anchor.anchor_slot < slots, "SCOPE", "anchor nominal bar does not fit session")
        require(n <= anchor.anchor_slot + 1, "SPEC_CONTRACT", "Feature window crosses session open")
        future_count = len(trading) - trading_index[anchor.market_calendar_date] - 1
        require(horizon <= future_count, "SCHEDULE_BINDING", "insufficient future trading-day coverage")
        # Full civil-date completeness was verified above. Future slot fit belongs to L2.
        with stage("SCOPE"):
            close = day.session_open + (anchor.anchor_slot + 1) * delta
            start = close - n * delta
            require(day.session_open <= start < close <= day.session_close
                    and start.astimezone(_ZONE).date() == anchor.market_calendar_date
                    and close.astimezone(_ZONE).date() == anchor.market_calendar_date,
                    "SCOPE", "Feature window outside anchor session/date")
            requests.append(PITSampleRequest(anchor.code, scope.interval, scope.adjustment,
                scope.requested_session, anchor.market_calendar_date, start, close,
                label_window_start=None, label_window_close=None))
    return tuple(sorted(requests, key=pit_sample_key))
