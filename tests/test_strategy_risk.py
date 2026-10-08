"""Price benchmark, complete-session statistics and real Research entry tests."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import json
import math
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from market_vault import cli, strategy_comparison_cli
from market_vault.backtest.equity import (
    EquityCurve, EquityError, EquityPoint, build_buy_and_hold_curve,
)
from market_vault.backtest.models import BacktestCosts
from market_vault.backtest.risk import SessionClose, calculate_daily_risk
from market_vault.cross_day import TradingDayRecord
from market_vault.research.strategy_equity import compare_strategies_with_equity
from market_vault.research.strategy_risk import _session_closes, compare_strategies_with_risk
from test_strategy_equity import START, _bars, _curve
from test_strategy_comparison import _plan, _real_config, verified_workspace_dataset  # noqa: F401


def _point(timestamp, equity, event="BAR_CLOSE"):
    return EquityPoint(timestamp, event, equity, 0, None, 0, equity, 0, 0, None, None)


def _account(points):
    return EquityCurve("test", "e" * 64, tuple(points), points[-1].equity, 0, 0)


def test_buy_hold_costs_and_intermediate_drawdown_share_accounting():
    bars = _bars()[:2]  # 100 -> 60 -> 110
    curve = build_buy_and_hold_curve(
        bars=bars, valuation_times=tuple(b.close_time for b in bars),
        start_time=START, end_time=bars[-1].close_time, costs=BacktestCosts(100, 0),
    )
    assert [p.event for p in curve.points] == ["INITIAL", "ENTRY", "BAR_CLOSE", "BAR_CLOSE", "EXIT"]
    assert curve.points[1].quantity == pytest.approx(0.0099)
    assert curve.points[2].equity == pytest.approx(0.594)
    assert curve.final_equity == pytest.approx(1.07811)
    assert curve.transaction_cost_total == pytest.approx(0.02089)
    assert curve.bar_close_max_drawdown == pytest.approx(0.406)
    assert all(p.sample_key is None for p in curve.points)  # No invented strategy signal.


def test_buy_hold_requires_prices_even_when_strategies_are_cash():
    bars = _bars()
    times = tuple(b.close_time for b in bars)
    missing = (bars[0],) + bars[2:]
    assert _curve(missing, valuation_times=times).final_equity == 1
    with pytest.raises(EquityError, match="missing held-position"):
        build_buy_and_hold_curve(bars=missing, valuation_times=times,
                                start_time=START, end_time=bars[-1].close_time, costs=BacktestCosts())
    with pytest.raises(EquityError, match="exact window"):
        build_buy_and_hold_curve(bars=bars[1:], valuation_times=times,
                                start_time=START, end_time=bars[-1].close_time, costs=BacktestCosts())


def test_daily_risk_uses_nominal_closes_final_events_and_excludes_partial_returns():
    zone = ZoneInfo("America/New_York")
    days = [date(2025, 11, 26) + timedelta(days=i) for i in range(7)]
    records = []
    for day in days:
        if day in (date(2025, 11, 27), date(2025, 11, 29), date(2025, 11, 30)):
            records.append(TradingDayRecord(day, "CLOSED", None, None, None))
        else:
            early = day == date(2025, 11, 28)
            opened = datetime(day.year, day.month, day.day, 9, 30, tzinfo=zone)
            closed = opened.replace(hour=13 if early else 16, minute=0)
            records.append(TradingDayRecord(day, "TRADING", opened, closed,
                                           "QUALIFIED_EARLY_CLOSE" if early else "NORMAL"))
    dataset = SimpleNamespace(scope=SimpleNamespace(interval="60m"),
                              schedule=SimpleNamespace(daily_records=tuple(records)))
    start = datetime(2025, 11, 26, 12, 30, tzinfo=zone)
    end = datetime(2025, 12, 2, 12, 30, tzinfo=zone)
    closes = _session_closes(dataset, start, end)
    assert [c.trading_day for c in closes] == [days[0], days[2], days[5]]
    assert [(c.timestamp.astimezone(zone).hour, c.timestamp.astimezone(zone).minute)
            for c in closes] == [(16, 30), (13, 30), (16, 30)]
    points = [_point(start, 1, "INITIAL"), _point(closes[0].timestamp, 1.2),
              _point(closes[1].timestamp, 4 / 3),
              _point(closes[1].timestamp, 1.33, "EXIT"),
              _point(closes[1].timestamp, 1.32, "ENTRY"),
              _point(closes[2].timestamp, 1.254), _point(end, 0.5, "EXIT")]
    result = calculate_daily_risk(_account(points), session_closes=closes)
    assert result.observation_count == 3 and result.return_count == 2
    assert [r.value for r in result.returns] == pytest.approx([0.1, -0.05])
    assert result.annualized_volatility == pytest.approx(math.sqrt(2.835))
    assert result.sharpe_ratio == pytest.approx(math.sqrt(14))
    assert result.start_time == closes[0].timestamp and result.end_time == closes[-1].timestamp
    assert result.unavailable_reason is None
    missing = [p for p in points if p.timestamp != closes[1].timestamp]
    with pytest.raises(EquityError, match="missing complete session"):
        calculate_daily_risk(_account(missing), session_closes=closes)


@pytest.mark.parametrize("values,reason,volatility", [
    ([], "INSUFFICIENT_DAILY_RETURNS", None),
    ([1], "INSUFFICIENT_DAILY_RETURNS", None),
    ([1, 1.25], "INSUFFICIENT_DAILY_RETURNS", None),
    ([1, 1, 1], "ZERO_VOLATILITY", 0),
    ([1, 1.25, 1.5625], "ZERO_VOLATILITY", 0),
    ([1, 1.1, 1.21], "ZERO_VOLATILITY", 0),
])
def test_daily_risk_short_or_zero_variance_is_explicit(values, reason, volatility):
    closes = tuple(SessionClose(date(2026, 1, 5) + timedelta(days=i), START + timedelta(days=i, hours=7))
                   for i in range(len(values)))
    points = [_point(START, 1, "INITIAL")]
    points.extend(_point(close.timestamp, value) for close, value in zip(closes, values))
    result = calculate_daily_risk(_account(points), session_closes=closes)
    assert result.return_count == max(0, len(values) - 1)
    assert result.unavailable_reason == reason
    assert result.annualized_volatility == volatility
    assert result.sharpe_ratio is None


def test_verified_risk_cli_preserves_existing_reports(verified_workspace_dataset, tmp_path, capsys, monkeypatch):
    dataset = verified_workspace_dataset
    equity = compare_strategies_with_equity(dataset, **_real_config())
    risk = compare_strategies_with_risk(dataset, **_real_config())
    assert risk.equity == equity
    assert len(risk.results) == len(equity.results) == 3
    assert all(result.daily_risk.return_count == risk.benchmark_risk.return_count for result in risk.results)
    assert all(p.timestamp == q.timestamp for p, q in zip(
        risk.results[0].daily_risk.observations, risk.benchmark_risk.observations, strict=True))
    assert risk.results[1].daily_risk.unavailable_reason == "ZERO_VOLATILITY"
    assert sum(p.event == "ENTRY" for p in risk.benchmark_curve.points) == 1
    assert sum(p.event == "EXIT" for p in risk.benchmark_curve.points) == 1
    plan = tmp_path / "risk.json"
    plan.write_text(json.dumps(_plan(dataset.build_path)), encoding="utf-8")
    monkeypatch.setattr(cli, "load_settings", lambda *a, **k: pytest.fail("risk CLI loaded settings"))
    assert cli.main(["research-compare-strategies", "--plan", str(plan), "--risk-report"]) == 0
    payload = json.loads(capsys.readouterr().out)
    expected = strategy_comparison_cli._risk_payload(risk)
    assert payload == expected
    legacy = strategy_comparison_cli._equity_payload(equity)
    assert {k: v for k, v in payload.items() if k not in ("risk", "result_schema_version")} == {
        k: v for k, v in legacy.items() if k != "result_schema_version"
    }
    assert payload["risk"]["benchmark"]["daily_risk"]["annualization_factor"] == 252
    assert payload["risk"]["benchmark"]["daily_risk"]["risk_free_rate"] == 0


def test_risk_cli_failure_uses_opt_in_schema(tmp_path, capsys):
    plan = tmp_path / "invalid.json"
    plan.write_text(json.dumps({**_plan(tmp_path / "missing"), "step_periods": 0}), encoding="utf-8")
    assert cli.main(["research-compare-strategies", "--plan", str(plan), "--risk-report"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["result_schema_version"] == strategy_comparison_cli.STRATEGY_RISK_CLI_VERSION


def test_desktop_risk_worker_uses_verified_report(verified_workspace_dataset):
    pytest.importorskip("PySide6")
    from market_vault.desktop.quant_research import _run_strategy_comparison
    view = _run_strategy_comparison(
        verified_workspace_dataset.build_path, trend_feature="return_2", reversion_feature="return_2",
        trend_threshold=0, reversion_threshold=0, ridge_alpha=1, ridge_threshold=0,
        return_label="execution_return_1d", minimum_train_periods=3, validation_periods=2,
        step_periods=2, commission_bps=10, slippage_bps=5, risk_report=True,
    )
    assert len(view.summary["risk_report_id"]) == 64
    assert len(view.risk_page.rows) == 4
    assert view.risk_page.rows[1][-1] == "σ = 0"
    assert view.equity[-1].name == "Buy & Hold"
    assert view.benchmark_series == view.equity[-1].series
    assert view.page.columns[-1] == "bar_close_max_drawdown"
