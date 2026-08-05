"""Built-in candle_range Feature transform (v0.5.0 PR-3).

candle_range is the high-minus-low range of the single current bar the
executor selected:

``candle_range = high - low``

``high < low`` fails closed (never a silent negative range). This module is
fully self-contained: the implementation fingerprint of the registration
hashes exactly this module's source, so unrelated module changes never churn
this transform's pin.
"""

from __future__ import annotations

import math

from ..feature_models import FeatureTransformInput


def candle_range(input_: FeatureTransformInput) -> float:
    """High minus low of the single current bar (input fields ``high``,
    ``low`` in that order).

    Raises ``ValueError`` (wrapped by the executor as
    ``FeatureExecutionError``) when the row count is not one, ``high`` is
    below ``low``, or the result is not finite.
    """
    if len(input_.rows) != 1:
        raise ValueError(
            f"candle_range consumes exactly one bar, got {len(input_.rows)}"
        )
    high = input_.rows[0][0]
    low = input_.rows[0][1]
    if high < low:
        raise ValueError("candle_range requires high >= low")
    result = high - low
    if not math.isfinite(result):
        raise ValueError("candle_range result must be finite")
    return result
