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


def test_v080_released_state_documents_pass_checker():
    checker = _load_release_checker()
    assert checker.check_v080_released_state_docs(ROOT) == []


def test_v080_ci_released_state_and_public_api_smoke_pass_checker():
    checker = _load_release_checker()
    assert checker.check_ci_version_assertions(ROOT) == []
    assert checker.check_ci_v080_released_state(ROOT) == []


def test_v080_release_notes_seal_exact_formal_identities():
    text = (ROOT / "docs" / "release_v0_8_0.md").read_text(encoding="utf-8")
    formal, historical = text.split("## Historical release-preparation record", 1)
    for marker in (
        "V080_RELEASE_STATUS=FORMALLY_RELEASED_AND_SEALED",
        "release commit: 90230ce1b55e63da0c583eaac8e94b64f6f4c2f9",
        "release tree: 2ed28297d03251da126460fa7084d6841c804cef",
        "main CI: 34757019730",
        "tag: v0.8.0",
        "tag type: annotated",
        "tag object: e4ecb355fcde04be469de66313aa8974d248fad8",
        "peeled tag commit: 90230ce1b55e63da0c583eaac8e94b64f6f4c2f9",
        "release ID: 387904895",
        "publishedAt: 2026-09-13T13:15:02Z",
        "draft: false",
        "prerelease: false",
        "latest: true",
        "6f24277a0e1d729e1723d0aa50d6d6a4969742a9666d741daa25b7a144e0358d",
        "9ab07826fa81372370132b16b71fb393a8d105ac78b2c60c75d3ea1e1677be5d",
        "5a27736b9c73f35921fc69f42676caa47a46b8e0553b60db9e6934ef8307e1d3",
        "PyPI: NOT PUBLISHED",
        "TestPyPI: NOT PUBLISHED",
    ):
        assert marker in formal
    assert "formal release gate pending" not in formal

    assert "Status: Stage 2 release-preparation candidate" in historical
    assert "RELEASE_PREPARATION_BASE_SHA=1eb3dec68816b133bb97e05d7422184d3815e9dc" in historical
    assert "RELEASE_PREPARATION_BASE_TREE=9f3f811606b1329b4e5565d42065419d5377bb2b" in historical
    assert "RELEASE_BLOCKER_PR_153=CLOSED" in historical
    assert "WINDOWS_PY311_REPARSE_RELEASE_BLOCKER=CLOSED" in historical
    assert "FORMAL_V070_RELEASE_SHA=f25a50481b5ee718881acf5cb5ea5aa05bd32d93" in historical
    assert "load_canonical_build\nload_dataset\nload_dataset_catalog" in historical
    assert "It did not ship the post-v0.7 QML production desktop" in historical
    assert "`ArtifactClient.select_dataset_catalog_entry(...)`" in historical


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
    direction = (ROOT / "docs" / "v0_8_0_direction.md").read_text(
        encoding="utf-8"
    )
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    assert "## [0.8.0] - 2026-09-11" in changelog
    assert "Current package version: v0.8.0" in readme
    assert "Current formal release: v0.8.0" in readme
    assert "Formal v0.8.0 release record" in readme
    assert "Status: v0.8.0 formally released; release direction closed." in direction
    assert "V080_DIRECTION_BASE_SHA=1f4da9154cdbe4a9b48e025a4777562fed0ef305" in direction
    assert "FORMAL_V080_RELEASE_COMMIT=90230ce1b55e63da0c583eaac8e94b64f6f4c2f9" in direction
    assert "FORMAL_V080_RELEASED=true" in direction
    assert "V080_RELEASED_OK" in workflow
    assert "V080_RELEASE_PREP_OK" not in workflow
