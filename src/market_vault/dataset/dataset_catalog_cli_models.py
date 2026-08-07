"""Frozen models and version constants of the Dataset Catalog CLI
contract (v0.6.0 PR-7).

This module defines the Dataset Catalog CLI layer's own contract surface:

- :data:`DATASET_CATALOG_CLI_CONTRACT_VERSION` — the version of the
  Dataset Catalog CLI input/output contract. It describes the CLI only;
  it never enters ``snapshot_id``, ``catalog_content_id``, any Dataset
  identity, the Catalog content identity, the physical snapshot identity,
  or any artifact;
- :data:`DATASET_CATALOG_CLI_RESULT_SCHEMA_VERSION` — the version of the
  deterministic Dataset Catalog CLI result JSON contract (success and
  failure outputs of the four commands);
- :class:`DatasetCatalogCLIError` — the unified documented error of the
  Dataset Catalog command layer (a subclass of
  :class:`~market_vault.dataset.dataset_catalog_models.DatasetCatalogError`).

The CLI constants and error type are internal to the command layer: they
are never exported from :mod:`market_vault.dataset` and never enter any
identity, any ``catalog.json`` / ``manifest.json`` bytes, or any artifact.
Nothing here reads or writes the filesystem and no current time is used.
"""

from __future__ import annotations

from .dataset_catalog_models import DatasetCatalogError

__all__ = [
    "DATASET_CATALOG_CLI_CONTRACT_VERSION",
    "DATASET_CATALOG_CLI_RESULT_SCHEMA_VERSION",
    "DatasetCatalogCLIError",
]

#: Version of the Dataset Catalog CLI input/output contract (described in
#: ``docs/contracts/dataset_catalog.md`` Part C). It records the CLI
#: contract only and never enters ``snapshot_id``,
#: ``catalog_content_id``, any Dataset identity, the Catalog content
#: identity, the physical snapshot identity, or any artifact.
DATASET_CATALOG_CLI_CONTRACT_VERSION = "market-vault-dataset-catalog-cli-v1"

#: Version of the deterministic Dataset Catalog CLI result JSON contract
#: (success and failure outputs of the four commands).
DATASET_CATALOG_CLI_RESULT_SCHEMA_VERSION = (
    "market-vault-dataset-catalog-cli-result-v1"
)


class DatasetCatalogCLIError(DatasetCatalogError):
    """Unified documented failure of the Dataset Catalog command layer.

    Raised for invalid CLI path inputs (``.`` / ``..`` lexical
    components), the missing-dataset lookup of ``dataset-catalog-show``,
    and every documented failure of the underlying formal layers
    (``DatasetCatalogError`` and its subclasses — the builder, the
    materializer, and the verified reader — plus the documented
    ``OSError`` / ``UnicodeError`` / ``TypeError`` / ``ValueError`` /
    ``KeyError``), each converted with its ``__cause__`` preserved and
    never double-wrapped. The command layer never uses broad
    ``except Exception``: real programming errors (``RuntimeError``,
    ``AssertionError``, and friends) are not disguised as user input
    errors and are never converted.
    """
