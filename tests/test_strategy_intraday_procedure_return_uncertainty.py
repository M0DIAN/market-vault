"""Actual selected accounts and discriminating five-series/basis oracles."""

from copy import deepcopy
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from market_vault.research import intraday_inner_selection as inner
from market_vault.research import intraday_procedure_return_uncertainty as procedure
from market_vault.research import intraday_research as research
from market_vault.research import intraday_return_uncertainty as uncertainty
from market_vault.research import intraday_threshold_selection as threshold
from market_vault.research.intraday_data import digest
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.strategy_experiment import StrategyExperiment, write_strategy_experiment
from test_intraday_research import return_uncertainty_data
from test_strategy_intraday_inner_objective_sensitivity import prohibit_recomputation
from test_strategy_intraday_inner_selection import inner_case, resigned  # noqa: F401
from test_strategy_intraday_ml import quadratic_dev_case  # noqa: F401
from test_strategy_intraday_threshold_selection import threshold_case  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def procedure_return_case(tmp_path_factory):
    root = tmp_path_factory.mktemp("procedure-returns")
    data = return_uncertainty_data(root, target_horizon_bars=2)
    days = [row["trading_day"] for row in data.as_dict()["report"]["sessions"]]
    plan = research.default_intraday_research_plan(data, commission_bps=3, slippage_bps=2)
    plan["feature_fields"] = ["return_2"]
    plan["strategies"] = [{"kind": "RIDGE", "name": "Fixed reference", "alpha": 1000., "threshold": -.0005}]
    plan["split"]["validation_end_day"] = days[119]
    # Four outer folds still supply 100 daily observations. Inner holdouts
    # remain the original five days; no unrelated rule report is generated.
    plan["walk_forward"] = {"minimum_train_days": 20, "validation_days": 25, "step_days": 25}
    plan["execution"]["max_hold_bars"] = 2
    source = create_intraday_experiment(plan=plan, report=research.run_intraday_research(plan))
    path = write_strategy_experiment(source, path=root / "source.json").path
    candidate = source.as_dict()["report"]["groups"][0]["results"][0]
    args = dict(expected_experiment_id=source.experiment_id, cost_index=0, candidate_index=0,
                expected_candidate_id=candidate["candidate_id"])
    studies = {}
    for name, run in (("q25", inner.run_intraday_inner_selection), ("q31", threshold.run_intraday_threshold_selection)):
        snapshot = run(path, **args)
        saved = write_strategy_experiment(snapshot, path=root / (name + ".json")).path
        studies[name] = snapshot, saved
    return SimpleNamespace(data=data, plan=plan, source=source, path=path, studies=studies)


def cash_oracle(accounts):
    values = {name: [float(Fraction(row["cash_close"]) / Fraction(row["cash_open"]) - 1)
                     for row in record["execution"]["daily"]] for name, record in accounts.items()}
    for reference in ("fixed_reference", "benchmark"):
        values["procedure_minus_" + reference] = [a - b for a, b in zip(values["procedure"], values[reference], strict=True)]
    return values


def test_real_100_day_studies_five_cash_series_one_decode_no_recompute(procedure_return_case, monkeypatch):
    prohibit_recomputation(monkeypatch)
    from market_vault.research import strategy_experiment
    monkeypatch.setattr(strategy_experiment, "write_strategy_experiment", lambda *a, **kw: pytest.fail("saved a derived report"))
    calls, decode, available = {"decode": 0, "accounts": 0}, StrategyExperiment.as_dict, uncertainty._available
    def decoded(self):
        calls["decode"] += 1
        return decode(self)
    def checked(*args, **kwargs):
        calls["accounts"] += 1
        return available(*args, **kwargs)
    monkeypatch.setattr(StrategyExperiment, "as_dict", decoded)
    monkeypatch.setattr(uncertainty, "_available", checked)
    for kind, (snapshot, path) in procedure_return_case.studies.items():
        before = path.read_bytes()
        calls.update(decode=0, accounts=0)
        report = procedure.analyze_intraday_procedure_return_uncertainty(snapshot)
        assert calls == {"decode": 1, "accounts": 3}
        assert report["status"] == "AVAILABLE" and report["basis"]["matches"]
        assert report["sample"]["sample_count"] == 100 and report["sample"]["fold_count"] == 4
        assert report["sample"]["is_contiguous"] and report["sample"]["gap_days"] == []
        assert report["sampling"]["block_days"] == 5 and report["sampling"]["expected_block_count"] == 20.8
        assert report["sampling"]["replications"] == 5000 and report["sampling"]["seed"] == 0
        assert report["sampling"]["confidence_level"] == .95
        assert not any(report["evidence"][key] for key in ("source_reconstructed", "models_refitted", "execution_replayed"))
        accounts = report["accounts"]
        assert accounts["fixed_reference"]["execution"]["policy"]["max_hold_bars"] == 2
        assert accounts["benchmark"]["execution"]["policy"]["max_hold_bars"] == 13
        assert len(accounts["benchmark"]["execution"]["decisions"]) < len(accounts["procedure"]["predictions"])
        expected = cash_oracle(accounts)
        assert [row["series"] for row in report["statistics"]] == list(procedure.SERIES_ORDER)
        assert [row["trading_day"] for row in report["daily"]] == report["sample"]["evaluated_days"]
        for row in report["statistics"]:
            name = row["series"]
            assert row["mean"] == pytest.approx(math.fsum(expected[name]) / 100, rel=1e-12, abs=1e-15)
            assert [day["values"][name] for day in report["daily"]] == pytest.approx(expected[name], rel=1e-12, abs=1e-15)
            if len(set(day["values"][name] for day in report["daily"])) > 1:
                assert row["lower"] is not None and row["upper"] is not None and row["interval_unavailable_reason"] is None
            else:
                assert row["interval_unavailable_reason"] == "ZERO_SAMPLE_VARIATION"
        assert len(set(day["values"]["procedure_minus_fixed_reference"] for day in report["daily"])) > 1, kind
        assert report["sample"]["account_counts"]["procedure"]["cash_only_day_count"] > 0
        original = json.loads(before)["report"]
        assert accounts["procedure"] == original["selected_account"]
        assert accounts["benchmark"] == original["benchmark"]
        assert path.read_bytes() == before


def test_all_five_series_receive_one_synchronous_resample_stream(procedure_return_case, monkeypatch):
    snapshot = procedure_return_case.studies["q31"][0]
    original = procedure.analyze_intraday_procedure_return_uncertainty(snapshot, replications=1000)
    values = {name: [row["values"][name] for row in original["daily"]] for name in procedure.SERIES_ORDER}
    # Prescribed draws select one real day at a time. Every active series must
    # use that same day; separate account/pair streams would exhaust the 1000.
    draws = iter(range(1000))
    def indices(count, block_days, rng):
        assert count == 100 and block_days == 5
        return [next(draws) % 100] * count
    monkeypatch.setattr(uncertainty, "_stationary_indices", indices)
    report = procedure.analyze_intraday_procedure_return_uncertainty(snapshot, replications=1000)
    assert next(draws, None) is None
    for row in report["statistics"]:
        if len(set(values[row["series"]])) == 1:
            continue
        ordered = sorted(values[row["series"]] * 10)
        # Independent interpolation positions for exactly 1000 replications.
        lower = ordered[24] * .025 + ordered[25] * .975
        upper = ordered[974] * .975 + ordered[975] * .025
        assert (row["lower"], row["upper"]) == pytest.approx((lower, upper), abs=1e-15)


def reseal_benchmark(snapshot, change):
    from test_intraday_experiment import signed
    root = snapshot.as_dict()
    source, selection = root["report"]["source_experiment"], root["plan"]["selection"]
    group = source["report"]["groups"][selection["cost_index"]]
    change(group["benchmark"]["execution"], group["results"][selection["candidate_index"]])
    source = json.loads(signed(source))
    root["report"]["source_experiment"] = source
    root["plan"]["source_experiment"]["experiment_id"] = source["experiment_id"]
    root["report"]["plan_sha256"] = digest(root["plan"])
    root["report"]["benchmark"] = deepcopy(source["report"]["groups"][selection["cost_index"]]["benchmark"])
    return StrategyExperiment(resigned(root))


def test_complete_raw_basis_and_first_eligible_support_block_both_increments(inner_case):
    def price(execution, reference):
        assert execution["ledger"][0]["quantity"] == 0
        execution["ledger"][0]["mark_price"] += 1
    def extra_decision(execution, reference):
        extra = deepcopy(reference["predictions"][1])
        extra.update(target="LONG", score=None)
        execution["decisions"].insert(1, extra)
    for change, failed in ((price, "raw_prices"), (extra_decision, "benchmark_first_eligible_ready")):
        report = procedure.analyze_intraday_procedure_return_uncertainty(reseal_benchmark(inner_case[4], change))
        assert failed in report["basis"]["failed_checks"]
        assert all(row["mean_unavailable_reason"] is None for row in report["statistics"][:3])
        assert all(row["mean"] is None and row["mean_unavailable_reason"] == "BASIS_MISMATCH"
                   for row in report["statistics"][3:])
        assert all(row["values"]["procedure_minus_fixed_reference"] is None for row in report["daily"])


def test_short_real_sources_keep_means_original_nonfirst_reference_and_cli(threshold_case, inner_case, monkeypatch, tmp_path):
    from market_vault import cli
    prohibit_recomputation(monkeypatch)
    monkeypatch.setattr(cli, "load_settings", lambda *a, **kw: pytest.fail("loaded settings"))
    for case, indices in ((inner_case, (1, 1)), (threshold_case, (0, 1))):
        report = procedure.analyze_intraday_procedure_return_uncertainty(case[4])
        assert tuple(report["source_selection"][key] for key in ("cost_index", "candidate_index")) == indices
        assert report["sample"]["sample_count"] == 10 and report["basis"]["matches"]
        assert all(row["mean"] is not None for row in report["statistics"])
        assert all(row["interval_unavailable_reason"] in ("INSUFFICIENT_DAILY_RETURNS", "ZERO_SAMPLE_VARIATION")
                   for row in report["statistics"])
    console = str(Path(sys.executable).with_name("market-vault.exe" if os.name == "nt" else "market-vault"))
    command = [console, "research-intraday-procedure-return-uncertainty", "--experiment"]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    hidden = []
    try:
        for path in (threshold_case[0].path, threshold_case[2]):
            moved = path.with_suffix(".temporarily-unavailable")
            path.rename(moved)
            hidden.append((moved, path))
        for path in (tmp_path / "missing.json", threshold_case[5]):
            process = subprocess.run([*command, str(path)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
            assert process.returncode == (0 if path == threshold_case[5] else 1)
            payload = json.loads(process.stdout if process.returncode == 0 else process.stderr)
            assert payload["result_schema_version"] == procedure.INTRADAY_PROCEDURE_RETURN_UNCERTAINTY_VERSION
            if process.returncode == 0:
                assert payload["report"]["sample"]["sample_count"] == 10
    finally:
        for moved, path in hidden:
            moved.rename(path)


def test_unavailable_source_and_invalid_sampling_do_not_access_sources(quadratic_dev_case, tmp_path, monkeypatch, capsys):
    plan = deepcopy(quadratic_dev_case[1])
    plan["walk_forward"]["minimum_train_days"] = 14
    plan["strategies"] = [plan["strategies"][0]]
    source = create_intraday_experiment(plan=plan, report=research.run_intraday_research(plan))
    path = write_strategy_experiment(source, path=tmp_path / "short-source.json").path
    candidate = source.as_dict()["report"]["groups"][0]["results"][0]
    study = inner.run_intraday_inner_selection(path, expected_experiment_id=source.experiment_id,
        cost_index=0, candidate_index=0, expected_candidate_id=candidate["candidate_id"])
    prohibit_recomputation(monkeypatch)
    report = procedure.analyze_intraday_procedure_return_uncertainty(study)
    assert report["status"] == "UNAVAILABLE" and report["unavailable_reason"] == "SOURCE_STUDY_UNAVAILABLE"
    assert report["statistics"] == report["daily"] == [] and report["accounts"] == {}
    assert report["sample"] is report["sampling"] is report["basis"] is None
    with pytest.raises(ValueError, match="Q25 or Q31"):
        procedure.analyze_intraday_procedure_return_uncertainty(source)
    from market_vault import cli, intraday_ml_diagnostics_cli
    monkeypatch.setattr(StrategyExperiment, "as_dict", lambda *a: pytest.fail("decoded before validation"))
    monkeypatch.setattr(intraday_ml_diagnostics_cli, "load_strategy_experiment", lambda *a: pytest.fail("read before validation"))
    for args, flag, value in (({"block_days": 1}, "--block-days", "1"),
                              ({"replications": 999}, "--replications", "999"),
                              ({"seed": True}, "--seed", "-1")):
        with pytest.raises(ValueError):
            procedure.analyze_intraday_procedure_return_uncertainty(study, **args)
        assert cli.main(["research-intraday-procedure-return-uncertainty", "--experiment", "absent.json", flag, value]) == 1
        assert json.loads(capsys.readouterr().err)["status"] == "FAILED"


def test_existing_block_and_gap_gates_and_missing_cash_day(procedure_return_case, tmp_path):
    snapshot = procedure_return_case.studies["q31"][0]
    blocked = procedure.analyze_intraday_procedure_return_uncertainty(snapshot, block_days=1000, replications=1000)
    assert all(row["mean"] is not None and row["lower"] is None and row["upper"] is None for row in blocked["statistics"])
    assert all(row["interval_unavailable_reason"] in ("INSUFFICIENT_EXPECTED_BLOCKS", "ZERO_SAMPLE_VARIATION")
               for row in blocked["statistics"])
    plan = deepcopy(procedure_return_case.plan)
    plan["walk_forward"]["step_days"] = 26
    source = create_intraday_experiment(plan=plan, report=research.run_intraday_research(plan))
    path = write_strategy_experiment(source, path=tmp_path / "gap-source.json").path
    candidate = source.as_dict()["report"]["groups"][0]["results"][0]
    study = threshold.run_intraday_threshold_selection(path, expected_experiment_id=source.experiment_id,
        cost_index=0, candidate_index=0, expected_candidate_id=candidate["candidate_id"])
    report = procedure.analyze_intraday_procedure_return_uncertainty(study)
    assert not report["sample"]["is_contiguous"] and len(report["sample"]["gap_days"]) == 2
    assert all(row["interval_unavailable_reason"] in ("GAPPED_EVALUATION_DAYS", "ZERO_SAMPLE_VARIATION")
               for row in report["statistics"])
    # A missing recorded cash-only day fails immutable admission, before a
    # daily-vector zip could silently shorten the paired sample.
    from market_vault.backtest.intraday import _digest
    from test_strategy_intraday_threshold_selection import resigned as threshold_signed
    root = snapshot.as_dict()
    account = root["report"]["selected_account"]["execution"]
    day = next(row for row in account["daily"] if row["trade_count"] == 0)
    account["daily"].remove(day)
    account["execution_id"] = _digest({key: value for key, value in account.items() if key != "execution_id"})
    with pytest.raises(ValueError, match="complete evaluated dates"):
        procedure.analyze_intraday_procedure_return_uncertainty(StrategyExperiment(threshold_signed(root)))
