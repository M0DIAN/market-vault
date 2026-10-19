"""S14: the saved public file is enough; no private journal or broker re-query."""
import hashlib
import json
import subprocess
import sys

import pytest

from market_vault import moomoo_simulation_report as reader
from market_vault.moomoo_simulation_evidence import build_evidence
from market_vault.moomoo_simulation_observations import summarize
from market_vault.moomoo_simulation_orders import BuyIntent, PaperJournal
from test_strategy_moomoo_qualifier import broker, run, submit_args


@pytest.fixture
def saved(broker, tmp_path):
    assert run(tmp_path, "prepare")[0] == 0
    assert run(tmp_path, "submit", extra=submit_args())[0] == 0
    broker.rows[0].update(order_status="FILLED_ALL", dealt_qty=1, dealt_avg_price=499,
                          updated_time="2026-10-16 11:01:00")
    broker.positions = [dict(code="US.SPY", qty=1, position_side="LONG")]
    broker.cash = "9500.01"  # synthetic unexplained cash difference, not an assigned fee
    assert run(tmp_path, "check")[0] == 1
    assert run(tmp_path, "stop")[0] == 0
    assert run(tmp_path, "check", filename="saved.json")[0] == 1
    return tmp_path / "saved.json"


def test_actual_saved_qualifier_report_recomputed_offline_without_touching_source(saved, monkeypatch, capsys):
    raw = saved.read_bytes()
    old = json.loads(raw)
    journal = saved.parent / "private.sqlite"
    journal_bytes = journal.read_bytes()
    def forbidden(*args, **kw):
        raise AssertionError("No runtime database or broker operation is permitted")
    monkeypatch.setattr(reader.projection, "read_journal", forbidden)
    monkeypatch.setattr(reader.orders.PaperJournal, "__init__", forbidden)
    monkeypatch.setattr(reader.orders.SimulationAccountSession, "connect", forbidden)
    output = saved.parent / "analysis.json"
    assert reader.main(["--input", str(saved), "--output", str(output)]) == 0
    analysis = json.loads(output.read_text())
    assert analysis["input_sha256"] == hashlib.sha256(raw).hexdigest()
    assert analysis["source_declared"]["result"] == "BLOCKED"
    assert analysis["source_declared"]["runtime"] == old["runtime"]
    assert analysis["source_declared"]["exporter_sha256"] == old["evidence"]["exporter_sha256"]
    assert analysis["observation_summary"] == summarize(old["evidence"])
    diag = analysis["observation_summary"]["reconciliation_diagnosis"]
    assert diag["order_states"] == {"FILLED_ALL": 1}
    assert diag["cash_status"] == "UNATTRIBUTED_DECREASE" and diag["cash_residual_usd"] == "-0.99"
    assert diag["stop_status"] == "STOP_RECORDED" and not analysis["new_orders_authorized"]
    assert saved.read_bytes() == raw and journal.read_bytes() == journal_bytes
    text = output.read_text() + capsys.readouterr().out
    assert all(s not in text for s in ("private-order", "987654321", "private-secret", "9500.01"))


def test_embedded_summary_and_unknown_private_keys_are_ignored(saved):
    original = reader.analyze_report(saved)
    value = json.loads(saved.read_bytes())
    value["evidence"]["observation_summary"] = {"intention_count": 999, "private": "DO_NOT_EXPORT"}
    value["private"] = value["evidence"]["private"] = "DO_NOT_EXPORT"
    value["evidence"]["events"][-2]["private"] = "DO_NOT_EXPORT"
    saved.write_text(json.dumps(value))
    changed = reader.analyze_report(saved)
    assert changed["observation_summary"] == original["observation_summary"]
    assert changed["input_sha256"] != original["input_sha256"]
    assert not changed["embedded_summary_used"] and "DO_NOT_EXPORT" not in json.dumps(changed)


@pytest.mark.parametrize("mutation", ["count", "sequence", "alias", "stopped", "finish", "result", "environment", "nan"])
def test_inconsistent_structure_does_not_create_output(saved, mutation, capsys):
    value = json.loads(saved.read_bytes())
    ev = value["evidence"]
    if mutation == "count": ev["source_event_count"] += 1
    elif mutation == "sequence": ev["events"][1]["seq"] = 1
    elif mutation == "alias": next(e for e in ev["events"] if e["kind"] == "ORDER_OBSERVATION")["intent"] = "intent-2"
    elif mutation == "stopped": ev["stopped"] = False
    elif mutation == "finish": ev["events"][-1]["start_seq"] = 999
    elif mutation == "result": value["result"] = "OBSERVATIONS_MATCH"
    elif mutation == "environment": ev["environment"] = "REAL"
    else: next(e for e in ev["events"] if e["kind"] == "RECONCILIATION")["cash_residual_usd"] = "NaN"
    saved.write_text(json.dumps(value))
    before = saved.read_bytes()
    output = saved.parent / "invalid.json"
    assert reader.main(["--input", str(saved), "--output", str(output)]) == 1
    assert not output.exists() and saved.read_bytes() == before
    assert "Traceback" not in capsys.readouterr().err


def test_missing_residual_or_basis_is_not_imputed_to_zero(saved):
    value = json.loads(saved.read_bytes())
    last = [e for e in value["evidence"]["events"] if e["kind"] == "RECONCILIATION"][-1]
    del last["cash_residual_usd"], last["position_residuals"], last["cash_basis"]
    saved.write_text(json.dumps(value))
    diag = reader.analyze_report(saved)["observation_summary"]["reconciliation_diagnosis"]
    assert diag["cash_status"] == "BASIS_UNVERIFIED" and diag["cash_residual_usd"] is None
    assert diag["owned_position_status"] == "NOT_COMPARED" and diag["reconciliation_result"] == "BLOCKED"


def test_bare_evidence_empty_and_unfinished_query_remain_unobserved(tmp_path):
    path = tmp_path / "private.sqlite"
    with PaperJournal.create(path, 200) as journal:
        bare = build_evidence(path)
        public = tmp_path / "bare.json"
        public.write_text(json.dumps(bare), encoding="utf-8-sig")
        empty = reader.analyze_report(public)
        assert empty["observation_summary"]["observed_outcome_fraction"] is None
        assert empty["source_declared"]["result"] is None
        identity = "0" * 32
        journal.reserve(BuyIntent(identity, "US.SPY", "500.00"))
        journal.append("QUALIFICATION_START", None, action="check", runtime={}, started_at_utc="2026-10-16T15:00:00+00:00")
        journal.append("ORDER_OBSERVATION", identity, order_id="private", order_status="FILLED_ALL", dealt_qty=1,
                       dealt_avg_price=499, updated_time="2026-10-16T11:00:01")
    bare = build_evidence(path)
    public.write_text(json.dumps(bare))
    summary = reader.analyze_report(public)["observation_summary"]
    assert summary["incomplete_action_count"] == 1 and summary["outcome_counts"]["UNRESOLVED"] == 1


def test_duplicate_json_keys_and_existing_destinations_are_not_accepted(saved):
    before = saved.read_bytes()
    assert reader.main(["--input", str(saved), "--output", str(saved)]) == 1
    assert saved.read_bytes() == before
    output = saved.parent / "output.json"
    output.write_bytes(b"keep me")
    assert reader.main(["--input", str(saved), "--output", str(output)]) == 1
    assert output.read_bytes() == b"keep me"
    duplicate = saved.parent / "duplicate.json"
    duplicate.write_text('{"schema": "wrong", "schema": "market_vault_paper_evidence_v1"}')
    with pytest.raises(ValueError): reader.analyze_report(duplicate)


def test_cli_runs_in_fresh_process_without_site_packages(saved):
    output = saved.parent / "subprocess.json"
    result = subprocess.run([sys.executable, "-S", "-m", "market_vault.moomoo_simulation_report",
                             "--input", str(saved), "--output", str(output)],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text())["source_declared"]["result"] == "BLOCKED"


@pytest.mark.parametrize("mutation", ["check_result", "check_missing_record", "stop_missing_record",
                                     "prepare_missing_baseline", "submit_missing_ack"])
def test_finish_declarations_require_supporting_operation_events(saved, mutation):
    value = json.loads(saved.read_bytes())
    evidence = value["evidence"]
    events = evidence["events"]
    if mutation == "check_result":
        value["result"] = events[-1]["result"] = "OBSERVATIONS_MATCH"
        value.pop("error_code", None)
        events[-1].pop("error_code", None)
    else:
        removed = {"check_missing_record": "RECONCILIATION", "stop_missing_record": "EMERGENCY_STOP",
                   "prepare_missing_baseline": "ACCOUNT_BASELINE", "submit_missing_ack": "SUBMISSION_ACK"}[mutation]
        target = next(e["seq"] for e in reversed(events) if e["kind"] == removed)
        events[:] = [e for e in events if e["seq"] != target]
        remap = {e["seq"]: index for index, e in enumerate(events, 1)}
        for event in events:
            event["seq"] = remap[event["seq"]]
            if "start_seq" in event:
                event["start_seq"] = remap[event["start_seq"]]
        evidence["source_event_count"] = len(events)
        if mutation == "stop_missing_record":
            evidence["stopped"] = False
    saved.write_text(json.dumps(value))
    before = saved.read_bytes()
    with pytest.raises(ValueError, match="INCONSISTENT"):
        reader.analyze_report(saved)
    assert saved.read_bytes() == before


@pytest.mark.parametrize("mode", ["blocked", "missing", "late"])
def test_submit_success_requires_earlier_operation_local_preflight(saved, mode):
    value = json.loads(saved.read_bytes())
    evidence = value["evidence"]
    events = evidence["events"]
    start = next(e for e in events if e["kind"] == "QUALIFICATION_START" and e["action"] == "submit")
    end = next(e for e in events if e["kind"] == "QUALIFICATION_FINISH" and e["action"] == "submit")
    preflight = next(e for e in events if e["kind"] == "RECONCILIATION" and start["seq"] < e["seq"] < end["seq"])
    if mode == "blocked":
        preflight["result"] = "BLOCKED"
        preflight["error_code"] = "ACCOUNT_RESIDUAL_UNEXPLAINED"
    else:
        events.remove(preflight)
        if mode == "late":
            events.insert(events.index(end), preflight)
        remap = {e["seq"]: index for index, e in enumerate(events, 1)}
        for event in events:
            event["seq"] = remap[event["seq"]]
            if "start_seq" in event:
                event["start_seq"] = remap[event["start_seq"]]
        evidence["source_event_count"] = len(events)
    saved.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="INCONSISTENT"):
        reader.analyze_report(saved)
