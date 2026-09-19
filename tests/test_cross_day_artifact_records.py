"""Closed sidecar field/type tables and detached recorded-only projections."""

from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timezone
from struct import pack

import pytest

from cross_day_dataset_helpers import fixture
from market_vault.cross_day_dataset import execution
from market_vault.cross_day_dataset import _artifact_records as records
from market_vault.cross_day_dataset._artifact_encoding import canonical_json, decode_json
from market_vault.cross_day_dataset.artifact_models import MultiSourceCrossDayArtifactError


def nodes(value):
    if type(value) is tuple:
        yield value
        for child in value:
            yield from nodes(child)


@pytest.mark.parametrize("case", ["A", "B", "C", "D", "E", "F", "G", "H_considered", "H_backing"])
def test_all_fixture_recorded_projections_round_trip(tmp_path, case):
    result = execution.join_multi_source_cross_day_dataset(**fixture(tmp_path, case))
    facts = execution._require_live_issued_multi_source_cross_day_dataset_artifact_facts(result)
    seen = set()
    for node in nodes(facts.snapshot):
        if (len(node) != 3 or type(node[0]) is not str or type(node[1]) is not str
                or node[1] not in records._SOURCE_MODULES):
            continue
        kind = node[1]
        projected = records._snapshot_projection(node, kind)
        assert type(projected) is records._Recorded
        assert not type(projected).__module__.startswith("market_vault.ts2_feature")
        data = records._fact_bytes(kind, (projected,))
        loaded, = records._read_facts(kind, data, singleton=True)
        assert records._fact_bytes(kind, (loaded,)) == data
        def no_class_tags(value):
            if type(value) is dict:
                assert not {"__class__", "__module__", "_schema_name", "_items"} & value.keys()
                for child in value.values():
                    no_class_tags(child)
            elif type(value) is list:
                for child in value:
                    no_class_tags(child)
        no_class_tags(decode_json(data))
        assert b"snapshot_file" not in data
        assert b"manifest_payload" not in data
        assert b"build_path" not in data
        seen.add(kind)
    assert {"PITAssemblyResult", "TS2FeatureExecutionResult", "ObservationPITAssemblyResult",
            "ObservationFeatureExecutionResult", "VerifiedTradingDaySchedule", "ChronologicalSplitResult"} <= seen


def test_literal_tables_match_frozen_declared_fields():
    for cls, names in execution._live._FIELDS.items():
        kind = cls.__name__
        if kind not in records._SOURCE_MODULES:
            continue
        assert records._SOURCE_MODULES[kind] == cls.__module__
        assert {name for name, _ in records._SCHEMAS[kind]} == set(names) - set(records._OMITTED.get(kind, ()))
        assert set(names) == {field.name for field in fields(cls)}
    assert len(records._SCHEMAS["MultiSourceCrossDaySampleAudit"]) == 32


def test_all_schema_references_are_closed():
    primitives = {"date", "datetime", "str", "bool", "int", "float", "number", "dimension", "parameter"}

    def check(shape):
        if shape[0] in "?*":
            check(shape[1:])
        elif shape.startswith("("):
            for child in shape[1:-1].split(","):
                check(child)
        else:
            assert shape in primitives or shape in records._SCHEMAS

    for schema in records._SCHEMAS.values():
        assert len({name for name, _ in schema}) == len(schema)
        for _, shape in schema:
            check(shape)


@pytest.mark.parametrize("payload", [
    {"name": "x", "logical_type": "float64"},
    {"name": "x", "logical_type": "float64", "nullable": False, "future": 1},
    {"name": "x", "logical_type": "float64", "nullable": 0},
    {"name": 1, "logical_type": "float64", "nullable": False},
])
def test_unknown_missing_and_wrong_exact_types_rejected(payload):
    with pytest.raises(MultiSourceCrossDayArtifactError):
        records._decode_record("DatasetField", payload)


def test_private_record_immutable_and_kind_field_not_shadowed():
    record = records._decode_record("SpecPin", dict(kind="FEATURE", name="x", version="v1", content_sha256="0" * 64))
    assert record.kind == "FEATURE"
    with pytest.raises(FrozenInstanceError):
        record._items = ()
    with pytest.raises(AttributeError):
        record.arbitrary


@pytest.mark.parametrize("value,shape", [(True, "int"), (1, "bool"), (1, "float"), (False, "number"),
                                         (1.0, "int"), (float("inf"), "number")])
def test_no_numeric_coercion(value, shape):
    with pytest.raises(MultiSourceCrossDayArtifactError):
        records._typed(value, shape, decoding=True)


def test_float_bits_and_date_types_survive_projection():
    negative = records._snapshot_scalar(("float64", pack("!d", -0.0)))
    assert pack("!d", negative) == pack("!d", -0.0)
    stamp = records._snapshot_scalar(("datetime", (2025, 3, 3, 14, 30, 0, 123456, 0, ("pytz-utc",))))
    assert type(stamp) is datetime
    assert stamp == datetime(2025, 3, 3, 14, 30, 0, 123456, tzinfo=timezone.utc)
    with pytest.raises(MultiSourceCrossDayArtifactError):
        records._snapshot_scalar(("timestamp", (2025, 3, 3, 14, 30, 0, 0, 0, ("pytz-utc",)), 1))


def test_no_upstream_result_construction_or_dynamic_dispatch():
    # Codec's record type cannot be mistaken for any upstream live issuance.
    record = records._decode_record("DatasetField", dict(name="x", logical_type="float64", nullable=False))
    assert type(record) is records._Recorded
    with pytest.raises(MultiSourceCrossDayArtifactError):
        records._decode_record("arbitrary.module.Class", {})
    with pytest.raises(MultiSourceCrossDayArtifactError):
        records._snapshot_projection(("arbitrary.module", "DatasetField", ()), "DatasetField")


def test_sidecar_closed_envelope_and_singleton():
    for payload in (
            {"artifact_version": "wrong", "records": []},
            {"artifact_version": records.SERIALIZATION_FORMAT_VERSION, "records": [], "extra": 0},
            {"artifact_version": records.SERIALIZATION_FORMAT_VERSION, "records": {}},
            {"artifact_version": records.SERIALIZATION_FORMAT_VERSION, "records": []}):
        with pytest.raises(MultiSourceCrossDayArtifactError):
            records._read_facts("DatasetField", canonical_json(payload), singleton=True)
