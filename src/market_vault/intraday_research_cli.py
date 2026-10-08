"""Explicit day-plan proposal, development comparison and finite diagnostics."""

from __future__ import annotations

import json
import sys

from .dataset.cli import DatasetCLIError, _coerce_plan_path
from .research.intraday_data import load_intraday_dataset, parse_json
from .research.intraday_experiment import create_intraday_experiment
from .research.intraday_research import (
    INTRADAY_DIAGNOSTICS_PLAN_VERSION, default_intraday_research_plan, expand_intraday_plan, run_intraday_research,
)
from .research.strategy_experiment import write_strategy_experiment


INTRADAY_RESEARCH_CLI_VERSION = "market-vault-intraday-research-cli-result-v1"


def add_intraday_research_subparsers(subparsers):
    proposal = subparsers.add_parser("research-intraday-plan", help="Propose explicit 70/15/15 day boundaries before research")
    proposal.add_argument("--data", required=True, metavar="PATH")
    proposal.add_argument("--commission-bps", required=True)
    proposal.add_argument("--slippage-bps", required=True)
    for name in ("research-intraday-compare", "research-intraday-diagnose"):
        parser = subparsers.add_parser(name, help="Evaluate explicit intraday development candidates with execution V2")
        parser.add_argument("--plan", required=True, metavar="PATH")
        parser.add_argument("--experiment", metavar="PATH", help="Create an immutable experiment file")
        parser.add_argument("--name", default="")
        parser.add_argument("--notes", default="")


def research_intraday_research_main(args, *, command: str) -> int:
    try:
        if command == "research-intraday-plan":
            data = load_intraday_dataset(_coerce_plan_path(args.data))
            plan = default_intraday_research_plan(data, commission_bps=float(args.commission_bps), slippage_bps=float(args.slippage_bps))
            payload = {"plan": plan}
        else:
            if (args.name or args.notes) and args.experiment is None:
                raise ValueError("--name/--notes require --experiment")
            path = _coerce_plan_path(args.plan)
            plan, _, _ = expand_intraday_plan(parse_json(path.read_bytes()), base=path.parent)
            if (plan["plan_schema_version"] == INTRADAY_DIAGNOSTICS_PLAN_VERSION) != (command == "research-intraday-diagnose"):
                raise ValueError("command differs from the supplied comparison/diagnostics plan")
            report = run_intraday_research(plan)
            payload = {"report": report}
            if args.experiment is not None:
                snapshot = create_intraday_experiment(plan=plan, report=report, name=args.name, notes=args.notes)
                written = write_strategy_experiment(snapshot, path=args.experiment)
                payload["experiment"] = {"path": str(written.path), "experiment_id": written.experiment_id,
                                         "created_new_file": written.created_new_file}
        print(json.dumps({"result_schema_version": INTRADAY_RESEARCH_CLI_VERSION, "status": "SUCCESS", **payload}, ensure_ascii=False, allow_nan=False))
        return 0
    except (DatasetCLIError, OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError) as exc:
        print(json.dumps({"result_schema_version": INTRADAY_RESEARCH_CLI_VERSION, "status": "FAILED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
