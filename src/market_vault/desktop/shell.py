"""Presentation-only navigation state for the parallel QML desktop."""

from __future__ import annotations

from typing import Final

from PySide6.QtCore import Property, QObject, Signal, Slot


PAGE_DEFINITIONS: Final[tuple[dict[str, object], ...]] = (
    {
        "id": "home",
        "labelKey": "nav.home",
        "groupKey": "nav.group.home",
        "showGroup": True,
    },
    {
        "id": "historical_data",
        "labelKey": "nav.historical_data",
        "groupKey": "nav.group.data",
        "showGroup": True,
    },
    {
        "id": "trading_calendar",
        "labelKey": "nav.trading_calendar",
        "groupKey": "nav.group.data",
        "showGroup": False,
    },
    {
        "id": "market_data",
        "labelKey": "nav.market_data",
        "groupKey": "nav.group.explore",
        "showGroup": True,
    },
    {
        "id": "inventory",
        "labelKey": "nav.inventory",
        "groupKey": "nav.group.explore",
        "showGroup": False,
    },
    {
        "id": "coverage_audit",
        "labelKey": "nav.coverage_audit",
        "groupKey": "nav.group.quality",
        "showGroup": True,
    },
    {
        "id": "intraday_audit",
        "labelKey": "nav.intraday_audit",
        "groupKey": "nav.group.quality",
        "showGroup": False,
    },
    {
        "id": "runs",
        "labelKey": "nav.runs",
        "groupKey": "nav.group.activity",
        "showGroup": True,
    },
    {
        "id": "storage_cleanup",
        "labelKey": "nav.storage_cleanup",
        "groupKey": "nav.group.advanced",
        "showGroup": True,
    },
)
PAGE_IDS: Final[tuple[str, ...]] = tuple(
    str(page["id"]) for page in PAGE_DEFINITIONS
)
PAGE_LABEL_KEYS: Final[dict[str, str]] = {
    str(page["id"]): str(page["labelKey"]) for page in PAGE_DEFINITIONS
}


class ShellController(QObject):
    """Own stable page selection without invoking business services."""

    currentPageChanged = Signal()

    def __init__(self, *, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._current_page = "home"

    @Property(str, notify=currentPageChanged)
    def currentPage(self) -> str:  # noqa: N802
        return self._current_page

    @Property(str, notify=currentPageChanged)
    def currentPageLabelKey(self) -> str:  # noqa: N802
        return PAGE_LABEL_KEYS[self._current_page]

    @Property("QVariantList", constant=True)
    def pages(self) -> list[dict[str, object]]:
        return [dict(page) for page in PAGE_DEFINITIONS]

    @Slot(str, result=bool)
    def selectPage(self, page_id: str) -> bool:  # noqa: N802
        if page_id not in PAGE_IDS:
            return False
        if page_id == self._current_page:
            return True
        self._current_page = page_id
        self.currentPageChanged.emit()
        return True
