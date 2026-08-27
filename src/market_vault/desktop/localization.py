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
    "columns.run_kind": "Run type",
    "columns.dataset": "Dataset",
    "columns.run_id": "Run ID",
    "columns.started_at": "Started",
    "columns.finished_at": "Finished",
    "columns.status": "Status",
    "columns.row_count": "Rows",
    "columns.requested_items": "Requested items",
    "columns.errors": "Errors",
    "common.query": "Query",
    "common.refresh": "Refresh",
    "common.export_csv": "Export CSV",
    "common.export_json": "Export JSON",
    "common.previous": "Previous",
    "common.next": "Next",
    "common.no_data": "No data loaded",
    "common.page": "Page",
    "common.of": "of",
    "common.rows": "rows",
    "common.status": "Status",
    "common.summary": "Summary",
    "common.cancel": "Cancel",
    "common.confirm": "Confirm",
    "common.ready": "Ready",
    "common.running": "Running",
    "common.close_busy": "An operation is still running. Wait for it to finish before closing.",
    "common.error": "Error",
    "status.ready": "Ready",
    "status.running": "Running",
    "status.success": "Success",
    "status.failed": "Failed",
    "status.busy": "Busy",
    "status.unconfigured": "Unconfigured",
    "status.unreviewed": "Not reviewed",
    "status.planned": "Planned",
    "status.refused": "Refused",
    "status.empty": "Empty",
    "status.partial": "Partial",
    "status.validation_error": "Validation error",
    "operation.dashboard": "Dashboard refresh",
    "operation.market_data": "Market data query",
    "operation.calendar_query": "Calendar query",
    "operation.calendar_collect": "Calendar collection",
    "operation.backfill_plan": "Backfill plan",
    "operation.backfill_execute": "Backfill execution",
    "operation.inventory": "Inventory",
    "operation.coverage_audit": "Coverage audit",
    "operation.intraday_audit": "Intraday audit",
    "operation.runs": "Run history",
    "operation.storage_review": "Storage review",
    "operation.storage_execute": "Safe Purge execution",
    "operation.export": "Export",
    "opend.title": "Confirm OpenD operation",
    "opend.message": "This operation may connect to OpenD.",
    "opend.operation": "Operation",
    "opend.host": "Host",
    "opend.port": "Port",
    "field.symbols": "Symbols",
    "field.code": "Code",
    "field.start_date": "Start date",
    "field.end_date": "End date",
    "field.bootstrap_start_date": "Bootstrap start date",
    "field.calendar_market": "Calendar market",
    "field.calendar_code": "Calendar code",
    "field.scope": "Scope",
    "field.market": "Market",
    "field.interval": "Interval",
    "field.requested_session": "Requested session",
    "field.bar_session": "Bar session",
    "field.session": "Session",
    "field.adjustment": "Adjustment",
    "field.page_size": "Page size",
    "field.max_retries": "Max retries",
    "field.retry_backoff": "Retry backoff (seconds)",
    "field.force": "Force recollection",
    "field.incremental": "Incremental",
    "field.status": "Status",
    "field.dataset": "Dataset",
    "field.source": "Source",
    "field.source_schema_version": "Source schema version",
    "field.confirmation": "Exact confirmation",
    "historical.plan": "Plan locally",
    "historical.execute": "Execute via OpenD",
    "historical.plan_items": "Backfill plan items",
    "calendar.local_query": "Query local",
    "calendar.fetch": "Fetch from OpenD",
    "market.query": "Query local data",
    "inventory.inspect": "Inspect inventory",
    "audit.run": "Run local audit",
    "runs.refresh": "Refresh runs",
    "storage.warning": "Files are moved to retained quarantine. Permanent deletion is not supported.",
    "storage.review": "Review scope",
    "storage.execute": "Execute Safe Purge",
    "storage.plan_id": "Reviewed plan ID",
    "storage.refusals": "Refusal reasons",
    "storage.confirmation_help": "Enter exactly PURGE <plan_id> after reviewing an executable plan.",
    "columns.code": "Code",
    "columns.symbol": "Symbol",
    "columns.trade_date": "Trade date",
    "columns.requested_trade_date": "Requested trade date",
    "columns.interval": "Interval",
    "columns.session": "Session",
    "columns.adjustment": "Adjustment",
    "columns.state": "State",
    "columns.page": "Page",
    "columns.market": "Market",
    "columns.date": "Date",
    "columns.trade_date_type": "Trade date type",
    "columns.ingestion_run_id": "Ingestion run ID",
    "columns.source_state": "Source state",
    "columns.audit_status": "Audit status",
    "columns.boundary_evaluated": "Boundary evaluated",
    "columns.internal_gap_count": "Internal gaps",
    "columns.physical_scope_status": "Physical scope",
    "columns.symbols": "Symbols",
    "columns.dates": "Dates",
    "columns.affected_rows": "Affected rows",
    "columns.raw_bytes": "Raw bytes",
    "columns.curated_bytes": "Curated bytes",
    "columns.raw_path": "Raw path",
    "columns.curated_path": "Curated path",
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
    "columns.run_kind": "运行类型",
    "columns.dataset": "数据集",
    "columns.run_id": "运行 ID",
    "columns.started_at": "开始时间",
    "columns.finished_at": "结束时间",
    "columns.status": "状态",
    "columns.row_count": "行数",
    "columns.requested_items": "请求项目",
    "columns.errors": "错误",
    "common.query": "查询",
    "common.refresh": "刷新",
    "common.export_csv": "导出 CSV",
    "common.export_json": "导出 JSON",
    "common.previous": "上一页",
    "common.next": "下一页",
    "common.no_data": "尚未加载数据",
    "common.page": "第",
    "common.of": "页，共",
    "common.rows": "行",
    "common.status": "状态",
    "common.summary": "摘要",
    "common.cancel": "取消",
    "common.confirm": "确认",
    "common.ready": "就绪",
    "common.running": "正在运行",
    "common.close_busy": "操作仍在运行，请等待完成后再关闭。",
    "common.error": "错误",
    "status.ready": "就绪",
    "status.running": "正在运行",
    "status.success": "成功",
    "status.failed": "失败",
    "status.busy": "忙碌",
    "status.unconfigured": "未配置",
    "status.unreviewed": "尚未检查",
    "status.planned": "已生成计划",
    "status.refused": "已拒绝",
    "status.empty": "无数据",
    "status.partial": "部分成功",
    "status.validation_error": "输入验证失败",
    "operation.dashboard": "刷新仪表盘",
    "operation.market_data": "查询行情数据",
    "operation.calendar_query": "查询交易日历",
    "operation.calendar_collect": "获取交易日历",
    "operation.backfill_plan": "生成回填计划",
    "operation.backfill_execute": "执行历史数据回填",
    "operation.inventory": "检查库存",
    "operation.coverage_audit": "运行覆盖检查",
    "operation.intraday_audit": "运行分钟数据检查",
    "operation.runs": "查询运行记录",
    "operation.storage_review": "检查存储范围",
    "operation.storage_execute": "执行安全清理",
    "operation.export": "导出",
    "opend.title": "确认 OpenD 操作",
    "opend.message": "此操作可能连接 OpenD。",
    "opend.operation": "操作",
    "opend.host": "主机",
    "opend.port": "端口",
    "field.symbols": "标的",
    "field.code": "代码",
    "field.start_date": "开始日期",
    "field.end_date": "结束日期",
    "field.bootstrap_start_date": "初始开始日期",
    "field.calendar_market": "日历市场",
    "field.calendar_code": "日历代码",
    "field.scope": "范围",
    "field.market": "市场",
    "field.interval": "周期",
    "field.requested_session": "请求时段",
    "field.bar_session": "K 线时段",
    "field.session": "时段",
    "field.adjustment": "复权",
    "field.page_size": "每页行数",
    "field.max_retries": "最大重试次数",
    "field.retry_backoff": "重试退避（秒）",
    "field.force": "强制重采",
    "field.incremental": "增量模式",
    "field.status": "状态",
    "field.dataset": "数据集",
    "field.source": "数据源",
    "field.source_schema_version": "数据源模式版本",
    "field.confirmation": "精确确认文本",
    "historical.plan": "本地生成计划",
    "historical.execute": "通过 OpenD 执行",
    "historical.plan_items": "回填计划项目",
    "calendar.local_query": "查询本地数据",
    "calendar.fetch": "从 OpenD 获取",
    "market.query": "查询本地数据",
    "inventory.inspect": "检查库存",
    "audit.run": "运行本地检查",
    "runs.refresh": "刷新运行记录",
    "storage.warning": "文件仅移动到保留的隔离区，不支持永久删除。",
    "storage.review": "检查范围",
    "storage.execute": "执行安全清理",
    "storage.plan_id": "已检查计划 ID",
    "storage.refusals": "拒绝原因",
    "storage.confirmation_help": "检查可执行计划后，请准确输入 PURGE <plan_id>。",
    "columns.code": "代码",
    "columns.symbol": "标的",
    "columns.trade_date": "交易日期",
    "columns.requested_trade_date": "请求交易日期",
    "columns.interval": "周期",
    "columns.session": "时段",
    "columns.adjustment": "复权",
    "columns.state": "状态",
    "columns.page": "页码",
    "columns.market": "市场",
    "columns.date": "日期",
    "columns.trade_date_type": "交易日类型",
    "columns.ingestion_run_id": "采集运行 ID",
    "columns.source_state": "数据源状态",
    "columns.audit_status": "检查状态",
    "columns.boundary_evaluated": "边界已评估",
    "columns.internal_gap_count": "内部缺口",
    "columns.physical_scope_status": "物理范围",
    "columns.symbols": "标的",
    "columns.dates": "日期",
    "columns.affected_rows": "影响行数",
    "columns.raw_bytes": "Raw 字节数",
    "columns.curated_bytes": "Curated 字节数",
    "columns.raw_path": "Raw 路径",
    "columns.curated_path": "Curated 路径",
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
        if not self._preference_store.save_language(locale):
            return False
        self._language = locale
        self.languageChanged.emit()
        return True

    @Slot(str, result=str)
    def translate(self, key: str) -> str:
        return TRANSLATIONS[self._language].get(key, EN.get(key, key))

    @Slot(str, result=str)
    def columnLabel(self, raw_key: str) -> str:  # noqa: N802
        key = f"columns.{raw_key}"
        return self.translate(key) if key in EN else raw_key

    @Slot(str, result=str)
    def statusLabel(self, raw_status: str) -> str:  # noqa: N802
        key = f"status.{str(raw_status).strip().lower()}"
        return self.translate(key) if key in EN else str(raw_status)

    @Slot(str, result=str)
    def operationLabel(self, operation_id: str) -> str:  # noqa: N802
        key = f"operation.{str(operation_id).strip()}"
        return self.translate(key) if key in EN else str(operation_id)
