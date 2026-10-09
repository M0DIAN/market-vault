"""Settings-independent comparison of two explicit saved intraday files."""

from __future__ import annotations

import json
import sys

from .research.intraday_saved_comparison import INTRADAY_SAVED_COMPARISON_VERSION, compare_saved_intraday_experiments
from .research.strategy_experiment import load_strategy_experiment


def add_intraday_saved_comparison_subparser(subparsers):
    parser = subparsers.add_parser("research-intraday-compare-saved", help="Describe two saved intraday selections offline")
    for side in ("left", "right"):
        parser.add_argument("--" + side, required=True, metavar="PATH")
        parser.add_argument("--" + side + "-cost-index", type=int, default=0)
        parser.add_argument("--" + side + "-candidate-index", type=int, default=0)


def research_intraday_saved_comparison_main(args) -> int:
    try:
        report = compare_saved_intraday_experiments(load_strategy_experiment(args.left), load_strategy_experiment(args.right),
            left_cost_index=args.left_cost_index, left_candidate_index=args.left_candidate_index,
            right_cost_index=args.right_cost_index, right_candidate_index=args.right_candidate_index)
        print(json.dumps({"result_schema_version": INTRADAY_SAVED_COMPARISON_VERSION, "status": "SUCCESS", "report": report},
                         ensure_ascii=False, allow_nan=False))
        return 0
    except (OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_SAVED_COMPARISON_VERSION, "status": "FAILED", "error": str(exc)},
                         ensure_ascii=False), file=sys.stderr)
        return 1
