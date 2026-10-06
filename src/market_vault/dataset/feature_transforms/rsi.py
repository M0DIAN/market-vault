"""Relative Strength Index (RSI) Feature transform.

The transform is window-local and PIT-safe. window_bars is the number of
close observations supplied to the transform, so a conventional RSI-14 uses
15 closes and therefore 14 adjacent price changes.

For the exact supplied window:

    gains  = max(delta, 0)
    losses = max(-delta, 0)
    avg_gain = sum(gains) / (window_bars - 1)
    avg_loss = sum(losses) / (window_bars - 1)

This is Wilder's initial RSI seed for that window; no pre-window recursive
state is consulted. Edge cases are deterministic: all gains -> 100, all
losses -> 0, completely flat -> 50.
"""

from __future__ import annotations

import math

from ..feature_models import FeatureTransformInput


def rsi(input_: FeatureTransformInput) -> float:
    """Return window-local Wilder-seed RSI in the closed range [0, 100]."""
    window_bars = _window_bars(input_)
    _require_row_count(input_, window_bars)
    if window_bars < 2:
        raise ValueError("rsi requires window_bars >= 2")

    closes = tuple(row[0] for row in input_.rows)
    gains = []
    losses = []
    for previous, current in zip(closes, closes[1:]):
        delta = current - previous
        gains.append(delta if delta > 0.0 else 0.0)
        losses.append(-delta if delta < 0.0 else 0.0)

    periods = window_bars - 1
    average_gain = math.fsum(gains) / periods
    average_loss = math.fsum(losses) / periods

    if average_gain == 0.0 and average_loss == 0.0:
        return 50.0
    if average_loss == 0.0:
        return 100.0
    if average_gain == 0.0:
        return 0.0

    relative_strength = average_gain / average_loss
    result = 100.0 - 100.0 / (1.0 + relative_strength)
    if not math.isfinite(result) or not 0.0 <= result <= 100.0:
        raise ValueError("rsi result must be finite and within [0, 100]")
    return result


def _window_bars(input_: FeatureTransformInput) -> int:
    for parameter in input_.parameters:
        if parameter.name == "window_bars":
            return parameter.value
    raise ValueError("rsi requires the window_bars parameter")


def _require_row_count(input_: FeatureTransformInput, window_bars: int) -> None:
    if len(input_.rows) != window_bars:
        raise ValueError(
            f"rsi consumes exactly window_bars rows, got {len(input_.rows)}"
        )
