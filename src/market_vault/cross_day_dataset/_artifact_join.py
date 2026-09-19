"""Read-only artifact join projection; no upstream result issuance."""

from types import MappingProxyType

from ..cross_day import identity as label_ids
from ..dataset import split_models as splits
from ..dataset.content import dataset_schema_id, logical_dataset_content_id
from ..dataset.encoding import encode_identity
from ..dataset.models import DatasetField, DatasetSchema
from ..multi_source.feature_spec_models import normalize_specs
from ._artifact_canonical import _canonical_closure, _pit_closure, _check, _ordered, _view, _INTERVALS
from ._artifact_labels import _label_closure
from ._artifact_observation import _observation_closure, _observation_features_closure
from ._artifact_records import _encode_record
from ._artifact_ts2 import _ts2_closure
from ._artifact_values import _value
from .closure import RESERVED_NAMES
from .models import MultiSourceCrossDaySampleAudit, MultiSourceCrossDayCompletionEntry, MultiSourceCrossDayCompletionSummary


_SPLIT_COLUMNS = ("feature_window_close_date", "nominal_split", "final_split", "assignment_status", "reason_code", "purge_boundary")


def _split_closure(record, spec, pit, ts2, a3, obs, labels):
    _encode_record(record, "ChronologicalSplitResult")
    _check(_value(record.split_spec) == spec and _value(record.split_spec_pin) == splits.chronological_split_spec_pin(spec),
           "split spec/pin differs")
    _check(record.splitter_version == splits.CHRONOLOGICAL_SPLITTER_VERSION, "splitter contract differs")
    assignments = tuple(_value(a) for a in record.assignments)
    _ordered(assignments, lambda a: a.sample_key, "split assignments")
    eligible = tuple(k for k in sorted(pit) if ts2[k].status == obs[k].status == "COMPLETE")
    _check(tuple(a.sample_key for a in assignments) == eligible, "split assignment membership differs")
    train = splits._next_local_midnight_utc(spec.train_end_date, spec.boundary_timezone)
    validation = splits._next_local_midnight_utc(spec.validation_end_date, spec.boundary_timezone)
    for assignment in assignments:
        key = assignment.sample_key
        expected = splits._expected_split_assignment(sample_key=key,
            sample_version_id=a3[key].multi_source_sample_version_id,
            feature_window_close=pit[key].request.feature_window_close,
            label_status=labels[key].status, actual_label_end_time=labels[key].actual_label_end_time,
            spec=spec, train_boundary=train, validation_boundary=validation)
        _check(assignment == expected, "recorded split policy or upstream linkage differs")
    schema = splits.split_assignment_schema()
    rows = splits._assignment_rows(assignments)
    _check(_value(record.assignment_schema) == schema and record.assignment_schema_id == dataset_schema_id(schema),
           "split schema differs")
    _check(tuple(dict(r._items) for r in record.assignment_rows) == rows, "split row projection differs")
    content_id = logical_dataset_content_id(schema, rows)
    result_id = splits.chronological_split_result_id(splitter_version=record.splitter_version,
        split_spec_content_id=record.split_spec_pin.content_sha256, assignment_schema_id=record.assignment_schema_id,
        assignment_content_id=content_id, sample_count=len(assignments))
    _check(record.assignment_content_id == content_id and record.split_result_id == result_id,
           "split identity differs")
    _check(_value(record.diagnostics) == splits._derive_diagnostics(assignments), "split diagnostics differ")
    return _view(split_spec=spec, split_spec_pin=_value(record.split_spec_pin), assignments=assignments,
                 split_result_id=result_id, assignment_schema=schema, assignment_content_id=content_id,
                 assignment_rows=tuple(MappingProxyType(r) for r in rows),
                 assignment_schema_id=record.assignment_schema_id, splitter_version=record.splitter_version,
                 diagnostics=_value(record.diagnostics))


def _project(scope, cutoff, pit, ts2, a3, obs, labels, association, schedule, obs_specs, split):
    fields = [DatasetField(n, t, null) for n, t, null in (
        ("code", "string", False), ("sample_key", "string", False), ("sample_version_id", "string", False),
        ("feature_window_close", "timestamp_us_utc", False), ("actual_label_end_time", "timestamp_us_utc", True),
        ("label_status", "string", False))]
    if cutoff is not None:
        fields.append(DatasetField("dataset_as_of", "timestamp_us_utc", False))
    for specs, nullable in ((ts2.feature_specs, False), (obs_specs, False), (labels.label_specs, True)):
        fields.extend(DatasetField(s.name, s.output.logical_type, nullable) for s in specs)
    fields.extend(DatasetField(n, t, null) for n, t, null in zip(_SPLIT_COLUMNS,
        ("date32", "string", "string", "string", "string", "timestamp_us_utc"), (False, True, True, False, True, True)))
    schema = DatasetSchema(tuple(fields))
    p, t, a, o, l = ({s.sample_key: s for s in seq} for seq in
        (pit.samples, ts2.samples, a3.sample_bindings, obs.samples, labels.samples))
    assignments = {s.sample_key: s for s in split.assignments}
    bindings = {b.sample_key: b for b in association.sample_bindings}
    audits, rows = [], []
    for key in sorted(p):
        sample, req = p[key], p[key].request
        eligible = t[key].status == o[key].status == "COMPLETE"
        values = l[key].values
        audits.append(MultiSourceCrossDaySampleAudit(key, sample.sample_version_id, a[key].multi_source_sample_version_id,
            req.code, req.interval, req.adjustment, req.requested_session, req.anchor_market_calendar_date,
            req.feature_window_start, req.feature_window_close, cutoff, pit.association_schema_id, pit.association_content_id,
            t[key].sample_id, t[key].values_content_id, a[key].observation_binding_id, o[key].values_content_id,
            bindings[key].sample_binding_id, label_ids.values_content_id(values), label_ids.schedule_pin_id(schedule.pin),
            t[key].status, o[key].status, l[key].status, l[key].actual_label_end_time, eligible, eligible,
            *(getattr(assignments[key], n) if eligible else None for n in _SPLIT_COLUMNS)))
        if eligible:
            row = dict(code=req.code, sample_key=key, sample_version_id=a[key].multi_source_sample_version_id,
                       feature_window_close=req.feature_window_close, actual_label_end_time=l[key].actual_label_end_time,
                       label_status=l[key].status)
            if cutoff is not None:
                row["dataset_as_of"] = cutoff
            row.update((v.feature_name, v.value) for v in t[key].values + o[key].values)
            row.update((v.label_name, v.value) for v in values)
            row.update((n, getattr(assignments[key], n)) for n in _SPLIT_COLUMNS)
            rows.append(tuple(row[f.name] for f in fields))
    rows.sort(key=lambda r: (r[0], r[3], r[1]))
    entries = []
    for symbol in scope.symbols:
        for day in scope.trade_dates:
            keys = tuple(k for k, s in p.items() if s.request.code == symbol and s.request.anchor_market_calendar_date == day)
            te = any(t[k].status == "EXCLUDED" for k in keys)
            oe = any(o[k].status == "EXCLUDED" for k in keys)
            li = any(l[k].status == "INCOMPLETE" for k in keys)
            reason = ("NO_SAMPLE_REQUEST" if not keys else
                "FEATURE_EXCLUDED_AND_CROSS_DAY_LABEL_INCOMPLETE" if (te or oe) and li else
                "TS2_AND_OBSERVATION_FEATURE_EXCLUDED" if te and oe else "TS2_FEATURE_EXCLUDED" if te else
                "OBSERVATION_FEATURE_EXCLUDED" if oe else "CROSS_DAY_LABEL_INCOMPLETE" if li else None)
            entries.append(MultiSourceCrossDayCompletionEntry(symbol, day,
                "MISSING" if not keys else "INCOMPLETE" if reason else "COMPLETE", reason))
    completion = MultiSourceCrossDayCompletionSummary(
        *(sum(e.status == s for e in entries) for s in ("COMPLETE", "INCOMPLETE", "MISSING")), tuple(entries))
    return schema, tuple(rows), tuple(audits), completion


def _recorded_closure(*, scope, cutoff, sidecars, observation_specs, label_specs, split_spec):
    """Validate declarations, never create a live Dataset/upstream result."""
    _check(scope.symbols and scope.trade_dates and all(s.startswith("US.") for s in scope.symbols)
           and scope.interval in _INTERVALS and scope.adjustment == "NONE" and scope.requested_session == "RTH",
           "unsupported artifact scope")
    def one(name):
        values = sidecars[name]
        _check(len(values) == 1, "singleton required: " + name)
        return values[0]
    association_record = one("cross_day_association.json")
    builds, pins, gaps, all_rows = _canonical_closure(sidecars["canonical_evidence.json"], scope)
    features = tuple(b for b in builds if b.canonical_build_id in association_record.feature_build_ids)
    _, feature_pins, feature_gaps, feature_rows = _canonical_closure(features, scope)
    pit = _pit_closure(one("feature_pit.json"), features, feature_pins, feature_gaps, feature_rows, scope, cutoff)
    ts2 = _ts2_closure(one("ts2_features.json"), pit, features, feature_rows, cutoff)
    _check(bool(ts2.feature_specs), "TS2 specs must be nonempty")
    observation_specs = normalize_specs(observation_specs)
    _check(bool(observation_specs), "Observation specs must be nonempty")
    a3, proofs, selected = _observation_closure(one("observation_pit.json"), sidecars["observation_evidence.json"],
                                               observation_specs, pit)
    obs = _observation_features_closure(one("observation_features.json"), observation_specs, a3, selected)
    association, labels, schedule = _label_closure(association_record, one("cross_day_values.json"),
        one("schedule.json"), label_specs, pit, a3, builds, all_rows, cutoff)
    names = tuple(s.name for s in ts2.feature_specs + observation_specs + label_specs)
    _check(len(set(names)) == len(names) and not set(names) & RESERVED_NAMES, "output name collision")
    maps = tuple({s.sample_key: s for s in seq} for seq in
        (pit.samples, ts2.samples, a3.sample_bindings, obs.samples, labels.samples))
    _check(all(tuple(m) == tuple(maps[0]) for m in maps), "common sample closure differs")
    split = _split_closure(one("split.json"), split_spec, *maps)
    schema, rows, audits, completion = _project(scope, cutoff, pit, ts2, a3, obs, labels, association,
                                               schedule, observation_specs, split)
    _check(tuple(_value(a) for a in sidecars["sample_audit.json"]) == audits, "recorded audit differs")
    return _view(scope=scope, dataset_as_of=cutoff, schema=schema, rows=rows, sample_audit=audits, completion=completion,
        split_result=split, feature_pit=pit, ts2_features=ts2, observation_pit=a3, observation_features=obs,
        cross_day_association=association, cross_day_labels=labels, schedule=schedule, canonical_builds=builds,
        canonical_build_pins=pins, gap_references=gaps, observation_input_proofs=proofs,
        observation_builds=sidecars["observation_evidence.json"],
        observation_feature_specs=observation_specs)
