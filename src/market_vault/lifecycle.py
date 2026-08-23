from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class LifecycleLockError(RuntimeError):
    """Raised when the market-bar lifecycle lock cannot be acquired safely."""


def is_junction_or_reparse(path: Path) -> bool:
    """Return whether *path* is a Windows junction or reparse point.

    Python 3.11 has no ``Path.is_junction``. On Windows the file attributes
    are queried directly and an uncheckable path fails closed.
    """
    if hasattr(path, "is_junction"):
        return path.is_junction()
    if os.name != "nt":
        return False
    import ctypes

    try:
        attributes = ctypes.windll.kernel32.GetFileAttributesW(str(path))
    except (AttributeError, OSError, TypeError) as exc:
        raise LifecycleLockError(
            f"cannot verify Windows reparse-point status for {path}"
        ) from exc
    if attributes == 0xFFFFFFFF:
        return False
    return bool(attributes & 0x400)


def reject_link(path: Path, label: str) -> None:
    if path.is_symlink() or is_junction_or_reparse(path):
        raise LifecycleLockError(f"{label} must not be a symlink or reparse point: {path}")


def verify_directory_chain(path: Path, *, label: str) -> None:
    """Fail closed unless every existing component is a regular directory."""
    absolute = Path(os.path.abspath(path))
    for component in (absolute, *absolute.parents):
        reject_link(component, label)
        if component.exists() and not component.is_dir():
            raise LifecycleLockError(f"{label} must be a regular directory: {component}")


@dataclass
class MarketBarLifecycleLock:
    """Cross-process exclusive lock for supported market-bar mutations.

    Atomic directory creation is the lock primitive. Locks are deliberately
    not reclaimed automatically: a process crash leaves a visible stale lock
    that blocks mutation until an operator investigates it.
    """

    data_root: Path
    operation: str

    def __post_init__(self) -> None:
        root = Path(os.path.abspath(self.data_root))
        self.data_root = root
        self.lock_parent = root / ".lifecycle"
        self.lock_path = self.lock_parent / "market_bars.lock"
        self.owner_path = self.lock_path / "owner.json"
        self.token = uuid4().hex
        self._acquired = False

    def acquire(self) -> "MarketBarLifecycleLock":
        verify_directory_chain(self.data_root, label="data root")
        self.data_root.mkdir(parents=True, exist_ok=True)
        verify_directory_chain(self.data_root, label="data root")
        self.lock_parent.mkdir(exist_ok=True)
        verify_directory_chain(self.lock_parent, label="lifecycle lock parent")
        try:
            self.lock_path.mkdir(exist_ok=False)
        except FileExistsError as exc:
            raise LifecycleLockError(
                f"market-bar lifecycle lock is already held: {self.lock_path}"
            ) from exc
        try:
            payload = {
                "operation": self.operation,
                "pid": os.getpid(),
                "acquired_at": datetime.now(timezone.utc).isoformat(),
                "token": self.token,
            }
            with self.owner_path.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._acquired = True
            return self
        except BaseException:
            try:
                self.owner_path.unlink(missing_ok=True)
                self.lock_path.rmdir()
            except OSError:
                pass
            raise

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            payload = json.loads(self.owner_path.read_text(encoding="utf-8"))
            if payload.get("token") != self.token:
                raise LifecycleLockError("lifecycle lock ownership changed before release")
            self.owner_path.unlink()
            self.lock_path.rmdir()
            self._acquired = False
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise LifecycleLockError(
                f"failed to release market-bar lifecycle lock: {self.lock_path}"
            ) from exc

    def __enter__(self) -> "MarketBarLifecycleLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()
