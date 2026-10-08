"""Offline single-strategy intraday execution V2 CLI."""

from __future__ import annotations

import json
import sys

from .dataset.cli import DatasetCLIError, _coerce_plan_path
from .research.intraday_data import parse_json
from .research.intraday_backtest import INTRADAY_BACKTEST_RESULT_VERSION, run_intraday_backtest


def add_intraday_backtest_subparser(subparsers) -> None:
    parser = subparsers.add_parser("research-intraday-backtest", help="Run one rule through intraday execution V2")
    parser.add_argument("--plan", required=True, metavar="PATH")


def research_intraday_backtest_main(args) -> int:
    try:
        path = _coerce_plan_path(args.plan)
        result = run_intraday_backtest(parse_json(path.read_bytes()), base=path.parent)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
        return 0
    except (DatasetCLIError, OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_BACKTEST_RESULT_VERSION,
                          "status": "FAILED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
