"""Built-in simple_return Feature transform (v0.5.0 PR-3).

simple_return is the close-to-close return over the trailing ``window_bars``
rows the executor selected:

``simple_return = last_close / first_close - 1.0``

``window_bars == 2`` is an ordinary one-bar-interval return. A zero first
close fails closed (never a silent zero result); the result must be finite.
This module is fully self-contained: the implementation fingerprint of the
registration hashes exactly this module's source, so unrelated module
changes never churn this transform's pin.
"""

from __future__ import annotations

import math

from ..feature_models import FeatureTransformInput


def simple_return(input_: FeatureTransformInput) -> float:
    """Close-to-close return over the trailing ``window_bars`` rows.

    Raises ``ValueError`` (wrapped by the executor as
    ``FeatureExecutionError``) when the first close is zero or the result is
    not finite.
    """
    window_bars = _window_bars(input_)
    _require_row_count(input_, window_bars)
    first_close = input_.rows[0][0]
    last_close = input_.rows[-1][0]
    if first_close == 0.0:
        raise ValueError("simple_return requires a non-zero first close")
    result = last_close / first_close - 1.0
    if not math.isfinite(result):
        raise ValueError("simple_return result must be finite")
    return result


def _window_bars(input_: FeatureTransformInput) -> int:
    for parameter in input_.parameters:
        if parameter.name == "window_bars":
            return parameter.value
    raise ValueError("simple_return requires the window_bars parameter")


def _require_row_count(input_: FeatureTransformInput, window_bars: int) -> None:
    if len(input_.rows) != window_bars:
        raise ValueError(
            f"simple_return consumes exactly window_bars rows, got "
            f"{len(input_.rows)}"
        )
