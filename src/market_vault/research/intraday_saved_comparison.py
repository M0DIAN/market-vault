"""Offline A/B descriptions of two explicitly selected intraday records.

Equality of recorded evaluation evidence permits neutral DEV differences. It
does not verify source data, reproduce a computation or select a winner.
"""

from __future__ import annotations

import math

from ..backtest.intraday import INTRADAY_COST_VERSION, INTRADAY_EXECUTION_VERSION
from .intraday_experiment import INTRADAY_EXPERIMENT_VERSION
from .intraday_final_test import INTRADAY_TEST_EXPERIMENT_VERSION
from .intraday_performance import (
    BREAKEVEN_RETURN_TOLERANCE, INTRADAY_PERFORMANCE_VERSION, summarize_intraday_execution,
)
from .strategy_experiment import StrategyExperiment


INTRADAY_SAVED_COMPARISON_VERSION = "market-vault-intraday-saved-comparison-v1"
_PERFORMANCE_UNITS = {
    "trade_count": "COUNT", "winning_trades": "COUNT", "losing_trades": "COUNT", "breakeven_trades": "COUNT",
    "win_rate": "RATIO", "mean_trade_return": "RATIO", "profit_factor": "NUMBER", "payoff_ratio": "NUMBER",
    "mean_holding_minutes": "MINUTES", "mean_held_bars": "BARS", "exposure_ratio": "RATIO",
    "evaluated_days": "COUNT", "cash_only_days": "COUNT", "market_pnl": "INITIAL_CASH_UNITS",
    "commission_total": "INITIAL_CASH_UNITS", "slippage_total": "INITIAL_CASH_UNITS", "net_cash_pnl": "INITIAL_CASH_UNITS",
}
_RISK_DEFINITION = ("version", "annualization_factor", "risk_free_rate", "ddof", "zero_volatility_tolerance")
_FOLD_FIELDS = ("training_days", "validation_days", "training_boundary", "training_keys", "purged_keys", "validation_keys")
_BAR_FIELDS = ("sequence", "trading_day", "slot", "timestamp", "phase", "row_version_id", "mark_price")
_DECISION_FIELDS = ("observation_key", "trading_day", "slot", "decision_time")
_MISSING = object()


def _performance(execution):
    if execution["version"] != INTRADAY_EXECUTION_VERSION or execution["cost_version"] != INTRADAY_COST_VERSION:
        return {"status": "UNAVAILABLE", "unavailable_reason": "UNSUPPORTED_EXECUTION_OR_COST_VERSION",
                "detail": "Q9 derivation requires the supported execution and fill-cost versions.", "report": None}
    try:
        report = summarize_intraday_execution(execution)
    except (ValueError, ArithmeticError) as exc:
        return {"status": "UNAVAILABLE",
                "unavailable_reason": "NUMERIC_OVERFLOW" if isinstance(exc, ArithmeticError) else "RECORDED_CASH_RECONCILIATION_FAILED",
                "detail": str(exc), "report": None}
    return {"status": "AVAILABLE", "unavailable_reason": None, "detail": None, "report": report}


def _selected(snapshot, cost_index, candidate_index):
    if type(snapshot) is not StrategyExperiment:
        raise ValueError("an immutable StrategyExperiment is required for each side")
    if any(type(value) is not int or value < 0 for value in (cost_index, candidate_index)):
        raise ValueError("cost_index and candidate_index must be nonnegative integers")
    root = snapshot.as_dict()
    report = root["report"]
    if root["artifact_schema_version"] == INTRADAY_EXPERIMENT_VERSION:
        if cost_index >= len(report["groups"]) or candidate_index >= len(report["groups"][cost_index]["results"]):
            raise ValueError("selected cost/candidate index is outside the saved experiment")
        group = report["groups"][cost_index]
        candidate = group["results"][candidate_index]
        identity = candidate["candidate_id"]
        comparison = root["plan"].get("comparison_plan", root["plan"])
        walk = comparison["walk_forward"]
    elif root["artifact_schema_version"] == INTRADAY_TEST_EXPERIMENT_VERSION:
        if cost_index or candidate_index:
            raise ValueError("TEST contains one frozen result; both indices must be zero")
        group = candidate = report
        identity, walk = report["final_test_id"], None
    elif root["evaluation_mode"] == "INTRADAY_EXECUTION_SCENARIOS":
        raise ValueError("export an ordinary Q7 scenario before comparing a collection")
    else:
        raise ValueError("saved comparison requires an intraday development or TEST experiment")
    context, benchmark = report["context"], group["benchmark"]
    side = {"experiment_id": root["experiment_id"], "data_id": root["dataset_id"],
            "evaluation_mode": root["evaluation_mode"], "evaluation_scope": report["evaluation_scope"],
            "name": root["name"], "notes": root["notes"], "environment": root["environment"],
            "algorithm_versions": root["algorithm_versions"], "cost_index": cost_index, "candidate_index": candidate_index,
            "candidate_id": identity, "feature_fields": context["feature_fields"], "strategy": candidate["strategy"],
            "execution_policy": group["execution_policy"], "candidate_performance": _performance(candidate["execution"]),
            "benchmark_performance": _performance(benchmark["execution"])}
    configuration = {"feature_fields": context["feature_fields"], "strategy": candidate["strategy"],
                     "execution_policy": group["execution_policy"], "walk_forward": walk}
    return side, context, candidate, benchmark, configuration


def _projection(rows, fields):
    return [{key: row[key] for key in fields} for row in rows]


def _basis(left, right):
    a, ac, ar, ab, _ = left
    b, bc, br, bb, _ = right
    checks = []

    def check(key, av, bv, *, matches=None):
        checks.append({"key": key, "left": av, "right": bv, "matches": av == bv if matches is None else matches})

    check("evaluation_scope", a["evaluation_scope"], b["evaluation_scope"])
    check("data_id", a["data_id"], b["data_id"])
    for key in ("symbol", "interval", "target_horizon_bars", "split"):
        check(key, ac[key], bc[key])
    check("evaluated_days", [row["trading_day"] for row in ar["execution"]["daily"]],
          [row["trading_day"] for row in br["execution"]["daily"]])
    # All four records must share the same raw input evidence, including
    # candidate/benchmark consistency within a single saved experiment.
    for key, project in (
        ("session_clocks", lambda e: _projection(e["daily"], ("trading_day", "open_time", "close_time"))),
        ("price_evidence_id", lambda e: e["price_evidence_id"]),
        ("raw_prices", lambda e: _projection(e["ledger"], _BAR_FIELDS)),
    ):
        av = {"strategy": project(ar["execution"]), "benchmark": project(ab["execution"])}
        bv = {"strategy": project(br["execution"]), "benchmark": project(bb["execution"])}
        check(key, av, bv, matches=av["strategy"] == av["benchmark"] == bv["strategy"] == bv["benchmark"])
    check("decision_identity", _projection(ar["predictions"], _DECISION_FIELDS), _projection(br["predictions"], _DECISION_FIELDS))
    check("development_folds", _projection(ac["folds"], _FOLD_FIELDS) if "folds" in ac else None,
          _projection(bc["folds"], _FOLD_FIELDS) if "folds" in bc else None)
    for key in ("training_boundary", "training_keys", "purged_keys", "test_keys"):
        if key in ac or key in bc:
            check("test_context." + key, ac.get(key), bc.get(key))
    check("initial_cash", ar["execution"]["metrics"]["initial_cash"], br["execution"]["metrics"]["initial_cash"])
    check("event_order", ar["execution"]["event_order"], br["execution"]["event_order"])
    for name, aa, ba in (("strategy_risk", ar, br), ("benchmark_risk", ab, bb)):
        check(name, {key: aa["risk"][key] for key in _RISK_DEFINITION}, {key: ba["risk"][key] for key in _RISK_DEFINITION})
    check("benchmark_definition", ab["definition"], bb["definition"])
    for key in ("data", "research", "walk_forward", "execution", "cost", "daily_risk", "benchmark",
                "selection", "final_test", "final_context"):
        if key in a["algorithm_versions"] or key in b["algorithm_versions"]:
            check("algorithm_versions." + key, a["algorithm_versions"].get(key), b["algorithm_versions"].get(key))
    # These maps include unselected candidates. Only a method shared by the
    # two selected strategies is an additional numerical-basis requirement.
    if a["strategy"]["kind"] == b["strategy"]["kind"]:
        key = {"RIDGE": "ridge", "COMPOSITE_RULE": "composite"}.get(a["strategy"]["kind"])
        if key:
            check("algorithm_versions." + key, a["algorithm_versions"][key], b["algorithm_versions"][key])
    definition = {"version": INTRADAY_PERFORMANCE_VERSION, "breakeven_return_tolerance": BREAKEVEN_RETURN_TOLERANCE}
    check("performance_derivation", dict(definition), dict(definition))
    return checks


def _differences(left, right, prefix=""):
    rows = []
    for key in dict.fromkeys([*left, *right]):
        a, b = left.get(key, _MISSING), right.get(key, _MISSING)
        name = prefix + key
        if type(a) is dict and type(b) is dict:
            rows.extend(_differences(a, b, name + "."))
        elif a != b:
            rows.append({"key": name, "left": None if a is _MISSING else a, "right": None if b is _MISSING else b,
                         "left_present": a is not _MISSING, "right_present": b is not _MISSING})
    return rows


def _metric(value, unit, reason=None, evidence="RECORDED"):
    if value is not None:
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            value, reason = None, "NUMERIC_OVERFLOW"
    return {"value": value, "unit": unit, "unavailable_reason": reason if value is None else None, "evidence": evidence}


def _metrics(record, performance, *, prediction=False):
    execution, risk = record["execution"], record["risk"]
    result = {key: _metric(execution["metrics"][key], unit) for key, unit in (
        ("total_return", "RATIO"), ("observed_max_drawdown", "RATIO"),
        ("initial_cash", "INITIAL_CASH_UNITS"), ("final_cash", "INITIAL_CASH_UNITS"))}
    for key, unit in (("mean_daily_return", "RATIO"), ("annualized_volatility", "RATIO"),
                      ("sharpe_ratio", "NUMBER"), ("return_count", "COUNT")):
        result[key] = _metric(risk[key], unit, risk["unavailable_reason"] or "UNAVAILABLE_STATISTIC")
    summary = performance["report"]["summary"] if performance["status"] == "AVAILABLE" else {}
    for key, unit in _PERFORMANCE_UNITS.items():
        item = summary.get(key, {"value": None, "unit": unit, "unavailable_reason": performance["unavailable_reason"]})
        result[key] = _metric(item["value"], item["unit"], item["unavailable_reason"], "RECORDED_LEDGER_DERIVATION")
    if prediction:
        errors = record["prediction_metrics"]
        for key, unit in (("prediction_count", "COUNT"), ("complete_target_count", "COUNT"),
                          ("mae", "RATIO"), ("rmse", "RATIO"), ("r2", "NUMBER")):
            result[key] = _metric(errors[key] if errors is not None else None, unit,
                                  (errors["unavailable_reason"] or "UNAVAILABLE_STATISTIC") if errors is not None else "NOT_APPLICABLE")
    return result


def _metric_rows(left, right, blocked):
    rows = []
    for key, a in left.items():
        b = right[key]
        unit = "PERCENTAGE_POINTS" if a["unit"] == "RATIO" else a["unit"]
        reason, value = blocked, None
        if reason is None:
            if a["value"] is None or b["value"] is None:
                reason = "BOTH_UNAVAILABLE" if a["value"] is None and b["value"] is None else "LEFT_UNAVAILABLE" if a["value"] is None else "RIGHT_UNAVAILABLE"
            else:
                value = (b["value"] - a["value"]) * (100 if a["unit"] == "RATIO" else 1)
        delta = _metric(value, unit, reason, "RECORDED_DIFFERENCE")
        rows.append({"metric": key, "left": a, "right": b, "delta": delta})
    return rows


def compare_saved_intraday_experiments(left_snapshot: StrategyExperiment, right_snapshot: StrategyExperiment, *,
                                      left_cost_index: int = 0, left_candidate_index: int = 0,
                                      right_cost_index: int = 0, right_candidate_index: int = 0) -> dict:
    """Describe two saved selections, with same-basis DEV-only B minus A.

    File validity is supplied by the immutable reader. No source, model or
    execution I/O occurs here, and TEST never receives numerical differences.
    """
    left = _selected(left_snapshot, left_cost_index, left_candidate_index)
    right = _selected(right_snapshot, right_cost_index, right_candidate_index)
    checks = _basis(left, right)
    matches = all(row["matches"] for row in checks)
    test = any(side[0]["evaluation_scope"] == "FROZEN_SINGLE_CANDIDATE_TEST" for side in (left, right))
    reasons = (["TEST_DESCRIPTIVE_ONLY"] if test else []) + ([] if matches else ["BASIS_MISMATCH"])
    blocked = reasons[0] if reasons else None
    return {"version": INTRADAY_SAVED_COMPARISON_VERSION, "status": "SUCCESS", "evidence": "RECORDED_LEDGER_DERIVATION",
            "left": left[0], "right": right[0], "basis_matches": matches, "delta_allowed": not reasons,
            "delta_reasons": reasons, "basis_checks": checks, "configuration_differences": _differences(left[4], right[4]),
            "strategy_metrics": _metric_rows(_metrics(left[2], left[0]["candidate_performance"], prediction=True),
                                             _metrics(right[2], right[0]["candidate_performance"], prediction=True), blocked),
            "benchmark_metrics": _metric_rows(_metrics(left[3], left[0]["benchmark_performance"]),
                                              _metrics(right[3], right[0]["benchmark_performance"]), blocked)}
