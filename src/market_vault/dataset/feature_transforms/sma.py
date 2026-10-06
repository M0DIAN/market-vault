"""Simple moving average (SMA) Feature transform.

SMA is the arithmetic mean of the exact trailing window_bars close values
selected by the executor:

    SMA(N) = fsum(close[-N:]) / N

The transform consumes exactly the supplied window, performs no data lookup,
and never reaches outside the PIT-selected rows.
"""

from __future__ import annotations

import math

from ..feature_models import FeatureTransformInput


def sma(input_: FeatureTransformInput) -> float:
    """Return the simple moving average of the supplied close window."""
    window_bars = _window_bars(input_)
    _require_row_count(input_, window_bars)
    result = math.fsum(row[0] for row in input_.rows) / window_bars
    if not math.isfinite(result):
        raise ValueError("sma result must be finite")
    return result


def _window_bars(input_: FeatureTransformInput) -> int:
    for parameter in input_.parameters:
        if parameter.name == "window_bars":
            return parameter.value
    raise ValueError("sma requires the window_bars parameter")


def _require_row_count(input_: FeatureTransformInput, window_bars: int) -> None:
    if len(input_.rows) != window_bars:
        raise ValueError(
            f"sma consumes exactly window_bars rows, got {len(input_.rows)}"
        )
