"""Canonical build manifest contract (v1).

The manifest is the authority describing one immutable canonical build:
logical identities, normalized request, counts, time ranges, source snapshot
provenance, and ordered output file records. Serialization is deterministic:
UTF-8, sorted keys, stable list ordering, compact separators, trailing
newline. created_at and observed file byte hashes are recorded facts; they
never enter canonical_build_id.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_SCHEMA_VERSION = "canonical-market-bars-manifest-v1"

STATUS_COMPLETE = "COMPLETE"
STATUS_EMPTY = "EMPTY"

#: Documented limitations of the internal gap policy, recorded in every manifest.
GAP_POLICY_LIMITATIONS = (
    "Internal gaps are detected only between adjacent observed Canonical bars "
    "within the same (dataset_kind, code, interval, adjustment, "
    "market_calendar_date, session) group.",
    "Missing bars before the first observed bar or after the last observed bar "
    "are not inferred.",
    "Cross-session and cross-market-calendar-date gaps are not inferred.",
    "Whether the exchange was officially open, early-close boundaries, and "
    "full-session completeness are not judged.",
    "The sidecar reports internal nominal spacing gaps, not an authoritative "
    "exchange-calendar completeness judgment.",
)


def build_manifest(
    *,
    status: str,
    dataset_kind: str,
    canonical_build_id: str,
    canonical_content_id: str,
    resolution_content_id: str,
    gap_content_id: str,
    canonical_builder_version: str,
    canonical_schema_version: str,
    materializer_version: str,
    gap_policy_version: str,
    created_at: datetime,
    symbols: list[str],
    trade_dates: list,
    request_key,
    source_snapshot_count: int,
    canonical_row_count: int,
    gap_range_count: int,
    resolution_row_count: int,
    min_event_time,
    max_event_time,
    min_archive_available_at,
    max_archive_available_at,
    source_snapshot_provenance: list[dict],
    output_files: list[dict],
) -> dict:
    """Deterministic manifest payload with sorted keys and stable ordering."""
    return {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "status": status,
        "dataset_kind": dataset_kind,
        "canonical_build_id": canonical_build_id,
        "canonical_content_id": canonical_content_id,
        "resolution_content_id": resolution_content_id,
        "gap_content_id": gap_content_id,
        "canonical_builder_version": canonical_builder_version,
        "canonical_schema_version": canonical_schema_version,
        "materializer_version": materializer_version,
        "gap_policy_version": gap_policy_version,
        "created_at": created_at.astimezone(timezone.utc).isoformat(),
        "normalized_request": {
            "symbols": sorted(symbols),
            "trade_dates": sorted(value.isoformat() for value in trade_dates),
            "interval": request_key.interval,
            "requested_session": request_key.requested_session,
            "adjustment": request_key.adjustment,
            "source_schema_version": request_key.source_schema_version,
        },
        "source_snapshot_count": source_snapshot_count,
        "canonical_row_count": canonical_row_count,
        "gap_range_count": gap_range_count,
        "resolution_row_count": resolution_row_count,
        "min_event_time": min_event_time.tz_convert("UTC").isoformat() if min_event_time is not None else None,
        "max_event_time": max_event_time.tz_convert("UTC").isoformat() if max_event_time is not None else None,
        "min_archive_available_at": (
            min_archive_available_at.tz_convert("UTC").isoformat()
            if min_archive_available_at is not None
            else None
        ),
        "max_archive_available_at": (
            max_archive_available_at.tz_convert("UTC").isoformat()
            if max_archive_available_at is not None
            else None
        ),
        "source_snapshot_provenance": list(source_snapshot_provenance),
        "output_files": list(output_files),
        "gap_policy_limitations": list(GAP_POLICY_LIMITATIONS),
    }


def write_manifest_json(path: Path, payload: dict) -> None:
    """Write the manifest with deterministic serialization and a trailing newline."""
    text = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ) + "\n"
    path.write_text(text, encoding="utf-8")
