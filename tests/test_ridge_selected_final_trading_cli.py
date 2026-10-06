"""Focused tests for selected-threshold Ridge Final Trading CLI V1."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from market_vault import cli, ridge_selected_final_trading_cli


def _plan():
    return {
        "plan_schema_version": (
            ridge_selected_final_trading_cli
            .RIDGE_SELECTED_FINAL_TRADING_PLAN_SCHEMA_VERSION
        ),
        "dataset_build_dir": "dataset_id=" + "a" * 64,
        "label_field": "forward_open_to_close_return_5d",
        "feature_fields": ["rsi14", "macd"],
        "minimum_train_periods": 100,
        "validation_periods": 20,
        "step_periods": 20,
        "alphas": [10.0, 0.1, 1.0],
        "thresholds": [0.02, -0.01, 0.0],
        "commission_bps": 1.5,
        "slippage_bps": 2.5,
    }


def _candidate():
    return SimpleNamespace(
        candidate_id="c" * 64,
        threshold=0.02,
        validation_sample_count=40,
        signal_count=20,
        overlap_skipped_count=2,
        trade_count=18,
        gross_total_return=0.17,
        total_return=0.15,
        realized_max_drawdown=0.05,
        win_rate=0.6,
        average_trade_return=0.02,
        profit_factor=1.5,
        average_signal_to_exit_seconds=172800.0,
    )


def _objects():
    verified = object()
    experiment = object()
    walk_forward = object()
    ridge = SimpleNamespace(selection_id="r" * 64)
    candidate = _candidate()
    threshold = SimpleNamespace(
        threshold_selection_id="t" * 64,
        walk_forward_id="w" * 64,
        dataset_id="a" * 64,
        label_name="forward_open_to_close_return_5d",
        feature_names=("rsi14", "macd"),
        selected_alpha=1.0,
        selected_threshold=0.02,
        selected_candidate_id=candidate.candidate_id,
        costs=SimpleNamespace(
            commission_bps=1.5,
            slippage_bps=2.5,
        ),
        candidates=(candidate,),
    )
    final = SimpleNamespace(
        final_test_id="f" * 64,
        model_id="m" * 64,
        dataset_id="a" * 64,
        label_name="forward_open_to_close_return_5d",
        feature_names=("rsi14", "macd"),
        alpha=1.0,
        test_count=12,
        mae=0.10,
        rmse=0.20,
        r2=0.30,
    )
    metrics = SimpleNamespace(
        candidate_count=12,
        signal_count=6,
        overlap_skipped_count=1,
        trade_count=5,
        gross_total_return=0.25,
        total_return=0.21,
        realized_max_drawdown=0.08,
        win_rate=0.6,
        average_trade_return=0.04,
        profit_factor=1.8,
        average_signal_to_exit_seconds=259200.0,
    )
    trading = SimpleNamespace(
        trading_id="g" * 64,
        metrics=metrics,
        trades=tuple(range(5)),
    )
    return (
        verified,
        experiment,
        walk_forward,
        ridge,
        threshold,
        final,
        trading,
    )


def test_cli_composes_validation_selection_before_permanent_test(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "ridge-selected-final-trading.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    (
        verified,
        experiment,
        walk_forward,
        ridge,
        threshold,
        final,
        trading,
    ) = _objects()
    calls = []

    def threshold_pipeline(plan, parent):
        calls.append(("threshold", plan, parent))
        return (
            verified,
            experiment,
            walk_forward,
            ridge,
            threshold,
        )

    def final_test(bundle, plan, selection):
        calls.append(("final", bundle, plan, selection))
        return final

    def selected_final(dataset, bundle, result, selection):
        calls.append(
            ("selected_final", dataset, bundle, result, selection)
        )
        return trading

    def forbidden_settings(_):
        pytest.fail(
            "research-ridge-selected-final-trading must dispatch before settings"
        )

    monkeypatch.setattr(
        ridge_selected_final_trading_cli,
        "_threshold_pipeline",
        threshold_pipeline,
    )
    monkeypatch.setattr(
        ridge_selected_final_trading_cli,
        "evaluate_ridge_final_test",
        final_test,
    )
    monkeypatch.setattr(
        ridge_selected_final_trading_cli,
        "evaluate_ridge_selected_final_trading",
        selected_final,
    )
    monkeypatch.setattr(cli, "load_settings", forbidden_settings)

    assert cli.main([
        "--settings",
        str(tmp_path / "missing-settings.yaml"),
        "research-ridge-selected-final-trading",
        "--plan",
        str(plan_path),
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "SUCCESS"
    assert output["threshold_selection_id"] == "t" * 64
    assert output["ridge_selection_id"] == "r" * 64
    assert output["walk_forward_id"] == "w" * 64
    assert output["final_test_id"] == "f" * 64
    assert output["model_id"] == "m" * 64
    assert output["trading_id"] == "g" * 64
    assert output["selected_alpha"] == 1.0
    assert output["selected_threshold"] == 0.02
    assert output["selected_candidate_id"] == "c" * 64
    assert output["costs"] == {
        "commission_bps": 1.5,
        "slippage_bps": 2.5,
    }
    assert output["validation_selected_candidate_metrics"]["total_return"] == 0.15
    assert output["test_regression_metrics"] == {
        "mae": 0.10,
        "rmse": 0.20,
        "r2": 0.30,
    }
    assert output["test_trading_metrics"]["total_return"] == 0.21
    assert output["accepted_test_trade_count"] == 5

    assert calls[0][0] == "threshold"
    assert calls[0][2] == tmp_path
    assert calls[1] == (
        "final",
        experiment,
        walk_forward,
        ridge,
    )
    assert calls[2] == (
        "selected_final",
        verified,
        experiment,
        final,
        threshold,
    )


def test_plan_reuses_threshold_selection_validation_and_normalization():
    plan = (
        ridge_selected_final_trading_cli
        .parse_ridge_selected_final_trading_plan_bytes(
            json.dumps(_plan()).encode("utf-8")
        )
    )
    inner = plan.threshold_plan
    assert inner.ridge_plan.alphas == (0.1, 1.0, 10.0)
    assert inner.thresholds == (-0.01, 0.0, 0.02)
    assert inner.commission_bps == 1.5
    assert inner.slippage_bps == 2.5


@pytest.mark.parametrize(
    "extra",
    [
        {"test_threshold": 0.0},
        {"final_threshold": 0.0},
        {"test_thresholds": [0.0, 0.1]},
        {"tune_on_test": True},
        {"reuse_test": True},
    ],
)
def test_plan_rejects_every_test_threshold_or_tuning_field(extra):
    payload = _plan() | extra
    with pytest.raises(
        ridge_selected_final_trading_cli
        .RidgeSelectedFinalTradingCLIError
    ):
        (
            ridge_selected_final_trading_cli
            .parse_ridge_selected_final_trading_plan_bytes(
                json.dumps(payload).encode("utf-8")
            )
        )


def test_plan_rejects_duplicate_json_key():
    payload = (
        b'{"plan_schema_version":'
        b'"market-vault-ridge-selected-final-trading-plan-v1",'
        b'"plan_schema_version":'
        b'"market-vault-ridge-selected-final-trading-plan-v1"}'
    )
    with pytest.raises(
        ridge_selected_final_trading_cli
        .RidgeSelectedFinalTradingCLIError,
        match="duplicate JSON key",
    ):
        (
            ridge_selected_final_trading_cli
            .parse_ridge_selected_final_trading_plan_bytes(payload)
        )


def test_cli_failure_is_structured(tmp_path, monkeypatch, capsys):
    payload = _plan()
    plan_path = tmp_path / "ridge-selected-final-trading.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(
        ridge_selected_final_trading_cli,
        "_threshold_pipeline",
        lambda plan, parent: (_ for _ in ()).throw(
            ValueError("not a verified Dataset")
        ),
    )

    assert cli.main([
        "research-ridge-selected-final-trading",
        "--plan",
        str(plan_path),
    ]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    output = json.loads(captured.err)
    assert output["status"] == "FAILED"
    assert output["result_schema_version"] == (
        ridge_selected_final_trading_cli
        .RIDGE_SELECTED_FINAL_TRADING_CLI_RESULT_SCHEMA_VERSION
    )
    assert "not a verified Dataset" in output["error"]
