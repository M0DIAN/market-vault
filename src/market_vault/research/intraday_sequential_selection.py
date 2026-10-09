"""Causal fold-by-fold selection from one complete saved DEV candidate family.

The fixed rule uses only previously completed folds. This is conditional on
the recorded family and fits, not proof of prior family commitment or source
point-in-time correctness, and not a new execution or global overfitting test.
"""

from __future__ import annotations

from .intraday_data import digest
from .intraday_experiment import INTRADAY_EXPERIMENT_VERSION
from .intraday_family_bounds import _family_basis
from .intraday_portfolio import _account_summary
from .intraday_return_uncertainty import _daily_values, _finite, _integer, _mean, _sample_coverage
from .intraday_risk_diagnostics import _clock, _metric, _reconcile
from .strategy_experiment import StrategyExperiment


INTRADAY_SEQUENTIAL_SELECTION_VERSION = "market-vault-intraday-sequential-selection-v1"


def _causality(context, candidates, benchmark):
    """Check recorded clocks and known observation membership, without Q5.

    The immutable reader already binds each Ridge model to its fold, including
    training keys and boundary. Unknown training-row timestamps still require
    source verification; these checks do not purport to establish those.
    """
    daily = {row["trading_day"]: row for row in benchmark["execution"]["daily"]}
    predictions = candidates[0]["predictions"]
    known_days = {row["observation_key"]: row["trading_day"] for row in predictions}
    failed, checks, previous_close = [], [], None
    for fold in context["folds"]:
        days = fold["validation_days"]
        opened = daily[days[0]]["open_time"]
        expected_keys = [row["observation_key"] for row in predictions if row["trading_day"] in days]
        invalid_training = [key for key in fold["training_keys"] if key in known_days and known_days[key] >= days[0]]
        invalid_purged = [key for key in fold["purged_keys"] if key in known_days and known_days[key] >= days[0]]
        checks.append({"fold_index": fold["fold_index"], "fold_id": fold["fold_id"],
            "training_boundary": fold["training_boundary"], "evaluation_open": opened,
            "boundary_matches_open": _clock(fold["training_boundary"]) == _clock(opened),
            "validation_keys_match_days": fold["validation_keys"] == expected_keys,
            "invalid_training_keys": invalid_training, "invalid_purged_keys": invalid_purged,
            "previous_fold_ends_before_open": previous_close is None or previous_close < _clock(opened)})
        for key in ("boundary_matches_open", "validation_keys_match_days", "previous_fold_ends_before_open"):
            if not checks[-1][key]:
                failed.append(f"fold[{fold['fold_index']}].{key}")
        for key in ("invalid_training_keys", "invalid_purged_keys"):
            if checks[-1][key]:
                failed.append(f"fold[{fold['fold_index']}].{key}")
        previous_close = _clock(daily[days[-1]]["close_time"])
    return {"status": "AVAILABLE" if not failed else "UNAVAILABLE", "failed_checks": failed,
            "scope": "RECORDED_FOLD_CLOCKS_AND_KNOWN_OBSERVATION_MEMBERSHIP", "fold_checks": checks}


def _fold_selections(context, candidates, excess, minimum_history_days, reason=None):
    """Every score uses a strict prefix ending before the current full fold."""
    history, previous_ids, rows = [], [], []
    for fold in context["folds"]:
        count = len(history)
        score_reason = reason or ("NO_COMPLETED_HISTORY" if not count else None)
        scores = [{"candidate_index": candidate["candidate_index"], "candidate_id": candidate["candidate_id"],
                   "mean_excess": None if score_reason else _mean(values[:count]),
                   "unavailable_reason": score_reason}
                  for candidate, values in zip(candidates, excess, strict=True)]
        enough = count >= minimum_history_days
        chosen = None if reason or not enough else max(range(len(candidates)), key=lambda index: scores[index]["mean_excess"])
        model_id = None
        if chosen is not None and candidates[chosen]["fold_models"]:
            model_id = candidates[chosen]["fold_models"][fold["fold_index"]]["model"]["model_id"]
        rows.append({"fold_index": fold["fold_index"], "fold_id": fold["fold_id"],
            "training_boundary": fold["training_boundary"], "validation_days": list(fold["validation_days"]),
            "history_days": list(history), "history_day_count": count, "history_fold_ids": list(previous_ids),
            "status": "UNAVAILABLE" if reason else "SELECTED" if enough else "WARMUP",
            "unavailable_reason": reason or (None if enough else "INSUFFICIENT_SELECTION_HISTORY"),
            "scores": scores, "chosen_candidate_index": chosen,
            "chosen_candidate_id": None if chosen is None else candidates[chosen]["candidate_id"],
            "chosen_model_id": model_id})
        history.extend(fold["validation_days"])
        previous_ids.append(fold["fold_id"])
    return rows


def _indexed_account(record):
    execution = record["execution"]
    marks = {}
    for point in execution["ledger"]:
        marks.setdefault(point["trading_day"], []).append(point)
    return {"execution_id": execution["execution_id"],
            "daily": {row["trading_day"]: row for row in execution["daily"]}, "marks": marks}


def _scaled_account(accounts, selections, *, fixed_index=None):
    """Keep every original intraday mark, rebased to this path's daily cash.

    Source accounts are flat at session boundaries with proportional costs.
    Their recorded net returns therefore scale with the new opening capital.
    No additional transfer trade or cost is invented at a fold boundary.
    """
    path, daily, cash, peak = [], [], 1.0, 1.0
    for fold in selections:
        index = fold["chosen_candidate_index"] if fixed_index is None else fixed_index
        account = accounts[index]
        for day in fold["validation_days"]:
            source = account["daily"][day]
            source_open = source["cash_open"]
            closed = _finite(cash * _finite(source["cash_close"] / source_open))
            if min(cash, closed) <= 0:
                raise ArithmeticError("derived daily cash must remain finite and strictly positive")
            common = {"fold_index": fold["fold_index"], "fold_id": fold["fold_id"],
                      "candidate_index": index, "source_execution_id": account["execution_id"]}
            first = len(path)
            for point in account["marks"][day]:
                equity = _finite(cash * _finite(point["equity"] / source_open))
                peak = max(peak, equity)
                path.append({**{key: point[key] for key in ("trading_day", "slot", "timestamp", "phase")},
                    **common, "sequence": len(path), "source_sequence": point["sequence"],
                    "equity": equity, "cash": _finite(cash * _finite(point["cash"] / source_open)),
                    "drawdown": _finite(1 - equity / peak)})
            _reconcile(path[first]["cash"], cash, "derived opening cash")
            _reconcile(path[-1]["cash"], closed, "derived closing cash")
            daily.append({**{key: source[key] for key in ("trading_day", "open_time", "close_time")},
                **common, "cash_open": cash, "cash_close": closed, "return": _finite(closed / cash - 1),
                "source_cash_open": source_open, "source_cash_close": source["cash_close"]})
            cash = closed
    return path, daily


def _join_accounts(path, daily, benchmark_path, benchmark_daily, candidates):
    for point, other in zip(path, benchmark_path, strict=True):
        point.update(candidate_id=candidates[point["candidate_index"]]["candidate_id"],
                     benchmark_source_sequence=other["source_sequence"],
                     benchmark_equity=other["equity"], benchmark_cash=other["cash"],
                     benchmark_drawdown=other["drawdown"])
    for row, other in zip(daily, benchmark_daily, strict=True):
        row.update(candidate_id=candidates[row["candidate_index"]]["candidate_id"],
                   benchmark_cash_open=other["cash_open"], benchmark_cash_close=other["cash_close"],
                   benchmark_return=other["return"], benchmark_source_cash_open=other["source_cash_open"],
                   benchmark_source_cash_close=other["source_cash_close"])
        row["paired_excess"] = _finite(row["return"] - row["benchmark_return"])


def _fold_outcomes(folds, daily, reason):
    by_fold = {}
    for row in daily:
        by_fold.setdefault(row["fold_id"], []).append(row)
    for fold in folds:
        rows = by_fold.get(fold["fold_id"], [])
        failure = reason or fold["unavailable_reason"]
        values = {"cash_open": None, "cash_close": None, "benchmark_cash_open": None, "benchmark_cash_close": None,
                  "compound_return": None, "benchmark_compound_return": None, "mean_daily_excess": None}
        if rows:
            for prefix in ("", "benchmark_"):
                values[prefix + "cash_open"], values[prefix + "cash_close"] = rows[0][prefix + "cash_open"], rows[-1][prefix + "cash_close"]
                values[prefix + "compound_return"] = _finite(values[prefix + "cash_close"] / values[prefix + "cash_open"] - 1)
            values["mean_daily_excess"] = _mean([row["paired_excess"] for row in rows])
        fold["outcome"] = {key: _metric(value, "INITIAL_CASH_UNITS" if "cash_" in key else "RATIO", failure)
                           for key, value in values.items()}


def analyze_intraday_sequential_selection(snapshot: StrategyExperiment, *, cost_index: int = 0,
                                          minimum_history_days: int = 20) -> dict:
    """Evaluate an expanding historical-mean selector on subsequent DEV folds.

    Every recorded member participates. Exact ties use original candidate order;
    negative scores still select the largest value. A short sample is explicitly
    unavailable, and no statistical interval or automatic Freeze is produced.
    """
    if type(snapshot) is not StrategyExperiment:
        raise ValueError("an immutable StrategyExperiment is required")
    _integer(cost_index, "cost_index", 0)
    _integer(minimum_history_days, "minimum_history_days", 1)
    root = snapshot.as_dict()
    if (root["artifact_schema_version"] != INTRADAY_EXPERIMENT_VERSION
            or root["evaluation_mode"] not in ("INTRADAY_COMPARISON", "INTRADAY_DIAGNOSTICS")
            or root["report"]["evaluation_scope"] != "DEVELOPMENT_WALK_FORWARD_ONLY"):
        raise ValueError("sequential selection requires an ordinary saved Q7 DEV comparison or diagnostics experiment")
    report = root["report"]
    if cost_index >= len(report["groups"]):
        raise ValueError("selected cost index is outside the saved experiment")
    context, group = report["context"], report["groups"][cost_index]
    candidates, benchmark = group["results"], group["benchmark"]
    source_sample = _sample_coverage(context)
    source_sample["unevaluated_development_day_count"] = len(context["unevaluated_development_days"])
    basis = _family_basis(root, context, candidates, benchmark)
    causality = _causality(context, candidates, benchmark)
    account_checks, series = [], []
    for index, record in [(-1, benchmark), *enumerate(candidates)]:
        values, failure, explanation = _daily_values(record["execution"], context["folds"],
                                                     None if index == -1 else record["fold_contributions"])
        series.append(values)
        account_checks.append({"account": "BENCHMARK" if index == -1 else "STRATEGY",
            "candidate_index": None if index == -1 else index,
            "execution_id": record["execution"]["execution_id"],
            "status": "AVAILABLE" if failure is None else "UNAVAILABLE", "unavailable_reason": failure, "detail": explanation})
    invalid = [row for row in account_checks if row["status"] == "UNAVAILABLE"]
    reason = ("BASIS_MISMATCH" if not basis["matches"] else "SOURCE_ACCOUNT_UNAVAILABLE" if invalid else
              "RECORDED_CAUSALITY_CHECK_FAILED" if causality["failed_checks"] else
              "GAPPED_EVALUATION_DAYS" if not source_sample["is_contiguous"] else None)
    detail = ("Recorded family basis differs: " + ", ".join(basis["failed_checks"]) if not basis["matches"] else
              "; ".join(f"{row['account']} {row['candidate_index']}: {row['unavailable_reason']}: {row['detail']}" for row in invalid) if invalid else
              ", ".join(causality["failed_checks"]) if causality["failed_checks"] else
              "Unevaluated DEV trading days occur inside the saved evaluation period." if reason else None)
    excess = [None] * len(candidates)
    folds, path, daily, static_references = None, [], [], []
    strategy_summary = benchmark_summary = None
    if reason is None:
        try:
            excess = [tuple(_finite(a - b) for a, b in zip(values, series[0], strict=True)) for values in series[1:]]
            folds = _fold_selections(context, candidates, excess, minimum_history_days)
            selected = [row for row in folds if row["status"] == "SELECTED"]
            if not selected:
                reason, detail = "INSUFFICIENT_HISTORY_FOR_SELECTION", (
                    f"No complete fold follows at least {minimum_history_days} previously evaluated trading days.")
            else:
                accounts = {index: _indexed_account(candidate) for index, candidate in enumerate(candidates)}
                path, daily = _scaled_account(accounts, selected)
                benchmark_path, benchmark_daily = _scaled_account({-1: _indexed_account(benchmark)}, selected, fixed_index=-1)
                strategy_summary = _account_summary(daily, path)
                benchmark_summary = _account_summary(benchmark_daily, benchmark_path)
                _join_accounts(path, daily, benchmark_path, benchmark_daily, candidates)
                for index, candidate in enumerate(candidates):
                    reference_path, reference_daily = _scaled_account(accounts, selected, fixed_index=index)
                    static_references.append({"candidate_index": index, "candidate_id": candidate["candidate_id"],
                        "strategy": candidate["strategy"], **_account_summary(reference_daily, reference_path)})
                _fold_outcomes(folds, daily, None)
        except (ValueError, ArithmeticError) as exc:
            reason = "NUMERIC_OVERFLOW" if isinstance(exc, ArithmeticError) else "RECORDED_SELECTION_ACCOUNT_RECONCILIATION_FAILED"
            detail = str(exc)
            folds = None
    if folds is None:
        folds = _fold_selections(context, candidates, [None] * len(candidates), minimum_history_days, reason)
    if reason is not None:
        path, daily = [], []
        strategy_summary = _account_summary([], [], reason=reason)
        benchmark_summary = _account_summary([], [], reason=reason)
        static_references = [{"candidate_index": index, "candidate_id": candidate["candidate_id"],
            "strategy": candidate["strategy"], **_account_summary([], [], reason=reason)} for index, candidate in enumerate(candidates)]
        _fold_outcomes(folds, [], reason)
    selected = [row for row in folds if row["status"] == "SELECTED"] if reason is None else []
    days = [day for fold in selected for day in fold["validation_days"]]
    warmup = [row for row in folds if row["history_day_count"] < minimum_history_days]
    members = []
    for index, candidate in enumerate(candidates):
        chosen = [row for row in selected if row["chosen_candidate_index"] == index]
        members.append({"candidate_index": index, "candidate_id": candidate["candidate_id"], "strategy": candidate["strategy"],
            "axis_values": candidate["axis_values"], "execution_id": candidate["execution"]["execution_id"],
            "fold_model_ids": [{"fold_id": row["fold_id"], "model_id": row["model"]["model_id"]} for row in candidate["fold_models"]],
            "selected_fold_count": None if reason else len(chosen),
            "selected_day_count": None if reason else sum(len(row["validation_days"]) for row in chosen)})
    result = {"version": INTRADAY_SEQUENTIAL_SELECTION_VERSION, "status": "SUCCESS", "evidence": "RECORDED_LEDGER_DERIVATION",
        "experiment_id": root["experiment_id"], "data_id": root["dataset_id"], "research_id": report["research_id"],
        "context_id": context["context_id"], "evaluation_scope": report["evaluation_scope"],
        "cost_index": cost_index, "cost_group_count": len(report["groups"]), "family_size": len(candidates),
        "family_scope": "SAVED_COST_GROUP_ONLY", "historical_search_coverage": "UNKNOWN", "family_precommitment": "UNKNOWN",
        "algorithm_versions": root["algorithm_versions"], "feature_fields": context["feature_fields"],
        "execution_policy": group["execution_policy"], "benchmark_execution_policy": benchmark["execution"]["policy"],
        "benchmark_execution_id": benchmark["execution"]["execution_id"],
        "selection_rule": {"method": "EXPANDING_PREVIOUS_COMPLETE_FOLDS", "minimum_history_days": minimum_history_days,
            "score": "MEAN_NET_DAILY_EXCESS", "tie_break": "LOWEST_RECORDED_CANDIDATE_INDEX",
            "negative_score_policy": "SELECT_HIGHEST", "selection_frequency": "FOLD_OPEN"},
        "capital": {"method": "SELECTED_FOLD_DAILY_CASH_SCALING", "initial_cash": 1.0,
            "cash_interest_rate": 0.0, "additional_switch_cost": 0.0, "session_boundary": "FLAT"},
        "source_sample": source_sample, "sample": {"sample_count": len(days) if reason is None else None,
            "first_day": days[0] if days else None, "last_day": days[-1] if days else None, "evaluated_days": days,
            "fold_count": len(selected) if reason is None else None, "fold_ids": [row["fold_id"] for row in selected],
            "warmup_days": [day for row in warmup for day in row["validation_days"]], "warmup_fold_count": len(warmup),
            "unavailable_reason": reason}, "basis": basis, "causality": causality,
        "availability": {"status": "AVAILABLE" if reason is None else "UNAVAILABLE", "unavailable_reason": reason,
            "detail": detail, "account_checks": account_checks}, "members": members, "folds": folds,
        "selection_summary": {"selection_count": len(selected) if reason is None else None,
            "switch_count": sum(a["chosen_candidate_index"] != b["chosen_candidate_index"]
                                for a, b in zip(selected, selected[1:])) if reason is None else None},
        "strategy": strategy_summary, "benchmark": benchmark_summary, "static_references": static_references,
        "path": path, "daily_returns": daily}
    result["sequential_selection_id"] = digest(result)
    return result
