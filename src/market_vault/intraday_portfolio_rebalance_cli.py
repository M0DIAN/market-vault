"""Settings-independent daily target cash reallocation of two saved accounts."""

from __future__ import annotations

import json
import sys

from .research.intraday_portfolio import _allocation, _integer
from .research.intraday_portfolio_rebalance import INTRADAY_PORTFOLIO_REBALANCE_VERSION, analyze_intraday_portfolio_rebalance
from .research.strategy_experiment import load_strategy_experiment


def add_intraday_portfolio_rebalance_subparser(subparsers):
    parser = subparsers.add_parser("research-intraday-portfolio-rebalance", help="Describe daily target cash reallocation of two saved DEV strategies offline")
    for side in ("left", "right"):
        parser.add_argument("--" + side, required=True, metavar="PATH")
        parser.add_argument("--" + side + "-cost-index", type=int, default=0)
        parser.add_argument("--" + side + "-candidate-index", type=int, default=0)
    parser.add_argument("--weight-a", type=float, default=.5)
    parser.add_argument("--weight-b", type=float, default=.5)


def research_intraday_portfolio_rebalance_main(args) -> int:
    try:
        _allocation(args.weight_a, args.weight_b)
        for name in ("left_cost_index", "left_candidate_index", "right_cost_index", "right_candidate_index"):
            _integer(getattr(args, name), name, 0)
        report = analyze_intraday_portfolio_rebalance(load_strategy_experiment(args.left), load_strategy_experiment(args.right),
            left_cost_index=args.left_cost_index, left_candidate_index=args.left_candidate_index,
            right_cost_index=args.right_cost_index, right_candidate_index=args.right_candidate_index,
            weight_a=args.weight_a, weight_b=args.weight_b)
        print(json.dumps({"result_schema_version": INTRADAY_PORTFOLIO_REBALANCE_VERSION, "status": "SUCCESS", "report": report},
                         ensure_ascii=True, allow_nan=False))
        return 0
    except (OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_PORTFOLIO_REBALANCE_VERSION, "status": "FAILED", "error": str(exc)},
                         ensure_ascii=True), file=sys.stderr)
        return 1
