"""Independent cash oracles, unavailable values and offline public entry points."""

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
import json
import math

import pytest

from market_vault import cli
from market_vault.backtest.intraday import IntradayExecutionPolicy, run_intraday_execution
from market_vault.research.intraday_performance import analyze_intraday_experiment, summarize_intraday_execution
from market_vault.research.strategy_experiment import write_strategy_experiment
from test_intraday_experiment import intraday_experiment  # noqa: F401
from test_intraday_final_test import final_case, selection_case  # noqa: F401
from test_intraday_research import research_case  # noqa: F401


def execution(*, commission=0, slippage=0, active=True):
    # Numerical session inputs; the shorter second session is a cash day.
    sessions, prices, decisions = [], [], []
    for day, offset, count in (("2025-03-07", "-05:00", 78), ("2025-03-10", "-04:00", 42)):
        start = datetime.fromisoformat(day + "T09:30:00" + offset)
        sessions.append({"trading_day": day, "open_time": start.isoformat(),
                         "close_time": (start + timedelta(minutes=5 * count)).isoformat(), "bar_count": count})
        for slot in range(count):
            price = {1: 100, 2: 110, 15: 120, 16: 115, 27: 100, 28: 100}.get(slot, 100)
            prices.append({"trading_day": day, "slot": slot, "event_time": (start + timedelta(minutes=5 * slot)).isoformat(),
                           "available_at": (start + timedelta(minutes=5 * (slot + 1))).isoformat(),
                           "open": price, "close": price, "row_version_id": f"price-{day}-{slot}"})
            if day == "2025-03-07":
                decisions.append({"trading_day": day, "slot": slot, "decision_time": prices[-1]["available_at"],
                                  "observation_key": f"observation-{slot}",
                                  "target": "LONG" if active and slot in (0, 14, 26) else "FLAT"})
    return run_intraday_execution(sessions=tuple(sessions), prices=tuple(prices), decisions=tuple(decisions),
        interval="5m", policy=IntradayExecutionPolicy(commission, slippage, entry_delay_minutes=0))


@pytest.mark.parametrize("commission,slippage", [(0, 0), (10, 5)])
def test_cash_attribution_decimal_oracle_and_session_time_exposure(commission, slippage):
    original = execution(commission=commission, slippage=slippage)
    before = deepcopy(original)
    result = summarize_intraday_execution(original)
    summary = {key: item["value"] for key, item in result["summary"].items()}
    with localcontext() as context:
        context.prec = 45
        cash, fee, slip = Decimal(1), Decimal(commission) / 10000, Decimal(slippage) / 10000
        market, fees, slips, pnls, returns = [], [], [], [], []
        for raw_buy, raw_sell in ((100, 110), (120, 115), (100, 100)):
            buy, sell = Decimal(raw_buy), Decimal(raw_sell)
            quantity = cash / (buy * (1 + slip) * (1 + fee))
            after = quantity * sell * (1 - slip) * (1 - fee)
            market.append(quantity * (sell - buy))
            fees.append(quantity * (buy * (1 + slip) + sell * (1 - slip)) * fee)
            slips.append(quantity * (buy + sell) * slip)
            pnls.append(after - cash)
            returns.append(after / cash - 1)
            cash = after
        for key, expected in (("market_pnl", sum(market)), ("commission_total", sum(fees)),
                              ("slippage_total", sum(slips)), ("net_cash_pnl", cash - 1)):
            assert summary[key] == pytest.approx(float(expected), rel=1e-12, abs=1e-14)
        gain = sum(p for p, r in zip(pnls, returns) if r > Decimal("1e-12"))
        loss = -sum(p for p, r in zip(pnls, returns) if r < Decimal("-1e-12"))
        assert summary["profit_factor"] == pytest.approx(float(gain / loss))
        assert summary["mean_trade_return"] == pytest.approx(float(sum(returns) / 3))
    assert original == before
    assert summary["trade_count"] == 3 and summary["winning_trades"] == 1
    assert summary["losing_trades"] == (1 if commission == 0 else 2)
    assert summary["win_rate"] == pytest.approx(1 / 3)
    assert summary["mean_holding_minutes"] == 5 and summary["mean_held_bars"] == 1
    assert result["session_minutes"] == 600 and summary["exposure_ratio"] == .025
    assert summary["cash_only_days"] == 1
    assert [row["group"] for row in result["by_entry_hour"]] == ["0-60m", "60-120m", "120-180m"]
    for key in ("by_entry_hour", "by_trading_day", "by_exit_reason"):
        assert math.fsum(row["net_cash_pnl"] for row in result[key]) == pytest.approx(summary["net_cash_pnl"])
    assert result["by_trading_day"][1]["trade_count"] == 0
    assert abs(result["reconciliation_residual"]) < 1e-12


def test_flat_account_has_explicit_unavailable_ratios_and_zero_cash_attribution():
    report = summarize_intraday_execution(execution(active=False))
    summary = report["summary"]
    assert summary["win_rate"] == {"value": None, "unit": "RATIO", "unavailable_reason": "NO_TRADES"}
    assert summary["profit_factor"]["value"] is None
    assert summary["profit_factor"]["unavailable_reason"] == "NO_LOSING_TRADES"
    assert summary["payoff_ratio"]["unavailable_reason"] == "NEEDS_WIN_AND_LOSS"
    assert summary["exposure_ratio"]["value"] == summary["net_cash_pnl"]["value"] == 0
    assert summary["cash_only_days"]["value"] == 2
    assert report["by_exit_reason"] == [] and report["by_entry_hour"] == []
    assert len(report["by_trading_day"]) == 2
    assert "NaN" not in json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("field", ["trade", "daily", "final", "version"])
def test_inconsistent_recorded_cash_or_unsupported_semantics_are_not_presented_as_analysis(field):
    result = execution()
    if field == "trade":
        result["trades"][0]["commission_total"] += .01
    elif field == "daily":
        result["daily"][1]["cash_close"] += .01
    elif field == "final":
        result["metrics"]["final_cash"] += .01
    else:
        result["version"] = "future-execution"
    with pytest.raises(ValueError, match="reconcile|supported"):
        summarize_intraday_execution(result)


def test_saved_development_and_test_cli_are_offline_and_remain_distinct(intraday_experiment, final_case, tmp_path, monkeypatch, capsys):
    from market_vault.research import intraday_research as research, intraday_final_test as final
    sources = (intraday_experiment, final_case[1])
    paths = [tmp_path / "development.json", tmp_path / "test.json"]
    for snapshot, path in zip(sources, paths):
        write_strategy_experiment(snapshot, path=path)
    monkeypatch.setattr(research, "load_intraday_dataset", lambda *a: pytest.fail("analysis read Q5"))
    monkeypatch.setattr(final, "load_intraday_dataset", lambda *a: pytest.fail("analysis read TEST sources"))
    monkeypatch.setattr(research, "_fit", lambda *a: pytest.fail("analysis fitted"))
    before = [path.read_bytes() for path in paths]
    for index, path in enumerate(paths):
        args = ["research-intraday-performance", "--experiment", str(path)]
        if index == 0:
            args += ["--candidate-index", "1"]
        assert cli.main(args) == 0
        result = json.loads(capsys.readouterr().out)["report"]
        assert result["evidence"] == "RECORDED_LEDGER_DERIVATION"
        assert result["evaluation_scope"] == ("DEVELOPMENT_WALK_FORWARD_ONLY" if index == 0 else "FROZEN_SINGLE_CANDIDATE_TEST")
        assert result["performance"]["summary"]["evaluated_days"]["value"] == (10 if index == 0 else 6)
        assert result["benchmark"]["execution_id"] != result["performance"]["execution_id"]
        assert result["experiment_id"] == sources[index].experiment_id
    assert [path.read_bytes() for path in paths] == before
    for path, candidate in ((paths[0], "-1"), (paths[0], "100"), (paths[1], "1")):
        assert cli.main(["research-intraday-performance", "--experiment", str(path), "--candidate-index", candidate]) == 1
        assert json.loads(capsys.readouterr().err)["status"] == "FAILED"
    with pytest.raises(ValueError, match="nonnegative"):
        analyze_intraday_experiment(intraday_experiment, cost_index=True)
