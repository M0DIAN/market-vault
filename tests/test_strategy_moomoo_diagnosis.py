from __future__ import annotations

from copy import deepcopy

import pytest

from market_vault.moomoo_simulation_observations import format_diagnosis, summarize


def evidence():
    """Synthetic projection; no owner market/account records are committed."""
    return {
        "intentions": [{"intent": "intent-1", "symbol": "US.SPY", "qty": 1, "limit_price": "500.00"}],
        "unrecognized_event_count": 0, "stopped": True,
        "events": [
            {"seq": 1, "kind": "SUBMISSION_CALL", "intent": "intent-1", "recorded_at_utc": "2026-10-16T15:00:00+00:00"},
            {"seq": 2, "kind": "ORDER_OBSERVATION", "intent": "intent-1", "order": "order-1",
             "order_status": "FILLED_ALL", "dealt_qty": "1", "dealt_avg_price": "499",
             "updated_time": "2026-10-16T11:00:01", "recorded_at_utc": "2026-10-16T15:00:02+00:00"},
            {"seq": 3, "kind": "RECONCILIATION", "intent": None, "recorded_at_utc": "2026-10-16T15:00:03+00:00",
             "result": "BLOCKED", "error_code": "ACCOUNT_RESIDUAL_UNEXPLAINED",
             "position_residuals": {"US.SPY": "0"}, "cash_residual_usd": "-0.73",
             "cash_basis": "USD_CURRENCY_BALANCE", "baseline_cash_basis": "USD_CURRENCY_BALANCE"},
            {"seq": 4, "kind": "EMERGENCY_STOP", "intent": None, "recorded_at_utc": "2026-10-16T15:00:04+00:00"},
        ],
    }


def test_order_and_owned_quantity_are_distinct_from_unexplained_cash_and_stop():
    source = evidence()
    before = deepcopy(source)
    summary = summarize(source)
    item = summary["reconciliation_diagnosis"]
    assert item["order_states"] == {"FILLED_ALL": 1}
    assert item["owned_position_status"] == "OWNED_QUANTITIES_MATCH_AS_RECORDED"
    assert item["cash_status"] == "UNATTRIBUTED_DECREASE" and item["cash_residual_usd"] == "-0.73"
    assert item["reconciliation_result"] == "BLOCKED"
    assert item["reconciliation_error"] == "ACCOUNT_RESIDUAL_UNEXPLAINED"
    assert item["fees"] == "NOT_OBSERVED" and item["cash_attribution"] == "NOT_ESTABLISHED"
    assert item["stop_status"] == "STOP_RECORDED" and not item["new_orders_authorized"]
    assert item["reconciliation_seq"] == 3 and item["subsequent_activity_recorded"]
    assert source == before
    line = format_diagnosis(summary)
    assert "FILLED_ALL:1" in line and "CASH_RESIDUAL_USD=-0.73" in line and "RECORDED_ONLY" in line
    assert "US.SPY" not in line and "499" not in line  # console contains no order/position details


@pytest.mark.parametrize("residual,status", [("-0.000001", "UNATTRIBUTED_DECREASE"),
                                             ("0", "ZERO_RESIDUAL_AS_RECORDED"),
                                             ("2.50", "UNATTRIBUTED_INCREASE")])
def test_no_tolerance_or_fee_guess_from_amount(residual, status):
    source = evidence()
    source["events"][2]["cash_residual_usd"] = residual
    item = summarize(source)["reconciliation_diagnosis"]
    assert item["cash_status"] == status and item["cash_residual_usd"] == residual
    assert item["reconciliation_result"] == "BLOCKED" and not item["new_orders_authorized"]
    assert item["fees"] == "NOT_OBSERVED"


@pytest.mark.parametrize("mode,status", [("missing", "BASIS_UNVERIFIED"), ("changed", "BASIS_MISMATCH"),
                                         ("race", "NOT_COMPARED"), ("no_cash", "NOT_COMPARED")])
def test_basis_and_comparison_stage_cannot_be_inferred(mode, status):
    source = evidence()
    record = source["events"][2]
    if mode == "missing":
        record.pop("cash_basis")
    elif mode == "changed":
        record["cash_basis"] = "LEGACY_DISPLAY_USD"
    elif mode == "race":
        record["error_code"] = "ORDER_CHANGED_DURING_ACCOUNT_SNAPSHOT"
    else:
        record.pop("cash_residual_usd")
    assert summarize(source)["reconciliation_diagnosis"]["cash_status"] == status


@pytest.mark.parametrize("positions,status", [({}, "NOT_COMPARED"), ({"US.SPY": "1"}, "OWNED_QUANTITY_DIFFERENCE")])
def test_missing_owned_quantity_is_not_zero(positions, status):
    source = evidence()
    source["events"][2]["position_residuals"] = positions
    assert summarize(source)["reconciliation_diagnosis"]["owned_position_status"] == status


def test_no_order_and_no_comparison_are_not_full_account_success():
    summary = summarize({"events": [], "intentions": [], "stopped": False, "unrecognized_event_count": 0})
    item = summary["reconciliation_diagnosis"]
    assert item["order_status"] == "NO_RECORDED_INTENTIONS" and not item["order_states"]
    assert item["owned_position_status"] == item["cash_status"] == "NOT_COMPARED"
    assert item["reconciliation_seq"] is None and not item["new_orders_authorized"]


def test_later_query_failure_keeps_order_unresolved_and_comparison_historical():
    source = evidence()
    source["events"].append({"seq": 5, "kind": "ORDER_QUERY_FAILED", "intent": "intent-1",
                             "recorded_at_utc": "2026-10-16T15:01:00+00:00"})
    item = summarize(source)["reconciliation_diagnosis"]
    assert item["order_status"] == "UNRESOLVED" and not item["order_states"]
    assert item["subsequent_activity_recorded"] and item["cash_residual_usd"] == "-0.73"


def test_false_match_does_not_turn_a_nonzero_residual_into_acceptance():
    source = evidence()
    source["events"][2].update(result="OBSERVATIONS_MATCH", error_code=None)
    item = summarize(source)["reconciliation_diagnosis"]
    assert item["cash_status"] == "INCONSISTENT_RECONCILIATION_RECORD"
    assert item["cash_residual_usd"] == "-0.73" and not item["new_orders_authorized"]


def test_actual_qualifier_cash_block_stop_and_reopen_keep_result_and_budget(tmp_path, capsys, request):
    # Use the established external-SDK fixture only; full entry/journal/recovery/export are real.
    from test_strategy_moomoo_qualifier import run, submit_args
    broker = request.getfixturevalue("broker")
    assert run(tmp_path, "prepare")[0] == 0
    assert run(tmp_path, "submit", extra=submit_args())[0] == 0
    broker.rows[0].update(order_status="FILLED_ALL", dealt_qty=1, dealt_avg_price=499,
                          updated_time="2026-10-16 11:01:00")
    broker.positions, broker.cash = [dict(code="US.SPY", qty=1, position_side="LONG")], "9500.27"
    code, checked = run(tmp_path, "check")
    assert code == 1 and checked["result"] == "BLOCKED"
    item = checked["evidence"]["observation_summary"]["reconciliation_diagnosis"]
    assert item["cash_status"] == "UNATTRIBUTED_DECREASE"
    assert item["owned_position_status"] == "OWNED_QUANTITIES_MATCH_AS_RECORDED"
    assert run(tmp_path, "stop")[0] == 0
    assert run(tmp_path, "check", filename="check-stopped.json")[1]["evidence"]["stopped"]
    assert run(tmp_path, "submit", extra=submit_args(), filename="refused-resubmit.json")[0] == 1
    assert broker.calls.count("place") == 1
    assert "RECORDED_ONLY: ORDER=" in capsys.readouterr().out


# Imported fixture is registered for the real qualifier integration above.
from test_strategy_moomoo_qualifier import broker
