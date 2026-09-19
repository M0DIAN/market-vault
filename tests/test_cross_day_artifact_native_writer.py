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
def test_native_complete_artifact_and_existing_idempotence(tmp_path, qualified_scope, case):
    scope = qualified_scope
    result = issued(tmp_path, case)
    first = materialize(result, scope)
    assert first.created_new_build and first.verified.rows == result.rows
    held = scope.member(first.verified.build_path, directory=True)
    try:
        second = materialize(result, scope)
        assert second.created_new_build is False
        held.recheck()
        assert first.verified.dataset_id == second.verified.dataset_id == result.dataset_id
        assert second.verified.identity_input.observation_input_proofs == result.identity_input.observation_input_proofs
    finally:
        held.close()


def test_native_equivalent_concurrent_full_writers(tmp_path, qualified_scope, monkeypatch):
    scope = qualified_scope
    result = issued(tmp_path)
    barrier = Barrier(2)
    original = m._publish
    def simultaneous(owner, seal):
        barrier.wait(timeout=60)
        return original(owner, seal)
    monkeypatch.setattr(m, "_publish", simultaneous)
    with ThreadPoolExecutor(2) as pool:
        outcomes = tuple(pool.map(lambda _: materialize(result, scope), range(2)))
    assert sorted(o.created_new_build for o in outcomes) == [False, True]
    assert {o.verified.dataset_id for o in outcomes} == {result.dataset_id}
    assert tuple(p.name for p in scope.root.iterdir()) == ("dataset_id=" + result.dataset_id,)


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
    with pytest.raises(Error) as caught:
        materialize(result, scope)
    assert caught.value.publication_state == "PUBLICATION_UNCERTAIN"
    assert caught.value.reason_code == "PUBLICATION_FAILED"
    final = scope.root / ("dataset_id=" + result.dataset_id)
    assert (final / "_SUCCESS").read_bytes() == b""
    assert r.load_verified_multi_source_cross_day_dataset(final).dataset_id == result.dataset_id
