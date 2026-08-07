"""Frozen models of the verified Dataset Catalog snapshot reader
contract (v0.6.0 PR-6).

This module defines the verified reader layer's own contract surface:

- :data:`~market_vault.dataset.dataset_catalog_snapshot_identity.
  DATASET_CATALOG_READER_CONTRACT_VERSION` — the version of the reader
  code contract (defined in the snapshot identity module; it describes
  the reader only and never enters any identity or artifact);
- :class:`DatasetCatalogArtifactValidationError` — the single public
  fail-closed error of the verified Catalog snapshot reader (a subclass
  of :class:`DatasetCatalogError`);
- :class:`DatasetCatalogFileRecord` — the frozen record of one
  ``catalog.json`` byte-facts record from ``manifest.json``;
- :class:`DatasetCatalogSnapshotManifestRecord` — the frozen typed record
  of ``manifest.json`` (exact field set, fixed version fields, real
  non-negative counts, UTC microsecond ``built_at``);
- :class:`DatasetCatalogSnapshotEntryRecord` — one verified snapshot
  entry: the reconstructed typed PR-5 content facts, the recomputed
  content ID, and the parsed non-content observed facts (the recorded
  ``built_at`` and the recorded build-location *text*, never a live
  ``Path`` — the reader treats the location as historical text and never
  reloads or re-verifies the original Dataset);
- :class:`VerifiedDatasetCatalogSnapshot` — the frozen, deeply immutable
  result of one verified Catalog snapshot read. Construction
  independently re-verifies every invariant (fail closed), so a manually
  constructed or ``dataclasses.replace``-modified object can never carry
  inconsistent facts.

Nothing here reads or writes the filesystem. ``snapshot_id``,
``catalog_content_id``, and every version constant are recorded facts
that never enter ``dataset_id``, any Canonical identity, the Sample
Generation identity, or the PR-5 Catalog content identity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .dataset_catalog_identity import catalog_dataset_content_id
from .dataset_catalog_models import (
    DatasetCatalogDatasetFacts,
    DatasetCatalogError,
)
from .dataset_catalog_materialization_models import (
    DATASET_CATALOG_CATALOG_FILENAME,
)
from .dataset_catalog_snapshot_identity import (
    DATASET_CATALOG_MATERIALIZER_VERSION,
    DATASET_CATALOG_READER_CONTRACT_VERSION,
    DATASET_CATALOG_SNAPSHOT_ID_VERSION,
    DATASET_CATALOG_SNAPSHOT_MANIFEST_VERSION,
)
from .encoding import normalize_utc_datetime

__all__ = [
    "DatasetCatalogArtifactValidationError",
    "DatasetCatalogFileRecord",
    "DatasetCatalogSnapshotEntryRecord",
    "DatasetCatalogSnapshotManifestRecord",
    "VerifiedDatasetCatalogSnapshot",
]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class DatasetCatalogArtifactValidationError(DatasetCatalogError):
    """Structured fail-closed failure of the verified Catalog snapshot
    reader.

    Raised for invalid snapshot-directory inputs, symlink / junction /
    reparse rejections, wrong directory names, missing or unexpected
    entries, invalid ``_SUCCESS``, non-canonical or identity-inconsistent
    ``catalog.json`` / ``manifest.json``, catalog byte-fact mismatches,
    snapshot-ID / content-ID / dataset-count tampering, dataset-facts
    tampering, dataset ordering / uniqueness violations, unknown or
    missing JSON fields, BOMs, unsupported versions, invalid recorded
    build-location text, and :class:`VerifiedDatasetCatalogSnapshot`
    self-validation failures.

    Every documented failure of the underlying layers (``DatasetError``
    and its layer subclasses, ``OSError``, ``UnicodeError``, and the
    documented ``TypeError`` / ``ValueError`` / ``KeyError``) is
    converted to this error with its ``__cause__`` preserved; an
    already-raised :class:`DatasetCatalogArtifactValidationError` is
    never double-wrapped. There is no "warn and continue" path and no
    partial result is ever returned.
    """


def _reject_dot_components(path: Path, label: str) -> None:
    for part in path.parts:
        if part in (".", ".."):
            raise DatasetCatalogArtifactValidationError(
                f"{label} must not contain '.' or '..' path components: "
                f"{path!r}"
            )


@dataclass(frozen=True)
class DatasetCatalogFileRecord:
    """The frozen record of ``manifest.json`` ``catalog_file``: the fixed
    relative path (always ``catalog.json``), the real non-negative byte
    size, and the lowercase SHA-256 of the actual ``catalog.json``
    bytes."""

    relative_path: str
    byte_size: int
    sha256: str

    def __post_init__(self) -> None:
        if self.relative_path != DATASET_CATALOG_CATALOG_FILENAME:
            raise DatasetCatalogArtifactValidationError(
                "catalog_file.relative_path must be exactly "
                f"{DATASET_CATALOG_CATALOG_FILENAME!r}, got "
                f"{self.relative_path!r}"
            )
        if type(self.byte_size) is not int or self.byte_size < 0:
            raise DatasetCatalogArtifactValidationError(
                "catalog_file.byte_size must be a real non-negative integer, "
                f"got {self.byte_size!r}"
            )
        if not isinstance(self.sha256, str) or not _SHA256_RE.fullmatch(self.sha256):
            raise DatasetCatalogArtifactValidationError(
                "catalog_file.sha256 must be a 64-character lowercase "
                f"SHA-256 hex string, got {self.sha256!r}"
            )


@dataclass(frozen=True)
class DatasetCatalogSnapshotManifestRecord:
    """The frozen typed record of ``manifest.json`` (exact field set).

    Carries every formal field of the deterministic physical manifest:
    the fixed manifest / snapshot-ID / materializer / builder version
    facts, the snapshot ID, the Catalog content identity, the UTC
    microsecond ``built_at``, the real non-negative dataset count, and
    the exact ``catalog.json`` byte-facts record. Construction validates
    the exact field set contract: every fixed version field must equal
    the current constants, ``snapshot_id`` and ``catalog_content_id``
    must be strict lowercase 64-hex, ``built_at`` must be timezone-aware
    (normalized to UTC microseconds), and ``dataset_count`` must be a
    real non-negative integer."""

    manifest_schema_version: str
    snapshot_id_version: str
    materializer_version: str
    builder_version: str
    snapshot_id: str
    catalog_content_id: str
    built_at: datetime
    dataset_count: int
    catalog_file: DatasetCatalogFileRecord

    def __post_init__(self) -> None:
        if self.manifest_schema_version != DATASET_CATALOG_SNAPSHOT_MANIFEST_VERSION:
            raise DatasetCatalogArtifactValidationError(
                "manifest_schema_version must be "
                f"{DATASET_CATALOG_SNAPSHOT_MANIFEST_VERSION}, got "
                f"{self.manifest_schema_version!r}"
            )
        if self.snapshot_id_version != DATASET_CATALOG_SNAPSHOT_ID_VERSION:
            raise DatasetCatalogArtifactValidationError(
                "snapshot_id_version must be "
                f"{DATASET_CATALOG_SNAPSHOT_ID_VERSION}, got "
                f"{self.snapshot_id_version!r}"
            )
        if self.materializer_version != DATASET_CATALOG_MATERIALIZER_VERSION:
            raise DatasetCatalogArtifactValidationError(
                "materializer_version must be "
                f"{DATASET_CATALOG_MATERIALIZER_VERSION}, got "
                f"{self.materializer_version!r}"
            )
        if not isinstance(self.snapshot_id, str) or not _SHA256_RE.fullmatch(
            self.snapshot_id
        ):
            raise DatasetCatalogArtifactValidationError(
                "snapshot_id must be a 64-character lowercase SHA-256 hex "
                f"string, got {self.snapshot_id!r}"
            )
        if not isinstance(self.catalog_content_id, str) or not _SHA256_RE.fullmatch(
            self.catalog_content_id
        ):
            raise DatasetCatalogArtifactValidationError(
                "catalog_content_id must be a 64-character lowercase "
                f"SHA-256 hex string, got {self.catalog_content_id!r}"
            )
        if not isinstance(self.built_at, datetime) or self.built_at.tzinfo is None:
            raise DatasetCatalogArtifactValidationError(
                "built_at must be a timezone-aware datetime"
            )
        object.__setattr__(
            self,
            "built_at",
            normalize_utc_datetime(self.built_at, "built_at"),
        )
        if type(self.dataset_count) is not int or self.dataset_count < 0:
            raise DatasetCatalogArtifactValidationError(
                "dataset_count must be a real non-negative integer, got "
                f"{self.dataset_count!r}"
            )
        if not isinstance(self.catalog_file, DatasetCatalogFileRecord):
            raise DatasetCatalogArtifactValidationError(
                f"catalog_file must be a DatasetCatalogFileRecord, got "
                f"{type(self.catalog_file).__name__}"
            )


def _validate_recorded_build_path(text: str, dataset_id: str) -> str:
    """Shape contract of the recorded build-location text (historical
    observed location only).

    Requires: a non-empty string; forward-slash representation (no
    backslash); no ``.`` / ``..`` path component; no interior empty
    component (a single leading empty component from the root slash of a
    POSIX absolute path such as ``/tmp/...`` is legal); and the final
    component exactly equal to ``dataset_id``. The text is never
    resolved, stat'ed, checked for existence, or used to reload the
    Dataset: the snapshot must stay self-verifying after the original
    Dataset moved, went offline, was deleted, or after the snapshot was
    relocated to a machine with different path semantics.
    """
    if not isinstance(text, str) or not text:
        raise DatasetCatalogArtifactValidationError(
            "recorded build location must be a non-empty string"
        )
    if "\\" in text:
        raise DatasetCatalogArtifactValidationError(
            "recorded build location must use forward-slash representation, "
            f"got backslash: {text!r}"
        )
    parts = text.split("/")
    if parts and parts[0] == "":
        parts = parts[1:]  # the leading root slash of a POSIX absolute path
    if not parts:
        # "/" is the root directory alone: no location component exists.
        raise DatasetCatalogArtifactValidationError(
            f"recorded build location must carry at least one path "
            f"component: {text!r}"
        )
    if any(part in ("", ".", "..") for part in parts):
        raise DatasetCatalogArtifactValidationError(
            f"recorded build location must not contain empty, '.', or '..' "
            f"path components: {text!r}"
        )
    if parts[-1] != dataset_id:
        raise DatasetCatalogArtifactValidationError(
            "recorded build location final component must equal the "
            f"dataset_id, got {parts[-1]!r}"
        )
    return text


@dataclass(frozen=True)
class DatasetCatalogSnapshotEntryRecord:
    """One verified snapshot entry: the reconstructed typed PR-5 content
    facts, the recomputed content ID, and the parsed non-content observed
    facts (``recorded_built_at`` and the historical ``recorded_build_path``
    text).

    Construction re-validates (fail closed): ``dataset_id`` is strict
    lowercase 64-hex and equals ``dataset_facts.dataset_id``;
    ``content_id`` is strict lowercase 64-hex and is recomputed over the
    facts (a ``dataclasses.replace`` tamper fails); ``recorded_built_at``
    is timezone-aware (normalized to UTC microseconds); and
    ``recorded_build_path`` obeys the recorded-location shape contract
    (never a live ``Path``, never reloaded)."""

    dataset_id: str
    content_id: str
    dataset_facts: DatasetCatalogDatasetFacts
    recorded_built_at: datetime
    recorded_build_path: str

    def __post_init__(self) -> None:
        if not isinstance(self.dataset_id, str) or not _SHA256_RE.fullmatch(
            self.dataset_id
        ):
            raise DatasetCatalogArtifactValidationError(
                "dataset_id must be a 64-character lowercase SHA-256 hex "
                f"string, got {self.dataset_id!r}"
            )
        if not isinstance(self.dataset_facts, DatasetCatalogDatasetFacts):
            raise DatasetCatalogArtifactValidationError(
                f"dataset_facts must be a DatasetCatalogDatasetFacts, got "
                f"{type(self.dataset_facts).__name__}"
            )
        if self.dataset_facts.dataset_id != self.dataset_id:
            raise DatasetCatalogArtifactValidationError(
                "dataset_facts.dataset_id does not match the recorded "
                "dataset_id"
            )
        if not isinstance(self.content_id, str) or not _SHA256_RE.fullmatch(
            self.content_id
        ):
            raise DatasetCatalogArtifactValidationError(
                "content_id must be a 64-character lowercase SHA-256 hex "
                f"string, got {self.content_id!r}"
            )
        expected = catalog_dataset_content_id(self.dataset_facts)
        if self.content_id != expected:
            raise DatasetCatalogArtifactValidationError(
                "content_id does not match the recomputed Catalog content "
                "identity of the dataset_facts"
            )
        if not isinstance(self.recorded_built_at, datetime) or (
            self.recorded_built_at.tzinfo is None
        ):
            raise DatasetCatalogArtifactValidationError(
                "recorded_built_at must be a timezone-aware datetime"
            )
        object.__setattr__(
            self,
            "recorded_built_at",
            normalize_utc_datetime(self.recorded_built_at, "recorded_built_at"),
        )
        object.__setattr__(
            self,
            "recorded_build_path",
            _validate_recorded_build_path(
                self.recorded_build_path, self.dataset_id
            ),
        )


@dataclass(frozen=True)
class VerifiedDatasetCatalogSnapshot:
    """A fully verified immutable Catalog snapshot.

    Produced exclusively by
    :func:`market_vault.dataset.dataset_catalog_reader.
    load_verified_dataset_catalog`; every field is re-validated against
    the actual ``catalog.json`` / ``manifest.json`` / ``_SUCCESS`` bytes
    and the recomputed identities. ``entries`` is the frozen
    ``dataset_id``-sorted tuple of
    :class:`DatasetCatalogSnapshotEntryRecord` records; ``manifest`` is
    the frozen typed :class:`DatasetCatalogSnapshotManifestRecord`;
    ``snapshot_dir`` is the lexically absolute snapshot directory (it
    only describes the location and never enters any identity). The
    recorded build locations inside the entries are historical observed
    location text and are never reloaded or re-verified.

    The model is deeply immutable and carries no mutable dict, no file
    handle, no current time, and no callback. Construction independently
    re-verifies every invariant (fail closed): the reader contract
    version; the snapshot schema / contract / entry / content-ID /
    builder version facts; the snapshot-ID and content-ID formats; the
    dataset count; the manifest record; the entry ordering and
    uniqueness; the ``snapshot_dir`` path contract
    (``snapshot_dir.name == snapshot_id``); and the normalized ``built_at``.
    A manually constructed or ``dataclasses.replace``-modified
    inconsistent object fails closed.
    """

    reader_contract_version: str
    snapshot_schema_version: str
    catalog_contract_version: str
    catalog_entry_schema_version: str
    catalog_content_id_version: str
    builder_version: str
    snapshot_id: str
    catalog_content_id: str
    dataset_count: int
    built_at: datetime
    snapshot_dir: Path
    manifest: DatasetCatalogSnapshotManifestRecord
    entries: tuple

    def __post_init__(self) -> None:
        if self.reader_contract_version != DATASET_CATALOG_READER_CONTRACT_VERSION:
            raise DatasetCatalogArtifactValidationError(
                "reader_contract_version must be "
                f"{DATASET_CATALOG_READER_CONTRACT_VERSION}, got "
                f"{self.reader_contract_version!r}"
            )
        if not isinstance(self.entries, tuple) or not all(
            isinstance(entry, DatasetCatalogSnapshotEntryRecord)
            for entry in self.entries
        ):
            raise DatasetCatalogArtifactValidationError(
                "entries must be a tuple of DatasetCatalogSnapshotEntryRecord "
                f"instances, got {type(self.entries).__name__}"
            )
        ids = [entry.dataset_id for entry in self.entries]
        if ids != sorted(ids):
            raise DatasetCatalogArtifactValidationError(
                "entries must be sorted by dataset_id in ascending order"
            )
        if len(set(ids)) != len(ids):
            raise DatasetCatalogArtifactValidationError(
                "entries must not contain duplicate dataset_id values"
            )
        count = len(self.entries)
        if type(self.dataset_count) is not int or self.dataset_count != count:
            raise DatasetCatalogArtifactValidationError(
                "dataset_count must be recomputed from the entries, got "
                f"{self.dataset_count!r} for {count} entries"
            )
        for name in (
            "snapshot_id",
            "catalog_content_id",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
                raise DatasetCatalogArtifactValidationError(
                    f"{name} must be a 64-character lowercase SHA-256 hex "
                    f"string, got {value!r}"
                )
        if not isinstance(self.manifest, DatasetCatalogSnapshotManifestRecord):
            raise DatasetCatalogArtifactValidationError(
                f"manifest must be a DatasetCatalogSnapshotManifestRecord, "
                f"got {type(self.manifest).__name__}"
            )
        if not isinstance(self.built_at, datetime) or self.built_at.tzinfo is None:
            raise DatasetCatalogArtifactValidationError(
                "built_at must be a timezone-aware datetime"
            )
        object.__setattr__(
            self,
            "built_at",
            normalize_utc_datetime(self.built_at, "built_at"),
        )
        snapshot_dir = self.snapshot_dir
        if not isinstance(snapshot_dir, Path) or not snapshot_dir.is_absolute():
            raise DatasetCatalogArtifactValidationError(
                f"snapshot_dir must be an absolute Path, got {snapshot_dir!r}"
            )
        _reject_dot_components(snapshot_dir, "snapshot_dir")
        if snapshot_dir.name != self.snapshot_id:
            raise DatasetCatalogArtifactValidationError(
                f"snapshot_dir.name must be exactly {self.snapshot_id!r}, got "
                f"{snapshot_dir.name!r}"
            )
        if self.manifest.snapshot_id != self.snapshot_id:
            raise DatasetCatalogArtifactValidationError(
                "manifest.snapshot_id does not match the verified snapshot_id"
            )
        if self.manifest.catalog_content_id != self.catalog_content_id:
            raise DatasetCatalogArtifactValidationError(
                "manifest.catalog_content_id does not match the verified "
                "catalog_content_id"
            )
        if self.manifest.built_at != self.built_at:
            raise DatasetCatalogArtifactValidationError(
                "manifest.built_at does not match the verified built_at"
            )
        if self.manifest.dataset_count != self.dataset_count:
            raise DatasetCatalogArtifactValidationError(
                "manifest.dataset_count does not match the verified "
                "dataset_count"
            )
