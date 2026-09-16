"""Explicit complete civil-date schedule declarations; no calendar discovery."""

from dataclasses import dataclass, replace
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from ._validation import civil_date, instant, record, require, sha256, typed_tuple

TRADING_DAY_SCHEDULE_SCHEMA_VERSION = "trading-day-schedule-v1"
CALENDAR_CONTRACT_VERSION = "cross-day-us-rth-calendar-contract-v1"
SCHEDULE_NORMALIZATION_VERSION = "trading-day-schedule-normalization-v1"
_ZONE = ZoneInfo("America/New_York")
_EARLY_DATES = frozenset((date(2025, 11, 28), date(2025, 12, 24)))


@dataclass(frozen=True)
class TradingDayRecord:
    market_calendar_date: date
    day_status: str
    session_open: datetime | None
    session_close: datetime | None
    session_profile: str | None

    def __post_init__(self):
        day = civil_date(self.market_calendar_date, "market_calendar_date")
        require(self.day_status in ("TRADING", "CLOSED"), "unsupported day status")
        if self.day_status == "CLOSED":
            require((self.session_open, self.session_close, self.session_profile) == (None, None, None),
                    "CLOSED must not declare session geometry")
            return
        opened = instant(self.session_open, "session_open")
        closed = instant(self.session_close, "session_close")
        early = day in _EARLY_DATES
        require(self.session_profile == ("QUALIFIED_EARLY_CLOSE" if early else "NORMAL"),
                "unqualified or mismatched session profile")
        require(opened == datetime.combine(day, time(9, 30), _ZONE)
                and closed == datetime.combine(day, time(13 if early else 16), _ZONE),
                "session geometry differs from the qualified profile")
        object.__setattr__(self, "session_open", opened)
        object.__setattr__(self, "session_close", closed)


def _validate_scalars(value):
    require(value.schedule_schema_version == TRADING_DAY_SCHEDULE_SCHEMA_VERSION, "schedule schema mismatch")
    require((value.market, value.requested_session, value.market_timezone) ==
            ("US", "RTH", "America/New_York"), "unsupported schedule scope")
    require(value.calendar_contract_version == CALENDAR_CONTRACT_VERSION, "calendar contract mismatch")
    require(value.normalization_version == SCHEDULE_NORMALIZATION_VERSION, "schedule normalization mismatch")
    start = civil_date(value.coverage_start_date, "coverage_start_date")
    end = civil_date(value.coverage_end_date, "coverage_end_date")
    require(start <= end, "reversed schedule coverage")
    require(value.coverage_complete is True, "complete schedule evidence required")
    for name in ("source_snapshot_id", "source_content_hash", "coverage_completion_evidence_id"):
        sha256(getattr(value, name), name)
    object.__setattr__(value, "archive_available_at", instant(value.archive_available_at, "archive_available_at"))


@dataclass(frozen=True)
class TradingDaySchedulePin:
    schedule_schema_version: str
    schedule_content_id: str
    market: str
    requested_session: str
    market_timezone: str
    coverage_start_date: date
    coverage_end_date: date
    source_snapshot_id: str
    source_content_hash: str
    calendar_contract_version: str
    normalization_version: str
    coverage_completion_evidence_id: str
    coverage_complete: bool
    archive_available_at: datetime

    def __post_init__(self):
        _validate_scalars(self)
        sha256(self.schedule_content_id, "schedule_content_id")


@dataclass(frozen=True)
class VerifiedTradingDaySchedule:
    schedule_schema_version: str
    market: str
    requested_session: str
    market_timezone: str
    coverage_start_date: date
    coverage_end_date: date
    daily_records: tuple[TradingDayRecord, ...]
    source_snapshot_id: str
    source_content_hash: str
    calendar_contract_version: str
    normalization_version: str
    coverage_completion_evidence_id: str
    coverage_complete: bool
    archive_available_at: datetime

    def __post_init__(self):
        _validate_scalars(self)
        days = tuple(sorted(typed_tuple(self.daily_records, TradingDayRecord, "daily_records"),
                            key=lambda r: r.market_calendar_date))
        start = self.coverage_start_date.toordinal()
        require(len(days) == self.coverage_end_date.toordinal() - start + 1,
                "schedule must cover every civil date exactly once")
        require(all(r.market_calendar_date.toordinal() == start + i for i, r in enumerate(days)),
                "duplicate or omitted schedule date")
        object.__setattr__(self, "daily_records", days)

    @property
    def schedule_content_id(self) -> str:
        from .identity import schedule_content_id
        return schedule_content_id(self)

    @property
    def pin(self) -> TradingDaySchedulePin:
        payload = record(self)
        del payload["daily_records"]
        return TradingDaySchedulePin(schedule_content_id=self.schedule_content_id, **payload)


def verify_trading_day_schedule(*, dataset_as_of=None, **declaration) -> VerifiedTradingDaySchedule:
    """Validate a supplied logical declaration, not physical provider evidence."""
    return admit_schedule(VerifiedTradingDaySchedule(**declaration), dataset_as_of)


def admit_schedule(schedule, dataset_as_of):
    require(type(schedule) is VerifiedTradingDaySchedule, "requires VerifiedTradingDaySchedule")
    schedule = replace(schedule)
    if dataset_as_of is not None:
        require(schedule.archive_available_at <= instant(dataset_as_of, "dataset_as_of"),
                "schedule evidence is archive-future")
    return schedule
