"""Read-only recorded Canonical/PIT admission with full selection validation."""

from dataclasses import replace

import pytest

from cross_day_dataset_helpers import fixture
from market_vault.cross_day_dataset import execution
from market_vault.cross_day_dataset._artifact_projection import _prepare_artifact_facts
from market_vault.cross_day_dataset._artifact_canonical import _canonical_closure, _pit_closure
from market_vault.cross_day_dataset._artifact_records import _Recorded
from market_vault.cross_day_dataset._artifact_values import _value
from market_vault.cross_day_dataset.artifact_models import MultiSourceCrossDayArtifactError


def change(record, **changes):
    return _Recorded(record._schema_name, tuple((k, changes.get(k, v)) for k, v in record._items))


def prepared(tmp_path, case="A"):
    result = execution.join_multi_source_cross_day_dataset(**fixture(tmp_path, case))
    facts = execution._require_live_issued_multi_source_cross_day_dataset_artifact_facts(result)
    return result, _prepare_artifact_facts(facts)


def validate(data):
    _, builds = data.sidecar("canonical_evidence.json")
    scope = _value(data.scope)
    union, pins, gaps, rows = _canonical_closure(builds, scope)
    association, = data.sidecar("cross_day_association.json")[1]
    feature_ids = association.feature_build_ids
    features = tuple(b for b in union if b.canonical_build_id in feature_ids)
    features, pins, gaps, feature_rows = _canonical_closure(features, scope)
    pit, = data.sidecar("feature_pit.json")[1]
    return _pit_closure(pit, features, pins, gaps, feature_rows, scope, data.dataset_as_of)


@pytest.mark.parametrize("case", ["A", "B", "C", "D", "E", "F", "G", "H_considered", "H_backing"])
def test_recorded_canonical_and_pit_closure(tmp_path, case):
    result, data = prepared(tmp_path, case)
    pit = validate(data)
    assert pit.samples == result.feature_pit.samples
    assert pit.association_content_id == result.feature_pit.association_content_id
    assert type(pit) is not type(result.feature_pit)


@pytest.mark.parametrize("field,value", [
    ("canonical_content_id", "0" * 64), ("canonical_build_id", "0" * 64),
    ("canonical_row_version_ids", ()), ("source_snapshot_provenance", ()),
    ("gap_content_id", "0" * 64), ("gap_count", 1),
    ("status", "EMPTY"), ("canonical_schema_version", "wrong"),
])
def test_full_canonical_evidence_tamper_rejected(tmp_path, field, value):
    _, data = prepared(tmp_path)
    _, builds = data.sidecar("canonical_evidence.json")
    with pytest.raises(MultiSourceCrossDayArtifactError):
        _canonical_closure(tuple(change(b, **{field: value}) for b in builds), _value(data.scope))


@pytest.mark.parametrize("field,value", [
    ("association_content_id", "0" * 64), ("association_schema_id", "0" * 64),
    ("canonical_row_version_ids", ()), ("canonical_build_pins", ()),
    ("gap_references", ()), ("association_rows", ()), ("samples", ()),
])
def test_recorded_pit_tamper_rejected(tmp_path, field, value):
    _, data = prepared(tmp_path)
    sidecars = tuple((p, k, (change(rs[0], **{field: value}),) if p == "feature_pit.json" else rs)
                     for p, k, rs in data.sidecars)
    with pytest.raises(MultiSourceCrossDayArtifactError):
        validate(replace(data, sidecars=sidecars))
