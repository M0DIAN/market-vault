from __future__ import annotations

from typing import Any

import pandas as pd


TRADING_CALENDAR_COLUMNS = [
    "scope_type",
    "scope_value",
    "market",
    "reference_code",
    "trade_date",
    "trade_date_type",
    "requested_start_date",
    "requested_end_date",
    "captured_at",
    "source",
    "source_schema_version",
    "ingestion_run_id",
]


def normalize_calendar_market(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if not normalized:
        raise ValueError("market cannot be empty")
    return normalized


def normalize_calendar_code(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if not normalized:
        raise ValueError("code cannot be empty")
    return normalized


def _date_type_name(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    name = getattr(value, "name", None)
    text = str(name if name is not None else value).strip()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text or None


def normalize_trading_calendar(
    frame: pd.DataFrame,
    *,
    market: str | None,
    code: str | None,
    requested_start_date,
    requested_end_date,
    captured_at: pd.Timestamp,
    source: str,
    source_schema_version: str,
    run_id: str,
) -> pd.DataFrame:
    normalized_market = normalize_calendar_market(market)
    normalized_code = normalize_calendar_code(code)
    if bool(normalized_market) == bool(normalized_code):
        raise ValueError("Provide exactly one of market or code")
    if frame.empty:
        return pd.DataFrame(columns=TRADING_CALENDAR_COLUMNS)

    request_start = pd.to_datetime(requested_start_date, errors="raise").date()
    request_end = pd.to_datetime(requested_end_date, errors="raise").date()
    scope_type = "MARKET" if normalized_market else "CODE"
    scope_value = normalized_market or normalized_code
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        rows.append(
            {
                "scope_type": scope_type,
                "scope_value": scope_value,
                "market": normalized_market,
                "reference_code": normalized_code,
                "trade_date": row.get("trade_date", row.get("time")),
                "trade_date_type": _date_type_name(row.get("trade_date_type")),
                "requested_start_date": request_start,
                "requested_end_date": request_end,
                "captured_at": captured_at,
                "source": source,
                "source_schema_version": source_schema_version,
                "ingestion_run_id": run_id,
            }
        )

    df = pd.DataFrame(rows, columns=TRADING_CALENDAR_COLUMNS)
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date
    df["requested_start_date"] = pd.to_datetime(df["requested_start_date"], errors="coerce").dt.date
    df["requested_end_date"] = pd.to_datetime(df["requested_end_date"], errors="coerce").dt.date
    df["captured_at"] = pd.to_datetime(df["captured_at"], utc=True)
    df = df.drop_duplicates(
        subset=["scope_type", "scope_value", "trade_date", "source", "captured_at"],
        keep="last",
    )
    return df.sort_values(["scope_type", "scope_value", "trade_date"]).reset_index(drop=True)
