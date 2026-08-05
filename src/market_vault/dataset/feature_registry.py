"""Built-in immutable Feature transform registrations (v0.5.0 PR-3).

This module declares the fixed set of built-in basic OHLCV Feature
registrations and the immutable registry that carries them. The executor
(:mod:`market_vault.dataset.feature_execution`) resolves FeatureSpecs only
against this built-in registry, so a caller can never make the executor run
an arbitrary function.

``built_in_feature_registrations`` returns the same deterministic tuple of
:class:`TransformRegistration` instances on every call (sorted by
``transform_ref``); ``built_in_feature_registry`` returns a fresh immutable
:class:`TransformRegistry` over them. There is no import side effect, no
decorator registration, no mutable global registry, no package / entry-point
/ filesystem scanning, no alias, no ``replace``, and no network access. The
registrations are constructed once per call from the already-imported
transform functions; each registration's implementation fingerprint is the
construction-time snapshot of that transform module's normalized source, so
one transform's source change only churns that transform's pin.
"""

from __future__ import annotations

from ..canonical.schema import CANONICAL_SCHEMA_VERSION
from .models import SPEC_KIND_FEATURE
from .feature_transforms import (
    candle_body,
    candle_range,
    log_return,
    rolling_mean,
    rolling_std,
    rolling_volume_mean,
    simple_return,
    volume_ratio,
)
from .transform_models import (
    BOUNDARY_POLICY_SAME_MARKET_CALENDAR_DATE,
    MISSING_POLICY_EXCLUDE_SAMPLE,
    PARAMETER_TYPE_INT64,
    TransformParameterContract,
    TransformRegistration,
    TransformWindowRequirement,
    WINDOW_BOUNDARY_INCLUSIVE,
    WINDOW_SOURCE_FIXED,
    WINDOW_SOURCE_NONE,
    WINDOW_SOURCE_PARAMETER,
    WINDOW_UNIT_BARS,
    WINDOW_UNIT_NONE,
)
from .transform_registry import TransformRegistry

__all__ = [
    "SUPPORTED_CANONICAL_SCHEMA_VERSIONS",
    "SUPPORTED_SOURCE_SCHEMA_VERSIONS",
    "built_in_feature_registrations",
    "built_in_feature_registry",
]

#: Canonical schema versions the built-in registrations support. The current
#: authoritative Canonical bars schema version is the only supported one;
#: no wildcard or version placeholder is ever used.
SUPPORTED_CANONICAL_SCHEMA_VERSIONS = (CANONICAL_SCHEMA_VERSION,)

#: Source schema versions the built-in registrations support: the codebase's
#: current authoritative source schema version (the ``Settings`` default,
#: ``"10.9"``). No wildcard or version placeholder is ever used.
SUPPORTED_SOURCE_SCHEMA_VERSIONS = ("10.9",)

#: Implementation version of every built-in transform in this catalog.
_IMPLEMENTATION_VERSION = "v1"


def _window_bars_contract(lower_bound: int) -> TransformParameterContract:
    """The fixed ``window_bars`` parameter contract of the windowed
    transforms: a non-nullable int64 parameter whose lower bound is the
    transform's minimum real window (1 or 2). No implicit default exists —
    every FeatureSpec must carry the parameter explicitly."""
    return TransformParameterContract(
        name="window_bars",
        value_type=PARAMETER_TYPE_INT64,
        nullable=False,
        lower_bound=lower_bound,
    )


def _parameter_window(parameter_name: str) -> TransformWindowRequirement:
    """A PARAMETER-derived lookback of ``window_bars`` bars, inclusive."""
    return TransformWindowRequirement(
        source=WINDOW_SOURCE_PARAMETER,
        unit=WINDOW_UNIT_BARS,
        value=None,
        parameter_name=parameter_name,
        boundary=WINDOW_BOUNDARY_INCLUSIVE,
    )


def _fixed_window(value: int) -> TransformWindowRequirement:
    """A fixed lookback of ``value`` bars, inclusive."""
    return TransformWindowRequirement(
        source=WINDOW_SOURCE_FIXED,
        unit=WINDOW_UNIT_BARS,
        value=value,
        parameter_name=None,
        boundary=WINDOW_BOUNDARY_INCLUSIVE,
    )


def _no_window() -> TransformWindowRequirement:
    return TransformWindowRequirement(source=WINDOW_SOURCE_NONE, unit=WINDOW_UNIT_NONE)


def _registration(
    *,
    transform_ref: str,
    implementation,
    input_canonical_fields: tuple[str, ...],
    parameters: tuple[TransformParameterContract, ...],
    lookback: TransformWindowRequirement,
    display_name: str,
) -> TransformRegistration:
    """One built-in Feature registration with the fixed shared metadata:
    kind FEATURE, implementation version ``v1``, the current authoritative
    canonical/source schema versions, float64 non-nullable output, NONE
    lookforward, SAME_MARKET_CALENDAR_DATE boundary policy, and
    EXCLUDE_SAMPLE missing policy."""
    return TransformRegistration(
        transform_ref=transform_ref,
        kind=SPEC_KIND_FEATURE,
        implementation_version=_IMPLEMENTATION_VERSION,
        implementation=implementation,
        input_canonical_fields=input_canonical_fields,
        supported_canonical_schema_versions=SUPPORTED_CANONICAL_SCHEMA_VERSIONS,
        supported_source_schema_versions=SUPPORTED_SOURCE_SCHEMA_VERSIONS,
        output_logical_type="float64",
        output_nullable=False,
        parameters=parameters,
        lookback=lookback,
        lookforward=_no_window(),
        boundary_policy=BOUNDARY_POLICY_SAME_MARKET_CALENDAR_DATE,
        missing_policy=MISSING_POLICY_EXCLUDE_SAMPLE,
        display_name=display_name,
    )


def built_in_feature_registrations() -> tuple[TransformRegistration, ...]:
    """The fixed tuple of built-in Feature registrations, deterministically
    sorted by ``transform_ref``. Every call returns an equal tuple; no
    global mutable registry is created."""
    registrations = (
        _registration(
            transform_ref="market_vault.dataset.feature_transforms.simple_return:simple_return",
            implementation=simple_return,
            input_canonical_fields=("close",),
            parameters=(_window_bars_contract(2),),
            lookback=_parameter_window("window_bars"),
            display_name="Simple close-to-close return",
        ),
        _registration(
            transform_ref="market_vault.dataset.feature_transforms.log_return:log_return",
            implementation=log_return,
            input_canonical_fields=("close",),
            parameters=(_window_bars_contract(2),),
            lookback=_parameter_window("window_bars"),
            display_name="Log close-to-close return",
        ),
        _registration(
            transform_ref="market_vault.dataset.feature_transforms.rolling_mean:rolling_mean",
            implementation=rolling_mean,
            input_canonical_fields=("close",),
            parameters=(_window_bars_contract(1),),
            lookback=_parameter_window("window_bars"),
            display_name="Rolling mean of closes",
        ),
        _registration(
            transform_ref="market_vault.dataset.feature_transforms.rolling_std:rolling_std",
            implementation=rolling_std,
            input_canonical_fields=("close",),
            parameters=(_window_bars_contract(2),),
            lookback=_parameter_window("window_bars"),
            display_name="Rolling population standard deviation of closes",
        ),
        _registration(
            transform_ref="market_vault.dataset.feature_transforms.rolling_volume_mean:rolling_volume_mean",
            implementation=rolling_volume_mean,
            input_canonical_fields=("volume",),
            parameters=(_window_bars_contract(1),),
            lookback=_parameter_window("window_bars"),
            display_name="Rolling mean of volumes",
        ),
        _registration(
            transform_ref="market_vault.dataset.feature_transforms.volume_ratio:volume_ratio",
            implementation=volume_ratio,
            input_canonical_fields=("volume",),
            parameters=(_window_bars_contract(2),),
            lookback=_parameter_window("window_bars"),
            display_name="Volume ratio to the previous mean",
        ),
        _registration(
            transform_ref="market_vault.dataset.feature_transforms.candle_range:candle_range",
            implementation=candle_range,
            input_canonical_fields=("high", "low"),
            parameters=(),
            lookback=_fixed_window(1),
            display_name="Candle high-minus-low range",
        ),
        _registration(
            transform_ref="market_vault.dataset.feature_transforms.candle_body:candle_body",
            implementation=candle_body,
            input_canonical_fields=("open", "close"),
            parameters=(),
            lookback=_fixed_window(1),
            display_name="Signed candle close-minus-open body",
        ),
    )
    return tuple(sorted(registrations, key=lambda item: item.transform_ref))


def built_in_feature_registry() -> TransformRegistry:
    """A fresh immutable :class:`TransformRegistry` carrying exactly the
    built-in Feature registrations. The registry is frozen after
    construction: there is no register-after-construction, no ``replace``,
    and no way for a caller to inject an external registration."""
    return TransformRegistry(built_in_feature_registrations())
