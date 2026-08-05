"""Read-only release-readiness checker for MarketVault.

Verifies that pyproject.toml, the package version module, documentation, CI
package assertions, and build hygiene agree before tagging. Never modifies
files. Uses only the Python 3.11 standard library.

Exit code 0 with "RELEASE_CHECK_OK version=..." on success; exit code 1 with
every failure listed otherwise.

This checker never requires a git tag, a GitHub Release, or a PyPI
publication to exist: those actions remain separate, explicit, and are not
part of release readiness.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

EXPECTED_VERSION = "0.5.0"
PEP440_RE = re.compile(
    r"^([1-9]\d*!)?(0|[1-9]\d*)(\.(0|[1-9]\d*))*((a|b|rc)(0|[1-9]\d*))?"
    r"(\.post(0|[1-9]\d*))?(\.dev(0|[1-9]\d*))?$"
)
FORBIDDEN_TRACKED = ("build/", "dist/", ".whl", "data/", "catalog/", "manifests/", "reports/")
# The CI fresh-wheel step asserts the installed package module version and the
# installed distribution metadata version separately; both must be present.
CI_PACKAGE_VERSION_MARKERS = (
    f'assert market_vault.__version__ == "{EXPECTED_VERSION}"',
    f"assert market_vault.__version__ == '{EXPECTED_VERSION}'",
)
CI_METADATA_VERSION_MARKERS = (
    f"assert version('market-vault') == '{EXPECTED_VERSION}'",
)
# The CI fresh-wheel public API smoke marker must use the v0.5 release marker.
CI_PUBLIC_API_MARKER = "V050_PUBLIC_API_IMPORT_OK"
# Stale v0.4-era claims that must never appear in the current README.
STALE_README_PHRASES = (
    "final Dataset builder is not implemented",
    "no final Dataset CLI",
    "no automatic Feature/Label value computation",
    "no final Dataset Parquet export",
    "V0.5 development",
    "V0.5 remains under development",
    "release preparation pending",
)
# Stale v0.5.0 direction status wording that must never appear in the current
# direction document.
STALE_DIRECTION_PHRASES = (
    "Status: proposed",
    "PR-10 has not started",
)
# Stale v0.5.0 pre-release wording that must never appear in the current
# direction document after the v0.5.0 release.
STALE_POST_RELEASE_PHRASES = (
    "Status: implementation complete; v0.5.0 release preparation",
    "PR-10 is the current release-preparation branch",
    "GitHub PR #29 is still OPEN",
    "No v0.5.0 tag exists",
    "No GitHub Release is published",
)
# Facts the v0.5.0 direction document must state after the release.
DIRECTION_RELEASED_FACTS = (
    "Status: released",
    "3b4d03c785123e204885faea08df7b9d7ed07ec0",
    "v0.5.0",
    "GitHub Release",
    "PyPI",
)
# Facts the v0.5.0 release notes must state after the release.
RELEASE_NOTES_FACTS = (
    "PR #29",
    "MERGED",
    "3b4d03c785123e204885faea08df7b9d7ed07ec0",
    "v0.5.0",
    "MarketVault v0.5.0",
    "market_vault-0.5.0-py3-none-any.whl",
    "market_vault-0.5.0.tar.gz",
    "PyPI",
)
# Stale pre-release wording that must never appear in the current release
# notes.
RELEASE_NOTES_STALE_PHRASES = (
    "GitHub PR #29 is still OPEN",
    "No v0.5.0 tag exists",
    "No GitHub Release is published",
)
# Facts the v0.5.1 direction document must state.
DIRECTION_V051_FACTS = (
    "Status: planned",
    "Stability and Usability Maintenance",
    "PR-1",
    "PR-2",
    "PR-3",
    "PR-4",
    "Sample Generator",
    "Dataset Catalog",
    "Python Client",
    "ML Experiment",
)
# The v0.5.1 direction document must mark the future capabilities as
# non-goals, not as implemented work.
DIRECTION_V051_NONGOAL_MARKERS = (
    "Explicit non-goals",
    "does not implement",
)


def tracked_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
    )
    if result.returncode != 0:
        # Not a git worktree (e.g. a temporary copy in tests): nothing tracked.
        return []
    return [item for item in result.stdout.decode("utf-8").split("\0") if item]


def check_pyproject_version(root: Path) -> list[str]:
    path = root / "pyproject.toml"
    if not path.exists():
        return ["pyproject.toml is missing"]
    with path.open("rb") as fh:
        pyproject = tomllib.load(fh)
    version = pyproject["project"]["version"]
    if version != EXPECTED_VERSION:
        return [f"pyproject.toml version is {version!r}, expected {EXPECTED_VERSION!r}"]
    return []


def check_package_version(root: Path) -> list[str]:
    version_file = root / "src" / "market_vault" / "_version.py"
    if not version_file.exists():
        return ["_version.py is missing"]
    text = version_file.read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        return ["_version.py does not define __version__"]
    version = match.group(1)
    if version != EXPECTED_VERSION:
        return [f"package __version__ is {version!r}, expected {EXPECTED_VERSION!r}"]
    return []


def check_readme_title(root: Path) -> list[str]:
    path = root / "README.md"
    if not path.exists():
        return ["README.md is missing"]
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    if first_line.strip() != "# MarketVault v0.5":
        return [f"README first line is {first_line.strip()!r}, expected '# MarketVault v0.5'"]
    return []


def check_changelog(root: Path) -> list[str]:
    path = root / "CHANGELOG.md"
    if not path.exists():
        return ["CHANGELOG.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    if "## [0.5.0] - 2026-08-05" not in text:
        failures.append("CHANGELOG.md is missing '## [0.5.0] - 2026-08-05'")
    if "## [0.4.0] - 2026-08-05" not in text:
        failures.append("CHANGELOG.md no longer contains '## [0.4.0] - 2026-08-05'")
    return failures


def check_readme_no_stale_wording(root: Path) -> list[str]:
    path = root / "README.md"
    if not path.exists():
        return ["README.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    for phrase in STALE_README_PHRASES:
        if phrase in text:
            failures.append(f"README still contains the outdated wording {phrase!r}")
    if "one calendar day after" in text:
        failures.append("README still contains the outdated 'one calendar day after' phrasing")
    if "next trading date" not in text and "first trading date strictly after" not in text:
        failures.append("README does not describe the next-trading-date calendar semantics")
    return failures


def check_direction_status(root: Path) -> list[str]:
    path = root / "docs" / "v0_5_0_direction.md"
    if not path.exists():
        return ["docs/v0_5_0_direction.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    for fact in DIRECTION_RELEASED_FACTS:
        if fact not in text:
            failures.append(
                f"docs/v0_5_0_direction.md does not state the released fact {fact!r}"
            )
    for phrase in STALE_DIRECTION_PHRASES + STALE_POST_RELEASE_PHRASES:
        if phrase in text:
            failures.append(
                f"docs/v0_5_0_direction.md still contains the stale wording {phrase!r}"
            )
    return failures


def check_release_notes(root: Path) -> list[str]:
    path = root / "docs" / "release_v0_5_0.md"
    if not path.exists():
        return ["docs/release_v0_5_0.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    for fact in RELEASE_NOTES_FACTS:
        if fact not in text:
            failures.append(
                f"docs/release_v0_5_0.md does not state the release fact {fact!r}"
            )
    for phrase in RELEASE_NOTES_STALE_PHRASES:
        if phrase in text:
            failures.append(
                f"docs/release_v0_5_0.md still contains the stale wording {phrase!r}"
            )
    return failures


def check_v051_direction(root: Path) -> list[str]:
    path = root / "docs" / "v0_5_1_direction.md"
    if not path.exists():
        return ["docs/v0_5_1_direction.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    for fact in DIRECTION_V051_FACTS:
        if fact not in text:
            failures.append(f"docs/v0_5_1_direction.md does not state the fact {fact!r}")
    for marker in DIRECTION_V051_NONGOAL_MARKERS:
        if marker not in text:
            failures.append(
                "docs/v0_5_1_direction.md does not mark the future capabilities "
                f"as non-goals ({marker!r})"
            )
    return failures


def check_old_release_notes(root: Path) -> list[str]:
    failures = []
    if not (root / "docs" / "release_v0_4_0.md").exists():
        failures.append("docs/release_v0_4_0.md is missing")
    if not (root / "docs" / "release_v0_3_0.md").exists():
        failures.append("docs/release_v0_3_0.md is missing")
    return failures


def check_readme_upgrade_sections(root: Path) -> list[str]:
    path = root / "README.md"
    if not path.exists():
        return ["README.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    if "Upgrade from v0.4" not in text:
        failures.append("README does not contain 'Upgrade from v0.4'")
    if "Upgrade from v0.3" not in text:
        failures.append("README does not contain 'Upgrade from v0.3'")
    return failures


def check_readme_dataset_builder_section(root: Path) -> list[str]:
    path = root / "README.md"
    if not path.exists():
        return ["README.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    if "V0.5 deterministic Dataset builder" not in text:
        failures.append("README does not contain the 'V0.5 deterministic Dataset builder' section")
    for command in ("dataset-build", "dataset-verify", "dataset-inspect"):
        if command not in text:
            failures.append(f"README does not describe the {command} command")
    if "verified Dataset reader" not in text:
        failures.append("README does not mention the verified Dataset reader")
    if "immutable Dataset materialization" not in text:
        failures.append("README does not mention immutable Dataset materialization")
    return failures


def check_readme_explicit_build_plan(root: Path) -> list[str]:
    path = root / "README.md"
    if not path.exists():
        return ["README.md is missing"]
    text = path.read_text(encoding="utf-8")
    if "explicit" not in text or "build-plan JSON" not in text:
        return ["README does not describe the explicit, pinned build-plan JSON input"]
    return []


def check_readme_adjustment_none(root: Path) -> list[str]:
    path = root / "README.md"
    if not path.exists():
        return ["README.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    if "adjustment" not in text or "NONE" not in text:
        failures.append("README does not mention the adjustment NONE default")
    if "adjusted-price" not in text:
        failures.append("README does not mention the no-adjusted-price boundary")
    return failures


def check_readme_dataset_boundaries(root: Path) -> list[str]:
    path = root / "README.md"
    if not path.exists():
        return ["README.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    if "cross-trading-day" not in text:
        failures.append("README does not mention the no-cross-trading-day boundary")
    if "arbitrary user code" not in text:
        failures.append("README does not mention the no-arbitrary-user-code boundary")
    if "ML training" not in text or "backtest" not in text or "automatic trading" not in text:
        failures.append(
            "README does not mention the no-ML/backtest/trading boundary"
        )
    return failures


def check_ci_version_assertions(root: Path) -> list[str]:
    path = root / ".github" / "workflows" / "ci.yml"
    if not path.exists():
        return [".github/workflows/ci.yml is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    if not any(marker in text for marker in CI_PACKAGE_VERSION_MARKERS):
        failures.append(
            ".github/workflows/ci.yml wheel package module version assertion "
            f"is missing or wrong (expected {EXPECTED_VERSION!r})"
        )
    if not any(marker in text for marker in CI_METADATA_VERSION_MARKERS):
        failures.append(
            ".github/workflows/ci.yml wheel distribution metadata assertion "
            f"is missing or wrong (expected {EXPECTED_VERSION!r})"
        )
    if CI_PUBLIC_API_MARKER not in text:
        failures.append(
            f".github/workflows/ci.yml public API smoke marker {CI_PUBLIC_API_MARKER!r} "
            "is missing or outdated"
        )
    if "0.3.0" in text:
        failures.append(".github/workflows/ci.yml still references the old version 0.3.0")
    return failures


def check_build_artifacts_untracked(root: Path) -> list[str]:
    failures = []
    for item in tracked_files(root):
        normalized = item.replace("\\", "/")
        for forbidden in FORBIDDEN_TRACKED:
            if normalized.startswith(forbidden) or normalized.endswith(".whl"):
                failures.append(f"tracked build artifact: {item}")
                break
    return failures


def check_pep440(root: Path) -> list[str]:
    path = root / "pyproject.toml"
    if not path.exists():
        return ["pyproject.toml is missing"]
    with path.open("rb") as fh:
        pyproject = tomllib.load(fh)
    version = pyproject["project"]["version"]
    if not PEP440_RE.match(version):
        return [f"version {version!r} is not PEP 440 compatible"]
    return []


def check_cli_version(root: Path) -> list[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root / "src")
    result = subprocess.run(
        [sys.executable, "-m", "market_vault", "--version"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
    )
    output = (result.stdout + result.stderr).strip()
    expected = f"market-vault {EXPECTED_VERSION}"
    if result.returncode != 0 or expected not in output:
        return [f"CLI --version output is {output!r}, expected {expected!r} with exit 0"]
    return []


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    checks = [
        ("pyproject version", check_pyproject_version),
        ("package __version__", check_package_version),
        ("README title", check_readme_title),
        ("CHANGELOG entry", check_changelog),
        ("README wording", check_readme_no_stale_wording),
        ("direction status", check_direction_status),
        ("release notes", check_release_notes),
        ("v0.5.1 direction", check_v051_direction),
        ("old release notes", check_old_release_notes),
        ("README upgrade notes", check_readme_upgrade_sections),
        ("README dataset builder", check_readme_dataset_builder_section),
        ("README explicit plan", check_readme_explicit_build_plan),
        ("README adjustment boundary", check_readme_adjustment_none),
        ("README dataset boundaries", check_readme_dataset_boundaries),
        ("CI version assertions", check_ci_version_assertions),
        ("build artifacts untracked", check_build_artifacts_untracked),
        ("PEP 440 version", check_pep440),
        ("CLI version output", check_cli_version),
    ]
    failures: list[str] = []
    for label, check in checks:
        failures.extend(check(root))
    if failures:
        print("RELEASE_CHECK_FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"RELEASE_CHECK_OK version={EXPECTED_VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
