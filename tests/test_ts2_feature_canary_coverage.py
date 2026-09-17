"""Explicit accounting: 43 TS2 runtime canaries, 3 legacy, 1 boundary, 1 deferred."""

import ast
from pathlib import Path

import pytest


RUNTIME = "IMPLEMENTED_TS2_FEATURE_TEST"
LEGACY = "PRESERVED_LEGACY_REGRESSION"
BOUNDARY = "BOUNDARY_ASSERTION"
DEFERRED = "DEFERRED_DATASET_JOIN"
EXECUTION = "test_ts2_feature_execution.py"
BOUNDARIES = "test_ts2_feature_boundaries.py"

CANARIES = (
    (1, RUNTIME, EXECUTION, "test_legacy_and_unknown_rejected_even_empty"),
    (2, RUNTIME, EXECUTION, "test_eight_real_formulas"),
    (3, LEGACY, "test_cross_day_admission.py", "test_old_authorities_not_widened"),
    (4, LEGACY, "test_dataset_transform_registry.py", None),
    (5, RUNTIME, BOUNDARIES, "test_old_layers_and_pit_selection_never_invoked"),
    (6, RUNTIME, EXECUTION, "test_scope_rejected"),
    (7, RUNTIME, EXECUTION, "test_clocks_equality_null_and_future"),
    (8, RUNTIME, EXECUTION, "test_clocks_equality_null_and_future"),
    (9, RUNTIME, EXECUTION, "test_clocks_equality_null_and_future"),
    (10, RUNTIME, EXECUTION, "test_conflict_precedes_clock_filter"),
    (11, RUNTIME, EXECUTION, "test_conflict_precedes_clock_filter"),
    (12, RUNTIME, EXECUTION, "test_identical_backing_rows_order_and_context"),
    (13, RUNTIME, EXECUTION, "test_source_pin_gap_and_membership_closure"),
    (14, RUNTIME, EXECUTION, "test_sample_identity_tamper"),
    (15, RUNTIME, EXECUTION, "test_identical_backing_rows_order_and_context"),
    (16, RUNTIME, BOUNDARIES, "test_relocation_is_in_memory_only"),
    (17, RUNTIME, BOUNDARIES, "test_fixed_registry_is_eight_immutable_static_functions"),
    (18, RUNTIME, BOUNDARIES, "test_source_failure_and_wrong_module_binding"),
    (19, RUNTIME, BOUNDARIES, "test_source_normalization_and_real_content_change"),
    (20, RUNTIME, BOUNDARIES, "test_source_path_mtime_cwd_are_not_identity"),
    (21, RUNTIME, BOUNDARIES, "test_coordinated_forgery_and_direct_construction"),
    (22, RUNTIME, BOUNDARIES, "test_coordinated_forgery_and_direct_construction"),
    (23, RUNTIME, BOUNDARIES, "test_deep_immutability_and_caller_aliases"),
    (24, RUNTIME, EXECUTION, "test_exact_spec_contract"),
    (25, RUNTIME, EXECUTION, "test_all_selected_numeric_inputs_fail_closed"),
    (26, RUNTIME, EXECUTION, "test_huge_window_and_insufficient_are_bounded"),
    (27, RUNTIME, EXECUTION, "test_huge_window_and_insufficient_are_bounded"),
    (28, RUNTIME, EXECUTION, "test_noncontiguous_tail_never_searches_older_window"),
    (29, RUNTIME, EXECUTION, "test_gap_outside_tail_is_not_exclusion"),
    (30, RUNTIME, EXECUTION, "test_dst_and_qualified_early_close_without_schedule"),
    (31, RUNTIME, EXECUTION, "test_dst_and_qualified_early_close_without_schedule"),
    (32, RUNTIME, EXECUTION, "test_eight_real_formulas"),
    (33, RUNTIME, EXECUTION, "test_formula_domain_errors_are_hard"),
    (34, RUNTIME, EXECUTION, "test_eight_real_formulas"),
    (35, RUNTIME, EXECUTION, "test_zero_samples_specs_and_both"),
    (36, RUNTIME, EXECUTION, "test_zero_samples_specs_and_both"),
    (37, RUNTIME, EXECUTION, "test_zero_samples_specs_and_both"),
    (38, RUNTIME, EXECUTION, "test_mixed_values_participate_in_identity"),
    (39, RUNTIME, EXECUTION, "test_identical_backing_rows_order_and_context"),
    (40, RUNTIME, "test_ts2_feature_identity.py", "test_frozen_digest"),
    (41, RUNTIME, BOUNDARIES, "test_schedule_label_and_a3_independence"),
    (42, RUNTIME, BOUNDARIES, "test_schedule_label_and_a3_independence"),
    (43, DEFERRED, "Future Dataset join is not implemented or authorized.", None),
    (44, RUNTIME, BOUNDARIES, "test_source_normalization_and_real_content_change"),
    (45, RUNTIME, BOUNDARIES, "test_only_eight_static_source_reads_no_other_io"),
    (46, RUNTIME, BOUNDARIES, "test_only_eight_static_source_reads_no_other_io"),
    (47, LEGACY, "test_cross_day_canary_coverage.py", None),
    (48, BOUNDARY, BOUNDARIES, "test_no_dataset_or_provider_exports_and_no_temporal_authority"),
)


def test_all_design_canaries_accounted():
    assert [r[0] for r in CANARIES] == list(range(1, 49))
    assert {phase: sum(r[1] == phase for r in CANARIES) for phase in (RUNTIME, LEGACY, BOUNDARY, DEFERRED)} == {
        RUNTIME: 43, LEGACY: 3, BOUNDARY: 1, DEFERRED: 1}
    assert CANARIES[42][1] == DEFERRED


@pytest.mark.parametrize("number,phase,path,function", CANARIES)
def test_canary_reference_exists(number, phase, path, function):
    if phase == DEFERRED:
        assert number == 43 and function is None
        return
    tree = ast.parse((Path(__file__).parent / path).read_text(encoding="utf-8"))
    functions = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert function in functions if function else any(f.startswith("test_") for f in functions)
