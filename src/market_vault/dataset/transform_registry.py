"""Explicit immutable Transform Implementation Registry (v0.5.0 PR-2).

The registry is the sole resolution authority for the existing v1
``transform_ref`` values (``module.path:function``): it resolves a frozen
:class:`FeatureSpec` / :class:`LabelSpec` against exactly one registered
:class:`TransformRegistration` by the complete transform_ref string, runs
the strict compatibility preflight (kind, input contract with authoritative
field order, output type / nullability, supported canonical and source
schema versions, exact parameter-schema match with type / nullability /
bounds / allowed-values validation, and the v0.5 Label boundary gates),
and produces a :class:`ResolvedTransform` carrying the original frozen
spec, the immutable registration, the validated parameters in stable name
order, and the generated :class:`ImplementationPin`.

The registry is immutable after construction: registrations are frozen and
sorted by transform_ref, duplicate transform_ref values fail closed (even
when byte-identical), and there is no register-after-construction, no
``replace``, no global decorator registration, no import side-effect
registration, no package / entry-point / filesystem scanning, and no
network access. An empty registry is allowed and fails closed on every
resolve (unknown transform). Resolution never imports ``transform_ref`` and
never executes the implementation callable.

All failures surface as :class:`TransformRegistryError` (a subclass of
:class:`DatasetError`); no bare ``KeyError``, ``TypeError``, ``ValueError``,
or ``inspect`` exception leaks.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import SPEC_KIND_FEATURE, SPEC_KIND_LABEL
from .spec_models import FeatureSpec, LabelSpec, SpecParameter
from .transform_models import (
    PARAMETER_TYPE_BOOL,
    PARAMETER_TYPE_FLOAT64,
    PARAMETER_TYPE_INT64,
    PARAMETER_TYPE_STRING,
    ResolvedTransform,
    TransformParameterContract,
    TransformRegistration,
    TransformRegistryError,
    WINDOW_SOURCE_LABEL_HORIZON,
    WINDOW_SOURCE_LABEL_OBSERVATION_WINDOW,
    transform_implementation_pin,
)

__all__ = ["TransformRegistry"]

_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


@dataclass(frozen=True)
class TransformRegistry:
    """Immutable collection of transform registrations, keyed by the exact
    v1 ``transform_ref`` string (``module.path:function``).

    Construction normalizes the registrations to a deterministically sorted
    tuple by transform_ref and rejects duplicate transform_ref values — even
    when the two registrations are byte-identical, never silently
    overwriting. The registry is frozen; there is no mutation after
    construction and no lookup alias, case folding, or partial-name
    resolution.
    """

    registrations: tuple[TransformRegistration, ...]

    def __post_init__(self) -> None:
        items = tuple(self.registrations)
        for item in items:
            if not isinstance(item, TransformRegistration):
                raise TransformRegistryError(
                    "registry registrations must be TransformRegistration "
                    f"instances, got {type(item).__name__}"
                )
        items = tuple(sorted(items, key=lambda item: item.transform_ref))
        for previous, current in zip(items, items[1:]):
            if previous.transform_ref == current.transform_ref:
                raise TransformRegistryError(
                    f"duplicate transform_ref {current.transform_ref!r}; "
                    "duplicate registrations are never silently merged"
                )
        object.__setattr__(self, "registrations", items)

    def resolve_spec(self, spec) -> ResolvedTransform:
        """Resolve one frozen FeatureSpec or LabelSpec against this registry.

        The spec's ``transform_ref`` must exist in the registry exactly;
        then the full compatibility preflight runs (kind, input fields in
        the authoritative order, output logical type and nullability,
        supported canonical / source schema versions, exact parameter
        schema match, and the v0.5 Label boundary gates). The transform is
        never executed.
        """
        if isinstance(spec, FeatureSpec):
            kind = SPEC_KIND_FEATURE
        elif isinstance(spec, LabelSpec):
            kind = SPEC_KIND_LABEL
        else:
            raise TransformRegistryError(
                "resolve_spec requires a FeatureSpec or LabelSpec, "
                f"got {type(spec).__name__}"
            )
        registration = self._find(spec.transform_ref)
        if registration.kind != kind:
            raise TransformRegistryError(
                f"registration {registration.transform_ref!r} is a "
                f"{registration.kind} transform but the spec is a {kind} spec"
            )
        if spec.input_canonical_fields != registration.input_canonical_fields:
            raise TransformRegistryError(
                f"spec {spec.name!r} input canonical fields "
                f"{tuple(spec.input_canonical_fields)!r} do not match the "
                f"registration contract {registration.input_canonical_fields!r} "
                "(order is authoritative)"
            )
        if spec.output.logical_type != registration.output_logical_type:
            raise TransformRegistryError(
                f"spec {spec.name!r} output logical type "
                f"{spec.output.logical_type!r} does not match the registration "
                f"contract {registration.output_logical_type!r}"
            )
        if spec.output.nullable != registration.output_nullable:
            raise TransformRegistryError(
                f"spec {spec.name!r} output nullable {spec.output.nullable} "
                f"does not match the registration contract "
                f"{registration.output_nullable}"
            )
        _require_supported_versions(
            spec.name,
            "canonical_schema_versions",
            spec.requirements.canonical_schema_versions,
            registration.supported_canonical_schema_versions,
        )
        _require_supported_versions(
            spec.name,
            "source_schema_versions",
            spec.requirements.source_schema_versions,
            registration.supported_source_schema_versions,
        )
        parameters = _validate_spec_parameters(
            spec.name, spec.parameters, registration.parameters
        )
        if isinstance(spec, LabelSpec):
            _preflight_label_boundaries(spec)
        _preflight_window_requirements(spec, registration)
        return ResolvedTransform(
            spec=spec,
            registration=registration,
            parameters=parameters,
            pin=transform_implementation_pin(registration),
        )

    def resolve_feature_spec(self, spec: FeatureSpec) -> ResolvedTransform:
        """Typed FeatureSpec resolution; requires a FeatureSpec."""
        if not isinstance(spec, FeatureSpec):
            raise TransformRegistryError(
                "resolve_feature_spec requires a FeatureSpec, "
                f"got {type(spec).__name__}"
            )
        return self.resolve_spec(spec)

    def resolve_label_spec(self, spec: LabelSpec) -> ResolvedTransform:
        """Typed LabelSpec resolution; requires a LabelSpec."""
        if not isinstance(spec, LabelSpec):
            raise TransformRegistryError(
                "resolve_label_spec requires a LabelSpec, "
                f"got {type(spec).__name__}"
            )
        return self.resolve_spec(spec)

    def _find(self, transform_ref: str) -> TransformRegistration:
        """Exact-key lookup; no import, no alias, no case folding, no partial
        names."""
        for registration in self.registrations:
            if registration.transform_ref == transform_ref:
                return registration
        raise TransformRegistryError(
            f"unknown transform_ref {transform_ref!r}; the registry contains "
            "no such registration"
        )


# ---------------------------------------------------------------------------
# Preflight rules.
# ---------------------------------------------------------------------------


def _require_supported_versions(
    spec_name: str,
    label: str,
    required: tuple[str, ...],
    supported: tuple[str, ...],
) -> None:
    """Every required version must be supported; the registration may
    support more versions — the spec is never modified to match."""
    supported_set = set(supported)
    unsupported = [version for version in required if version not in supported_set]
    if unsupported:
        raise TransformRegistryError(
            f"spec {spec_name!r} requires unsupported {label}: "
            f"{', '.join(unsupported)}"
        )


def _validate_spec_parameters(
    spec_name: str,
    spec_parameters: tuple[SpecParameter, ...],
    contracts: tuple[TransformParameterContract, ...],
) -> tuple[SpecParameter, ...]:
    """Exact parameter-set match plus per-value contract validation.

    Missing parameters (declared by the registration but absent from the
    spec) and unknown parameters (declared by the spec but not by the
    registration) fail closed; duplicates are already rejected by the spec
    model. The returned tuple holds the spec's own parameters in stable
    name order; the frozen spec is never modified and no implicit default
    is invented.
    """
    schema_names = [contract.name for contract in contracts]
    spec_names = [parameter.name for parameter in spec_parameters]
    if spec_names != schema_names:
        missing = sorted(name for name in schema_names if name not in spec_names)
        unknown = sorted(name for name in spec_names if name not in schema_names)
        raise TransformRegistryError(
            f"spec {spec_name!r} parameter set must match the registration "
            f"parameter schema exactly; missing {missing}, unknown {unknown}"
        )
    result: list[SpecParameter] = []
    for parameter in spec_parameters:
        contract = next(
            contract for contract in contracts if contract.name == parameter.name
        )
        _validate_parameter_value(contract, parameter.value)
        result.append(parameter)
    return tuple(result)


def _validate_parameter_value(
    contract: TransformParameterContract, value
) -> None:
    """Exact type / nullability / bounds / allowed-values validation of one
    spec parameter value against its contract (fail closed)."""
    label = f"parameter {contract.name!r}"
    if value is None:
        if not contract.nullable:
            raise TransformRegistryError(
                f"spec {label} is null but the contract is not nullable"
            )
        return
    if contract.value_type == PARAMETER_TYPE_BOOL:
        if type(value) is not bool:
            raise TransformRegistryError(
                f"spec {label} must be a real bool, got {type(value).__name__}; "
                "bool is never treated as int and int is never treated as bool"
            )
    elif contract.value_type == PARAMETER_TYPE_INT64:
        if type(value) is not int:
            raise TransformRegistryError(
                f"spec {label} must be a real int64 value, "
                f"got {type(value).__name__}"
            )
        if not _INT64_MIN <= value <= _INT64_MAX:
            raise TransformRegistryError(
                f"spec {label} must be within signed int64 range, got {value}"
            )
        _require_numeric_bounds(contract, value)
    elif contract.value_type == PARAMETER_TYPE_FLOAT64:
        if type(value) is not float:
            raise TransformRegistryError(
                f"spec {label} must be a real finite float64 value, "
                f"got {type(value).__name__}"
            )
        # SpecParameter already rejects NaN / infinities; re-check for safety.
        if value != value or value in (float("inf"), float("-inf")):
            raise TransformRegistryError(
                f"spec {label} NaN and positive/negative infinity are rejected"
            )
        _require_numeric_bounds(contract, value)
    else:
        if not isinstance(value, str):
            raise TransformRegistryError(
                f"spec {label} must be a string, got {type(value).__name__}"
            )
    if contract.allowed_values is not None and value not in contract.allowed_values:
        raise TransformRegistryError(
            f"spec {label} value {value!r} is not one of the allowed values "
            f"{tuple(contract.allowed_values)!r}"
        )


def _require_numeric_bounds(
    contract: TransformParameterContract, value
) -> None:
    """Inclusive numeric bounds; bound checks are exact."""
    if contract.lower_bound is not None and value < contract.lower_bound:
        raise TransformRegistryError(
            f"spec parameter {contract.name!r} value {value!r} is below the "
            f"contract lower bound {contract.lower_bound!r}"
        )
    if contract.upper_bound is not None and value > contract.upper_bound:
        raise TransformRegistryError(
            f"spec parameter {contract.name!r} value {value!r} exceeds the "
            f"contract upper bound {contract.upper_bound!r}"
        )


def _preflight_label_boundaries(spec: LabelSpec) -> None:
    """v0.5 execution-scope gates: a TRADING_DAYS horizon and any explicit
    cross-trading-day opt-in fail closed as unsupported. Configuration
    preflight only; no label window is assembled and no ``label_status`` is
    produced."""
    if spec.cross_trading_day.allow:
        raise TransformRegistryError(
            f"label spec {spec.name!r} sets cross_trading_day.allow=true, "
            "which is unsupported in the v0.5 execution scope; resolve fails "
            "closed"
        )
    if spec.horizon.unit == "TRADING_DAYS":
        raise TransformRegistryError(
            f"label spec {spec.name!r} uses a TRADING_DAYS horizon, which is "
            "unsupported in the v0.5 execution scope; resolve fails closed"
        )


def _preflight_window_requirements(
    spec, registration: TransformRegistration
) -> None:
    """Spec-level window-requirement preflight: a Label-derived lookforward
    requirement must agree with the LabelSpec's own declared unit. Nothing
    is computed here and no PIT row is read."""
    if (
        registration.lookforward.source == WINDOW_SOURCE_LABEL_HORIZON
        and isinstance(spec, LabelSpec)
        and registration.lookforward.unit != spec.horizon.unit
    ):
        raise TransformRegistryError(
            f"registration {registration.transform_ref!r} lookforward requires "
            f"unit {registration.lookforward.unit} but the label spec "
            f"{spec.name!r} declares horizon unit {spec.horizon.unit!r}"
        )
    if (
        registration.lookforward.source == WINDOW_SOURCE_LABEL_OBSERVATION_WINDOW
        and isinstance(spec, LabelSpec)
        and registration.lookforward.unit != spec.observation_window.unit
    ):
        raise TransformRegistryError(
            f"registration {registration.transform_ref!r} lookforward requires "
            f"unit {registration.lookforward.unit} but the label spec "
            f"{spec.name!r} declares observation window unit "
            f"{spec.observation_window.unit!r}"
        )
