#!/usr/bin/env python3
"""Fail-closed local FULL pytest runner used by verify_full.ps1."""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4


GIB = 1024**3
MINIMUM_FREE_BYTES = 10 * GIB
RUN_ID_RE = re.compile(r"^run-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$")
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF


class ValidationSafetyError(RuntimeError):
    """The local FULL run cannot prove that its temporary path is safe."""


@dataclass(frozen=True)
class ValidationPreflight:
    repo_root: Path
    temp_parent: Path
    run_id: str
    run_dir: Path
    worktrees: tuple[Path, ...]
    available_bytes: int
    required_bytes: int
    command: tuple[str, ...]


def _decode_git_output(value: bytes) -> str:
    return value.decode("utf-8", errors="surrogateescape")


def discover_repo_root(anchor: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(anchor), "rev-parse", "--show-toplevel"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = _decode_git_output(result.stderr).strip()
        raise ValidationSafetyError(f"cannot discover repository root: {detail}")
    raw = _decode_git_output(result.stdout).strip()
    if not raw:
        raise ValidationSafetyError("git returned an empty repository root")
    return _resolved(Path(raw), "repository root")


def parse_worktree_porcelain(payload: bytes) -> tuple[Path, ...]:
    worktrees: list[Path] = []
    for field in payload.split(b"\0"):
        if field.startswith(b"worktree "):
            raw = _decode_git_output(field[len(b"worktree ") :])
            if not raw:
                raise ValidationSafetyError("git reported an empty worktree path")
            worktrees.append(Path(raw))
    if not worktrees:
        raise ValidationSafetyError("git did not report any registered worktrees")
    return tuple(worktrees)


def discover_worktrees(repo_root: Path) -> tuple[Path, ...]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "list", "--porcelain", "-z"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = _decode_git_output(result.stderr).strip()
        raise ValidationSafetyError(f"cannot enumerate registered Git worktrees: {detail}")
    worktrees = tuple(
        _resolved(path, "registered worktree")
        for path in parse_worktree_porcelain(result.stdout)
    )
    if not any(_same_path(repo_root, worktree) for worktree in worktrees):
        raise ValidationSafetyError(
            "current repository root is absent from git worktree list; safety is unproven"
        )
    return worktrees


def _resolved(path: Path, label: str) -> Path:
    try:
        return path.expanduser().resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ValidationSafetyError(f"cannot resolve {label}: {path}") from exc


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _same_path(left: Path, right: Path) -> bool:
    return _path_key(left) == _path_key(right)


def _contains(root: Path, candidate: Path) -> bool:
    try:
        return os.path.commonpath([_path_key(root), _path_key(candidate)]) == _path_key(root)
    except ValueError:
        return False


def assert_outside_worktrees(
    candidate: Path, repo_root: Path, worktrees: Sequence[Path]
) -> Path:
    if not worktrees:
        raise ValidationSafetyError("registered worktree set is empty; safety is unproven")
    absolute = Path(os.path.abspath(os.fspath(candidate.expanduser())))
    resolved = _resolved(absolute, "pytest temporary run directory")
    roots = tuple(worktrees) + (repo_root,)
    for root in roots:
        root_absolute = Path(os.path.abspath(os.fspath(root.expanduser())))
        root_resolved = _resolved(root_absolute, "registered worktree")
        if _contains(root_absolute, absolute) or _contains(root_resolved, resolved):
            raise ValidationSafetyError(
                "pytest temporary run directory is inside a registered Git worktree: "
                f"candidate={resolved} worktree={root_resolved}"
            )
    return resolved


def _nearest_existing(path: Path) -> Path:
    candidate = path
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            raise ValidationSafetyError(
                f"cannot find an existing filesystem ancestor for temp root: {path}"
            )
        candidate = parent
    if not candidate.is_dir():
        raise ValidationSafetyError(
            f"temp root filesystem ancestor is not a directory: {candidate}"
        )
    return candidate


def available_bytes(
    path: Path, disk_usage: Callable[[Path], Any] = shutil.disk_usage
) -> int:
    anchor = _nearest_existing(path)
    try:
        free = int(disk_usage(anchor).free)
    except (OSError, TypeError, ValueError, AttributeError) as exc:
        raise ValidationSafetyError(
            f"cannot determine available bytes for temp filesystem: {anchor}"
        ) from exc
    if free < 0:
        raise ValidationSafetyError("disk-space discovery returned a negative value")
    return free


def new_run_id(now_utc: str | None = None) -> str:
    if now_utc is None:
        from datetime import datetime, timezone

        now_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{now_utc}-{uuid4().hex[:12]}"


def _automatic_temp_parents(env: Mapping[str, str]) -> tuple[Path, ...]:
    candidates: list[Path] = []
    if os.name == "nt" and Path("D:/").is_dir():
        candidates.append(Path("D:/MarketVault-TestTemp"))
    local_app_data = env.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        candidates.append(Path(local_app_data) / "MarketVault" / "TestTemp")
    candidates.append(Path(tempfile.gettempdir()) / "MarketVault-TestTemp")
    unique: list[Path] = []
    for candidate in candidates:
        if not any(_same_path(candidate, existing) for existing in unique):
            unique.append(candidate)
    return tuple(unique)


def choose_temp_parent(
    *,
    repo_root: Path,
    worktrees: Sequence[Path],
    run_id: str,
    explicit: str | None,
    env: Mapping[str, str],
) -> Path:
    override = explicit or env.get("MARKET_VAULT_TEST_TEMP_ROOT")
    if override:
        parent = Path(override).expanduser()
        if not parent.is_absolute():
            raise ValidationSafetyError(
                "MARKET_VAULT_TEST_TEMP_ROOT must be an absolute path"
            )
        assert_outside_worktrees(parent / run_id, repo_root, worktrees)
        return _resolved(parent, "configured pytest temp parent")

    refusals: list[str] = []
    for parent in _automatic_temp_parents(env):
        try:
            assert_outside_worktrees(parent / run_id, repo_root, worktrees)
            _nearest_existing(parent)
        except ValidationSafetyError as exc:
            refusals.append(f"{parent}: {exc}")
            continue
        return _resolved(parent, "pytest temp parent")
    raise ValidationSafetyError(
        "no safe repository-external pytest temp parent is available: "
        + "; ".join(refusals)
    )


def build_preflight(
    *,
    repo_root: Path,
    temp_parent: Path,
    worktrees: Sequence[Path],
    run_id: str,
    python_executable: str,
    required_bytes: int = MINIMUM_FREE_BYTES,
    disk_usage: Callable[[Path], Any] = shutil.disk_usage,
) -> ValidationPreflight:
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValidationSafetyError(f"invalid generated validation run ID: {run_id}")
    if required_bytes < 0:
        raise ValidationSafetyError("minimum free-space threshold cannot be negative")
    run_dir = assert_outside_worktrees(
        temp_parent / run_id, repo_root, worktrees
    )
    free = available_bytes(run_dir, disk_usage)
    command = (
        python_executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "--basetemp",
        str(run_dir),
    )
    return ValidationPreflight(
        repo_root=repo_root,
        temp_parent=temp_parent,
        run_id=run_id,
        run_dir=run_dir,
        worktrees=tuple(worktrees),
        available_bytes=free,
        required_bytes=required_bytes,
        command=command,
    )


def _format_command(command: Sequence[str]) -> str:
    return subprocess.list2cmdline(list(command))


def _emit_line(line: str) -> None:
    print(line, flush=True)


def _running_on_windows() -> bool:
    return os.name == "nt"


def _windows_file_attributes(path: Path) -> int:
    """Read native attributes or fail closed with the Windows error code."""
    import ctypes

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_attributes = kernel32.GetFileAttributesW
        get_attributes.argtypes = [ctypes.c_wchar_p]
        get_attributes.restype = ctypes.c_uint32
        ctypes.set_last_error(0)
        attributes = int(get_attributes(str(path)))
        error_code = int(ctypes.get_last_error())
    except (AttributeError, OSError, TypeError) as exc:
        raise ValidationSafetyError(
            f"cannot verify Windows file attributes for cleanup target {path}: {exc}"
        ) from exc
    if attributes == INVALID_FILE_ATTRIBUTES:
        if error_code in {2, 3} and not os.path.lexists(path):
            return 0
        raise ValidationSafetyError(
            f"cannot verify Windows file attributes for cleanup target {path}: "
            f"INVALID_FILE_ATTRIBUTES (Windows error {error_code})"
        )
    return attributes


def _is_link_or_reparse(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        if _running_on_windows():
            return bool(
                _windows_file_attributes(path) & FILE_ATTRIBUTE_REPARSE_POINT
            )
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction and is_junction())
    except ValidationSafetyError:
        raise
    except OSError as exc:
        raise ValidationSafetyError(f"cannot inspect cleanup target: {path}") from exc


def cleanup_run_directory(
    run_dir: Path,
    *,
    temp_parent: Path,
    run_id: str,
    cleanup: Callable[[Path], None] = shutil.rmtree,
) -> None:
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValidationSafetyError("refusing cleanup for an invalid run ID")
    expected = Path(os.path.abspath(os.fspath(temp_parent / run_id)))
    actual = Path(os.path.abspath(os.fspath(run_dir)))
    if not _same_path(actual, expected) or not _same_path(actual.parent, temp_parent):
        raise ValidationSafetyError(
            f"refusing cleanup outside the exact run-owned directory: {actual}"
        )
    if _is_link_or_reparse(actual):
        raise ValidationSafetyError(
            f"refusing cleanup of a linked or reparse run directory: {actual}"
        )
    cleanup(actual)


def execute_validation(
    preflight: ValidationPreflight,
    *,
    emit: Callable[[str], None] = _emit_line,
    run_process: Callable[..., Any] = subprocess.run,
    cleanup: Callable[[Path], None] = shutil.rmtree,
    refresh_worktrees: Callable[[], Sequence[Path]] | None = None,
) -> int:
    emit(f"repo_root={preflight.repo_root}")
    emit(f"temp_root={preflight.run_dir}")
    emit(f"available_bytes={preflight.available_bytes}")
    emit(f"available_gib={preflight.available_bytes / GIB:.2f}")
    emit(f"required_bytes={preflight.required_bytes}")
    emit(f"required_gib={preflight.required_bytes / GIB:.2f}")
    emit(f"python_executable={preflight.command[0]}")
    emit(f"python_version={platform.python_version()}")
    emit(f"pytest_command={_format_command(preflight.command)}")

    if preflight.available_bytes < preflight.required_bytes:
        raise ValidationSafetyError(
            "insufficient free space for FULL pytest before launch: "
            f"required={preflight.required_bytes} available={preflight.available_bytes} "
            f"temp_root={preflight.run_dir}"
        )

    def current_worktrees() -> tuple[Path, ...]:
        if refresh_worktrees is not None:
            return tuple(refresh_worktrees())
        return discover_worktrees(preflight.repo_root)

    preflight.temp_parent.mkdir(parents=True, exist_ok=True)
    pre_create_worktrees = current_worktrees()
    assert_outside_worktrees(
        preflight.run_dir, preflight.repo_root, pre_create_worktrees
    )
    preflight.run_dir.mkdir(parents=False, exist_ok=False)
    post_create_worktrees = current_worktrees()
    assert_outside_worktrees(
        preflight.run_dir, preflight.repo_root, post_create_worktrees
    )

    child_env = os.environ.copy()
    child_env["PYTHONUTF8"] = "1"
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env.pop("PYTEST_ADDOPTS", None)
    try:
        completed = run_process(
            list(preflight.command),
            cwd=preflight.repo_root,
            env=child_env,
            check=False,
        )
        return int(completed.returncode)
    finally:
        try:
            cleanup_run_directory(
                preflight.run_dir,
                temp_parent=preflight.temp_parent,
                run_id=preflight.run_id,
                cleanup=cleanup,
            )
            emit(f"cleanup_status=REMOVED path={preflight.run_dir}")
        except (OSError, ValidationSafetyError) as exc:
            emit(f"cleanup_status=RETAINED path={preflight.run_dir} error={exc}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--temp-root",
        help=(
            "Absolute shared parent for unique run directories. Defaults to "
            "MARKET_VAULT_TEST_TEMP_ROOT, then a safe external platform path."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo_root = discover_repo_root(Path(__file__).resolve().parent)
        worktrees = discover_worktrees(repo_root)
        run_id = new_run_id()
        temp_parent = choose_temp_parent(
            repo_root=repo_root,
            worktrees=worktrees,
            run_id=run_id,
            explicit=args.temp_root,
            env=os.environ,
        )
        preflight = build_preflight(
            repo_root=repo_root,
            temp_parent=temp_parent,
            worktrees=worktrees,
            run_id=run_id,
            python_executable=sys.executable,
        )
        return execute_validation(
            preflight,
            refresh_worktrees=lambda: discover_worktrees(repo_root),
        )
    except ValidationSafetyError as exc:
        print(f"FULL_VALIDATION_REFUSED: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"FULL_VALIDATION_ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
