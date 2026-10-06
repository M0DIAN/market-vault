"""Focused tests for selected-threshold Ridge Final TEST Trading CLI V1."""

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


def _ridge_selection():
    return SimpleNamespace(selection_id="r" * 64)


def _candidate(letter, threshold, total_return, drawdown):
    return SimpleNamespace(
        candidate_id=letter * 64,
        threshold=threshold,
        validation_sample_count=40,
        signal_count=20,
        overlap_skipped_count=2,
        trade_count=18,
        gross_total_return=total_return + 0.02,
        total_return=total_return,
        realized_max_drawdown=drawdown,
        win_rate=0.6,
        average_trade_return=0.02,
        profit_factor=1.5,
        average_signal_to_exit_seconds=172800.0,
    )


def _threshold_selection():
    return SimpleNamespace(
        threshold_selection_id="t" * 64,
        selected_candidate_id="c" * 64,
        walk_forward_id="w" * 64,
        dataset_id="a" * 64,
        label_name="forward_open_to_close_return_5d",
        feature_names=("rsi14", "macd"),
        selected_alpha=1.0,
        selected_threshold=0.02,
        costs=SimpleNamespace(
            commission_bps=1.5,
            slippage_bps=2.5,
        ),
        validation_predictions=tuple(range(40)),
        candidates=(
            _candidate("b", -0.01, 0.10, 0.08),
            _candidate("d", 0.0, 0.12, 0.07),
            _candidate("c", 0.02, 0.15, 0.05),
        ),
    )


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
        trading_id="z" * 64,
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


def test_cli_applies_validation_selected_threshold_to_final_test_only(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "ridge-selected-final-trading-plan.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    verified = object()
    experiment = object()
    walk_forward = object()
    ridge = _ridge_selection()
    threshold = _threshold_selection()
    final = _final()
    trading = _trading()
    captured = {}

    def pipeline(plan, parent):
        captured["ridge_plan"] = plan
        captured["parent"] = parent
        return verified, experiment, walk_forward, ridge, final

    def select_threshold(dataset, bundle, walk, selection, **kwargs):
        captured["threshold_dataset"] = dataset
        captured["threshold_bundle"] = bundle
        captured["threshold_walk"] = walk
        captured["threshold_ridge"] = selection
        captured["threshold_kwargs"] = kwargs
        return threshold

    def evaluate(dataset, bundle, result, selected):
        captured["test_dataset"] = dataset
        captured["test_bundle"] = bundle
        captured["test_final"] = result
        captured["test_threshold"] = selected
        return trading

    def forbidden_settings(_):
        pytest.fail(
            "research-ridge-selected-final-trading must dispatch before settings"
        )

    monkeypatch.setattr(
        ridge_selected_final_trading_cli,
        "ridge_final_pipeline",
        pipeline,
    )
    monkeypatch.setattr(
        ridge_selected_final_trading_cli,
        "select_ridge_trading_threshold",
        select_threshold,
    )
    monkeypatch.setattr(
        ridge_selected_final_trading_cli,
        "evaluate_ridge_selected_final_trading",
        evaluate,
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
    assert output["result_schema_version"] == (
        ridge_selected_final_trading_cli
        .RIDGE_SELECTED_FINAL_TRADING_CLI_RESULT_SCHEMA_VERSION
    )
    assert output["threshold_selection_version"] == (
        "market-vault-ridge-trading-threshold-selection-v1"
    )
    assert output["selected_final_trading_version"] == (
        "market-vault-ridge-selected-final-trading-v1"
    )
    assert output["ridge_selection_id"] == "r" * 64
    assert output["walk_forward_id"] == "w" * 64
    assert output["threshold_selection_id"] == "t" * 64
    assert output["selected_candidate_id"] == "c" * 64
    assert output["final_test_id"] == "f" * 64
    assert output["model_id"] == "m" * 64
    assert output["trading_id"] == "z" * 64
    assert output["dataset_id"] == "a" * 64
    assert output["selected_alpha"] == 1.0
    assert output["selected_threshold"] == 0.02
    assert output["threshold_selection_metric"] == "TOTAL_RETURN"
    assert output["signal_rule"] == (
        "PREDICTED_RETURN_GT_VALIDATION_SELECTED_THRESHOLD"
    )
    assert output["costs"] == {
        "commission_bps": 1.5,
        "slippage_bps": 2.5,
    }
    assert output["validation_prediction_count"] == 40
    assert [item["threshold"] for item in output["validation_candidates"]] == [
        -0.01, 0.0, 0.02
    ]
    assert output["test_count"] == 30
    assert output["test_metrics"] == {
        "mae": 0.025,
        "rmse": 0.035,
        "r2": 0.15,
    }
    assert output["trading_metrics"]["total_return"] == 0.36
    assert output["trade_count"] == 15

    # There is no separate TEST threshold/cost channel.
    assert "test_threshold" not in payload
    assert "final_threshold" not in payload
    assert "test_threshold" not in output
    assert "final_threshold" not in output

    base = captured["ridge_plan"]
    assert base.dataset_build_dir == payload["dataset_build_dir"]
    assert base.label_field == payload["label_field"]
    assert base.feature_fields == ("rsi14", "macd")
    assert base.alphas == (0.1, 1.0, 10.0)
    assert captured["parent"] == tmp_path
    assert captured["threshold_dataset"] is verified
    assert captured["threshold_bundle"] is experiment
    assert captured["threshold_walk"] is walk_forward
    assert captured["threshold_ridge"] is ridge
    assert captured["threshold_kwargs"] == {
        "thresholds": (-0.01, 0.0, 0.02),
        "commission_bps": 1.5,
        "slippage_bps": 2.5,
    }
    assert captured["test_dataset"] is verified
    assert captured["test_bundle"] is experiment
    assert captured["test_final"] is final
    assert captured["test_threshold"] is threshold


def test_plan_reuses_validation_selection_normalization():
    parsed = (
        ridge_selected_final_trading_cli
        .parse_ridge_selected_final_trading_plan_bytes(
            json.dumps(_plan()).encode("utf-8")
        )
    )
    selection = parsed.selection_plan
    assert selection.ridge_plan.feature_fields == ("rsi14", "macd")
    assert selection.ridge_plan.alphas == (0.1, 1.0, 10.0)
    assert selection.thresholds == (-0.01, 0.0, 0.02)
    assert selection.commission_bps == 1.5
    assert selection.slippage_bps == 2.5


@pytest.mark.parametrize(
    "extra",
    [
        {"test_threshold": 0.0},
        {"final_threshold": 0.0},
        {"test_commission_bps": 1.0},
        {"test_slippage_bps": 1.0},
        {"test_refit": True},
    ],
)
def test_plan_rejects_test_stage_overrides(extra):
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
    plan_path = tmp_path / "ridge-selected-final-trading-plan.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(
        ridge_selected_final_trading_cli,
        "ridge_final_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(
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
