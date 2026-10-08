"""Offline strategy comparison CLI with optional explicit experiment saving."""

from __future__ import annotations

import json
import sys

from .backtest_cli import BacktestCLIError
from .cross_day_dataset import load_verified_multi_source_cross_day_dataset
from .dataset.cli import DatasetCLIError, _coerce_plan_path, _read_plan_bytes, _resolve_plan_path
from .research.strategy_comparison import CompositeRuleStrategy
# Preserve existing imports from this CLI module while sharing one exact codec.
from .strategy_comparison_io import (
    STRATEGY_COMPARISON_PLAN_VERSION, STRATEGY_COMPARISON_PLAN_V2_VERSION,
    STRATEGY_COMPARISON_CLI_VERSION, STRATEGY_COMPARISON_CLI_V2_VERSION,
    STRATEGY_EQUITY_CLI_VERSION, STRATEGY_EQUITY_CLI_V2_VERSION,
    STRATEGY_RISK_CLI_VERSION, STRATEGY_RISK_CLI_V2_VERSION,
    _PLAN_FIELDS, _cli_result_version, _success_payload, _curve_payload,
    _json_values, _equity_payload, _risk_payload,
    parse_strategy_comparison_plan_bytes, normalized_comparison_plan,
    evaluate_comparison_payload,
)


def add_strategy_comparison_subparser(subparsers) -> None:
    parser = subparsers.add_parser(
        "research-compare-strategies",
        help="Compare Feature rules, composite rules and Ridge on common validation samples",
    )
    parser.add_argument("--plan", required=True, metavar="PATH")
    parser.add_argument(
        "--equity-curve", action="store_true",
        help="Add verified bar-close cash/share equity paths and drawdown",
    )
    parser.add_argument(
        "--risk-report", action="store_true",
        help="Include equity, same-symbol buy-and-hold and daily risk statistics",
    )
    parser.add_argument("--output", metavar="PATH", help="Exclusively save the completed experiment snapshot")
    parser.add_argument("--name", default="", help="Optional saved experiment name (requires --output)")
    parser.add_argument("--notes", default="", help="Optional saved experiment notes (requires --output)")


def research_compare_strategies_main(args) -> int:
    with_equity = getattr(args, "equity_curve", False)
    with_risk = getattr(args, "risk_report", False)
    extended = False
    try:
        if not getattr(args, "output", None) and (getattr(args, "name", "") or getattr(args, "notes", "")):
            raise ValueError("--name and --notes require --output")
        plan_path = _coerce_plan_path(args.plan)
        config = parse_strategy_comparison_plan_bytes(_read_plan_bytes(plan_path))
        extended = any(type(item) is CompositeRuleStrategy for item in config["strategies"])
        build_dir = _resolve_plan_path(
            config.pop("dataset_build_dir"), base=plan_path.parent,
            label="Research Dataset build",
        )
        dataset = load_verified_multi_source_cross_day_dataset(build_dir)
        mode = "RISK" if with_risk else "EQUITY" if with_equity else "COMPARISON"
        payload = evaluate_comparison_payload(dataset, config, mode)
        if getattr(args, "output", None):
            from .research.strategy_experiment import create_strategy_experiment, write_strategy_experiment
            snapshot = create_strategy_experiment(
                plan=normalized_comparison_plan(config, dataset_build_dir=str(build_dir)),
                report=payload, mode=mode,
                name=getattr(args, "name", ""), notes=getattr(args, "notes", ""),
            )
            write_strategy_experiment(snapshot, path=args.output)
        print(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (BacktestCLIError, DatasetCLIError, OSError, TypeError, ValueError, KeyError, OverflowError) as exc:
        print(json.dumps({
            "result_schema_version": _cli_result_version(
                STRATEGY_RISK_CLI_VERSION if with_risk else
                STRATEGY_EQUITY_CLI_VERSION if with_equity else STRATEGY_COMPARISON_CLI_VERSION,
                extended,
            ),
            "status": "FAILED",
            "error": f"research-compare-strategies failed: {exc}",
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
