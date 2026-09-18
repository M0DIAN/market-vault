"""Full native writer/reader evidence. Never replaces native APIs or capability admission."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from pathlib import Path
import stat
from threading import Barrier

import pytest

from cross_day_dataset_helpers import fixture
from market_vault.cross_day_dataset import execution, materialization as m, reader as r
from market_vault.cross_day_dataset._artifact_platform import _require_qualified
from market_vault.cross_day_dataset.artifact_models import MultiSourceCrossDayArtifactError as Error
from test_cross_day_artifact_native_publication import native_scope, mkdir, write


BUILT_AT = datetime(2026, 1, 2, tzinfo=timezone.utc)


@pytest.fixture
def qualified_scope(native_scope):
    scope, _ = native_scope
    try:
        _require_qualified(scope)
    except Error as exc:
        if exc.reason_code == "PLATFORM_UNQUALIFIED":
            pytest.skip("full-writer native tuple not yet admitted: " + str(exc))
        raise
    return scope


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
