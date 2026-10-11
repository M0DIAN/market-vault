"""Complete three-procedure outer-return bounds against one fixed reference.

The family is exactly Q25, Q31 and Q36 on their identical ordinary source.
Only recorded account paths are used; fitting, selection and execution are
not repeated. The bounds cover this declared family, not unknown research.
"""

from __future__ import annotations

from copy import deepcopy

from . import intraday_family_bounds as bounds
from . import intraday_return_uncertainty as uncertainty
from .intraday_data import digest
from .intraday_procedure_comparison import (
    PROCEDURE_ORDER, _accounts, _member, _paired_values, _parameters, _procedure, _same_source,
)
from .intraday_procedure_return_uncertainty import _account_basis
from .strategy_experiment import StrategyExperiment


INTRADAY_PROCEDURE_FAMILY_VERSION = "market-vault-intraday-procedure-family-v1"
FAMILY_ROLES = ("Q25", "Q31", "Q36")


def _family(snapshots):
    if type(snapshots) not in (tuple, list) or len(snapshots) != len(FAMILY_ROLES):
        raise ValueError("the family requires exactly three explicit Q25, Q31 and Q36 studies")
    if any(type(snapshot) is not StrategyExperiment for snapshot in snapshots):
        raise ValueError("every family member must be an immutable StrategyExperiment")
    selected = [_procedure(snapshot) for snapshot in snapshots]
    by_kind = {view["kind"]: view for view in selected}
    if set(by_kind) != set(PROCEDURE_ORDER):
        raise ValueError("the family requires each of Q25, Q31 and Q36 exactly once; duplicate kinds are invalid")
    ordered = [by_kind[kind] for kind in PROCEDURE_ORDER]
    for view in ordered[1:]:
        _same_source(ordered[0], view)
    return ordered


def _daily_account(account, context):
    series, reason, detail = uncertainty._daily_values(account["execution"], context["folds"],
                                                      account.get("fold_contributions"))
    if [row["trading_day"] for row in account["execution"]["daily"]] != context["evaluated_days"]:
        return None, "BASIS_MISMATCH", "Complete original evaluated dates differ."
    return series, reason, detail


def _statistic(member, index, count):
    account = member["selected_account"]
    return {"role": member["role"], "member_index": index, "experiment_id": member["experiment_id"],
            "selection_id": member["selection_id"],
            "execution_id": None if account is None else account["execution"]["execution_id"],
            "sample_count": count, "mean_excess": None, "lower": None, "unit": "RATIO",
            "mean_unavailable_reason": None, "bound_unavailable_reason": None, "detail": None}


def _family_inference(statistics, values, sample, sampling, basis):
    # Q16's private numerical primitive calls each column candidate_index.
    # This adapter supplies column positions only, never fixed-strategy IDs.
    temporary = [{**row, "candidate_index": row["member_index"]} for row in statistics]
    inference = bounds._family_bounds(temporary, values, sample, sampling, basis)

    def detail(value):
        if value is not None:
            for index, role in enumerate(FAMILY_ROLES):
                value = value.replace(f"candidate {index}:", f"procedure {role}:")
        return value

    for original, computed in zip(statistics, temporary, strict=True):
        for key in ("lower", "bound_unavailable_reason"):
            original[key] = computed[key]
        original["detail"] = detail(computed["detail"])
    return {**inference, "detail": detail(inference["detail"])}


def analyze_intraday_procedure_family(
    snapshots: tuple[StrategyExperiment, ...] | list[StrategyExperiment], *,
    block_days: int | None = None, replications: int = 5000, seed: int = 0,
) -> dict:
    """Bound all three recorded procedure-minus-fixed daily means together."""
    _parameters(block_days, replications, seed)
    selected = _family(snapshots)
    first, context = selected[0], selected[0]["context"]
    members = [_member(view, role) for view, role in zip(selected, FAMILY_ROLES, strict=True)]
    count = len(context["evaluated_days"])
    statistics = [_statistic(member, index, count) for index, member in enumerate(members)]
    result = {"version": INTRADAY_PROCEDURE_FAMILY_VERSION, "status": "AVAILABLE",
        "evaluation_scope": "DEVELOPMENT_OUTER_PROCEDURE_FAMILY_BOUNDS_ONLY",
        "ordinary_source_id": first["source"]["experiment_id"], "data_id": first["source"]["dataset_id"],
        "source_selection": deepcopy(first["selection"]), "context": deepcopy(context), "members": members,
        "family_size": 3, "family_scope": "DECLARED_THREE_PROCEDURES_ONLY", "historical_search_coverage": "UNKNOWN",
        "reference": {"ordinary_source_id": first["source"]["experiment_id"], **deepcopy(first["selection"]),
                      "account": deepcopy(first["reference"])},
        "benchmark": deepcopy(first["group"]["benchmark"]),
        "evidence": {"scope": "RECORDED_LEDGER_DERIVATION", "source_reconstructed": False,
                     "models_refitted": False, "execution_replayed": False},
        "method": {"family_order": list(FAMILY_ROLES), "daily_return": "CASH_CLOSE_OVER_CASH_OPEN_MINUS_ONE",
                   "excess": "PROCEDURE_MINUS_ORIGINAL_FIXED_REFERENCE_PER_DAY_NOT_AN_INVESTABLE_ACCOUNT",
                   "resampling": "SYNCHRONOUS_INDICES_FOR_ALL_THREE_EXCESS_SERIES",
                   "numerical_engine": bounds.INTRADAY_FAMILY_BOUNDS_VERSION,
                   "daily_numerical_engine": uncertainty.INTRADAY_RETURN_UNCERTAINTY_VERSION,
                   "inference": "RECORDED_OUTER_PATH_CONDITIONAL_ON_BLOCK_RESAMPLING_ASSUMPTIONS",
                   "exclusions": "NO_REFIT_SELECTION_RESAMPLING_GLOBAL_SEARCH_CORRECTION_PROFIT_PROBABILITY_OR_PROMOTION",
                   "scope": "OUTER_DEV_ONLY_NO_INNER_FINAL_DEV_OR_TEST_ACCOUNTS"},
        "parameters": {"block_days": block_days, "replications": replications, "seed": seed},
        "basis": None, "sample": None, "sampling": None, "statistics": statistics, "daily": [],
        "shared_account_checks": [], "family_inference": None,
        "unavailable_reason": None, "unavailable_reasons": []}
    failed = [{"role": member["role"], "reason": "SOURCE_STUDY_UNAVAILABLE",
               "details": member["unavailable_reasons"]} for member in members if member["status"] != "AVAILABLE"]
    if failed:
        explanation = "Required unavailable procedures: " + ", ".join(row["role"] for row in failed)
        for row, member in zip(statistics, members, strict=True):
            reason = "SOURCE_STUDY_UNAVAILABLE" if member["status"] != "AVAILABLE" else "REQUIRED_SOURCE_STUDY_UNAVAILABLE"
            row.update(mean_unavailable_reason=reason, bound_unavailable_reason=reason, detail=explanation)
        result.update(status="UNAVAILABLE", unavailable_reason="SOURCE_STUDY_UNAVAILABLE", unavailable_reasons=failed,
                      family_inference={"status": "UNAVAILABLE", "reason": "SOURCE_STUDY_UNAVAILABLE",
                                        "detail": explanation, "deduction": None})
    else:
        sample = uncertainty._sample_coverage(context)
        sampling = uncertainty._sampling(count, block_days=block_days, replications=replications, seed=seed)
        sampling.pop("interval_method")
        sampling.update(bound_method="SINGLE_STEP_UNSTUDENTIZED_CENTERED_MAX", bound_type="ONE_SIDED_LOWER")
        checks = [{"role": role, **_account_basis(view, _accounts(view))}
                  for role, view in zip(FAMILY_ROLES, selected, strict=True)]
        failures = [row["role"] + ":" + key for row in checks for key in row["failed_checks"]]
        basis = {"matches": not failures, "failed_checks": failures, "members": checks,
                 "source_comparison": "COMPLETE_ORDINARY_SOURCE_AND_REFERENCE_EQUAL"}
        shared, shared_checks = {}, []
        for name, account in (("fixed_reference", first["reference"]), ("benchmark", first["group"]["benchmark"])):
            series, failure, explanation = _daily_account(account, context)
            shared[name] = series
            shared_checks.append({"account": name, "unavailable_reason": failure, "detail": explanation})
        shared_failed = [row for row in shared_checks if row["unavailable_reason"]]
        values, procedure_returns = [], {}
        for member, row, check in zip(members, statistics, checks, strict=True):
            series, reason, detail = _daily_account(member["selected_account"], context)
            procedure_returns[member["role"]] = series
            paired, mean = None, None
            if not check["matches"]:
                reason, detail = "BASIS_MISMATCH", "Recorded procedure basis differs: " + ", ".join(check["failed_checks"])
            elif shared_failed:
                reason, detail = "SHARED_ACCOUNT_UNAVAILABLE", "; ".join(
                    item["account"] + ": " + item["unavailable_reason"] for item in shared_failed)
            if reason is None:
                try:
                    paired = _paired_values(shared["fixed_reference"], series)
                    mean = uncertainty._mean(paired)
                except ArithmeticError as exc:
                    paired, reason, detail = None, "NUMERIC_OVERFLOW", str(exc)
            row.update(mean_excess=mean, mean_unavailable_reason=reason, bound_unavailable_reason=reason, detail=detail)
            values.append(paired)
        inference = _family_inference(statistics, values, sample, sampling, basis)
        folds = {day: fold["fold_id"] for fold in context["folds"] for day in fold["validation_days"]}
        daily = [{"trading_day": day, "fold_id": folds[day],
                  "values": {role: series[index] if series is not None else None
                             for role, series in zip(FAMILY_ROLES, values, strict=True)},
                  "fixed_reference_return": None if shared["fixed_reference"] is None else shared["fixed_reference"][index],
                  "procedure_returns": {role: series[index] if series is not None else None
                                        for role, series in procedure_returns.items()}}
                 for index, day in enumerate(context["evaluated_days"])]
        result.update(basis=basis, sample=sample, sampling=sampling, daily=daily,
                      shared_account_checks=shared_checks, family_inference=inference)
        invalid = [{"role": row["role"], "reason": row["mean_unavailable_reason"], "details": row["detail"]}
                   for row in statistics if row["mean_unavailable_reason"]]
        if not basis["matches"] or shared_failed or invalid:
            reason = "BASIS_MISMATCH" if not basis["matches"] else "SHARED_ACCOUNT_UNAVAILABLE" if shared_failed else "FAMILY_MEMBER_UNAVAILABLE"
            result.update(status="UNAVAILABLE", unavailable_reason=reason, unavailable_reasons=invalid)
    result["family_bounds_id"] = digest(result)
    return result
