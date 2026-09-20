"""Recorded L2 closure without association construction or execution."""

from ..cross_day import identity as ids
from ..cross_day.registry import admit_specs, built_in_cross_day_label_registry
from ..cross_day.schedule import admit_schedule
from ._artifact_canonical import _check, _ordered, _view
from ._artifact_records import _encode_record
from ._artifact_values import _value
from ._label_closure import verify_labels


def _label_closure(association_record, values_record, schedule_record, specs, pit, a3, builds, rows, cutoff):
    _encode_record(association_record, "CrossDayAssociation")
    _encode_record(values_record, "CrossDayValues")
    schedule = admit_schedule(_value(schedule_record), cutoff)
    admitted = admit_specs(specs, built_in_cross_day_label_registry())
    _check(bool(admitted) and tuple(s for s, _ in admitted) == specs, "Label spec order differs")
    feature_ids, label_ids = association_record.feature_build_ids, association_record.label_build_ids
    _ordered(feature_ids, lambda v: v, "Feature build roles")
    _ordered(label_ids, lambda v: v, "Label build roles")
    considered = tuple(b.canonical_build_id for b in builds)
    _check(tuple(sorted(set(feature_ids + label_ids))) == considered, "Canonical role union differs")
    _check(feature_ids == tuple(p.canonical_build_id for p in pit.canonical_build_pins),
           "Feature considered boundary differs")
    _check(association_record.dataset_as_of == cutoff, "L2 cutoff differs")
    decisions = tuple(_value(d) for d in association_record.decisions)
    bindings = tuple(_value(b) for b in association_record.sample_bindings)
    association = _view(feature_pit=pit, observation_pit=a3, schedule=schedule, label_specs=specs,
        dataset_as_of=cutoff, considered_canonical_build_ids=considered, decisions=decisions,
        sample_bindings=bindings, association_content_id=ids.association_content_id(
            schedule.pin, specs, considered, decisions, bindings))
    values = tuple(_value(v) for v in values_record.values)
    samples = []
    for binding in bindings:
        members = tuple(v for v in values if v.sample_key == binding.sample_key)
        ends = tuple(v.actual_label_end_time for v in members if v.actual_label_end_time is not None)
        samples.append(_view(sample_key=binding.sample_key, bar_sample_version_id=binding.bar_sample_version_id,
            multi_source_sample_version_id=binding.multi_source_sample_version_id, values=members,
            status="COMPLETE" if all(v.status == "COMPLETE" for v in members) else "INCOMPLETE",
            actual_label_end_time=max(ends) if ends else None))
    execution = _view(association=association, label_specs=specs,
        implementation_pins=tuple(_value(p) for p in values_record.implementation_pins),
        implementation_source_hashes=values_record.implementation_source_hashes,
        values=values, samples=tuple(samples), values_content_id=ids.values_content_id(values))
    verify_labels(association, execution, pit, a3, schedule, builds, rows, admitted, cutoff)
    return association, execution, schedule
