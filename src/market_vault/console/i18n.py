from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping

from .preferences import DEFAULT_LOCALE, SUPPORTED_LOCALES


LANGUAGE_NAMES = {
    "en": "English",
    "zh-CN": "简体中文",
    "ja": "日本語",
}
LOCALES_BY_NAME = {name: locale for locale, name in LANGUAGE_NAMES.items()}


EN = {
    "app.title": "MarketVault Console",
    "header.title": "MarketVault",
    "header.local_mode": "Local Mode",
    "header.context": "Settings: {settings_path} | OpenD only on explicit Fetch or Execute",
    "header.language": "Language:",
    "status.ready": "Ready | Local operations only",
    "status.running": "Running: {operation}",
    "status.completed": "Completed: {operation}",
    "status.failed": "Failed: {operation}",
    "tabs.dashboard": "Home",
    "tabs.explorer": "Data Explorer",
    "tabs.inventory": "Inventory",
    "tabs.coverage": "Coverage Audit",
    "tabs.intraday": "Intraday Audit",
    "tabs.calendar": "Trading Calendar",
    "tabs.backfill": "Backfill",
    "tabs.purge": "Storage / Purge",
    "tabs.runs": "Runs",
    "sections.archive_overview": "Local archive overview",
    "sections.recent_runs": "Recent runs",
    "sections.explorer": "Bounded local market-bar query",
    "sections.inventory": "Local physical and logical inventory",
    "sections.coverage": "Trading-date coverage audit",
    "sections.intraday": "Latest complete snapshot structure",
    "sections.calendar": "Local query and explicit OpenD fetch",
    "sections.backfill": "Calendar-driven historical backfill",
    "sections.runs": "Local collection and dataset run history",
    "sections.purge": "Exact physical market-bar snapshot scope",
    "sections.purge_execute": "Execute reviewed plan",
    "metrics.symbols": "Symbols",
    "metrics.snapshots": "Snapshots",
    "metrics.latest_rows": "Latest rows",
    "metrics.completed_dates": "Completed dates",
    "metrics.incomplete_dates": "Incomplete dates",
    "metrics.latest_trade_date": "Latest trade date",
    "fields.code": "Code",
    "fields.symbols": "Symbols",
    "fields.start_date": "Start date",
    "fields.end_date": "End date",
    "fields.interval": "Interval",
    "fields.requested_session": "Request session",
    "fields.bar_session": "Bar session",
    "fields.session": "Session",
    "fields.adjustment": "Adjustment",
    "fields.page_size": "Rows/page",
    "fields.calendar_market": "Calendar market",
    "fields.calendar_code": "Calendar code",
    "fields.scope": "Scope",
    "fields.market": "Market",
    "fields.bootstrap_start_date": "Bootstrap start date",
    "fields.max_retries": "Max retries",
    "fields.retry_backoff_seconds": "Retry backoff seconds",
    "fields.status": "Status",
    "fields.dataset": "Dataset",
    "fields.source": "Source",
    "fields.source_schema_version": "Source schema version",
    "buttons.refresh": "Refresh",
    "buttons.query": "Query",
    "buttons.query_local": "Query local",
    "buttons.fetch_opend": "Fetch from OpenD",
    "buttons.export_csv": "Export page CSV",
    "buttons.export_json": "Export page JSON",
    "buttons.run_inventory": "Run inventory",
    "buttons.run_coverage": "Run coverage audit",
    "buttons.run_intraday": "Run intraday audit",
    "buttons.plan_local": "Plan locally",
    "buttons.execute_opend": "Execute via OpenD",
    "buttons.preview_purge": "Preview purge",
    "buttons.move_quarantine": "Move to quarantine",
    "buttons.previous": "Previous",
    "buttons.next": "Next",
    "checkbox.incremental": "Incremental",
    "checkbox.force": "Force re-collection",
    "empty.no_data": "No data loaded",
    "empty.no_inventory": "No inventory run",
    "empty.no_audit": "No audit run",
    "empty.no_plan": "No plan generated",
    "empty.no_purge_plan": "No sealed plan",
    "pagination.info": "Rows {start:,}-{end:,} of {total:,} | Page {page} of {pages}",
    "purge.description": "This removes the selected data from the active MarketVault archive and moves it to quarantine. It does not permanently erase quarantine contents.",
    "purge.confirmation": "Type PURGE <plan_id>",
    "purge.scope_changed": "Scope changed; run Preview again",
    "dialog.running.title": "Operation running",
    "dialog.running.body": "Wait for the current operation to finish.",
    "dialog.running.close_body": "Wait for the current operation to finish before exiting.",
    "dialog.opend.title": "OpenD operation",
    "dialog.opend.body": "{operation} may connect to OpenD at {host}:{port}.\n\nContinue?",
    "dialog.export.title": "Export",
    "dialog.export.no_data": "Load a table page before exporting.",
    "dialog.export.complete_title": "Export complete",
    "dialog.export.complete_body": "Exported {row_count} rows to\n{path}",
    "dialog.purge.title": "Safe Purge",
    "dialog.purge.preview_first": "Preview an executable purge plan first.",
    "startup.tk_unavailable": "Unable to start MarketVault Console: the Python Tcl/Tk runtime is unavailable. Install or repair a standard Python distribution with Tkinter support. Details: {details}",
    "operations.dashboard_refresh": "Dashboard refresh",
    "operations.market_bar_query": "Market-bar query",
    "operations.inventory": "Inventory",
    "operations.coverage_audit": "Coverage audit",
    "operations.intraday_audit": "Intraday audit",
    "operations.calendar_query": "Calendar query",
    "operations.calendar_fetch": "Calendar fetch",
    "operations.backfill_plan": "Backfill plan",
    "operations.backfill_execute": "Backfill execute",
    "operations.purge_preview": "Purge preview",
    "operations.purge_execute": "Safe Purge execute",
    "operations.run_history": "Run history",
    "operations.export_page": "Export current page",
    "summary.calendar_fetch": "Calendar fetch {status} | run {run_id} | rows {row_count}",
    "summary.backfill_plan": "{scope} | {dates} dates | {pending} pending | {skipped} skipped",
    "summary.backfill_result": "{status} | run {run_id} | success {success} | failed {failed}",
    "summary.purge_plan": "{status} | plan {plan_id} | {pairs} snapshot pairs | {rows} rows",
    "summary.purge_result": "{status} | plan {plan_id} | moved {files} files",
    "summary.status": "status",
    "summary.calendar_coverage_complete": "calendar coverage complete",
    "summary.failure_reason": "failure reason",
    "summary.calendar_coverage_gaps": "calendar coverage gaps",
    "summary.symbol_count": "symbol count",
    "summary.snapshot_count": "snapshot count",
    "summary.total_expected_items": "expected items",
    "summary.complete_item_count": "complete items",
    "summary.audited_item_count": "audited items",
    "summary.warn_item_count": "warnings",
    "summary.fail_item_count": "failures",
    "summary.coverage_percentage": "coverage percentage",
    "columns.run_id": "Run ID",
    "columns.dataset": "Dataset",
    "columns.status": "Status",
    "columns.started_at": "Started at",
    "columns.finished_at": "Finished at",
    "columns.row_count": "Rows",
    "columns.code": "Code",
    "columns.symbol": "Symbol",
    "columns.trade_date": "Trade date",
    "columns.requested_trade_date": "Requested trade date",
    "columns.interval": "Interval",
    "columns.requested_session": "Requested session",
    "columns.session": "Session",
    "columns.adjustment": "Adjustment",
    "columns.time_market": "Market time",
    "columns.time_utc": "UTC time",
    "columns.open": "Open",
    "columns.high": "High",
    "columns.low": "Low",
    "columns.close": "Close",
    "columns.volume": "Volume",
    "columns.scope_type": "Scope type",
    "columns.scope_value": "Scope value",
    "columns.market": "Market",
    "columns.reference_code": "Reference code",
    "columns.trade_date_type": "Trade date type",
    "columns.state": "State",
    "columns.source_state": "Source state",
    "columns.audit_status": "Audit status",
    "columns.complete_trade_date_count": "Complete dates",
    "columns.incomplete_trade_date_count": "Incomplete dates",
    "columns.expected_trade_date_count": "Expected dates",
    "columns.coverage_percentage": "Coverage",
    "columns.first_trade_date": "First trade date",
    "columns.last_trade_date": "Last trade date",
    "columns.snapshot_count": "Snapshots",
    "columns.snapshot_row_count": "Snapshot rows",
    "columns.physical_scope_status": "Physical scope",
    "columns.symbols": "Symbols",
    "columns.rows": "Rows",
}


ZH_CN = {
    "app.title": "MarketVault 控制台", "header.title": "MarketVault", "header.local_mode": "本地模式",
    "header.context": "设置：{settings_path} | 仅在明确获取或执行时连接 OpenD", "header.language": "语言：",
    "status.ready": "就绪 | 仅限本地操作", "status.running": "正在运行：{operation}", "status.completed": "已完成：{operation}", "status.failed": "失败：{operation}",
    "tabs.dashboard": "首页", "tabs.explorer": "数据浏览", "tabs.inventory": "数据清单", "tabs.coverage": "覆盖审计", "tabs.intraday": "盘中审计", "tabs.calendar": "交易日历", "tabs.backfill": "历史数据回填", "tabs.purge": "存储 / 清理", "tabs.runs": "运行记录",
    "sections.archive_overview": "本地归档概览", "sections.recent_runs": "最近运行", "sections.explorer": "受限本地行情查询", "sections.inventory": "本地物理与逻辑数据清单", "sections.coverage": "交易日覆盖审计", "sections.intraday": "最新完整快照结构", "sections.calendar": "本地查询与显式 OpenD 获取", "sections.backfill": "按交易日历进行历史数据回填", "sections.runs": "本地采集与数据集运行记录", "sections.purge": "精确的行情物理快照范围", "sections.purge_execute": "执行已审核计划",
    "metrics.symbols": "标的", "metrics.snapshots": "快照", "metrics.latest_rows": "最新行数", "metrics.completed_dates": "完整日期", "metrics.incomplete_dates": "不完整日期", "metrics.latest_trade_date": "最新交易日",
    "fields.code": "代码", "fields.symbols": "标的", "fields.start_date": "开始日期", "fields.end_date": "结束日期", "fields.interval": "周期", "fields.requested_session": "请求时段", "fields.bar_session": "K 线时段", "fields.session": "时段", "fields.adjustment": "复权", "fields.page_size": "每页行数", "fields.calendar_market": "日历市场", "fields.calendar_code": "日历代码", "fields.scope": "范围", "fields.market": "市场", "fields.bootstrap_start_date": "初始开始日期", "fields.max_retries": "最大重试次数", "fields.retry_backoff_seconds": "重试退避秒数", "fields.status": "状态", "fields.dataset": "数据集", "fields.source": "来源", "fields.source_schema_version": "来源架构版本",
    "buttons.refresh": "刷新", "buttons.query": "查询", "buttons.query_local": "查询本地数据", "buttons.fetch_opend": "从 OpenD 获取", "buttons.export_csv": "导出当前页 CSV", "buttons.export_json": "导出当前页 JSON", "buttons.run_inventory": "生成数据清单", "buttons.run_coverage": "运行覆盖审计", "buttons.run_intraday": "运行盘中审计", "buttons.plan_local": "本地生成计划", "buttons.execute_opend": "通过 OpenD 执行", "buttons.preview_purge": "预览清理计划", "buttons.move_quarantine": "移至隔离区", "buttons.previous": "上一页", "buttons.next": "下一页",
    "checkbox.incremental": "增量模式", "checkbox.force": "强制重新采集",
    "empty.no_data": "尚未加载数据", "empty.no_inventory": "尚未生成数据清单", "empty.no_audit": "尚未运行审计", "empty.no_plan": "尚未生成计划", "empty.no_purge_plan": "尚无已封存计划",
    "pagination.info": "第 {start:,}-{end:,} 行，共 {total:,} 行 | 第 {page}/{pages} 页",
    "purge.description": "此操作会从 MarketVault 活动归档中移出所选数据，并将其放入隔离区；不会永久删除隔离区内容。", "purge.confirmation": "输入 PURGE <plan_id>", "purge.scope_changed": "范围已更改，请重新预览",
    "dialog.running.title": "操作正在运行", "dialog.running.body": "请等待当前操作完成。", "dialog.running.close_body": "请等待当前操作完成后再退出。", "dialog.opend.title": "OpenD 操作", "dialog.opend.body": "{operation} 可能连接到 {host}:{port} 的 OpenD。\n\n是否继续？", "dialog.export.title": "导出", "dialog.export.no_data": "请先加载一个表格页面。", "dialog.export.complete_title": "导出完成", "dialog.export.complete_body": "已将 {row_count} 行导出到\n{path}", "dialog.purge.title": "安全清理", "dialog.purge.preview_first": "请先预览可执行的清理计划。", "startup.tk_unavailable": "无法启动 MarketVault 控制台：Python Tcl/Tk 运行时不可用。请安装或修复包含 Tkinter 的标准 Python 发行版。详细信息：{details}",
    "operations.dashboard_refresh": "刷新仪表盘", "operations.market_bar_query": "行情查询", "operations.inventory": "数据清单", "operations.coverage_audit": "覆盖审计", "operations.intraday_audit": "盘中审计", "operations.calendar_query": "日历查询", "operations.calendar_fetch": "获取交易日历", "operations.backfill_plan": "回填计划", "operations.backfill_execute": "执行回填", "operations.purge_preview": "预览清理计划", "operations.purge_execute": "执行安全清理", "operations.run_history": "运行记录", "operations.export_page": "导出当前页",
    "summary.calendar_fetch": "交易日历获取 {status} | 运行 {run_id} | {row_count} 行", "summary.backfill_plan": "{scope} | {dates} 个交易日 | {pending} 个待处理 | {skipped} 个已跳过", "summary.backfill_result": "{status} | 运行 {run_id} | 成功 {success} | 失败 {failed}", "summary.purge_plan": "{status} | 计划 {plan_id} | {pairs} 对快照 | {rows} 行", "summary.purge_result": "{status} | 计划 {plan_id} | 已移动 {files} 个文件",
    "summary.status": "状态", "summary.calendar_coverage_complete": "日历覆盖完整", "summary.failure_reason": "失败原因", "summary.calendar_coverage_gaps": "日历覆盖缺口", "summary.symbol_count": "标的数", "summary.snapshot_count": "快照数", "summary.total_expected_items": "预期项目", "summary.complete_item_count": "完整项目", "summary.audited_item_count": "已审计项目", "summary.warn_item_count": "警告", "summary.fail_item_count": "失败", "summary.coverage_percentage": "覆盖率",
    "columns.run_id": "运行 ID", "columns.dataset": "数据集", "columns.status": "状态", "columns.started_at": "开始时间", "columns.finished_at": "完成时间", "columns.row_count": "行数", "columns.code": "代码", "columns.symbol": "标的", "columns.trade_date": "交易日", "columns.requested_trade_date": "请求交易日", "columns.interval": "周期", "columns.requested_session": "请求时段", "columns.session": "时段", "columns.adjustment": "复权", "columns.time_market": "市场时间", "columns.time_utc": "UTC 时间", "columns.open": "开盘", "columns.high": "最高", "columns.low": "最低", "columns.close": "收盘", "columns.volume": "成交量", "columns.scope_type": "范围类型", "columns.scope_value": "范围值", "columns.market": "市场", "columns.reference_code": "参考代码", "columns.trade_date_type": "交易日类型", "columns.state": "状态", "columns.source_state": "来源状态", "columns.audit_status": "审计状态", "columns.complete_trade_date_count": "完整日期", "columns.incomplete_trade_date_count": "不完整日期", "columns.expected_trade_date_count": "预期日期", "columns.coverage_percentage": "覆盖率", "columns.first_trade_date": "首个交易日", "columns.last_trade_date": "最后交易日", "columns.snapshot_count": "快照数", "columns.snapshot_row_count": "快照行数", "columns.physical_scope_status": "物理范围", "columns.symbols": "标的", "columns.rows": "行数",
}


JA = {
    "app.title": "MarketVault コンソール", "header.title": "MarketVault", "header.local_mode": "ローカルモード",
    "header.context": "設定：{settings_path} | 明示的な取得または実行時のみ OpenD に接続", "header.language": "言語：",
    "status.ready": "準備完了 | ローカル操作のみ", "status.running": "実行中：{operation}", "status.completed": "完了：{operation}", "status.failed": "失敗：{operation}",
    "tabs.dashboard": "ホーム", "tabs.explorer": "データエクスプローラー", "tabs.inventory": "インベントリ", "tabs.coverage": "カバレッジ監査", "tabs.intraday": "日中監査", "tabs.calendar": "取引カレンダー", "tabs.backfill": "履歴データ補完", "tabs.purge": "ストレージ / パージ", "tabs.runs": "実行履歴",
    "sections.archive_overview": "ローカルアーカイブ概要", "sections.recent_runs": "最近の実行", "sections.explorer": "件数制限付きローカル市場データ照会", "sections.inventory": "ローカル物理・論理インベントリ", "sections.coverage": "取引日カバレッジ監査", "sections.intraday": "最新完全スナップショット構造", "sections.calendar": "ローカル照会と明示的な OpenD 取得", "sections.backfill": "取引カレンダーによる履歴データ補完", "sections.runs": "ローカル収集・データセット実行履歴", "sections.purge": "市場データ物理スナップショットの厳密な範囲", "sections.purge_execute": "確認済み計画を実行",
    "metrics.symbols": "銘柄", "metrics.snapshots": "スナップショット", "metrics.latest_rows": "最新行数", "metrics.completed_dates": "完了日", "metrics.incomplete_dates": "未完了日", "metrics.latest_trade_date": "最新取引日",
    "fields.code": "コード", "fields.symbols": "銘柄", "fields.start_date": "開始日", "fields.end_date": "終了日", "fields.interval": "足種", "fields.requested_session": "要求セッション", "fields.bar_session": "バーセッション", "fields.session": "セッション", "fields.adjustment": "株価調整", "fields.page_size": "1ページの行数", "fields.calendar_market": "カレンダー市場", "fields.calendar_code": "カレンダーコード", "fields.scope": "範囲", "fields.market": "市場", "fields.bootstrap_start_date": "初期開始日", "fields.max_retries": "最大再試行回数", "fields.retry_backoff_seconds": "再試行待機秒数", "fields.status": "ステータス", "fields.dataset": "データセット", "fields.source": "ソース", "fields.source_schema_version": "ソーススキーマ版",
    "buttons.refresh": "更新", "buttons.query": "照会", "buttons.query_local": "ローカルデータを照会", "buttons.fetch_opend": "OpenD から取得", "buttons.export_csv": "現在ページを CSV 出力", "buttons.export_json": "現在ページを JSON 出力", "buttons.run_inventory": "インベントリ実行", "buttons.run_coverage": "カバレッジ監査を実行", "buttons.run_intraday": "日中監査を実行", "buttons.plan_local": "ローカルで計画", "buttons.execute_opend": "OpenD で実行", "buttons.preview_purge": "パージ計画をプレビュー", "buttons.move_quarantine": "隔離領域へ移動", "buttons.previous": "前へ", "buttons.next": "次へ",
    "checkbox.incremental": "増分モード", "checkbox.force": "強制再収集",
    "empty.no_data": "データ未読込", "empty.no_inventory": "インベントリ未実行", "empty.no_audit": "監査未実行", "empty.no_plan": "計画未作成", "empty.no_purge_plan": "封印済み計画なし",
    "pagination.info": "{start:,}-{end:,} 行 / 全 {total:,} 行 | {page}/{pages} ページ",
    "purge.description": "選択したデータを MarketVault のアクティブアーカイブから隔離領域へ移動します。隔離領域の内容は完全削除されません。", "purge.confirmation": "PURGE <plan_id> と入力", "purge.scope_changed": "範囲が変更されました。再度プレビューしてください",
    "dialog.running.title": "処理を実行中", "dialog.running.body": "現在の処理が完了するまでお待ちください。", "dialog.running.close_body": "現在の処理が完了してから終了してください。", "dialog.opend.title": "OpenD 操作", "dialog.opend.body": "{operation} は {host}:{port} の OpenD に接続する場合があります。\n\n続行しますか？", "dialog.export.title": "エクスポート", "dialog.export.no_data": "先に表のページを読み込んでください。", "dialog.export.complete_title": "エクスポート完了", "dialog.export.complete_body": "{row_count} 行を次へ出力しました\n{path}", "dialog.purge.title": "安全なパージ", "dialog.purge.preview_first": "先に実行可能なパージ計画をプレビューしてください。", "startup.tk_unavailable": "MarketVault コンソールを起動できません。Python の Tcl/Tk ランタイムが利用できません。Tkinter を含む標準 Python ディストリビューションをインストールまたは修復してください。詳細：{details}",
    "operations.dashboard_refresh": "ダッシュボード更新", "operations.market_bar_query": "市場データ照会", "operations.inventory": "インベントリ", "operations.coverage_audit": "カバレッジ監査", "operations.intraday_audit": "日中監査", "operations.calendar_query": "カレンダー照会", "operations.calendar_fetch": "取引カレンダー取得", "operations.backfill_plan": "補完計画", "operations.backfill_execute": "履歴データ補完", "operations.purge_preview": "パージ計画プレビュー", "operations.purge_execute": "安全なパージ実行", "operations.run_history": "実行履歴", "operations.export_page": "現在ページを出力",
    "summary.calendar_fetch": "取引カレンダー取得 {status} | 実行 {run_id} | {row_count} 行", "summary.backfill_plan": "{scope} | {dates} 取引日 | 保留 {pending} | スキップ {skipped}", "summary.backfill_result": "{status} | 実行 {run_id} | 成功 {success} | 失敗 {failed}", "summary.purge_plan": "{status} | 計画 {plan_id} | {pairs} スナップショットペア | {rows} 行", "summary.purge_result": "{status} | 計画 {plan_id} | {files} ファイル移動済み",
    "summary.status": "ステータス", "summary.calendar_coverage_complete": "カレンダーカバレッジ完了", "summary.failure_reason": "失敗理由", "summary.calendar_coverage_gaps": "カレンダー範囲の欠落", "summary.symbol_count": "銘柄数", "summary.snapshot_count": "スナップショット数", "summary.total_expected_items": "想定項目", "summary.complete_item_count": "完了項目", "summary.audited_item_count": "監査済み項目", "summary.warn_item_count": "警告", "summary.fail_item_count": "失敗", "summary.coverage_percentage": "カバレッジ率",
    "columns.run_id": "実行 ID", "columns.dataset": "データセット", "columns.status": "ステータス", "columns.started_at": "開始日時", "columns.finished_at": "完了日時", "columns.row_count": "行数", "columns.code": "コード", "columns.symbol": "銘柄", "columns.trade_date": "取引日", "columns.requested_trade_date": "要求取引日", "columns.interval": "足種", "columns.requested_session": "要求セッション", "columns.session": "セッション", "columns.adjustment": "株価調整", "columns.time_market": "市場時刻", "columns.time_utc": "UTC 時刻", "columns.open": "始値", "columns.high": "高値", "columns.low": "安値", "columns.close": "終値", "columns.volume": "出来高", "columns.scope_type": "範囲種別", "columns.scope_value": "範囲値", "columns.market": "市場", "columns.reference_code": "参照コード", "columns.trade_date_type": "取引日種別", "columns.state": "状態", "columns.source_state": "ソース状態", "columns.audit_status": "監査状態", "columns.complete_trade_date_count": "完了日", "columns.incomplete_trade_date_count": "未完了日", "columns.expected_trade_date_count": "想定日", "columns.coverage_percentage": "カバレッジ", "columns.first_trade_date": "最初の取引日", "columns.last_trade_date": "最後の取引日", "columns.snapshot_count": "スナップショット数", "columns.snapshot_row_count": "スナップショット行数", "columns.physical_scope_status": "物理範囲", "columns.symbols": "銘柄", "columns.rows": "行数",
}


# Additional known backend columns. Keys remain the backend schema identities;
# only their Treeview presentation labels are localized.
EN.update(
    {
        "columns.name": "Name",
        "columns.asset_type": "Asset type",
        "columns.underlying_code": "Underlying code",
        "columns.market_calendar_date": "Market calendar date",
        "columns.turnover": "Turnover",
        "columns.last_close": "Previous close",
        "columns.change_rate": "Change rate",
        "columns.pe_ratio": "P/E ratio",
        "columns.turnover_rate": "Turnover rate",
        "columns.source": "Source",
        "columns.source_schema_version": "Source schema version",
        "columns.ingestion_run_id": "Ingestion run ID",
        "columns.ingested_at": "Ingested at",
        "columns.time_key": "Provider time",
        "columns.requested_start_date": "Requested start date",
        "columns.requested_end_date": "Requested end date",
        "columns.captured_at": "Captured at",
        "columns.present_trade_date_count": "Present dates",
        "columns.latest_ingested_at": "Latest ingestion",
        "columns.missing_trade_date_count": "Missing dates",
        "columns.first_complete_date": "First complete date",
        "columns.last_complete_date": "Last complete date",
        "columns.incomplete_dates": "Incomplete dates",
        "columns.incomplete_reasons": "Incomplete reasons",
        "columns.missing_dates": "Missing dates",
        "columns.complete_dates": "Complete dates",
        "columns.boundary_evaluated": "Boundary evaluated",
        "columns.internal_gap_count": "Internal gaps",
        "columns.dates": "Dates",
        "columns.affected_rows": "Affected rows",
        "columns.raw_bytes": "Raw bytes",
        "columns.curated_bytes": "Curated bytes",
        "columns.raw_path": "Raw path",
        "columns.curated_path": "Curated path",
        "columns.run_kind": "Run kind",
        "columns.requested_items": "Requested items",
        "columns.errors": "Errors",
    }
)
ZH_CN.update(
    {
        "columns.name": "名称",
        "columns.asset_type": "资产类型",
        "columns.underlying_code": "标的代码",
        "columns.market_calendar_date": "市场日历日期",
        "columns.turnover": "成交额",
        "columns.last_close": "前收盘价",
        "columns.change_rate": "涨跌幅",
        "columns.pe_ratio": "市盈率",
        "columns.turnover_rate": "换手率",
        "columns.source": "来源",
        "columns.source_schema_version": "来源架构版本",
        "columns.ingestion_run_id": "采集运行 ID",
        "columns.ingested_at": "采集时间",
        "columns.time_key": "数据源时间",
        "columns.requested_start_date": "请求开始日期",
        "columns.requested_end_date": "请求结束日期",
        "columns.captured_at": "捕获时间",
        "columns.present_trade_date_count": "已有日期",
        "columns.latest_ingested_at": "最新采集时间",
        "columns.missing_trade_date_count": "缺失日期",
        "columns.first_complete_date": "首个完整日期",
        "columns.last_complete_date": "最后完整日期",
        "columns.incomplete_dates": "不完整日期",
        "columns.incomplete_reasons": "不完整原因",
        "columns.missing_dates": "缺失日期",
        "columns.complete_dates": "完整日期",
        "columns.boundary_evaluated": "已评估边界",
        "columns.internal_gap_count": "内部缺口",
        "columns.dates": "日期",
        "columns.affected_rows": "受影响行数",
        "columns.raw_bytes": "Raw 字节数",
        "columns.curated_bytes": "Curated 字节数",
        "columns.raw_path": "Raw 路径",
        "columns.curated_path": "Curated 路径",
        "columns.run_kind": "运行类型",
        "columns.requested_items": "请求项目",
        "columns.errors": "错误",
    }
)
JA.update(
    {
        "columns.name": "名称",
        "columns.asset_type": "資産種別",
        "columns.underlying_code": "原資産コード",
        "columns.market_calendar_date": "市場カレンダー日",
        "columns.turnover": "売買代金",
        "columns.last_close": "前日終値",
        "columns.change_rate": "騰落率",
        "columns.pe_ratio": "PER",
        "columns.turnover_rate": "売買回転率",
        "columns.source": "ソース",
        "columns.source_schema_version": "ソーススキーマ版",
        "columns.ingestion_run_id": "収集実行 ID",
        "columns.ingested_at": "収集日時",
        "columns.time_key": "プロバイダー時刻",
        "columns.requested_start_date": "要求開始日",
        "columns.requested_end_date": "要求終了日",
        "columns.captured_at": "取得日時",
        "columns.present_trade_date_count": "存在日",
        "columns.latest_ingested_at": "最新収集日時",
        "columns.missing_trade_date_count": "欠落日",
        "columns.first_complete_date": "最初の完了日",
        "columns.last_complete_date": "最後の完了日",
        "columns.incomplete_dates": "未完了日",
        "columns.incomplete_reasons": "未完了理由",
        "columns.missing_dates": "欠落日",
        "columns.complete_dates": "完了日",
        "columns.boundary_evaluated": "境界評価済み",
        "columns.internal_gap_count": "内部欠落数",
        "columns.dates": "日付",
        "columns.affected_rows": "対象行数",
        "columns.raw_bytes": "Raw バイト数",
        "columns.curated_bytes": "Curated バイト数",
        "columns.raw_path": "Raw パス",
        "columns.curated_path": "Curated パス",
        "columns.run_kind": "実行種別",
        "columns.requested_items": "要求項目",
        "columns.errors": "エラー",
    }
)


EN.update(
    {
        "header.subtitle": "Local Market Data Vault",
        "header.settings_path": "Settings: {settings_path}",
        "navigation.groups.data": "DATA",
        "navigation.groups.explore": "EXPLORE",
        "navigation.groups.quality": "QUALITY",
        "navigation.groups.activity": "ACTIVITY",
        "navigation.groups.advanced": "ADVANCED",
        "navigation.items.home": "Home",
        "navigation.items.historical_data": "Historical Data",
        "navigation.items.trading_calendar": "Trading Calendar",
        "navigation.items.market_data": "Market Data",
        "navigation.items.inventory": "Inventory",
        "navigation.items.coverage_audit": "Coverage Audit",
        "navigation.items.intraday_audit": "Intraday Audit",
        "navigation.items.runs": "Runs",
        "navigation.items.storage_cleanup": "Storage & Cleanup",
        "home.title": "Local data overview",
        "home.unloaded.body": "Refresh to inspect the current local archive.",
        "home.empty.body": (
            "No market data yet.\n"
            "Prepare a trading calendar or open Historical Data to begin."
        ),
    }
)
ZH_CN.update(
    {
        "header.subtitle": "本地市场数据仓库",
        "header.settings_path": "设置：{settings_path}",
        "navigation.groups.data": "数据",
        "navigation.groups.explore": "浏览",
        "navigation.groups.quality": "质量检查",
        "navigation.groups.activity": "运行",
        "navigation.groups.advanced": "高级管理",
        "navigation.items.home": "首页",
        "navigation.items.historical_data": "历史数据",
        "navigation.items.trading_calendar": "交易日历",
        "navigation.items.market_data": "行情数据",
        "navigation.items.inventory": "数据库存",
        "navigation.items.coverage_audit": "覆盖检查",
        "navigation.items.intraday_audit": "分钟数据检查",
        "navigation.items.runs": "运行记录",
        "navigation.items.storage_cleanup": "存储与清理",
        "home.title": "本地数据概览",
        "home.unloaded.body": "点击刷新以查看当前本地数据仓库。",
        "home.empty.body": (
            "暂无市场数据。\n"
            "可以先准备交易日历，或进入“历史数据”开始操作。"
        ),
    }
)
JA.update(
    {
        "header.subtitle": "ローカル市場データ保管庫",
        "header.settings_path": "設定：{settings_path}",
        "navigation.groups.data": "データ",
        "navigation.groups.explore": "閲覧",
        "navigation.groups.quality": "品質チェック",
        "navigation.groups.activity": "実行",
        "navigation.groups.advanced": "詳細管理",
        "navigation.items.home": "ホーム",
        "navigation.items.historical_data": "履歴データ",
        "navigation.items.trading_calendar": "取引カレンダー",
        "navigation.items.market_data": "市場データ",
        "navigation.items.inventory": "インベントリ",
        "navigation.items.coverage_audit": "カバレッジ監査",
        "navigation.items.intraday_audit": "日中データ監査",
        "navigation.items.runs": "実行履歴",
        "navigation.items.storage_cleanup": "ストレージとクリーンアップ",
        "home.title": "ローカルデータ概要",
        "home.unloaded.body": "更新して現在のローカルデータを確認してください。",
        "home.empty.body": (
            "市場データはまだありません。\n"
            "取引カレンダーを準備するか、「履歴データ」を開いて開始できます。"
        ),
    }
)


TRANSLATIONS: Mapping[str, Mapping[str, str]] = {
    "en": EN,
    "zh-CN": ZH_CN,
    "ja": JA,
}


def translation_key_parity() -> bool:
    english_keys = set(EN)
    return all(set(TRANSLATIONS[locale]) == english_keys for locale in SUPPORTED_LOCALES)


class Translator:
    def __init__(self, locale: str = DEFAULT_LOCALE):
        self.locale = locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE

    def set_locale(self, locale: str) -> None:
        self.locale = locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE

    @staticmethod
    def has_key(key: str) -> bool:
        return key in EN

    def t(self, key: str, **values) -> str:
        catalog = TRANSLATIONS.get(self.locale, EN)
        template = catalog.get(key, EN.get(key, key))
        try:
            return template.format(**values)
        except (KeyError, ValueError):
            return template


def choose_ui_font(locale: str, available_families: set[str]) -> str:
    preferred = {
        "en": "Segoe UI",
        "zh-CN": "Microsoft YaHei UI",
        "ja": "Yu Gothic UI",
    }.get(locale, "Segoe UI")
    if preferred in available_families:
        return preferred
    if "Segoe UI" in available_families:
        return "Segoe UI"
    return "TkDefaultFont"


@dataclass
class TextBinding:
    translator: Translator
    setter: Callable[[str], None]
    key: str
    values: dict = field(default_factory=dict)

    def refresh(self) -> None:
        self.setter(self.translator.t(self.key, **self.values))

    def update(self, key: str | None = None, **values) -> None:
        if key is not None:
            self.key = key
        self.values = values
        self.refresh()


class LocalizationBindings:
    """Tk-independent registry for live translation of existing UI objects."""

    def __init__(self, translator: Translator):
        self.translator = translator
        self._bindings: list[TextBinding] = []
        self._refresh_callbacks: list[Callable[[], None]] = []

    def bind(self, setter: Callable[[str], None], key: str, **values) -> TextBinding:
        binding = TextBinding(self.translator, setter, key, values)
        self._bindings.append(binding)
        binding.refresh()
        return binding

    def on_refresh(self, callback: Callable[[], None]) -> None:
        self._refresh_callbacks.append(callback)

    def set_locale(self, locale: str) -> None:
        self.translator.set_locale(locale)
        self.refresh()

    def refresh(self) -> None:
        for binding in self._bindings:
            binding.refresh()
        for callback in self._refresh_callbacks:
            callback()
