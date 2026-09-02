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

MARKET_TIME_ZONE = ZoneInfo("America/New_York")
MOOMOO_TIMESTAMP_SEMANTICS_V2_SCHEMA = "10.9-mv-ts2"
_MOOMOO_TS2_INTRADAY_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "60m": 60,
}
_DAILY_INTERVALS = {"1d", "day", "k_day"}

_OPTION_RE = re.compile(r"^(?P<market>[A-Z]+)\.(?P<root>[A-Z.]+)\d{6}[CP]\d+$")


def infer_asset_type(code: str) -> str:
    return "OPTION" if _OPTION_RE.match(code.upper()) else "EQUITY"


def infer_underlying(code: str) -> str | None:
    match = _OPTION_RE.match(code.upper())
    if not match:
        return None
    return f"{match.group('market')}.{match.group('root')}"


def parse_market_time_key(series: pd.Series) -> pd.Series:
    """Parse raw ``time_key`` values into America/New_York-aware timestamps.

    Centralizes the semantics normalize_bars has always used: naive values are
    localized to America/New_York (DST-ambiguous and nonexistent local times
    raise), already-aware values are converted to America/New_York. The
    resulting timestamps are the market-time instants of the bars.
    """
    parsed = pd.to_datetime(series, errors="raise")
    if parsed.dt.tz is None:
        parsed = parsed.dt.tz_localize(
            MARKET_TIME_ZONE, ambiguous="raise", nonexistent="raise"
        )
    else:
        parsed = parsed.dt.tz_convert(MARKET_TIME_ZONE)
    return parsed


def _market_timestamp(value: date, clock: str) -> pd.Timestamp:
    return pd.Timestamp(f"{value.isoformat()} {clock}:00", tz=MARKET_TIME_ZONE)


def _expected_moomoo_ts2_times(
    requested_trade_date: date,
    interval: str,
    requested_session: str,
) -> tuple[list[pd.Timestamp], list[pd.Timestamp]]:
    midnight = _market_timestamp(requested_trade_date, "00:00")
    regular_open = _market_timestamp(requested_trade_date, "09:30")
    regular_close = _market_timestamp(requested_trade_date, "16:00")
    minutes = _MOOMOO_TS2_INTRADAY_MINUTES[interval]

    if requested_session == "RTH":
        if interval == "60m":
            provider = [
                regular_open + pd.Timedelta(value, unit="h")
                for value in range(1, 7)
            ]
            provider.append(regular_close)
        else:
            provider = list(
                pd.date_range(
                    regular_open + pd.Timedelta(minutes, unit="m"),
                    regular_close,
                    freq=f"{minutes}min",
                )
            )
        canonical = [regular_open, *provider[:-1]]
        return provider, canonical

    if interval == "60m":
        # OpenD splits 60m ALL bars at 09:30 and 16:00 session boundaries.
        provider = [
            *[
                midnight + pd.Timedelta(value, unit="h")
                for value in range(0, 10)
            ],
            *[
                regular_open + pd.Timedelta(value, unit="h")
                for value in range(0, 7)
            ],
            *[
                _market_timestamp(requested_trade_date, "16:00")
                + pd.Timedelta(value, unit="h")
                for value in range(0, 4)
            ],
            *[
                _market_timestamp(requested_trade_date, "20:00")
                + pd.Timedelta(value, unit="h")
                for value in range(0, 4)
            ],
        ]
    else:
        provider = list(
            pd.date_range(
                midnight,
                midnight + pd.Timedelta(1, unit="D"),
                freq=f"{minutes}min",
                inclusive="left",
            )
        )
    return provider, list(provider)


def normalize_moomoo_intraday_timestamp_v2(
    parsed_time_key: pd.Series,
    codes: pd.Series,
    *,
    requested_trade_date: date,
    interval: str,
    requested_session: str,
) -> pd.Series:
    """Translate one verified Moomoo intraday response to interval starts.

    The accepted shapes are deliberately exact. Provider changes, partial
    sequences, and early-close geometry must be re-qualified instead of being
    inferred from a nominal interval length.
    """
    interval_value = interval.strip().lower()
    session_value = requested_session.strip().upper()
    if interval_value not in _MOOMOO_TS2_INTRADAY_MINUTES:
        raise ValueError(
            "Unsupported Moomoo Timestamp Semantics V2 intraday interval: "
            f"{interval!r}; supported: {', '.join(_MOOMOO_TS2_INTRADAY_MINUTES)}"
        )
    if session_value not in {"RTH", "ALL"}:
        raise ValueError(
            "Unsupported Moomoo Timestamp Semantics V2 requested_session: "
            f"{requested_session!r}; supported: RTH, ALL"
        )

    expected_provider, expected_canonical = _expected_moomoo_ts2_times(
        requested_trade_date,
        interval_value,
        session_value,
    )
    normalized_codes = codes.map(lambda value: str(value).strip().upper())
    result = parsed_time_key.copy()
    for code in sorted(normalized_codes.unique()):
        indexes = normalized_codes.index[normalized_codes == code]
        observed = parsed_time_key.loc[indexes]
        if observed.duplicated().any():
            raise ValueError(
                "Moomoo Timestamp Semantics V2 geometry has duplicate provider "
                f"endpoints for {code}"
            )
        if not observed.is_monotonic_increasing:
            raise ValueError(
                "Moomoo Timestamp Semantics V2 geometry has non-monotonic provider "
                f"timestamps for {code}"
            )
        if observed.tolist() != expected_provider:
            raise ValueError(
                "Moomoo Timestamp Semantics V2 geometry mismatch for "
                f"{code} {requested_trade_date.isoformat()} {interval_value} "
                f"{session_value}: expected {len(expected_provider)} verified "
                f"timestamps from {expected_provider[0]} through {expected_provider[-1]}, "
                f"received {len(observed)}"
            )
        result.loc[indexes] = pd.Series(expected_canonical, index=indexes)
    return result


def bar_available_at(market_time: pd.Timestamp, interval_seconds: int) -> pd.Timestamp:
    """Market availability instant of a bar whose interval starts at
    ``market_time``, expressed in UTC.

    Under the adopted interval-start ``time_key`` interpretation, ``market_time
    + interval`` is the exact earliest instant at which the complete OHLCV bar
    could be known **only when the bar spans its full nominal interval**. For
    bars that may be truncated at session boundaries or early closes it is a
    conservative leakage-safe not-before bound; exact bar-end times require
    authoritative per-date session schedules, which V0.3 does not have. This
    is the v0.4 ``market_available_at`` rule; it is a pure computation and is
    not part of any canonical materialization.
    """
    interval_delta = pd.Timedelta(int(interval_seconds), unit="s")
    return (market_time + interval_delta).tz_convert("UTC")


def market_session_label(ts: pd.Timestamp) -> str:
    """Session label for a market-time instant, based on local wall-clock
    session boundaries in the timestamp's own timezone.

    20:00-04:00 -> OVERNIGHT, 04:00-09:30 -> PRE_MARKET,
    09:30-16:00 -> REGULAR, 16:00-20:00 -> AFTER_HOURS.
    """
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
    requested_session: str,
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
    parsed = parse_market_time_key(df["time_key"])

    if source_schema_version == MOOMOO_TIMESTAMP_SEMANTICS_V2_SCHEMA:
        if source != "moomoo":
            raise ValueError(
                "Timestamp Semantics V2 requires source='moomoo', "
                f"got {source!r}"
            )
        interval_value = interval.strip().lower()
        if interval_value not in _DAILY_INTERVALS:
            parsed = normalize_moomoo_intraday_timestamp_v2(
                parsed,
                df["code"],
                requested_trade_date=requested_trade_date,
                interval=interval_value,
                requested_session=requested_session,
            )

    df["time_market"] = parsed
    df["time_utc"] = parsed.dt.tz_convert("UTC")
    df["market_calendar_date"] = parsed.dt.date
    df["requested_trade_date"] = requested_trade_date
    df["requested_session"] = requested_session.upper()
    df["session"] = parsed.map(market_session_label)
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
        "requested_session",
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
