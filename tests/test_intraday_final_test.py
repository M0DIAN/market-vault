"""Real-source final fitting, immutable selections and full-source TEST replay."""

import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest

import cross_day_helpers as cd
from market_vault import cli
from market_vault.backtest.intraday import _digest as execution_digest
from market_vault.research import intraday_final_test as final
from market_vault.research import intraday_research as research
from market_vault.research.intraday_data import build_intraday_dataset, digest, json_values, write_intraday_dataset
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.strategy_experiment import (
    StrategyExperiment, canonical_json, load_strategy_experiment, replay_strategy_experiment, write_strategy_experiment,
)
from test_intraday_experiment import intraday_experiment, signed as sign_source  # noqa: F401
from test_intraday_research import comparison_plan, diagnostic_plan, research_case, research_data  # noqa: F401


def bind(value, key, function=digest):
    value[key] = function({k: v for k, v in value.items() if k != key})


def sign_selection(root):
    root["report"]["plan_sha256"] = digest(root["plan"])
    bind(root["report"], "selection_id")
    bind(root, "experiment_id")
    return canonical_json(root)


def sign_test(root):
    """Re-sign raw changes so tests exercise grammar/replay beyond a checksum."""
    report = root["report"]
    if type(report["model"]) is dict:
        bind(report["model"], "model_id")
    bind(report["context"], "context_id")
    for record in (report, report["benchmark"]):
        execution = record["execution"]
        for trade in execution["trades"]:
            bind(trade, "trade_id", execution_digest)
        bind(execution, "execution_id", execution_digest)
        record["risk"]["execution_id"] = execution["execution_id"]
        bind(record["risk"], "risk_id")
    bind(report, "final_test_id")
    bind(root, "experiment_id")
    return canonical_json(root)


def freeze_source(source, path, *, cost=0, index=2):
    write_strategy_experiment(source, path=path)
    candidate = source.as_dict()["report"]["groups"][cost]["results"][index]
    return final.freeze_intraday_candidate(path, expected_experiment_id=source.experiment_id,
        cost_index=cost, candidate_index=index, expected_candidate_id=candidate["candidate_id"])


@pytest.fixture(scope="session")
def selection_case(intraday_experiment, tmp_path_factory):
    path = tmp_path_factory.mktemp("intraday-selection") / "development.json"
    return path, freeze_source(intraday_experiment, path)


@pytest.fixture(scope="session")
def final_case(selection_case):
    _, selection = selection_case
    calls = {"loads": 0, "fits": []}
    loader, fitter = final.load_intraday_dataset, research._fit
    def load(path):
        calls["loads"] += 1
        return loader(path)
    def fit(*args):
        calls["fits"].append((len(args[0]), args[2]))
        return fitter(*args)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(final, "load_intraday_dataset", load)
        patch.setattr(research, "_fit", fit)
        patch.setattr(research, "_evaluate_intraday_research", lambda *a: pytest.fail("ordinary TEST recomputed development"))
        report = final.run_intraday_final_test(selection)
    snapshot = final.create_intraday_test_experiment(selection, report, name="Frozen TEST")
    return report, snapshot, calls


def test_final_ridge_once_all_development_rows_tail_predictions_and_numeric_oracles(final_case):
    report, snapshot, calls = final_case
    assert calls == {"loads": 1, "fits": [(2130, 1.0)]}
    assert report["evaluation_scope"] == "FROZEN_SINGLE_CANDIDATE_TEST"
    model = report["model"]
    assert model["means"] == pytest.approx([114.875])
    assert model["scales"] == pytest.approx([8.657867327850818])
    # Independent Decimal normal equation, alpha=1, standardized training X:
    # beta = sum((x-xmean)*(y-ymean)) / ((n+alpha)*population_variance).
    assert model["coefficients"] == pytest.approx([0.00000108137341205827997116], rel=1e-9)
    assert model["intercept"] == pytest.approx(0.00009011451684023604625182, rel=1e-9)
    assert report["predictions"][0]["score"] == pytest.approx(0.0002307200947431138995, rel=1e-9)
    assert report["predictions"][-1]["score"] == pytest.approx(0.0002361764887056775902, rel=1e-9)
    assert len(report["predictions"]) == 444
    assert report["prediction_metrics"]["complete_target_count"] == 426
    assert report["prediction_metrics"]["prediction_count"] == 444
    assert report["context"]["purged_keys"] == []
    assert len(report["execution"]["daily"]) == report["risk"]["return_count"] == 6
    assert report["execution"]["daily"][0]["cash_open"] == 1
    benchmark = report["benchmark"]
    assert benchmark["execution"]["metrics"]["trade_count"] == 6
    assert benchmark["execution"]["metrics"]["final_cash"] == pytest.approx(1.008895340376)
    assert benchmark["risk"]["sharpe_ratio"] == pytest.approx(1.238081869396555)
    assert all((t["entry_slot"], t["exit_slot"], t["exit_reason"]) == (5, 77, "EOD") for t in benchmark["execution"]["trades"])
    assert "groups" not in snapshot.as_dict()["plan"]["selection"]["report"]
    assert "model" not in snapshot.as_dict()["plan"]["selection"]["report"]


def test_freeze_second_cost_nonfirst_candidate_without_data_or_fit(research_case, tmp_path, monkeypatch):
    _, plan, _ = research_case
    diagnostic = diagnostic_plan(plan)
    source = create_intraday_experiment(plan=diagnostic, report=research.run_intraday_research(diagnostic))
    with monkeypatch.context() as patch:
        patch.setattr(final, "load_intraday_dataset", lambda *a: pytest.fail("Freeze read Q5 data"))
        patch.setattr(research, "_fit", lambda *a: pytest.fail("Freeze fitted"))
        selection = freeze_source(source, tmp_path / "diagnostics.json", cost=1, index=2)
        frozen = selection.as_dict()["report"]["candidate"]
        assert frozen["axis_values"] == [1000, 0]
        assert frozen["strategy"]["alpha"] == 1000
        assert frozen["execution_policy"]["commission_bps"] == 10
        assert frozen["execution_policy"]["slippage_bps"] == 5
        assert "max_hold_bars" not in selection.as_dict()["report"]["benchmark_definition"]
        assert write_strategy_experiment(selection, path=tmp_path / "selection.json").created_new_file
        assert load_strategy_experiment(tmp_path / "selection.json").content == selection.content


@pytest.mark.parametrize("index", [0, 1])
def test_feature_and_composite_test_fit_no_model(intraday_experiment, tmp_path, monkeypatch, index):
    selection = freeze_source(intraday_experiment, tmp_path / "source.json", index=index)
    monkeypatch.setattr(research, "_fit", lambda *a: pytest.fail("rule TEST fitted"))
    report = final.run_intraday_final_test(selection)
    assert report["model"] is None and report["prediction_metrics"] is None
    assert len(report["predictions"]) == 444
    assert report["execution"]["metrics"]["trade_count"] == (0 if index == 0 else 36)
    assert final.create_intraday_test_experiment(selection, report).as_dict()["report"] == report


def test_offline_open_exclusive_save_and_embedded_selection(final_case, selection_case, tmp_path, monkeypatch):
    _, snapshot, _ = final_case
    _, selection = selection_case
    monkeypatch.setattr(final, "load_intraday_dataset", lambda *a: pytest.fail("offline read data"))
    monkeypatch.setattr(final, "load_strategy_experiment", lambda *a: pytest.fail("offline read development source"))
    monkeypatch.setattr(research, "_fit", lambda *a: pytest.fail("offline fitted"))
    for value, name in ((selection, "selection.json"), (snapshot, "test.json")):
        path = tmp_path / name
        assert write_strategy_experiment(value, path=path).created_new_file
        assert not write_strategy_experiment(value, path=path).created_new_file
        assert load_strategy_experiment(path).content == value.content
        root = value.as_dict()
        root["notes"] = "changed metadata"
        bind(root, "experiment_id")
        with pytest.raises(ValueError, match="choose a new file path"):
            write_strategy_experiment(StrategyExperiment(canonical_json(root)), path=path)
        assert path.read_bytes() == value.content
    assert snapshot.as_dict()["plan"]["selection"] == selection.as_dict()


@pytest.mark.parametrize("case", ["model_keys", "negative_scale", "prediction_clock", "daily_shape", "benchmark_decision",
    "context_overlap", "errors", "nested_test", "bool_strategy", "bool_policy", "bool_execution_policy", "bool_benchmark_policy",
    "decision_slot", "decision_day"])
def test_resigned_malformed_test_records_are_rejected(final_case, case):
    root = final_case[1].as_dict()
    report = root["report"]
    if case == "model_keys":
        report["model"]["training_keys"].pop()
    elif case == "negative_scale":
        report["model"]["scales"][0] = -1
    elif case == "prediction_clock":
        report["predictions"][0]["decision_time"] = "bad"
        report["execution"]["decisions"][0]["decision_time"] = "bad"
    elif case == "daily_shape":
        report["execution"]["daily"][0] = {}
    elif case == "benchmark_decision":
        report["benchmark"]["execution"]["decisions"][0] = {}
    elif case == "context_overlap":
        report["context"]["purged_keys"] = report["context"]["test_keys"][:1]
    elif case == "errors":
        report["prediction_metrics"]["complete_target_count"] = 445
    elif case == "bool_strategy":
        report["strategy"]["threshold"] = False
    elif case == "bool_policy":
        report["execution_policy"]["commission_bps"] = False
    elif case == "bool_execution_policy":
        report["execution"]["policy"]["commission_bps"] = False
    elif case == "bool_benchmark_policy":
        report["benchmark"]["execution"]["policy"]["commission_bps"] = False
    elif case == "decision_slot":
        report["predictions"][0]["slot"] = report["execution"]["decisions"][0]["slot"] = 999
    elif case == "decision_day":
        day = report["context"]["split"]["TEST"][1]
        report["predictions"][0]["trading_day"] = report["execution"]["decisions"][0]["trading_day"] = day
    else:
        root["plan"]["selection"] = {"artifact_schema_version": final.INTRADAY_TEST_EXPERIMENT_VERSION}
    with pytest.raises((ValueError, TypeError, KeyError)):
        StrategyExperiment(sign_test(root))


def test_version_source_and_candidate_guards_precede_data_and_fit(selection_case, final_case, tmp_path, monkeypatch):
    source_path, selection = selection_case
    monkeypatch.setattr(final, "load_intraday_dataset", lambda *a: pytest.fail("guard read data"))
    monkeypatch.setattr(research, "_fit", lambda *a: pytest.fail("guard fitted"))
    root = selection.as_dict()
    root["algorithm_versions"]["selection"] = root["report"]["version"] = "historical-selection"
    historical = StrategyExperiment(sign_selection(root))
    with monkeypatch.context() as patch:
        patch.setattr(final, "load_strategy_experiment", lambda *a: pytest.fail("version guard read source"))
        with pytest.raises(ValueError, match="no source was read"):
            final.run_intraday_final_test(historical)
    root = selection.as_dict()
    root["plan"]["selection"]["candidate_id"] = "0" * 64
    with pytest.raises(ValueError, match="candidate identity"):
        final.run_intraday_final_test(StrategyExperiment(sign_selection(root)))
    root = selection.as_dict()
    root["plan"]["source_experiment"]["experiment_id"] = "0" * 64
    with pytest.raises(ValueError, match="source experiment identity"):
        final.run_intraday_final_test(StrategyExperiment(sign_selection(root)))
    root = final_case[1].as_dict()
    root["algorithm_versions"]["final_test"] = root["report"]["version"] = "historical-final-test"
    with pytest.raises(ValueError, match="no source was read"):
        replay_strategy_experiment(StrategyExperiment(sign_test(root)))
    for index in (-1, True):
        with pytest.raises(ValueError, match="nonnegative integer"):
            final.freeze_intraday_candidate(tmp_path / "unread", expected_experiment_id="0" * 64,
                cost_index=index, candidate_index=0, expected_candidate_id="0" * 64)


def test_real_test_gap_fails_before_final_fit_even_for_flat(tmp_path, monkeypatch):
    data = research_data(tmp_path / "data", missing=True, missing_day=30)
    plan = comparison_plan(data)
    source = create_intraday_experiment(plan=plan, report=research.run_intraday_research(plan))
    monkeypatch.setattr(research, "_fit", lambda *a: pytest.fail("TEST price gap fitted"))
    for index in (0, 2):
        selection = freeze_source(source, tmp_path / "source.json", index=index)
        with pytest.raises(ValueError, match="incomplete session price flow"):
            final.run_intraday_final_test(selection)


def test_early_development_benchmark_does_not_shorten_normal_test(tmp_path, monkeypatch):
    # Legal qualified calendar: Q7 evaluates the early-close validation day,
    # then Final evaluates a normal TEST day through real Canonical/Q5 files.
    entries = [("2025-11-26", "N"), ("2025-11-27", "C"), ("2025-11-28", "E"),
               ("2025-11-29", "C"), ("2025-11-30", "C"), ("2025-12-01", "N")]
    trading = [(day, profile) for day, profile in entries if profile != "C"]
    bars = [cd.bar(day, slot, open=100.0 + slot / 100, close=100.005 + slot / 100, code="US.SPY")
            for day, profile in trading for slot in range(42 if profile == "E" else 78)]
    built = cd.build(tmp_path / "canonical", bars)
    data = build_intraday_dataset({"plan_schema_version": "market-vault-intraday-data-plan-v1",
        "canonical_build_dirs": [str(built.build_path)], "schedule": json_values(asdict(cd.schedule(entries))),
        "symbol": "US.SPY", "interval": "5m", "preset": "LIGHT_TECHNICAL", "stride_bars": 1,
        "target_horizon_bars": 3, "dataset_as_of": cd.AS_OF.isoformat()})
    path = write_intraday_dataset(data, path=tmp_path / "data.json")
    plan = {"plan_schema_version": research.INTRADAY_RESEARCH_PLAN_VERSION, "intraday_data_path": str(path),
        "data_id": data.data_id, "feature_fields": ["sma_5"],
        "split": {"train_end_day": trading[0][0], "validation_end_day": trading[1][0], "test_end_day": trading[2][0]},
        "walk_forward": {"minimum_train_days": 1, "validation_days": 1, "step_days": 1},
        "strategies": [{"kind": "FEATURE_RULE", "name": "Long", "signal_field": "sma_5", "comparator": "GT", "threshold": 0}],
        "execution": {"commission_bps": 0, "slippage_bps": 0, "entry_delay_minutes": 15,
                      "stop_new_minutes": 30, "flatten_minutes": 5, "max_hold_bars": 12}}
    monkeypatch.setattr(research, "_fit", lambda *a: pytest.fail("rule path fitted"))
    source_report = research.run_intraday_research(plan)
    assert source_report["groups"][0]["benchmark"]["execution"]["policy"]["max_hold_bars"] == 42
    source = create_intraday_experiment(plan=plan, report=source_report)
    selection = freeze_source(source, tmp_path / "source.json", index=0)
    result = final.run_intraday_final_test(selection)
    benchmark = result["benchmark"]["execution"]
    assert benchmark["policy"]["max_hold_bars"] == 78
    assert len(benchmark["trades"]) == 1
    assert (benchmark["trades"][0]["held_bars"], benchmark["trades"][0]["exit_reason"]) == (72, "EOD")
    assert result["risk"]["return_count"] == 1
    assert result["risk"]["unavailable_reason"] == "INSUFFICIENT_DAILY_RETURNS"
    assert final.create_intraday_test_experiment(selection, result).as_dict()["report"] == result


def test_real_test_only_change_does_not_change_final_training(final_case, selection_case, tmp_path, monkeypatch):
    old, _, _ = final_case
    changed_data = research_data(tmp_path / "changed", test_change=True)
    plan = comparison_plan(changed_data)
    source = create_intraday_experiment(plan=plan, report=research.run_intraday_research(plan))
    selection = freeze_source(source, tmp_path / "changed-source.json")
    current = final.run_intraday_final_test(selection)
    for key in ("alpha", "feature_fields", "means", "scales", "coefficients", "intercept"):
        assert current["model"][key] == old["model"][key]
    assert current["strategy"] == old["strategy"] and current["execution_policy"] == old["execution_policy"]
    assert current["predictions"][0]["score"] != old["predictions"][0]["score"]
    monkeypatch.setattr(research, "_fit", lambda *a: pytest.fail("wrong data identity reached a final fit"))
    with pytest.raises(ValueError, match="data identity differs"):
        final.run_intraday_final_test(selection_case[1], intraday_data_file=changed_data.path)


def test_final_uses_actual_target_end_and_preserves_single_empty_day(selection_case, research_case):
    _, selection = selection_case
    data, _, _ = research_case
    source = data.as_dict()
    fake = SimpleNamespace(data_id=data.data_id, as_dict=lambda: source)
    boundary = source["report"]["sessions"][30]["open_time"]
    source["report"]["targets"][0]["actual_label_end_time"] = boundary
    # Pure internal row-view counterexample, not a persisted/verified artifact.
    absent = source["report"]["sessions"][30]["trading_day"]
    source["report"]["observations"] = [r for r in source["report"]["observations"] if r["trading_day"] != absent]
    report = final._evaluate_final_test(selection.as_dict(), fake)
    assert len(report["context"]["training_keys"]) == 2129
    assert len(report["context"]["purged_keys"]) == 1
    assert len(report["execution"]["daily"]) == 6 and report["execution"]["daily"][0]["return"] == 0
    source["report"]["observations"] = [r for r in source["report"]["observations"] if r["trading_day"] < absent]
    with pytest.raises(ValueError, match="TEST has no READY"):
        final._evaluate_final_test(selection.as_dict(), fake)


def test_selection_replay_runs_source_only_and_test_replay_loads_once(selection_case, final_case, monkeypatch):
    _, selection = selection_case
    _, snapshot, _ = final_case
    with monkeypatch.context() as patch:
        patch.setattr(final, "_evaluate_final_test", lambda *a: pytest.fail("selection replay ran TEST"))
        result = replay_strategy_experiment(selection)
        assert result["source_report_matches"] and result["selection_report_matches"]
        assert "final_report_matches" not in result
    loads, fits = [], []
    loader, fitter = final.load_intraday_dataset, research._fit
    def load(path):
        loads.append(path)
        return loader(path)
    def fit(*args):
        fits.append(len(args[0]))
        return fitter(*args)
    monkeypatch.setattr(final, "load_intraday_dataset", load)
    monkeypatch.setattr(research, "_fit", fit)
    result = replay_strategy_experiment(snapshot)
    assert len(loads) == 1 and fits == [1420, 1775, 2130]
    assert result["source_report_matches"] and result["selection_report_matches"] and result["final_report_matches"]
    assert result["expected_report_sha256"] == result["actual_report_sha256"]


def test_full_replay_rejects_unselected_source_raw_change(intraday_experiment, tmp_path, monkeypatch):
    root = intraday_experiment.as_dict()
    unselected = root["report"]["groups"][0]["results"][0]
    unselected["predictions"][157]["score"] += 1e-8
    unselected["execution"]["decisions"][157]["score"] += 1e-8
    source = StrategyExperiment(sign_source(root))
    selection = freeze_source(source, tmp_path / "source.json")
    # Ordinary TEST verifies source/config identity, not the development math.
    report = final.run_intraday_final_test(selection)
    snapshot = final.create_intraday_test_experiment(selection, report)
    monkeypatch.setattr(final, "_evaluate_final_test", lambda *a: pytest.fail("source mismatch reached Final fit"))
    with pytest.raises(ValueError, match="complete source development report mismatch"):
        replay_strategy_experiment(snapshot)


def test_full_replay_rejects_hidden_final_raw_change(final_case):
    root = final_case[1].as_dict()
    root["report"]["predictions"][157]["score"] += 1e-8
    root["report"]["execution"]["decisions"][157]["score"] += 1e-8
    with pytest.raises(ValueError, match="complete final TEST report mismatch"):
        replay_strategy_experiment(StrategyExperiment(sign_test(root)))


def test_recorded_windows_paths_with_explicit_two_file_relocation(selection_case, research_case, tmp_path):
    path, selection = selection_case
    data, _, _ = research_case
    root = selection.as_dict()
    root["plan"]["source_experiment"]["path"] = r"C:\archive\development.json"
    moved = StrategyExperiment(sign_selection(root))
    data_path, source_path = tmp_path / "data.json", tmp_path / "development.json"
    data_path.write_bytes(data.content)
    source_path.write_bytes(path.read_bytes())
    before = moved.content
    assert replay_strategy_experiment(moved, source_experiment_file=source_path, intraday_data_file=data_path)["report_matches"]
    assert moved.content == before
    with pytest.raises(ValueError, match="Dataset directory"):
        replay_strategy_experiment(moved, dataset_build_dir=tmp_path)
    with pytest.raises(ValueError, match="source_experiment_file"):
        replay_strategy_experiment(load_strategy_experiment(source_path), source_experiment_file=source_path)


def test_actual_cli_freeze_test_open_and_structured_preflight(selection_case, tmp_path, capsys):
    source, selection = selection_case
    root = selection.as_dict()
    frozen, tested = tmp_path / "selection.json", tmp_path / "test.json"
    args = ["research-intraday-freeze", "--source-experiment", str(source),
        "--expected-experiment-id", root["plan"]["source_experiment"]["experiment_id"],
        "--cost-index", "0", "--candidate-index", "2",
        "--expected-candidate-id", root["plan"]["selection"]["candidate_id"], "--experiment", str(frozen)]
    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out)["selection"]["evaluation_mode"] == "INTRADAY_SELECTION"
    assert cli.main(["research-intraday-test", "--selection", str(frozen), "--experiment", str(tested)]) == 0
    assert len(json.loads(capsys.readouterr().out)["report"]["model"]["training_keys"]) == 2130
    assert cli.main(["research-experiment-open", "--experiment", str(tested)]) == 0
    assert json.loads(capsys.readouterr().out)["result_schema_version"] == "market-vault-strategy-experiment-cli-result-v3"
    assert cli.main(["research-intraday-test", "--selection", "/unread", "--name", "unsaved"]) == 1
    captured = capsys.readouterr()
    assert not captured.out and "require --experiment" in json.loads(captured.err)["error"]
    bad = args[:]
    bad[bad.index("--cost-index") + 1] = "True"
    assert cli.main(bad) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "FAILED"
