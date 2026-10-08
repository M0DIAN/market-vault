"""Explicit, offline finite strategy diagnostics with optional whole-bundle save."""

from __future__ import annotations

import json
import sys

from .backtest_cli import BacktestCLIError
from .cross_day_dataset import load_verified_multi_source_cross_day_dataset
from .dataset.cli import DatasetCLIError, _coerce_plan_path, _read_plan_bytes, _resolve_plan_path
from .research.strategy_diagnostics import (
    STRATEGY_DIAGNOSTICS_RESULT_VERSION, parse_strategy_diagnostics_plan_bytes,
    run_strategy_diagnostics,
)
from .research.strategy_experiment import create_strategy_diagnostics_experiment, write_strategy_experiment


def add_strategy_diagnostics_subparser(subparsers) -> None:
    parser = subparsers.add_parser(
        "research-diagnose-strategy", help="Evaluate every explicit parameter/cost combination on common validation folds",
    )
    parser.add_argument("--plan", required=True, metavar="PATH")
    parser.add_argument("--output", metavar="PATH", help="Exclusively save the complete diagnostic experiment")
    parser.add_argument("--name", default="", help="Optional saved experiment name (requires --output)")
    parser.add_argument("--notes", default="", help="Optional saved experiment notes (requires --output)")


def research_diagnose_strategy_main(args) -> int:
    try:
        if not args.output and (args.name or args.notes):
            raise ValueError("--name and --notes require --output")
        path = _coerce_plan_path(args.plan)
        plan = parse_strategy_diagnostics_plan_bytes(_read_plan_bytes(path))
        build = _resolve_plan_path(plan["comparison_plan"]["dataset_build_dir"],
                                   base=path.parent, label="Research Dataset build")
        plan["comparison_plan"]["dataset_build_dir"] = str(build)
        dataset = load_verified_multi_source_cross_day_dataset(build)
        report = run_strategy_diagnostics(dataset, plan=plan)
        if args.output:
            snapshot = create_strategy_diagnostics_experiment(
                plan=plan, report=report, name=args.name, notes=args.notes,
            )
            write_strategy_experiment(snapshot, path=args.output)
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (BacktestCLIError, DatasetCLIError, OSError, TypeError, ValueError, KeyError,
            OverflowError, RecursionError) as exc:
        print(json.dumps({
            "result_schema_version": STRATEGY_DIAGNOSTICS_RESULT_VERSION,
            "status": "FAILED", "error": f"research-diagnose-strategy failed: {exc}",
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
