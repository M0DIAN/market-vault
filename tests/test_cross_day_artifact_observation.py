"""Artifact Observation/A3 proof multiplicity and recorded Feature closure."""

from dataclasses import replace

import pytest

from test_cross_day_artifact_canonical import prepared, change
from test_cross_day_artifact_ts2 import validation_inputs
from market_vault.cross_day_dataset._artifact_observation import _observation_closure, _observation_features_closure
from market_vault.cross_day_dataset._artifact_values import _value
from market_vault.cross_day_dataset.artifact_models import MultiSourceCrossDayArtifactError
from market_vault.multi_source.feature_identity import observation_feature_values_content_id


def validate(result, data, record=None, evidence=None):
    pit = validation_inputs(data)[0]
    record = data.sidecar("observation_pit.json")[1][0] if record is None else record
    evidence = data.sidecar("observation_evidence.json")[1] if evidence is None else evidence
    a3, proofs, selected = _observation_closure(record, evidence, result.observation_feature_specs, pit)
    features = _observation_features_closure(data.sidecar("observation_features.json")[1][0],
                                             result.observation_feature_specs, a3, selected)
    return a3, proofs, features


@pytest.mark.parametrize("case", ["A", "B", "C", "D", "E", "F", "G", "H_considered", "H_backing"])
def test_all_recorded_observation_components(tmp_path, case):
    result, data = prepared(tmp_path, case)
    a3, proofs, features = validate(result, data)
    assert type(a3) is not type(result.observation_pit)
    assert type(features) is not type(result.observation_features)
    assert proofs == result.identity_input.observation_input_proofs
    assert a3.combined_association_content_id == result.observation_pit.combined_association_content_id
    assert features.values_content_id == observation_feature_values_content_id(result.observation_features)


@pytest.mark.parametrize("field,value", [
    ("combined_association_content_id", "0" * 64), ("observation_association_content_id", "0" * 64),
    ("sample_binding_content_id", "0" * 64), ("bar_association_content_id", "0" * 64),
    ("decisions", ()), ("evidence", ()), ("sample_bindings", ()), ("bindings", ()),
])
def test_a3_top_level_recorded_tamper(tmp_path, field, value):
    result, data = prepared(tmp_path)
    record = change(data.sidecar("observation_pit.json")[1][0], **{field: value})
    with pytest.raises((MultiSourceCrossDayArtifactError, ValueError)):
        validate(result, data, record=record)


def test_duplicate_identical_observation_proof_rejected(tmp_path):
    result, data = prepared(tmp_path)
    evidence = data.sidecar("observation_evidence.json")[1]
    with pytest.raises(MultiSourceCrossDayArtifactError, match="duplicate complete"):
        validate(result, data, evidence=evidence + evidence)


@pytest.mark.parametrize("field,value", [
    ("implementation_pins", ()), ("feature_spec_pins", ()), ("samples", ()),
    ("execution_contract_version", "wrong"),
])
def test_observation_feature_projection_tamper(tmp_path, field, value):
    result, data = prepared(tmp_path)
    sidecars = tuple((p, k, (change(rs[0], **{field: value}),) if p == "observation_features.json" else rs)
                     for p, k, rs in data.sidecars)
    with pytest.raises(MultiSourceCrossDayArtifactError):
        validate(result, replace(data, sidecars=sidecars))
