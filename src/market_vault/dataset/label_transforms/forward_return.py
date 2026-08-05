"""Built-in forward_return Label transform (v0.5.0 PR-4).

forward_return is the close-to-close return from the exact Feature-close
anchor bar to the exact horizon target bar:

``forward_return = target_close / anchor_close - 1.0``

The executor passes exactly one future row — the horizon target row at
``feature_window_close + (horizon.value - 1) * nominal_interval`` — so this
transform consumes ``input_.rows[-1]`` as the target. Both prices must be
positive and the ratio must be finite; a non-positive anchor or target close
fails closed (never a silent zero result). The result is never rounded and
never formatted into a percent string. This module is fully self-contained:
the implementation fingerprint of the registration hashes exactly this
module's source, so unrelated module changes never churn this transform's
pin.
"""

from __future__ import annotations

import math

from ..label_models import LabelTransformInput


def forward_return(input_: LabelTransformInput) -> float:
    """Close-to-close return from the anchor close to the horizon target
    close.

    Raises ``ValueError`` (wrapped by the executor as
    ``LabelExecutionError``) when the anchor or target close is not
    positive or the result is not finite.
    """
    if len(input_.rows) != 1:
        raise ValueError(
            f"forward_return consumes exactly one future row (the horizon "
            f"target), got {len(input_.rows)}"
        )
    anchor_close = _close(input_, input_.anchor_row)
    target_close = _close(input_, input_.rows[-1])
    if anchor_close <= 0.0:
        raise ValueError("forward_return requires a positive anchor close")
    if target_close <= 0.0:
        raise ValueError("forward_return requires a positive target close")
    result = target_close / anchor_close - 1.0
    if not math.isfinite(result):
        raise ValueError("forward_return result must be finite")
    return result


def _close(input_: LabelTransformInput, row: tuple[float, ...]) -> float:
    try:
        index = input_.field_names.index("close")
    except ValueError as exc:
        raise ValueError("forward_return requires the close input field") from exc
    return row[index]
