"""Settings-independent fixed three-procedure run and individual study saves."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import sys

from .dataset.cli import DatasetCLIError
from .research.intraday_procedure_suite import PROCEDURE_ORDER, run_intraday_procedure_suite
from .research.strategy_experiment import write_strategy_experiment


INTRADAY_PROCEDURE_SUITE_CLI_VERSION = "market-vault-intraday-procedure-suite-cli-result-v1"


def add_intraday_procedure_suite_subparser(subparsers):
    parser = subparsers.add_parser("research-intraday-procedure-suite",
        help="Run all Q25/Q31/Q36 procedures with one complete ordinary-source reconstruction")
    parser.add_argument("--source-experiment", required=True, metavar="PATH")
    parser.add_argument("--expected-experiment-id", required=True)
    parser.add_argument("--cost-index", required=True, type=int)
    parser.add_argument("--candidate-index", required=True, type=int)
    parser.add_argument("--expected-candidate-id", required=True)
    parser.add_argument("--intraday-data", metavar="PATH", help="Explicit relocated Q5 with unchanged identity")
    parser.add_argument("--name", default="")
    parser.add_argument("--notes", default="")
    for member in PROCEDURE_ORDER:
        parser.add_argument(f"--{member.lower()}-experiment", metavar="PATH",
            help=f"Save the {member} study individually; prior successful saves survive a later failure")


def research_intraday_procedure_suite_main(args) -> int:
    result = {"result_schema_version": INTRADAY_PROCEDURE_SUITE_CLI_VERSION, "status": "FAILED",
              "studies": [], "saved_experiments": []}
    pending, saving = [], None
    try:
        studies = run_intraday_procedure_suite(args.source_experiment,
            expected_experiment_id=args.expected_experiment_id, cost_index=args.cost_index,
            candidate_index=args.candidate_index, expected_candidate_id=args.expected_candidate_id,
            intraday_data_file=args.intraday_data, name=args.name, notes=args.notes)
        result["studies"] = [{"procedure": member, "study": study.as_dict()}
                             for member, study in zip(PROCEDURE_ORDER, studies, strict=True)]
        pending = [{"procedure": member, "path": str(Path(path).absolute()), "study_index": index}
                   for index, member in enumerate(PROCEDURE_ORDER)
                   if (path := getattr(args, member.lower() + "_experiment")) is not None]
        while pending:
            request = pending.pop(0)
            saving = {key: request[key] for key in ("procedure", "path")}
            saved = asdict(write_strategy_experiment(studies[request["study_index"]], path=request["path"]))
            result["saved_experiments"].append({"procedure": request["procedure"], **saved, "path": str(saved["path"])})
            saving = None
        result["status"] = "SUCCESS"
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        return 0
    except (DatasetCLIError, OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        result["status"] = "FAILED"
        result["error"] = str(exc)
        if saving is not None:
            result["failed_save"] = saving
            result["unattempted_saves"] = [{key: request[key] for key in ("procedure", "path")} for request in pending]
        print(json.dumps(result, ensure_ascii=True, allow_nan=False), file=sys.stderr)
        return 1
