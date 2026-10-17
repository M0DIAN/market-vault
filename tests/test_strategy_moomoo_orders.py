from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pandas as pd
import pytest

from market_vault import moomoo_sdk
from market_vault.moomoo_simulation import SimulationAccountSession, SimulationError
from market_vault import moomoo_simulation_orders as orders

NOW = datetime(2026, 10, 16, 15, 0, tzinfo=timezone.utc)
IDENTIFIER = "0123456789abcdef0123456789abcdef"
OTHER_ID = "1123456789abcdef0123456789abcdef"


@pytest.fixture
def broker(monkeypatch):
    state = SimpleNamespace(calls=[], contexts=[], env="SIMULATE", cash_qty=10,
                            buy_back=0, rows=[], fail_place=None, fail_cancel=False,
                            fail_query=False, before_place=None)

    class Context:
        def __init__(self, **kwargs):
            assert kwargs == dict(filter_trdmarket="US", host="127.0.0.1", port=11111,
                                  security_firm="NONE")
            self.closed = False
            state.contexts.append(self)

        def close(self):
            self.closed = True

        def get_acc_list(self):
            return 0, pd.DataFrame([dict(acc_id=200, trd_env=state.env, sim_acc_type="STOCK",
                                        trdmarket_auth=["US"], acc_status="ACTIVE")])

        def _record(self, method, kwargs):
            assert kwargs["trd_env"] == "SIMULATE" and kwargs["acc_id"] == 200
            assert "acc_index" not in kwargs
            state.calls.append((method, kwargs))

        def acctradinginfo_query(self, **kwargs):
            self._record("cash", kwargs)
            assert kwargs["session"] == "RTH" and kwargs["order_type"] == "NORMAL"
            return 0, pd.DataFrame([dict(max_cash_buy=state.cash_qty,
                                        max_cash_and_margin_buy=10000, max_buy_back=state.buy_back)])

        def place_order(self, **kwargs):
            self._record("place", kwargs)
            if state.before_place:
                state.before_place()
            row = dict(order_id="paper-001", code=kwargs["code"], trd_side=kwargs["trd_side"],
                       qty=kwargs["qty"], price=kwargs["price"], order_type=kwargs["order_type"],
                       remark=kwargs["remark"], order_status="SUBMITTED", dealt_qty=0,
                       dealt_avg_price=0, create_time="2026-10-16 11:00:00",
                       updated_time="2026-10-16 11:00:00", last_err_msg="private-error-text")
            state.rows = [row]
            if state.fail_place:
                raise state.fail_place
            return 0, pd.DataFrame(state.rows)

        def order_list_query(self, **kwargs):
            self._record("query", kwargs)
            assert kwargs["refresh_cache"] is True
            if state.fail_query:
                raise RuntimeError("private-session-details")
            return 0, pd.DataFrame(state.rows)

        def modify_order(self, **kwargs):
            self._record("cancel", kwargs)
            assert kwargs["modify_order_op"] == "CANCEL" and kwargs["order_id"] == "paper-001"
            if state.fail_cancel:
                raise TimeoutError("private-token")
            return 0, pd.DataFrame([dict(order_id="paper-001", trd_env="SIMULATE")])

    module = SimpleNamespace(
        OpenSecTradeContext=Context, OpenQuoteContext=object, RET_OK=0,
        TrdEnv=SimpleNamespace(SIMULATE="SIMULATE", REAL="REAL"),
        TrdMarket=SimpleNamespace(US="US"), SecurityFirm=SimpleNamespace(NONE="NONE"),
        OrderType=SimpleNamespace(NORMAL="NORMAL"), Session=SimpleNamespace(RTH="RTH"),
        TrdSide=SimpleNamespace(BUY="BUY"), TimeInForce=SimpleNamespace(DAY="DAY"),
        ModifyOrderOp=SimpleNamespace(CANCEL="CANCEL"), __version__="offline-fixture",
    )
    monkeypatch.setattr(moomoo_sdk, "_import_sdk_module", lambda: (module, "moomoo"))
    return state


def intent(**kwargs):
    return orders.BuyIntent(**{**dict(intent_id=IDENTIFIER, symbol="US.SPY", price="500.00"), **kwargs})


def test_actual_cli_persists_before_submit_and_ack_is_not_a_fill(broker, monkeypatch, tmp_path):
    path = tmp_path / "paper.sqlite"
    assert orders.main(["init", "--journal", str(path)]) == 0
    original = orders.PaperExecution
    monkeypatch.setattr(orders, "PaperExecution", lambda s, j: original(s, j, clock=lambda: NOW))

    def durable_before_call():
        with orders.PaperJournal(path) as reopened:
            assert reopened.intent(IDENTIFIER) == intent()
            assert reopened.events(IDENTIFIER)[0]["kind"] == "SUBMISSION_INTENT"

    broker.before_place = durable_before_call
    argv = ["submit", "--journal", str(path), "--intent-id", IDENTIFIER,
            "--symbol", "US.SPY", "--price", "500.00", "--execute-simulate"]
    assert orders.main(argv) == 0
    assert orders.main(argv) == 1
    assert [name for name, _ in broker.calls].count("place") == 1
    call = [data for name, data in broker.calls if name == "place"][0]
    assert call["time_in_force"] == "DAY" and call["session"] == "RTH"
    assert not call["fill_outside_rth"] and call["adjust_limit"] == 0
    assert call["remark"] == "mv-" + IDENTIFIER
    assert all(ctx.closed for ctx in broker.contexts)
    with orders.PaperJournal(path) as journal:
        assert journal.bound_order_id(IDENTIFIER) == "paper-001"
        assert journal.events(IDENTIFIER)[-1]["kind"] == "SUBMISSION_ACK"
        assert "private-error-text" not in json.dumps(journal.events())


@pytest.mark.parametrize("failure", [TimeoutError("private-token"), SystemExit("crash")])
def test_ambiguous_or_crashed_submit_never_resends_after_reopening(broker, tmp_path, failure):
    path = tmp_path / "paper.sqlite"
    broker.fail_place = failure
    with orders.PaperJournal.create(path, 200) as journal, SimulationAccountSession() as session:
        engine = orders.PaperExecution(session, journal, clock=lambda: NOW)
        with pytest.raises((SimulationError, SystemExit)):
            engine.submit(intent(), execute_simulate=True)
        assert len(broker.rows) == 1  # Simulated broker accepted before the response was lost.
    with orders.PaperJournal(path) as journal, SimulationAccountSession() as session:
        engine = orders.PaperExecution(session, journal, clock=lambda: NOW)
        with pytest.raises(SimulationError, match="NO_RESUBMIT"):
            engine.submit(intent(), execute_simulate=True)
        with pytest.raises(SimulationError, match="INTENTION_LIMIT"):
            engine.submit(intent(intent_id=OTHER_ID), execute_simulate=True)
        with pytest.raises(SimulationError, match="OUTCOME_UNKNOWN"):
            journal.bound_order_id(IDENTIFIER)
        assert "private-token" not in json.dumps(journal.events())
    assert [name for name, _ in broker.calls].count("place") == 1


@pytest.mark.parametrize("changes", [dict(qty=True), dict(qty=2), dict(price="NaN"),
                                      dict(price="1000.01"), dict(price="0.90"),
                                      dict(price="500.001"), dict(symbol="US.AAPL"),
                                      dict(intent_id="not-a-uuid")])
def test_invalid_intent_has_no_broker_call_or_durable_reservation(broker, tmp_path, changes):
    with orders.PaperJournal.create(tmp_path / "p.sqlite", 200) as journal, SimulationAccountSession() as session:
        with pytest.raises(SimulationError):
            orders.PaperExecution(session, journal, clock=lambda: NOW).submit(intent(**changes), execute_simulate=True)
        assert not broker.calls and not journal.intentions()


@pytest.mark.parametrize("now", [datetime(2026, 10, 17, 15, tzinfo=timezone.utc),
                                  datetime(2026, 11, 27, 18, tzinfo=timezone.utc),
                                  datetime(2028, 1, 3, 15, tzinfo=timezone.utc)])
def test_weekend_early_close_and_unknown_calendar_do_not_send(broker, tmp_path, now):
    with orders.PaperJournal.create(tmp_path / "p.sqlite", 200) as journal, SimulationAccountSession() as session:
        with pytest.raises(SimulationError, match="OUTSIDE_SUPPORTED_RTH"):
            orders.PaperExecution(session, journal, clock=lambda: now).submit(intent(), execute_simulate=True)
        assert not broker.calls and not journal.intentions()


def test_uses_cash_not_margin_and_rejects_covering_existing_short(broker, tmp_path):
    with orders.PaperJournal.create(tmp_path / "p.sqlite", 200) as journal, SimulationAccountSession() as session:
        engine = orders.PaperExecution(session, journal, clock=lambda: NOW)
        broker.cash_qty = 0
        with pytest.raises(SimulationError, match="CASH_ONLY"):
            engine.submit(intent(), execute_simulate=True)
        broker.cash_qty, broker.buy_back = 10, 1
        with pytest.raises(SimulationError, match="CASH_ONLY"):
            engine.submit(intent(), execute_simulate=True)
        assert not journal.intentions() and all(name == "cash" for name, _ in broker.calls)


def test_account_drift_and_journal_mismatch_never_send(broker, tmp_path):
    with orders.PaperJournal.create(tmp_path / "p.sqlite", 201) as journal, SimulationAccountSession() as session:
        engine = orders.PaperExecution(session, journal, clock=lambda: NOW)
        with pytest.raises(SimulationError, match="JOURNAL_ACCOUNT_MISMATCH"):
            engine.submit(intent(), execute_simulate=True)
        assert not broker.calls
    with orders.PaperJournal.create(tmp_path / "q.sqlite", 200) as journal, SimulationAccountSession() as session:
        broker.env = "REAL"
        with pytest.raises(SimulationError):
            orders.PaperExecution(session, journal, clock=lambda: NOW).submit(intent(), execute_simulate=True)
        assert not broker.calls


def test_journal_commit_failure_stops_before_mutating_sdk(broker, monkeypatch, tmp_path):
    with orders.PaperJournal.create(tmp_path / "p.sqlite", 200) as journal, SimulationAccountSession() as session:
        def fail(_):
            raise sqlite3.OperationalError("disk full")
        monkeypatch.setattr(journal, "reserve", fail)
        with pytest.raises(sqlite3.OperationalError):
            orders.PaperExecution(session, journal, clock=lambda: NOW).submit(intent(), execute_simulate=True)
        assert all(name == "cash" for name, _ in broker.calls)


def test_cancel_is_owned_fresh_queried_and_ack_is_not_final(broker, tmp_path):
    with orders.PaperJournal.create(tmp_path / "p.sqlite", 200) as journal, SimulationAccountSession() as session:
        engine = orders.PaperExecution(session, journal, clock=lambda: NOW)
        engine.submit(intent(), execute_simulate=True)
        with pytest.raises(SimulationError, match="NOT_OWNED"):
            engine.cancel(OTHER_ID, execute_simulate=True)
        result = engine.cancel(IDENTIFIER, execute_simulate=True)
        assert result == {"result": "CANCEL_ACKNOWLEDGED", "final_outcome": "NOT_VERIFIED"}
        assert broker.rows[0]["order_status"] == "SUBMITTED"
        with pytest.raises(SimulationError, match="CANCEL_ALREADY_ATTEMPTED"):
            engine.cancel(IDENTIFIER, execute_simulate=True)
        broker.rows[0]["order_status"] = "CANCELLED_ALL"
        assert engine.observe(IDENTIFIER)["order_status"] == "CANCELLED_ALL"
    assert [name for name, _ in broker.calls].count("cancel") == 1


def test_cancel_query_failure_or_mismatched_identity_does_not_cancel(broker, tmp_path):
    with orders.PaperJournal.create(tmp_path / "p.sqlite", 200) as journal, SimulationAccountSession() as session:
        engine = orders.PaperExecution(session, journal, clock=lambda: NOW)
        engine.submit(intent(), execute_simulate=True)
        broker.fail_query = True
        with pytest.raises(SimulationError, match="OBSERVATION_UNAVAILABLE"):
            engine.cancel(IDENTIFIER, execute_simulate=True)
        broker.fail_query = False
        broker.rows[0]["remark"] = "other-owner"
        with pytest.raises(SimulationError, match="OBSERVATION_UNAVAILABLE"):
            engine.cancel(IDENTIFIER, execute_simulate=True)
        assert "private-session-details" not in json.dumps(journal.events())
    assert all(name != "cancel" for name, _ in broker.calls)


def test_cancel_timeout_is_retained_not_reported_cancelled(broker, tmp_path):
    with orders.PaperJournal.create(tmp_path / "p.sqlite", 200) as journal, SimulationAccountSession() as session:
        engine = orders.PaperExecution(session, journal, clock=lambda: NOW)
        engine.submit(intent(), execute_simulate=True)
        broker.fail_cancel = True
        with pytest.raises(SimulationError, match="CANCEL_OUTCOME_UNKNOWN"):
            engine.cancel(IDENTIFIER, execute_simulate=True)
        assert journal.events(IDENTIFIER)[-1]["kind"] == "CANCEL_UNKNOWN"
        assert "private-token" not in json.dumps(journal.events())


def test_existing_or_missing_journal_is_never_reinitialized(tmp_path):
    path = tmp_path / "p.sqlite"
    with orders.PaperJournal.create(path, 200):
        pass
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        orders.PaperJournal.create(path, 201)
    assert path.read_bytes() == before
    missing = tmp_path / "missing.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        orders.PaperJournal(missing)
    assert not missing.exists()


def test_cli_requires_explicit_opt_in_before_connection(broker, tmp_path):
    with pytest.raises(SystemExit) as error:
        orders.main(["submit", "--journal", str(tmp_path / "p.sqlite")])
    assert error.value.code == 2 and not broker.contexts


@pytest.mark.parametrize("change", [{"dealt_qty": 2}, {"dealt_qty": 1, "dealt_avg_price": 0}])
def test_invalid_cumulative_broker_fill_is_not_accepted(broker, tmp_path, change):
    with orders.PaperJournal.create(tmp_path / "p.sqlite", 200) as journal, SimulationAccountSession() as session:
        engine = orders.PaperExecution(session, journal, clock=lambda: NOW)
        engine.submit(intent(), execute_simulate=True)
        broker.rows[0].update(change)
        with pytest.raises(SimulationError, match="ORDER_OBSERVATION_UNAVAILABLE"):
            engine.observe(IDENTIFIER)
        assert journal.events()[-1]["kind"] == "ORDER_QUERY_FAILED"
        assert not any(method == "cancel" for method, _ in broker.calls)


def test_preflight_crossing_close_retains_not_sent_intent(broker, tmp_path):
    times = iter([NOW, datetime(2026, 10, 16, 20, 0, tzinfo=timezone.utc)])
    with orders.PaperJournal.create(tmp_path / "p.sqlite", 200) as journal, SimulationAccountSession() as session:
        engine = orders.PaperExecution(session, journal, clock=lambda: next(times))
        with pytest.raises(SimulationError, match="SUBMISSION_NOT_SENT"):
            engine.submit(intent(), execute_simulate=True)
        assert len(journal.intentions()) == 1
        assert journal.events()[-1]["kind"] == "SUBMISSION_NOT_SENT"
        assert not any(method == "place" for method, _ in broker.calls)
