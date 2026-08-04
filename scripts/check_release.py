"""Read-only release-readiness checker for MarketVault.

Verifies that pyproject.toml, the package version module, documentation, CI
package assertions, and build hygiene agree before tagging. Never modifies
files. Uses only the Python 3.11 standard library.

Exit code 0 with "RELEASE_CHECK_OK version=..." on success; exit code 1 with
every failure listed otherwise.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

EXPECTED_VERSION = "0.4.0"
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
    if first_line.strip() != "# MarketVault v0.4":
        return [f"README first line is {first_line.strip()!r}, expected '# MarketVault v0.4'"]
    return []


def check_changelog(root: Path) -> list[str]:
    path = root / "CHANGELOG.md"
    if not path.exists():
        return ["CHANGELOG.md is missing"]
    text = path.read_text(encoding="utf-8")
    if "## [0.4.0] - 2026-08-05" not in text:
        return ["CHANGELOG.md is missing '## [0.4.0] - 2026-08-05'"]
    return []


def check_readme_no_development_wording(root: Path) -> list[str]:
    path = root / "README.md"
    if not path.exists():
        return ["README.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    if "V0.4 development" in text:
        failures.append("README still contains 'V0.4 development'")
    if "V0.4 remains under development" in text:
        failures.append("README still contains 'V0.4 remains under development'")
    if "release preparation pending" in text:
        failures.append("README still contains 'release preparation pending'")
    if "one calendar day after" in text:
        failures.append("README still contains the outdated 'one calendar day after' phrasing")
    if "next trading date" not in text and "first trading date strictly after" not in text:
        failures.append("README does not describe the next-trading-date calendar semantics")
    return failures


def check_release_notes(root: Path) -> list[str]:
    path = root / "docs" / "release_v0_4_0.md"
    if not path.exists():
        return ["docs/release_v0_4_0.md is missing"]
    return []


def check_old_release_notes(root: Path) -> list[str]:
    path = root / "docs" / "release_v0_3_0.md"
    if not path.exists():
        return ["docs/release_v0_3_0.md is missing"]
    return []


def check_readme_upgrade_from_v03(root: Path) -> list[str]:
    path = root / "README.md"
    if not path.exists():
        return ["README.md is missing"]
    text = path.read_text(encoding="utf-8")
    if "Upgrade from v0.3" not in text:
        return ["README does not contain 'Upgrade from v0.3'"]
    return []


def check_readme_no_final_dataset_builder(root: Path) -> list[str]:
    path = root / "README.md"
    if not path.exists():
        return ["README.md is missing"]
    text = path.read_text(encoding="utf-8")
    if "final Dataset builder" not in text or "not implemented" not in text:
        return ["README does not state that the final Dataset builder is not implemented"]
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
        ("README wording", check_readme_no_development_wording),
        ("release notes", check_release_notes),
        ("old release notes", check_old_release_notes),
        ("README upgrade notes", check_readme_upgrade_from_v03),
        ("README dataset boundary", check_readme_no_final_dataset_builder),
        ("README adjustment boundary", check_readme_adjustment_none),
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
