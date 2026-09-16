"""Frozen physical encoder vectors and portable replay of admitted artifacts."""

from dataclasses import replace
from datetime import date
import hashlib

import pytest

from market_vault.multi_source import load_verified_multi_source_dataset, MultiSourceDatasetArtifactError
from market_vault.multi_source._artifact_schema import table_contracts, parquet_bytes
from market_vault.multi_source._serialization import canonical_json, read_json, timestamp, evidence_from_bytes, payload, evidence_payload
from market_vault.multi_source.manifest import MANIFEST_FIELDS, manifest_from_payload, serialize_multi_source_dataset_manifest
import _multi_source_artifact_vectors as vectors


def test_M0_literal_canonical_encoding_and_authority_rejection(tmp_path):
    from test_multi_source_identity import matrix_vector, evidence_vector, vector_results, U, Z, O, P, Q
    from test_multi_source_feature_identity import fixture_value, COMPLETE_CONTENT
    from market_vault.observation.pit_identity import observation_build_pin_id
    from market_vault.observation.identity import observation_coverage_id
    from market_vault.multi_source.manifest import SPEC_ARTIFACT_VERSIONS
    from market_vault.multi_source.identity import _VERSIONS
    result = vector_results()
    evidence, value = evidence_vector(), fixture_value()
    schema, _ = matrix_vector()
    m0 = dict(_VERSIONS, dataset_id=result["dataset"], dataset_kind="SUPERVISED", status="COMPLETE", built_at=U,
        scope=dict(symbols=["US.TEST"], trade_dates=["2026-01-02"], adjustment="NONE", interval="1m", requested_session="RTH"),
        dataset_as_of=None, schema=payload(schema), dataset_schema_id=result["schema"], logical_dataset_content_id=result["content"],
        logical_row_count=1, row_order="CODE_FEATURE_CLOSE_SAMPLE_KEY", canonical_builds=[], canonical_row_version_ids=[],
        bar_feature_specs=[], observation_feature_specs=[payload(value.spec_pin)], label_specs=[], split_spec=None,
        implementations=[payload(value.implementation_pin)], completion=dict(complete_count=0, incomplete_count=0, missing_count=0, entries=[]),
        gap_references=[], sample_audit=[], output_files=[], bar_association_schema_id=O, bar_association_content_id=Z,
        bar_association_schema_version="pit-association-schema-v1", observation_association_content_id=P, sample_binding_content_id=Q,
        combined_association_content_id=result["combined"], observation_evidence_content_id=result["evidence"],
        observation_build_pin_ids=[observation_build_pin_id(evidence.build_pins[0])],
        observation_coverage_ids=[observation_coverage_id(evidence.coverages[0])],
        observation_feature_values_content_id=COMPLETE_CONTENT, sample_audit_content_id=result["empty_audit"],
        materializer_version="multi-source-dataset-materializer-v1", reader_contract_version="multi-source-dataset-reader-v1",
        spec_artifact_versions=SPEC_ARTIFACT_VERSIONS)
    assert set(m0) == MANIFEST_FIELDS
    assert canonical_json(m0) == vectors.M0_BYTES
    assert hashlib.sha256(canonical_json(m0)).hexdigest() == vectors.M0_SHA256
    root = tmp_path / result["dataset"]
    (root / "associations").mkdir(parents=True)
    (root / "manifest.json").write_bytes(vectors.M0_BYTES)
    (root / "associations/observation_evidence.json").write_bytes(canonical_json(evidence_payload((evidence,))))
    (root / "_SUCCESS").write_bytes(b"")
    with pytest.raises(MultiSourceDatasetArtifactError):
        load_verified_multi_source_dataset(root)


@pytest.mark.parametrize("case", ["COMPLETE", "EMPTY"])
def test_fixed_admitted_e2e_artifact(case, tmp_path):
    raw = getattr(vectors, case + "_MANIFEST_BYTES")
    expected_ids = getattr(vectors, case + "_IDENTITIES")
    obj = read_json(raw)
    assert hashlib.sha256(raw).hexdigest() == getattr(vectors, case + "_MANIFEST_SHA256")
    assert {k: obj[k] for k in expected_ids} == expected_ids
    texts = getattr(vectors, case + "_TEXTS")
    tables = getattr(vectors, case + "_TABLES")
    evidence = evidence_from_bytes(texts["associations/observation_evidence.json"].encode())
    manifest = manifest_from_payload(obj, evidence)
    assert serialize_multi_source_dataset_manifest(manifest) == raw
    files = {name: value.encode() for name, value in texts.items()}
    # Original byte facts remain literal above. Only physical Parquet facts may
    # change when replaying these same records with a different Arrow version.
    for contract in table_contracts(manifest.identity_input):
        rows = []
        for source in tables[contract[0]]:
            row = dict(source)
            for f in contract[4].fields:
                if row[f.name] is not None:
                    if f.logical_type == "timestamp_us_utc":
                        row[f.name] = timestamp(row[f.name])
                    elif f.logical_type == "date32":
                        row[f.name] = date.fromisoformat(row[f.name])
            rows.append(row)
        files[contract[0]] = parquet_bytes(manifest.dataset_id, contract, tuple(rows))
    facts = tuple(replace(f, byte_size=len(files[f.relative_path]), sha256=hashlib.sha256(files[f.relative_path]).hexdigest())
                  for f in manifest.output_files)
    replay = replace(manifest, output_files=facts)
    root = tmp_path / replay.dataset_id
    root.mkdir()
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (root / "manifest.json").write_bytes(serialize_multi_source_dataset_manifest(replay))
    (root / "_SUCCESS").write_bytes(b"")
    verified = load_verified_multi_source_dataset(root)
    assert verified.status == case
    assert verified.dataset_id == expected_ids["dataset_id"]
    assert tuple((f.relative_path, f.file_role) for f in verified.manifest.output_files) == getattr(vectors, case + "_ROLES")
    assert verified.sample_audit and verified.observation_evidence and verified.sample_bindings
    if case == "EMPTY":
        assert not verified.rows
        assert verified.observation_feature_result.samples[0].values[0].consumed_observation_version_id is None
