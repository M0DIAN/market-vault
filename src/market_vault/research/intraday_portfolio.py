"""Two saved DEV strategies with fixed initial capital and no capital transfers.

All results are recorded-ledger derivations. Original executions and their own
benchmarks keep their policies, cash and costs; no portfolio trade is invented.
"""

from __future__ import annotations

import math
import statistics

from ..backtest.risk import ZERO_VOLATILITY_TOLERANCE
from .intraday_data import digest
from .intraday_experiment import INTRADAY_EXPERIMENT_VERSION
from .intraday_return_uncertainty import _daily_values, _finite, _integer, _sample_coverage
from .intraday_risk_diagnostics import ZERO_RETURN_TOLERANCE, _clock, _metric, _reconcile
from .intraday_saved_comparison import _basis
from .strategy_experiment import StrategyExperiment


INTRADAY_PORTFOLIO_VERSION = "market-vault-intraday-portfolio-v1"
_HOLDING_CATEGORIES = ("both", "a_only", "b_only", "neither")


def _allocation(weight_a, weight_b):
    weights = []
    for name, value in (("weight_a", weight_a), ("weight_b", weight_b)):
        try:
            valid = type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError(f"{name} must be a finite nonnegative number no greater than 1")
        weights.append(0.0 if value == 0 else float(value))
    total = math.fsum(weights)
    if total > 1:
        raise ValueError("weight_a plus weight_b cannot exceed 1; weights are not normalized")
    return {"method": "FIXED_INITIAL_CAPITAL_SLEEVES", "initial_cash": 1.0,
            "weight_a": weights[0], "weight_b": weights[1], "cash_weight": 1 - total,
            "cash_interest_rate": 0.0}


def _selection(root, cost_index, candidate_index):
    if (root["artifact_schema_version"] != INTRADAY_EXPERIMENT_VERSION
            or root["evaluation_mode"] not in ("INTRADAY_COMPARISON", "INTRADAY_DIAGNOSTICS")
            or root["report"]["evaluation_scope"] != "DEVELOPMENT_WALK_FORWARD_ONLY"):
        raise ValueError("portfolio analysis requires two ordinary saved Q7 DEV comparison or diagnostics experiments")
    report = root["report"]
    if cost_index >= len(report["groups"]) or candidate_index >= len(report["groups"][cost_index]["results"]):
        raise ValueError("selected cost/candidate index is outside the saved experiment")
    context, group = report["context"], report["groups"][cost_index]
    candidate, benchmark = group["results"][candidate_index], group["benchmark"]
    sample = _sample_coverage(context)
    sample["unevaluated_development_day_count"] = len(context["unevaluated_development_days"])
    side = {"name": root["name"], "experiment_id": root["experiment_id"], "data_id": root["dataset_id"],
            "evaluation_mode": root["evaluation_mode"], "evaluation_scope": report["evaluation_scope"],
            "cost_index": cost_index, "candidate_index": candidate_index, "candidate_id": candidate["candidate_id"],
            "feature_fields": context["feature_fields"], "strategy": candidate["strategy"],
            "algorithm_versions": root["algorithm_versions"], "execution_policy": group["execution_policy"],
            "benchmark_execution_policy": benchmark["execution"]["policy"],
            "strategy_execution_id": candidate["execution"]["execution_id"],
            "benchmark_execution_id": benchmark["execution"]["execution_id"], "sample": sample}
    # Q11 needs the complete basis, without recalculating its separate Q9 views.
    return side, context, candidate, benchmark, None


def _risk(values, reason=None):
    count = len(values) if values is not None else None
    mean = _finite(statistics.mean(values)) if values else None
    deviation = _finite(statistics.stdev(values)) if values is not None and len(values) >= 2 else None
    if reason is None:
        reason = ("INSUFFICIENT_DAILY_RETURNS" if deviation is None else
                  "ZERO_VOLATILITY" if deviation <= ZERO_VOLATILITY_TOLERANCE else None)
    volatility = None if deviation is None else 0.0 if reason else _finite(deviation * math.sqrt(252))
    sharpe = None if reason else _finite(mean / deviation * math.sqrt(252))
    return {"annualization_factor": 252, "risk_free_rate": 0.0, "ddof": 1,
            "zero_volatility_tolerance": ZERO_VOLATILITY_TOLERANCE,
            "return_count": _metric(count, "COUNT", reason if count is None else None),
            "mean_daily_return": _metric(mean, "RATIO", reason if mean is None else None),
            "annualized_volatility": _metric(volatility, "RATIO", reason if volatility is None else None),
            "sharpe_ratio": _metric(sharpe, "NUMBER", reason if sharpe is None else None),
            "unavailable_reason": reason}


def _account_summary(daily, path, *, benchmark=False, reason=None):
    prefix = "benchmark_" if benchmark else ""
    final = daily[-1][prefix + "cash_close"] if daily else None
    drawdown = max(point[prefix + "drawdown"] for point in path) if path else None
    return {"summary": {"initial_cash": _metric(1.0, "INITIAL_CASH_UNITS"),
                "final_cash": _metric(final, "INITIAL_CASH_UNITS", reason),
                "total_return": _metric(_finite(final - 1) if final is not None else None, "RATIO", reason),
                "observed_max_drawdown": _metric(drawdown, "RATIO", reason)},
            "risk": _risk([row[prefix + "return"] for row in daily] if daily else None, reason)}


def _weighted(a, b, allocation):
    return _finite(math.fsum((allocation["cash_weight"], allocation["weight_a"] * a, allocation["weight_b"] * b)))


def _combined_path(a, b, ab, bb, allocation):
    path, daily = [], []
    peak = benchmark_peak = 1.0
    for pa, pb, pab, pbb in zip(a["ledger"], b["ledger"], ab["ledger"], bb["ledger"], strict=True):
        equity = _weighted(pa["equity"], pb["equity"], allocation)
        benchmark_equity = _weighted(pab["equity"], pbb["equity"], allocation)
        peak, benchmark_peak = max(peak, equity), max(benchmark_peak, benchmark_equity)
        path.append({**{key: pa[key] for key in ("sequence", "trading_day", "slot", "timestamp", "phase")},
            "equity": equity, "cash": _weighted(pa["cash"], pb["cash"], allocation),
            "drawdown": _finite(1 - equity / peak), "benchmark_equity": benchmark_equity,
            "benchmark_cash": _weighted(pab["cash"], pbb["cash"], allocation),
            "benchmark_drawdown": _finite(1 - benchmark_equity / benchmark_peak)})
    for da, db, dab, dbb in zip(a["daily"], b["daily"], ab["daily"], bb["daily"], strict=True):
        opened, closed = (_weighted(da[key], db[key], allocation) for key in ("cash_open", "cash_close"))
        benchmark_open, benchmark_close = (_weighted(dab[key], dbb[key], allocation) for key in ("cash_open", "cash_close"))
        if min(opened, benchmark_open) <= 0:
            raise ValueError("combined daily return requires strictly positive opening cash")
        daily.append({**{key: da[key] for key in ("trading_day", "open_time", "close_time")},
            "cash_open": opened, "cash_close": closed, "return": _finite(closed / opened - 1),
            "benchmark_cash_open": benchmark_open, "benchmark_cash_close": benchmark_close,
            "benchmark_return": _finite(benchmark_close / benchmark_open - 1),
            "return_a": _finite(da["cash_close"] / da["cash_open"] - 1),
            "return_b": _finite(db["cash_close"] / db["cash_open"] - 1)})
    return path, daily


def _correlation(a, b):
    if len(a) < 2:
        return _metric(None, "NUMBER", "INSUFFICIENT_DAILY_RETURNS")
    try:
        da, db = _finite(statistics.stdev(a)), _finite(statistics.stdev(b))
        if min(da, db) <= ZERO_VOLATILITY_TOLERANCE:
            return _metric(None, "NUMBER", "ZERO_VOLATILITY")
        ma, mb = statistics.mean(a), statistics.mean(b)
        # Standardize before multiplying, avoiding an overflowing covariance.
        value = _finite(math.fsum(((x - ma) / da) * ((y - mb) / db) / (len(a) - 1)
                                 for x, y in zip(a, b, strict=True)))
        return _metric(max(-1.0, min(1.0, value)), "NUMBER")
    except ArithmeticError:
        return _metric(None, "NUMBER", "NUMERIC_OVERFLOW")


def _holding_overlap(a, b, total_minutes):
    minutes = {key: [] for key in _HOLDING_CATEGORIES}
    sessions = {row["trading_day"]: (_clock(row["open_time"]), _clock(row["close_time"])) for row in a["daily"]}
    previous = {day: opened for day, (opened, _) in sessions.items()}
    for index in range(0, len(a["ledger"]), 2):
        opened, closed = a["ledger"][index:index + 2]
        start, end = _clock(opened["timestamp"]), _clock(closed["timestamp"])
        day = opened["trading_day"]
        if start != previous[day] or not start < end <= sessions[day][1]:
            raise ValueError("recorded OPEN-to-CLOSE intervals must cover each full session without gaps")
        previous[day] = end
        held_a, held_b = opened["quantity"] > 0, b["ledger"][index]["quantity"] > 0
        category = "both" if held_a and held_b else "a_only" if held_a else "b_only" if held_b else "neither"
        minutes[category].append((end - start).total_seconds() / 60)
    if any(previous[day] != closed for day, (_, closed) in sessions.items()):
        raise ValueError("recorded holding intervals do not reach every session close")
    totals = {key: _finite(math.fsum(values)) for key, values in minutes.items()}
    _reconcile(math.fsum(totals.values()), total_minutes, "holding-session minutes")
    return {key: {"minutes": _metric(value, "MINUTES"), "ratio": _metric(_finite(value / total_minutes), "RATIO")}
            for key, value in totals.items()}


def _complementarity(a, b, values_a, values_b, sample, reason=None):
    days = [] if reason else [day for day, av, bv in zip(sample["evaluated_days"], values_a, values_b, strict=True)
                             if av < -ZERO_RETURN_TOLERANCE and bv < -ZERO_RETURN_TOLERANCE]
    return {"correlation_method": "PEARSON_NET_DAILY_CASH_RETURN",
            "zero_volatility_tolerance": ZERO_VOLATILITY_TOLERANCE, "loss_return_tolerance": ZERO_RETURN_TOLERANCE,
            "holding_basis": "UTC_OPEN_TO_CLOSE_ELAPSED_MINUTES_OVER_ALL_SESSION_MINUTES",
            "correlation": _metric(None, "NUMBER", reason) if reason else _correlation(values_a, values_b),
            "joint_loss_count": _metric(None if reason else len(days), "COUNT", reason),
            "joint_loss_ratio": _metric(None if reason else len(days) / sample["sample_count"], "RATIO", reason),
            "joint_loss_days": days,
            "holding_overlap": {key: {"minutes": _metric(None, "MINUTES", reason), "ratio": _metric(None, "RATIO", reason)}
                                for key in _HOLDING_CATEGORIES} if reason else _holding_overlap(a, b, sample["total_session_minutes"])}


def _attribution(a, b, allocation, final, reason=None):
    rows = []
    for sleeve, weight, execution in (("A", allocation["weight_a"], a), ("B", allocation["weight_b"], b),
                                      ("CASH", allocation["cash_weight"], None)):
        amounts = {key: None for key in ("final_cash", "cash_contribution", "market_pnl", "commission_total", "slippage_total")}
        if reason is None:
            amounts = {key: 0.0 for key in amounts}
            amounts["final_cash"] = weight
            if execution is not None:
                amounts["final_cash"] = _finite(weight * execution["metrics"]["final_cash"])
                amounts["cash_contribution"] = _finite(weight * (execution["metrics"]["final_cash"] - 1))
                amounts["market_pnl"] = _finite(weight * math.fsum(
                    trade["quantity"] * (trade["exit_raw_open"] - trade["entry_raw_open"]) for trade in execution["trades"]))
                for key in ("commission_total", "slippage_total"):
                    amounts[key] = _finite(weight * math.fsum(trade[key] for trade in execution["trades"]))
        rows.append({"sleeve": sleeve, "weight": _metric(weight, "RATIO"),
                     **{key: _metric(value, "INITIAL_CASH_UNITS", reason) for key, value in amounts.items()}})
    if reason is None:
        _reconcile(math.fsum(row["final_cash"]["value"] for row in rows), final, "combined final cash")
        contribution = math.fsum(row["cash_contribution"]["value"] for row in rows)
        _reconcile(contribution, final - 1, "combined sleeve contributions")
        _reconcile(math.fsum(row["market_pnl"]["value"] - row["commission_total"]["value"] - row["slippage_total"]["value"]
                             for row in rows), contribution, "combined cost attribution")
    return rows


def analyze_intraday_portfolio(left_snapshot: StrategyExperiment, right_snapshot: StrategyExperiment, *,
                               left_cost_index: int = 0, left_candidate_index: int = 0,
                               right_cost_index: int = 0, right_candidate_index: int = 0,
                               weight_a: float = .5, weight_b: float = .5) -> dict:
    """Describe two explicit ordinary DEV selections and fixed capital sleeves.

    Full Q11 basis and all four Q9/Q12 accounts gate every joint derivation.
    Correlation alone may be unavailable while the remaining description is
    valid. Neither input is refitted, executed, rebalanced or modified.
    """
    if any(type(snapshot) is not StrategyExperiment for snapshot in (left_snapshot, right_snapshot)):
        raise ValueError("an immutable StrategyExperiment is required for each side")
    for name, value in (("left_cost_index", left_cost_index), ("left_candidate_index", left_candidate_index),
                        ("right_cost_index", right_cost_index), ("right_candidate_index", right_candidate_index)):
        _integer(value, name, 0)
    allocation = _allocation(weight_a, weight_b)
    left_root = left_snapshot.as_dict()
    right_root = left_root if right_snapshot is left_snapshot else right_snapshot.as_dict()
    left = _selection(left_root, left_cost_index, left_candidate_index)
    right = _selection(right_root, right_cost_index, right_candidate_index)
    failed = [row["key"] for row in _basis(left, right) if not row["matches"]]
    basis = {"matches": not failed, "failed_checks": failed}
    sample = dict(left[0]["sample"]) if not failed else {
        key: [] if type(value) is list else None for key, value in left[0]["sample"].items()}
    sample["total_session_minutes"] = None if failed else _finite(math.fsum(
        (_clock(row["close_time"]) - _clock(row["open_time"])).total_seconds() / 60 for row in left[2]["execution"]["daily"]))
    sample["unavailable_reason"] = "BASIS_MISMATCH" if failed else None
    account_checks, values, checked = [], {}, {}
    for side_name, selected in (("LEFT", left), ("RIGHT", right)):
        for account_name, record, contributions in (("STRATEGY", selected[2], selected[2]["fold_contributions"]),
                                                      ("BENCHMARK", selected[3], None)):
            # Reuse only an identical account/context in this action, retaining
            # a distinct saved-contribution check whenever that input differs.
            key = (id(record["execution"]), id(selected[1]["folds"]), id(contributions))
            if key not in checked:
                checked[key] = _daily_values(record["execution"], selected[1]["folds"], contributions)
            series, reason, detail = checked[key]
            values[side_name, account_name] = series
            account_checks.append({"side": side_name, "account": account_name,
                "status": "AVAILABLE" if reason is None else "UNAVAILABLE", "unavailable_reason": reason, "detail": detail})
    invalid = [row for row in account_checks if row["status"] == "UNAVAILABLE"]
    reason = "BASIS_MISMATCH" if failed else "SOURCE_ACCOUNT_UNAVAILABLE" if invalid else None
    detail = ("Recorded complete basis differs: " + ", ".join(failed) if failed else
              "; ".join(row["side"] + " " + row["account"] + ": " + row["unavailable_reason"] + ": " + row["detail"]
                        for row in invalid) if invalid else None)
    a, b, ab, bb = (selected[index]["execution"] for selected, index in ((left, 2), (right, 2), (left, 3), (right, 3)))
    derived = None
    if reason is None:
        try:
            complementarity = _complementarity(a, b, values["LEFT", "STRATEGY"], values["RIGHT", "STRATEGY"], sample)
            path, daily = _combined_path(a, b, ab, bb, allocation)
            portfolio, benchmark = _account_summary(daily, path), _account_summary(daily, path, benchmark=True)
            attribution = {"portfolio": _attribution(a, b, allocation, daily[-1]["cash_close"]),
                           "benchmark": _attribution(ab, bb, allocation, daily[-1]["benchmark_cash_close"])}
            derived = {"complementarity": complementarity, "portfolio": portfolio, "benchmark": benchmark,
                       "path": path, "daily_returns": daily, "attribution": attribution}
        except (ValueError, ArithmeticError) as exc:
            reason = "NUMERIC_OVERFLOW" if isinstance(exc, ArithmeticError) else "RECORDED_PORTFOLIO_RECONCILIATION_FAILED"
            detail = str(exc)
    if derived is None:
        derived = {"complementarity": _complementarity(a, b, None, None, sample, reason),
                   "portfolio": _account_summary([], [], reason=reason),
                   "benchmark": _account_summary([], [], reason=reason), "path": [], "daily_returns": [],
                   "attribution": {"portfolio": _attribution(a, b, allocation, None, reason),
                                   "benchmark": _attribution(ab, bb, allocation, None, reason)}}
    result = {"version": INTRADAY_PORTFOLIO_VERSION, "status": "SUCCESS", "evidence": "RECORDED_LEDGER_DERIVATION",
              "left": left[0], "right": right[0], "allocation": allocation, "basis": basis, "sample": sample,
              "availability": {"status": "AVAILABLE" if reason is None else "UNAVAILABLE",
                               "unavailable_reason": reason, "detail": detail, "account_checks": account_checks}, **derived}
    result["portfolio_id"] = digest(result)
    return result
