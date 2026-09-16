"""Checked coverage accounting for the 66 L1 design obligations.

Deferred entries are not claimed as implemented. Canary 45 covers L2 only;
generator behavior and the full TS2 Feature Dataset belong to L3. No canary
authorizes L4 physical schedule acquisition; all schedules here are synthetic.
"""
import ast
from pathlib import Path

import pytest

CANARIES = (
    (1, "PRESERVED_LEGACY_REGRESSION", "test_feature_label_specs.py", None),
    (2, "PRESERVED_LEGACY_REGRESSION", "test_dataset_label_execution.py", None),
    (3, "PRESERVED_LEGACY_REGRESSION", "test_pit_sample_assembly.py", None),
    (4, "IMPLEMENTED_L2_TEST", "test_cross_day_admission.py", "test_spec_preflight_even_zero_samples"),
    (5, "IMPLEMENTED_L2_TEST", "test_cross_day_admission.py", "test_explicit_opt_in_bool_and_duplicate_semantics"),
    (6, "IMPLEMENTED_L2_TEST", "test_cross_day_admission.py", "test_spec_preflight_even_zero_samples"),
    (7, "IMPLEMENTED_L2_TEST", "test_cross_day_admission.py", "test_explicit_opt_in_bool_and_duplicate_semantics"),
    (8, "IMPLEMENTED_L2_TEST", "test_cross_day_admission.py", "test_schedule_every_civil_date_and_duplicate_rejection"),
    (9, "IMPLEMENTED_L2_TEST", "test_cross_day_admission.py", "test_schedule_every_civil_date_and_duplicate_rejection"),
    (10, "IMPLEMENTED_L2_TEST", "test_cross_day_admission.py", "test_schedule_every_civil_date_and_duplicate_rejection"),
    (11, "IMPLEMENTED_L2_TEST", "test_cross_day_admission.py", "test_schedule_archive_gate_and_identity"),
    (12, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_missing_anchor_does_not_substitute"),
    (13, "IMPLEMENTED_L2_TEST", "test_cross_day_admission.py", "test_anchor_geometry_failures"),
    (14, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_real_verified_scenarios"),
    (15, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_real_verified_scenarios"),
    (16, "IMPLEMENTED_L2_TEST", "test_cross_day_admission.py", "test_schedule_every_civil_date_and_duplicate_rejection"),
    (17, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_forward_uses_endpoint_only"),
    (18, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_forward_uses_endpoint_only"),
    (19, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_forward_gap_endpoint_and_no_interpolation"),
    (20, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_gap_proofs_and_incomplete_subsets"),
    (21, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_gap_proofs_and_incomplete_subsets"),
    (22, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_gap_proofs_and_incomplete_subsets"),
    (23, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_forward_gap_endpoint_and_no_interpolation"),
    (24, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_real_verified_scenarios"),
    (25, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_real_verified_scenarios"),
    (26, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_real_verified_scenarios"),
    (27, "IMPLEMENTED_L2_TEST", "test_cross_day_admission.py", "test_unqualified_geometry_rejected"),
    (28, "IMPLEMENTED_L2_TEST", "test_cross_day_admission.py", "test_wrong_scope_and_pit_evidence_failures"),
    (29, "IMPLEMENTED_L2_TEST", "test_cross_day_admission.py", "test_wrong_scope_and_pit_evidence_failures"),
    (30, "IMPLEMENTED_L2_TEST", "test_cross_day_admission.py", "test_wrong_scope_and_pit_evidence_failures"),
    (31, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_archive_equality_and_future"),
    (32, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_unproved_negative_authority_fails"),
    (33, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_gap_proofs_and_incomplete_subsets"),
    (34, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_market_clock_is_not_feature_or_session_cutoff"),
    (35, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_split_uses_actual_consumption_only"),
    (36, "IMPLEMENTED_L2_TEST", "test_cross_day_admission.py", "test_schedule_archive_gate_and_identity"),
    (37, "IMPLEMENTED_L2_TEST", "test_cross_day_admission.py", "test_schedule_archive_gate_and_identity"),
    (38, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_selected_revision_identity_even_equal_value"),
    (39, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_multi_spec_sample_end_and_order"),
    (40, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_backing_considered_and_relocation"),
    (41, "IMPLEMENTED_L2_TEST", "test_cross_day_admission.py", "test_exactly_once_and_never_incomplete"),
    (42, "DEFERRED_L3", "Cross-Day multi-source Dataset and Feature-side TS2 authority; L2 proves Feature PIT independence.", None),
    (43, "PRESERVED_LEGACY_REGRESSION", "test_multi_source_feature_identity.py", None),
    (44, "DEFERRED_L3", "New Dataset cohort/old-reader rejection needs L3. Existing A4 reader regressions remain unchanged.", None),
    (45, "IMPLEMENTED_L2_TEST", "test_cross_day_admission.py", "test_only_static_fingerprint_reads"),
    (46, "IMPLEMENTED_L2_TEST", "test_cross_day_identity.py", "test_frozen_l1_digest"),
    (47, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_zero_samples_and_finite_horizon"),
    (48, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_missing_anchor_does_not_substitute"),
    (49, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_incomplete_precedence_keeps_proof_obligations"),
    (50, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_conflict_fails_before_archive_filter"),
    (51, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_unproved_negative_authority_fails"),
    (52, "IMPLEMENTED_L2_TEST", "test_cross_day_admission.py", "test_exactly_once_and_never_incomplete"),
    (53, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_zero_samples_and_finite_horizon"),
    (54, "DEFERRED_L3", "Sample generation is forbidden in L2; explicit-sample finite schedule-capacity rejection is tested.", None),
    (55, "IMPLEMENTED_L2_TEST", "test_cross_day_admission.py", "test_only_static_fingerprint_reads"),
    (56, "IMPLEMENTED_L2_TEST", "test_cross_day_admission.py", "test_old_authorities_not_widened"),
    (57, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_result_tampering_fails"),
    (58, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_multi_spec_sample_end_and_order"),
    (59, "IMPLEMENTED_L2_TEST", "test_cross_day_identity.py", "test_frozen_l1_digest"),
    (60, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_legacy_source_rejected"),
    (61, "PRESERVED_LEGACY_REGRESSION", "test_dataset_transform_registry.py", None),
    (62, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_legacy_early_close_rejected"),
    (63, "DEFERRED_L3", "Separately reviewed additive TS2 Feature-side authority remains a locked precondition.", None),
    (64, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_backing_considered_and_relocation"),
    (65, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_backing_considered_and_relocation"),
    (66, "IMPLEMENTED_L2_TEST", "test_cross_day_execution.py", "test_gap_backings_are_not_considered_set"),
)


def test_all_design_obligations_accounted():
    assert [row[0] for row in CANARIES] == list(range(1, 67))
    assert sum(row[1] == "IMPLEMENTED_L2_TEST" for row in CANARIES) == 57
    assert sum(row[1] == "PRESERVED_LEGACY_REGRESSION" for row in CANARIES) == 5
    assert sum(row[1] == "DEFERRED_L3" for row in CANARIES) == 4


@pytest.mark.parametrize("number,phase,target,test_name", CANARIES)
def test_coverage_reference_exists(number, phase, target, test_name):
    if phase == "DEFERRED_L3":
        assert test_name is None
        return
    path = Path(__file__).parent / target
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    if phase == "IMPLEMENTED_L2_TEST":
        assert test_name in functions
    else:
        assert any(name.startswith("test_") for name in functions)
