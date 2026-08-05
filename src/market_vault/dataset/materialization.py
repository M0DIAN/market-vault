"""Deterministic immutable Dataset artifact materialization (v0.5.0 PR-6).

This module materializes one verified :class:`DatasetOrchestrationResult`
(PR-5) into an immutable, traceable, fail-closed Dataset build directory.
It consumes only the trusted PR-5 result and never re-executes Canonical
reads, PIT assembly, Feature execution, Label execution, or the
chronological split / purge, and it never recomputes any identity algorithm.

One commit executes the fixed sequence: output root and fixed staging path
(``output_root / ".staging-<dataset_id>"``), ``dataset.parquet`` (single
file, explicit schema, fixed writer options, fixed metadata), Feature / Label
spec artifacts, ``split_spec.yaml``, ``build_report.json``, byte facts
(:class:`DatasetOutputFile`), the existing
``build_dataset_manifest`` / ``serialize_dataset_manifest`` /
``validate_dataset_manifest`` core, a full private verification of the
staging directory, ``_SUCCESS`` written last (empty, regular, not a
symlink), a re-verification of ``_SUCCESS``, and an atomic same-filesystem
no-overwrite rename of staging onto the final directory
``output_root / <dataset_id>``.

An existing final directory is never trusted by its name alone: it is
strictly verified against the expected result (exact whitelist, symlink /
junction rejection, ``_SUCCESS`` contract, manifest validation and identity
binding, output-file byte facts, Parquet schema / metadata / rows / content
identity, spec artifact pins, build-report binding) and returns
``created_new_build=False`` without rewriting anything. A pre-existing
staging directory is staging residue or a concurrent build and fails closed
(never deleted, never adopted). Ordinary exceptions after this call created
the staging directory clean up only that staging directory; the final
directory never appears partially.

The entry takes an explicit timezone-aware ``built_at`` (never current
time), an explicit ``output_root``, and no callbacks, no filename or
compression overrides, and no ``dataset_id`` override. ``built_at`` and
output byte hashes are recorded facts that never enter ``dataset_id``.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
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
    _dataset_schema_to_arrow,
    build_report_bytes,
    build_report_payload,
    feature_spec_artifact,
    file_byte_size,
    file_sha256,
    label_spec_artifact,
    parse_split_spec_artifact,
    read_dataset_parquet,
    readback_rows_and_content_id,
    split_spec_artifact,
    write_dataset_parquet,
)
from .content import dataset_schema_id, logical_dataset_content_id
from .encoding import DatasetError, normalize_utc_datetime
from .identity import dataset_id
from .manifest import (
    build_dataset_manifest,
    serialize_dataset_manifest,
    validate_dataset_manifest,
)
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
    DATASET_SPLIT_SPEC_FILENAME,
    DATASET_SUCCESS_FILENAME,
    DatasetMaterializationError,
    DatasetMaterializationResult,
    _as_materialization_error,
)
from .models import (
    STATUS_COMPLETE,
    STATUS_EMPTY,
    DatasetOutputFile,
    _validate_output_relative_path,
)
from .orchestration_models import DatasetOrchestrationResult
from .specs import feature_label_spec_pin, parse_feature_spec, parse_label_spec
from .split_models import chronological_split_spec_pin

__all__ = ["materialize_dataset_artifacts"]

_DOCUMENTED_ERRORS = (
    DatasetError,
    OSError,
    UnicodeError,
    TypeError,
    ValueError,
    KeyError,
    pa.ArrowException,
)


def materialize_dataset_artifacts(
    result: DatasetOrchestrationResult,
    *,
    output_root,
    built_at: datetime,
) -> DatasetMaterializationResult:
    """Materialize one verified orchestration result into an immutable
    Dataset build directory.

    ``result`` must be a :class:`DatasetOrchestrationResult`; ``output_root``
    is an explicit path-like (the parent of the final
    ``output_root / <dataset_id>`` directory); ``built_at`` must be an
    explicitly provided timezone-aware datetime (None and naive values fail
    closed; no current time, no clock callback, no writer callback, no
    registry callback, and no output overrides are accepted). The PR-5
    result is fully re-verified before any file is written (its
    ``__post_init__`` is re-triggered via ``dataclasses.replace`` and the
    identity, row-count, status, and identity-input facts are re-checked);
    the orchestrator and the PIT / Feature / Label / Split layers are never
    re-executed.

    The final directory is exactly ``output_root / <dataset_id>`` (no
    ``dataset_id=`` prefix, no timestamp, no random directory name, no
    ``latest`` pointer, no symlink). An existing verified identical build
    returns ``created_new_build=False`` without rewriting anything; a
    conflicting or corrupt existing build, pre-existing staging residue, or
    any verification failure raises :class:`DatasetMaterializationError`
    (fail closed, no partial result, ``__cause__`` preserved).
    """
    try:
        return _materialize(result, output_root=output_root, built_at=built_at)
    except _DOCUMENTED_ERRORS as exc:
        _as_materialization_error(
            exc, "materialize_dataset_artifacts failed"
        )


def _materialize(
    result: DatasetOrchestrationResult,
    *,
    output_root,
    built_at: datetime,
) -> DatasetMaterializationResult:
    # 1. Explicit public input contract (fail closed on every violation).
    if not isinstance(result, DatasetOrchestrationResult):
        raise DatasetMaterializationError(
            f"result must be a DatasetOrchestrationResult, got "
            f"{type(result).__name__}"
        )
    output_root = _coerce_output_root(output_root)
    built_at = normalize_utc_datetime(built_at, "built_at")

    # 2. Re-trigger the complete PR-5 self-validation: never trust the
    # object type or cached fields, never re-execute the orchestrator.
    revalidated = dataclasses.replace(result)
    if revalidated != result:
        raise DatasetMaterializationError(
            "result re-validation produced a different result; the carried "
            "DatasetOrchestrationResult must be self-consistent"
        )
    _verify_revalidated_result(result)

    # 3. Fixed final and staging paths (same filesystem, no random names).
    final = output_root / result.dataset_id
    staging = output_root / f".staging-{result.dataset_id}"

    # 4. Existing final directory: strict verification, idempotent return;
    # no staging is created and nothing is ever rewritten.
    if final.exists() or final.is_symlink():
        return _existing_build_result(final, result)

    # 5. Pre-existing staging is residue or a concurrent build: fail closed,
    # never delete, never adopt, never overwrite.
    if staging.exists() or staging.is_symlink():
        raise DatasetMaterializationError(
            f"staging directory already exists (crash residue or concurrent "
            f"build): {staging}; refusing to build over it"
        )

    # 6. Create the output root and the fixed staging directory.
    try:
        output_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DatasetMaterializationError(
            f"failed to create output root {output_root}: {exc}"
        ) from exc
    try:
        staging.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise DatasetMaterializationError(
            f"staging directory appeared concurrently: {staging}"
        ) from exc
    except OSError as exc:
        raise DatasetMaterializationError(
            f"failed to create staging directory {staging}: {exc}"
        ) from exc

    # 7. Commit; ordinary exceptions clean up only the staging created here.
    try:
        return _commit_new_build(staging, final, result, built_at)
    except _DOCUMENTED_ERRORS:
        _remove_tree(staging)
        raise


def _coerce_output_root(output_root) -> Path:
    try:
        path = Path(output_root)
    except TypeError as exc:
        raise DatasetMaterializationError(
            f"output_root must be a path-like, got {type(output_root).__name__}"
        ) from exc
    if not isinstance(path, Path):
        raise DatasetMaterializationError(
            f"output_root must be a path-like, got {type(output_root).__name__}"
        )
    # Lexical absolute path only (never resolves symlinks, never touches
    # the filesystem); the result model requires absolute artifact paths.
    return path.absolute()


def _verify_revalidated_result(result: DatasetOrchestrationResult) -> None:
    """Explicit identity / row-count / status re-checks of the re-validated
    PR-5 result (the orchestrator itself is never re-executed)."""
    if dataset_schema_id(result.schema) != result.dataset_schema_id:
        raise DatasetMaterializationError(
            "result.dataset_schema_id does not match the carried schema"
        )
    mappings = result.logical_row_mappings()
    if (
        logical_dataset_content_id(result.schema, mappings)
        != result.logical_dataset_content_id
    ):
        raise DatasetMaterializationError(
            "result.logical_dataset_content_id does not match the carried "
            "logical rows"
        )
    if dataset_id(result.identity_input) != result.dataset_id:
        raise DatasetMaterializationError(
            "result.dataset_id does not match the carried identity input"
        )
    if len(result.rows) != result.diagnostics.logical_row_count:
        raise DatasetMaterializationError(
            "result logical row count does not match the diagnostics"
        )
    expected_status = STATUS_EMPTY if not result.rows else STATUS_COMPLETE
    if result.status != expected_status:
        raise DatasetMaterializationError(
            f"result status must be {expected_status} for {len(result.rows)} "
            f"logical rows, got {result.status!r}"
        )
    identity_input = result.identity_input
    if identity_input.dataset_kind != result.dataset_kind:
        raise DatasetMaterializationError(
            "identity_input.dataset_kind does not match the result"
        )
    if identity_input.scope != result.scope:
        raise DatasetMaterializationError(
            "identity_input.scope does not match the result"
        )
    if identity_input.dataset_as_of != result.dataset_as_of:
        raise DatasetMaterializationError(
            "identity_input.dataset_as_of does not match the result"
        )
    if identity_input.schema != result.schema:
        raise DatasetMaterializationError(
            "identity_input.schema does not match the result"
        )
    if identity_input.dataset_schema_id != result.dataset_schema_id:
        raise DatasetMaterializationError(
            "identity_input.dataset_schema_id does not match the result"
        )
    if identity_input.logical_dataset_content_id != result.logical_dataset_content_id:
        raise DatasetMaterializationError(
            "identity_input.logical_dataset_content_id does not match the result"
        )


# ---------------------------------------------------------------------------
# New build commit (staging -> verified -> _SUCCESS -> atomic rename).
# ---------------------------------------------------------------------------


def _commit_new_build(
    staging: Path,
    final: Path,
    result: DatasetOrchestrationResult,
    built_at: datetime,
) -> DatasetMaterializationResult:
    # 1. dataset.parquet (single file; the empty Dataset writes a legal
    # zero-row Parquet with the full schema and metadata).
    dataset_path = staging / DATASET_PARQUET_FILENAME
    write_dataset_parquet(
        dataset_path,
        schema=result.schema,
        rows=result.rows,
        dataset_id_value=result.dataset_id,
        dataset_schema_id_value=result.dataset_schema_id,
        logical_dataset_content_id_value=result.logical_dataset_content_id,
        serialization_format_version=result.serialization_format_version,
        row_order=result.row_order,
    )

    # 2-4. Feature / Label spec artifacts and split_spec.yaml, generated
    # deterministically from the typed models (never from original files).
    feature_dir = staging / DATASET_FEATURE_SPECS_DIRNAME
    label_dir = staging / DATASET_LABEL_SPECS_DIRNAME
    feature_dir.mkdir()
    label_dir.mkdir()
    for spec in result.feature_specs:
        _write_artifact_bytes(
            feature_dir / _feature_spec_filename(spec),
            feature_spec_artifact(spec),
        )
    for spec in result.label_specs:
        _write_artifact_bytes(
            label_dir / _label_spec_filename(spec),
            label_spec_artifact(spec),
        )
    _write_artifact_bytes(
        staging / DATASET_SPLIT_SPEC_FILENAME,
        split_spec_artifact(result.split_spec),
    )

    # 5. build_report.json (recorded facts; never identity-bearing).
    report_path = staging / DATASET_BUILD_REPORT_FILENAME
    _write_artifact_bytes(report_path, build_report_bytes(result, built_at))

    # 6. DatasetOutputFile byte facts from the actual staged files.
    records = _build_output_file_records(staging, result)

    # 7. Existing DatasetManifest core: build, verify, serialize, validate.
    manifest = build_dataset_manifest(
        result.identity_input,
        built_at=built_at,
        status=result.status,
        logical_row_count=len(result.rows),
        output_files=records,
    )
    _verify_manifest_facts(manifest, result, built_at)
    payload = serialize_dataset_manifest(manifest)
    roundtrip = validate_dataset_manifest(payload)
    if roundtrip != manifest:
        raise DatasetMaterializationError(
            "manifest roundtrip validation must reproduce the manifest exactly"
        )
    _write_artifact_bytes(staging / DATASET_MANIFEST_FILENAME, payload)

    # 8. Full private verification of the staging directory (without
    # _SUCCESS, which is written last).
    verified = _verify_build_directory(
        staging, result, built_at, require_success=False
    )
    if verified != manifest:
        raise DatasetMaterializationError(
            "staging verification must reproduce the constructed manifest"
        )

    # 9-10. _SUCCESS last (empty, regular, not a symlink), then re-verified.
    success_path = staging / DATASET_SUCCESS_FILENAME
    _write_empty_success(success_path)
    _verify_success(success_path)

    # 11. Atomic same-filesystem no-overwrite rename; a final directory that
    # appears concurrently is strictly verified (never overwritten).
    raced = _publish_staging(staging, final, result)
    if raced is not None:
        return raced
    return _result_from_manifest(final, result, manifest, created_new_build=True)


def _publish_staging(staging: Path, final: Path, result) -> DatasetMaterializationResult | None:
    """Atomic no-overwrite publication of staging onto final.

    Returns None when the rename published the new build, or an idempotent
    result when the final directory appeared concurrently and verified as
    the same logical Dataset. Never uses ``os.replace``, never deletes or
    overwrites an existing final directory, and never falls back to a
    cross-filesystem move.
    """
    if final.exists() or final.is_symlink():
        return _handle_concurrent_final(final, staging, result)
    try:
        os.rename(staging, final)
    except FileExistsError:
        # The final directory appeared between the check and the rename
        # (Windows enforces no-replace natively); verify, never overwrite.
        return _handle_concurrent_final(final, staging, result)
    except OSError as exc:
        raise DatasetMaterializationError(
            f"failed to atomically rename staging {staging} to {final}: {exc}"
        ) from exc
    return None


def _handle_concurrent_final(final: Path, staging: Path, result) -> DatasetMaterializationResult:
    """A final directory appeared before the rename: verify it strictly.

    Our staging is always removed. A verified identical build returns
    ``created_new_build=False``; a corrupt or conflicting build raises
    :class:`DatasetMaterializationError`. The existing final directory is
    never overwritten or deleted.
    """
    try:
        manifest = _verify_build_directory(final, result, None, require_success=True)
    except _DOCUMENTED_ERRORS as exc:
        _remove_tree(staging)
        raise DatasetMaterializationError(
            f"final directory appeared during staging and failed strict "
            f"verification: {final}"
        ) from exc
    _remove_tree(staging)
    return _result_from_manifest(final, result, manifest, created_new_build=False)


def _result_from_manifest(
    build_path: Path,
    result: DatasetOrchestrationResult,
    manifest,
    *,
    created_new_build: bool,
) -> DatasetMaterializationResult:
    return DatasetMaterializationResult(
        dataset_id=result.dataset_id,
        status=result.status,
        build_path=build_path,
        dataset_path=build_path / DATASET_PARQUET_FILENAME,
        manifest_path=build_path / DATASET_MANIFEST_FILENAME,
        build_report_path=build_path / DATASET_BUILD_REPORT_FILENAME,
        success_path=build_path / DATASET_SUCCESS_FILENAME,
        logical_row_count=len(result.rows),
        output_file_count=len(manifest.output_files),
        created_new_build=created_new_build,
        materializer_version=DATASET_MATERIALIZER_VERSION,
    )


def _existing_build_result(final: Path, result) -> DatasetMaterializationResult:
    """Strict verification of an existing final directory (idempotent
    return; nothing is rewritten, repaired, updated, or deleted)."""
    manifest = _verify_build_directory(final, result, None, require_success=True)
    return _result_from_manifest(final, result, manifest, created_new_build=False)


# ---------------------------------------------------------------------------
# Artifact filenames, writes, and byte facts.
# ---------------------------------------------------------------------------


def _spec_artifact_filename(pin) -> str:
    return f"{pin.name}--{pin.version}--{pin.content_sha256}.yaml"


def _feature_spec_filename(spec) -> str:
    return _spec_artifact_filename(feature_label_spec_pin(spec))


def _label_spec_filename(spec) -> str:
    return _spec_artifact_filename(feature_label_spec_pin(spec))


def _write_artifact_bytes(path: Path, data: bytes) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
    except OSError as exc:
        raise DatasetMaterializationError(
            f"failed to write artifact file {path}: {exc}"
        ) from exc


def _write_empty_success(path: Path) -> None:
    try:
        with path.open("xb") as handle:
            handle.flush()
    except OSError as exc:
        raise DatasetMaterializationError(
            f"failed to write _SUCCESS {path}: {exc}"
        ) from exc


def _read_artifact_bytes(path: Path, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise DatasetMaterializationError(
            f"failed to read {label} {path}: {exc}"
        ) from exc


def _read_artifact_text(path: Path, label: str) -> str:
    data = _read_artifact_bytes(path, label)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DatasetMaterializationError(
            f"{label} is not valid UTF-8: {path}"
        ) from exc


def _build_output_file_records(
    staging: Path, result: DatasetOrchestrationResult
) -> tuple[DatasetOutputFile, ...]:
    """Exact DatasetOutputFile records of the formal artifacts.

    ``manifest.json`` is excluded (a self-hash cycle is impossible) and
    ``_SUCCESS`` is excluded; every other formal artifact is recorded with
    its actual byte size and SHA-256. The manifest core normalizes the final
    ordering (sorted by relative path).
    """

    def record(rel: str, role: str, content_role: str, row_count: int) -> None:
        path = staging / rel
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
        len(result.rows),
    )
    record(
        DATASET_BUILD_REPORT_FILENAME,
        DATASET_OUTPUT_ROLE_BUILD_REPORT,
        DATASET_CONTENT_ROLE_BUILD_REPORT,
        1,
    )
    for spec in result.feature_specs:
        record(
            f"{DATASET_FEATURE_SPECS_DIRNAME}/{_feature_spec_filename(spec)}",
            DATASET_OUTPUT_ROLE_FEATURE_SPEC,
            DATASET_CONTENT_ROLE_FEATURE_SPEC,
            1,
        )
    for spec in result.label_specs:
        record(
            f"{DATASET_LABEL_SPECS_DIRNAME}/{_label_spec_filename(spec)}",
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
    return tuple(records)


# ---------------------------------------------------------------------------
# Manifest fact verification.
# ---------------------------------------------------------------------------


def _verify_manifest_facts(manifest, result: DatasetOrchestrationResult, built_at) -> None:
    """Every identity-bearing, status, count, and serialization fact of the
    constructed manifest must equal the verified result exactly."""
    if manifest.dataset_id != result.dataset_id:
        raise DatasetMaterializationError(
            "manifest.dataset_id does not match the result"
        )
    if manifest.dataset_kind != result.dataset_kind:
        raise DatasetMaterializationError(
            "manifest.dataset_kind does not match the result"
        )
    if manifest.dataset_schema_id != result.dataset_schema_id:
        raise DatasetMaterializationError(
            "manifest.dataset_schema_id does not match the result"
        )
    if manifest.logical_dataset_content_id != result.logical_dataset_content_id:
        raise DatasetMaterializationError(
            "manifest.logical_dataset_content_id does not match the result"
        )
    if manifest.schema != result.schema:
        raise DatasetMaterializationError(
            "manifest.schema does not match the result"
        )
    if manifest.scope != result.scope:
        raise DatasetMaterializationError(
            "manifest.scope does not match the result"
        )
    if manifest.dataset_as_of != result.dataset_as_of:
        raise DatasetMaterializationError(
            "manifest.dataset_as_of does not match the result"
        )
    if manifest.completion != result.completion:
        raise DatasetMaterializationError(
            "manifest.completion does not match the result"
        )
    if manifest.canonical_builds != result.identity_input.canonical_builds:
        raise DatasetMaterializationError(
            "manifest canonical pins do not match the result"
        )
    if (
        manifest.canonical_row_version_ids
        != result.identity_input.canonical_row_version_ids
    ):
        raise DatasetMaterializationError(
            "manifest canonical row-version IDs do not match the result"
        )
    if manifest.feature_specs != result.identity_input.feature_specs:
        raise DatasetMaterializationError(
            "manifest Feature spec pins do not match the result"
        )
    if manifest.label_specs != result.identity_input.label_specs:
        raise DatasetMaterializationError(
            "manifest Label spec pins do not match the result"
        )
    if manifest.split_spec != result.identity_input.split_spec:
        raise DatasetMaterializationError(
            "manifest split spec pin does not match the result"
        )
    if manifest.implementations != result.identity_input.implementations:
        raise DatasetMaterializationError(
            "manifest implementation pins do not match the result"
        )
    if manifest.gap_references != result.identity_input.gap_references:
        raise DatasetMaterializationError(
            "manifest gap references do not match the result"
        )
    if manifest.status != result.status:
        raise DatasetMaterializationError(
            "manifest status does not match the result"
        )
    if manifest.logical_row_count != len(result.rows):
        raise DatasetMaterializationError(
            "manifest logical_row_count does not match the result rows"
        )
    if manifest.serialization_format != result.serialization_format:
        raise DatasetMaterializationError(
            "manifest serialization_format does not match the result"
        )
    if (
        manifest.serialization_format_version
        != result.serialization_format_version
    ):
        raise DatasetMaterializationError(
            "manifest serialization_format_version does not match the result"
        )
    if manifest.manifest_schema_version != result.manifest_schema_version:
        raise DatasetMaterializationError(
            "manifest manifest_schema_version does not match the result"
        )
    if manifest.built_at != built_at:
        raise DatasetMaterializationError(
            "manifest built_at does not match the explicit built_at"
        )


# ---------------------------------------------------------------------------
# Directory verification (staging and existing builds share one validator).
# ---------------------------------------------------------------------------


def _expected_build_entries(
    result: DatasetOrchestrationResult, *, include_success: bool
) -> dict[str, str]:
    """The exact whitelist of one build directory: formal files and the two
    spec directories keyed by relative POSIX path (``file`` / ``dir``).

    ``_SUCCESS`` is included only for verified existing builds
    (``include_success=True``); the staging verification runs before
    ``_SUCCESS`` is written, so the staging whitelist deliberately omits it.
    """
    entries = {
        DATASET_PARQUET_FILENAME: "file",
        DATASET_MANIFEST_FILENAME: "file",
        DATASET_BUILD_REPORT_FILENAME: "file",
        DATASET_SPLIT_SPEC_FILENAME: "file",
        DATASET_FEATURE_SPECS_DIRNAME: "dir",
        DATASET_LABEL_SPECS_DIRNAME: "dir",
    }
    if include_success:
        entries[DATASET_SUCCESS_FILENAME] = "file"
    for spec in result.feature_specs:
        entries[f"{DATASET_FEATURE_SPECS_DIRNAME}/{_feature_spec_filename(spec)}"] = "file"
    for spec in result.label_specs:
        entries[f"{DATASET_LABEL_SPECS_DIRNAME}/{_label_spec_filename(spec)}"] = "file"
    expected_file_count = (5 if include_success else 4) + len(result.feature_specs) + len(result.label_specs)
    if len(entries) != 2 + expected_file_count:
        raise DatasetMaterializationError(
            "spec artifact filename collision detected in the expected build "
            "entry whitelist"
        )
    return entries


def _list_build_entries(build_dir: Path) -> dict[str, Path]:
    """Every entry under ``build_dir`` keyed by safe relative POSIX path."""
    entries: dict[str, Path] = {}
    for root, dirs, files in os.walk(build_dir):
        root_path = Path(root)
        base = root_path.relative_to(build_dir).as_posix()
        for name in dirs:
            rel = name if base == "." else f"{base}/{name}"
            _validate_output_relative_path(rel, "dataset entry")
            entries[rel] = root_path / name
        for name in files:
            rel = name if base == "." else f"{base}/{name}"
            _validate_output_relative_path(rel, "dataset entry")
            entries[rel] = root_path / name
    return entries


def _reject_symlink(path: Path, label: str) -> None:
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise DatasetMaterializationError(
            f"{label} must not be a symlink or junction: {path}"
        )


def _verify_success(success_path: Path) -> None:
    _reject_symlink(success_path, "dataset _SUCCESS")
    if not success_path.is_file():
        raise DatasetMaterializationError(
            f"dataset _SUCCESS must be a regular file: {success_path}"
        )
    if _read_artifact_bytes(success_path, "dataset _SUCCESS") != b"":
        raise DatasetMaterializationError(
            f"dataset _SUCCESS must be exactly empty bytes: {success_path}"
        )


def _parse_build_report(payload: bytes, expected_fields: frozenset) -> dict:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DatasetMaterializationError(
            f"build_report.json is not valid UTF-8: {exc}"
        ) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DatasetMaterializationError(
            f"build_report.json is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise DatasetMaterializationError(
            "build_report.json must be a JSON object"
        )
    unknown = sorted(set(data) - set(expected_fields))
    if unknown:
        raise DatasetMaterializationError(
            f"build_report.json unknown field(s): {', '.join(unknown)}"
        )
    missing = sorted(set(expected_fields) - set(data))
    if missing:
        raise DatasetMaterializationError(
            f"build_report.json missing field(s): {', '.join(missing)}"
        )
    for key in (
        "report_schema_version",
        "materializer_version",
        "dataset_id",
        "status",
    ):
        if not isinstance(data[key], str):
            raise DatasetMaterializationError(
                f"build_report.json {key} must be a string"
            )
    for key in ("logical_row_count",):
        if type(data[key]) is not int or isinstance(data[key], bool):
            raise DatasetMaterializationError(
                f"build_report.json {key} must be an integer"
            )
    built_at = data["built_at"]
    if built_at is not None and not isinstance(built_at, str):
        raise DatasetMaterializationError(
            "build_report.json built_at must be an ISO datetime string or null"
        )
    if built_at is not None:
        try:
            datetime.fromisoformat(built_at)
        except ValueError as exc:
            raise DatasetMaterializationError(
                f"build_report.json built_at is not a valid ISO datetime: "
                f"{built_at!r}"
            ) from exc
    return data


def _verify_build_directory(
    build_dir: Path,
    expected: DatasetOrchestrationResult,
    built_at: datetime | None,
    *,
    require_success: bool,
):
    """Private full verification of one build directory against one expected
    orchestration result (the materializer's staging verification and its
    existing-build idempotency verification share this validator; it is not
    a public Dataset reader).

    ``built_at`` is the manifest ``built_at`` the directory must carry; when
    ``None`` (existing builds) the binding is derived from the directory's
    own manifest and the report must agree with it. ``require_success=True``
    additionally enforces the ``_SUCCESS`` contract (existing builds); the
    staging path verifies everything except ``_SUCCESS``, which is written
    last and verified separately.
    """
    if not isinstance(build_dir, Path):
        raise DatasetMaterializationError(
            f"build_dir must be a Path, got {type(build_dir).__name__}"
        )
    if not build_dir.exists():
        raise DatasetMaterializationError(
            f"dataset build directory does not exist: {build_dir}"
        )
    if not build_dir.is_dir():
        raise DatasetMaterializationError(
            f"dataset build path is not a directory: {build_dir}"
        )
    _reject_symlink(build_dir, "dataset build directory")

    # Exact whitelist: every entry must be expected and regular; unexpected
    # files or directories, symlinks, junctions, and non-regular entries
    # fail closed. Every relative path is additionally validated for safety.
    expected_entries = _expected_build_entries(
        expected, include_success=require_success
    )
    actual_entries = _list_build_entries(build_dir)
    if set(actual_entries) != set(expected_entries):
        extra = sorted(set(actual_entries) - set(expected_entries))
        missing = sorted(set(expected_entries) - set(actual_entries))
        raise DatasetMaterializationError(
            f"dataset build directory has unexpected or missing entries: "
            f"extra={extra} missing={missing}"
        )
    for rel, path in actual_entries.items():
        _reject_symlink(path, f"dataset entry {rel}")
        kind = expected_entries[rel]
        if kind == "file" and not path.is_file():
            raise DatasetMaterializationError(
                f"dataset entry {rel} must be a regular file: {path}"
            )
        if kind == "dir" and not path.is_dir():
            raise DatasetMaterializationError(
                f"dataset entry {rel} must be a regular directory: {path}"
            )

    if require_success:
        _verify_success(build_dir / DATASET_SUCCESS_FILENAME)

    # Manifest: strict validation and identity binding.
    manifest_payload = _read_artifact_bytes(
        build_dir / DATASET_MANIFEST_FILENAME, "manifest.json"
    )
    manifest = validate_dataset_manifest(manifest_payload)
    # The final directory name must be exactly the dataset_id; the staging
    # directory carries the fixed ".staging-<dataset_id>" prefix and is
    # verified before publication, so the binding applies only to verified
    # existing builds (built_at is derived from the file there).
    if built_at is None and manifest.dataset_id != build_dir.name:
        raise DatasetMaterializationError(
            f"manifest dataset_id {manifest.dataset_id!r} does not equal the "
            f"directory name {build_dir.name!r}"
        )
    _verify_manifest_facts(manifest, expected, built_at=manifest.built_at)
    if built_at is not None and manifest.built_at != built_at:
        raise DatasetMaterializationError(
            "existing manifest built_at does not match the expected built_at"
        )

    # Output-file records must exactly cover the formal artifacts (all but
    # manifest.json and _SUCCESS) with byte size, SHA-256, and row counts.
    expected_output_paths = sorted(
        rel
        for rel, kind in expected_entries.items()
        if kind == "file"
        and rel not in (DATASET_MANIFEST_FILENAME, DATASET_SUCCESS_FILENAME)
    )
    manifest_paths = [record.relative_path for record in manifest.output_files]
    if manifest_paths != expected_output_paths:
        raise DatasetMaterializationError(
            "manifest output_files must exactly cover the formal artifact "
            "files"
        )
    for record in manifest.output_files:
        path = build_dir / record.relative_path
        _reject_symlink(path, f"output file {record.relative_path}")
        if not path.is_file():
            raise DatasetMaterializationError(
                f"manifest output file does not exist: {record.relative_path}"
            )
        if file_byte_size(path) != record.byte_size:
            raise DatasetMaterializationError(
                f"output file byte size mismatch: {record.relative_path}"
            )
        if file_sha256(path) != record.sha256:
            raise DatasetMaterializationError(
                f"output file SHA-256 mismatch: {record.relative_path}"
            )
        if record.relative_path == DATASET_PARQUET_FILENAME:
            if record.row_count != len(expected.rows):
                raise DatasetMaterializationError(
                    "dataset.parquet row_count does not match the expected "
                    "logical row count"
                )
        elif record.row_count != 1:
            raise DatasetMaterializationError(
                f"non-dataset artifact row_count must be 1: "
                f"{record.relative_path}"
            )

    # Parquet: schema (field order, Arrow types, nullability, metadata),
    # row count, physical row order, values, and logical content identity.
    dataset_path = build_dir / DATASET_PARQUET_FILENAME
    table = read_dataset_parquet(dataset_path)
    expected_arrow = _dataset_schema_to_arrow(
        expected.schema,
        dataset_id=expected.dataset_id,
        dataset_schema_id_value=expected.dataset_schema_id,
        logical_dataset_content_id_value=expected.logical_dataset_content_id,
        serialization_format_version=expected.serialization_format_version,
        row_order=expected.row_order,
    )
    if table.schema != expected_arrow:
        raise DatasetMaterializationError(
            "Dataset Parquet schema or metadata does not match the expected "
            "logical schema"
        )
    actual_metadata = {
        key.decode("utf-8"): value.decode("utf-8")
        for key, value in (table.schema.metadata or {}).items()
    }
    expected_metadata = {
        PARQUET_METADATA_KEY_DATASET_ID: expected.dataset_id,
        PARQUET_METADATA_KEY_SCHEMA_ID: expected.dataset_schema_id,
        PARQUET_METADATA_KEY_CONTENT_ID: expected.logical_dataset_content_id,
        PARQUET_METADATA_KEY_FORMAT_VERSION: expected.serialization_format_version,
        PARQUET_METADATA_KEY_ROW_ORDER: expected.row_order,
        PARQUET_METADATA_KEY_MATERIALIZER: DATASET_MATERIALIZER_VERSION,
    }
    if actual_metadata != expected_metadata:
        raise DatasetMaterializationError(
            "Dataset Parquet metadata does not match the expected facts"
        )
    if table.num_rows != len(expected.rows):
        raise DatasetMaterializationError(
            "Dataset Parquet row count does not match the expected logical "
            "row count"
        )
    readback_rows, content_id = readback_rows_and_content_id(
        dataset_path, expected.schema
    )
    if content_id != expected.logical_dataset_content_id:
        raise DatasetMaterializationError(
            "Dataset Parquet logical content does not match the expected "
            "logical_dataset_content_id"
        )
    if readback_rows != expected.rows:
        raise DatasetMaterializationError(
            "Dataset Parquet physical rows do not match the expected logical "
            "rows in order and value"
        )

    # Spec artifacts: Feature / Label round-trip through the existing typed
    # parse contracts with identical SpecPins; split through the strict
    # package-internal parser with the existing split SpecPin.
    for spec in expected.feature_specs:
        rel = f"{DATASET_FEATURE_SPECS_DIRNAME}/{_feature_spec_filename(spec)}"
        parsed = parse_feature_spec(_read_artifact_text(build_dir / rel, rel))
        if parsed != spec:
            raise DatasetMaterializationError(
                f"Feature spec artifact {rel} does not reproduce the "
                "expected FeatureSpec"
            )
        if feature_label_spec_pin(parsed) != feature_label_spec_pin(spec):
            raise DatasetMaterializationError(
                f"Feature spec artifact {rel} pin mismatch"
            )
    for spec in expected.label_specs:
        rel = f"{DATASET_LABEL_SPECS_DIRNAME}/{_label_spec_filename(spec)}"
        parsed = parse_label_spec(_read_artifact_text(build_dir / rel, rel))
        if parsed != spec:
            raise DatasetMaterializationError(
                f"Label spec artifact {rel} does not reproduce the expected "
                "LabelSpec"
            )
        if feature_label_spec_pin(parsed) != feature_label_spec_pin(spec):
            raise DatasetMaterializationError(
                f"Label spec artifact {rel} pin mismatch"
            )
    split_parsed = parse_split_spec_artifact(
        _read_artifact_text(
            build_dir / DATASET_SPLIT_SPEC_FILENAME, "split_spec.yaml"
        )
    )
    if split_parsed != expected.split_spec:
        raise DatasetMaterializationError(
            "split_spec.yaml does not reproduce the expected "
            "ChronologicalSplitSpec"
        )
    if chronological_split_spec_pin(split_parsed) != expected.split_result.split_spec_pin:
        raise DatasetMaterializationError(
            "split_spec.yaml pin does not match the expected split SpecPin"
        )

    # Build report: fixed schema version, materializer version, dataset_id,
    # status, row count, and built_at bound to the manifest's built_at.
    report = _parse_build_report(
        _read_artifact_bytes(
            build_dir / DATASET_BUILD_REPORT_FILENAME, "build_report.json"
        ),
        frozenset(build_report_payload(expected, manifest.built_at).keys()),
    )
    if report["report_schema_version"] != DATASET_BUILD_REPORT_SCHEMA_VERSION:
        raise DatasetMaterializationError(
            "build_report.json report_schema_version mismatch"
        )
    if report["materializer_version"] != DATASET_MATERIALIZER_VERSION:
        raise DatasetMaterializationError(
            "build_report.json materializer_version mismatch"
        )
    if report["dataset_id"] != expected.dataset_id:
        raise DatasetMaterializationError(
            "build_report.json dataset_id does not match the expected result"
        )
    if report["status"] != manifest.status:
        raise DatasetMaterializationError(
            "build_report.json status does not match the manifest"
        )
    if report["logical_row_count"] != manifest.logical_row_count:
        raise DatasetMaterializationError(
            "build_report.json logical_row_count does not match the manifest"
        )
    report_built_at = (
        datetime.fromisoformat(report["built_at"]) if report["built_at"] is not None else None
    )
    if report_built_at != manifest.built_at:
        raise DatasetMaterializationError(
            "build_report.json built_at does not match the manifest built_at"
        )

    return manifest


def _remove_tree(path: Path) -> None:
    """Best-effort removal of a directory this call created. Cleanup
    failures never hide the primary failure (the original exception is
    always the ``__cause__``); nothing outside the created directory is
    ever removed."""
    try:
        shutil.rmtree(path)
    except OSError:
        pass
