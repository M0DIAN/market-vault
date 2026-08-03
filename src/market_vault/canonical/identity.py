"""Canonical identity encodings.

Implements the two identity levels of ADR 0001:

- ``canonical_bar_key``: business identity of the market event
  ``(dataset_kind, code, interval, adjustment, event_time)``.
- ``canonical_row_version_id``: physical row version identity
  ``canonical_bar_key + ingestion_run_id + source_snapshot_content_hash +
  source_schema_version + canonical_builder_version``.

Both use an explicit versioned SHA-256 encoding over a canonical serialization
with a fixed field order; Python's process-randomized builtin ``hash()`` is
never used.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

import pandas as pd

#: Explicit encoding version; bumping it changes every derived identity.
IDENTITY_ENCODING_VERSION = "v1"

_KEY_PREFIX = "market-bars-canonical-key"
_ROW_VERSION_PREFIX = "market-bars-canonical-row-version"


def _utc_iso(value: pd.Timestamp | datetime) -> str:
    if isinstance(value, pd.Timestamp):
        stamp = value
    else:
        stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        raise ValueError(f"naive timestamp cannot be encoded as a canonical identity: {value!r}")
    return stamp.tz_convert("UTC").isoformat()


def _field_text(value) -> str:
    if isinstance(value, (pd.Timestamp, datetime)):
        return _utc_iso(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return repr(float(value))
    return str(value)


def _encode(prefix: str, fields: dict[str, object]) -> str:
    """Versioned SHA-256 over a canonical JSON serialization.

    The payload is sorted by key and serialized with compact separators, so
    the digest depends only on the field values, never on insertion order.
    """
    payload = json.dumps(
        {key: _field_text(value) for key, value in fields.items()},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    text = f"{IDENTITY_ENCODING_VERSION}|{prefix}|{payload}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_bar_key(
    *,
    dataset_kind: str,
    code: str,
    interval: str,
    adjustment: str,
    event_time: pd.Timestamp,
) -> str:
    """Business identity of a market event.

    ``event_time`` must be timezone-aware; it is normalized to UTC before
    encoding, so two representations of the same instant yield the same key.
    ``ingestion_run_id``, ``source_schema_version``, ``requested_trade_date``,
    ``requested_session``, ``market_calendar_date``, and ``session`` are
    deliberately not part of the business identity.
    """
    return _encode(
        _KEY_PREFIX,
        {
            "dataset_kind": dataset_kind,
            "code": code,
            "interval": interval,
            "adjustment": adjustment,
            "event_time": event_time,
        },
    )


def canonical_row_version_id(
    *,
    canonical_bar_key: str,
    ingestion_run_id: str,
    source_snapshot_content_hash: str,
    source_schema_version: str,
    canonical_builder_version: str,
) -> str:
    """Physical row version identity.

    ``snapshot_file`` is provenance only and must not affect the identity:
    moving a byte-identical snapshot to another path keeps the same row
    version ID, while changing contents, run ID, schema version, or builder
    version changes it.
    """
    return _encode(
        _ROW_VERSION_PREFIX,
        {
            "canonical_bar_key": canonical_bar_key,
            "ingestion_run_id": ingestion_run_id,
            "source_snapshot_content_hash": source_snapshot_content_hash,
            "source_schema_version": source_schema_version,
            "canonical_builder_version": canonical_builder_version,
        },
    )
