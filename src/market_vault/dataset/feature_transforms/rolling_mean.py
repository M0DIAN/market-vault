"""Built-in rolling_mean Feature transform (v0.5.0 PR-3).

rolling_mean is the arithmetic mean of the trailing ``window_bars`` close
values the executor selected:

``rolling_mean = math.fsum(close_values) / window_bars``

The mean uses the exact-sum ``math.fsum`` (never pandas rolling) and is not
rounded. This module is fully self-contained: the implementation fingerprint
of the registration hashes exactly this module's source, so unrelated module
changes never churn this transform's pin.
"""

from __future__ import annotations

import math

from ..feature_models import FeatureTransformInput


def rolling_mean(input_: FeatureTransformInput) -> float:
    """Arithmetic mean of the trailing ``window_bars`` close values.

    Raises ``ValueError`` (wrapped by the executor as
    ``FeatureExecutionError``) when the row count does not equal the window
    or the result is not finite.
    """
    window_bars = _window_bars(input_)
    _require_row_count(input_, window_bars)
    result = math.fsum(row[0] for row in input_.rows) / window_bars
    if not math.isfinite(result):
        raise ValueError("rolling_mean result must be finite")
    return result


def _window_bars(input_: FeatureTransformInput) -> int:
    for parameter in input_.parameters:
        if parameter.name == "window_bars":
            return parameter.value
    raise ValueError("rolling_mean requires the window_bars parameter")


def _require_row_count(input_: FeatureTransformInput, window_bars: int) -> None:
    if len(input_.rows) != window_bars:
        raise ValueError(
            f"rolling_mean consumes exactly window_bars rows, got "
            f"{len(input_.rows)}"
        )
