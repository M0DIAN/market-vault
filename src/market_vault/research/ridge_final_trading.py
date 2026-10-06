"""Leakage-safe Ridge held-out TEST trading evaluation V1.

This layer answers one narrow question after Ridge final TEST inference is
already complete:

    Do positive predicted execution-safe returns translate into economic value
    on the permanent held-out TEST?

V1 deliberately fixes the signal rule to:

    predicted_return > 0.0  => LONG
    otherwise               => FLAT

There is no TEST threshold search or tuning.

PnL is accepted only when the selected LabelSpec is the execution-safe
forward_open_to_close_return transform.  The supplied verified Research
Dataset artifact is re-read at invocation and the ExperimentDatasetBundle is
rebuilt from that exact artifact before any trading evaluation proceeds.

Trades are full-notional and non-overlapping.  Because Experiment Metadata V1
does not expose the exact entry-open timestamp, V1 does not claim holding-time
or exposure metrics.  It reports only signal-to-exit duration, which is fully
authorized by feature_window_close and the selected Label's exact end time.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import math
import re

from ..backtest.models import BacktestCosts, BacktestError
from ..cross_day_dataset import (
    VerifiedMultiSourceCrossDayDataset,
    load_verified_multi_source_cross_day_dataset,
)
from ..cross_day_dataset.artifact_models import MultiSourceCrossDayArtifactError
from ..dataset.encoding import encode_identity
from .experiment import (
    ExperimentDatasetBundle,
    ExperimentMetadataError,
    build_experiment_dataset,
)
from .ridge_final_test import (
    RidgeFinalTestError,
    RidgeFinalTestPrediction,
    RidgeFinalTestResult,
)


RIDGE_FINAL_TRADING_VERSION = "market-vault-ridge-final-trading-v1"
RIDGE_FINAL_TRADING_SIGNAL_RULE = "PREDICTED_RETURN_GT_ZERO"
_EXECUTION_SAFE_RETURN_REF = (
    "market_vault.dataset.label_transforms.forward_open_to_close_return:"
    "forward_open_to_close_return"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RidgeFinalTradingError(ValueError):
    """Fail-closed Ridge final TEST trading evaluation error."""


def _identity(value: str, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise RidgeFinalTradingError(
            f"{label} must be a lowercase SHA-256 identity"
        )
    return value


def _finite(value, label: str) -> float:
    if type(value) is bool or not isinstance(value, (int, float)):
        raise RidgeFinalTradingError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise RidgeFinalTradingError(f"{label} must be finite")
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
class RidgeFinalTradingTrade:
    trade_id: str
    prediction_id: str
    label_value_id: str
    sample_key: str
    code: str
    signal_time: datetime
    exit_time: datetime
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
            raise RidgeFinalTradingError("trade code must be a US symbol")
        for name in ("signal_time", "exit_time"):
            value = getattr(self, name)
            if type(value) is not datetime or value.tzinfo is None:
                raise RidgeFinalTradingError(
                    f"{name} must be timezone-aware"
                )
        if self.exit_time <= self.signal_time:
            raise RidgeFinalTradingError(
                "trade exit_time must be after signal_time"
            )
        for name in (
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
        if self.predicted_return <= 0.0:
            raise RidgeFinalTradingError(
                "accepted trade prediction must be strictly positive"
            )
        if self.gross_return <= -1.0 or self.net_return <= -1.0:
            raise RidgeFinalTradingError(
                "trade returns must be greater than -100%"
            )
        if self.equity_before <= 0.0 or self.equity_after <= 0.0:
            raise RidgeFinalTradingError("trade equity must remain positive")
        expected = _trade_id(
            prediction_id=self.prediction_id,
            label_value_id=self.label_value_id,
            sample_key=self.sample_key,
            code=self.code,
            signal_time=self.signal_time,
            exit_time=self.exit_time,
            predicted_return=self.predicted_return,
            gross_return=self.gross_return,
            net_return=self.net_return,
            equity_before=self.equity_before,
            equity_after=self.equity_after,
        )
        if self.trade_id != expected:
            raise RidgeFinalTradingError(
                "trade_id differs from trade content"
            )


@dataclass(frozen=True, slots=True)
class RidgeFinalTradingMetrics:
    candidate_count: int
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
            "candidate_count",
            "signal_count",
            "overlap_skipped_count",
            "trade_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise RidgeFinalTradingError(
                    f"{name} must be a non-negative integer"
                )
        if self.trade_count > self.signal_count or self.signal_count > self.candidate_count:
            raise RidgeFinalTradingError("trading counts are inconsistent")
        if self.overlap_skipped_count != self.signal_count - self.trade_count:
            raise RidgeFinalTradingError(
                "overlap_skipped_count must equal signals minus trades"
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
                _finite(getattr(self, name), name),
            )
        if self.realized_max_drawdown < 0.0:
            raise RidgeFinalTradingError(
                "realized_max_drawdown must be non-negative"
            )
        if not 0.0 <= self.win_rate <= 1.0:
            raise RidgeFinalTradingError("win_rate must be within [0, 1]")
        if self.average_signal_to_exit_seconds < 0.0:
            raise RidgeFinalTradingError(
                "average_signal_to_exit_seconds must be non-negative"
            )
        if self.profit_factor is not None:
            value = _finite(self.profit_factor, "profit_factor")
            if value < 0.0:
                raise RidgeFinalTradingError(
                    "profit_factor must be non-negative"
                )
            object.__setattr__(self, "profit_factor", value)


@dataclass(frozen=True, slots=True)
class RidgeFinalTradingResult:
    version: str
    trading_id: str
    final_test_id: str
    model_id: str
    dataset_id: str
    label_name: str
    signal_rule: str
    costs: BacktestCosts
    trades: tuple[RidgeFinalTradingTrade, ...]
    metrics: RidgeFinalTradingMetrics

    def __post_init__(self) -> None:
        if self.version != RIDGE_FINAL_TRADING_VERSION:
            raise RidgeFinalTradingError(
                "unsupported Ridge final trading version"
            )
        for name in (
            "trading_id",
            "final_test_id",
            "model_id",
            "dataset_id",
        ):
            _identity(getattr(self, name), name)
        if type(self.label_name) is not str or not self.label_name:
            raise RidgeFinalTradingError("label_name must be non-empty")
        if self.signal_rule != RIDGE_FINAL_TRADING_SIGNAL_RULE:
            raise RidgeFinalTradingError("unsupported trading signal rule")
        if type(self.costs) is not BacktestCosts:
            raise RidgeFinalTradingError("exact BacktestCosts required")
        if type(self.trades) is not tuple or not all(
            type(item) is RidgeFinalTradingTrade for item in self.trades
        ):
            raise RidgeFinalTradingError(
                "trades must be an immutable RidgeFinalTradingTrade tuple"
            )
        if type(self.metrics) is not RidgeFinalTradingMetrics:
            raise RidgeFinalTradingError(
                "exact RidgeFinalTradingMetrics required"
            )
        if self.metrics.trade_count != len(self.trades):
            raise RidgeFinalTradingError(
                "trade_count differs from trade tuple length"
            )
        ordering = tuple(
            (trade.signal_time, trade.code, trade.sample_key)
            for trade in self.trades
        )
        if ordering != tuple(sorted(ordering)):
            raise RidgeFinalTradingError(
                "trades must be chronologically ordered"
            )
        expected = _trading_id(
            final_test_id=self.final_test_id,
            model_id=self.model_id,
            dataset_id=self.dataset_id,
            label_name=self.label_name,
            costs=self.costs,
            trades=self.trades,
            metrics=self.metrics,
        )
        if self.trading_id != expected:
            raise RidgeFinalTradingError(
                "trading_id differs from trading result content"
            )


def _trade_id(
    *,
    prediction_id: str,
    label_value_id: str,
    sample_key: str,
    code: str,
    signal_time: datetime,
    exit_time: datetime,
    predicted_return: float,
    gross_return: float,
    net_return: float,
    equity_before: float,
    equity_after: float,
) -> str:
    return encode_identity(
        "market-vault-ridge-final-trading-trade-v1",
        {
            "prediction_id": prediction_id,
            "label_value_id": label_value_id,
            "sample_key": sample_key,
            "code": code,
            "signal_time": signal_time,
            "exit_time": exit_time,
            "predicted_return": predicted_return,
            "gross_return": gross_return,
            "net_return": net_return,
            "equity_before": equity_before,
            "equity_after": equity_after,
        },
    )


def _metrics_id(metrics: RidgeFinalTradingMetrics) -> str:
    return encode_identity(
        "market-vault-ridge-final-trading-metrics-v1",
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
    final_test_id: str,
    model_id: str,
    dataset_id: str,
    label_name: str,
    costs: BacktestCosts,
    trades: tuple[RidgeFinalTradingTrade, ...],
    metrics: RidgeFinalTradingMetrics,
) -> str:
    trade_ids = tuple(item.trade_id for item in trades)
    return encode_identity(
        RIDGE_FINAL_TRADING_VERSION,
        {
            "final_test_id": final_test_id,
            "model_id": model_id,
            "dataset_id": dataset_id,
            "label_name": label_name,
            "signal_rule": RIDGE_FINAL_TRADING_SIGNAL_RULE,
            "commission_bps": costs.commission_bps,
            "slippage_bps": costs.slippage_bps,
            "trade_ids_digest": _members_digest(
                "market-vault-ridge-final-trading-trade-ids-v1",
                trade_ids,
            ),
            "metrics_id": _metrics_id(metrics),
        },
    )


def _validated_inputs(
    dataset: VerifiedMultiSourceCrossDayDataset,
    bundle: ExperimentDatasetBundle,
    final_test: RidgeFinalTestResult,
):
    if type(dataset) is not VerifiedMultiSourceCrossDayDataset:
        raise RidgeFinalTradingError(
            "Ridge final trading V1 requires a Verified Research Dataset artifact"
        )
    if type(bundle) is not ExperimentDatasetBundle:
        raise RidgeFinalTradingError(
            "Ridge final trading V1 requires ExperimentDatasetBundle"
        )
    if type(final_test) is not RidgeFinalTestResult:
        raise RidgeFinalTradingError(
            "Ridge final trading V1 requires RidgeFinalTestResult"
        )

    try:
        fresh = load_verified_multi_source_cross_day_dataset(
            dataset.build_path
        )
    except (
        MultiSourceCrossDayArtifactError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        raise RidgeFinalTradingError(
            "verified Research Dataset revalidation failed"
        ) from exc
    if fresh.dataset_id != dataset.dataset_id:
        raise RidgeFinalTradingError(
            "verified Research Dataset identity changed since load"
        )

    specs = tuple(
        spec for spec in fresh.cross_day_labels.label_specs
        if spec.name == bundle.label_name
    )
    if len(specs) != 1:
        raise RidgeFinalTradingError(
            "Experiment Label must select exactly one verified Dataset Label"
        )
    spec = specs[0]
    if (
        spec.transform_ref != _EXECUTION_SAFE_RETURN_REF
        or spec.output.logical_type != "float64"
        or spec.input_canonical_fields != ("open", "close")
    ):
        raise RidgeFinalTradingError(
            "Ridge final trading requires execution-safe "
            "forward_open_to_close_return Label semantics"
        )

    try:
        rebuilt = build_experiment_dataset(
            fresh,
            label_field=bundle.label_name,
            feature_fields=bundle.feature_names,
        )
    except ExperimentMetadataError as exc:
        raise RidgeFinalTradingError(
            "Experiment Dataset rebuild failed"
        ) from exc
    if rebuilt != bundle:
        raise RidgeFinalTradingError(
            "Experiment Dataset differs from the verified Research Dataset"
        )

    try:
        validated_final = replace(final_test)
    except RidgeFinalTestError as exc:
        raise RidgeFinalTradingError(
            "Ridge final TEST result identity validation failed"
        ) from exc

    if (
        validated_final.dataset_id != bundle.dataset_id
        or validated_final.feature_names != bundle.feature_names
        or validated_final.label_name != bundle.label_name
        or validated_final.test_count != bundle.test.row_count
    ):
        raise RidgeFinalTradingError(
            "Ridge final TEST result differs from Experiment Dataset schema"
        )

    if bundle.test.row_count <= 0:
        raise RidgeFinalTradingError("held-out TEST split must not be empty")

    for prediction, actual, metadata in zip(
        validated_final.predictions,
        bundle.test.y,
        bundle.test.metadata,
    ):
        if (
            prediction.sample_key != metadata.sample_key
            or prediction.code != metadata.code
            or prediction.feature_window_close
            != metadata.feature_window_close
            or prediction.actual != actual
        ):
            raise RidgeFinalTradingError(
                "Ridge TEST prediction differs from Experiment TEST row"
            )

    return fresh, rebuilt, validated_final


def _evaluate(
    bundle: ExperimentDatasetBundle,
    final_test: RidgeFinalTestResult,
    costs: BacktestCosts,
) -> RidgeFinalTradingResult:
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
        if predicted <= 0.0:
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
            raise RidgeFinalTradingError(
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
            raise RidgeFinalTradingError(
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
            predicted_return=predicted,
            gross_return=gross_return,
            net_return=net_return,
            equity_before=before,
            equity_after=after,
        )
        trades.append(
            RidgeFinalTradingTrade(
                trade_id,
                prediction.prediction_id,
                metadata.label_value_id,
                prediction.sample_key,
                prediction.code,
                prediction.feature_window_close,
                exit_time,
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
        final_test_id=final_test.final_test_id,
        model_id=final_test.model_id,
        dataset_id=final_test.dataset_id,
        label_name=final_test.label_name,
        costs=costs,
        trades=trade_tuple,
        metrics=metrics,
    )
    return RidgeFinalTradingResult(
        RIDGE_FINAL_TRADING_VERSION,
        trading_id,
        final_test.final_test_id,
        final_test.model_id,
        final_test.dataset_id,
        final_test.label_name,
        RIDGE_FINAL_TRADING_SIGNAL_RULE,
        costs,
        trade_tuple,
        metrics,
    )


def evaluate_ridge_final_trading(
    dataset: VerifiedMultiSourceCrossDayDataset,
    bundle: ExperimentDatasetBundle,
    final_test: RidgeFinalTestResult,
    *,
    commission_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> RidgeFinalTradingResult:
    """Evaluate fixed positive-prediction Long/Flat trading on held-out TEST."""
    _, rebuilt, validated_final = _validated_inputs(
        dataset,
        bundle,
        final_test,
    )
    try:
        costs = BacktestCosts(
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
        )
    except BacktestError as exc:
        raise RidgeFinalTradingError(str(exc)) from exc
    return _evaluate(rebuilt, validated_final, costs)
