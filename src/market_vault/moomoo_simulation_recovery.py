"""Owner-operated SIMULATE recovery, account comparison, and durable stop.

No strategy runner, new order, automatic resume, liquidation, or REAL fallback.
Only local allowlisted events are retained; the journal remains account-private.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
import sys
from typing import Any
from zoneinfo import ZoneInfo

from .moomoo_simulation import SimulationAccountSession, SimulationError
from .moomoo_simulation_orders import (
    BuyIntent, CANCELLABLE, PaperExecution, PaperJournal, TERMINAL,
    number, one_row, order_snapshot,
)

OBSERVATIONS = {"SUBMISSION_ACK", "ORDER_OBSERVATION"}
UNFILLED = frozenset({"UNSUBMITTED", "WAITING_SUBMIT", "SUBMITTING", "SUBMITTED"})
WORKING = CANCELLABLE | {"UNSUBMITTED", "WAITING_SUBMIT", "SUBMITTING",
                         "CANCELLING_PART", "CANCELLING_ALL"}


FUNDS_DIAGNOSTIC_VALUES = {
    "requested_currency": frozenset({"USD"}),
    "display_currency": frozenset({"USD", "HKD", "CNH", "JPY", "SGD", "AUD", "CAD", "MYR",
                                    "NONE", "N/A", "MISSING", "UNAVAILABLE"}),
    "cash_state": frozenset({"FINITE", "MISSING", "UNAVAILABLE", "INVALID"}),
    "us_cash_state": frozenset({"FINITE", "MISSING", "UNAVAILABLE", "INVALID"}),
    "response_shape": frozenset({"SINGLE_ROW", "INVALID_SCHEMA"}),
}


def funds_diagnostic(frame: Any) -> dict[str, str]:
    """Fixed shape/currency metadata only; no amounts, IDs, raw columns or errors."""
    from pandas import DataFrame

    result = {"requested_currency": "USD", "display_currency": "MISSING",
              "cash_state": "MISSING", "us_cash_state": "MISSING",
              "response_shape": "INVALID_SCHEMA"}
    if not isinstance(frame, DataFrame) or not frame.columns.is_unique or len(frame) != 1:
        return result
    result["response_shape"] = "SINGLE_ROW"
    row = frame.to_dict("records")[0]
    currency = row.get("currency")
    if "currency" in row:
        result["display_currency"] = (currency if isinstance(currency, str) and currency in
                                      FUNDS_DIAGNOSTIC_VALUES["display_currency"] else
                                      "UNAVAILABLE" if currency is None else "UNRECOGNIZED")
    for key in ("cash", "us_cash"):
        if key not in row:
            continue
        value = row[key]
        if value is None or (isinstance(value, str) and value in {"N/A", "NONE", ""}):
            result[key + "_state"] = "UNAVAILABLE"
        else:
            try:
                number(value)
                result[key + "_state"] = "FINITE"
            except SimulationError:
                result[key + "_state"] = "INVALID"
    return result


CASH_BASES = frozenset({"USD_CURRENCY_BALANCE", "LEGACY_DISPLAY_USD"})


def select_usd_cash(frame: Any) -> tuple[Decimal, str]:
    """Prefer actual USD balance; never relabel requested/displayed currency.

    Missing/unavailable explicit USD may use the original strictly USD-labelled
    cash path, but as a DIFFERENT compatibility basis. Invalid explicit USD is
    a hard failure, not a reason to fall back to an otherwise valid display sum.
    """
    row = one_row(frame, set())
    state = funds_diagnostic(frame)["us_cash_state"]
    if state == "FINITE":
        return number(row["us_cash"]), "USD_CURRENCY_BALANCE"
    if state == "INVALID":
        raise SimulationError("USD_CASH_INVALID")
    row = one_row(frame, {"cash", "currency"})
    if not isinstance(row["currency"], str) or row["currency"] != "USD":
        raise SimulationError("CASH_CURRENCY_NOT_USD")
    try:
        return number(row["cash"]), "LEGACY_DISPLAY_USD"
    except SimulationError:
        raise SimulationError("USD_CASH_UNAVAILABLE") from None


def cash_basis(snapshot: dict[str, Any]) -> str:
    """The published original v1 baseline had strict USD display-cash semantics."""
    basis = snapshot.get("cash_basis", "LEGACY_DISPLAY_USD")
    if (snapshot.get("currency") != "USD" or not isinstance(basis, str)
            or basis not in CASH_BASES):
        raise SimulationError("CASH_BASIS_UNVERIFIED")
    return basis


def records(frame: Any, required: set[str]) -> list[dict[str, Any]]:
    from pandas import DataFrame

    if (not isinstance(frame, DataFrame) or not frame.columns.is_unique
            or not required.issubset(frame.columns)):
        raise SimulationError("BROKER_RESPONSE_SCHEMA_MISMATCH")
    return frame.to_dict("records")


def check_progress(snapshot: dict[str, Any], previous: list[dict[str, Any]]) -> None:
    """Reject stale or regressing cumulative observations, never sum snapshots."""
    for old in previous:
        if old["kind"] not in OBSERVATIONS:
            continue
        if old["order_id"] != snapshot["order_id"]:
            raise SimulationError("AMBIGUOUS_BROKER_ORDER")
        if ("dealt_qty" in old and "dealt_qty" in snapshot
                and number(snapshot["dealt_qty"]) < number(old["dealt_qty"])):
            raise SimulationError("CUMULATIVE_FILL_REGRESSION")
        if old["order_status"] == "FILLED_PART" and snapshot["order_status"] in UNFILLED:
            raise SimulationError("WORKING_STATUS_REGRESSION")
        if (old["order_status"] in TERMINAL
                and snapshot["order_status"] != old["order_status"]):
            raise SimulationError("TERMINAL_STATUS_REGRESSION")
        if (old.get("updated_time") and snapshot.get("updated_time")
                and datetime.fromisoformat(snapshot["updated_time"])
                < datetime.fromisoformat(old["updated_time"])):
            raise SimulationError("STALE_ORDER_OBSERVATION")
        if ("dealt_qty" in old and "dealt_avg_price" in old
                and number(old["dealt_qty"]) > 0
                and snapshot.get("dealt_qty") is not None
                and number(old["dealt_qty"]) == number(snapshot["dealt_qty"])
                and number(old["dealt_avg_price"]) != number(snapshot.get("dealt_avg_price"))):
            raise SimulationError("CUMULATIVE_PRICE_REVISION_UNRESOLVED")


def complete_snapshot(row: dict[str, Any], intent: BuyIntent) -> dict[str, Any]:
    snapshot = order_snapshot(row, intent)
    status = snapshot["order_status"]
    filled, average = number(snapshot.get("dealt_qty")), number(snapshot.get("dealt_avg_price"))
    if status not in WORKING | TERMINAL:
        raise SimulationError("UNKNOWN_ORDER_STATUS")
    if ((status == "FILLED_ALL" and filled != intent.qty)
            or (status in {"FILLED_PART", "CANCELLED_PART"} and not 0 < filled < intent.qty)
            or (status in UNFILLED | {"CANCELLED_ALL", "FAILED"} and filled != 0)
            or (filled == 0 and average != 0)):
        raise SimulationError("ORDER_STATUS_FILL_CONFLICT")
    if not isinstance(snapshot.get("updated_time"), str) or not snapshot["updated_time"]:
        raise SimulationError("ORDER_UPDATE_TIME_MISSING")
    datetime.fromisoformat(snapshot["updated_time"])  # Malformed time cannot rank evidence.
    return snapshot


class PaperRecovery(PaperExecution):
    def _open_orders(self) -> list[dict[str, Any]]:
        return records(self._call("order_list_query", order_market=self.session._sdk.TrdMarket.US,
                                  refresh_cache=True), {"order_id", "order_status", "remark"})

    def recover(self, intent_id: str) -> dict[str, Any]:
        """Locate a lost ACK by exact remark; missing or ambiguous is NOT rejection."""
        intent = self.journal.intent(intent_id)
        previous = self.journal.events(intent_id)
        hints = {item["order_id"] for item in previous
                 if item["kind"] in OBSERVATIONS | {"SUBMISSION_RECEIPT"}}
        try:
            if len(hints) > 1:
                raise SimulationError("AMBIGUOUS_BROKER_ORDER")
            def attributable(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
                return [row for row in rows if row.get("remark") == intent.remark
                        or row.get("order_id") in hints]

            rows = attributable(self._open_orders())
            source = "CURRENT_ORDER_QUERY"
            if not rows:
                submitted = next(item for item in previous if item["kind"] == "SUBMISSION_INTENT")
                start = datetime.fromisoformat(submitted["recorded_at_utc"])
                now = self.clock()
                if (start.utcoffset() is None or now.utcoffset() is None
                        or not timedelta(0) <= now - start <= timedelta(days=31)):
                    raise SimulationError("HISTORY_WINDOW_UNSUPPORTED")
                zone = ZoneInfo("America/New_York")
                frame = self._call("history_order_list_query", code=intent.symbol,
                                   order_market=self.session._sdk.TrdMarket.US,
                                   start=start.astimezone(zone).strftime("%Y-%m-%d 00:00:00"),
                                   end=now.astimezone(zone).strftime("%Y-%m-%d %H:%M:%S"))
                rows = attributable(records(frame, {"order_id", "order_status", "remark"}))
                source = "HISTORICAL_ORDER_QUERY"
            if not rows:
                raise SimulationError("SUBMISSION_OUTCOME_UNKNOWN")
            snapshots = [complete_snapshot(row, intent) for row in rows]
            # Identical duplicates are harmless; contradictory returned rows are not.
            unique = {json.dumps(item, sort_keys=True) for item in snapshots}
            if len(unique) != 1 or (hints and snapshots[0]["order_id"] not in hints):
                raise SimulationError("AMBIGUOUS_BROKER_ORDER")
            snapshot = snapshots[0]
            check_progress(snapshot, previous)
            self.journal.append("ORDER_OBSERVATION", intent_id, source=source, **snapshot)
            return snapshot
        except Exception as exc:
            self.journal.append("RECOVERY_FAILED", intent_id,
                                error_code=str(exc) if isinstance(exc, SimulationError) else "RECOVERY_UNAVAILABLE",
                                error_type=type(exc).__name__)
            raise SimulationError(str(exc) if isinstance(exc, SimulationError) else "RECOVERY_UNAVAILABLE") from None

    def observe(self, intent_id: str) -> dict[str, Any]:
        # Inherited cancellation still requires a fresh, fully attributed query.
        return self.recover(intent_id)

    def account_snapshot(self) -> dict[str, Any]:
        started = self.clock().isoformat()
        positions: dict[str, str] = {}
        rows = records(self._call("position_list_query", refresh_cache=True),
                       {"code", "qty", "position_side"})
        for row in rows:
            code, qty = row["code"], number(row["qty"])
            if not isinstance(code, str) or not code or code in positions:
                raise SimulationError("AMBIGUOUS_POSITION")
            if row["position_side"] != "LONG" or qty < 0:
                raise SimulationError("POSITION_OUTSIDE_LONG_SCOPE")
            positions[code] = str(qty)
        frame = self._call("accinfo_query", refresh_cache=True, currency=self.session._sdk.Currency.USD)
        self.journal.append("FUNDS_RESPONSE", None, **funds_diagnostic(frame))
        cash, basis = select_usd_cash(frame)
        snapshot = {"started_at_utc": started, "finished_at_utc": self.clock().isoformat(),
                    "positions": positions, "cash": str(cash), "currency": "USD", "cash_basis": basis,
                    "atomic_snapshot": False, "fees": "NOT_OBSERVED", "cash_flows": "NOT_OBSERVED"}
        self.journal.append("ACCOUNT_OBSERVATION", None, **snapshot)
        return snapshot

    def baseline(self) -> dict[str, Any]:
        if self.journal.intentions() or any(e["kind"] == "ACCOUNT_BASELINE" for e in self.journal.events()):
            raise SimulationError("BASELINE_MUST_PRECEDE_INTENT_AND_NOT_BE_REPLACED")
        for row in self._open_orders():
            if row["order_status"] not in TERMINAL:
                raise SimulationError("BASELINE_HAS_WORKING_OR_UNKNOWN_ORDERS")
        snapshot = self.account_snapshot()
        for row in self._open_orders():
            if row["order_status"] not in TERMINAL:
                raise SimulationError("BASELINE_HAS_WORKING_OR_UNKNOWN_ORDERS")
        # Single writer; reserve/stop admission remains atomic in the S2 journal.
        with self.journal._db:
            self.journal._db.execute("BEGIN IMMEDIATE")
            if self.journal.intentions() or any(e["kind"] == "ACCOUNT_BASELINE" for e in self.journal.events()):
                raise SimulationError("BASELINE_MUST_PRECEDE_INTENT_AND_NOT_BE_REPLACED")
            self.journal._insert_event("ACCOUNT_BASELINE", None, snapshot)
        return {"result": "BASELINE_RECORDED", "orders_sent": False, "atomic_snapshot": False}

    def reconcile(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "result": "BLOCKED", "stopped": self.journal.stopped,
            "new_orders_authorized": False, "fees": "NOT_OBSERVED",
            "cash_flows": "NOT_OBSERVED", "atomic_snapshot": False,
            "execution_detail": "CUMULATIVE_ORDER_ONLY", "independent_market_data": "NOT_SUPPLIED",
        }
        try:
            baselines = [e for e in self.journal.events() if e["kind"] == "ACCOUNT_BASELINE"]
            if len(baselines) != 1:
                raise SimulationError("BASELINE_MISSING_OR_AMBIGUOUS")
            intents = self.journal.intentions()
            before = [self.recover(item.intent_id) for item in intents]
            account = self.account_snapshot()
            result.update(baseline_cash_basis=cash_basis(baselines[0]), cash_basis=cash_basis(account))
            if result["baseline_cash_basis"] != result["cash_basis"]:
                raise SimulationError("CASH_BASIS_CHANGED")
            after = [self.recover(item.intent_id) for item in intents]
            if before != after:
                raise SimulationError("ORDER_CHANGED_DURING_ACCOUNT_SNAPSHOT")
            owned = {order["order_id"] for order in after}
            if any(row["order_status"] not in TERMINAL and row["order_id"] not in owned
                   for row in self._open_orders()):
                raise SimulationError("UNOWNED_WORKING_OR_UNKNOWN_ORDER")
            expected = {code: number(qty) for code, qty in baselines[0]["positions"].items()}
            expected_cash = number(baselines[0]["cash"])
            for intent, order in zip(intents, after):
                qty = number(order["dealt_qty"])
                expected[intent.symbol] = expected.get(intent.symbol, number(0)) + qty
                expected_cash -= qty * number(order["dealt_avg_price"])
            actual = {code: number(qty) for code, qty in account["positions"].items()}
            delta = {code: str(actual.get(code, number(0)) - expected.get(code, number(0)))
                     for code in sorted(actual.keys() | expected.keys())}
            residual = number(account["cash"]) - expected_cash
            result.update(position_residuals=delta, cash_residual_usd=str(residual),
                          cash_expected_before_unobserved_fees_usd=str(expected_cash),
                          orders=after, account_observation=account)
            if any(number(value) != 0 for value in delta.values()) or residual != 0:
                raise SimulationError("ACCOUNT_RESIDUAL_UNEXPLAINED")
            if any(order["order_status"] not in TERMINAL for order in after):
                raise SimulationError("OWNED_ORDER_STILL_WORKING")
            # A conditional observation match, never complete-account or live readiness.
            result["result"] = "OBSERVATIONS_MATCH"
        except Exception as exc:
            result.update(error_code=str(exc) if isinstance(exc, SimulationError) else "RECONCILIATION_UNAVAILABLE",
                          error_type=type(exc).__name__)
        self.journal.append("RECONCILIATION", None, **result)
        return result

    def stop(self, *, cancel_owned: bool = False, execute_simulate: bool = False) -> dict[str, Any]:
        self.journal.stop()  # Persist first, even if opt-in, connection or cancel fails.
        results = []
        if cancel_owned:
            if execute_simulate is not True:
                raise SimulationError("EXPLICIT_SIMULATION_OPT_IN_REQUIRED")
            for intent in self.journal.intentions():
                try:
                    results.append(self.cancel(intent.intent_id, execute_simulate=True))
                except Exception as exc:
                    results.append({"result": "CANCEL_NOT_CONFIRMED",
                                    "error_code": str(exc) if isinstance(exc, SimulationError) else "STOP_CANCEL_FAILED"})
        return {"result": "STOPPED", "stopped": True, "cancel_results": results,
                "positions_liquidated": False, "new_orders_authorized": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("baseline", "recover", "reconcile", "stop"))
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--intent-id")
    parser.add_argument("--port", type=int, default=11111)
    parser.add_argument("--security-firm", default="NONE")
    parser.add_argument("--cancel-owned", action="store_true")
    parser.add_argument("--execute-simulate", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "recover" and not args.intent_id:
        parser.error("recover requires --intent-id")
    if args.cancel_owned and (args.action != "stop" or not args.execute_simulate):
        parser.error("--cancel-owned requires stop and --execute-simulate")
    stopped = False
    try:
        with PaperJournal(args.journal) as journal:
            stopped = journal.stopped
            if args.action == "stop":
                journal.stop()  # This path needs neither OpenD nor an available SDK.
                stopped = True
            if args.action == "stop" and not args.cancel_owned:
                result = {"result": "STOPPED", "stopped": True, "orders_sent": False}
            else:
                with SimulationAccountSession(account_id=journal.account_id, port=args.port,
                                              security_firm=args.security_firm) as session:
                    recovery = PaperRecovery(session, journal)
                    if args.action == "recover":
                        recovery.recover(args.intent_id)
                        result = {"result": "ORDER_RECOVERED", "new_orders_authorized": False}
                    elif args.action == "stop":
                        result = recovery.stop(cancel_owned=True, execute_simulate=True)
                    else:
                        result = getattr(recovery, args.action)()
                    # Full account/order details stay in the private journal only.
            public = {key: result[key] for key in ("result", "stopped", "error_code", "new_orders_authorized")
                      if key in result}
            if "cancel_results" in result:
                public["cancel_results"] = [{"result": r["result"], "error_code": r.get("error_code")}
                                             for r in result["cancel_results"]]
            print(json.dumps(public, sort_keys=True))
            failed_cancel = any(r["result"] == "CANCEL_NOT_CONFIRMED" for r in result.get("cancel_results", []))
            return 1 if result["result"] == "BLOCKED" or failed_cancel else 0
    except Exception as exc:
        print(json.dumps({"result": "NOT_VERIFIED", "stopped": stopped,
                          "error_code": str(exc) if isinstance(exc, SimulationError) else "RECOVERY_OPERATION_FAILED"}),
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
