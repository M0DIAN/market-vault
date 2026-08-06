"""Shared built-in Label configuration contract (v0.6.0 PR-3 hardening).

The built-in Label executor (:mod:`market_vault.dataset.label_execution`)
and the Sample Generator core
(:mod:`market_vault.dataset.sample_generation_core`) share exactly one
full built-in Label spec configuration contract. Both run it for every
Label spec **before any sample is processed**, so the generator can never
emit a request that the formal executor would reject at configuration
preflight, and the two consumers cannot drift into two subtly different
implementations.

The contract (message-identical to the executor's historical preflight):

1. ``alignment_rule`` must be exactly
   :data:`market_vault.dataset.label_models.LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED`;
2. ``observation_window.end_offset == horizon.value - 1``;
3. the forward transforms additionally require
   ``start_offset == end_offset`` (only the horizon target row is
   required);
4. the excursion transforms require ``start_offset == 0`` (the full window
   from the first future bar);
5. ``transform_ref`` must belong to the fixed built-in catalog.

This module is **private**: it is never exported from
:mod:`market_vault.dataset`. It performs pure configuration validation of
frozen specs and registrations only: no files, no Canonical, no transform
execution, no PIT work, no current time, and no network / settings / OpenD.
All failures surface as :class:`LabelContractError`; each consumer converts
them to its own public error at its entry boundary, preserving the
``__cause__`` chain.
"""

from __future__ import annotations

from .encoding import DatasetError
from .label_models import LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED
from .spec_models import LabelSpec
from .transform_models import TransformRegistration

__all__ = ["LabelContractError", "validate_builtin_label_spec_contract"]


class LabelContractError(DatasetError):
    """Private fail-closed failure of the shared built-in Label
    configuration contract.

    Raised by :func:`validate_builtin_label_spec_contract`. Public
    consumers (the Label executor and the Sample Generator core) convert
    this error to their own public error at their entry boundary; it never
    leaks past a public API.
    """


#: Exact transform_ref values of the four built-in Label transforms.
_REF_FORWARD_RETURN = (
    "market_vault.dataset.label_transforms.forward_return:forward_return"
)
_REF_FORWARD_DIRECTION = (
    "market_vault.dataset.label_transforms.forward_direction:forward_direction"
)
_REF_MAXIMUM_FAVORABLE_EXCURSION = (
    "market_vault.dataset.label_transforms."
    "maximum_favorable_excursion:maximum_favorable_excursion"
)
_REF_MAXIMUM_ADVERSE_EXCURSION = (
    "market_vault.dataset.label_transforms."
    "maximum_adverse_excursion:maximum_adverse_excursion"
)

#: The fixed forward-transform shape group.
FORWARD_SHAPE_REFS = (_REF_FORWARD_RETURN, _REF_FORWARD_DIRECTION)

#: The fixed excursion-transform shape group.
EXCURSION_SHAPE_REFS = (
    _REF_MAXIMUM_FAVORABLE_EXCURSION,
    _REF_MAXIMUM_ADVERSE_EXCURSION,
)


def validate_builtin_label_spec_contract(
    spec: LabelSpec,
    registration: TransformRegistration,
) -> None:
    """Full built-in Label spec configuration contract of the catalog.

    Runs for every (spec, resolved) pair after Registry resolution and
    before any sample is processed (and therefore also for an empty sample
    set). A violation is a configuration-contract error and fails closed —
    it is never marked INCOMPLETE and never silently normalized.
    """
    if spec.alignment_rule != LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED:
        raise LabelContractError(
            f"label spec {spec.name!r} alignment_rule must be exactly "
            f"{LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED}, got "
            f"{spec.alignment_rule!r}; no other alignment rule is executed "
            "or silently normalized"
        )
    horizon = spec.horizon.value
    window = spec.observation_window
    if window.end_offset != horizon - 1:
        raise LabelContractError(
            f"label spec {spec.name!r} observation_window.end_offset "
            f"{window.end_offset} must equal horizon.value - 1 ({horizon - 1}) "
            "for every built-in Label transform"
        )
    if registration.transform_ref in FORWARD_SHAPE_REFS:
        if window.start_offset != horizon - 1:
            raise LabelContractError(
                f"label spec {spec.name!r} observation_window.start_offset "
                f"{window.start_offset} must equal horizon.value - 1 "
                f"({horizon - 1}) for the forward transform "
                f"{registration.transform_ref!r}: only the horizon target row "
                "is required"
            )
        return
    if registration.transform_ref in EXCURSION_SHAPE_REFS:
        if window.start_offset != 0:
            raise LabelContractError(
                f"label spec {spec.name!r} observation_window.start_offset "
                f"{window.start_offset} must be 0 for the excursion transform "
                f"{registration.transform_ref!r}: every future bar from "
                "offset 0 to the horizon target is required"
            )
        return
    raise LabelContractError(
        f"registration {registration.transform_ref!r} is not a supported "
        "built-in Label transform of this catalog"
    )
