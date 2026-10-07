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


def test_v090_candidate_versions_are_consistent():
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


def test_v090_release_preparation_documents_pass_checker():
    checker = _load_release_checker()
    assert checker.check_v090_release_preparation_docs(ROOT) == []


def test_v090_ci_release_preparation_passes_checker():
    checker = _load_release_checker()
    assert checker.check_ci_version_assertions(ROOT) == []
    assert checker.check_ci_v090_release_preparation(ROOT) == []


def test_v090_release_notes_do_not_claim_future_formal_identities():
    text = (ROOT / "docs" / "release_v0_9_0.md").read_text(encoding="utf-8")
    assert "V090_RELEASE_STATUS=RELEASE_PREPARATION_CANDIDATE" in text
    assert "FORMAL_V090_RELEASED=false" in text
    assert "CURRENT_FORMAL_RELEASE=v0.8.0" in text
    for forbidden in (
        "V090_RELEASE_STATUS=FORMALLY_RELEASED_AND_SEALED",
        "FORMAL_V090_RELEASED=true",
        "V090_RELEASED_OK",
        "release commit:",
        "release tree:",
        "main CI:",
        "tag object:",
        "peeled tag commit:",
        "release ID:",
        "publishedAt:",
    ):
        assert forbidden not in text


def test_v090_changelog_and_readme_candidate_lifecycle():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    direction = (ROOT / "docs" / "v0_9_0_direction.md").read_text(
        encoding="utf-8"
    )

    assert "## [0.9.0] - 2026-10-07" in changelog
    assert (
        "[0.9.0]: "
        "https://github.com/M0DIAN/market-vault/compare/v0.8.0...v0.9.0"
        in changelog
    )
    assert "Package candidate version: v0.9.0" in readme
    assert "Current formal release: v0.8.0" in readme
    assert "V0.9.0 release-preparation notes" in readme
    assert "Status: scope frozen on main; Stage 2 release-preparation candidate." in direction
    assert "FORMAL_V090_RELEASED=false" in direction


def test_v090_fresh_wheel_research_surface_is_pinned():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    assert "assert market_vault.__version__ == '0.9.0'" in workflow
    assert "assert version('market-vault') == '0.9.0'" in workflow
    assert "V080_RELEASED_OK" in workflow
    assert "V090_RELEASE_PREP_OK" in workflow
    assert "V090_RELEASED_OK" not in workflow
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
