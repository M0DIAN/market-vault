"""Window-local KDJ D-line Feature transform.

KDJ V1 uses fixed standard parameters: RSV period 9, K/D smoothing 3/3,
and initial K=D=50.  The transform consumes exactly 17 PIT-selected bars,
which yields nine consecutive RSV9 observations.  No pre-window K/D state
or hidden history is consulted.
"""

from __future__ import annotations

import math

from ..feature_models import FeatureTransformInput


def kdj_d(input_: FeatureTransformInput) -> float:
    """Return the final window-local KDJ D value."""
    k, d = _kd(input_)
    result = d
    if not math.isfinite(result):
        raise ValueError("kdj_d result must be finite")
    return 0.0 if result == 0.0 else result


def _kd(input_: FeatureTransformInput) -> tuple[float, float]:
    if input_.parameters:
        raise ValueError("kdj_d accepts no parameters")
    if len(input_.rows) != 17:
        raise ValueError("kdj_d consumes exactly 17 rows")

    rows = input_.rows
    for high, low, close in rows:
        if high < low or close < low or close > high:
            raise ValueError("kdj_d requires low <= close <= high")

    k = 50.0
    d = 50.0
    for end in range(8, 17):
        window = rows[end - 8 : end + 1]
        highest = max(row[0] for row in window)
        lowest = min(row[1] for row in window)
        close = window[-1][2]
        rsv = 50.0 if highest == lowest else (
            (close - lowest) / (highest - lowest) * 100.0
        )
        k = (2.0 / 3.0) * k + (1.0 / 3.0) * rsv
        d = (2.0 / 3.0) * d + (1.0 / 3.0) * k

    if not math.isfinite(k) or not math.isfinite(d):
        raise ValueError("kdj_d K/D state must be finite")
    return k, d
