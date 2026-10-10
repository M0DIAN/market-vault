"""Bundled exchange schedule facts; these do not qualify provider timestamps."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time


US_RTH_CALENDAR_VERSION = "nyse-us-equities-2025-2027-v1"
US_RTH_CALENDAR_START = date(2025, 1, 1)
US_RTH_CALENDAR_END = date(2027, 12, 31)
US_RTH_CALENDAR_CAPTURED_ON = "2026-10-10"
US_RTH_CALENDAR_REFERENCE = (
    "https://ir.theice.com/press/news-details/2024/"
    "NYSE-Group-Announces-2025-2026-and-2027-Holiday-and-Early-Closings-Calendar/"
    "default.aspx"
)
US_RTH_EMERGENCY_REFERENCE = (
    "https://ir.theice.com/press/news-details/2024/"
    "The-New-York-Stock-Exchange-Will-Close-Markets-on-January-9-to-Honor-the-"
    "Passing-of-Former-President-Jimmy-Carter-on-National-Day-of-Mourning/"
    "default.aspx"
)

# Exact exchange-published dates, not US federal-holiday rules. In particular,
# 2026-07-02 and 2027-12-31 are normal sessions; 2027-12-24 is a full closure.
_HOLIDAYS = (
    ("2025-01-01", "New Year's Day"),
    ("2025-01-09", "National Day of Mourning"),
    ("2025-01-20", "Martin Luther King Jr. Day"),
    ("2025-02-17", "Washington's Birthday"),
    ("2025-04-18", "Good Friday"),
    ("2025-05-26", "Memorial Day"),
    ("2025-06-19", "Juneteenth"),
    ("2025-07-04", "Independence Day"),
    ("2025-09-01", "Labor Day"),
    ("2025-11-27", "Thanksgiving Day"),
    ("2025-12-25", "Christmas Day"),
    ("2026-01-01", "New Year's Day"),
    ("2026-01-19", "Martin Luther King Jr. Day"),
    ("2026-02-16", "Washington's Birthday"),
    ("2026-04-03", "Good Friday"),
    ("2026-05-25", "Memorial Day"),
    ("2026-06-19", "Juneteenth"),
    ("2026-07-03", "Independence Day observed"),
    ("2026-09-07", "Labor Day"),
    ("2026-11-26", "Thanksgiving Day"),
    ("2026-12-25", "Christmas Day"),
    ("2027-01-01", "New Year's Day"),
    ("2027-01-18", "Martin Luther King Jr. Day"),
    ("2027-02-15", "Washington's Birthday"),
    ("2027-03-26", "Good Friday"),
    ("2027-05-31", "Memorial Day"),
    ("2027-06-18", "Juneteenth observed"),
    ("2027-07-05", "Independence Day observed"),
    ("2027-09-06", "Labor Day"),
    ("2027-11-25", "Thanksgiving Day"),
    ("2027-12-24", "Christmas Day observed"),
)
_EARLY_CLOSE_DATES = (
    date(2025, 7, 3),
    date(2025, 11, 28),
    date(2025, 12, 24),
    date(2026, 11, 27),
    date(2026, 12, 24),
    date(2027, 11, 26),
)


@dataclass(frozen=True, slots=True)
class ExchangeRTHSession:
    trade_date: date
    classification: str
    open_time: time | None
    close_time: time | None
    reason: str
    authority_reference: str = US_RTH_CALENDAR_REFERENCE
    authority_published_on: str = "2024-11-08"
    authority_version: str = US_RTH_CALENDAR_VERSION
    authority_captured_on: str = US_RTH_CALENDAR_CAPTURED_ON
    market: str = "US"
    timezone: str = "America/New_York"


def resolve_exchange_rth_session(trade_date: date) -> ExchangeRTHSession:
    """Return schedule status even when runtime conversion is unsupported.

    Covered weekdays other than the published closures use the normal core
    session. A later emergency notice requires a new reviewed calendar version;
    normalization never fetches a live calendar or guesses from observed bars.
    """
    if type(trade_date) is not date:
        raise ValueError("US RTH calendar requires a datetime.date")
    if not US_RTH_CALENDAR_START <= trade_date <= US_RTH_CALENDAR_END:
        return ExchangeRTHSession(
            trade_date, "UNSUPPORTED", None, None,
            f"outside calendar coverage {US_RTH_CALENDAR_START}..{US_RTH_CALENDAR_END}",
        )
    if trade_date.weekday() >= 5:
        return ExchangeRTHSession(trade_date, "CLOSED", None, None, "weekend")
    for value, holiday in _HOLIDAYS:
        if trade_date.isoformat() == value:
            if value == "2025-01-09":
                return ExchangeRTHSession(
                    trade_date, "CLOSED", None, None, holiday,
                    US_RTH_EMERGENCY_REFERENCE, "2024-12-30",
                )
            return ExchangeRTHSession(trade_date, "CLOSED", None, None, holiday)
    if trade_date in _EARLY_CLOSE_DATES:
        return ExchangeRTHSession(
            trade_date, "EARLY_CLOSE", time(9, 30), time(13),
            "exchange-published 13:00 early close",
        )
    return ExchangeRTHSession(
        trade_date, "NORMAL", time(9, 30), time(16), "normal core session",
    )
