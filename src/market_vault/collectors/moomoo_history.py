from __future__ import annotations

import time
from datetime import date
from typing import Any

import pandas as pd

from ..models import Settings


class MoomooDependencyError(RuntimeError):
    pass


class MoomooRequestError(RuntimeError):
    pass


class MoomooHistoryCollector:
    """Thin, pageable wrapper around OpenQuoteContext.request_history_kline."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._ctx: Any | None = None
        self._sdk: dict[str, Any] | None = None

    def _load_sdk(self) -> dict[str, Any]:
        if self._sdk is not None:
            return self._sdk
        try:
            from futu import (  # type: ignore
                AuType,
                KLType,
                KL_FIELD,
                OpenQuoteContext,
                RET_OK,
                Session,
            )
        except ImportError as exc:
            raise MoomooDependencyError(
                "The moomoo Python SDK is unavailable. Run `pip install moomoo-api`, "
                "start OpenD, and try again."
            ) from exc

        self._sdk = {
            "AuType": AuType,
            "KLType": KLType,
            "KL_FIELD": KL_FIELD,
            "OpenQuoteContext": OpenQuoteContext,
            "RET_OK": RET_OK,
            "Session": Session,
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

    def __enter__(self) -> "MoomooHistoryCollector":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _enum(self, group: str, value: str) -> Any:
        sdk = self._load_sdk()
        enum_group = sdk[group]
        normalized = value.upper()
        aliases = {
            "1M": "K_1M",
            "5M": "K_5M",
            "15M": "K_15M",
            "30M": "K_30M",
            "60M": "K_60M",
            "DAY": "K_DAY",
            "1D": "K_DAY",
            "NONE": "NONE",
            "QFQ": "QFQ",
            "HFQ": "HFQ",
        }
        name = aliases.get(normalized, normalized)
        try:
            return getattr(enum_group, name)
        except AttributeError as exc:
            raise ValueError(f"Unsupported {group} value: {value}") from exc

    def fetch_history(
        self,
        code: str,
        trade_date: date,
        interval: str = "1m",
        adjustment: str = "NONE",
        session: str = "ALL",
    ) -> pd.DataFrame:
        self.connect()
        assert self._ctx is not None
        sdk = self._load_sdk()

        date_text = trade_date.isoformat()
        page_req_key = None
        pages: list[pd.DataFrame] = []

        while True:
            kwargs: dict[str, Any] = {
                "code": code,
                "start": date_text,
                "end": date_text,
                "ktype": self._enum("KLType", interval),
                "autype": self._enum("AuType", adjustment),
                "fields": [sdk["KL_FIELD"].ALL],
                "max_count": self.settings.max_count,
                "page_req_key": page_req_key,
            }

            is_intraday = interval.lower() not in {"1d", "day", "k_day"}
            if is_intraday:
                try:
                    kwargs["session"] = getattr(sdk["Session"], session.upper())
                except AttributeError as exc:
                    raise ValueError(f"Unsupported session: {session}") from exc

            try:
                ret, data, next_key = self._ctx.request_history_kline(**kwargs)
            except TypeError:
                # Compatibility path for older SDKs that do not expose `session`.
                kwargs.pop("session", None)
                kwargs["extended_time"] = session.upper() != "RTH"
                ret, data, next_key = self._ctx.request_history_kline(**kwargs)

            if ret != sdk["RET_OK"]:
                raise MoomooRequestError(f"{code}: {data}")
            if not isinstance(data, pd.DataFrame):
                raise MoomooRequestError(f"{code}: SDK returned a non-DataFrame response")
            if not data.empty:
                pages.append(data.copy())

            page_req_key = next_key
            if page_req_key is None:
                break
            time.sleep(self.settings.request_pause_seconds)

        if not pages:
            return pd.DataFrame()
        return pd.concat(pages, ignore_index=True)
