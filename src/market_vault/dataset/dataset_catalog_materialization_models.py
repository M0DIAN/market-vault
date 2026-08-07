"""Frozen models and constants of the Dataset Catalog snapshot
materialization contract (v0.6.0 PR-6).

This module defines the materialization layer's own contract surface:

- the fixed artifact file names of one Catalog snapshot directory
  (``catalog.json``, ``manifest.json``, ``_SUCCESS``) and the fixed
  staging prefix (``.staging-<snapshot_id>``);
- :class:`DatasetCatalogMaterializationError` — the unified fail-closed
  error of the Catalog snapshot materializer (a subclass of
  :class:`DatasetCatalogError`);
- :class:`DatasetCatalogMaterializationResult` — the frozen result model
  of one committed Catalog snapshot directory, which independently
  re-verifies every invariant at construction (fail closed, without ever
  reading the filesystem).

Nothing here reads or writes the filesystem. ``snapshot_id`` and
``catalog_content_id`` are recorded facts; the constants of this module
never enter ``dataset_id``, any Canonical identity, the Sample Generation
identity, or the PR-5 Catalog content identity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .dataset_catalog_models import DatasetCatalogError
from .dataset_catalog_snapshot_identity import (
    DATASET_CATALOG_MATERIALIZER_VERSION,
)

__all__ = [
    "DATASET_CATALOG_CATALOG_FILENAME",
    "DATASET_CATALOG_MANIFEST_FILENAME",
    "DATASET_CATALOG_STAGING_PREFIX",
    "DATASET_CATALOG_SUCCESS_FILENAME",
    "DatasetCatalogMaterializationError",
    "DatasetCatalogMaterializationResult",
]

#: Fixed artifact file names of one Catalog snapshot directory (only these
#: three files are ever allowed).
DATASET_CATALOG_CATALOG_FILENAME = "catalog.json"
DATASET_CATALOG_MANIFEST_FILENAME = "manifest.json"
DATASET_CATALOG_SUCCESS_FILENAME = "_SUCCESS"

#: Fixed staging directory prefix (``.staging-<snapshot_id>``; never a
#: random name).
DATASET_CATALOG_STAGING_PREFIX = ".staging-"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class DatasetCatalogMaterializationError(DatasetCatalogError):
    """Structured fail-closed failure of the Dataset Catalog snapshot
    materialization layer.

    Raised for invalid materialization inputs, output-root / staging
    safety failures, staging residue and concurrent staging conflicts,
    write / readback verification failures, non-canonical or
    identity-inconsistent artifacts, existing-snapshot verification
    failures, no-replace publication unavailability, and result-model
    inconsistencies. Every documented failure of the underlying layers
    (``DatasetError`` and its layer subclasses, ``OSError``,
    ``UnicodeError``, and the documented ``TypeError`` / ``ValueError`` /
    ``KeyError``) is converted to this error with its ``__cause__``
    preserved; an already-raised
    :class:`DatasetCatalogMaterializationError` is never double-wrapped.
    Broad ``except Exception`` is never used: real programming errors are
    not hidden.
    """


def _reject_dot_components(path: Path, label: str) -> None:
    for part in path.parts:
        if part in (".", ".."):
            raise DatasetCatalogMaterializationError(
                f"{label} must not contain '.' or '..' path components: "
                f"{path!r}"
            )


def _require_exact_artifact_child(
    path: Path, snapshot_path: Path, filename: str, label: str
) -> None:
    """One artifact path must be exactly ``snapshot_path / <fixed
    filename>`` (fixed direct children only)."""
    if not isinstance(path, Path) or not path.is_absolute():
        raise DatasetCatalogMaterializationError(
            f"{label} must be an absolute Path, got {path!r}"
        )
    _reject_dot_components(path, label)
    if path != snapshot_path / filename:
        raise DatasetCatalogMaterializationError(
            f"{label} must be exactly snapshot_path / {filename!r}, got {path!r}"
        )


@dataclass(frozen=True)
class DatasetCatalogMaterializationResult:
    """Deterministic output of one committed Catalog snapshot
    materialization.

    Carries the snapshot ID, the PR-5 Catalog content identity, the
    dataset count, the immutable fact paths of the committed snapshot
    directory, whether a new snapshot directory was created by this call,
    and the materializer version. Construction independently re-verifies
    every invariant (fail closed, never reading the filesystem):
    ``snapshot_id`` and ``catalog_content_id`` are strict lowercase
    64-hex; ``dataset_count`` is a real non-negative integer;
    ``created_new_snapshot`` is a real bool; ``materializer_version`` is
    the current constant; every path is an absolute
    :class:`pathlib.Path` without ``.`` / ``..`` lexical components;
    ``snapshot_path.name`` is exactly ``snapshot_id``; and every artifact
    path is exactly ``snapshot_path / <fixed artifact name>`` (fixed
    direct children — a path that merely shares the snapshot directory as
    an ancestor is rejected).

    The model never carries a mutable dict, a temporary path, elapsed
    time, current time, or arbitrary metadata.
    """

    snapshot_id: str
    catalog_content_id: str
    dataset_count: int
    snapshot_path: Path
    catalog_path: Path
    manifest_path: Path
    success_path: Path
    created_new_snapshot: bool
    materializer_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_id, str) or not _SHA256_RE.fullmatch(
            self.snapshot_id
        ):
            raise DatasetCatalogMaterializationError(
                "snapshot_id must be a 64-character lowercase SHA-256 hex "
                f"string, got {self.snapshot_id!r}"
            )
        if not isinstance(self.catalog_content_id, str) or not _SHA256_RE.fullmatch(
            self.catalog_content_id
        ):
            raise DatasetCatalogMaterializationError(
                "catalog_content_id must be a 64-character lowercase SHA-256 "
                f"hex string, got {self.catalog_content_id!r}"
            )
        if type(self.dataset_count) is not int or self.dataset_count < 0:
            raise DatasetCatalogMaterializationError(
                "dataset_count must be a real non-negative integer, got "
                f"{self.dataset_count!r}"
            )
        if type(self.created_new_snapshot) is not bool:
            raise DatasetCatalogMaterializationError(
                "created_new_snapshot must be a real bool, got "
                f"{self.created_new_snapshot!r}"
            )
        if self.materializer_version != DATASET_CATALOG_MATERIALIZER_VERSION:
            raise DatasetCatalogMaterializationError(
                f"materializer_version must be "
                f"{DATASET_CATALOG_MATERIALIZER_VERSION}, got "
                f"{self.materializer_version!r}"
            )
        snapshot_path = self.snapshot_path
        if not isinstance(snapshot_path, Path) or not snapshot_path.is_absolute():
            raise DatasetCatalogMaterializationError(
                f"snapshot_path must be an absolute Path, got {snapshot_path!r}"
            )
        _reject_dot_components(snapshot_path, "snapshot_path")
        if snapshot_path.name != self.snapshot_id:
            raise DatasetCatalogMaterializationError(
                f"snapshot_path.name must be exactly {self.snapshot_id!r}, got "
                f"{snapshot_path.name!r}"
            )
        _require_exact_artifact_child(
            self.catalog_path,
            snapshot_path,
            DATASET_CATALOG_CATALOG_FILENAME,
            "catalog_path",
        )
        _require_exact_artifact_child(
            self.manifest_path,
            snapshot_path,
            DATASET_CATALOG_MANIFEST_FILENAME,
            "manifest_path",
        )
        _require_exact_artifact_child(
            self.success_path,
            snapshot_path,
            DATASET_CATALOG_SUCCESS_FILENAME,
            "success_path",
        )
