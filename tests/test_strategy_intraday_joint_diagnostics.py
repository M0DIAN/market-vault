"""Actual joint refits, complete-recipe sensitivity and shared cash-day draws."""

from copy import deepcopy
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
from types import SimpleNamespace

import pytest

from market_vault.research import intraday_inner_objective_sensitivity as sensitivity
from market_vault.research import intraday_joint_selection as joint
from market_vault.research import intraday_ml_diagnostics as diagnostics
from market_vault.research import intraday_procedure_return_uncertainty as procedure
from market_vault.research import intraday_research as research
from market_vault.research import intraday_return_uncertainty as uncertainty
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.strategy_experiment import StrategyExperiment, write_strategy_experiment
from test_intraday_research import return_uncertainty_data
from test_strategy_intraday_inner_objective_sensitivity import prohibit_recomputation
from test_strategy_intraday_joint_selection import joint_case  # noqa: F401
from test_strategy_intraday_ml import quadratic_dev_case  # noqa: F401
from test_strategy_intraday_ml_diagnostics import _quality_oracle


ROOT = Path(__file__).resolve().parents[1]


def _prohibit_joint_recomputation(monkeypatch):
    prohibit_recomputation(monkeypatch)
    # Q36 owns direct imported bindings, so patching Q25/Q31 alone is not enough.
    for name in ("_fit", "_evaluate", "run_intraday_execution"):
        monkeypatch.setattr(joint, name, lambda *a, **k: pytest.fail("recorded-only joint diagnostic recomputed"))


def _saved_joint(plan, root):
    source = create_intraday_experiment(plan=plan, report=research.run_intraday_research(plan))
    source_path = write_strategy_experiment(source, path=root / "source.json").path
    candidate = source.as_dict()["report"]["groups"][0]["results"][0]
    study = joint.run_intraday_joint_selection(source_path, expected_experiment_id=source.experiment_id,
        cost_index=0, candidate_index=0, expected_candidate_id=candidate["candidate_id"])
    saved = write_strategy_experiment(study, path=root / "joint.json").path
    return SimpleNamespace(plan=plan, source=source, source_path=source_path, study=study, saved=saved)


@pytest.fixture(scope="session")
def joint_return_case(tmp_path_factory):
    root = tmp_path_factory.mktemp("joint-returns")
    data = return_uncertainty_data(root, target_horizon_bars=2)
    days = [row["trading_day"] for row in data.as_dict()["report"]["sessions"]]
    plan = research.default_intraday_research_plan(data, commission_bps=3, slippage_bps=2)
    plan["feature_fields"] = ["return_2"]
    plan["strategies"] = [{"kind": "RIDGE", "name": "Fixed reference", "alpha": 1000., "threshold": -.0005}]
    plan["split"]["validation_end_day"] = days[119]
    plan["walk_forward"] = {"minimum_train_days": 20, "validation_days": 25, "step_days": 25}
    plan["execution"]["max_hold_bars"] = 2
    # One real ordinary source and one Q36 study; no unrelated Q25/Q31 studies.
    case = _saved_joint(plan, root)
    case.data = data
    return case


def test_real_outer_refits_one_q5_common_target_oracle_and_complete_recipe_rejection(joint_case, monkeypatch):
    data, _, source_path, _, study, saved, _ = joint_case
    original = study.as_dict()["report"]
    before = source_path.read_bytes(), saved.read_bytes()
    calls, load = [], research.load_intraday_dataset
    def loaded(*args, **kwargs):
        calls.append(1)
        return load(*args, **kwargs)
    monkeypatch.setattr(research, "load_intraday_dataset", loaded)
    report = diagnostics.analyze_intraday_ml_prediction_quality(study)
    assert calls == [1] and report["source_kind"] == "JOINT_ECONOMIC_SELECTION"
    assert report["selection_id"] == original["joint_selection_id"]
    assert report["evidence"]["scope"] == "SOURCE_VERIFIED_COMPLETE_ML_PROCEDURE"
    assert report["evidence"]["execution_replayed"]
    assert report["source_selection"] == original["fixed_reference"]
    assert report["method"]["score_boundaries_bps"] == [0., 5., 10., 20.]
    _quality_oracle(report, data)
    for fold, recorded in zip(report["folds"], original["outer_folds"], strict=True):
        assert fold["model"] == recorded["refit"]["model"]
        assert fold["strategy"] == recorded["refit"]["strategy"] == recorded["inner"]["selected_recipe"]
        assert (fold["strategy"]["kind"], fold["strategy"]["alpha"]) != (
            fold["reference_strategy"]["kind"], fold["reference_strategy"]["alpha"])
    expected = original["selected_account"]["predictions"]
    assert [row["scores"]["SELECTED"] for row in report["predictions"]] == [row["score"] for row in expected]
    # The complete-procedure check must catch a correct threshold with either
    # the wrong representation or alpha, before accepting derived forecasts.
    for field, value in (("kind", "QUADRATIC_RIDGE"), ("alpha", 123.)):
        changed = deepcopy(original)
        recipe = changed["outer_folds"][0]["refit"]["strategy"]
        if field == "kind" and recipe[field] == value:
            value = "RIDGE"
        recipe[field] = value
        assert recipe["threshold"] == original["outer_folds"][0]["refit"]["strategy"]["threshold"]
        monkeypatch.setattr(joint, "_evaluate", lambda *a, **k: changed)
        with pytest.raises(ValueError, match="complete saved selection procedure"):
            diagnostics.analyze_intraday_ml_prediction_quality(study)
    assert (source_path.read_bytes(), saved.read_bytes()) == before


def test_independent_24_member_day_omission_changes_model_with_same_threshold():
    days = [f"2025-01-0{index}" for index in range(1, 6)]
    recipes = [{"name": "Fixed reference", **member} for member in joint.FAMILY]
    returns = [[0.] * 5 for _ in range(24)]
    returns[5], returns[13], returns[17] = [.5, -.4, 0., 0., 0.], [.04, .04, 0., 0., 0.], [.04, .04, 0., 0., 0.]
    family = [{"candidate_index": index, "model_index": index // 4, "threshold_index": index % 4,
        "strategy": recipes[index], "execution": {
            "daily": [{"trading_day": day, "return": value} for day, value in zip(days, values, strict=True)],
            "metrics": {"total_return": math.prod(1 + value for value in values) - 1}}}
        for index, values in enumerate(returns)]
    window = {"validation_days": days, "family_results": family, "selected_index": 13,
        "models": [{"model_index": index, "model": {"model_id": str(index)}, "predictions": [index]}
                   for index in range(6)]}
    before = deepcopy(window)
    report = sensitivity._window_sensitivity(window, maximize=True, joint_family=True, window_index=0,
        source_strategy={"kind": "RIDGE", "name": "Fixed reference", "alpha": 999., "threshold": -.01})
    assert report["original"]["selected_index"] == 13 and report["original"]["runner_up_index"] == 17
    assert report["original"]["margin"]["value"] == 0.
    assert [row["selected_index"] for row in report["omissions"]] == [13, 5, 13, 13, 13]
    for day_index, omission in enumerate(report["omissions"]):
        expected = [float(math.prod(1 + Fraction(str(value)) for index, value in enumerate(values) if index != day_index) - 1)
                    for values in returns]
        assert [row["value"] for row in omission["objectives"]] == pytest.approx(expected, abs=1e-14)
        assert [row["recipe"] for row in omission["objectives"]] == recipes
        assert omission["selected_index"] == max(range(24), key=expected.__getitem__)
        assert omission["remaining_complete_target_count"] is None
    original, changed = report["original"]["selected_recipe"], report["omissions"][1]["selected_recipe"]
    assert (original["kind"], original["alpha"]) == ("QUADRATIC_RIDGE", .1)
    assert (changed["kind"], changed["alpha"]) == ("RIDGE", 1.)
    assert original["threshold"] == changed["threshold"] == .0005
    assert report["omissions"][1]["margin"]["value"] == pytest.approx(.46)
    assert report["selection_counts"] == [{"candidate_index": index, "count": 1 if index == 5 else 4 if index == 13 else 0}
                                           for index in range(24)]
    assert report["changed_choice_count"] == 1 and report["fixed_evidence"] == window == before


def test_real_recorded_only_single_decode_full_family_reference_and_short_intervals(joint_case, monkeypatch):
    data, _, source_path, _, study, saved, _ = joint_case
    original = study.as_dict()["report"]
    before = {path: path.read_bytes() for path in (data.path, source_path, saved)}
    _prohibit_joint_recomputation(monkeypatch)
    from market_vault.research import strategy_experiment
    monkeypatch.setattr(strategy_experiment, "write_strategy_experiment", lambda *a, **k: pytest.fail("saved a derived report"))
    calls, decode = [], StrategyExperiment.as_dict
    def decoded(self):
        calls.append(1)
        return decode(self)
    monkeypatch.setattr(StrategyExperiment, "as_dict", decoded)
    report = sensitivity.analyze_intraday_inner_objective_sensitivity(study)
    assert calls == [1] and report["source_kind"] == "JOINT_ECONOMIC_SELECTION"
    assert report["source_selection"] == original["fixed_reference"]
    assert report["sample"] == {"outer_window_count": 2, "final_dev_window_count": 1, "omission_count": 15}
    windows = [fold["inner"] for fold in original["outer_folds"]] + [original["final_dev"]]
    for derived, recorded in zip(report["windows"], windows, strict=True):
        assert derived["fixed_evidence"] == recorded
        assert len(derived["fixed_evidence"]["models"]) == 6
        assert len(derived["original"]["objectives"]) == 24
        assert derived["original"]["selected_recipe"] == recorded["selected_recipe"]
        recipes = [member["strategy"] for member in recorded["family_results"]]
        assert [member["recipe"] for member in derived["original"]["objectives"]] == recipes
        for omission in derived["omissions"]:
            expected = [float(math.prod(1 + Fraction(day["return"]) for day in member["execution"]["daily"]
                                       if day["trading_day"] != omission["omitted_day"]) - 1)
                        for member in recorded["family_results"]]
            assert [member["value"] for member in omission["objectives"]] == pytest.approx(expected, abs=1e-14)
            assert [member["recipe"] for member in omission["objectives"]] == recipes
    calls.clear()
    returns = procedure.analyze_intraday_procedure_return_uncertainty(study)
    assert calls == [1] and returns["source_kind"] == "JOINT_ECONOMIC_SELECTION"
    assert returns["source_selection"] == original["fixed_reference"]
    assert returns["basis"]["matches"] and returns["sample"]["sample_count"] == 10
    assert returns["accounts"]["procedure"] == original["selected_account"]
    assert returns["accounts"]["fixed_reference"] == original["source_experiment"]["report"]["groups"][1]["results"][1]
    assert all(row["mean"] is not None and row["interval_unavailable_reason"] in (
        "INSUFFICIENT_DAILY_RETURNS", "ZERO_SAMPLE_VARIATION") for row in returns["statistics"])
    for result in (report, returns):
        assert not any(result["evidence"][key] for key in ("source_reconstructed", "models_refitted", "execution_replayed"))
    assert all(path.read_bytes() == content for path, content in before.items())


def _cash_values(accounts):
    values = {name: [float(Fraction(row["cash_close"]) / Fraction(row["cash_open"]) - 1)
                     for row in account["execution"]["daily"]] for name, account in accounts.items()}
    for reference in ("fixed_reference", "benchmark"):
        values["procedure_minus_" + reference] = [a - b for a, b in zip(values["procedure"], values[reference], strict=True)]
    return values


def _default_interval_oracle(values):
    # Independent cash-ratio vectors, literal default settings and percentile
    # positions. Do not call the production sampler, mean or quantile helpers.
    generator = random.Random(0)
    draws = {name: [] for name, values in values.items() if len(set(values)) > 1}
    for _ in range(5000):
        sample = [generator.randrange(100)]
        for _ in range(99):
            sample.append(generator.randrange(100) if generator.random() < .2 else (sample[-1] + 1) % 100)
        for name in draws:
            draws[name].append(math.fsum(values[name][index] for index in sample) / 100)
    result = {}
    for name, means in draws.items():
        ordered = sorted(means)
        result[name] = (ordered[124] * .025 + ordered[125] * .975, ordered[4874] * .975 + ordered[4875] * .025)
    return result


def test_actual_100_days_four_folds_default_5000_cash_intervals_and_synchronous_draws(joint_return_case, monkeypatch):
    case = joint_return_case
    before = case.saved.read_bytes(), case.source_path.read_bytes()
    _prohibit_joint_recomputation(monkeypatch)
    report = procedure.analyze_intraday_procedure_return_uncertainty(case.study)
    assert report["source_kind"] == "JOINT_ECONOMIC_SELECTION" and report["basis"]["matches"]
    assert report["sample"]["sample_count"] == 100 and report["sample"]["fold_count"] == 4
    assert report["sample"]["is_contiguous"] and report["sample"]["gap_days"] == []
    assert report["sampling"]["block_days"] == 5 and report["sampling"]["expected_block_count"] == 20.8
    assert report["sampling"]["replications"] == 5000 and report["sampling"]["seed"] == 0
    assert report["sampling"]["confidence_level"] == .95
    assert report["accounts"]["fixed_reference"]["execution"]["policy"]["max_hold_bars"] == 2
    assert report["accounts"]["benchmark"]["execution"]["policy"]["max_hold_bars"] == 13
    assert report["sample"]["account_counts"]["procedure"]["cash_only_day_count"] > 0
    assert [row["series"] for row in report["statistics"]] == list(procedure.SERIES_ORDER)
    expected = _cash_values(report["accounts"])
    intervals = _default_interval_oracle(expected)
    assert "procedure_minus_fixed_reference" in intervals and "procedure_minus_benchmark" in intervals
    for row in report["statistics"]:
        name = row["series"]
        assert [day["values"][name] for day in report["daily"]] == pytest.approx(expected[name], abs=1e-15)
        assert row["mean"] == pytest.approx(math.fsum(expected[name]) / 100, abs=1e-15)
        if name in intervals:
            assert row["interval_unavailable_reason"] is None
            assert (row["lower"], row["upper"]) == pytest.approx(intervals[name], abs=1e-15)
        else:
            assert row["interval_unavailable_reason"] == "ZERO_SAMPLE_VARIATION"
    # A second, prescribed default-sized stream proves that all five series
    # share each draw: independent account streams would exhaust this iterator.
    draws = iter(range(5000))
    def indices(count, block_days, rng):
        assert count == 100 and block_days == 5
        return [next(draws) % 100] * count
    monkeypatch.setattr(uncertainty, "_stationary_indices", indices)
    synchronous = procedure.analyze_intraday_procedure_return_uncertainty(case.study)
    assert next(draws, None) is None
    for row in synchronous["statistics"]:
        if row["series"] not in intervals:
            continue
        ordered = sorted(expected[row["series"]] * 50)
        bounds = ordered[124] * .025 + ordered[125] * .975, ordered[4874] * .975 + ordered[4875] * .025
        assert (row["lower"], row["upper"]) == pytest.approx(bounds, abs=1e-15)
    assert (case.saved.read_bytes(), case.source_path.read_bytes()) == before


def test_real_joint_gap_and_expected_block_gates(joint_return_case, tmp_path):
    blocked = procedure.analyze_intraday_procedure_return_uncertainty(joint_return_case.study, block_days=1000)
    assert all(row["mean"] is not None and row["lower"] is None and row["upper"] is None for row in blocked["statistics"])
    assert all(row["interval_unavailable_reason"] in ("INSUFFICIENT_EXPECTED_BLOCKS", "ZERO_SAMPLE_VARIATION")
               for row in blocked["statistics"])
    plan = deepcopy(joint_return_case.plan)
    plan["walk_forward"]["step_days"] = 26
    case = _saved_joint(plan, tmp_path)
    report = procedure.analyze_intraday_procedure_return_uncertainty(case.study)
    assert report["status"] == "AVAILABLE" and report["basis"]["matches"]
    assert not report["sample"]["is_contiguous"] and len(report["sample"]["gap_days"]) == 2
    assert all(row["mean"] is not None and row["interval_unavailable_reason"] in (
        "GAPPED_EVALUATION_DAYS", "ZERO_SAMPLE_VARIATION") for row in report["statistics"])


def test_unavailable_joint_remains_whole_and_never_reads_sources(quadratic_dev_case, tmp_path, monkeypatch):
    plan = deepcopy(quadratic_dev_case[1])
    plan["walk_forward"]["minimum_train_days"] = 14
    plan["strategies"] = [plan["strategies"][0]]
    case = _saved_joint(plan, tmp_path)
    original = case.study.as_dict()["report"]
    assert original["status"] == "UNAVAILABLE"
    _prohibit_joint_recomputation(monkeypatch)
    reports = [analyze(case.study) for analyze in (diagnostics.analyze_intraday_ml_prediction_quality,
        sensitivity.analyze_intraday_inner_objective_sensitivity, procedure.analyze_intraday_procedure_return_uncertainty)]
    for report in reports:
        assert report["status"] == "UNAVAILABLE" and report["source_kind"] == "JOINT_ECONOMIC_SELECTION"
        assert report["unavailable_reason"] == "SOURCE_STUDY_UNAVAILABLE"
        assert report["unavailable_reasons"] == original["unavailable_reasons"] and report["sample"] is None
    assert reports[0]["predictions"] == reports[0]["folds"] == reports[1]["windows"] == reports[2]["statistics"] == []
    assert reports[2]["accounts"] == {}


def test_existing_cli_commands_relocation_source_absence_and_failure_recovery(joint_case, tmp_path):
    data, _, source_path, _, _, saved, _ = joint_case
    relocated = tmp_path / "relocated-q5.json"
    relocated.write_bytes(data.path.read_bytes())
    before = {path: path.read_bytes() for path in (data.path, source_path, saved)}
    console = str(Path(sys.executable).with_name("market-vault.exe" if os.name == "nt" else "market-vault"))
    prefix = [console, "--settings", str(tmp_path / "absent-settings.yaml")]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    commands = ("research-intraday-ml-prediction-quality", "research-intraday-inner-objective-sensitivity",
                "research-intraday-procedure-return-uncertainty")
    hidden = []
    try:
        for path in (data.path, source_path):
            moved = path.with_suffix(".temporarily-unavailable")
            path.rename(moved)
            hidden.append((moved, path))
        for command in commands:
            quality = command == commands[0]
            for valid in (False, True):
                arguments = ["--experiment", str(saved if quality or valid else tmp_path / "missing-study.json")]
                if quality:
                    arguments += ["--intraday-data", str(relocated if valid else tmp_path / "missing-q5.json")]
                process = subprocess.run(prefix + [command] + arguments, cwd=tmp_path, env=env,
                    capture_output=True, text=True, timeout=120)
                assert process.returncode == (0 if valid else 1), process.stderr
                payload = json.loads(process.stdout if valid else process.stderr)
                assert payload["status"] == ("SUCCESS" if valid else "FAILED")
                if valid:
                    report = payload["report"]
                    assert report["status"] == "AVAILABLE" and report["source_kind"] == "JOINT_ECONOMIC_SELECTION"
                    if quality:
                        assert report["source_locator"]["used"] == str(relocated)
                        assert report["source_locator"]["override_used"]
                    elif command == commands[1]:
                        assert all(len(row["fixed_evidence"]["models"]) == 6 and len(row["original"]["objectives"]) == 24
                                   for row in report["windows"])
                    else:
                        assert report["sample"]["sample_count"] == 10 and report["basis"]["matches"]
    finally:
        for moved, path in hidden:
            moved.rename(path)
    assert all(path.read_bytes() == content for path, content in before.items())
