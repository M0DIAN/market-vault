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
        return f"t:{_utc_iso(value)}"
    if isinstance(value, date):
        return f"d:{value.isoformat()}"
    if isinstance(value, float):
        # Shortest round-trip decimal; explicit float marker.
        return f"f:{float(value)!r}"
    if isinstance(value, int):
        return f"i:{value}"
    return f"s:{value}"


def _encode(prefix: str, fields: dict[str, object]) -> str:
    """Versioned SHA-256 over an explicitly typed canonical serialization.

    Every value is encoded with an explicit type marker (s/d/t/f/i) and a
    normalized representation; the payload is sorted by key, so the digest
    depends only on the field values, never on insertion order. SHA-256 is
    used as a collision-resistant digest; it is not claimed to be
    collision-free.
    """
    payload = "\x1f".join(
        f"{key}:{_field_text(value)}" for key, value in sorted(fields.items())
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


# ---------------------------------------------------------------------------
# Build-level logical identities (ADR 0001, section 5).
# ---------------------------------------------------------------------------

_CONTENT_ID_PREFIX = "canonical-content"
_RESOLUTION_ID_PREFIX = "canonical-resolution"
_GAP_ID_PREFIX_BUILD = "canonical-gap-content"
_BUILD_ID_PREFIX = "canonical-build"


def _stable_source_identity(
    *,
    ingestion_run_id: str,
    physical_snapshot_hash: str,
    logical_source_rows_hash: str,
    source_schema_version: str,
    requested_trade_date,
    requested_session: str,
) -> dict:
    """Path-independent stable source identity (snapshot_file excluded)."""
    return {
        "ingestion_run_id": ingestion_run_id,
        "physical_snapshot_hash": physical_snapshot_hash,
        "logical_source_rows_hash": logical_source_rows_hash,
        "source_schema_version": source_schema_version,
        "requested_trade_date": requested_trade_date,
        "requested_session": requested_session,
    }


def canonical_content_id(bars: tuple) -> str:
    """Versioned SHA-256 over deterministic logical Canonical Bar contents.

    Includes all authoritative logical row fields and canonical identities;
    excludes created_at, output paths, Parquet byte layout, file size,
    serializer metadata, and ``snapshot_file`` (movable descriptive
    provenance). Row order is normalized by sorting row digests, so equivalent
    logical rows in any input order or timezone display produce the same ID.
    """
    row_digests = []
    for bar in bars:
        fields = {
            "canonical_bar_key": bar.canonical_bar_key,
            "canonical_row_version_id": bar.canonical_row_version_id,
            "dataset_kind": bar.dataset_kind,
            "code": bar.code,
            "interval": bar.interval,
            "adjustment": bar.adjustment,
            "event_time": bar.event_time,
            "market_available_at": bar.market_available_at,
            "archive_available_at": bar.archive_available_at,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "extra_fields": tuple(bar.extra_fields),
            "ingestion_run_id": bar.ingestion_run_id,
            "physical_snapshot_hash": bar.physical_snapshot_hash,
            "logical_source_rows_hash": bar.logical_source_rows_hash,
            "source_schema_version": bar.source_schema_version,
            "canonical_builder_version": bar.canonical_builder_version,
            "requested_trade_date": bar.requested_trade_date,
            "requested_session": bar.requested_session,
            "market_calendar_date": bar.market_calendar_date,
            "session": bar.session,
        }
        payload = "\x1f".join(
            f"{key}:{_field_text(value)}" for key, value in sorted(fields.items())
        )
        row_digests.append(hashlib.sha256(payload.encode("utf-8")).hexdigest())
    row_digests.sort()
    return _encode(_CONTENT_ID_PREFIX, {"row_hashes": "\x1e".join(row_digests)})


def resolution_content_id(resolution: tuple) -> str:
    """Deterministic path-independent hash of resolution semantics.

    Covers canonical_bar_key, the selected source stable identity, and the
    equivalent discarded source stable identities; ``snapshot_file`` never
    influences it.
    """
    entry_digests = []
    for entry in resolution:
        selected = _stable_source_identity(
            ingestion_run_id=entry.selected.ingestion_run_id,
            physical_snapshot_hash=entry.selected.physical_snapshot_hash,
            logical_source_rows_hash=entry.selected.logical_source_rows_hash,
            source_schema_version=entry.selected.source_schema_version,
            requested_trade_date=entry.selected.requested_trade_date,
            requested_session=entry.selected.requested_session,
        )
        discarded = [
            _stable_source_identity(
                ingestion_run_id=ref.ingestion_run_id,
                physical_snapshot_hash=ref.physical_snapshot_hash,
                logical_source_rows_hash=ref.logical_source_rows_hash,
                source_schema_version=ref.source_schema_version,
                requested_trade_date=ref.requested_trade_date,
                requested_session=ref.requested_session,
            )
            for ref in entry.equivalent_discarded
        ]
        payload = "\x1f".join(
            [
                f"key:{entry.canonical_bar_key}",
                f"selected:{_encode(_RESOLUTION_ID_PREFIX + '-src', selected)}",
                "discarded:"
                + "\x1e".join(
                    sorted(_encode(_RESOLUTION_ID_PREFIX + "-src", item) for item in discarded)
                ),
            ]
        )
        entry_digests.append(hashlib.sha256(payload.encode("utf-8")).hexdigest())
    entry_digests.sort()
    return _encode(_RESOLUTION_ID_PREFIX, {"entries": "\x1e".join(entry_digests)})


def gap_content_id(gaps: tuple, gap_policy_version: str) -> str:
    """Deterministic hash of generated gap sidecar rows and the gap policy."""
    gap_digests = []
    for gap in gaps:
        payload = "\x1f".join(
            [
                f"gap_id:{gap.gap_id}",
                f"dataset_kind:{gap.dataset_kind}",
                f"code:{gap.code}",
                f"interval:{gap.interval}",
                f"adjustment:{gap.adjustment}",
                f"market_calendar_date:{gap.market_calendar_date.isoformat()}",
                f"session:{gap.session}",
                f"previous:{_utc_iso(gap.previous_event_time)}",
                f"next:{_utc_iso(gap.next_event_time)}",
                f"missing_from:{_utc_iso(gap.missing_from_event_time)}",
                f"missing_to:{_utc_iso(gap.missing_to_event_time)}",
                f"missing_bar_count:{gap.missing_bar_count}",
            ]
        )
        gap_digests.append(hashlib.sha256(payload.encode("utf-8")).hexdigest())
    gap_digests.sort()
    return _encode(
        _GAP_ID_PREFIX_BUILD,
        {"gap_policy_version": gap_policy_version, "rows": "\x1e".join(gap_digests)},
    )


def canonical_build_id(
    *,
    symbols: list[str],
    trade_dates: list,
    request_key,
    canonical_content_id: str,
    resolution_content_id: str,
    gap_content_id: str,
    selected_row_version_ids: list[str],
    canonical_builder_version: str,
    canonical_schema_version: str,
    materializer_version: str,
    gap_policy_version: str,
) -> str:
    """Deterministic versioned SHA-256 over the full build contract.

    Independent of input order (all lists are normalized by sorting),
    local machine timezone, snapshot path relocation, generated file paths,
    Parquet byte hashes, and created_at. Changing the builder, schema,
    materializer, gap policy, selected physical source, or logical contents
    changes the build ID.
    """
    return _encode(
        _BUILD_ID_PREFIX,
        {
            "symbols": "\x1e".join(sorted(symbols)),
            "trade_dates": "\x1e".join(sorted(value.isoformat() for value in trade_dates)),
            "interval": request_key.interval,
            "requested_session": request_key.requested_session,
            "adjustment": request_key.adjustment,
            "source_schema_version": request_key.source_schema_version,
            "canonical_content_id": canonical_content_id,
            "resolution_content_id": resolution_content_id,
            "gap_content_id": gap_content_id,
            "selected_row_version_ids": "\x1e".join(sorted(selected_row_version_ids)),
            "canonical_builder_version": canonical_builder_version,
            "canonical_schema_version": canonical_schema_version,
            "materializer_version": materializer_version,
            "gap_policy_version": gap_policy_version,
        },
    )
