"""One pure live join over recorded upstream facts; exactly one split invocation."""

from dataclasses import dataclass, fields, replace
from datetime import datetime
from types import MappingProxyType

from ..cross_day import identity as label_ids
from ..cross_day.assembly import CrossDayLabelAssemblyResult
from ..cross_day.execution import CrossDayLabelExecutionResult
from ..cross_day.schedule import VerifiedTradingDaySchedule
from ..dataset.encoding import encode_identity
from ..canonical.reader import VerifiedCanonicalBuild
from ..dataset.models import DatasetScope, DatasetSchema, DatasetField, CanonicalBuildPin, GapReference
from ..dataset.pit_models import PITAssemblyResult
from ..dataset.split_models import ChronologicalSplitSpec, ChronologicalSplitSample, ChronologicalSplitResult
from ..dataset.splits import assign_chronological_splits
from ..multi_source.feature_models import ObservationFeatureExecutionResult
from ..multi_source.feature_spec_models import ObservationFeatureSpec
from ..multi_source.feature_specs import observation_feature_spec_pin
from ..multi_source.feature_identity import observation_feature_value_id
from ..observation.artifact_models import VerifiedObservationBuild
from ..observation.pit_models import ObservationPITAssemblyResult, ObservationBuildPin
from ..observation.pit_identity import feature_spec_pin_id, observation_build_pin_id
from ..ts2_feature.models import TS2FeatureExecutionResult
from .closure import admit_inputs, _logical_build
from .identity import MULTI_SOURCE_CROSS_DAY_DATASET_ID_VERSION, _payload
from .models import (
    MultiSourceCrossDayDatasetResult, MultiSourceCrossDayDatasetIdentityInput,
    MultiSourceCrossDaySampleAudit, MultiSourceCrossDayCompletionEntry, MultiSourceCrossDayCompletionSummary,
)
from ._validation import checked_record, numeric, records, require, require_immutable, stage


SPLIT_COLUMNS = ("feature_window_close_date", "nominal_split", "final_split",
                 "assignment_status", "reason_code", "purge_boundary")


def _sample_maps(admitted):
    return tuple({s.sample_key: s for s in values} for values in (
        admitted.feature_pit.samples, admitted.ts2_features.samples, admitted.observation_pit.sample_bindings,
        admitted.observation_features.samples, admitted.cross_day_labels.samples))


def _split_samples(admitted):
    pit, ts2, a3, obs, labels = _sample_maps(admitted)
    return tuple(ChronologicalSplitSample(k, a3[k].multi_source_sample_version_id, pit[k].request.feature_window_close,
                                         labels[k].status, labels[k].actual_label_end_time)
                 for k in sorted(pit) if ts2[k].status == obs[k].status == "COMPLETE")


def _validated_split(admitted, value):
    with stage("SPLIT_BINDING"):
        checked_record(value, ChronologicalSplitResult, "SPLIT_BINDING")
        require(value.split_spec == admitted.split_spec, "SPLIT_BINDING", "split spec mismatch")
        expected = _split_samples(admitted)
        actual = tuple(ChronologicalSplitSample(a.sample_key, a.sample_version_id, a.feature_window_close,
                                                a.label_status, a.actual_label_end_time) for a in value.assignments)
        require(actual == expected, "SPLIT_BINDING", "split inputs differ from Feature-eligible L2/A3 facts")
        copy = replace(value)
        # Detach the legacy split's mutable row dictionaries without changing its semantics.
        object.__setattr__(copy, "assignment_rows", tuple(MappingProxyType(dict(r)) for r in copy.assignment_rows))
        return copy


def _schema(admitted):
    fields_ = [DatasetField(n, t, nullable) for n, t, nullable in (
        ("code", "string", False), ("sample_key", "string", False), ("sample_version_id", "string", False),
        ("feature_window_close", "timestamp_us_utc", False), ("actual_label_end_time", "timestamp_us_utc", True),
        ("label_status", "string", False))]
    if admitted.dataset_as_of is not None:
        fields_.append(DatasetField("dataset_as_of", "timestamp_us_utc", False))
    observation_specs = tuple(sorted(admitted.observation_feature_specs,
        key=lambda s: feature_spec_pin_id(observation_feature_spec_pin(s))))
    for family, nullable in ((admitted.ts2_features.feature_specs, False), (observation_specs, False),
                             (admitted.cross_day_labels.label_specs, True)):
        fields_.extend(DatasetField(s.name, s.output.logical_type, nullable) for s in family)
    fields_.extend(DatasetField(n, t, nullable) for n, t, nullable in zip(SPLIT_COLUMNS,
        ("date32", "string", "string", "string", "string", "timestamp_us_utc"), (False, True, True, False, True, True)))
    return DatasetSchema(tuple(fields_))


def _project(admitted, split):
    pit, ts2, a3, obs, labels = _sample_maps(admitted)
    bindings = {b.sample_key: b for b in admitted.cross_day_association.sample_bindings}
    assignment = {a.sample_key: a for a in split.assignments}
    schema = _schema(admitted)
    audits, rows = [], []
    for key in sorted(pit):
        sample, t, o, label = pit[key], ts2[key], obs[key], labels[key]
        req = sample.request
        values = tuple(v for v in admitted.cross_day_labels.values if v.sample_key == key)
        eligible = t.status == o.status == "COMPLETE"
        obs_ids = tuple(observation_feature_value_id(v) for v in sorted(o.values, key=lambda v: feature_spec_pin_id(v.spec_pin)))
        audit = MultiSourceCrossDaySampleAudit(
            key, sample.sample_version_id, a3[key].multi_source_sample_version_id, req.code, req.interval,
            req.adjustment, req.requested_session, req.anchor_market_calendar_date, req.feature_window_start,
            req.feature_window_close, admitted.dataset_as_of, admitted.feature_pit.association_schema_id,
            admitted.feature_pit.association_content_id, t.sample_id, t.values_content_id, a3[key].observation_binding_id,
            encode_identity("observation-feature-values-v1", dict(count=len(obs_ids), members="".join(obs_ids))),
            bindings[key].sample_binding_id, label_ids.values_content_id(values), label_ids.schedule_pin_id(admitted.schedule.pin),
            t.status, o.status, label.status, label.actual_label_end_time, eligible, eligible,
            *(getattr(assignment[key], name) if eligible else None for name in SPLIT_COLUMNS))
        audits.append(audit)
        if eligible:
            row = dict(code=req.code, sample_key=key, sample_version_id=a3[key].multi_source_sample_version_id,
                       feature_window_close=req.feature_window_close, actual_label_end_time=label.actual_label_end_time,
                       label_status=label.status)
            if admitted.dataset_as_of is not None:
                row["dataset_as_of"] = admitted.dataset_as_of
            row.update((v.feature_name, v.value) for v in t.values + o.values)
            row.update((v.label_name, v.value) for v in values)
            row.update((n, getattr(assignment[key], n)) for n in SPLIT_COLUMNS)
            rows.append(tuple(row[f.name] for f in schema.fields))
    rows.sort(key=lambda r: (r[0], r[3], r[1]))
    entries = []
    for symbol in admitted.scope.symbols:
        for day in admitted.scope.trade_dates:
            members = tuple(k for k, s in pit.items() if s.request.code == symbol and s.request.anchor_market_calendar_date == day)
            t = any(ts2[k].status == "EXCLUDED" for k in members)
            o = any(obs[k].status == "EXCLUDED" for k in members)
            l = any(labels[k].status == "INCOMPLETE" for k in members)
            reason = ("NO_SAMPLE_REQUEST" if not members else
                      "FEATURE_EXCLUDED_AND_CROSS_DAY_LABEL_INCOMPLETE" if (t or o) and l else
                      "TS2_AND_OBSERVATION_FEATURE_EXCLUDED" if t and o else
                      "TS2_FEATURE_EXCLUDED" if t else "OBSERVATION_FEATURE_EXCLUDED" if o else
                      "CROSS_DAY_LABEL_INCOMPLETE" if l else None)
            entries.append(MultiSourceCrossDayCompletionEntry(symbol, day,
                "MISSING" if not members else "INCOMPLETE" if reason else "COMPLETE", reason))
    completion = MultiSourceCrossDayCompletionSummary(
        *(sum(e.status == s for e in entries) for s in ("COMPLETE", "INCOMPLETE", "MISSING")), tuple(entries))
    return schema, tuple(rows), tuple(audits), completion


def _declaration(admitted, split, projection):
    schema, rows, audit, completion = projection
    return MultiSourceCrossDayDatasetIdentityInput(admitted.scope, admitted.dataset_as_of, schema, rows,
        admitted.canonical_builds, admitted.canonical_build_pins, admitted.gap_references, admitted.feature_pit,
        admitted.ts2_features, admitted.observation_pit, admitted.observation_builds, admitted.observation_input_proofs,
        admitted.observation_feature_specs, admitted.observation_features, admitted.cross_day_association,
        admitted.cross_day_labels, admitted.schedule, split, audit, completion)


def _validate_identity_input(value):
    require(type(value) is MultiSourceCrossDayDatasetIdentityInput, "INPUT_TYPE", "exact identity declaration required")
    require(type(value.split_result) is ChronologicalSplitResult, "INPUT_TYPE", "exact split result required")
    records(value.canonical_builds, VerifiedCanonicalBuild, lambda b: b.canonical_build_id)
    for values, cls, key in (
            (value.canonical_build_pins, CanonicalBuildPin, lambda p: p.canonical_build_id),
            (value.gap_references, GapReference, lambda g: g.canonical_build_id),
            (value.observation_input_proofs, ObservationBuildPin, observation_build_pin_id)):
        for record in records(values, cls, key):
            checked_record(record, cls, "IDENTITY_AUTHORITY")
    admitted = admit_inputs(feature_pit=value.feature_pit, ts2_features=value.ts2_features,
        observation_pit=value.observation_pit, observation_builds=value.observation_builds,
        observation_feature_specs=value.observation_feature_specs, observation_features=value.observation_features,
        cross_day_association=value.cross_day_association, cross_day_labels=value.cross_day_labels,
        schedule=value.schedule, scope=value.scope, split_spec=value.split_result.split_spec, dataset_as_of=value.dataset_as_of)
    split = _validated_split(admitted, value.split_result)
    expected = _declaration(admitted, split, _project(admitted, split))
    require(type(value.rows) is tuple and all(type(row) is tuple and len(row) == len(value.schema.fields) for row in value.rows),
            "IDENTITY_AUTHORITY", "exact immutable matrix rows required")
    for row in value.rows:
        for field, scalar in zip(value.schema.fields, row):
            if scalar is not None and field.logical_type in ("float64", "int64"):
                numeric(scalar, field.logical_type, "IDENTITY_AUTHORITY")
    require(_logical_build(value.canonical_builds) == _logical_build(expected.canonical_builds),
            "IDENTITY_AUTHORITY", "Canonical identity projection mismatch")
    for field in fields(expected):
        if field.name != "canonical_builds":
            require(getattr(value, field.name) == getattr(expected, field.name),
                    "IDENTITY_AUTHORITY", "identity declaration mismatch: " + field.name)


def join_multi_source_cross_day_dataset(
    *, feature_pit: PITAssemblyResult, ts2_features: TS2FeatureExecutionResult,
    observation_pit: ObservationPITAssemblyResult, observation_builds: tuple[VerifiedObservationBuild, ...],
    observation_feature_specs: tuple[ObservationFeatureSpec, ...], observation_features: ObservationFeatureExecutionResult,
    cross_day_association: CrossDayLabelAssemblyResult, cross_day_labels: CrossDayLabelExecutionResult,
    schedule: VerifiedTradingDaySchedule, scope: DatasetScope, split_spec: ChronologicalSplitSpec,
    dataset_as_of: datetime | None,
) -> MultiSourceCrossDayDatasetResult:
    """Join exact recorded facts; never execute a Feature/Label or choose PIT winners."""
    admitted = admit_inputs(feature_pit=feature_pit, ts2_features=ts2_features, observation_pit=observation_pit,
        observation_builds=observation_builds, observation_feature_specs=observation_feature_specs,
        observation_features=observation_features, cross_day_association=cross_day_association,
        cross_day_labels=cross_day_labels, schedule=schedule, scope=scope, split_spec=split_spec, dataset_as_of=dataset_as_of)
    with stage("SPLIT_BINDING"):
        split = _validated_split(admitted, assign_chronological_splits(_split_samples(admitted), admitted.split_spec))
    with stage("IDENTITY_AUTHORITY"):
        projection = _project(admitted, split)
        declaration = _declaration(admitted, split, projection)
        require_immutable(declaration)
        payload = _payload(declaration)
        require(len(payload) == 49, "IDENTITY_AUTHORITY", "closed Dataset payload mismatch")
        dataset_id = encode_identity(MULTI_SOURCE_CROSS_DAY_DATASET_ID_VERSION, payload)

    @dataclass(frozen=True, slots=True)
    class _IssuanceContext:
        authority: object
        split: ChronologicalSplitResult
        declaration: MultiSourceCrossDayDatasetIdentityInput
        dataset_id: str

    context = _IssuanceContext(admitted, split, declaration, dataset_id)
    result = object.__new__(MultiSourceCrossDayDatasetResult)
    values = dict(identity_input=context.declaration, dataset_id=context.dataset_id,
                  status="COMPLETE" if context.declaration.rows else "EMPTY")
    for field in fields(MultiSourceCrossDayDatasetResult):
        if field.name not in values:
            values[field.name] = getattr(context.declaration, field.name)
    for name, value in values.items():
        object.__setattr__(result, name, value)
    return result
