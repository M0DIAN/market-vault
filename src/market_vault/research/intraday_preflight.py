"""Read-only structural preflight of an explicit Q7 comparison plan.

This is not an experiment, an accuracy certificate or a profitability gate.
The existing Q5 loader and Q7 preparation remain the admission authorities.
No fitted model, signal, account or TEST score is produced.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


INTRADAY_PREFLIGHT_VERSION = "market-vault-intraday-preflight-v1"
_EXCLUSIONS = (
    "NO_NEXT_SESSION_OPEN", "AT_OR_AFTER_FORCED_FLAT",
    "BEFORE_ENTRY_WINDOW", "AT_OR_AFTER_STOP_NEW",
)


def _daily_opportunities(report: dict, calendars: dict) -> list[dict]:
    """Count potential fresh entries while flat, not executable trade totals.

    Calendars are the output of Q6's existing complete-grid validation. The
    observation stream comes from this action's strictly reconstructed Q5.
    Neither targets nor hypothetical Long/Flat predictions filter these rows.
    """
    by_day = {day: [] for day in calendars}
    for observation in report["observations"]:
        if observation["trading_day"] in by_day:
            by_day[observation["trading_day"]].append(observation)
    result = []
    for day, calendar in calendars.items():
        observations = by_day[day]
        ready = [row for row in observations if row["status"] == "READY"]
        excluded = dict.fromkeys(_EXCLUSIONS, 0)
        eligible = []
        for row in ready:
            next_slot = row["slot"] + 1
            instant = datetime.fromisoformat(row["decision_time"])
            if next_slot >= calendar["count"]:
                reason = "NO_NEXT_SESSION_OPEN"
            elif next_slot >= calendar["flatten_slot"]:
                reason = "AT_OR_AFTER_FORCED_FLAT"
            elif instant < calendar["first"]:
                reason = "BEFORE_ENTRY_WINDOW"
            elif instant >= calendar["stop"]:
                reason = "AT_OR_AFTER_STOP_NEW"
            else:
                eligible.append(row)
                continue
            excluded[reason] += 1
        result.append({
            "trading_day": day,
            "observation_count": len(observations),
            "ready_observation_count": len(ready),
            "unavailable_observation_count": len(observations) - len(ready),
            "first_ready_decision_time": ready[0]["decision_time"] if ready else None,
            "eligible_entry_observation_count": len(eligible),
            "first_eligible_next_open_time": eligible[0]["decision_time"] if eligible else None,
            "excluded_ready_observations": excluded,
        })
    return result


def analyze_intraday_preflight(plan: dict, *, base: Path | None = None) -> dict:
    """Check one ordinary comparison plan without fitting, executing or saving.

    Invalid source/plan/preparation evidence raises the existing errors. A
    valid preparation with no possible entries or empty learned TRAIN rows
    instead returns BLOCKED with explicit reasons. CHECKED only means these
    structural checks found no blocker; numerical fit and economic validation
    have not run. Existing research behavior and saved artifact identities are
    unchanged, and callers never supply a preverified-data shortcut.
    """
    from ..backtest.intraday import _inputs
    from .intraday_backtest import execution_views, parse_execution_policy
    from .intraday_data import digest
    from .intraday_research import normalize_intraday_research_plan, _prepare_intraday_research

    normalized = normalize_intraday_research_plan(plan, base=base)
    prepared = _prepare_intraday_research(normalized)
    context, report = prepared.context, prepared.report
    sessions, prices = execution_views(report, trading_days=tuple(context["evaluated_days"]))
    policy = parse_execution_policy(normalized["execution"])
    # Reuse Q6's window rounding and complete-price validation, not a second
    # execution-policy implementation. This performs no account simulation.
    _, calendars, _, _ = _inputs(sessions, prices, (), report["interval"], policy)
    days = _daily_opportunities(report, calendars)
    by_day = {row["trading_day"]: row for row in days}
    learned = any(row["kind"] in ("RIDGE", "QUADRATIC_RIDGE") for row in normalized["strategies"])
    blockers = []
    folds = []
    for fold in context["folds"]:
        training_count = len(fold["training_keys"])
        entries = sum(by_day[day]["eligible_entry_observation_count"] for day in fold["validation_days"])
        folds.append({
            "fold_index": fold["fold_index"],
            "training_day_count": len(fold["training_days"]),
            "training_row_count": training_count,
            "purged_training_row_count": len(fold["purged_keys"]),
            "validation_days": fold["validation_days"],
            "ready_validation_observation_count": len(fold["validation_keys"]),
            "eligible_entry_observation_count": entries,
        })
        if learned and training_count == 0:
            blockers.append({"reason": "NO_LEARNED_TRAINING_ROWS", "fold_index": fold["fold_index"]})
    entry_count = sum(row["eligible_entry_observation_count"] for row in days)
    if entry_count == 0:
        blockers.append({"reason": "NO_ELIGIBLE_ENTRY_OBSERVATIONS", "fold_index": None})
    sampling_plan = prepared.data.as_dict()["plan"]
    result = {
        "result_schema_version": INTRADAY_PREFLIGHT_VERSION,
        "status": "BLOCKED" if blockers else "CHECKED",
        "scope": "DEVELOPMENT_STRUCTURAL_PREFLIGHT_ONLY",
        "data_id": prepared.data.data_id,
        "symbol": report["symbol"],
        "interval": report["interval"],
        "context_id": context["context_id"],
        "plan": normalized,
        "sampling": {key: sampling_plan[key]
                     for key in ("preset", "stride_bars", "target_horizon_bars")},
        "feature_window_bars": report["feature_window_bars"],
        "split_day_counts": {key: len(value) for key, value in context["split"].items()},
        "evaluated_days": context["evaluated_days"],
        "unevaluated_development_days": context["unevaluated_development_days"],
        "sessions": days,
        "folds": folds,
        "eligible_entry_observation_count": entry_count,
        "zero_entry_days": [row["trading_day"] for row in days if row["eligible_entry_observation_count"] == 0],
        "zero_entry_folds": [row["fold_index"] for row in folds if row["eligible_entry_observation_count"] == 0],
        "blockers": blockers,
        "not_evaluated": ["MODEL_FIT", "SIGNALS", "ACCOUNT", "TEST_PERFORMANCE",
                          "MARKET_ACCURACY", "FILL_ACHIEVABILITY", "PROFITABILITY"],
        "entry_count_basis": "FRESH_READY_OBSERVATIONS_ELIGIBLE_WHILE_FLAT_NOT_TRADE_COUNT",
    }
    result["preflight_id"] = digest(result)
    return result
