from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from market_vault.collectors.moomoo_history import MoomooHistoryCollector, MoomooRequestError
from market_vault.models import Settings
from market_vault.moomoo_sdk import MoomooDependencyError


_OMITTED = object()
TRADE_DATE = date(2026, 7, 31)


class RecordingContext:
    def __init__(self):
        self.calls = []
        self.responses = None

    def respond(self, kwargs):
        self.calls.append(kwargs)
        if self.responses is not None:
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        if kwargs["page_req_key"] is None:
            return 0, pd.DataFrame({"code": ["US.MU"], "close": [100.0]}), b"next"
        return 0, pd.DataFrame({"code": ["US.MU"], "close": [101.0]}), None

    def close(self):
        pass


class NativeContext(RecordingContext):
    def request_history_kline(self, session=_OMITTED, extended_time=_OMITTED, **kwargs):
        if session is not _OMITTED:
            kwargs["session"] = session
        if extended_time is not _OMITTED:
            kwargs["extended_time"] = extended_time
        return self.respond(kwargs)


class LegacyContext(RecordingContext):
    def request_history_kline(self, *, extended_time=_OMITTED, **kwargs):
        if extended_time is not _OMITTED:
            kwargs["extended_time"] = extended_time
        return self.respond(kwargs)


def make_collector(tmp_path, context, *, session_enum=True):
    settings = Settings(
        project_root=tmp_path,
        opend_host="127.0.0.1",
        opend_port=11111,
        data_root=tmp_path / "data",
        catalog_path=tmp_path / "catalog.duckdb",
        manifest_dir=tmp_path / "manifests",
        report_dir=tmp_path / "reports",
        request_pause_seconds=0,
    )
    collector = MoomooHistoryCollector(settings)
    collector._ctx = context
    collector._sdk = {
        "AuType": SimpleNamespace(NONE="NONE", QFQ="QFQ", HFQ="HFQ"),
        "KLType": SimpleNamespace(K_1M="K_1M", K_DAY="K_DAY"),
        "KL_FIELD": SimpleNamespace(ALL="ALL"),
        "RET_OK": 0,
        "Session": SimpleNamespace(ALL="sdk-ALL", RTH="sdk-RTH", ETH="sdk-ETH") if session_enum else None,
        "module_name": "moomoo",
        "version": "9.3-test-sdk",
    }
    return collector


@pytest.mark.parametrize("session", ["RTH", "ETH", "ALL"])
def test_fetch_history_pages_until_key_is_none(tmp_path, session):
    context = NativeContext()
    collector = make_collector(tmp_path, context)

    frame = collector.fetch_history("US.MU", TRADE_DATE, "1m", "NONE", session)

    assert frame["close"].tolist() == [100.0, 101.0]
    assert [call["page_req_key"] for call in context.calls] == [None, b"next"]
    for call in context.calls:
        assert call == {
            "code": "US.MU", "start": str(TRADE_DATE), "end": str(TRADE_DATE),
            "ktype": "K_1M", "autype": "NONE", "fields": ["ALL"],
            "max_count": collector.settings.max_count, "page_req_key": call["page_req_key"],
            "session": f"sdk-{session}",
        }
    assert collector.last_request_evidence == {
        "symbol": "US.MU", "interval": "1m", "requested_session": session,
        "effective_request_session": session, "request_mode": "SESSION",
        "session_keyword_supported": True, "extended_time_keyword_supported": True,
        "sdk_module": "moomoo", "sdk_version": "9.3-test-sdk",
        "validation_scope": "REQUEST_PARAMETER_CAPABILITY_ONLY",
        "response_session_coverage_verified": False,
    }


@pytest.mark.parametrize("session,extended_time", [("RTH", False), ("ETH", True)])
def test_legacy_sdk_without_session_enum_preserves_exact_session(tmp_path, session, extended_time):
    context = LegacyContext()
    collector = make_collector(tmp_path, context, session_enum=False)

    frame = collector.fetch_history("US.MU", TRADE_DATE, "1m", "NONE", session)

    assert frame["close"].tolist() == [100.0, 101.0]
    assert [call["page_req_key"] for call in context.calls] == [None, b"next"]
    assert all(call["extended_time"] is extended_time and "session" not in call for call in context.calls)
    assert collector.last_request_evidence["requested_session"] == session
    assert collector.last_request_evidence["effective_request_session"] == session
    assert collector.last_request_evidence["request_mode"] == "EXTENDED_TIME"
    assert collector.last_request_evidence["session_keyword_supported"] is False
    assert collector.last_request_evidence["extended_time_keyword_supported"] is True
    assert collector.last_request_evidence["response_session_coverage_verified"] is False


def test_legacy_all_is_refused_before_any_history_request(tmp_path):
    context = LegacyContext()
    collector = make_collector(tmp_path, context, session_enum=False)
    collector.fetch_history("US.MU", TRADE_DATE, session="RTH")
    assert collector.last_request_evidence is not None
    context.calls.clear()

    with pytest.raises(MoomooDependencyError, match="ALL requires native session support"):
        collector.fetch_history("US.MU", TRADE_DATE, session="ALL")

    assert context.calls == []
    assert collector.last_request_evidence is None


@pytest.mark.parametrize("failure", ["internal", "unpack"])
def test_type_error_is_not_retried_with_different_session_parameters(tmp_path, failure):
    context = NativeContext()
    collector = make_collector(tmp_path, context)
    collector.fetch_history("US.MU", TRADE_DATE)
    assert collector.last_request_evidence is not None
    context.calls.clear()
    error = TypeError("SDK response decoding failed")
    context.responses = [error if failure == "internal" else None]

    with pytest.raises(TypeError) as caught:
        collector.fetch_history("US.MU", TRADE_DATE)

    if failure == "internal":
        assert caught.value is error
    assert len(context.calls) == 1
    assert context.calls[0]["session"] == "sdk-ALL"
    assert "extended_time" not in context.calls[0]
    assert collector.last_request_evidence is None


@pytest.mark.parametrize("failure,expected_calls", [("return_code", 1), ("nonframe", 1), ("second_page", 2)])
def test_unsuccessful_fetch_clears_previous_request_evidence(tmp_path, failure, expected_calls):
    context = NativeContext()
    collector = make_collector(tmp_path, context)
    collector.fetch_history("US.MU", TRADE_DATE)
    assert collector.last_request_evidence is not None
    context.calls.clear()
    if failure == "nonframe":
        context.responses = [(0, {"close": [100.0]}, None)]
        message = "non-DataFrame"
    else:
        context.responses = [(1, "provider failed", None)]
        message = "provider failed"
        if failure == "second_page":
            context.responses.insert(0, (0, pd.DataFrame({"close": [100.0]}), b"next"))

    with pytest.raises(MoomooRequestError, match=message):
        collector.fetch_history("US.MU", TRADE_DATE)

    assert len(context.calls) == expected_calls
    assert [call["page_req_key"] for call in context.calls] == [None, b"next"][:expected_calls]
    assert collector.last_request_evidence is None


@pytest.mark.parametrize("signature", ["kwargs_only", "positional_only", "unknown"])
def test_intraday_requires_proven_keyword_capability(tmp_path, signature):
    calls = []
    if signature == "positional_only":
        def request(session=None, /, **kwargs):
            calls.append(kwargs)
    else:
        def request(**kwargs):
            calls.append(kwargs)
        if signature == "unknown":
            request.__signature__ = "unavailable"
    collector = make_collector(tmp_path, SimpleNamespace(request_history_kline=request))

    with pytest.raises(MoomooDependencyError, match="[Cc]apabilit|keyword support"):
        collector.fetch_history("US.MU", TRADE_DATE, session="RTH")

    assert calls == []
    assert collector.last_request_evidence is None


def test_native_session_capability_requires_matching_sdk_enum(tmp_path):
    context = NativeContext()
    collector = make_collector(tmp_path, context, session_enum=False)

    with pytest.raises(MoomooDependencyError, match=r"requires Session\.ALL"):
        collector.fetch_history("US.MU", TRADE_DATE, session="ALL")

    assert context.calls == []
    assert collector.last_request_evidence is None


@pytest.mark.parametrize("context_type", [NativeContext, LegacyContext])
def test_daily_history_uses_sdk_default_without_session_arguments(tmp_path, context_type):
    context = context_type()
    collector = make_collector(tmp_path, context, session_enum=False)

    frame = collector.fetch_history("US.MU", TRADE_DATE, "1d", "NONE", "ALL")

    assert frame["close"].tolist() == [100.0, 101.0]
    assert len(context.calls) == 2
    assert all(call["ktype"] == "K_DAY" for call in context.calls)
    assert all("session" not in call and "extended_time" not in call for call in context.calls)
    assert collector.last_request_evidence == {
        "symbol": "US.MU", "interval": "1d", "requested_session": "ALL",
        "effective_request_session": "SDK_DAILY_DEFAULT", "request_mode": "DAILY_DEFAULT",
        "session_keyword_supported": None, "extended_time_keyword_supported": None,
        "sdk_module": "moomoo", "sdk_version": "9.3-test-sdk",
        "validation_scope": "REQUEST_PARAMETER_CAPABILITY_ONLY",
        "response_session_coverage_verified": False,
    }
