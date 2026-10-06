"""Read-only final Ridge research evaluation report V1.

This layer compares two already-frozen permanent TEST trading evaluations for
the same final Ridge model:

- the historical fixed rule: predicted return > 0
- the validation-selected trading threshold

It performs no model fitting, alpha selection, threshold search, trade
re-evaluation, Dataset access, or winner selection.  It only revalidates the
identity-bearing inputs and reports deterministic metric deltas.

The validation threshold-selection result is required explicitly so the report
does not merely trust threshold identifiers copied into the selected TEST
trading result.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
import re

from ..backtest.models import BacktestCosts
from ..dataset.encoding import encode_identity
from .ridge_final_test import (
    RidgeFinalTestError,
    RidgeFinalTestResult,
)
from .ridge_final_trading import (
    RIDGE_FINAL_TRADING_SIGNAL_RULE,
    RidgeFinalTradingError,
    RidgeFinalTradingMetrics,
    RidgeFinalTradingResult,
)
from .ridge_selected_final_trading import (
    RIDGE_SELECTED_FINAL_TRADING_SIGNAL_RULE,
    RidgeSelectedFinalTradingError,
    RidgeSelectedFinalTradingResult,
)
from .ridge_trading_selection import (
    RidgeTradingThresholdSelectionError,
    RidgeTradingThresholdSelectionResult,
)


RIDGE_FINAL_EVALUATION_VERSION = "market-vault-ridge-final-evaluation-v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RidgeFinalEvaluationError(ValueError):
    """Fail-closed frozen TEST comparison error."""


def _identity(value: str, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise RidgeFinalEvaluationError(
            f"{label} must be a lowercase SHA-256 identity"
        )
    return value


def _finite(value, label: str) -> float:
    if type(value) is bool or not isinstance(value, (int, float)):
        raise RidgeFinalEvaluationError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise RidgeFinalEvaluationError(f"{label} must be finite")
    return 0.0 if number == 0.0 else number


def _optional_finite(value, label: str) -> float | None:
    if value is None:
        return None
    return _finite(value, label)


def _metrics_id(prefix: str, metrics: RidgeFinalTradingMetrics) -> str:
    return encode_identity(
        prefix,
        {
            "candidate_count": metrics.candidate_count,
            "signal_count": metrics.signal_count,
            "overlap_skipped_count": metrics.overlap_skipped_count,
            "trade_count": metrics.trade_count,
            "gross_total_return": metrics.gross_total_return,
            "total_return": metrics.total_return,
            "realized_max_drawdown": metrics.realized_max_drawdown,
            "win_rate": metrics.win_rate,
            "average_trade_return": metrics.average_trade_return,
            "profit_factor": metrics.profit_factor,
            "average_signal_to_exit_seconds": (
                metrics.average_signal_to_exit_seconds
            ),
        },
    )


@dataclass(frozen=True, slots=True)
class RidgeFinalEvaluationDelta:
    signal_count: int
    overlap_skipped_count: int
    trade_count: int
    gross_total_return: float
    total_return: float
    realized_max_drawdown: float
    win_rate: float
    average_trade_return: float
    profit_factor: float | None
    average_signal_to_exit_seconds: float

    def __post_init__(self) -> None:
        for name in (
            "signal_count",
            "overlap_skipped_count",
            "trade_count",
        ):
            if type(getattr(self, name)) is not int:
                raise RidgeFinalEvaluationError(
                    f"{name} delta must be an integer"
                )
        for name in (
            "gross_total_return",
            "total_return",
            "realized_max_drawdown",
            "win_rate",
            "average_trade_return",
            "average_signal_to_exit_seconds",
        ):
            object.__setattr__(
                self,
                name,
                _finite(getattr(self, name), f"{name} delta"),
            )
        object.__setattr__(
            self,
            "profit_factor",
            _optional_finite(
                self.profit_factor,
                "profit_factor delta",
            ),
        )


@dataclass(frozen=True, slots=True)
class RidgeFinalEvaluationReport:
    version: str
    report_id: str
    final_test_id: str
    model_id: str
    ridge_selection_id: str
    walk_forward_id: str
    dataset_id: str
    feature_names: tuple[str, ...]
    label_name: str
    selected_alpha: float
    test_count: int
    test_mae: float
    test_rmse: float
    test_r2: float | None
    costs: BacktestCosts
    fixed_signal_rule: str
    selected_signal_rule: str
    selected_threshold: float
    threshold_selection_id: str
    selected_candidate_id: str
    fixed_trading_id: str
    selected_trading_id: str
    fixed_metrics: RidgeFinalTradingMetrics
    selected_metrics: RidgeFinalTradingMetrics
    delta: RidgeFinalEvaluationDelta

    def __post_init__(self) -> None:
        if self.version != RIDGE_FINAL_EVALUATION_VERSION:
            raise RidgeFinalEvaluationError(
                "unsupported Ridge final evaluation version"
            )
        for name in (
            "report_id",
            "final_test_id",
            "model_id",
            "ridge_selection_id",
            "walk_forward_id",
            "dataset_id",
            "threshold_selection_id",
            "selected_candidate_id",
            "fixed_trading_id",
            "selected_trading_id",
        ):
            _identity(getattr(self, name), name)
        if (
            type(self.feature_names) is not tuple
            or not self.feature_names
            or not all(type(name) is str and name for name in self.feature_names)
            or len(self.feature_names) != len(set(self.feature_names))
        ):
            raise RidgeFinalEvaluationError(
                "feature_names must be a unique non-empty tuple"
            )
        if type(self.label_name) is not str or not self.label_name:
            raise RidgeFinalEvaluationError("label_name must be non-empty")
        alpha = _finite(self.selected_alpha, "selected_alpha")
        if alpha <= 0.0:
            raise RidgeFinalEvaluationError(
                "selected_alpha must be strictly positive"
            )
        object.__setattr__(self, "selected_alpha", alpha)
        if type(self.test_count) is not int or self.test_count <= 0:
            raise RidgeFinalEvaluationError("test_count must be positive")
        mae = _finite(self.test_mae, "test_mae")
        rmse = _finite(self.test_rmse, "test_rmse")
        if mae < 0.0 or rmse < 0.0:
            raise RidgeFinalEvaluationError(
                "TEST MAE/RMSE must be non-negative"
            )
        object.__setattr__(self, "test_mae", mae)
        object.__setattr__(self, "test_rmse", rmse)
        object.__setattr__(
            self,
            "test_r2",
            _optional_finite(self.test_r2, "test_r2"),
        )
        if type(self.costs) is not BacktestCosts:
            raise RidgeFinalEvaluationError("exact BacktestCosts required")
        if self.fixed_signal_rule != RIDGE_FINAL_TRADING_SIGNAL_RULE:
            raise RidgeFinalEvaluationError(
                "invalid fixed-zero signal rule"
            )
        if (
            self.selected_signal_rule
            != RIDGE_SELECTED_FINAL_TRADING_SIGNAL_RULE
        ):
            raise RidgeFinalEvaluationError(
                "invalid validation-selected signal rule"
            )
        object.__setattr__(
            self,
            "selected_threshold",
            _finite(self.selected_threshold, "selected_threshold"),
        )
        if type(self.fixed_metrics) is not RidgeFinalTradingMetrics:
            raise RidgeFinalEvaluationError(
                "exact fixed RidgeFinalTradingMetrics required"
            )
        if type(self.selected_metrics) is not RidgeFinalTradingMetrics:
            raise RidgeFinalEvaluationError(
                "exact selected RidgeFinalTradingMetrics required"
            )
        if type(self.delta) is not RidgeFinalEvaluationDelta:
            raise RidgeFinalEvaluationError(
                "exact RidgeFinalEvaluationDelta required"
            )
        if (
            self.fixed_metrics.candidate_count != self.test_count
            or self.selected_metrics.candidate_count != self.test_count
        ):
            raise RidgeFinalEvaluationError(
                "trading candidate counts differ from final TEST count"
            )
        expected_delta = _delta(
            self.fixed_metrics,
            self.selected_metrics,
        )
        if self.delta != expected_delta:
            raise RidgeFinalEvaluationError(
                "reported deltas differ from frozen trading metrics"
            )
        expected = _report_id(
            final_test_id=self.final_test_id,
            model_id=self.model_id,
            ridge_selection_id=self.ridge_selection_id,
            walk_forward_id=self.walk_forward_id,
            dataset_id=self.dataset_id,
            feature_names=self.feature_names,
            label_name=self.label_name,
            selected_alpha=self.selected_alpha,
            test_count=self.test_count,
            test_mae=self.test_mae,
            test_rmse=self.test_rmse,
            test_r2=self.test_r2,
            costs=self.costs,
            selected_threshold=self.selected_threshold,
            threshold_selection_id=self.threshold_selection_id,
            selected_candidate_id=self.selected_candidate_id,
            fixed_trading_id=self.fixed_trading_id,
            selected_trading_id=self.selected_trading_id,
            fixed_metrics=self.fixed_metrics,
            selected_metrics=self.selected_metrics,
            delta=self.delta,
        )
        if self.report_id != expected:
            raise RidgeFinalEvaluationError(
                "report_id differs from report content"
            )


def _delta(
    fixed: RidgeFinalTradingMetrics,
    selected: RidgeFinalTradingMetrics,
) -> RidgeFinalEvaluationDelta:
    profit_delta = (
        None
        if fixed.profit_factor is None or selected.profit_factor is None
        else selected.profit_factor - fixed.profit_factor
    )
    return RidgeFinalEvaluationDelta(
        selected.signal_count - fixed.signal_count,
        selected.overlap_skipped_count - fixed.overlap_skipped_count,
        selected.trade_count - fixed.trade_count,
        selected.gross_total_return - fixed.gross_total_return,
        selected.total_return - fixed.total_return,
        (
            selected.realized_max_drawdown
            - fixed.realized_max_drawdown
        ),
        selected.win_rate - fixed.win_rate,
        selected.average_trade_return - fixed.average_trade_return,
        profit_delta,
        (
            selected.average_signal_to_exit_seconds
            - fixed.average_signal_to_exit_seconds
        ),
    )


def _feature_names_digest(feature_names: tuple[str, ...]) -> str:
    framed = "".join(f"{len(name)}:{name}" for name in feature_names)
    return encode_identity(
        "market-vault-ridge-final-evaluation-feature-names-v1",
        {
            "count": len(feature_names),
            "members": framed,
        },
    )


def _delta_id(delta: RidgeFinalEvaluationDelta) -> str:
    return encode_identity(
        "market-vault-ridge-final-evaluation-delta-v1",
        {
            "signal_count": delta.signal_count,
            "overlap_skipped_count": delta.overlap_skipped_count,
            "trade_count": delta.trade_count,
            "gross_total_return": delta.gross_total_return,
            "total_return": delta.total_return,
            "realized_max_drawdown": delta.realized_max_drawdown,
            "win_rate": delta.win_rate,
            "average_trade_return": delta.average_trade_return,
            "profit_factor": delta.profit_factor,
            "average_signal_to_exit_seconds": (
                delta.average_signal_to_exit_seconds
            ),
        },
    )


def _report_id(
    *,
    final_test_id: str,
    model_id: str,
    ridge_selection_id: str,
    walk_forward_id: str,
    dataset_id: str,
    feature_names: tuple[str, ...],
    label_name: str,
    selected_alpha: float,
    test_count: int,
    test_mae: float,
    test_rmse: float,
    test_r2: float | None,
    costs: BacktestCosts,
    selected_threshold: float,
    threshold_selection_id: str,
    selected_candidate_id: str,
    fixed_trading_id: str,
    selected_trading_id: str,
    fixed_metrics: RidgeFinalTradingMetrics,
    selected_metrics: RidgeFinalTradingMetrics,
    delta: RidgeFinalEvaluationDelta,
) -> str:
    return encode_identity(
        RIDGE_FINAL_EVALUATION_VERSION,
        {
            "final_test_id": final_test_id,
            "model_id": model_id,
            "ridge_selection_id": ridge_selection_id,
            "walk_forward_id": walk_forward_id,
            "dataset_id": dataset_id,
            "feature_names_digest": _feature_names_digest(feature_names),
            "label_name": label_name,
            "selected_alpha": selected_alpha,
            "test_count": test_count,
            "test_mae": test_mae,
            "test_rmse": test_rmse,
            "test_r2": test_r2,
            "commission_bps": costs.commission_bps,
            "slippage_bps": costs.slippage_bps,
            "fixed_signal_rule": RIDGE_FINAL_TRADING_SIGNAL_RULE,
            "selected_signal_rule": (
                RIDGE_SELECTED_FINAL_TRADING_SIGNAL_RULE
            ),
            "selected_threshold": selected_threshold,
            "threshold_selection_id": threshold_selection_id,
            "selected_candidate_id": selected_candidate_id,
            "fixed_trading_id": fixed_trading_id,
            "selected_trading_id": selected_trading_id,
            "fixed_metrics_id": _metrics_id(
                "market-vault-ridge-final-evaluation-fixed-metrics-v1",
                fixed_metrics,
            ),
            "selected_metrics_id": _metrics_id(
                "market-vault-ridge-final-evaluation-selected-metrics-v1",
                selected_metrics,
            ),
            "delta_id": _delta_id(delta),
        },
    )


def compare_ridge_final_trading(
    final_test: RidgeFinalTestResult,
    fixed_trading: RidgeFinalTradingResult,
    threshold_selection: RidgeTradingThresholdSelectionResult,
    selected_trading: RidgeSelectedFinalTradingResult,
) -> RidgeFinalEvaluationReport:
    """Compare two frozen TEST trading policies without making a decision."""
    if type(final_test) is not RidgeFinalTestResult:
        raise RidgeFinalEvaluationError(
            "exact RidgeFinalTestResult required"
        )
    if type(fixed_trading) is not RidgeFinalTradingResult:
        raise RidgeFinalEvaluationError(
            "exact RidgeFinalTradingResult required"
        )
    if type(threshold_selection) is not RidgeTradingThresholdSelectionResult:
        raise RidgeFinalEvaluationError(
            "exact RidgeTradingThresholdSelectionResult required"
        )
    if type(selected_trading) is not RidgeSelectedFinalTradingResult:
        raise RidgeFinalEvaluationError(
            "exact RidgeSelectedFinalTradingResult required"
        )

    try:
        final = replace(final_test)
    except RidgeFinalTestError as exc:
        raise RidgeFinalEvaluationError(
            "final TEST identity validation failed"
        ) from exc
    try:
        fixed = replace(fixed_trading)
    except RidgeFinalTradingError as exc:
        raise RidgeFinalEvaluationError(
            "fixed trading identity validation failed"
        ) from exc
    try:
        threshold = replace(threshold_selection)
    except RidgeTradingThresholdSelectionError as exc:
        raise RidgeFinalEvaluationError(
            "threshold selection identity validation failed"
        ) from exc
    try:
        selected = replace(selected_trading)
    except RidgeSelectedFinalTradingError as exc:
        raise RidgeFinalEvaluationError(
            "selected trading identity validation failed"
        ) from exc

    if (
        fixed.final_test_id != final.final_test_id
        or fixed.model_id != final.model_id
        or fixed.dataset_id != final.dataset_id
        or fixed.label_name != final.label_name
    ):
        raise RidgeFinalEvaluationError(
            "fixed trading result differs from frozen final TEST"
        )

    if (
        threshold.dataset_id != final.dataset_id
        or threshold.feature_names != final.feature_names
        or threshold.label_name != final.label_name
        or threshold.ridge_selection_id != final.selection_id
        or threshold.walk_forward_id != final.walk_forward_id
        or threshold.selected_alpha != final.alpha
    ):
        raise RidgeFinalEvaluationError(
            "threshold selection differs from frozen final TEST model/schema"
        )

    if (
        selected.threshold_selection_id
        != threshold.threshold_selection_id
        or selected.selected_candidate_id
        != threshold.selected_candidate_id
        or selected.final_test_id != final.final_test_id
        or selected.model_id != final.model_id
        or selected.ridge_selection_id != final.selection_id
        or selected.walk_forward_id != final.walk_forward_id
        or selected.dataset_id != final.dataset_id
        or selected.feature_names != final.feature_names
        or selected.label_name != final.label_name
        or selected.selected_alpha != final.alpha
        or selected.selected_threshold != threshold.selected_threshold
    ):
        raise RidgeFinalEvaluationError(
            "selected trading result differs from frozen selection/TEST"
        )

    if fixed.costs != threshold.costs or selected.costs != threshold.costs:
        raise RidgeFinalEvaluationError(
            "fixed and selected TEST trading must use identical frozen costs"
        )

    delta = _delta(fixed.metrics, selected.metrics)
    report_id = _report_id(
        final_test_id=final.final_test_id,
        model_id=final.model_id,
        ridge_selection_id=final.selection_id,
        walk_forward_id=final.walk_forward_id,
        dataset_id=final.dataset_id,
        feature_names=final.feature_names,
        label_name=final.label_name,
        selected_alpha=final.alpha,
        test_count=final.test_count,
        test_mae=final.mae,
        test_rmse=final.rmse,
        test_r2=final.r2,
        costs=threshold.costs,
        selected_threshold=threshold.selected_threshold,
        threshold_selection_id=threshold.threshold_selection_id,
        selected_candidate_id=threshold.selected_candidate_id,
        fixed_trading_id=fixed.trading_id,
        selected_trading_id=selected.trading_id,
        fixed_metrics=fixed.metrics,
        selected_metrics=selected.metrics,
        delta=delta,
    )
    return RidgeFinalEvaluationReport(
        RIDGE_FINAL_EVALUATION_VERSION,
        report_id,
        final.final_test_id,
        final.model_id,
        final.selection_id,
        final.walk_forward_id,
        final.dataset_id,
        final.feature_names,
        final.label_name,
        final.alpha,
        final.test_count,
        final.mae,
        final.rmse,
        final.r2,
        threshold.costs,
        RIDGE_FINAL_TRADING_SIGNAL_RULE,
        RIDGE_SELECTED_FINAL_TRADING_SIGNAL_RULE,
        threshold.selected_threshold,
        threshold.threshold_selection_id,
        threshold.selected_candidate_id,
        fixed.trading_id,
        selected.trading_id,
        fixed.metrics,
        selected.metrics,
        delta,
    )
