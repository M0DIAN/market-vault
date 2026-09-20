"""L3.3 obligation overlay; native evidence is a separate mandatory acceptance gate."""

import ast
from collections import Counter
from pathlib import Path

import pytest

from test_cross_day_generator_canaries import CANARIES as L32_CANARIES


L33_TESTS = {
    2: ("test_cross_day_artifact_reader_boundaries.py", "test_old_readers_reject_cross_day_discriminator"),
    3: ("test_cross_day_artifact_reader_boundaries.py", "test_reader_rejects_old_manifest_discriminators"),
    38: ("test_cross_day_artifact_reader_boundaries.py", "test_relocation_and_full_observation_proofs"),
    39: ("test_cross_day_artifact_manifest.py", "test_built_at_changes_only_physical_metadata"),
    40: ("test_cross_day_artifact_reader_boundaries.py", "test_output_root_independence"),
    61: ("test_cross_day_artifact_reader_boundaries.py", "test_reader_never_reexecutes_upstream_or_enrolls"),
    75: ("test_cross_day_artifact_reader_physical.py", "test_second_physical_pass_rejects_identical_byte_object_replacement"),
    76: ("test_cross_day_artifact_publication_state.py", "test_partial_staging_cleanup_requires_no_manifest_or_seal"),
    77: ("test_cross_day_artifact_publication_state.py", "test_simulated_full_orchestration_and_existing_idempotence"),
}
CANARIES = tuple((number, "L3_3_TEST_OBLIGATION", *L33_TESTS[number]) if number in L33_TESTS else row
                 for row in L32_CANARIES for number in (row[0],))
NATIVE_QUALIFICATION_REQUIRED = (75, 76)


def test_all_80_canaries_accounted_with_historical_tables_unchanged():
    assert [r[0] for r in CANARIES] == list(range(1, 81))
    assert {r[0] for r in L32_CANARIES if r[1] == "L3_3_DEFERRED"} == set(L33_TESTS)
    assert Counter(r[1] for r in CANARIES) == {
        "L3_1_RUNTIME": 58, "L3_2_RUNTIME": 5, "PRESERVED_UPSTREAM": 6,
        "L3_3_TEST_OBLIGATION": 9, "BOUNDARY": 2,
    }
    assert all(new == old for new, old in zip(CANARIES, L32_CANARIES) if old[0] not in L33_TESTS)
    assert NATIVE_QUALIFICATION_REQUIRED == (75, 76)


@pytest.mark.parametrize("number,target", L33_TESTS.items())
def test_nine_l33_obligations_have_concrete_tests(number, target):
    filename, name = target
    tree = ast.parse((Path(__file__).parent / filename).read_text(encoding="utf-8"))
    assert name in {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
