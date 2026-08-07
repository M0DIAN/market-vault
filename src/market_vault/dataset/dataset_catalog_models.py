"""Frozen typed models of the v0.6.0 Dataset Catalog contract foundation
(PR-5).

Every model is frozen, validates at construction, and normalizes
deterministically at construction (lowercase SHA-256 text, NFC +
deterministic-strip + unsafe-text rejection for raw identity text,
deterministic sorting under the existing Dataset identity business keys,
UTC microsecond instants, typed nested models), so the metadata
projection and the Catalog content identity layer can trust their
inputs. All failures raise the unified :class:`DatasetCatalogError` (a
subclass of :class:`DatasetError`); unknown, future, or old schema
versions fail closed and are never "best-effort" interpreted.

Normalization semantics follow the existing Dataset identity contract:

- set-like facts (canonical row-version IDs) are normalized and
  deduplicated as a set;
- structures with a business unique key (SpecPins under
  ``(kind, name, version)``, CanonicalBuildPins under
  ``canonical_build_id``, Completion entries under their key) are sorted
  deterministically and fail closed on duplicate or conflicting entries;
  conflicting entries are never silently deduplicated;
- iterable container input is accepted and frozen into an immutable
  tuple at the formal construction boundary; the model never stores a
  mutable container, and untyped / invalid element payloads fail closed.

The contract split is structural:

- :class:`DatasetCatalogDatasetFacts` — identity-bearing, normalized,
  verified Dataset facts only. These facts are the exact inputs of the
  Catalog content identity; nothing else may ever enter it. The
  Catalog-level ``canonical_row_version_ids`` must be a subset of the
  pinned Canonical builds' row versions, exactly like the existing
  ``DatasetIdentityInput`` contract; a pin may declare more row versions
  than the Dataset-level list uses.
- :class:`DatasetCatalogObservedMetadata` — non-content observed
  metadata only (``built_at`` and the Dataset build location). The two
  types are disjoint by construction: no field of the observed-metadata
  type exists on the facts type, so ``built_at`` / location facts can
  never be accidentally mixed into the content identity. The content ID
  binds only the facts: a legal observed-metadata change (a different
  ``built_at`` or a move to another parent directory) never changes it;
  invalid metadata shape or a ``build_path`` basename that does not
  equal ``dataset_id`` fails closed.
- :class:`DatasetCatalogEntry` — the projection result combining one
  facts object with one observed-metadata object; it carries the
  self-validated content ID of its facts and recomputes it at
  construction (and therefore after any ``dataclasses.replace``
  tampering), and it binds the metadata location to the facts'
  ``dataset_id``.

This module contains only version constants, the error type, and frozen
models with construction-time normalization and validation. It never
reads files, never scans directories, never calls
``load_verified_dataset``, never accesses the network, never loads
settings, and never uses the current time; the projection entry point
lives in :mod:`market_vault.dataset.dataset_catalog_projection`. The
physical Catalog snapshot builder, materializer, and verified reader are
PR-6 and are not implemented here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .encoding import (
    DatasetError,
    normalize_nfc,
    normalize_utc_datetime,
    reject_unsafe_text,
)
from .models import (
    SPEC_KIND_FEATURE,
    SPEC_KIND_LABEL,
    SPEC_KIND_SPLIT,
    STATUS_COMPLETE,
    STATUS_EMPTY,
    CanonicalBuildPin,
    CompletionSummary,
    DatasetScope,
    SpecPin,
)

__all__ = [
    "DATASET_CATALOG_CONTRACT_VERSION",
    "DATASET_CATALOG_CONTENT_ID_VERSION",
    "DATASET_CATALOG_ENTRY_SCHEMA_VERSION",
    "DatasetCatalogDatasetFacts",
    "DatasetCatalogEntry",
    "DatasetCatalogError",
    "DatasetCatalogObservedMetadata",
]

#: Version of the whole Dataset Catalog contract (frozen models, strict
#: entry schema, normalization, metadata projection, and content identity).
#: Changing it changes every Catalog content identity that references it.
DATASET_CATALOG_CONTRACT_VERSION = "market-vault-dataset-catalog-contract-v1"

#: Version of the frozen :class:`DatasetCatalogEntry` schema (the
#: identity-bearing facts record). Changing it changes every per-Dataset
#: content digest and therefore every Catalog content identity.
DATASET_CATALOG_ENTRY_SCHEMA_VERSION = "market-vault-dataset-catalog-entry-v1"

#: Version of the deterministic Catalog content identity
#: (:func:`market_vault.dataset.dataset_catalog_identity.dataset_catalog_content_id`).
#: Changing it changes every Catalog content identity.
DATASET_CATALOG_CONTENT_ID_VERSION = "market-vault-dataset-catalog-content-v1"

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class DatasetCatalogError(DatasetError):
    """Structured fail-closed failure of the Dataset Catalog contract layer
    (v0.6.0 PR-5).

    Raised for every invalid contract input: unsupported contract versions,
    invalid frozen models, invalid SHA-256 IDs, wrong pin kinds, duplicate
    conflicting facts, scope inconsistencies, malformed datetimes, and
    content-ID mismatches. Low-level documented validation exceptions
    (``DatasetError``, ``TypeError``, ``ValueError``, ``KeyError``) are
    always converted to this error; broad ``except Exception`` is never
    used and programming errors are never hidden.
    """


def _normalize_sha256(value, label: str) -> str:
    if not isinstance(value, str):
        raise DatasetCatalogError(
            f"{label} must be a 64-character lowercase SHA-256 hex string, "
            f"got {type(value).__name__}"
        )
    normalized = value.lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise DatasetCatalogError(
            f"{label} must be a 64-character lowercase SHA-256 hex string, "
            f"got {value!r}"
        )
    return normalized


def _require_text(value, label: str) -> str:
    """Formal identity text under the existing Dataset encoding contract:
    a string that is NFC-normalized, deterministically stripped, and free
    of control characters and reserved encoding separators. The raw input
    is never accepted; the normalized text is what enters the Catalog
    content identity."""
    if not isinstance(value, str):
        raise DatasetCatalogError(f"{label} must be a string, got {type(value).__name__}")
    text = normalize_nfc(value).strip()
    if not text:
        raise DatasetCatalogError(f"{label} must not be empty")
    try:
        reject_unsafe_text(text, label)
    except DatasetError as exc:
        raise DatasetCatalogError(str(exc)) from exc
    return text


def _freeze_tuple(values, label: str) -> tuple:
    """Safe container freeze at the formal construction boundary.

    Iterable container input is accepted and frozen into an immutable
    tuple; a non-iterable formal input is converted to
    :class:`DatasetCatalogError` (never a raw ``TypeError``). The frozen
    tuple is what the model keeps; no mutable container is ever stored.
    """
    try:
        return tuple(values)
    except TypeError as exc:
        raise DatasetCatalogError(
            f"{label} must be an iterable of typed values, got "
            f"{type(values).__name__}"
        ) from exc


def _require_non_negative_int(value, label: str) -> int:
    if type(value) is not int or value < 0:
        raise DatasetCatalogError(
            f"{label} must be a real non-negative integer, got {value!r}"
        )
    return value


def _normalize_instant(value, label: str) -> datetime:
    """Timezone-aware instant normalized to UTC microseconds; naive fails."""
    if not isinstance(value, datetime):
        raise DatasetCatalogError(
            f"{label} must be a timezone-aware datetime, got {type(value).__name__}"
        )
    if value.tzinfo is None:
        raise DatasetCatalogError(
            f"{label} must be timezone-aware, got a naive datetime"
        )
    try:
        return normalize_utc_datetime(value, label)
    except DatasetError as exc:
        raise DatasetCatalogError(str(exc)) from exc


def _normalize_spec_pins(values, expected_kind: str, label: str) -> tuple:
    """Spec pins under the existing Dataset identity contract: every pin
    must be a SpecPin of the expected kind; ``(kind, name, version)`` is
    the business duplicate key — the same key with the same content hash
    is a duplicate and the same key with a different content hash is a
    conflicting duplicate; both fail closed and are never silently
    deduplicated. Pins are deterministically sorted by
    ``(kind, name, version, content_sha256)`` (the content hash is a
    stable tie-breaker only and never part of the business key)."""
    pins = _freeze_tuple(values, label)
    for pin in pins:
        if not isinstance(pin, SpecPin):
            raise DatasetCatalogError(
                f"{label} must contain SpecPin instances, got "
                f"{type(pin).__name__}"
            )
        if pin.kind != expected_kind:
            raise DatasetCatalogError(
                f"{label} pin {pin.name!r} has kind {pin.kind!r}, expected "
                f"{expected_kind}"
            )
    ordered = tuple(
        sorted(
            pins,
            key=lambda pin: (pin.kind, pin.name, pin.version, pin.content_sha256),
        )
    )
    seen: set[tuple] = set()
    for pin in ordered:
        key = (pin.kind, pin.name, pin.version)
        if key in seen:
            raise DatasetCatalogError(
                f"{label} must not contain duplicate or conflicting pins for "
                f"({pin.kind}, {pin.name!r}, {pin.version!r})"
            )
        seen.add(key)
    return ordered


def _normalize_canonical_build_pins(values) -> tuple:
    pins = _freeze_tuple(values, "canonical_build_pins")
    for pin in pins:
        if not isinstance(pin, CanonicalBuildPin):
            raise DatasetCatalogError(
                "canonical_build_pins must contain CanonicalBuildPin "
                f"instances, got {type(pin).__name__}"
            )
    ordered = tuple(sorted(pins, key=lambda pin: pin.canonical_build_id))
    ids = [pin.canonical_build_id for pin in ordered]
    if len(set(ids)) != len(ids):
        raise DatasetCatalogError(
            "canonical_build_pins must not contain duplicate canonical_build_id "
            "values"
        )
    return ordered


def _normalize_row_version_ids(values) -> tuple:
    ids = tuple(
        sorted(
            {
                _normalize_sha256(value, "canonical row version id")
                for value in _freeze_tuple(values, "canonical_row_version_ids")
            }
        )
    )
    return ids


def _validate_completion_scope(completion: CompletionSummary, scope: DatasetScope) -> None:
    """Cross-check: every completion entry key must be inside the scope.

    The completion summary is already normalized by its own model; this
    check binds it to the scope facts so a tampered or inconsistent
    completion can never pass as verified facts.
    """
    symbols = set(scope.symbols)
    trade_dates = set(scope.trade_dates)
    for entry in completion.entries:
        if entry.code not in symbols:
            raise DatasetCatalogError(
                f"completion entry code {entry.code!r} is not in the scope "
                "symbols"
            )
        if entry.trade_date not in trade_dates:
            raise DatasetCatalogError(
                f"completion entry trade date {entry.trade_date} is not in "
                "the scope trade dates"
            )


def _validate_row_version_coverage(
    canonical_build_pins: tuple, canonical_row_version_ids: tuple
) -> None:
    """Cross-check: every Catalog-level canonical row-version ID must be
    covered by the pinned Canonical builds.

    This is exactly the existing Dataset identity contract direction
    (:func:`market_vault.dataset.identity.normalize_dataset_identity_input`):
    the Catalog-level ``canonical_row_version_ids`` must be a subset of the
    union of the pinned builds' row versions. A ``CanonicalBuildPin`` may
    declare more row versions than the Dataset-level list uses; the Catalog
    contract never adds a private "every pinned row version must be used"
    restriction.
    """
    covered: set[str] = set()
    for pin in canonical_build_pins:
        covered.update(pin.canonical_row_version_ids)
    uncovered = sorted(set(canonical_row_version_ids) - covered)
    if uncovered:
        raise DatasetCatalogError(
            "canonical row-version ID(s) not covered by the pinned canonical "
            f"builds: {uncovered}"
        )


@dataclass(frozen=True)
class DatasetCatalogDatasetFacts:
    """Identity-bearing normalized verified Dataset facts.

    Exactly the fields that enter the Catalog content identity, projected
    from a verified :class:`~market_vault.dataset.reader_models.
    VerifiedDatasetBuild` by :func:`market_vault.dataset.dataset_catalog_projection.
    project_dataset_catalog_entry`. Raw identity text is NFC-normalized,
    deterministically stripped, and unsafe-text rejected; set-like facts
    (canonical row-version IDs) are normalized and deduplicated;
    business-key structures (spec pins under ``(kind, name, version)``,
    canonical build pins, completion entries) are deterministically sorted
    and fail closed on duplicate / conflicting entries; every instant is
    UTC-microsecond normalized; and every nested value is an existing
    frozen typed model of the Dataset layer (``DatasetScope``, ``SpecPin``,
    ``CanonicalBuildPin``, ``CompletionSummary``) — no raw dict and no
    untyped payload is accepted, while iterable container input is frozen
    into tuples at the boundary. ``built_at``, build paths, and all
    location facts are deliberately absent from this type: they live only
    in :class:`DatasetCatalogObservedMetadata` and can never reach the
    content identity through the model structure.
    """

    dataset_id: str
    dataset_kind: str
    status: str
    logical_row_count: int
    dataset_schema_id: str
    logical_dataset_content_id: str
    dataset_as_of: datetime | None
    scope: DatasetScope
    feature_spec_pins: tuple
    label_spec_pins: tuple
    split_spec_pin: SpecPin | None
    canonical_build_pins: tuple
    canonical_row_version_ids: tuple
    completion: CompletionSummary

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "dataset_id", _normalize_sha256(self.dataset_id, "dataset_id")
        )
        object.__setattr__(
            self,
            "dataset_kind",
            _require_text(self.dataset_kind, "dataset_kind"),
        )
        status = self.status
        if status not in (STATUS_COMPLETE, STATUS_EMPTY):
            raise DatasetCatalogError(
                f"status must be {STATUS_COMPLETE} or {STATUS_EMPTY}, got "
                f"{status!r}"
            )
        object.__setattr__(self, "status", status)
        row_count = _require_non_negative_int(
            self.logical_row_count, "logical_row_count"
        )
        object.__setattr__(self, "logical_row_count", row_count)
        object.__setattr__(
            self,
            "dataset_schema_id",
            _normalize_sha256(self.dataset_schema_id, "dataset_schema_id"),
        )
        object.__setattr__(
            self,
            "logical_dataset_content_id",
            _normalize_sha256(
                self.logical_dataset_content_id, "logical_dataset_content_id"
            ),
        )
        if self.dataset_as_of is not None:
            object.__setattr__(
                self,
                "dataset_as_of",
                _normalize_instant(self.dataset_as_of, "dataset_as_of"),
            )
        if not isinstance(self.scope, DatasetScope):
            raise DatasetCatalogError(
                f"scope must be a DatasetScope, got {type(self.scope).__name__}"
            )
        object.__setattr__(
            self,
            "feature_spec_pins",
            _normalize_spec_pins(
                self.feature_spec_pins, SPEC_KIND_FEATURE, "feature_spec_pins"
            ),
        )
        object.__setattr__(
            self,
            "label_spec_pins",
            _normalize_spec_pins(
                self.label_spec_pins, SPEC_KIND_LABEL, "label_spec_pins"
            ),
        )
        split_pin = self.split_spec_pin
        if split_pin is not None:
            if not isinstance(split_pin, SpecPin):
                raise DatasetCatalogError(
                    f"split_spec_pin must be a SpecPin or None, got "
                    f"{type(split_pin).__name__}"
                )
            if split_pin.kind != SPEC_KIND_SPLIT:
                raise DatasetCatalogError(
                    f"split_spec_pin may only be a SPLIT spec pin, got kind "
                    f"{split_pin.kind!r}"
                )
        object.__setattr__(self, "split_spec_pin", split_pin)
        object.__setattr__(
            self,
            "canonical_build_pins",
            _normalize_canonical_build_pins(self.canonical_build_pins),
        )
        object.__setattr__(
            self,
            "canonical_row_version_ids",
            _normalize_row_version_ids(self.canonical_row_version_ids),
        )
        if not isinstance(self.completion, CompletionSummary):
            raise DatasetCatalogError(
                f"completion must be a CompletionSummary, got "
                f"{type(self.completion).__name__}"
            )
        # Status / row-count consistency mirrors the manifest contract.
        if status == STATUS_EMPTY and row_count != 0:
            raise DatasetCatalogError(
                "status EMPTY requires logical_row_count == 0"
            )
        if status == STATUS_COMPLETE and row_count == 0:
            raise DatasetCatalogError(
                "status COMPLETE requires at least one logical row; zero "
                "rows must be EMPTY"
            )
        _validate_completion_scope(self.completion, self.scope)
        _validate_row_version_coverage(
            self.canonical_build_pins, self.canonical_row_version_ids
        )


@dataclass(frozen=True)
class DatasetCatalogObservedMetadata:
    """Non-content observed metadata of one Dataset build.

    Only ``built_at`` and the verified build location (``build_path``) are
    recorded. This type is structurally disjoint from
    :class:`DatasetCatalogDatasetFacts` (it shares no field names with the
    content facts), so the metadata can never be accidentally mixed into
    the Catalog content identity; the content identity functions accept
    facts only, never metadata. ``build_path`` is the lexically absolute
    build directory carried by the verified build; it only describes the
    location and never enters any identity.
    """

    built_at: datetime
    build_path: Path

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "built_at", _normalize_instant(self.built_at, "built_at")
        )
        build_path = self.build_path
        if not isinstance(build_path, Path) or not build_path.is_absolute():
            raise DatasetCatalogError(
                f"build_path must be an absolute Path, got {build_path!r}"
            )
        for part in build_path.parts:
            if part in (".", ".."):
                raise DatasetCatalogError(
                    f"build_path must not contain '.' or '..' path components: "
                    f"{build_path!r}"
                )
        object.__setattr__(self, "build_path", build_path)


@dataclass(frozen=True)
class DatasetCatalogEntry:
    """One projected Catalog record: verified content facts plus observed
    metadata plus the self-validated content ID.

    ``content_id`` is the 64-character lowercase SHA-256 of the
    deterministic Catalog content identity over ``dataset_facts`` only and
    is recomputed at construction, so a ``dataclasses.replace`` tamper
    (wrong content ID or substituted facts) fails closed. The observed
    metadata never enters ``content_id``: a legal metadata change (a
    different ``built_at`` or a move to another parent directory with the
    same ``dataset_id`` basename) never changes it. Metadata fails closed
    only when its own shape is invalid or when the ``build_path`` basename
    does not equal ``dataset_facts.dataset_id``.
    """

    dataset_facts: DatasetCatalogDatasetFacts
    observed_metadata: DatasetCatalogObservedMetadata
    content_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.dataset_facts, DatasetCatalogDatasetFacts):
            raise DatasetCatalogError(
                f"dataset_facts must be a DatasetCatalogDatasetFacts, got "
                f"{type(self.dataset_facts).__name__}"
            )
        if not isinstance(self.observed_metadata, DatasetCatalogObservedMetadata):
            raise DatasetCatalogError(
                f"observed_metadata must be a DatasetCatalogObservedMetadata, "
                f"got {type(self.observed_metadata).__name__}"
            )
        # Location binding: the verified Dataset build path contract fixes
        # ``build_path.name == dataset_id``. The observed metadata is never
        # identity-bearing, but a Dataset's facts must never be bound to
        # another Dataset's location; moving to a different parent keeps the
        # basename and stays legal.
        if (
            self.observed_metadata.build_path.name
            != self.dataset_facts.dataset_id
        ):
            raise DatasetCatalogError(
                "observed_metadata.build_path basename must equal "
                "dataset_facts.dataset_id"
            )
        content_id = _normalize_sha256(self.content_id, "content_id")
        object.__setattr__(self, "content_id", content_id)
        # Lazy import keeps the models module free of identity-module
        # dependencies at import time (the identity module imports these
        # models).
        from .dataset_catalog_identity import catalog_dataset_content_id

        expected = catalog_dataset_content_id(self.dataset_facts)
        if content_id != expected:
            raise DatasetCatalogError(
                "content_id does not match the recomputed Catalog content "
                "identity of dataset_facts"
            )
