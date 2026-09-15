"""One pure in-memory assembler for the frozen MODEL_B Observation sidecar."""

from dataclasses import fields, replace
from datetime import timedelta

from ..dataset.encoding import DatasetError
from ..dataset.pit_models import PITAssemblyError, PITAssemblyResult
from .artifact_models import VerifiedObservationBuild
from ._validation import ObservationError
from .identity import observation_coverage_id, observation_source_snapshot_id
from ._pit_validation import admit_bar, admit_build, admit_source, eligible, prove_coverage, reconcile
from .pit_identity import (
    considered_observation_builds_digest, observation_build_pin_id, observation_binding_id,
    multi_source_sample_version_id, observation_association_content_id,
    sample_binding_content_id, combined_association_content_id,
)
from .pit_models import (
    ObservationPITError, ObservationPITFeatureBinding, ObservationPITDecision,
    ObservationBuildPin, ObservationSnapshotPin, ObservationSampleBinding,
    ObservationDecisionEvidence, ObservationPITAssemblyResult,
)


def _pins(builds, selected):
    pins = {}
    for build in builds:
        identity = build.identity
        snapshots = tuple(ObservationSnapshotPin(
            observation_source_snapshot_id(s), s.source_content_sha256, s.provider_id, s.source_kind,
            s.provider_contract.version, s.provider_contract.content_id, s.normalized_request_id,
            s.acquisition_receipt_id, s.acquisition_receipt_content_id, s.completed_possession_at)
            for s in sorted(build.snapshots, key=observation_source_snapshot_id))
        versions = (selected.observation_version_id,) if selected is not None and selected in identity.rows else ()
        pin = ObservationBuildPin(build.build_id, build.content_id, identity.schema_version,
                                  observation_coverage_id(identity.coverage), build.created_at, build.status,
                                  identity.authority_evidence_ids, identity.provider_contracts,
                                  identity.normalizations, snapshots, versions)
        key = observation_build_pin_id(pin)
        if key in pins and pins[key] != (pin, identity.coverage):
            raise ObservationPITError("conflicting complete build pin")
        pins[key] = (pin, identity.coverage)
    ordered = tuple(pins[k] for k in sorted(pins))
    return tuple(p[0] for p in ordered), tuple(p[1] for p in ordered)


def _decision(sample, binding, builds):
    source = binding.source_spec
    T, A = sample.request.feature_window_close, sample.dataset_as_of
    latest = source.alignment == "LATEST_EFFECTIVE_AT_OR_BEFORE"
    target = T if source.exact_target_binding == "FEATURE_WINDOW_CLOSE" else sample.request.feature_window_start
    try:
        fresh_start = T - timedelta(microseconds=source.max_age_us)
    except OverflowError as exc:
        raise ObservationPITError("unrepresentable freshness interval") from exc
    prove_coverage(builds, fresh_start if latest else target, T if latest else target, T, A)
    rows, containing, chains = reconcile(builds)
    # Point proof for every contributing effective key also covers supplied older history.
    for chain in chains.values():
        first = chain[0][0]
        if first.known_at <= T and (first.event_time <= T if latest else first.event_time == target):
            prove_coverage(builds, first.event_time, first.event_time, T, A, earliest_known=first.known_at)
    revisions = eligible(chains, T, A)
    def aligned(row):
        return row.event_time <= T if latest else row.event_time == target
    candidates = [r for r in revisions.values() if aligned(r)]
    selected = None
    if candidates:
        greatest = max(r.event_time for r in candidates)
        winners = [r for r in candidates if r.event_time == greatest]
        if len(winners) != 1:
            raise ObservationPITError("ambiguous effective observation tie")
        selected = winners[0]
        if latest and selected.event_time < fresh_start:
            prove_coverage(builds, selected.event_time, T, T, A)
    market = [r for r in eligible(chains, T, None).values() if aligned(r)]
    if selected is None:
        reason = ("ARCHIVE_FUTURE" if A is not None and market else
                  "FUTURE_KNOWN" if any(r.known_at > T and aligned(r) for r in rows) else
                  "NO_ELIGIBLE_OBSERVATION")
    else:
        reason = (selected.value_status if selected.value_status != "VALUE" else
                  "STALE" if selected.event_time < fresh_start else None)
    archive_limited = False
    if A is not None:
        archive_limited = reason == "ARCHIVE_FUTURE"
        if selected is not None:
            archive_limited = any((latest and r.event_time > selected.event_time) or
                                  (r.observation_key == selected.observation_key and r.known_at > selected.known_at)
                                  for r in market)
    if reason is not None and source.missing_policy == "FAIL":
        raise ObservationPITError("missing policy FAIL: " + reason)
    pins, coverages = _pins(builds, selected)
    selected_fields = (None,) * 8 if selected is None else (
        selected.observation_key, selected.observation_version_id,
        min(containing[selected.observation_version_id]), selected.source_snapshot_id,
        selected.known_at_authority_id, selected.event_time, selected.known_at, selected.archive_available_at)
    decision = ObservationPITDecision(
        sample.sample_key, sample.sample_version_id, binding.feature_spec_pin_id,
        binding.observation_source_spec_id, T, A, considered_observation_builds_digest(pins),
        "COMPLETE" if reason is None else "EXCLUDED", reason, archive_limited, *selected_fields,
        len(rows), sum(r.known_at > T for r in rows),
        sum(r.known_at <= T and A is not None and r.archive_available_at > A for r in rows),
        len(revisions), len(candidates))
    return decision, ObservationDecisionEvidence(sample.sample_key, binding.feature_spec_pin_id, pins, coverages)


def _assemble(bar_pit, observation_builds, bindings):
    samples = admit_bar(bar_pit)
    if type(bindings) is not tuple or any(type(b) is not ObservationPITFeatureBinding for b in bindings):
        raise ObservationPITError("bindings requires explicit ObservationPITFeatureBinding tuple")
    by_pin = {}
    for b in bindings:
        binding = replace(b)
        previous = by_pin.get(binding.feature_spec_pin_id)
        if previous is not None and previous.observation_source_spec_id != binding.observation_source_spec_id:
            raise ObservationPITError("conflicting Feature binding")
        by_pin[binding.feature_spec_pin_id] = binding
    bindings = tuple(by_pin[k] for k in sorted(by_pin))
    if type(observation_builds) is not tuple:
        raise ObservationPITError("builds requires explicit VerifiedObservationBuild tuple")
    builds = tuple(admit_build(b) for b in observation_builds)
    routed = {}
    matched = set()
    for binding in bindings:
        source = binding.source_spec
        entities = (source.entity_id,) if source.entity_binding == "EXACT_ENTITY" else tuple(e for _, e in source.code_entity_map)
        for entity in set(entities):
            relevant = tuple(b for b in builds if b.identity.coverage.scope == source.scope(entity))
            for b in relevant:
                admit_source(b, source)
                matched.add(id(b))
            routed[(binding.feature_spec_pin_id, entity)] = relevant
    if len(matched) != len(builds):
        raise ObservationPITError("unmatched Observation build scope")
    decisions, evidence, sample_bindings = [], [], []
    for sample in samples:
        per_sample = []
        for binding in bindings:
            source = binding.source_spec
            entity = source.entity_id
            if source.entity_binding == "SAMPLE_CODE":
                entity = dict(source.code_entity_map).get(sample.request.code)
                if entity is None:
                    raise ObservationPITError("unknown sample code")
            decision, proof = _decision(sample, binding, routed[(binding.feature_spec_pin_id, entity)])
            decisions.append(decision)
            per_sample.append(decision)
            evidence.append(proof)
        binding_id = observation_binding_id(per_sample)
        sample_bindings.append(ObservationSampleBinding(sample.sample_key, sample.sample_version_id, binding_id,
                              multi_source_sample_version_id(sample.sample_key, sample.sample_version_id, binding_id)))
    decisions, evidence, sample_bindings = tuple(decisions), tuple(evidence), tuple(sample_bindings)
    _verify_result(samples, bindings, decisions, evidence, sample_bindings, routed)
    content = observation_association_content_id(decisions)
    binding_content = sample_binding_content_id(sample_bindings)
    values = dict(decisions=decisions, evidence=evidence, sample_bindings=sample_bindings, bindings=bindings,
                  observation_association_content_id=content, sample_binding_content_id=binding_content,
                  combined_association_content_id=combined_association_content_id(
                      bar_pit.association_content_id, bar_pit.association_schema_id, content, binding_content),
                  bar_association_content_id=bar_pit.association_content_id,
                  bar_association_schema_id=bar_pit.association_schema_id)
    result = object.__new__(ObservationPITAssemblyResult)
    for f in fields(result):
        object.__setattr__(result, f.name, values[f.name])
    return result


def _verify_result(samples, bindings, decisions, evidence, sample_bindings, routed):
    expected = [(s.sample_key, b.feature_spec_pin_id) for s in samples for b in bindings]
    if [(d.sample_key, d.feature_spec_pin_id) for d in decisions] != expected or len(evidence) != len(expected):
        raise ObservationPITError("decision cardinality/order mismatch")
    by_sample = {s.sample_key: s for s in samples}
    by_binding = {b.feature_spec_pin_id: b for b in bindings}
    for d, proof in zip(decisions, evidence):
        sample, binding = by_sample[d.sample_key], by_binding[d.feature_spec_pin_id]
        source = binding.source_spec
        entity = source.entity_id if source.entity_binding == "EXACT_ENTITY" else dict(source.code_entity_map)[sample.request.code]
        # Recompute full decisions from the admitted authorities, not stored hash assertions.
        expected_decision, expected_proof = _decision(sample, binding, routed[(d.feature_spec_pin_id, entity)])
        if d != expected_decision or proof != expected_proof:
            raise ObservationPITError("decision/provenance mismatch")
        if considered_observation_builds_digest(proof.build_pins) != d.considered_observation_builds_digest:
            raise ObservationPITError("build pin digest mismatch")
    for sample, row in zip(samples, sample_bindings):
        digest = observation_binding_id(tuple(d for d in decisions if d.sample_key == sample.sample_key))
        expected_row = ObservationSampleBinding(sample.sample_key, sample.sample_version_id, digest,
            multi_source_sample_version_id(sample.sample_key, sample.sample_version_id, digest))
        if row != expected_row:
            raise ObservationPITError("sample binding mismatch")
    if len(sample_bindings) != len(samples):
        raise ObservationPITError("sample binding cardinality mismatch")


def assemble_observation_pit_sidecar(
    bar_pit: PITAssemblyResult,
    observation_builds: tuple[VerifiedObservationBuild, ...],
    bindings: tuple[ObservationPITFeatureBinding, ...],
) -> ObservationPITAssemblyResult:
    """Bind verified in-memory Observation facts without changing bar PIT authority."""
    try:
        return _assemble(bar_pit, observation_builds, bindings)
    except ObservationPITError:
        raise
    except (ObservationError, DatasetError, PITAssemblyError) as exc:
        raise ObservationPITError(str(exc)) from exc
