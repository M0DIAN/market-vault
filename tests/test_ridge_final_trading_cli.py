"""Focused tests for Ridge Final TEST Trading Plan + CLI V1."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from market_vault import cli, ridge_final_trading_cli


def _plan():
    return {
        "plan_schema_version": (
            ridge_final_trading_cli.RIDGE_FINAL_TRADING_PLAN_SCHEMA_VERSION
        ),
        "dataset_build_dir": "dataset_id=" + "a" * 64,
        "label_field": "forward_open_to_close_return_5d",
        "feature_fields": ["rsi14", "macd"],
        "minimum_train_periods": 100,
        "validation_periods": 20,
        "step_periods": 20,
        "alphas": [10.0, 0.1, 1.0],
        "commission_bps": 1.5,
        "slippage_bps": 2.5,
    }


def _selection():
    return SimpleNamespace(selection_id="s" * 64)


def _final():
    return SimpleNamespace(
        version="market-vault-ridge-final-test-v1",
        final_test_id="f" * 64,
        model_id="m" * 64,
        dataset_id="a" * 64,
        label_name="forward_open_to_close_return_5d",
        feature_names=("rsi14", "macd"),
        alpha=1.0,
        test_count=30,
        mae=0.025,
        rmse=0.035,
        r2=0.15,
    )


def _trading():
    return SimpleNamespace(
        trading_id="t" * 64,
        costs=SimpleNamespace(
            commission_bps=1.5,
            slippage_bps=2.5,
        ),
        metrics=SimpleNamespace(
            candidate_count=30,
            signal_count=18,
            overlap_skipped_count=3,
            trade_count=15,
            gross_total_return=0.42,
            total_return=0.36,
            realized_max_drawdown=0.08,
            win_rate=0.6,
            average_trade_return=0.025,
            profit_factor=1.8,
            average_signal_to_exit_seconds=172800.0,
        ),
        trades=tuple(range(15)),
    )


def test_trading_cli_is_settings_independent_and_has_no_test_threshold(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "ridge-final-trading-plan.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    verified = object()
    experiment = object()
    walk_forward = object()
    selection = _selection()
    final = _final()
    trading = _trading()
    captured = {}

    def pipeline(plan, parent):
        captured["base_plan"] = plan
        captured["parent"] = parent
        return (
            verified,
            experiment,
            walk_forward,
            selection,
            final,
        )

    def evaluate(dataset, bundle, result, **kwargs):
        captured["trading_dataset"] = dataset
        captured["trading_bundle"] = bundle
        captured["trading_final"] = result
        captured["trading_kwargs"] = kwargs
        return trading

    def forbidden_settings(_):
        pytest.fail(
            "research-ridge-final-trading must dispatch before settings load"
        )

    monkeypatch.setattr(
        ridge_final_trading_cli,
        "_pipeline",
        pipeline,
    )
    monkeypatch.setattr(
        ridge_final_trading_cli,
        "evaluate_ridge_final_trading",
        evaluate,
    )
    monkeypatch.setattr(cli, "load_settings", forbidden_settings)

    assert cli.main([
        "--settings",
        str(tmp_path / "missing-settings.yaml"),
        "research-ridge-final-trading",
        "--plan",
        str(plan_path),
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "SUCCESS"
    assert output["result_schema_version"] == (
        ridge_final_trading_cli
        .RIDGE_FINAL_TRADING_CLI_RESULT_SCHEMA_VERSION
    )
    assert output["final_test_version"] == (
        "market-vault-ridge-final-test-v1"
    )
    assert output["trading_evaluation_version"] == (
        "market-vault-ridge-final-trading-v1"
    )
    assert output["selection_id"] == "s" * 64
    assert output["final_test_id"] == "f" * 64
    assert output["model_id"] == "m" * 64
    assert output["trading_id"] == "t" * 64
    assert output["dataset_id"] == "a" * 64
    assert output["label_name"] == "forward_open_to_close_return_5d"
    assert output["feature_names"] == ["rsi14", "macd"]
    assert output["selected_alpha"] == 1.0
    assert output["test_count"] == 30
    assert output["test_metrics"] == {
        "mae": 0.025,
        "rmse": 0.035,
        "r2": 0.15,
    }
    assert output["signal_rule"] == "PREDICTED_RETURN_GT_ZERO"
    assert output["costs"] == {
        "commission_bps": 1.5,
        "slippage_bps": 2.5,
    }
    assert output["trading_metrics"] == {
        "candidate_count": 30,
        "signal_count": 18,
        "overlap_skipped_count": 3,
        "trade_count": 15,
        "gross_total_return": 0.42,
        "total_return": 0.36,
        "realized_max_drawdown": 0.08,
        "win_rate": 0.6,
        "average_trade_return": 0.025,
        "profit_factor": 1.8,
        "average_signal_to_exit_seconds": 172800.0,
    }
    assert output["trade_count"] == 15
    assert "threshold" not in payload
    assert "threshold" not in output

    base = captured["base_plan"]
    assert base.dataset_build_dir == payload["dataset_build_dir"]
    assert base.label_field == payload["label_field"]
    assert base.feature_fields == ("rsi14", "macd")
    assert base.alphas == (0.1, 1.0, 10.0)
    assert captured["parent"] == tmp_path
    assert captured["trading_dataset"] is verified
    assert captured["trading_bundle"] is experiment
    assert captured["trading_final"] is final
    assert captured["trading_kwargs"] == {
        "commission_bps": 1.5,
        "slippage_bps": 2.5,
    }


def test_trading_plan_reuses_ridge_final_validation_and_normalization():
    payload = _plan()
    parsed = ridge_final_trading_cli.parse_ridge_final_trading_plan_bytes(
        json.dumps(payload).encode("utf-8")
    )
    base = parsed.ridge_final_plan
    assert base.feature_fields == ("rsi14", "macd")
    assert base.alphas == (0.1, 1.0, 10.0)
    assert base.minimum_train_periods == 100
    assert base.validation_periods == 20
    assert base.step_periods == 20
    assert parsed.commission_bps == 1.5
    assert parsed.slippage_bps == 2.5


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("commission_bps", -1.0, "non-negative"),
        ("slippage_bps", -1.0, "non-negative"),
        ("commission_bps", True, "real finite number"),
        ("slippage_bps", float("inf"), "finite"),
        ("commission_bps", 9999.0, "below 10000"),
    ],
)
def test_trading_plan_rejects_invalid_costs(field, value, match):
    payload = _plan()
    payload[field] = value
    if field == "commission_bps" and value == 9999.0:
        payload["slippage_bps"] = 2.0
    with pytest.raises(
        ridge_final_trading_cli.RidgeFinalTradingCLIError,
        match=match,
    ):
        ridge_final_trading_cli.parse_ridge_final_trading_plan_bytes(
            json.dumps(payload).encode("utf-8")
        )


def test_trading_plan_has_no_threshold_or_unknown_fields():
    payload = _plan() | {"threshold": 0.01}
    with pytest.raises(
        ridge_final_trading_cli.RidgeFinalTradingCLIError,
    ):
        ridge_final_trading_cli.parse_ridge_final_trading_plan_bytes(
            json.dumps(payload).encode("utf-8")
        )


def test_trading_plan_rejects_duplicate_json_key():
    payload = (
        b'{"plan_schema_version":'
        b'"market-vault-ridge-final-trading-plan-v1",'
        b'"plan_schema_version":'
        b'"market-vault-ridge-final-trading-plan-v1"}'
    )
    with pytest.raises(
        ridge_final_trading_cli.RidgeFinalTradingCLIError,
        match="duplicate JSON key",
    ):
        ridge_final_trading_cli.parse_ridge_final_trading_plan_bytes(
            payload
        )


def test_trading_cli_failure_is_structured(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "ridge-final-trading-plan.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(
        ridge_final_trading_cli,
        "_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError("not a verified Dataset")
        ),
    )

    assert cli.main([
        "research-ridge-final-trading",
        "--plan",
        str(plan_path),
    ]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    output = json.loads(captured.err)
    assert output["status"] == "FAILED"
    assert output["result_schema_version"] == (
        ridge_final_trading_cli
        .RIDGE_FINAL_TRADING_CLI_RESULT_SCHEMA_VERSION
    )
    assert "not a verified Dataset" in output["error"]
