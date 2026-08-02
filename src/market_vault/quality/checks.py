from __future__ import annotations

import pandas as pd

from ..models import QualityResult


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
