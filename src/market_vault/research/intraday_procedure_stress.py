"""Fixed-decision cost/delay stress for an explicit saved outer procedure.

Q35 admits the three recorded accounts, Q12 reconciles them, and Q19 supplies
the minimal price projection and LONG/FLAT transform. Only the unchanged Q6
kernel reexecutes; this is neither fitted-source replay nor a new strategy.
"""

from __future__ import annotations

from copy import deepcopy

from ..backtest.intraday import (
    INTRADAY_COST_VERSION, INTRADAY_EXECUTION_VERSION, IntradayExecutionPolicy, run_intraday_execution,
)
from . import intraday_signal_delay as delay_engine
from .intraday_data import canonical_json, digest
from .intraday_procedure_comparison import _accounts, _member, _procedure
from .intraday_procedure_return_uncertainty import ACCOUNT_ORDER, _account_basis
from .intraday_research import intraday_daily_risk
from .intraday_return_uncertainty import _finite, _mean, _sample_coverage
from .intraday_risk_diagnostics import _available, _metric
from .strategy_experiment import StrategyExperiment


INTRADAY_PROCEDURE_STRESS_VERSION = "market-vault-intraday-procedure-stress-v1"
ADDITIONAL_SLIPPAGE_BPS = (0, 5, 10)
SIGNAL_DELAY_BARS = delay_engine.SIGNAL_DELAY_BARS


def _policy_records(accounts, additional_slippage):
    return {name: {**record["execution"]["policy"],
                   "slippage_bps": record["execution"]["policy"]["slippage_bps"] + additional_slippage}
            for name, record in accounts.items()}


def _derived_account(execution):
    risk = intraday_daily_risk(execution)
    canonical_json(risk)
    return {"execution": execution, "risk": risk, "metrics": delay_engine._metrics(execution, risk)}


def _daily_summary(sides, context, reason=None, detail=None):
    folds = {day: fold["fold_id"] for fold in context["folds"] for day in fold["validation_days"]}
    values = {} if reason else {name: [_finite(row["cash_close"] / row["cash_open"] - 1)
                                     for row in sides[name]["execution"]["daily"]] for name in ACCOUNT_ORDER}
    daily = []
    for index, day in enumerate(context["evaluated_days"]):
        returns = {name: None if reason else values[name][index] for name in ACCOUNT_ORDER}
        excess = None if reason else _finite(returns["procedure"] - returns["fixed_reference"])
        daily.append({"trading_day": day, "fold_id": folds[day], "returns": returns,
                      "procedure_minus_fixed_reference": excess})
    increment = {"mean": None if reason else _mean([row["procedure_minus_fixed_reference"] for row in daily]),
                 "unit": "RATIO", "sample_count": len(daily), "unavailable_reason": reason, "detail": detail}
    return daily, increment


def analyze_intraday_procedure_stress(snapshot: StrategyExperiment) -> dict:
    """Run the declared nine-cell grid with no fitting, selection or Q5 access.

    A source study must be AVAILABLE. Once admitted, all nine cells remain in
    the result, even if a complete baseline or one whole stress cell fails.
    """
    selected = _procedure(snapshot)
    root, context = selected["root"], selected["context"]
    report = root["report"]
    if report["status"] != "AVAILABLE":
        raise ValueError("SOURCE_STUDY_UNAVAILABLE: procedure stress requires an AVAILABLE Q25/Q31/Q36 study")
    records = _accounts(selected)
    recorded_sessions = {name: delay_engine._recorded_sessions(record["execution"])
                         for name, record in records.items()}
    sessions = recorded_sessions["fixed_reference"]
    basis = _account_basis(selected, records)
    admission = []
    for name, record in records.items():
        check = _available(record["execution"], context["folds"], record.get("fold_contributions"))
        admission.append({"account": name, "execution_id": record["execution"]["execution_id"],
                          **{key: check[key] for key in ("status", "unavailable_reason", "detail")}})
    failed = [row for row in admission if row["status"] != "AVAILABLE"]
    reason = "BASIS_MISMATCH" if not basis["matches"] else "SOURCE_ACCOUNT_UNAVAILABLE" if failed else None
    detail = ("Recorded three-account basis differs: " + ", ".join(basis["failed_checks"]) if not basis["matches"] else
              "; ".join(f"{row['account']}: {row['unavailable_reason']}: {row['detail']}" for row in failed) if failed else None)
    projection = {"status": "UNAVAILABLE", "unavailable_reason": reason, "detail": detail,
        "source_price_evidence_ids": {name: record["execution"]["price_evidence_id"] for name, record in records.items()},
        "reconstructed_price_evidence_id": None, "session_fields": list(delay_engine._SESSION_FIELDS),
        "price_fields": list(delay_engine._PRICE_FIELDS)}
    checks = [delay_engine._baseline_check(name, record["execution"]) for name, record in records.items()]
    prices, zero_sides, zero_policies = None, {}, None
    if reason is None:
        try:
            prices = delay_engine._reconstructed_prices(records["fixed_reference"]["execution"])
            # Validate every role's original policy before the first baseline
            # call; the zero helper independently reconstructs that same policy.
            zero_policies = {name: IntradayExecutionPolicy(**policy)
                             for name, policy in _policy_records(records, 0).items()}
        except (ValueError, ArithmeticError) as exc:
            reason, detail = "RECORDED_PRICE_GRID_UNAVAILABLE", str(exc)
        if reason is None:
            executions = {name: delay_engine._zero_delay_execution(record["execution"], sessions, prices, check)
                          for (name, record), check in zip(records.items(), checks, strict=True)}
            projection["reconstructed_price_evidence_id"] = checks[0]["reconstructed_price_evidence_id"]
            if projection["reconstructed_price_evidence_id"] is not None:
                projection.update(status="AVAILABLE", unavailable_reason=None, detail=None)
            failed = [check for check in checks if check["status"] != "AVAILABLE"]
            if failed:
                reason, detail = "ZERO_DELAY_REPRODUCTION_FAILED", "; ".join(
                    f"{row['account']}: {row['detail']}" for row in failed)
            else:
                try:
                    zero_sides = {name: _derived_account(execution) for name, execution in executions.items()}
                    _daily_summary(zero_sides, context)
                except (ValueError, ArithmeticError) as exc:
                    reason, detail = "ZERO_STRESS_DERIVATION_FAILED", str(exc)
    if projection["status"] != "AVAILABLE":
        projection.update(unavailable_reason=reason, detail=detail)
    for check in checks:
        if check["status"] == "NOT_RUN":
            check.update(unavailable_reason=reason, detail=detail)
    baseline = {"status": "AVAILABLE" if reason is None else "UNAVAILABLE", "unavailable_reason": reason,
                "detail": detail, "excluded_identity_fields": list(delay_engine._PROJECTION_ID_FIELDS), "accounts": checks}
    # Signal provenance is a property of each recorded stream and delay, not
    # the slippage axis. Retain it even when the complete baseline is blocked.
    streams = {delay: {name: delay_engine._delayed_decisions(record["execution"], recorded_sessions[name], delay)
                       for name, record in records.items()} for delay in SIGNAL_DELAY_BARS}
    scenarios, zero_metrics, zero_increment = [], {}, None
    for additional_slippage in ADDITIONAL_SLIPPAGE_BPS:
        for delay in SIGNAL_DELAY_BARS:
            is_zero = additional_slippage == delay == 0
            policies = _policy_records(records, additional_slippage)
            sides, failure, explanation = {}, reason, detail
            if failure is None:
                try:
                    # All policies must be legal before executing any role in
                    # this cell. Invalid added slippage is never clipped.
                    executable_policies = zero_policies if is_zero else {
                        name: IntradayExecutionPolicy(**policy) for name, policy in policies.items()}
                except (ValueError, ArithmeticError) as exc:
                    failure, explanation = "SCENARIO_POLICY_UNAVAILABLE", str(exc)
            if failure is None:
                try:
                    for name, record in records.items():
                        sides[name] = zero_sides[name] if is_zero else _derived_account(run_intraday_execution(
                            sessions=sessions, prices=prices, decisions=streams[delay][name][0],
                            interval=record["execution"]["interval"], policy=executable_policies[name]))
                    daily, increment = _daily_summary(sides, context)
                except (ValueError, ArithmeticError) as exc:
                    failure = "NUMERIC_OVERFLOW" if isinstance(exc, ArithmeticError) else "SCENARIO_REEXECUTION_FAILED"
                    explanation = f"{name}: {exc}"
            if failure is not None:
                sides = {name: {"execution": None, "risk": None, "metrics": delay_engine._metrics(None, None, failure)}
                         for name in ACCOUNT_ORDER}
                daily, increment = _daily_summary(sides, context, failure, explanation)
            for name, side in sides.items():
                if is_zero:
                    zero_metrics[name] = side["metrics"]
                side.update(execution_policy=policies[name], signals=streams[delay][name][1],
                            delta_from_zero=delay_engine._changes(side["metrics"], zero_metrics[name], failure))
            metric = _metric(increment["mean"], "RATIO", increment["unavailable_reason"])
            if is_zero:
                zero_increment = metric
            increment["delta_from_zero"] = delay_engine._changes({"mean": metric}, {"mean": zero_increment}, failure)["mean"]
            scenarios.append({"scenario_index": len(scenarios), "additional_slippage_bps": additional_slippage,
                              "delay_bars": delay, "status": "AVAILABLE" if failure is None else "UNAVAILABLE",
                              "unavailable_reason": failure, "detail": explanation, "accounts": sides,
                              "daily": daily, "increment": increment})
    available_count = sum(row["status"] == "AVAILABLE" for row in scenarios)
    status = "AVAILABLE" if available_count == len(scenarios) else "PARTIAL" if available_count else "UNAVAILABLE"
    sample = {**_sample_coverage(context), "split": deepcopy(context["split"]), "sessions": list(sessions),
        "schedule_evidence": "RECORDED_COMMON_SESSION_GRID", "prediction_count": len(records["procedure"]["predictions"]),
        "unevaluated_development_day_count": len(context["unevaluated_development_days"]),
        "unevaluated_development_days": deepcopy(context["unevaluated_development_days"]),
        "folds": [{key: deepcopy(fold[key]) for key in ("fold_id", "fold_index", "training_boundary", "validation_days")}
                  for fold in context["folds"]],
        "account_counts": {name: {"evaluated_day_count": len(record["execution"]["daily"]),
                                  "trade_count": record["execution"]["metrics"]["trade_count"],
                                  "cash_only_day_count": sum(row["trade_count"] == 0 for row in record["execution"]["daily"])}
                           for name, record in records.items()}}
    unavailable = [row for row in scenarios if row["status"] != "AVAILABLE"]
    result = {"version": INTRADAY_PROCEDURE_STRESS_VERSION, "status": status,
        "evaluation_scope": "DEVELOPMENT_OUTER_PROCEDURE_EXECUTION_STRESS_ONLY",
        "name": root["name"], "experiment_id": root["experiment_id"], "data_id": root["dataset_id"],
        "ordinary_source_id": selected["source"]["experiment_id"], "source_kind": selected["kind"],
        "source_schema_version": root["artifact_schema_version"], "algorithm_versions": deepcopy(root["algorithm_versions"]),
        "selection_id": report[selected["report_key"]], "source_selection": deepcopy(selected["selection"]),
        "source_evaluation_scope": report["evaluation_scope"], "context": deepcopy(context),
        "member": _member(selected, "procedure"), "accounts": deepcopy(records),
        "evidence": {"scope": "RECORDED_PRICE_GRID_REEXECUTION", "source_reconstructed": False,
                     "models_refitted": False, "decisions_reselected": False, "execution_replayed": True},
        "method": {"additional_slippage_bps": list(ADDITIONAL_SLIPPAGE_BPS), "delay_bars": list(SIGNAL_DELAY_BARS),
            "scenario_order": "ADDITIONAL_SLIPPAGE_OUTER_DELAY_INNER", "account_order": list(ACCOUNT_ORDER),
            "execution_engine": INTRADAY_EXECUTION_VERSION, "cost_engine": INTRADAY_COST_VERSION,
            "signal_transform": delay_engine.INTRADAY_SIGNAL_DELAY_VERSION,
            "time_basis": "FULL_PLANNED_SESSION_BAR_GRID", "signal_policy": "DELAY_BOTH_LONG_AND_FLAT",
            "benchmark_policy": "DELAY_ORIGINAL_BENCHMARK_DECISIONS_WITH_ORIGINAL_FULL_SESSION_MAX_HOLD",
            "slippage_policy": "ADDITIVE_BPS_PER_FILL_WITHOUT_CLIPPING",
            "risk_controls": "UNCHANGED_COMMISSION_ENTRY_STOP_MAX_HOLD_AND_EOD", "cross_session_signals": False,
            "baseline_equality": "COMPLETE_CANONICAL_EXECUTION_EXCEPT_PROJECTION_IDENTITIES",
            "daily_return": "CASH_CLOSE_OVER_CASH_OPEN_MINUS_ONE", "increment": "ARITHMETIC_MEAN_PROCEDURE_MINUS_FIXED_PER_DAY",
            "change_units": "RATIO_DELTAS_ALREADY_IN_PERCENTAGE_POINTS", "resampling": "NONE",
            "scope": "OUTER_DEV_ONLY_NO_INNER_FINAL_DEV_OR_TEST_ACCOUNTS"},
        "sample": sample, "basis": basis, "projection": projection, "baseline": baseline,
        "availability": {"status": baseline["status"], "unavailable_reason": reason, "detail": detail, "accounts": admission},
        "scenario_counts": {"declared": len(scenarios), "available": available_count, "unavailable": len(unavailable)},
        "scenarios": scenarios, "unavailable_reason": reason or ("SCENARIOS_UNAVAILABLE" if unavailable else None),
        "detail": detail or ("; ".join(f"cell {row['scenario_index']}: {row['unavailable_reason']}: {row['detail']}"
                                      for row in unavailable) if unavailable else None),
        "warnings": ["RECORDED_PRICES_AND_SIGNALS_NOT_CANONICAL_OR_FITTED_SOURCE_REPLAY",
                     "DECLARED_SLIPPAGE_INCREMENTS_NOT_MARKET_IMPACT_ESTIMATES", "FIXED_BAR_DELAYS_NOT_MEASURED_LATENCY",
                     "DELAY_EFFECT_NEED_NOT_BE_MONOTONIC", "DAILY_EXCESS_NOT_AN_INVESTABLE_ACCOUNT",
                     "NO_REFIT_RESELECTION_BOOTSTRAP_FREEZE_TEST_OR_PROMOTION"]}
    result["stress_id"] = digest(result)
    return result
