"""Compare explicit rules and fixed-alpha Ridge on common development folds.

Signals differ; the verified execution evidence and Backtest V1 kernel do not.
This is single-symbol, full-notional Long/Flat research with realized equity,
not a marked-to-market portfolio or an independent final TEST evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math

from ..backtest.engine import _candidates, _run_candidates, _trade_id
from ..backtest.models import (
    BACKTEST_ENGINE_VERSION,
    BacktestCosts,
    BacktestMetrics,
    BacktestRule,
    BacktestTrade,
)
from ..cross_day_dataset import VerifiedMultiSourceCrossDayDataset
from ..dataset.encoding import encode_identity
from .experiment import build_experiment_dataset
from .ridge_baseline import RIDGE_BASELINE_VERSION, _predict, evaluate_ridge_baseline
from .trading_authority import validate_execution_safe_experiment
from .walk_forward import WalkForwardPlan, build_walk_forward_plan


STRATEGY_COMPARISON_VERSION = "market-vault-strategy-comparison-v1"
EVALUATION_SCOPE = "WALK_FORWARD_VALIDATION"


class StrategyComparisonError(ValueError):
    """Invalid comparison configuration or inconsistent execution evidence."""


def _name(value: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise StrategyComparisonError("strategy name must be a non-empty trimmed string")
    return value


@dataclass(frozen=True, slots=True)
class FeatureRuleStrategy:
    name: str
    rule: BacktestRule

    def __post_init__(self) -> None:
        _name(self.name)
        if type(self.rule) is not BacktestRule:
            raise StrategyComparisonError("feature rule requires BacktestRule")


@dataclass(frozen=True, slots=True)
class RidgeStrategy:
    name: str
    alpha: float = 1.0
    threshold: float = 0.0

    def __post_init__(self) -> None:
        _name(self.name)
        for field in ("alpha", "threshold"):
            value = getattr(self, field)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise StrategyComparisonError(f"Ridge {field} must be finite numeric")
            object.__setattr__(self, field, 0.0 if value == 0 else float(value))
        if self.alpha <= 0:
            raise StrategyComparisonError("Ridge alpha must be strictly positive")


Strategy = FeatureRuleStrategy | RidgeStrategy


@dataclass(frozen=True, slots=True)
class StrategyComparisonResult:
    strategy: Strategy
    result_id: str
    metrics: BacktestMetrics
    trades: tuple[BacktestTrade, ...]


@dataclass(frozen=True, slots=True)
class StrategyComparisonReport:
    version: str
    comparison_id: str
    engine_version: str
    evaluation_scope: str
    plan: WalkForwardPlan
    costs: BacktestCosts
    validation_sample_keys: tuple[str, ...]
    results: tuple[StrategyComparisonResult, ...]


def _strategy_fields(strategy: Strategy) -> dict:
    if type(strategy) is FeatureRuleStrategy:
        return {
            "name": strategy.name,
            "kind": "FEATURE_RULE",
            "signal_field": strategy.rule.signal_field,
            "comparator": strategy.rule.comparator,
            "threshold": strategy.rule.threshold,
        }
    return {
        "name": strategy.name,
        "kind": "RIDGE",
        "model_version": RIDGE_BASELINE_VERSION,
        "alpha": strategy.alpha,
        "comparator": "GT",
        "threshold": strategy.threshold,
    }


def _common_candidates(dataset, plan: WalkForwardPlan):
    # The union can contain original TRAIN rows and can have gaps. An original
    # Dataset split is not interchangeable with walk-forward validation.
    rows = {}
    for fold in plan.folds:
        for metadata, features, target in zip(
            fold.validation.metadata, fold.validation.X, fold.validation.y, strict=True
        ):
            if metadata.sample_key in rows:
                raise StrategyComparisonError("duplicate walk-forward validation sample")
            rows[metadata.sample_key] = (metadata, features, target)

    evidence_rule = BacktestRule(plan.feature_names[0], "GT", 0.0)
    candidates = {}
    for split in ("TRAIN", "VALIDATION"):
        for candidate in _candidates(dataset, evidence_rule, plan.label_name, split):
            if candidate.sample_key not in rows:
                continue
            if candidate.sample_key in candidates:
                raise StrategyComparisonError("duplicate validation execution evidence")
            metadata, _, target = rows[candidate.sample_key]
            if (
                candidate.code != metadata.code
                or candidate.signal_time != metadata.feature_window_close
                or candidate.exit_time != metadata.actual_label_end_time
                or candidate.gross_return != target
            ):
                raise StrategyComparisonError("validation execution evidence differs from Experiment")
            candidates[candidate.sample_key] = candidate
    if candidates.keys() != rows.keys():
        raise StrategyComparisonError("missing validation execution evidence")
    ordered = tuple(sorted(candidates.values(), key=lambda c: (c.signal_time, c.sample_key)))
    return ordered, rows


def compare_strategies(
    dataset: VerifiedMultiSourceCrossDayDataset,
    *,
    feature_fields: tuple[str, ...],
    return_label: str,
    strategies: tuple[Strategy, ...],
    minimum_train_periods: int,
    validation_periods: int,
    step_periods: int | None = None,
    commission_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> StrategyComparisonReport:
    """Fit Ridge per fold, then simulate each strategy over one common stream.

    Parameters are explicit research choices; no winner is selected, no model
    is refit on TEST, and no output artifact is written. Position/equity state
    continues across validation folds, including gaps between their windows.
    """
    if type(strategies) is not tuple or not strategies:
        raise StrategyComparisonError("strategies must be a non-empty tuple")
    if any(type(item) not in (FeatureRuleStrategy, RidgeStrategy) for item in strategies):
        raise StrategyComparisonError("only FeatureRuleStrategy and RidgeStrategy are supported")
    if len({item.name for item in strategies}) != len(strategies):
        raise StrategyComparisonError("strategy names must be unique")
    if type(feature_fields) is not tuple or not feature_fields:
        raise StrategyComparisonError("feature_fields must be an explicit non-empty tuple")
    costs = BacktestCosts(commission_bps, slippage_bps)
    bundle = build_experiment_dataset(
        dataset, label_field=return_label, feature_fields=feature_fields
    )
    fresh, bundle = validate_execution_safe_experiment(dataset, bundle)
    for strategy in strategies:
        if type(strategy) is FeatureRuleStrategy and strategy.rule.signal_field not in bundle.feature_names:
            raise StrategyComparisonError("rule signal_field must belong to the common Feature projection")
    plan = build_walk_forward_plan(
        bundle,
        minimum_train_periods=minimum_train_periods,
        validation_periods=validation_periods,
        step_periods=step_periods,
    )
    candidates, rows = _common_candidates(fresh, plan)
    sample_keys = tuple(candidate.sample_key for candidate in candidates)
    context_id = encode_identity(STRATEGY_COMPARISON_VERSION + ":context", {
        "engine_version": BACKTEST_ENGINE_VERSION,
        "evaluation_scope": EVALUATION_SCOPE,
        "dataset_id": plan.dataset_id,
        "walk_forward_id": plan.walk_forward_id,
        "return_label": return_label,
        "commission_bps": costs.commission_bps,
        "slippage_bps": costs.slippage_bps,
        "sample_count": len(sample_keys),
        "sample_keys": "".join(sample_keys),
    })

    results = []
    for strategy in strategies:
        if type(strategy) is FeatureRuleStrategy:
            index = plan.feature_names.index(strategy.rule.signal_field)
            scores = {key: value[1][index] for key, value in rows.items()}
            rule = strategy.rule
        else:
            ridge = evaluate_ridge_baseline(plan, alpha=strategy.alpha)
            scores = {}
            for fold, fitted in zip(plan.folds, ridge.folds, strict=True):
                predictions = _predict(
                    fold.validation.X, fitted.intercept, fitted.coefficients
                )
                scores.update(zip(fold.validation.sample_keys, predictions, strict=True))
            # Internal model scores never enter the Dataset's Feature namespace.
            rule = BacktestRule("ridge_prediction", "GT", strategy.threshold)
        scored = tuple(replace(c, signal_value=scores[c.sample_key]) for c in candidates)
        trades, metrics = _run_candidates(scored, rule=rule, costs=costs)
        result_id = encode_identity(STRATEGY_COMPARISON_VERSION + ":strategy", {
            "context_id": context_id,
            **_strategy_fields(strategy),
            "scores_id": encode_identity(STRATEGY_COMPARISON_VERSION + ":scores", {
                c.sample_key: c.signal_value for c in scored
            }),
            "trade_count": len(trades),
            "trades": "".join(_trade_id(trade) for trade in trades),
        })
        results.append(StrategyComparisonResult(strategy, result_id, metrics, trades))
    comparison_id = encode_identity(STRATEGY_COMPARISON_VERSION, {
        "context_id": context_id,
        "strategy_count": len(results),
        "results": "".join(result.result_id for result in results),
    })
    return StrategyComparisonReport(
        STRATEGY_COMPARISON_VERSION, comparison_id, BACKTEST_ENGINE_VERSION,
        EVALUATION_SCOPE, plan, costs, sample_keys, tuple(results),
    )
