from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from ..api import MarketVault, QueryPage
from .models import BackfillPlanView, DashboardSnapshot, ExportResult, PurgePlanView, TablePage


MAX_EXPORT_ROWS = 1000
MAX_PLAN_DISPLAY_ROWS = 1000
MAX_REPORT_DISPLAY_ROWS = 1000


def parse_iso_date(value: str, field_name: str, *, required: bool = True) -> date | None:
    text = value.strip()
    if not text:
        if required:
            raise ValueError(f"{field_name} is required")
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD") from exc


def parse_symbols(value: str | list[str]) -> list[str]:
    raw = value if isinstance(value, list) else value.replace(",", " ").split()
    symbols = sorted({item.strip().upper() for item in raw if item.strip()})
    if not symbols:
        raise ValueError("At least one symbol is required")
    return symbols


def _display_value(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            pass
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def table_page_from_query(page: QueryPage) -> TablePage:
    columns = tuple(str(column) for column in page.data.columns)
    rows = tuple(
        tuple(_display_value(value) for value in row)
        for row in page.data.itertuples(index=False, name=None)
    )
    return TablePage(columns, rows, page.page, page.page_size, page.total_rows)


def table_page_from_records(
    records: list[dict[str, Any]],
    *,
    page: int = 1,
    page_size: int = 100,
    total_rows: int | None = None,
) -> TablePage:
    if page < 1:
        raise ValueError("page must be at least 1")
    if page_size < 1 or page_size > 1000:
        raise ValueError("page_size must be between 1 and 1000")
    columns: tuple[str, ...] = tuple(records[0]) if records else ()
    rows = tuple(
        tuple(_display_value(record.get(column)) for column in columns)
        for record in records[:page_size]
    )
    return TablePage(columns, rows, page, page_size, len(records) if total_rows is None else total_rows)


def _audit_summary(report: Any) -> dict[str, Any]:
    summary = report.summary.as_dict() if report.summary is not None else {}
    summary["status"] = report.status
    calendar = getattr(report, "calendar", None)
    if calendar is None:
        return summary

    coverage_complete = bool(calendar.coverage_complete)
    coverage_gaps = list(calendar.coverage_gaps)
    summary["calendar_coverage_complete"] = coverage_complete
    summary["calendar_coverage_gaps"] = coverage_gaps
    if not coverage_complete:
        ranges = ", ".join(
            f"{gap.get('start_date', '?')}..{gap.get('end_date', '?')}"
            for gap in coverage_gaps
        )
        suffix = f" Missing ranges: {ranges}." if ranges else ""
        summary["failure_reason"] = (
            "Trading-calendar coverage is incomplete; audit classifications "
            f"were not evaluated.{suffix}"
        )
    return summary


class ConsoleBackend:
    """Headless application service used by the Tkinter Console.

    Local query, audit, purge-plan, and purge-execute methods never invoke
    OpenD. Only ``collect_calendar`` and ``execute_backfill`` are explicit
    network-capable operator actions, routed through MarketVault service
    abstractions.
    """

    def __init__(self, vault: MarketVault):
        self.vault = vault
        self._executable_purge_plan_id: str | None = None

    @classmethod
    def from_settings(cls, settings_path: str | Path) -> "ConsoleBackend":
        return cls(MarketVault(settings_path))

    def dashboard(self) -> DashboardSnapshot:
        inventory = self.vault.inventory_market_bars(include_files=False)
        summary = inventory.summary
        metrics = {
            "Symbols": str(summary.symbol_count),
            "Snapshots": str(summary.snapshot_count),
            "Latest rows": str(summary.latest_query_row_count),
            "Completed dates": str(summary.completed_trade_date_count),
            "Incomplete dates": str(summary.incomplete_trade_date_count),
            "Latest trade date": summary.latest_trade_date or "-",
        }
        recent = table_page_from_query(self.vault.load_run_history_page(page=1, page_size=20))
        return DashboardSnapshot(inventory.status, metrics, recent, inventory.report_file or "")

    def query_bars(
        self,
        *,
        code: str,
        start_date: str = "",
        end_date: str = "",
        interval: str = "1m",
        requested_session: str = "",
        bar_session: str = "",
        adjustment: str = "NONE",
        page: int = 1,
        page_size: int = 100,
    ) -> TablePage:
        result = self.vault.load_bars_page(
            code=code,
            start_date=parse_iso_date(start_date, "start_date", required=False),
            end_date=parse_iso_date(end_date, "end_date", required=False),
            interval=interval,
            requested_session=requested_session or None,
            bar_session=bar_session or None,
            adjustment=adjustment,
            page=page,
            page_size=page_size,
        )
        return table_page_from_query(result)

    def inventory(
        self,
        *,
        symbols: str = "",
        start_date: str = "",
        end_date: str = "",
        interval: str = "",
        session: str = "",
        adjustment: str = "",
    ) -> tuple[dict[str, Any], TablePage]:
        report = self.vault.inventory_market_bars(
            symbols=parse_symbols(symbols) if symbols.strip() else None,
            start_date=parse_iso_date(start_date, "start_date", required=False),
            end_date=parse_iso_date(end_date, "end_date", required=False),
            interval=interval or None,
            session=session or None,
            adjustment=adjustment or None,
            include_files=False,
        )
        return report.summary.as_dict(), table_page_from_records(
            [item.as_dict() for item in report.items[:MAX_REPORT_DISPLAY_ROWS]],
            page_size=MAX_REPORT_DISPLAY_ROWS,
            total_rows=len(report.items),
        )

    def coverage_audit(
        self,
        *,
        symbols: str,
        start_date: str,
        end_date: str,
        calendar_market: str = "US",
        calendar_code: str = "",
        interval: str = "1m",
        session: str = "ALL",
        adjustment: str = "NONE",
    ) -> tuple[dict[str, Any], TablePage]:
        report = self.vault.audit_market_bars(
            symbols=parse_symbols(symbols),
            start_date=parse_iso_date(start_date, "start_date"),
            end_date=parse_iso_date(end_date, "end_date"),
            calendar_market=calendar_market or None,
            calendar_code=calendar_code or None,
            interval=interval,
            session=session,
            adjustment=adjustment,
        )
        summary = _audit_summary(report)
        return summary, table_page_from_records(
            [item.as_dict() for item in report.symbols[:MAX_REPORT_DISPLAY_ROWS]],
            page_size=MAX_REPORT_DISPLAY_ROWS,
            total_rows=len(report.symbols),
        )

    def intraday_audit(
        self,
        *,
        symbols: str,
        start_date: str,
        end_date: str,
        calendar_market: str = "US",
        calendar_code: str = "",
        interval: str = "1m",
        session: str = "ALL",
        adjustment: str = "NONE",
    ) -> tuple[dict[str, Any], TablePage]:
        report = self.vault.audit_intraday_market_bars(
            symbols=parse_symbols(symbols),
            start_date=parse_iso_date(start_date, "start_date"),
            end_date=parse_iso_date(end_date, "end_date"),
            calendar_market=calendar_market or None,
            calendar_code=calendar_code or None,
            interval=interval,
            session=session,
            adjustment=adjustment,
        )
        records: list[dict[str, Any]] = []
        total_rows = sum(len(symbol.items) for symbol in report.symbols)
        for symbol in report.symbols:
            for item in symbol.items:
                if len(records) >= MAX_REPORT_DISPLAY_ROWS:
                    break
                records.append(
                    {
                        "code": symbol.code,
                        "trade_date": item.requested_trade_date,
                        "source_state": item.source_state,
                        "audit_status": item.audit_status,
                        "boundary_evaluated": item.boundary_coverage.evaluated,
                        "row_count": (
                            sum(item.observed.session_row_counts.values())
                            if item.observed is not None
                            else 0
                        ),
                        "internal_gap_count": len(item.internal_gaps),
                    }
                )
            if len(records) >= MAX_REPORT_DISPLAY_ROWS:
                break
        summary = _audit_summary(report)
        return summary, table_page_from_records(
            records,
            page_size=MAX_REPORT_DISPLAY_ROWS,
            total_rows=total_rows,
        )

    def query_calendar(
        self,
        *,
        market: str = "",
        code: str = "",
        start_date: str = "",
        end_date: str = "",
        page: int = 1,
        page_size: int = 100,
    ) -> TablePage:
        result = self.vault.load_trading_calendar_page(
            market=market or None,
            code=code or None,
            start_date=parse_iso_date(start_date, "start_date", required=False),
            end_date=parse_iso_date(end_date, "end_date", required=False),
            page=page,
            page_size=page_size,
        )
        return table_page_from_query(result)

    def collect_calendar(
        self,
        *,
        market: str = "",
        code: str = "",
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        manifest = self.vault.collect_trading_calendar(
            market=market or None,
            code=code or None,
            start_date=parse_iso_date(start_date, "start_date"),
            end_date=parse_iso_date(end_date, "end_date"),
        )
        return manifest.as_dict()

    def plan_backfill(self, **values: Any) -> BackfillPlanView:
        plan = self.vault.plan_backfill(**self._backfill_arguments(values, execute=False))
        records = [
            {"code": item.code, "trade_date": item.trade_date, "state": "PENDING"}
            for item in plan.pending_items[:MAX_PLAN_DISPLAY_ROWS]
        ]
        remaining = MAX_PLAN_DISPLAY_ROWS - len(records)
        if remaining > 0:
            records.extend(
                {"code": item.code, "trade_date": item.trade_date, "state": "SKIPPED"}
                for item in plan.skipped_items[:remaining]
            )
        total = len(plan.pending_items) + len(plan.skipped_items)
        return BackfillPlanView(
            scope=f"{plan.calendar_scope_type}:{plan.calendar_scope_value}",
            symbols=tuple(plan.symbols),
            trading_date_count=len(plan.trading_dates),
            pending_count=len(plan.pending_items),
            skipped_count=len(plan.skipped_items),
            items=table_page_from_records(
                records,
                page_size=MAX_PLAN_DISPLAY_ROWS,
                total_rows=total,
            ),
        )

    def execute_backfill(self, **values: Any) -> dict[str, Any]:
        manifest = self.vault.backfill(**self._backfill_arguments(values, execute=True))
        return manifest.as_dict()

    def preview_purge(
        self,
        *,
        source: str,
        symbols: str,
        start_date: str,
        end_date: str,
        interval: str,
        session: str,
        adjustment: str,
        source_schema_version: str,
    ) -> PurgePlanView:
        """Create the only plan that this backend instance may execute."""
        self._executable_purge_plan_id = None
        plan = self.vault.purge_plan(
            source=source.strip(),
            symbols=parse_symbols(symbols),
            start_date=parse_iso_date(start_date, "start_date"),
            end_date=parse_iso_date(end_date, "end_date"),
            interval=interval.strip(),
            requested_session=session.strip(),
            adjustment=adjustment.strip(),
            source_schema_version=source_schema_version.strip(),
        )
        records = []
        for target in plan.targets[:MAX_PLAN_DISPLAY_ROWS]:
            facts = target["curated"]["facts"]
            records.append(
                {
                    "ingestion_run_id": target["ingestion_run_id"],
                    "physical_scope_status": target["physical_scope_status"],
                    "symbols": facts["symbols"],
                    "dates": facts["dates"],
                    "affected_rows": target["affected_row_count"],
                    "raw_bytes": target["raw"]["byte_size"],
                    "curated_bytes": target["curated"]["byte_size"],
                    "raw_path": target["raw"]["relative_path"],
                    "curated_path": target["curated"]["relative_path"],
                }
            )
        if plan.executable:
            self._executable_purge_plan_id = plan.plan_id
        return PurgePlanView(
            plan_id=plan.plan_id,
            status=plan.status,
            executable=plan.executable,
            summary=plan.summary,
            refusal_reasons=plan.refusal_reasons,
            items=table_page_from_records(
                records,
                page_size=MAX_PLAN_DISPLAY_ROWS,
                total_rows=len(plan.targets),
            ),
        )

    def execute_purge(self, *, plan_id: str, confirmation: str) -> dict[str, Any]:
        if not self._executable_purge_plan_id:
            raise ValueError("Preview an executable purge plan before execution")
        if plan_id != self._executable_purge_plan_id:
            raise ValueError("The requested purge plan is not the current reviewed plan")
        result = self.vault.purge_execute(plan_id=plan_id, confirmation=confirmation)
        self._executable_purge_plan_id = None
        return result.as_dict()

    def runs(
        self,
        *,
        page: int = 1,
        page_size: int = 100,
        status: str = "",
        dataset: str = "",
    ) -> TablePage:
        return table_page_from_query(
            self.vault.load_run_history_page(
                page=page,
                page_size=page_size,
                status=status or None,
                dataset=dataset or None,
            )
        )

    def export_page(self, table: TablePage, destination: str | Path, format_name: str) -> ExportResult:
        if len(table.rows) > MAX_EXPORT_ROWS:
            raise ValueError(f"Cannot export more than {MAX_EXPORT_ROWS} loaded rows")
        path = Path(destination).expanduser().resolve()
        if not path.parent.exists():
            raise ValueError(f"Export directory does not exist: {path.parent}")
        normalized_format = format_name.strip().lower()
        if normalized_format == "csv":
            with path.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(table.columns)
                writer.writerows(table.rows)
        elif normalized_format == "json":
            records = [dict(zip(table.columns, row, strict=True)) for row in table.rows]
            path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            raise ValueError("Export format must be csv or json")
        return ExportResult(str(path), normalized_format, len(table.rows))

    def _backfill_arguments(self, values: dict[str, Any], *, execute: bool) -> dict[str, Any]:
        arguments: dict[str, Any] = {
            "symbols": parse_symbols(str(values.get("symbols", ""))),
            "start_date": parse_iso_date(str(values.get("start_date", "")), "start_date", required=False),
            "end_date": parse_iso_date(str(values.get("end_date", "")), "end_date"),
            "calendar_market": str(values.get("calendar_market", "")).strip().upper() or None,
            "calendar_code": str(values.get("calendar_code", "")).strip().upper() or None,
            "interval": str(values.get("interval", "1m")),
            "session": str(values.get("session", "ALL")),
            "adjustment": str(values.get("adjustment", "NONE")),
            "force": bool(values.get("force", False)),
            "incremental": bool(values.get("incremental", False)),
            "bootstrap_start_date": parse_iso_date(
                str(values.get("bootstrap_start_date", "")),
                "bootstrap_start_date",
                required=False,
            ),
        }
        if execute:
            arguments["max_retries"] = int(values.get("max_retries", 2))
            arguments["retry_backoff_seconds"] = float(values.get("retry_backoff_seconds", 2.0))
        return arguments
