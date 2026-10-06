"""Exponential moving average (EMA) Feature transform.

EMA uses the exact trailing window_bars close values selected by the executor.
The smoothing factor is the conventional 2 / (N + 1), and the first close in
the supplied PIT-safe window is the deterministic seed:

    ema_0 = close_0
    ema_t = alpha * close_t + (1 - alpha) * ema_(t-1)

This is deliberately a window-local EMA: no value before the declared Feature
window is consulted, so execution remains PIT-safe and reproducible.
"""

from __future__ import annotations

import math

from ..feature_models import FeatureTransformInput


def ema(input_: FeatureTransformInput) -> float:
    """Return the deterministic window-local EMA of the supplied closes."""
    window_bars = _window_bars(input_)
    _require_row_count(input_, window_bars)
    alpha = 2.0 / (window_bars + 1.0)
    result = input_.rows[0][0]
    one_minus_alpha = 1.0 - alpha
    for row in input_.rows[1:]:
        result = alpha * row[0] + one_minus_alpha * result
    if not math.isfinite(result):
        raise ValueError("ema result must be finite")
    return result


def _window_bars(input_: FeatureTransformInput) -> int:
    for parameter in input_.parameters:
        if parameter.name == "window_bars":
            return parameter.value
    raise ValueError("ema requires the window_bars parameter")


def _require_row_count(input_: FeatureTransformInput, window_bars: int) -> None:
    if len(input_.rows) != window_bars:
        raise ValueError(
            f"ema consumes exactly window_bars rows, got {len(input_.rows)}"
        )
