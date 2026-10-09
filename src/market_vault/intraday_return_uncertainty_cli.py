"""Settings-independent paired mean intervals from one saved DEV experiment."""

from __future__ import annotations

import json
import sys

from .research.intraday_return_uncertainty import (
    INTRADAY_RETURN_UNCERTAINTY_VERSION, analyze_intraday_return_uncertainty,
)
from .research.strategy_experiment import load_strategy_experiment


def add_intraday_return_uncertainty_subparser(subparsers):
    parser = subparsers.add_parser("research-intraday-return-uncertainty", help="Calculate paired saved DEV daily-mean intervals offline")
    parser.add_argument("--experiment", required=True, metavar="PATH")
    parser.add_argument("--cost-index", type=int, default=0)
    parser.add_argument("--candidate-index", type=int, default=0)
    parser.add_argument("--block-days", type=int)
    parser.add_argument("--replications", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=0)


def research_intraday_return_uncertainty_main(args) -> int:
    try:
        report = analyze_intraday_return_uncertainty(load_strategy_experiment(args.experiment),
            cost_index=args.cost_index, candidate_index=args.candidate_index, block_days=args.block_days,
            replications=args.replications, seed=args.seed)
        print(json.dumps({"result_schema_version": INTRADAY_RETURN_UNCERTAINTY_VERSION, "status": "SUCCESS", "report": report},
                         ensure_ascii=True, allow_nan=False))
        return 0
    except (OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_RETURN_UNCERTAINTY_VERSION, "status": "FAILED", "error": str(exc)},
                         ensure_ascii=True), file=sys.stderr)
        return 1
