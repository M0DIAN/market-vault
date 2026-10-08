"""Verified same-window price benchmark and daily strategy risk report."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ..backtest.equity import EquityCurve, build_buy_and_hold_curve
from ..backtest.risk import DailyRisk, SessionClose, calculate_daily_risk
from ..cross_day._authority import INTERVAL_MINUTES
from ..cross_day_dataset import VerifiedMultiSourceCrossDayDataset
from ..dataset.encoding import encode_identity, normalize_utc_datetime
from .strategy_comparison import Strategy, compare_strategies
from .strategy_equity import StrategyEquityReport, _value_verified_comparison


STRATEGY_RISK_VERSION = "market-vault-strategy-risk-v1"
BENCHMARK_DEFINITION = "SAME_SYMBOL_BUY_AND_HOLD_PRICE_RETURN"


@dataclass(frozen=True, slots=True)
class StrategyRiskResult:
    strategy_result_id: str
    total_return: float
    return_difference: float
    bar_close_max_drawdown: float
    daily_risk: DailyRisk


@dataclass(frozen=True, slots=True)
class StrategyRiskReport:
    version: str
    risk_report_id: str
    equity: StrategyEquityReport
    benchmark_definition: str
    benchmark_curve: EquityCurve
    benchmark_risk: DailyRisk
    results: tuple[StrategyRiskResult, ...]


def _session_closes(dataset, start: datetime, end: datetime) -> tuple[SessionClose, ...]:
    """Derive complete closes before clipping to the comparison window."""
    step = timedelta(minutes=INTERVAL_MINUTES[dataset.scope.interval])
    closes = []
    for day in dataset.schedule.daily_records:
        if day.day_status != "TRADING":
            continue
        opened = normalize_utc_datetime(day.session_open, "session_open")
        closed = normalize_utc_datetime(day.session_close, "session_close")
        slots, remainder = divmod(closed - opened, step)
        recorded_close = opened + step * (slots + bool(remainder))
        if start < recorded_close <= end:
            closes.append(SessionClose(day.market_calendar_date, recorded_close))
    return tuple(closes)


def compare_strategies_with_risk(
    dataset: VerifiedMultiSourceCrossDayDataset,
    *, feature_fields: tuple[str, ...], return_label: str, strategies: tuple[Strategy, ...],
    minimum_train_periods: int, validation_periods: int, step_periods: int | None = None,
    commission_bps: float = 0.0, slippage_bps: float = 0.0,
) -> StrategyRiskReport:
    """Compute explicit development strategies and a verified price benchmark.

    No caller-provided report is accepted as authority. The price benchmark
    buys once at the common window's first entry open and sells once at its
    final close. It uses the same instrument, prices, calendar and side costs.
    Daily statistics use recorded complete close endpoints, 252 trading days
    and zero risk-free rate. TEST remains outside strategy decisions.
    """
    comparison = compare_strategies(
        dataset, feature_fields=feature_fields, return_label=return_label, strategies=strategies,
        minimum_train_periods=minimum_train_periods, validation_periods=validation_periods,
        step_periods=step_periods, commission_bps=commission_bps, slippage_bps=slippage_bps,
    )
    equity, fresh, bars, valuation_times = _value_verified_comparison(dataset, comparison)
    benchmark = build_buy_and_hold_curve(
        bars=bars, valuation_times=valuation_times, start_time=equity.start_time,
        end_time=equity.end_time, costs=comparison.costs,
    )
    closes = _session_closes(fresh, equity.start_time, equity.end_time)
    benchmark_risk = calculate_daily_risk(benchmark, session_closes=closes)
    results = tuple(StrategyRiskResult(
        result.strategy_result_id, result.curve.final_equity - 1.0,
        result.curve.final_equity - benchmark.final_equity,
        result.curve.bar_close_max_drawdown,
        calculate_daily_risk(result.curve, session_closes=closes),
    ) for result in equity.results)
    report_id = encode_identity(STRATEGY_RISK_VERSION, {
        "equity_comparison_id": equity.equity_comparison_id,
        "benchmark_definition": BENCHMARK_DEFINITION,
        "benchmark_curve_id": benchmark.curve_id, "benchmark_risk_id": benchmark_risk.risk_id,
        "results": "".join(result.strategy_result_id + result.daily_risk.risk_id for result in results),
    })
    return StrategyRiskReport(
        STRATEGY_RISK_VERSION, report_id, equity, BENCHMARK_DEFINITION,
        benchmark, benchmark_risk, results,
    )
