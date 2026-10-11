"""Settings-independent direct comparison of two saved selection procedures."""

from __future__ import annotations

import json
import sys

from .dataset.cli import DatasetCLIError
from .research.intraday_procedure_comparison import (
    INTRADAY_PROCEDURE_COMPARISON_VERSION, _parameters, compare_intraday_procedures,
)
from .research.strategy_experiment import load_strategy_experiment


def add_intraday_procedure_comparison_subparser(subparsers):
    parser = subparsers.add_parser("research-intraday-procedure-comparison",
        help="Compare two different saved Q25/Q31/Q36 procedures on their identical original DEV source")
    parser.add_argument("--left", required=True, metavar="PATH", help="Explicit procedure A")
    parser.add_argument("--right", required=True, metavar="PATH", help="Explicit procedure B; paired difference is B minus A")
    parser.add_argument("--block-days", type=int)
    parser.add_argument("--replications", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=0)


def research_intraday_procedure_comparison_main(args) -> int:
    try:
        _parameters(args.block_days, args.replications, args.seed)
        left, right = load_strategy_experiment(args.left), load_strategy_experiment(args.right)
        report = compare_intraday_procedures(left, right, block_days=args.block_days,
                                            replications=args.replications, seed=args.seed)
        print(json.dumps({"result_schema_version": INTRADAY_PROCEDURE_COMPARISON_VERSION,
                          "status": "SUCCESS", "report": report}, ensure_ascii=True, allow_nan=False))
        return 0
    except (DatasetCLIError, OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_PROCEDURE_COMPARISON_VERSION,
                          "status": "FAILED", "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1
