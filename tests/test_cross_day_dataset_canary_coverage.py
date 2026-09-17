"""All 80 design obligations, with generator/artifact work explicitly deferred."""

import ast
from collections import Counter
from pathlib import Path

import pytest

CANARIES = (
    (1, "PRESERVED_UPSTREAM", "test_dataset_orchestration.py", None),
    (2, "L3_3_DEFERRED", "Artifact/reader/publication obligation; upstream relocation is tested, but no new artifact exists.", None),
    (3, "L3_3_DEFERRED", "Artifact/reader/publication obligation; upstream relocation is tested, but no new artifact exists.", None),
    (4, "L3_1_RUNTIME", "test_cross_day_dataset_execution.py", "test_a3_binding_tamper_rejected"),
    (5, "L3_1_RUNTIME", "test_cross_day_dataset_execution.py", "test_a3_binding_tamper_rejected"),
    (6, "L3_1_RUNTIME", "test_cross_day_dataset_execution.py", "test_a3_binding_tamper_rejected"),
    (7, "L3_1_RUNTIME", "test_cross_day_dataset_execution.py", "test_l2_recorded_tamper_rejected"),
    (8, "L3_1_RUNTIME", "test_cross_day_dataset_execution.py", "test_a3_binding_tamper_rejected"),
    (9, "L3_1_RUNTIME", "test_cross_day_dataset_execution.py", "test_ts2_recorded_tamper_rejected"),
    (10, "L3_1_RUNTIME", "test_cross_day_dataset_execution.py", "test_observation_feature_tamper_rejected"),
    (11, "L3_1_RUNTIME", "test_cross_day_dataset_execution.py", "test_l2_recorded_tamper_rejected"),
    (12, "L3_1_RUNTIME", "test_cross_day_dataset_semantics.py", "test_common_authority_mismatches_fail"),
    (13, "L3_1_RUNTIME", "test_cross_day_dataset_semantics.py", "test_common_authority_mismatches_fail"),
    (14, "L3_1_RUNTIME", "test_cross_day_dataset_execution.py", "test_l2_recorded_tamper_rejected"),
    (15, "L3_1_RUNTIME", "test_cross_day_dataset_semantics.py", "test_considered_backing_schedule_and_observation_independence"),
    (16, "L3_1_RUNTIME", "test_cross_day_dataset_semantics.py", "test_considered_backing_schedule_and_observation_independence"),
    (17, "L3_1_RUNTIME", "test_cross_day_dataset_semantics.py", "test_real_ts2_outcome_changes_dataset_id"),
    (18, "L3_1_RUNTIME", "test_cross_day_dataset_semantics.py", "test_considered_backing_schedule_and_observation_independence"),
    (19, "L3_1_RUNTIME", "test_cross_day_dataset_semantics.py", "test_considered_backing_schedule_and_observation_independence"),
    (20, "L3_1_RUNTIME", "test_cross_day_dataset_semantics.py", "test_considered_backing_schedule_and_observation_independence"),
    (21, "L3_1_RUNTIME", "test_cross_day_dataset_semantics.py", "test_considered_backing_schedule_and_observation_independence"),
    (22, "L3_1_RUNTIME", "test_cross_day_dataset_boundaries.py", "test_actual_new_label_implementation_pin_changes_dataset_identity"),
    (23, "L3_1_RUNTIME", "test_cross_day_dataset_semantics.py", "test_considered_backing_schedule_and_observation_independence"),
    (24, "L3_1_RUNTIME", "test_cross_day_dataset_execution.py", "test_l2_recorded_tamper_rejected"),
    (25, "L3_1_RUNTIME", "test_cross_day_dataset_execution.py", "test_eligibility_audit_and_completion"),
    (26, "L3_1_RUNTIME", "test_cross_day_dataset_execution.py", "test_eligibility_audit_and_completion"),
    (27, "L3_1_RUNTIME", "test_cross_day_dataset_execution.py", "test_eligibility_audit_and_completion"),
    (28, "L3_1_RUNTIME", "test_cross_day_dataset_execution.py", "test_eligibility_audit_and_completion"),
    (29, "L3_1_RUNTIME", "test_cross_day_dataset_execution.py", "test_eligibility_audit_and_completion"),
    (30, "L3_1_RUNTIME", "test_cross_day_dataset_execution.py", "test_eligibility_audit_and_completion"),
    (31, "L3_1_RUNTIME", "test_cross_day_dataset_semantics.py", "test_gap_recorded_closure_partial_consumption_and_actual_end"),
    (32, "L3_1_RUNTIME", "test_cross_day_dataset_semantics.py", "test_gap_recorded_closure_partial_consumption_and_actual_end"),
    (33, "L3_1_RUNTIME", "test_cross_day_dataset_execution.py", "test_eligibility_audit_and_completion"),
    (34, "L3_1_RUNTIME", "test_cross_day_dataset_execution.py", "test_eligibility_audit_and_completion"),
    (35, "L3_1_RUNTIME", "test_cross_day_dataset_semantics.py", "test_split_actual_end_boundary_and_matrix_retention"),
    (36, "L3_1_RUNTIME", "test_cross_day_dataset_semantics.py", "test_considered_backing_schedule_and_observation_independence"),
    (37, "L3_1_RUNTIME", "test_cross_day_dataset_identity.py", "test_literal_known_answer"),
    (38, "L3_3_DEFERRED", "Artifact/reader/publication obligation; upstream relocation is tested, but no new artifact exists.", None),
    (39, "L3_3_DEFERRED", "Artifact/reader/publication obligation; upstream relocation is tested, but no new artifact exists.", None),
    (40, "L3_3_DEFERRED", "Artifact/reader/publication obligation; upstream relocation is tested, but no new artifact exists.", None),
    (41, "L3_1_RUNTIME", "test_cross_day_dataset_execution.py", "test_canary_41_full_selection_and_candidate_tail"),
    (42, "L3_1_RUNTIME", "test_cross_day_dataset_execution.py", "test_ts2_recorded_tamper_rejected"),
    (43, "L3_1_RUNTIME", "test_cross_day_dataset_execution.py", "test_distinct_physical_proofs_retained_and_identity_bearing"),
    (44, "L3_1_RUNTIME", "test_cross_day_dataset_execution.py", "test_eligibility_audit_and_completion"),
    (45, "L3_1_RUNTIME", "test_cross_day_dataset_execution.py", "test_l2_recorded_tamper_rejected"),
    (46, "L3_1_RUNTIME", "test_cross_day_dataset_semantics.py", "test_zero_samples_input_proofs_and_missing_families_remain_strict"),
    (47, "L3_1_RUNTIME", "test_cross_day_dataset_execution.py", "test_eligibility_audit_and_completion"),
    (48, "L3_1_RUNTIME", "test_cross_day_dataset_semantics.py", "test_cross_family_and_reserved_names_rejected"),
    (49, "L3_1_RUNTIME", "test_cross_day_dataset_semantics.py", "test_cross_family_and_reserved_names_rejected"),
    (50, "L3_1_RUNTIME", "test_cross_day_dataset_semantics.py", "test_common_authority_mismatches_fail"),
    (51, "L3_1_RUNTIME", "test_cross_day_dataset_boundaries.py", "test_no_upstream_execution_and_only_bounded_registry_io"),
    (52, "L3_1_RUNTIME", "test_cross_day_dataset_boundaries.py", "test_no_upstream_execution_and_only_bounded_registry_io"),
    (53, "L3_1_RUNTIME", "test_cross_day_dataset_boundaries.py", "test_no_upstream_execution_and_only_bounded_registry_io"),
    (54, "L3_1_RUNTIME", "test_cross_day_dataset_boundaries.py", "test_no_upstream_execution_and_only_bounded_registry_io"),
    (55, "L3_1_RUNTIME", "test_cross_day_dataset_boundaries.py", "test_no_upstream_execution_and_only_bounded_registry_io"),
    (56, "L3_2_DEFERRED", "Generator obligation; no generator is implemented or invoked.", None),
    (57, "L3_2_DEFERRED", "Generator obligation; no generator is implemented or invoked.", None),
    (58, "L3_2_DEFERRED", "Generator obligation; no generator is implemented or invoked.", None),
    (59, "L3_2_DEFERRED", "Generator obligation; no generator is implemented or invoked.", None),
    (60, "L3_1_RUNTIME", "test_cross_day_dataset_boundaries.py", "test_no_upstream_execution_and_only_bounded_registry_io"),
    (61, "L3_3_DEFERRED", "Artifact/reader/publication obligation; upstream relocation is tested, but no new artifact exists.", None),
    (62, "PRESERVED_UPSTREAM", "test_multi_source_identity.py", None),
    (63, "PRESERVED_UPSTREAM", "test_cross_day_identity.py", None),
    (64, "PRESERVED_UPSTREAM", "test_cross_day_canary_coverage.py", None),
    (65, "PRESERVED_UPSTREAM", "test_ts2_feature_identity.py", None),
    (66, "PRESERVED_UPSTREAM", "test_ts2_feature_canary_coverage.py", None),
    (67, "BOUNDARY", "test_cross_day_dataset_boundaries.py", "test_package_is_pure_additive_and_has_no_future_api"),
    (68, "BOUNDARY", "test_cross_day_dataset_boundaries.py", "test_package_is_pure_additive_and_has_no_future_api"),
    (69, "L3_1_RUNTIME", "test_cross_day_dataset_execution.py", "test_distinct_physical_proofs_retained_and_identity_bearing"),
    (70, "L3_1_RUNTIME", "test_cross_day_dataset_execution.py", "test_observation_proof_tamper_rejected"),
    (71, "L3_1_RUNTIME", "test_cross_day_dataset_semantics.py", "test_zero_sample_a41_helper_exception_is_local_only"),
    (72, "L3_1_RUNTIME", "test_cross_day_dataset_semantics.py", "test_unused_canonical_boundary_is_validated_before_clocks"),
    (73, "L3_1_RUNTIME", "test_cross_day_dataset_semantics.py", "test_unused_canonical_boundary_is_validated_before_clocks"),
    (74, "L3_1_RUNTIME", "test_cross_day_dataset_boundaries.py", "test_coordinated_ts2_source_fingerprint_pin_forgery_rejected"),
    (75, "L3_3_DEFERRED", "Artifact/reader/publication obligation; upstream relocation is tested, but no new artifact exists.", None),
    (76, "L3_3_DEFERRED", "Artifact/reader/publication obligation; upstream relocation is tested, but no new artifact exists.", None),
    (77, "L3_3_DEFERRED", "Artifact/reader/publication obligation; upstream relocation is tested, but no new artifact exists.", None),
    (78, "L3_1_RUNTIME", "test_cross_day_dataset_semantics.py", "test_split_actual_end_boundary_and_matrix_retention"),
    (79, "L3_2_DEFERRED", "Generator obligation; no generator is implemented or invoked.", None),
    (80, "L3_1_RUNTIME", "test_cross_day_dataset_identity.py", "test_literal_known_answer"),
)


def test_complete_honest_canary_accounting():
    assert [row[0] for row in CANARIES] == list(range(1, 81))
    assert Counter(row[1] for row in CANARIES) == {
        "L3_1_RUNTIME": 58, "PRESERVED_UPSTREAM": 6, "L3_2_DEFERRED": 5,
        "L3_3_DEFERRED": 9, "BOUNDARY": 2,
    }
    assert CANARIES[40][3] == "test_canary_41_full_selection_and_candidate_tail"


@pytest.mark.parametrize("number,phase,target,test_name", CANARIES)
def test_canary_evidence_reference_exists(number, phase, target, test_name):
    if phase.endswith("_DEFERRED"):
        assert test_name is None and target
        return
    tree = ast.parse((Path(__file__).parent / target).read_text(encoding="utf-8"))
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    if test_name is None:
        assert phase == "PRESERVED_UPSTREAM"
        assert any(n.startswith("test_") for n in names)
    else:
        assert test_name in names
