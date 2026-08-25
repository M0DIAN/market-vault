from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import DashboardSnapshot


class PageId(StrEnum):
    HOME = "home"
    HISTORICAL_DATA = "historical_data"
    TRADING_CALENDAR = "trading_calendar"
    MARKET_DATA = "market_data"
    INVENTORY = "inventory"
    COVERAGE_AUDIT = "coverage_audit"
    INTRADAY_AUDIT = "intraday_audit"
    RUNS = "runs"
    STORAGE_CLEANUP = "storage_cleanup"


@dataclass(frozen=True)
class NavigationItem:
    page_id: PageId
    label_key: str


@dataclass(frozen=True)
class NavigationGroup:
    label_key: str | None
    items: tuple[NavigationItem, ...]


NAVIGATION_GROUPS = (
    NavigationGroup(
        None,
        (NavigationItem(PageId.HOME, "navigation.items.home"),),
    ),
    NavigationGroup(
        "navigation.groups.data",
        (
            NavigationItem(PageId.HISTORICAL_DATA, "navigation.items.historical_data"),
            NavigationItem(PageId.TRADING_CALENDAR, "navigation.items.trading_calendar"),
        ),
    ),
    NavigationGroup(
        "navigation.groups.explore",
        (
            NavigationItem(PageId.MARKET_DATA, "navigation.items.market_data"),
            NavigationItem(PageId.INVENTORY, "navigation.items.inventory"),
        ),
    ),
    NavigationGroup(
        "navigation.groups.quality",
        (
            NavigationItem(PageId.COVERAGE_AUDIT, "navigation.items.coverage_audit"),
            NavigationItem(PageId.INTRADAY_AUDIT, "navigation.items.intraday_audit"),
        ),
    ),
    NavigationGroup(
        "navigation.groups.activity",
        (NavigationItem(PageId.RUNS, "navigation.items.runs"),),
    ),
    NavigationGroup(
        "navigation.groups.advanced",
        (NavigationItem(PageId.STORAGE_CLEANUP, "navigation.items.storage_cleanup"),),
    ),
)


PAGE_TAB_KEYS = {
    PageId.HOME: "tabs.dashboard",
    PageId.HISTORICAL_DATA: "tabs.backfill",
    PageId.TRADING_CALENDAR: "tabs.calendar",
    PageId.MARKET_DATA: "tabs.explorer",
    PageId.INVENTORY: "tabs.inventory",
    PageId.COVERAGE_AUDIT: "tabs.coverage",
    PageId.INTRADAY_AUDIT: "tabs.intraday",
    PageId.RUNS: "tabs.runs",
    PageId.STORAGE_CLEANUP: "tabs.purge",
}


class HomeState(StrEnum):
    UNLOADED = "unloaded"
    EMPTY = "empty"
    POPULATED = "populated"


HOME_METRICS = (
    ("Symbols", "metrics.symbols"),
    ("Snapshots", "metrics.snapshots"),
    ("Completed dates", "metrics.completed_dates"),
    ("Incomplete dates", "metrics.incomplete_dates"),
    ("Latest trade date", "metrics.latest_trade_date"),
    ("Latest rows", "metrics.latest_rows"),
)


def dashboard_home_state(snapshot: DashboardSnapshot) -> HomeState:
    """Classify only from Dashboard metrics already authorized by the backend."""

    symbols = _metric_count(snapshot.metrics.get("Symbols"))
    snapshots = _metric_count(snapshot.metrics.get("Snapshots"))
    if symbols == 0 and snapshots == 0:
        return HomeState.EMPTY
    return HomeState.POPULATED


def _metric_count(value: str | None) -> int:
    if value is None:
        return 0
    try:
        return int(value.replace(",", "").strip())
    except ValueError:
        return 0
