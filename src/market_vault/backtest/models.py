"""Frozen models for MarketVault Backtest Engine V1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
import re


BACKTEST_ENGINE_VERSION = "market-vault-backtest-v1"
BACKTEST_COMPARATORS = ("GT", "GE", "LT", "LE")
BACKTEST_SPLITS = ("TRAIN", "VALIDATION", "TEST")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class BacktestError(ValueError):
    """Fail-closed Backtest V1 input or execution error."""


def _finite_number(value, label: str) -> float:
    if type(value) is bool or not isinstance(value, (int, float)):
        raise BacktestError(f"{label} must be a real finite number")
    number = float(value)
    if not math.isfinite(number):
        raise BacktestError(f"{label} must be finite")
    return 0.0 if number == 0.0 else number


def _instant(value, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None:
        raise BacktestError(f"{label} must be a timezone-aware datetime")
    return value


@dataclass(frozen=True, slots=True)
class BacktestRule:
    signal_field: str
    comparator: str
    threshold: float

    def __post_init__(self) -> None:
        if type(self.signal_field) is not str or not self.signal_field:
            raise BacktestError("signal_field must be a non-empty string")
        if self.comparator not in BACKTEST_COMPARATORS:
            raise BacktestError(
                "comparator must be one of " + ", ".join(BACKTEST_COMPARATORS)
            )
        object.__setattr__(
            self,
            "threshold",
            _finite_number(self.threshold, "threshold"),
        )


@dataclass(frozen=True, slots=True)
class BacktestCosts:
    commission_bps: float = 0.0
    slippage_bps: float = 0.0

    def __post_init__(self) -> None:
        commission = _finite_number(self.commission_bps, "commission_bps")
        slippage = _finite_number(self.slippage_bps, "slippage_bps")
        if commission < 0.0 or slippage < 0.0:
            raise BacktestError("commission_bps and slippage_bps must be non-negative")
        if commission + slippage >= 10000.0:
            raise BacktestError("per-side total cost must be below 10000 bps")
        object.__setattr__(self, "commission_bps", commission)
        object.__setattr__(self, "slippage_bps", slippage)

    @property
    def per_side_rate(self) -> float:
        return (self.commission_bps + self.slippage_bps) / 10000.0


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    sample_key: str
    code: str
    signal_time: datetime
    entry_time: datetime
    exit_time: datetime
    signal_value: float
    gross_return: float
    net_return: float
    equity_before: float
    equity_after: float

    def __post_init__(self) -> None:
        if type(self.sample_key) is not str or _SHA256_RE.fullmatch(self.sample_key) is None:
            raise BacktestError("sample_key must be a 64-character lowercase hex identity")
        if type(self.code) is not str or not self.code:
            raise BacktestError("trade code must be a non-empty string")
        signal = _instant(self.signal_time, "signal_time")
        entry = _instant(self.entry_time, "entry_time")
        exit_ = _instant(self.exit_time, "exit_time")
        if not signal < entry < exit_:
            raise BacktestError("trade times must satisfy signal < entry < exit")
        for name in (
            "signal_value",
            "gross_return",
            "net_return",
            "equity_before",
            "equity_after",
        ):
            value = _finite_number(getattr(self, name), name)
            object.__setattr__(self, name, value)
        if self.gross_return <= -1.0 or self.net_return <= -1.0:
            raise BacktestError("trade returns must be greater than -100%")
        if self.equity_before <= 0.0 or self.equity_after <= 0.0:
            raise BacktestError("equity must remain positive")


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    candidate_count: int
    signal_count: int
    overlap_skipped_count: int
    trade_count: int
    gross_total_return: float
    total_return: float
    max_drawdown: float
    win_rate: float
    average_trade_return: float
    profit_factor: float | None
    average_holding_seconds: float
    exposure: float

    def __post_init__(self) -> None:
        for name in (
            "candidate_count",
            "signal_count",
            "overlap_skipped_count",
            "trade_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise BacktestError(f"{name} must be a non-negative integer")
        if self.trade_count > self.signal_count or self.signal_count > self.candidate_count:
            raise BacktestError("backtest counts are inconsistent")
        if self.overlap_skipped_count != self.signal_count - self.trade_count:
            raise BacktestError("overlap_skipped_count must equal signals minus trades")
        for name in (
            "gross_total_return",
            "total_return",
            "max_drawdown",
            "win_rate",
            "average_trade_return",
            "average_holding_seconds",
            "exposure",
        ):
            object.__setattr__(
                self,
                name,
                _finite_number(getattr(self, name), name),
            )
        if self.max_drawdown < 0.0:
            raise BacktestError("max_drawdown must be non-negative")
        if not 0.0 <= self.win_rate <= 1.0:
            raise BacktestError("win_rate must be within [0, 1]")
        if self.average_holding_seconds < 0.0:
            raise BacktestError("average_holding_seconds must be non-negative")
        if not 0.0 <= self.exposure <= 1.0:
            raise BacktestError("exposure must be within [0, 1]")
        if self.profit_factor is not None:
            value = _finite_number(self.profit_factor, "profit_factor")
            if value < 0.0:
                raise BacktestError("profit_factor must be non-negative")
            object.__setattr__(self, "profit_factor", value)


@dataclass(frozen=True, slots=True)
class BacktestResult:
    backtest_id: str
    engine_version: str
    dataset_id: str
    split: str
    rule: BacktestRule
    return_label: str
    costs: BacktestCosts
    trades: tuple[BacktestTrade, ...]
    metrics: BacktestMetrics

    def __post_init__(self) -> None:
        if type(self.backtest_id) is not str or len(self.backtest_id) != 64:
            raise BacktestError("backtest_id must be a 64-character identity")
        if self.engine_version != BACKTEST_ENGINE_VERSION:
            raise BacktestError("unsupported backtest engine version")
        if type(self.dataset_id) is not str or len(self.dataset_id) != 64:
            raise BacktestError("dataset_id must be a 64-character identity")
        if self.split not in BACKTEST_SPLITS:
            raise BacktestError("invalid backtest split")
        if type(self.rule) is not BacktestRule or type(self.costs) is not BacktestCosts:
            raise BacktestError("exact BacktestRule and BacktestCosts required")
        if type(self.return_label) is not str or not self.return_label:
            raise BacktestError("return_label must be a non-empty string")
        if type(self.trades) is not tuple or not all(
            type(item) is BacktestTrade for item in self.trades
        ):
            raise BacktestError("trades must be an exact immutable BacktestTrade tuple")
        if type(self.metrics) is not BacktestMetrics:
            raise BacktestError("exact BacktestMetrics required")
