"""Composite signals, compatibility and real plan/desktop transport."""

from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from market_vault import cli, strategy_comparison_cli as cli_io
from market_vault.backtest.models import BacktestRule
from market_vault.research.strategy_comparison import (
    CompositeRuleStrategy, FeatureRuleStrategy, RidgeStrategy, StrategyComparisonError,
    _strategy_signals, compare_strategies,
)
from market_vault.research.strategy_config import parse_strategy_specs, strategy_plan_fields
from market_vault.research.strategy_risk import compare_strategies_with_risk
from test_strategy_comparison import (
    _bind_bundle, _config, _execution_bundle, _plan, _real_config,
    verified_workspace_dataset,  # noqa: F401
)


def _composite(match="ALL", *, name="combined", first="f1", second="f2"):
    return CompositeRuleStrategy(name, (
        BacktestRule(first, "GE", 0), BacktestRule(second, "LT", 10),
    ), match)


def test_all_any_boundary_truth_values_are_feature_only():
    rows = {"both": (0.0, 9.0), "first": (1.0, 10.0),
            "second": (-1.0, 5.0), "neither": (-1.0, 10.0)}
    plan = SimpleNamespace(feature_names=("f1", "f2"))
    all_scores, all_rule = _strategy_signals(_composite(), plan, rows)
    any_scores, any_rule = _strategy_signals(_composite("ANY"), plan, rows)
    assert all_scores == {"both": 1.0, "first": 0.0, "second": 0.0, "neither": 0.0}
    assert any_scores == {"both": 1.0, "first": 1.0, "second": 1.0, "neither": 0.0}
    assert all_rule == any_rule == BacktestRule("composite_signal", "GT", 0.5)
    # The rule adapter can operate without target arrays or trading returns.
    numeric, _ = _strategy_signals(FeatureRuleStrategy("raw", BacktestRule("f2", "GT", 0)), plan, rows)
    assert numeric == {key: row[1] for key, row in rows.items()}


def test_adding_composite_preserves_legacy_result_ids_and_condition_order(monkeypatch):
    _bind_bundle(monkeypatch, _execution_bundle())
    original = compare_strategies(object(), **_config())
    assert original.comparison_id == "cf6b7fbbc796004eedaf0f9483500ae438e6b69d543f508835c4141b0e32727d"
    mixed = compare_strategies(object(), **_config(strategies=_config()["strategies"] + (_composite(),)))
    assert mixed.results[:3] == original.results
    assert mixed.version == "market-vault-strategy-comparison-v2"
    assert cli_io._success_payload(mixed)["result_schema_version"] == cli_io.STRATEGY_COMPARISON_CLI_V2_VERSION
    reverse = replace(_composite(), conditions=tuple(reversed(_composite().conditions)))
    reordered = compare_strategies(object(), **_config(strategies=_config()["strategies"] + (reverse,)))
    assert mixed.results[-1].trades == reordered.results[-1].trades
    assert mixed.results[-1].metrics == reordered.results[-1].metrics
    assert mixed.results[-1].result_id != reordered.results[-1].result_id
    assert mixed.validation_sample_keys == original.validation_sample_keys
    assert all(item.metrics.candidate_count == len(mixed.validation_sample_keys) for item in mixed.results)
    assert parse_strategy_specs([strategy_plan_fields(reverse)]) == (reverse,)


@pytest.mark.parametrize("match,threshold,forbidden", [("ALL", 10000, "forward_open_to_close_return_5d"),
                                                        ("ANY", -10000, "not_projected")])
def test_short_circuit_never_skips_feature_authority(monkeypatch, match, threshold, forbidden):
    _bind_bundle(monkeypatch, _execution_bundle())
    strategy = CompositeRuleStrategy("bad", (BacktestRule("f1", "GT", threshold),
                                              BacktestRule(forbidden, "GT", 0)), match)
    with pytest.raises(StrategyComparisonError, match="common Feature projection"):
        compare_strategies(object(), **_config(strategies=(strategy,)))


@pytest.mark.parametrize("change", [
    {"conditions": []}, {"conditions": [{"signal_field": "f1", "comparator": "GT", "threshold": 0}]},
    {"match": "NOT"}, {"name": " "}, {"extra": True},
    {"conditions": [{"signal_field": "f1", "comparator": "GT", "threshold": True}] * 2},
    {"conditions": [{"signal_field": "f1", "comparator": "GT", "threshold": float("inf")}] * 2},
])
def test_composite_descriptor_rejects_ambiguous_or_nonfinite_inputs(change):
    with pytest.raises(ValueError):
        parse_strategy_specs([{**strategy_plan_fields(_composite()), **change}])


def test_plan_versions_keep_legacy_grammar_and_roundtrip():
    old = _plan("dataset")
    new = {**old, "plan_schema_version": cli_io.STRATEGY_COMPARISON_PLAN_V2_VERSION}
    assert cli_io.parse_strategy_comparison_plan_bytes(json.dumps(old).encode()) == (
        cli_io.parse_strategy_comparison_plan_bytes(json.dumps(new).encode())
    )
    composite = strategy_plan_fields(_composite(first="return_2", second="return_2"))
    with pytest.raises(ValueError, match="unsupported strategy kind"):
        cli_io.parse_strategy_comparison_plan_bytes(json.dumps({**old, "strategies": [composite]}).encode())
    parsed = cli_io.parse_strategy_comparison_plan_bytes(json.dumps({**new, "strategies": [composite]}).encode())
    assert strategy_plan_fields(parsed["strategies"][0]) == composite
    with pytest.raises(ValueError, match="unique"):
        parse_strategy_specs([composite, composite])


def _verified_composite_config():
    config = _real_config()
    config["feature_fields"] = ("return_2", "volume_ratio_5")
    config["strategies"] += (CompositeRuleStrategy("MomentumWithVolume", (
        BacktestRule("return_2", "GT", 0), BacktestRule("volume_ratio_5", "GE", 0),
    )),)
    return config


def test_verified_composite_risk_cli(verified_workspace_dataset, tmp_path, monkeypatch, capsys):
    dataset = verified_workspace_dataset
    config = _verified_composite_config()
    report = compare_strategies_with_risk(dataset, **config)
    assert len(report.results) == 4
    assert report.equity.comparison.results[-1].metrics.trade_count > 0
    plan = {**_plan(dataset.build_path), **config,
            "plan_schema_version": cli_io.STRATEGY_COMPARISON_PLAN_V2_VERSION,
            "strategies": [strategy_plan_fields(item) for item in config["strategies"]]}
    path = tmp_path / "composite.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    monkeypatch.setattr(cli, "load_settings", lambda *a, **k: pytest.fail("comparison loaded settings"))
    assert cli.main(["research-compare-strategies", "--plan", str(path), "--risk-report"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == cli_io._risk_payload(report)
    assert result["result_schema_version"] == cli_io.STRATEGY_RISK_CLI_V2_VERSION


def test_verified_composite_desktop(verified_workspace_dataset):
    pytest.importorskip("PySide6")
    from market_vault.desktop.quant_research import _run_strategy_comparison
    config = _verified_composite_config()
    view = _run_strategy_comparison(verified_workspace_dataset.build_path, **config, risk_report=True)
    assert [row[0] for row in view.page.rows] == [item.name for item in config["strategies"]]
    assert len(view.equity) == len(view.risk_page.rows) == 5


def test_desktop_projection_and_blank_numbers_are_explicit():
    pytest.importorskip("PySide6")
    from market_vault.desktop.quant_research import _parse_comparison_strategies
    values = {"feature_fields": ["f1", "f2"], "strategies": [strategy_plan_fields(_composite())]}
    assert _parse_comparison_strategies(values, ("f1", "f2"))["strategies"] == (_composite(),)
    ridge_only = {"feature_fields": ["f2"], "strategies": [strategy_plan_fields(RidgeStrategy("only"))]}
    assert _parse_comparison_strategies(ridge_only, ("f1", "f2"))["feature_fields"] == ("f2",)
    for fields in ([], ["f1", "f1"], ["f1"], ["f1", "LABEL"]):
        with pytest.raises(ValueError):
            _parse_comparison_strategies({**values, "feature_fields": fields}, ("f1", "f2"))
    values["strategies"][0]["conditions"][0]["threshold"] = ""
    with pytest.raises(ValueError, match="finite"):
        _parse_comparison_strategies(values, ("f1", "f2"))


def test_v2_failure_keeps_admitted_strategy_schema(tmp_path, capsys):
    plan = {**_plan(tmp_path / "missing"), "plan_schema_version": cli_io.STRATEGY_COMPARISON_PLAN_V2_VERSION,
            "strategies": [strategy_plan_fields(_composite(first="return_2", second="return_2"))]}
    path = tmp_path / "failure.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    assert cli.main(["research-compare-strategies", "--plan", str(path), "--risk-report"]) == 1
    assert json.loads(capsys.readouterr().err)["result_schema_version"] == cli_io.STRATEGY_RISK_CLI_V2_VERSION
    plan["strategies"][0]["conditions"].pop()
    path.write_text(json.dumps(plan), encoding="utf-8")
    assert cli.main(["research-compare-strategies", "--plan", str(path)]) == 1
    assert json.loads(capsys.readouterr().err)["result_schema_version"] == cli_io.STRATEGY_COMPARISON_CLI_VERSION
