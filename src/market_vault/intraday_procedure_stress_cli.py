"""Settings-independent fixed-decision stress for one saved ML procedure."""

from __future__ import annotations

import json
import sys

from .dataset.cli import DatasetCLIError
from .research.intraday_procedure_stress import (
    INTRADAY_PROCEDURE_STRESS_VERSION, analyze_intraday_procedure_stress,
)
from .research.strategy_experiment import load_strategy_experiment


def add_intraday_procedure_stress_subparser(subparsers):
    parser = subparsers.add_parser("research-intraday-procedure-stress",
        help="Stress one saved Q25/Q31/Q36 outer procedure on the fixed nine-cell cost/delay grid")
    parser.add_argument("--study", required=True, metavar="PATH", help="Explicit AVAILABLE saved Q25/Q31/Q36 study")


def research_intraday_procedure_stress_main(args) -> int:
    try:
        report = analyze_intraday_procedure_stress(load_strategy_experiment(args.study))
        print(json.dumps({"result_schema_version": INTRADAY_PROCEDURE_STRESS_VERSION,
                          "status": "SUCCESS", "report": report}, ensure_ascii=True, allow_nan=False))
        return 0
    except (DatasetCLIError, OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_PROCEDURE_STRESS_VERSION,
                          "status": "FAILED", "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1
