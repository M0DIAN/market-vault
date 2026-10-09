"""Settings-independent sequential selection from one saved DEV family."""

from __future__ import annotations

import json
import sys

from .research.intraday_sequential_selection import (
    INTRADAY_SEQUENTIAL_SELECTION_VERSION, _integer, analyze_intraday_sequential_selection,
)
from .research.strategy_experiment import load_strategy_experiment


def add_intraday_sequential_selection_subparser(subparsers):
    parser = subparsers.add_parser("research-intraday-sequential-selection", help="Evaluate a fixed historical selection rule on subsequent saved DEV folds offline")
    parser.add_argument("--experiment", required=True, metavar="PATH")
    parser.add_argument("--cost-index", type=int, default=0)
    parser.add_argument("--minimum-history-days", type=int, default=20)


def research_intraday_sequential_selection_main(args) -> int:
    try:
        _integer(args.cost_index, "cost_index", 0)
        _integer(args.minimum_history_days, "minimum_history_days", 1)
        report = analyze_intraday_sequential_selection(load_strategy_experiment(args.experiment),
            cost_index=args.cost_index, minimum_history_days=args.minimum_history_days)
        print(json.dumps({"result_schema_version": INTRADAY_SEQUENTIAL_SELECTION_VERSION, "status": "SUCCESS", "report": report},
                         ensure_ascii=True, allow_nan=False))
        return 0
    except (OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_SEQUENTIAL_SELECTION_VERSION, "status": "FAILED", "error": str(exc)},
                         ensure_ascii=True), file=sys.stderr)
        return 1
