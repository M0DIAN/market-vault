"""Lightweight bilingual localization for the parallel QML desktop."""

from __future__ import annotations

from typing import Final

from PySide6.QtCore import Property, QObject, Signal, Slot

from market_vault.desktop.preferences import (
    DesktopPreferenceStore,
    SUPPORTED_LANGUAGES,
)


EN: Final[dict[str, str]] = {
    "app.title": "MarketVault",
    "app.subtitle": "Local market data vault",
    "language.control": "Language",
    "nav.group.home": "HOME",
    "nav.group.data": "DATA",
    "nav.group.explore": "EXPLORE",
    "nav.group.quality": "QUALITY",
    "nav.group.activity": "ACTIVITY",
    "nav.group.advanced": "ADVANCED",
    "nav.home": "Home",
    "nav.historical_data": "Historical Data",
    "nav.trading_calendar": "Trading Calendar",
    "nav.market_data": "Market Data",
    "nav.inventory": "Inventory",
    "nav.coverage_audit": "Coverage Audit",
    "nav.intraday_audit": "Intraday Audit",
    "nav.runs": "Runs",
    "nav.storage_cleanup": "Storage & Cleanup",
    "home.title": "Home",
    "home.refresh": "Refresh Dashboard",
    "home.refreshing": "Refreshing...",
    "home.unconfigured": "Dashboard unconfigured",
    "home.recent_runs": "Recent Runs",
    "home.no_recent_runs": "No recent runs",
    "home.ping": "Ping Python",
    "status.bridge": "Bridge",
    "status.dashboard": "Dashboard",
    "metric.symbols": "Symbols",
    "metric.snapshots": "Snapshots",
    "metric.latest_rows": "Latest rows",
    "metric.completed_dates": "Completed dates",
    "metric.incomplete_dates": "Incomplete dates",
    "metric.latest_trade_date": "Latest trade date",
    "placeholder.message": "This page will be connected in a later migration phase.",
    "columns.run_kind": "Run type",
    "columns.dataset": "Dataset",
    "columns.run_id": "Run ID",
    "columns.started_at": "Started",
    "columns.finished_at": "Finished",
    "columns.status": "Status",
    "columns.row_count": "Rows",
    "columns.requested_items": "Requested items",
    "columns.errors": "Errors",
}

ZH_CN: Final[dict[str, str]] = {
    "app.title": "MarketVault",
    "app.subtitle": "本地市场数据仓库",
    "language.control": "语言",
    "nav.group.home": "首页",
    "nav.group.data": "数据",
    "nav.group.explore": "浏览",
    "nav.group.quality": "质量检查",
    "nav.group.activity": "运行",
    "nav.group.advanced": "高级管理",
    "nav.home": "首页",
    "nav.historical_data": "历史数据",
    "nav.trading_calendar": "交易日历",
    "nav.market_data": "行情数据",
    "nav.inventory": "数据库存",
    "nav.coverage_audit": "覆盖检查",
    "nav.intraday_audit": "分钟数据检查",
    "nav.runs": "运行记录",
    "nav.storage_cleanup": "存储与清理",
    "home.title": "首页",
    "home.refresh": "刷新仪表盘",
    "home.refreshing": "正在刷新...",
    "home.unconfigured": "仪表盘未配置",
    "home.recent_runs": "最近运行",
    "home.no_recent_runs": "暂无运行记录",
    "home.ping": "测试 Python",
    "status.bridge": "桥接状态",
    "status.dashboard": "仪表盘",
    "metric.symbols": "标的数量",
    "metric.snapshots": "快照数量",
    "metric.latest_rows": "最新行数",
    "metric.completed_dates": "完整日期",
    "metric.incomplete_dates": "不完整日期",
    "metric.latest_trade_date": "最新交易日",
    "placeholder.message": "此页面将在后续迁移阶段接入。",
    "columns.run_kind": "运行类型",
    "columns.dataset": "数据集",
    "columns.run_id": "运行 ID",
    "columns.started_at": "开始时间",
    "columns.finished_at": "结束时间",
    "columns.status": "状态",
    "columns.row_count": "行数",
    "columns.requested_items": "请求项目",
    "columns.errors": "错误",
}

TRANSLATIONS: Final[dict[str, dict[str, str]]] = {
    "en": EN,
    "zh-CN": ZH_CN,
}


def translation_keys_match() -> bool:
    return set(EN) == set(ZH_CN)


class I18nBridge(QObject):
    """Expose live translations without importing the legacy Console package."""

    languageChanged = Signal()

    def __init__(
        self,
        *,
        preference_store: DesktopPreferenceStore | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._preference_store = preference_store or DesktopPreferenceStore()
        self._language = self._preference_store.load_language()

    @Property(str, notify=languageChanged)
    def language(self) -> str:
        return self._language

    @Property("QVariantMap", notify=languageChanged)
    def catalog(self) -> dict[str, str]:
        return dict(TRANSLATIONS[self._language])

    @Property("QVariantList", constant=True)
    def availableLanguages(self) -> list[dict[str, str]]:  # noqa: N802
        return [
            {"code": "zh-CN", "label": "中文"},
            {"code": "en", "label": "English"},
        ]

    @Slot(str, result=bool)
    def setLanguage(self, locale: str) -> bool:  # noqa: N802
        if locale not in SUPPORTED_LANGUAGES:
            return False
        if locale == self._language:
            return True
        self._language = locale
        self.languageChanged.emit()
        return self._preference_store.save_language(locale)

    @Slot(str, result=str)
    def translate(self, key: str) -> str:
        return TRANSLATIONS[self._language].get(key, EN.get(key, key))

    @Slot(str, result=str)
    def columnLabel(self, raw_key: str) -> str:  # noqa: N802
        key = f"columns.{raw_key}"
        return self.translate(key) if key in EN else raw_key
