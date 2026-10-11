"""Settings-independent diagnostics for saved fixed and selected intraday ML."""

from __future__ import annotations

import json
import sys

from .dataset.cli import DatasetCLIError
from .research.intraday_ml_diagnostics import (
    INTRADAY_ML_PREDICTION_QUALITY_VERSION, analyze_intraday_ml_prediction_quality,
)
from .research.intraday_inner_objective_sensitivity import (
    INTRADAY_INNER_OBJECTIVE_SENSITIVITY_VERSION, analyze_intraday_inner_objective_sensitivity,
)
from .research.intraday_procedure_return_uncertainty import (
    INTRADAY_PROCEDURE_RETURN_UNCERTAINTY_VERSION, analyze_intraday_procedure_return_uncertainty,
)
from .research.strategy_experiment import load_strategy_experiment


def add_intraday_ml_diagnostics_subparser(subparsers):
    parser = subparsers.add_parser("research-intraday-ml-prediction-quality",
        help="Verify fixed or Q25/Q31/Q36 outer ML forecasts and describe five fixed score intervals")
    parser.add_argument("--experiment", required=True, metavar="PATH")
    parser.add_argument("--cost-index", type=int, default=0)
    parser.add_argument("--candidate-index", type=int, default=0)
    parser.add_argument("--intraday-data", metavar="PATH", help="Relocated Q5 source with the same data identity")
    sensitivity = subparsers.add_parser("research-intraday-inner-objective-sensitivity",
        help="Describe fixed-fit single-day objective sensitivity of a saved Q25/Q31/Q36 study without source access")
    sensitivity.add_argument("--experiment", required=True, metavar="PATH")
    returns = subparsers.add_parser("research-intraday-procedure-return-uncertainty",
        help="Describe selected-procedure outer daily increments and paired intervals from a saved Q25/Q31/Q36 study")
    returns.add_argument("--experiment", required=True, metavar="PATH")
    returns.add_argument("--block-days", type=int)
    returns.add_argument("--replications", type=int, default=5000)
    returns.add_argument("--seed", type=int, default=0)


def research_intraday_ml_diagnostics_main(args) -> int:
    sensitivity = args.command == "research-intraday-inner-objective-sensitivity"
    returns = args.command == "research-intraday-procedure-return-uncertainty"
    version = (INTRADAY_PROCEDURE_RETURN_UNCERTAINTY_VERSION if returns else
               INTRADAY_INNER_OBJECTIVE_SENSITIVITY_VERSION if sensitivity else INTRADAY_ML_PREDICTION_QUALITY_VERSION)
    try:
        if returns:
            from .research.intraday_return_uncertainty import _integer
            if args.block_days is not None:
                _integer(args.block_days, "block_days", 2)
            _integer(args.replications, "replications", 1000, 20000)
            _integer(args.seed, "seed", 0, 2 ** 32 - 1)
        snapshot = load_strategy_experiment(args.experiment)
        report = (analyze_intraday_procedure_return_uncertainty(snapshot, block_days=args.block_days,
                     replications=args.replications, seed=args.seed) if returns else
            analyze_intraday_inner_objective_sensitivity(snapshot) if sensitivity else
            analyze_intraday_ml_prediction_quality(snapshot, cost_index=args.cost_index,
                candidate_index=args.candidate_index, intraday_data_file=args.intraday_data))
        print(json.dumps({"result_schema_version": version,
                          "status": "SUCCESS", "report": report}, ensure_ascii=True, allow_nan=False))
        return 0
    except (DatasetCLIError, OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": version,
                          "status": "FAILED", "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1
