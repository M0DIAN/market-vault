"""Standard research LabelSpec constructors for MarketVault v0.9.0.

The library adds no new Label arithmetic. It generates exact versioned
LabelSpec objects for the already-validated Cross-Day transforms:

- forward_return
- forward_direction
- maximum_favorable_excursion
- maximum_adverse_excursion

The bounded v1 presets use 1, 3, 5, and 10 TRADING_DAYS horizons. Every spec
uses FEATURE_CLOSE_ALIGNED, INCOMPLETE missing-data semantics, and the
existing SAME_REQUESTED_SESSION_BAR_SLOT boundary rule.
"""

from __future__ import annotations

from ..canonical.schema import CANONICAL_SCHEMA_VERSION
from ..cross_day.registry import BOUNDARY_RULE, CROSS_DAY_SOURCE_SCHEMA_VERSION
from ..dataset.models import DatasetField
from ..dataset.spec_models import (
    CrossTradingDayPolicy,
    LabelHorizon,
    LabelObservationWindow,
    LabelSpec,
    SpecVersionRequirements,
)

RESEARCH_LABEL_LIBRARY_VERSION = "market-vault-research-label-library-v1"
STANDARD_LABEL_HORIZONS = (1, 3, 5, 10)

_FORWARD_RETURN_REF = (
    "market_vault.dataset.label_transforms.forward_return:forward_return"
)
_FORWARD_DIRECTION_REF = (
    "market_vault.dataset.label_transforms.forward_direction:forward_direction"
)
_MFE_REF = (
    "market_vault.dataset.label_transforms.maximum_favorable_excursion:"
    "maximum_favorable_excursion"
)
_MAE_REF = (
    "market_vault.dataset.label_transforms.maximum_adverse_excursion:"
    "maximum_adverse_excursion"
)


def _horizon_days(value: int) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("horizon_days must be a positive integer")
    return value


def _requirements() -> SpecVersionRequirements:
    return SpecVersionRequirements(
        (CANONICAL_SCHEMA_VERSION,),
        (CROSS_DAY_SOURCE_SCHEMA_VERSION,),
    )


def _label(
    *,
    name: str,
    horizon_days: int,
    transform_ref: str,
    logical_type: str,
    input_fields: tuple[str, ...],
    observation_start: int,
) -> LabelSpec:
    horizon_days = _horizon_days(horizon_days)
    end_offset = horizon_days - 1
    return LabelSpec(
        "market-vault-label-spec-v1",
        name,
        "v1",
        DatasetField(name, logical_type, False),
        input_fields,
        transform_ref,
        (),
        _requirements(),
        LabelObservationWindow(
            "TRADING_DAYS",
            observation_start,
            end_offset,
        ),
        LabelHorizon("TRADING_DAYS", horizon_days),
        "FEATURE_CLOSE_ALIGNED",
        "INCOMPLETE",
        CrossTradingDayPolicy(True, BOUNDARY_RULE),
    )


def forward_return_label(horizon_days: int) -> LabelSpec:
    """Return a close-to-close forward-return LabelSpec for N trading days."""
    horizon_days = _horizon_days(horizon_days)
    return _label(
        name=f"forward_return_{horizon_days}d",
        horizon_days=horizon_days,
        transform_ref=_FORWARD_RETURN_REF,
        logical_type="float64",
        input_fields=("close",),
        observation_start=horizon_days - 1,
    )


def forward_direction_label(horizon_days: int) -> LabelSpec:
    """Return a signed -1/0/1 forward-direction LabelSpec for N trading days."""
    horizon_days = _horizon_days(horizon_days)
    return _label(
        name=f"forward_direction_{horizon_days}d",
        horizon_days=horizon_days,
        transform_ref=_FORWARD_DIRECTION_REF,
        logical_type="int64",
        input_fields=("close",),
        observation_start=horizon_days - 1,
    )


def maximum_favorable_excursion_label(horizon_days: int) -> LabelSpec:
    """Return long-direction maximum favorable excursion over N trading days."""
    horizon_days = _horizon_days(horizon_days)
    return _label(
        name=f"maximum_favorable_excursion_{horizon_days}d",
        horizon_days=horizon_days,
        transform_ref=_MFE_REF,
        logical_type="float64",
        input_fields=("close", "high"),
        observation_start=0,
    )


def maximum_adverse_excursion_label(horizon_days: int) -> LabelSpec:
    """Return signed long-direction maximum adverse excursion over N trading days."""
    horizon_days = _horizon_days(horizon_days)
    return _label(
        name=f"maximum_adverse_excursion_{horizon_days}d",
        horizon_days=horizon_days,
        transform_ref=_MAE_REF,
        logical_type="float64",
        input_fields=("close", "low"),
        observation_start=0,
    )


def label_preset_names() -> tuple[str, ...]:
    """Canonical names of the bounded v1 standard research Label presets."""
    return tuple(
        [f"forward_return_{n}d" for n in STANDARD_LABEL_HORIZONS]
        + [f"forward_direction_{n}d" for n in STANDARD_LABEL_HORIZONS]
        + [f"maximum_favorable_excursion_{n}d" for n in STANDARD_LABEL_HORIZONS]
        + [f"maximum_adverse_excursion_{n}d" for n in STANDARD_LABEL_HORIZONS]
    )


def label_preset(name: str) -> LabelSpec:
    """Resolve one exact standard preset name; no aliases or fuzzy matching."""
    if type(name) is not str:
        raise ValueError("label preset name must be a string")
    for horizon_days in STANDARD_LABEL_HORIZONS:
        if name == f"forward_return_{horizon_days}d":
            return forward_return_label(horizon_days)
        if name == f"forward_direction_{horizon_days}d":
            return forward_direction_label(horizon_days)
        if name == f"maximum_favorable_excursion_{horizon_days}d":
            return maximum_favorable_excursion_label(horizon_days)
        if name == f"maximum_adverse_excursion_{horizon_days}d":
            return maximum_adverse_excursion_label(horizon_days)
    raise ValueError(f"unknown research label preset: {name!r}")
