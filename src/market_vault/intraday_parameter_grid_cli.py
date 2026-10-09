"""Settings-independent descriptions of saved finite DEV parameter grids."""

from __future__ import annotations

import json
import sys

from .research.intraday_parameter_grid import INTRADAY_PARAMETER_GRID_VERSION, analyze_intraday_parameter_grid
from .research.strategy_experiment import load_strategy_experiment


def add_intraday_parameter_grid_subparser(subparsers):
    parser = subparsers.add_parser("research-intraday-parameter-grid", help="Describe one saved DEV parameter grid without new evaluations")
    parser.add_argument("--experiment", required=True, metavar="PATH")
    parser.add_argument("--cost-index", type=int, default=0)
    parser.add_argument("--center-candidate-index", type=int, default=0)
    parser.add_argument("--metric", default="total_return")


def research_intraday_parameter_grid_main(args) -> int:
    try:
        report = analyze_intraday_parameter_grid(load_strategy_experiment(args.experiment),
            cost_index=args.cost_index, center_candidate_index=args.center_candidate_index, metric=args.metric)
        print(json.dumps({"result_schema_version": INTRADAY_PARAMETER_GRID_VERSION, "status": "SUCCESS", "report": report},
                         ensure_ascii=False, allow_nan=False))
        return 0
    except (OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_PARAMETER_GRID_VERSION, "status": "FAILED", "error": str(exc)},
                         ensure_ascii=False), file=sys.stderr)
        return 1
