"""Real Canonical development research, independent numerical oracles and leakage."""

from dataclasses import asdict, replace
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
import math
from types import SimpleNamespace

import pytest

import cross_day_helpers as cd
from market_vault.research import intraday_research as research
from market_vault.research.intraday_data import build_intraday_dataset, write_intraday_dataset, json_values


def research_data(root, *, changed_day=None, missing=False, missing_day=20, test_change=False):
    first, last = date(2025, 2, 3), date(2025, 3, 25)
    entries, days, bars = [], [], []
    current = first
    rates = [Decimal("-.02"), Decimal(".01"), Decimal(".03"), Decimal("-.01"), Decimal(".02")]
    while current <= last:
        closed = current.weekday() >= 5 or current == date(2025, 2, 17)
        entries.append((current.isoformat(), "C" if closed else "N"))
        if not closed:
            days.append(current.isoformat())
        current += timedelta(days=1)
    for index, day in enumerate(days):
        for slot in range(78):
            if missing and index == missing_day and slot == 7:
                continue
            base = Decimal(100 + index)
            price = base + Decimal(slot) / 100 if slot < 77 else (base + Decimal(".05")) * (1 + rates[index % 5])
            if index == changed_day or (test_change and index >= 30):
                price *= Decimal("1.1")
            bars.append(cd.bar(day, slot, open=float(price), close=float(price + Decimal(".005")), high=200.0, low=50.0, code="US.SPY"))
    source = cd.build(root, bars)
    plan = {"plan_schema_version": "market-vault-intraday-data-plan-v1", "canonical_build_dirs": [str(source.build_path)],
            "schedule": json_values(asdict(cd.schedule(entries))), "symbol": "US.SPY", "interval": "5m", "preset": "LIGHT_TECHNICAL",
            "stride_bars": 1, "target_horizon_bars": 3, "dataset_as_of": cd.AS_OF.isoformat()}
    data = build_intraday_dataset(plan)
    path = write_intraday_dataset(data, path=root / "intraday.json")
    return replace(data, path=path)


def comparison_plan(data):
    plan = research.default_intraday_research_plan(data, commission_bps=0, slippage_bps=0)
    plan["feature_fields"] = ["sma_5"]
    plan["strategies"] = [
        {"kind": "FEATURE_RULE", "name": "Flat", "signal_field": "sma_5", "comparator": "GT", "threshold": 1e6},
        {"kind": "COMPOSITE_RULE", "name": "Long", "match": "ALL", "conditions": [
            {"signal_field": "sma_5", "comparator": "GT", "threshold": 0},
            {"signal_field": "sma_5", "comparator": "LT", "threshold": 1e6}]},
        {"kind": "RIDGE", "name": "Ridge", "alpha": 1, "threshold": 0},
    ]
    return plan


@pytest.fixture(scope="session")
def research_case(tmp_path_factory):
    data = research_data(tmp_path_factory.mktemp("intraday-research"))
    plan = comparison_plan(data)
    return data, plan, research.run_intraday_research(plan)


def execution_scenarios_plan(plan):
    from market_vault.research.intraday_execution_scenarios import INTRADAY_EXECUTION_SCENARIOS_PLAN_VERSION
    base = deepcopy(plan)
    return {"plan_schema_version": INTRADAY_EXECUTION_SCENARIOS_PLAN_VERSION, "comparison_plan": base,
            "execution_scenarios": [
                {"name": "Original", "execution": deepcopy(base["execution"])},
                {"name": "Delayed", "execution": {"commission_bps": 10, "slippage_bps": 5,
                    "entry_delay_minutes": 60, "stop_new_minutes": 45, "flatten_minutes": 10, "max_hold_bars": 3}}]}


@pytest.fixture(scope="session")
def execution_scenarios_case(research_case):
    from market_vault.research.intraday_execution_scenarios import run_intraday_execution_scenarios
    data, comparison, _ = research_case
    plan, calls = execution_scenarios_plan(comparison), {"loads": 0, "fits": []}
    loader, fit = research.load_intraday_dataset, research._fit
    def loaded(*args, **kwargs):
        calls["loads"] += 1
        return loader(*args, **kwargs)
    def fitted(*args, **kwargs):
        calls["fits"].append((len(args[0]), args[2]))
        return fit(*args, **kwargs)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(research, "load_intraday_dataset", loaded)
        patch.setattr(research, "_fit", fitted)
        snapshot = run_intraday_execution_scenarios(plan, name="Execution sensitivity")
    return data, plan, snapshot, calls


def test_execution_scenarios_share_one_load_and_fit_and_match_standalone_q7(execution_scenarios_case, research_case):
    from market_vault.research.strategy_experiment import canonical_json
    _, plan, snapshot, calls = execution_scenarios_case
    root = snapshot.as_dict()
    first, second = [row["experiment"] for row in root["report"]["scenarios"]]
    assert calls == {"loads": 1, "fits": [(1420, 1.0), (1775, 1.0)]}
    assert root["report"]["evaluation_count"] == 6
    assert canonical_json(first["report"]) == canonical_json(research_case[2])
    assert canonical_json(second["report"]) == canonical_json(research.run_intraday_research(second["plan"]))
    for child, scenario in zip((first, second), plan["execution_scenarios"], strict=True):
        report, group = child["report"], child["report"]["groups"][0]
        assert report["evaluation_scope"] == "DEVELOPMENT_WALK_FORWARD_ONLY"
        assert child["evaluation_mode"] == "INTRADAY_COMPARISON" and len(report["groups"]) == 1
        assert group["execution_policy"] == scenario["execution"]
        assert all(r["axis_values"] == [] and r["return_change_from_first_cost"] == 0 for r in group["results"])
        assert not set(report["context"]["split"]["TEST"]) & set(report["context"]["evaluated_days"])
        assert group["benchmark"]["execution"]["policy"]["max_hold_bars"] == 78
    assert all((t["entry_slot"], t["exit_slot"], t["exit_reason"]) == (12, 76, "EOD")
               for t in second["report"]["groups"][0]["benchmark"]["execution"]["trades"])
    assert plan == execution_scenarios_plan(research_case[1])


@pytest.mark.parametrize("case", ["duplicate_policy", "duplicate_name", "missing_field", "bool_window", "limit", "diagnostics", "test_field"])
def test_execution_scenarios_preflight_rejects_before_source_io(research_case, monkeypatch, case):
    from market_vault.research.intraday_execution_scenarios import run_intraday_execution_scenarios
    plan = execution_scenarios_plan(research_case[1])
    if case == "duplicate_policy":
        plan["execution_scenarios"][1]["execution"] = {**plan["execution_scenarios"][0]["execution"], "commission_bps": -0.0}
    elif case == "duplicate_name":
        plan["execution_scenarios"][1]["name"] = "Original"
    elif case == "missing_field":
        del plan["execution_scenarios"][1]["execution"]["flatten_minutes"]
    elif case == "bool_window":
        plan["execution_scenarios"][1]["execution"]["max_hold_bars"] = True
    elif case == "limit":
        plan["execution_scenarios"] = plan["execution_scenarios"] * 33
    elif case == "diagnostics":
        plan["comparison_plan"] = diagnostic_plan(plan["comparison_plan"])
    else:
        plan["evaluation_scope"] = "TEST"
    monkeypatch.setattr(research, "load_intraday_dataset", lambda *a, **kw: pytest.fail("invalid scenarios read data"))
    monkeypatch.setattr(research, "_fit", lambda *a, **kw: pytest.fail("invalid scenarios fitted"))
    with pytest.raises(ValueError):
        run_intraday_execution_scenarios(plan)


def test_all_actual_scenario_windows_precede_fit_and_unused_base_is_not_evaluated(research_case, monkeypatch):
    from market_vault.research.intraday_execution_scenarios import run_intraday_execution_scenarios
    plan = execution_scenarios_plan(research_case[1])
    plan["comparison_plan"]["execution"]["entry_delay_minutes"] = 400
    # No actual scenario uses this geometrically invalid base policy.
    result = run_intraday_execution_scenarios(plan).as_dict()
    assert result["report"]["scenarios"][0]["experiment"]["report"] == research_case[2]
    plan["execution_scenarios"][1]["execution"]["entry_delay_minutes"] = 400
    monkeypatch.setattr(research, "_fit", lambda *a, **kw: pytest.fail("a later invalid scenario was checked after fitting"))
    with pytest.raises(ValueError, match="windows do not fit"):
        run_intraday_execution_scenarios(plan)


def test_real_common_folds_tail_predictions_cash_benchmark_and_ridge_oracles(research_case):
    data, plan, report = research_case
    context = report["context"]
    assert {k: len(v) for k, v in context["split"].items()} == {"TRAIN": 25, "VALIDATION": 5, "TEST": 6}
    assert plan["split"] == {"train_end_day": "2025-03-10", "validation_end_day": "2025-03-17", "test_end_day": "2025-03-25"}
    assert len(context["folds"]) == 2 and len(context["validation_keys"]) == 740
    assert [len(f["training_keys"]) for f in context["folds"]] == [1420, 1775]
    assert all(not f["purged_keys"] for f in context["folds"])
    assert context["held_out_test_observation_count"] == 444
    group = report["groups"][0]
    flat, long, ridge = group["results"]
    for candidate in group["results"]:
        assert [p["observation_key"] for p in candidate["predictions"]] == context["validation_keys"]
        assert [d["trading_day"] for d in candidate["execution"]["daily"]] == context["evaluated_days"]
        assert 1 + math.fsum(f["cash_contribution"] for f in candidate["fold_contributions"]) == pytest.approx(candidate["execution"]["metrics"]["final_cash"])
    assert flat["execution"]["metrics"]["trade_count"] == 0
    assert flat["risk"]["annualized_volatility"] == 0 and flat["risk"]["sharpe_ratio"] is None
    assert flat["risk"]["unavailable_reason"] == "ZERO_VOLATILITY"
    assert long["execution"]["metrics"]["trade_count"] == 60
    assert ridge["prediction_metrics"]["prediction_count"] == 740
    assert ridge["prediction_metrics"]["complete_target_count"] == 710
    model = ridge["fold_models"][0]["model"]
    assert model["means"] == pytest.approx([109.875])
    assert model["scales"] == pytest.approx([5.769922009871537])
    assert model["coefficients"] == pytest.approx([0.00000371657145575480065], rel=1e-9)
    assert model["intercept"] == pytest.approx(-0.000188502999704031905, rel=1e-9)
    assert ridge["predictions"][0]["score"] == pytest.approx(0.000257578489272938043, rel=1e-9)
    benchmark = group["benchmark"]
    assert benchmark["execution"]["metrics"]["trade_count"] == 10
    assert all((t["entry_slot"], t["exit_slot"], t["exit_reason"]) == (5, 77, "EOD") for t in benchmark["execution"]["trades"])
    assert benchmark["execution"]["metrics"]["final_cash"] == pytest.approx(1.05983945005456569744)
    assert benchmark["risk"]["return_count"] == 10
    assert benchmark["risk"]["mean_daily_return"] == pytest.approx(.006)
    assert benchmark["risk"]["annualized_volatility"] == pytest.approx(.31035463586033317)
    assert benchmark["risk"]["sharpe_ratio"] == pytest.approx(4.871846028040114)


def test_validation_and_test_source_changes_do_not_leak_into_training(research_case, tmp_path):
    data, plan, expected = research_case
    changed = research.run_intraday_research(comparison_plan(research_data(tmp_path / "validation", changed_day=20)))
    old = expected["groups"][0]["results"][2]
    new = changed["groups"][0]["results"][2]
    for key in ("means", "scales", "coefficients", "intercept"):
        assert new["fold_models"][0]["model"][key] == old["fold_models"][0]["model"][key]
    assert new["fold_models"][1]["model"]["means"] != old["fold_models"][1]["model"]["means"]
    test_only = research.run_intraday_research(comparison_plan(research_data(tmp_path / "test", test_change=True)))
    current = test_only["groups"][0]["results"][2]
    for index in range(2):
        for key in ("means", "scales", "coefficients", "intercept"):
            assert current["fold_models"][index]["model"][key] == old["fold_models"][index]["model"][key]
    assert [p["score"] for p in current["predictions"]] == [p["score"] for p in old["predictions"]]
    assert current["execution"]["metrics"] == old["execution"]["metrics"]


def test_shared_validation_gap_fails_before_fit_even_first_candidate_flat(tmp_path, monkeypatch):
    data = research_data(tmp_path, missing=True)
    monkeypatch.setattr(research, "_fit", lambda *a: pytest.fail("fit happened before price preflight"))
    with pytest.raises(ValueError, match="incomplete session price flow"):
        research.run_intraday_research(comparison_plan(data))


def diagnostic_plan(plan):
    return {"plan_schema_version": research.INTRADAY_DIAGNOSTICS_PLAN_VERSION, "comparison_plan": plan,
            "strategy_name": "Ridge", "parameter_axes": [
                {"parameter": "alpha", "values": [1, 1000]}, {"parameter": "threshold", "values": [0, .00025]}],
            "cost_scenarios": [{"commission_bps": 0, "slippage_bps": 0}, {"commission_bps": 10, "slippage_bps": 5}]}


def test_finite_grid_shared_data_fit_reuse_cost_order_and_bound(research_case, monkeypatch, tmp_path):
    data, plan, report = research_case
    loader, fitter = research.load_intraday_dataset, research._fit
    calls, fits = [], []
    def load(path):
        calls.append(path)
        return loader(path)
    def fit(*args):
        fits.append((len(args[0]), args[2]))
        return fitter(*args)
    monkeypatch.setattr(research, "load_intraday_dataset", load)
    monkeypatch.setattr(research, "_fit", fit)
    actual = research.run_intraday_research(diagnostic_plan(plan))
    assert len(calls) == 1 and len(fits) == 4
    assert actual["evaluation_count"] == 8
    assert actual["context"] == report["context"]
    assert [r["axis_values"] for r in actual["groups"][0]["results"]] == [[1, 0], [1, .00025], [1000, 0], [1000, .00025]]
    for first, second in zip(actual["groups"][0]["results"], actual["groups"][1]["results"], strict=True):
        assert first["predictions"] == second["predictions"] and first["fold_models"] == second["fold_models"]
        assert first["candidate_id"] != second["candidate_id"]
    assert actual["groups"][1]["benchmark"]["execution"]["metrics"]["final_cash"] == pytest.approx(1.028516452870082824)
    from market_vault.research.intraday_experiment import create_intraday_experiment
    from market_vault.research.intraday_plan import extract_intraday_candidate_plan
    saved = create_intraday_experiment(plan=diagnostic_plan(plan), report=actual)
    source = tmp_path / "ridge-grid.json"
    source.write_bytes(saved.content)
    continued = extract_intraday_candidate_plan(source, cost_index=1, candidate_index=3)
    assert continued["strategies"] == [actual["groups"][1]["results"][3]["strategy"]]
    assert continued["strategies"][0]["alpha"] == 1000 and continued["strategies"][0]["threshold"] == .00025
    assert continued["execution"] == actual["groups"][1]["execution_policy"]
    assert len(calls) == 1 and len(fits) == 4 and source.read_bytes() == saved.content
    oversized = diagnostic_plan({**plan, "intraday_data_path": "/unreachable/data.json"})
    oversized["parameter_axes"] = [{"parameter": "alpha", "values": list(range(1, 66))}]
    calls.clear()
    with pytest.raises(ValueError, match="64 evaluations"):
        research.run_intraday_research(oversized)
    assert not calls


def test_gap_days_not_zero_returns_and_actual_target_end_purge(research_case):
    data, plan, _ = research_case
    altered = {**plan, "walk_forward": {"minimum_train_days": 15, "validation_days": 3, "step_days": 5}, "strategies": [plan["strategies"][0]]}
    report = research.run_intraday_research(altered)
    assert len(report["context"]["evaluated_days"]) == 9
    assert report["groups"][0]["results"][0]["risk"]["return_count"] == 9
    assert "2025-03-07" in report["context"]["unevaluated_development_days"]
    source = data.as_dict()["report"]
    boundary = source["sessions"][20]["open_time"]
    days = tuple(s["trading_day"] for s in source["sessions"][:20])
    rows, purged = research.training_rows(source, days, boundary)
    assert len(rows) == 1420 and not purged
    # Pure target selection counterexample, not a fabricated Canonical artifact.
    source["targets"][0]["actual_label_end_time"] = boundary
    rows, purged = research.training_rows(source, days, boundary)
    assert len(rows) == 1419 and len(purged) == 1


def test_empty_observation_fold_rejected_but_one_empty_day_kept(research_case):
    data, plan, _ = research_case
    source = data.as_dict()
    first_fold = {s["trading_day"] for s in source["report"]["sessions"][20:25]}
    source["report"]["observations"] = [row for row in source["report"]["observations"] if row["trading_day"] not in first_fold]
    # Exercise preparation with a pure in-memory row view; public paths still
    # require verified Canonical input. No fabricated artifact is persisted.
    prepared_input = SimpleNamespace(data_id=data.data_id, as_dict=lambda: source)
    with pytest.raises(ValueError, match="no READY observations"):
        research._prepare_intraday_research(plan, data=prepared_input)
    source = data.as_dict()
    absent = source["report"]["sessions"][20]["trading_day"]
    source["report"]["observations"] = [row for row in source["report"]["observations"] if row["trading_day"] != absent]
    prepared = research._prepare_intraday_research(plan, data=prepared_input)
    assert absent in prepared.context["evaluated_days"]
    assert len(prepared.context["validation_keys"]) == 666


def return_uncertainty_fixture(root):
    """130 declared sessions through Canonical/Q5/Q7; 105 DEV cash days.

    Rule-only 30-minute data keeps this longer statistical sample smaller than
    the existing 36-session five-minute fitting fixture. It proves software
    behavior, not evidence of a profitable market strategy.
    """
    from market_vault.research.intraday_experiment import create_intraday_experiment
    from market_vault.research.strategy_experiment import write_strategy_experiment
    current, entries, days, bars = date(2025, 2, 3), [], [], []
    closed_days = {"2025-02-17", "2025-04-18", "2025-05-26", "2025-06-19", "2025-07-04"}
    while len(days) < 130:
        day = current.isoformat()
        closed = current.weekday() >= 5 or day in closed_days
        entries.append((day, "C" if closed else "N"))
        if not closed:
            days.append(day)
        current += timedelta(days=1)
    for index, day in enumerate(days):
        slope = (index % 7 - 3) * .04
        for slot in range(13):
            price = 100 + slot * slope
            bars.append(cd.bar(day, slot, interval="30m", open=price, close=price + .005, code="US.SPY"))
    source = cd.build(root, bars, interval="30m")
    data = build_intraday_dataset({
        "plan_schema_version": "market-vault-intraday-data-plan-v1", "canonical_build_dirs": [str(source.build_path)],
        "schedule": json_values(asdict(cd.schedule(entries))), "symbol": "US.SPY", "interval": "30m",
        "preset": "LIGHT_TECHNICAL", "stride_bars": 1, "target_horizon_bars": None, "dataset_as_of": cd.AS_OF.isoformat()})
    data = replace(data, path=write_intraday_dataset(data, path=root / "intraday.json"))
    comparison = research.default_intraday_research_plan(data, commission_bps=0, slippage_bps=0)
    comparison["feature_fields"] = ["sma_5"]
    comparison["strategies"] = [{"kind": "FEATURE_RULE", "name": "日内均值", "signal_field": "sma_5", "comparator": "GT", "threshold": 100}]
    comparison["walk_forward"] = {"minimum_train_days": 5, "validation_days": 5, "step_days": 5}
    comparison["execution"]["max_hold_bars"] = 2
    plan = {"plan_schema_version": research.INTRADAY_DIAGNOSTICS_PLAN_VERSION, "comparison_plan": comparison,
            "strategy_name": "日内均值", "parameter_axes": [{"parameter": "threshold", "values": [100, 100.2]}],
            "cost_scenarios": [{"commission_bps": 0, "slippage_bps": 0}, {"commission_bps": 3, "slippage_bps": 2}]}
    report = research.run_intraday_research(plan)
    snapshot = create_intraday_experiment(plan=plan, report=report, name="105 日重采样样本")
    path = root / "development.json"
    write_strategy_experiment(snapshot, path=path)
    return SimpleNamespace(data=data, plan=plan, snapshot=snapshot, path=path)


@pytest.fixture(scope="session")
def return_uncertainty_case(tmp_path_factory):
    return return_uncertainty_fixture(tmp_path_factory.mktemp("intraday-return-uncertainty"))


def test_return_uncertainty_stationary_restart_wrap_and_exact_quantile_oracle(monkeypatch):
    from fractions import Fraction
    from market_vault.research import intraday_return_uncertainty as uncertainty
    class Draws:
        def __init__(self):
            self.starts, self.restarts, self.bounds = iter((4, 3)), iter((.2, .1, .9, .8)), []
        def randrange(self, count):
            self.bounds.append(count)
            return next(self.starts)
        def random(self):
            return next(self.restarts)
    draws = Draws()
    assert uncertainty._stationary_indices(5, 5, draws) == [4, 0, 3, 4, 0]
    assert draws.bounds == [5, 5]
    assert [uncertainty._default_block_days(n) for n in (100, 125, 126, 1000)] == [5, 5, 6, 10]
    # Independent rational oracle: each prescribed resample has a occurrences
    # of 1/8 and b of 1/32, out of 100 observations. The paired excess is -1/4.
    values = {"strategy": (0., .125, .03125) + (0.,) * 97}
    values["benchmark"] = tuple(value + .25 for value in values["strategy"])
    values["paired_excess"] = (-.25,) * 100
    pairs = [divmod(index, 91) for index in range(1000)]
    prescribed = iter(pairs)
    def indices(count, block_days, rng):
        a, b = next(prescribed)
        assert count == 100 and block_days == 5
        return [1] * a + [2] * b + [0] * (100 - a - b)
    monkeypatch.setattr(uncertainty, "_stationary_indices", indices)
    rows = [uncertainty._statistic(name, 100, series) for name, series in values.items()]
    sample = {"sample_count": 100, "is_contiguous": True}
    sampling = {"expected_block_count": 20.8, "block_days": 5, "seed": 0, "replications": 1000}
    uncertainty._mean_intervals(rows, values, sample, sampling)
    expected = sorted(Fraction(4 * a + b, 3200) for a, b in pairs)
    lower = (expected[24] * 25 + expected[25] * 975) / 1000
    upper = (expected[974] * 975 + expected[975] * 25) / 1000
    assert rows[0]["mean"] == pytest.approx(float(Fraction(5, 3200)))
    assert (rows[0]["lower"], rows[0]["upper"]) == pytest.approx((float(lower), float(upper)))
    assert (rows[1]["lower"], rows[1]["upper"]) == pytest.approx((float(lower) + .25, float(upper) + .25))
    assert rows[2]["mean"] == -.25 and rows[2]["mean_unavailable_reason"] is None
    assert rows[2]["lower"] is rows[2]["upper"] is None
    assert rows[2]["interval_unavailable_reason"] == "ZERO_SAMPLE_VARIATION"
    # Distinguish a constant input from a nonconstant input with degenerate draws.
    monkeypatch.setattr(uncertainty, "_stationary_indices", lambda count, block_days, rng: list(range(count)))
    rows = [uncertainty._statistic(name, 100, series) for name, series in values.items()]
    uncertainty._mean_intervals(rows, values, sample, sampling)
    assert [row["interval_unavailable_reason"] for row in rows] == ["DEGENERATE_RESAMPLING", "DEGENERATE_RESAMPLING", "ZERO_SAMPLE_VARIATION"]


def test_return_uncertainty_real_long_account_one_decode_paired_cash_days_and_console(return_uncertainty_case, monkeypatch, capsys):
    import json
    import os
    import statistics
    import subprocess
    import sysconfig
    from pathlib import Path
    from market_vault import cli
    from market_vault.research import intraday_return_uncertainty as uncertainty
    from market_vault.research.strategy_experiment import StrategyExperiment
    case = return_uncertainty_case
    original = case.snapshot.as_dict()
    group = original["report"]["groups"][1]
    candidate = group["results"][1]
    actual_days = candidate["execution"]["daily"]
    expected = [row["cash_close"] / row["cash_open"] - 1 for row in actual_days]
    benchmark = [row["cash_close"] / row["cash_open"] - 1 for row in group["benchmark"]["execution"]["daily"]]
    calls, decode, available = {"decode": 0, "accounts": 0}, StrategyExperiment.as_dict, uncertainty._available
    def decoded(self):
        calls["decode"] += 1
        return decode(self)
    def checked(*args, **kwargs):
        calls["accounts"] += 1
        return available(*args, **kwargs)
    monkeypatch.setattr(StrategyExperiment, "as_dict", decoded)
    monkeypatch.setattr(uncertainty, "_available", checked)
    for name in ("load_intraday_dataset", "_fit", "run_intraday_execution"):
        monkeypatch.setattr(research, name, lambda *a, **kw: pytest.fail("uncertainty accessed source, fit or execution"))
    monkeypatch.setattr(cli, "load_settings", lambda *a, **kw: pytest.fail("uncertainty loaded settings"))
    before = case.path.read_bytes()
    result = uncertainty.analyze_intraday_return_uncertainty(case.snapshot, cost_index=1, candidate_index=1)
    assert calls == {"decode": 1, "accounts": 2}
    assert result["sample"]["sample_count"] == 105 and result["sample"]["is_contiguous"]
    assert result["sample"]["gap_days"] == []
    assert result["sample"]["development_day_count"] == 110
    assert result["sample"]["unevaluated_development_day_count"] == 5
    assert result["sample"]["prediction_count"] == 945
    assert result["sample"]["complete_target_count"] is None
    assert result["sample"]["complete_target_count_unavailable_reason"] == "NOT_APPLICABLE"
    assert result["sampling"]["block_days"] == 5 and result["sampling"]["expected_block_count"] == pytest.approx(21.8)
    assert result["candidate_id"] == candidate["candidate_id"] and result["basis"] == {"matches": True, "failed_checks": []}
    assert result["strategy_execution_id"] == candidate["execution"]["execution_id"]
    assert result["benchmark_execution_id"] == group["benchmark"]["execution"]["execution_id"]
    assert any(row["trade_count"] == 0 for row in actual_days) and len(expected) == 105
    assert [row["mean"] for row in result["statistics"]] == pytest.approx([
        statistics.fmean(expected), statistics.fmean(benchmark), statistics.fmean(a - b for a, b in zip(expected, benchmark, strict=True))])
    for row in result["statistics"]:
        assert row["mean_unavailable_reason"] is row["interval_unavailable_reason"] is None
        assert math.isfinite(row["lower"]) and row["lower"] < row["upper"]
    assert uncertainty.analyze_intraday_return_uncertainty(case.snapshot, cost_index=1, candidate_index=1) == result
    assert cli.main(["research-intraday-return-uncertainty", "--experiment", str(case.path),
                     "--cost-index", "1", "--candidate-index", "1"]) == 0
    assert json.loads(capsys.readouterr().out)["report"] == result
    console = Path(sysconfig.get_path("scripts")) / ("market-vault.exe" if os.name == "nt" else "market-vault")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"), "PYTHONIOENCODING": "cp1252:strict"}
    process = subprocess.run([str(console), "research-intraday-return-uncertainty", "--experiment", str(case.path),
                              "--cost-index", "1", "--candidate-index", "1"], env=env, capture_output=True, check=False)
    assert process.returncode == 0 and not process.stderr
    assert process.stdout.isascii() and json.loads(process.stdout)["report"] == result
    invalid = subprocess.run([str(console), "research-intraday-return-uncertainty", "--experiment", str(case.path),
                              "--candidate-index", "-1"], env=env, capture_output=True, check=False)
    assert invalid.returncode == 1 and not invalid.stdout and json.loads(invalid.stderr)["status"] == "FAILED"
    parsed = subprocess.run([str(console), "research-intraday-return-uncertainty", "--experiment", str(case.path),
                             "--seed", "1.5"], env=env, capture_output=True, check=False)
    assert parsed.returncode == 2 and not parsed.stdout
    assert case.path.read_bytes() == before


@pytest.mark.parametrize("changes", [
    {"cost_index": True}, {"candidate_index": 1.5}, {"block_days": True}, {"block_days": 1},
    {"replications": 999}, {"replications": 20001}, {"replications": False}, {"seed": -1}, {"seed": 2 ** 32}, {"seed": True},
])
def test_return_uncertainty_invalid_parameters_precede_decode(return_uncertainty_case, monkeypatch, changes):
    from market_vault.research.intraday_return_uncertainty import analyze_intraday_return_uncertainty
    from market_vault.research.strategy_experiment import StrategyExperiment
    monkeypatch.setattr(StrategyExperiment, "as_dict", lambda self: pytest.fail("invalid parameters decoded an experiment"))
    with pytest.raises(ValueError, match="integer"):
        analyze_intraday_return_uncertainty(return_uncertainty_case.snapshot, **changes)


def test_return_uncertainty_small_sample_and_expected_blocks_keep_means(research_case, return_uncertainty_case):
    from market_vault.research.intraday_experiment import create_intraday_experiment
    from market_vault.research.intraday_return_uncertainty import analyze_intraday_return_uncertainty
    _, plan, report = research_case
    small = analyze_intraday_return_uncertainty(create_intraday_experiment(plan=plan, report=report), candidate_index=1)
    assert small["sample"]["sample_count"] == 10 and small["sample"]["is_contiguous"]
    assert all(row["mean"] is not None and row["lower"] is row["upper"] is None for row in small["statistics"])
    assert all(row["interval_unavailable_reason"] in ("INSUFFICIENT_DAILY_RETURNS", "ZERO_SAMPLE_VARIATION") for row in small["statistics"])
    broad = analyze_intraday_return_uncertainty(return_uncertainty_case.snapshot, candidate_index=1, block_days=100)
    assert broad["sampling"]["block_days_source"] == "EXPLICIT"
    assert all(row["mean"] is not None and row["interval_unavailable_reason"] == "INSUFFICIENT_EXPECTED_BLOCKS" for row in broad["statistics"])


def test_return_uncertainty_real_gap_keeps_cash_means(return_uncertainty_case):
    from market_vault.research.intraday_experiment import create_intraday_experiment
    from market_vault.research.intraday_return_uncertainty import analyze_intraday_return_uncertainty
    plan = deepcopy(return_uncertainty_case.plan["comparison_plan"])
    plan["walk_forward"]["step_days"] = 6
    report = research.run_intraday_research(plan)
    result = analyze_intraday_return_uncertainty(create_intraday_experiment(plan=plan, report=report))
    assert not result["sample"]["is_contiguous"] and result["sample"]["gap_days"]
    assert result["sample"]["sample_count"] == len(report["context"]["evaluated_days"])
    assert all(row["mean"] is not None and row["mean_unavailable_reason"] is None for row in result["statistics"])
    assert all(row["lower"] is row["upper"] is None and row["interval_unavailable_reason"] == "GAPPED_EVALUATION_DAYS" for row in result["statistics"])


@pytest.mark.parametrize("case", ["strategy_cash", "benchmark_cash", "basis"])
def test_return_uncertainty_bad_saved_side_and_full_basis_are_local(return_uncertainty_case, case):
    from market_vault.research.intraday_return_uncertainty import analyze_intraday_return_uncertainty
    from market_vault.research.strategy_experiment import StrategyExperiment
    from test_intraday_experiment import signed
    root = return_uncertainty_case.snapshot.as_dict()
    group = root["report"]["groups"][0]
    execution = group["benchmark"]["execution"] if case == "benchmark_cash" else group["results"][1]["execution"]
    if case == "basis":
        execution["ledger"][-2]["row_version_id"] = "f" * 64
    else:
        execution["trades"][0]["commission_total"] += .01
    result = analyze_intraday_return_uncertainty(StrategyExperiment(signed(root)), candidate_index=1, replications=1000)
    strategy, benchmark, paired = result["statistics"]
    if case == "basis":
        assert result["basis"] == {"matches": False, "failed_checks": ["raw_prices"]}
        assert strategy["lower"] is not None and benchmark["lower"] is not None
        assert paired["mean_unavailable_reason"] == paired["interval_unavailable_reason"] == "BASIS_MISMATCH"
    else:
        bad, good = (strategy, benchmark) if case == "strategy_cash" else (benchmark, strategy)
        assert bad["mean"] is bad["lower"] is bad["upper"] is None
        assert bad["mean_unavailable_reason"] == bad["interval_unavailable_reason"] == "RECORDED_CASH_RECONCILIATION_FAILED"
        assert good["mean"] is not None and good["lower"] is not None
        assert paired["mean_unavailable_reason"] == ("STRATEGY_UNAVAILABLE" if case == "strategy_cash" else "BENCHMARK_UNAVAILABLE")
    assert paired["mean"] is paired["lower"] is paired["upper"] is None
