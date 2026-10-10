"""Paired stationary-bootstrap mean intervals from one saved DEV account.

The calculation is conditional on the recorded strategies and evaluated days.
It neither refits models nor corrects for selecting a candidate after research.
The sample gates are engineering minima, not proof of statistical adequacy.
"""

from __future__ import annotations

import math
import random

from .intraday_data import digest
from .intraday_experiment import INTRADAY_EXPERIMENT_VERSIONS
from .intraday_risk_diagnostics import _available, _quantile
from .intraday_saved_comparison import _basis
from .strategy_experiment import StrategyExperiment


INTRADAY_RETURN_UNCERTAINTY_VERSION = "market-vault-intraday-return-uncertainty-v1"
MINIMUM_SAMPLE_COUNT = 100
MINIMUM_EXPECTED_BLOCK_COUNT = 10


def _integer(value, label, minimum, maximum=None):
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        bounds = f"at least {minimum}" if maximum is None else f"between {minimum} and {maximum}"
        raise ValueError(f"{label} must be an integer {bounds}")
    return value


def _finite(value):
    if not math.isfinite(value):
        raise OverflowError("recorded return arithmetic produced a nonfinite value")
    return value


def _mean(values):
    # Scale before summing so finite means need not overflow an unscaled sum.
    return _finite(math.fsum(value / len(values) for value in values))


def _default_block_days(count):
    value = max(2, math.ceil(count ** (1 / 3)))
    # Correct floating cube-root rounding at exact integer cubes.
    if value > 2 and (value - 1) ** 3 >= count:
        value -= 1
    if value ** 3 < count:
        value += 1
    return value


def _stationary_indices(count, block_days, rng):
    """Uniform first index, geometric restarts, and circular successors."""
    index = rng.randrange(count)
    indices = [index]
    for _ in range(1, count):
        index = rng.randrange(count) if rng.random() < 1 / block_days else (index + 1) % count
        indices.append(index)
    return indices


def _sample_coverage(context):
    development = context["split"]["TRAIN"] + context["split"]["VALIDATION"]
    evaluated = context["evaluated_days"]
    # Only omissions between the first and last evaluated trading days are gaps.
    # Unevaluated training prefixes, incomplete tails, weekends and closures are
    # not missing evaluation observations.
    window = development[development.index(evaluated[0]):development.index(evaluated[-1]) + 1]
    present = set(evaluated)
    gaps = [day for day in window if day not in present]
    return {"sample_count": len(evaluated), "first_day": evaluated[0], "last_day": evaluated[-1],
            "evaluated_days": list(evaluated), "development_day_count": len(development),
            "fold_count": len(context["folds"]), "is_contiguous": window == evaluated, "gap_days": gaps}


def _self_basis(root, context, candidate, benchmark):
    # Q11's full basis needs identities and raw records, not its separately
    # calculated Q9 performance views. Q12 already reconciles each account once.
    side = {"evaluation_scope": root["report"]["evaluation_scope"], "data_id": root["dataset_id"],
            "algorithm_versions": root["algorithm_versions"], "strategy": candidate["strategy"]}
    selected = side, context, candidate, benchmark, None
    checks = _basis(selected, selected)
    failed = [row["key"] for row in checks if not row["matches"]]
    return {"matches": not failed, "failed_checks": failed}


def _daily_values(execution, folds, recorded_contributions=None):
    availability = _available(execution, folds, recorded_contributions)
    if availability["status"] != "AVAILABLE":
        return None, availability["unavailable_reason"], availability["detail"]
    try:
        values = []
        for row in execution["daily"]:
            opened, closed = _finite(row["cash_open"]), _finite(row["cash_close"])
            if opened <= 0:
                raise ValueError("daily return requires a strictly positive opening cash denominator")
            values.append(_finite(closed / opened - 1))
        return tuple(values), None, None
    except (ValueError, ArithmeticError) as exc:
        reason = "NUMERIC_OVERFLOW" if isinstance(exc, ArithmeticError) else "RECORDED_CASH_RECONCILIATION_FAILED"
        return None, reason, str(exc)


def _statistic(series, count, values, reason=None, detail=None):
    mean = None
    if values is not None:
        try:
            mean = _mean(values)
        except ArithmeticError as exc:
            reason, detail = "NUMERIC_OVERFLOW", str(exc)
    return {"series": series, "sample_count": count, "mean": mean, "lower": None, "upper": None,
            "unit": "RATIO", "mean_unavailable_reason": reason,
            "interval_unavailable_reason": reason, "detail": detail}


def _interval_gate(sample, sampling):
    if not sample["is_contiguous"]:
        return "GAPPED_EVALUATION_DAYS", "Unevaluated DEV trading days occur inside the evaluated period."
    if sample["sample_count"] < MINIMUM_SAMPLE_COUNT:
        return "INSUFFICIENT_DAILY_RETURNS", "Mean intervals require at least 100 evaluated daily returns."
    if sampling["expected_block_count"] < MINIMUM_EXPECTED_BLOCK_COUNT:
        return "INSUFFICIENT_EXPECTED_BLOCKS", "Mean intervals require at least 10 expected resampled blocks."
    return None, None


def _mean_intervals(statistics, values, sample, sampling):
    reason, detail = _interval_gate(sample, sampling)
    active = {}
    for row in statistics:
        name = row["series"]
        if row["mean_unavailable_reason"] is not None:
            continue
        series = values[name]
        if all(value == series[0] for value in series):
            row["interval_unavailable_reason"] = "ZERO_SAMPLE_VARIATION"
            row["detail"] = "The recorded daily series is exactly constant; no mean interval is reported."
        elif reason is not None:
            row["interval_unavailable_reason"], row["detail"] = reason, detail
        else:
            active[name] = []
    if not active:
        return
    rng = random.Random(sampling["seed"])
    rows = {row["series"]: row for row in statistics}
    for _ in range(sampling["replications"]):
        indices = _stationary_indices(sample["sample_count"], sampling["block_days"], rng)
        for name in tuple(active):
            try:
                active[name].append(_mean([values[name][index] for index in indices]))
            except ArithmeticError as exc:
                rows[name]["interval_unavailable_reason"] = "NUMERIC_OVERFLOW"
                rows[name]["detail"] = str(exc)
                del active[name]
        if not active:
            return
    for name, means in active.items():
        row = rows[name]
        if all(value == means[0] for value in means):
            row["interval_unavailable_reason"] = "DEGENERATE_RESAMPLING"
            row["detail"] = "The nonconstant recorded series produced no variation among resampled means."
        else:
            ordered = sorted(means)
            try:
                row["lower"], row["upper"] = _quantile(ordered, .025), _quantile(ordered, .975)
            except ArithmeticError as exc:
                row["interval_unavailable_reason"], row["detail"] = "NUMERIC_OVERFLOW", str(exc)


def analyze_intraday_return_uncertainty(snapshot: StrategyExperiment, *, cost_index: int = 0,
                                        candidate_index: int = 0, block_days: int | None = None,
                                        replications: int = 5000, seed: int = 0) -> dict:
    """Derive paired DEV mean intervals without source access or model fitting.

    All three series use synchronous stationary-bootstrap indices. Intervals
    assume the recorded daily process is suitable for block resampling; they
    are neither a future-profit probability nor a selection-bias correction.
    """
    if type(snapshot) is not StrategyExperiment:
        raise ValueError("an immutable StrategyExperiment is required")
    _integer(cost_index, "cost_index", 0)
    _integer(candidate_index, "candidate_index", 0)
    if block_days is not None:
        _integer(block_days, "block_days", 2)
    _integer(replications, "replications", 1000, 20000)
    _integer(seed, "seed", 0, 2 ** 32 - 1)
    root = snapshot.as_dict()
    if (root["artifact_schema_version"] not in INTRADAY_EXPERIMENT_VERSIONS
            or root["evaluation_mode"] not in ("INTRADAY_COMPARISON", "INTRADAY_DIAGNOSTICS")
            or root["report"]["evaluation_scope"] != "DEVELOPMENT_WALK_FORWARD_ONLY"):
        raise ValueError("return uncertainty requires an ordinary saved Q7 DEV comparison or diagnostics experiment")
    report = root["report"]
    if cost_index >= len(report["groups"]) or candidate_index >= len(report["groups"][cost_index]["results"]):
        raise ValueError("selected cost/candidate index is outside the saved experiment")
    context, group = report["context"], report["groups"][cost_index]
    candidate, benchmark = group["results"][candidate_index], group["benchmark"]
    sample = _sample_coverage(context)
    errors = candidate["prediction_metrics"]
    sample.update(unevaluated_development_day_count=len(context["unevaluated_development_days"]),
                  prediction_count=len(candidate["predictions"]),
                  complete_target_count=errors["complete_target_count"] if errors is not None else None,
                  complete_target_count_unavailable_reason=None if errors is not None else "NOT_APPLICABLE")
    count = sample["sample_count"]
    length = _default_block_days(count) if block_days is None else block_days
    sampling = {"method": "STATIONARY_BOOTSTRAP", "prng": "PYTHON_RANDOM_MT19937", "block_days": length,
                "block_days_source": "CUBE_ROOT_HEURISTIC" if block_days is None else "EXPLICIT",
                "replications": replications, "seed": seed, "confidence_level": .95,
                "interval_method": "PERCENTILE", "quantile_method": "LINEAR_N_MINUS_ONE",
                "restart_probability": 1 / length, "expected_block_count": 1 + (count - 1) / length,
                "minimum_sample_count": MINIMUM_SAMPLE_COUNT,
                "minimum_expected_block_count": MINIMUM_EXPECTED_BLOCK_COUNT, "boundary": "CIRCULAR"}
    basis = _self_basis(root, context, candidate, benchmark)
    statistics, values = [], {}
    for name, record, contributions in (("strategy", candidate, candidate["fold_contributions"]),
                                         ("benchmark", benchmark, None)):
        series, reason, detail = _daily_values(record["execution"], context["folds"], contributions)
        values[name] = series
        statistics.append(_statistic(name, count, series, reason, detail))
    unavailable = [row for row in statistics if row["mean_unavailable_reason"] is not None]
    paired, reason, detail = None, None, None
    if unavailable:
        reason = "BOTH_SIDES_UNAVAILABLE" if len(unavailable) == 2 else unavailable[0]["series"].upper() + "_UNAVAILABLE"
        detail = "; ".join(row["series"] + ": " + row["mean_unavailable_reason"] for row in unavailable)
    elif not basis["matches"]:
        reason, detail = "BASIS_MISMATCH", "Recorded strategy and benchmark basis differs: " + ", ".join(basis["failed_checks"])
    else:
        try:
            paired = tuple(_finite(a - b) for a, b in zip(values["strategy"], values["benchmark"], strict=True))
        except ArithmeticError as exc:
            reason, detail = "NUMERIC_OVERFLOW", str(exc)
    values["paired_excess"] = paired
    statistics.append(_statistic("paired_excess", count, paired, reason, detail))
    _mean_intervals(statistics, values, sample, sampling)
    result = {"version": INTRADAY_RETURN_UNCERTAINTY_VERSION, "status": "SUCCESS", "evidence": "RECORDED_LEDGER_DERIVATION",
              "experiment_id": root["experiment_id"], "data_id": root["dataset_id"],
              "evaluation_scope": report["evaluation_scope"], "cost_index": cost_index, "candidate_index": candidate_index,
              "candidate_id": candidate["candidate_id"], "strategy": candidate["strategy"],
              "strategy_execution_id": candidate["execution"]["execution_id"],
              "benchmark_execution_id": benchmark["execution"]["execution_id"],
              "execution_policy": group["execution_policy"], "sample": sample, "sampling": sampling,
              "basis": basis, "statistics": statistics}
    result["uncertainty_id"] = digest(result)
    return result
