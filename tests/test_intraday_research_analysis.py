"""Saved intraday analyses and native prediction diagnostics with numerical oracles."""

from copy import deepcopy
from datetime import timedelta
import math
from types import SimpleNamespace

import pytest

from market_vault.research import intraday_research as research
from test_intraday_research import (
    _feature_ablation_case,
    _signal_delay_oracle_case,
    diagnostic_plan,
    execution_scenarios_case,
    family_test_rows,
    portfolio_execution,
    research_case,
    return_uncertainty_case,
)


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
    snapshot = create_intraday_experiment(plan=plan, report=report)
    result = analyze_intraday_return_uncertainty(snapshot)
    assert not result["sample"]["is_contiguous"] and result["sample"]["gap_days"]
    assert result["sample"]["sample_count"] == len(report["context"]["evaluated_days"])
    assert all(row["mean"] is not None and row["mean_unavailable_reason"] is None for row in result["statistics"])
    assert all(row["lower"] is row["upper"] is None and row["interval_unavailable_reason"] == "GAPPED_EVALUATION_DAYS" for row in result["statistics"])
    # Reuse this actual gapped account for Q18; a gap cannot become fabricated
    # cash days in the selected path, even after enough historical observations.
    from market_vault.research.intraday_sequential_selection import analyze_intraday_sequential_selection
    selection = analyze_intraday_sequential_selection(snapshot)
    assert selection["availability"]["unavailable_reason"] == "GAPPED_EVALUATION_DAYS"
    assert selection["source_sample"]["gap_days"] == result["sample"]["gap_days"]
    assert selection["path"] == selection["daily_returns"] == selection["sample"]["evaluated_days"] == []
    assert all(row["chosen_candidate_index"] is None for row in selection["folds"])
    # Q19 is deterministic re-execution, so it retains these actual gaps but
    # does not impose Q15's statistical continuity/minimum-history gate.
    from market_vault.research.intraday_signal_delay import analyze_intraday_signal_delay
    delayed = analyze_intraday_signal_delay(snapshot)
    assert delayed["availability"]["status"] == "AVAILABLE"
    assert delayed["sample"]["gap_days"] == result["sample"]["gap_days"]
    for scenario in delayed["scenarios"]:
        assert [row["trading_day"] for row in scenario["strategy"]["execution"]["daily"]] == report["context"]["evaluated_days"]
    from market_vault.research.intraday_portfolio_rebalance import analyze_intraday_portfolio_rebalance
    rebalanced = analyze_intraday_portfolio_rebalance(snapshot, snapshot)
    assert rebalanced["availability"]["status"] == "AVAILABLE"
    assert rebalanced["sample"]["gap_days"] == result["sample"]["gap_days"]
    days = report["context"]["evaluated_days"]
    assert [row["trading_day"] for row in rebalanced["daily_returns"]] == days
    for account in ("portfolio", "benchmark"):
        assert [row["trading_day"] for row in rebalanced["daily_allocations"][account]] == [day for day in days for _ in range(3)]
        assert [row["trading_day"] for row in rebalanced["cash_transfers"][account]] == [day for day in days[1:] for _ in range(3)]


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


def test_family_bounds_exact_centered_joint_oracle_duplicate_and_reordered_columns(monkeypatch):
    from fractions import Fraction
    from market_vault.research import intraday_family_bounds as family
    a = (0., .125, .03125) + (0.,) * 97
    b = (.0625, -.0625, .25) + (.0625,) * 97
    fixed = (.1,) * 100
    pairs = [divmod(index, 91) for index in range(1000)]
    expected_maxima = sorted(max(Fraction(4 * x + y - 5, 3200), Fraction(-4 * x + 6 * y - 2, 3200), 0)
                             for x, y in pairs)
    expected_deduction = (19 * expected_maxima[949] + expected_maxima[950]) / 20
    sample = {"sample_count": 100, "is_contiguous": True}
    sampling = {"expected_block_count": 20.8, "block_days": 5, "seed": 0, "replications": 1000}
    actual_quantile, actual_mean = family._quantile, family._mean
    captured = []
    def quantile(values, probability):
        assert probability == .95
        captured.append(values)
        return actual_quantile(values, probability)
    def mean(values):
        assert not all(value == .1 for value in values), "constant columns must contribute exact zero directly"
        return actual_mean(values)
    monkeypatch.setattr(family, "_quantile", quantile)
    monkeypatch.setattr(family, "_mean", mean)
    def calculate(columns):
        prescribed, calls = iter(pairs), []
        def indices(count, block_days, rng):
            calls.append((count, block_days))
            x, y = next(prescribed)
            return [1] * x + [2] * y + [0] * (count - x - y)
        monkeypatch.setattr(family, "_stationary_indices", indices)
        rows = family_test_rows(columns)
        inference = family._family_bounds(rows, columns, sample, sampling, {"matches": True})
        assert calls == [(100, 5)] * 1000  # One shared draw per replicate, not independent candidate streams.
        return rows, inference
    rows, inference = calculate([a, b, fixed])
    assert captured[-1] == pytest.approx([float(value) for value in expected_maxima])
    assert inference == {"status": "AVAILABLE", "reason": None, "detail": None,
                         "deduction": pytest.approx(float(expected_deduction))}
    assert [row["mean_excess"] for row in rows] == pytest.approx([5 / 3200, 202 / 3200, .1])
    assert [row["lower"] for row in rows[:2]] == pytest.approx([float(Fraction(5, 3200) - expected_deduction),
                                                              float(Fraction(202, 3200) - expected_deduction)])
    assert rows[2]["lower"] is None and rows[2]["bound_unavailable_reason"] == "ZERO_SAMPLE_VARIATION"
    duplicate, duplicate_inference = calculate([a, b, fixed, a])
    reordered, reordered_inference = calculate([fixed, b, a])
    assert duplicate_inference == reordered_inference == inference
    assert [row["lower"] for row in duplicate] == [row["lower"] for row in rows] + [rows[0]["lower"]]
    assert [row["lower"] for row in reordered] == [rows[2]["lower"], rows[1]["lower"], rows[0]["lower"]]
    _, narrower = calculate([a])
    assert narrower["deduction"] < inference["deduction"]  # The volatile member widens the common deduction.


def test_family_bounds_constants_joint_degeneracy_tiny_returns_and_overflow(monkeypatch):
    from market_vault.research import intraday_family_bounds as family
    sample = {"sample_count": 100, "is_contiguous": True}
    sampling = {"expected_block_count": 20.8, "block_days": 5, "seed": 0, "replications": 1000}
    def calculate(columns):
        rows = family_test_rows(columns)
        return rows, family._family_bounds(rows, columns, sample, sampling, {"matches": True})
    fixed = [(1e-14,) * 100, (-.25,) * 100]
    rows, inference = calculate(fixed)
    assert inference["reason"] == "DEGENERATE_FAMILY" and inference["deduction"] is None
    assert all(row["bound_unavailable_reason"] == "ZERO_SAMPLE_VARIATION" and row["lower"] is None for row in rows)
    assert rows[0]["mean_excess"] == 1e-14
    monkeypatch.setattr(family, "_stationary_indices", lambda count, block_days, rng: list(range(count)))
    rows, inference = calculate([(0., 1.) * 50, (1., 0.) * 50])
    assert inference["reason"] == "DEGENERATE_FAMILY"
    assert all(row["bound_unavailable_reason"] == "DEGENERATE_FAMILY" for row in rows)
    draws = iter([0, 1] * 500)
    monkeypatch.setattr(family, "_stationary_indices", lambda count, block_days, rng: [next(draws)] * count)
    rows, inference = calculate([(0., 1e-14, 2e-14) + (0.,) * 97,
                                 (.5e-14,) * 3 + (0.,) * 97])
    assert inference["status"] == "AVAILABLE" and inference["deduction"] > 0
    assert 0 < rows[0]["mean_excess"] < 1e-12 and rows[0]["lower"] < 0
    assert rows[1]["mean_excess"] > 0 and rows[1]["lower"] is None
    assert rows[1]["bound_unavailable_reason"] == "DEGENERATE_RESAMPLING"
    # Finite inputs whose centered deviation overflows must block the entire
    # family, without retaining an earlier member's apparent bound.
    monkeypatch.setattr(family, "_stationary_indices", lambda count, block_days, rng: [1] * count)
    rows, inference = calculate([(0., .125) * 50, (-1e308, 1e308) + (-1e308,) * 98])
    assert inference["reason"] == "NUMERIC_OVERFLOW" and inference["deduction"] is None
    assert all(row["mean_excess"] is not None and row["lower"] is None
               and row["bound_unavailable_reason"] == "NUMERIC_OVERFLOW" for row in rows)


def test_family_bounds_real_all_members_one_decode_and_installed_console(return_uncertainty_case, monkeypatch, capsys, tmp_path):
    import json
    import os
    import statistics
    import subprocess
    import sysconfig
    from pathlib import Path
    from market_vault import cli
    from market_vault.research import intraday_family_bounds as family
    from market_vault.research import intraday_return_uncertainty as uncertainty
    from market_vault.research.strategy_experiment import StrategyExperiment
    case = return_uncertainty_case
    original = case.snapshot.as_dict()
    group = original["report"]["groups"][1]
    benchmark = [row["cash_close"] / row["cash_open"] - 1 for row in group["benchmark"]["execution"]["daily"]]
    expected = [statistics.fmean(row["cash_close"] / row["cash_open"] - 1 - reference
                                for row, reference in zip(candidate["execution"]["daily"], benchmark, strict=True))
                for candidate in group["results"]]
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
        monkeypatch.setattr(research, name, lambda *a, **kw: pytest.fail("family bounds accessed source, fit or execution"))
    monkeypatch.setattr(cli, "load_settings", lambda *a, **kw: pytest.fail("family bounds loaded settings"))
    before = case.path.read_bytes()
    report = family.analyze_intraday_family_bounds(case.snapshot, cost_index=1)
    assert calls == {"decode": 1, "accounts": 3}
    assert report["experiment_id"] == original["experiment_id"] and report["data_id"] == original["dataset_id"]
    assert report["family_scope"] == "SAVED_COST_GROUP_ONLY" and report["historical_search_coverage"] == "UNKNOWN"
    assert (report["cost_index"], report["cost_group_count"], report["evaluation_count"], report["family_size"]) == (1, 2, 4, 2)
    assert report["execution_policy"] == group["execution_policy"]
    assert report["benchmark_execution_id"] == group["benchmark"]["execution"]["execution_id"]
    assert report["basis"] == {"matches": True, "failed_checks": []}
    assert report["sample"]["sample_count"] == 105 and report["sample"]["fold_count"] == 21
    assert report["sample"]["evaluated_days"] == original["report"]["context"]["evaluated_days"]
    assert report["sample"]["is_contiguous"] and report["sample"]["gap_days"] == []
    assert (report["sample"]["development_day_count"], report["sample"]["unevaluated_development_day_count"]) == (110, 5)
    sampling = report["sampling"]
    assert (sampling["block_days"], sampling["replications"], sampling["seed"], sampling["confidence_level"]) == (5, 5000, 0, .95)
    assert sampling["block_days_source"] == "CUBE_ROOT_HEURISTIC" and sampling["expected_block_count"] == pytest.approx(21.8)
    assert sampling["bound_method"] == "SINGLE_STEP_UNSTUDENTIZED_CENTERED_MAX" and sampling["bound_type"] == "ONE_SIDED_LOWER"
    assert report["family_inference"]["status"] == "AVAILABLE"
    deduction = report["family_inference"]["deduction"]
    assert [row["mean_excess"] for row in report["members"]] == pytest.approx(expected)
    for index, (row, candidate) in enumerate(zip(report["members"], group["results"], strict=True)):
        assert row["candidate_index"] == index and row["candidate_id"] == candidate["candidate_id"]
        assert row["execution_id"] == candidate["execution"]["execution_id"] and row["strategy"] == candidate["strategy"]
        assert row["sample_count"] == 105 and row["basis"] == {"matches": True, "failed_checks": []}
        assert row["prediction_coverage"] == {"prediction_count": 945, "complete_target_count": None,
                                             "complete_target_count_unavailable_reason": "NOT_APPLICABLE"}
        assert row["mean_unavailable_reason"] is row["bound_unavailable_reason"] is row["detail"] is None
        assert row["lower"] == pytest.approx(expected[index] - deduction)
        assert any(day["trade_count"] == 0 for day in candidate["execution"]["daily"])
    assert family.analyze_intraday_family_bounds(case.snapshot, cost_index=1) == report
    assert cli.main(["research-intraday-family-bounds", "--experiment", str(case.path), "--cost-index", "1"]) == 0
    assert json.loads(capsys.readouterr().out)["report"] == report
    console = Path(sysconfig.get_path("scripts")) / ("market-vault.exe" if os.name == "nt" else "market-vault")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"), "PYTHONIOENCODING": "cp1252:strict"}
    command = [str(console), "--settings", str(tmp_path / "absent-settings.yaml"), "research-intraday-family-bounds",
               "--experiment", str(case.path), "--cost-index", "1"]
    process = subprocess.run(command, env=env, capture_output=True, check=False)
    assert process.returncode == 0 and not process.stderr
    assert process.stdout.isascii() and json.loads(process.stdout)["report"] == report
    configured = family.analyze_intraday_family_bounds(case.snapshot, cost_index=1, block_days=6, replications=1000, seed=17)
    explicit = subprocess.run([*command, "--block-days", "6", "--replications", "1000", "--seed", "17"], env=env, capture_output=True, check=False)
    assert explicit.returncode == 0 and json.loads(explicit.stdout)["report"] == configured
    assert configured["sampling"]["block_days_source"] == "EXPLICIT" and configured["family_bounds_id"] != report["family_bounds_id"]
    invalid = subprocess.run([*command, "--cost-index", "-1"], env=env, capture_output=True, check=False)
    assert invalid.returncode == 1 and not invalid.stdout and json.loads(invalid.stderr)["status"] == "FAILED"
    for extra in (["--seed", "1.5"], ["--candidate-index", "0"]):
        parsed = subprocess.run([*command, *extra], env=env, capture_output=True, check=False)
        assert parsed.returncode == 2 and not parsed.stdout
    assert case.path.read_bytes() == before


@pytest.mark.parametrize("case", ["cash", "raw_basis", "decision_basis", "overflow", "benchmark"])
def test_family_bounds_hidden_member_blocks_complete_family_without_losing_good_means(return_uncertainty_case, case):
    from datetime import datetime
    from market_vault.research.intraday_family_bounds import analyze_intraday_family_bounds
    from market_vault.research.strategy_experiment import StrategyExperiment
    from test_intraday_experiment import signed
    root = return_uncertainty_case.snapshot.as_dict()
    group = root["report"]["groups"][1]
    bad = group["results"][1]
    execution = group["benchmark"]["execution"] if case == "benchmark" else bad["execution"]
    if case == "raw_basis":
        execution["ledger"][-2]["row_version_id"] = "f" * 64
    elif case == "decision_basis":
        # The immutable grammar accepts a different valid decision-grid point
        # with the same observation key; self-basis and day counts still match.
        # Cost scenarios must retain identical predictions for this candidate.
        for saved_group in root["report"]["groups"]:
            candidate = saved_group["results"][1]
            for row in (candidate["predictions"][0], candidate["execution"]["decisions"][0]):
                row["slot"] -= 1
                row["decision_time"] = (datetime.fromisoformat(row["decision_time"]) - timedelta(minutes=30)).isoformat()
    elif case == "overflow":
        execution["trades"][0]["quantity"] = 1e308
        execution["trades"][0]["exit_raw_open"] = 1e308
    else:
        execution["trades"][0]["commission_total"] += .01
    result = analyze_intraday_family_bounds(StrategyExperiment(signed(root)), cost_index=1, replications=1000)
    first, second = result["members"]
    assert result["family_size"] == 2 and [row["candidate_index"] for row in result["members"]] == [0, 1]
    assert result["family_inference"]["status"] == "UNAVAILABLE" and result["family_inference"]["deduction"] is None
    assert all(row["lower"] is None for row in result["members"])
    if case in ("raw_basis", "decision_basis"):
        failed = "raw_prices" if case == "raw_basis" else "decision_identity"
        assert result["basis"] == {"matches": False, "failed_checks": [failed]}
        assert result["family_inference"]["reason"] == first["bound_unavailable_reason"] == "BASIS_MISMATCH"
        assert first["mean_excess"] is not None and first["mean_unavailable_reason"] is None
        if case == "raw_basis":
            assert second["mean_excess"] is None and second["mean_unavailable_reason"] == "BASIS_MISMATCH"
        else:
            assert second["mean_excess"] is not None and second["mean_unavailable_reason"] is None
            assert all(row["basis"] == {"matches": True, "failed_checks": []} for row in result["members"])
    else:
        assert result["family_inference"]["reason"] == "FAMILY_MEMBER_UNAVAILABLE"
        if case == "benchmark":
            assert all(row["mean_excess"] is None and row["mean_unavailable_reason"] == "BENCHMARK_UNAVAILABLE" for row in result["members"])
        else:
            assert first["mean_excess"] is not None and first["bound_unavailable_reason"] == "FAMILY_MEMBER_UNAVAILABLE"
            assert second["mean_excess"] is None and second["mean_unavailable_reason"] == "STRATEGY_UNAVAILABLE"
        underlying = "NUMERIC_OVERFLOW" if case == "overflow" else "RECORDED_CASH_RECONCILIATION_FAILED"
        assert underlying in second["detail"]


def test_family_bounds_common_gates_preserve_means_and_reject_subset_before_decode(return_uncertainty_case, monkeypatch):
    from market_vault.research import intraday_family_bounds as family
    from market_vault.research.strategy_experiment import StrategyExperiment
    blocked = family.analyze_intraday_family_bounds(return_uncertainty_case.snapshot, block_days=100, replications=1000)
    assert blocked["family_inference"]["reason"] == "INSUFFICIENT_EXPECTED_BLOCKS"
    assert all(row["mean_excess"] is not None and row["lower"] is None and row["bound_unavailable_reason"] == "INSUFFICIENT_EXPECTED_BLOCKS"
               for row in blocked["members"])
    monkeypatch.setattr(StrategyExperiment, "as_dict", lambda self: pytest.fail("invalid family parameters decoded a snapshot"))
    with pytest.raises(ValueError, match="integer"):
        family.analyze_intraday_family_bounds(return_uncertainty_case.snapshot, cost_index=True)
    with pytest.raises(TypeError, match="candidate_index"):
        family.analyze_intraday_family_bounds(return_uncertainty_case.snapshot, candidate_index=0)


def test_portfolio_two_day_fixed_capital_oracle_preserves_same_clock_drawdown_and_daily_risk():
    from market_vault.research import intraday_portfolio as portfolio
    prices = [[(1, 1), (1, 4), (1, 1), (2, 2)], [(2, 2), (2, 2), (2, 2), (1, 1)]]
    a = portfolio_execution(prices, [{0: "LONG"}, {0: "LONG"}])
    b = portfolio_execution(prices, [{}, {}])
    assert [row["return"] for row in a["daily"]] == [1.0, -.5]
    allocation = portfolio._allocation(.5, .5)
    path, daily = portfolio._combined_path(a, b, a, b, allocation)
    assert [1.0, *[row["cash_close"] for row in daily]] == [1.0, 1.5, 1.0]
    assert [row["return"] for row in daily] == pytest.approx([.5, -1 / 3])
    assert math.prod(1 + .5 * row["return"] for row in a["daily"]) - 1 == .125
    summary = portfolio._account_summary(daily, path)
    assert summary["summary"]["total_return"]["value"] == 0
    assert summary["summary"]["observed_max_drawdown"]["value"] == pytest.approx(.6)
    assert .5 * a["metrics"]["observed_max_drawdown"] == .375
    # The high CLOSE and lower following OPEN share a clock. Keeping only the
    # final point at that timestamp would erase the actual portfolio peak.
    high, following = path[3:5]
    assert high["timestamp"] == following["timestamp"] and high["phase"] == "CLOSE" and following["phase"] == "OPEN"
    assert high["equity"] == 2.5 and following["equity"] == 1 and following["drawdown"] == pytest.approx(.6)
    assert [row["sequence"] for row in path] == list(range(16))
    risk = summary["risk"]
    assert (risk["annualization_factor"], risk["risk_free_rate"], risk["ddof"], risk["zero_volatility_tolerance"]) == (252, 0, 1, 1e-15)
    assert risk["return_count"]["value"] == 2 and risk["mean_daily_return"]["value"] == pytest.approx(1 / 12)
    assert risk["annualized_volatility"]["value"] == pytest.approx(5 / (6 * math.sqrt(2)) * math.sqrt(252))
    assert risk["sharpe_ratio"]["value"] == pytest.approx(math.sqrt(504) / 10)


def test_portfolio_holding_elapsed_minutes_early_close_and_tiny_positive_quantity():
    from market_vault.research import intraday_portfolio as portfolio
    prices = [[(1e15, 1e15)] * 13, [(1e15, 1e15)] * 7]
    a = portfolio_execution(prices, [{0: "LONG", 2: "FLAT"}, {0: "LONG", 1: "FLAT"}])
    b = portfolio_execution(prices, [{1: "LONG", 3: "FLAT"}, {}])
    assert 0 < a["trades"][0]["quantity"] < 1e-12
    actual = portfolio._holding_overlap(a, b, 390 + 210)
    expected = {"both": 30, "a_only": 60, "b_only": 30, "neither": 480}
    assert {key: row["minutes"]["value"] for key, row in actual.items()} == expected
    assert {key: row["ratio"]["value"] for key, row in actual.items()} == pytest.approx({key: value / 600 for key, value in expected.items()})
    assert sum(row["ratio"]["value"] for row in actual.values()) == pytest.approx(1)


def test_portfolio_cash_days_pearson_tolerance_and_unrounded_joint_losses():
    from market_vault.research import intraday_portfolio as portfolio
    prices = [[(1, 1), (1, 1), (1, 1), (1 - loss, 1 - loss)] for loss in (1e-12, 2e-12, .01)]
    a = portfolio_execution(prices, [{0: "LONG"}, {0: "LONG"}, {}])
    b = portfolio_execution(prices, [{0: "LONG"}, {0: "LONG"}, {}])
    av, reason, _ = portfolio._daily_values(a, None)
    bv, _, _ = portfolio._daily_values(b, None)
    assert reason is None and av[-1] == bv[-1] == 0
    days = [row["trading_day"] for row in a["daily"]]
    result = portfolio._complementarity(a, b, av, bv, {"sample_count": 3, "evaluated_days": days, "total_session_minutes": 360})
    assert -1e-12 < av[0] < 0 and av[1] < -1e-12
    assert result["joint_loss_days"] == days[1:2] and result["joint_loss_count"]["value"] == 1
    assert result["joint_loss_ratio"]["value"] == pytest.approx(1 / 3)
    assert result["correlation"]["value"] == pytest.approx(1)
    assert portfolio._correlation((0., 1e-14, 2e-14), (2e-14, 1e-14, 0.))["value"] == pytest.approx(-1)
    assert portfolio._correlation((0., 1e-16), (0., 1.))["unavailable_reason"] == "ZERO_VOLATILITY"
    assert portfolio._correlation((0.,), (0.,))["unavailable_reason"] == "INSUFFICIENT_DAILY_RETURNS"


def test_portfolio_real_saved_accounts_full_path_cost_attribution_and_installed_console(return_uncertainty_case, monkeypatch, capsys, tmp_path):
    import json
    import os
    import statistics
    import subprocess
    import sysconfig
    from pathlib import Path
    from market_vault import cli
    from market_vault.research import intraday_portfolio as portfolio
    from market_vault.research import intraday_return_uncertainty as uncertainty
    from market_vault.research.strategy_experiment import StrategyExperiment
    case = return_uncertainty_case
    root = case.snapshot.as_dict()
    other = StrategyExperiment(case.snapshot.content)
    groups = root["report"]["groups"]
    a, b = groups[1]["results"][1]["execution"], groups[0]["results"][0]["execution"]
    ab, bb = groups[1]["benchmark"]["execution"], groups[0]["benchmark"]["execution"]
    calls, decode, available = {"decode": 0, "accounts": 0}, StrategyExperiment.as_dict, uncertainty._available
    checked_accounts = []
    def decoded(self):
        calls["decode"] += 1
        return decode(self)
    def checked(*args, **kwargs):
        calls["accounts"] += 1
        checked_accounts.append((args[0]["execution_id"], args[1], args[2]))
        return available(*args, **kwargs)
    monkeypatch.setattr(StrategyExperiment, "as_dict", decoded)
    monkeypatch.setattr(uncertainty, "_available", checked)
    for name in ("load_intraday_dataset", "_fit", "run_intraday_execution"):
        monkeypatch.setattr(research, name, lambda *a, **kw: pytest.fail("portfolio accessed source, fit or execution"))
    monkeypatch.setattr(cli, "load_settings", lambda *a, **kw: pytest.fail("portfolio loaded settings"))
    before = case.path.read_bytes()
    options = dict(left_cost_index=1, left_candidate_index=1, right_cost_index=0, right_candidate_index=0, weight_a=.35, weight_b=.45)
    result = portfolio.analyze_intraday_portfolio(case.snapshot, other, **options)
    assert calls == {"decode": 2, "accounts": 4}
    folds = root["report"]["context"]["folds"]
    assert checked_accounts == [(a["execution_id"], folds, groups[1]["results"][1]["fold_contributions"]),
                                (ab["execution_id"], folds, None),
                                (b["execution_id"], folds, groups[0]["results"][0]["fold_contributions"]),
                                (bb["execution_id"], folds, None)]
    assert result["availability"]["status"] == "AVAILABLE" and result["basis"] == {"matches": True, "failed_checks": []}
    assert result["sample"]["sample_count"] == 105 and result["sample"]["total_session_minutes"] == 105 * 390
    assert result["sample"]["evaluated_days"] == result["left"]["sample"]["evaluated_days"] == result["right"]["sample"]["evaluated_days"]
    assert (result["left"]["cost_index"], result["left"]["candidate_index"], result["right"]["cost_index"], result["right"]["candidate_index"]) == (1, 1, 0, 0)
    assert result["left"]["strategy_execution_id"] == a["execution_id"] and result["right"]["strategy_execution_id"] == b["execution_id"]
    assert result["left"]["benchmark_execution_id"] == ab["execution_id"] and result["right"]["benchmark_execution_id"] == bb["execution_id"]
    assert result["left"]["execution_policy"] == a["policy"] and result["right"]["execution_policy"] == b["policy"]
    assert result["left"]["benchmark_execution_policy"] == ab["policy"] and result["right"]["benchmark_execution_policy"] == bb["policy"]
    assert "execution_id" not in result["portfolio"] and "trades" not in result["portfolio"]
    cash_weight = 1 - math.fsum((.35, .45))
    for point, pa, pb, pab, pbb in zip(result["path"], a["ledger"], b["ledger"], ab["ledger"], bb["ledger"], strict=True):
        assert (point["sequence"], point["timestamp"], point["phase"]) == (pa["sequence"], pa["timestamp"], pa["phase"])
        assert (point["equity"], point["cash"], point["benchmark_equity"], point["benchmark_cash"]) == pytest.approx((
            cash_weight + .35 * pa["equity"] + .45 * pb["equity"], cash_weight + .35 * pa["cash"] + .45 * pb["cash"],
            cash_weight + .35 * pab["equity"] + .45 * pbb["equity"], cash_weight + .35 * pab["cash"] + .45 * pbb["cash"]))
    for name, aa, ba, prefix in (("portfolio", a, b, ""), ("benchmark", ab, bb, "benchmark_")):
        expected = []
        for row, da, db in zip(result["daily_returns"], aa["daily"], ba["daily"], strict=True):
            opened, closed = cash_weight + .35 * da["cash_open"] + .45 * db["cash_open"], cash_weight + .35 * da["cash_close"] + .45 * db["cash_close"]
            expected.append(closed / opened - 1)
            assert (row[prefix + "cash_open"], row[prefix + "cash_close"], row[prefix + "return"]) == pytest.approx((opened, closed, expected[-1]))
        risk = result[name]["risk"]
        assert risk["mean_daily_return"]["value"] == pytest.approx(statistics.mean(expected))
        assert risk["annualized_volatility"]["value"] == pytest.approx(statistics.stdev(expected) * math.sqrt(252))
        rows = result["attribution"][name]
        assert [row["sleeve"] for row in rows] == ["A", "B", "CASH"]
        for row, execution, weight in zip(rows[:2], (aa, ba), (.35, .45), strict=True):
            assert row["cash_contribution"]["value"] == pytest.approx(weight * (execution["metrics"]["final_cash"] - 1))
            assert row["market_pnl"]["value"] == pytest.approx(weight * math.fsum(t["quantity"] * (t["exit_raw_open"] - t["entry_raw_open"]) for t in execution["trades"]))
            for key in ("commission_total", "slippage_total"):
                assert row[key]["value"] == pytest.approx(weight * math.fsum(t[key] for t in execution["trades"]))
        assert rows[2]["final_cash"]["value"] == cash_weight
        assert all(rows[2][key]["value"] == 0 for key in ("cash_contribution", "market_pnl", "commission_total", "slippage_total"))
        assert math.fsum(row["cash_contribution"]["value"] for row in rows) == pytest.approx(result[name]["summary"]["total_return"]["value"])
        assert math.fsum(row["market_pnl"]["value"] - row["commission_total"]["value"] - row["slippage_total"]["value"] for row in rows) == pytest.approx(result[name]["summary"]["total_return"]["value"])
    assert result["attribution"]["portfolio"][0]["commission_total"]["value"] > 0
    av, bv = ([row["cash_close"] / row["cash_open"] - 1 for row in execution["daily"]] for execution in (a, b))
    assert any(row["trade_count"] == 0 for row in a["daily"])
    assert result["complementarity"]["correlation"]["value"] == pytest.approx(statistics.correlation(av, bv))
    expected_loss_days = [row["trading_day"] for row, avalue, bvalue in zip(a["daily"], av, bv, strict=True) if avalue < -1e-12 and bvalue < -1e-12]
    assert result["complementarity"]["joint_loss_days"] == expected_loss_days
    assert result["complementarity"]["joint_loss_ratio"]["value"] == len(expected_loss_days) / 105
    assert portfolio.analyze_intraday_portfolio(case.snapshot, case.snapshot, **options) == result
    arguments = ["research-intraday-portfolio", "--left", str(case.path), "--right", str(case.path),
                 "--left-cost-index", "1", "--left-candidate-index", "1", "--right-cost-index", "0", "--right-candidate-index", "0",
                 "--weight-a", ".35", "--weight-b", ".45"]
    assert cli.main(arguments) == 0 and json.loads(capsys.readouterr().out)["report"] == result
    console = Path(sysconfig.get_path("scripts")) / ("market-vault.exe" if os.name == "nt" else "market-vault")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"), "PYTHONIOENCODING": "cp1252:strict"}
    process = subprocess.run([str(console), "--settings", str(tmp_path / "absent.yaml"), *arguments], env=env, capture_output=True, check=False)
    assert process.returncode == 0 and not process.stderr and process.stdout.isascii()
    assert json.loads(process.stdout)["report"] == result
    assert case.path.read_bytes() == before


def test_portfolio_same_source_endpoints_all_cash_and_identity(return_uncertainty_case):
    from market_vault.research.intraday_portfolio import analyze_intraday_portfolio
    from test_intraday_experiment import _comparison_snapshot
    snapshot = return_uncertainty_case.snapshot
    original = snapshot.as_dict()["report"]["groups"][1]["results"][1]["execution"]
    identities = []
    for a, b in ((1, 0), (0, 1), (.5, .5), (0, 0)):
        result = analyze_intraday_portfolio(snapshot, snapshot, left_cost_index=1, right_cost_index=1,
            left_candidate_index=1, right_candidate_index=1, weight_a=a, weight_b=b)
        assert result["availability"]["status"] == "AVAILABLE"
        identities.append(result["portfolio_id"])
        assert [row["equity"] for row in result["path"]] == ([1.] * len(original["ledger"]) if a == b == 0 else [row["equity"] for row in original["ledger"]])
        assert [row["cash"] for row in result["path"]] == ([1.] * len(original["ledger"]) if a == b == 0 else [row["cash"] for row in original["ledger"]])
    assert len(set(identities)) == 4
    assert result["portfolio"]["summary"]["total_return"]["value"] == result["portfolio"]["summary"]["observed_max_drawdown"]["value"] == 0
    assert result["portfolio"]["risk"]["sharpe_ratio"]["unavailable_reason"] == "ZERO_VOLATILITY"
    assert all(row["cash_contribution"]["value"] == 0 for row in result["attribution"]["portfolio"])
    # An additional unused recorded Feature changes provenance, not Q11's
    # common raw prices, decision identities or evaluation folds.
    root = snapshot.as_dict()
    root["plan"]["comparison_plan"]["feature_fields"] = ["return_2", "sma_5"]
    root["report"]["context"]["feature_fields"] = ["return_2", "sma_5"]
    other = _comparison_snapshot(root)
    feature_pair = analyze_intraday_portfolio(snapshot, other, left_cost_index=1, right_cost_index=1,
        left_candidate_index=1, right_candidate_index=1)
    assert feature_pair["availability"]["status"] == "AVAILABLE" and feature_pair["basis"]["matches"]
    assert feature_pair["left"]["feature_fields"] != feature_pair["right"]["feature_fields"]


@pytest.mark.parametrize("changes", [{"weight_a": True}, {"weight_b": float("nan")}, {"weight_a": float("inf")},
    {"weight_a": -0.01}, {"weight_a": .6}, {"weight_b": "0.5"}, {"weight_a": 10 ** 1000},
    {"left_cost_index": True}, {"right_candidate_index": -1}, {"right_cost_index": 1.0}])
def test_portfolio_invalid_parameters_precede_decode_and_cli_file_load(return_uncertainty_case, monkeypatch, capsys, changes):
    from market_vault.research import intraday_portfolio as portfolio
    from market_vault.research.strategy_experiment import StrategyExperiment
    from market_vault import intraday_portfolio_cli as console
    monkeypatch.setattr(StrategyExperiment, "as_dict", lambda self: pytest.fail("invalid portfolio parameters decoded an experiment"))
    monkeypatch.setattr(console, "load_strategy_experiment", lambda *a: pytest.fail("invalid portfolio parameters loaded a file"))
    with pytest.raises(ValueError):
        portfolio.analyze_intraday_portfolio(return_uncertainty_case.snapshot, return_uncertainty_case.snapshot, **changes)
    arguments = {"left": "absent-left.json", "right": "absent-right.json", "left_cost_index": 0, "left_candidate_index": 0,
                 "right_cost_index": 0, "right_candidate_index": 0, "weight_a": .5, "weight_b": .5, **changes}
    assert console.research_intraday_portfolio_main(SimpleNamespace(**arguments)) == 1
    assert '"status": "FAILED"' in capsys.readouterr().err


@pytest.mark.parametrize("side,account,case", [("LEFT", "STRATEGY", "cash"), ("LEFT", "BENCHMARK", "cash"),
    ("RIGHT", "STRATEGY", "cash"), ("RIGHT", "BENCHMARK", "cash"), ("RIGHT", "STRATEGY", "ledger"),
    ("RIGHT", "BENCHMARK", "overflow"), ("RIGHT", "STRATEGY", "raw_basis"), ("RIGHT", "BENCHMARK", "raw_basis"),
    ("RIGHT", "STRATEGY", "decision_basis"), ("RIGHT", "STRATEGY", "fold_basis")])
def test_portfolio_complete_basis_and_each_source_account_block_every_joint_result(return_uncertainty_case, side, account, case):
    from datetime import datetime
    from market_vault.research.intraday_portfolio import analyze_intraday_portfolio
    from market_vault.research.strategy_experiment import StrategyExperiment
    from test_intraday_experiment import signed, _comparison_snapshot
    original = return_uncertainty_case.snapshot
    root = original.as_dict()
    group = root["report"]["groups"][1]
    record = group["results"][1] if account == "STRATEGY" else group["benchmark"]
    execution = record["execution"]
    if case == "cash":
        execution["trades"][0]["commission_total"] += .01
    elif case == "ledger":
        execution["ledger"][0]["cash"] += .01
    elif case == "overflow":
        execution["trades"][0]["quantity"] = execution["trades"][0]["exit_raw_open"] = 1e308
    elif case == "raw_basis":
        execution["ledger"][-2]["row_version_id"] = "f" * 64
    elif case == "decision_basis":
        for saved_group in root["report"]["groups"]:
            candidate = saved_group["results"][1]
            for row in (candidate["predictions"][0], candidate["execution"]["decisions"][0]):
                row["slot"] -= 1
                row["decision_time"] = (datetime.fromisoformat(row["decision_time"]) - timedelta(minutes=30)).isoformat()
    else:
        # Rule-only samples have no supervised training keys. Move a real
        # validation key between folds while preserving the complete key order.
        folds = root["report"]["context"]["folds"]
        folds[1]["validation_keys"].insert(0, folds[0]["validation_keys"].pop())
    changed = _comparison_snapshot(root) if case == "fold_basis" else StrategyExperiment(signed(root))
    result = analyze_intraday_portfolio(changed if side == "LEFT" else original, changed if side == "RIGHT" else original,
        left_cost_index=1, right_cost_index=1, left_candidate_index=1, right_candidate_index=1)
    assert result["availability"]["status"] == "UNAVAILABLE"
    assert result["path"] == result["daily_returns"] == []
    assert result["complementarity"]["correlation"]["value"] is result["complementarity"]["joint_loss_count"]["value"] is None
    assert all(row["minutes"]["value"] is row["ratio"]["value"] is None for row in result["complementarity"]["holding_overlap"].values())
    for name in ("portfolio", "benchmark"):
        assert result[name]["summary"]["final_cash"]["value"] is result[name]["summary"]["total_return"]["value"] is None
        for row in result["attribution"][name]:
            assert row["weight"]["value"] is not None
            assert all(row[key]["value"] is None for key in ("final_cash", "cash_contribution", "market_pnl", "commission_total", "slippage_total"))
    assert result["left"]["sample"]["sample_count"] == result["right"]["sample"]["sample_count"] == 105
    if case.endswith("basis"):
        expected = {"raw_basis": "raw_prices", "decision_basis": "decision_identity", "fold_basis": "development_folds"}[case]
        assert expected in result["basis"]["failed_checks"]
        assert result["availability"]["unavailable_reason"] == "BASIS_MISMATCH"
        assert result["sample"]["evaluated_days"] == [] and result["sample"]["sample_count"] is result["sample"]["total_session_minutes"] is None
    else:
        assert result["basis"]["matches"] and result["availability"]["unavailable_reason"] == "SOURCE_ACCOUNT_UNAVAILABLE"
        failure = next(row for row in result["availability"]["account_checks"] if row["side"] == side and row["account"] == account)
        expected = {"cash": "RECORDED_CASH_RECONCILIATION_FAILED", "ledger": "RECORDED_LEDGER_RECONCILIATION_FAILED", "overflow": "NUMERIC_OVERFLOW"}[case]
        assert failure["unavailable_reason"] == expected


def test_portfolio_historical_accounts_remain_unavailable_even_at_zero_weights(return_uncertainty_case):
    from market_vault.research.intraday_portfolio import analyze_intraday_portfolio
    from market_vault.research.strategy_experiment import StrategyExperiment
    from test_intraday_experiment import signed
    root = return_uncertainty_case.snapshot.as_dict()
    root["algorithm_versions"]["execution"], root["algorithm_versions"]["cost"] = "historical-execution", "historical-cost"
    for group in root["report"]["groups"]:
        for record in (*group["results"], group["benchmark"]):
            record["execution"]["version"] = "historical-execution"
            record["execution"]["cost_version"] = "historical-cost"
    snapshot = StrategyExperiment(signed(root))
    result = analyze_intraday_portfolio(snapshot, snapshot, weight_a=0, weight_b=0)
    assert result["basis"]["matches"] and result["availability"]["status"] == "UNAVAILABLE"
    assert all(row["unavailable_reason"] == "UNSUPPORTED_EXECUTION_OR_COST_VERSION" for row in result["availability"]["account_checks"])
    assert result["path"] == [] and result["attribution"]["portfolio"][2]["weight"]["value"] == 1


def test_portfolio_ordinary_q10_children_keep_distinct_strategies_and_policies(execution_scenarios_case):
    from market_vault.research.intraday_portfolio import analyze_intraday_portfolio
    from market_vault.research.intraday_execution_scenarios import extract_intraday_execution_scenario
    collection = execution_scenarios_case[2]
    root = collection.as_dict()
    children = [extract_intraday_execution_scenario(collection, expected_experiment_id=root["experiment_id"], scenario_index=index,
                expected_child_experiment_id=row["experiment"]["experiment_id"]) for index, row in enumerate(root["report"]["scenarios"])]
    before = [child.content for child in children]
    result = analyze_intraday_portfolio(*children, left_candidate_index=1, right_candidate_index=2)
    assert result["availability"]["status"] == "AVAILABLE" and result["basis"]["matches"]
    assert result["left"]["strategy"]["kind"] != result["right"]["strategy"]["kind"]
    assert result["left"]["execution_policy"] != result["right"]["execution_policy"]
    assert result["left"]["benchmark_execution_policy"] != result["right"]["benchmark_execution_policy"]
    assert result["left"]["benchmark_execution_id"] != result["right"]["benchmark_execution_id"]
    assert [child.content for child in children] == before
    with pytest.raises(ValueError, match="ordinary saved Q7 DEV"):
        analyze_intraday_portfolio(collection, children[0])


def test_portfolio_low_variance_correlation_does_not_block_cash_paths_or_different_window_refusal(research_case, return_uncertainty_case):
    from market_vault.research.intraday_experiment import create_intraday_experiment
    from market_vault.research.intraday_portfolio import analyze_intraday_portfolio
    _, plan, report = research_case
    short = create_intraday_experiment(plan=plan, report=report)
    result = analyze_intraday_portfolio(short, short)
    assert result["sample"]["sample_count"] == 10 and result["availability"]["status"] == "AVAILABLE"
    assert result["complementarity"]["correlation"]["unavailable_reason"] == "ZERO_VOLATILITY"
    assert result["complementarity"]["holding_overlap"]["neither"]["ratio"]["value"] == 1
    assert all(point["equity"] == point["cash"] == 1 for point in result["path"])
    assert result["portfolio"]["summary"]["total_return"]["value"] == 0
    blocked = analyze_intraday_portfolio(short, return_uncertainty_case.snapshot)
    assert blocked["left"]["sample"]["sample_count"] == 10 and blocked["right"]["sample"]["sample_count"] == 105
    assert "evaluated_days" in blocked["basis"]["failed_checks"] and blocked["availability"]["unavailable_reason"] == "BASIS_MISMATCH"
    assert blocked["path"] == blocked["daily_returns"] == blocked["sample"]["evaluated_days"] == []


def test_portfolio_rebalance_two_day_cash_transfers_benchmark_and_full_path_oracle():
    from market_vault.research import intraday_portfolio as fixed
    from market_vault.research import intraday_portfolio_rebalance as rebalanced
    prices = [[(1, 1), (1, 4), (1, 1), (2, 2)], [(2, 2), (2, 2), (2, 2), (1, 1)]]
    a = portfolio_execution(prices, [{0: "LONG"}, {0: "LONG"}])
    b = portfolio_execution(prices, [{}, {}])
    allocation = fixed._allocation(.5, .5)
    _, original = fixed._combined_path(a, b, a, b, allocation)
    path, daily, allocations, transfers = rebalanced._reallocated_account(a, b, allocation)
    assert original[-1]["cash_close"] == 1
    assert [row["cash_open"] for row in daily] == [1, 1.5]
    assert [row["cash_close"] for row in daily] == [1.5, 1.125]
    assert [row["return"] for row in daily] == [.5, -.25]
    assert [row["net_transfer"] for row in transfers] == [-.25, .25, 0]
    assert [row["previous_cash_close"] for row in transfers] == [1, .5, 0]
    assert [row["target_cash"] for row in transfers] == [.75, .75, 0]
    assert len(allocations) == 6 and len(transfers) == 3
    assert [row["sequence"] for row in path] == list(range(16))
    high, following = path[3:5]
    assert high["timestamp"] == following["timestamp"] and (high["phase"], following["phase"]) == ("CLOSE", "OPEN")
    assert (high["equity"], following["equity"], following["drawdown"]) == (2.5, 1, .6)
    summary = fixed._account_summary(daily, path)
    assert summary["summary"]["observed_max_drawdown"]["value"] == .6
    assert summary["risk"]["mean_daily_return"]["value"] == .125
    assert summary["risk"]["annualized_volatility"]["value"] == pytest.approx(.75 / math.sqrt(2) * math.sqrt(252))
    assert summary["risk"]["sharpe_ratio"]["value"] == pytest.approx(math.sqrt(504) / 6)
    attributed = rebalanced._attribution(allocations, transfers, allocation, 1.125)
    assert [row["cash_contribution"]["value"] for row in attributed] == [.125, 0, 0]
    assert [row["final_cash"]["value"] for row in attributed] == [.375, .75, 0]
    # The benchmark has a different first-day return, so it must never reuse
    # the portfolio's 1.5 opening cash for the second day.
    benchmark = portfolio_execution(prices, [{}, {0: "LONG"}])
    _, benchmark_days, _, benchmark_transfers = rebalanced._reallocated_account(benchmark, b, allocation)
    assert [row["cash_open"] for row in benchmark_days] == [1, 1]
    assert benchmark_days[-1]["cash_close"] == .75
    assert [row["net_transfer"] for row in benchmark_transfers] == [0, 0, 0]
    allocation = fixed._allocation(.25, .25)
    _, daily, allocations, transfers = rebalanced._reallocated_account(a, b, allocation)
    assert daily[-1]["cash_close"] == 35 / 32
    assert [row["net_transfer"] for row in transfers] == [-.1875, .0625, .125]
    cash = rebalanced._attribution(allocations, transfers, allocation, 35 / 32)[2]
    assert (cash["initial_allocation"]["value"], cash["final_cash"]["value"], cash["cash_contribution"]["value"], cash["net_transfers"]["value"]) == (.5, .625, 0, .125)
    assert all(row["source_cash_open"] is row["scale_factor"] is None for row in allocations if row["sleeve"] == "CASH")


def test_portfolio_rebalance_proportional_fees_are_scaled_by_each_day_and_never_deducted_twice():
    from market_vault.backtest.intraday import IntradayExecutionPolicy
    from market_vault.research.intraday_portfolio import _allocation
    from market_vault.research.intraday_portfolio_rebalance import _reallocated_account, _attribution
    prices = [[(100, 100)] * 4] * 2
    policy = IntradayExecutionPolicy(commission_bps=100, slippage_bps=100, entry_delay_minutes=0,
                                     stop_new_minutes=30, flatten_minutes=5, max_hold_bars=20)
    a = portfolio_execution(prices, [{0: "LONG"}, {0: "LONG"}], policy=policy)
    b = portfolio_execution(prices, [{}, {}], policy=policy)
    allocation = _allocation(.5, .5)
    _, daily, allocations, transfers = _reallocated_account(a, b, allocation)
    source_factor, combined_factor = 9801 / 10201, 10001 / 10201
    assert a["daily"][1]["cash_open"] == pytest.approx(source_factor)
    assert daily[-1]["cash_close"] == pytest.approx(combined_factor ** 2)
    second_a = allocations[3]
    assert second_a["scale_factor"] == pytest.approx(.5 * combined_factor / source_factor)
    attribution = _attribution(allocations, transfers, allocation, daily[-1]["cash_close"])
    fee = 2020200 / 104060401
    assert attribution[0]["market_pnl"]["value"] == 0
    assert attribution[0]["commission_total"]["value"] == pytest.approx(fee)
    assert attribution[0]["slippage_total"]["value"] == pytest.approx(fee)
    assert daily[-1]["cash_close"] == pytest.approx(1 - 2 * fee)
    assert attribution[1]["cash_contribution"]["value"] == 0
    assert attribution[1]["net_transfers"]["value"] < 0


def test_portfolio_rebalance_real_saved_daily_cash_path_and_installed_console(return_uncertainty_case, monkeypatch, capsys, tmp_path):
    import json
    import os
    from pathlib import Path
    import subprocess
    import sysconfig
    from market_vault import cli
    from market_vault.backtest import intraday as execution
    from market_vault.research import intraday_portfolio as fixed
    from market_vault.research import intraday_portfolio_rebalance as rebalanced
    from market_vault.research import intraday_return_uncertainty as uncertainty
    from market_vault.research.strategy_experiment import StrategyExperiment
    case = return_uncertainty_case
    root, before = case.snapshot.as_dict(), case.path.read_bytes()
    other = StrategyExperiment(case.snapshot.content)
    groups = root["report"]["groups"]
    options = dict(left_cost_index=1, left_candidate_index=1, right_cost_index=0, right_candidate_index=0, weight_a=.3, weight_b=.4)
    calls = {"decode": 0, "basis": 0, "prepare": 0, "accounts": 0}
    def counted(name, function):
        def run(*args, **kwargs):
            calls[name] += 1
            return function(*args, **kwargs)
        return run
    with monkeypatch.context() as patch:
        patch.setattr(StrategyExperiment, "as_dict", counted("decode", StrategyExperiment.as_dict))
        patch.setattr(fixed, "_basis", counted("basis", fixed._basis))
        patch.setattr(rebalanced, "_prepare_portfolio", counted("prepare", rebalanced._prepare_portfolio))
        patch.setattr(uncertainty, "_available", counted("accounts", uncertainty._available))
        for name in ("load_intraday_dataset", "_fit", "run_intraday_execution"):
            patch.setattr(research, name, lambda *a, **kw: pytest.fail("reallocation accessed source, fit or execution"))
        patch.setattr(execution, "run_intraday_execution", lambda *a, **kw: pytest.fail("reallocation executed trades"))
        patch.setattr(Path, "read_bytes", lambda *a, **kw: pytest.fail("reallocation read files"))
        patch.setattr(cli, "load_settings", lambda *a, **kw: pytest.fail("reallocation loaded settings"))
        result = rebalanced.analyze_intraday_portfolio_rebalance(case.snapshot, other, **options)
        assert calls == {"decode": 2, "basis": 1, "prepare": 1, "accounts": 4}
        calls.update({key: 0 for key in calls})
        same = rebalanced.analyze_intraday_portfolio_rebalance(case.snapshot, case.snapshot)
        assert calls == {"decode": 1, "basis": 1, "prepare": 1, "accounts": 2}
        assert len(same["availability"]["account_checks"]) == 4
    assert result["availability"]["status"] == "AVAILABLE" and result["sample"]["sample_count"] == 105
    assert result["allocation"] == {"method": "DAILY_TARGET_CASH_REALLOCATION", "initial_cash": 1.0,
        "weight_a": .3, "weight_b": .4, "cash_weight": 1 - math.fsum((.3, .4)), "cash_interest_rate": 0.0, "cash_transfer_cost": 0.0}
    assert result["version"] == "market-vault-intraday-portfolio-rebalance-v1"
    assert result["evidence"] == "RECORDED_LEDGER_DERIVATION" and "portfolio_id" not in result
    assert "execution_id" not in result["portfolio"] and "trades" not in result["portfolio"]
    for name, prefix in (("portfolio", ""), ("benchmark", "benchmark_")):
        a = groups[1]["results"][1]["execution"] if name == "portfolio" else groups[1]["benchmark"]["execution"]
        b = groups[0]["results"][0]["execution"] if name == "portfolio" else groups[0]["benchmark"]["execution"]
        allocations, transfers = result["daily_allocations"][name], result["cash_transfers"][name]
        assert len(allocations) == 315 and len(transfers) == 312
        wealth, expected_open, previous = 1.0, {}, None
        for index, (da, db, day) in enumerate(zip(a["daily"], b["daily"], result["daily_returns"], strict=True)):
            expected_open[da["trading_day"]] = wealth
            ret = .3 * (da["cash_close"] / da["cash_open"] - 1) + .4 * (db["cash_close"] / db["cash_open"] - 1)
            assert (day[prefix + "cash_open"], day[prefix + "cash_close"], day[prefix + "return"]) == pytest.approx((wealth, wealth * (1 + ret), ret))
            rows = allocations[index * 3:index * 3 + 3]
            assert [row["sleeve"] for row in rows] == ["A", "B", "CASH"]
            assert [row["allocated_cash"] for row in rows] == pytest.approx([wealth * weight for weight in (.3, .4, .3)])
            assert sum(row["cash_close"] for row in rows) == pytest.approx(wealth * (1 + ret))
            if previous is not None:
                movements = transfers[(index - 1) * 3:index * 3]
                assert sum(row["net_transfer"] for row in movements) == pytest.approx(0, abs=1e-12)
                for moved, old, current in zip(movements, previous, rows, strict=True):
                    assert (moved["previous_cash_close"], moved["target_cash"], moved["net_transfer"]) == pytest.approx((old["cash_close"], current["allocated_cash"], current["allocated_cash"] - old["cash_close"]))
            previous, wealth = rows, wealth * (1 + ret)
        peak = 1.0
        daily_a, daily_b = ({row["trading_day"]: row["cash_open"] for row in account["daily"]} for account in (a, b))
        for point, pa, pb in zip(result["path"], a["ledger"], b["ledger"], strict=True):
            day = pa["trading_day"]
            assert (point["sequence"], point["timestamp"], point["phase"]) == (pa["sequence"], pa["timestamp"], pa["phase"])
            amounts = {key: expected_open[day] * (.3 + .3 * pa[key] / daily_a[day] + .4 * pb[key] / daily_b[day]) for key in ("cash", "equity")}
            peak = max(peak, amounts["equity"])
            assert (point[prefix + "cash"], point[prefix + "equity"], point[prefix + "drawdown"]) == pytest.approx((amounts["cash"], amounts["equity"], 1 - amounts["equity"] / peak))
        assert result[name]["summary"]["final_cash"]["value"] == pytest.approx(wealth)
        for row in result["attribution"][name]:
            assert row["final_cash"]["value"] == pytest.approx(row["initial_allocation"]["value"] + row["cash_contribution"]["value"] + row["net_transfers"]["value"])
    arguments = ["research-intraday-portfolio-rebalance", "--left", str(case.path), "--right", str(case.path),
        "--left-cost-index", "1", "--left-candidate-index", "1", "--right-cost-index", "0", "--right-candidate-index", "0", "--weight-a", ".3", "--weight-b", ".4"]
    assert cli.main(arguments) == 0 and json.loads(capsys.readouterr().out)["report"] == result
    console = Path(sysconfig.get_path("scripts")) / ("market-vault.exe" if os.name == "nt" else "market-vault")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"), "PYTHONIOENCODING": "cp1252:strict"}
    process = subprocess.run([str(console), "--settings", str(tmp_path / "absent.yaml"), *arguments], env=env, capture_output=True, check=False)
    assert process.returncode == 0 and not process.stderr and process.stdout.isascii()
    assert json.loads(process.stdout)["report"] == result and case.path.read_bytes() == before


@pytest.mark.parametrize("changes", [{"weight_a": True}, {"weight_b": float("nan")}, {"weight_a": .6}, {"right_candidate_index": False}])
def test_portfolio_rebalance_invalid_arguments_precede_decode_and_cli_io(return_uncertainty_case, monkeypatch, capsys, changes):
    from market_vault.research.intraday_portfolio_rebalance import analyze_intraday_portfolio_rebalance
    from market_vault.research.strategy_experiment import StrategyExperiment
    from market_vault import intraday_portfolio_rebalance_cli as console
    monkeypatch.setattr(StrategyExperiment, "as_dict", lambda self: pytest.fail("invalid arguments decoded an experiment"))
    monkeypatch.setattr(console, "load_strategy_experiment", lambda *a: pytest.fail("invalid arguments loaded a file"))
    with pytest.raises(ValueError):
        analyze_intraday_portfolio_rebalance(return_uncertainty_case.snapshot, return_uncertainty_case.snapshot, **changes)
    arguments = {"left": "absent-left.json", "right": "absent-right.json", "left_cost_index": 0, "left_candidate_index": 0,
        "right_cost_index": 0, "right_candidate_index": 0, "weight_a": .5, "weight_b": .5, **changes}
    assert console.research_intraday_portfolio_rebalance_main(SimpleNamespace(**arguments)) == 1
    assert '"status": "FAILED"' in capsys.readouterr().err


@pytest.mark.parametrize("side,account", [("LEFT", "STRATEGY"), ("LEFT", "BENCHMARK"), ("RIGHT", "STRATEGY"), ("RIGHT", "BENCHMARK")])
def test_portfolio_rebalance_each_zero_weight_bad_account_blocks_both_derived_paths(return_uncertainty_case, side, account):
    from market_vault.research.intraday_portfolio_rebalance import analyze_intraday_portfolio_rebalance
    from market_vault.research.strategy_experiment import StrategyExperiment
    from test_intraday_experiment import signed
    original = return_uncertainty_case.snapshot
    root = original.as_dict()
    group = root["report"]["groups"][1]
    record = group["results"][1] if account == "STRATEGY" else group["benchmark"]
    record["execution"]["trades"][0]["commission_total"] += .01
    changed = StrategyExperiment(signed(root))
    result = analyze_intraday_portfolio_rebalance(changed if side == "LEFT" else original, changed if side == "RIGHT" else original,
        left_cost_index=1, left_candidate_index=1, right_cost_index=1, right_candidate_index=1, weight_a=0, weight_b=0)
    assert result["basis"]["matches"] and result["availability"]["unavailable_reason"] == "SOURCE_ACCOUNT_UNAVAILABLE"
    failed = [row for row in result["availability"]["account_checks"] if row["status"] == "UNAVAILABLE"]
    assert [(row["side"], row["account"]) for row in failed] == [(side, account)]
    assert result["path"] == result["daily_returns"] == []
    assert result["daily_allocations"] == result["cash_transfers"] == {"portfolio": [], "benchmark": []}
    for name in ("portfolio", "benchmark"):
        assert result[name]["summary"]["final_cash"]["value"] is None
        for row, initial in zip(result["attribution"][name], (0, 0, 1), strict=True):
            assert row["weight"]["value"] == row["initial_allocation"]["value"] == initial
            assert row["initial_allocation"]["unavailable_reason"] is None
            assert all(row[key]["value"] is None and row[key]["unavailable_reason"] == "SOURCE_ACCOUNT_UNAVAILABLE"
                       for key in ("final_cash", "cash_contribution", "market_pnl", "commission_total", "slippage_total", "net_transfers"))


def test_portfolio_rebalance_endpoints_same_source_and_all_cash(return_uncertainty_case):
    from market_vault.research.intraday_portfolio_rebalance import analyze_intraday_portfolio_rebalance
    snapshot = return_uncertainty_case.snapshot
    original = snapshot.as_dict()["report"]["groups"][1]["results"][1]["execution"]
    ids = []
    for a, b in ((1, 0), (0, 1), (.5, .5), (0, 0)):
        result = analyze_intraday_portfolio_rebalance(snapshot, snapshot, left_cost_index=1, right_cost_index=1,
            left_candidate_index=1, right_candidate_index=1, weight_a=a, weight_b=b)
        assert result["availability"]["status"] == "AVAILABLE"
        ids.append(result["portfolio_rebalance_id"])
        for key in ("cash", "equity"):
            expected = [1.] * len(original["ledger"]) if a == b == 0 else [row[key] for row in original["ledger"]]
            assert [point[key] for point in result["path"]] == pytest.approx(expected)
        assert all(row["net_transfer"] == pytest.approx(0, abs=1e-12) for row in result["cash_transfers"]["portfolio"])
    assert len(set(ids)) == 4
    assert result["portfolio"]["summary"]["total_return"]["value"] == result["portfolio"]["summary"]["observed_max_drawdown"]["value"] == 0
    assert result["portfolio"]["risk"]["sharpe_ratio"]["unavailable_reason"] == "ZERO_VOLATILITY"


def test_portfolio_rebalance_basis_and_late_numeric_failure_remain_atomic(return_uncertainty_case, monkeypatch):
    from market_vault.research import intraday_portfolio_rebalance as rebalanced
    from market_vault.research.strategy_experiment import StrategyExperiment
    from test_intraday_experiment import signed
    snapshot = return_uncertainty_case.snapshot
    root = snapshot.as_dict()
    root["report"]["groups"][0]["results"][0]["execution"]["ledger"][-2]["row_version_id"] = "f" * 64
    changed = StrategyExperiment(signed(root))
    report = rebalanced.analyze_intraday_portfolio_rebalance(snapshot, changed)
    assert report["availability"]["unavailable_reason"] == "BASIS_MISMATCH"
    assert "raw_prices" in report["basis"]["failed_checks"] and report["sample"]["sample_count"] is None
    assert report["path"] == report["daily_returns"] == report["sample"]["evaluated_days"] == []
    original, calls = rebalanced._reallocated_account, []
    def benchmark_overflow(*args):
        calls.append(1)
        if len(calls) == 2:
            raise OverflowError("benchmark arithmetic overflow after the strategy path completed")
        return original(*args)
    monkeypatch.setattr(rebalanced, "_reallocated_account", benchmark_overflow)
    report = rebalanced.analyze_intraday_portfolio_rebalance(snapshot, snapshot)
    assert len(calls) == 2 and all(row["status"] == "AVAILABLE" for row in report["availability"]["account_checks"])
    assert report["availability"]["unavailable_reason"] == "NUMERIC_OVERFLOW"
    assert report["path"] == report["daily_returns"] == []
    assert report["daily_allocations"] == report["cash_transfers"] == {"portfolio": [], "benchmark": []}
    assert report["portfolio"]["summary"]["final_cash"]["value"] is report["benchmark"]["summary"]["final_cash"]["value"] is None


def test_portfolio_rebalance_ordinary_children_and_saved_selection_boundaries(execution_scenarios_case, return_uncertainty_case):
    from market_vault.research.intraday_execution_scenarios import extract_intraday_execution_scenario
    from market_vault.research.intraday_final_test import freeze_intraday_candidate
    from market_vault.research.intraday_portfolio_rebalance import analyze_intraday_portfolio_rebalance
    collection = execution_scenarios_case[2]
    root = collection.as_dict()
    children = [extract_intraday_execution_scenario(collection, expected_experiment_id=root["experiment_id"], scenario_index=index,
        expected_child_experiment_id=row["experiment"]["experiment_id"]) for index, row in enumerate(root["report"]["scenarios"])]
    report = analyze_intraday_portfolio_rebalance(*children, left_candidate_index=1, right_candidate_index=2)
    assert report["availability"]["status"] == "AVAILABLE" and report["sample"]["sample_count"] == 10
    assert report["left"]["strategy"]["kind"] != report["right"]["strategy"]["kind"]
    assert report["left"]["execution_policy"] != report["right"]["execution_policy"]
    with pytest.raises(ValueError, match="ordinary saved Q7 DEV"):
        analyze_intraday_portfolio_rebalance(collection, children[0])
    case = return_uncertainty_case
    root = case.snapshot.as_dict()
    selection = freeze_intraday_candidate(case.path, expected_experiment_id=root["experiment_id"], cost_index=0, candidate_index=0,
        expected_candidate_id=root["report"]["groups"][0]["results"][0]["candidate_id"])
    with pytest.raises(ValueError, match="ordinary saved Q7 DEV"):
        analyze_intraday_portfolio_rebalance(selection, case.snapshot)
    with pytest.raises(ValueError, match="outside the saved experiment"):
        analyze_intraday_portfolio_rebalance(case.snapshot, case.snapshot, right_cost_index=2)


def test_sequential_selection_strict_prefix_negative_scores_exact_ties_and_future_nonintervention():
    from fractions import Fraction
    from market_vault.research.intraday_sequential_selection import _fold_selections
    folds = [{"fold_index": index, "fold_id": f"fold-{index}", "training_boundary": f"open-{index}",
              "validation_days": [f"day-{2 * index}", f"day-{2 * index + 1}"]} for index in range(4)]
    candidates = [{"candidate_index": index, "candidate_id": f"candidate-{index}", "fold_models": []} for index in range(2)]
    a = (-.25, -.25, 1., 1., -1., -1., 8., 8.)
    b = (-.125, -.125, -.25, -.25, .5, .5, 0., 0.)
    rows = _fold_selections({"folds": folds}, candidates, [a, b], 2)
    assert [row["chosen_candidate_index"] for row in rows] == [None, 1, 0, 1]
    assert rows[0]["status"] == "WARMUP" and rows[0]["scores"][0]["mean_excess"] is None
    assert rows[1]["scores"][1]["mean_excess"] < 0  # No silent cash alternative.
    for index, row in enumerate(rows):
        assert row["history_days"] == [day for fold in folds[:index] for day in fold["validation_days"]]
        assert row["history_fold_ids"] == [fold["fold_id"] for fold in folds[:index]]
        if index:
            assert [score["mean_excess"] for score in row["scores"]] == pytest.approx([
                float(sum(map(Fraction, values[:2 * index])) / (2 * index)) for values in (a, b)])
    changed = [a[:4] + (10.,) * 4, b[:4] + (-10.,) * 4]
    later = _fold_selections({"folds": folds}, candidates, changed, 2)
    assert later[:3] == rows[:3] and later[3]["chosen_candidate_index"] == 0
    tied = _fold_selections({"folds": folds}, candidates, [a, a], 2)
    assert all(row["chosen_candidate_index"] == 0 for row in tied[1:])
    tiny = _fold_selections({"folds": folds}, candidates, [(0.,) * 8, (1e-14,) * 8], 2)
    assert all(row["chosen_candidate_index"] == 1 for row in tiny[1:])
    # One completed 2-day fold is enough for an explicit 2-day requirement;
    # no unrequested minimum count of historical folds is imposed.
    assert rows[1]["history_day_count"] == 2 and rows[1]["status"] == "SELECTED"


def test_sequential_selection_rebased_switching_account_keeps_every_ordered_mark():
    from market_vault.research import intraday_sequential_selection as sequential
    prices = [[(1, 1), (1, 1), (1, 1), (2, 2)],
              [(2, 2), (2, 8), (2, 2), (1, 1)],
              [(1, 1), (1, 1), (1, 1), (2, 2)]]
    a = portfolio_execution(prices, [{0: "LONG"}, {0: "LONG"}, {0: "LONG"}])
    b = portfolio_execution(prices, [{}, {}, {0: "LONG"}])
    accounts = {index: sequential._indexed_account({"execution": execution}) for index, execution in enumerate((a, b))}
    selections = [{"fold_index": index, "fold_id": f"fold-{index}", "validation_days": [a["daily"][index]["trading_day"]],
                   "chosen_candidate_index": index - 1} for index in (1, 2)]
    path, daily = sequential._scaled_account(accounts, selections)
    assert [row["cash_close"] for row in daily] == [.5, 1.]
    assert [row["return"] for row in daily] == [-.5, 1.]
    assert daily[0]["source_cash_open"] == 2 and daily[0]["cash_open"] == 1
    assert daily[1]["source_cash_open"] == 1 and daily[1]["cash_open"] == .5
    assert [point["sequence"] for point in path] == list(range(16))
    assert [point["source_sequence"] for point in path] == list(range(8, 24))
    high, next_open = path[3:5]
    assert high["timestamp"] == next_open["timestamp"] and (high["phase"], next_open["phase"]) == ("CLOSE", "OPEN")
    assert high["equity"] == 4 and next_open["equity"] == 1
    summary = sequential._account_summary(daily, path)
    assert summary["summary"]["observed_max_drawdown"]["value"] == .875
    assert summary["summary"]["total_return"]["value"] == 0
    assert summary["risk"]["mean_daily_return"]["value"] == .25
    assert summary["risk"]["annualized_volatility"]["value"] == pytest.approx(math.sqrt(1.125 * 252))
    reference_path, reference_daily = sequential._scaled_account(accounts, selections, fixed_index=1)
    assert sequential._account_summary(reference_daily, reference_path)["summary"]["final_cash"]["value"] == 2


def test_sequential_selection_real_complete_family_scores_same_sample_accounts_and_console(return_uncertainty_case, monkeypatch, capsys, tmp_path):
    import json
    import os
    import statistics
    import subprocess
    import sysconfig
    from pathlib import Path
    from market_vault import cli
    from market_vault.research import intraday_return_uncertainty as uncertainty
    from market_vault.research import intraday_sequential_selection as sequential
    from market_vault.research.intraday_data import digest
    from market_vault.research.strategy_experiment import StrategyExperiment
    case, calls = return_uncertainty_case, {"decode": 0, "accounts": 0}
    root = case.snapshot.as_dict()
    context, group = root["report"]["context"], root["report"]["groups"][1]
    decoded, checked = StrategyExperiment.as_dict, uncertainty._available
    def decode(self):
        calls["decode"] += 1
        return decoded(self)
    def account(*args, **kwargs):
        calls["accounts"] += 1
        return checked(*args, **kwargs)
    monkeypatch.setattr(StrategyExperiment, "as_dict", decode)
    monkeypatch.setattr(uncertainty, "_available", account)
    for name in ("load_intraday_dataset", "_fit", "run_intraday_execution"):
        monkeypatch.setattr(research, name, lambda *a, **kw: pytest.fail("selection accessed source, fit or execution"))
    monkeypatch.setattr(cli, "load_settings", lambda *a, **kw: pytest.fail("selection accessed settings"))
    before = case.path.read_bytes()
    result = sequential.analyze_intraday_sequential_selection(case.snapshot, cost_index=1)
    assert calls == {"decode": 1, "accounts": 3}
    assert result["availability"]["status"] == "AVAILABLE" and result["causality"]["status"] == "AVAILABLE"
    assert result["basis"] == {"matches": True, "failed_checks": []}
    assert result["family_size"] == 2 and result["family_scope"] == "SAVED_COST_GROUP_ONLY"
    assert result["historical_search_coverage"] == result["family_precommitment"] == "UNKNOWN"
    assert result["source_sample"]["sample_count"] == 105 and result["sample"]["sample_count"] == 85
    assert result["sample"]["evaluated_days"] == context["evaluated_days"][20:]
    assert result["sample"]["warmup_days"] == context["evaluated_days"][:20]
    assert result["sample"]["warmup_fold_count"] == 4 and result["selection_summary"]["selection_count"] == 17
    executions = [row["execution"] for row in group["results"]]
    values = [[day["cash_close"] / day["cash_open"] - 1 for day in execution["daily"]] for execution in executions]
    benchmark = group["benchmark"]["execution"]
    benchmark_values = [day["cash_close"] / day["cash_open"] - 1 for day in benchmark["daily"]]
    for index, fold in enumerate(result["folds"]):
        count = 5 * index
        assert fold["history_days"] == context["evaluated_days"][:count]
        assert fold["history_fold_ids"] == [row["fold_id"] for row in context["folds"][:index]]
        if count:
            expected = [statistics.fmean(a - b for a, b in zip(series[:count], benchmark_values[:count], strict=True)) for series in values]
            assert [score["mean_excess"] for score in fold["scores"]] == pytest.approx(expected)
        if index < 4:
            assert fold["status"] == "WARMUP" and fold["chosen_candidate_id"] is None
            assert fold["outcome"]["compound_return"]["value"] is None
        else:
            assert fold["chosen_candidate_index"] == max(range(2), key=lambda j: expected[j])
            actual_days = [row for row in result["daily_returns"] if row["fold_id"] == fold["fold_id"]]
            assert fold["outcome"]["compound_return"]["value"] == pytest.approx(math.prod(1 + row["return"] for row in actual_days) - 1)
            assert fold["outcome"]["mean_daily_excess"]["value"] == pytest.approx(statistics.fmean(row["paired_excess"] for row in actual_days))
    cumulative = benchmark_cumulative = 1.
    for index, row in enumerate(result["daily_returns"], 20):
        selected = row["candidate_index"]
        assert row["source_execution_id"] == executions[selected]["execution_id"]
        assert row["candidate_id"] == group["results"][selected]["candidate_id"]
        assert row["cash_open"] == pytest.approx(cumulative)
        cumulative *= 1 + values[selected][index]
        benchmark_cumulative *= 1 + benchmark_values[index]
        assert row["cash_close"] == pytest.approx(cumulative)
        assert row["benchmark_cash_close"] == pytest.approx(benchmark_cumulative)
        assert row["paired_excess"] == row["return"] - row["benchmark_return"]
    by_day = {row["trading_day"]: row for row in result["daily_returns"]}
    peak = benchmark_peak = 1.
    for point in result["path"]:
        original = executions[point["candidate_index"]]["ledger"][point["source_sequence"]]
        reference = benchmark["ledger"][point["benchmark_source_sequence"]]
        day = by_day[point["trading_day"]]
        assert (point["timestamp"], point["phase"], point["slot"]) == (original["timestamp"], original["phase"], original["slot"])
        assert point["equity"] == pytest.approx(day["cash_open"] * original["equity"] / day["source_cash_open"])
        assert point["benchmark_equity"] == pytest.approx(day["benchmark_cash_open"] * reference["equity"] / day["benchmark_source_cash_open"])
        peak, benchmark_peak = max(peak, point["equity"]), max(benchmark_peak, point["benchmark_equity"])
        assert point["drawdown"] == pytest.approx(1 - point["equity"] / peak)
        assert point["benchmark_drawdown"] == pytest.approx(1 - point["benchmark_equity"] / benchmark_peak)
    assert len(result["path"]) == 85 * 26 and len(result["static_references"]) == 2
    for reference, execution in zip(result["static_references"], executions, strict=True):
        assert reference["risk"]["return_count"]["value"] == 85
        assert reference["summary"]["final_cash"]["value"] == pytest.approx(execution["daily"][-1]["cash_close"] / execution["daily"][20]["cash_open"])
    assert sum(row["selected_day_count"] for row in result["members"]) == 85
    assert result["sequential_selection_id"] == digest({key: value for key, value in result.items() if key != "sequential_selection_id"})
    assert "execution_id" not in result["strategy"] and "trades" not in result["strategy"]
    arguments = ["research-intraday-sequential-selection", "--experiment", str(case.path), "--cost-index", "1"]
    assert cli.main(arguments) == 0 and json.loads(capsys.readouterr().out)["report"] == result
    console = Path(sysconfig.get_path("scripts")) / ("market-vault.exe" if os.name == "nt" else "market-vault")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"), "PYTHONIOENCODING": "cp1252:strict"}
    process = subprocess.run([str(console), "--settings", str(tmp_path / "missing.yaml"), *arguments], env=env, capture_output=True, check=False)
    assert process.returncode == 0 and not process.stderr and process.stdout.isascii()
    assert json.loads(process.stdout)["report"] == result and case.path.read_bytes() == before


@pytest.mark.parametrize("case", ["hidden_cash", "hidden_basis", "benchmark_overflow"])
def test_sequential_selection_invalid_unselected_member_or_benchmark_blocks_whole_path(return_uncertainty_case, case):
    from market_vault.research.intraday_sequential_selection import analyze_intraday_sequential_selection
    from market_vault.research.strategy_experiment import StrategyExperiment
    from test_intraday_experiment import signed
    snapshot = return_uncertainty_case.snapshot
    normal = analyze_intraday_sequential_selection(snapshot, cost_index=1)
    hidden = next(row["candidate_index"] for row in normal["members"] if not row["selected_day_count"])
    root = snapshot.as_dict()
    group = root["report"]["groups"][1]
    execution = group["benchmark"]["execution"] if case == "benchmark_overflow" else group["results"][hidden]["execution"]
    if case == "hidden_cash":
        execution["trades"][0]["commission_total"] += .01
    elif case == "hidden_basis":
        execution["ledger"][-2]["row_version_id"] = "f" * 64
    else:
        execution["trades"][0]["quantity"] = execution["trades"][0]["exit_raw_open"] = 1e308
    result = analyze_intraday_sequential_selection(StrategyExperiment(signed(root)), cost_index=1)
    expected = "BASIS_MISMATCH" if case == "hidden_basis" else "SOURCE_ACCOUNT_UNAVAILABLE"
    assert result["availability"]["unavailable_reason"] == expected
    assert len(result["members"]) == len(result["static_references"]) == 2
    assert result["path"] == result["daily_returns"] == result["sample"]["evaluated_days"] == []
    assert result["strategy"]["summary"]["final_cash"]["value"] is result["selection_summary"]["selection_count"] is None
    assert all(row["chosen_candidate_index"] is None and all(score["mean_excess"] is None for score in row["scores"]) for row in result["folds"])


@pytest.mark.parametrize("case", ["boundary", "validation_membership", "future_training", "future_purged"])
def test_sequential_selection_saved_clock_and_known_key_causality_gate(return_uncertainty_case, case):
    from datetime import datetime
    from market_vault.research.intraday_sequential_selection import analyze_intraday_sequential_selection
    from test_intraday_experiment import _comparison_snapshot
    root = return_uncertainty_case.snapshot.as_dict()
    folds = root["report"]["context"]["folds"]
    if case == "boundary":
        folds[0]["training_boundary"] = (datetime.fromisoformat(folds[0]["training_boundary"]) + timedelta(seconds=1)).isoformat()
    elif case == "validation_membership":
        folds[1]["validation_keys"].insert(0, folds[0]["validation_keys"].pop())
    else:
        folds[0]["training_keys" if case == "future_training" else "purged_keys"].append(folds[1]["validation_keys"][0])
    snapshot = _comparison_snapshot(root)  # Legal saved grammar, deliberately false causal evidence.
    result = analyze_intraday_sequential_selection(snapshot)
    assert result["basis"]["matches"] and all(row["status"] == "AVAILABLE" for row in result["availability"]["account_checks"])
    assert result["availability"]["unavailable_reason"] == "RECORDED_CAUSALITY_CHECK_FAILED"
    expected = {"boundary": "boundary_matches_open", "validation_membership": "validation_keys_match_days",
                "future_training": "invalid_training_keys", "future_purged": "invalid_purged_keys"}[case]
    assert any(expected in name for name in result["causality"]["failed_checks"])
    assert result["path"] == result["daily_returns"] == []


def test_sequential_selection_short_default_preserves_warmup_and_explicit_smaller_history(research_case):
    from market_vault.research.intraday_experiment import create_intraday_experiment
    from market_vault.research.intraday_sequential_selection import analyze_intraday_sequential_selection
    _, plan, report = research_case
    snapshot = create_intraday_experiment(plan=plan, report=report)
    result = analyze_intraday_sequential_selection(snapshot)
    assert result["availability"]["unavailable_reason"] == "INSUFFICIENT_HISTORY_FOR_SELECTION"
    assert result["selection_rule"]["minimum_history_days"] == 20 and result["source_sample"]["sample_count"] == 10
    assert len(result["folds"]) == 2 and all(row["status"] == "WARMUP" for row in result["folds"])
    assert all(score["mean_excess"] is not None for score in result["folds"][1]["scores"])
    assert result["path"] == result["daily_returns"] == [] and result["sample"]["sample_count"] is None
    explicit = analyze_intraday_sequential_selection(snapshot, minimum_history_days=5)
    assert explicit["availability"]["status"] == "AVAILABLE" and explicit["sample"]["sample_count"] == 5
    assert explicit["selection_summary"]["selection_count"] == 1
    assert explicit["sequential_selection_id"] != result["sequential_selection_id"]


def test_sequential_selection_ordinary_q10_child_keeps_ridge_model_bindings_and_rejects_collection(execution_scenarios_case):
    from market_vault.research.intraday_execution_scenarios import extract_intraday_execution_scenario
    from market_vault.research.intraday_sequential_selection import analyze_intraday_sequential_selection
    collection = execution_scenarios_case[2]
    root = collection.as_dict()
    child = extract_intraday_execution_scenario(collection, expected_experiment_id=root["experiment_id"], scenario_index=1,
        expected_child_experiment_id=root["report"]["scenarios"][1]["experiment"]["experiment_id"])
    child_root = child.as_dict()
    report = analyze_intraday_sequential_selection(child, minimum_history_days=5)
    assert report["availability"]["status"] == "AVAILABLE" and report["experiment_id"] == child_root["experiment_id"]
    assert report["execution_policy"] == child_root["report"]["groups"][0]["execution_policy"]
    for member, candidate in zip(report["members"], child_root["report"]["groups"][0]["results"], strict=True):
        assert member["fold_model_ids"] == [{"fold_id": row["fold_id"], "model_id": row["model"]["model_id"]} for row in candidate["fold_models"]]
    with pytest.raises(ValueError, match="ordinary saved Q7 DEV"):
        analyze_intraday_sequential_selection(collection)


@pytest.mark.parametrize("changes", [{"cost_index": True}, {"cost_index": -1}, {"minimum_history_days": True},
                                      {"minimum_history_days": 0}, {"minimum_history_days": 1.5}])
def test_sequential_selection_invalid_arguments_precede_decode_and_cli_file_io(return_uncertainty_case, monkeypatch, capsys, changes):
    import json
    from market_vault import intraday_sequential_selection_cli as console
    from market_vault.research.intraday_sequential_selection import analyze_intraday_sequential_selection
    from market_vault.research.strategy_experiment import StrategyExperiment
    monkeypatch.setattr(StrategyExperiment, "as_dict", lambda self: pytest.fail("invalid parameters decoded an experiment"))
    monkeypatch.setattr(console, "load_strategy_experiment", lambda *a: pytest.fail("invalid parameters opened a file"))
    with pytest.raises(ValueError, match="integer"):
        analyze_intraday_sequential_selection(return_uncertainty_case.snapshot, **changes)
    args = SimpleNamespace(experiment="missing.json", **{"cost_index": 0, "minimum_history_days": 20, **changes})
    assert console.research_intraday_sequential_selection_main(args) == 1
    output = capsys.readouterr()
    assert not output.out and json.loads(output.err)["status"] == "FAILED"


def test_signal_delay_price_reversal_sparse_signals_and_delayed_flat_oracle():
    from market_vault.backtest.intraday import run_intraday_execution
    from market_vault.research.intraday_signal_delay import _delayed_decisions, _reconstructed_prices
    original, sessions, bars, policy = _signal_delay_oracle_case()
    assert original["metrics"]["total_return"] == pytest.approx(.2)
    assert (original["trades"][0]["entry_slot"], original["trades"][0]["exit_slot"]) == (1, 3)
    assert _reconstructed_prices(original) == bars
    decisions, signals = _delayed_decisions(original, sessions, 1)
    # Slot 1 had no original observation. Delay is on the planned grid, not
    # the next saved observation, which is slot 2.
    assert [row["slot"] for row in decisions] == [1, 3]
    assert [row["target"] for row in decisions] == ["LONG", "FLAT"]
    delayed = run_intraday_execution(sessions=sessions, prices=bars, decisions=decisions, interval="30m", policy=policy)
    trade = delayed["trades"][0]
    assert (trade["entry_slot"], trade["exit_slot"], trade["exit_reason"]) == (2, 4, "TARGET_FLAT")
    assert trade["entry_raw_open"] == 130 and trade["exit_raw_open"] == 100
    assert delayed["metrics"]["final_cash"] == pytest.approx(100 / 130)
    assert delayed["metrics"]["total_return"] < 0
    for source, mapping, decision in zip(original["decisions"], signals["provenance"], decisions, strict=True):
        assert mapping["source_observation_key"] == source["observation_key"]
        assert mapping["source_time"] == source["decision_time"]
        assert mapping["source_score"] == source["score"]
        assert mapping["source_target"] == decision["target"]
        assert mapping["arrival_slot"] == mapping["source_slot"] + 1
        assert mapping["status"] == "FORWARDED" and mapping["passed_to_kernel"]
        assert mapping["derived_decision_key"] == decision["observation_key"] != source["observation_key"]
    assert delayed["ledger"][3]["timestamp"] == delayed["ledger"][4]["timestamp"]
    assert delayed["ledger"][3]["phase"] == "CLOSE" and delayed["ledger"][4]["phase"] == "OPEN"


@pytest.mark.parametrize("signals,max_hold,expected_slot,expected_reason", [
    (((0, "LONG"), (2, "FLAT")), 1, 3, "MAX_HOLD"),
    (((0, "LONG"), (4, "FLAT")), 20, 6, "EOD"),
])
def test_signal_delay_risk_controls_precede_delayed_exit(signals, max_hold, expected_slot, expected_reason):
    from market_vault.backtest.intraday import run_intraday_execution
    from market_vault.research.intraday_signal_delay import _delayed_decisions
    original, sessions, prices, policy = _signal_delay_oracle_case(signals=signals, max_hold=max_hold)
    decisions, _ = _delayed_decisions(original, sessions, 1)
    delayed = run_intraday_execution(sessions=sessions, prices=prices, decisions=decisions, interval="30m", policy=policy)
    trade = delayed["trades"][0]
    assert trade["entry_slot"] == 2
    assert trade["exit_slot"] == expected_slot and trade["exit_reason"] == expected_reason
    assert trade["exit_observation_key"] is None
    assert delayed["windows"] == original["windows"]
    assert delayed["ledger"][-1]["quantity"] == 0 and delayed["policy"] == original["policy"]


def test_signal_delay_last_eligible_entry_benchmark_is_not_reselected():
    from market_vault.backtest.intraday import run_intraday_execution
    from market_vault.research.intraday_signal_delay import _delayed_decisions
    original, sessions, prices, policy = _signal_delay_oracle_case(signals=((4, "LONG"),))
    assert original["trades"][0]["entry_slot"] == 5
    assert original["trades"][0]["exit_slot"] == 6
    for delay in (1, 2):
        decisions, signals = _delayed_decisions(original, sessions, delay)
        result = run_intraday_execution(sessions=sessions, prices=prices, decisions=decisions, interval="30m", policy=policy)
        assert signals["source_count"] == len(decisions) == 1
        assert decisions[0]["slot"] == 4 + delay
        assert result["trades"] == [] and result["metrics"]["final_cash"] == 1
        if delay == 1:
            assert signals["consumable_count"] == 1
            assert result["ledger"][12]["reason"] == "OUTSIDE_ENTRY_WINDOW"
        else:
            assert signals["no_next_open_count"] == 1


def test_signal_delay_session_tail_provenance_never_moves_to_next_day():
    from datetime import datetime
    from market_vault.backtest.intraday import run_intraday_execution
    from market_vault.research.intraday_signal_delay import _delayed_decisions
    original, sessions, prices, policy = _signal_delay_oracle_case(signals=((5, "LONG"), (6, "FLAT")))
    next_open = datetime.fromisoformat("2025-12-01T14:30:00+00:00")
    next_session = {"trading_day": "2025-12-01", "open_time": next_open.isoformat(),
                    "close_time": (next_open + timedelta(minutes=390)).isoformat(), "bar_count": 13}
    next_prices = tuple({"trading_day": "2025-12-01", "slot": slot,
        "event_time": (next_open + timedelta(minutes=30 * slot)).isoformat(),
        "available_at": (next_open + timedelta(minutes=30 * (slot + 1))).isoformat(),
        "open": 100, "close": 100, "row_version_id": f"{slot:064x}"} for slot in range(13))
    sessions, prices = (*sessions, next_session), (*prices, *next_prices)
    zero, zero_signals = _delayed_decisions(original, sessions, 0)
    assert list(zero) == original["decisions"]
    assert zero_signals["no_next_open_count"] == 1 and zero_signals["outside_session_count"] == 0
    for delay, forwarded, no_next, outside in ((1, 1, 1, 1), (2, 0, 0, 2)):
        decisions, signals = _delayed_decisions(original, sessions, delay)
        assert (signals["passed_to_kernel_count"], signals["no_next_open_count"], signals["outside_session_count"]) == (forwarded, no_next, outside)
        assert len(signals["provenance"]) == 2
        for row in signals["provenance"]:
            assert row["source_trading_day"] == "2025-11-28"
            assert row["arrival_slot"] == row["source_slot"] + delay
            assert row["passed_to_kernel"] == (row["status"] == "NO_NEXT_OPEN")
        result = run_intraday_execution(sessions=sessions, prices=prices, decisions=decisions, interval="30m", policy=policy)
        assert result["trades"] == [] and len(result["daily"]) == 2
        assert all(row["trade_count"] == 0 and row["return"] == 0 for row in result["daily"])
        assert all(row["observation_key"] is None for row in result["ledger"])


def test_signal_delay_real_saved_full_zero_equality_one_decode_and_installed_console(return_uncertainty_case, monkeypatch, capsys, tmp_path):
    import json
    import os
    import subprocess
    import sysconfig
    from pathlib import Path
    from market_vault import cli
    from market_vault.research import intraday_signal_delay as delay
    from market_vault.research.intraday_data import canonical_json, digest
    from market_vault.research.strategy_experiment import StrategyExperiment
    case = return_uncertainty_case
    root = case.snapshot.as_dict()
    group = root["report"]["groups"][1]
    sources = {"strategy": group["results"][1]["execution"], "benchmark": group["benchmark"]["execution"]}
    calls, decoded, checked, executed = {"decode": 0, "accounts": 0, "executions": 0}, StrategyExperiment.as_dict, delay._available, delay.run_intraday_execution
    def decode(self):
        calls["decode"] += 1
        return decoded(self)
    def account(*args, **kwargs):
        calls["accounts"] += 1
        return checked(*args, **kwargs)
    def execution(*args, **kwargs):
        calls["executions"] += 1
        return executed(*args, **kwargs)
    monkeypatch.setattr(StrategyExperiment, "as_dict", decode)
    monkeypatch.setattr(delay, "_available", account)
    monkeypatch.setattr(delay, "run_intraday_execution", execution)
    for name in ("load_intraday_dataset", "_fit"):
        monkeypatch.setattr(research, name, lambda *a, **kw: pytest.fail("signal delay accessed source or fit"))
    monkeypatch.setattr(cli, "load_settings", lambda *a, **kw: pytest.fail("signal delay accessed settings"))
    before = case.path.read_bytes()
    result = delay.analyze_intraday_signal_delay(case.snapshot, cost_index=1, candidate_index=1)
    assert calls == {"decode": 1, "accounts": 2, "executions": 6}
    assert result["availability"]["status"] == result["baseline"]["status"] == "AVAILABLE"
    assert result["evidence"] == "RECORDED_PRICE_GRID_REEXECUTION"
    assert result["baseline"]["excluded_identity_fields"] == ["price_evidence_id", "execution_id"]
    assert all(row["matches"] and row["differing_fields"] == [] for row in result["baseline"]["accounts"])
    assert result["sample"]["sample_count"] == 105 and result["sample"]["prediction_count"] == 945
    assert result["sample"]["split"] == root["report"]["context"]["split"]
    assert result["candidate_id"] == group["results"][1]["candidate_id"]
    for name, original in sources.items():
        baseline = result["scenarios"][0][name]
        strip = lambda value: {key: item for key, item in value.items() if key not in result["baseline"]["excluded_identity_fields"]}
        assert canonical_json(strip(baseline["execution"])) == canonical_json(strip(original))
        assert baseline["execution"]["execution_id"] != original["execution_id"]
        assert baseline["execution"]["price_evidence_id"] == result["projection"]["reconstructed_price_evidence_id"]
        assert baseline["execution"]["price_evidence_id"] != original["price_evidence_id"]
        for scenario in result["scenarios"]:
            side = scenario[name]
            assert scenario["status"] == "AVAILABLE"
            assert side["execution"]["policy"] == original["policy"]
            assert len(side["execution"]["ledger"]) == len(original["ledger"]) == 2730
            assert side["risk"]["execution_id"] == side["execution"]["execution_id"]
            assert side["risk"]["return_count"] == 105
            assert side["metrics"]["total_return"]["value"] == side["execution"]["metrics"]["total_return"]
            change = side["delta_from_zero"]["total_return"]
            assert change["unit"] == "PERCENTAGE_POINTS"
            assert change["value"] == (side["metrics"]["total_return"]["value"] - baseline["metrics"]["total_return"]["value"]) * 100
            assert [row["trading_day"] for row in side["execution"]["daily"]] == result["sample"]["evaluated_days"]
            assert [row["source_observation_key"] for row in side["signals"]["provenance"]] == [row["observation_key"] for row in original["decisions"]]
            assert side["signals"]["source_count"] == len(original["decisions"])
    assert [row["strategy"]["signals"]["passed_to_kernel_count"] for row in result["scenarios"]] == [945, 840, 735]
    assert [row["strategy"]["signals"]["outside_session_count"] for row in result["scenarios"]] == [0, 105, 210]
    # This saved counterexample prevents claiming monotonic degradation.
    assert result["scenarios"][1]["strategy"]["metrics"]["total_return"]["value"] > result["scenarios"][0]["strategy"]["metrics"]["total_return"]["value"]
    assert result["signal_delay_id"] == digest({key: value for key, value in result.items() if key != "signal_delay_id"})
    arguments = ["research-intraday-signal-delay", "--experiment", str(case.path), "--cost-index", "1", "--candidate-index", "1"]
    assert cli.main(arguments) == 0 and json.loads(capsys.readouterr().out)["report"] == result
    console = Path(sysconfig.get_path("scripts")) / ("market-vault.exe" if os.name == "nt" else "market-vault")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"), "PYTHONIOENCODING": "cp1252:strict"}
    process = subprocess.run([str(console), "--settings", str(tmp_path / "missing.yaml"), *arguments], env=env, capture_output=True, check=False)
    assert process.returncode == 0 and not process.stderr and process.stdout.isascii()
    assert json.loads(process.stdout)["report"] == result
    invalid = subprocess.run([str(console), *arguments, "--candidate-index", "-1"], env=env, capture_output=True, check=False)
    assert invalid.returncode == 1 and not invalid.stdout and json.loads(invalid.stderr)["status"] == "FAILED"
    for extra in (["--cost-index", "1.5"], ["--delay-bars", "3"]):
        rejected = subprocess.run([str(console), *arguments, *extra], env=env, capture_output=True, check=False)
        assert rejected.returncode == 2 and not rejected.stdout
    assert case.path.read_bytes() == before


@pytest.mark.parametrize("fault", ["semantic_ledger", "account", "basis"])
def test_signal_delay_signed_bad_source_or_complete_zero_mismatch_blocks_stress(return_uncertainty_case, monkeypatch, fault):
    from market_vault.research import intraday_signal_delay as delay
    from market_vault.research.strategy_experiment import StrategyExperiment
    from test_intraday_experiment import signed
    root = return_uncertainty_case.snapshot.as_dict()
    source = root["report"]["groups"][1]["results"][1]["execution"]
    if fault == "semantic_ledger":
        source["ledger"][0]["reason"] = "CHANGED_SAVED_REASON"
    elif fault == "account":
        source["trades"][0]["commission_total"] += .01
    else:
        source["ledger"][-2]["row_version_id"] = "f" * 64
    snapshot = StrategyExperiment(signed(root))
    calls, execute = [], delay.run_intraday_execution
    def recorded(**kwargs):
        calls.append(kwargs["decisions"])
        return execute(**kwargs)
    monkeypatch.setattr(delay, "run_intraday_execution", recorded)
    result = delay.analyze_intraday_signal_delay(snapshot, cost_index=1, candidate_index=1)
    assert result["availability"]["status"] == result["baseline"]["status"] == "UNAVAILABLE"
    if fault == "semantic_ledger":
        assert result["basis"]["matches"]
        assert all(row["status"] == "AVAILABLE" for row in result["availability"]["accounts"])
        assert result["availability"]["unavailable_reason"] == "ZERO_DELAY_REPRODUCTION_FAILED"
        assert len(calls) == 2
        check = result["baseline"]["accounts"][0]
        assert check["matches"] is False and check["differing_fields"] == ["ledger"]
        assert result["baseline"]["accounts"][1]["matches"] is True
    else:
        assert calls == []
        assert result["availability"]["unavailable_reason"] == ("BASIS_MISMATCH" if fault == "basis" else "SOURCE_ACCOUNT_UNAVAILABLE")
    for scenario in result["scenarios"]:
        assert scenario["status"] == "UNAVAILABLE"
        for name in ("strategy", "benchmark"):
            side = scenario[name]
            assert side["execution"] is side["risk"] is None
            assert all(row["value"] is None and row["unavailable_reason"] for row in side["metrics"].values())
            assert all(row["value"] is None and row["unavailable_reason"] for row in side["delta_from_zero"].values())
    assert result["sample"]["sample_count"] == 105


@pytest.mark.parametrize("changes", [{"cost_index": True}, {"cost_index": -1}, {"candidate_index": False}, {"candidate_index": 1.5}])
def test_signal_delay_invalid_indices_precede_decode_and_cli_file_io(return_uncertainty_case, monkeypatch, capsys, changes):
    import json
    from market_vault import intraday_signal_delay_cli as console
    from market_vault.research.intraday_signal_delay import analyze_intraday_signal_delay
    from market_vault.research.strategy_experiment import StrategyExperiment
    monkeypatch.setattr(StrategyExperiment, "as_dict", lambda self: pytest.fail("invalid arguments decoded source"))
    monkeypatch.setattr(console, "load_strategy_experiment", lambda *a: pytest.fail("invalid arguments opened file"))
    with pytest.raises(ValueError, match="integer"):
        analyze_intraday_signal_delay(return_uncertainty_case.snapshot, **changes)
    args = SimpleNamespace(experiment="missing.json", **{"cost_index": 0, "candidate_index": 0, **changes})
    assert console.research_intraday_signal_delay_main(args) == 1
    output = capsys.readouterr()
    assert not output.out and json.loads(output.err)["status"] == "FAILED"


def test_signal_delay_short_q10_child_rejects_collection_and_keeps_flat_accounts(execution_scenarios_case):
    from market_vault.research.intraday_execution_scenarios import extract_intraday_execution_scenario
    from market_vault.research.intraday_signal_delay import analyze_intraday_signal_delay
    collection = execution_scenarios_case[2]
    root = collection.as_dict()
    child = extract_intraday_execution_scenario(collection, expected_experiment_id=root["experiment_id"], scenario_index=1,
        expected_child_experiment_id=root["report"]["scenarios"][1]["experiment"]["experiment_id"])
    report = analyze_intraday_signal_delay(child, candidate_index=0)
    assert report["availability"]["status"] == "AVAILABLE" and report["sample"]["sample_count"] == 10
    assert report["sample"]["sample_count"] < 100
    for scenario in report["scenarios"]:
        assert scenario["strategy"]["execution"]["trades"] == []
        assert scenario["strategy"]["metrics"]["final_cash"]["value"] == 1
        assert scenario["strategy"]["metrics"]["sharpe_ratio"]["unavailable_reason"] == "ZERO_VOLATILITY"
        assert scenario["strategy"]["delta_from_zero"]["sharpe_ratio"]["unavailable_reason"] == "BOTH_UNAVAILABLE"
    with pytest.raises(ValueError, match="ordinary saved Q7 DEV"):
        analyze_intraday_signal_delay(collection)


def test_signal_delay_rejects_frozen_selection_and_out_of_range_indices(return_uncertainty_case):
    from market_vault.research.intraday_final_test import freeze_intraday_candidate
    from market_vault.research.intraday_signal_delay import analyze_intraday_signal_delay
    case = return_uncertainty_case
    root = case.snapshot.as_dict()
    candidate = root["report"]["groups"][0]["results"][0]
    selection = freeze_intraday_candidate(case.path, expected_experiment_id=root["experiment_id"], cost_index=0,
                                          candidate_index=0, expected_candidate_id=candidate["candidate_id"])
    with pytest.raises(ValueError, match="ordinary saved Q7 DEV"):
        analyze_intraday_signal_delay(selection)
    for options in ({"cost_index": 2}, {"candidate_index": 2}):
        with pytest.raises(ValueError, match="outside the saved experiment"):
            analyze_intraday_signal_delay(case.snapshot, **options)


def test_prediction_quality_small_rmse_negative_skill_and_pooled_fold_reversal():
    from market_vault.research.intraday_prediction_quality import _score_forecasts

    def rows(actual, predicted):
        return [{"target_status": "COMPLETE", "target_value": target,
                 "scores": {"RIDGE": prediction, "ZERO": 0.0, "TRAIN_MEAN": 0.0}}
                for target, prediction in zip(actual, predicted, strict=True)]

    tiny = _score_forecasts(rows((.001, -.001), (.003, -.003)))[0]["metrics"]
    assert tiny["rmse"]["value"] == pytest.approx(.002)
    assert tiny["mse_skill_vs_zero"]["value"] == pytest.approx(-3)
    assert tiny["pearson"]["value"] == tiny["spearman"]["value"] == pytest.approx(1)
    first, second = rows((-2, -1), (-2, -1)), rows((1, 2, 3), (-1, -2, -3))
    fold_a, fold_b = (_score_forecasts(items)[0]["metrics"] for items in (first, second))
    pooled = _score_forecasts(first + second)[0]["metrics"]
    assert fold_a["pearson"]["value"] == pytest.approx(1)
    assert fold_b["pearson"]["value"] == pytest.approx(-1)
    assert pooled["mse"]["value"] == pytest.approx(56 / 5)
    assert pooled["rmse"]["value"] == pytest.approx(math.sqrt(56 / 5))
    assert pooled["mae"]["value"] == pytest.approx(12 / 5)
    assert pooled["bias"]["value"] == pytest.approx(-12 / 5)
    assert pooled["r2"]["value"] == pytest.approx(1 - 56 / 17.2)
    assert pooled["mse"]["value"] != pytest.approx((fold_a["mse"]["value"] + fold_b["mse"]["value"]) / 2)


def test_prediction_quality_ties_constants_missing_targets_and_finite_loss_ratios():
    from market_vault.research.intraday_prediction_quality import _loss_skill, _prediction_metrics, _score_forecasts
    tied = _prediction_metrics((1.0, 1.0, 2.0, 3.0), (4.0, 4.0, 3.0, 1.0))
    assert tied["spearman"]["value"] == pytest.approx(-1)
    constant = _prediction_metrics((0.0, 0.0), (0.0, 0.0))
    assert constant["r2"]["unavailable_reason"] == "CONSTANT_TARGETS"
    assert constant["pearson"]["unavailable_reason"] == "CONSTANT_PREDICTIONS_AND_TARGETS"
    assert _prediction_metrics((1.0, 2.0), (0.0, 0.0))["pearson"]["unavailable_reason"] == "CONSTANT_PREDICTIONS"
    assert _prediction_metrics((1.0,), (2.0,))["spearman"]["unavailable_reason"] == "INSUFFICIENT_COMPLETE_TARGETS"
    assert _loss_skill((0.0, 0.0), (1.0, 1.0), (0.0, 0.0))["unavailable_reason"] == "ZERO_BASELINE_ERROR"
    for forecast in _score_forecasts([]):
        assert all(metric["value"] is None and metric["unavailable_reason"] == "NO_COMPLETE_TARGETS"
                   for metric in forecast["metrics"].values())
    # Tiny nonzero baseline errors must not be mislabeled as a perfect baseline.
    assert _loss_skill((1e-200, -1e-200), (0.0, 0.0), (0.0, 0.0))["value"] == 0
    large = _prediction_metrics((1e200, -1e200), (0.0, 0.0))
    assert large["mse"]["unavailable_reason"] == "NONFINITE_RESULT"
    assert large["rmse"]["value"] == pytest.approx(1e200)
    assert large["r2"]["value"] == pytest.approx(0)


def test_prediction_quality_training_mean_uses_each_purged_history_not_current_or_test_targets():
    from market_vault.research.intraday_prediction_quality import _paired_prediction_rows
    observations = [{"observation_key": f"key-{i}", "trading_day": f"2025-02-0{i + 3}",
                     "status": "READY", "slot": 1, "decision_time": f"2025-02-0{i + 3}T15:00:00+00:00"}
                    for i in range(4)]
    folds = [{"fold_index": i, "fold_id": f"fold-{i}",
              "training_boundary": f"2025-02-0{i + 4}T14:30:00+00:00",
              "validation_keys": [f"key-{i + 1}"], "validation_days": [f"2025-02-0{i + 4}"]}
             for i in range(2)]
    candidate = {"predictions": [{**row, "score": 0.0} for row in observations[1:3]],
                 "fold_models": [{"model": {"model_id": f"model-{i}"}} for i in range(2)]}

    def calculated(values):
        report = {"observations": observations,
                  "targets": [{"observation_key": row["observation_key"], "status": "COMPLETE", "reason": None,
                               "actual_label_end_time": f"{row['trading_day']}T15:15:00+00:00", "value": value}
                              for row, value in zip(observations, values, strict=True)]}
        retained = tuple(research.training_rows(report, tuple(row["trading_day"] for row in observations[:i + 1]),
                                               fold["training_boundary"])[0] for i, fold in enumerate(folds))
        prepared = SimpleNamespace(report=report, fold_rows=retained,
                                   context={"folds": folds, "validation_keys": ["key-1", "key-2"]})
        return _paired_prediction_rows(prepared, candidate)

    original, future, held_out = calculated((1.0, 10.0, 100.0, 1000.0)), calculated((1.0, 20.0, 200.0, 1000.0)), calculated((1.0, 10.0, 100.0, -1000.0))
    assert [fold["training_target_mean"] for fold in original[1]] == [1.0, 5.5]
    assert [fold["training_target_mean"] for fold in future[1]] == [1.0, 10.5]
    assert original == held_out
    assert [row["scores"]["TRAIN_MEAN"] for row in future[0]] == [1.0, 10.5]
    assert {row["observation_key"] for row in original[0]} == {"key-1", "key-2"}


def test_prediction_quality_real_selected_refit_tail_coverage_source_locator_and_installed_cli(research_case, tmp_path, monkeypatch):
    import json
    import os
    from pathlib import Path
    import subprocess
    import sysconfig
    from market_vault.research import intraday_prediction_quality as quality
    from market_vault.research.intraday_experiment import create_intraday_experiment
    from market_vault.research.strategy_experiment import write_strategy_experiment
    data, plan, report = research_case
    snapshot = create_intraday_experiment(plan=plan, report=report, name="预测质量")
    path, relocated = tmp_path / "development.json", tmp_path / "relocated-intraday.json"
    write_strategy_experiment(snapshot, path=path)
    relocated.write_bytes(data.path.read_bytes())
    before = path.read_bytes(), data.path.read_bytes(), relocated.read_bytes()
    calls, loader, fitter = {"loads": 0, "fits": 0}, research.load_intraday_dataset, research._fit
    def loaded(*args, **kwargs):
        calls["loads"] += 1
        return loader(*args, **kwargs)
    def fitted(*args, **kwargs):
        calls["fits"] += 1
        return fitter(*args, **kwargs)
    monkeypatch.setattr(research, "load_intraday_dataset", loaded)
    monkeypatch.setattr(research, "_fit", fitted)
    monkeypatch.setattr(research, "run_intraday_execution", lambda *a, **kw: pytest.fail("prediction quality reran Q6"))
    result = quality.analyze_intraday_prediction_quality(snapshot, candidate_index=2, intraday_data_file=" ")
    assert calls == {"loads": 1, "fits": 2}
    assert result["sample"] == {"prediction_count": 740, "complete_target_count": 710, "incomplete_target_count": 30,
                                "scored_day_count": 10, "evaluated_day_count": 10, "fold_count": 2}
    assert result["context"] == report["context"]
    assert result["candidate_id"] == report["groups"][0]["results"][2]["candidate_id"]
    assert result["source_locator"] == {"recorded": str(data.path), "used": str(data.path.resolve()), "override_used": False}
    assert result["evidence"] == {"scope": "SOURCE_VERIFIED_SELECTED_RIDGE_RECONSTRUCTION", "context_matches": True,
                                  "fold_models_match": True, "predictions_match": True,
                                  "prediction_metrics_match": True, "execution_replayed": False}
    assert [row["observation_key"] for row in result["predictions"]] == report["context"]["validation_keys"]
    assert all(row["target_value"] is None and row["target_reason"] == "SESSION_END" and len(row["scores"]) == 3
               for row in result["predictions"] if row["target_status"] != "COMPLETE")
    target_by_key = {row["observation_key"]: row for row in data.as_dict()["report"]["targets"]}
    for fold, original in zip(result["folds"], report["context"]["folds"], strict=True):
        expected = math.fsum(target_by_key[key]["value"] for key in original["training_keys"]) / len(original["training_keys"])
        assert fold["training_target_mean"] == expected
        assert fold["sample"]["complete_target_count"] == 355
    expected_errors = report["groups"][0]["results"][2]["prediction_metrics"]
    assert [result["forecasts"][0]["metrics"][key]["value"] for key in ("mae", "rmse", "r2")] == pytest.approx(
        [expected_errors[key] for key in ("mae", "rmse", "r2")])
    assert result["prediction_quality_id"] == research.digest({key: value for key, value in result.items() if key != "prediction_quality_id"})
    console = Path(sysconfig.get_path("scripts")) / ("market-vault.exe" if os.name == "nt" else "market-vault")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"), "PYTHONIOENCODING": "cp1252:strict"}
    process = subprocess.run([str(console), "research-intraday-prediction-quality", "--experiment", str(path),
                              "--candidate-index", "2", "--intraday-data", str(relocated)], env=env, capture_output=True, check=False)
    assert process.returncode == 0 and not process.stderr
    assert process.stdout.isascii()
    cli_result = json.loads(process.stdout)["report"]
    assert cli_result["forecasts"] == result["forecasts"] and cli_result["predictions"] == result["predictions"]
    assert cli_result["source_locator"] == {"recorded": str(data.path), "used": str(relocated.resolve()), "override_used": True}
    # Q5 locators are portable metadata. A valid relocated Q5 whose Canonical
    # source is missing must fail as structured CLI output, without a traceback.
    broken = data.as_dict()
    broken["plan"]["canonical_build_dirs"] = [str(tmp_path / "missing-canonical")]
    broken_path = tmp_path / "missing-source-intraday.json"
    from market_vault.research.intraday_data import canonical_json
    broken_path.write_bytes(canonical_json(broken))
    failed = subprocess.run([str(console), "research-intraday-prediction-quality", "--experiment", str(path),
                             "--candidate-index", "2", "--intraday-data", str(broken_path)],
                            env=env, capture_output=True, check=False)
    assert failed.returncode == 1 and not failed.stdout
    assert failed.stderr.isascii() and json.loads(failed.stderr)["status"] == "FAILED"
    assert (path.read_bytes(), data.path.read_bytes(), relocated.read_bytes()) == before


@pytest.mark.parametrize("changed_field", ["context", "models", "predictions", "prediction_metrics"])
def test_prediction_quality_rejects_resigned_selected_evidence(research_case, monkeypatch, changed_field):
    from market_vault.research.intraday_prediction_quality import analyze_intraday_prediction_quality
    from market_vault.research.intraday_experiment import create_intraday_experiment
    from test_intraday_experiment import _comparison_snapshot
    data, plan, report = research_case
    root = create_intraday_experiment(plan=plan, report=report).as_dict()
    candidate = root["report"]["groups"][0]["results"][2]
    if changed_field == "context":
        root["report"]["context"]["held_out_test_observation_count"] += 1
    elif changed_field == "models":
        candidate["fold_models"][0]["model"]["coefficients"][0] += .01
    elif changed_field == "predictions":
        candidate["predictions"][0]["score"] += .01
        candidate["execution"]["decisions"][0]["score"] += .01
    else:
        candidate["prediction_metrics"]["rmse"] += .01
    changed = _comparison_snapshot(root)  # Real saved grammar accepts these newly signed contents.
    prepared = research._prepare_intraday_research(plan, data=data)
    calls, fit = [], research._fit
    monkeypatch.setattr(research, "_prepare_intraday_research", lambda *a, **kw: prepared)
    def fitted(*args, **kwargs):
        calls.append(1)
        return fit(*args, **kwargs)
    monkeypatch.setattr(research, "_fit", fitted)
    with pytest.raises(ValueError, match="saved context" if changed_field == "context" else "reconstruction differs"):
        analyze_intraday_prediction_quality(changed, candidate_index=2)
    assert len(calls) == (0 if changed_field == "context" else 2)


def test_prediction_quality_admission_precedes_source_io_and_cli_settings(research_case, tmp_path, monkeypatch, capsys):
    import json
    from market_vault import cli
    from market_vault.research.intraday_prediction_quality import analyze_intraday_prediction_quality
    from market_vault.research.intraday_experiment import create_intraday_experiment
    from market_vault.research.intraday_final_test import freeze_intraday_candidate
    from market_vault.research.strategy_experiment import write_strategy_experiment
    from test_intraday_experiment import _comparison_snapshot
    _, plan, report = research_case
    snapshot = create_intraday_experiment(plan=plan, report=report)
    monkeypatch.setattr(research, "load_intraday_dataset", lambda *a, **kw: pytest.fail("inadmissible request loaded Q5"))
    monkeypatch.setattr(cli, "load_settings", lambda *a, **kw: pytest.fail("prediction quality loaded settings"))
    for options in ({"cost_index": True}, {"candidate_index": -1}, {"candidate_index": 1.5},
                    {"cost_index": 1}, {"candidate_index": 3}, {"candidate_index": 0}, {"intraday_data_file": False}):
        with pytest.raises(ValueError):
            analyze_intraday_prediction_quality(snapshot, **options)
    root = snapshot.as_dict()
    root["algorithm_versions"]["ridge"] = "historical-ridge"
    with pytest.raises(ValueError, match="versions differ"):
        analyze_intraday_prediction_quality(_comparison_snapshot(root), candidate_index=2)
    with pytest.raises(ValueError, match="immutable StrategyExperiment"):
        analyze_intraday_prediction_quality(object())
    # A real frozen selection cannot enter the native DEV reconstruction path.
    path = tmp_path / "development.json"
    write_strategy_experiment(snapshot, path=path)
    selection = freeze_intraday_candidate(path, expected_experiment_id=snapshot.experiment_id,
        cost_index=0, candidate_index=2, expected_candidate_id=report["groups"][0]["results"][2]["candidate_id"])
    with pytest.raises(ValueError, match="ordinary saved DEV"):
        analyze_intraday_prediction_quality(selection)
    assert cli.main(["research-intraday-prediction-quality", "--experiment", str(tmp_path / "missing.json"),
                     "--candidate-index", "-1"]) == 1
    error = capsys.readouterr()
    assert not error.out and json.loads(error.err)["error"] == "candidate_index must be a nonnegative integer"


def test_feature_ablation_constant_informative_order_and_exact_model_rows(monkeypatch):
    from market_vault.research.intraday_feature_ablation import _ablation_predictions, _paired_error_changes
    prepared, candidate = _feature_ablation_case()
    original = deepcopy((prepared.context, prepared.report, candidate))
    calls, fit = [], research.fit_ridge_rows
    def fitted(training, observations, features, alpha, *, boundary):
        calls.append((training, tuple(row["observation_key"] for row in observations), tuple(features), alpha, boundary))
        return fit(training, observations, features, alpha, boundary=boundary)
    monkeypatch.setattr(research, "fit_ridge_rows", fitted)
    rows, folds, variants = _ablation_predictions(prepared, candidate)
    assert len(calls) == 6
    assert [variant["omitted_feature"] for variant in variants] == ["constant", "informative", "distractor"]
    assert [variant["retained_features"] for variant in variants] == [["informative", "distractor"], ["constant", "distractor"], ["constant", "informative"]]
    assert [row["observation_key"] for row in rows] == prepared.context["validation_keys"]
    assert [fold["sample"]["complete_target_count"] for fold in folds] == [2, 4]
    assert all(row["scores"]["DROP_0"] == row["scores"]["RIDGE"] for row in rows)
    deltas = _paired_error_changes(rows, forecast_order=("DROP_0", "DROP_1", "DROP_2"))
    assert all(metric["value"] == 0 for metric in deltas[0]["metrics"].values())
    assert deltas[1]["metrics"]["mse"]["value"] > .05
    for variant_index, variant in enumerate(variants):
        assert variant["model_kind"] == "RIDGE_REFIT"
        for index, (record, fold) in enumerate(zip(variant["fold_models"], prepared.context["folds"], strict=True)):
            training, keys, features, alpha, boundary = calls[variant_index * 2 + index]
            model = record["model"]
            assert training is prepared.fold_rows[index]
            assert keys == tuple(fold["validation_keys"])
            assert list(features) == model["feature_fields"] == variant["retained_features"]
            assert alpha == model["alpha"] == candidate["strategy"]["alpha"]
            assert boundary == model["training_boundary"] == fold["training_boundary"]
            assert model["training_keys"] == fold["training_keys"] and "not-ready" not in model["training_keys"]
            assert ("boundary-purged" in model["training_keys"]) == (index == 1)
            for field, mean, scale in zip(features, model["means"], model["scales"], strict=True):
                values = [row["features"][field] for row, _ in training]
                expected_mean = sum(values) / len(values)
                assert mean == pytest.approx(expected_mean)
                assert scale == pytest.approx(math.sqrt(sum((value - expected_mean) ** 2 for value in values) / len(values)))
            assert model["model_id"] == research.digest({key: value for key, value in model.items() if key != "model_id"})
    assert (prepared.context, prepared.report, candidate) == original


def test_feature_ablation_single_feature_is_explicit_training_mean_without_solver(monkeypatch):
    from market_vault.research.intraday_feature_ablation import _ablation_predictions
    prepared, candidate = _feature_ablation_case(("informative",))
    monkeypatch.setattr(research, "fit_ridge_rows", lambda *a, **kw: pytest.fail("intercept-only called Ridge solver"))
    rows, folds, variants = _ablation_predictions(prepared, candidate)
    assert len(variants) == 1 and variants[0]["retained_features"] == []
    assert variants[0]["model_kind"] == "INTERCEPT_ONLY_TRAIN_MEAN"
    assert all(row["scores"]["DROP_0"] == row["scores"]["TRAIN_MEAN"] for row in rows)
    for index, (record, fold) in enumerate(zip(variants[0]["fold_models"], folds, strict=True)):
        model = record["model"]
        expected = math.fsum(target["value"] for _, target in prepared.fold_rows[index]) / len(prepared.fold_rows[index])
        assert model["kind"] == "INTERCEPT_ONLY_TRAIN_MEAN" and model["solver_used"] is False
        assert model["intercept"] == expected == fold["training_target_mean"]
        assert model["feature_fields"] == model["coefficients"] == model["means"] == model["scales"] == []
        assert model["training_keys"] == prepared.context["folds"][index]["training_keys"]
        assert model["training_boundary"] == fold["training_boundary"]
        assert model["model_id"] == research.digest({key: value for key, value in model.items() if key != "model_id"})


def test_feature_ablation_signed_paired_errors_pool_rows_and_preserve_metric_availability():
    from market_vault.research.intraday_feature_ablation import _paired_error_changes
    def row(full, ablated, *, complete=True):
        return {"target_status": "COMPLETE" if complete else "INCOMPLETE", "target_value": 0.0 if complete else None,
                "scores": {"RIDGE": full, "DROP_0": ablated}}
    first, second = [row(1, 3)], [row(2, 0), row(2, 1), row(2, 2)]
    def metrics(rows):
        return _paired_error_changes(rows, forecast_order=("DROP_0",))[0]["metrics"]
    left, right = metrics(first), metrics(second)
    pooled = metrics(first + second + [row(1e300, -1e300, complete=False)])
    assert left["mse"]["value"] == 8 and right["mse"]["value"] == pytest.approx(-7 / 3)
    assert pooled["mse"] == {"value": pytest.approx(.25), "unit": "SQUARED_RATIO", "unavailable_reason": None}
    assert pooled["mae"]["value"] == pytest.approx(-.25)
    assert pooled["rmse"]["value"] == pytest.approx(math.sqrt(14 / 4) - math.sqrt(13 / 4))
    assert pooled["mse"]["value"] != pytest.approx((left["mse"]["value"] + right["mse"]["value"]) / 2)
    assert all(metric["unavailable_reason"] == "NO_COMPLETE_TARGETS" for metric in metrics([]).values())
    large = metrics([row(1e200, 2e200)])
    assert large["mse"]["value"] is None and large["mse"]["unavailable_reason"] == "NONFINITE_RESULT"
    assert large["mae"]["value"] == large["rmse"]["value"] == pytest.approx(1e200)


def test_feature_ablation_future_target_changes_only_later_fits_and_test_is_excluded():
    from market_vault.research.intraday_feature_ablation import _ablation_predictions
    original = _ablation_predictions(*_feature_ablation_case())
    future = _ablation_predictions(*_feature_ablation_case(future_shift=.6))
    held_out = _ablation_predictions(*_feature_ablation_case(test_shift=1000))
    assert original == held_out
    for full, changed in zip(original[2], future[2], strict=True):
        assert full["fold_models"][0] == changed["fold_models"][0]
        assert full["fold_models"][1]["model"]["intercept"] != changed["fold_models"][1]["model"]["intercept"]
        for before, after in zip(full["fold_models"], changed["fold_models"], strict=True):
            assert before["model"]["means"] == after["model"]["means"]
            assert before["model"]["scales"] == after["model"]["scales"]
    assert [row["scores"] for row in original[0][:3]] == [row["scores"] for row in future[0][:3]]
    assert original[1][0]["forecasts"] != future[1][0]["forecasts"]


def test_feature_ablation_real_nonfirst_selected_source_refit_and_installed_cli(research_case, tmp_path, monkeypatch, capsys):
    import json
    import os
    from pathlib import Path
    import subprocess
    import sysconfig
    from market_vault import cli
    from market_vault.research.intraday_feature_ablation import analyze_intraday_feature_ablation
    from market_vault.research.intraday_experiment import create_intraday_experiment
    from market_vault.research.strategy_experiment import write_strategy_experiment
    data, comparison, _ = research_case
    plan = diagnostic_plan(deepcopy(comparison))
    plan["comparison_plan"]["feature_fields"] = ["return_2", "sma_5", "candle_body"]
    plan["parameter_axes"] = [{"parameter": "alpha", "values": [1, 10]}]
    saved = research.run_intraday_research(plan)
    snapshot = create_intraday_experiment(plan=plan, report=saved, name="逐项移除")
    path, relocated = tmp_path / "development.json", tmp_path / "relocated-intraday.json"
    write_strategy_experiment(snapshot, path=path)
    relocated.write_bytes(data.path.read_bytes())
    before = path.read_bytes(), data.path.read_bytes(), relocated.read_bytes()
    calls, loader, fitter = {"loads": 0, "fits": []}, research.load_intraday_dataset, research.fit_ridge_rows
    def loaded(*args, **kwargs):
        calls["loads"] += 1
        return loader(*args, **kwargs)
    def fitted(training, observations, features, alpha, *, boundary):
        calls["fits"].append((list(features), alpha))
        return fitter(training, observations, features, alpha, boundary=boundary)
    monkeypatch.setattr(research, "load_intraday_dataset", loaded)
    monkeypatch.setattr(research, "fit_ridge_rows", fitted)
    monkeypatch.setattr(research, "run_intraday_execution", lambda *a, **kw: pytest.fail("ablation reran Q6"))
    monkeypatch.setattr(cli, "load_settings", lambda *a, **kw: pytest.fail("ablation loaded settings"))
    result = analyze_intraday_feature_ablation(snapshot, cost_index=1, candidate_index=1)
    candidate = saved["groups"][1]["results"][1]
    assert calls["loads"] == 1 and len(calls["fits"]) == 8
    assert all(alpha == 10.0 for _, alpha in calls["fits"])
    assert result["candidate_id"] == candidate["candidate_id"] and result["context"] == saved["context"]
    assert result["baseline"] == {"strategy": candidate["strategy"], "fold_models": candidate["fold_models"]}
    assert result["evidence"]["execution_replayed"] is False
    assert result["method"]["forecast_order"] == ["RIDGE", "ZERO", "TRAIN_MEAN", "DROP_0", "DROP_1", "DROP_2"]
    assert result["method"]["paired_error_difference"] == "ABLATION_MINUS_FULL_RIDGE"
    assert result["sample"]["prediction_count"] == 740 and result["sample"]["complete_target_count"] == 710
    assert [row["observation_key"] for row in result["predictions"]] == saved["context"]["validation_keys"]
    assert all(list(row["scores"]) == result["method"]["forecast_order"] for row in result["predictions"])
    assert all(row["target_value"] is None for row in result["predictions"] if row["target_status"] != "COMPLETE")
    assert all(row["trading_day"] not in saved["context"]["split"]["TEST"] for row in result["predictions"])
    assert result["feature_ablation_id"] == research.digest({key: value for key, value in result.items() if key != "feature_ablation_id"})
    for fold, original in zip(result["folds"], saved["context"]["folds"], strict=True):
        paired = [row for row in result["predictions"] if row["fold_id"] == fold["fold_id"] and row["target_status"] == "COMPLETE"]
        for variant, change in zip(result["variants"], fold["paired_error_changes"], strict=True):
            assert change["forecast"] == variant["forecast"]
            expected = math.fsum((row["scores"][variant["forecast"]] - row["target_value"]) ** 2
                                - (row["scores"]["RIDGE"] - row["target_value"]) ** 2 for row in paired) / len(paired)
            assert change["metrics"]["mse"]["value"] == pytest.approx(expected, rel=1e-8, abs=1e-20)
            model = variant["fold_models"][fold["fold_index"]]["model"]
            assert model["training_keys"] == original["training_keys"]
            assert model["feature_fields"] == variant["retained_features"]
    console = Path(sysconfig.get_path("scripts")) / ("market-vault.exe" if os.name == "nt" else "market-vault")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"), "PYTHONIOENCODING": "cp1252:strict"}
    command = [str(console), "research-intraday-feature-ablation", "--experiment", str(path),
               "--cost-index", "1", "--candidate-index", "1", "--intraday-data", str(relocated)]
    process = subprocess.run(command, env=env, cwd=tmp_path, capture_output=True, check=False)
    assert process.returncode == 0 and not process.stderr and process.stdout.isascii()
    cli_result = json.loads(process.stdout)["report"]
    assert cli_result["forecasts"] == result["forecasts"] and cli_result["predictions"] == result["predictions"]
    assert cli_result["variants"] == result["variants"] and cli_result["paired_error_changes"] == result["paired_error_changes"]
    assert cli_result["source_locator"] == {"recorded": str(data.path), "used": str(relocated.resolve()), "override_used": True}
    failed = subprocess.run(command[:-1] + [str(tmp_path / "missing-q5.json")], env=env, cwd=tmp_path, capture_output=True, check=False)
    assert failed.returncode == 1 and not failed.stdout and json.loads(failed.stderr)["status"] == "FAILED"
    assert cli.main(["research-intraday-feature-ablation", "--experiment", str(tmp_path / "missing.json"),
                     "--cost-index", "-1"]) == 1
    error = capsys.readouterr()
    assert not error.out and json.loads(error.err)["error"] == "cost_index must be a nonnegative integer"
    assert (path.read_bytes(), data.path.read_bytes(), relocated.read_bytes()) == before


def _quadratic_case(features=("x",), *, interaction=False, future_target_shift=0.0,
                    future_feature_shift=0.0, test_shift=0.0):
    """Small chronological rows with analytic curvature/interaction oracles."""
    days = [f"2025-04-{index:02d}" for index in range(1, 8)]
    observations, targets = [], []
    for index, day in enumerate(days):
        if interaction:
            points = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
            if index in (4, 5):
                points = [(-2, -3), (-2, 3), (2, -3), (2, 3), (4, 5)]
        else:
            points = [(x, 0) for x in ((-3, 0, 3, 4) if index == 4
                      else (-4, -2, 0, 2, 4, 5) if index == 5 else (-2, -1, 1, 2))]
        for slot, (x, y) in enumerate(points):
            key = f"{day}-{slot}"
            incomplete = index in (4, 5) and slot == len(points) - 1
            shift = future_feature_shift if index == 4 else test_shift if index == 6 else 0.0
            observations.append({"observation_key": key, "trading_day": day, "slot": slot,
                "decision_time": f"{day}T15:{slot * 5:02d}:00+00:00", "status": "READY",
                "features": {"x": x + shift, "y": y + shift, "constant": 7.0}})
            target = x * y if interaction else x * x
            targets.append({"observation_key": key, "status": "INCOMPLETE" if incomplete else "COMPLETE",
                "reason": "SESSION_END" if incomplete else None,
                "actual_label_end_time": None if incomplete else f"{day}T15:{slot * 5 + 5:02d}:00+00:00",
                "value": None if incomplete else target + (future_target_shift if index == 4
                                                          else test_shift if index == 6 else 0.0)})
    observations.append({**observations[0], "observation_key": "not-ready", "status": "NOT_READY",
                         "features": {"x": None, "y": None, "constant": 7.0}})
    targets.append({**targets[0], "observation_key": "not-ready"})
    observations.append({**observations[12], "observation_key": "boundary-purged"})
    targets.append({**targets[12], "observation_key": "boundary-purged",
                    "actual_label_end_time": f"{days[4]}T14:30:00+00:00"})
    report, folds, training = {"observations": observations, "targets": targets}, [], []
    for index, day in enumerate(days[4:6]):
        boundary = f"{day}T14:30:00+00:00"
        rows, purged = research.training_rows(report, tuple(days[:index + 4]), boundary)
        fold = {"fold_index": index, "training_days": days[:index + 4], "validation_days": [day],
                "training_boundary": boundary, "training_keys": [row["observation_key"] for row, _ in rows],
                "purged_keys": list(purged),
                "validation_keys": [row["observation_key"] for row in observations if row["trading_day"] == day]}
        fold["fold_id"] = research.digest(fold)
        folds.append(fold)
        training.append(rows)
    context = {"feature_fields": list(features), "folds": folds, "evaluated_days": days[4:6],
               "validation_keys": [key for fold in folds for key in fold["validation_keys"]]}
    prepared = SimpleNamespace(report=report, context=context, fold_rows=tuple(training),
        observations=tuple(row for row in observations if row["observation_key"] in context["validation_keys"]))
    strategy = {"kind": "RIDGE", "name": "Controlled quadratic reference", "alpha": 2.0, "threshold": 0.0}
    predictions, models, metrics = research.candidate_predictions(prepared, research.parse_strategy_specs([strategy])[0], {})
    return prepared, {"strategy": strategy, "predictions": predictions, "fold_models": models, "prediction_metrics": metrics}


def test_quadratic_ridge_symmetric_heldout_curvature_and_both_training_normalizations():
    from market_vault.research.intraday_quadratic_ridge import _quadratic_predictions
    prepared, candidate = _quadratic_case()
    original = deepcopy((prepared.context, prepared.report, candidate))
    rows, folds, quadratic = _quadratic_predictions(prepared, candidate)
    # TRAIN is sixteen symmetric x values with E[x²]=2.5. Normalized x²
    # has scale 0.6, so the existing solver shrinks its one nonzero direction
    # by n/(n+alpha), without fitting any expected model in this oracle.
    shrink = 16 / (16 + 2)
    first = rows[:4]
    assert [row["scores"]["RIDGE"] for row in first] == pytest.approx([2.5] * 4)
    assert [row["scores"]["QUADRATIC_RIDGE"] for row in first] == pytest.approx(
        [2.5 * (1 - shrink) + shrink * x * x for x in (-3, 0, 3, 4)])
    assert quadratic["degree"] == 2 and quadratic["expanded_width"] == 2
    assert quadratic["terms"] == [{"name": "z_0", "input_indices": [0]}, {"name": "z_0*z_0", "input_indices": [0, 0]}]
    model = quadratic["fold_models"][0]["model"]
    assert model["input_transform"] == {"means": [0.0], "scales": [pytest.approx(math.sqrt(2.5))], "constant_policy": "ZERO"}
    assert model["ridge_model"]["means"] == pytest.approx([0.0, 1.0])
    assert model["ridge_model"]["scales"] == pytest.approx([1.0, .6])
    assert model["ridge_model"]["coefficients"] == pytest.approx([0.0, 2.5 * shrink])
    assert model["ridge_model"]["intercept"] == pytest.approx(2.5 * (1 - shrink))
    assert folds[0]["paired_error_changes"][0]["metrics"]["mse"]["value"] < -20
    assert [row["observation_key"] for row in rows] == prepared.context["validation_keys"]
    assert [fold["sample"]["complete_target_count"] for fold in folds] == [3, 5]
    assert [fold["sample"]["incomplete_target_count"] for fold in folds] == [1, 1]
    assert all(row["target_value"] is None and math.isfinite(row["scores"]["QUADRATIC_RIDGE"])
               for row in rows if row["target_status"] == "INCOMPLETE")
    for record, fold in zip(quadratic["fold_models"], prepared.context["folds"], strict=True):
        model, ridge = record["model"], record["model"]["ridge_model"]
        assert model["training_keys"] == ridge["training_keys"] == fold["training_keys"]
        assert model["training_boundary"] == ridge["training_boundary"] == fold["training_boundary"]
        assert ("boundary-purged" in model["training_keys"]) == (fold["fold_index"] == 1)
        assert "not-ready" not in model["training_keys"]
        assert ridge["feature_fields"] == [term["name"] for term in quadratic["terms"]]
        assert model["alpha"] == ridge["alpha"] == candidate["strategy"]["alpha"]
        assert model["model_id"] == research.digest({key: value for key, value in model.items() if key != "model_id"})
        assert ridge["model_id"] == research.digest({key: value for key, value in ridge.items() if key != "model_id"})
        assert all(row["quadratic_model_id"] == model["model_id"] for row in rows if row["fold_id"] == fold["fold_id"])
        assert all(row["model_id"] == candidate["fold_models"][fold["fold_index"]]["model"]["model_id"]
                   for row in rows if row["fold_id"] == fold["fold_id"])
    assert (prepared.context, prepared.report, candidate) == original


def test_quadratic_ridge_pair_interaction_exact_order_arithmetic_and_constant_columns():
    from market_vault.research.intraday_quadratic_ridge import _expanded_observation, _quadratic_predictions, _quadratic_terms
    prepared, candidate = _quadratic_case(("y", "x", "constant"), interaction=True)
    for row in prepared.observations:
        row["features"]["constant"] = 99.0  # TRAIN-constant remains zero even on changed validation values.
    rows, _, quadratic = _quadratic_predictions(prepared, candidate)
    names = ["z_0", "z_1", "z_2", "z_0*z_0", "z_0*z_1", "z_0*z_2", "z_1*z_1", "z_1*z_2", "z_2*z_2"]
    assert quadratic["input_features"] == ["y", "x", "constant"]
    assert quadratic["expanded_width"] == 9 and [term["name"] for term in quadratic["terms"]] == names
    assert [term["input_indices"] for term in quadratic["terms"]] == [[0], [1], [2], [0, 0], [0, 1], [0, 2], [1, 1], [1, 2], [2, 2]]
    model = quadratic["fold_models"][0]["model"]
    assert model["input_transform"] == {"means": [0.0, 0.0, 7.0], "scales": [1.0, 1.0, 0.0], "constant_policy": "ZERO"}
    ridge = model["ridge_model"]
    assert ridge["means"] == pytest.approx([0, 0, 0, 1, 0, 0, 1, 0, 0])
    assert ridge["scales"] == pytest.approx([1, 1, 0, 0, 1, 0, 0, 0, 0])
    shrink = 16 / 18
    assert ridge["coefficients"] == pytest.approx([0, 0, 0, 0, shrink, 0, 0, 0, 0])
    assert ridge["intercept"] == pytest.approx(0)
    assert [row["scores"]["RIDGE"] for row in rows[:5]] == pytest.approx([0] * 5)
    assert [row["scores"]["QUADRATIC_RIDGE"] for row in rows[:5]] == pytest.approx(
        [6 * shrink, -6 * shrink, -6 * shrink, 6 * shrink, 20 * shrink])
    observation = {"features": {"y": 14.0, "x": 4.0, "constant": 99.0}, "observation_key": "arithmetic"}
    expanded = _expanded_observation(observation, quadratic["input_features"], (10, 2, 7), (2, 4, 0), quadratic["terms"])
    assert list(expanded["features"].values()) == [2, .5, 0, 4, 1, 0, .25, 0, 0]
    assert expanded["observation_key"] == observation["observation_key"]
    assert observation["features"] == {"y": 14.0, "x": 4.0, "constant": 99.0}
    maximum = _quadratic_terms(tuple(f"f_{index}" for index in range(6)))
    assert len(maximum) == 6 * (6 + 3) // 2 == 27 and maximum[-1] == {"name": "z_5*z_5", "input_indices": [5, 5]}
    assert all(term["input_indices"] for term in maximum)  # There is no explicit bias term.


@pytest.mark.parametrize("constant", [0.1, -0.1, 7.0])
def test_quadratic_ridge_fractional_train_constant_cannot_create_interactions(constant):
    from market_vault.research.intraday_quadratic_ridge import _quadratic_predictions
    training = tuple(({"observation_key": f"train-{index}", "features": {"x": x, "constant": constant}},
                      {"value": x}) for index, x in enumerate((-3.0, -2.0, -1.0, 1.0, 2.0, 3.0)))
    validation = tuple({"observation_key": f"validation-{index}", "trading_day": "2025-01-02",
                        "slot": index, "decision_time": "2025-01-02T15:00:00+00:00",
                        "features": {"x": 2.0, "constant": value}}
                       for index, value in enumerate((constant, 99.0)))
    fold = {"fold_index": 0, "fold_id": "constant-fold", "training_days": ["2025-01-01"],
            "validation_days": ["2025-01-02"], "training_boundary": "2025-01-02T14:30:00+00:00",
            "training_keys": [row["observation_key"] for row, _ in training],
            "validation_keys": [row["observation_key"] for row in validation]}
    prepared = SimpleNamespace(context={"feature_fields": ["x", "constant"], "folds": [fold],
                                        "validation_keys": fold["validation_keys"]},
        report={"targets": [{"observation_key": row["observation_key"], "status": "COMPLETE", "reason": None,
                             "value": 2.0, "actual_label_end_time": "2025-01-02T15:05:00+00:00"}
                            for row in validation]}, fold_rows=(training,), observations=validation)
    strategy = {"kind": "RIDGE", "name": "Constant column reference", "alpha": 2.0, "threshold": 0.0}
    predictions, models, metrics = research.candidate_predictions(prepared, research.parse_strategy_specs([strategy])[0], {})
    rows, _, quadratic = _quadratic_predictions(prepared, {"strategy": strategy, "predictions": predictions,
        "fold_models": models, "prediction_metrics": metrics})
    model = quadratic["fold_models"][0]["model"]
    assert model["input_transform"]["means"][1] == constant
    assert model["input_transform"]["scales"][1] == 0.0
    assert all(model["ridge_model"][field][index] == 0.0
               for field in ("means", "scales", "coefficients") for index in (1, 3, 4))
    # Symmetric TRAIN x and target=x leave one predictive direction. Its
    # closed-form shrinkage is n/(n+alpha)=6/8, regardless of VALIDATION's
    # changed constant input; no model fitted by this test supplies the oracle.
    assert [row["scores"]["QUADRATIC_RIDGE"] for row in rows] == pytest.approx([1.5, 1.5])


def test_quadratic_ridge_single_constant_is_training_mean_and_finite_overflow_fails():
    from market_vault.research.intraday_quadratic_ridge import _expanded_observation, _quadratic_predictions, _quadratic_terms
    rows, _, quadratic = _quadratic_predictions(*_quadratic_case(("constant",)))
    assert quadratic["expanded_width"] == 2
    assert all(row["scores"]["QUADRATIC_RIDGE"] == row["scores"]["TRAIN_MEAN"] for row in rows)
    assert all(record["model"]["ridge_model"]["means"] == record["model"]["ridge_model"]["scales"] == [0.0, 0.0]
               for record in quadratic["fold_models"])
    terms = _quadratic_terms(("x",))
    with pytest.raises(ValueError, match="normalization is not finite"):
        _expanded_observation({"features": {"x": 1e308}}, ("x",), (-1e308,), (1.0,), terms)
    with pytest.raises(ValueError, match="generated term is not finite"):
        _expanded_observation({"features": {"x": 1e200}}, ("x",), (0.0,), (1.0,), terms)
    prepared, candidate = _quadratic_case()
    prepared.observations[0]["features"]["x"] = 1e200
    with pytest.raises(ValueError, match="generated term is not finite"):
        _quadratic_predictions(prepared, candidate)
    prepared, candidate = _quadratic_case()
    prepared.fold_rows[0][0][0]["features"]["x"] = 1e200
    with pytest.raises(ArithmeticError):
        _quadratic_predictions(prepared, candidate)


def test_quadratic_ridge_future_data_changes_only_later_training_and_test_is_excluded():
    from market_vault.research.intraday_quadratic_ridge import _quadratic_predictions
    original = _quadratic_predictions(*_quadratic_case())
    future = _quadratic_predictions(*_quadratic_case(future_target_shift=.6))
    future_features = _quadratic_predictions(*_quadratic_case(future_feature_shift=10.0))
    assert original == _quadratic_predictions(*_quadratic_case(test_shift=float("inf")))
    for changed in (future, future_features):
        assert original[2]["fold_models"][0] == changed[2]["fold_models"][0]
        assert original[2]["fold_models"][1] != changed[2]["fold_models"][1]
    assert original[2]["fold_models"][1]["model"]["input_transform"] == future[2]["fold_models"][1]["model"]["input_transform"]
    assert original[2]["fold_models"][1]["model"]["input_transform"] != future_features[2]["fold_models"][1]["model"]["input_transform"]
    assert [row["scores"] for row in original[0][:4]] == [row["scores"] for row in future[0][:4]]
    assert original[1][0]["forecasts"] != future[1][0]["forecasts"]


def test_quadratic_ridge_dimension_and_selected_admission_precede_q5_io(research_case, monkeypatch):
    from market_vault.research.intraday_experiment import create_intraday_experiment
    from market_vault.research.intraday_prediction_quality import analyze_intraday_prediction_quality
    from market_vault.research.intraday_quadratic_ridge import analyze_intraday_quadratic_ridge
    from test_intraday_experiment import _comparison_snapshot
    data, plan, report = research_case
    snapshot = create_intraday_experiment(plan=plan, report=report)
    root = snapshot.as_dict()
    fields = ["sma_5", *[name for name in data.as_dict()["report"]["feature_names"] if name != "sma_5"][:6]]
    assert len(fields) == 7
    root["plan"]["feature_fields"] = root["report"]["context"]["feature_fields"] = fields
    for group in root["report"]["groups"]:
        for candidate in group["results"]:
            for record in candidate["fold_models"]:
                model = record["model"]
                model["feature_fields"] = fields
                for key in ("means", "scales", "coefficients"):
                    model[key] += [0.0] * 6
    # A structurally valid, re-signed oversized saved projection must be rejected
    # before source access; no source-reconstruction proof is invented here.
    oversized = _comparison_snapshot(root)
    calls = []
    def blocked(*args, **kwargs):
        calls.append(True)
        raise RuntimeError("Q5 was requested")
    monkeypatch.setattr(research, "load_intraday_dataset", blocked)
    with pytest.raises(ValueError, match="at most 6 Features"):
        analyze_intraday_quadratic_ridge(oversized, candidate_index=2)
    for options in ({"candidate_index": True}, {"cost_index": -1}, {"candidate_index": 0},
                    {"cost_index": 1}, {"candidate_index": 3}, {"intraday_data_file": False}):
        with pytest.raises(ValueError):
            analyze_intraday_quadratic_ridge(snapshot, **options)
    assert calls == []
    # The new comparator's engineering bound does not restrict Q21's existing
    # selected-Ridge path: a wider request still advances to its ordinary loader.
    with pytest.raises(RuntimeError, match="Q5 was requested"):
        analyze_intraday_prediction_quality(oversized, candidate_index=2)
    assert calls == [True]


def test_quadratic_ridge_real_nonfirst_same_source_pairing_and_installed_cli(research_case, tmp_path, monkeypatch, capsys):
    import json
    import os
    from pathlib import Path
    import subprocess
    import sysconfig
    from market_vault import cli
    from market_vault.research.intraday_feature_ablation import analyze_intraday_feature_ablation
    from market_vault.research.intraday_prediction_quality import analyze_intraday_prediction_quality
    from market_vault.research.intraday_quadratic_ridge import analyze_intraday_quadratic_ridge
    from market_vault.research.intraday_experiment import create_intraday_experiment
    from market_vault.research.strategy_experiment import write_strategy_experiment
    data, comparison, _ = research_case
    plan = diagnostic_plan(deepcopy(comparison))
    plan["comparison_plan"]["feature_fields"] = ["return_2", "sma_5", "candle_body"]
    plan["parameter_axes"] = [{"parameter": "alpha", "values": [1, 10]}]
    normalized, children, coordinates = research.expand_intraday_plan(plan, recorded=True)
    prepared = research._prepare_intraday_research(children[0], data=data)
    saved = research._evaluate_intraday_research(normalized, children, coordinates, prepared)
    snapshot = create_intraday_experiment(plan=normalized, report=saved, name="固定二次基函数")
    path, relocated = tmp_path / "development.json", tmp_path / "relocated-intraday.json"
    write_strategy_experiment(snapshot, path=path)
    relocated.write_bytes(data.path.read_bytes())
    before = path.read_bytes(), data.path.read_bytes(), relocated.read_bytes()
    calls, loader, fitter = {"loads": 0, "fits": []}, research.load_intraday_dataset, research.fit_ridge_rows
    def loaded(*args, **kwargs):
        calls["loads"] += 1
        return loader(*args, **kwargs)
    def fitted(training, observations, features, alpha, *, boundary):
        calls["fits"].append((list(features), alpha))
        return fitter(training, observations, features, alpha, boundary=boundary)
    monkeypatch.setattr(research, "load_intraday_dataset", loaded)
    monkeypatch.setattr(research, "fit_ridge_rows", fitted)
    monkeypatch.setattr(research, "run_intraday_execution", lambda *a, **kw: pytest.fail("quadratic analysis reran Q6"))
    monkeypatch.setattr(cli, "load_settings", lambda *a, **kw: pytest.fail("quadratic analysis loaded settings"))
    common = {"cost_index": 1, "candidate_index": 1}
    quality = analyze_intraday_prediction_quality(snapshot, **common)
    assert calls["loads"] == 1 and len(calls["fits"]) == 2
    ablation = analyze_intraday_feature_ablation(snapshot, **common)
    assert calls["loads"] == 2 and len(calls["fits"]) == 10
    result = analyze_intraday_quadratic_ridge(snapshot, **common)
    assert calls["loads"] == 3 and len(calls["fits"]) == 14
    assert calls["fits"][-4:] == [(["return_2", "sma_5", "candle_body"], 10.0)] * 2 + [
        ([term["name"] for term in result["quadratic"]["terms"]], 10.0)] * 2
    candidate = saved["groups"][1]["results"][1]
    assert result["candidate_id"] == quality["candidate_id"] == ablation["candidate_id"] == candidate["candidate_id"]
    assert result["context"] == quality["context"] == ablation["context"] == saved["context"]
    assert result["baseline"] == {"strategy": candidate["strategy"], "fold_models": candidate["fold_models"]}
    assert result["evidence"]["execution_replayed"] is False
    assert result["method"]["forecast_order"] == ["RIDGE", "ZERO", "TRAIN_MEAN", "QUADRATIC_RIDGE"]
    assert result["method"]["paired_error_difference"] == "QUADRATIC_MINUS_LINEAR_RIDGE"
    assert result["quadratic"]["expanded_width"] == 9
    assert result["sample"] == quality["sample"] == ablation["sample"]
    assert result["sample"]["prediction_count"] == 740 and result["sample"]["complete_target_count"] == 710
    assert [row["observation_key"] for row in result["predictions"]] == saved["context"]["validation_keys"]
    for row, linear, omitted in zip(result["predictions"], quality["predictions"], ablation["predictions"], strict=True):
        assert {key: value for key, value in row.items() if key not in ("quadratic_model_id", "scores")} == {
            key: value for key, value in linear.items() if key != "scores"}
        assert {key: row["scores"][key] for key in linear["scores"]} == linear["scores"] == {
            key: omitted["scores"][key] for key in linear["scores"]}
        assert list(row["scores"]) == result["method"]["forecast_order"]
        assert row["trading_day"] not in saved["context"]["split"]["TEST"]
    assert result["quadratic_ridge_id"] == research.digest({key: value for key, value in result.items() if key != "quadratic_ridge_id"})
    for summary in [result, *result["folds"]]:
        paired = [row for row in result["predictions"] if row["target_status"] == "COMPLETE"
                  and ("fold_id" not in summary or row["fold_id"] == summary["fold_id"])]
        def error(name, squared=False):
            return math.fsum((row["scores"][name] - row["target_value"]) ** 2 if squared
                             else abs(row["scores"][name] - row["target_value"]) for row in paired) / len(paired)
        change = summary["paired_error_changes"][0]
        assert change["forecast"] == "QUADRATIC_RIDGE"
        for name, expected in {"mae": error("QUADRATIC_RIDGE") - error("RIDGE"),
                               "mse": error("QUADRATIC_RIDGE", True) - error("RIDGE", True),
                               "rmse": math.sqrt(error("QUADRATIC_RIDGE", True)) - math.sqrt(error("RIDGE", True))}.items():
            metric = change["metrics"][name]
            assert metric["value"] == pytest.approx(expected, rel=1e-8, abs=1e-20)
            assert metric["unit"] == ("SQUARED_RATIO" if name == "mse" else "RATIO") and metric["unavailable_reason"] is None
    console = Path(sysconfig.get_path("scripts")) / ("market-vault.exe" if os.name == "nt" else "market-vault")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"), "PYTHONIOENCODING": "cp1252:strict"}
    command = [str(console), "research-intraday-quadratic-ridge", "--experiment", str(path),
               "--cost-index", "1", "--candidate-index", "1", "--intraday-data", str(relocated)]
    process = subprocess.run(command, env=env, cwd=tmp_path, capture_output=True, check=False)
    assert process.returncode == 0 and not process.stderr and process.stdout.isascii()
    cli_result = json.loads(process.stdout)["report"]
    assert cli_result["forecasts"] == result["forecasts"] and cli_result["predictions"] == result["predictions"]
    assert cli_result["quadratic"] == result["quadratic"] and cli_result["paired_error_changes"] == result["paired_error_changes"]
    assert cli_result["source_locator"] == {"recorded": str(data.path), "used": str(relocated.resolve()), "override_used": True}
    failed = subprocess.run(command[:-1] + [str(tmp_path / "missing-q5.json")], env=env, cwd=tmp_path, capture_output=True, check=False)
    assert failed.returncode == 1 and not failed.stdout and json.loads(failed.stderr)["status"] == "FAILED"
    assert cli.main(["research-intraday-quadratic-ridge", "--experiment", str(tmp_path / "missing.json"),
                     "--candidate-index", "-1"]) == 1
    error = capsys.readouterr()
    assert not error.out and json.loads(error.err)["error"] == "candidate_index must be a nonnegative integer"
    assert (path.read_bytes(), data.path.read_bytes(), relocated.read_bytes()) == before
