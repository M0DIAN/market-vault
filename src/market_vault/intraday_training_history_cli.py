"""Settings-independent fixed-recipe training-history sensitivity command."""

from __future__ import annotations

import json
import sys

from .dataset.cli import DatasetCLIError
from .research.intraday_prediction_quality import _index
from .research.intraday_training_history import INTRADAY_TRAINING_HISTORY_VERSION, analyze_intraday_training_history
from .research.strategy_experiment import load_strategy_experiment


def add_intraday_training_history_subparser(subparsers):
    parser = subparsers.add_parser("research-intraday-training-history",
                                  help="Compare expanding and fixed recent histories for a saved DEV Ridge recipe")
    parser.add_argument("--experiment", required=True, metavar="PATH")
    parser.add_argument("--cost-index", type=int, default=0)
    parser.add_argument("--candidate-index", type=int, default=0)
    parser.add_argument("--intraday-data", metavar="PATH", help="Relocated Q5 source; its data identity must match")


def research_intraday_training_history_main(args) -> int:
    try:
        _index(args.cost_index, "cost_index")
        _index(args.candidate_index, "candidate_index")
        report = analyze_intraday_training_history(load_strategy_experiment(args.experiment),
            cost_index=args.cost_index, candidate_index=args.candidate_index, intraday_data_file=args.intraday_data)
        print(json.dumps({"result_schema_version": INTRADAY_TRAINING_HISTORY_VERSION,
                          "status": "SUCCESS", "report": report}, ensure_ascii=True, allow_nan=False))
        return 0
    except (DatasetCLIError, OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_TRAINING_HISTORY_VERSION,
                          "status": "FAILED", "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1
