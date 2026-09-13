from __future__ import annotations

import ast
import importlib.util
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_release_checker():
    path = ROOT / "scripts" / "check_release.py"
    spec = importlib.util.spec_from_file_location("check_release_v080", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v080_versions_are_consistent():
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project_version = tomllib.load(handle)["project"]["version"]
    namespace: dict[str, str] = {}
    exec(
        (ROOT / "src" / "market_vault" / "_version.py").read_text(
            encoding="utf-8"
        ),
        namespace,
    )
    assert project_version == namespace["__version__"] == "0.8.0"


def test_v080_release_preparation_documents_pass_checker():
    checker = _load_release_checker()
    assert checker.check_v080_release_preparation_docs(ROOT) == []


def test_v080_ci_version_and_public_api_smoke_pass_checker():
    checker = _load_release_checker()
    assert checker.check_ci_version_assertions(ROOT) == []
    assert checker.check_ci_v080_release_preparation(ROOT) == []


def test_v080_release_notes_preserve_v070_history_and_pending_gate():
    text = (ROOT / "docs" / "release_v0_8_0.md").read_text(encoding="utf-8")
    historical = text.split("## 5. Formal release gate remains pending", 1)[0]
    assert "RELEASE_PREPARATION_BASE_SHA=1eb3dec68816b133bb97e05d7422184d3815e9dc" in text
    assert "RELEASE_PREPARATION_BASE_TREE=9f3f811606b1329b4e5565d42065419d5377bb2b" in text
    assert "RELEASE_BLOCKER_PR_153=CLOSED" in text
    assert "WINDOWS_PY311_REPARSE_RELEASE_BLOCKER=CLOSED" in text
    assert "FORMAL_V070_RELEASE_SHA=f25a50481b5ee718881acf5cb5ea5aa05bd32d93" in text
    assert "load_canonical_build\nload_dataset\nload_dataset_catalog" in historical
    assert "It did not ship the post-v0.7 QML production desktop" in historical
    assert "`ArtifactClient.select_dataset_catalog_entry(...)`" in historical
    assert "formal release gate pending" in text
    assert "V080_RELEASED_OK" not in text


def test_v080_current_artifact_client_has_exact_four_business_methods():
    tree = ast.parse(
        (ROOT / "src" / "market_vault" / "artifact_client.py").read_text(
            encoding="utf-8"
        )
    )
    client = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ArtifactClient"
    )
    methods = tuple(
        node.name
        for node in client.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    )
    assert methods == (
        "load_canonical_build",
        "load_dataset",
        "load_dataset_catalog",
        "select_dataset_catalog_entry",
    )


def test_v080_changelog_and_readme_lifecycle_markers():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## [0.8.0] - 2026-09-11" in changelog
    assert "Package candidate version: v0.8.0" in readme
    assert "Current formal release: v0.7.0" in readme
