"""Add verified bar-close valuation to an unchanged V1 strategy comparison."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..backtest.engine import _admit_dataset, _return_spec
from ..backtest.equity import EquityBar, EquityCurve, EquityError, PricedTrade, build_equity_curve
from ..cross_day._authority import INTERVAL_MINUTES
from ..cross_day.identity import label_spec_pin_id
from ..cross_day_dataset import VerifiedMultiSourceCrossDayDataset
from ..dataset.encoding import encode_identity, normalize_utc_datetime
from .strategy_comparison import Strategy, StrategyComparisonReport, _common_candidates, compare_strategies


STRATEGY_EQUITY_VERSION = "market-vault-strategy-equity-v1"


@dataclass(frozen=True, slots=True)
class StrategyEquityResult:
    strategy_result_id: str
    curve: EquityCurve


@dataclass(frozen=True, slots=True)
class StrategyEquityReport:
    version: str
    equity_comparison_id: str
    comparison: StrategyComparisonReport
    interval: str
    start_time: datetime
    end_time: datetime
    price_evidence_id: str
    results: tuple[StrategyEquityResult, ...]


def _valuation_grid(dataset, start: datetime, end: datetime):
    """Use declared sessions, including closed days and nominal 60m tails."""
    schedule = dataset.schedule
    step = timedelta(minutes=INTERVAL_MINUTES[dataset.scope.interval])
    zone = ZoneInfo(schedule.market_timezone)
    if (start.astimezone(zone).date() < schedule.coverage_start_date
            or end.astimezone(zone).date() > schedule.coverage_end_date):
        raise EquityError("valuation window exceeds the verified trading-day schedule")
    grid = {}
    for day in schedule.daily_records:
        if day.day_status != "TRADING":
            continue
        opened = normalize_utc_datetime(day.session_open, "session_open")
        closed = normalize_utc_datetime(day.session_close, "session_close")
        event = opened
        while event < closed:
            available = event + step
            if start < available <= end:
                grid[event] = available
            event += step
    if not grid or max(grid.values()) != end:
        raise EquityError("valuation end must match a declared bar's recorded close clock")
    return grid


def _valuation_bars(dataset, grid):
    # The strict reader has already checked all recorded builds, conflicts and
    # content identities. These are recorded views, not live Canonical objects.
    rows = {}
    cutoff = dataset.dataset_as_of
    code = dataset.scope.symbols[0]
    for build in dataset.identity_input.canonical_builds:
        for bar in build.bars:
            if bar.code != code or bar.event_time not in grid:
                continue
            if cutoff is not None and bar.archive_available_at > cutoff:
                continue
            if bar.market_available_at != grid[bar.event_time]:
                raise EquityError("valuation bar differs from its recorded nominal close clock")
            value = EquityBar(
                bar.canonical_row_version_id,
                normalize_utc_datetime(bar.event_time, "event_time"),
                normalize_utc_datetime(bar.market_available_at, "market_available_at"),
                bar.open, bar.close,
            )
            previous = rows.get(value.row_version_id)
            if previous is not None and previous != value:
                raise EquityError("conflicting valuation price version")
            rows[value.row_version_id] = value
    return tuple(sorted(rows.values(), key=lambda b: (b.close_time, b.row_version_id)))


def compare_strategies_with_equity(
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
) -> StrategyEquityReport:
    """Run V1's explicit research choices, then value its accepted trades.

    This entry recomputes comparison evidence; a caller-supplied report is not
    treated as trading authority. TEST remains excluded from the comparison.
    No Dataset, evaluation artifact or trading account is written.
    """
    comparison = compare_strategies(
        dataset, feature_fields=feature_fields, return_label=return_label,
        strategies=strategies, minimum_train_periods=minimum_train_periods,
        validation_periods=validation_periods, step_periods=step_periods,
        commission_bps=commission_bps, slippage_bps=slippage_bps,
    )
    return _value_verified_comparison(dataset, comparison)[0]


def _value_verified_comparison(dataset, comparison):
    """Share one admitted valuation context with additive research reports."""
    fresh = _admit_dataset(dataset)
    if fresh.dataset_id != comparison.plan.dataset_id:
        raise EquityError("Dataset identity differs from the strategy comparison")
    candidates, _ = _common_candidates(fresh, comparison.plan)
    start = min(item.entry_time for item in candidates)
    end = max(item.exit_time for item in candidates)
    grid = _valuation_grid(fresh, start, end)
    bars = _valuation_bars(fresh, grid)
    price_id = encode_identity(STRATEGY_EQUITY_VERSION + ":prices", {
        "dataset_id": fresh.dataset_id,
        "schedule_id": fresh.schedule.schedule_content_id,
        "start_time": start, "end_time": end,
        "bar_count": len(bars),
        "bars": "".join(encode_identity(STRATEGY_EQUITY_VERSION + ":bar", asdict(bar)) for bar in bars),
    })
    pin = label_spec_pin_id(_return_spec(fresh, comparison.plan.label_name))
    decisions = {
        d.sample_key: d for d in fresh.cross_day_association.decisions
        if d.label_spec_pin_id == pin
    }
    results = []
    for result in comparison.results:
        priced = tuple(PricedTrade(
            trade,
            decisions[trade.sample_key].selected_rows[0].canonical_row_version_id,
            decisions[trade.sample_key].selected_rows[-1].canonical_row_version_id,
        ) for trade in result.trades)
        curve = build_equity_curve(
            trades=priced, bars=bars, valuation_times=tuple(grid.values()),
            start_time=start, end_time=end, costs=comparison.costs,
        )
        results.append(StrategyEquityResult(result.result_id, curve))
    equity_id = encode_identity(STRATEGY_EQUITY_VERSION, {
        "comparison_id": comparison.comparison_id, "price_evidence_id": price_id,
        "results": "".join(r.strategy_result_id + r.curve.curve_id for r in results),
    })
    report = StrategyEquityReport(
        STRATEGY_EQUITY_VERSION, equity_id, comparison, fresh.scope.interval,
        start, end, price_id, tuple(results),
    )
    return report, fresh, bars, tuple(grid.values())
