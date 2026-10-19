"""Offline, allowlisted evidence export from a private S2/S3 paper journal.

Reads a consistent SQLite snapshot in mode=ro. Never connects to OpenD, modifies
or copies the database, exports account balances/IDs, or authorizes trading.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
import sqlite3
import sys
from typing import Any

from .moomoo_simulation_orders import BuyIntent, LIMITS, SCHEMA, number
from . import moomoo_simulation_cash as cash_code

EVENT_KINDS = frozenset({
    "SUBMISSION_INTENT", "SUBMISSION_CALL", "SUBMISSION_RECEIPT", "SUBMISSION_ACK",
    "SUBMISSION_UNKNOWN", "SUBMISSION_NOT_SENT", "ORDER_OBSERVATION", "ORDER_QUERY_FAILED",
    "CANCEL_INTENT", "CANCEL_ACK", "CANCEL_UNKNOWN", "RECOVERY_FAILED", "ACCOUNT_OBSERVATION",
    "ACCOUNT_BASELINE", "RECONCILIATION", "EMERGENCY_STOP",
    "QUALIFICATION_START", "QUALIFICATION_FINISH", "FUNDS_RESPONSE", "PREPARATION_ORIGIN",
})
ORDER_STATES = frozenset({
    "UNSUBMITTED", "WAITING_SUBMIT", "SUBMITTING", "SUBMITTED", "FILLED_PART", "FILLED_ALL",
    "CANCELLING_PART", "CANCELLING_ALL", "CANCELLED_PART", "CANCELLED_ALL", "FAILED",
    "DISABLED", "DELETED",
})
ERROR_TYPES = frozenset({"SimulationError", "RuntimeError", "TimeoutError", "KeyboardInterrupt",
                         "OSError", "OperationalError", "ValueError", "TypeError", "KeyError"})
ERROR_CODES = frozenset({
    "QUALIFICATION_FAILED", "QUALIFICATION_PREFLIGHT_BLOCKED",
    "QUALIFICATION_PREPARATION_REQUIRED", "QUALIFICATION_CANCEL_NOT_CONFIRMED",
    "QUALIFICATION_OUTPUT_IS_JOURNAL",
    "PREVIOUS_PREPARE_UNSAFE", "PREVIOUS_PREPARE_UNAVAILABLE", "PREVIOUS_PREPARE_CHANGED",
    "PREPARATION_SUCCESSOR_PATH_REQUIRED",
    "ACCOUNT_QUERY_FAILED",
    "ACCOUNT_RESIDUAL_UNEXPLAINED",
    "ACCOUNT_SCHEMA_MISMATCH",
    "AMBIGUOUS_BROKER_ORDER",
    "AMBIGUOUS_POSITION",
    "BASELINE_HAS_WORKING_OR_UNKNOWN_ORDERS",
    "BASELINE_MISSING_OR_AMBIGUOUS",
    "BASELINE_MUST_PRECEDE_INTENT_AND_NOT_BE_REPLACED",
    "BROKER_OPERATION_FAILED",
    "BROKER_ORDER_ID_MISMATCH",
    "BROKER_ORDER_INTENTION_MISMATCH",
    "BROKER_RESPONSE_SCHEMA_MISMATCH",
    "CANCEL_ALREADY_ATTEMPTED_QUERY_OUTCOME",
    "CANCEL_OUTCOME_UNKNOWN",
    "CANCEL_RESPONSE_MISMATCH",
    "CASH_CURRENCY_NOT_USD",
    "USD_CASH_INVALID", "USD_CASH_UNAVAILABLE", "CASH_BASIS_CHANGED", "CASH_BASIS_UNVERIFIED",
    "CASH_ONLY_LONG_BUY_UNAVAILABLE",
    "CASH_PREFLIGHT_FAILED",
    "CLOCK_MUST_BE_AWARE",
    "CONTEXT_CLOSE_FAILED",
    "CUMULATIVE_FILL_REGRESSION",
    "CUMULATIVE_PRICE_REVISION_UNRESOLVED",
    "DUPLICATE_ACCOUNT_ID",
    "EXPLICIT_SIMULATION_OPT_IN_REQUIRED",
    "HISTORY_WINDOW_UNSUPPORTED",
    "INTENTION_ALREADY_RECORDED_NO_RESUBMIT",
    "INTENTION_NOT_OWNED",
    "INTENT_ID_MUST_BE_UUID_HEX",
    "INVALID_ACCOUNT_ID",
    "INVALID_BROKER_NUMBER",
    "INVALID_CUMULATIVE_FILL_PRICE",
    "INVALID_CUMULATIVE_FILL_QUANTITY",
    "INVALID_LOCAL_PORT",
    "JOURNAL_ACCOUNT_MISMATCH",
    "JOURNAL_ALREADY_EXISTS",
    "JOURNAL_METADATA_MISMATCH",
    "LIMIT_PRICE_REQUIRES_CENTS",
    "ORDER_CHANGED_DURING_ACCOUNT_SNAPSHOT",
    "ORDER_NOT_IN_VERIFIED_CANCELLABLE_STATE",
    "ORDER_OBSERVATION_UNAVAILABLE",
    "ORDER_STATUS_FILL_CONFLICT",
    "ORDER_UPDATE_TIME_MISSING",
    "OUTSIDE_SUPPORTED_RTH",
    "OWNED_ORDER_STILL_WORKING",
    "PAPER_JOURNAL_STOPPED",
    "PAPER_NOTIONAL_LIMIT",
    "PAPER_QUANTITY_LIMIT",
    "PAPER_RECONCILIATION_BLOCKED",
    "PAPER_RUN_INTENTION_LIMIT",
    "PINNED_SIMULATION_ACCOUNT_UNAVAILABLE",
    "POSITION_OUTSIDE_LONG_SCOPE",
    "RECONCILIATION_UNAVAILABLE",
    "RECONNECT_ACCOUNT_CHANGED",
    "RECOVERY_UNAVAILABLE",
    "SIMULATION_ACCOUNT_NOT_UNIQUE",
    "SIMULATION_ACCOUNT_NOT_VERIFIED",
    "SIMULATION_NOT_CONNECTED",
    "STALE_ORDER_OBSERVATION",
    "SUBMISSION_NOT_SENT",
    "SUBMISSION_OUTCOME_UNKNOWN",
    "SYMBOL_OUTSIDE_PAPER_SCOPE",
    "TERMINAL_STATUS_REGRESSION",
    "UNKNOWN_ORDER_STATUS",
    "UNOWNED_WORKING_OR_UNKNOWN_ORDER",
    "UNSUPPORTED_SIMULATION_ENUM",
    "WORKING_STATUS_REGRESSION",
})


PREPARE_FUNDS_ERRORS = frozenset({"CASH_CURRENCY_NOT_USD", "USD_CASH_INVALID", "USD_CASH_UNAVAILABLE"})

RUNTIME_FILES = (
    "moomoo_simulation.py", "moomoo_sdk.py", "moomoo_simulation_orders.py",
    "moomoo_simulation_recovery.py", "moomoo_simulation_qualifier.py",
    "normalization/rth_calendar.py",
)
ACTIONS = frozenset({"prepare", "submit", "check", "stop"})
ACTION_RESULTS = frozenset({"PREPARED", "SUBMISSION_ACKNOWLEDGED", "OBSERVATIONS_MATCH",
                            "BLOCKED", "STOPPED", "FAILED"})


def safe_runtime(value: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"source_sha256_lf": {}}
    for key in ("python_version", "sdk_version"):
        version = value.get(key)
        if isinstance(version, str) and re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", version):
            result[key] = version
    if value.get("sdk_module") in {"moomoo", "futu"}:
        result["sdk_module"] = value["sdk_module"]
    for name, digest in value.get("source_sha256_lf", {}).items():
        if name in RUNTIME_FILES and isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
            result["source_sha256_lf"][name] = digest
    return result


def timestamp(value: Any, *, aware: bool) -> str:
    if not isinstance(value, str):
        raise ValueError("INVALID_EVIDENCE_TIME")
    parsed = datetime.fromisoformat(value)
    if aware and parsed.utcoffset() is None:
        raise ValueError("INVALID_EVIDENCE_TIME")
    return parsed.isoformat()  # Re-serialize, never forward arbitrary source text.


def read_journal(path: Path) -> tuple[dict[str, Any], list[BuyIntent], list[dict[str, Any]]]:
    """Use the published v1 writer contract; do not open the write-mode class."""
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        meta_rows = db.execute("SELECT payload FROM metadata").fetchall()
        if len(meta_rows) != 1:
            raise ValueError("JOURNAL_METADATA_MISMATCH")
        meta = json.loads(meta_rows[0]["payload"])
        if meta.get("schema") != SCHEMA or meta.get("environment") != "SIMULATE" or meta.get("limits") != LIMITS:
            raise ValueError("JOURNAL_METADATA_MISMATCH")
        intent_rows = db.execute("SELECT intent_id,payload FROM intentions ORDER BY intent_id").fetchall()
        if len(intent_rows) > LIMITS["max_intentions"]:
            raise ValueError("JOURNAL_SCOPE_MISMATCH")
        intents = [BuyIntent(**json.loads(row["payload"])).validated() for row in intent_rows]
        if any(row["intent_id"] != intent.intent_id for row, intent in zip(intent_rows, intents)):
            raise ValueError("JOURNAL_INTENT_MISMATCH")
        rows = db.execute("SELECT seq,kind,intent_id,payload FROM events ORDER BY seq").fetchall()
        events = []
        for row in rows:
            payload = json.loads(row["payload"])
            if not isinstance(payload, dict) or (row["intent_id"] is not None and
                                                row["intent_id"] not in {i.intent_id for i in intents}):
                raise ValueError("JOURNAL_EVENT_MISMATCH")
            # Row identities cannot be shadowed by a JSON payload.
            events.append({**payload, "seq": row["seq"], "kind": row["kind"], "intent_id": row["intent_id"]})
        return meta, intents, events


def build_evidence(path: Path) -> dict[str, Any]:
    meta, intents, events = read_journal(path)
    aliases = {item.intent_id: f"intent-{index + 1}" for index, item in enumerate(intents)}
    order_aliases: dict[str, str] = {}
    owned_symbols = {item.symbol for item in intents}
    projected = []
    for event in events:
        kind = event["kind"]
        item: dict[str, Any] = {
            "seq": event["seq"], "kind": kind if kind in EVENT_KINDS else "UNRECOGNIZED_EVENT",
            "intent": aliases.get(event["intent_id"]),
            "recorded_at_utc": timestamp(event["recorded_at_utc"], aware=True),
        }
        if kind in EVENT_KINDS:
            if kind == "PREPARATION_ORIGIN":
                digest = event.get("previous_journal_sha256")
                count, error = event.get("previous_event_count"), event.get("previous_failure_code")
                if (not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                        or type(count) is not int or count not in {3, 4}
                        or not isinstance(error, str) or error not in PREPARE_FUNDS_ERRORS):
                    raise ValueError("INVALID_PREPARATION_ORIGIN")
                item.update(previous_journal_sha256=digest, previous_event_count=count,
                            previous_failure_code=error)
            if kind == "FUNDS_RESPONSE":
                from .moomoo_simulation_recovery import FUNDS_DIAGNOSTIC_VALUES
                for key, allowed in FUNDS_DIAGNOSTIC_VALUES.items():
                    value = event.get(key)
                    item[key] = value if isinstance(value, str) and value in allowed else "UNRECOGNIZED"
            if kind in {"SUBMISSION_RECEIPT", "SUBMISSION_ACK", "ORDER_OBSERVATION", "CANCEL_INTENT", "CANCEL_ACK"}:
                oid = event.get("order_id")
                if not isinstance(oid, str) or not oid:
                    raise ValueError("INVALID_EVIDENCE_ORDER_ID")
                if oid not in order_aliases:
                    order_aliases[oid] = f"order-{len(order_aliases) + 1}"
                item["order"] = order_aliases[oid]
            if kind in {"SUBMISSION_ACK", "ORDER_OBSERVATION"}:
                state = event.get("order_status")
                item["order_status"] = state if state in ORDER_STATES else "UNKNOWN"
                for key in ("dealt_qty", "dealt_avg_price"):
                    if key in event:
                        item[key] = str(number(event[key]))
                for key in ("create_time", "updated_time"):
                    if event.get(key):
                        item[key] = timestamp(event[key], aware=False)
                item["broker_time_basis"] = "AS_REPORTED_NOT_CLOCK_ALIGNED"
            if kind in {"ACCOUNT_BASELINE", "ACCOUNT_OBSERVATION"}:
                for key in ("started_at_utc", "finished_at_utc"):
                    item[key] = timestamp(event[key], aware=True)
                item["atomic_snapshot"] = False
            if kind == "RECONCILIATION":
                item["cash_arithmetic"] = cash_code.replay_cash_arithmetic(events, event["seq"])
                item["result"] = ("OBSERVATIONS_MATCH" if event.get("result") == "OBSERVATIONS_MATCH" else "BLOCKED")
                if "cash_residual_usd" in event:
                    item["cash_residual_usd"] = str(number(event["cash_residual_usd"]))
                residuals = event.get("position_residuals", {})
                item["position_residuals"] = {code: str(number(qty)) for code, qty in residuals.items()
                                              if code in owned_symbols}
            if kind in {"ACCOUNT_BASELINE", "ACCOUNT_OBSERVATION", "RECONCILIATION"}:
                from .moomoo_simulation_recovery import CASH_BASES
                for key in ("cash_basis", "baseline_cash_basis"):
                    if key in event:
                        value = event[key]
                        item[key] = value if isinstance(value, str) and value in CASH_BASES else "UNVERIFIED"
            if kind in {"QUALIFICATION_START", "QUALIFICATION_FINISH"}:
                if event.get("action") not in ACTIONS:
                    raise ValueError("INVALID_QUALIFICATION_ACTION")
                item["action"] = event["action"]
                item["runtime"] = safe_runtime(event.get("runtime", {}))
                item["started_at_utc"] = timestamp(event["started_at_utc"], aware=True)
                if kind == "QUALIFICATION_FINISH":
                    if event.get("result") not in ACTION_RESULTS:
                        raise ValueError("INVALID_QUALIFICATION_RESULT")
                    if type(event.get("start_seq")) is not int or event["start_seq"] <= 0:
                        raise ValueError("INVALID_QUALIFICATION_START")
                    elapsed = number(event["elapsed_ms"])
                    if elapsed < 0:
                        raise ValueError("INVALID_QUALIFICATION_DURATION")
                    item.update(result=event["result"], start_seq=event["start_seq"], elapsed_ms=str(elapsed),
                                finished_at_utc=timestamp(event["finished_at_utc"], aware=True))
            if "error_type" in event:
                item["error_type"] = event["error_type"] if event["error_type"] in ERROR_TYPES else "REDACTED_ERROR_TYPE"
            if "error_code" in event:
                item["error_code"] = event["error_code"] if event["error_code"] in ERROR_CODES else "REDACTED_ERROR_CODE"
        projected.append(item)
    report = {
        "schema": "market_vault_paper_evidence_v1", "environment": "SIMULATE",
        "journal_created_at_utc": timestamp(meta["created_at_utc"], aware=True),
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "exporter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "cash_arithmetic_source_sha256_lf": hashlib.sha256(
            Path(cash_code.__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
        "limits": dict(LIMITS),
        "intentions": [{"intent": aliases[i.intent_id], "symbol": i.symbol, "qty": i.qty,
                        "limit_price": i.price, "side": "BUY"} for i in intents],
        "events": projected, "source_event_count": len(events),
        "unrecognized_event_count": sum(item["kind"] == "UNRECOGNIZED_EVENT" for item in projected),
        "stopped": any(item["kind"] == "EMERGENCY_STOP" for item in projected),
        "account_identity_exported": False, "broker_identifiers_exported": False,
        "account_balances_exported": False, "new_orders_authorized": False,
        "broker_qualification": "NOT_ASSESSED", "independent_market_data": "NOT_SUPPLIED",
        "fees": "NOT_OBSERVED", "cash_flows": "NOT_OBSERVED",
        "scope": "OWNER_LOCAL_JOURNAL_PROJECTION_NOT_BROKER_ATTESTATION",
    }
    from . import moomoo_simulation_observations as observed_code
    from . import moomoo_simulation_orders as order_code
    from . import moomoo_simulation_recovery as recovery_code
    report["observation_summary"] = observed_code.summarize(report)
    report["observation_summary_source_sha256_lf"] = {
        name: hashlib.sha256(Path(module.__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for name, module in (("moomoo_simulation_observations.py", observed_code),
                             ("moomoo_simulation_orders.py", order_code),
                             ("moomoo_simulation_recovery.py", recovery_code))
    }
    return report


def export_evidence(journal: Path, output: Path) -> dict[str, Any]:
    report = build_evidence(journal)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        export_evidence(args.journal, args.output)
    except Exception:
        # Do not turn corrupt/private file content into public exception output.
        print("EVIDENCE_EXPORT_FAILED: preserve the journal; choose a new output file", file=sys.stderr)
        return 1
    print("EVIDENCE_EXPORTED; ORDERS_SENT=false; BROKER_QUALIFICATION=NOT_ASSESSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
