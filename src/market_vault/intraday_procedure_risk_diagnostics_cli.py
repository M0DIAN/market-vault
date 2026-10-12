"""Settings-independent risk paths of one explicitly saved ML procedure."""

from __future__ import annotations

import json
import sys

from .research.intraday_procedure_risk_diagnostics import (
    INTRADAY_PROCEDURE_RISK_DIAGNOSTICS_VERSION, analyze_intraday_procedure_risk_diagnostics,
)
from .research.strategy_experiment import load_strategy_experiment


def add_intraday_procedure_risk_diagnostics_subparser(subparsers):
    parser = subparsers.add_parser("research-intraday-procedure-risk-diagnostics",
        help="Describe the recorded outer risk paths of a saved Q25/Q31/Q36 procedure")
    parser.add_argument("--study", required=True, metavar="PATH", help="Explicit saved Q25/Q31/Q36 study")


def research_intraday_procedure_risk_diagnostics_main(args) -> int:
    try:
        report = analyze_intraday_procedure_risk_diagnostics(load_strategy_experiment(args.study))
        print(json.dumps({"result_schema_version": INTRADAY_PROCEDURE_RISK_DIAGNOSTICS_VERSION,
                          "status": "SUCCESS", "report": report}, ensure_ascii=False, allow_nan=False))
        return 0
    except (OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_PROCEDURE_RISK_DIAGNOSTICS_VERSION,
                          "status": "FAILED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
