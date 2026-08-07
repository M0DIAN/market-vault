"""Physical Catalog snapshot identity and PR-6 version constants
(v0.6.0 PR-6).

This module defines the fixed version constants of the PR-6 physical
snapshot layer and the snapshot ID computation. The snapshot ID is the
physical / materialization identity of one immutable Catalog snapshot
directory; it is fully independent of the PR-5 Catalog content identity
(:mod:`market_vault.dataset.dataset_catalog_identity`) and of every
Dataset / Canonical / Sample Generation identity:

- ``catalog_content_id`` (PR-5) binds only the normalized verified
  Dataset facts;
- ``snapshot_id`` (PR-6) binds the physical schema / manifest / snapshot
  ID / builder / materializer versions, the Catalog content identity, the
  dataset count, the explicit snapshot ``built_at``, and the exact
  ``catalog.json`` byte facts (size and SHA-256).

Therefore: the same Catalog logical facts + the same observed metadata +
the same explicit ``built_at`` produce the same snapshot ID; a different
``output_root`` or a move of the snapshot directory to another parent
never changes the snapshot ID; a Dataset relocation that changes
``catalog.json`` bytes changes the snapshot ID while the Catalog content
identity stays the same; and a different snapshot ``built_at`` changes
the snapshot ID while the Catalog content identity stays the same. The
snapshot ID never flows back into any Dataset fact.

None of the constants of this module enter ``dataset_id``, the Canonical
identity, the Sample Generation identity, or the PR-5 Catalog content
identity. The module never reads or writes files and never uses the
current time.
"""

from __future__ import annotations

import re
from datetime import datetime

from .dataset_catalog_builder_models import DATASET_CATALOG_BUILDER_VERSION
from .encoding import DatasetError, encode_identity, normalize_utc_datetime

__all__ = [
    "DATASET_CATALOG_MATERIALIZER_VERSION",
    "DATASET_CATALOG_READER_CONTRACT_VERSION",
    "DATASET_CATALOG_SNAPSHOT_ID_VERSION",
    "DATASET_CATALOG_SNAPSHOT_MANIFEST_VERSION",
    "DATASET_CATALOG_SNAPSHOT_SCHEMA_VERSION",
    "dataset_catalog_snapshot_id",
]

#: Version of the physical Catalog snapshot schema (``catalog.json`` file
#: layout). Changing it changes every snapshot ID that references it.
DATASET_CATALOG_SNAPSHOT_SCHEMA_VERSION = (
    "market-vault-dataset-catalog-snapshot-v1"
)

#: Version of the physical Catalog snapshot manifest (``manifest.json``
#: file layout).
DATASET_CATALOG_SNAPSHOT_MANIFEST_VERSION = (
    "market-vault-dataset-catalog-snapshot-manifest-v1"
)

#: Version of the deterministic physical snapshot identity
#: (:func:`dataset_catalog_snapshot_id`). Changing it changes every
#: snapshot ID.
DATASET_CATALOG_SNAPSHOT_ID_VERSION = "market-vault-dataset-catalog-snapshot-id-v1"

#: Version of the Catalog snapshot materializer implementation itself. It
#: is carried on every :class:`~market_vault.dataset.
#: dataset_catalog_materialization_models.DatasetCatalogMaterializationResult`
#: and recorded in ``manifest.json``; it never enters any Dataset identity
#: and never enters the PR-5 Catalog content identity.
DATASET_CATALOG_MATERIALIZER_VERSION = "market-vault-dataset-catalog-materializer-v1"

#: Version of the verified Catalog snapshot reader code contract. It is
#: carried on every
#: :class:`~market_vault.dataset.dataset_catalog_reader_models.
#: VerifiedDatasetCatalogSnapshot` and describes the reader only; it never
#: enters any identity and never enters any artifact.
DATASET_CATALOG_READER_CONTRACT_VERSION = (
    "market-vault-verified-dataset-catalog-reader-v1"
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _require_snapshot_inputs(
    *,
    catalog_content_id: str,
    dataset_count: int,
    built_at: datetime,
    catalog_file_byte_size: int,
    catalog_file_sha256: str,
) -> None:
    """Exact typed input contract of the snapshot identity (fail closed)."""
    if not isinstance(catalog_content_id, str) or not _SHA256_RE.fullmatch(
        catalog_content_id
    ):
        raise ValueError(
            "catalog_content_id must be a 64-character lowercase SHA-256 "
            f"hex string, got {catalog_content_id!r}"
        )
    if type(dataset_count) is not int or dataset_count < 0:
        raise ValueError(
            f"dataset_count must be a real non-negative integer, got "
            f"{dataset_count!r}"
        )
    if not isinstance(catalog_file_sha256, str) or not _SHA256_RE.fullmatch(
        catalog_file_sha256
    ):
        raise ValueError(
            "catalog_file_sha256 must be a 64-character lowercase SHA-256 "
            f"hex string, got {catalog_file_sha256!r}"
        )
    if type(catalog_file_byte_size) is not int or catalog_file_byte_size < 0:
        raise ValueError(
            f"catalog_file_byte_size must be a real non-negative integer, "
            f"got {catalog_file_byte_size!r}"
        )


def dataset_catalog_snapshot_id(
    *,
    catalog_content_id: str,
    dataset_count: int,
    built_at: datetime,
    catalog_file_byte_size: int,
    catalog_file_sha256: str,
) -> str:
    """64-character lowercase SHA-256 of the deterministic physical
    snapshot identity of one Catalog snapshot materialization.

    Binds the snapshot schema / manifest / snapshot-ID / builder /
    materializer versions, the PR-5 Catalog content identity, the dataset
    count, the explicit snapshot ``built_at`` (normalized to UTC
    microseconds, so timezone-equivalent representations of the same
    instant produce the same snapshot ID), and the exact ``catalog.json``
    byte facts (real non-negative byte size and lowercase SHA-256). The
    Catalog ``output_root``, the snapshot path, the machine name, cwd, and
    the current time never enter the snapshot ID.

    All inputs are validated (fail closed); the function never reads or
    writes files.
    """
    _require_snapshot_inputs(
        catalog_content_id=catalog_content_id,
        dataset_count=dataset_count,
        built_at=built_at,
        catalog_file_byte_size=catalog_file_byte_size,
        catalog_file_sha256=catalog_file_sha256,
    )
    fields = {
        "snapshot_schema_version": DATASET_CATALOG_SNAPSHOT_SCHEMA_VERSION,
        "manifest_schema_version": DATASET_CATALOG_SNAPSHOT_MANIFEST_VERSION,
        "snapshot_id_version": DATASET_CATALOG_SNAPSHOT_ID_VERSION,
        "builder_version": DATASET_CATALOG_BUILDER_VERSION,
        "materializer_version": DATASET_CATALOG_MATERIALIZER_VERSION,
        "catalog_content_id": catalog_content_id,
        "dataset_count": dataset_count,
        "built_at": normalize_utc_datetime(built_at, "built_at"),
        "catalog_file_byte_size": catalog_file_byte_size,
        "catalog_file_sha256": catalog_file_sha256,
    }
    try:
        return encode_identity(DATASET_CATALOG_SNAPSHOT_ID_VERSION, fields)
    except DatasetError as exc:
        raise ValueError(str(exc)) from exc
