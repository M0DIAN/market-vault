"""Window-local KDJ J-line Feature transform.

KDJ is computed from standard 9-bar RSV values. K and D start at 50 and are
updated for every valid RSV inside the exact PIT-selected window:

    K = (2/3) * K_prev + (1/3) * RSV
    D = (2/3) * D_prev + (1/3) * K
    J = 3*K - 2*D

window_bars is the explicit amount of history used for this window-local
recurrence and must be >= 9. No pre-window K/D state is consulted.
"""

from __future__ import annotations

import math

from ..feature_models import FeatureTransformInput


def kdj_j(input_: FeatureTransformInput) -> float:
    """Return the final window-local KDJ J value."""
    k, d = _kd(input_)
    result = 3.0 * k - 2.0 * d
    if not math.isfinite(result):
        raise ValueError("kdj_j result must be finite")
    return 0.0 if result == 0.0 else result


def _kd(input_: FeatureTransformInput) -> tuple[float, float]:
    window_bars = _window_bars(input_)
    _require_row_count(input_, window_bars)
    if window_bars < 9:
        raise ValueError("kdj_j requires window_bars >= 9")

    rows = input_.rows
    for high, low, close in rows:
        if high < low or close < low or close > high:
            raise ValueError("kdj_j requires low <= close <= high")

    k = 50.0
    d = 50.0
    for end in range(8, len(rows)):
        window = rows[end - 8 : end + 1]
        highest = max(row[0] for row in window)
        lowest = min(row[1] for row in window)
        close = window[-1][2]
        if highest == lowest:
            rsv = 50.0
        else:
            rsv = (close - lowest) / (highest - lowest) * 100.0
        k = (2.0 / 3.0) * k + (1.0 / 3.0) * rsv
        d = (2.0 / 3.0) * d + (1.0 / 3.0) * k

    if not math.isfinite(k) or not math.isfinite(d):
        raise ValueError("kdj_j K/D state must be finite")
    return k, d


def _window_bars(input_: FeatureTransformInput) -> int:
    for parameter in input_.parameters:
        if parameter.name == "window_bars":
            return parameter.value
    raise ValueError("kdj_j requires the window_bars parameter")


def _require_row_count(input_: FeatureTransformInput, window_bars: int) -> None:
    if len(input_.rows) != window_bars:
        raise ValueError(
            f"kdj_j consumes exactly window_bars rows, got {len(input_.rows)}"
        )
