from __future__ import annotations

import re
from datetime import date, time
from zoneinfo import ZoneInfo

import pandas as pd

REQUIRED_SOURCE_COLUMNS = {
    "code",
    "time_key",
    "open",
    "high",
    "low",
    "close",
    "volume",
}

_OPTION_RE = re.compile(r"^(?P<market>[A-Z]+)\.(?P<root>[A-Z.]+)\d{6}[CP]\d+$")


def infer_asset_type(code: str) -> str:
    return "OPTION" if _OPTION_RE.match(code.upper()) else "EQUITY"


def infer_underlying(code: str) -> str | None:
    match = _OPTION_RE.match(code.upper())
    if not match:
        return None
    return f"{match.group('market')}.{match.group('root')}"


def _session_label(ts: pd.Timestamp) -> str:
    t = ts.timetz().replace(tzinfo=None)
    if t >= time(20, 0) or t < time(4, 0):
        return "OVERNIGHT"
    if time(4, 0) <= t < time(9, 30):
        return "PRE_MARKET"
    if time(9, 30) <= t < time(16, 0):
        return "REGULAR"
    if time(16, 0) <= t < time(20, 0):
        return "AFTER_HOURS"
    return "UNKNOWN"


def normalize_bars(
    frame: pd.DataFrame,
    requested_trade_date: date,
    interval: str,
    adjustment: str,
    source: str,
    source_schema_version: str,
    run_id: str,
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()

    missing = REQUIRED_SOURCE_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"Missing source columns: {sorted(missing)}")

    df = frame.copy()
    market_tz = ZoneInfo("America/New_York")
    parsed = pd.to_datetime(df["time_key"], errors="raise")
    if parsed.dt.tz is None:
        parsed = parsed.dt.tz_localize(market_tz, ambiguous="raise", nonexistent="raise")
    else:
        parsed = parsed.dt.tz_convert(market_tz)

    df["time_market"] = parsed
    df["time_utc"] = parsed.dt.tz_convert("UTC")
    df["market_calendar_date"] = parsed.dt.date
    df["requested_trade_date"] = requested_trade_date
    df["session"] = parsed.map(_session_label)
    df["interval"] = interval.lower()
    df["adjustment"] = adjustment.upper()
    df["asset_type"] = df["code"].map(infer_asset_type)
    df["underlying_code"] = df["code"].map(infer_underlying)
    df["source"] = source
    df["source_schema_version"] = source_schema_version
    df["ingestion_run_id"] = run_id
    df["ingested_at"] = pd.Timestamp.now(tz="UTC")

    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "turnover",
        "last_close",
        "pe_ratio",
        "turnover_rate",
        "change_rate",
    ]
    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    preferred = [
        "code",
        "name",
        "asset_type",
        "underlying_code",
        "interval",
        "adjustment",
        "time_market",
        "time_utc",
        "market_calendar_date",
        "requested_trade_date",
        "session",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "turnover",
        "last_close",
        "change_rate",
        "pe_ratio",
        "turnover_rate",
        "source",
        "source_schema_version",
        "ingestion_run_id",
        "ingested_at",
        "time_key",
    ]
    ordered = [c for c in preferred if c in df.columns]
    remaining = [c for c in df.columns if c not in ordered]
    return df[ordered + remaining].sort_values(["code", "time_utc"]).reset_index(drop=True)
