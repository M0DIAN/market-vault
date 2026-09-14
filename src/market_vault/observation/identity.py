"""Domain-separated pure identities using MarketVault's tagged scalar codec.

Compound records are hashes of named scalar fields. Sequences contain only
fixed-width digests, with an explicit count; no raw nested JSON or repr enters
an identity. These functions do not read, write or qualify external evidence.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from ..dataset.encoding import encode_identity
from ._validation import ObservationError, instant, items
from .models import (
    Observation,
    ObservationBuildIdentityInput,
    ObservationContractPin,
    ObservationCoverage,
    ObservationDimension,
    ObservationScope,
    ObservationSnapshotMember,
    ObservationSourceSnapshotInput,
)
from .schema import (
    OBSERVATION_BUILD_ID_VERSION,
    OBSERVATION_CONTENT_ID_VERSION,
    OBSERVATION_COVERAGE_ID_VERSION,
    OBSERVATION_KEY_VERSION,
    OBSERVATION_SOURCE_CONTENT_ID_VERSION,
    OBSERVATION_SOURCE_SNAPSHOT_ID_VERSION,
    OBSERVATION_VALUE_SCHEMA_ID_VERSION,
    OBSERVATION_VERSION_ID_VERSION,
    ObservationValueSchema,
)


def _sequence(domain: str, digests) -> str:
    values = tuple(digests)
    return encode_identity(domain, {"count": len(values), "members": "".join(values)})


def _scope_fields(scope: ObservationScope) -> dict:
    dimensions = (
        encode_identity("observation-dimension-v1", {
            "name": dim.name, "logical_type": dim.logical_type, "value": dim.value,
        })
        for dim in scope.dimensions
    )
    return {
        "provider_id": scope.provider_id,
        "source_kind": scope.source_kind,
        "entity_id": scope.entity_id,
        "observation_name": scope.observation_name,
        "dimensions": _sequence("observation-dimensions-v1", dimensions),
    }


def _pin(pin: ObservationContractPin) -> str:
    return encode_identity("observation-contract-pin-v1", {
        "version": pin.version, "content_id": pin.content_id,
    })


def observation_value_schema_id(schema: ObservationValueSchema) -> str:
    """Hash ordered explicit numeric field names, types, units and representations."""
    if type(schema) is not ObservationValueSchema:
        raise ObservationError("schema must be ObservationValueSchema")
    return _sequence(OBSERVATION_VALUE_SCHEMA_ID_VERSION, (
        encode_identity("observation-value-field-v1", {
            "name": field.name, "logical_type": field.logical_type,
            "unit": field.unit, "representation": field.representation,
        })
        for field in schema.fields
    ))


def observation_key(
    *,
    provider_id: str,
    source_kind: str,
    entity_id: str,
    observation_name: str,
    dimensions: tuple[ObservationDimension, ...],
    event_time: datetime,
    event_period_start: datetime | None = None,
) -> str:
    """Logical effective observation only, independent of revision/evidence."""
    scope = ObservationScope(provider_id, source_kind, entity_id, observation_name, dimensions)
    event = instant(event_time, "event_time")
    start = None if event_period_start is None else instant(event_period_start, "event_period_start")
    if start is not None and start >= event:
        raise ObservationError("event_period_start must precede event_time")
    return encode_identity(OBSERVATION_KEY_VERSION, {
        **_scope_fields(scope), "event_time": event, "event_period_start": start,
    })


def observation_version_id(row: Observation) -> str:
    """Bind K and the complete normalized revision/value/evidence facts."""
    if type(row) is not Observation:
        raise ObservationError("row must be Observation")
    values = None if row.values is None else _sequence("observation-values-v1", (
        encode_identity("observation-value-v1", {"value": value}) for value in row.values
    ))
    return encode_identity(OBSERVATION_VERSION_ID_VERSION, {
        "observation_key": row.observation_key,
        "value_schema_id": row.value_schema_id,
        "values": values,
        "value_status": row.value_status,
        "known_at": row.known_at,
        "known_at_authority_id": row.known_at_authority_id,
        "archive_available_at": row.archive_available_at,
        "source_snapshot_id": row.source_snapshot_id,
        "source_content_sha256": row.source_content_sha256,
        "provider_contract_version": row.provider_contract_version,
        "provider_contract_content_id": row.provider_contract_content_id,
        "normalization_version": row.normalization_version,
        "normalization_content_id": row.normalization_content_id,
        "revision_id": row.revision_id,
        "supersedes_revision_id": row.supersedes_revision_id,
    })


def observation_source_content_id(members: tuple[ObservationSnapshotMember, ...]) -> str:
    """Sorted safe multi-file inventory seal, not file hashing or file I/O."""
    members = items(members, ObservationSnapshotMember, "members", nonempty=True)
    if len({m.relative_name for m in members}) != len(members):
        raise ObservationError("duplicate snapshot members")
    return _sequence(OBSERVATION_SOURCE_CONTENT_ID_VERSION, (
        encode_identity("observation-source-member-v1", {
            "relative_name": member.relative_name,
            "byte_size": member.byte_size,
            "sha256": member.sha256,
        })
        for member in sorted(members, key=lambda m: m.relative_name)
    ))


def observation_source_snapshot_id(snapshot: ObservationSourceSnapshotInput) -> str:
    """Bind the content, exact request/contract and acquisition receipt."""
    if type(snapshot) is not ObservationSourceSnapshotInput:
        raise ObservationError("snapshot must be ObservationSourceSnapshotInput")
    return encode_identity(OBSERVATION_SOURCE_SNAPSHOT_ID_VERSION, {
        "provider_id": snapshot.provider_id,
        "source_kind": snapshot.source_kind,
        "provider_contract": _pin(snapshot.provider_contract),
        "normalized_request_id": snapshot.normalized_request_id,
        "source_content_sha256": snapshot.source_content_sha256,
        "acquisition_receipt_id": snapshot.acquisition_receipt_id,
        "acquisition_receipt_content_id": snapshot.acquisition_receipt_content_id,
        "completed_possession_at": snapshot.completed_possession_at,
    })


def observation_coverage_id(coverage: ObservationCoverage) -> str:
    """Bind coverage claims and their evidence, without inferring truth."""
    if type(coverage) is not ObservationCoverage:
        raise ObservationError("coverage must be ObservationCoverage")
    return encode_identity(OBSERVATION_COVERAGE_ID_VERSION, {
        **_scope_fields(coverage.scope),
        "provider_contract": _pin(coverage.provider_contract),
        "range_bounds": "closed",
        "effective_start": coverage.effective_start,
        "effective_end": coverage.effective_end,
        "knowledge_start": coverage.knowledge_start,
        "knowledge_end": coverage.knowledge_end,
        "normalized_request_id": coverage.normalized_request_id,
        "request_completion_evidence_id": coverage.request_completion_evidence_id,
        "request_pages_complete": coverage.request_pages_complete,
        "missing_semantics": coverage.missing_semantics,
        "missing_semantics_content_id": coverage.missing_semantics_content_id,
        "revision_inventory_content_id": coverage.revision_inventory_content_id,
        "revision_inventory_complete": coverage.revision_inventory_complete,
    })


def _ordered_rows(rows) -> tuple[Observation, ...]:
    rows = items(rows, Observation, "rows")
    by_version: dict[str, Observation] = {}
    for row in rows:
        existing = by_version.get(row.observation_version_id)
        if existing is not None and existing != row:
            raise ObservationError("conflicting duplicate observation_version_id")
        by_version[row.observation_version_id] = row
    for row in by_version.values():
        # Frozen objects are the normal input; never hash a forged/stale ID.
        if replace(row) != row:
            raise ObservationError("Observation is not normalized or has inconsistent derived IDs")
    return tuple(sorted(by_version.values(), key=lambda r: (r.observation_key, r.observation_version_id)))


def observation_content_id(rows: tuple[Observation, ...]) -> str:
    """Order-independent normalized row content; identical duplicates collapse."""
    return _sequence(OBSERVATION_CONTENT_ID_VERSION, (
        encode_identity("observation-content-row-v1", {
            "observation_key": row.observation_key,
            "observation_version_id": row.observation_version_id,
        })
        for row in _ordered_rows(rows)
    ))


def observation_build_id(build: ObservationBuildIdentityInput) -> str:
    """Pure declared build identity; no materialization, reader or PIT engine."""
    if type(build) is not ObservationBuildIdentityInput:
        raise ObservationError("build must be ObservationBuildIdentityInput")
    return encode_identity(OBSERVATION_BUILD_ID_VERSION, {
        "schema_version": build.schema_version,
        "observation_content_id": observation_content_id(build.rows),
        "source_snapshot_ids": _sequence("observation-build-snapshots-v1", build.source_snapshot_ids),
        "authority_evidence_ids": _sequence("observation-build-authorities-v1", build.authority_evidence_ids),
        "provider_contracts": _sequence("observation-build-providers-v1", map(_pin, build.provider_contracts)),
        "normalizations": _sequence("observation-build-normalizers-v1", map(_pin, build.normalizations)),
        "coverage_id": observation_coverage_id(build.coverage),
    })
