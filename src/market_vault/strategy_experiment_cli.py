"""Settings-independent explicit experiment Open and Replay commands."""

from __future__ import annotations

import json
import sys

from .research.strategy_experiment import load_strategy_experiment, replay_strategy_experiment
from .dataset.cli import DatasetCLIError


STRATEGY_EXPERIMENT_CLI_VERSION = "market-vault-strategy-experiment-cli-result-v1"
STRATEGY_EXPERIMENT_CLI_V2_VERSION = "market-vault-strategy-experiment-cli-result-v2"
STRATEGY_EXPERIMENT_CLI_V3_VERSION = "market-vault-strategy-experiment-cli-result-v3"


def add_strategy_experiment_subparsers(subparsers) -> None:
    opened = subparsers.add_parser("research-experiment-open", help="View one saved experiment without loading its Dataset")
    opened.add_argument("--experiment", required=True, metavar="PATH")
    replay = subparsers.add_parser("research-experiment-replay", help="Verify the Dataset and reproduce the complete saved result")
    replay.add_argument("--experiment", required=True, metavar="PATH")
    replay.add_argument("--dataset-build-dir", metavar="PATH", help="Explicit relocated Dataset directory; ID must match")
    replay.add_argument("--intraday-data-file", metavar="PATH", help="Explicit relocated intraday file; data ID must match")
    replay.add_argument("--source-experiment-file", metavar="PATH", help="Explicit relocated development experiment for a frozen intraday selection/TEST")


def research_experiment_main(args, *, replay: bool = False) -> int:
    version = STRATEGY_EXPERIMENT_CLI_VERSION
    try:
        snapshot = load_strategy_experiment(args.experiment)
        if snapshot.as_dict()["evaluation_mode"] == "DIAGNOSTICS":
            version = STRATEGY_EXPERIMENT_CLI_V2_VERSION
        if snapshot.as_dict()["evaluation_mode"].startswith("INTRADAY_"):
            version = STRATEGY_EXPERIMENT_CLI_V3_VERSION
        payload = (replay_strategy_experiment(snapshot, dataset_build_dir=getattr(args, "dataset_build_dir", None),
                                              intraday_data_file=getattr(args, "intraday_data_file", None),
                                              source_experiment_file=getattr(args, "source_experiment_file", None))
                   if replay else {"experiment": snapshot.as_dict()})
        print(json.dumps({"result_schema_version": version,
                          "status": "SUCCESS", **payload}, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (DatasetCLIError, OSError, TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": version,
                          "status": "FAILED", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
