"""A1/A3/A4.1 recorded closure over full proof pairs, without live reconstruction."""

from dataclasses import replace
from datetime import timedelta
from types import MappingProxyType

from ..dataset.encoding import encode_identity
from ..dataset.identity import _implementation_digest
from ..observation import pit_identity as ids
from ..observation.identity import observation_build_id, observation_content_id
from ..observation._artifact_validation import validate_inputs
from ..observation._pit_validation import _Build, admit_source, prove_coverage, reconcile
from ..observation.pit import _pins
from ..multi_source._feature_validation import _selected
from ..multi_source._evidence import normalize_evidence, observation_evidence_content_id
from ..multi_source.feature_spec_models import normalize_specs
from ..multi_source.feature_specs import observation_feature_binding, observation_feature_spec_pin
from ..multi_source.feature_registry import _preflight_registry, _resolve
from ._artifact_canonical import _check, _ordered, _view
from ._artifact_records import _encode_record
from ._artifact_values import _value
from ._validation import numeric


def _evidence_builds(evidence, specs):
    by_pin = {}
    for record in evidence:
        _encode_record(record, "ObservationEvidence")
        declaration = _value(record.identity_input)
        snapshots = tuple(_value(s) for s in record.source_snapshots)
        declaration, snapshots, created = validate_inputs(declaration, snapshots, record.created_at)
        build = _Build(declaration, snapshots, created, observation_build_id(declaration),
                       observation_content_id(declaration.rows), "COMPLETE" if declaration.rows else "EMPTY")
        pins, _ = _pins((build,), None)
        key = ids.observation_build_pin_id(pins[0])
        _check(key not in by_pin, "duplicate complete Observation proof")
        matching = []
        for spec in specs:
            source = spec.source_spec
            entities = (source.entity_id,) if source.entity_binding == "EXACT_ENTITY" else tuple(e for _, e in source.code_entity_map)
            if any(declaration.coverage.scope == source.scope(e) for e in entities):
                admit_source(build, source)
                matching.append(source)
        _check(bool(matching), "unmatched Observation input proof scope")
        by_pin[key] = build
    _check(tuple(by_pin) == tuple(sorted(by_pin)), "Observation evidence full proof order differs")
    return by_pin


def _observation_closure(record, evidence_records, specs, pit):
    _encode_record(record, "ObservationPITAssemblyResult")
    _check(specs == normalize_specs(specs) and bool(specs), "canonical nonempty Observation specs required")
    builds = _evidence_builds(evidence_records, specs)
    bindings = tuple(_value(b) for b in record.bindings)
    expected_bindings = tuple(sorted((observation_feature_binding(s) for s in specs), key=lambda b: b.feature_spec_pin_id))
    _check(bindings == expected_bindings, "A3 complete spec/source binding mismatch")
    decisions = tuple(_value(d) for d in record.decisions)
    evidence = tuple(_value(e) for e in record.evidence)
    samples = tuple(_value(s) for s in record.sample_bindings)
    _ordered(samples, lambda s: s.sample_key, "A3 sample bindings")
    _check(tuple(s.sample_key for s in samples) == tuple(s.sample_key for s in pit.samples), "A3/PIT sample set differs")
    expected_keys = tuple((s.sample_key, b.feature_spec_pin_id) for s in samples for b in bindings)
    _check(tuple((d.sample_key, d.feature_spec_pin_id) for d in decisions) == expected_keys
           and tuple((e.sample_key, e.feature_spec_pin_id) for e in evidence) == expected_keys,
           "A3 recorded decision/evidence cross-product differs")
    _check(normalize_evidence(evidence) == evidence, "A3 proof pairing/order differs")
    requests = {s.sample_key: s for s in pit.samples}
    by_binding = {b.feature_spec_pin_id: b for b in bindings}
    selected, matched = {}, set()
    for decision, proof in zip(decisions, evidence):
        sample = requests[decision.sample_key]
        binding = by_binding[decision.feature_spec_pin_id]
        source = binding.source_spec
        _check((decision.bar_sample_version_id, decision.T, decision.A, decision.observation_source_spec_id) ==
               (sample.sample_version_id, sample.request.feature_window_close, sample.dataset_as_of,
                binding.observation_source_spec_id), "A3 decision/PIT clock/version/source differs")
        entity = source.entity_id if source.entity_binding == "EXACT_ENTITY" else dict(source.code_entity_map).get(sample.request.code)
        _check(entity is not None, "A3 source does not bind code")
        relevant = {k: b for k, b in builds.items() if b.identity.coverage.scope == source.scope(entity)}
        proof_keys = tuple(ids.observation_build_pin_id(replace(p, selected_observation_version_ids=())) for p in proof.build_pins)
        _check(len(proof_keys) == len(set(proof_keys)) and set(proof_keys) == set(relevant),
               "A3 evidence omits/duplicates a full input proof")
        represented = tuple(relevant[k] for k in sorted(relevant))
        for pin, coverage in zip(proof.build_pins, proof.coverages):
            key = ids.observation_build_pin_id(replace(pin, selected_observation_version_ids=()))
            _check(relevant[key].identity.coverage == coverage, "A3 full pin/coverage pair differs")
            admit_source(relevant[key], source)
            matched.add(key)
        row = _selected(decision, represented, source)
        expected_pins, expected_coverages = _pins(represented, row)
        _check(proof.build_pins == expected_pins and proof.coverages == expected_coverages
               and decision.considered_observation_builds_digest == ids.considered_observation_builds_digest(proof.build_pins),
               "A3 selected membership/considered proof digest differs")
        latest = source.alignment == "LATEST_EFFECTIVE_AT_OR_BEFORE"
        target = sample.request.feature_window_close if source.exact_target_binding == "FEATURE_WINDOW_CLOSE" else sample.request.feature_window_start
        start = decision.T - timedelta(microseconds=source.max_age_us)
        prove_coverage(represented, start if latest else target, decision.T if latest else target, decision.T, decision.A)
        rows, _, chains = reconcile(represented)
        for chain in chains.values():
            first = chain[0][0]
            if first.known_at <= decision.T and (first.event_time <= decision.T if latest else first.event_time == target):
                prove_coverage(represented, first.event_time, first.event_time, decision.T, decision.A, earliest_known=first.known_at)
        if row is not None:
            _check(row.known_at <= decision.T and (decision.A is None or row.archive_available_at <= decision.A)
                   and (row.event_time <= decision.T if latest else row.event_time == target), "selected Observation clock differs")
            if latest and row.event_time < start:
                prove_coverage(represented, row.event_time, decision.T, decision.T, decision.A)
        _check(decision.scoped_version_count == len(rows) and decision.status in ("COMPLETE", "EXCLUDED"),
               "A3 scoped row count/status differs")
        selected[(decision.sample_key, decision.feature_spec_pin_id)] = row
    _check(not pit.samples or matched == set(builds), "unmatched extra Observation input proof")
    for sample in samples:
        per_sample = tuple(d for d in decisions if d.sample_key == sample.sample_key)
        binding_id = ids.observation_binding_id(per_sample)
        _check(sample.bar_sample_version_id == requests[sample.sample_key].sample_version_id
               and sample.observation_binding_id == binding_id
               and sample.multi_source_sample_version_id is not None
               and sample.multi_source_sample_version_id == ids.multi_source_sample_version_id(
                   sample.sample_key, sample.bar_sample_version_id, binding_id), "A3 mandatory sample binding differs")
    content = ids.observation_association_content_id(decisions)
    sample_content = ids.sample_binding_content_id(samples)
    combined = ids.combined_association_content_id(pit.association_content_id, pit.association_schema_id, content, sample_content)
    _check((record.bar_association_content_id, record.bar_association_schema_id, record.observation_association_content_id,
            record.sample_binding_content_id, record.combined_association_content_id) ==
           (pit.association_content_id, pit.association_schema_id, content, sample_content, combined), "A3 association identity differs")
    input_proofs, _ = _pins(tuple(builds.values()), None)
    return _view(decisions=decisions, evidence=evidence, sample_bindings=samples, bindings=bindings,
        observation_association_content_id=content, sample_binding_content_id=sample_content,
        combined_association_content_id=combined, bar_association_content_id=pit.association_content_id,
        bar_association_schema_id=pit.association_schema_id,
        evidence_content_id=observation_evidence_content_id(evidence)), input_proofs, MappingProxyType(selected)


def _observation_value_id(value):
    return encode_identity("observation-feature-value-v1", dict(
        sample_key=value.sample_key, multi_source_sample_version_id=value.multi_source_sample_version_id,
        feature_name=value.feature_name, feature_spec_pin_id=ids.feature_spec_pin_id(value.spec_pin),
        implementation_pin_id=_implementation_digest(value.implementation_pin), decision_id=value.decision_id,
        status=value.status, value=value.value, reason_code=value.reason_code,
        consumed_observation_version_id=value.consumed_observation_version_id))


def _observation_values_id(values):
    ordered = sorted(values, key=lambda v: (v.sample_key, ids.feature_spec_pin_id(v.spec_pin)))
    members = tuple(_observation_value_id(v) for v in ordered)
    return encode_identity("observation-feature-values-v1", dict(count=len(members), members="".join(members)))


def _observation_features_closure(record, specs, a3, selected):
    _encode_record(record, "ObservationFeatureExecutionResult")
    _preflight_registry()
    registrations = tuple(_resolve(s) for s in specs)
    pins = tuple(observation_feature_spec_pin(s) for s in specs)
    implementation_pins = tuple(sorted({r.implementation_pin for r in registrations}, key=lambda p: (p.name, p.version, p.content_sha256)))
    _check(record.execution_contract_version == "observation-feature-execution-v1"
           and tuple(_value(p) for p in record.feature_spec_pins) == pins
           and tuple(_value(p) for p in record.implementation_pins) == implementation_pins,
           "Observation execution/spec/implementation contract differs")
    _check(tuple(s.sample_key for s in record.samples) == tuple(s.sample_key for s in a3.sample_bindings),
           "Observation Feature sample set differs")
    decisions = {(d.sample_key, d.feature_spec_pin_id): d for d in a3.decisions}
    samples = []
    for sample, binding in zip(record.samples, a3.sample_bindings):
        _check(sample.multi_source_sample_version_id == binding.multi_source_sample_version_id
               and len(sample.values) == len(specs), "Observation sample binding/cross-product differs")
        values = []
        for value, spec, pin, reg in zip(sample.values, specs, pins, registrations):
            key = (sample.sample_key, ids.feature_spec_pin_id(pin))
            decision, row = decisions[key], selected[key]
            complete = decision.status == "COMPLETE"
            _check((value.sample_key, value.multi_source_sample_version_id, value.feature_name, _value(value.spec_pin),
                    _value(value.implementation_pin), value.decision_id, value.status, value.reason_code,
                    value.consumed_observation_version_id) ==
                   (sample.sample_key, binding.multi_source_sample_version_id, spec.name, pin, reg.implementation_pin,
                    ids.observation_decision_id(decision), decision.status, decision.reason,
                    decision.selected_observation_version_id if complete else None), "Observation Feature recorded closure differs")
            if row is not None:
                fields = {f.name: (i, f.logical_type) for i, f in enumerate(row.value_schema.fields)}
                names = spec.source_spec.input_field_names
                _check(all(n in fields for n in names) and tuple(fields[n][1] for n in names) == reg.input_logical_types,
                       "Observation Feature input types differ")
                if complete:
                    for name in names:
                        index, logical_type = fields[name]
                        numeric(row.values[index], logical_type, "OBSERVATION_FEATURE_BINDING")
            if complete:
                numeric(value.value, spec.output.logical_type, "OBSERVATION_FEATURE_BINDING")
            else:
                _check(value.value is None, "excluded Observation value must be null")
            view = _view(**{k: v for k, v in value._items if k not in ("spec_pin", "implementation_pin")},
                         spec_pin=pin, implementation_pin=reg.implementation_pin)
            values.append(view)
        values = tuple(values)
        status = "COMPLETE" if all(v.status == "COMPLETE" for v in values) else "EXCLUDED"
        _check(sample.status == status, "Observation Feature sample aggregate differs")
        samples.append(_view(sample_key=sample.sample_key, multi_source_sample_version_id=sample.multi_source_sample_version_id,
                             status=status, values=values, values_content_id=_observation_values_id(values)))
    samples = tuple(samples)
    return _view(samples=samples, feature_spec_pins=pins, implementation_pins=implementation_pins,
        execution_contract_version=record.execution_contract_version,
        values_content_id=_observation_values_id(tuple(v for s in samples for v in s.values)))
