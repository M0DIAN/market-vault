"""Replay recorded paper-account cash arithmetic without account access.

Inputs are an existing private journal snapshot, not broker attestations. Only
cash differences and owned cumulative notionals leave this module. Arithmetic
agreement does not attribute a fee, reconcile an account, or authorize an order.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

CASH_BASES = frozenset({"USD_CURRENCY_BALANCE", "LEGACY_DISPLAY_USD"})
SCOPE = "HISTORICAL_NONATOMIC_CASH_ARITHMETIC_ONLY"


class _Unavailable(ValueError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise _Unavailable(reason)


def _number(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise _Unavailable("INVALID_RECORDED_NUMBER")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise _Unavailable("INVALID_RECORDED_NUMBER") from None
    _require(result.is_finite(), "INVALID_RECORDED_NUMBER")
    return result


def _basis(snapshot: dict[str, Any]) -> str:
    # Original v1 snapshots used strictly USD-labelled display cash. Absence of
    # the additive basis key has that meaning, not an inferred USD cash balance.
    basis = snapshot.get("cash_basis", "LEGACY_DISPLAY_USD")
    _require(snapshot.get("currency") == "USD" and isinstance(basis, str)
             and basis in CASH_BASES, "CASH_BASIS_UNVERIFIED_OR_CHANGED")
    return basis


def replay_cash_arithmetic(events: list[dict[str, Any]], reconciliation_seq: int) -> dict[str, Any]:
    """Recompute one recorded comparison using its prior baseline/order records.

    Repeated cumulative queries contribute once per reserved intention, never
    once per event. Later events cannot change an earlier comparison. Missing or
    inconsistent supporting records remain unavailable; no balance is imputed.
    The original expected-cash/residual values are checked, not used to derive
    the independent gross debit and observed cash change. No input is modified.
    """
    result: dict[str, Any] = {
        "status": "UNAVAILABLE", "reason": None,
        "baseline_seq": None, "account_observation_seq": None,
        "order_observation_seqs": [], "cash_basis": None,
        "observed_cash_change_usd": None, "gross_buy_notional_usd": None,
        "recomputed_cash_residual_usd": None, "recorded_cash_residual_usd": None,
        "recorded_expected_cash_matches": None,
        "scope": SCOPE, "fees": "NOT_OBSERVED", "cash_flows": "NOT_OBSERVED",
        "new_orders_authorized": False,
    }
    try:
        _require(type(reconciliation_seq) is int and reconciliation_seq > 0,
                 "RECONCILIATION_UNAVAILABLE")
        _require(isinstance(events, list) and all(isinstance(e, dict) for e in events),
                 "RECONCILIATION_UNAVAILABLE")
        # Only the exact prefix is relevant to this historical comparison.
        prefix = []
        for event in events:
            seq = event.get("seq")
            _require(type(seq) is int and seq == len(prefix) + 1, "EVENT_SEQUENCE_INCONSISTENT")
            prefix.append(event)
            if seq == reconciliation_seq:
                break
        _require(bool(prefix) and prefix[-1]["seq"] == reconciliation_seq
                 and prefix[-1].get("kind") == "RECONCILIATION", "RECONCILIATION_UNAVAILABLE")
        recorded, prior = prefix[-1], prefix[:-1]
        _require(all(k in recorded for k in ("cash_residual_usd",
                 "cash_expected_before_unobserved_fees_usd", "orders", "account_observation")),
                 "COMPARISON_TERMS_NOT_RECORDED")
        baselines = [e for e in prior if e.get("kind") == "ACCOUNT_BASELINE"]
        accounts = [e for e in prior if e.get("kind") == "ACCOUNT_OBSERVATION"]
        _require(len(baselines) == 1 and bool(accounts), "ACCOUNT_SNAPSHOT_UNAVAILABLE")
        baseline, account = baselines[0], accounts[-1]
        nested = recorded["account_observation"]
        _require(isinstance(nested, dict) and baseline["seq"] < account["seq"],
                 "ACCOUNT_SNAPSHOT_INCONSISTENT")
        for key in ("cash", "currency", "positions", "started_at_utc", "finished_at_utc"):
            _require(key in nested and key in account and nested[key] == account[key],
                     "ACCOUNT_SNAPSHOT_INCONSISTENT")
        basis = _basis(baseline)
        _require(_basis(account) == _basis(nested) == basis
                 and recorded.get("cash_basis", "LEGACY_DISPLAY_USD") == basis
                 and recorded.get("baseline_cash_basis", "LEGACY_DISPLAY_USD") == basis,
                 "CASH_BASIS_UNVERIFIED_OR_CHANGED")
        reservations = [e for e in prior if e.get("kind") == "SUBMISSION_INTENT"]
        _require(len(reservations) <= 1 and all(e["seq"] > baseline["seq"] for e in reservations),
                 "INTENTION_HISTORY_INCONSISTENT")
        orders = recorded["orders"]
        _require(isinstance(orders, list) and len(orders) == len(reservations),
                 "ORDER_EVIDENCE_INCONSISTENT")
        gross = Decimal(0)
        observation_seqs = []
        for reservation, order in zip(reservations, orders):
            identifier = reservation.get("intent_id")
            _require(isinstance(identifier, str) and bool(identifier), "INTENTION_HISTORY_INCONSISTENT")
            queries = [e for e in prior if e.get("kind") == "ORDER_OBSERVATION"
                       and e.get("intent_id") == identifier and e["seq"] > reservation["seq"]]
            _require(bool(queries) and isinstance(order, dict), "ORDER_EVIDENCE_UNAVAILABLE")
            last = queries[-1]
            _require(last["seq"] > account["seq"], "ORDER_EVIDENCE_UNAVAILABLE")
            for key in ("order_id", "order_status", "dealt_qty", "dealt_avg_price", "updated_time"):
                _require(key in order and key in last and order[key] == last[key],
                         "ORDER_EVIDENCE_INCONSISTENT")
            preceding = [e for e in queries if e["seq"] < account["seq"]]
            fields = ("order_id", "order_status", "dealt_qty", "dealt_avg_price", "create_time", "updated_time")
            _require(bool(preceding) and all(
                (key in preceding[-1]) == (key in last) and preceding[-1].get(key) == last.get(key)
                for key in fields), "ORDER_SNAPSHOT_NOT_STABLE")
            qty, average = _number(last["dealt_qty"]), _number(last["dealt_avg_price"])
            _require(0 <= qty <= 1 and average >= 0 and ((qty == 0 and average == 0)
                     or (qty > 0 and average > 0)), "ORDER_EVIDENCE_INCONSISTENT")
            # The frozen v1 journal's complete_snapshot status/fill contract.
            # Work only on its allowlisted cumulative fields, not fabricated SDK rows.
            unfilled = {"UNSUBMITTED", "WAITING_SUBMIT", "SUBMITTING", "SUBMITTED"}
            known = unfilled | {"FILLED_PART", "FILLED_ALL", "CANCELLING_PART", "CANCELLING_ALL",
                                "CANCELLED_PART", "CANCELLED_ALL", "FAILED", "DISABLED", "DELETED"}
            status = last["order_status"]
            _require(isinstance(status, str) and status in known
                     and (status != "FILLED_ALL" or qty == 1)
                     and (status not in {"FILLED_PART", "CANCELLED_PART"} or 0 < qty < 1)
                     and (status not in unfilled | {"CANCELLED_ALL", "FAILED"} or qty == 0),
                     "ORDER_EVIDENCE_INCONSISTENT")
            _require(isinstance(last["order_id"], str) and bool(last["order_id"].strip())
                     and isinstance(last["updated_time"], str) and bool(last["updated_time"]),
                     "ORDER_EVIDENCE_INCONSISTENT")
            try:
                datetime.fromisoformat(last["updated_time"])
            except ValueError:
                raise _Unavailable("ORDER_EVIDENCE_INCONSISTENT") from None
            gross += qty * average
            observation_seqs.append(last["seq"])
        before, after = _number(baseline.get("cash")), _number(account.get("cash"))
        observed_change = after - before
        recomputed = observed_change + gross
        original = _number(recorded["cash_residual_usd"])
        expected_matches = _number(recorded["cash_expected_before_unobserved_fees_usd"]) == before - gross
        matches = expected_matches and original == recomputed
        result.update(
            status="RECOMPUTED_MATCH" if matches else "RECOMPUTED_MISMATCH", reason=None,
            baseline_seq=baseline["seq"], account_observation_seq=account["seq"],
            order_observation_seqs=observation_seqs, cash_basis=basis,
            observed_cash_change_usd=str(observed_change), gross_buy_notional_usd=str(gross),
            recomputed_cash_residual_usd=str(recomputed), recorded_cash_residual_usd=str(original),
            recorded_expected_cash_matches=expected_matches,
        )
    except _Unavailable as exc:
        result["reason"] = str(exc)  # Only fixed internal reason codes, never private input.
    return result
