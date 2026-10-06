"""Focused tests for Ridge trading threshold selection Plan + CLI V1."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from market_vault import cli, ridge_trading_selection_cli


def _plan():
    return {
        "plan_schema_version": (
            ridge_trading_selection_cli
            .RIDGE_TRADING_SELECTION_PLAN_SCHEMA_VERSION
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
        walk_forward_id="w" * 64,
        dataset_id="a" * 64,
        label_name="forward_open_to_close_return_5d",
        feature_names=("rsi14", "macd"),
        selected_alpha=1.0,
        costs=SimpleNamespace(
            commission_bps=1.5,
            slippage_bps=2.5,
        ),
        validation_predictions=tuple(range(40)),
        selected_threshold=0.02,
        selected_candidate_id="c" * 64,
        candidates=(
            _candidate("b", -0.01, 0.10, 0.08),
            _candidate("d", 0.0, 0.12, 0.07),
            _candidate("c", 0.02, 0.15, 0.05),
        ),
    )


def test_cli_is_settings_independent_and_stops_before_final_test(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "ridge-trading-selection.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    verified = object()
    experiment = object()
    walk_forward = object()
    ridge = _ridge_selection()
    threshold = _threshold_selection()
    captured = {}

    def load(path):
        captured["path"] = path
        return verified

    def build(dataset, **kwargs):
        captured["build_dataset"] = dataset
        captured["build_kwargs"] = kwargs
        return experiment

    def walk(bundle, **kwargs):
        captured["walk_bundle"] = bundle
        captured["walk_kwargs"] = kwargs
        return walk_forward

    def select_alpha(plan, **kwargs):
        captured["alpha_plan"] = plan
        captured["alpha_kwargs"] = kwargs
        return ridge

    def select_threshold(dataset, bundle, plan, selection, **kwargs):
        captured["threshold_dataset"] = dataset
        captured["threshold_bundle"] = bundle
        captured["threshold_plan"] = plan
        captured["threshold_ridge"] = selection
        captured["threshold_kwargs"] = kwargs
        return threshold

    def forbidden_settings(_):
        pytest.fail(
            "research-ridge-trading-select must dispatch before settings load"
        )

    monkeypatch.setattr(
        ridge_trading_selection_cli,
        "load_verified_multi_source_cross_day_dataset",
        load,
    )
    monkeypatch.setattr(
        ridge_trading_selection_cli,
        "build_experiment_dataset",
        build,
    )
    monkeypatch.setattr(
        ridge_trading_selection_cli,
        "build_walk_forward_plan",
        walk,
    )
    monkeypatch.setattr(
        ridge_trading_selection_cli,
        "select_ridge_alpha",
        select_alpha,
    )
    monkeypatch.setattr(
        ridge_trading_selection_cli,
        "select_ridge_trading_threshold",
        select_threshold,
    )
    monkeypatch.setattr(cli, "load_settings", forbidden_settings)

    assert cli.main([
        "--settings",
        str(tmp_path / "missing-settings.yaml"),
        "research-ridge-trading-select",
        "--plan",
        str(plan_path),
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "SUCCESS"
    assert output["result_schema_version"] == (
        ridge_trading_selection_cli
        .RIDGE_TRADING_SELECTION_CLI_RESULT_SCHEMA_VERSION
    )
    assert output["ridge_alpha_selection_version"] == (
        "market-vault-ridge-alpha-selection-v1"
    )
    assert output["trading_threshold_selection_version"] == (
        "market-vault-ridge-trading-threshold-selection-v1"
    )
    assert output["threshold_selection_id"] == "t" * 64
    assert output["ridge_selection_id"] == "r" * 64
    assert output["walk_forward_id"] == "w" * 64
    assert output["dataset_id"] == "a" * 64
    assert output["selected_alpha"] == 1.0
    assert output["metric"] == "TOTAL_RETURN"
    assert output["selected_threshold"] == 0.02
    assert output["validation_prediction_count"] == 40
    assert output["costs"] == {
        "commission_bps": 1.5,
        "slippage_bps": 2.5,
    }
    assert [item["threshold"] for item in output["candidates"]] == [
        -0.01, 0.0, 0.02
    ]
    assert "test" not in output
    assert "final_test_id" not in output

    base = captured["build_kwargs"]
    assert captured["path"] == tmp_path / payload["dataset_build_dir"]
    assert captured["build_dataset"] is verified
    assert base == {
        "label_field": payload["label_field"],
        "feature_fields": ("rsi14", "macd"),
    }
    assert captured["walk_bundle"] is experiment
    assert captured["walk_kwargs"] == {
        "minimum_train_periods": 100,
        "validation_periods": 20,
        "step_periods": 20,
    }
    assert captured["alpha_plan"] is walk_forward
    assert captured["alpha_kwargs"] == {
        "alphas": (0.1, 1.0, 10.0),
    }
    assert captured["threshold_dataset"] is verified
    assert captured["threshold_bundle"] is experiment
    assert captured["threshold_plan"] is walk_forward
    assert captured["threshold_ridge"] is ridge
    assert captured["threshold_kwargs"] == {
        "thresholds": (-0.01, 0.0, 0.02),
        "commission_bps": 1.5,
        "slippage_bps": 2.5,
    }


def test_plan_normalizes_alpha_and_threshold_order():
    plan = ridge_trading_selection_cli.parse_ridge_trading_selection_plan_bytes(
        json.dumps(_plan()).encode("utf-8")
    )
    assert plan.ridge_plan.alphas == (0.1, 1.0, 10.0)
    assert plan.thresholds == (-0.01, 0.0, 0.02)
    assert plan.commission_bps == 1.5
    assert plan.slippage_bps == 2.5


@pytest.mark.parametrize(
    "thresholds,match",
    [
        ([], "at least two"),
        ([0.0], "at least two"),
        ([0.0, 0.0], "unique"),
        ([True, 0.0], "JSON numbers"),
        ([float("inf"), 0.0], "finite"),
        ("0,0.1", "JSON array"),
    ],
)
def test_plan_rejects_invalid_thresholds(thresholds, match):
    payload = _plan()
    payload["thresholds"] = thresholds
    with pytest.raises(
        ridge_trading_selection_cli.RidgeTradingSelectionCLIError,
        match=match,
    ):
        ridge_trading_selection_cli.parse_ridge_trading_selection_plan_bytes(
            json.dumps(payload).encode("utf-8")
        )


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("commission_bps", -1.0, "non-negative"),
        ("slippage_bps", -1.0, "non-negative"),
        ("commission_bps", True, "real finite number"),
        ("slippage_bps", float("inf"), "finite"),
    ],
)
def test_plan_rejects_invalid_costs(field, value, match):
    payload = _plan()
    payload[field] = value
    with pytest.raises(
        ridge_trading_selection_cli.RidgeTradingSelectionCLIError,
        match=match,
    ):
        ridge_trading_selection_cli.parse_ridge_trading_selection_plan_bytes(
            json.dumps(payload).encode("utf-8")
        )


def test_plan_rejects_test_and_unknown_fields():
    for extra in (
        {"test_threshold": 0.0},
        {"final_test": True},
        {"reuse_test": True},
    ):
        payload = _plan() | extra
        with pytest.raises(
            ridge_trading_selection_cli.RidgeTradingSelectionCLIError,
        ):
            ridge_trading_selection_cli.parse_ridge_trading_selection_plan_bytes(
                json.dumps(payload).encode("utf-8")
            )


def test_plan_rejects_duplicate_json_key():
    payload = (
        b'{"plan_schema_version":'
        b'"market-vault-ridge-trading-selection-plan-v1",'
        b'"plan_schema_version":'
        b'"market-vault-ridge-trading-selection-plan-v1"}'
    )
    with pytest.raises(
        ridge_trading_selection_cli.RidgeTradingSelectionCLIError,
        match="duplicate JSON key",
    ):
        ridge_trading_selection_cli.parse_ridge_trading_selection_plan_bytes(
            payload
        )


def test_cli_failure_is_structured(tmp_path, monkeypatch, capsys):
    payload = _plan()
    plan_path = tmp_path / "ridge-trading-selection.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(
        ridge_trading_selection_cli,
        "load_verified_multi_source_cross_day_dataset",
        lambda path: (_ for _ in ()).throw(
            ValueError("not a verified Dataset")
        ),
    )

    assert cli.main([
        "research-ridge-trading-select",
        "--plan",
        str(plan_path),
    ]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    output = json.loads(captured.err)
    assert output["status"] == "FAILED"
    assert output["result_schema_version"] == (
        ridge_trading_selection_cli
        .RIDGE_TRADING_SELECTION_CLI_RESULT_SCHEMA_VERSION
    )
    assert "not a verified Dataset" in output["error"]
