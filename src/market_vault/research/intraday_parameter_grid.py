"""Describe an existing finite DEV parameter grid without running new trials."""

from __future__ import annotations

from fractions import Fraction

from .intraday_data import digest
from .intraday_experiment import INTRADAY_EXPERIMENT_VERSION
from .intraday_risk_diagnostics import _available as _risk_available
from .intraday_saved_comparison import _basis, _metric, _metric_rows, _selected_from_root
from .strategy_experiment import StrategyExperiment


INTRADAY_PARAMETER_GRID_VERSION = "market-vault-intraday-parameter-grid-v1"
PARAMETER_GRID_METRICS = ("total_return", "observed_max_drawdown", "trade_count",
                          "worst_fold_return", "median_fold_return", "best_fold_return")


def _candidate_metric(candidate, folds, metric):
    if metric in PARAMETER_GRID_METRICS[:3]:
        return _metric(candidate["execution"]["metrics"][metric], "COUNT" if metric == "trade_count" else "RATIO")
    available = _risk_available(candidate["execution"], folds, candidate["fold_contributions"])
    if available["status"] != "AVAILABLE":
        return _metric(None, "RATIO", available["unavailable_reason"], "RECORDED_LEDGER_DERIVATION")
    value = available["report"]["fold_diagnostics"]["summary"][metric]
    return _metric(value["value"], value["unit"], value["unavailable_reason"], "RECORDED_LEDGER_DERIVATION")


def _neighbors(axes, cells, center_index):
    center = cells[center_index]["axis_values"]
    positions = {tuple(cell["axis_values"]): cell["candidate_index"] for cell in cells}
    result = []
    for axis_index, axis in enumerate(axes):
        lower = [value for value in axis["values"] if value < center[axis_index]]
        higher = [value for value in axis["values"] if value > center[axis_index]]
        for direction, value in (("LOWER", max(lower) if lower else None), ("HIGHER", min(higher) if higher else None)):
            if value is None:
                continue
            coordinate = list(center)
            coordinate[axis_index] = value
            result.append((axis_index, direction, positions[tuple(coordinate)]))
    return result


def _summary(neighbors, unit):
    matching = [row for row in neighbors if row["basis_matches"]]
    values = sorted(row["metric"]["value"] for row in matching if row["metric"]["value"] is not None)
    # An exact midpoint of the two finite input values cannot overflow or
    # underflow merely because their floating-point sum/difference would.
    median = (float((Fraction(values[(len(values) - 1) // 2]) + Fraction(values[len(values) // 2])) / 2)
              if values else None)
    reason = ("NO_NEIGHBORS" if not neighbors else "NO_MATCHING_BASIS" if not matching
              else "NO_AVAILABLE_NEIGHBOR_METRICS" if not values else None)
    return {"population": "AXIS_NEIGHBORS_EXCLUDING_CENTER", "neighbor_count": len(neighbors),
            "basis_matching_count": len(matching), "available_count": len(values),
            "minimum": values[0] if values else None, "median": median,
            "maximum": values[-1] if values else None, "unit": unit, "unavailable_reason": reason}


def analyze_intraday_parameter_grid(snapshot: StrategyExperiment, *, cost_index: int = 0,
                                   center_candidate_index: int = 0, metric: str = "total_return") -> dict:
    """Describe one saved diagnostic grid and its explicit center's neighbors.

    Decode the already validated immutable snapshot once. Complete Q11 basis
    checks retain all four candidate/benchmark raw projections; Q12 supplies
    fold metrics with its original per-execution availability constraints.
    """
    if type(snapshot) is not StrategyExperiment:
        raise ValueError("an immutable StrategyExperiment is required")
    if any(type(value) is not int or value < 0 for value in (cost_index, center_candidate_index)):
        raise ValueError("cost_index and center_candidate_index must be nonnegative integers")
    if type(metric) is not str or metric not in PARAMETER_GRID_METRICS:
        raise ValueError("unsupported parameter-grid metric")
    root = snapshot.as_dict()
    report = root["report"]
    if (root["artifact_schema_version"] != INTRADAY_EXPERIMENT_VERSION
            or root["evaluation_mode"] != "INTRADAY_DIAGNOSTICS"
            or report["evaluation_scope"] != "DEVELOPMENT_WALK_FORWARD_ONLY"):
        raise ValueError("parameter grid requires an ordinary saved Q7 DEV INTRADAY_DIAGNOSTICS experiment")
    groups = report["groups"]
    if cost_index >= len(groups) or center_candidate_index >= len(groups[cost_index]["results"]):
        raise ValueError("selected cost/center candidate index is outside the saved diagnostics")
    axes = [{"axis_index": index, **axis} for index, axis in enumerate(root["plan"]["parameter_axes"])]
    group, folds = groups[cost_index], report["context"]["folds"]
    cells = [{"candidate_index": candidate["candidate_index"], "candidate_id": candidate["candidate_id"],
              "strategy_name": candidate["strategy"]["name"], "axis_values": list(candidate["axis_values"]),
              "metric": _candidate_metric(candidate, folds, metric)} for candidate in group["results"]]
    center = cells[center_candidate_index]
    # Selection and shared-basis helpers consume the same detached root. Never
    # re-create or decode a whole experiment for an individual grid cell.
    selected_center = _selected_from_root(root, cost_index, center_candidate_index)
    neighbors = []
    for axis_index, direction, candidate_index in _neighbors(axes, cells, center_candidate_index):
        cell = cells[candidate_index]
        checks = _basis(selected_center, _selected_from_root(root, cost_index, candidate_index))
        failed = [row["key"] for row in checks if not row["matches"]]
        difference = _metric_rows({metric: center["metric"]}, {metric: cell["metric"]},
                                  "BASIS_MISMATCH" if failed else None)[0]["delta"]
        neighbors.append({"axis_index": axis_index, "direction": direction, **cell,
                          "delta": difference, "basis_matches": not failed, "failed_basis_checks": failed})
    result = {"version": INTRADAY_PARAMETER_GRID_VERSION, "status": "SUCCESS", "evidence": "RECORDED_LEDGER_DERIVATION",
              "experiment_id": root["experiment_id"], "data_id": root["dataset_id"], "evaluation_scope": report["evaluation_scope"],
              "axes": axes,
              "cost_scenarios": [{"cost_index": index, "execution_policy": value["execution_policy"],
                                  "candidate_count": len(value["results"])} for index, value in enumerate(groups)],
              "selection": {"cost_index": cost_index, "center_candidate_index": center_candidate_index,
                            "center_candidate_id": center["candidate_id"], "metric": metric},
              "cells": cells, "neighbors": neighbors, "neighborhood_summary": _summary(neighbors, center["metric"]["unit"])}
    result["grid_id"] = digest(result)
    return result
