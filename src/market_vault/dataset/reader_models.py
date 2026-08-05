"""Frozen models of the verified Dataset reader contract (v0.5.0 PR-7).

This module defines the reader layer's own contract surface:

- :data:`DATASET_READER_CONTRACT_VERSION` — the version of the reader code
  contract. It describes the reader only; it never enters ``dataset_id``,
  the manifest, the Parquet metadata, or any artifact;
- :class:`DatasetArtifactValidationError` — the single public fail-closed
  error of the verified Dataset reader (a subclass of
  :class:`DatasetError`);
- :class:`DatasetOutputLayoutRecord` — the frozen record of the fixed
  output layout filenames (every value must equal the PR-6 fixed
  constant);
- :class:`DatasetBuildReportRecord` — the frozen typed record of
  ``build_report.json`` (exact field set, fixed version fields, real
  non-negative counts, UTC microsecond datetimes, the exact output
  layout);
- :class:`VerifiedDatasetBuild` — the frozen, deeply immutable result of
  one verified Dataset read. Construction independently re-verifies every
  invariant (fail closed), so a manually constructed or
  ``dataclasses.replace``-modified object can never carry inconsistent
  facts.

Nothing here reads or writes the filesystem. ``dataset_id`` and every
existing identity algorithm are untouched; the reader contract version and
the build-report facts are recorded, never identity-bearing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .artifact_serialization import _canonical_json_bytes
from .content import dataset_schema_id, logical_dataset_content_id
from .encoding import DatasetError, normalize_utc_datetime
from .manifest import DatasetManifest, serialize_dataset_manifest
from .materialization_models import (
    DATASET_BUILD_REPORT_FILENAME,
    DATASET_BUILD_REPORT_SCHEMA_VERSION,
    DATASET_FEATURE_SPECS_DIRNAME,
    DATASET_LABEL_SPECS_DIRNAME,
    DATASET_MANIFEST_FILENAME,
    DATASET_MATERIALIZER_VERSION,
    DATASET_PARQUET_FILENAME,
    DATASET_SPLIT_SPEC_FILENAME,
    DATASET_SUCCESS_FILENAME,
)
from .models import (
    DATASET_MANIFEST_SCHEMA_VERSION,
    SERIALIZATION_FORMAT_PARQUET,
    SERIALIZATION_FORMAT_VERSION_PARQUET,
    STATUS_COMPLETE,
    STATUS_EMPTY,
    DatasetSchema,
)
from .orchestration_models import (
    DATASET_KIND_SUPERVISED,
    DATASET_ORCHESTRATION_CONTRACT_VERSION,
    DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY,
    DatasetOrchestrationDiagnostics,
    dataset_orchestration_schema,
)
from .spec_models import FeatureSpec, LabelSpec
from .specs import feature_label_spec_pin
from .split_models import (
    ChronologicalSplitResult,
    ChronologicalSplitSample,
    ChronologicalSplitSpec,
    chronological_split_spec_pin,
)
from .splits import assign_chronological_splits

__all__ = [
    "DATASET_READER_CONTRACT_VERSION",
    "DatasetArtifactValidationError",
    "DatasetBuildReportRecord",
    "DatasetOutputLayoutRecord",
    "VerifiedDatasetBuild",
]

#: Version of the verified Dataset reader code contract. It is carried on
#: every :class:`VerifiedDatasetBuild` and describes the reader only: it
#: never enters ``dataset_id``, the manifest, the Parquet metadata, or any
#: artifact.
DATASET_READER_CONTRACT_VERSION = "market-vault-verified-dataset-reader-v1"

_DATASET_ID_RE = re.compile(r"^[0-9a-f]{64}$")

#: Fixed output layout field names of ``build_report.json``.
_LAYOUT_FIELD_NAMES = (
    "dataset_parquet_filename",
    "manifest_filename",
    "build_report_filename",
    "split_spec_filename",
    "success_filename",
    "feature_specs_dirname",
    "label_specs_dirname",
)

#: Exact fixed output layout mapping (every value is a PR-6 constant).
_EXPECTED_LAYOUT = {
    "dataset_parquet_filename": DATASET_PARQUET_FILENAME,
    "manifest_filename": DATASET_MANIFEST_FILENAME,
    "build_report_filename": DATASET_BUILD_REPORT_FILENAME,
    "split_spec_filename": DATASET_SPLIT_SPEC_FILENAME,
    "success_filename": DATASET_SUCCESS_FILENAME,
    "feature_specs_dirname": DATASET_FEATURE_SPECS_DIRNAME,
    "label_specs_dirname": DATASET_LABEL_SPECS_DIRNAME,
}


class DatasetArtifactValidationError(DatasetError):
    """Structured fail-closed failure of the verified Dataset reader.

    Raised for invalid build-directory inputs, symlink / junction
    rejections, missing or unexpected entries, invalid ``_SUCCESS``,
    non-canonical or identity-inconsistent manifests, output-file record /
    size / hash mismatches, spec artifact parse / pin / canonical-bytes
    failures, build-report shape or canonical-bytes failures, Parquet
    schema / metadata / row / content-identity failures, physical row
    order and sample-uniqueness violations, scope and ``dataset_as_of``
    binding violations, split re-derivation mismatches, and
    :class:`VerifiedDatasetBuild` self-validation failures.

    Every documented failure of the underlying layers (``DatasetError``
    and its layer subclasses, ``OSError``, ``UnicodeError``, JSON
    validation errors, documented PyArrow errors, and the documented
    ``TypeError`` / ``ValueError`` / ``KeyError``) is converted to this
    error with its ``__cause__`` preserved; an already-raised
    :class:`DatasetArtifactValidationError` is never double-wrapped.
    There is no "warn and continue" path and no partial result is ever
    returned.
    """


def _iso(value: datetime) -> str:
    """UTC microsecond ISO string of one instant (the build-report
    datetime representation)."""
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _report_payload_from_record(record: "DatasetBuildReportRecord") -> dict:
    """The exact deterministic ``build_report.json`` payload of one typed
    :class:`DatasetBuildReportRecord`.

    The reader regenerates the canonical build-report bytes from the
    parsed strict typed record (never from a
    ``DatasetOrchestrationResult``) and requires the actual file bytes to
    be byte-equal.
    """
    layout = record.output_layout
    return {
        "report_schema_version": record.report_schema_version,
        "materializer_version": record.materializer_version,
        "dataset_id": record.dataset_id,
        "dataset_kind": record.dataset_kind,
        "status": record.status,
        "built_at": _iso(record.built_at),
        "dataset_as_of": (
            _iso(record.dataset_as_of) if record.dataset_as_of is not None else None
        ),
        "dataset_schema_id": record.dataset_schema_id,
        "logical_dataset_content_id": record.logical_dataset_content_id,
        "logical_row_count": record.logical_row_count,
        "orchestration_contract_version": record.orchestration_contract_version,
        "row_order": record.row_order,
        "manifest_schema_version": record.manifest_schema_version,
        "serialization_format": record.serialization_format,
        "serialization_format_version": record.serialization_format_version,
        "feature_spec_count": record.feature_spec_count,
        "label_spec_count": record.label_spec_count,
        "canonical_build_pin_count": record.canonical_build_pin_count,
        "canonical_row_version_count": record.canonical_row_version_count,
        "completion_complete_key_count": record.completion_complete_key_count,
        "completion_incomplete_key_count": record.completion_incomplete_key_count,
        "completion_missing_key_count": record.completion_missing_key_count,
        "request_count": record.request_count,
        "pit_sample_count": record.pit_sample_count,
        "feature_complete_sample_count": record.feature_complete_sample_count,
        "feature_excluded_sample_count": record.feature_excluded_sample_count,
        "label_complete_sample_count": record.label_complete_sample_count,
        "label_incomplete_sample_count": record.label_incomplete_sample_count,
        "split_sample_count": record.split_sample_count,
        "assigned_sample_count": record.assigned_sample_count,
        "purged_sample_count": record.purged_sample_count,
        "excluded_sample_count": record.excluded_sample_count,
        "split_spec_content_id": record.split_spec_content_id,
        "split_result_id": record.split_result_id,
        "output_layout": {
            "dataset_parquet_filename": layout.dataset_parquet_filename,
            "manifest_filename": layout.manifest_filename,
            "build_report_filename": layout.build_report_filename,
            "split_spec_filename": layout.split_spec_filename,
            "success_filename": layout.success_filename,
            "feature_specs_dirname": layout.feature_specs_dirname,
            "label_specs_dirname": layout.label_specs_dirname,
        },
    }


def _row_field_indexes(schema: DatasetSchema) -> dict[str, int]:
    """Field name -> column index, resolved from the schema field names
    (never hardcoded numeric positions)."""
    return {field.name: index for index, field in enumerate(schema.fields)}


def _split_samples_from_rows(rows, schema: DatasetSchema):
    """Reconstruct the explicit :class:`ChronologicalSplitSample` facts of
    every final Dataset row (pure verification input; Feature and Label
    execution are never re-run and no stored assignment is used as a
    derivation input)."""
    indexes = _row_field_indexes(schema)
    return tuple(
        ChronologicalSplitSample(
            sample_key=row[indexes["sample_key"]],
            sample_version_id=row[indexes["sample_version_id"]],
            feature_window_close=row[indexes["feature_window_close"]],
            label_status=row[indexes["label_status"]],
            actual_label_end_time=row[indexes["actual_label_end_time"]],
        )
        for row in rows
    )


def _verify_row_assignment_columns(
    rows, schema: DatasetSchema, split_result: ChronologicalSplitResult
) -> None:
    """Every stored split assignment column of every Dataset row must
    exactly equal the re-derived assignment for that ``sample_key``."""
    indexes = _row_field_indexes(schema)
    by_key = {assignment.sample_key: assignment for assignment in split_result.assignments}
    for row in rows:
        assignment = by_key[row[indexes["sample_key"]]]
        for column in (
            "feature_window_close_date",
            "nominal_split",
            "final_split",
            "assignment_status",
            "reason_code",
            "purge_boundary",
        ):
            if row[indexes[column]] != getattr(assignment, column):
                raise DatasetArtifactValidationError(
                    f"Dataset row for sample {assignment.sample_key} stored "
                    f"{column} {row[indexes[column]]!r} does not match the "
                    f"re-derived split assignment "
                    f"{getattr(assignment, column)!r}"
                )


def _verify_verified_rows(rows, *, schema: DatasetSchema, manifest) -> None:
    """The single shared independent row self-validation of a verified
    Dataset (fail closed).

    Used by the public reader (``market_vault.dataset.reader``) and by
    :class:`VerifiedDatasetBuild` construction, so the two contracts can
    never drift. Verifies:

    1. strict tuple-of-tuples rows with the exact schema field count;
    2. the recomputed ``logical_dataset_content_id`` under the
       authoritative schema (this also enforces every scalar type,
       nullability, and NaN / Infinity rejection through the identity
       encoding);
    3. globally unique ``sample_key`` values;
    4. every row ``code`` belongs to ``manifest.scope.symbols``;
    5. the ``dataset_as_of`` contract (field absent when the manifest
       value is null; present and exactly equal to the manifest value on
       every row otherwise);
    6. the fixed physical row order ``code`` ASC,
       ``feature_window_close`` ASC, ``sample_key`` ASC.

    Field indexes are always resolved from the schema field names, never
    from hardcoded numeric positions. The physical-order check is
    independent of the logical content ID, which is row-order-irrelevant
    by contract: a reversed but otherwise identical row set keeps the
    same content ID and must still fail.
    """
    if not isinstance(rows, tuple):
        raise DatasetArtifactValidationError(
            "rows must be a tuple of schema-ordered immutable tuples"
        )
    for row in rows:
        if not isinstance(row, tuple):
            raise DatasetArtifactValidationError(
                "every row must be an immutable tuple; list, generator, "
                "string, and bytes rows are rejected and never silently "
                "converted"
            )
        if len(row) != len(schema.fields):
            raise DatasetArtifactValidationError(
                f"every row must carry exactly the schema field count, got "
                f"{len(row)} for a schema with {len(schema.fields)} fields"
            )
    mappings = tuple(
        dict(zip((field.name for field in schema.fields), row)) for row in rows
    )
    if (
        logical_dataset_content_id(schema, mappings)
        != manifest.logical_dataset_content_id
    ):
        raise DatasetArtifactValidationError(
            "recomputed logical_dataset_content_id does not match the "
            "manifest"
        )
    indexes = _row_field_indexes(schema)
    code_index = indexes["code"]
    sample_key_index = indexes["sample_key"]
    feature_close_index = indexes["feature_window_close"]
    if len({row[sample_key_index] for row in rows}) != len(rows):
        raise DatasetArtifactValidationError(
            "Dataset rows must not contain duplicate sample_key values"
        )
    symbols = set(manifest.scope.symbols)
    for row in rows:
        if row[code_index] not in symbols:
            raise DatasetArtifactValidationError(
                f"Dataset row code {row[code_index]!r} is outside the "
                f"manifest scope symbols"
            )
    if manifest.dataset_as_of is None:
        if "dataset_as_of" in indexes:
            raise DatasetArtifactValidationError(
                "manifest dataset_as_of is null but the schema carries a "
                "dataset_as_of field"
            )
    else:
        if "dataset_as_of" not in indexes:
            raise DatasetArtifactValidationError(
                "manifest dataset_as_of is set but the schema carries no "
                "dataset_as_of field"
            )
        as_of_index = indexes["dataset_as_of"]
        for row in rows:
            if row[as_of_index] != manifest.dataset_as_of:
                raise DatasetArtifactValidationError(
                    "Dataset row dataset_as_of must equal the manifest "
                    "dataset_as_of"
                )
    ordered = tuple(
        sorted(
            rows,
            key=lambda row: (
                row[code_index],
                row[feature_close_index],
                row[sample_key_index],
            ),
        )
    )
    if rows != ordered:
        raise DatasetArtifactValidationError(
            "Dataset physical row order must be exactly code ASC, "
            "feature_window_close ASC, sample_key ASC"
        )


@dataclass(frozen=True)
class DatasetOutputLayoutRecord:
    """The fixed output layout of one Dataset build directory.

    Every value must exactly equal the PR-6 fixed artifact name constant;
    a record carrying any other filename fails at construction.
    """

    dataset_parquet_filename: str
    manifest_filename: str
    build_report_filename: str
    split_spec_filename: str
    success_filename: str
    feature_specs_dirname: str
    label_specs_dirname: str

    def __post_init__(self) -> None:
        for name in _LAYOUT_FIELD_NAMES:
            value = getattr(self, name)
            expected = _EXPECTED_LAYOUT[name]
            if not isinstance(value, str) or value != expected:
                raise DatasetArtifactValidationError(
                    f"output layout {name} must be the fixed value {expected!r}, "
                    f"got {value!r}"
                )


@dataclass(frozen=True)
class DatasetBuildReportRecord:
    """The frozen typed record of ``build_report.json`` (exact field set).

    Carries every formal field of the deterministic non-identity build
    report: the fixed report schema / materializer / orchestration /
    row-order / manifest / serialization version facts, the dataset
    identity facts, status and timestamps (UTC microseconds), the real
    non-negative execution counts, the stable split spec content ID and
    split result ID, and the exact output layout. Construction validates
    the exact field set contract: fixed version fields must equal the
    current constants, ``dataset_id`` must be strict lowercase 64-hex,
    counts must be real non-negative integers, timestamps must be
    timezone-aware (normalized to UTC microseconds), the split IDs must
    be 64-hex, and ``status`` must be consistent with
    ``logical_row_count``. The fixed orchestration diagnostics matrix is
    validated by :class:`VerifiedDatasetBuild`, which carries the scope.
    """

    report_schema_version: str
    materializer_version: str
    dataset_id: str
    dataset_kind: str
    status: str
    built_at: datetime
    dataset_as_of: datetime | None
    dataset_schema_id: str
    logical_dataset_content_id: str
    logical_row_count: int
    orchestration_contract_version: str
    row_order: str
    manifest_schema_version: str
    serialization_format: str
    serialization_format_version: str
    feature_spec_count: int
    label_spec_count: int
    canonical_build_pin_count: int
    canonical_row_version_count: int
    completion_complete_key_count: int
    completion_incomplete_key_count: int
    completion_missing_key_count: int
    request_count: int
    pit_sample_count: int
    feature_complete_sample_count: int
    feature_excluded_sample_count: int
    label_complete_sample_count: int
    label_incomplete_sample_count: int
    split_sample_count: int
    assigned_sample_count: int
    purged_sample_count: int
    excluded_sample_count: int
    split_spec_content_id: str
    split_result_id: str
    output_layout: DatasetOutputLayoutRecord

    def __post_init__(self) -> None:
        try:
            self._revalidate()
        except DatasetArtifactValidationError:
            raise
        except (DatasetError, TypeError, ValueError, KeyError) as exc:
            raise DatasetArtifactValidationError(
                f"invalid DatasetBuildReportRecord: {exc}"
            ) from exc

    def _revalidate(self) -> None:
        if self.report_schema_version != DATASET_BUILD_REPORT_SCHEMA_VERSION:
            raise DatasetArtifactValidationError(
                f"report_schema_version must be "
                f"{DATASET_BUILD_REPORT_SCHEMA_VERSION}, got "
                f"{self.report_schema_version!r}"
            )
        if self.materializer_version != DATASET_MATERIALIZER_VERSION:
            raise DatasetArtifactValidationError(
                f"materializer_version must be {DATASET_MATERIALIZER_VERSION}, "
                f"got {self.materializer_version!r}"
            )
        if not isinstance(self.dataset_id, str) or not _DATASET_ID_RE.fullmatch(
            self.dataset_id
        ):
            raise DatasetArtifactValidationError(
                f"dataset_id must be a 64-character lowercase SHA-256 hex "
                f"string, got {self.dataset_id!r}"
            )
        if self.dataset_kind != DATASET_KIND_SUPERVISED:
            raise DatasetArtifactValidationError(
                f"dataset_kind must be {DATASET_KIND_SUPERVISED}, got "
                f"{self.dataset_kind!r}"
            )
        if self.status not in (STATUS_COMPLETE, STATUS_EMPTY):
            raise DatasetArtifactValidationError(
                f"status must be {STATUS_COMPLETE} or {STATUS_EMPTY}, got "
                f"{self.status!r}"
            )
        if (
            not isinstance(self.built_at, datetime)
            or self.built_at.tzinfo is None
        ):
            raise DatasetArtifactValidationError(
                "built_at must be a timezone-aware datetime"
            )
        object.__setattr__(
            self, "built_at", normalize_utc_datetime(self.built_at, "built_at")
        )
        if self.dataset_as_of is not None:
            if (
                not isinstance(self.dataset_as_of, datetime)
                or self.dataset_as_of.tzinfo is None
            ):
                raise DatasetArtifactValidationError(
                    "dataset_as_of must be a timezone-aware datetime or null"
                )
            object.__setattr__(
                self,
                "dataset_as_of",
                normalize_utc_datetime(self.dataset_as_of, "dataset_as_of"),
            )
        for name in (
            "dataset_schema_id",
            "logical_dataset_content_id",
            "split_spec_content_id",
            "split_result_id",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not _DATASET_ID_RE.fullmatch(value):
                raise DatasetArtifactValidationError(
                    f"{name} must be a 64-character lowercase SHA-256 hex "
                    f"string, got {value!r}"
                )
        for name in (
            "logical_row_count",
            "feature_spec_count",
            "label_spec_count",
            "canonical_build_pin_count",
            "canonical_row_version_count",
            "completion_complete_key_count",
            "completion_incomplete_key_count",
            "completion_missing_key_count",
            "request_count",
            "pit_sample_count",
            "feature_complete_sample_count",
            "feature_excluded_sample_count",
            "label_complete_sample_count",
            "label_incomplete_sample_count",
            "split_sample_count",
            "assigned_sample_count",
            "purged_sample_count",
            "excluded_sample_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise DatasetArtifactValidationError(
                    f"{name} must be a non-negative real integer, got {value!r}"
                )
        if self.orchestration_contract_version != DATASET_ORCHESTRATION_CONTRACT_VERSION:
            raise DatasetArtifactValidationError(
                f"orchestration_contract_version must be "
                f"{DATASET_ORCHESTRATION_CONTRACT_VERSION}, got "
                f"{self.orchestration_contract_version!r}"
            )
        if self.row_order != DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY:
            raise DatasetArtifactValidationError(
                f"row_order must be "
                f"{DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY}, got "
                f"{self.row_order!r}"
            )
        if self.manifest_schema_version != DATASET_MANIFEST_SCHEMA_VERSION:
            raise DatasetArtifactValidationError(
                f"manifest_schema_version must be "
                f"{DATASET_MANIFEST_SCHEMA_VERSION}, got "
                f"{self.manifest_schema_version!r}"
            )
        if self.serialization_format != SERIALIZATION_FORMAT_PARQUET:
            raise DatasetArtifactValidationError(
                f"serialization_format must be {SERIALIZATION_FORMAT_PARQUET}, "
                f"got {self.serialization_format!r}"
            )
        if (
            self.serialization_format_version
            != SERIALIZATION_FORMAT_VERSION_PARQUET
        ):
            raise DatasetArtifactValidationError(
                f"serialization_format_version must be "
                f"{SERIALIZATION_FORMAT_VERSION_PARQUET}, got "
                f"{self.serialization_format_version!r}"
            )
        if not isinstance(self.output_layout, DatasetOutputLayoutRecord):
            raise DatasetArtifactValidationError(
                f"output_layout must be a DatasetOutputLayoutRecord, got "
                f"{type(self.output_layout).__name__}"
            )
        if self.status == STATUS_EMPTY and self.logical_row_count != 0:
            raise DatasetArtifactValidationError(
                "status EMPTY requires logical_row_count == 0"
            )
        if self.status == STATUS_COMPLETE and self.logical_row_count == 0:
            raise DatasetArtifactValidationError(
                "status COMPLETE requires at least one logical row; zero rows "
                "must be EMPTY"
            )


@dataclass(frozen=True)
class VerifiedDatasetBuild:
    """A fully verified immutable Dataset build artifact.

    Produced exclusively by :func:`market_vault.dataset.reader.
    load_verified_dataset`; every field is re-validated against the
    manifest, the actual artifacts, and the reconstructed facts.
    ``rows`` are strict schema-ordered tuples (no dicts, no pandas
    objects); ``manifest`` is the frozen typed :class:`DatasetManifest`;
    ``feature_specs`` / ``label_specs`` are frozen typed spec tuples in
    the manifest pin order; ``split_spec`` is the frozen parsed split
    spec; ``split_result`` is the :class:`ChronologicalSplitResult`
    re-derived from the actual Dataset rows; ``build_report`` is the
    frozen typed :class:`DatasetBuildReportRecord`; ``manifest_payload``
    and ``build_report_payload`` are the original verified canonical
    bytes; ``build_path`` is the lexically absolute build directory (it
    only describes the location and never enters any identity).

    The model is deeply immutable and carries no mutable dict, mutable
    list, pandas DataFrame, unverified PyArrow Table, file handle,
    temporary path, current time, elapsed time, arbitrary metadata,
    logger, or callback.

    Construction independently re-verifies every invariant (fail closed):
    the reader contract version; the dataset ID format; status / row-count
    consistency; the manifest bindings (dataset ID, kind, status, built_at,
    ``dataset_as_of``, schema, row count); the canonical manifest payload;
    the strict tuple-of-tuples rows with the exact schema field count; the
    recomputed ``logical_dataset_content_id``; the Feature / Label spec
    pins in manifest order and the split spec pin; the authoritative
    schema re-derivation and its schema ID; the split result re-derived
    from the rows (including every stored assignment column of every row);
    the build-report bindings to the manifest and the re-derived split
    result; the canonical build-report payload; the fixed orchestration
    diagnostics matrix over the recorded counts; and the build-path rules
    (absolute, no ``.`` / ``..`` lexical components,
    ``build_path.name == dataset_id``). A manually constructed or
    ``dataclasses.replace``-modified inconsistent object fails closed.
    """

    reader_contract_version: str
    dataset_id: str
    dataset_kind: str
    status: str
    built_at: datetime
    dataset_as_of: datetime | None
    schema: DatasetSchema
    rows: tuple[tuple[object, ...], ...]
    manifest: DatasetManifest
    feature_specs: tuple[FeatureSpec, ...]
    label_specs: tuple[LabelSpec, ...]
    split_spec: ChronologicalSplitSpec
    split_result: ChronologicalSplitResult
    build_report: DatasetBuildReportRecord
    manifest_payload: bytes
    build_report_payload: bytes
    build_path: Path

    def __post_init__(self) -> None:
        try:
            self._revalidate()
        except DatasetArtifactValidationError:
            raise
        except (DatasetError, TypeError, ValueError, KeyError) as exc:
            raise DatasetArtifactValidationError(
                f"invalid VerifiedDatasetBuild: {exc}"
            ) from exc

    def _revalidate(self) -> None:
        if self.reader_contract_version != DATASET_READER_CONTRACT_VERSION:
            raise DatasetArtifactValidationError(
                f"reader_contract_version must be "
                f"{DATASET_READER_CONTRACT_VERSION}, got "
                f"{self.reader_contract_version!r}"
            )
        if not isinstance(self.dataset_id, str) or not _DATASET_ID_RE.fullmatch(
            self.dataset_id
        ):
            raise DatasetArtifactValidationError(
                f"dataset_id must be a 64-character lowercase SHA-256 hex "
                f"string, got {self.dataset_id!r}"
            )
        if self.dataset_kind != DATASET_KIND_SUPERVISED:
            raise DatasetArtifactValidationError(
                f"dataset_kind must be {DATASET_KIND_SUPERVISED}, got "
                f"{self.dataset_kind!r}"
            )
        if self.status not in (STATUS_COMPLETE, STATUS_EMPTY):
            raise DatasetArtifactValidationError(
                f"status must be {STATUS_COMPLETE} or {STATUS_EMPTY}, got "
                f"{self.status!r}"
            )
        if not isinstance(self.schema, DatasetSchema):
            raise DatasetArtifactValidationError(
                f"schema must be a DatasetSchema, got "
                f"{type(self.schema).__name__}"
            )
        if not isinstance(self.manifest, DatasetManifest):
            raise DatasetArtifactValidationError(
                f"manifest must be a DatasetManifest, got "
                f"{type(self.manifest).__name__}"
            )
        if not isinstance(self.split_spec, ChronologicalSplitSpec):
            raise DatasetArtifactValidationError(
                f"split_spec must be a ChronologicalSplitSpec, got "
                f"{type(self.split_spec).__name__}"
            )
        if not isinstance(self.split_result, ChronologicalSplitResult):
            raise DatasetArtifactValidationError(
                f"split_result must be a ChronologicalSplitResult, got "
                f"{type(self.split_result).__name__}"
            )
        if not isinstance(self.build_report, DatasetBuildReportRecord):
            raise DatasetArtifactValidationError(
                f"build_report must be a DatasetBuildReportRecord, got "
                f"{type(self.build_report).__name__}"
            )
        if not isinstance(self.manifest_payload, bytes):
            raise DatasetArtifactValidationError(
                f"manifest_payload must be bytes, got "
                f"{type(self.manifest_payload).__name__}"
            )
        if not isinstance(self.build_report_payload, bytes):
            raise DatasetArtifactValidationError(
                f"build_report_payload must be bytes, got "
                f"{type(self.build_report_payload).__name__}"
            )
        # Timestamps are normalized to UTC microseconds at construction so
        # an equivalent non-canonical representation of the same instant
        # (any UTC offset) never bypasses the model contract, while a
        # different instant or a naive value fails.
        if not isinstance(self.built_at, datetime) or self.built_at.tzinfo is None:
            raise DatasetArtifactValidationError(
                "built_at must be a timezone-aware datetime"
            )
        object.__setattr__(
            self, "built_at", normalize_utc_datetime(self.built_at, "built_at")
        )
        if self.dataset_as_of is not None:
            if (
                not isinstance(self.dataset_as_of, datetime)
                or self.dataset_as_of.tzinfo is None
            ):
                raise DatasetArtifactValidationError(
                    "dataset_as_of must be a timezone-aware datetime or null"
                )
            object.__setattr__(
                self,
                "dataset_as_of",
                normalize_utc_datetime(self.dataset_as_of, "dataset_as_of"),
            )
        build_path = self.build_path
        if not isinstance(build_path, Path) or not build_path.is_absolute():
            raise DatasetArtifactValidationError(
                f"build_path must be an absolute Path, got {build_path!r}"
            )
        for part in build_path.parts:
            if part in (".", ".."):
                raise DatasetArtifactValidationError(
                    f"build_path must not contain '.' or '..' path "
                    f"components: {build_path!r}"
                )
        if build_path.name != self.dataset_id:
            raise DatasetArtifactValidationError(
                f"build_path.name must be exactly {self.dataset_id!r}, got "
                f"{build_path.name!r}"
            )

        # Status / row-count consistency.
        if self.status == STATUS_EMPTY and len(self.rows) != 0:
            raise DatasetArtifactValidationError(
                "status EMPTY requires zero logical rows"
            )
        if self.status == STATUS_COMPLETE and len(self.rows) == 0:
            raise DatasetArtifactValidationError(
                "status COMPLETE requires at least one logical row; zero rows "
                "must be EMPTY"
            )

        # Independent row self-validation (strict tuples, field count,
        # logical content identity, sample uniqueness, scope binding,
        # dataset_as_of contract, and the fixed physical row order) via
        # the shared helper the public reader also uses.
        _verify_verified_rows(self.rows, schema=self.schema, manifest=self.manifest)

        # Manifest bindings with the explicit model fields.
        if self.manifest.dataset_id != self.dataset_id:
            raise DatasetArtifactValidationError(
                "manifest.dataset_id does not match the verified dataset_id"
            )
        if self.manifest.dataset_kind != self.dataset_kind:
            raise DatasetArtifactValidationError(
                "manifest.dataset_kind does not match the verified "
                "dataset_kind"
            )
        if self.manifest.status != self.status:
            raise DatasetArtifactValidationError(
                "manifest.status does not match the verified status"
            )
        if self.manifest.built_at != self.built_at:
            raise DatasetArtifactValidationError(
                "manifest.built_at does not match the verified built_at"
            )
        if self.manifest.dataset_as_of != self.dataset_as_of:
            raise DatasetArtifactValidationError(
                "manifest.dataset_as_of does not match the verified "
                "dataset_as_of"
            )
        if self.manifest.schema != self.schema:
            raise DatasetArtifactValidationError(
                "manifest.schema does not match the verified schema"
            )
        if self.manifest.logical_row_count != len(self.rows):
            raise DatasetArtifactValidationError(
                "manifest.logical_row_count does not match the verified rows"
            )

        # Canonical manifest payload.
        if serialize_dataset_manifest(self.manifest) != self.manifest_payload:
            raise DatasetArtifactValidationError(
                "manifest_payload must be the exact canonical serialization "
                "of the validated manifest"
            )

        # Specs: typed tuples, pins in manifest order, unique names.
        if not isinstance(self.feature_specs, tuple) or not all(
            isinstance(spec, FeatureSpec) for spec in self.feature_specs
        ):
            raise DatasetArtifactValidationError(
                "feature_specs must be a tuple of FeatureSpec instances"
            )
        if not isinstance(self.label_specs, tuple) or not all(
            isinstance(spec, LabelSpec) for spec in self.label_specs
        ):
            raise DatasetArtifactValidationError(
                "label_specs must be a tuple of LabelSpec instances"
            )
        if tuple(
            feature_label_spec_pin(spec) for spec in self.feature_specs
        ) != self.manifest.feature_specs:
            raise DatasetArtifactValidationError(
                "Feature spec pins do not match the manifest Feature pins in "
                "the manifest order"
            )
        if tuple(
            feature_label_spec_pin(spec) for spec in self.label_specs
        ) != self.manifest.label_specs:
            raise DatasetArtifactValidationError(
                "Label spec pins do not match the manifest Label pins in the "
                "manifest order"
            )
        feature_names = [spec.name for spec in self.feature_specs]
        label_names = [spec.name for spec in self.label_specs]
        if len(set(feature_names)) != len(feature_names):
            raise DatasetArtifactValidationError(
                "duplicate Feature spec name in the verified build"
            )
        if len(set(label_names)) != len(label_names):
            raise DatasetArtifactValidationError(
                "duplicate Label spec name in the verified build"
            )
        if (
            self.manifest.split_spec is None
            or chronological_split_spec_pin(self.split_spec)
            != self.manifest.split_spec
        ):
            raise DatasetArtifactValidationError(
                "split spec pin does not match the manifest split spec pin"
            )

        # Authoritative schema re-derivation from the typed specs.
        rederived_schema = dataset_orchestration_schema(
            self.feature_specs,
            self.label_specs,
            include_dataset_as_of=self.dataset_as_of is not None,
        )
        if rederived_schema != self.schema:
            raise DatasetArtifactValidationError(
                "the schema re-derived from the typed specs does not match "
                "the verified schema"
            )
        if dataset_schema_id(self.schema) != self.manifest.dataset_schema_id:
            raise DatasetArtifactValidationError(
                "dataset_schema_id does not match the verified schema"
            )

        # Split result re-derived from the actual rows (never from stored
        # assignments) and per-row assignment column equality.
        samples = _split_samples_from_rows(self.rows, self.schema)
        rederived_split_result = assign_chronological_splits(
            samples, self.split_spec
        )
        if rederived_split_result != self.split_result:
            raise DatasetArtifactValidationError(
                "split_result must exactly equal the split result re-derived "
                "from the Dataset rows under the parsed split spec"
            )
        _verify_row_assignment_columns(
            self.rows, self.schema, self.split_result
        )

        # Build report bindings.
        report = self.build_report
        if report.dataset_id != self.manifest.dataset_id:
            raise DatasetArtifactValidationError(
                "build report dataset_id does not match the manifest"
            )
        if report.dataset_kind != self.manifest.dataset_kind:
            raise DatasetArtifactValidationError(
                "build report dataset_kind does not match the manifest"
            )
        if report.status != self.manifest.status:
            raise DatasetArtifactValidationError(
                "build report status does not match the manifest"
            )
        if report.built_at != self.manifest.built_at:
            raise DatasetArtifactValidationError(
                "build report built_at does not match the manifest"
            )
        if report.dataset_as_of != self.manifest.dataset_as_of:
            raise DatasetArtifactValidationError(
                "build report dataset_as_of does not match the manifest"
            )
        if report.dataset_schema_id != self.manifest.dataset_schema_id:
            raise DatasetArtifactValidationError(
                "build report dataset_schema_id does not match the manifest"
            )
        if (
            report.logical_dataset_content_id
            != self.manifest.logical_dataset_content_id
        ):
            raise DatasetArtifactValidationError(
                "build report logical_dataset_content_id does not match the "
                "manifest"
            )
        if report.logical_row_count != self.manifest.logical_row_count:
            raise DatasetArtifactValidationError(
                "build report logical_row_count does not match the manifest"
            )
        if (
            report.manifest_schema_version
            != self.manifest.manifest_schema_version
        ):
            raise DatasetArtifactValidationError(
                "build report manifest_schema_version does not match the "
                "manifest"
            )
        if report.serialization_format != self.manifest.serialization_format:
            raise DatasetArtifactValidationError(
                "build report serialization_format does not match the "
                "manifest"
            )
        if (
            report.serialization_format_version
            != self.manifest.serialization_format_version
        ):
            raise DatasetArtifactValidationError(
                "build report serialization_format_version does not match "
                "the manifest"
            )
        if report.feature_spec_count != len(self.manifest.feature_specs):
            raise DatasetArtifactValidationError(
                "build report feature_spec_count does not match the manifest"
            )
        if report.label_spec_count != len(self.manifest.label_specs):
            raise DatasetArtifactValidationError(
                "build report label_spec_count does not match the manifest"
            )
        if report.canonical_build_pin_count != len(self.manifest.canonical_builds):
            raise DatasetArtifactValidationError(
                "build report canonical_build_pin_count does not match the "
                "manifest"
            )
        if (
            report.canonical_row_version_count
            != len(self.manifest.canonical_row_version_ids)
        ):
            raise DatasetArtifactValidationError(
                "build report canonical_row_version_count does not match the "
                "manifest"
            )
        if (
            report.completion_complete_key_count
            != self.manifest.completion.complete_count
            or report.completion_incomplete_key_count
            != self.manifest.completion.incomplete_count
            or report.completion_missing_key_count
            != self.manifest.completion.missing_count
        ):
            raise DatasetArtifactValidationError(
                "build report completion key counts do not match the "
                "manifest completion summary"
            )
        if (
            report.split_spec_content_id
            != chronological_split_spec_pin(self.split_spec).content_sha256
        ):
            raise DatasetArtifactValidationError(
                "build report split_spec_content_id does not match the "
                "parsed split spec"
            )
        if report.split_result_id != self.split_result.split_result_id:
            raise DatasetArtifactValidationError(
                "build report split_result_id does not match the re-derived "
                "split result"
            )
        if report.split_sample_count != self.split_result.diagnostics.sample_count:
            raise DatasetArtifactValidationError(
                "build report split_sample_count does not match the "
                "re-derived split result"
            )
        if (
            report.assigned_sample_count
            != self.split_result.diagnostics.assigned_count
        ):
            raise DatasetArtifactValidationError(
                "build report assigned_sample_count does not match the "
                "re-derived split result"
            )
        if (
            report.purged_sample_count
            != self.split_result.diagnostics.purged_count
        ):
            raise DatasetArtifactValidationError(
                "build report purged_sample_count does not match the "
                "re-derived split result"
            )
        if (
            report.excluded_sample_count
            != self.split_result.diagnostics.excluded_count
        ):
            raise DatasetArtifactValidationError(
                "build report excluded_sample_count does not match the "
                "re-derived split result"
            )

        # Canonical build-report payload regenerated from the typed record.
        if _canonical_json_bytes(_report_payload_from_record(report)) != (
            self.build_report_payload
        ):
            raise DatasetArtifactValidationError(
                "build_report_payload must be the exact canonical "
                "serialization of the typed build report record"
            )

        # Fixed orchestration diagnostics matrix over the recorded counts
        # (scope from the manifest).
        DatasetOrchestrationDiagnostics(
            scope=self.manifest.scope,
            request_count=report.request_count,
            pit_sample_count=report.pit_sample_count,
            feature_complete_sample_count=report.feature_complete_sample_count,
            feature_excluded_sample_count=report.feature_excluded_sample_count,
            label_complete_sample_count=report.label_complete_sample_count,
            label_incomplete_sample_count=report.label_incomplete_sample_count,
            split_sample_count=report.split_sample_count,
            assigned_sample_count=report.assigned_sample_count,
            purged_sample_count=report.purged_sample_count,
            excluded_sample_count=report.excluded_sample_count,
            logical_row_count=report.logical_row_count,
            completion_complete_key_count=report.completion_complete_key_count,
            completion_incomplete_key_count=report.completion_incomplete_key_count,
            completion_missing_key_count=report.completion_missing_key_count,
        )
