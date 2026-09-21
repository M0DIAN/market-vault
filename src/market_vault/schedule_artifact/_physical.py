"""Read-only physical capture, not semantic or production schedule authority."""

from dataclasses import dataclass
import os
from pathlib import Path
import stat
import sys
from types import MappingProxyType

from ._canonical import _decode_base64, _parse_canonical_json
from ._errors import _ScheduleArtifactError, _require
from ._identity import _sha256
from ._models import (_MAX_FILE_BYTES, _MAX_INVENTORY_BYTES,
                      _MAX_SOURCE_BODY_BYTES, _MAX_JSON_NESTING)
from ._paths import _MEMBERS, _native_final_path
from ._platform import _require_qualified
from ._semantics import _admit_manifest, _validate_artifact_structure


class _NativeScope:
    """Retained parent/ancestry proof; the artifact is not opened here."""

    def __init__(self, parent):
        self.root, self.handles = Path(parent), []
        self.current_sid = None
        _require(os.name == "nt" or sys.platform == "linux",
                 "PLATFORM_UNQUALIFIED", "unsupported platform")
        if os.name == "nt":
            from ._windows import _current_sid
            self.current_sid = _current_sid()
        try:
            for path in tuple(reversed(self.root.parents)) + (self.root,):
                held = self.open(path, directory=True, ancestor=True)
                self.handles.append(held)
            self.root_object = self.handles[-1]
            self.filesystem = self.root_object.filesystem
            _require(all(item.filesystem == self.filesystem for item in self.handles),
                     "UNSAFE_PATH", "ancestry mount/volume transition")
            if sys.platform == "linux":
                from ._linux import _ext4_capability
                _require(self.filesystem[0] == 0xef53, "PLATFORM_UNQUALIFIED", "ext4 required")
                self.mount_description = _ext4_capability(self.root_object.fd)
            self.recheck()
        except BaseException:
            self.close()
            raise

    def open(self, path, *, directory, ancestor=False):
        if os.name == "nt":
            from ._windows import _WindowsObject
            return _WindowsObject(path, directory=directory, ancestor=ancestor,
                                  current_sid=self.current_sid)
        from ._linux import _LinuxObject
        return _LinuxObject(path, directory=directory, ancestor=ancestor)

    def member(self, path, *, directory):
        held = self.open(path, directory=directory)
        try:
            _require(held.filesystem == self.filesystem, "UNSAFE_PATH", "member mount/volume transition")
            return held
        except BaseException:
            held.close()
            raise

    def recheck(self):
        _require(bool(self.handles), "PHYSICAL_DRIFT", "scope already closed")
        for item in self.handles:
            item.recheck()
        if sys.platform == "linux":
            from ._linux import _ext4_capability
            _require(_ext4_capability(self.root_object.fd) == self.mount_description,
                     "PHYSICAL_DRIFT", "mount description changed")

    def close(self):
        for item in reversed(self.handles):
            item.close()
        self.handles.clear()


def _inventory(path):
    names = []
    with os.scandir(path) as children:
        for child in children:
            _require(child.name in _MEMBERS and child.name not in names,
                     "INVENTORY_MISMATCH", "unexpected/aliased member")
            data = child.stat(follow_symlinks=False)
            _require(stat.S_ISREG(data.st_mode) and not getattr(data, "st_file_attributes", 0) & 0x402,
                     "UNSAFE_PATH", "nonregular, hidden or reparse member")
            # Windows DirEntry link counts are not native single-link evidence.
            names.append(child.name)
    _require(tuple(sorted(names)) == _MEMBERS, "INVENTORY_MISMATCH", "missing member")
    return _MEMBERS


def _check_sizes(sizes):
    _require(tuple(sorted(sizes)) == _MEMBERS, "INVENTORY_MISMATCH", "incomplete native sizes")
    _require(all(type(n) is int and 0 <= n <= _MAX_FILE_BYTES for n in sizes.values()),
             "INTEGRITY_MISMATCH", "file resource bound")
    _require(sum(sizes.values()) <= _MAX_INVENTORY_BYTES,
             "INTEGRITY_MISMATCH", "inventory resource bound")
    _require(sizes["_SUCCESS"] == 0, "INTEGRITY_MISMATCH", "nonempty success marker")


def _json_nesting_preflight(data):
    _require(type(data) is bytes and len(data) <= _MAX_FILE_BYTES,
             "NONCANONICAL_BYTES", "bounded exact JSON bytes required")
    stack, quoted, escaped = [], False, False
    for byte in data:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (123, 91):
            _require(len(stack) < _MAX_JSON_NESTING, "NONCANONICAL_BYTES", "JSON nesting limit")
            stack.append(byte)
        elif byte in (125, 93):
            _require(bool(stack) and stack.pop() == (123 if byte == 125 else 91),
                     "NONCANONICAL_BYTES", "unbalanced JSON structure")
    _require(not stack and not quoted, "NONCANONICAL_BYTES", "unfinished JSON structure")


def _source_encoded_size(text):
    _require(type(text) is str and len(text) % 4 == 0,
             "NONCANONICAL_BYTES", "padded source base64 required")
    # Exact decoded length from quartet count/padding, before any decoded allocation.
    padding = 2 if text.endswith("==") else int(text.endswith("="))
    size = len(text) // 4 * 3 - padding
    _require(0 <= size <= _MAX_SOURCE_BODY_BYTES,
             "INTEGRITY_MISMATCH", "source body predecode bound")
    return size


def _decode_source_body(text):
    size = _source_encoded_size(text)
    raw = _decode_base64(text)
    _require(len(raw) == size, "INTEGRITY_MISMATCH", "source decoded length differs")
    return raw


def _parse_guarded_json(data):
    _json_nesting_preflight(data)
    value = _parse_canonical_json(data)
    def visit(item):
        if type(item) is dict:
            for name, child in item.items():
                if name in ("request_bytes_base64", "response_bytes_base64"):
                    _source_encoded_size(child)
                visit(child)
        elif type(item) is list:
            for child in item:
                visit(child)
    visit(value)
    return value


@dataclass(frozen=True, slots=True)
class _ObjectEvidence:
    identity: tuple
    filesystem: tuple
    security: tuple
    size: int


def _evidence(held):
    return _ObjectEvidence(held.identity, held.filesystem, held.security, held.size)


@dataclass(frozen=True, slots=True)
class _PhysicalCapture:
    """Immutable facts and byte copies; live resources are private, never trust IDs."""

    _scope: object
    _directory: Path
    _objects: tuple
    ancestry: tuple
    evidence: MappingProxyType
    inventory: tuple
    data: MappingProxyType
    sizes: MappingProxyType
    hashes: MappingProxyType

    def recheck(self):
        try:
            self._scope.recheck()
            _require(tuple(_evidence(h) for h in self._scope.handles) == self.ancestry,
                     "PHYSICAL_DRIFT", "ancestry evidence changed")
            _require(_inventory(self._directory) == self.inventory,
                     "INVENTORY_MISMATCH", "inventory changed")
            for name, held in self._objects:
                held.recheck()
                _require(_evidence(held) == self.evidence[name], "PHYSICAL_DRIFT", "object evidence changed")
                if name:
                    raw = held.read_bytes(self.sizes[name])
                    _require(raw == self.data[name] and _sha256(raw) == self.hashes[name],
                             "PHYSICAL_DRIFT", "captured bytes changed")
                    held.recheck()
            _require(_inventory(self._directory) == self.inventory,
                     "INVENTORY_MISMATCH", "inventory changed after bytes")
            self._scope.recheck()
        except (OSError, _ScheduleArtifactError) as exc:
            if isinstance(exc, _ScheduleArtifactError) and exc.reason_code in ("INVENTORY_MISMATCH", "PHYSICAL_DRIFT"):
                raise
            raise _ScheduleArtifactError("PHYSICAL_DRIFT", "native closure failed") from exc

    def close(self):
        for _, held in reversed(self._objects):
            held.close()
        self._scope.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _capture_members(scope, directory):
    """Low-level mechanics only, deliberately separate from platform admission."""
    objects = []
    try:
        scope.recheck()
        root = scope.member(directory, directory=True)
        objects.append(("", root))
        inventory = _inventory(directory)
        for name in inventory:
            objects.append((name, scope.member(directory / name, directory=False)))
        sizes = {name: held.size for name, held in objects if name}
        _check_sizes(sizes)
        data = {name: held.read_bytes(sizes[name]) for name, held in objects if name}
        capture = _PhysicalCapture(scope, directory, tuple(objects),
            tuple(_evidence(h) for h in scope.handles),
            MappingProxyType({name: _evidence(held) for name, held in objects}), inventory,
            MappingProxyType(data), MappingProxyType(sizes),
            MappingProxyType({name: _sha256(raw) for name, raw in data.items()}))
        capture.recheck()
        return capture
    except BaseException:
        for _, held in reversed(objects):
            held.close()
        raise


def _preflight_documents(data):
    """Raw-byte guards over every captured document; not logical-document parsing."""
    for name in data:
        if name != "_SUCCESS":
            _parse_guarded_json(data[name])


def _admit_captured_manifest(capture):
    """The only path from captured bytes to manifest admission."""
    return _admit_manifest(
        manifest_bytes=capture.data["manifest.json"],
        supplied={member: capture.data[member] for member in _MEMBERS if member != "_SUCCESS"},
    )


def _capture_physical(value):
    """Read-only physical entrypoint; logical documents are parsed only after admission."""
    directory = _native_final_path(value)
    scope = _NativeScope(directory.parent)
    try:
        _require_qualified(scope)
        capture = _capture_members(scope, directory)
        try:
            _preflight_documents(capture.data)
            admitted = _admit_captured_manifest(capture)
            facts = _validate_artifact_structure(
                admitted=admitted,
                source_snapshot_bytes=capture.data["source_snapshot.json"],
                coverage_evidence_bytes=capture.data["coverage_evidence.json"],
                verification_receipt_bytes=capture.data["verification_receipt.json"],
                schedule_bytes=capture.data["schedule.json"],
                directory_name=directory.name,
            )
            capture.recheck()
            return facts
        finally:
            capture.close()
    except BaseException:
        scope.close()
        raise
