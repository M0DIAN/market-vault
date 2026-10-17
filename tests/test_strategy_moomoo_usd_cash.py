from __future__ import annotations

import json

import pytest

from market_vault.moomoo_simulation import SimulationAccountSession, SimulationError
from market_vault.moomoo_simulation_evidence import build_evidence
from market_vault.moomoo_simulation_orders import PaperJournal, number, utc_now
from market_vault.moomoo_simulation_recovery import PaperRecovery
from test_strategy_moomoo_funds_diagnostics import funds_broker, prepare, diagnostic


def test_prepare_uses_explicit_usd_even_without_display_currency(funds_broker, tmp_path):
    funds_broker.funds = {"us_cash": "4321.12", "currency": "NONE", "cash": "N/A"}
    code, path, report = prepare(tmp_path)
    assert code == 0 and report["result"] == "PREPARED"
    with PaperJournal(path) as journal:
        baseline = [e for e in journal.events() if e["kind"] == "ACCOUNT_BASELINE"][0]
        assert number(baseline["cash"]) == number("4321.12")
        assert baseline["cash_basis"] == "USD_CURRENCY_BALANCE"
    assert "4321.12" not in json.dumps(report)
    assert not report["evidence"]["intentions"] and not report["new_orders_authorized"]


def test_explicit_balance_changes_cannot_hide_behind_constant_display_cash(funds_broker, tmp_path):
    funds_broker.funds.update(us_cash="3456.78")
    code, path, _ = prepare(tmp_path)
    assert code == 0
    funds_broker.funds["us_cash"] = "3451.78"  # Display cash remains unchanged.
    with PaperJournal(path) as journal, SimulationAccountSession(account_id=200) as session:
        result = PaperRecovery(session, journal).reconcile()
        assert result["result"] == "BLOCKED"
        assert number(result["cash_residual_usd"]) == -5
        assert result["cash_basis"] == result["baseline_cash_basis"] == "USD_CURRENCY_BALANCE"
        with pytest.raises(SimulationError, match="RECONCILIATION_BLOCKED"):
            journal.require_running()
    assert build_evidence(path)["events"][-1]["error_code"] == "ACCOUNT_RESIDUAL_UNEXPLAINED"


def test_equal_amounts_with_different_bases_do_not_reconcile(funds_broker, tmp_path):
    code, path, _ = prepare(tmp_path)  # Legacy cash, explicitly USD.
    assert code == 0
    with PaperJournal(path) as journal:
        old = [e for e in journal.events() if e["kind"] == "ACCOUNT_BASELINE"][0]
    funds_broker.funds["us_cash"] = funds_broker.funds["cash"]
    with PaperJournal(path) as journal, SimulationAccountSession(account_id=200) as session:
        result = PaperRecovery(session, journal).reconcile()
        assert result["result"] == "BLOCKED" and result["error_code"] == "CASH_BASIS_CHANGED"
        assert "cash_residual_usd" not in result
        assert old == [e for e in journal.events() if e["kind"] == "ACCOUNT_BASELINE"][0]
    item = build_evidence(path)["events"][-1]
    assert item["cash_basis"] == "USD_CURRENCY_BALANCE"
    assert item["baseline_cash_basis"] == "LEGACY_DISPLAY_USD"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, {"secret": "DO_NOT_EXPORT"}])
def test_invalid_explicit_balance_never_falls_back_to_valid_legacy_cash(funds_broker, tmp_path, value):
    funds_broker.funds["us_cash"] = value
    code, _, report = prepare(tmp_path)
    assert code == 1 and report["error_code"] == "USD_CASH_INVALID"
    assert report["evidence"]["stopped"] and not report["evidence"]["intentions"]
    assert diagnostic(report)["us_cash_state"] == "INVALID"
    assert "DO_NOT_EXPORT" not in json.dumps(report)


@pytest.mark.parametrize("currency", ["NONE", "JPY", None])
def test_unavailable_usd_is_not_zero_or_inferred_from_request(funds_broker, tmp_path, currency):
    funds_broker.funds.update(us_cash="N/A", currency=currency)
    code, _, report = prepare(tmp_path)
    assert code == 1 and report["error_code"] == "CASH_CURRENCY_NOT_USD"
    assert not any(e["kind"] == "ACCOUNT_BASELINE" for e in report["evidence"]["events"])


def test_zero_explicit_cash_is_observed_not_missing_and_needs_no_legacy_fields(funds_broker, tmp_path):
    funds_broker.funds = {"us_cash": 0}
    code, path, report = prepare(tmp_path)
    assert code == 0
    with PaperJournal(path) as journal:
        baseline = [e for e in journal.events() if e["kind"] == "ACCOUNT_BASELINE"][0]
        assert number(baseline["cash"]) == 0 and baseline["cash_basis"] == "USD_CURRENCY_BALANCE"
    assert diagnostic(report)["cash_state"] == diagnostic(report)["display_currency"] == "MISSING"


def test_original_v1_baseline_retains_its_legacy_basis_without_migration(funds_broker, tmp_path):
    path = tmp_path / "old.sqlite"
    stamp = utc_now().isoformat()
    with PaperJournal.create(path, 200) as journal:
        journal.append("ACCOUNT_BASELINE", None, started_at_utc=stamp, finished_at_utc=stamp,
                       positions={}, cash=str(funds_broker.funds["cash"]), currency="USD",
                       atomic_snapshot=False, fees="NOT_OBSERVED", cash_flows="NOT_OBSERVED")
        original = journal.events()[0]
    with PaperJournal(path) as journal, SimulationAccountSession(account_id=200) as session:
        result = PaperRecovery(session, journal).reconcile()
        assert result["result"] == "OBSERVATIONS_MATCH"
        assert result["baseline_cash_basis"] == "LEGACY_DISPLAY_USD"
        assert journal.events()[0] == original and "cash_basis" not in journal.events()[0]


def test_missing_usd_and_unusable_legacy_cash_stays_stopped(funds_broker, tmp_path):
    funds_broker.funds.update(cash="N/A", us_cash=None)
    code, _, report = prepare(tmp_path)
    assert code == 1 and report["error_code"] == "USD_CASH_UNAVAILABLE"
    assert report["evidence"]["stopped"]


@pytest.mark.parametrize("basis", [None, "UNRECOGNIZED_BASIS"])
def test_explicit_unknown_basis_is_not_treated_as_original_v1(funds_broker, tmp_path, basis):
    path = tmp_path / "unverified.sqlite"
    stamp = utc_now().isoformat()
    with PaperJournal.create(path, 200) as journal, SimulationAccountSession(account_id=200) as session:
        journal.append("ACCOUNT_BASELINE", None, started_at_utc=stamp, finished_at_utc=stamp,
                       positions={}, cash=str(funds_broker.funds["cash"]), currency="USD", cash_basis=basis)
        result = PaperRecovery(session, journal).reconcile()
        assert result["result"] == "BLOCKED" and result["error_code"] == "CASH_BASIS_UNVERIFIED"
        assert "cash_residual_usd" not in result
    report = build_evidence(path)
    assert report["events"][0]["cash_basis"] == "UNVERIFIED"
