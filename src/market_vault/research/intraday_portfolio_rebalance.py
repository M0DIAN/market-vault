"""Daily target cash reallocation between two recorded DEV strategy sleeves.

Each source keeps its own trades and proportional costs. Cash-only transfers
at flat session boundaries are free under this explicit research assumption.
"""

from __future__ import annotations

import math

from .intraday_data import digest
from .intraday_portfolio import _account_summary, _complementarity, _prepare_portfolio
from .intraday_return_uncertainty import _finite
from .intraday_risk_diagnostics import _metric, _reconcile
from .strategy_experiment import StrategyExperiment


INTRADAY_PORTFOLIO_REBALANCE_VERSION = "market-vault-intraday-portfolio-rebalance-v1"
_SLEEVES = ("A", "B", "CASH")
_COST_FIELDS = ("market_pnl", "commission_total", "slippage_total")


def _daily_costs(execution):
    trades = {day["trading_day"]: [] for day in execution["daily"]}
    for trade in execution["trades"]:
        trades[trade["trading_day"]].append(trade)
    return {day: {"market_pnl": _finite(math.fsum(
        row["quantity"] * (row["exit_raw_open"] - row["entry_raw_open"]) for row in rows)),
        **{key: _finite(math.fsum(row[key] for row in rows)) for key in _COST_FIELDS[1:]}}
        for day, rows in trades.items()}


def _attribution(allocations, transfers, allocation, final, reason=None):
    result = []
    for sleeve, weight in zip(_SLEEVES, (allocation["weight_a"], allocation["weight_b"], allocation["cash_weight"]), strict=True):
        amounts = {key: None for key in ("final_cash", "cash_contribution", *_COST_FIELDS, "net_transfers")}
        if reason is None:
            days = [row for row in allocations if row["sleeve"] == sleeve]
            amounts = {"final_cash": days[-1]["cash_close"],
                       **{key: _finite(math.fsum(row[key] for row in days)) for key in ("cash_contribution", *_COST_FIELDS)},
                       "net_transfers": _finite(math.fsum(row["net_transfer"] for row in transfers if row["sleeve"] == sleeve))}
            _reconcile(amounts["final_cash"], math.fsum((weight, amounts["cash_contribution"], amounts["net_transfers"])),
                       "reallocated sleeve final cash")
        result.append({"sleeve": sleeve, "weight": _metric(weight, "RATIO"),
                       "initial_allocation": _metric(weight, "INITIAL_CASH_UNITS"),
                       **{key: _metric(value, "INITIAL_CASH_UNITS", reason) for key, value in amounts.items()}})
    if reason is None:
        _reconcile(math.fsum(row["final_cash"]["value"] for row in result), final, "reallocated final cash")
        _reconcile(math.fsum(row["net_transfers"]["value"] for row in result), 0, "net cash transfers")
        contribution = math.fsum(row["cash_contribution"]["value"] for row in result)
        _reconcile(contribution, final - 1, "reallocated trading contributions")
        _reconcile(math.fsum(row["market_pnl"]["value"] - row["commission_total"]["value"] - row["slippage_total"]["value"]
                             for row in result), contribution, "reallocated cost attribution")
    return result


def _reallocated_account(a, b, allocation):
    daily, allocations, transfers, factors = [], [], [], {}
    weights = (allocation["weight_a"], allocation["weight_b"], allocation["cash_weight"])
    costs_a, costs_b = _daily_costs(a), _daily_costs(b)
    wealth, previous = 1.0, None
    for da, db in zip(a["daily"], b["daily"], strict=True):
        if wealth <= 0:
            raise ValueError("reallocated daily return requires strictly positive opening cash")
        targets = tuple(_finite(weight * wealth) for weight in weights)
        _reconcile(math.fsum(targets), wealth, "daily target cash")
        scales = tuple(_finite(target / day["cash_open"]) for target, day in zip(targets[:2], (da, db), strict=True))
        closes = tuple(_finite(scale * day["cash_close"]) for scale, day in zip(scales, (da, db), strict=True)) + targets[2:]
        day, clock = da["trading_day"], da["open_time"]
        factors[day] = (*scales, targets[2])
        if previous is not None:
            amounts = tuple(_finite(target - old) for target, old in zip(targets, previous, strict=True))
            _reconcile(math.fsum(amounts), 0, "daily cash transfers")
            transfers.extend({"trading_day": day, "open_time": clock, "sleeve": sleeve,
                "previous_cash_close": old, "target_cash": target, "net_transfer": amount}
                for sleeve, old, target, amount in zip(_SLEEVES, previous, targets, amounts, strict=True))
        for index, (sleeve, weight, target, closed) in enumerate(zip(_SLEEVES, weights, targets, closes, strict=True)):
            source = (da, db)[index] if index < 2 else None
            scale = scales[index] if source is not None else None
            costs = (costs_a, costs_b)[index][day] if source is not None else None
            amounts = {key: _finite(scale * costs[key]) if costs is not None else 0.0 for key in _COST_FIELDS}
            contribution = _finite(closed - target)
            _reconcile(amounts["market_pnl"] - amounts["commission_total"] - amounts["slippage_total"], contribution,
                       "daily sleeve trading contribution")
            allocations.append({"trading_day": day, "open_time": clock, "sleeve": sleeve, "target_weight": weight,
                "source_cash_open": source["cash_open"] if source is not None else None, "scale_factor": scale,
                "allocated_cash": target, "cash_close": closed, "cash_contribution": contribution, **amounts})
        closed = _finite(math.fsum(closes))
        returns = tuple(_finite(row["cash_close"] / row["cash_open"] - 1) for row in (da, db))
        value = _finite(closed / wealth - 1)
        _reconcile(value, math.fsum(weight * ret for weight, ret in zip(weights[:2], returns, strict=True)),
                   "daily target-weight return")
        daily.append({**{key: da[key] for key in ("trading_day", "open_time", "close_time")},
            "cash_open": wealth, "cash_close": closed, "return": value, "return_a": returns[0], "return_b": returns[1]})
        wealth, previous = closed, closes
    path, peak, boundaries = [], 1.0, {}
    for pa, pb in zip(a["ledger"], b["ledger"], strict=True):
        scale_a, scale_b, cash = factors[pa["trading_day"]]
        amounts = {key: _finite(math.fsum((cash, scale_a * pa[key], scale_b * pb[key]))) for key in ("equity", "cash")}
        peak = max(peak, amounts["equity"])
        point = {**{key: pa[key] for key in ("sequence", "trading_day", "slot", "timestamp", "phase")},
                 **amounts, "drawdown": _finite(1 - amounts["equity"] / peak)}
        path.append(point)
        boundary = boundaries.setdefault(pa["trading_day"], [point, point])
        boundary[1] = point
    for day in daily:
        for point, expected in zip(boundaries[day["trading_day"]], (day["cash_open"], day["cash_close"]), strict=True):
            _reconcile(point["cash"], expected, "reallocated session-boundary cash")
            _reconcile(point["equity"], expected, "reallocated session-boundary equity")
    return path, daily, allocations, transfers


def analyze_intraday_portfolio_rebalance(left_snapshot: StrategyExperiment, right_snapshot: StrategyExperiment, *,
                                         left_cost_index: int = 0, left_candidate_index: int = 0,
                                         right_cost_index: int = 0, right_candidate_index: int = 0,
                                         weight_a: float = .5, weight_b: float = .5) -> dict:
    """Reallocate at recorded flat daily boundaries, without orders or refits."""
    left, right, allocation, basis, sample, account_checks, values, reason, detail = _prepare_portfolio(
        left_snapshot, right_snapshot, left_cost_index=left_cost_index, left_candidate_index=left_candidate_index,
        right_cost_index=right_cost_index, right_candidate_index=right_candidate_index, weight_a=weight_a, weight_b=weight_b)
    allocation.update(method="DAILY_TARGET_CASH_REALLOCATION", cash_transfer_cost=0.0)
    a, b, ab, bb = (selected[index]["execution"] for selected, index in ((left, 2), (right, 2), (left, 3), (right, 3)))
    derived = None
    if reason is None:
        try:
            complementarity = _complementarity(a, b, values["LEFT", "STRATEGY"], values["RIGHT", "STRATEGY"], sample)
            path, daily, allocations, transfers = _reallocated_account(a, b, allocation)
            benchmark_path, benchmark_daily, benchmark_allocations, benchmark_transfers = _reallocated_account(ab, bb, allocation)
            for point, other in zip(path, benchmark_path, strict=True):
                point.update({"benchmark_" + key: other[key] for key in ("cash", "equity", "drawdown")})
            for day, other in zip(daily, benchmark_daily, strict=True):
                day.update({"benchmark_" + key: other[key] for key in ("cash_open", "cash_close", "return")})
            derived = {"complementarity": complementarity, "portfolio": _account_summary(daily, path),
                "benchmark": _account_summary(daily, path, benchmark=True), "path": path, "daily_returns": daily,
                "daily_allocations": {"portfolio": allocations, "benchmark": benchmark_allocations},
                "cash_transfers": {"portfolio": transfers, "benchmark": benchmark_transfers},
                "attribution": {"portfolio": _attribution(allocations, transfers, allocation, daily[-1]["cash_close"]),
                    "benchmark": _attribution(benchmark_allocations, benchmark_transfers, allocation, benchmark_daily[-1]["cash_close"])}}
        except (ValueError, ArithmeticError) as exc:
            reason = "NUMERIC_OVERFLOW" if isinstance(exc, ArithmeticError) else "RECORDED_PORTFOLIO_RECONCILIATION_FAILED"
            detail = str(exc)
    if derived is None:
        derived = {"complementarity": _complementarity(a, b, None, None, sample, reason),
            "portfolio": _account_summary([], [], reason=reason), "benchmark": _account_summary([], [], reason=reason),
            "path": [], "daily_returns": [], "daily_allocations": {"portfolio": [], "benchmark": []},
            "cash_transfers": {"portfolio": [], "benchmark": []},
            "attribution": {name: _attribution([], [], allocation, None, reason) for name in ("portfolio", "benchmark")}}
    result = {"version": INTRADAY_PORTFOLIO_REBALANCE_VERSION, "status": "SUCCESS", "evidence": "RECORDED_LEDGER_DERIVATION",
        "left": left[0], "right": right[0], "allocation": allocation, "basis": basis, "sample": sample,
        "availability": {"status": "AVAILABLE" if reason is None else "UNAVAILABLE",
                         "unavailable_reason": reason, "detail": detail, "account_checks": account_checks}, **derived}
    result["portfolio_rebalance_id"] = digest(result)
    return result
