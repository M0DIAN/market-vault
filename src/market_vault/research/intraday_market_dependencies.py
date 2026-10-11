"""Recorded Q5 Feature windows and target dependencies on external bar evidence.

The full Q46 market report is captured once. Dependencies reference its row
indices; they never replace prices, delete observations, recompute an external
target, or assert that a Feature, fitted model, or strategy return changed.
"""

from __future__ import annotations

from datetime import timedelta
from itertools import chain
from pathlib import Path

from ..quality import market_data_comparison as comparison
from . import intraday_market_evidence as market
from .intraday_data import IntradayDataset, digest, load_intraday_dataset, verify_intraday_dataset


INTRADAY_MARKET_DEPENDENCIES_VERSION = "market-vault-intraday-market-dependencies-v1"


def _field_status(row, field):
    compared = row["differences"].get(field)
    if compared is None:
        return row["status"]
    return "MATCH" if compared["within_tolerance"] else "DIFFERENT"


def _support_counts(rows, indices):
    result = {"bar_links": 0, "local_present_links": 0, "local_missing_links": 0,
              "comparison_status_counts": dict.fromkeys(market.SLOT_STATUSES, 0),
              "field_comparison_counts": {field: {"matched_links": 0, "different_links": 0,
                                                   "unassessable_links": 0}
                                          for field in comparison.VALUE_FIELDS}}
    for index in indices:
        row = rows[index]
        result["bar_links"] += 1
        result["local_present_links" if row["local_state"] == "PRESENT" else "local_missing_links"] += 1
        result["comparison_status_counts"][row["status"]] += 1
        for field in comparison.VALUE_FIELDS:
            status = _field_status(row, field)
            key = "matched_links" if status == "MATCH" else "different_links" if status == "DIFFERENT" else "unassessable_links"
            result["field_comparison_counts"][field][key] += 1
    return result


def _endpoints(target, observation, rows, by_version, horizon):
    result = {}
    for role, field, expected_slot in (("entry", "open", observation["slot"] + 1),
                                      ("exit", "close", observation["slot"] + horizon)):
        version = target[role + "_row_version_id"]
        index = by_version.get(version)
        if index is None:
            raise ValueError("COMPLETE target endpoint is absent from the verified Q5 price grid")
        row = rows[index]
        if (row["trading_day"] != observation["trading_day"] or row["slot"] != expected_slot
                or row["local_state"] != "PRESENT"):
            raise ValueError("COMPLETE target endpoint differs from its actual Q5 session/slot")
        expected_clock = observation["decision_time"] if role == "entry" else target["actual_label_end_time"]
        actual_clock = row["start"] if role == "entry" else row["end"]
        if comparison.parse_utc(expected_clock) != comparison.parse_utc(actual_clock):
            raise ValueError("COMPLETE target endpoint clock differs from its actual Q5 evidence")
        result[role] = {"bar_index": index, "row_version_id": version, "field": field,
                        "evidence_status": _field_status(row, field)}
    return result


def _observation_record(index, observation, target, session, horizon, rows, by_slot, by_version, step):
    day = observation["trading_day"]
    opening = comparison.parse_utc(session["open_time"])
    start = comparison.parse_utc(observation["window_start"])
    end = comparison.parse_utc(observation["decision_time"])
    first, stop = (start - opening) // step, (end - opening) // step
    if (not 0 <= first < stop <= session["bar_count"] or opening + first * step != start
            or opening + stop * step != end):
        raise ValueError("recorded Feature window differs from its verified Q5 session grid")
    feature_indices = [by_slot[day, slot] for slot in range(first, stop)]
    result = {"observation_index": index, "observation_key": observation["observation_key"],
              "trading_day": day, "slot": observation["slot"], "decision_time": observation["decision_time"],
              "observation_status": observation["status"], "observation_reason": observation["reason"],
              "feature_value_ids": observation["feature_value_ids"],
              "feature_support": {"window_start": observation["window_start"],
                                  "window_end": observation["decision_time"], "bar_indices": feature_indices,
                                  "counts": _support_counts(rows, feature_indices)}, "target": None}
    if target is None:
        return result
    remaining = session["bar_count"] - observation["slot"] - 1
    count = min(horizon, remaining)
    # Q5 allows a very large H. Only the remaining same-session grid can be
    # represented by bar indices; the rest is an integer shortfall, never an
    # H-sized list or a fabricated continuation into a later session.
    future_indices = [by_slot[day, slot] for slot in range(observation["slot"] + 1,
                                                         observation["slot"] + count + 1)]
    result["target"] = {"status": target["status"], "reason": target["reason"], "value": target["value"],
                        "actual_label_end_time": target["actual_label_end_time"],
                        "completeness_support": {"bar_indices": future_indices,
                                                 "same_session_support_count": count,
                                                 "session_end_shortfall": horizon - count,
                                                 "counts": _support_counts(rows, future_indices)},
                        "endpoints": _endpoints(target, observation, rows, by_version, horizon)
                                     if target["status"] == "COMPLETE" else None}
    return result


def _summary(records, rows, horizon):
    targets = [row["target"] for row in records if row["target"] is not None]
    endpoints = [endpoint for target in targets if target["endpoints"] is not None
                 for endpoint in target["endpoints"].values()]
    complete = [target for target in targets if target["status"] == "COMPLETE"]
    return {"observation_count": len(records),
            "observation_status_counts": {status: sum(row["observation_status"] == status for row in records)
                                          for status in ("READY", "UNAVAILABLE")},
            "target_record_count": len(targets), "no_target_observation_count": len(records) - len(targets),
            "target_status_counts": {status: sum(target["status"] == status for target in targets)
                                     for status in ("COMPLETE", "INCOMPLETE")},
            "target_reason_counts": {reason: sum(target["reason"] == reason for target in targets)
                                     for reason in ("SESSION_END", "MISSING_PRICE")},
            "feature_support": _support_counts(rows, chain.from_iterable(
                row["feature_support"]["bar_indices"] for row in records)),
            "target_completeness_support": _support_counts(rows, chain.from_iterable(
                target["completeness_support"]["bar_indices"] for target in targets)),
            "target_session_end_shortfall": sum(target["completeness_support"]["session_end_shortfall"] for target in targets),
            "target_declared_horizon_links": 0 if horizon is None else len(targets) * horizon,
            "target_endpoint_count": len(endpoints),
            "target_endpoint_status_counts": {status: sum(endpoint["evidence_status"] == status for endpoint in endpoints)
                                              for status in market.SLOT_STATUSES},
            "complete_targets_with_endpoint_price_disagreement": sum(
                any(endpoint["evidence_status"] == "DIFFERENT" for endpoint in target["endpoints"].values())
                for target in complete),
            "complete_targets_without_full_endpoint_comparison": sum(
                any(endpoint["evidence_status"] not in ("MATCH", "DIFFERENT")
                    for endpoint in target["endpoints"].values()) for target in complete)}


def _analyze_verified(snapshot: IntradayDataset, normalized_plan: dict) -> dict:
    """Derive dependencies after the caller has strictly verified Q5 once."""
    evidence = market._analyze_verified(snapshot, normalized_plan)
    root = snapshot.as_dict()
    source, rows = root["report"], evidence["rows"]
    by_slot = {(row["trading_day"], row["slot"]): index for index, row in enumerate(rows)}
    by_version = {row["row_version_id"]: index for index, row in enumerate(rows) if row["row_version_id"] is not None}
    sessions = {row["trading_day"]: row for row in source["sessions"]}
    targets = {row["observation_key"]: row for row in source["targets"]}
    horizon = root["plan"]["target_horizon_bars"]
    step = timedelta(minutes=comparison.INTERVAL_MINUTES[source["interval"]])
    records = [_observation_record(index, observation, None if horizon is None else targets[observation["observation_key"]],
                                   sessions[observation["trading_day"]], horizon, rows, by_slot, by_version, step)
               for index, observation in enumerate(source["observations"])]
    result = {"version": INTRADAY_MARKET_DEPENDENCIES_VERSION, "status": "REPORTED",
              "evaluation_scope": "Q5_DEPENDENCY_EVIDENCE_ONLY", "market_accuracy_certified": False,
              "data_id": root["data_id"], "market_evidence_id": evidence["market_evidence_id"],
              "market_evidence": evidence,
              "sampling": {key: root["plan"][key] for key in ("preset", "stride_bars", "target_horizon_bars")},
              "feature_names": source["feature_names"], "feature_window_bars": source["feature_window_bars"],
              "summary": _summary(records, rows, horizon), "observations": records,
              "limitations": ["REPORTED means dependency mapping completed; market evidence retains its own availability and diagnostics.",
                              "Feature support is conservative whole-window exposure, not formula-level numerical sensitivity.",
                              "Target completeness support describes required bar presence; original status and reason remain unchanged.",
                              "Only COMPLETE targets have actual entry-open and exit-close endpoint evidence.",
                              "Endpoint price disagreement does not prove a changed target return; changes can cancel in the ratio.",
                              "PRESENT means admitted to Q5, independently of Q44 comparison validity.",
                              "Support counts measure dependency links, not independent samples or unique bars.",
                              "Complete-target disagreement and incomplete-comparison counts can overlap across their two endpoints.",
                              "No prices, Feature values, labels or samples are changed; no model is fitted and no strategy effect is computed."]}
    return {**result, "market_dependencies_id": digest(result)}


def analyze_intraday_market_dependencies(data: IntradayDataset | str | Path, plan: dict, *,
                                         base: str | Path | None = None) -> dict:
    """Verify Q5 once, capture Q46 once, and retain all original observations."""
    normalized = market.parse_intraday_market_evidence_plan(plan, base=base)
    snapshot = verify_intraday_dataset(data) if type(data) is IntradayDataset else load_intraday_dataset(data)
    return _analyze_verified(snapshot, normalized)


def run_intraday_market_dependencies(data_path: str | Path, manifest_path: str | Path) -> dict:
    """Read the existing Q46 manifest; relative references resolve beside it."""
    path = Path(manifest_path).absolute()
    return analyze_intraday_market_dependencies(data_path, comparison.read_json_file(path), base=path.parent)
