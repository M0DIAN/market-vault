"""Read-only authority reconstruction and adversarial physical artifact checks."""

import ast
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
import hashlib
import os
from pathlib import Path
import shutil
import socket
import sys
import time

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from market_vault.observation import ObservationArtifactError, VerifiedObservationBuild, load_verified_observation_build
from market_vault.observation import reader, materialization
from market_vault.observation.artifact_schema import OBSERVATION_ARROW_SCHEMA, OBSERVATION_PARQUET_PATH
from market_vault.observation.manifest import canonical_json, read_json
from test_observation_materialization import materialize
from test_observation_models import H, T, sample_build, sample_observation


def manifest_mutation(build_dir, change):
    path = build_dir / "manifest.json"
    value = read_json(path.read_bytes())
    change(value)
    path.write_bytes(canonical_json(value))


def parquet_mutation(build_dir, change):
    path = build_dir / OBSERVATION_PARQUET_PATH
    table = pq.read_table(pa.BufferReader(path.read_bytes()))
    table = change(table)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink)
    data = sink.getvalue().to_pybytes()
    path.write_bytes(data)
    def rehash(value):
        value["output_files"][0]["sha256"] = hashlib.sha256(data).hexdigest()
        value["output_files"][0]["byte_size"] = len(data)
    manifest_mutation(build_dir, rehash)


def test_relocation_and_deep_immutability(tmp_path):
    source = materialize(tmp_path / "source").build_dir
    target = tmp_path / "relocated" / source.name
    shutil.copytree(source, target)
    result = load_verified_observation_build(target)
    assert result.rows == sample_build().rows
    assert result.build_dir == target
    with pytest.raises(FrozenInstanceError):
        result.status = "EMPTY"
    with pytest.raises(TypeError):
        result.manifest_payload["status"] = "EMPTY"
    with pytest.raises(TypeError):
        result.manifest_payload["output_files"][0]["sha256"] = H[0]
    with pytest.raises(TypeError):
        VerifiedObservationBuild()
    for name in ("from_unverified", "trust_me", "skip_validation"):
        assert not hasattr(VerifiedObservationBuild, name)


@pytest.mark.parametrize("field", ["observation_build_id", "observation_content_id", "coverage_id",
                                  "manifest_version", "artifact_format_version", "materializer_version",
                                  "observation_schema_version", "status", "row_count", "source_snapshot_count",
                                  "created_at", "time_bounds", "provider_contracts", "normalizations",
                                  "authority_evidence_ids"])
def test_manifest_claim_corruption(tmp_path, field):
    path = materialize(tmp_path).build_dir
    manifest_mutation(path, lambda v: v.__setitem__(field, "tampered"))
    with pytest.raises(ObservationArtifactError):
        load_verified_observation_build(path)


def test_invalid_utf8_manifest_has_artifact_error_boundary(tmp_path):
    path = materialize(tmp_path).build_dir
    (path / "manifest.json").write_bytes(b"\xff")
    with pytest.raises(ObservationArtifactError) as caught:
        load_verified_observation_build(path)
    assert isinstance(caught.value.__cause__, UnicodeDecodeError)


def test_arrow_capacity_error_has_artifact_error_boundary(tmp_path, monkeypatch):
    path = materialize(tmp_path).build_dir
    error = pa.ArrowCapacityError("injected Parquet capacity failure")
    assert isinstance(error, pa.ArrowException)
    assert not isinstance(error, (ValueError, TypeError, OSError))
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(reader.pq, "read_table", fail)
    with pytest.raises(ObservationArtifactError) as caught:
        load_verified_observation_build(path)
    assert caught.value.__cause__ is error


def test_existing_artifact_error_remains_unwrapped(tmp_path, monkeypatch):
    error = ObservationArtifactError("already classified")
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(reader, "_verify_directory", fail)
    with pytest.raises(ObservationArtifactError) as caught:
        load_verified_observation_build(tmp_path)
    assert caught.value is error
    assert caught.value.__cause__ is None


@pytest.mark.parametrize("member", ["manifest.json", OBSERVATION_PARQUET_PATH, "_SUCCESS"])
def test_content_mutation_after_first_read_fails_with_unchanged_inventory(tmp_path, monkeypatch, member):
    root = materialize(tmp_path).build_dir
    target = root / member
    initial = target.read_bytes()
    changed = bytes([initial[0] ^ 1]) + initial[1:] if initial else b"not-empty"
    inventory = reader._inventory(root)
    original_read = reader._read_bytes
    reads = []
    def mutate_after_read(path):
        data = original_read(path)
        if path == target:
            reads.append(data)
            if len(reads) == 1:
                target.write_bytes(changed)
                assert reader._inventory(root) == inventory
        return data
    monkeypatch.setattr(reader, "_read_bytes", mutate_after_read)
    with pytest.raises(ObservationArtifactError, match="changed during verification|empty regular commit marker"):
        load_verified_observation_build(root)
    assert reads == [initial, changed]
    assert reader._inventory(root) == inventory
    assert target.read_bytes() == changed


@pytest.mark.parametrize("field", ["value_schema_id", "observation_key", "observation_version_id",
                                  "source_snapshot_id", "source_content_sha256", "known_at_authority_id",
                                  "provider_contract_content_id", "normalization_content_id"])
def test_stored_row_ids_recomputed_even_after_physical_rehash(tmp_path, field):
    path = materialize(tmp_path).build_dir
    def change(table):
        rows = table.to_pylist()
        rows[0][field] = "f" * 64
        return pa.Table.from_pylist(rows, schema=OBSERVATION_ARROW_SCHEMA)
    parquet_mutation(path, change)
    with pytest.raises(ObservationArtifactError):
        load_verified_observation_build(path)


@pytest.mark.parametrize("value", ["[true,12]\n", "[1,12]\n", "[NaN,12]\n", "[4.25,9223372036854775808]\n"])
def test_physical_values_keep_numeric_type_safety(tmp_path, value):
    path = materialize(tmp_path).build_dir
    def change(table):
        rows = table.to_pylist()
        rows[0]["values"] = value
        return pa.Table.from_pylist(rows, schema=OBSERVATION_ARROW_SCHEMA)
    parquet_mutation(path, change)
    with pytest.raises(ObservationArtifactError):
        load_verified_observation_build(path)


@pytest.mark.parametrize("case", ["nullable", "metadata", "extra", "order", "duplicate", "reverse_rows"])
def test_exact_schema_and_order(tmp_path, case):
    build = sample_build(rows=(sample_observation(), sample_observation(event_time=T + timedelta(hours=1))))
    path = materialize(tmp_path, build).build_dir
    def change(table):
        if case == "nullable":
            schema = pa.schema([pa.field(f.name, f.type, nullable=True) for f in table.schema])
            return table.cast(schema)
        if case == "metadata":
            return table.replace_schema_metadata({b"unknown": b"value"})
        if case == "extra":
            return table.append_column("extra", pa.array([1] * table.num_rows))
        if case == "order":
            return table.select(list(reversed(table.column_names)))
        if case == "duplicate":
            return pa.concat_tables([table, table])
        return table.take(pa.array([1, 0]))
    parquet_mutation(path, change)
    with pytest.raises(ObservationArtifactError):
        load_verified_observation_build(path)


@pytest.mark.parametrize("field", ["sha256", "byte_size", "row_count", "file_role", "content_role"])
def test_output_file_facts(tmp_path, field):
    path = materialize(tmp_path).build_dir
    manifest_mutation(path, lambda v: v["output_files"][0].__setitem__(field, "bad"))
    with pytest.raises(ObservationArtifactError):
        load_verified_observation_build(path)


@pytest.mark.parametrize("relative", ["/absolute", "../outside", "./observations/x", "observations//x",
                                     "observations/../x", "observations\\x", "D:/x", "x:ads", "", "."])
def test_member_paths_never_traversed(tmp_path, relative):
    path = materialize(tmp_path).build_dir
    manifest_mutation(path, lambda v: v["output_files"][0].__setitem__("relative_path", relative))
    with pytest.raises(ObservationArtifactError):
        load_verified_observation_build(path)


@pytest.mark.parametrize("case", ["extra_file", "extra_directory", "missing_manifest", "missing_parquet",
                                 "missing_success", "bad_success", "parquet_bytes", "manifest_unknown",
                                 "manifest_missing", "manifest_duplicate", "snapshot_id", "coverage", "wrong_name"])
def test_artifact_corruption_fails_closed(tmp_path, case):
    path = materialize(tmp_path).build_dir
    if case == "extra_file":
        (path / "unexpected").write_bytes(b"x")
    elif case == "extra_directory":
        (path / "unexpected").mkdir()
    elif case.startswith("missing_"):
        member = {"missing_manifest": "manifest.json", "missing_parquet": OBSERVATION_PARQUET_PATH,
                  "missing_success": "_SUCCESS"}[case]
        (path / member).unlink()
    elif case == "bad_success":
        (path / "_SUCCESS").write_bytes(b"not enough")
    elif case == "parquet_bytes":
        (path / OBSERVATION_PARQUET_PATH).write_bytes(b"invalid")
    elif case == "manifest_unknown":
        manifest_mutation(path, lambda v: v.__setitem__("unknown", True))
    elif case == "manifest_missing":
        manifest_mutation(path, lambda v: v.pop("coverage"))
    elif case == "manifest_duplicate":
        data = (path / "manifest.json").read_bytes()
        (path / "manifest.json").write_bytes(b'{"status":"COMPLETE",' + data[1:])
    elif case == "snapshot_id":
        manifest_mutation(path, lambda v: v["source_snapshots"][0].__setitem__("source_snapshot_id", H[10]))
    elif case == "coverage":
        manifest_mutation(path, lambda v: v["coverage"].__setitem__("request_pages_complete", False))
    else:
        target = path.parent / "build_id=wrong"
        path.rename(target)
        path = target
    with pytest.raises(ObservationArtifactError):
        load_verified_observation_build(path)


def test_success_alone_and_relative_path_have_no_authority(tmp_path):
    (tmp_path / "_SUCCESS").write_bytes(b"")
    with pytest.raises(ObservationArtifactError):
        load_verified_observation_build(tmp_path)
    with pytest.raises(ObservationArtifactError):
        load_verified_observation_build("relative")


def test_symlinked_file_and_output_ancestor_rejected(tmp_path):
    path = materialize(tmp_path / "real").build_dir
    external = tmp_path / "external"
    external.write_bytes((path / "_SUCCESS").read_bytes())
    (path / "_SUCCESS").unlink()
    try:
        (path / "_SUCCESS").symlink_to(external)
    except OSError:
        pytest.skip("environment without symlink support")
    with pytest.raises(ObservationArtifactError, match="symlink"):
        load_verified_observation_build(path)
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path / "real", target_is_directory=True)
    with pytest.raises(ObservationArtifactError, match="symlink"):
        materialize(alias / "child")
    assert not (tmp_path / "real" / "child").exists()


@pytest.mark.skipif(os.name != "nt", reason="actual Windows junction regression")
def test_non_escaping_windows_junction_rejected(tmp_path):
    import _winapi
    path = materialize(tmp_path).build_dir
    observations = path / "observations"
    target = path / "retained-observations"
    observations.rename(target)
    _winapi.CreateJunction(str(target), str(observations))
    try:
        assert not observations.is_symlink()
        assert observations.resolve().is_relative_to(path.resolve())
        assert observations.lstat().st_file_attributes & 0x400
        with pytest.raises(ObservationArtifactError, match="junction|reparse"):
            load_verified_observation_build(path)
        with pytest.raises(ObservationArtifactError, match="junction|reparse"):
            materialize(tmp_path)
    finally:
        observations.rmdir()


def test_no_clock_network_settings_or_cwd_dependency(tmp_path, monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("forbidden side channel")
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(time, "time", forbidden)
    monkeypatch.setattr(Path, "cwd", forbidden)
    monkeypatch.setattr(os, "getcwd", forbidden)
    result = materialize(tmp_path)
    assert load_verified_observation_build(result.build_dir).rows == sample_build().rows


def test_a2_public_scope_and_reader_read_only_ast():
    import market_vault
    import market_vault.observation as api
    assert not hasattr(market_vault, "load_verified_observation_build")
    # A3 adds only the reviewed parallel PIT sidecar, not Feature execution.
    a3_exports = {
        "assemble_observation_pit_sidecar", "ObservationPITError", "ObservationPITFeatureBinding",
        "ObservationPITDecision", "ObservationPITAssemblyResult", "feature_spec_pin_id",
        "OBSERVATION_FEATURE_SPEC_PIN_ID_VERSION", "MULTI_SOURCE_PIT_CONTRACT_VERSION",
    }
    assert a3_exports <= set(api.__all__)
    assert not any(token in name.lower() for name in api.__all__ if name not in a3_exports
                   for token in ("provider", "pit", "feature", "latest", "catalog"))
    tree = ast.parse(Path(reader.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            assert name not in {"now", "utcnow", "getcwd", "getenv", "connect", "urlopen", "mkdir",
                                "write_bytes", "write_text", "unlink", "remove", "rmtree", "rename", "replace"}
            if name == "open":
                assert len(node.args) == 1 and node.args[0].value == "rb"


def test_cross_filesystem_member_is_not_traversed(tmp_path, monkeypatch):
    from types import SimpleNamespace
    path = materialize(tmp_path).build_dir
    original = Path.lstat
    def changed_device(self, *args, **kwargs):
        value = original(self, *args, **kwargs)
        if self == path / "observations":
            return SimpleNamespace(st_dev=value.st_dev + 1, st_mode=value.st_mode)
        return value
    monkeypatch.setattr(Path, "lstat", changed_device)
    with pytest.raises(ObservationArtifactError, match="cross-filesystem"):
        load_verified_observation_build(path)
