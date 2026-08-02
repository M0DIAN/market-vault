from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from ..moomoo_sdk import load_moomoo_sdk
from ..models import Settings
from ..normalization.calendar import normalize_calendar_code, normalize_calendar_market
from .moomoo_history import MoomooRequestError


SUPPORTED_TRADE_DATE_MARKETS = [
    "US",
    "HK",
    "CN",
    "NT",
    "ST",
    "JP_FUTURE",
    "SG_FUTURE",
    "SG",
    "MY",
    "JP",
]


def resolve_trade_date_market(name: str, sdk: dict[str, Any]) -> Any:
    normalized = normalize_calendar_market(name)
    if normalized not in SUPPORTED_TRADE_DATE_MARKETS:
        supported = ", ".join(SUPPORTED_TRADE_DATE_MARKETS)
        raise ValueError(f"Unsupported trade date market: {name}. Supported values: {supported}")
    market_group = sdk.get("TradeDateMarket")
    if market_group is not None and hasattr(market_group, normalized):
        return getattr(market_group, normalized)
    supported = ", ".join(SUPPORTED_TRADE_DATE_MARKETS)
    raise ValueError(
        f"Installed moomoo SDK does not expose TradeDateMarket.{normalized}. Supported values: {supported}"
    )


class MoomooCalendarCollector:
    """Thin wrapper around OpenQuoteContext.request_trading_days."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._ctx: Any | None = None
        self._sdk: dict[str, Any] | None = None

    def _load_sdk(self) -> dict[str, Any]:
        if self._sdk is not None:
            return self._sdk
        self._sdk = load_moomoo_sdk()
        return self._sdk

    def connect(self) -> None:
        sdk = self._load_sdk()
        if self._ctx is None:
            self._ctx = sdk["OpenQuoteContext"](
                host=self.settings.opend_host,
                port=self.settings.opend_port,
            )

    def close(self) -> None:
        if self._ctx is not None:
            self._ctx.close()
            self._ctx = None

    def __enter__(self) -> "MoomooCalendarCollector":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def fetch_trading_calendar(
        self,
        start_date: date,
        end_date: date,
        market: str | None = None,
        code: str | None = None,
    ) -> pd.DataFrame:
        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")
        normalized_market = normalize_calendar_market(market)
        normalized_code = normalize_calendar_code(code)
        if bool(normalized_market) == bool(normalized_code):
            raise ValueError("Provide exactly one of market or code")

        self.connect()
        assert self._ctx is not None
        sdk = self._load_sdk()
        kwargs: dict[str, Any] = {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
        }
        label = normalized_code or normalized_market or "UNKNOWN"
        if normalized_market:
            kwargs["market"] = resolve_trade_date_market(normalized_market, sdk)
        else:
            kwargs["code"] = normalized_code

        ret, data = self._ctx.request_trading_days(**kwargs)
        if ret != sdk["RET_OK"]:
            raise MoomooRequestError(f"{label}: {data}")
        if isinstance(data, pd.DataFrame):
            return data.copy()
        if isinstance(data, list) and all(isinstance(item, dict) for item in data):
            return pd.DataFrame(data)
        raise MoomooRequestError(f"{label}: SDK returned unsupported trading calendar response type")
