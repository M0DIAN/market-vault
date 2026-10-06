"""Window-local Average True Range (ATR) Feature transform.

window_bars is the number of OHLC observations supplied. A conventional
ATR-14 therefore uses 15 bars and 14 true-range observations. The result is
Wilder's initial ATR seed: the arithmetic mean of those true ranges. No
pre-window recursive state is consulted.
"""

from __future__ import annotations

import math

from ..feature_models import FeatureTransformInput


def atr(input_: FeatureTransformInput) -> float:
    """Return the window-local Wilder-seed ATR."""
    window_bars = _window_bars(input_)
    _require_row_count(input_, window_bars)
    if window_bars < 2:
        raise ValueError("atr requires window_bars >= 2")

    true_ranges = []
    for previous, current in zip(input_.rows, input_.rows[1:]):
        previous_close = previous[2]
        high, low, _close = current
        if high < low:
            raise ValueError("atr requires high >= low")
        true_ranges.append(
            max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            )
        )

    result = math.fsum(true_ranges) / (window_bars - 1)
    if not math.isfinite(result) or result < 0.0:
        raise ValueError("atr result must be finite and non-negative")
    return result


def _window_bars(input_: FeatureTransformInput) -> int:
    for parameter in input_.parameters:
        if parameter.name == "window_bars":
            return parameter.value
    raise ValueError("atr requires the window_bars parameter")


def _require_row_count(input_: FeatureTransformInput, window_bars: int) -> None:
    if len(input_.rows) != window_bars:
        raise ValueError(
            f"atr consumes exactly window_bars rows, got {len(input_.rows)}"
        )
