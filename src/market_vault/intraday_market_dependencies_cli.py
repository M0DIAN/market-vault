"""Settings-independent Q5 Feature and target dependency evidence."""

from __future__ import annotations

import json
import sys

from .dataset.cli import DatasetCLIError
from .lifecycle import LifecycleLockError
from .quality.market_data_comparison import write_market_data_json
from .research.intraday_market_dependencies import INTRADAY_MARKET_DEPENDENCIES_VERSION, run_intraday_market_dependencies
from .storage.atomic_file import AtomicFilePublicationError


def add_intraday_market_dependencies_subparser(subparsers) -> None:
    parser = subparsers.add_parser("research-intraday-market-dependencies",
        help="Map every Q5 Feature window and actual target dependency to explicit market evidence")
    parser.add_argument("--data", required=True, metavar="PATH", help="Explicit Q5 intraday data file")
    parser.add_argument("--manifest", required=True, metavar="PATH", help="Existing Q46 source/basis/reference plan")
    parser.add_argument("--output", required=True, metavar="NEW_PATH", help="New immutable dependency report")


def research_intraday_market_dependencies_main(args) -> int:
    try:
        report = run_intraday_market_dependencies(args.data, args.manifest)
        output = write_market_data_json(args.output, report)
        print(json.dumps({"result_schema_version": INTRADAY_MARKET_DEPENDENCIES_VERSION,
                          "status": "SUCCESS", "output": str(output), "report": report},
                         ensure_ascii=True, allow_nan=False))
        return 0
    except AtomicFilePublicationError as exc:
        print(json.dumps({"result_schema_version": INTRADAY_MARKET_DEPENDENCIES_VERSION,
                          "status": "FAILED", "error": str(exc), "published": exc.published},
                         ensure_ascii=True), file=sys.stderr)
        return 1
    except (DatasetCLIError, OSError, TypeError, ValueError, KeyError, ArithmeticError,
            RecursionError, LifecycleLockError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_MARKET_DEPENDENCIES_VERSION,
                          "status": "FAILED", "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1
