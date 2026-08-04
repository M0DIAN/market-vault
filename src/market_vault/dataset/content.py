"""Deterministic logical schema and content identities for derived datasets.

``dataset_schema_id`` is a versioned SHA-256 over the authoritative field
order, logical types, and nullability flags. ``logical_dataset_content_id`` is
a versioned SHA-256 over the schema ID and every logical row encoded under
that exact schema, with row multiplicity preserved but row order irrelevant.

This describes logical content only: cross-version byte-identical Parquet
output is not promised or claimed.
"""

from __future__ import annotations

import hashlib
import numbers
from datetime import date, datetime
from typing import Mapping

import pandas as pd

from .encoding import DatasetError, encode_identity, encode_scalar, reject_unsafe_text
from .models import (
    DATASET_CONTENT_ID_VERSION,
    DATASET_SCHEMA_ID_VERSION,
    DatasetField,
    DatasetSchema,
)

_SCHEMA_ID_PREFIX = "dataset-schema"
_CONTENT_ID_PREFIX = "dataset-logical-content"


def dataset_schema_id(schema: DatasetSchema) -> str:
    """Versioned SHA-256 over the ordered field names, ordered logical types,
    ordered nullability flags, and the schema identity version.

    Field order is authoritative; Python object construction order outside the
    fields tuple never matters. Field names are NFC-normalized and validated
    at model construction.
    """
    if not isinstance(schema, DatasetSchema):
        raise DatasetError(
            f"dataset_schema_id requires a DatasetSchema, got {type(schema).__name__}"
        )
    field_text = "\x1e".join(
        f"{field.name}|{field.logical_type}|{'1' if field.nullable else '0'}"
        for field in schema.fields
    )
    return encode_identity(
        _SCHEMA_ID_PREFIX,
        {"version": DATASET_SCHEMA_ID_VERSION, "fields": field_text},
    )


def _coerce_scalar(field: DatasetField, value) -> str:
    """Validate one row value against its declared logical type and return its
    canonical tagged scalar text. Fails closed on any mismatch."""
    if value is None:
        if not field.nullable:
            raise DatasetError(f"non-nullable field {field.name!r} received null")
        return "n"
    logical_type = field.logical_type
    if logical_type == "string":
        if not isinstance(value, str):
            raise DatasetError(
                f"field {field.name!r} expects string, got {type(value).__name__}"
            )
        # No stripping, no case folding; control characters and encoding
        # separators fail so the tagged payload cannot be corrupted.
        reject_unsafe_text(value, f"string field {field.name!r}")
        return encode_scalar(value)
    if logical_type == "int64":
        if type(value) is bool or not isinstance(value, numbers.Integral):
            raise DatasetError(
                f"field {field.name!r} expects int64, got {type(value).__name__}"
            )
        integer = int(value)
        if not -(2**63) <= integer <= 2**63 - 1:
            raise DatasetError(
                f"field {field.name!r} int64 value out of range "
                f"[-2**63, 2**63-1]: {integer}"
            )
        return encode_scalar(integer)
    if logical_type == "float64":
        if type(value) is bool or not isinstance(value, numbers.Real):
            raise DatasetError(
                f"field {field.name!r} expects float64, got {type(value).__name__}"
            )
        return encode_scalar(float(value))
    if logical_type == "bool":
        if type(value) is not bool:
            raise DatasetError(
                f"field {field.name!r} expects bool, got {type(value).__name__}"
            )
        return encode_scalar(value)
    if logical_type == "date32":
        if isinstance(value, (pd.Timestamp, datetime)):
            raise DatasetError(
                f"field {field.name!r} is date32 and rejects datetime values; "
                f"convert deliberately before calling the identity layer"
            )
        if not isinstance(value, date):
            raise DatasetError(
                f"field {field.name!r} expects date32, got {type(value).__name__}"
            )
        return encode_scalar(value)
    if logical_type == "timestamp_us_utc":
        if not isinstance(value, (pd.Timestamp, datetime)):
            raise DatasetError(
                f"field {field.name!r} expects timestamp_us_utc, "
                f"got {type(value).__name__}"
            )
        # encode_scalar rejects naive timestamps and normalizes to UTC
        # microseconds, so equivalent timezone representations hash identically.
        return encode_scalar(value)
    raise DatasetError(f"unsupported logical type {logical_type!r}")


def _row_digest(schema: DatasetSchema, row: Mapping[str, object]) -> str:
    """Deterministic per-row digest under the exact schema.

    The row must contain exactly the schema fields (no missing, no unknown);
    every value must match its declared logical type; duplicate logical rows
    produce identical digests and therefore preserve multiplicity.
    """
    if not isinstance(row, Mapping):
        raise DatasetError(
            f"logical rows must be mappings, got {type(row).__name__}"
        )
    fields = schema.fields
    field_names = {field.name for field in fields}
    for field in fields:
        if field.name not in row:
            raise DatasetError(f"row is missing field {field.name!r}")
    for key in row:
        if key not in field_names:
            raise DatasetError(f"row contains unknown field {key!r}")
    if len(row) != len(fields):
        raise DatasetError(
            f"row must contain exactly the schema fields; expected {len(fields)} fields, "
            f"got {len(row)}"
        )
    # Fragments are built in the authoritative field order, so input
    # construction order of the mapping never matters.
    payload = "\x1f".join(
        f"{field.name}:{_coerce_scalar(field, row[field.name])}" for field in fields
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def logical_dataset_content_id(schema: DatasetSchema, rows) -> str:
    """Versioned SHA-256 over ``dataset_schema_id`` and every logical row
    encoded under that schema, preserving row multiplicity.

    Row order is irrelevant: each row contributes one digest and the digests
    are sorted with duplicates preserved. Therefore reversing rows does not
    change the ID, adding or removing one duplicate row does change it,
    equivalent timezone representations of one instant do not change it, and
    changing any value, null state, field order, type, or nullability does
    change it.
    """
    schema_id = dataset_schema_id(schema)
    try:
        row_iterator = iter(rows)
    except TypeError as exc:
        raise DatasetError(
            f"logical rows must be iterable, got {type(rows).__name__}"
        ) from exc
    row_digests = [_row_digest(schema, row) for row in row_iterator]
    row_digests.sort()
    return encode_identity(
        _CONTENT_ID_PREFIX,
        {
            "version": DATASET_CONTENT_ID_VERSION,
            "schema_id": schema_id,
            "row_hashes": "\x1e".join(row_digests),
        },
    )
