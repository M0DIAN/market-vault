"""Physical sequencing/resource unit seams. Fakes are not native qualification."""

from dataclasses import FrozenInstanceError
import base64
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from market_vault.schedule_artifact import _physical as p
from market_vault.schedule_artifact._canonical import _canonical_json
from market_vault.schedule_artifact._errors import _ScheduleArtifactError
from market_vault.schedule_artifact._models import _MAX_FILE_BYTES, _MAX_INVENTORY_BYTES, _MAX_SOURCE_BODY_BYTES
from market_vault.schedule_artifact._paths import _MEMBERS


def _tree(tmp_path):
    path = tmp_path / ("schedule_artifact_id=" + "a" * 64)
    path.mkdir()
    for name in _MEMBERS:
        (path / name).write_bytes(b"" if name == "_SUCCESS" else b"{}\n")
    return path


class _FakeObject:
    """Unit double only; production exclusively uses retained native evidence."""
    def __init__(self, path, directory, scope):
        self.path, self.directory, self.scope, self.closed = path, directory, scope, False
        data = path.stat(follow_symlinks=False)
        assert stat.S_ISDIR(data.st_mode) if directory else stat.S_ISREG(data.st_mode)
        if not directory and data.st_nlink != 1:
            raise _ScheduleArtifactError("UNSAFE_PATH", "unit hardlink")
        self.identity = (data.st_dev, data.st_ino, directory)
        self.filesystem, self.security = ("unit",), (data.st_mode,)
        self.size = 0 if directory else data.st_size
        self.original = (self.identity, self.security, self.size)

    def recheck(self):
        if self.closed:
            raise _ScheduleArtifactError("PHYSICAL_DRIFT", "closed unit object")
        data = self.path.stat(follow_symlinks=False)
        now = ((data.st_dev, data.st_ino, self.directory), (data.st_mode,), 0 if self.directory else data.st_size)
        if now != self.original:
            raise _ScheduleArtifactError("PHYSICAL_DRIFT", "unit evidence mismatch")

    def read_bytes(self, size):
        assert len(self.scope.opened) == 7, "all members must be opened before any read"
        self.scope.reads.append(self.path.name)
        assert self.size == size
        return self.path.read_bytes()

    def close(self):
        self.closed = True


class _FakeScope:
    def __init__(self):
        self.handles, self.opened, self.reads, self.closed = [], [], [], False

    def recheck(self):
        assert not self.closed

    def member(self, path, *, directory):
        result = _FakeObject(path, directory, self)
        self.opened.append(result)
        return result

    def close(self):
        self.closed = True


def test_capture_immutable_bytes_and_second_closure(tmp_path):
    root, scope = _tree(tmp_path), _FakeScope()
    with p._capture_members(scope, root) as capture:
        assert capture.inventory == _MEMBERS
        assert len(capture.evidence) == 7
        assert capture.sizes["_SUCCESS"] == 0
        assert all(type(raw) is bytes for raw in capture.data.values())
        with pytest.raises(TypeError):
            capture.data["schedule.json"] = b"new"
        with pytest.raises(FrozenInstanceError):
            capture.inventory = ()
        capture.recheck()
    assert scope.closed and all(item.closed for item in scope.opened)


@pytest.mark.parametrize("member", _MEMBERS)
def test_each_missing_member_rejected_before_content_read(tmp_path, member):
    root, scope = _tree(tmp_path), _FakeScope()
    (root / member).rename(tmp_path / member)
    with pytest.raises(_ScheduleArtifactError, match="INVENTORY_MISMATCH"):
        p._capture_members(scope, root)
    assert not scope.reads and all(item.closed for item in scope.opened)


@pytest.mark.parametrize("name,directory", [("extra", False), (".hidden", False), ("Schedule.json", False), ("extra", True)])
def test_extra_alias_hidden_directory_rejected(tmp_path, name, directory):
    root = _tree(tmp_path)
    if name == "Schedule.json":
        (root / "schedule.json").rename(tmp_path / "original")
    (root / name).mkdir() if directory else (root / name).write_bytes(b"")
    with pytest.raises(_ScheduleArtifactError, match="INVENTORY_MISMATCH"):
        p._capture_members(_FakeScope(), root)


def test_native_member_rejection_never_admits_capture(tmp_path):
    scope = _FakeScope()
    original = scope.member
    def member(path, *, directory):
        if not directory:
            raise _ScheduleArtifactError("UNSAFE_PATH", "native proof unavailable")
        return original(path, directory=directory)
    scope.member = member
    with pytest.raises(_ScheduleArtifactError, match="UNSAFE_PATH"):
        p._capture_members(scope, _tree(tmp_path))
    assert not scope.reads


@pytest.mark.parametrize("kind", ["bytes", "identical_replacement", "different_replacement", "root", "missing", "extra", "case"])
def test_after_capture_drift_fails_closure(tmp_path, kind):
    root, scope = _tree(tmp_path), _FakeScope()
    with p._capture_members(scope, root) as capture:
        member = root / "schedule.json"
        if kind == "bytes":
            member.write_bytes(b"[]\n")
        elif kind.endswith("replacement"):
            member.rename(tmp_path / "held-original")
            member.write_bytes(b"{}\n" if kind == "identical_replacement" else b"[]\n")
        elif kind == "root":
            root.rename(tmp_path / "held-root")
            _tree(tmp_path)
        elif kind == "missing":
            member.rename(tmp_path / "missing")
        elif kind == "extra":
            (root / "extra").write_bytes(b"")
        else:
            member.rename(root / "Schedule.json")
        with pytest.raises(_ScheduleArtifactError, match="PHYSICAL_DRIFT|INVENTORY_MISMATCH"):
            capture.recheck()


def test_scope_drift_fails_closure(tmp_path):
    scope = _FakeScope()
    with p._capture_members(scope, _tree(tmp_path)) as capture:
        scope.recheck = lambda: (_ for _ in ()).throw(OSError("ancestry changed"))
        with pytest.raises(_ScheduleArtifactError, match="PHYSICAL_DRIFT"):
            capture.recheck()


@pytest.mark.parametrize("member", _MEMBERS)
def test_every_member_byte_drift_rejected(tmp_path, member):
    root = _tree(tmp_path)
    with p._capture_members(_FakeScope(), root) as capture:
        (root / member).write_bytes(b"x" if member == "_SUCCESS" else b"[]\n")
        with pytest.raises(_ScheduleArtifactError, match="PHYSICAL_DRIFT"):
            capture.recheck()


@pytest.mark.parametrize("member", _MEMBERS)
def test_every_identical_member_replacement_rejected(tmp_path, member):
    root = _tree(tmp_path)
    with p._capture_members(_FakeScope(), root) as capture:
        path = root / member
        path.rename(tmp_path / "retained")
        path.write_bytes(capture.data[member])
        with pytest.raises(_ScheduleArtifactError, match="PHYSICAL_DRIFT"):
            capture.recheck()


def test_member_security_evidence_and_filesystem_drift_rejected(tmp_path):
    root, scope = _tree(tmp_path), _FakeScope()
    with p._capture_members(scope, root) as capture:
        member = scope.opened[-1]
        security, filesystem = member.security, member.filesystem
        member.security = ("different",)
        with pytest.raises(_ScheduleArtifactError, match="PHYSICAL_DRIFT"):
            capture.recheck()
        member.security = security
        member.filesystem = ("other-volume",)
        with pytest.raises(_ScheduleArtifactError, match="PHYSICAL_DRIFT"):
            capture.recheck()
        member.filesystem = filesystem


def test_member_volume_transition_refused_and_handle_closed():
    scope = p._NativeScope.__new__(p._NativeScope)
    scope.filesystem = ("expected",)
    closed = []
    held = SimpleNamespace(filesystem=("other",), close=lambda: closed.append(True))
    scope.open = lambda *a, **k: held
    with pytest.raises(_ScheduleArtifactError, match="UNSAFE_PATH"):
        scope.member(Path("member"), directory=False)
    assert closed == [True]


def test_nonempty_success_fails_before_any_file_read(tmp_path):
    root, scope = _tree(tmp_path), _FakeScope()
    (root / "_SUCCESS").write_bytes(b"x")
    with pytest.raises(_ScheduleArtifactError, match="INTEGRITY_MISMATCH"):
        p._capture_members(scope, root)
    assert not scope.reads


@pytest.mark.parametrize("size,accepted", [(_MAX_FILE_BYTES, True), (_MAX_FILE_BYTES + 1, False), (-1, False), (True, False)])
def test_file_size_boundary_without_content_allocation(size, accepted):
    sizes = dict.fromkeys(_MEMBERS, 0)
    sizes["schedule.json"] = size
    if accepted:
        p._check_sizes(sizes)
    else:
        with pytest.raises(_ScheduleArtifactError, match="INTEGRITY_MISMATCH"):
            p._check_sizes(sizes)


@pytest.mark.parametrize("excess", [0, 1])
def test_total_size_boundary_without_large_allocation(excess):
    sizes = dict.fromkeys(_MEMBERS, 0)
    sizes["schedule.json"] = sizes["source_snapshot.json"] = _MAX_FILE_BYTES
    sizes["manifest.json"] = excess
    assert sum(sizes.values()) == _MAX_INVENTORY_BYTES + excess
    if excess:
        with pytest.raises(_ScheduleArtifactError, match="INTEGRITY_MISMATCH"):
            p._check_sizes(sizes)
    else:
        p._check_sizes(sizes)


def test_all_metadata_precedes_first_read_and_limit_prevents_reads(tmp_path):
    root, scope = _tree(tmp_path), _FakeScope()
    original = scope.member
    def member(path, *, directory):
        held = original(path, directory=directory)
        if path.name == "verification_receipt.json":
            held.size = _MAX_FILE_BYTES + 1
        return held
    scope.member = member
    with pytest.raises(_ScheduleArtifactError, match="INTEGRITY_MISMATCH"):
        p._capture_members(scope, root)
    assert len(scope.opened) == 7 and not scope.reads


@pytest.mark.parametrize("length", [_MAX_SOURCE_BODY_BYTES, _MAX_SOURCE_BODY_BYTES + 1])
def test_source_body_bound_before_decode_allocation(monkeypatch, length):
    text = base64.b64encode(b"a" * length).decode("ascii")
    if length == _MAX_SOURCE_BODY_BYTES:
        assert len(p._decode_source_body(text)) == length
    else:
        monkeypatch.setattr(p, "_decode_base64", lambda value: pytest.fail("oversized decoded allocation"))
        with pytest.raises(_ScheduleArtifactError, match="predecode"):
            p._decode_source_body(text)


@pytest.mark.parametrize("field", ["request_bytes_base64", "response_bytes_base64"])
def test_guarded_parser_applies_body_bound_independently(monkeypatch, field):
    monkeypatch.setattr(p, "_MAX_SOURCE_BODY_BYTES", 2)
    raw = _canonical_json({"nested": [{field: "YWJj"}]})
    with pytest.raises(_ScheduleArtifactError, match="predecode"):
        p._parse_guarded_json(raw)


@pytest.mark.parametrize("depth", [32, 33])
def test_nesting_bound_before_parser(monkeypatch, depth):
    raw = b"[" * depth + b"0" + b"]" * depth + b"\n"
    if depth == 32:
        assert p._parse_guarded_json(raw)
    else:
        monkeypatch.setattr(p, "_parse_canonical_json", lambda raw: pytest.fail("full parser reached"))
        with pytest.raises(_ScheduleArtifactError, match="nesting"):
            p._parse_guarded_json(raw)


def test_raw_nesting_understands_string_escapes_and_rejects_malformed():
    raw = _canonical_json({"s": '{["\\' * 100})
    assert p._parse_guarded_json(raw)["s"]
    for bad in (b"[}\n", b"{\n", b'"unterminated', b"]\n"):
        with pytest.raises(_ScheduleArtifactError, match="NONCANONICAL_BYTES"):
            p._json_nesting_preflight(bad)


def test_noncanonical_json_is_refused_by_the_preflight_guard(tmp_path):
    root, scope = _tree(tmp_path), _FakeScope()
    (root / "manifest.json").write_bytes(b"{}")
    capture = p._capture_members(scope, root)
    try:
        with pytest.raises(ValueError, match="noncanonical"):
            p._preflight_documents(capture.data)
    finally:
        capture.close()
    assert all(item.closed for item in scope.opened)
