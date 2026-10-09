"""Settings-independent simultaneous bounds for a complete saved DEV family."""

from __future__ import annotations

import json
import sys

from .research.intraday_family_bounds import (
    INTRADAY_FAMILY_BOUNDS_VERSION, analyze_intraday_family_bounds,
)
from .research.strategy_experiment import load_strategy_experiment


def add_intraday_family_bounds_subparser(subparsers):
    parser = subparsers.add_parser("research-intraday-family-bounds", help="Calculate simultaneous lower bounds for every saved DEV cost-group member offline")
    parser.add_argument("--experiment", required=True, metavar="PATH")
    parser.add_argument("--cost-index", type=int, default=0)
    parser.add_argument("--block-days", type=int)
    parser.add_argument("--replications", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=0)


def research_intraday_family_bounds_main(args) -> int:
    try:
        report = analyze_intraday_family_bounds(load_strategy_experiment(args.experiment),
            cost_index=args.cost_index, block_days=args.block_days, replications=args.replications, seed=args.seed)
        print(json.dumps({"result_schema_version": INTRADAY_FAMILY_BOUNDS_VERSION, "status": "SUCCESS", "report": report},
                         ensure_ascii=True, allow_nan=False))
        return 0
    except (OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_FAMILY_BOUNDS_VERSION, "status": "FAILED", "error": str(exc)},
                         ensure_ascii=True), file=sys.stderr)
        return 1
