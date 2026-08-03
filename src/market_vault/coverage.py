from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .backfill import missing_coverage_ranges
from .models import Settings
from .storage import Catalog


@dataclass
class MarketBarCoverageState:
    """Pure-local trading-day-level coverage classification shared by the
    coverage audit and the intraday integrity audit."""

    calendar_scope_type: str
    calendar_scope_value: str
    start_date: date
    end_date: date
    expected_trade_dates: list[date]
    calendar_coverage_gaps: list[tuple[date, date]]
    complete_items: set[tuple[str, date]]
    present_items: set[tuple[str, date]]
    incomplete_reasons: dict[tuple[str, date], list[str]]

    @property
    def incomplete_items(self) -> set[tuple[str, date]]:
        return self.present_items - self.complete_items


def load_market_bar_coverage_state(
    settings: Settings,
    *,
    scope_type: str,
    scope_value: str,
    symbols: list[str],
    start_date: date,
    end_date: date,
    interval: str,
    requested_session: str,
    adjustment: str,
    source_schema_version: str,
) -> MarketBarCoverageState:
    """Compute calendar coverage, expected trade dates, and the COMPLETE /
    PRESENT / INCOMPLETE classification for the exact request key.

    Reuses the same completion semantics as the backfill:
    Catalog.completed_market_bar_items / present_market_bar_items /
    incomplete_market_bar_item_reasons. Pure local, never touches OpenD.
    """
    catalog = Catalog(settings)
    coverage_ranges = catalog.trading_calendar_requested_ranges(
        scope_type,
        scope_value,
        start_date,
        end_date,
    )
    gaps = missing_coverage_ranges(start_date, end_date, coverage_ranges)
    expected_dates = (
        catalog.trading_calendar_dates(scope_type, scope_value, start_date, end_date)
        if not gaps
        else []
    )
    complete_items = catalog.completed_market_bar_items(
        symbols=symbols,
        trade_dates=expected_dates,
        interval=interval,
        requested_session=requested_session,
        adjustment=adjustment,
        source_schema_version=source_schema_version,
    )
    present_items = catalog.present_market_bar_items(
        symbols=symbols,
        trade_dates=expected_dates,
        interval=interval,
        requested_session=requested_session,
        adjustment=adjustment,
        source_schema_version=source_schema_version,
    )
    incomplete_reasons = catalog.incomplete_market_bar_item_reasons(
        symbols=symbols,
        trade_dates=expected_dates,
        interval=interval,
        requested_session=requested_session,
        adjustment=adjustment,
        source_schema_version=source_schema_version,
    )
    return MarketBarCoverageState(
        calendar_scope_type=scope_type,
        calendar_scope_value=scope_value,
        start_date=start_date,
        end_date=end_date,
        expected_trade_dates=expected_dates,
        calendar_coverage_gaps=gaps,
        complete_items=complete_items,
        present_items=present_items,
        incomplete_reasons=incomplete_reasons,
    )
