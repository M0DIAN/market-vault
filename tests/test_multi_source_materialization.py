"""A4.3 publication ownership, race, crash and actual platform canaries."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, fields
import errno
import os
from pathlib import Path
import shutil
import subprocess
import sys
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock

import pyarrow as pa
import pytest

from market_vault.multi_source import materialize_multi_source_dataset_build, load_verified_multi_source_dataset
from market_vault.multi_source import materialization as writer
from market_vault.multi_source.artifact_models import MultiSourceDatasetArtifactError, MultiSourceDatasetMaterializationError
from test_multi_source_artifact import candidate, artifact, BUILT_AT
from test_multi_source_orchestration import fixtures, artifacts, observation_factory


def tree_bytes(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("nonempty", [False, True])
@pytest.mark.skipif(os.name != "nt", reason="actual Windows primitive")
def test_canary_49_actual_windows_no_replace(tmp_path, nonempty):
    staging, final = tmp_path / "staging", tmp_path / "final"
    staging.mkdir()
    final.mkdir()
    (staging / "private").write_bytes(b"ours")
    if nonempty:
        (final / "winner").write_bytes(b"winner")
    before = tree_bytes(final)
    with pytest.raises(writer._DestinationExistsError):
        writer._rename_directory_no_replace_windows(staging, final)
    assert tree_bytes(final) == before and (staging / "private").read_bytes() == b"ours"


@pytest.mark.parametrize("nonempty", [False, True])
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="actual Linux renameat2 primitive")
def test_canary_50_actual_linux_no_replace(tmp_path, nonempty):
    staging, final = tmp_path / "staging", tmp_path / "final"
    staging.mkdir()
    final.mkdir()
    (staging / "private").write_bytes(b"ours")
    if nonempty:
        (final / "winner").write_bytes(b"winner")
    before = tree_bytes(final)
    with pytest.raises(writer._DestinationExistsError):
        writer._rename_directory_no_replace_linux(staging, final)
    assert tree_bytes(final) == before and (staging / "private").read_bytes() == b"ours"


@pytest.mark.parametrize("error", [errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EACCES])
def test_linux_error_no_fallback(tmp_path, monkeypatch, error):
    class Native:
        def __call__(self, *args):
            writer.ctypes.set_errno(error)
            return -1
    monkeypatch.setattr(writer.ctypes, "CDLL", lambda *a, **k: SimpleNamespace(renameat2=Native()))
    with pytest.raises(MultiSourceDatasetMaterializationError):
        writer._rename_directory_no_replace_linux(tmp_path / "a", tmp_path / "b")


def test_missing_linux_primitive_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(writer.ctypes, "CDLL", lambda *a, **k: SimpleNamespace())
    with pytest.raises(writer._NoReplaceUnsupportedError):
        writer._rename_directory_no_replace_linux(tmp_path / "a", tmp_path / "b")


@pytest.mark.parametrize("kind", ["arrow", "unsupported", "ordinary"])
def test_owned_cleanup_only(candidate, tmp_path, monkeypatch, kind):
    root = tmp_path / "out"
    root.mkdir()
    unrelated = root / "unrelated"
    unrelated.mkdir()
    (unrelated / "keep").write_bytes(b"untouched")
    error = pa.ArrowCapacityError("injected") if kind == "arrow" else writer._NoReplaceUnsupportedError("unsupported") if kind == "unsupported" else OSError("failed")
    if kind == "arrow":
        assert not isinstance(error, (ValueError, TypeError, OSError))
    def fail(*args, **kwargs):
        assert list(root.glob(".*.tmp-*")), "failure must occur after ownership"
        raise error
    monkeypatch.setattr(writer, "parquet_bytes" if kind == "arrow" else "_publish", fail)
    with pytest.raises(MultiSourceDatasetMaterializationError) as caught:
        materialize_multi_source_dataset_build(candidate, output_root=root, built_at=BUILT_AT)
    assert caught.value is error or caught.value.__cause__ is error
    assert not (root / candidate.dataset_id).exists()
    assert not list(root.glob(".*.tmp-*"))
    assert (unrelated / "keep").read_bytes() == b"untouched"


def test_preexisting_staging_not_adopted_or_deleted(candidate, tmp_path, monkeypatch):
    root = tmp_path / "out"
    staging = root / ("." + candidate.dataset_id + ".tmp-" + "1"*32)
    staging.mkdir(parents=True)
    (staging / "keep").write_bytes(b"old residue")
    monkeypatch.setattr(writer, "uuid4", lambda: SimpleNamespace(hex="1"*32))
    with pytest.raises(MultiSourceDatasetMaterializationError):
        materialize_multi_source_dataset_build(candidate, output_root=root, built_at=BUILT_AT)
    assert (staging / "keep").read_bytes() == b"old residue"


def test_substituted_staging_cleanup_refused(candidate, tmp_path, monkeypatch):
    root = tmp_path / "out"
    saved = []
    def substitute(owner, seal):
        original = owner.path.with_name(owner.path.name + "-saved")
        owner.path.rename(original)
        owner.path.mkdir()
        (owner.path / "manifest.json").write_bytes(b"not ours")
        saved.append((owner.path, original))
        raise OSError("substituted")
    monkeypatch.setattr(writer, "_publish", substitute)
    with pytest.raises(MultiSourceDatasetMaterializationError, match="cleanup refused"):
        materialize_multi_source_dataset_build(candidate, output_root=root, built_at=BUILT_AT)
    assert saved[0][0].exists() and saved[0][1].exists()
    assert (saved[0][0] / "manifest.json").read_bytes() == b"not ours"


def test_actual_concurrent_publish_one_creator(candidate, tmp_path, monkeypatch):
    barrier = Barrier(2)
    original = writer._publish
    def rendezvous(owner, seal):
        barrier.wait(timeout=30)
        original(owner, seal)
    monkeypatch.setattr(writer, "_publish", rendezvous)
    def run():
        return materialize_multi_source_dataset_build(candidate, output_root=tmp_path / "out", built_at=BUILT_AT)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = tuple(pool.map(lambda _: run(), range(2)))
    assert sorted((a.created_new_build, b.created_new_build)) == [False, True]
    assert a.dataset_id == b.dataset_id == candidate.dataset_id
    assert not list((tmp_path / "out").glob(".*.tmp-*"))


def test_corrupt_race_winner_untouched(candidate, tmp_path, monkeypatch):
    original = writer._publish
    def winner(owner, seal):
        owner.final.mkdir()
        (owner.final / "keep").write_bytes(b"foreign corrupt winner")
        original(owner, seal)
    monkeypatch.setattr(writer, "_publish", winner)
    with pytest.raises(MultiSourceDatasetMaterializationError):
        materialize_multi_source_dataset_build(candidate, output_root=tmp_path / "out", built_at=BUILT_AT)
    assert (tmp_path / "out" / candidate.dataset_id / "keep").read_bytes() == b"foreign corrupt winner"
    assert not list((tmp_path / "out").glob(".*.tmp-*"))


def test_postcommit_reader_failure_never_removes_final(candidate, tmp_path, monkeypatch):
    def fail(path):
        raise MultiSourceDatasetArtifactError("postcommit verification failed")
    monkeypatch.setattr(writer, "load_verified_multi_source_dataset", fail)
    with pytest.raises(MultiSourceDatasetMaterializationError):
        materialize_multi_source_dataset_build(candidate, output_root=tmp_path / "out", built_at=BUILT_AT)
    final = tmp_path / "out" / candidate.dataset_id
    assert load_verified_multi_source_dataset(final).dataset_id == candidate.dataset_id


def test_crash_residue_non_authoritative_not_swept(candidate, tmp_path, monkeypatch):
    original = writer._publish
    def crash(owner, seal):
        raise KeyboardInterrupt("process crash simulation")
    monkeypatch.setattr(writer, "_publish", crash)
    with pytest.raises(KeyboardInterrupt):
        materialize_multi_source_dataset_build(candidate, output_root=tmp_path / "out", built_at=BUILT_AT)
    residue, = (tmp_path / "out").iterdir()
    before = tree_bytes(residue)
    with pytest.raises(MultiSourceDatasetArtifactError):
        load_verified_multi_source_dataset(residue)
    monkeypatch.setattr(writer, "_publish", original)
    assert materialize_multi_source_dataset_build(candidate, output_root=tmp_path / "out", built_at=BUILT_AT).created_new_build
    assert tree_bytes(residue) == before


def test_existing_corrupt_final_no_staging(candidate, tmp_path):
    final = tmp_path / "out" / candidate.dataset_id
    final.mkdir(parents=True)
    (final / "keep").write_bytes(b"do not repair")
    with pytest.raises(MultiSourceDatasetMaterializationError):
        materialize_multi_source_dataset_build(candidate, output_root=final.parent, built_at=BUILT_AT)
    assert tuple(final.parent.iterdir()) == (final,)
    assert tree_bytes(final) == {"keep": b"do not repair"}


@pytest.mark.parametrize("junction", [False, True])
def test_in_root_link_rejected(artifact, tmp_path, junction):
    source = artifact / "associations"
    saved = artifact / "saved-associations"
    source.rename(saved)
    if junction:
        if os.name != "nt":
            pytest.skip("Windows junction")
        subprocess.run(["cmd", "/c", "mklink", "/J", str(source), str(saved)], check=True, capture_output=True)
    else:
        try:
            source.symlink_to(saved, target_is_directory=True)
        except OSError as exc:
            pytest.skip("symlink creation unavailable: " + str(exc))
    with pytest.raises(MultiSourceDatasetArtifactError, match="symlink|junction|reparse"):
        load_verified_multi_source_dataset(artifact)


@pytest.mark.parametrize("bad", [None, "latest", ".", "../data"])
def test_no_implicit_output_authority(candidate, bad):
    with pytest.raises(MultiSourceDatasetMaterializationError):
        materialize_multi_source_dataset_build(candidate, output_root=bad, built_at=BUILT_AT)


def test_tampered_result_not_silently_repaired(candidate, tmp_path):
    clone = object.__new__(type(candidate))
    for f in fields(candidate):
        object.__setattr__(clone, f.name, getattr(candidate, f.name))
    object.__setattr__(clone, "rows", ())
    with pytest.raises(MultiSourceDatasetMaterializationError, match="tampered"):
        materialize_multi_source_dataset_build(clone, output_root=tmp_path / "out", built_at=BUILT_AT)
    assert not (tmp_path / "out").exists()


def test_materializer_io_stays_under_explicit_root(candidate, tmp_path, monkeypatch):
    root = tmp_path / "out"
    original = Path.open
    observed = []
    def bounded(path, mode="r", *args, **kwargs):
        assert root in path.parents, "upstream or unrelated filesystem access"
        observed.append((path, mode))
        return original(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", bounded)
    result = materialize_multi_source_dataset_build(candidate, output_root=root, built_at=BUILT_AT)
    assert result.created_new_build and observed
    assert {mode for _, mode in observed} <= {"rb", "xb"}


def test_staging_link_refuses_cleanup(candidate, tmp_path, monkeypatch):
    outside = tmp_path / "unrelated"
    outside.mkdir()
    (outside / "keep").write_bytes(b"source evidence")
    recorded = []
    def linked(owner, seal):
        child = owner.path / "escape"
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(child), str(outside)], check=True, capture_output=True)
        else:
            child.symlink_to(outside, target_is_directory=True)
        recorded.append(owner.path)
        raise OSError("unsafe staging")
    monkeypatch.setattr(writer, "_publish", linked)
    with pytest.raises(MultiSourceDatasetMaterializationError, match="cleanup refused"):
        materialize_multi_source_dataset_build(candidate, output_root=tmp_path / "out", built_at=BUILT_AT)
    assert recorded[0].exists() and (outside / "keep").read_bytes() == b"source evidence"


@pytest.mark.parametrize("built_at", [None, "latest", BUILT_AT.replace(tzinfo=None)])
def test_explicit_built_at_required(candidate, tmp_path, built_at):
    with pytest.raises(MultiSourceDatasetMaterializationError):
        materialize_multi_source_dataset_build(candidate, output_root=tmp_path / "out", built_at=built_at)
    assert not (tmp_path / "out").exists()


SEALED_MEMBERS = (
    "dataset.parquet", "manifest.json", "_SUCCESS", "associations/bar.parquet",
    "associations/observation.parquet", "associations/sample_bindings.parquet",
    "associations/observation_feature_values.parquet", "associations/observation_evidence.json",
    "feature_specs/bar/*.yaml", "feature_specs/observation/*.yaml", "label_specs/*.yaml",
    "split_spec.yaml", "build_report.json",
)


def assert_rejected_before_rename(candidate, tmp_path, monkeypatch, match="publication"):
    root = tmp_path / "out"
    unrelated = root / "unrelated"
    unrelated.mkdir(parents=True)
    (unrelated / "keep").write_bytes(b"untouched")
    rename = Mock(side_effect=AssertionError("invalid staging reached no-replace primitive"))
    monkeypatch.setattr(writer, "_rename_directory_no_replace_windows", rename)
    monkeypatch.setattr(writer, "_rename_directory_no_replace_linux", rename)
    with pytest.raises(MultiSourceDatasetMaterializationError, match=match):
        materialize_multi_source_dataset_build(candidate, output_root=root, built_at=BUILT_AT)
    assert rename.call_count == 0
    assert not (root / candidate.dataset_id).exists()
    assert tuple(root.iterdir()) == (unrelated,)
    assert tree_bytes(unrelated) == {"keep": b"untouched"}


@pytest.mark.parametrize("member", SEALED_MEMBERS)
@pytest.mark.parametrize("mutation", ["bytes", "remove", "substitute"])
def test_sealed_member_drift_rejected_before_rename(candidate, tmp_path, monkeypatch, member, mutation):
    publish = writer._publish
    def drift(owner, seal):
        assert seal is owner.publication_seal
        assert writer.inventory(owner.path) == seal.expected_inventory
        path, = owner.path.glob(member)
        before = path.read_bytes()
        if mutation == "bytes":
            path.write_bytes(bytes([before[0] ^ 1]) + before[1:] if before else b"not empty")
        elif mutation == "remove":
            path.unlink()
        else:
            path.rename(tmp_path / "original-file-object")
            path.write_bytes(before)
            assert path.read_bytes() == before, "same bytes must not hide object substitution"
        publish(owner, seal)
    monkeypatch.setattr(writer, "_publish", drift)
    assert_rejected_before_rename(candidate, tmp_path, monkeypatch)


@pytest.mark.parametrize("member", ["dataset.parquet", "manifest.json", "_SUCCESS", "build_report.json"])
def test_seal_cannot_capture_new_bytes_after_private_verification(candidate, tmp_path, monkeypatch, member):
    verify = writer._verify_directory
    verified_final = []
    def mutate_after_verified(root, *, require_success, final_name):
        result = verify(root, require_success=require_success, final_name=final_name)
        if require_success and not final_name:
            verified_final.append(root)
            path = root / member
            path.write_bytes(path.read_bytes() + b"post-verification drift")
        return result
    monkeypatch.setattr(writer, "_verify_directory", mutate_after_verified)
    assert_rejected_before_rename(candidate, tmp_path, monkeypatch)
    assert len(verified_final) == 1


def test_publication_seal_requires_reconstructed_owner_dataset_id(candidate, tmp_path, monkeypatch):
    verify = writer._verify_directory
    def wrong_binding(root, *, require_success, final_name):
        result = verify(root, require_success=require_success, final_name=final_name)
        if require_success and not final_name:
            result["dataset_id"] = "0" * 64
        return result
    monkeypatch.setattr(writer, "_verify_directory", wrong_binding)
    assert_rejected_before_rename(candidate, tmp_path, monkeypatch, "manifest Dataset identity")


@pytest.mark.parametrize("supplied", [None, object()])
def test_publish_rejects_unissued_seal(candidate, tmp_path, monkeypatch, supplied):
    publish = writer._publish
    def unissued(owner, seal):
        publish(owner, supplied)
    monkeypatch.setattr(writer, "_publish", unissued)
    assert_rejected_before_rename(candidate, tmp_path, monkeypatch, "unissued publication seal")


def test_publication_seal_is_immutable_and_not_caller_constructible(candidate, tmp_path, monkeypatch):
    publish = writer._publish
    def inspect(owner, seal):
        with pytest.raises(TypeError, match="private verification"):
            writer._PublicationSeal()
        with pytest.raises(FrozenInstanceError):
            seal.dataset_id = "0" * 64
        assert seal.dataset_id == candidate.dataset_id
        assert seal.expected_inventory == frozenset(writer.expected_inventory(owner.allowed))
        assert tuple(f[0] for f in seal.file_facts) == tuple(sorted(owner.allowed))
        publish(owner, seal)
    monkeypatch.setattr(writer, "_publish", inspect)
    assert materialize_multi_source_dataset_build(candidate, output_root=tmp_path / "out", built_at=BUILT_AT).created_new_build


def test_partial_write_cleanup_does_not_require_publication_seal(candidate, tmp_path, monkeypatch):
    write = writer._write_bytes
    def fail_after_first_file(owner, name, data):
        write(owner, name, data)
        assert owner.publication_seal is None
        assert writer.inventory(owner.path) < writer.expected_inventory(owner.allowed)
        raise OSError("partial staging write failure")
    monkeypatch.setattr(writer, "_write_bytes", fail_after_first_file)
    assert_rejected_before_rename(candidate, tmp_path, monkeypatch, "partial staging write failure")
