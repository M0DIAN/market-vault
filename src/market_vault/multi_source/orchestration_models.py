"""Immutable, self-validating in-memory multi-source Dataset result."""

from dataclasses import dataclass, field, fields, replace
from datetime import datetime
from types import MappingProxyType

from ..canonical.reader import VerifiedCanonicalBuild
from ..dataset.content import dataset_schema_id, logical_dataset_content_id
from ..dataset.encoding import DatasetError, normalize_utc_datetime
from ..dataset.execution_provenance import normalize_verified_builds, reconcile_canonical_rows, verify_pit_pin_binding
from ..dataset.feature_models import FeatureExecutionResult
from ..dataset.label_models import LabelExecutionResult
from ..dataset.models import CompletionSummary, DatasetSchema, DatasetScope
from ..dataset.orchestration_models import _verify_scope_request_binding
from ..dataset.pit_models import PITAssemblyResult
from ..dataset.split_models import ChronologicalSplitResult, ChronologicalSplitSpec
from ..observation.artifact_models import VerifiedObservationBuild
from ..observation.pit_models import ObservationPITAssemblyResult
from ._audit import sample_audit_content_id
from ._evidence import evidence_ids, normalize_evidence, observation_evidence_content_id
from ._orchestration_closure import (
    close_layers, completion, derive_schema, logical_rows, merge_implementations,
    normalize_spec_families, split_samples,
)
from ._orchestration_validation import MultiSourceDatasetError, canonical_copy, freeze_copy, items, require
from .feature_identity import observation_feature_values_content_id
from .feature_models import ObservationFeatureExecutionResult
from .identity import MultiSourceDatasetIdentityInput, multi_source_dataset_id


@dataclass(frozen=True, slots=True)
class MultiSourceDatasetOrchestrationResult:
    scope: DatasetScope
    dataset_as_of: datetime | None
    bar_feature_specs: tuple
    observation_feature_specs: tuple
    label_specs: tuple
    split_spec: ChronologicalSplitSpec
    canonical_builds: tuple[VerifiedCanonicalBuild, ...] = field(repr=False)
    observation_builds: tuple[VerifiedObservationBuild, ...] = field(repr=False)
    bar_pit_result: PITAssemblyResult
    observation_pit_result: ObservationPITAssemblyResult
    bar_feature_result: FeatureExecutionResult
    observation_feature_result: ObservationFeatureExecutionResult
    label_result: LabelExecutionResult
    split_result: ChronologicalSplitResult
    dataset_kind: str = "SUPERVISED"
    status: str = field(init=False)
    schema: DatasetSchema = field(init=False)
    rows: tuple[tuple, ...] = field(init=False)
    dataset_schema_id: str = field(init=False)
    logical_dataset_content_id: str = field(init=False)
    sample_audit: tuple = field(init=False)
    sample_audit_content_id: str = field(init=False)
    observation_evidence: tuple = field(init=False)
    observation_evidence_content_id: str = field(init=False)
    observation_feature_values_content_id: str = field(init=False)
    completion: CompletionSummary = field(init=False)
    identity_input: MultiSourceDatasetIdentityInput = field(init=False)
    dataset_id: str = field(init=False)
    diagnostics: object = field(init=False)

    def logical_row_mappings(self):
        return tuple(dict(zip((f.name for f in self.schema.fields), row)) for row in self.rows)

    def __post_init__(self):
        try:
            self._validate_and_derive()
        except MultiSourceDatasetError:
            raise
        except (DatasetError, ValueError, TypeError, KeyError) as exc:
            raise MultiSourceDatasetError(f"invalid multi-source orchestration result: {exc}") from exc

    def _validate_and_derive(self):
        require(self.dataset_kind == "SUPERVISED", "only SUPERVISED is supported")
        scope = canonical_copy(self.scope, DatasetScope, "scope")
        cutoff = None if self.dataset_as_of is None else normalize_utc_datetime(self.dataset_as_of, "dataset_as_of")
        bar, observation, labels = normalize_spec_families(self.bar_feature_specs, self.observation_feature_specs, self.label_specs)
        spec = canonical_copy(self.split_spec, ChronologicalSplitSpec, "split spec")
        canonical = normalize_verified_builds(items(self.canonical_builds, VerifiedCanonicalBuild, "Canonical builds", nonempty=True))
        items(self.observation_builds, VerifiedObservationBuild, "Observation builds", nonempty=True)
        verify_pit_pin_binding(self.bar_pit_result, {b.canonical_build_id: b for b in canonical}, reconcile_canonical_rows(canonical))
        _verify_scope_request_binding(scope, tuple(s.request for s in self.bar_pit_result.samples))
        features, observations, label_result, audit = close_layers(self.bar_pit_result, self.observation_pit_result,
            self.observation_builds, bar, observation, labels, self.bar_feature_result, self.observation_feature_result,
            self.label_result, cutoff)
        split = canonical_copy(self.split_result, ChronologicalSplitResult, "split result")
        require(split.split_spec == spec, "split spec/result mismatch")
        expected = split_samples(self.bar_pit_result, self.observation_pit_result, features, observations, label_result)
        require({a.sample_key for a in split.assignments} == {s.sample_key for s in expected}, "split eligibility mismatch")
        assignments = {a.sample_key: a for a in split.assignments}
        for sample in expected:
            a = assignments[sample.sample_key]
            require(all(getattr(a, name) == getattr(sample, name) for name in
                        ("sample_version_id", "feature_window_close", "label_status", "actual_label_end_time")),
                    "split input/result facts mismatch")
        completed = completion(scope, audit, observations)
        schema = derive_schema(bar, observation, labels, cutoff)
        rows = logical_rows(self.bar_pit_result, features, observations, label_result, split, schema)
        schema_id = dataset_schema_id(schema)
        content_id = logical_dataset_content_id(schema, tuple(dict(zip((f.name for f in schema.fields), r)) for r in rows))
        proof = normalize_evidence(self.observation_pit_result.evidence)
        proof_id = observation_evidence_content_id(proof)
        audit_id = sample_audit_content_id(audit)
        value_id = observation_feature_values_content_id(observations)
        pin_ids, coverage_ids = evidence_ids(proof)
        pit, obs = self.bar_pit_result, self.observation_pit_result
        identity = MultiSourceDatasetIdentityInput(
            dataset_kind=self.dataset_kind, scope=scope, dataset_as_of=cutoff, schema=schema,
            dataset_schema_id=schema_id, logical_dataset_content_id=content_id,
            canonical_builds=pit.canonical_build_pins, canonical_row_version_ids=pit.canonical_row_version_ids,
            bar_feature_specs=features.feature_spec_pins, observation_feature_specs=observations.feature_spec_pins,
            label_specs=label_result.label_spec_pins, split_spec=split.split_spec_pin,
            implementations=merge_implementations(features, observations, label_result),
            completion=completed, gap_references=pit.gap_references,
            bar_association_schema_id=pit.association_schema_id, bar_association_content_id=pit.association_content_id,
            observation_association_content_id=obs.observation_association_content_id,
            sample_binding_content_id=obs.sample_binding_content_id, combined_association_content_id=obs.combined_association_content_id,
            observation_evidence_content_id=proof_id, observation_build_pin_ids=pin_ids, observation_coverage_ids=coverage_ids,
            observation_feature_values_content_id=value_id, sample_audit_content_id=audit_id,
            sample_audit=audit, observation_evidence=proof)
        derived = dict(scope=scope, dataset_as_of=cutoff, bar_feature_specs=bar, observation_feature_specs=observation,
            label_specs=labels, split_spec=spec, bar_feature_result=features, observation_feature_result=observations,
            label_result=label_result, split_result=split, status="COMPLETE" if rows else "EMPTY", schema=schema,
            rows=rows, dataset_schema_id=schema_id, logical_dataset_content_id=content_id,
            sample_audit=audit, sample_audit_content_id=audit_id, observation_evidence=proof,
            observation_evidence_content_id=proof_id, observation_feature_values_content_id=value_id,
            completion=completed, identity_input=identity, dataset_id=multi_source_dataset_id(identity),
            diagnostics=MappingProxyType(dict(request_count=len(audit), matrix_row_count=len(rows),
                feature_excluded_sample_count=len(audit)-len(rows),
                label_incomplete_sample_count=sum(a.label_status == "INCOMPLETE" for a in audit),
                observation_decision_count=len(obs.decisions), observation_evidence_count=len(proof))))
        for name, value in derived.items():
            object.__setattr__(self, name, value)
        # Detach legacy mapping leaves only after their full validation.
        for f in fields(self):
            object.__setattr__(self, f.name, freeze_copy(getattr(self, f.name)))
