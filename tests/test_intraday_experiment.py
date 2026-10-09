"""Saved raw evidence, offline grammar, actual replay and installed CLI boundary."""

from copy import deepcopy
from hashlib import sha256
import json

import pytest

from market_vault import cli
from market_vault.backtest.intraday import _digest as execution_digest
from market_vault.research import intraday_research as research
from market_vault.research.intraday_data import digest
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.strategy_experiment import (
    StrategyExperiment, canonical_json, load_strategy_experiment, replay_strategy_experiment, write_strategy_experiment,
)
from test_intraday_research import execution_scenarios_case, execution_scenarios_plan, research_case  # noqa: F401


def signed(root):
    """Re-sign changed records to test grammar/replay beyond checksum detection."""
    def bind(value, key, function=digest):
        value[key] = function({k: v for k, v in value.items() if k != key})
    report = root["report"]
    context = report["context"]
    for fold in context["folds"]:
        bind(fold, "fold_id")
    bind(context, "context_id")
    for group in report["groups"]:
        for candidate in [*group["results"], group["benchmark"]]:
            execution = candidate["execution"]
            for trade in execution["trades"]:
                bind(trade, "trade_id", execution_digest)
            bind(execution, "execution_id", execution_digest)
            candidate["risk"]["execution_id"] = execution["execution_id"]
            bind(candidate["risk"], "risk_id")
            if "candidate_id" in candidate:
                candidate["context_id"] = context["context_id"]
                bind(candidate, "candidate_id")
    bind(report, "research_id")
    bind(root, "experiment_id", lambda value: sha256(canonical_json(value)).hexdigest())
    return canonical_json(root)


@pytest.fixture(scope="session")
def intraday_experiment(research_case):
    _, plan, report = research_case
    return create_intraday_experiment(plan=plan, report=report, name="Development", notes="Explicit candidate evidence")


def signed_scenarios(root):
    for row in root["report"]["scenarios"]:
        row["experiment"] = json.loads(signed(row["experiment"]))
    root["report"]["scenarios_id"] = digest({k: v for k, v in root["report"].items() if k != "scenarios_id"})
    root["experiment_id"] = digest({k: v for k, v in root.items() if k != "experiment_id"})
    return canonical_json(root)


def test_scenarios_offline_cli_export_guards_and_nonfirst_child_final_test(execution_scenarios_case, tmp_path, monkeypatch, capsys):
    from market_vault.research.intraday_execution_scenarios import extract_intraday_execution_scenario
    from market_vault.research.intraday_final_test import freeze_intraday_candidate, run_intraday_final_test
    _, _, collection, _ = execution_scenarios_case
    path, output = tmp_path / "collection.json", tmp_path / "delayed.json"
    write_strategy_experiment(collection, path=path)
    child = collection.as_dict()["report"]["scenarios"][1]["experiment"]
    selected = child["report"]["groups"][0]["results"][2]
    capture = {"expected_experiment_id": collection.experiment_id, "scenario_index": 1,
               "expected_child_experiment_id": child["experiment_id"]}
    with monkeypatch.context() as patch:
        patch.setattr(research, "load_intraday_dataset", lambda *a, **kw: pytest.fail("Open/Export read source"))
        patch.setattr(research, "_fit", lambda *a, **kw: pytest.fail("Open/Export fitted"))
        assert cli.main(["research-experiment-open", "--experiment", str(path)]) == 0
        opened = json.loads(capsys.readouterr().out)
        assert opened["result_schema_version"] == "market-vault-strategy-experiment-cli-result-v3"
        assert opened["experiment"]["experiment_id"] == collection.experiment_id
        args = ["research-intraday-export-scenario", "--experiment", str(path),
                "--expected-experiment-id", collection.experiment_id, "--scenario-index", "1",
                "--expected-child-experiment-id", child["experiment_id"], "--output", str(output)]
        assert cli.main(args) == 0
        assert json.loads(capsys.readouterr().out)["experiment"]["created_new_file"]
        assert output.read_bytes() == canonical_json(child)
        assert cli.main(args) == 0
        assert not json.loads(capsys.readouterr().out)["experiment"]["created_new_file"]
        for changed in ({"expected_experiment_id": "0" * 64}, {"scenario_index": True},
                        {"scenario_index": 2}, {"expected_child_experiment_id": "0" * 64}):
            with pytest.raises(ValueError):
                extract_intraday_execution_scenario(collection, **{**capture, **changed})
        with pytest.raises(ValueError, match="choose a new file path"):
            write_strategy_experiment(collection, path=output)
        assert output.read_bytes() == canonical_json(child) and path.read_bytes() == collection.content
    with pytest.raises(ValueError):
        freeze_intraday_candidate(path, expected_experiment_id=collection.experiment_id, cost_index=0,
                                  candidate_index=2, expected_candidate_id=selected["candidate_id"])
    frozen = freeze_intraday_candidate(output, expected_experiment_id=child["experiment_id"], cost_index=0,
                                      candidate_index=2, expected_candidate_id=selected["candidate_id"])
    tested = run_intraday_final_test(frozen)
    assert tested["execution_policy"] == child["plan"]["execution"]
    assert tested["strategy"]["name"] == "Ridge" and tested["execution_policy"]["max_hold_bars"] == 3
    assert len(tested["context"]["split"]["TEST"]) == len(tested["execution"]["daily"]) == 6
    assert path.read_bytes() == collection.content


@pytest.mark.parametrize("case", ["swapped_child", "shared_predictions", "missing_child", "recursive_child", "bool_index"])
def test_scenario_collection_checks_relationships_beyond_individual_q7_grammar(execution_scenarios_case, case):
    root = execution_scenarios_case[2].as_dict()
    scenarios = root["report"]["scenarios"]
    if case == "swapped_child":
        scenarios[0]["experiment"], scenarios[1]["experiment"] = scenarios[1]["experiment"], scenarios[0]["experiment"]
    elif case == "shared_predictions":
        candidate = scenarios[1]["experiment"]["report"]["groups"][0]["results"][2]
        candidate["predictions"][157]["score"] += 1e-8
        candidate["execution"]["decisions"][157]["score"] += 1e-8
    elif case == "missing_child":
        scenarios.pop()
    elif case == "bool_index":
        scenarios[1]["scenario_index"] = True
    else:
        # Signed ordinary children are replaced afterwards to avoid making
        # this test helper recursively sign the intentionally forbidden type.
        root = json.loads(signed_scenarios(root))
        root["report"]["scenarios"][1]["experiment"] = {"artifact_schema_version": root["artifact_schema_version"],
                                                        "evaluation_mode": root["evaluation_mode"]}
        root["report"]["scenarios_id"] = digest({k: v for k, v in root["report"].items() if k != "scenarios_id"})
        root["experiment_id"] = digest({k: v for k, v in root.items() if k != "experiment_id"})
        with pytest.raises(ValueError, match="ordinary Q7"):
            StrategyExperiment(canonical_json(root))
        return
    with pytest.raises(ValueError):
        StrategyExperiment(signed_scenarios(root))


def test_scenario_replay_preserves_metadata_and_checks_hidden_unselected_child(execution_scenarios_case, tmp_path, monkeypatch):
    data, _, collection, _ = execution_scenarios_case
    root = collection.as_dict()
    root["environment"]["python"] = "historical root environment"
    root["report"]["scenarios"][1]["experiment"]["environment"]["python"] = "historical child environment"
    root["report"]["scenarios"][1]["experiment"]["notes"] = "Recorded metadata remains diagnostic"
    snapshot = StrategyExperiment(signed_scenarios(root))
    moved = tmp_path / "relocated-data.json"
    moved.write_bytes(data.content)
    assert replay_strategy_experiment(snapshot, intraday_data_file=moved)["report_matches"]
    altered = snapshot.as_dict()
    altered["report"]["scenarios"][1]["experiment"]["report"]["groups"][0]["results"][2]["execution"]["ledger"][157]["drawdown"] += 1e-8
    record = StrategyExperiment(signed_scenarios(altered))
    with pytest.raises(ValueError, match="complete execution-scenarios report mismatch"):
        replay_strategy_experiment(record)
    historical = snapshot.as_dict()
    historical["algorithm_versions"]["execution_scenarios"] = "historical-scenarios-v0"
    historical["report"]["version"] = "historical-scenarios-v0"
    historical = StrategyExperiment(signed_scenarios(historical))
    monkeypatch.setattr(research, "load_intraday_dataset", lambda *a, **kw: pytest.fail("incompatible replay read source"))
    with pytest.raises(ValueError, match="versions differ"):
        replay_strategy_experiment(historical)
    with pytest.raises(ValueError, match="intraday_data_file"):
        replay_strategy_experiment(snapshot, dataset_build_dir=tmp_path)
    with pytest.raises(ValueError, match="source_experiment_file"):
        replay_strategy_experiment(snapshot, source_experiment_file=tmp_path / "unrelated.json")


def test_actual_execution_scenarios_cli_normalizes_relative_plan_and_saves_all(research_case, tmp_path, capsys):
    data, comparison, _ = research_case
    plan = execution_scenarios_plan(comparison)
    plan["comparison_plan"]["strategies"] = [comparison["strategies"][0]]
    plan["comparison_plan"]["intraday_data_path"] = "data.json"
    (tmp_path / "data.json").write_bytes(data.content)
    path, output = tmp_path / "scenarios-plan.json", tmp_path / "all-scenarios.json"
    path.write_text(json.dumps(plan))
    assert cli.main(["research-intraday-scenarios", "--plan", str(path), "--experiment", str(output), "--name", "CLI scenarios"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["collection"]["report"]["evaluation_count"] == 2
    assert payload["collection"]["plan"]["comparison_plan"]["intraday_data_path"] == str(tmp_path / "data.json")
    assert load_strategy_experiment(output).as_dict() == payload["collection"]
    assert cli.main(["research-intraday-scenarios", "--plan", str(path), "--name", "unsaved"]) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "FAILED"


def test_offline_open_exclusive_writer_and_actual_full_replay(intraday_experiment, tmp_path, monkeypatch):
    path = tmp_path / "experiment.json"
    with monkeypatch.context() as patch:
        patch.setattr(research, "load_intraday_dataset", lambda *a: pytest.fail("offline Open/Save read source"))
        patch.setattr(research, "_fit", lambda *a: pytest.fail("offline Open/Save fitted a model"))
        assert write_strategy_experiment(intraday_experiment, path=path).created_new_file
        assert not write_strategy_experiment(intraday_experiment, path=path).created_new_file
        opened = load_strategy_experiment(path)
        assert opened.content == intraday_experiment.content
        different = opened.as_dict()
        different["name"] = "Another saved record"
        with pytest.raises(ValueError, match="choose a new file path"):
            write_strategy_experiment(StrategyExperiment(signed(different)), path=path)
        assert path.read_bytes() == intraday_experiment.content
    result = replay_strategy_experiment(opened)
    assert result["report_matches"] and result["expected_report_sha256"] == result["actual_report_sha256"]


@pytest.mark.parametrize("case", ["trade_shape", "transaction_shape", "daily_clock", "benchmark_decision", "negative_fee", "prediction_clock", "target_horizon"])
def test_malformed_nested_record_rejected_before_desktop_presentation(intraday_experiment, case):
    root = intraday_experiment.as_dict()
    candidate = root["report"]["groups"][0]["results"][1]
    if case == "trade_shape":
        candidate["execution"]["trades"][0] = {}
    elif case == "transaction_shape":
        candidate["execution"]["transactions"][0] = {"garbage": "garbage"}
    elif case == "daily_clock":
        candidate["execution"]["daily"][0]["open_time"] = "not a time"
    elif case == "benchmark_decision":
        root["report"]["groups"][0]["benchmark"]["execution"]["decisions"] = [{"garbage": "garbage"}]
    elif case == "negative_fee":
        candidate["execution"]["trades"][0]["entry_commission"] = -100
    elif case == "prediction_clock":
        candidate["predictions"][0]["decision_time"] = "not a time"
        candidate["execution"]["decisions"][0]["decision_time"] = "not a time"
    else:
        root["report"]["context"]["target_horizon_bars"] = "not a horizon"
    with pytest.raises((ValueError, TypeError, KeyError)):
        StrategyExperiment(signed(root))


def test_replay_compares_hidden_raw_predictions_not_displayed_rounding(intraday_experiment):
    root = intraday_experiment.as_dict()
    candidate = root["report"]["groups"][0]["results"][2]
    candidate["predictions"][157]["score"] += 1e-8
    candidate["execution"]["decisions"][157]["score"] += 1e-8
    recorded = StrategyExperiment(signed(root))
    with pytest.raises(ValueError, match="complete intraday report mismatch"):
        replay_strategy_experiment(recorded)


def test_historical_versions_open_but_replay_rejects_before_io(intraday_experiment, monkeypatch):
    root = intraday_experiment.as_dict()
    root["algorithm_versions"]["research"] = "historical-research-version"
    root["report"]["version"] = root["algorithm_versions"]["research"]
    historical = StrategyExperiment(signed(root))
    monkeypatch.setattr(research, "load_intraday_dataset", lambda *a: pytest.fail("version mismatch read source"))
    with pytest.raises(ValueError, match="no source was read"):
        replay_strategy_experiment(historical)


def test_windows_recorded_locator_offline_and_real_relocated_source_replay(intraday_experiment, research_case, tmp_path):
    data, _, _ = research_case
    root = intraday_experiment.as_dict()
    root["plan"]["intraday_data_path"] = r"C:\archive\intraday.json"
    root["report"]["plan_sha256"] = digest(root["plan"])
    recorded = StrategyExperiment(signed(root))
    content = recorded.content
    relocated = tmp_path / "same-data.json"
    relocated.write_bytes(data.content)
    assert replay_strategy_experiment(recorded, intraday_data_file=relocated)["report_matches"]
    assert recorded.content == content and recorded.as_dict()["plan"]["intraday_data_path"] == r"C:\archive\intraday.json"
    with pytest.raises(ValueError, match="intraday_data_file"):
        replay_strategy_experiment(recorded, dataset_build_dir=tmp_path)


def test_data_identity_guard_precedes_fit(research_case, monkeypatch):
    _, plan, _ = research_case
    monkeypatch.setattr(research, "_fit", lambda *a: pytest.fail("wrong identity fitted"))
    with pytest.raises(ValueError, match="identity differs"):
        research.run_intraday_research({**plan, "data_id": "0" * 64})


def test_actual_cli_plan_compare_diagnose_and_experiment_open(research_case, tmp_path, capsys):
    data, plan, _ = research_case
    assert cli.main(["research-intraday-plan", "--data", str(data.path), "--commission-bps", "0", "--slippage-bps", "0"]) == 0
    proposal = json.loads(capsys.readouterr().out)
    assert proposal["plan"]["split"] == plan["split"]
    path, output = tmp_path / "plan.json", tmp_path / "saved.json"
    comparison = deepcopy(plan)
    comparison["strategies"] = [plan["strategies"][0]]
    path.write_text(json.dumps(comparison))
    assert cli.main(["research-intraday-compare", "--plan", str(path), "--experiment", str(output), "--name", "CLI record"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["report"]["evaluation_scope"] == "DEVELOPMENT_WALK_FORWARD_ONLY"
    assert cli.main(["research-experiment-open", "--experiment", str(output)]) == 0
    opened = json.loads(capsys.readouterr().out)
    assert opened["result_schema_version"] == "market-vault-strategy-experiment-cli-result-v3"
    assert opened["experiment"]["name"] == "CLI record"
    diagnostics = {"plan_schema_version": research.INTRADAY_DIAGNOSTICS_PLAN_VERSION, "comparison_plan": comparison,
                   "strategy_name": "Flat", "parameter_axes": [{"parameter": "threshold", "values": [0, 1000000]}],
                   "cost_scenarios": [{"commission_bps": 0, "slippage_bps": 0}]}
    path.write_text(json.dumps(diagnostics))
    assert cli.main(["research-intraday-diagnose", "--plan", str(path), "--experiment", str(tmp_path / "diagnostics.json")]) == 0
    diagnosed = json.loads(capsys.readouterr().out)
    assert diagnosed["report"]["evaluation_count"] == 2
    assert load_strategy_experiment(tmp_path / "diagnostics.json").as_dict()["evaluation_mode"] == "INTRADAY_DIAGNOSTICS"


@pytest.mark.parametrize("arguments", [
    ["--name", "unsaved metadata"], ["--notes", "unsaved notes"], [],
])
def test_cli_preflight_failures_have_json_envelope(tmp_path, capsys, arguments):
    path = tmp_path / "invalid.json"
    path.write_text("[]")
    assert cli.main(["research-intraday-compare", "--plan", str(path), *arguments]) == 1
    captured = capsys.readouterr()
    assert not captured.out
    result = json.loads(captured.err)
    assert result["status"] == "FAILED"
    if arguments:
        assert "require --experiment" in result["error"]
