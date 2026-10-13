"""Settings-independent market evidence for one explicit Q5 data file."""

from __future__ import annotations

import json
import sys

from .dataset.cli import DatasetCLIError
from .lifecycle import LifecycleLockError
from .quality.market_data_comparison import write_market_data_json
from .research.intraday_market_evidence import INTRADAY_MARKET_EVIDENCE_VERSION, run_intraday_market_evidence
from .storage.atomic_file import AtomicFilePublicationError


def add_intraday_market_evidence_subparser(subparsers) -> None:
    parser = subparsers.add_parser("research-intraday-market-evidence",
        help="Compare the exact verified Q5 price grid with explicitly supplied reference snapshots")
    parser.add_argument("--data", required=True, metavar="PATH", help="Explicit Q5 intraday data file")
    parser.add_argument("--manifest", required=True, metavar="PATH", help="Explicit source/basis/reference plan")
    parser.add_argument("--output", required=True, metavar="NEW_PATH", help="New immutable evidence report")
    parser.add_argument("--policy", metavar="PATH", help="Judge the full Q5 grid under an explicit acceptance policy")


def research_intraday_market_evidence_main(args) -> int:
    policy_path = getattr(args, "policy", None)
    result_version = INTRADAY_MARKET_EVIDENCE_VERSION
    if policy_path is not None:
        from .research.intraday_data_acceptance import INTRADAY_DATA_ACCEPTANCE_VERSION, run_intraday_data_acceptance
        result_version = INTRADAY_DATA_ACCEPTANCE_VERSION
    try:
        report = (run_intraday_market_evidence(args.data, args.manifest) if policy_path is None
                  else run_intraday_data_acceptance(args.data, args.manifest, policy_path))
        output = write_market_data_json(args.output, report)
        print(json.dumps({"result_schema_version": result_version,
                          "status": "SUCCESS" if policy_path is None else report["status"], "output": str(output), "report": report},
                         ensure_ascii=True, allow_nan=False))
        return 0 if policy_path is None or report["status"] == "POLICY_SATISFIED" else 2
    except AtomicFilePublicationError as exc:
        print(json.dumps({"result_schema_version": result_version,
                          "status": "FAILED", "error": str(exc), "published": exc.published},
                         ensure_ascii=True), file=sys.stderr)
        return 1
    except (DatasetCLIError, OSError, TypeError, ValueError, KeyError, ArithmeticError,
            RecursionError, LifecycleLockError) as exc:
        print(json.dumps({"result_schema_version": result_version,
                          "status": "FAILED", "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1
