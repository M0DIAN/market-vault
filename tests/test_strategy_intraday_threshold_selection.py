"""Economic oracle, causal threshold selection and one compact real source."""

from copy import deepcopy
from datetime import datetime, timedelta
from fractions import Fraction
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from market_vault.backtest.intraday import IntradayExecutionPolicy
from market_vault.research import intraday_research as research
from market_vault.research import intraday_threshold_selection as threshold
from market_vault.research.intraday_data import digest
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.strategy_experiment import (
    StrategyExperiment, canonical_json, load_strategy_experiment, replay_strategy_experiment, write_strategy_experiment,
)
from test_strategy_intraday_ml import quadratic_dev_case  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]


def economic_grid():
    """Two known opportunities and four subsequent full cash days, no fits."""
    sessions, prices, predictions = [], [], []
    for index in range(5):
        opened = datetime.fromisoformat("2025-03-03T14:30:00+00:00") + timedelta(days=index)
        day = opened.date().isoformat()
        sessions.append({"trading_day": day, "open_time": opened.isoformat(),
                         "close_time": (opened + timedelta(minutes=390)).isoformat(), "bar_count": 78})
        for slot in range(78):
            price = 100.10 if index == 0 and slot == 6 else 101.0 if index == 0 and slot == 8 else 100.0
            prices.append({"trading_day": day, "slot": slot, "event_time": (opened + timedelta(minutes=5 * slot)).isoformat(),
                "available_at": (opened + timedelta(minutes=5 * (slot + 1))).isoformat(), "open": price, "close": price,
                "row_version_id": digest(["price", index, slot])})
            if slot >= 4:
                score = .0005 if index == 0 and slot == 4 else .002 if index == 0 and slot == 6 else 0.0
                predictions.append({"observation_key": digest(["observation", index, slot]), "trading_day": day,
                    "slot": slot, "decision_time": (opened + timedelta(minutes=5 * (slot + 1))).isoformat(),
                    "score": score, "target": "LONG" if score > 0 else "FLAT"})
    return sessions, prices, predictions


@pytest.mark.parametrize("commission,slippage,expected_index", [(0, 0, 0), (10, 5, 1)])
def test_two_opportunity_cash_oracle_cost_reversal_and_strict_ties(commission, slippage, expected_index):
    sessions, prices, predictions = economic_grid()
    family, chosen = threshold._threshold_accounts(predictions, sessions, prices, "5m", IntradayExecutionPolicy(commission, slippage))
    c, s = Fraction(commission, 10000), Fraction(slippage, 10000)
    factor = (1 - s) * (1 - c) / ((1 + s) * (1 + c))
    expected = [Fraction(1001, 1000) * Fraction(101, 100) * factor ** 2, Fraction(101, 100) * factor,
                Fraction(101, 100) * factor, Fraction(1)]
    assert [row["execution"]["metrics"]["final_cash"] for row in family] == pytest.approx([float(x) for x in expected], abs=1e-14)
    assert chosen == expected_index
    assert family[1]["execution"]["metrics"]["final_cash"] == family[2]["execution"]["metrics"]["final_cash"]
    assert [row["execution"]["metrics"]["trade_count"] for row in family] == [2, 1, 1, 0]
    assert len(prices) == 390 and len(predictions) == 370
    assert [(row["entry_slot"], row["exit_slot"], row["exit_reason"], row["held_bars"])
            for row in family[0]["execution"]["trades"]] == [(5, 6, "TARGET_FLAT", 1), (7, 8, "TARGET_FLAT", 1)]
    for member in family:
        account = member["execution"]
        assert len(account["decisions"]) == 370 and len(account["ledger"]) == 780
        assert len(account["daily"]) == 5 and account["daily"][0]["cash_open"] == 1
        assert all(row["trade_count"] == 0 for row in account["daily"][1:])


def training_case(*, future_shift=0.0, no_training=False, gap=False, boundary_target=1000.0):
    """A tiny real Ridge fit; all holdout targets deliberately unavailable."""
    sessions, prices, observations, targets = [], [], [], []
    for index in range(23):
        opened = datetime.fromisoformat("2025-04-01T14:30:00+00:00") + timedelta(days=index)
        day = opened.date().isoformat()
        sessions.append({"trading_day": day, "open_time": opened.isoformat(),
                         "close_time": (opened + timedelta(minutes=30)).isoformat(), "bar_count": 6})
        for slot in range(6):
            price = 100.0 + (.02 if slot == 2 else 0.0) + (future_shift if index >= 20 else 0)
            if not (gap and index == 15 and slot == 1):
                prices.append({"trading_day": day, "slot": slot, "event_time": (opened + timedelta(minutes=5 * slot)).isoformat(),
                    "available_at": (opened + timedelta(minutes=5 * (slot + 1))).isoformat(), "open": price, "close": price,
                    "row_version_id": digest([index, slot])})
            if slot in (0, 1, 5):
                key = digest(["observation", index, slot])
                observations.append({"observation_key": key, "trading_day": day, "slot": slot,
                    "decision_time": (opened + timedelta(minutes=5 * (slot + 1))).isoformat(), "status": "READY",
                    "features": {f"x{n}": (slot - 1) * (n + 1) + (future_shift if index >= 20 else 0) for n in range(7)}})
                complete = index < 15 and not no_training
                targets.append({"observation_key": key, "status": "COMPLETE" if complete else "INCOMPLETE",
                    "actual_label_end_time": (opened + timedelta(minutes=5 * (slot + 2))).isoformat() if complete else None,
                    "value": .0007 if complete else None})
    # A large would-be training row at exact inner-boundary equality is purged.
    targets[44].update(status="COMPLETE", actual_label_end_time=sessions[15]["open_time"], value=boundary_target)
    observations[44]["features"] = {f"x{n}": 1e6 for n in range(7)}
    report = {"interval": "5m", "sessions": sessions, "prices": prices, "observations": observations, "targets": targets}
    days = [row["trading_day"] for row in sessions]
    rows, purged = research.training_rows(report, tuple(days[:20]), sessions[20]["open_time"])
    policy = IntradayExecutionPolicy(10, 5, entry_delay_minutes=0, stop_new_minutes=5, flatten_minutes=5)
    window = threshold._window(SimpleNamespace(report=report), days[:20], rows, purged, sessions[20]["open_time"], policy)
    return report, window, policy


def test_single_fixed_fit_wide_linear_purge_no_complete_holdout_and_future_isolation(monkeypatch):
    report, window, policy = training_case()
    calls, fit = [], threshold._fit
    def fitted(*args, **kwargs):
        calls.append(1)
        return fit(*args, **kwargs)
    monkeypatch.setattr(threshold, "_fit", fitted)
    strategy = {"kind": "RIDGE", "name": "Fixed wide linear", "alpha": 1.0, "threshold": -.01}
    features = [f"x{index}" for index in range(7)]
    threshold._select(window, features, strategy, "5m", policy)
    assert len(calls) == 1 and len(window[0]["family_results"]) == 4
    assert window[0]["unavailable_reason"] is None
    assert len(window[0]["purged_keys"]) == 1 and len(window[0]["model"]["training_keys"]) == 44
    assert window[0]["model"]["intercept"] == pytest.approx(.0007)
    assert max(abs(value) for value in window[0]["model"]["means"]) < 100
    assert not any(row["status"] == "COMPLETE" and row["observation_key"] in window[0]["validation_keys"] for row in report["targets"])
    assert len(window[0]["predictions"]) == 15 and all(len(row["execution"]["decisions"]) == 15 for row in window[0]["family_results"])
    _, altered, _ = training_case(future_shift=500)
    threshold._select(altered, features, strategy, "5m", policy)
    assert altered[0] == window[0]
    # Fixed recipe admission does not apply Q25's six-feature family bound.
    fake = {"artifact_schema_version": "market-vault-intraday-experiment-v1", "evaluation_mode": "INTRADAY_COMPARISON",
        "experiment_id": "source", "report": {"context": {"feature_fields": features},
        "groups": [{"results": [{"candidate_id": "candidate", "strategy": strategy}]}]}}
    threshold._selected(fake, {"source_experiment": {"experiment_id": "source"},
                               "selection": {"cost_index": 0, "candidate_index": 0, "candidate_id": "candidate"}})


def test_inner_outer_economic_reversal_keeps_the_historical_choice():
    report, window, policy = training_case(boundary_target=.0007)
    strategy = {"kind": "RIDGE", "name": "Fixed wide linear", "alpha": 1.0, "threshold": -.01}
    features = [f"x{index}" for index in range(7)]
    outer_days = [row["trading_day"] for row in report["sessions"][20:]]
    for price in report["prices"]:
        if price["trading_day"] in outer_days and price["slot"] == 5:
            price.update(open=110.0, close=110.0)
    threshold._select(window, features, strategy, "5m", policy)
    # Every fitted score is .0007. Inner trades lose their round-trip cost;
    # exact ties choose .001 over .002. Outer prices are already in the report.
    factor = Fraction(665667, 667667)
    expected_inner = [factor ** 5, factor ** 5, Fraction(1), Fraction(1)]
    assert [row["execution"]["metrics"]["final_cash"] for row in window[0]["family_results"]] == pytest.approx(
        [float(value) for value in expected_inner], abs=1e-14)
    assert window[0]["selected_index"] == 2
    history, _ = research.training_rows(report, tuple(window[0]["history_days"]), window[0]["history_boundary"])
    observations = tuple(row for row in report["observations"] if row["trading_day"] in outer_days)
    _, predictions = threshold._fit(history, observations, features, strategy, window[0]["history_boundary"])
    from market_vault.research.intraday_backtest import execution_views
    sessions, prices = execution_views(report, trading_days=tuple(outer_days))
    family, hindsight = threshold._threshold_accounts(predictions, sessions, prices, "5m", policy)
    expected_outer = (Fraction(11, 10) * factor) ** 3
    assert [row["execution"]["metrics"]["final_cash"] for row in family] == pytest.approx(
        [float(expected_outer), float(expected_outer), 1, 1], abs=1e-14)
    assert hindsight == 0 and window[0]["selected_index"] == 2
    assert family[window[0]["selected_index"]]["execution"]["metrics"]["final_cash"] == 1


def test_only_expected_inner_input_unavailability_is_classified():
    _, empty, _ = training_case(no_training=True)
    assert empty[0]["unavailable_reason"] == "NO_INNER_TRAINING_ROWS"
    _, gap, policy = training_case(gap=True)
    assert gap[0]["unavailable_reason"] == "INNER_EXECUTION_INPUT_UNAVAILABLE"
    assert "incomplete session price flow" in gap[0]["execution_input"]["detail"]
    sessions, prices, _ = economic_grid()
    prices[0]["open"] = -1
    with pytest.raises(ValueError, match="positive"):
        threshold._execution_input_status(sessions, prices, "5m", policy)


@pytest.fixture(scope="session")
def threshold_case(quadratic_dev_case, tmp_path_factory):
    root = tmp_path_factory.mktemp("intraday-threshold")
    data, _, _, source, source_path, _ = quadratic_dev_case
    candidate = source.as_dict()["report"]["groups"][0]["results"][1]
    args = {"expected_experiment_id": source.experiment_id, "cost_index": 0, "candidate_index": 1,
            "expected_candidate_id": candidate["candidate_id"]}
    study = threshold.run_intraday_threshold_selection(source_path, **args)
    saved = write_strategy_experiment(study, path=root / "threshold.json").path
    return data, source, source_path, args, study, saved


def test_real_source_fixed_outer_models_one_q5_complete_study_and_replay(threshold_case, monkeypatch):
    data, source, path, args, study, saved = threshold_case
    root, original = study.as_dict(), source.as_dict()
    report, reference = root["report"], original["report"]["groups"][0]["results"][1]
    context = original["report"]["context"]
    assert report["status"] == "AVAILABLE"
    assert reference["strategy"]["threshold"] == -1 and threshold.THRESHOLDS == (0.0, .0005, .001, .002)
    assert len(report["outer_folds"]) == len(context["folds"])
    for recorded, old in zip(report["outer_folds"], reference["fold_models"], strict=True):
        assert recorded["application"]["model"] == old["model"]
        assert len(recorded["inner"]["family_results"]) == 4
    assert report["benchmark"] == original["report"]["groups"][0]["benchmark"]
    account = report["selected_account"]
    assert account["prediction_metrics"] == reference["prediction_metrics"]
    assert [row["score"] for row in account["predictions"]] == [row["score"] for row in reference["predictions"]]
    assert [row["observation_key"] for row in account["predictions"]] == context["validation_keys"]
    assert account["prediction_metrics"]["prediction_count"] > account["prediction_metrics"]["complete_target_count"]
    assert [row["trading_day"] for row in account["execution"]["daily"]] == context["evaluated_days"]
    assert report["final_dev"]["history_days"] == context["split"]["TRAIN"] + context["split"]["VALIDATION"]
    before, saved_before = path.read_bytes(), saved.read_bytes()
    calls, fits, load, fit = [], [], research.load_intraday_dataset, threshold._fit
    def loaded(*args, **kwargs):
        calls.append(1)
        return load(*args, **kwargs)
    def fitted(*args, **kwargs):
        fits.append(1)
        return fit(*args, **kwargs)
    monkeypatch.setattr(research, "load_intraday_dataset", loaded)
    monkeypatch.setattr(threshold, "_fit", fitted)
    monkeypatch.setattr(threshold, "load_strategy_experiment", lambda *a, **k: pytest.fail("Replay uses embedded ordinary"))
    assert replay_strategy_experiment(study)["report_matches"]
    assert len(calls) == 1 and len(fits) == len(context["folds"]) + 1
    assert path.read_bytes() == before and saved.read_bytes() == saved_before


def test_real_available_linear_source_reuses_its_original_outer_recipe(threshold_case):
    _, source, path, _, _, _ = threshold_case
    reference = source.as_dict()["report"]["groups"][0]["results"][0]
    study = threshold.run_intraday_threshold_selection(path, expected_experiment_id=source.experiment_id,
        cost_index=0, candidate_index=0, expected_candidate_id=reference["candidate_id"])
    report = study.as_dict()["report"]
    assert report["status"] == "AVAILABLE" and report["final_dev"]["selected_recipe"]["kind"] == "RIDGE"
    assert [row["application"]["model"] for row in report["outer_folds"]] == [row["model"] for row in reference["fold_models"]]
    assert [row["score"] for row in report["selected_account"]["predictions"]] == [row["score"] for row in reference["predictions"]]


def resigned(root):
    report = root["report"]
    report["threshold_selection_id"] = digest({key: value for key, value in report.items() if key != "threshold_selection_id"})
    root["experiment_id"] = digest({key: value for key, value in root.items() if key != "experiment_id"})
    return canonical_json(root)


def test_open_bindings_and_replay_source_proof_are_distinct(threshold_case, monkeypatch):
    _, _, _, _, study, _ = threshold_case
    for case in ("drop_member", "threshold_order", "chosen", "future_target", "outer_model", "daily_return"):
        root = study.as_dict()
        window = root["report"]["outer_folds"][0]["inner"]
        if case == "drop_member":
            window["family_results"].pop()
        elif case == "threshold_order":
            window["family_results"][0]["threshold"] = .002
        elif case == "chosen":
            window["selected_index"] = (window["selected_index"] + 1) % 4
        elif case == "future_target":
            window["history_targets"][0]["actual_label_end_time"] = window["history_boundary"]
        elif case == "outer_model":
            model = root["report"]["outer_folds"][0]["application"]["model"]
            model["alpha"] += 1
        else:
            window["family_results"][0]["execution"]["daily"][0]["return"] += .1
        with pytest.raises(ValueError):
            StrategyExperiment(resigned(root))
    root = study.as_dict()
    model = root["report"]["final_dev"]["model"]
    model["input_transform"]["means"][0] += 1e-8
    model["model_id"] = digest({key: value for key, value in model.items() if key != "model_id"})
    altered = StrategyExperiment(resigned(root))
    with pytest.raises(ValueError, match="complete replay"):
        replay_strategy_experiment(altered)
    monkeypatch.setattr(research, "load_intraday_dataset", lambda *a, **k: pytest.fail("Open read Q5"))
    monkeypatch.setattr(threshold, "_fit", lambda *a, **k: pytest.fail("Open fitted"))
    assert StrategyExperiment(study.content).experiment_id == study.experiment_id


def test_whole_study_unavailable_and_linear_source(quadratic_dev_case, tmp_path, monkeypatch):
    _, base, _, _, _, _ = quadratic_dev_case
    plan = deepcopy(base)
    plan["walk_forward"]["minimum_train_days"] = 10
    plan["strategies"] = [plan["strategies"][0]]
    source = create_intraday_experiment(plan=plan, report=research.run_intraday_research(plan))
    path = write_strategy_experiment(source, path=tmp_path / "short-linear.json").path
    candidate = source.as_dict()["report"]["groups"][0]["results"][0]
    monkeypatch.setattr(threshold, "_fit", lambda *a, **k: pytest.fail("unavailable study partially fitted"))
    study = threshold.run_intraday_threshold_selection(path, expected_experiment_id=source.experiment_id, cost_index=0,
        candidate_index=0, expected_candidate_id=candidate["candidate_id"])
    report = study.as_dict()["report"]
    assert report["status"] == "UNAVAILABLE" and report["selected_account"] is None
    assert len(report["outer_folds"]) == len(source.as_dict()["report"]["context"]["folds"])
    assert report["unavailable_reasons"][0]["reason"] == "INSUFFICIENT_INNER_HISTORY"
    assert all(row["inner"]["model"] is None and row["application"] is None for row in report["outer_folds"])
    assert report["final_dev"]["model"] is None
    assert replay_strategy_experiment(study)["report_matches"]


def test_real_threshold_cli_save_open_replay_relocation_and_identity(threshold_case, tmp_path):
    data, source, path, args, _, _ = threshold_case
    output = tmp_path / "cli-threshold.json"
    cli = str(Path(sys.executable).with_name("market-vault.exe" if os.name == "nt" else "market-vault"))
    command = [cli, "research-intraday-threshold-selection", "--source-experiment", str(path),
        "--expected-experiment-id", source.experiment_id, "--cost-index", "0", "--candidate-index", "1",
        "--expected-candidate-id", args["expected_candidate_id"], "--experiment", str(output)]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT / "tests")))}
    completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["study"]["report"]["status"] == "AVAILABLE"
    before = output.read_bytes()
    for action in ("research-experiment-open", "research-experiment-replay"):
        completed = subprocess.run([cli, action, "--experiment", str(output)],
                                   cwd=ROOT, env=env, capture_output=True, text=True)
        assert completed.returncode == 0, completed.stderr
    relocated = tmp_path / "relocated-q5.json"
    relocated.write_bytes(data.path.read_bytes())
    assert replay_strategy_experiment(load_strategy_experiment(output), intraday_data_file=relocated)["report_matches"]
    completed = subprocess.run(command + ["--name", "Changed"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert completed.returncode == 1 and output.read_bytes() == before
    command[command.index("--expected-candidate-id") + 1] = "a" * 64
    completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
    assert completed.returncode == 1 and "captured identity" in completed.stderr
