from __future__ import annotations

from datetime import timedelta
import json
import sqlite3
from types import SimpleNamespace

import pandas as pd
import pytest

from market_vault import moomoo_sdk
from market_vault.moomoo_simulation import SimulationAccountSession, SimulationError
from market_vault import moomoo_simulation_orders as orders
from market_vault import moomoo_simulation_recovery as recovery
from test_strategy_moomoo_orders import broker, intent, IDENTIFIER, OTHER_ID, NOW


@pytest.fixture
def paper(broker, monkeypatch):
    """Only the external SDK is substituted; session, journal and entry points are real."""
    module = moomoo_sdk._import_sdk_module()[0]
    cls = module.OpenSecTradeContext
    module.Currency = SimpleNamespace(USD="USD")
    broker.history = []
    broker.positions = []
    broker.balance = "10000.00"
    broker.currency = "USD"
    broker.funds_hook = None
    broker.fail_history = False
    monkeypatch.setattr(orders, "utc_now", lambda: NOW)

    def query(self, **kwargs):
        self._record("query", kwargs)
        assert kwargs["refresh_cache"] is True
        if broker.fail_query:
            raise TimeoutError("private-token")
        return 0, pd.DataFrame(broker.rows, columns=list(broker.rows[0]) if broker.rows else
                               ["order_id", "order_status", "remark"])

    def history(self, **kwargs):
        self._record("history", kwargs)
        assert kwargs["code"] == "US.SPY" and kwargs["order_market"] == "US"
        assert "refresh_cache" not in kwargs
        assert kwargs["start"] == "2026-10-16 00:00:00"
        if broker.fail_history:
            raise RuntimeError("private-history")
        return 0, pd.DataFrame(broker.history, columns=list(broker.history[0]) if broker.history else
                               ["order_id", "order_status", "remark"])

    def positions(self, **kwargs):
        self._record("positions", kwargs)
        assert kwargs["refresh_cache"] is True
        return 0, pd.DataFrame(broker.positions, columns=["code", "qty", "position_side"])

    def funds(self, **kwargs):
        self._record("funds", kwargs)
        assert kwargs["refresh_cache"] is True and kwargs["currency"] == "USD"
        if broker.funds_hook:
            broker.funds_hook()
        return 0, pd.DataFrame([dict(cash=broker.balance, currency=broker.currency,
                                    private_token="never-export")])

    monkeypatch.setattr(cls, "order_list_query", query)
    monkeypatch.setattr(cls, "history_order_list_query", history, raising=False)
    monkeypatch.setattr(cls, "position_list_query", positions, raising=False)
    monkeypatch.setattr(cls, "accinfo_query", funds, raising=False)
    return broker


def engine(session, journal):
    return recovery.PaperRecovery(session, journal, clock=lambda: NOW + timedelta(hours=1))


def fill(paper, *, qty="1", price="499", status="FILLED_ALL", updated="2026-10-16 11:01:00"):
    paper.rows[0].update(dealt_qty=qty, dealt_avg_price=price, order_status=status, updated_time=updated)
    paper.positions = [dict(code="US.SPY", qty=qty, position_side="LONG")]
    paper.balance = str(orders.number(10000) - orders.number(qty) * orders.number(price))


def test_restart_partial_cancel_and_repeated_reconciliation_do_not_double_count(paper, tmp_path):
    path = tmp_path / "paper.sqlite"
    with orders.PaperJournal.create(path, 200) as journal, SimulationAccountSession() as session:
        work = engine(session, journal)
        assert work.baseline()["result"] == "BASELINE_RECORDED"
        work.submit(intent(), execute_simulate=True)
    with orders.PaperJournal(path) as journal, SimulationAccountSession() as session:
        work = engine(session, journal)
        session.reconnect()
        fill(paper, qty="0.4", price="495", status="FILLED_PART")
        assert work.reconcile()["error_code"] == "OWNED_ORDER_STILL_WORKING"
        assert work.stop(cancel_owned=True, execute_simulate=True)["cancel_results"][0]["result"] == "CANCEL_ACKNOWLEDGED"
        fill(paper, qty="0.4", price="495", status="CANCELLED_PART", updated="2026-10-16 11:02:00")
        for _ in range(2):
            result = work.reconcile()
            assert result["result"] == "OBSERVATIONS_MATCH"
            assert orders.number(result["cash_expected_before_unobserved_fees_usd"]) == 9802
            assert result["position_residuals"] == {"US.SPY": "0.0"}
            assert result["stopped"] and not result["new_orders_authorized"]
            assert result["fees"] == result["cash_flows"] == "NOT_OBSERVED"
        assert "never-export" not in json.dumps(journal.events())
    assert [name for name, _ in paper.calls].count("place") == 1
    assert [name for name, _ in paper.calls].count("cancel") == 1
    assert all(c.closed for c in paper.contexts)


@pytest.mark.parametrize("failure", [TimeoutError("private-token"), SystemExit("crash")])
def test_lost_ack_recovers_by_remark_without_resend(paper, tmp_path, failure):
    path = tmp_path / "paper.sqlite"
    paper.fail_place = failure
    with orders.PaperJournal.create(path, 200) as journal, SimulationAccountSession() as session:
        with pytest.raises((SimulationError, SystemExit)):
            engine(session, journal).submit(intent(), execute_simulate=True)
    paper.rows.append(dict(paper.rows[0]))  # Exact duplicate must not create two fills.
    with orders.PaperJournal(path) as journal, SimulationAccountSession() as session:
        work = engine(session, journal)
        assert work.recover(IDENTIFIER)["order_id"] == "paper-001"
        assert journal.bound_order_id(IDENTIFIER) == "paper-001"
        with pytest.raises(SimulationError, match="NO_RESUBMIT"):
            work.submit(intent(), execute_simulate=True)
        with pytest.raises(SimulationError, match="INTENTION_LIMIT"):
            work.submit(intent(intent_id=OTHER_ID), execute_simulate=True)
    assert [name for name, _ in paper.calls].count("place") == 1


def test_fresh_history_recovers_terminal_order_absent_from_current_list(paper, tmp_path):
    with orders.PaperJournal.create(tmp_path / "p.sqlite", 200) as journal, SimulationAccountSession() as session:
        work = engine(session, journal)
        work.baseline()
        work.submit(intent(), execute_simulate=True)
        fill(paper)
        paper.history, paper.rows = paper.rows, []
        assert work.reconcile()["result"] == "OBSERVATIONS_MATCH"
        assert work.stop(cancel_owned=True, execute_simulate=True)["cancel_results"][0]["result"] == "ALREADY_TERMINAL"
        assert any(e.get("source") == "HISTORICAL_ORDER_QUERY" for e in journal.events())
        assert all(name != "cancel" for name, _ in paper.calls)


@pytest.mark.parametrize("mode", ["missing", "history_failure", "two_ids", "wrong_remark", "unknown_status", "missing_time"])
def test_missing_ambiguous_and_incomplete_evidence_never_authorizes_cancel(paper, tmp_path, mode):
    with orders.PaperJournal.create(tmp_path / "p.sqlite", 200) as journal, SimulationAccountSession() as session:
        work = engine(session, journal)
        work.submit(intent(), execute_simulate=True)
        if mode in {"missing", "history_failure"}:
            paper.rows = []
            paper.fail_history = mode == "history_failure"
        elif mode == "two_ids":
            paper.rows.append({**paper.rows[0], "order_id": "paper-002"})
        elif mode == "wrong_remark":
            paper.rows[0]["remark"] = "someone-else"
        elif mode == "unknown_status":
            paper.rows[0]["order_status"] = "MYSTERY"
        else:
            paper.rows[0].pop("updated_time")
        result = work.stop(cancel_owned=True, execute_simulate=True)
        assert journal.stopped and result["cancel_results"][0]["result"] == "CANCEL_NOT_CONFIRMED"
        assert not any(name == "cancel" for name, _ in paper.calls)
        assert "private-history" not in json.dumps(journal.events())


@pytest.mark.parametrize("mode", ["quantity", "time", "terminal", "price_revision"])
def test_recovery_rejects_regression_without_overwriting_last_accepted_snapshot(paper, tmp_path, mode):
    with orders.PaperJournal.create(tmp_path / "p.sqlite", 200) as journal, SimulationAccountSession() as session:
        work = engine(session, journal)
        work.submit(intent(), execute_simulate=True)
        fill(paper, qty="0.5", status="FILLED_PART")
        if mode == "terminal":
            fill(paper)
        accepted = work.recover(IDENTIFIER)
        if mode == "quantity":
            paper.rows[0]["dealt_qty"] = "0.4"
        elif mode == "time":
            paper.rows[0]["updated_time"] = "2026-10-16 11:00:00"
        elif mode == "terminal":
            paper.rows[0]["order_status"] = "SUBMITTED"
        else:
            paper.rows[0]["dealt_avg_price"] = "498"
        with pytest.raises(SimulationError):
            work.recover(IDENTIFIER)
        latest = [e for e in journal.events() if e["kind"] == "ORDER_OBSERVATION"][-1]
        assert latest["dealt_qty"] == accepted["dealt_qty"]
        assert latest["dealt_avg_price"] == accepted["dealt_avg_price"]
        assert journal.events()[-1]["kind"] == "RECOVERY_FAILED"


@pytest.mark.parametrize("mode", ["fee", "unrelated_position", "wrong_currency", "unknown_working"])
def test_account_disagreement_is_reported_not_silently_rebased(paper, tmp_path, mode):
    with orders.PaperJournal.create(tmp_path / "p.sqlite", 200) as journal, SimulationAccountSession() as session:
        work = engine(session, journal)
        work.baseline()
        work.submit(intent(), execute_simulate=True)
        fill(paper)
        if mode == "fee":
            paper.balance = str(orders.number(paper.balance) - orders.number("0.01"))
        elif mode == "unrelated_position":
            paper.positions.append(dict(code="US.QQQ", qty=1, position_side="LONG"))
        elif mode == "wrong_currency":
            paper.currency = "HKD"
        else:
            paper.rows.append({**paper.rows[0], "order_id": "unrelated", "remark": "manual", "order_status": "SUBMITTED"})
        result = work.reconcile()
        assert result["result"] == "BLOCKED" and not result["new_orders_authorized"]
        if mode == "fee":
            assert result["cash_residual_usd"] == "-0.01" and result["fees"] == "NOT_OBSERVED"
        assert len([e for e in journal.events() if e["kind"] == "ACCOUNT_BASELINE"]) == 1
        with pytest.raises(SimulationError, match="BASELINE_MUST_PRECEDE"):
            work.baseline()


def test_missing_baseline_is_explicit_and_observation_race_is_not_a_match(paper, tmp_path):
    with orders.PaperJournal.create(tmp_path / "p.sqlite", 200) as journal, SimulationAccountSession() as session:
        work = engine(session, journal)
        assert work.reconcile()["error_code"] == "BASELINE_MISSING_OR_AMBIGUOUS"
        work.baseline()
        assert work.reconcile()["result"] == "OBSERVATIONS_MATCH"
        work.submit(intent(), execute_simulate=True)
        paper.funds_hook = lambda: fill(paper)
        assert work.reconcile()["error_code"] == "ORDER_CHANGED_DURING_ACCOUNT_SNAPSHOT"
        paper.funds_hook = None
        assert work.reconcile()["result"] == "OBSERVATIONS_MATCH"


def test_durable_stop_blocks_existing_submit_path(paper, tmp_path):
    path = tmp_path / "p.sqlite"
    with orders.PaperJournal.create(path, 200) as journal:
        journal.append("EMERGENCY_STOP", None, automatic_resume=False)
    with orders.PaperJournal(path) as journal, SimulationAccountSession() as session:
        with pytest.raises(SimulationError, match="STOPPED"):
            orders.PaperExecution(session, journal, clock=lambda: NOW).submit(intent(), execute_simulate=True)
        assert not paper.calls and not journal.intentions()


def test_existing_cancel_rejects_regressing_filled_quantity(paper, tmp_path):
    with orders.PaperJournal.create(tmp_path / "p.sqlite", 200) as journal, SimulationAccountSession() as session:
        work = orders.PaperExecution(session, journal, clock=lambda: NOW)
        work.submit(intent(), execute_simulate=True)
        fill(paper, qty="0.5", status="FILLED_PART")
        work.observe(IDENTIFIER)
        fill(paper, qty="0.4", status="FILLED_PART", updated="2026-10-16 11:02:00")
        with pytest.raises(SimulationError, match="ORDER_OBSERVATION_UNAVAILABLE"):
            work.cancel(IDENTIFIER, execute_simulate=True)
        assert not any(name == "cancel" for name, _ in paper.calls)


def test_cli_stop_persists_before_connect_and_works_without_sdk(paper, monkeypatch, tmp_path, capsys):
    path = tmp_path / "p.sqlite"
    with orders.PaperJournal.create(path, 200):
        pass
    def offline():
        raise RuntimeError("private-login-token")
    monkeypatch.setattr(moomoo_sdk, "_import_sdk_module", offline)
    assert recovery.main(["stop", "--journal", str(path)]) == 0
    assert not paper.contexts
    assert recovery.main(["stop", "--journal", str(path), "--cancel-owned", "--execute-simulate"]) == 1
    with orders.PaperJournal(path) as journal:
        assert journal.stopped
        assert len([e for e in journal.events() if e["kind"] == "EMERGENCY_STOP"]) == 1
        with pytest.raises(SimulationError, match="STOPPED"):
            journal.reserve(intent())
    output = capsys.readouterr()
    assert '"stopped": true' in output.err and "private-login-token" not in output.err


def test_failed_cancel_retains_stop_and_never_retries_or_touches_unrelated_orders(paper, tmp_path):
    path = tmp_path / "p.sqlite"
    with orders.PaperJournal.create(path, 200) as journal, SimulationAccountSession() as session:
        work = engine(session, journal)
        work.submit(intent(), execute_simulate=True)
        paper.rows.append({**paper.rows[0], "order_id": "unrelated", "remark": "manual"})
        paper.fail_cancel = True
        assert work.stop(cancel_owned=True, execute_simulate=True)["cancel_results"][0]["error_code"] == "CANCEL_OUTCOME_UNKNOWN"
    with orders.PaperJournal(path) as journal, SimulationAccountSession() as session:
        assert journal.stopped
        result = engine(session, journal).stop(cancel_owned=True, execute_simulate=True)
        assert result["cancel_results"][0]["error_code"] == "CANCEL_ALREADY_ATTEMPTED_QUERY_OUTCOME"
    assert [name for name, _ in paper.calls].count("cancel") == 1


def test_stop_commit_failure_prevents_broker_cancellation(paper, monkeypatch, tmp_path):
    with orders.PaperJournal.create(tmp_path / "p.sqlite", 200) as journal, SimulationAccountSession() as session:
        work = engine(session, journal)
        work.submit(intent(), execute_simulate=True)
        def fail():
            raise sqlite3.OperationalError("disk full")
        monkeypatch.setattr(journal, "stop", fail)
        with pytest.raises(sqlite3.OperationalError):
            work.stop(cancel_owned=True, execute_simulate=True)
        assert not any(name == "cancel" for name, _ in paper.calls)


def test_account_drift_after_connect_blocks_funds_and_positions(paper, tmp_path):
    with orders.PaperJournal.create(tmp_path / "p.sqlite", 200) as journal, SimulationAccountSession() as session:
        paper.env = "REAL"
        with pytest.raises(SimulationError):
            engine(session, journal).account_snapshot()
        assert not paper.calls


def test_recovery_cli_reopens_journal_and_only_prints_summary(paper, monkeypatch, tmp_path, capsys):
    path = tmp_path / "p.sqlite"
    original = recovery.PaperRecovery
    monkeypatch.setattr(recovery, "PaperRecovery", lambda s, j: original(s, j, clock=lambda: NOW + timedelta(hours=1)))
    with orders.PaperJournal.create(path, 200):
        pass
    assert recovery.main(["baseline", "--journal", str(path)]) == 0
    with orders.PaperJournal(path) as journal, SimulationAccountSession() as session:
        original(session, journal, clock=lambda: NOW).submit(intent(), execute_simulate=True)
    fill(paper)
    assert recovery.main(["recover", "--journal", str(path), "--intent-id", IDENTIFIER]) == 0
    assert recovery.main(["reconcile", "--journal", str(path)]) == 0
    text = capsys.readouterr().out
    assert "OBSERVATIONS_MATCH" in text
    assert "paper-001" not in text and "9501" not in text and "account_id" not in text


def test_failed_reconciliation_blocks_unused_budget_until_explicit_fresh_comparison(paper, tmp_path):
    with orders.PaperJournal.create(tmp_path / "p.sqlite", 200) as journal, SimulationAccountSession() as session:
        work = engine(session, journal)
        work.baseline()
        paper.balance = "9999"
        assert work.reconcile()["result"] == "BLOCKED"
        count = len(paper.calls)
        with pytest.raises(SimulationError, match="RECONCILIATION_BLOCKED"):
            work.submit(intent(), execute_simulate=True)
        assert len(paper.calls) == count and not journal.intentions()
        session.reconnect()
        with pytest.raises(SimulationError, match="RECONCILIATION_BLOCKED"):
            journal.reserve(intent())
        paper.balance = "10000"
        assert work.reconcile()["result"] == "OBSERVATIONS_MATCH"
        assert work.submit(intent(), execute_simulate=True)["result"] == "SUBMISSION_ACKNOWLEDGED"


def test_stop_arriving_during_revalidation_is_checked_at_place_boundary(paper, monkeypatch, tmp_path):
    with orders.PaperJournal.create(tmp_path / "p.sqlite", 200) as journal, SimulationAccountSession() as session:
        work = engine(session, journal)
        verify = session.verify
        count = 0
        def late_stop():
            nonlocal count
            count += 1
            if count == 2:  # cash preflight already passed; place-order validation now runs.
                journal.stop()
            return verify()
        monkeypatch.setattr(session, "verify", late_stop)
        with pytest.raises(SimulationError, match="SUBMISSION_OUTCOME_UNKNOWN"):
            work.submit(intent(), execute_simulate=True)
        assert journal.stopped and not any(name == "place" for name, _ in paper.calls)


@pytest.mark.parametrize("entry", ["existing", "recovery"])
def test_partial_to_submitted_regression_cannot_authorize_cancel(paper, tmp_path, entry):
    with orders.PaperJournal.create(tmp_path / "p.sqlite", 200) as journal, SimulationAccountSession() as session:
        work = (orders.PaperExecution(session, journal, clock=lambda: NOW)
                if entry == "existing" else engine(session, journal))
        work.submit(intent(), execute_simulate=True)
        fill(paper, qty="0.5", status="FILLED_PART")
        work.observe(IDENTIFIER)
        paper.rows[0].update(order_status="SUBMITTED", updated_time="2026-10-16 11:02:00")
        with pytest.raises(SimulationError):
            work.cancel(IDENTIFIER, execute_simulate=True)
        assert not any(name == "cancel" for name, _ in paper.calls)
        latest = [e for e in journal.events() if e["kind"] == "ORDER_OBSERVATION"][-1]
        assert latest["order_status"] == "FILLED_PART"


def test_first_recovered_submitted_row_with_nonzero_fill_is_inconsistent(paper, tmp_path):
    paper.fail_place = TimeoutError("lost-ack")
    with orders.PaperJournal.create(tmp_path / "p.sqlite", 200) as journal, SimulationAccountSession() as session:
        work = engine(session, journal)
        with pytest.raises(SimulationError, match="OUTCOME_UNKNOWN"):
            work.submit(intent(), execute_simulate=True)
        fill(paper, qty="0.5", status="SUBMITTED")
        with pytest.raises(SimulationError, match="ORDER_STATUS_FILL_CONFLICT"):
            work.recover(IDENTIFIER)
        assert not any(e["kind"] == "ORDER_OBSERVATION" for e in journal.events())
