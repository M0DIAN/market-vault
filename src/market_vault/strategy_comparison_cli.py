"""Strict, offline JSON plan for common walk-forward strategy comparison."""

from __future__ import annotations

import codecs
from dataclasses import asdict
import json
import sys

from .backtest import BacktestCosts, BacktestRule
from .backtest_cli import BacktestCLIError, _metrics_payload, _number
from .cross_day_dataset import load_verified_multi_source_cross_day_dataset
from .dataset.cli import (
    DatasetCLIError,
    _coerce_plan_path,
    _no_duplicate_pairs,
    _read_plan_bytes,
    _require_exact_fields,
    _require_object,
    _require_string,
    _require_string_array,
    _resolve_plan_path,
)
from .research.strategy_comparison import (
    FeatureRuleStrategy,
    RidgeStrategy,
    _strategy_fields,
    compare_strategies,
)
from .research.walk_forward import _positive_int


STRATEGY_COMPARISON_PLAN_VERSION = "market-vault-strategy-comparison-plan-v1"
STRATEGY_COMPARISON_CLI_VERSION = "market-vault-strategy-comparison-cli-result-v1"
_PLAN_FIELDS = frozenset({
    "plan_schema_version", "dataset_build_dir", "feature_fields", "return_label",
    "strategies", "minimum_train_periods", "validation_periods", "step_periods",
    "commission_bps", "slippage_bps",
})


def add_strategy_comparison_subparser(subparsers) -> None:
    parser = subparsers.add_parser(
        "research-compare-strategies",
        help="Compare rules and Ridge on common walk-forward validation samples",
    )
    parser.add_argument("--plan", required=True, metavar="PATH")


def parse_strategy_comparison_plan_bytes(payload: bytes) -> dict:
    if payload.startswith(codecs.BOM_UTF8):
        raise ValueError("strategy comparison plan must not carry a UTF-8 BOM")
    root = _require_object(
        json.loads(payload.decode("utf-8"), object_pairs_hook=_no_duplicate_pairs),
        "strategy comparison plan",
    )
    _require_exact_fields(root, _PLAN_FIELDS, "strategy comparison plan")
    if root["plan_schema_version"] != STRATEGY_COMPARISON_PLAN_VERSION:
        raise ValueError("unsupported strategy comparison plan_schema_version")
    specs = root["strategies"]
    if type(specs) is not list or not specs:
        raise ValueError("strategies must be a non-empty JSON array")
    strategies = []
    for spec in specs:
        spec = _require_object(spec, "strategy")
        kind = spec.get("kind")
        if kind == "FEATURE_RULE":
            _require_exact_fields(spec, frozenset({
                "kind", "name", "signal_field", "comparator", "threshold",
            }), "feature rule strategy")
            strategies.append(FeatureRuleStrategy(
                _require_string(spec["name"], "name"),
                BacktestRule(
                    _require_string(spec["signal_field"], "signal_field"),
                    _require_string(spec["comparator"], "comparator"),
                    _number(spec["threshold"], "threshold"),
                ),
            ))
        elif kind == "RIDGE":
            _require_exact_fields(spec, frozenset({
                "kind", "name", "alpha", "threshold",
            }), "Ridge strategy")
            strategies.append(RidgeStrategy(
                _require_string(spec["name"], "name"),
                _number(spec["alpha"], "alpha"),
                _number(spec["threshold"], "threshold"),
            ))
        else:
            raise ValueError("strategy kind must be FEATURE_RULE or RIDGE")
    if len({spec.name for spec in strategies}) != len(strategies):
        raise ValueError("strategy names must be unique")
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


def _success_payload(report) -> dict:
    plan = report.plan
    return {
        "result_schema_version": STRATEGY_COMPARISON_CLI_VERSION,
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


def research_compare_strategies_main(args) -> int:
    try:
        plan_path = _coerce_plan_path(args.plan)
        config = parse_strategy_comparison_plan_bytes(_read_plan_bytes(plan_path))
        build_dir = _resolve_plan_path(
            config.pop("dataset_build_dir"), base=plan_path.parent,
            label="Research Dataset build",
        )
        dataset = load_verified_multi_source_cross_day_dataset(build_dir)
        report = compare_strategies(dataset, **config)
        print(json.dumps(_success_payload(report), ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (BacktestCLIError, DatasetCLIError, OSError, TypeError, ValueError, KeyError) as exc:
        print(json.dumps({
            "result_schema_version": STRATEGY_COMPARISON_CLI_VERSION,
            "status": "FAILED",
            "error": f"research-compare-strategies failed: {exc}",
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
