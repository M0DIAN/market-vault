"""Separate Cross-Day executor over exact schedule-bound Label decisions."""

from dataclasses import dataclass, replace

from ..dataset.encoding import DatasetError
from ..dataset.label_models import LabelTransformInput
from ..dataset.models import ImplementationPin
from ..dataset.specs import feature_label_spec_pin
from ._authority import reconcile
from ._validation import CrossDayLabelError, instant, require, scalar, sha256, typed_tuple
from .assembly import CrossDayLabelAssemblyResult
from .identity import label_spec_pin_id, schedule_pin_id, values_content_id
from .models import CrossDayLabelValueResult
from .registry import admit_specs, built_in_cross_day_label_registry


@dataclass(frozen=True)
class CrossDayLabelSampleResult:
    sample_key: str
    status: str
    actual_label_end_time: object

    def __post_init__(self):
        sha256(self.sample_key, "sample_key")
        require(self.status in ("COMPLETE", "INCOMPLETE"), "invalid sample status")
        require(self.status != "COMPLETE" or self.actual_label_end_time is not None, "COMPLETE sample requires end")
        if self.actual_label_end_time is not None:
            object.__setattr__(self, "actual_label_end_time", instant(self.actual_label_end_time, "actual_label_end_time"))


@dataclass(frozen=True)
class CrossDayLabelExecutionResult:
    association: CrossDayLabelAssemblyResult
    implementation_pins: tuple[ImplementationPin, ...]
    implementation_source_hashes: tuple[tuple[str, str], ...]
    values: tuple[CrossDayLabelValueResult, ...]

    def __post_init__(self):
        require(type(self.association) is CrossDayLabelAssemblyResult, "typed association required")
        association = replace(self.association)
        admitted = admit_specs(association.label_specs, built_in_cross_day_label_registry())
        pins = typed_tuple(self.implementation_pins, ImplementationPin, "implementation pins")
        require(type(self.implementation_source_hashes) is tuple
                and all(type(p) is tuple and len(p) == 2 for p in self.implementation_source_hashes),
                "immutable implementation source records required")
        sources = dict(self.implementation_source_hashes)
        require(len(sources) == len(self.implementation_source_hashes), "duplicate implementation source")
        expected_refs = {r.transform_ref for _, r in admitted}
        require(set(sources) == expected_refs, "implementation source cardinality mismatch")
        expected_pins = {}
        for _, registration in admitted:
            ref = registration.transform_ref
            source = sha256(sources[ref], "implementation source")
            require(source == registration.implementation_source_sha256, "fixed registry implementation source mismatch")
            expected_pins[ref] = registration.implementation_pin
        require(pins == tuple(expected_pins[r] for r in sorted(expected_pins)), "Cross-Day implementation pin mismatch")
        values = typed_tuple(self.values, CrossDayLabelValueResult, "values")
        require(len(values) == len(association.decisions), "value cardinality mismatch")
        by_spec = {label_spec_pin_id(s): (s, r) for s, r in admitted}
        versions = {b.sample_key: b.multi_source_sample_version_id for b in association.sample_bindings}
        for decision, value in zip(association.decisions, values):
            spec, contract = by_spec[decision.label_spec_pin_id]
            require(value.multi_source_sample_version_id == versions[decision.sample_key],
                    "A3 decision/value binding linkage mismatch")
            require((value.sample_key, value.bar_sample_version_id, value.spec_pin, value.implementation_pin,
                     value.schedule_pin_id, value.decision_id, value.anchor_canonical_row_version_id,
                     value.consumed_rows, value.status, value.reason_code, value.actual_label_end_time) ==
                    (decision.sample_key, decision.bar_sample_version_id, feature_label_spec_pin(spec),
                     expected_pins[contract.transform_ref], decision.schedule_pin_id, decision.decision_id,
                     None if decision.anchor is None else decision.anchor.canonical_row_version_id,
                     decision.selected_rows, decision.status, decision.reason_code, decision.actual_label_end_time),
                    "decision/value/spec/evidence linkage mismatch")
            if decision.status == "COMPLETE":
                scalar(value.value, contract.output_logical_type)
        object.__setattr__(self, "association", association)
        object.__setattr__(self, "implementation_pins", pins)
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "implementation_source_hashes", tuple(sorted(sources.items())))

    @property
    def schedule_pin(self):
        return self.association.schedule.pin

    @property
    def label_specs(self):
        return self.association.label_specs

    @property
    def decisions(self):
        return self.association.decisions

    @property
    def sample_bindings(self):
        return self.association.sample_bindings

    @property
    def association_content_id(self):
        return self.association.association_content_id

    @property
    def values_content_id(self):
        return values_content_id(self.values)

    @property
    def samples(self):
        result = []
        for binding in self.sample_bindings:
            values = tuple(v for v in self.values if v.sample_key == binding.sample_key)
            ends = tuple(v.actual_label_end_time for v in values if v.actual_label_end_time is not None)
            result.append(CrossDayLabelSampleResult(binding.sample_key,
                "COMPLETE" if all(v.status == "COMPLETE" for v in values) else "INCOMPLETE",
                max(ends) if ends else None))
        return tuple(result)


def execute_cross_day_labels(association: CrossDayLabelAssemblyResult) -> CrossDayLabelExecutionResult:
    """Revalidate the sidecar and invoke each COMPLETE decision exactly once."""
    try:
        require(type(association) is CrossDayLabelAssemblyResult, "requires CrossDayLabelAssemblyResult")
        registry = built_in_cross_day_label_registry()
        association = replace(association)
        admitted = admit_specs(association.label_specs, registry)
        by_spec = {label_spec_pin_id(s): (s, r) for s, r in admitted}
        builds = {b.canonical_build_id: b for b in association.feature_builds + association.label_builds}
        rows = reconcile(tuple(builds[k] for k in sorted(builds)))
        versions = {b.sample_key: b.multi_source_sample_version_id for b in association.sample_bindings}
        values = []
        for decision in association.decisions:
            spec, reg = by_spec[decision.label_spec_pin_id]
            value = None
            if decision.status == "COMPLETE":
                anchor = rows[decision.anchor.canonical_row_version_id].bar
                selected = tuple(rows[r.canonical_row_version_id].bar for r in decision.selected_rows)
                numeric = LabelTransformInput(
                    field_names=reg.input_fields,
                    anchor_row=tuple(getattr(anchor, f) for f in reg.input_fields),
                    rows=tuple(tuple(getattr(r, f) for f in reg.input_fields) for r in selected),
                    parameters=(), alignment_rule="FEATURE_CLOSE_ALIGNED")
                value = scalar(reg.implementation(numeric), reg.output_logical_type)
            values.append(CrossDayLabelValueResult(
                decision.sample_key, decision.bar_sample_version_id, versions[decision.sample_key], spec.name,
                feature_label_spec_pin(spec), reg.implementation_pin, schedule_pin_id(association.schedule.pin),
                decision.decision_id, None if decision.anchor is None else decision.anchor.canonical_row_version_id,
                decision.selected_rows, decision.status, value, decision.reason_code, decision.actual_label_end_time))
        used = {r.transform_ref: r for _, r in admitted}
        return CrossDayLabelExecutionResult(association,
            tuple(used[k].implementation_pin for k in sorted(used)),
            tuple((k, used[k].implementation_source_sha256) for k in sorted(used)), tuple(values))
    except CrossDayLabelError:
        raise
    except (DatasetError, ValueError, TypeError, OverflowError) as exc:
        raise CrossDayLabelError("Cross-Day execution failed: " + str(exc)) from exc


def validate_cross_day_execution_result(result: CrossDayLabelExecutionResult) -> CrossDayLabelExecutionResult:
    """Reverify logical closure and current built-in fingerprints without arithmetic."""
    require(type(result) is CrossDayLabelExecutionResult, "requires exact Cross-Day result")
    return replace(result)
