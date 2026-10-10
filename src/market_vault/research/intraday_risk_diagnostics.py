"""Offline risk-path and fold descriptions of immutable intraday records.

The saved continuous account supplies every sample. These descriptions neither
rerun execution nor establish source, replay or statistical validation.
"""

from __future__ import annotations

from datetime import datetime, timezone
import math

from ..backtest.intraday import INTRADAY_COST_VERSION, INTRADAY_EXECUTION_VERSION
from .intraday_data import digest
from .intraday_experiment import INTRADAY_EXPERIMENT_VERSIONS
from .intraday_final_test import INTRADAY_TEST_EXPERIMENT_VERSION
from .intraday_performance import summarize_intraday_execution
from .strategy_experiment import StrategyExperiment


INTRADAY_RISK_DIAGNOSTICS_VERSION = "market-vault-intraday-risk-diagnostics-v1"
ZERO_RETURN_TOLERANCE = 1e-12
QUANTILE_POINTS = (("p05", .05), ("p25", .25), ("p50", .50), ("p75", .75), ("p95", .95))


class _LedgerConsistencyError(ValueError):
    pass


class _FoldConsistencyError(ValueError):
    pass


def _finite(value):
    if not math.isfinite(value):
        raise OverflowError("recorded risk arithmetic produced a nonfinite value")
    return value


def _reconcile(actual, expected, label):
    if not math.isclose(_finite(actual), _finite(expected), rel_tol=1e-10, abs_tol=1e-12):
        raise ValueError("recorded " + label + " does not reconcile with the continuous account")


def _metric(value, unit="COUNT", reason=None):
    return {"value": value, "unit": unit, "unavailable_reason": reason}


def _sign(value):
    return "POSITIVE" if value > ZERO_RETURN_TOLERANCE else "NEGATIVE" if value < -ZERO_RETURN_TOLERANCE else "ZERO"


def _quantile(ordered, probability):
    position = (len(ordered) - 1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    # Convex interpolation avoids overflow from subtracting large endpoints.
    return _finite((1 - weight) * ordered[lower] + weight * ordered[upper])


def _distribution(values, empty_reason):
    ordered = sorted(_finite(value) for value in values)
    signs = [_sign(value) for value in values]
    return {"sample_count": len(ordered), "positive_count": signs.count("POSITIVE"),
            "zero_count": signs.count("ZERO"), "negative_count": signs.count("NEGATIVE"),
            "unit": "RATIO", "unavailable_reason": None if ordered else empty_reason,
            "minimum": ordered[0] if ordered else None, "maximum": ordered[-1] if ordered else None,
            **{key: _quantile(ordered, point) if ordered else None for key, point in QUANTILE_POINTS}}


def _clock(value):
    clock = datetime.fromisoformat(value)
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise ValueError("recorded risk clocks must be timezone-aware")
    return clock.astimezone(timezone.utc)


def _drawdowns(execution):
    daily, ledger = execution["daily"], execution["ledger"]
    if not daily or not ledger:
        raise ValueError("risk diagnostics requires evaluated sessions and complete ledger marks")
    marks_by_day = {}
    for point in ledger:
        marks_by_day.setdefault(point["trading_day"], []).append(point)
    for day in daily:
        marks = marks_by_day.get(day["trading_day"], [])
        if not marks:
            raise ValueError("recorded ledger does not cover an evaluated cash day")
        for point, cash in ((marks[0], day["cash_open"]), (marks[-1], day["cash_close"])):
            if point["quantity"] != 0:
                raise ValueError("recorded session boundary must be flat")
            _reconcile(point["cash"], cash, "session-boundary cash")
            _reconcile(point["equity"], cash, "session-boundary equity")
    initial = execution["metrics"]["initial_cash"]
    if _finite(initial) <= 0:
        raise ValueError("initial cash must be positive")
    peak = {"sequence": -1, "timestamp": daily[0]["open_time"], "equity": initial}
    trough, active, episodes, last_depth = None, False, [], 0.0
    previous_clock = _clock(peak["timestamp"])

    def finish(end, recovered):
        elapsed = (_clock(end["timestamp"]) - _clock(peak["timestamp"])).total_seconds() / 60
        episodes.append({"episode_index": len(episodes), "peak_sequence": peak["sequence"],
            "peak_time": peak["timestamp"], "peak_equity": peak["equity"],
            "trough_sequence": trough["sequence"], "trough_time": trough["timestamp"], "trough_equity": trough["equity"],
            "recovery_sequence": end["sequence"] if recovered else None,
            "recovery_time": end["timestamp"] if recovered else None,
            "recovery_equity": end["equity"] if recovered else None,
            "depth": _finite(1 - trough["equity"] / peak["equity"]),
            "duration_minutes": _finite(elapsed), "recovered": recovered})

    for index, point in enumerate(ledger):
        clock, equity = _clock(point["timestamp"]), _finite(point["equity"])
        if type(point["sequence"]) is not int or point["sequence"] != index or clock < previous_clock or equity < 0:
            raise ValueError("recorded ledger must preserve nonnegative equity and ordered clock/sequence positions")
        previous_clock = clock
        _reconcile(equity, point["cash"] + point["quantity"] * point["mark_price"], "ledger equity")
        if equity >= peak["equity"]:
            if active:
                finish(point, True)
            peak, trough, active, last_depth = point, None, False, 0.0
        else:
            if not active or equity < trough["equity"]:
                trough = point
            active = True
            last_depth = _finite(1 - equity / peak["equity"])
        _reconcile(point["drawdown"], last_depth, "ledger drawdown")
    if active:
        finish(ledger[-1], False)
    maximum = max((row["depth"] for row in episodes), default=0.0)
    _reconcile(maximum, execution["metrics"]["observed_max_drawdown"], "maximum drawdown")
    summary = {"drawdown_episode_count": _metric(len(episodes)),
               "recovered_episode_count": _metric(sum(row["recovered"] for row in episodes)),
               "unrecovered_episode_count": _metric(sum(not row["recovered"] for row in episodes)),
               "maximum_drawdown": _metric(maximum, "RATIO"),
               "longest_drawdown_minutes": _metric(max((row["duration_minutes"] for row in episodes), default=0.0), "MINUTES"),
               "last_drawdown": _metric(last_depth, "RATIO")}
    return episodes, summary


def _concentration(daily):
    result = {}
    for name, positive in (("positive", True), ("negative", False)):
        rows = [{"trading_day": row["trading_day"], "cash_contribution": _finite(row["cash_close"] - row["cash_open"])}
                for row in daily]
        rows = [row for row in rows if row["cash_contribution"] > 0] if positive else [row for row in rows if row["cash_contribution"] < 0]
        # Stable sorting preserves recorded trading-day order for equal amounts.
        rows.sort(key=lambda row: abs(row["cash_contribution"]), reverse=True)
        total = _finite(math.fsum(abs(row["cash_contribution"]) for row in rows))
        one = abs(rows[0]["cash_contribution"]) if rows else 0.0
        three = _finite(math.fsum(abs(row["cash_contribution"]) for row in rows[:3]))
        result[name] = {"day_count": len(rows), "total_absolute_cash": total,
            "top_1_absolute_cash": one, "top_3_absolute_cash": three,
            "top_1_share": _finite(one / total) if total else None,
            "top_3_share": _finite(three / total) if total else None,
            "unavailable_reason": None if total else "NO_POSITIVE_CASH_CONTRIBUTIONS" if positive else "NO_NEGATIVE_CASH_CONTRIBUTIONS",
            "top_days": rows[:3]}
    return result


def _folds(execution, folds):
    if folds is None:
        return {"status": "NOT_APPLICABLE", "unavailable_reason": "NOT_APPLICABLE", "rows": [], "summary": {}}
    daily = execution["daily"]
    by_day = {row["trading_day"]: row for row in daily}
    if not folds or [day for fold in folds for day in fold["validation_days"]] != [row["trading_day"] for row in daily]:
        raise ValueError("recorded folds must partition all evaluated days exactly once in their original order")
    rows = []
    for index, fold in enumerate(folds):
        values = [by_day[day] for day in fold["validation_days"]]
        if not values or type(fold["fold_index"]) is not int or fold["fold_index"] != index:
            raise ValueError("recorded fold indices and day windows must remain complete")
        opened, closed = values[0]["cash_open"], values[-1]["cash_close"]
        contribution = _finite(math.fsum(row["cash_close"] - row["cash_open"] for row in values))
        _reconcile(contribution, closed - opened, "fold cash contribution")
        compound = _finite(closed / opened - 1)
        rows.append({"fold_index": index, "fold_id": fold["fold_id"], "validation_days": list(fold["validation_days"]),
                     "day_count": len(values), "trade_count": sum(row["trade_count"] for row in values),
                     "cash_only_days": sum(row["trade_count"] == 0 for row in values),
                     "cash_open": opened, "cash_close": closed, "compound_return": compound,
                     "cash_contribution": contribution, "return_sign": _sign(compound)})
    _reconcile(math.fsum(row["cash_contribution"] for row in rows),
               execution["metrics"]["final_cash"] - execution["metrics"]["initial_cash"], "all fold contributions")
    returns = sorted(row["compound_return"] for row in rows)
    summary = {"fold_count": _metric(len(rows)),
               **{key: _metric(sum(row["return_sign"] == sign for row in rows)) for key, sign in
                  (("positive_folds", "POSITIVE"), ("zero_folds", "ZERO"), ("negative_folds", "NEGATIVE"))},
               "worst_fold_return": _metric(returns[0], "RATIO"),
               "median_fold_return": _metric(_quantile(returns, .5), "RATIO"),
               "best_fold_return": _metric(returns[-1], "RATIO")}
    return {"status": "AVAILABLE", "unavailable_reason": None, "rows": rows, "summary": summary}


def summarize_intraday_risk_diagnostics(execution: dict, *, folds: list[dict] | None = None) -> dict:
    """Derive a recorded V2 account's risk path; absent folds mean not applicable.

    The input is a V2 result or an execution from the immutable reader. Cash
    reconciliation is descriptive consistency checking, not execution proof.
    """
    summarize_intraday_execution(execution)
    try:
        episodes, summary = _drawdowns(execution)
    except ValueError as exc:
        raise _LedgerConsistencyError(str(exc)) from exc
    try:
        fold_report = _folds(execution, folds)
    except ValueError as exc:
        raise _FoldConsistencyError(str(exc)) from exc
    daily_returns = [_finite(row["cash_close"] / row["cash_open"] - 1) for row in execution["daily"]]
    trade_returns = [_finite(row["cash_after"] / row["cash_before"] - 1) for row in execution["trades"]]
    result = {"version": INTRADAY_RISK_DIAGNOSTICS_VERSION, "execution_id": execution["execution_id"],
              "definitions": {"zero_return_tolerance": ZERO_RETURN_TOLERANCE,
                  "quantile_method": "LINEAR_N_MINUS_ONE", "quantile_points": [value for _, value in QUANTILE_POINTS],
                  "drawdown_basis": "INITIAL_CASH_AND_ORDERED_OPEN_CLOSE_EQUITY",
                  "duration_basis": "UTC_CALENDAR_ELAPSED_MINUTES_INCLUDING_GAPS",
                  "concentration_basis": "ACTUAL_SIGNED_DAILY_CASH_CONTRIBUTIONS"},
              "summary": summary, "drawdown_episodes": episodes,
              "daily_return_distribution": _distribution(daily_returns, "NO_EVALUATED_DAYS"),
              "trade_return_distribution": _distribution(trade_returns, "NO_TRADES"),
              "cash_concentration": _concentration(execution["daily"]), "fold_diagnostics": fold_report}
    result["diagnostics_id"] = digest(result)
    return result


def _available(execution, folds, recorded_contributions=None):
    if execution["version"] != INTRADAY_EXECUTION_VERSION or execution["cost_version"] != INTRADAY_COST_VERSION:
        return {"status": "UNAVAILABLE", "unavailable_reason": "UNSUPPORTED_EXECUTION_OR_COST_VERSION",
                "detail": "Q12 derivation requires the supported execution and fill-cost versions.", "report": None}
    try:
        report = summarize_intraday_risk_diagnostics(execution, folds=folds)
        if recorded_contributions is not None:
            computed = report["fold_diagnostics"]["rows"]
            if len(recorded_contributions) != len(computed):
                raise _FoldConsistencyError("recorded fold contribution count differs")
            for recorded, actual in zip(recorded_contributions, computed, strict=True):
                if any(recorded[key] != actual[key] for key in ("fold_id", "fold_index", "validation_days", "trade_count")):
                    raise _FoldConsistencyError("recorded fold contribution identity or trade count differs")
                try:
                    _reconcile(recorded["cash_contribution"], actual["cash_contribution"], "saved fold contribution")
                except ValueError as exc:
                    raise _FoldConsistencyError(str(exc)) from exc
    except (ValueError, ArithmeticError) as exc:
        reason = ("NUMERIC_OVERFLOW" if isinstance(exc, ArithmeticError)
                  else "RECORDED_LEDGER_RECONCILIATION_FAILED" if isinstance(exc, _LedgerConsistencyError)
                  else "RECORDED_FOLD_RECONCILIATION_FAILED" if isinstance(exc, _FoldConsistencyError)
                  else "RECORDED_CASH_RECONCILIATION_FAILED")
        return {"status": "UNAVAILABLE",
                "unavailable_reason": reason,
                "detail": str(exc), "report": None}
    return {"status": "AVAILABLE", "unavailable_reason": None, "detail": None, "report": report}


def analyze_intraday_risk_diagnostics(snapshot: StrategyExperiment, *, cost_index: int = 0, candidate_index: int = 0) -> dict:
    """Describe one explicit saved Q7/Q8 selection, independently on each side."""
    if type(snapshot) is not StrategyExperiment:
        raise ValueError("an immutable StrategyExperiment is required")
    if any(type(value) is not int or value < 0 for value in (cost_index, candidate_index)):
        raise ValueError("cost_index and candidate_index must be nonnegative integers")
    root = snapshot.as_dict()
    report = root["report"]
    if root["artifact_schema_version"] in INTRADAY_EXPERIMENT_VERSIONS:
        if cost_index >= len(report["groups"]) or candidate_index >= len(report["groups"][cost_index]["results"]):
            raise ValueError("selected cost/candidate index is outside the saved experiment")
        group = report["groups"][cost_index]
        candidate = group["results"][candidate_index]
        candidate_id, folds = candidate["candidate_id"], report["context"]["folds"]
        recorded_contributions = candidate["fold_contributions"]
    elif root["artifact_schema_version"] == INTRADAY_TEST_EXPERIMENT_VERSION:
        if cost_index or candidate_index:
            raise ValueError("TEST contains one frozen result; both indices must be zero")
        group = candidate = report
        candidate_id, folds, recorded_contributions = report["final_test_id"], None, None
    elif root["evaluation_mode"] == "INTRADAY_EXECUTION_SCENARIOS":
        raise ValueError("export an ordinary Q7 scenario before deriving risk diagnostics from a collection")
    else:
        raise ValueError("risk diagnostics requires an intraday development or TEST experiment")
    return {"version": INTRADAY_RISK_DIAGNOSTICS_VERSION, "status": "SUCCESS", "evidence": "RECORDED_LEDGER_DERIVATION",
            "experiment_id": root["experiment_id"], "data_id": root["dataset_id"],
            "evaluation_scope": report["evaluation_scope"], "cost_index": cost_index, "candidate_index": candidate_index,
            "candidate_id": candidate_id, "strategy": candidate["strategy"], "execution_policy": group["execution_policy"],
            "strategy_diagnostics": _available(candidate["execution"], folds, recorded_contributions),
            "benchmark_diagnostics": _available(group["benchmark"]["execution"], folds)}
