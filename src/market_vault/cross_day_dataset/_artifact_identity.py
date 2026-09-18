"""The frozen 49-field Dataset identity calculated from validated records."""

from ..cross_day import identity as label_ids
from ..dataset.content import dataset_schema_id, logical_dataset_content_id
from ..dataset.encoding import encode_identity
from ..dataset.identity import _scope_digest, _build_pin_digest, _gap_reference_digest, _spec_digest, _implementation_digest
from ..dataset.specs import feature_label_spec_pin
from ..dataset.split_models import chronological_split_spec_pin
from ..multi_source._evidence import observation_evidence_content_id
from ..observation.pit_identity import observation_build_pin_id
from ..ts2_feature.identity import considered_builds_digest
from .identity import (
    MULTI_SOURCE_CROSS_DAY_DATASET_ID_VERSION, MULTI_SOURCE_CROSS_DAY_DATASET_ORCHESTRATION_CONTRACT_VERSION,
    MULTI_SOURCE_CROSS_DAY_SAMPLE_AUDIT_VERSION, cross_day_dataset_sequence_id,
    multi_source_cross_day_completion_content_id, multi_source_cross_day_sample_audit_id,
)


def _recorded_payload(value):
    # This closed projection has no upstream live-result constructors or type bypass.
    q = cross_day_dataset_sequence_id
    pit, ts2, a3, obs, labels = (value.feature_pit, value.ts2_features, value.observation_pit,
                                value.observation_features, value.cross_day_labels)
    association = value.cross_day_association
    row_mappings = tuple(dict(zip((f.name for f in value.schema.fields), row)) for row in value.rows)
    return dict(
        dataset_kind="SUPERVISED",
        source_schema_version="10.9-mv-ts2",
        scope_id=_scope_digest(value.scope),
        dataset_as_of=value.dataset_as_of,
        dataset_schema_id=dataset_schema_id(value.schema),
        logical_dataset_content_id=logical_dataset_content_id(value.schema, row_mappings),
        canonical_build_pins_digest=q("CANONICAL_BUILD_PINS", tuple(_build_pin_digest(p) for p in value.canonical_build_pins)),
        feature_canonical_builds_digest=considered_builds_digest(ts2.considered_canonical_build_ids),
        cross_day_considered_canonical_builds_digest=label_ids.considered_canonical_build_ids_digest(association.considered_canonical_build_ids),
        canonical_row_versions_digest=q("CANONICAL_ROW_VERSIONS", tuple(v for p in value.canonical_build_pins for v in p.canonical_row_version_ids)),
        gap_references_digest=q("GAP_REFERENCES", tuple(_gap_reference_digest(g) for g in value.gap_references)),
        ts2_spec_pins_digest=q("TS2_SPEC_PINS", tuple(_spec_digest(p) for p in ts2.feature_spec_pins)),
        observation_spec_pins_digest=q("OBSERVATION_SPEC_PINS", tuple(_spec_digest(p) for p in obs.feature_spec_pins)),
        cross_day_spec_pins_digest=q("CROSS_DAY_SPEC_PINS", tuple(_spec_digest(feature_label_spec_pin(s)) for s in labels.label_specs)),
        ts2_registry_pins_digest=q("TS2_REGISTRY_PINS", tuple(_implementation_digest(p) for p in ts2.registry_implementation_pins)),
        observation_implementation_pins_digest=q("OBSERVATION_IMPLEMENTATION_PINS", tuple(_implementation_digest(p) for p in obs.implementation_pins)),
        cross_day_implementation_pins_digest=q("CROSS_DAY_IMPLEMENTATION_PINS", tuple(_implementation_digest(p) for p in labels.implementation_pins)),
        split_spec_pin_id=_spec_digest(chronological_split_spec_pin(value.split_result.split_spec)),
        split_result_id=value.split_result.split_result_id,
        completion_content_id=multi_source_cross_day_completion_content_id(value.completion),
        feature_association_schema_id=pit.association_schema_id,
        feature_association_content_id=pit.association_content_id,
        observation_association_content_id=a3.observation_association_content_id,
        observation_sample_binding_content_id=a3.sample_binding_content_id,
        combined_association_content_id=a3.combined_association_content_id,
        observation_evidence_content_id=observation_evidence_content_id(a3.evidence),
        observation_input_proofs_digest=q("OBSERVATION_INPUT_PROOFS", tuple(observation_build_pin_id(p) for p in value.observation_input_proofs)),
        observation_build_pin_ids_digest=q("OBSERVATION_BUILDPIN_IDS", tuple(observation_build_pin_id(p) for e in a3.evidence for p in e.build_pins)),
        observation_coverage_ids_digest=q("OBSERVATION_COVERAGE_IDS", tuple(p.coverage_id for p in value.observation_input_proofs)),
        multi_source_sample_versions_digest=q("MULTI_SOURCE_SAMPLE_VERSIONS", tuple(b.multi_source_sample_version_id for b in a3.sample_bindings)),
        ts2_execution_id=ts2.execution_id,
        ts2_values_content_id=ts2.values_content_id,
        observation_values_content_id=obs.values_content_id,
        schedule_pin_id=label_ids.schedule_pin_id(value.schedule.pin),
        cross_day_association_content_id=association.association_content_id,
        cross_day_sample_bindings_digest=q("CROSS_DAY_SAMPLE_BINDINGS", tuple(b.sample_binding_id for b in association.sample_bindings)),
        cross_day_decisions_digest=q("CROSS_DAY_DECISIONS", tuple(d.decision_id for d in association.decisions)),
        cross_day_values_content_id=labels.values_content_id,
        sample_audit_content_id=q("SAMPLE_AUDIT", tuple(multi_source_cross_day_sample_audit_id(a) for a in value.sample_audit)),
        manifest_schema_version="multi-source-cross-day-dataset-manifest-v1",
        serialization_format="parquet",
        serialization_format_version="multi-source-cross-day-dataset-parquet-v1",
        orchestration_contract_version=MULTI_SOURCE_CROSS_DAY_DATASET_ORCHESTRATION_CONTRACT_VERSION,
        sample_audit_contract_version=MULTI_SOURCE_CROSS_DAY_SAMPLE_AUDIT_VERSION,
        ts2_feature_execution_contract_version="ts2-feature-execution-v1",
        observation_feature_execution_contract_version="observation-feature-execution-v1",
        multi_source_pit_contract_version="multi-source-pit-v1",
        cross_day_association_schema_version="cross-day-label-association-v1",
        cross_day_execution_contract_version="cross-day-label-execution-v1",
    )


def _recorded_dataset_id(value):
    return encode_identity(MULTI_SOURCE_CROSS_DAY_DATASET_ID_VERSION, _recorded_payload(value))
