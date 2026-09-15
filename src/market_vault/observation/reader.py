"""Sole read-only trust entry point for immutable Observation artifacts."""

from dataclasses import fields
import hashlib
import os
from pathlib import Path
import stat
from types import MappingProxyType

import pyarrow as pa
import pyarrow.parquet as pq

from ._artifact_validation import validate_inputs
from ._validation import ObservationError
from .artifact_models import ObservationArtifactError, VerifiedObservationBuild
from .artifact_schema import JSON_COLUMNS, TIME_COLUMNS, OBSERVATION_ARROW_SCHEMA, OBSERVATION_PARQUET_PATH
from .identity import observation_build_id, observation_source_snapshot_id
from .manifest import (
    canonical_json, coverage_from_payload, make_manifest, payload, read_json,
    record, row_from_payload, snapshot_from_payload, timestamp,
)
from .models import ObservationBuildIdentityInput, ObservationContractPin


def _absolute_path(value) -> Path:
    if not isinstance(value, (str, Path)):
        raise ObservationArtifactError("an explicit absolute artifact path is required")
    raw = str(value)
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ObservationArtifactError("artifact path must be absolute without traversal")
    # Reject ADS and ambiguous Win32 aliases; do not normalize them into authority.
    for part in path.parts[1:]:
        if ":" in part or part.endswith((".", " ")) or "\x00" in part:
            raise ObservationArtifactError("unsafe artifact path component")
    if "\x00" in raw:
        raise ObservationArtifactError("unsafe artifact path")
    return path


def _safe_path(path: Path, *, directory: bool, allow_missing: bool = False):
    parts = list(reversed(path.parents)) + [path]
    for component in parts:
        try:
            info = component.lstat()
        except FileNotFoundError:
            if allow_missing:
                return None
            raise ObservationArtifactError(f"missing artifact path: {component}")
        if os.name == "nt" and not hasattr(info, "st_file_attributes"):
            raise ObservationArtifactError("Windows reparse status cannot be established")
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ObservationArtifactError("artifact path contains a symlink, junction or reparse point")
        is_dir = directory if component == path else True
        if not (stat.S_ISDIR(info.st_mode) if is_dir else stat.S_ISREG(info.st_mode)):
            raise ObservationArtifactError("unverifiable or unexpected artifact path type")
        if not is_dir and info.st_nlink != 1:
            raise ObservationArtifactError("artifact file must not be hard-linked")
    return info


def _identity(info):
    if info is None or not info.st_ino:
        raise ObservationArtifactError("filesystem object identity cannot be established")
    # Windows creation time is stable as children change, and detects inode reuse.
    birth = getattr(info, "st_birthtime_ns", info.st_ctime_ns if os.name == "nt" else None)
    return info.st_dev, info.st_ino, birth


def _read_bytes(path):
    before = _safe_path(path, directory=False)
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if _identity(opened) != _identity(before):
            raise ObservationArtifactError("artifact path changed while opening")
        data = stream.read()
        after = os.fstat(stream.fileno())
    last = _safe_path(path, directory=False)
    if (_identity(last) != _identity(before) or
            (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or
            (last.st_size, last.st_mtime_ns) != (after.st_size, after.st_mtime_ns)):
        raise ObservationArtifactError("artifact changed during verification")
    return data


def _inventory(root):
    root_device = _safe_path(root, directory=True).st_dev
    result = set()
    def visit(directory):
        _safe_path(directory, directory=True)
        for child in directory.iterdir():
            info = child.lstat()
            if info.st_dev != root_device:
                raise ObservationArtifactError("cross-filesystem artifact member")
            is_dir = stat.S_ISDIR(info.st_mode)
            _safe_path(child, directory=is_dir)
            result.add(child.relative_to(root).as_posix())
            if is_dir:
                visit(child)
    visit(root)
    return result


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _verify_directory(root, *, require_success, final_name):
    root = _absolute_path(root)
    root_identity = _identity(_safe_path(root, directory=True))
    expected = {"observations", OBSERVATION_PARQUET_PATH, "manifest.json"}
    if require_success:
        expected.add("_SUCCESS")
    if _inventory(root) != expected:
        raise ObservationArtifactError("artifact inventory mismatch: missing or unlisted file")
    raw_manifest = _read_bytes(root / "manifest.json")
    manifest = read_json(raw_manifest)
    parquet = _read_bytes(root / OBSERVATION_PARQUET_PATH)
    table = pq.read_table(pa.BufferReader(parquet))
    if not table.schema.equals(OBSERVATION_ARROW_SCHEMA, check_metadata=True):
        raise ObservationArtifactError("Observation Arrow schema/nullability mismatch")
    rows = []
    for physical in table.to_pylist():
        for field in OBSERVATION_ARROW_SCHEMA:
            if not field.nullable and physical[field.name] is None:
                raise ObservationArtifactError("null in non-null Observation field")
        for name in JSON_COLUMNS:
            physical[name] = read_json(physical[name].encode("utf-8"))
        for name in TIME_COLUMNS:
            physical[name] = payload(physical[name])
        rows.append(row_from_payload(physical))
    keys = [(r.observation_key, r.observation_version_id) for r in rows]
    if keys != sorted(set(keys)):
        raise ObservationArtifactError("duplicate or unordered physical Observation rows")
    snapshots = tuple(snapshot_from_payload(s["snapshot"]) for s in manifest["source_snapshots"])
    build = ObservationBuildIdentityInput(
        rows=tuple(rows), source_snapshot_ids=tuple(observation_source_snapshot_id(s) for s in snapshots),
        authority_evidence_ids=manifest["authority_evidence_ids"],
        provider_contracts=tuple(record(ObservationContractPin, p) for p in manifest["provider_contracts"]),
        normalizations=tuple(record(ObservationContractPin, p) for p in manifest["normalizations"]),
        coverage=coverage_from_payload(manifest["coverage"]),
        schema_version=manifest["observation_schema_version"],
    )
    build, snapshots, created_at = validate_inputs(build, snapshots, timestamp(manifest["created_at"]))
    expected_manifest = make_manifest(build, snapshots, created_at, byte_size=len(parquet),
                                      sha256=hashlib.sha256(parquet).hexdigest())
    if canonical_json(expected_manifest) != raw_manifest:
        raise ObservationArtifactError("manifest claims, physical facts or identity mismatch")
    if final_name and root.name != "build_id=" + observation_build_id(build):
        raise ObservationArtifactError("build directory name does not match identity")
    if require_success and _read_bytes(root / "_SUCCESS") != b"":
        raise ObservationArtifactError("_SUCCESS must be an empty regular commit marker")
    if _identity(_safe_path(root, directory=True)) != root_identity or _inventory(root) != expected:
        raise ObservationArtifactError("artifact directory changed during verification")
    # Semantic verification must close over the same physical bytes, not just names.
    if _read_bytes(root / "manifest.json") != raw_manifest:
        raise ObservationArtifactError("manifest.json changed during verification")
    if _read_bytes(root / OBSERVATION_PARQUET_PATH) != parquet:
        raise ObservationArtifactError("Observation Parquet changed during verification")
    if require_success and _read_bytes(root / "_SUCCESS") != b"":
        raise ObservationArtifactError("_SUCCESS must be an empty regular commit marker")
    if _identity(_safe_path(root, directory=True)) != root_identity or _inventory(root) != expected:
        raise ObservationArtifactError("artifact directory changed during verification")
    return build, snapshots, created_at, expected_manifest


def load_verified_observation_build(build_dir) -> VerifiedObservationBuild:
    """Verify an exact local directory; no discovery, repair, or trust bypass."""
    try:
        build, snapshots, created_at, manifest = _verify_directory(
            build_dir, require_success=True, final_name=True)
        result = object.__new__(VerifiedObservationBuild)
        values = dict(observation_build_id=manifest["observation_build_id"],
                      observation_content_id=manifest["observation_content_id"],
                      status=manifest["status"], rows=build.rows, source_snapshots=snapshots,
                      authority_evidence_ids=build.authority_evidence_ids,
                      provider_contracts=build.provider_contracts, normalizations=build.normalizations,
                      coverage=build.coverage, created_at=created_at,
                      manifest_payload=_freeze(manifest), build_dir=_absolute_path(build_dir))
        for field in fields(result):
            object.__setattr__(result, field.name, values[field.name])
        return result
    except ObservationArtifactError:
        raise
    except (ObservationError, OSError, ValueError, TypeError, KeyError, AttributeError,
            OverflowError, UnicodeError, pa.ArrowException) as exc:
        raise ObservationArtifactError(f"invalid Observation artifact: {exc}") from exc
