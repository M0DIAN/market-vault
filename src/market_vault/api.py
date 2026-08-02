from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd

from .config import load_settings
from .models import Settings
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
        if bool(market) == bool(code):
            raise ValueError("Provide exactly one of market or code")
        if not self.catalog.refresh_trading_calendar_views():
            return pd.DataFrame()

        scope_type = "MARKET" if market else "CODE"
        scope_value = market.upper() if market else code
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
