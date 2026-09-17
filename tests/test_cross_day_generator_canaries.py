"""L3.2 overlay: preserve the historical L3.1 table, close only five obligations."""

import ast
from collections import Counter
from pathlib import Path

import pytest

from test_cross_day_dataset_canary_coverage import CANARIES as L31_CANARIES


L32_TESTS = {
    56: "test_exact_feature_only_request_and_existing_identity",
    57: "test_missing_future_coverage_and_no_tail_anchor_drop",
    58: "test_closed_day_is_explicit_not_inferred_from_bars",
    59: "test_no_execution_no_io_no_clock",
    79: "test_window_cannot_cross_open_and_huge_counts_fail_boundedly",
}
CANARIES = tuple((number, "L3_2_RUNTIME", "test_cross_day_generator.py", L32_TESTS[number])
                 if number in L32_TESTS else (number, phase, target, name)
                 for number, phase, target, name in L31_CANARIES)


def test_all_80_accounted_without_rewriting_l31_history():
    assert [r[0] for r in CANARIES] == list(range(1, 81))
    assert {r[0] for r in L31_CANARIES if r[1] == "L3_2_DEFERRED"} == set(L32_TESTS)
    assert Counter(r[1] for r in CANARIES) == {
        "L3_1_RUNTIME": 58, "L3_2_RUNTIME": 5, "PRESERVED_UPSTREAM": 6,
        "L3_3_DEFERRED": 9, "BOUNDARY": 2,
    }
    assert all(new == old for new, old in zip(CANARIES, L31_CANARIES) if old[0] not in L32_TESTS)


@pytest.mark.parametrize("number,name", L32_TESTS.items())
def test_five_runtime_canaries_have_concrete_tests(number, name):
    tree = ast.parse((Path(__file__).parent / "test_cross_day_generator.py").read_text(encoding="utf-8"))
    functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert name in functions
    if number == 79:
        assert "test_qualified_future_early_close_nonfit_left_to_real_l2" in functions
