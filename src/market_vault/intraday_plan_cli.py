"""Save an ordinary comparison plan from one explicitly named saved candidate."""

from __future__ import annotations

import json
import sys

from .dataset.cli import DatasetCLIError
from .research.intraday_plan import extract_intraday_candidate_plan, serialize_intraday_plan, write_intraday_plan


INTRADAY_PLAN_CLI_VERSION = "market-vault-intraday-plan-cli-result-v1"


def add_intraday_plan_subparser(subparsers):
    parser = subparsers.add_parser("research-intraday-plan-from-candidate", help="Save a plan for continuing one recorded DEV candidate")
    parser.add_argument("--experiment", required=True, metavar="PATH")
    parser.add_argument("--output", required=True, metavar="PATH")
    parser.add_argument("--cost-index", type=int, default=0)
    parser.add_argument("--candidate-index", type=int, default=0)
    parser.add_argument("--expected-experiment-id")
    parser.add_argument("--expected-candidate-id")


def research_intraday_plan_main(args) -> int:
    try:
        plan = extract_intraday_candidate_plan(args.experiment, cost_index=args.cost_index, candidate_index=args.candidate_index,
            expected_experiment_id=args.expected_experiment_id, expected_candidate_id=args.expected_candidate_id)
        written = write_intraday_plan(serialize_intraday_plan(plan), path=args.output)
        payload = {"plan": plan, "selection": {"cost_index": args.cost_index, "candidate_index": args.candidate_index},
                   "plan_file": {"path": str(written.path), "plan_schema_version": written.plan_schema_version,
                                 "content_sha256": written.content_sha256, "created_new_file": written.created_new_file}}
        print(json.dumps({"result_schema_version": INTRADAY_PLAN_CLI_VERSION, "status": "SUCCESS", **payload},
                         ensure_ascii=True, allow_nan=False))
        return 0
    except (DatasetCLIError, OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_PLAN_CLI_VERSION, "status": "FAILED", "error": str(exc)},
                         ensure_ascii=True), file=sys.stderr)
        return 1
