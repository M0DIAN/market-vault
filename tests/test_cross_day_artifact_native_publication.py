"""Real native primitive probes. Passing probes alone does not qualify the full writer."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import sys
from threading import Barrier

import pytest

from market_vault.cross_day_dataset import materialization as m
from market_vault.cross_day_dataset._artifact_io import _NativeScope, _inventory
from market_vault.cross_day_dataset._artifact_platform import _capability, _QUALIFIED_CAPABILITIES
from market_vault.cross_day_dataset._artifact_windows import _new_directory, _new_file_handle, _write_handle
from market_vault.cross_day_dataset.artifact_models import MultiSourceCrossDayArtifactError as Error


def mkdir(scope, path):
    if os.name == "nt":
        _new_directory(path, scope.current_sid)
    else:
        os.mkdir(path, 0o700)


def write(scope, path, data):
    if os.name == "nt":
        from market_vault.cross_day_dataset._artifact_windows import _close
        handle = _new_file_handle(path, scope.current_sid)
        try:
            _write_handle(handle, data)
        finally:
            _close(handle)
    else:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            assert os.write(fd, data) == len(data)
            os.fsync(fd)
        finally:
            os.close(fd)


def rename(scope, source, target):
    if os.name == "nt":
        m._rename_directory_no_replace_windows(source, target)
    else:
        m._rename_directory_no_replace_linux(scope.root_object.fd, os.fsencode(source.name), os.fsencode(target.name))


@pytest.fixture
def native_scope(tmp_path):
    if os.name == "nt":
        proposed = os.environ.get("MV_L33_NATIVE_TEST_ROOT")
        if proposed is None:
            pytest.skip("real Windows native evidence requires a fresh qualified Sandbox, never host D:")
        parent = Path(proposed)
        assert str(parent).startswith("C:\\MV-L33-Qualification"), "guest-only qualification root required"
    elif sys.platform == "linux":
        parent = tmp_path
    else:
        pytest.skip("not a candidate native platform")
    # This fixture does not alter pre-existing ACLs or permissions.
    with _NativeScope(parent, output=True) as ancestry:
        capability = _capability(ancestry)
        child = parent / ("np-" + os.urandom(16).hex())
        ancestry.recheck()
        mkdir(ancestry, child)
    scope = _NativeScope(child, output=True)
    original = scope.root_object.identity
    try:
        yield scope, capability
    finally:
        try:
            scope.recheck()
            assert scope.root_object.identity == original
        finally:
            scope.close()
        # Only this fixture's exclusively-created child, never the supplied root.
        assert child.is_absolute() and child.parent == parent and child.name.startswith("np-")
        shutil.rmtree(child)


def test_native_capability_and_stable_object_evidence(native_scope, capsys, monkeypatch):
    scope, capability = native_scope
    directory, file = scope.root / "directory", scope.root / "file"
    mkdir(scope, directory)
    write(scope, file, b"native identity evidence")
    objects = [scope.member(directory, directory=True), scope.member(file, directory=False)]
    try:
        for item in objects:
            item.recheck()
            assert item.identity and item.filesystem == scope.filesystem
        assert objects[0].identity != objects[1].identity
        assert objects[1].read_bytes() == b"native identity evidence"
        inventory_file = directory / "dataset.parquet"
        write(scope, inventory_file, b"single-link inventory evidence")
        with os.scandir(directory) as stream:
            entry = next(stream)
            assert entry.name == inventory_file.name
            direntry_links = entry.stat(follow_symlinks=False).st_nlink
        assert _inventory(directory, scope) == (("dataset.parquet", "FILE"),)
        if os.name == "nt":
            assert direntry_links == 0
            with capsys.disabled():
                print("WINDOWS_DIRENTRY_NLINK_ZERO_REGULAR_FILE_ACCEPTED=true")

        def rejected_member(path, *, directory):
            assert path == inventory_file and directory is False
            raise Error("UNSAFE_PATH", "PREFLIGHT", "injected native member refusal")

        with monkeypatch.context() as patch:
            patch.setattr(scope, "member", rejected_member)
            with pytest.raises(Error, match="injected native member refusal"):
                _inventory(directory, scope)

        held_file = scope.member(inventory_file, directory=False)
        closed = []

        class FailedRecheck:
            def recheck(self):
                held_file.recheck()
                raise Error("UNSAFE_PATH", "PREFLIGHT", "injected native recheck refusal")

            def close(self):
                held_file.close()
                closed.append(True)

        try:
            with monkeypatch.context() as patch:
                patch.setattr(scope, "member", lambda path, *, directory: FailedRecheck())
                with pytest.raises(Error, match="injected native recheck refusal"):
                    _inventory(directory, scope)
            assert closed == [True]
        finally:
            held_file.close()
        if os.name == "nt":
            from market_vault.cross_day_dataset._artifact_windows import _native_volume_root
            assert _native_volume_root(scope.handles[0].handle) is True
            assert scope.handles[0].filesystem == scope.filesystem
            assert all(not _native_volume_root(item.handle) for item in scope.handles[1:])
            with capsys.disabled():
                print("WINDOWS_ROOT_ADMISSION=PASS")
                print("WINDOWS_NATIVE_VOLUME_ROOT_CLASSIFICATION=PASS")
        with capsys.disabled():
            print("L33_NATIVE_CANDIDATE_CAPABILITY=" + json.dumps(capability, separators=(",", ":")))
            print("L33_NATIVE_OBJECT_AND_VOLUME_PROBE=PASS")
            print("L33_FULL_WRITER_TUPLE_ADMITTED=" + str(capability in _QUALIFIED_CAPABILITIES).lower())
    finally:
        for item in objects:
            item.close()


@pytest.mark.parametrize("destination", ["absent", "empty", "nonempty"])
def test_native_no_replace_collision_and_winner_identity(native_scope, destination):
    scope, _ = native_scope
    source, final = scope.root / "source", scope.root / "final"
    mkdir(scope, source)
    write(scope, source / "payload", b"source")
    held_source = scope.member(source, directory=True)
    held_final = None
    try:
        if destination != "absent":
            mkdir(scope, final)
            if destination == "nonempty":
                write(scope, final / "winner", b"winner must survive")
            held_final = scope.member(final, directory=True)
            with pytest.raises(m._DestinationExists):
                rename(scope, source, final)
            held_final.recheck()
            held_source.recheck()
            if destination == "nonempty":
                member = scope.member(final / "winner", directory=False)
                try:
                    assert member.read_bytes() == b"winner must survive"
                finally:
                    member.close()
        else:
            rename(scope, source, final)
            assert not source.exists()
            held_final = scope.member(final, directory=True)
            assert held_final.identity == held_source.identity
            assert (final / "payload").read_bytes() == b"source"
    finally:
        held_source.close()
        if held_final:
            held_final.close()


@pytest.mark.parametrize("equal", [True, False])
def test_native_concurrent_equivalent_and_conflicting_rename(native_scope, equal):
    scope, _ = native_scope
    sources = (scope.root / "first", scope.root / "second")
    final = scope.root / "winner"
    data = (b"first", b"first" if equal else b"second")
    ids = []
    for source, value in zip(sources, data):
        mkdir(scope, source)
        write(scope, source / "payload", value)
        item = scope.member(source, directory=True)
        ids.append(item.identity)
        item.close()
    barrier = Barrier(2)
    def contender(index):
        barrier.wait(timeout=20)
        try:
            rename(scope, sources[index], final)
            return index, "won"
        except m._DestinationExists:
            return index, "lost"
    with ThreadPoolExecutor(2) as executor:
        outcomes = tuple(executor.map(contender, (0, 1)))
    assert sorted(state for _, state in outcomes) == ["lost", "won"]
    winner = next(index for index, state in outcomes if state == "won")
    held = scope.member(final, directory=True)
    try:
        assert held.identity == ids[winner]
        assert (final / "payload").read_bytes() == data[winner]
        with pytest.raises(m._DestinationExists):
            rename(scope, sources[1 - winner], final)
        held.recheck()
        assert (final / "payload").read_bytes() == data[winner]
    finally:
        held.close()


def test_native_same_path_identical_bytes_replacement_detected(native_scope):
    scope, _ = native_scope
    path = scope.root / "member"
    write(scope, path, b"same bytes")
    held = scope.member(path, directory=False)
    try:
        path.rename(scope.root / "retired-member")
        write(scope, path, b"same bytes")
        with pytest.raises(Error):
            held.recheck()
    finally:
        held.close()


def test_native_symlink_or_reparse_rejected(native_scope):
    scope, _ = native_scope
    target, link = scope.root / "target", scope.root / "link"
    mkdir(scope, target)
    link.symlink_to(target, target_is_directory=True)
    try:
        with pytest.raises(Error):
            scope.member(link, directory=True)
    finally:
        link.unlink()


def test_native_hardlink_rejected(native_scope, capsys):
    scope, _ = native_scope
    first, second = scope.root / "dataset.parquet", scope.root / "feature_pit.json"
    write(scope, first, b"linked")
    os.link(first, second)
    for path in (first, second):
        with pytest.raises(Error):
            scope.member(path, directory=False)
    with pytest.raises(Error, match="hard.link"):
        _inventory(scope.root, scope)
    with capsys.disabled():
        platform = "WINDOWS" if os.name == "nt" else "LINUX"
        print(platform + "_REAL_HARDLINK_INVENTORY_REJECTED=true")


def test_linux_cross_volume_member_rejected(native_scope):
    if sys.platform != "linux":
        pytest.skip("Linux native cross-device evidence")
    scope, _ = native_scope
    import tempfile
    with tempfile.TemporaryDirectory(prefix="mv-l33-cross-device-", dir="/dev/shm") as different:
        path = Path(different) / "member"
        write(scope, path, b"other device")
        assert os.stat(path).st_dev != os.fstat(scope.root_object.fd).st_dev
        with pytest.raises(Error, match="FILESYSTEM_MISMATCH"):
            scope.member(path, directory=False)


def test_linux_permission_failure_no_native_fallback(native_scope):
    if sys.platform != "linux":
        pytest.skip("Linux permission evidence")
    scope, _ = native_scope
    if os.geteuid() == 0:
        pytest.skip("ordinary non-root qualification runner required for permission denial")
    parent = scope.root / "denied"
    mkdir(scope, parent)
    source = parent / "source"
    os.mkdir(source, 0o700)
    descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        # Only this test-created object, never an ancestor or publication cleanup callback.
        os.chmod(parent, 0o500)
        with pytest.raises(Error, match="PUBLICATION_FAILED"):
            m._rename_directory_no_replace_linux(descriptor, b"source", b"final")
        assert source.is_dir() and not (parent / "final").exists()
    finally:
        os.chmod(parent, 0o700)
        os.close(descriptor)


@pytest.mark.parametrize("attribute", [0x1, 0x2, 0x4])
def test_windows_native_attribute_drift_rejected(native_scope, attribute):
    if os.name != "nt":
        pytest.skip("Windows native file attributes")
    import ctypes
    from ctypes import wintypes
    scope, _ = native_scope
    path = scope.root / "attributes"
    write(scope, path, b"owned qualification fixture")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    get = kernel.GetFileAttributesW
    get.argtypes, get.restype = [wintypes.LPCWSTR], wintypes.DWORD
    set_attributes = kernel.SetFileAttributesW
    set_attributes.argtypes, set_attributes.restype = [wintypes.LPCWSTR, wintypes.DWORD], wintypes.BOOL
    original = get(str(path))
    assert original != 0xFFFFFFFF
    held = scope.member(path, directory=False)
    try:
        assert set_attributes(str(path), original | attribute)
        with pytest.raises(Error):
            held.recheck()
    finally:
        # Restore only this newly-created fixture, never a root or cleanup failure.
        assert set_attributes(str(path), original)
        held.close()


def test_windows_native_named_stream_rejected(native_scope):
    if os.name != "nt":
        pytest.skip("Windows native alternate stream")
    scope, _ = native_scope
    path = scope.root / "stream"
    write(scope, path, b"owned qualification fixture")
    with open(str(path) + ":unexpected", "xb") as stream:
        stream.write(b"outside closed inventory")
    with pytest.raises(Error, match="INVENTORY_MISMATCH"):
        scope.member(path, directory=False)


def test_native_root_replacement_detected(native_scope):
    scope, _ = native_scope
    path = scope.root / "inner-root"
    mkdir(scope, path)
    with _NativeScope(path, output=True) as held:
        path.rename(scope.root / "retired-root")
        mkdir(scope, path)
        with pytest.raises(Error, match="UNSAFE_PATH"):
            held.recheck()
