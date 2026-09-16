"""Pure closure checks of A3 results and their exact A2 evidence, without selection."""

from dataclasses import replace
from datetime import timedelta

from ..observation._validation import sha256
from ..observation.models import ObservationScope
from ..observation._pit_validation import admit_build, admit_source
from ..observation.pit import _pins
from ..observation.pit_identity import (
    observation_build_pin_id, considered_observation_builds_digest,
    observation_binding_id, multi_source_sample_version_id,
    observation_association_content_id, sample_binding_content_id, combined_association_content_id,
)
from ..observation.pit_models import (
    ObservationPITAssemblyResult, ObservationPITFeatureBinding, ObservationPITDecision,
    ObservationDecisionEvidence, ObservationSampleBinding,
)
from .feature_models import ObservationFeatureExecutionError, _tuple
from .feature_specs import observation_feature_binding


def _fail(message):
    raise ObservationFeatureExecutionError(message)


def _copy(values, cls, label):
    copies = tuple(replace(v) for v in _tuple(values, cls, label))
    if copies != values:
        _fail("noncanonical or tampered " + label)
    return copies


def _selected(decision, builds, source):
    if decision.selected_observation_version_id is None:
        return None
    representatives = [b for b in builds if b.build_id == decision.selected_observation_build_id]
    rows = [row for b in representatives for row in b.identity.rows
            if row.observation_version_id == decision.selected_observation_version_id]
    if not rows or any(r != rows[0] for r in rows):
        _fail("selected version missing or conflicting in exact representative")
    row = rows[0]
    actual = (row.observation_key, row.observation_version_id, row.source_snapshot_id,
              row.known_at_authority_id, row.event_time, row.known_at, row.archive_available_at)
    expected = (decision.selected_observation_key, decision.selected_observation_version_id,
                decision.selected_source_snapshot_id, decision.selected_known_at_authority_id,
                decision.selected_event_time, decision.selected_known_at, decision.selected_archive_available_at)
    if actual != expected or row.value_schema_id != source.value_schema_id:
        _fail("selected provenance/schema mismatch")
    if ObservationScope(row.provider_id, row.source_kind, row.entity_id,
                        row.observation_name, row.dimensions) != source.scope(row.entity_id):
        _fail("selected scope mismatch")
    if decision.status == "COMPLETE" and (row.value_status != "VALUE" or row.values is None):
        _fail("COMPLETE decision requires a VALUE observation")
    fresh = row.event_time >= decision.T - timedelta(microseconds=source.max_age_us)
    if (decision.status == "COMPLETE" and not fresh) or (decision.reason == "STALE" and fresh):
        _fail("selected freshness/status mismatch")
    if decision.reason in ("NOT_REPORTED", "WITHDRAWN") and row.value_status != decision.reason:
        _fail("selected exclusion status mismatch")
    if decision.reason == "STALE" and row.value_status != "VALUE":
        _fail("STALE requires a VALUE observation")
    return row


def verify_execution_inputs(result, observation_builds, specs):
    if type(result) is not ObservationPITAssemblyResult:
        _fail("requires exact ObservationPITAssemblyResult")
    if type(observation_builds) is not tuple:
        _fail("requires VerifiedObservationBuild tuple")
    bindings = _copy(result.bindings, ObservationPITFeatureBinding, "bindings")
    derived = tuple(sorted((observation_feature_binding(s) for s in specs), key=lambda b: b.feature_spec_pin_id))
    if bindings != derived:
        _fail("A3 spec/source binding set mismatch")
    decisions = _copy(result.decisions, ObservationPITDecision, "decisions")
    evidence = _copy(result.evidence, ObservationDecisionEvidence, "evidence")
    samples = _copy(result.sample_bindings, ObservationSampleBinding, "sample bindings")
    keys = [s.sample_key for s in samples]
    if keys != sorted(set(keys)):
        _fail("sample cardinality/order mismatch")
    expected = [(s.sample_key, b.feature_spec_pin_id) for s in samples for b in bindings]
    if ([(d.sample_key, d.feature_spec_pin_id) for d in decisions] != expected
            or [(e.sample_key, e.feature_spec_pin_id) for e in evidence] != expected):
        _fail("decision/evidence cardinality/order mismatch")
    builds_by_pin = {}
    for value in observation_builds:
        build = admit_build(value)
        pins, _ = _pins((build,), None)
        key = observation_build_pin_id(pins[0])
        if key in builds_by_pin:
            _fail("duplicate or conflicting supplied build evidence")
        builds_by_pin[key] = build
    matched = set()
    selected_rows = {}
    by_binding = {b.feature_spec_pin_id: b for b in bindings}
    for decision, proof in zip(decisions, evidence):
        binding = by_binding[decision.feature_spec_pin_id]
        source = binding.source_spec
        if decision.observation_source_spec_id != binding.observation_source_spec_id:
            _fail("decision/source identity mismatch")
        proof_builds = []
        for pin, coverage in zip(proof.build_pins, proof.coverages):
            key = observation_build_pin_id(replace(pin, selected_observation_version_ids=()))
            build = builds_by_pin.get(key)
            if build is None or build.identity.coverage != coverage:
                _fail("missing or conflicting exact build evidence")
            entities = (source.entity_id,) if source.entity_binding == "EXACT_ENTITY" else tuple(e for _, e in source.code_entity_map)
            if coverage.scope not in tuple(source.scope(entity) for entity in entities):
                _fail("build/source scope mismatch")
            admit_source(build, source)
            matched.add(key)
            proof_builds.append(build)
        if len({b.identity.coverage.scope for b in proof_builds}) > 1:
            _fail("one decision cannot mix entity scopes")
        row = _selected(decision, proof_builds, source)
        expected_pins, expected_coverages = _pins(proof_builds, row)
        if proof.build_pins != expected_pins or proof.coverages != expected_coverages:
            _fail("selected membership or complete build pin mismatch")
        if considered_observation_builds_digest(proof.build_pins) != decision.considered_observation_builds_digest:
            _fail("considered build digest mismatch")
        selected_rows[(decision.sample_key, decision.feature_spec_pin_id)] = row
    if matched != builds_by_pin.keys():
        _fail("unmatched extra build evidence")
    for sample in samples:
        per_sample = tuple(d for d in decisions if d.sample_key == sample.sample_key)
        if any(d.bar_sample_version_id != sample.bar_sample_version_id for d in per_sample):
            _fail("decision/bar sample version mismatch")
        if len({(d.T, d.A) for d in per_sample}) > 1:
            _fail("inconsistent sample cutoffs")
        digest = observation_binding_id(per_sample)
        if (digest != sample.observation_binding_id or sample.multi_source_sample_version_id !=
                multi_source_sample_version_id(sample.sample_key, sample.bar_sample_version_id, digest)):
            _fail("sample binding identity mismatch")
    for name in ("bar_association_content_id", "bar_association_schema_id"):
        sha256(getattr(result, name), name)
    content = observation_association_content_id(decisions)
    sample_content = sample_binding_content_id(samples)
    if (content != result.observation_association_content_id or sample_content != result.sample_binding_content_id
            or combined_association_content_id(result.bar_association_content_id, result.bar_association_schema_id,
                                              content, sample_content) != result.combined_association_content_id):
        _fail("A3 association identity closure mismatch")
    return decisions, samples, selected_rows
