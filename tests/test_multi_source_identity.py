"""Literal design 12.3/12.4 encodings, separate from verified admission."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from market_vault.dataset.content import dataset_schema_id, logical_dataset_content_id
from market_vault.dataset.encoding import encode_identity
from market_vault.dataset.identity import _implementation_digest, _spec_digest
from market_vault.dataset.models import DatasetField, DatasetSchema
from market_vault.observation.models import ObservationCoverage, ObservationScope, ObservationContractPin
from market_vault.observation.identity import observation_coverage_id
from market_vault.observation.pit_models import ObservationSnapshotPin, ObservationBuildPin, ObservationDecisionEvidence
from market_vault.observation.pit_identity import observation_build_pin_id, combined_association_content_id, feature_spec_pin_id
from market_vault.multi_source import observation_feature_spec_pin, sample_audit_content_id
from market_vault.multi_source._evidence import (
    observation_proof_pair_id, observation_evidence_item_id, observation_evidence_content_id,
)
from market_vault.multi_source._orchestration_validation import MultiSourceDatasetError, flatten
from market_vault.multi_source.identity import MULTI_SOURCE_DATASET_ID_VERSION, _VERSIONS
from test_multi_source_feature_specs import vector_spec
from test_multi_source_feature_identity import fixture_value, COMPLETE_CONTENT

Z, O, P, Q = (str(n) * 64 for n in range(4))
U = datetime(2026, 1, 2, tzinfo=timezone.utc)


def evidence_vector():
    source = vector_spec().source_spec
    coverage = ObservationCoverage(ObservationScope("offline", "series", "US", "rate", source.dimensions),
        ObservationContractPin("v1", O), U, U, U, U, Z, P, True, "EXPLICIT_EMPTY", Q, O, True)
    snapshot = ObservationSnapshotPin(Z, O, "offline", "series", "v1", O, Z, "receipt-1", P, U)
    pin = ObservationBuildPin(Z, O, "observation-schema-v1", observation_coverage_id(coverage), U, "EMPTY", (Q,),
        (ObservationContractPin("v1", O),), (ObservationContractPin("v1", P),), (snapshot,), ())
    return ObservationDecisionEvidence(Z, feature_spec_pin_id(observation_feature_spec_pin(vector_spec())), (pin,), (coverage,))


def matrix_vector():
    columns = (("code", "string", False), ("sample_key", "string", False), ("sample_version_id", "string", False),
        ("feature_window_close", "timestamp_us_utc", False), ("actual_label_end_time", "timestamp_us_utc", True),
        ("label_status", "string", False), ("bar_return", "float64", False), ("obs_rate", "float64", False),
        ("label_return", "float64", True), ("feature_window_close_date", "date32", False),
        ("nominal_split", "string", True), ("final_split", "string", True), ("assignment_status", "string", False),
        ("reason_code", "string", True), ("purge_boundary", "timestamp_us_utc", True))
    schema = DatasetSchema(tuple(DatasetField(*c) for c in columns))
    row = ("US.TEST", Z, O, U, None, "INCOMPLETE", 0.5, 1.25, None, U.date(), "TRAIN", None, "EXCLUDED", "INCOMPLETE_LABEL", None)
    return schema, (dict(zip((f.name for f in schema.fields), row)),)


def encoder_payload():
    evidence, value = evidence_vector(), fixture_value()
    schema, rows = matrix_vector()
    return dict(_VERSIONS, dataset_kind="SUPERVISED", scope=Z, dataset_as_of=None,
        dataset_schema_id=dataset_schema_id(schema), logical_dataset_content_id=logical_dataset_content_id(schema, rows),
        canonical_builds=O, canonical_row_version_ids=P, bar_feature_specs=Q,
        observation_feature_specs=_spec_digest(value.spec_pin), label_specs=Z, split_spec=O,
        implementations=_implementation_digest(value.implementation_pin), completion=P, gap_references="",
        bar_association_schema_id=O, bar_association_content_id=Z, observation_association_content_id=P,
        sample_binding_content_id=Q, combined_association_content_id=combined_association_content_id(Z, O, P, Q),
        observation_evidence_content_id=observation_evidence_content_id((evidence,)),
        observation_build_pin_ids=observation_build_pin_id(evidence.build_pins[0]),
        observation_coverage_ids=observation_coverage_id(evidence.coverages[0]),
        observation_feature_values_content_id=COMPLETE_CONTENT, sample_audit_content_id=sample_audit_content_id(()))


def vector_results():
    item = evidence_vector()
    schema, rows = matrix_vector()
    return {
        "pair": observation_proof_pair_id(item.build_pins[0], item.coverages[0]),
        "item": observation_evidence_item_id(item),
        "evidence": observation_evidence_content_id((item,)),
        "empty_evidence": observation_evidence_content_id(()),
        "two_items": observation_evidence_content_id((replace(item, sample_key=O), item)),
        "combined": combined_association_content_id(Z, O, P, Q),
        "empty_audit": sample_audit_content_id(()),
        "schema": dataset_schema_id(schema),
        "content": logical_dataset_content_id(schema, rows),
        "empty_content": logical_dataset_content_id(schema, ()),
        "dataset": encode_identity(MULTI_SOURCE_DATASET_ID_VERSION, encoder_payload()),
    }


EXPECTED = {
    "pair": "3cba0f81871304c300eb1e50bd96e6736623886039dd46e1f5575c27cbba7435",
    "item": "07f95bce59e4116aa954d8f00af753ec3b54b6182d265f4eff30ab79db253bad",
    "evidence": "e95ea941bc105ff7639880a934202e196f9aace9fc81f4ae3634e6ddce4601c9",
    "empty_evidence": "69e8fce7307afc78b5f6b29faa76588613892b1a60d5bcc53e9ad4a6a25a7344",
    "two_items": "4fd06a934f381b1622848361d76efbd47da88bdc4c1b99f775b0d92317469435",
    "combined": "033e0354191090b361dba3a67532704af21a1f27d8bd807bfc603ec25f0fbf72",
    "empty_audit": "5a18ca976576c54556d424145176541b4480d1e5cb95315739f075d1465a276e",
    "schema": "8253f07ea6b6a6834b1fa17720c7027e4d440782ad5f1df10c51034759bc8370",
    "content": "755433cbcdda97a969f8029a1a80da1451e69c27c58fa6faffa24350d3e277b0",
    "empty_content": "7c67e831beb16a18826dae36bf0aa5542c603cf24232eaa33b7e2c89fec8a315",
    "dataset": "fb7957a655e79ed2347d4c7a5c357e3d33196b935ea68949127a127365874442",
}


def test_design_literal_vectors():
    assert vector_results() == EXPECTED


def test_evidence_order_and_pairing():
    item = evidence_vector()
    other = replace(item, sample_key=O)
    assert observation_evidence_content_id((other, item)) == observation_evidence_content_id((item, other))
    changed_coverage = replace(item.coverages[0], effective_end=U.replace(hour=1))
    with pytest.raises(MultiSourceDatasetError, match="pairing"):
        observation_evidence_content_id((replace(item, coverages=(changed_coverage,)),))
    with pytest.raises(MultiSourceDatasetError, match="duplicate"):
        observation_evidence_content_id((item, item))
    with pytest.raises(MultiSourceDatasetError, match="duplicate"):
        observation_evidence_content_id((replace(item, build_pins=item.build_pins*2, coverages=item.coverages*2),))


def test_same_logical_build_distinct_physical_proof_identity():
    item = evidence_vector()
    one = item.build_pins[0]
    two = replace(one, coverage_proof_available_at=U + timedelta(microseconds=1))
    assert one.observation_build_id == two.observation_build_id
    assert observation_build_pin_id(one) != observation_build_pin_id(two)
    assert observation_proof_pair_id(one, item.coverages[0]) != observation_proof_pair_id(two, item.coverages[0])
    pair = replace(item, build_pins=(one, two), coverages=item.coverages * 2)
    content = observation_evidence_content_id((pair,))
    assert content != observation_evidence_content_id((item,))
    assert content != observation_evidence_content_id((replace(item, build_pins=(two,)),))
    assert content == observation_evidence_content_id((replace(pair, build_pins=(two, one)),))
    for index in (0, 1):
        pins = list(pair.build_pins)
        pins[index] = replace(pins[index], coverage_proof_available_at=U + timedelta(microseconds=2))
        assert content != observation_evidence_content_id((replace(pair, build_pins=tuple(pins)),))
    with pytest.raises(MultiSourceDatasetError, match="duplicate Observation proof pair"):
        observation_evidence_content_id((replace(pair, build_pins=(one, two, two), coverages=item.coverages * 3),))


def test_flatten_typed_and_empty_records():
    assert flatten("samples", ({"time": U, "empty": {}, "null": None, "values": (1, 1.0)},)) == {
        "samples.count": 1, "samples.0000.time": U, "samples.0000.empty.count": 0,
        "samples.0000.null": None, "samples.0000.values.count": 2,
        "samples.0000.values.0000": 1, "samples.0000.values.0001": 1.0}
    with pytest.raises(MultiSourceDatasetError):
        flatten("x", {"unsafe.key": 1})


@pytest.mark.parametrize("field", list(_VERSIONS))
def test_each_contract_version_is_identity_bearing(field):
    payload = encoder_payload()
    assert encode_identity(MULTI_SOURCE_DATASET_ID_VERSION, payload | {field: "future"}) != vector_results()["dataset"]
