"""Deterministic immutable Dataset Catalog snapshot materialization
(v0.6.0 PR-6).

``materialize_dataset_catalog_snapshot`` commits one
:class:`~market_vault.dataset.dataset_catalog_builder_models.
DatasetCatalogBuildResult` into an immutable, traceable, fail-closed
Catalog snapshot directory with the fixed physical layout:

```text
<output_root>/<snapshot_id>/
    catalog.json
    manifest.json
    _SUCCESS
```

and the fixed staging path ``<output_root>/.staging-<snapshot_id>`` (no
random names). One commit executes the fixed sequence: re-validation of
the build result, normalization of the explicit ``built_at``, the
deterministic canonical ``catalog.json`` bytes (never the current time,
never the ``output_root`` or snapshot path), the catalog byte facts and
the physical snapshot ID, the fixed final / staging paths, output-root
link safety, strict existing-final idempotency, pre-existing staging
rejection, staging creation, exclusive-write + readback of ``catalog.json``
and ``manifest.json`` with write-return validation, a full strict private
verification of the staging directory, ``_SUCCESS`` written last (exact
empty regular file, not a symlink), its re-verification, and a true
no-replace atomic publication of staging onto the final directory (the
platform primitive itself refuses an existing destination — Windows
native directory-move semantics or Linux ``renameat2`` with
``RENAME_NOREPLACE`` — and platforms or filesystems without a safe
primitive fail closed; an overwriting ``os.rename`` / ``os.replace`` /
``shutil.move`` / delete-then-rename fallback is never used).

An existing final directory is never trusted by its name alone: it is
strictly verified through the public verified Catalog reader
(:func:`market_vault.dataset.dataset_catalog_reader.
load_verified_dataset_catalog`) and then bound to the requested result
(snapshot ID, Catalog content ID, dataset count, ``built_at``, per-entry
content facts, and the catalog byte facts); an identical existing
snapshot returns ``created_new_snapshot=False`` without rewriting or
touching anything, and a corrupt or conflicting existing snapshot fails
closed. A pre-existing staging directory is staging residue or a
concurrent build and fails closed (never deleted, never adopted). A final
directory that appears concurrently during staging is verified the same
way: an identical final returns ``created_new_snapshot=False`` after our
own staging is removed; a corrupt or conflicting final fails closed and
is never deleted or overwritten.

Ordinary exceptions after this call created the staging directory clean
up only that staging directory (best-effort) and preserve the original
exception semantics: documented business errors are converted to
:class:`DatasetCatalogMaterializationError` at the public boundary,
programming errors propagate unchanged. The final directory never appears
partially.

The entry takes an explicit timezone-aware ``built_at`` (never current
time) and an explicit ``output_root``. ``built_at`` and the catalog byte
facts are recorded facts that never enter the PR-5 Catalog content
identity.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import shutil
from datetime import datetime
from pathlib import Path

from .dataset_catalog_builder_models import DatasetCatalogBuildResult
from .dataset_catalog_identity import dataset_catalog_content_id
from .dataset_catalog_materialization_models import (
    DATASET_CATALOG_CATALOG_FILENAME,
    DATASET_CATALOG_MANIFEST_FILENAME,
    DATASET_CATALOG_STAGING_PREFIX,
    DATASET_CATALOG_SUCCESS_FILENAME,
    DatasetCatalogMaterializationError,
    DatasetCatalogMaterializationResult,
)
from .dataset_catalog_reader import load_verified_dataset_catalog
from .dataset_catalog_serialization import (
    catalog_payload_bytes,
    manifest_payload_bytes,
    parse_catalog_bytes,
    parse_manifest_bytes,
)
from .dataset_catalog_snapshot_identity import (
    DATASET_CATALOG_MATERIALIZER_VERSION,
    dataset_catalog_snapshot_id,
)
from .encoding import DatasetError, normalize_utc_datetime
from .materialization import (
    _DestinationExistsError,
    _NoReplaceUnsupportedError,
    _atomic_rename_directory_no_replace,
    _is_junction_or_reparse,
)

__all__ = ["materialize_dataset_catalog_snapshot"]

_DOCUMENTED_ERRORS = (
    DatasetError,
    OSError,
    UnicodeError,
    TypeError,
    ValueError,
    KeyError,
)


def _as_materialization_error(exc, context: str) -> None:
    """Convert a documented materialization failure to
    :class:`DatasetCatalogMaterializationError` with the ``__cause__``
    preserved; an already-raised error passes through unchanged (never
    double-wrapped); programming errors are never hidden."""
    if isinstance(exc, DatasetCatalogMaterializationError):
        raise exc
    if isinstance(exc, _DOCUMENTED_ERRORS):
        raise DatasetCatalogMaterializationError(f"{context}: {exc}") from exc
    raise exc


def materialize_dataset_catalog_snapshot(
    result: DatasetCatalogBuildResult,
    *,
    output_root,
    built_at: datetime,
) -> DatasetCatalogMaterializationResult:
    """Materialize one deterministic Catalog build result into an
    immutable Catalog snapshot directory.

    ``result`` must be a :class:`DatasetCatalogBuildResult`;
    ``output_root`` is an explicit path-like (the parent of the final
    ``output_root / <snapshot_id>`` directory); ``built_at`` must be an
    explicitly provided timezone-aware datetime (None and naive values
    fail closed; no current time and no clock callback are ever used).
    The result is fully re-validated before any file is written (its
    ``__post_init__`` is re-triggered via ``dataclasses.replace`` and the
    content identity / count / ordering facts are re-checked); the
    Dataset verified reader and the projection are never re-executed.

    The final directory is exactly ``output_root / <snapshot_id>`` with
    only ``catalog.json``, ``manifest.json``, and ``_SUCCESS`` (no
    timestamp, no random directory name, no ``latest`` pointer, no
    symlink). An existing verified identical snapshot returns
    ``created_new_snapshot=False`` without rewriting anything; a
    conflicting or corrupt existing snapshot, pre-existing staging
    residue, or any verification failure raises
    :class:`DatasetCatalogMaterializationError` (fail closed, no partial
    result, ``__cause__`` preserved).
    """
    try:
        return _materialize(
            result, output_root=output_root, built_at=built_at
        )
    except DatasetCatalogMaterializationError:
        raise
    except _DOCUMENTED_ERRORS as exc:
        _as_materialization_error(exc, "materialize_dataset_catalog_snapshot failed")


def _coerce_output_root(output_root) -> Path:
    try:
        path = Path(output_root)
    except TypeError as exc:
        raise DatasetCatalogMaterializationError(
            f"output_root must be a path-like, got {type(output_root).__name__}"
        ) from exc
    if not isinstance(path, Path):
        raise DatasetCatalogMaterializationError(
            f"output_root must be a path-like, got {type(output_root).__name__}"
        )
    # Lexical absolute path only (never resolves symlinks, never touches
    # the filesystem).
    return path.absolute()


def _reject_symlink(path: Path, label: str) -> None:
    if path.is_symlink() or _is_junction_or_reparse(path):
        raise DatasetCatalogMaterializationError(
            f"{label} must not be a symlink or junction: {path}"
        )


def _verify_output_root_safety(output_root: Path) -> None:
    """``output_root`` and every path component must be a real, regular
    directory.

    Called both before and after the output root is created; a component
    whose link status cannot be verified fails closed (Python 3.11
    Windows reparse-point detection included). ``resolve()`` is never
    used to mask a link.
    """
    for component in (output_root, *output_root.parents):
        _reject_symlink(component, "output root or path component")
        if component.exists() and not component.is_dir():
            raise DatasetCatalogMaterializationError(
                f"output root or path component must be a regular "
                f"directory: {component}"
            )


def _verify_revalidated_result(result: DatasetCatalogBuildResult) -> None:
    """Explicit identity / count / ordering re-checks of the re-validated
    build result (the builder itself is never re-executed)."""
    if dataset_catalog_content_id(result.entries) != result.catalog_content_id:
        raise DatasetCatalogMaterializationError(
            "result.catalog_content_id does not match the recomputed PR-5 "
            "Catalog content identity of the entries"
        )
    if len(result.entries) != result.dataset_count:
        raise DatasetCatalogMaterializationError(
            "result.dataset_count does not match the entry count"
        )
    ids = [entry.dataset_facts.dataset_id for entry in result.entries]
    if ids != sorted(ids) or len(set(ids)) != len(ids):
        raise DatasetCatalogMaterializationError(
            "result entries must be sorted by dataset_id with no duplicates"
        )


def _materialize(
    result: DatasetCatalogBuildResult,
    *,
    output_root,
    built_at: datetime,
) -> DatasetCatalogMaterializationResult:
    # 1. Explicit public input contract (fail closed on every violation).
    if not isinstance(result, DatasetCatalogBuildResult):
        raise DatasetCatalogMaterializationError(
            f"result must be a DatasetCatalogBuildResult, got "
            f"{type(result).__name__}"
        )
    output_root = _coerce_output_root(output_root)

    # 2. Re-trigger the complete builder self-validation: never trust the
    #    object type or cached fields, never re-execute the builder.
    revalidated = dataclasses.replace(result)
    if revalidated != result:
        raise DatasetCatalogMaterializationError(
            "result re-validation produced a different result; the carried "
            "DatasetCatalogBuildResult must be self-consistent"
        )
    _verify_revalidated_result(result)

    # 3. Normalize the explicit built_at (UTC microseconds).
    built_at = normalize_utc_datetime(built_at, "built_at")

    # 4. Deterministic canonical catalog.json bytes (same result -> same
    #    bytes; current time, output_root, snapshot path, host, cwd,
    #    mtimes, and scan / candidate order never enter them).
    catalog_bytes = catalog_payload_bytes(result)
    catalog_byte_size = len(catalog_bytes)
    catalog_sha256 = hashlib.sha256(catalog_bytes).hexdigest()

    # 5. Physical snapshot identity (content identity + observed facts +
    #    explicit built_at + catalog byte facts).
    snapshot_id = dataset_catalog_snapshot_id(
        catalog_content_id=result.catalog_content_id,
        dataset_count=result.dataset_count,
        built_at=built_at,
        catalog_file_byte_size=catalog_byte_size,
        catalog_file_sha256=catalog_sha256,
    )

    # 6. Fixed final and staging paths (same filesystem, no random names).
    final = output_root / snapshot_id
    staging = output_root / f"{DATASET_CATALOG_STAGING_PREFIX}{snapshot_id}"

    # 7. Output-root safety runs before ANY final / staging existence
    #    query, before the existing-snapshot access, before the
    #    staging-residue judgement, and before any artifact read or
    #    directory creation: the existing-snapshot idempotency path shares
    #    exactly the same link boundary as the new-snapshot path.
    _verify_output_root_safety(output_root)

    # 8. Existing final directory: strict verification through the public
    #    verified reader plus binding to the requested result; idempotent
    #    return; no staging is created and nothing is ever rewritten.
    if final.exists() or final.is_symlink():
        verified = _verify_existing_final(
            final,
            result=result,
            built_at=built_at,
            snapshot_id=snapshot_id,
            catalog_bytes=catalog_bytes,
        )
        return _result_from_verified(final, verified, created_new_snapshot=False)

    # 9. Pre-existing staging is residue or a concurrent build: fail
    #    closed, never delete, never adopt, never overwrite.
    if staging.exists() or staging.is_symlink():
        raise DatasetCatalogMaterializationError(
            f"staging directory already exists (crash residue or concurrent "
            f"build): {staging}; refusing to build over it"
        )

    # 10. Create the output root and the fixed staging directory; the
    #     post-creation re-verification detects path replacement during
    #     creation.
    try:
        output_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DatasetCatalogMaterializationError(
            f"failed to create output root {output_root}: {exc}"
        ) from exc
    _verify_output_root_safety(output_root)
    try:
        staging.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise DatasetCatalogMaterializationError(
            f"staging directory appeared concurrently: {staging}"
        ) from exc
    except OSError as exc:
        raise DatasetCatalogMaterializationError(
            f"failed to create staging directory {staging}: {exc}"
        ) from exc

    # 11. Commit; every exception after the staging creation cleans up
    #     only the staging created here (best-effort) and preserves the
    #     original exception semantics.
    try:
        return _commit_new_snapshot(
            staging,
            final,
            result,
            built_at=built_at,
            snapshot_id=snapshot_id,
            catalog_bytes=catalog_bytes,
            catalog_byte_size=catalog_byte_size,
            catalog_sha256=catalog_sha256,
        )
    except Exception:
        _remove_tree(staging)
        raise


# ---------------------------------------------------------------------------
# New snapshot commit (staging -> verified -> _SUCCESS -> atomic rename).
# ---------------------------------------------------------------------------


def _write_exact_bytes(path: Path, data: bytes, label: str) -> None:
    """Exclusive write with write-return validation (fail closed).

    ``handle.write`` must return exactly ``len(data)`` as a real int; a
    ``None``, bool, short, long, or differently typed return is rejected
    (never silently accepted), then the handle is flushed and closed by
    the context manager.
    """
    try:
        with path.open("xb") as handle:
            written = handle.write(data)
            if type(written) is not int or written != len(data):
                raise DatasetCatalogMaterializationError(
                    f"invalid write return while writing {label} {path}: "
                    f"handle.write returned {written!r} for {len(data)} bytes"
                )
            handle.flush()
    except OSError as exc:
        raise DatasetCatalogMaterializationError(
            f"failed to write {label} {path}: {exc}"
        ) from exc


def _write_empty_success(path: Path) -> None:
    """``_SUCCESS`` must be an exact empty regular file, written
    exclusively with write-return validation."""
    try:
        with path.open("xb") as handle:
            written = handle.write(b"")
            if type(written) is not int or written != 0:
                raise DatasetCatalogMaterializationError(
                    f"invalid write return while writing _SUCCESS {path}: "
                    f"handle.write returned {written!r}"
                )
            handle.flush()
    except OSError as exc:
        raise DatasetCatalogMaterializationError(
            f"failed to write _SUCCESS {path}: {exc}"
        ) from exc


def _read_artifact_bytes(path: Path, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise DatasetCatalogMaterializationError(
            f"failed to read {label} {path}: {exc}"
        ) from exc


def _readback_exact(path: Path, expected: bytes, label: str) -> bytes:
    actual = _read_artifact_bytes(path, label)
    if actual != expected:
        raise DatasetCatalogMaterializationError(
            f"{label} readback must equal the written bytes exactly: {path}"
        )
    return actual


def _verify_success(success_path: Path) -> None:
    _reject_symlink(success_path, "catalog snapshot _SUCCESS")
    if not success_path.is_file():
        raise DatasetCatalogMaterializationError(
            f"catalog snapshot _SUCCESS must be a regular file: {success_path}"
        )
    if _read_artifact_bytes(success_path, "catalog snapshot _SUCCESS") != b"":
        raise DatasetCatalogMaterializationError(
            f"catalog snapshot _SUCCESS must be exactly empty bytes: "
            f"{success_path}"
        )


def _list_snapshot_entries(snapshot_dir: Path) -> dict[str, Path]:
    """Safe single-level enumeration: every entry must be a regular
    non-link file; directories, symlinks, junctions, FIFOs, and sockets
    fail closed (never descended)."""
    try:
        with os.scandir(snapshot_dir) as iterator:
            items = sorted(iterator, key=lambda item: item.name)
    except OSError as exc:
        raise DatasetCatalogMaterializationError(
            f"failed to enumerate snapshot directory {snapshot_dir}: {exc}"
        ) from exc
    entries: dict[str, Path] = {}
    for item in items:
        path = Path(item.path)
        _reject_symlink(path, f"snapshot entry {item.name}")
        if not item.is_file(follow_symlinks=False):
            raise DatasetCatalogMaterializationError(
                f"snapshot entry must be a regular file: {item.name}"
            )
        entries[item.name] = path
    return entries


def _verify_staging_snapshot(
    staging: Path,
    *,
    result: DatasetCatalogBuildResult,
    built_at: datetime,
    snapshot_id: str,
    catalog_bytes: bytes,
    manifest_bytes: bytes,
) -> None:
    """Full strict private verification of the staging directory (before
    ``_SUCCESS``): the exact two-file whitelist, readback byte equality,
    strict parse (canonical bytes enforced inside), and every binding to
    the requested result, the snapshot ID, and the catalog byte facts."""
    actual_entries = _list_snapshot_entries(staging)
    expected_entries = {
        DATASET_CATALOG_CATALOG_FILENAME,
        DATASET_CATALOG_MANIFEST_FILENAME,
    }
    if set(actual_entries) != expected_entries:
        extra = sorted(set(actual_entries) - expected_entries)
        missing = sorted(expected_entries - set(actual_entries))
        raise DatasetCatalogMaterializationError(
            f"staging snapshot directory has unexpected or missing entries: "
            f"extra={extra} missing={missing}"
        )

    actual_catalog = _readback_exact(
        staging / DATASET_CATALOG_CATALOG_FILENAME,
        catalog_bytes,
        "catalog.json",
    )
    parsed = parse_catalog_bytes(actual_catalog)
    if parsed.catalog_content_id != result.catalog_content_id:
        raise DatasetCatalogMaterializationError(
            "staging catalog.json catalog_content_id does not match the "
            "result"
        )
    if parsed.dataset_count != result.dataset_count:
        raise DatasetCatalogMaterializationError(
            "staging catalog.json dataset_count does not match the result"
        )
    if parsed.builder_version != result.builder_version:
        raise DatasetCatalogMaterializationError(
            "staging catalog.json builder_version does not match the result"
        )
    expected_by_id = {
        entry.dataset_facts.dataset_id: entry.dataset_facts
        for entry in result.entries
    }
    actual_by_id = {
        entry.dataset_facts.dataset_id: entry.dataset_facts
        for entry in parsed.entries
    }
    if actual_by_id != expected_by_id:
        raise DatasetCatalogMaterializationError(
            "staging catalog.json dataset facts do not match the result "
            "entries"
        )

    actual_manifest = _readback_exact(
        staging / DATASET_CATALOG_MANIFEST_FILENAME,
        manifest_bytes,
        "manifest.json",
    )
    parsed_manifest = parse_manifest_bytes(actual_manifest)
    if parsed_manifest.snapshot_id != snapshot_id:
        raise DatasetCatalogMaterializationError(
            "staging manifest.json snapshot_id does not match the computed "
            "snapshot_id"
        )
    if parsed_manifest.catalog_content_id != result.catalog_content_id:
        raise DatasetCatalogMaterializationError(
            "staging manifest.json catalog_content_id does not match the "
            "result"
        )
    if parsed_manifest.built_at != built_at:
        raise DatasetCatalogMaterializationError(
            "staging manifest.json built_at does not match the explicit "
            "built_at"
        )
    if parsed_manifest.dataset_count != result.dataset_count:
        raise DatasetCatalogMaterializationError(
            "staging manifest.json dataset_count does not match the result"
        )
    if parsed_manifest.catalog_byte_size != len(catalog_bytes):
        raise DatasetCatalogMaterializationError(
            "staging manifest.json catalog_file.byte_size does not match "
            "the catalog.json bytes"
        )
    if parsed_manifest.catalog_sha256 != hashlib.sha256(catalog_bytes).hexdigest():
        raise DatasetCatalogMaterializationError(
            "staging manifest.json catalog_file.sha256 does not match the "
            "catalog.json bytes"
        )


def _commit_new_snapshot(
    staging: Path,
    final: Path,
    result: DatasetCatalogBuildResult,
    *,
    built_at: datetime,
    snapshot_id: str,
    catalog_bytes: bytes,
    catalog_byte_size: int,
    catalog_sha256: str,
) -> DatasetCatalogMaterializationResult:
    # 1. catalog.json: exclusive write with write-return validation,
    #    then exact readback.
    catalog_path = staging / DATASET_CATALOG_CATALOG_FILENAME
    _write_exact_bytes(catalog_path, catalog_bytes, "catalog.json")
    _readback_exact(catalog_path, catalog_bytes, "catalog.json")

    # 2. manifest.json: constructed from the snapshot ID and the catalog
    #    byte facts, then exclusive write + exact readback.
    manifest_bytes = manifest_payload_bytes(
        snapshot_id=snapshot_id,
        catalog_content_id=result.catalog_content_id,
        dataset_count=result.dataset_count,
        built_at=built_at,
        catalog_byte_size=catalog_byte_size,
        catalog_sha256=catalog_sha256,
    )
    manifest_path = staging / DATASET_CATALOG_MANIFEST_FILENAME
    _write_exact_bytes(manifest_path, manifest_bytes, "manifest.json")
    _readback_exact(manifest_path, manifest_bytes, "manifest.json")

    # 3. Full strict private verification of the staging directory
    #    (without _SUCCESS, which is written last).
    _verify_staging_snapshot(
        staging,
        result=result,
        built_at=built_at,
        snapshot_id=snapshot_id,
        catalog_bytes=catalog_bytes,
        manifest_bytes=manifest_bytes,
    )

    # 4. _SUCCESS last (exact empty regular file, not a symlink), then
    #    re-verified.
    success_path = staging / DATASET_CATALOG_SUCCESS_FILENAME
    _write_empty_success(success_path)
    _verify_success(success_path)

    # 5. Atomic same-filesystem no-overwrite publication; a final
    #    directory that appears concurrently is strictly verified (never
    #    overwritten).
    raced = _publish_staging(
        staging,
        final,
        result=result,
        built_at=built_at,
        snapshot_id=snapshot_id,
        catalog_bytes=catalog_bytes,
    )
    if raced is not None:
        return raced
    return _result_from_new(final, result, snapshot_id)


def _publish_staging(
    staging: Path,
    final: Path,
    *,
    result: DatasetCatalogBuildResult,
    built_at: datetime,
    snapshot_id: str,
    catalog_bytes: bytes,
) -> DatasetCatalogMaterializationResult | None:
    """Atomic no-overwrite publication of staging onto final.

    Returns None when the atomic no-replace publication published the new
    snapshot, or an idempotent result when the final directory appeared
    concurrently and verified as the same logical snapshot. The existence
    pre-check is only a fast path; the safety guarantee comes from the
    atomic no-replace primitive itself, whose destination-exists result
    flows into the concurrent-final handling.
    """
    if final.exists() or final.is_symlink():
        return _handle_concurrent_final(
            final,
            staging,
            result=result,
            built_at=built_at,
            snapshot_id=snapshot_id,
            catalog_bytes=catalog_bytes,
        )
    try:
        _atomic_rename_directory_no_replace(staging, final)
    except _DestinationExistsError:
        return _handle_concurrent_final(
            final,
            staging,
            result=result,
            built_at=built_at,
            snapshot_id=snapshot_id,
            catalog_bytes=catalog_bytes,
        )
    except _NoReplaceUnsupportedError as exc:
        raise DatasetCatalogMaterializationError(
            f"safe no-replace directory publication is unavailable on this "
            f"platform or filesystem; refusing to fall back to an "
            f"overwriting rename: {exc}"
        ) from exc
    return None


def _handle_concurrent_final(
    final: Path,
    staging: Path,
    *,
    result: DatasetCatalogBuildResult,
    built_at: datetime,
    snapshot_id: str,
    catalog_bytes: bytes,
) -> DatasetCatalogMaterializationResult:
    """A final directory appeared before the rename: verify it strictly.

    Our staging is always removed. A verified identical snapshot returns
    ``created_new_snapshot=False``; a corrupt or conflicting snapshot
    raises :class:`DatasetCatalogMaterializationError`. The existing
    final directory is never overwritten or deleted.
    """
    try:
        verified = _verify_existing_final(
            final,
            result=result,
            built_at=built_at,
            snapshot_id=snapshot_id,
            catalog_bytes=catalog_bytes,
        )
    except _DOCUMENTED_ERRORS as exc:
        _remove_tree(staging)
        raise DatasetCatalogMaterializationError(
            f"final snapshot directory appeared during staging and failed "
            f"strict verification: {final}"
        ) from exc
    _remove_tree(staging)
    return _result_from_verified(final, verified, created_new_snapshot=False)


def _verify_existing_final(
    final: Path,
    *,
    result: DatasetCatalogBuildResult,
    built_at: datetime,
    snapshot_id: str,
    catalog_bytes: bytes,
):
    """Strict verification of an existing final directory: the public
    verified reader verifies the snapshot directory itself, then every
    binding to the requested result and to our generated catalog bytes is
    enforced. Nothing is rewritten, repaired, updated, or deleted."""
    verified = load_verified_dataset_catalog(final)
    if verified.snapshot_id != snapshot_id:
        raise DatasetCatalogMaterializationError(
            "existing snapshot_id does not match the requested snapshot_id"
        )
    if verified.catalog_content_id != result.catalog_content_id:
        raise DatasetCatalogMaterializationError(
            "existing catalog_content_id does not match the requested "
            "Catalog content identity"
        )
    if verified.dataset_count != result.dataset_count:
        raise DatasetCatalogMaterializationError(
            "existing dataset_count does not match the requested dataset "
            "count"
        )
    if verified.manifest.built_at != built_at:
        raise DatasetCatalogMaterializationError(
            "existing manifest built_at does not match the explicit built_at"
        )
    expected_by_id = {
        entry.dataset_facts.dataset_id: entry.dataset_facts
        for entry in result.entries
    }
    actual_by_id = {
        record.dataset_id: record.dataset_facts for record in verified.entries
    }
    if actual_by_id != expected_by_id:
        raise DatasetCatalogMaterializationError(
            "existing snapshot dataset facts do not match the requested "
            "result entries"
        )
    file_record = verified.manifest.catalog_file
    if file_record.byte_size != len(catalog_bytes) or (
        file_record.sha256 != hashlib.sha256(catalog_bytes).hexdigest()
    ):
        raise DatasetCatalogMaterializationError(
            "existing manifest catalog_file byte facts do not match the "
            "requested catalog.json bytes"
        )
    return verified


def _result_from_verified(
    final: Path,
    verified,
    *,
    created_new_snapshot: bool,
) -> DatasetCatalogMaterializationResult:
    return DatasetCatalogMaterializationResult(
        snapshot_id=verified.snapshot_id,
        catalog_content_id=verified.catalog_content_id,
        dataset_count=verified.dataset_count,
        snapshot_path=final,
        catalog_path=final / DATASET_CATALOG_CATALOG_FILENAME,
        manifest_path=final / DATASET_CATALOG_MANIFEST_FILENAME,
        success_path=final / DATASET_CATALOG_SUCCESS_FILENAME,
        created_new_snapshot=created_new_snapshot,
        materializer_version=DATASET_CATALOG_MATERIALIZER_VERSION,
    )


def _result_from_new(
    final: Path,
    result: DatasetCatalogBuildResult,
    snapshot_id: str,
) -> DatasetCatalogMaterializationResult:
    return DatasetCatalogMaterializationResult(
        snapshot_id=snapshot_id,
        catalog_content_id=result.catalog_content_id,
        dataset_count=result.dataset_count,
        snapshot_path=final,
        catalog_path=final / DATASET_CATALOG_CATALOG_FILENAME,
        manifest_path=final / DATASET_CATALOG_MANIFEST_FILENAME,
        success_path=final / DATASET_CATALOG_SUCCESS_FILENAME,
        created_new_snapshot=True,
        materializer_version=DATASET_CATALOG_MATERIALIZER_VERSION,
    )


def _remove_tree(path: Path) -> None:
    """Best-effort removal of a directory this call created. Cleanup
    failures never hide the primary failure (the original exception is
    always re-raised); nothing outside the created directory is ever
    removed."""
    try:
        shutil.rmtree(path)
    except OSError:
        pass
