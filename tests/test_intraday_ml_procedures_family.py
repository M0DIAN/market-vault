"""Complete procedure-family integration and independent centered-max oracles."""

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

from market_vault.research import intraday_family_bounds as bounds
from market_vault.research import intraday_inner_selection as inner
from market_vault.research import intraday_joint_selection as joint
from market_vault.research import intraday_procedure_family as family
from market_vault.research import intraday_research as research
from market_vault.research import intraday_return_uncertainty as uncertainty
from market_vault.research import intraday_threshold_selection as threshold
from market_vault.research.intraday_data import digest
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.strategy_experiment import StrategyExperiment, write_strategy_experiment
from test_intraday_ml_procedures_comparison import _no_recompute, reseal_procedure_benchmark


ROOT = Path(__file__).resolve().parents[1]


def _studies(case):
    return tuple(case.studies[name][0] for name in ("q25", "q31", "q36"))


def _cash_values(account):
    return [float(Fraction(row["cash_close"]) / Fraction(row["cash_open"]) - 1)
            for row in account["execution"]["daily"]]


def _oracle_values(case):
    fixed = _cash_values(case.source.as_dict()["report"]["groups"][0]["results"][0])
    procedures = {role: _cash_values(snapshot.as_dict()["report"]["selected_account"])
                  for role, snapshot in zip(family.FAMILY_ROLES, _studies(case), strict=True)}
    excess = {role: [actual - reference for actual, reference in zip(values, fixed, strict=True)]
              for role, values in procedures.items()}
    return fixed, procedures, excess


def test_real_complete_family_cash_oracle_evidence_and_no_recomputation(procedure_comparison_case, monkeypatch):
    case = procedure_comparison_case
    snapshots = _studies(case)
    fixed, procedures, excess = _oracle_values(case)
    source = case.source.as_dict()
    cash_days = {day["trading_day"] for day in snapshots[1].as_dict()["report"]["selected_account"]["execution"]["daily"]
                 if day["trade_count"] == 0}
    original = {path: path.read_bytes() for _, path in case.studies.values()}
    _no_recompute(monkeypatch)
    calls, decode = [], StrategyExperiment.as_dict
    def decoded(snapshot):
        calls.append(snapshot)
        return decode(snapshot)
    monkeypatch.setattr(StrategyExperiment, "as_dict", decoded)
    report = family.analyze_intraday_procedure_family(snapshots)
    assert calls == list(snapshots)
    assert report["status"] == "AVAILABLE" and report["basis"]["matches"]
    assert report["family_size"] == 3 and report["family_scope"] == "DECLARED_THREE_PROCEDURES_ONLY"
    assert report["historical_search_coverage"] == "UNKNOWN"
    assert report["sample"]["sample_count"] == 100
    assert report["sampling"]["replications"] == 5000 and report["sampling"]["seed"] == 0
    assert report["sampling"]["block_days"] == 5 and "interval_method" not in report["sampling"]
    assert report["sampling"]["bound_method"] == "SINGLE_STEP_UNSTUDENTIZED_CENTERED_MAX"
    assert report["sampling"]["bound_type"] == "ONE_SIDED_LOWER"
    assert report["family_inference"]["status"] == "AVAILABLE"
    assert [row["role"] for row in report["members"]] == ["Q25", "Q31", "Q36"]
    assert [row["member_index"] for row in report["statistics"]] == [0, 1, 2]
    assert all("candidate_index" not in row for row in report["statistics"])
    assert report["reference"]["account"] == source["report"]["groups"][0]["results"][0]
    assert report["reference"]["candidate_id"] == report["source_selection"]["candidate_id"]
    assert report["benchmark"] == source["report"]["groups"][0]["benchmark"]
    assert all(row["unavailable_reason"] is None for row in report["shared_account_checks"])
    assert not any(report["evidence"][key] for key in ("source_reconstructed", "models_refitted", "execution_replayed"))
    for row in report["statistics"]:
        values = excess[row["role"]]
        assert row["unit"] == "RATIO" and row["sample_count"] == 100
        assert row["mean_excess"] == pytest.approx(math.fsum(values) / len(values), abs=1e-15)
        assert row["lower"] == pytest.approx(row["mean_excess"] - report["family_inference"]["deduction"], abs=1e-15)
    assert [row["trading_day"] for row in report["daily"]] == report["context"]["evaluated_days"]
    assert cash_days
    assert all(day["procedure_returns"]["Q31"] == 0 and day["values"]["Q31"] == -day["fixed_reference_return"]
               for day in report["daily"] if day["trading_day"] in cash_days)
    assert [row["fixed_reference_return"] for row in report["daily"]] == pytest.approx(fixed, abs=1e-15)
    for role in family.FAMILY_ROLES:
        assert [row["procedure_returns"][role] for row in report["daily"]] == pytest.approx(procedures[role], abs=1e-15)
        assert [row["values"][role] for row in report["daily"]] == pytest.approx(excess[role], abs=1e-15)
    assert report["family_bounds_id"] == digest({key: value for key, value in report.items() if key != "family_bounds_id"})
    assert all(path.read_bytes() == content for path, content in original.items())


def test_independent_joint_max_quantile_and_canonical_reordering(procedure_comparison_case, monkeypatch):
    case = procedure_comparison_case
    snapshots = _studies(case)
    _, _, excess = _oracle_values(case)
    _no_recompute(monkeypatch)
    draws = []
    def indices(count, block_days, rng):
        assert count == 100 and block_days == 5
        day = len(draws) % 100
        draws.append(day)
        return [day] * count
    monkeypatch.setattr(bounds, "_stationary_indices", indices)
    report = family.analyze_intraday_procedure_family(snapshots, replications=1000)
    assert draws == list(range(100)) * 10
    means = {role: math.fsum(column) / 100 for role, column in excess.items()}
    # Every controlled draw repeats one original date across all three
    # columns. Independent per-column draws cannot produce this joint oracle.
    maxima = sorted(max(excess[role][day] - means[role] for role in family.FAMILY_ROLES)
                    for day in range(100) for _ in range(10))
    deduction = max(0.0, maxima[949] * .95 + maxima[950] * .05)
    assert report["family_inference"]["deduction"] == pytest.approx(deduction, abs=1e-15)
    for row in report["statistics"]:
        assert row["lower"] == pytest.approx(means[row["role"]] - deduction, abs=1e-15)
    draws.clear()
    other = family.analyze_intraday_procedure_family([snapshots[2], snapshots[0], snapshots[1]], replications=1000)
    assert len(draws) == 1000 and other == report


def test_exact_family_and_parameter_validation_precede_decode(procedure_comparison_case, monkeypatch):
    snapshots = _studies(procedure_comparison_case)
    with monkeypatch.context() as patch:
        patch.setattr(StrategyExperiment, "as_dict", lambda *a: pytest.fail("invalid input was decoded"))
        for bad in (None, snapshots[:2], (*snapshots, snapshots[0]), (snapshots[0], object(), snapshots[2])):
            with pytest.raises(ValueError, match="three|immutable"):
                family.analyze_intraday_procedure_family(bad)
        for options in ({"block_days": 1}, {"replications": 999}, {"seed": True}):
            with pytest.raises(ValueError):
                family.analyze_intraday_procedure_family(snapshots, **options)
    with pytest.raises(ValueError, match="exactly once"):
        family.analyze_intraday_procedure_family((snapshots[0], snapshots[0], snapshots[2]))
    with pytest.raises(ValueError, match="explicit saved"):
        family.analyze_intraday_procedure_family((snapshots[0], snapshots[1], procedure_comparison_case.source))


def test_hidden_source_reference_basis_and_shared_account_cannot_form_subfamily(procedure_comparison_case, monkeypatch):
    snapshots = _studies(procedure_comparison_case)
    _no_recompute(monkeypatch)
    def price(execution, candidate):
        execution["ledger"][0]["mark_price"] += 1
    changed = reseal_procedure_benchmark(snapshots[2], price)
    with pytest.raises(ValueError, match="same complete ordinary source"):
        family.analyze_intraday_procedure_family((*snapshots[:2], changed))
    # Verify the separate captured-reference boundary through the public
    # family action, without inventing another legal candidate in this source.
    original = family._procedure
    altered_view = original(snapshots[2])
    altered_view["selection"]["candidate_id"] = "f" * 64
    with monkeypatch.context() as patch:
        patch.setattr(family, "_procedure", lambda snapshot: altered_view if snapshot is snapshots[2] else original(snapshot))
        with pytest.raises(ValueError, match="same original cost/candidate"):
            family.analyze_intraday_procedure_family(snapshots)
    def cash(execution, candidate):
        execution["trades"][0]["commission_total"] += .01
    for change, expected in ((price, "BASIS_MISMATCH"), (cash, "SHARED_ACCOUNT_UNAVAILABLE")):
        altered = [reseal_procedure_benchmark(snapshot, change) for snapshot in snapshots]
        report = family.analyze_intraday_procedure_family(altered, replications=1000)
        assert report["status"] == "UNAVAILABLE" and report["unavailable_reason"] == expected
        assert report["family_inference"]["status"] == "UNAVAILABLE"
        assert len(report["members"]) == len(report["statistics"]) == 3
        assert all(row["mean_excess"] is row["lower"] is None for row in report["statistics"])
        assert all(all(value is None for value in row["values"].values()) for row in report["daily"])


def test_small_matrix_constant_invalid_and_short_family_gates(monkeypatch):
    columns = [(0.0,) * 100, tuple((day % 5 - 2) / 100 for day in range(100)),
               tuple((day % 7 - 3) / 100 for day in range(100))]
    def rows(values):
        return [{"role": role, "member_index": index, "mean_excess": None if column is None else math.fsum(column) / len(column),
                 "mean_unavailable_reason": "RECORDED_CASH_RECONCILIATION_FAILED" if column is None else None,
                 "bound_unavailable_reason": None, "lower": None, "detail": None}
                for index, (role, column) in enumerate(zip(family.FAMILY_ROLES, values, strict=True))]
    sample = {"sample_count": 100, "is_contiguous": True}
    sampling = uncertainty._sampling(100, replications=1000)
    counter = []
    def indices(count, block_days, rng):
        day = len(counter) % count
        counter.append(day)
        return [day] * count
    monkeypatch.setattr(bounds, "_stationary_indices", indices)
    statistics = rows(columns)
    inference = family._family_inference(statistics, columns, sample, sampling, {"matches": True})
    assert inference["status"] == "AVAILABLE" and len(counter) == 1000
    assert statistics[0]["mean_excess"] == 0 and statistics[0]["lower"] is None
    assert statistics[0]["bound_unavailable_reason"] == "ZERO_SAMPLE_VARIATION"
    assert all(row["lower"] is not None for row in statistics[1:])
    invalid = [columns[0], None, columns[2]]
    statistics = rows(invalid)
    inference = family._family_inference(statistics, invalid, sample, sampling, {"matches": True})
    assert inference["reason"] == "FAMILY_MEMBER_UNAVAILABLE" and len(counter) == 1000
    assert "procedure Q31:" in inference["detail"] and "candidate" not in inference["detail"]
    assert all(row["lower"] is None for row in statistics)
    short = [column[:20] for column in columns]
    statistics = rows(short)
    inference = family._family_inference(statistics, short, {"sample_count": 20, "is_contiguous": True},
                                         uncertainty._sampling(20, replications=1000), {"matches": True})
    assert inference["reason"] == "INSUFFICIENT_DAILY_RETURNS"
    assert all(row["mean_excess"] is not None and row["lower"] is None for row in statistics)


def test_public_expected_block_gate_and_unavailable_study_keep_complete_family(procedure_comparison_case, tmp_path, monkeypatch):
    case = procedure_comparison_case
    with monkeypatch.context() as patch:
        _no_recompute(patch)
        report = family.analyze_intraday_procedure_family(_studies(case), block_days=100, replications=1000)
    assert report["status"] == "AVAILABLE" and len(report["daily"]) == 100
    assert report["family_inference"]["reason"] == "INSUFFICIENT_EXPECTED_BLOCKS"
    assert all(row["mean_excess"] is not None and row["lower"] is None for row in report["statistics"])
    # Reuse the existing Q5 data, restricting DEV to 25 days. The first
    # ten-day history cannot support any declared inner procedure; no second
    # 100-day study or new market-data fixture is built for this branch.
    days = [row["trading_day"] for row in case.data.as_dict()["report"]["sessions"]]
    plan = deepcopy(case.plan)
    plan["walk_forward"] = {"minimum_train_days": 10, "validation_days": 5, "step_days": 5}
    plan["split"]["train_end_day"] = days[9]
    plan["split"]["validation_end_day"] = days[24]
    with monkeypatch.context() as setup:
        # Q5 source verification is covered by the shared real fixture. Its
        # already admitted identical data can serve these short setup fits;
        # the Q40 action below must not request that data at all.
        def admitted_data(path):
            assert Path(path).resolve() == case.data.path.resolve()
            return case.data
        setup.setattr(research, "load_intraday_dataset", admitted_data)
        source = create_intraday_experiment(plan=plan, report=research.run_intraday_research(plan))
        path = write_strategy_experiment(source, path=tmp_path / "short-history.json").path
        args = dict(expected_experiment_id=source.experiment_id, cost_index=0, candidate_index=0,
                    expected_candidate_id=source.as_dict()["report"]["groups"][0]["results"][0]["candidate_id"])
        studies = [run(path, **args) for run in (inner.run_intraday_inner_selection,
                   threshold.run_intraday_threshold_selection, joint.run_intraday_joint_selection)]
    _no_recompute(monkeypatch)
    monkeypatch.setattr(family, "_daily_account", lambda *a: pytest.fail("unavailable source computed partial accounts"))
    report = family.analyze_intraday_procedure_family(studies)
    assert report["status"] == "UNAVAILABLE" and report["unavailable_reason"] == "SOURCE_STUDY_UNAVAILABLE"
    assert len(report["members"]) == len(report["statistics"]) == len(report["unavailable_reasons"]) == 3
    assert report["daily"] == [] and report["sample"] is report["sampling"] is None
    assert all(row["mean_excess"] is row["lower"] is None for row in report["statistics"])
    assert report["family_inference"]["reason"] == "SOURCE_STUDY_UNAVAILABLE"


def test_cli_parameter_count_preflight_and_settings_independent_three_file_action(procedure_comparison_case, tmp_path, monkeypatch, capsys):
    from market_vault import intraday_procedure_family_cli as cli
    with monkeypatch.context() as patch:
        patch.setattr(cli, "load_strategy_experiment", lambda *a: pytest.fail("invalid CLI input accessed a file"))
        for overrides in ({"study": ["missing"]}, {"study": ["missing"] * 4},
                          {"replications": 999}, {"block_days": 1}, {"seed": -1}):
            args = SimpleNamespace(**{**dict(study=["missing"] * 3, replications=1000, block_days=None, seed=0), **overrides})
            assert cli.research_intraday_procedure_family_main(args) == 1
            output = capsys.readouterr()
            assert not output.out and json.loads(output.err)["status"] == "FAILED"
    case = procedure_comparison_case
    paths = [case.studies[name][1] for name in ("q36", "q25", "q31")]
    original = {path: path.read_bytes() for path in paths}
    command = [sys.executable, "-c", "from market_vault.cli import main; raise SystemExit(main())",
               "--settings", str(tmp_path / "absent.yaml"), "research-intraday-procedure-family",
               *[part for path in paths for part in ("--study", str(path))], "--replications", "1000"]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "cp1252:strict"}
    run = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr
    output = json.loads(run.stdout)
    assert run.stdout.isascii() and not run.stderr
    assert output["status"] == "SUCCESS" and output["result_schema_version"] == family.INTRADAY_PROCEDURE_FAMILY_VERSION
    report = output["report"]
    assert report["status"] == "AVAILABLE" and report["parameters"]["replications"] == 1000
    assert [row["role"] for row in report["members"]] == ["Q25", "Q31", "Q36"]
    assert report["reference"]["candidate_id"] == report["source_selection"]["candidate_id"]
    assert all(path.read_bytes() == content for path, content in original.items())
