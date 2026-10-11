"""Fixed decisions, real three-account baselines and independent cash oracles."""

from copy import deepcopy
from datetime import datetime, timedelta
from fractions import Fraction
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

from market_vault.research import intraday_data as data
from market_vault.research import intraday_inner_selection as inner
from market_vault.research import intraday_joint_selection as joint
from market_vault.research import intraday_procedure_stress as stress
from market_vault.research import intraday_research as research
from market_vault.research import intraday_signal_delay as delay_engine
from market_vault.research import intraday_threshold_selection as threshold
from market_vault.research.intraday_data import digest
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.strategy_experiment import write_strategy_experiment
from test_intraday_ml_procedures_comparison import reseal_procedure_benchmark


ROOT = Path(__file__).resolve().parents[1]
ROLES = ("procedure", "fixed_reference", "benchmark")


def prohibit_sources_and_selection(monkeypatch):
    """The stress action may run real Q6, but never reconstruct or reselect."""
    def forbidden(*args, **kwargs):
        pytest.fail("procedure stress read Q5, fitted or reselected")
    for module, names in (
        (data, ("load_intraday_dataset",)),
        (research, ("load_intraday_dataset", "_prepare_intraday_research", "_fit", "run_intraday_execution")),
        (inner, ("_fit", "_evaluate", "run_intraday_execution", "run_intraday_inner_selection")),
        (threshold, ("_fit", "_evaluate", "run_intraday_execution", "run_intraday_threshold_selection")),
        (joint, ("_fit", "_evaluate", "run_intraday_execution", "run_intraday_joint_selection")),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)


def _kernel_calls(monkeypatch):
    calls, execute = [], stress.run_intraday_execution
    def recorded(**kwargs):
        calls.append(kwargs)
        return execute(**kwargs)
    monkeypatch.setattr(stress, "run_intraday_execution", recorded)
    monkeypatch.setattr(delay_engine, "run_intraday_execution", recorded)
    return calls


def _short_study(case, tmp_path, monkeypatch, *, kind="q36", minimum=20, slippage=2, nonfirst=False):
    """Real short fits reuse only the identical, already admitted Q5 input."""
    days = [row["trading_day"] for row in case.data.as_dict()["report"]["sessions"]]
    comparison = deepcopy(case.plan)
    comparison["walk_forward"] = {"minimum_train_days": minimum, "validation_days": 5, "step_days": 5}
    comparison["split"].update(train_end_day=days[minimum - 1], validation_end_day=days[24])
    comparison["execution"]["slippage_bps"] = slippage
    plan = ({"plan_schema_version": research.INTRADAY_DIAGNOSTICS_PLAN_VERSION,
             "comparison_plan": comparison, "strategy_name": comparison["strategies"][0]["name"],
             "parameter_axes": [{"parameter": "alpha", "values": [.5, 1000.]}],
             "cost_scenarios": [{"commission_bps": 0, "slippage_bps": 0},
                                {"commission_bps": 3, "slippage_bps": slippage}]} if nonfirst else comparison)
    with monkeypatch.context() as setup:
        def admitted_data(path):
            assert Path(path).resolve() == case.data.path.resolve()
            return case.data
        setup.setattr(research, "load_intraday_dataset", admitted_data)
        source = create_intraday_experiment(plan=plan, report=research.run_intraday_research(plan))
        source_path = write_strategy_experiment(source, path=tmp_path / "source.json").path
        index = 1 if nonfirst else 0
        reference = source.as_dict()["report"]["groups"][index]["results"][index]
        run = {"q25": inner.run_intraday_inner_selection, "q31": threshold.run_intraday_threshold_selection,
               "q36": joint.run_intraday_joint_selection}[kind]
        study = run(source_path, expected_experiment_id=source.experiment_id, cost_index=index, candidate_index=index,
                    expected_candidate_id=reference["candidate_id"])
    path = write_strategy_experiment(study, path=tmp_path / "study.json").path
    return study, path, source


def _all_unavailable(report, reason):
    assert report["status"] == "UNAVAILABLE" and report["unavailable_reason"] == reason
    assert report["scenario_counts"] == {"declared": 9, "available": 0, "unavailable": 9}
    for scenario in report["scenarios"]:
        assert scenario["status"] == "UNAVAILABLE" and scenario["unavailable_reason"] == reason
        assert tuple(scenario["accounts"]) == ROLES
        for account in scenario["accounts"].values():
            assert account["execution"] is account["risk"] is None
            assert all(row["value"] is None and row["unavailable_reason"] for row in account["metrics"].values())
        assert scenario["increment"]["mean"] is None
        assert len(scenario["daily"]) == report["sample"]["sample_count"]
        assert all(row["procedure_minus_fixed_reference"] is None and all(v is None for v in row["returns"].values())
                   for row in scenario["daily"])


def test_real_q36_complete_baselines_fixed_grid_daily_cash_and_cost_oracle(procedure_comparison_case, monkeypatch):
    case = procedure_comparison_case
    snapshot, _ = case.studies["q36"]
    paths = [case.path, case.data.path, *(path for _, path in case.studies.values())]
    before = {path: sha256(path.read_bytes()).digest() for path in paths}
    prohibit_sources_and_selection(monkeypatch)
    calls = _kernel_calls(monkeypatch)
    report = stress.analyze_intraday_procedure_stress(snapshot)
    assert report["status"] == "AVAILABLE" and report["basis"]["matches"]
    assert report["scenario_counts"] == {"declared": 9, "available": 9, "unavailable": 0}
    assert len(calls) == 27  # Three baseline accounts are reused by cell 0.
    assert report["baseline"]["status"] == "AVAILABLE"
    assert report["baseline"]["excluded_identity_fields"] == ["price_evidence_id", "execution_id"]
    assert all(row["status"] == "AVAILABLE" for row in report["availability"]["accounts"])
    assert report["evidence"] == {"scope": "RECORDED_PRICE_GRID_REEXECUTION", "source_reconstructed": False,
                                  "models_refitted": False, "decisions_reselected": False, "execution_replayed": True}
    assert [(s["additional_slippage_bps"], s["delay_bars"]) for s in report["scenarios"]] == [
        (slippage, delay) for slippage in (0, 5, 10) for delay in (0, 1, 2)]
    zero = report["scenarios"][0]
    for name, check in zip(ROLES, report["baseline"]["accounts"], strict=True):
        source = report["accounts"][name]["execution"]
        reproduced = zero["accounts"][name]["execution"]
        assert check["account"] == name and check["matches"]
        assert {k: v for k, v in source.items() if k not in ("price_evidence_id", "execution_id")} == {
            k: v for k, v in reproduced.items() if k not in ("price_evidence_id", "execution_id")}
        assert check["source_execution_id"] != check["reexecuted_execution_id"] == reproduced["execution_id"]
        assert check["source_price_evidence_id"] != reproduced["price_evidence_id"]
    for scenario in report["scenarios"]:
        assert [row["trading_day"] for row in scenario["daily"]] == report["context"]["evaluated_days"]
        oracle = {}
        for name in ROLES:
            side = scenario["accounts"][name]
            original_policy = report["accounts"][name]["execution"]["policy"]
            assert side["execution"]["policy"] == {**original_policy,
                "slippage_bps": original_policy["slippage_bps"] + scenario["additional_slippage_bps"]}
            oracle[name] = [float(Fraction(row["cash_close"]) / Fraction(row["cash_open"]) - 1)
                            for row in side["execution"]["daily"]]
            assert [row["returns"][name] for row in scenario["daily"]] == pytest.approx(oracle[name], abs=1e-15)
            change = side["delta_from_zero"]["total_return"]
            assert change["unit"] == "PERCENTAGE_POINTS"
            assert change["value"] == pytest.approx(100 * (side["metrics"]["total_return"]["value"] -
                zero["accounts"][name]["metrics"]["total_return"]["value"]))
        excess = [a - b for a, b in zip(oracle["procedure"], oracle["fixed_reference"], strict=True)]
        assert [row["procedure_minus_fixed_reference"] for row in scenario["daily"]] == pytest.approx(excess, abs=1e-15)
        assert scenario["increment"]["mean"] == pytest.approx(math.fsum(excess) / len(excess), abs=1e-15)
        assert scenario["increment"]["delta_from_zero"]["unit"] == "PERCENTAGE_POINTS"
        assert scenario["increment"]["delta_from_zero"]["value"] == pytest.approx(
            100 * (scenario["increment"]["mean"] - zero["increment"]["mean"]), abs=1e-13)
    # Independent nonzero commission and additive slippage arithmetic. Use
    # the original raw grid, not the stressed account's recorded fill prices.
    for name in ROLES:
        original = report["accounts"][name]["execution"]
        side = report["scenarios"][4]["accounts"][name]["execution"]  # +5 bp, one-bar delay.
        c, s = Fraction(original["policy"]["commission_bps"]) / 10000, Fraction(original["policy"]["slippage_bps"] + 5) / 10000
        assert c > 0 and s > Fraction(5, 10000) and side["trades"]
        raw = {(row["trading_day"], row["slot"]): Fraction(row["mark_price"])
               for row in original["ledger"] if row["phase"] == "OPEN"}
        factors, commissions, slippages = [], [], []
        for trade in side["trades"]:
            entry, exit_price = [raw[trade["trading_day"], trade[key]] for key in ("entry_slot", "exit_slot")]
            quantity = Fraction(trade["cash_before"]) / (entry * (1 + s) * (1 + c))
            expected_cash = quantity * exit_price * (1 - s) * (1 - c)
            commission = quantity * (entry * (1 + s) + exit_price * (1 - s)) * c
            slippage = quantity * (entry + exit_price) * s
            assert trade["quantity"] == pytest.approx(float(quantity), rel=1e-13)
            assert trade["cash_after"] == pytest.approx(float(expected_cash), rel=1e-13)
            factors.append(float(exit_price / entry * (1 - s) * (1 - c) / ((1 + s) * (1 + c))))
            commissions.append(float(commission))
            slippages.append(float(slippage))
        assert side["metrics"]["final_cash"] == pytest.approx(math.prod(factors), rel=1e-12)
        assert side["metrics"]["commission_total"] == pytest.approx(math.fsum(commissions), rel=1e-12)
        assert side["metrics"]["slippage_total"] == pytest.approx(math.fsum(slippages), rel=1e-12)
    assert report["stress_id"] == digest({k: v for k, v in report.items() if k != "stress_id"})
    assert all(sha256(path.read_bytes()).digest() == value for path, value in before.items())


def test_real_q25_long_flat_tails_cash_days_and_unchanged_benchmark(procedure_comparison_case, monkeypatch):
    snapshot = procedure_comparison_case.studies["q25"][0]
    prohibit_sources_and_selection(monkeypatch)
    report = stress.analyze_intraday_procedure_stress(snapshot)
    assert report["source_kind"] == "INNER_MODEL_SELECTION" and report["status"] == "AVAILABLE"
    assert report["sample"]["account_counts"]["procedure"]["cash_only_day_count"] > 0
    assert any(row["returns"]["procedure"] == 0 for row in report["scenarios"][0]["daily"])
    counts = {row["trading_day"]: row["bar_count"] for row in report["sample"]["sessions"]}
    for delay in (1, 2):
        scenario = report["scenarios"][delay]
        for name in ROLES:
            original = report["accounts"][name]["execution"]
            side = scenario["accounts"][name]
            passed = {row["observation_key"]: row for row in side["execution"]["decisions"]}
            signals = side["signals"]
            assert len(signals["provenance"]) == len(original["decisions"])
            for signal, source in zip(signals["provenance"], original["decisions"], strict=True):
                assert (signal["source_target"], signal["source_score"]) == (source["target"], source["score"])
                assert signal["arrival_slot"] == source["slot"] + delay
                assert signal["arrival_time"] == (datetime.fromisoformat(source["decision_time"]) +
                                                   timedelta(minutes=30 * delay)).isoformat()
                count = counts[source["trading_day"]]
                expected = ("OUTSIDE_SESSION" if source["slot"] + delay >= count else
                            "NO_NEXT_OPEN" if source["slot"] + delay == count - 1 else "FORWARDED")
                assert signal["status"] == expected
                if expected == "OUTSIDE_SESSION":
                    assert not signal["passed_to_kernel"] and signal["derived_decision_key"] is None
                else:
                    derived = passed[signal["derived_decision_key"]]
                    assert derived["trading_day"] == source["trading_day"]
                    assert (derived["target"], derived["score"]) == (source["target"], source["score"])
                    assert derived["observation_key"] != source["observation_key"]
            assert side["signals"] == report["scenarios"][delay + 3]["accounts"][name]["signals"]
        procedure = scenario["accounts"]["procedure"]
        assert {row["source_target"] for row in procedure["signals"]["provenance"]} == {"LONG", "FLAT"}
        assert procedure["signals"]["no_next_open_count"] == 100
        assert procedure["signals"]["outside_session_count"] == 100 * delay
        assert any(row["source_target"] == "FLAT" and row["status"] == "OUTSIDE_SESSION"
                   for row in procedure["signals"]["provenance"])
        benchmark = scenario["accounts"]["benchmark"]
        assert benchmark["execution_policy"]["max_hold_bars"] == max(counts.values()) == 13
        assert benchmark["signals"]["source_count"] == 100
        assert [row["slot"] for row in benchmark["execution"]["decisions"]] == [
            row["slot"] + delay for row in report["accounts"]["benchmark"]["execution"]["decisions"]]
    original_folds = snapshot.as_dict()["report"]["outer_folds"]
    for actual, original in zip(report["member"]["outer_folds"], original_folds, strict=True):
        assert actual["refit"] == original["refit"] and actual["selected_recipe"] == original["inner"]["selected_recipe"]


@pytest.mark.parametrize("fault", ["semantic_ledger", "cash", "basis"])
def test_original_three_account_gate_and_nonnumeric_baseline_mismatch(procedure_comparison_case, monkeypatch, fault):
    def change(execution, reference):
        if fault == "semantic_ledger":
            execution["ledger"][0]["reason"] = "CHANGED_SAVED_REASON"
        elif fault == "cash":
            execution["trades"][0]["commission_total"] += .01
        else:
            execution["ledger"][0]["mark_price"] += 1
    snapshot = reseal_procedure_benchmark(procedure_comparison_case.studies["q36"][0], change)
    prohibit_sources_and_selection(monkeypatch)
    calls = _kernel_calls(monkeypatch)
    report = stress.analyze_intraday_procedure_stress(snapshot)
    expected = {"semantic_ledger": "ZERO_DELAY_REPRODUCTION_FAILED", "cash": "SOURCE_ACCOUNT_UNAVAILABLE",
                "basis": "BASIS_MISMATCH"}[fault]
    _all_unavailable(report, expected)
    assert report["baseline"]["status"] == "UNAVAILABLE"
    if fault == "semantic_ledger":
        assert len(calls) == 3 and report["basis"]["matches"]
        assert all(row["status"] == "AVAILABLE" for row in report["availability"]["accounts"])
        assert [row["matches"] for row in report["baseline"]["accounts"]] == [True, True, False]
        assert report["baseline"]["accounts"][2]["differing_fields"] == ["ledger"]
    else:
        assert not calls


def test_real_short_nonfirst_q36_reference_and_whole_cell_runtime_failure(procedure_comparison_case, tmp_path, monkeypatch):
    study, path, source = _short_study(procedure_comparison_case, tmp_path, monkeypatch, nonfirst=True)
    saved = study.as_dict()["report"]
    assert saved["status"] == "AVAILABLE"
    reference = source.as_dict()["report"]["groups"][1]["results"][1]
    before = path.read_bytes()
    prohibit_sources_and_selection(monkeypatch)
    report = stress.analyze_intraday_procedure_stress(study)
    assert report["status"] == "AVAILABLE" and report["sample"]["sample_count"] == 5
    assert report["source_selection"] == {"cost_index": 1, "candidate_index": 1, "candidate_id": reference["candidate_id"]}
    assert report["accounts"]["fixed_reference"] == reference
    assert report["accounts"]["procedure"] == report["member"]["selected_account"] == saved["selected_account"]
    assert report["member"]["outer_folds"][0]["refit"] == saved["outer_folds"][0]["refit"]
    assert all(row["increment"]["mean"] is not None for row in report["scenarios"])
    # A second role's execution failure discards the whole cell, including the
    # first role's successful account, while the other eight cells still run.
    executed, execute = [], stress.run_intraday_execution
    def fail_second(**kwargs):
        executed.append(1)
        if len(executed) == 2:
            raise ValueError("controlled fixed-reference execution failure")
        return execute(**kwargs)
    monkeypatch.setattr(stress, "run_intraday_execution", fail_second)
    partial = stress.analyze_intraday_procedure_stress(study)
    assert partial["status"] == "PARTIAL" and partial["baseline"]["status"] == "AVAILABLE"
    assert partial["scenario_counts"] == {"declared": 9, "available": 8, "unavailable": 1}
    assert len(executed) == 23  # Cell 1 stops after its second role; baseline uses Q19's alias.
    failed = partial["scenarios"][1]
    assert failed["unavailable_reason"] == "SCENARIO_REEXECUTION_FAILED" and "fixed_reference" in failed["detail"]
    assert all(side["execution"] is side["risk"] is None for side in failed["accounts"].values())
    assert all(row["procedure_minus_fixed_reference"] is None for row in failed["daily"])
    assert path.read_bytes() == before


def test_real_high_slippage_policy_cells_and_settings_independent_cli(procedure_comparison_case, tmp_path, monkeypatch):
    study, path, _ = _short_study(procedure_comparison_case, tmp_path, monkeypatch, kind="q31", slippage=9996)
    assert study.as_dict()["report"]["status"] == "AVAILABLE"
    before = path.read_bytes()
    prohibit_sources_and_selection(monkeypatch)
    calls = _kernel_calls(monkeypatch)
    report = stress.analyze_intraday_procedure_stress(study)
    assert report["source_kind"] == "ECONOMIC_THRESHOLD_SELECTION"
    assert report["status"] == "PARTIAL" and report["baseline"]["status"] == "AVAILABLE"
    assert report["scenario_counts"] == {"declared": 9, "available": 3, "unavailable": 6}
    assert len(calls) == 9 and all(call["policy"].slippage_bps == 9996 for call in calls)
    for scenario in report["scenarios"][3:]:
        assert scenario["unavailable_reason"] == "SCENARIO_POLICY_UNAVAILABLE"
        assert "[0, 10000)" in scenario["detail"]
        for side in scenario["accounts"].values():
            assert side["execution_policy"]["slippage_bps"] == 9996 + scenario["additional_slippage_bps"]
            assert side["execution"] is side["risk"] is None
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "cp1252:strict"}
    command = [sys.executable, "-c", "from market_vault.cli import main; raise SystemExit(main())",
               "--settings", str(tmp_path / "absent.yaml"), "research-intraday-procedure-stress", "--study", str(path)]
    process = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, timeout=120)
    assert process.returncode == 0 and not process.stderr and process.stdout.isascii()
    result = json.loads(process.stdout)
    assert result["status"] == "SUCCESS" and result["result_schema_version"] == stress.INTRADAY_PROCEDURE_STRESS_VERSION
    assert result["report"] == report
    assert path.read_bytes() == before


def test_entry_rejects_ordinary_unavailable_and_custom_grid(procedure_comparison_case, tmp_path, monkeypatch):
    study, path, _ = _short_study(procedure_comparison_case, tmp_path, monkeypatch, kind="q25", minimum=10)
    assert study.as_dict()["report"]["status"] == "UNAVAILABLE"
    prohibit_sources_and_selection(monkeypatch)
    monkeypatch.setattr(stress, "_account_basis", lambda *a: pytest.fail("invalid study entered baseline/grid"))
    for snapshot, message in ((object(), "immutable"), (procedure_comparison_case.source, "explicit saved"),
                              (study, "SOURCE_STUDY_UNAVAILABLE")):
        with pytest.raises(ValueError, match=message):
            stress.analyze_intraday_procedure_stress(snapshot)
    from market_vault import cli, intraday_procedure_stress_cli as console
    monkeypatch.setattr(console, "load_strategy_experiment", lambda *a: pytest.fail("invalid CLI input opened a study"))
    with pytest.raises(SystemExit) as rejected:
        cli.main(["research-intraday-procedure-stress", "--study", str(path), "--delay-bars", "3"])
    assert rejected.value.code == 2
