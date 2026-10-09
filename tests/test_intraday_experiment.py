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


def test_saved_comparison_q10_children_allow_policy_changes_and_keep_metric_units(execution_scenarios_case):
    from market_vault.research.intraday_execution_scenarios import extract_intraday_execution_scenario
    collection = execution_scenarios_case[2]
    original = collection.content
    children = [extract_intraday_execution_scenario(collection,
        expected_experiment_id=collection.experiment_id, scenario_index=index,
        expected_child_experiment_id=row["experiment"]["experiment_id"])
        for index, row in enumerate(collection.as_dict()["report"]["scenarios"])]
    before = [child.content for child in children]
    result = _compare_saved(*children, left_candidate_index=2, right_candidate_index=2)
    assert result["status"] == "SUCCESS" and result["basis_matches"] and result["delta_allowed"]
    assert result["delta_reasons"] == [] and all(row["matches"] for row in result["basis_checks"])
    for side, child in zip(("left", "right"), children, strict=True):
        root = child.as_dict()
        candidate = root["report"]["groups"][0]["results"][2]
        assert result[side]["experiment_id"] == child.experiment_id
        assert result[side]["candidate_id"] == candidate["candidate_id"]
        assert result[side]["execution_policy"] == root["plan"]["execution"]
    assert result["left"]["execution_policy"] != result["right"]["execution_policy"]
    rows = _saved_metrics(result)
    for key in ("total_return", "observed_max_drawdown", "annualized_volatility", "mae", "rmse", "exposure_ratio"):
        row = rows[key]
        assert row["left"]["unit"] == row["right"]["unit"] == "RATIO"
        assert row["delta"]["unit"] == "PERCENTAGE_POINTS"
        assert row["delta"]["value"] == pytest.approx((row["right"]["value"] - row["left"]["value"]) * 100)
    for key in ("sharpe_ratio", "r2", "profit_factor", "payoff_ratio"):
        row = rows[key]
        assert row["left"]["unit"] == row["right"]["unit"] == row["delta"]["unit"] == "NUMBER"
        if row["left"]["value"] is not None and row["right"]["value"] is not None:
            assert row["delta"]["value"] == pytest.approx(row["right"]["value"] - row["left"]["value"])
    for key in ("net_cash_pnl", "commission_total", "slippage_total"):
        row = rows[key]
        assert row["left"]["unit"] == row["delta"]["unit"] == "INITIAL_CASH_UNITS"
        assert row["delta"]["value"] == pytest.approx(row["right"]["value"] - row["left"]["value"])
    benchmark = _saved_metrics(result, "benchmark_metrics")["total_return"]
    assert benchmark["delta"]["value"] == pytest.approx((benchmark["right"]["value"] - benchmark["left"]["value"]) * 100)
    assert collection.content == original and [child.content for child in children] == before
    with pytest.raises(ValueError):
        _compare_saved(collection, children[0])


def test_saved_comparison_cli_is_offline_and_preserves_nonfirst_cost_candidate_and_feature_order(
        saved_comparison_feature_pair, intraday_experiment, tmp_path, monkeypatch, capsys):
    from market_vault.research import intraday_final_test as final
    left, right = saved_comparison_feature_pair
    paths = [tmp_path / "a.json", tmp_path / "b.json"]
    for snapshot, path in zip((left, right), paths, strict=True):
        write_strategy_experiment(snapshot, path=path)
    before = [path.read_bytes() for path in paths]
    blocked = lambda *a, **kw: pytest.fail("saved comparison read Q5/source, loaded settings, or fitted")
    monkeypatch.setattr(research, "load_intraday_dataset", blocked)
    monkeypatch.setattr(final, "load_intraday_dataset", blocked)
    monkeypatch.setattr(final, "load_strategy_experiment", blocked)
    monkeypatch.setattr(research, "_fit", blocked)
    monkeypatch.setattr(cli, "load_settings", blocked)
    args = ["--settings", str(tmp_path / "missing-settings.yaml"), "research-intraday-compare-saved",
        "--left", str(paths[0]), "--right", str(paths[1]), "--left-candidate-index", "1",
        "--right-cost-index", "1", "--right-candidate-index", "1"]
    assert cli.main(args) == 0
    captured = capsys.readouterr()
    assert not captured.err
    result = json.loads(captured.out)["report"]
    assert result["basis_matches"] and result["delta_allowed"]
    assert result["left"]["feature_fields"] == ["sma_5", "return_2"]
    assert result["right"]["feature_fields"] == ["return_2", "sma_5"]
    assert result["right"]["evaluation_mode"] == "INTRADAY_DIAGNOSTICS"
    expected = right.as_dict()["report"]["groups"][1]["results"][1]
    assert result["right"]["candidate_id"] == expected["candidate_id"]
    assert result["right"]["cost_index"] == result["right"]["candidate_index"] == 1
    assert result["right"]["strategy"] == expected["strategy"]
    assert result["right"]["execution_policy"]["commission_bps"] == 10
    assert result["configuration_differences"]
    projected = _compare_saved(intraday_experiment, left)
    assert projected["delta_allowed"]
    assert projected["left"]["feature_fields"] == ["sma_5"]
    assert projected["right"]["feature_fields"] == ["sma_5", "return_2"]
    for flag, bad in (("--right-candidate-index", "1000"), ("--right-cost-index", "-1"), ("--left", str(tmp_path / "missing.json"))):
        invalid = args[:]
        invalid[invalid.index(flag) + 1] = bad
        assert cli.main(invalid) == 1
        failed = capsys.readouterr()
        assert not failed.out and json.loads(failed.err)["status"] == "FAILED"
    invalid = args[:]
    invalid[invalid.index("--right-cost-index") + 1] = "True"
    with pytest.raises(SystemExit) as syntax:
        cli.main(invalid)
    assert syntax.value.code == 2
    failed = capsys.readouterr()
    assert not failed.out and "usage:" in failed.err
    for field, value in (("left_cost_index", True), ("right_candidate_index", True), ("right_cost_index", 1.0)):
        with pytest.raises(ValueError):
            _compare_saved(left, right, **{field: value})
    assert [path.read_bytes() for path in paths] == before


def test_saved_comparison_metadata_and_unselected_algorithm_versions_do_not_disable_delta(intraday_experiment):
    root = intraday_experiment.as_dict()
    root["name"], root["notes"] = "Renamed saved result", "Same selected Feature rule"
    root["environment"]["python"] = "different recorded environment"
    root["plan"]["intraday_data_path"] = r"C:\archive\same-data.json"
    root["algorithm_versions"]["ridge"] = "historical-unselected-ridge"
    root["algorithm_versions"]["composite"] = "historical-unselected-composite"
    changed = _comparison_snapshot(root)
    result = _compare_saved(intraday_experiment, changed)
    assert result["basis_matches"] and result["delta_allowed"]
    assert result["left"]["experiment_id"] != result["right"]["experiment_id"]
    assert result["right"]["name"] == root["name"]
    assert result["right"]["algorithm_versions"]["ridge"] == "historical-unselected-ridge"


def test_saved_comparison_selected_alpha_threshold_and_model_identity_are_configuration(intraday_experiment):
    # This is a recorded comparison, not a claim that the changed model was
    # fitted. Its valid changed IDs must not replace evaluation-basis checks.
    root = intraday_experiment.as_dict()
    spec = root["plan"]["strategies"][2]
    spec["alpha"], spec["threshold"] = 2.0, .00025
    candidate = root["report"]["groups"][0]["results"][2]
    candidate["strategy"] = deepcopy(spec)
    for record in candidate["fold_models"]:
        record["model"]["alpha"] = spec["alpha"]
    for rows in (candidate["predictions"], candidate["execution"]["decisions"]):
        for row in rows:
            row["target"] = "LONG" if row["score"] > spec["threshold"] else "FLAT"
    changed = _comparison_snapshot(root)
    result = _compare_saved(intraday_experiment, changed, left_candidate_index=2, right_candidate_index=2)
    assert result["basis_matches"] and result["delta_allowed"]
    assert result["left"]["candidate_id"] != result["right"]["candidate_id"]
    assert result["left"]["strategy"]["alpha"] == 1 and result["right"]["strategy"]["alpha"] == 2
    assert result["right"]["strategy"]["threshold"] == .00025


@pytest.mark.parametrize("case", ["training_order", "purged_order", "fold_validation_ownership", "decision_identity",
    "raw_price", "raw_row", "raw_clock", "self_contradictory_price", "split_boundary", "target_horizon",
    "research_version", "risk_definition"])
def test_saved_comparison_checks_complete_basis_even_for_internally_contradictory_self_comparison(intraday_experiment, case):
    left = intraday_experiment
    root = left.as_dict()
    context = root["report"]["context"]
    if case == "training_order":
        context["folds"][0]["training_keys"][:2] = context["folds"][0]["training_keys"][:2][::-1]
    elif case == "purged_order":
        fold = context["folds"][0]
        fold["purged_keys"] = fold["training_keys"][:2]
        del fold["training_keys"][:2]
        left = _comparison_snapshot(root)
        root = left.as_dict()
        root["report"]["context"]["folds"][0]["purged_keys"].reverse()
    elif case == "fold_validation_ownership":
        # Overall decisions, counts, dates and joined validation keys stay
        # identical; only the actual fold ownership changes.
        folds = context["folds"]
        folds[1]["validation_keys"].insert(0, folds[0]["validation_keys"].pop())
    elif case == "decision_identity":
        from datetime import datetime, timedelta
        for group in root["report"]["groups"]:
            for candidate in group["results"]:
                for rows in (candidate["predictions"], candidate["execution"]["decisions"]):
                    rows[0]["slot"] -= 1
                    rows[0]["decision_time"] = (datetime.fromisoformat(rows[0]["decision_time"]) - timedelta(minutes=5)).isoformat()
    elif case.startswith("raw_") or case == "self_contradictory_price":
        from datetime import datetime, timedelta
        group = root["report"]["groups"][0]
        records = group["results"][2:3] if case == "self_contradictory_price" else [*group["results"], group["benchmark"]]
        for record in records:
            row = record["execution"]["ledger"][0]
            if case in ("raw_price", "self_contradictory_price"):
                row["mark_price"] += .01
            elif case == "raw_row":
                row["row_version_id"] = "0" * 64
            else:
                row["timestamp"] = (datetime.fromisoformat(row["timestamp"]) + timedelta(seconds=1)).isoformat()
    elif case == "split_boundary":
        context["split"]["VALIDATION"].insert(0, context["split"]["TRAIN"].pop())
        root["plan"]["split"]["train_end_day"] = context["split"]["TRAIN"][-1]
    elif case == "target_horizon":
        context["target_horizon_bars"] += 1
    elif case == "research_version":
        root["algorithm_versions"]["research"] = root["report"]["version"] = "historical-research"
    else:
        for group in root["report"]["groups"]:
            for record in (*group["results"], group["benchmark"]):
                record["risk"]["zero_volatility_tolerance"] *= 2
    right = _comparison_snapshot(root)  # Each counterexample passes actual Q7 grammar.
    if case == "self_contradictory_price":
        left = right
    result = _compare_saved(left, right, left_candidate_index=2, right_candidate_index=2)
    assert result["status"] == "SUCCESS" and not result["basis_matches"] and not result["delta_allowed"]
    assert any(not row["matches"] for row in result["basis_checks"])
    assert result["left"]["experiment_id"] == left.experiment_id
    assert result["right"]["experiment_id"] == right.experiment_id
    assert _saved_metrics(result)["final_cash"]["right"]["value"] is not None
    for section in ("strategy_metrics", "benchmark_metrics"):
        assert all(row["delta"]["value"] is None and row["delta"]["unavailable_reason"] == "BASIS_MISMATCH"
                   for row in result[section])


@pytest.mark.parametrize("case", ["historical_execution_cost", "candidate_reconciliation", "benchmark_reconciliation"])
def test_saved_comparison_retains_raw_metrics_when_one_derived_portion_is_unavailable(intraday_experiment, case):
    root = intraday_experiment.as_dict()
    if case == "historical_execution_cost":
        root["algorithm_versions"]["execution"] = "historical-execution"
        root["algorithm_versions"]["cost"] = "historical-cost"
        for group in root["report"]["groups"]:
            for record in (*group["results"], group["benchmark"]):
                record["execution"]["version"] = root["algorithm_versions"]["execution"]
                record["execution"]["cost_version"] = root["algorithm_versions"]["cost"]
    else:
        group = root["report"]["groups"][0]
        record = group["results"][1] if case == "candidate_reconciliation" else group["benchmark"]
        record["execution"]["trades"][0]["commission_total"] += .01
    changed = _comparison_snapshot(root)
    result = _compare_saved(intraday_experiment, changed, left_candidate_index=1, right_candidate_index=1)
    assert result["status"] == "SUCCESS"
    for portion in ("candidate_performance", "benchmark_performance"):
        assert result["left"][portion]["status"] == "AVAILABLE"
        bad = case == "historical_execution_cost" or case.startswith(portion.split("_")[0])
        state = result["right"][portion]
        assert state["status"] == ("UNAVAILABLE" if bad else "AVAILABLE")
        assert (state["report"] is None) == bad
        assert bool(state["unavailable_reason"]) == bad
        assert bool(state["detail"]) == bad
    for section, record in (("strategy_metrics", root["report"]["groups"][0]["results"][1]),
                            ("benchmark_metrics", root["report"]["groups"][0]["benchmark"])):
        rows = _saved_metrics(result, section)
        assert rows["total_return"]["right"]["value"] == record["execution"]["metrics"]["total_return"]
        assert rows["total_return"]["right"]["evidence"] == "RECORDED"
        assert rows["sharpe_ratio"]["right"]["value"] == record["risk"]["sharpe_ratio"]
        affected = case == "historical_execution_cost" or (case == "candidate_reconciliation") == (section == "strategy_metrics")
        if affected:
            assert rows["win_rate"]["right"]["value"] is None
            assert rows["win_rate"]["right"]["unavailable_reason"]
            assert rows["win_rate"]["delta"]["value"] is None
        else:
            assert rows["win_rate"]["right"]["value"] is not None


def test_saved_comparison_preserves_zero_volatility_and_each_null_reason(intraday_experiment):
    root = intraday_experiment.as_dict()
    errors = root["report"]["groups"][0]["results"][2]["prediction_metrics"]
    errors["r2"], errors["unavailable_reason"] = None, None
    changed = _comparison_snapshot(root)
    result = _compare_saved(intraday_experiment, changed, left_candidate_index=0, right_candidate_index=2)
    assert result["delta_allowed"]
    rows = _saved_metrics(result)
    assert rows["annualized_volatility"]["left"]["value"] == 0
    assert rows["annualized_volatility"]["left"]["unavailable_reason"] is None
    assert rows["annualized_volatility"]["delta"]["value"] is not None
    assert rows["sharpe_ratio"]["left"]["value"] is None
    assert rows["sharpe_ratio"]["left"]["unavailable_reason"] == "ZERO_VOLATILITY"
    assert rows["sharpe_ratio"]["delta"]["unavailable_reason"] == "LEFT_UNAVAILABLE"
    assert rows["win_rate"]["left"]["unavailable_reason"] == "NO_TRADES"
    assert rows["profit_factor"]["left"]["unavailable_reason"] == "NO_LOSING_TRADES"
    assert rows["r2"]["left"]["unavailable_reason"] == "NOT_APPLICABLE"
    assert rows["r2"]["right"]["unavailable_reason"] == "UNAVAILABLE_STATISTIC"
    assert rows["r2"]["delta"]["value"] is None
    assert rows["r2"]["delta"]["unavailable_reason"] == "BOTH_UNAVAILABLE"
    assert "NaN" not in json.dumps(result, allow_nan=False)


def test_saved_comparison_overflow_keeps_finite_recorded_values_and_unavailable_delta(intraday_experiment):
    values = []
    for value in (-1e308, 1e308):
        root = intraday_experiment.as_dict()
        root["report"]["groups"][0]["results"][1]["risk"]["sharpe_ratio"] = value
        values.append(_comparison_snapshot(root))
    result = _compare_saved(*values, left_candidate_index=1, right_candidate_index=1)
    assert result["delta_allowed"]
    row = _saved_metrics(result)["sharpe_ratio"]
    assert row["left"]["value"] == -1e308 and row["right"]["value"] == 1e308
    assert row["delta"]["value"] is None and row["delta"]["unit"] == "NUMBER"
    assert row["delta"]["unavailable_reason"] == "NUMERIC_OVERFLOW"
    assert row["delta"]["evidence"] == "RECORDED_DIFFERENCE"
    json.dumps(result, allow_nan=False)
