"""US paper-account boundary and a read-only owner-local probe.

No connection on import; no trading unlock, order, or REAL-environment option.
The probe exports an allowlisted result, never raw account-list rows or IDs.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from numbers import Integral
from pathlib import Path
import sys
from typing import Any

from .moomoo_sdk import load_moomoo_sdk


class SimulationError(RuntimeError):
    """A static diagnostic code; arbitrary SDK error text is never forwarded."""


@dataclass(frozen=True)
class SimulationAccount:
    account_id: int = field(repr=False)
    simulation_type: str


def _account_id(value: Any) -> int:
    # Float account IDs may already have lost uint64 precision.
    if isinstance(value, bool) or not isinstance(value, Integral) or value <= 0:
        raise SimulationError("INVALID_ACCOUNT_ID")
    return int(value)


def select_simulation_account(frame: Any, account_id: int | None = None) -> SimulationAccount:
    """Select an explicit ID, or the sole eligible account; never the first row."""
    from pandas import DataFrame

    required = {"acc_id", "trd_env", "sim_acc_type", "trdmarket_auth", "acc_status"}
    if (not isinstance(frame, DataFrame) or not frame.columns.is_unique
            or not required.issubset(frame.columns)):
        raise SimulationError("ACCOUNT_SCHEMA_MISMATCH")
    if account_id is not None:
        account_id = _account_id(account_id)
    candidates: list[SimulationAccount] = []
    seen: set[int] = set()
    for row in frame.to_dict("records"):
        identifier = _account_id(row["acc_id"])
        if identifier in seen:
            raise SimulationError("DUPLICATE_ACCOUNT_ID")
        seen.add(identifier)
        markets = row["trdmarket_auth"]
        eligible = (
            row["trd_env"] == "SIMULATE"
            and row["acc_status"] == "ACTIVE"
            and row["sim_acc_type"] in {"STOCK", "STOCK_AND_OPTION"}
            and isinstance(markets, (list, tuple))
            and "US" in markets
        )
        if eligible and (account_id is None or identifier == account_id):
            candidates.append(SimulationAccount(identifier, row["sim_acc_type"]))
    if len(candidates) != 1:
        raise SimulationError("SIMULATION_ACCOUNT_NOT_UNIQUE" if account_id is None
                              else "PINNED_SIMULATION_ACCOUNT_UNAVAILABLE")
    return candidates[0]


class SimulationAccountSession:
    """One pinned US stock-capable simulation account across reconnects.

    The account ID stays local. A failed validation immediately clears readiness;
    reconnect never silently substitutes another account. Downstream simulation
    calls must revalidate, pass this ID and explicitly pass TrdEnv.SIMULATE.
    """

    def __init__(self, *, account_id: int | None = None, port: int = 11111,
                 security_firm: str = "NONE") -> None:
        if account_id is not None:
            account_id = _account_id(account_id)
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise SimulationError("INVALID_LOCAL_PORT")
        self._pinned_id = account_id
        self._port = port
        self._security_firm = security_firm
        self._ctx: Any = None
        self._sdk: Any = None
        self._metadata: dict[str, Any] = {}
        self._account: SimulationAccount | None = None
        self._verified = False

    @property
    def account(self) -> SimulationAccount:
        if not self._verified or self._account is None:
            raise SimulationError("SIMULATION_ACCOUNT_NOT_VERIFIED")
        return self._account

    def connect(self) -> SimulationAccount:
        self.close()
        try:
            loaded = load_moomoo_sdk()
            self._sdk = loaded["module"]
            firm = getattr(self._sdk.SecurityFirm, self._security_firm)
            # Fail before connecting if this SDK lacks the explicit environment.
            if self._sdk.TrdEnv.SIMULATE != "SIMULATE":
                raise SimulationError("UNSUPPORTED_SIMULATION_ENUM")
            self._metadata = {"sdk_module": loaded["module_name"], "sdk_version": loaded["version"]}
            self._ctx = self._sdk.OpenSecTradeContext(
                filter_trdmarket=self._sdk.TrdMarket.US,
                host="127.0.0.1", port=self._port, security_firm=firm,
            )
            return self.verify()
        except BaseException:
            self.close()
            raise

    def verify(self) -> SimulationAccount:
        self._verified = False
        if self._ctx is None:
            raise SimulationError("SIMULATION_NOT_CONNECTED")
        try:
            ret, frame = self._ctx.get_acc_list()
        except Exception:
            raise SimulationError("ACCOUNT_QUERY_FAILED") from None
        if ret != self._sdk.RET_OK:
            raise SimulationError("ACCOUNT_QUERY_FAILED")
        account = select_simulation_account(frame, self._pinned_id)
        self._pinned_id = account.account_id
        self._account = account
        self._verified = True
        return account

    def reconnect(self) -> SimulationAccount:
        return self.connect()

    def close(self) -> None:
        self._verified = False
        ctx, self._ctx = self._ctx, None
        if ctx is not None:
            try:
                ctx.close()
            except Exception:
                raise SimulationError("CONTEXT_CLOSE_FAILED") from None

    def __enter__(self) -> SimulationAccountSession:
        self.connect()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


def run_probe(*, account_id: int | None = None, port: int = 11111,
              security_firm: str = "NONE") -> dict[str, Any]:
    """Read account metadata twice across two connections; never place an order."""
    report: dict[str, Any] = {
        "schema": "market_vault_simulation_probe_v1",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0],
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "result": "NOT_VERIFIED", "environment": "SIMULATE", "market": "US",
        "account_id_exported": False, "orders_sent": False,
        "funds_or_positions_read": False, "reconnect_same_account": False,
        "independent_market_data": "NOT_SUPPLIED",
        "broker_order_lifecycle": "NOT_RUN",
    }
    try:
        with SimulationAccountSession(account_id=account_id, port=port,
                                      security_firm=security_firm) as session:
            initial = session.account
            second = session.reconnect()
            if initial.account_id != second.account_id:
                raise SimulationError("RECONNECT_ACCOUNT_CHANGED")
            report.update(session._metadata)
            report.update(result="ACCOUNT_VERIFIED", simulation_type=second.simulation_type,
                          reconnect_same_account=True)
    except Exception as exc:
        report["result"] = "NOT_VERIFIED"
        report["error_code"] = str(exc) if isinstance(exc, SimulationError) else "PROBE_FAILED"
        report["error_type"] = type(exc).__name__
    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-id", type=int, help="Optional explicit SIMULATE ID, kept local")
    parser.add_argument("--port", type=int, default=11111)
    parser.add_argument("--security-firm", default="NONE", help="SDK SecurityFirm name; no fallback")
    parser.add_argument("--output", type=Path, required=True, help="New JSON file; never overwritten")
    args = parser.parse_args(argv)
    try:
        # Refuse an existing destination before opening any SDK context.
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            report = run_probe(account_id=args.account_id, port=args.port,
                               security_firm=args.security_firm)
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    except OSError:
        print("OUTPUT_UNAVAILABLE: choose a new file in an existing directory", file=sys.stderr)
        return 2
    print(f"RESULT={report['result']}; ORDERS_SENT=false")
    return 0 if report["result"] == "ACCOUNT_VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
