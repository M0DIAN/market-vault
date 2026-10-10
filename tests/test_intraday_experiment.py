"""Saved raw evidence, offline grammar, actual replay and installed CLI boundary."""

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sysconfig

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


@pytest.mark.parametrize("side", ["strategy", "benchmark"])
@pytest.mark.parametrize("case", ["cash", "overflow", "ledger", "ledger_scale"])
def test_saved_risk_diagnostics_partial_failures_remain_local_and_cli_succeeds(intraday_experiment, side, case, tmp_path, monkeypatch, capsys):
    from market_vault.research.intraday_risk_diagnostics import analyze_intraday_risk_diagnostics
    root = intraday_experiment.as_dict()
    group = root["report"]["groups"][0]
    execution = (group["results"][1] if side == "strategy" else group["benchmark"])["execution"]
    if case == "cash":
        execution["trades"][0]["commission_total"] += .01
    elif case == "overflow":
        execution["trades"][0]["quantity"] = 1e308
        execution["trades"][0]["exit_raw_open"] = 1e308
    elif case == "ledger":
        execution["ledger"][0]["cash"] += .01
    else:
        for point in execution["ledger"]:
            for key in ("cash", "quantity", "equity"):
                point[key] *= 2
    snapshot = StrategyExperiment(signed(root))  # Accepted immutable grammar, beyond checksum-only rejection.
    path = tmp_path / "saved-risk.json"
    write_strategy_experiment(snapshot, path=path)
    before = path.read_bytes()
    monkeypatch.setattr(research, "load_intraday_dataset", lambda *a, **kw: pytest.fail("risk diagnostics read Q5"))
    monkeypatch.setattr(research, "_fit", lambda *a, **kw: pytest.fail("risk diagnostics fitted"))
    monkeypatch.setattr(research, "run_intraday_execution", lambda *a, **kw: pytest.fail("risk diagnostics executed"))
    result = analyze_intraday_risk_diagnostics(snapshot, candidate_index=1)
    failed = result[side + "_diagnostics"]
    available = result[("benchmark" if side == "strategy" else "strategy") + "_diagnostics"]
    assert failed["status"] == "UNAVAILABLE" and failed["report"] is None
    expected = ("NUMERIC_OVERFLOW" if case == "overflow" else "RECORDED_LEDGER_RECONCILIATION_FAILED"
                if case in ("ledger", "ledger_scale") else "RECORDED_CASH_RECONCILIATION_FAILED")
    assert failed["unavailable_reason"] == expected
    assert available["status"] == "AVAILABLE" and available["report"]["fold_diagnostics"]["status"] == "AVAILABLE"
    assert result["experiment_id"] == snapshot.experiment_id
    assert result["candidate_id"] == snapshot.as_dict()["report"]["groups"][0]["results"][1]["candidate_id"]
    assert cli.main(["research-intraday-risk-diagnostics", "--experiment", str(path), "--candidate-index", "1"]) == 0
    assert json.loads(capsys.readouterr().out)["report"] == result
    assert path.read_bytes() == snapshot.content == before


def test_saved_risk_diagnostics_historical_execution_is_descriptive_unavailable(intraday_experiment):
    from market_vault.research.intraday_risk_diagnostics import analyze_intraday_risk_diagnostics
    root = intraday_experiment.as_dict()
    root["algorithm_versions"]["execution"] = "recorded-historical-execution"
    for group in root["report"]["groups"]:
        for record in [*group["results"], group["benchmark"]]:
            record["execution"]["version"] = root["algorithm_versions"]["execution"]
    snapshot = StrategyExperiment(signed(root))
    result = analyze_intraday_risk_diagnostics(snapshot, candidate_index=1)
    assert result["status"] == "SUCCESS" and result["experiment_id"] == snapshot.experiment_id
    for key in ("strategy_diagnostics", "benchmark_diagnostics"):
        assert result[key]["status"] == "UNAVAILABLE"
        assert result[key]["unavailable_reason"] == "UNSUPPORTED_EXECUTION_OR_COST_VERSION"
        assert result[key]["report"] is None


def signed_scenarios(root):
    for row in root["report"]["scenarios"]:
        row["experiment"] = json.loads(signed(row["experiment"]))
    root["report"]["scenarios_id"] = digest({k: v for k, v in root["report"].items() if k != "scenarios_id"})
    root["experiment_id"] = digest({k: v for k, v in root.items() if k != "experiment_id"})
    return canonical_json(root)


def test_scenarios_offline_cli_export_guards_and_nonfirst_child_final_test(execution_scenarios_case, tmp_path, monkeypatch, capsys):
    from market_vault.research.intraday_execution_scenarios import extract_intraday_execution_scenario
    from market_vault.research.intraday_final_test import freeze_intraday_candidate, run_intraday_final_test
    from market_vault.research.intraday_risk_diagnostics import analyze_intraday_risk_diagnostics
    from market_vault.research.intraday_parameter_grid import analyze_intraday_parameter_grid
    _, _, collection, _ = execution_scenarios_case
    path, output = tmp_path / "collection.json", tmp_path / "delayed.json"
    write_strategy_experiment(collection, path=path)
    child = collection.as_dict()["report"]["scenarios"][1]["experiment"]
    with pytest.raises(ValueError, match="export an ordinary Q7"):
        analyze_intraday_risk_diagnostics(collection)
    with pytest.raises(ValueError, match="INTRADAY_DIAGNOSTICS"):
        analyze_intraday_parameter_grid(collection)
    with pytest.raises(ValueError, match="INTRADAY_DIAGNOSTICS"):
        analyze_intraday_parameter_grid(StrategyExperiment(canonical_json(child)))
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


@pytest.mark.parametrize("case", ["swapped_child", "shared_predictions", "missing_child", "recursive_child", "bool_index",
                                 "cross_scenario_price", "within_scenario_price", "cross_scenario_row", "cross_scenario_clock"])
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
    elif case in ("cross_scenario_price", "within_scenario_price", "cross_scenario_row", "cross_scenario_clock"):
        group = scenarios[1]["experiment"]["report"]["groups"][0]
        records = group["results"][:1] if case == "within_scenario_price" else [*group["results"], group["benchmark"]]
        for record in records:
            row = record["execution"]["ledger"][0]
            if case.endswith("price"):
                row["mark_price"] += 0.01
            elif case.endswith("row"):
                row["row_version_id"] = "0" * 64
            else:
                from datetime import datetime, timedelta
                row["timestamp"] = (datetime.fromisoformat(row["timestamp"]) + timedelta(seconds=1)).isoformat()
        # Ordinary Q7 grammar accepts these re-signed records. The new
        # collection must independently bind the actual shared raw evidence.
        StrategyExperiment(signed(scenarios[1]["experiment"]))
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


def _compare_saved(*args, **kwargs):
    from market_vault.research.intraday_saved_comparison import compare_saved_intraday_experiments
    return compare_saved_intraday_experiments(*args, **kwargs)


def _saved_metrics(report, section="strategy_metrics"):
    return {row["metric"]: row for row in report[section]}


def _comparison_snapshot(root):
    """Bind intentional recorded changes without inventing replay evidence."""
    context = root["report"]["context"]
    for fold in context["folds"]:
        fold["fold_id"] = digest({key: value for key, value in fold.items() if key != "fold_id"})
    for group in root["report"]["groups"]:
        for candidate in group["results"]:
            for record, fold in zip(candidate["fold_models"], context["folds"]):
                model = record["model"]
                model["training_keys"] = list(fold["training_keys"])
                model["training_boundary"] = fold["training_boundary"]
                model["version"] = root["algorithm_versions"]["ridge"]
                model["model_id"] = digest({key: value for key, value in model.items() if key != "model_id"})
                record["fold_id"] = fold["fold_id"]
            candidate["fold_contributions"] = research.fold_cash_contributions(context, candidate["execution"])
    root["report"]["plan_sha256"] = digest(root["plan"])
    return StrategyExperiment(signed(root))


@pytest.fixture(scope="session")
def saved_comparison_feature_pair(research_case):
    """Two real rule reports reuse verified Q5; no extra source load or fit."""
    data, original, _ = research_case
    comparison = deepcopy(original)
    comparison["feature_fields"] = ["sma_5", "return_2"]
    comparison["strategies"] = [deepcopy(original["strategies"][0]),
        {**original["strategies"][0], "name": "Long", "threshold": 0}]
    reordered = deepcopy(comparison)
    reordered["feature_fields"].reverse()
    diagnostic = {"plan_schema_version": research.INTRADAY_DIAGNOSTICS_PLAN_VERSION,
        "comparison_plan": reordered, "strategy_name": "Long",
        "parameter_axes": [{"parameter": "threshold", "values": [1000000, 0]}],
        "cost_scenarios": [{"commission_bps": 0, "slippage_bps": 0}, {"commission_bps": 10, "slippage_bps": 5}]}
    snapshots = []
    for plan in (comparison, diagnostic):
        normalized, children, axes = research.expand_intraday_plan(plan, recorded=True)
        prepared = research._prepare_intraday_research(children[0], data=data)
        report = research._evaluate_intraday_research(normalized, children, axes, prepared)
        snapshots.append(create_intraday_experiment(plan=normalized, report=report))
    return tuple(snapshots)


@pytest.fixture(scope="session")
def parameter_grid_experiment(research_case):
    """One real Composite grid reuses verified Q5; no extra source load or fit."""
    data, comparison, _ = research_case
    plan = {"plan_schema_version": research.INTRADAY_DIAGNOSTICS_PLAN_VERSION,
        "comparison_plan": deepcopy(comparison), "strategy_name": "Long",
        "parameter_axes": [{"parameter": "condition_threshold", "condition_index": 0, "values": [125, 0, 130.000000000001]},
                           {"parameter": "condition_threshold", "condition_index": 1, "values": [1000000, 126]}],
        "cost_scenarios": [{"commission_bps": 0, "slippage_bps": 0}, {"commission_bps": 10, "slippage_bps": 5}]}
    normalized, children, coordinates = research.expand_intraday_plan(plan, recorded=True)
    prepared = research._prepare_intraday_research(children[0], data=data)
    report = research._evaluate_intraday_research(normalized, children, coordinates, prepared)
    return create_intraday_experiment(plan=normalized, report=report, name="Explicit Composite grid")


def _plan_reuse_forms(locator):
    """Complete grammar examples need no data, result or fitted fixture."""
    from market_vault.research.intraday_execution_scenarios import INTRADAY_EXECUTION_SCENARIOS_PLAN_VERSION
    comparison = {"plan_schema_version": research.INTRADAY_RESEARCH_PLAN_VERSION,
        "intraday_data_path": locator, "data_id": "a" * 64, "feature_fields": ["return_2", "sma_5"],
        "split": {"train_end_day": "2025-02-01", "validation_end_day": "2025-03-01", "test_end_day": "2025-04-01"},
        "walk_forward": {"minimum_train_days": 20, "validation_days": 5, "step_days": 5},
        "strategies": [{"kind": "COMPOSITE_RULE", "name": "条件", "match": "ALL", "conditions": [
            {"signal_field": "return_2", "comparator": "GT", "threshold": .000000000001},
            {"signal_field": "sma_5", "comparator": "LT", "threshold": 130.000000000001}]},
            {"kind": "RIDGE", "name": "Ridge", "alpha": 1000, "threshold": .00025}],
        "execution": {"commission_bps": 7, "slippage_bps": 3, "entry_delay_minutes": 60,
                      "stop_new_minutes": 45, "flatten_minutes": 10, "max_hold_bars": 3}}
    return {"comparison": comparison,
        "diagnostics": {"plan_schema_version": research.INTRADAY_DIAGNOSTICS_PLAN_VERSION,
            "comparison_plan": deepcopy(comparison), "strategy_name": "条件",
            "parameter_axes": [{"parameter": "condition_threshold", "condition_index": 1, "values": [130.000000000001, 0]}],
            "cost_scenarios": [{"commission_bps": 10, "slippage_bps": 5}, {"commission_bps": 0, "slippage_bps": 0}]},
        "scenarios": {"plan_schema_version": INTRADAY_EXECUTION_SCENARIOS_PLAN_VERSION,
            "comparison_plan": deepcopy(comparison), "execution_scenarios": [
                {"name": "Second named first", "execution": {**comparison["execution"], "commission_bps": 10}},
                {"name": "First named second", "execution": {**comparison["execution"], "commission_bps": 0}}]}}
