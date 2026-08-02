from __future__ import annotations

import time
from datetime import date
from typing import Any

import pandas as pd

from ..models import Settings
from .moomoo_history import MoomooDependencyError, MoomooRequestError


class MoomooOptionCollector:
    """Thin wrapper around moomoo option-chain and option-volatility endpoints."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._ctx: Any | None = None
        self._sdk: dict[str, Any] | None = None

    def _load_sdk(self) -> dict[str, Any]:
        if self._sdk is not None:
            return self._sdk
        try:
            from futu import (  # type: ignore
                IndexOptionType,
                OpenQuoteContext,
                OptionCondType,
                OptionType,
                RET_OK,
            )
        except ImportError as exc:
            raise MoomooDependencyError(
                "The moomoo Python SDK is unavailable. Run `pip install moomoo-api`, "
                "start OpenD, and try again."
            ) from exc
        try:
            from futu import OptionVolatilityTimePeriodType  # type: ignore
        except ImportError:
            OptionVolatilityTimePeriodType = None

        self._sdk = {
            "IndexOptionType": IndexOptionType,
            "OpenQuoteContext": OpenQuoteContext,
            "OptionCondType": OptionCondType,
            "OptionType": OptionType,
            "OptionVolatilityTimePeriodType": OptionVolatilityTimePeriodType,
            "RET_OK": RET_OK,
        }
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

    def _enum(self, group: str, value: str, aliases: dict[str, list[str]] | None = None) -> Any:
        sdk = self._load_sdk()
        enum_group = sdk[group]
        normalized = value.upper()
        names = (aliases or {}).get(normalized, [normalized])
        for name in names:
            if hasattr(enum_group, name):
                return getattr(enum_group, name)
        raise ValueError(f"Unsupported {group} value: {value}")

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
                {"ITM": ["WITHIN"], "ATM": ["NEAR", "ATM", "ALL"], "OTM": ["OUTSIDE"]},
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
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        self.connect()
        assert self._ctx is not None
        sdk = self._load_sdk()
        if not hasattr(self._ctx, "get_option_volatility"):
            raise MoomooRequestError(
                f"{option_code}: installed moomoo SDK does not expose get_option_volatility"
            )

        kwargs: dict[str, Any] = {"code": option_code}
        period_group = sdk.get("OptionVolatilityTimePeriodType")
        if period_group is not None:
            for name in ["MONTH", "THREE_MONTH", "HALF_YEAR", "YEAR"]:
                if hasattr(period_group, name):
                    kwargs["query_time_period"] = getattr(period_group, name)
                    break
        kwargs["hv_time_period"] = 30

        ret, data = self._ctx.get_option_volatility(**kwargs)
        if ret != sdk["RET_OK"]:
            raise MoomooRequestError(f"{option_code}: {data}")
        if not isinstance(data, pd.DataFrame):
            raise MoomooRequestError(f"{option_code}: SDK returned a non-DataFrame response")
        time.sleep(self.settings.request_pause_seconds)
        return data.copy()
