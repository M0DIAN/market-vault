"""Shared immutable studies for the Q39-Q41 procedure evidence tests."""

from copy import copy

import pytest

from test_strategy_intraday_procedure_return_uncertainty import procedure_return_case  # noqa: F401


@pytest.fixture(scope="session")
def procedure_comparison_case(procedure_return_case):
    # One fixture definition serves the comparison, family and stress files.
    # No source is built until a test requests it; the original Q35 fixture's
    # study mapping is not mutated when adding the actual Q36 study.
    from market_vault.research.intraday_joint_selection import run_intraday_joint_selection
    from market_vault.research.strategy_experiment import write_strategy_experiment

    case = copy(procedure_return_case)
    candidate = case.source.as_dict()["report"]["groups"][0]["results"][0]
    snapshot = run_intraday_joint_selection(case.path,
        expected_experiment_id=case.source.experiment_id, cost_index=0, candidate_index=0,
        expected_candidate_id=candidate["candidate_id"])
    case.studies = {**case.studies,
        "q36": (snapshot, write_strategy_experiment(snapshot, path=case.path.parent / "q36.json").path)}
    return case
