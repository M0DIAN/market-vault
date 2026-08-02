from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from .bars import infer_underlying

OPTION_CONTRACT_COLUMNS = [
    "option_code",
    "option_name",
    "underlying_code",
    "option_type",
    "strike_price",
    "expiry_date",
    "contract_size",
    "lot_size",
    "exchange",
    "exercise_type",
    "suspension",
    "delisting",
    "captured_at",
    "source",
    "source_schema_version",
    "ingestion_run_id",
]

OPTION_VOLATILITY_COLUMNS = [
    "option_code",
    "trade_date",
    "implied_volatility",
    "historical_volatility",
    "volatility_premium",
    "average_implied_volatility",
    "volatility_status",
    "source",
    "ingestion_run_id",
]


def _first_present(row: pd.Series, names: list[str]) -> Any:
    for name in names:
        if name in row and pd.notna(row[name]):
            return row[name]
    return None


def _option_type(value: Any, option_code: str | None = None) -> str | None:
    if pd.isna(value):
        text = ""
    else:
        text = str(value).upper()
    if "CALL" in text or text in {"C", "1"}:
        return "CALL"
    if "PUT" in text or text in {"P", "2"}:
        return "PUT"
    if option_code:
        upper = option_code.upper()
        if len(upper) >= 8:
            marker = upper[-7]
            if marker == "C":
                return "CALL"
            if marker == "P":
                return "PUT"
    return None


def normalize_option_contracts(
    frame: pd.DataFrame,
    underlying_code: str,
    captured_at: pd.Timestamp,
    source: str,
    source_schema_version: str,
    run_id: str,
) -> pd.DataFrame:
    """Normalize moomoo option-chain static fields.

    moomoo's option-chain endpoint returns static contract fields. Fields that
    are not present in the SDK response are kept as null instead of inferred.
    """
    if frame.empty:
        return pd.DataFrame(columns=OPTION_CONTRACT_COLUMNS)

    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        option_code = _first_present(row, ["option_code", "code", "stock_code"])
        option_code = str(option_code) if option_code is not None else None
        row_underlying = _first_present(row, ["underlying_code", "owner_stock_code", "stock_owner", "underlying"])
        inferred_underlying = infer_underlying(option_code or "")
        expiry = _first_present(row, ["expiry_date", "strike_time", "expire_time", "expiration_date"])
        contract_size = _first_present(row, ["contract_size", "contract_multiplier"])
        rows.append(
            {
                "option_code": option_code,
                "option_name": _first_present(row, ["option_name", "name", "stock_name"]),
                "underlying_code": row_underlying or inferred_underlying or underlying_code,
                "option_type": _option_type(_first_present(row, ["option_type", "type"]), option_code),
                "strike_price": _first_present(row, ["strike_price", "strike"]),
                "expiry_date": expiry,
                "contract_size": contract_size,
                "lot_size": _first_present(row, ["lot_size"]),
                "exchange": _first_present(row, ["exchange", "market"]),
                "exercise_type": _first_present(row, ["exercise_type"]),
                "suspension": _first_present(row, ["suspension", "suspended"]),
                "delisting": _first_present(row, ["delisting", "delisted"]),
                "captured_at": captured_at,
                "source": source,
                "source_schema_version": source_schema_version,
                "ingestion_run_id": run_id,
            }
        )

    df = pd.DataFrame(rows, columns=OPTION_CONTRACT_COLUMNS)
    df["captured_at"] = pd.to_datetime(df["captured_at"], utc=True)
    df["expiry_date"] = pd.to_datetime(df["expiry_date"], errors="coerce").dt.date
    for column in ["strike_price", "contract_size", "lot_size"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    for column in ["suspension", "delisting"]:
        df[column] = df[column].map(_nullable_bool)
    df = df.drop_duplicates(subset=["option_code", "captured_at", "source"], keep="last")
    return df.sort_values(["option_code"]).reset_index(drop=True)


def _nullable_bool(value: Any) -> bool | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "suspended", "delisted"}:
        return True
    if text in {"false", "0", "no", "n", "normal"}:
        return False
    return None


def normalize_option_volatility(
    frame: pd.DataFrame,
    option_code: str,
    start_date: date,
    end_date: date,
    source: str,
    run_id: str,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=OPTION_VOLATILITY_COLUMNS)

    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        raw_date = _first_present(row, ["trade_date", "timestamp_str", "date"])
        if raw_date is None and "timestamp" in row and pd.notna(row["timestamp"]):
            raw_date = pd.to_datetime(row["timestamp"], unit="s", utc=True).date()
        rows.append(
            {
                "option_code": _first_present(row, ["option_code", "code"]) or option_code,
                "trade_date": raw_date,
                "implied_volatility": _first_present(row, ["implied_volatility", "impvol"]),
                "historical_volatility": _first_present(row, ["historical_volatility", "history_volatility", "hv"]),
                "volatility_premium": _first_present(row, ["volatility_premium"]),
                "average_implied_volatility": _first_present(row, ["average_implied_volatility", "average_impvol"]),
                "volatility_status": _first_present(row, ["volatility_status", "impvol_status"]),
                "source": source,
                "ingestion_run_id": run_id,
            }
        )

    df = pd.DataFrame(rows, columns=OPTION_VOLATILITY_COLUMNS)
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date
    for column in [
        "implied_volatility",
        "historical_volatility",
        "volatility_premium",
        "average_implied_volatility",
    ]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df[(df["trade_date"] >= start_date) & (df["trade_date"] <= end_date)]
    df = df.drop_duplicates(subset=["option_code", "trade_date", "source"], keep="last")
    return df.sort_values(["option_code", "trade_date"]).reset_index(drop=True)
