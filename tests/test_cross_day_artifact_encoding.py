"""Physical encoding does not infer schema, coerce values, or add logical IDs."""

from datetime import date, datetime, timezone
import math

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from market_vault.cross_day_dataset._artifact_encoding import (
    canonical_json, decode_json, decode_timestamp, decode_date,
    parquet_bytes, decode_parquet, exact_fields,
)
from market_vault.cross_day_dataset.artifact_models import MultiSourceCrossDayArtifactError
from market_vault.dataset.models import DatasetField, DatasetSchema


SCHEMA = DatasetSchema(tuple(DatasetField(name, kind, nullable) for name, kind, nullable in (
    ("code", "string", False), ("n", "int64", False), ("v", "float64", True),
    ("t", "timestamp_us_utc", False), ("d", "date32", False))))
ROW = ("US.AAPL", 2, 0.25, datetime(2025, 1, 2, 15, tzinfo=timezone.utc), date(2025, 1, 2))


def test_json_exact_bytes_and_scalar_types():
    data = canonical_json({"z": [True, 1, 1.0, -0.0, None], "a": "\u65e5"})
    assert data == b'{"a":"\\u65e5","z":[true,1,1.0,-0.0,null]}\n'
    actual = decode_json(data)["z"]
    assert tuple(type(x) for x in actual) == (bool, int, float, float, type(None))
    assert math.copysign(1, actual[3]) == -1


@pytest.mark.parametrize("data", [b'{"a":1,"a":1}\n', b'{}', b'{}\r\n', b'{ "a":1}\n',
    b'\xef\xbb\xbf{}\n', b'"\xff"\n', b'NaN\n', b'Infinity\n', b'1e999\n',
    b'"\\u0000"\n', b'"\\ud800"\n', b'9223372036854775808\n'])
def test_noncanonical_json_rejected(data):
    with pytest.raises(MultiSourceCrossDayArtifactError):
        decode_json(data)


@pytest.mark.parametrize("value", [(1,), {1: "a"}, float("nan"), float("inf"), b"x", object()])
def test_no_general_object_serialization(value):
    with pytest.raises(MultiSourceCrossDayArtifactError):
        canonical_json(value)


def test_closed_fields_and_typed_clock_decoding():
    assert exact_fields({"a": 1}, ("a",)) == {"a": 1}
    for value in ({}, {"a": 1, "extra": 2}, []):
        with pytest.raises(MultiSourceCrossDayArtifactError):
            exact_fields(value, ("a",))
    assert decode_timestamp("2025-01-02T15:00:00.000000Z") == ROW[3]
    assert decode_date("2025-01-02") == ROW[4]
    for value in ("2025-01-02T15:00:00Z", "2025-01-02T15:00:00.000000+00:00", "2025-01-02"):
        with pytest.raises(MultiSourceCrossDayArtifactError):
            decode_timestamp(value)


@pytest.mark.parametrize("rows", [(), (ROW,), (ROW, ("US.AAPL", 3, None, ROW[3], ROW[4]))])
def test_parquet_exact_roundtrip_including_empty(rows):
    data = parquet_bytes(SCHEMA, rows)
    assert decode_parquet(data, SCHEMA) == rows
    file = pq.ParquetFile(pa.BufferReader(data))
    assert file.schema_arrow.metadata is None
    assert file.metadata.num_rows == len(rows)
    assert all(field.metadata is None for field in file.schema_arrow)


@pytest.mark.parametrize("index,value", [(0, b"US.AAPL"), (1, True), (1, 2.0), (1, 2**63),
    (2, 1), (2, True), (2, float("nan")), (3, datetime(2025, 1, 2)), (4, ROW[3]), (0, None)])
def test_matrix_has_no_numeric_date_or_null_coercion(index, value):
    row = list(ROW)
    row[index] = value
    with pytest.raises(MultiSourceCrossDayArtifactError):
        parquet_bytes(SCHEMA, (tuple(row),))


def test_reader_rejects_metadata_schema_and_dictionary_changes():
    data = parquet_bytes(SCHEMA, (ROW,))
    table = pq.read_table(pa.BufferReader(data))
    for changed in (table.replace_schema_metadata({b"pandas": b"{}"}), table):
        sink = pa.BufferOutputStream()
        pq.write_table(changed, sink, compression="zstd", use_dictionary=True)
        with pytest.raises(MultiSourceCrossDayArtifactError):
            decode_parquet(sink.getvalue().to_pybytes(), SCHEMA)
