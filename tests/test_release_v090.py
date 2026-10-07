from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_release_checker():
    path = ROOT / "scripts" / "check_release.py"
    spec = importlib.util.spec_from_file_location("check_release_v090", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v090_versions_are_consistent():
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project_version = tomllib.load(handle)["project"]["version"]
    namespace: dict[str, str] = {}
    exec(
        (ROOT / "src" / "market_vault" / "_version.py").read_text(
            encoding="utf-8"
        ),
        namespace,
    )
    assert project_version == namespace["__version__"] == "0.9.0"


def test_v090_released_state_documents_pass_checker():
    checker = _load_release_checker()
    assert checker.check_v090_released_state_docs(ROOT) == []


def test_v090_ci_released_state_passes_checker():
    checker = _load_release_checker()
    assert checker.check_ci_version_assertions(ROOT) == []
    assert checker.check_ci_v090_released_state(ROOT) == []


def test_v090_release_notes_seal_exact_formal_identities():
    text = (ROOT / "docs" / "release_v0_9_0.md").read_text(encoding="utf-8")
    formal, historical = text.split("## Historical release-preparation record", 1)
    for marker in (
        "V090_RELEASE_STATUS=FORMALLY_RELEASED_AND_SEALED",
        "release commit: 5a796f0d4290b50291993dfcdfcacccb0c8dcb69",
        "release tree: 62f051f0c5a59edf35e7ec3fa3d74206407b7773",
        "main CI: 37556656352",
        "tag: v0.9.0",
        "tag type: annotated",
        "tag object: 029890e4d857e3db98e9ed104d9ec5dfe81c8ea0",
        "peeled tag commit: 5a796f0d4290b50291993dfcdfcacccb0c8dcb69",
        "release ID: 405290783",
        "publishedAt: 2026-10-07T01:46:35Z",
        "draft: false",
        "prerelease: false",
        "latest: true",
        "71de59c5170384a7f22115761077fd525d2190ff666108888950e081d33ccc99",
        "0ae6f46144d66fdc85e0ecb96191bb6f68a90bdc16f3aea3eab908c09dc17ef5",
        "10f96d62ef0f55148e9e0948e926c5fb28f2b8ff1a1cc9d595f2f50fb7146d8d",
        "PyPI: NOT PUBLISHED",
        "TestPyPI: NOT PUBLISHED",
    ):
        assert marker in formal
    assert "formal release gate pending" not in formal

    assert "Status: Stage 2 release-preparation candidate" in historical
    assert "RELEASE_PREPARATION_BASE_SHA=d01bcf22f9b6d526cff90f3aceb7e3ef441a1a1e" in historical
    assert "FORMAL_V090_RELEASED=false" in historical
    assert "CURRENT_FORMAL_RELEASE=v0.8.0" in historical


def test_v090_changelog_and_readme_released_lifecycle():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    direction = (ROOT / "docs" / "v0_9_0_direction.md").read_text(
        encoding="utf-8"
    )
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "## [0.9.0] - 2026-10-07" in changelog
    assert (
        "[0.9.0]: "
        "https://github.com/M0DIAN/market-vault/compare/v0.8.0...v0.9.0"
        in changelog
    )
    assert "Current package version: v0.9.0" in readme
    assert "Current formal release: v0.9.0" in readme
    assert "Formal v0.9.0 release record" in readme
    assert "Status: v0.9.0 formally released; release direction closed." in direction
    assert "FORMAL_V090_RELEASE_COMMIT=5a796f0d4290b50291993dfcdfcacccb0c8dcb69" in direction
    assert "FORMAL_V090_RELEASED=true" in direction
    assert "V090_RELEASED_OK" in workflow
    assert "V090_RELEASE_PREP_OK" not in workflow


def test_v090_fresh_wheel_research_surface_is_pinned():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    assert "assert market_vault.__version__ == '0.9.0'" in workflow
    assert "assert version('market-vault') == '0.9.0'" in workflow
    assert "V080_RELEASED_OK" in workflow
    assert "V090_RELEASED_OK" in workflow
    assert "V090_RELEASE_PREP_OK" not in workflow
    assert "V090_RESEARCH_SURFACE_OK" in workflow
    for command in (
        "research-build",
        "research-backtest",
        "research-feature-report",
        "research-feature-stability",
        "research-feature-select",
        "research-walk-forward",
        "research-ridge",
        "research-ridge-final",
        "research-ridge-trading-select",
        "research-ridge-final-trading",
        "research-ridge-selected-final-trading",
        "research-ridge-final-evaluation",
        "research-ridge-final-evaluation-artifact",
    ):
        assert f"market-vault {command} --help" in workflow
