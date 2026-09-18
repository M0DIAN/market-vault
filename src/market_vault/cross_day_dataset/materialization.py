"""Invocation-owned sealed no-replace Cross-Day artifact publication."""

import ctypes
from dataclasses import dataclass
from datetime import datetime
import errno
from hashlib import sha256
import os
from pathlib import Path
import shutil
import sys
from threading import RLock

from ..dataset.encoding import DatasetError
from . import execution
from .models import MultiSourceCrossDayDatasetResult
from ._artifact_io import _NativeScope, _PhysicalCapture, _inventory, _exists
from ._artifact_paths import _output_root, _expected_inventory, _relative_member
from ._artifact_platform import _require_qualified
from ._artifact_projection import _prepare_artifact_facts, _content_bytes
from ._artifact_encoding import timestamp_text, decode_json
from ._artifact_windows import _new_directory, _new_file_handle, _write_handle
from .artifact_models import (
    MultiSourceCrossDayArtifactError, MultiSourceCrossDayDatasetMaterializationResult, _require,
)
from .manifest import _manifest_bytes
from .reader import _verify_capture, load_verified_multi_source_cross_day_dataset


RENAME_NOREPLACE = 1


class _DestinationExists(Exception):
    pass


@dataclass(frozen=True, slots=True, init=False)
class _PublicationSeal:
    dataset_id: str
    binding: tuple
    inventory: tuple
    file_facts: tuple
    manifest_bytes: bytes

    def __init__(self, *args, **kwargs):
        raise TypeError("only complete private staging verification issues a seal")


@dataclass(slots=True, eq=False)
class _Owner:
    scope: object
    path: Path
    final: Path
    dataset_id: str
    expected: tuple
    members: dict
    process_id: int
    state: str = "PRIVATE_STAGING"
    seal: object = None
    seal_snapshot: tuple = ()
    cleanup_attempted: bool = False


def _binding(owner):
    return (owner.scope.root, owner.path, owner.final, owner.dataset_id, owner.scope.filesystem,
            tuple((v.path, v.identity, v.security) for v in owner.scope.handles),
            tuple((name, item.identity, item.filesystem, item.security) for name, item in sorted(owner.members.items())))


def _check_owner(owner):
    _require_owner(owner)
    _require(owner.state in ("PRIVATE_STAGING", "SEALED", "FAILED_PRECOMMIT"), "OWNERSHIP_UNPROVEN", "staging cleanup revoked")
    owner.scope.recheck()
    _require("" in owner.members, "OWNERSHIP_UNPROVEN", "exclusive staging creation unrecorded")
    owner.members[""].recheck()
    inventory = _inventory(owner.path, owner.scope)
    _require(set(inventory) <= set(_expected_inventory(owner.expected)), "OWNERSHIP_UNPROVEN", "unexpected cleanup child")
    for name, kind in inventory:
        item = owner.members.get(name)
        _require(item is not None and item.directory == (kind == "DIRECTORY"), "OWNERSHIP_UNPROVEN", "unowned extant member")
        item.recheck()
    return inventory


def _remove_tree(owner):
    _check_owner(owner)
    _require(not owner.cleanup_attempted, "CLEANUP_REFUSED", "cleanup is not retried")
    owner.cleanup_attempted = True
    try:
        shutil.rmtree(owner.path)
    except OSError as exc:
        raise MultiSourceCrossDayArtifactError("CLEANUP_REFUSED", "FAILED_PRECOMMIT", exc) from exc
    owner.state = "FAILED_PRECOMMIT"


def _rename_directory_no_replace_windows(staging, final):
    _require(os.name == "nt", "PLATFORM_UNQUALIFIED", "Windows primitive unavailable")
    try:
        os.rename(staging, final)
    except FileExistsError as exc:
        raise _DestinationExists() from exc


def _rename_directory_no_replace_linux(root_fd, staging_name, final_name):
    _require(sys.platform == "linux", "PLATFORM_UNQUALIFIED", "Linux primitive unavailable")
    _require(type(root_fd) is int and type(staging_name) is bytes and type(final_name) is bytes
             and all(b"/" not in n and b"\0" not in n for n in (staging_name, final_name)),
             "UNSAFE_PATH", "root-fd-relative single names required")
    try:
        renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
    except (OSError, AttributeError) as exc:
        raise MultiSourceCrossDayArtifactError("PLATFORM_UNQUALIFIED", "SEALED", exc) from exc
    renameat2.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    renameat2.restype = ctypes.c_int
    if renameat2(root_fd, staging_name, root_fd, final_name, RENAME_NOREPLACE) == 0:
        return
    error = ctypes.get_errno()
    if error in (errno.EEXIST, errno.ENOTEMPTY):
        raise _DestinationExists()
    code = "FILESYSTEM_MISMATCH" if error == errno.EXDEV else "PLATFORM_UNQUALIFIED" if error in (
        errno.ENOSYS, errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP) else "PUBLICATION_FAILED"
    raise MultiSourceCrossDayArtifactError(code, "SEALED", OSError(error, os.strerror(error)))


def _write_member(owner, name, data):
    _check_owner(owner)
    _require(name in owner.expected and type(data) is bytes, "OWNERSHIP_UNPROVEN", "unapproved write member")
    path = owner.path / _relative_member(name)
    for parent in reversed(path.parents):
        if parent == owner.path or owner.path not in parent.parents:
            continue
        relative = parent.relative_to(owner.path).as_posix()
        if relative not in owner.members:
            _check_owner(owner)
            if os.name == "nt":
                _new_directory(parent, owner.scope.current_sid)
            else:
                os.mkdir(parent, 0o700)
            owner.members[relative] = owner.scope.member(parent, directory=True)
    _check_owner(owner)
    if os.name == "nt":
        from ._artifact_windows import _close
        handle = _new_file_handle(path, owner.scope.current_sid)
        try:
            owner.members[name] = owner.scope.member(path, directory=False)
            _check_owner(owner)
            _write_handle(handle, data)
        finally:
            _close(handle)
    else:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            owner.members[name] = owner.scope.member(path, directory=False)
            _check_owner(owner)
            offset = 0
            while offset < len(data):
                count = os.write(fd, data[offset:offset + 65536])
                _require(count > 0, "PUBLICATION_FAILED", "zero write")
                offset += count
            os.fsync(fd)
        finally:
            os.close(fd)


def _seal_values(seal):
    return seal.dataset_id, seal.binding, seal.inventory, seal.file_facts, seal.manifest_bytes


def _verify_and_seal_staging(owner):
    _check_owner(owner)
    with _PhysicalCapture(owner.scope, owner.path, require_success=True) as capture:
        _, payload = _verify_capture(capture)
        _require(payload["dataset_id"] == owner.dataset_id and capture.inventory == _expected_inventory(owner.expected),
                 "SEAL_AUTHORITY", "staging owner/manifest/inventory differs")
        capture.recheck()
        roles = {r["relative_path"]: r["file_role"] for r in payload["output_files"]}
        roles.update({"manifest.json": "MANIFEST", "_SUCCESS": "SUCCESS"})
        facts = tuple((name, roles[name], item.identity, len(capture.data[name]), sha256(capture.data[name]).hexdigest())
                      for name, item in capture.objects if name in capture.data)
        seal = object.__new__(_PublicationSeal)
        values = dict(dataset_id=owner.dataset_id, binding=_binding(owner), inventory=capture.inventory,
                      file_facts=facts, manifest_bytes=capture.data["manifest.json"])
        for name, value in values.items():
            object.__setattr__(seal, name, value)
        # Capture may not bless bytes changed since the complete private verification.
        capture.recheck()
        owner.seal, owner.seal_snapshot, owner.state = seal, _seal_values(seal), "SEALED"
        return seal


def _revalidate_publication_seal(owner, seal):
    _check_owner(owner)
    _require(owner.state == "SEALED" and type(seal) is _PublicationSeal and seal is owner.seal
             and _seal_values(seal) == owner.seal_snapshot, "SEAL_AUTHORITY", "unissued, changed or consumed seal")
    _require(_binding(owner) == seal.binding, "SEAL_AUTHORITY", "ownership binding changed")
    _require(_inventory(owner.path, owner.scope) == seal.inventory == _expected_inventory(owner.expected),
             "INVENTORY_MISMATCH", "publication inventory differs")
    for name, _, identity, size, digest in seal.file_facts:
        item = owner.members[name]
        item.recheck()
        data = item.read_bytes()
        _require(item.identity == identity and len(data) == size and sha256(data).hexdigest() == digest,
                 "CONTENT_MISMATCH", "sealed member changed")
        _require(name != "manifest.json" or data == seal.manifest_bytes, "MANIFEST_BINDING", "manifest changed")
        _require(name != "_SUCCESS" or data == b"", "SUCCESS_MARKER", "marker changed")
        item.recheck()
    _check_owner(owner)


def _publish(owner, seal):
    _revalidate_publication_seal(owner, seal)
    if _exists(owner.final):
        raise _DestinationExists()
    try:
        if os.name == "nt":
            _rename_directory_no_replace_windows(owner.path, owner.final)
        else:
            _rename_directory_no_replace_linux(owner.scope.root_object.fd, os.fsencode(owner.path.name), os.fsencode(owner.final.name))
        owner.state = "COMMITTED_UNVERIFIED"
    except (_DestinationExists, MultiSourceCrossDayArtifactError):
        raise
    except BaseException as exc:
        owner.state = "PUBLICATION_UNCERTAIN"
        raise MultiSourceCrossDayArtifactError("PUBLICATION_FAILED", "PUBLICATION_UNCERTAIN", exc) from exc


def _existing(final, prepared, expected_identity):
    verified = load_verified_multi_source_cross_day_dataset(final)
    _require(verified.dataset_id == prepared.dataset_id, "EXISTING_FINAL_INVALID", "existing Dataset ID differs")
    # The reader checks physical integrity; this comparison binds it to this invocation.
    _require(dict(verified.manifest_payload["identity"]) == expected_identity
             and verified.status == prepared.status,
             "EXISTING_FINAL_INVALID", "existing identity differs from requested detached facts")
    return verified


def _make_publication_boundary():
    active, lock = {}, RLock()
    process_id = os.getpid()

    def after_fork():
        nonlocal active, lock, process_id
        active, lock, process_id = {}, RLock(), os.getpid()

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=after_fork)

    def require_owner(owner):
        _require(process_id == os.getpid() and type(owner) is _Owner and owner.process_id == process_id,
                 "OWNERSHIP_UNPROVEN", "current invocation owner required")
        with lock:
            record = active.get(id(owner))
            _require(record is not None and record[0] is owner and record[1:] ==
                     (owner.scope, owner.path, owner.final, owner.dataset_id, owner.expected),
                     "OWNERSHIP_UNPROVEN", "unissued or changed ownership record")

    def materialize_multi_source_cross_day_dataset_build(
        result: MultiSourceCrossDayDatasetResult, *, output_root: str | Path, built_at: datetime,
    ) -> MultiSourceCrossDayDatasetMaterializationResult:
        """Publish only issuance-bound detached facts; never reread caller content."""
        owner = None
        scope = None
        try:
            _require(process_id == os.getpid(), "INPUT_AUTHORITY", "inherited publication state")
            root = _output_root(output_root)
            timestamp_text(built_at)
            bridge = execution._require_live_issued_multi_source_cross_day_dataset_artifact_facts
            facts = bridge(result)
            prepared = _prepare_artifact_facts(facts)
            files = dict(_content_bytes(prepared))
            files["manifest.json"] = _manifest_bytes(prepared, files, built_at)
            expected_identity = decode_json(files["manifest.json"])["identity"]
            try:
                scope = _NativeScope(root, output=True)
            except OSError as exc:
                raise MultiSourceCrossDayArtifactError("UNSAFE_PATH", "PREFLIGHT", exc) from exc
            try:
                _require_qualified(scope)
            except OSError as exc:
                raise MultiSourceCrossDayArtifactError("PLATFORM_UNQUALIFIED", "PREFLIGHT", exc) from exc
            final = root / ("dataset_id=" + prepared.dataset_id)
            if _exists(final):
                try:
                    return MultiSourceCrossDayDatasetMaterializationResult(_existing(final, prepared, expected_identity), False)
                except (MultiSourceCrossDayArtifactError, OSError) as exc:
                    raise MultiSourceCrossDayArtifactError("EXISTING_FINAL_INVALID", "FAILED_PRECOMMIT", exc) from exc
            staging = root / ("." + prepared.dataset_id + ".tmp-" + os.urandom(16).hex())
            # Last live gate is before the first mutation. Byte preparation above used only detached facts.
            scope.recheck()
            again = bridge(result)
            _require(again.generation is facts.generation and again.epoch is facts.epoch
                     and again.process_id == facts.process_id and again.dataset_id == facts.dataset_id
                     and again.snapshot == facts.snapshot, "INPUT_AUTHORITY", "live issuance binding changed")
            scope.recheck()
            owner = _Owner(scope, staging, final, prepared.dataset_id, tuple(sorted((*files, "_SUCCESS"))), {}, os.getpid())
            if os.name == "nt":
                _new_directory(staging, scope.current_sid)
            else:
                os.mkdir(staging.name, 0o700, dir_fd=scope.root_object.fd)
            owner.members[""] = scope.member(staging, directory=True)
            with lock:
                active[id(owner)] = (owner, scope, staging, final, owner.dataset_id, owner.expected)
            for name in sorted(files, key=lambda n: (n == "manifest.json", n)):
                _write_member(owner, name, files[name])
            with _PhysicalCapture(scope, staging, require_success=False) as capture:
                _, payload = _verify_capture(capture)
                _require(payload["dataset_id"] == prepared.dataset_id, "MANIFEST_BINDING", "private Dataset ID differs")
            _write_member(owner, "_SUCCESS", b"")
            seal = _verify_and_seal_staging(owner)
            try:
                _publish(owner, seal)
            except _DestinationExists:
                try:
                    verified = _existing(final, prepared, expected_identity)
                except (MultiSourceCrossDayArtifactError, OSError) as exc:
                    raise MultiSourceCrossDayArtifactError("EXISTING_FINAL_INVALID", "FAILED_PRECOMMIT", exc) from exc
                _remove_tree(owner)
                owner.state = "EXISTING_EQUIVALENT"
                return MultiSourceCrossDayDatasetMaterializationResult(verified, False)
            try:
                verified = _existing(final, prepared, expected_identity)
            except (MultiSourceCrossDayArtifactError, OSError, ValueError) as exc:
                owner.state = "COMMITTED_INVALID"
                raise MultiSourceCrossDayArtifactError("FINAL_VERIFICATION_FAILED", "COMMITTED_INVALID", exc) from exc
            owner.state = "VERIFIED_FINAL"
            return MultiSourceCrossDayDatasetMaterializationResult(verified, True)
        except BaseException as exc:
            failure = exc
            if isinstance(exc, (DatasetError, OSError, UnicodeError, ValueError)) and not isinstance(exc, MultiSourceCrossDayArtifactError):
                failure = MultiSourceCrossDayArtifactError(
                    ("UNSAFE_PATH" if scope is not None and isinstance(exc, OSError) else "INPUT_AUTHORITY")
                    if owner is None else "PUBLICATION_FAILED",
                    "PREFLIGHT" if owner is None else "FAILED_PRECOMMIT", exc)
            if owner is not None and not owner.cleanup_attempted and owner.state in ("PRIVATE_STAGING", "SEALED", "FAILED_PRECOMMIT"):
                try:
                    _remove_tree(owner)
                except (MultiSourceCrossDayArtifactError, OSError) as cleanup:
                    failure.cleanup_failure = MultiSourceCrossDayArtifactError("CLEANUP_REFUSED", "FAILED_PRECOMMIT", cleanup)
                    failure.residue_path = owner.path
            if failure is exc:
                raise
            raise failure from exc
        finally:
            if owner is not None:
                with lock:
                    active.pop(id(owner), None)
                for item in owner.members.values():
                    item.close()
            if scope is not None:
                scope.close()

    return materialize_multi_source_cross_day_dataset_build, require_owner


materialize_multi_source_cross_day_dataset_build, _require_owner = _make_publication_boundary()
del _make_publication_boundary
