"""Synthetic existing-journal cash arithmetic; no SDK, market data or account."""
from copy import deepcopy
from decimal import Decimal
import json

import pytest

from market_vault.moomoo_simulation_cash import replay_cash_arithmetic


def snapshot():
    account = dict(cash="747.80", currency="USD", cash_basis="USD_CURRENCY_BALANCE",
                   positions={"US.SPY": "1"}, started_at_utc="2026-01-05T15:01:00+00:00",
                   finished_at_utc="2026-01-05T15:01:01+00:00")
    baseline = dict(account, cash="1000.00", positions={})
    order = dict(order_id="private-order", order_status="FILLED_ALL", dealt_qty="1",
                 dealt_avg_price="250.00", updated_time="2026-01-05T10:00:00")
    events = [
        dict(kind="ACCOUNT_BASELINE", **baseline),
        dict(kind="SUBMISSION_INTENT", intent_id="private-intent"),
        dict(kind="ORDER_OBSERVATION", intent_id="private-intent", **order),
        dict(kind="ACCOUNT_OBSERVATION", **account),
        dict(kind="ORDER_OBSERVATION", intent_id="private-intent", **order),
        dict(kind="RECONCILIATION", result="BLOCKED", orders=[order], account_observation=account,
             cash_basis="USD_CURRENCY_BALANCE", baseline_cash_basis="USD_CURRENCY_BALANCE",
             cash_expected_before_unobserved_fees_usd="750.00", cash_residual_usd="-2.20"),
        dict(kind="EMERGENCY_STOP"),
    ]
    return [dict(e, seq=index) for index, e in enumerate(events, 1)]


def test_replay_independent_terms_preserves_blocked_source_and_privacy():
    events = snapshot()
    before = deepcopy(events)
    result = replay_cash_arithmetic(events, 6)
    assert events == before
    assert result["status"] == "RECOMPUTED_MATCH"
    assert Decimal(result["gross_buy_notional_usd"]) == 250
    assert Decimal(result["observed_cash_change_usd"]) == Decimal("-252.20")
    assert Decimal(result["recomputed_cash_residual_usd"]) == Decimal("-2.20")
    assert result["order_observation_seqs"] == [5]  # Two queries, one cumulative debit.
    assert result["baseline_seq"] == 1 and result["account_observation_seq"] == 4
    assert result["fees"] == result["cash_flows"] == "NOT_OBSERVED"
    assert result["new_orders_authorized"] is False
    text = json.dumps(result)
    for private in ("private-order", "private-intent", "US.SPY", "747.80", "1000.00"):
        assert private not in text
    assert events[5]["result"] == "BLOCKED" and events[-1]["kind"] == "EMERGENCY_STOP"


@pytest.mark.parametrize("field,value", [
    ("cash_residual_usd", "0"), ("cash_expected_before_unobserved_fees_usd", "749.00"),
])
def test_original_arithmetic_is_not_used_as_replay_input(field, value):
    events = snapshot()
    events[5][field] = value
    result = replay_cash_arithmetic(events, 6)
    assert result["status"] == "RECOMPUTED_MISMATCH"
    assert Decimal(result["recomputed_cash_residual_usd"]) == Decimal("-2.20")
    assert result["new_orders_authorized"] is False


def test_later_account_and_orders_never_rewrite_historical_comparison():
    events = snapshot()
    events += [dict(events[3], seq=8, cash="999999.00"), dict(events[4], seq=9, dealt_avg_price="999.00")]
    assert replay_cash_arithmetic(events, 6) == replay_cash_arithmetic(snapshot(), 6)


@pytest.mark.parametrize("mutation,reason", [
    (lambda e: e[5].pop("account_observation"), "COMPARISON_TERMS_NOT_RECORDED"),
    (lambda e: e[0].pop("cash"), "INVALID_RECORDED_NUMBER"),
    (lambda e: e[0].update(cash_basis="LEGACY_DISPLAY_USD"), "CASH_BASIS_UNVERIFIED_OR_CHANGED"),
    (lambda e: e[5].update(orders=[]), "ORDER_EVIDENCE_INCONSISTENT"),
    (lambda e: e[4].update(order_id="different-private-id"), "ORDER_EVIDENCE_INCONSISTENT"),
    (lambda e: e[3].update(cash="748.00"), "ACCOUNT_SNAPSHOT_INCONSISTENT"),
    (lambda e: e[1].update(seq=99), "EVENT_SEQUENCE_INCONSISTENT"),
])
def test_missing_or_inconsistent_support_is_unavailable(mutation, reason):
    events = deepcopy(snapshot())
    mutation(events)
    result = replay_cash_arithmetic(events, 6)
    assert result["status"] == "UNAVAILABLE" and result["reason"] == reason
    assert result["observed_cash_change_usd"] is None
    assert result["gross_buy_notional_usd"] is None


@pytest.mark.parametrize("bad", [True, "NaN", "Infinity", "private-value"])
def test_invalid_numbers_never_escape_as_amounts_or_errors(bad):
    events = snapshot()
    events[0]["cash"] = bad
    result = replay_cash_arithmetic(events, 6)
    assert result["status"] == "UNAVAILABLE"
    assert result["reason"] == "INVALID_RECORDED_NUMBER"
    assert "private-value" not in json.dumps(result)


def test_original_legacy_usd_basis_without_additive_fields():
    events = snapshot()
    for item in (events[0], events[3], events[5]["account_observation"], events[5]):
        item.pop("cash_basis", None)
        item.pop("baseline_cash_basis", None)
    result = replay_cash_arithmetic(events, 6)
    assert result["status"] == "RECOMPUTED_MATCH" and result["cash_basis"] == "LEGACY_DISPLAY_USD"
    events[0]["currency"] = "JPY"
    assert replay_cash_arithmetic(events, 6)["status"] == "UNAVAILABLE"


def test_zero_intention_preparation_has_zero_debit_not_missing_order():
    events = snapshot()
    baseline, account = events[0], events[3]
    account["cash"] = "1000.00"
    account["positions"] = {}
    compared = dict(events[5], orders=[], account_observation=account,
                    cash_expected_before_unobserved_fees_usd="1000.00", cash_residual_usd="0")
    prefix = [dict(e, seq=n) for n, e in enumerate((baseline, account, compared), 1)]
    result = replay_cash_arithmetic(prefix, 3)
    assert result["status"] == "RECOMPUTED_MATCH"
    assert Decimal(result["gross_buy_notional_usd"]) == 0
    assert result["order_observation_seqs"] == []


@pytest.mark.parametrize("change", ["missing", "changed_fill", "changed_time"])
def test_order_observations_must_bracket_cash_with_identical_snapshot(change):
    events = deepcopy(snapshot())
    if change == "missing":
        events[2]["kind"] = "SUBMISSION_ACK"
    elif change == "changed_fill":
        events[2].update(order_status="SUBMITTED", dealt_qty="0", dealt_avg_price="0")
    else:
        events[2]["updated_time"] = "2026-01-05T09:59:59"
    result = replay_cash_arithmetic(events, 6)
    assert result["status"] == "UNAVAILABLE"
    assert result["reason"] == "ORDER_SNAPSHOT_NOT_STABLE"


@pytest.mark.parametrize("state,quantity,average", [
    ("FILLED_ALL", "0", "0"), ("SUBMITTED", "1", "250.00"),
    ("FILLED_PART", "1", "250.00"), ("CANCELLED_PART", "0", "0"),
    ("UNRECOGNIZED", "1", "250.00"), ("FAILED", "1", "250.00"),
])
def test_impossible_status_fill_combinations_do_not_become_arithmetic_evidence(state, quantity, average):
    events = deepcopy(snapshot())
    for item in (events[2], events[4], events[5]["orders"][0]):
        item.update(order_status=state, dealt_qty=quantity, dealt_avg_price=average)
    # Make the stored arithmetic match even an impossible zero-quantity order.
    if quantity == "0":
        events[5].update(cash_expected_before_unobserved_fees_usd="1000.00", cash_residual_usd="-252.20")
    result = replay_cash_arithmetic(events, 6)
    assert result["status"] == "UNAVAILABLE"
    assert result["reason"] == "ORDER_EVIDENCE_INCONSISTENT"


@pytest.mark.parametrize('contradictory', [True, False])
def test_all_post_cash_observations_must_remain_stable(contradictory):
    events = deepcopy(snapshot())
    extra = dict(events[4])
    if contradictory:
        extra.update(order_status='SUBMITTED', dealt_qty='0', dealt_avg_price='0')
    events.insert(4, extra)
    events = [dict(e, seq=n) for n, e in enumerate(events, 1)]
    result = replay_cash_arithmetic(events, 7)
    assert result['status'] == ('UNAVAILABLE' if contradictory else 'RECOMPUTED_MATCH')
    if contradictory:
        assert result['reason'] == 'ORDER_SNAPSHOT_NOT_STABLE'
    else:
        assert Decimal(result['gross_buy_notional_usd']) == 250
