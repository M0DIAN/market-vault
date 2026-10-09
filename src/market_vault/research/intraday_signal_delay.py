"""Whole-bar signal-delay stress on a saved DEV price and decision record.

The unchanged numerical execution kernel consumes delayed LONG/FLAT signals.
This does not establish Canonical authority, reproduce fitted predictions, or
create an ordinary Q7 experiment eligible for Freeze/TEST.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from ..backtest.intraday import IntradayExecutionPolicy, run_intraday_execution
from .intraday_data import canonical_json, digest
from .intraday_experiment import INTRADAY_EXPERIMENT_VERSION
from .intraday_research import intraday_daily_risk
from .intraday_return_uncertainty import _finite, _integer, _sample_coverage, _self_basis
from .intraday_risk_diagnostics import _available, _metric
from .strategy_experiment import StrategyExperiment


INTRADAY_SIGNAL_DELAY_VERSION = "market-vault-intraday-signal-delay-v1"
SIGNAL_DELAY_BARS = (0, 1, 2)
_PROJECTION_ID_FIELDS = ("price_evidence_id", "execution_id")
_SESSION_FIELDS = ("trading_day", "open_time", "close_time", "bar_count")
_PRICE_FIELDS = ("trading_day", "slot", "event_time", "available_at", "row_version_id", "open", "close")
_METRIC_UNITS = {
    "final_cash": "INITIAL_CASH_UNITS", "total_return": "RATIO", "observed_max_drawdown": "RATIO",
    "trade_count": "COUNT", "commission_total": "INITIAL_CASH_UNITS", "slippage_total": "INITIAL_CASH_UNITS",
    "mean_daily_return": "RATIO", "annualized_volatility": "RATIO", "sharpe_ratio": "NUMBER", "return_count": "COUNT",
}


def _recorded_sessions(execution):
    counts = Counter(point["trading_day"] for point in execution["ledger"] if point["phase"] == "OPEN")
    return tuple({**{key: row[key] for key in ("trading_day", "open_time", "close_time")},
                  "bar_count": counts[row["trading_day"]]} for row in execution["daily"])


def _reconstructed_prices(execution):
    """Recover only the price projection present in the complete saved ledger.

    Q5 has additional session metadata that is not recoverable here. The kernel
    must compute its own identity for these minimal inputs, never inherit the
    source price-evidence identity merely because numerical prices agree.
    """
    prices = []
    ledger = execution["ledger"]
    for index in range(0, len(ledger), 2):
        opened, closed = ledger[index:index + 2]
        if (opened["phase"] != "OPEN" or closed["phase"] != "CLOSE"
                or any(opened[key] != closed[key] for key in ("trading_day", "slot", "row_version_id"))):
            raise ValueError("each saved OPEN/CLOSE pair must describe the same price row and slot")
        prices.append({"trading_day": opened["trading_day"], "slot": opened["slot"],
                       "event_time": opened["timestamp"], "available_at": closed["timestamp"],
                       "row_version_id": opened["row_version_id"],
                       "open": opened["mark_price"], "close": closed["mark_price"]})
    return tuple(prices)


def _delayed_decisions(execution, sessions, delay):
    """Shift every signal by planned slots, with no remembered/cross-day target."""
    counts = {row["trading_day"]: row["bar_count"] for row in sessions}
    step = timedelta(minutes=int(execution["interval"][:-1]))
    decisions, provenance = [], []
    for original in execution["decisions"]:
        arrival_slot = original["slot"] + delay
        arrival_time = (datetime.fromisoformat(original["decision_time"]) + delay * step).isoformat()
        count = counts[original["trading_day"]]
        status = ("OUTSIDE_SESSION" if arrival_slot >= count else
                  "NO_NEXT_OPEN" if arrival_slot == count - 1 else "FORWARDED")
        passed = arrival_slot < count
        key = None
        if passed:
            decision = dict(original)
            if delay:
                key = digest({"method": INTRADAY_SIGNAL_DELAY_VERSION,
                              "source_observation_key": original["observation_key"],
                              "delay_bars": delay, "arrival_time": arrival_time})
                decision.update(observation_key=key, slot=arrival_slot, decision_time=arrival_time)
            else:
                key = original["observation_key"]
            decisions.append(decision)
        provenance.append({"source_observation_key": original["observation_key"],
            "source_trading_day": original["trading_day"], "source_slot": original["slot"],
            "source_time": original["decision_time"], "source_target": original["target"],
            "source_score": original["score"], "delay_bars": delay, "arrival_slot": arrival_slot,
            "arrival_time": arrival_time, "derived_decision_key": key, "status": status,
            "passed_to_kernel": passed})
    statuses = Counter(row["status"] for row in provenance)
    return tuple(decisions), {"source_count": len(provenance), "passed_to_kernel_count": len(decisions),
        "consumable_count": statuses["FORWARDED"], "no_next_open_count": statuses["NO_NEXT_OPEN"],
        "outside_session_count": statuses["OUTSIDE_SESSION"], "provenance": provenance}


def _baseline_check(account, source):
    return {"account": account, "status": "NOT_RUN", "matches": None, "unavailable_reason": None,
            "detail": None, "source_execution_id": source["execution_id"],
            "source_price_evidence_id": source["price_evidence_id"], "reexecuted_execution_id": None,
            "reconstructed_price_evidence_id": None, "differing_fields": []}


def _zero_delay_execution(source, sessions, prices, check):
    try:
        execution = run_intraday_execution(sessions=sessions, prices=prices, decisions=tuple(source["decisions"]),
                                          interval=source["interval"], policy=IntradayExecutionPolicy(**source["policy"]))
        check.update(reexecuted_execution_id=execution["execution_id"],
                     reconstructed_price_evidence_id=execution["price_evidence_id"])
        before = {key: value for key, value in source.items() if key not in _PROJECTION_ID_FIELDS}
        after = {key: value for key, value in execution.items() if key not in _PROJECTION_ID_FIELDS}
        check["matches"] = canonical_json(before) == canonical_json(after)
        if not check["matches"]:
            check["differing_fields"] = [key for key in dict.fromkeys([*before, *after])
                if key not in before or key not in after or canonical_json(before[key]) != canonical_json(after[key])]
            check.update(status="UNAVAILABLE", unavailable_reason="ZERO_DELAY_REPRODUCTION_FAILED",
                         detail="Complete zero-delay execution differs in: " + ", ".join(check["differing_fields"]))
            return None
    except (ValueError, ArithmeticError) as exc:
        check.update(status="UNAVAILABLE", unavailable_reason="ZERO_DELAY_REEXECUTION_FAILED", detail=str(exc))
        return None
    check["status"] = "AVAILABLE"
    return execution


def _metrics(execution, risk, reason=None):
    result = {}
    for key, unit in _METRIC_UNITS.items():
        value = None if execution is None else (execution["metrics"][key] if key in execution["metrics"] else risk[key])
        missing = reason if execution is None else risk["unavailable_reason"] if value is None else None
        result[key] = _metric(None if value is None else _finite(value), unit, missing)
    return result


def _changes(metrics, baseline, reason=None):
    result = {}
    for key, value in metrics.items():
        original = baseline[key]
        unit = "PERCENTAGE_POINTS" if value["unit"] == "RATIO" else value["unit"]
        unavailable = reason or ("BOTH_UNAVAILABLE" if value["value"] is original["value"] is None else
                                "SCENARIO_UNAVAILABLE" if value["value"] is None else
                                "BASELINE_UNAVAILABLE" if original["value"] is None else None)
        try:
            delta = None if unavailable else _finite((value["value"] - original["value"]) *
                                                     (100 if value["unit"] == "RATIO" else 1))
        except ArithmeticError:
            delta, unavailable = None, "NUMERIC_OVERFLOW"
        result[key] = _metric(delta, unit, unavailable)
    return result


def analyze_intraday_signal_delay(snapshot: StrategyExperiment, *, cost_index: int = 0,
                                  candidate_index: int = 0) -> dict:
    """Re-execute one saved DEV candidate and its benchmark at 0/1/2-bar delays.

    Every source account and the common raw-price basis must be admitted, and
    both complete zero-delay executions must reproduce before stress paths are
    returned. Actual evaluated gaps remain visible and are never filled.
    """
    if type(snapshot) is not StrategyExperiment:
        raise ValueError("an immutable StrategyExperiment is required")
    _integer(cost_index, "cost_index", 0)
    _integer(candidate_index, "candidate_index", 0)
    root = snapshot.as_dict()
    if (root["artifact_schema_version"] != INTRADAY_EXPERIMENT_VERSION
            or root["evaluation_mode"] not in ("INTRADAY_COMPARISON", "INTRADAY_DIAGNOSTICS")
            or root["report"]["evaluation_scope"] != "DEVELOPMENT_WALK_FORWARD_ONLY"):
        raise ValueError("signal delay requires an ordinary saved Q7 DEV comparison or diagnostics experiment")
    report = root["report"]
    if cost_index >= len(report["groups"]) or candidate_index >= len(report["groups"][cost_index]["results"]):
        raise ValueError("selected cost/candidate index is outside the saved experiment")
    context, group = report["context"], report["groups"][cost_index]
    candidate, benchmark = group["results"][candidate_index], group["benchmark"]
    records = {"strategy": candidate, "benchmark": benchmark}
    sessions = _recorded_sessions(candidate["execution"])
    sample = {**_sample_coverage(context), "split": context["split"], "sessions": list(sessions),
        "schedule_evidence": "RECORDED_STRATEGY_SESSION_GRID", "prediction_count": len(candidate["predictions"]),
        "unevaluated_development_day_count": len(context["unevaluated_development_days"]),
        "unevaluated_development_days": context["unevaluated_development_days"],
        "folds": [{key: fold[key] for key in ("fold_id", "fold_index", "training_boundary", "validation_days")}
                  for fold in context["folds"]]}
    basis = _self_basis(root, context, candidate, benchmark)
    accounts = []
    for name, record in records.items():
        availability = _available(record["execution"], context["folds"],
                                  candidate["fold_contributions"] if name == "strategy" else None)
        accounts.append({"account": name.upper(), "execution_id": record["execution"]["execution_id"],
                         **{key: availability[key] for key in ("status", "unavailable_reason", "detail")}})
    failed_accounts = [row for row in accounts if row["status"] != "AVAILABLE"]
    reason = "BASIS_MISMATCH" if not basis["matches"] else "SOURCE_ACCOUNT_UNAVAILABLE" if failed_accounts else None
    detail = ("Recorded candidate/benchmark basis differs: " + ", ".join(basis["failed_checks"]) if not basis["matches"] else
              "; ".join(f"{row['account']}: {row['unavailable_reason']}: {row['detail']}" for row in failed_accounts) if failed_accounts else None)
    projection = {"status": "UNAVAILABLE", "unavailable_reason": reason, "detail": detail,
        "source_strategy_price_evidence_id": candidate["execution"]["price_evidence_id"],
        "source_benchmark_price_evidence_id": benchmark["execution"]["price_evidence_id"],
        "reconstructed_price_evidence_id": None, "session_fields": list(_SESSION_FIELDS), "price_fields": list(_PRICE_FIELDS)}
    checks = [_baseline_check(name.upper(), record["execution"]) for name, record in records.items()]
    baseline_executions, prices = {}, None
    if reason is None:
        try:
            prices = _reconstructed_prices(candidate["execution"])
        except (ValueError, ArithmeticError) as exc:
            reason, detail = "RECORDED_PRICE_GRID_UNAVAILABLE", str(exc)
        if reason is None:
            for (name, record), check in zip(records.items(), checks, strict=True):
                baseline_executions[name] = _zero_delay_execution(record["execution"], sessions, prices, check)
            projection["reconstructed_price_evidence_id"] = checks[0]["reconstructed_price_evidence_id"]
            if projection["reconstructed_price_evidence_id"] is not None:
                projection.update(status="AVAILABLE", unavailable_reason=None, detail=None)
            failed = [check for check in checks if check["status"] != "AVAILABLE"]
            if failed:
                reason, detail = "ZERO_DELAY_REPRODUCTION_FAILED", "; ".join(f"{row['account']}: {row['detail']}" for row in failed)
    if projection["status"] != "AVAILABLE":
        projection.update(unavailable_reason=reason, detail=detail)
    for check in checks:
        if check["status"] == "NOT_RUN":
            check.update(unavailable_reason=reason, detail=detail)
    baseline = {"status": "AVAILABLE" if reason is None else "UNAVAILABLE", "unavailable_reason": reason,
                "detail": detail, "excluded_identity_fields": list(_PROJECTION_ID_FIELDS), "accounts": checks}
    scenarios, baseline_metrics = [], {}
    for delay in SIGNAL_DELAY_BARS:
        sides, failure, explanation = {}, reason, detail
        streams = {name: _delayed_decisions(record["execution"], sessions, delay) for name, record in records.items()}
        if failure is None:
            try:
                for name, record in records.items():
                    execution = baseline_executions[name] if delay == 0 else run_intraday_execution(
                        sessions=sessions, prices=prices, decisions=streams[name][0], interval=record["execution"]["interval"],
                        policy=IntradayExecutionPolicy(**record["execution"]["policy"]))
                    risk = intraday_daily_risk(execution)
                    metrics = _metrics(execution, risk)
                    # Validate the complete derived risk too, not just metrics
                    # currently chosen for display.
                    canonical_json(risk)
                    sides[name] = {"execution": execution, "risk": risk, "metrics": metrics}
            except (ValueError, ArithmeticError) as exc:
                failure = "NUMERIC_OVERFLOW" if isinstance(exc, ArithmeticError) else "SCENARIO_REEXECUTION_FAILED"
                explanation = str(exc)
        if failure is not None:
            sides = {name: {"execution": None, "risk": None, "metrics": _metrics(None, None, failure)} for name in records}
        for name, side in sides.items():
            if delay == 0:
                baseline_metrics[name] = side["metrics"]
            side["delta_from_zero"] = _changes(side["metrics"], baseline_metrics[name], failure)
            side["signals"] = streams[name][1]
        scenarios.append({"delay_bars": delay, "status": "AVAILABLE" if failure is None else "UNAVAILABLE",
                          "unavailable_reason": failure, "detail": explanation, **sides})
    result = {"version": INTRADAY_SIGNAL_DELAY_VERSION, "status": "SUCCESS", "evidence": "RECORDED_PRICE_GRID_REEXECUTION",
        "name": root["name"], "experiment_id": root["experiment_id"], "data_id": root["dataset_id"],
        "research_id": report["research_id"], "context_id": context["context_id"], "evaluation_scope": report["evaluation_scope"],
        "cost_index": cost_index, "candidate_index": candidate_index, "candidate_id": candidate["candidate_id"],
        "strategy": candidate["strategy"], "axis_values": candidate["axis_values"], "feature_fields": context["feature_fields"],
        "algorithm_versions": root["algorithm_versions"], "execution_policy": group["execution_policy"],
        "benchmark_execution_policy": benchmark["execution"]["policy"],
        "strategy_execution_id": candidate["execution"]["execution_id"], "benchmark_execution_id": benchmark["execution"]["execution_id"],
        "method": {"delay_bars": list(SIGNAL_DELAY_BARS), "time_basis": "FULL_PLANNED_SESSION_BAR_GRID",
            "signal_policy": "DELAY_BOTH_LONG_AND_FLAT", "benchmark_policy": "DELAY_ORIGINAL_BENCHMARK_DECISIONS",
            "risk_controls": "UNCHANGED_ENTRY_STOP_MAX_HOLD_AND_EOD", "cross_session_signals": False,
            "baseline_equality": "COMPLETE_CANONICAL_EXECUTION_EXCEPT_PROJECTION_IDENTITIES"},
        "sample": sample, "basis": basis, "projection": projection, "baseline": baseline,
        "availability": {"status": "AVAILABLE" if reason is None else "UNAVAILABLE", "unavailable_reason": reason,
                         "detail": detail, "accounts": accounts}, "scenarios": scenarios,
        "warnings": ["RECORDED_PRICES_AND_SIGNALS_NOT_CANONICAL_OR_Q7_REPLAY",
            "FIXED_BAR_DELAYS_NOT_MEASURED_LATENCY", "DELAY_EFFECT_NEED_NOT_BE_MONOTONIC",
            "NO_AUTOMATIC_DELAY_SELECTION_OR_FREEZE"]}
    result["signal_delay_id"] = digest(result)
    return result
