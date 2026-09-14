"""Immutable publication under observation_artifact_atomic_publication_v1.

Only the two exactly bound helpers mutate existing directory state. All other
artifact writes use exclusive creation within invocation-owned private staging.
"""

import ctypes
from dataclasses import dataclass
from datetime import datetime
import errno
import hashlib
import os
from pathlib import Path
import shutil
import sys
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq

from ._artifact_validation import validate_inputs
from ._validation import ObservationError
from .artifact_models import ObservationMaterializationError, ObservationMaterializationResult
from .artifact_schema import JSON_COLUMNS, TIME_COLUMNS, OBSERVATION_ARROW_SCHEMA, OBSERVATION_PARQUET_PATH
from .identity import observation_build_id
from .manifest import canonical_json, make_manifest, payload
from .models import ObservationBuildIdentityInput, ObservationSourceSnapshotInput
from .reader import (
    _absolute_path, _identity, _inventory, _safe_path, _verify_directory,
    load_verified_observation_build,
)


class _DestinationExistsError(ObservationMaterializationError):
    pass


class _NoReplaceUnsupportedError(ObservationMaterializationError):
    pass


@dataclass(slots=True)
class _StagingOwnership:
    path: Path
    path_identity: tuple
    output_root: Path
    root_identity: tuple
    final: Path
    build_id: str
    committed: bool = False
    removed: bool = False


def _check_owner(owner):
    if type(owner) is not _StagingOwnership or owner.committed or owner.removed:
        raise ObservationMaterializationError("no uncommitted staging ownership")
    if (owner.path.parent != owner.output_root or owner.final.parent != owner.output_root
            or owner.final.name != "build_id=" + owner.build_id
            or not owner.path.name.startswith("." + owner.build_id + ".tmp-")):
        raise ObservationMaterializationError("staging ownership scope mismatch")
    root = _safe_path(owner.output_root, directory=True)
    staging = _safe_path(owner.path, directory=True)
    if (_identity(root) != owner.root_identity or _identity(staging) != owner.path_identity
            or root.st_dev != staging.st_dev):
        raise ObservationMaterializationError("staging/root identity changed or cross-filesystem staging")
    _inventory(owner.path)


def _remove_tree(owner):
    """Remove only the still-owned, safe, uncommitted staging object."""
    _check_owner(owner)
    shutil.rmtree(owner.path)
    owner.removed = True


def _rename_directory_no_replace_windows(staging, final):
    if os.name != "nt":
        raise _NoReplaceUnsupportedError("Windows no-replace primitive used on another platform")
    try:
        os.rename(staging, final)
    except OSError as exc:
        if isinstance(exc, FileExistsError) or getattr(exc, "winerror", None) in (80, 183):
            raise _DestinationExistsError("final destination already exists") from exc
        raise


def _rename_directory_no_replace_linux(staging, final):
    try:
        renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
    except (OSError, AttributeError) as exc:
        raise _NoReplaceUnsupportedError("safe no-replace publication unsupported: missing renameat2") from exc
    renameat2.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    renameat2.restype = ctypes.c_int
    ctypes.set_errno(0)
    if renameat2(-100, os.fsencode(staging), -100, os.fsencode(final), 1) == 0:
        return
    error = ctypes.get_errno()
    if error in (errno.EEXIST, errno.ENOTEMPTY):
        raise _DestinationExistsError("final destination already exists")
    if error in (errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP):
        raise _NoReplaceUnsupportedError(f"safe no-replace publication unsupported: errno {error}")
    raise ObservationMaterializationError(f"atomic no-replace publication failed: errno {error}")


def _publish(owner):
    _check_owner(owner)
    _safe_path(owner.final, directory=True, allow_missing=True)
    if os.name == "nt":
        _rename_directory_no_replace_windows(owner.path, owner.final)
    elif os.name == "posix" and sys.platform.startswith("linux"):
        _rename_directory_no_replace_linux(owner.path, owner.final)
    else:
        raise _NoReplaceUnsupportedError("safe no-replace publication unsupported on this platform")
    owner.committed = True


def _create_root(root):
    for component in list(reversed(root.parents)) + [root]:
        if _safe_path(component, directory=True, allow_missing=True) is None:
            try:
                component.mkdir()
            except FileExistsError:
                pass
        _safe_path(component, directory=True)


def _write_bytes(owner, relative_path, data):
    _check_owner(owner)
    path = owner.path / relative_path
    if relative_path not in {OBSERVATION_PARQUET_PATH, "manifest.json", "_SUCCESS"}:
        raise ObservationMaterializationError("unapproved staging member")
    _safe_path(path.parent, directory=True)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _parquet_bytes(rows):
    physical = []
    for row in rows:
        value = payload(row)
        for name in JSON_COLUMNS:
            value[name] = canonical_json(value[name]).decode("utf-8")
        for name in TIME_COLUMNS:
            value[name] = getattr(row, name)
        physical.append(value)
    sink = pa.BufferOutputStream()
    pq.write_table(pa.Table.from_pylist(physical, schema=OBSERVATION_ARROW_SCHEMA), sink,
                   compression="snappy", version="2.6")
    return sink.getvalue().to_pybytes()


def _existing(final, build_id):
    verified = load_verified_observation_build(final)
    if verified.observation_build_id != build_id:
        raise ObservationMaterializationError("existing final build identity mismatch")
    return ObservationMaterializationResult(verified, created_new_build=False)


def materialize_observation_build(
    build: ObservationBuildIdentityInput,
    source_snapshots: tuple[ObservationSourceSnapshotInput, ...],
    *,
    output_root: str | Path,
    created_at: datetime,
) -> ObservationMaterializationResult:
    """Create or strictly verify one build; no implicit root, clock or acquisition."""
    owner = None
    try:
        build, snapshots, created_at = validate_inputs(build, source_snapshots, created_at)
        build_id = observation_build_id(build)
        root = _absolute_path(output_root)
        _create_root(root)
        final = root / ("build_id=" + build_id)
        if _safe_path(final, directory=True, allow_missing=True) is not None:
            return _existing(final, build_id)
        staging = root / ("." + build_id + ".tmp-" + uuid4().hex)
        root_identity = _identity(_safe_path(root, directory=True))
        # Ownership is acquired only AFTER exclusive creation. A collision is never cleaned.
        staging.mkdir()
        owner = _StagingOwnership(staging, _identity(_safe_path(staging, directory=True)),
                                  root, root_identity, final, build_id)
        _check_owner(owner)
        (staging / "observations").mkdir()
        parquet = _parquet_bytes(build.rows)
        _write_bytes(owner, OBSERVATION_PARQUET_PATH, parquet)
        manifest = make_manifest(build, snapshots, created_at, byte_size=len(parquet),
                                 sha256=hashlib.sha256(parquet).hexdigest())
        _write_bytes(owner, "manifest.json", canonical_json(manifest))
        _verify_directory(staging, require_success=False, final_name=False)
        _write_bytes(owner, "_SUCCESS", b"")
        _verify_directory(staging, require_success=True, final_name=False)
        try:
            _publish(owner)
        except _DestinationExistsError:
            result = _existing(final, build_id)
            _remove_tree(owner)
            return result
        return ObservationMaterializationResult(load_verified_observation_build(final), True)
    except (ObservationError, OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        if owner is not None and not owner.committed and not owner.removed:
            try:
                _remove_tree(owner)
            except (ObservationError, OSError) as cleanup_error:
                raise ObservationMaterializationError(
                    f"materialization failed; staging cleanup refused/failed: {cleanup_error}"
                ) from exc
        if isinstance(exc, ObservationMaterializationError):
            raise
        raise ObservationMaterializationError(f"Observation materialization failed: {exc}") from exc
