"""Final held-out TEST trading with a VALIDATION-selected Ridge threshold.

This layer is deliberately distinct from Ridge Final TEST Trading V1, whose
signal rule is permanently fixed at predicted return > 0.

Here the threshold is not tuned on TEST. It arrives frozen inside one exact
RidgeTradingThresholdSelectionResult produced from Walk-Forward VALIDATION.
The same transaction costs used during threshold selection are carried into
the permanent held-out TEST evaluation without override.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import math
import re

from ..backtest.models import BacktestCosts
from ..cross_day_dataset import VerifiedMultiSourceCrossDayDataset
from ..dataset.encoding import encode_identity
from .experiment import ExperimentDatasetBundle
from .ridge_final_test import RidgeFinalTestResult
from .ridge_final_trading import (
    RidgeFinalTradingError,
    RidgeFinalTradingMetrics,
    _validated_inputs,
)
from .ridge_trading_selection import (
    RidgeTradingThresholdSelectionError,
    RidgeTradingThresholdSelectionResult,
)


RIDGE_SELECTED_THRESHOLD_FINAL_TRADING_VERSION = (
    "market-vault-ridge-selected-threshold-final-trading-v1"
)
RIDGE_SELECTED_THRESHOLD_FINAL_SIGNAL_RULE = (
    "PREDICTED_RETURN_GT_VALIDATION_SELECTED_THRESHOLD"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RidgeSelectedThresholdFinalTradingError(ValueError):
    """Fail-closed selected-threshold Final TEST trading error."""


def _identity(value: str, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise RidgeSelectedThresholdFinalTradingError(
            f"{label} must be a lowercase SHA-256 identity"
        )
    return value


def _finite(value, label: str) -> float:
    if type(value) is bool or not isinstance(value, (int, float)):
        raise RidgeSelectedThresholdFinalTradingError(
            f"{label} must be numeric"
        )
    number = float(value)
    if not math.isfinite(number):
        raise RidgeSelectedThresholdFinalTradingError(
            f"{label} must be finite"
        )
    return 0.0 if number == 0.0 else number


def _members_digest(prefix: str, members: tuple[str, ...]) -> str:
    framed = "".join(f"{len(member)}:{member}" for member in members)
    return encode_identity(
        prefix,
        {
            "count": len(members),
            "members": framed,
        },
    )


@dataclass(frozen=True, slots=True)
class RidgeSelectedThresholdFinalTrade:
    trade_id: str
    prediction_id: str
    label_value_id: str
    sample_key: str
    code: str
    signal_time: datetime
    exit_time: datetime
    selected_threshold: float
    predicted_return: float
    gross_return: float
    net_return: float
    equity_before: float
    equity_after: float

    def __post_init__(self) -> None:
        for name in (
            "trade_id",
            "prediction_id",
            "label_value_id",
            "sample_key",
        ):
            _identity(getattr(self, name), name)
        if type(self.code) is not str or not self.code.startswith("US."):
            raise RidgeSelectedThresholdFinalTradingError(
                "trade code must be a US symbol"
            )
        for name in ("signal_time", "exit_time"):
            value = getattr(self, name)
            if type(value) is not datetime or value.tzinfo is None:
                raise RidgeSelectedThresholdFinalTradingError(
                    f"{name} must be timezone-aware"
                )
        if self.exit_time <= self.signal_time:
            raise RidgeSelectedThresholdFinalTradingError(
                "trade exit_time must be after signal_time"
            )
        for name in (
            "selected_threshold",
            "predicted_return",
            "gross_return",
            "net_return",
            "equity_before",
            "equity_after",
        ):
            object.__setattr__(
                self,
                name,
                _finite(getattr(self, name), name),
            )
        if self.predicted_return <= self.selected_threshold:
            raise RidgeSelectedThresholdFinalTradingError(
                "accepted trade prediction must exceed selected_threshold"
            )
        if self.gross_return <= -1.0 or self.net_return <= -1.0:
            raise RidgeSelectedThresholdFinalTradingError(
                "trade returns must be greater than -100%"
            )
        if self.equity_before <= 0.0 or self.equity_after <= 0.0:
            raise RidgeSelectedThresholdFinalTradingError(
                "trade equity must remain positive"
            )
        expected = _trade_id(
            prediction_id=self.prediction_id,
            label_value_id=self.label_value_id,
            sample_key=self.sample_key,
            code=self.code,
            signal_time=self.signal_time,
            exit_time=self.exit_time,
            selected_threshold=self.selected_threshold,
            predicted_return=self.predicted_return,
            gross_return=self.gross_return,
            net_return=self.net_return,
            equity_before=self.equity_before,
            equity_after=self.equity_after,
        )
        if self.trade_id != expected:
            raise RidgeSelectedThresholdFinalTradingError(
                "trade_id differs from trade content"
            )


@dataclass(frozen=True, slots=True)
class RidgeSelectedThresholdFinalTradingResult:
    version: str
    trading_id: str
    threshold_selection_id: str
    ridge_selection_id: str
    final_test_id: str
    model_id: str
    walk_forward_id: str
    dataset_id: str
    label_name: str
    selected_alpha: float
    selected_threshold: float
    signal_rule: str
    costs: BacktestCosts
    trades: tuple[RidgeSelectedThresholdFinalTrade, ...]
    metrics: RidgeFinalTradingMetrics

    def __post_init__(self) -> None:
        if self.version != RIDGE_SELECTED_THRESHOLD_FINAL_TRADING_VERSION:
            raise RidgeSelectedThresholdFinalTradingError(
                "unsupported selected-threshold final trading version"
            )
        for name in (
            "trading_id",
            "threshold_selection_id",
            "ridge_selection_id",
            "final_test_id",
            "model_id",
            "walk_forward_id",
            "dataset_id",
        ):
            _identity(getattr(self, name), name)
        if type(self.label_name) is not str or not self.label_name:
            raise RidgeSelectedThresholdFinalTradingError(
                "label_name must be non-empty"
            )
        object.__setattr__(
            self,
            "selected_alpha",
            _finite(self.selected_alpha, "selected_alpha"),
        )
        if self.selected_alpha <= 0.0:
            raise RidgeSelectedThresholdFinalTradingError(
                "selected_alpha must be strictly positive"
            )
        object.__setattr__(
            self,
            "selected_threshold",
            _finite(self.selected_threshold, "selected_threshold"),
        )
        if self.signal_rule != RIDGE_SELECTED_THRESHOLD_FINAL_SIGNAL_RULE:
            raise RidgeSelectedThresholdFinalTradingError(
                "unsupported selected-threshold signal rule"
            )
        if type(self.costs) is not BacktestCosts:
            raise RidgeSelectedThresholdFinalTradingError(
                "exact BacktestCosts required"
            )
        if type(self.trades) is not tuple or not all(
            type(item) is RidgeSelectedThresholdFinalTrade
            for item in self.trades
        ):
            raise RidgeSelectedThresholdFinalTradingError(
                "trades must be an immutable selected-threshold trade tuple"
            )
        if type(self.metrics) is not RidgeFinalTradingMetrics:
            raise RidgeSelectedThresholdFinalTradingError(
                "exact RidgeFinalTradingMetrics required"
            )
        if self.metrics.trade_count != len(self.trades):
            raise RidgeSelectedThresholdFinalTradingError(
                "trade_count differs from trade tuple length"
            )
        ordering = tuple(
            (trade.signal_time, trade.code, trade.sample_key)
            for trade in self.trades
        )
        if ordering != tuple(sorted(ordering)):
            raise RidgeSelectedThresholdFinalTradingError(
                "trades must be chronologically ordered"
            )
        if any(
            trade.selected_threshold != self.selected_threshold
            for trade in self.trades
        ):
            raise RidgeSelectedThresholdFinalTradingError(
                "trade threshold differs from result selected_threshold"
            )
        expected = _trading_id(
            threshold_selection_id=self.threshold_selection_id,
            ridge_selection_id=self.ridge_selection_id,
            final_test_id=self.final_test_id,
            model_id=self.model_id,
            walk_forward_id=self.walk_forward_id,
            dataset_id=self.dataset_id,
            label_name=self.label_name,
            selected_alpha=self.selected_alpha,
            selected_threshold=self.selected_threshold,
            costs=self.costs,
            trades=self.trades,
            metrics=self.metrics,
        )
        if self.trading_id != expected:
            raise RidgeSelectedThresholdFinalTradingError(
                "trading_id differs from selected-threshold result content"
            )


def _trade_id(
    *,
    prediction_id: str,
    label_value_id: str,
    sample_key: str,
    code: str,
    signal_time: datetime,
    exit_time: datetime,
    selected_threshold: float,
    predicted_return: float,
    gross_return: float,
    net_return: float,
    equity_before: float,
    equity_after: float,
) -> str:
    return encode_identity(
        "market-vault-ridge-selected-threshold-final-trade-v1",
        {
            "prediction_id": prediction_id,
            "label_value_id": label_value_id,
            "sample_key": sample_key,
            "code": code,
            "signal_time": signal_time,
            "exit_time": exit_time,
            "selected_threshold": selected_threshold,
            "predicted_return": predicted_return,
            "gross_return": gross_return,
            "net_return": net_return,
            "equity_before": equity_before,
            "equity_after": equity_after,
        },
    )


def _metrics_id(metrics: RidgeFinalTradingMetrics) -> str:
    return encode_identity(
        "market-vault-ridge-selected-threshold-final-metrics-v1",
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


def _trading_id(
    *,
    threshold_selection_id: str,
    ridge_selection_id: str,
    final_test_id: str,
    model_id: str,
    walk_forward_id: str,
    dataset_id: str,
    label_name: str,
    selected_alpha: float,
    selected_threshold: float,
    costs: BacktestCosts,
    trades: tuple[RidgeSelectedThresholdFinalTrade, ...],
    metrics: RidgeFinalTradingMetrics,
) -> str:
    return encode_identity(
        RIDGE_SELECTED_THRESHOLD_FINAL_TRADING_VERSION,
        {
            "threshold_selection_id": threshold_selection_id,
            "ridge_selection_id": ridge_selection_id,
            "final_test_id": final_test_id,
            "model_id": model_id,
            "walk_forward_id": walk_forward_id,
            "dataset_id": dataset_id,
            "label_name": label_name,
            "selected_alpha": selected_alpha,
            "selected_threshold": selected_threshold,
            "signal_rule": RIDGE_SELECTED_THRESHOLD_FINAL_SIGNAL_RULE,
            "commission_bps": costs.commission_bps,
            "slippage_bps": costs.slippage_bps,
            "trade_ids_digest": _members_digest(
                "market-vault-ridge-selected-threshold-final-trade-ids-v1",
                tuple(item.trade_id for item in trades),
            ),
            "metrics_id": _metrics_id(metrics),
        },
    )


def _validate_selection_against_final(
    selection: RidgeTradingThresholdSelectionResult,
    final_test: RidgeFinalTestResult,
    bundle: ExperimentDatasetBundle,
) -> RidgeTradingThresholdSelectionResult:
    if type(selection) is not RidgeTradingThresholdSelectionResult:
        raise RidgeSelectedThresholdFinalTradingError(
            "selected-threshold final trading requires "
            "RidgeTradingThresholdSelectionResult"
        )
    try:
        selection = replace(selection)
    except RidgeTradingThresholdSelectionError as exc:
        raise RidgeSelectedThresholdFinalTradingError(
            "threshold selection identity validation failed"
        ) from exc

    if (
        selection.ridge_selection_id != final_test.selection_id
        or selection.walk_forward_id != final_test.walk_forward_id
        or selection.dataset_id != final_test.dataset_id
        or selection.dataset_id != bundle.dataset_id
        or selection.feature_names != final_test.feature_names
        or selection.feature_names != bundle.feature_names
        or selection.label_name != final_test.label_name
        or selection.label_name != bundle.label_name
        or selection.selected_alpha != final_test.alpha
    ):
        raise RidgeSelectedThresholdFinalTradingError(
            "validation threshold selection differs from Final TEST model schema"
        )

    test_keys = {item.sample_key for item in bundle.test.metadata}
    if any(
        prediction.sample_key in test_keys
        for prediction in selection.validation_predictions
    ):
        raise RidgeSelectedThresholdFinalTradingError(
            "validation threshold selection overlaps held-out TEST samples"
        )
    return selection


def _evaluate_selected_threshold(
    bundle: ExperimentDatasetBundle,
    final_test: RidgeFinalTestResult,
    selection: RidgeTradingThresholdSelectionResult,
):
    costs = selection.costs
    threshold = selection.selected_threshold

    equity = 1.0
    gross_equity = 1.0
    peak = 1.0
    realized_max_drawdown = 0.0
    signal_count = 0
    overlap_skipped_count = 0
    last_exit = None
    trades = []
    gains = 0.0
    losses = 0.0
    signal_to_exit_seconds = 0.0

    for prediction, metadata in zip(
        final_test.predictions,
        bundle.test.metadata,
    ):
        predicted = _finite(
            prediction.predicted,
            "predicted TEST return",
        )
        if predicted <= threshold:
            continue
        signal_count += 1

        exit_time = metadata.actual_label_end_time
        if (
            last_exit is not None
            and metadata.feature_window_close < last_exit
        ):
            overlap_skipped_count += 1
            continue

        gross_return = _finite(
            prediction.actual,
            "actual execution-safe TEST return",
        )
        if gross_return <= -1.0:
            raise RidgeSelectedThresholdFinalTradingError(
                "execution-safe TEST return must be greater than -100%"
            )

        gross_multiplier = 1.0 + gross_return
        side_multiplier = 1.0 - costs.per_side_rate
        net_multiplier = (
            gross_multiplier
            * side_multiplier
            * side_multiplier
        )
        net_return = net_multiplier - 1.0
        if net_return <= -1.0 or not math.isfinite(net_return):
            raise RidgeSelectedThresholdFinalTradingError(
                "cost-adjusted TEST trade return is invalid"
            )

        before = equity
        after = before * net_multiplier
        pnl = after - before
        if pnl > 0.0:
            gains += pnl
        elif pnl < 0.0:
            losses += -pnl

        trade_id = _trade_id(
            prediction_id=prediction.prediction_id,
            label_value_id=metadata.label_value_id,
            sample_key=prediction.sample_key,
            code=prediction.code,
            signal_time=prediction.feature_window_close,
            exit_time=exit_time,
            selected_threshold=threshold,
            predicted_return=predicted,
            gross_return=gross_return,
            net_return=net_return,
            equity_before=before,
            equity_after=after,
        )
        trades.append(
            RidgeSelectedThresholdFinalTrade(
                trade_id,
                prediction.prediction_id,
                metadata.label_value_id,
                prediction.sample_key,
                prediction.code,
                prediction.feature_window_close,
                exit_time,
                threshold,
                predicted,
                gross_return,
                net_return,
                before,
                after,
            )
        )

        equity = after
        gross_equity *= gross_multiplier
        peak = max(peak, equity)
        realized_max_drawdown = max(
            realized_max_drawdown,
            1.0 - equity / peak,
        )
        signal_to_exit_seconds += (
            exit_time - prediction.feature_window_close
        ).total_seconds()
        last_exit = exit_time

    trade_tuple = tuple(trades)
    trade_count = len(trade_tuple)
    win_rate = (
        sum(item.net_return > 0.0 for item in trade_tuple)
        / trade_count
        if trade_count
        else 0.0
    )
    average_trade_return = (
        math.fsum(item.net_return for item in trade_tuple)
        / trade_count
        if trade_count
        else 0.0
    )
    profit_factor = gains / losses if losses > 0.0 else None
    average_signal_to_exit = (
        signal_to_exit_seconds / trade_count
        if trade_count
        else 0.0
    )

    metrics = RidgeFinalTradingMetrics(
        final_test.test_count,
        signal_count,
        overlap_skipped_count,
        trade_count,
        gross_equity - 1.0,
        equity - 1.0,
        realized_max_drawdown,
        win_rate,
        average_trade_return,
        profit_factor,
        average_signal_to_exit,
    )
    trading_id = _trading_id(
        threshold_selection_id=selection.threshold_selection_id,
        ridge_selection_id=selection.ridge_selection_id,
        final_test_id=final_test.final_test_id,
        model_id=final_test.model_id,
        walk_forward_id=final_test.walk_forward_id,
        dataset_id=final_test.dataset_id,
        label_name=final_test.label_name,
        selected_alpha=final_test.alpha,
        selected_threshold=threshold,
        costs=costs,
        trades=trade_tuple,
        metrics=metrics,
    )
    return RidgeSelectedThresholdFinalTradingResult(
        RIDGE_SELECTED_THRESHOLD_FINAL_TRADING_VERSION,
        trading_id,
        selection.threshold_selection_id,
        selection.ridge_selection_id,
        final_test.final_test_id,
        final_test.model_id,
        final_test.walk_forward_id,
        final_test.dataset_id,
        final_test.label_name,
        final_test.alpha,
        threshold,
        RIDGE_SELECTED_THRESHOLD_FINAL_SIGNAL_RULE,
        costs,
        trade_tuple,
        metrics,
    )


def evaluate_ridge_selected_threshold_final_trading(
    dataset: VerifiedMultiSourceCrossDayDataset,
    bundle: ExperimentDatasetBundle,
    final_test: RidgeFinalTestResult,
    threshold_selection: RidgeTradingThresholdSelectionResult,
) -> RidgeSelectedThresholdFinalTradingResult:
    """Apply the VALIDATION-selected threshold once on permanent Final TEST."""
    try:
        _, rebuilt, validated_final = _validated_inputs(
            dataset,
            bundle,
            final_test,
        )
    except RidgeFinalTradingError as exc:
        raise RidgeSelectedThresholdFinalTradingError(str(exc)) from exc

    validated_selection = _validate_selection_against_final(
        threshold_selection,
        validated_final,
        rebuilt,
    )
    return _evaluate_selected_threshold(
        rebuilt,
        validated_final,
        validated_selection,
    )
