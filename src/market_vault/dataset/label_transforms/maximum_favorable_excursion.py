"""Built-in maximum_favorable_excursion Label transform (v0.5.0 PR-4).

maximum_favorable_excursion is the largest positive close-relative excursion
of the future window's highs from the exact Feature-close anchor price,
measured long-direction and floored at zero:

``mfe = max(0.0, max(row_high / anchor_close - 1.0 for row in future_rows))``

The anchor close is the baseline price 0; the result is always ``>= 0.0``
and never a bullish/bearish or buy/sell signal. Every future row's ``high``
must be positive and every ratio must be finite; the anchor close must be
positive. The result is never rounded and never formatted into a percent
string. This module is fully self-contained: the implementation fingerprint
of the registration hashes exactly this module's source, so unrelated module
changes never churn this transform's pin.
"""

from __future__ import annotations

import math

from ..label_models import LabelTransformInput


def maximum_favorable_excursion(input_: LabelTransformInput) -> float:
    """Largest positive high-to-anchor excursion over the future window.

    Raises ``ValueError`` (wrapped by the executor as
    ``LabelExecutionError``) when the anchor close or any future ``high`` is
    not positive or any ratio is not finite.
    """
    anchor_close = _field(input_, "close", input_.anchor_row)
    if anchor_close <= 0.0:
        raise ValueError(
            "maximum_favorable_excursion requires a positive anchor close"
        )
    high_index = _field_index(input_, "high")
    best = 0.0
    for row in input_.rows:
        high = row[high_index]
        if high <= 0.0:
            raise ValueError(
                "maximum_favorable_excursion requires every future high to "
                "be positive"
            )
        ratio = high / anchor_close - 1.0
        if not math.isfinite(ratio):
            raise ValueError(
                "maximum_favorable_excursion ratios must be finite"
            )
        if ratio > best:
            best = ratio
    return best


def _field_index(input_: LabelTransformInput, name: str) -> int:
    try:
        return input_.field_names.index(name)
    except ValueError as exc:
        raise ValueError(
            f"maximum_favorable_excursion requires the {name} input field"
        ) from exc


def _field(input_: LabelTransformInput, name: str, row: tuple[float, ...]) -> float:
    return row[_field_index(input_, name)]
