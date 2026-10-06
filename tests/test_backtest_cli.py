"""Focused tests for Backtest Plan + CLI V1."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from market_vault import backtest_cli, cli


def _plan():
    return {
        "plan_schema_version": backtest_cli.BACKTEST_PLAN_SCHEMA_VERSION,
        "dataset_build_dir": "dataset_id=" + "a" * 64,
        "signal_field": "ts2_simple_return",
        "comparator": "GT",
        "threshold": 0.0,
        "return_label": "forward_open_to_close_return_1d",
        "split": "TEST",
        "commission_bps": 1.5,
        "slippage_bps": 2.5,
    }


def _result():
    return SimpleNamespace(
        engine_version="market-vault-backtest-v1",
        backtest_id="b" * 64,
        dataset_id="a" * 64,
        split="TEST",
        rule=SimpleNamespace(
            signal_field="ts2_simple_return",
            comparator="GT",
            threshold=0.0,
        ),
        return_label="forward_open_to_close_return_1d",
        costs=SimpleNamespace(commission_bps=1.5, slippage_bps=2.5),
        metrics=SimpleNamespace(
            candidate_count=10,
            signal_count=5,
            overlap_skipped_count=1,
            trade_count=4,
            gross_total_return=0.20,
            total_return=0.18,
            realized_max_drawdown=0.07,
            win_rate=0.75,
            average_trade_return=0.04,
            profit_factor=2.5,
            average_holding_seconds=86400.0,
            exposure=0.5,
        ),
    )


def test_research_backtest_cli_is_settings_independent_and_explicit(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "backtest-plan.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = object()
    captured = {}

    def load(path):
        captured["path"] = path
        return loaded

    def run(dataset, **kwargs):
        captured["dataset"] = dataset
        captured["kwargs"] = kwargs
        return _result()

    def forbidden_settings(_):
        pytest.fail("research-backtest must dispatch before settings load")

    monkeypatch.setattr(
        backtest_cli,
        "load_verified_multi_source_cross_day_dataset",
        load,
    )
    monkeypatch.setattr(backtest_cli, "run_backtest", run)
    monkeypatch.setattr(cli, "load_settings", forbidden_settings)

    assert cli.main([
        "--settings",
        str(tmp_path / "missing-settings.yaml"),
        "research-backtest",
        "--plan",
        str(plan_path),
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "result_schema_version": backtest_cli.BACKTEST_CLI_RESULT_SCHEMA_VERSION,
        "status": "SUCCESS",
        "engine_version": "market-vault-backtest-v1",
        "backtest_id": "b" * 64,
        "dataset_id": "a" * 64,
        "split": "TEST",
        "rule": {
            "signal_field": "ts2_simple_return",
            "comparator": "GT",
            "threshold": 0.0,
        },
        "return_label": "forward_open_to_close_return_1d",
        "costs": {
            "commission_bps": 1.5,
            "slippage_bps": 2.5,
        },
        "metrics": {
            "candidate_count": 10,
            "signal_count": 5,
            "overlap_skipped_count": 1,
            "trade_count": 4,
            "gross_total_return": 0.20,
            "total_return": 0.18,
            "realized_max_drawdown": 0.07,
            "win_rate": 0.75,
            "average_trade_return": 0.04,
            "profit_factor": 2.5,
            "average_holding_seconds": 86400.0,
            "exposure": 0.5,
        },
    }
    assert captured["path"] == tmp_path / payload["dataset_build_dir"]
    assert captured["dataset"] is loaded
    assert captured["kwargs"] == {
        "signal_field": "ts2_simple_return",
        "comparator": "GT",
        "threshold": 0.0,
        "return_label": "forward_open_to_close_return_1d",
        "split": "TEST",
        "commission_bps": 1.5,
        "slippage_bps": 2.5,
    }


def test_backtest_plan_rejects_duplicate_json_key():
    payload = (
        b'{"plan_schema_version":"market-vault-backtest-plan-v1",'
        b'"plan_schema_version":"market-vault-backtest-plan-v1"}'
    )
    with pytest.raises(backtest_cli.BacktestCLIError, match="duplicate JSON key"):
        backtest_cli.parse_backtest_plan_bytes(payload)


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("comparator", "EQ", "comparator"),
        ("split", "ALL", "split"),
        ("threshold", True, "JSON number"),
        ("commission_bps", -1, "non-negative"),
        ("slippage_bps", float("inf"), "finite"),
    ],
)
def test_backtest_plan_rejects_invalid_values(field, value, match):
    payload = _plan()
    payload[field] = value
    encoded = json.dumps(payload).encode("utf-8")
    with pytest.raises(backtest_cli.BacktestCLIError, match=match):
        backtest_cli.parse_backtest_plan_bytes(encoded)


def test_backtest_plan_rejects_extra_or_missing_fields():
    extra = _plan() | {"latest": True}
    with pytest.raises(backtest_cli.BacktestCLIError):
        backtest_cli.parse_backtest_plan_bytes(json.dumps(extra).encode("utf-8"))

    missing = _plan()
    del missing["dataset_build_dir"]
    with pytest.raises(backtest_cli.BacktestCLIError):
        backtest_cli.parse_backtest_plan_bytes(
            json.dumps(missing).encode("utf-8")
        )


def test_research_backtest_cli_failure_is_structured(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "backtest-plan.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    def fail(_):
        raise ValueError("not a verified Dataset")

    monkeypatch.setattr(
        backtest_cli,
        "load_verified_multi_source_cross_day_dataset",
        fail,
    )

    assert cli.main([
        "research-backtest",
        "--plan",
        str(plan_path),
    ]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    output = json.loads(captured.err)
    assert output["status"] == "FAILED"
    assert output["result_schema_version"] == (
        backtest_cli.BACKTEST_CLI_RESULT_SCHEMA_VERSION
    )
    assert "not a verified Dataset" in output["error"]
