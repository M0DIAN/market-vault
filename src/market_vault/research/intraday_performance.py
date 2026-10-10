"""Descriptive performance from recorded V2 trades, with no source reads or fit.

Cash attribution uses the quantity actually bought, not a counterfactual
zero-cost account. It therefore reconciles commissions and slippage exactly
once against the continuous account. It is not a replay verification.
"""

from __future__ import annotations

from datetime import datetime
import math
import statistics

from ..backtest.intraday import INTRADAY_COST_VERSION, INTRADAY_EXECUTION_VERSION
from .intraday_data import digest


INTRADAY_PERFORMANCE_VERSION = "market-vault-intraday-performance-v1"
BREAKEVEN_RETURN_TOLERANCE = 1e-12


def _total(rows: list[dict], key: str) -> float:
    return math.fsum(row[key] for row in rows)


def _reconcile_cash(actual: float, expected: float, message: str) -> None:
    if not math.isfinite(actual) or not math.isfinite(expected):
        raise OverflowError("recorded cash arithmetic overflowed during reconciliation")
    if not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-12):
        raise ValueError(message)


def _attribution(rows: list[dict], group: str) -> dict:
    return {"group": group, "trade_count": len(rows),
            **{key: _total(rows, key) for key in
               ("market_pnl", "commission_total", "slippage_total", "net_cash_pnl", "holding_minutes")}}


def summarize_intraday_execution(execution: dict) -> dict:
    """Summarize execution produced by V2 or read from a validated experiment.

    Trades and every declared cash day are retained. Arithmetic reconciliation
    is checked independently of the saved metrics; this does not establish
    market-data authority or prove the original execution was run.
    """
    if (execution["version"] != INTRADAY_EXECUTION_VERSION
            or execution["cost_version"] != INTRADAY_COST_VERSION):
        raise ValueError("performance requires the supported execution V2 and fill-cost V2")
    daily = execution["daily"]
    opens = {row["trading_day"]: datetime.fromisoformat(row["open_time"]) for row in daily}
    session_minutes = math.fsum((datetime.fromisoformat(row["close_time"]) - opens[row["trading_day"]]).total_seconds() / 60
                               for row in daily)
    rows, day_groups, hour_groups, reason_groups = [], {day: [] for day in opens}, {}, {}
    for trade in execution["trades"]:
        entry, exit_ = (datetime.fromisoformat(trade[key]) for key in ("entry_time", "exit_time"))
        row = {"trade_id": trade["trade_id"], "trading_day": trade["trading_day"],
               "net_cash_pnl": trade["cash_after"] - trade["cash_before"],
               "market_pnl": trade["quantity"] * (trade["exit_raw_open"] - trade["entry_raw_open"]),
               "commission_total": trade["commission_total"], "slippage_total": trade["slippage_total"],
               "holding_minutes": (exit_ - entry).total_seconds() / 60,
               "held_bars": trade["held_bars"], "net_return": trade["cash_after"] / trade["cash_before"] - 1}
        expected = row["market_pnl"] - row["commission_total"] - row["slippage_total"]
        _reconcile_cash(row["net_cash_pnl"], expected,
                        "recorded trade cash does not reconcile with prices, quantity and costs")
        offset = int((entry - opens[row["trading_day"]]).total_seconds() // 3600)
        rows.append(row)
        day_groups[row["trading_day"]].append(row)
        hour_groups.setdefault(offset, []).append(row)
        reason_groups.setdefault(trade["exit_reason"], []).append(row)
    total = _attribution(rows, "ALL")
    metrics = execution["metrics"]
    expected_net = metrics["final_cash"] - metrics["initial_cash"]
    _reconcile_cash(total["net_cash_pnl"], expected_net,
                    "recorded trade cash does not reconcile with final account cash")
    for day in daily:
        pnl = _total(day_groups[day["trading_day"]], "net_cash_pnl")
        _reconcile_cash(pnl, day["cash_close"] - day["cash_open"],
                        "recorded trade cash does not reconcile with daily cash")
    wins = [r for r in rows if r["net_return"] > BREAKEVEN_RETURN_TOLERANCE]
    losses = [r for r in rows if r["net_return"] < -BREAKEVEN_RETURN_TOLERANCE]
    count = len(rows)
    summary = {}

    def metric(key, value, unit="NUMBER", reason=None):
        if value is not None and not math.isfinite(value):
            value, reason = None, "NUMERIC_OVERFLOW"
        summary[key] = {"value": value, "unit": unit, "unavailable_reason": reason}

    metric("trade_count", count, "COUNT")
    metric("winning_trades", len(wins), "COUNT")
    metric("losing_trades", len(losses), "COUNT")
    metric("breakeven_trades", count - len(wins) - len(losses), "COUNT")
    metric("win_rate", len(wins) / count if count else None, "RATIO", None if count else "NO_TRADES")
    metric("mean_trade_return", statistics.fmean(r["net_return"] for r in rows) if rows else None,
           "RATIO", None if rows else "NO_TRADES")
    gain, loss = _total(wins, "net_cash_pnl"), -_total(losses, "net_cash_pnl")
    metric("profit_factor", gain / loss if losses else None, reason=None if losses else "NO_LOSING_TRADES")
    metric("payoff_ratio", statistics.fmean(r["net_return"] for r in wins) / -statistics.fmean(r["net_return"] for r in losses)
           if wins and losses else None, reason=None if wins and losses else "NEEDS_WIN_AND_LOSS")
    for key in ("holding_minutes", "held_bars"):
        metric("mean_" + key, statistics.fmean(r[key] for r in rows) if rows else None,
               "MINUTES" if key == "holding_minutes" else "BARS", None if rows else "NO_TRADES")
    metric("exposure_ratio", total["holding_minutes"] / session_minutes, "RATIO")
    metric("evaluated_days", len(daily), "COUNT")
    metric("cash_only_days", sum(not rows for rows in day_groups.values()), "COUNT")
    for key in ("market_pnl", "commission_total", "slippage_total", "net_cash_pnl"):
        metric(key, total[key], "INITIAL_CASH_UNITS")
    result = {"version": INTRADAY_PERFORMANCE_VERSION, "execution_id": execution["execution_id"],
              "breakeven_return_tolerance": BREAKEVEN_RETURN_TOLERANCE,
              "session_minutes": session_minutes, "summary": summary,
              "by_exit_reason": [_attribution(reason_groups[key], key) for key in sorted(reason_groups)],
              "by_entry_hour": [_attribution(hour_groups[key], f"{key * 60}-{(key + 1) * 60}m") for key in sorted(hour_groups)],
              "by_trading_day": [_attribution(rows, day) for day, rows in day_groups.items()],
              "reconciliation_residual": total["market_pnl"] - total["commission_total"] - total["slippage_total"] - total["net_cash_pnl"]}
    result["performance_id"] = digest(result)
    return result


def analyze_intraday_experiment(snapshot, *, cost_index: int = 0, candidate_index: int = 0) -> dict:
    """Analyze one explicit candidate of a validated immutable Q7/Q8 snapshot."""
    from .strategy_experiment import StrategyExperiment
    if type(snapshot) is not StrategyExperiment:
        raise ValueError("an immutable StrategyExperiment is required")
    if any(type(v) is not int or v < 0 for v in (cost_index, candidate_index)):
        raise ValueError("cost_index and candidate_index must be nonnegative integers")
    root = snapshot.as_dict()
    report = root["report"]
    if root["artifact_schema_version"] in ("market-vault-intraday-experiment-v1", "market-vault-intraday-experiment-v2"):
        if cost_index >= len(report["groups"]) or candidate_index >= len(report["groups"][cost_index]["results"]):
            raise ValueError("selected cost/candidate index is outside the saved experiment")
        group = report["groups"][cost_index]
        candidate = group["results"][candidate_index]
        identity, scope = candidate["candidate_id"], "DEVELOPMENT_WALK_FORWARD_ONLY"
    elif root["artifact_schema_version"] in ("market-vault-intraday-test-v1", "market-vault-intraday-test-v2"):
        if cost_index or candidate_index:
            raise ValueError("TEST contains one frozen result; both indices must be zero")
        group = candidate = report
        identity, scope = report["final_test_id"], "FROZEN_SINGLE_CANDIDATE_TEST"
    else:
        raise ValueError("performance requires an intraday development or TEST experiment")
    return {"version": INTRADAY_PERFORMANCE_VERSION, "experiment_id": root["experiment_id"],
            "data_id": root["dataset_id"], "evaluation_scope": scope, "candidate_id": identity,
            "evidence": "RECORDED_LEDGER_DERIVATION", "strategy": candidate["strategy"],
            "execution_policy": group["execution_policy"],
            "performance": summarize_intraday_execution(candidate["execution"]),
            "benchmark": summarize_intraday_execution(group["benchmark"]["execution"])}
