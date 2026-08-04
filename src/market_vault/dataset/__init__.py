"""Derived dataset layer (v0.4.0 manifest/identity and PIT foundation).

The deterministic identity and manifest foundation for derived datasets: the
explicit logical Dataset schema model, ``dataset_schema_id``, deterministic
logical content hashing, canonical-build provenance pins, Feature/Label/Split/
Transform fingerprints, scope and ``dataset_as_of`` normalization, completion
and gap references, the versioned Dataset manifest, deterministic
serialization, strict validation, and atomic standalone manifest writing.
The two-clock point-in-time sample assembly foundation
(:mod:`market_vault.dataset.pit`) binds verified Canonical rows to
Feature/Label observation windows under the market clock and the optional
archive clock and produces the association content the future Dataset
builder consumes.

The versioned Feature/Label spec contracts (:mod:`market_vault.dataset.
spec_models`) provide frozen typed spec models, and
:mod:`market_vault.dataset.specs` provides strict YAML parsing,
deterministic semantic content identity, and conversion to the existing
SpecPin, so spec documents bind into ``DatasetIdentityInput`` /
``dataset_id``. Spec parsing and validation never import or execute
``transform_ref``.

This layer does not compute features or labels, assign train/validation/test
splits, purge by actual label end, export Dataset Parquet, build the final
DatasetManifest, create DuckDB views, add CLI commands, or train models. The
Canonical manifest remains authoritative for Canonical builds; the Dataset
layer only references immutable Canonical builds and their stable identities.
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
from .pit import (
    PIT_ASSOCIATION_COLUMNS,
    assemble_point_in_time_samples,
    pit_association_content_id,
    pit_association_schema,
    pit_association_schema_id,
)
from .pit_identity import pit_sample_key, pit_sample_version_id
from .pit_models import (
    PIT_ASSEMBLER_VERSION,
    PIT_ASSOCIATION_SCHEMA_VERSION,
    PIT_ROLE_FEATURE,
    PIT_ROLE_LABEL,
    PIT_SAMPLE_KEY_VERSION,
    PIT_SAMPLE_VERSION_ID_VERSION,
    PITAssemblyDiagnostics,
    PITAssemblyError,
    PITAssemblyResult,
    PITDiagnostics,
    PITObservationWindow,
    PITSample,
    PITSampleRequest,
)
from .spec_models import (
    FEATURE_LABEL_SPEC_CONTENT_ID_VERSION,
    FEATURE_SPEC_SCHEMA_VERSION,
    LABEL_SPEC_SCHEMA_VERSION,
    CrossTradingDayPolicy,
    FeatureSpec,
    LabelHorizon,
    LabelObservationWindow,
    LabelSpec,
    SpecParameter,
    SpecValidationError,
    SpecVersionRequirements,
)
from .specs import (
    feature_label_spec_content_id,
    feature_label_spec_pin,
    load_feature_spec,
    load_label_spec,
    parse_feature_spec,
    parse_label_spec,
)

__all__ = [
    "DATASET_CONTENT_ID_VERSION",
    "DATASET_IDENTITY_ENCODING_VERSION",
    "DATASET_MANIFEST_SCHEMA_VERSION",
    "DATASET_SCHEMA_ID_VERSION",
    "FEATURE_LABEL_SPEC_CONTENT_ID_VERSION",
    "FEATURE_SPEC_SCHEMA_VERSION",
    "LABEL_SPEC_SCHEMA_VERSION",
    "PIT_ASSEMBLER_VERSION",
    "PIT_ASSOCIATION_COLUMNS",
    "PIT_ASSOCIATION_SCHEMA_VERSION",
    "PIT_ROLE_FEATURE",
    "PIT_ROLE_LABEL",
    "PIT_SAMPLE_KEY_VERSION",
    "PIT_SAMPLE_VERSION_ID_VERSION",
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
    "CrossTradingDayPolicy",
    "DatasetError",
    "FeatureSpec",
    "GapReference",
    "ImplementationPin",
    "LabelHorizon",
    "LabelObservationWindow",
    "LabelSpec",
    "SpecParameter",
    "SpecValidationError",
    "SpecVersionRequirements",
    "DatasetField",
    "DatasetIdentityInput",
    "DatasetManifest",
    "DatasetOutputFile",
    "DatasetSchema",
    "DatasetScope",
    "PITAssemblyDiagnostics",
    "PITAssemblyError",
    "PITAssemblyResult",
    "PITDiagnostics",
    "PITObservationWindow",
    "PITSample",
    "PITSampleRequest",
    "SourceSnapshotPin",
    "SpecPin",
    "assemble_point_in_time_samples",
    "build_dataset_manifest",
    "dataset_id",
    "dataset_schema_id",
    "feature_label_spec_content_id",
    "feature_label_spec_pin",
    "load_feature_spec",
    "load_label_spec",
    "logical_dataset_content_id",
    "parse_feature_spec",
    "parse_label_spec",
    "pit_association_content_id",
    "pit_association_schema",
    "pit_association_schema_id",
    "pit_sample_key",
    "pit_sample_version_id",
    "serialize_dataset_manifest",
    "validate_dataset_manifest",
    "write_dataset_manifest_atomic",
]
