"""Focused tests for the CI risk-tier classifier (Phase 1).

Tests run the classifier against small temporary git repositories; the
MarketVault repository itself is never used as a fixture. The suite is
designed to stay in the seconds range (no whole-repo copies).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci_risk_tier.py"

GIT_ENV = dict(
    os.environ,
    GIT_AUTHOR_NAME="Tier Test",
    GIT_AUTHOR_EMAIL="tier@example.com",
    GIT_COMMITTER_NAME="Tier Test",
    GIT_COMMITTER_EMAIL="tier@example.com",
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


def run_classifier(
    repo: Path, base: str, head: str, mode: str = "pull_request"
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo),
         "--mode", mode, "--base", base, "--head", head],
        capture_output=True,
        text=True,
    )


def tier_of(result: subprocess.CompletedProcess) -> str:
    for line in result.stdout.splitlines():
        if line.startswith("tier="):
            return line.split("=", 1)[1]
    pytest.fail(f"no tier= line in output: {result.stdout!r}")


def classify_change(
    repo: Path,
    path: str,
    content: str = "x\n",
    changed_content: str = "changed\n",
) -> str:
    """Change one path between two commits and return the tier."""
    write_file(repo, path, content)
    base = commit_all(repo, "base")
    write_file(repo, path, changed_content)
    head = commit_all(repo, "head")
    result = run_classifier(repo, base, head)
    assert result.returncode == 0, result.stdout + result.stderr
    return tier_of(result)


def classify_changes(repo: Path, paths: list[str]) -> str:
    """Change several paths between two commits and return the tier."""
    for path in paths:
        write_file(repo, path)
    base = commit_all(repo, "base")
    for path in paths:
        write_file(repo, path, "changed\n")
    head = commit_all(repo, "head")

    result = run_classifier(repo, base, head)

    assert result.returncode == 0, result.stdout + result.stderr
    return tier_of(result)


def test_docs_dir_only_docs_fast(tmp_path):
    repo = make_repo(tmp_path)
    assert classify_change(repo, "docs/guide.md") == "docs_fast"


def test_playbook_only_docs_fast(tmp_path):
    repo = make_repo(tmp_path)
    assert classify_change(repo, "DEVELOPMENT_PLAYBOOK.md") == "docs_fast"


def test_multiple_policy_docs_docs_fast(tmp_path):
    repo = make_repo(tmp_path)
    write_file(repo, "AGENT_HANDOFF.md")
    write_file(repo, "RELEASE_PLAYBOOK.md")
    write_file(repo, "docs/sub/page.md")
    base = commit_all(repo, "base")
    write_file(repo, "AGENT_HANDOFF.md", "changed\n")
    write_file(repo, "RELEASE_PLAYBOOK.md", "changed\n")
    write_file(repo, "docs/sub/page.md", "changed\n")
    head = commit_all(repo, "head")

    result = run_classifier(repo, base, head)

    assert result.returncode == 0, result.stdout + result.stderr
    assert tier_of(result) == "docs_fast"
    assert "changed_files=3" in result.stdout


def test_readme_only_package_docs(tmp_path):
    repo = make_repo(tmp_path)
    assert classify_change(repo, "README.md") == "package_docs"


def test_readme_plus_docs_package_docs(tmp_path):
    repo = make_repo(tmp_path)
    write_file(repo, "README.md")
    write_file(repo, "docs/guide.md")
    base = commit_all(repo, "base")
    write_file(repo, "README.md", "changed\n")
    write_file(repo, "docs/guide.md", "changed\n")
    head = commit_all(repo, "head")

    result = run_classifier(repo, base, head)

    assert result.returncode == 0, result.stdout + result.stderr
    assert tier_of(result) == "package_docs"
    assert "reason=readme_changed_in_docs_scope" in result.stdout


def test_src_change_full(tmp_path):
    repo = make_repo(tmp_path)
    assert classify_change(repo, "src/market_vault/thing.py") == "full"


def test_tests_change_full(tmp_path):
    repo = make_repo(tmp_path)
    assert classify_change(repo, "tests/test_thing.py") == "full"


def test_scripts_change_full(tmp_path):
    repo = make_repo(tmp_path)
    assert classify_change(repo, "scripts/foo.py") == "full"


def test_pyproject_change_full(tmp_path):
    repo = make_repo(tmp_path)
    assert classify_change(repo, "pyproject.toml") == "full"


def test_ci_workflow_only_control_plane(tmp_path):
    """A ci.yml-only change classifies control_plane: a validated subset
    that never requires the full matrix."""
    repo = make_repo(tmp_path)
    write_file(repo, ".github/workflows/ci.yml")
    base = commit_all(repo, "base")
    write_file(repo, ".github/workflows/ci.yml", "changed\n")
    head = commit_all(repo, "head")

    result = run_classifier(repo, base, head)

    assert result.returncode == 0, result.stdout + result.stderr
    assert tier_of(result) == "control_plane"
    assert "reason=all_changes_in_control_plane_scope" in result.stdout
    assert "full_matrix_required=false" in result.stdout


CONTROL_PLANE_ELIGIBLE_PATHS = [
    "scripts/ci_risk_tier.py",
    "scripts/ci_post_merge_reuse.py",
    "scripts/audit_pr.py",
    "scripts/check_release.py",
    "ci/components.toml",
    "tests/test_ci_risk_tier.py",
    "tests/test_component_aware_tiers.py",
    "tests/test_ci_post_merge_reuse.py",
    "tests/test_audit_pr.py",
    "tests/test_v061_ci_auditability.py",
]


VALID_REGISTRY = """\
[components.core]
paths = ["src/market_vault/"]

[components.package]
paths = ["pyproject.toml", "README.md"]
"""


@pytest.mark.parametrize("path", CONTROL_PLANE_ELIGIBLE_PATHS)
def test_control_plane_eligible_path_only(tmp_path, path):
    """Every allowlisted control-plane path alone classifies control_plane."""
    repo = make_repo(tmp_path)
    if path == "ci/components.toml":
        # The classifier parses ci/components.toml, so both commits must
        # hold valid TOML for the path to be eligible.
        changed = VALID_REGISTRY + "# changed\n"
        assert classify_change(
            repo, path, content=VALID_REGISTRY, changed_content=changed
        ) == "control_plane"
    else:
        assert classify_change(repo, path) == "control_plane"


def test_control_plane_plus_docs_control_plane(tmp_path):
    """control_plane mixed with docs stays control_plane (CP + docs scope)."""
    repo = make_repo(tmp_path)
    assert classify_changes(
        repo, [".github/workflows/ci.yml", "docs/guide.md"]
    ) == "control_plane"


def test_control_plane_plus_playbook_control_plane(tmp_path):
    """DEVELOPMENT_PLAYBOOK.md is in the docs scope, so the mix is valid."""
    repo = make_repo(tmp_path)
    assert classify_changes(
        repo, [".github/workflows/ci.yml", "DEVELOPMENT_PLAYBOOK.md"]
    ) == "control_plane"


def test_control_plane_plus_readme_full(tmp_path):
    """README is outside CP + docs: the mixed change must be FULL."""
    repo = make_repo(tmp_path)
    assert classify_changes(repo, [".github/workflows/ci.yml", "README.md"]) == "full"


def test_control_plane_plus_pyproject_full(tmp_path):
    """pyproject.toml is a shared/package-schema path: FULL."""
    repo = make_repo(tmp_path)
    assert classify_changes(
        repo, [".github/workflows/ci.yml", "pyproject.toml"]
    ) == "full"


def test_control_plane_plus_src_full(tmp_path):
    """A src/ change mixed with control-plane paths must be FULL."""
    repo = make_repo(tmp_path)
    assert classify_changes(
        repo, [".github/workflows/ci.yml", "src/market_vault/thing.py"]
    ) == "full"


def test_control_plane_plus_release_test_full(tmp_path):
    """tests/test_release_v061.py is deliberately NOT control-plane eligible."""
    repo = make_repo(tmp_path)
    assert classify_changes(
        repo, [".github/workflows/ci.yml", "tests/test_release_v061.py"]
    ) == "full"


def test_control_plane_plus_repo_hygiene_full(tmp_path):
    """scripts/check_repo_hygiene.py is outside the control-plane allowlist."""
    repo = make_repo(tmp_path)
    assert classify_changes(
        repo, [".github/workflows/ci.yml", "scripts/check_repo_hygiene.py"]
    ) == "full"


def test_control_plane_plus_other_workflow_full(tmp_path):
    """Only ci.yml is control-plane eligible; other workflows stay FULL."""
    repo = make_repo(tmp_path)
    assert classify_changes(
        repo, [".github/workflows/ci.yml", ".github/workflows/release.yml"]
    ) == "full"


# P1-1 (PR #75): the Python 3.14 compatibility surface contract
# (ci/python314_compatibility_surface.txt, scripts/ci_python314_surface.py,
# tests/test_python314_compatibility_surface.py) is in CONTROL_RULES but
# INTENTIONALLY NOT in CONTROL_PLANE_SCOPE_RULES: any change touching the
# surface must force FULL and must never classify as the validated
# control_plane subset tier.
PY314_SURFACE_PATHS = [
    "ci/python314_compatibility_surface.txt",
    "scripts/ci_python314_surface.py",
    "tests/test_python314_compatibility_surface.py",
]


@pytest.mark.parametrize("path", PY314_SURFACE_PATHS)
def test_py314_surface_path_alone_full(tmp_path, path):
    """A surface contract change alone forces FULL (shared control rule)."""
    repo = make_repo(tmp_path)
    assert classify_change(repo, path) == "full"


@pytest.mark.parametrize("path", PY314_SURFACE_PATHS)
def test_py314_surface_path_not_control_plane_eligible(tmp_path, path):
    """A surface path is NOT in the control-plane allowlist: mixed with
    ci.yml the change must stay FULL, never control_plane."""
    repo = make_repo(tmp_path)
    assert classify_changes(
        repo, [".github/workflows/ci.yml", path]
    ) == "full"


def test_py314_surface_manifest_plus_ci_yml_full_reason(tmp_path):
    """manifest + ci.yml classifies FULL with the shared-mutation reason."""
    repo = make_repo(tmp_path)
    write_file(repo, ".github/workflows/ci.yml")
    write_file(repo, "ci/python314_compatibility_surface.txt")
    base = commit_all(repo, "base")
    write_file(repo, ".github/workflows/ci.yml", "changed\n")
    write_file(repo, "ci/python314_compatibility_surface.txt", "changed\n")
    head = commit_all(repo, "head")

    result = run_classifier(repo, base, head)

    assert result.returncode == 0, result.stdout + result.stderr
    assert tier_of(result) == "full"
    assert "reason=workflow_or_registry_mutation_requires_full" in result.stdout


def test_rename_py314_surface_validator_full(tmp_path):
    """Renaming scripts/ci_python314_surface.py classifies FULL via both
    paths (the old control-rule path and the unknown new path)."""
    repo = make_repo(tmp_path)
    write_file(repo, "scripts/ci_python314_surface.py")
    base = commit_all(repo, "base")
    (repo / "scripts" / "moved").mkdir(parents=True)
    run_git(repo, "mv", "scripts/ci_python314_surface.py",
            "scripts/moved/surface_validator.py")
    head = commit_all(repo, "head")

    result = run_classifier(repo, base, head)

    assert result.returncode == 0, result.stdout + result.stderr
    assert tier_of(result) == "full"
    assert "changed_files=2" in result.stdout


def test_rename_eligible_to_unknown_full(tmp_path):
    """Renaming a control-plane path to an unknown path must classify FULL."""
    repo = make_repo(tmp_path)
    write_file(repo, ".github/workflows/ci.yml")
    base = commit_all(repo, "base")
    run_git(repo, "mv", ".github/workflows/ci.yml", "notes.txt")
    head = commit_all(repo, "head")

    result = run_classifier(repo, base, head)

    assert result.returncode == 0, result.stdout + result.stderr
    assert tier_of(result) == "full"


def test_rename_unknown_to_eligible_full(tmp_path):
    """Renaming an unknown path into the allowlist stays FULL: the old path
    participates in the diff."""
    repo = make_repo(tmp_path)
    write_file(repo, "notes.txt")
    base = commit_all(repo, "base")
    # git mv does not create leading directories for the destination
    (repo / ".github" / "workflows").mkdir(parents=True)
    run_git(repo, "mv", "notes.txt", ".github/workflows/ci.yml")
    head = commit_all(repo, "head")

    result = run_classifier(repo, base, head)

    assert result.returncode == 0, result.stdout + result.stderr
    assert tier_of(result) == "full"


def test_invalid_registry_fail_closed_full(tmp_path):
    """A malformed component registry must fail closed to FULL."""
    repo = make_repo(tmp_path)
    write_file(repo, "docs/guide.md")
    write_file(repo, "ci/components.toml", "not a toml = [\n")
    base = commit_all(repo, "base")
    write_file(repo, "docs/guide.md", "changed\n")
    head = commit_all(repo, "head")

    result = run_classifier(repo, base, head)

    assert result.returncode == 2, result.stdout + result.stderr
    assert tier_of(result) == "full"
    assert "reason=invalid_registry_fail_closed" in result.stdout


def test_docs_and_src_mixed_full(tmp_path):
    repo = make_repo(tmp_path)
    write_file(repo, "docs/guide.md")
    write_file(repo, "src/market_vault/thing.py")
    base = commit_all(repo, "base")
    write_file(repo, "docs/guide.md", "changed\n")
    write_file(repo, "src/market_vault/thing.py", "changed\n")
    head = commit_all(repo, "head")

    result = run_classifier(repo, base, head)

    assert result.returncode == 0, result.stdout + result.stderr
    assert tier_of(result) == "full"
    assert "reason=changed_path_not_in_docs_scope" in result.stdout


def test_unknown_root_file_full(tmp_path):
    repo = make_repo(tmp_path)
    assert classify_change(repo, "notes.txt") == "full"


def test_rename_docs_to_src_full(tmp_path):
    """Rename out of the docs scope must classify as full via both paths."""
    repo = make_repo(tmp_path)
    write_file(repo, "docs/old.md")
    base = commit_all(repo, "base")
    # git mv does not create leading directories for the destination
    (repo / "src").mkdir()
    run_git(repo, "mv", "docs/old.md", "src/old.md")
    head = commit_all(repo, "head")

    result = run_classifier(repo, base, head)

    assert result.returncode == 0, result.stdout + result.stderr
    assert tier_of(result) == "full"
    assert "changed_files=2" in result.stdout
    assert "- docs/old.md" in result.stdout
    assert "- src/old.md" in result.stdout


def test_rename_within_docs_scope_docs_fast(tmp_path):
    """A rename fully inside the docs scope stays docs_fast."""
    repo = make_repo(tmp_path)
    write_file(repo, "docs/old.md")
    base = commit_all(repo, "base")
    (repo / "docs" / "sub").mkdir(parents=True)
    run_git(repo, "mv", "docs/old.md", "docs/sub/new.md")
    head = commit_all(repo, "head")

    result = run_classifier(repo, base, head)

    assert result.returncode == 0, result.stdout + result.stderr
    assert tier_of(result) == "docs_fast"
    assert "changed_files=2" in result.stdout


def test_invalid_base_error_fail_closed(tmp_path):
    repo = make_repo(tmp_path)
    write_file(repo, "docs/guide.md")
    head = commit_all(repo, "base")

    result = run_classifier(repo, "0" * 40, head)

    assert result.returncode == 2, result.stdout + result.stderr
    assert tier_of(result) == "full"
    assert "reason=classifier_error_fail_closed" in result.stdout


def test_empty_diff_full(tmp_path):
    repo = make_repo(tmp_path)
    write_file(repo, "docs/guide.md")
    base = commit_all(repo, "base")

    result = run_classifier(repo, base, base)

    assert result.returncode == 0, result.stdout + result.stderr
    assert tier_of(result) == "full"
    assert "reason=empty_diff" in result.stdout
    assert "changed_files=0" in result.stdout


def test_pull_request_merge_base_vs_push_direct_semantics(tmp_path):
    """pull_request uses the merge-base diff; push uses the direct diff.

    Main advances (README change) after the feature branched. The PR's
    own changes are docs-only, so pull_request classifies docs_fast;
    the direct pushed-range diff includes main's README change, so the
    push mode classifies package_docs.
    """
    repo = make_repo(tmp_path)
    write_file(repo, "README.md")
    base = commit_all(repo, "base")  # c1
    write_file(repo, "docs/x.md")
    head_feature = commit_all(repo, "feature")  # c2
    run_git(repo, "checkout", "-q", "-b", "mainline", base)
    write_file(repo, "README.md", "changed\n")
    head_main = commit_all(repo, "mainline")  # c3

    pr = run_classifier(repo, head_main, head_feature, mode="pull_request")
    push = run_classifier(repo, head_main, head_feature, mode="push")

    assert pr.returncode == 0, pr.stdout + pr.stderr
    assert tier_of(pr) == "docs_fast"
    assert push.returncode == 0, push.stdout + push.stderr
    assert tier_of(push) == "package_docs"
