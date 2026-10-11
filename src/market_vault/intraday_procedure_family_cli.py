"""Settings-independent complete Q25/Q31/Q36 procedure-family bounds."""

from __future__ import annotations

import json
import sys

from .dataset.cli import DatasetCLIError
from .research.intraday_procedure_comparison import _parameters
from .research.intraday_procedure_family import (
    INTRADAY_PROCEDURE_FAMILY_VERSION, analyze_intraday_procedure_family,
)
from .research.strategy_experiment import load_strategy_experiment


def add_intraday_procedure_family_subparser(subparsers):
    parser = subparsers.add_parser("research-intraday-procedure-family",
        help="Bound the complete Q25/Q31/Q36 family against its identical original fixed DEV reference")
    parser.add_argument("--study", action="append", required=True, metavar="PATH",
                        help="Explicit saved study; repeat exactly three times for Q25, Q31 and Q36")
    parser.add_argument("--block-days", type=int)
    parser.add_argument("--replications", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=0)


def research_intraday_procedure_family_main(args) -> int:
    try:
        _parameters(args.block_days, args.replications, args.seed)
        if type(args.study) is not list or len(args.study) != 3:
            raise ValueError("exactly three --study paths are required for Q25, Q31 and Q36")
        snapshots = [load_strategy_experiment(path) for path in args.study]
        report = analyze_intraday_procedure_family(snapshots, block_days=args.block_days,
                                                   replications=args.replications, seed=args.seed)
        print(json.dumps({"result_schema_version": INTRADAY_PROCEDURE_FAMILY_VERSION,
                          "status": "SUCCESS", "report": report}, ensure_ascii=True, allow_nan=False))
        return 0
    except (DatasetCLIError, OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_PROCEDURE_FAMILY_VERSION,
                          "status": "FAILED", "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1
