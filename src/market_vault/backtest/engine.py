"""Deterministic single-symbol Long/Flat Backtest Engine V1.

Backtest V1 consumes a live-issued or strictly verified Research Dataset.
Signals may use Feature fields only; Label fields are never admitted as signal
inputs. Realized PnL must come from the execution-safe
forward_open_to_close_return Cross-Day Label family.

A trade signal is observed at feature_window_close, enters at the first future
same-slot bar open proven by the Label decision, and exits at that Label's
actual end time. Full-notional Long trades are non-overlapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math

from ..cross_day.identity import label_spec_pin_id
from ..cross_day_dataset import (
    MultiSourceCrossDayDatasetResult,
    VerifiedMultiSourceCrossDayDataset,
    multi_source_cross_day_dataset_id,
)
from ..cross_day_dataset import execution as dataset_execution
from ..cross_day_dataset._validation import MultiSourceCrossDayDatasetError
from ..cross_day_dataset.artifact_models import MultiSourceCrossDayArtifactError
from ..dataset.encoding import DatasetError, encode_identity
from .models import (
    BACKTEST_ENGINE_VERSION,
    BACKTEST_SPLITS,
    BacktestCosts,
    BacktestError,
    BacktestMetrics,
    BacktestResult,
    BacktestRule,
    BacktestTrade,
)


_EXECUTION_SAFE_RETURN_REF = (
    "market_vault.dataset.label_transforms.forward_open_to_close_return:"
    "forward_open_to_close_return"
)


@dataclass(frozen=True, slots=True)
class _Candidate:
    sample_key: str
    code: str
    signal_time: datetime
    entry_time: datetime
    exit_time: datetime
    signal_value: float
    gross_return: float


def _finite(value, label: str) -> float:
    if type(value) is bool or not isinstance(value, (int, float)):
        raise BacktestError(f"{label} must be a real number")
    result = float(value)
    if not math.isfinite(result):
        raise BacktestError(f"{label} must be finite")
    return 0.0 if result == 0.0 else result


def _admit_dataset(dataset):
    if type(dataset) is MultiSourceCrossDayDatasetResult:
        try:
            dataset_execution._require_live_issued_multi_source_cross_day_dataset_result(
                dataset
            )
        except (MultiSourceCrossDayDatasetError, TypeError, ValueError) as exc:
            raise BacktestError("unissued or changed logical Research Dataset") from exc
        return dataset
    if type(dataset) is VerifiedMultiSourceCrossDayDataset:
        try:
            dataset_id = multi_source_cross_day_dataset_id(dataset.identity_input)
        except (
            MultiSourceCrossDayDatasetError,
            MultiSourceCrossDayArtifactError,
            DatasetError,
            TypeError,
            ValueError,
        ) as exc:
            raise BacktestError("verified Research Dataset logical closure failed") from exc
        if dataset_id != dataset.dataset_id:
            raise BacktestError("verified Research Dataset ID mismatch")
        for name in (
            "scope",
            "dataset_as_of",
            "schema",
            "rows",
            "sample_audit",
            "completion",
            "split_result",
            "feature_pit",
            "ts2_features",
            "observation_pit",
            "observation_features",
            "cross_day_association",
            "cross_day_labels",
            "schedule",
        ):
            if getattr(dataset, name) != getattr(dataset.identity_input, name):
                raise BacktestError(
                    f"verified Research Dataset projection mismatch: {name}"
                )
        return dataset
    raise BacktestError(
        "Backtest V1 requires a live-issued or verified Cross-Day Research Dataset"
    )


def _schema_index(dataset) -> dict[str, int]:
    fields = tuple(dataset.schema.fields)
    names = tuple(field.name for field in fields)
    if len(names) != len(set(names)):
        raise BacktestError("Research Dataset schema contains duplicate fields")
    return {name: index for index, name in enumerate(names)}


def _signal_feature_names(dataset) -> frozenset[str]:
    ts2 = tuple(spec.name for spec in dataset.ts2_features.feature_specs)
    observation_specs = dataset.identity_input.observation_feature_specs
    observation = tuple(spec.name for spec in observation_specs)
    names = ts2 + observation
    if len(names) != len(set(names)):
        raise BacktestError("Research Dataset Feature names are not unique")
    return frozenset(names)


def _return_spec(dataset, return_label: str):
    matches = tuple(
        spec for spec in dataset.cross_day_labels.label_specs
        if spec.name == return_label
    )
    if len(matches) != 1:
        raise BacktestError("return_label must select exactly one Dataset Label")
    spec = matches[0]
    if (
        spec.transform_ref != _EXECUTION_SAFE_RETURN_REF
        or spec.output.logical_type != "float64"
        or spec.input_canonical_fields != ("open", "close")
    ):
        raise BacktestError(
            "Backtest V1 PnL requires forward_open_to_close_return Label semantics"
        )
    return spec


def _compare(value: float, rule: BacktestRule) -> bool:
    if rule.comparator == "GT":
        return value > rule.threshold
    if rule.comparator == "GE":
        return value >= rule.threshold
    if rule.comparator == "LT":
        return value < rule.threshold
    if rule.comparator == "LE":
        return value <= rule.threshold
    raise BacktestError("unreachable comparator")


def _candidates(dataset, rule: BacktestRule, return_label: str, split: str):
    if split not in BACKTEST_SPLITS:
        raise BacktestError("split must be TRAIN, VALIDATION, or TEST")
    if len(dataset.scope.symbols) != 1:
        raise BacktestError("Backtest V1 supports exactly one Dataset symbol")
    feature_names = _signal_feature_names(dataset)
    if rule.signal_field not in feature_names:
        raise BacktestError("signal_field must be an admitted Feature, never a Label")

    spec = _return_spec(dataset, return_label)
    target_pin = label_spec_pin_id(spec)
    decisions = {
        (decision.sample_key, decision.label_spec_pin_id): decision
        for decision in dataset.cross_day_association.decisions
    }
    label_values = {
        (value.sample_key, value.label_name): value
        for value in dataset.cross_day_labels.values
    }
    if len(label_values) != len(dataset.cross_day_labels.values):
        raise BacktestError("Cross-Day Label values contain duplicate sample/name pairs")
    index = _schema_index(dataset)
    for required in (
        "code",
        "sample_key",
        "feature_window_close",
        "label_status",
        "final_split",
        "assignment_status",
        rule.signal_field,
        return_label,
    ):
        if required not in index:
            raise BacktestError(f"Research Dataset field is missing: {required}")

    field_types = {field.name: field.logical_type for field in dataset.schema.fields}
    if field_types[rule.signal_field] not in ("float64", "int64"):
        raise BacktestError("signal_field must be numeric")
    if field_types[return_label] != "float64":
        raise BacktestError("return_label must be float64")

    result = []
    for row in dataset.rows:
        values = {name: row[position] for name, position in index.items()}
        if (
            values["assignment_status"] != "ASSIGNED"
            or values["final_split"] != split
            or values["label_status"] != "COMPLETE"
        ):
            continue
        if values["code"] != dataset.scope.symbols[0]:
            raise BacktestError("Dataset row code differs from the sole Dataset symbol")
        sample_key = values["sample_key"]
        decision = decisions.get((sample_key, target_pin))
        label_value = label_values.get((sample_key, return_label))
        if (
            decision is None
            or decision.status != "COMPLETE"
            or not decision.selected_rows
            or label_value is None
            or label_value.status != "COMPLETE"
            or label_value.spec_pin.content_sha256 != spec.content_sha256
        ):
            raise BacktestError("execution-safe Label decision/value evidence is missing")
        signal_time = values["feature_window_close"]
        entry_time = decision.selected_rows[0].event_time
        exit_time = label_value.actual_label_end_time
        if exit_time != decision.actual_label_end_time:
            raise BacktestError("selected Label value/decision exit time mismatch")
        if not (
            type(signal_time) is datetime
            and type(entry_time) is datetime
            and type(exit_time) is datetime
            and signal_time.tzinfo is not None
            and entry_time.tzinfo is not None
            and exit_time.tzinfo is not None
            and signal_time < entry_time < exit_time
        ):
            raise BacktestError("execution-safe trade timing is invalid")
        signal_value = _finite(values[rule.signal_field], "signal value")
        gross_return = _finite(label_value.value, "return Label value")
        row_return = _finite(values[return_label], "Dataset return Label value")
        if row_return != gross_return:
            raise BacktestError("Dataset row/selected Label value mismatch")
        if gross_return <= -1.0:
            raise BacktestError("return Label must be greater than -100%")
        result.append(_Candidate(
            sample_key,
            values["code"],
            signal_time,
            entry_time,
            exit_time,
            signal_value,
            gross_return,
        ))
    return tuple(sorted(result, key=lambda item: (item.signal_time, item.sample_key)))


def _trade_id(trade: BacktestTrade) -> str:
    return encode_identity(
        "market-vault-backtest-trade-v1",
        {
            "sample_key": trade.sample_key,
            "code": trade.code,
            "signal_time": trade.signal_time,
            "entry_time": trade.entry_time,
            "exit_time": trade.exit_time,
            "signal_value": trade.signal_value,
            "gross_return": trade.gross_return,
            "net_return": trade.net_return,
            "equity_before": trade.equity_before,
            "equity_after": trade.equity_after,
        },
    )


def _run_candidates(
    candidates: tuple[_Candidate, ...],
    *,
    rule: BacktestRule,
    costs: BacktestCosts,
):
    equity = 1.0
    gross_equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    signals = 0
    skipped = 0
    last_exit = None
    trades = []
    gains = 0.0
    losses = 0.0
    total_holding = 0.0

    for candidate in candidates:
        if not _compare(candidate.signal_value, rule):
            continue
        signals += 1
        if last_exit is not None and candidate.entry_time < last_exit:
            skipped += 1
            continue

        gross_multiplier = 1.0 + candidate.gross_return
        side_multiplier = 1.0 - costs.per_side_rate
        net_multiplier = gross_multiplier * side_multiplier * side_multiplier
        net_return = net_multiplier - 1.0
        if net_return <= -1.0 or not math.isfinite(net_return):
            raise BacktestError("cost-adjusted trade return is invalid")

        before = equity
        after = before * net_multiplier
        gross_equity *= gross_multiplier
        pnl = after - before
        if pnl > 0.0:
            gains += pnl
        elif pnl < 0.0:
            losses += -pnl

        trade = BacktestTrade(
            candidate.sample_key,
            candidate.code,
            candidate.signal_time,
            candidate.entry_time,
            candidate.exit_time,
            candidate.signal_value,
            candidate.gross_return,
            net_return,
            before,
            after,
        )
        trades.append(trade)
        equity = after
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, 1.0 - equity / peak)
        total_holding += (candidate.exit_time - candidate.entry_time).total_seconds()
        last_exit = candidate.exit_time

    trade_count = len(trades)
    win_rate = (
        sum(trade.net_return > 0.0 for trade in trades) / trade_count
        if trade_count else 0.0
    )
    average_return = (
        sum(trade.net_return for trade in trades) / trade_count
        if trade_count else 0.0
    )
    profit_factor = gains / losses if losses > 0.0 else None
    average_holding = total_holding / trade_count if trade_count else 0.0

    if candidates:
        universe_start = min(item.entry_time for item in candidates)
        universe_end = max(item.exit_time for item in candidates)
        duration = (universe_end - universe_start).total_seconds()
        exposure = (
            min(1.0, total_holding / duration)
            if duration > 0.0
            else (1.0 if trade_count else 0.0)
        )
    else:
        exposure = 0.0

    metrics = BacktestMetrics(
        candidate_count=len(candidates),
        signal_count=signals,
        overlap_skipped_count=skipped,
        trade_count=trade_count,
        gross_total_return=gross_equity - 1.0,
        total_return=equity - 1.0,
        max_drawdown=max_drawdown,
        win_rate=win_rate,
        average_trade_return=average_return,
        profit_factor=profit_factor,
        average_holding_seconds=average_holding,
        exposure=exposure,
    )
    return tuple(trades), metrics


def _backtest_id(
    *,
    dataset_id: str,
    split: str,
    rule: BacktestRule,
    return_label: str,
    costs: BacktestCosts,
    trades: tuple[BacktestTrade, ...],
) -> str:
    trade_ids = tuple(_trade_id(trade) for trade in trades)
    trade_digest = encode_identity(
        "market-vault-backtest-trades-v1",
        {"count": len(trade_ids), "members": "".join(trade_ids)},
    )
    return encode_identity(
        BACKTEST_ENGINE_VERSION,
        {
            "dataset_id": dataset_id,
            "split": split,
            "signal_field": rule.signal_field,
            "comparator": rule.comparator,
            "threshold": rule.threshold,
            "return_label": return_label,
            "commission_bps": costs.commission_bps,
            "slippage_bps": costs.slippage_bps,
            "trade_count": len(trades),
            "trades_digest": trade_digest,
        },
    )


def run_backtest(
    dataset,
    *,
    signal_field: str,
    comparator: str,
    threshold: float,
    return_label: str,
    split: str = "TEST",
    commission_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> BacktestResult:
    """Run deterministic single-symbol Long/Flat Backtest V1."""
    dataset = _admit_dataset(dataset)
    rule = BacktestRule(signal_field, comparator, threshold)
    costs = BacktestCosts(commission_bps, slippage_bps)
    candidates = _candidates(dataset, rule, return_label, split)
    trades, metrics = _run_candidates(candidates, rule=rule, costs=costs)
    backtest_id = _backtest_id(
        dataset_id=dataset.dataset_id,
        split=split,
        rule=rule,
        return_label=return_label,
        costs=costs,
        trades=trades,
    )
    return BacktestResult(
        backtest_id,
        BACKTEST_ENGINE_VERSION,
        dataset.dataset_id,
        split,
        rule,
        return_label,
        costs,
        trades,
        metrics,
    )
