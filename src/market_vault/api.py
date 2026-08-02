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
