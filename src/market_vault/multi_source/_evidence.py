"""Identity of complete A3 evidence, preserving every BuildPin/Coverage pair."""

from dataclasses import replace

from ..dataset.encoding import encode_identity
from ..observation.identity import observation_coverage_id
from ..observation.pit_identity import observation_build_pin_id
from ..observation.pit_models import ObservationBuildPin, ObservationDecisionEvidence
from ..observation.models import ObservationCoverage
from ._orchestration_validation import exact, items, require, sequence

MULTI_SOURCE_OBSERVATION_EVIDENCE_CONTENT_ID_VERSION = "multi-source-observation-evidence-v1"


def observation_proof_pair_id(pin: ObservationBuildPin, coverage: ObservationCoverage) -> str:
    exact(pin, ObservationBuildPin, "build pin")
    exact(coverage, ObservationCoverage, "coverage")
    pin, coverage = replace(pin), replace(coverage)
    coverage_id = observation_coverage_id(coverage)
    require(pin.coverage_id == coverage_id, "Observation pin/coverage pairing mismatch")
    return encode_identity("multi-source-observation-proof-v1", {
        "observation_build_pin_id": observation_build_pin_id(pin), "coverage_id": coverage_id})


def normalize_evidence(evidence):
    items(evidence, ObservationDecisionEvidence, "observation evidence")
    result = []
    seen = set()
    for item in evidence:
        item = replace(item)
        key = item.sample_key, item.feature_spec_pin_id
        require(key not in seen, "duplicate Observation evidence item")
        seen.add(key)
        pairs = sorted(zip(item.build_pins, item.coverages), key=lambda p: observation_build_pin_id(p[0]))
        pair_ids = tuple(observation_proof_pair_id(*pair) for pair in pairs)
        require(len(set(pair_ids)) == len(pair_ids), "duplicate Observation proof pair")
        require(len({p.observation_build_id for p, _ in pairs}) == len(pairs), "conflicting Observation build proofs")
        result.append(replace(item, build_pins=tuple(p for p, _ in pairs), coverages=tuple(c for _, c in pairs)))
    return tuple(sorted(result, key=lambda e: (e.sample_key, e.feature_spec_pin_id)))


def observation_evidence_item_id(evidence: ObservationDecisionEvidence) -> str:
    evidence, = normalize_evidence((evidence,))
    pairs = tuple(observation_proof_pair_id(p, c) for p, c in zip(evidence.build_pins, evidence.coverages))
    return encode_identity("multi-source-observation-evidence-item-v1", {
        "sample_key": evidence.sample_key, "feature_spec_pin_id": evidence.feature_spec_pin_id,
        "proofs_digest": sequence("multi-source-observation-proofs-v1", pairs)})


def observation_evidence_content_id(evidence: tuple[ObservationDecisionEvidence, ...]) -> str:
    evidence = normalize_evidence(evidence)
    return sequence(MULTI_SOURCE_OBSERVATION_EVIDENCE_CONTENT_ID_VERSION,
                    tuple(observation_evidence_item_id(e) for e in evidence))


def evidence_ids(evidence):
    evidence = normalize_evidence(evidence)
    pins = tuple(sorted({observation_build_pin_id(p) for e in evidence for p in e.build_pins}))
    coverages = tuple(sorted({observation_coverage_id(c) for e in evidence for c in e.coverages}))
    return pins, coverages
