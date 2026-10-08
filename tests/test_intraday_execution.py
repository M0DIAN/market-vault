"""V2 economic/phase counterexamples and the real verified CLI path."""

from dataclasses import asdict, replace
from decimal import Decimal, localcontext
import json

import pytest

import cross_day_helpers as cd
from market_vault import cli
from market_vault.backtest.intraday import IntradayExecutionPolicy, run_intraday_execution
from market_vault.research.intraday_data import build_intraday_dataset, write_intraday_dataset, canonical_json
from market_vault.research.intraday_backtest import (
    INTRADAY_BACKTEST_PLAN_VERSION, execution_views, run_intraday_backtest,
)
from test_intraday_data import input_plan


def backtest_plan(path, *, threshold=0, comparator="GT", commission=0, slippage=0, **policy):
    return {"plan_schema_version": INTRADAY_BACKTEST_PLAN_VERSION, "intraday_data_path": str(path),
            "strategy": {"kind": "FEATURE_RULE", "name": "Trend", "signal_field": "return_2",
                         "comparator": comparator, "threshold": threshold},
            "execution": asdict(IntradayExecutionPolicy(commission, slippage, **policy))}


def signals(report, active):
    return tuple({**{name: row[name] for name in ("observation_key", "trading_day", "slot", "decision_time")},
                  "target": "LONG" if active(row["slot"]) else "FLAT"}
                 for row in report["observations"] if row["status"] == "READY")


def execute(report, decisions, **policy):
    sessions, prices = execution_views(report)
    return run_intraday_execution(sessions=sessions, prices=prices, decisions=decisions,
                                  interval=report["interval"], policy=IntradayExecutionPolicy(**policy))


def test_next_open_phase_two_trades_and_decimal_cash_reconciliation(tmp_path):
    opens = {5: 100.0, 6: 110.0, 7: 120.0, 8: 115.0}
    plan = input_plan(tmp_path, change=lambda bar: replace(bar, open=opens.get(
        int((bar.event_time - cd.local("2025-03-03")).total_seconds() // 300), bar.open)))
    report = build_intraday_dataset(plan).as_dict()["report"]
    result = execute(report, signals(report, lambda slot: slot in (4, 6)), commission_bps=10, slippage_bps=5)
    assert [(t["entry_slot"], t["exit_slot"], t["exit_reason"]) for t in result["trades"]] == [(5, 6, "TARGET_FLAT"), (7, 8, "TARGET_FLAT")]
    assert result["trades"][0]["entry_raw_open"] == 100  # observed close is 100.045
    assert result["trades"][0]["signal_time"] == result["trades"][0]["entry_time"]
    at_entry = [p for p in result["ledger"] if p["timestamp"] == cd.local("2025-03-03", 9, 55).isoformat()]
    assert [p["phase"] for p in at_entry] == ["CLOSE", "OPEN"]
    assert [p["quantity"] > 0 for p in at_entry] == [False, True]
    with localcontext() as ctx:
        ctx.prec = 45
        cash, c, s = Decimal(1), Decimal(".001"), Decimal(".0005")
        for index, (buy, sell) in enumerate(((100, 110), (120, 115))):
            quantity = cash / (Decimal(buy) * (1 + s) * (1 + c))
            entry_fee = quantity * Decimal(buy) * (1 + s) * c
            exit_fee = quantity * Decimal(sell) * (1 - s) * c
            cash = quantity * Decimal(sell) * (1 - s) * (1 - c)
            trade = result["trades"][index]
            assert trade["quantity"] == pytest.approx(float(quantity), rel=1e-13)
            assert trade["commission_total"] == pytest.approx(float(entry_fee + exit_fee), rel=1e-13)
            assert trade["cash_after"] == pytest.approx(float(cash), rel=1e-13)
        assert result["metrics"]["final_cash"] == pytest.approx(float(cash), rel=1e-13)
    assert result["daily"][0]["cash_open"] == 1 and result["ledger"][-1]["quantity"] == 0
    assert len(result["ledger"]) == 156
    # Later close/high/low never sets an earlier open fill.
    changed = input_plan(tmp_path / "later", change=lambda bar: replace(bar, open=opens.get(
        int((bar.event_time - cd.local("2025-03-03")).total_seconds() // 300), bar.open), close=130.0, high=160.0))
    other = build_intraday_dataset(changed).as_dict()["report"]
    actual = execute(other, signals(other, lambda slot: slot in (4, 6)), commission_bps=10, slippage_bps=5)
    assert actual["transactions"] == result["transactions"]


@pytest.mark.parametrize("interval,first,flat", [("1m", 15, 385), ("5m", 5, 77), ("15m", 5, 25), ("30m", 5, 12)])
@pytest.mark.parametrize("early", [False, True])
def test_entry_and_forced_flat_geometry(tmp_path, interval, first, flat, early):
    day = "2025-11-28" if early else "2025-03-10"
    report = build_intraday_dataset(input_plan(tmp_path, day=day, early=early, interval=interval)).as_dict()["report"]
    result = execute(report, signals(report, lambda _: True), commission_bps=0, slippage_bps=0, max_hold_bars=1000)
    assert len(result["trades"]) == 1
    trade = result["trades"][0]
    assert trade["entry_slot"] == first
    assert trade["exit_slot"] == flat - (180 // int(interval[:-1]) if early else 0)
    assert trade["exit_reason"] == "EOD"
    expected_minute = 55 if interval in ("1m", "5m") else 45 if interval == "15m" else 30
    assert trade["exit_time"] == cd.local(day, 12 if early else 15, expected_minute).isoformat()


def test_stride_max_hold_fresh_decision_and_priority(tmp_path):
    report = build_intraday_dataset(input_plan(tmp_path, stride_bars=3)).as_dict()["report"]
    result = execute(report, signals(report, lambda _: True), commission_bps=0, slippage_bps=0)
    trades = result["trades"]
    assert (trades[0]["entry_slot"], trades[0]["exit_slot"], trades[0]["held_bars"]) == (5, 17, 12)
    assert trades[0]["exit_reason"] == "MAX_HOLD" and trades[1]["entry_slot"] == 20
    assert [t["side"] for t in result["transactions"] if t["slot"] == 17] == ["SELL"]
    # EOD beats simultaneous max hold / Flat; max hold beats simultaneous Flat.
    full = build_intraday_dataset(input_plan(tmp_path / "full")).as_dict()["report"]
    decisions = signals(full, lambda slot: slot < 76)
    priority = execute(full, decisions, commission_bps=0, slippage_bps=0, max_hold_bars=72)
    assert priority["trades"][0]["exit_reason"] == "EOD" and priority["trades"][0]["held_bars"] == 72
    maximum = execute(full, signals(full, lambda slot: slot < 16), commission_bps=0, slippage_bps=0)
    assert maximum["trades"][0]["exit_reason"] == "MAX_HOLD"
    # Fresh Long at exactly 15:30 is blocked; a prior target is never carried.
    late = execute(full, signals(full, lambda slot: slot >= 71), commission_bps=0, slippage_bps=0)
    assert late["trades"] == []


def test_horizon_independence_composite_and_actual_cli(tmp_path, capsys):
    source = input_plan(tmp_path)
    results = []
    for horizon in (3, 6, None):
        data = build_intraday_dataset({**source, "target_horizon_bars": horizon})
        path = write_intraday_dataset(data, path=tmp_path / f"data-{horizon}.json")
        plan = backtest_plan(path, commission=10, slippage=5)
        results.append(run_intraday_backtest(plan))
    assert results[0]["execution"] == results[1]["execution"] == results[2]["execution"]
    assert len({result["data_id"] for result in results}) == 3
    plan["strategy"] = {"kind": "COMPOSITE_RULE", "name": "Both", "match": "ALL", "conditions": [
        {"signal_field": "return_2", "comparator": "GT", "threshold": 0},
        {"signal_field": "sma_5", "comparator": "GE", "threshold": 0}]}
    plan["intraday_data_path"] = path.name
    plan_path = tmp_path / "backtest.json"
    plan_path.write_bytes(canonical_json(plan))
    assert cli.main(["research-intraday-backtest", "--plan", str(plan_path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["execution"]["trades"] == results[0]["execution"]["trades"]
    assert output["execution"]["metrics"]["trade_count"] > 0
    with pytest.raises(ValueError, match="selected snapshot"):
        run_intraday_backtest(backtest_plan(path), expected_data_id="0" * 64)
    plan["execution"]["commission_bps"] = True
    plan_path.write_bytes(canonical_json(plan))
    assert cli.main(["research-intraday-backtest", "--plan", str(plan_path)]) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "FAILED"


@pytest.mark.parametrize("missing", [0, 5, 6, 77])
def test_any_required_price_gap_invalidates_even_flat_strategy(tmp_path, missing):
    data = build_intraday_dataset(input_plan(tmp_path, missing=(missing,)))
    path = write_intraday_dataset(data, path=tmp_path / "gap.json")
    with pytest.raises(ValueError, match="incomplete session price flow"):
        run_intraday_backtest(backtest_plan(path, threshold=1e6))


def test_cash_carries_between_evaluated_sessions(tmp_path):
    days = ("2025-03-07", "2025-03-10")
    daily = (("2025-03-07", "N"), ("2025-03-08", "C"), ("2025-03-09", "C"), ("2025-03-10", "N"))
    source = input_plan(tmp_path / "template")
    built = cd.build(tmp_path / "both", [cd.bar(day, slot=slot, close=100 + slot / 100, open=100 + slot / 100)
                                        for day in days for slot in range(78)])
    from market_vault.research.intraday_data import json_values
    source.update(canonical_build_dirs=[str(built.build_path)], schedule=json_values(asdict(cd.schedule(daily))))
    report = build_intraday_dataset(source).as_dict()["report"]
    result = execute(report, signals(report, lambda _: True), commission_bps=10, slippage_bps=5)
    assert [day["trading_day"] for day in result["daily"]] == list(days)
    assert result["daily"][1]["cash_open"] == result["daily"][0]["cash_close"] != 1
    assert result["daily"][1]["cash_close"] == result["metrics"]["final_cash"]
    assert all(row["quantity"] == 0 for row in result["ledger"] if row["timestamp"] in
               (cd.local(day, 16, 0).isoformat() for day in days))
    assert result["trades"][0]["entry_time"].endswith("14:55:00+00:00")
    assert next(t for t in result["trades"] if t["trading_day"] == days[1])["entry_time"].endswith("13:55:00+00:00")
