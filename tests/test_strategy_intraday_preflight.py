"""Q73: actual structural preflight and small independent entry-clock oracles.

Prices in the real Canonical fixture are synthetic. These tests demonstrate
software behavior, not observed market accuracy or profitable strategies.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import pytest


def geometry(minutes, window, *, duration=390, stride=1, entry_delay=15):
    start = datetime(2025, 3, 3, 9, 30, tzinfo=timezone(timedelta(hours=-5)))
    end = start + timedelta(minutes=duration)
    count = duration // minutes
    day = start.date().isoformat()
    observations = [
        {"trading_day": day, "slot": slot, "status": "READY",
         "observation_key": f"slot-{slot}",
         "decision_time": (start + timedelta(minutes=(slot + 1) * minutes)).isoformat()}
        for slot in range(window - 1, count, stride)
    ]
    calendar = {"start": start, "end": end, "count": count,
                "first": start + timedelta(minutes=entry_delay),
                "stop": end - timedelta(minutes=30), "flatten_slot": (duration - 5) // minutes}
    return {"observations": observations}, {day: calendar}


@pytest.mark.parametrize("minutes,window,duration,stride,first,entries", [
    (5, 5, 390, 1, "09:55", 67),
    (5, 26, 390, 1, "11:40", 46),
    (15, 26, 390, 1, "16:00", 0),
    (30, 26, 390, 1, None, 0),
    (5, 5, 210, 1, "09:55", 31),
    (5, 5, 390, 3, "09:55", 23),
])
def test_opportunity_clock_examples_and_complete_denominators(minutes, window, duration, stride, first, entries):
    from market_vault.research.intraday_preflight import _daily_opportunities
    report, calendars = geometry(minutes, window, duration=duration, stride=stride)
    row = _daily_opportunities(report, calendars)[0]
    actual_first = row["first_ready_decision_time"]
    assert (actual_first[11:16] if actual_first else None) == first
    assert row["eligible_entry_observation_count"] == entries
    assert row["observation_count"] == row["ready_observation_count"] == len(report["observations"])
    assert row["ready_observation_count"] == entries + sum(row["excluded_ready_observations"].values())
    if minutes == 15:
        assert row["excluded_ready_observations"]["NO_NEXT_SESSION_OPEN"] == 1
    # Unavailable Features remain in the denominator, while target status is
    # deliberately absent: target completeness must not filter fresh entries.
    if entries:
        report["observations"][0]["status"] = "UNAVAILABLE"
        changed = _daily_opportunities(report, calendars)[0]
        assert changed["eligible_entry_observation_count"] == entries - 1
        assert changed["unavailable_observation_count"] == 1
        assert changed["observation_count"] == row["observation_count"]


def test_entry_boundaries_agree_with_actual_q6_single_decision_execution():
    from market_vault.backtest.intraday import IntradayExecutionPolicy, _inputs, run_intraday_execution
    from market_vault.research.intraday_preflight import _daily_opportunities
    report, calendars = geometry(5, 5, entry_delay=60)
    day, cal = next(iter(calendars.items()))
    sessions = ({"trading_day": day, "open_time": cal["start"].isoformat(),
                 "close_time": cal["end"].isoformat(), "bar_count": 78},)
    prices = tuple({"trading_day": day, "slot": slot, "row_version_id": f"bar-{slot}",
                    "event_time": (cal["start"] + timedelta(minutes=slot * 5)).isoformat(),
                    "available_at": (cal["start"] + timedelta(minutes=(slot + 1) * 5)).isoformat(),
                    "open": 100.0, "close": 100.0} for slot in range(78))
    policy = IntradayExecutionPolicy(0, 0, entry_delay_minutes=60)
    _, actual_calendars, _, _ = _inputs(sessions, prices, (), "5m", policy)
    summary = _daily_opportunities(report, actual_calendars)[0]
    assert summary["eligible_entry_observation_count"] == 60
    assert summary["first_eligible_next_open_time"][11:16] == "10:30"
    assert summary["excluded_ready_observations"] == {
        "NO_NEXT_SESSION_OPEN": 1, "AT_OR_AFTER_FORCED_FLAT": 1,
        "BEFORE_ENTRY_WINDOW": 7, "AT_OR_AFTER_STOP_NEW": 5,
    }
    for slot, expected in ((10, 0), (11, 1), (70, 1), (71, 0), (76, 0), (77, 0)):
        observation = next(row for row in report["observations"] if row["slot"] == slot)
        actual = run_intraday_execution(sessions=sessions, prices=prices,
                                       decisions=({**observation, "target": "LONG"},),
                                       interval="5m", policy=policy)
        assert len(actual["trades"]) == expected
        assert _daily_opportunities({"observations": [observation]}, actual_calendars)[0]["eligible_entry_observation_count"] == expected


@pytest.fixture(scope="module")
def preflight_data(tmp_path_factory):
    from test_intraday_research import research_data
    return research_data(tmp_path_factory.mktemp("q73-preflight"))


def test_public_preflight_strictly_loads_once_without_fit_execution_or_test(preflight_data, monkeypatch):
    from market_vault.research import intraday_research as research
    from market_vault.research.intraday_preflight import analyze_intraday_preflight
    from test_intraday_research import comparison_plan
    data = preflight_data
    before = data.path.read_bytes()
    loader, calls = research.load_intraday_dataset, []
    def loaded(*args, **kwargs):
        calls.append(args[0])
        return loader(*args, **kwargs)
    def forbidden(*args, **kwargs):
        pytest.fail("structural preflight fitted or executed a candidate")
    monkeypatch.setattr(research, "load_intraday_dataset", loaded)
    monkeypatch.setattr(research, "_fit", forbidden)
    monkeypatch.setattr(research, "run_intraday_execution", forbidden)
    plan = comparison_plan(data)
    original_plan = deepcopy(plan)
    report = analyze_intraday_preflight(plan)
    assert len(calls) == 1 and report["data_id"] == data.data_id
    assert report["status"] == "CHECKED" and report["blockers"] == []
    assert report["eligible_entry_observation_count"] == 670
    assert [fold["training_row_count"] for fold in report["folds"]] == [1420, 1775]
    assert report["split_day_counts"] == {"TRAIN": 25, "VALIDATION": 5, "TEST": 6}
    assert len(report["evaluated_days"]) == 10
    assert not any(row["trading_day"] > plan["split"]["validation_end_day"] for row in report["sessions"])
    assert report["zero_entry_days"] == report["zero_entry_folds"] == []
    assert "TEST_PERFORMANCE" in report["not_evaluated"]
    assert "MARKET_ACCURACY" in report["not_evaluated"]
    assert data.path.read_bytes() == before and plan == original_plan
    assert analyze_intraday_preflight(plan) == report
    assert len(calls) == 2  # A second action verifies again; no persistent bypass.
    stale = {**plan, "data_id": "0" * 64}
    with pytest.raises(ValueError, match="identity differs"):
        analyze_intraday_preflight(stale)


def test_actual_cli_checked_blocked_and_no_experiment_publication(preflight_data, tmp_path, capsys):
    from market_vault.cli import main
    from market_vault.research.intraday_data import canonical_json
    from test_intraday_research import comparison_plan
    plan = comparison_plan(preflight_data)
    # Flat-only is valid: opportunities do not depend on a selected rule's
    # hypothetical signals or its actual trading propensity.
    plan["strategies"] = plan["strategies"][:1]
    path = tmp_path / "plan.json"
    path.write_bytes(canonical_json(plan))
    command = ["research-intraday-compare", "--plan", str(path), "--preflight"]
    assert main(command) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "CHECKED" and result["preflight"]["eligible_entry_observation_count"] == 670
    assert "experiment" not in result and "report" not in result
    # A valid continuous minute window can contain no five-minute next open.
    plan["execution"]["entry_delay_minutes"] = 359
    path.write_bytes(canonical_json(plan))
    assert main(command) == 2
    blocked = json.loads(capsys.readouterr().out)
    assert blocked["status"] == "BLOCKED"
    assert blocked["preflight"]["blockers"] == [{"reason": "NO_ELIGIBLE_ENTRY_OBSERVATIONS", "fold_index": None}]
    assert len(blocked["preflight"]["zero_entry_days"]) == 10
    assert list(tmp_path.iterdir()) == [path]
    output = tmp_path / "experiment.json"
    assert main(command + ["--experiment", str(output)]) == 1
    assert "cannot save" in json.loads(capsys.readouterr().err)["error"]
    assert not output.exists()


def test_no_targets_block_learners_not_rules(preflight_data, tmp_path):
    from market_vault.research.intraday_data import build_intraday_dataset, write_intraday_dataset
    from market_vault.research.intraday_preflight import analyze_intraday_preflight
    from test_intraday_research import comparison_plan
    source = {**preflight_data.as_dict()["plan"], "target_horizon_bars": None}
    data = build_intraday_dataset(source)
    data = replace(data, path=write_intraday_dataset(data, path=tmp_path / "without-targets.json"))
    plan = comparison_plan(data)
    result = analyze_intraday_preflight(plan)
    assert result["status"] == "BLOCKED"
    assert result["blockers"] == [{"reason": "NO_LEARNED_TRAINING_ROWS", "fold_index": index} for index in range(2)]
    assert result["eligible_entry_observation_count"] == 670
    plan["strategies"] = plan["strategies"][:1]
    rules = analyze_intraday_preflight(plan)
    assert rules["status"] == "CHECKED" and rules["blockers"] == []
    assert all(fold["training_row_count"] == 0 for fold in rules["folds"])
