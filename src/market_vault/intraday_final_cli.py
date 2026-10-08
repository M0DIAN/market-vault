"""Settings-independent explicit intraday selection and final TEST commands."""

from __future__ import annotations

import json
import sys

from .dataset.cli import DatasetCLIError
from .research.intraday_final_test import (
    create_intraday_test_experiment, freeze_intraday_candidate, run_intraday_final_test,
)
from .research.strategy_experiment import load_strategy_experiment, write_strategy_experiment


INTRADAY_FINAL_CLI_VERSION = "market-vault-intraday-final-cli-result-v1"


def add_intraday_final_subparsers(subparsers):
    freeze = subparsers.add_parser("research-intraday-freeze", help="Freeze one explicit candidate from a saved intraday development experiment")
    freeze.add_argument("--source-experiment", required=True, metavar="PATH")
    freeze.add_argument("--expected-experiment-id", required=True)
    freeze.add_argument("--cost-index", required=True)
    freeze.add_argument("--candidate-index", required=True)
    freeze.add_argument("--expected-candidate-id", required=True)
    freeze.add_argument("--experiment", required=True, metavar="PATH")
    test = subparsers.add_parser("research-intraday-test", help="Evaluate one frozen candidate on independent TEST with execution V2")
    test.add_argument("--selection", required=True, metavar="PATH")
    test.add_argument("--source-experiment-file", metavar="PATH", help="Relocated development experiment; frozen identity must match")
    test.add_argument("--intraday-data-file", metavar="PATH", help="Relocated Q5 file; frozen data identity must match")
    test.add_argument("--experiment", metavar="PATH")
    for parser in (freeze, test):
        parser.add_argument("--name", default="")
        parser.add_argument("--notes", default="")


def research_intraday_final_main(args, *, command: str) -> int:
    try:
        if (args.name or args.notes) and args.experiment is None:
            raise ValueError("--name/--notes require --experiment")
        if command == "research-intraday-freeze":
            snapshot = freeze_intraday_candidate(args.source_experiment, expected_experiment_id=args.expected_experiment_id,
                cost_index=int(args.cost_index), candidate_index=int(args.candidate_index), expected_candidate_id=args.expected_candidate_id,
                name=args.name, notes=args.notes)
            payload = {"selection": snapshot.as_dict()}
        else:
            selection = load_strategy_experiment(args.selection)
            report = run_intraday_final_test(selection, source_experiment_file=args.source_experiment_file,
                                              intraday_data_file=args.intraday_data_file)
            payload = {"report": report}
            snapshot = create_intraday_test_experiment(selection, report, name=args.name, notes=args.notes) if args.experiment else None
        if args.experiment is not None:
            written = write_strategy_experiment(snapshot, path=args.experiment)
            payload["experiment"] = {"path": str(written.path), "experiment_id": written.experiment_id,
                                     "created_new_file": written.created_new_file}
        print(json.dumps({"result_schema_version": INTRADAY_FINAL_CLI_VERSION, "status": "SUCCESS", **payload},
                         ensure_ascii=False, allow_nan=False))
        return 0
    except (DatasetCLIError, OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_FINAL_CLI_VERSION, "status": "FAILED", "error": str(exc)},
                         ensure_ascii=False), file=sys.stderr)
        return 1
