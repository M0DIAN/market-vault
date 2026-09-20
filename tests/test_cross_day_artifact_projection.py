"""Complete artifact content preparation reads only the issuance snapshot."""

from dataclasses import fields
from datetime import datetime, timezone

import pytest

from cross_day_dataset_helpers import fixture
from market_vault.cross_day_dataset import execution
from market_vault.cross_day_dataset._artifact_encoding import decode_json, decode_parquet
from market_vault.cross_day_dataset._artifact_projection import _prepare_artifact_facts, _content_bytes
from market_vault.cross_day_dataset._artifact_records import _read_facts
from market_vault.cross_day_dataset._artifact_values import _value, _VALUE_TYPES


def prepare(result):
    return _prepare_artifact_facts(execution._require_live_issued_multi_source_cross_day_dataset_artifact_facts(result))


@pytest.mark.parametrize("case", ["A", "B", "C", "D", "E", "F", "G", "H_considered", "H_backing"])
def test_full_preparation_exact_records_specs_and_matrix(tmp_path, case):
    result = execution.join_multi_source_cross_day_dataset(**fixture(tmp_path, case))
    prepared = prepare(result)
    files = _content_bytes(prepared)
    assert len(fields(type(result))) == 19
    assert prepared.dataset_id == result.dataset_id
    assert prepared.rows == result.rows
    assert prepared.status == result.status
    assert decode_parquet(files["dataset.parquet"], result.schema) == result.rows
    assert len(files) == 17 + (3 if case == "F" else 0)
    assert set(files) == {"dataset.parquet", *(path for path, _, _ in prepared.sidecars),
                          *(path for path, _, _, _ in prepared.specs)}
    for path, kind, values in prepared.sidecars:
        if path == "build_report.json":
            assert decode_json(files[path])["artifact_version"] == "multi-source-cross-day-build-report-v1"
        else:
            assert _read_facts(kind, files[path]) == values
    for _, _, _, data in prepared.specs:
        assert data.endswith(b"\n")
    ts2 = decode_json(files["ts2_features.json"])["records"][0]
    assert len(ts2["implementation_source_hashes"]) == 8
    assert all(set(r) == {"transform_ref", "source_sha256"} for r in ts2["implementation_source_hashes"])
    l2 = decode_json(files["cross_day_association.json"])["records"][0]
    assert set(l2) == {"feature_build_ids", "label_build_ids", "dataset_as_of", "decisions", "sample_bindings"}
    evidence = decode_json(files["observation_evidence.json"])["records"]
    assert len(evidence) == len(result.observation_builds)
    assert all(set(r) == {"identity_input", "source_snapshots", "created_at"} for r in evidence)
    assert all(b"manifest_payload" not in files[p] and b"snapshot_file" not in files[p]
               for p in ("canonical_evidence.json", "observation_evidence.json"))


def test_post_bridge_mutation_cannot_change_prepared_content(tmp_path):
    result = execution.join_multi_source_cross_day_dataset(**fixture(tmp_path))
    facts = execution._require_live_issued_multi_source_cross_day_dataset_artifact_facts(result)
    original = _content_bytes(_prepare_artifact_facts(facts))
    object.__setattr__(result.ts2_features.samples[0].values[0], "value", 999.0)
    object.__setattr__(result, "rows", ())
    object.__setattr__(result, "schedule", None)
    object.__setattr__(result, "identity_input", None)
    assert _content_bytes(_prepare_artifact_facts(facts)) == original
    assert b'"value":0.25' in original["ts2_features.json"]
    assert b'"value":999.0' not in original["ts2_features.json"]


def test_caller_graph_access_after_capture_not_used(tmp_path, monkeypatch):
    result = execution.join_multi_source_cross_day_dataset(**fixture(tmp_path))
    facts = execution._require_live_issued_multi_source_cross_day_dataset_artifact_facts(result)
    expected = _content_bytes(_prepare_artifact_facts(facts))

    def denied(self, name):
        raise AssertionError("caller result graph reread: " + name)

    monkeypatch.setattr(type(result), "__getattribute__", denied)
    assert _content_bytes(_prepare_artifact_facts(facts)) == expected


def test_value_converter_cannot_construct_upstream_live_results():
    assert not {"PITAssemblyResult", "TS2FeatureExecutionResult", "TS2FeatureSampleResult", "TS2FeatureValueResult",
                "ObservationPITAssemblyResult", "ObservationFeatureExecutionResult", "VerifiedObservationBuild",
                "CrossDayLabelAssemblyResult", "CrossDayLabelExecutionResult", "VerifiedCanonicalBuild",
                "MultiSourceCrossDayDatasetResult"} & _VALUE_TYPES.keys()
