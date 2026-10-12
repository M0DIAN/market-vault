"""Actual procedure roles, independent risk arithmetic and recorded-only CLI."""

from datetime import datetime
from fractions import Fraction
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from market_vault.research import intraday_procedure_risk_diagnostics as procedure
from market_vault.research.intraday_data import digest
from market_vault.research.intraday_risk_diagnostics import summarize_intraday_risk_diagnostics
from test_intraday_ml_procedures_comparison import _no_recompute, reseal_procedure_benchmark
from test_intraday_ml_procedures_stress import _short_study


ROOT = Path(__file__).resolve().parents[1]
ROLES = ("procedure", "fixed_reference", "benchmark")


def _cash_and_peak_oracle(execution, diagnostics, folds):
    """Use actual cash and exact rational ratios, not the saved risk metrics."""
    equities = [Fraction(execution["metrics"]["initial_cash"])]
    equities.extend(Fraction(point["equity"]) for point in execution["ledger"])
    peak, depths = equities[0], []
    for value in equities:
        peak = max(peak, value)
        depths.append(1 - value / peak)
    assert diagnostics["summary"]["maximum_drawdown"]["value"] == pytest.approx(float(max(depths)), abs=1e-14)
    for episode in diagnostics["drawdown_episodes"]:
        end = episode["recovery_time"] if episode["recovered"] else execution["ledger"][-1]["timestamp"]
        duration = (datetime.fromisoformat(end) - datetime.fromisoformat(episode["peak_time"])).total_seconds() / 60
        assert episode["duration_minutes"] == duration
        assert episode["depth"] == pytest.approx(float(1 - Fraction(episode["trough_equity"]) /
                                                       Fraction(episode["peak_equity"])), abs=1e-14)
    daily = {row["trading_day"]: row for row in execution["daily"]}
    contributions = {day: Fraction(row["cash_close"]) - Fraction(row["cash_open"]) for day, row in daily.items()}
    for name, sign in (("positive", 1), ("negative", -1)):
        values = sorted((abs(value) for value in contributions.values() if sign * value > 0), reverse=True)
        actual = diagnostics["cash_concentration"][name]
        assert actual["total_absolute_cash"] == pytest.approx(float(sum(values)), abs=1e-14)
        assert actual["top_1_share"] == (pytest.approx(float(values[0] / sum(values)), abs=1e-14) if values else None)
    for actual, fold in zip(diagnostics["fold_diagnostics"]["rows"], folds, strict=True):
        days = fold["validation_days"]
        assert actual["validation_days"] == days
        assert actual["cash_contribution"] == pytest.approx(float(sum(contributions[day] for day in days)), abs=1e-14)
        compound = Fraction(daily[days[-1]]["cash_close"]) / Fraction(daily[days[0]]["cash_open"]) - 1
        assert actual["compound_return"] == pytest.approx(float(compound), abs=1e-14)


@pytest.mark.parametrize("kind", ("q25", "q31", "q36"))
def test_real_three_roles_complete_support_direct_q12_and_independent_cash(procedure_comparison_case, monkeypatch, kind):
    case = procedure_comparison_case
    snapshot, path = case.studies[kind]
    before = path.read_bytes()
    root = snapshot.as_dict()
    saved, source = root["report"], root["report"]["source_experiment"]
    selection = root["plan"]["selection"]
    group = source["report"]["groups"][selection["cost_index"]]
    expected = {"procedure": saved["selected_account"],
                "fixed_reference": group["results"][selection["candidate_index"]], "benchmark": saved["benchmark"]}
    _no_recompute(monkeypatch)
    from market_vault.research import intraday_data, intraday_final_test
    monkeypatch.setattr(intraday_data, "load_intraday_dataset", lambda *a, **k: pytest.fail("Q52 read Q5"))
    for name in ("freeze_intraday_candidate", "run_intraday_final_test"):
        monkeypatch.setattr(intraday_final_test, name, lambda *a, **k: pytest.fail("Q52 entered Freeze/TEST"))
    report = procedure.analyze_intraday_procedure_risk_diagnostics(snapshot)
    assert report["status"] == "AVAILABLE" and report["basis"]["matches"]
    assert report["comparability"] == {"status": "AVAILABLE", "comparable": True, "unavailable_reason": None, "detail": None}
    assert report["account_availability"] == {"declared": 3, "available": 3, "unavailable": 0}
    assert tuple(report["accounts"]) == tuple(report["diagnostics"]) == ROLES
    assert report["accounts"] == expected
    assert report["source_selection"] == selection
    assert report["experiment_id"] == snapshot.experiment_id and report["ordinary_source_id"] == source["experiment_id"]
    assert report["context"] == source["report"]["context"]
    assert report["sample"]["evaluated_days"] == report["context"]["evaluated_days"]
    assert report["sample"]["account_counts"]["procedure"]["cash_only_day_count"] > 0
    assert report["accounts"]["benchmark"]["execution"]["policy"]["max_hold_bars"] == 13
    assert report["accounts"]["fixed_reference"]["execution"]["policy"]["max_hold_bars"] == 2
    assert report["evidence"] == {"scope": "RECORDED_LEDGER_DERIVATION", "source_reconstructed": False,
        "models_refitted": False, "decisions_reselected": False, "execution_replayed": False}
    for name, account in expected.items():
        diagnostic = report["diagnostics"][name]
        assert diagnostic["status"] == "AVAILABLE" and diagnostic["unavailable_reason"] is None
        assert diagnostic["report"] == summarize_intraday_risk_diagnostics(account["execution"], folds=report["context"]["folds"])
        assert diagnostic["report"]["execution_id"] == account["execution"]["execution_id"]
        _cash_and_peak_oracle(account["execution"], diagnostic["report"], report["context"]["folds"])
    field = "application" if kind == "q31" else "refit"
    for actual, recorded in zip(report["procedure"]["outer_folds"], saved["outer_folds"], strict=True):
        assert actual["selected_index"] == recorded["inner"]["selected_index"]
        assert actual["selected_recipe"] == recorded["inner"]["selected_recipe"]
        assert actual[field] == recorded[field]
    assert report["diagnostics_id"] == digest({key: value for key, value in report.items() if key != "diagnostics_id"})
    assert path.read_bytes() == before == snapshot.content


def test_basis_mismatch_preserves_independent_risk_but_cannot_claim_comparability(procedure_comparison_case, monkeypatch):
    def changed_price(execution, reference):
        assert execution["ledger"][0]["quantity"] == 0
        execution["ledger"][0]["mark_price"] += 1
    snapshot = reseal_procedure_benchmark(procedure_comparison_case.studies["q31"][0], changed_price)
    _no_recompute(monkeypatch)
    report = procedure.analyze_intraday_procedure_risk_diagnostics(snapshot)
    assert report["status"] == "PARTIAL" and report["unavailable_reason"] == "BASIS_MISMATCH"
    assert not report["basis"]["matches"] and "raw_prices" in report["basis"]["failed_checks"]
    assert report["comparability"]["status"] == "UNAVAILABLE" and not report["comparability"]["comparable"]
    assert report["account_availability"] == {"declared": 3, "available": 3, "unavailable": 0}
    assert all(item["status"] == "AVAILABLE" for item in report["diagnostics"].values())


def test_one_invalid_recorded_ledger_does_not_remove_other_roles(procedure_comparison_case, monkeypatch):
    def changed_cash(execution, reference):
        execution["ledger"][0]["cash"] += .01
    snapshot = reseal_procedure_benchmark(procedure_comparison_case.studies["q25"][0], changed_cash)
    _no_recompute(monkeypatch)
    report = procedure.analyze_intraday_procedure_risk_diagnostics(snapshot)
    assert report["basis"]["matches"] and report["status"] == "PARTIAL"
    assert report["unavailable_reason"] == "ACCOUNT_DIAGNOSTICS_UNAVAILABLE"
    assert not report["comparability"]["comparable"]
    assert report["account_availability"] == {"declared": 3, "available": 2, "unavailable": 1}
    failed = report["diagnostics"]["benchmark"]
    assert failed["status"] == "UNAVAILABLE" and failed["report"] is None
    assert failed["unavailable_reason"] == "RECORDED_LEDGER_RECONCILIATION_FAILED"
    assert all(report["diagnostics"][name]["status"] == "AVAILABLE" for name in ROLES[:2])


def test_unavailable_study_keeps_identity_reasons_and_no_invented_account(procedure_comparison_case, tmp_path, monkeypatch):
    snapshot, _, _ = _short_study(procedure_comparison_case, tmp_path, monkeypatch, kind="q31", minimum=14)
    saved = snapshot.as_dict()["report"]
    _no_recompute(monkeypatch)
    monkeypatch.setattr(procedure, "_account_basis", lambda *a, **k: pytest.fail("unavailable source has no complete basis"))
    monkeypatch.setattr(procedure, "_available", lambda *a, **k: pytest.fail("unavailable source cannot run account diagnosis"))
    report = procedure.analyze_intraday_procedure_risk_diagnostics(snapshot)
    assert report["status"] == "UNAVAILABLE" and report["unavailable_reason"] == "SOURCE_STUDY_UNAVAILABLE"
    assert report["experiment_id"] == snapshot.experiment_id
    assert report["source_unavailable_reasons"] == saved["unavailable_reasons"]
    assert report["source_unavailable_reasons"]
    assert report["accounts"]["procedure"] is report["sample"] is report["basis"] is None
    assert report["accounts"]["benchmark"] == saved["benchmark"]
    assert report["account_availability"] == {"declared": 3, "available": 0, "unavailable": 3}
    assert all(item["report"] is None for item in report["diagnostics"].values())
    assert not report["comparability"]["comparable"]
    with pytest.raises(ValueError, match="selection study"):
        procedure.analyze_intraday_procedure_risk_diagnostics(procedure_comparison_case.source)
    with pytest.raises(ValueError, match="immutable"):
        procedure.analyze_intraday_procedure_risk_diagnostics({})


def test_installed_cli_complete_report_without_settings_or_source_files(procedure_comparison_case, tmp_path):
    case = procedure_comparison_case
    snapshot, saved_path = case.studies["q36"]
    before = saved_path.read_bytes()
    isolated = tmp_path / "study.json"
    isolated.write_bytes(before)
    expected = procedure.analyze_intraday_procedure_risk_diagnostics(snapshot)
    launcher = str(Path(sys.executable).with_name("market-vault.exe" if os.name == "nt" else "market-vault"))
    command = [launcher, "--settings", str(tmp_path / "absent.yaml"),
               "research-intraday-procedure-risk-diagnostics", "--study"]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    missing = subprocess.run([*command, str(tmp_path / "missing.json")], cwd=tmp_path, env=env,
                             text=True, capture_output=True, timeout=30)
    assert missing.returncode == 1 and not missing.stdout
    assert json.loads(missing.stderr)["status"] == "FAILED"
    hidden = []
    try:
        # Only synthetic fixture paths move, and are restored immediately.
        # The actual installed launcher receives only a saved-study copy.
        for path in (case.path, case.data.path):
            moved = path.with_name(path.name + ".q52-hidden")
            path.rename(moved)
            hidden.append((moved, path))
        result = subprocess.run([*command, str(isolated)], cwd=tmp_path, env=env,
                                text=True, capture_output=True, timeout=120)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "SUCCESS"
        assert payload["result_schema_version"] == procedure.INTRADAY_PROCEDURE_RISK_DIAGNOSTICS_VERSION
        assert payload["report"] == expected
    finally:
        for moved, path in hidden:
            moved.rename(path)
    assert saved_path.read_bytes() == isolated.read_bytes() == before
