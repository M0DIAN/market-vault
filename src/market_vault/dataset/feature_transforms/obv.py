"""Window-local On-Balance Volume (OBV) Feature transform.

The first bar in the supplied PIT-safe window has deterministic OBV seed 0.
For each later bar, current volume is added when close rises, subtracted when
close falls, and ignored when close is unchanged. The returned value therefore
represents OBV movement inside the declared window without hidden pre-window
history.
"""

from __future__ import annotations

import math

from ..feature_models import FeatureTransformInput


def obv(input_: FeatureTransformInput) -> float:
    """Return window-local OBV with a zero seed at the first close."""
    window_bars = _window_bars(input_)
    _require_row_count(input_, window_bars)
    if window_bars < 2:
        raise ValueError("obv requires window_bars >= 2")

    result = 0.0
    previous_close = input_.rows[0][0]
    for close, volume in input_.rows[1:]:
        if volume < 0.0:
            raise ValueError("obv requires non-negative volume")
        if close > previous_close:
            result += volume
        elif close < previous_close:
            result -= volume
        previous_close = close

    if not math.isfinite(result):
        raise ValueError("obv result must be finite")
    return 0.0 if result == 0.0 else result


def _window_bars(input_: FeatureTransformInput) -> int:
    for parameter in input_.parameters:
        if parameter.name == "window_bars":
            return parameter.value
    raise ValueError("obv requires the window_bars parameter")


def _require_row_count(input_: FeatureTransformInput, window_bars: int) -> None:
    if len(input_.rows) != window_bars:
        raise ValueError(
            f"obv consumes exactly window_bars rows, got {len(input_.rows)}"
        )
