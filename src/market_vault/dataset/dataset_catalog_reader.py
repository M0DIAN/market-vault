"""Verified Dataset Catalog snapshot reader (v0.6.0 PR-6).

``load_verified_dataset_catalog`` is the one public, read-only,
fail-closed read path into committed Catalog snapshot directories: it
accepts one explicit final snapshot directory
(``<output_root>/<snapshot_id>``) and independently rebuilds and verifies
the complete snapshot facts from the directory's own ``catalog.json``,
``manifest.json``, and ``_SUCCESS``.

The reader verifies only the snapshot itself — the immutable record of
facts that were verified at build time:

- it never calls ``load_verified_dataset``;
- it never accesses a recorded Dataset build path (the recorded build
  location is historical observed location text with a shape contract
  only; it is never resolved, stat'ed, checked for existence, and
  never reloaded), so a Dataset that later moved, went offline, was
  deleted, or sits on an unmounted disk never makes an intact snapshot
  unverifiable;
- it never scans the Dataset root or the Catalog ``output_root``;
- it never connects to OpenD / the network, never loads settings, and
  never reads the current time;
- it never writes, repairs, rewrites, or deletes any file.

The strict sequence: explicit snapshot directory coerced to a lexical
absolute path; parent-chain link safety; the snapshot directory itself
must be a real regular directory named exactly the 64-hex
``snapshot_id``; the exact three-file whitelist; every entry regular and
non-link; ``_SUCCESS`` exactly empty; ``manifest.json`` read and strictly
parsed (exact field set, fixed versions, canonical bytes equality);
``snapshot_id`` == directory name; ``catalog.json`` read and strictly
parsed with byte size / SHA-256 equal to the manifest ``catalog_file``
record; every entry content ID recomputed over the reconstructed typed
PR-5 facts; dataset ordering and uniqueness; the PR-5 Catalog content
identity recomputed over the facts (never trusting the recorded
``catalog_content_id``) and compared to the top-level and manifest
values; the dataset counts cross-checked; the physical snapshot ID
recomputed and compared to the manifest; and a second pass re-verifying
the path contract, the whitelist, ``_SUCCESS``, the manifest bytes, and
the catalog bytes / hash (a concurrent modification fails closed; no
mixed-instant partial result is ever returned).

Every documented failure surfaces as
:class:`DatasetCatalogArtifactValidationError` with the ``__cause__``
preserved; an already-wrapped error is never double-wrapped, no partial
:class:`VerifiedDatasetCatalogSnapshot` is ever returned, and broad
``except Exception`` is never used (real programming errors are not
disguised as artifact corruption).
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from .dataset_catalog_identity import _dataset_catalog_content_id_from_facts
from .dataset_catalog_materialization_models import (
    DATASET_CATALOG_CATALOG_FILENAME,
    DATASET_CATALOG_MANIFEST_FILENAME,
    DATASET_CATALOG_SUCCESS_FILENAME,
)
from .dataset_catalog_models import DatasetCatalogError
from .dataset_catalog_reader_models import (
    DATASET_CATALOG_READER_CONTRACT_VERSION,
    DatasetCatalogArtifactValidationError,
    DatasetCatalogFileRecord,
    DatasetCatalogSnapshotEntryRecord,
    DatasetCatalogSnapshotManifestRecord,
    VerifiedDatasetCatalogSnapshot,
)
from .dataset_catalog_serialization import (
    parse_catalog_bytes,
    parse_manifest_bytes,
)
from .dataset_catalog_snapshot_identity import dataset_catalog_snapshot_id
from .encoding import DatasetError
from .materialization import _is_junction_or_reparse

__all__ = ["load_verified_dataset_catalog"]

_SNAPSHOT_ID_RE = re.compile(r"^[0-9a-f]{64}$")

#: The exact whitelist of one final snapshot directory.
_SNAPSHOT_WHITELIST = frozenset(
    {
        DATASET_CATALOG_CATALOG_FILENAME,
        DATASET_CATALOG_MANIFEST_FILENAME,
        DATASET_CATALOG_SUCCESS_FILENAME,
    }
)

_DOCUMENTED_ERRORS = (
    DatasetError,
    OSError,
    UnicodeError,
    TypeError,
    ValueError,
    KeyError,
)


def _fail(reason: str) -> None:
    raise DatasetCatalogArtifactValidationError(reason)


def load_verified_dataset_catalog(snapshot_dir) -> VerifiedDatasetCatalogSnapshot:
    """Read and strictly verify one immutable Catalog snapshot directory.

    ``snapshot_dir`` must be a path-like pointing at the exact final
    snapshot directory ``<output_root>/<snapshot_id>`` (absolute or
    relative). The directory name must be the lowercase 64-hex
    ``snapshot_id`` carried by the manifest; ``.staging-<id>`` and any
    other name are rejected. The path must be lexically absolute
    (``resolve()`` is never used to mask a link), must not contain
    ``.`` / ``..`` components, and no path component may be a symlink or
    Windows junction (Python 3.11 reparse-point detection included; a
    path whose link status cannot be verified fails closed).

    The snapshot is verified entirely from its own artifacts; the
    recorded Dataset build locations are historical text and are never
    reloaded or re-verified, so relocating the snapshot to another parent
    (or another machine) never breaks verification as long as the
    directory name stays the ``snapshot_id``. Any inconsistency raises
    :class:`DatasetCatalogArtifactValidationError`. Nothing is written,
    repaired, rewritten, or deleted; no current time, no random values,
    no environment variables, no settings, and no network are used.
    """
    try:
        return _load_verified_dataset_catalog(snapshot_dir)
    except DatasetCatalogArtifactValidationError:
        raise
    except _DOCUMENTED_ERRORS as exc:
        _convert_documented_error(exc, "load_verified_dataset_catalog failed")


def _convert_documented_error(exc, context: str) -> None:
    """Convert every documented failure to
    :class:`DatasetCatalogArtifactValidationError` with the ``__cause__``
    preserved. An already-raised
    :class:`DatasetCatalogArtifactValidationError` passes through
    unchanged (never double-wrapped); broad ``except Exception`` is never
    used, so real programming errors are not hidden."""
    if isinstance(exc, DatasetCatalogArtifactValidationError):
        raise exc
    if isinstance(exc, _DOCUMENTED_ERRORS):
        raise DatasetCatalogArtifactValidationError(f"{context}: {exc}") from exc
    raise exc


# ---------------------------------------------------------------------------
# Path and link safety.
# ---------------------------------------------------------------------------


def _coerce_snapshot_dir(snapshot_dir) -> Path:
    """Lexically absolute Path of the input; raw ``.`` / ``..`` components
    are rejected before any normalization and ``resolve()`` is never used
    to mask a link."""
    try:
        raw_text = os.fspath(snapshot_dir)
    except TypeError as exc:
        raise DatasetCatalogArtifactValidationError(
            f"snapshot_dir must be a path-like, got "
            f"{type(snapshot_dir).__name__}"
        ) from exc
    for part in raw_text.replace("\\", "/").split("/"):
        if part in (".", ".."):
            raise DatasetCatalogArtifactValidationError(
                f"snapshot_dir must not contain '.' or '..' path components: "
                f"{snapshot_dir!r}"
            )
    try:
        raw = Path(snapshot_dir)
    except TypeError as exc:
        raise DatasetCatalogArtifactValidationError(
            f"snapshot_dir must be a path-like, got "
            f"{type(snapshot_dir).__name__}"
        ) from exc
    if not isinstance(raw, Path):
        raise DatasetCatalogArtifactValidationError(
            f"snapshot_dir must be a path-like, got "
            f"{type(snapshot_dir).__name__}"
        )
    if raw.is_absolute():
        return raw
    try:
        return Path.cwd() / raw
    except OSError as exc:
        raise DatasetCatalogArtifactValidationError(
            f"cannot resolve the current working directory for a relative "
            f"snapshot_dir: {exc}"
        ) from exc


def _reject_symlink(path: Path, label: str) -> None:
    if path.is_symlink() or _is_junction_or_reparse(path):
        _fail(f"{label} must not be a symlink or junction: {path}")


def _verify_snapshot_dir_safety(snapshot: Path) -> None:
    """``snapshot`` and every existing parent component must be a real,
    regular directory; the directory name must be the lowercase 64-hex
    ``snapshot_id``. A component whose link status cannot be verified
    fails closed (Python 3.11 Windows reparse-point detection included)."""
    for component in (snapshot.parent, *snapshot.parents):
        _reject_symlink(component, "snapshot path component")
        if component.exists() and not component.is_dir():
            _fail(
                f"snapshot path component must be a regular directory: "
                f"{component}"
            )
    if not snapshot.exists():
        _fail(f"catalog snapshot directory does not exist: {snapshot}")
    if not snapshot.is_dir():
        _fail(f"catalog snapshot path is not a directory: {snapshot}")
    _reject_symlink(snapshot, "catalog snapshot directory")
    if not _SNAPSHOT_ID_RE.fullmatch(snapshot.name):
        _fail(
            f"catalog snapshot directory name must be a 64-character "
            f"lowercase SHA-256 hex string, got {snapshot.name!r}; "
            f"'.staging-<id>' and any other name are not valid snapshot "
            f"directories"
        )


# ---------------------------------------------------------------------------
# Entries, whitelist, and artifacts.
# ---------------------------------------------------------------------------


def _list_snapshot_entries(snapshot: Path) -> dict[str, Path]:
    """Safe single-level enumeration of one snapshot directory: every
    entry must be a regular non-link file; directories, symlinks,
    junctions, FIFOs, and sockets fail closed (never descended; no
    recursion, no ``os.walk``, no ``rglob``)."""
    try:
        with os.scandir(snapshot) as iterator:
            items = sorted(iterator, key=lambda item: item.name)
    except OSError as exc:
        raise DatasetCatalogArtifactValidationError(
            f"failed to enumerate catalog snapshot directory {snapshot}: {exc}"
        ) from exc
    entries: dict[str, Path] = {}
    for item in items:
        path = Path(item.path)
        _reject_symlink(path, f"catalog snapshot entry {item.name}")
        if not item.is_file(follow_symlinks=False):
            _fail(
                f"catalog snapshot entry must be a regular file: {item.name}"
            )
        entries[item.name] = path
    return entries


def _verify_entries(snapshot: Path) -> None:
    """The exact whitelist: only ``catalog.json``, ``manifest.json``, and
    ``_SUCCESS`` may exist; anything else fails closed."""
    actual = set(_list_snapshot_entries(snapshot))
    if actual != _SNAPSHOT_WHITELIST:
        extra = sorted(actual - _SNAPSHOT_WHITELIST)
        missing = sorted(_SNAPSHOT_WHITELIST - actual)
        _fail(
            f"catalog snapshot directory has unexpected or missing entries: "
            f"extra={extra} missing={missing}"
        )


def _verify_success(success_path: Path) -> None:
    _reject_symlink(success_path, "catalog snapshot _SUCCESS")
    if not success_path.is_file():
        _fail(f"catalog snapshot _SUCCESS must be a regular file: {success_path}")
    if _read_artifact_bytes(success_path, "catalog snapshot _SUCCESS") != b"":
        _fail(
            f"catalog snapshot _SUCCESS must be exactly empty bytes: "
            f"{success_path}"
        )


def _read_artifact_bytes(path: Path, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise DatasetCatalogArtifactValidationError(
            f"failed to read {label} {path}: {exc}"
        ) from exc


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise DatasetCatalogArtifactValidationError(
            f"failed to hash catalog snapshot file {path}: {exc}"
        ) from exc
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Fixed read sequence.
# ---------------------------------------------------------------------------


def _load_verified_dataset_catalog(snapshot_dir) -> VerifiedDatasetCatalogSnapshot:
    # 1-5. Input contract, lexical absolute path, parent-chain link
    # safety, the snapshot directory itself, and the strict 64-hex
    # directory-name binding.
    snapshot = _coerce_snapshot_dir(snapshot_dir)
    _verify_snapshot_dir_safety(snapshot)

    # 6-8. Exact whitelist, symlink / junction rejection of every entry,
    # and the _SUCCESS contract.
    _verify_entries(snapshot)
    _verify_success(snapshot / DATASET_CATALOG_SUCCESS_FILENAME)

    # 9-12. Manifest: strict exact-field parse (fixed versions, canonical
    # bytes equality) and the directory-name / snapshot_id binding.
    manifest_bytes = _read_artifact_bytes(
        snapshot / DATASET_CATALOG_MANIFEST_FILENAME, "manifest.json"
    )
    manifest = parse_manifest_bytes(manifest_bytes)
    if manifest.snapshot_id != snapshot.name:
        _fail(
            f"manifest snapshot_id {manifest.snapshot_id!r} does not equal "
            f"the snapshot directory name {snapshot.name!r}"
        )

    # 13-16. catalog.json: bytes read, byte size / SHA-256 equal to the
    # manifest catalog_file record, strict exact-field parse (fixed
    # versions, typed nested reconstruction, canonical bytes equality).
    catalog_path = snapshot / DATASET_CATALOG_CATALOG_FILENAME
    catalog_bytes = _read_artifact_bytes(catalog_path, "catalog.json")
    if manifest.catalog_byte_size != len(catalog_bytes):
        _fail(
            f"catalog.json byte size {len(catalog_bytes)} does not match the "
            f"manifest record {manifest.catalog_byte_size}"
        )
    if manifest.catalog_sha256 != _file_sha256(catalog_path):
        _fail("catalog.json SHA-256 does not match the manifest record")
    catalog = parse_catalog_bytes(catalog_bytes)

    # 17-19. Reconstruct the typed entry records (each recomputes its
    # content ID over its facts) and verify dataset ordering / uniqueness.
    entries = tuple(
        DatasetCatalogSnapshotEntryRecord(
            dataset_id=parsed.dataset_facts.dataset_id,
            content_id=parsed.content_id,
            dataset_facts=parsed.dataset_facts,
            recorded_built_at=parsed.observed_built_at,
            recorded_build_path=parsed.observed_build_path,
        )
        for parsed in catalog.entries
    )
    ids = [entry.dataset_id for entry in entries]
    if ids != sorted(ids):
        _fail("catalog.json datasets must be sorted by dataset_id ascending")
    if len(set(ids)) != len(ids):
        _fail("catalog.json datasets must not contain duplicate dataset_id")

    # 20-22. Recompute the PR-5 Catalog content identity over the facts
    # (never trusting the recorded value) and compare with the top-level
    # and the manifest; cross-check the dataset counts.
    recomputed_content_id = _dataset_catalog_content_id_from_facts(
        {entry.dataset_id: entry.dataset_facts for entry in entries}
    )
    if recomputed_content_id != catalog.catalog_content_id:
        _fail(
            "catalog.json catalog_content_id does not match the recomputed "
            "PR-5 Catalog content identity of the datasets"
        )
    if recomputed_content_id != manifest.catalog_content_id:
        _fail(
            "manifest.json catalog_content_id does not match the recomputed "
            "PR-5 Catalog content identity of the datasets"
        )
    if catalog.dataset_count != len(entries):
        _fail(
            f"catalog.json dataset_count {catalog.dataset_count} does not "
            f"match the {len(entries)} dataset record(s)"
        )
    if manifest.dataset_count != len(entries):
        _fail(
            f"manifest.json dataset_count {manifest.dataset_count} does not "
            f"match the {len(entries)} dataset record(s)"
        )

    # 23-24. Recompute the physical snapshot ID from the manifest facts
    # and the actual catalog byte facts, and compare with the manifest.
    recomputed_snapshot_id = dataset_catalog_snapshot_id(
        catalog_content_id=recomputed_content_id,
        dataset_count=len(entries),
        built_at=manifest.built_at,
        catalog_file_byte_size=len(catalog_bytes),
        catalog_file_sha256=_file_sha256(catalog_path),
    )
    if recomputed_snapshot_id != manifest.snapshot_id:
        _fail(
            "manifest.json snapshot_id does not match the recomputed "
            "physical snapshot identity"
        )

    # 25. Second pass: path contract, whitelist, _SUCCESS, manifest bytes,
    # and catalog bytes / hash re-verified (a concurrent modification
    # fails closed; no mixed-instant partial result is ever returned).
    _second_pass_verify(snapshot, manifest_bytes, catalog_bytes, catalog_path)

    # 26. Construct the VerifiedDatasetCatalogSnapshot; construction
    # re-verifies every invariant (fail closed) and only then is the
    # result returned.
    return VerifiedDatasetCatalogSnapshot(
        reader_contract_version=DATASET_CATALOG_READER_CONTRACT_VERSION,
        snapshot_schema_version=catalog.snapshot_schema_version,
        catalog_contract_version=catalog.catalog_contract_version,
        catalog_entry_schema_version=catalog.catalog_entry_schema_version,
        catalog_content_id_version=catalog.catalog_content_id_version,
        builder_version=catalog.builder_version,
        snapshot_id=manifest.snapshot_id,
        catalog_content_id=recomputed_content_id,
        dataset_count=len(entries),
        built_at=manifest.built_at,
        snapshot_dir=snapshot,
        manifest=DatasetCatalogSnapshotManifestRecord(
            manifest_schema_version=manifest.manifest_schema_version,
            snapshot_id_version=manifest.snapshot_id_version,
            materializer_version=manifest.materializer_version,
            builder_version=manifest.builder_version,
            snapshot_id=manifest.snapshot_id,
            catalog_content_id=manifest.catalog_content_id,
            built_at=manifest.built_at,
            dataset_count=manifest.dataset_count,
            catalog_file=DatasetCatalogFileRecord(
                relative_path=manifest.catalog_relative_path,
                byte_size=manifest.catalog_byte_size,
                sha256=manifest.catalog_sha256,
            ),
        ),
        entries=entries,
    )


def _second_pass_verify(
    snapshot: Path,
    manifest_bytes: bytes,
    catalog_bytes: bytes,
    catalog_path: Path,
) -> None:
    """Final re-verification before the result is constructed: the path
    contract, the exact whitelist, ``_SUCCESS``, the manifest re-read
    (byte equality with the initially read payload), and the catalog
    bytes re-read with its size / hash re-verified. A concurrent
    modification fails closed; no mixed-instant partial result is ever
    returned."""
    _verify_snapshot_dir_safety(snapshot)
    _verify_entries(snapshot)
    _verify_success(snapshot / DATASET_CATALOG_SUCCESS_FILENAME)
    current_manifest = _read_artifact_bytes(
        snapshot / DATASET_CATALOG_MANIFEST_FILENAME, "manifest.json"
    )
    if current_manifest != manifest_bytes:
        _fail(
            "manifest.json changed between the first and the final "
            "verification pass (the raw bytes no longer match the "
            "initially verified payload)"
        )
    current_catalog = _read_artifact_bytes(catalog_path, "catalog.json")
    if current_catalog != catalog_bytes:
        _fail(
            "catalog.json changed between the first and the final "
            "verification pass (the raw bytes no longer match the "
            "initially verified payload)"
        )
    # Byte equality with the first-pass bytes subsumes the size / hash
    # re-verification: the first pass already bound those bytes to the
    # manifest catalog_file record.
