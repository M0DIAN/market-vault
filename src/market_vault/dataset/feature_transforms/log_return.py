"""Built-in log_return Feature transform (v0.5.0 PR-3).

log_return is the natural log of the close-to-close ratio over the trailing
``window_bars`` rows the executor selected:

``log_return = log(last_close / first_close)``

Both boundary closes must be strictly positive, the ratio must be finite
and positive, and the result must be finite. ``window_bars == 2`` is an
ordinary one-bar-interval log return. This module is fully self-contained:
the implementation fingerprint of the registration hashes exactly this
module's source, so unrelated module changes never churn this transform's
pin.
"""

from __future__ import annotations

import math

from ..feature_models import FeatureTransformInput


def log_return(input_: FeatureTransformInput) -> float:
    """Natural log of the close-to-close ratio over the trailing
    ``window_bars`` rows.

    Raises ``ValueError`` (wrapped by the executor as
    ``FeatureExecutionError``) on non-positive closes, a non-positive or
    non-finite ratio, or a non-finite result.
    """
    window_bars = _window_bars(input_)
    _require_row_count(input_, window_bars)
    first_close = input_.rows[0][0]
    last_close = input_.rows[-1][0]
    if first_close <= 0.0 or last_close <= 0.0:
        raise ValueError(
            "log_return requires strictly positive closes on both boundaries"
        )
    ratio = last_close / first_close
    if not (math.isfinite(ratio) and ratio > 0.0):
        raise ValueError("log_return ratio must be finite and positive")
    result = math.log(ratio)
    if not math.isfinite(result):
        raise ValueError("log_return result must be finite")
    return result


def _window_bars(input_: FeatureTransformInput) -> int:
    for parameter in input_.parameters:
        if parameter.name == "window_bars":
            return parameter.value
    raise ValueError("log_return requires the window_bars parameter")


def _require_row_count(input_: FeatureTransformInput, window_bars: int) -> None:
    if len(input_.rows) != window_bars:
        raise ValueError(
            f"log_return consumes exactly window_bars rows, got "
            f"{len(input_.rows)}"
        )
