from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from market_vault.moomoo_simulation_orders import BuyIntent, PaperJournal
from market_vault import moomoo_simulation_evidence as evidence

ID = "0123456789abcdef0123456789abcdef"
STAMP = "2026-10-17T11:00:00+00:00"


def sample(path):
    with PaperJournal.create(path, 98765432123456789) as journal:
        journal.append("ACCOUNT_BASELINE", None, started_at_utc=STAMP, finished_at_utc=STAMP,
                       cash="9876543.21", currency="USD", positions={"US.PRIVATE": "99"})
        journal.reserve(BuyIntent(ID, "US.SPY", "500.00"))
        journal.append("SUBMISSION_CALL", ID)
        journal.append("SUBMISSION_RECEIPT", ID, order_id="sensitive-broker-id", attribution="UNVERIFIED")
        journal.append("SUBMISSION_UNKNOWN", ID, error_type="TimeoutError", password="private-token")
        for _ in range(2):
            journal.append("ORDER_OBSERVATION", ID, order_id="sensitive-broker-id", order_status="FILLED_PART",
                           dealt_qty="0.4", dealt_avg_price="495", updated_time="2026-10-17 09:45:00")
        journal.append("RECONCILIATION", None, result="BLOCKED", cash_residual_usd="-0.01",
                       error_code="ACCOUNT_RESIDUAL_UNEXPLAINED", cash_expected_before_unobserved_fees_usd="9876345.21",
                       position_residuals={"US.SPY": "0", "US.PRIVATE": "1"},
                       account_observation={"cash": "9876543.21"}, orders=[{"order_id": "sensitive-broker-id"}])
        journal.stop()


def test_actual_writer_read_only_export_preserves_unknown_and_duplicate_observations(tmp_path):
    path, output = tmp_path / "journal.sqlite", tmp_path / "upload.json"
    sample(path)
    before = path.read_bytes()
    report = evidence.export_evidence(path, output)
    assert path.read_bytes() == before
    assert json.loads(output.read_text()) == report
    assert report["source_event_count"] == len(report["events"]) == 9
    assert report["stopped"] and not report["new_orders_authorized"]
    assert report["broker_qualification"] == "NOT_ASSESSED"
    assert report["intentions"] == [{"intent": "intent-1", "symbol": "US.SPY", "qty": 1,
                                    "limit_price": "500.00", "side": "BUY"}]
    rows = [e for e in report["events"] if e["kind"] == "ORDER_OBSERVATION"]
    assert len(rows) == 2 and all(e["dealt_qty"] == "0.4" and e["order"] == "order-1" for e in rows)
    assert any(e["kind"] == "SUBMISSION_UNKNOWN" for e in report["events"])
    reconciliation = next(e for e in report["events"] if e["kind"] == "RECONCILIATION")
    assert reconciliation["cash_residual_usd"] == "-0.01"
    assert reconciliation["position_residuals"] == {"US.SPY": "0"}
    assert reconciliation["unrelated_position_residual_count"] == 1
    text = output.read_text()
    for secret in [ID, "sensitive-broker-id", "98765432123456789", "9876543.21", "US.PRIVATE", "private-token"]:
        assert secret not in text


def test_unknown_events_and_errors_are_counted_without_copying_arbitrary_payloads(tmp_path):
    path = tmp_path / "journal.sqlite"
    with PaperJournal.create(path, 200) as journal:
        journal.append("SECRET_CUSTOM_KIND", None, token="private-token", result="PASS")
        journal.append("RECOVERY_FAILED", None, error_type="SecretToken", error_code="SECRET_VALUE")
    report = evidence.build_evidence(path)
    assert report["unrecognized_event_count"] == 1 and len(report["events"]) == 2
    assert report["events"][0]["kind"] == "UNRECOGNIZED_EVENT"
    assert report["events"][1]["error_code"] == "REDACTED_ERROR_CODE"
    assert "SECRET" not in json.dumps(report) and "private-token" not in json.dumps(report)


@pytest.mark.parametrize("change", [{"environment": "REAL"}, {"schema": "future"}, {"limits": {}}])
def test_incompatible_journals_are_not_relabelled_simulate(tmp_path, change):
    path, output = tmp_path / "journal.sqlite", tmp_path / "out.json"
    with PaperJournal.create(path, 200) as journal:
        meta = {**journal.metadata, **change}
    with sqlite3.connect(path) as db:
        db.execute("UPDATE metadata SET payload=?", (json.dumps(meta),))
    before = path.read_bytes()
    assert evidence.main(["--journal", str(path), "--output", str(output)]) == 1
    assert not output.exists() and path.read_bytes() == before


def test_missing_input_and_existing_output_are_not_created_or_overwritten(tmp_path):
    path, output = tmp_path / "missing.sqlite", tmp_path / "out.json"
    assert evidence.main(["--journal", str(path), "--output", str(output)]) == 1
    assert not path.exists() and not output.exists()
    with PaperJournal.create(path, 200):
        pass
    output.write_text("keep-me")
    assert evidence.main(["--journal", str(path), "--output", str(output)]) == 1
    assert output.read_text() == "keep-me"
    original = path.read_bytes()
    assert evidence.main(["--journal", str(path), "--output", str(path)]) == 1
    assert path.read_bytes() == original


def test_row_identity_cannot_be_shadowed_by_payload_and_orphans_refuse(tmp_path):
    path = tmp_path / "journal.sqlite"
    with PaperJournal.create(path, 200) as journal:
        journal._db.execute("INSERT INTO events(kind,intent_id,payload) VALUES (?,?,?)",
                            ("EMERGENCY_STOP", None, json.dumps({"kind": "ALL_CLEAR", "seq": 987,
                                                               "recorded_at_utc": STAMP})))
        journal._db.commit()
    report = evidence.build_evidence(path)
    assert report["stopped"] and report["events"][0]["seq"] == 1
    with sqlite3.connect(path) as db:
        db.execute("UPDATE events SET intent_id='not-owned'")
    with pytest.raises(ValueError, match="EVENT_MISMATCH"):
        evidence.build_evidence(path)


def test_cli_export_and_help_need_no_sdk_and_emit_no_private_details(tmp_path, capsys):
    path, output = tmp_path / "p.sqlite", tmp_path / "out.json"
    sample(path)
    assert evidence.main(["--journal", str(path), "--output", str(output)]) == 0
    assert "EVIDENCE_EXPORTED" in capsys.readouterr().out
    command = [sys.executable, "-m", "market_vault.moomoo_simulation_evidence", "--help"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0 and "--journal" in result.stdout
