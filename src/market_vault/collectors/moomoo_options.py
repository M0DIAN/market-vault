from __future__ import annotations

import time
from datetime import date
from typing import Any

import pandas as pd

from ..moomoo_sdk import load_moomoo_sdk
from ..models import Settings
from .moomoo_history import MoomooDependencyError, MoomooRequestError


OPTION_VOLATILITY_PERIOD_VALUES = {
    "WEEK": 1,
    "MONTH": 2,
    "QUARTER": 3,
    "HALF_YEAR": 4,
    "YEAR": 5,
}


def select_option_volatility_period(start_date: date, as_of_date: date) -> str:
    if start_date > as_of_date:
        raise ValueError("start_date cannot be after the option volatility as_of_date")
    days = (as_of_date - start_date).days
    if days <= 7:
        return "WEEK"
    if days <= 31:
        return "MONTH"
    if days <= 92:
        return "QUARTER"
    if days <= 183:
        return "HALF_YEAR"
    if days <= 366:
        return "YEAR"
    raise ValueError("Option volatility requests cannot exceed the official YEAR range")


def resolve_option_volatility_period(name: str, sdk: dict[str, Any]) -> Any:
    normalized = name.upper()
    if normalized not in OPTION_VOLATILITY_PERIOD_VALUES:
        supported = ", ".join(OPTION_VOLATILITY_PERIOD_VALUES)
        raise ValueError(f"Unsupported option volatility period: {name}. Supported values: {supported}")
    period_group = sdk.get("OptionVolatilityTimePeriodType")
    if period_group is not None and hasattr(period_group, normalized):
        return getattr(period_group, normalized)
    return OPTION_VOLATILITY_PERIOD_VALUES[normalized]


class MoomooOptionCollector:
    """Thin wrapper around moomoo option-chain and option-volatility endpoints."""

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

    def __enter__(self) -> "MoomooOptionCollector":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _enum(self, group: str, value: str, aliases: dict[str, str] | None = None) -> Any:
        sdk = self._load_sdk()
        enum_group = sdk[group]
        normalized = value.upper()
        name = (aliases or {}).get(normalized, normalized)
        if hasattr(enum_group, name):
            return getattr(enum_group, name)
        raise ValueError(f"Unsupported {group} value: {value}; missing SDK enum {name}")

    def fetch_option_chain(
        self,
        underlying: str,
        start_date: date,
        end_date: date,
        option_type: str = "ALL",
        option_cond_type: str = "ALL",
    ) -> pd.DataFrame:
        self.connect()
        assert self._ctx is not None
        sdk = self._load_sdk()

        kwargs: dict[str, Any] = {
            "code": underlying,
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "option_type": self._enum("OptionType", option_type),
            "option_cond_type": self._enum(
                "OptionCondType",
                option_cond_type,
                {"ALL": "ALL", "ITM": "WITHIN", "OTM": "OUTSIDE"},
            ),
        }
        if "IndexOptionType" in sdk and hasattr(sdk["IndexOptionType"], "NORMAL"):
            kwargs["index_option_type"] = sdk["IndexOptionType"].NORMAL

        try:
            ret, data = self._ctx.get_option_chain(**kwargs)
        except TypeError:
            kwargs.pop("index_option_type", None)
            ret, data = self._ctx.get_option_chain(**kwargs)

        if ret != sdk["RET_OK"]:
            raise MoomooRequestError(f"{underlying}: {data}")
        if not isinstance(data, pd.DataFrame):
            raise MoomooRequestError(f"{underlying}: SDK returned a non-DataFrame response")
        return data.copy()

    def fetch_option_volatility(
        self,
        option_code: str,
        query_time_period: str,
        hv_time_period: int = 30,
    ) -> pd.DataFrame:
        self.connect()
        assert self._ctx is not None
        sdk = self._load_sdk()
        if not hasattr(self._ctx, "get_option_volatility"):
            raise MoomooRequestError(
                f"{option_code}: installed moomoo SDK does not expose get_option_volatility"
            )

        period = resolve_option_volatility_period(query_time_period, sdk)

        ret, data = self._ctx.get_option_volatility(
            option_code,
            query_time_period=period,
            hv_time_period=hv_time_period,
        )
        if ret != sdk["RET_OK"]:
            raise MoomooRequestError(f"{option_code}: {data}")
        if not isinstance(data, pd.DataFrame):
            raise MoomooRequestError(f"{option_code}: SDK returned a non-DataFrame response")
        time.sleep(self.settings.request_pause_seconds)
        return data.copy()
