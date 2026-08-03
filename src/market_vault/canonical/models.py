"""Canonical market-bar data models.

Defines the in-memory canonical row, source references, the exact request
key, resolution metadata, and structured errors used by the canonical builder
core (ADR 0001). No materialization happens here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd

from ..storage.catalog import CompleteSnapshotRef


@dataclass(frozen=True)
class CanonicalRequestKey:
    """Exact request key the source rows must match (ADR 0001, section 4)."""

    interval: str
    requested_session: str
    adjustment: str
    source_schema_version: str


@dataclass(frozen=True)
class CanonicalBar:
    """One canonical business row derived from an audited complete snapshot.

    ``canonical_bar_key`` identifies the market event; ``canonical_row_version_id``
    identifies the physical data and builder version that produced this row.
    The remaining fields are the market values, time columns, and
    provenance/audit/classification metadata (ADR 0001, sections 2 and 4).
    """

    canonical_bar_key: str
    canonical_row_version_id: str
    dataset_kind: str
    code: str
    interval: str
    adjustment: str
    event_time: pd.Timestamp
    market_available_at: pd.Timestamp
    archive_available_at: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: int | float
    extra_fields: tuple[tuple[str, float], ...]
    # Provenance and audit/classification fields (not part of the business key).
    ingestion_run_id: str
    physical_snapshot_hash: str
    logical_source_rows_hash: str
    source_schema_version: str
    canonical_builder_version: str
    requested_trade_date: date
    requested_session: str
    market_calendar_date: date | None
    session: str
    snapshot_file: str


@dataclass(frozen=True)
class CanonicalSnapshotInput:
    """One audited complete physical snapshot fed to the canonical builder.

    ``snapshot`` must come from the V0.3 latest-complete selection
    (``Catalog.latest_complete_market_bar_snapshots``); it is the COMPLETE
    gate. The builder never redefines completion: it validates that the
    supplied rows actually match the selected ref and the exact request key,
    and it fails closed on any mismatch. ``physical_snapshot_hash`` is the
    SHA-256 of the complete physical snapshot file bytes (precomputed input).
    """

    snapshot: CompleteSnapshotRef
    rows: pd.DataFrame
    physical_snapshot_hash: str
    request_key: CanonicalRequestKey


@dataclass(frozen=True)
class CanonicalSourceRef:
    """Reference to one source snapshot contributing to a canonical row.

    ``snapshot_file`` is descriptive provenance: a relocated byte-identical
    file keeps the same identities and the same selected logical source.
    """

    ingestion_run_id: str
    physical_snapshot_hash: str
    logical_source_rows_hash: str
    snapshot_file: str
    requested_trade_date: date
    requested_session: str


@dataclass(frozen=True)
class CanonicalResolutionEntry:
    """How duplicate business keys were reconciled for one canonical row."""

    canonical_bar_key: str
    selected: CanonicalSourceRef
    equivalent_discarded: tuple[CanonicalSourceRef, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CanonicalBuildResult:
    """Deterministic output of the canonical builder core.

    ``bars`` is ordered by ``canonical_bar_key`` ascending; ``resolution`` is
    ordered the same way and contains one entry per emitted row.
    ``source_snapshot_count`` counts distinct physical snapshot identities
    (physical files), not distinct run ids: one run may produce several files.
    """

    bars: tuple[CanonicalBar, ...]
    resolution: tuple[CanonicalResolutionEntry, ...]
    builder_version: str
    source_snapshot_count: int


class CanonicalConflictError(Exception):
    """Two source candidates for the same canonical_bar_key disagree on
    contract-relevant market or classification values.

    Raised instead of silently emitting two business rows or picking a winner
    (ADR 0001, key reconciliation rule).
    """

    def __init__(
        self,
        *,
        canonical_bar_key: str,
        differing_fields: tuple[str, ...],
        candidates: tuple[dict, ...],
    ) -> None:
        self.canonical_bar_key = canonical_bar_key
        self.differing_fields = differing_fields
        self.candidates = candidates
        lines = [
            f"conflicting canonical candidates for key {canonical_bar_key}",
            f"differing fields: {', '.join(differing_fields)}",
        ]
        for candidate in candidates:
            lines.append(
                "  run_id={run_id} snapshot_hash={snapshot_hash} "
                "snapshot_file={snapshot_file}".format(**candidate)
            )
        super().__init__("\n".join(lines))


@dataclass(frozen=True)
class CanonicalBuildError(ValueError):
    """Structured validation failure of canonical inputs (fail-closed)."""

    reason: str
