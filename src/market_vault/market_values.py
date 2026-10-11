"""Shared numeric admission for equity bars and option strike prices.

This is a numeric constraint, not evidence of market accuracy, session coverage
or point-in-time authority. Numeric strings remain admissible at normalization
boundaries; callers that require typed JSON retain their stricter type checks.
"""

from __future__ import annotations

import math


def _bounded_number(value, *, positive: bool) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(number) and (number > 0 if positive else number >= 0)


def is_positive_price(value) -> bool:
    """Prices, including strikes, must be present, finite and strictly positive."""
    return _bounded_number(value, positive=True)


def is_nonnegative_volume(value) -> bool:
    """Zero volume is valid; missing, infinite and negative volume are not."""
    return _bounded_number(value, positive=False)
