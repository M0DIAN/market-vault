"""Accounting, exact-clock coverage and verified Dataset/CLI equity paths."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from market_vault import cli, strategy_comparison_cli
from market_vault.backtest.engine import _Candidate, _run_candidates
from market_vault.backtest.equity import EquityBar, EquityError, PricedTrade, build_equity_curve
from market_vault.backtest.models import BacktestCosts, BacktestRule
from market_vault.cross_day.schedule import TradingDayRecord
from market_vault.research.strategy_comparison import compare_strategies
from market_vault.research import strategy_equity
from market_vault.research.strategy_equity import compare_strategies_with_equity
from test_strategy_comparison import verified_workspace_dataset, _plan, _real_config


START = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)


def _bars(values=((100, 60), (60, 110), (110, 120), (120, 100))):
    return tuple(EquityBar(
        f"{index + 1:064x}", START + timedelta(minutes=5 * index),
        START + timedelta(minutes=5 * (index + 1)), opened, closed,
    ) for index, (opened, closed) in enumerate(values))


def _trades(bars, spans, costs):
    candidates = tuple(_Candidate(
        f"{index + 100:064x}", "US.SPY", bars[first].event_time - timedelta(minutes=1),
        bars[first].event_time, bars[last].close_time, 1,
        bars[last].close / bars[first].open - 1,
    ) for index, (first, last) in enumerate(spans))
    trades, metrics = _run_candidates(candidates, rule=BacktestRule("signal", "GT", 0), costs=costs)
    return tuple(PricedTrade(trade, bars[first].row_version_id, bars[last].row_version_id)
                 for trade, (first, last) in zip(trades, spans, strict=True)), metrics


def _curve(bars, trades=(), costs=BacktestCosts(), **overrides):
    return build_equity_curve(**{
        "trades": trades, "bars": bars, "costs": costs,
        "valuation_times": tuple(bar.close_time for bar in bars),
        "start_time": START, "end_time": bars[-1].close_time, **overrides,
    })


def test_profitable_trade_reveals_intermediate_loss_without_lookahead():
    bars = _bars()[:2]
    trades, metrics = _trades(bars, ((0, 1),), BacktestCosts())
    curve = _curve(bars, trades)
    assert metrics.realized_max_drawdown == 0
    assert curve.bar_close_max_drawdown == pytest.approx(0.4)
    assert curve.final_equity == pytest.approx(1.1)
    entry = next(point for point in curve.points if point.event == "ENTRY")
    assert entry.timestamp == START
    assert entry.mark_price == 100  # close=60 is unavailable at entry.
    assert entry.quantity == pytest.approx(0.01)
    assert entry.cash == 0
    assert curve.points[2].timestamp == bars[0].close_time
    assert curve.points[2].equity == pytest.approx(0.6)


@pytest.mark.parametrize("costs", [BacktestCosts(), BacktestCosts(10, 5)])
def test_costs_reconcile_and_equal_time_exit_precedes_next_entry(costs):
    bars = _bars()
    trades, metrics = _trades(bars, ((0, 1), (2, 3)), costs)
    curve = _curve(bars, trades, costs)
    assert curve.final_equity == pytest.approx(1 + metrics.total_return)
    assert curve.final_equity == pytest.approx((1 - costs.per_side_rate) ** 4)
    assert [p.event for p in curve.points if p.timestamp == bars[1].close_time] == [
        "BAR_CLOSE", "EXIT", "ENTRY",
    ]
    for point in curve.points:
        assert point.equity == pytest.approx(point.cash + point.market_value)
        assert point.market_value == pytest.approx(point.quantity * (point.mark_price or 0))
    assert curve.transaction_cost_total == pytest.approx(sum(p.transaction_cost for p in curve.points))
    for trade in trades:
        exit_point = next(p for p in curve.points if p.event == "EXIT" and p.sample_key == trade.trade.sample_key)
        assert exit_point.quantity == 0
        assert exit_point.cash == pytest.approx(trade.trade.equity_after)
    assert _curve(bars, trades, costs) == curve


def test_missing_held_bar_fails_but_cash_needs_no_invented_quote():
    bars = _bars()
    trades, _ = _trades(bars, ((0, 3),), BacktestCosts())
    incomplete = (bars[0], bars[2], bars[3])
    times = tuple(b.close_time for b in bars)
    with pytest.raises(EquityError, match="missing held-position"):
        _curve(incomplete, trades, valuation_times=times)
    flat = _curve(incomplete, valuation_times=times)
    assert flat.final_equity == 1
    assert flat.bar_close_max_drawdown == 0
    missing = next(p for p in flat.points if p.timestamp == bars[1].close_time)
    assert missing.mark_price is None
    assert missing.cash == 1 and missing.market_value == 0


def test_execution_version_and_return_reconciliation_reject_mismatch():
    bars = _bars()
    trades, _ = _trades(bars, ((0, 3),), BacktestCosts())
    with pytest.raises(EquityError, match="execution price version"):
        _curve(bars, (replace(trades[0], entry_row_version_id="f" * 64),))
    with pytest.raises(EquityError, match="price/cost ledger"):
        _curve((replace(bars[0], open=101),) + bars[1:], trades)
    with pytest.raises(EquityError, match="strictly positive"):
        replace(bars[0], close=0)


def _schedule_dataset(days, *, closed_days=()):
    from zoneinfo import ZoneInfo
    zone = ZoneInfo("America/New_York")
    records = []
    for day in days:
        opened = datetime(day.year, day.month, day.day, 9, 30, tzinfo=zone)
        closed = opened + timedelta(hours=6, minutes=30)
        records.append(TradingDayRecord(
            day, "CLOSED" if day in closed_days else "TRADING",
            None if day in closed_days else opened, None if day in closed_days else closed,
            None if day in closed_days else "NORMAL",
        ))
    return SimpleNamespace(
        scope=SimpleNamespace(interval="5m"),
        schedule=SimpleNamespace(daily_records=tuple(records), market_timezone="America/New_York",
                                 coverage_start_date=days[0], coverage_end_date=days[-1]),
    )


def test_complete_session_grid_detects_a_missing_whole_held_day():
    dataset = _schedule_dataset([date(2026, 1, day) for day in (5, 6, 7)])
    start = START + timedelta(hours=6, minutes=25)
    end = START + timedelta(days=2, minutes=5)
    bars = (
        EquityBar("1" * 64, start, start + timedelta(minutes=5), 100, 100),
        EquityBar("2" * 64, end - timedelta(minutes=5), end, 100, 110),
    )
    trades, _ = _trades(bars, ((0, 1),), BacktestCosts())
    grid = strategy_equity._valuation_grid(dataset, start, end)
    assert len(grid) == 80  # Monday tail + complete Tuesday + Wednesday first bar.
    with pytest.raises(EquityError, match="2026-01-06T14:35"):
        _curve(bars, trades, start_time=start, valuation_times=tuple(grid.values()))


def test_weekend_needs_no_quotes_and_future_archived_price_is_not_used():
    days = [date(2026, 1, day) for day in (9, 10, 11, 12)]
    dataset = _schedule_dataset(days, closed_days=days[1:3])
    start = START + timedelta(days=4, hours=6, minutes=25)
    end = START + timedelta(days=7, minutes=5)
    grid = strategy_equity._valuation_grid(dataset, start, end)
    assert len(grid) == 2
    bar = SimpleNamespace(
        code="US.SPY", event_time=start, market_available_at=start + timedelta(minutes=5),
        archive_available_at=end + timedelta(days=1), canonical_row_version_id="a" * 64,
        open=100, close=101,
    )
    dataset.scope.symbols = ("US.SPY",)
    dataset.dataset_as_of = end
    dataset.identity_input = SimpleNamespace(canonical_builds=(SimpleNamespace(bars=(bar,)),))
    assert strategy_equity._valuation_bars(dataset, grid) == ()


@pytest.mark.parametrize("day,closing_hour", [(date(2026, 1, 5), 16), (date(2025, 11, 28), 13)])
def test_sixty_minute_tail_preserves_recorded_conservative_close_clock(day, closing_hour):
    from zoneinfo import ZoneInfo
    zone = ZoneInfo("America/New_York")
    opened = datetime(day.year, day.month, day.day, 9, 30, tzinfo=zone)
    closed = datetime(day.year, day.month, day.day, closing_hour, tzinfo=zone)
    record = TradingDayRecord(day, "TRADING", opened, closed,
                              "NORMAL" if closing_hour == 16 else "QUALIFIED_EARLY_CLOSE")
    dataset = SimpleNamespace(
        scope=SimpleNamespace(interval="60m"),
        schedule=SimpleNamespace(daily_records=(record,), market_timezone="America/New_York",
                                 coverage_start_date=day, coverage_end_date=day),
    )
    end = closed + timedelta(minutes=30)
    grid = strategy_equity._valuation_grid(dataset, opened, end)
    assert max(grid.values()) == end  # Never clamp 16:30/13:30 to the session close.
    assert max(grid) == closed - timedelta(minutes=30)


def test_verified_comparison_equity_and_cli_preserve_v1(verified_workspace_dataset, tmp_path, monkeypatch, capsys):
    dataset = verified_workspace_dataset
    original = compare_strategies(dataset, **_real_config())
    report = compare_strategies_with_equity(dataset, **_real_config())
    assert report.comparison == original
    assert len(report.results) == 3
    for valued, result in zip(report.results, original.results, strict=True):
        assert valued.strategy_result_id == result.result_id
        assert valued.curve.final_equity == pytest.approx(1 + result.metrics.total_return)
        assert valued.curve.bar_close_max_drawdown >= result.metrics.realized_max_drawdown - 1e-12
        assert valued.curve.points[0].timestamp == report.start_time
        assert valued.curve.points[-1].timestamp == report.end_time
    # The one continuous holding stream includes overnight marks, independent
    # of which validation fold generated the next accepted signal.
    assert len(report.results[0].curve.points) > len(original.validation_sample_keys)
    plan = tmp_path / "equity.json"
    plan.write_text(json.dumps(_plan(dataset.build_path)), encoding="utf-8")
    monkeypatch.setattr(cli, "load_settings", lambda *a, **k: pytest.fail("equity CLI loaded settings"))
    assert cli.main(["research-compare-strategies", "--plan", str(plan), "--equity-curve"]) == 0
    output = capsys.readouterr()
    payload = json.loads(output.out)
    assert output.err == ""
    assert payload["result_schema_version"] == strategy_comparison_cli.STRATEGY_EQUITY_CLI_VERSION
    assert payload["comparison_id"] == original.comparison_id
    assert payload["equity"]["equity_comparison_id"] == report.equity_comparison_id
    assert payload["equity"]["results"][0]["points"][-1]["equity"] == report.results[0].curve.final_equity
    assert cli.main(["research-compare-strategies", "--plan", str(plan)]) == 0
    legacy = json.loads(capsys.readouterr().out)
    assert legacy == strategy_comparison_cli._success_payload(original)
    assert "equity" not in legacy


def test_verified_equity_continues_across_validation_gaps(verified_workspace_dataset):
    report = compare_strategies_with_equity(verified_workspace_dataset, **{
        **_real_config(), "validation_periods": 1, "step_periods": 3,
    })
    assert len(report.comparison.plan.folds) >= 2
    curve = report.results[0].curve
    assert curve.final_equity == pytest.approx(1 + report.comparison.results[0].metrics.total_return)
    first_exit = report.comparison.results[0].trades[0].exit_time
    second_entry = report.comparison.results[0].trades[1].entry_time
    assert second_entry > first_exit
    gap_points = [p for p in curve.points if first_exit < p.timestamp < second_entry]
    assert gap_points
    assert all(p.quantity == 0 and p.cash == pytest.approx(curve.points[0].cash *
        (1 + report.comparison.results[0].trades[0].net_return)) for p in gap_points)


def test_desktop_equity_worker_uses_verified_prices(verified_workspace_dataset):
    pytest.importorskip("PySide6")
    from market_vault.desktop.quant_research import _run_strategy_comparison
    view = _run_strategy_comparison(
        verified_workspace_dataset.build_path, trend_feature="return_2", trend_threshold=0,
        reversion_feature="return_2", reversion_threshold=0, ridge_alpha=1,
        ridge_threshold=0, return_label="execution_return_1d", minimum_train_periods=3,
        validation_periods=2, step_periods=2, commission_bps=10, slippage_bps=5,
        equity_curve=True,
    )
    assert len(view.summary["equity_comparison_id"]) == 64
    assert view.page.columns[-1] == "bar_close_max_drawdown"
    assert [item.name for item in view.equity] == ["Trend", "MeanReversion", "Ridge"]
    assert len(view.equity[0].rows) > 100
    assert all(point[1] == 1 for point in view.equity[1].series)
    assert view.equity[0].rows[-1][4] == "0"  # No remaining shares.


def test_equity_cli_failure_identifies_the_opt_in_schema(tmp_path, capsys):
    plan = tmp_path / "invalid-equity.json"
    plan.write_text(json.dumps({**_plan(tmp_path / "missing"), "step_periods": 0}), encoding="utf-8")
    assert cli.main(["research-compare-strategies", "--plan", str(plan), "--equity-curve"]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["result_schema_version"] == strategy_comparison_cli.STRATEGY_EQUITY_CLI_VERSION
