from datetime import date

import pandas as pd

from market_vault.normalization.bars import infer_asset_type, infer_underlying, normalize_bars


def sample_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "code": ["US.MU", "US.MU"],
            "name": ["MICRON", "MICRON"],
            "time_key": ["2026-07-31 09:30:00", "2026-07-31 16:01:00"],
            "open": [110.0, 111.0],
            "high": [111.0, 112.0],
            "low": [109.5, 110.5],
            "close": [110.5, 111.5],
            "volume": [1000, 500],
            "turnover": [110500.0, 55750.0],
        }
    )


def test_normalize_assigns_timezones_and_sessions():
    out = normalize_bars(sample_frame(), date(2026, 7, 31), "1m", "ALL", "NONE", "moomoo", "10.9", "run-1")
    assert str(out["time_market"].dt.tz) == "America/New_York"
    assert str(out["time_utc"].dt.tz) == "UTC"
    assert out["session"].tolist() == ["REGULAR", "AFTER_HOURS"]
    assert out["requested_session"].tolist() == ["ALL", "ALL"]


def test_option_inference():
    code = "US.MU260807C120000"
    assert infer_asset_type(code) == "OPTION"
    assert infer_underlying(code) == "US.MU"
