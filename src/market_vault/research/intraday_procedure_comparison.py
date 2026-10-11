"""Direct paired outer-return evidence for two explicit selection procedures.

The original ordinary source and reference are identical on both sides.
This recorded-only analysis does not refit, reselect, replay Q5 or create a
strategy eligible for Freeze. A daily B-minus-A difference is not an account.
"""

from __future__ import annotations

from copy import deepcopy

from . import intraday_return_uncertainty as uncertainty
from .intraday_data import digest
from .intraday_ml_diagnostics import _saved_ml_source
from .intraday_procedure_return_uncertainty import _account_basis
from .strategy_experiment import StrategyExperiment, canonical_json


INTRADAY_PROCEDURE_COMPARISON_VERSION = "market-vault-intraday-procedure-comparison-v1"
PROCEDURE_ORDER = ("INNER_MODEL_SELECTION", "ECONOMIC_THRESHOLD_SELECTION", "JOINT_ECONOMIC_SELECTION")
SERIES_ORDER = ("A", "B", "B_MINUS_A")


def _parameters(block_days, replications, seed):
    if block_days is not None:
        uncertainty._integer(block_days, "block_days", 2)
    uncertainty._integer(replications, "replications", 1000, 20000)
    uncertainty._integer(seed, "seed", 0, 2 ** 32 - 1)


def _procedure(snapshot):
    selected = _saved_ml_source(snapshot)
    if selected["kind"] not in PROCEDURE_ORDER:
        raise ValueError("an explicit saved Q25, Q31 or Q36 selection study is required")
    return selected


def _same_source(left, right):
    # Equality covers the complete saved source, not only declared IDs or an
    # intersection of evaluation dates. Relocated study locators may differ.
    if canonical_json(left["source"]) != canonical_json(right["source"]):
        raise ValueError("procedures must embed the same complete ordinary source")
    if left["selection"] != right["selection"]:
        raise ValueError("procedures must use the same original cost/candidate reference")


def _accounts(selected):
    return {"procedure": selected["root"]["report"]["selected_account"],
            "fixed_reference": selected["reference"], "benchmark": selected["group"]["benchmark"]}


def _member(selected, role):
    root, report = selected["root"], selected["root"]["report"]
    # Keep each actual outer application/refit and its selection identity.
    # Inner objective matrices are not inputs to this outer-return analysis.
    folds = []
    for record in report["outer_folds"]:
        field = "application" if "application" in record else "refit"
        folds.append({"fold_id": record["fold_id"], "selected_index": record["inner"]["selected_index"],
                      "selected_recipe": deepcopy(record["inner"]["selected_recipe"]),
                      field: deepcopy(record[field])})
    return {"role": role, "experiment_id": root["experiment_id"], "source_kind": selected["kind"],
            "selection_id": report[selected["report_key"]], "name": root["name"],
            "source_schema_version": root["artifact_schema_version"],
            "algorithm_versions": deepcopy(root["algorithm_versions"]), "status": report["status"],
            "unavailable_reasons": deepcopy(report["unavailable_reasons"]),
            "selected_account": deepcopy(report["selected_account"]), "outer_folds": folds}


def _paired_values(left, right):
    return tuple(uncertainty._finite(b - a) for a, b in zip(left, right, strict=True))


def compare_intraday_procedures(left: StrategyExperiment, right: StrategyExperiment, *,
                                block_days: int | None = None, replications: int = 5000,
                                seed: int = 0) -> dict:
    """Compare two different recorded procedures on one complete outer basis."""
    _parameters(block_days, replications, seed)
    selected = [_procedure(left), _procedure(right)]
    if selected[0]["kind"] == selected[1]["kind"]:
        raise ValueError("A/B comparison requires two different Q25/Q31/Q36 procedure kinds")
    _same_source(*selected)
    first, context = selected[0], selected[0]["context"]
    members = [_member(view, role) for view, role in zip(selected, SERIES_ORDER[:2], strict=True)]
    result = {"version": INTRADAY_PROCEDURE_COMPARISON_VERSION, "status": "AVAILABLE",
        "evaluation_scope": "DEVELOPMENT_OUTER_PROCEDURE_COMPARISON_ONLY",
        "ordinary_source_id": first["source"]["experiment_id"], "data_id": first["source"]["dataset_id"],
        "source_selection": deepcopy(first["selection"]), "context": deepcopy(context), "members": members,
        "evidence": {"scope": "RECORDED_LEDGER_DERIVATION", "source_reconstructed": False,
                     "models_refitted": False, "execution_replayed": False},
        "method": {"series_order": list(SERIES_ORDER), "daily_return": "CASH_CLOSE_OVER_CASH_OPEN_MINUS_ONE",
                   "paired_difference": "B_MINUS_A_PER_DAY_NOT_AN_INVESTABLE_ACCOUNT",
                   "resampling": "SYNCHRONOUS_INDICES_FOR_ALL_THREE_SERIES",
                   "numerical_engine": uncertainty.INTRADAY_RETURN_UNCERTAINTY_VERSION,
                   "inference": "RECORDED_OUTER_PATH_CONDITIONAL_ON_BLOCK_RESAMPLING_ASSUMPTIONS",
                   "exclusions": "NO_REFIT_SELECTION_RESAMPLING_SEARCH_CORRECTION_PROFIT_PROBABILITY_OR_PROMOTION",
                   "scope": "OUTER_DEV_ONLY_NO_INNER_FINAL_DEV_OR_TEST_ACCOUNTS"},
        "parameters": {"block_days": block_days, "replications": replications, "seed": seed},
        "basis": None, "sample": None, "sampling": None, "statistics": [], "daily": [],
        "shared_account_checks": [],
        "unavailable_reason": None, "unavailable_reasons": []}
    failed = [{"role": member["role"], "reason": "SOURCE_STUDY_UNAVAILABLE",
               "details": member["unavailable_reasons"]} for member in members if member["status"] != "AVAILABLE"]
    if failed:
        result.update(status="UNAVAILABLE", unavailable_reason="SOURCE_STUDY_UNAVAILABLE", unavailable_reasons=failed)
    else:
        sample = uncertainty._sample_coverage(context)
        sampling = uncertainty._sampling(sample["sample_count"], block_days=block_days, replications=replications, seed=seed)
        checks = [{"role": role, **_account_basis(view, _accounts(view))}
                  for role, view in zip(SERIES_ORDER[:2], selected, strict=True)]
        failures = [row["role"] + ":" + key for row in checks for key in row["failed_checks"]]
        basis = {"matches": not failures, "failed_checks": failures, "members": checks,
                 "source_comparison": "COMPLETE_ORDINARY_SOURCE_AND_REFERENCE_EQUAL"}
        shared_checks = []
        for name, account in (("fixed_reference", first["reference"]), ("benchmark", first["group"]["benchmark"])):
            _, failure, explanation = uncertainty._daily_values(account["execution"], context["folds"],
                                                                account.get("fold_contributions"))
            shared_checks.append({"account": name, "unavailable_reason": failure, "detail": explanation})
        values, statistics = {}, []
        for member in members:
            account, role = member["selected_account"], member["role"]
            series, reason, detail = uncertainty._daily_values(account["execution"], context["folds"],
                                                              account["fold_contributions"])
            # No intersection/truncation even if a saved account is internally
            # consistent but does not have the complete original day support.
            if [row["trading_day"] for row in account["execution"]["daily"]] != context["evaluated_days"]:
                series, reason, detail = None, "BASIS_MISMATCH", "Complete original evaluated dates differ."
            values[role] = series
            statistics.append(uncertainty._statistic(role, sample["sample_count"], series, reason, detail))
        pair, reason, detail = None, None, None
        invalid = [row for row in statistics if row["mean_unavailable_reason"]]
        if not basis["matches"]:
            reason, detail = "BASIS_MISMATCH", ", ".join(failures)
        elif any(row["unavailable_reason"] for row in shared_checks):
            reason = "SHARED_ACCOUNT_UNAVAILABLE"
            detail = "; ".join(row["account"] + ": " + row["unavailable_reason"]
                               for row in shared_checks if row["unavailable_reason"])
        elif invalid:
            reason = "BOTH_SIDES_UNAVAILABLE" if len(invalid) == 2 else invalid[0]["series"] + "_UNAVAILABLE"
            detail = "; ".join(row["series"] + ": " + row["mean_unavailable_reason"] for row in invalid)
        else:
            try:
                pair = _paired_values(values["A"], values["B"])
            except ArithmeticError as exc:
                reason, detail = "NUMERIC_OVERFLOW", str(exc)
        values["B_MINUS_A"] = pair
        statistics.append(uncertainty._statistic("B_MINUS_A", sample["sample_count"], pair, reason, detail))
        uncertainty._mean_intervals(statistics, values, sample, sampling)
        folds = {day: fold["fold_id"] for fold in context["folds"] for day in fold["validation_days"]}
        daily = [{"trading_day": day, "fold_id": folds[day],
                  "values": {name: series[index] if series is not None else None for name, series in values.items()}}
                 for index, day in enumerate(context["evaluated_days"])]
        result.update(basis=basis, sample=sample, sampling=sampling, statistics=statistics, daily=daily,
                      shared_account_checks=shared_checks)
        if reason:
            result.update(status="UNAVAILABLE", unavailable_reason=reason,
                          unavailable_reasons=[{"role": "B_MINUS_A", "reason": reason, "details": detail}])
    result["comparison_id"] = digest(result)
    return result
