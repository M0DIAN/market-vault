"""Strict portable strategy descriptors shared by CLI and desktop editors."""

from __future__ import annotations

from dataclasses import asdict

from ..backtest.models import BacktestRule
from .strategy_comparison import CompositeRuleStrategy, FeatureRuleStrategy, RidgeStrategy, Strategy


def _object(value, fields, label):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError(f"{label} must have exactly these fields: {', '.join(sorted(fields))}")
    return value


def _string(value, label):
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{label} must be a non-empty trimmed string")
    return value


def _rule(spec):
    _object(spec, ("signal_field", "comparator", "threshold"), "rule condition")
    return BacktestRule(_string(spec["signal_field"], "signal_field"),
                        _string(spec["comparator"], "comparator"), spec["threshold"])


def parse_strategy_specs(specs: list[dict], *, allow_composite: bool = True) -> tuple[Strategy, ...]:
    """Decode finite explicit descriptors; no imports, expressions or registry lookup."""
    if type(specs) is not list or not specs:
        raise ValueError("strategies must be a non-empty JSON array")
    strategies = []
    for spec in specs:
        if type(spec) is not dict:
            raise ValueError("strategy must be a JSON object")
        kind = spec.get("kind")
        if kind == "FEATURE_RULE":
            _object(spec, ("kind", "name", "signal_field", "comparator", "threshold"), "feature rule strategy")
            strategies.append(FeatureRuleStrategy(
                _string(spec["name"], "name"), _rule({key: spec[key] for key in
                                                     ("signal_field", "comparator", "threshold")}),
            ))
        elif kind == "RIDGE":
            _object(spec, ("kind", "name", "alpha", "threshold"), "Ridge strategy")
            strategies.append(RidgeStrategy(_string(spec["name"], "name"), spec["alpha"], spec["threshold"]))
        elif kind == "COMPOSITE_RULE" and allow_composite:
            _object(spec, ("kind", "name", "match", "conditions"), "composite rule strategy")
            if type(spec["conditions"]) is not list:
                raise ValueError("conditions must be a JSON array")
            strategies.append(CompositeRuleStrategy(
                _string(spec["name"], "name"), tuple(_rule(rule) for rule in spec["conditions"]),
                _string(spec["match"], "match"),
            ))
        else:
            raise ValueError("unsupported strategy kind for this plan version")
    if len({item.name for item in strategies}) != len(strategies):
        raise ValueError("strategy names must be unique")
    return tuple(strategies)


def strategy_plan_fields(strategy: Strategy) -> dict:
    """Encode plan input, separately from result descriptors and identity fields."""
    if type(strategy) is FeatureRuleStrategy:
        return {"kind": "FEATURE_RULE", "name": strategy.name, **asdict(strategy.rule)}
    if type(strategy) is RidgeStrategy:
        return {"kind": "RIDGE", "name": strategy.name,
                "alpha": strategy.alpha, "threshold": strategy.threshold}
    if type(strategy) is CompositeRuleStrategy:
        return {"kind": "COMPOSITE_RULE", "name": strategy.name, "match": strategy.match,
                "conditions": [asdict(rule) for rule in strategy.conditions]}
    raise ValueError("unsupported strategy type")
