"""Separate multi-source Dataset identity; no legacy identity is extended."""

from dataclasses import dataclass, fields, replace
from datetime import datetime

from ..dataset.content import dataset_schema_id
from ..dataset.encoding import encode_identity, normalize_utc_datetime
from ..dataset.identity import (
    _build_pin_digest, _completion_digest, _gap_reference_digest,
    _implementation_digest, _scope_digest, _spec_digest,
)
from ..dataset.models import (
    CanonicalBuildPin, CompletionSummary, DatasetSchema, DatasetScope,
    GapReference, ImplementationPin, SpecPin,
)
from ..dataset.orchestration_models import _verify_scope_request_binding
from ..observation.pit_identity import feature_spec_pin_id
from ..observation.pit_models import ObservationDecisionEvidence
from ._audit import MultiSourceSampleAudit, normalize_audit, sample_audit_content_id
from ._evidence import evidence_ids, normalize_evidence, observation_evidence_content_id
from ._orchestration_validation import canonical_copy, hashes, items, pin_key, require

MULTI_SOURCE_DATASET_ID_VERSION = "multi-source-dataset-id-v1"
MULTI_SOURCE_DATASET_ORCHESTRATION_CONTRACT_VERSION = "multi-source-dataset-orchestration-v1"

_VERSIONS = {
    "manifest_schema_version": "multi-source-dataset-manifest-v1",
    "serialization_format": "parquet",
    "serialization_format_version": "multi-source-dataset-parquet-v1",
    "observation_association_schema_version": "observation-association-v1",
    "sample_binding_schema_version": "observation-sample-binding-v1",
    "multi_source_pit_contract_version": "multi-source-pit-v1",
    "observation_feature_execution_contract_version": "observation-feature-execution-v1",
    "multi_source_dataset_orchestration_contract_version": MULTI_SOURCE_DATASET_ORCHESTRATION_CONTRACT_VERSION,
}


@dataclass(frozen=True, slots=True)
class MultiSourceDatasetIdentityInput:
    dataset_kind: str
    scope: DatasetScope
    dataset_as_of: datetime | None
    schema: DatasetSchema
    dataset_schema_id: str
    logical_dataset_content_id: str
    canonical_builds: tuple[CanonicalBuildPin, ...]
    canonical_row_version_ids: tuple[str, ...]
    bar_feature_specs: tuple[SpecPin, ...]
    observation_feature_specs: tuple[SpecPin, ...]
    label_specs: tuple[SpecPin, ...]
    split_spec: SpecPin
    implementations: tuple[ImplementationPin, ...]
    completion: CompletionSummary
    gap_references: tuple[GapReference, ...]
    bar_association_schema_id: str
    bar_association_content_id: str
    observation_association_content_id: str
    sample_binding_content_id: str
    combined_association_content_id: str
    observation_evidence_content_id: str
    observation_build_pin_ids: tuple[str, ...]
    observation_coverage_ids: tuple[str, ...]
    observation_feature_values_content_id: str
    sample_audit_content_id: str
    sample_audit: tuple[MultiSourceSampleAudit, ...]
    observation_evidence: tuple[ObservationDecisionEvidence, ...]
    manifest_schema_version: str = _VERSIONS["manifest_schema_version"]
    serialization_format: str = "parquet"
    serialization_format_version: str = _VERSIONS["serialization_format_version"]
    observation_association_schema_version: str = "observation-association-v1"
    sample_binding_schema_version: str = "observation-sample-binding-v1"
    multi_source_pit_contract_version: str = "multi-source-pit-v1"
    observation_feature_execution_contract_version: str = "observation-feature-execution-v1"
    multi_source_dataset_orchestration_contract_version: str = MULTI_SOURCE_DATASET_ORCHESTRATION_CONTRACT_VERSION

    def __post_init__(self):
        require(self.dataset_kind == "SUPERVISED", "only SUPERVISED is supported")
        for name, expected in _VERSIONS.items():
            require(getattr(self, name) == expected, f"invalid {name}")
        for name, cls in (("scope", DatasetScope), ("schema", DatasetSchema),
                          ("completion", CompletionSummary), ("split_spec", SpecPin)):
            object.__setattr__(self, name, canonical_copy(getattr(self, name), cls, name))
        require(self.split_spec.kind == "SPLIT", "split pin kind mismatch")
        if self.dataset_as_of is not None:
            object.__setattr__(self, "dataset_as_of", normalize_utc_datetime(self.dataset_as_of, "dataset_as_of"))
        scalar_ids = ("dataset_schema_id", "logical_dataset_content_id", "bar_association_schema_id",
            "bar_association_content_id", "observation_association_content_id", "sample_binding_content_id",
            "combined_association_content_id", "observation_evidence_content_id",
            "observation_feature_values_content_id", "sample_audit_content_id")
        for name in scalar_ids:
            hashes((getattr(self, name),), name)
        require(self.dataset_schema_id == dataset_schema_id(self.schema), "schema ID mismatch")
        for name, cls, key in (
            ("canonical_builds", CanonicalBuildPin, lambda p: p.canonical_build_id),
            ("gap_references", GapReference, lambda p: p.canonical_build_id),
            ("bar_feature_specs", SpecPin, pin_key),
            ("observation_feature_specs", SpecPin, pin_key),
            ("label_specs", SpecPin, pin_key),
            ("implementations", ImplementationPin, lambda p: (p.name, p.version)),
        ):
            values = tuple(canonical_copy(v, cls, name) for v in items(getattr(self, name), cls, name))
            if name == "implementations":
                unique = {}
                for value in values:
                    require(key(value) not in unique or unique[key(value)] == value, "conflicting implementation pins")
                    unique[key(value)] = value
                values = tuple(unique.values())
            require(len({key(v) for v in values}) == len(values), f"duplicate {name}")
            object.__setattr__(self, name, tuple(sorted(values, key=key)))
        specs = self.bar_feature_specs + self.observation_feature_specs + self.label_specs
        require(self.bar_feature_specs and self.observation_feature_specs and self.label_specs,
                "all spec families must be nonempty")
        require(len({s.name for s in specs}) == len(specs), "duplicate cross-family spec name")
        require(all(s.kind == "FEATURE" for s in self.bar_feature_specs + self.observation_feature_specs)
                and all(s.kind == "LABEL" for s in self.label_specs), "spec family mismatch")
        builds = {p.canonical_build_id: p for p in self.canonical_builds}
        require(builds, "Canonical pins must be nonempty")
        covered = {v for p in builds.values() for v in p.canonical_row_version_ids}
        object.__setattr__(self, "canonical_row_version_ids", hashes(self.canonical_row_version_ids, "canonical rows", distinct=True))
        require(set(self.canonical_row_version_ids) <= covered, "uncovered Canonical row version")
        for gap in self.gap_references:
            require(gap.canonical_build_id in builds and
                    builds[gap.canonical_build_id].gap_content_id == gap.gap_content_id, "unbound gap")
        expected_scope = {(s, d) for s in self.scope.symbols for d in self.scope.trade_dates}
        require({(e.code, e.trade_date) for e in self.completion.entries} == expected_scope,
                "completion must cover exact scope")
        audit = normalize_audit(self.sample_audit)
        evidence = normalize_evidence(self.observation_evidence)
        object.__setattr__(self, "sample_audit", audit)
        object.__setattr__(self, "observation_evidence", evidence)
        require(sample_audit_content_id(audit) == self.sample_audit_content_id, "audit content mismatch")
        require(observation_evidence_content_id(evidence) == self.observation_evidence_content_id, "evidence content mismatch")
        proof_ids, coverage_ids = evidence_ids(evidence)
        for name, actual in (("observation_build_pin_ids", proof_ids), ("observation_coverage_ids", coverage_ids)):
            value = hashes(getattr(self, name), name, distinct=True)
            require(value == actual, f"{name} not exact evidence")
            object.__setattr__(self, name, value)
        expected_evidence = {(a.sample_key, feature_spec_pin_id(p)) for a in audit for p in self.observation_feature_specs}
        require({(e.sample_key, e.feature_spec_pin_id) for e in evidence} == expected_evidence,
                "evidence cardinality must equal audit x Observation specs")
        implementation_set = set(self.implementations)
        for a in audit:
            _verify_scope_request_binding(self.scope, (a.request,))
            require(a.dataset_as_of == self.dataset_as_of, "audit cutoff mismatch")
            require(set(a.considered_canonical_build_ids) <= set(builds), "audit references unpinned build")
            require(set(a.feature_canonical_row_version_ids + a.label_canonical_row_version_ids)
                    <= set(self.canonical_row_version_ids), "audit references unpinned row")
            require(tuple(v.spec_pin for v in a.bar_feature_values) == self.bar_feature_specs and
                    tuple(v.spec_pin for v in a.label_values) == self.label_specs, "audit spec pins mismatch")
            require(all(v.implementation_pin in implementation_set for v in a.bar_feature_values + a.label_values),
                    "audit implementation not pinned")
        combined = encode_identity("multi-source-association-content-v1", {
            "bar_association_schema_version": "pit-association-schema-v1",
            **{n: getattr(self, n) for n in ("bar_association_content_id", "bar_association_schema_id",
                "observation_association_content_id", "observation_association_schema_version",
                "sample_binding_content_id", "sample_binding_schema_version", "multi_source_pit_contract_version")},
        })
        require(combined == self.combined_association_content_id, "combined association mismatch")


def _identity_payload(value):
    excluded = {"schema", "sample_audit", "observation_evidence"}
    result = {f.name: getattr(value, f.name) for f in fields(value) if f.name not in excluded}
    result["scope"] = _scope_digest(value.scope)
    result["completion"] = _completion_digest(value.completion)
    result["split_spec"] = _spec_digest(value.split_spec)
    for name, digest in (("canonical_builds", _build_pin_digest), ("bar_feature_specs", _spec_digest),
        ("observation_feature_specs", _spec_digest), ("label_specs", _spec_digest),
        ("implementations", _implementation_digest), ("gap_references", _gap_reference_digest)):
        result[name] = "\x1e".join(sorted(digest(p) for p in getattr(value, name)))
    for name in ("canonical_row_version_ids", "observation_build_pin_ids", "observation_coverage_ids"):
        result[name] = "\x1e".join(getattr(value, name))
    return result


def multi_source_dataset_id(value: MultiSourceDatasetIdentityInput) -> str:
    value = canonical_copy(value, MultiSourceDatasetIdentityInput, "multi-source identity input")
    return encode_identity(MULTI_SOURCE_DATASET_ID_VERSION, _identity_payload(value))
