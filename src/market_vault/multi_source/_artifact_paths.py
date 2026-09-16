"""Fail-closed physical path inspection shared by the A4.3 reader and writer."""

import os
from pathlib import Path
import stat

from ._serialization import require
from .artifact_models import MultiSourceDatasetArtifactError


def member_path(value):
    require(type(value) is str and value and "\\" not in value and ":" not in value and "\x00" not in value,
            "unsafe member path")
    require(all(p not in ("", ".", "..") and not p.endswith((".", " ")) for p in value.split("/")), "unsafe member component")
    return value


def absolute_path(value):
    require(isinstance(value, (str, Path)), "explicit absolute path required")
    raw = str(value)
    path = Path(value)
    require(path.is_absolute() and "\x00" not in raw, "explicit absolute path required")
    # Inspect syntax before Path can erase dot/empty components.
    tail = raw[len(path.anchor):].replace("\\", "/")
    require(all(p not in ("", ".", "..") and ":" not in p and not p.endswith((".", " ")) for p in tail.split("/")),
            "unsafe absolute path")
    return path


def safe_path(path, *, directory, allow_missing=False):
    for component in list(reversed(path.parents)) + [path]:
        try:
            info = component.lstat()
        except FileNotFoundError:
            if allow_missing:
                return None
            raise MultiSourceDatasetArtifactError("missing artifact path: " + str(component))
        require(os.name != "nt" or hasattr(info, "st_file_attributes"), "unverifiable reparse status")
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
                "symlink/junction/reparse point forbidden")
        is_dir = directory if component == path else True
        require(stat.S_ISDIR(info.st_mode) if is_dir else stat.S_ISREG(info.st_mode), "unexpected filesystem object type")
        require(is_dir or info.st_nlink == 1, "hard-linked artifact file forbidden")
    return info


def object_identity(info):
    require(info is not None and info.st_ino, "unverifiable filesystem identity")
    return info.st_dev, info.st_ino, getattr(info, "st_birthtime_ns", info.st_ctime_ns if os.name == "nt" else None)


def read_bytes(path):
    before = safe_path(path, directory=False)
    with path.open("rb") as stream:
        require(object_identity(os.fstat(stream.fileno())) == object_identity(before), "file substituted while opening")
        data = stream.read()
        after = os.fstat(stream.fileno())
    last = safe_path(path, directory=False)
    require(object_identity(last) == object_identity(before) and
            (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns) == (last.st_size, last.st_mtime_ns),
            "file changed during read")
    return data


def inventory(root):
    device = safe_path(root, directory=True).st_dev
    result = set()
    def visit(directory):
        safe_path(directory, directory=True)
        for child in directory.iterdir():
            info = child.lstat()
            require(info.st_dev == device, "cross-filesystem member")
            is_dir = stat.S_ISDIR(info.st_mode)
            safe_path(child, directory=is_dir)
            result.add(child.relative_to(root).as_posix())
            if is_dir:
                visit(child)
    visit(root)
    return result


def expected_inventory(paths):
    result = set(paths)
    for path in paths:
        member_path(path)
        parts = path.split("/")
        result.update("/".join(parts[:i]) for i in range(1, len(parts)))
    return result
