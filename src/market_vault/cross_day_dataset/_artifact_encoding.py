"""Canonical fact bytes and exact matrix encoding, entirely in memory."""

from datetime import date, datetime, timezone
import json
import math

import pyarrow as pa
import pyarrow.parquet as pq

from ..dataset.encoding import DatasetError, reject_unsafe_text
from ..dataset.models import DatasetSchema
from .artifact_models import MultiSourceCrossDayArtifactError, _require


def _text(value):
    _require(type(value) is str, "ARTIFACT_DECODE", "exact string required")
    try:
        reject_unsafe_text(value, "artifact string")
        value.encode("utf-8", errors="strict")
    except (DatasetError, UnicodeError) as exc:
        raise MultiSourceCrossDayArtifactError("ARTIFACT_DECODE", "PREFLIGHT", exc) from exc
    return value


def _json_value(value):
    cls = type(value)
    if value is None or cls is bool:
        return
    if cls is str:
        _text(value)
    elif cls is int:
        _require(-(2**63) <= value <= 2**63 - 1, "ARTIFACT_DECODE", "integer outside int64")
    elif cls is float:
        _require(math.isfinite(value), "ARTIFACT_DECODE", "nonfinite JSON scalar")
    elif cls is list:
        for member in value:
            _json_value(member)
    elif cls is dict:
        for key, member in value.items():
            _text(key)
            _json_value(member)
    else:
        _require(False, "ARTIFACT_DECODE", "non-JSON declared value")


def canonical_json(value):
    _json_value(value)
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "ARTIFACT_DECODE", "duplicate JSON field")
        result[key] = value
    return result


def _constant(value):
    _require(False, "ARTIFACT_DECODE", "nonfinite JSON number")


def decode_json(data):
    _require(type(data) is bytes, "ARTIFACT_DECODE", "exact JSON bytes required")
    try:
        value = json.loads(data.decode("utf-8", errors="strict"),
                           object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise MultiSourceCrossDayArtifactError("ARTIFACT_DECODE", "PREFLIGHT", exc) from exc
    _require(canonical_json(value) == data, "ARTIFACT_DECODE", "noncanonical JSON bytes")
    return value


def exact_fields(value, names):
    _require(type(value) is dict and set(value) == set(names),
             "ARTIFACT_DECODE", "closed record field set differs")
    return value


def timestamp_text(value):
    _require(type(value) is datetime and value.tzinfo is not None
             and value.utcoffset() is not None, "ARTIFACT_DECODE", "aware datetime required")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def decode_timestamp(value):
    _text(value)
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise MultiSourceCrossDayArtifactError("ARTIFACT_DECODE", "PREFLIGHT", exc) from exc
    _require(timestamp_text(result) == value, "ARTIFACT_DECODE", "noncanonical UTC timestamp")
    return result


def decode_date(value):
    _text(value)
    try:
        result = date.fromisoformat(value)
    except ValueError as exc:
        raise MultiSourceCrossDayArtifactError("ARTIFACT_DECODE", "PREFLIGHT", exc) from exc
    _require(result.isoformat() == value, "ARTIFACT_DECODE", "noncanonical date")
    return result


def arrow_schema(schema):
    _require(type(schema) is DatasetSchema, "ARTIFACT_AUTHORITY", "exact declared schema required")
    types = {"string": pa.string(), "int64": pa.int64(), "float64": pa.float64(),
             "timestamp_us_utc": pa.timestamp("us", tz="UTC"), "date32": pa.date32()}
    _require(all(f.logical_type in types for f in schema.fields),
             "ARTIFACT_AUTHORITY", "unsupported matrix logical type")
    return pa.schema([pa.field(f.name, types[f.logical_type], nullable=f.nullable) for f in schema.fields])


def _matrix_scalar(field, value):
    if value is None:
        _require(field.nullable, "ARTIFACT_AUTHORITY", "null in nonnullable matrix field")
        return
    kind = field.logical_type
    valid = ((kind == "string" and type(value) is str)
             or (kind == "int64" and type(value) is int and -(2**63) <= value < 2**63)
             or (kind == "float64" and type(value) is float and math.isfinite(value))
             or (kind == "date32" and type(value) is date)
             or (kind == "timestamp_us_utc" and type(value) is datetime
                 and value.tzinfo is not None and value.utcoffset() == timezone.utc.utcoffset(value)))
    _require(valid, "ARTIFACT_AUTHORITY", "matrix scalar requires exact declared type")
    if kind == "string":
        _text(value)


def _matrix_rows(schema, rows):
    _require(type(rows) is tuple and all(type(r) is tuple and len(r) == len(schema.fields) for r in rows),
             "ARTIFACT_AUTHORITY", "exact immutable matrix row shape required")
    for row in rows:
        for field, value in zip(schema.fields, row):
            _matrix_scalar(field, value)


def parquet_bytes(schema, rows):
    physical_schema = arrow_schema(schema)
    _matrix_rows(schema, rows)
    try:
        arrays = [pa.array([r[i] for r in rows], type=field.type, from_pandas=False, safe=True)
                  for i, field in enumerate(physical_schema)]
        table = pa.Table.from_arrays(arrays, schema=physical_schema)
        sink = pa.BufferOutputStream()
        pq.write_table(table, sink, compression="zstd", version="2.6", data_page_version="1.0",
                       use_dictionary=False, write_statistics=True, row_group_size=65536)
        return sink.getvalue().to_pybytes()
    except (pa.ArrowException, OverflowError) as exc:
        raise MultiSourceCrossDayArtifactError("ARTIFACT_DECODE", "PREFLIGHT", exc) from exc


def decode_parquet(data, schema):
    _require(type(data) is bytes, "ARTIFACT_DECODE", "exact Parquet bytes required")
    expected = arrow_schema(schema)
    try:
        file = pq.ParquetFile(pa.BufferReader(data))
        _require(file.schema_arrow.equals(expected, check_metadata=True),
                 "ARTIFACT_AUTHORITY", "Parquet schema/metadata differs")
        _require(file.metadata.format_version == "2.6", "ARTIFACT_AUTHORITY", "Parquet format differs")
        for group in range(file.metadata.num_row_groups):
            meta = file.metadata.row_group(group)
            _require(meta.num_rows <= 65536, "ARTIFACT_AUTHORITY", "oversized row group")
            for index in range(meta.num_columns):
                column = meta.column(index)
                _require(column.compression == "ZSTD" and not column.has_dictionary_page,
                         "ARTIFACT_AUTHORITY", "Parquet physical encoding differs")
                _require(meta.num_rows == 0 or column.statistics is not None,
                         "ARTIFACT_AUTHORITY", "Parquet statistics absent")
        table = file.read()
        columns = [column.to_pylist() for column in table.columns]
        rows = tuple(tuple(column[i] for column in columns) for i in range(table.num_rows))
    except (pa.ArrowException, OverflowError) as exc:
        raise MultiSourceCrossDayArtifactError("ARTIFACT_DECODE", "PREFLIGHT", exc) from exc
    _matrix_rows(schema, rows)
    return rows
