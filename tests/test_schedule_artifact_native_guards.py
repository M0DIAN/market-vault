"""Static access-policy tests do not constitute native platform qualification."""

import os
import ctypes

import pytest

from market_vault.schedule_artifact._windows import _access_boundary
from market_vault.schedule_artifact._errors import _ScheduleArtifactError


CURRENT = "S-1-5-21-1-2-3-1001"


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
import inspect
from pathlib import Path, PureWindowsPath
import socket
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
    from pathlib import PureWindowsPath
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
