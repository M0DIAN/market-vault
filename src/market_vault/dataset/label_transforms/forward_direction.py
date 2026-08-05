"""Built-in forward_direction Label transform (v0.5.0 PR-4).

forward_direction is the sign of the close-to-close move from the exact
Feature-close anchor bar to the exact horizon target bar:

``target_close > anchor_close -> 1``
``target_close == anchor_close -> 0``
``target_close < anchor_close -> -1``

The executor passes exactly one future row — the horizon target row at
``feature_window_close + (horizon.value - 1) * nominal_interval`` — so this
transform consumes ``input_.rows[-1]`` as the target. Both prices must be
positive; a non-positive price fails closed. The result is a real ``int``
(never a bool), and the executor additionally verifies the value is one of
``-1``, ``0``, ``1`` with the int64 output contract. This module is fully
self-contained: the implementation fingerprint of the registration hashes
exactly this module's source, so unrelated module changes never churn this
transform's pin.
"""

from __future__ import annotations

from ..label_models import LabelTransformInput


def forward_direction(input_: LabelTransformInput) -> int:
    """Signed direction (-1 / 0 / 1) of the anchor-to-target close move.

    Raises ``ValueError`` (wrapped by the executor as
    ``LabelExecutionError``) when the anchor or target close is not
    positive.
    """
    if len(input_.rows) != 1:
        raise ValueError(
            f"forward_direction consumes exactly one future row (the "
            f"horizon target), got {len(input_.rows)}"
        )
    anchor_close = _close(input_, input_.anchor_row)
    target_close = _close(input_, input_.rows[-1])
    if anchor_close <= 0.0:
        raise ValueError("forward_direction requires a positive anchor close")
    if target_close <= 0.0:
        raise ValueError("forward_direction requires a positive target close")
    if target_close > anchor_close:
        return 1
    if target_close == anchor_close:
        return 0
    return -1


def _close(input_: LabelTransformInput, row: tuple[float, ...]) -> float:
    try:
        index = input_.field_names.index("close")
    except ValueError as exc:
        raise ValueError("forward_direction requires the close input field") from exc
    return row[index]
