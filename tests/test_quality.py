from datetime import date

import pandas as pd
import pytest

from market_vault.normalization.bars import normalize_bars
from market_vault.quality.checks import run_bar_quality_checks, run_option_contract_quality_checks


def test_quality_passes_clean_frame():
    raw = pd.DataFrame(
        {
            "code": ["US.MU"],
            "time_key": ["2026-07-31 09:30:00"],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [100],
        }
    )
    df = normalize_bars(
        raw,
        date(2026, 7, 31),
        "1m",
        "ALL",
        "NONE",
        "moomoo",
        "10.9",
        "run-1",
    )
    checks = run_bar_quality_checks(df)
    assert all(item.result == "PASS" for item in checks)


def quality_frame():
    return pd.DataFrame({
        "code": ["US.MU"], "interval": ["1m"], "adjustment": ["NONE"],
        "time_utc": [pd.Timestamp("2026-07-31T13:30:00Z")],
        "open": [100.0], "high": [101.0], "low": [99.0], "close": [100.5],
        "volume": [100.0],
    })


@pytest.mark.parametrize("values", [
    dict(open=0.0, high=0.0, low=0.0, close=0.0),
    dict(open=-2.0, high=-1.0, low=-3.0, close=-2.0),
    dict(high=float("inf")), dict(close=float("nan")), dict(open="not-a-price"),
])
def test_invalid_prices_cannot_pass_basic_quality(values):
    checks = run_bar_quality_checks(quality_frame().assign(**values))
    assert any(item.result == "FAIL" for item in checks)


@pytest.mark.parametrize("volume", [float("inf"), float("-inf"), float("nan"), None, -1.0, "bad"])
def test_volume_must_be_finite_nonnegative(volume):
    checks = run_bar_quality_checks(quality_frame().assign(volume=volume))
    assert any(item.result == "FAIL" for item in checks)


def test_zero_volume_is_valid_without_claiming_external_accuracy():
    checks = {item.check_name: item for item in run_bar_quality_checks(quality_frame().assign(volume=0))}
    assert all(item.result == "PASS" for item in checks.values())
    assert checks["validation_scope"].actual_value == "BASIC_BAR_STRUCTURE_AND_NUMERICS"
    assert "external" in checks["validation_scope"].details.lower()


def option_quality_frame(strike=120.0):
    return pd.DataFrame({
        "option_code": ["US.MU260807C120000"], "underlying_code": ["US.MU"],
        "option_type": ["CALL"], "strike_price": [strike], "expiry_date": ["2026-08-07"],
        "captured_at": [pd.Timestamp("2026-08-02T01:00:00Z")], "source": ["moomoo"],
    })


@pytest.mark.parametrize("strike", [float("nan"), pd.NA, None, float("inf"), float("-inf"), 0, -1, "bad"])
def test_strike_is_present_finite_and_strictly_positive(strike):
    checks = {item.check_name: item for item in run_option_contract_quality_checks(option_quality_frame(strike))}
    assert checks["strike_price_positive"].result == "FAIL"
    assert checks["strike_price_positive"].actual_value == "1"


@pytest.mark.parametrize("strike", [120.0, "120.0"])
def test_valid_option_strike_still_passes(strike):
    assert all(item.result == "PASS" for item in run_option_contract_quality_checks(option_quality_frame(strike)))


@pytest.mark.parametrize("kind,column", [
    ("bars", "interval"), ("bars", "adjustment"), ("options", "captured_at"), ("options", "source"),
])
def test_duplicate_key_columns_are_reported_missing(kind, column):
    frame, check = ((quality_frame(), run_bar_quality_checks) if kind == "bars"
                    else (option_quality_frame(), run_option_contract_quality_checks))
    checks = check(frame.drop(columns=[column]))
    assert len(checks) == 1
    assert checks[0].check_name == "required_columns" and checks[0].result == "FAIL"
    assert column in checks[0].actual_value
