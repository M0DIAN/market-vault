"""Verified Dataset artifact reader (v0.5.0 PR-7).

This module implements the one public, read-only, fail-closed Dataset
reader: :func:`load_verified_dataset` accepts one explicit Dataset final
directory (``<output_root>/<dataset_id>``) and independently rebuilds and
verifies the complete Dataset facts from the directory's own
``dataset.parquet``, ``manifest.json``, ``build_report.json``,
``feature_specs/``, ``label_specs/``, ``split_spec.yaml``, and
``_SUCCESS``.

The reader never accepts a ``DatasetOrchestrationResult``, never re-executes
PIT assembly, Feature execution, Label execution, or the materializer,
never scans for a ``latest`` directory, never scans ``output_root``, and
never writes, repairs, or deletes any file. Canonical pins, row-version
IDs, and gap references are verified through the manifest identity
contract (typed manifest validation plus the recomputed ``dataset_id``);
the upstream Canonical build directories are never reloaded or audited.
Build-report execution counts that cannot be re-derived from the final
directory remain non-identity recorded facts, validated by shape, exact
canonical bytes, the fixed diagnostics matrix, and every artifact-
observable cross-check; nothing is pretended to be independently
recomputable that is not.

Every documented failure surfaces as
:class:`DatasetArtifactValidationError` with the ``__cause__`` preserved;
an already-wrapped error is never double-wrapped, no partial
:class:`VerifiedDatasetBuild` is ever returned, and broad
``except Exception`` is never used (real programming errors are not
disguised as artifact corruption).
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pyarrow as pa

from .artifact_serialization import (
    PARQUET_METADATA_KEY_CONTENT_ID,
    PARQUET_METADATA_KEY_DATASET_ID,
    PARQUET_METADATA_KEY_FORMAT_VERSION,
    PARQUET_METADATA_KEY_MATERIALIZER,
    PARQUET_METADATA_KEY_ROW_ORDER,
    PARQUET_METADATA_KEY_SCHEMA_ID,
    _canonical_json_bytes,
    _dataset_schema_to_arrow,
    _table_to_logical_rows,
    feature_spec_artifact,
    file_byte_size,
    file_sha256,
    label_spec_artifact,
    parse_split_spec_artifact,
    read_dataset_parquet,
    split_spec_artifact,
)
from .content import dataset_schema_id
from .encoding import DatasetError, normalize_utc_datetime
from .manifest import serialize_dataset_manifest, validate_dataset_manifest
from .materialization import (
    _is_junction_or_reparse,
    _verify_success,
)
from .materialization_models import (
    DATASET_BUILD_REPORT_FILENAME,
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
    DATASET_SPLIT_SPEC_FILENAME,
    DATASET_SUCCESS_FILENAME,
)
from .models import (
    DATASET_MANIFEST_SCHEMA_VERSION,
    SERIALIZATION_FORMAT_PARQUET,
    SERIALIZATION_FORMAT_VERSION_PARQUET,
    SPEC_KIND_FEATURE,
    SPEC_KIND_LABEL,
    SPEC_KIND_SPLIT,
    STATUS_COMPLETE,
    STATUS_EMPTY,
    DatasetOutputFile,
    _validate_output_relative_path,
)
from .orchestration_models import (
    DATASET_KIND_SUPERVISED,
    DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY,
    DatasetOrchestrationDiagnostics,
    dataset_orchestration_schema,
)
from .reader_models import (
    DATASET_READER_CONTRACT_VERSION,
    DatasetArtifactValidationError,
    DatasetBuildReportRecord,
    DatasetOutputLayoutRecord,
    VerifiedDatasetBuild,
    _report_payload_from_record,
    _split_samples_from_rows,
    _verify_verified_rows,
)
from .spec_models import FeatureSpec, LabelSpec
from .specs import feature_label_spec_pin, parse_feature_spec, parse_label_spec
from .split_models import (
    ChronologicalSplitResult,
    ChronologicalSplitSpec,
    chronological_split_spec_pin,
)
from .splits import assign_chronological_splits

__all__ = ["load_verified_dataset"]

_UTF8_BOM = "﻿"

#: The exact field set of ``build_report.json``.
_REPORT_FIELDS = frozenset(
    {
        "report_schema_version",
        "materializer_version",
        "dataset_id",
        "dataset_kind",
        "status",
        "built_at",
        "dataset_as_of",
        "dataset_schema_id",
        "logical_dataset_content_id",
        "logical_row_count",
        "orchestration_contract_version",
        "row_order",
        "manifest_schema_version",
        "serialization_format",
        "serialization_format_version",
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
        "split_spec_content_id",
        "split_result_id",
        "output_layout",
    }
)

_LAYOUT_FIELDS = frozenset(
    {
        "dataset_parquet_filename",
        "manifest_filename",
        "build_report_filename",
        "split_spec_filename",
        "success_filename",
        "feature_specs_dirname",
        "label_specs_dirname",
    }
)

_DOCUMENTED_ERRORS = (
    DatasetError,
    OSError,
    UnicodeError,
    TypeError,
    ValueError,
    KeyError,
    pa.ArrowException,
)


def load_verified_dataset(build_dir) -> VerifiedDatasetBuild:
    """Read and strictly verify one immutable Dataset build directory.

    ``build_dir`` must be a path-like pointing at the exact final Dataset
    directory ``<output_root>/<dataset_id>`` (absolute or relative). The
    directory name must be the lowercase 64-hex ``dataset_id`` carried by
    the manifest; ``.staging-<id>`` and any other name are rejected. The
    path must be lexically absolute (``resolve()`` is never used to mask a
    link), must not contain ``.`` / ``..`` components, and no path
    component may be a symlink or Windows junction (Python 3.11
    reparse-point detection included; a path whose link status cannot be
    verified fails closed).

    The complete Dataset facts are rebuilt from the directory's own
    artifacts: canonical manifest validation and byte identity, the
    directory-name binding, the exact artifact whitelist derived from the
    manifest pins, ``_SUCCESS``, the full ``DatasetOutputFile`` records
    with sizes and SHA-256s, Feature / Label / Split artifact parse / pin
    / canonical-bytes verification, the authoritative schema re-derivation,
    Parquet schema / metadata / rows / logical content identity, physical
    row order, sample-key uniqueness, scope and ``dataset_as_of`` binding,
    the split result re-derived from the actual rows, the build report's
    canonical bytes and observable-fact bindings, and the fixed
    diagnostics matrix. A second pass re-verifies the path contract, the
    whitelist, ``_SUCCESS``, the manifest (re-read and re-validated
    against the initially parsed manifest and payload —
    ``manifest.json`` is not in ``output_files``, so it must be verified
    independently), and every output-file size and hash before the
    :class:`VerifiedDatasetBuild` is constructed, so a concurrent
    modification is detected and no mixed-instant partial result is ever
    returned. Entries are enumerated by the reader's own safe
    non-recursive enumerator, which rejects symlinks and junctions before
    any descent.

    Any inconsistency raises :class:`DatasetArtifactValidationError`.
    Nothing is written, repaired, rewritten, or deleted; no current time,
    no random values, no environment variables, and no network are used.
    """
    try:
        return _load_verified_dataset(build_dir)
    except DatasetArtifactValidationError:
        raise
    except _DOCUMENTED_ERRORS as exc:
        _convert_documented_error(exc, "load_verified_dataset failed")


def _convert_documented_error(exc, context: str) -> None:
    """Convert every documented failure, including PyArrow exceptions, to
    :class:`DatasetArtifactValidationError` with the ``__cause__``
    preserved. An already-raised
    :class:`DatasetArtifactValidationError` passes through unchanged
    (never double-wrapped); broad ``except Exception`` is never used, so
    real programming errors are not hidden."""
    if isinstance(exc, pa.ArrowException):
        raise DatasetArtifactValidationError(f"{context}: {exc}") from exc
    if isinstance(
        exc,
        (DatasetError, OSError, UnicodeError, TypeError, ValueError, KeyError),
    ):
        raise DatasetArtifactValidationError(f"{context}: {exc}") from exc
    raise exc


def _fail(reason: str) -> None:
    raise DatasetArtifactValidationError(reason)


# ---------------------------------------------------------------------------
# Fixed read sequence.
# ---------------------------------------------------------------------------


def _load_verified_dataset(build_dir) -> VerifiedDatasetBuild:
    # 1-2. Input contract, lexical absolute path, full parent-chain link
    # safety, and the 64-hex directory-name binding.
    build = _coerce_build_dir(build_dir)
    _verify_build_dir_safety(build)

    # 3-7. Manifest: regular non-link file, strict validation, canonical
    # bytes, dataset_id binding, and the current-contract facts.
    manifest_path = build / DATASET_MANIFEST_FILENAME
    _reject_symlink(manifest_path, "dataset manifest")
    if not manifest_path.is_file():
        _fail(f"dataset manifest must be a regular file: {manifest_path}")
    manifest_payload = _read_artifact_bytes(manifest_path, "manifest.json")
    manifest = validate_dataset_manifest(manifest_payload)
    if manifest_payload != serialize_dataset_manifest(manifest):
        _fail(
            "manifest.json must be the exact canonical serialization of the "
            "validated manifest (any formatting, key-order, whitespace, "
            "BOM, or timestamp-representation difference is rejected)"
        )
    if manifest.dataset_id != build.name:
        _fail(
            f"manifest dataset_id {manifest.dataset_id!r} does not equal the "
            f"build directory name {build.name!r}"
        )
    if manifest.dataset_kind != DATASET_KIND_SUPERVISED:
        _fail(
            f"dataset_kind must be {DATASET_KIND_SUPERVISED}, got "
            f"{manifest.dataset_kind!r}"
        )
    if manifest.serialization_format != SERIALIZATION_FORMAT_PARQUET:
        _fail(
            f"serialization_format must be {SERIALIZATION_FORMAT_PARQUET}, "
            f"got {manifest.serialization_format!r}"
        )
    if (
        manifest.serialization_format_version
        != SERIALIZATION_FORMAT_VERSION_PARQUET
    ):
        _fail(
            f"serialization_format_version must be "
            f"{SERIALIZATION_FORMAT_VERSION_PARQUET}, got "
            f"{manifest.serialization_format_version!r}"
        )
    if manifest.status not in (STATUS_COMPLETE, STATUS_EMPTY):
        _fail(f"manifest status must be COMPLETE or EMPTY, got {manifest.status!r}")
    if manifest.status == STATUS_COMPLETE and manifest.logical_row_count == 0:
        _fail("manifest status COMPLETE requires a positive logical row count")
    if manifest.status == STATUS_EMPTY and manifest.logical_row_count != 0:
        _fail("manifest status EMPTY requires logical_row_count == 0")
    if manifest.split_spec is None or manifest.split_spec.kind != SPEC_KIND_SPLIT:
        _fail("manifest split_spec must be present and kind=SPLIT")
    for pin in manifest.feature_specs:
        if pin.kind != SPEC_KIND_FEATURE:
            _fail("manifest feature pins must be kind=FEATURE")
    for pin in manifest.label_specs:
        if pin.kind != SPEC_KIND_LABEL:
            _fail("manifest label pins must be kind=LABEL")

    # 8-10. Exact whitelist from the manifest pins; traverse and verify
    # every entry; _SUCCESS contract.
    expected_entries = _expected_build_entries(manifest)
    _verify_entries(build, expected_entries)
    _verify_success(build / DATASET_SUCCESS_FILENAME)

    # 11-13. Authoritative DatasetOutputFile records rebuilt from the
    # actual build directory; full six-field equality with the manifest;
    # every file exists as a regular file with matching size and SHA-256.
    records = _rebuild_output_records(build, manifest)
    _verify_output_records(build, manifest, records)

    # 14-17. Feature / Label / Split spec artifacts in manifest pin order.
    feature_specs = _read_feature_specs(build, manifest)
    label_specs = _read_label_specs(build, manifest)
    split_spec = _read_split_spec(build, manifest)

    # 18. Authoritative DatasetSchema re-derivation from the typed specs.
    rederived_schema = dataset_orchestration_schema(
        feature_specs,
        label_specs,
        include_dataset_as_of=manifest.dataset_as_of is not None,
    )
    if rederived_schema != manifest.schema:
        _fail(
            "the schema re-derived from the typed specs does not match the "
            "manifest schema"
        )
    if dataset_schema_id(rederived_schema) != manifest.dataset_schema_id:
        _fail(
            "the schema ID of the re-derived schema does not match the "
            "manifest dataset_schema_id"
        )

    # 19. Build report: strict typed record and exact canonical bytes.
    report_bytes = _read_artifact_bytes(
        build / DATASET_BUILD_REPORT_FILENAME, "build_report.json"
    )
    report = _parse_build_report_record(report_bytes)
    if _canonical_json_bytes(_report_payload_from_record(report)) != report_bytes:
        _fail(
            "build_report.json must be the exact canonical serialization of "
            "the typed build report (any formatting, key-order, whitespace, "
            "BOM, or timestamp-representation difference is rejected)"
        )

    # 20-24. Parquet: Arrow schema, metadata, row count, logical rows,
    # content identity, physical order, uniqueness, scope and
    # dataset_as_of binding.
    dataset_path = build / DATASET_PARQUET_FILENAME
    table = read_dataset_parquet(dataset_path)
    _verify_parquet(table, manifest)
    rows = _table_to_logical_rows(table, manifest.schema)
    _verify_rows(rows, manifest)

    # 25. Split result re-derived from the actual rows; every stored
    # assignment column compared.
    split_result = assign_chronological_splits(
        _split_samples_from_rows(rows, manifest.schema), split_spec
    )
    _verify_split_rows(rows, manifest.schema, split_result)

    # 26. Report observable facts: split spec content ID, split result ID,
    # split sample / assigned / purged / excluded counts, and the fixed
    # orchestration diagnostics matrix over the recorded counts.
    _verify_report_split_facts(manifest, split_spec, split_result, report)
    _verify_diagnostics_matrix(manifest, report)

    # 27. Second pass: path contract, exact whitelist, _SUCCESS, the
    # manifest re-read and re-validated against the initially parsed
    # manifest and payload, and every output-file size / hash re-verified
    # (a concurrent modification fails closed; no mixed-instant partial
    # result is ever returned).
    _second_pass_verify(build, manifest, manifest_payload)

    # 28-30. Construct the VerifiedDatasetBuild; construction re-verifies
    # every invariant (fail closed) and only then is the result returned.
    return VerifiedDatasetBuild(
        reader_contract_version=DATASET_READER_CONTRACT_VERSION,
        dataset_id=manifest.dataset_id,
        dataset_kind=manifest.dataset_kind,
        status=manifest.status,
        built_at=manifest.built_at,
        dataset_as_of=manifest.dataset_as_of,
        schema=manifest.schema,
        rows=rows,
        manifest=manifest,
        feature_specs=feature_specs,
        label_specs=label_specs,
        split_spec=split_spec,
        split_result=split_result,
        build_report=report,
        manifest_payload=manifest_payload,
        build_report_payload=report_bytes,
        build_path=build,
    )


# ---------------------------------------------------------------------------
# Path and link safety.
# ---------------------------------------------------------------------------


def _coerce_build_dir(build_dir) -> Path:
    """Lexically absolute Path of the input; raw ``.`` / ``..`` components
    are rejected before any normalization and ``resolve()`` is never used
    to mask a link.

    The raw caller-supplied string is checked on both separators *before*
    :class:`pathlib.Path` construction, because pathlib itself strips
    ``.`` components during parsing (``str(Path("./abc")) == "abc"``) and
    a lexical ``.`` / ``..`` component must never survive into the
    verified path.
    """
    try:
        raw_text = os.fspath(build_dir)
    except TypeError as exc:
        raise DatasetArtifactValidationError(
            f"build_dir must be a path-like, got {type(build_dir).__name__}"
        ) from exc
    for part in raw_text.replace("\\", "/").split("/"):
        if part in (".", ".."):
            raise DatasetArtifactValidationError(
                f"build_dir must not contain '.' or '..' path components: "
                f"{build_dir!r}"
            )
    try:
        raw = Path(build_dir)
    except TypeError as exc:
        raise DatasetArtifactValidationError(
            f"build_dir must be a path-like, got {type(build_dir).__name__}"
        ) from exc
    if not isinstance(raw, Path):
        raise DatasetArtifactValidationError(
            f"build_dir must be a path-like, got {type(build_dir).__name__}"
        )
    if raw.is_absolute():
        return raw
    try:
        return Path.cwd() / raw
    except OSError as exc:
        raise DatasetArtifactValidationError(
            f"cannot resolve the current working directory for a relative "
            f"build_dir: {exc}"
        ) from exc


def _reject_symlink(path: Path, label: str) -> None:
    if path.is_symlink() or _is_junction_or_reparse(path):
        _fail(f"{label} must not be a symlink or junction: {path}")


def _verify_build_dir_safety(build: Path) -> None:
    """``build`` and every existing parent component must be a real,
    regular directory; the directory name must be the lowercase 64-hex
    ``dataset_id``. A component whose link status cannot be verified fails
    closed (Python 3.11 Windows reparse-point detection included)."""
    for component in (build.parent, *build.parents):
        _reject_symlink(component, "build path component")
        if component.exists() and not component.is_dir():
            _fail(
                f"build path component must be a regular directory: {component}"
            )
    if not build.exists():
        _fail(f"dataset build directory does not exist: {build}")
    if not build.is_dir():
        _fail(f"dataset build path is not a directory: {build}")
    _reject_symlink(build, "dataset build directory")
    if not _matches_dataset_id(build.name):
        _fail(
            f"dataset build directory name must be a 64-character lowercase "
            f"SHA-256 hex string, got {build.name!r}; '.staging-<id>' and any "
            f"other name are not valid build directories"
        )


def _matches_dataset_id(name: str) -> bool:
    return (
        isinstance(name, str)
        and len(name) == 64
        and all(character in "0123456789abcdef" for character in name)
    )


# ---------------------------------------------------------------------------
# Manifest, whitelist, and entries.
# ---------------------------------------------------------------------------


def _expected_build_entries(manifest) -> dict[str, str]:
    """The exact whitelist of one build directory derived from the manifest
    pins, keyed by relative POSIX path (``file`` / ``dir``)."""
    entries = {
        DATASET_PARQUET_FILENAME: "file",
        DATASET_MANIFEST_FILENAME: "file",
        DATASET_BUILD_REPORT_FILENAME: "file",
        DATASET_SPLIT_SPEC_FILENAME: "file",
        DATASET_SUCCESS_FILENAME: "file",
        DATASET_FEATURE_SPECS_DIRNAME: "dir",
        DATASET_LABEL_SPECS_DIRNAME: "dir",
    }
    for pin in manifest.feature_specs:
        entries[
            f"{DATASET_FEATURE_SPECS_DIRNAME}/{_spec_artifact_filename(pin)}"
        ] = "file"
    for pin in manifest.label_specs:
        entries[
            f"{DATASET_LABEL_SPECS_DIRNAME}/{_spec_artifact_filename(pin)}"
        ] = "file"
    expected_file_count = (
        5 + len(manifest.feature_specs) + len(manifest.label_specs)
    )
    if len(entries) != 2 + expected_file_count:
        _fail(
            "spec artifact filename collision detected in the expected build "
            "entry whitelist"
        )
    return entries


def _spec_artifact_filename(pin) -> str:
    return f"{pin.name}--{pin.version}--{pin.content_sha256}.yaml"


def _list_verified_dataset_entries_safely(build: Path) -> dict[str, Path]:
    """Safe non-recursive enumeration of one build directory.

    The formal layout is enumerated in exactly two controlled levels and
    never with a recursive walk:

    - ``os.scandir`` enumerates the build root only;
    - every root entry is rejected as a symlink or Windows junction /
      reparse point *before* any classification or descent, and must be a
      regular file or one of the two spec directories;
    - only ``feature_specs/`` and ``label_specs/`` may exist as
      directories, and each is scanned exactly once (a second single-level
      ``os.scandir``) after it was confirmed to be a regular non-link
      directory;
    - spec directory entries must be regular non-link files; any nested
      directory, symlink, junction, FIFO, or socket fails closed without
      recursion.

    ``os.walk``, ``Path.rglob``, ``glob("**/*")``, and ``followlinks`` are
    never used, so no link target is ever traversed or enumerated. Returns
    the safe relative POSIX path -> Path mapping.
    """
    entries: dict[str, Path] = {}
    with os.scandir(build) as iterator:
        root_items = sorted(iterator, key=lambda item: item.name)
    for item in root_items:
        path = Path(item.path)
        # Reject symlinks and junctions before any descent or target
        # enumeration (Python 3.11 Windows reparse-point detection).
        _reject_symlink(path, f"dataset entry {item.name}")
        if item.is_dir(follow_symlinks=False):
            if item.name not in (
                DATASET_FEATURE_SPECS_DIRNAME,
                DATASET_LABEL_SPECS_DIRNAME,
            ):
                _fail(
                    f"dataset build directory may contain only the "
                    f"{DATASET_FEATURE_SPECS_DIRNAME}/ and "
                    f"{DATASET_LABEL_SPECS_DIRNAME}/ subdirectories, got "
                    f"{item.name!r}"
                )
            entries[item.name] = path
            continue
        if item.is_file(follow_symlinks=False):
            _validate_output_relative_path(item.name, "dataset entry")
            entries[item.name] = path
            continue
        _fail(
            f"dataset entry must be a regular file or directory: {item.name}"
        )
    for dirname in (DATASET_FEATURE_SPECS_DIRNAME, DATASET_LABEL_SPECS_DIRNAME):
        if dirname not in entries:
            continue  # a missing directory is reported by the whitelist
        with os.scandir(entries[dirname]) as iterator:
            spec_items = sorted(iterator, key=lambda item: item.name)
        for item in spec_items:
            rel = f"{dirname}/{item.name}"
            spec_path = Path(item.path)
            _reject_symlink(spec_path, f"dataset entry {rel}")
            if item.is_dir(follow_symlinks=False):
                _fail(
                    f"spec directory {dirname} must contain only regular "
                    f"files, got nested directory {item.name!r}"
                )
            if not item.is_file(follow_symlinks=False):
                _fail(
                    f"spec directory {dirname} entry must be a regular "
                    f"file: {item.name}"
                )
            _validate_output_relative_path(rel, "dataset entry")
            entries[rel] = spec_path
    return entries


def _verify_entries(build: Path, expected_entries: dict[str, str]) -> None:
    """Every entry under ``build`` must be expected and regular;
    unexpected files or directories, symlinks, junctions, and non-regular
    entries fail closed. Nothing is ever deleted or ignored."""
    actual_entries = _list_verified_dataset_entries_safely(build)
    if set(actual_entries) != set(expected_entries):
        extra = sorted(set(actual_entries) - set(expected_entries))
        missing = sorted(set(expected_entries) - set(actual_entries))
        _fail(
            f"dataset build directory has unexpected or missing entries: "
            f"extra={extra} missing={missing}"
        )
    for rel, path in actual_entries.items():
        _reject_symlink(path, f"dataset entry {rel}")
        kind = expected_entries[rel]
        if kind == "file" and not path.is_file():
            _fail(f"dataset entry {rel} must be a regular file: {path}")
        if kind == "dir" and not path.is_dir():
            _fail(f"dataset entry {rel} must be a regular directory: {path}")


# ---------------------------------------------------------------------------
# Output file records.
# ---------------------------------------------------------------------------


def _rebuild_output_records(build: Path, manifest) -> tuple[DatasetOutputFile, ...]:
    """Exact DatasetOutputFile records rebuilt from the actual build
    directory and the manifest pins. ``manifest.json`` is excluded (a
    self-hash cycle is impossible) and ``_SUCCESS`` is excluded; the
    records are normalized by the manifest sort rule (relative path)."""

    def record(rel: str, role: str, content_role: str, row_count: int) -> None:
        path = build / rel
        records.append(
            DatasetOutputFile(
                relative_path=rel,
                file_role=role,
                row_count=row_count,
                byte_size=file_byte_size(path),
                sha256=file_sha256(path),
                content_role=content_role,
            )
        )

    records: list[DatasetOutputFile] = []
    record(
        DATASET_PARQUET_FILENAME,
        DATASET_OUTPUT_ROLE_DATASET,
        DATASET_CONTENT_ROLE_LOGICAL_ROWS,
        manifest.logical_row_count,
    )
    record(
        DATASET_BUILD_REPORT_FILENAME,
        DATASET_OUTPUT_ROLE_BUILD_REPORT,
        DATASET_CONTENT_ROLE_BUILD_REPORT,
        1,
    )
    for pin in manifest.feature_specs:
        record(
            f"{DATASET_FEATURE_SPECS_DIRNAME}/{_spec_artifact_filename(pin)}",
            DATASET_OUTPUT_ROLE_FEATURE_SPEC,
            DATASET_CONTENT_ROLE_FEATURE_SPEC,
            1,
        )
    for pin in manifest.label_specs:
        record(
            f"{DATASET_LABEL_SPECS_DIRNAME}/{_spec_artifact_filename(pin)}",
            DATASET_OUTPUT_ROLE_LABEL_SPEC,
            DATASET_CONTENT_ROLE_LABEL_SPEC,
            1,
        )
    record(
        DATASET_SPLIT_SPEC_FILENAME,
        DATASET_OUTPUT_ROLE_SPLIT_SPEC,
        DATASET_CONTENT_ROLE_SPLIT_SPEC,
        1,
    )
    return tuple(sorted(records, key=lambda record: record.relative_path))


def _verify_output_records(build: Path, manifest, records) -> None:
    """Full six-field equality of ``manifest.output_files`` with the
    authoritative records, then existence, regularity, size, and SHA-256
    of every recorded file."""
    if manifest.output_files != records:
        _fail(
            "manifest.output_files must exactly equal the authoritative "
            "output file records rebuilt from the build directory "
            "(relative_path, file_role, content_role, row_count, byte_size, "
            "sha256)"
        )
    for record in manifest.output_files:
        path = build / record.relative_path
        _reject_symlink(path, f"output file {record.relative_path}")
        if not path.is_file():
            _fail(
                f"manifest output file does not exist as a regular file: "
                f"{record.relative_path}"
            )
        if file_byte_size(path) != record.byte_size:
            _fail(
                f"output file byte size mismatch: {record.relative_path}"
            )
        if file_sha256(path) != record.sha256:
            _fail(f"output file SHA-256 mismatch: {record.relative_path}")


# ---------------------------------------------------------------------------
# Spec artifacts.
# ---------------------------------------------------------------------------


def _read_feature_specs(build: Path, manifest) -> tuple[FeatureSpec, ...]:
    specs: list[FeatureSpec] = []
    names: set[str] = set()
    for pin in manifest.feature_specs:
        rel = f"{DATASET_FEATURE_SPECS_DIRNAME}/{_spec_artifact_filename(pin)}"
        payload = _read_artifact_bytes(build / rel, rel)
        parsed = parse_feature_spec(_decode_utf8(payload, rel))
        if feature_label_spec_pin(parsed) != pin:
            _fail(f"Feature spec artifact {rel} pin mismatch")
        if payload != feature_spec_artifact(parsed):
            _fail(
                f"Feature spec artifact {rel} is not the canonical artifact "
                "bytes of the parsed FeatureSpec"
            )
        if parsed.name in names:
            _fail(f"duplicate Feature spec name {parsed.name!r}")
        names.add(parsed.name)
        specs.append(parsed)
    return tuple(specs)


def _read_label_specs(build: Path, manifest) -> tuple[LabelSpec, ...]:
    specs: list[LabelSpec] = []
    names: set[str] = set()
    for pin in manifest.label_specs:
        rel = f"{DATASET_LABEL_SPECS_DIRNAME}/{_spec_artifact_filename(pin)}"
        payload = _read_artifact_bytes(build / rel, rel)
        parsed = parse_label_spec(_decode_utf8(payload, rel))
        if feature_label_spec_pin(parsed) != pin:
            _fail(f"Label spec artifact {rel} pin mismatch")
        if payload != label_spec_artifact(parsed):
            _fail(
                f"Label spec artifact {rel} is not the canonical artifact "
                "bytes of the parsed LabelSpec"
            )
        if parsed.name in names:
            _fail(f"duplicate Label spec name {parsed.name!r}")
        names.add(parsed.name)
        specs.append(parsed)
    return tuple(specs)


def _read_split_spec(build: Path, manifest) -> ChronologicalSplitSpec:
    rel = DATASET_SPLIT_SPEC_FILENAME
    payload = _read_artifact_bytes(build / rel, rel)
    parsed = parse_split_spec_artifact(_decode_utf8(payload, rel))
    if parsed.kind != SPEC_KIND_SPLIT:
        _fail(
            f"split spec artifact kind must be {SPEC_KIND_SPLIT}, got "
            f"{parsed.kind!r}"
        )
    if chronological_split_spec_pin(parsed) != manifest.split_spec:
        _fail("split_spec.yaml pin does not match the manifest split spec pin")
    if payload != split_spec_artifact(parsed):
        _fail(
            "split_spec.yaml is not the canonical artifact bytes of the "
            "parsed ChronologicalSplitSpec"
        )
    return parsed


# ---------------------------------------------------------------------------
# Parquet and rows.
# ---------------------------------------------------------------------------


def _verify_parquet(table, manifest) -> None:
    """Arrow schema (field order, types, nullability) and the exact
    metadata set must equal the manifest facts.

    ``pa.Schema`` equality ignores metadata, so the field contract and
    the exact metadata set are verified separately: the schema fields are
    compared without metadata and the decoded UTF-8 metadata mapping must
    equal the exact expected key set and values.
    """
    expected_arrow = _dataset_schema_to_arrow(
        manifest.schema,
        dataset_id=manifest.dataset_id,
        dataset_schema_id_value=manifest.dataset_schema_id,
        logical_dataset_content_id_value=manifest.logical_dataset_content_id,
        serialization_format_version=manifest.serialization_format_version,
        row_order=DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY,
    )
    if table.schema.remove_metadata() != expected_arrow.remove_metadata():
        _fail(
            "Dataset Parquet schema does not match the manifest facts "
            "(field order, Arrow types, nullability)"
        )
    actual_metadata = {
        key.decode("utf-8"): value.decode("utf-8")
        for key, value in (table.schema.metadata or {}).items()
    }
    expected_metadata = {
        PARQUET_METADATA_KEY_DATASET_ID: manifest.dataset_id,
        PARQUET_METADATA_KEY_SCHEMA_ID: manifest.dataset_schema_id,
        PARQUET_METADATA_KEY_CONTENT_ID: manifest.logical_dataset_content_id,
        PARQUET_METADATA_KEY_FORMAT_VERSION: manifest.serialization_format_version,
        PARQUET_METADATA_KEY_ROW_ORDER: DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY,
        PARQUET_METADATA_KEY_MATERIALIZER: DATASET_MATERIALIZER_VERSION,
    }
    if actual_metadata != expected_metadata:
        _fail(
            "Dataset Parquet metadata does not match the manifest facts "
            "(exact key set and values; extra, missing, or changed keys "
            "are rejected)"
        )
    if table.num_rows != manifest.logical_row_count:
        _fail(
            f"Dataset Parquet row count {table.num_rows} does not match the "
            f"manifest logical_row_count {manifest.logical_row_count}"
        )


def _verify_rows(rows, manifest) -> None:
    """Shared row self-validation: strict tuples, field count, logical
    content identity, sample-key uniqueness, scope binding,
    ``dataset_as_of`` binding, and the fixed physical row order. The
    public reader and :class:`VerifiedDatasetBuild` share exactly this
    helper so the two contracts can never drift."""
    _verify_verified_rows(rows, schema=manifest.schema, manifest=manifest)


def _verify_split_rows(rows, schema, split_result: ChronologicalSplitResult) -> None:
    """Every stored split assignment column of every Dataset row must
    equal the re-derived assignment for that ``sample_key``."""
    indexes = {
        field.name: index for index, field in enumerate(schema.fields)
    }
    by_key = {
        assignment.sample_key: assignment for assignment in split_result.assignments
    }
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
                _fail(
                    f"Dataset row for sample {assignment.sample_key} stored "
                    f"{column} {row[indexes[column]]!r} does not match the "
                    f"re-derived split assignment "
                    f"{getattr(assignment, column)!r}"
                )


# ---------------------------------------------------------------------------
# Build report.
# ---------------------------------------------------------------------------


def _require_string(value, label: str) -> str:
    if not isinstance(value, str):
        _fail(f"{label} must be a string, got {type(value).__name__}")
    return value


def _parse_datetime(value, label: str) -> datetime:
    if not isinstance(value, str):
        _fail(f"{label} must be an ISO datetime string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise DatasetArtifactValidationError(
            f"{label} must be an ISO datetime, got {value!r}"
        ) from exc
    if parsed.tzinfo is None:
        _fail(f"{label} must be timezone-aware, got a naive value {value!r}")
    return normalize_utc_datetime(parsed, label)


def _parse_build_report_record(payload: bytes) -> DatasetBuildReportRecord:
    """Strict exact-field parse of one ``build_report.json`` into the
    frozen typed :class:`DatasetBuildReportRecord`. UTF-8 without BOM,
    JSON object, exact field set, and typed values; the record's own
    construction validates every fixed version, count, and ID contract."""
    if payload.startswith(_UTF8_BOM.encode("utf-8")):
        _fail("build_report.json must not carry a UTF-8 BOM")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DatasetArtifactValidationError(
            f"build_report.json is not valid UTF-8: {exc}"
        ) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DatasetArtifactValidationError(
            f"build_report.json is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        _fail("build_report.json must be a JSON object")
    unknown = sorted(set(data) - _REPORT_FIELDS)
    if unknown:
        _fail(f"build_report.json unknown field(s): {', '.join(unknown)}")
    missing = sorted(_REPORT_FIELDS - set(data))
    if missing:
        _fail(f"build_report.json missing field(s): {', '.join(missing)}")
    layout = data["output_layout"]
    if not isinstance(layout, dict):
        _fail("build_report.json output_layout must be a JSON object")
    unknown = sorted(set(layout) - _LAYOUT_FIELDS)
    if unknown:
        _fail(
            f"build_report.json output_layout unknown field(s): "
            f"{', '.join(unknown)}"
        )
    missing = sorted(_LAYOUT_FIELDS - set(layout))
    if missing:
        _fail(
            f"build_report.json output_layout missing field(s): "
            f"{', '.join(missing)}"
        )
    dataset_as_of_value = data["dataset_as_of"]
    dataset_as_of = (
        _parse_datetime(dataset_as_of_value, "dataset_as_of")
        if dataset_as_of_value is not None
        else None
    )
    return DatasetBuildReportRecord(
        report_schema_version=_require_string(
            data["report_schema_version"], "report_schema_version"
        ),
        materializer_version=_require_string(
            data["materializer_version"], "materializer_version"
        ),
        dataset_id=_require_string(data["dataset_id"], "dataset_id"),
        dataset_kind=_require_string(data["dataset_kind"], "dataset_kind"),
        status=_require_string(data["status"], "status"),
        built_at=_parse_datetime(data["built_at"], "built_at"),
        dataset_as_of=dataset_as_of,
        dataset_schema_id=_require_string(
            data["dataset_schema_id"], "dataset_schema_id"
        ),
        logical_dataset_content_id=_require_string(
            data["logical_dataset_content_id"], "logical_dataset_content_id"
        ),
        logical_row_count=data["logical_row_count"],
        orchestration_contract_version=_require_string(
            data["orchestration_contract_version"],
            "orchestration_contract_version",
        ),
        row_order=_require_string(data["row_order"], "row_order"),
        manifest_schema_version=_require_string(
            data["manifest_schema_version"], "manifest_schema_version"
        ),
        serialization_format=_require_string(
            data["serialization_format"], "serialization_format"
        ),
        serialization_format_version=_require_string(
            data["serialization_format_version"],
            "serialization_format_version",
        ),
        feature_spec_count=data["feature_spec_count"],
        label_spec_count=data["label_spec_count"],
        canonical_build_pin_count=data["canonical_build_pin_count"],
        canonical_row_version_count=data["canonical_row_version_count"],
        completion_complete_key_count=data["completion_complete_key_count"],
        completion_incomplete_key_count=data["completion_incomplete_key_count"],
        completion_missing_key_count=data["completion_missing_key_count"],
        request_count=data["request_count"],
        pit_sample_count=data["pit_sample_count"],
        feature_complete_sample_count=data["feature_complete_sample_count"],
        feature_excluded_sample_count=data["feature_excluded_sample_count"],
        label_complete_sample_count=data["label_complete_sample_count"],
        label_incomplete_sample_count=data["label_incomplete_sample_count"],
        split_sample_count=data["split_sample_count"],
        assigned_sample_count=data["assigned_sample_count"],
        purged_sample_count=data["purged_sample_count"],
        excluded_sample_count=data["excluded_sample_count"],
        split_spec_content_id=_require_string(
            data["split_spec_content_id"], "split_spec_content_id"
        ),
        split_result_id=_require_string(
            data["split_result_id"], "split_result_id"
        ),
        output_layout=DatasetOutputLayoutRecord(
            dataset_parquet_filename=_require_string(
                layout["dataset_parquet_filename"],
                "output_layout.dataset_parquet_filename",
            ),
            manifest_filename=_require_string(
                layout["manifest_filename"], "output_layout.manifest_filename"
            ),
            build_report_filename=_require_string(
                layout["build_report_filename"],
                "output_layout.build_report_filename",
            ),
            split_spec_filename=_require_string(
                layout["split_spec_filename"],
                "output_layout.split_spec_filename",
            ),
            success_filename=_require_string(
                layout["success_filename"], "output_layout.success_filename"
            ),
            feature_specs_dirname=_require_string(
                layout["feature_specs_dirname"],
                "output_layout.feature_specs_dirname",
            ),
            label_specs_dirname=_require_string(
                layout["label_specs_dirname"],
                "output_layout.label_specs_dirname",
            ),
        ),
    )


def _verify_report_split_facts(manifest, split_spec, split_result, report) -> None:
    """The report's split facts must bind exactly to the parsed split spec
    and the re-derived split result."""
    if report.split_spec_content_id != chronological_split_spec_pin(
        split_spec
    ).content_sha256:
        _fail(
            "build report split_spec_content_id does not match the parsed "
            "split spec"
        )
    if report.split_result_id != split_result.split_result_id:
        _fail(
            "build report split_result_id does not match the re-derived "
            "split result"
        )
    if report.split_sample_count != split_result.diagnostics.sample_count:
        _fail(
            "build report split_sample_count does not match the re-derived "
            "split result"
        )
    if report.assigned_sample_count != split_result.diagnostics.assigned_count:
        _fail(
            "build report assigned_sample_count does not match the "
            "re-derived split result"
        )
    if report.purged_sample_count != split_result.diagnostics.purged_count:
        _fail(
            "build report purged_sample_count does not match the re-derived "
            "split result"
        )
    if report.excluded_sample_count != split_result.diagnostics.excluded_count:
        _fail(
            "build report excluded_sample_count does not match the "
            "re-derived split result"
        )


def _verify_diagnostics_matrix(manifest, report) -> None:
    """The fixed orchestration diagnostics matrix over the recorded
    counts (scope from the manifest) must construct: pit == feature
    complete + excluded, pit == label complete + incomplete, split ==
    feature complete, split == assigned + purged + excluded, logical rows
    == split, and completion key counts sum to scope keys."""
    DatasetOrchestrationDiagnostics(
        scope=manifest.scope,
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


# ---------------------------------------------------------------------------
# Second-pass verification and read helpers.
# ---------------------------------------------------------------------------


def _second_pass_verify(build: Path, manifest, manifest_payload: bytes) -> None:
    """Final re-verification before the result is constructed: the path
    contract, the exact whitelist, ``_SUCCESS``, the manifest re-read and
    re-validated against the initially parsed manifest and payload, and
    every output-file size / hash must still hold (a concurrent
    modification fails closed; no mixed-instant partial result is ever
    returned).

    ``manifest.json`` is not a member of ``manifest.output_files`` (a
    self-hash cycle is impossible), so its byte facts cannot be
    re-verified through the output-file hashes: the second pass re-reads
    the raw bytes and requires (1) byte equality with the initially read
    payload, (2) re-validation through ``validate_dataset_manifest``
    reproducing the initially parsed manifest, (3) canonical
    re-serialization of the re-validated manifest reproducing the current
    payload, (4) the directory-name / ``dataset_id`` binding, and (5) the
    regular non-link file contract. Comparing only file size, mtime, or
    the in-memory first-read object is never sufficient.
    """
    _verify_build_dir_safety(build)
    _verify_entries(build, _expected_build_entries(manifest))
    _verify_success(build / DATASET_SUCCESS_FILENAME)
    manifest_path = build / DATASET_MANIFEST_FILENAME
    _reject_symlink(manifest_path, "dataset manifest")
    if not manifest_path.is_file():
        _fail(
            f"dataset manifest must be a regular file on final "
            f"verification: {manifest_path}"
        )
    current_payload = _read_artifact_bytes(manifest_path, "manifest.json")
    if current_payload != manifest_payload:
        _fail(
            "manifest.json changed between the first and the final "
            "verification pass (the raw bytes no longer match the "
            "initially verified payload)"
        )
    current_manifest = validate_dataset_manifest(current_payload)
    if current_manifest != manifest:
        _fail(
            "manifest.json changed between the first and the final "
            "verification pass (re-validation no longer reproduces the "
            "initially parsed manifest)"
        )
    if serialize_dataset_manifest(current_manifest) != current_payload:
        _fail(
            "manifest.json must be the exact canonical serialization of "
            "the re-validated manifest on final verification"
        )
    if current_manifest.dataset_id != build.name:
        _fail(
            f"manifest dataset_id {current_manifest.dataset_id!r} does not "
            f"equal the build directory name {build.name!r} on final "
            f"verification"
        )
    for record in manifest.output_files:
        path = build / record.relative_path
        _reject_symlink(path, f"output file {record.relative_path}")
        if not path.is_file():
            _fail(
                f"manifest output file no longer exists as a regular file: "
                f"{record.relative_path}"
            )
        if file_byte_size(path) != record.byte_size:
            _fail(
                f"output file byte size mismatch on final verification: "
                f"{record.relative_path}"
            )
        if file_sha256(path) != record.sha256:
            _fail(
                f"output file SHA-256 mismatch on final verification: "
                f"{record.relative_path}"
            )


def _read_artifact_bytes(path: Path, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise DatasetArtifactValidationError(
            f"failed to read {label} {path}: {exc}"
        ) from exc


def _decode_utf8(payload: bytes, label: str) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DatasetArtifactValidationError(
            f"{label} is not valid UTF-8: {exc}"
        ) from exc
