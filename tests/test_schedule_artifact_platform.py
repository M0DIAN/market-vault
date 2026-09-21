"""Exact production fail-closed policy; mechanics never enroll a tuple."""

import ast
import ctypes
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

# The exact observed 10-field Linux L4 candidate.
#
# Field order and each field's producer are fixed by _platform._capability's Linux
# branch, so this literal uses that exact order and arity. Every index below is the
# position in the returned tuple, and every filesystem index is the position inside
# the scope.filesystem tuple:
#   0 "Linux"                        5 scope.filesystem[0]  (ext4 superblock magic)
#   1 os.uname().release             6 scope.filesystem[2]  (statfs flags)
#   2 os.uname().machine             7 scope.filesystem[3]  (statfs block size)
#   3 glibc gnu_get_libc_version()   8 _ext4_capability(...) ("ext4", opts, super)
#   4 python tuple (impl, version, pointer width)
#   9 "l4-schedule-readonly-statx-ext4-v1"
#
# Field 4 is os' python triple as the L3-qualified host recorded it:
# sys.implementation.name, sys.version and c.sizeof(c_void_p) * 8, which is 64 there.
# It is recorded evidence, NOT a live binding to whichever interpreter runs this test.
# Field 8 is the L4 projection of _ext4_capability, which is a single 3-element
# tuple field -- "ext4" plus the already-sorted mount and super option tuples.
#
# Every field except the version tag carries the L3-qualified host's recorded
# measurements verbatim: kernel release, machine, glibc, interpreter triple, ext4
# superblock magic, statfs flags and statfs block size.
# The historical 11-field literal was structurally impossible: it split that one
# tuple field across three positions and used (0, 0) where L4 carries the real
# statfs flags, so it could never equal a production tuple for any host.
L4_LINUX_CANDIDATE = (
    "Linux", "6.17.0-1022-azure", "x86_64", "2.39",
    ("cpython", "3.11.16 (main, Aug 13 2026, 02:46:14) [GCC 13.3.0]", 64),
    61267, 4128, 4096, ("ext4", ("relatime", "rw"),
                        ("commit=30", "discard", "errors=remount-ro", "rw")),
    "l4-schedule-readonly-statx-ext4-v1",
)


def _single_field_mutations(value, path=()):
    """Recursively mutate every leaf field, exactly as the L3 pattern does.

    Each mutation is one observable step that preserves the field's own type, so a
    rejection is attributable to that field and not to a type error. Tuples also
    receive an arity mutation at every nesting level.
    """
    if type(value) is tuple:
        yield path, value + ("UNTESTED",)
        for index, field in enumerate(value):
            for changed_path, changed in _single_field_mutations(field, path + (index,)):
                yield changed_path, value[:index] + (changed,) + value[index + 1:]
    else:
        yield path, value + 1 if type(value) is int else value + "-UNTESTED"


def _tuple_nodes(value):
    """Yield every tuple node in the candidate, at every nesting level."""
    if type(value) is tuple:
        yield value
        for field in value:
            yield from _tuple_nodes(field)


def _leaf_nodes(value):
    """Yield every non-tuple leaf in the candidate, at every nesting level."""
    if type(value) is tuple:
        for field in value:
            yield from _leaf_nodes(field)
    else:
        yield value


def _shape_mutations(candidate):
    """Shortened, extended, reordered, tag-mutated, L3 and unknown candidates."""
    return [
        ("shortened", candidate[:-1]),
        ("extended", candidate + ("extra",)),
        ("reordered", (candidate[1], candidate[0]) + candidate[2:]),
        ("tag_mutation", candidate[:-1] + (candidate[-1][:-1],)),
        ("empty", ()),
        ("unknown", ("unknown",)),
        ("unknown_multi", ("unknown",) * len(candidate)),
        ("l3_tuples", _L3),
    ]


L4_MUTATION_CASES = [
    pytest.param(changed, id="leaf-" + ".".join(map(str, path)) if path else "arity-root")
    for path, changed in _single_field_mutations(L4_LINUX_CANDIDATE)
]

# The mutation-case count is NOT hand-stated here. It is computed from the exact
# candidate by the same generator that builds L4_MUTATION_CASES and asserted
# against the parametrised set, so arity or nesting drift is caught rather than
# silently changing the size of the mutation family.
L4_MUTATION_CASE_COUNT = sum(1 for _ in _single_field_mutations(L4_LINUX_CANDIDATE))
L4_SHAPE_CASE_COUNT = len(_shape_mutations(L4_LINUX_CANDIDATE))


@pytest.fixture
def enrolled(monkeypatch):
    """Temporary enrollment of exactly L4_LINUX_CANDIDATE; never production authority."""
    assert type(_platform._QUALIFIED_CAPABILITIES) is frozenset
    assert _platform._QUALIFIED_CAPABILITIES == frozenset()
    monkeypatch.setattr(_platform, "_QUALIFIED_CAPABILITIES", frozenset({L4_LINUX_CANDIDATE}))
    monkeypatch.setattr(_platform, "_capability", lambda scope: L4_LINUX_CANDIDATE)
    assert _platform._QUALIFIED_CAPABILITIES == frozenset({L4_LINUX_CANDIDATE})
    try:
        yield L4_LINUX_CANDIDATE
    finally:
        # Scoped temporary enrollment only: the patched registry is still the
        # temporary one here, and monkeypatch removes it after this fixture.
        assert _platform._QUALIFIED_CAPABILITIES == frozenset({L4_LINUX_CANDIDATE})


def test_rqp_l19_candidate_is_the_exact_ten_field_linux_l4_shape():
    """Pin the candidate's arity and per-field types to the production assembly."""
    assert len(L4_LINUX_CANDIDATE) == 10
    assert [type(field) for field in L4_LINUX_CANDIDATE] == [
        str, str, str, str, tuple, int, int, int, tuple, str]
    # Exactly two nested fields carry tuples: the interpreter triple and the
    # _ext4_capability triple. Anything else means the literal drifted from the
    # production field order rather than from a host measurement.
    assert [index for index, field in enumerate(L4_LINUX_CANDIDATE) if type(field) is tuple] == [4, 8]
    assert len(L4_LINUX_CANDIDATE[4]) == 3 and len(L4_LINUX_CANDIDATE[8]) == 3
    # Field 5 is the ext4 superblock magic, which is the value L4 projects.
    assert L4_LINUX_CANDIDATE[5] == 0xEF53
    # Field 4 keeps the projected SHAPE of os' python triple without claiming this
    # host's interpreter: the literal is the L3-qualified host's recorded value and
    # must NOT be rewritten to whatever interpreter runs the test. Only field 9 is a
    # production constant that must match this tree exactly.
    implementation, version, pointer_width = L4_LINUX_CANDIDATE[4]
    assert type(implementation) is str and implementation
    assert type(version) is str and version
    assert pointer_width == ctypes.sizeof(ctypes.c_void_p) * 8
    assert L4_LINUX_CANDIDATE[9] == "l4-schedule-readonly-statx-ext4-v1"
    assert type(L4_LINUX_CANDIDATE) is tuple and hash(L4_LINUX_CANDIDATE) is not None


def test_rqp_l19_mutation_case_count_is_machine_verified(capsys):
    """The mutation family size is computed from the candidate, never hand-claimed.

    Every tuple node contributes exactly one arity mutation and every non-tuple leaf
    contributes exactly one value mutation, at every nesting level. The count is
    derived from the real candidate and pinned to the parametrised set, so a change
    in candidate arity or nesting cannot silently shrink or grow the family that is
    proved to fail closed.
    """
    cases = list(_single_field_mutations(L4_LINUX_CANDIDATE))
    tuple_nodes = sum(1 for _ in _tuple_nodes(L4_LINUX_CANDIDATE))
    leaves = sum(1 for _ in _leaf_nodes(L4_LINUX_CANDIDATE))
    assert L4_MUTATION_CASE_COUNT == len(cases)
    assert L4_MUTATION_CASE_COUNT == len(L4_MUTATION_CASES)
    assert L4_MUTATION_CASE_COUNT == tuple_nodes + leaves
    assert len({path for path, _ in cases}) == L4_MUTATION_CASE_COUNT, "each mutation must be distinct"
    assert L4_SHAPE_CASE_COUNT == len(_shape_mutations(L4_LINUX_CANDIDATE))
    with capsys.disabled():
        print("RQP_L19_MUTATION_CASE_COUNT=%d" % L4_MUTATION_CASE_COUNT)
        print("RQP_L19_SHAPE_CASE_COUNT=%d" % L4_SHAPE_CASE_COUNT)


def test_rqp_l19_temporary_registry_admits_only_the_exact_candidate(enrolled):
    assert _platform._require_qualified(object()) == L4_LINUX_CANDIDATE
    assert _platform._QUALIFIED_CAPABILITIES == frozenset({L4_LINUX_CANDIDATE})


@pytest.mark.parametrize("tuple_", L4_MUTATION_CASES)
def test_rqp_l19_every_recursive_leaf_field_mutation_fails_closed(enrolled, monkeypatch, tuple_):
    assert tuple_ != L4_LINUX_CANDIDATE
    monkeypatch.setattr(_platform, "_capability", lambda scope: tuple_)
    with pytest.raises(_ScheduleArtifactError, match="PLATFORM_UNQUALIFIED"):
        _platform._require_qualified(object())


@pytest.mark.parametrize("label,tuple_", _shape_mutations(L4_LINUX_CANDIDATE),
                         ids=[label for label, _ in _shape_mutations(L4_LINUX_CANDIDATE)])
def test_rqp_l19_shape_reorder_tag_l3_and_unknown_candidates_fail_closed(enrolled, monkeypatch, label, tuple_):
    assert tuple_ != L4_LINUX_CANDIDATE, label
    monkeypatch.setattr(_platform, "_capability", lambda scope: tuple_)
    with pytest.raises(_ScheduleArtifactError, match="PLATFORM_UNQUALIFIED"):
        _platform._require_qualified(object())


def test_rqp_l19_l3_tuples_are_admitted_only_by_their_own_registry(enrolled, monkeypatch):
    """The historical L3 tuples stay unqualified under L4 admission.

    L3 and L4 tuples share a length and a field order for the first nine fields, so
    this is the case a length or prefix check would wrongly admit. The observed L3
    tuples are proved to differ from the observed L4 candidate, and are then
    rejected by exact membership.
    """
    l3_linux = next(tuple_ for tuple_ in _L3 if tuple_[0] == "Linux")
    assert len(l3_linux) == len(L4_LINUX_CANDIDATE) == 10
    assert l3_linux != L4_LINUX_CANDIDATE
    assert l3_linux[:-1] == L4_LINUX_CANDIDATE[:-1], (
        "only the version tag separates the observed L3 and L4 Linux tuples")
    assert l3_linux[-1] == "statx-protected-ext4-v1"
    for tuple_ in _L3:
        assert tuple_ not in _platform._QUALIFIED_CAPABILITIES
        monkeypatch.setattr(_platform, "_capability", lambda scope, value=tuple_: value)
        with pytest.raises(_ScheduleArtifactError, match="PLATFORM_UNQUALIFIED"):
            _platform._require_qualified(object())


def test_rqp_l19_temporary_enrollment_never_survives_into_production():
    assert type(_platform._QUALIFIED_CAPABILITIES) is frozenset
    assert _platform._QUALIFIED_CAPABILITIES == frozenset()
    assert len(_platform._QUALIFIED_CAPABILITIES) == 0
    assert _L3 & _platform._QUALIFIED_CAPABILITIES == frozenset()
