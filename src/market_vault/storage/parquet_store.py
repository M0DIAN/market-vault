from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path

import pandas as pd

from ..models import Settings


class ParquetStore:
    def __init__(self, settings: Settings):
        self.settings = settings

    @staticmethod
    def _batch_key(symbols: list[str], interval: str, session: str, adjustment: str) -> str:
        payload = "|".join(sorted(symbols) + [interval.lower(), session.upper(), adjustment.upper()])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def _path(
        self,
        layer: str,
        trade_date: date,
        interval: str,
        symbols: list[str],
        session: str,
        adjustment: str,
    ) -> Path:
        key = self._batch_key(symbols, interval, session, adjustment)
        return (
            self.settings.data_root
            / layer
            / f"source={self.settings.source}"
            / "dataset=market_bars"
            / f"interval={interval.lower()}"
            / f"requested_trade_date={trade_date.isoformat()}"
            / f"batch-{key}.parquet"
        )

    def write_raw(
        self,
        df: pd.DataFrame,
        trade_date: date,
        interval: str,
        symbols: list[str],
        session: str,
        adjustment: str,
    ) -> Path:
        path = self._path("raw", trade_date, interval, symbols, session, adjustment)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False, compression="zstd")
        return path

    def write_curated(
        self,
        df: pd.DataFrame,
        trade_date: date,
        interval: str,
        symbols: list[str],
        session: str,
        adjustment: str,
    ) -> Path:
        path = self._path("curated", trade_date, interval, symbols, session, adjustment)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False, compression="zstd")
        return path

    @staticmethod
    def _dataset_key(parts: list[str]) -> str:
        payload = "|".join(parts)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _safe_partition_value(value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
            raise ValueError(f"Unsafe partition value: {value}")
        if value in {".", ".."} or ".." in value:
            raise ValueError(f"Unsafe partition value: {value}")
        return value

    def write_option_chain_raw(
        self,
        df: pd.DataFrame,
        underlying_code: str,
        capture_date: date,
        run_id: str,
    ) -> Path:
        key = self._dataset_key([underlying_code, capture_date.isoformat(), run_id])
        path = (
            self.settings.data_root
            / "raw"
            / f"source={self.settings.source}"
            / "dataset=option_chain"
            / f"underlying_code={underlying_code}"
            / f"capture_date={capture_date.isoformat()}"
            / f"batch-{key}.parquet"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False, compression="zstd")
        return path

    def write_option_contracts_curated(
        self,
        df: pd.DataFrame,
        underlying_code: str,
        capture_date: date,
        run_id: str,
    ) -> Path:
        key = self._dataset_key([underlying_code, capture_date.isoformat(), run_id])
        path = (
            self.settings.data_root
            / "curated"
            / "option_contracts"
            / f"underlying_code={underlying_code}"
            / f"capture_date={capture_date.isoformat()}"
            / f"batch-{key}.parquet"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False, compression="zstd")
        return path

    def write_option_volatility_raw(
        self,
        df: pd.DataFrame,
        start_date: date,
        end_date: date,
        run_id: str,
    ) -> Path:
        key = self._dataset_key([start_date.isoformat(), end_date.isoformat(), run_id])
        path = (
            self.settings.data_root
            / "raw"
            / f"source={self.settings.source}"
            / "dataset=option_volatility_daily"
            / f"start_date={start_date.isoformat()}"
            / f"end_date={end_date.isoformat()}"
            / f"batch-{key}.parquet"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False, compression="zstd")
        return path

    def write_option_volatility_curated(
        self,
        df: pd.DataFrame,
        start_date: date,
        end_date: date,
        run_id: str,
    ) -> Path:
        key = self._dataset_key([start_date.isoformat(), end_date.isoformat(), run_id])
        path = (
            self.settings.data_root
            / "curated"
            / "option_volatility_daily"
            / f"start_date={start_date.isoformat()}"
            / f"end_date={end_date.isoformat()}"
            / f"batch-{key}.parquet"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False, compression="zstd")
        return path

    def write_trading_calendar_raw(
        self,
        df: pd.DataFrame,
        scope_type: str,
        scope_value: str,
        start_date: date,
        end_date: date,
        run_id: str,
    ) -> Path:
        safe_scope_type = self._safe_partition_value(scope_type.upper())
        safe_scope_value = self._safe_partition_value(scope_value)
        key = self._dataset_key([safe_scope_type, safe_scope_value, start_date.isoformat(), end_date.isoformat(), run_id])
        path = (
            self.settings.data_root
            / "raw"
            / f"source={self.settings.source}"
            / "dataset=trading_calendar"
            / f"scope_type={safe_scope_type}"
            / f"scope_value={safe_scope_value}"
            / f"start_date={start_date.isoformat()}"
            / f"end_date={end_date.isoformat()}"
            / f"batch-{key}.parquet"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False, compression="zstd")
        return path

    def write_trading_calendar_curated(
        self,
        df: pd.DataFrame,
        scope_type: str,
        scope_value: str,
        start_date: date,
        end_date: date,
        run_id: str,
    ) -> Path:
        safe_scope_type = self._safe_partition_value(scope_type.upper())
        safe_scope_value = self._safe_partition_value(scope_value)
        key = self._dataset_key([safe_scope_type, safe_scope_value, start_date.isoformat(), end_date.isoformat(), run_id])
        path = (
            self.settings.data_root
            / "curated"
            / "trading_calendar"
            / f"scope_type={safe_scope_type}"
            / f"scope_value={safe_scope_value}"
            / f"start_date={start_date.isoformat()}"
            / f"end_date={end_date.isoformat()}"
            / f"batch-{key}.parquet"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False, compression="zstd")
        return path
