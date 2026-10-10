from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path
from typing import BinaryIO, Callable

from ..lifecycle import reject_link, verify_directory_chain


class AtomicFilePublicationError(RuntimeError):
    """Publication/cleanup uncertainty with an explicit physical commit state."""

    def __init__(self, message: str, *, path: Path, temporary_path: Path, published: bool):
        self.path = path
        self.temporary_path = temporary_path
        self.published = published
        state = "published; temporary residue retained" if published else "not published"
        super().__init__(f"{state}: {path}; temporary file {temporary_path}: {message}")


def _file_identity(value: os.stat_result) -> tuple[int, int]:
    if not value.st_ino:
        raise RuntimeError("Cannot establish file object identity")
    return value.st_dev, value.st_ino


def _verify_owned_temporary(
    path: Path,
    *,
    identity: tuple[int, int],
    parent_identity: tuple[int, int],
    published: bool,
) -> None:
    verify_directory_chain(path.parent, label="publication parent")
    if _file_identity(path.parent.stat()) != parent_identity:
        raise RuntimeError("Publication parent identity changed")
    reject_link(path, "publication temporary file")
    current = path.lstat()
    if (
        not stat.S_ISREG(current.st_mode)
        or _file_identity(current) != identity
        or current.st_nlink != (2 if published else 1)
    ):
        raise RuntimeError("Publication temporary file ownership changed")


def _write_file_no_replace(path: Path, serialize: Callable[[BinaryIO], None]) -> Path:
    """Publish one complete local file, strictly refusing every existing target.

    Only this invocation's exclusive sibling is a cleanup candidate. The
    no-replace commit is ``os.link`` after serialization, flush and close;
    unsupported filesystems fail without a fallback. This is one file's
    publication, not a Raw/Curated/Catalog transaction or power-loss promise.
    """
    path = Path(os.path.abspath(path))
    verify_directory_chain(path.parent, label="publication parent")
    reject_link(path, "publication target")
    if os.path.lexists(path):
        raise FileExistsError(f"Refusing existing publication target: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    verify_directory_chain(path.parent, label="publication parent")
    parent_identity = _file_identity(path.parent.stat())
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(name)
    identity: tuple[int, int] | None = None
    published = False
    failure: BaseException | None = None
    try:
        with os.fdopen(descriptor, "wb") as stream:
            created = os.fstat(stream.fileno())
            if not stat.S_ISREG(created.st_mode):
                raise RuntimeError("Publication temporary object is not a regular file")
            identity = _file_identity(created)
            _verify_owned_temporary(
                temporary_path, identity=identity, parent_identity=parent_identity, published=False
            )
            serialize(stream)
            stream.flush()
            os.fsync(stream.fileno())
        _verify_owned_temporary(
            temporary_path, identity=identity, parent_identity=parent_identity, published=False
        )
        reject_link(path, "publication target")
        if os.path.lexists(path):
            raise FileExistsError(f"Refusing existing publication target: {path}")
        os.link(temporary_path, path, follow_symlinks=False)
        published = True
        return path
    except BaseException as exc:
        failure = exc
        raise
    finally:
        try:
            if identity is None:
                raise RuntimeError("Publication temporary ownership was not established")
            _verify_owned_temporary(
                temporary_path,
                identity=identity,
                parent_identity=parent_identity,
                published=published,
            )
            temporary_path.unlink()
        except Exception as exc:
            detail = str(exc)
            if failure is not None:
                detail = f"{failure}; cleanup refused or failed: {detail}"
            raise AtomicFilePublicationError(
                detail, path=path, temporary_path=temporary_path, published=published
            ) from (failure if failure is not None else exc)
