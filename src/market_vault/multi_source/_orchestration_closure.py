"""Pure cross-layer checks and derivations, never selection or execution."""

from dataclasses import replace

from ..dataset.content import logical_dataset_content_id
from ..dataset.feature_models import FeatureExecutionResult
from ..dataset.label_models import LabelExecutionResult
from ..dataset.models import CompletionEntry, CompletionSummary, DatasetField, DatasetSchema
from ..dataset.orchestration_models import _RESERVED_FIELD_NAMES, _normalize_specs, _verify_sample_binding
from ..dataset.spec_models import FeatureSpec, LabelSpec
from ..dataset.specs import feature_label_spec_pin
from ..dataset.split_models import ChronologicalSplitSample
from ..observation._pit_validation import admit_bar, admit_build, admit_source
from ..observation.pit import _pins
from ..observation.pit_identity import feature_spec_pin_id, observation_build_pin_id, observation_decision_id
from ._audit import build_audit
from ._feature_validation import verify_execution_inputs
from ._orchestration_validation import canonical_copy, items, require
from .feature_models import ObservationFeatureExecutionResult
from .feature_spec_models import ObservationFeatureSpec, normalize_specs
from .feature_specs import observation_feature_spec_pin


def normalize_spec_families(bar_specs, observation_specs, label_specs):
    bar = _normalize_specs(items(bar_specs, FeatureSpec, "bar Feature specs", nonempty=True), FeatureSpec, "bar Feature specs")
    observation = normalize_specs(items(observation_specs, ObservationFeatureSpec, "Observation Feature specs", nonempty=True))
    labels = _normalize_specs(items(label_specs, LabelSpec, "Label specs", nonempty=True), LabelSpec, "Label specs")
    bar = tuple(replace(s) for s in bar)
    labels = tuple(replace(s) for s in labels)
    names = [s.output.name for s in bar + observation + labels]
    require(len(set(names)) == len(names) and not set(names) & _RESERVED_FIELD_NAMES,
            "output names collide across families or reserved fields")
    require(all(s.output.nullable is False for s in bar + observation), "Feature outputs cannot be nullable")
    return bar, observation, labels


def derive_schema(bar, observation, labels, cutoff):
    columns = [("code", "string", False), ("sample_key", "string", False),
        ("sample_version_id", "string", False), ("feature_window_close", "timestamp_us_utc", False),
        ("actual_label_end_time", "timestamp_us_utc", True), ("label_status", "string", False)]
    if cutoff is not None:
        columns.append(("dataset_as_of", "timestamp_us_utc", False))
    columns.extend((s.output.name, s.output.logical_type, False) for s in bar + observation)
    columns.extend((s.output.name, s.output.logical_type, True) for s in labels)
    columns.extend((("feature_window_close_date", "date32", False), ("nominal_split", "string", True),
        ("final_split", "string", True), ("assignment_status", "string", False),
        ("reason_code", "string", True), ("purge_boundary", "timestamp_us_utc", True)))
    return DatasetSchema(tuple(DatasetField(n, t, nullable=b) for n, t, b in columns))


def represented_builds(pit, builds):
    ids = {p.observation_build_id for e in pit.evidence for p in e.build_pins}
    return tuple(b for b in builds if b.observation_build_id in ids)


def close_layers(bar_pit, observation_pit, builds, bar_specs, observation_specs, label_specs,
                 features, observation_features, labels, cutoff):
    admit_bar(bar_pit)
    features = canonical_copy(features, FeatureExecutionResult, "bar Feature result")
    labels = canonical_copy(labels, LabelExecutionResult, "Label result")
    observation_features = canonical_copy(observation_features, ObservationFeatureExecutionResult, "Observation Feature result")
    _verify_sample_binding(bar_pit, features, labels, cutoff)
    require(features.feature_spec_pins == tuple(feature_label_spec_pin(s) for s in bar_specs), "bar spec/result mismatch")
    require(labels.label_spec_pins == tuple(feature_label_spec_pin(s) for s in label_specs), "Label spec/result mismatch")
    require(observation_features.feature_spec_pins == tuple(observation_feature_spec_pin(s) for s in observation_specs),
            "Observation spec/result mismatch")
    decisions, bindings, _ = verify_execution_inputs(observation_pit, represented_builds(observation_pit, builds), observation_specs)
    admitted = tuple(admit_build(b) for b in builds)
    admitted_by_pin = {}
    for build in admitted:
        pins, _ = _pins((build,), None)
        key = observation_build_pin_id(pins[0])
        require(key not in admitted_by_pin, "duplicate Observation build proof")
        admitted_by_pin[key] = build
    for build in admitted:
        matched = False
        for spec in observation_specs:
            source = spec.source_spec
            entities = (source.entity_id,) if source.entity_binding == "EXACT_ENTITY" else tuple(e for _, e in source.code_entity_map)
            if build.identity.coverage.scope in tuple(source.scope(e) for e in entities):
                admit_source(build, source)
                matched = True
        require(matched, "unmatched Observation build scope")
    require(observation_pit.bar_association_schema_id == bar_pit.association_schema_id and
            observation_pit.bar_association_content_id == bar_pit.association_content_id, "A3/bar association mismatch")
    samples = {s.sample_key: s for s in bar_pit.samples}
    sources = {b.feature_spec_pin_id: b.source_spec for b in observation_pit.bindings}
    for proof in observation_pit.evidence:
        source = sources[proof.feature_spec_pin_id]
        entity = source.entity_id if source.entity_binding == "EXACT_ENTITY" else dict(source.code_entity_map)[samples[proof.sample_key].request.code]
        expected = {key for key, b in admitted_by_pin.items() if b.identity.coverage.scope == source.scope(entity)}
        actual = {observation_build_pin_id(replace(p, selected_observation_version_ids=())) for p in proof.build_pins}
        require(actual == expected, "omitted or extra considered proof")
    require(set(samples) == {s.sample_key for s in bindings} == {s.sample_key for s in observation_features.samples},
            "A3/Observation Feature sample set mismatch")
    for binding in bindings:
        require(binding.bar_sample_version_id == samples[binding.sample_key].sample_version_id, "A3/bar version mismatch")
    for decision in decisions:
        sample = samples[decision.sample_key]
        require(decision.T == sample.request.feature_window_close and decision.A == cutoff,
                "A3 decision cutoff mismatch")
    versions = {s.sample_key: s.multi_source_sample_version_id for s in bindings}
    decision_by_key = {(d.sample_key, d.feature_spec_pin_id): d for d in decisions}
    for sample in observation_features.samples:
        require(sample.multi_source_sample_version_id == versions[sample.sample_key], "Observation Feature version mismatch")
        for value in sample.values:
            decision = decision_by_key[(sample.sample_key, feature_spec_pin_id(value.spec_pin))]
            require(value.decision_id == observation_decision_id(decision) and value.status == decision.status,
                    "Observation value/decision mismatch")
            require(value.reason_code == decision.reason, "Observation value reason mismatch")
            consumed = decision.selected_observation_version_id if decision.status == "COMPLETE" else None
            require(value.consumed_observation_version_id == consumed, "Observation consumption mismatch")
    audit = build_audit(bar_pit, features, labels)
    return features, observation_features, labels, audit


def split_samples(bar_pit, observation_pit, features, observation_features, labels):
    observations = {s.sample_key: s for s in observation_features.samples}
    versions = {s.sample_key: s.multi_source_sample_version_id for s in observation_pit.sample_bindings}
    label_by_key = {s.sample_key: s for s in labels.samples}
    result = []
    for sample in features.samples:
        if sample.status == "COMPLETE" and observations[sample.sample_key].status == "COMPLETE":
            label = label_by_key[sample.sample_key]
            result.append(ChronologicalSplitSample(sample.sample_key, versions[sample.sample_key],
                sample.feature_window_close, label.status, label.actual_label_end_time))
    return tuple(sorted(result, key=lambda s: s.sample_key))


def completion(scope, audit, observation_features):
    observation = {s.sample_key: s for s in observation_features.samples}
    entries = []
    for code in scope.symbols:
        for day in scope.trade_dates:
            samples = [a for a in audit if a.request.code == code and a.request.anchor_market_calendar_date == day]
            excluded = any(a.bar_feature_status != "COMPLETE" or observation[a.sample_key].status != "COMPLETE" for a in samples)
            incomplete = any(a.label_status != "COMPLETE" for a in samples)
            if not samples:
                status, reason = "MISSING", "NO_SAMPLE_REQUEST"
            elif excluded or incomplete:
                status = "INCOMPLETE"
                reason = ("MULTI_SOURCE_FEATURE_EXCLUDED_AND_LABEL_INCOMPLETE" if excluded and incomplete else
                          "MULTI_SOURCE_FEATURE_EXCLUDED" if excluded else "LABEL_INCOMPLETE")
            else:
                status, reason = "COMPLETE", None
            entries.append(CompletionEntry(code, day, status, reason))
    return CompletionSummary(sum(e.status == "COMPLETE" for e in entries),
        sum(e.status == "INCOMPLETE" for e in entries), sum(e.status == "MISSING" for e in entries), tuple(entries))


def logical_rows(bar_pit, features, observations, labels, split, schema):
    feature = {s.sample_key: s for s in features.samples}
    observation = {s.sample_key: s for s in observations.samples}
    label = {s.sample_key: s for s in labels.samples}
    assignments = {a.sample_key: a for a in split.assignments}
    rows = []
    for sample in bar_pit.samples:
        key = sample.sample_key
        if key not in assignments:
            continue
        a, l = assignments[key], label[key]
        row = dict(code=sample.request.code, sample_key=key, sample_version_id=a.sample_version_id,
            feature_window_close=sample.request.feature_window_close, actual_label_end_time=l.actual_label_end_time,
            label_status=l.status, dataset_as_of=sample.dataset_as_of)
        row.update((v.feature_name, v.value) for v in feature[key].values)
        row.update((v.feature_name, v.value) for v in observation[key].values)
        row.update((v.label_name, v.value) for v in l.values)
        for name in ("feature_window_close_date", "nominal_split", "final_split", "assignment_status", "reason_code", "purge_boundary"):
            row[name] = getattr(a, name)
        rows.append(row)
    rows.sort(key=lambda r: (r["code"], r["feature_window_close"], r["sample_key"]))
    require(len({r["sample_key"] for r in rows}) == len(rows), "duplicate matrix sample")
    # The unchanged content encoder checks every scalar and nullability.
    logical_dataset_content_id(schema, tuple({f.name: r[f.name] for f in schema.fields} for r in rows))
    return tuple(tuple(r[f.name] for f in schema.fields) for r in rows)


def merge_implementations(*results):
    pins = {}
    for result in results:
        for pin in result.implementation_pins:
            key = (pin.name, pin.version)
            require(key not in pins or pins[key] == pin, "conflicting cross-family implementation pins")
            pins[key] = pin
    return tuple(pins[k] for k in sorted(pins))
