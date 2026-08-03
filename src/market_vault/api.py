from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd

from .backfill import collect_history_backfill, plan_history_backfill
from .config import load_settings
from .models import Settings
from .normalization.calendar import normalize_calendar_code, normalize_calendar_market
from .storage import Catalog


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
