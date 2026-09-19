"""Strict physical manifest and complete recorded-file closure."""

from datetime import datetime, timezone
from hashlib import sha256

import pytest

from market_vault.cross_day_dataset._artifact_encoding import canonical_json, decode_json
from market_vault.cross_day_dataset._artifact_projection import _content_bytes
from market_vault.cross_day_dataset.manifest import _manifest_bytes, _validate_manifest_content
from test_cross_day_artifact_canonical import prepared


BUILT_AT = datetime(2026, 1, 2, tzinfo=timezone.utc)


def fixture(tmp_path, case="A"):
    original, data = prepared(tmp_path, case)
    content = dict(_content_bytes(data))
    manifest = _manifest_bytes(data, content, BUILT_AT)
    return original, data, content, manifest


@pytest.mark.parametrize("case", ("A", "B", "C", "D", "E", "F", "G", "H_considered", "H_backing"))
def test_manifest_all_frozen_cases(tmp_path, case):
    original, _, content, manifest = fixture(tmp_path, case)
    recorded, payload = _validate_manifest_content(manifest, content)
    assert payload["dataset_id"] == original.dataset_id
    assert len(payload["identity"]) == 49
    assert set(payload) == set((
        "manifest_schema_version dataset_id identity status built_at logical_row_count schema scope completion row_order "
        "materializer_version reader_contract_version build_report_contract_version spec_artifact_versions output_files"
    ).split())
    assert payload["logical_row_count"] == len(original.rows)
    assert recorded.rows == original.rows
    assert tuple(r["relative_path"] for r in payload["output_files"]) == tuple(sorted(content))
    assert "manifest.json" not in content and "_SUCCESS" not in content


@pytest.mark.parametrize("field,value", [
    ("dataset_id", "0" * 64), ("manifest_schema_version", "market-vault-dataset-manifest-v1"),
    ("status", "EMPTY"), ("logical_row_count", True), ("row_order", "INPUT"),
    ("output_files", []), ("materializer_version", "unknown"), ("reader_contract_version", "unknown"),
    ("build_report_contract_version", "unknown"), ("identity", {}), ("extra", "not allowed"),
])
def test_manifest_rejects_tamper(tmp_path, field, value):
    _, _, content, manifest = fixture(tmp_path)
    payload = decode_json(manifest)
    payload[field] = value
    with pytest.raises(ValueError):
        _validate_manifest_content(canonical_json(payload), content)


@pytest.mark.parametrize("path", ("feature_pit.json", "canonical_evidence.json", "ts2_features.json", "observation_pit.json",
    "observation_evidence.json", "observation_features.json", "cross_day_association.json", "cross_day_values.json",
    "schedule.json", "sample_audit.json", "split.json", "build_report.json", "dataset.parquet", "specs/split.yaml"))
def test_every_content_file_required(tmp_path, path):
    _, _, content, manifest = fixture(tmp_path)
    del content[path]
    with pytest.raises(ValueError):
        _validate_manifest_content(manifest, content)


def test_extra_file_rejected_even_with_rehashed_inventory(tmp_path):
    _, _, content, manifest = fixture(tmp_path)
    content[".hidden"] = b"hidden"
    payload = decode_json(manifest)
    payload["output_files"].append(dict(relative_path=".hidden", file_role="MATRIX", artifact_version="unknown",
        row_count=0, byte_size=6, sha256=sha256(b"hidden").hexdigest(), content_role="MATRIX", content_id="0" * 64))
    with pytest.raises(ValueError):
        _validate_manifest_content(canonical_json(payload), content)


def test_built_at_changes_only_physical_metadata(tmp_path):
    original, data, content, manifest = fixture(tmp_path)
    later = _manifest_bytes(data, content, datetime(2026, 2, 1, tzinfo=timezone.utc))
    _, first = _validate_manifest_content(manifest, content)
    _, second = _validate_manifest_content(later, content)
    assert first["dataset_id"] == second["dataset_id"] == original.dataset_id
    assert first["identity"] == second["identity"]
    assert first["built_at"] != second["built_at"]
    with pytest.raises(ValueError, match="precedes"):
        _manifest_bytes(data, content, datetime(2020, 1, 1, tzinfo=timezone.utc))
