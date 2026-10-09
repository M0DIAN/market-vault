"""Settings-independent risk descriptions of one explicit saved experiment."""

from __future__ import annotations

import json
import sys

from .research.intraday_risk_diagnostics import INTRADAY_RISK_DIAGNOSTICS_VERSION, analyze_intraday_risk_diagnostics
from .research.strategy_experiment import load_strategy_experiment


def add_intraday_risk_diagnostics_subparser(subparsers):
    parser = subparsers.add_parser("research-intraday-risk-diagnostics", help="Describe saved intraday risk paths, distributions and folds offline")
    parser.add_argument("--experiment", required=True, metavar="PATH")
    parser.add_argument("--cost-index", type=int, default=0)
    parser.add_argument("--candidate-index", type=int, default=0)


def research_intraday_risk_diagnostics_main(args) -> int:
    try:
        report = analyze_intraday_risk_diagnostics(load_strategy_experiment(args.experiment),
            cost_index=args.cost_index, candidate_index=args.candidate_index)
        print(json.dumps({"result_schema_version": INTRADAY_RISK_DIAGNOSTICS_VERSION, "status": "SUCCESS", "report": report},
                         ensure_ascii=False, allow_nan=False))
        return 0
    except (OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_RISK_DIAGNOSTICS_VERSION, "status": "FAILED", "error": str(exc)},
                         ensure_ascii=False), file=sys.stderr)
        return 1
