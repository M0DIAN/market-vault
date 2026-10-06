"""Leakage-safe Ridge trading threshold selection V1.

This layer selects one Long/Flat prediction threshold using only non-overlapping
Walk-Forward VALIDATION predictions from the Ridge alpha already selected by
validation RMSE.

Permanent TEST values and final TEST predictions are inaccessible here.

Public selection also verifies that the Experiment Label is the execution-safe
forward_open_to_close_return family through the shared Research trading
authority.

Selection metric:

    validation compounded net total return (higher is better)

Exact ties are broken by lower realized drawdown and then the higher threshold,
making the tie-break deterministic and conservative.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
import re

from ..backtest.models import BacktestCosts, BacktestError
from ..cross_day_dataset import VerifiedMultiSourceCrossDayDataset
from ..dataset.encoding import encode_identity
from .experiment import ExperimentDatasetBundle
from .ridge_baseline import RidgeBaselineError, _predict
from .ridge_selection import (
    RidgeAlphaSelectionResult,
)
from .trading_authority import (
    TradingAuthorityError,
    validate_execution_safe_experiment,
)
from .walk_forward import (
    WalkForwardError,
    WalkForwardPlan,
    build_walk_forward_plan,
)


RIDGE_TRADING_THRESHOLD_SELECTION_VERSION = (
    "market-vault-ridge-trading-threshold-selection-v1"
)
RIDGE_TRADING_THRESHOLD_SELECTION_METRIC = "TOTAL_RETURN"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RidgeTradingThresholdSelectionError(ValueError):
    """Fail-closed Ridge validation trading threshold selection error."""


def _identity(value: str, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise RidgeTradingThresholdSelectionError(
            f"{label} must be a lowercase SHA-256 identity"
        )
    return value


def _finite(value, label: str) -> float:
    if type(value) is bool or not isinstance(value, (int, float)):
        raise RidgeTradingThresholdSelectionError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise RidgeTradingThresholdSelectionError(f"{label} must be finite")
    return 0.0 if number == 0.0 else number


def _thresholds(values) -> tuple[float, ...]:
    if isinstance(values, (str, bytes)):
        raise RidgeTradingThresholdSelectionError(
            "thresholds must be an iterable of numeric values"
        )
    try:
        normalized = tuple(
            _finite(value, "threshold") for value in values
        )
    except TypeError as exc:
        raise RidgeTradingThresholdSelectionError(
            "thresholds must be an iterable of numeric values"
        ) from exc
    if len(normalized) < 2:
        raise RidgeTradingThresholdSelectionError(
            "threshold selection requires at least two candidates"
        )
    if len(set(normalized)) != len(normalized):
        raise RidgeTradingThresholdSelectionError(
            "threshold candidates must be unique"
        )
    return tuple(sorted(normalized))


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
class RidgeValidationTradingPrediction:
    prediction_id: str
    fold_index: int
    fold_id: str
    sample_key: str
    label_value_id: str
    code: str
    feature_window_close: datetime
    actual_label_end_time: datetime
    actual: float
    predicted: float

    def __post_init__(self) -> None:
        for name in (
            "prediction_id",
            "fold_id",
            "sample_key",
            "label_value_id",
        ):
            _identity(getattr(self, name), name)
        if type(self.fold_index) is not int or self.fold_index < 0:
            raise RidgeTradingThresholdSelectionError(
                "fold_index must be a non-negative integer"
            )
        if type(self.code) is not str or not self.code.startswith("US."):
            raise RidgeTradingThresholdSelectionError(
                "prediction code must be a US symbol"
            )
        for name in (
            "feature_window_close",
            "actual_label_end_time",
        ):
            value = getattr(self, name)
            if type(value) is not datetime or value.tzinfo is None:
                raise RidgeTradingThresholdSelectionError(
                    f"{name} must be timezone-aware"
                )
        if self.actual_label_end_time <= self.feature_window_close:
            raise RidgeTradingThresholdSelectionError(
                "validation Label must end after feature_window_close"
            )
        object.__setattr__(
            self,
            "actual",
            _finite(self.actual, "actual validation return"),
        )
        object.__setattr__(
            self,
            "predicted",
            _finite(self.predicted, "predicted validation return"),
        )
        if self.actual <= -1.0:
            raise RidgeTradingThresholdSelectionError(
                "execution-safe validation return must be greater than -100%"
            )
        expected = _prediction_id(
            fold_index=self.fold_index,
            fold_id=self.fold_id,
            sample_key=self.sample_key,
            label_value_id=self.label_value_id,
            code=self.code,
            feature_window_close=self.feature_window_close,
            actual_label_end_time=self.actual_label_end_time,
            actual=self.actual,
            predicted=self.predicted,
        )
        if self.prediction_id != expected:
            raise RidgeTradingThresholdSelectionError(
                "prediction_id differs from validation prediction content"
            )


@dataclass(frozen=True, slots=True)
class RidgeTradingThresholdCandidate:
    candidate_id: str
    threshold: float
    validation_sample_count: int
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
        _identity(self.candidate_id, "candidate_id")
        object.__setattr__(
            self,
            "threshold",
            _finite(self.threshold, "threshold"),
        )
        for name in (
            "validation_sample_count",
            "signal_count",
            "overlap_skipped_count",
            "trade_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise RidgeTradingThresholdSelectionError(
                    f"{name} must be a non-negative integer"
                )
        if (
            self.trade_count > self.signal_count
            or self.signal_count > self.validation_sample_count
            or self.overlap_skipped_count
            != self.signal_count - self.trade_count
        ):
            raise RidgeTradingThresholdSelectionError(
                "threshold candidate counts are inconsistent"
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
            raise RidgeTradingThresholdSelectionError(
                "realized_max_drawdown must be non-negative"
            )
        if not 0.0 <= self.win_rate <= 1.0:
            raise RidgeTradingThresholdSelectionError(
                "win_rate must be within [0, 1]"
            )
        if self.average_signal_to_exit_seconds < 0.0:
            raise RidgeTradingThresholdSelectionError(
                "average_signal_to_exit_seconds must be non-negative"
            )
        if self.profit_factor is not None:
            value = _finite(self.profit_factor, "profit_factor")
            if value < 0.0:
                raise RidgeTradingThresholdSelectionError(
                    "profit_factor must be non-negative"
                )
            object.__setattr__(self, "profit_factor", value)


@dataclass(frozen=True, slots=True)
class RidgeTradingThresholdSelectionResult:
    version: str
    threshold_selection_id: str
    ridge_selection_id: str
    walk_forward_id: str
    dataset_id: str
    feature_names: tuple[str, ...]
    label_name: str
    selected_alpha: float
    metric: str
    costs: BacktestCosts
    validation_predictions: tuple[RidgeValidationTradingPrediction, ...]
    validation_prediction_ids_digest: str
    candidates: tuple[RidgeTradingThresholdCandidate, ...]
    selected_threshold: float
    selected_candidate_id: str

    def __post_init__(self) -> None:
        if self.version != RIDGE_TRADING_THRESHOLD_SELECTION_VERSION:
            raise RidgeTradingThresholdSelectionError(
                "unsupported Ridge trading threshold selection version"
            )
        for name in (
            "threshold_selection_id",
            "ridge_selection_id",
            "walk_forward_id",
            "dataset_id",
            "validation_prediction_ids_digest",
            "selected_candidate_id",
        ):
            _identity(getattr(self, name), name)
        if (
            type(self.feature_names) is not tuple
            or not self.feature_names
            or not all(
                type(name) is str and name
                for name in self.feature_names
            )
            or len(self.feature_names) != len(set(self.feature_names))
        ):
            raise RidgeTradingThresholdSelectionError(
                "feature_names must be a unique non-empty tuple"
            )
        if type(self.label_name) is not str or not self.label_name:
            raise RidgeTradingThresholdSelectionError(
                "label_name must be non-empty"
            )
        alpha = _finite(self.selected_alpha, "selected_alpha")
        if alpha <= 0.0:
            raise RidgeTradingThresholdSelectionError(
                "selected_alpha must be strictly positive"
            )
        object.__setattr__(self, "selected_alpha", alpha)
        if self.metric != RIDGE_TRADING_THRESHOLD_SELECTION_METRIC:
            raise RidgeTradingThresholdSelectionError(
                "unsupported threshold selection metric"
            )
        if type(self.costs) is not BacktestCosts:
            raise RidgeTradingThresholdSelectionError(
                "exact BacktestCosts required"
            )
        if (
            type(self.validation_predictions) is not tuple
            or not self.validation_predictions
            or not all(
                type(item) is RidgeValidationTradingPrediction
                for item in self.validation_predictions
            )
        ):
            raise RidgeTradingThresholdSelectionError(
                "validation_predictions must be a non-empty immutable tuple"
            )
        ordering = tuple(
            (
                item.feature_window_close,
                item.code,
                item.sample_key,
            )
            for item in self.validation_predictions
        )
        if ordering != tuple(sorted(ordering)):
            raise RidgeTradingThresholdSelectionError(
                "validation predictions must be chronological"
            )
        keys = tuple(
            item.sample_key for item in self.validation_predictions
        )
        if len(keys) != len(set(keys)):
            raise RidgeTradingThresholdSelectionError(
                "validation predictions contain duplicate sample keys"
            )
        expected_predictions_digest = _members_digest(
            "market-vault-ridge-validation-trading-prediction-ids-v1",
            tuple(
                item.prediction_id
                for item in self.validation_predictions
            ),
        )
        if (
            self.validation_prediction_ids_digest
            != expected_predictions_digest
        ):
            raise RidgeTradingThresholdSelectionError(
                "validation prediction digest differs from predictions"
            )
        if (
            type(self.candidates) is not tuple
            or len(self.candidates) < 2
            or not all(
                type(item) is RidgeTradingThresholdCandidate
                for item in self.candidates
            )
        ):
            raise RidgeTradingThresholdSelectionError(
                "candidates must contain at least two threshold candidates"
            )
        thresholds = tuple(item.threshold for item in self.candidates)
        if thresholds != tuple(sorted(set(thresholds))):
            raise RidgeTradingThresholdSelectionError(
                "candidate thresholds must be unique and increasing"
            )
        if any(
            item.validation_sample_count
            != len(self.validation_predictions)
            for item in self.candidates
        ):
            raise RidgeTradingThresholdSelectionError(
                "candidate validation sample counts differ from predictions"
            )
        for item in self.candidates:
            metrics = {
                "validation_sample_count": item.validation_sample_count,
                "signal_count": item.signal_count,
                "overlap_skipped_count": item.overlap_skipped_count,
                "trade_count": item.trade_count,
                "gross_total_return": item.gross_total_return,
                "total_return": item.total_return,
                "realized_max_drawdown": item.realized_max_drawdown,
                "win_rate": item.win_rate,
                "average_trade_return": item.average_trade_return,
                "profit_factor": item.profit_factor,
                "average_signal_to_exit_seconds": (
                    item.average_signal_to_exit_seconds
                ),
            }
            expected_candidate_id = _candidate_id(
                threshold=item.threshold,
                costs=self.costs,
                predictions_digest=self.validation_prediction_ids_digest,
                metrics=metrics,
            )
            if item.candidate_id != expected_candidate_id:
                raise RidgeTradingThresholdSelectionError(
                    "candidate_id differs from threshold candidate content"
                )

        selected = max(
            self.candidates,
            key=lambda item: (
                item.total_return,
                -item.realized_max_drawdown,
                item.threshold,
            ),
        )
        selected_threshold = _finite(
            self.selected_threshold,
            "selected_threshold",
        )
        object.__setattr__(
            self,
            "selected_threshold",
            selected_threshold,
        )
        if (
            selected_threshold != selected.threshold
            or self.selected_candidate_id != selected.candidate_id
        ):
            raise RidgeTradingThresholdSelectionError(
                "selected threshold differs from deterministic selection rule"
            )

        expected_id = _selection_id(
            ridge_selection_id=self.ridge_selection_id,
            walk_forward_id=self.walk_forward_id,
            dataset_id=self.dataset_id,
            label_name=self.label_name,
            selected_alpha=self.selected_alpha,
            costs=self.costs,
            predictions_digest=self.validation_prediction_ids_digest,
            candidates=self.candidates,
            selected=selected,
        )
        if self.threshold_selection_id != expected_id:
            raise RidgeTradingThresholdSelectionError(
                "threshold_selection_id differs from selection content"
            )


def _prediction_id(
    *,
    fold_index: int,
    fold_id: str,
    sample_key: str,
    label_value_id: str,
    code: str,
    feature_window_close: datetime,
    actual_label_end_time: datetime,
    actual: float,
    predicted: float,
) -> str:
    return encode_identity(
        "market-vault-ridge-validation-trading-prediction-v1",
        {
            "fold_index": fold_index,
            "fold_id": fold_id,
            "sample_key": sample_key,
            "label_value_id": label_value_id,
            "code": code,
            "feature_window_close": feature_window_close,
            "actual_label_end_time": actual_label_end_time,
            "actual": actual,
            "predicted": predicted,
        },
    )


def _validation_predictions(
    plan: WalkForwardPlan,
    ridge_selection: RidgeAlphaSelectionResult,
) -> tuple[RidgeValidationTradingPrediction, ...]:
    report = ridge_selection.selected_report
    if len(report.folds) != len(plan.folds):
        raise RidgeTradingThresholdSelectionError(
            "selected Ridge report fold count differs from Walk-Forward plan"
        )

    predictions = []
    for fold, result in zip(plan.folds, report.folds):
        if (
            result.fold_index != fold.fold_index
            or result.fold_id != fold.fold_id
            or result.alpha != ridge_selection.selected_alpha
            or result.validation_count != fold.validation.row_count
        ):
            raise RidgeTradingThresholdSelectionError(
                "selected Ridge fold result differs from Walk-Forward fold"
            )
        try:
            values = _predict(
                fold.validation.X,
                result.intercept,
                result.coefficients,
            )
        except RidgeBaselineError as exc:
            raise RidgeTradingThresholdSelectionError(str(exc)) from exc

        for actual, predicted, metadata in zip(
            fold.validation.y,
            values,
            fold.validation.metadata,
        ):
            actual_value = _finite(
                actual,
                "actual validation return",
            )
            predicted_value = _finite(
                predicted,
                "predicted validation return",
            )
            prediction_id = _prediction_id(
                fold_index=fold.fold_index,
                fold_id=fold.fold_id,
                sample_key=metadata.sample_key,
                label_value_id=metadata.label_value_id,
                code=metadata.code,
                feature_window_close=metadata.feature_window_close,
                actual_label_end_time=metadata.actual_label_end_time,
                actual=actual_value,
                predicted=predicted_value,
            )
            predictions.append(
                RidgeValidationTradingPrediction(
                    prediction_id,
                    fold.fold_index,
                    fold.fold_id,
                    metadata.sample_key,
                    metadata.label_value_id,
                    metadata.code,
                    metadata.feature_window_close,
                    metadata.actual_label_end_time,
                    actual_value,
                    predicted_value,
                )
            )

    ordered = tuple(
        sorted(
            predictions,
            key=lambda item: (
                item.feature_window_close,
                item.code,
                item.sample_key,
            ),
        )
    )
    keys = tuple(item.sample_key for item in ordered)
    if len(keys) != len(set(keys)):
        raise RidgeTradingThresholdSelectionError(
            "Walk-Forward validation samples overlap across folds"
        )
    return ordered


def _candidate_id(
    *,
    threshold: float,
    costs: BacktestCosts,
    predictions_digest: str,
    metrics,
) -> str:
    return encode_identity(
        "market-vault-ridge-trading-threshold-candidate-v1",
        {
            "threshold": threshold,
            "commission_bps": costs.commission_bps,
            "slippage_bps": costs.slippage_bps,
            "predictions_digest": predictions_digest,
            "validation_sample_count": metrics["validation_sample_count"],
            "signal_count": metrics["signal_count"],
            "overlap_skipped_count": metrics["overlap_skipped_count"],
            "trade_count": metrics["trade_count"],
            "gross_total_return": metrics["gross_total_return"],
            "total_return": metrics["total_return"],
            "realized_max_drawdown": metrics["realized_max_drawdown"],
            "win_rate": metrics["win_rate"],
            "average_trade_return": metrics["average_trade_return"],
            "profit_factor": metrics["profit_factor"],
            "average_signal_to_exit_seconds": (
                metrics["average_signal_to_exit_seconds"]
            ),
        },
    )


def _evaluate_threshold(
    predictions: tuple[RidgeValidationTradingPrediction, ...],
    *,
    threshold: float,
    costs: BacktestCosts,
):
    equity = 1.0
    gross_equity = 1.0
    peak = 1.0
    drawdown = 0.0
    signal_count = 0
    skipped = 0
    trade_count = 0
    gains = 0.0
    losses = 0.0
    net_returns = []
    duration_sum = 0.0
    last_exit = None

    for prediction in predictions:
        if prediction.predicted <= threshold:
            continue
        signal_count += 1
        if (
            last_exit is not None
            and prediction.feature_window_close < last_exit
        ):
            skipped += 1
            continue

        gross_multiplier = 1.0 + prediction.actual
        side_multiplier = 1.0 - costs.per_side_rate
        net_multiplier = (
            gross_multiplier
            * side_multiplier
            * side_multiplier
        )
        net_return = net_multiplier - 1.0
        if net_return <= -1.0 or not math.isfinite(net_return):
            raise RidgeTradingThresholdSelectionError(
                "cost-adjusted validation trade return is invalid"
            )

        before = equity
        after = before * net_multiplier
        pnl = after - before
        if pnl > 0.0:
            gains += pnl
        elif pnl < 0.0:
            losses += -pnl

        trade_count += 1
        net_returns.append(net_return)
        equity = after
        gross_equity *= gross_multiplier
        peak = max(peak, equity)
        drawdown = max(drawdown, 1.0 - equity / peak)
        duration_sum += (
            prediction.actual_label_end_time
            - prediction.feature_window_close
        ).total_seconds()
        last_exit = prediction.actual_label_end_time

    return {
        "validation_sample_count": len(predictions),
        "signal_count": signal_count,
        "overlap_skipped_count": skipped,
        "trade_count": trade_count,
        "gross_total_return": gross_equity - 1.0,
        "total_return": equity - 1.0,
        "realized_max_drawdown": drawdown,
        "win_rate": (
            sum(value > 0.0 for value in net_returns) / trade_count
            if trade_count else 0.0
        ),
        "average_trade_return": (
            math.fsum(net_returns) / trade_count
            if trade_count else 0.0
        ),
        "profit_factor": gains / losses if losses > 0.0 else None,
        "average_signal_to_exit_seconds": (
            duration_sum / trade_count if trade_count else 0.0
        ),
    }


def _selection_id(
    *,
    ridge_selection_id: str,
    walk_forward_id: str,
    dataset_id: str,
    label_name: str,
    selected_alpha: float,
    costs: BacktestCosts,
    predictions_digest: str,
    candidates: tuple[RidgeTradingThresholdCandidate, ...],
    selected: RidgeTradingThresholdCandidate,
) -> str:
    return encode_identity(
        RIDGE_TRADING_THRESHOLD_SELECTION_VERSION,
        {
            "ridge_selection_id": ridge_selection_id,
            "walk_forward_id": walk_forward_id,
            "dataset_id": dataset_id,
            "label_name": label_name,
            "selected_alpha": selected_alpha,
            "metric": RIDGE_TRADING_THRESHOLD_SELECTION_METRIC,
            "commission_bps": costs.commission_bps,
            "slippage_bps": costs.slippage_bps,
            "predictions_digest": predictions_digest,
            "candidate_ids_digest": _members_digest(
                "market-vault-ridge-trading-threshold-candidate-ids-v1",
                tuple(item.candidate_id for item in candidates),
            ),
            "selected_threshold": selected.threshold,
            "selected_candidate_id": selected.candidate_id,
        },
    )


def select_ridge_trading_threshold(
    dataset: VerifiedMultiSourceCrossDayDataset,
    bundle: ExperimentDatasetBundle,
    plan: WalkForwardPlan,
    ridge_selection: RidgeAlphaSelectionResult,
    *,
    thresholds,
    commission_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> RidgeTradingThresholdSelectionResult:
    """Select one Ridge trading threshold from Walk-Forward VALIDATION only."""
    try:
        costs = BacktestCosts(
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
        )
    except BacktestError as exc:
        raise RidgeTradingThresholdSelectionError(str(exc)) from exc
    normalized = _thresholds(thresholds)

    try:
        _, rebuilt = validate_execution_safe_experiment(
            dataset,
            bundle,
        )
    except TradingAuthorityError as exc:
        raise RidgeTradingThresholdSelectionError(str(exc)) from exc

    if type(plan) is not WalkForwardPlan:
        raise RidgeTradingThresholdSelectionError(
            "threshold selection requires WalkForwardPlan"
        )
    if type(ridge_selection) is not RidgeAlphaSelectionResult:
        raise RidgeTradingThresholdSelectionError(
            "threshold selection requires RidgeAlphaSelectionResult"
        )
    if rebuilt.label_logical_type != "float64":
        raise RidgeTradingThresholdSelectionError(
            "threshold selection supports float64 return Labels only"
        )

    try:
        expected_plan = build_walk_forward_plan(
            rebuilt,
            minimum_train_periods=plan.minimum_train_periods,
            validation_periods=plan.validation_periods,
            step_periods=plan.step_periods,
        )
    except WalkForwardError as exc:
        raise RidgeTradingThresholdSelectionError(str(exc)) from exc
    if expected_plan != plan:
        raise RidgeTradingThresholdSelectionError(
            "WalkForwardPlan differs from the verified Experiment Dataset"
        )
    if (
        ridge_selection.walk_forward_id != plan.walk_forward_id
        or ridge_selection.dataset_id != plan.dataset_id
        or ridge_selection.feature_names != plan.feature_names
        or ridge_selection.label_name != plan.label_name
    ):
        raise RidgeTradingThresholdSelectionError(
            "Ridge alpha selection differs from Walk-Forward schema"
        )

    predictions = _validation_predictions(
        plan,
        ridge_selection,
    )
    predictions_digest = _members_digest(
        "market-vault-ridge-validation-trading-prediction-ids-v1",
        tuple(item.prediction_id for item in predictions),
    )

    candidates = []
    for threshold in normalized:
        metrics = _evaluate_threshold(
            predictions,
            threshold=threshold,
            costs=costs,
        )
        candidate_id = _candidate_id(
            threshold=threshold,
            costs=costs,
            predictions_digest=predictions_digest,
            metrics=metrics,
        )
        candidates.append(
            RidgeTradingThresholdCandidate(
                candidate_id,
                threshold,
                metrics["validation_sample_count"],
                metrics["signal_count"],
                metrics["overlap_skipped_count"],
                metrics["trade_count"],
                metrics["gross_total_return"],
                metrics["total_return"],
                metrics["realized_max_drawdown"],
                metrics["win_rate"],
                metrics["average_trade_return"],
                metrics["profit_factor"],
                metrics["average_signal_to_exit_seconds"],
            )
        )
    candidate_tuple = tuple(candidates)
    selected = max(
        candidate_tuple,
        key=lambda item: (
            item.total_return,
            -item.realized_max_drawdown,
            item.threshold,
        ),
    )
    selection_id = _selection_id(
        ridge_selection_id=ridge_selection.selection_id,
        walk_forward_id=plan.walk_forward_id,
        dataset_id=plan.dataset_id,
        label_name=plan.label_name,
        selected_alpha=ridge_selection.selected_alpha,
        costs=costs,
        predictions_digest=predictions_digest,
        candidates=candidate_tuple,
        selected=selected,
    )
    return RidgeTradingThresholdSelectionResult(
        RIDGE_TRADING_THRESHOLD_SELECTION_VERSION,
        selection_id,
        ridge_selection.selection_id,
        plan.walk_forward_id,
        plan.dataset_id,
        plan.feature_names,
        plan.label_name,
        ridge_selection.selected_alpha,
        RIDGE_TRADING_THRESHOLD_SELECTION_METRIC,
        costs,
        predictions,
        predictions_digest,
        candidate_tuple,
        selected.threshold,
        selected.candidate_id,
    )
