from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from market_vault import moomoo_sdk
from market_vault import moomoo_simulation_qualifier as qualifier
from market_vault.moomoo_simulation import SimulationAccountSession, SimulationError
from market_vault.moomoo_simulation_evidence import build_evidence
from market_vault.moomoo_simulation_orders import PaperJournal
from market_vault.moomoo_simulation_recovery import PaperRecovery


@pytest.fixture
def funds_broker(monkeypatch):
    state = SimpleNamespace(calls=[], contexts=[], environment="SIMULATE", account_id=200,
                            funds={"cash": 987654.32, "currency": "USD"})

    class Context:
        def __init__(self, **kwargs):
            assert kwargs == dict(filter_trdmarket="US", host="127.0.0.1", port=11111,
                                  security_firm="NONE")
            self.closed = False
            state.contexts.append(self)

        def close(self):
            self.closed = True

        def get_acc_list(self):
            return 0, pd.DataFrame([dict(acc_id=state.account_id, trd_env=state.environment,
                                        sim_acc_type="STOCK_AND_OPTION", trdmarket_auth=["US"],
                                        acc_status="ACTIVE")])

        def record(self, method, kwargs):
            assert kwargs["trd_env"] == "SIMULATE" and kwargs["acc_id"] == state.account_id
            assert "acc_index" not in kwargs
            state.calls.append(method)

        def order_list_query(self, **kwargs):
            self.record("orders", kwargs)
            return 0, pd.DataFrame(columns=["order_id", "order_status", "remark"])

        def position_list_query(self, **kwargs):
            self.record("positions", kwargs)
            return 0, pd.DataFrame(columns=["code", "qty", "position_side"])

        def accinfo_query(self, **kwargs):
            self.record("funds", kwargs)
            assert kwargs["currency"] == "USD" and kwargs["refresh_cache"] is True
            return 0, pd.DataFrame([{**state.funds, "private_key": "DO_NOT_EXPORT"}])

        def place_order(self, **kwargs):
            raise AssertionError("Prepare/diagnostics must not place")

        def modify_order(self, **kwargs):
            raise AssertionError("Prepare/diagnostics must not cancel")

    sdk = SimpleNamespace(OpenQuoteContext=object, OpenSecTradeContext=Context, RET_OK=0,
                          TrdEnv=SimpleNamespace(SIMULATE="SIMULATE", REAL="REAL"),
                          TrdMarket=SimpleNamespace(US="US"), SecurityFirm=SimpleNamespace(NONE="NONE"),
                          Currency=SimpleNamespace(USD="USD"), __version__="10.09.6908")
    monkeypatch.setattr(moomoo_sdk, "_import_sdk_module", lambda: (sdk, "moomoo"))
    return state


def prepare(tmp_path, name="run", extra=()):
    path, output = tmp_path / (name + ".sqlite"), tmp_path / (name + ".json")
    code = qualifier.main(["prepare", "--journal", str(path), "--output", str(output), *extra])
    return code, path, json.loads(output.read_text())


def diagnostic(report):
    return [e for e in report["evidence"]["events"] if e["kind"] == "FUNDS_RESPONSE"][-1]


def test_prepare_cash_failure_explains_only_shape(funds_broker, tmp_path):
    funds_broker.funds.update(currency="NONE", us_cash="N/A")
    code, path, report = prepare(tmp_path)
    assert code == 1 and report["error_code"] == "CASH_CURRENCY_NOT_USD"
    item = diagnostic(report)
    assert item["requested_currency"] == "USD" and item["display_currency"] == "NONE"
    assert item["cash_state"] == "FINITE" and item["us_cash_state"] == "UNAVAILABLE"
    assert item["response_shape"] == "SINGLE_ROW"
    assert report["evidence"]["stopped"] and not report["evidence"]["intentions"]
    with PaperJournal(path) as journal:
        assert not any(e["kind"] == "ACCOUNT_BASELINE" for e in journal.events())
    assert all(c.closed for c in funds_broker.contexts)
    assert "DO_NOT_EXPORT" not in json.dumps(report) and "987654.32" not in json.dumps(report)


def test_successful_prepare_preserves_previous_behavior(funds_broker, tmp_path):
    code, _, report = prepare(tmp_path)
    assert code == 0 and report["result"] == "PREPARED"
    assert diagnostic(report)["us_cash_state"] == "MISSING"
    assert not report["evidence"]["stopped"] and not report["new_orders_authorized"]
    assert set(funds_broker.calls) == {"orders", "positions", "funds"}


@pytest.mark.parametrize("value,expected", [(0, "FINITE"), (None, "UNAVAILABLE"),
                                           ("N/A", "UNAVAILABLE"), (float("nan"), "INVALID"),
                                           (True, "INVALID"), ({"secret": "DO_NOT_EXPORT"}, "INVALID")])
def test_funds_field_classification_does_not_export_values(funds_broker, tmp_path, value, expected):
    funds_broker.funds.update(currency="NONE", us_cash=value)
    _, _, report = prepare(tmp_path)
    assert diagnostic(report)["us_cash_state"] == expected
    assert "DO_NOT_EXPORT" not in json.dumps(report)


def test_export_rechecks_diagnostic_allowlist_and_preserves_source(tmp_path):
    path = tmp_path / "private.sqlite"
    with PaperJournal.create(path, 200) as journal:
        journal.append("FUNDS_RESPONSE", None, requested_currency="USD", display_currency="DO_NOT_EXPORT",
                       cash_state="FINITE", us_cash_state=["DO_NOT_EXPORT"], response_shape="SINGLE_ROW",
                       cash=987654.32, account_id="DO_NOT_EXPORT")
    before = path.read_bytes()
    report = build_evidence(path)
    item = diagnostic({"evidence": report})
    assert item["display_currency"] == item["us_cash_state"] == "UNRECOGNIZED"
    assert "987654.32" not in json.dumps(report) and "DO_NOT_EXPORT" not in json.dumps(report)
    assert path.read_bytes() == before


def test_failed_funds_read_after_reconciliation_is_later_activity(funds_broker, tmp_path):
    code, path, _ = prepare(tmp_path)
    assert code == 0
    funds_broker.funds["currency"] = "NONE"
    with PaperJournal(path) as journal, SimulationAccountSession(account_id=200) as session:
        with pytest.raises(SimulationError, match="CASH_CURRENCY_NOT_USD"):
            PaperRecovery(session, journal).account_snapshot()
    report = build_evidence(path)
    assert report["observation_summary"]["last_reconciliation"]["subsequent_activity_recorded"]
