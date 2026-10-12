"""Complete saved inner families, actual Q6 cost reversals and fail-closed choices."""

from collections import Counter
from dataclasses import asdict
from fractions import Fraction
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from market_vault.backtest.intraday import IntradayExecutionPolicy, _digest as execution_digest
from market_vault.research import intraday_inner_cost_sensitivity as sensitivity
from market_vault.research import intraday_threshold_selection as threshold
from market_vault.research.intraday_data import canonical_json, digest
from market_vault.research.strategy_experiment import StrategyExperiment
from test_intraday_ml_procedures_stress import _short_study, prohibit_sources_and_selection
from test_strategy_intraday_threshold_selection import economic_grid, resigned


ROOT = Path(__file__).resolve().parents[1]


def _prohibit_source_fit_and_test(monkeypatch):
    prohibit_sources_and_selection(monkeypatch)
    from market_vault.research import intraday_final_test, strategy_experiment
    def forbidden(*args, **kwargs):
        pytest.fail("inner cost sensitivity entered source replay or Freeze/TEST")
    monkeypatch.setattr(strategy_experiment, "replay_strategy_experiment", forbidden)
    for name in ("freeze_intraday_candidate", "run_intraday_final_test"):
        monkeypatch.setattr(intraday_final_test, name, forbidden)


def _kernel_calls(monkeypatch):
    calls, execute = [], sensitivity.run_intraday_execution
    def recorded(**kwargs):
        calls.append(kwargs)
        return execute(**kwargs)
    monkeypatch.setattr(sensitivity, "run_intraday_execution", recorded)
    return calls


def _installed_cli(case, snapshot, expected, tmp_path):
    isolated = tmp_path / "study.json"
    isolated.write_bytes(snapshot.content)
    launcher = str(Path(sys.executable).with_name("market-vault.exe" if os.name == "nt" else "market-vault"))
    command = [launcher, "--settings", str(tmp_path / "absent.yaml"),
               "research-intraday-inner-cost-sensitivity", "--study"]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    failed = subprocess.run([*command, str(tmp_path / "missing.json")], cwd=tmp_path, env=env,
                            text=True, capture_output=True, timeout=30)
    assert failed.returncode == 1 and not failed.stdout
    assert json.loads(failed.stderr)["status"] == "FAILED"
    hidden = []
    try:
        for path in (case.path, case.data.path):
            moved = path.with_name(path.name + ".q53-hidden")
            path.rename(moved)
            hidden.append((moved, path))
        process = subprocess.run([*command, str(isolated)], cwd=tmp_path, env=env,
                                 text=True, capture_output=True, timeout=120)
        assert process.returncode == 0, process.stderr
        payload = json.loads(process.stdout)
        assert payload["status"] == "SUCCESS"
        assert payload["result_schema_version"] == sensitivity.INTRADAY_INNER_COST_SENSITIVITY_VERSION
        assert payload["report"] == expected
    finally:
        for moved, path in hidden:
            moved.rename(path)
    assert isolated.read_bytes() == snapshot.content


@pytest.mark.parametrize("kind,family_size", (("q31", 4), ("q36", 24)))
def test_real_complete_zero_accounts_fixed_forecasts_full_family_and_saved_only_cli(
        procedure_comparison_case, tmp_path, monkeypatch, kind, family_size):
    case = procedure_comparison_case
    snapshot, _ = case.studies[kind]
    paths = [case.path, case.data.path, *(path for _, path in case.studies.values())]
    before = {path: sha256(path.read_bytes()).digest() for path in paths}
    source = snapshot.as_dict()
    saved = source["report"]
    original_windows = [row["inner"] for row in saved["outer_folds"]] + [saved["final_dev"]]
    assert len(original_windows) == 5
    _prohibit_source_fit_and_test(monkeypatch)
    calls = _kernel_calls(monkeypatch)
    report = sensitivity.analyze_intraday_inner_cost_sensitivity(snapshot)
    assert report["status"] == "AVAILABLE" and report["unavailable_reasons"] == []
    assert report["experiment_id"] == snapshot.experiment_id and report["source_status"] == "AVAILABLE"
    assert report["source_selection"] == source["plan"]["selection"]
    assert report["source_method"] == saved["method"] and report["return_basis"] == saved["return_basis"]
    assert report["sample"] == {"outer_window_count": 4, "final_dev_window_count": 1, "family_size": family_size,
                                "scenario_count": 15, "available_scenario_count": 15}
    assert report["evidence"] == {"scope": "RECORDED_INNER_FIXED_FORECAST_REEXECUTION", "source_reconstructed": False,
        "models_refitted": False, "forecasts_changed": False, "execution_replayed": True,
        "outer_execution_replayed": False, "test_evaluated": False}
    assert report["method"]["additional_slippage_bps"] == [0, 5, 10]
    assert report["method"]["objective_and_gap_unit"] == "RATIO"
    assert report["method"]["cost_unit"] == "NORMALIZED_CASH"
    # All 20 Q31 and 120 Q36 zero accounts are actually reexecuted exactly
    # once; subsequent costs retain the exact inner support and decisions.
    assert len(calls) == len(original_windows) * family_size * 3
    remaining_calls = iter(calls)
    for index, (actual, original) in enumerate(zip(report["windows"], original_windows, strict=True)):
        assert actual["fixed_evidence"] == original
        assert actual["window_index"] == index
        assert actual["scope"] == ("OUTER_FOLD" if index < 4 else "FINAL_DEV")
        assert actual["fold_id"] == (saved["outer_folds"][index]["fold_id"] if index < 4 else None)
        assert actual["original"] == {key: original[key] for key in ("selected_index", "selected_recipe")}
        baseline = actual["baseline"]
        assert baseline["status"] == "AVAILABLE" and baseline["excluded_identity_fields"] == []
        assert baseline["selected_index_matches"] and baseline["selected_recipe_matches"]
        for check, old in zip(baseline["member_checks"], original["family_results"], strict=True):
            assert check["matches"] and check["different_fields"] == []
            assert check["source_execution_id"] == check["reexecuted_execution_id"] == old["execution"]["execution_id"]
        assert [row["additional_slippage_bps"] for row in actual["scenarios"]] == [0, 5, 10]
        for scenario in actual["scenarios"]:
            added = scenario["additional_slippage_bps"]
            assert scenario["status"] == "AVAILABLE"
            assert scenario["member_counts"] == {"declared": family_size, "recorded": family_size,
                                                 "executed": family_size, "available": family_size}
            assert [row["candidate_index"] for row in scenario["members"]] == list(range(family_size))
            for member, old in zip(scenario["members"], original["family_results"], strict=True):
                call = next(remaining_calls)
                assert call["sessions"] == tuple(original["sessions"])
                assert call["prices"] == tuple(original["prices"])
                assert canonical_json(call["decisions"]) == canonical_json(old["execution"]["decisions"])
                assert call["interval"] == old["execution"]["interval"]
                policy = {**old["execution"]["policy"], "slippage_bps": old["execution"]["policy"]["slippage_bps"] + added}
                assert asdict(call["policy"]) == scenario["execution_policy"] == policy
                assert member["source_execution_id"] == old["execution"]["execution_id"]
                assert member["metrics"] == member["execution"]["metrics"]
                if kind == "q36":
                    assert member["recipe"] == old["strategy"]
                else:
                    assert member["recipe"] == {**original["selected_recipe"], "threshold": old["threshold"]}
                if added == 0:
                    assert canonical_json(member["execution"]) == canonical_json(old["execution"])
            if added == 0:
                assert scenario["selected_index"] == original["selected_index"] and not scenario["changed_choice"]
                assert scenario["selected_recipe"] == original["selected_recipe"]
    assert next(remaining_calls, None) is None
    assert [(row["scope"], row["additional_slippage_bps"], row["declared_window_count"], row["eligible_window_count"])
            for row in report["choice_changes"]] == [(scope, cost, count, count)
                for scope, count in (("OUTER_FOLD", 4), ("FINAL_DEV", 1)) for cost in (0, 5, 10)]
    assert all(row["changed_choice_count"] == row["changed_choice_rate"] == 0
               for row in report["choice_changes"] if row["additional_slippage_bps"] == 0)
    assert report["sensitivity_id"] == digest({key: value for key, value in report.items() if key != "sensitivity_id"})
    if kind == "q36":
        _installed_cli(case, snapshot, report, tmp_path)
    assert all(sha256(path.read_bytes()).digest() == content for path, content in before.items())


def _fill_oracle(exit_prices, commission, slippage):
    """Independent rational entry/exit cash and costs for the known fills."""
    c, s = Fraction(commission, 10000), Fraction(slippage, 10000)
    cash, fees, slips = Fraction(1), Fraction(0), Fraction(0)
    for exit_price in exit_prices:
        quantity = cash / (100 * (1 + s) * (1 + c))
        fees += quantity * (100 * (1 + s) + exit_price * (1 - s)) * c
        slips += quantity * (100 + exit_price) * s
        cash = quantity * exit_price * (1 - s) * (1 - c)
    return float(cash), float(fees), float(slips)


@pytest.mark.parametrize("flat", (False, True))
def test_actual_fill_cost_recipe_reversal_and_first_declared_ties(monkeypatch, flat):
    sessions, prices, predictions = economic_grid()
    if flat:
        predictions = [{**row, "score": 0.0, "target": "FLAT"} for row in predictions]
    policy = IntradayExecutionPolicy(3, 0)
    strategy = {"kind": "RIDGE", "name": "Controlled fixed forecasts", "alpha": 1000.0, "threshold": 0.0}
    family, chosen = threshold._threshold_accounts(predictions, sessions, prices, "5m", policy)
    # This is a controlled numerical window, not a fabricated saved study.
    window = {"sessions": sessions, "prices": prices, "predictions": predictions, "family_results": family,
        "selected_index": chosen, "selected_recipe": {**strategy, "threshold": family[chosen]["threshold"]},
        "validation_days": [row["trading_day"] for row in sessions], "unavailable_reason": None}
    _prohibit_source_fit_and_test(monkeypatch)
    actual = sensitivity._window_sensitivity(window, source_strategy=strategy, source_policy=asdict(policy),
        source_status="AVAILABLE", interval="5m", joint_family=False, declared_family_size=4, window_index=0,
        fold_index=0, fold_id="controlled-inner-window")
    assert actual["baseline"]["status"] == "AVAILABLE"
    exits = [[], [], [], []] if flat else [[Fraction(1001, 10), Fraction(101)], [Fraction(101)], [Fraction(101)], []]
    assert [row["selected_index"] for row in actual["scenarios"]] == ([0, 0, 0] if flat else [0, 1, 1])
    for scenario in actual["scenarios"]:
        added = scenario["additional_slippage_bps"]
        assert scenario["selected_recipe"] == {**strategy, "threshold": 0.0 if flat or added == 0 else .0005}
        assert scenario["changed_choice"] is (not flat and added != 0)
        assert scenario["tied_best_indices"] == (list(range(4)) if flat else [0] if added == 0 else [1, 2])
        assert scenario["runner_up_index"] == (1 if flat or added == 0 else 2)
        for member, trades in zip(scenario["members"], exits, strict=True):
            cash, commission, slippage = _fill_oracle(trades, 3, added)
            assert member["metrics"]["final_cash"] == pytest.approx(cash, abs=1e-14)
            assert member["metrics"]["total_return"] == pytest.approx(cash - 1, abs=1e-14)
            assert member["metrics"]["commission_total"] == pytest.approx(commission, abs=1e-14)
            assert member["metrics"]["slippage_total"] == pytest.approx(slippage, abs=1e-14)
            assert member["metrics"]["trade_count"] == len(trades)
        expected = sorted((_fill_oracle(trades, 3, added)[0] for trades in exits), reverse=True)
        assert scenario["best_runner_up_gap"] == pytest.approx(expected[0] - expected[1], abs=1e-14)
        if flat or added != 0:
            assert scenario["best_runner_up_gap"] == 0.0


def test_full_zero_ledger_mismatch_blocks_only_its_window(procedure_comparison_case, monkeypatch):
    root = procedure_comparison_case.studies["q31"][0].as_dict()
    execution = root["report"]["outer_folds"][0]["inner"]["family_results"][0]["execution"]
    execution["ledger"][0]["reason"] = "Saved semantic evidence differs"
    execution["execution_id"] = execution_digest({key: value for key, value in execution.items() if key != "execution_id"})
    # The immutable grammar admits this complete, resealed account. Q53 must
    # still require its numerical execution to reproduce every field.
    study = StrategyExperiment(resigned(root))
    _prohibit_source_fit_and_test(monkeypatch)
    calls = _kernel_calls(monkeypatch)
    report = sensitivity.analyze_intraday_inner_cost_sensitivity(study)
    assert report["status"] == "PARTIAL" and report["sample"]["available_scenario_count"] == 12
    window = report["windows"][0]
    assert window["status"] == "UNAVAILABLE"
    baseline = window["baseline"]
    assert baseline["unavailable_reason"] == "ZERO_ADDED_COST_REPRODUCTION_FAILED"
    assert baseline["selected_index_matches"] and baseline["selected_recipe_matches"]
    assert baseline["member_checks"][0]["different_fields"] == ["execution_id", "ledger"]
    assert all(row["matches"] for row in baseline["member_checks"][1:])
    for scenario in window["scenarios"]:
        assert scenario["unavailable_reason"] == "ZERO_ADDED_COST_REPRODUCTION_FAILED"
        assert scenario["selected_index"] is scenario["selected_recipe"] is scenario["changed_choice"] is None
        assert len(scenario["members"]) == 4
        assert scenario["member_counts"]["executed"] == (0 if scenario["additional_slippage_bps"] else 4)
    assert len(calls) == 52  # Failed window runs four zero accounts and no pressure accounts.
    assert all(row["status"] == "AVAILABLE" for row in report["windows"][1:])
    assert all(row["eligible_window_count"] == 3 for row in report["choice_changes"] if row["scope"] == "OUTER_FOLD")


def test_one_failed_member_keeps_whole_family_without_partial_winner(procedure_comparison_case, monkeypatch):
    study = procedure_comparison_case.studies["q31"][0]
    first_day = study.as_dict()["report"]["outer_folds"][0]["inner"]["validation_days"][0]
    _prohibit_source_fit_and_test(monkeypatch)
    calls, execute = Counter(), sensitivity.run_intraday_execution
    def fail_one(**kwargs):
        key = kwargs["sessions"][0]["trading_day"], kwargs["policy"].slippage_bps
        calls[key] += 1
        if key == (first_day, 7) and calls[key] == 2:
            raise ValueError("controlled second member failure")
        return execute(**kwargs)
    monkeypatch.setattr(sensitivity, "run_intraday_execution", fail_one)
    report = sensitivity.analyze_intraday_inner_cost_sensitivity(study)
    assert report["status"] == "PARTIAL" and report["sample"]["available_scenario_count"] == 14
    failed = report["windows"][0]["scenarios"][1]
    assert failed["unavailable_reason"] == "INCOMPLETE_INNER_FAMILY"
    assert "member 1" in failed["detail"]
    assert failed["selected_index"] is failed["selected_recipe"] is failed["changed_choice"] is None
    assert failed["best_runner_up_gap"] is None and failed["tied_best_indices"] == []
    assert failed["member_counts"] == {"declared": 4, "recorded": 4, "executed": 3, "available": 3}
    assert [row["status"] for row in failed["members"]] == ["AVAILABLE", "UNAVAILABLE", "AVAILABLE", "AVAILABLE"]
    assert failed["members"][1]["execution"] is failed["members"][1]["metrics"] is None
    assert all(row["execution"] is not None for row in (failed["members"][0], *failed["members"][2:]))
    assert sum(calls.values()) == 60 and all(count == 4 for count in calls.values())
    assert all(row["baseline"]["status"] == "AVAILABLE" for row in report["windows"])
    count = report["choice_changes"][1]
    assert count["scope"] == "OUTER_FOLD" and count["status"] == "PARTIAL"
    assert count["eligible_window_count"] == 3 and count["unavailable_window_count"] == 1
    assert all(row["eligible_window_count"] == 1 for row in report["choice_changes"] if row["scope"] == "FINAL_DEV")


def test_invalid_added_policy_is_preserved_and_never_clipped(procedure_comparison_case, tmp_path, monkeypatch):
    study, path, _ = _short_study(procedure_comparison_case, tmp_path, monkeypatch, kind="q31", slippage=9996)
    before = path.read_bytes()
    _prohibit_source_fit_and_test(monkeypatch)
    calls = _kernel_calls(monkeypatch)
    report = sensitivity.analyze_intraday_inner_cost_sensitivity(study)
    assert report["status"] == "PARTIAL"
    assert len(calls) == len(report["windows"]) * 4
    assert all(call["policy"].slippage_bps == 9996 for call in calls)
    for window in report["windows"]:
        assert window["baseline"]["status"] == "AVAILABLE"
        for scenario in window["scenarios"][1:]:
            assert scenario["unavailable_reason"] == "SCENARIO_POLICY_UNAVAILABLE"
            assert "[0, 10000)" in scenario["detail"]
            assert scenario["execution_policy"]["slippage_bps"] == 9996 + scenario["additional_slippage_bps"]
            assert scenario["selected_index"] is scenario["changed_choice"] is None
            assert len(scenario["members"]) == 4 and all(row["execution"] is None for row in scenario["members"])
    assert all(row["changed_choice_count"] is row["changed_choice_rate"] is None
               for row in report["choice_changes"] if row["additional_slippage_bps"] != 0)
    assert path.read_bytes() == before


@pytest.mark.parametrize("kind,family_size", (("q31", 4), ("q36", 24)))
def test_whole_study_unavailable_retains_unexecuted_later_windows_and_no_zero_rate(
        procedure_comparison_case, tmp_path, monkeypatch, kind, family_size):
    study, _, _ = _short_study(procedure_comparison_case, tmp_path, monkeypatch, kind=kind, minimum=14)
    saved = study.as_dict()["report"]
    _prohibit_source_fit_and_test(monkeypatch)
    monkeypatch.setattr(sensitivity, "run_intraday_execution", lambda **kwargs: pytest.fail("unexecuted study ran Q6"))
    report = sensitivity.analyze_intraday_inner_cost_sensitivity(study)
    assert report["status"] == "UNAVAILABLE" and report["unavailable_reason"] == "SOURCE_STUDY_UNAVAILABLE"
    assert report["source_unavailable_reasons"] == saved["unavailable_reasons"]
    originals = [row["inner"] for row in saved["outer_folds"]] + [saved["final_dev"]]
    assert any(row["unavailable_reason"] is None for row in originals)
    assert all(row["family_results"] == [] for row in originals)
    assert len(report["windows"]) == len(originals) and not report["evidence"]["execution_replayed"]
    for window, original in zip(report["windows"], originals, strict=True):
        assert window["fixed_evidence"] == original and window["source_unavailable_reason"] == original["unavailable_reason"]
        assert window["baseline"]["unavailable_reason"] == "SOURCE_STUDY_UNAVAILABLE"
        assert [row["additional_slippage_bps"] for row in window["scenarios"]] == [0, 5, 10]
        for scenario in window["scenarios"]:
            assert scenario["unavailable_reason"] == "SOURCE_STUDY_UNAVAILABLE"
            assert scenario["member_counts"] == {"declared": family_size, "recorded": 0, "executed": 0, "available": 0}
            assert scenario["members"] == [] and scenario["selected_index"] is scenario["selected_recipe"] is None
    assert all(row["unavailable_reason"] == "NO_ELIGIBLE_WINDOWS" and row["eligible_window_count"] == 0
               and row["changed_choice_count"] is row["changed_choice_rate"] is None for row in report["choice_changes"])
    for invalid, message in (({}, "immutable"), (procedure_comparison_case.source, "Q31 or Q36"),
                             (procedure_comparison_case.studies["q25"][0], "Q31 or Q36")):
        with pytest.raises(ValueError, match=message):
            sensitivity.analyze_intraday_inner_cost_sensitivity(invalid)
    if kind == "q31":
        from market_vault import cli, intraday_inner_cost_sensitivity_cli as console
        monkeypatch.setattr(console, "load_strategy_experiment", lambda *args: pytest.fail("custom grid opened a study"))
        with pytest.raises(SystemExit) as rejected:
            cli.main(["research-intraday-inner-cost-sensitivity", "--study", "unused.json", "--additional-slippage-bps", "1"])
        assert rejected.value.code == 2
