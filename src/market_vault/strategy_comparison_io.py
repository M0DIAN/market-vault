"""Shared strict plan and complete result transport for strategy research."""

from __future__ import annotations

import codecs
from dataclasses import asdict
from datetime import date, datetime
import json

from .backtest import BacktestCosts
from .backtest_cli import BacktestCLIError, _metrics_payload, _number
from .dataset.cli import (
    _no_duplicate_pairs,
    _require_exact_fields,
    _require_object,
    _require_string,
    _require_string_array,
)
from .research.strategy_comparison import (
    CompositeRuleStrategy,
    STRATEGY_COMPARISON_V2_VERSION,
    _strategy_fields,
    compare_strategies,
)
from .research.strategy_config import parse_strategy_specs, strategy_plan_fields
from .research.walk_forward import _positive_int


STRATEGY_COMPARISON_PLAN_VERSION = "market-vault-strategy-comparison-plan-v1"
STRATEGY_COMPARISON_PLAN_V2_VERSION = "market-vault-strategy-comparison-plan-v2"
STRATEGY_COMPARISON_CLI_VERSION = "market-vault-strategy-comparison-cli-result-v1"
STRATEGY_EQUITY_CLI_VERSION = "market-vault-strategy-equity-cli-result-v1"
STRATEGY_RISK_CLI_VERSION = "market-vault-strategy-risk-cli-result-v1"
STRATEGY_COMPARISON_CLI_V2_VERSION = "market-vault-strategy-comparison-cli-result-v2"
STRATEGY_EQUITY_CLI_V2_VERSION = "market-vault-strategy-equity-cli-result-v2"
STRATEGY_RISK_CLI_V2_VERSION = "market-vault-strategy-risk-cli-result-v2"
_PLAN_FIELDS = frozenset({
    "plan_schema_version", "dataset_build_dir", "feature_fields", "return_label",
    "strategies", "minimum_train_periods", "validation_periods", "step_periods",
    "commission_bps", "slippage_bps",
})


def parse_strategy_comparison_plan_bytes(payload: bytes) -> dict:
    if payload.startswith(codecs.BOM_UTF8):
        raise ValueError("strategy comparison plan must not carry a UTF-8 BOM")
    root = _require_object(
        json.loads(payload.decode("utf-8"), object_pairs_hook=_no_duplicate_pairs),
        "strategy comparison plan",
    )
    _require_exact_fields(root, _PLAN_FIELDS, "strategy comparison plan")
    if root["plan_schema_version"] not in (STRATEGY_COMPARISON_PLAN_VERSION, STRATEGY_COMPARISON_PLAN_V2_VERSION):
        raise ValueError("unsupported strategy comparison plan_schema_version")
    strategies = parse_strategy_specs(
        root["strategies"], allow_composite=root["plan_schema_version"] == STRATEGY_COMPARISON_PLAN_V2_VERSION,
    )
    costs = BacktestCosts(
        _number(root["commission_bps"], "commission_bps"),
        _number(root["slippage_bps"], "slippage_bps"),
    )
    validation = _positive_int(root["validation_periods"], "validation_periods")
    step = _positive_int(root["step_periods"], "step_periods")
    if step < validation:
        raise ValueError("step_periods must be at least validation_periods")
    return {
        "dataset_build_dir": _require_string(root["dataset_build_dir"], "dataset_build_dir"),
        "feature_fields": _require_string_array(root["feature_fields"], "feature_fields"),
        "return_label": _require_string(root["return_label"], "return_label"),
        "strategies": tuple(strategies),
        "minimum_train_periods": _positive_int(root["minimum_train_periods"], "minimum_train_periods"),
        "validation_periods": validation,
        "step_periods": step,
        "commission_bps": costs.commission_bps,
        "slippage_bps": costs.slippage_bps,
    }


def _cli_result_version(version: str, extended: bool) -> str:
    return {
        STRATEGY_COMPARISON_CLI_VERSION: STRATEGY_COMPARISON_CLI_V2_VERSION,
        STRATEGY_EQUITY_CLI_VERSION: STRATEGY_EQUITY_CLI_V2_VERSION,
        STRATEGY_RISK_CLI_VERSION: STRATEGY_RISK_CLI_V2_VERSION,
    }[version] if extended else version


def _success_payload(report) -> dict:
    plan = report.plan
    return {
        "result_schema_version": _cli_result_version(
            STRATEGY_COMPARISON_CLI_VERSION, report.version == STRATEGY_COMPARISON_V2_VERSION,
        ),
        "status": "SUCCESS",
        "version": report.version,
        "comparison_id": report.comparison_id,
        "engine_version": report.engine_version,
        "evaluation_scope": report.evaluation_scope,
        "dataset_id": plan.dataset_id,
        "walk_forward_id": plan.walk_forward_id,
        "feature_names": list(plan.feature_names),
        "return_label": plan.label_name,
        "costs": asdict(report.costs),
        "minimum_train_periods": plan.minimum_train_periods,
        "validation_periods": plan.validation_periods,
        "step_periods": plan.step_periods,
        "held_out_test_sample_count": plan.held_out_test_count,
        "validation_sample_keys": list(report.validation_sample_keys),
        "folds": [{
            "fold_index": fold.fold_index,
            "fold_id": fold.fold_id,
            "validation_start_time": fold.validation_start_time.isoformat(),
            "validation_end_time": fold.validation_end_time.isoformat(),
            "train_count": fold.train.row_count,
            "purged_train_count": fold.purged_train_count,
            "validation_sample_keys": list(fold.validation.sample_keys),
        } for fold in plan.folds],
        "results": [{
            "strategy": _strategy_fields(result.strategy),
            "result_id": result.result_id,
            "metrics": _metrics_payload(result.metrics),
            "trades": [{
                **asdict(trade),
                "signal_time": trade.signal_time.isoformat(),
                "entry_time": trade.entry_time.isoformat(),
                "exit_time": trade.exit_time.isoformat(),
            } for trade in result.trades],
        } for result in report.results],
    }


def _curve_payload(curve) -> dict:
    return {
        "version": curve.version, "curve_id": curve.curve_id,
        "final_equity": curve.final_equity,
        "bar_close_max_drawdown": curve.bar_close_max_drawdown,
        "transaction_cost_total": curve.transaction_cost_total,
        "points": [{**asdict(point), "timestamp": point.timestamp.isoformat()}
                   for point in curve.points],
    }


def _json_values(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_values(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_values(item) for item in value]
    return value


def _equity_payload(report) -> dict:
    payload = _success_payload(report.comparison)
    payload["result_schema_version"] = _cli_result_version(
        STRATEGY_EQUITY_CLI_VERSION, report.comparison.version == STRATEGY_COMPARISON_V2_VERSION,
    )
    payload["equity"] = {
        "version": report.version,
        "equity_comparison_id": report.equity_comparison_id,
        "interval": report.interval,
        "start_time": report.start_time.isoformat(),
        "end_time": report.end_time.isoformat(),
        "price_evidence_id": report.price_evidence_id,
        "results": [{
            "strategy_result_id": result.strategy_result_id,
            **_curve_payload(result.curve),
        } for result in report.results],
    }
    return payload


def _risk_payload(report) -> dict:
    payload = _equity_payload(report.equity)
    payload["result_schema_version"] = _cli_result_version(
        STRATEGY_RISK_CLI_VERSION, report.equity.comparison.version == STRATEGY_COMPARISON_V2_VERSION,
    )
    payload["risk"] = {
        "version": report.version, "risk_report_id": report.risk_report_id,
        "benchmark_definition": report.benchmark_definition,
        "sampling": "COMPLETE_RECORDED_SESSION_CLOSE_TO_CLOSE",
        "benchmark": {
            "curve": _curve_payload(report.benchmark_curve),
            "total_return": report.benchmark_curve.final_equity - 1.0,
            "daily_risk": _json_values(asdict(report.benchmark_risk)),
        },
        "results": [_json_values(asdict(result)) for result in report.results],
    }
    return payload


def normalized_comparison_plan(config: dict, *, dataset_build_dir: str) -> dict:
    """Capture explicit, normalized inputs in their original semantic order."""
    raw = {
        "plan_schema_version": STRATEGY_COMPARISON_PLAN_V2_VERSION if any(
            type(item) is CompositeRuleStrategy for item in config["strategies"]
        ) else STRATEGY_COMPARISON_PLAN_VERSION,
        "dataset_build_dir": dataset_build_dir,
        "feature_fields": list(config["feature_fields"]),
        "return_label": config["return_label"],
        "strategies": [strategy_plan_fields(item) for item in config["strategies"]],
        "minimum_train_periods": config["minimum_train_periods"],
        "validation_periods": config["validation_periods"],
        "step_periods": (config["validation_periods"] if config.get("step_periods") is None
                         else config["step_periods"]),
        "commission_bps": config.get("commission_bps", 0.0),
        "slippage_bps": config.get("slippage_bps", 0.0),
    }
    parsed = parse_strategy_comparison_plan_bytes(json.dumps(raw, allow_nan=False).encode())
    return {**raw, **{key: parsed[key] for key in (
        "minimum_train_periods", "validation_periods", "step_periods", "commission_bps", "slippage_bps",
    )}, "strategies": [strategy_plan_fields(item) for item in parsed["strategies"]]}


def evaluate_comparison_payload(dataset, config: dict, mode: str) -> dict:
    """Use the same existing calculation and payload path for live runs and replay."""
    if mode == "RISK":
        from .research.strategy_risk import compare_strategies_with_risk
        return _risk_payload(compare_strategies_with_risk(dataset, **config))
    if mode == "EQUITY":
        from .research.strategy_equity import compare_strategies_with_equity
        return _equity_payload(compare_strategies_with_equity(dataset, **config))
    if mode == "COMPARISON":
        return _success_payload(compare_strategies(dataset, **config))
    raise ValueError("unsupported experiment evaluation mode")
