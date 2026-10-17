from __future__ import annotations

from contextlib import closing
import hashlib
import json
import sqlite3

import pytest

from market_vault import moomoo_simulation_qualifier as qualifier
from market_vault.moomoo_simulation import SimulationError
from market_vault.moomoo_simulation_evidence import build_evidence
from market_vault.moomoo_simulation_orders import BuyIntent, PaperJournal
from test_strategy_moomoo_funds_diagnostics import funds_broker, prepare


STAMP = "2026-10-17T13:34:56+00:00"
ID = "0123456789abcdef0123456789abcdef"


def old_failure(path, *, intention=False):
    """Original S5/S6 completed failure shape, before S7 added diagnostics."""
    with PaperJournal.create(path, 200) as journal:
        journal.append("QUALIFICATION_START", None, action="prepare", started_at_utc=STAMP,
                       recorded_at_utc=STAMP, runtime={})
        if intention:
            journal.reserve(BuyIntent(ID, "US.SPY", "500.00"))
        journal.stop()
        journal.append("QUALIFICATION_FINISH", None, action="prepare", started_at_utc=STAMP,
                       finished_at_utc=STAMP, elapsed_ms="1", start_seq=1, result="FAILED",
                       error_code="CASH_CURRENCY_NOT_USD", runtime={})
    return path


def successor(path):
    path = path.resolve()
    return path.with_name(path.name + ".funds-repair.sqlite")


def run_linked(path, output, *, destination=None):
    code = qualifier.main(["prepare", "--previous-journal", str(path),
                           "--journal", str(destination or successor(path)), "--output", str(output)])
    return code, json.loads(output.read_text())


@pytest.mark.parametrize("original", [True, False])
def test_linked_prepare_preserves_failed_predecessor_and_creates_same_account_baseline(
    funds_broker, tmp_path, original,
):
    if original:
        previous = old_failure(tmp_path / "old.sqlite")
    else:
        funds_broker.funds.update(currency="NONE", us_cash="N/A")
        code, previous, failed = prepare(tmp_path, name="old")
        assert code == 1 and failed["error_code"] == "CASH_CURRENCY_NOT_USD"
    before = previous.read_bytes()
    funds_broker.funds = {"us_cash": "4321.12", "currency": "NONE", "cash": "N/A"}
    code, report = run_linked(previous, tmp_path / "linked.json")
    assert code == 0 and report["result"] == "PREPARED"
    assert previous.read_bytes() == before
    with PaperJournal(previous) as old:
        assert old.stopped and not old.intentions()
    with PaperJournal(successor(previous)) as new:
        assert new.account_id == 200 and not new.stopped and not new.intentions()
        baseline = next(e for e in new.events() if e["kind"] == "ACCOUNT_BASELINE")
        assert baseline["cash_basis"] == "USD_CURRENCY_BALANCE"
        assert baseline["cash"] == "4321.12"
    evidence = report["evidence"]
    origin = evidence["events"][0]
    assert origin["kind"] == "PREPARATION_ORIGIN"
    assert origin["previous_journal_sha256"] == hashlib.sha256(before).hexdigest()
    assert origin["previous_event_count"] == (3 if original else 4)
    assert origin["previous_failure_code"] == "CASH_CURRENCY_NOT_USD"
    assert evidence["unrecognized_event_count"] == 0
    assert evidence["observation_summary"]["intention_count"] == 0
    assert not report["new_orders_authorized"] and report["broker_qualification"] == "NOT_ASSESSED"
    assert all(c.closed for c in funds_broker.contexts)
    text = json.dumps(report)
    assert not any(secret in text for secret in (str(previous), "4321.12", "DO_NOT_EXPORT", '"account_id"'))
    assert set(funds_broker.calls) == {"orders", "positions", "funds"}


@pytest.mark.parametrize("mode", ["intention", "baseline", "unknown_event", "incomplete", "wrong_start", "other_failure"])
def test_unsafe_predecessor_is_rejected_before_any_connection(funds_broker, tmp_path, mode):
    previous = old_failure(tmp_path / "old.sqlite", intention=mode == "intention")
    with PaperJournal(previous) as journal:
        if mode in {"baseline", "unknown_event"}:
            journal.append("ACCOUNT_BASELINE" if mode == "baseline" else "UNKNOWN_OPERATION", None)
    if mode in {"incomplete", "wrong_start", "other_failure"}:
        with closing(sqlite3.connect(previous)) as db, db:
            if mode == "incomplete":
                db.execute("DELETE FROM events WHERE kind='QUALIFICATION_FINISH'")
            else:
                payload = json.loads(db.execute("SELECT payload FROM events WHERE kind='QUALIFICATION_FINISH'").fetchone()[0])
                payload["start_seq" if mode == "wrong_start" else "error_code"] = 99 if mode == "wrong_start" else "BROKER_OPERATION_FAILED"
                db.execute("UPDATE events SET payload=? WHERE kind='QUALIFICATION_FINISH'", (json.dumps(payload),))
    before = previous.read_bytes()
    code, report = run_linked(previous, tmp_path / "failure.json")
    assert code == 1 and report["error_code"] == "PREVIOUS_PREPARE_UNSAFE"
    assert not funds_broker.contexts and not successor(previous).exists()
    assert previous.read_bytes() == before


@pytest.mark.parametrize("drift", ["account", "environment"])
def test_pinned_account_is_not_replaced_on_linked_prepare(funds_broker, tmp_path, drift):
    previous = old_failure(tmp_path / "old.sqlite")
    before = previous.read_bytes()
    if drift == "account":
        funds_broker.account_id = 201
    else:
        funds_broker.environment = "REAL"
    code, report = run_linked(previous, tmp_path / "failure.json")
    assert code == 1 and report["error_code"] == "PINNED_SIMULATION_ACCOUNT_UNAVAILABLE"
    assert not funds_broker.calls and not successor(previous).exists()
    assert previous.read_bytes() == before and all(c.closed for c in funds_broker.contexts)


def test_successor_is_unique_even_after_restart_or_consumed_intention(funds_broker, tmp_path):
    previous = old_failure(tmp_path / "old.sqlite")
    assert run_linked(previous, tmp_path / "first.json")[0] == 0
    with PaperJournal(successor(previous)) as new:
        new.reserve(BuyIntent(ID, "US.SPY", "500.00"))
        new.stop()  # An unknown/consumed intention cannot regain a budget through this path.
    before, child = previous.read_bytes(), successor(previous).read_bytes()
    count = len(funds_broker.contexts)
    assert run_linked(previous, tmp_path / "repeat.json")[1]["error_code"] == "JOURNAL_ALREADY_EXISTS"
    assert run_linked(previous, tmp_path / "sibling.json", destination=tmp_path / "other.sqlite")[1]["error_code"] == "PREPARATION_SUCCESSOR_PATH_REQUIRED"
    assert len(funds_broker.contexts) == count
    assert previous.read_bytes() == before and successor(previous).read_bytes() == child
    assert not (tmp_path / "other.sqlite").exists()


def test_failed_successor_is_retained_stopped_without_recursive_continuation(funds_broker, tmp_path):
    previous = old_failure(tmp_path / "old.sqlite")
    before = previous.read_bytes()
    funds_broker.funds.update(currency="NONE", us_cash="N/A")
    code, report = run_linked(previous, tmp_path / "failed.json")
    assert code == 1 and report["error_code"] == "CASH_CURRENCY_NOT_USD"
    assert report["evidence"]["stopped"] and not report["evidence"]["intentions"]
    count = len(funds_broker.contexts)
    child = successor(previous)
    assert run_linked(child, tmp_path / "recursive.json")[1]["error_code"] == "PREVIOUS_PREPARE_UNSAFE"
    assert len(funds_broker.contexts) == count and not successor(child).exists()
    assert previous.read_bytes() == before


@pytest.mark.parametrize("mode", ["missing", "locked", "wal"])
def test_missing_or_active_source_is_not_recovered_or_modified(funds_broker, tmp_path, mode):
    previous = tmp_path / "old.sqlite"
    lock = None
    try:
        if mode != "missing":
            old_failure(previous)
            lock = sqlite3.connect(previous)
            if mode == "locked":
                lock.execute("BEGIN EXCLUSIVE")
            else:
                lock.execute("PRAGMA journal_mode=WAL")
        before = previous.read_bytes() if previous.exists() else None
        code, _ = run_linked(previous, tmp_path / "failed.json")
        assert code == 1 and not funds_broker.contexts and not successor(previous).exists()
        assert (previous.read_bytes() if previous.exists() else None) == before
    finally:
        if lock is not None:
            lock.close()


def test_read_lock_and_downstream_errors_do_not_modify_or_misdiagnose_source(tmp_path):
    previous = old_failure(tmp_path / "old.sqlite")
    before = previous.read_bytes()
    with pytest.raises(OSError, match="successor-disk-full"):
        with qualifier.preparation_origin(previous, successor(previous)) as origin:
            assert origin["account_id"] == 200
            with closing(sqlite3.connect(previous, timeout=0)) as writer:
                with pytest.raises(sqlite3.OperationalError):
                    writer.execute("BEGIN EXCLUSIVE")
            raise OSError("successor-disk-full")
    assert previous.read_bytes() == before


def test_origin_export_allowlist_and_invalid_lineage(funds_broker, tmp_path):
    previous = old_failure(tmp_path / "old.sqlite")
    assert run_linked(previous, tmp_path / "success.json")[0] == 0
    child = successor(previous)
    with closing(sqlite3.connect(child)) as db, db:
        data = json.loads(db.execute("SELECT payload FROM events WHERE kind='PREPARATION_ORIGIN'").fetchone()[0])
        data.update(previous_path="PRIVATE_PATH", account_id="SECRET_ID", cash="SECRET_BALANCE")
        db.execute("UPDATE events SET payload=? WHERE kind='PREPARATION_ORIGIN'", (json.dumps(data),))
    before = child.read_bytes()
    text = json.dumps(build_evidence(child))
    assert not any(s in text for s in ("PRIVATE_PATH", "SECRET_ID", "SECRET_BALANCE"))
    assert child.read_bytes() == before
    with closing(sqlite3.connect(child)) as db, db:
        data["previous_journal_sha256"] = "PRIVATE_PATH"
        db.execute("UPDATE events SET payload=? WHERE kind='PREPARATION_ORIGIN'", (json.dumps(data),))
    with pytest.raises(ValueError, match="INVALID_PREPARATION_ORIGIN"):
        build_evidence(child)


@pytest.mark.parametrize("extra", [["--account-id", "201"], []])
def test_previous_flag_cannot_select_account_or_be_used_for_check(funds_broker, tmp_path, extra):
    with pytest.raises(SystemExit) as error:
        qualifier.main(["prepare" if extra else "check", "--previous-journal", str(tmp_path / "old.sqlite"),
                        "--journal", str(tmp_path / "new.sqlite"), "--output", str(tmp_path / "x.json"), *extra])
    assert error.value.code == 2 and not funds_broker.contexts
