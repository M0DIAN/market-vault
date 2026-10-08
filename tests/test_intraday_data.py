"""Intraday sampling against real Canonical artifacts, PIT and local entry points."""

from dataclasses import asdict, replace
from datetime import date
from pathlib import Path
import json
from types import SimpleNamespace

import pytest

import cross_day_helpers as cd
from market_vault import cli
from market_vault.research.intraday_data import (
    INTRADAY_PLAN_VERSION, IntradayDataset, build_intraday_dataset, canonical_json,
    intraday_summary, json_values, load_intraday_dataset, parse_intraday_plan,
    write_intraday_dataset, _data_identity,
)


def input_plan(tmp_path, *, day="2025-03-03", early=False, interval="5m", missing=(), change=None, **options):
    count = (210 if early else 390) // int(interval[:-1])
    bars = [cd.bar(day, slot=i, interval=interval, open=100 + i / 100, close=100.005 + i / 100)
            for i in range(count) if i not in missing]
    if change is not None:
        bars = [change(bar) for bar in bars]
    built = cd.build(tmp_path, bars, interval=interval, dates=[date.fromisoformat(day)])
    return {"plan_schema_version": INTRADAY_PLAN_VERSION,
            "canonical_build_dirs": [str(built.build_path)],
            "schedule": json_values(asdict(cd.schedule(((day, "E" if early else "N"),)))),
            "symbol": "US.AAPL", "interval": interval, "preset": "LIGHT_TECHNICAL",
            "stride_bars": 1, "target_horizon_bars": 3, "dataset_as_of": cd.AS_OF.isoformat(), **options}


@pytest.mark.parametrize("day,early,bars,observations,complete", [
    ("2025-03-03", False, 78, 74, 71), ("2025-11-28", True, 42, 38, 35),
])
def test_full_sessions_and_independent_targets(tmp_path, day, early, bars, observations, complete):
    plan = input_plan(tmp_path, day=day, early=early)
    data = build_intraday_dataset(plan)
    report = data.as_dict()["report"]
    assert len(report["prices"]) == bars
    assert len(report["observations"]) == observations == report["ready_observation_count"]
    assert report["complete_target_count"] == complete
    assert report["observations"][0]["decision_time"] == cd.local(day, 9, 55).isoformat()
    assert report["observations"][-1]["decision_time"] == cd.local(day, 13 if early else 16, 0).isoformat()
    assert [row["status"] for row in report["targets"][-3:]] == ["INCOMPLETE"] * 3
    assert all(row["reason"] == "SESSION_END" for row in report["targets"][-3:])
    first = report["observations"][0]
    closes = [100.005 + i / 100 for i in range(5)]
    assert first["features"]["sma_5"] == pytest.approx(sum(closes) / 5)
    assert first["features"]["return_2"] == pytest.approx(closes[-1] / closes[-2] - 1)
    assert report["targets"][0]["value"] == pytest.approx((100.005 + .07) / (100 + .05) - 1)
    changed = build_intraday_dataset({**plan, "target_horizon_bars": 6}).as_dict()["report"]
    disabled = build_intraday_dataset({**plan, "target_horizon_bars": None}).as_dict()["report"]
    for candidate in (changed, disabled):
        assert candidate["observations"] == report["observations"]
        assert candidate["prices"] == report["prices"]
    assert disabled["targets"] == []
    assert changed["complete_target_count"] == observations - 6


def test_gap_keeps_grid_and_does_not_borrow_prices(tmp_path):
    plan = input_plan(tmp_path, missing=(10,), stride_bars=3)
    report = build_intraday_dataset(plan).as_dict()["report"]
    assert [row["slot"] for row in report["observations"]] == list(range(4, 78, 3))
    assert [row["slot"] for row in report["observations"] if row["status"] == "UNAVAILABLE"] == [10, 13]
    assert report["gaps"] == [{"trading_day": "2025-03-03", "slot": 10, "event_time": cd.local("2025-03-03", 10, 20).isoformat()}]
    assert len(report["prices"]) == 77
    # Slot 7's target requires slots 8, 9, 10, not the next three extant bars.
    key = next(row["observation_key"] for row in report["observations"] if row["slot"] == 7)
    target = next(row for row in report["targets"] if row["observation_key"] == key)
    assert target["status"] == "INCOMPLETE" and target["reason"] == "MISSING_PRICE"


def test_future_prices_do_not_change_prior_features(tmp_path):
    first = input_plan(tmp_path / "first")
    boundary = cd.local("2025-03-03", 12, 0)
    second = input_plan(tmp_path / "second", change=lambda bar: replace(bar, close=bar.close + 1) if bar.event_time >= boundary else bar)
    left = build_intraday_dataset(first).as_dict()["report"]
    right = build_intraday_dataset(second).as_dict()["report"]
    before = lambda report: [(r["decision_time"], r["features"]) for r in report["observations"] if r["decision_time"] <= boundary.isoformat()]
    assert before(left) == before(right)
    assert left["targets"] != right["targets"]


@pytest.mark.parametrize("day,utc_hour", [("2025-03-07", 14), ("2025-03-10", 13)])
def test_observation_clock_follows_dst(tmp_path, day, utc_hour):
    data = build_intraday_dataset(input_plan(tmp_path, day=day)).as_dict()["report"]
    assert data["observations"][0]["decision_time"] == f"{day}T{utc_hour}:55:00+00:00"


@pytest.mark.parametrize("interval,count", [("1m", 386), ("15m", 22), ("30m", 9)])
def test_supported_interval_geometry(tmp_path, interval, count):
    data = build_intraday_dataset(input_plan(tmp_path, interval=interval)).as_dict()["report"]
    assert len(data["observations"]) == count
    assert data["observations"][-1]["decision_time"] == cd.local("2025-03-03", 16, 0).isoformat()


def test_no_warmup_or_targets_fabricated_for_short_session(tmp_path):
    data = build_intraday_dataset(input_plan(tmp_path, interval="30m", preset="CORE_TECHNICAL")).as_dict()["report"]
    assert data["observations"] == [] and len(data["prices"]) == 13
    assert data["sessions"][0]["warmup_bar_count"] == 13
    large = build_intraday_dataset(input_plan(tmp_path / "large", target_horizon_bars=2**31 - 1)).as_dict()["report"]
    assert large["complete_target_count"] == 0


@pytest.mark.parametrize("field,bad", [("stride_bars", True), ("stride_bars", 0), ("target_horizon_bars", -1),
                                         ("target_horizon_bars", 1.5), ("interval", "60m"), ("preset", "unknown")])
def test_plan_rejects_invalid_parameters_before_source_io(tmp_path, field, bad):
    plan = input_plan(tmp_path)
    plan["canonical_build_dirs"] = [str(tmp_path / "missing")]
    plan[field] = bad
    with pytest.raises((ValueError, TypeError)):
        parse_intraday_plan(plan)


def test_strict_source_reconstruction_exclusive_write_and_cli(tmp_path, capsys):
    plan = input_plan(tmp_path)
    plan_path, data_path = tmp_path / "plan.json", tmp_path / "data.json"
    plan_path.write_bytes(canonical_json(plan))
    assert cli.main(["research-intraday-build", "--plan", str(plan_path), "--output", str(data_path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["summary"]["intraday_ready"] == "74"
    data = load_intraday_dataset(data_path)
    assert write_intraday_dataset(data, path=data_path) == data_path
    assert cli.main(["research-intraday-inspect", "--data", str(data_path)]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["data_id"] == data.data_id
    different = build_intraday_dataset({**plan, "stride_bars": 2})
    with pytest.raises(ValueError, match="existing data differs"):
        write_intraday_dataset(different, path=data_path)
    assert data_path.read_bytes() == data.content
    tampered = data.as_dict()
    tampered["report"]["observations"][0]["features"]["sma_5"] += 1
    tampered["data_id"] = _data_identity(tampered)
    other = tmp_path / "tampered.json"
    other.write_bytes(canonical_json(tampered))
    with pytest.raises(ValueError, match="source reconstruction"):
        load_intraday_dataset(other)
    # A malformed schedule stays inside the CLI error envelope.
    plan["schedule"]["extra"] = True
    plan_path.write_bytes(canonical_json(plan))
    assert cli.main(["research-intraday-build", "--plan", str(plan_path), "--output", str(tmp_path / "bad.json")]) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "FAILED"
    assert not (tmp_path / "bad.json").exists()


def test_workspace_uses_real_catalog_canonical_and_only_requested_day(tmp_path):
    from test_research_workspace import _settings, _write_real_calendar, _write_real_ts2_day
    from market_vault.research_workspace import research_ready_settings, plan_local_intraday_research, build_local_intraday_research
    cfg = _settings(tmp_path)
    day = date(2026, 1, 5)
    _write_real_calendar(cfg, [day])
    _write_real_ts2_day(research_ready_settings(cfg), day, ordinal=0)
    from market_vault.api import MarketVault
    vault = MarketVault(cfg)
    arguments = dict(symbol="US.SPY", start_date=day, end_date=day, interval="5m")
    preview = plan_local_intraday_research(vault, **arguments)
    assert preview["summary"]["build_ready"] == "true"
    assert preview["trading_dates"] == (day,)
    saved = build_local_intraday_research(vault, output_path=tmp_path / "workspace.json", **arguments)
    assert intraday_summary(saved)["intraday_ready"] == "74"
    repeated = build_local_intraday_research(vault, output_path=tmp_path / "workspace.json", **arguments)
    assert repeated.data_id == saved.data_id
    assert load_intraday_dataset(saved.path).content == saved.content
