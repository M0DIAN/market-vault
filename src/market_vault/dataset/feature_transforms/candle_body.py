"""Built-in candle_body Feature transform (v0.5.0 PR-3).

candle_body is the signed close-minus-open body of the single current bar
the executor selected:

``candle_body = close - open``

The sign is preserved (a down bar yields a negative body). This module is
fully self-contained: the implementation fingerprint of the registration
hashes exactly this module's source, so unrelated module changes never churn
this transform's pin.
"""

from __future__ import annotations

import math

from ..feature_models import FeatureTransformInput


def candle_body(input_: FeatureTransformInput) -> float:
    """Signed close minus open of the single current bar (input fields
    ``open``, ``close`` in that order).

    Raises ``ValueError`` (wrapped by the executor as
    ``FeatureExecutionError``) when the row count is not one or the result
    is not finite.
    """
    if len(input_.rows) != 1:
        raise ValueError(
            f"candle_body consumes exactly one bar, got {len(input_.rows)}"
        )
    open_price = input_.rows[0][0]
    close = input_.rows[0][1]
    result = close - open_price
    if not math.isfinite(result):
        raise ValueError("candle_body result must be finite")
    return result
