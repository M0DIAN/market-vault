"""Descriptive S4/S5 observations, never trading or research acceptance authority.

Input is the existing allowlisted journal projection, not arbitrary broker data.
No new query, file write, signal denominator, market quote or fill is invented.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .moomoo_simulation_orders import TERMINAL, number
from .moomoo_simulation_recovery import UNFILLED, WORKING, check_progress

UNCERTAIN = frozenset({"SUBMISSION_UNKNOWN", "ORDER_QUERY_FAILED", "RECOVERY_FAILED",
                       "CANCEL_INTENT", "CANCEL_ACK", "CANCEL_UNKNOWN", "UNRECOGNIZED_EVENT"})


def wall_elapsed(start: dict[str, Any] | None, end: dict[str, Any] | None) -> dict[str, Any]:
    """Local wall-clock observation delay, including manual wait/recovery; not latency."""
    result: dict[str, Any] = {"seconds": None, "reason": "MISSING_OBSERVATION"}
    if start is None or end is None:
        return result
    try:
        left, right = (datetime.fromisoformat(e["recorded_at_utc"]) for e in (start, end))
        if left.utcoffset() is None or right.utcoffset() is None:
            raise ValueError("naive")
        delta = right - left
        if end["seq"] < start["seq"] or delta.total_seconds() < 0:
            raise ValueError("backwards")
        result.update(seconds=delta.total_seconds(), reason=None)
    except (KeyError, TypeError, ValueError, OverflowError):
        result["reason"] = "INVALID_OR_REGRESSING_LOCAL_CLOCK"
    return result


def action_observations(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for start in (e for e in events if e["kind"] == "QUALIFICATION_START"):
        ends = [e for e in events if e["kind"] == "QUALIFICATION_FINISH" and e.get("start_seq") == start["seq"]]
        valid = (len(ends) == 1 and ends[0].get("action") == start["action"]
                 and ends[0]["seq"] > start["seq"])
        rows.append({"start_seq": start["seq"], "action": start["action"],
                     "finish_seq": ends[0]["seq"] if valid else None,
                     "result": ends[0]["result"] if valid else "INCOMPLETE_OR_AMBIGUOUS",
                     "elapsed_ms": ends[0]["elapsed_ms"] if valid else None})
    return rows


def _observation(event: dict[str, Any], qty: int) -> dict[str, Any]:
    state = event["order_status"]
    filled, price = number(event.get("dealt_qty")), number(event.get("dealt_avg_price"))
    if (state not in WORKING | TERMINAL or not 0 <= filled <= qty or price < 0
            or (filled == 0 and price != 0) or (filled > 0 and price <= 0)
            or (state == "FILLED_ALL" and filled != qty)
            or (state in {"FILLED_PART", "CANCELLED_PART"} and not 0 < filled < qty)
            or (state in UNFILLED | {"CANCELLED_ALL", "FAILED"} and filled != 0)
            or not event.get("updated_time")):
        raise ValueError("Incomplete or contradictory observation")
    # Reuse S3's progression checks with the report's local order alias.
    return {**event, "order_id": event["order"]}


def summarize(evidence: dict[str, Any]) -> dict[str, Any]:
    """Summarize recorded intentions, not all signals or the live account state."""
    events, intentions = evidence["events"], evidence["intentions"]
    actions = action_observations(events)
    unresolved_actions = [r for r in actions if r["finish_seq"] is None]
    summaries = []
    for intent in intentions:
        own = [e for e in events if e.get("intent") == intent["intent"]]
        observations = [e for e in own if e["kind"] == "ORDER_OBSERVATION"]
        locators = {e["order"] for e in own if "order" in e}
        last = None
        reason = "NO_FRESH_ORDER_OBSERVATION"
        accepted: list[dict[str, Any]] = []
        try:
            if len(locators) > 1:
                raise ValueError("Ambiguous order")
            for event in observations:
                snapshot = _observation(event, intent["qty"])
                check_progress(snapshot, accepted)
                accepted.append(snapshot)
            if accepted:
                last = accepted[-1]
                reason = None
        except (ValueError, RuntimeError, TypeError, KeyError):
            reason = "INCOMPLETE_OR_CONFLICTING_ORDER_EVIDENCE"
        last_seq = last["seq"] if last else 0
        later = [e for e in events if e["seq"] > last_seq and e.get("intent") in {None, intent["intent"]}]
        failed_later = any(e["kind"] in UNCERTAIN or
                           (e["kind"] == "QUALIFICATION_FINISH" and e.get("result") == "FAILED")
                           for e in later)
        # An unmatched operation containing the last observation is not a completed check.
        incomplete = any(not any(a["start_seq"] > r["start_seq"] and a["start_seq"] <= last_seq
                                 for a in actions) for r in unresolved_actions)
        if last and (failed_later or incomplete):
            reason = "LATER_OR_INCOMPLETE_OPERATION_UNRESOLVED"
        outcome = ("OBSERVED_TERMINAL" if last["order_status"] in TERMINAL else "OBSERVED_WORKING") if last and reason is None else "UNRESOLVED"
        call = next((e for e in own if e["kind"] == "SUBMISSION_CALL"), None)
        not_sent = [e for e in own if e["kind"] == "SUBMISSION_NOT_SENT"]
        if (not observations and not locators and call is None and not_sent and not incomplete
                and not any(e["kind"] in UNCERTAIN and e["seq"] > not_sent[-1]["seq"] for e in later)):
            outcome, reason = "NOT_SENT", None
        receipt = next((e for e in own if e["kind"] == "SUBMISSION_RECEIPT"), None)
        last_values = None
        if last:
            qty, average, limit = number(last["dealt_qty"]), number(last["dealt_avg_price"]), number(intent["limit_price"])
            last_values = {
                "seq": last["seq"], "order_status": last["order_status"],
                "cumulative_qty": str(qty), "average_price": str(average) if qty > 0 else None,
                "fill_minus_owner_limit_usd": str(average - limit) if qty > 0 else None,
                "basis": "LAST_RECORDED_SUCCESSFUL_QUERY_NOT_CURRENT_STATE",
            }
        summaries.append({
            "intent": intent["intent"], "outcome_as_of_record": outcome, "reason": reason,
            "local_submission_boundary_entered": call is not None,
            "receipt_recorded": receipt is not None,
            "full_ack_recorded": any(e["kind"] == "SUBMISSION_ACK" for e in own),
            "had_submission_unknown": any(e["kind"] == "SUBMISSION_UNKNOWN" for e in own),
            "recorded_query_count": len(observations), "last_observation": last_values,
            "call_to_receipt_wall": wall_elapsed(call, receipt),
            "call_to_first_query_wall": wall_elapsed(call, observations[0] if observations else None),
        })
    counts = {name: sum(s["outcome_as_of_record"] == name for s in summaries)
              for name in ("OBSERVED_TERMINAL", "OBSERVED_WORKING", "NOT_SENT", "UNRESOLVED")}
    reconciliations = [e for e in events if e["kind"] == "RECONCILIATION"]
    last_reconciliation = None
    if reconciliations:
        record = reconciliations[-1]
        last_reconciliation = {key: record[key] for key in (
            "seq", "result", "cash_residual_usd", "position_residuals", "error_code") if key in record}
        last_reconciliation["subsequent_activity_recorded"] = any(
            e["seq"] > record["seq"] and (e["kind"] in UNCERTAIN | {"SUBMISSION_CALL", "ORDER_OBSERVATION", "ACCOUNT_OBSERVATION",
                                                                     "EMERGENCY_STOP", "QUALIFICATION_START", "FUNDS_RESPONSE"}
                                          or (e["kind"] == "QUALIFICATION_FINISH" and
                                              (e.get("result") == "FAILED" or e.get("action") == "stop")))
            for e in events) or any(a["start_seq"] > record["seq"] for a in unresolved_actions)
        last_reconciliation["basis"] = "HISTORICAL_NONATOMIC_COMPARISON_ONLY"
    return {
        "schema": "market_vault_paper_observations_v1",
        "denominator": "ALL_RECORDED_INTENTIONS_IN_THIS_JOURNAL", "intention_count": len(intentions),
        "outcome_counts": counts,
        "observed_outcome_fraction": ((counts["OBSERVED_TERMINAL"] + counts["OBSERVED_WORKING"]) / len(intentions)
                                      if intentions else None),
        "intentions": summaries, "actions": actions, "incomplete_action_count": len(unresolved_actions),
        "unrecognized_event_count": evidence["unrecognized_event_count"],
        "last_reconciliation": last_reconciliation,
        "time_basis": "ACTION_MONOTONIC_ELAPSED_AND_LOCAL_WALL_WAIT_NOT_BROKER_LATENCY",
        "price_basis": "BUY_FILL_MINUS_OWNER_LIMIT_NOT_MARKET_SLIPPAGE",
        "market_signal_count": None, "broker_latency_ms": None, "market_slippage_bps": None,
        "fees": "NOT_OBSERVED", "cost_calibration": "NOT_PERFORMED",
        "strategy_forward_validation": "NOT_PERFORMED", "broker_qualification": "NOT_ASSESSED",
        "new_orders_authorized": False,
    }
