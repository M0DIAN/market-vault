"""Settings-independent descriptive analytics for existing intraday files."""

from __future__ import annotations

import json
import sys

from .research.intraday_performance import INTRADAY_PERFORMANCE_VERSION, analyze_intraday_experiment
from .research.strategy_experiment import load_strategy_experiment


def add_intraday_performance_subparser(subparsers):
    parser = subparsers.add_parser("research-intraday-performance", help="Analyze one saved intraday candidate without fitting or source reads")
    parser.add_argument("--experiment", required=True, metavar="PATH")
    parser.add_argument("--cost-index", type=int, default=0)
    parser.add_argument("--candidate-index", type=int, default=0)


def research_intraday_performance_main(args) -> int:
    try:
        report = analyze_intraday_experiment(load_strategy_experiment(args.experiment),
                                            cost_index=args.cost_index, candidate_index=args.candidate_index)
        print(json.dumps({"result_schema_version": INTRADAY_PERFORMANCE_VERSION, "status": "SUCCESS", "report": report},
                         ensure_ascii=False, allow_nan=False))
        return 0
    except (OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_PERFORMANCE_VERSION, "status": "FAILED", "error": str(exc)},
                         ensure_ascii=False), file=sys.stderr)
        return 1
