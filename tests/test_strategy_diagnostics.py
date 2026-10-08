"""Finite diagnostics, continuous-account attribution and whole-bundle replay.

The verified fixture retains the existing MemoryFS Research publication
boundary; it exercises real research/risk computation, not native publication.
"""

from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
import json
import math
from types import SimpleNamespace

import pytest

from market_vault import cli, cross_day_dataset
from market_vault.backtest import BacktestCosts, BacktestRule
from market_vault.backtest.engine import _Candidate, _run_candidates
from market_vault.research import strategy_diagnostics as diagnostics
from market_vault.research import strategy_experiment as artifacts
from market_vault.research.strategy_comparison import FeatureRuleStrategy, compare_strategies
from market_vault.strategy_comparison_io import (
    _success_payload, canonical_json, evaluate_comparison_payload,
    normalized_comparison_plan, parse_strategy_comparison_plan_bytes,
)
from test_strategy_comparison import _bind_bundle, _config, verified_workspace_dataset  # noqa: F401
from test_strategy_configuration import _verified_composite_config
from test_ridge_final_trading import _execution_bundle, _time


def _diagnostic_plan(path):
    return {
        "plan_schema_version": diagnostics.STRATEGY_DIAGNOSTICS_PLAN_VERSION,
        "comparison_plan": normalized_comparison_plan(_verified_composite_config(), dataset_build_dir=str(path)),
        "strategy_name": "ridge",
        "parameter_axes": [
            {"parameter": "alpha", "values": [0.1, 1.0]},
            {"parameter": "threshold", "values": [-1_000_000.0, 0.0, 1_000_000.0]},
        ],
        "cost_scenarios": [
            {"commission_bps": 0.0, "slippage_bps": 0.0},
            {"commission_bps": 10.0, "slippage_bps": 5.0},
        ],
    }


@pytest.fixture(scope="module")
def diagnostic_case(verified_workspace_dataset):
    dataset = verified_workspace_dataset
    plan = _diagnostic_plan(dataset.build_path)
    report = diagnostics.run_strategy_diagnostics(dataset, plan=plan)
    snapshot = artifacts.create_strategy_diagnostics_experiment(plan=plan, report=report, name="Ridge neighborhood")
    return dataset, plan, report, snapshot


def _resign(root):
    root["report"]["diagnostics_id"] = diagnostics.diagnostics_report_identity(root["report"])
    root["experiment_id"] = sha256(canonical_json(
        {key: value for key, value in root.items() if key != "experiment_id"},
    )).hexdigest()
    return canonical_json(root)


def test_all_twelve_candidates_equal_direct_public_risk_results(diagnostic_case):
    dataset, plan, report, snapshot = diagnostic_case
    assert report["evaluation_count"] == 12 and report["variant_count"] == 6
    assert len(report["groups"]) == 2
    assert "winner" not in report and "best" not in report
    assert snapshot.as_dict()["artifact_schema_version"] == artifacts.STRATEGY_EXPERIMENT_V2_VERSION
    # The unused composite in the source list must not promote selected Ridge to V2.
    assert "composite_rule" not in snapshot.as_dict()["algorithm_versions"]
    for cost_index, group in enumerate(report["groups"]):
        assert group["cost_index"] == cost_index
        assert group["report"]["result_schema_version"] == "market-vault-strategy-risk-cli-result-v1"
        config = parse_strategy_comparison_plan_bytes(canonical_json(group["comparison_plan"]))
        config.pop("dataset_build_dir")
        for index, variant in enumerate(config["strategies"]):
            direct = evaluate_comparison_payload(dataset, {**config, "strategies": (variant,)}, "RISK")
            assert group["report"]["results"][index] == direct["results"][0]
            assert group["report"]["equity"]["results"][index] == direct["equity"]["results"][0]
            assert group["report"]["risk"]["results"][index] == direct["risk"]["results"][0]
            assert group["report"]["risk"]["benchmark"] == direct["risk"]["benchmark"]
            candidate = group["candidates"][index]
            assert candidate["variant_index"] == index
            assert candidate["axis_values"] == [plan["parameter_axes"][0]["values"][index // 3],
                                                 plan["parameter_axes"][1]["values"][index % 3]]
            assert candidate["strategy_result_id"] == direct["results"][0]["result_id"]
            assert math.fsum(fold["cash_contribution"] for fold in candidate["fold_contributions"]) == pytest.approx(
                direct["results"][0]["metrics"]["total_return"],
            )
    assert any(result["trades"] for group in report["groups"] for result in group["report"]["results"])
    assert all(not group["report"]["results"][2]["trades"] for group in report["groups"])


def test_orchestration_calls_once_per_cost_and_never_changes_inputs(diagnostic_case, monkeypatch):
    dataset, plan, expected, _ = diagnostic_case
    before, calls = canonical_json(plan), []
    groups = expected["groups"]

    def evaluate(actual, config, mode):
        assert actual is dataset and mode == "RISK" and len(config["strategies"]) == 6
        calls.append((config["commission_bps"], config["slippage_bps"]))
        assert calls[-1] == tuple(plan["cost_scenarios"][len(calls) - 1].values())
        return groups[len(calls) - 1]["report"]

    monkeypatch.setattr(diagnostics, "evaluate_comparison_payload", evaluate)
    assert diagnostics.run_strategy_diagnostics(dataset, plan=plan) == expected
    assert len(calls) == 2 and canonical_json(plan) == before


@pytest.mark.parametrize("case", [
    "axis_count", "boolean", "nan", "infinity", "zero_duplicate", "alpha_zero",
    "unknown_parameter", "duplicate_target", "condition_bounds", "condition_boolean",
    "wrong_strategy_kind", "unknown_strategy", "unknown_field", "empty_values",
    "empty_costs", "duplicate_costs", "negative_cost", "side_cost_limit",
    "axis_65", "combined_72", "costs_65", "outside_projection",
])
def test_invalid_finite_grid_is_rejected_before_evaluation(tmp_path, monkeypatch, case):
    plan = _diagnostic_plan(tmp_path / "absent")
    axes = plan["parameter_axes"]
    if case == "axis_count":
        axes.append(axes[0].copy())
    elif case in ("boolean", "nan", "infinity", "alpha_zero"):
        axes[0]["values"][0] = {"boolean": True, "nan": float("nan"), "infinity": float("inf"), "alpha_zero": 0}[case]
    elif case == "zero_duplicate":
        axes[1]["values"] = [-0.0, 0.0]
    elif case == "unknown_parameter":
        axes[0]["parameter"] = "import_path"
    elif case == "duplicate_target":
        axes[1] = axes[0].copy()
    elif case in ("condition_bounds", "condition_boolean"):
        plan["strategy_name"] = plan["comparison_plan"]["strategies"][-1]["name"]
        plan["parameter_axes"] = [{"parameter": "condition_threshold",
                                   "condition_index": 999 if case == "condition_bounds" else True,
                                   "values": [0]}]
    elif case == "wrong_strategy_kind":
        plan["strategy_name"] = "trend"
    elif case == "unknown_strategy":
        plan["strategy_name"] = "absent"
    elif case == "unknown_field":
        axes[0]["expression"] = "arbitrary"
    elif case == "empty_values":
        axes[0]["values"] = []
    elif case == "empty_costs":
        plan["cost_scenarios"] = []
    elif case == "duplicate_costs":
        plan["cost_scenarios"][1] = {"commission_bps": -0.0, "slippage_bps": 0}
    elif case == "negative_cost":
        plan["cost_scenarios"][0]["slippage_bps"] = -1
    elif case == "side_cost_limit":
        plan["cost_scenarios"][0] = {"commission_bps": 9_999, "slippage_bps": 1}
    elif case == "axis_65":
        axes[1]["values"] = list(range(65))
    elif case == "combined_72":
        axes[0]["values"] = list(range(1, 9))
        axes[1]["values"] = list(range(9))
        plan["cost_scenarios"] = plan["cost_scenarios"][:1]
    elif case == "costs_65":
        plan["parameter_axes"] = []
        plan["cost_scenarios"] = [{"commission_bps": value, "slippage_bps": 0} for value in range(65)]
    else:
        plan["strategy_name"] = "trend"
        plan["parameter_axes"] = []
        plan["comparison_plan"]["strategies"][0]["signal_field"] = plan["comparison_plan"]["return_label"]
    monkeypatch.setattr(diagnostics, "evaluate_comparison_payload", lambda *a, **k: pytest.fail("invalid grid evaluated"))
    with pytest.raises(ValueError):
        diagnostics.run_strategy_diagnostics(object(), plan=plan)


def test_zero_axes_exact_limit_composite_targets_and_distinct_cost_pairs(tmp_path):
    plan = _diagnostic_plan(tmp_path)
    plan["parameter_axes"] = []
    normalized, children, values = diagnostics.expand_strategy_diagnostics_plan(plan)
    assert values == ((),) and len(children) == 2
    assert children[0]["strategies"] == [{"kind": "RIDGE", "name": "ridge [1]", "alpha": 1.0, "threshold": 0.0}]
    plan["parameter_axes"] = [{"parameter": "alpha", "values": list(range(1, 33))}]
    _, children, values = diagnostics.expand_strategy_diagnostics_plan(plan)
    assert len(children) * len(values) == 64
    composite = plan["comparison_plan"]["strategies"][-1]
    plan["strategy_name"] = composite["name"]
    plan["parameter_axes"] = [
        {"parameter": "condition_threshold", "condition_index": 0, "values": [-1, 1]},
        {"parameter": "condition_threshold", "condition_index": 1, "values": [2, 3]},
    ]
    plan["cost_scenarios"] = [{"commission_bps": 5, "slippage_bps": 2},
                               {"commission_bps": 2, "slippage_bps": 5}]
    before = canonical_json(plan)
    _, children, values = diagnostics.expand_strategy_diagnostics_plan(plan)
    assert values == ((-1.0, 2.0), (-1.0, 3.0), (1.0, 2.0), (1.0, 3.0))
    assert len(children) == 2 and canonical_json(plan) == before
    assert children[0]["plan_schema_version"] == "market-vault-strategy-comparison-plan-v2"
    for index, strategy in enumerate(children[0]["strategies"]):
        assert strategy["match"] == composite["match"]
        assert [rule["threshold"] for rule in strategy["conditions"]] == list(values[index])
        assert [rule["signal_field"] for rule in strategy["conditions"]] == [
            rule["signal_field"] for rule in composite["conditions"]
        ]


@pytest.mark.parametrize("kind", ["FEATURE_RULE", "COMPOSITE_RULE"])
def test_rule_grids_execute_comparators_and_composite_any_with_full_replay(
    verified_workspace_dataset, kind,
):
    plan = _diagnostic_plan(verified_workspace_dataset.build_path)
    specs = plan["comparison_plan"]["strategies"]
    selected = next(item for item in specs if item["kind"] == kind
                    and (kind == "COMPOSITE_RULE" or item["comparator"] == "LT"))
    plan["strategy_name"] = selected["name"]
    if kind == "FEATURE_RULE":
        plan["parameter_axes"] = [{"parameter": "threshold", "values": [-1e6, 1e6]}]
        expected_trades = [False, True]
    else:
        selected["match"] = "ANY"
        selected["conditions"][1]["comparator"] = "LE"
        plan["parameter_axes"] = [
            {"parameter": "condition_threshold", "condition_index": index, "values": [-1e6, 1e6]}
            for index in range(2)
        ]
        expected_trades = [True, True, False, True]
    # Both explicit pairs survive even though the current kernel uses their sum.
    plan["cost_scenarios"] = [{"commission_bps": 5, "slippage_bps": 2},
                               {"commission_bps": 2, "slippage_bps": 5}]
    report = diagnostics.run_strategy_diagnostics(verified_workspace_dataset, plan=plan)
    first, second = [group["report"] for group in report["groups"]]
    assert [bool(item["trades"]) for item in first["results"]] == expected_trades
    assert first["comparison_id"] != second["comparison_id"]
    for index, (left, right) in enumerate(zip(first["results"], second["results"], strict=True)):
        assert left["metrics"] == right["metrics"] and left["trades"] == right["trades"]
        assert first["equity"]["results"][index]["points"] == second["equity"]["results"][index]["points"]
        child = report["groups"][0]["comparison_plan"]["strategies"][index]
        if kind == "FEATURE_RULE":
            assert child["comparator"] == "LT" and child["signal_field"] == selected["signal_field"]
        else:
            assert child["match"] == "ANY"
            assert [(rule["signal_field"], rule["comparator"]) for rule in child["conditions"]] == [
                (rule["signal_field"], rule["comparator"]) for rule in selected["conditions"]
            ]
    suffix = "v2" if kind == "COMPOSITE_RULE" else "v1"
    assert first["result_schema_version"] == f"market-vault-strategy-risk-cli-result-{suffix}"
    snapshot = artifacts.create_strategy_diagnostics_experiment(plan=plan, report=report)
    assert ("composite_rule" in snapshot.as_dict()["algorithm_versions"]) == (kind == "COMPOSITE_RULE")
    assert artifacts.StrategyExperiment(snapshot.content).content == snapshot.content
    assert artifacts.replay_strategy_experiment(snapshot)["report_matches"]


def test_origin_fold_cash_attribution_preserves_compounding_overlap_and_zero_fold(monkeypatch):
    bundle = _execution_bundle(
        train_periods=(0, 1, 2), validation_periods=tuple(range(3, 12)), test_periods=(12, 13),
        crossing_ends={(5, "US.AAPL"): _time(7) + timedelta(hours=2),
                       (7, "US.AAPL"): _time(7) + timedelta(hours=4)},
    )
    parts = {}
    for name in ("train", "validation", "test"):
        split = getattr(bundle, name)
        periods = [(item.feature_window_close - _time(0)).days for item in split.metadata]
        ml = replace(split.ml_split,
                     X=tuple((float(period in (5, 6, 7)), *row[1:]) for period, row in zip(periods, split.X)),
                     y=tuple(0.1 if period == 5 else -0.1 if period == 7 else y
                             for period, y in zip(periods, split.y)))
        parts[name] = replace(split, ml_split=ml)
    bundle = replace(bundle, **parts, ml_bundle=replace(
        bundle.ml_bundle, **{name: split.ml_split for name, split in parts.items()},
    ))
    _bind_bundle(monkeypatch, bundle, late_entry_period=_time(7))
    raw = _success_payload(compare_strategies(object(), **_config(
        strategies=(FeatureRuleStrategy("Crossfold", BacktestRule("f1", "GT", 0)),),
        minimum_train_periods=3, validation_periods=3, step_periods=3, commission_bps=0, slippage_bps=0,
    )))
    result = raw["results"][0]
    assert [int(trade["sample_key"], 16) for trade in result["trades"]] == [6, 8]
    assert [result["metrics"][key] for key in ("candidate_count", "signal_count", "trade_count", "overlap_skipped_count")] == [9, 3, 2, 1]
    first, last = result["trades"]
    assert raw["folds"][1]["validation_start_time"] < first["exit_time"] < raw["folds"][1]["validation_end_time"]
    assert last["signal_time"] < first["exit_time"] < last["entry_time"]
    assert first["equity_before"] == 1 and first["equity_after"] == last["equity_before"] == pytest.approx(1.1)
    assert last["equity_after"] == pytest.approx(0.99)
    rows = diagnostics.fold_trade_contributions(raw["folds"], result)
    assert [row["trade_count"] for row in rows] == [1, 1, 0]
    assert [row["cash_contribution"] for row in rows] == pytest.approx([0.1, -0.11, 0])
    assert math.fsum(row["cash_contribution"] for row in rows) == pytest.approx(-0.01)


def test_cost_drag_can_turn_a_positive_trade_negative_with_explicit_reference():
    from dataclasses import asdict
    key = "a" * 64
    folds = [{"fold_index": 0, "fold_id": "b" * 64, "validation_start_time": _time(0).isoformat(),
              "validation_end_time": _time(0).isoformat(), "validation_sample_keys": [key]}]
    reports = []
    for cost in (0, 60):
        trades, metrics = _run_candidates(
            (_Candidate(key, "US.AAPL", _time(0), _time(0) + timedelta(hours=1),
                        _time(0) + timedelta(hours=2), 1, 0.01),),
            rule=BacktestRule("f1", "GT", 0), costs=BacktestCosts(cost, 0),
        )
        reports.append({"folds": folds,
                        "results": [{"result_id": str(cost), "metrics": asdict(metrics),
                                     "trades": [asdict(trade) for trade in trades]}],
                        "equity": {"results": [{"final_equity": trades[-1].equity_after}]}})
    zero = diagnostics.diagnostic_candidate_records(reports[0], ((),), reports[0])[0]
    costly = diagnostics.diagnostic_candidate_records(reports[1], ((),), reports[0])[0]
    assert zero["fold_contributions"][0]["cash_contribution"] == pytest.approx(0.01)
    assert costly["fold_contributions"][0]["cash_contribution"] == pytest.approx(-0.00208364)
    assert costly["return_change_from_first_cost"] == pytest.approx(-0.01208364)


def test_whole_bundle_roundtrip_real_replay_and_offline_open(diagnostic_case, tmp_path, monkeypatch):
    _, _, report, snapshot = diagnostic_case
    path = tmp_path / "diagnostics.json"
    assert artifacts.write_strategy_experiment(snapshot, path=path).created_new_file
    assert artifacts.load_strategy_experiment(path) == snapshot
    assert artifacts.replay_strategy_experiment(snapshot)["report_matches"]
    with monkeypatch.context() as patch:
        patch.setattr(cross_day_dataset, "load_verified_multi_source_cross_day_dataset",
                      lambda *a, **k: pytest.fail("Open read a Dataset"))
        assert artifacts.load_strategy_experiment(path).as_dict()["report"] == report
    assert not artifacts.write_strategy_experiment(snapshot, path=path).created_new_file
    assert path.read_bytes() == snapshot.content
    detached = snapshot.as_dict()
    detached["plan"]["parameter_axes"][0]["values"][0] = 999
    assert artifacts.load_strategy_experiment(path) == snapshot


def test_near_zero_return_reconciles_at_the_existing_equity_scale():
    from dataclasses import asdict
    from test_strategy_equity import _bars, _trades, _curve
    bars = _bars(((1, 100_000), (100_000, 1)))
    trades, metrics = _trades(bars, ((0, 0), (1, 1)), BacktestCosts())
    curve = _curve(bars, trades)  # This is admitted by the production equity ledger.
    folds = [{"fold_index": index, "fold_id": f"{index:064x}",
              "validation_start_time": item.trade.signal_time.isoformat(),
              "validation_end_time": item.trade.signal_time.isoformat(),
              "validation_sample_keys": [item.trade.sample_key]} for index, item in enumerate(trades)]
    raw = {"folds": folds, "results": [{"result_id": "a" * 64, "metrics": asdict(metrics),
                                      "trades": [asdict(item.trade) for item in trades]}],
           "equity": {"results": [{"final_equity": curve.final_equity}]}}
    rows = diagnostics.diagnostic_candidate_records(raw, ((),), raw)[0]["fold_contributions"]
    cash_change = math.fsum(row["cash_contribution"] for row in rows)
    assert cash_change == 0.0 and curve.final_equity == 1.0
    assert not math.isclose(cash_change, metrics.total_return, rel_tol=1e-10, abs_tol=1e-12)
    assert math.isclose(1.0 + cash_change, 1.0 + metrics.total_return, rel_tol=1e-11, abs_tol=1e-12)


@pytest.mark.parametrize("case", ["dropped_group", "dropped_candidate", "reordered_group", "changed_child",
                                  "changed_axis", "count_boolean", "changed_cost_delta", "missing_zero_fold",
                                  "changed_contribution"])
def test_rehashed_diagnostic_records_require_complete_coverage_and_derived_bindings(diagnostic_case, case):
    root = diagnostic_case[-1].as_dict()
    report = root["report"]
    if case == "dropped_group":
        report["groups"].pop()
    elif case == "dropped_candidate":
        report["groups"][-1]["candidates"].pop()
    elif case == "reordered_group":
        report["groups"].reverse()
    elif case == "changed_child":
        report["groups"][-1]["comparison_plan"]["strategies"][-1]["alpha"] += 0.01
    elif case == "changed_axis":
        report["groups"][-1]["candidates"][-1]["axis_values"][0] += 0.01
    elif case == "count_boolean":
        report["variant_count"] = True
    elif case == "changed_cost_delta":
        report["groups"][-1]["candidates"][-1]["return_change_from_first_cost"] += 1e-12
    elif case == "missing_zero_fold":
        report["groups"][-1]["candidates"][-1]["fold_contributions"].pop()
    else:
        report["groups"][-1]["candidates"][-1]["fold_contributions"][0]["cash_contribution"] += 1e-12
    with pytest.raises(ValueError):
        artifacts.StrategyExperiment(_resign(root))


def test_replay_checks_versions_and_dataset_before_fit_and_compares_hidden_group_values(diagnostic_case, monkeypatch):
    dataset, _, original, snapshot = diagnostic_case
    root = snapshot.as_dict()
    root["algorithm_versions"]["diagnostics"] = root["report"]["version"] = "historical-diagnostics"
    historical = artifacts.StrategyExperiment(_resign(root))
    with monkeypatch.context() as patch:
        patch.setattr(cross_day_dataset, "load_verified_multi_source_cross_day_dataset",
                      lambda *a, **k: pytest.fail("version mismatch read a Dataset"))
        with pytest.raises(ValueError, match="algorithm versions differ"):
            artifacts.replay_strategy_experiment(historical)
    with monkeypatch.context() as patch:
        patch.setattr(cross_day_dataset, "load_verified_multi_source_cross_day_dataset",
                      lambda *a, **k: SimpleNamespace(dataset_id="f" * 64))
        patch.setattr(diagnostics, "run_strategy_diagnostics", lambda *a, **k: pytest.fail("wrong Dataset fitted"))
        with pytest.raises(ValueError, match="Dataset ID differs"):
            artifacts.replay_strategy_experiment(snapshot)
    root = snapshot.as_dict()
    root["report"]["groups"][-1]["report"]["equity"]["results"][-1]["points"][101]["equity"] += 1e-12
    changed = artifacts.StrategyExperiment(_resign(root))
    assert changed.as_dict()["report"]["groups"][-1]["report"]["comparison_id"] == original["groups"][-1]["report"]["comparison_id"]
    # Full real replay is tested above; isolate byte comparison here, retaining strict Dataset read.
    monkeypatch.setattr(diagnostics, "run_strategy_diagnostics", lambda *a, **k: original)
    with pytest.raises(ValueError, match="complete report mismatch"):
        artifacts.replay_strategy_experiment(changed, dataset_build_dir=dataset.build_path)


def test_test_targets_do_not_change_any_diagnostic_group(verified_workspace_dataset, monkeypatch):
    from market_vault.research import strategy_comparison, trading_authority
    original = strategy_comparison.build_experiment_dataset
    shift = 0

    def build(*args, **kwargs):
        bundle = original(*args, **kwargs)
        test_ml = replace(bundle.test.ml_split, y=tuple(y + shift for y in bundle.test.y))
        return replace(bundle, test=replace(bundle.test, ml_split=test_ml),
                       ml_bundle=replace(bundle.ml_bundle, test=test_ml))

    monkeypatch.setattr(strategy_comparison, "build_experiment_dataset", build)
    monkeypatch.setattr(trading_authority, "build_experiment_dataset", build)
    plan = _diagnostic_plan(verified_workspace_dataset.build_path)
    plan["comparison_plan"]["strategies"][2]["threshold"] = -100
    plan["parameter_axes"] = [{"parameter": "alpha", "values": [0.1, 1]}]
    first = diagnostics.run_strategy_diagnostics(verified_workspace_dataset, plan=plan)
    shift = 10_000
    second = diagnostics.run_strategy_diagnostics(verified_workspace_dataset, plan=plan)
    # Identity and source authority are fixed deliberately to isolate TEST target use.
    assert canonical_json(first) == canonical_json(second)
    assert first["evaluation_count"] == 4
    test_keys = {item.sample_key for item in original(
        verified_workspace_dataset, label_field=plan["comparison_plan"]["return_label"],
        feature_fields=tuple(plan["comparison_plan"]["feature_fields"])).test.metadata}
    for group in first["groups"]:
        assert not test_keys.intersection(group["report"]["validation_sample_keys"])
        assert all(result["trades"] for result in group["report"]["results"])
        assert not test_keys.intersection(trade["sample_key"] for result in group["report"]["results"] for trade in result["trades"])


def test_cli_saves_every_group_once_and_keeps_settings_independent(diagnostic_case, tmp_path, monkeypatch, capsys):
    from market_vault import strategy_diagnostics_cli
    _, plan, report, _ = diagnostic_case
    calls = []

    def run(dataset, *, plan):
        calls.append(plan)
        return report

    monkeypatch.setattr(strategy_diagnostics_cli, "run_strategy_diagnostics", run)
    monkeypatch.setattr(diagnostics, "run_strategy_diagnostics", run)
    monkeypatch.setattr(cli, "load_settings", lambda *a, **k: pytest.fail("diagnostics loaded settings"))
    file = tmp_path / "plan.json"
    file.write_bytes(canonical_json(plan))
    output = tmp_path / "diagnostics.json"
    assert cli.main(["research-diagnose-strategy", "--plan", str(file), "--output", str(output)]) == 0
    assert json.loads(capsys.readouterr().out) == report and len(calls) == 1
    snapshot = artifacts.load_strategy_experiment(output)
    assert len(snapshot.as_dict()["report"]["groups"]) == 2
    assert cli.main(["research-experiment-open", "--experiment", str(output)]) == 0
    opened = json.loads(capsys.readouterr().out)
    assert opened["result_schema_version"] == "market-vault-strategy-experiment-cli-result-v2"
    assert opened["experiment"] == snapshot.as_dict()
    assert cli.main(["research-experiment-replay", "--experiment", str(output)]) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["diagnostics_id"] == report["diagnostics_id"] and replay["report_matches"]
    assert len(calls) == 2
    invalid = _diagnostic_plan(tmp_path / "absent")
    invalid["parameter_axes"][0]["values"] = [True]
    file.write_bytes(canonical_json(invalid))
    monkeypatch.setattr(strategy_diagnostics_cli, "load_verified_multi_source_cross_day_dataset",
                        lambda *a, **k: pytest.fail("invalid grid loaded Dataset"))
    assert cli.main(["research-diagnose-strategy", "--plan", str(file)]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and json.loads(captured.err)["status"] == "FAILED"
