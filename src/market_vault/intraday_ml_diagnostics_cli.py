"""Settings-independent diagnostics for saved fixed and selected intraday ML."""

from __future__ import annotations

import json
import sys

from .dataset.cli import DatasetCLIError
from .research.intraday_ml_diagnostics import (
    INTRADAY_ML_PREDICTION_QUALITY_VERSION, analyze_intraday_ml_prediction_quality,
)
from .research.strategy_experiment import load_strategy_experiment


def add_intraday_ml_diagnostics_subparser(subparsers):
    parser = subparsers.add_parser("research-intraday-ml-prediction-quality",
        help="Verify fixed or Q25/Q31 outer ML forecasts and describe five fixed score intervals")
    parser.add_argument("--experiment", required=True, metavar="PATH")
    parser.add_argument("--cost-index", type=int, default=0)
    parser.add_argument("--candidate-index", type=int, default=0)
    parser.add_argument("--intraday-data", metavar="PATH", help="Relocated Q5 source with the same data identity")


def research_intraday_ml_diagnostics_main(args) -> int:
    try:
        report = analyze_intraday_ml_prediction_quality(load_strategy_experiment(args.experiment),
            cost_index=args.cost_index, candidate_index=args.candidate_index, intraday_data_file=args.intraday_data)
        print(json.dumps({"result_schema_version": INTRADAY_ML_PREDICTION_QUALITY_VERSION,
                          "status": "SUCCESS", "report": report}, ensure_ascii=True, allow_nan=False))
        return 0
    except (DatasetCLIError, OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_ML_PREDICTION_QUALITY_VERSION,
                          "status": "FAILED", "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1
