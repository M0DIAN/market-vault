from __future__ import annotations

import inspect
import time
from datetime import date
from typing import Any

import pandas as pd

from ..moomoo_sdk import MoomooDependencyError, load_moomoo_sdk
from ..models import Settings


class MoomooRequestError(RuntimeError):
    pass


class MoomooHistoryCollector:
    """Thin, pageable wrapper around OpenQuoteContext.request_history_kline."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._ctx: Any | None = None
        self._sdk: dict[str, Any] | None = None
        self.last_request_evidence: dict[str, Any] | None = None

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
        self.last_request_evidence = None
        self.connect()
        assert self._ctx is not None
        sdk = self._load_sdk()
        session_kwargs, evidence = self._session_request(interval, session)

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

            kwargs.update(session_kwargs)
            # Execution/unpacking TypeError is a real failure, never evidence
            # that retrying with a narrower trading session is safe.
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

        frame = pd.concat(pages, ignore_index=True) if pages else pd.DataFrame()
        self.last_request_evidence = {"symbol": code, "interval": interval, **evidence}
        return frame

    def _session_request(self, interval: str, session: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """Choose one documented request meaning before the first history page."""
        sdk = self._load_sdk()
        requested = session.upper()
        kwargs: dict[str, Any] = {}
        native: bool | None = None
        legacy: bool | None = None
        mode = "DAILY_DEFAULT"
        effective = "SDK_DAILY_DEFAULT"
        if interval.lower() not in {"1d", "day", "k_day"}:
            if requested not in {"RTH", "ETH", "ALL"}:
                raise ValueError(f"Unsupported session: {session}")
            assert self._ctx is not None
            try:
                parameters = inspect.signature(self._ctx.request_history_kline).parameters
            except (TypeError, ValueError) as exc:
                raise MoomooDependencyError("Cannot determine history session keyword capabilities") from exc

            def supports(name: str) -> bool:
                parameter = parameters.get(name)
                return parameter is not None and parameter.kind in {
                    inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY,
                }

            native, legacy = supports("session"), supports("extended_time")
            if native:
                value = getattr(sdk.get("Session"), requested, None)
                if value is None:
                    raise MoomooDependencyError(f"SDK session parameter requires Session.{requested}")
                kwargs["session"] = value
                mode = "SESSION"
            elif legacy and requested in {"RTH", "ETH"}:
                kwargs["extended_time"] = requested == "ETH"
                mode = "EXTENDED_TIME"
            elif legacy:
                raise MoomooDependencyError(
                    "ALL requires native session support; extended_time only expresses RTH/ETH"
                )
            else:
                # A **kwargs parameter alone is not an explicit capability.
                raise MoomooDependencyError(
                    "History method does not expose explicit session or extended_time keyword support"
                )
            effective = requested
        return kwargs, {
            "requested_session": requested,
            "effective_request_session": effective,
            "request_mode": mode,
            "session_keyword_supported": native,
            "extended_time_keyword_supported": legacy,
            "sdk_module": sdk.get("module_name"),
            "sdk_version": sdk.get("version"),
            "validation_scope": "REQUEST_PARAMETER_CAPABILITY_ONLY",
            "response_session_coverage_verified": False,
        }
