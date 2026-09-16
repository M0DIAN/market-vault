"""A4.3 canaries 33-48 and read-only physical closure."""

from dataclasses import fields
import hashlib
import socket

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from market_vault.multi_source import load_verified_multi_source_dataset, MultiSourceDatasetArtifactError
from market_vault.multi_source import reader
from market_vault.multi_source._serialization import canonical_json, read_json
from test_multi_source_artifact import candidate, artifact, rewrite
from test_multi_source_orchestration import fixtures, artifacts, observation_factory


@pytest.mark.parametrize("name", ["dataset.parquet", "associations/bar.parquet", "associations/observation.parquet",
    "associations/sample_bindings.parquet", "associations/observation_feature_values.parquet", "associations/observation_evidence.json"])
def test_component_byte_corruption(artifact, name):
    path = artifact / name
    path.write_bytes(path.read_bytes() + b"corrupt")
    with pytest.raises(MultiSourceDatasetArtifactError, match="hash|canonical|Extra data"):
        load_verified_multi_source_dataset(artifact)


@pytest.mark.parametrize("name,column,value", [
    ("dataset.parquet", "obs_rate", 81.25),
    ("associations/bar.parquet", "sample_version_id", "0"*64),
    ("associations/observation.parquet", "selected_known_at_authority_id", "0"*64),
    ("associations/sample_bindings.parquet", "observation_binding_id", "0"*64),
    ("associations/observation_feature_values.parquet", "consumed_observation_version_id", "0"*64),
    ("associations/observation_feature_values.parquet", "value_float64", 123.25),
])
def test_rehashed_logical_corruption(artifact, name, column, value):
    path = artifact / name
    table = pq.read_table(pa.BufferReader(path.read_bytes()))
    rows = table.to_pylist()
    rows[0][column] = value
    sink = pa.BufferOutputStream()
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), sink)
    rewrite(artifact, name, sink.getvalue().to_pybytes())
    with pytest.raises(MultiSourceDatasetArtifactError):
        load_verified_multi_source_dataset(artifact)


@pytest.mark.parametrize("mutation", ["schema", "nullable", "metadata", "field_metadata", "row_count"])
def test_physical_contract_mismatch(artifact, mutation):
    path = artifact / "dataset.parquet"
    table = pq.read_table(pa.BufferReader(path.read_bytes()))
    if mutation == "row_count":
        manifest = read_json((artifact / "manifest.json").read_bytes())
        next(f for f in manifest["output_files"] if f["relative_path"] == "dataset.parquet")["row_count"] = 9
        (artifact / "manifest.json").write_bytes(canonical_json(manifest))
    else:
        schema = table.schema
        if mutation == "metadata":
            schema = schema.with_metadata(dict(schema.metadata) | {b"unexpected": b"authority"})
        elif mutation == "schema":
            schema = schema.set(0, pa.field("wrong", schema.field(0).type, nullable=False))
        elif mutation == "nullable":
            schema = schema.set(0, pa.field(schema.field(0).name, schema.field(0).type, nullable=True))
        else:
            schema = schema.set(0, schema.field(0).with_metadata({b"extra": b"bad"}))
        sink = pa.BufferOutputStream()
        pq.write_table(pa.Table.from_arrays(table.columns, schema=schema), sink)
        rewrite(artifact, "dataset.parquet", sink.getvalue().to_pybytes())
    with pytest.raises(MultiSourceDatasetArtifactError):
        load_verified_multi_source_dataset(artifact)


@pytest.mark.parametrize("mutation", ["extra", "missing", "missing_marker", "marker", "identity", "role", "path", "version", "duplicate_json", "unknown"])
def test_whitelist_manifest_marker_rejection(artifact, mutation):
    if mutation == "extra":
        (artifact / ".unlisted").write_bytes(b"x")
    elif mutation == "missing":
        (artifact / "associations/bar.parquet").unlink()
    elif mutation == "missing_marker":
        (artifact / "_SUCCESS").unlink()
    elif mutation == "marker":
        (artifact / "_SUCCESS").write_bytes(b"not empty")
    else:
        path = artifact / "manifest.json"
        obj = read_json(path.read_bytes())
        if mutation == "identity":
            obj["dataset_id"] = "0"*64
        elif mutation == "role":
            obj["output_files"][0]["file_role"] = "MATRIX"
        elif mutation == "path":
            obj["output_files"][0]["relative_path"] = "../source"
        elif mutation == "version":
            obj["reader_contract_version"] = "future"
        elif mutation == "unknown":
            obj["repair"] = True
        if mutation == "duplicate_json":
            path.write_bytes(b'{"status":"EMPTY",' + canonical_json(obj)[1:])
        else:
            path.write_bytes(canonical_json(obj))
    with pytest.raises(MultiSourceDatasetArtifactError):
        load_verified_multi_source_dataset(artifact)


def test_success_alone_not_authority(tmp_path):
    root = tmp_path / ("0"*64)
    root.mkdir()
    (root / "_SUCCESS").write_bytes(b"")
    with pytest.raises(MultiSourceDatasetArtifactError):
        load_verified_multi_source_dataset(root)


@pytest.mark.parametrize("family", ["feature_specs/bar", "feature_specs/observation", "label_specs"])
def test_noncanonical_spec_fails_even_when_rehashed(artifact, family):
    path, = (artifact / family).iterdir()
    rewrite(artifact, path.relative_to(artifact).as_posix(), b"# ignored semantic comment\n" + path.read_bytes())
    with pytest.raises(MultiSourceDatasetArtifactError, match="spec"):
        load_verified_multi_source_dataset(artifact)


def test_evidence_pair_loss_rehashed(artifact):
    name = "associations/observation_evidence.json"
    obj = read_json((artifact / name).read_bytes())
    obj["items"][0]["proofs"][0]["coverage"]["revision_inventory_content_id"] = "0"*64
    rewrite(artifact, name, canonical_json(obj))
    with pytest.raises(MultiSourceDatasetArtifactError, match="pair|coverage|identity"):
        load_verified_multi_source_dataset(artifact)


@pytest.mark.parametrize("name", ["manifest.json", "dataset.parquet", "associations/bar.parquet",
    "associations/observation.parquet", "associations/sample_bindings.parquet",
    "associations/observation_feature_values.parquet", "associations/observation_evidence.json", "build_report.json", "_SUCCESS"])
def test_same_inventory_content_change_between_passes(artifact, monkeypatch, name):
    original = reader.read_bytes
    done = False
    def changing(path):
        nonlocal done
        data = original(path)
        if path == artifact / name and not done:
            done = True
            path.write_bytes(data + b" ")
        return data
    monkeypatch.setattr(reader, "read_bytes", changing)
    with pytest.raises(MultiSourceDatasetArtifactError, match="changed|marker"):
        load_verified_multi_source_dataset(artifact)
    assert done


def test_unicode_error_preserves_cause(artifact):
    (artifact / "manifest.json").write_bytes(b"\xff")
    with pytest.raises(MultiSourceDatasetArtifactError) as caught:
        load_verified_multi_source_dataset(artifact)
    assert isinstance(caught.value.__cause__, UnicodeDecodeError)


def test_arrow_capacity_error_preserves_cause(artifact, monkeypatch):
    error = pa.ArrowCapacityError("injected capacity")
    assert not isinstance(error, (ValueError, TypeError, OSError))
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(pq, "read_table", fail)
    with pytest.raises(MultiSourceDatasetArtifactError) as caught:
        load_verified_multi_source_dataset(artifact)
    assert caught.value.__cause__ is error


def test_reader_no_upstream_or_execution_calls(artifact, monkeypatch):
    from market_vault.dataset import pit, feature_execution, label_execution
    from market_vault.observation import pit as obs_pit, reader as obs_reader
    from market_vault.canonical import reader as canonical_reader
    from market_vault.multi_source import feature_execution as obs_feature, orchestration
    def forbidden(*args, **kwargs):
        raise AssertionError("reader executed upstream authority")
    for module, name in ((pit, "assemble_point_in_time_samples"), (obs_pit, "assemble_observation_pit_sidecar"),
        (feature_execution, "execute_builtin_features"), (label_execution, "execute_builtin_labels"),
        (obs_feature, "execute_observation_features"), (orchestration, "orchestrate_multi_source_dataset_build"),
        (obs_reader, "load_verified_observation_build"), (canonical_reader, "load_verified_canonical_build")):
        monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    assert load_verified_multi_source_dataset(artifact).dataset_id == artifact.name


def test_new_reader_rejects_real_legacy_artifact(fixtures, tmp_path):
    from test_dataset_orchestration import orchestrate, request
    from market_vault.dataset import materialize_dataset_artifacts
    from test_multi_source_artifact import BUILT_AT
    old = materialize_dataset_artifacts(orchestrate(fixtures, requests=(request(),)), output_root=tmp_path / "old", built_at=BUILT_AT)
    with pytest.raises(MultiSourceDatasetArtifactError, match="unsupported manifest"):
        load_verified_multi_source_dataset(old.build_path)


def test_excluded_sample_cannot_be_reinserted(candidate, fixtures, observation_factory, tmp_path):
    from test_multi_source_orchestration import inputs, spec
    from test_multi_source_artifact import BUILT_AT
    from market_vault.multi_source import orchestrate_multi_source_dataset_build, materialize_multi_source_dataset_build
    from market_vault.multi_source._artifact_schema import table_contracts, parquet_bytes
    empty = orchestrate_multi_source_dataset_build(**inputs(fixtures, observation_factory(), observation_feature_specs=(spec(max_age_us=1),)))
    root = materialize_multi_source_dataset_build(empty, output_root=tmp_path / "empty", built_at=BUILT_AT).build_dir
    data = parquet_bytes(empty.dataset_id, table_contracts(empty.identity_input)[0], candidate.logical_row_mappings())
    rewrite(root, "dataset.parquet", data)
    obj = read_json((root / "manifest.json").read_bytes())
    obj["logical_row_count"], obj["status"] = 1, "COMPLETE"
    next(f for f in obj["output_files"] if f["relative_path"] == "dataset.parquet")["row_count"] = 1
    (root / "manifest.json").write_bytes(canonical_json(obj))
    with pytest.raises(MultiSourceDatasetArtifactError, match="matrix eligibility"):
        load_verified_multi_source_dataset(root)


@pytest.mark.parametrize("path", ["/absolute", "..", ".", "a//b", "a\\b", "C:member", "a:stream", "a/../b", "a/./b"])
def test_member_syntax_fails(path):
    from market_vault.multi_source._artifact_paths import member_path
    with pytest.raises(MultiSourceDatasetArtifactError):
        member_path(path)
