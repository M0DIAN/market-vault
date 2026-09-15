"""Offline A2 publication/admission tests; fixture claims are not provider qualification."""

from dataclasses import replace
from datetime import timedelta
import errno
import importlib.util
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pyarrow as pa
import pytest

from market_vault.observation import (
    ObservationArtifactError, ObservationMaterializationError,
    materialize_observation_build, load_verified_observation_build,
    observation_build_id, observation_source_snapshot_id,
)
from market_vault.observation import materialization as m
from test_observation_models import H, T, sample_build, sample_coverage, sample_observation, sample_snapshot


CREATED = T + timedelta(days=4)


def materialize(root, build=None, snapshots=None, **kwargs):
    return materialize_observation_build(
        sample_build() if build is None else build,
        (sample_snapshot(),) if snapshots is None else snapshots,
        output_root=root, created_at=kwargs.pop("created_at", CREATED), **kwargs)


@pytest.mark.parametrize("empty", [False, True])
def test_roundtrip_and_idempotence(tmp_path, empty):
    build = sample_build(rows=() if empty else (sample_observation(),))
    first = materialize(tmp_path, build)
    original = {p.relative_to(first.build_dir): p.read_bytes()
                for p in first.build_dir.rglob("*") if p.is_file()}
    second = materialize(tmp_path, build, created_at=CREATED + timedelta(days=1))
    assert first.created_new_build and not second.created_new_build
    assert first.verified_build == second.verified_build
    assert first.verified_build.rows == build.rows
    assert first.verified_build.status == ("EMPTY" if empty else "COMPLETE")
    assert first.observation_build_id == observation_build_id(build)
    assert set(tmp_path.iterdir()) == {first.build_dir}
    assert original == {p.relative_to(first.build_dir): p.read_bytes()
                        for p in first.build_dir.rglob("*") if p.is_file()}


@pytest.mark.parametrize("field", ["request_pages_complete", "revision_inventory_complete"])
@pytest.mark.parametrize("empty", [False, True])
def test_incomplete_coverage_cannot_be_verified(tmp_path, field, empty):
    build = sample_build(coverage=sample_coverage(**{field: False}),
                         rows=() if empty else (sample_observation(),))
    with pytest.raises(ObservationMaterializationError, match="complete"):
        materialize(tmp_path, build)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("kind", ["missing", "duplicate", "extra", "wrong_id", "request", "content", "archive"])
def test_snapshot_cross_binding(tmp_path, kind):
    snapshot = sample_snapshot()
    build = sample_build()
    snapshots = (snapshot,)
    if kind == "missing":
        snapshots = ()
    elif kind == "duplicate":
        snapshots = (snapshot, snapshot)
    elif kind in {"extra", "wrong_id"}:
        other = replace(snapshot, acquisition_receipt_id="other")
        snapshots = (snapshot, other) if kind == "extra" else (other,)
    elif kind == "request":
        snapshot = replace(snapshot, normalized_request_id=H[10])
        sid = observation_source_snapshot_id(snapshot)
        build = sample_build(rows=(sample_observation(source_snapshot_id=sid),), source_snapshot_ids=(sid,))
        snapshots = (snapshot,)
    elif kind == "content":
        build = sample_build(rows=(sample_observation(source_content_sha256=H[10]),))
    else:
        build = sample_build(rows=(sample_observation(archive_available_at=T),))
    with pytest.raises(ObservationMaterializationError):
        materialize(tmp_path, build, snapshots)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("created", [None, T.replace(tzinfo=None), T, "2026-03-05"])
def test_created_at_is_explicit_and_after_all_possession(tmp_path, created):
    with pytest.raises(ObservationMaterializationError):
        materialize(tmp_path, created_at=created)


@pytest.mark.parametrize("case", ["valid", "missing", "two_initial", "fork", "equal_clock", "backward", "disconnected_cycle"])
def test_revision_structure_without_winner_selection(tmp_path, case):
    initial = sample_observation()
    second = replace(initial, revision_id="second", supersedes_revision_id=initial.revision_id,
                     known_at=T + timedelta(hours=3))
    rows = [initial, second]
    if case == "missing":
        rows = [second]
    elif case == "two_initial":
        rows[1] = replace(second, supersedes_revision_id=None)
    elif case == "fork":
        rows.append(replace(second, revision_id="fork", known_at=T + timedelta(hours=4)))
    elif case in {"equal_clock", "backward"}:
        rows[1] = replace(second, known_at=initial.known_at if case == "equal_clock" else T)
    elif case == "disconnected_cycle":
        rows += [replace(second, revision_id="cycle-a", supersedes_revision_id="cycle-b"),
                 replace(second, revision_id="cycle-b", supersedes_revision_id="cycle-a")]
    build = sample_build(rows=tuple(rows))
    if case == "valid":
        assert materialize(tmp_path, build).verified_build.rows == build.rows
    else:
        with pytest.raises(ObservationMaterializationError):
            materialize(tmp_path, build)


@pytest.mark.parametrize("change", [None, "values", "value_status", "known_at", "known_at_authority_id", "supersedes_revision_id"])
def test_repeated_capture_economic_consistency(tmp_path, change):
    original = sample_observation()
    captured = replace(original, archive_available_at=T + timedelta(hours=3))
    alterations = {
        "values": {"values": (9.0, 12)},
        "value_status": {"value_status": "WITHDRAWN", "values": None},
        "known_at": {"known_at": T},
        "known_at_authority_id": {"known_at_authority_id": H[6]},
        "supersedes_revision_id": {"supersedes_revision_id": "missing"},
    }
    if change:
        captured = replace(captured, **alterations[change])
    build = sample_build(rows=(original, captured))
    if change:
        with pytest.raises(ObservationMaterializationError, match="repeated capture"):
            materialize(tmp_path, build)
    else:
        assert len(materialize(tmp_path, build).verified_build.rows) == 2


def test_actual_platform_no_replace_preserves_existing_directory(tmp_path):
    staging, final = tmp_path / "staging", tmp_path / "final"
    staging.mkdir()
    final.mkdir()
    (staging / "new").write_bytes(b"new")
    # An empty destination must also be preserved; plain POSIX rename would replace it.
    primitive = m._rename_directory_no_replace_windows if os.name == "nt" else m._rename_directory_no_replace_linux
    if os.name != "nt" and not sys.platform.startswith("linux"):
        pytest.skip("requires Windows or Linux no-replace primitive")
    final_identity = final.stat().st_ino
    with pytest.raises(m._DestinationExistsError):
        primitive(staging, final)
    assert final.stat().st_ino == final_identity and not list(final.iterdir())
    (final / "existing").write_bytes(b"sealed")
    with pytest.raises(m._DestinationExistsError):
        primitive(staging, final)
    assert (final / "existing").read_bytes() == b"sealed"
    assert (staging / "new").read_bytes() == b"new"


@pytest.mark.parametrize("error", [errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EACCES, errno.EXDEV])
def test_linux_native_error_fails_closed(tmp_path, monkeypatch, error):
    class Native:
        def __call__(self, *args):
            assert args[0] == args[2] == -100 and args[-1] == 1
            m.ctypes.set_errno(error)
            return -1
    native = Native()
    class Library:
        renameat2 = native
    monkeypatch.setattr(m.ctypes, "CDLL", lambda *a, **k: Library())
    with pytest.raises(ObservationMaterializationError):
        m._rename_directory_no_replace_linux(tmp_path / "a", tmp_path / "b")
    assert native.restype is m.ctypes.c_int
    assert native.argtypes[-1] is m.ctypes.c_uint


def test_missing_native_primitive_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(m.ctypes, "CDLL", lambda *a, **k: object())
    with pytest.raises(m._NoReplaceUnsupportedError):
        m._rename_directory_no_replace_linux(tmp_path / "a", tmp_path / "b")


@pytest.mark.parametrize("phase", ["parquet", "manifest", "private_verify", "marker", "publish"])
def test_handled_failure_cleans_only_owned_staging(tmp_path, monkeypatch, phase):
    unrelated = tmp_path / "unrelated"
    unrelated.write_bytes(b"retain")
    residue = tmp_path / ".old.tmp-residue"
    residue.mkdir()
    def fail(*a, **k):
        raise OSError("injected failure")
    if phase == "parquet":
        monkeypatch.setattr(m, "_parquet_bytes", fail)
    elif phase in {"manifest", "marker"}:
        original = m._write_bytes
        def write(owner, path, data):
            if path == ("manifest.json" if phase == "manifest" else "_SUCCESS"):
                fail()
            return original(owner, path, data)
        monkeypatch.setattr(m, "_write_bytes", write)
    elif phase == "private_verify":
        monkeypatch.setattr(m, "_verify_directory", fail)
    else:
        monkeypatch.setattr(m, "_publish", fail)
    with pytest.raises(ObservationMaterializationError):
        materialize(tmp_path)
    assert set(tmp_path.iterdir()) == {unrelated, residue}
    assert unrelated.read_bytes() == b"retain"


@pytest.mark.parametrize("cleanup", ["safe", "refused", "failed"])
def test_arrow_capacity_failure_obeys_owned_staging_cleanup(tmp_path, monkeypatch, cleanup):
    unrelated = tmp_path / "unrelated"
    unrelated.write_bytes(b"retain")
    residue = tmp_path / ".old.tmp-residue"
    residue.mkdir()
    (residue / "evidence").write_bytes(b"not owned")
    error = pa.ArrowCapacityError("injected Parquet capacity failure")
    assert isinstance(error, pa.ArrowException)
    assert not isinstance(error, (ValueError, TypeError, OSError))
    owners = []
    original_check = m._check_owner
    def checked_owner(owner):
        original_check(owner)
        owners.append(owner)
    def fail(*args, **kwargs):
        assert owners and owners[-1].path.is_dir()
        assert not owners[-1].committed
        assert not owners[-1].final.exists()
        raise error
    monkeypatch.setattr(m, "_check_owner", checked_owner)
    monkeypatch.setattr(m.pq, "write_table", fail)
    if cleanup != "safe":
        def refuse_cleanup(owner):
            raise (ObservationMaterializationError("ownership unproven")
                   if cleanup == "refused" else OSError("cleanup failed"))
        monkeypatch.setattr(m, "_remove_tree", refuse_cleanup)
    with pytest.raises(ObservationMaterializationError) as caught:
        materialize(tmp_path)
    assert caught.value.__cause__ is error
    owner = owners[0]
    assert not owner.final.exists()
    if cleanup == "safe":
        assert owner.removed and not owner.path.exists()
        assert set(tmp_path.iterdir()) == {unrelated, residue}
    else:
        assert "cleanup refused/failed" in str(caught.value)
        assert not owner.removed and owner.path.is_dir()
        assert set(tmp_path.iterdir()) == {unrelated, residue, owner.path}
    assert unrelated.read_bytes() == b"retain"
    assert (residue / "evidence").read_bytes() == b"not owned"


def test_preexisting_selected_staging_never_adopted_or_deleted(tmp_path, monkeypatch):
    class Fixed:
        hex = "chosen"
    monkeypatch.setattr(m, "uuid4", lambda: Fixed())
    path = tmp_path / ("." + observation_build_id(sample_build()) + ".tmp-chosen")
    path.mkdir()
    (path / "evidence").write_bytes(b"not owned")
    with pytest.raises(ObservationMaterializationError):
        materialize(tmp_path)
    assert (path / "evidence").read_bytes() == b"not owned"


@pytest.mark.parametrize("corrupt", [False, True])
def test_publication_race_preserves_winner(tmp_path, monkeypatch, corrupt):
    output = tmp_path / "output"
    winner = materialize(tmp_path / "winner").build_dir
    real_publish = m._publish
    def race(owner):
        shutil.copytree(winner, owner.final)
        if corrupt:
            (owner.final / "_SUCCESS").write_bytes(b"corrupt")
        return real_publish(owner)
    monkeypatch.setattr(m, "_publish", race)
    if corrupt:
        with pytest.raises(ObservationMaterializationError):
            materialize(output)
    else:
        assert not materialize(output).created_new_build
    final = output / winner.name
    assert set(output.iterdir()) == {final}
    assert (final / "_SUCCESS").read_bytes() == (b"corrupt" if corrupt else b"")


def test_owner_substitution_refuses_cleanup(tmp_path, monkeypatch):
    escaped = tmp_path / "retained-staging"
    def substitute(owner):
        owner.path.rename(escaped)
        owner.path.mkdir()
        (owner.path / "not-owned").write_bytes(b"retain")
        raise OSError("substituted")
    monkeypatch.setattr(m, "_publish", substitute)
    with pytest.raises(ObservationMaterializationError, match="cleanup refused"):
        materialize(tmp_path)
    assert (escaped / "manifest.json").is_file()
    assert len(list(tmp_path.glob(".*/not-owned"))) == 1
    with pytest.raises(ObservationMaterializationError):
        m._remove_tree(tmp_path)


@pytest.mark.parametrize("error_type", [ObservationArtifactError, pa.ArrowCapacityError])
def test_post_commit_reader_failure_never_deletes_final(tmp_path, monkeypatch, error_type):
    error = error_type("post-commit reader failure")
    def fail(*args):
        raise error
    monkeypatch.setattr(m, "load_verified_observation_build", fail)
    with pytest.raises(ObservationMaterializationError) as caught:
        materialize(tmp_path)
    assert caught.value.__cause__ is error
    final = tmp_path / ("build_id=" + observation_build_id(sample_build()))
    assert load_verified_observation_build(final).rows == sample_build().rows


def test_staging_commit_order(tmp_path, monkeypatch):
    events = []
    write, verify, publish = m._write_bytes, m._verify_directory, m._publish
    def logged_write(owner, path, data):
        events.append(path)
        return write(owner, path, data)
    def logged_verify(path, **kwargs):
        events.append("verify_success" if kwargs["require_success"] else "verify_private")
        return verify(path, **kwargs)
    def logged_publish(owner):
        events.append("publish")
        return publish(owner)
    monkeypatch.setattr(m, "_write_bytes", logged_write)
    monkeypatch.setattr(m, "_verify_directory", logged_verify)
    monkeypatch.setattr(m, "_publish", logged_publish)
    materialize(tmp_path)
    assert events == ["observations/part-00000.parquet", "manifest.json", "verify_private",
                      "_SUCCESS", "verify_success", "publish"]


def test_unsupported_platform_has_no_fallback(tmp_path, monkeypatch):
    real_publish = m._publish
    def unsupported(owner):
        with monkeypatch.context() as patch:
            patch.setattr(m, "os", SimpleNamespace(name="unsupported"))
            return real_publish(owner)
    monkeypatch.setattr(m, "_publish", unsupported)
    with pytest.raises(m._NoReplaceUnsupportedError):
        materialize(tmp_path)
    assert not list(tmp_path.iterdir())


def test_repeated_capture_with_distinct_snapshot_evidence(tmp_path):
    snapshot = replace(sample_snapshot(), acquisition_receipt_id="recapture",
                       completed_possession_at=T + timedelta(hours=3))
    sid = observation_source_snapshot_id(snapshot)
    first = sample_observation()
    second = replace(first, source_snapshot_id=sid, archive_available_at=T + timedelta(hours=3))
    build = sample_build(rows=(first, second), source_snapshot_ids=(first.source_snapshot_id, sid))
    result = materialize(tmp_path, build, (snapshot, sample_snapshot()))
    assert len(result.verified_build.rows) == 2
    assert len(result.verified_build.source_snapshots) == 2


@pytest.mark.skipif(os.name != "nt", reason="actual Windows staging junction regression")
def test_staging_junction_prevents_cleanup_of_external_data(tmp_path, monkeypatch):
    import _winapi
    external = tmp_path / "external"
    external.mkdir()
    (external / "evidence").write_bytes(b"retain")
    inserted = []
    def inject(owner):
        junction = owner.path / "injected-junction"
        _winapi.CreateJunction(str(external), str(junction))
        inserted.append(junction)
        raise OSError("injected junction before cleanup")
    monkeypatch.setattr(m, "_publish", inject)
    try:
        with pytest.raises(ObservationMaterializationError, match="cleanup refused"):
            materialize(tmp_path)
        assert (external / "evidence").read_bytes() == b"retain"
        assert inserted[0].parent.is_dir()
    finally:
        for junction in inserted:
            junction.rmdir()


def test_exact_governance_inventory_and_frozen_base_bindings():
    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("observation_a2_gate", repo / "scripts/check_destructive_design_gate.py")
    gate = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = gate
    spec.loader.exec_module(gate)
    findings = []
    for path in (repo / "src/market_vault/observation").glob("*.py"):
        found, _ = gate._analyze_source(path.relative_to(repo).as_posix(), path.read_bytes())
        findings.extend(found)
    assert {(f.symbol, f.kind, f.signal) for f in findings} == {
        ("_rename_directory_no_replace_windows", "destructive_call", "os.rename"),
        ("_remove_tree", "destructive_call", "shutil.rmtree"),
    }
    assert len(findings) == 2
    assert all(f.path == "src/market_vault/observation/materialization.py" for f in findings)
