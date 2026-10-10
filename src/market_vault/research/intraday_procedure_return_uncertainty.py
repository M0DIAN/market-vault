"""Recorded outer-return increments of saved Q25/Q31 selection procedures.

All five daily series share stationary-bootstrap indices. These conditional
path intervals do not resample fitting/selection or correct research search.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from . import intraday_inner_selection as inner
from . import intraday_return_uncertainty as uncertainty
from .intraday_data import digest
from .intraday_ml_diagnostics import _saved_ml_source
from .intraday_research import BENCHMARK_DEFINITION
from .intraday_saved_comparison import _BAR_FIELDS, _DECISION_FIELDS, _RISK_DEFINITION, _projection
from .strategy_experiment import StrategyExperiment


INTRADAY_PROCEDURE_RETURN_UNCERTAINTY_VERSION = "market-vault-intraday-procedure-return-uncertainty-v1"
ACCOUNT_ORDER = ("procedure", "fixed_reference", "benchmark")
SERIES_ORDER = (*ACCOUNT_ORDER, "procedure_minus_fixed_reference", "procedure_minus_benchmark")


def _benchmark_support(predictions, windows):
    expected = []
    for window in windows:
        first = datetime.fromisoformat(window["earliest_entry_time"])
        stop = datetime.fromisoformat(window["stop_new_time"])
        for row in predictions:
            if (row["trading_day"] == window["trading_day"]
                    and first <= datetime.fromisoformat(row["decision_time"]) < stop
                    and row["slot"] + 1 < window["forced_flat_slot"]):
                expected.append({**{key: row[key] for key in _DECISION_FIELDS}, "target": "LONG"})
                break
    return expected


def _account_basis(selected, accounts):
    """Check three actual roles without pretending the procedure is fixed."""
    root, source, context = selected["root"], selected["source"], selected["context"]
    reference, benchmark = accounts["fixed_reference"], accounts["benchmark"]
    executions = {name: record["execution"] for name, record in accounts.items()}
    fixed = executions["fixed_reference"]
    checks = []

    def check(key, expected, recorded, *, compact=False):
        def evidence(value):
            return {"sha256": digest(value), "count": len(value)} if compact else deepcopy(value)
        checks.append({"key": key, "matches": all(value == expected for value in recorded.values()),
                       "expected": evidence(expected), "recorded": {name: evidence(value) for name, value in recorded.items()}})

    check("original_reference", selected["selection"],
          {"plan": root["plan"]["selection"], "study": root["report"]["fixed_reference"]})
    check("source_data", source["dataset_id"], {"study": root["dataset_id"], "context": context["data_id"]})
    check("source_scope", "DEVELOPMENT_WALK_FORWARD_ONLY", {"source": source["report"]["evaluation_scope"]})
    check("source_algorithms", source["algorithm_versions"],
          {"procedure": {key: root["algorithm_versions"].get(key) for key in source["algorithm_versions"]}})
    check("original_benchmark", selected["group"]["benchmark"], {"study": root["report"]["benchmark"]}, compact=True)
    check("outer_fold_identity", [row["fold_id"] for row in context["folds"]],
          {"procedure": [row["fold_id"] for row in root["report"]["outer_folds"]]}, compact=True)
    check("evaluated_days", context["evaluated_days"],
          {name: [row["trading_day"] for row in execution["daily"]] for name, execution in executions.items()}, compact=True)
    for key, project in (
        ("session_clocks", lambda e: _projection(e["daily"], ("trading_day", "open_time", "close_time"))),
        ("raw_prices", lambda e: _projection(e["ledger"], _BAR_FIELDS)),
        ("execution_windows", lambda e: e["windows"]),
    ):
        check(key, project(fixed), {name: project(execution) for name, execution in executions.items()}, compact=True)
    for key, expected in (("price_evidence_id", fixed["price_evidence_id"]), ("interval", context["interval"]),
                          ("version", source["algorithm_versions"]["execution"]),
                          ("cost_version", source["algorithm_versions"]["cost"]),
                          ("event_order", "BAR_CLOSE_THEN_DECISION_THEN_NEXT_PLANNED_OPEN")):
        check(key, expected, {name: execution[key] for name, execution in executions.items()})
    check("initial_cash", 1., {name: execution["metrics"]["initial_cash"] for name, execution in executions.items()})
    policy = selected["group"]["execution_policy"]
    check("procedure_and_fixed_policy", policy, {name: executions[name]["policy"] for name in ACCOUNT_ORDER[:2]})
    # The benchmark deliberately holds for a whole evaluated session. Its
    # max_hold_bars is the maximum complete session grid, not the model limit.
    counts = {day: sum(row["phase"] == "OPEN" and row["trading_day"] == day for row in fixed["ledger"])
              for day in context["evaluated_days"]}
    check("benchmark_policy", {**policy, "max_hold_bars": max(counts.values())},
          {"benchmark": executions["benchmark"]["policy"]})
    check("benchmark_definition", BENCHMARK_DEFINITION, {"benchmark": benchmark["definition"]})
    support = _projection(reference["predictions"], _DECISION_FIELDS)
    check("all_ready_support", support,
          {name: _projection(accounts[name]["predictions"], _DECISION_FIELDS) for name in ACCOUNT_ORDER[:2]}, compact=True)
    check("outer_validation_keys", context["validation_keys"],
          {name: [row["observation_key"] for row in accounts[name]["predictions"]] for name in ACCOUNT_ORDER[:2]}, compact=True)
    for name in ACCOUNT_ORDER[:2]:
        check(name + "_executed_decisions", accounts[name]["predictions"], {name: executions[name]["decisions"]}, compact=True)
    check("benchmark_first_eligible_ready", _benchmark_support(reference["predictions"], fixed["windows"]),
          {"benchmark": _projection(executions["benchmark"]["decisions"], (*_DECISION_FIELDS, "target"))}, compact=True)
    definition = {key: reference["risk"][key] for key in _RISK_DEFINITION}
    check("risk_definition", definition, {name: {key: record["risk"][key] for key in _RISK_DEFINITION}
                                          for name, record in accounts.items()})
    failed = [row["key"] for row in checks if not row["matches"]]
    return {"matches": not failed, "failed_checks": failed, "checks": checks}


def _statistics(accounts, context, sample, sampling, basis):
    count, values, statistics = sample["sample_count"], {}, []
    for name, record in accounts.items():
        series, reason, detail = uncertainty._daily_values(record["execution"], context["folds"],
                                                          record.get("fold_contributions"))
        values[name] = series
        statistics.append(uncertainty._statistic(name, count, series, reason, detail))
    by_name = {row["series"]: row for row in statistics}
    for reference in ACCOUNT_ORDER[1:]:
        name, paired, reason, detail = "procedure_minus_" + reference, None, None, None
        unavailable = [by_name[key] for key in ("procedure", reference) if by_name[key]["mean_unavailable_reason"]]
        if unavailable:
            reason = "BOTH_SIDES_UNAVAILABLE" if len(unavailable) == 2 else unavailable[0]["series"].upper() + "_UNAVAILABLE"
            detail = "; ".join(row["series"] + ": " + row["mean_unavailable_reason"] for row in unavailable)
        elif not basis["matches"]:
            reason, detail = "BASIS_MISMATCH", "Recorded common outer basis differs: " + ", ".join(basis["failed_checks"])
        else:
            try:
                paired = tuple(uncertainty._finite(a - b) for a, b in zip(values["procedure"], values[reference], strict=True))
            except ArithmeticError as exc:
                reason, detail = "NUMERIC_OVERFLOW", str(exc)
        values[name] = paired
        statistics.append(uncertainty._statistic(name, count, paired, reason, detail))
    # One call gives every active series the same draw at every replication.
    uncertainty._mean_intervals(statistics, values, sample, sampling)
    folds = {day: fold["fold_id"] for fold in context["folds"] for day in fold["validation_days"]}
    daily = [{"trading_day": day, "fold_id": folds[day],
              "values": {name: series[index] if series is not None else None for name, series in values.items()}}
             for index, day in enumerate(context["evaluated_days"])]
    return statistics, daily


def analyze_intraday_procedure_return_uncertainty(snapshot: StrategyExperiment, *, block_days: int | None = None,
                                                replications: int = 5000, seed: int = 0) -> dict:
    """Describe conditional outer daily means, never a new selection or TEST."""
    if block_days is not None:
        uncertainty._integer(block_days, "block_days", 2)
    uncertainty._integer(replications, "replications", 1000, 20000)
    uncertainty._integer(seed, "seed", 0, 2 ** 32 - 1)
    selected = _saved_ml_source(snapshot)
    root, source, module = selected["root"], selected["source"], selected["module"]
    if module is None:
        raise ValueError("procedure return uncertainty requires a saved Q25 or Q31 selection study")
    report, context = root["report"], selected["context"]
    key = "inner_selection_id" if module is inner else "threshold_selection_id"
    result = {"version": INTRADAY_PROCEDURE_RETURN_UNCERTAINTY_VERSION, "status": report["status"],
        "evaluation_scope": "DEVELOPMENT_OUTER_RETURN_UNCERTAINTY_ONLY",
        "experiment_id": root["experiment_id"], "data_id": root["dataset_id"], "source_kind": selected["kind"],
        "source_schema_version": root["artifact_schema_version"], "algorithm_versions": deepcopy(root["algorithm_versions"]),
        "ordinary_source_id": source["experiment_id"], "source_selection": selected["selection"],
        "selection_id": report[key], "source_evaluation_scope": report["evaluation_scope"],
        "evidence": {"scope": "RECORDED_LEDGER_DERIVATION", "source_reconstructed": False,
                     "models_refitted": False, "execution_replayed": False},
        "method": {"numerical_engine": uncertainty.INTRADAY_RETURN_UNCERTAINTY_VERSION,
                   "series_order": list(SERIES_ORDER), "daily_return": "CASH_CLOSE_OVER_CASH_OPEN_MINUS_ONE",
                   "paired_difference": "PROCEDURE_MINUS_REFERENCE_PER_DAY_NOT_AN_INVESTABLE_ACCOUNT",
                   "resampling": "SYNCHRONOUS_INDICES_FOR_ALL_FIVE_SERIES",
                   "paired_basis": "COMPLETE_COMMON_THREE_ACCOUNT_BASIS_REQUIRED",
                   "inference": "RECORDED_OUTER_PATH_CONDITIONAL_ON_BLOCK_RESAMPLING_ASSUMPTIONS",
                   "exclusions": "NO_REFIT_SELECTION_RESAMPLING_SEARCH_CORRECTION_PROFIT_PROBABILITY_OR_PROMOTION",
                   "scope": "OUTER_DEV_ONLY_NO_INNER_FINAL_DEV_OR_TEST_ACCOUNTS"},
        "parameters": {"block_days": block_days, "replications": replications, "seed": seed},
        "context": deepcopy(context), "unavailable_reason": None, "unavailable_reasons": [],
        "sample": None, "sampling": None, "basis": None, "statistics": [], "daily": [], "accounts": {}}
    if report["status"] != "AVAILABLE":
        result.update(unavailable_reason="SOURCE_STUDY_UNAVAILABLE",
                      unavailable_reasons=deepcopy(report["unavailable_reasons"]))
    else:
        accounts = {"procedure": report["selected_account"], "fixed_reference": selected["reference"],
                    "benchmark": selected["group"]["benchmark"]}
        sample = uncertainty._sample_coverage(context)
        sample.update(prediction_count=len(accounts["procedure"]["predictions"]),
            complete_target_count=accounts["procedure"]["prediction_metrics"]["complete_target_count"],
            account_counts={name: {"evaluated_day_count": len(record["execution"]["daily"]),
                                  "trade_count": record["execution"]["metrics"]["trade_count"],
                                  "cash_only_day_count": sum(row["trade_count"] == 0 for row in record["execution"]["daily"])}
                            for name, record in accounts.items()})
        sampling = uncertainty._sampling(sample["sample_count"], block_days=block_days, replications=replications, seed=seed)
        basis = _account_basis(selected, accounts)
        statistics, daily = _statistics(accounts, context, sample, sampling, basis)
        result.update(sample=sample, sampling=sampling, basis=basis, statistics=statistics, daily=daily,
                      accounts=deepcopy(accounts))
    result["uncertainty_id"] = digest(result)
    return result
