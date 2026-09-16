"""Immutable publication under multi_source_dataset_atomic_publication_v1."""

import ctypes
from dataclasses import dataclass, fields, replace
from datetime import datetime
import errno
import hashlib
import os
from pathlib import Path
import shutil
import sys
from uuid import uuid4

import pyarrow as pa
import yaml

from ..dataset.artifact_serialization import feature_spec_artifact, label_spec_artifact, split_spec_artifact
from ..dataset.encoding import normalize_utc_datetime
from ..dataset.specs import feature_label_spec_pin
from ._artifact_paths import absolute_path, inventory, object_identity, safe_path, expected_inventory, read_bytes
from ._artifact_schema import output_contracts, parquet_bytes, physical_values, table_contracts
from ._artifact_validation import build_report
from ._serialization import canonical_json, evidence_payload, require
from .artifact_models import MultiSourceDatasetMaterializationError, MultiSourceDatasetMaterializationResult, MultiSourceDatasetOutputFile
from .feature_specs import observation_feature_spec_pin, serialize_observation_feature_spec
from .manifest import MultiSourceDatasetManifest, serialize_multi_source_dataset_manifest
from .orchestration_models import MultiSourceDatasetOrchestrationResult
from .reader import _verify_directory, load_verified_multi_source_dataset


class _DestinationExistsError(MultiSourceDatasetMaterializationError):
    pass


class _NoReplaceUnsupportedError(MultiSourceDatasetMaterializationError):
    pass


@dataclass(slots=True)
class _StagingOwnership:
    path: object
    path_identity: tuple
    output_root: object
    root_identity: tuple
    final: object
    dataset_id: str
    allowed: frozenset
    committed: bool = False
    removed: bool = False
    publication_seal: object = None


@dataclass(frozen=True, slots=True, init=False)
class _PublicationSeal:
    path: Path
    output_root: Path
    final: Path
    path_identity: tuple
    root_identity: tuple
    dataset_id: str
    expected_inventory: frozenset
    file_facts: tuple

    def __init__(self, *args, **kwargs):
        raise TypeError("publication seals are issued only by private verification")


def _check_owner(owner):
    require(type(owner) is _StagingOwnership and not owner.committed and not owner.removed, "no uncommitted staging ownership")
    require(owner.path.parent == owner.output_root == owner.final.parent and owner.final.name == owner.dataset_id
        and owner.path.name.startswith("." + owner.dataset_id + ".tmp-"), "staging ownership scope mismatch")
    root = safe_path(owner.output_root, directory=True)
    staging = safe_path(owner.path, directory=True)
    require(object_identity(root) == owner.root_identity and object_identity(staging) == owner.path_identity
        and staging.st_dev == root.st_dev, "staging/root identity changed or filesystem mismatch")
    require(inventory(owner.path) <= expected_inventory(owner.allowed), "unowned staging member")


def _remove_tree(owner):
    """Only the current invocation's same, safe, uncommitted staging object."""
    _check_owner(owner)
    shutil.rmtree(owner.path)
    owner.removed = True


def _rename_directory_no_replace_windows(staging, final):
    if os.name != "nt":
        raise _NoReplaceUnsupportedError("Windows no-replace primitive unavailable")
    try:
        os.rename(staging, final)
    except OSError as exc:
        if isinstance(exc, FileExistsError) or getattr(exc, "winerror", None) in (80, 183):
            raise _DestinationExistsError("destination already exists") from exc
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
        raise _DestinationExistsError("destination already exists")
    if error in (errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP):
        raise _NoReplaceUnsupportedError(f"safe no-replace publication unsupported: errno {error}")
    raise MultiSourceDatasetMaterializationError(f"atomic no-replace failed: errno {error}")


def _revalidate_publication_seal(owner, seal):
    require(type(seal) is _PublicationSeal and seal is owner.publication_seal, "unissued publication seal")
    require((owner.path, owner.output_root, owner.final, owner.path_identity, owner.root_identity, owner.dataset_id) ==
        (seal.path, seal.output_root, seal.final, seal.path_identity, seal.root_identity, seal.dataset_id),
        "publication seal ownership mismatch")
    _check_owner(owner)
    require(frozenset(expected_inventory(owner.allowed)) == seal.expected_inventory and
            inventory(owner.path) == seal.expected_inventory, "publication inventory mismatch")
    require({name for name, _, _, _ in seal.file_facts} == owner.allowed, "publication whitelist mismatch")
    for name, file_identity, size, digest in seal.file_facts:
        path = owner.path / name
        require(object_identity(safe_path(path, directory=False)) == file_identity, "publication file substituted: " + name)
        data = read_bytes(path)
        require(len(data) == size and hashlib.sha256(data).hexdigest() == digest, "publication content changed: " + name)
        require(name != "_SUCCESS" or data == b"", "publication marker must be empty")
        require(object_identity(safe_path(path, directory=False)) == file_identity, "publication file substituted: " + name)
    _check_owner(owner)
    require(inventory(owner.path) == seal.expected_inventory, "publication inventory changed")
    final = safe_path(owner.final, directory=True, allow_missing=True)
    require(final is None or final.st_dev == seal.root_identity[0], "publication final filesystem mismatch")


def _verify_and_seal_staging(owner):
    _check_owner(owner)
    expected = frozenset(expected_inventory(owner.allowed))
    require(inventory(owner.path) == expected, "publication inventory mismatch")
    identities = {name: object_identity(safe_path(owner.path / name, directory=False)) for name in sorted(owner.allowed)}
    verified = _verify_directory(owner.path, require_success=True, final_name=False)
    manifest = verified["manifest"]
    require(verified["dataset_id"] == manifest.dataset_id == owner.dataset_id, "publication manifest Dataset identity mismatch")
    # Anchor hashes to the verified manifest, never to new unchecked staging bytes.
    raw_manifest = serialize_multi_source_dataset_manifest(manifest)
    facts = {f.relative_path: (f.byte_size, f.sha256) for f in manifest.output_files}
    facts["manifest.json"] = (len(raw_manifest), hashlib.sha256(raw_manifest).hexdigest())
    facts["_SUCCESS"] = (0, hashlib.sha256(b"").hexdigest())
    require(set(facts) == owner.allowed, "publication manifest whitelist mismatch")
    seal = object.__new__(_PublicationSeal)
    values = dict(path=owner.path, output_root=owner.output_root, final=owner.final,
        path_identity=owner.path_identity, root_identity=owner.root_identity, dataset_id=owner.dataset_id,
        expected_inventory=expected, file_facts=tuple((n, identities[n], *facts[n]) for n in sorted(facts)))
    for name, value in values.items():
        object.__setattr__(seal, name, value)
    owner.publication_seal = seal
    _revalidate_publication_seal(owner, seal)
    return seal


def _publish(owner, seal):
    _revalidate_publication_seal(owner, seal)
    if os.name == "nt":
        _rename_directory_no_replace_windows(owner.path, owner.final)
    elif os.name == "posix" and sys.platform.startswith("linux"):
        _rename_directory_no_replace_linux(owner.path, owner.final)
    else:
        raise _NoReplaceUnsupportedError("safe no-replace publication unsupported on platform")
    owner.committed = True


def _create_root(root):
    for component in list(reversed(root.parents)) + [root]:
        if safe_path(component, directory=True, allow_missing=True) is None:
            try:
                component.mkdir()
            except FileExistsError:
                pass
        safe_path(component, directory=True)


def _write_bytes(owner, name, data):
    _check_owner(owner)
    require(name in owner.allowed, "unapproved staging member")
    path = owner.path / name
    for parent in reversed(path.parents):
        if parent == owner.path or owner.path in parent.parents:
            if safe_path(parent, directory=True, allow_missing=True) is None:
                parent.mkdir()
            safe_path(parent, directory=True)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _files(result, built_at):
    identity = result.identity_input
    rows = (result.logical_row_mappings(), result.bar_pit_result.association_rows,
        tuple({f.name: getattr(d, f.name) for f in fields(d)} for d in result.observation_pit_result.decisions),
        tuple({f.name: getattr(b, f.name) for f in fields(b)} for b in result.observation_pit_result.sample_bindings),
        physical_values(result.observation_feature_result, result.observation_feature_specs))
    files, counts = {}, {}
    for contract, table in zip(table_contracts(identity), rows):
        files[contract[0]] = parquet_bytes(result.dataset_id, contract, table)
        counts[contract[0]] = len(table)
    files["associations/observation_evidence.json"] = canonical_json(evidence_payload(result.observation_evidence))
    for specs, prefix, pin_fn, serializer in (
        (result.bar_feature_specs, "feature_specs/bar", feature_label_spec_pin, feature_spec_artifact),
        (result.observation_feature_specs, "feature_specs/observation", observation_feature_spec_pin, serialize_observation_feature_spec),
        (result.label_specs, "label_specs", feature_label_spec_pin, label_spec_artifact)):
        for spec in specs:
            files[prefix + "/" + pin_fn(spec).content_sha256 + ".yaml"] = serializer(spec)
    files["split_spec.yaml"] = split_spec_artifact(result.split_spec)
    files["build_report.json"] = canonical_json(build_report(identity, built_at, len(result.rows), result.observation_feature_result, result.split_result))
    contracts = output_contracts(identity)
    facts = tuple(MultiSourceDatasetOutputFile(name, contracts[name][0], len(data), hashlib.sha256(data).hexdigest(),
        counts.get(name), contracts[name][0], contracts[name][1], contracts[name][2]) for name, data in sorted(files.items()))
    files["manifest.json"] = serialize_multi_source_dataset_manifest(MultiSourceDatasetManifest(identity, built_at, len(result.rows), facts))
    return files


def _existing(final, dataset_id):
    verified = load_verified_multi_source_dataset(final)
    require(verified.dataset_id == dataset_id, "existing final identity mismatch")
    return MultiSourceDatasetMaterializationResult(verified, False)


def materialize_multi_source_dataset_build(
    result: MultiSourceDatasetOrchestrationResult, *, output_root: str | Path, built_at: datetime,
) -> MultiSourceDatasetMaterializationResult:
    """Publish one exact A4.2 result, or verify an existing immutable final."""
    owner = None
    try:
        require(type(result) is MultiSourceDatasetOrchestrationResult, "materializer requires exact A4.2 result")
        validated = replace(result)
        claims = tuple(f.name for f in fields(result) if f.name not in ("canonical_builds", "observation_builds"))
        require(canonical_json({n: getattr(validated, n) for n in claims}) ==
                canonical_json({n: getattr(result, n) for n in claims}), "tampered A4.2 result")
        result = validated
        built_at = normalize_utc_datetime(built_at, "built_at")
        root = absolute_path(output_root)
        _create_root(root)
        final = root / result.dataset_id
        if safe_path(final, directory=True, allow_missing=True) is not None:
            return _existing(final, result.dataset_id)
        staging = root / ("." + result.dataset_id + ".tmp-" + uuid4().hex)
        root_identity = object_identity(safe_path(root, directory=True))
        staging.mkdir()
        allowed = frozenset(output_contracts(result.identity_input)) | {"manifest.json", "_SUCCESS"}
        owner = _StagingOwnership(staging, object_identity(safe_path(staging, directory=True)), root,
            root_identity, final, result.dataset_id, allowed)
        _check_owner(owner)
        for name, data in _files(result, built_at).items():
            _write_bytes(owner, name, data)
        _verify_directory(staging, require_success=False, final_name=False)
        _write_bytes(owner, "_SUCCESS", b"")
        seal = _verify_and_seal_staging(owner)
        try:
            _publish(owner, seal)
        except _DestinationExistsError:
            existing = _existing(final, result.dataset_id)
            _remove_tree(owner)
            return existing
        return MultiSourceDatasetMaterializationResult(load_verified_multi_source_dataset(final), True)
    except (OSError, ValueError, TypeError, KeyError, OverflowError, UnicodeError, pa.ArrowException, yaml.YAMLError) as exc:
        if owner is not None and not owner.committed and not owner.removed:
            try:
                _remove_tree(owner)
            except (OSError, ValueError) as cleanup:
                raise MultiSourceDatasetMaterializationError(f"materialization failed; staging cleanup refused/failed: {cleanup}") from exc
        if isinstance(exc, MultiSourceDatasetMaterializationError):
            raise
        raise MultiSourceDatasetMaterializationError(f"multi-source materialization failed: {exc}") from exc
