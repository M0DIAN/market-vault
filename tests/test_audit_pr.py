"""Focused tests for the automated PR scope audit (DP2).

Tests run the script against small temporary git repositories; the
MarketVault repository itself is never used as a fixture. The suite is
designed to stay in the seconds range (no whole-repo copies).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_pr.py"

GIT_ENV = dict(
    os.environ,
    GIT_AUTHOR_NAME="Audit Test",
    GIT_AUTHOR_EMAIL="audit@example.com",
    GIT_COMMITTER_NAME="Audit Test",
    GIT_COMMITTER_EMAIL="audit@example.com",
)


def run_git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        env=GIT_ENV,
    )
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc.stdout


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-q")
    return repo


def commit_all(repo: Path, message: str) -> str:
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", message)
    return run_git(repo, "rev-parse", "HEAD").strip()


def write_file(repo: Path, name: str, content: str = "x\n") -> None:
    target = repo / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def run_audit(repo: Path, base: str, head: str, *allow: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPT), "--repo", str(repo), "--base", base, "--head", head]
    for rule in allow:
        cmd += ["--allow", rule]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_exact_allowed_file_pass(tmp_path):
    repo = make_repo(tmp_path)
    write_file(repo, "a.txt")
    base = commit_all(repo, "base")
    write_file(repo, "a.txt", "changed\n")
    head = commit_all(repo, "head")

    result = run_audit(repo, base, head, "a.txt")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "AUDIT_PR_OK" in result.stdout
    assert "changed_files=1" in result.stdout
    assert "docs_only=false" in result.stdout
    assert "scope=PASS" in result.stdout


def test_allowed_directory_prefix_pass(tmp_path):
    repo = make_repo(tmp_path)
    write_file(repo, "dir/nested/f.txt")
    base = commit_all(repo, "base")
    write_file(repo, "dir/nested/f.txt", "changed\n")
    head = commit_all(repo, "head")

    result = run_audit(repo, base, head, "dir/")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "AUDIT_PR_OK" in result.stdout
    assert "scope=PASS" in result.stdout


def test_allow_rule_does_not_fuzzy_match(tmp_path):
    """--allow script must NOT match scripts/audit_pr.py."""
    repo = make_repo(tmp_path)
    write_file(repo, "scripts/audit_pr.py")
    base = commit_all(repo, "base")
    write_file(repo, "scripts/audit_pr.py", "changed\n")
    head = commit_all(repo, "head")

    result = run_audit(repo, base, head, "script")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "AUDIT_PR_FAILED" in result.stdout
    assert "- scripts/audit_pr.py" in result.stdout
    assert "scope=FAIL" in result.stdout


def test_unauthorized_path_fail(tmp_path):
    repo = make_repo(tmp_path)
    write_file(repo, "a.txt")
    base = commit_all(repo, "base")
    write_file(repo, "b.txt")
    head = commit_all(repo, "head")

    result = run_audit(repo, base, head, "a.txt")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "AUDIT_PR_FAILED" in result.stdout
    assert "scope violations:" in result.stdout
    assert "- b.txt" in result.stdout
    assert "scope=FAIL" in result.stdout


def test_multiple_violations_reported_together(tmp_path):
    repo = make_repo(tmp_path)
    write_file(repo, "a.txt")
    write_file(repo, "b.txt")
    write_file(repo, "c.txt")
    base = commit_all(repo, "base")
    write_file(repo, "a.txt", "ok\n")
    write_file(repo, "b.txt", "bad\n")
    write_file(repo, "c.txt", "bad\n")
    head = commit_all(repo, "head")

    result = run_audit(repo, base, head, "a.txt")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "AUDIT_PR_FAILED" in result.stdout
    assert "changed_files=3" in result.stdout
    assert "- b.txt" in result.stdout
    assert "- c.txt" in result.stdout
    assert "scope=FAIL" in result.stdout
    assert "- a.txt" not in result.stdout[result.stdout.index("scope violations:"):]


def test_surface_flags_detected(tmp_path):
    """product_src / pyproject / workflow / tests detection, docs_only false."""
    repo = make_repo(tmp_path)
    write_file(repo, "src/market_vault/thing.py")
    write_file(repo, "pyproject.toml")
    write_file(repo, ".github/workflows/ci.yml")
    write_file(repo, "tests/test_thing.py")
    base = commit_all(repo, "base")
    write_file(repo, "src/market_vault/thing.py", "changed\n")
    write_file(repo, "pyproject.toml", "changed\n")
    write_file(repo, ".github/workflows/ci.yml", "changed\n")
    write_file(repo, "tests/test_thing.py", "changed\n")
    head = commit_all(repo, "head")

    result = run_audit(
        repo, base, head,
        "src/market_vault/", "pyproject.toml", ".github/workflows/", "tests/",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "product_src_changed=true" in result.stdout
    assert "pyproject_changed=true" in result.stdout
    assert "workflow_changed=true" in result.stdout
    assert "tests_changed=true" in result.stdout
    assert "docs_only=false" in result.stdout


def test_docs_only_true(tmp_path):
    repo = make_repo(tmp_path)
    write_file(repo, "README.md")
    write_file(repo, "docs/guide.md")
    write_file(repo, "docs/sub/page.md")
    base = commit_all(repo, "base")
    write_file(repo, "README.md", "changed\n")
    write_file(repo, "docs/guide.md", "changed\n")
    write_file(repo, "docs/sub/page.md", "changed\n")
    head = commit_all(repo, "head")

    result = run_audit(repo, base, head, "README.md", "docs/")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "changed_files=3" in result.stdout
    assert "docs_only=true" in result.stdout


def test_docs_only_false_for_non_doc_path(tmp_path):
    """A .md file plus a non-doc file is NOT docs-only."""
    repo = make_repo(tmp_path)
    write_file(repo, "README.md")
    write_file(repo, "notes.txt")
    base = commit_all(repo, "base")
    write_file(repo, "README.md", "changed\n")
    write_file(repo, "notes.txt", "changed\n")
    head = commit_all(repo, "head")

    result = run_audit(repo, base, head, "README.md", "notes.txt")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "docs_only=false" in result.stdout


def test_docs_only_false_for_doc_named_file(tmp_path):
    """A file named *documentation* is not docs just because of its name."""
    repo = make_repo(tmp_path)
    write_file(repo, "documentation.py")
    base = commit_all(repo, "base")
    write_file(repo, "documentation.py", "changed\n")
    head = commit_all(repo, "head")

    result = run_audit(repo, base, head, "documentation.py")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "docs_only=false" in result.stdout


def test_empty_diff_pass(tmp_path):
    repo = make_repo(tmp_path)
    write_file(repo, "a.txt")
    base = commit_all(repo, "base")

    result = run_audit(repo, base, base)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "AUDIT_PR_OK" in result.stdout
    assert "changed_files=0" in result.stdout
    assert "docs_only=false" in result.stdout
    assert "scope=PASS" in result.stdout


def test_invalid_base_fail_closed(tmp_path):
    repo = make_repo(tmp_path)
    write_file(repo, "a.txt")
    head = commit_all(repo, "base")

    result = run_audit(repo, "0" * 40, head)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "AUDIT_PR_FAILED" in result.stdout
    assert "error=" in result.stdout
    assert "AUDIT_PR_OK" not in result.stdout


def test_invalid_head_fail_closed(tmp_path):
    repo = make_repo(tmp_path)
    write_file(repo, "a.txt")
    base = commit_all(repo, "base")

    result = run_audit(repo, base, "0" * 40)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "AUDIT_PR_FAILED" in result.stdout
    assert "error=" in result.stdout
    assert "AUDIT_PR_OK" not in result.stdout


def test_rename_into_unauthorized_path_fail(tmp_path):
    """Rename must not escape the scope audit: both old and new path count."""
    repo = make_repo(tmp_path)
    write_file(repo, "allowed.txt")
    base = commit_all(repo, "base")
    run_git(repo, "mv", "allowed.txt", "forbidden.txt")
    head = commit_all(repo, "head")

    result = run_audit(repo, base, head, "allowed.txt")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "AUDIT_PR_FAILED" in result.stdout
    assert "changed_files=2" in result.stdout
    assert "- allowed.txt" in result.stdout
    assert "- forbidden.txt" in result.stdout
    assert "scope violations:" in result.stdout
    assert "- forbidden.txt" in result.stdout
    assert "scope=FAIL" in result.stdout


def test_rename_within_allowed_paths_pass(tmp_path):
    """A fully allowed rename passes and reports both old and new paths."""
    repo = make_repo(tmp_path)
    write_file(repo, "allowed.txt")
    base = commit_all(repo, "base")
    # git mv does not create leading directories for the destination
    (repo / "sub").mkdir()
    run_git(repo, "mv", "allowed.txt", "sub/allowed.txt")
    head = commit_all(repo, "head")

    result = run_audit(repo, base, head, "allowed.txt", "sub/")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "AUDIT_PR_OK" in result.stdout
    assert "changed_files=2" in result.stdout
    assert "- allowed.txt" in result.stdout
    assert "- sub/allowed.txt" in result.stdout
    assert "scope=PASS" in result.stdout


def test_no_allow_rules_fail_closed(tmp_path):
    """With no allow rules, any changed file is a violation."""
    repo = make_repo(tmp_path)
    write_file(repo, "a.txt")
    base = commit_all(repo, "base")
    write_file(repo, "a.txt", "changed\n")
    head = commit_all(repo, "head")

    result = run_audit(repo, base, head)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "AUDIT_PR_FAILED" in result.stdout
    assert "- a.txt" in result.stdout
    assert "scope=FAIL" in result.stdout
