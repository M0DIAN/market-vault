"""Settings-independent explicit experiment Open and Replay commands."""

from __future__ import annotations

import json
import sys

from .research.strategy_experiment import load_strategy_experiment, replay_strategy_experiment
from .dataset.cli import DatasetCLIError


STRATEGY_EXPERIMENT_CLI_VERSION = "market-vault-strategy-experiment-cli-result-v1"


def add_strategy_experiment_subparsers(subparsers) -> None:
    opened = subparsers.add_parser("research-experiment-open", help="View one saved experiment without loading its Dataset")
    opened.add_argument("--experiment", required=True, metavar="PATH")
    replay = subparsers.add_parser("research-experiment-replay", help="Verify the Dataset and reproduce the complete saved result")
    replay.add_argument("--experiment", required=True, metavar="PATH")
    replay.add_argument("--dataset-build-dir", metavar="PATH", help="Explicit relocated Dataset directory; ID must match")


def research_experiment_main(args, *, replay: bool = False) -> int:
    try:
        snapshot = load_strategy_experiment(args.experiment)
        payload = (replay_strategy_experiment(snapshot, dataset_build_dir=getattr(args, "dataset_build_dir", None))
                   if replay else {"experiment": snapshot.as_dict()})
        print(json.dumps({"result_schema_version": STRATEGY_EXPERIMENT_CLI_VERSION,
                          "status": "SUCCESS", **payload}, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (DatasetCLIError, OSError, TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": STRATEGY_EXPERIMENT_CLI_VERSION,
                          "status": "FAILED", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
