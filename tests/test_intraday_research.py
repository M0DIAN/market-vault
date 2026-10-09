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


def test_finite_grid_shared_data_fit_reuse_cost_order_and_bound(research_case, monkeypatch):
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
