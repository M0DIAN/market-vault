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
built-in registrations; it never imports ``transform_ref`` and never executes
an implementation.

The deterministic built-in Feature execution core (v0.5.0 PR-3;
:mod:`market_vault.dataset.feature_models`,
:mod:`market_vault.dataset.feature_registry`,
:mod:`market_vault.dataset.feature_execution`, and
:mod:`market_vault.dataset.feature_transforms`) executes eight basic OHLCV
Feature transforms (simple_return, log_return, rolling_mean, rolling_std,
rolling_volume_mean, volume_ratio, candle_range, candle_body) over the
PIT-selected Canonical rows with strict row binding, market/archive clock,
provenance, trailing-window contiguity, output-type, and finite-value
validation, producing explicit COMPLETE / EXCLUDED results under the frozen
invocation contract. The executor calls only the built-in registry's
function objects; no external registration can be injected.

The deterministic built-in Label execution core (v0.5.0 PR-4;
:mod:`market_vault.dataset.label_models`,
:mod:`market_vault.dataset.label_registry`,
:mod:`market_vault.dataset.label_execution`, and
:mod:`market_vault.dataset.label_transforms`) executes four built-in Label
transforms (forward_return, forward_direction,
maximum_favorable_excursion, maximum_adverse_excursion) over the exact
Feature-close anchor row and the PIT-selected future Label rows under the
FEATURE_CLOSE_ALIGNED alignment rule, proving required-input completeness
(exact horizon target, contiguous excursion observation window) and
producing explicit COMPLETE / INCOMPLETE results with
``actual_label_end_time`` taken from the last actually consumed Label row.
BARS horizons and observation windows only; MINUTES, TRADING_DAYS, and
cross-trading-day execution fail closed at registry preflight. The shared
PIT-to-Canonical binding and provenance verification lives in the private
:mod:`market_vault.dataset.execution_provenance` module, reused by both
executors.

The deterministic Dataset orchestration core (v0.5.0 PR-5;
:mod:`market_vault.dataset.orchestration_models` and
:mod:`market_vault.dataset.orchestration`) connects the shipped layers in
one pure in-memory, fail-closed pipeline: explicit supervised-build inputs,
scope/request validation, the authoritative logical Dataset schema
derivation, one PIT assembly, one built-in Feature execution and one
built-in Label execution over the same PIT result, strict cross-layer
sample binding, Feature EXCLUDED filtering, explicit
ChronologicalSplitSample construction, one chronological split / purge
invocation, the scope-wide CompletionSummary, the final logical rows under
the fixed physical sort (``code``, ``feature_window_close``,
``sample_key``), the merged Feature/Label ImplementationPins,
``logical_dataset_content_id``, ``DatasetIdentityInput``, and the
deterministic ``dataset_id``. Orchestration computes logical rows and
identities in memory only: it never writes files, never creates Dataset
directories, never writes Parquet, and never builds a DatasetManifest.

The deterministic Dataset materialization core (v0.5.0 PR-6;
:mod:`market_vault.dataset.materialization` and
:mod:`market_vault.dataset.materialization_models`) materializes one
verified :class:`DatasetOrchestrationResult` into an immutable, traceable,
fail-closed Dataset build directory: a single ``dataset.parquet`` with the
explicit logical schema mapped to PyArrow and fixed writer options and
metadata, deterministic Feature / Label / Split spec artifacts, the
deterministic non-identity ``build_report.json``, the existing
DatasetManifest core with exact :class:`DatasetOutputFile` byte facts, a
fixed same-filesystem staging directory, ``_SUCCESS`` written last, an
atomic no-overwrite rename to ``output_root / <dataset_id>``, strict
existing-build verification with idempotent return, and fail-closed
rejection of staging residue, conflicts, corruption, symlinks, and
junctions. The materializer re-verifies the PR-5 result and consumes only
its trusted output; it never re-executes Canonical reads, PIT assembly,
Feature / Label execution, or split / purge, and it never recomputes an
identity algorithm. ``built_at`` and output byte hashes are recorded facts
that never enter ``dataset_id``.

The verified Dataset reader (v0.5.0 PR-7;
:mod:`market_vault.dataset.reader` and
:mod:`market_vault.dataset.reader_models`) is the one public, read-only,
fail-closed read path into committed Dataset build directories:
``load_verified_dataset(build_dir)`` accepts one explicit final Dataset
directory (``<output_root>/<dataset_id>``) and independently rebuilds and
verifies the complete Dataset facts from the directory's own
``dataset.parquet``, ``manifest.json``, ``build_report.json``,
``feature_specs/``, ``label_specs/``, ``split_spec.yaml``, and
``_SUCCESS``: canonical manifest validation and bytes, the directory-name
binding, the exact artifact whitelist, ``_SUCCESS``, full
:class:`DatasetOutputFile` records with sizes and SHA-256s, Feature /
Label / Split artifact parse / pin / canonical-bytes verification, the
authoritative schema re-derivation, Parquet schema / metadata / rows /
logical content identity, physical row order, sample-key uniqueness,
scope and ``dataset_as_of`` binding, the split result re-derived from the
actual rows, the typed build-report record with its canonical bytes and
observable-fact bindings, and the fixed diagnostics matrix. It returns a
deeply immutable :class:`VerifiedDatasetBuild`; it never accepts a
``DatasetOrchestrationResult``, never re-executes PIT / Feature / Label /
split-or-materialization work, never scans for a ``latest`` directory,
and never writes, repairs, or deletes any file. Canonical pins, row-
version IDs, and gap references are verified through the manifest identity
contract; upstream Canonical build directories are never reloaded or
audited. Build-report execution counts that cannot be re-derived from the
final directory remain non-identity recorded facts validated by shape,
exact canonical bytes, the fixed diagnostics matrix, and every artifact-
observable cross-check.

The Sample Generation contract foundation (v0.6.0 PR-2;
:mod:`market_vault.dataset.sample_generation_models` and
:mod:`market_vault.dataset.sample_generation`) defines the frozen
generation-plan models, the strict generation-plan JSON parser, the
canonical generation-plan serializer, and the deterministic semantic
content identity over versioned generation inputs. It is the contract
foundation only: the Sample Generator core (PR-3), the Sample Generation
CLI (PR-4), and the Dataset Catalog (PR-5+) are not implemented. This layer
never reads or writes files, never reads specs or Canonical builds, never
uses the current time, never constructs a sample request, and never
orchestrates a Dataset build; the generation content ID never enters
``dataset_id`` and the generated output remains an ordinary
``market-vault-dataset-build-plan-v1`` document.

The Dataset CLI (v0.5.0 PR-8; :mod:`market_vault.dataset.cli` and
:mod:`market_vault.dataset.cli_models`) exposes three formal commands —
``dataset-build``, ``dataset-verify``, and ``dataset-inspect`` — as a thin
wrapper over the formal public chain: the verified Canonical reader, the
Feature / Label spec parsers, the typed PIT request / scope / split-spec
construction, the authoritative schema builder, the orchestrator, the
materializer, and the verified Dataset reader. ``dataset-build`` consumes
one strict, versioned build-plan JSON document whose bytes never enter any
Dataset identity; the CLI adds no second builder, no second validator, no
latest-directory scan, no automatic sample generation, no scope inference,
no settings.yaml / OpenD / network dependency, and no current time.
``dataset-verify`` and ``dataset-inspect`` are strictly read-only. The
end-to-end determinism and leakage regression (PR-9) and the v0.5.0 release
preparation (PR-10) are not implemented yet.

This layer does not create DuckDB views, does not add an API server or a
Python client, and does not train models, backtest, or trade. The Canonical
manifest remains authoritative for Canonical builds; the Dataset layer only
references immutable Canonical builds and their stable identities.
MarketVault's future read-only data-serving and ML usage are outside this
layer.
"""

from .content import dataset_schema_id, logical_dataset_content_id
from .encoding import DATASET_IDENTITY_ENCODING_VERSION, DatasetError
from .feature_execution import execute_builtin_features
from .feature_models import (
    FEATURE_EXECUTION_CONTRACT_VERSION,
    FEATURE_EXCLUSION_CROSS_MARKET_DATE,
    FEATURE_EXCLUSION_INSUFFICIENT_ROWS,
    FEATURE_EXCLUSION_NON_CONTIGUOUS_ROWS,
    FEATURE_TRANSFORM_CALL_CONTRACT_VERSION,
    FEATURE_VALUE_STATUS_COMPLETE,
    FEATURE_VALUE_STATUS_EXCLUDED,
    FeatureExecutionDiagnostics,
    FeatureExecutionError,
    FeatureExecutionResult,
    FeatureSampleResult,
    FeatureTransformInput,
    FeatureValueResult,
)
from .feature_registry import (
    built_in_feature_registrations,
    built_in_feature_registry,
)
from .identity import dataset_id
from .label_execution import execute_builtin_labels
from .label_models import (
    LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED,
    LABEL_EXECUTION_CONTRACT_VERSION,
    LABEL_INCOMPLETE_INSUFFICIENT_ROWS,
    LABEL_INCOMPLETE_MISSING_ANCHOR_ROW,
    LABEL_INCOMPLETE_MISSING_TARGET_ROW,
    LABEL_INCOMPLETE_NON_CONTIGUOUS_ROWS,
    LABEL_TRANSFORM_CALL_CONTRACT_VERSION,
    LabelExecutionDiagnostics,
    LabelExecutionError,
    LabelExecutionResult,
    LabelSampleResult,
    LabelTransformInput,
    LabelValueResult,
)
from .label_registry import (
    built_in_label_registrations,
    built_in_label_registry,
)
from .manifest import (
    build_dataset_manifest,
    serialize_dataset_manifest,
    validate_dataset_manifest,
    write_dataset_manifest_atomic,
)
from .materialization import materialize_dataset_artifacts
from .materialization_models import (
    DATASET_BUILD_REPORT_FILENAME,
    DATASET_BUILD_REPORT_SCHEMA_VERSION,
    DATASET_CONTENT_ROLE_BUILD_REPORT,
    DATASET_CONTENT_ROLE_FEATURE_SPEC,
    DATASET_CONTENT_ROLE_LABEL_SPEC,
    DATASET_CONTENT_ROLE_LOGICAL_ROWS,
    DATASET_CONTENT_ROLE_SPLIT_SPEC,
    DATASET_FEATURE_SPECS_DIRNAME,
    DATASET_LABEL_SPECS_DIRNAME,
    DATASET_MANIFEST_FILENAME,
    DATASET_MATERIALIZER_VERSION,
    DATASET_OUTPUT_ROLE_BUILD_REPORT,
    DATASET_OUTPUT_ROLE_DATASET,
    DATASET_OUTPUT_ROLE_FEATURE_SPEC,
    DATASET_OUTPUT_ROLE_LABEL_SPEC,
    DATASET_OUTPUT_ROLE_SPLIT_SPEC,
    DATASET_PARQUET_FILENAME,
    DATASET_SPEC_ARTIFACT_VERSION,
    DATASET_SPLIT_SPEC_FILENAME,
    DATASET_SUCCESS_FILENAME,
    DatasetMaterializationError,
    DatasetMaterializationResult,
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
from .orchestration import orchestrate_dataset_build
from .orchestration_models import (
    DATASET_COMPLETION_REASON_FEATURE_EXCLUDED,
    DATASET_COMPLETION_REASON_FEATURE_EXCLUDED_AND_LABEL_INCOMPLETE,
    DATASET_COMPLETION_REASON_LABEL_INCOMPLETE,
    DATASET_COMPLETION_REASON_NO_SAMPLE_REQUEST,
    DATASET_KIND_SUPERVISED,
    DATASET_ORCHESTRATION_CONTRACT_VERSION,
    DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY,
    DatasetOrchestrationDiagnostics,
    DatasetOrchestrationError,
    DatasetOrchestrationResult,
    dataset_orchestration_schema,
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
from .reader import load_verified_dataset
from .reader_models import (
    DATASET_READER_CONTRACT_VERSION,
    DatasetArtifactValidationError,
    DatasetBuildReportRecord,
    DatasetOutputLayoutRecord,
    VerifiedDatasetBuild,
)
from .sample_generation import (
    parse_sample_generation_plan_bytes,
    sample_generation_content_id,
    serialize_sample_generation_plan,
)
from .sample_generation_models import (
    SAMPLE_GENERATION_CONTRACT_VERSION,
    SAMPLE_GENERATION_CONTENT_ID_VERSION,
    SAMPLE_GENERATION_PLAN_SCHEMA_VERSION,
    SAMPLE_GENERATION_RULE_SCHEMA_VERSION,
    SampleGenerationError,
    SampleGenerationIdentityInput,
    SampleGenerationPlan,
    SampleGenerationRule,
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
    "DATASET_BUILD_REPORT_FILENAME",
    "DATASET_BUILD_REPORT_SCHEMA_VERSION",
    "DATASET_COMPLETION_REASON_FEATURE_EXCLUDED",
    "DATASET_COMPLETION_REASON_FEATURE_EXCLUDED_AND_LABEL_INCOMPLETE",
    "DATASET_COMPLETION_REASON_LABEL_INCOMPLETE",
    "DATASET_COMPLETION_REASON_NO_SAMPLE_REQUEST",
    "DATASET_CONTENT_ROLE_BUILD_REPORT",
    "DATASET_CONTENT_ROLE_FEATURE_SPEC",
    "DATASET_CONTENT_ROLE_LABEL_SPEC",
    "DATASET_CONTENT_ROLE_LOGICAL_ROWS",
    "DATASET_CONTENT_ROLE_SPLIT_SPEC",
    "DATASET_FEATURE_SPECS_DIRNAME",
    "DATASET_KIND_SUPERVISED",
    "DATASET_LABEL_SPECS_DIRNAME",
    "DATASET_MANIFEST_FILENAME",
    "DATASET_MATERIALIZER_VERSION",
    "DATASET_ORCHESTRATION_CONTRACT_VERSION",
    "DATASET_OUTPUT_ROLE_BUILD_REPORT",
    "DATASET_OUTPUT_ROLE_DATASET",
    "DATASET_OUTPUT_ROLE_FEATURE_SPEC",
    "DATASET_OUTPUT_ROLE_LABEL_SPEC",
    "DATASET_OUTPUT_ROLE_SPLIT_SPEC",
    "DATASET_PARQUET_FILENAME",
    "DATASET_READER_CONTRACT_VERSION",
    "DATASET_SPEC_ARTIFACT_VERSION",
    "DATASET_SPLIT_SPEC_FILENAME",
    "DATASET_SUCCESS_FILENAME",
    "CHRONOLOGICAL_SPLIT_SPEC_CONTENT_ID_VERSION",
    "CHRONOLOGICAL_SPLIT_SPEC_SCHEMA_VERSION",
    "CHRONOLOGICAL_SPLITTER_VERSION",
    "DATASET_CONTENT_ID_VERSION",
    "DATASET_IDENTITY_ENCODING_VERSION",
    "DATASET_MANIFEST_SCHEMA_VERSION",
    "DATASET_SCHEMA_ID_VERSION",
    "FEATURE_LABEL_SPEC_CONTENT_ID_VERSION",
    "FEATURE_EXECUTION_CONTRACT_VERSION",
    "FEATURE_EXCLUSION_CROSS_MARKET_DATE",
    "FEATURE_EXCLUSION_INSUFFICIENT_ROWS",
    "FEATURE_EXCLUSION_NON_CONTIGUOUS_ROWS",
    "FEATURE_SPEC_SCHEMA_VERSION",
    "FEATURE_TRANSFORM_CALL_CONTRACT_VERSION",
    "FEATURE_VALUE_STATUS_COMPLETE",
    "FEATURE_VALUE_STATUS_EXCLUDED",
    "LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED",
    "LABEL_EXECUTION_CONTRACT_VERSION",
    "LABEL_INCOMPLETE_INSUFFICIENT_ROWS",
    "LABEL_INCOMPLETE_MISSING_ANCHOR_ROW",
    "LABEL_INCOMPLETE_MISSING_TARGET_ROW",
    "LABEL_INCOMPLETE_NON_CONTIGUOUS_ROWS",
    "LABEL_SPEC_SCHEMA_VERSION",
    "LABEL_STATUS_COMPLETE",
    "LABEL_STATUS_INCOMPLETE",
    "LABEL_TRANSFORM_CALL_CONTRACT_VERSION",
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
    "SAMPLE_GENERATION_CONTRACT_VERSION",
    "SAMPLE_GENERATION_CONTENT_ID_VERSION",
    "SAMPLE_GENERATION_PLAN_SCHEMA_VERSION",
    "SAMPLE_GENERATION_RULE_SCHEMA_VERSION",
    "DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY",
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
    "DatasetArtifactValidationError",
    "DatasetBuildReportRecord",
    "DatasetError",
    "DatasetMaterializationError",
    "DatasetMaterializationResult",
    "DatasetOrchestrationDiagnostics",
    "DatasetOrchestrationError",
    "DatasetOrchestrationResult",
    "DatasetOutputLayoutRecord",
    "FeatureExecutionDiagnostics",
    "FeatureExecutionError",
    "FeatureExecutionResult",
    "FeatureSampleResult",
    "FeatureSpec",
    "FeatureTransformInput",
    "FeatureValueResult",
    "GapReference",
    "ImplementationPin",
    "LabelExecutionDiagnostics",
    "LabelExecutionError",
    "LabelExecutionResult",
    "LabelHorizon",
    "LabelObservationWindow",
    "LabelSampleResult",
    "LabelSpec",
    "LabelTransformInput",
    "LabelValueResult",
    "ResolvedTransform",
    "SampleGenerationError",
    "SampleGenerationIdentityInput",
    "SampleGenerationPlan",
    "SampleGenerationRule",
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
    "built_in_feature_registrations",
    "built_in_feature_registry",
    "built_in_label_registrations",
    "built_in_label_registry",
    "chronological_split_result_id",
    "chronological_split_spec_content_id",
    "chronological_split_spec_pin",
    "dataset_id",
    "dataset_orchestration_schema",
    "dataset_schema_id",
    "execute_builtin_features",
    "execute_builtin_labels",
    "feature_label_spec_content_id",
    "feature_label_spec_pin",
    "load_feature_spec",
    "load_label_spec",
    "load_verified_dataset",
    "logical_dataset_content_id",
    "materialize_dataset_artifacts",
    "orchestrate_dataset_build",
    "parse_feature_spec",
    "parse_label_spec",
    "parse_sample_generation_plan_bytes",
    "pit_association_content_id",
    "pit_association_schema",
    "pit_association_schema_id",
    "pit_sample_key",
    "pit_sample_version_id",
    "sample_generation_content_id",
    "serialize_dataset_manifest",
    "serialize_sample_generation_plan",
    "split_assignment_content_id",
    "split_assignment_schema",
    "split_assignment_schema_id",
    "transform_implementation_fingerprint",
    "transform_implementation_pin",
    "validate_dataset_manifest",
    "VerifiedDatasetBuild",
    "write_dataset_manifest_atomic",
]
