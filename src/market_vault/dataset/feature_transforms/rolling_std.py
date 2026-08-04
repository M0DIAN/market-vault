"""Built-in rolling_std Feature transform (v0.5.0 PR-3).

rolling_std is the population standard deviation (ddof = 0) of the trailing
``window_bars`` close values the executor selected:

``mean = math.fsum(values) / n``
``variance = math.fsum((x - mean) ** 2 for x in values) / n``
``result = math.sqrt(variance)``

This is the explicit population formula; pandas' default sample standard
deviation (ddof = 1) is never used. This module is fully self-contained: the
implementation fingerprint of the registration hashes exactly this module's
source, so unrelated module changes never churn this transform's pin.
"""

from __future__ import annotations

import math

from ..feature_models import FeatureTransformInput


def rolling_std(input_: FeatureTransformInput) -> float:
    """Population standard deviation (ddof = 0) of the trailing
    ``window_bars`` close values.

    Raises ``ValueError`` (wrapped by the executor as
    ``FeatureExecutionError``) when the row count does not equal the window
    or the result is not finite.
    """
    window_bars = _window_bars(input_)
    _require_row_count(input_, window_bars)
    values = [row[0] for row in input_.rows]
    mean = math.fsum(values) / window_bars
    variance = math.fsum((x - mean) ** 2 for x in values) / window_bars
    result = math.sqrt(variance)
    if not math.isfinite(result):
        raise ValueError("rolling_std result must be finite")
    return result


def _window_bars(input_: FeatureTransformInput) -> int:
    for parameter in input_.parameters:
        if parameter.name == "window_bars":
            return parameter.value
    raise ValueError("rolling_std requires the window_bars parameter")


def _require_row_count(input_: FeatureTransformInput, window_bars: int) -> None:
    if len(input_.rows) != window_bars:
        raise ValueError(
            f"rolling_std consumes exactly window_bars rows, got "
            f"{len(input_.rows)}"
        )
