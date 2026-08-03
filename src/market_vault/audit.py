from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from .backfill import normalize_backfill_symbols, resolve_calendar_scope
from .coverage import load_market_bar_coverage_state
from .models import Settings
from .reporting import write_json_report_atomic
from .storage import Catalog

#: Legacy snapshot files are named batch-<16 hex>.parquet; current snapshot
#: files carry a run id suffix: batch-<16 hex>-<run id>.parquet.
LEGACY_BATCH_FILENAME_RE = re.compile(r"^batch-[0-9a-f]{16}\.parquet$")

INVENTORY_REPORT_TYPE = "MARKET_BARS_INVENTORY"
AUDIT_REPORT_TYPE = "MARKET_BARS_COVERAGE_AUDIT"

EMPTY = "EMPTY"
PASS = "PASS"
WARN = "WARN"
FAILED = "FAILED"
SUCCESS = "SUCCESS"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_timestamp(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


@dataclass
class PhysicalStorage:
    raw_file_count: int = 0
    raw_total_bytes: int = 0
    curated_file_count: int = 0
    curated_total_bytes: int = 0
    oldest_file_modified_at: str | None = None
    newest_file_modified_at: str | None = None

    def as_dict(self) -> dict:
        return {
            "raw_file_count": self.raw_file_count,
            "raw_total_bytes": self.raw_total_bytes,
            "curated_file_count": self.curated_file_count,
            "curated_total_bytes": self.curated_total_bytes,
            "oldest_file_modified_at": self.oldest_file_modified_at,
            "newest_file_modified_at": self.newest_file_modified_at,
        }


@dataclass
class InventorySummary:
    symbol_count: int = 0
    parameter_combination_count: int = 0
    snapshot_count: int = 0
    snapshot_row_count: int = 0
    latest_query_row_count: int = 0
    present_trade_date_count: int = 0
    completed_trade_date_count: int = 0
    incomplete_trade_date_count: int = 0
    legacy_metadata_row_count: int = 0
    earliest_trade_date: str | None = None
    latest_trade_date: str | None = None
    latest_ingested_at: str | None = None

    def as_dict(self) -> dict:
        return {
            "symbol_count": self.symbol_count,
            "parameter_combination_count": self.parameter_combination_count,
            "snapshot_count": self.snapshot_count,
            "snapshot_row_count": self.snapshot_row_count,
            "latest_query_row_count": self.latest_query_row_count,
            "present_trade_date_count": self.present_trade_date_count,
            "completed_trade_date_count": self.completed_trade_date_count,
            "incomplete_trade_date_count": self.incomplete_trade_date_count,
            "legacy_metadata_row_count": self.legacy_metadata_row_count,
            "earliest_trade_date": self.earliest_trade_date,
            "latest_trade_date": self.latest_trade_date,
            "latest_ingested_at": self.latest_ingested_at,
        }


@dataclass
class InventoryItem:
    code: str
    interval: str
    requested_session: str | None
    adjustment: str
    source_schema_version: str | None
    first_trade_date: str | None
    last_trade_date: str | None
    present_trade_date_count: int
    completed_trade_date_count: int
    incomplete_trade_date_count: int
    snapshot_count: int
    snapshot_row_count: int
    latest_ingested_at: str | None

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "interval": self.interval,
            "requested_session": self.requested_session,
            "adjustment": self.adjustment,
            "source_schema_version": self.source_schema_version,
            "first_trade_date": self.first_trade_date,
            "last_trade_date": self.last_trade_date,
            "present_trade_date_count": self.present_trade_date_count,
            "completed_trade_date_count": self.completed_trade_date_count,
            "incomplete_trade_date_count": self.incomplete_trade_date_count,
            "snapshot_count": self.snapshot_count,
            "snapshot_row_count": self.snapshot_row_count,
            "latest_ingested_at": self.latest_ingested_at,
        }


@dataclass
class InventoryFileEntry:
    layer: str
    relative_path: str
    size_bytes: int
    modified_at: str
    legacy_filename: bool

    def as_dict(self) -> dict:
        return {
            "layer": self.layer,
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
            "modified_at": self.modified_at,
            "legacy_filename": self.legacy_filename,
        }


@dataclass
class InventoryReport:
    run_id: str
    started_at: str
    finished_at: str | None = None
    status: str = SUCCESS
    parameters: dict = field(default_factory=dict)
    physical_storage: PhysicalStorage = field(default_factory=PhysicalStorage)
    summary: InventorySummary = field(default_factory=InventorySummary)
    items: list[InventoryItem] = field(default_factory=list)
    files: list[InventoryFileEntry] = field(default_factory=list)
    report_file: str | None = None

    def as_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "report_type": INVENTORY_REPORT_TYPE,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "parameters": self.parameters,
            "physical_storage": self.physical_storage.as_dict(),
            "summary": self.summary.as_dict(),
            "items": [item.as_dict() for item in self.items],
            "files": [entry.as_dict() for entry in self.files],
            "report_file": self.report_file,
        }


@dataclass
class AuditCalendarInfo:
    coverage_complete: bool = True
    coverage_gaps: list[dict] = field(default_factory=list)
    expected_trade_date_count: int = 0
    expected_trade_dates: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "coverage_complete": self.coverage_complete,
            "coverage_gaps": self.coverage_gaps,
            "expected_trade_date_count": self.expected_trade_date_count,
            "expected_trade_dates": self.expected_trade_dates,
        }


@dataclass
class AuditSummary:
    total_expected_items: int = 0
    complete_item_count: int = 0
    incomplete_item_count: int = 0
    missing_item_count: int = 0
    coverage_percentage: float = 100.0

    def as_dict(self) -> dict:
        return {
            "total_expected_items": self.total_expected_items,
            "complete_item_count": self.complete_item_count,
            "incomplete_item_count": self.incomplete_item_count,
            "missing_item_count": self.missing_item_count,
            "coverage_percentage": self.coverage_percentage,
        }


@dataclass
class AuditSymbolReport:
    code: str
    expected_trade_date_count: int = 0
    complete_trade_date_count: int = 0
    incomplete_trade_date_count: int = 0
    missing_trade_date_count: int = 0
    coverage_percentage: float = 100.0
    first_complete_date: str | None = None
    last_complete_date: str | None = None
    incomplete_dates: list[str] = field(default_factory=list)
    incomplete_reasons: dict[str, list[str]] = field(default_factory=dict)
    missing_dates: list[str] = field(default_factory=list)
    complete_dates: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        result = {
            "code": self.code,
            "expected_trade_date_count": self.expected_trade_date_count,
            "complete_trade_date_count": self.complete_trade_date_count,
            "incomplete_trade_date_count": self.incomplete_trade_date_count,
            "missing_trade_date_count": self.missing_trade_date_count,
            "coverage_percentage": self.coverage_percentage,
            "first_complete_date": self.first_complete_date,
            "last_complete_date": self.last_complete_date,
            "incomplete_dates": self.incomplete_dates,
            "incomplete_reasons": self.incomplete_reasons,
            "missing_dates": self.missing_dates,
        }
        if self.complete_dates:
            result["complete_dates"] = self.complete_dates
        return result


@dataclass
class AuditReport:
    run_id: str
    started_at: str
    finished_at: str | None = None
    status: str = FAILED
    parameters: dict = field(default_factory=dict)
    calendar: AuditCalendarInfo = field(default_factory=AuditCalendarInfo)
    summary: AuditSummary | None = None
    symbols: list[AuditSymbolReport] = field(default_factory=list)
    report_file: str | None = None

    def as_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "report_type": AUDIT_REPORT_TYPE,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "parameters": self.parameters,
            "calendar": self.calendar.as_dict(),
            "summary": self.summary.as_dict() if self.summary else None,
            "symbols": [symbol.as_dict() for symbol in self.symbols],
            "report_file": self.report_file,
        }


def _market_bars_roots(settings: Settings) -> tuple[Path, Path]:
    root = settings.data_root
    return (
        root / "raw" / f"source={settings.source}" / "dataset=market_bars",
        root / "curated" / f"source={settings.source}" / "dataset=market_bars",
    )


def _market_bars_files(settings: Settings) -> tuple[list[Path], list[Path]]:
    raw_root, curated_root = _market_bars_roots(settings)
    raw_files = list(raw_root.rglob("*.parquet")) if raw_root.exists() else []
    curated_files = list(curated_root.rglob("*.parquet")) if curated_root.exists() else []
    return raw_files, curated_files


def _physical_storage(raw_files: list[Path], curated_files: list[Path]) -> PhysicalStorage:
    raw_bytes = sum(item.stat().st_size for item in raw_files)
    curated_bytes = sum(item.stat().st_size for item in curated_files)
    all_files = raw_files + curated_files
    oldest = newest = None
    if all_files:
        timestamps = sorted(item.stat().st_mtime for item in all_files)
        oldest = _iso_timestamp(datetime.fromtimestamp(timestamps[0], tz=timezone.utc))
        newest = _iso_timestamp(datetime.fromtimestamp(timestamps[-1], tz=timezone.utc))
    return PhysicalStorage(
        raw_file_count=len(raw_files),
        raw_total_bytes=raw_bytes,
        curated_file_count=len(curated_files),
        curated_total_bytes=curated_bytes,
        oldest_file_modified_at=oldest,
        newest_file_modified_at=newest,
    )


def _file_entries(
    settings: Settings,
    raw_files: list[Path],
    curated_files: list[Path],
) -> list[InventoryFileEntry]:
    entries: list[InventoryFileEntry] = []
    for layer, files in (("raw", raw_files), ("curated", curated_files)):
        for path in files:
            stat = path.stat()
            entries.append(
                InventoryFileEntry(
                    layer=layer,
                    relative_path=path.relative_to(settings.data_root).as_posix(),
                    size_bytes=stat.st_size,
                    modified_at=_iso_timestamp(datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)) or "",
                    legacy_filename=bool(LEGACY_BATCH_FILENAME_RE.match(path.name)),
                )
            )
    entries.sort(key=lambda entry: (entry.layer, entry.relative_path))
    return entries


def _finish_report(report, prefix: str, settings: Settings) -> None:
    report.finished_at = _now_iso()
    report_path = settings.report_dir / f"{prefix}_{report.run_id}.json"
    payload = report.as_dict()
    payload["report_file"] = str(report_path)
    write_json_report_atomic(report_path, payload)
    report.report_file = str(report_path)


def run_inventory(
    settings: Settings,
    *,
    symbols: list[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    interval: str | None = None,
    requested_session: str | None = None,
    adjustment: str | None = None,
    source_schema_version: str | None = None,
    include_files: bool = False,
) -> InventoryReport:
    """Summarize local market-bar storage, snapshots, and coverage.

    Pure local: no collector, no OpenD connection, no data mutation.
    """
    report = InventoryReport(run_id=str(uuid4()), started_at=_now_iso())
    normalized_symbols = normalize_backfill_symbols(symbols) if symbols else None
    interval_value = interval.lower() if interval else None
    session_value = requested_session.upper() if requested_session else None
    adjustment_value = adjustment.upper() if adjustment else None
    schema_value = source_schema_version.strip() if source_schema_version else None
    report.parameters = {
        "symbols": normalized_symbols or [],
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "interval": interval_value,
        "requested_session": session_value,
        "adjustment": adjustment_value,
        "source_schema_version": schema_value,
        "include_files": include_files,
    }

    raw_files, curated_files = _market_bars_files(settings)
    report.physical_storage = _physical_storage(raw_files, curated_files)
    if include_files:
        report.files = _file_entries(settings, raw_files, curated_files)

    catalog = Catalog(settings)
    if not curated_files or not catalog.refresh_market_bars_view():
        report.status = EMPTY
        _finish_report(report, "market_bars_inventory", settings)
        return report

    columns = catalog.market_bars_snapshot_columns()
    has_session = "requested_session" in columns
    has_schema = "source_schema_version" in columns
    has_run_id = "ingestion_run_id" in columns
    run_id_expr = "ingestion_run_id" if has_run_id else "NULL::VARCHAR"

    where_clause, params = _inventory_where(
        normalized_symbols,
        start_date,
        end_date,
        interval_value,
        session_value,
        adjustment_value,
        schema_value,
        has_session=has_session,
        has_schema=has_schema,
    )
    session_expr = "requested_session" if has_session else "NULL::VARCHAR"
    schema_expr = "source_schema_version" if has_schema else "NULL::VARCHAR"

    with catalog.connect() as con:
        agg_sql = f"""
            SELECT
                code,
                interval,
                {session_expr} AS requested_session,
                adjustment,
                {schema_expr} AS source_schema_version,
                MIN(requested_trade_date) AS first_trade_date,
                MAX(requested_trade_date) AS last_trade_date,
                COUNT(DISTINCT requested_trade_date) AS present_trade_date_count,
                COUNT(DISTINCT {run_id_expr}) AS snapshot_count,
                COUNT(*) AS snapshot_row_count,
                MAX(ingested_at) AS latest_ingested_at,
                COUNT(*) FILTER (
                    WHERE {session_expr} IS NULL OR {schema_expr} IS NULL
                ) AS legacy_metadata_row_count
            FROM market_bars_snapshots
            WHERE 1 = 1 {where_clause}
            GROUP BY code, interval, requested_session, adjustment, source_schema_version
            ORDER BY code, interval, requested_session, adjustment, source_schema_version
        """
        agg_rows = con.execute(agg_sql, params).fetchall()
        latest_query_sql = f"SELECT COUNT(*) FROM market_bars WHERE 1 = 1 {where_clause}"
        latest_query_row_count = int(con.execute(latest_query_sql, params).fetchone()[0])
        # Global snapshot count over the same filters: distinct run ids
        # across the whole range, not a sum over per-combination items.
        # COUNT(DISTINCT ...) keeps DuckDB's NULL-excluding semantics, so
        # rows without a run id never inflate the count.
        snapshot_sql = (
            f"SELECT COUNT(DISTINCT {run_id_expr}) FROM market_bars_snapshots WHERE 1 = 1 {where_clause}"
        )
        global_snapshot_count = int(con.execute(snapshot_sql, params).fetchone()[0])

    items: list[InventoryItem] = []
    legacy_total = 0
    for (
        code,
        interval_value,
        session_value,
        adjustment_value,
        schema_value,
        first_trade_date,
        last_trade_date,
        present_count,
        snapshot_count,
        snapshot_row_count,
        latest_ingested_at,
        legacy_rows,
    ) in agg_rows:
        legacy_total += int(legacy_rows or 0)
        dates = _combination_dates(
            catalog,
            has_session=has_session,
            has_schema=has_schema,
            code=code,
            interval=interval_value,
            session=session_value,
            adjustment=adjustment_value,
            schema=schema_value,
            start_date=start_date,
            end_date=end_date,
        )
        completed = (
            catalog.completed_market_bar_items(
                symbols=[code],
                trade_dates=dates,
                interval=interval_value,
                requested_session=session_value or "",
                adjustment=adjustment_value,
                source_schema_version=schema_value or "",
            )
            if dates
            else set()
        )
        items.append(
            InventoryItem(
                code=code,
                interval=interval_value,
                requested_session=session_value,
                adjustment=adjustment_value,
                source_schema_version=schema_value,
                first_trade_date=_iso_timestamp(first_trade_date),
                last_trade_date=_iso_timestamp(last_trade_date),
                present_trade_date_count=int(present_count),
                completed_trade_date_count=len(completed),
                incomplete_trade_date_count=int(present_count) - len(completed),
                snapshot_count=int(snapshot_count),
                snapshot_row_count=int(snapshot_row_count),
                latest_ingested_at=_iso_timestamp(latest_ingested_at),
            )
        )

    first_dates = [item.first_trade_date for item in items if item.first_trade_date]
    last_dates = [item.last_trade_date for item in items if item.last_trade_date]
    report.summary = InventorySummary(
        symbol_count=len({item.code for item in items}),
        parameter_combination_count=len(items),
        snapshot_count=global_snapshot_count,
        snapshot_row_count=sum(item.snapshot_row_count for item in items),
        latest_query_row_count=latest_query_row_count,
        present_trade_date_count=sum(item.present_trade_date_count for item in items),
        completed_trade_date_count=sum(item.completed_trade_date_count for item in items),
        incomplete_trade_date_count=sum(item.incomplete_trade_date_count for item in items),
        legacy_metadata_row_count=legacy_total,
        earliest_trade_date=min(first_dates) if first_dates else None,
        latest_trade_date=max(last_dates) if last_dates else None,
        latest_ingested_at=max(
            (item.latest_ingested_at for item in items if item.latest_ingested_at),
            default=None,
        ),
    )
    report.items = items
    _finish_report(report, "market_bars_inventory", settings)
    return report


def _inventory_where(
    symbols: list[str] | None,
    start_date: date | None,
    end_date: date | None,
    interval: str | None,
    requested_session: str | None,
    adjustment: str | None,
    source_schema_version: str | None,
    *,
    has_session: bool,
    has_schema: bool,
) -> tuple[str, list[object]]:
    clauses: list[str] = []
    params: list[object] = []
    if symbols:
        clauses.append(f"code IN ({', '.join('?' for _ in symbols)})")
        params.extend(symbols)
    if start_date is not None:
        clauses.append("requested_trade_date >= ?")
        params.append(start_date)
    if end_date is not None:
        clauses.append("requested_trade_date <= ?")
        params.append(end_date)
    if interval is not None:
        clauses.append("interval = ?")
        params.append(interval)
    if requested_session is not None:
        if has_session:
            clauses.append("requested_session = ?")
            params.append(requested_session)
        else:
            clauses.append("FALSE")
    if adjustment is not None:
        clauses.append("adjustment = ?")
        params.append(adjustment)
    if source_schema_version is not None:
        if has_schema:
            clauses.append("source_schema_version = ?")
            params.append(source_schema_version)
        else:
            clauses.append("FALSE")
    return (f" AND ({' AND '.join(clauses)})" if clauses else ""), params


def _combination_dates(
    catalog: Catalog,
    *,
    has_session: bool,
    has_schema: bool,
    code: str,
    interval: str,
    session: str | None,
    adjustment: str,
    schema: str | None,
    start_date: date | None,
    end_date: date | None,
) -> list[date]:
    clauses = ["code = ?", "interval = ?", "adjustment = ?"]
    params: list[object] = [code, interval, adjustment]
    if has_session:
        clauses.append("requested_session IS NULL" if session is None else "requested_session = ?")
        if session is not None:
            params.append(session)
    elif session is not None:
        return []
    if has_schema:
        clauses.append("source_schema_version IS NULL" if schema is None else "source_schema_version = ?")
        if schema is not None:
            params.append(schema)
    elif schema is not None:
        return []
    if start_date is not None:
        clauses.append("requested_trade_date >= ?")
        params.append(start_date)
    if end_date is not None:
        clauses.append("requested_trade_date <= ?")
        params.append(end_date)
    sql = f"""
        SELECT DISTINCT requested_trade_date
        FROM market_bars_snapshots
        WHERE {' AND '.join(clauses)}
        ORDER BY requested_trade_date
    """
    with catalog.connect() as con:
        rows = con.execute(sql, params).fetchall()
    return [row[0] for row in rows]


def run_audit(
    settings: Settings,
    *,
    symbols: list[str],
    start_date: date,
    end_date: date,
    calendar_market: str | None = None,
    calendar_code: str | None = None,
    interval: str = "1m",
    requested_session: str | None = None,
    adjustment: str | None = None,
    source_schema_version: str | None = None,
    include_complete_dates: bool = False,
    today: date | None = None,
) -> AuditReport:
    """Audit trading-day coverage against the local trading calendar.

    Pure local: no collector, no OpenD connection, no data mutation.
    """
    effective_today = today or datetime.now(timezone.utc).date()
    normalized_symbols = normalize_backfill_symbols(symbols)
    interval_value = interval.lower()
    session_value = (requested_session or settings.default_session).upper()
    adjustment_value = (adjustment or settings.default_adjustment).upper()
    schema_value = source_schema_version or settings.source_schema_version
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    if end_date >= effective_today:
        raise ValueError("end_date must be before today's UTC date")
    scope_type, scope_value = resolve_calendar_scope(calendar_market, calendar_code)

    report = AuditReport(run_id=str(uuid4()), started_at=_now_iso())
    report.parameters = {
        "calendar_scope_type": scope_type,
        "calendar_scope_value": scope_value,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "symbols": normalized_symbols,
        "interval": interval_value,
        "requested_session": session_value,
        "adjustment": adjustment_value,
        "source_schema_version": schema_value,
    }

    state = load_market_bar_coverage_state(
        settings,
        scope_type=scope_type,
        scope_value=scope_value,
        symbols=normalized_symbols,
        start_date=start_date,
        end_date=end_date,
        interval=interval_value,
        requested_session=session_value,
        adjustment=adjustment_value,
        source_schema_version=schema_value,
    )
    if state.calendar_coverage_gaps:
        # Calendar coverage is incomplete: the expected trading-day set is
        # not fully determined and no bar-level classification ran. Leave
        # summary null instead of claiming a coverage percentage.
        report.status = FAILED
        report.calendar.coverage_complete = False
        report.calendar.coverage_gaps = [
            {"start_date": gap_start.isoformat(), "end_date": gap_end.isoformat()}
            for gap_start, gap_end in state.calendar_coverage_gaps
        ]
        report.summary = None
        _finish_report(report, "market_bars_audit", settings)
        return report

    expected_dates = state.expected_trade_dates
    report.calendar.expected_trade_date_count = len(expected_dates)
    report.calendar.expected_trade_dates = [value.isoformat() for value in expected_dates]

    complete = state.complete_items
    present = state.present_items
    incomplete_keys = state.incomplete_items
    all_reasons = state.incomplete_reasons

    symbol_reports: list[AuditSymbolReport] = []
    total_complete = 0
    total_incomplete = 0
    total_missing = 0
    for code in normalized_symbols:
        complete_dates = sorted(value for (symbol, value) in complete if symbol == code)
        incomplete_dates = sorted(value for (symbol, value) in incomplete_keys if symbol == code)
        incomplete_reasons = {
            value.isoformat(): all_reasons.get((code, value), [])
            for value in incomplete_dates
        }
        missing_dates = sorted(value for value in expected_dates if (code, value) not in present)
        expected_count = len(expected_dates)
        coverage = _coverage_percentage(len(complete_dates), expected_count)
        symbol_reports.append(
            AuditSymbolReport(
                code=code,
                expected_trade_date_count=expected_count,
                complete_trade_date_count=len(complete_dates),
                incomplete_trade_date_count=len(incomplete_dates),
                missing_trade_date_count=len(missing_dates),
                coverage_percentage=coverage,
                first_complete_date=complete_dates[0].isoformat() if complete_dates else None,
                last_complete_date=complete_dates[-1].isoformat() if complete_dates else None,
                incomplete_dates=[value.isoformat() for value in incomplete_dates],
                incomplete_reasons=incomplete_reasons,
                missing_dates=[value.isoformat() for value in missing_dates],
                complete_dates=(
                    [value.isoformat() for value in complete_dates] if include_complete_dates else []
                ),
            )
        )
        total_complete += len(complete_dates)
        total_incomplete += len(incomplete_dates)
        total_missing += len(missing_dates)

    total_expected = len(normalized_symbols) * len(expected_dates)
    report.summary = AuditSummary(
        total_expected_items=total_expected,
        complete_item_count=total_complete,
        incomplete_item_count=total_incomplete,
        missing_item_count=total_missing,
        coverage_percentage=_coverage_percentage(total_complete, total_expected),
    )
    report.symbols = symbol_reports
    report.status = PASS if total_incomplete == 0 and total_missing == 0 else WARN
    _finish_report(report, "market_bars_audit", settings)
    return report


def _coverage_percentage(complete_count: int, expected_count: int) -> float:
    if expected_count <= 0:
        return 100.0
    return round(complete_count / expected_count * 100, 2)
