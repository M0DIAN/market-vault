from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from market_vault import moomoo_simulation as sim


def account(identifier=200, **changes):
    row = dict(acc_id=identifier, trd_env="SIMULATE", sim_acc_type="STOCK_AND_OPTION",
               trdmarket_auth=["US"], acc_status="ACTIVE", card_num="private-card-value")
    return {**row, **changes}


def install_sdk(monkeypatch, responses):
    contexts = []

    class Context:
        def __init__(self, **kwargs):
            assert kwargs == dict(filter_trdmarket="US", host="127.0.0.1", port=11111,
                                  security_firm="NONE")
            self.rows = responses[len(contexts)]
            self.closed = False
            contexts.append(self)

        def get_acc_list(self):
            if isinstance(self.rows, Exception):
                raise self.rows
            return 0, pd.DataFrame(self.rows)

        def close(self):
            self.closed = True

    module = SimpleNamespace(
        OpenSecTradeContext=Context, OpenQuoteContext=object, RET_OK=0,
        TrdEnv=SimpleNamespace(SIMULATE="SIMULATE", REAL="REAL"),
        TrdMarket=SimpleNamespace(US="US"), SecurityFirm=SimpleNamespace(NONE="NONE"),
        __version__="offline-fixture",
    )
    # Exercise the existing SDK loader as well; only external module import is replaced.
    import market_vault.moomoo_sdk as loader
    monkeypatch.setattr(loader, "_import_sdk_module", lambda: (module, "moomoo"))
    return contexts, module


def test_probe_selects_only_eligible_account_and_reconnects_without_exporting_ids(monkeypatch):
    rows = [account(100, trd_env="REAL"), account(300, sim_acc_type="FUTURES"),
            account(400, acc_status="DISABLED"), account(500, trdmarket_auth=["HK"]), account()]
    contexts, _ = install_sdk(monkeypatch, [rows, list(reversed(rows))])
    result = sim.run_probe()
    assert result["result"] == "ACCOUNT_VERIFIED"
    assert result["reconnect_same_account"] and result["sdk_module"] == "moomoo"
    assert len(contexts) == 2 and all(ctx.closed for ctx in contexts)
    assert not result["orders_sent"] and not result["funds_or_positions_read"]
    assert not result["account_id_exported"]
    assert "private-card-value" not in json.dumps(result)
    assert "account_id" not in result and "card_num" not in result


@pytest.mark.parametrize("rows,code", [
    ([account(), account(201)], "SIMULATION_ACCOUNT_NOT_UNIQUE"),
    ([account(trd_env="REAL")], "SIMULATION_ACCOUNT_NOT_UNIQUE"),
    ([account(), account()], "DUPLICATE_ACCOUNT_ID"),
    ([account(trdmarket_auth="US")], "SIMULATION_ACCOUNT_NOT_UNIQUE"),
    ([account(sim_acc_type="OPTION")], "SIMULATION_ACCOUNT_NOT_UNIQUE"),
    ([account(1.5)], "INVALID_ACCOUNT_ID"),
    ([{"acc_id": 200}], "ACCOUNT_SCHEMA_MISMATCH"),
])
def test_ineligible_or_ambiguous_metadata_is_rejected(rows, code):
    with pytest.raises(sim.SimulationError, match=code):
        sim.select_simulation_account(pd.DataFrame(rows))


def test_explicit_account_never_falls_back_to_other_simulation_account():
    rows = pd.DataFrame([account(100, trd_env="REAL"), account(), account(201)])
    assert sim.select_simulation_account(rows, 201).account_id == 201
    with pytest.raises(sim.SimulationError, match="PINNED_SIMULATION_ACCOUNT_UNAVAILABLE"):
        sim.select_simulation_account(rows, 100)


def test_reconnect_rejects_changed_environment_even_with_another_eligible_account(monkeypatch):
    contexts, _ = install_sdk(monkeypatch, [[account()], [account(trd_env="REAL"), account(201)]])
    session = sim.SimulationAccountSession()
    session.connect()
    with pytest.raises(sim.SimulationError, match="PINNED_SIMULATION_ACCOUNT_UNAVAILABLE"):
        session.reconnect()
    with pytest.raises(sim.SimulationError, match="NOT_VERIFIED"):
        _ = session.account
    assert all(ctx.closed for ctx in contexts)


def test_failed_revalidation_clears_previous_readiness(monkeypatch):
    contexts, _ = install_sdk(monkeypatch, [[account()]])
    with sim.SimulationAccountSession() as session:
        contexts[0].rows = RuntimeError("password=not-for-upload")
        with pytest.raises(sim.SimulationError, match="ACCOUNT_QUERY_FAILED"):
            session.verify()
        with pytest.raises(sim.SimulationError, match="NOT_VERIFIED"):
            _ = session.account
    assert contexts[0].closed


def test_cli_writes_failure_report_without_arbitrary_sdk_text(monkeypatch, tmp_path):
    contexts, _ = install_sdk(monkeypatch, [RuntimeError("password=not-for-upload")])
    output = tmp_path / "probe.json"
    assert sim.main(["--output", str(output)]) == 1
    result = json.loads(output.read_text())
    assert result["error_code"] == "ACCOUNT_QUERY_FAILED"
    assert "not-for-upload" not in output.read_text()
    assert contexts[0].closed
    before = output.read_bytes()
    assert sim.main(["--output", str(output)]) == 2
    assert output.read_bytes() == before and len(contexts) == 1


def test_unknown_security_firm_fails_before_connect(monkeypatch):
    contexts, _ = install_sdk(monkeypatch, [])
    result = sim.run_probe(security_firm="NOT_AN_ENUM")
    assert result["result"] == "NOT_VERIFIED" and contexts == []


def test_probe_close_failure_does_not_leave_success_result(monkeypatch):
    contexts, module = install_sdk(monkeypatch, [[account()], [account()]])
    original = module.OpenSecTradeContext.close

    def close(self):
        original(self)
        if len(contexts) == 2:
            raise RuntimeError("private-session")

    monkeypatch.setattr(module.OpenSecTradeContext, "close", close)
    result = sim.run_probe()
    assert result["result"] == "NOT_VERIFIED"
    assert result["error_code"] == "CONTEXT_CLOSE_FAILED"
    assert "private-session" not in json.dumps(result)


def test_help_is_offline():
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    result = subprocess.run([sys.executable, "-m", "market_vault.moomoo_simulation", "--help"],
                            capture_output=True, text=True, timeout=20, env=env)
    assert result.returncode == 0 and "--output" in result.stdout
