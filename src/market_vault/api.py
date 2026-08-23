from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import ceil
from pathlib import Path

import pandas as pd

from .audit import AuditReport, InventoryReport, run_audit, run_inventory
from .backfill import collect_history_backfill, plan_history_backfill
from .config import load_settings
from .intraday_audit import IntradayAuditReport, run_intraday_audit
from .models import Settings
from .normalization.calendar import normalize_calendar_code, normalize_calendar_market
from .purge import PurgePlan, PurgeResult, purge_execute, purge_plan
from .service import collect_trading_calendar
from .storage import Catalog


DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 1000


@dataclass(frozen=True)
class QueryPage:
    """One bounded page returned by a local MarketVault query."""

    data: pd.DataFrame
    page: int
    page_size: int
    total_rows: int

    @property
    def total_pages(self) -> int:
        return max(1, ceil(self.total_rows / self.page_size))

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages


def _validated_page(page: int, page_size: int) -> tuple[int, int, int]:
    if page < 1:
        raise ValueError("page must be at least 1")
    if page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
    return page, page_size, (page - 1) * page_size


class MarketVault:
    def __init__(self, settings: Settings | str | Path = "config/settings.yaml"):
        self.settings = settings if isinstance(settings, Settings) else load_settings(settings)
        self.catalog = Catalog(self.settings)

    def load_bars(
        self,
        code: str,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        trade_date: str | date | None = None,
        interval: str = "1m",
        session: str | None = None,
        adjustment: str = "NONE",
    ) -> pd.DataFrame:
        if not self.catalog.refresh_market_bars_view():
            return pd.DataFrame()

        clauses = ["code = ?", "interval = ?", "adjustment = ?"]
        params: list[object] = [code, interval.lower(), adjustment.upper()]
        if start is not None:
            clauses.append("time_market >= ?")
            params.append(start)
        if end is not None:
            clauses.append("time_market <= ?")
            params.append(end)
        if trade_date is not None:
            clauses.append("requested_trade_date = ?")
            params.append(trade_date)
        if session is not None:
            clauses.append("session = ?")
            params.append(session.upper())

        sql = f"""
            SELECT *
            FROM market_bars
            WHERE {' AND '.join(clauses)}
            ORDER BY time_utc
        """
        with self.catalog.connect() as con:
            return con.execute(sql, params).fetchdf()

    def load_bars_page(
        self,
        *,
        code: str,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        start_date: str | date | None = None,
        end_date: str | date | None = None,
        interval: str = "1m",
        requested_session: str | None = None,
        bar_session: str | None = None,
        adjustment: str = "NONE",
    ) -> QueryPage:
        """Return one bounded page from the local latest market-bar view.

        This method never connects to OpenD. Date filters apply to the
        collection request's trade date; ``bar_session`` applies to the
        normalized per-row session label.
        """
        page, page_size, offset = _validated_page(page, page_size)
        normalized_code = code.strip().upper()
        if not normalized_code:
            raise ValueError("code cannot be blank")
        if start_date is not None and end_date is not None:
            if pd.Timestamp(start_date).date() > pd.Timestamp(end_date).date():
                raise ValueError("start_date must be on or before end_date")
        if not self.catalog.refresh_market_bars_view():
            return QueryPage(pd.DataFrame(), page, page_size, 0)

        clauses = ["code = ?", "interval = ?", "adjustment = ?"]
        params: list[object] = [normalized_code, interval.strip().lower(), adjustment.strip().upper()]
        if start_date is not None:
            clauses.append("requested_trade_date >= ?")
            params.append(start_date)
        if end_date is not None:
            clauses.append("requested_trade_date <= ?")
            params.append(end_date)
        if requested_session:
            clauses.append("requested_session = ?")
            params.append(requested_session.strip().upper())
        if bar_session:
            clauses.append("session = ?")
            params.append(bar_session.strip().upper())
        where = " AND ".join(clauses)
        with self.catalog.connect() as con:
            total_rows = int(
                con.execute(f"SELECT COUNT(*) FROM market_bars WHERE {where}", params).fetchone()[0]
            )
            data = con.execute(
                f"""
                SELECT *
                FROM market_bars
                WHERE {where}
                ORDER BY time_utc, ingestion_run_id
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, offset],
            ).fetchdf()
        return QueryPage(data, page, page_size, total_rows)

    def load_trading_calendar(
        self,
        market: str | None = None,
        code: str | None = None,
        start_date: str | date | None = None,
        end_date: str | date | None = None,
    ) -> pd.DataFrame:
        normalized_market = normalize_calendar_market(market)
        normalized_code = normalize_calendar_code(code)
        if bool(normalized_market) == bool(normalized_code):
            raise ValueError("Provide exactly one of market or code")
        if not self.catalog.refresh_trading_calendar_views():
            return pd.DataFrame()

        scope_type = "MARKET" if normalized_market else "CODE"
        scope_value = normalized_market or normalized_code
        clauses = ["scope_type = ?", "scope_value = ?"]
        params: list[object] = [scope_type, scope_value]
        if start_date is not None:
            clauses.append("trade_date >= ?")
            params.append(start_date)
        if end_date is not None:
            clauses.append("trade_date <= ?")
            params.append(end_date)

        sql = f"""
            SELECT *
            FROM trading_calendar_latest
            WHERE {' AND '.join(clauses)}
            ORDER BY trade_date
        """
        with self.catalog.connect() as con:
            return con.execute(sql, params).fetchdf()

    def load_trading_calendar_page(
        self,
        *,
        market: str | None = None,
        code: str | None = None,
        start_date: str | date | None = None,
        end_date: str | date | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> QueryPage:
        """Return one bounded page from the local calendar latest view."""
        page, page_size, offset = _validated_page(page, page_size)
        normalized_market = normalize_calendar_market(market)
        normalized_code = normalize_calendar_code(code)
        if bool(normalized_market) == bool(normalized_code):
            raise ValueError("Provide exactly one of market or code")
        if start_date is not None and end_date is not None:
            if pd.Timestamp(start_date).date() > pd.Timestamp(end_date).date():
                raise ValueError("start_date must be on or before end_date")
        if not self.catalog.refresh_trading_calendar_views():
            return QueryPage(pd.DataFrame(), page, page_size, 0)

        scope_type = "MARKET" if normalized_market else "CODE"
        scope_value = normalized_market or normalized_code
        clauses = ["scope_type = ?", "scope_value = ?"]
        params: list[object] = [scope_type, scope_value]
        if start_date is not None:
            clauses.append("trade_date >= ?")
            params.append(start_date)
        if end_date is not None:
            clauses.append("trade_date <= ?")
            params.append(end_date)
        where = " AND ".join(clauses)
        with self.catalog.connect() as con:
            total_rows = int(
                con.execute(
                    f"SELECT COUNT(*) FROM trading_calendar_latest WHERE {where}", params
                ).fetchone()[0]
            )
            data = con.execute(
                f"""
                SELECT *
                FROM trading_calendar_latest
                WHERE {where}
                ORDER BY trade_date, ingestion_run_id
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, offset],
            ).fetchdf()
        return QueryPage(data, page, page_size, total_rows)

    def load_run_history_page(
        self,
        *,
        page: int = 1,
        page_size: int = 100,
        status: str | None = None,
        dataset: str | None = None,
    ) -> QueryPage:
        """Return a bounded, read-only projection of collection run status."""
        page, page_size, offset = _validated_page(page, page_size)
        if not self.settings.catalog_path.exists():
            return QueryPage(pd.DataFrame(), page, page_size, 0)
        clauses: list[str] = []
        params: list[object] = []
        if status:
            clauses.append("status = ?")
            params.append(status.strip().upper())
        if dataset:
            clauses.append("dataset = ?")
            params.append(dataset.strip())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        runs_sql = """
            SELECT
                'COLLECTION' AS run_kind,
                'market_bars' AS dataset,
                run_id,
                started_at,
                finished_at,
                status,
                row_count,
                CAST(requested_symbols AS VARCHAR) AS requested_items,
                CAST(failed_symbols AS VARCHAR) AS errors
            FROM ingestion_runs
            UNION ALL
            SELECT
                'DATASET' AS run_kind,
                dataset,
                run_id,
                started_at,
                finished_at,
                status,
                row_count,
                CAST(requested_items AS VARCHAR) AS requested_items,
                CAST(failed_items AS VARCHAR) AS errors
            FROM dataset_ingestion_runs
        """
        with self.catalog.connect() as con:
            table_names = {
                row[0]
                for row in con.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
                ).fetchall()
            }
            if not {"ingestion_runs", "dataset_ingestion_runs"}.issubset(table_names):
                return QueryPage(pd.DataFrame(), page, page_size, 0)
            total_rows = int(
                con.execute(f"SELECT COUNT(*) FROM ({runs_sql}) runs {where}", params).fetchone()[0]
            )
            data = con.execute(
                f"""
                SELECT *
                FROM ({runs_sql}) runs
                {where}
                ORDER BY started_at DESC NULLS LAST, run_id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, offset],
            ).fetchdf()
        return QueryPage(data, page, page_size, total_rows)

    def collect_trading_calendar(
        self,
        *,
        start_date: date,
        end_date: date,
        market: str | None = None,
        code: str | None = None,
    ):
        """Explicitly collect a trading-calendar snapshot through OpenD."""
        return collect_trading_calendar(
            self.settings,
            start_date=start_date,
            end_date=end_date,
            market=market,
            code=code,
        )

    def purge_plan(
        self,
        *,
        source: str,
        symbols: list[str],
        start_date: date,
        end_date: date,
        interval: str,
        requested_session: str,
        adjustment: str,
        source_schema_version: str,
    ) -> PurgePlan:
        """Seal a local Safe Purge plan; no OpenD or market-data mutation."""
        return purge_plan(
            self.settings,
            source=source,
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
            requested_session=requested_session,
            adjustment=adjustment,
            source_schema_version=source_schema_version,
        )

    def purge_execute(self, *, plan_id: str, confirmation: str) -> PurgeResult:
        """Execute one exact sealed plan by moving files to quarantine."""
        return purge_execute(
            self.settings,
            plan_id=plan_id,
            confirmation=confirmation,
        )

    def plan_backfill(
        self,
        *,
        symbols: list[str],
        end_date: date,
        calendar_market: str | None = None,
        calendar_code: str | None = None,
        start_date: date | None = None,
        interval: str = "1m",
        session: str | None = None,
        adjustment: str | None = None,
        force: bool = False,
        incremental: bool = False,
        bootstrap_start_date: date | None = None,
        today: date | None = None,
    ):
        if session is None:
            session = self.settings.default_session
        if adjustment is None:
            adjustment = self.settings.default_adjustment
        return plan_history_backfill(
            self.settings,
            symbols=symbols,
            end_date=end_date,
            calendar_market=calendar_market,
            calendar_code=calendar_code,
            start_date=start_date,
            interval=interval,
            session=session,
            adjustment=adjustment,
            force=force,
            incremental=incremental,
            bootstrap_start_date=bootstrap_start_date,
            today=today,
        )

    def backfill(
        self,
        *,
        symbols: list[str],
        end_date: date,
        calendar_market: str | None = None,
        calendar_code: str | None = None,
        start_date: date | None = None,
        interval: str = "1m",
        session: str | None = None,
        adjustment: str | None = None,
        force: bool = False,
        incremental: bool = False,
        bootstrap_start_date: date | None = None,
        max_retries: int = 2,
        retry_backoff_seconds: float = 2.0,
        today: date | None = None,
    ):
        if session is None:
            session = self.settings.default_session
        if adjustment is None:
            adjustment = self.settings.default_adjustment
        return collect_history_backfill(
            self.settings,
            symbols=symbols,
            end_date=end_date,
            calendar_market=calendar_market,
            calendar_code=calendar_code,
            start_date=start_date,
            interval=interval,
            session=session,
            adjustment=adjustment,
            force=force,
            incremental=incremental,
            bootstrap_start_date=bootstrap_start_date,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            today=today,
        )

    def inventory_market_bars(
        self,
        *,
        symbols: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        interval: str | None = None,
        session: str | None = None,
        adjustment: str | None = None,
        source_schema_version: str | None = None,
        include_files: bool = False,
        today: date | None = None,
    ) -> InventoryReport:
        """Summarize local market-bar storage, snapshots, and coverage.

        Pure local: no OpenD connection and no data mutation. ``symbols``
        defaults to all local symbols; ``session``/``adjustment`` default to
        no filter (unlike the audit command).
        """
        return run_inventory(
            self.settings,
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
            requested_session=session,
            adjustment=adjustment,
            source_schema_version=source_schema_version,
            include_files=include_files,
        )

    def audit_market_bars(
        self,
        *,
        symbols: list[str],
        start_date: date,
        end_date: date,
        calendar_market: str | None = None,
        calendar_code: str | None = None,
        interval: str = "1m",
        session: str | None = None,
        adjustment: str | None = None,
        source_schema_version: str | None = None,
        include_complete_dates: bool = False,
        today: date | None = None,
    ) -> AuditReport:
        """Audit trading-day coverage against the local trading calendar.

        Pure local: no OpenD connection and no data mutation. ``session`` and
        ``adjustment`` fall back to settings defaults when omitted.
        """
        return run_audit(
            self.settings,
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            calendar_market=calendar_market,
            calendar_code=calendar_code,
            interval=interval,
            requested_session=session,
            adjustment=adjustment,
            source_schema_version=source_schema_version,
            include_complete_dates=include_complete_dates,
            today=today,
        )

    def audit_intraday_market_bars(
        self,
        *,
        symbols: list[str],
        start_date: date,
        end_date: date,
        calendar_market: str | None = None,
        calendar_code: str | None = None,
        interval: str = "1m",
        session: str | None = None,
        adjustment: str | None = None,
        source_schema_version: str | None = None,
        include_pass_checks: bool = False,
        max_gap_details: int = 100,
        today: date | None = None,
    ) -> IntradayAuditReport:
        """Audit the intraday structure of the latest complete snapshot per
        (symbol, trade date).

        Pure local: no OpenD connection, no data mutation, no automatic
        repair. ``session`` and ``adjustment`` fall back to settings defaults
        when omitted.
        """
        return run_intraday_audit(
            self.settings,
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            calendar_market=calendar_market,
            calendar_code=calendar_code,
            interval=interval,
            requested_session=session,
            adjustment=adjustment,
            source_schema_version=source_schema_version,
            include_pass_checks=include_pass_checks,
            max_gap_details=max_gap_details,
            today=today,
        )
