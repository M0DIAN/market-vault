"""Built-in immutable Label transform registrations (v0.5.0 PR-4).

This module declares the fixed set of built-in Label registrations and the
immutable registry that carries them. The executor
(:mod:`market_vault.dataset.label_execution`) resolves LabelSpecs only
against this built-in registry, so a caller can never make the executor run
an arbitrary function.

``built_in_label_registrations`` returns the same deterministic tuple of
:class:`TransformRegistration` instances on every call (sorted by
``transform_ref``); ``built_in_label_registry`` returns a fresh immutable
:class:`TransformRegistry` over them. There is no import side effect, no
decorator registration, no mutable global registry, no package / entry-point
/ filesystem scanning, no alias, no ``replace``, and no network access. The
registrations are constructed once per call from the already-imported
transform functions; each registration's implementation fingerprint is the
construction-time snapshot of that transform module's normalized source, so
one transform's source change only churns that transform's pin.

This PR executes **BARS only** horizons and observation windows. The PR-2
registry preflight already fails closed on ``TRADING_DAYS`` horizons and on
``cross_trading_day.allow == true``; a ``MINUTES`` spec fails closed at
resolve time because these registrations declare BARS-only lookforward
requirements (the PR-2 window-requirement unit match is unchanged — no
registry contract is modified to support multiple units).
"""

from __future__ import annotations

from ..canonical.schema import CANONICAL_SCHEMA_VERSION
from .label_transforms import (
    forward_direction,
    forward_return,
    maximum_adverse_excursion,
    maximum_favorable_excursion,
)
from .models import SPEC_KIND_LABEL
from .transform_models import (
    BOUNDARY_POLICY_NO_CROSS_TRADING_DAY,
    MISSING_POLICY_LABEL_INCOMPLETE,
    TransformRegistration,
    TransformWindowRequirement,
    WINDOW_BOUNDARY_INCLUSIVE,
    WINDOW_SOURCE_FIXED,
    WINDOW_SOURCE_LABEL_HORIZON,
    WINDOW_SOURCE_LABEL_OBSERVATION_WINDOW,
    WINDOW_UNIT_BARS,
)
from .transform_registry import TransformRegistry

__all__ = [
    "built_in_label_registrations",
    "built_in_label_registry",
]

#: Canonical schema versions the built-in Label registrations support. The
#: current authoritative Canonical bars schema version is the only supported
#: one; no wildcard or version placeholder is ever used.
SUPPORTED_CANONICAL_SCHEMA_VERSIONS = (CANONICAL_SCHEMA_VERSION,)

#: Source schema versions the built-in Label registrations support: the
#: codebase's current authoritative source schema version (the ``Settings``
#: default, ``"10.9"``). No wildcard or version placeholder is ever used.
SUPPORTED_SOURCE_SCHEMA_VERSIONS = ("10.9",)

#: Implementation version of every built-in Label transform in this catalog.
_IMPLEMENTATION_VERSION = "v1"

#: The fixed 1-bar lookback of every built-in Label transform: the exact
#: Feature-close anchor row only. Future Label rows come from the
#: lookforward requirement, never from the lookback.
_FIXED_ONE_BAR_LOOKBACK = TransformWindowRequirement(
    source=WINDOW_SOURCE_FIXED,
    unit=WINDOW_UNIT_BARS,
    value=1,
    parameter_name=None,
    boundary=WINDOW_BOUNDARY_INCLUSIVE,
)

#: The LabelSpec's own horizon, in bars, inclusive.
_HORIZON_LOOKFORWARD = TransformWindowRequirement(
    source=WINDOW_SOURCE_LABEL_HORIZON,
    unit=WINDOW_UNIT_BARS,
    value=None,
    parameter_name=None,
    boundary=WINDOW_BOUNDARY_INCLUSIVE,
)

#: The LabelSpec's own observation window, in bars, inclusive.
_OBSERVATION_WINDOW_LOOKFORWARD = TransformWindowRequirement(
    source=WINDOW_SOURCE_LABEL_OBSERVATION_WINDOW,
    unit=WINDOW_UNIT_BARS,
    value=None,
    parameter_name=None,
    boundary=WINDOW_BOUNDARY_INCLUSIVE,
)


def _registration(
    *,
    transform_ref: str,
    implementation,
    input_canonical_fields: tuple[str, ...],
    output_logical_type: str,
    lookforward: TransformWindowRequirement,
    display_name: str,
) -> TransformRegistration:
    """One built-in Label registration with the fixed shared metadata:
    kind LABEL, implementation version ``v1``, the current authoritative
    canonical/source schema versions, non-nullable output, a FIXED 1-bar
    INCLUSIVE lookback, NO_CROSS_TRADING_DAY boundary policy, and
    LABEL_INCOMPLETE missing policy. No parameters are declared."""
    return TransformRegistration(
        transform_ref=transform_ref,
        kind=SPEC_KIND_LABEL,
        implementation_version=_IMPLEMENTATION_VERSION,
        implementation=implementation,
        input_canonical_fields=input_canonical_fields,
        supported_canonical_schema_versions=SUPPORTED_CANONICAL_SCHEMA_VERSIONS,
        supported_source_schema_versions=SUPPORTED_SOURCE_SCHEMA_VERSIONS,
        output_logical_type=output_logical_type,
        output_nullable=False,
        parameters=(),
        lookback=_FIXED_ONE_BAR_LOOKBACK,
        lookforward=lookforward,
        boundary_policy=BOUNDARY_POLICY_NO_CROSS_TRADING_DAY,
        missing_policy=MISSING_POLICY_LABEL_INCOMPLETE,
        display_name=display_name,
    )


def built_in_label_registrations() -> tuple[TransformRegistration, ...]:
    """The fixed tuple of built-in Label registrations, deterministically
    sorted by ``transform_ref``. Every call returns an equal tuple; no
    global mutable registry is created."""
    registrations = (
        _registration(
            transform_ref="market_vault.dataset.label_transforms.forward_return:forward_return",
            implementation=forward_return,
            input_canonical_fields=("close",),
            output_logical_type="float64",
            lookforward=_HORIZON_LOOKFORWARD,
            display_name="Forward close-to-close return to the horizon target",
        ),
        _registration(
            transform_ref="market_vault.dataset.label_transforms.forward_direction:forward_direction",
            implementation=forward_direction,
            input_canonical_fields=("close",),
            output_logical_type="int64",
            lookforward=_HORIZON_LOOKFORWARD,
            display_name="Signed forward direction of the close move",
        ),
        _registration(
            transform_ref="market_vault.dataset.label_transforms.maximum_favorable_excursion:maximum_favorable_excursion",
            implementation=maximum_favorable_excursion,
            input_canonical_fields=("close", "high"),
            output_logical_type="float64",
            lookforward=_OBSERVATION_WINDOW_LOOKFORWARD,
            display_name="Maximum favorable long excursion over the observation window",
        ),
        _registration(
            transform_ref="market_vault.dataset.label_transforms.maximum_adverse_excursion:maximum_adverse_excursion",
            implementation=maximum_adverse_excursion,
            input_canonical_fields=("close", "low"),
            output_logical_type="float64",
            lookforward=_OBSERVATION_WINDOW_LOOKFORWARD,
            display_name="Maximum adverse signed long excursion over the observation window",
        ),
    )
    return tuple(sorted(registrations, key=lambda item: item.transform_ref))


def built_in_label_registry() -> TransformRegistry:
    """A fresh immutable :class:`TransformRegistry` carrying exactly the
    built-in Label registrations. The registry is frozen after
    construction: there is no register-after-construction, no ``replace``,
    and no way for a caller to inject an external registration."""
    return TransformRegistry(built_in_label_registrations())
