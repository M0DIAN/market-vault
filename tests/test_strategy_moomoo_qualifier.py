from __future__ import annotations

from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pandas as pd
import pytest

from market_vault import moomoo_sdk
from market_vault import moomoo_simulation_qualifier as qualifier
from market_vault import moomoo_simulation_evidence as evidence
from market_vault.moomoo_simulation_orders import PaperJournal

NOW = datetime(2026, 10, 16, 15, 0, tzinfo=timezone.utc)


@pytest.fixture
def broker(monkeypatch):
    state = SimpleNamespace(env="SIMULATE", rows=[], cash="10000.00", positions=[], calls=[],
                            contexts=[], fail_funds=False, fail_place=False, fail_cancel=False,
                            invalid_position=False)

    class Context:
        def __init__(self, **kw):
            assert kw == dict(filter_trdmarket="US", host="127.0.0.1", port=11111, security_firm="NONE")
            self.closed = False
            state.contexts.append(self)

        def close(self):
            self.closed = True

        def get_acc_list(self):
            return 0, pd.DataFrame([dict(acc_id=987654321, trd_env=state.env, acc_status="ACTIVE",
                                        sim_acc_type="STOCK_AND_OPTION", trdmarket_auth=["US"])])

        def record(self, name, kw):
            assert kw["trd_env"] == "SIMULATE" and kw["acc_id"] == 987654321
            assert "acc_index" not in kw
            state.calls.append(name)

        def order_list_query(self, **kw):
            self.record("orders", kw)
            assert kw["refresh_cache"] is True
            return 0, pd.DataFrame(state.rows, columns=list(state.rows[0]) if state.rows else
                                   ["order_id", "order_status", "remark"])

        def position_list_query(self, **kw):
            self.record("positions", kw)
            if state.invalid_position:
                return 0, pd.DataFrame([{"unrecognized": "secret-position"}])
            return 0, pd.DataFrame(state.positions, columns=["code", "qty", "position_side"])

        def accinfo_query(self, **kw):
            self.record("funds", kw)
            assert kw["currency"] == "USD"
            if state.fail_funds:
                raise TimeoutError("password=private-secret")
            return 0, pd.DataFrame([{"cash": state.cash, "currency": "USD", "private": "private-secret"}])

        def acctradinginfo_query(self, **kw):
            self.record("capacity", kw)
            return 0, pd.DataFrame([dict(max_cash_buy=10, max_buy_back=0)])

        def place_order(self, **kw):
            self.record("place", kw)
            assert kw["qty"] == 1 and kw["session"] == "RTH" and kw["time_in_force"] == "DAY"
            state.rows = [dict(order_id="private-order", order_status="SUBMITTED", code=kw["code"],
                               price=kw["price"], qty=1, trd_side="BUY", order_type="NORMAL",
                               remark=kw["remark"], dealt_qty=0, dealt_avg_price=0,
                               updated_time="2026-10-16 11:00:00")]
            if state.fail_place:
                raise TimeoutError("private-secret")
            return 0, pd.DataFrame(state.rows)

        def modify_order(self, **kw):
            self.record("cancel", kw)
            assert kw["order_id"] == "private-order" and kw["modify_order_op"] == "CANCEL"
            if state.fail_cancel:
                raise TimeoutError("private-secret")
            return 0, pd.DataFrame([dict(order_id="private-order", trd_env="SIMULATE")])

    sdk = SimpleNamespace(OpenSecTradeContext=Context, OpenQuoteContext=object, RET_OK=0, __version__="10.09.6908",
                          SecurityFirm=SimpleNamespace(NONE="NONE"), TrdEnv=SimpleNamespace(SIMULATE="SIMULATE"),
                          TrdMarket=SimpleNamespace(US="US"), Currency=SimpleNamespace(USD="USD"),
                          Session=SimpleNamespace(RTH="RTH"), OrderType=SimpleNamespace(NORMAL="NORMAL"),
                          TrdSide=SimpleNamespace(BUY="BUY"), TimeInForce=SimpleNamespace(DAY="DAY"),
                          ModifyOrderOp=SimpleNamespace(CANCEL="CANCEL"))
    monkeypatch.setattr(moomoo_sdk, "_import_sdk_module", lambda: (sdk, "moomoo"))
    actual = qualifier.PaperRecovery
    # Only control the clock and external SDK; all execution/journal logic is real.
    monkeypatch.setattr(qualifier, "PaperRecovery", lambda s, j: actual(s, j, clock=lambda: NOW))
    return state


def run(tmp_path, action, *, extra=(), filename=None):
    out = tmp_path / (filename or f"{action}.json")
    code = qualifier.main([action, "--journal", str(tmp_path / "private.sqlite"),
                           "--output", str(out), *extra])
    return code, json.loads(out.read_text())


def submit_args():
    return ("--symbol", "US.SPY", "--price", "500.00", "--execute-simulate")


def test_actual_prepare_submit_reopen_check_stop_workflow_exports_no_account_or_ids(broker, tmp_path):
    code, prepared = run(tmp_path, "prepare")
    assert code == 0 and prepared["result"] == "PREPARED" and "place" not in broker.calls
    assert len(prepared["evidence"]["intentions"]) == 0
    code, submitted = run(tmp_path, "submit", extra=submit_args())
    assert code == 0 and submitted["result"] == "SUBMISSION_ACKNOWLEDGED"
    broker.rows[0].update(order_status="FILLED_ALL", dealt_qty=1, dealt_avg_price=499,
                          updated_time="2026-10-16 11:01:00")
    broker.positions, broker.cash = [dict(code="US.SPY", qty=1, position_side="LONG")], "9501.00"
    code, checked = run(tmp_path, "check")
    assert code == 0 and checked["result"] == "OBSERVATIONS_MATCH"
    code, stopped = run(tmp_path, "stop")
    assert code == 0 and stopped["evidence"]["stopped"]
    assert all(ctx.closed for ctx in broker.contexts)
    assert broker.calls.count("place") == 1 and "cancel" not in broker.calls
    assert not stopped["new_orders_authorized"] and stopped["broker_qualification"] == "NOT_ASSESSED"
    with PaperJournal(tmp_path / "private.sqlite") as journal:
        assert len(journal.intentions()) == 1 and journal.stopped
    text = json.dumps(stopped)
    for value in ("private-order", "987654321", "9501.00", "private-secret"):
        assert value not in text
    ends = [e for e in stopped["evidence"]["events"] if e["kind"] == "QUALIFICATION_FINISH"]
    assert len(ends) == 4 and all(float(e["elapsed_ms"]) >= 0 for e in ends)
    assert ends[0]["runtime"]["sdk_version"] == "10.09.6908"


@pytest.mark.parametrize("failure", ["funds", "schema", "real"])
def test_preparation_failure_never_sends_and_returns_static_diagnostic(broker, tmp_path, failure):
    broker.fail_funds = failure == "funds"
    broker.invalid_position = failure == "schema"
    broker.env = "REAL" if failure == "real" else "SIMULATE"
    code, report = run(tmp_path, "prepare")
    assert code == 1 and report["result"] == "FAILED" and "place" not in broker.calls
    assert "private-secret" not in json.dumps(report) and "secret-position" not in json.dumps(report)
    if failure != "real":
        assert report["evidence"]["stopped"]
        if failure == "schema":
            assert report["error_code"] == "BROKER_RESPONSE_SCHEMA_MISMATCH"


def test_missing_preparation_and_changed_cash_cannot_submit(broker, tmp_path):
    with PaperJournal.create(tmp_path / "private.sqlite", 987654321):
        pass
    code, report = run(tmp_path, "submit", extra=submit_args())
    assert code == 1 and report["error_code"] == "QUALIFICATION_PREPARATION_REQUIRED"
    assert "place" not in broker.calls
    other = tmp_path / "other"
    other.mkdir()
    assert run(other, "prepare")[0] == 0
    broker.cash = "9999"
    code, report = run(other, "submit", extra=submit_args())
    assert code == 1 and report["error_code"] == "QUALIFICATION_PREFLIGHT_BLOCKED"
    assert not report["evidence"]["intentions"] and "place" not in broker.calls


def test_unknown_submission_cannot_resend_but_can_recover_after_reopen(broker, tmp_path):
    assert run(tmp_path, "prepare")[0] == 0
    broker.fail_place = True
    code, report = run(tmp_path, "submit", extra=submit_args())
    assert code == 1 and report["error_code"] == "SUBMISSION_OUTCOME_UNKNOWN"
    assert report["evidence"]["stopped"] and len(report["evidence"]["intentions"]) == 1
    assert run(tmp_path, "submit", extra=submit_args(), filename="retry.json")[0] == 1
    code, report = run(tmp_path, "check")
    assert code == 1 and report["result"] == "BLOCKED"  # still working, not disappeared/rejected
    assert any(e["kind"] == "ORDER_OBSERVATION" for e in report["evidence"]["events"])
    assert broker.calls.count("place") == 1


def test_existing_report_blocks_submission_but_cannot_prevent_local_stop(broker, tmp_path):
    assert run(tmp_path, "prepare")[0] == 0
    prior = (tmp_path / "prepare.json").read_bytes()
    args = ["--journal", str(tmp_path / "private.sqlite"), "--output", str(tmp_path / "prepare.json")]
    assert qualifier.main(["submit", *args, *submit_args()]) == 1
    assert "place" not in broker.calls
    before = len(broker.contexts)
    assert qualifier.main(["stop", *args]) == 1
    assert len(broker.contexts) == before
    assert (tmp_path / "prepare.json").read_bytes() == prior
    with PaperJournal(tmp_path / "private.sqlite") as journal:
        assert journal.stopped


def test_optional_cancel_failure_preserves_stop_and_no_blind_retry(broker, tmp_path):
    assert run(tmp_path, "prepare")[0] == 0
    assert run(tmp_path, "submit", extra=submit_args())[0] == 0
    broker.fail_cancel = True
    extra = ("--cancel-owned", "--execute-simulate")
    code, report = run(tmp_path, "stop", extra=extra)
    assert code == 1 and report["evidence"]["stopped"]
    assert report["error_code"] == "QUALIFICATION_CANCEL_NOT_CONFIRMED"
    assert run(tmp_path, "stop", extra=extra, filename="stop2.json")[0] == 1
    assert broker.calls.count("cancel") == 1


def test_cli_refuses_implicit_order_and_same_new_path_before_any_connection(broker, tmp_path):
    with pytest.raises(SystemExit):
        run(tmp_path, "submit")
    target = tmp_path / "new.sqlite"
    assert qualifier.main(["prepare", "--journal", str(target), "--output", str(target)]) == 1
    assert not target.exists() and not broker.contexts


def test_new_runtime_fields_cannot_export_arbitrary_values(tmp_path):
    result = evidence.safe_runtime({"sdk_module": "private-module", "sdk_version": "private-token",
                                    "python_version": "3.14.4", "source_sha256_lf": {
                                        "secret-file": "a" * 64, "moomoo_simulation.py": "a" * 64}})
    assert result == {"python_version": "3.14.4", "source_sha256_lf": {"moomoo_simulation.py": "a" * 64}}
