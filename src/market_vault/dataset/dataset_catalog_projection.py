"""Pure metadata projection of the v0.6.0 Dataset Catalog contract
(PR-5).

``project_dataset_catalog_entry`` is the single projection entry point: it
accepts exactly one verified :class:`~market_vault.dataset.reader_models.
VerifiedDatasetBuild` (the frozen, deeply immutable result of
:func:`market_vault.dataset.reader.load_verified_dataset`) and returns one
:class:`DatasetCatalogEntry` with the normalized identity-bearing facts,
the observed non-content metadata, and the self-validated content ID.

The projection is a pure function over verified typed facts only: it never
re-derives the Dataset, never executes Feature or Label work, never reads
the Dataset Parquet, never accepts a manifest dict, a manifest path, or an
arbitrary build directory, and never calls ``load_verified_dataset``
itself — the PR-6 builder is responsible for calling the verified reader
on every candidate and passing the resulting verified builds into this
projection. It never accesses OpenD, the network, settings, or the
current time, and it never scans the filesystem.

All failures raise :class:`DatasetCatalogError`; programming errors are
never swallowed.
"""

from __future__ import annotations

from .dataset_catalog_identity import catalog_dataset_content_id
from .dataset_catalog_models import (
    DatasetCatalogDatasetFacts,
    DatasetCatalogEntry,
    DatasetCatalogError,
    DatasetCatalogObservedMetadata,
)
from .reader_models import VerifiedDatasetBuild

__all__ = ["project_dataset_catalog_entry"]


def project_dataset_catalog_entry(
    build: VerifiedDatasetBuild,
) -> DatasetCatalogEntry:
    """Project one verified Dataset build into one Catalog entry.

    Only a :class:`VerifiedDatasetBuild` is accepted; a manifest dict, a
    manifest path, an arbitrary build directory, and any other object fail
    closed. All content facts come from the verified typed build (the
    manifest model is itself re-validated by the verified reader), the
    observed metadata records only ``built_at`` and the build location,
    and the entry's content ID is recomputed over the facts and
    self-validated at construction.

    The projection is deterministic and side-effect free: the same
    verified build always produces the same facts and the same content
    ID, regardless of where the Dataset directory is located, which
    machine or working directory the projection runs in, and when it is
    invoked.
    """
    if not isinstance(build, VerifiedDatasetBuild):
        raise DatasetCatalogError(
            "project_dataset_catalog_entry accepts only a "
            f"VerifiedDatasetBuild, got {type(build).__name__}"
        )
    manifest = build.manifest
    facts = DatasetCatalogDatasetFacts(
        dataset_id=build.dataset_id,
        dataset_kind=build.dataset_kind,
        status=build.status,
        logical_row_count=manifest.logical_row_count,
        dataset_schema_id=manifest.dataset_schema_id,
        logical_dataset_content_id=manifest.logical_dataset_content_id,
        dataset_as_of=build.dataset_as_of,
        scope=manifest.scope,
        feature_spec_pins=manifest.feature_specs,
        label_spec_pins=manifest.label_specs,
        split_spec_pin=manifest.split_spec,
        canonical_build_pins=manifest.canonical_builds,
        canonical_row_version_ids=manifest.canonical_row_version_ids,
        completion=manifest.completion,
    )
    metadata = DatasetCatalogObservedMetadata(
        built_at=build.built_at,
        build_path=build.build_path,
    )
    return DatasetCatalogEntry(
        dataset_facts=facts,
        observed_metadata=metadata,
        content_id=catalog_dataset_content_id(facts),
    )
