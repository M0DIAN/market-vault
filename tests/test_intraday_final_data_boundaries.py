"""Final TEST price-flow and calendar boundaries over real source data."""

from dataclasses import asdict

import pytest

import cross_day_helpers as cd
from market_vault.research import intraday_final_test as final
from market_vault.research import intraday_research as research
from market_vault.research.intraday_data import build_intraday_dataset, json_values, write_intraday_dataset
from market_vault.research.intraday_experiment import create_intraday_experiment
from test_intraday_final_test import freeze_source
from test_intraday_research import comparison_plan, research_data


def test_real_test_gap_fails_before_final_fit_even_for_flat(tmp_path, monkeypatch):
    data = research_data(tmp_path / "data", missing=True, missing_day=30)
    plan = comparison_plan(data)
    source = create_intraday_experiment(plan=plan, report=research.run_intraday_research(plan))
    monkeypatch.setattr(research, "_fit", lambda *a: pytest.fail("TEST price gap fitted"))
    for index in (0, 2):
        selection = freeze_source(source, tmp_path / "source.json", index=index)
        with pytest.raises(ValueError, match="incomplete session price flow"):
            final.run_intraday_final_test(selection)


def test_early_development_benchmark_does_not_shorten_normal_test(tmp_path, monkeypatch):
    # Legal qualified calendar: Q7 evaluates the early-close validation day,
    # then Final evaluates a normal TEST day through real Canonical/Q5 files.
    entries = [("2025-11-26", "N"), ("2025-11-27", "C"), ("2025-11-28", "E"),
               ("2025-11-29", "C"), ("2025-11-30", "C"), ("2025-12-01", "N")]
    trading = [(day, profile) for day, profile in entries if profile != "C"]
    bars = [cd.bar(day, slot, open=100.0 + slot / 100, close=100.005 + slot / 100, code="US.SPY")
            for day, profile in trading for slot in range(42 if profile == "E" else 78)]
    built = cd.build(tmp_path / "canonical", bars)
    data = build_intraday_dataset({"plan_schema_version": "market-vault-intraday-data-plan-v1",
        "canonical_build_dirs": [str(built.build_path)], "schedule": json_values(asdict(cd.schedule(entries))),
        "symbol": "US.SPY", "interval": "5m", "preset": "LIGHT_TECHNICAL", "stride_bars": 1,
        "target_horizon_bars": 3, "dataset_as_of": cd.AS_OF.isoformat()})
    path = write_intraday_dataset(data, path=tmp_path / "data.json")
    plan = {"plan_schema_version": research.INTRADAY_RESEARCH_PLAN_VERSION, "intraday_data_path": str(path),
        "data_id": data.data_id, "feature_fields": ["sma_5"],
        "split": {"train_end_day": trading[0][0], "validation_end_day": trading[1][0], "test_end_day": trading[2][0]},
        "walk_forward": {"minimum_train_days": 1, "validation_days": 1, "step_days": 1},
        "strategies": [{"kind": "FEATURE_RULE", "name": "Long", "signal_field": "sma_5", "comparator": "GT", "threshold": 0}],
        "execution": {"commission_bps": 0, "slippage_bps": 0, "entry_delay_minutes": 15,
                      "stop_new_minutes": 30, "flatten_minutes": 5, "max_hold_bars": 12}}
    monkeypatch.setattr(research, "_fit", lambda *a: pytest.fail("rule path fitted"))
    source_report = research.run_intraday_research(plan)
    assert source_report["groups"][0]["benchmark"]["execution"]["policy"]["max_hold_bars"] == 42
    source = create_intraday_experiment(plan=plan, report=source_report)
    selection = freeze_source(source, tmp_path / "source.json", index=0)
    result = final.run_intraday_final_test(selection)
    benchmark = result["benchmark"]["execution"]
    assert benchmark["policy"]["max_hold_bars"] == 78
    assert len(benchmark["trades"]) == 1
    assert (benchmark["trades"][0]["held_bars"], benchmark["trades"][0]["exit_reason"]) == (72, "EOD")
    assert result["risk"]["return_count"] == 1
    assert result["risk"]["unavailable_reason"] == "INSUFFICIENT_DAILY_RETURNS"
    assert final.create_intraday_test_experiment(selection, result).as_dict()["report"] == result
