"""Joint economic numerical oracle, causal fits and one shared real workflow."""

from copy import deepcopy
from fractions import Fraction
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from market_vault.backtest.intraday import IntradayExecutionPolicy
from market_vault.research import intraday_joint_selection as joint
from market_vault.research import intraday_research as research
from market_vault.research.intraday_data import digest
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.strategy_experiment import (
    StrategyExperiment, canonical_json, load_strategy_experiment, replay_strategy_experiment, write_strategy_experiment,
)
from test_strategy_intraday_ml import quadratic_dev_case  # noqa: F401
from test_strategy_intraday_threshold_selection import economic_grid, training_case


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("commission,slippage,expected_index", [(0, 0, 0), (10, 5, 13)])
def test_global_24_account_cash_oracle_cost_reversal_and_six_shared_fits(monkeypatch, commission, slippage, expected_index):
    sessions, prices, original = economic_grid()
    calls = []
    def fit(rows, observations, features, recipe, boundary):
        model_index = next(index for index, model in enumerate(joint.MODEL_FAMILY)
                           if (model["kind"], model["alpha"]) == (recipe["kind"], recipe["alpha"]))
        calls.append(model_index)
        predictions = deepcopy(original)
        for row in predictions:
            old = row["score"]
            score = ({.0005: .002, .002: .0005}.get(old, 0) if model_index in (0, 1)
                     else old if model_index == 3 else .0025 if model_index == 4 and old == .0005 else 0)
            row.update(score=score, target="LONG" if score > recipe["threshold"] else "FLAT")
        return {"oracle_model_index": model_index}, predictions
    monkeypatch.setattr(joint, "_fit", fit)
    strategy = {"kind": "RIDGE", "alpha": 2.0, "threshold": -1, "name": "Explicit reference"}
    window = ({"sessions": sessions, "prices": prices, "training_boundary": sessions[0]["open_time"]}, (), ())
    joint._select(window, ["x"], strategy, "5m", IntradayExecutionPolicy(commission, slippage))
    evidence = window[0]
    c, s = Fraction(commission, 10000), Fraction(slippage, 10000)
    factor = (1 - s) * (1 - c) / ((1 + s) * (1 + c))
    small, large = Fraction(1001, 1000) * factor, Fraction(101, 100) * factor
    both, cash = small * large, Fraction(1)
    expected = [both, small, small, cash] * 2 + [cash] * 4 + [both, large, large, cash] + [small] * 4 + [cash] * 4
    assert calls == list(range(6)) and len(evidence["models"]) == 6
    assert len(evidence["family_results"]) == 24
    assert [row["execution"]["metrics"]["final_cash"] for row in evidence["family_results"]] == pytest.approx(
        [float(value) for value in expected], abs=1e-14)
    assert evidence["selected_index"] == expected_index
    assert evidence["selected_recipe"] == evidence["family_results"][expected_index]["strategy"]
    for index, member in enumerate(evidence["family_results"]):
        assert (member["candidate_index"], member["model_index"], member["threshold_index"]) == (index, index // 4, index % 4)
        account = member["execution"]
        assert len(account["decisions"]) == 370 and len(account["ledger"]) == 780
        assert len(account["daily"]) == 5 and all(row["trade_count"] == 0 for row in account["daily"][1:])


def test_real_six_fits_purge_no_complete_holdout_and_future_isolation(monkeypatch):
    report, old_window, policy = training_case()
    from types import SimpleNamespace
    days = old_window[0]["history_days"]
    rows, purged = research.training_rows(report, tuple(days), old_window[0]["history_boundary"])
    window = joint._window(SimpleNamespace(report=report), days, rows, purged, old_window[0]["history_boundary"], policy)
    calls, executions, fit, execute = [], [], joint._fit, joint.run_intraday_execution
    def fitted(*args, **kwargs):
        calls.append(1)
        return fit(*args, **kwargs)
    def executed(*args, **kwargs):
        executions.append(1)
        return execute(*args, **kwargs)
    monkeypatch.setattr(joint, "_fit", fitted)
    monkeypatch.setattr(joint, "run_intraday_execution", executed)
    strategy = {"kind": "RIDGE", "name": "Fixed reference", "alpha": 2.0, "threshold": -.01}
    joint._select(window, ["x0", "x1"], strategy, "5m", policy)
    evidence = window[0]
    assert len(calls) == 6 and len(executions) == 24
    assert evidence["unavailable_reason"] is None and len(evidence["purged_keys"]) == 1
    assert not any(row["status"] == "COMPLETE" and row["observation_key"] in evidence["validation_keys"] for row in report["targets"])
    assert evidence["selected_index"] == 2  # First cash-only recipe; all six models predict .0007.
    for record in evidence["models"]:
        model = record["model"]
        assert len(model["training_keys"]) == 44
        ridge_model = model.get("ridge_model", model)
        assert ridge_model["intercept"] == pytest.approx(.0007)
        assert max(abs(value) for value in ridge_model["means"]) < 100
        if "input_transform" in model:
            assert max(abs(value) for value in model["input_transform"]["means"]) < 100
        assert len(record["predictions"]) == 15
    for change in ({"future_shift": 500}, {"boundary_target": 1e8}):
        altered, _, _ = training_case(**change)
        altered_rows, altered_purged = research.training_rows(altered, tuple(days), evidence["history_boundary"])
        other = joint._window(SimpleNamespace(report=altered), days, altered_rows, altered_purged, evidence["history_boundary"], policy)
        joint._select(other, ["x0", "x1"], strategy, "5m", policy)
        # A purged target remains recorded historical evidence, but cannot
        # affect any fitted transform, score, account or the selected recipe.
        for key in ("models", "family_results", "selected_index", "selected_recipe"):
            assert other[0][key] == evidence[key]
    _, gap, _ = training_case(gap=True)
    _, empty, _ = training_case(no_training=True)
    assert gap[0]["unavailable_reason"] == "INNER_EXECUTION_INPUT_UNAVAILABLE"
    assert empty[0]["unavailable_reason"] == "NO_INNER_TRAINING_ROWS"


@pytest.fixture(scope="session")
def joint_case(quadratic_dev_case, tmp_path_factory):
    root = tmp_path_factory.mktemp("intraday-joint")
    data, comparison, _, _, _, _ = quadratic_dev_case
    plan = {"plan_schema_version": research.INTRADAY_DIAGNOSTICS_PLAN_V2_VERSION,
        "comparison_plan": comparison, "strategy_name": "Quadratic",
        "parameter_axes": [{"parameter": "alpha", "values": [.5, 2]}],
        "cost_scenarios": [{"commission_bps": 0, "slippage_bps": 0}, {"commission_bps": 10, "slippage_bps": 5}]}
    source = create_intraday_experiment(plan=plan, report=research.run_intraday_research(plan))
    source_path = write_strategy_experiment(source, path=root / "source.json").path
    reference = source.as_dict()["report"]["groups"][1]["results"][1]
    args = {"expected_experiment_id": source.experiment_id, "cost_index": 1, "candidate_index": 1,
        "expected_candidate_id": reference["candidate_id"]}
    counts = {"load": 0, "fit": 0, "execute": 0}
    load, fit, execute = research.load_intraday_dataset, joint._fit, joint.run_intraday_execution
    def loaded(*a, **k):
        counts["load"] += 1
        return load(*a, **k)
    def fitted(*a, **k):
        counts["fit"] += 1
        return fit(*a, **k)
    def executed(*a, **k):
        counts["execute"] += 1
        return execute(*a, **k)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(research, "load_intraday_dataset", loaded)
        patch.setattr(joint, "_fit", fitted)
        patch.setattr(joint, "run_intraday_execution", executed)
        study = joint.run_intraday_joint_selection(source_path, **args)
    saved = write_strategy_experiment(study, path=root / "joint.json").path
    return data, source, source_path, args, study, saved, counts


def test_real_source_one_load_all_windows_selected_outer_refits_and_replay(joint_case, monkeypatch, tmp_path):
    data, source, source_path, args, study, saved, counts = joint_case
    root, original = study.as_dict(), source.as_dict()
    report, context = root["report"], original["report"]["context"]
    folds = len(context["folds"])
    assert counts == {"load": 1, "fit": 6 * (folds + 1) + folds, "execute": 24 * (folds + 1) + 1}
    assert report["status"] == "AVAILABLE" and report["source_experiment"] == original
    assert report["fixed_reference"] == {"cost_index": 1, "candidate_index": 1, "candidate_id": args["expected_candidate_id"]}
    assert report["benchmark"] == original["report"]["groups"][1]["benchmark"]
    assert report["selected_account"]["execution"]["policy"] == original["report"]["groups"][1]["execution_policy"]
    for record, fold in zip(report["outer_folds"], context["folds"], strict=True):
        inner, refit = record["inner"], record["refit"]
        assert len(inner["models"]) == 6 and len(inner["family_results"]) == 24
        assert refit["strategy"] == inner["selected_recipe"]
        assert refit["model"]["training_keys"] == fold["training_keys"] != inner["training_keys"]
        assert refit["model"]["training_boundary"] == fold["training_boundary"]
        assert [row["observation_key"] for row in refit["predictions"]] == fold["validation_keys"]
    account = report["selected_account"]
    assert [row["observation_key"] for row in account["predictions"]] == context["validation_keys"]
    assert account["prediction_metrics"]["complete_target_count"] < account["prediction_metrics"]["prediction_count"]
    assert [row["trading_day"] for row in account["execution"]["daily"]] == context["evaluated_days"]
    final = report["final_dev"]
    assert final["history_days"] == context["split"]["TRAIN"] + context["split"]["VALIDATION"]
    assert len(final["models"]) == 6 and len(final["family_results"]) == 24
    assert all(row["trading_day"] not in context["split"]["TEST"] for row in account["predictions"])
    assert "refit" not in final  # The selected final recipe is not a TEST-trained model.
    before = source_path.read_bytes(), saved.read_bytes()
    relocated = tmp_path / "relocated-q5.json"
    relocated.write_bytes(data.path.read_bytes())
    monkeypatch.setattr(joint, "load_strategy_experiment", lambda *a, **k: pytest.fail("replay must use embedded ordinary source"))
    assert replay_strategy_experiment(study, intraday_data_file=relocated)["report_matches"]
    assert (source_path.read_bytes(), saved.read_bytes()) == before


def _resigned(root):
    report = root["report"]
    report["joint_selection_id"] = digest({key: value for key, value in report.items() if key != "joint_selection_id"})
    root["experiment_id"] = digest({key: value for key, value in root.items() if key != "experiment_id"})
    return canonical_json(root)


def test_recorded_family_order_recipe_price_and_selected_evidence_reject_tampering(joint_case, monkeypatch):
    _, _, _, _, study, _, _ = joint_case
    def missing_member(root):
        root["report"]["outer_folds"][0]["inner"]["family_results"].pop()
    def wrong_model_index(root):
        root["report"]["outer_folds"][0]["inner"]["family_results"][4]["model_index"] = 0
    def changed_threshold(root):
        root["report"]["final_dev"]["family_results"][0]["strategy"]["threshold"] = .003
    def wrong_refit(root):
        root["report"]["outer_folds"][0]["refit"]["strategy"]["alpha"] = 99.0
    def changed_price(root):
        root["report"]["final_dev"]["prices"][0]["open"] += 1.0
    def wrong_mode(root):
        root["evaluation_mode"] = "INTRADAY_THRESHOLD_SELECTION"
    def wrong_version(root):
        root["artifact_schema_version"] = "market-vault-intraday-threshold-selection-v1"
    for corrupt in (missing_member, wrong_model_index, changed_threshold, wrong_refit, changed_price, wrong_mode, wrong_version):
        root = study.as_dict()
        corrupt(root)
        with pytest.raises(ValueError):
            StrategyExperiment(_resigned(root))
    root = study.as_dict()
    model = root["report"]["final_dev"]["models"][0]["model"]
    model["intercept"] += .01
    model["model_id"] = digest({key: value for key, value in model.items() if key != "model_id"})
    altered = StrategyExperiment(_resigned(root))
    with pytest.raises(ValueError, match="complete replay"):
        replay_strategy_experiment(altered)
    monkeypatch.setattr(research, "load_intraday_dataset", lambda *a, **k: pytest.fail("Open read Q5"))
    monkeypatch.setattr(joint, "_fit", lambda *a, **k: pytest.fail("Open refitted"))
    monkeypatch.setattr(joint, "run_intraday_execution", lambda *a, **k: pytest.fail("Open executed Q6"))
    assert StrategyExperiment(study.content).experiment_id == study.experiment_id


def test_whole_study_unavailable_and_dimension_preflight(quadratic_dev_case, tmp_path, monkeypatch):
    _, base, _, _, _, _ = quadratic_dev_case
    plan = deepcopy(base)
    plan["walk_forward"]["minimum_train_days"] = 14
    plan["strategies"] = [plan["strategies"][0]]
    source = create_intraday_experiment(plan=plan, report=research.run_intraday_research(plan))
    path = write_strategy_experiment(source, path=tmp_path / "short-linear.json").path
    candidate = source.as_dict()["report"]["groups"][0]["results"][0]
    monkeypatch.setattr(joint, "_fit", lambda *a, **k: pytest.fail("unavailable study partially fitted"))
    monkeypatch.setattr(joint, "run_intraday_execution", lambda *a, **k: pytest.fail("unavailable study executed Q6"))
    study = joint.run_intraday_joint_selection(path, expected_experiment_id=source.experiment_id,
        cost_index=0, candidate_index=0, expected_candidate_id=candidate["candidate_id"])
    report = study.as_dict()["report"]
    assert report["status"] == "UNAVAILABLE" and report["selected_account"] is None
    assert report["unavailable_reasons"][0]["reason"] == "INSUFFICIENT_INNER_HISTORY"
    assert all(row["refit"] is None and row["inner"]["models"] == [] and row["inner"]["family_results"] == []
               for row in report["outer_folds"])
    assert report["final_dev"]["models"] == []
    fake = source.as_dict()
    fake["report"]["context"]["feature_fields"] = [f"feature_{index}" for index in range(7)]
    selection = {"source_experiment": {"experiment_id": fake["experiment_id"]},
        "selection": {"cost_index": 0, "candidate_index": 0, "candidate_id": candidate["candidate_id"]}}
    with pytest.raises(ValueError, match="six|6"):
        joint._selected(fake, selection)


def test_settings_independent_cli_saved_open_replay_and_immutable_identity(joint_case, tmp_path):
    data, source, source_path, args, study, saved, _ = joint_case
    output = tmp_path / "cli-joint.json"
    cli = str(Path(sys.executable).with_name("market-vault.exe" if os.name == "nt" else "market-vault"))
    prefix = [cli, "--settings", str(tmp_path / "absent-settings.yaml")]
    command = prefix + ["research-intraday-joint-selection", "--source-experiment", str(source_path),
        "--expected-experiment-id", source.experiment_id, "--cost-index", "1", "--candidate-index", "1",
        "--expected-candidate-id", args["expected_candidate_id"], "--experiment", str(output)]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT / "tests")))}
    completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["study"]["report"]["status"] == "AVAILABLE"
    assert load_strategy_experiment(output).experiment_id == study.experiment_id
    before = output.read_bytes(), source_path.read_bytes(), saved.read_bytes()
    completed = subprocess.run(prefix + ["research-experiment-open", "--experiment", str(output)],
        cwd=ROOT, env=env, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    relocated = tmp_path / "relocated-q5.json"
    relocated.write_bytes(data.path.read_bytes())
    completed = subprocess.run(prefix + ["research-intraday-joint-selection-replay", "--experiment", str(output),
        "--intraday-data-file", str(relocated), "--source-experiment-file", str(source_path)],
        cwd=ROOT, env=env, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["replay"]["report_matches"]
    command[command.index("--expected-candidate-id") + 1] = "a" * 64
    completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
    assert completed.returncode == 1 and "captured identity" in completed.stderr
    with pytest.raises(ValueError, match="differs"):
        write_strategy_experiment(study, path=source_path)
    assert (output.read_bytes(), source_path.read_bytes(), saved.read_bytes()) == before
