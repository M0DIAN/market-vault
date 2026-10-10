"""Offline entry to fixed-model inner economic threshold selection."""

from __future__ import annotations

from dataclasses import asdict
import json
import sys

from .dataset.cli import DatasetCLIError
from .research.intraday_threshold_selection import run_intraday_threshold_selection
from .research.strategy_experiment import write_strategy_experiment


INTRADAY_THRESHOLD_SELECTION_CLI_VERSION = "market-vault-intraday-threshold-selection-cli-result-v1"


def add_intraday_threshold_selection_subparser(subparsers):
    parser = subparsers.add_parser("research-intraday-threshold-selection",
        help="Select among four fixed return thresholds using historical inner Q6 net accounts")
    parser.add_argument("--source-experiment", required=True, metavar="PATH")
    parser.add_argument("--expected-experiment-id", required=True)
    parser.add_argument("--cost-index", required=True, type=int)
    parser.add_argument("--candidate-index", required=True, type=int)
    parser.add_argument("--expected-candidate-id", required=True)
    parser.add_argument("--intraday-data", metavar="PATH", help="Explicit relocated Q5; its data ID must match")
    parser.add_argument("--experiment", metavar="PATH", help="Exclusively save the complete new study")
    parser.add_argument("--name", default=None)
    parser.add_argument("--notes", default=None)


def research_intraday_threshold_selection_main(args) -> int:
    try:
        if not args.experiment and (args.name is not None or args.notes is not None):
            raise ValueError("--name/--notes require --experiment")
        snapshot = run_intraday_threshold_selection(args.source_experiment,
            expected_experiment_id=args.expected_experiment_id, cost_index=args.cost_index,
            candidate_index=args.candidate_index, expected_candidate_id=args.expected_candidate_id,
            intraday_data_file=args.intraday_data, name=args.name or "", notes=args.notes or "")
        result = {"result_schema_version": INTRADAY_THRESHOLD_SELECTION_CLI_VERSION, "status": "SUCCESS", "study": snapshot.as_dict()}
        if args.experiment:
            saved = asdict(write_strategy_experiment(snapshot, path=args.experiment))
            result["experiment"] = {**saved, "path": str(saved["path"])}
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        return 0
    except (DatasetCLIError, OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_THRESHOLD_SELECTION_CLI_VERSION,
                          "status": "FAILED", "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1
