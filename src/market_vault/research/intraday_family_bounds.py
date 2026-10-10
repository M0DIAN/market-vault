"""Joint stationary-bootstrap lower bounds for a complete saved DEV cost group.

The single-step, unstudentized region conditions on the recorded strategies.
Its nominal coverage is approximate and assumes suitable stationary, weakly
dependent daily evidence; it does not cover unseen historical research.
"""

from __future__ import annotations

import random

from .intraday_data import digest
from .intraday_experiment import INTRADAY_EXPERIMENT_VERSIONS
from .intraday_return_uncertainty import (
    MINIMUM_EXPECTED_BLOCK_COUNT, MINIMUM_SAMPLE_COUNT, _daily_values,
    _default_block_days, _finite, _integer, _interval_gate, _mean,
    _sample_coverage, _self_basis, _stationary_indices,
)
from .intraday_risk_diagnostics import _quantile
from .intraday_saved_comparison import _basis
from .strategy_experiment import StrategyExperiment


INTRADAY_FAMILY_BOUNDS_VERSION = "market-vault-intraday-family-bounds-v1"


def _family_basis(root, context, candidates, benchmark):
    # Q11 needs the complete recorded basis, without its additional Q9 views.
    # Account derivation below already reconciles every member and benchmark.
    reference, failed = None, []
    for candidate in candidates:
        side = {"evaluation_scope": root["report"]["evaluation_scope"], "data_id": root["dataset_id"],
                "algorithm_versions": root["algorithm_versions"], "strategy": candidate["strategy"]}
        selected = side, context, candidate, benchmark, None
        if reference is None:
            reference = selected
        for check in _basis(reference, selected):
            if not check["matches"] and check["key"] not in failed:
                failed.append(check["key"])
    return {"matches": not failed, "failed_checks": failed}


def _family_bounds(members, values, sample, sampling, basis):
    """Retain every column in one centered maximum; never select a subfamily."""
    constant = []
    for row, series in zip(members, values, strict=True):
        fixed = series is not None and all(value == series[0] for value in series)
        constant.append(fixed)
        if fixed and row["mean_unavailable_reason"] is None:
            row["bound_unavailable_reason"] = "ZERO_SAMPLE_VARIATION"
            row["detail"] = "The recorded excess series is exactly constant; no lower bound is reported."

    def unavailable(reason, detail):
        for row in members:
            if row["bound_unavailable_reason"] is None:
                row["bound_unavailable_reason"], row["detail"] = reason, detail
        return {"status": "UNAVAILABLE", "reason": reason, "detail": detail, "deduction": None}

    if not basis["matches"]:
        return unavailable("BASIS_MISMATCH", "Recorded family basis differs: " + ", ".join(basis["failed_checks"]))
    invalid = [row for row in members if row["mean_unavailable_reason"] is not None]
    if invalid:
        detail = "; ".join(f"candidate {row['candidate_index']}: {row['mean_unavailable_reason']}" for row in invalid)
        return unavailable("FAMILY_MEMBER_UNAVAILABLE", detail)
    if all(constant):
        return unavailable("DEGENERATE_FAMILY", "Every recorded excess series is exactly constant.")
    reason, detail = _interval_gate(sample, sampling)
    if reason is not None:
        return unavailable(reason, detail.replace("Mean intervals", "Family bounds"))

    rng, maxima = random.Random(sampling["seed"]), []
    first_deltas, varied = None, [False] * len(members)
    try:
        for _ in range(sampling["replications"]):
            indices = _stationary_indices(sample["sample_count"], sampling["block_days"], rng)
            # Exactly constant columns contribute exact centered zero, even
            # when the floating mean of a repeated constant rounds differently.
            deltas = [0.0 if fixed else _finite(_mean([series[index] for index in indices]) - row["mean_excess"])
                      for row, series, fixed in zip(members, values, constant, strict=True)]
            maxima.append(max(deltas))
            if first_deltas is None:
                first_deltas = deltas
            else:
                varied = [changed or a != b for changed, a, b in zip(varied, first_deltas, deltas, strict=True)]
        if all(value == maxima[0] for value in maxima):
            return unavailable("DEGENERATE_FAMILY", "The joint centered maximum has no variation among resamples.")
        deduction = max(0.0, _quantile(sorted(maxima), .95))
        # Calculate all bounds before assigning any: one overflow cannot leave
        # an apparently available subset of the declared family.
        lowers = [None if fixed or not changed else _finite(row["mean_excess"] - deduction)
                  for row, fixed, changed in zip(members, constant, varied, strict=True)]
    except ArithmeticError as exc:
        return unavailable("NUMERIC_OVERFLOW", str(exc))
    for row, fixed, changed, lower in zip(members, constant, varied, lowers, strict=True):
        if not fixed and not changed:
            row["bound_unavailable_reason"] = "DEGENERATE_RESAMPLING"
            row["detail"] = "The nonconstant excess series produced no variation among resampled means."
        row["lower"] = lower
    return {"status": "AVAILABLE", "reason": None, "detail": None, "deduction": deduction}


def analyze_intraday_family_bounds(snapshot: StrategyExperiment, *, cost_index: int = 0,
                                  block_days: int | None = None, replications: int = 5000,
                                  seed: int = 0) -> dict:
    """Derive approximate 95% one-sided bounds for every saved DEV member.

    The shared deduction is the nonnegative 95th percentile of jointly
    centered bootstrap maxima. This is neither a step-down procedure nor a
    global selection adjustment, and it never chooses a candidate.
    """
    if type(snapshot) is not StrategyExperiment:
        raise ValueError("an immutable StrategyExperiment is required")
    _integer(cost_index, "cost_index", 0)
    if block_days is not None:
        _integer(block_days, "block_days", 2)
    _integer(replications, "replications", 1000, 20000)
    _integer(seed, "seed", 0, 2 ** 32 - 1)
    root = snapshot.as_dict()
    if root["evaluation_mode"] == "INTRADAY_EXECUTION_SCENARIOS":
        raise ValueError("export an ordinary Q7 scenario before deriving family bounds from a collection")
    if (root["artifact_schema_version"] not in INTRADAY_EXPERIMENT_VERSIONS
            or root["evaluation_mode"] not in ("INTRADAY_COMPARISON", "INTRADAY_DIAGNOSTICS")
            or root["report"]["evaluation_scope"] != "DEVELOPMENT_WALK_FORWARD_ONLY"):
        raise ValueError("family bounds requires an ordinary saved Q7 DEV comparison or diagnostics experiment")
    report = root["report"]
    if cost_index >= len(report["groups"]):
        raise ValueError("selected cost index is outside the saved experiment")
    context, group = report["context"], report["groups"][cost_index]
    candidates, benchmark = group["results"], group["benchmark"]
    sample = _sample_coverage(context)
    sample["unevaluated_development_day_count"] = len(context["unevaluated_development_days"])
    count = sample["sample_count"]
    length = _default_block_days(count) if block_days is None else block_days
    sampling = {"method": "STATIONARY_BOOTSTRAP", "prng": "PYTHON_RANDOM_MT19937", "block_days": length,
                "block_days_source": "CUBE_ROOT_HEURISTIC" if block_days is None else "EXPLICIT",
                "replications": replications, "seed": seed, "confidence_level": .95,
                "bound_method": "SINGLE_STEP_UNSTUDENTIZED_CENTERED_MAX", "bound_type": "ONE_SIDED_LOWER",
                "quantile_method": "LINEAR_N_MINUS_ONE", "restart_probability": 1 / length,
                "expected_block_count": 1 + (count - 1) / length,
                "minimum_sample_count": MINIMUM_SAMPLE_COUNT,
                "minimum_expected_block_count": MINIMUM_EXPECTED_BLOCK_COUNT, "boundary": "CIRCULAR"}
    basis = _family_basis(root, context, candidates, benchmark)
    benchmark_values, benchmark_reason, benchmark_detail = _daily_values(benchmark["execution"], context["folds"])
    members, values = [], []
    for index, candidate in enumerate(candidates):
        own_basis = _self_basis(root, context, candidate, benchmark)
        series, strategy_reason, strategy_detail = _daily_values(
            candidate["execution"], context["folds"], candidate["fold_contributions"])
        paired, mean, reason, detail = None, None, None, None
        invalid = [(name, failure, explanation) for name, failure, explanation in (
            ("strategy", strategy_reason, strategy_detail), ("benchmark", benchmark_reason, benchmark_detail)) if failure is not None]
        if invalid:
            reason = "BOTH_SIDES_UNAVAILABLE" if len(invalid) == 2 else invalid[0][0].upper() + "_UNAVAILABLE"
            detail = "; ".join(f"{name}: {failure}: {explanation}" for name, failure, explanation in invalid)
        elif not own_basis["matches"]:
            reason, detail = "BASIS_MISMATCH", "Recorded strategy and benchmark basis differs: " + ", ".join(own_basis["failed_checks"])
        else:
            try:
                paired = tuple(_finite(a - b) for a, b in zip(series, benchmark_values, strict=True))
                mean = _mean(paired)
            except ArithmeticError as exc:
                reason, detail = "NUMERIC_OVERFLOW", str(exc)
        errors = candidate["prediction_metrics"]
        members.append({"candidate_index": index, "candidate_id": candidate["candidate_id"], "strategy": candidate["strategy"],
            "execution_id": candidate["execution"]["execution_id"], "sample_count": count,
            "mean_excess": mean, "lower": None, "unit": "RATIO", "mean_unavailable_reason": reason,
            "bound_unavailable_reason": reason, "detail": detail, "basis": own_basis,
            "prediction_coverage": {"prediction_count": len(candidate["predictions"]),
                "complete_target_count": errors["complete_target_count"] if errors is not None else None,
                "complete_target_count_unavailable_reason": None if errors is not None else "NOT_APPLICABLE"}})
        values.append(paired)
    inference = _family_bounds(members, values, sample, sampling, basis)
    result = {"version": INTRADAY_FAMILY_BOUNDS_VERSION, "status": "SUCCESS", "evidence": "RECORDED_LEDGER_DERIVATION",
              "experiment_id": root["experiment_id"], "data_id": root["dataset_id"],
              "evaluation_scope": report["evaluation_scope"], "cost_index": cost_index,
              "cost_group_count": len(report["groups"]), "evaluation_count": report["evaluation_count"],
              "family_size": len(candidates), "family_scope": "SAVED_COST_GROUP_ONLY", "historical_search_coverage": "UNKNOWN",
              "benchmark_execution_id": benchmark["execution"]["execution_id"], "execution_policy": group["execution_policy"],
              "sample": sample, "sampling": sampling, "basis": basis, "members": members, "family_inference": inference}
    result["family_bounds_id"] = digest(result)
    return result
