"""Window-local standard MACD histogram (12, 26, 9).

The transform consumes exactly 34 PIT-selected closes. It computes the same
nine trailing MACD(12,26) observations as macd_signal, derives their EMA(9)
signal, and returns the latest MACD line minus that signal. No pre-window
state is consulted.
"""

from __future__ import annotations

import math

from ..feature_models import FeatureTransformInput


def macd_histogram(input_: FeatureTransformInput) -> float:
    """Return latest MACD(12,26) minus the window-local EMA(9) signal."""
    _require_window(input_, 34)
    closes = tuple(row[0] for row in input_.rows)
    lines = _macd_lines(closes)
    signal = _ema(lines, 9)
    result = lines[-1] - signal
    if not math.isfinite(result):
        raise ValueError("macd_histogram result must be finite")
    return result


def _macd_lines(closes: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(
        _ema(closes[end - 25 : end + 1], 12)
        - _ema(closes[end - 25 : end + 1], 26)
        for end in range(25, 34)
    )


def _ema(values: tuple[float, ...], period: int) -> float:
    alpha = 2.0 / (period + 1.0)
    result = values[0]
    one_minus_alpha = 1.0 - alpha
    for value in values[1:]:
        result = alpha * value + one_minus_alpha * result
    return result


def _require_window(input_: FeatureTransformInput, size: int) -> None:
    if input_.parameters:
        raise ValueError("macd_histogram accepts no parameters")
    if len(input_.rows) != size:
        raise ValueError(f"macd_histogram consumes exactly {size} rows")
