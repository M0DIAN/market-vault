"""Pre-admission native writer/reader evidence; production admission stays empty."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
from threading import Barrier

import pytest

from cross_day_dataset_helpers import fixture
from market_vault.cross_day_dataset import execution, materialization as m, reader as r
from market_vault.cross_day_dataset import _artifact_platform as platform
from market_vault.cross_day_dataset import _artifact_windows as windows
from market_vault.cross_day_dataset._artifact_io import _NativeScope
from market_vault.cross_day_dataset.artifact_models import MultiSourceCrossDayArtifactError as Error
from test_cross_day_artifact_native_publication import native_scope, mkdir, write


BUILT_AT = datetime(2026, 1, 2, tzinfo=timezone.utc)
_PRE_ADMISSION_EVIDENCE_CAPABILITIES = frozenset({
    ("Windows", (10, 0, 26100), 1, (34404, 0),
     ("cpython", "3.14.7 (tags/v3.14.7:823f032, Aug  5 2026, 10:51:32) [MSC v.1944 64 bit (AMD64)]", 64),
     "NTFS", 29830879, (3, 1, 512, 4096, 1024), "protected-DACL-FileIdInfo-v1"),
    ("Linux", "6.17.0-1022-azure", "x86_64", "2.39",
     ("cpython", "3.11.16 (main, Aug 13 2026, 02:46:14) [GCC 13.3.0]", 64),
     61267, 4128, 4096, ("ext4", ("relatime", "rw"),
                       ("commit=30", "discard", "errors=remount-ro", "rw")), "statx-protected-ext4-v1"),
})


@pytest.fixture(scope="session")
def _pre_admission_evidence_seen():
    return set()


@pytest.fixture
def qualified_scope(native_scope, monkeypatch, capsys, _pre_admission_evidence_seen):
    scope, capability = native_scope
    assert type(platform._QUALIFIED_CAPABILITIES) is frozenset
    assert platform._QUALIFIED_CAPABILITIES == frozenset()
    assert len(_PRE_ADMISSION_EVIDENCE_CAPABILITIES) == 2
    assert platform._capability(scope) == capability
    with pytest.raises(Error) as rejected:
        platform._require_qualified(scope)
    assert rejected.value.reason_code == "PLATFORM_UNQUALIFIED"
    if capability not in _PRE_ADMISSION_EVIDENCE_CAPABILITIES:
        if capability not in _pre_admission_evidence_seen:
            with capsys.disabled():
                print("PRE_ADMISSION_CAPABILITY_MATCH=false")
                print("L33_UNMATCHED_NATIVE_CAPABILITY=" + json.dumps(capability, separators=(",", ":")))
            _pre_admission_evidence_seen.add(capability)
        pytest.skip("not an exact frozen pre-admission evidence tuple")
    try:
        with monkeypatch.context() as admission:
            admission.setattr(platform, "_QUALIFIED_CAPABILITIES", frozenset({capability}))
            assert platform._require_qualified(scope) == capability
            if capability not in _pre_admission_evidence_seen:
                with capsys.disabled():
                    print("PRE_ADMISSION_CAPABILITY_MATCH=true")
                    print("L33_PRE_ADMISSION_FULL_WRITER_CAPABILITY=" + json.dumps(capability, separators=(",", ":")))
                    print("L33_PRODUCTION_CAPABILITY_TABLE_EMPTY=true")
                    print("L33_TEST_ONLY_EPHEMERAL_ADMISSION=true")
                _pre_admission_evidence_seen.add(capability)
            yield scope
    finally:
        assert type(platform._QUALIFIED_CAPABILITIES) is frozenset
        assert platform._QUALIFIED_CAPABILITIES == frozenset()
        with pytest.raises(Error) as rejected:
            platform._require_qualified(scope)
        assert rejected.value.reason_code == "PLATFORM_UNQUALIFIED"


def issued(tmp_path, case="A"):
    return execution.join_multi_source_cross_day_dataset(**fixture(tmp_path, case))


def materialize(result, scope):
    return m.materialize_multi_source_cross_day_dataset_build(result, output_root=scope.root, built_at=BUILT_AT)


@pytest.mark.parametrize("case", ["A", "B", "C", "D", "E", "F", "G"])
def test_native_complete_artifact_and_existing_idempotence(tmp_path, qualified_scope, case, monkeypatch):
    scope = qualified_scope
    result = issued(tmp_path, case)
    events, owners, final_passes = [], [], []
    validate, publish = m._revalidate_publication_seal, m._publish
    primitive_name = "_rename_directory_no_replace_windows" if os.name == "nt" else "_rename_directory_no_replace_linux"
    primitive = getattr(m, primitive_name)
    physical_recheck = r._PhysicalCapture.recheck
    def checked_physical_recheck(capture):
        physical_recheck(capture)
        if capture.directory == scope.root / ("dataset_id=" + result.dataset_id):
            assert all(item is not owners[-1].members[name] for name, item in capture.objects)
            assert all(item.path == capture.directory / name for name, item in capture.objects)
            final_passes.append(capture.directory)
    def checked_validation(owner, seal):
        validate(owner, seal)
        owners.append(owner)
        if os.name == "nt":
            assert not owner.windows_descendants_quiesced
            assert all(item.handle is not None for item in owner.members.values())
        events.append("full-seal")
    def checked_primitive(*args):
        owner = owners[-1]
        assert owner.state == "SEALED" and events == ["full-seal"]
        if os.name == "nt":
            assert owner.windows_descendants_quiesced
            assert owner.members[""].handle is not None
            assert all(item.handle is None for name, item in owner.members.items() if name)
            assert all(item.handle is not None for item in owner.scope.handles)
        else:
            assert not owner.windows_descendants_quiesced
            assert all(item.fd is not None for item in owner.members.values())
        events.append("rename")
        primitive(*args)
    def checked_publish(owner, seal):
        publish(owner, seal)
        assert owner.state == "COMMITTED_UNVERIFIED"
    monkeypatch.setattr(m, "_revalidate_publication_seal", checked_validation)
    monkeypatch.setattr(m, primitive_name, checked_primitive)
    monkeypatch.setattr(m, "_publish", checked_publish)
    monkeypatch.setattr(r._PhysicalCapture, "recheck", checked_physical_recheck)
    def forbidden_rebind(*args):
        pytest.fail("successful publication must not rebind the old staging path")
    monkeypatch.setattr(m, "_rebind_windows_cleanup_evidence", forbidden_rebind)
    first = materialize(result, scope)
    assert events == ["full-seal", "rename"]
    assert len(final_passes) == 3, "initial, logical-closure and final physical passes required"
    assert first.created_new_build and first.verified.rows == result.rows
    held = scope.member(first.verified.build_path, directory=True)
    try:
        second = materialize(result, scope)
        assert second.created_new_build is False
        assert len(final_passes) == 6
        held.recheck()
        assert first.verified.dataset_id == second.verified.dataset_id == result.dataset_id
        assert second.verified.identity_input.observation_input_proofs == result.identity_input.observation_input_proofs
    finally:
        held.close()


def test_native_equivalent_concurrent_full_writers(tmp_path, qualified_scope, monkeypatch):
    scope = qualified_scope
    result = issued(tmp_path)
    barrier = Barrier(2)
    name = "_rename_directory_no_replace_windows" if os.name == "nt" else "_rename_directory_no_replace_linux"
    original = getattr(m, name)
    rebound = []
    rebind = m._rebind_windows_cleanup_evidence
    def checked_rebind(owner):
        assert owner.windows_descendants_quiesced
        before = m._binding(owner)
        assert all(item.handle is None for key, item in owner.members.items() if key)
        rebind(owner)
        assert not owner.windows_descendants_quiesced and m._binding(owner) == before == owner.seal.binding
        assert all(item.handle is not None for item in owner.members.values())
        rebound.append(owner.path)
    def simultaneous(*args):
        barrier.wait(timeout=60)
        return original(*args)
    monkeypatch.setattr(m, name, simultaneous)
    monkeypatch.setattr(m, "_rebind_windows_cleanup_evidence", checked_rebind)
    with ThreadPoolExecutor(2) as pool:
        outcomes = tuple(pool.map(lambda _: materialize(result, scope), range(2)))
    assert sorted(o.created_new_build for o in outcomes) == [False, True]
    assert {o.verified.dataset_id for o in outcomes} == {result.dataset_id}
    assert tuple(p.name for p in scope.root.iterdir()) == ("dataset_id=" + result.dataset_id,)
    assert len(rebound) == (1 if os.name == "nt" else 0)


def _windows_race_rebind_fault(scope, result, monkeypatch, drift):
    child = scope.root / ("rebind-" + drift)
    mkdir(scope, child)
    with _NativeScope(child, output=True) as local:
        primitive = m._rename_directory_no_replace_windows
        rebind = m._rebind_windows_cleanup_evidence
        owners, winners, restored, modes = [], [], [], []
        validate = m._revalidate_publication_seal
        def capture(owner, seal):
            validate(owner, seal)
            owners.append(owner)
        def race(source, final):
            owner = owners[-1]
            assert owner.windows_descendants_quiesced and owner.members[""].handle is not None
            assert all(item.handle is None for key, item in owner.members.items() if key)
            mkdir(local, final)
            write(local, final / "winner", b"unchanged race winner")
            winners.append(local.member(final, directory=True))
            try:
                primitive(source, final)
            except m._DestinationExists:
                path = source / "dataset.parquet"
                if drift == "replacement":
                    data = path.read_bytes()
                    path.rename(child / "retired")
                    write(local, path, data)
                elif drift == "security":
                    modes.append((path, stat.S_IMODE(path.stat().st_mode)))
                    os.chmod(path, stat.S_IREAD)
                elif drift == "extra":
                    write(local, source / "unexpected", b"unowned")
                raise
        def check_rebind(owner):
            before = owner.members
            try:
                rebind(owner)
            except Error:
                assert owner.members is before, "partial evidence must never be installed"
                assert owner.windows_descendants_quiesced
                raise
            restored.append(True)
            assert m._binding(owner) == owner.seal.binding
        try:
            with monkeypatch.context() as patch:
                patch.setattr(m, "_revalidate_publication_seal", capture)
                patch.setattr(m, "_rename_directory_no_replace_windows", race)
                patch.setattr(m, "_rebind_windows_cleanup_evidence", check_rebind)
                with pytest.raises(Error, match="EXISTING_FINAL_INVALID") as caught:
                    materialize(result, local)
            winners[0].recheck()
            assert (winners[0].path / "winner").read_bytes() == b"unchanged race winner"
            if drift == "none":
                assert restored == [True] and not owners[0].path.exists()
                assert not hasattr(caught.value, "cleanup_failure")
            else:
                assert restored == [] and owners[0].path.is_dir()
                assert caught.value.cleanup_failure.reason_code == "CLEANUP_REFUSED"
                assert not owners[0].cleanup_attempted
                if drift == "security":
                    assert not modes[0][0].stat().st_mode & stat.S_IWRITE
        finally:
            for item in winners:
                item.close()
            for path, mode in modes:
                os.chmod(path, mode)  # Restore only this test-created member for fixture disposal.


def test_native_corrupt_race_winner_never_overwritten(tmp_path, qualified_scope, monkeypatch):
    scope = qualified_scope
    result = issued(tmp_path)
    original = m._publish
    winner = []
    def race(owner, seal):
        mkdir(scope, owner.final)
        write(scope, owner.final / "winner", b"conflicting creator")
        winner.append(scope.member(owner.final, directory=True))
        return original(owner, seal)
    monkeypatch.setattr(m, "_publish", race)
    try:
        with pytest.raises(Error, match="EXISTING_FINAL_INVALID"):
            materialize(result, scope)
        winner[0].recheck()
        assert (winner[0].path / "winner").read_bytes() == b"conflicting creator"
        assert not any(p.name.startswith(".") for p in scope.root.iterdir())
    finally:
        for item in winner:
            item.close()
    if os.name == "nt":
        monkeypatch.setattr(m, "_publish", original)
        for drift in ("none", "replacement", "security", "extra"):
            _windows_race_rebind_fault(scope, result, monkeypatch, drift)


def test_native_final_reader_failure_no_rollback(tmp_path, qualified_scope, monkeypatch):
    scope = qualified_scope
    result = issued(tmp_path)
    def fail(*args):
        raise Error("CONTENT_MISMATCH", "PREFLIGHT", "injected final verification failure")
    monkeypatch.setattr(m, "_existing", fail)
    with pytest.raises(Error) as caught:
        materialize(result, scope)
    assert caught.value.publication_state == "COMMITTED_INVALID"
    final = scope.root / ("dataset_id=" + result.dataset_id)
    assert (final / "_SUCCESS").read_bytes() == b""
    assert r.load_verified_multi_source_cross_day_dataset(final).dataset_id == result.dataset_id


@pytest.mark.parametrize("member", ["manifest.json", "dataset.parquet", "_SUCCESS"])
def test_native_reader_final_pass_rejects_same_path_replacement(tmp_path, qualified_scope, monkeypatch, member):
    scope = qualified_scope
    result = issued(tmp_path)
    final = materialize(result, scope).verified.build_path
    original = r._validate_manifest_content
    def substituted(*args):
        valid = original(*args)
        path = final / member
        data = path.read_bytes()
        path.rename(scope.root / "retired-reader-member")
        write(scope, path, data)
        return valid
    monkeypatch.setattr(r, "_validate_manifest_content", substituted)
    with pytest.raises(Error):
        r.load_verified_multi_source_cross_day_dataset(final)
    assert final.is_dir(), "reader may not remove or repair final"


@pytest.mark.parametrize("drift", ["bytes", "object", "extra", "marker", "manifest", "seal"])
def test_native_seal_drift_has_zero_publication(tmp_path, qualified_scope, monkeypatch, drift):
    scope = qualified_scope
    result = issued(tmp_path)
    original = m._verify_and_seal_staging
    def altered(owner):
        seal = original(owner)
        path = owner.path / "dataset.parquet"
        if drift == "object":
            data = path.read_bytes()
            path.rename(scope.root / "retired-staging-member")
            write(scope, path, data)
        elif drift == "extra":
            write(scope, owner.path / "unlisted", b"new")
        elif drift == "seal":
            object.__setattr__(seal, "dataset_id", "0" * 64)
        else:
            path = owner.path / ({"marker": "_SUCCESS", "manifest": "manifest.json"}.get(drift, "dataset.parquet"))
            with path.open("r+b") as stream:
                stream.write(b"x")
        return seal
    monkeypatch.setattr(m, "_verify_and_seal_staging", altered)
    with pytest.raises(Error):
        materialize(result, scope)
    assert not (scope.root / ("dataset_id=" + result.dataset_id)).exists()
    assert bool(tuple(scope.root.iterdir())) == (drift in ("object", "extra"))


def test_native_partial_staging_cleanup_is_not_seal_authority(tmp_path, qualified_scope, monkeypatch):
    scope = qualified_scope
    result = issued(tmp_path)
    original = m._write_member
    def fail(owner, name, data):
        original(owner, name, data)
        raise OSError("injected partial-write failure before manifest")
    monkeypatch.setattr(m, "_write_member", fail)
    with pytest.raises(Error, match="PUBLICATION_FAILED"):
        materialize(result, scope)
    assert tuple(scope.root.iterdir()) == ()
    if os.name == "nt":
        monkeypatch.setattr(m, "_write_member", original)
        for replaced in (False, True):
            child = scope.root / ("partial-close-" + str(replaced))
            mkdir(scope, child)
            with _NativeScope(child, output=True) as local:
                closed, owners, rebound = [], [], []
                close = windows._WindowsObject.close_for_directory_rename
                validate, rebind = m._revalidate_publication_seal, m._rebind_windows_cleanup_evidence
                def capture(owner, seal):
                    validate(owner, seal)
                    owners.append(owner)
                def fail_second(item):
                    if closed:
                        if replaced:
                            path = closed[0].path
                            data = path.read_bytes()
                            path.rename(child / "retired")
                            write(local, path, data)
                        raise OSError("injected checked-close failure")
                    close(item)
                    closed.append(item)
                def restore(owner):
                    assert owner.windows_descendants_quiesced
                    assert closed[0].handle is None
                    rebind(owner)
                    rebound.append(True)
                def forbidden_rename(*args):
                    pytest.fail("partial checked-close failure must have zero primitive calls")
                with monkeypatch.context() as patch:
                    patch.setattr(m, "_revalidate_publication_seal", capture)
                    patch.setattr(windows._WindowsObject, "close_for_directory_rename", fail_second)
                    patch.setattr(m, "_rebind_windows_cleanup_evidence", restore)
                    patch.setattr(m, "_rename_directory_no_replace_windows", forbidden_rename)
                    with pytest.raises(Error, match="PUBLICATION_FAILED") as caught:
                        materialize(result, local)
                assert len(closed) == 1 and not owners[0].final.exists()
                if replaced:
                    assert rebound == [] and owners[0].path.is_dir()
                    assert caught.value.cleanup_failure.reason_code == "CLEANUP_REFUSED"
                    assert not owners[0].cleanup_attempted
                else:
                    assert rebound == [True] and not owners[0].path.exists()


def test_native_pre_mutation_live_check_and_detached_serialization(tmp_path, qualified_scope, monkeypatch):
    scope = qualified_scope
    result = issued(tmp_path)
    original = m._write_member
    original_id = result.dataset_id
    def after_live_gate(owner, name, data):
        object.__setattr__(result, "identity_input", None)
        object.__setattr__(result, "rows", ())
        object.__setattr__(result, "dataset_id", "0" * 64)
        return original(owner, name, data)
    monkeypatch.setattr(m, "_write_member", after_live_gate)
    verified = materialize(result, scope).verified
    assert verified.dataset_id == original_id and len(verified.rows) == 1
    assert verified.ts2_features.samples[0].values[0].value == 0.25


def test_native_staging_replacement_refuses_publication_and_cleanup(tmp_path, qualified_scope, monkeypatch):
    scope = qualified_scope
    result = issued(tmp_path)
    original = m._verify_and_seal_staging
    def substitute(owner):
        seal = original(owner)
        owner.path.rename(scope.root / "retired-staging")
        mkdir(scope, owner.path)
        return seal
    monkeypatch.setattr(m, "_verify_and_seal_staging", substitute)
    if os.name == "nt":
        # Inject after the last checked close, while the original root is still held.
        monkeypatch.setattr(m, "_verify_and_seal_staging", original)
        owners = []
        validate = m._revalidate_publication_seal
        close = windows._WindowsObject.close_for_directory_rename
        def capture(owner, seal):
            validate(owner, seal)
            owners.append(owner)
        def substitute_after_close(item):
            close(item)
            owner = owners[-1]
            if all(value.handle is None for key, value in owner.members.items() if key):
                assert owner.members[""].handle is not None
                owner.path.rename(scope.root / "retired-staging")
                mkdir(scope, owner.path)
                raise OSError("injected staging replacement before primitive")
        def forbidden_rename(*args):
            pytest.fail("staging replacement during quiescence must not publish")
        monkeypatch.setattr(m, "_revalidate_publication_seal", capture)
        monkeypatch.setattr(windows._WindowsObject, "close_for_directory_rename", substitute_after_close)
        monkeypatch.setattr(m, "_rename_directory_no_replace_windows", forbidden_rename)
    with pytest.raises(Error) as caught:
        materialize(result, scope)
    assert caught.value.cleanup_failure.reason_code == "CLEANUP_REFUSED"
    assert not (scope.root / ("dataset_id=" + result.dataset_id)).exists()
    assert (scope.root / "retired-staging" / "_SUCCESS").read_bytes() == b""


def test_native_permission_drift_refuses_cleanup_without_repair(tmp_path, qualified_scope, monkeypatch):
    scope = qualified_scope
    result = issued(tmp_path)
    original = m._verify_and_seal_staging
    owned = []
    def deny(owner):
        seal = original(owner)
        path = owner.path / "dataset.parquet"
        mode = stat.S_IMODE(path.stat().st_mode)
        owned.append((path, mode))
        os.chmod(path, stat.S_IREAD if os.name == "nt" else 0o400)
        return seal
    monkeypatch.setattr(m, "_verify_and_seal_staging", deny)
    try:
        with pytest.raises(Error) as caught:
            materialize(result, scope)
        assert caught.value.cleanup_failure.reason_code == "CLEANUP_REFUSED"
        assert owned[0][0].is_file()
        assert not (scope.root / ("dataset_id=" + result.dataset_id)).exists()
    finally:
        # Test fixture restoration only. Production cleanup never repairs permissions.
        for path, mode in owned:
            os.chmod(path, mode)


def test_native_committed_interruption_is_uncertain_without_rollback(tmp_path, qualified_scope, monkeypatch):
    scope = qualified_scope
    result = issued(tmp_path)
    name = "_rename_directory_no_replace_windows" if os.name == "nt" else "_rename_directory_no_replace_linux"
    original = getattr(m, name)
    def interrupted(*args):
        original(*args)
        raise KeyboardInterrupt("after actual native rename returned, before caller observed completion")
    monkeypatch.setattr(m, name, interrupted)
    def forbidden_cleanup(*args):
        pytest.fail("ambiguous publication must never rebind or remove staging/final")
    monkeypatch.setattr(m, "_rebind_windows_cleanup_evidence", forbidden_cleanup)
    monkeypatch.setattr(m, "_remove_tree", forbidden_cleanup)
    with pytest.raises(Error) as caught:
        materialize(result, scope)
    assert caught.value.publication_state == "PUBLICATION_UNCERTAIN"
    assert caught.value.reason_code == "PUBLICATION_FAILED"
    final = scope.root / ("dataset_id=" + result.dataset_id)
    assert (final / "_SUCCESS").read_bytes() == b""
    assert r.load_verified_multi_source_cross_day_dataset(final).dataset_id == result.dataset_id
