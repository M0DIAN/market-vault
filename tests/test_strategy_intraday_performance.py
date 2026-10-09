"""Independent cash oracles, unavailable values and offline public entry points."""

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

from market_vault import cli
from market_vault.backtest.intraday import IntradayExecutionPolicy, run_intraday_execution
from market_vault.research.intraday_performance import analyze_intraday_experiment, summarize_intraday_execution
from market_vault.research.intraday_risk_diagnostics import analyze_intraday_risk_diagnostics, summarize_intraday_risk_diagnostics
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
    from market_vault.research.intraday_parameter_grid import analyze_intraday_parameter_grid
    sources = (intraday_experiment, final_case[1])
    paths = [tmp_path / "development.json", tmp_path / "test.json"]
    for snapshot, path in zip(sources, paths):
        write_strategy_experiment(snapshot, path=path)
    monkeypatch.setattr(research, "load_intraday_dataset", lambda *a: pytest.fail("analysis read Q5"))
    monkeypatch.setattr(final, "load_intraday_dataset", lambda *a: pytest.fail("analysis read TEST sources"))
    monkeypatch.setattr(research, "_fit", lambda *a: pytest.fail("analysis fitted"))
    before = [path.read_bytes() for path in paths]
    for index, path in enumerate(paths):
        with pytest.raises(ValueError, match="INTRADAY_DIAGNOSTICS"):
            analyze_intraday_parameter_grid(sources[index])
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
        risk_args = ["research-intraday-risk-diagnostics", "--experiment", str(path)]
        if index == 0:
            risk_args += ["--candidate-index", "1"]
        assert cli.main(risk_args) == 0
        risk = json.loads(capsys.readouterr().out)["report"]
        assert risk["experiment_id"] == result["experiment_id"] and risk["candidate_id"] == result["candidate_id"]
        assert risk["evidence"] == "RECORDED_LEDGER_DERIVATION"
        for side in ("strategy_diagnostics", "benchmark_diagnostics"):
            derived = risk[side]["report"]
            assert risk[side]["status"] == "AVAILABLE"
            assert derived["daily_return_distribution"]["sample_count"] == (10 if index == 0 else 6)
            assert derived["fold_diagnostics"]["status"] == ("AVAILABLE" if index == 0 else "NOT_APPLICABLE")
        # Exercise the console entry in a separate process, with this
        # checkout's source rather than another editable installation.
        environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
        completed = subprocess.run([sys.executable, "-m", "market_vault", *risk_args],
                                   capture_output=True, text=True, env=environment, check=False)
        assert completed.returncode == 0, completed.stderr
        assert json.loads(completed.stdout)["report"] == risk
    assert [path.read_bytes() for path in paths] == before
    for path, candidate in ((paths[0], "-1"), (paths[0], "100"), (paths[1], "1")):
        assert cli.main(["research-intraday-performance", "--experiment", str(path), "--candidate-index", candidate]) == 1
        assert json.loads(capsys.readouterr().err)["status"] == "FAILED"
    with pytest.raises(ValueError, match="nonnegative"):
        analyze_intraday_experiment(intraday_experiment, cost_index=True)
    for value in (True, False, -1, 1.0, "1"):
        with pytest.raises(ValueError, match="nonnegative"):
            analyze_intraday_risk_diagnostics(intraday_experiment, cost_index=value)
    for path, candidate in ((paths[0], "-1"), (paths[0], "100"), (paths[1], "1")):
        assert cli.main(["research-intraday-risk-diagnostics", "--experiment", str(path), "--candidate-index", candidate]) == 1
        assert json.loads(capsys.readouterr().err)["status"] == "FAILED"
    with pytest.raises(SystemExit) as exc:
        cli.main(["research-intraday-risk-diagnostics", "--experiment", str(paths[0]), "--candidate-index", "True"])
    assert exc.value.code == 2
    capsys.readouterr()
    assert [path.read_bytes() for path in paths] == before


def risk_execution(changes, *, first_prices=None):
    """Small real V2 account, with a DST weekend and optional cash-only days."""
    sessions, prices, decisions = [], [], []
    for index, change in enumerate(changes):
        opened = datetime.fromisoformat("2025-03-07T09:30:00-05:00") if index == 0 else (
            datetime.fromisoformat("2025-03-10T09:30:00-04:00") + timedelta(days=index - 1))
        day = opened.date().isoformat()
        sessions.append({"trading_day": day, "open_time": opened.isoformat(),
                         "close_time": (opened + timedelta(minutes=40)).isoformat(), "bar_count": 8})
        path = first_prices if index == 0 and first_prices is not None else [100] * 6 + [100 * (1 + (change or 0))] * 2
        for slot, price in enumerate(path):
            prices.append({"trading_day": day, "slot": slot, "event_time": (opened + timedelta(minutes=slot * 5)).isoformat(),
                           "available_at": (opened + timedelta(minutes=(slot + 1) * 5)).isoformat(),
                           "open": price, "close": price, "row_version_id": f"risk-{index}-{slot}"})
        if change is not None:
            decisions.append({"trading_day": day, "slot": 0, "decision_time": (opened + timedelta(minutes=5)).isoformat(),
                              "observation_key": "risk-observation-" + str(index), "target": "LONG"})
    return run_intraday_execution(sessions=tuple(sessions), prices=tuple(prices), decisions=tuple(decisions),
        interval="5m", policy=IntradayExecutionPolicy(0, 0, entry_delay_minutes=0, stop_new_minutes=15,
                                                     flatten_minutes=10, max_hold_bars=100))


def test_risk_drawdown_episodes_same_clock_latest_peak_dst_gap_and_unrecovered_tail():
    original = risk_execution([.05, None], first_prices=[100, 100, 110, 99, 110, 88, 105, 105])
    before = deepcopy(original)
    report = summarize_intraday_risk_diagnostics(original)
    first, second = report["drawdown_episodes"]
    assert first["peak_sequence"] == 5 and first["trough_sequence"] == 6 and first["recovery_sequence"] == 8
    assert first["peak_time"] == first["trough_time"] == "2025-03-07T09:45:00-05:00"
    assert first["depth"] == pytest.approx(.1) and first["duration_minutes"] == 5
    assert first["recovered"] is True
    assert second["peak_sequence"] == 9 and second["trough_sequence"] == 10
    assert second["depth"] == pytest.approx(.2)
    assert second["duration_minutes"] == 4275  # DST removes 60 minutes from this calendar span.
    assert second["recovered"] is False
    assert second["recovery_sequence"] is second["recovery_time"] is second["recovery_equity"] is None
    assert report["summary"]["maximum_drawdown"]["value"] == pytest.approx(.2)
    assert report["summary"]["last_drawdown"]["value"] == pytest.approx(1 - 1.05 / 1.1)
    assert report["summary"]["longest_drawdown_minutes"]["unit"] == "MINUTES"
    assert report["daily_return_distribution"]["sample_count"] == 2
    assert report["daily_return_distribution"]["zero_count"] == 1
    assert report["trade_return_distribution"]["sample_count"] == 1
    assert {report["trade_return_distribution"][key] for key in ("minimum", "maximum", "p05", "p50", "p95")} == {original["trades"][0]["net_return"]}
    assert original == before


def test_risk_quantiles_cash_concentration_and_compound_fold_oracles():
    execution = risk_execution([.1, -.1, None, .2, -.2])
    days = [row["trading_day"] for row in execution["daily"]]
    folds = [{"fold_index": index, "fold_id": "fold-" + str(index), "validation_days": values}
             for index, values in enumerate((days[:2], days[2:3], days[3:4], days[4:]))]
    report = summarize_intraday_risk_diagnostics(execution, folds=folds)
    daily, trades = report["daily_return_distribution"], report["trade_return_distribution"]
    assert (daily["sample_count"], daily["positive_count"], daily["zero_count"], daily["negative_count"]) == (5, 2, 1, 2)
    assert [daily[key] for key in ("p05", "p25", "p50", "p75", "p95")] == pytest.approx([-.18, -.1, 0, .1, .18])
    assert [trades[key] for key in ("p05", "p25", "p50", "p75", "p95")] == pytest.approx([-.185, -.125, 0, .125, .185])
    positive, negative = (report["cash_concentration"][side] for side in ("positive", "negative"))
    assert positive["total_absolute_cash"] == pytest.approx(.298)
    assert positive["top_1_share"] == pytest.approx(.198 / .298)
    assert negative["total_absolute_cash"] == pytest.approx(.3476)
    assert negative["top_1_share"] == pytest.approx(.2376 / .3476)
    assert positive["top_3_share"] == negative["top_3_share"] == 1
    assert negative["top_days"][0]["cash_contribution"] == pytest.approx(-.2376)
    fold_report = report["fold_diagnostics"]
    assert [row["compound_return"] for row in fold_report["rows"]] == pytest.approx([-.01, 0, .2, -.2])
    assert [row["cash_contribution"] for row in fold_report["rows"]] == pytest.approx([-.01, 0, .198, -.2376])
    assert fold_report["rows"][0]["cash_open"] == 1 and fold_report["rows"][0]["cash_close"] == pytest.approx(.99)
    assert fold_report["rows"][0]["day_count"] == fold_report["rows"][0]["trade_count"] == 2
    assert fold_report["rows"][1]["cash_only_days"] == 1
    summary = fold_report["summary"]
    assert [summary[key]["value"] for key in ("positive_folds", "zero_folds", "negative_folds")] == [1, 1, 2]
    assert summary["median_fold_return"]["value"] == pytest.approx(-.005)
    assert math.fsum(row["cash_contribution"] for row in fold_report["rows"]) == pytest.approx(-.0496)
    assert math.fsum(row["compound_return"] for row in fold_report["rows"]) != pytest.approx(-.0496)


def test_risk_empty_trade_sample_zero_account_and_not_applicable_folds():
    report = summarize_intraday_risk_diagnostics(risk_execution([None]))
    assert report["drawdown_episodes"] == []
    assert all(item["value"] == 0 for item in report["summary"].values())
    trade = report["trade_return_distribution"]
    assert trade["sample_count"] == 0 and trade["unavailable_reason"] == "NO_TRADES"
    assert all(trade[key] is None for key in ("minimum", "maximum", "p05", "p25", "p50", "p75", "p95"))
    assert report["daily_return_distribution"]["p95"] == 0
    assert report["fold_diagnostics"] == {"status": "NOT_APPLICABLE", "unavailable_reason": "NOT_APPLICABLE", "rows": [], "summary": {}}
    for side in ("positive", "negative"):
        assert report["cash_concentration"][side]["top_1_share"] is None
        assert report["cash_concentration"][side]["top_3_share"] is None
        assert report["cash_concentration"][side]["day_count"] == 0
    assert "NaN" not in json.dumps(report, allow_nan=False)


def test_risk_concentration_uses_actual_sign_ties_and_top_three_not_zero_tolerance():
    from market_vault.research.intraday_risk_diagnostics import _concentration, _distribution
    changes = [.125, .125, .25, .5, -.125, -.125, -.25, -.5, 2 ** -48]
    cash, daily = 1.0, []
    for index, change in enumerate(changes):
        daily.append({"trading_day": str(index), "cash_open": cash, "cash_close": cash + change})
        cash += change
    result = _concentration(daily)
    assert result["positive"]["day_count"] == 5  # The tiny actual gain remains a positive cash contribution.
    assert result["positive"]["top_1_share"] == pytest.approx(.5 / (1 + 2 ** -48))
    assert result["positive"]["top_3_share"] == pytest.approx(.875 / (1 + 2 ** -48))
    assert result["negative"]["top_1_share"] == .5 and result["negative"]["top_3_share"] == .875
    assert [row["trading_day"] for row in result["positive"]["top_days"]] == ["3", "2", "0"]
    signs = _distribution([-1e-12, 1e-12, -2e-12, 2e-12], "EMPTY")
    assert [signs[key] for key in ("positive_count", "zero_count", "negative_count")] == [1, 2, 1]


@pytest.mark.parametrize("case", ["ledger", "ledger_scale", "drawdown", "maximum", "fold_gap", "fold_overlap"])
def test_risk_inconsistent_ledger_or_fold_partition_rejects_derived_analysis(case):
    execution = risk_execution([.1, -.1])
    days = [row["trading_day"] for row in execution["daily"]]
    folds = [{"fold_index": 0, "fold_id": "fold-0", "validation_days": days}]
    if case == "ledger":
        execution["ledger"][2]["cash"] += .1
    elif case == "ledger_scale":
        # Internally consistent marks with unchanged drawdown ratios, but a
        # different account scale from the recorded daily cash and trades.
        for point in execution["ledger"]:
            for key in ("cash", "quantity", "equity"):
                point[key] *= 2
    elif case == "drawdown":
        execution["ledger"][2]["drawdown"] += .1
    elif case == "maximum":
        execution["metrics"]["observed_max_drawdown"] += .1
    elif case == "fold_gap":
        folds[0]["validation_days"] = days[:1]
    else:
        folds[0]["validation_days"] = days + days[:1]
    with pytest.raises(ValueError, match="reconcile|partition"):
        summarize_intraday_risk_diagnostics(execution, folds=folds)


def test_parameter_grid_neighbors_use_numeric_order_and_fixed_other_axes():
    from itertools import product
    from market_vault.research.intraday_parameter_grid import _neighbors
    axes = [{"values": [10, 1, 100]}, {"values": [7, -2, 1]}]
    cells = [{"candidate_index": index, "axis_values": list(values)}
             for index, values in enumerate(product(*(axis["values"] for axis in axes)))]
    original = deepcopy(cells)
    # Center (10, 1) is candidate 2 in input order. Numeric adjacency is not
    # neighboring array positions and never includes a diagonal coordinate.
    assert _neighbors(axes, cells, 2) == [(0, "LOWER", 5), (0, "HIGHER", 8), (1, "LOWER", 1), (1, "HIGHER", 0)]
    assert _neighbors([{"values": [1]}], [{"candidate_index": 0, "axis_values": [1]}], 0) == []
    assert _neighbors([], [{"candidate_index": 0, "axis_values": []}], 0) == []
    assert cells == original


def test_parameter_grid_neighborhood_population_availability_and_finite_midpoint():
    from market_vault.research.intraday_parameter_grid import _summary
    rows = [{"basis_matches": True, "metric": {"value": 1e308}},
            {"basis_matches": True, "metric": {"value": 1e308}},
            {"basis_matches": False, "metric": {"value": -100}},
            {"basis_matches": True, "metric": {"value": None}}]
    result = _summary(rows, "RATIO")
    assert (result["neighbor_count"], result["basis_matching_count"], result["available_count"]) == (4, 3, 2)
    assert result["minimum"] == result["median"] == result["maximum"] == 1e308
    assert result["population"] == "AXIS_NEIGHBORS_EXCLUDING_CENTER"
    assert _summary([], "RATIO")["unavailable_reason"] == "NO_NEIGHBORS"
    assert _summary(rows[2:3], "RATIO")["unavailable_reason"] == "NO_MATCHING_BASIS"
    assert _summary(rows[3:], "RATIO")["unavailable_reason"] == "NO_AVAILABLE_NEIGHBOR_METRICS"
