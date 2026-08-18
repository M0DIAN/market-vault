"""Read-only git access: ref resolution, deterministic changed-path
extraction, exact/prefix rule matching.

This module is the generic extraction of the ref/diff mechanics that
originally shipped with the production CI audit tooling. It never
mutates the repository (no stash / reset / merge / branch operations),
never uses ``shell=True``, and fails closed on any git failure.

Diff modes:
- ``merge_base=True`` (default): three-dot merge-base diff
  ``base...head``. This is the pull_request mode: the diff is
  merge-base-correct even when the base branch has advanced.
- ``merge_base=False``: direct tree diff ``base head``. This is the
  push mode: the pushed range exactly.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Any, Callable

SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class GitError(Exception):
    """A git invocation failure with a specific fail-closed reason."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class Git:
    """Minimal read-only git wrapper. ``runner`` is injectable for tests."""

    def __init__(self, repo_dir: str = ".", runner: Callable[..., Any] | None = None):
        self.repo_dir = repo_dir
        self._run = runner if runner is not None else self._default_run

    @staticmethod
    def _default_run(cmd: list[str]) -> Any:
        env = dict(os.environ, LC_ALL="C")
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            env=env,
        )

    def _git(self, *args: str) -> str:
        proc = self._run(
            ["git", "-C", self.repo_dir, "-c", "core.quotepath=false", *args]
        )
        if proc.returncode != 0:
            raise GitError("git_error", (proc.stderr or proc.stdout or "").strip())
        return proc.stdout

    def resolve_ref(self, ref: str) -> None:
        """Fail closed when the ref does not exist in the repository."""
        self._git("rev-parse", "--verify", "--quiet", ref)

    def changed_paths(
        self, base: str, head: str, *, merge_base: bool = True
    ) -> list[str]:
        """Deterministic changed-file list between two refs.

        Renames (R<similarity>) and copies (C<similarity>) contribute
        BOTH the old and the new path, so a rename can never escape any
        classification or scope check. The result preserves git's output
        order (no set ordering). A malformed diff stream fails closed.
        """
        if merge_base:
            diff_args: list[str] = [f"{base}...{head}"]
        else:
            diff_args = [base, head]
        out = self._git("diff", "-z", "--name-status", "-M", *diff_args)
        parts = out.split("\0")
        paths: list[str] = []
        index = 0
        while index < len(parts):
            status = parts[index]
            index += 1
            if not status:
                continue
            if index >= len(parts):
                raise GitError("git_changed_paths_malformed")
            old = parts[index]
            index += 1
            paths.append(old)
            if status.startswith(("R", "C")):
                if index >= len(parts):
                    raise GitError("git_changed_paths_malformed")
                paths.append(parts[index])
                index += 1
        return paths

    def rev_list_parents(self, sha: str) -> tuple[str, ...]:
        """``git rev-list --parents -n 1 <sha>`` -> (parent, ...).

        Verifies the parsed commit identity matches the requested SHA.
        """
        out = self._git("rev-list", "--parents", "-n", "1", sha).strip()
        parts = out.split() if out else []
        if not parts or parts[0] != sha:
            raise GitError("git_commit_mismatch")
        return tuple(parts[1:])

    def rev_parse_tree(self, sha: str) -> str:
        """``git rev-parse <sha>^{tree}`` -> the tree SHA."""
        out = self._git("rev-parse", f"{sha}^{{tree}}").strip()
        if not SHA_RE.fullmatch(out):
            raise GitError("git_tree_failed")
        return out
