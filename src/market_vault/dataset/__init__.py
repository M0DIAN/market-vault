"""Derived dataset layer (v0.4.0 manifest/identity core).

The deterministic identity and manifest foundation for derived datasets: the
explicit logical Dataset schema model, ``dataset_schema_id``, deterministic
logical content hashing, canonical-build provenance pins, Feature/Label/Split/
Transform fingerprints, scope and ``dataset_as_of`` normalization, completion
and gap references, the versioned Dataset manifest, deterministic
serialization, strict validation, and atomic standalone manifest writing.

This core does not assemble market samples, compute features or labels, parse
Feature/Label spec files, assign train/validation/test splits, purge by actual
label end, export Dataset Parquet, read canonical bar Parquet, filter
Canonical rows by ``dataset_as_of``, create DuckDB views, add CLI commands, or
train models. The Canonical manifest remains authoritative for Canonical
builds; the Dataset layer only references immutable Canonical builds and their
stable identities.
"""

from .content import dataset_schema_id, logical_dataset_content_id
from .encoding import DATASET_IDENTITY_ENCODING_VERSION, DatasetError
from .identity import dataset_id
from .manifest import (
    build_dataset_manifest,
    serialize_dataset_manifest,
    validate_dataset_manifest,
    write_dataset_manifest_atomic,
)
from .models import (
    DATASET_CONTENT_ID_VERSION,
    DATASET_MANIFEST_SCHEMA_VERSION,
    DATASET_SCHEMA_ID_VERSION,
    SERIALIZATION_FORMAT_PARQUET,
    SERIALIZATION_FORMAT_VERSION_PARQUET,
    SPEC_KIND_FEATURE,
    SPEC_KIND_LABEL,
    SPEC_KIND_SPLIT,
    STATUS_COMPLETE,
    STATUS_EMPTY,
    SUPPORTED_LOGICAL_TYPES,
    CanonicalBuildPin,
    CompletionEntry,
    CompletionSummary,
    DatasetField,
    DatasetIdentityInput,
    DatasetManifest,
    DatasetOutputFile,
    DatasetSchema,
    DatasetScope,
    GapReference,
    ImplementationPin,
    SourceSnapshotPin,
    SpecPin,
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
    "DatasetError",
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
    "build_dataset_manifest",
    "dataset_id",
    "dataset_schema_id",
    "logical_dataset_content_id",
    "serialize_dataset_manifest",
    "validate_dataset_manifest",
    "write_dataset_manifest_atomic",
]
