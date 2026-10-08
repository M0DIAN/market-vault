"""Finite, explicit development diagnostics over the existing risk authority.

Every requested parameter/cost combination is retained. There is no optimizer,
winner selection, TEST evaluation, separate execution engine or artifact I/O.
"""

from __future__ import annotations

import codecs
from dataclasses import replace
from hashlib import sha256
from itertools import product
import json
import math

from ..backtest.models import BacktestCosts, _finite_number
from ..dataset.cli import _no_duplicate_pairs
from ..strategy_comparison_io import (
    canonical_json, evaluate_comparison_payload, normalized_comparison_plan,
    parse_strategy_comparison_plan_bytes,
)
from .strategy_comparison import (
    EVALUATION_SCOPE, CompositeRuleStrategy, FeatureRuleStrategy, RidgeStrategy,
)
from .strategy_config import _object, _string


STRATEGY_DIAGNOSTICS_VERSION = "market-vault-strategy-diagnostics-v1"
STRATEGY_DIAGNOSTICS_PLAN_VERSION = "market-vault-strategy-diagnostics-plan-v1"
STRATEGY_DIAGNOSTICS_RESULT_VERSION = "market-vault-strategy-diagnostics-result-v1"
MAX_DIAGNOSTIC_EVALUATIONS = 64
_PLAN_FIELDS = {
    "plan_schema_version", "comparison_plan", "strategy_name",
    "parameter_axes", "cost_scenarios",
}


def _list(value, label, *, nonempty=False):
    if type(value) is not list or (nonempty and not value):
        raise ValueError(f"{label} must be a {'non-empty ' if nonempty else ''}JSON array")
    return value


def _number(value, label):
    number = _finite_number(value, label)
    return 0.0 if number == 0 else number


def normalize_parameter_axes(selected, raw_axes) -> list[dict]:
    """Shared finite axes, independent of data and execution cost grammar."""
    raw_axes = _list(raw_axes, "parameter_axes")
    if len(raw_axes) > 2:
        raise ValueError("diagnostics permits at most two parameter axes")
    axes, targets = [], set()
    for raw in raw_axes:
        if type(raw) is not dict:
            raise ValueError("parameter axis must be a JSON object")
        parameter = raw.get("parameter")
        composite = parameter == "condition_threshold"
        _object(raw, {"parameter", "values"} | ({"condition_index"} if composite else set()), "parameter axis")
        index = raw.get("condition_index")
        if composite:
            if (type(selected) is not CompositeRuleStrategy or type(index) is not int
                    or not 0 <= index < len(selected.conditions)):
                raise ValueError("condition_threshold requires a valid zero-based composite condition_index")
        elif parameter == "alpha":
            if type(selected) is not RidgeStrategy:
                raise ValueError("alpha axis requires a Ridge strategy")
        elif parameter == "threshold":
            if type(selected) not in (FeatureRuleStrategy, RidgeStrategy):
                raise ValueError("threshold axis requires a Feature rule or Ridge strategy")
        else:
            raise ValueError("unsupported diagnostic parameter")
        target = (parameter, index)
        if target in targets:
            raise ValueError("diagnostic parameter targets must be unique")
        targets.add(target)
        values = _list(raw["values"], "axis values", nonempty=True)
        if len(values) > MAX_DIAGNOSTIC_EVALUATIONS:
            raise ValueError("diagnostics is limited to 64 evaluations")
        values = [_number(value, "axis value") for value in values]
        if len(set(values)) != len(values):
            raise ValueError("axis values must be unique after numeric normalization")
        if parameter == "alpha" and any(value <= 0 for value in values):
            raise ValueError("Ridge alpha must be strictly positive")
        axes.append({"parameter": parameter, **({"condition_index": index} if composite else {}),
                     "values": values})
    return axes


def parameter_variants(selected, axes) -> tuple[tuple, tuple[tuple[float, ...], ...]]:
    """Preserve explicit axis order and the existing variant naming contract."""
    combinations = tuple(product(*(axis["values"] for axis in axes)))
    variants = []
    for index, values in enumerate(combinations):
        variant = replace(selected, name=f"{selected.name} [{index + 1}]")
        for axis, value in zip(axes, values, strict=True):
            if axis["parameter"] == "condition_threshold":
                conditions = list(variant.conditions)
                position = axis["condition_index"]
                conditions[position] = replace(conditions[position], threshold=value)
                variant = replace(variant, conditions=tuple(conditions))
            elif type(variant) is FeatureRuleStrategy:
                variant = replace(variant, rule=replace(variant.rule, threshold=value))
            else:
                variant = replace(variant, **{axis["parameter"]: value})
        variants.append(variant)
    return tuple(variants), combinations


def normalize_strategy_diagnostics_plan(plan: dict) -> dict:
    """Validate all axes, costs and the finite bound before any Dataset or fit."""
    _object(plan, _PLAN_FIELDS, "diagnostics plan")
    if plan["plan_schema_version"] != STRATEGY_DIAGNOSTICS_PLAN_VERSION:
        raise ValueError("unsupported diagnostics plan_schema_version")
    config = parse_strategy_comparison_plan_bytes(canonical_json(plan["comparison_plan"]))
    name = _string(plan["strategy_name"], "strategy_name")
    selected = next((item for item in config["strategies"] if item.name == name), None)
    if selected is None:
        raise ValueError("diagnostics strategy_name must select an existing strategy")
    rules = ((selected.rule,) if type(selected) is FeatureRuleStrategy else
             selected.conditions if type(selected) is CompositeRuleStrategy else ())
    if any(rule.signal_field not in config["feature_fields"] for rule in rules):
        raise ValueError("diagnostics rule Feature must belong to the common Feature projection")
    axes = normalize_parameter_axes(selected, plan["parameter_axes"])
    raw_costs = _list(plan["cost_scenarios"], "cost_scenarios", nonempty=True)
    if len(raw_costs) * math.prod(len(axis["values"]) for axis in axes) > MAX_DIAGNOSTIC_EVALUATIONS:
        raise ValueError("diagnostics is limited to 64 evaluations")
    costs, seen_costs = [], set()
    for raw in raw_costs:
        _object(raw, {"commission_bps", "slippage_bps"}, "cost scenario")
        cost = BacktestCosts(*(_number(raw[key], key) for key in ("commission_bps", "slippage_bps")))
        pair = (cost.commission_bps, cost.slippage_bps)
        if pair in seen_costs:
            raise ValueError("cost scenarios must be unique after numeric normalization")
        seen_costs.add(pair)
        costs.append(dict(zip(("commission_bps", "slippage_bps"), pair, strict=True)))
    return {
        "plan_schema_version": STRATEGY_DIAGNOSTICS_PLAN_VERSION,
        "comparison_plan": normalized_comparison_plan(config, dataset_build_dir=config["dataset_build_dir"]),
        "strategy_name": name, "parameter_axes": axes, "cost_scenarios": costs,
    }


def parse_strategy_diagnostics_plan_bytes(payload: bytes) -> dict:
    if type(payload) is not bytes or payload.startswith(codecs.BOM_UTF8):
        raise ValueError("diagnostics plan must be UTF-8 bytes without a BOM")
    return normalize_strategy_diagnostics_plan(
        json.loads(payload.decode("utf-8"), object_pairs_hook=_no_duplicate_pairs),
    )


def expand_strategy_diagnostics_plan(plan: dict) -> tuple[dict, tuple[dict, ...], tuple[tuple[float, ...], ...]]:
    """Return detached normalized inputs, actual child plans and ordered values."""
    normalized = normalize_strategy_diagnostics_plan(plan)
    config = parse_strategy_comparison_plan_bytes(canonical_json(normalized["comparison_plan"]))
    selected = next(item for item in config["strategies"] if item.name == normalized["strategy_name"])
    variants, combinations = parameter_variants(selected, normalized["parameter_axes"])
    children = tuple(normalized_comparison_plan(
        {**config, "strategies": tuple(variants), **cost},
        dataset_build_dir=config["dataset_build_dir"],
    ) for cost in normalized["cost_scenarios"])
    return normalized, children, combinations


def fold_trade_contributions(folds: list[dict], result: dict) -> list[dict]:
    """Attribute actual wealth changes to the originating validation sample."""
    ownership, contributions = {}, [[] for _ in folds]
    for index, fold in enumerate(folds):
        for key in fold["validation_sample_keys"]:
            if key in ownership:
                raise ValueError("fold validation sample keys must be unique")
            ownership[key] = index
    seen = set()
    for trade in result["trades"]:
        key = trade["sample_key"]
        if key not in ownership or key in seen:
            raise ValueError("trade must belong to one unique originating validation sample")
        seen.add(key)
        contributions[ownership[key]].append(trade["equity_after"] - trade["equity_before"])
    rows = [{
        "fold_index": fold["fold_index"], "fold_id": fold["fold_id"],
        "validation_start_time": fold["validation_start_time"],
        "validation_end_time": fold["validation_end_time"],
        "validation_sample_count": len(fold["validation_sample_keys"]),
        "trade_count": len(values), "cash_contribution": math.fsum(values),
    } for fold, values in zip(folds, contributions, strict=True)]
    # Reconcile account wealth using the existing equity ledger tolerance.
    # Relative error on a near-zero return would reject otherwise valid ledgers.
    if not math.isclose(1.0 + math.fsum(row["cash_contribution"] for row in rows),
                        1.0 + result["metrics"]["total_return"], rel_tol=1e-11, abs_tol=1e-12):
        raise ValueError("fold cash contributions do not reconcile with the continuous account")
    return rows


def diagnostic_candidate_records(report: dict, values: tuple[tuple[float, ...], ...],
                                 reference_report: dict) -> list[dict]:
    """Derive every candidate mapping, cost difference and fold contribution."""
    if len(report["results"]) != len(values) or len(reference_report["results"]) != len(values):
        raise ValueError("diagnostics candidate coverage differs from parameter combinations")
    records = []
    for index, (result, axis_values, curve, reference) in enumerate(zip(
        report["results"], values, report["equity"]["results"], reference_report["results"], strict=True,
    )):
        rows = fold_trade_contributions(report["folds"], result)
        if not math.isclose(1.0 + math.fsum(row["cash_contribution"] for row in rows),
                            curve["final_equity"], rel_tol=1e-11, abs_tol=1e-12):
            raise ValueError("fold contributions differ from final marked equity")
        records.append({
            "variant_index": index, "axis_values": list(axis_values),
            "strategy_result_id": result["result_id"],
            "return_change_from_first_cost": result["metrics"]["total_return"] - reference["metrics"]["total_return"],
            "fold_contributions": rows,
        })
    return records


def diagnostic_common_context(report: dict) -> bytes:
    """Costs and parameter values cannot change the shared research window."""
    return canonical_json({
        **{key: report[key] for key in (
            "dataset_id", "walk_forward_id", "feature_names", "return_label",
            "minimum_train_periods", "validation_periods", "step_periods",
            "held_out_test_sample_count", "validation_sample_keys", "folds",
        )},
        "valuation": {key: report["equity"][key] for key in
                      ("interval", "start_time", "end_time", "price_evidence_id")},
    })


def diagnostics_report_identity(report: dict) -> str:
    return sha256(canonical_json({key: value for key, value in report.items()
                                 if key != "diagnostics_id"})).hexdigest()


def run_strategy_diagnostics(dataset, *, plan: dict) -> dict:
    """Evaluate the complete bounded grid once per cost group; never pick a winner."""
    normalized, children, values = expand_strategy_diagnostics_plan(plan)
    groups = []
    context = None
    for index, child in enumerate(children):
        config = parse_strategy_comparison_plan_bytes(canonical_json(child))
        config.pop("dataset_build_dir")
        report = evaluate_comparison_payload(dataset, config, "RISK")
        current = diagnostic_common_context(report)
        if context is not None and current != context:
            raise ValueError("diagnostic cost groups must share the same Dataset, folds and prices")
        context = current
        reference = groups[0]["report"] if groups else report
        groups.append({
            "cost_index": index, "comparison_plan": child, "report": report,
            "candidates": diagnostic_candidate_records(report, values, reference),
        })
    output = {
        "result_schema_version": STRATEGY_DIAGNOSTICS_RESULT_VERSION, "status": "SUCCESS",
        "version": STRATEGY_DIAGNOSTICS_VERSION, "dataset_id": groups[0]["report"]["dataset_id"],
        "evaluation_scope": EVALUATION_SCOPE,
        "plan_sha256": sha256(canonical_json(normalized)).hexdigest(),
        "evaluation_count": len(children) * len(values), "variant_count": len(values),
        "groups": groups,
    }
    output["diagnostics_id"] = diagnostics_report_identity(output)
    return output
