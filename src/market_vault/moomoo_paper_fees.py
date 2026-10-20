"""Owner-selected simulation cost assumptions, never a broker fee attestation.

A fixed per-filled-order fee is supplied before evaluating a comparison. It is
not fitted to whatever cash difference happened to be observed. Legacy journal
results and stop flags are not changed by this purely numerical policy.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from .moomoo_simulation_orders import number

PAPER_FEE_POLICY = "OWNER_ESTIMATED_FLAT_PAPER_FEE_V1"
DEFAULT_PAPER_FEE_USD = "0.99"
CASH_ROUNDING_USD = Decimal("0.01")


def fee_amount(value: Any) -> Decimal:
    amount = number(value)
    if amount < 0 or amount > 100 or amount != amount.quantize(Decimal("0.01")):
        raise ValueError("PAPER_FEE_REQUIRES_NONNEGATIVE_CENTS_UP_TO_100_USD")
    return amount


def assess_cash(*, observed_cash_change: Any, gross_cash_flow: Any,
                filled_order_count: int, fee_usd: Any = DEFAULT_PAPER_FEE_USD) -> dict:
    """BUY gross flow is negative; SELL gross flow positive. Count each order once.

    The one-cent tolerance is currency rounding only, not an unlimited residual
    allowance. Unfilled/cancelled-without-fill orders do not create estimated fees.
    """
    per_order = fee_amount(fee_usd)
    if type(filled_order_count) is not int or filled_order_count < 0:
        raise ValueError("INVALID_FILLED_ORDER_COUNT")
    delta, gross = number(observed_cash_change), number(gross_cash_flow)
    estimated = per_order * filled_order_count
    raw = delta - gross
    adjusted = raw + estimated
    matched = abs(adjusted) <= CASH_ROUNDING_USD
    return {
        "policy": PAPER_FEE_POLICY, "environment": "SIMULATE",
        "status": ("RECONCILED_WITH_ESTIMATED_PAPER_FEE" if matched and estimated > 0
                   else "RECONCILED_WITHOUT_ESTIMATED_FEE" if matched else "CASH_MISMATCH"),
        "fee_per_filled_order_usd": format(per_order, ".2f"),
        "filled_order_count": filled_order_count, "estimated_fee_usd": str(estimated),
        "cash_residual_before_estimated_fees_usd": str(raw),
        "cash_residual_after_estimated_fees_usd": str(adjusted),
        "rounding_tolerance_usd": str(CASH_ROUNDING_USD),
        "fee_basis": "OWNER_ACCEPTED_ASSUMPTION_NOT_BROKER_DETAIL",
        "new_orders_authorized": False,
    }


def assess_saved_analysis(analysis: dict, fee_usd: Any) -> dict:
    """Add one research conclusion to the existing validated saved-report result.

    This operates on the analyzer's recomputed public fields, not a user-supplied
    embedded summary. No SQLite, broker request or state mutation occurs here.
    """
    amount = fee_amount(fee_usd)
    result = {
        "policy": PAPER_FEE_POLICY, "fee_per_filled_order_usd": format(amount, ".2f"),
        "status": "INSUFFICIENT_RECORDED_SUPPORT", "blocks_paper_research": True,
        "new_orders_authorized": False, "original_result_preserved": True,
        "original_stop_preserved": True,
    }
    comparisons = analysis["cash_arithmetic"]
    diagnosis = analysis["observation_summary"]["reconciliation_diagnosis"]
    if not comparisons:
        return result
    last = comparisons[-1]
    if (last["status"] != "PUBLIC_EQUATION_VERIFIED"
            or last.get("exporter_replay_status") != "RECOMPUTED_MATCH"
            or last["reconciliation_seq"] != diagnosis["reconciliation_seq"]
            or diagnosis["unresolved_intention_count"] != 0
            or diagnosis["owned_position_status"] != "OWNED_QUANTITIES_MATCH_AS_RECORDED"
            or diagnosis["reconciliation_error"] not in (None, "ACCOUNT_RESIDUAL_UNEXPLAINED")):
        return result
    # v1 supports one BUY intention. Public validation has already bound its
    # cumulative quantity/price and aliases. A positive gross amount means a fill.
    gross = number(last["gross_buy_notional_usd"])
    if gross <= 0:
        return result
    assessment = assess_cash(observed_cash_change=last["cash_change_declared_usd"],
                             gross_cash_flow=-gross, filled_order_count=1, fee_usd=amount)
    result.update(assessment, reconciliation_seq=last["reconciliation_seq"],
                  blocks_paper_research=assessment["status"] == "CASH_MISMATCH",
                  cash_change_basis="LOCAL_EXPORTER_DECLARATION")
    return result
