from __future__ import annotations

from contextlib import contextmanager
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pandas as pd
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "capture_moomoo_evidence.py"


@pytest.fixture
def capture_module(monkeypatch):
    spec = importlib.util.spec_from_file_location("capture_moomoo_evidence_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    monkeypatch.setattr(module, "source_identity", lambda: {"git_head": None, "sha256": {}})
    return module


def install_fake(module, monkeypatch, *, fail=False, empty=False, dates=None):
    calls = []
    closed = []
    bars = pd.DataFrame({
        "code": ["US.SPY", "US.SPY"],
        "time_key": ["2020-01-02 09:30:00"] * 2,
        "close": [321.23456789, 321.23456789], "volume": [17, 17],
    })

    class Calendar:
        def fetch_trading_calendar(self, start, end, market=None):
            calls.append(("calendar", start.isoformat(), end.isoformat(), market))
            return pd.DataFrame({"time": dates if dates is not None else ["2020-01-02"],
                                 "trade_date_type": ["WHOLE"] * (len(dates) if dates is not None else 1)})

    class History:
        last_request_evidence = {"effective_request_session": "RTH", "sdk_module": "test",
                                 "response_session_coverage_verified": False}

        def fetch_history(self, symbol, day, *, interval, adjustment, session):
            calls.append((symbol, day.isoformat(), interval, adjustment, session))
            if fail and symbol == "US.QQQ":
                raise RuntimeError("password=must-not-export")
            result = bars.copy()
            result["code"] = symbol
            return result.iloc[:0] if empty else result

    @contextmanager
    def factory(output, port):
        # The requested scope must already have been persisted before connect.
        request = json.loads((output / "request.json").read_text())
        assert request["session"] == "RTH" and request["adjustment"] == "NONE"
        assert port == 11111
        try:
            yield Calendar(), History()
        finally:
            closed.append(True)

    monkeypatch.setattr(module, "open_collectors", factory)
    return calls, closed


def arguments(output):
    return ["--start", "2020-01-02", "--end", "2020-01-02", "--output", str(output)]


def read_manifest(output):
    return json.loads((output / "manifest.json").read_text())


def test_cli_preserves_raw_rows_and_does_not_claim_independent_coverage(capture_module, monkeypatch, tmp_path):
    calls, closed = install_fake(capture_module, monkeypatch)
    output = tmp_path / "capture"
    assert capture_module.main(arguments(output)) == 0
    assert calls == [("calendar", "2020-01-02", "2020-01-02", "US"),
                     ("US.SPY", "2020-01-02", "1m", "NONE", "RTH"),
                     ("US.QQQ", "2020-01-02", "1m", "NONE", "RTH")]
    assert closed == [True]
    raw = pd.read_csv(output / "US.SPY_2020-01-02.csv")
    assert len(raw) == 2 and raw.iloc[0].equals(raw.iloc[1])
    assert raw.loc[0, "close"] == 321.23456789
    manifest = read_manifest(output)
    assert manifest["completed_history_requests"] == 2
    assert manifest["not_completed_history_requests"] == 0
    assert manifest["coverage"] == manifest["data_evidence_gate"] == "NOT_EVALUATED"
    assert manifest["independent_reference"] == "NOT_SUPPLIED"
    for snapshot in manifest["snapshots"]:
        assert hashlib.sha256((output / snapshot["file"]).read_bytes()).hexdigest() == snapshot["sha256"]
    schedule = json.loads((output / "provider_schedule.json").read_text())
    assert schedule["expected_bar_count"] is None and not schedule["independently_verified"]
    with zipfile.ZipFile(output / "upload.zip") as bundle:
        assert set(bundle.namelist()) == {"request.json", "events.jsonl", "manifest.json",
                                         "provider_schedule.json", "calendar.csv",
                                         "US.SPY_2020-01-02.csv", "US.QQQ_2020-01-02.csv"}


def test_failure_preserves_completed_request_and_redacts_arbitrary_sdk_error(capture_module, monkeypatch, tmp_path):
    _, closed = install_fake(capture_module, monkeypatch, fail=True)
    output = tmp_path / "failed"
    assert capture_module.main(arguments(output)) == 1
    manifest = read_manifest(output)
    assert manifest["capture_status"] == "FAILED"
    assert manifest["completed_history_requests"] == 1
    assert manifest["not_completed_history_requests"] == 1
    assert manifest["failure"]["symbol"] == "US.QQQ"
    assert manifest["failure"]["error_type"] == "RuntimeError"
    assert not manifest["partial_pages_of_failed_request_preserved"]
    assert closed == [True]
    with zipfile.ZipFile(output / "upload.zip") as bundle:
        assert "US.SPY_2020-01-02.csv" in bundle.namelist()
        assert all(b"must-not-export" not in bundle.read(name) for name in bundle.namelist())
    original = {path.name: path.read_bytes() for path in output.iterdir()}
    assert capture_module.main(arguments(output)) == 1
    assert original == {path.name: path.read_bytes() for path in output.iterdir()}
    install_fake(capture_module, monkeypatch)
    assert capture_module.main(arguments(tmp_path / "new_attempt")) == 0
    assert original == {path.name: path.read_bytes() for path in output.iterdir()}


def test_empty_history_is_not_a_clean_capture(capture_module, monkeypatch, tmp_path):
    install_fake(capture_module, monkeypatch, empty=True)
    output = tmp_path / "empty"
    assert capture_module.main(arguments(output)) == 2
    manifest = read_manifest(output)
    assert manifest["empty_history_requests"] == 2
    assert manifest["capture_status"] == "COMPLETE_WITH_EMPTY_REQUESTS"


@pytest.mark.parametrize("dates", [[], ["2020-01-02", "2020-01-02"], ["2020-01-03"], ["invalid"]])
def test_invalid_calendar_is_retained_not_silently_filtered(capture_module, monkeypatch, tmp_path, dates):
    calls, _ = install_fake(capture_module, monkeypatch, dates=dates)
    output = tmp_path / "bad_calendar"
    assert capture_module.main(arguments(output)) == 1
    assert len(calls) == 1
    assert (output / "calendar.csv").exists()
    manifest = read_manifest(output)
    assert manifest["planned_history_requests"] is None
    assert manifest["capture_status"] == "FAILED"


@pytest.mark.parametrize("extra", [["--symbols", "US.SPY", "US.SPY"], ["--symbols", "../secret"],
                                   ["--end", "2020-02-02"], ["--port", "0"]])
def test_scope_rejected_before_connect_or_write(capture_module, monkeypatch, tmp_path, extra):
    calls, _ = install_fake(capture_module, monkeypatch)
    output = tmp_path / "invalid"
    with pytest.raises(SystemExit) as exc:
        capture_module.main(arguments(output) + extra)
    assert exc.value.code == 2
    assert not output.exists() and not calls


def test_help_does_not_require_sdk_or_connect():
    result = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0
    assert "--output" in result.stdout and "--symbols" in result.stdout


def test_default_factory_uses_existing_collectors_with_quote_only_sdk(capture_module, monkeypatch, tmp_path):
    """Exercise the real Settings and collectors; only the external SDK is fake."""
    from types import SimpleNamespace
    import market_vault.collectors.moomoo_calendar as calendar_module
    import market_vault.collectors.moomoo_history as history_module

    calls = []
    contexts = []

    class QuoteContext:
        def __init__(self, *, host, port):
            assert (host, port) == ("127.0.0.1", 11111)
            self.closed = False
            contexts.append(self)

        def close(self):
            self.closed = True

        def request_trading_days(self, **kwargs):
            calls.append(("calendar", kwargs))
            return 0, [{"time": "2020-01-02", "trade_date_type": "WHOLE"}]

        def request_history_kline(self, *, session, **kwargs):
            calls.append(("history", {"session": session, **kwargs}))
            return 0, pd.DataFrame({"code": [kwargs["code"]],
                                    "time_key": ["2020-01-02 09:30:00"], "close": [321.5]}), None

    sdk = {"OpenQuoteContext": QuoteContext, "RET_OK": 0,
           "KLType": SimpleNamespace(K_1M="K_1M"), "AuType": SimpleNamespace(NONE="NONE"),
           "KL_FIELD": SimpleNamespace(ALL="ALL"), "Session": SimpleNamespace(RTH="RTH"),
           "TradeDateMarket": SimpleNamespace(US="US"), "module_name": "offline_fixture", "version": "test"}
    monkeypatch.setattr(calendar_module, "load_moomoo_sdk", lambda: sdk)
    monkeypatch.setattr(history_module, "load_moomoo_sdk", lambda: sdk)
    output = tmp_path / "bound"
    assert capture_module.main(arguments(output)) == 0
    assert len(contexts) == 2 and all(context.closed for context in contexts)
    history_calls = [kwargs for kind, kwargs in calls if kind == "history"]
    assert len(history_calls) == 2
    assert all(item["session"] == "RTH" and item["autype"] == "NONE"
               and item["ktype"] == "K_1M" for item in history_calls)
    assert all(item["start"] == item["end"] == "2020-01-02" for item in history_calls)
    assert not (output / "unused_catalog.sqlite").exists()
    events = [json.loads(line) for line in (output / "events.jsonl").read_text().splitlines()]
    returned = [event for event in events if event["kind"] == "history" and event["status"] == "RETURNED"]
    assert all(event["request_capability"]["sdk_module"] == "offline_fixture" for event in returned)
    assert all(not event["request_capability"]["response_session_coverage_verified"] for event in returned)
