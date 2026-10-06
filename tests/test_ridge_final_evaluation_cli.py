"""Focused tests for final Ridge research evaluation Plan + CLI V1."""

from __future__ import annotations

import argparse
import json
from types import SimpleNamespace

import pytest

from market_vault import ridge_final_evaluation_cli


def _plan():
    return {
        "plan_schema_version": (
            ridge_final_evaluation_cli
            .RIDGE_FINAL_EVALUATION_PLAN_SCHEMA_VERSION
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


def _metric(total_return, drawdown, signals=18, trades=15):
    return SimpleNamespace(
        candidate_count=30,
        signal_count=signals,
        overlap_skipped_count=signals - trades,
        trade_count=trades,
        gross_total_return=total_return + 0.03,
        total_return=total_return,
        realized_max_drawdown=drawdown,
        win_rate=0.6,
        average_trade_return=0.025,
        profit_factor=1.8,
        average_signal_to_exit_seconds=172800.0,
    )


def _objects():
    ridge = SimpleNamespace(selection_id="r" * 64)
    threshold = SimpleNamespace(
        threshold_selection_id="t" * 64,
        selected_candidate_id="c" * 64,
        selected_threshold=0.02,
        walk_forward_id="w" * 64,
        costs=SimpleNamespace(
            commission_bps=1.5,
            slippage_bps=2.5,
        ),
    )
    final = SimpleNamespace(
        final_test_id="f" * 64,
        model_id="m" * 64,
    )
    fixed = SimpleNamespace(
        trading_id="x" * 64,
    )
    selected = SimpleNamespace(
        trading_id="y" * 64,
    )
    fixed_metrics = _metric(0.20, 0.10, signals=20, trades=17)
    selected_metrics = _metric(0.27, 0.07, signals=16, trades=14)
    delta = SimpleNamespace(
        signal_count=-4,
        overlap_skipped_count=-1,
        trade_count=-3,
        gross_total_return=0.07,
        total_return=0.07,
        realized_max_drawdown=-0.03,
        win_rate=0.0,
        average_trade_return=0.0,
        profit_factor=0.0,
        average_signal_to_exit_seconds=0.0,
    )
    report = SimpleNamespace(
        report_id="q" * 64,
        walk_forward_id="w" * 64,
        threshold_selection_id="t" * 64,
        selected_candidate_id="c" * 64,
        final_test_id="f" * 64,
        model_id="m" * 64,
        dataset_id="a" * 64,
        label_name="forward_open_to_close_return_5d",
        feature_names=("rsi14", "macd"),
        selected_alpha=1.0,
        selected_threshold=0.02,
        costs=threshold.costs,
        test_count=30,
        test_mae=0.025,
        test_rmse=0.035,
        test_r2=0.15,
        fixed_metrics=fixed_metrics,
        selected_metrics=selected_metrics,
        delta=delta,
    )
    return ridge, threshold, final, fixed, selected, report


def test_cli_runs_one_reporting_pipeline_without_test_selection(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "ridge-final-evaluation-plan.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")
    ridge, threshold, final, fixed, selected, report = _objects()

    verified = object()
    experiment = object()
    walk_forward = object()
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

    def evaluate_fixed(dataset, bundle, result, **kwargs):
        captured["fixed"] = (dataset, bundle, result, kwargs)
        return fixed

    def evaluate_selected(dataset, bundle, result, selection):
        captured["selected"] = (dataset, bundle, result, selection)
        return selected

    def compare(result, fixed_result, threshold_result, selected_result):
        captured["compare"] = (
            result,
            fixed_result,
            threshold_result,
            selected_result,
        )
        return report

    monkeypatch.setattr(
        ridge_final_evaluation_cli,
        "ridge_final_pipeline",
        pipeline,
    )
    monkeypatch.setattr(
        ridge_final_evaluation_cli,
        "select_ridge_trading_threshold",
        select_threshold,
    )
    monkeypatch.setattr(
        ridge_final_evaluation_cli,
        "evaluate_ridge_final_trading",
        evaluate_fixed,
    )
    monkeypatch.setattr(
        ridge_final_evaluation_cli,
        "evaluate_ridge_selected_final_trading",
        evaluate_selected,
    )
    monkeypatch.setattr(
        ridge_final_evaluation_cli,
        "compare_ridge_final_trading",
        compare,
    )

    assert ridge_final_evaluation_cli.research_ridge_final_evaluation_main(
        argparse.Namespace(plan=str(plan_path))
    ) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "SUCCESS"
    assert output["result_schema_version"] == (
        ridge_final_evaluation_cli
        .RIDGE_FINAL_EVALUATION_CLI_RESULT_SCHEMA_VERSION
    )
    assert output["evaluation_version"] == (
        "market-vault-ridge-final-evaluation-v1"
    )
    assert output["report_id"] == "q" * 64
    assert output["selected_threshold"] == 0.02
    assert output["delta_direction"] == (
        "VALIDATION_SELECTED_MINUS_FIXED_ZERO"
    )
    assert output["fixed_zero"]["trading_id"] == "x" * 64
    assert output["validation_selected"]["trading_id"] == "y" * 64
    assert output["fixed_zero"]["metrics"]["total_return"] == 0.20
    assert output["validation_selected"]["metrics"]["total_return"] == 0.27
    assert output["delta"]["total_return"] == 0.07
    assert output["delta"]["realized_max_drawdown"] == -0.03

    assert "winner" not in output
    assert "decision" not in output
    assert "recommendation" not in output

    base = captured["ridge_plan"]
    assert base.dataset_build_dir == payload["dataset_build_dir"]
    assert base.feature_fields == ("rsi14", "macd")
    assert base.alphas == (0.1, 1.0, 10.0)
    assert captured["parent"] == tmp_path
    assert captured["threshold_kwargs"] == {
        "thresholds": (-0.01, 0.0, 0.02),
        "commission_bps": 1.5,
        "slippage_bps": 2.5,
    }
    assert captured["fixed"][3] == {
        "commission_bps": 1.5,
        "slippage_bps": 2.5,
    }
    assert captured["selected"][3] is threshold
    assert captured["compare"] == (final, fixed, threshold, selected)


def test_plan_reuses_validation_selection_normalization():
    parsed = (
        ridge_final_evaluation_cli
        .parse_ridge_final_evaluation_plan_bytes(
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
        {"winner_metric": "total_return"},
        {"recommendation_rule": "best"},
        {"test_selection": True},
        {"test_threshold": 0.0},
        {"final_threshold": 0.0},
        {"test_refit": True},
    ],
)
def test_plan_rejects_test_selection_or_recommendation_controls(extra):
    payload = _plan() | extra
    with pytest.raises(
        ridge_final_evaluation_cli.RidgeFinalEvaluationCLIError,
    ):
        ridge_final_evaluation_cli.parse_ridge_final_evaluation_plan_bytes(
            json.dumps(payload).encode("utf-8")
        )


def test_plan_rejects_duplicate_json_key():
    payload = (
        b'{"plan_schema_version":'
        b'"market-vault-ridge-final-evaluation-plan-v1",'
        b'"plan_schema_version":'
        b'"market-vault-ridge-final-evaluation-plan-v1"}'
    )
    with pytest.raises(
        ridge_final_evaluation_cli.RidgeFinalEvaluationCLIError,
        match="duplicate JSON key",
    ):
        ridge_final_evaluation_cli.parse_ridge_final_evaluation_plan_bytes(
            payload
        )


def test_cli_failure_is_structured(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "ridge-final-evaluation-plan.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(
        ridge_final_evaluation_cli,
        "ridge_final_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError("not a verified Dataset")
        ),
    )

    assert ridge_final_evaluation_cli.research_ridge_final_evaluation_main(
        argparse.Namespace(plan=str(plan_path))
    ) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    output = json.loads(captured.err)
    assert output["status"] == "FAILED"
    assert output["result_schema_version"] == (
        ridge_final_evaluation_cli
        .RIDGE_FINAL_EVALUATION_CLI_RESULT_SCHEMA_VERSION
    )
    assert "not a verified Dataset" in output["error"]
