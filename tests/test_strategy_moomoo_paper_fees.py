"""The owner may model paper fees without falsifying historical broker facts."""
from decimal import Decimal
import json

import pytest

from market_vault import moomoo_simulation_report as reader
from market_vault.moomoo_paper_fees import assess_cash
from test_strategy_moomoo_report import saved
from test_strategy_moomoo_qualifier import broker


def test_existing_cli_accepts_estimated_fee_and_preserves_original_result_stop(saved):
    original = saved.read_bytes()
    journal = (saved.parent / "private.sqlite").read_bytes()
    strict = reader.analyze_report(saved)
    out = saved.parent / "estimated.json"
    assert reader.main(["--input", str(saved), "--output", str(out), "--paper-fee-usd", "0.99"]) == 0
    estimated = json.loads(out.read_bytes())
    fee = estimated["paper_fee_assessment"]
    assert fee["status"] == "RECONCILED_WITH_ESTIMATED_PAPER_FEE"
    assert not fee["blocks_paper_research"] and not fee["new_orders_authorized"]
    assert Decimal(fee["estimated_fee_usd"]) == Decimal("0.99")
    assert Decimal(fee["cash_residual_after_estimated_fees_usd"]) == 0
    assert fee["filled_order_count"] == 1
    assert estimated["observation_summary"] == strict["observation_summary"]
    assert estimated["source_declared"] == strict["source_declared"]
    assert estimated["source_declared"]["result"] == "BLOCKED"
    assert estimated["observation_summary"]["reconciliation_diagnosis"]["stop_status"] == "STOP_RECORDED"
    assert saved.read_bytes() == original
    assert (saved.parent / "private.sqlite").read_bytes() == journal
    assert "paper_fee_assessment" not in strict


def test_fixed_fee_is_not_fitted_to_an_arbitrary_residual(saved):
    result = reader.analyze_report(saved, paper_fee_usd="1.99")
    fee = result["paper_fee_assessment"]
    assert fee["status"] == "CASH_MISMATCH" and fee["blocks_paper_research"]
    assert Decimal(fee["cash_residual_after_estimated_fees_usd"]) == 1


def test_old_missing_terms_stay_available_for_analysis_not_waived(saved):
    doc = json.loads(saved.read_bytes())
    for event in doc["evidence"]["events"]:
        event.pop("cash_arithmetic", None)
    saved.write_text(json.dumps(doc))
    result = reader.analyze_report(saved, paper_fee_usd="0.99")
    assert result["paper_fee_assessment"]["status"] == "INSUFFICIENT_RECORDED_SUPPORT"
    assert result["source_declared"]["result"] == "BLOCKED"


def test_position_or_other_failure_is_not_overridden_by_fee(saved):
    doc = json.loads(saved.read_bytes())
    last = [e for e in doc["evidence"]["events"] if e["kind"] == "RECONCILIATION"][-1]
    last["position_residuals"]["US.SPY"] = "1"
    saved.write_text(json.dumps(doc))
    result = reader.analyze_report(saved, paper_fee_usd="0.99")
    assert result["paper_fee_assessment"]["blocks_paper_research"]


@pytest.mark.parametrize("fee", ["-0.99", "NaN", "Infinity", "0.991", True, "101"])
def test_invalid_fee_is_not_an_admission_override(fee):
    with pytest.raises((ValueError, RuntimeError)):
        assess_cash(observed_cash_change="-100.99", gross_cash_flow="-100", filled_order_count=1, fee_usd=fee)


def test_round_trip_cash_includes_both_filled_orders_once():
    result = assess_cash(observed_cash_change="8.02", gross_cash_flow="10", filled_order_count=2)
    assert result["status"] == "RECONCILED_WITH_ESTIMATED_PAPER_FEE"
    assert Decimal(result["estimated_fee_usd"]) == Decimal("1.98")
    assert Decimal(result["cash_residual_after_estimated_fees_usd"]) == 0
    unfilled = assess_cash(observed_cash_change="0", gross_cash_flow="0", filled_order_count=0)
    assert unfilled["status"] == "RECONCILED_WITHOUT_ESTIMATED_FEE"
    assert Decimal(unfilled["estimated_fee_usd"]) == 0
