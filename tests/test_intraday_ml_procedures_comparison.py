"""Direct procedure comparison on real shared DEV studies and cash oracles."""

from copy import deepcopy
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

from market_vault.research import intraday_joint_selection as joint
from market_vault.research import intraday_inner_selection as inner
from market_vault.research import intraday_procedure_comparison as comparison
from market_vault.research import intraday_research as research
from market_vault.research import intraday_return_uncertainty as uncertainty
from market_vault.research import intraday_threshold_selection as threshold
from market_vault.research.intraday_data import digest
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.strategy_experiment import StrategyExperiment, canonical_json, write_strategy_experiment
from test_intraday_experiment import signed
from test_strategy_intraday_inner_objective_sensitivity import prohibit_recomputation
from test_strategy_intraday_procedure_return_uncertainty import procedure_return_case  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def procedure_comparison_case(procedure_return_case):
    case = procedure_return_case
    candidate = case.source.as_dict()["report"]["groups"][0]["results"][0]
    snapshot = joint.run_intraday_joint_selection(case.path,
        expected_experiment_id=case.source.experiment_id, cost_index=0, candidate_index=0,
        expected_candidate_id=candidate["candidate_id"])
    case.studies["q36"] = snapshot, write_strategy_experiment(snapshot, path=case.path.parent / "q36.json").path
    return case


def _values(snapshot):
    return [float(Fraction(row["cash_close"]) / Fraction(row["cash_open"]) - 1)
            for row in snapshot.as_dict()["report"]["selected_account"]["execution"]["daily"]]


def _no_recompute(monkeypatch):
    prohibit_recomputation(monkeypatch)
    for name in ("_evaluate", "_fit", "run_intraday_execution"):
        monkeypatch.setattr(joint, name, lambda *a, **k: pytest.fail("comparison recomputed joint selection"))


def reseal_procedure_benchmark(snapshot, change):
    selected = comparison._procedure(snapshot)
    root, source = selected["root"], selected["source"]
    selection = selected["selection"]
    group = source["report"]["groups"][selection["cost_index"]]
    change(group["benchmark"]["execution"], group["results"][selection["candidate_index"]])
    source = json.loads(signed(source))
    root["report"]["source_experiment"] = source
    root["plan"]["source_experiment"]["experiment_id"] = source["experiment_id"]
    root["report"]["plan_sha256"] = digest(root["plan"])
    root["report"]["benchmark"] = deepcopy(source["report"]["groups"][selection["cost_index"]]["benchmark"])
    key = selected["report_key"]
    root["report"][key] = digest({k: v for k, v in root["report"].items() if k != key})
    root["experiment_id"] = digest({k: v for k, v in root.items() if k != "experiment_id"})
    return StrategyExperiment(canonical_json(root))


@pytest.mark.parametrize("names", [("q25", "q31"), ("q31", "q36")])
def test_real_pair_direction_complete_support_and_recorded_only(procedure_comparison_case, monkeypatch, names):
    case = procedure_comparison_case
    a, b = [case.studies[name][0] for name in names]
    expected_a, expected_b = _values(a), _values(b)
    original = {path: path.read_bytes() for _, path in case.studies.values()}
    _no_recompute(monkeypatch)
    report = comparison.compare_intraday_procedures(a, b)
    assert report["status"] == "AVAILABLE" and report["basis"]["matches"]
    assert report["sample"]["sample_count"] == 100
    assert report["sampling"]["replications"] == 5000 and report["sampling"]["seed"] == 0
    assert report["sampling"]["block_days"] == 5
    assert report["sampling"]["confidence_level"] == .95
    assert not any(report["evidence"][key] for key in ("source_reconstructed", "models_refitted", "execution_replayed"))
    assert all(row["unavailable_reason"] is None for row in report["shared_account_checks"])
    expected = {"A": expected_a, "B": expected_b,
                "B_MINUS_A": [b - a for a, b in zip(expected_a, expected_b, strict=True)]}
    assert any(value != 0 for value in expected["B_MINUS_A"])
    for row in report["statistics"]:
        values = expected[row["series"]]
        assert row["mean"] == pytest.approx(math.fsum(values) / len(values), abs=1e-15)
        assert [day["values"][row["series"]] for day in report["daily"]] == pytest.approx(values, abs=1e-15)
    assert [day["trading_day"] for day in report["daily"]] == report["context"]["evaluated_days"]
    for member, snapshot in zip(report["members"], (a, b), strict=True):
        root = snapshot.as_dict()
        assert member["selected_account"] == root["report"]["selected_account"]
        assert member["experiment_id"] == root["experiment_id"]
        assert len(member["outer_folds"]) == report["sample"]["fold_count"]
        field = "application" if member["source_kind"] == "ECONOMIC_THRESHOLD_SELECTION" else "refit"
        for actual, source in zip(member["outer_folds"], root["report"]["outer_folds"], strict=True):
            assert actual[field] == source[field]
            assert actual["selected_recipe"] == source["inner"]["selected_recipe"]
    assert all(path.read_bytes() == content for path, content in original.items())


def test_one_synchronous_draw_stream_and_reversed_pair(procedure_comparison_case, monkeypatch):
    a, b = [procedure_comparison_case.studies[name][0] for name in ("q25", "q31")]
    draws = []
    def indices(count, block_days, rng):
        assert count == 100 and block_days == 5
        day = len(draws) % 100
        draws.append(day)
        return [day] * count
    monkeypatch.setattr(uncertainty, "_stationary_indices", indices)
    report = comparison.compare_intraday_procedures(a, b, replications=1000)
    assert len(draws) == 1000
    for row in report["statistics"]:
        values = sorted(day["values"][row["series"]] for day in report["daily"] for _ in range(10))
        if len(set(values)) == 1:
            assert row["interval_unavailable_reason"] == "ZERO_SAMPLE_VARIATION"
        else:
            oracle = (values[24] * .025 + values[25] * .975, values[974] * .975 + values[975] * .025)
            assert (row["lower"], row["upper"]) == pytest.approx(oracle, abs=1e-15)
    other = comparison.compare_intraday_procedures(b, a, replications=1000)
    pair, reverse = report["statistics"][2], other["statistics"][2]
    assert reverse["mean"] == pytest.approx(-pair["mean"], abs=1e-15)
    assert (reverse["lower"], reverse["upper"]) == pytest.approx((-pair["upper"], -pair["lower"]), abs=1e-15)
    assert comparison._paired_values((.1, -.2, 0.), (.1, -.2, 0.)) == (0., 0., 0.)


def test_explicit_source_kind_and_complete_common_source_rejection(procedure_comparison_case, monkeypatch):
    case = procedure_comparison_case
    a, b = [case.studies[name][0] for name in ("q25", "q31")]
    _no_recompute(monkeypatch)
    with pytest.raises(ValueError, match="two different"):
        comparison.compare_intraday_procedures(a, a)
    with pytest.raises(ValueError, match="selection study"):
        comparison.compare_intraday_procedures(case.source, b)
    # A hidden cash-flat price change can survive a saved-record grammar; it
    # must not disappear behind the same evaluated dates or named data ID.
    def price(execution, reference):
        assert execution["ledger"][0]["quantity"] == 0
        execution["ledger"][0]["mark_price"] += 1
    changed = reseal_procedure_benchmark(b, price)
    with pytest.raises(ValueError, match="same complete ordinary source"):
        comparison.compare_intraday_procedures(a, changed)
    # Even two consistently changed embedded sources retain the failed raw
    # benchmark/reference basis: pair statistics must not become available.
    changed_a = reseal_procedure_benchmark(a, price)
    blocked = comparison.compare_intraday_procedures(changed_a, changed)
    assert blocked["status"] == "UNAVAILABLE" and blocked["unavailable_reason"] == "BASIS_MISMATCH"
    assert blocked["statistics"][2]["mean"] is None
    assert all(row["values"]["B_MINUS_A"] is None for row in blocked["daily"])


def test_explicit_block_gate_keeps_descriptive_cash_evidence(procedure_comparison_case):
    a, b = [procedure_comparison_case.studies[name][0] for name in ("q25", "q36")]
    report = comparison.compare_intraday_procedures(a, b, block_days=100, replications=1000)
    assert report["status"] == "AVAILABLE" and len(report["daily"]) == 100
    assert all(row["mean"] is not None for row in report["statistics"])
    assert all(row["lower"] is None and row["upper"] is None for row in report["statistics"])
    assert report["statistics"][2]["interval_unavailable_reason"] in ("INSUFFICIENT_EXPECTED_BLOCKS", "ZERO_SAMPLE_VARIATION")


def test_unavailable_historical_study_retains_both_identities_without_partial_pair(procedure_comparison_case, tmp_path, monkeypatch):
    plan = deepcopy(procedure_comparison_case.plan)
    plan["walk_forward"]["minimum_train_days"] = 10
    source = create_intraday_experiment(plan=plan, report=research.run_intraday_research(plan))
    path = write_strategy_experiment(source, path=tmp_path / "short-history.json").path
    args = dict(expected_experiment_id=source.experiment_id, cost_index=0, candidate_index=0,
                expected_candidate_id=source.as_dict()["report"]["groups"][0]["results"][0]["candidate_id"])
    a, b = inner.run_intraday_inner_selection(path, **args), threshold.run_intraday_threshold_selection(path, **args)
    _no_recompute(monkeypatch)
    report = comparison.compare_intraday_procedures(a, b)
    assert report["status"] == "UNAVAILABLE" and report["unavailable_reason"] == "SOURCE_STUDY_UNAVAILABLE"
    assert [row["experiment_id"] for row in report["members"]] == [a.experiment_id, b.experiment_id]
    assert report["statistics"] == report["daily"] == []
    assert len(report["unavailable_reasons"]) == 2


def test_settings_independent_cli_success_and_failure(procedure_comparison_case, tmp_path):
    case = procedure_comparison_case
    paths = [str(case.studies[name][1]) for name in ("q25", "q36")]
    command = [sys.executable, "-c", "from market_vault.cli import main; raise SystemExit(main())",
               "--settings", str(tmp_path / "absent.yaml"),
               "research-intraday-procedure-comparison", "--left", paths[0], "--right", paths[1], "--replications", "1000"]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    run = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr
    output = json.loads(run.stdout)
    assert output["status"] == "SUCCESS" and output["report"]["status"] == "AVAILABLE"
    assert output["report"] == comparison.compare_intraday_procedures(
        case.studies["q25"][0], case.studies["q36"][0], replications=1000)
    failed = subprocess.run(command + ["--block-days", "1"], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=30)
    assert failed.returncode == 1 and not failed.stdout
    assert "block_days" in json.loads(failed.stderr)["error"]
