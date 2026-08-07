"""Deterministic versioned Catalog content identity of the v0.6.0 Dataset
Catalog contract (PR-5).

``catalog_dataset_content_id`` is the per-Dataset content digest of one
:class:`DatasetCatalogDatasetFacts` record; ``dataset_catalog_content_id``
is the Catalog content identity of one normalized set of entries. Both use
the existing versioned canonical encoding
(:func:`market_vault.dataset.encoding.encode_identity`) with the
Catalog's own domain prefixes; no existing identity algorithm or version
constant is modified and the Catalog identity never flows back into any
Dataset or Canonical identity.

The Catalog content identity is determined only by the normalized set of
verified Dataset facts under the versioned Catalog contract. The
following never enter it: ``built_at``, Dataset build paths / location
metadata, the Catalog ``output_root``, the Catalog snapshot path, machine
names, host-specific filesystem representation, cwd, mtimes, the current
time, scan order, and candidate input order. Input order never matters
(entries are normalized by ``dataset_id`` with an exact-duplicate merge
and a fail-closed conflict policy), equivalent timezone representations
of the same instant produce the same identity, and moving a verified
Dataset to another parent directory never changes it.

Duplicate ``dataset_id`` policy: exactly identical normalized content
facts merge under set semantics into one Dataset record; any conflicting
content fact for the same ``dataset_id`` fails closed. First-wins,
last-wins, and path-wins are never used.

This module never reads or writes files, never scans directories, never
calls the verified Dataset reader, never loads settings, never accesses
the network, and never uses the current time.
"""

from __future__ import annotations

from .dataset_catalog_models import (
    DATASET_CATALOG_CONTRACT_VERSION,
    DATASET_CATALOG_CONTENT_ID_VERSION,
    DATASET_CATALOG_ENTRY_SCHEMA_VERSION,
    DatasetCatalogDatasetFacts,
    DatasetCatalogEntry,
    DatasetCatalogError,
)
from .encoding import DatasetError, encode_identity

__all__ = [
    "catalog_dataset_content_id",
    "dataset_catalog_content_id",
]

#: Domain-separated sub-digest prefixes of the Catalog content identity
#: (fixed-length 64-character SHA-256 hex, so the ``\\x1e`` sequence
#: encoding is unambiguous; all strings reaching the encoding are safe text
#: that can never contain the separator).
_CANONICAL_BUILD_PIN_DIGEST_PREFIX = "dataset-catalog-canonical-build-pin"
_SPEC_PIN_DIGEST_PREFIX = "dataset-catalog-spec-pin"
_COMPLETION_ENTRY_DIGEST_PREFIX = "dataset-catalog-completion-entry"
_DATASET_FACTS_DIGEST_PREFIX = "dataset-catalog-dataset-facts"


def _spec_pin_digest(pin) -> str:
    """Sub-digest of one Feature / Label / Split spec pin: kind, name,
    version, and content SHA-256 (the frozen SpecPin contract)."""
    return encode_identity(
        _SPEC_PIN_DIGEST_PREFIX,
        {
            "kind": pin.kind,
            "name": pin.name,
            "version": pin.version,
            "content_sha256": pin.content_sha256,
        },
    )


def _canonical_build_pin_digest(pin) -> str:
    """Sub-digest of one canonical build pin.

    Binds the full frozen :class:`CanonicalBuildPin` identity contract:
    build / content / gap identities, builder / schema / materializer /
    gap-policy versions, status, the sorted canonical row-version IDs, and
    the sorted source snapshot pins. ``snapshot_file`` is descriptive
    provenance of the pin model and is excluded from the sub-digest, so a
    relocated byte-identical source snapshot never changes the Catalog
    identity.
    """
    return encode_identity(
        _CANONICAL_BUILD_PIN_DIGEST_PREFIX,
        {
            "canonical_build_id": pin.canonical_build_id,
            "canonical_content_id": pin.canonical_content_id,
            "canonical_builder_version": pin.canonical_builder_version,
            "canonical_schema_version": pin.canonical_schema_version,
            "materializer_version": pin.materializer_version,
            "gap_policy_version": pin.gap_policy_version,
            "gap_content_id": pin.gap_content_id,
            "status": pin.status,
            "canonical_row_version_ids": "\x1e".join(
                pin.canonical_row_version_ids
            ),
            "source_snapshots": "\x1e".join(
                encode_identity(
                    "dataset-catalog-source-snapshot",
                    {
                        "ingestion_run_id": snapshot.ingestion_run_id,
                        "physical_snapshot_hash": snapshot.physical_snapshot_hash,
                        "logical_source_rows_hash": snapshot.logical_source_rows_hash,
                        "source_schema_version": snapshot.source_schema_version,
                        "requested_trade_date": snapshot.requested_trade_date,
                        "requested_session": snapshot.requested_session,
                    },
                )
                for snapshot in pin.source_snapshots
            ),
        },
    )


def _completion_entry_digest(entry) -> str:
    """Sub-digest of one completion entry: code, trade date, status, and
    the optional stable reason code."""
    return encode_identity(
        _COMPLETION_ENTRY_DIGEST_PREFIX,
        {
            "code": entry.code,
            "trade_date": entry.trade_date,
            "status": entry.status,
            "reason_code": entry.reason_code,
        },
    )


def catalog_dataset_content_id(
    facts: DatasetCatalogDatasetFacts,
) -> str:
    """64-character lowercase SHA-256 of the deterministic content of one
    :class:`DatasetCatalogDatasetFacts` record.

    The digest binds the entry schema version, ``dataset_id``,
    ``dataset_kind``, ``status``, ``logical_row_count``,
    ``dataset_schema_id``, ``logical_dataset_content_id``, the normalized
    ``dataset_as_of``, the normalized scope, the normalized Feature /
    Label / Split spec pins, the normalized canonical build pins, the
    normalized canonical row-version IDs, and the normalized completion
    summary, all through the existing versioned canonical encoding. It
    never binds ``built_at``, paths, or any observed metadata.
    """
    if not isinstance(facts, DatasetCatalogDatasetFacts):
        raise DatasetCatalogError(
            f"catalog_dataset_content_id requires a DatasetCatalogDatasetFacts, "
            f"got {type(facts).__name__}"
        )
    scope = facts.scope
    fields = {
        "entry_schema_version": DATASET_CATALOG_ENTRY_SCHEMA_VERSION,
        "dataset_id": facts.dataset_id,
        "dataset_kind": facts.dataset_kind,
        "status": facts.status,
        "logical_row_count": facts.logical_row_count,
        "dataset_schema_id": facts.dataset_schema_id,
        "logical_dataset_content_id": facts.logical_dataset_content_id,
        "dataset_as_of": facts.dataset_as_of,
        "scope_symbols": "\x1e".join(scope.symbols),
        "scope_trade_dates": "\x1e".join(
            trade_date.isoformat() for trade_date in scope.trade_dates
        ),
        "scope_interval": scope.interval,
        "scope_adjustment": scope.adjustment,
        "scope_requested_session": scope.requested_session,
        "feature_spec_pins": "\x1e".join(
            _spec_pin_digest(pin) for pin in facts.feature_spec_pins
        ),
        "label_spec_pins": "\x1e".join(
            _spec_pin_digest(pin) for pin in facts.label_spec_pins
        ),
        "split_spec_pin": (
            _spec_pin_digest(facts.split_spec_pin)
            if facts.split_spec_pin is not None
            else None
        ),
        "canonical_build_pins": "\x1e".join(
            _canonical_build_pin_digest(pin)
            for pin in facts.canonical_build_pins
        ),
        "canonical_row_version_ids": "\x1e".join(
            facts.canonical_row_version_ids
        ),
        "completion_complete_count": facts.completion.complete_count,
        "completion_incomplete_count": facts.completion.incomplete_count,
        "completion_missing_count": facts.completion.missing_count,
        "completion_entries": "\x1e".join(
            _completion_entry_digest(entry)
            for entry in facts.completion.entries
        ),
    }
    try:
        return encode_identity(_DATASET_FACTS_DIGEST_PREFIX, fields)
    except DatasetError as exc:
        raise DatasetCatalogError(str(exc)) from exc


def dataset_catalog_content_id(
    entries: tuple,
) -> str:
    """64-character lowercase SHA-256 of the deterministic Catalog content
    of one normalized set of :class:`DatasetCatalogEntry` records.

    Entries are normalized by set semantics keyed on ``dataset_id``:
    exactly identical :class:`DatasetCatalogDatasetFacts` records merge
    into one, and any conflicting content fact for the same
    ``dataset_id`` fails closed (first-wins, last-wins, and path-wins are
    never used). The resulting unique records are encoded in
    ``dataset_id`` order, so candidate input order, scan order, and
    Dataset relocation never change the identity. The identity binds the
    Catalog contract version and the per-Dataset content digests only;
    ``built_at``, build paths, output roots, snapshot paths, machine
    names, cwd, mtimes, and the current time never enter it, and it never
    flows back into any Dataset or Canonical identity.
    """
    if not isinstance(entries, tuple):
        raise DatasetCatalogError(
            f"dataset_catalog_content_id requires a tuple of "
            f"DatasetCatalogEntry records, got {type(entries).__name__}"
        )
    by_id: dict = {}
    for entry in entries:
        if not isinstance(entry, DatasetCatalogEntry):
            raise DatasetCatalogError(
                "dataset_catalog_content_id entries must be "
                f"DatasetCatalogEntry instances, got {type(entry).__name__}"
            )
        facts = entry.dataset_facts
        existing = by_id.get(facts.dataset_id)
        if existing is None:
            by_id[facts.dataset_id] = facts
        elif existing != facts:
            raise DatasetCatalogError(
                f"conflicting DatasetCatalogDatasetFacts for dataset_id "
                f"{facts.dataset_id}"
            )
    dataset_digests = "\x1e".join(
        f"{dataset_id}:{catalog_dataset_content_id(facts)}"
        for dataset_id, facts in sorted(by_id.items())
    )
    fields = {
        "contract_version": DATASET_CATALOG_CONTRACT_VERSION,
        "content_id_version": DATASET_CATALOG_CONTENT_ID_VERSION,
        "dataset_count": len(by_id),
        "datasets": dataset_digests,
    }
    try:
        return encode_identity(DATASET_CATALOG_CONTENT_ID_VERSION, fields)
    except DatasetError as exc:
        raise DatasetCatalogError(str(exc)) from exc
