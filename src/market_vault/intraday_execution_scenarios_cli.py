"""Explicit finite execution scenarios and offline export of one Q7 child."""

from __future__ import annotations

import json
import sys

from .dataset.cli import DatasetCLIError, _coerce_plan_path
from .research.intraday_data import parse_json
from .research.intraday_execution_scenarios import extract_intraday_execution_scenario, run_intraday_execution_scenarios
from .research.strategy_experiment import load_strategy_experiment, write_strategy_experiment


INTRADAY_EXECUTION_SCENARIOS_CLI_VERSION = "market-vault-intraday-execution-scenarios-cli-result-v1"


def add_intraday_execution_scenarios_subparsers(subparsers):
    run = subparsers.add_parser("research-intraday-scenarios", help="Evaluate finite explicit DEV execution policies on one common context")
    run.add_argument("--plan", required=True, metavar="PATH")
    run.add_argument("--experiment", metavar="PATH", help="Save the entire immutable collection")
    run.add_argument("--name", default="")
    run.add_argument("--notes", default="")
    export = subparsers.add_parser("research-intraday-export-scenario", help="Export one explicitly bound ordinary Q7 experiment without source access")
    export.add_argument("--experiment", required=True, metavar="PATH", help="Saved collection")
    export.add_argument("--expected-experiment-id", required=True)
    export.add_argument("--scenario-index", required=True, type=int)
    export.add_argument("--expected-child-experiment-id", required=True)
    export.add_argument("--output", required=True, metavar="PATH")


def research_intraday_execution_scenarios_main(args, *, command: str) -> int:
    try:
        if command == "research-intraday-scenarios":
            if (args.name or args.notes) and args.experiment is None:
                raise ValueError("--name/--notes require --experiment")
            path = _coerce_plan_path(args.plan)
            snapshot = run_intraday_execution_scenarios(parse_json(path.read_bytes()), base=path.parent,
                                                       name=args.name, notes=args.notes)
            payload, destination = {"collection": snapshot.as_dict()}, args.experiment
        else:
            collection = load_strategy_experiment(args.experiment)
            snapshot = extract_intraday_execution_scenario(collection, expected_experiment_id=args.expected_experiment_id,
                scenario_index=args.scenario_index, expected_child_experiment_id=args.expected_child_experiment_id)
            payload = {"source_experiment_id": collection.experiment_id, "scenario_index": args.scenario_index,
                       "child_experiment_id": snapshot.experiment_id}
            destination = args.output
        if destination is not None:
            result = write_strategy_experiment(snapshot, path=destination)
            payload["experiment"] = {"path": str(result.path), "experiment_id": result.experiment_id,
                                     "created_new_file": result.created_new_file}
        print(json.dumps({"result_schema_version": INTRADAY_EXECUTION_SCENARIOS_CLI_VERSION,
                          "status": "SUCCESS", **payload}, ensure_ascii=False, allow_nan=False))
        return 0
    except (DatasetCLIError, OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_EXECUTION_SCENARIOS_CLI_VERSION,
                          "status": "FAILED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
