"""Verify complete A2/A3 proofs and recorded A4.1 outcomes without selection."""

from dataclasses import replace
from datetime import timedelta

from ..cross_day._authority import admit_observation_pit
from ..observation.artifact_models import VerifiedObservationBuild
from ..observation._pit_validation import admit_build, admit_source, prove_coverage, reconcile
from ..observation.pit import _pins
from ..observation.pit_identity import observation_build_pin_id, feature_spec_pin_id, observation_decision_id
from ..multi_source._evidence import normalize_evidence, observation_evidence_content_id
from ..multi_source._feature_validation import verify_execution_inputs
from ..multi_source.feature_models import ObservationFeatureExecutionResult, ObservationFeatureTransformInput
from ..multi_source.feature_specs import observation_feature_spec_pin
from ..multi_source.feature_identity import observation_feature_values_content_id
from ._validation import checked_record, digest, numeric, require


def proof_key(pin):
    return observation_build_pin_id(replace(pin, selected_observation_version_ids=()))


def admit_observation(pit, a3, builds, specs):
    code = "A3_BINDING"
    require(type(builds) is tuple and all(type(b) is VerifiedObservationBuild for b in builds),
            "INPUT_TYPE", "exact Observation build tuple required")
    versions = admit_observation_pit(pit, a3)
    require(all(v is not None for v in versions.values()), code, "non-null A3 version required")
    admitted = {}
    originals = {}
    for original in builds:
        build = admit_build(original)
        pins, _ = _pins((build,), None)
        key = observation_build_pin_id(pins[0])
        require(key not in admitted, "DUPLICATE_INPUT", "duplicate complete Observation input proof")
        admitted[key] = build
        originals[key] = original
        matching = []
        for spec in specs:
            source = spec.source_spec
            entities = (source.entity_id,) if source.entity_binding == "EXACT_ENTITY" else tuple(e for _, e in source.code_entity_map)
            if any(build.identity.coverage.scope == source.scope(e) for e in entities):
                admit_source(build, source)
                matching.append(source)
        require(bool(matching), code, "unmatched Observation input scope")
    ordered = tuple(originals[k] for k in sorted(originals))
    # Empty A3 closure cannot represent builds; retain and validate all input proofs separately.
    decisions, samples, selected = verify_execution_inputs(a3, ordered if pit.samples else (), specs)
    evidence = normalize_evidence(a3.evidence)
    require(evidence == a3.evidence, code, "noncanonical paired Observation evidence")
    requests = {s.sample_key: s for s in pit.samples}
    bindings = {b.feature_spec_pin_id: b for b in a3.bindings}
    for decision, proof in zip(decisions, evidence):
        sample = requests[decision.sample_key]
        source = bindings[decision.feature_spec_pin_id].source_spec
        entity = source.entity_id if source.entity_binding == "EXACT_ENTITY" else dict(source.code_entity_map)[sample.request.code]
        relevant = {k: b for k, b in admitted.items() if b.identity.coverage.scope == source.scope(entity)}
        keys = tuple(proof_key(p) for p in proof.build_pins)
        require(len(set(keys)) == len(keys), "DUPLICATE_INPUT", "duplicate complete evidence proof")
        require(set(keys) == set(relevant), code, "evidence omits an applicable physical proof")
        represented = tuple(relevant[k] for k in sorted(relevant))
        latest = source.alignment == "LATEST_EFFECTIVE_AT_OR_BEFORE"
        target = (sample.request.feature_window_close if source.exact_target_binding == "FEATURE_WINDOW_CLOSE"
                  else sample.request.feature_window_start)
        start = decision.T - timedelta(microseconds=source.max_age_us)
        prove_coverage(represented, start if latest else target, decision.T if latest else target, decision.T, decision.A)
        rows, _, chains = reconcile(represented)
        for chain in chains.values():
            first = chain[0][0]
            if first.known_at <= decision.T and (first.event_time <= decision.T if latest else first.event_time == target):
                prove_coverage(represented, first.event_time, first.event_time, decision.T, decision.A,
                               earliest_known=first.known_at)
        row = selected[(decision.sample_key, decision.feature_spec_pin_id)]
        if row is not None:
            require(row.known_at <= decision.T and (decision.A is None or row.archive_available_at <= decision.A)
                    and (row.event_time <= decision.T if latest else row.event_time == target),
                    "CLOCK_AUTHORITY", "selected Observation clock/alignment mismatch")
            if latest and row.event_time < start:
                prove_coverage(represented, row.event_time, decision.T, decision.T, decision.A)
        require(decision.scoped_version_count == len(rows) and decision.status in ("COMPLETE", "EXCLUDED"), code,
                "invalid recorded Observation decision")
    digest(observation_evidence_content_id(evidence))
    input_pins, _ = _pins(tuple(admitted[k] for k in sorted(admitted)), None)
    return ordered, input_pins, decisions, samples, selected


def verify_observation_features(result, specs, registrations, decisions, samples, selected):
    code = "OBSERVATION_FEATURE_BINDING"
    checked_record(result, ObservationFeatureExecutionResult, code)
    pins = tuple(observation_feature_spec_pin(s) for s in specs)
    implementation_pins = tuple(sorted({r.implementation_pin for r in registrations},
                                      key=lambda p: (p.name, p.version, p.content_sha256)))
    require(result.feature_spec_pins == pins and result.implementation_pins == implementation_pins,
            "IMPLEMENTATION_BINDING", "Observation spec/implementation pin mismatch")
    require(tuple(s.sample_key for s in result.samples) == tuple(s.sample_key for s in samples),
            code, "Observation sample closure mismatch")
    by_key = {(d.sample_key, d.feature_spec_pin_id): d for d in decisions}
    for sample, binding in zip(result.samples, samples):
        require(sample.multi_source_sample_version_id == binding.multi_source_sample_version_id,
                code, "Observation/A3 version mismatch")
        require(len(sample.values) == len(specs), code, "Observation value cardinality mismatch")
        for value, spec, pin, reg in zip(sample.values, specs, pins, registrations):
            key = (sample.sample_key, feature_spec_pin_id(pin))
            decision = by_key[key]
            row = selected[key]
            complete = decision.status == "COMPLETE"
            require((value.sample_key, value.multi_source_sample_version_id, value.feature_name,
                     value.spec_pin, value.implementation_pin, value.decision_id, value.status,
                     value.reason_code, value.consumed_observation_version_id) ==
                    (sample.sample_key, binding.multi_source_sample_version_id, spec.name, pin,
                     reg.implementation_pin, observation_decision_id(decision), decision.status,
                     decision.reason, decision.selected_observation_version_id if complete else None),
                    code, "Observation value/decision linkage mismatch")
            if row is not None:
                fields = {f.name: (i, f.logical_type) for i, f in enumerate(row.value_schema.fields)}
                names = spec.source_spec.input_field_names
                types = tuple(fields[n][1] for n in names)
                require(types == reg.input_logical_types, code, "Observation field types differ")
                if complete:
                    ObservationFeatureTransformInput(names, types,
                        tuple(row.values[fields[n][0]] for n in names), spec.parameters)
            if complete:
                numeric(value.value, spec.output.logical_type, code)
            else:
                require(value.value is None, code, "excluded Observation value must be null")
    digest(observation_feature_values_content_id(result))
