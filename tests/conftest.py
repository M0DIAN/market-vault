"""Shared fixtures and generic constants for the framework test suite.

The suite never contacts the network (the GitHub API surface is mocked)
and never touches any real repository beyond throwaway temp git repos.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ci_optimizer.policy import load_config

# Generic identifiers (no project-specific history).
BASE = "a" * 40          # PR base SHA == push "before" SHA
HEAD = "b" * 40          # PR head SHA
MAIN = "c" * 40          # new main commit SHA (squash commit)
TREE = "d" * 40          # the tested tree SHA
MERGE = "f" * 40         # the PR run's synthetic merge commit
REPO = "example/ci-optimizer"
RUN_ID = 31352080511
ATTEMPT = 1
PR_NUMBER = 60
PREFIX = "ci-full-attestation-"
REQUIRED_JOBS = ("test (3.11)", "test (3.12)", "package")

CONFIG_TEXT = f'''\
schema_version = 1

[repository]
main_branch = "main"
workflow_name = "CI"
workflow_path = ".github/workflows/ci.yml"

[paths]
docs = ["docs/"]
package_docs = ["README.md"]
control_plane = [".github/workflows/", "ciopt.toml"]
control_plane_eligible = [".github/workflows/ci.yml", "ciopt.toml"]

[components.core]
paths = ["src/"]
requires_full = true

[components.package]
paths = ["pyproject.toml"]
requires_package = true

[reuse]
enabled = true
required_jobs = ["test (3.11)", "test (3.12)", "package"]
control_plane_paths = [".github/workflows/", "ciopt.toml"]
artifact_prefix = "{PREFIX}"
'''


@pytest.fixture
def config(tmp_path: Path):
    """A fully valid generic config (any single test may override)."""
    path = tmp_path / "ciopt.toml"
    path.write_text(CONFIG_TEXT, encoding="utf-8")
    return load_config(path)
