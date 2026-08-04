"""Conservative internal-nominal-interval gap sidecar (policy v1).

The sidecar detects only internal nominal-interval gaps directly supported by
adjacent observed Canonical bars within the same group
(dataset_kind, code, interval, adjustment, market_calendar_date, session).
It never emits synthetic bars and never infers:

- missing bars before the first observed bar or after the last one;
- cross-session or cross-market-calendar-date gaps;
- whether the exchange was officially open;
- early-close boundaries;
- full-session completeness.

This is a report of internal nominal spacing, not an authoritative
exchange-calendar completeness judgment.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date

import pandas as pd

from .models import CanonicalBar, CanonicalGapArithmeticError

GAP_POLICY_VERSION = "internal-nominal-interval-gap-v1"
GAP_IDENTITY_ENCODING_VERSION = "v1"
GAP_ID_PREFIX = "canonical-internal-gap"


@dataclass(frozen=True)
class GapRange:
    gap_id: str
    gap_policy_version: str
    dataset_kind: str
    code: str
    interval: str
    adjustment: str
    market_calendar_date: date
    session: str
    previous_event_time: pd.Timestamp
    next_event_time: pd.Timestamp
    missing_from_event_time: pd.Timestamp
    missing_to_event_time: pd.Timestamp
    missing_bar_count: int


def gap_range_id(
    *,
    dataset_kind: str,
    code: str,
    interval: str,
    adjustment: str,
    market_calendar_date: date,
    session: str,
    previous_event_time: pd.Timestamp,
    next_event_time: pd.Timestamp,
) -> str:
    """Deterministic versioned gap identity (never Python's hash())."""
    payload = "\x1f".join(
        [
            dataset_kind,
            code,
            interval,
            adjustment,
            market_calendar_date.isoformat(),
            session,
            previous_event_time.tz_convert("UTC").isoformat(),
            next_event_time.tz_convert("UTC").isoformat(),
        ]
    )
    return hashlib.sha256(
        f"{GAP_IDENTITY_ENCODING_VERSION}|{GAP_ID_PREFIX}|{payload}".encode("utf-8")
    ).hexdigest()


def derive_internal_gap_ranges(bars: tuple[CanonicalBar, ...], interval_seconds: int) -> tuple[GapRange, ...]:
    """Derive internal nominal-interval gap ranges from observed canonical bars.

    An adjacent delta greater than one nominal interval must be an exact
    interval multiple; otherwise the materialization fails closed with a
    structured error instead of silently rounding.
    """
    gaps: list[GapRange] = []
    groups: dict[tuple, list[CanonicalBar]] = {}
    for bar in bars:
        key = (
            bar.dataset_kind,
            bar.code,
            bar.interval,
            bar.adjustment,
            bar.market_calendar_date,
            bar.session,
        )
        groups.setdefault(key, []).append(bar)

    nominal = pd.Timedelta(seconds=interval_seconds)
    for key in sorted(groups):
        group_bars = sorted(groups[key], key=lambda bar: (bar.event_time, bar.canonical_bar_key))
        for previous, current in zip(group_bars, group_bars[1:]):
            delta = current.event_time - previous.event_time
            if delta <= nominal:
                continue
            if delta % nominal != pd.Timedelta(0):
                raise CanonicalGapArithmeticError(
                    "internal adjacent delta is not an exact nominal-interval "
                    f"multiple: {previous.event_time} -> {current.event_time} "
                    f"({delta} for interval {nominal})"
                )
            missing_count = int(delta // nominal) - 1
            (
                dataset_kind,
                code,
                interval,
                adjustment,
                market_calendar_date,
                session,
            ) = key
            previous_time = previous.event_time.tz_convert("UTC")
            current_time = current.event_time.tz_convert("UTC")
            gap = GapRange(
                gap_id=gap_range_id(
                    dataset_kind=dataset_kind,
                    code=code,
                    interval=interval,
                    adjustment=adjustment,
                    market_calendar_date=market_calendar_date,
                    session=session,
                    previous_event_time=previous_time,
                    next_event_time=current_time,
                ),
                gap_policy_version=GAP_POLICY_VERSION,
                dataset_kind=dataset_kind,
                code=code,
                interval=interval,
                adjustment=adjustment,
                market_calendar_date=market_calendar_date,
                session=session,
                previous_event_time=previous_time,
                next_event_time=current_time,
                missing_from_event_time=previous_time + pd.Timedelta(seconds=interval_seconds),
                missing_to_event_time=current_time - pd.Timedelta(seconds=interval_seconds),
                missing_bar_count=missing_count,
            )
            gaps.append(gap)

    gaps.sort(
        key=lambda gap: (
            gap.dataset_kind,
            gap.code,
            gap.interval,
            gap.adjustment,
            gap.market_calendar_date,
            gap.session,
            gap.previous_event_time,
        )
    )
    return tuple(gaps)
