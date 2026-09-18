"""Retained native handles and two-pass physical artifact closure."""

import os
from pathlib import Path
import re
import stat
import sys
from types import MappingProxyType

from ._artifact_paths import _absolute_path, _output_root, _relative_member, _component, _expected_inventory
from ._artifact_windows import _WindowsObject, _current_sid
from ._artifact_linux import _LinuxObject
from .artifact_models import _require


_BASE_FILES = frozenset(("dataset.parquet", "feature_pit.json", "canonical_evidence.json", "ts2_features.json",
    "observation_pit.json", "observation_evidence.json", "observation_features.json", "cross_day_association.json",
    "cross_day_values.json", "schedule.json", "sample_audit.json", "split.json", "build_report.json", "manifest.json",
    "specs/split.yaml", "_SUCCESS"))
_SPEC_FILE = re.compile(r"^specs/(ts2|observation|cross_day)/[0-9a-f]{64}\.yaml$")
_DIRECTORIES = frozenset(("specs", "specs/ts2", "specs/observation", "specs/cross_day"))


def _exists(path):
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    return True


class _NativeScope:
    def __init__(self, root, *, output=False):
        self.root = _output_root(root) if output else _absolute_path(root)
        self.handles = []
        self.current_sid = _current_sid() if os.name == "nt" else None
        _require(os.name == "nt" or sys.platform == "linux", "PLATFORM_UNQUALIFIED", "unsupported native platform")
        try:
            for parent in tuple(reversed(self.root.parents)) + (self.root,):
                item = self.open(parent, directory=True, ancestor=parent != self.root)
                self.handles.append(item)
                if output:
                    # Exact marker checks, never repository or staging discovery/adoption.
                    for marker in (".git", ".hg", "manifest.json"):
                        _require(not _exists(parent / marker), "UNSAFE_PATH", "output root inside repository/evidence/artifact")
            self.root_object = self.handles[-1]
            self.filesystem = self.root_object.filesystem
            if sys.platform == "linux":
                _require(self.filesystem[0] == 0xef53, "PLATFORM_UNQUALIFIED", "local ext-family filesystem required")
            self.recheck()
        except BaseException:
            self.close()
            raise

    def open(self, path, *, directory, ancestor=False):
        data = os.lstat(path)
        _require(stat.S_ISDIR(data.st_mode) if directory else stat.S_ISREG(data.st_mode), "UNSAFE_PATH", "wrong filesystem object type")
        _require(not getattr(data, "st_file_attributes", 0) & 0x400, "UNSAFE_PATH", "reparse object forbidden")
        if os.name == "nt":
            return _WindowsObject(path, directory=directory, current_sid=self.current_sid, ancestor=ancestor)
        return _LinuxObject(path, directory=directory, ancestor=ancestor)

    def member(self, path, *, directory):
        item = self.open(path, directory=directory)
        try:
            _require(item.filesystem == self.filesystem, "FILESYSTEM_MISMATCH", "volume/mount transition")
            return item
        except BaseException:
            item.close()
            raise

    def recheck(self):
        for item in self.handles:
            item.recheck()

    def close(self):
        for item in reversed(self.handles):
            item.close()
        self.handles.clear()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _inventory(directory, scope):
    entries = []
    def visit(path, prefix):
        with os.scandir(path) as stream:
            children = tuple(sorted(stream, key=lambda e: e.name))
        for child in children:
            _component(child.name)
            name = prefix + child.name
            data = child.stat(follow_symlinks=False)
            _require(not getattr(data, "st_file_attributes", 0) & 0x400, "UNSAFE_PATH", "reparse inventory member")
            if stat.S_ISDIR(data.st_mode):
                _require(name in _DIRECTORIES, "INVENTORY_MISMATCH", "unexpected directory")
                entries.append((name, "DIRECTORY"))
                held = scope.member(Path(child.path), directory=True)
                try:
                    visit(Path(child.path), name + "/")
                    held.recheck()
                finally:
                    held.close()
            else:
                _require(stat.S_ISREG(data.st_mode) and data.st_nlink == 1, "UNSAFE_PATH", "nonregular or hard-linked member")
                _require(name in _BASE_FILES or _SPEC_FILE.fullmatch(name), "INVENTORY_MISMATCH", "unexpected file")
                entries.append((name, "FILE"))
    visit(directory, "")
    _require(len({n.casefold() for n, _ in entries}) == len(entries), "INVENTORY_MISMATCH", "case alias")
    return tuple(sorted(entries))


class _PhysicalCapture:
    def __init__(self, scope, directory, *, require_success):
        self.scope, self.directory = scope, Path(directory)
        self.objects = []
        try:
            scope.recheck()
            self.root_object = scope.member(self.directory, directory=True)
            self.objects.append(("", self.root_object))
            self.inventory = _inventory(self.directory, scope)
            content_names = tuple(n for n, kind in self.inventory if kind == "FILE")
            _require(self.inventory == _expected_inventory(content_names), "INVENTORY_MISMATCH", "extra/empty directory")
            _require(("_SUCCESS" in content_names) == require_success, "SUCCESS_MARKER", "incorrect marker state")
            data = {}
            for name, kind in self.inventory:
                item = scope.member(self.directory / _relative_member(name), directory=kind == "DIRECTORY")
                self.objects.append((name, item))
                if kind == "FILE":
                    data[name] = item.read_bytes()
                    item.recheck()
            _require(not require_success or data["_SUCCESS"] == b"", "SUCCESS_MARKER", "nonempty marker")
            self.data = MappingProxyType(data)
            self.recheck()
        except BaseException:
            self.close()
            raise

    def recheck(self):
        self.scope.recheck()
        self.root_object.recheck()
        _require(_inventory(self.directory, self.scope) == self.inventory, "INVENTORY_MISMATCH", "inventory changed")
        for name, item in self.objects:
            item.recheck()
            if name in self.data:
                _require(item.read_bytes() == self.data[name], "CONTENT_MISMATCH", "same-object byte mutation: " + name)
                item.recheck()
        _require(_inventory(self.directory, self.scope) == self.inventory, "INVENTORY_MISMATCH", "inventory changed after byte verification")
        self.scope.recheck()

    def close(self):
        for _, item in reversed(self.objects):
            item.close()
        self.objects.clear()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
