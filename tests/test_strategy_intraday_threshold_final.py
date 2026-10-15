"""Q32 saved economic Freeze, one final fit, strict history and real CLI."""

from copy import deepcopy
from dataclasses import asdict
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
from market_vault.research import intraday_final_test as final
from market_vault.research import intraday_research as research
from market_vault.research import intraday_threshold_selection as threshold
from market_vault.research.intraday_data import digest
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.strategy_experiment import (
    StrategyExperiment, canonical_json, load_strategy_experiment, replay_strategy_experiment, write_strategy_experiment,
)
from test_strategy_intraday_threshold_selection import threshold_case, quadratic_dev_case  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]


def bind(value, key):
    value[key] = digest({name: item for name, item in value.items() if name != key})


def signed_selection(root):
    root["report"]["plan_sha256"] = digest(root["plan"])
    bind(root["report"], "selection_id")
    bind(root, "experiment_id")
    return canonical_json(root)


@pytest.fixture(scope="session")
def threshold_final_case(threshold_case, tmp_path_factory):
    _, _, _, _, study, study_path = threshold_case
    path = tmp_path_factory.mktemp("threshold-final")
    blocked = lambda *a, **kw: pytest.fail("Freeze/Open read Q5, fitted, reselected or executed")
    with pytest.MonkeyPatch.context() as patch:
        for module, name in ((final, "load_intraday_dataset"), (research, "load_intraday_dataset"),
                             (research, "_fit"), (threshold, "_select"), (threshold, "_threshold_accounts"),
                             (threshold, "run_intraday_execution"), (final, "run_intraday_execution")):
            patch.setattr(module, name, blocked)
        selection = final.freeze_intraday_threshold_selection(study_path, expected_experiment_id=study.experiment_id)
        written = write_strategy_experiment(selection, path=path / "selection.json")
        assert load_strategy_experiment(written.path).content == selection.content
    calls = {"loads": 0, "fits": []}
    loader, fitter = final.load_intraday_dataset, research._fit
    def load(value):
        calls["loads"] += 1
        return loader(value)
    def fit(X, y, alpha):
        calls["fits"].append((len(X), len(X[0]), alpha))
        return fitter(X, y, alpha)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(final, "load_intraday_dataset", load)
        patch.setattr(research, "_fit", fit)
        patch.setattr(research, "load_intraday_dataset", blocked)
        patch.setattr(research, "_evaluate_intraday_research", blocked)
        patch.setattr(threshold, "_evaluate", blocked)
        patch.setattr(threshold, "_select", blocked)
        patch.setattr(threshold, "_threshold_accounts", blocked)
        report = final.run_intraday_final_test(selection)
    tested = final.create_intraday_test_experiment(selection, report)
    write_strategy_experiment(tested, path=path / "test.json")
    return selection, tested, calls, path


def test_freeze_exact_saved_economic_evidence_and_unavailable_guards(threshold_case, threshold_final_case,
                                                                  quadratic_dev_case, tmp_path, monkeypatch):
    _, source, source_path, _, study, study_path = threshold_case
    selection, tested, _, _ = threshold_final_case
    root, original = selection.as_dict(), study.as_dict()
    report, evidence = root["report"], root["report"]["dev_selection"]
    fixed = source.as_dict()["report"]["groups"][0]["results"][1]
    assert root["artifact_schema_version"] == final.INTRADAY_SELECTION_V3_VERSION
    assert root["plan"]["source_experiment"] == {"path": str(study_path), "experiment_id": study.experiment_id,
        "artifact_schema_version": threshold.INTRADAY_THRESHOLD_SELECTION_VERSION,
        "report_id": original["report"]["threshold_selection_id"]}
    assert report["evaluation_scope"] == "DEVELOPMENT_INNER_ECONOMIC_THRESHOLD_FINAL_RECIPE"
    assert evidence["final_dev"] == original["report"]["final_dev"]
    assert evidence["method"] == threshold.METHOD and len(evidence["final_dev"]["family_results"]) == 4
    assert evidence["source_selection"] == original["plan"]["selection"]
    assert evidence["source_experiment"] == {"path": str(source_path), "experiment_id": source.experiment_id,
                                             "research_id": source.as_dict()["report"]["research_id"]}
    assert evidence["fixed_reference"] == {key: fixed[key] for key in ("strategy", "axis_values")}
    assert report["candidate"] == {"strategy": evidence["final_dev"]["selected_recipe"], "axis_values": [],
                                    "execution_policy": source.as_dict()["report"]["groups"][0]["execution_policy"]}
    assert report["return_basis"] == tested.as_dict()["report"]["return_basis"] == threshold.RETURN_BASIS
    assert root["algorithm_versions"] == {**original["algorithm_versions"], "selection": final.INTRADAY_SELECTION_V3_VERSION}
    # Build one genuinely unavailable saved source on the same verified Q5.
    data, plan, *_ = quadratic_dev_case
    plan = deepcopy(plan)
    plan["walk_forward"]["minimum_train_days"] = 10
    plan["strategies"] = [plan["strategies"][0]]
    prepared = research._prepare_intraday_research(plan, data=data)
    ordinary = create_intraday_experiment(plan=plan, report=research._evaluate_intraday_research(plan, (plan,), ((),), prepared))
    ordinary_path = write_strategy_experiment(ordinary, path=tmp_path / "short-source.json").path
    unavailable = threshold.run_intraday_threshold_selection(ordinary_path, expected_experiment_id=ordinary.experiment_id,
        cost_index=0, candidate_index=0, expected_candidate_id=ordinary.as_dict()["report"]["groups"][0]["results"][0]["candidate_id"])
    unavailable_path = write_strategy_experiment(unavailable, path=tmp_path / "unavailable.json").path
    assert unavailable.as_dict()["report"]["status"] == "UNAVAILABLE"
    blocked = lambda *a, **kw: pytest.fail("guard or immutable Open read Q5 or fitted")
    monkeypatch.setattr(final, "load_intraday_dataset", blocked)
    monkeypatch.setattr(research, "load_intraday_dataset", blocked)
    monkeypatch.setattr(research, "_fit", blocked)
    for snapshot in (selection, tested):
        assert StrategyExperiment(snapshot.content).content == snapshot.content
    with pytest.raises(ValueError, match="only an AVAILABLE"):
        final.freeze_intraday_threshold_selection(unavailable_path, expected_experiment_id=unavailable.experiment_id)
    with pytest.raises(ValueError, match="identity differs"):
        final.freeze_intraday_threshold_selection(study_path, expected_experiment_id="a" * 64)
    with pytest.raises(ValueError, match="saved threshold-selection"):
        final.freeze_intraday_threshold_selection(source_path, expected_experiment_id=source.experiment_id)
    historical = study.as_dict()
    historical["algorithm_versions"]["threshold_selection"] = historical["report"]["version"] = "historical-threshold"
    bind(historical["report"], "threshold_selection_id"); bind(historical, "experiment_id")
    old = StrategyExperiment(canonical_json(historical))
    old_path = write_strategy_experiment(old, path=tmp_path / "historical.json").path
    with pytest.raises(ValueError, match="source algorithms differ"):
        final.freeze_intraday_threshold_selection(old_path, expected_experiment_id=old.experiment_id)


def test_one_final_fit_all_ready_actual_cost_accounts_and_full_replay_once(threshold_case, threshold_final_case, monkeypatch):
    data, _, _, _, study, _ = threshold_case
    selection, tested, calls, _ = threshold_final_case
    report, window = tested.as_dict()["report"], study.as_dict()["report"]["final_dev"]
    context, model = report["context"], report["model"]
    assert calls == {"loads": 1, "fits": [(180, 5, 1.0)]}
    assert tested.as_dict()["artifact_schema_version"] == final.INTRADAY_TEST_EXPERIMENT_V3_VERSION
    assert tested.as_dict()["plan"]["selection"] == selection.as_dict()
    assert report["strategy"] == window["selected_recipe"]
    assert context["training_keys"] == window["history_training_keys"] == model["training_keys"]
    assert context["purged_keys"] == window["history_purged_keys"]
    assert context["training_boundary"] == window["history_boundary"] == model["training_boundary"]
    assert set(window["training_keys"]) < set(model["training_keys"])
    assert model["model_id"] != window["model"]["model_id"]
    assert len(report["predictions"]) == report["prediction_metrics"]["prediction_count"] == 54
    assert report["prediction_metrics"]["complete_target_count"] == 36
    targets = {row["observation_key"]: row for row in data.as_dict()["report"]["targets"]}
    assert any(targets[row["observation_key"]]["status"] != "COMPLETE" for row in report["predictions"])
    assert all(row["target"] == ("LONG" if row["score"] > report["strategy"]["threshold"] else "FLAT") for row in report["predictions"])
    raw = {(row["trading_day"], row["slot"]): row["open"] for row in data.as_dict()["report"]["prices"]}
    factor = (1 - Fraction(5, 10000)) * (1 - Fraction(10, 10000)) / ((1 + Fraction(5, 10000)) * (1 + Fraction(10, 10000)))
    for account in (report["execution"], report["benchmark"]["execution"]):
        assert account["daily"][0]["cash_open"] == 1
        assert all(day["cash_open"] == previous["cash_close"] for previous, day in zip(account["daily"], account["daily"][1:]))
        cash = 1.0
        for trade in account["trades"]:
            entry, exit_ = raw[(trade["trading_day"], trade["entry_slot"])], raw[(trade["trading_day"], trade["exit_slot"])]
            assert (trade["entry_raw_open"], trade["exit_raw_open"]) == (entry, exit_)
            cash *= exit_ / entry * float(factor)
        assert account["metrics"]["final_cash"] == pytest.approx(cash, abs=1e-13)
        assert account["metrics"]["commission_total"] > 0 and account["metrics"]["slippage_total"] > 0
        assert [row["trading_day"] for row in account["daily"]] == context["split"]["TEST"]
    assert report["execution"]["price_evidence_id"] == report["benchmark"]["execution"]["price_evidence_id"]
    loader, loaded = final.load_intraday_dataset, []
    def load(path):
        loaded.append(path)
        return loader(path)
    monkeypatch.setattr(final, "load_intraday_dataset", load)
    monkeypatch.setattr(research, "load_intraday_dataset", lambda *a, **kw: pytest.fail("Replay admitted Q5 twice"))
    monkeypatch.setattr(threshold, "load_strategy_experiment", lambda *a, **kw: pytest.fail("Replay requested embedded ordinary file"))
    proof = replay_strategy_experiment(tested)
    assert len(loaded) == 1 and proof["source_report_matches"] and proof["selection_report_matches"] and proof["final_report_matches"]
    assert proof["expected_report_sha256"] == proof["actual_report_sha256"]


def test_bound_history_triple_precedes_fit_and_test_interventions_leave_training_fixed(threshold_case, threshold_final_case, monkeypatch):
    data = threshold_case[0]
    selection, tested, _, _ = threshold_final_case
    frozen, baseline = selection.as_dict(), tested.as_dict()["report"]
    # These deliberate private-evaluator counterfactuals are not saved Q5
    # artifacts, and are never passed through a public verified-data bypass.
    def evaluate(selected, raw):
        return final._evaluate_final_test(selected, SimpleNamespace(data_id=data.data_id, as_dict=lambda: raw))
    with monkeypatch.context() as patch:
        patch.setattr(research, "_fit", lambda *a, **kw: pytest.fail("history mismatch reached fitter"))
        for key in ("history_boundary", "history_training_keys", "history_purged_keys"):
            changed = selection.as_dict()
            window = changed["report"]["dev_selection"]["final_dev"]
            if key == "history_boundary":
                window[key] = window["training_boundary"]
            elif key == "history_training_keys":
                window[key] = window[key][1:]
            else:
                window[key] = ["a" * 64]
            with pytest.raises(ValueError, match="frozen final DEV history"):
                evaluate(changed, data.as_dict())
        raw = data.as_dict()
        first = baseline["context"]["training_keys"][0]
        next(row for row in raw["report"]["targets"] if row["observation_key"] == first)["actual_label_end_time"] = baseline["context"]["training_boundary"]
        with pytest.raises(ValueError, match="frozen final DEV history"):
            evaluate(frozen, raw)
    test_keys = set(baseline["context"]["test_keys"])
    for kind in ("targets", "features", "prices"):
        raw = data.as_dict()
        if kind == "targets":
            for row in raw["report"]["targets"]:
                if row["observation_key"] in test_keys and row["status"] == "COMPLETE":
                    row["value"] += 1
        elif kind == "features":
            for row in raw["report"]["observations"]:
                if row["observation_key"] in test_keys:
                    row["features"]["sma_5"] += 2
        else:
            for row in raw["report"]["prices"]:
                if row["trading_day"] in baseline["context"]["split"]["TEST"]:
                    row["open"] *= 1.2; row["close"] *= 1.2
        actual = evaluate(frozen, raw)
        assert actual["model"] == baseline["model"] and actual["context"] == baseline["context"]
        assert actual["strategy"] == baseline["strategy"] and actual["execution_policy"] == baseline["execution_policy"]
        if kind == "targets":
            assert actual["predictions"] == baseline["predictions"] and actual["prediction_metrics"] != baseline["prediction_metrics"]
        elif kind == "features":
            assert actual["predictions"] != baseline["predictions"]
        else:
            assert actual["predictions"] == baseline["predictions"] and actual["execution"] != baseline["execution"]


def test_constant_feature_oracle_uses_all_dev_and_purges_exact_boundary():
    """Small private numerical oracle; not a fabricated verified Q5 artifact."""
    sessions, prices, observations, targets = [], [], [], []
    features = [f"x{index}" for index in range(7)]
    for index in range(33):
        opened = datetime.fromisoformat("2025-04-01T14:30:00+00:00") + timedelta(days=index)
        day = opened.date().isoformat()
        sessions.append({"trading_day": day, "open_time": opened.isoformat(),
                         "close_time": (opened + timedelta(minutes=30)).isoformat(), "bar_count": 6})
        for slot in range(6):
            price = 110.0 if index >= 30 and slot == 5 else 100.0
            prices.append({"trading_day": day, "slot": slot, "event_time": (opened + timedelta(minutes=5 * slot)).isoformat(),
                "available_at": (opened + timedelta(minutes=5 * (slot + 1))).isoformat(), "open": price, "close": price,
                "row_version_id": digest([index, slot])})
            if slot == 0 or index >= 30 and slot == 5 or index == 29 and slot == 1:
                key = digest(["row", index, slot])
                observations.append({"observation_key": key, "trading_day": day, "slot": slot, "status": "READY",
                    "decision_time": (opened + timedelta(minutes=5 * (slot + 1))).isoformat(), "features": dict.fromkeys(features, 0.0)})
                complete = slot != 5
                targets.append({"observation_key": key, "status": "COMPLETE" if complete else "INCOMPLETE",
                    "actual_label_end_time": (opened + timedelta(minutes=5 * (slot + 2))).isoformat() if complete else None,
                    "value": .0007 if index < 25 else .0073 if complete else None})
    boundary = sessions[30]["open_time"]
    purged_key = observations[30]["observation_key"]
    observations[30]["features"] = dict.fromkeys(features, 1e9)
    targets[30].update(actual_label_end_time=boundary, value=1e9)
    days = [row["trading_day"] for row in sessions]
    raw = {"symbol": "US.SPY", "interval": "5m", "feature_names": features,
           "sessions": sessions, "prices": prices, "observations": observations, "targets": targets}
    policy = IntradayExecutionPolicy(10, 5, entry_delay_minutes=0, stop_new_minutes=5, flatten_minutes=5)
    rows, purged = research.training_rows(raw, tuple(days[:30]), boundary)
    window = threshold._window(SimpleNamespace(report=raw), days[:30], rows, purged, boundary, policy)
    recipe = {"kind": "RIDGE", "name": "Constant wide", "alpha": 1.0, "threshold": -1.0}
    threshold._select(window, features, recipe, "5m", policy)
    assert window[0]["model"]["intercept"] == pytest.approx(.0007)
    assert window[0]["selected_index"] == 2 and window[0]["selected_recipe"]["threshold"] == .001
    frozen = {"artifact_schema_version": final.INTRADAY_SELECTION_V3_VERSION, "experiment_id": "selection", "dataset_id": "data",
        "report": {"selection_id": "selection-report", "context": {"symbol": "US.SPY", "interval": "5m", "feature_fields": features,
                   "target_horizon_bars": 1, "split": {"TRAIN": days[:25], "VALIDATION": days[25:30], "TEST": days[30:]}},
            "candidate": {"strategy": window[0]["selected_recipe"], "execution_policy": asdict(policy)},
            "dev_selection": {"final_dev": window[0]}, "return_basis": threshold.RETURN_BASIS}}
    def evaluate(report):
        return final._evaluate_final_test(frozen, SimpleNamespace(data_id="data", as_dict=lambda: {
            "plan": {"target_horizon_bars": 1}, "report": report}))
    actual = evaluate(raw)
    assert len(actual["model"]["training_keys"]) == 30
    assert actual["context"]["purged_keys"] == [purged_key]
    assert actual["model"]["intercept"] == pytest.approx(float((25 * Fraction(7, 10000) + 5 * Fraction(73, 10000)) / 30))
    assert actual["model"]["intercept"] == pytest.approx(.0018)
    assert actual["model"]["means"] == actual["model"]["scales"] == actual["model"]["coefficients"] == [0.0] * 7
    assert len(actual["predictions"]) == 6 and all(row["target"] == "LONG" for row in actual["predictions"])
    assert actual["prediction_metrics"]["complete_target_count"] == 3
    factor = Fraction(665667, 667667)
    expected_cash = float((Fraction(11, 10) * factor) ** 3)
    for account in (actual["execution"], actual["benchmark"]["execution"]):
        assert account["metrics"]["final_cash"] == pytest.approx(expected_cash, abs=1e-14)
        assert [(row["entry_slot"], row["exit_slot"]) for row in account["trades"]] == [(1, 5)] * 3
    changed = deepcopy(raw)
    changed["targets"][30]["value"] = -1e12
    changed["observations"][30]["features"] = dict.fromkeys(features, -1e12)
    assert evaluate(changed) == actual


def test_real_seven_feature_linear_source_keeps_its_existing_width(quadratic_dev_case, tmp_path):
    data, plan, *_ = quadratic_dev_case
    plan = deepcopy(plan)
    plan.update(plan_schema_version=research.INTRADAY_RESEARCH_PLAN_VERSION,
                feature_fields=data.as_dict()["report"]["feature_names"][:7], strategies=[plan["strategies"][0]])
    prepared = research._prepare_intraday_research(plan, data=data)
    source = create_intraday_experiment(plan=plan, report=research._evaluate_intraday_research(plan, (plan,), ((),), prepared))
    path = write_strategy_experiment(source, path=tmp_path / "wide-source.json").path
    candidate = source.as_dict()["report"]["groups"][0]["results"][0]
    study = threshold.run_intraday_threshold_selection(path, expected_experiment_id=source.experiment_id,
        cost_index=0, candidate_index=0, expected_candidate_id=candidate["candidate_id"])
    path = write_strategy_experiment(study, path=tmp_path / "wide-threshold.json").path
    selection = final.freeze_intraday_threshold_selection(path, expected_experiment_id=study.experiment_id)
    report = final.run_intraday_final_test(selection)
    tested = final.create_intraday_test_experiment(selection, report)
    assert len(report["model"]["feature_fields"]) == len(report["model"]["coefficients"]) == 7
    assert report["strategy"]["kind"] == "RIDGE"
    assert "quadratic" not in selection.as_dict()["algorithm_versions"]
    assert "quadratic" not in tested.as_dict()["algorithm_versions"]
    assert replay_strategy_experiment(tested)["final_report_matches"]


def test_resealed_grammar_history_version_and_false_fit_full_replay(threshold_case, threshold_final_case, tmp_path, monkeypatch):
    selection, tested, _, _ = threshold_final_case
    for case in ("missing_account", "wrong_winner", "bad_method", "return_basis", "v2_source"):
        root = selection.as_dict()
        window = root["report"]["dev_selection"]["final_dev"]
        if case == "missing_account":
            window["family_results"].pop()
        elif case == "wrong_winner":
            window["selected_index"] = (window["selected_index"] + 1) % 4
        elif case == "bad_method":
            root["report"]["dev_selection"]["method"]["tie_break"] = "HIGHER_THRESHOLD"
        elif case == "return_basis":
            root["report"]["return_basis"]["corporate_action_coverage"] = "COMPLETE"
        else:
            root["plan"]["source_experiment"]["artifact_schema_version"] = "market-vault-intraday-inner-selection-v1"
        with pytest.raises(ValueError):
            StrategyExperiment(signed_selection(root))
    for case in ("history_keys", "history_purged", "history_boundary", "selection_pair", "result_version", "return_basis"):
        root = tested.as_dict()
        context = root["report"]["context"]
        if case == "history_keys":
            context["training_keys"] = context["training_keys"][1:]
        elif case == "history_purged":
            context["purged_keys"] = ["a" * 64]
        elif case == "history_boundary":
            context["training_boundary"] = selection.as_dict()["report"]["dev_selection"]["final_dev"]["training_boundary"]
        elif case == "selection_pair":
            root["plan"]["selection"]["artifact_schema_version"] = final.INTRADAY_SELECTION_V2_VERSION
        elif case == "result_version":
            root["report"]["result_schema_version"] = final.INTRADAY_FINAL_RESULT_V2_VERSION
        else:
            root["report"]["return_basis"]["price_basis"] = "ADJUSTED"
        bind(context, "context_id"); bind(root["report"], "final_test_id"); bind(root, "experiment_id")
        with pytest.raises(ValueError):
            StrategyExperiment(canonical_json(root))
    # All saved shape/hash/account checks accept this well-shaped false inner
    # fit; only reconstruction can prove its coefficients came from Q5.
    source = threshold_case[4].as_dict()
    model = source["report"]["final_dev"]["model"]
    model["ridge_model"]["coefficients"][0] += 1e-6
    bind(model["ridge_model"], "model_id"); bind(model, "model_id")
    bind(source["report"], "threshold_selection_id"); bind(source, "experiment_id")
    corrupted = StrategyExperiment(canonical_json(source))
    path = write_strategy_experiment(corrupted, path=tmp_path / "false-fit.json").path
    frozen = final.freeze_intraday_threshold_selection(path, expected_experiment_id=corrupted.experiment_id)
    with monkeypatch.context() as patch:
        patch.setattr(final, "_evaluate_final_test", lambda *a, **kw: pytest.fail("source mismatch reached TEST"))
        with pytest.raises(ValueError, match="complete source development report mismatch"):
            replay_strategy_experiment(frozen)


def test_real_cli_freeze_test_open_full_replay_relocation_and_immutable_recovery(threshold_case, threshold_final_case, tmp_path):
    data, ordinary, ordinary_path, _, study, study_path = threshold_case
    cli = str(Path(sys.executable).with_name("market-vault.exe" if os.name == "nt" else "market-vault"))
    env = {**os.environ, "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT / "tests")))}
    def command(*args, ok=True):
        result = subprocess.run([cli, *map(str, args)], cwd=ROOT, env=env, capture_output=True, text=True)
        assert result.returncode == (0 if ok else 1), result.stderr
        return json.loads(result.stdout if ok else result.stderr)
    source_copy, q5_copy = tmp_path / "source.json", tmp_path / "q5.json"
    source_copy.write_bytes(study_path.read_bytes()); q5_copy.write_bytes(data.path.read_bytes())
    selected_path, test_path = tmp_path / "selection.json", tmp_path / "test.json"
    freeze = ("research-intraday-freeze-threshold-selection", "--source-experiment", source_copy,
              "--expected-experiment-id", study.experiment_id, "--experiment", selected_path)
    result = command(*freeze)
    assert result["selection"]["artifact_schema_version"] == final.INTRADAY_SELECTION_V3_VERSION
    before = selected_path.read_bytes()
    assert not command(*freeze)["experiment"]["created_new_file"]
    assert command(*freeze, "--name", "Different", ok=False)["status"] == "FAILED"
    assert selected_path.read_bytes() == before
    relocated = tmp_path / "relocated-threshold.json"
    source_copy.rename(relocated)
    assert command("research-intraday-test", "--selection", selected_path, ok=False)["status"] == "FAILED"
    assert command("research-intraday-test", "--selection", selected_path, "--source-experiment-file", ordinary_path,
                   "--intraday-data-file", q5_copy, ok=False)["status"] == "FAILED"
    command("research-intraday-test", "--selection", selected_path, "--source-experiment-file", relocated,
            "--intraday-data-file", q5_copy, "--experiment", test_path)
    tested = load_strategy_experiment(test_path)
    assert tested.as_dict()["report"]["model"] == threshold_final_case[1].as_dict()["report"]["model"]
    for path in (selected_path, test_path):
        command("research-experiment-open", "--experiment", path)
        proof = command("research-experiment-replay", "--experiment", path,
                        "--source-experiment-file", relocated, "--intraday-data-file", q5_copy)
        assert proof["source_report_matches"] and proof["selection_report_matches"] and proof["report_matches"]
        assert proof.get("final_report_matches", path == selected_path)
    assert selected_path.read_bytes() == before and relocated.read_bytes() == study.content
    assert load_strategy_experiment(ordinary_path).experiment_id == ordinary.experiment_id


def test_explicit_saved_reader_boundaries_for_v3(threshold_final_case, monkeypatch, tmp_path, capsys):
    from market_vault import cli
    from market_vault.research import return_assessment
    from market_vault.research.intraday_performance import analyze_intraday_experiment, summarize_intraday_execution
    from market_vault.research.intraday_risk_diagnostics import analyze_intraday_risk_diagnostics
    from market_vault.research.intraday_saved_comparison import compare_saved_intraday_experiments
    from market_vault.research.return_assessment import ReturnAssessmentError, assess_saved_experiment
    selection, tested, _, path = threshold_final_case
    blocked = lambda *a, **kw: pytest.fail("recorded reader read Q5 or fitted")
    monkeypatch.setattr(return_assessment, "load_verified_multi_source_cross_day_dataset", blocked)
    monkeypatch.setattr(final, "run_intraday_execution", blocked)
    monkeypatch.setattr(final, "load_intraday_dataset", blocked)
    monkeypatch.setattr(final, "load_strategy_experiment", blocked)
    monkeypatch.setattr(research, "load_intraday_dataset", blocked)
    monkeypatch.setattr(research, "_fit", blocked)
    risk = analyze_intraday_risk_diagnostics(tested)
    assert risk["status"] == "SUCCESS"
    assert risk["strategy_diagnostics"]["report"]["fold_diagnostics"]["status"] == "NOT_APPLICABLE"
    performance = summarize_intraday_execution(tested.as_dict()["report"]["execution"])
    assert performance["summary"]["trade_count"]["value"] > 0
    with pytest.raises(ValueError, match="both indices must be zero"):
        analyze_intraday_risk_diagnostics(tested, candidate_index=1)
    with pytest.raises(ValueError):
        analyze_intraday_risk_diagnostics(selection)
    audited = analyze_intraday_experiment(tested)
    assert audited["performance"] == performance
    assert audited["benchmark"] == summarize_intraday_execution(tested.as_dict()["report"]["benchmark"]["execution"])
    assert audited["return_basis"] == tested.as_dict()["report"]["return_basis"]
    assert audited["candidate_id"] == tested.as_dict()["report"]["final_test_id"]
    assert audited["evaluation_scope"] == "FROZEN_SINGLE_CANDIDATE_TEST"
    for args in ({"candidate_index": 1}, {"cost_index": 1}, {"candidate_index": True}):
        with pytest.raises(ValueError):
            analyze_intraday_experiment(tested, **args)
    with pytest.raises(ValueError):
        analyze_intraday_experiment(selection)
    comparison = compare_saved_intraday_experiments(tested, tested)
    assert comparison["basis_matches"] and not comparison["delta_allowed"]
    assert comparison["delta_reasons"] == ["TEST_DESCRIPTIVE_ONLY"]
    assert comparison["left"]["return_basis"] == comparison["right"]["return_basis"] == audited["return_basis"]
    assert all(row["delta"]["value"] is None and row["delta"]["unavailable_reason"] == "TEST_DESCRIPTIVE_ONLY"
               for group in ("strategy_metrics", "benchmark_metrics") for row in comparison[group])
    for kwargs in ({"left_candidate_index": 1}, {"right_cost_index": True}):
        with pytest.raises(ValueError):
            compare_saved_intraday_experiments(tested, tested, **kwargs)
    with pytest.raises(ValueError):
        compare_saved_intraday_experiments(selection, tested)
    saved = path / "test.json"
    before = saved.read_bytes()
    assessment = assess_saved_experiment(saved)
    assert assessment["source_id"] == tested.experiment_id
    assert assessment["source_return_basis"] == audited["return_basis"]
    assert assessment["assessment_id"] == digest({key: value for key, value in assessment.items() if key != "assessment_id"})
    assert assessment["coverage_status"] == "UNKNOWN" and assessment["screening_status"] == "NOT_CHECKED"
    assert assessment["window_counts"]["STRATEGY_TRADE"] == performance["summary"]["trade_count"]["value"]
    events = {"schema_version": "market-vault-return-restrictions-v1", "provenance": "synthetic declared event",
              "events": [{"event_id": "known", "symbol": tested.as_dict()["report"]["context"]["symbol"],
                          "kind": "EFFECTIVE_INSTANT", "source": "test only",
                          "effective_at": tested.as_dict()["report"]["execution"]["trades"][0]["exit_time"]}]}
    restricted = assess_saved_experiment(saved, events=events)
    assert restricted["coverage_status"] == "PARTIAL" and restricted["restriction_matches"]
    event_path = tmp_path / "events.json"
    event_path.write_text(json.dumps(events))
    assert cli.main(["research-intraday-performance", "--experiment", str(saved)]) == 0
    assert json.loads(capsys.readouterr().out)["report"] == audited
    assert cli.main(["research-intraday-compare-saved", "--left", str(saved), "--right", str(saved)]) == 0
    assert json.loads(capsys.readouterr().out)["report"] == comparison
    assert cli.main(["research-return-assessment", "--experiment", str(saved), "--events", str(event_path)]) == 2
    assert json.loads(capsys.readouterr().out) == restricted
    with pytest.raises(ReturnAssessmentError):
        assess_saved_experiment(path / "selection.json")
    assert saved.read_bytes() == before
