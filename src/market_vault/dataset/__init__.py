"""Derived dataset layer (v0.4.0 manifest/identity, PIT, and split
foundation).

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

The deterministic chronological split foundation
(:mod:`market_vault.dataset.split_models` and
:mod:`market_vault.dataset.splits`) assigns nominal TRAIN / VALIDATION /
TEST splits by the local-market date of the feature window close under an
explicitly declared IANA boundary timezone, excludes caller-declared
INCOMPLETE labels, purges TRAIN/VALIDATION samples whose actual label end
crosses the next-local-midnight exclusive boundary, and produces the fixed
split assignment schema/content identities, the split result identity, and
the existing ``SpecPin``(kind=SPLIT) for ``dataset_id`` integration. Label
completeness is never inferred; ``actual_label_end_time`` is the only purge
time fact.

The explicit immutable Transform Implementation Registry
(:mod:`market_vault.dataset.transform_models` and
:mod:`market_vault.dataset.transform_registry`) provides frozen transform
registration models, the exact-key registry (the complete v1
``module.path:function`` ``transform_ref`` string is the only lookup key),
strict FeatureSpec/LabelSpec compatibility preflight, exact parameter-schema
validation, and versioned deterministic implementation fingerprints that map
to the existing ``ImplementationPin`` entries of
``DatasetIdentityInput.implementations``. The registry resolves only explicit
built-in registrations; it never imports ``transform_ref``, never executes
an implementation, contains no built-in Feature or Label transform, and
does not compute any Feature or Label value.

This layer does not compute features or labels, execute transforms, build
samples or datasets, export Dataset Parquet, build the final DatasetManifest,
create DuckDB views, add CLI commands, or train models. The Canonical
manifest remains authoritative for Canonical builds; the Dataset layer only
references immutable Canonical builds and their stable identities.
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
from .split_models import (
    CHRONOLOGICAL_SPLIT_RESULT_ID_VERSION,
    CHRONOLOGICAL_SPLIT_SPEC_CONTENT_ID_VERSION,
    CHRONOLOGICAL_SPLIT_SPEC_SCHEMA_VERSION,
    CHRONOLOGICAL_SPLITTER_VERSION,
    LABEL_STATUS_COMPLETE,
    LABEL_STATUS_INCOMPLETE,
    REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY,
    REASON_CODE_ACTUAL_LABEL_END_CROSSES_VALIDATION_BOUNDARY,
    REASON_CODE_FEATURE_CLOSE_AFTER_TEST_END,
    REASON_CODE_INCOMPLETE_LABEL,
    SPLIT_ASSIGNMENT_RULE_FEATURE_WINDOW_CLOSE_DATE,
    SPLIT_ASSIGNMENT_SCHEMA_VERSION,
    SPLIT_INCOMPLETE_LABEL_POLICY_EXCLUDE,
    SPLIT_OUT_OF_RANGE_POLICY_EXCLUDE,
    SPLIT_PURGE_RULE_ACTUAL_LABEL_END,
    SPLIT_STATUS_ASSIGNED,
    SPLIT_STATUS_EXCLUDED,
    SPLIT_STATUS_PURGED,
    SPLIT_TEST,
    SPLIT_TRAIN,
    SPLIT_VALIDATION,
    ChronologicalSplitAssignment,
    ChronologicalSplitDiagnostics,
    ChronologicalSplitResult,
    ChronologicalSplitSample,
    ChronologicalSplitSpec,
    SplitValidationError,
    chronological_split_spec_content_id,
    chronological_split_spec_pin,
)
from .splits import (
    SPLIT_ASSIGNMENT_COLUMNS,
    assign_chronological_splits,
    chronological_split_result_id,
    split_assignment_content_id,
    split_assignment_schema,
    split_assignment_schema_id,
)
from .transform_models import (
    BOUNDARY_POLICY_NO_CROSS_TRADING_DAY,
    BOUNDARY_POLICY_PIT_WINDOW_ONLY,
    BOUNDARY_POLICY_SAME_MARKET_CALENDAR_DATE,
    MISSING_POLICY_EXCLUDE_SAMPLE,
    MISSING_POLICY_FAIL,
    MISSING_POLICY_LABEL_INCOMPLETE,
    PARAMETER_TYPE_BOOL,
    PARAMETER_TYPE_FLOAT64,
    PARAMETER_TYPE_INT64,
    PARAMETER_TYPE_STRING,
    TRANSFORM_IMPLEMENTATION_FINGERPRINT_VERSION,
    TRANSFORM_REGISTRY_CONTRACT_VERSION,
    ResolvedTransform,
    TransformParameterContract,
    TransformRegistration,
    TransformRegistryError,
    TransformWindowRequirement,
    WINDOW_BOUNDARY_EXCLUSIVE,
    WINDOW_BOUNDARY_INCLUSIVE,
    WINDOW_SOURCE_FIXED,
    WINDOW_SOURCE_LABEL_HORIZON,
    WINDOW_SOURCE_LABEL_OBSERVATION_WINDOW,
    WINDOW_SOURCE_NONE,
    WINDOW_SOURCE_PARAMETER,
    WINDOW_UNIT_BARS,
    WINDOW_UNIT_MINUTES,
    WINDOW_UNIT_NONE,
    transform_implementation_fingerprint,
    transform_implementation_pin,
)
from .transform_registry import TransformRegistry

__all__ = [
    "BOUNDARY_POLICY_NO_CROSS_TRADING_DAY",
    "BOUNDARY_POLICY_PIT_WINDOW_ONLY",
    "BOUNDARY_POLICY_SAME_MARKET_CALENDAR_DATE",
    "CHRONOLOGICAL_SPLIT_RESULT_ID_VERSION",
    "CHRONOLOGICAL_SPLIT_SPEC_CONTENT_ID_VERSION",
    "CHRONOLOGICAL_SPLIT_SPEC_SCHEMA_VERSION",
    "CHRONOLOGICAL_SPLITTER_VERSION",
    "DATASET_CONTENT_ID_VERSION",
    "DATASET_IDENTITY_ENCODING_VERSION",
    "DATASET_MANIFEST_SCHEMA_VERSION",
    "DATASET_SCHEMA_ID_VERSION",
    "FEATURE_LABEL_SPEC_CONTENT_ID_VERSION",
    "FEATURE_SPEC_SCHEMA_VERSION",
    "LABEL_SPEC_SCHEMA_VERSION",
    "LABEL_STATUS_COMPLETE",
    "LABEL_STATUS_INCOMPLETE",
    "MISSING_POLICY_EXCLUDE_SAMPLE",
    "MISSING_POLICY_FAIL",
    "MISSING_POLICY_LABEL_INCOMPLETE",
    "PARAMETER_TYPE_BOOL",
    "PARAMETER_TYPE_FLOAT64",
    "PARAMETER_TYPE_INT64",
    "PARAMETER_TYPE_STRING",
    "PIT_ASSEMBLER_VERSION",
    "PIT_ASSOCIATION_COLUMNS",
    "PIT_ASSOCIATION_SCHEMA_VERSION",
    "PIT_ROLE_FEATURE",
    "PIT_ROLE_LABEL",
    "PIT_SAMPLE_KEY_VERSION",
    "PIT_SAMPLE_VERSION_ID_VERSION",
    "REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY",
    "REASON_CODE_ACTUAL_LABEL_END_CROSSES_VALIDATION_BOUNDARY",
    "REASON_CODE_FEATURE_CLOSE_AFTER_TEST_END",
    "REASON_CODE_INCOMPLETE_LABEL",
    "SERIALIZATION_FORMAT_PARQUET",
    "SERIALIZATION_FORMAT_VERSION_PARQUET",
    "SPEC_KIND_FEATURE",
    "SPEC_KIND_LABEL",
    "SPEC_KIND_SPLIT",
    "SPLIT_ASSIGNMENT_COLUMNS",
    "SPLIT_ASSIGNMENT_RULE_FEATURE_WINDOW_CLOSE_DATE",
    "SPLIT_ASSIGNMENT_SCHEMA_VERSION",
    "SPLIT_INCOMPLETE_LABEL_POLICY_EXCLUDE",
    "SPLIT_OUT_OF_RANGE_POLICY_EXCLUDE",
    "SPLIT_PURGE_RULE_ACTUAL_LABEL_END",
    "SPLIT_STATUS_ASSIGNED",
    "SPLIT_STATUS_EXCLUDED",
    "SPLIT_STATUS_PURGED",
    "SPLIT_TEST",
    "SPLIT_TRAIN",
    "SPLIT_VALIDATION",
    "STATUS_COMPLETE",
    "STATUS_EMPTY",
    "SUPPORTED_LOGICAL_TYPES",
    "TRANSFORM_IMPLEMENTATION_FINGERPRINT_VERSION",
    "TRANSFORM_REGISTRY_CONTRACT_VERSION",
    "WINDOW_BOUNDARY_EXCLUSIVE",
    "WINDOW_BOUNDARY_INCLUSIVE",
    "WINDOW_SOURCE_FIXED",
    "WINDOW_SOURCE_LABEL_HORIZON",
    "WINDOW_SOURCE_LABEL_OBSERVATION_WINDOW",
    "WINDOW_SOURCE_NONE",
    "WINDOW_SOURCE_PARAMETER",
    "WINDOW_UNIT_BARS",
    "WINDOW_UNIT_MINUTES",
    "WINDOW_UNIT_NONE",
    "CanonicalBuildPin",
    "ChronologicalSplitAssignment",
    "ChronologicalSplitDiagnostics",
    "ChronologicalSplitResult",
    "ChronologicalSplitSample",
    "ChronologicalSplitSpec",
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
    "ResolvedTransform",
    "SourceSnapshotPin",
    "SpecParameter",
    "SpecPin",
    "SpecValidationError",
    "SpecVersionRequirements",
    "SplitValidationError",
    "TransformParameterContract",
    "TransformRegistration",
    "TransformRegistry",
    "TransformRegistryError",
    "TransformWindowRequirement",
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
    "assign_chronological_splits",
    "assemble_point_in_time_samples",
    "build_dataset_manifest",
    "chronological_split_result_id",
    "chronological_split_spec_content_id",
    "chronological_split_spec_pin",
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
    "split_assignment_content_id",
    "split_assignment_schema",
    "split_assignment_schema_id",
    "transform_implementation_fingerprint",
    "transform_implementation_pin",
    "validate_dataset_manifest",
    "write_dataset_manifest_atomic",
]
