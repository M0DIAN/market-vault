"""Frozen models and constants of the Dataset Catalog builder contract
(v0.6.0 PR-6).

This module defines the builder layer's own contract surface:

- :data:`DATASET_CATALOG_BUILDER_VERSION` — the version of the builder
  implementation. It is carried on every
  :class:`DatasetCatalogBuildResult` and recorded in ``catalog.json`` and
  ``manifest.json``; it never enters ``dataset_id``, any Canonical
  identity, the Sample Generation identity, or the PR-5 Catalog content
  identity;
- :class:`DatasetCatalogBuildError` — the unified fail-closed error of the
  builder (a subclass of :class:`DatasetCatalogError`);
- :class:`DatasetCatalogBuildResult` — the frozen deterministic result of
  one Catalog build: the ``dataset_id``-sorted frozen entry tuple, the
  recomputed PR-5 Catalog content identity, the recomputed dataset count,
  and the builder version. Construction independently re-verifies every
  invariant (fail closed), so a manually constructed or
  ``dataclasses.replace``-modified result can never carry an unsorted,
  duplicated, mistyped, or wrong-identity payload.

Nothing here reads or writes the filesystem, never scans directories,
never calls ``load_verified_dataset``, never loads settings, never
accesses the network, and never uses the current time; the candidate
discovery and verified loading live in
:mod:`market_vault.dataset.dataset_catalog_builder`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .dataset_catalog_models import (
    DatasetCatalogEntry,
    DatasetCatalogError,
)

__all__ = [
    "DATASET_CATALOG_BUILDER_VERSION",
    "DatasetCatalogBuildError",
    "DatasetCatalogBuildResult",
]

#: Version of the Dataset Catalog builder implementation itself. It is
#: carried on every :class:`DatasetCatalogBuildResult` and recorded in
#: ``catalog.json`` / ``manifest.json``; it never enters the PR-5 Catalog
#: content identity and never enters any Dataset identity.
DATASET_CATALOG_BUILDER_VERSION = "market-vault-dataset-catalog-builder-v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class DatasetCatalogBuildError(DatasetCatalogError):
    """Structured fail-closed failure of the Dataset Catalog builder.

    Raised for invalid build inputs (missing or ambiguous candidate
    mode), unsafe / linked / special discovery roots and candidates,
    unverified candidates, ambiguous duplicate Dataset locations,
    conflicting content facts, and result-model inconsistencies. Every
    documented failure of the underlying layers (``DatasetError`` and its
    layer subclasses, ``OSError``, ``UnicodeError``, and the documented
    ``TypeError`` / ``ValueError`` / ``KeyError``) is converted to this
    error with its ``__cause__`` preserved; an already-raised
    :class:`DatasetCatalogBuildError` is never double-wrapped. Broad
    ``except Exception`` is never used: real programming errors are not
    hidden.
    """


@dataclass(frozen=True)
class DatasetCatalogBuildResult:
    """Deterministic output of one Dataset Catalog build.

    Carries the ``dataset_id``-sorted frozen tuple of
    :class:`DatasetCatalogEntry` records, the recomputed PR-5 Catalog
    content identity, the recomputed dataset count, and the builder
    version. Construction independently re-verifies every invariant (fail
    closed): every entry is a :class:`DatasetCatalogEntry`; the entries
    are sorted by ``dataset_id`` in strictly ascending order and carry no
    duplicate ``dataset_id``; ``dataset_count`` is recomputed from the
    entries; ``catalog_content_id`` is recomputed through the PR-5
    Catalog content identity over the entries; and ``builder_version`` is
    the current constant. A ``dataclasses.replace`` tamper (wrong content
    ID, substituted / unsorted / duplicated entries, wrong count, wrong
    version) fails closed.

    The model never carries a mutable container, a timestamp of the build
    invocation, a machine name, a path, or any observed metadata beyond
    what the entries themselves carry.
    """

    entries: tuple
    catalog_content_id: str
    dataset_count: int
    builder_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.entries, tuple) or not all(
            isinstance(entry, DatasetCatalogEntry) for entry in self.entries
        ):
            raise DatasetCatalogBuildError(
                "entries must be a tuple of DatasetCatalogEntry instances, "
                f"got {type(self.entries).__name__}"
            )
        ids = [entry.dataset_facts.dataset_id for entry in self.entries]
        if ids != sorted(ids):
            raise DatasetCatalogBuildError(
                "entries must be sorted by dataset_id in ascending order"
            )
        if len(set(ids)) != len(ids):
            raise DatasetCatalogBuildError(
                "entries must not contain duplicate dataset_id values"
            )
        count = len(self.entries)
        if type(self.dataset_count) is not int or self.dataset_count != count:
            raise DatasetCatalogBuildError(
                "dataset_count must be recomputed from the entries, got "
                f"{self.dataset_count!r} for {count} entries"
            )
        if not isinstance(self.catalog_content_id, str) or not _SHA256_RE.fullmatch(
            self.catalog_content_id
        ):
            raise DatasetCatalogBuildError(
                "catalog_content_id must be a 64-character lowercase SHA-256 "
                f"hex string, got {self.catalog_content_id!r}"
            )
        if self.builder_version != DATASET_CATALOG_BUILDER_VERSION:
            raise DatasetCatalogBuildError(
                f"builder_version must be {DATASET_CATALOG_BUILDER_VERSION}, "
                f"got {self.builder_version!r}"
            )
        # Lazy import keeps the models module free of identity-module
        # dependencies at import time (the identity module imports the PR-5
        # models, never these).
        from .dataset_catalog_identity import dataset_catalog_content_id

        expected = dataset_catalog_content_id(self.entries)
        if self.catalog_content_id != expected:
            raise DatasetCatalogBuildError(
                "catalog_content_id does not match the recomputed PR-5 "
                "Catalog content identity of the entries"
            )
