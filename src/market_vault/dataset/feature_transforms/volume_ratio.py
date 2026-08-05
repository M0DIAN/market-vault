"""Built-in volume_ratio Feature transform (v0.5.0 PR-3).

volume_ratio compares the last bar's volume with the mean volume of the
``window_bars - 1`` earlier bars of the trailing window the executor
selected:

``previous_mean = math.fsum(previous_volumes) / (window_bars - 1)``
``volume_ratio = current_volume / previous_mean``

The current bar never enters ``previous_mean``; ``window_bars`` must be at
least 2 (the registry lower bound). A non-positive ``previous_mean`` fails
closed (never a silent zero result). This module is fully self-contained:
the implementation fingerprint of the registration hashes exactly this
module's source, so unrelated module changes never churn this transform's
pin.
"""

from __future__ import annotations

import math

from ..feature_models import FeatureTransformInput


def volume_ratio(input_: FeatureTransformInput) -> float:
    """Current volume divided by the mean volume of the ``window_bars - 1``
    earlier bars.

    Raises ``ValueError`` (wrapped by the executor as
    ``FeatureExecutionError``) on a non-positive previous mean or a
    non-finite result.
    """
    window_bars = _window_bars(input_)
    _require_row_count(input_, window_bars)
    current_volume = input_.rows[-1][0]
    previous_volumes = [row[0] for row in input_.rows[:-1]]
    previous_mean = math.fsum(previous_volumes) / (window_bars - 1)
    if previous_mean <= 0.0:
        raise ValueError("volume_ratio previous mean must be positive")
    result = current_volume / previous_mean
    if not math.isfinite(result):
        raise ValueError("volume_ratio result must be finite")
    return result


def _window_bars(input_: FeatureTransformInput) -> int:
    for parameter in input_.parameters:
        if parameter.name == "window_bars":
            return parameter.value
    raise ValueError("volume_ratio requires the window_bars parameter")


def _require_row_count(input_: FeatureTransformInput, window_bars: int) -> None:
    if len(input_.rows) != window_bars:
        raise ValueError(
            f"volume_ratio consumes exactly window_bars rows, got "
            f"{len(input_.rows)}"
        )
