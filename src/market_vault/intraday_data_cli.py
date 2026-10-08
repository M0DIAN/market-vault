"""Offline build and full source verification of one explicit intraday data file."""

from __future__ import annotations

import json
import sys

from .research.intraday_data import (
    build_intraday_dataset, intraday_summary, load_intraday_dataset,
    parse_json, write_intraday_dataset,
)
from .dataset.cli import DatasetCLIError, _coerce_plan_path


INTRADAY_DATA_CLI_VERSION = "market-vault-intraday-data-cli-result-v1"


def add_intraday_data_subparsers(subparsers):
    build = subparsers.add_parser("research-intraday-build", help="Build independent intraday observations, prices and targets")
    build.add_argument("--plan", required=True, metavar="PATH")
    build.add_argument("--output", required=True, metavar="PATH")
    inspect = subparsers.add_parser("research-intraday-inspect", help="Verify an intraday data file against its exact sources")
    inspect.add_argument("--data", required=True, metavar="PATH")


def research_intraday_data_main(args, *, inspect=False):
    try:
        if inspect:
            snapshot = load_intraday_dataset(args.data)
            path = snapshot.path
        else:
            path = _coerce_plan_path(args.plan)
            snapshot = build_intraday_dataset(parse_json(path.read_bytes()), base=path.parent)
            path = write_intraday_dataset(snapshot, path=args.output)
        print(json.dumps({"result_schema_version": INTRADAY_DATA_CLI_VERSION, "status": "SUCCESS",
                          "data_path": str(path), "summary": intraday_summary(snapshot),
                          "data": snapshot.as_dict()}, ensure_ascii=False, allow_nan=False, indent=2))
        return 0
    except (DatasetCLIError, OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_DATA_CLI_VERSION,
                          "status": "FAILED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
