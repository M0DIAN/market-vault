"""Pure immutable Observation declarations, not verified artifact authority.

Construction proves local shape/identity consistency only. Provider evidence,
coverage truth, revision chains and artifact trust belong to later phases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ._validation import ObservationError, hashes, instant, items, numeric, sha256, text
from .schema import (
    OBSERVATION_SCHEMA_VERSION,
    OBSERVATION_VALUE_STATUSES,
    ObservationValueSchema,
)


@dataclass(frozen=True)
class ObservationDimension:
    """An exact typed semantic coordinate, never an inferred filter."""

    name: str
    logical_type: str
    value: str | int | float

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", text(self.name, "dimension name"))
        object.__setattr__(self, "logical_type", text(self.logical_type, "dimension type"))
        value = (
            text(self.value, "dimension value")
            if self.logical_type == "string"
            else numeric(self.value, self.logical_type)
        )
        object.__setattr__(self, "value", value)


@dataclass(frozen=True)
class ObservationScope:
    """One exact provider/source/entity/measure and dimension scope."""

    provider_id: str
    source_kind: str
    entity_id: str
    observation_name: str
    dimensions: tuple[ObservationDimension, ...]

    def __post_init__(self) -> None:
        for name in ("provider_id", "source_kind", "entity_id", "observation_name"):
            object.__setattr__(self, name, text(getattr(self, name), name))
        dims = items(self.dimensions, ObservationDimension, "dimensions")
        if len({dim.name for dim in dims}) != len(dims):
            raise ObservationError("duplicate dimension names")
        object.__setattr__(self, "dimensions", tuple(sorted(dims, key=lambda d: d.name)))


@dataclass(frozen=True)
class ObservationContractPin:
    """Exact version/content pair; not a registry or claim of qualification."""

    version: str
    content_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", text(self.version, "contract version"))
        sha256(self.content_id, "contract content_id")


@dataclass(frozen=True)
class Observation:
    """Normalized numeric observation with derived, non-caller-supplied IDs.

    The complete value schema is required so values cannot contradict an opaque
    schema hash. No public-knowledge or possession time is invented here.
    """

    provider_id: str
    source_kind: str
    entity_id: str
    observation_name: str
    dimensions: tuple[ObservationDimension, ...]
    event_time: datetime
    event_period_start: datetime | None
    value_schema: ObservationValueSchema
    values: tuple[int | float, ...] | None
    value_status: str
    known_at: datetime
    known_at_authority_id: str
    archive_available_at: datetime
    source_snapshot_id: str
    source_content_sha256: str
    provider_contract_version: str
    provider_contract_content_id: str
    normalization_version: str
    normalization_content_id: str
    revision_id: str
    supersedes_revision_id: str | None
    value_schema_id: str = field(init=False)
    observation_key: str = field(init=False)
    observation_version_id: str = field(init=False)

    def __post_init__(self) -> None:
        scope = ObservationScope(
            self.provider_id, self.source_kind, self.entity_id,
            self.observation_name, self.dimensions,
        )
        for name in ("provider_id", "source_kind", "entity_id", "observation_name", "dimensions"):
            object.__setattr__(self, name, getattr(scope, name))
        for name in ("event_time", "known_at", "archive_available_at"):
            object.__setattr__(self, name, instant(getattr(self, name), name))
        if self.event_period_start is not None:
            start = instant(self.event_period_start, "event_period_start")
            if start >= self.event_time:
                raise ObservationError("event_period_start must precede event_time")
            object.__setattr__(self, "event_period_start", start)
        for name in ("known_at_authority_id", "source_snapshot_id", "source_content_sha256",
                     "provider_contract_content_id", "normalization_content_id"):
            sha256(getattr(self, name), name)
        for name in ("provider_contract_version", "normalization_version", "revision_id"):
            object.__setattr__(self, name, text(getattr(self, name), name))
        if self.supersedes_revision_id is not None:
            predecessor = text(self.supersedes_revision_id, "supersedes_revision_id")
            if predecessor == self.revision_id:
                raise ObservationError("revision cannot supersede itself")
            object.__setattr__(self, "supersedes_revision_id", predecessor)
        if type(self.value_schema) is not ObservationValueSchema:
            raise ObservationError("value_schema must be ObservationValueSchema")
        if type(self.value_status) is not str or self.value_status not in OBSERVATION_VALUE_STATUSES:
            raise ObservationError("unsupported value_status")
        if self.value_status == "VALUE":
            if not isinstance(self.values, (tuple, list)):
                raise ObservationError("VALUE requires an explicit numeric tuple")
            if len(self.values) != len(self.value_schema.fields):
                raise ObservationError("value count does not match value schema")
            values = tuple(numeric(v, f.logical_type) for v, f in zip(self.values, self.value_schema.fields))
            object.__setattr__(self, "values", values)
        elif self.values is not None:
            raise ObservationError("NOT_REPORTED/WITHDRAWN require values=None")
        from .identity import observation_key, observation_value_schema_id, observation_version_id

        object.__setattr__(self, "value_schema_id", observation_value_schema_id(self.value_schema))
        object.__setattr__(self, "observation_key", observation_key(
            provider_id=self.provider_id, source_kind=self.source_kind,
            entity_id=self.entity_id, observation_name=self.observation_name,
            dimensions=self.dimensions, event_time=self.event_time,
            event_period_start=self.event_period_start,
        ))
        object.__setattr__(self, "observation_version_id", observation_version_id(self))


@dataclass(frozen=True)
class ObservationSnapshotMember:
    """Safe relative member metadata only; construction never accesses a path."""

    relative_name: str
    byte_size: int
    sha256: str

    def __post_init__(self) -> None:
        name = text(self.relative_name, "relative_name")
        if ":" in name or "\\" in name or any(p in {"", ".", ".."} for p in name.split("/")):
            raise ObservationError("unsafe snapshot relative member name")
        if type(self.byte_size) is not int or not 0 <= self.byte_size < 2**63:
            raise ObservationError("byte_size must be a nonnegative int64")
        sha256(self.sha256, "member SHA-256")
        object.__setattr__(self, "relative_name", name)


@dataclass(frozen=True)
class ObservationSourceSnapshotInput:
    """Qualified request/receipt identities, never request credentials or URLs."""

    provider_id: str
    source_kind: str
    provider_contract: ObservationContractPin
    normalized_request_id: str
    source_content_sha256: str
    acquisition_receipt_id: str
    acquisition_receipt_content_id: str
    completed_possession_at: datetime
    members: tuple[ObservationSnapshotMember, ...] = ()

    def __post_init__(self) -> None:
        for name in ("provider_id", "source_kind", "acquisition_receipt_id"):
            object.__setattr__(self, name, text(getattr(self, name), name))
        if type(self.provider_contract) is not ObservationContractPin:
            raise ObservationError("provider_contract must be ObservationContractPin")
        for name in ("normalized_request_id", "source_content_sha256", "acquisition_receipt_content_id"):
            sha256(getattr(self, name), name)
        object.__setattr__(self, "completed_possession_at", instant(self.completed_possession_at, "completed_possession_at"))
        members = items(self.members, ObservationSnapshotMember, "members")
        if len({m.relative_name for m in members}) != len(members):
            raise ObservationError("duplicate snapshot members")
        object.__setattr__(self, "members", tuple(sorted(members, key=lambda m: m.relative_name)))
        if members:
            from .identity import observation_source_content_id

            if observation_source_content_id(members) != self.source_content_sha256:
                raise ObservationError("inventory does not match source_content_sha256")


@dataclass(frozen=True)
class ObservationCoverage:
    """Content-bound coverage claims, not independently verified completeness.

    Both ranges are closed UTC-microsecond intervals. Completion claims may be
    false: A1 binds them, while the future reader decides admissibility.
    """

    scope: ObservationScope
    provider_contract: ObservationContractPin
    effective_start: datetime
    effective_end: datetime
    knowledge_start: datetime
    knowledge_end: datetime
    normalized_request_id: str
    request_completion_evidence_id: str
    request_pages_complete: bool
    missing_semantics: str
    missing_semantics_content_id: str
    revision_inventory_content_id: str
    revision_inventory_complete: bool

    def __post_init__(self) -> None:
        if type(self.scope) is not ObservationScope or type(self.provider_contract) is not ObservationContractPin:
            raise ObservationError("coverage requires exact scope and provider contract")
        for name in ("effective_start", "effective_end", "knowledge_start", "knowledge_end"):
            object.__setattr__(self, name, instant(getattr(self, name), name))
        if self.effective_start > self.effective_end or self.knowledge_start > self.knowledge_end:
            raise ObservationError("coverage range start must not exceed end")
        for name in ("normalized_request_id", "request_completion_evidence_id",
                     "missing_semantics_content_id", "revision_inventory_content_id"):
            sha256(getattr(self, name), name)
        object.__setattr__(self, "missing_semantics", text(self.missing_semantics, "missing_semantics"))
        for name in ("request_pages_complete", "revision_inventory_complete"):
            if type(getattr(self, name)) is not bool:
                raise ObservationError(f"{name} must be an explicit bool")


@dataclass(frozen=True)
class ObservationBuildIdentityInput:
    """Pure future-build declaration; not a VerifiedObservationBuild."""

    rows: tuple[Observation, ...]
    source_snapshot_ids: tuple[str, ...]
    authority_evidence_ids: tuple[str, ...]
    provider_contracts: tuple[ObservationContractPin, ...]
    normalizations: tuple[ObservationContractPin, ...]
    coverage: ObservationCoverage
    schema_version: str = OBSERVATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != OBSERVATION_SCHEMA_VERSION:
            raise ObservationError("unsupported observation schema version")
        if type(self.coverage) is not ObservationCoverage:
            raise ObservationError("coverage must be ObservationCoverage")
        for name in ("source_snapshot_ids", "authority_evidence_ids"):
            object.__setattr__(self, name, hashes(getattr(self, name), name))
        for name in ("provider_contracts", "normalizations"):
            pins = items(getattr(self, name), ObservationContractPin, name, nonempty=True)
            if len({p.version for p in pins}) != len(pins):
                raise ObservationError(f"duplicate/conflicting {name} version")
            object.__setattr__(self, name, tuple(sorted(pins, key=lambda p: (p.version, p.content_id))))
        from .identity import _ordered_rows

        rows = _ordered_rows(self.rows)
        object.__setattr__(self, "rows", rows)
        if self.coverage.provider_contract not in self.provider_contracts:
            raise ObservationError("coverage provider contract is not pinned")
        evidence = {self.coverage.request_completion_evidence_id,
                    self.coverage.missing_semantics_content_id,
                    self.coverage.revision_inventory_content_id}
        if not evidence.issubset(self.authority_evidence_ids):
            raise ObservationError("coverage evidence is not pinned")
        for row in rows:
            scope = ObservationScope(row.provider_id, row.source_kind, row.entity_id,
                                     row.observation_name, row.dimensions)
            if scope != self.coverage.scope:
                raise ObservationError("row does not match declared coverage scope")
            if not self.coverage.effective_start <= row.event_time <= self.coverage.effective_end:
                raise ObservationError("row outside declared effective coverage")
            if not self.coverage.knowledge_start <= row.known_at <= self.coverage.knowledge_end:
                raise ObservationError("row outside declared knowledge coverage")
            provider = ObservationContractPin(row.provider_contract_version, row.provider_contract_content_id)
            normalizer = ObservationContractPin(row.normalization_version, row.normalization_content_id)
            if provider != self.coverage.provider_contract or provider not in self.provider_contracts:
                raise ObservationError("row provider contract does not match coverage/pins")
            if normalizer not in self.normalizations:
                raise ObservationError("row normalization is not pinned")
            if row.source_snapshot_id not in self.source_snapshot_ids or row.known_at_authority_id not in self.authority_evidence_ids:
                raise ObservationError("row source/known-at authority is not pinned")
