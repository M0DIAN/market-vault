"""Deterministic Dataset Catalog builder (v0.6.0 PR-6).

``build_dataset_catalog`` builds the deterministic logical Catalog from
verified Datasets only, in exactly one of two explicit modes:

- ``dataset_root`` mode: an explicit bounded discovery root whose direct
  children named exactly ``[0-9a-f]{64}`` are candidates. Only the direct
  children are enumerated (never recursively, never via a recursive
  glob, never the parent directory, never other disks). Non-candidate children —
  ordinary files, ordinary directories, ``.staging-*``, documentation,
  any other name — are ignored but never entered or followed. A 64-hex
  named child that is a symlink, junction, reparse point, ordinary file,
  or special file fails closed, as does a ``dataset_root`` (or any
  existing parent component) that is itself a link.
- ``candidate_build_dirs`` mode: an explicit iterable of build
  directories, frozen at the boundary; input order never matters and an
  exactly identical lexical path listed twice is processed once.

Every candidate (in either mode) must pass the formal
``load_verified_dataset``; only after it returns a
:class:`VerifiedDatasetBuild` is ``project_dataset_catalog_entry``
called. The builder never parses a manifest itself, never trusts
``manifest.json``, never reads Dataset Parquet, and never repairs an
invalid Dataset. Two different physical paths that yield the same
``dataset_id`` fail closed as an ambiguous duplicate Dataset location
(observed locations must be unique in one Catalog snapshot); the same
``dataset_id`` with different content facts fails closed the same way.
First-wins, last-wins, shortest-path-wins, and lexicographical-path-wins
are never used.

The builder is deterministic and side-effect free: the same set of
verified Datasets always produces the same entry order, the same Catalog
content ID, and the same logical payload, regardless of candidate order,
root enumeration order, cwd, machine, or invocation time. It never reads
the current time, never accesses the network / OpenD / settings, and
never writes files.

All failures raise :class:`DatasetCatalogBuildError`; documented
underlying failures are converted with their ``__cause__`` preserved and
programming errors are never hidden.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .dataset_catalog_builder_models import (
    DATASET_CATALOG_BUILDER_VERSION,
    DatasetCatalogBuildError,
    DatasetCatalogBuildResult,
)
from .dataset_catalog_identity import dataset_catalog_content_id
from .dataset_catalog_projection import project_dataset_catalog_entry
from .encoding import DatasetError
from .materialization import _is_junction_or_reparse
from .reader import load_verified_dataset

__all__ = ["build_dataset_catalog"]

_CANDIDATE_NAME_RE = re.compile(r"^[0-9a-f]{64}$")

_DOCUMENTED_ERRORS = (
    DatasetError,
    OSError,
    UnicodeError,
    TypeError,
    ValueError,
    KeyError,
)


def _as_build_error(exc, context: str) -> None:
    """Convert a documented builder failure to
    :class:`DatasetCatalogBuildError` with the ``__cause__`` preserved;
    an already-raised error passes through unchanged (never
    double-wrapped); programming errors are never hidden."""
    if isinstance(exc, DatasetCatalogBuildError):
        raise exc
    if isinstance(exc, _DOCUMENTED_ERRORS):
        raise DatasetCatalogBuildError(f"{context}: {exc}") from exc
    raise exc


def build_dataset_catalog(
    *,
    dataset_root=None,
    candidate_build_dirs=None,
) -> DatasetCatalogBuildResult:
    """Build the deterministic logical Catalog from verified Datasets.

    Exactly one of ``dataset_root`` or ``candidate_build_dirs`` must be
    provided (both / neither fail closed). ``dataset_root`` is the
    explicit bounded discovery root (direct 64-hex children only);
    ``candidate_build_dirs`` is the explicit candidate set
    (``()`` produces a legal empty Catalog). cwd, settings, a latest
    pointer, a default Dataset root, and environment variables are never
    implicit inputs.

    Every candidate must pass ``load_verified_dataset`` and is projected
    through ``project_dataset_catalog_entry``; the result entries are
    sorted by ``dataset_id`` and the PR-5 Catalog content identity is
    recomputed over the entries.
    """
    try:
        return _build_dataset_catalog(
            dataset_root=dataset_root,
            candidate_build_dirs=candidate_build_dirs,
        )
    except DatasetCatalogBuildError:
        raise
    except _DOCUMENTED_ERRORS as exc:
        _as_build_error(exc, "build_dataset_catalog failed")


def _coerce_root(dataset_root, label: str) -> Path:
    """Lexically absolute Path of an explicit input; raw ``.`` / ``..``
    components are rejected before any normalization and ``resolve()`` is
    never used to mask a link."""
    try:
        raw_text = os.fspath(dataset_root)
    except TypeError as exc:
        raise DatasetCatalogBuildError(
            f"{label} must be a path-like, got {type(dataset_root).__name__}"
        ) from exc
    for part in raw_text.replace("\\", "/").split("/"):
        if part in (".", ".."):
            raise DatasetCatalogBuildError(
                f"{label} must not contain '.' or '..' path components: "
                f"{dataset_root!r}"
            )
    try:
        raw = Path(dataset_root)
    except TypeError as exc:
        raise DatasetCatalogBuildError(
            f"{label} must be a path-like, got {type(dataset_root).__name__}"
        ) from exc
    if not isinstance(raw, Path):
        raise DatasetCatalogBuildError(
            f"{label} must be a path-like, got {type(dataset_root).__name__}"
        )
    if raw.is_absolute():
        return raw
    try:
        return Path.cwd() / raw
    except OSError as exc:
        raise DatasetCatalogBuildError(
            f"cannot resolve the current working directory for a relative "
            f"{label}: {exc}"
        ) from exc


def _reject_symlink(path: Path, label: str) -> None:
    if path.is_symlink() or _is_junction_or_reparse(path):
        raise DatasetCatalogBuildError(
            f"{label} must not be a symlink or junction: {path}"
        )


def _verify_root_safety(dataset_root: Path) -> None:
    """``dataset_root`` and every existing parent component must be a
    real, regular directory (no symlink, junction, reparse point, file,
    FIFO, or special type); a component whose link status cannot be
    verified fails closed. ``resolve()`` is never used to mask a link."""
    for component in (dataset_root, *dataset_root.parents):
        _reject_symlink(component, "dataset_root or path component")
        if component.exists() and not component.is_dir():
            raise DatasetCatalogBuildError(
                f"dataset_root or path component must be a regular "
                f"directory: {component}"
            )
    if not dataset_root.exists():
        raise DatasetCatalogBuildError(
            f"dataset_root does not exist: {dataset_root}"
        )
    if not dataset_root.is_dir():
        raise DatasetCatalogBuildError(
            f"dataset_root must be a regular directory: {dataset_root}"
        )
    _reject_symlink(dataset_root, "dataset_root")


def _verify_candidate_safety(candidate: Path) -> None:
    """One discovered candidate directory: a real regular non-link
    directory whose name is exactly the lowercase 64-hex dataset ID."""
    _reject_symlink(candidate, "catalog candidate")
    if not candidate.exists():
        raise DatasetCatalogBuildError(
            f"catalog candidate does not exist: {candidate}"
        )
    if not candidate.is_dir():
        raise DatasetCatalogBuildError(
            f"catalog candidate must be a regular directory: {candidate}"
        )


def _discover_root_candidates(dataset_root: Path) -> tuple[Path, ...]:
    """Bounded direct-child enumeration of ``dataset_root``.

    Only the direct children are enumerated with a single ``os.scandir``
    (never recursively, never via a recursive glob, never the parent). A child whose
    name strictly matches the 64-hex candidate pattern must be a real
    regular non-link directory and becomes a candidate; every other child
    (ordinary files, ordinary directories, ``.staging-*``, documentation,
    any other name) is ignored but never entered or followed, and a
    linked / special 64-hex named child fails closed. Children are
    processed in sorted name order so the enumeration order never affects
    the result.
    """
    try:
        with os.scandir(dataset_root) as iterator:
            items = sorted(iterator, key=lambda item: item.name)
    except OSError as exc:
        raise DatasetCatalogBuildError(
            f"failed to enumerate dataset_root {dataset_root}: {exc}"
        ) from exc
    candidates: list[Path] = []
    for item in items:
        if not _CANDIDATE_NAME_RE.fullmatch(item.name):
            continue  # non-candidate: ignored, never entered or followed
        path = Path(item.path)
        _verify_candidate_safety(path)
        candidates.append(path)
    return tuple(candidates)


def _coerce_candidate_build_dirs(candidate_build_dirs) -> tuple[Path, ...]:
    """Explicit candidate set frozen at the boundary: every candidate
    must be a lexically absolute safe path; an exactly identical lexical
    path listed twice is processed once (deduplicated before any
    access)."""
    try:
        items = tuple(candidate_build_dirs)
    except TypeError as exc:
        raise DatasetCatalogBuildError(
            "candidate_build_dirs must be an iterable of path-like values, "
            f"got {type(candidate_build_dirs).__name__}"
        ) from exc
    paths: list[Path] = []
    seen: set[str] = set()
    for item in items:
        path = _coerce_root(item, "candidate build dir")
        if str(path) in seen:
            continue
        seen.add(str(path))
        paths.append(path)
    return tuple(paths)


def _verify_candidate_build_dir(candidate: Path) -> None:
    """One explicit candidate build directory: a real regular non-link
    directory with a 64-hex name (the verified Dataset reader enforces
    the directory-name / dataset_id binding itself)."""
    _reject_symlink(candidate, "catalog candidate")
    if not candidate.exists():
        raise DatasetCatalogBuildError(
            f"catalog candidate does not exist: {candidate}"
        )
    if not candidate.is_dir():
        raise DatasetCatalogBuildError(
            f"catalog candidate must be a regular directory: {candidate}"
        )


def _build_dataset_catalog(
    *,
    dataset_root=None,
    candidate_build_dirs=None,
) -> DatasetCatalogBuildResult:
    # 1. Exactly one explicit mode; cwd / settings / latest / default
    #    roots / environment variables are never implicit.
    if (dataset_root is None) == (candidate_build_dirs is None):
        raise DatasetCatalogBuildError(
            "exactly one of dataset_root or candidate_build_dirs must be "
            "provided"
        )

    # 2. Root mode: bounded direct-child discovery.
    if dataset_root is not None:
        root = _coerce_root(dataset_root, "dataset_root")
        _verify_root_safety(root)
        candidates = _discover_root_candidates(root)
    else:
        candidates = _coerce_candidate_build_dirs(candidate_build_dirs)

    # 3. Every candidate: formal verified reader, then projection. The
    #    builder never parses manifests, never trusts manifest.json,
    #    never reads Dataset Parquet, and never repairs an invalid
    #    Dataset.
    entries = []
    observed_locations: dict[str, str] = {}
    for candidate in candidates:
        if dataset_root is not None:
            _verify_candidate_safety(candidate)
        else:
            _verify_candidate_build_dir(candidate)
        verified = load_verified_dataset(candidate)
        dataset_id = verified.dataset_id
        prior = observed_locations.get(dataset_id)
        if prior is not None and prior != str(candidate):
            raise DatasetCatalogBuildError(
                "ambiguous duplicate Dataset location: dataset_id "
                f"{dataset_id!r} was observed at both {prior} and "
                f"{candidate}; a Catalog snapshot records exactly one "
                "observed location per Dataset"
            )
        observed_locations[dataset_id] = str(candidate)
        entries.append(project_dataset_catalog_entry(verified))

    # 4. Deterministic normalization: entries sorted by dataset_id; the
    #    PR-5 Catalog content identity over the normalized set.
    ordered = tuple(sorted(entries, key=lambda entry: entry.dataset_facts.dataset_id))
    return DatasetCatalogBuildResult(
        entries=ordered,
        catalog_content_id=dataset_catalog_content_id(ordered),
        dataset_count=len(ordered),
        builder_version=DATASET_CATALOG_BUILDER_VERSION,
    )
