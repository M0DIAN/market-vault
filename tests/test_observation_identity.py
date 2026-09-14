"""Deterministic A1 identities and no-I/O boundary, with offline fixtures."""

import ast
import builtins
from dataclasses import fields, replace
from datetime import timedelta, timezone
import inspect
from pathlib import Path
import socket
import time

import pandas as pd
import pytest

import market_vault.observation as api
from market_vault.observation import (
    ObservationContractPin, ObservationDimension, ObservationError,
    ObservationSnapshotMember, ObservationValueSchema,
    observation_build_id, observation_content_id, observation_coverage_id,
    observation_key, observation_source_content_id, observation_source_snapshot_id,
    observation_value_schema_id, observation_version_id,
)
from test_observation_models import (
    H, T, sample_build, sample_coverage, sample_observation, sample_snapshot,
)


def key_args(row):
    return {name: getattr(row, name) for name in (
        "provider_id", "source_kind", "entity_id", "observation_name", "dimensions",
        "event_time", "event_period_start",
    )}


def test_version_domains_are_explicit_and_separate():
    expected = {
        "OBSERVATION_SCHEMA_VERSION": "observation-schema-v1",
        "OBSERVATION_VALUE_SCHEMA_ID_VERSION": "observation-value-schema-v1",
        "OBSERVATION_KEY_VERSION": "observation-key-v1",
        "OBSERVATION_VERSION_ID_VERSION": "observation-version-v1",
        "OBSERVATION_SOURCE_SNAPSHOT_ID_VERSION": "observation-source-snapshot-v1",
        "OBSERVATION_SOURCE_CONTENT_ID_VERSION": "observation-source-content-v1",
        "OBSERVATION_COVERAGE_ID_VERSION": "observation-coverage-v1",
        "OBSERVATION_CONTENT_ID_VERSION": "observation-content-v1",
        "OBSERVATION_BUILD_ID_VERSION": "observation-build-v1",
    }
    assert {name: getattr(api, name) for name in expected} == expected
    assert len(set(expected.values())) == len(expected)
    assert api.OBSERVATION_NUMERIC_TYPES == ("int64", "float64")
    assert api.OBSERVATION_VALUE_STATUSES == ("VALUE", "NOT_REPORTED", "WITHDRAWN")


def test_frozen_a1_identity_vectors():
    row = sample_observation()
    members = (ObservationSnapshotMember("b/page.csv", 0, H[0]),
               ObservationSnapshotMember("a.csv", 5, H[1]))
    actual = {
        "schema": observation_value_schema_id(row.value_schema),
        "key": observation_key(**key_args(row)),
        "version": observation_version_id(row),
        "snapshot": observation_source_snapshot_id(sample_snapshot()),
        "inventory": observation_source_content_id(members),
        "coverage": observation_coverage_id(sample_coverage()),
        "content": observation_content_id((row,)),
        "empty_content": observation_content_id(()),
        "build": observation_build_id(sample_build()),
        "empty_build": observation_build_id(sample_build(rows=())),
    }
    assert actual == {
        "schema": "2fbe85ba4a7c62435f693a63e8510ff6a82eb1b18347a14073c580655f4949ed",
        "key": "0c4230091cbe455bce6d0666186644458ac26042ab7fdc337ebf46de35adf3f3",
        "version": "97760a2a18cda9b8a6df3a123de5c1784cda3a988e87aa7a5e1adf87f85d63ed",
        "snapshot": "2ba9324130b34ae0896e2c613caf5c9484ab8649a8ec4d9d47229e05cb2fde99",
        "inventory": "860bb7c9b0fdd0767df781a0d84dcc69045be1586e90515fdc85c60b2bc3f904",
        "coverage": "704ab1311d1ac513cf3029840d184d4517d6039a375d16a9c1a14d5e279ab539",
        "content": "34d0de2c267fe362f7cb9a517635032fdf585a121adce8206b5e121c59ada126",
        "empty_content": "8926a17316665ade720a1c7c7ea90909807e9f0877f9e9b56e5326807f8b1d03",
        "build": "6ab4f55f59c3453e5e5f116bbc10cf9ff314de5dc86d623ae08fdbd41df9612a",
        "empty_build": "2da668cd6235bd46b84523ef3d576ffbe9320cd7cb86e37866b28d9f401fbdef",
    }
    assert len(set(actual.values())) == len(actual)


def test_timezone_and_microsecond_normalization():
    row = sample_observation(event_period_start=T-timedelta(days=1))
    offset = timezone(timedelta(hours=9))
    equivalent = replace(row, **{
        name: getattr(row, name).astimezone(offset)
        for name in ("event_time", "event_period_start", "known_at", "archive_available_at")
    })
    assert equivalent == row
    assert equivalent.observation_key == row.observation_key
    assert equivalent.observation_version_id == row.observation_version_id
    assert equivalent.event_time.utcoffset() == timedelta(0)
    # The established scalar codec truncates sub-microsecond precision.
    nanos = replace(row, event_time=pd.Timestamp(row.event_time)+pd.Timedelta(999, "ns"))
    assert nanos == row
    shifted = replace(row, event_time=row.event_time+timedelta(microseconds=1))
    assert shifted.observation_key != row.observation_key
    snapshot = sample_snapshot()
    assert observation_source_snapshot_id(snapshot) == observation_source_snapshot_id(
        replace(snapshot, completed_possession_at=snapshot.completed_possession_at.astimezone(offset))
    )
    coverage = sample_coverage()
    assert observation_coverage_id(coverage) == observation_coverage_id(replace(coverage, **{
        name: getattr(coverage, name).astimezone(offset)
        for name in ("effective_start", "effective_end", "knowledge_start", "knowledge_end")
    }))


def test_nfc_dimensions_and_negative_zero_normalize_without_case_folding():
    row = sample_observation(entity_id="fixture:caf\u00e9")
    equivalent = replace(row, entity_id="fixture:cafe\u0301", dimensions=list(reversed(row.dimensions)))
    assert equivalent == row
    assert replace(row, entity_id="fixture:CAF\u00c9").observation_key != row.observation_key
    zero = sample_observation(values=(0.0, 0))
    assert replace(zero, values=(-0.0, 0)).observation_version_id == zero.observation_version_id
    float_zero = ObservationDimension("offset", "float64", 0.0)
    assert float_zero == ObservationDimension("offset", "float64", -0.0)
    integer = replace(row, dimensions=(ObservationDimension("x", "int64", 1),))
    string = replace(row, dimensions=(ObservationDimension("x", "string", "1"),))
    floating = replace(row, dimensions=(ObservationDimension("x", "float64", 1.0),))
    assert len({integer.observation_key, string.observation_key, floating.observation_key}) == 3


def test_nfc_value_schema_equivalence():
    field = sample_observation().value_schema.fields[0]
    composed = replace(field, name="caf\u00e9", unit="unit:\u00e9", representation="scale:\u00e9")
    decomposed = replace(field, name="cafe\u0301", unit="unit:e\u0301", representation="scale:e\u0301")
    assert observation_value_schema_id(ObservationValueSchema((composed,))) == observation_value_schema_id(
        ObservationValueSchema((decomposed,))
    )


@pytest.mark.parametrize("change", [
    dict(provider_id="other-provider"), dict(source_kind="other-source"),
    dict(entity_id="fixture:other"), dict(observation_name="other-measure"),
    dict(event_time=T+timedelta(microseconds=1)),
    dict(event_period_start=T-timedelta(days=1)),
    dict(dimensions=(ObservationDimension("tenor", "string", "5Y"),)),
])
def test_each_logical_coordinate_changes_key(change):
    row = sample_observation()
    changed = replace(row, **change)
    assert changed.observation_key != row.observation_key
    assert changed.observation_version_id != row.observation_version_id
    assert observation_key(**key_args(changed)) == changed.observation_key


@pytest.mark.parametrize("change", [
    dict(values=(4.5, 12)), dict(values=(4.25, 13)),
    dict(known_at=T+timedelta(hours=1, microseconds=1)),
    dict(known_at_authority_id=H[15]),
    dict(archive_available_at=T+timedelta(hours=2, microseconds=1)),
    dict(source_snapshot_id=H[15]), dict(source_content_sha256=H[15]),
    dict(provider_contract_version="fixture-contract-v2"),
    dict(provider_contract_content_id=H[15]),
    dict(normalization_version="fixture-normalizer-v2"),
    dict(normalization_content_id=H[15]), dict(revision_id="corrected-1"),
    dict(supersedes_revision_id="predecessor-0"),
    dict(value_status="WITHDRAWN", values=None),
    dict(value_status="NOT_REPORTED", values=None),
])
def test_version_only_facts_do_not_enter_logical_key(change):
    row = sample_observation()
    changed = replace(row, **change)
    assert changed.observation_key == row.observation_key
    assert changed.observation_version_id != row.observation_version_id
    assert observation_version_id(changed) == changed.observation_version_id


@pytest.mark.parametrize("change", [dict(name="renamed"), dict(logical_type="int64"),
                                    dict(unit="basis-points"), dict(representation="scaled-by-100")])
def test_schema_field_semantics_change_schema_id(change):
    row = sample_observation()
    new = replace(row.value_schema, fields=(replace(row.value_schema.fields[0], **change),
                                            row.value_schema.fields[1]))
    assert observation_value_schema_id(new) != row.value_schema_id
    values = (4, 12) if change.get("logical_type") == "int64" else row.values
    changed = replace(row, value_schema=new, values=values)
    assert changed.observation_key == row.observation_key
    assert changed.observation_version_id != row.observation_version_id


def test_schema_field_order_and_value_order_are_authoritative():
    row = sample_observation()
    reordered = replace(row, value_schema=ObservationValueSchema(tuple(reversed(row.value_schema.fields))),
                        values=tuple(reversed(row.values)))
    assert reordered.value_schema_id != row.value_schema_id
    assert reordered.observation_version_id != row.observation_version_id
    assert reordered.observation_key == row.observation_key
    a = replace(row.value_schema.fields[0], name="a")
    b = replace(a, name="b")
    row = replace(row, value_schema=ObservationValueSchema((a, b)), values=(1.0, 2.0))
    assert replace(row, values=(2.0, 1.0)).observation_version_id != row.observation_version_id


@pytest.mark.parametrize("change", [
    dict(provider_id="other"), dict(source_kind="other"),
    dict(provider_contract=ObservationContractPin("fixture-contract-v2", H[0])),
    dict(provider_contract=ObservationContractPin("fixture-contract-v1", H[15])),
    dict(normalized_request_id=H[15]), dict(source_content_sha256=H[15]),
    dict(acquisition_receipt_id="receipt-2"), dict(acquisition_receipt_content_id=H[15]),
    dict(completed_possession_at=T+timedelta(hours=3)),
])
def test_snapshot_binds_every_acquisition_fact(change):
    assert observation_source_snapshot_id(sample_snapshot()) != observation_source_snapshot_id(sample_snapshot(**change))


def test_recapture_is_not_revision_chronology():
    row = sample_observation()
    later = sample_snapshot(acquisition_receipt_id="receipt-2", completed_possession_at=T+timedelta(days=1))
    recaptured = replace(row, source_snapshot_id=observation_source_snapshot_id(later),
                         archive_available_at=later.completed_possession_at)
    assert recaptured.revision_id == row.revision_id
    assert recaptured.observation_key == row.observation_key
    assert recaptured.observation_version_id != row.observation_version_id


@pytest.mark.parametrize("name", ["relative_name", "byte_size", "sha256"])
def test_inventory_fields_bound(name):
    member = ObservationSnapshotMember("one.csv", 12, H[0])
    changes = {"relative_name": "two.csv", "byte_size": 13, "sha256": H[1]}
    changed = replace(member, **{name: changes[name]})
    assert observation_source_content_id((member,)) != observation_source_content_id((changed,))


@pytest.mark.parametrize("change", [
    dict(effective_start=T-timedelta(days=2)), dict(effective_end=T+timedelta(days=3)),
    dict(knowledge_start=T-timedelta(days=2)), dict(knowledge_end=T+timedelta(days=4)),
    dict(normalized_request_id=H[15]), dict(request_completion_evidence_id=H[15]),
    dict(request_pages_complete=False), dict(missing_semantics="other-missing-semantics"),
    dict(missing_semantics_content_id=H[15]), dict(revision_inventory_content_id=H[15]),
    dict(revision_inventory_complete=False),
    dict(provider_contract=ObservationContractPin("other-contract", H[15])),
])
def test_coverage_binds_all_claims_and_authorities(change):
    assert observation_coverage_id(sample_coverage()) != observation_coverage_id(sample_coverage(**change))


@pytest.mark.parametrize("field", ["provider_id", "source_kind", "entity_id", "observation_name"])
def test_coverage_scope_bound(field):
    coverage = sample_coverage()
    changed = replace(coverage, scope=replace(coverage.scope, **{field: "other"}))
    assert observation_coverage_id(coverage) != observation_coverage_id(changed)


def test_coverage_dimension_scope_and_empty_build_evidence_are_bound():
    coverage = sample_coverage()
    changed = replace(coverage, scope=replace(coverage.scope, dimensions=()))
    assert observation_coverage_id(coverage) != observation_coverage_id(changed)
    empty = sample_build(rows=())
    changed = replace(empty, authority_evidence_ids=empty.authority_evidence_ids+(H[15],))
    assert observation_build_id(empty) != observation_build_id(changed)
    assert observation_build_id(empty) != observation_build_id(replace(
        empty, coverage=replace(coverage, request_pages_complete=False),
    ))


def test_build_order_independence_and_complete_pin_binding():
    row = sample_observation()
    later = replace(row, event_time=T+timedelta(days=1), values=(4.5, 14))
    base = sample_build(rows=(row, later), source_snapshot_ids=(row.source_snapshot_id, H[15]),
                        authority_evidence_ids=(H[4], H[6], H[7], H[8], H[15]),
                        provider_contracts=(ObservationContractPin("unused", H[15]),
                                            ObservationContractPin(row.provider_contract_version, H[0])),
                        normalizations=(ObservationContractPin("unused", H[15]),
                                        ObservationContractPin(row.normalization_version, H[5])))
    reversed_input = replace(base, **{name: tuple(reversed(getattr(base, name))) for name in (
        "rows", "source_snapshot_ids", "authority_evidence_ids", "provider_contracts", "normalizations",
    )})
    assert observation_content_id((row, later)) == observation_content_id((later, row))
    assert observation_build_id(reversed_input) == observation_build_id(base)
    for change in [dict(rows=(row,)), dict(source_snapshot_ids=(row.source_snapshot_id,)),
                   dict(authority_evidence_ids=(H[4], H[6], H[7], H[8])),
                   dict(provider_contracts=(ObservationContractPin(row.provider_contract_version, H[0]),)),
                   dict(normalizations=(ObservationContractPin(row.normalization_version, H[5]),)),
                   dict(coverage=replace(base.coverage, revision_inventory_complete=False))]:
        assert observation_build_id(replace(base, **change)) != observation_build_id(base)
    assert base.rows == tuple(sorted(base.rows, key=lambda r: (r.observation_key, r.observation_version_id)))
    assert observation_content_id((row, row)) == observation_content_id((row,))


def test_location_is_not_a_model_or_identity_input():
    # External descriptive envelopes can relocate; no locator is passed to A1.
    row = sample_observation()
    relocated = [dict(location="D:/old/file", row=row),
                 dict(location="https://invalid.test/new", row=replace(row))]
    assert observation_content_id((relocated[0]["row"],)) == observation_content_id((relocated[1]["row"],))
    forbidden = {"source_locator", "path", "url", "output_path", "built_at"}
    for cls in (api.Observation, api.ObservationSourceSnapshotInput, api.ObservationBuildIdentityInput):
        assert not forbidden.intersection(field.name for field in fields(cls))
    assert not forbidden.intersection(inspect.signature(observation_key).parameters)


@pytest.mark.parametrize("function", [observation_value_schema_id, observation_version_id,
                                     observation_source_snapshot_id, observation_source_content_id,
                                     observation_coverage_id, observation_content_id, observation_build_id])
def test_wrong_identity_input_type_fails(function):
    for bad in (None, {}, "latest", 123):
        with pytest.raises(ObservationError):
            function(bad)


def test_semantic_operations_are_in_memory(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("semantic operation attempted I/O or current-time access")

    expected = observation_build_id(sample_build())
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        for method in ("open", "read_bytes", "read_text", "write_bytes", "write_text", "resolve", "stat", "mkdir"):
            patch.setattr(Path, method, forbidden)
        patch.setattr(socket, "socket", forbidden)
        patch.setattr(socket, "create_connection", forbidden)
        patch.setattr(time, "time", forbidden)
        assert observation_build_id(sample_build()) == expected
        assert observation_source_snapshot_id(sample_snapshot())
        assert observation_coverage_id(sample_coverage())


def test_a1_semantic_source_boundary_has_no_reader_provider_or_selection_engine():
    root = Path(api.__file__).parent
    allowed_imports = {"__future__", "dataclasses", "datetime", "math", "re", "unicodedata",
                       "dataset.encoding", "_validation", "models", "schema", "identity"}
    forbidden_calls = {"open", "now", "utcnow", "today", "stat", "resolve", "read_bytes",
                       "write_bytes", "getenv", "getcwd", "urlopen", "connect", "read_parquet",
                       "load_verified_observation_build", "assemble_point_in_time_samples"}
    # A2 adds physical authority and package exports, not I/O to A1 semantics.
    modules = [root / name for name in ("_validation.py", "models.py", "schema.py", "identity.py")]
    for module in modules:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module in allowed_imports
            if isinstance(node, ast.Import):
                assert {a.name for a in node.names}.issubset(allowed_imports)
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                assert name not in forbidden_calls
    assert not any("select" in name or "provider" in name for name in api.__all__)
