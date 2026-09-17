"""Closed Cross-Day registrations over the four unchanged pure Label formulas."""

from dataclasses import dataclass, replace

from ..canonical.schema import CANONICAL_SCHEMA_VERSION
from ..dataset.encoding import encode_identity
from ..dataset.label_transforms import (
    forward_return, forward_direction, maximum_favorable_excursion, maximum_adverse_excursion,
)
from ..dataset.models import ImplementationPin
from ..dataset.spec_models import LabelSpec
from ..dataset.specs import feature_label_spec_pin
from ..dataset.transform_models import _module_source_sha256
from ._validation import CrossDayLabelError, integer, require, typed_tuple

CROSS_DAY_SOURCE_SCHEMA_VERSION = "10.9-mv-ts2"
CROSS_DAY_LABEL_EXECUTION_CONTRACT_VERSION = "cross-day-label-execution-v1"
CROSS_DAY_LABEL_TRANSFORM_CALL_CONTRACT_VERSION = "cross-day-label-transform-call-v1"
BOUNDARY_RULE = "SAME_REQUESTED_SESSION_BAR_SLOT"


@dataclass(frozen=True)
class _LabelContract:
    transform_ref: str
    input_fields: tuple[str, ...]
    output_logical_type: str
    offset_shape: str
    implementation: object


@dataclass(frozen=True)
class CrossDayLabelRegistration(_LabelContract):
    implementation_source_sha256: str
    implementation_pin: ImplementationPin


def _contracts():
    return tuple(_LabelContract(f"{fn.__module__}:{fn.__name__}", fields, output, shape, fn)
                 for fn, fields, output, shape in (
        (forward_return, ("close",), "float64", "TARGET_ONLY"),
        (forward_direction, ("close",), "int64", "TARGET_ONLY"),
        (maximum_favorable_excursion, ("close", "high"), "float64", "ALIGNED_DAILY_POINTS"),
        (maximum_adverse_excursion, ("close", "low"), "float64", "ALIGNED_DAILY_POINTS")))


def implementation_payload(ref, source_hash, fields, output, shape):
    return dict(
        transform_ref=ref, implementation_version="v1", implementation_source_sha256=source_hash,
        execution_contract_version=CROSS_DAY_LABEL_EXECUTION_CONTRACT_VERSION,
        transform_call_contract_version=CROSS_DAY_LABEL_TRANSFORM_CALL_CONTRACT_VERSION,
        canonical_schema_version=CANONICAL_SCHEMA_VERSION, source_schema_version=CROSS_DAY_SOURCE_SCHEMA_VERSION,
        boundary_rule=BOUNDARY_RULE, window_unit="TRADING_DAYS", offset_shape=shape,
        input_count=len(fields), **{f"input_{i:04d}": f for i, f in enumerate(fields)},
        output_logical_type=output, output_nullable=False, parameter_count=0)


def built_in_cross_day_label_registry() -> tuple[CrossDayLabelRegistration, ...]:
    registrations = []
    for contract in _contracts():
        fn, fields, output, shape = (contract.implementation, contract.input_fields,
                                    contract.output_logical_type, contract.offset_shape)
        ref = contract.transform_ref
        try:
            source = _module_source_sha256(fn, ref)
        except (ValueError, TypeError, OSError) as exc:
            raise CrossDayLabelError("cannot obtain stable built-in implementation source") from exc
        fingerprint = encode_identity("cross-day-label-implementation-v1",
                                      implementation_payload(ref, source, fields, output, shape))
        registrations.append(CrossDayLabelRegistration(
            ref, fields, output, shape, fn, source, ImplementationPin(ref, "v1", fingerprint)))
    return tuple(sorted(registrations, key=lambda r: r.transform_ref))


def admit_specs(specs, registry=None):
    specs = typed_tuple(specs, LabelSpec, "label_specs")
    require(bool(specs), "at least one LabelSpec is required")
    require(len({s.name for s in specs}) == len(specs), "duplicate semantic Label name")
    registrations = {r.transform_ref: r for r in (_contracts() if registry is None else registry)}
    result = []
    for spec in specs:
        # Reconstruct nested records too; frozen dataclasses are not trust tokens.
        spec = replace(spec, output=replace(spec.output), requirements=replace(spec.requirements),
                       horizon=replace(spec.horizon), observation_window=replace(spec.observation_window),
                       cross_trading_day=replace(spec.cross_trading_day))
        reg = registrations.get(spec.transform_ref)
        require(reg is not None, "unregistered Cross-Day Label transform")
        n = integer(spec.horizon.value, "horizon", minimum=1)
        start = n - 1 if reg.offset_shape == "TARGET_ONLY" else 0
        require(spec.horizon.unit == spec.observation_window.unit == "TRADING_DAYS", "TRADING_DAYS only")
        require((spec.observation_window.start_offset, spec.observation_window.end_offset) == (start, n - 1),
                "unsupported Cross-Day offset shape")
        require(spec.cross_trading_day.allow is True and spec.cross_trading_day.boundary_rule == BOUNDARY_RULE,
                "explicit Cross-Day boundary opt-in required")
        require(spec.alignment_rule == "FEATURE_CLOSE_ALIGNED" and spec.missing_data_policy == "INCOMPLETE",
                "unsupported alignment or missing policy")
        require(spec.parameters == () and spec.input_canonical_fields == reg.input_fields,
                "exact built-in inputs and empty parameters required")
        require(spec.output.name == spec.name and spec.output.nullable is False
                and spec.output.logical_type == reg.output_logical_type, "output contract mismatch")
        require(spec.requirements.canonical_schema_versions == (CANONICAL_SCHEMA_VERSION,)
                and spec.requirements.source_schema_versions == (CROSS_DAY_SOURCE_SCHEMA_VERSION,),
                "Cross-Day requires exact TS2 Canonical authority")
        result.append((spec, reg))
    return tuple(sorted(result, key=lambda pair: encode_identity("dataset-spec", {
        "kind": "LABEL", "name": pair[0].name, "version": pair[0].version,
        "content_sha256": feature_label_spec_pin(pair[0]).content_sha256})))
