"""Settings-independent selected Ridge forecast quality from verified Q5 data."""

from __future__ import annotations

import json
import sys

from .dataset.cli import DatasetCLIError
from .research.intraday_prediction_quality import (
    INTRADAY_PREDICTION_QUALITY_VERSION, _index, analyze_intraday_prediction_quality,
)
from .research.strategy_experiment import load_strategy_experiment


def add_intraday_prediction_quality_subparser(subparsers):
    parser = subparsers.add_parser("research-intraday-prediction-quality",
                                  help="Reconstruct one saved DEV Ridge and describe its out-of-fold forecast quality")
    parser.add_argument("--experiment", required=True, metavar="PATH")
    parser.add_argument("--cost-index", type=int, default=0)
    parser.add_argument("--candidate-index", type=int, default=0)
    parser.add_argument("--intraday-data", metavar="PATH", help="Relocated Q5 source; its data identity must match")


def research_intraday_prediction_quality_main(args) -> int:
    try:
        _index(args.cost_index, "cost_index")
        _index(args.candidate_index, "candidate_index")
        report = analyze_intraday_prediction_quality(load_strategy_experiment(args.experiment),
            cost_index=args.cost_index, candidate_index=args.candidate_index, intraday_data_file=args.intraday_data)
        print(json.dumps({"result_schema_version": INTRADAY_PREDICTION_QUALITY_VERSION,
                          "status": "SUCCESS", "report": report}, ensure_ascii=True, allow_nan=False))
        return 0
    except (DatasetCLIError, OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_PREDICTION_QUALITY_VERSION,
                          "status": "FAILED", "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1
