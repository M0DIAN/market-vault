"""Research-facing standard Label library.

This package contains thin, deterministic research-spec helpers only. The
actual Label formulas and Cross-Day execution authority remain in the existing
dataset/cross_day layers.
"""

from .labels import (
    RESEARCH_LABEL_LIBRARY_VERSION,
    STANDARD_LABEL_HORIZONS,
    forward_direction_label,
    forward_open_to_close_return_label,
    forward_return_label,
    label_preset,
    label_preset_names,
    maximum_adverse_excursion_label,
    maximum_favorable_excursion_label,
)

__all__ = [
    "RESEARCH_LABEL_LIBRARY_VERSION",
    "STANDARD_LABEL_HORIZONS",
    "forward_direction_label",
    "forward_open_to_close_return_label",
    "forward_return_label",
    "label_preset",
    "label_preset_names",
    "maximum_adverse_excursion_label",
    "maximum_favorable_excursion_label",
]
