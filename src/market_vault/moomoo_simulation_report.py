"""Analyze an existing sanitized paper report, entirely offline.

No SQLite, OpenD, orders, fee attribution or acceptance authority. Embedded
summaries are ignored; the original file and its declared runtime are retained.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from . import moomoo_simulation_evidence as projection
from . import moomoo_simulation_observations as observations
from . import moomoo_simulation_orders as orders
from . import moomoo_simulation_recovery as recovery

ORDER_EVENTS = frozenset({"SUBMISSION_RECEIPT", "SUBMISSION_ACK", "ORDER_OBSERVATION",
                          "CANCEL_INTENT", "CANCEL_ACK"})
INTENT_EVENTS = frozenset(k for k in projection.EVENT_KINDS
                          if k.startswith(("SUBMISSION_", "ORDER_", "CANCEL_")) or k == "RECOVERY_FAILED")
RESULTS = {"prepare": {"PREPARED", "FAILED"}, "submit": {"SUBMISSION_ACKNOWLEDGED", "FAILED"},
           "check": {"OBSERVATIONS_MATCH", "BLOCKED", "FAILED"}, "stop": {"STOPPED", "BLOCKED", "FAILED"}}


def require(condition: bool) -> None:
    if not condition:
        raise ValueError("UNSUPPORTED_OR_INCONSISTENT_PAPER_REPORT")


def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value = dict(pairs)
    require(len(value) == len(pairs))
    return value


def declared_runtime(value: Any) -> dict[str, Any]:
    require(isinstance(value, dict) and isinstance(value.get("source_sha256_lf", {}), dict))
    return projection.safe_runtime(value)



def validate_finish(finish: dict[str, Any], prior: list[dict[str, Any]]) -> None:
    """A repeated wrapper/finish declaration is not its own supporting event."""
    if finish["result"] == "FAILED":
        return  # Failure may occur before any operation-specific response.
    window = [e for e in prior if e["seq"] > finish["start_seq"]]
    require(not any(e["kind"] == "QUALIFICATION_START" for e in window))
    action = finish["action"]
    compared = [e for e in window if e["kind"] == "RECONCILIATION"]
    if action in {"check", "prepare"}:
        expected = "OBSERVATIONS_MATCH" if action == "prepare" else finish["result"]
        require(bool(compared) and compared[-1]["result"] == expected)
        if action == "prepare":
            require(any(e["kind"] == "ACCOUNT_BASELINE" and e["seq"] < compared[-1]["seq"] for e in window))
    elif action == "submit":
        reservations = [e for e in window if e["kind"] == "SUBMISSION_INTENT"]
        require(len(compared) == 1 and compared[0]["result"] == "OBSERVATIONS_MATCH"
                and len(reservations) == 1 and compared[0]["seq"] < reservations[0]["seq"])
        acks = [e for e in window if e["kind"] == "SUBMISSION_ACK"]
        require(len(acks) == 1)
        ack = acks[0]
        for kind in ("SUBMISSION_INTENT", "SUBMISSION_CALL", "SUBMISSION_RECEIPT"):
            require(any(e["kind"] == kind and e["intent"] == ack["intent"] and e["seq"] < ack["seq"]
                        and (kind != "SUBMISSION_RECEIPT" or e["order"] == ack["order"]) for e in window))
    else:
        # qualifier persists stop before QUALIFICATION_START, including offline stop.
        require(any(e["kind"] == "EMERGENCY_STOP" for e in prior))


def _project(evidence: dict[str, Any]) -> dict[str, Any]:
    """Validate the existing public projection; copy only summary-consumed fields."""
    require(evidence.get("schema") == "market_vault_paper_evidence_v1"
            and evidence.get("environment") == "SIMULATE" and evidence.get("limits") == orders.LIMITS)
    intents, events = evidence.get("intentions"), evidence.get("events")
    require(isinstance(intents, list) and len(intents) <= orders.LIMITS["max_intentions"]
            and isinstance(events, list))
    safe_intents = []
    for index, item in enumerate(intents, 1):
        require(isinstance(item, dict) and item.get("intent") == f"intent-{index}" and item.get("side") == "BUY")
        validated = orders.BuyIntent("0" * 32, item["symbol"], item["limit_price"], item["qty"]).validated()
        safe_intents.append(dict(intent=item["intent"], symbol=validated.symbol, qty=validated.qty,
                                 limit_price=validated.price, side="BUY"))
    aliases = {i["intent"] for i in safe_intents}
    symbols = {i["symbol"] for i in safe_intents}
    reserved: set[str] = set()
    starts: dict[int, dict[str, Any]] = {}
    finished: set[int] = set()
    safe_events = []
    for seq, event in enumerate(events, 1):
        require(isinstance(event, dict) and type(event.get("seq")) is int and event["seq"] == seq)
        kind, alias = event.get("kind"), event.get("intent")
        require(isinstance(kind, str) and (alias is None or isinstance(alias, str) and alias in aliases))
        known = kind in projection.EVENT_KINDS
        row = dict(seq=seq, kind=kind if known else "UNRECOGNIZED_EVENT", intent=alias,
                   recorded_at_utc=projection.timestamp(event["recorded_at_utc"], aware=True))
        if known:
            require((alias in aliases) if kind in INTENT_EVENTS else alias is None)
            if kind == "SUBMISSION_INTENT":
                require(alias not in reserved)
                reserved.add(alias)
            elif kind in INTENT_EVENTS:
                require(alias in reserved)
            if kind in ORDER_EVENTS:
                require(isinstance(event.get("order"), str)
                        and re.fullmatch(r"order-[1-9][0-9]*", event["order"]) is not None)
                row["order"] = event["order"]
            if kind in {"SUBMISSION_ACK", "ORDER_OBSERVATION"}:
                state = event.get("order_status")
                row["order_status"] = state if isinstance(state, str) and state in projection.ORDER_STATES else "UNKNOWN"
                for key in ("dealt_qty", "dealt_avg_price"):
                    if key in event:
                        row[key] = str(orders.number(event[key]))
                for key in ("create_time", "updated_time"):
                    if event.get(key):
                        row[key] = projection.timestamp(event[key], aware=False)
            if kind == "RECONCILIATION":
                require(event.get("result") in {"BLOCKED", "OBSERVATIONS_MATCH"})
                row["result"] = event["result"]
                if "cash_residual_usd" in event:
                    row["cash_residual_usd"] = str(orders.number(event["cash_residual_usd"]))
                if "position_residuals" in event:
                    require(isinstance(event["position_residuals"], dict))
                    row["position_residuals"] = {code: str(orders.number(qty))
                        for code, qty in event["position_residuals"].items() if code in symbols}
                for key in ("cash_basis", "baseline_cash_basis"):
                    if key in event:
                        value = event[key]
                        row[key] = value if isinstance(value, str) and value in recovery.CASH_BASES else "UNVERIFIED"
            if kind in {"QUALIFICATION_START", "QUALIFICATION_FINISH"}:
                require(isinstance(event.get("action"), str) and event["action"] in RESULTS)
                row["action"] = event["action"]
                row["started_at_utc"] = projection.timestamp(event["started_at_utc"], aware=True)
                row["runtime"] = declared_runtime(event.get("runtime", {}))
                if kind == "QUALIFICATION_START":
                    starts[seq] = row
                else:
                    start_seq = event.get("start_seq")
                    require(type(start_seq) is int and start_seq in starts and start_seq not in finished)
                    start = starts[start_seq]
                    require(start["action"] == row["action"] and start["started_at_utc"] == row["started_at_utc"]
                            and event.get("result") in RESULTS[row["action"]])
                    elapsed = orders.number(event["elapsed_ms"])
                    end = projection.timestamp(event["finished_at_utc"], aware=True)
                    require(elapsed >= 0 and datetime.fromisoformat(end) >= datetime.fromisoformat(row["started_at_utc"]))
                    row.update(start_seq=start_seq, result=event["result"], elapsed_ms=str(elapsed), finished_at_utc=end)
                    finished.add(start_seq)
            if "error_code" in event:
                value = event["error_code"]
                row["error_code"] = value if isinstance(value, str) and value in projection.ERROR_CODES else "REDACTED_ERROR_CODE"
        if kind == "QUALIFICATION_FINISH":
            validate_finish(row, safe_events)
        safe_events.append(row)
    require(reserved == aliases)
    require(type(evidence.get("source_event_count")) is int and evidence["source_event_count"] == len(events))
    unknown = sum(e["kind"] == "UNRECOGNIZED_EVENT" for e in safe_events)
    require(type(evidence.get("unrecognized_event_count")) is int and evidence["unrecognized_event_count"] == unknown)
    stopped = any(e["kind"] == "EMERGENCY_STOP" for e in safe_events)
    require(type(evidence.get("stopped")) is bool and evidence["stopped"] == stopped)
    return dict(events=safe_events, intentions=safe_intents, unrecognized_event_count=unknown, stopped=stopped)


def analyze_report(path: Path) -> dict[str, Any]:
    """Recompute S13 from one immutable input, not from its embedded summary."""
    raw = path.read_bytes()
    document = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=object_pairs,
                          parse_constant=lambda _: require(False))
    require(isinstance(document, dict))
    wrapper = document.get("schema") == "market_vault_paper_qualification_v1"
    evidence = document.get("evidence") if wrapper else document
    require(isinstance(evidence, dict))
    supported = _project(evidence)
    original: dict[str, Any] = {"schema": document["schema"], "action": None, "result": None}
    if wrapper:
        require(isinstance(document.get("action"), str) and document["action"] in RESULTS
                and document.get("result") in RESULTS[document["action"]])
        finishes = [e for e in supported["events"] if e["kind"] == "QUALIFICATION_FINISH"]
        require(bool(finishes) and finishes[-1]["seq"] == len(supported["events"]))
        last = finishes[-1]
        require((last["action"], last["result"]) == (document["action"], document["result"]))
        original.update(action=document["action"], result=document["result"],
                        runtime=declared_runtime(document.get("runtime", {})))
        if "error_code" in document:
            code = document["error_code"]
            code = code if isinstance(code, str) and code in projection.ERROR_CODES else "REDACTED_ERROR_CODE"
            require(code == last.get("error_code"))
            original["error_code"] = code
    # These are declarations in the old file, NOT this analyzer's execution identity.
    original["journal_created_at_utc"] = projection.timestamp(evidence["journal_created_at_utc"], aware=True)
    original["exported_at_utc"] = projection.timestamp(evidence["exported_at_utc"], aware=True)
    digest = evidence.get("exporter_sha256")
    require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) is not None)
    original["exporter_sha256"] = digest
    declared_sources = evidence.get("observation_summary_source_sha256_lf", {})
    require(isinstance(declared_sources, dict))
    original["observation_summary_source_sha256_lf"] = {
        key: value for key, value in declared_sources.items()
        if key in {"moomoo_simulation_observations.py", "moomoo_simulation_orders.py", "moomoo_simulation_recovery.py"}
        and isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)}
    modules = (sys.modules[__name__], projection, observations, orders, recovery)
    return {
        "schema": "market_vault_paper_report_analysis_v1", "analysis_status": "ANALYZED",
        "input_sha256": hashlib.sha256(raw).hexdigest(), "source_declared": original,
        "analyzer_runtime": {"python_version": sys.version.split()[0], "source_sha256_lf": {
            Path(m.__file__).name: hashlib.sha256(Path(m.__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for m in modules}},
        "analyzed_at_utc": datetime.now(timezone.utc).isoformat(),
        "observation_summary": observations.summarize(supported), "embedded_summary_used": False,
        "scope": "OFFLINE_REANALYSIS_OF_DECLARED_REPORT_NOT_NEW_BROKER_OBSERVATIONS",
        "broker_qualification": "NOT_ASSESSED", "new_orders_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Existing sanitized qualification/evidence JSON")
    parser.add_argument("--output", type=Path, required=True, help="New analysis JSON; never overwritten")
    args = parser.parse_args(argv)
    try:
        require(args.input.resolve() != args.output.resolve())
        report = analyze_report(args.input)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    except (Exception, KeyboardInterrupt):
        print("PAPER_REPORT_ANALYSIS_FAILED: preserve input; use a supported report and a new output file", file=sys.stderr)
        return 1
    print("ANALYZED; OFFLINE=true; BROKER_QUALIFICATION=NOT_ASSESSED; NEW_ORDERS_AUTHORIZED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
