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


# ---------------------------------------------------------------------------
# RQP-L19: pure membership semantics.
#
# A TEST-ONLY, monkeypatch-scoped temporary enrollment of exactly one candidate
# proves that admission is exact-tuple membership. It enrolls no production
# authority: _QUALIFIED_CAPABILITIES is a module-level frozenset that monkeypatch
# restores, and every test below re-asserts frozenset() afterwards. No tuple is
# qualified by this file.
# ---------------------------------------------------------------------------

# A structurally exact L4 candidate: ten fields, the real recorded tags, and a
# filesystem tuple of the same arity _linux/_windows actually produce.
CANDIDATE = ("Linux", "6.8.0-generic", "x86_64", "2.39", ("cpython", "3.11.9", 64),
             0xEF53, 0x0, 4096, (0, 0), 17, "l4-schedule-readonly-statx-ext4-v1")


def _mutate(field):
    """One field changed by exactly one observable step, preserving its type."""
    if type(field) is str:
        return field + "-mutated"
    if type(field) is int:
        return field + 1
    if type(field) is tuple:
        return field + ("mutated",)
    raise AssertionError("unexpected candidate field type: " + repr(field))


def _mutations(candidate):
    """Every single-field mutation of an exact tuple, plus shape mutations."""
    cases = [("changed_field_%d" % index,
              candidate[:index] + (_mutate(candidate[index]),) + candidate[index + 1:])
             for index in range(len(candidate))]
    cases += [
        ("shortened", candidate[:-1]),
        ("extended", candidate + ("extra",)),
        ("truncated_registry_tag", candidate[:-1] + (candidate[-1][:-1],)),
        ("reordered", (candidate[1], candidate[0]) + candidate[2:]),
        ("empty", ()),
    ]
    return cases


@pytest.fixture
def enrolled(monkeypatch):
    """Temporary enrollment of exactly CANDIDATE; never production authority."""
    assert _platform._QUALIFIED_CAPABILITIES == frozenset()
    monkeypatch.setattr(_platform, "_QUALIFIED_CAPABILITIES", frozenset({CANDIDATE}))
    monkeypatch.setattr(_platform, "_capability", lambda scope: CANDIDATE)
    assert _platform._QUALIFIED_CAPABILITIES == frozenset({CANDIDATE})
    return CANDIDATE


def test_rqp_l19_temporary_registry_admits_only_the_exact_candidate(enrolled):
    assert _platform._require_qualified(object()) == CANDIDATE
    assert _platform._QUALIFIED_CAPABILITIES == frozenset({CANDIDATE})


@pytest.mark.parametrize("label,tuple_", list(_mutations(CANDIDATE)),
                         ids=lambda value: value if isinstance(value, str) else "")
def test_rqp_l19_every_single_field_mutation_fails_closed(enrolled, monkeypatch, label, tuple_):
    assert tuple_ != CANDIDATE, label
    monkeypatch.setattr(_platform, "_capability", lambda scope: tuple_)
    with pytest.raises(_ScheduleArtifactError, match="PLATFORM_UNQUALIFIED"):
        _platform._require_qualified(object())


@pytest.mark.parametrize("tuple_", [(), ("unknown",), *_L3])
def test_rqp_l19_unknown_short_and_l3_tuples_fail_closed(enrolled, monkeypatch, tuple_):
    monkeypatch.setattr(_platform, "_capability", lambda scope: tuple_)
    with pytest.raises(_ScheduleArtifactError, match="PLATFORM_UNQUALIFIED"):
        _platform._require_qualified(object())


def test_rqp_l19_temporary_enrollment_never_survives_into_production():
    assert _platform._QUALIFIED_CAPABILITIES == frozenset()
    assert len(_platform._QUALIFIED_CAPABILITIES) == 0
    assert _L3 & _platform._QUALIFIED_CAPABILITIES == frozenset()
