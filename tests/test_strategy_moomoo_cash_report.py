"""Existing exporter and saved-report entry points, not another broker exercise."""
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from market_vault import moomoo_simulation_cash as cash
from market_vault import moomoo_simulation_report as reader
from test_strategy_moomoo_report import saved
from test_strategy_moomoo_qualifier import broker


def last_comparison(document):
    return [e for e in document["evidence"]["events"] if e["kind"] == "RECONCILIATION"][-1]


def test_existing_export_and_analysis_clis_replay_stopped_journal_without_sdk(saved):
    journal = saved.parent / "private.sqlite"
    originals = {path: path.read_bytes() for path in (saved, journal)}
    exported, analyzed = saved.parent / "cash-export.json", saved.parent / "cash-analysis.json"
    env = {**os.environ, "PYTHONPATH": str(Path(reader.__file__).resolve().parents[1])}
    for module, args in (
        ("moomoo_simulation_evidence", ["--journal", str(journal), "--output", str(exported)]),
        ("moomoo_simulation_report", ["--input", str(exported), "--output", str(analyzed)]),
    ):
        result = subprocess.run([sys.executable, "-S", "-m", "market_vault." + module, *args],
                                env=env, cwd=saved.parent, capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
    evidence = json.loads(exported.read_bytes())
    terms = [e["cash_arithmetic"] for e in evidence["events"] if e["kind"] == "RECONCILIATION"]
    assert all(t["status"] == "RECOMPUTED_MATCH" for t in terms)
    assert Decimal(terms[0]["gross_buy_notional_usd"]) == 0
    assert Decimal(terms[-1]["gross_buy_notional_usd"]) == 499
    assert Decimal(terms[-1]["observed_cash_change_usd"]) == Decimal("-499.99")
    analysis = json.loads(analyzed.read_bytes())
    checked = analysis["cash_arithmetic"][-1]
    assert checked["status"] == "PUBLIC_EQUATION_VERIFIED"
    assert checked["exporter_replay_status"] == "RECOMPUTED_MATCH"
    assert Decimal(checked["gross_buy_notional_usd"]) == 499  # Repeated queries are not debits.
    assert Decimal(checked["recomputed_cash_residual_usd"]) == Decimal("-0.99")
    assert checked["private_cash_change"] == "EXPORTER_DECLARATION_NOT_INDEPENDENTLY_VERIFIED"
    assert checked["fees"] == checked["cash_flows"] == "NOT_OBSERVED"
    diag = analysis["observation_summary"]["reconciliation_diagnosis"]
    assert diag["reconciliation_result"] == "BLOCKED" and diag["stop_status"] == "STOP_RECORDED"
    assert diag["cash_status"] == "UNATTRIBUTED_DECREASE" and not analysis["new_orders_authorized"]
    assert analysis["input_sha256"] == hashlib.sha256(exported.read_bytes()).hexdigest()
    digest = hashlib.sha256(Path(cash.__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    assert evidence["cash_arithmetic_source_sha256_lf"] == digest
    assert analysis["source_declared"]["cash_arithmetic_source_sha256_lf"] == digest
    assert analysis["analyzer_runtime"]["source_sha256_lf"]["moomoo_simulation_cash.py"] == digest
    assert all(path.read_bytes() == content for path, content in originals.items())
    text = exported.read_text() + analyzed.read_text()
    assert all(private not in text for private in ("9500.01", "10000", "987654321", "private-order", "private-secret"))


def test_old_reports_keep_missing_terms_without_backsolving_and_original_runtime(saved):
    document = json.loads(saved.read_bytes())
    original_runtime = document["runtime"]
    document["evidence"].pop("cash_arithmetic_source_sha256_lf", None)
    for event in document["evidence"]["events"]:
        event.pop("cash_arithmetic", None)
    saved.write_text(json.dumps(document))
    result = reader.analyze_report(saved)
    assert result["source_declared"]["runtime"] == original_runtime
    assert result["source_declared"]["result"] == "BLOCKED"
    assert result["cash_arithmetic"] and all(r["status"] == "NOT_RECORDED" for r in result["cash_arithmetic"])
    assert all("gross_buy_notional_usd" not in r for r in result["cash_arithmetic"])
    assert result["observation_summary"]["reconciliation_diagnosis"]["cash_residual_usd"] == "-0.99"


@pytest.mark.parametrize("field,wrong", [
    ("gross_buy_notional_usd", "998"), ("observed_cash_change_usd", "-499.00"),
    ("recomputed_cash_residual_usd", "0"), ("recorded_cash_residual_usd", "0"),
    ("order_observation_seqs", []), ("account_observation_seq", 1),
    ("cash_basis", "USD_UNKNOWN"), ("recorded_expected_cash_matches", "true"),
    ("new_orders_authorized", True), ("status", ["RECOMPUTED_MATCH"]),
])
def test_altered_public_terms_are_rejected_before_output_creation(saved, field, wrong):
    document = json.loads(saved.read_bytes())
    last_comparison(document)["cash_arithmetic"][field] = wrong
    saved.write_text(json.dumps(document))
    before = saved.read_bytes()
    output = saved.parent / "invalid-cash.json"
    assert reader.main(["--input", str(saved), "--output", str(output)]) == 1
    assert not output.exists() and saved.read_bytes() == before


def test_consistent_public_equation_does_not_authenticate_private_expected_cash(saved):
    document = json.loads(saved.read_bytes())
    comparison = last_comparison(document)
    comparison["cash_arithmetic"].update(status="RECOMPUTED_MISMATCH", recorded_expected_cash_matches=False)
    saved.write_text(json.dumps(document))
    result = reader.analyze_report(saved)
    last = result["cash_arithmetic"][-1]
    assert last["status"] == "PUBLIC_EQUATION_VERIFIED"
    assert last["exporter_replay_status"] == "RECOMPUTED_MISMATCH"
    assert last["expected_cash_match_declared"] is False and last["recorded_residual_matches"]
    assert last["private_cash_change"] == "EXPORTER_DECLARATION_NOT_INDEPENDENTLY_VERIFIED"
    assert result["source_declared"]["result"] == "BLOCKED" and not result["new_orders_authorized"]


def test_unavailable_projection_does_not_forward_arbitrary_private_fields(saved):
    document = json.loads(saved.read_bytes())
    terms = last_comparison(document)["cash_arithmetic"]
    terms.update(status="UNAVAILABLE", reason="private-secret", observed_cash_change_usd="private-secret",
                 arbitrary={"account": "private-secret"})
    saved.write_text(json.dumps(document))
    result = reader.analyze_report(saved)
    assert result["cash_arithmetic"][-1]["status"] == "UNAVAILABLE"
    assert "private-secret" not in json.dumps(result)


def test_public_order_reference_must_match_bracketing_observation(saved):
    document = json.loads(saved.read_bytes())
    events = document["evidence"]["events"]
    comparison = last_comparison(document)
    seq = comparison["cash_arithmetic"]["order_observation_seqs"][0]
    # Preserve all arithmetic fields, but change the actual referenced observation.
    events[seq - 1]["dealt_avg_price"] = "498"
    saved.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        reader.analyze_report(saved)


def test_cash_verification_rejects_observations_for_a_different_receipted_order(saved):
    document = json.loads(saved.read_bytes())
    for event in document["evidence"]["events"]:
        if event["kind"] == "ORDER_OBSERVATION":
            event["order"] = "order-2"
    # Receipt/ACK still identify order-1; unchanged arithmetic must not hide this.
    saved.write_text(json.dumps(document))
    before = saved.read_bytes()
    with pytest.raises(ValueError):
        reader.analyze_report(saved)
    assert saved.read_bytes() == before
