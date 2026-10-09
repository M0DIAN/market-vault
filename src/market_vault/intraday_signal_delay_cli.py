"""Settings-independent signal-delay stress from one saved DEV result."""

from __future__ import annotations

import json
import sys

from .research.intraday_signal_delay import (
    INTRADAY_SIGNAL_DELAY_VERSION, _integer, analyze_intraday_signal_delay,
)
from .research.strategy_experiment import load_strategy_experiment


def add_intraday_signal_delay_subparser(subparsers):
    parser = subparsers.add_parser("research-intraday-signal-delay", help="Re-execute saved DEV signals at fixed 0/1/2-bar delays offline")
    parser.add_argument("--experiment", required=True, metavar="PATH")
    parser.add_argument("--cost-index", type=int, default=0)
    parser.add_argument("--candidate-index", type=int, default=0)


def research_intraday_signal_delay_main(args) -> int:
    try:
        _integer(args.cost_index, "cost_index", 0)
        _integer(args.candidate_index, "candidate_index", 0)
        report = analyze_intraday_signal_delay(load_strategy_experiment(args.experiment),
                                              cost_index=args.cost_index, candidate_index=args.candidate_index)
        print(json.dumps({"result_schema_version": INTRADAY_SIGNAL_DELAY_VERSION, "status": "SUCCESS", "report": report},
                         ensure_ascii=True, allow_nan=False))
        return 0
    except (OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_SIGNAL_DELAY_VERSION, "status": "FAILED", "error": str(exc)},
                         ensure_ascii=True), file=sys.stderr)
        return 1
