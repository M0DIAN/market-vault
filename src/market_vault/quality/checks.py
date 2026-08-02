from __future__ import annotations

from datetime import date

import pandas as pd

from ..models import QualityResult
from ..normalization.bars import infer_underlying


def _result(name: str, passed: bool, expected: str, actual: str, details: str = "") -> QualityResult:
    return QualityResult(
        check_name=name,
        result="PASS" if passed else "FAIL",
        expected_value=expected,
        actual_value=actual,
        details=details or None,
    )


def run_bar_quality_checks(df: pd.DataFrame) -> list[QualityResult]:
    if df.empty:
        return [QualityResult("non_empty", "FAIL", "> 0 rows", "0 rows", "No bars were returned")]

    checks: list[QualityResult] = []
    required = {"code", "time_utc", "open", "high", "low", "close", "volume"}
    missing = sorted(required - set(df.columns))
    checks.append(_result("required_columns", not missing, "all present", str(missing or "all present")))
    if missing:
        return checks

    duplicate_count = int(df.duplicated(subset=["code", "interval", "adjustment", "time_utc"]).sum())
    checks.append(_result("duplicate_bars", duplicate_count == 0, "0", str(duplicate_count)))

    invalid_ohlc = (
        (df["high"] < df[["open", "close", "low"]].max(axis=1))
        | (df["low"] > df[["open", "close", "high"]].min(axis=1))
    )
    invalid_ohlc_count = int(invalid_ohlc.fillna(True).sum())
    checks.append(_result("ohlc_consistency", invalid_ohlc_count == 0, "0 invalid rows", str(invalid_ohlc_count)))

    negative_volume_count = int((df["volume"].fillna(-1) < 0).sum())
    checks.append(_result("non_negative_volume", negative_volume_count == 0, "0 invalid rows", str(negative_volume_count)))

    monotonic_failures = 0
    for _, group in df.groupby("code", sort=False):
        if not group["time_utc"].is_monotonic_increasing:
            monotonic_failures += 1
    checks.append(_result("time_monotonic_by_code", monotonic_failures == 0, "0 symbols", str(monotonic_failures)))

    null_price_count = int(df[["open", "high", "low", "close"]].isna().any(axis=1).sum())
    checks.append(_result("non_null_prices", null_price_count == 0, "0 invalid rows", str(null_price_count)))

    return checks


def run_option_contract_quality_checks(df: pd.DataFrame) -> list[QualityResult]:
    if df.empty:
        return [QualityResult("non_empty", "FAIL", "> 0 rows", "0 rows", "No option contracts were returned")]

    checks: list[QualityResult] = []
    required = {"option_code", "underlying_code", "option_type", "strike_price", "expiry_date"}
    missing = sorted(required - set(df.columns))
    checks.append(_result("required_columns", not missing, "all present", str(missing or "all present")))
    if missing:
        return checks

    null_option_code = int(df["option_code"].isna().sum() + (df["option_code"].astype("string").str.len() == 0).sum())
    checks.append(_result("option_code_non_empty", null_option_code == 0, "0 invalid rows", str(null_option_code)))

    null_underlying = int(
        df["underlying_code"].isna().sum() + (df["underlying_code"].astype("string").str.len() == 0).sum()
    )
    checks.append(_result("underlying_code_non_empty", null_underlying == 0, "0 invalid rows", str(null_underlying)))

    invalid_type = int((~df["option_type"].isin(["CALL", "PUT"])).sum())
    checks.append(_result("option_type_call_or_put", invalid_type == 0, "CALL or PUT", str(invalid_type)))

    invalid_strike = int((pd.to_numeric(df["strike_price"], errors="coerce") <= 0).fillna(True).sum())
    checks.append(_result("strike_price_positive", invalid_strike == 0, "> 0", str(invalid_strike)))

    invalid_expiry = int(pd.to_datetime(df["expiry_date"], errors="coerce").isna().sum())
    checks.append(_result("expiry_date_valid", invalid_expiry == 0, "valid dates", str(invalid_expiry)))

    duplicate_count = int(df.duplicated(subset=["option_code", "captured_at", "source"]).sum())
    checks.append(_result("duplicate_option_contracts", duplicate_count == 0, "0", str(duplicate_count)))

    relationship_warnings = 0
    for _, row in df.iterrows():
        inferred = infer_underlying(str(row["option_code"]))
        if inferred and inferred != row["underlying_code"]:
            relationship_warnings += 1
    checks.append(
        QualityResult(
            "option_underlying_relationship",
            "WARN" if relationship_warnings else "PASS",
            "0 suspicious rows",
            str(relationship_warnings),
            "option_code implies a different underlying_code" if relationship_warnings else None,
        )
    )
    return checks


def run_option_volatility_quality_checks(
    df: pd.DataFrame,
    start_date: date,
    end_date: date,
    returned_min_date: date | None = None,
    returned_max_date: date | None = None,
    range_complete: bool = True,
    coverage_by_code: dict | None = None,
) -> list[QualityResult]:
    if df.empty:
        checks = [
            QualityResult("non_empty", "FAIL", "> 0 rows", "0 rows", "No option volatility rows were returned")
        ]
        if not range_complete:
            checks.append(
                QualityResult(
                    "requested_range_complete",
                    "WARN",
                    f"requested_start_date={start_date.isoformat()}, requested_end_date={end_date.isoformat()}",
                    (
                        f"returned_min_date={returned_min_date.isoformat() if returned_min_date else None}, "
                        f"returned_max_date={returned_max_date.isoformat() if returned_max_date else None}"
                    ),
                    "The API response did not cover the full requested date window.",
                )
            )
        return checks

    checks: list[QualityResult] = []
    required = {"option_code", "trade_date", "source"}
    missing = sorted(required - set(df.columns))
    checks.append(_result("required_columns", not missing, "all present", str(missing or "all present")))
    if missing:
        return checks

    parsed_dates = pd.to_datetime(df["trade_date"], errors="coerce")
    invalid_dates = int(parsed_dates.isna().sum())
    checks.append(_result("trade_date_valid", invalid_dates == 0, "valid dates", str(invalid_dates)))

    duplicate_count = int(df.duplicated(subset=["option_code", "trade_date", "source"]).sum())
    checks.append(_result("duplicate_option_volatility", duplicate_count == 0, "0", str(duplicate_count)))

    vol_columns = [
        "implied_volatility",
        "historical_volatility",
        "volatility_premium",
        "average_implied_volatility",
    ]
    present = [c for c in vol_columns if c in df.columns]
    negative_count = int((df[present].apply(pd.to_numeric, errors="coerce") < 0).sum().sum()) if present else 0
    checks.append(_result("non_negative_volatility", negative_count == 0, "0 negative values", str(negative_count)))

    out_of_range = int(((parsed_dates.dt.date < start_date) | (parsed_dates.dt.date > end_date)).fillna(True).sum())
    checks.append(_result("trade_date_in_requested_range", out_of_range == 0, "0 out-of-range rows", str(out_of_range)))
    checks.append(
        QualityResult(
            "requested_range_complete",
            "PASS" if range_complete else "WARN",
            f"requested_start_date={start_date.isoformat()}, requested_end_date={end_date.isoformat()}",
            (
                f"returned_min_date={returned_min_date.isoformat() if returned_min_date else None}, "
                f"returned_max_date={returned_max_date.isoformat() if returned_max_date else None}"
            ),
            None if range_complete else "One or more option codes did not cover the full requested date window.",
        )
    )
    for option_code, coverage in sorted((coverage_by_code or {}).items()):
        if not coverage.get("range_complete"):
            checks.append(
                QualityResult(
                    "requested_range_complete_by_code",
                    "WARN",
                    (
                        f"option_code={option_code}, requested_start_date={start_date.isoformat()}, "
                        f"requested_end_date={end_date.isoformat()}"
                    ),
                    (
                        f"returned_min_date={coverage.get('returned_min_date')}, "
                        f"returned_max_date={coverage.get('returned_max_date')}, "
                        f"row_count={coverage.get('row_count')}"
                    ),
                    f"Option code {option_code} did not cover the full requested date window.",
                )
            )

    return checks
