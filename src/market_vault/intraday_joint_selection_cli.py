"""Settings-independent joint economic selection and complete replay."""

from __future__ import annotations

from dataclasses import asdict
import json
import sys

from .dataset.cli import DatasetCLIError
from .research.intraday_joint_selection import run_intraday_joint_selection, replay_intraday_joint_selection
from .research.strategy_experiment import load_strategy_experiment, write_strategy_experiment


INTRADAY_JOINT_SELECTION_CLI_VERSION = "market-vault-intraday-joint-selection-cli-result-v1"


def add_intraday_joint_selection_subparsers(subparsers):
    parser = subparsers.add_parser("research-intraday-joint-selection",
        help="Select the fixed six-model by four-threshold family by historical inner net return")
    parser.add_argument("--source-experiment", required=True, metavar="PATH")
    parser.add_argument("--expected-experiment-id", required=True)
    parser.add_argument("--cost-index", required=True, type=int)
    parser.add_argument("--candidate-index", required=True, type=int)
    parser.add_argument("--expected-candidate-id", required=True)
    parser.add_argument("--intraday-data", metavar="PATH", help="Explicit relocated Q5; its data ID must match")
    parser.add_argument("--experiment", metavar="PATH", help="Exclusively save the complete new study")
    parser.add_argument("--name", default=None)
    parser.add_argument("--notes", default=None)
    replay = subparsers.add_parser("research-intraday-joint-selection-replay",
        help="Reconstruct a saved joint study and its complete embedded ordinary DEV source")
    replay.add_argument("--experiment", required=True, metavar="PATH")
    replay.add_argument("--intraday-data-file", metavar="PATH", help="Explicit relocated Q5 with unchanged identity")
    replay.add_argument("--source-experiment-file", metavar="PATH", help="Optional exact ordinary source replacement")


def research_intraday_joint_selection_main(args, *, command: str) -> int:
    try:
        if command == "research-intraday-joint-selection-replay":
            replay = replay_intraday_joint_selection(load_strategy_experiment(args.experiment),
                intraday_data_file=args.intraday_data_file, source_experiment_file=args.source_experiment_file)
            result = {"result_schema_version": INTRADAY_JOINT_SELECTION_CLI_VERSION, "status": "SUCCESS", "replay": replay}
        else:
            if not args.experiment and (args.name is not None or args.notes is not None):
                raise ValueError("--name/--notes require --experiment")
            snapshot = run_intraday_joint_selection(args.source_experiment,
                expected_experiment_id=args.expected_experiment_id, cost_index=args.cost_index,
                candidate_index=args.candidate_index, expected_candidate_id=args.expected_candidate_id,
                intraday_data_file=args.intraday_data, name=args.name or "", notes=args.notes or "")
            result = {"result_schema_version": INTRADAY_JOINT_SELECTION_CLI_VERSION, "status": "SUCCESS", "study": snapshot.as_dict()}
            if args.experiment:
                saved = asdict(write_strategy_experiment(snapshot, path=args.experiment))
                result["experiment"] = {**saved, "path": str(saved["path"])}
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        return 0
    except (DatasetCLIError, OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_JOINT_SELECTION_CLI_VERSION,
                          "status": "FAILED", "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1
