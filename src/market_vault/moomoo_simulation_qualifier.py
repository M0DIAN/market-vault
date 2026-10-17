"""Bounded owner-run simulator exercise; prepare never sends an order.

Keep the same private journal. Unknown submission must be checked, never retried.
There is no REAL option, automatic price selection, liquidation, or resume.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any
from uuid import uuid4

from .moomoo_simulation import SimulationAccountSession, SimulationError
from .moomoo_simulation_orders import BuyIntent, PaperJournal, SYMBOLS
from .moomoo_simulation_recovery import PaperRecovery
from .moomoo_simulation_evidence import (
    ERROR_CODES, RUNTIME_FILES, build_evidence, safe_runtime,
)


def utc_time() -> str:
    return datetime.now(timezone.utc).isoformat()


def runtime_identity() -> dict[str, Any]:
    root = Path(__file__).parent
    return {"python_version": sys.version.split()[0], "source_sha256_lf": {
        name: hashlib.sha256((root / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for name in RUNTIME_FILES
    }}


def diagnostic(exc: BaseException) -> str:
    code = str(exc)
    return code if isinstance(exc, SimulationError) and code in ERROR_CODES else "QUALIFICATION_FAILED"


def _connected_action(args: argparse.Namespace, journal: PaperJournal,
                      session: SimulationAccountSession) -> dict[str, Any]:
    work = PaperRecovery(session, journal)
    if args.action == "prepare":
        work.baseline()
        result = work.reconcile()
        if result["result"] != "OBSERVATIONS_MATCH":
            raise SimulationError("QUALIFICATION_PREFLIGHT_BLOCKED")
        return {"result": "PREPARED"}
    if args.action == "submit":
        journal.require_running()
        if journal.intentions():
            raise SimulationError("PAPER_RUN_INTENTION_LIMIT")
        prepared = [e for e in journal.events() if e["kind"] == "QUALIFICATION_FINISH"
                    and e.get("action") == "prepare" and e.get("result") == "PREPARED"]
        if len(prepared) != 1:
            raise SimulationError("QUALIFICATION_PREPARATION_REQUIRED")
        intent = BuyIntent(uuid4().hex, args.symbol, args.price).validated()
        # An earlier baseline/connection success is not current account readiness.
        if work.reconcile()["result"] != "OBSERVATIONS_MATCH":
            raise SimulationError("QUALIFICATION_PREFLIGHT_BLOCKED")
        return work.submit(intent, execute_simulate=args.execute_simulate)
    if args.action == "check":
        return work.reconcile()
    return work.stop(cancel_owned=args.cancel_owned, execute_simulate=args.execute_simulate)


def perform(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    """Run once; use existing S1/S2/S3 guard, journal, recovery and stop paths."""
    started, tick = utc_time(), time.monotonic_ns()
    journal: PaperJournal | None = None
    runtime: dict[str, Any] = {}
    start_seq: int | None = None
    result: dict[str, Any] = {"result": "FAILED"}
    try:
        runtime = runtime_identity()
        if args.action == "prepare":
            if args.journal.exists():
                raise SimulationError("JOURNAL_ALREADY_EXISTS")
            with SimulationAccountSession(account_id=args.account_id, port=args.port,
                                          security_firm=args.security_firm) as session:
                journal = PaperJournal.create(args.journal, session.account.account_id)
                journal.append("QUALIFICATION_START", None, action=args.action,
                               started_at_utc=started, runtime=runtime)
                start_seq = journal.events()[-1]["seq"]
                runtime.update(session._metadata)
                result = _connected_action(args, journal, session)
        else:
            journal = PaperJournal(args.journal)
            if args.action == "stop":
                journal.stop()
            journal.append("QUALIFICATION_START", None, action=args.action,
                           started_at_utc=started, runtime=runtime)
            start_seq = journal.events()[-1]["seq"]
            if args.action == "stop" and not args.cancel_owned:
                result = {"result": "STOPPED"}
            else:
                with SimulationAccountSession(account_id=journal.account_id, port=args.port,
                                              security_firm=args.security_firm) as session:
                    runtime.update(session._metadata)
                    result = _connected_action(args, journal, session)
    except (Exception, KeyboardInterrupt) as exc:
        result = {"result": "FAILED", "error_code": diagnostic(exc)}
        # Never reset a failed preparation or ambiguous submission to try again.
        if journal is not None and (args.action == "prepare" or
                                    (args.action == "submit" and journal.intentions())):
            journal.stop()
    finally:
        if journal is not None:
            try:
                cancel_failed = any(r["result"] == "CANCEL_NOT_CONFIRMED"
                                    for r in result.get("cancel_results", []))
                if cancel_failed:
                    result = {"result": "BLOCKED", "error_code": "QUALIFICATION_CANCEL_NOT_CONFIRMED"}
                result = {key: result[key] for key in ("result", "error_code") if key in result}
                result.update(action=args.action, started_at_utc=started, finished_at_utc=utc_time(),
                              elapsed_ms=str((time.monotonic_ns() - tick) / 1_000_000),
                              runtime=safe_runtime(runtime), start_seq=start_seq, stopped=journal.stopped)
                if start_seq is not None:
                    journal.append("QUALIFICATION_FINISH", None, **result)
            finally:
                journal.close()
    # Export only AFTER the writer and SDK contexts close. No private data in fallback.
    public: dict[str, Any] = {"schema": "market_vault_paper_qualification_v1",
                              "action": args.action, "result": result["result"],
                              "broker_qualification": "NOT_ASSESSED", "new_orders_authorized": False}
    if "error_code" in result:
        public["error_code"] = result["error_code"]
    public["runtime"] = safe_runtime(runtime)
    try:
        public["evidence"] = build_evidence(args.journal) if journal is not None else None
    except Exception:
        public["evidence"] = None
        public["evidence_error"] = "EVIDENCE_UNAVAILABLE_KEEP_JOURNAL"
    code = int(result["result"] in {"BLOCKED", "FAILED"} or public.get("evidence") is None)
    return code, public


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "submit", "check", "stop"))
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New sanitized JSON for this action")
    parser.add_argument("--account-id", type=int, help="Only for prepare; kept local")
    parser.add_argument("--port", type=int, default=11111)
    parser.add_argument("--security-firm", default="NONE")
    parser.add_argument("--symbol", choices=SYMBOLS)
    parser.add_argument("--price", help="Owner-chosen one-share limit; not an automatic signal")
    parser.add_argument("--execute-simulate", action="store_true")
    parser.add_argument("--cancel-owned", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "submit" and (not args.execute_simulate or not args.symbol or not args.price):
        parser.error("submit requires --symbol, --price and --execute-simulate")
    if args.action != "prepare" and args.account_id is not None:
        parser.error("--account-id is only for prepare; existing journal pins the account")
    if args.cancel_owned and (args.action != "stop" or not args.execute_simulate):
        parser.error("--cancel-owned requires stop and --execute-simulate")
    try:
        if args.action == "stop":
            # Safety state must not depend on report availability or OpenD connection.
            with PaperJournal(args.journal) as journal:
                journal.stop()
        if args.output.resolve() == args.journal.resolve():
            raise SimulationError("QUALIFICATION_OUTPUT_IS_JOURNAL")
        # Reserve output before any broker mutation; never overwrite old reports.
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            code, report = perform(args)
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        print(f"RESULT={report['result']}; BROKER_QUALIFICATION=NOT_ASSESSED")
        return code
    except (Exception, KeyboardInterrupt):
        print("QUALIFICATION_OR_REPORT_FAILED: keep the journal; do not resubmit; use check/stop", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
