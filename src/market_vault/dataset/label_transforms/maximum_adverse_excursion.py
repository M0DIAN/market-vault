"""Built-in maximum_adverse_excursion Label transform (v0.5.0 PR-4).

maximum_adverse_excursion is the largest negative close-relative excursion
of the future window's lows from the exact Feature-close anchor price,
measured long-direction and capped at zero:

``mae = min(0.0, min(row_low / anchor_close - 1.0 for row in future_rows))``

The result is a **signed** long-direction adverse excursion: always
``<= 0.0``, never converted to an absolute value, and never a trading
recommendation. The anchor close is the baseline price 0. Every future
row's ``low`` must be positive and every ratio must be finite; the anchor
close must be positive. The result is never rounded and never formatted
into a percent string. This module is fully self-contained: the
implementation fingerprint of the registration hashes exactly this module's
source, so unrelated module changes never churn this transform's pin.
"""

from __future__ import annotations

import math

from ..label_models import LabelTransformInput


def maximum_adverse_excursion(input_: LabelTransformInput) -> float:
    """Largest negative low-to-anchor excursion over the future window.

    Raises ``ValueError`` (wrapped by the executor as
    ``LabelExecutionError``) when the anchor close or any future ``low`` is
    not positive or any ratio is not finite.
    """
    anchor_close = _field(input_, "close", input_.anchor_row)
    if anchor_close <= 0.0:
        raise ValueError(
            "maximum_adverse_excursion requires a positive anchor close"
        )
    low_index = _field_index(input_, "low")
    worst = 0.0
    for row in input_.rows:
        low = row[low_index]
        if low <= 0.0:
            raise ValueError(
                "maximum_adverse_excursion requires every future low to "
                "be positive"
            )
        ratio = low / anchor_close - 1.0
        if not math.isfinite(ratio):
            raise ValueError(
                "maximum_adverse_excursion ratios must be finite"
            )
        if ratio < worst:
            worst = ratio
    return worst


def _field_index(input_: LabelTransformInput, name: str) -> int:
    try:
        return input_.field_names.index(name)
    except ValueError as exc:
        raise ValueError(
            f"maximum_adverse_excursion requires the {name} input field"
        ) from exc


def _field(input_: LabelTransformInput, name: str, row: tuple[float, ...]) -> float:
    return row[_field_index(input_, name)]
