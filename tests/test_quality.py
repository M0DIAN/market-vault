from datetime import date

import pandas as pd

from market_vault.normalization.bars import normalize_bars
from market_vault.quality.checks import run_bar_quality_checks


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
