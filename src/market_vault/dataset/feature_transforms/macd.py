"""Window-local standard MACD line (12, 26).

The transform consumes exactly 26 PIT-selected close observations. Fast and
slow EMAs use periods 12 and 26 with the first close in the supplied window
as the deterministic seed. No pre-window state is consulted.
"""

from __future__ import annotations

import math

from ..feature_models import FeatureTransformInput


def macd(input_: FeatureTransformInput) -> float:
    """Return EMA(12) minus EMA(26) for the exact 26-close window."""
    _require_window(input_, 26)
    closes = tuple(row[0] for row in input_.rows)
    result = _ema(closes, 12) - _ema(closes, 26)
    if not math.isfinite(result):
        raise ValueError("macd result must be finite")
    return result


def _ema(values: tuple[float, ...], period: int) -> float:
    alpha = 2.0 / (period + 1.0)
    result = values[0]
    one_minus_alpha = 1.0 - alpha
    for value in values[1:]:
        result = alpha * value + one_minus_alpha * result
    return result


def _require_window(input_: FeatureTransformInput, size: int) -> None:
    if input_.parameters:
        raise ValueError("macd accepts no parameters")
    if len(input_.rows) != size:
        raise ValueError(f"macd consumes exactly {size} rows")
