"""Settings-independent evidence for recorded intraday ML sample uses."""

from __future__ import annotations

import json
import sys

from .dataset.cli import DatasetCLIError
from .lifecycle import LifecycleLockError
from .quality.market_data_comparison import write_market_data_json
from .research.intraday_sample_usage import INTRADAY_SAMPLE_USAGE_VERSION, run_intraday_sample_usage
from .storage.atomic_file import AtomicFilePublicationError


def add_intraday_sample_usage_subparser(subparsers) -> None:
    parser = subparsers.add_parser("research-intraday-sample-usage",
        help="Bind recorded DEV training and scoring samples to explicit market evidence")
    parser.add_argument("--experiment", required=True, metavar="PATH", help="Saved ordinary learned DEV candidate or Q25/Q31/Q36 study")
    parser.add_argument("--manifest", required=True, metavar="PATH", help="Existing Q46 source/basis/reference plan")
    parser.add_argument("--cost-index", type=int, default=0, help="Saved ordinary cost index; zero for a procedure")
    parser.add_argument("--candidate-index", type=int, default=0, help="Saved ordinary learned candidate index; zero for a procedure")
    parser.add_argument("--intraday-data", metavar="PATH", help="Explicit relocated Q5 file with the same verified data identity")
    parser.add_argument("--output", required=True, metavar="NEW_PATH", help="New immutable sample-use report")


def research_intraday_sample_usage_main(args) -> int:
    try:
        report = run_intraday_sample_usage(args.experiment, args.manifest, cost_index=args.cost_index,
            candidate_index=args.candidate_index, intraday_data_file=args.intraday_data)
        output = write_market_data_json(args.output, report)
        print(json.dumps({"result_schema_version": INTRADAY_SAMPLE_USAGE_VERSION,
                          "status": "SUCCESS", "output": str(output), "report": report},
                         ensure_ascii=True, allow_nan=False))
        return 0
    except AtomicFilePublicationError as exc:
        print(json.dumps({"result_schema_version": INTRADAY_SAMPLE_USAGE_VERSION,
                          "status": "FAILED", "error": str(exc), "published": exc.published},
                         ensure_ascii=True), file=sys.stderr)
        return 1
    except (DatasetCLIError, OSError, TypeError, ValueError, KeyError, ArithmeticError,
            RecursionError, LifecycleLockError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_SAMPLE_USAGE_VERSION,
                          "status": "FAILED", "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1
