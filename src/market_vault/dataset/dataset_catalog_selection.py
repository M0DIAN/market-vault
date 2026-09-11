"""Pure selection from an already verified Dataset Catalog snapshot.

The verified Catalog reader is the sole artifact-validation authority.
This module validates only its own call shape and exact-match cardinality;
it performs no filesystem access, discovery, Dataset loading, or secondary
artifact validation.
"""

from __future__ import annotations

import re

from .dataset_catalog_models import DatasetCatalogError
from .dataset_catalog_reader_models import (
    DatasetCatalogSnapshotEntryRecord,
    VerifiedDatasetCatalogSnapshot,
)

__all__ = [
    "DatasetCatalogSelectionError",
    "select_verified_dataset_catalog_entry",
]

_DATASET_ID_RE = re.compile(r"^[0-9a-f]{64}$")


class DatasetCatalogSelectionError(DatasetCatalogError):
    """Fail-closed error for selecting from a verified Catalog."""


def select_verified_dataset_catalog_entry(
    catalog: VerifiedDatasetCatalogSnapshot,
    dataset_id: str,
) -> DatasetCatalogSnapshotEntryRecord:
    """Return the one entry whose ``dataset_id`` exactly matches.

    ``catalog`` must already have crossed the formal verified-reader trust
    boundary. The returned object is the exact instance held in
    ``catalog.entries``.
    """
    if not isinstance(catalog, VerifiedDatasetCatalogSnapshot):
        raise DatasetCatalogSelectionError(
            "catalog must be a VerifiedDatasetCatalogSnapshot, got "
            f"{type(catalog).__name__}"
        )
    if not isinstance(dataset_id, str) or not _DATASET_ID_RE.fullmatch(
        dataset_id
    ):
        raise DatasetCatalogSelectionError(
            "dataset_id must be a 64-character lowercase hexadecimal string"
        )

    matches = [
        entry for entry in catalog.entries if entry.dataset_id == dataset_id
    ]
    if not matches:
        raise DatasetCatalogSelectionError(
            f"dataset_id is absent from the verified Dataset Catalog: "
            f"{dataset_id}"
        )
    if len(matches) != 1:
        raise DatasetCatalogSelectionError(
            "dataset_id must match exactly one verified Dataset Catalog "
            f"entry, found {len(matches)}: {dataset_id}"
        )
    return matches[0]
