"""Offline tests for the read-only git wrapper using real throwaway
repositories: merge-base-correct three-dot diffs, direct push diffs,
rename old+new path extraction (including spaces and non-ASCII names),
commit topology, and fail-closed behavior on git failures."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ci_optimizer.git import Git, GitError, SHA_RE


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def write_and_commit(repo: Path, name: str, content: str, message: str) -> None:
    (repo / name).write_text(content, encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", message)


def head_of(repo: Path, ref: str = "HEAD") -> str:
    return run_git(repo, "rev-parse", ref).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    d = tmp_path / "repo"
    d.mkdir()
    run_git(d, "init", "-b", "main")
    run_git(d, "config", "user.email", "ciopt-test@example.com")
    run_git(d, "config", "user.name", "CI Opt Test")
    return d


@pytest.fixture
def g(repo: Path) -> Git:
    return Git(str(repo))


# ---------------------------------------------------------------------------
# Ref resolution.
# ---------------------------------------------------------------------------


def test_resolve_ref_existing(repo: Path, g: Git) -> None:
    write_and_commit(repo, "a.txt", "a", "init")
    assert g.resolve_ref("HEAD") is None  # returns None, no error


def test_resolve_ref_missing_fails_closed(repo: Path, g: Git) -> None:
    write_and_commit(repo, "a.txt", "a", "init")
    with pytest.raises(GitError) as exc:
        g.resolve_ref("no-such-ref")
    assert exc.value.reason == "git_error"
    # --quiet suppresses stderr; the fail-closed signal is the exit code,
    # which is what raised GitError. Non-quiet failures do surface detail.
    assert exc.value.reason == "git_error"


# ---------------------------------------------------------------------------
# Changed paths: merge-base-correct three-dot vs direct diff.
# ---------------------------------------------------------------------------


def test_changed_paths_three_dot_merge_base_correct(repo: Path, g: Git) -> None:
    # main: a.txt; branch feat: + b.txt; then main advances: + c.txt.
    write_and_commit(repo, "a.txt", "a", "base")
    run_git(repo, "checkout", "-q", "-b", "feat")
    write_and_commit(repo, "b.txt", "b", "feat work")
    run_git(repo, "checkout", "-q", "main")
    write_and_commit(repo, "c.txt", "c", "main advanced")
    main_sha = head_of(repo, "main")
    feat_sha = head_of(repo, "feat")

    # pull_request mode: merge-base-correct — only the PR's own change.
    assert g.changed_paths(main_sha, feat_sha, merge_base=True) == ["b.txt"]

    # push mode: direct tree diff — both sides of the fork appear.
    assert sorted(g.changed_paths(main_sha, feat_sha, merge_base=False)) == [
        "b.txt",
        "c.txt",
    ]


def test_changed_paths_direct_mode_reports_removed_files(repo: Path, g: Git) -> None:
    write_and_commit(repo, "keep.txt", "k", "one")
    write_and_commit(repo, "drop.txt", "d", "two")
    before = head_of(repo)
    (repo / "drop.txt").unlink()
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "drop")
    after = head_of(repo)
    assert g.changed_paths(before, after, merge_base=False) == ["drop.txt"]


# ---------------------------------------------------------------------------
# Renames: old + new paths both count (fail-closed).
# ---------------------------------------------------------------------------


def test_rename_reports_both_paths(repo: Path, g: Git) -> None:
    write_and_commit(repo, "old.txt", "x", "before")
    before = head_of(repo)
    run_git(repo, "mv", "old.txt", "new.txt")
    run_git(repo, "commit", "-q", "-m", "rename")
    after = head_of(repo)
    assert sorted(g.changed_paths(before, after, merge_base=False)) == [
        "new.txt",
        "old.txt",
    ]


def test_rename_with_spaces_reports_both_paths(repo: Path, g: Git) -> None:
    write_and_commit(repo, "my file.txt", "x", "before")
    before = head_of(repo)
    run_git(repo, "mv", "my file.txt", "renamed file.txt")
    run_git(repo, "commit", "-q", "-m", "rename with spaces")
    after = head_of(repo)
    assert sorted(g.changed_paths(before, after, merge_base=False)) == [
        "my file.txt",
        "renamed file.txt",
    ]


def test_changed_paths_unicode_preserved_without_quoting(repo: Path, g: Git) -> None:
    """core.quotepath=false is forced: UTF-8 names survive verbatim."""
    write_and_commit(repo, "café.txt", "x", "before")
    before = head_of(repo)
    write_and_commit(repo, "café.txt", "y", "edit")
    after = head_of(repo)
    assert g.changed_paths(before, after, merge_base=False) == ["café.txt"]


# ---------------------------------------------------------------------------
# Commit topology.
# ---------------------------------------------------------------------------


def test_rev_list_parents_root_commit(repo: Path, g: Git) -> None:
    write_and_commit(repo, "a.txt", "a", "root")
    root = head_of(repo)
    assert g.rev_list_parents(root) == ()


def test_rev_list_parents_single_parent(repo: Path, g: Git) -> None:
    write_and_commit(repo, "a.txt", "a", "root")
    write_and_commit(repo, "b.txt", "b", "second")
    second = head_of(repo)
    root = head_of(repo, "HEAD~1")
    assert g.rev_list_parents(second) == (root,)


def test_rev_list_parents_merge_commit_has_two(repo: Path, g: Git) -> None:
    write_and_commit(repo, "a.txt", "a", "root")
    run_git(repo, "checkout", "-q", "-b", "side")
    write_and_commit(repo, "b.txt", "b", "side work")
    run_git(repo, "checkout", "-q", "main")
    write_and_commit(repo, "c.txt", "c", "main work")
    run_git(repo, "merge", "--no-ff", "-q", "-m", "merge side", "side")
    merge_sha = head_of(repo)
    assert len(g.rev_list_parents(merge_sha)) == 2


def test_rev_parse_tree_returns_sha(repo: Path, g: Git) -> None:
    write_and_commit(repo, "a.txt", "a", "root")
    sha = head_of(repo)
    tree = g.rev_parse_tree(sha)
    assert SHA_RE.fullmatch(tree)
    assert tree == head_of(repo, "HEAD^{tree}")


def test_rev_parse_tree_fails_closed_on_bad_sha(repo: Path, g: Git) -> None:
    with pytest.raises(GitError) as exc:
        g.rev_parse_tree("not-a-sha")
    assert exc.value.reason == "git_error"


# ---------------------------------------------------------------------------
# Malformed diff stream / runner failures fail closed.
# ---------------------------------------------------------------------------


class FakeProc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def fake_git(proc: FakeProc) -> Git:
    return Git(repo_dir=".", runner=lambda cmd: proc)


def test_malformed_diff_stream_raises() -> None:
    # "R100\0old" without a trailing NUL: the rename target is missing.
    g = fake_git(FakeProc(0, "R100\0old"))
    with pytest.raises(GitError) as exc:
        g.changed_paths("a" * 40, "b" * 40, merge_base=False)
    assert exc.value.reason == "git_changed_paths_malformed"


def test_git_failure_fails_closed() -> None:
    g = fake_git(FakeProc(1, "", "fatal: unknown revision"))
    with pytest.raises(GitError) as exc:
        g.changed_paths("a" * 40, "b" * 40, merge_base=False)
    assert exc.value.reason == "git_error"


def test_rev_list_parents_identity_mismatch_raises() -> None:
    g = fake_git(FakeProc(0, f"{'e' * 40} {'a' * 40}"))
    with pytest.raises(GitError) as exc:
        g.rev_list_parents("c" * 40)
    assert exc.value.reason == "git_commit_mismatch"


def test_rev_parse_tree_garbage_output_raises() -> None:
    g = fake_git(FakeProc(0, "not-a-sha"))
    with pytest.raises(GitError) as exc:
        g.rev_parse_tree("c" * 40)
    assert exc.value.reason == "git_tree_failed"
