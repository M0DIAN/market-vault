"""Settings-independent deterministic, standalone return-basis assessment."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from .dataset.cli import DatasetCLIError
from .research.return_assessment import (
    RETURN_ASSESSMENT_VERSION, ReturnAssessmentError, assess_dataset,
    assess_saved_experiment, parse_event_restrictions,
)


def add_return_assessment_subparser(subparsers) -> None:
    parser = subparsers.add_parser("research-return-assessment", help="Assess unadjusted price windows; corporate-action coverage remains UNKNOWN/PARTIAL")
    parser.add_argument("--dataset", metavar="DIR", help="Exact verified Dataset; choose this or --experiment")
    parser.add_argument("--experiment", metavar="FILE", help="Saved ordinary base/intraday/TEST experiment")
    parser.add_argument("--events", metavar="FILE", help="Explicit finite return-restrictions-v1 JSON list")
    parser.add_argument("--source-dataset", metavar="DIR", help="Relocated exact Dataset for a saved base experiment; recorded ID must match")


def research_return_assessment_main(args) -> int:
    try:
        if (args.dataset is not None) == (args.experiment is not None):
            raise ReturnAssessmentError("INVALID_INPUT", "choose exactly one of --dataset or --experiment")
        if args.dataset is not None and args.source_dataset is not None:
            raise ReturnAssessmentError("INVALID_INPUT", "--source-dataset applies only to a saved base experiment")
        for option in ("dataset", "experiment", "events", "source_dataset"):
            value = getattr(args, option)
            if value is not None and (type(value) is not str or not value.strip()):
                raise ReturnAssessmentError("INVALID_INPUT", f"--{option.replace('_', '-')} must be a nonblank path")
        events = None if args.events is None else parse_event_restrictions(Path(args.events).read_bytes())
        result = (assess_dataset(args.dataset, events=events) if args.dataset is not None else
                  assess_saved_experiment(args.experiment, events=events, source_dataset=args.source_dataset))
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False))
        return 2 if result["restriction_matches"] else 0
    except (DatasetCLIError, OSError, TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        print(json.dumps({"version": RETURN_ASSESSMENT_VERSION, "status": "FAILED",
                          "reason_code": getattr(exc, "reason_code", "INVALID_INPUT"), "error": str(exc)},
                         ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False), file=sys.stderr)
        return 1
