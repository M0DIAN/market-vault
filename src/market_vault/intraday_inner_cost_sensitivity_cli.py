"""Settings-independent cost sensitivity of one saved economic procedure."""

from __future__ import annotations

import json
import sys

from .research.intraday_inner_cost_sensitivity import (
    INTRADAY_INNER_COST_SENSITIVITY_VERSION, analyze_intraday_inner_cost_sensitivity,
)
from .research.strategy_experiment import load_strategy_experiment


def add_intraday_inner_cost_sensitivity_subparser(subparsers):
    parser = subparsers.add_parser("research-intraday-inner-cost-sensitivity",
        help="Inspect +0/+5/+10 bp cost sensitivity of saved Q31/Q36 inner choices")
    parser.add_argument("--study", required=True, metavar="PATH", help="Explicit saved Q31/Q36 economic selection study")


def research_intraday_inner_cost_sensitivity_main(args) -> int:
    try:
        report = analyze_intraday_inner_cost_sensitivity(load_strategy_experiment(args.study))
        print(json.dumps({"result_schema_version": INTRADAY_INNER_COST_SENSITIVITY_VERSION,
                          "status": "SUCCESS", "report": report}, ensure_ascii=False, allow_nan=False))
        return 0
    except (OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_INNER_COST_SENSITIVITY_VERSION,
                          "status": "FAILED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
