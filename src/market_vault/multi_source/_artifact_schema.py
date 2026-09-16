"""Frozen five-table physical contract and exact scalar admission."""

from dataclasses import fields
from datetime import date, datetime
import math

import pyarrow as pa
import pyarrow.parquet as pq

from ..dataset.models import DatasetField, DatasetSchema
from ..dataset.pit import pit_association_schema
from ..observation.pit_models import ObservationPITDecision, ObservationSampleBinding
from ..observation.pit_identity import feature_spec_pin_id
from ._serialization import require
from .artifact_models import MULTI_SOURCE_DATASET_MATERIALIZER_VERSION, MULTI_SOURCE_DATASET_SERIALIZATION_FORMAT_VERSION
from .manifest import SPEC_ARTIFACT_VERSIONS

PARQUET_FILES = (
    ("dataset.parquet", "MATRIX", "logical_dataset_content_id", "CODE_FEATURE_CLOSE_SAMPLE_KEY"),
    ("associations/bar.parquet", "BAR_ASSOCIATION", "bar_association_content_id", "SAMPLE_ROLE_POSITION"),
    ("associations/observation.parquet", "OBSERVATION_ASSOCIATION", "observation_association_content_id", "SAMPLE_FEATURE_SPEC_PIN_ID"),
    ("associations/sample_bindings.parquet", "SAMPLE_BINDING", "sample_binding_content_id", "SAMPLE_KEY"),
    ("associations/observation_feature_values.parquet", "OBSERVATION_FEATURE_VALUES", "observation_feature_values_content_id", "SAMPLE_FEATURE_SPEC_PIN_ID"),
)
_TYPES = {"string": pa.string(), "int64": pa.int64(), "float64": pa.float64(), "bool": pa.bool_(),
          "date32": pa.date32(), "timestamp_us_utc": pa.timestamp("us", tz="UTC")}


def _schema(columns):
    return DatasetSchema(tuple(DatasetField(n, t, b) for n, t, b in columns))


def decision_schema():
    times = {"T", "A", "selected_event_time", "selected_known_at", "selected_archive_available_at"}
    return _schema(tuple((f.name, "timestamp_us_utc" if f.name in times else "bool" if f.name == "archive_limited"
        else "int64" if f.name.endswith("_count") else "string",
        f.name in ("A", "reason") or f.name.startswith("selected_")) for f in fields(ObservationPITDecision)))


def binding_schema():
    return _schema(tuple((f.name, "string", False) for f in fields(ObservationSampleBinding)))


def value_schema():
    strings = ("sample_key", "multi_source_sample_version_id", "feature_name", "feature_spec_pin_id",
        "implementation_name", "implementation_version", "implementation_content_sha256", "decision_id", "status", "output_logical_type")
    return _schema(tuple((n, "string", False) for n in strings) + (("value_int64", "int64", True),
        ("value_float64", "float64", True), ("reason_code", "string", True), ("consumed_observation_version_id", "string", True)))


def table_contracts(identity):
    schemas = (identity.schema, pit_association_schema(), decision_schema(), binding_schema(), value_schema())
    schema_ids = (identity.dataset_schema_id, identity.bar_association_schema_id, "observation-association-v1",
                  "observation-sample-binding-v1", "observation-feature-value-v1")
    return tuple((path, role, getattr(identity, content), order, schema, schema_id)
        for (path, role, content, order), schema, schema_id in zip(PARQUET_FILES, schemas, schema_ids))


def arrow_schema(dataset_id, contract):
    path, role, content_id, order, schema, schema_id = contract
    metadata = dict(multi_source_dataset_id=dataset_id, serialization_format_version=MULTI_SOURCE_DATASET_SERIALIZATION_FORMAT_VERSION,
        materializer_version=MULTI_SOURCE_DATASET_MATERIALIZER_VERSION, file_role=role, logical_schema_id=schema_id,
        logical_content_id=content_id, row_order=order)
    return pa.schema([pa.field(f.name, _TYPES[f.logical_type], nullable=f.nullable) for f in schema.fields],
                     metadata={("market_vault." + k).encode(): v.encode() for k, v in metadata.items()})


def exact_rows(rows, schema):
    for row in rows:
        require(set(row) == {f.name for f in schema.fields}, "row fields mismatch")
        for f in schema.fields:
            v = row[f.name]
            if v is None:
                require(f.nullable, "null in nonnullable column")
                continue
            kind = f.logical_type
            cls = {"string": str, "int64": int, "float64": float, "bool": bool, "date32": date, "timestamp_us_utc": datetime}[kind]
            require(isinstance(v, datetime) if cls is datetime else type(v) is cls, "physical scalar type mismatch: " + f.name)
            if kind == "int64":
                require(-(2**63) <= v < 2**63, "int64 overflow")
            if kind == "float64":
                require(math.isfinite(v), "nonfinite float")
            if kind == "timestamp_us_utc":
                require(v.tzinfo is not None and v.utcoffset().total_seconds() == 0 and not getattr(v, "nanosecond", 0),
                        "non-UTC or submicrosecond physical timestamp")


def parquet_bytes(dataset_id, contract, rows):
    exact_rows(rows, contract[4])
    table = pa.Table.from_pylist(list(rows), schema=arrow_schema(dataset_id, contract))
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, compression="zstd", use_dictionary=False, write_statistics=True,
        coerce_timestamps="us", allow_truncated_timestamps=False, version="2.6", data_page_version="2.0")
    return sink.getvalue().to_pybytes()


def parquet_rows(data, dataset_id, contract):
    table = pq.read_table(pa.BufferReader(data))
    require(table.schema.equals(arrow_schema(dataset_id, contract), check_metadata=True), "Parquet schema/nullability/metadata mismatch")
    rows = tuple(table.to_pylist())
    exact_rows(rows, contract[4])
    order = contract[3]
    key = {"CODE_FEATURE_CLOSE_SAMPLE_KEY": lambda r: (r["code"], r["feature_window_close"], r["sample_key"]),
        "SAMPLE_ROLE_POSITION": lambda r: (r["sample_key"], r["role"], r["position"]),
        "SAMPLE_FEATURE_SPEC_PIN_ID": lambda r: (r["sample_key"], r["feature_spec_pin_id"]),
        "SAMPLE_KEY": lambda r: r["sample_key"]}[order]
    keys = [key(r) for r in rows]
    require(keys == sorted(set(keys)), "duplicate or unordered physical rows")
    return rows


def physical_values(result, specs):
    types = {s.name: s.output.logical_type for s in specs}
    rows = []
    for sample in result.samples:
        for v in sample.values:
            t = types[v.feature_name]
            rows.append(dict(sample_key=v.sample_key, multi_source_sample_version_id=v.multi_source_sample_version_id,
                feature_name=v.feature_name, feature_spec_pin_id=feature_spec_pin_id(v.spec_pin),
                implementation_name=v.implementation_pin.name, implementation_version=v.implementation_pin.version,
                implementation_content_sha256=v.implementation_pin.content_sha256, decision_id=v.decision_id,
                status=v.status, output_logical_type=t, value_int64=v.value if t == "int64" else None,
                value_float64=v.value if t == "float64" else None, reason_code=v.reason_code,
                consumed_observation_version_id=v.consumed_observation_version_id))
    return tuple(sorted(rows, key=lambda r: (r["sample_key"], r["feature_spec_pin_id"])))


def output_contracts(identity):
    result = {p: (role, content, MULTI_SOURCE_DATASET_SERIALIZATION_FORMAT_VERSION, True)
              for p, role, content, *_ in table_contracts(identity)}
    result["associations/observation_evidence.json"] = ("OBSERVATION_EVIDENCE", identity.observation_evidence_content_id,
        "multi-source-observation-evidence-v1", False)
    for pins, prefix, role, version in ((identity.bar_feature_specs, "feature_specs/bar", "BAR_FEATURE_SPEC", "bar_feature"),
        (identity.observation_feature_specs, "feature_specs/observation", "OBSERVATION_FEATURE_SPEC", "observation_feature"),
        (identity.label_specs, "label_specs", "LABEL_SPEC", "label")):
        for pin in pins:
            result[prefix + "/" + pin.content_sha256 + ".yaml"] = (role, pin.content_sha256, SPEC_ARTIFACT_VERSIONS[version], False)
    result["split_spec.yaml"] = ("SPLIT_SPEC", identity.split_spec.content_sha256, SPEC_ARTIFACT_VERSIONS["split"], False)
    result["build_report.json"] = ("BUILD_REPORT", None, "multi-source-dataset-build-report-v1", False)
    return result
