"""Bounded owner-operated paper orders; not an unattended strategy runner.

One buy intention per journal, one whole share, at most USD 1,000 limit notional.
A durable intention is never resubmitted, even after an unacknowledged outcome.
Journals are local/account-sensitive; do not publish them or reset them to retry.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .moomoo_simulation import SimulationAccountSession, SimulationError, _account_id

SCHEMA = "market_vault_paper_journal_v1"
SYMBOLS = ("US.SPY", "US.QQQ")
LIMITS = {"max_intentions": 1, "max_qty": 1, "max_notional_usd": "1000.00",
          "side": "BUY", "order_type": "NORMAL", "time_in_force": "DAY", "session": "RTH"}
TERMINAL = frozenset({"FILLED_ALL", "CANCELLED_ALL", "CANCELLED_PART", "FAILED", "DISABLED", "DELETED"})
CANCELLABLE = frozenset({"SUBMITTED", "FILLED_PART"})


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def number(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise SimulationError("INVALID_BROKER_NUMBER")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise SimulationError("INVALID_BROKER_NUMBER") from None
    if not result.is_finite():
        raise SimulationError("INVALID_BROKER_NUMBER")
    return result


def require_rth(now: datetime) -> None:
    from .normalization.rth_calendar import resolve_exchange_rth_session

    if now.tzinfo is None or now.utcoffset() is None:
        raise SimulationError("CLOCK_MUST_BE_AWARE")
    local = now.astimezone(ZoneInfo("America/New_York"))
    schedule = resolve_exchange_rth_session(local.date())
    if (schedule.classification not in {"NORMAL", "EARLY_CLOSE"}
            or not schedule.open_time <= local.time() < schedule.close_time):
        raise SimulationError("OUTSIDE_SUPPORTED_RTH")


@dataclass(frozen=True)
class BuyIntent:
    intent_id: str
    symbol: str
    price: str
    qty: int = 1

    def validated(self) -> BuyIntent:
        if not isinstance(self.intent_id, str) or re.fullmatch(r"[0-9a-f]{32}", self.intent_id) is None:
            raise SimulationError("INTENT_ID_MUST_BE_UUID_HEX")
        if self.symbol not in SYMBOLS:
            raise SimulationError("SYMBOL_OUTSIDE_PAPER_SCOPE")
        if type(self.qty) is not int or self.qty != 1:
            raise SimulationError("PAPER_QUANTITY_LIMIT")
        price = number(self.price)
        if not Decimal("1.00") <= price <= Decimal(LIMITS["max_notional_usd"]):
            raise SimulationError("PAPER_NOTIONAL_LIMIT")
        if price != price.quantize(Decimal("0.01")):
            raise SimulationError("LIMIT_PRICE_REQUIRES_CENTS")
        return BuyIntent(self.intent_id, self.symbol, format(price, ".2f"), self.qty)

    @property
    def remark(self) -> str:
        return "mv-" + self.intent_id


class PaperJournal:
    """Small SQLite journal: only insertions, no reset, deletion or migration.

    Opening an existing journal never creates a missing database. SQLite commits
    persist the intention before the broker boundary. Only one intention can be
    admitted, including across concurrent callers and process restart.
    """

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self._db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=0)
        self._db.row_factory = sqlite3.Row
        try:
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.execute("PRAGMA synchronous=FULL")
            rows = self._db.execute("SELECT payload FROM metadata").fetchall()
            if len(rows) != 1:
                raise SimulationError("JOURNAL_METADATA_MISMATCH")
            self.metadata = json.loads(rows[0]["payload"])
            if (self.metadata["schema"] != SCHEMA or self.metadata["limits"] != LIMITS
                    or self.metadata["environment"] != "SIMULATE"):
                raise SimulationError("JOURNAL_METADATA_MISMATCH")
            self.account_id = _account_id(int(self.metadata["account_id"]))
            # Do not turn an incomplete or unrelated database into a new run.
            self._db.execute("SELECT intent_id, payload FROM intentions LIMIT 1")
            self._db.execute("SELECT seq, kind, intent_id, payload FROM events LIMIT 1")
        except BaseException:
            self._db.close()
            raise

    @classmethod
    def create(cls, path: Path, account_id: int) -> PaperJournal:
        identifier = _account_id(account_id)
        # Create exclusively; even an empty existing file is not a fresh run.
        with path.open("xb"):
            pass
        db = sqlite3.connect(path)
        try:
            with db:
                db.execute("CREATE TABLE metadata (payload TEXT NOT NULL)")
                db.execute("CREATE TABLE intentions (intent_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
                db.execute("CREATE TABLE events (seq INTEGER PRIMARY KEY, kind TEXT NOT NULL, "
                           "intent_id TEXT REFERENCES intentions(intent_id), payload TEXT NOT NULL)")
                meta = {"schema": SCHEMA, "environment": "SIMULATE", "account_id": str(identifier),
                        "limits": LIMITS, "created_at_utc": utc_now().isoformat()}
                db.execute("INSERT INTO metadata VALUES (?)", (json.dumps(meta, sort_keys=True),))
        finally:
            db.close()
        return cls(path)

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> PaperJournal:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _insert_event(self, kind: str, intent_id: str | None, payload: dict[str, Any]) -> None:
        body = {"recorded_at_utc": utc_now().isoformat(), **payload}
        self._db.execute("INSERT INTO events(kind,intent_id,payload) VALUES (?,?,?)",
                         (kind, intent_id, json.dumps(body, sort_keys=True, allow_nan=False)))

    def append(self, kind: str, intent_id: str | None, **payload: Any) -> None:
        with self._db:
            self._insert_event(kind, intent_id, payload)

    def events(self, intent_id: str | None = None) -> list[dict[str, Any]]:
        rows = (self._db.execute("SELECT * FROM events ORDER BY seq") if intent_id is None else
                self._db.execute("SELECT * FROM events WHERE intent_id=? ORDER BY seq", (intent_id,)))
        return [{"seq": row["seq"], "kind": row["kind"], "intent_id": row["intent_id"],
                 **json.loads(row["payload"])} for row in rows]

    def intentions(self) -> list[BuyIntent]:
        return [BuyIntent(**json.loads(row["payload"])).validated()
                for row in self._db.execute("SELECT payload FROM intentions ORDER BY intent_id")]

    def intent(self, intent_id: str) -> BuyIntent:
        matches = [item for item in self.intentions() if item.intent_id == intent_id]
        if len(matches) != 1:
            raise SimulationError("INTENTION_NOT_OWNED")
        return matches[0]

    @property
    def stopped(self) -> bool:
        return self._db.execute("SELECT 1 FROM events WHERE kind='EMERGENCY_STOP' LIMIT 1").fetchone() is not None

    def require_running(self) -> None:
        if self.stopped:
            raise SimulationError("PAPER_JOURNAL_STOPPED")
        latest = self._db.execute("SELECT payload FROM events WHERE kind='RECONCILIATION' "
                                  "ORDER BY seq DESC LIMIT 1").fetchone()
        if latest is not None and json.loads(latest["payload"]).get("result") != "OBSERVATIONS_MATCH":
            raise SimulationError("PAPER_RECONCILIATION_BLOCKED")

    def stop(self) -> None:
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            if not self.stopped:
                self._insert_event("EMERGENCY_STOP", None, {"automatic_resume": False})

    def reserve(self, intent: BuyIntent) -> None:
        intent = intent.validated()
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self.require_running()
            if self._db.execute("SELECT 1 FROM intentions WHERE intent_id=?", (intent.intent_id,)).fetchone():
                raise SimulationError("INTENTION_ALREADY_RECORDED_NO_RESUBMIT")
            if self._db.execute("SELECT 1 FROM intentions").fetchone():
                raise SimulationError("PAPER_RUN_INTENTION_LIMIT")
            self._db.execute("INSERT INTO intentions VALUES (?,?)",
                             (intent.intent_id, json.dumps(asdict(intent), sort_keys=True)))
            self._insert_event("SUBMISSION_INTENT", intent.intent_id, {"remark": intent.remark})

    def reserve_cancel(self, intent_id: str, order_id: str) -> None:
        self.intent(intent_id)
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            if self._db.execute("SELECT 1 FROM events WHERE intent_id=? AND kind='CANCEL_INTENT'",
                                (intent_id,)).fetchone():
                raise SimulationError("CANCEL_ALREADY_ATTEMPTED_QUERY_OUTCOME")
            self._insert_event("CANCEL_INTENT", intent_id, {"order_id": order_id})

    def bound_order_id(self, intent_id: str) -> str:
        self.intent(intent_id)
        identifiers = {item["order_id"] for item in self.events(intent_id)
                       if item["kind"] in {"SUBMISSION_ACK", "ORDER_OBSERVATION"}}
        if len(identifiers) != 1:
            raise SimulationError("SUBMISSION_OUTCOME_UNKNOWN")
        return identifiers.pop()

    def query_order_id(self, intent_id: str) -> str:
        self.intent(intent_id)
        # A sparse placement receipt is a query hint, never cancel authority.
        identifiers = {item["order_id"] for item in self.events(intent_id)
                       if item["kind"] in {"SUBMISSION_RECEIPT", "SUBMISSION_ACK", "ORDER_OBSERVATION"}}
        if len(identifiers) != 1:
            raise SimulationError("SUBMISSION_OUTCOME_UNKNOWN")
        return identifiers.pop()


def one_row(frame: Any, columns: set[str]) -> dict[str, Any]:
    from pandas import DataFrame

    if (not isinstance(frame, DataFrame) or not frame.columns.is_unique
            or len(frame) != 1 or not columns.issubset(frame.columns)):
        raise SimulationError("BROKER_RESPONSE_SCHEMA_MISMATCH")
    return frame.to_dict("records")[0]


def order_snapshot(row: dict[str, Any], intent: BuyIntent, order_id: str | None = None) -> dict[str, Any]:
    """Allowlisted cumulative order observation, not a fabricated execution fill."""
    oid = row.get("order_id")
    if not isinstance(oid, str) or not oid.strip() or (order_id is not None and oid != order_id):
        raise SimulationError("BROKER_ORDER_ID_MISMATCH")
    if (row.get("code") != intent.symbol or row.get("trd_side") != "BUY"
            or number(row.get("qty")) != intent.qty or number(row.get("price")) != number(intent.price)
            or row.get("remark") != intent.remark or row.get("order_type") != "NORMAL"):
        raise SimulationError("BROKER_ORDER_INTENTION_MISMATCH")
    result = {"order_id": oid, "order_status": str(row.get("order_status", "UNKNOWN"))}
    # Capture only documented numeric/time fields. No account columns or error text.
    for name in ("dealt_qty", "dealt_avg_price"):
        if name in row:
            result[name] = str(number(row[name]))
    if "dealt_qty" in result:
        filled = number(result["dealt_qty"])
        if not 0 <= filled <= intent.qty:
            raise SimulationError("INVALID_CUMULATIVE_FILL_QUANTITY")
        if "dealt_avg_price" in result:
            average = number(result["dealt_avg_price"])
            if average < 0 or (filled > 0 and average <= 0):
                raise SimulationError("INVALID_CUMULATIVE_FILL_PRICE")
    for name in ("create_time", "updated_time"):
        if isinstance(row.get(name), str):
            result[name] = row[name]
    return result


class PaperExecution:
    def __init__(self, session: SimulationAccountSession, journal: PaperJournal,
                 *, clock: Callable[[], datetime] = utc_now) -> None:
        self.session, self.journal, self.clock = session, journal, clock

    def _call(self, method: str, **kwargs: Any) -> Any:
        account = self.session.verify()
        if account.account_id != self.journal.account_id:
            raise SimulationError("JOURNAL_ACCOUNT_MISMATCH")
        if method == "place_order":
            self.journal.require_running()
        # There is deliberately no caller-selectable environment or account index.
        ret, frame = getattr(self.session._ctx, method)(
            trd_env=self.session._sdk.TrdEnv.SIMULATE,
            acc_id=account.account_id, **kwargs,
        )
        if ret != self.session._sdk.RET_OK:
            raise SimulationError("BROKER_OPERATION_FAILED")
        return frame

    def submit(self, intent: BuyIntent, *, execute_simulate: bool = False) -> dict[str, Any]:
        if execute_simulate is not True:
            raise SimulationError("EXPLICIT_SIMULATION_OPT_IN_REQUIRED")
        intent = intent.validated()
        self.journal.require_running()
        require_rth(self.clock())
        # Check duplicates before a network preflight as well as atomically at reserve.
        if self.journal.intentions():
            self.journal.reserve(intent)  # Always refuses; never replaces an old intention.
        sdk = self.session._sdk
        try:
            limits = one_row(self._call(
                "acctradinginfo_query", order_type=sdk.OrderType.NORMAL, code=intent.symbol,
                price=float(intent.price), adjust_limit=0, session=sdk.Session.RTH,
            ), {"max_cash_buy", "max_buy_back"})
            if number(limits["max_cash_buy"]) < intent.qty or number(limits["max_buy_back"]) != 0:
                raise SimulationError("CASH_ONLY_LONG_BUY_UNAVAILABLE")
        except Exception as exc:
            if isinstance(exc, SimulationError):
                raise
            raise SimulationError("CASH_PREFLIGHT_FAILED") from None
        self.journal.reserve(intent)  # COMMITTED before a mutating SDK call.
        attempted = False
        try:
            require_rth(self.clock())  # A slow preflight cannot carry us past the close.
            self.journal.append("SUBMISSION_CALL", intent.intent_id)
            attempted = True
            frame = self._call(
                "place_order", price=float(intent.price), qty=intent.qty, code=intent.symbol,
                trd_side=sdk.TrdSide.BUY, order_type=sdk.OrderType.NORMAL, adjust_limit=0,
                remark=intent.remark, time_in_force=sdk.TimeInForce.DAY,
                fill_outside_rth=False, session=sdk.Session.RTH,
            )
            row = one_row(frame, {"order_id"})
            oid = row["order_id"]
            if not isinstance(oid, str) or not oid.strip():
                raise SimulationError("BROKER_ORDER_ID_MISMATCH")
            # The SDK may return only an ID before its cached order row appears.
            self.journal.append("SUBMISSION_RECEIPT", intent.intent_id,
                                order_id=oid, attribution="UNVERIFIED")
            snapshot = order_snapshot(row, intent)
            self.journal.append("SUBMISSION_ACK", intent.intent_id, **snapshot)
        except (Exception, KeyboardInterrupt) as exc:
            self.journal.append("SUBMISSION_UNKNOWN" if attempted else "SUBMISSION_NOT_SENT",
                                intent.intent_id, error_type=type(exc).__name__)
            raise SimulationError("SUBMISSION_OUTCOME_UNKNOWN" if attempted else "SUBMISSION_NOT_SENT") from None
        return {"result": "SUBMISSION_ACKNOWLEDGED", "intent_id": intent.intent_id,
                "order_id": snapshot["order_id"], "final_outcome": "NOT_VERIFIED"}

    def observe(self, intent_id: str) -> dict[str, Any]:
        intent = self.journal.intent(intent_id)
        oid = self.journal.query_order_id(intent_id)
        try:
            frame = self._call("order_list_query", order_id=oid,
                               order_market=self.session._sdk.TrdMarket.US, refresh_cache=True)
            snapshot = order_snapshot(one_row(frame, {"order_id"}), intent, oid)
            from .moomoo_simulation_recovery import check_progress
            check_progress(snapshot, self.journal.events(intent_id))
        except Exception as exc:
            self.journal.append("ORDER_QUERY_FAILED", intent_id, error_type=type(exc).__name__)
            raise SimulationError("ORDER_OBSERVATION_UNAVAILABLE") from None
        self.journal.append("ORDER_OBSERVATION", intent_id, **snapshot)
        return snapshot

    def cancel(self, intent_id: str, *, execute_simulate: bool = False) -> dict[str, Any]:
        if execute_simulate is not True:
            raise SimulationError("EXPLICIT_SIMULATION_OPT_IN_REQUIRED")
        snapshot = self.observe(intent_id)  # Never accept an arbitrary broker order ID.
        if snapshot["order_status"] in TERMINAL:
            return {"result": "ALREADY_TERMINAL", **snapshot}
        if snapshot["order_status"] not in CANCELLABLE:
            raise SimulationError("ORDER_NOT_IN_VERIFIED_CANCELLABLE_STATE")
        self.journal.reserve_cancel(intent_id, snapshot["order_id"])
        try:
            frame = self._call(
                "modify_order", modify_order_op=self.session._sdk.ModifyOrderOp.CANCEL,
                order_id=snapshot["order_id"], qty=0, price=0, adjust_limit=0,
            )
            row = one_row(frame, {"trd_env", "order_id"})
            if row["trd_env"] != "SIMULATE" or row["order_id"] != snapshot["order_id"]:
                raise SimulationError("CANCEL_RESPONSE_MISMATCH")
            self.journal.append("CANCEL_ACK", intent_id, order_id=snapshot["order_id"])
        except (Exception, KeyboardInterrupt) as exc:
            self.journal.append("CANCEL_UNKNOWN", intent_id, error_type=type(exc).__name__)
            raise SimulationError("CANCEL_OUTCOME_UNKNOWN") from None
        return {"result": "CANCEL_ACKNOWLEDGED", "final_outcome": "NOT_VERIFIED"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "submit", "observe", "cancel"))
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--account-id", type=int, help="Only for init; never exported")
    parser.add_argument("--port", type=int, default=11111)
    parser.add_argument("--security-firm", default="NONE")
    parser.add_argument("--intent-id")
    parser.add_argument("--symbol", choices=SYMBOLS)
    parser.add_argument("--price", help="Explicit limit price, not an automatic signal")
    parser.add_argument("--execute-simulate", action="store_true")
    args = parser.parse_args(argv)
    if args.action in {"submit", "cancel"} and not args.execute_simulate:
        parser.error("--execute-simulate is required; no orders were sent")
    if args.action != "init" and args.account_id is not None:
        parser.error("Existing journals pin the account; --account-id is only for init")
    if args.action != "init" and not args.intent_id:
        parser.error("--intent-id is required")
    try:
        if args.action == "init":
            if args.journal.exists():
                raise SimulationError("JOURNAL_ALREADY_EXISTS")
            with SimulationAccountSession(account_id=args.account_id, port=args.port,
                                          security_firm=args.security_firm) as session:
                with PaperJournal.create(args.journal, session.account.account_id):
                    pass
            result = {"result": "JOURNAL_CREATED", "orders_sent": False, "limits": LIMITS}
        else:
            intent = (BuyIntent(args.intent_id, args.symbol, args.price).validated()
                      if args.action == "submit" else None)
            with PaperJournal(args.journal) as journal:
                with SimulationAccountSession(account_id=journal.account_id, port=args.port,
                                              security_firm=args.security_firm) as session:
                    execution = PaperExecution(session, journal)
                    if args.action == "submit":
                        result = execution.submit(intent, execute_simulate=True)
                    elif args.action == "cancel":
                        result = execution.cancel(args.intent_id, execute_simulate=True)
                    else:
                        result = execution.observe(args.intent_id)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except Exception as exc:
        code = str(exc) if isinstance(exc, SimulationError) else "PAPER_OPERATION_FAILED"
        print(json.dumps({"result": "NOT_VERIFIED", "error_code": code,
                          "error_type": type(exc).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
