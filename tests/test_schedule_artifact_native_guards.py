"""Static access-policy tests do not constitute native platform qualification."""

import os
import ctypes

import pytest

from market_vault.schedule_artifact._windows import _access_boundary
from market_vault.schedule_artifact._errors import _ScheduleArtifactError


CURRENT = "S-1-5-21-1-2-3-1001"


def _guard_functions(module):
    """Top-level function definitions of a module, by name.

    Module-level so the RQP-L21 static guard and the later GAP-discipline guards
    share exactly one implementation of "which functions does this file define".
    """
    return {node.name: node for node in module.body if isinstance(node, ast.FunctionDef)}


@pytest.fixture
def native_evidence(monkeypatch):
    from market_vault.schedule_artifact import _windows as native
    volume = "\\\\?\\Volume{00000000-0000-0000-0000-000000000001}\\"
    facts = dict(guid_path=volume, directory=1, attributes=0x10, tag=0,
                 serial=17, identifier=1, delete_pending=0, drive_type=3)

    def info(handle, code, pointer, size):
        assert handle == 123
        kind = {18: native._IdInfo, 9: native._TagInfo, 1: native._StandardInfo}[code]
        assert size == ctypes.sizeof(kind)
        record = ctypes.cast(pointer, ctypes.POINTER(kind)).contents
        if code == 18:
            record.serial = facts["serial"]
            record.identifier[0] = facts["identifier"]
        elif code == 9:
            record.attributes, record.tag = facts["attributes"], facts["tag"]
        else:
            record.directory, record.delete_pending = facts["directory"], facts["delete_pending"]
        return 1

    def volume_path(path, buffer, size):
        assert path == "Z:\\"
        buffer.value = "Z:\\"
        return 1

    def volume_name(mount, buffer, size):
        assert mount.value == "Z:\\"
        buffer.value = volume
        return 1

    monkeypatch.setattr(native, "_info", info, raising=False)
    monkeypatch.setattr(native, "_file_type", lambda handle: 1, raising=False)
    monkeypatch.setattr(native, "_handle_path", lambda handle, flags: facts["guid_path"] if flags else "\\\\?\\Z:\\")
    monkeypatch.setattr(native, "_volume_path", volume_path, raising=False)
    monkeypatch.setattr(native, "_volume_name", volume_name, raising=False)
    monkeypatch.setattr(native, "_drive_type", lambda mount: facts["drive_type"], raising=False)
    return facts


def test_observed_sandbox_mask_only_admitted_for_native_volume_ancestor(native_evidence):
    facts = ("S-1-5-18", 0x1000, ((0, 0, 0x001301BF, "S-1-5-11"),), b"sd")
    _access_boundary(facts, CURRENT, ancestor=True, held_handle=123)
    with pytest.raises(_ScheduleArtifactError):
        _access_boundary(facts, CURRENT, ancestor=True)
    with pytest.raises(_ScheduleArtifactError):
        _access_boundary(facts, CURRENT, ancestor=False, held_handle=123)
    native_evidence["guid_path"] += "ordinary-ancestor"
    with pytest.raises(_ScheduleArtifactError):
        _access_boundary(facts, CURRENT, ancestor=True, held_handle=123)


@pytest.mark.parametrize("mask", (0x40, 0x40000, 0x80000, 0x10000000, 0x40000000))
@pytest.mark.parametrize("ace_flags", (0, 0x10))
def test_native_volume_root_still_rejects_child_or_security_authority(native_evidence, mask, ace_flags):
    facts = ("S-1-5-18", 0, ((0, ace_flags, mask, "S-1-5-11"),), b"sd")
    with pytest.raises(_ScheduleArtifactError):
        _access_boundary(facts, CURRENT, ancestor=True, held_handle=123)


def test_ordinary_ancestor_delete_remains_forbidden(native_evidence):
    native_evidence["guid_path"] += "ordinary-ancestor"
    facts = ("S-1-5-18", 0, ((0, 0, 0x10000, "S-1-5-11"),), b"sd")
    with pytest.raises(_ScheduleArtifactError):
        _access_boundary(facts, CURRENT, ancestor=True, held_handle=123)


def test_native_root_requires_exact_guid_root_not_shared_prefix(native_evidence):
    from market_vault.schedule_artifact._windows import _native_volume_root
    assert _native_volume_root(123) is True
    native_evidence["guid_path"] += "child"
    assert _native_volume_root(123) is False
    native_evidence["guid_path"] = "\\\\?\\Volume{00000000-0000-0000-0000-000000000002}\\"
    with pytest.raises(_ScheduleArtifactError):
        _native_volume_root(123)


@pytest.mark.parametrize("key,value", (("directory", 0), ("attributes", 0), ("attributes", 0x410),
    ("tag", 0xA0000003), ("serial", 0), ("identifier", 0), ("delete_pending", 1), ("drive_type", 4)))
def test_native_volume_root_requires_live_nonreparse_local_directory(native_evidence, key, value):
    from market_vault.schedule_artifact._windows import _native_volume_root
    native_evidence[key] = value
    with pytest.raises(_ScheduleArtifactError):
        _native_volume_root(123)


def test_caller_boolean_cannot_establish_volume_root(native_evidence):
    from market_vault.schedule_artifact._windows import _native_volume_root
    facts = (CURRENT, 0x1000, (), b"sd")
    with pytest.raises(TypeError):
        _access_boundary(facts, CURRENT, ancestor=True, volume_root=True)
    for value in (True, False, None, 0, -1, "C:\\"):
        with pytest.raises(_ScheduleArtifactError):
            _native_volume_root(value)


@pytest.mark.parametrize("principal", ("S-1-1-0", "S-1-5-11", "S-1-5-32-545", "S-1-5-21-1-2-3-1002"))
@pytest.mark.parametrize("mask", (2, 4, 0x10, 0x40, 0x100, 0x10000, 0x40000, 0x80000, 0x10000000, 0x40000000))
def test_windows_untrusted_mutation_grant_fails(principal, mask):
    facts = (CURRENT, 0x1000, ((0, 0, 0x1f01ff, CURRENT), (0, 0, mask, principal)), b"sd")
    with pytest.raises(_ScheduleArtifactError):
        _access_boundary(facts, CURRENT, ancestor=False)


def test_parent_sibling_creation_is_not_delete_child_authority():
    facts = ("S-1-5-18", 0, ((0, 0, 2 | 4, "S-1-5-11"),), b"sd")
    _access_boundary(facts, CURRENT, ancestor=True)
    with pytest.raises(_ScheduleArtifactError):
        _access_boundary(facts, CURRENT, ancestor=False)
    with pytest.raises(_ScheduleArtifactError):
        _access_boundary((facts[0], 0, ((0, 0, 0x40, "S-1-5-11"),), b"sd"), CURRENT, ancestor=True)


def test_protected_private_child_and_trusted_owner_required():
    entries = tuple((0, 3, 0x1f01ff, sid) for sid in (CURRENT, "S-1-5-18", "S-1-5-32-544"))
    _access_boundary((CURRENT, 0x1000, entries, b"sd"), CURRENT, ancestor=False)
    for owner, control in ((CURRENT, 0), ("S-1-1-0", 0x1000)):
        with pytest.raises(_ScheduleArtifactError):
            _access_boundary((owner, control, entries, b"sd"), CURRENT, ancestor=False)


def test_inherited_ace_is_not_ignored():
    with pytest.raises(_ScheduleArtifactError):
        _access_boundary((CURRENT, 0x1000, ((0, 0x10, 0x10000, "S-1-5-11"),), b"sd"), CURRENT, ancestor=False)


def test_linux_native_adapter_refuses_windows():
    if os.name != "nt":
        pytest.skip("Windows-only unavailable-API refusal")
    from market_vault.schedule_artifact._linux import _native
    with pytest.raises(_ScheduleArtifactError):
        _native()



# The tests below never change a production registry or repair an unsafe host.
import ast
import errno
import inspect
from pathlib import Path, PureWindowsPath
import shutil
import socket
import subprocess
import sys

from market_vault.schedule_artifact import _physical, _platform, _linux, _windows
from test_schedule_artifact_physical import _tree


def test_new_modules_are_read_only_by_construction():
    root = Path(__file__).resolve().parents[1] / "src/market_vault/schedule_artifact"
    forbidden = {"remove", "unlink", "unlinkat", "rename", "renameat", "renameat2",
        "replace", "rmtree", "chmod", "fchmod", "chown", "fchown", "mkdir", "rmdir",
        "write", "write_bytes", "write_text", "truncate", "ftruncate", "system",
        "popen", "subprocess", "shutil", "socket", "requests", "urllib", "moomoo"}
    prefixes = ("MoveFile", "DeleteFile", "RemoveDirectory", "CreateDirectory",
                "WriteFile", "SetFile", "SetSecurity", "SetNamedSecurity", "FlushFile")
    allowed_imports = {"ctypes", "os", "pathlib", "re", "stat", "sys", "dataclasses", "types"}
    # _semantics is imported by _physical only to sequence pure manifest admission
    # and logical admission; it adds no native surface and no write authority.
    relative_imports = {"_errors", "_canonical", "_models", "_paths", "_platform", "_identity",
                        "_windows", "_linux", "_semantics"}
    for name in ("_paths.py", "_windows.py", "_linux.py", "_platform.py", "_physical.py"):
        tree = ast.parse((root / name).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name in allowed_imports for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                assert (node.level == 1 and node.module in relative_imports) or (node.level == 0 and node.module in allowed_imports)
            if isinstance(node, (ast.Name, ast.Attribute)):
                word = node.id if isinstance(node, ast.Name) else node.attr
                assert word not in forbidden and not word.startswith(prefixes)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert not node.value.startswith(prefixes)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
                assert len(node.args) == 2 and isinstance(node.args[1], ast.Constant) and node.args[1].value == "rb"
    native = ast.parse(inspect.getsource(_windows))
    opens = [n for n in ast.walk(native) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_create"]
    assert len(opens) == 2
    assert {n.args[1].value for n in opens} == {0x20081, 0x80000000}
    assert all(n.args[4].value == 3 for n in opens)  # OPEN_EXISTING only.
    assert "_new_directory" not in inspect.getsource(_windows)
    assert "_QUALIFIED_CAPABILITIES" not in inspect.getsource(_windows)
    assert "os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK" in inspect.getsource(_linux)
    assert "os.pread" in inspect.getsource(_linux)


@pytest.fixture
def mechanics_scope(tmp_path):
    try:
        scope = _physical._NativeScope(tmp_path)
    except (OSError, _ScheduleArtifactError) as exc:
        pytest.skip("MECHANICS_TEST_ONLY unavailable native ancestry: " + str(exc))
    try:
        yield scope
    finally:
        scope.close()


def test_real_candidate_remains_unqualified(mechanics_scope, capsys):
    try:
        capability = _platform._capability(mechanics_scope)
    except (OSError, _ScheduleArtifactError) as exc:
        pytest.skip("MECHANICS_TEST_ONLY capability unavailable: " + str(exc))
    with pytest.raises(_ScheduleArtifactError, match="PLATFORM_UNQUALIFIED"):
        _platform._require_qualified(mechanics_scope)
    assert _platform._QUALIFIED_CAPABILITIES == frozenset()
    with capsys.disabled():
        print("L4_NATIVE_READER_MECHANICS_CANDIDATE=" + repr(capability))
        print("L4_READER_PLATFORM_QUALIFIED=false")


def test_real_retained_native_capture_and_second_closure(tmp_path, mechanics_scope):
    root = _tree(tmp_path)
    try:
        capture = _physical._capture_members(mechanics_scope, root)
    except _ScheduleArtifactError as exc:
        if os.name == "nt" and exc.reason_code == "UNSAFE_PATH":
            pytest.skip("MECHANICS_TEST_ONLY protected ACL fixture unavailable; no ACL repair: " + str(exc))
        raise
    with capture:
        assert len(capture.evidence) == 7
        capture.recheck()
        assert capture.data["schedule.json"] == b"{}\n"
        assert capture.evidence["schedule.json"].size == 3
        assert capture.hashes["schedule.json"]
        assert capture.evidence[""].filesystem == mechanics_scope.filesystem


@pytest.mark.skipif(sys.platform != "linux", reason="Linux native mechanics only")
@pytest.mark.parametrize("fault", ["bytes", "same_bytes", "other_bytes", "root", "missing", "extra", "mode", "case"])
def test_real_linux_drift(tmp_path, mechanics_scope, fault):
    root = _tree(tmp_path)
    with _physical._capture_members(mechanics_scope, root) as capture:
        path = root / "schedule.json"
        if fault == "bytes":
            path.write_bytes(b"[]\n")
        elif fault in ("same_bytes", "other_bytes"):
            path.rename(tmp_path / "retained-original")
            path.write_bytes(b"{}\n" if fault == "same_bytes" else b"[]\n")
        elif fault == "root":
            root.rename(tmp_path / "retained-root")
            _tree(tmp_path)
        elif fault == "missing":
            path.rename(tmp_path / "missing")
        elif fault == "extra":
            (root / "extra").write_bytes(b"")
        elif fault == "mode":
            path.chmod(0o644 if path.stat().st_mode & 0o077 == 0 else 0o600)
        else:
            path.rename(root / "Schedule.json")
        with pytest.raises(_ScheduleArtifactError, match="PHYSICAL_DRIFT|INVENTORY_MISMATCH"):
            capture.recheck()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux native mechanics only")
@pytest.mark.parametrize("kind", ["hardlink", "symlink", "fifo", "socket", "directory", "xattr"])
def test_real_linux_nonregular_or_unqualified_member(tmp_path, mechanics_scope, kind):
    root = _tree(tmp_path)
    path = root / "schedule.json"
    path.rename(tmp_path / "original")
    sock = None
    try:
        if kind == "hardlink":
            os.link(tmp_path / "original", path)
        elif kind == "symlink":
            path.symlink_to(tmp_path / "original")
        elif kind == "fifo":
            os.mkfifo(path)
        elif kind == "socket":
            sock = socket.socket(socket.AF_UNIX)
            socket_path = tmp_path / "socket"
            sock.bind(str(socket_path))
            socket_path.rename(path)
        elif kind == "directory":
            path.mkdir()
        else:
            path.write_bytes(b"{}\n")
            try:
                os.setxattr(path, "user.l4_mechanics", b"test")
            except OSError as exc:
                pytest.skip("native xattr fixture unavailable: " + str(exc))
        with pytest.raises(_ScheduleArtifactError, match="UNSAFE_PATH"):
            _physical._capture_members(mechanics_scope, root)
    finally:
        if sock is not None:
            sock.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows native mechanics only")
def test_windows_real_fileid_size_and_repeat_read_if_protected(tmp_path):
    path = tmp_path / "schedule.json"
    path.write_bytes(b"{}\n")
    try:
        held = _windows._WindowsObject(path, directory=False, current_sid=_windows._current_sid())
    except _ScheduleArtifactError as exc:
        pytest.skip("MECHANICS_TEST_ONLY protected ACL fixture unavailable; no host ACL change: " + str(exc))
    try:
        assert len(held.identity[1]) == 16 and held.filesystem[3] == "NTFS"
        assert held.size == 3
        assert held.read_bytes(3) == held.read_bytes(3) == b"{}\n"
        held.recheck()
    finally:
        held.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows native mechanics only")
def test_windows_real_hardlink_refused_before_acl(tmp_path):
    path = tmp_path / "schedule.json"
    path.write_bytes(b"{}\n")
    os.link(path, tmp_path / "manifest.json")
    with pytest.raises(_ScheduleArtifactError, match="hard-linked"):
        _windows._WindowsObject(path, directory=False, current_sid=_windows._current_sid())


@pytest.mark.skipif(os.name != "nt", reason="Windows native mechanics only")
def test_windows_actual_named_stream_is_observable(tmp_path):
    path = tmp_path / "schedule.json"
    path.write_bytes(b"{}\n")
    Path(str(path) + ":extra").write_bytes(b"x")
    handle = _windows._create(str(path), 0x20081, 7, None, 3, 0x02200000, None)
    assert handle != ctypes.c_void_p(-1).value
    try:
        assert ":extra:$DATA" in _windows._streams(handle)
    finally:
        _windows._close(handle)


@pytest.mark.skipif(os.name != "nt", reason="Windows native mechanics only")
def test_windows_real_reparse_refused_without_acl_repair(tmp_path):
    original = tmp_path / "source"
    original.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(original, target_is_directory=True)
    except OSError as exc:
        pytest.skip("native reparse fixture unavailable: " + str(exc))
    with pytest.raises(_ScheduleArtifactError, match="reparse"):
        _windows._WindowsObject(link, directory=True, current_sid=_windows._current_sid())


@pytest.mark.parametrize("defect", ["stream", "hardlink", "delete_pending", "reparse", "wrong_type"])
def test_windows_retained_object_facts_fail_closed_at_native_evidence(native_evidence, monkeypatch, defect):
    native = _windows
    original_info = native._info
    def info(handle, code, pointer, size):
        original_info(handle, code, pointer, size)
        if code == 1:
            value = ctypes.cast(pointer, ctypes.POINTER(native._StandardInfo)).contents
            value.directory = defect == "wrong_type"
            value.links = 2 if defect == "hardlink" else 1
            value.delete_pending = defect == "delete_pending"
        if code == 9:
            value = ctypes.cast(pointer, ctypes.POINTER(native._TagInfo)).contents
            value.attributes = 0x400 if defect == "reparse" else (0x10 if defect == "wrong_type" else 0)
        return 1
    monkeypatch.setattr(native, "_info", info)
    monkeypatch.setattr(native, "_streams", lambda handle: ("::$DATA", ":extra:$DATA"))
    monkeypatch.setattr(native, "_security_facts", lambda handle: (CURRENT, 0x1000, (), b"sd"))
    def volume_info(handle, name, name_size, serial, maximum, flags, fs, fs_size):
        ctypes.cast(serial, ctypes.POINTER(native.w.DWORD)).contents.value = 17
        ctypes.cast(flags, ctypes.POINTER(native.w.DWORD)).contents.value = 8
        fs.value = "NTFS"
        return 1
    monkeypatch.setattr(native, "_volume_info", volume_info, raising=False)
    held = native._WindowsObject.__new__(native._WindowsObject)
    held.path, held.directory, held.current_sid, held.ancestor, held.handle = PureWindowsPath("Z:\\"), False, CURRENT, False, 123
    with pytest.raises(_ScheduleArtifactError, match="INVENTORY_MISMATCH|UNSAFE_PATH"):
        held._facts()


VOLUME = "\\\\?\\Volume{00000000-0000-0000-0000-000000000001}\\"
ARTIFACT = PureWindowsPath("Z:\\sched\\schedule_artifact_id=" + "a" * 64)


@pytest.fixture
def stream_facts(monkeypatch):
    """Deterministic native evidence for the MEMBER_TREE_ZERO_STREAM policy.

    Only _streams() carries the stream surface; every other native fact is held
    constant so a reason code can be attributed to stream handling alone.
    """
    from market_vault.schedule_artifact import _windows as native
    state = dict(streams=("::$DATA",), directory=0)

    def info(handle, code, pointer, size):
        assert handle == 123
        kind = {18: native._IdInfo, 9: native._TagInfo, 1: native._StandardInfo}[code]
        assert size == ctypes.sizeof(kind)
        record = ctypes.cast(pointer, ctypes.POINTER(kind)).contents
        if code == 18:
            record.serial, record.identifier[0] = 17, 1
        elif code == 9:
            record.attributes, record.tag = (0x10 if state["directory"] else 0), 0
        else:
            record.directory = state["directory"]
            record.delete_pending, record.links, record.size = 0, 1, 0
        return 1

    def volume_path(path, buffer, size):
        assert path in (str(ARTIFACT), str(ARTIFACT / "schedule.json"))
        buffer.value = "Z:\\"
        return 1

    def volume_name(mount, buffer, size):
        assert mount.value == "Z:\\"
        buffer.value = VOLUME
        return 1

    def volume_info(handle, name, name_size, serial, maximum, flags, fs, fs_size):
        ctypes.cast(serial, ctypes.POINTER(native.w.DWORD)).contents.value = 17
        ctypes.cast(flags, ctypes.POINTER(native.w.DWORD)).contents.value = 8
        fs.value = "NTFS"
        return 1

    def handle_path(handle, flags):
        if flags:
            return VOLUME
        # _facts compares this native DOS spelling against the held object path.
        return "\\\\?\\" + str(ARTIFACT if state["directory"] else ARTIFACT / "schedule.json")

    monkeypatch.setattr(native, "_info", info, raising=False)
    monkeypatch.setattr(native, "_file_type", lambda handle: 1, raising=False)
    monkeypatch.setattr(native, "_create", lambda *args: 123, raising=False)
    monkeypatch.setattr(native, "_close", lambda handle: None, raising=False)
    monkeypatch.setattr(native, "_native_volume_root", lambda handle: True, raising=False)
    monkeypatch.setattr(native, "_handle_path", handle_path, raising=False)
    monkeypatch.setattr(native, "_volume_path", volume_path, raising=False)
    monkeypatch.setattr(native, "_volume_name", volume_name, raising=False)
    monkeypatch.setattr(native, "_drive_type", lambda mount: 3, raising=False)
    monkeypatch.setattr(native, "_volume_info", volume_info, raising=False)
    monkeypatch.setattr(native, "_security_facts", lambda handle: (CURRENT, 0x1000, (), b"sd"))
    monkeypatch.setattr(native, "_streams", lambda handle: tuple(state["streams"]))

    def synthetic_init(self, path, *, directory, current_sid, ancestor=False):
        """Constructor double for the production same-path second open in recheck().

        recheck() re-opens the retained path through _WindowsObject(...) so that a
        same-path replacement is re-observed rather than trusted. The only
        host-specific requirement of that constructor is the platform gate; every
        native primitive it consumes is already modelled deterministically above.
        This double therefore mirrors the production field set and field order and
        still obtains identity, filesystem, security, size and streams through the
        real patched _facts() path. It is scoped to this fixture and replaces
        neither recheck() nor _facts().
        """
        state["directory"] = 1 if directory else 0
        # Path(str(...)) preserves the fixture's Windows spelling on a POSIX host,
        # where an nt->posix flavour conversion would rewrite the separators.
        self.path = Path(str(path))
        self.directory, self.current_sid, self.ancestor = directory, current_sid, ancestor
        self.handle = native._create(str(path), 0x00020081, 7, None, 3, 0x02200000, None)
        try:
            self.identity, self.filesystem, self.security, self.size, self.streams = self._facts()
        except BaseException:
            self.close()
            raise

    monkeypatch.setattr(native._WindowsObject, "__init__", synthetic_init)
    return state


def _held_native(stream_facts, ancestor, *, directory=False):
    """Construct a native object whose fakes describe the requested object kind."""
    stream_facts["directory"] = 1 if directory else 0
    held = _windows._WindowsObject.__new__(_windows._WindowsObject)
    held.path = ARTIFACT if directory else ARTIFACT / "schedule.json"
    held.directory, held.current_sid = directory, CURRENT
    held.ancestor, held.handle = ancestor, 123
    return held


def _capture_native(held):
    held.identity, held.filesystem, held.security, held.size, held.streams = held._facts()
    return held


# ---------------------------------------------------------------------------
# Stream-set policy: member/tree zero named streams, retained ancestry tolerated.
# These are reader mechanics probes only; they are not platform qualification.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("directory", [True, False], ids=["artifact_directory", "fixed_member"])
@pytest.mark.parametrize("streams", [
    ("::$DATA", ":extra:$DATA"),                 # one extra named data stream
    ("::$DATA", ":a:$DATA", ":b:$DATA"),         # multiple extra named data streams
    (":only:$DATA",),                            # named stream without the default
])
def test_extra_named_stream_rejected_for_tree_and_members(stream_facts, directory, streams):
    """T1/T2: an extra named stream is rejected for the artifact object either way."""
    stream_facts["streams"] = streams
    with pytest.raises(_ScheduleArtifactError, match="INVENTORY_MISMATCH"):
        _held_native(stream_facts, False, directory=directory)._facts()


@pytest.mark.parametrize("directory", [True, False], ids=["artifact_directory", "fixed_member"])
@pytest.mark.parametrize("streams", [
    (),                                          # empty native no-more-streams result
    ("::$DATA",),                                # default unnamed stream only
])
def test_zero_named_stream_states_admitted_for_tree_and_members(stream_facts, directory, streams):
    """A proved empty set and a default-only stream are both admitted."""
    stream_facts["streams"] = streams
    held = _capture_native(_held_native(stream_facts, False, directory=directory))
    assert held.streams == tuple(sorted(streams))
    held.recheck()


@pytest.mark.parametrize("streams", [
    (),
    ("::$DATA",),
    ("::$DATA", ":extra:$DATA"),
    ("::$DATA", ":a:$DATA", ":b:$DATA"),
    (":only:$DATA",),
])
def test_retained_ancestor_admits_any_named_stream_set(stream_facts, streams):
    """T3: named streams above the artifact directory are not an admission failure."""
    stream_facts["streams"] = streams
    held = _capture_native(_held_native(stream_facts, True, directory=True))
    assert held.streams == tuple(sorted(streams))
    held.recheck()


def test_ancestor_tolerance_does_not_leak_onto_artifact_directory(stream_facts):
    """T10: admission is decided by the ancestor flag, never lexical parenthood."""
    stream_facts["streams"] = ("::$DATA", ":extra:$DATA")
    accepted = _capture_native(_held_native(stream_facts, True, directory=True))
    with pytest.raises(_ScheduleArtifactError, match="INVENTORY_MISMATCH"):
        _held_native(stream_facts, False, directory=True)._facts()
    # The tolerated object still carries the exact observed set as evidence.
    assert accepted.streams == ("::$DATA", ":extra:$DATA")
    assert accepted.ancestor is True


def test_ancestor_stream_set_stability_and_enumeration_order(stream_facts):
    """T4/T5: the same set is stable, and enumeration order is not evidence."""
    baseline = ("::$DATA", ":extra:$DATA")
    stream_facts["streams"] = baseline
    held = _capture_native(_held_native(stream_facts, True, directory=True))
    for enumeration in [baseline,
                        (":extra:$DATA", "::$DATA"),
                        tuple(reversed(baseline))]:
        stream_facts["streams"] = enumeration
        held.recheck()
    assert held.streams == baseline


@pytest.mark.parametrize("later,label", [
    (("::$DATA", ":extra:$DATA", ":added:$DATA"), "addition"),
    (("::$DATA",), "removal"),
    (("::$DATA", ":other:$DATA"), "replacement"),
])
def test_ancestor_stream_set_change_is_physical_drift(stream_facts, later, label):
    """T6/T7/T8: addition, removal and replacement are PHYSICAL_DRIFT."""
    stream_facts["directory"] = 1
    stream_facts["streams"] = ("::$DATA", ":extra:$DATA")
    held = _capture_native(_held_native(stream_facts, True, directory=True))
    baseline = held.streams
    assert baseline == ("::$DATA", ":extra:$DATA"), label
    stream_facts["streams"] = later
    with pytest.raises(_ScheduleArtifactError, match="PHYSICAL_DRIFT"):
        held.recheck()
    assert held.streams == baseline  # never rebaselined by an observation


def test_detected_ancestor_stream_drift_is_not_rebaselined(stream_facts):
    """T9: a drifted set never becomes a new accepted baseline."""
    stream_facts["directory"] = 1
    stream_facts["streams"] = ("::$DATA", ":extra:$DATA")
    held = _capture_native(_held_native(stream_facts, True, directory=True))
    baseline = held.streams
    stream_facts["streams"] = ("::$DATA", ":drift:$DATA")
    for attempt in range(3):
        with pytest.raises(_ScheduleArtifactError, match="PHYSICAL_DRIFT"):
            held.recheck()
        assert held.streams == baseline
    # Returning to the original set is still compared against the original baseline.
    stream_facts["streams"] = ("::$DATA", ":extra:$DATA")
    held.recheck()


def test_ancestor_stream_evidence_is_compared_in_second_closure(stream_facts):
    """The capture carrier compares the exact stream set, not a count or boolean."""
    stream_facts["directory"] = 1
    stream_facts["streams"] = ("::$DATA", ":extra:$DATA")
    native_held = _capture_native(_held_native(stream_facts, True, directory=True))
    captured = tuple(_physical._evidence(item) for item in [native_held])
    assert captured[0].streams == ("::$DATA", ":extra:$DATA")
    stream_facts["streams"] = ("::$DATA", ":extra:$DATA", ":added:$DATA")
    assert tuple(_physical._evidence(item) for item in [native_held]) != captured


def test_qualified_capability_registry_remains_empty():
    """T11: reader mechanics evidence is not platform qualification."""
    from market_vault.schedule_artifact import _platform
    assert _platform._QUALIFIED_CAPABILITIES == frozenset()
    assert len(_platform._QUALIFIED_CAPABILITIES) == 0


@pytest.mark.parametrize("table", [
    b"17 1 8:1 / / rw - ext4 /dev/sda1 rw\n18 1 8:1 /dir /bind rw - ext4 /dev/sda1 rw\n",
    b"17 1 8:1 /subtree / rw - ext4 /dev/sda1 rw\n",
    b"17 1 8:1 / / rw - nfs server:/ rw\n",
    b"17 1 8:2 / / rw - ext4 /dev/sda2 rw\n",
])
def test_mountinfo_binding_refuses_bind_network_and_device_mismatch(table):
    with pytest.raises(_ScheduleArtifactError, match="PLATFORM_UNQUALIFIED"):
        _linux._mount_description(table, 17, b"8:1")


def test_mountinfo_exact_ext4_record():
    assert _linux._mount_description(b"17 1 8:1 / / rw,relatime - ext4 /dev/sda1 rw\n", 17, b"8:1") == ("ext4", ("relatime", "rw"), ("rw",))


# ---------------------------------------------------------------------------
# RQP-L21: real Linux O_NOFOLLOW effectiveness under a pre-open replacement.
#
# Orchestration contract. The watched path `held` is created by the test BEFORE
# production starts (write_bytes for the file case, mkdir for the directory
# case). The exact-path one-shot os.lstat wrapper is then installed, and the
# very next statement calls production:
#
#     _linux._LinuxObject(held, ...)
#
# There is deliberately NO test-owned os.lstat(held) anywhere between arming the
# wrapper and calling production, so the wrapper fires inside production's own
# first lstat and nowhere else. That ordering, not a test-owned observation, is
# what makes the observed type the type production itself admitted.
#
# Every os.open and every O_NOFOLLOW bit exercised here is the real Linux kernel
# call issued by production _LinuxObject.__init__; no syscall, flag or errno is
# mocked, and every observed value is the kernel's own.
# ---------------------------------------------------------------------------

class _Seam:
    """A one-shot, exact-path os.lstat wrapper that fires during production.

    Scoping and ordering guarantees, all structural:

    * it fires only for an lstat whose first argument is exactly `held`;
    * it fires at most once, because `fire()` consumes the armed closure before
      anything else happens;
    * the disarm therefore happens BEFORE any mutation, so the swap can never
      recurse into a second lstat or re-arm itself;
    * it returns the original, real stat object unmodified, so production sees
      exactly what a real lstat produced.
    """

    def __init__(self, monkeypatch, held, replacement):
        self.held, self.replacement = held, replacement
        self.armed, self.observation, self.calls = [], None, []
        real_lstat, target = os.lstat, str(held)

        def lstat(path, *args, **kwargs):
            observed = real_lstat(path, *args, **kwargs)
            self.calls.append(str(path))
            if self.armed and str(path) == target:
                self.fire(observed)
            return observed

        monkeypatch.setattr(os, "lstat", lstat)

    def fire(self, observed):
        """Disarm, then mutate, then hand the untouched real observation back."""
        self.armed.pop()
        self.observation = _Observation(observed.st_mode, observed.st_ino, observed.st_dev)
        self.replacement.replace(self.held)
        return observed


class _Observation:
    """The stat fields the seam must record, snapshotted from the real lstat.

    Only the three fields the race assertions actually need are retained. The
    real os.stat_result object itself is returned to production untouched; it is
    NOT proxied or reconstructed, so production's own st_dev/st_ino comparison
    reads the genuine object.
    """

    def __init__(self, mode, inode, device):
        self.mode, self.inode, self.device = mode, inode, device


class _Replacement:
    """An exactly described real replacement of one existing `held` path."""

    def __init__(self, held, action, verify):
        self.held, self._action, self._verify = held, action, verify

    def replace(self, held):
        assert str(held) == str(self.held), "the seam is exact-path scoped"
        assert not self.held.is_symlink(), "the real watched object must pre-exist"
        self._action()
        self._verify()


def _real_symlink_replacement(held, target, target_is_directory=False):
    """Rename the real watched object aside, then plant a real symlink at `held`."""
    retained = held.with_name(held.name + ".retained-original")

    def action():
        held.rename(retained)
        held.symlink_to(target, target_is_directory=target_is_directory)

    def verify():
        assert held.is_symlink()
        assert not retained.is_symlink()
        assert retained.is_dir() if target_is_directory else retained.is_file()
        assert os.path.realpath(held) == os.path.realpath(target)

    return _Replacement(held, action, verify)


def _real_regular_swap_replacement(held, planted):
    """Rename the real watched object aside, then plant another REAL regular file.

    The original is retained under a distinct name and the pre-staged real regular
    file is moved onto `held`, so the path holds a real regular file whose
    device/inode is not the identity the lstat observation recorded.
    """
    retained = held.with_name(held.name + ".retained-original")

    def action():
        held.rename(retained)
        planted.rename(held)

    def verify():
        assert held.is_file() and not held.is_symlink()
        assert retained.is_file() and not retained.is_symlink()

    return _Replacement(held, action, verify)


class _Race:
    """The outcome of the one production call made after the seam was armed."""

    def __init__(self, returned, raised):
        self.returned, self.raised = returned, raised


def _call_production(held, *, directory):
    """The ONLY call between arming the seam and production's own lstat.

    Nothing test-owned may touch `held` in between, so the seam can only ever be
    consumed by production. A successful return is closed here so a fixture that
    unexpectedly succeeds cannot leak a descriptor.
    """
    try:
        return _Race(_linux._LinuxObject(held, directory=directory), None)
    except BaseException as exc:
        return _Race(None, exc)


def _symlink_race(tmp_path, monkeypatch, *, directory, target_is_directory):
    """Shared setup for the symlink-replacement races.

    `held` is created as a REAL object first: a regular file, or a directory for
    the O_DIRECTORY path. The target holds attacker bytes whose consumption would
    prove the link was followed.
    """
    held, target = tmp_path / "held", tmp_path / "target"
    if directory:
        held.mkdir()
        target.mkdir()
        (target / "schedule.json").write_bytes(b"ATTACKER\n")
    else:
        held.write_bytes(b"{}\n")
        target.write_bytes(b"ATTACKER\n")
    seam = _Seam(monkeypatch, held,
                 _real_symlink_replacement(held, target, target_is_directory=target_is_directory))
    seam.armed.append(seam.replacement.replace)
    return held, target, seam


@pytest.mark.skipif(sys.platform != "linux", reason="Linux native mechanics only")
def test_rqp_l21_real_no_follow_refuses_symlink_planted_after_lstat(tmp_path, monkeypatch):
    """A pre-existing real file is lstat-ed by production, then replaced by a real symlink.

    Order proved here, and only production's own lstat may observe step 1:

      1. the real watched object exists at `held` before production starts;
      2. the seam fires INSIDE production's first os.lstat, which therefore
         observes a real regular file with the kernel's own mode bits;
      3. the seam disarms itself and only then plants a real symlink at `held`;
      4. production continues into its real os.open with the real O_NOFOLLOW bit.
    """
    held, target, seam = _symlink_race(tmp_path, monkeypatch, directory=False, target_is_directory=False)
    assert not held.is_symlink(), "the watched path must pre-exist as a real object"
    race = _call_production(held, directory=False)

    # 2: production's own lstat saw a real regular file, not a symlink.
    assert seam.observation is not None, "the seam never fired inside production's lstat"
    assert stat.S_ISREG(seam.observation.mode)
    assert not stat.S_ISLNK(seam.observation.mode)
    assert (seam.observation.inode, seam.observation.device) != (0, 0)

    # The wrapper was never re-armed, and nothing test-owned observed `held`.
    assert seam.armed == [], "the one-shot seam must be fully consumed"
    assert seam.calls.count(str(held)) == 1, "the seam must fire for the held path exactly once"

    # 3: the real symlink now sits at the same path.
    assert held.is_symlink()
    assert stat.S_ISREG(os.lstat(target).st_mode)

    # 4: the real O_NOFOLLOW open is refused and the refusal fails closed.
    assert race.returned is None, "a real symlink must never be admitted"
    assert isinstance(race.raised, OSError)
    assert not isinstance(race.raised, _ScheduleArtifactError)

    # The link was not followed and the attacker bytes were never reached.
    assert held.is_symlink()
    assert target.read_bytes() == b"ATTACKER\n"


@pytest.mark.skipif(sys.platform != "linux", reason="Linux native mechanics only")
def test_rqp_l21_direct_kernel_control_on_the_identical_real_symlink(tmp_path, monkeypatch):
    """Direct real-kernel control: normal open follows the link, O_NOFOLLOW refuses.

    The control runs on exactly the same real symlink object production refuses,
    so the only difference between the control opens is the O_NOFOLLOW bit.
    Nothing is mocked here: these are real os.open calls issued by the test.
    """
    held, target, seam = _symlink_race(tmp_path, monkeypatch, directory=False, target_is_directory=False)
    race = _call_production(held, directory=False)
    assert race.returned is None
    assert stat.S_ISREG(seam.observation.mode)
    assert held.is_symlink()

    # The recorded observation is the kernel's own lstat of the pre-replacement
    # real object, distinct from the identity the symlink target now has.
    assert seam.observation.inode == os.lstat(held.with_name(held.name + ".retained-original")).st_ino

    # Control A: without O_NOFOLLOW the real kernel follows the symlink.
    followed = os.open(held, os.O_RDONLY)
    try:
        assert os.fstat(followed).st_ino == os.lstat(target).st_ino
        assert os.fstat(followed).st_ino != seam.observation.inode
        assert os.pread(followed, 64, 0) == b"ATTACKER\n"
    finally:
        os.close(followed)

    # Control B: with the production bit set the real kernel refuses.
    with pytest.raises(OSError) as direct:
        os.open(held, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    assert direct.value.errno == errno.ELOOP

    # The production refusal is the same kernel effect as Control B, compared by
    # errno rather than by exception class so that a future normalization of the
    # error surface does not invalidate the race evidence.
    assert isinstance(race.raised, OSError)
    assert race.raised.errno == direct.value.errno
    print("RQP_L21_CURRENT_ERROR_SURFACE_TYPE=%s" % type(race.raised).__name__)
    print("RQP_L21_CURRENT_ERROR_SURFACE_ERRNO=%s" % race.raised.errno)
    print("RQP_L21_NOFOLLOW_REPLACEMENT_NOT_FOLLOWED=true")
    print("RQP_L21_TARGET_BYTES_NOT_CONSUMED=true")
    print("RQP_L21_ACQUISITION_FAILS_CLOSED=true")

    # Nothing consumed the target bytes, under either control.
    assert target.read_bytes() == b"ATTACKER\n"


@pytest.mark.skipif(sys.platform != "linux", reason="Linux native mechanics only")
def test_rqp_l21_real_no_follow_refuses_directory_symlink(tmp_path, monkeypatch):
    """The directory acquisition path requests O_DIRECTORY and the same no-follow bit."""
    held, target, seam = _symlink_race(tmp_path, monkeypatch, directory=True, target_is_directory=True)
    assert held.is_dir() and not held.is_symlink(), "the watched directory must pre-exist"
    race = _call_production(held, directory=True)

    # Production's own lstat observed a real directory.
    assert seam.observation is not None, "the seam never fired inside production's lstat"
    assert stat.S_ISDIR(seam.observation.mode)
    assert not stat.S_ISLNK(seam.observation.mode)
    assert seam.armed == []
    assert seam.calls.count(str(held)) == 1

    # The directory symlink is refused and its contents are untouched.
    assert race.returned is None
    assert isinstance(race.raised, OSError)
    assert not isinstance(race.raised, _ScheduleArtifactError)
    assert held.is_symlink()
    assert (target / "schedule.json").read_bytes() == b"ATTACKER\n"


@pytest.mark.skipif(sys.platform != "linux", reason="Linux native mechanics only")
def test_rqp_l21_swapped_regular_object_is_caught_by_identity_comparison(tmp_path, monkeypatch):
    """A permitted REAL open of a substituted regular file still fails on identity.

    This is the residual case O_NOFOLLOW cannot address: the replacement is itself
    a real regular file, so the kernel has no reason to refuse the open. The real
    watched object is moved aside, a DIFFERENT real regular file is moved onto the
    same path, and production's own device/inode comparison must reject it.
    """
    held, planted = tmp_path / "held", tmp_path / "planted-file"
    held.write_bytes(b"ORIGINAL\n")
    planted.write_bytes(b"ATTACKER\n")
    seam = _Seam(monkeypatch, held, _real_regular_swap_replacement(held, planted))
    seam.armed.append(seam.replacement.replace)
    race = _call_production(held, directory=False)

    # Production's own lstat observed the ORIGINAL inode, before the swap.
    assert seam.observation is not None
    assert stat.S_ISREG(seam.observation.mode)
    assert seam.armed == []
    assert seam.observation.inode == os.lstat(held.with_name(held.name + ".retained-original")).st_ino

    # The real os.open succeeded on a real regular file; only identity comparison
    # can catch the substitution, and it must.
    assert held.is_file() and not held.is_symlink()
    assert race.returned is None, "a substituted regular file must never be admitted"
    assert isinstance(race.raised, _ScheduleArtifactError)
    assert race.raised.reason_code == "UNSAFE_PATH"
    assert "object changed during open" in str(race.raised)

    # The substituted bytes are still on disk and were never read as the artifact.
    assert held.read_bytes() == b"ATTACKER\n"


def test_rqp_l21_race_invariants_are_structural_not_error_surface():
    """The durable RQP-L21 contract is the race outcome, not a specific exception type.

    A future normalization from the raw kernel OSError to a reader reason code must
    NOT be prohibited by this tests-only qualification work, so no static rule here
    requires the acquisition to stay outside try/except. What is pinned instead is
    the orchestration that makes the native races attributable: the watched path
    pre-exists, the seam fires only inside production's own lstat for that exact
    path, the wrapper disarms before it mutates, and the unmodified real stat
    object is what production receives.
    """
    module = ast.parse(inspect.getsource(_linux))
    class_node = next(node for node in ast.walk(module) if isinstance(node, ast.ClassDef)
                      and node.name == "_LinuxObject")
    init = next(node for node in class_node.body if isinstance(node, ast.FunctionDef)
                and node.name == "__init__")

    # Production's first lstat is still the lstat the seam intercepts.
    lstat_calls = [node for node in ast.walk(init) if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Attribute) and node.func.attr == "lstat"]
    assert len(lstat_calls) == 1, "the watched path must be lstat-ed exactly once"
    assert getattr(lstat_calls[0].func.value, "id", None) == "os"
    assigns = [node for node in ast.walk(init) if isinstance(node, ast.Assign)
               and node.value is lstat_calls[0]]
    assert len(assigns) == 1
    before = assigns[0].targets[0]
    assert getattr(before, "id", None) == "before"

    # That observation is still what the retained identity is compared against:
    #   self.identity[:2] == (before.st_dev, before.st_ino)
    def identity_prefix(node):
        """`self.identity[:2]`, sliced from the start."""
        if not (isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.Slice)
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "identity"):
            return False
        lower = node.slice.lower
        starts_at_zero = lower is None or (isinstance(lower, ast.Constant) and lower.value == 0)
        return starts_at_zero and isinstance(node.slice.upper, ast.Constant) and node.slice.upper.value == 2

    def reads_before(node):
        """`(before.st_dev, before.st_ino)`: fields read from the lstat observation."""
        return (isinstance(node, ast.Tuple) and len(node.elts) == 2
                and all(isinstance(element, ast.Attribute)
                        and getattr(element.value, "id", None) == "before" for element in node.elts))

    comparisons = [node for node in ast.walk(init) if isinstance(node, ast.Compare)
                   and identity_prefix(node.left)
                   and any(reads_before(comparator) for comparator in node.comparators)]
    assert comparisons, "the retained identity must still be compared with the pre-open observation"

    # And the tests defend both arms of the race.
    testfile = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    tests = {node.name for node in testfile.body if isinstance(node, ast.FunctionDef)}
    assert {"test_rqp_l21_real_no_follow_refuses_symlink_planted_after_lstat",
            "test_rqp_l21_real_no_follow_refuses_directory_symlink",
            "test_rqp_l21_swapped_regular_object_is_caught_by_identity_comparison"} <= tests
    # No test-owned os.lstat may stand between arming and production.
    for name in ("test_rqp_l21_real_no_follow_refuses_symlink_planted_after_lstat",
                 "test_rqp_l21_real_no_follow_refuses_directory_symlink",
                 "test_rqp_l21_swapped_regular_object_is_caught_by_identity_comparison"):
        tree = next(node for node in testfile.body
                    if isinstance(node, ast.FunctionDef) and node.name == name)
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == "lstat"
                 and getattr(node.func.value, "id", None) == "os"]
        production = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                      and isinstance(node.func, ast.Name) and node.func.id == "_call_production"]
        assert len(production) == 1, name
        assert all(node.lineno > production[0].lineno for node in calls), name

    # The seam's disarm is the first executable statement of fire(), before any
    # mutation, which is what makes "disarm BEFORE mutation" structural.
    seam = next(node for node in testfile.body if isinstance(node, ast.ClassDef) and node.name == "_Seam")
    fire = next(node for node in seam.body if isinstance(node, ast.FunctionDef) and node.name == "fire")
    body = [node for node in fire.body
            if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))]
    assert body, "fire() must have an executable body"
    disarm = body[0]
    assert isinstance(disarm, ast.Expr) and isinstance(disarm.value, ast.Call)
    assert getattr(disarm.value.func, "attr", None) == "pop"
    assert getattr(disarm.value.func.value, "attr", None) == "armed"


# ---------------------------------------------------------------------------
# RQP-L09: real native Linux access-control cases.
#
# Every fixture below is created by this test invocation under pytest's own
# tmp_path and is owned by the invoking user. No repository path, host path,
# pre-existing temporary file, ACL or permission outside these fixtures is
# chmod-ed, chown-ed, ACL-ed or repaired. No sudo, no package installation and
# no host mutation is used anywhere in this section.
#
# OUTCOME DISCIPLINE. Test-suite health and qualification evidence status are
# deliberately different axes:
#
#   PASS  = the real required behaviour was observed on this runner.
#   XFAIL = the required qualification evidence is unavailable here (a GAP),
#           raised with a stable QUALIFICATION_GAP message. A GAP is never a PASS.
#   FAIL  = observed behaviour violates the requirement.
#   SKIP  = the platform test is not applicable on this host.
#
# A case that cannot construct its fixture raises pytest.xfail inside the test
# body, not a bare return: returning normally would be recorded as a PASS by the
# suite while proving nothing, and a real failure would redden normal CI for an
# environmental absence. XFAIL counts in the XFAILED row, never in the PASSED row,
# so QUALIFICATION_MATRIX_PASS_ROWS can never absorb a GAP.
# ---------------------------------------------------------------------------


# Every qualification case in this file, so the accounting can report cases that
# were never executed (skipped or unselected) instead of silently omitting them.
# A conditional case appears in both registries: it records exactly one outcome --
# a real PASS when its fixture is constructible, a GAP when it is not.
RQP_L09_PASS_CASES = (
    "TRUSTED_OWNER_ADMISSION",
    "GROUP_WORLD_WRITABLE_OBJECT",
    "WRITABLE_NON_STICKY_ANCESTOR",
    "STICKY_WRITABLE_ANCESTOR_ADMITTED",
    "NON_WRITABLE_ANCESTOR_MODES",
    "STICKY_EXCEPTION_LIMITS",
    "XATTR",
    "POSIX_ACL",
    "FOREIGN_OWNER",
    "ROOT_OWNED",
)
RQP_L09_CONDITIONAL_CASES = ("XATTR", "POSIX_ACL", "FOREIGN_OWNER", "ROOT_OWNED")
RQP_L09_GAP_CASES = RQP_L09_CONDITIONAL_CASES

_QUALIFICATION_LEDGER = {"pass": [], "gap": []}


def _qualification_pass(case):
    """Record that real required behaviour was actually observed."""
    _record_outcome("pass", case)
    print("RQP_L09_REAL_PASS_CASES=%s" % case)


def _marker(case):
    """The single source of the NOT_CONSTRUCTED evidence marker."""
    return "RQP_L09_FIXTURE_%s=NOT_CONSTRUCTED" % case


def _record_outcome(row, case):
    """The single write path for a qualification outcome.

    Keeping both recoders on one audited function is what makes the PASS/GAP
    distinction structural: a case can only ever land in the row it was declared for,
    the two rows can never overlap, and a duplicate registration is rejected.
    """
    assert row in ("pass", "gap"), "unknown qualification outcome row: %r" % (row,)
    assert case in RQP_L09_PASS_CASES, "undeclared qualification case: %s" % case
    other = "gap" if row == "pass" else "pass"
    assert case not in _QUALIFICATION_LEDGER[other], \
        "a case cannot be both PASS and GAP: %s" % case
    assert case not in _QUALIFICATION_LEDGER[row], "duplicate registration: %s" % case
    _QUALIFICATION_LEDGER[row].append(case)


def _qualification_gap(case, fixture, reason, **observations):
    """Report a NOT_CONSTRUCTED qualification case and record it as a GAP.

    The evidence is printed before the xfail is raised, so the exact observed reason
    and errno survive into captured output. The message carries the stable
    QUALIFICATION_GAP marker, and the case is recorded in the GAP row only, so it can
    never be reported as a qualification PASS. Failure observations are recorded
    verbatim rather than attributed to a privilege this test did not measure.
    """
    assert case in RQP_L09_GAP_CASES, "undeclared qualification gap case: %s" % case
    _record_outcome("gap", case)
    print(_marker(case))
    print("RQP_L09_GAP_EVIDENCE_fixture=%s" % fixture)
    print("RQP_L09_GAP_EVIDENCE_reason=%s" % reason)
    for name in sorted(observations):
        print("RQP_L09_GAP_%s=%s" % (name, observations[name]))
    print("RQP_L09_GAP_CASES=%s" % case)
    pytest.xfail("QUALIFICATION_GAP: %s not constructed: %s" % (fixture, reason))


def _audit_qualification_accounting():
    """Audit the real ledger and return it.

    Proves the accounting cannot report a GAP as a PASS: no case may appear in both
    rows, and every declared case must be accounted for as a PASS, a GAP, or
    explicitly not executed. Called both by the module fixture and by a static guard.
    """
    ledger = _QUALIFICATION_LEDGER
    passed, gapped = set(ledger["pass"]), set(ledger["gap"])
    assert not passed & gapped, "a case cannot be both PASS and GAP: %r" % sorted(passed & gapped)
    assert len(ledger["pass"]) == len(passed), "duplicate PASS registration"
    assert len(ledger["gap"]) == len(gapped), "duplicate GAP registration"
    executed = passed | gapped
    ledger["executed"] = len(executed)
    ledger["not_executed"] = tuple(sorted(set(RQP_L09_PASS_CASES) - executed))
    ledger["complete"] = not ledger["not_executed"] and not gapped
    assert executed <= set(RQP_L09_PASS_CASES), "undeclared case executed"
    return ledger


@pytest.fixture(autouse=True, scope="module")
def qualification_outcome_accounting():
    """Emit machine-readable qualification accounting after this module settles.

    The counts are real per-case outcomes, not a claim about the file. The two
    required lines are always present on every platform: RQP_L09_REAL_PASS_CASES
    lists exactly the cases that produced real local qualification evidence and
    RQP_L09_GAP_CASES lists exactly the GAPs. RQP_L09_NOT_EXECUTED lists every other
    case, which is what a Windows-local run must report, because skipped Linux tests
    are not qualification evidence. The lines are printed for the normal capture
    channels, so they appear under -s and -rP and in a failure report.
    """
    yield
    ledger = _audit_qualification_accounting()
    passed, gapped = sorted(ledger["pass"]), sorted(ledger["gap"])
    not_executed = list(ledger["not_executed"])
    print("==== RQP-L09 QUALIFICATION OUTCOME ACCOUNTING ====")
    print("RQP_L09_REAL_PASS_CASES=%s" % (",".join(passed) if passed else "NONE"))
    print("RQP_L09_GAP_CASES=%s" % (",".join(gapped) if gapped else "NONE"))
    print("RQP_L09_NOT_EXECUTED=%s" % (",".join(not_executed) if not_executed else "NONE"))
    print("RQP_L09_REAL_PASS_CASE_COUNT=%d" % len(passed))
    print("RQP_L09_GAP_CASE_COUNT=%d" % len(gapped))
    print("RQP_L09_QUALIFICATION_COMPLETE=%s" % ("true" if ledger["complete"] else "false"))
    print("RQP_L09_XFAIL_IS_NOT_PASS=true")
    print("RQP_L09_SKIP_IS_NOT_EVIDENCE=true")


@pytest.mark.skipif(sys.platform != "linux", reason="Linux native mechanics only")
def test_rqp_l09_trusted_owner_admission_is_real(tmp_path):
    """Baseline: a real, safely-permissioned private fixture is admitted."""
    path = tmp_path / "schedule.json"
    path.write_bytes(b"{}\n")
    path.chmod(0o600)
    held = _linux._LinuxObject(path, directory=False)
    try:
        uid, gid, mode, attributes = held.security
        assert uid == os.geteuid()
        assert mode == 0o600
        assert attributes == ()
        assert held.size == 3
        assert held.read_bytes(3) == b"{}\n"
        held.recheck()
    finally:
        held.close()
    _qualification_pass("TRUSTED_OWNER_ADMISSION")


@pytest.mark.parametrize("mode", [0o666, 0o622, 0o602, 0o660, 0o620, 0o606])
@pytest.mark.skipif(sys.platform != "linux", reason="Linux native mechanics only")
def test_rqp_l09_group_or_world_writable_object_is_refused(tmp_path, mode):
    """Any untrusted mutation grant on the object itself is refused."""
    path = tmp_path / "schedule.json"
    path.write_bytes(b"{}\n")
    path.chmod(mode)
    with pytest.raises(_ScheduleArtifactError) as caught:
        _linux._LinuxObject(path, directory=False)
    assert caught.value.reason_code == "UNSAFE_PATH"
    assert "mutation permissions" in str(caught.value)
    _qualification_pass("GROUP_WORLD_WRITABLE_OBJECT")


@pytest.mark.skipif(sys.platform != "linux", reason="Linux native mechanics only")
def test_rqp_l09_group_or_world_writable_ancestor_is_refused_without_sticky(tmp_path):
    """A real writable, non-sticky ancestor directory is refused."""
    parent = tmp_path / "ancestor"
    parent.mkdir()
    parent.chmod(0o777)
    with pytest.raises(_ScheduleArtifactError) as caught:
        _linux._LinuxObject(parent, directory=True, ancestor=True)
    assert caught.value.reason_code == "UNSAFE_PATH"
    assert "mutation permissions" in str(caught.value)
    _qualification_pass("WRITABLE_NON_STICKY_ANCESTOR")


@pytest.mark.skipif(sys.platform != "linux", reason="Linux native mechanics only")
def test_rqp_l09_sticky_writable_ancestor_is_admitted(tmp_path):
    """The sticky-directory ancestor exception is real."""
    parent = tmp_path / "sticky"
    parent.mkdir()
    parent.chmod(0o1777)
    held = _linux._LinuxObject(parent, directory=True, ancestor=True)
    try:
        assert held.security[2] == 0o1777
        held.recheck()
    finally:
        held.close()
    _qualification_pass("STICKY_WRITABLE_ANCESTOR_ADMITTED")


@pytest.mark.parametrize("mode", [0o1700, 0o1775, 0o1755])
@pytest.mark.skipif(sys.platform != "linux", reason="Linux native mechanics only")
def test_rqp_l09_non_writable_ancestor_modes_are_trusted(tmp_path, mode):
    """Sticky alone never admits: a non-writable directory is trusted regardless."""
    parent = tmp_path / "sticky-safe"
    parent.mkdir()
    parent.chmod(mode)
    held = _linux._LinuxObject(parent, directory=True, ancestor=True)
    try:
        assert held.security[2] == mode
    finally:
        held.close()
    _qualification_pass("NON_WRITABLE_ANCESTOR_MODES")


@pytest.mark.skipif(sys.platform != "linux", reason="Linux native mechanics only")
def test_rqp_l09_sticky_exception_does_not_apply_to_non_ancestor(tmp_path):
    """The same sticky writable object is refused when it is not retained ancestry."""
    parent = tmp_path / "sticky-object"
    parent.mkdir()
    parent.chmod(0o1777)
    with pytest.raises(_ScheduleArtifactError, match="UNSAFE_PATH"):
        _linux._LinuxObject(parent, directory=True, ancestor=False)
    _qualification_pass("STICKY_EXCEPTION_LIMITS")


@pytest.mark.skipif(sys.platform != "linux", reason="Linux native mechanics only")
def test_rqp_l09_sticky_exception_does_not_apply_to_regular_object(tmp_path):
    """A sticky writable REGULAR object is not an ancestor exception."""
    path = tmp_path / "schedule.json"
    path.write_bytes(b"{}\n")
    path.chmod(0o1666)
    with pytest.raises(_ScheduleArtifactError) as caught:
        _linux._LinuxObject(path, directory=False, ancestor=True)
    assert caught.value.reason_code == "UNSAFE_PATH"
    assert "mutation permissions" in str(caught.value)
    _qualification_pass("STICKY_EXCEPTION_LIMITS")


@pytest.mark.skipif(sys.platform != "linux", reason="Linux native mechanics only")
def test_rqp_l09_extended_attribute_is_refused(tmp_path):
    """A real user extended attribute on the object is refused, or the gap recorded.

    A user extended attribute on an attacker-free fixture needs no special
    privilege; it needs only a filesystem that stores user xattrs. Where the runner's
    filesystem cannot, that is a GAP in this invocation's evidence: the case is
    reported NOT_CONSTRUCTED and XFAILED, never a PASS and never a permanent failure.
    """
    path = tmp_path / "schedule.json"
    path.write_bytes(b"{}\n")
    path.chmod(0o600)
    try:
        os.setxattr(path, "user.l4_qualification", b"present")
    except OSError as exc:
        _qualification_gap("XATTR", "user extended attribute",
                           "user extended attributes are not storable on the runner filesystem",
                           ERRNO=exc.errno, ERROR=exc)
        return
    try:
        assert "user.l4_qualification" in os.listxattr(path)
        with pytest.raises(_ScheduleArtifactError) as caught:
            _linux._LinuxObject(path, directory=False)
        assert caught.value.reason_code == "UNSAFE_PATH"
        assert "extended attributes" in str(caught.value)
    finally:
        os.removexattr(path, "user.l4_qualification")
    _qualification_pass("XATTR")


@pytest.mark.skipif(sys.platform != "linux", reason="Linux native mechanics only")
def test_rqp_l09_posix_access_acl_is_refused(tmp_path):
    """A real POSIX access ACL must be refused, or the gap recorded.

    This test does NOT claim that CAP_FOWNER is generally required for an owner to
    set an ACL on an owner-owned file. Whether `setfacl` can store
    system.posix_acl_access here depends on the runner's filesystem ACL support and
    on the utility being installed; neither is measured by this test. What is
    measured is the actual outcome, and the actual failure text is recorded verbatim
    as GAP evidence rather than attributed to a privilege this test did not observe.
    No package installation is attempted.
    """
    path = tmp_path / "schedule.json"
    path.write_bytes(b"{}\n")
    path.chmod(0o600)
    setfacl = shutil.which("setfacl")
    if setfacl is None:
        _qualification_gap("POSIX_ACL", "POSIX access ACL",
                           "no setfacl utility on this runner and no installation is authorized",
                           UTILITY_PRESENT=False)
        return
    completed = subprocess.run([setfacl, "-m", "u:%d:r--" % os.geteuid(), str(path)],
                               capture_output=True, text=True)
    if completed.returncode != 0:
        _qualification_gap("POSIX_ACL", "POSIX access ACL",
                           "the real setfacl invocation did not store an ACL (observed outcome recorded verbatim)",
                           RETURNCODE=completed.returncode, STDERR=completed.stderr.strip(),
                           UTILITY_PRESENT=True)
        return
    try:
        assert "system.posix_acl_access" in os.listxattr(path)
        with pytest.raises(_ScheduleArtifactError) as caught:
            _linux._LinuxObject(path, directory=False)
        assert caught.value.reason_code == "UNSAFE_PATH"
        assert "POSIX ACL" in str(caught.value)
    finally:
        subprocess.run([setfacl, "-b", str(path)], capture_output=True, text=True)
    _qualification_pass("POSIX_ACL")


def _ownership_fixture(path, uid, case):
    """Create a real ownership fixture, or record the observed refusal as a GAP.

    Reassigning ownership needs CAP_CHOWN. The attempt is real: a refusal by the
    kernel is recorded verbatim as GAP evidence and XFAILED, never as a permanent
    failure, and no privilege is escalated to produce the fixture. Returns True when
    the fixture was really established, False after recording a GAP.

    This is the ONLY place in this file that changes ownership, and it only ever
    touches the invocation-owned tmp_path fixture it is handed.
    """
    if os.geteuid() == uid:
        return True
    try:
        os.chown(path, uid, os.getegid())
    except OSError as exc:
        _qualification_gap(case, "uid %d owned object" % uid,
                           "the real chown to the target uid was refused by the kernel",
                           EUID=os.geteuid(), TARGET_UID=uid, ERRNO=exc.errno, ERROR=exc)
        return False
    assert os.lstat(path).st_uid == uid
    return True


@pytest.mark.skipif(sys.platform != "linux", reason="Linux native mechanics only")
def test_rqp_l09_foreign_owner_is_refused(tmp_path):
    """A real foreign-owned regular object must be refused, or the gap recorded."""
    path = tmp_path / "schedule.json"
    path.write_bytes(b"{}\n")
    path.chmod(0o600)
    foreign = 65534 if os.geteuid() != 0 else 1
    if not _ownership_fixture(path, foreign, "FOREIGN_OWNER"):
        return
    try:
        with pytest.raises(_ScheduleArtifactError) as caught:
            _linux._LinuxObject(path, directory=False)
        assert caught.value.reason_code == "UNSAFE_PATH"
        assert "untrusted Linux object owner" in str(caught.value)
    finally:
        os.chown(path, os.geteuid(), os.getegid())
    _qualification_pass("FOREIGN_OWNER")


@pytest.mark.skipif(sys.platform != "linux", reason="Linux native mechanics only")
def test_rqp_l09_root_owned_object_is_trusted(tmp_path):
    """Root ownership is trusted by the contract; the observation is real st_uid."""
    path = tmp_path / "schedule.json"
    path.write_bytes(b"{}\n")
    path.chmod(0o600)
    if not _ownership_fixture(path, 0, "ROOT_OWNED"):
        return
    held = _linux._LinuxObject(path, directory=False)
    try:
        assert held.security[0] == 0
    finally:
        held.close()
    _qualification_pass("ROOT_OWNED")


# ---------------------------------------------------------------------------
# RQP-L17: read-only feasibility of a real mount-identity/options drift fixture.
#
# Nothing here mounts, unmounts, unshares, enters a namespace or escalates
# privilege. The probe only READS whether this qualification host could ever
# produce a real drift fixture, so the matrix records a factual GAP instead of
# substituting a mock for real mount evidence.
#
# RQP-L17 REMAINS A GAP. A green feasibility probe is status reporting about the
# runner, not qualification evidence and not a PASS for the drift case itself.
# These status lines are module-level so the GAP is visible even where the native
# probe is skipped for platform reasons.
# ---------------------------------------------------------------------------

RQP_L17_STATUS = "GAP"
RQP_L17_MOUNT_OPERATIONS_PERFORMED = False

_CAPABILITY_BITS = {"CAP_DAC_READ_SEARCH": 2, "CAP_SYS_CHROOT": 18, "CAP_SYS_ADMIN": 21}


def _effective_capabilities():
    """Decode the real CapEff mask; capability N is bit N."""
    with open("/proc/self/status", "r") as stream:
        for line in stream:
            if line.startswith("CapEff:"):
                return int(line.split()[1], 16)
    raise AssertionError("CapEff absent from /proc/self/status")


@pytest.mark.skipif(sys.platform != "linux", reason="Linux native mechanics only")
def test_rqp_l17_mount_drift_fixture_feasibility_is_recorded(capsys):
    """Record, from real host state, whether a native mount-drift fixture is possible.

    The probe is read-only and performs no mount operation. A runner that cannot
    construct the fixture records RQP_L17_PRIVILEGED_FIXTURE_REQUIRED=true and RQP-L17
    stays a GAP. A runner that could construct it still has no reviewed fixture
    authorization in this invocation, so it records
    RQP_L17_PRIVILEGED_FIXTURE_REQUIRED=true with the fixture STILL not constructed.

    Either way this case is an XFAIL, not a PASS: the probe reports the runner's
    feasibility, which is status reporting about the host, not the required mount-drift
    behaviour. Neither branch fabricates mount evidence, and neither turns the absence
    of a fixture into a qualification PASS.
    """
    effective = _effective_capabilities()
    holds = {name: bool(effective >> bit & 1) for name, bit in _CAPABILITY_BITS.items()}
    available = holds["CAP_SYS_ADMIN"]
    with capsys.disabled():
        print("RQP_L17_HOST_EUID=%d" % os.geteuid())
        print("RQP_L17_CAP_EFF=0x%x" % effective)
        print("RQP_L17_CAPABILITIES=%r" % (holds,))
        print("RQP_L17_CAP_SYS_ADMIN_AVAILABLE=%s" % ("true" if available else "false"))
        # The drift fixture is not constructed on either branch: without CAP_SYS_ADMIN
        # the runner cannot build it, and with CAP_SYS_ADMIN no privileged
        # qualification-fixture authorization exists for this invocation.
        print("RQP_L17_PRIVILEGED_FIXTURE_REQUIRED=%s" % ("false" if available else "true"))
        print("RQP_L17_PRIVILEGED_FIXTURE_CONSTRUCTED=false")
        print("RQP_L17_STATUS=%s" % RQP_L17_STATUS)
        print("RQP_L17_MOUNT_OPERATIONS_PERFORMED=%s"
              % ("true" if RQP_L17_MOUNT_OPERATIONS_PERFORMED else "false"))
        reason = ("privileged mount fixture available but not authorized for this invocation"
                  if available else
                  "CAP_SYS_ADMIN absent; real mount identity/options drift not constructible here")
        print("RQP_L17_GAP_REASON=%s" % reason)
        print("RQP_L17_GAP_CASES=MOUNT_IDENTITY_OPTIONS_DRIFT")
    pytest.xfail("QUALIFICATION_GAP: real mount identity/options drift not constructed: %s" % reason)


def test_rqp_l17_capability_bit_decoding_is_exact():
    """Guard the bit-index arithmetic the feasibility probe reports from.

    A mask holding exactly CAP_SYS_ADMIN must decode to that capability alone, so
    an off-by-one or mislabelled bit cannot silently misreport which capability the
    host holds. Effective capability N is bit N of CapEff; no privilege is used.
    """
    cap_sys_admin_only = 1 << 21
    holds = {name: bool(cap_sys_admin_only >> bit & 1) for name, bit in _CAPABILITY_BITS.items()}
    assert holds == {"CAP_DAC_READ_SEARCH": False, "CAP_SYS_CHROOT": False, "CAP_SYS_ADMIN": True}
    assert not {name: bool(0 >> bit & 1) for name, bit in _CAPABILITY_BITS.items()}["CAP_SYS_ADMIN"]


def test_rqp_l17_status_is_gap_and_no_mount_was_performed():
    """RQP-L17 is not satisfied by this file, whatever the runner reports."""
    assert RQP_L17_STATUS == "GAP"
    assert RQP_L17_MOUNT_OPERATIONS_PERFORMED is False


# ---------------------------------------------------------------------------
# Static guards for the GAP discipline itself.
#
# These are plain AST checks over this file, so they run on every platform and
# cannot be skipped as "Linux-only": the properties they defend are properties of
# this test file, not of the host.
# ---------------------------------------------------------------------------

_GAP_DISCIPLINE_TESTS = (
    "_qualification_gap",
    "test_rqp_l09_extended_attribute_is_refused",
    "test_rqp_l09_posix_access_acl_is_refused",
    "test_rqp_l09_foreign_owner_is_refused",
    "test_rqp_l09_root_owned_object_is_trusted",
    "test_rqp_l17_mount_drift_fixture_feasibility_is_recorded",
)

# The qualification cases whose fixture is conditional on the runner. Each must be
# able to record a GAP by XFAIL and a real PASS, and must never report a GAP as a
# PASS by merely returning from the test body.
_CONDITIONAL_GAP_TESTS = (
    "test_rqp_l09_extended_attribute_is_refused",
    "test_rqp_l09_posix_access_acl_is_refused",
    "test_rqp_l09_foreign_owner_is_refused",
    "test_rqp_l09_root_owned_object_is_trusted",
)


def _guard_module():
    return ast.parse(Path(__file__).read_text(encoding="utf-8"))


def _guard_module_of(nodes):
    """One walkable module for a node, a list of nodes, or a module's body."""
    if isinstance(nodes, ast.Module):
        return nodes
    if isinstance(nodes, (list, tuple)):
        return ast.Module(body=list(nodes), type_ignores=[])
    return ast.Module(body=[nodes], type_ignores=[])


def _guard_attributes(nodes):
    return {node.attr for node in ast.walk(_guard_module_of(nodes))
            if isinstance(node, ast.Attribute)}


def _guard_called_attributes(nodes):
    """Attribute names of every call in `nodes`, for real syscall-level checks."""
    return {node.func.attr for node in ast.walk(_guard_module_of(nodes))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}


def _guard_executed_programs(nodes):
    """The program expression of every argv passed to subprocess.run in `nodes`."""
    programs = set()
    for node in ast.walk(ast.Module(body=list(nodes), type_ignores=[])):
        if not (isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "run"):
            continue
        if not node.args or not isinstance(node.args[0], (ast.List, ast.Tuple)):
            continue
        element = node.args[0].elts[0] if node.args[0].elts else None
        if isinstance(element, ast.Constant) and isinstance(element.value, str):
            programs.add(element.value)
        elif isinstance(element, ast.Name):
            programs.add(element.id)
    return programs


def test_gap_discipline_never_encodes_an_unavailable_fixture_as_a_failure():
    """No pytest.fail or raise may stand in for a fixture this runner cannot build.

    The named functions are exactly the GAP-recording cases. A raise or a
    pytest.fail in any of them would turn an environmental absence into a permanent
    normal-test failure. `xfail` is permitted and is the only allowed GAP outcome
    besides a genuinely constructed fixture.
    """
    functions = _guard_functions(_guard_module())
    for name in _GAP_DISCIPLINE_TESTS:
        assert name in functions, name
        assert [node for node in ast.walk(functions[name]) if isinstance(node, ast.Raise)] == [], name
        called = _guard_called_attributes(functions[name].body)
        assert "fail" not in called, name


def test_gap_discipline_raises_xfail_with_a_stable_qualification_gap_marker():
    """A GAP must be an explicit XFAIL carrying QUALIFICATION_GAP, never a return.

    Ordinary skip is not used for evidence, and a bare return from the test body is
    not used as a qualification PASS: the recorder always raises xfail, so a GAP can
    only ever appear in the XFAILED row of the suite and is machine-derivable from
    the ledger.
    """
    module = _guard_module()
    recorder = _guard_functions(module)["_qualification_gap"]
    called = _guard_called_attributes(recorder.body)
    assert "xfail" in called, "the GAP recorder must raise pytest.xfail"
    assert "fail" not in called and "skip" not in called, "a GAP is an xfail, not a failure or a skip"
    assert [node for node in ast.walk(recorder) if isinstance(node, ast.Raise)] == []
    marker = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "_marker")
    returns = [node.value for node in ast.walk(marker) if isinstance(node, ast.Return)]
    assert returns, "_marker must return the evidence marker"
    # `_marker` returns "RQP_L09_FIXTURE_%s=NOT_CONSTRUCTED" % case, so the evidence
    # literal is the left operand of the formatting BinOp. Matching it by its own
    # prefix keeps the function's docstring from being read as evidence text.
    literals = set()
    for value in returns:
        candidates = [value.left] if isinstance(value, ast.BinOp) else [value]
        literals |= {node.value for node in candidates
                     if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert {text for text in literals if text.startswith("RQP_L09_FIXTURE_")} == {
        "RQP_L09_FIXTURE_%s=NOT_CONSTRUCTED"}
    # The marker is what the recorder prints, so the two cannot drift apart.
    assert any(isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_marker"
               for node in ast.walk(recorder))


def test_gap_cases_record_xfail_or_pass_and_never_a_silent_return():
    """Every conditional qualification case either XFAILs or records a real PASS."""
    module = _guard_module()
    functions = _guard_functions(module)
    for name in _CONDITIONAL_GAP_TESTS:
        test = functions[name]
        called = _guard_called_attributes(test.body)
        assert "fail" not in called, name
        assert [node for node in ast.walk(test) if isinstance(node, ast.Raise)] == [], name
        # The body must record exactly one outcome: a GAP or a real PASS.
        assert {"_qualification_gap", "_qualification_pass"} & {
            node.func.id for node in ast.walk(test)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }, name


def test_qualification_accounting_cannot_report_a_gap_as_a_pass():
    """The ledger keeps PASS and GAP disjoint and reports unexecuted cases."""
    module = _guard_module()
    functions = _guard_functions(module)
    gap_recorder = functions["_qualification_gap"]
    pass_recorder = functions["_qualification_pass"]

    def ledger_keys(function):
        return {node.slice.value for node in ast.walk(function)
                if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)
                and getattr(node.value, "id", None) == "_QUALIFICATION_LEDGER"}

    def declared_row(function):
        return {node.args[0].value for node in ast.walk(function)
                if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_record_outcome"}

    # Both recoders write through the single audited path, and each declares only its
    # own row, so neither can write the other's row directly.
    assert "_QUALIFICATION_LEDGER" in ast.dump(functions["_record_outcome"]), \
        "the shared outcome recorder must own the ledger write"
    assert ledger_keys(functions["_qualification_pass"]) == set(), \
        "the PASS recoder must not write the ledger directly"
    assert ledger_keys(functions["_qualification_gap"]) == set(), \
        "the GAP recoder must not write the ledger directly"
    assert declared_row(functions["_qualification_pass"]) == {"pass"}
    assert declared_row(functions["_qualification_gap"]) == {"gap"}
    assert "xfail" in _guard_called_attributes(functions["_qualification_gap"].body)

    # The declared registries, and the real ledger of this run.
    assert set(RQP_L09_GAP_CASES) == set(RQP_L09_CONDITIONAL_CASES)
    assert set(RQP_L09_CONDITIONAL_CASES) <= set(RQP_L09_PASS_CASES)
    ledger = _audit_qualification_accounting()
    for case in RQP_L09_CONDITIONAL_CASES:
        assert not (case in ledger["pass"] and case in ledger["gap"]), case
    assert ledger["executed"] == len(ledger["pass"]) + len(ledger["gap"])
    if os.name != "nt" or sys.platform == "linux":
        assert ledger["executed"] == len(RQP_L09_PASS_CASES), "every case must settle on Linux"
    else:
        # A Windows-local run is not qualification evidence for any native case.
        assert ledger["pass"] == [], "no Linux-native case may claim a PASS on Windows"
        assert ledger["not_executed"], "unexecuted native cases must be reported"


def test_no_privilege_escalation_or_package_installation_anywhere():
    """No sudo/doas/pkexec, no installer, and no euid/root change is invoked."""
    module = _guard_module()
    programs = _guard_executed_programs(module.body)
    assert programs == {"setfacl"}, "the ACL utility is the only external program"
    assert _guard_called_attributes(module.body) & {"setuid", "seteuid", "setgid", "chroot"} == set()
    assert _guard_attributes(module.body) & {"system", "popen", "spawnv", "spawnvp"} == set()


def test_ownership_mutation_is_confined_to_the_two_ownership_fixtures():
    """chown appears only in the ownership helper and the foreign-owner restore.

    The helper is the only place ownership is reassigned to establish a fixture, and
    it is called only by the foreign-owner and root-owner qualification cases, so
    ownership can never be changed on any path outside the invocation-owned tmp_path
    fixture those cases create.
    """
    module = _guard_module()
    owners = {node.name for node in ast.walk(module) if isinstance(node, ast.FunctionDef)
              for inner in ast.walk(node)
              if isinstance(inner, ast.Call) and getattr(inner.func, "attr", None) == "chown"}
    assert owners, "the ownership helper must establish the fixture with a real chown"
    assert owners <= {"_ownership_fixture", "test_rqp_l09_foreign_owner_is_refused"}, \
        "chown must be confined to the ownership helper and the foreign-owner restore"
    callers = {node.name for node in ast.walk(module) if isinstance(node, ast.FunctionDef)
               for inner in ast.walk(node)
               if isinstance(inner, ast.Call) and getattr(inner.func, "id", None) == "_ownership_fixture"}
    assert callers == {"test_rqp_l09_foreign_owner_is_refused",
                       "test_rqp_l09_root_owned_object_is_trusted"}
    # The foreign-owner restore only ever targets the fixture's own path.
    foreign = _guard_functions(module)["test_rqp_l09_foreign_owner_is_refused"]
    restores = [node for node in ast.walk(foreign) if isinstance(node, ast.Call)
                and getattr(node.func, "attr", None) == "chown"]
    assert len(restores) == 1, "only the single restore chown belongs to this test"
    assert getattr(restores[0].args[0], "id", None) == "path"


def test_rqp_l17_feasibility_evidence_stays_read_only():
    """The feasibility probe reads host state and performs no mount or namespace trip."""
    module = _guard_module()
    forbidden = {"mount", "umount", "unmount", "unshare", "setns", "unshareat"}
    defined = {node.name for node in ast.walk(module) if isinstance(node, ast.FunctionDef)}
    assert not defined & forbidden
    assert _guard_called_attributes(module.body) & forbidden == set()
    probe = _guard_functions(module)["test_rqp_l17_mount_drift_fixture_feasibility_is_recorded"]
    assert _guard_called_attributes(probe) & {"system", "popen", "run"} == set()
    literals = {node.value for node in ast.walk(probe)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert "RQP_L17_PRIVILEGED_FIXTURE_REQUIRED=%s" in literals
    assert "RQP_L17_PRIVILEGED_FIXTURE_CONSTRUCTED=false" in literals
    # The real host state the probe reads: real CapEff mask and real mount record.
    cap_reader = _guard_functions(module)["_effective_capabilities"]
    assert {node.value for node in ast.walk(cap_reader)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)} >= {"CapEff:", "r"}
    assert _guard_attributes(cap_reader) & forbidden == set()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux native mechanics only")
def test_rqp_l17_mountinfo_of_held_object_is_really_bound(capsys):
    """The held mount is bound to a real /proc mount record, not a synthetic table."""
    scope = None
    try:
        scope = _physical._NativeScope(os.path.dirname(os.path.abspath(__file__)))
    except (OSError, _ScheduleArtifactError) as exc:
        pytest.skip("MECHANICS_TEST_ONLY unavailable native ancestry: " + str(exc))
    try:
        mount_id = _linux._mount_id(scope.root_object.fd)
        device = "%d:%d" % (os.major(scope.root_object.identity[0]),
                            os.minor(scope.root_object.identity[0]))
        assert scope.mount_description[0] == "ext4"
        with capsys.disabled():
            print("RQP_L17_REAL_MOUNT_ID=%d" % mount_id)
            print("RQP_L17_REAL_DEVICE=%s" % device)
            print("RQP_L17_REAL_MOUNT_OPTIONS=%r" % (scope.mount_description[1],))
            print("RQP_L17_REAL_SUPER_OPTIONS=%r" % (scope.mount_description[2],))
    finally:
        scope.close()
