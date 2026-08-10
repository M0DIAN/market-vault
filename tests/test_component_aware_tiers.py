"""Focused tests for the component-aware classifier foundation (DP4).

The component-aware foundation is additive to the Phase 1 tier model:
ci/components.toml registers component path surfaces, and the classifier
emits component impact (components=, core_changed=, package_changed=,
unknown_changed=, shared_changed=, independent_only=,
full_matrix_required=) while no registered component makes anything
faster. The tier model is docs_fast / package_docs / control_plane /
full (P1-2, PR #71): control_plane is a validated SUBSET tier driven by
the allowlist in scripts/ci_risk_tier.py, NOT by the registry — no
registry component can make a change control_plane.

Tests run the classifier against small temporary git repositories with
a minimal ci/components.toml; the MarketVault repository itself is never
used as a fixture. The suite is designed to stay in the seconds range.
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
    GIT_AUTHOR_NAME="Component Test",
    GIT_AUTHOR_EMAIL="component@example.com",
    GIT_COMMITTER_NAME="Component Test",
    GIT_COMMITTER_EMAIL="component@example.com",
)

# The repository's real registry (kept in sync with ci/components.toml).
REAL_REGISTRY = """\
[components.core]
paths = ["src/market_vault/"]
requires_core_full = true

[components.package]
paths = ["pyproject.toml", "README.md"]
requires_package = true
"""

# A hypothetical independent component, used to prove the mechanism can
# express a component-only classification (no such component is
# registered in the real repository).
INDEPENDENT_REGISTRY = """\
[components.widgets]
paths = ["widgets/"]
requires_core_full = false
requires_package = false
"""


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


def write_registry(repo: Path, text: str) -> None:
    write_file(repo, "ci/components.toml", text)


def run_classifier(
    repo: Path, base: str, head: str, mode: str = "pull_request"
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo),
         "--mode", mode, "--base", base, "--head", head],
        capture_output=True,
        text=True,
    )


def line_value(result: subprocess.CompletedProcess, key: str) -> str:
    for line in result.stdout.splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    pytest.fail(f"no {key}= line in output: {result.stdout!r}")


def classify_change(
    repo: Path, path: str, registry: str | None = REAL_REGISTRY
) -> subprocess.CompletedProcess:
    """Change one path between two commits and return the result."""
    if registry is not None:
        write_registry(repo, registry)
    write_file(repo, path)
    base = commit_all(repo, "base")
    write_file(repo, path, "changed\n")
    head = commit_all(repo, "head")
    result = run_classifier(repo, base, head)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def tier(result: subprocess.CompletedProcess) -> str:
    return line_value(result, "tier")


# ---------------------------------------------------------------------------
# Phase 1 tiers unchanged under the real registry.
# ---------------------------------------------------------------------------


def test_docs_only_stays_docs_fast_with_registry(tmp_path):
    repo = make_repo(tmp_path)
    result = classify_change(repo, "docs/guide.md")

    assert tier(result) == "docs_fast"
    assert line_value(result, "components") == "none"
    assert line_value(result, "core_changed") == "false"
    assert line_value(result, "package_changed") == "false"
    assert line_value(result, "unknown_changed") == "false"
    assert line_value(result, "shared_changed") == "false"
    assert line_value(result, "independent_only") == "false"
    assert line_value(result, "full_matrix_required") == "false"


def test_package_sensitive_docs_stays_package_docs_with_registry(tmp_path):
    repo = make_repo(tmp_path)
    write_registry(repo, REAL_REGISTRY)
    write_file(repo, "README.md")
    write_file(repo, "docs/guide.md")
    base = commit_all(repo, "base")
    write_file(repo, "README.md", "changed\n")
    write_file(repo, "docs/guide.md", "changed\n")
    head = commit_all(repo, "head")
    result = run_classifier(repo, base, head)

    assert result.returncode == 0, result.stdout + result.stderr
    assert tier(result) == "package_docs"
    assert line_value(result, "reason") == "readme_changed_in_docs_scope"
    assert line_value(result, "components") == "package"
    assert line_value(result, "package_changed") == "true"
    assert line_value(result, "core_changed") == "false"
    assert line_value(result, "full_matrix_required") == "false"


# ---------------------------------------------------------------------------
# Component impact under the real registry.
# ---------------------------------------------------------------------------


def test_core_path_full_and_core_changed(tmp_path):
    repo = make_repo(tmp_path)
    result = classify_change(repo, "src/market_vault/thing.py")

    assert tier(result) == "full"
    assert line_value(result, "reason") == "core_component_requires_full"
    assert line_value(result, "components") == "core"
    assert line_value(result, "core_changed") == "true"
    assert line_value(result, "unknown_changed") == "false"
    assert line_value(result, "independent_only") == "false"
    assert line_value(result, "full_matrix_required") == "true"


def test_unknown_path_full_and_unknown_changed(tmp_path):
    repo = make_repo(tmp_path)
    result = classify_change(repo, "notes.txt")

    assert tier(result) == "full"
    assert line_value(result, "reason") == "changed_path_not_in_docs_scope"
    assert line_value(result, "unknown_changed") == "true"
    assert line_value(result, "components") == "none"
    assert line_value(result, "full_matrix_required") == "true"


def test_package_schema_full_and_shared_changed(tmp_path):
    """pyproject.toml is the package schema: a control-plane mutation.

    Future-rule condition 4: a component may not skip the core full
    matrix when it modifies package / workflow / shared schema.
    """
    repo = make_repo(tmp_path)
    result = classify_change(repo, "pyproject.toml")

    assert tier(result) == "full"
    assert line_value(result, "reason") == "workflow_or_registry_mutation_requires_full"
    assert line_value(result, "shared_changed") == "true"
    assert line_value(result, "components") == "package"
    assert line_value(result, "package_changed") == "true"
    assert line_value(result, "full_matrix_required") == "true"


def test_ci_workflow_control_plane_subset(tmp_path):
    """ci.yml is the allowlisted control-plane path: validated subset.

    The control-plane branch runs BEFORE the generic shared_changed FULL
    check, so shared_changed stays true as impact information while the
    tier is control_plane with full_matrix_required=false.
    """
    repo = make_repo(tmp_path)
    result = classify_change(repo, ".github/workflows/ci.yml")

    assert tier(result) == "control_plane"
    assert line_value(result, "reason") == "all_changes_in_control_plane_scope"
    assert line_value(result, "shared_changed") == "true"
    assert line_value(result, "full_matrix_required") == "false"


def test_registry_mutation_control_plane_subset(tmp_path):
    """ci/components.toml is allowlisted: mutating it with docs is
    control_plane, not the generic shared-mutation FULL."""
    repo = make_repo(tmp_path)
    write_registry(repo, REAL_REGISTRY)
    write_file(repo, "docs/guide.md")
    base = commit_all(repo, "base")
    write_file(repo, "ci/components.toml", REAL_REGISTRY + "\n")
    head = commit_all(repo, "head")
    result = run_classifier(repo, base, head)

    assert result.returncode == 0, result.stdout + result.stderr
    assert tier(result) == "control_plane"
    assert line_value(result, "reason") == "all_changes_in_control_plane_scope"
    assert line_value(result, "shared_changed") == "true"
    assert line_value(result, "full_matrix_required") == "false"


# ---------------------------------------------------------------------------
# Independent component classification (mechanism proof).
# ---------------------------------------------------------------------------


def test_registered_independent_component_component_only(tmp_path):
    """A registered independent component classifies component-only.

    independent_only=true is eligibility/impact information only: the
    changed paths are structurally isolated to a registered non-core /
    non-package / non-shared component. It does NOT authorize skipping
    the core full matrix: without an explicit validation contract the
    tier stays FULL and full_matrix_required stays true (it reflects
    the currently ACTIVE policy). Only a future PR registering explicit
    component validation may flip full_matrix_required to false.
    """
    repo = make_repo(tmp_path)
    result = classify_change(repo, "widgets/thing.py", registry=INDEPENDENT_REGISTRY)

    assert tier(result) == "full"
    assert line_value(result, "reason") == "component_without_validation_requires_full"
    assert line_value(result, "components") == "widgets"
    assert line_value(result, "core_changed") == "false"
    assert line_value(result, "package_changed") == "false"
    assert line_value(result, "unknown_changed") == "false"
    assert line_value(result, "shared_changed") == "false"
    assert line_value(result, "independent_only") == "true"
    assert line_value(result, "full_matrix_required") == "true"


def test_known_component_plus_core_full(tmp_path):
    repo = make_repo(tmp_path)
    write_registry(repo, INDEPENDENT_REGISTRY + REAL_REGISTRY)
    write_file(repo, "widgets/thing.py")
    write_file(repo, "src/market_vault/core.py")
    base = commit_all(repo, "base")
    write_file(repo, "widgets/thing.py", "changed\n")
    write_file(repo, "src/market_vault/core.py", "changed\n")
    head = commit_all(repo, "head")
    result = run_classifier(repo, base, head)

    assert result.returncode == 0, result.stdout + result.stderr
    assert tier(result) == "full"
    assert line_value(result, "reason") == "core_component_requires_full"
    assert line_value(result, "components") == "core,widgets"
    assert line_value(result, "core_changed") == "true"
    assert line_value(result, "independent_only") == "false"
    assert line_value(result, "full_matrix_required") == "true"


def test_component_plus_workflow_full(tmp_path):
    repo = make_repo(tmp_path)
    write_registry(repo, INDEPENDENT_REGISTRY)
    write_file(repo, "widgets/thing.py")
    write_file(repo, ".github/workflows/release.yml")
    base = commit_all(repo, "base")
    write_file(repo, "widgets/thing.py", "changed\n")
    write_file(repo, ".github/workflows/release.yml", "changed\n")
    head = commit_all(repo, "head")
    result = run_classifier(repo, base, head)

    assert result.returncode == 0, result.stdout + result.stderr
    assert tier(result) == "full"
    assert line_value(result, "reason") == "workflow_or_registry_mutation_requires_full"
    assert line_value(result, "components") == "widgets"
    assert line_value(result, "shared_changed") == "true"
    assert line_value(result, "full_matrix_required") == "true"


def test_component_plus_package_sensitive_path_elevated(tmp_path):
    """Known component + README must never be docs_fast.

    The fail-closed answer is FULL (the component has no validation
    contract yet and the change is no longer docs-scope), while the
    package sensitivity is still reported. full_matrix_required stays
    true: it reflects the active policy, and this change is not under
    the docs_fast / package_docs fast paths.
    """
    repo = make_repo(tmp_path)
    write_registry(repo, INDEPENDENT_REGISTRY)
    write_file(repo, "widgets/thing.py")
    write_file(repo, "README.md")
    base = commit_all(repo, "base")
    write_file(repo, "widgets/thing.py", "changed\n")
    write_file(repo, "README.md", "changed\n")
    head = commit_all(repo, "head")
    result = run_classifier(repo, base, head)

    assert result.returncode == 0, result.stdout + result.stderr
    assert tier(result) == "full"
    assert line_value(result, "components") == "widgets"
    assert line_value(result, "package_changed") == "true"
    assert line_value(result, "independent_only") == "false"
    assert line_value(result, "full_matrix_required") == "true"


def test_rename_into_unknown_full(tmp_path):
    """A rename out of a registered component classifies by BOTH paths."""
    repo = make_repo(tmp_path)
    write_registry(repo, INDEPENDENT_REGISTRY)
    write_file(repo, "widgets/old.txt")
    base = commit_all(repo, "base")
    (repo / "unknown").mkdir()
    run_git(repo, "mv", "widgets/old.txt", "unknown/new.txt")
    head = commit_all(repo, "head")
    result = run_classifier(repo, base, head)

    assert result.returncode == 0, result.stdout + result.stderr
    assert tier(result) == "full"
    assert line_value(result, "changed_files") == "2"
    assert "- widgets/old.txt" in result.stdout
    assert "- unknown/new.txt" in result.stdout
    assert line_value(result, "unknown_changed") == "true"


# ---------------------------------------------------------------------------
# Fail-closed: invalid registry / invalid ref.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "registry_text",
    [
        "[components.core\npaths = 42",  # unparseable TOML
        "[components.core]\npaths = 42",  # paths not a list
        "[components.core]\npaths = [\"src/\"]\nrequires_core_full = \"yes\"",
        "paths = [\"src/\"]",  # missing [components] table
        "[components.BAD NAME]\npaths = [\"x/\"]",  # invalid component name
    ],
)
def test_invalid_registry_fail_closed_full(tmp_path, registry_text):
    """A present-but-invalid registry exits 2 and fails closed to FULL."""
    repo = make_repo(tmp_path)
    write_registry(repo, registry_text)
    write_file(repo, "docs/guide.md")
    base = commit_all(repo, "base")
    write_file(repo, "docs/guide.md", "changed\n")
    head = commit_all(repo, "head")

    result = run_classifier(repo, base, head)

    assert result.returncode == 2, result.stdout + result.stderr
    assert line_value(result, "tier") == "full"
    assert line_value(result, "reason") == "invalid_registry_fail_closed"


def test_invalid_ref_fail_closed_with_registry(tmp_path):
    """An unresolvable ref still fails closed even with a registry."""
    repo = make_repo(tmp_path)
    write_registry(repo, REAL_REGISTRY)
    write_file(repo, "docs/guide.md")
    head = commit_all(repo, "base")

    result = run_classifier(repo, "0" * 40, head)

    assert result.returncode == 2, result.stdout + result.stderr
    assert line_value(result, "tier") == "full"
    assert line_value(result, "reason") == "classifier_error_fail_closed"


def test_full_matrix_required_matches_active_policy(tmp_path):
    """full_matrix_required reflects the ACTIVE policy, not eligibility.

    Invariant: full_matrix_required == true exactly when tier == full.
    In particular, a registered independent component WITHOUT a
    validation contract must report independent_only=true together with
    full_matrix_required=true, tier=full and
    reason=component_without_validation_requires_full. The
    contradictory state (component_without_validation_requires_full
    AND full_matrix_required=false) must never occur.
    """
    scenarios = [
        (REAL_REGISTRY, ["docs/guide.md"], "docs_fast"),
        (REAL_REGISTRY, ["README.md", "docs/guide.md"], "package_docs"),
        (REAL_REGISTRY, ["src/market_vault/thing.py"], "full"),
        (REAL_REGISTRY, ["notes.txt"], "full"),
        (REAL_REGISTRY, [".github/workflows/ci.yml"], "control_plane"),
        (REAL_REGISTRY, ["pyproject.toml"], "full"),
        (INDEPENDENT_REGISTRY, ["widgets/thing.py"], "full"),
        (INDEPENDENT_REGISTRY, ["widgets/thing.py", "README.md"], "full"),
        (
            INDEPENDENT_REGISTRY + REAL_REGISTRY,
            ["widgets/thing.py", "src/market_vault/thing.py"],
            "full",
        ),
    ]
    for i, (registry, paths, expected_tier) in enumerate(scenarios):
        scenario_dir = tmp_path / f"repo{i}"
        scenario_dir.mkdir()
        repo = make_repo(scenario_dir)
        write_registry(repo, registry)
        for path in paths:
            write_file(repo, path)
        base = commit_all(repo, "base")
        for path in paths:
            write_file(repo, path, "changed\n")
        head = commit_all(repo, "head")
        result = run_classifier(repo, base, head)

        assert result.returncode == 0, result.stdout + result.stderr
        assert tier(result) == expected_tier, result.stdout
        assert line_value(result, "full_matrix_required") == (
            "true" if expected_tier == "full" else "false"
        ), result.stdout
        assert not (
            line_value(result, "reason")
            == "component_without_validation_requires_full"
            and line_value(result, "full_matrix_required") == "false"
        ), result.stdout
