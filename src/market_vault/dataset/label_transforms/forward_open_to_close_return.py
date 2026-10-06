"""Execution-safe forward open-to-close return Label transform.

This Label is designed for signals that become known only at the current
Feature window close.  It never assumes a fill at that already-observed close.

The future Label rows are the aligned same-slot bars of future trading days.
The first future row supplies the entry open and the last future row supplies
the exit close:

    return = last_future_close / first_future_open - 1.0

For a 1-trading-day horizon the same next-trading-day bar provides both entry
open and exit close.  For longer horizons the first future day's open is the
entry and the Nth future day's close is the exit.  No anchor price is used and
no hidden/pre-window state is consulted.
"""

from __future__ import annotations

import math

from ..label_models import LabelTransformInput


def forward_open_to_close_return(input_: LabelTransformInput) -> float:
    """Return future-first-open to future-last-close return."""
    if not input_.rows:
        raise ValueError(
            "forward_open_to_close_return requires at least one future row"
        )
    open_index = _field_index(input_, "open")
    close_index = _field_index(input_, "close")
    entry_open = input_.rows[0][open_index]
    exit_close = input_.rows[-1][close_index]
    if entry_open <= 0.0:
        raise ValueError(
            "forward_open_to_close_return requires a positive entry open"
        )
    if exit_close <= 0.0:
        raise ValueError(
            "forward_open_to_close_return requires a positive exit close"
        )
    result = exit_close / entry_open - 1.0
    if not math.isfinite(result):
        raise ValueError("forward_open_to_close_return result must be finite")
    return 0.0 if result == 0.0 else result


def _field_index(input_: LabelTransformInput, name: str) -> int:
    try:
        return input_.field_names.index(name)
    except ValueError as exc:
        raise ValueError(
            f"forward_open_to_close_return requires the {name} input field"
        ) from exc
