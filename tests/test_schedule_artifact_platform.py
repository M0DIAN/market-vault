"""Exact production fail-closed policy; mechanics never enroll a tuple."""

import ast
import inspect
from types import SimpleNamespace

import pytest

from market_vault.schedule_artifact import _physical, _platform
from market_vault.schedule_artifact._errors import _ScheduleArtifactError
from market_vault.cross_day_dataset._artifact_platform import _QUALIFIED_CAPABILITIES as _L3


def test_empty_l4_registry_is_not_l3_admission():
    assert type(_platform._QUALIFIED_CAPABILITIES) is frozenset
    assert _platform._QUALIFIED_CAPABILITIES == frozenset()
    assert len(_L3) == 2
    assert not _L3 & _platform._QUALIFIED_CAPABILITIES


@pytest.mark.parametrize("tuple_", [(), ("unknown",), *_L3])
def test_unknown_and_l3_tuples_fail_closed(monkeypatch, tuple_):
    monkeypatch.setattr(_platform, "_capability", lambda scope: tuple_)
    with pytest.raises(_ScheduleArtifactError, match="PLATFORM_UNQUALIFIED"):
        _platform._require_qualified(object())
    assert _platform._QUALIFIED_CAPABILITIES == frozenset()


def test_production_capture_stops_before_artifact_open(monkeypatch):
    events = []
    scope = SimpleNamespace(close=lambda: events.append("close"))
    def parent(path):
        events.append("ancestry")
        return scope
    monkeypatch.setattr(_physical, "_NativeScope", parent)
    monkeypatch.setattr(_platform, "_capability", lambda scope: (events.append("capability"), "unqualified"))
    monkeypatch.setattr(_physical, "_capture_members", lambda *args: pytest.fail("artifact opened before admission"))
    path = ("C:/safe/" if __import__("os").name == "nt" else "/safe/") + "schedule_artifact_id=" + "a" * 64
    with pytest.raises(_ScheduleArtifactError, match="PLATFORM_UNQUALIFIED"):
        _physical._capture_physical(path)
    assert events == ["ancestry", "capability", "close"]


def test_bad_path_never_reaches_filesystem(monkeypatch):
    monkeypatch.setattr(_physical, "_NativeScope", lambda *a: pytest.fail("filesystem touched"))
    with pytest.raises(_ScheduleArtifactError, match="UNSAFE_PATH"):
        _physical._capture_physical("latest")


def test_no_environment_settings_or_test_enrollment():
    source = inspect.getsource(_platform)
    tree = ast.parse(source)
    forbidden = {"environ", "getenv", "settings", "register", "add", "monkeypatch", "override"}
    assert not {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} & forbidden
    assert not {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} & forbidden
    assert {n.name for n in tree.body if isinstance(n, ast.FunctionDef)} == {"_capability", "_require_qualified"}
    assert "l4-schedule-readonly-FileIdInfo-v1" in source
    assert "l4-schedule-readonly-statx-ext4-v1" in source
    assert "cross_day_dataset" not in source
