"""Literal path and inventory admission, before any artifact traversal."""

import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re

from .artifact_models import _require


_DEVICE = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]|COM[\u00b9\u00b2\u00b3]|LPT[\u00b9\u00b2\u00b3])(?:\.|$)", re.I)
_FINAL = re.compile(r"^dataset_id=[0-9a-f]{64}$")
_STAGING = re.compile(r"^\.[0-9a-f]{64}\.tmp-[0-9a-f]{32}$")


def _component(name):
    _require(type(name) is str and name not in ("", ".", "..") and not any(ord(c) < 32 or ord(c) == 127 for c in name)
             and not name.endswith((".", " ")) and not any(c in name for c in '<>:"/\\|?*')
             and not _DEVICE.match(name), "UNSAFE_PATH", "noncanonical path component")
    try:
        name.encode("utf-8", errors="strict")
    except UnicodeError:
        _require(False, "UNSAFE_PATH", "invalid path encoding")
    return name


def _absolute_path(value):
    _require(type(value) in (str, Path, type(Path())), "INPUT_AUTHORITY", "native path or exact string required")
    text = str(value)
    if os.name == "nt":
        _require(re.match(r"^[A-Z]:[\\/]", text) is not None and not text.startswith(("\\\\", "//")),
                 "UNSAFE_PATH", "absolute canonical local drive required")
        tail = text[3:]
        components = re.split(r"[\\/]", tail) if tail else []
        _require(not components or all(components), "UNSAFE_PATH", "empty or trailing path component")
        for part in components:
            _component(part)
        _require(PureWindowsPath(text).is_absolute(), "UNSAFE_PATH", "absolute path required")
    else:
        _require(text.startswith("/") and not text.startswith("//"), "UNSAFE_PATH", "absolute local path required")
        components = text[1:].split("/") if text != "/" else []
        for part in components:
            _component(part)
        _require(PurePosixPath(text).is_absolute(), "UNSAFE_PATH", "absolute path required")
    return Path(text)


def _output_root(value):
    root = _absolute_path(value)
    _require(root != Path(root.anchor) and not any(_FINAL.fullmatch(p) or _STAGING.fullmatch(p) for p in root.parts),
             "UNSAFE_PATH", "output root must be separate from volume/artifact/staging")
    return root


def _relative_member(value):
    _require(type(value) is str and not value.startswith("/") and "\\" not in value,
             "UNSAFE_PATH", "canonical relative POSIX member required")
    for component in value.split("/"):
        _component(component)
    return value


def _expected_inventory(files):
    _require(type(files) in (tuple, frozenset) and len(files) == len(set(files)), "INVENTORY_MISMATCH", "unique file set required")
    entries = set()
    for name in files:
        _relative_member(name)
        entries.add((name, "FILE"))
        parts = name.split("/")
        for index in range(1, len(parts)):
            entries.add(("/".join(parts[:index]), "DIRECTORY"))
    _require(len({n.casefold() for n, _ in entries}) == len(entries), "INVENTORY_MISMATCH", "case/type alias")
    return tuple(sorted(entries))
