"""Frozen data models of the derived-dataset manifest core.

Every model is frozen, validates at construction, and normalizes deterministically
at construction (sorting, deduplication, case/Unicode normalization), so the
identity layer can trust its inputs. No market sample assembly, feature or
label computation, spec-file parsing, split assignment, or Dataset Parquet
export happens here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from .encoding import (
    DATASET_IDENTITY_ENCODING_VERSION,
    DatasetError,
    normalize_nfc,
    normalize_utc_datetime,
    reject_unsafe_text,
)

__all__ = [
    "DATASET_CONTENT_ID_VERSION",
    "DATASET_IDENTITY_ENCODING_VERSION",
    "DATASET_MANIFEST_SCHEMA_VERSION",
    "DATASET_SCHEMA_ID_VERSION",
    "SERIALIZATION_FORMAT_PARQUET",
    "SERIALIZATION_FORMAT_VERSION_PARQUET",
    "SPEC_KIND_FEATURE",
    "SPEC_KIND_LABEL",
    "SPEC_KIND_SPLIT",
    "STATUS_COMPLETE",
    "STATUS_EMPTY",
    "SUPPORTED_LOGICAL_TYPES",
    "CanonicalBuildPin",
    "CompletionEntry",
    "CompletionSummary",
    "DatasetField",
    "DatasetIdentityInput",
    "DatasetManifest",
    "DatasetOutputFile",
    "DatasetSchema",
    "DatasetScope",
    "GapReference",
    "ImplementationPin",
    "SourceSnapshotPin",
    "SpecPin",
]

#: Supported logical scalar types (explicit initial set; no inference).
SUPPORTED_LOGICAL_TYPES = (
    "string",
    "int64",
    "float64",
    "bool",
    "date32",
    "timestamp_us_utc",
)

#: Explicit version constants; changing one changes the identities that
#: reference it.
DATASET_SCHEMA_ID_VERSION = "dataset-logical-schema-v1"
DATASET_CONTENT_ID_VERSION = "dataset-logical-content-v1"
DATASET_MANIFEST_SCHEMA_VERSION = "market-vault-dataset-manifest-v1"

STATUS_COMPLETE = "COMPLETE"
STATUS_EMPTY = "EMPTY"

#: Per-key completion status values.
COMPLETION_STATUSES = ("COMPLETE", "INCOMPLETE", "MISSING")

#: Spec pin kinds.
SPEC_KIND_FEATURE = "FEATURE"
SPEC_KIND_LABEL = "LABEL"
SPEC_KIND_SPLIT = "SPLIT"

#: Declared future-output serialization contract (not proof of written files).
SERIALIZATION_FORMAT_PARQUET = "parquet"
SERIALIZATION_FORMAT_VERSION_PARQUET = "market-vault-dataset-parquet-v1"

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _require_text(
    value, label: str, *, upper: bool = False, lower: bool = False
) -> str:
    """Non-empty NFC-normalized string; control characters and encoding
    separators fail. Optional deterministic case normalization."""
    if not isinstance(value, str):
        raise DatasetError(f"{label} must be a string, got {type(value).__name__}")
    text = normalize_nfc(value).strip()
    if upper:
        text = text.upper()
    if lower:
        text = text.lower()
    if not text:
        raise DatasetError(f"{label} must not be empty")
    reject_unsafe_text(text, label)
    return text


def _normalize_sha256(value, label: str) -> str:
    """Normalize one SHA-256 hex string to lowercase 64 characters."""
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise DatasetError(
            f"{label} must be a 64-character SHA-256 hex string, got {value!r}"
        )
    return value.lower()


def _normalize_trade_date(value, label: str = "trade date") -> date:
    """date, datetime (converted to its date), or ISO string -> date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise DatasetError(f"invalid {label}: {value!r}") from exc
    raise DatasetError(f"invalid {label}: {value!r}")


def _require_int_non_negative(value, label: str) -> None:
    if type(value) is not int or value < 0:
        raise DatasetError(f"{label} must be a non-negative integer")


@dataclass(frozen=True)
class DatasetField:
    """One explicit logical field of a derived dataset schema."""

    name: str
    logical_type: str
    nullable: bool

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise DatasetError(
                f"field name must be a string, got {type(self.name).__name__}"
            )
        name = normalize_nfc(self.name)
        if not name:
            raise DatasetError("field name must not be empty")
        reject_unsafe_text(name, "field name")
        object.__setattr__(self, "name", name)
        if self.logical_type not in SUPPORTED_LOGICAL_TYPES:
            raise DatasetError(
                f"unsupported logical type {self.logical_type!r}; supported: "
                + ", ".join(SUPPORTED_LOGICAL_TYPES)
            )
        if type(self.nullable) is not bool:
            raise DatasetError("field nullable must be a real bool")


@dataclass(frozen=True)
class DatasetSchema:
    """Explicit logical table schema; field order is authoritative and
    participates in ``dataset_schema_id``."""

    fields: tuple[DatasetField, ...]

    def __post_init__(self) -> None:
        fields = tuple(self.fields)
        for field in fields:
            if not isinstance(field, DatasetField):
                raise DatasetError(
                    f"schema fields must be DatasetField instances, "
                    f"got {type(field).__name__}"
                )
        names = [field.name for field in fields]
        if len(set(names)) != len(names):
            raise DatasetError("duplicate field names are rejected")
        object.__setattr__(self, "fields", fields)


@dataclass(frozen=True)
class DatasetScope:
    """Explicit normalized dataset scope.

    Symbols are stripped, uppercase-normalized, deduplicated, and sorted;
    trade dates are validated, deduplicated, and sorted; interval is
    lowercase-normalized; adjustment and requested_session are uppercase
    normalized; an empty scope fails; control characters and encoding
    separators fail.
    """

    symbols: tuple[str, ...]
    trade_dates: tuple[date, ...]
    adjustment: str
    interval: str
    requested_session: str

    def __post_init__(self) -> None:
        symbols = tuple(
            sorted({_require_text(value, "symbol", upper=True) for value in self.symbols})
        )
        trade_dates = tuple(sorted({_normalize_trade_date(value) for value in self.trade_dates}))
        if not symbols:
            raise DatasetError("scope must contain at least one symbol")
        if not trade_dates:
            raise DatasetError("scope must contain at least one trade date")
        object.__setattr__(self, "symbols", symbols)
        object.__setattr__(self, "trade_dates", trade_dates)
        object.__setattr__(self, "adjustment", _require_text(self.adjustment, "adjustment", upper=True))
        object.__setattr__(self, "interval", _require_text(self.interval, "interval", lower=True))
        object.__setattr__(self, "requested_session", _require_text(self.requested_session, "requested_session", upper=True))


@dataclass(frozen=True)
class SourceSnapshotPin:
    """Stable path-independent provenance of one physical source snapshot.

    ``snapshot_file`` and ``created_at`` are deliberately excluded: relocated
    byte-identical files and wall-clock facts must never participate in
    identities.
    """

    ingestion_run_id: str
    physical_snapshot_hash: str
    logical_source_rows_hash: str
    source_schema_version: str
    requested_trade_date: date
    requested_session: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "ingestion_run_id", _require_text(self.ingestion_run_id, "ingestion_run_id"))
        object.__setattr__(self, "physical_snapshot_hash", _normalize_sha256(self.physical_snapshot_hash, "physical_snapshot_hash"))
        object.__setattr__(self, "logical_source_rows_hash", _normalize_sha256(self.logical_source_rows_hash, "logical_source_rows_hash"))
        object.__setattr__(self, "source_schema_version", _require_text(self.source_schema_version, "source_schema_version"))
        object.__setattr__(self, "requested_trade_date", _normalize_trade_date(self.requested_trade_date, "requested_trade_date"))
        object.__setattr__(self, "requested_session", _require_text(self.requested_session, "requested_session", upper=True))

    @property
    def stable_identity(self) -> tuple:
        """Path-independent stable identity used for deduplication."""
        return (
            self.ingestion_run_id,
            self.physical_snapshot_hash,
            self.logical_source_rows_hash,
            self.source_schema_version,
            self.requested_trade_date,
            self.requested_session,
        )


@dataclass(frozen=True)
class CanonicalBuildPin:
    """Pin to one immutable Canonical build and its stable identities.

    Paths and ``created_at`` are excluded. All SHA-256 values are normalized
    to lowercase 64-character hex; canonical row-version IDs are deduplicated
    and sorted; source snapshot pins are deduplicated by stable identity and
    deterministically sorted; ``status`` accepts COMPLETE or EMPTY only, and
    an EMPTY pin must have zero row-version IDs. The caller constructs pins
    from a previously verified Canonical manifest; this core never reads
    Canonical files.
    """

    canonical_build_id: str
    canonical_content_id: str
    canonical_builder_version: str
    canonical_schema_version: str
    materializer_version: str
    gap_policy_version: str
    gap_content_id: str
    status: str
    canonical_row_version_ids: tuple[str, ...]
    source_snapshots: tuple[SourceSnapshotPin, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "canonical_build_id", _normalize_sha256(self.canonical_build_id, "canonical_build_id"))
        object.__setattr__(self, "canonical_content_id", _normalize_sha256(self.canonical_content_id, "canonical_content_id"))
        object.__setattr__(self, "canonical_builder_version", _require_text(self.canonical_builder_version, "canonical_builder_version"))
        object.__setattr__(self, "canonical_schema_version", _require_text(self.canonical_schema_version, "canonical_schema_version"))
        object.__setattr__(self, "materializer_version", _require_text(self.materializer_version, "materializer_version"))
        object.__setattr__(self, "gap_policy_version", _require_text(self.gap_policy_version, "gap_policy_version"))
        object.__setattr__(self, "gap_content_id", _normalize_sha256(self.gap_content_id, "gap_content_id"))
        if self.status not in (STATUS_COMPLETE, STATUS_EMPTY):
            raise DatasetError(
                f"canonical build pin status must be COMPLETE or EMPTY, got {self.status!r}"
            )
        row_versions = tuple(
            sorted({_normalize_sha256(value, "canonical row version id") for value in self.canonical_row_version_ids})
        )
        if self.status == STATUS_EMPTY and row_versions:
            raise DatasetError("an EMPTY canonical build pin must have zero row-version IDs")
        object.__setattr__(self, "canonical_row_version_ids", row_versions)
        snapshots = tuple(self.source_snapshots)
        for snapshot in snapshots:
            if not isinstance(snapshot, SourceSnapshotPin):
                raise DatasetError(
                    f"source snapshots must be SourceSnapshotPin instances, "
                    f"got {type(snapshot).__name__}"
                )
        # Deduplicate by stable identity (documented rule) and sort
        # deterministically by stable identity.
        deduped: list[SourceSnapshotPin] = []
        seen: set = set()
        for snapshot in sorted(snapshots, key=lambda item: item.stable_identity):
            if snapshot.stable_identity in seen:
                continue
            seen.add(snapshot.stable_identity)
            deduped.append(snapshot)
        object.__setattr__(self, "source_snapshots", tuple(deduped))


@dataclass(frozen=True)
class SpecPin:
    """Fingerprint of a versioned Feature, Label, or Split spec.

    Spec files are not parsed and transforms are not executed by this core;
    the pins simply record kind, name, version, and content hash so future
    implementations can use them.
    """

    kind: str
    name: str
    version: str
    content_sha256: str

    def __post_init__(self) -> None:
        if self.kind not in (SPEC_KIND_FEATURE, SPEC_KIND_LABEL, SPEC_KIND_SPLIT):
            raise DatasetError(
                f"spec pin kind must be FEATURE, LABEL, or SPLIT, got {self.kind!r}"
            )
        object.__setattr__(self, "name", _require_text(self.name, "spec name"))
        object.__setattr__(self, "version", _require_text(self.version, "spec version"))
        object.__setattr__(self, "content_sha256", _normalize_sha256(self.content_sha256, "spec content_sha256"))


@dataclass(frozen=True)
class ImplementationPin:
    """Fingerprint of one transform implementation (future contracts)."""

    name: str
    version: str
    content_sha256: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_text(self.name, "implementation name"))
        object.__setattr__(self, "version", _require_text(self.version, "implementation version"))
        if self.content_sha256 is not None:
            object.__setattr__(self, "content_sha256", _normalize_sha256(self.content_sha256, "implementation content_sha256"))


@dataclass(frozen=True)
class CompletionEntry:
    """One per-key completion status entry (stable reason codes only)."""

    code: str
    trade_date: date
    status: str
    reason_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _require_text(self.code, "completion code", upper=True))
        object.__setattr__(self, "trade_date", _normalize_trade_date(self.trade_date, "completion trade date"))
        if self.status not in COMPLETION_STATUSES:
            raise DatasetError(
                f"completion status must be one of {', '.join(COMPLETION_STATUSES)}, got {self.status!r}"
            )
        if self.reason_code is not None:
            object.__setattr__(self, "reason_code", _require_text(self.reason_code, "completion reason code"))


@dataclass(frozen=True)
class CompletionSummary:
    """Deterministic per-key completion summary.

    Counts must equal the actual entries; duplicate (code, trade date) keys
    fail; entries are canonically ordered by (code, trade date); unknown
    status values fail.
    """

    complete_count: int
    incomplete_count: int
    missing_count: int
    entries: tuple[CompletionEntry, ...]

    def __post_init__(self) -> None:
        for name, value in (
            ("complete_count", self.complete_count),
            ("incomplete_count", self.incomplete_count),
            ("missing_count", self.missing_count),
        ):
            _require_int_non_negative(value, name)
        entries = tuple(self.entries)
        for entry in entries:
            if not isinstance(entry, CompletionEntry):
                raise DatasetError(
                    f"completion entries must be CompletionEntry instances, "
                    f"got {type(entry).__name__}"
                )
        entries = tuple(sorted(entries, key=lambda entry: (entry.code, entry.trade_date)))
        seen: set[tuple] = set()
        for entry in entries:
            key = (entry.code, entry.trade_date)
            if key in seen:
                raise DatasetError(
                    f"duplicate completion key ({entry.code}, {entry.trade_date.isoformat()})"
                )
            seen.add(key)
        actual = {
            "COMPLETE": sum(1 for entry in entries if entry.status == "COMPLETE"),
            "INCOMPLETE": sum(1 for entry in entries if entry.status == "INCOMPLETE"),
            "MISSING": sum(1 for entry in entries if entry.status == "MISSING"),
        }
        declared = {
            "COMPLETE": self.complete_count,
            "INCOMPLETE": self.incomplete_count,
            "MISSING": self.missing_count,
        }
        if actual != declared:
            raise DatasetError(
                f"completion counts must equal the actual entries: declared {declared}, actual {actual}"
            )
        object.__setattr__(self, "entries", entries)


@dataclass(frozen=True)
class GapReference:
    """Reference to one pinned Canonical build's gap sidecar.

    Gap Parquet contents are never duplicated into the Dataset manifest.
    """

    canonical_build_id: str
    gap_content_id: str
    gap_range_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "canonical_build_id", _normalize_sha256(self.canonical_build_id, "gap reference canonical_build_id"))
        object.__setattr__(self, "gap_content_id", _normalize_sha256(self.gap_content_id, "gap reference gap_content_id"))
        _require_int_non_negative(self.gap_range_count, "gap_range_count")


@dataclass(frozen=True)
class DatasetOutputFile:
    """Immutable record of one output file (recorded fact; hashes never
    enter ``dataset_id``). Safe relative POSIX paths only."""

    relative_path: str
    file_role: str
    row_count: int
    byte_size: int
    sha256: str
    content_role: str

    def __post_init__(self) -> None:
        path = _require_text(self.relative_path, "output relative_path")
        if path.startswith("/") or "\\" in path:
            raise DatasetError(f"unsafe output relative_path {path!r}")
        parts = path.split("/")
        if not parts or any(part in ("", ".", "..") for part in parts):
            raise DatasetError(f"unsafe output relative_path {path!r}")
        object.__setattr__(self, "relative_path", path)
        object.__setattr__(self, "file_role", _require_text(self.file_role, "output file_role"))
        _require_int_non_negative(self.row_count, "output row_count")
        _require_int_non_negative(self.byte_size, "output byte_size")
        object.__setattr__(self, "sha256", _normalize_sha256(self.sha256, "output sha256"))
        object.__setattr__(self, "content_role", _require_text(self.content_role, "output content_role"))


@dataclass(frozen=True)
class DatasetIdentityInput:
    """All identity-bearing inputs of one derived dataset.

    ``dataset_id`` is a versioned SHA-256 over these normalized fields only.
    ``manifest_schema_version``, ``serialization_format``, and
    ``serialization_format_version`` default to the current constants and may
    be overridden explicitly so schema/format changes are visible in
    ``dataset_id``. ``dataset_schema_id`` must match
    ``dataset_schema_id(schema)`` and cross-field consistency (duplicate
    pins, row-version coverage, gap references) is validated by
    :func:`market_vault.dataset.identity.dataset_id`.
    """

    dataset_kind: str
    scope: DatasetScope
    dataset_as_of: datetime | None
    schema: DatasetSchema
    dataset_schema_id: str
    logical_dataset_content_id: str
    canonical_builds: tuple[CanonicalBuildPin, ...]
    canonical_row_version_ids: tuple[str, ...]
    feature_specs: tuple[SpecPin, ...]
    label_specs: tuple[SpecPin, ...]
    split_spec: SpecPin | None
    implementations: tuple[ImplementationPin, ...]
    completion: CompletionSummary
    gap_references: tuple[GapReference, ...]
    manifest_schema_version: str = DATASET_MANIFEST_SCHEMA_VERSION
    serialization_format: str = SERIALIZATION_FORMAT_PARQUET
    serialization_format_version: str = SERIALIZATION_FORMAT_VERSION_PARQUET

    def __post_init__(self) -> None:
        object.__setattr__(self, "dataset_kind", _require_text(self.dataset_kind, "dataset_kind"))
        if not isinstance(self.scope, DatasetScope):
            raise DatasetError(
                f"scope must be a DatasetScope, got {type(self.scope).__name__}"
            )
        if self.dataset_as_of is not None:
            object.__setattr__(self, "dataset_as_of", normalize_utc_datetime(self.dataset_as_of, "dataset_as_of"))
        if not isinstance(self.schema, DatasetSchema):
            raise DatasetError(
                f"schema must be a DatasetSchema, got {type(self.schema).__name__}"
            )
        object.__setattr__(self, "dataset_schema_id", _normalize_sha256(self.dataset_schema_id, "dataset_schema_id"))
        object.__setattr__(self, "logical_dataset_content_id", _normalize_sha256(self.logical_dataset_content_id, "logical_dataset_content_id"))

        builds = tuple(self.canonical_builds)
        for pin in builds:
            if not isinstance(pin, CanonicalBuildPin):
                raise DatasetError(
                    f"canonical_builds must contain CanonicalBuildPin instances, "
                    f"got {type(pin).__name__}"
                )
        object.__setattr__(self, "canonical_builds", tuple(sorted(builds, key=lambda pin: pin.canonical_build_id)))

        row_versions = tuple(
            sorted({_normalize_sha256(value, "canonical row version id") for value in self.canonical_row_version_ids})
        )
        object.__setattr__(self, "canonical_row_version_ids", row_versions)

        def _specs(values, label):
            items = tuple(values)
            for item in items:
                if not isinstance(item, SpecPin):
                    raise DatasetError(f"{label} must contain SpecPin instances, got {type(item).__name__}")
            return tuple(sorted(items, key=lambda item: (item.kind, item.name, item.version)))

        object.__setattr__(self, "feature_specs", _specs(self.feature_specs, "feature_specs"))
        object.__setattr__(self, "label_specs", _specs(self.label_specs, "label_specs"))
        if self.split_spec is not None and not isinstance(self.split_spec, SpecPin):
            raise DatasetError(
                f"split_spec must be a SpecPin or None, got {type(self.split_spec).__name__}"
            )

        implementations = tuple(self.implementations)
        for item in implementations:
            if not isinstance(item, ImplementationPin):
                raise DatasetError(
                    f"implementations must contain ImplementationPin instances, "
                    f"got {type(item).__name__}"
                )
        object.__setattr__(
            self,
            "implementations",
            tuple(sorted(implementations, key=lambda item: (item.name, item.version))),
        )

        if not isinstance(self.completion, CompletionSummary):
            raise DatasetError(
                f"completion must be a CompletionSummary, got {type(self.completion).__name__}"
            )

        gap_references = tuple(self.gap_references)
        for ref in gap_references:
            if not isinstance(ref, GapReference):
                raise DatasetError(
                    f"gap_references must contain GapReference instances, "
                    f"got {type(ref).__name__}"
                )
        # Identical duplicate gap references are deduplicated (documented rule).
        deduped: list[GapReference] = []
        seen: set[tuple] = set()
        for ref in sorted(gap_references, key=lambda item: (item.canonical_build_id, item.gap_content_id)):
            identity = (ref.canonical_build_id, ref.gap_content_id, ref.gap_range_count)
            if identity in seen:
                continue
            seen.add(identity)
            deduped.append(ref)
        object.__setattr__(self, "gap_references", tuple(deduped))

        object.__setattr__(self, "manifest_schema_version", _require_text(self.manifest_schema_version, "manifest_schema_version"))
        object.__setattr__(self, "serialization_format", _require_text(self.serialization_format, "serialization_format", lower=True))
        object.__setattr__(self, "serialization_format_version", _require_text(self.serialization_format_version, "serialization_format_version"))


@dataclass(frozen=True)
class DatasetManifest:
    """Versioned derived-dataset manifest.

    ``dataset_id`` is recomputed from the identity-bearing fields; ``built_at``
    and output-file facts (byte hashes) are recorded but never enter
    ``dataset_id``. Status EMPTY requires ``logical_row_count == 0``; status
    COMPLETE requires at least one logical row. Output file records are
    validated and deterministically sorted by relative path.
    """

    manifest_schema_version: str
    dataset_id: str
    dataset_kind: str
    status: str
    built_at: datetime
    dataset_as_of: datetime | None
    logical_dataset_content_id: str
    dataset_schema_id: str
    schema: DatasetSchema
    scope: DatasetScope
    canonical_builds: tuple[CanonicalBuildPin, ...]
    canonical_row_version_ids: tuple[str, ...]
    feature_specs: tuple[SpecPin, ...]
    label_specs: tuple[SpecPin, ...]
    split_spec: SpecPin | None
    implementations: tuple[ImplementationPin, ...]
    completion: CompletionSummary
    gap_references: tuple[GapReference, ...]
    serialization_format: str
    serialization_format_version: str
    logical_row_count: int
    output_files: tuple[DatasetOutputFile, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest_schema_version", _require_text(self.manifest_schema_version, "manifest_schema_version"))
        object.__setattr__(self, "dataset_id", _normalize_sha256(self.dataset_id, "dataset_id"))
        object.__setattr__(self, "dataset_kind", _require_text(self.dataset_kind, "dataset_kind"))
        if self.status not in (STATUS_COMPLETE, STATUS_EMPTY):
            raise DatasetError(f"manifest status must be COMPLETE or EMPTY, got {self.status!r}")
        object.__setattr__(self, "built_at", normalize_utc_datetime(self.built_at, "built_at"))
        if self.dataset_as_of is not None:
            object.__setattr__(self, "dataset_as_of", normalize_utc_datetime(self.dataset_as_of, "dataset_as_of"))
        object.__setattr__(self, "logical_dataset_content_id", _normalize_sha256(self.logical_dataset_content_id, "logical_dataset_content_id"))
        object.__setattr__(self, "dataset_schema_id", _normalize_sha256(self.dataset_schema_id, "dataset_schema_id"))
        _require_int_non_negative(self.logical_row_count, "logical_row_count")
        if self.status == STATUS_EMPTY and self.logical_row_count != 0:
            raise DatasetError("status EMPTY requires logical_row_count == 0")
        if self.status == STATUS_COMPLETE and self.logical_row_count == 0:
            raise DatasetError("status COMPLETE requires at least one logical row; zero rows must be EMPTY")
        if not isinstance(self.schema, DatasetSchema):
            raise DatasetError(
                f"manifest schema must be a DatasetSchema, got {type(self.schema).__name__}"
            )
        if not isinstance(self.scope, DatasetScope):
            raise DatasetError(
                f"manifest scope must be a DatasetScope, got {type(self.scope).__name__}"
            )
        if not isinstance(self.completion, CompletionSummary):
            raise DatasetError(
                f"manifest completion must be a CompletionSummary, "
                f"got {type(self.completion).__name__}"
            )
        object.__setattr__(self, "serialization_format", _require_text(self.serialization_format, "serialization_format", lower=True))
        object.__setattr__(self, "serialization_format_version", _require_text(self.serialization_format_version, "serialization_format_version"))

        builds = tuple(self.canonical_builds)
        for pin in builds:
            if not isinstance(pin, CanonicalBuildPin):
                raise DatasetError(
                    f"manifest canonical_builds must contain CanonicalBuildPin instances, "
                    f"got {type(pin).__name__}"
                )
        object.__setattr__(self, "canonical_builds", tuple(sorted(builds, key=lambda pin: pin.canonical_build_id)))

        row_versions = tuple(
            sorted({_normalize_sha256(value, "canonical row version id") for value in self.canonical_row_version_ids})
        )
        object.__setattr__(self, "canonical_row_version_ids", row_versions)

        def _specs(values, label):
            items = tuple(values)
            for item in items:
                if not isinstance(item, SpecPin):
                    raise DatasetError(f"manifest {label} must contain SpecPin instances, got {type(item).__name__}")
            return tuple(sorted(items, key=lambda item: (item.kind, item.name, item.version)))

        object.__setattr__(self, "feature_specs", _specs(self.feature_specs, "feature_specs"))
        object.__setattr__(self, "label_specs", _specs(self.label_specs, "label_specs"))
        if self.split_spec is not None and not isinstance(self.split_spec, SpecPin):
            raise DatasetError(
                f"manifest split_spec must be a SpecPin or None, got {type(self.split_spec).__name__}"
            )

        implementations = tuple(self.implementations)
        for item in implementations:
            if not isinstance(item, ImplementationPin):
                raise DatasetError(
                    f"manifest implementations must contain ImplementationPin instances, "
                    f"got {type(item).__name__}"
                )
        object.__setattr__(
            self,
            "implementations",
            tuple(sorted(implementations, key=lambda item: (item.name, item.version))),
        )

        gap_references = tuple(self.gap_references)
        for ref in gap_references:
            if not isinstance(ref, GapReference):
                raise DatasetError(
                    f"manifest gap_references must contain GapReference instances, "
                    f"got {type(ref).__name__}"
                )
        # Identical duplicate gap references are deduplicated (documented rule).
        deduped: list[GapReference] = []
        seen: set[tuple] = set()
        for ref in sorted(gap_references, key=lambda item: (item.canonical_build_id, item.gap_content_id)):
            identity = (ref.canonical_build_id, ref.gap_content_id, ref.gap_range_count)
            if identity in seen:
                continue
            seen.add(identity)
            deduped.append(ref)
        object.__setattr__(self, "gap_references", tuple(deduped))

        output_files = tuple(self.output_files)
        for record in output_files:
            if not isinstance(record, DatasetOutputFile):
                raise DatasetError(
                    f"output_files must contain DatasetOutputFile instances, "
                    f"got {type(record).__name__}"
                )
        paths = [record.relative_path for record in output_files]
        if len(set(paths)) != len(paths):
            raise DatasetError("duplicate output file relative_path")
        object.__setattr__(
            self,
            "output_files",
            tuple(sorted(output_files, key=lambda record: record.relative_path)),
        )
