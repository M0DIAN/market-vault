from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import date
from pathlib import Path

import pytest
import importlib.util as _importlib_util


def _load_check_release():
    """Load scripts/check_release.py as a plain module (scripts/ is
    not a package). Tests invoke the exact production check functions
    through this single registry instead of a full checker subprocess."""
    spec = _importlib_util.spec_from_file_location(
        "check_release", str(ROOT / "scripts" / "check_release.py")
    )
    assert spec is not None and spec.loader is not None
    module = _importlib_util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_check_fails(check, repo: Path, *fragments: str) -> list[str]:
    """Run one production check against a mutated repo copy and assert it
    reports every expected failure fragment.

    The mutation tests exercise the smallest exact production check
    responsible for each invariant instead of paying for a full checker
    subprocess run; run_check_release retains the end-to-end integration
    cases. Returns the failure list so tests can assert on absences.
    """
    failures = check(repo)
    assert failures, f"{check.__name__} reported no failure"
    text = "\n".join(failures)
    for fragment in fragments:
        assert fragment in text, (
            f"expected {fragment!r} in {check.__name__} failures: {failures!r}"
        )
    return failures


import market_vault
from market_vault import MarketVault
from market_vault._version import __version__
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars, normalize_trading_calendar
from market_vault.storage import Catalog, ParquetStore

ROOT = Path(__file__).resolve().parents[1]
_check_release = _load_check_release()


SRC = ROOT / "src"
EXPECTED_VERSION = "0.7.0"
PUBLIC_API_IMPORT_CODE = "\n".join(
    [
        "from market_vault.canonical import load_verified_canonical_build",
        "from market_vault.dataset import (",
        "    orchestrate_dataset_build,",
        "    materialize_dataset_artifacts,",
        "    load_verified_dataset,",
        "    generate_sample_requests,",
        ")",
        "print('V061_PUBLIC_API_IMPORT_OK')",
    ]
)
PEP440_RE = re.compile(
    r"^([1-9]\d*!)?(0|[1-9]\d*)(\.(0|[1-9]\d*))*((a|b|rc)(0|[1-9]\d*))?"
    r"(\.post(0|[1-9]\d*))?(\.dev(0|[1-9]\d*))?$"
)
CLI_COMMANDS = [
    "init-catalog",
    "doctor",
    "collect",
    "query",
    "option-chain",
    "option-volatility",
    "calendar",
    "calendar-query",
    "backfill",
    "inventory",
    "audit",
    "intraday-audit",
    "dataset-build",
    "dataset-verify",
    "dataset-inspect",
]


def run_code(code: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
    )


def run_code_in(cwd: Path, code: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


def run_cli(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "market_vault", *args],
        capture_output=True,
        text=True,
        env=env,
    )


def copy_repo(tmp_path: Path) -> Path:
    target = tmp_path / "repo"
    shutil.copytree(
        ROOT,
        target,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            ".release-venv",
            ".pytest_cache",
            "__pycache__",
            "build",
            "dist",
            "data",
            "catalog",
            "manifests",
            "reports",
            "*.duckdb",
            "*.egg-info",
        ),
    )
    return target


# --- Version ----------------------------------------------------------------


def test_pyproject_version():
    with (ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)
    assert pyproject["project"]["version"] == EXPECTED_VERSION


def test_package_version():
    assert __version__ == EXPECTED_VERSION


def test_pyproject_and_package_versions_agree():
    with (ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)
    assert pyproject["project"]["version"] == __version__


def test_version_in_all():
    assert "__version__" in market_vault.__all__


def test_version_pep440():
    assert PEP440_RE.match(__version__)


# --- Lightweight import -----------------------------------------------------


def test_import_market_vault_succeeds():
    result = run_code("import market_vault; print(market_vault.__version__)")
    assert result.returncode == 0
    assert result.stdout.strip() == EXPECTED_VERSION


def test_import_does_not_load_moomoo():
    result = run_code(
        "import market_vault, sys; assert 'moomoo' not in sys.modules"
    )
    assert result.returncode == 0, result.stderr


def test_import_does_not_load_futu():
    result = run_code(
        "import market_vault, sys; assert 'futu' not in sys.modules"
    )
    assert result.returncode == 0, result.stderr


def test_import_does_not_load_duckdb():
    result = run_code(
        "import market_vault, sys; assert 'duckdb' not in sys.modules"
    )
    assert result.returncode == 0, result.stderr


def test_market_vault_remains_lazy():
    result = run_code(
        "import market_vault; assert market_vault.MarketVault.__name__ == 'MarketVault'"
    )
    assert result.returncode == 0, result.stderr


# --- CLI --------------------------------------------------------------------


def test_cli_version_output():
    result = run_cli("--version")
    assert result.returncode == 0
    assert result.stdout.strip() == f"market-vault {EXPECTED_VERSION}"


def test_cli_version_does_not_require_settings_file(tmp_path):
    cwd = tmp_path
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    result = subprocess.run(
        [sys.executable, "-m", "market_vault", "--version"],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0
    assert f"market-vault {EXPECTED_VERSION}" in result.stdout


def test_cli_version_does_not_require_subcommand():
    result = run_cli("--version")
    assert result.returncode == 0


def test_cli_version_exit_zero():
    assert run_cli("--version").returncode == 0


def test_cli_top_level_help_lists_all_commands():
    result = run_cli("--help")
    assert result.returncode == 0
    for command in CLI_COMMANDS:
        assert command in result.stdout


@pytest.mark.parametrize("command", CLI_COMMANDS)
def test_each_subcommand_help_parses(command):
    result = run_cli(command, "--help")
    assert result.returncode == 0, result.stderr


def test_help_and_version_do_not_construct_collectors():
    # Instantiating any collector would attempt to reach OpenD and fail
    # loudly; both commands must exit cleanly without a traceback.
    assert run_cli("--version").returncode == 0
    assert run_cli("--help").returncode == 0
    assert "Traceback" not in run_cli("--version").stderr


def test_dataset_cli_helps_do_not_require_settings():
    # The Dataset commands are dispatched before settings loading; --help must
    # parse from an empty directory with no settings file, no OpenD, and no
    # network.
    for command in ("dataset-build", "dataset-verify", "dataset-inspect"):
        result = run_cli(command, "--help")
        assert result.returncode == 0, result.stderr
        assert "Traceback" not in result.stderr


def test_cli_success_branches_return_zero():
    text = (ROOT / "src" / "market_vault" / "cli.py").read_text(encoding="utf-8")
    # No bare success returns remain; failures still use explicit 1/2 codes.
    assert not re.search(r"^\s+return\s*$", text, re.MULTILINE)
    assert "return 1" in text
    assert "return 2" in text


def test_cli_existing_failure_exit_codes_unchanged():
    assert "return 1" in (ROOT / "src" / "market_vault" / "cli.py").read_text(encoding="utf-8")
    assert "return 2" in (ROOT / "src" / "market_vault" / "cli.py").read_text(encoding="utf-8")


# --- Documentation ----------------------------------------------------------


def test_readme_title_is_v070():
    first_line = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()[0]
    assert first_line.strip() == "# MarketVault v0.7.0"


def test_readme_no_development_wording():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "V0.5 development" not in text
    assert "V0.5 remains under development" not in text
    assert "release preparation pending" not in text


def test_readme_incremental_uses_trading_day_semantics():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "one calendar day after" not in text
    assert "first trading date strictly after" in text


def test_readme_mentions_boundary_not_evaluated():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "boundary_coverage" in text or "session boundaries" in text


def test_readme_does_not_claim_fixed_bar_counts():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    # Fixed counts only appear as negated boundaries ("no fixed daily bar
    # counts"); the README must never assert an expected count.
    assert "exactly 1440" not in text
    assert "exactly 390" not in text
    assert "exactly 1201" not in text
    assert "must contain 1440" not in text
    assert "requires 390" not in text


def test_changelog_contains_061():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [0.6.1] - 2026-08-08" in text


def test_changelog_still_contains_060():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [0.6.0] - 2026-08-08" in text


def test_changelog_still_contains_051():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [0.5.1] - 2026-08-06" in text


def test_changelog_still_contains_050():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [0.5.0] - 2026-08-05" in text


def test_changelog_still_contains_040():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [0.4.0] - 2026-08-05" in text


def test_changelog_contains_061_compare_link():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert (
        "[0.6.1]: https://github.com/M0DIAN/market-vault/compare/v0.6.0...v0.6.1"
        in text
    )


def test_changelog_still_contains_060_compare_link():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert (
        "[0.6.0]: https://github.com/M0DIAN/market-vault/compare/v0.5.1...v0.6.0"
        in text
    )


def test_changelog_still_contains_051_compare_link():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert (
        "[0.5.1]: https://github.com/M0DIAN/market-vault/compare/v0.5.0...v0.5.1"
        in text
    )


def test_release_notes_v051_exist():
    assert (ROOT / "docs" / "release_v0_5_1.md").is_file()


def test_release_notes_v050_still_present():
    assert (ROOT / "docs" / "release_v0_5_0.md").is_file()


def test_release_notes_v04_still_present():
    assert (ROOT / "docs" / "release_v0_4_0.md").is_file()


def test_release_notes_v03_still_present():
    assert (ROOT / "docs" / "release_v0_3_0.md").is_file()


def test_release_notes_contain_base_commits():
    text = (ROOT / "docs" / "release_v0_5_0.md").read_text(encoding="utf-8")
    # The v0.4.0 release-preparation base commit.
    assert "1225b0ae0c96ef7a27b4eae92d676c65394ee85e" in text
    # The PR-9 squash merge commit on main.
    assert "583db37b4f04014674a51b9908bf2409767fb291" in text


def test_release_notes_contain_development_prs():
    text = (ROOT / "docs" / "release_v0_5_0.md").read_text(encoding="utf-8")
    for number in range(20, 29):
        assert f"PR #{number}" in text


def test_release_notes_contain_dataset_boundaries():
    text = (ROOT / "docs" / "release_v0_5_0.md").read_text(encoding="utf-8")
    assert "No arbitrary user transforms" in text
    assert "No cross-trading-day Label" in text


def test_readme_contains_v04_foundation():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "V0.4 canonical and dataset foundation" in text


def test_readme_contains_upgrade_from_v03():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Upgrade from v0.3" in text


def test_readme_contains_upgrade_from_v04():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Upgrade from v0.4" in text


def test_readme_does_not_claim_builder_not_implemented():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "final Dataset builder is not implemented" not in text
    assert "no final Dataset CLI" not in text
    assert "no automatic Feature/Label value computation" not in text
    assert "no final Dataset Parquet export" not in text


def test_readme_contains_v05_builder_section():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "V0.5 deterministic Dataset builder" in text


def test_readme_describes_dataset_cli_commands():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "dataset-build --plan" in text
    assert "dataset-verify --build-dir" in text
    assert "dataset-inspect --build-dir" in text


def test_readme_describes_full_dataset_chain():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "verified Canonical builds" in text
    assert "verified Dataset reader" in text
    assert "immutable Dataset materialization" in text
    assert "label_status" in text
    assert "actual_label_end_time" in text


def test_readme_describes_explicit_build_plan():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "explicit" in text
    assert "build-plan JSON" in text


def test_readme_claims_v06_capabilities():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "# MarketVault v0.7.0" in text
    assert "deterministic sample generation" in text
    assert "Dataset Catalog" in text
    assert "sample-generate" in text
    assert "dataset-catalog-build" in text


def test_direction_document_is_released():
    text = (ROOT / "docs" / "v0_5_0_direction.md").read_text(encoding="utf-8")
    assert "Status: released" in text
    assert "Status: proposed" not in text
    assert "PR-10 has not started" not in text
    assert "Status: implementation complete; v0.5.0 release preparation" not in text
    assert "3b4d03c785123e204885faea08df7b9d7ed07ec0" in text


def test_readme_describes_ci_matrix():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Normal CI on Python 3.11 and 3.14" in text
    assert "PyArrow24 full-suite compatibility gate" in text


def test_readme_contains_empty_build_semantics():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "no eligible COMPLETE snapshots" in text
    assert "deterministic EMPTY build" in text
    assert "not converted into synthetic rows or internal-gap sidecar entries" in text


def test_readme_contains_gap_sidecar_scope():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "internal nominal-spacing gaps" in text
    assert "never infers leading/trailing/session gaps" in text


def test_readme_contains_market_available_at_precision():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "exact for bars known to span the complete nominal interval" in text
    assert "conservative leakage-safe not-before bound" in text


def test_readme_contains_dataset_boundaries():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "adjustment = NONE" in text
    assert "cross-trading-day" in text
    assert "arbitrary user code" in text
    assert "ML training" in text
    assert "backtest" in text
    assert "automatic trading" in text


def test_upgrade_notes_contain_legacy_compatibility():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Upgrade from v0.2" in text
    assert "batch-<batch_key>.parquet" in text


# --- V0.6 public API imports ------------------------------------------------


def test_v061_public_api_imports_succeed(tmp_path):
    result = run_code_in(tmp_path, PUBLIC_API_IMPORT_CODE)
    assert result.returncode == 0, result.stderr
    assert "V061_PUBLIC_API_IMPORT_OK" in result.stdout


def test_v061_public_api_imports_do_not_connect_opend(tmp_path):
    # The imports run from an empty directory without any settings file or
    # OpenD host; a collector connection attempt would fail loudly.
    result = run_code_in(tmp_path, PUBLIC_API_IMPORT_CODE)
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr


def test_v061_public_api_imports_do_not_write_data(tmp_path):
    result = run_code_in(tmp_path, PUBLIC_API_IMPORT_CODE)
    assert result.returncode == 0, result.stderr
    leftovers = {p.name for p in tmp_path.iterdir()}
    assert "data" not in leftovers
    assert "catalog" not in leftovers
    assert "manifests" not in leftovers
    assert "reports" not in leftovers


def test_v061_dataset_exports_are_public():
    import market_vault.dataset as dataset

    for name in (
        "orchestrate_dataset_build",
        "materialize_dataset_artifacts",
        "load_verified_dataset",
        "generate_sample_requests",
    ):
        assert name in dataset.__all__


# --- Release checker --------------------------------------------------------


def run_check_release(repo: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo / "src")
    # Force UTF-8 child stdout so the utf-8 decode below matches on any
    # locale (Windows GBK would otherwise mangle non-ASCII checker facts).
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / "check_release.py")],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def test_release_checker_passes_on_current_repo():
    result = run_check_release(ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"RELEASE_CHECK_OK version={EXPECTED_VERSION}" in result.stdout


def test_release_checker_output_is_exactly_release_check_ok_v070():
    result = run_check_release(ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "RELEASE_CHECK_OK version=0.7.0"


def test_release_checker_fails_on_version_mismatch(tmp_path):
    repo = copy_repo(tmp_path)
    pyproject = repo / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    pyproject.write_text(text.replace('version = "0.7.0"', 'version = "9.9.9"'), encoding="utf-8")
    version_file = repo / "src" / "market_vault" / "_version.py"
    version_file.write_text(
        version_file.read_text(encoding="utf-8").replace('"0.7.0"', '"9.9.9"'),
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "pyproject.toml version" in result.stdout
    assert "package __version__" in result.stdout


def test_release_checker_fails_on_cli_version_mismatch(tmp_path):
    repo = copy_repo(tmp_path)
    version_file = repo / "src" / "market_vault" / "_version.py"
    version_file.write_text(
        version_file.read_text(encoding="utf-8").replace('"0.7.0"', '"9.9.9"'),
        encoding="utf-8",
    )
    assert_check_fails(_check_release.check_cli_version, repo, "CLI --version output")


def test_release_checker_fails_on_development_wording(tmp_path):
    repo = copy_repo(tmp_path)
    readme = repo / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8") + "\nV0.5 development leftover\n",
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "V0.5 development" in result.stdout


def test_release_checker_fails_on_stale_builder_wording(tmp_path):
    repo = copy_repo(tmp_path)
    readme = repo / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8")
        + "\nfinal Dataset builder is not implemented\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_readme_no_stale_wording,
        repo,
        'final Dataset builder is not implemented',
    )


def test_release_checker_fails_without_changelog(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "CHANGELOG.md").unlink()
    assert_check_fails(_check_release.check_changelog, repo, "CHANGELOG.md")


def test_release_checker_fails_without_v05_release_notes(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "docs" / "release_v0_5_0.md").unlink()
    assert_check_fails(_check_release.check_release_notes, repo, "release_v0_5_0.md")


def test_release_checker_fails_without_v04_release_notes(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "docs" / "release_v0_4_0.md").unlink()
    assert_check_fails(_check_release.check_old_release_notes, repo, "release_v0_4_0.md")


def test_release_checker_fails_on_readme_title_mismatch(tmp_path):
    repo = copy_repo(tmp_path)
    readme = repo / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8").replace(
            "# MarketVault v0.7", "# MarketVault v9.9"
        ),
        encoding="utf-8",
    )
    assert_check_fails(_check_release.check_readme_title, repo, "README first line")


def test_release_checker_fails_on_old_ci_version_assertion(tmp_path):
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    text = ci.read_text(encoding="utf-8")
    ci.write_text(text.replace("'0.7.0'", "'0.3.0'"), encoding="utf-8")
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "package module version assertion" in result.stdout
    assert "distribution metadata assertion" in result.stdout
    assert "old version 0.3.0" in result.stdout


def test_release_checker_fails_on_wrong_package_assertion_only(tmp_path):
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    text = ci.read_text(encoding="utf-8")
    ci.write_text(
        text.replace(
            "assert market_vault.__version__ == '0.7.0'",
            "assert market_vault.__version__ == '9.9.9'",
        ),
        encoding="utf-8",
    )
    failures = assert_check_fails(
        _check_release.check_ci_version_assertions,
        repo,
        'package module version assertion',
    )
    assert 'distribution metadata assertion' not in "\n".join(failures)
    assert 'old version 0.3.0' not in "\n".join(failures)


def test_release_checker_fails_on_wrong_metadata_assertion_only(tmp_path):
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    text = ci.read_text(encoding="utf-8")
    ci.write_text(
        text.replace(
            "assert version('market-vault') == '0.7.0'",
            "assert version('market-vault') == '9.9.9'",
        ),
        encoding="utf-8",
    )
    failures = assert_check_fails(
        _check_release.check_ci_version_assertions,
        repo,
        'distribution metadata assertion',
    )
    assert 'package module version assertion' not in "\n".join(failures)
    assert 'old version 0.3.0' not in "\n".join(failures)


def test_release_checker_fails_on_wrong_public_api_marker(tmp_path):
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    text = ci.read_text(encoding="utf-8")
    ci.write_text(text.replace("V061_PUBLIC_API_IMPORT_OK", "V040_PUBLIC_API_IMPORT_OK"), encoding="utf-8")
    assert_check_fails(_check_release.check_ci_version_assertions, repo, "public API smoke marker")


def test_release_checker_fails_on_tracked_artifact(tmp_path):
    repo = copy_repo(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    tracked = repo / "data" / "tracked.txt"
    tracked.parent.mkdir(parents=True, exist_ok=True)
    tracked.write_text("x", encoding="utf-8")
    # data/ is gitignored; -f is required to make the artifact tracked.
    subprocess.run(["git", "add", "-f", "data/tracked.txt"], cwd=repo, check=True)
    assert_check_fails(_check_release.check_build_artifacts_untracked, repo, "tracked build artifact")


def test_release_checker_reports_all_failures_at_once(tmp_path):
    repo = copy_repo(tmp_path)
    pyproject = repo / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace('version = "0.7.0"', 'version = "9.9.9"'),
        encoding="utf-8",
    )
    (repo / "CHANGELOG.md").unlink()
    readme = repo / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8").replace(
            "# MarketVault v0.7", "# MarketVault v9.9"
        ),
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "pyproject.toml version" in result.stdout
    assert "CHANGELOG.md" in result.stdout
    assert "README first line" in result.stdout


def test_release_checker_fails_on_old_direction_status(tmp_path):
    # Reverting the v0.5.0 direction top status to the old
    # release-preparation wording must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_5_0_direction.md"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace(
            "Status: released on 2026-08-05",
            "Status: implementation complete; v0.5.0 release preparation (PR-10)",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_direction_status,
        repo,
        "does not state the released fact 'Status: released'",
        "still contains the stale wording 'Status: implementation complete; v0.5.0 release preparation'",
    )


def test_release_checker_fails_when_direction_missing_release_commit(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_5_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "3b4d03c785123e204885faea08df7b9d7ed07ec0",
            "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_direction_status,
        repo,
        "does not state the released fact '3b4d03c785123e204885faea08df7b9d7ed07ec0'",
    )


def test_release_checker_fails_when_release_notes_missing_pr29_merged(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_5_0.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("MERGED", "OPEN"),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_release_notes,
        repo,
        "does not state the release fact 'MERGED'",
    )


def test_release_checker_fails_when_release_notes_claim_pr29_still_open(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_5_0.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nGitHub PR #29 is still OPEN and not merged.\n",
        encoding="utf-8",
    )
    assert_check_fails(_check_release.check_release_notes, repo, "GitHub PR #29 is still OPEN")


def test_release_checker_fails_when_release_notes_missing_wheel_asset(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_5_0.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "market_vault-0.5.0-py3-none-any.whl",
            "market_vault-0.5.0-py3-none-any.egg",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_release_notes,
        repo,
        "does not state the release fact 'market_vault-0.5.0-py3-none-any.whl'",
    )


def test_release_checker_fails_when_release_notes_missing_sdist_asset(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_5_0.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "market_vault-0.5.0.tar.gz",
            "market_vault-0.5.0.tar.bz2",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_release_notes,
        repo,
        "does not state the release fact 'market_vault-0.5.0.tar.gz'",
    )


def test_release_checker_fails_without_v051_direction(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "docs" / "v0_5_1_direction.md").unlink()
    assert_check_fails(_check_release.check_v051_direction, repo, "docs/v0_5_1_direction.md is missing")


def test_release_checker_fails_when_v051_direction_reverts_to_planned(tmp_path):
    # Reverting the v0.5.1 direction top status to the pre-release
    # "Status: planned" must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_5_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "Status: released on 2026-08-06 JST",
            "Status: planned",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v051_direction,
        repo,
        "does not state the fact 'Status: released on 2026-08-06 JST'",
        "still contains the stale wording 'Status: planned'",
    )


def test_release_checker_fails_when_v051_direction_reverts_to_release_preparation(
    tmp_path,
):
    # Restoring the pre-release release-preparation top status must fail the
    # checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_5_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "Status: released on 2026-08-06 JST",
            "Status: implementation complete; v0.5.1 release preparation",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v051_direction,
        repo,
        "does not state the fact 'Status: released on 2026-08-06 JST'",
        "still contains the stale wording 'Status: implementation complete; v0.5.1 release preparation'",
    )


def test_release_checker_fails_when_v051_direction_missing_release_commit(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_5_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "a978eef291d5e26d20e5cf977bc76609c227cb52",
            "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v051_direction,
        repo,
        "does not state the fact 'a978eef291d5e26d20e5cf977bc76609c227cb52'",
    )


def test_release_checker_fails_when_v051_direction_missing_main_ci_run(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_5_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "31029709970",
            "00000000000000000000",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v051_direction,
        repo,
        "does not state the fact '31029709970'",
    )


def test_release_checker_fails_when_release_notes_missing_pr33_merged(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_5_1.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("MERGED", "OPEN"),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v051_release_notes,
        repo,
        "does not state the fact 'MERGED'",
    )


def test_release_checker_fails_when_formal_section_claims_pr4_still_open(tmp_path):
    # A stale current-state sentence in the formal region (before the
    # historical release-preparation record) must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_5_1.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "## Historical release-preparation record",
            "PR-4 is open and not merged.\n\n"
            "## Historical release-preparation record",
            1,
        ),
        encoding="utf-8",
    )
    assert_check_fails(_check_release.check_v051_release_notes, repo, "PR-4 is open and not merged")


def test_release_checker_fails_when_release_notes_missing_wheel_hash(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_5_1.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "80965A671AEEF75F315386D9BD4B62EC5DC08E552CB3430AEF92F83C562248C1",
            "0000000000000000000000000000000000000000000000000000000000000000",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v051_release_notes,
        repo,
        "does not state the fact '80965A671AEEF75F315386D9BD4B62EC5DC08E552CB3430AEF92F83C562248C1'",
    )


def test_release_checker_fails_when_release_notes_missing_sdist_hash(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_5_1.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "FE82FB4FD254C493EC00519EDEB438533C0C5E8D5A7690E1F14AEA39DE4CCDAB",
            "0000000000000000000000000000000000000000000000000000000000000000",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v051_release_notes,
        repo,
        "does not state the fact 'FE82FB4FD254C493EC00519EDEB438533C0C5E8D5A7690E1F14AEA39DE4CCDAB'",
    )


def test_release_checker_fails_when_asset_source_reverts_to_release_preparation_build(
    tmp_path,
):
    # Reverting the formal asset source to "built by the release-preparation
    # PR" must fail the checker: the formal assets were rebuilt after the
    # merge from the exact release commit.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_5_1.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "rebuilt from the exact release commit",
            "built by the release-preparation PR",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v051_release_notes,
        repo,
        "does not state the fact 'rebuilt from the exact release commit'",
    )


def test_release_notes_allow_released_phrase_in_formal_section(tmp_path):
    # "v0.5.1 is released" is now a legal formal-state expression in the
    # current-state region of the release notes.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_5_1.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "## Historical release-preparation record",
            "v0.5.1 is released.\n\n## Historical release-preparation record",
            1,
        ),
        encoding="utf-8",
    )
    assert _check_release.check_v051_release_notes(repo) == []


def test_release_checker_allows_historical_pr4_open_sentence(tmp_path):
    # The historical release-preparation record may quote the
    # preparation-time state verbatim; the checker must not reject it.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_5_1.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nPR-4 is open and not merged.\n",
        encoding="utf-8",
    )
    assert _check_release.check_v051_release_notes(repo) == []


def test_release_checker_fails_without_v060_direction(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "docs" / "v0_6_0_direction.md").unlink()
    assert_check_fails(_check_release.check_v060_direction, repo, "docs/v0_6_0_direction.md is missing")


def test_release_checker_fails_when_v060_direction_reverts_to_planned(
    tmp_path,
):
    # Reverting the v0.6.0 direction top status back to the old
    # pre-release "Status: planned" wording must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "Status: released on 2026-08-08",
            "Status: planned",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v060_direction,
        repo,
        "does not state the fact 'Status: released on 2026-08-08'",
        "still contains the stale wording 'Status: planned'",
    )


def test_release_checker_fails_when_v060_direction_reclaims_pr9_not_started(
    tmp_path,
):
    # "PR-9 has not started" is stale wording in the current-state
    # regions (header / Progress section); reintroducing it must fail.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\nPR-9 has not started.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v060_direction,
        repo,
        "still contains the stale wording 'PR-9 has not started'",
    )


def test_release_checker_fails_when_v060_direction_reverts_to_release_preparation(
    tmp_path,
):
    # Reverting the v0.6.0 direction top status back to the
    # release-preparation wording must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "Status: released on 2026-08-08",
            "Status: implementation complete; v0.6.0 release preparation",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v060_direction,
        repo,
        "does not state the fact 'Status: released on 2026-08-08'",
        "still contains the stale wording 'Status: implementation complete; v0.6.0 release preparation'",
    )


def test_release_checker_fails_when_v060_direction_reclaims_pr8_this_pr(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\nPR-8 (this PR) is complete.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v060_direction,
        repo,
        "still contains the stale wording 'PR-8 (this PR)'",
    )


def test_release_checker_fails_when_v060_direction_claims_pypi_published(
    tmp_path,
):
    # The GitHub Release exists, but a PyPI publication claim must fail:
    # PyPI and TestPyPI are NOT PUBLISHED.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\nPyPI published.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v060_direction,
        repo,
        "contains the false release claim 'PyPI published'",
    )


def test_release_checker_fails_when_v060_direction_includes_python_client_in_v06(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "not part of v0.6",
            "part of v0.6",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v060_direction,
        repo,
        "does not state the fact 'not part of v0.6'",
    )


# --- V0.6.1 maintenance direction guards ------------------------------------


def test_v061_direction_document_states_released_state():
    text = (ROOT / "docs" / "v0_6_1_direction.md").read_text(encoding="utf-8")
    assert "Status: released on 2026-08-08" in text
    assert "Stability, Auditability, and Usability Maintenance" in text
    assert "669c955abc0a234264964dfdb7fcafdf502a901a" in text
    assert "package version at planning time: 0.6.0" in text
    for number in range(1, 5):
        assert f"PR-{number}" in text
    assert "0.6.0 through PR-3" in text
    assert "bumped to 0.6.1 only in PR-4" in text
    # The released-state narrative: every stage is COMPLETE and merged as
    # PR #44, PR #45, PR #46, and PR #47; the release is sealed at the
    # release commit; the v0.6.1 tag is created; the GitHub Release
    # MarketVault v0.6.1 is published; PyPI / TestPyPI are NOT PUBLISHED;
    # future feature development continues in docs/v0_7_0_direction.md.
    assert "PR-1 COMPLETE: PR #44 merged at" in text
    assert "6bb9a9500fae53511ff964f47e5ccea20f3d91f7" in text
    assert "PR-2 COMPLETE: PR #45 merged at" in text
    assert "33d7f5856bf060527ccf4d2ab679df4429009ce6" in text
    assert "PR-3 COMPLETE: PR #46 merged at" in text
    assert "99c2e7bd445333740806dedec4aed03f82f32b11" in text
    assert "PR-4 COMPLETE: PR #47 merged at" in text
    assert "37614d539171ef7b738e47415f3cd6ca2de332d1" in text
    assert "V0.6.1 is formally released" in text
    assert "The v0.6.1 tag is created" in text
    assert "The GitHub Release MarketVault v0.6.1 is published" in text
    assert "PyPI: NOT PUBLISHED" in text
    assert "TestPyPI: NOT PUBLISHED" in text
    assert "docs/v0_7_0_direction.md" in text
    assert "The fixed 4-PR sequence itself remains" in text
    assert "unchanged as the historical record" in text
    # None of the stale lifecycle wordings may reappear.
    assert "Status: planned maintenance release" not in text
    assert "Status: implementation complete; v0.6.1 release preparation" not in text
    assert "V0.6.1 maintenance development is in PR-3" not in text
    assert (
        "PR-3 is the current CI/package auditability and maintenance-"
        "hardening stage"
    ) not in text
    assert "PR-4 has not started" not in text
    assert "PR-4 is the current v0.6.1 release-preparation stage" not in text
    assert "The package version is now 0.6.1 in PR-4" not in text
    assert "Package remains 0.6.0" not in text
    assert "PR-1 is the current maintenance-baseline and direction stage" not in text
    assert "PR-2 has not started" not in text
    assert (
        "PR-2 is the current CLI/help/error/usability consistency-polish "
        "stage"
    ) not in text
    assert "PR-3 has not started" not in text
    assert "The release is not started" not in text
    assert "V0.6.1 is NOT formally released" not in text
    assert "The v0.6.1 tag has not been created" not in text
    assert "The GitHub Release v0.6.1 has not been published" not in text
    assert "PyPI is not published" not in text
    assert "TestPyPI is not published" not in text
    for marker in (
        "Python Client",
        "REST API",
        "Dataset Catalog query command",
        "identity v2",
        "schema v2",
        "dependency modernization",
        "PyArrow runtime pin",
        "ML training",
        "backtesting",
        "signals",
        "automatic trading",
        "Trading Execution",
        "Canonical identity algorithms unchanged",
        "Dataset identity algorithms unchanged",
        "CLI command set unchanged",
    ):
        assert marker in text


def test_release_checker_fails_without_v061_direction(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "docs" / "v0_6_1_direction.md").unlink()
    assert_check_fails(_check_release.check_v061_direction, repo, "docs/v0_6_1_direction.md is missing")


def test_release_checker_fails_when_v061_direction_adds_python_client(tmp_path):
    # Sneaking the Python Client into v0.6.1 must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nThe Python Client is part of v0.6.1.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_direction,
        repo,
        "contains the false claim 'Python Client is part of v0.6.1'",
    )


def test_release_checker_fails_when_v061_direction_adds_dataset_catalog_query(
    tmp_path,
):
    # Sneaking a Dataset Catalog query command into v0.6.1 must fail.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nPR-2 adds the Dataset Catalog query command.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_direction,
        repo,
        'adds the Dataset Catalog query command',
    )


def test_release_checker_fails_when_v061_direction_bumps_version_early(tmp_path):
    # Moving the 0.6.1 bump out of PR-4 must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "bumped to 0.6.1 only in PR-4",
            "bumped to 0.6.1 in PR-2",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_direction,
        repo,
        "does not state the fact 'bumped to 0.6.1 only in PR-4'",
    )


def test_release_checker_fails_when_v061_direction_pr_sequence_changed(tmp_path):
    # Changing the fixed 4-PR sequence (PR-4 is the release preparation)
    # must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "v0.6.1 release preparation",
            "v0.6.1 feature release",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_direction,
        repo,
        "does not state the fact 'v0.6.1 release preparation'",
    )


def test_release_checker_fails_when_v061_direction_invariant_lost(tmp_path):
    # Losing a frozen invariant must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "Canonical identity algorithms unchanged",
            "Canonical identity algorithms changed",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_direction,
        repo,
        "does not state the frozen invariant 'Canonical identity algorithms unchanged'",
    )


def test_release_checker_fails_when_v061_direction_reverts_current_stage(
    tmp_path,
):
    # Reverting the released-state narrative to the stale "The release is
    # not started" wording must fail the checker: the stale phrase is
    # banned and the released facts are lost.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-4 COMPLETE: PR #47 merged at",
            "The release is not started.",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_direction,
        repo,
        "still contains the stale wording 'The release is not started'",
        "does not state the fact 'PR-4 COMPLETE: PR #47 merged at'",
    )


def test_release_checker_fails_when_v061_direction_reverts_to_pr1_current(
    tmp_path,
):
    # Reverting to the PR-1 stage wording ("PR-1 is the current
    # maintenance-baseline and direction stage") must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-1 COMPLETE: PR #44 merged at",
            "PR-1 is the current maintenance-baseline and direction stage",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_direction,
        repo,
        "still contains the stale wording 'PR-1 is the current maintenance-baseline and direction stage'",
        "does not state the fact 'PR-1 COMPLETE: PR #44 merged at'",
    )


def test_release_checker_fails_when_v061_direction_reverts_pr2_not_started(
    tmp_path,
):
    # Reverting to "PR-2 has not started" must fail the checker: PR-2 is
    # complete and merged.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-2 COMPLETE: PR #45 merged at",
            "PR-2 has not started.",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_direction,
        repo,
        "still contains the stale wording 'PR-2 has not started'",
    )


def test_release_checker_fails_when_v061_direction_loses_pr44_baseline(
    tmp_path,
):
    # Removing the PR #44 merged-baseline claim must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-1 COMPLETE: PR #44 merged at",
            "PR-1 is complete",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_direction,
        repo,
        "does not state the fact 'PR-1 COMPLETE: PR #44 merged at'",
    )


def test_release_checker_fails_when_v061_direction_squash_sha_changed(
    tmp_path,
):
    # Changing the PR-1 squash baseline SHA must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "6bb9a9500fae53511ff964f47e5ccea20f3d91f7",
            "0000000000000000000000000000000000000000",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_direction,
        repo,
        "does not state the fact '6bb9a9500fae53511ff964f47e5ccea20f3d91f7'",
    )


def test_release_checker_fails_when_v061_direction_claims_pr3_current(
    tmp_path,
):
    # Reverting to "PR-3 is the current CI/package auditability and
    # maintenance-hardening stage" must fail the checker: PR-3 is COMPLETE
    # and merged, and the release is sealed.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-3 COMPLETE: PR #46 merged at",
            "PR-3 is the current CI/package auditability and "
            "maintenance-hardening stage.",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_direction,
        repo,
        "still contains the stale wording 'PR-3 is the current CI/package auditability and maintenance-hardening stage'",
        "does not state the fact 'PR-3 COMPLETE: PR #46 merged at'",
    )


def test_release_checker_fails_without_v061_cli_usability_audit(tmp_path):
    # The PR-2 CLI usability audit document is a pinned deliverable.
    repo = copy_repo(tmp_path)
    (repo / "docs" / "v0_6_1_cli_usability_audit.md").unlink()
    assert_check_fails(
        _check_release.check_v061_cli_usability_audit,
        repo,
        'docs/v0_6_1_cli_usability_audit.md is missing',
    )


# --- V0.6.1 PR-3 CI/package auditability guards -----------------------------


def test_v061_ci_package_audit_document_states_audit_chain():
    text = (ROOT / "docs" / "v0_6_1_ci_package_audit.md").read_text(encoding="utf-8")
    assert "MarketVault v0.6.1 CI and Package Auditability" in text
    assert "33d7f5856bf060527ccf4d2ab679df4429009ce6" in text
    assert "actions/checkout@v6" in text
    assert "actions/setup-python@v6" in text
    assert "actions/upload-artifact@v7" in text
    assert "SHA256SUMS.txt" in text
    assert "artifact-digest" in text
    assert "V061_PACKAGE_AUDIT_OK" in text
    # The raw-file-SHA256 vs GitHub artifact-digest distinction must be
    # documented explicitly.
    assert "artifact-digest" in text
    assert "RAW wheel" in text
    assert "container/archive" in text


def test_release_checker_fails_when_v061_direction_reverts_to_pr2_current(
    tmp_path,
):
    # Reverting the released-state narrative to the stale PR-2 current
    # wording must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-2 COMPLETE: PR #45 merged at",
            "PR-2 is the current CLI/help/error/usability consistency-"
            "polish stage.",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_direction,
        repo,
        "still contains the stale wording 'PR-2 is the current CLI/help/error/usability consistency-polish stage'",
    )


def test_release_checker_fails_when_v061_direction_says_pr3_not_started(
    tmp_path,
):
    # Reverting to "PR-3 has not started" must fail the checker: PR-3 is
    # COMPLETE and merged.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-3 COMPLETE: PR #46 merged at",
            "PR-3 has not started",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_direction,
        repo,
        "still contains the stale wording 'PR-3 has not started'",
        "does not state the fact 'PR-3 COMPLETE: PR #46 merged at'",
    )


def test_release_checker_fails_when_v061_direction_loses_pr45_baseline(
    tmp_path,
):
    # Removing the PR #45 merged-baseline claim must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-2 COMPLETE: PR #45 merged at",
            "PR-2 is complete",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_direction,
        repo,
        "does not state the fact 'PR-2 COMPLETE: PR #45 merged at'",
    )


def test_release_checker_fails_when_v061_direction_pr45_squash_sha_changed(
    tmp_path,
):
    # Changing the PR-2 squash baseline SHA must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "33d7f5856bf060527ccf4d2ab679df4429009ce6",
            "0000000000000000000000000000000000000000",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_direction,
        repo,
        "does not state the fact '33d7f5856bf060527ccf4d2ab679df4429009ce6'",
    )


def test_release_checker_fails_when_v061_direction_claims_pr4_not_started(
    tmp_path,
):
    # Reverting to "PR-4 has not started" must fail the checker: PR-4 is
    # complete and merged.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-4 COMPLETE: PR #47 merged at",
            "PR-4 has not started.",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_direction,
        repo,
        "still contains the stale wording 'PR-4 has not started'",
        "does not state the fact 'PR-4 COMPLETE: PR #47 merged at'",
    )


def test_release_checker_fails_when_v061_direction_loses_release_prep_status(
    tmp_path,
):
    # Losing the released status must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "Status: released on 2026-08-08",
            "Status: planned",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_direction,
        repo,
        "does not state the fact 'Status: released on 2026-08-08'",
        "still contains the stale wording 'Status: planned'",
    )


def test_release_checker_fails_when_v061_direction_package_still_060(
    tmp_path,
):
    # Reverting the package version claim to "Package remains 0.6.0" must
    # fail the checker: the stale phrase is banned.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "The package version is 0.6.1.",
            "Package remains 0.6.0.",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_direction,
        repo,
        "still contains the stale wording 'Package remains 0.6.0'",
    )


def test_release_checker_fails_when_v061_direction_reverts_to_not_released(
    tmp_path,
):
    # Reverting the released-state claim to "V0.6.1 is NOT formally
    # released" must fail the checker: the stale phrase is banned.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nV0.6.1 is NOT formally released.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_direction,
        repo,
        "still contains the stale wording 'V0.6.1 is NOT formally released'",
    )


def test_release_checker_fails_when_v061_direction_claims_tag_not_created(
    tmp_path,
):
    # Reverting to "The v0.6.1 tag has not been created" must fail the
    # checker: the stale phrase is banned.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nThe v0.6.1 tag has not been created.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_direction,
        repo,
        "still contains the stale wording 'The v0.6.1 tag has not been created'",
    )


def test_release_checker_fails_when_v061_direction_claims_release_not_published(
    tmp_path,
):
    # Reverting to "The GitHub Release v0.6.1 has not been published" must
    # fail the checker: the stale phrase is banned.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nThe GitHub Release v0.6.1 has not been published.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_direction,
        repo,
        "still contains the stale wording 'The GitHub Release v0.6.1 has not been published'",
    )


def test_release_checker_fails_when_v061_direction_claims_pypi_published(
    tmp_path,
):
    # Claiming a PyPI publication must fail the checker: PyPI is NOT
    # PUBLISHED.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PyPI: NOT PUBLISHED.",
            "PyPI: PUBLISHED.",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_direction,
        repo,
        "contains the false release claim 'PyPI: PUBLISHED'",
    )


def test_release_checker_fails_without_v061_ci_package_audit(tmp_path):
    # The PR-3 CI/package audit document is a pinned deliverable.
    repo = copy_repo(tmp_path)
    (repo / "docs" / "v0_6_1_ci_package_audit.md").unlink()
    assert_check_fails(
        _check_release.check_v061_ci_package_audit,
        repo,
        'docs/v0_6_1_ci_package_audit.md is missing',
    )


def test_release_checker_fails_when_ci_restores_checkout_v4(tmp_path):
    # Restoring the stale Node-20-targeting checkout@v4 must fail.
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8").replace(
            "actions/checkout@v6",
            "actions/checkout@v4",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_ci_auditability,
        repo,
        "CI must never restore the stale Action major 'actions/checkout@v4'",
    )


def test_release_checker_fails_when_ci_restores_setup_python_v5(tmp_path):
    # Restoring the stale Node-20-targeting setup-python@v5 must fail.
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8").replace(
            "actions/setup-python@v6",
            "actions/setup-python@v5",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_ci_auditability,
        repo,
        "CI must never restore the stale Action major 'actions/setup-python@v5'",
    )


def test_release_checker_fails_when_ci_drops_upload_artifact_v7(tmp_path):
    # Removing the Node-24 upload-artifact major must fail.
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8").replace(
            "actions/upload-artifact@v7",
            "actions/upload-artifact@v4",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_ci_auditability,
        repo,
        "CI must use the Node-24 Action major 'actions/upload-artifact@v7'",
    )


def test_release_checker_fails_when_ci_drops_package_audit_ok(tmp_path):
    # Removing the V061_PACKAGE_AUDIT_OK marker must fail.
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8").replace(
            "V061_PACKAGE_AUDIT_OK",
            "V061_PACKAGE_AUDIT_MISSING",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_ci_auditability,
        repo,
        "CI package audit chain is missing 'V061_PACKAGE_AUDIT_OK'",
    )


def test_release_checker_fails_when_ci_reverts_to_github_sha_only_artifact_name(
    tmp_path,
):
    # Reverting the package artifact name to the github.sha-only binding
    # (which is the synthetic merge-ref commit on pull_request runs, not
    # the reviewed PR head) must fail the checker.
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8").replace(
            "market-vault-package-${{ github.event.pull_request.head.sha || "
            "github.sha }}-attempt-${{ github.run_attempt }}",
            "market-vault-package-${{ github.sha }}-attempt-${{ github.run_attempt }}",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_ci_auditability,
        repo,
        'CI package artifact name regressed to github.sha-only naming',
    )


# --- V0.6.1 release preparation guards --------------------------------------


def test_release_notes_state_formal_release_status():
    text = (ROOT / "docs" / "release_v0_6_1.md").read_text(encoding="utf-8")
    assert "## Formal release status" in text
    assert "formally released" in text
    assert "PR-4: PR #47 MERGED" in text
    assert "2026-08-08T12:20:16Z" in text
    assert "37614d539171ef7b738e47415f3cd6ca2de332d1" in text
    assert "31257004716" in text
    assert "0e0508065a6330d643e7801823e908fee881afc9" in text
    assert "MarketVault v0.6.1" in text
    assert "367204479" in text
    assert "2026-08-08T13:06:51Z" in text
    assert "PyPI: NOT PUBLISHED" in text
    assert "TestPyPI: NOT PUBLISHED" in text
    assert (
        "8fd8ec510a7724742d6e3e9fbca5c73b07e991cb3fa35002af792a8dd64ed550"
        in text
    )
    assert (
        "0cadd537a0980978a9a0878766cb2234f5b419f3f5d3874ef92e300c76c756f1"
        in text
    )
    assert "## Historical release-preparation record" in text
    assert "99c2e7bd445333740806dedec4aed03f82f32b11" in text
    assert "PR-1: PR #44 MERGED 6bb9a9500fae53511ff964f47e5ccea20f3d91f7" in text
    assert "PR-2: PR #45 MERGED 33d7f5856bf060527ccf4d2ab679df4429009ce6" in text
    assert "PR-3: PR #46 MERGED 99c2e7bd445333740806dedec4aed03f82f32b11" in text
    assert "PR-4: current release-preparation stage, OPEN / UNMERGED" in text
    assert "package version in PR-4: 0.6.1" in text
    assert "v0.6.1 tag:            NOT CREATED" in text
    assert "GitHub Release v0.6.1: NOT PUBLISHED" in text
    assert "PyPI:                  NOT PUBLISHED" in text
    assert "TestPyPI:              NOT PUBLISHED" in text
    assert "No future merge SHA was claimed" in text
    assert "no formal artifact SHA256 values" in text
    assert "candidate validation only" in text
    assert "CI audit artifact" in text
    assert "new product capabilities = 0" in text
    assert "PR candidate hashes: not reused as formal release asset hashes" in text
    assert "## Release preparation status" not in text
    assert "NOT formally released" not in text
    assert "PR-4 is open" not in text
    assert "PyPI: PUBLISHED" not in text
    assert "TestPyPI: PUBLISHED" not in text


def test_release_checker_fails_without_v061_release_notes(tmp_path):
    # The v0.6.1 release notes are a pinned PR-4 deliverable.
    repo = copy_repo(tmp_path)
    (repo / "docs" / "release_v0_6_1.md").unlink()
    assert_check_fails(
        _check_release.check_v061_release_notes,
        repo,
        'docs/release_v0_6_1.md is missing',
    )


def test_release_checker_fails_when_release_notes_revert_to_preparation_status(
    tmp_path,
):
    # Reverting the release notes header to a release-preparation status
    # must fail the checker: the formal facts are lost and the stale
    # header appears in the formal region.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_6_1.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "## Formal release status",
            "## Release preparation status",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_release_notes,
        repo,
        "does not state the fact '## Formal release status'",
        "formal region contains the stale release claim '## Release preparation status'",
    )


def test_release_checker_fails_when_release_notes_claim_tag_created(
    tmp_path,
):
    # Claiming the v0.6.1 tag was created must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_6_1.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "v0.6.1 tag:            NOT CREATED",
            "v0.6.1 tag:            CREATED",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_release_notes,
        repo,
        "does not state the fact 'v0.6.1 tag:            NOT CREATED'",
    )


def test_release_checker_fails_when_release_notes_claim_github_release_published(
    tmp_path,
):
    # Claiming the GitHub Release was published must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_6_1.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "GitHub Release v0.6.1: NOT PUBLISHED",
            "GitHub Release v0.6.1: PUBLISHED",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_release_notes,
        repo,
        "does not state the fact 'GitHub Release v0.6.1: NOT PUBLISHED'",
    )


def test_release_checker_fails_when_release_notes_claim_pypi_published(
    tmp_path,
):
    # Claiming a PyPI publication must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_6_1.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PyPI:                  NOT PUBLISHED",
            "PyPI:                  PUBLISHED",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_release_notes,
        repo,
        "does not state the fact 'PyPI:                  NOT PUBLISHED'",
    )


def test_release_checker_fails_when_release_notes_claim_testpypi_published(
    tmp_path,
):
    # Claiming a TestPyPI publication must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_6_1.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "TestPyPI:              NOT PUBLISHED",
            "TestPyPI:              PUBLISHED",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_release_notes,
        repo,
        "does not state the fact 'TestPyPI:              NOT PUBLISHED'",
    )


def test_release_checker_fails_when_release_notes_claim_pr4_merged(
    tmp_path,
):
    # Tampering with the historical release-preparation record (claiming
    # PR-4 merged instead of OPEN / UNMERGED at preparation time) must
    # fail the checker: the preparation-time fact is lost.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_6_1.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-4: current release-preparation stage, OPEN / UNMERGED",
            "PR-4 MERGED",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_release_notes,
        repo,
        "does not state the fact 'PR-4: current release-preparation stage, OPEN / UNMERGED'",
    )


def test_release_checker_fails_when_release_notes_lose_candidate_distinction(
    tmp_path,
):
    # Losing the candidate-vs-formal artifact distinction must fail the
    # checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_6_1.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "candidate validation only;",
            "candidate validation;",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_release_notes,
        repo,
        "does not state the fact 'candidate validation only'",
    )


def test_release_checker_fails_when_release_notes_lose_merge_record(
    tmp_path,
):
    # Removing the PR-1 merged record must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_6_1.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-1: PR #44 MERGED 6bb9a9500fae53511ff964f47e5ccea20f3d91f7",
            "PR-1: PR #44 MERGED",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_release_notes,
        repo,
        "does not state the fact 'PR-1: PR #44 MERGED 6bb9a9500fae53511ff964f47e5ccea20f3d91f7'",
    )


# --- V0.6.1 README / version / CI release-preparation guards ----------------


def test_readme_v061_section_states_maintenance_facts():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## V0.6.1 stability, auditability, and usability maintenance" in text
    assert "V0.6.1 adds NO new product capability" in text
    assert "### A. Lifecycle / release-state truth" in text
    assert "### B. CLI usability wording" in text
    assert "### C. CI/package auditability" in text
    assert "SHA256SUMS.txt" in text
    assert "V061_PACKAGE_AUDIT_OK" in text
    assert "v0.6.1 formal release is published and sealed" in text
    assert "37614d539171ef7b738e47415f3cd6ca2de332d1" in text
    assert "MarketVault v0.6.1" in text
    assert "PyPI: NOT PUBLISHED" in text
    assert "TestPyPI: NOT PUBLISHED" in text
    assert "the v0.6.1 formal release does not exist yet" not in text


def test_release_checker_fails_when_readme_loses_v061_section(tmp_path):
    # Removing the v0.6.1 maintenance section header must fail the
    # checker.
    repo = copy_repo(tmp_path)
    readme = repo / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8").replace(
            "## V0.6.1 stability, auditability, and usability maintenance",
            "## V0.6.1 section removed",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_readme_v061_section,
        repo,
        "does not state the v0.6.1 maintenance fact '## V0.6.1 stability, auditability, and usability maintenance'",
    )


def test_release_checker_fails_when_readme_reverts_to_not_released(tmp_path):
    # Reverting the README to the stale "the v0.6.1 formal release does
    # not exist yet" wording must fail the checker even when all required
    # facts are present.
    repo = copy_repo(tmp_path)
    readme = repo / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8")
        + "\nthe v0.6.1 formal release does not exist yet.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_readme_v061_section,
        repo,
        "README contains the stale v0.6.1 release-state wording 'the v0.6.1 formal release does not exist yet'",
    )


def test_release_checker_fails_when_version_reverts_to_060(tmp_path):
    # Reverting pyproject.toml and _version.py to 0.6.0 must fail the
    # checker.
    repo = copy_repo(tmp_path)
    pyproject = repo / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            'version = "0.7.0"', 'version = "0.6.0"'
        ),
        encoding="utf-8",
    )
    version_file = repo / "src" / "market_vault" / "_version.py"
    version_file.write_text(
        version_file.read_text(encoding="utf-8").replace(
            '"0.7.0"', '"0.6.0"'
        ),
        encoding="utf-8",
    )
    assert_check_fails(_check_release.check_pyproject_version, repo, "pyproject.toml version")
    assert_check_fails(_check_release.check_package_version, repo, "package __version__")


def test_release_checker_fails_when_readme_title_reverts_to_v060(tmp_path):
    # Reverting the README title to v0.6.0 must fail the checker.
    repo = copy_repo(tmp_path)
    readme = repo / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8").replace(
            "# MarketVault v0.7.0",
            "# MarketVault v0.6.0",
        ),
        encoding="utf-8",
    )
    assert_check_fails(_check_release.check_readme_title, repo, "README first line")


def test_release_checker_fails_when_changelog_loses_061_entry(tmp_path):
    # Removing the [0.6.1] CHANGELOG entry must fail the checker.
    repo = copy_repo(tmp_path)
    changelog = repo / "CHANGELOG.md"
    changelog.write_text(
        changelog.read_text(encoding="utf-8").replace(
            "## [0.6.1] - 2026-08-08",
            "## [0.6.0] - 2026-08-08",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_changelog,
        repo,
        "CHANGELOG.md is missing '## [0.6.1] - 2026-08-08'",
    )


def test_release_checker_fails_when_ci_wheel_assertion_reverts_to_060(
    tmp_path,
):
    # Reverting the CI wheel version assertions to 0.6.0 must fail the
    # checker.
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8").replace("'0.7.0'", "'0.6.0'"),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_ci_version_assertions,
        repo,
        'package module version assertion',
        'distribution metadata assertion',
    )


def test_release_checker_fails_when_ci_claims_v061_released(tmp_path):
    # Claiming the V061_RELEASED state in CI must fail the checker: the
    # marker set is V061_RELEASE_STATE_OK, never V061_RELEASED.
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8")
        + "\necho 'V061_RELEASED'\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_ci_v070_released_state,
        repo,
        'must never claim the V061_RELEASED state',
    )


# --- V0.7.0 PR-1 boundary / mutation guards ----------------------------------


def test_v070_direction_document_states_baseline_and_sequence():
    text = (ROOT / "docs" / "v0_7_0_direction.md").read_text(encoding="utf-8")
    assert "# MarketVault v0.7.0 Direction: Python Client and Read-only Artifact Access" in text
    assert "Status: released on 2026-08-09" in text
    assert "base version: v0.6.1" in text
    assert "37614d539171ef7b738e47415f3cd6ca2de332d1" in text
    assert "v0.7.0: FORMALLY RELEASED" in text
    assert "PR-1: COMPLETE / MERGED / MAIN VERIFIED" in text
    assert "PR-2: COMPLETE / MERGED / MAIN VERIFIED" in text
    assert "PR-3: COMPLETE / MERGED / MAIN VERIFIED" in text
    assert "PR-4: COMPLETE / MERGED / MAIN VERIFIED" in text
    assert "PR-5: COMPLETE / MERGED / MAIN VERIFIED" in text
    assert "PR-6: COMPLETE / MERGED / RELEASED" in text
    assert "PR #48 merged at 2026-08-08T23:50:24Z" in text
    assert "bad62ee51e8eda03c7c5f20ac858973923e5f93d" in text
    assert "31284875166" in text
    assert "PR #49 merged at 2026-08-09T01:24:46Z" in text
    assert "1a3ca95a6765e4418e753f1fec6d5c79b8e49e2f" in text
    assert "42c63ebfb0c2dfc91b1d61860bed2106faf1bba0" in text
    assert "31288212317" in text
    assert "ArtifactClient foundation: IMPLEMENTED" in text
    assert "Canonical / Dataset / Catalog reads at PR-2: NOT IMPLEMENTED" in text
    assert "PR #50 merged at 2026-08-09T05:34:20Z" in text
    assert "01d40bd9a090dc1e23d9539aa57a8649c0d64b7c" in text
    assert "61a2b055163815d463d5b261f5b6a94e54e515bd" in text
    assert "31296976872" in text
    assert "ArtifactClient Canonical verified read: IMPLEMENTED" in text
    assert "ArtifactClient Dataset verified read: IMPLEMENTED" in text
    assert "Dataset Catalog client read at PR-3: NOT IMPLEMENTED" in text
    assert "PR #51 merged at 2026-08-09T07:42:17Z" in text
    assert "49dbc9fdc53d40d0955febe61c87e9cb71dcc159" in text
    assert "8b6bb12355c64d02c7e4f73fc67b6222ff2af6ed" in text
    assert "31301770295" in text
    assert "ArtifactClient Dataset Catalog verified read: IMPLEMENTED" in text
    assert "PR #52 merged at 2026-08-09T10:07:06Z" in text
    assert "2f7ee8dd6c7c3ce07f677be99cdd8afb8f2c68d4" in text
    assert "5ec437d37bb2cde0b716aa5dc1f84538b4bc6215" in text
    assert "31307554050" in text
    assert "package before PR-6: 0.6.1" in text
    assert "ArtifactClient integrated E2E acceptance: IMPLEMENTED" in text
    assert "consumer usability docs and source-tree examples: IMPLEMENTED" in text
    assert "package: 0.7.0" in text
    for stage in (
        "PR-1 — Post-v0.6.1 release baseline",
        "PR-2 — Settings-independent ArtifactClient foundation",
        "PR-3 — Canonical + Dataset verified read-only client access",
        "PR-4 — Dataset Catalog verified read-only client access",
        "PR-5 — Integrated E2E",
        "PR-6 — v0.7.0 release preparation",
    ):
        assert stage in text
    assert "Then a separate explicit GitHub Release gate" in text
    assert "PR-1: 0.6.1" in text
    assert "PR-2: 0.6.1" in text
    assert "PR-3: 0.6.1" in text
    assert "PR-4: 0.6.1" in text
    assert "PR-5: 0.6.1" in text
    assert "PR-6: 0.6.1 -> 0.7.0" in text
    assert "the version is bumped to 0.7.0 only in PR-6" in text
    assert "No early 0.7.0 version bump" in text
    # PR-2 / PR-3 / PR-4 / PR-5 / PR-6 are merged history; v0.7.0 is
    # formally released (2026-08-09) and the release is sealed.
    for boundary in (
        "PR-2 (the merged foundation PR, #49) implemented only",
        "the `ArtifactClient` class foundation",
        "a stateless zero-argument constructor",
        "the lazy top-level package export",
        "PR-2 did not implement",
        "Canonical reader methods",
        "Dataset reader methods",
        "Dataset Catalog reader methods",
        "filesystem artifact access",
        "discovery / latest",
        "network / OpenD",
        "future method stubs",
        "PR-3 (the merged reader PR, #50) implemented only",
        "`load_canonical_build`",
        "`load_dataset`",
        "direct formal verified reader delegation",
        "reader-access tests",
        "contract/direction/checker changes",
        "fresh-wheel API smoke updates",
        "PR-3 did not implement",
        "Dataset Catalog client access",
        "Catalog lookup/filter",
        "any writer/builder",
        "discovery/latest",
        "settings",
        "OpenD/network",
        "current-time behavior",
        "CLI",
        "PR-4/5/6 work",
        "PR-4 (the merged Catalog-read PR, #51) implemented only",
        "`load_dataset_catalog`",
        "direct formal verified Catalog reader delegation",
        "Catalog reader access tests",
        "fresh-wheel smoke updates",
        "PR-4 did not implement",
        "Catalog builder",
        "Catalog materialization",
        "Catalog list/filter/query convenience API",
        "new CLI",
        "dataset-catalog-query CLI",
        "Canonical/Dataset production changes",
        "artifact format change",
        "schema change",
        "identity change",
        "migration",
        "discovery/latest",
        "network/OpenD",
        "current time",
        "PR-5 usability/examples",
        "PR-6 release prep",
        "version bump",
        "## 6.4 PR-5 boundary",
        "PR-5 (this PR) MAY ONLY",
        "add integrated offline E2E acceptance",
        "add explicit-path Python consumer documentation",
        "add Jupyter-friendly consumer documentation",
        "add ML-consumer handoff documentation without ML implementation",
        "add source-tree examples",
        "harden backward compatibility tests",
        "harden release checker",
        "add existing-job CI smoke for PR-5 examples/acceptance",
        "PR-5 MUST NOT",
        "modify src/",
        "modify dependencies",
        "modify version",
        "add ArtifactClient capabilities",
        "add CLI",
        "add discovery/latest",
        "add settings",
        "add network/OpenD",
        "add current time",
        "add visualization product code",
        "add ML/training/evaluation",
        "perform PR-6 release preparation",
        "## 6.5 PR-6 boundary",
        "PR-6 (this PR) MAY ONLY",
        "bump the package version from 0.6.1 to 0.7.0",
        "sync the lifecycle documents (direction, contract, README, CHANGELOG)",
        "add the v0.7.0 release notes (`docs/release_v0_7_0.md`)",
        "harden the release checker / release regression guards",
        "sync the CI release-state marker to `V070_RELEASE_PREP_OK`",
        "PR-6 MUST NOT",
        "modify `src/` except the `_version.py` version bump",
        "modify dependencies",
        "add ArtifactClient capabilities",
        "add CLI",
        "add discovery/latest",
        "add settings",
        "add network/OpenD",
        "add current time",
        "create the v0.7.0 tag",
        "publish a GitHub Release",
        "publish to PyPI / TestPyPI",
    ):
        assert boundary in text
    assert "ArtifactClient is implemented" not in text
    assert "from market_vault import ArtifactClient" not in text
    assert "PR-1: CURRENT" not in text
    assert "PR-2: NOT STARTED" not in text
    assert "PR-2: CURRENT" not in text
    assert "PR-3: NOT STARTED" not in text
    assert "PR-3: CURRENT" not in text
    assert "PR-4: NOT STARTED" not in text
    assert "PR-4: CURRENT" not in text
    assert "PR-5: CURRENT" not in text
    assert "PR-6: NOT STARTED" not in text
    assert "PR-6: CURRENT" not in text
    assert "v0.7.0: NOT RELEASED" not in text
    assert "V0.7.0 is released" not in text
    assert "V0.7.0 is formally released" in text
    assert "PR #53 merged at 2026-08-09T12:16:49Z" in text
    assert "31312887229" in text
    assert "The CI release-state marker is `V070_RELEASED_OK`" in text
    for boundary in (
        "No new CLI command",
        "No REST API",
        "No HTTP",
        "No ML training",
        "No backtesting",
        "No signals",
        "No trading",
        "No writes through ArtifactClient",
    ):
        assert boundary in text
    for invariant in (
        "Canonical identity unchanged",
        "verified readers remain trust boundaries",
        "explicit path only",
        "no hidden latest",
        "no current time",
        "no settings requirement for ArtifactClient",
        "no OpenD/network for ArtifactClient",
        "PyPI/TestPyPI deferred",
    ):
        assert invariant in text


def test_v070_python_client_contract_states_boundaries():
    text = (ROOT / "docs" / "contracts" / "python_client.md").read_text(
        encoding="utf-8"
    )
    assert "# MarketVault Python Client Contract" in text
    assert "Status: formally released in v0.7.0 (2026-08-09)" in text
    assert "Target release: v0.7.0" in text
    assert "Public root: `ArtifactClient`" in text
    assert "Formal v0.6.1 GitHub Release artifacts" in text
    assert "DO NOT contain `ArtifactClient`" in text
    assert "PR #52" in text
    assert "package metadata to" in text
    assert "frozen version policy" in text
    assert "PR-3: Canonical + Dataset verified read-only access implemented" in text
    assert "PR-4: Dataset Catalog verified read-only access implemented" in text
    for section in range(1, 12):
        assert f"## 13.{section}" in text
    assert "PR-5: integrated acceptance/usability/examples COMPLETE / MERGED / MAIN VERIFIED" in text
    assert "PR-6: release preparation COMPLETE / MERGED / RELEASED (PR #53)" in text
    assert "package: 0.7.0" in text
    assert "v0.7.0: FORMALLY RELEASED" in text
    assert "merged as PR #53 at the release commit" in text
    assert "f25a50481b5ee718881acf5cb5ea5aa05bd32d93" in text
    assert "V0.7.0 is formally released" in text
    assert "the annotated `v0.7.0` tag is created" in text
    assert "the GitHub Release `MarketVault v0.7.0` is published" in text
    assert "The formal v0.7.0 GitHub Release artifacts contain" in text
    assert "the `ArtifactClient` wheel and sdist" in text
    # PR-5 consumer-side usability boundary: examples and documentation
    # are consumer-side only and never form a second trust path; consumer
    # transformations after a verified read are not artifact verification.
    assert "CONSUMER-SIDE only" in text
    assert "second trust path" in text
    assert (
        "Consumer transformations performed AFTER an ArtifactClient "
        "verified read" in text
    )
    assert "the ArtifactClient trust contract" in text
    assert "Zero arguments" in text
    assert "Stateless" in text
    assert "No required settings" in text
    assert "No default settings path" in text
    assert "No implicit `config/settings.yaml`" in text
    assert "No filesystem access in the constructor" in text
    assert "No network" in text
    assert "No OpenD" in text
    assert "No current time" in text
    assert "No cwd-derived artifact root" in text
    assert "No build / materialize / generate / repair / write APIs" in text
    assert "`load_canonical_build`" in text
    assert "`load_dataset`" in text
    assert "`load_dataset_catalog`" in text
    assert "`load_verified_canonical_build`" in text
    assert "`load_verified_dataset`" in text
    assert "`load_verified_dataset_catalog`" in text
    assert "VerifiedCanonicalBuild" in text
    assert "VerifiedDatasetBuild" in text
    assert "VerifiedDatasetCatalogSnapshot" in text
    assert "DatasetCatalogArtifactValidationError" in text
    assert "No Catalog list convenience" in text
    assert "No Catalog show convenience" in text
    assert "No Catalog filter convenience" in text
    assert "No Catalog query convenience" in text
    assert "method-call boundary" in text
    assert "no client-side artifact parsing" in text
    assert "no client-side validation" in text
    assert "no exception wrapping" in text
    assert "parse `manifest.json` itself" in text
    assert "parse `catalog.json` itself" in text
    assert "second validation path" in text
    assert "repair artifacts" in text
    assert "rewrite artifacts" in text
    assert "delete artifacts" in text
    assert "adopt partial staging output" in text
    assert "`latest`" in text
    assert "auto-discovery" in text
    assert "environment-variable root" in text
    assert "settings-derived root" in text
    assert "cwd default root" in text
    assert "recursive scan" in text
    assert "search by guessing IDs" in text
    assert "Do not resolve symlinks to hide them" in text
    assert "mtime mutation" in text
    assert "cache file writes" in text
    assert "DuckDB Catalog construction" in text
    assert "No thin views" in text
    assert "second artifact-validation universe" in text
    assert "No warn-and-continue" in text
    assert "No partial success" in text
    assert "eagerly import `duckdb`, `pandas`, `moomoo`, or `futu`" in text
    for non_goal in (
        "REST API",
        "API server",
        "HTTP service",
        "new CLI command",
        "dataset-catalog-query",
        "ML training",
        "model evaluation",
        "experiment tracking",
        "backtesting",
        "signals",
        "automatic trading",
        "Trading Execution",
        "new artifact format",
        "identity v2",
        "schema v2",
        "migration",
        "dependency modernization",
    ):
        assert non_goal in text
    # PR-3 / PR-4 implement exactly the three verified reads; the full
    # client and the class implementation details are not contract state.
    assert "ArtifactClient is fully implemented" not in text
    assert "ArtifactClient() is implemented" not in text
    assert "class ArtifactClient" not in text
    for claim in (
        "read access is implemented in PR-2",
        "PR-2 implements Canonical",
        "PR-2 implements Dataset",
        "PR-2 implements Catalog",
        "PR-3 implements Catalog",
        "PR-3 implements Dataset Catalog",
        "load_dataset_catalog is implemented in PR-3",
        "Catalog list convenience is implemented",
        "Catalog show convenience is implemented",
        "Catalog filter convenience is implemented",
        "Catalog query convenience is implemented",
    ):
        assert claim not in text


def test_v070_python_api_audit_states_audit_facts():
    text = (ROOT / "docs" / "v0_7_0_python_api_audit.md").read_text(
        encoding="utf-8"
    )
    assert "# MarketVault v0.7.0 Existing Python API Audit" in text
    assert "lazy" in text
    assert "`MarketVault`" in text
    assert "settings-backed" in text
    assert "load_verified_canonical_build" in text
    assert "load_verified_dataset" in text
    assert "load_verified_dataset_catalog" in text
    assert "trust boundaries" in text
    assert "silently make settings optional" in text
    assert "compatibility surface" in text
    assert "public-name collision" in text
    assert "`ArtifactClient`" in text
    assert "PR-1 does not define that symbol" in text
    # The accurate plan_backfill classification: local Catalog-backed
    # planning with no OpenD/network and the current-UTC-date fallback.
    assert "plan_backfill" in text
    assert "local planning / read-local" in text
    assert "reads Catalog" in text
    assert "no OpenD/network" in text
    assert "uses current UTC date when today is omitted" in text
    assert "pure planning" not in text
    assert "performs OpenD" not in text
    assert "(through `backfill`/`plan_backfill`)" not in text


def test_artifact_client_foundation_importable():
    # PR-2 implements the ArtifactClient foundation: `from market_vault
    # import ArtifactClient` succeeds and `ArtifactClient()` constructs a
    # stateless settings-independent instance.
    from market_vault import ArtifactClient  # noqa: F401

    client = ArtifactClient()
    assert not hasattr(client, "__dict__")


def test_release_checker_fails_when_release_notes_tamper_release_commit(
    tmp_path,
):
    # Mutation guard 2: tampering with the release commit SHA in the
    # release notes must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_6_1.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "37614d539171ef7b738e47415f3cd6ca2de332d1",
            "0000000000000000000000000000000000000000",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_release_notes,
        repo,
        "does not state the fact '37614d539171ef7b738e47415f3cd6ca2de332d1'",
    )


def test_release_checker_fails_when_release_notes_tamper_wheel_hash(
    tmp_path,
):
    # Mutation guard 3: tampering with the formal wheel SHA-256 in the
    # release notes must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_6_1.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "8fd8ec510a7724742d6e3e9fbca5c73b07e991cb3fa35002af792a8dd64ed550",
            "0000000000000000000000000000000000000000000000000000000000000000",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_release_notes,
        repo,
        "does not state the fact '8fd8ec510a7724742d6e3e9fbca5c73b07e991cb3fa35002af792a8dd64ed550'",
    )


def test_release_checker_fails_when_release_notes_tamper_sdist_hash(
    tmp_path,
):
    # Mutation guard 4: tampering with the formal sdist SHA-256 in the
    # release notes must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_6_1.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "0cadd537a0980978a9a0878766cb2234f5b419f3f5d3874ef92e300c76c756f1",
            "0000000000000000000000000000000000000000000000000000000000000000",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_release_notes,
        repo,
        "does not state the fact '0cadd537a0980978a9a0878766cb2234f5b419f3f5d3874ef92e300c76c756f1'",
    )


def test_release_checker_fails_when_v061_direction_claims_pypi_published(
    tmp_path,
):
    # Mutation guard 5: claiming PyPI published in the v0.6.1 direction
    # must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_1_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PyPI: NOT PUBLISHED.",
            "PyPI: PUBLISHED.",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v061_direction,
        repo,
        "contains the false release claim 'PyPI: PUBLISHED'",
    )


def test_release_checker_fails_without_v070_direction(tmp_path):
    # Mutation guard 6: deleting the v0.7.0 direction document must fail
    # the checker.
    repo = copy_repo(tmp_path)
    (repo / "docs" / "v0_7_0_direction.md").unlink()
    assert_check_fails(_check_release.check_v070_direction, repo, "docs/v0_7_0_direction.md is missing")


def test_release_checker_fails_when_v070_sequence_tampered(tmp_path):
    # Mutation guard 7: tampering with the fixed 6-PR sequence in the
    # v0.7.0 direction must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_7_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-6 — v0.7.0 release preparation",
            "PR-5 — v0.7.0 release preparation",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_direction,
        repo,
        "does not state the fact 'PR-6 — v0.7.0 release preparation'",
    )


def test_release_checker_fails_when_package_reverts_to_061(tmp_path):
    # PR-6 guard: reverting the current package back to 0.6.1 must fail
    # the checker: the package is 0.7.0 in the PR-6 release preparation.
    repo = copy_repo(tmp_path)
    pyproject = repo / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            'version = "0.7.0"', 'version = "0.6.1"'
        ),
        encoding="utf-8",
    )
    version_file = repo / "src" / "market_vault" / "_version.py"
    version_file.write_text(
        version_file.read_text(encoding="utf-8").replace(
            '"0.7.0"', '"0.6.1"'
        ),
        encoding="utf-8",
    )
    assert_check_fails(_check_release.check_pyproject_version, repo, "pyproject.toml version")
    assert_check_fails(_check_release.check_package_version, repo, "package __version__")


def test_release_checker_fails_when_contract_modifies_marketvault_constructor(
    tmp_path,
):
    # Mutation guard 10: the contract must not modify the existing
    # MarketVault constructor.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "python_client.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "- the `MarketVault` constructor;",
            "- the `MarketVault` settings object;",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_python_client_contract,
        repo,
        "does not state the fact 'the `MarketVault` constructor'",
    )


def test_release_checker_fails_when_contract_requires_settings_yaml(tmp_path):
    # Mutation guard 11: the contract must not require settings.yaml.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "python_client.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "No implicit `config/settings.yaml`",
            "Implicit `config/settings.yaml` is required",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_python_client_contract,
        repo,
        "does not state the fact 'No implicit `config/settings.yaml`'",
    )


def test_release_checker_fails_when_contract_adds_latest(tmp_path):
    # Mutation guard 12: the contract must not add a hidden latest.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "python_client.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "- `latest`;",
            "- `newest`;",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_python_client_contract,
        repo,
        "does not state the fact '`latest`'",
    )


def test_release_checker_fails_when_contract_allows_raw_manifest_parsing(
    tmp_path,
):
    # Mutation guard 13: the contract must never allow the client to parse
    # manifest.json / catalog.json itself.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "python_client.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "parse `manifest.json` itself",
            "parse `manifest.json` via a second validation path",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_python_client_contract,
        repo,
        "does not state the fact 'parse `manifest.json` itself'",
    )


def test_release_checker_fails_when_contract_allows_repair(tmp_path):
    # Mutation guard 14: the contract must never allow artifact repair /
    # rewrite / delete.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "python_client.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "- repair artifacts;\n- rewrite artifacts;\n- delete artifacts;",
            "- republish artifacts;",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_python_client_contract,
        repo,
        "does not state the fact 'repair artifacts'",
        "does not state the fact 'rewrite artifacts'",
        "does not state the fact 'delete artifacts'",
    )


def test_release_checker_fails_when_contract_adds_rest_api(tmp_path):
    # Mutation guard 15: the contract must not add a REST API.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "python_client.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "No REST API.",
            "A REST API is provided.",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_python_client_contract,
        repo,
        "does not state the fact 'No REST API'",
    )


def test_release_checker_fails_when_contract_adds_backtesting(tmp_path):
    # Mutation guard 16: the contract must not add ML / backtesting /
    # trading capabilities.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "python_client.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "No backtesting.",
            "Backtesting is provided.",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_python_client_contract,
        repo,
        "does not state the fact 'No backtesting'",
    )


def test_release_checker_fails_when_ci_restores_v070_release_prep_marker(
    tmp_path,
):
    # Post-release guard: reverting the CI released-state marker
    # V070_RELEASED_OK back to the superseded preparation-time marker
    # V070_RELEASE_PREP_OK must fail the checker.
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8").replace(
            "V070_RELEASED_OK",
            "V070_RELEASE_PREP_OK",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_ci_v070_released_state,
        repo,
        'must carry the V070_RELEASED_OK marker',
        'must never restore the superseded V070_RELEASE_PREP_OK preparation marker',
    )


def test_release_checker_fails_when_ci_restores_v061_release_state_marker(
    tmp_path,
):
    # PR-6 guard: restoring the stale v0.6.1 released-state marker must
    # fail the checker: the marker set is V070_RELEASED_OK.
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8")
        + "\necho 'V061_RELEASE_STATE_OK'\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_ci_v070_released_state,
        repo,
        'must never restore the stale V061_RELEASE_STATE_OK marker',
    )


def test_release_checker_fails_when_ci_loses_v070_public_api_import_ok(
    tmp_path,
):
    # Mutation guard 13: the CI fresh-wheel smoke must carry the
    # V070_PUBLIC_API_IMPORT_OK marker once PR-2 implements the
    # ArtifactClient foundation.
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8").replace(
            "print('V070_PUBLIC_API_IMPORT_OK')",
            "print('V070_PUBLIC_API_IMPORT_MISSING')",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_ci_v070_public_api_smoke,
        repo,
        'must carry the V070_PUBLIC_API_IMPORT_OK marker',
    )


def test_release_checker_fails_when_src_removes_artifact_client_module(
    tmp_path,
):
    # Mutation guard 1: removing the ArtifactClient production module must
    # fail the checker: the PR-2 foundation is required.
    repo = copy_repo(tmp_path)
    (repo / "src" / "market_vault" / "artifact_client.py").unlink()
    assert_check_fails(
        _check_release.check_v070_artifact_client_foundation,
        repo,
        'src/market_vault/artifact_client.py is missing',
    )


def test_release_checker_fails_when_artifact_client_removed_from_all(
    tmp_path,
):
    # Mutation guard 2: removing ArtifactClient from __all__ must fail the
    # checker: it is a required top-level public export.
    repo = copy_repo(tmp_path)
    init_path = repo / "src" / "market_vault" / "__init__.py"
    init_path.write_text(
        init_path.read_text(encoding="utf-8").replace(
            '    "ArtifactClient",\n',
            "",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_foundation,
        repo,
        "src/market_vault/__init__.py __all__ must contain 'ArtifactClient'",
    )


def test_release_checker_fails_when_artifact_client_export_becomes_eager(
    tmp_path,
):
    # Mutation guard 3: an eager top-level import of the artifact_client
    # module must fail the checker: the export must stay lazy through
    # __getattr__.
    repo = copy_repo(tmp_path)
    init_path = repo / "src" / "market_vault" / "__init__.py"
    init_path.write_text(
        "from .artifact_client import ArtifactClient\n"
        + init_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_foundation,
        repo,
        'ArtifactClient must be exported lazily through __getattr__, never through an eager top-level import',
    )


def test_release_checker_fails_when_constructor_gains_settings_argument(
    tmp_path,
):
    # Mutation guard 4: a settings argument on the constructor must fail
    # the checker: the constructor is strictly zero-argument.
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    module.write_text(
        module.read_text(encoding="utf-8").replace(
            "def __init__(self) -> None:",
            "def __init__(self, settings=None) -> None:",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_foundation,
        repo,
        'ArtifactClient.__init__ must take exactly self and no positional/keyword configuration arguments',
    )


def test_release_checker_fails_when_constructor_gains_root_argument(
    tmp_path,
):
    # Mutation guard 5: a root/path argument on the constructor must fail
    # the checker: the constructor is strictly zero-argument.
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    module.write_text(
        module.read_text(encoding="utf-8").replace(
            "def __init__(self) -> None:",
            "def __init__(self, root=None) -> None:",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_foundation,
        repo,
        'ArtifactClient.__init__ must take exactly self and no positional/keyword configuration arguments',
    )


def test_release_checker_fails_when_constructor_gains_path_argument(
    tmp_path,
):
    # Mutation guard 5b: a path argument on the constructor must fail the
    # checker: the constructor is strictly zero-argument.
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    module.write_text(
        module.read_text(encoding="utf-8").replace(
            "def __init__(self) -> None:",
            "def __init__(self, path=None) -> None:",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_foundation,
        repo,
        'ArtifactClient.__init__ must take exactly self and no positional/keyword configuration arguments',
    )


def test_release_checker_fails_when_constructor_does_work(tmp_path):
    # Mutation guard 5c: a constructor body that performs work (any
    # non-docstring statement) must fail the checker.
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    module.write_text(
        module.read_text(encoding="utf-8").replace(
            '        """Initialize the client with no configuration '
            "and no side\n        effects.\"\"\"\n",
            "        return None\n",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_foundation,
        repo,
        'ArtifactClient.__init__ body must not perform any work (no calls, no filesystem/network/time access)',
    )


def test_release_checker_fails_when_slots_removed(tmp_path):
    # Mutation guard 6: removing the __slots__ stateless boundary must
    # fail the checker.
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    module.write_text(
        module.read_text(encoding="utf-8").replace(
            "    __slots__ = ()\n",
            "",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_foundation,
        repo,
        'ArtifactClient must keep the stateless boundary __slots__ == ()',
    )


def test_release_checker_fails_when_module_imports_config_or_storage(
    tmp_path,
):
    # Mutation guard 7: the foundation module must never import
    # market_vault.config or market_vault.storage.
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    module.write_text(
        module.read_text(encoding="utf-8")
        + "\nfrom market_vault import config\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_foundation,
        repo,
        'artifact_client.py must not import anything except __future__.annotations',
    )


def test_release_checker_fails_when_module_imports_canonical_or_dataset(
    tmp_path,
):
    # Mutation guard 8: the foundation module must never import
    # market_vault.canonical or market_vault.dataset (reader delegation
    # belongs to PR-3 / PR-4).
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    module.write_text(
        module.read_text(encoding="utf-8")
        + "\nfrom market_vault.dataset import load_verified_dataset\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_foundation,
        repo,
        'artifact_client.py must not import anything except __future__.annotations',
    )


def test_release_checker_fails_when_module_imports_fs_time_network(
    tmp_path,
):
    # Mutation guard 9: the foundation module must never import a
    # filesystem / time / network dependency.
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    module.write_text(
        module.read_text(encoding="utf-8") + "\nfrom pathlib import Path\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_foundation,
        repo,
        'artifact_client.py must not import anything except __future__.annotations',
    )


def test_release_checker_fails_when_client_gets_public_read_method(
    tmp_path,
):
    # Mutation guard 10 / PR-3 guard C / PR-4 guard 13: the ArtifactClient
    # public business method set is frozen at exactly load_canonical_build,
    # load_dataset and load_dataset_catalog; any extra public method —
    # including a load_dataset_catalog_latest convenience — must fail the
    # checker.
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    module.write_text(
        module.read_text(encoding="utf-8").replace(
            "class ArtifactClient:",
            "class ArtifactClient:\n"
            "    def load_dataset_catalog_latest(self) -> None:\n"
            "        return None\n",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_foundation,
        repo,
        'ArtifactClient public business methods must be exactly load_canonical_build, load_dataset and load_dataset_catalog, with only __init__ as constructor (found: __init__, load_canonical_build, load_dataset, load_dataset_catalog, load_dataset_catalog_latest)',
    )


def test_release_checker_fails_when_direction_states_pr3_not_started(
    tmp_path,
):
    # Mutation guard 11 / PR-3 guard D: the direction document regressing
    # PR-3 to NOT STARTED must fail the checker — PR-3 is merged history.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_7_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-3: COMPLETE / MERGED / MAIN VERIFIED",
            "PR-3: NOT STARTED",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_direction,
        repo,
        "contains the false implementation/release claim 'PR-3: NOT STARTED'",
    )


def test_release_checker_fails_when_contract_claims_read_access_in_pr2(
    tmp_path,
):
    # Mutation guard 12: the contract claiming Canonical / Dataset /
    # Catalog read access is already implemented in PR-2 must fail the
    # checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "python_client.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nCanonical read access is implemented in PR-2.\n"
        + "PR-2 implements Canonical and Dataset and Catalog reads.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_python_client_contract,
        repo,
        "contains the false PR-2 read-capability claim 'read access is implemented in PR-2'",
        "contains the false PR-2 read-capability claim 'PR-2 implements Canonical'",
    )


def test_release_checker_fails_when_contract_drops_load_canonical_build(
    tmp_path,
):
    # PR-3 mutation guard A: the contract dropping the load_canonical_build
    # API fact must fail the checker — the Canonical read method is frozen
    # contract state.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "python_client.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "`load_canonical_build`",
            "",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_python_client_contract,
        repo,
        "does not state the fact '`load_canonical_build`'",
    )


def test_release_checker_fails_when_contract_drops_load_dataset(
    tmp_path,
):
    # PR-3 mutation guard B: the contract dropping the load_dataset API
    # fact must fail the checker — the Dataset read method is frozen
    # contract state.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "python_client.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "`load_dataset`",
            "",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_python_client_contract,
        repo,
        "does not state the fact '`load_dataset`'",
    )


def test_release_checker_fails_when_direction_regresses_pr6_to_not_started(
    tmp_path,
):
    # PR-6 guard: regressing the completed release-preparation stage back
    # to NOT STARTED must fail the checker — PR-6 is COMPLETE / MERGED /
    # RELEASED.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_7_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-6: COMPLETE / MERGED / RELEASED",
            "PR-6: NOT STARTED",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_direction,
        repo,
        "contains the false implementation/release claim 'PR-6: NOT STARTED'",
    )


def test_release_checker_fails_when_direction_regresses_pr5_to_current(
    tmp_path,
):
    # PR-6 guard: regressing the merged PR-5 stage back to CURRENT must
    # fail the checker — PR-5 is COMPLETE / MERGED / MAIN VERIFIED.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_7_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-5: COMPLETE / MERGED / MAIN VERIFIED",
            "PR-5: CURRENT",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_direction,
        repo,
        "contains the false implementation/release claim 'PR-5: CURRENT'",
    )


def test_release_checker_fails_when_direction_loses_package_070(tmp_path):
    # PR-6 guard: reverting the current progress-block package back to
    # 0.6.1 must fail the checker — the PR-6 package is 0.7.0.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_7_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "package: 0.7.0",
            "package: 0.6.1",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_direction,
        repo,
        "does not state the fact 'package: 0.7.0'",
    )


def test_release_checker_fails_when_contract_regresses_pr5_to_current(
    tmp_path,
):
    # PR-6 guard: regressing the merged PR-5 contract stage back to
    # CURRENT must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "python_client.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-5: integrated acceptance/usability/examples "
            "COMPLETE / MERGED / MAIN VERIFIED",
            "PR-5: integrated acceptance/usability/examples CURRENT",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_python_client_contract,
        repo,
        "does not state the fact 'PR-5: integrated acceptance/usability/examples COMPLETE / MERGED / MAIN VERIFIED'",
    )


def test_release_checker_fails_when_contract_regresses_pr6_to_not_started(
    tmp_path,
):
    # PR-6 guard: regressing the completed contract release-preparation
    # stage back to NOT STARTED must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "python_client.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-6: release preparation COMPLETE / MERGED / RELEASED "
            "(PR #53)",
            "PR-6: release preparation NOT STARTED",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_python_client_contract,
        repo,
        "does not state the fact 'PR-6: release preparation COMPLETE / MERGED / RELEASED (PR #53)'",
    )


def test_release_checker_fails_when_contract_loses_package_070(tmp_path):
    # PR-6 guard: reverting the contract package line back to 0.6.1 must
    # fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "python_client.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "package: 0.7.0",
            "package: 0.6.1",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_python_client_contract,
        repo,
        "does not state the fact 'package: 0.7.0'",
    )


def test_release_checker_fails_when_release_notes_missing(tmp_path):
    # PR-6 guard: deleting the v0.7.0 release notes document must fail
    # the checker.
    repo = copy_repo(tmp_path)
    (repo / "docs" / "release_v0_7_0.md").unlink()
    assert_check_fails(
        _check_release.check_v070_release_notes,
        repo,
        'docs/release_v0_7_0.md is missing',
    )


def test_release_checker_fails_when_release_notes_formal_region_claims_not_released(
    tmp_path,
):
    # Post-release guard: the release-notes formal region must never
    # restore the preparation-time NOT formally released status — v0.7.0
    # is formally released.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_7_0.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "The v0.7.0 release is formally released and sealed",
            "V0.7.0 is NOT formally released",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_release_notes,
        repo,
        "formal region contains the stale release claim 'V0.7.0 is NOT formally released'",
    )


def test_release_checker_fails_when_release_notes_formal_region_claims_tag_not_created(
    tmp_path,
):
    # Post-release guard: the release-notes formal region must never
    # restore the preparation-time tag state — the v0.7.0 tag IS CREATED.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_7_0.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "## Formal release status",
            "## Formal release status\nv0.7.0 tag:            NOT CREATED",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_release_notes,
        repo,
        "formal region contains the stale release claim 'v0.7.0 tag:            NOT CREATED'",
    )


def test_release_checker_fails_when_release_notes_predict_future_merge_sha(
    tmp_path,
):
    # Post-release guard: the release-notes formal region must never
    # predict a future merge commit — the PR-6 release commit is known
    # and recorded.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_7_0.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "## Formal release status",
            "## Formal release status\nthe future merge commit is "
            "5ec437d37bb2cde0b716aa5dc1f84538b4bc6215",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_release_notes,
        repo,
        "formal region contains the stale release claim 'the future merge commit is'",
    )


def test_release_checker_fails_when_release_notes_predict_formal_hash(
    tmp_path,
):
    # Post-release guard: the release-notes formal region must never
    # claim formal artifact hash values are predicted — the formal
    # SHA-256 values are recorded, not predicted.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_7_0.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "## Formal release status",
            "## Formal release status\nformal artifact SHA256 values are "
            "predicted",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_release_notes,
        repo,
        "formal region contains the stale release claim 'formal artifact SHA256 values are predicted'",
    )


def test_release_checker_fails_when_release_notes_lose_pr6_merged(
    tmp_path,
):
    # Post-release guard: losing the merged PR-6 record (the exact
    # release commit) must fail the checker — PR-6 is MERGED at the
    # release commit.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_7_0.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-6: PR #53 MERGED f25a50481b5ee718881acf5cb5ea5aa05bd32d93",
            "PR-6: PR #53 OPEN / UNMERGED",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_release_notes,
        repo,
        "does not state the fact 'PR-6: PR #53 MERGED f25a50481b5ee718881acf5cb5ea5aa05bd32d93'",
    )


def test_release_checker_fails_when_release_notes_lose_formal_release_status(
    tmp_path,
):
    # Post-release guard: losing the formal release status statement must
    # fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_7_0.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "The v0.7.0 release is formally released and sealed",
            "The v0.7.0 release is NOT released",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_release_notes,
        repo,
        "does not state the fact 'The v0.7.0 release is formally released and sealed'",
    )


def test_release_checker_fails_when_release_notes_formal_region_restores_candidate_hashes(
    tmp_path,
):
    # Post-release guard: the release-notes formal region must never
    # restore the candidate-hashes-not-reused preparation wording — the
    # formal assets and their SHA-256 values are sealed.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_7_0.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "## Formal release status",
            "## Formal release status\nPR candidate hashes: not reused as "
            "formal release asset hashes",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_release_notes,
        repo,
        "formal region contains the stale release claim 'PR candidate hashes: not reused as formal release asset hashes'",
    )


def test_release_checker_fails_when_release_notes_restore_unstable_main_head(
    tmp_path,
):
    # Post-release guard: the release-notes formal region must state the
    # main HEAD at release sealing and must never restore the unstable
    # current-state "main HEAD: <release commit>" wording, which becomes
    # false as soon as the post-release PR merges.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_7_0.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "main HEAD at release sealing: f25a50481b5ee718881acf5cb5ea5aa05bd32d93",
            "main HEAD: f25a50481b5ee718881acf5cb5ea5aa05bd32d93",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_release_notes,
        repo,
        "formal region contains the stale release claim 'main HEAD: f25a50481b5ee718881acf5cb5ea5aa05bd32d93'",
    )


def test_release_checker_fails_when_release_notes_tamper_sha256sums_file_hash(
    tmp_path,
):
    # Post-release guard: tampering with the formal SHA256SUMS.txt file
    # SHA-256 (the manifest file's own hash, distinct from its contents
    # lines) must fail the checker — all three formal asset hashes are
    # sealed.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_7_0.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "8294805C21CEBE3A2D62465664F9A90E0CF4F3B02AE4F1A0651C7D7830403512",
            "0000000000000000000000000000000000000000000000000000000000000000",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_release_notes,
        repo,
        "does not state the fact '8294805C21CEBE3A2D62465664F9A90E0CF4F3B02AE4F1A0651C7D7830403512'",
    )


def test_release_checker_fails_when_release_notes_manifest_hash_replaced_by_contents(
    tmp_path,
):
    # Post-release guard: the SHA256SUMS.txt file hash must not be
    # replaced by the manifest contents lines (the reviewer-flagged
    # confusion); the record must state the manifest file's own SHA-256
    # and the two contents lines separately.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_7_0.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "SHA256SUMS.txt\nSHA-256:\n"
            "8294805C21CEBE3A2D62465664F9A90E0CF4F3B02AE4F1A0651C7D7830403512\n\n"
            "Contents:",
            "SHA256SUMS.txt\nSHA-256:",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_release_notes,
        repo,
        "does not state the fact '8294805C21CEBE3A2D62465664F9A90E0CF4F3B02AE4F1A0651C7D7830403512'",
    )


def test_release_checker_fails_when_client_parses_manifest_itself(
    tmp_path,
):
    # PR-3 mutation guard F: the Canonical reader method replaced with an
    # independent manifest/JSON second read path must fail the checker.
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    module.write_text(
        module.read_text(encoding="utf-8").replace(
            "return load_verified_canonical_build(build_dir)",
            "return json.load(open(build_dir / 'manifest.json'))",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_readers,
        repo,
        'ArtifactClient.load_canonical_build must return the direct load_verified_canonical_build(build_dir) result without wrapping',
        "ArtifactClient source must not independently use the identifier 'json' (no second trust path)",
    )


def test_release_checker_fails_when_client_reads_parquet_itself(
    tmp_path,
):
    # PR-3 mutation guard G: the Dataset reader method replaced with a raw
    # Parquet read (second trust path) must fail the checker.
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    module.write_text(
        module.read_text(encoding="utf-8").replace(
            "return load_verified_dataset(build_dir)",
            "return pyarrow.parquet.read_table(build_dir)",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_readers,
        repo,
        'ArtifactClient.load_dataset must return the direct load_verified_dataset(build_dir) result without wrapping',
        "ArtifactClient source must not independently use the identifier 'parquet' (no second trust path)",
    )


def test_release_checker_fails_when_reader_import_moves_to_module_level(
    tmp_path,
):
    # PR-3 mutation guard H: a reader import at module level (even the
    # formal reader) must fail the checker — reader imports live only at
    # the method-call boundary. Heavy third-party module-level imports are
    # pinned by mutation guards 7/8.
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    module.write_text(
        module.read_text(encoding="utf-8")
        + "\nfrom .canonical.reader import load_verified_canonical_build\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_foundation,
        repo,
        'artifact_client.py must not import anything except __future__.annotations',
    )


def test_release_checker_fails_when_client_method_uses_settings(
    tmp_path,
):
    # PR-3 mutation guard I: the client deriving its artifact root from
    # settings (settings-derived root behavior) must fail the checker —
    # the client has no settings and passes build_dir verbatim.
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    module.write_text(
        module.read_text(encoding="utf-8").replace(
            "return load_verified_canonical_build(build_dir)",
            "build_root = settings.get(\"root\", build_dir)\n"
            "        return load_verified_canonical_build(build_root)",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_readers,
        repo,
        "ArtifactClient source must not independently use the identifier 'settings' (no second trust path)",
    )


def test_release_checker_fails_when_contract_drops_no_exception_wrapping(
    tmp_path,
):
    # PR-3 mutation guard J: the contract dropping the
    # no-exception-wrapping / verified-reader authority boundary must fail
    # the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "python_client.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "no exception wrapping and ",
            "",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_python_client_contract,
        repo,
        "does not state the fact 'no exception wrapping'",
    )


def test_release_checker_fails_when_contract_drops_schema_v2_non_goal(tmp_path):
    # Mutation guard A: the contract must keep "No schema v2" as an
    # explicit v0.7.0 non-goal.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "python_client.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "- No schema v2.\n",
            "",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_python_client_contract,
        repo,
        "does not state the fact 'No schema v2'",
    )


def test_release_checker_fails_when_contract_drops_migration_non_goal(tmp_path):
    # Mutation guard B: the contract must keep "No migration" as an
    # explicit v0.7.0 non-goal.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "python_client.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "- No migration.\n",
            "",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_python_client_contract,
        repo,
        "does not state the fact 'No migration'",
    )


def test_release_checker_fails_when_contract_drops_dependency_modernization(
    tmp_path,
):
    # Mutation guard C: the contract must keep "No dependency
    # modernization" as an explicit v0.7.0 non-goal.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "python_client.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "- No dependency modernization.\n",
            "",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_python_client_contract,
        repo,
        "does not state the fact 'No dependency modernization'",
    )


def test_release_checker_fails_when_audit_reverts_plan_backfill_to_pure_planning(
    tmp_path,
):
    # Mutation guard D: the API audit must never classify plan_backfill
    # as "pure planning".
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_7_0_python_api_audit.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "local planning / read-local",
            "pure planning",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_python_api_audit,
        repo,
        "contains the stale plan_backfill claim 'pure planning'",
    )


def test_release_checker_fails_when_audit_claims_plan_backfill_performs_opend(
    tmp_path,
):
    # Mutation guard E: the API audit must never claim plan_backfill
    # performs OpenD/network collection (only backfill does).
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_7_0_python_api_audit.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "local planning / read-local",
            "performs OpenD collection",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_python_api_audit,
        repo,
        "contains the stale plan_backfill claim 'performs OpenD'",
    )


# --- V0.7.0 PR-4 boundary / mutation guards -------------------------------


def test_release_checker_fails_when_catalog_method_deleted(tmp_path):
    # PR-4 guard: deleting load_dataset_catalog must fail the checker —
    # the Dataset Catalog read method is frozen PR-4 surface.
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    text = module.read_text(encoding="utf-8")
    module.write_text(
        text.split("    def load_dataset_catalog", 1)[0],
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_catalog,
        repo,
        'ArtifactClient.load_dataset_catalog must exist and delegate to load_verified_dataset_catalog',
    )


def test_release_checker_fails_when_catalog_method_renamed(tmp_path):
    # PR-4 guard: renaming load_dataset_catalog must fail the checker.
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    module.write_text(
        module.read_text(encoding="utf-8").replace(
            "    def load_dataset_catalog(self, snapshot_dir):",
            "    def load_dataset_catalog_archive(self, snapshot_dir):",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_catalog,
        repo,
        'ArtifactClient.load_dataset_catalog must exist and delegate to load_verified_dataset_catalog',
    )


def test_release_checker_fails_when_catalog_reader_import_moves_to_module_level(
    tmp_path,
):
    # PR-4 guard: the Catalog reader import at module level must fail the
    # checker — reader imports live only at the method-call boundary.
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    module.write_text(
        module.read_text(encoding="utf-8")
        + "\nfrom .dataset.dataset_catalog_reader import "
        "load_verified_dataset_catalog\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_foundation,
        repo,
        'artifact_client.py must not import anything except __future__.annotations',
    )


def test_release_checker_fails_when_catalog_imports_wrong_reader(tmp_path):
    # PR-4 guard: importing load_verified_dataset_catalog from the wrong
    # module (dataset.reader) must fail the checker.
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    module.write_text(
        module.read_text(encoding="utf-8").replace(
            "from .dataset.dataset_catalog_reader import "
            "load_verified_dataset_catalog",
            "from .dataset.reader import load_verified_dataset_catalog",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_catalog,
        repo,
        "ArtifactClient.load_dataset_catalog must import load_verified_dataset_catalog from '.dataset.dataset_catalog_reader' at the method-call boundary",
    )


def test_release_checker_fails_when_catalog_calls_wrong_reader_function(
    tmp_path,
):
    # PR-4 guard: the Catalog method calling a different formal reader
    # function must fail the checker (direct-return authority).
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    module.write_text(
        module.read_text(encoding="utf-8").replace(
            "return load_verified_dataset_catalog(snapshot_dir)",
            "return load_verified_dataset(snapshot_dir)",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_catalog,
        repo,
        'ArtifactClient.load_dataset_catalog must return the direct load_verified_dataset_catalog(snapshot_dir) result without wrapping',
    )


def test_release_checker_fails_when_catalog_method_uses_path(tmp_path):
    # PR-4 guard: Path(snapshot_dir) coercion (identity break + second
    # trust path) must fail the checker.
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    module.write_text(
        module.read_text(encoding="utf-8").replace(
            "return load_verified_dataset_catalog(snapshot_dir)",
            "return load_verified_dataset_catalog(Path(snapshot_dir))",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_catalog,
        repo,
        'ArtifactClient.load_dataset_catalog must return the direct load_verified_dataset_catalog(snapshot_dir) result without wrapping',
        "must not independently use the identifier 'Path' (no second trust path)",
    )


def test_release_checker_fails_when_catalog_method_uses_str(tmp_path):
    # PR-4 guard: str(snapshot_dir) coercion must fail the checker — the
    # exact caller object passes through unchanged.
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    module.write_text(
        module.read_text(encoding="utf-8").replace(
            "return load_verified_dataset_catalog(snapshot_dir)",
            "return load_verified_dataset_catalog(str(snapshot_dir))",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_catalog,
        repo,
        'ArtifactClient.load_dataset_catalog must return the direct load_verified_dataset_catalog(snapshot_dir) result without wrapping',
    )


def test_release_checker_fails_when_catalog_result_wrapped(tmp_path):
    # PR-4 guard: wrapping the formal result must fail the checker.
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    module.write_text(
        module.read_text(encoding="utf-8").replace(
            "return load_verified_dataset_catalog(snapshot_dir)",
            "return _wrap(load_verified_dataset_catalog(snapshot_dir))",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_catalog,
        repo,
        'ArtifactClient.load_dataset_catalog must return the direct load_verified_dataset_catalog(snapshot_dir) result without wrapping',
    )


def test_release_checker_fails_when_catalog_error_caught(tmp_path):
    # PR-4 guard: catching DatasetCatalogArtifactValidationError must fail
    # the checker — formal errors propagate unwrapped.
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    module.write_text(
        module.read_text(encoding="utf-8").replace(
            "        return load_verified_dataset_catalog(snapshot_dir)",
            "        try:\n"
            "            return load_verified_dataset_catalog(snapshot_dir)\n"
            "        except DatasetCatalogArtifactValidationError:\n"
            "            raise\n",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_foundation,
        repo,
        'ArtifactClient methods must not catch or wrap any exception (no try/except, formal errors propagate unwrapped)',
    )


def test_release_checker_fails_when_catalog_catches_exception(tmp_path):
    # PR-4 guard: a bare except Exception in the Catalog method must fail
    # the checker.
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    module.write_text(
        module.read_text(encoding="utf-8").replace(
            "        return load_verified_dataset_catalog(snapshot_dir)",
            "        try:\n"
            "            return load_verified_dataset_catalog(snapshot_dir)\n"
            "        except Exception:\n"
            "            raise\n",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_foundation,
        repo,
        'ArtifactClient methods must not catch or wrap any exception (no try/except, formal errors propagate unwrapped)',
    )


def test_release_checker_fails_when_catalog_adds_query_method(tmp_path):
    # PR-4 guard: a Catalog query/filter convenience method must fail the
    # checker — the public surface is exactly the three verified reads.
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    module.write_text(
        module.read_text(encoding="utf-8").replace(
            "class ArtifactClient:",
            "class ArtifactClient:\n"
            "    def query_catalog(self, expr) -> None:\n"
            "        return None\n",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_foundation,
        repo,
        'ArtifactClient public business methods must be exactly load_canonical_build, load_dataset and load_dataset_catalog, with only __init__ as constructor',
    )


def test_release_checker_fails_when_catalog_parses_files(tmp_path):
    # PR-4 guard: independent Catalog file parsing (hashlib/read_bytes)
    # must fail the checker — no second trust path.
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    module.write_text(
        module.read_text(encoding="utf-8").replace(
            "        return load_verified_dataset_catalog(snapshot_dir)",
            "        payload = hashlib.sha256(snapshot_dir.read_bytes())\n"
            "        return load_verified_dataset_catalog(snapshot_dir)",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_catalog,
        repo,
        "ArtifactClient.load_dataset_catalog must not independently use the identifier 'hashlib' (no second trust path)",
    )


def test_release_checker_fails_when_canonical_reader_deleted(tmp_path):
    # PR-4 guard: deleting the Canonical reader method must fail the
    # checker — the PR-3 verified reads stay frozen.
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    text = module.read_text(encoding="utf-8")
    start = text.index("    def load_canonical_build(")
    end = text.index("    def load_dataset(")
    module.write_text(text[:start] + text[end:], encoding="utf-8")
    assert_check_fails(
        _check_release.check_v070_artifact_client_readers,
        repo,
        'ArtifactClient.load_canonical_build must exist and delegate to load_verified_canonical_build',
    )


def test_release_checker_fails_when_dataset_reader_deleted(tmp_path):
    # PR-4 guard: deleting the Dataset reader method must fail the
    # checker — the PR-3 verified reads stay frozen.
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    text = module.read_text(encoding="utf-8")
    start = text.index("    def load_dataset(")
    end = text.index("    def load_dataset_catalog")
    module.write_text(text[:start] + text[end:], encoding="utf-8")
    assert_check_fails(
        _check_release.check_v070_artifact_client_readers,
        repo,
        'ArtifactClient.load_dataset must exist and delegate to load_verified_dataset',
    )


def test_release_checker_fails_when_existing_reader_delegation_changed(
    tmp_path,
):
    # PR-4 guard: modifying an existing PR-3 reader delegation must fail
    # the checker.
    repo = copy_repo(tmp_path)
    module = repo / "src" / "market_vault" / "artifact_client.py"
    module.write_text(
        module.read_text(encoding="utf-8").replace(
            "return load_verified_dataset(build_dir)",
            "return None",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_artifact_client_readers,
        repo,
        'ArtifactClient.load_dataset must return the direct load_verified_dataset(build_dir) result without wrapping',
    )


def test_release_checker_fails_when_ci_loses_catalog_client_marker(tmp_path):
    # PR-4 guard: the fresh-wheel Catalog client smoke marker must stay in
    # CI.
    repo = copy_repo(tmp_path)
    path = repo / ".github" / "workflows" / "ci.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "print('V070_CATALOG_CLIENT_IMPORT_OK')",
            "print('V070_CATALOG_CLIENT_MISSING')",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_ci_v070_public_api_smoke,
        repo,
        'CI fresh-wheel smoke must carry the V070_CATALOG_CLIENT_IMPORT_OK marker',
    )


def test_release_checker_fails_when_contract_drops_load_dataset_catalog(
    tmp_path,
):
    # PR-4 guard: the contract dropping the load_dataset_catalog API fact
    # must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "python_client.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "`load_dataset_catalog`",
            "",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_python_client_contract,
        repo,
        "does not state the fact '`load_dataset_catalog`'",
    )


def test_release_checker_fails_when_direction_drops_pr4_boundary(tmp_path):
    # PR-4 guard: the direction document dropping the PR-4 boundary must
    # fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_7_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-4 (the merged Catalog-read PR, #51) implemented only",
            "",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_direction,
        repo,
        "does not state the fact 'PR-4 (the merged Catalog-read PR, #51) implemented only'",
    )


def test_release_checker_fails_when_direction_states_pr4_not_started(
    tmp_path,
):
    # PR-4 guard: the direction document regressing PR-4 to NOT STARTED
    # must fail the checker — PR-4 is merged history.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_7_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-4: COMPLETE / MERGED / MAIN VERIFIED",
            "PR-4: NOT STARTED",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_direction,
        repo,
        "contains the false implementation/release claim 'PR-4: NOT STARTED'",
    )


def test_release_checker_fails_when_v060_direction_missing_pr_number(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("PR-5", "PX-5"),
        encoding="utf-8",
    )
    assert_check_fails(_check_release.check_v060_direction, repo, "does not state the fact 'PR-5'")


def test_release_checker_fails_without_v060_adr(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "docs" / "adr" / "0003-project-boundaries-and-v060-data-discovery.md").unlink()
    assert_check_fails(
        _check_release.check_v060_adr,
        repo,
        'docs/adr/0003-project-boundaries-and-v060-data-discovery.md is missing',
    )


def test_release_checker_fails_without_sample_generation_contract(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "docs" / "contracts" / "sample_generation.md").unlink()
    assert_check_fails(
        _check_release.check_sample_generation_contract,
        repo,
        'docs/contracts/sample_generation.md is missing',
    )


def test_release_checker_fails_without_dataset_catalog_contract(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "docs" / "contracts" / "dataset_catalog.md").unlink()
    assert_check_fails(
        _check_release.check_dataset_catalog_contract,
        repo,
        'docs/contracts/dataset_catalog.md is missing',
    )


def test_release_checker_fails_when_v060_direction_appends_sample_generator_implemented(
    tmp_path,
):
    # An appended contradictory claim must fail even when the required
    # not-implemented markers are still present.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nThe Sample Generator is implemented and available now.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v060_direction,
        repo,
        "false claim 'Sample Generator is implemented'",
    )


def test_release_checker_fails_when_v060_direction_appends_dataset_catalog_implemented(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nThe Dataset Catalog is implemented and available now.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v060_direction,
        repo,
        "false claim 'Dataset Catalog is implemented'",
    )


def test_release_checker_fails_when_sample_contract_singular_canonical_dirs(
    tmp_path,
):
    # Shrinking the plural Canonical build directory input back to a single
    # directory must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "sample_generation.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "one or more explicit verified Canonical build directories",
            "one explicit verified Canonical build directory",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_contract,
        repo,
        "does not state the plural input fact 'one or more explicit verified Canonical build directories'",
    )


def test_release_checker_fails_when_sample_contract_singular_feature_spec_paths(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "sample_generation.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "one or more explicit Feature spec file paths",
            "one explicit Feature spec file path",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_contract,
        repo,
        "does not state the plural input fact 'one or more explicit Feature spec file paths'",
    )


def test_release_checker_fails_when_sample_contract_singular_label_spec_paths(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "sample_generation.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "one or more explicit Label spec file paths",
            "one explicit Label spec file path",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_contract,
        repo,
        "does not state the plural input fact 'one or more explicit Label spec file paths'",
    )


def test_release_checker_fails_when_sample_contract_appends_implemented_in_v051(
    tmp_path,
):
    # An affirmative "implemented in v0.5.1" claim appended next to the
    # required planned markers must still fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "sample_generation.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nThe Sample Generator is implemented in v0.5.1.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_contract,
        repo,
        "affirmative 'implemented in v0.5.1'",
    )


def test_release_checker_fails_when_catalog_contract_appends_available_now(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "dataset_catalog.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nThe Dataset Catalog is available now.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_contract,
        repo,
        "stale claim 'available now'",
    )


def test_release_checker_fails_when_catalog_contract_claims_built_at_enters_identity(
    tmp_path,
):
    # A contradictory claim that built_at enters Catalog content identity
    # must fail even when the identity facts are present.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "dataset_catalog.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nbuilt_at enters Catalog content identity.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_contract,
        repo,
        "false identity claim 'built_at enters Catalog content identity'",
    )


def test_release_checker_fails_when_catalog_contract_claims_output_directory_enters_identity(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "dataset_catalog.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nThe physical output directory enters Catalog content identity.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_contract,
        repo,
        "false identity claim 'physical output directory enters Catalog content identity'",
    )


def test_release_checker_fails_when_catalog_contract_missing_separate_materialization_identity(
    tmp_path,
):
    # Deleting the separate materialization / snapshot identity distinction
    # must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "dataset_catalog.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "separate materialization or snapshot identity",
            "materialization metadata",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_contract,
        repo,
        "does not state the Catalog identity fact 'separate materialization or snapshot identity'",
    )


def test_release_checker_fails_when_sample_generation_contract_claims_implemented(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "sample_generation.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "not implemented in v0.5.1",
            "implemented in v0.5.1",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_contract,
        repo,
        "does not state the planned-contract marker 'not implemented in v0.5.1'",
    )


def test_release_checker_fails_when_dataset_catalog_contract_claims_implemented(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "dataset_catalog.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "not implemented in v0.5.1",
            "implemented in v0.5.1",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_contract,
        repo,
        "does not state the planned-contract marker 'not implemented in v0.5.1'",
    )


def test_release_checker_fails_when_v051_direction_claims_sample_generator_implemented(
    tmp_path,
):
    # A v0.5.1 direction that claims the future capabilities are implemented
    # instead of non-goals must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_5_1_direction.md"
    text = path.read_text(encoding="utf-8")
    text = text.replace("## 3. Explicit non-goals", "## 3. Implemented in v0.5.1")
    text = text.replace(
        "V0.5.1 does not implement any of the following",
        "V0.5.1 has implemented all of the following",
    )
    path.write_text(text, encoding="utf-8")
    assert_check_fails(
        _check_release.check_v051_direction,
        repo,
        'does not mark the future capabilities as non-goals',
    )


# --- Package metadata -------------------------------------------------------


def test_pyproject_name():
    with (ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)
    assert pyproject["project"]["name"] == "market-vault"


def test_python_requirement():
    with (ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)
    assert pyproject["project"]["requires-python"] == ">=3.11"


def test_runtime_dependencies_exclude_build_tools():
    with (ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)
    dependencies = " ".join(pyproject["project"]["dependencies"])
    assert "build" not in dependencies
    assert "twine" not in dependencies


def test_dev_dependencies_include_build_tools():
    with (ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)
    dev = " ".join(pyproject["project"]["optional-dependencies"]["dev"])
    assert "build" in dev
    assert "twine" in dev


# --- V0.2 compatibility -----------------------------------------------------


def settings(tmp_path) -> Settings:
    return Settings(
        project_root=tmp_path,
        opend_host="127.0.0.1",
        opend_port=11111,
        data_root=tmp_path / "data",
        catalog_path=tmp_path / "catalog" / "market_vault.duckdb",
        manifest_dir=tmp_path / "manifests",
        report_dir=tmp_path / "reports",
        request_pause_seconds=0,
    )


def write_legacy_snapshot(cfg: Settings, *, code: str, trade_date: date) -> None:
    store = ParquetStore(cfg)
    raw = pd_frame(code, trade_date)
    curated = normalize_bars(
        raw,
        requested_trade_date=trade_date,
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source=cfg.source,
        source_schema_version=cfg.source_schema_version,
        run_id="legacy-run",
    )
    batch_key = ParquetStore._batch_key([code], "1m", "ALL", "NONE")
    path = (
        cfg.data_root
        / "curated"
        / f"source={cfg.source}"
        / "dataset=market_bars"
        / "interval=1m"
        / f"requested_trade_date={trade_date.isoformat()}"
        / f"batch-{batch_key}.parquet"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    curated.to_parquet(path, index=False, compression="zstd")
    run = RunManifest(
        requested_trade_date=trade_date,
        requested_symbols=[code],
        interval="1m",
        session="ALL",
        adjustment="NONE",
        run_id="legacy-run",
    )
    run.successful_symbols = [code]
    run.status = "SUCCESS"
    run.finished_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    Catalog(cfg).record_run(run)
    Catalog(cfg).record_quality(run.run_id, [QualityResult("bars_complete", "PASS")])


def pd_frame(code: str, trade_date: date):
    import pandas as pd

    return pd.DataFrame(
        {
            "code": [code],
            "name": [code],
            "time_key": [f"{trade_date.isoformat()} 09:30:00"],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [100],
        }
    )


def test_v02_legacy_filename_detected_by_inventory(tmp_path):
    from market_vault.audit import run_inventory

    cfg = settings(tmp_path)
    write_legacy_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1))
    report = run_inventory(cfg, include_files=True)
    assert any(entry.legacy_filename for entry in report.files)
    assert report.summary.legacy_metadata_row_count == 0  # still full schema


def test_v02_legacy_file_not_deleted_by_audits(tmp_path):
    from market_vault.audit import run_audit

    cfg = settings(tmp_path)
    write_legacy_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1))
    frame = __import__("pandas").DataFrame(
        {"time": ["2026-07-01"], "trade_date_type": ["WHOLE"]}
    )
    curated = normalize_trading_calendar(
        frame,
        market="US",
        code=None,
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 1),
        captured_at=__import__("pandas").Timestamp("2026-08-01T01:00:00Z"),
        source="moomoo",
        source_schema_version=cfg.source_schema_version,
        run_id="cal",
    )
    ParquetStore(cfg).write_trading_calendar_curated(
        curated, "MARKET", "US", date(2026, 7, 1), date(2026, 7, 1), "cal"
    )
    Catalog(cfg).refresh_trading_calendar_views()
    before = sorted(p.as_posix() for p in (cfg.data_root / "curated").rglob("*.parquet"))
    run_audit(
        cfg,
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        calendar_market="US",
        today=date(2026, 8, 2),
    )
    after = sorted(p.as_posix() for p in (cfg.data_root / "curated").rglob("*.parquet"))
    assert before == after


def test_v02_snapshots_view_reads_legacy_and_new(tmp_path):
    cfg = settings(tmp_path)
    write_legacy_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1))
    catalog = Catalog(cfg)
    assert catalog.refresh_market_bars_view()
    with catalog.connect() as con:
        count = con.execute("SELECT COUNT(*) FROM market_bars_snapshots").fetchone()[0]
    assert count == 1


def test_v02_market_bars_returns_latest_logical_row(tmp_path):
    cfg = settings(tmp_path)
    write_legacy_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1))
    catalog = Catalog(cfg)
    assert catalog.refresh_market_bars_view()
    with catalog.connect() as con:
        rows = con.execute(
            "SELECT code, interval FROM market_bars WHERE requested_trade_date = ?",
            [date(2026, 7, 1)],
        ).fetchall()
    assert rows == [("US.MU", "1m")]


def test_v02_initialize_idempotent(tmp_path):
    catalog = Catalog(settings(tmp_path))
    catalog.initialize()
    catalog.initialize()
    with catalog.connect() as con:
        tables = {
            row[0]
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
    assert {"ingestion_runs", "quality_results", "dataset_ingestion_runs"} <= tables


def test_v02_settings_load_without_new_keys(tmp_path):
    from market_vault.config import load_settings

    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / "settings.yaml"
    cfg_path.write_text(
        "opend:\n  host: 127.0.0.1\n  port: 11111\n"
        "storage:\n  root_dir: ./data\n  catalog_path: ./catalog/market_vault.duckdb\n"
        "  manifest_dir: ./manifests\n  report_dir: ./reports\n"
        "collector:\n  source: moomoo\n",
        encoding="utf-8",
    )
    loaded = load_settings(cfg_path)
    assert loaded.source == "moomoo"
    assert loaded.source_schema_version == "10.9"


def test_market_vault_api_still_importable():
    assert MarketVault is not None


# --- V0.5.1 released facts --------------------------------------------------


def test_v051_direction_document_is_released():
    text = (ROOT / "docs" / "v0_5_1_direction.md").read_text(encoding="utf-8")
    assert "Status: released on 2026-08-06 JST" in text
    assert "Status: planned" not in text
    assert "Status: proposed" not in text
    assert "have not started" in text
    assert "a978eef291d5e26d20e5cf977bc76609c227cb52" in text
    assert "MarketVault v0.5.1" in text
    assert "31029709970" in text
    assert "v0.6.0" in text


def test_v060_direction_document_is_released():
    text = (ROOT / "docs" / "v0_6_0_direction.md").read_text(encoding="utf-8")
    assert "Status: released on 2026-08-08" in text
    assert "Deterministic Sample Generation and Dataset Catalog" in text
    assert "a978eef291d5e26d20e5cf977bc76609c227cb52" in text
    assert "package version at planning time: 0.5.1" in text
    assert "bumped to 0.6.0 only in PR-9" in text
    assert "not part of v0.6" in text
    assert "PR #43" in text
    assert "MERGED" in text
    assert "669c955abc0a234264964dfdb7fcafdf502a901a" in text
    assert "31227915770" in text
    assert "MarketVault v0.6.0" in text
    assert "2026-08-08T03:17:48Z" in text
    assert "NOT PUBLISHED" in text
    for number in range(1, 10):
        assert f"PR-{number}" in text
    assert "PR-9 not started" not in text
    assert "Status: planned" not in text
    assert "PR-9 is the current v0.6.0 release-preparation stage" not in text
    assert "not formally released" not in text
    assert "Quant Research" in text
    assert "Trading Execution" in text


def test_v060_direction_records_pr7_complete_and_pr8_merged():
    text = (ROOT / "docs" / "v0_6_0_direction.md").read_text(encoding="utf-8")
    assert "PR #41" in text
    assert "2026-08-07T13:25:52Z" in text
    assert "15ce0ef" in text
    assert "PR-7 COMPLETE" in text
    assert "PR #42" in text
    assert "2026-08-07T18:32:32Z" in text
    assert "24a2243031b5f16fdbb9334f1a1722e56eb7a2f7" in text
    assert "PR-8 COMPLETE" in text
    assert "main verified" in text
    assert "31207428151" in text
    assert "0.5.1" in text
    assert "PR #43" in text
    assert "669c955abc0a234264964dfdb7fcafdf502a901a" in text
    assert "PR-9 COMPLETE" in text
    assert "31227915770" in text
    assert "2026-08-08T03:17:48Z" in text


def test_v060_direction_docs_are_boundary_contracts():
    for rel in (
        "docs/contracts/sample_generation.md",
        "docs/contracts/dataset_catalog.md",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "not implemented in v0.5.1" in text
        assert "Target release: v0.6.0" in text


def test_release_notes_state_formal_asset_source():
    text = (ROOT / "docs" / "release_v0_5_1.md").read_text(encoding="utf-8")
    assert "rebuilt from the exact release commit" in text
    assert "candidate validation only" in text
    assert "downloaded again" in text
    assert "a978eef291d5e26d20e5cf977bc76609c227cb52" in text


def test_sample_generation_contract_supports_multiple_canonical_dirs():
    text = (ROOT / "docs" / "contracts" / "sample_generation.md").read_text(
        encoding="utf-8"
    )
    assert "one or more explicit verified Canonical build directories" in text


def test_sample_generation_contract_supports_multiple_feature_spec_paths():
    text = (ROOT / "docs" / "contracts" / "sample_generation.md").read_text(
        encoding="utf-8"
    )
    assert "one or more explicit Feature spec file paths" in text
    assert "feature_spec_files" in text


def test_sample_generation_contract_supports_multiple_label_spec_paths():
    text = (ROOT / "docs" / "contracts" / "sample_generation.md").read_text(
        encoding="utf-8"
    )
    assert "one or more explicit Label spec file paths" in text
    assert "label_spec_files" in text


def test_v060_direction_distinguishes_catalog_identity_layers():
    text = (ROOT / "docs" / "v0_6_0_direction.md").read_text(encoding="utf-8")
    assert "Catalog content identity" in text
    assert "built_at" in text
    assert "never enter Catalog content identity" in text
    assert "separate materialization or snapshot identity" in text


def test_dataset_catalog_contract_distinguishes_identity_layers():
    text = (ROOT / "docs" / "contracts" / "dataset_catalog.md").read_text(
        encoding="utf-8"
    )
    assert "Catalog content identity" in text
    assert "physical paths" in text
    assert "never enter Catalog content identity" in text
    assert "separate materialization or snapshot identity" in text


def test_v060_adr_exists_and_is_accepted():
    text = (ROOT / "docs" / "adr" / "0003-project-boundaries-and-v060-data-discovery.md").read_text(
        encoding="utf-8"
    )
    assert "Status: Accepted" in text
    assert "MarketVault" in text
    assert "Quant Research" in text
    assert "Trading Execution" in text
    assert "Sample Generator" in text
    assert "Dataset Catalog" in text


def test_release_notes_v051_contain_pr_facts():
    text = (ROOT / "docs" / "release_v0_5_1.md").read_text(encoding="utf-8")
    assert "PR #30" in text
    assert "PR #31" in text
    assert "PR #32" in text
    assert "PR #33" in text
    assert "8de57d497ae5d922e3df29d9475f14b9407865f0" in text
    assert "2d9c8a539f04ee2d75e5482c858ec6c3364af135" in text
    assert "240f7ccac89a773366a510f10a13d6de801051ea" in text
    assert "a978eef291d5e26d20e5cf977bc76609c227cb52" in text
    assert "2026-08-05T17:22:15Z" in text
    assert "3b4d03c785123e204885faea08df7b9d7ed07ec0" in text


def test_release_notes_v051_contain_expected_artifacts():
    text = (ROOT / "docs" / "release_v0_5_1.md").read_text(encoding="utf-8")
    assert "Formal release status" in text
    assert "market_vault-0.5.1-py3-none-any.whl" in text
    assert "market_vault-0.5.1.tar.gz" in text
    assert "80965A671AEEF75F315386D9BD4B62EC5DC08E552CB3430AEF92F83C562248C1" in text
    assert "FE82FB4FD254C493EC00519EDEB438533C0C5E8D5A7690E1F14AEA39DE4CCDAB" in text
    assert "MarketVault v0.5.1" in text
    assert "31029709970" in text
    assert "PyPI" in text
    assert "TestPyPI" in text
    assert "release preparation" in text


def test_examples_readme_states_install_version():
    text = (ROOT / "examples" / "dataset_cli" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "market-vault 0.6.0" in text


def test_warning_guard_retained():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert (
        "error:The 'generic' unit for NumPy timedelta is deprecated"
        in text
    )
    assert "ignore::DeprecationWarning" not in text


def test_renderer_contains_hardening_markers():
    text = (ROOT / "examples" / "dataset_cli" / "render_plans.py").read_text(
        encoding="utf-8"
    )
    assert 'isoformat(timespec="microseconds")' in text
    assert "destination exists and is not a directory" in text
    assert "refusing to overwrite" in text
    assert "render_plans: error:" in text


def test_ci_contains_061_assertions_and_marker():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "assert market_vault.__version__ == '0.7.0'" in text
    assert "assert version('market-vault') == '0.7.0'" in text
    assert "V061_PUBLIC_API_IMPORT_OK" in text
    assert "V070_RELEASED_OK" in text
    assert "V070_RELEASE_PREP_OK" not in text
    assert "V061_RELEASE_STATE_OK" not in text
    assert "V061_RELEASE_PREP_OK" not in text
    # PR-2: the ArtifactClient foundation fresh-wheel smoke is required.
    assert "V070_PUBLIC_API_IMPORT_OK" in text
    assert "from market_vault import ArtifactClient" in text
    assert "ArtifactClient()" in text
    assert "V061_RELEASED" not in text
    assert "generate_sample_requests" in text
    assert '".b64"' in text
    assert "compileall -q src tests scripts examples" in text
    assert "render_plans.py --help" in text


def test_release_notes_v060_state_formal_release_facts():
    text = (ROOT / "docs" / "release_v0_6_0.md").read_text(encoding="utf-8")
    assert "## Formal release status" in text
    assert "PR #43" in text
    assert "MERGED" in text
    assert "2026-08-07T23:41:36Z" in text
    assert "669c955abc0a234264964dfdb7fcafdf502a901a" in text
    assert "31227915770" in text
    assert "v0.6.0" in text
    assert "MarketVault v0.6.0" in text
    assert "2026-08-08T03:17:48Z" in text
    assert "market_vault-0.6.0-py3-none-any.whl" in text
    assert "B1BC7D945A8DDF981AEB4AB2B973E5A8BD07919D7293DED15A7715BC03B262AF" in text
    assert "market_vault-0.6.0.tar.gz" in text
    assert "DBA631EC71BD6FD56A436DEB1F82481FAA3E3E89BA5D03D207870F2C96AF3C37" in text
    assert "PyPI: NOT PUBLISHED" in text
    assert "TestPyPI: NOT PUBLISHED" in text
    assert "## Historical release-preparation record" in text
    assert "PR-9" in text
    assert "24a2243031b5f16fdbb9334f1a1722e56eb7a2f7" in text
    assert "PR #42" in text
    assert "2026-08-07T18:32:32Z" in text
    assert "31207428151" in text
    assert "candidate validation only" in text
    assert "exact release commit" in text
    assert "PyArrow 24.0.0" in text
    assert "PyArrow 25.0.0" in text
    assert "pyarrow>=16" in text
    assert "no standalone" in text
    assert "dataset-catalog-query" in text
    assert "## Release preparation status" not in text
    assert "PR-9 is open and **not merged**." not in text
    assert "The v0.6.0 tag does **not** exist yet." not in text
    assert "No GitHub Release exists yet." not in text


def test_release_checker_fails_without_v060_release_notes(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "docs" / "release_v0_6_0.md").unlink()
    assert_check_fails(
        _check_release.check_v060_release_notes,
        repo,
        'docs/release_v0_6_0.md is missing',
    )


def test_release_checker_fails_when_release_notes_formal_region_claims_pr9_open(
    tmp_path,
):
    # A stale current-state sentence in the formal region (before the
    # historical release-preparation record) must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_6_0.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "## Historical release-preparation record",
            "PR-9 is open and **not merged**.\n\n"
            "## Historical release-preparation record",
            1,
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v060_release_notes,
        repo,
        'PR-9 is open and **not merged**.',
    )


def test_release_checker_fails_when_release_notes_formal_region_claims_tag_missing(
    tmp_path,
):
    # A stale current-state "tag does not exist yet" sentence in the formal
    # region must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_6_0.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "## Historical release-preparation record",
            "The v0.6.0 tag does **not** exist yet.\n\n"
            "## Historical release-preparation record",
            1,
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v060_release_notes,
        repo,
        'The v0.6.0 tag does **not** exist yet.',
    )


def test_release_checker_fails_when_release_notes_formal_region_claims_no_release(
    tmp_path,
):
    # A stale current-state "No GitHub Release exists yet" sentence in the
    # formal region must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_6_0.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "## Historical release-preparation record",
            "No GitHub Release exists yet.\n\n"
            "## Historical release-preparation record",
            1,
        ),
        encoding="utf-8",
    )
    assert_check_fails(_check_release.check_v060_release_notes, repo, "No GitHub Release exists yet.")


def test_release_checker_fails_when_release_notes_claim_pypi_published(tmp_path):
    # The claim must be smuggled into the formal region (before the
    # historical release-preparation record); the historical record may
    # quote stale release-preparation phrasing verbatim.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_6_0.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "## Historical release-preparation record",
            "PyPI: published\n\n## Historical release-preparation record",
            1,
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v060_release_notes,
        repo,
        "still contains the stale wording 'PyPI: published'",
    )


def test_release_checker_fails_when_release_notes_claim_every_writer(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_6_0.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "## Historical release-preparation record",
            "every supported PyArrow writer\n\n"
            "## Historical release-preparation record",
            1,
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v060_release_notes,
        repo,
        "still contains the stale wording 'every supported PyArrow writer'",
    )


def test_release_checker_fails_when_release_notes_lose_candidate_wording(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_6_0.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "candidate validation only",
            "candidate validation",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v060_release_notes,
        repo,
        "does not state the fact 'candidate validation only'",
    )


def test_release_checker_fails_when_release_notes_lose_pr42(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_6_0.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("PR #42", "PR #4x"),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v060_release_notes,
        repo,
        "does not state the fact 'PR #42'",
    )


def test_release_checker_fails_when_ci_reverts_to_v051(tmp_path):
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    text = ci.read_text(encoding="utf-8")
    ci.write_text(text.replace("'0.7.0'", "'0.5.1'"), encoding="utf-8")
    assert_check_fails(
        _check_release.check_ci_version_assertions,
        repo,
        'package module version assertion',
        'distribution metadata assertion',
    )


def test_release_checker_fails_when_ci_loses_release_state_marker(tmp_path):
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    text = ci.read_text(encoding="utf-8")
    ci.write_text(
        text.replace("echo 'V070_RELEASED_OK'", "echo 'V070_PREP_OK'"),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_ci_v070_released_state,
        repo,
        'must carry the V070_RELEASED_OK marker',
    )


def test_release_checker_fails_when_ci_loses_b64_forbidden(tmp_path):
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    text = ci.read_text(encoding="utf-8")
    ci.write_text(text.replace('".b64"', '".b64x"'), encoding="utf-8")
    assert_check_fails(
        _check_release.check_ci_v070_released_state,
        repo,
        'wheel hygiene forbidden tuple must include ".b64"',
    )


def test_release_checker_fails_when_ci_loses_generate_sample_requests(tmp_path):
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    text = ci.read_text(encoding="utf-8")
    ci.write_text(
        text.replace("generate_sample_requests", "generate_sample_plan"),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_ci_v070_released_state,
        repo,
        "CI public API smoke must import 'generate_sample_requests'",
    )


def test_release_checker_fails_without_v051_release_notes(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "docs" / "release_v0_5_1.md").unlink()
    assert_check_fails(
        _check_release.check_v051_release_notes,
        repo,
        'docs/release_v0_5_1.md is missing',
    )


def test_release_checker_fails_without_warning_guard(tmp_path):
    repo = copy_repo(tmp_path)
    pyproject = repo / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            "error:The 'generic' unit for NumPy timedelta is deprecated.*:DeprecationWarning",
            "ignore::DeprecationWarning",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_warning_guard,
        repo,
        'warning-as-error guard',
        'must not ignore DeprecationWarnings',
    )


# --- V0.6.0 Sample Generation contract (PR-2) -------------------------------


def test_release_checker_fails_without_sample_generation_modules(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "src" / "market_vault" / "dataset" / "sample_generation.py").unlink()
    assert_check_fails(
        _check_release.check_sample_generation_modules,
        repo,
        'sample_generation.py is missing',
    )


def _mutate_models_version(repo: Path, old: str, new: str) -> None:
    path = repo / "src" / "market_vault" / "dataset" / "sample_generation_models.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8"
    )


def test_release_checker_fails_when_plan_schema_version_constant_removed(tmp_path):
    # Mutation 1: deleting the generation-plan schema version constant must
    # fail the checker.
    repo = copy_repo(tmp_path)
    _mutate_models_version(
        repo,
        "market-vault-sample-generation-plan-v1",
        "market-vault-sample-generation-plan-v9",
    )
    assert_check_fails(
        _check_release.check_sample_generation_modules,
        repo,
        "does not define the exact version constant 'market-vault-sample-generation-plan-v1'",
    )


def test_release_checker_fails_when_rule_schema_version_constant_removed(tmp_path):
    # Mutation 2: deleting the generation-rule schema version constant must
    # fail the checker.
    repo = copy_repo(tmp_path)
    _mutate_models_version(
        repo,
        "market-vault-sample-generation-rule-v1",
        "market-vault-sample-generation-rule-v9",
    )
    assert_check_fails(
        _check_release.check_sample_generation_modules,
        repo,
        "does not define the exact version constant 'market-vault-sample-generation-rule-v1'",
    )


def test_release_checker_fails_when_content_id_version_constant_removed(tmp_path):
    # Mutation 3: deleting the content-ID version constant must fail the
    # checker.
    repo = copy_repo(tmp_path)
    _mutate_models_version(
        repo,
        "market-vault-sample-generation-content-v1",
        "market-vault-sample-generation-content-v9",
    )
    assert_check_fails(
        _check_release.check_sample_generation_modules,
        repo,
        "does not define the exact version constant 'market-vault-sample-generation-content-v1'",
    )


def test_release_checker_accepts_core_implemented_claim(tmp_path):
    # The Sample Generator core is now implemented: the affirmative
    # core-implemented claim must NOT fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "sample_generation.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nThe Sample Generator core is implemented.\n",
        encoding="utf-8",
    )
    assert _check_release.check_sample_generation_contract(repo) == []


def test_release_checker_accepts_cli_implemented_claim(tmp_path):
    # The Sample Generation CLI is now implemented: the affirmative
    # CLI-implemented claim must NOT fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "sample_generation.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nThe Sample Generation CLI is implemented.\n",
        encoding="utf-8",
    )
    assert _check_release.check_sample_generation_contract(repo) == []


def test_release_checker_fails_without_generator_core_module(tmp_path):
    # Mutation 11: deleting the Sample Generator core module must fail the
    # checker.
    repo = copy_repo(tmp_path)
    (repo / "src" / "market_vault" / "dataset" / "sample_generation_core.py").unlink()
    assert_check_fails(
        _check_release.check_sample_generation_core,
        repo,
        'sample_generation_core.py is missing',
    )


def test_release_checker_fails_when_generator_core_version_constant_removed(
    tmp_path,
):
    # Mutation 12: deleting the generator core version constant must fail
    # the checker.
    repo = copy_repo(tmp_path)
    path = repo / "src" / "market_vault" / "dataset" / "sample_generation_core_models.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "market-vault-sample-generator-core-v1",
            "market-vault-sample-generator-core-v9",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_core,
        repo,
        "does not define the exact core version constant 'market-vault-sample-generator-core-v1'",
    )


def test_release_checker_fails_when_contract_doc_claims_generator_writes_dataset(
    tmp_path,
):
    # Mutation 13: a contract document claiming the generator writes the
    # Dataset build plan must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "sample_generation.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nthe generator writes the Dataset build plan.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_core,
        repo,
        "false core claim 'the generator writes the Dataset build plan'",
    )


def test_release_checker_fails_when_contract_doc_claims_gaps_are_skipped(
    tmp_path,
):
    # Mutation 14: a contract document claiming gaps are skipped must fail
    # the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "sample_generation.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\ngaps are skipped.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_core,
        repo,
        "false core claim 'gaps are skipped'",
    )


def test_release_checker_fails_when_contract_doc_claims_gaps_are_filled(
    tmp_path,
):
    # Mutation 15: a contract document claiming gaps are filled must fail
    # the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "sample_generation.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\ngaps are filled.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_core,
        repo,
        "false core claim 'gaps are filled'",
    )


def test_release_checker_fails_when_contract_doc_claims_cross_day_allowed(
    tmp_path,
):
    # Mutation 16: a contract document claiming cross-day windows are
    # allowed must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "sample_generation.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\ncross-day windows are allowed.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_core,
        repo,
        "false core claim 'cross-day windows are allowed'",
    )




def test_release_checker_fails_when_contract_doc_singular_feature_spec_paths(
    tmp_path,
):
    # Mutation 6: shrinking the plural Feature spec input to a single file
    # must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "sample_generation.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "one or more explicit Feature spec file paths",
            "one explicit Feature spec file path",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_contract,
        repo,
        "does not state the plural input fact 'one or more explicit Feature spec file paths'",
    )


def test_release_checker_fails_when_contract_doc_singular_label_spec_paths(
    tmp_path,
):
    # Mutation 7: shrinking the plural Label spec input to a single file
    # must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "sample_generation.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "one or more explicit Label spec file paths",
            "one explicit Label spec file path",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_contract,
        repo,
        "does not state the plural input fact 'one or more explicit Label spec file paths'",
    )


def test_release_checker_fails_when_contract_doc_claims_paths_enter_identity(
    tmp_path,
):
    # Mutation 8: a contract document claiming paths enter the content
    # identity must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "sample_generation.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nPaths enter the Sample Generation content identity.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_contract,
        repo,
        "false claim 'Paths enter the Sample Generation content identity'",
    )


def test_release_checker_fails_when_contract_doc_claims_built_at_enters_identity(
    tmp_path,
):
    # Mutation 9: a contract document claiming built_at enters the content
    # identity must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "sample_generation.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nbuilt_at enters the Sample Generation content identity.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_contract,
        repo,
        "false claim 'built_at enters the Sample Generation content identity'",
    )


def test_release_checker_fails_when_contract_doc_claims_generation_id_enters_dataset_identity(
    tmp_path,
):
    # Mutation 10: a contract document claiming the Generation content ID
    # enters the Dataset identity must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "sample_generation.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nGeneration content ID enters dataset_id.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_contract,
        repo,
        "false claim 'Generation content ID enters dataset_id'",
    )


def test_release_checker_fails_when_path_base_absolute_declaration_removed(
    tmp_path,
):
    # Mutation 18: deleting the explicit absolute path_base declaration must
    # fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "sample_generation.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "explicit absolute path_base", "path_base"
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_core,
        repo,
        "does not state the core fact 'explicit absolute path_base'",
    )


def test_release_checker_fails_when_overlap_segment_declaration_removed(
    tmp_path,
):
    # Mutation 19: deleting the overlapping-rows boundary declaration must
    # fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "sample_generation.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "Overlapping Canonical rows never become a segment boundary",
            "Overlapping Canonical rows may become a segment boundary",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_core,
        repo,
        "does not state the core fact 'Overlapping Canonical rows never become a segment boundary'",
    )


def test_release_checker_fails_when_shared_label_contract_declaration_removed(
    tmp_path,
):
    # Mutation 20: deleting the shared Label configuration contract
    # declaration must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "sample_generation.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "Shared Label configuration contract",
            "Generator-local Label configuration",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_core,
        repo,
        "does not state the core fact 'Shared Label configuration contract'",
    )


def test_release_checker_fails_when_generation_id_recompute_declaration_removed(
    tmp_path,
):
    # Mutation 21: deleting the Generation-ID recomputation declaration must
    # fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "sample_generation.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "recomputes the Generation content ID",
            "accepts the carried Generation content ID",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_core,
        repo,
        "does not state the core fact 'recomputes the Generation content ID'",
    )


# --- V0.6.0 Sample Generation CLI (PR-4) ------------------------------------


def _mutate_cli_models_version(repo: Path, old: str, new: str) -> None:
    path = repo / "src" / "market_vault" / "dataset" / "sample_generation_cli_models.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8"
    )


def _mutate_contract_doc(repo: Path, claim: str) -> None:
    path = repo / "docs" / "contracts" / "sample_generation.md"
    path.write_text(
        path.read_text(encoding="utf-8") + f"\n{claim}\n", encoding="utf-8"
    )


def test_release_checker_fails_without_sample_generation_cli_module(tmp_path):
    # Mutation: deleting the CLI module must fail the checker.
    repo = copy_repo(tmp_path)
    (repo / "src" / "market_vault" / "dataset" / "sample_generation_cli.py").unlink()
    assert_check_fails(
        _check_release.check_sample_generation_cli,
        repo,
        'sample_generation_cli.py is missing',
    )


def test_release_checker_fails_without_sample_generation_output_module(tmp_path):
    # Mutation: deleting the pure renderer module must fail the checker.
    repo = copy_repo(tmp_path)
    (repo / "src" / "market_vault" / "dataset" / "sample_generation_output.py").unlink()
    assert_check_fails(
        _check_release.check_sample_generation_cli,
        repo,
        'sample_generation_output.py is missing',
    )


def test_release_checker_fails_when_cli_contract_version_removed(tmp_path):
    # Mutation: changing the CLI contract version constant must fail the
    # checker.
    repo = copy_repo(tmp_path)
    _mutate_cli_models_version(
        repo,
        "market-vault-sample-generation-cli-v1",
        "market-vault-sample-generation-cli-v9",
    )
    assert_check_fails(
        _check_release.check_sample_generation_cli,
        repo,
        "does not define the exact CLI version constant 'market-vault-sample-generation-cli-v1'",
    )


def test_release_checker_fails_when_cli_result_schema_version_removed(tmp_path):
    # Mutation: changing the CLI result schema version constant must fail
    # the checker.
    repo = copy_repo(tmp_path)
    _mutate_cli_models_version(
        repo,
        "market-vault-sample-generation-cli-result-v1",
        "market-vault-sample-generation-cli-result-v9",
    )
    assert_check_fails(
        _check_release.check_sample_generation_cli,
        repo,
        "does not define the exact CLI version constant 'market-vault-sample-generation-cli-result-v1'",
    )


def test_release_checker_fails_when_sample_generate_registration_removed(tmp_path):
    # Mutation: deleting the sample-generate subparser registration must
    # fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "src" / "market_vault" / "dataset" / "sample_generation_cli.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            'add_parser(\n        "sample-generate",',
            'add_parser(\n        "sample-generate-renamed",',
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_cli,
        repo,
        'does not register sample-generate',
    )


def test_release_checker_fails_when_sample_generate_gains_a_business_option(
    tmp_path,
):
    # Mutation: registering a second business option must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "src" / "market_vault" / "dataset" / "sample_generation_cli.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            'add_argument(\n        "--plan",',
            'add_argument(\n        "--output",',
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_cli,
        repo,
        "registers the business option '--output'",
    )


def test_release_checker_fails_when_cli_module_calls_orchestration(tmp_path):
    # Mutation: the CLI module calling the orchestrator must fail the
    # checker.
    repo = copy_repo(tmp_path)
    path = repo / "src" / "market_vault" / "dataset" / "sample_generation_cli.py"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nresult = orchestrate_dataset_build()\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_cli,
        repo,
        'must never call orchestrate_dataset_build',
    )


def test_release_checker_fails_when_contract_doc_claims_generator_builds_dataset(
    tmp_path,
):
    # Mutation: a contract document claiming the Sample Generator builds the
    # Dataset must fail the checker.
    repo = copy_repo(tmp_path)
    _mutate_contract_doc(repo, "The Sample Generator builds the Dataset.")
    assert_check_fails(
        _check_release.check_sample_generation_cli,
        repo,
        "contains the false PR-4 claim 'Sample Generator builds the Dataset'",
    )


def test_release_checker_fails_when_contract_doc_claims_cli_builds_dataset(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    _mutate_contract_doc(repo, "the CLI builds the Dataset.")
    assert_check_fails(
        _check_release.check_sample_generation_cli,
        repo,
        "contains the false PR-4 claim 'the CLI builds the Dataset'",
    )


def test_release_checker_fails_when_contract_doc_claims_cli_calls_orchestration(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    _mutate_contract_doc(repo, "the CLI calls orchestrate_dataset_build.")
    assert_check_fails(
        _check_release.check_sample_generation_cli,
        repo,
        "contains the false PR-4 claim 'the CLI calls orchestrate_dataset_build'",
    )


def test_release_checker_fails_when_contract_doc_claims_cli_implements_catalog(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    _mutate_contract_doc(repo, "the CLI implements Dataset Catalog.")
    assert_check_fails(
        _check_release.check_sample_generation_cli,
        repo,
        "contains the false PR-4 claim 'the CLI implements Dataset Catalog'",
    )


def test_release_checker_fails_when_contract_doc_claims_output_overwrites(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    _mutate_contract_doc(repo, "The output plan overwrites existing files.")
    assert_check_fails(
        _check_release.check_sample_generation_cli,
        repo,
        "contains the false PR-4 claim 'output plan overwrites existing files'",
    )


def test_release_checker_fails_when_contract_doc_claims_relative_paths_move(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    _mutate_contract_doc(repo, "relative paths may move to another parent.")
    assert_check_fails(
        _check_release.check_sample_generation_cli,
        repo,
        "contains the false PR-4 claim 'relative paths may move to another parent'",
    )


def test_release_checker_fails_when_contract_doc_claims_current_time_built_at(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    _mutate_contract_doc(repo, "The current time supplies built_at.")
    assert_check_fails(
        _check_release.check_sample_generation_cli,
        repo,
        "contains the false PR-4 claim 'current time supplies built_at'",
    )


def test_release_checker_fails_when_contract_doc_claims_output_path_enters_identity(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    _mutate_contract_doc(
        repo, "The output_plan_path enters the Generation content identity."
    )
    assert_check_fails(
        _check_release.check_sample_generation_cli,
        repo,
        "contains the false PR-4 claim 'output_plan_path enters the Generation content identity'",
    )


def test_release_checker_fails_when_contract_doc_reverts_cli_status(tmp_path):
    # Mutation: reverting the formal status to the pre-PR-4 wording must
    # fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "sample_generation.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "Status: Sample Generation contract, generator core, and CLI implemented",
            "Status: Sample Generation contract foundation and generator core "
            "implemented; Sample Generation CLI not implemented",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_contract,
        repo,
        "does not state the formal v1 contract marker 'Status: Sample Generation contract, generator core, and CLI implemented'",
    )
    assert_check_fails(
        _check_release.check_sample_generation_cli,
        repo,
        "contains the false PR-4 claim 'CLI not implemented'",
    )


def test_release_checker_fails_when_direction_reverts_pr4_stage(tmp_path):
    # Mutation: reverting the PR-4 progress record to the pre-PR-4 wording
    # must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-4 is complete",
            "PR-4 is not complete",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_cli,
        repo,
        "does not state the PR-4 progress fact 'PR-4 is complete'",
    )


def test_release_checker_fails_when_direction_loses_pr6_complete(tmp_path):
    # Mutation: removing the required "PR-6 is complete" progress fact must
    # fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-6 is complete",
            "PR-6 is not complete",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_pr6,
        repo,
        "does not state the PR-6 progress fact 'PR-6 is complete'",
    )


def test_release_checker_fails_when_direction_claims_v060_released(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\nV0.6.0 is released.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_cli,
        repo,
        "contains the false PR-4 claim 'V0.6.0 is released'",
    )


def test_release_checker_fails_when_ci_loses_sample_generate_smoke(tmp_path):
    # Mutation: deleting the fresh-wheel sample-generate help smoke must
    # fail the checker.
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8").replace(
            ".release-venv/bin/market-vault sample-generate --help",
            ".release-venv/bin/market-vault dataset-build --help",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_cli,
        repo,
        "fresh-wheel smoke must cover 'market-vault sample-generate --help'",
    )


# --- V0.6.0 Dataset Catalog contract (PR-5) ----------------------------------


def _mutate_catalog_models_version(repo: Path, old: str, new: str) -> None:
    path = repo / "src" / "market_vault" / "dataset" / "dataset_catalog_models.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8"
    )


def _mutate_catalog_contract_doc(repo: Path, claim: str) -> None:
    path = repo / "docs" / "contracts" / "dataset_catalog.md"
    path.write_text(
        path.read_text(encoding="utf-8") + f"\n{claim}\n", encoding="utf-8"
    )


def test_release_checker_fails_without_catalog_models_module(tmp_path):
    # Mutation: deleting a key PR-5 boundary module must fail the checker.
    repo = copy_repo(tmp_path)
    (repo / "src" / "market_vault" / "dataset" / "dataset_catalog_models.py").unlink()
    assert_check_fails(
        _check_release.check_dataset_catalog,
        repo,
        'dataset_catalog_models.py is missing',
    )


def test_release_checker_fails_without_catalog_identity_module(tmp_path):
    # Mutation: deleting the identity module must fail the checker.
    repo = copy_repo(tmp_path)
    (repo / "src" / "market_vault" / "dataset" / "dataset_catalog_identity.py").unlink()
    assert_check_fails(
        _check_release.check_dataset_catalog,
        repo,
        'dataset_catalog_identity.py is missing',
    )


def test_release_checker_fails_without_catalog_projection_module(tmp_path):
    # Mutation: deleting the projection module must fail the checker.
    repo = copy_repo(tmp_path)
    (repo / "src" / "market_vault" / "dataset" / "dataset_catalog_projection.py").unlink()
    assert_check_fails(
        _check_release.check_dataset_catalog,
        repo,
        'dataset_catalog_projection.py is missing',
    )


def test_release_checker_fails_when_catalog_contract_version_removed(tmp_path):
    # Mutation: changing the Catalog contract version constant must fail.
    repo = copy_repo(tmp_path)
    _mutate_catalog_models_version(
        repo,
        "market-vault-dataset-catalog-contract-v1",
        "market-vault-dataset-catalog-contract-v9",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog,
        repo,
        "does not define the exact version constant 'market-vault-dataset-catalog-contract-v1'",
    )


def test_release_checker_fails_when_catalog_entry_schema_version_removed(
    tmp_path,
):
    # Mutation: changing the entry schema version constant must fail.
    repo = copy_repo(tmp_path)
    _mutate_catalog_models_version(
        repo,
        "market-vault-dataset-catalog-entry-v1",
        "market-vault-dataset-catalog-entry-v9",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog,
        repo,
        "does not define the exact version constant 'market-vault-dataset-catalog-entry-v1'",
    )


def test_release_checker_fails_when_catalog_content_id_version_removed(
    tmp_path,
):
    # Mutation: changing the content identity version constant must fail.
    repo = copy_repo(tmp_path)
    _mutate_catalog_models_version(
        repo,
        "market-vault-dataset-catalog-content-v1",
        "market-vault-dataset-catalog-content-v9",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog,
        repo,
        "does not define the exact version constant 'market-vault-dataset-catalog-content-v1'",
    )


def test_release_checker_fails_when_catalog_identity_function_removed(
    tmp_path,
):
    # Mutation: deleting the Catalog-level identity function must fail.
    repo = copy_repo(tmp_path)
    path = repo / "src" / "market_vault" / "dataset" / "dataset_catalog_identity.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "def dataset_catalog_content_id(",
            "def removed_dataset_catalog_content_id(",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog,
        repo,
        'dataset_catalog_identity.py is missing def dataset_catalog_content_id',
    )


def test_release_checker_fails_when_projection_loses_trust_boundary(
    tmp_path,
):
    # Mutation: the projection no longer binding VerifiedDatasetBuild must
    # fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "src" / "market_vault" / "dataset" / "dataset_catalog_projection.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "VerifiedDatasetBuild", "AnyBuild"
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog,
        repo,
        'must bind the trust boundary to VerifiedDatasetBuild',
    )


def test_release_checker_fails_when_catalog_module_imports_legacy_catalog(
    tmp_path,
):
    # Mutation: a PR-5 module importing the legacy Catalog must fail.
    repo = copy_repo(tmp_path)
    path = repo / "src" / "market_vault" / "dataset" / "dataset_catalog_identity.py"
    path.write_text(
        path.read_text(encoding="utf-8") + "\nfrom market_vault.storage import Catalog\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog,
        repo,
        'must never import the legacy Catalog',
    )


def test_release_checker_fails_when_package_loses_catalog_export(tmp_path):
    # Mutation: removing a PR-5 public export must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "src" / "market_vault" / "dataset" / "__init__.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "project_dataset_catalog_entry",
            "missing_catalog_export",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog,
        repo,
        "market_vault.dataset does not export the PR-5 public API 'project_dataset_catalog_entry'",
    )


def test_release_checker_fails_without_catalog_cli_module(tmp_path):
    # Mutation: removing the PR-7 CLI production module must fail the
    # checker.
    repo = copy_repo(tmp_path)
    (repo / "src" / "market_vault" / "dataset" / "dataset_catalog_cli.py").unlink()
    assert_check_fails(
        _check_release.check_dataset_catalog_cli,
        repo,
        'src/market_vault/dataset/dataset_catalog_cli.py is missing',
    )


def test_release_checker_fails_when_contract_trusts_manifest_directly(
    tmp_path,
):
    # Mutation: claiming the Catalog can trust a manifest directly must
    # fail the checker.
    repo = copy_repo(tmp_path)
    _mutate_catalog_contract_doc(
        repo, "The Dataset Catalog trusts manifests directly."
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_contract,
        repo,
        "contains the false PR-5 claim 'trusts manifests directly'",
    )


def test_release_checker_fails_when_contract_claims_builder_implemented(
    tmp_path,
):
    # Mutation: claiming the PR-6 builder is already implemented must fail.
    repo = copy_repo(tmp_path)
    _mutate_catalog_contract_doc(repo, "The Dataset Catalog builder is implemented.")
    assert_check_fails(
        _check_release.check_dataset_catalog_contract,
        repo,
        "contains the false PR-5 claim 'Dataset Catalog builder is implemented'",
    )


def test_release_checker_fails_when_contract_claims_reader_implemented(
    tmp_path,
):
    # Mutation: claiming the verified Catalog reader is already implemented
    # must fail.
    repo = copy_repo(tmp_path)
    _mutate_catalog_contract_doc(repo, "The verified Catalog reader is implemented.")
    assert_check_fails(
        _check_release.check_dataset_catalog_contract,
        repo,
        "contains the false PR-5 claim 'verified Catalog reader is implemented'",
    )


def test_release_checker_fails_when_contract_claims_path_enters_identity(
    tmp_path,
):
    # Mutation: claiming a physical output directory enters the content
    # identity must fail the checker.
    repo = copy_repo(tmp_path)
    _mutate_catalog_contract_doc(
        repo, "physical output directory enters Catalog content identity"
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_contract,
        repo,
        'contains the false identity claim',
    )


def test_release_checker_fails_when_contract_claims_built_at_enters_identity(
    tmp_path,
):
    # Mutation: claiming built_at enters the content identity must fail.
    repo = copy_repo(tmp_path)
    _mutate_catalog_contract_doc(
        repo, "built_at enters Catalog content identity"
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_contract,
        repo,
        "contains the false identity claim 'built_at enters Catalog content identity'",
    )


def test_release_checker_fails_when_contract_reuses_legacy_catalog_tables(
    tmp_path,
):
    # Mutation: an affirmative reuse claim must fail (the legitimate
    # "never reuses" wording is preserved in the real document).
    repo = copy_repo(tmp_path)
    _mutate_catalog_contract_doc(repo, "The new Catalog reuses the legacy Catalog's tables.")
    assert_check_fails(
        _check_release.check_dataset_catalog_contract,
        repo,
        "reuses the legacy Catalog's tables",
    )


def test_release_checker_fails_when_contract_loses_facts_field(tmp_path):
    # Mutation: deleting a content-facts field from the contract document
    # must fail.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "dataset_catalog.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "canonical_row_version_ids",
            "missing_row_version_ids",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_contract,
        repo,
        "does not state the exact facts field 'canonical_row_version_ids'",
    )


def test_release_checker_fails_when_direction_reverts_pr6_stage(tmp_path):
    # Mutation: reverting the PR-6 progress record to the pre-PR-6 wording
    # must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-6 merged",
            "PR-6 has not started",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_pr6,
        repo,
        "does not state the PR-6 progress fact 'PR-6 merged'",
    )


def test_release_checker_fails_when_direction_loses_pr7_record(tmp_path):
    # Mutation: reverting the merged PR-7 progress record to the
    # pre-PR-7 wording must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-7 merged",
            "PR-7 has not started",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_cli,
        repo,
        "does not state the PR-7 progress fact 'PR-7 merged'",
    )


def _mutate_catalog_cli_append(repo: Path, snippet: str) -> None:
    path = repo / "src" / "market_vault" / "dataset" / "dataset_catalog_cli.py"
    path.write_text(
        path.read_text(encoding="utf-8") + f"\n{snippet}\n", encoding="utf-8"
    )


def _move_catalog_dispatch_after_settings(repo: Path) -> None:
    path = repo / "src" / "market_vault" / "cli.py"
    text = path.read_text(encoding="utf-8")
    old = (
        "    if args.command in DATASET_CATALOG_COMMANDS:\n"
        "        # The Dataset Catalog CLI is settings-independent exactly like the\n"
        "        # Dataset commands and the Sample Generation CLI: it never loads\n"
        "        # settings.yaml, never connects to OpenD, and never accesses the\n"
        "        # network. It is dispatched before load_settings with its own\n"
        "        # contract version constants and never falls under the Dataset CLI\n"
        "        # or the Sample Generation CLI contract.\n"
        "        return run_dataset_catalog_command(args.command, args)\n"
        "    settings = load_settings(args.settings)"
    )
    new = (
        "    settings = load_settings(args.settings)\n"
        "    if args.command in DATASET_CATALOG_COMMANDS:\n"
        "        # The Dataset Catalog CLI is settings-independent exactly like the\n"
        "        # Dataset commands and the Sample Generation CLI: it never loads\n"
        "        # settings.yaml, never connects to OpenD, and never accesses the\n"
        "        # network. It is dispatched before load_settings with its own\n"
        "        # contract version constants and never falls under the Dataset CLI\n"
        "        # or the Sample Generation CLI contract.\n"
        "        return run_dataset_catalog_command(args.command, args)"
    )
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_release_checker_fails_without_catalog_cli_models_module(tmp_path):
    # Mutation: removing the PR-7 CLI models module must fail the checker.
    repo = copy_repo(tmp_path)
    (repo / "src" / "market_vault" / "dataset" / "dataset_catalog_cli_models.py").unlink()
    assert_check_fails(
        _check_release.check_dataset_catalog_cli,
        repo,
        'src/market_vault/dataset/dataset_catalog_cli_models.py is missing',
    )


def test_release_checker_fails_when_catalog_cli_registration_removed(
    tmp_path,
):
    # Mutation: renaming one of the four command registrations must fail
    # the checker.
    repo = copy_repo(tmp_path)
    path = repo / "src" / "market_vault" / "dataset" / "dataset_catalog_cli.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            'add_parser(\n        "dataset-catalog-build",',
            'add_parser(\n        "dataset-catalog-buidl",',
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_cli,
        repo,
        'dataset_catalog_cli.py does not register dataset-catalog-build',
    )


def test_release_checker_fails_when_catalog_cli_adds_query_command(
    tmp_path,
):
    # Mutation: adding a fifth dataset-catalog-query command must fail the
    # checker.
    repo = copy_repo(tmp_path)
    _mutate_catalog_cli_append(
        repo, 'subparsers.add_parser("dataset-catalog-query")'
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_cli,
        repo,
        'must never register a fifth dataset-catalog-query command',
    )


def test_release_checker_fails_when_catalog_cli_dispatched_after_settings(
    tmp_path,
):
    # Mutation: moving the Dataset Catalog dispatch below load_settings
    # must fail the checker.
    repo = copy_repo(tmp_path)
    _move_catalog_dispatch_after_settings(repo)
    assert_check_fails(
        _check_release.check_dataset_catalog_cli,
        repo,
        'must dispatch the Dataset Catalog commands before load_settings',
    )


def test_release_checker_fails_when_catalog_cli_reloads_dataset(tmp_path):
    # Mutation: the CLI calling load_verified_dataset (instead of the
    # verified reader) must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "src" / "market_vault" / "dataset" / "dataset_catalog_cli.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "load_verified_dataset_catalog(",
            "load_verified_dataset(",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_cli,
        repo,
        "must not contain the forbidden pattern 'load_verified_dataset('",
    )


def test_release_checker_fails_when_catalog_cli_reads_catalog_json(
    tmp_path,
):
    # Mutation: the CLI reading the raw catalog.json must fail the checker.
    repo = copy_repo(tmp_path)
    _mutate_catalog_cli_append(repo, 'raw = snapshot_dir / "catalog.json"')
    assert_check_fails(
        _check_release.check_dataset_catalog_cli,
        repo,
        'must not contain the forbidden pattern \'"catalog.json"\'',
    )


def test_release_checker_fails_when_catalog_cli_gains_latest(tmp_path):
    repo = copy_repo(tmp_path)
    _mutate_catalog_cli_append(repo, 'parser.add_argument("--latest")')
    assert_check_fails(
        _check_release.check_dataset_catalog_cli,
        repo,
        "must not contain the forbidden pattern '--latest'",
    )


def test_release_checker_fails_when_catalog_cli_gains_force(tmp_path):
    repo = copy_repo(tmp_path)
    _mutate_catalog_cli_append(repo, 'parser.add_argument("--force")')
    assert_check_fails(
        _check_release.check_dataset_catalog_cli,
        repo,
        "must not contain the forbidden pattern '--force'",
    )


def test_release_checker_fails_when_catalog_cli_gains_overwrite(tmp_path):
    repo = copy_repo(tmp_path)
    _mutate_catalog_cli_append(repo, 'parser.add_argument("--overwrite")')
    assert_check_fails(
        _check_release.check_dataset_catalog_cli,
        repo,
        "must not contain the forbidden pattern '--overwrite'",
    )


def test_release_checker_fails_when_catalog_cli_loads_settings(tmp_path):
    repo = copy_repo(tmp_path)
    _mutate_catalog_cli_append(repo, "settings = load_settings(args.settings)")
    assert_check_fails(
        _check_release.check_dataset_catalog_cli,
        repo,
        "must not contain the forbidden pattern 'load_settings('",
    )


def test_release_checker_fails_when_catalog_cli_references_legacy_storage(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    _mutate_catalog_cli_append(
        repo, "legacy = market_vault.storage.catalog.Catalog"
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_cli,
        repo,
        "must not contain the forbidden pattern 'storage.catalog'",
    )


def test_release_checker_fails_when_catalog_cli_uses_duckdb(tmp_path):
    repo = copy_repo(tmp_path)
    _mutate_catalog_cli_append(repo, "import duckdb")
    assert_check_fails(
        _check_release.check_dataset_catalog_cli,
        repo,
        "must not contain the forbidden pattern 'duckdb'",
    )


def test_release_checker_fails_when_contract_doc_loses_and_semantics(
    tmp_path,
):
    # Mutation: removing the AND-semantics fact from the contract document
    # must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "dataset_catalog.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "AND semantics",
            "combined semantics",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_cli,
        repo,
        "does not state the PR-7 fact 'AND semantics'",
    )


def test_release_checker_fails_when_contract_doc_reclaims_pr8_not_started(
    tmp_path,
):
    # Mutation: "PR-8 has not started" is stale wording now that PR-8 is
    # complete; reintroducing it in the contract document must fail.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "dataset_catalog.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nPR-8 has not started.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_contract,
        repo,
        "still contains the stale claim 'PR-8 has not started'",
    )


def test_release_checker_fails_when_contract_doc_reclaims_catalog_cli_missing(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "dataset_catalog.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nCatalog CLI is not implemented.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_contract,
        repo,
        "still contains the stale claim 'Catalog CLI is not implemented'",
    )


def test_release_checker_fails_when_sample_contract_reclaims_catalog_missing(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "sample_generation.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nDataset Catalog (PR-5+) is not implemented.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_sample_generation_contract,
        repo,
        "still contains the stale claim 'Dataset Catalog (PR-5+) is not implemented'",
    )


def test_release_checker_fails_when_contract_doc_claims_repairs(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    _mutate_catalog_contract_doc(repo, "The CLI repairs the snapshot.")
    assert_check_fails(
        _check_release.check_dataset_catalog_cli,
        repo,
        "contains the false PR-7 claim 'repairs the snapshot'",
    )


def test_release_checker_fails_when_contract_doc_gains_latest_pointer(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    _mutate_catalog_contract_doc(repo, "The CLI maintains a latest pointer.")
    assert_check_fails(
        _check_release.check_dataset_catalog_cli,
        repo,
        "contains the false PR-7 claim 'maintains a latest pointer'",
    )


def test_release_checker_fails_when_ci_loses_pr7_smoke(tmp_path):
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8").replace(
            "PR7_CATALOG_CLI_HELP_OK", "PR7_MISSING_MARKER"
        ),
        encoding="utf-8",
    )
    assert_check_fails(_check_release.check_dataset_catalog_cli, repo, "PR-7 CLI help smoke marker")


def test_release_checker_fails_when_ci_loses_catalog_help_command(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8").replace(
            "market-vault dataset-catalog-show --help\n", ""
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_cli,
        repo,
        "must cover 'market-vault dataset-catalog-show --help'",
    )


def _mutate_catalog_models_marker(repo: Path, old: str, new: str) -> None:
    path = repo / "src" / "market_vault" / "dataset" / "dataset_catalog_models.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8"
    )


def test_release_checker_fails_when_row_version_coverage_reversed(tmp_path):
    # Mutation: reversing the coverage direction (pinned rows must be a
    # subset of the top-level list) must fail the checker.
    repo = copy_repo(tmp_path)
    _mutate_catalog_models_marker(
        repo,
        "uncovered = sorted(set(canonical_row_version_ids) - covered)",
        "uncovered = sorted(covered - set(canonical_row_version_ids))",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog,
        repo,
        "is missing the independent-review hardening marker 'set(canonical_row_version_ids) - covered'",
    )


def test_release_checker_fails_when_specpin_business_key_drifts(tmp_path):
    # Mutation: content_sha256 joining the SpecPin duplicate business key
    # must fail the checker.
    repo = copy_repo(tmp_path)
    _mutate_catalog_models_marker(
        repo,
        "key = (pin.kind, pin.name, pin.version)",
        "key = (pin.kind, pin.name, pin.version, pin.content_sha256)",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog,
        repo,
        "is missing the independent-review hardening marker 'key = (pin.kind, pin.name, pin.version)'",
    )


def test_release_checker_fails_when_unsafe_identity_text_rejection_lost(
    tmp_path,
):
    # Mutation: dropping the unsafe identity text rejection must fail.
    repo = copy_repo(tmp_path)
    _mutate_catalog_models_marker(
        repo,
        "reject_unsafe_text(text, label)",
        "reject_unsafe_text_nothing(text, label)",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog,
        repo,
        "is missing the independent-review hardening marker 'reject_unsafe_text(text, label)'",
    )


def test_release_checker_fails_when_location_binding_lost(tmp_path):
    # Mutation: dropping the build_path basename binding must fail.
    repo = copy_repo(tmp_path)
    _mutate_catalog_models_marker(
        repo,
        "!= self.dataset_facts.dataset_id",
        "== self.dataset_facts.dataset_id",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog,
        repo,
        "is missing the independent-review hardening marker '!= self.dataset_facts.dataset_id'",
    )


def test_release_checker_fails_when_contract_claims_metadata_enters_identity(
    tmp_path,
):
    # Mutation: a document claim that metadata enters the content identity
    # must fail (the legitimate wording never claims this).
    repo = copy_repo(tmp_path)
    _mutate_catalog_contract_doc(
        repo, "built_at enters Catalog content identity"
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_contract,
        repo,
        'contains the false identity claim',
    )


# --- V0.6.0 Dataset Catalog snapshot layer (PR-6) ----------------------------


def _mutate_catalog_builder(repo: Path, old: str, new: str) -> None:
    path = repo / "src" / "market_vault" / "dataset" / "dataset_catalog_builder.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8"
    )


def test_release_checker_fails_without_pr6_builder_module(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "src" / "market_vault" / "dataset" / "dataset_catalog_builder.py").unlink()
    assert_check_fails(
        _check_release.check_dataset_catalog_pr6,
        repo,
        'dataset_catalog_builder.py is missing',
    )


def test_release_checker_fails_without_pr6_reader_module(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "src" / "market_vault" / "dataset" / "dataset_catalog_reader.py").unlink()
    assert_check_fails(
        _check_release.check_dataset_catalog_pr6,
        repo,
        'dataset_catalog_reader.py is missing',
    )


def test_release_checker_fails_without_pr6_materializer_module(tmp_path):
    repo = copy_repo(tmp_path)
    (
        repo
        / "src"
        / "market_vault"
        / "dataset"
        / "dataset_catalog_materialization.py"
    ).unlink()
    assert_check_fails(
        _check_release.check_dataset_catalog_pr6,
        repo,
        'dataset_catalog_materialization.py is missing',
    )


def test_release_checker_fails_when_builder_version_constant_removed(tmp_path):
    repo = copy_repo(tmp_path)
    path = (
        repo
        / "src"
        / "market_vault"
        / "dataset"
        / "dataset_catalog_builder_models.py"
    )
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "market-vault-dataset-catalog-builder-v1",
            "market-vault-dataset-catalog-builder-v9",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_pr6,
        repo,
        "does not define the exact builder version constant 'market-vault-dataset-catalog-builder-v1'",
    )


def test_release_checker_fails_when_snapshot_id_version_constant_removed(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    path = (
        repo
        / "src"
        / "market_vault"
        / "dataset"
        / "dataset_catalog_snapshot_identity.py"
    )
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "market-vault-dataset-catalog-snapshot-id-v1",
            "market-vault-dataset-catalog-snapshot-id-v9",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_pr6,
        repo,
        "does not define the exact version constant 'market-vault-dataset-catalog-snapshot-id-v1'",
    )


def test_release_checker_fails_when_reader_version_constant_removed(tmp_path):
    repo = copy_repo(tmp_path)
    path = (
        repo
        / "src"
        / "market_vault"
        / "dataset"
        / "dataset_catalog_snapshot_identity.py"
    )
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "market-vault-verified-dataset-catalog-reader-v1",
            "market-vault-verified-dataset-catalog-reader-v9",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_pr6,
        repo,
        "does not define the exact version constant 'market-vault-verified-dataset-catalog-reader-v1'",
    )


def test_release_checker_fails_when_builder_trusts_manifest_directly(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    _mutate_catalog_builder(
        repo,
        "verified = load_verified_dataset(candidate)",
        "verified = _parse_manifest(candidate)",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_pr6,
        repo,
        "missing the contract marker 'load_verified_dataset(candidate)'",
    )


def test_release_checker_fails_when_builder_skips_verified_reader(tmp_path):
    repo = copy_repo(tmp_path)
    _mutate_catalog_builder(
        repo,
        "project_dataset_catalog_entry(verified)",
        "project_dataset_catalog_entry(None)",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_pr6,
        repo,
        "missing the contract marker 'project_dataset_catalog_entry(verified)'",
    )


def test_release_checker_fails_when_root_scan_becomes_recursive(tmp_path):
    repo = copy_repo(tmp_path)
    _mutate_catalog_builder(
        repo,
        "with os.scandir(dataset_root) as iterator:",
        "for entry in dataset_root.rglob('*'):",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_pr6,
        repo,
        "must not contain the forbidden pattern 'rglob'",
        "missing the contract marker 'os.scandir(dataset_root)'",
    )


def test_release_checker_fails_when_builder_reads_cwd_for_inputs(tmp_path):
    # Mutation: the builder reverting to a Path.cwd()-based relative
    # coercion of a formal input must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "src" / "market_vault" / "dataset" / "dataset_catalog_builder.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "    if not raw.is_absolute():\n"
        "        raise DatasetCatalogBuildError(\n"
        "            f\"{label} must be a lexically absolute path (cwd is never an \"\n"
        "            f\"implicit input), got {dataset_root!r}\"\n"
        "        )\n"
        "    return raw",
        "    if raw.is_absolute():\n"
        "        return raw\n"
        "    return Path.cwd() / raw",
    )
    path.write_text(text, encoding="utf-8")
    assert_check_fails(
        _check_release.check_dataset_catalog_pr6,
        repo,
        "must not contain the forbidden pattern 'Path.cwd()'",
    )


def test_release_checker_fails_when_content_identity_includes_path(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "src" / "market_vault" / "dataset" / "dataset_catalog_identity.py"
    path.write_text(
        path.read_text(encoding="utf-8") + '\n    "build_path": facts.build_path,\n',
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_pr6,
        repo,
        'must not contain the forbidden pattern \'"build_path":\'',
    )


def test_release_checker_fails_when_content_identity_includes_built_at(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    path = repo / "src" / "market_vault" / "dataset" / "dataset_catalog_identity.py"
    path.write_text(
        path.read_text(encoding="utf-8") + '\n    "built_at": facts.built_at,\n',
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_pr6,
        repo,
        'must not contain the forbidden pattern \'"built_at":\'',
    )


def test_release_checker_fails_when_snapshot_identity_includes_output_root(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    path = (
        repo
        / "src"
        / "market_vault"
        / "dataset"
        / "dataset_catalog_snapshot_identity.py"
    )
    path.write_text(
        path.read_text(encoding="utf-8") + '\n    "output_root": output_root,\n',
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_pr6,
        repo,
        'must not contain the forbidden pattern \'"output_root"\'',
    )


def test_release_checker_fails_when_reader_reloads_recorded_paths(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "src" / "market_vault" / "dataset" / "dataset_catalog_reader.py"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nload_verified_dataset(entry.recorded_build_path)\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_pr6,
        repo,
        "must not contain the forbidden pattern 'load_verified_dataset('",
    )


def test_release_checker_fails_when_reader_loses_historical_location_contract(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    path = repo / "src" / "market_vault" / "dataset" / "dataset_catalog_reader.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "historical observed location text", "live dataset path"
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_pr6,
        repo,
        "missing the contract marker 'historical observed location'",
    )


def test_release_checker_fails_when_success_not_written_last(tmp_path):
    repo = copy_repo(tmp_path)
    path = (
        repo
        / "src"
        / "market_vault"
        / "dataset"
        / "dataset_catalog_materialization.py"
    )
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "    _write_empty_success(success_path)",
        "    raced = _publish_staging(\n"
        "        staging, final, result=result,\n"
        "        built_at=built_at, snapshot_id=snapshot_id,\n"
        "        catalog_bytes=catalog_bytes,\n"
        "    )\n"
        "    if raced is not None:\n"
        "        return raced\n"
        "    _write_empty_success(success_path)",
        1,
    )
    path.write_text(text, encoding="utf-8")
    assert_check_fails(
        _check_release.check_dataset_catalog_pr6,
        repo,
        'must write _SUCCESS before the atomic publication',
    )


def test_release_checker_fails_when_publication_allows_overwrite(tmp_path):
    repo = copy_repo(tmp_path)
    path = (
        repo
        / "src"
        / "market_vault"
        / "dataset"
        / "dataset_catalog_materialization.py"
    )
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "_atomic_rename_directory_no_replace(staging, final)",
            "os.replace(staging, final)",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_pr6,
        repo,
        "must not contain the forbidden pattern 'os.replace('",
        "missing the contract marker '_atomic_rename_directory_no_replace(",
    )


def test_release_checker_fails_when_latest_appears(tmp_path):
    repo = copy_repo(tmp_path)
    path = (
        repo
        / "src"
        / "market_vault"
        / "dataset"
        / "dataset_catalog_materialization.py"
    )
    path.write_text(
        path.read_text(encoding="utf-8") + '\nlatest = final.parent / "latest"\n',
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_pr6,
        repo,
        'must not contain the forbidden pattern \'"latest"\'',
    )


def test_release_checker_fails_when_write_return_validation_lost(tmp_path):
    repo = copy_repo(tmp_path)
    path = (
        repo
        / "src"
        / "market_vault"
        / "dataset"
        / "dataset_catalog_materialization.py"
    )
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "type(written) is not int or written != len(data)",
            "written is None",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_pr6,
        repo,
        "missing the contract marker 'type(written) is not int",
    )


def test_release_checker_fails_when_package_loses_pr6_export(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "src" / "market_vault" / "dataset" / "__init__.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "build_dataset_catalog",
            "missing_catalog_builder",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_dataset_catalog_pr6,
        repo,
        "market_vault.dataset does not export the PR-6 public API 'build_dataset_catalog'",
    )


def test_release_checker_fails_when_ci_loses_pr6_smoke(tmp_path):
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8").replace(
            "PR6_CATALOG_API_IMPORT_OK", "PR6_MISSING_MARKER"
        ),
        encoding="utf-8",
    )
    assert_check_fails(_check_release.check_dataset_catalog_pr6, repo, "PR-6 public API smoke marker")


# --- V0.6.0 integrated acceptance (PR-8) ------------------------------------


def test_release_checker_fails_without_acceptance_doc(tmp_path):
    # Mutation: the acceptance document must exist.
    repo = copy_repo(tmp_path)
    (repo / "docs" / "v0_6_0_acceptance.md").unlink()
    assert_check_fails(
        _check_release.check_v060_acceptance,
        repo,
        'docs/v0_6_0_acceptance.md is missing',
    )


def test_release_checker_fails_when_acceptance_doc_claims_released(tmp_path):
    # Mutation: an affirmative "v0.6.0 is released" claim in the
    # acceptance document must fail the checker even when the required
    # facts are present (the legitimate "v0.6.0 is not released" wording
    # is preserved in the real document).
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_acceptance.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\nv0.6.0 is released.\n",
        encoding="utf-8",
    )
    assert_check_fails(_check_release.check_v060_acceptance, repo, "false claim 'v0.6.0 is released'")


def test_release_checker_fails_when_acceptance_doc_loses_pyarrow_fact(tmp_path):
    # Mutation: deleting an audited PyArrow writer fact must fail the
    # checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_acceptance.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PyArrow 25.0.0", "PyArrow 26.0.0"
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v060_acceptance,
        repo,
        "does not state the fact 'PyArrow 25.0.0'",
    )


def test_release_checker_fails_when_acceptance_doc_claims_byte_identical(
    tmp_path,
):
    # Mutation: a false byte-identical cross-writer claim must fail the
    # checker (the audited source Parquet physical bytes DIFFER).
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_acceptance.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nThe source Parquet bytes are byte-identical across writers.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v060_acceptance,
        repo,
        "false claim 'byte-identical across writers'",
    )


def test_release_checker_fails_when_acceptance_doc_removes_physical_provenance(
    tmp_path,
):
    # Mutation: claiming physical_snapshot_hash is not part of the
    # physical source provenance must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_acceptance.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nphysical_snapshot_hash is not part of the provenance.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v060_acceptance,
        repo,
        "false claim 'physical_snapshot_hash is not part of'",
    )


def test_release_checker_fails_when_acceptance_doc_loses_frozen_generation_id(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_acceptance.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "f70e0c89793a1ccfb51d8a16720a8446a74989415ad7c491608d19e2dd759fb3",
            "f70e0c89793a1ccfb51d8a16720a8446a74989415ad7c491608d19e2dd759fb4",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v060_acceptance,
        repo,
        'must record the frozen generation content id',
    )


def test_release_checker_fails_when_acceptance_doc_claims_pr9_started(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_acceptance.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\nPR-9 has started.\n",
        encoding="utf-8",
    )
    assert_check_fails(_check_release.check_v060_acceptance, repo, "false claim 'PR-9 has started'")


def test_release_checker_fails_without_acceptance_helpers(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "tests" / "v060_acceptance_helpers.py").unlink()
    assert_check_fails(
        _check_release.check_v060_frozen_fixture,
        repo,
        'tests/v060_acceptance_helpers.py is missing',
    )


def test_release_checker_fails_without_fixture_bundle(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "tests" / "fixtures" / "v060_portability" / "canonical_fixture.b64").unlink()
    assert_check_fails(
        _check_release.check_v060_frozen_fixture,
        repo,
        'canonical_fixture.b64 is missing',
    )


def test_release_checker_fails_when_frozen_fixture_generation_id_changes(
    tmp_path,
):
    # Mutation: re-baselining the frozen generation content id in the
    # acceptance helpers must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "tests" / "v060_acceptance_helpers.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "f70e0c89793a1ccfb51d8a16720a8446a74989415ad7c491608d19e2dd759fb3",
            "f70e0c89793a1ccfb51d8a16720a8446a74989415ad7c491608d19e2dd759fb4",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v060_frozen_fixture,
        repo,
        'the frozen FIXTURE_GENERATION_ID must not change',
    )


def test_release_checker_fails_when_frozen_fixture_plan_sha_changes(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "tests" / "v060_acceptance_helpers.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "78cd9e895ee966722c83db8d5388a49c635b8fd448fe8de796e2b56dcebf964b",
            "78cd9e895ee966722c83db8d5388a49c635b8fd448fe8de796e2b56dcebf964c",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v060_frozen_fixture,
        repo,
        'the frozen FROZEN_RELATIVE_PLAN_SHA256 must not change',
    )


def test_release_checker_fails_when_pyarrow_pinned(tmp_path):
    # Mutation: pinning pyarrow==24.0.0 in pyproject.toml must fail the
    # checker (the pyarrow>=16 boundary must stay).
    repo = copy_repo(tmp_path)
    path = repo / "pyproject.toml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            '"pyarrow>=16"', '"pyarrow==24.0.0"'
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_pyarrow_dependency,
        repo,
        'must keep the pyarrow>=16 dependency',
        'must never pin a PyArrow writer version',
    )


def test_release_checker_fails_when_ci_matrix_changes(tmp_path):
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8").replace(
            '["3.11", "3.14"]', '["3.11", "3.13", "3.14"]'
        ),
        encoding="utf-8",
    )
    assert_check_fails(_check_release.check_ci_pr8, repo, "CI python matrix must stay exactly")


def test_release_checker_fails_without_portability_job(tmp_path):
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8").replace(
            "portability-pyarrow24", "portability-pyarrow25"
        ),
        encoding="utf-8",
    )
    assert_check_fails(_check_release.check_ci_pr8, repo, "portability-pyarrow24 job")


@pytest.mark.parametrize(
    "replacement",
    [
        'pip install "pyarrow>=24.0.0"',  # pin changed
        'pip install "pyarrow"',  # pin removed
    ],
)
def test_release_checker_fails_when_portability_job_unpinned(
    tmp_path, replacement
):
    # Mutation: the portability job installing a non-pinned pyarrow
    # (changed or unpinned) must fail the checker.
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8").replace(
            'pip install "pyarrow==24.0.0"',
            replacement,
        ),
        encoding="utf-8",
    )
    assert_check_fails(_check_release.check_ci_pr8, repo, "must install pyarrow==24.0.0")


def test_release_checker_fails_when_ci_loses_acceptance_marker(tmp_path):
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8").replace(
            "PR8_INTEGRATED_ACCEPTANCE_OK", "PR8_MISSING_MARKER"
        ),
        encoding="utf-8",
    )
    assert_check_fails(_check_release.check_ci_pr8, repo, "PR8_INTEGRATED_ACCEPTANCE_OK")


def test_release_checker_allows_negated_release_wording_in_acceptance_doc(
    tmp_path,
):
    # "v0.6.0 is not released" is the required legitimate wording and must
    # never be rejected.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_acceptance.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nv0.6.0 is not released by PR-8.\n",
        encoding="utf-8",
    )
    assert _check_release.check_v060_acceptance(repo) == []


def test_release_checker_fails_when_acceptance_doc_loses_upstream_curated_provenance(
    tmp_path,
):
    # Mutation: losing the upstream source / curated provenance wording
    # must fail the checker (the source Parquet bytes are identity-bearing
    # physical source provenance).
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_acceptance.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "upstream source / curated snapshot",
            "upstream source snapshot",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v060_acceptance,
        repo,
        "does not state the fact 'upstream source / curated'",
    )


def test_release_checker_fails_when_acceptance_doc_loses_canonical_output_parquet(
    tmp_path,
):
    # Mutation: blurring the Canonical output Parquet artifact into the
    # source provenance input must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_acceptance.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "Canonical output Parquet",
            "Canonical output artifact",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v060_acceptance,
        repo,
        "does not state the fact 'Canonical output Parquet'",
    )


def test_release_checker_fails_when_acceptance_doc_loses_exactly_empty_success(
    tmp_path,
):
    # Mutation: relaxing the Catalog snapshot _SUCCESS contract (bytes
    # exactly empty) must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_acceptance.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "bytes exactly empty",
            "bytes empty",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v060_acceptance,
        repo,
        "does not state the fact 'exactly empty'",
    )


def test_release_checker_fails_when_acceptance_doc_claims_every_supported_writer(
    tmp_path,
):
    # Mutation: the over-strong "every supported PyArrow writer" claim
    # must fail the checker (only 24.0.0 and 25.0.0 are audited).
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_acceptance.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nevery supported PyArrow writer version is proven.\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v060_acceptance,
        repo,
        "false claim 'every supported PyArrow writer'",
    )


def test_release_checker_fails_when_portability_job_loses_c_surface_step(
    tmp_path,
):
    # Mutation: removing the PyArrow 24 sensitive regression surface step
    # (P0-1 replacement for the old full offline suite step) must fail the
    # checker.
    repo = copy_repo(tmp_path)
    path = repo / ".github" / "workflows" / "ci.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "Run audited PyArrow 24 sensitive regression surface",
            "Run audited PyArrow 24 compatibility subset",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_ci_pr8,
        repo,
        "must include the audited PyArrow 24 sensitive regression step",
    )


@pytest.mark.parametrize(
    "test_file",
    [
        "tests/test_canonical_materialization_v03.py",
        "tests/test_canonical_builder_v03.py",
        "tests/test_dataset_materialization.py",
        "tests/test_verified_dataset_reader.py",
        "tests/test_pit_sample_assembly.py",
        "tests/test_dataset_end_to_end_regression.py",
    ],
)
def test_release_checker_fails_when_any_c_surface_file_removed(
    tmp_path, test_file
):
    # Mutation: removing any one of the six audited PyArrow 24 sensitive
    # regression files must fail the checker (the six-file contract is
    # literal and reviewable).
    repo = copy_repo(tmp_path)
    path = repo / ".github" / "workflows" / "ci.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            test_file, test_file.replace(".py", "_missing.py")
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_ci_pr8,
        repo,
        f"must run the exact audited sensitive regression file {test_file!r}",
    )


def test_release_checker_fails_when_c_surface_file_replaced_by_unrelated_test(
    tmp_path,
):
    # Mutation: swapping one C surface file for an unrelated test file
    # must fail the checker (the C file set cannot be inferred at
    # runtime; it is exact).
    repo = copy_repo(tmp_path)
    path = repo / ".github" / "workflows" / "ci.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "tests/test_canonical_materialization_v03.py",
            "tests/test_v061_ci_auditability.py",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_ci_pr8,
        repo,
        "must run the exact audited sensitive regression file "
        "'tests/test_canonical_materialization_v03.py'",
    )


def test_release_checker_fails_when_portability_job_restores_blanket_full_step(
    tmp_path,
):
    # Mutation: restoring the old blanket FULL PyArrow step in place of
    # the C surface must fail the checker (the old step name is
    # forbidden, C is required, and no unqualified pytest run may appear
    # in the portability job).
    repo = copy_repo(tmp_path)
    path = repo / ".github" / "workflows" / "ci.yml"
    text = path.read_text(encoding="utf-8")
    c_step_region = (
        "- name: Run audited PyArrow 24 sensitive regression surface\n"
        "        if: env.CI_TIER != 'docs_fast' && env.CI_TIER != "
        "'package_docs' && env.POST_MERGE_REUSE != 'true'\n"
        "        run: |\n"
        "          python -m pytest \\\n"
        "            tests/test_canonical_materialization_v03.py \\\n"
        "            tests/test_canonical_builder_v03.py \\\n"
        "            tests/test_dataset_materialization.py \\\n"
        "            tests/test_verified_dataset_reader.py \\\n"
        "            tests/test_pit_sample_assembly.py \\\n"
        "            tests/test_dataset_end_to_end_regression.py \\\n"
        "            -q --durations=100\n"
    )
    old_full_region = (
        "- name: Run full offline suite under PyArrow 24.0.0\n"
        "        run: python -m pytest\n"
    )
    assert c_step_region in text
    path.write_text(
        text.replace(c_step_region, old_full_region), encoding="utf-8"
    )
    assert_check_fails(
        _check_release.check_ci_pr8,
        repo,
        "must never restore the blanket",
        "must include the audited PyArrow 24 sensitive regression step",
        "must never run an unqualified",
    )


def test_release_checker_fails_when_portability_job_loses_a_surface(
    tmp_path,
):
    # Mutation: removing the exact targeted portability surface (A) must
    # fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / ".github" / "workflows" / "ci.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "python -m pytest tests/test_v060_portability.py -q",
            "python -m pytest -q",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_ci_pr8,
        repo,
        "must keep the exact portability surface "
        "'tests/test_v060_portability.py'",
    )


@pytest.mark.parametrize(
    "test_file",
    [
        "tests/test_canonical_reader.py",
        "tests/test_sample_generation_core.py",
        "tests/test_sample_generation_cli.py",
    ],
)
def test_release_checker_fails_when_b_surface_member_removed(
    tmp_path, test_file
):
    # Mutation: removing any one of the three canonical / frozen
    # regression files (B) must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / ".github" / "workflows" / "ci.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            test_file, test_file.replace(".py", "_missing.py")
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_ci_pr8,
        repo,
        f"must keep the exact canonical/frozen regression file {test_file!r}",
    )


def test_release_checker_fails_when_portability_job_loses_version_assertion(
    tmp_path,
):
    # Mutation: removing the explicit PyArrow version assertion step must
    # fail the checker (the runtime is only audited when the asserted
    # version stays pinned).
    repo = copy_repo(tmp_path)
    path = repo / ".github" / "workflows" / "ci.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "Assert the audited PyArrow compatibility version",
            "Assert the installed PyArrow version",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_ci_pr8,
        repo,
        "must keep the explicit PyArrow version assertion step",
    )


def _mutate_step_guard(tmp_path, step_name, old, new):
    """Replace ``old`` with ``new`` inside the exact YAML region of one
    named step of the portability-pyarrow24 job only. Every other step —
    and every other job — stays byte-identical, so the mutation proves
    the checker is step-scoped rather than block-scoped."""
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    text = ci.read_text(encoding="utf-8")
    block = _check_release._ci_job_block(text, "portability-pyarrow24")
    assert block is not None
    region = _check_release._ci_step_region(block, step_name)
    assert region is not None, step_name
    assert old in region, (step_name, old)
    new_block = block.replace(region, region.replace(old, new))
    assert block in text
    ci.write_text(text.replace(block, new_block), encoding="utf-8")
    return repo


@pytest.mark.parametrize(
    ("old_fragment", "new_fragment"),
    [
        # A: docs_fast exclusion inverted on the C step only.
        ("env.CI_TIER != 'docs_fast'", "env.CI_TIER == 'docs_fast'"),
        # B: package_docs exclusion inverted on the C step only.
        ("env.CI_TIER != 'package_docs'", "env.CI_TIER == 'package_docs'"),
        # C: reuse exclusion inverted on the C step only.
        ("env.POST_MERGE_REUSE != 'true'", "env.POST_MERGE_REUSE == 'true'"),
        # D: POST_MERGE_REUSE condition removed from the C step only.
        (" && env.POST_MERGE_REUSE != 'true'", ""),
    ],
)
def test_release_checker_fails_when_c_step_guard_weakened(
    tmp_path, old_fragment, new_fragment
):
    # Mutation: weakening the C step's own heavy guard only — every
    # other heavy step and the A/B surfaces stay byte-identical — must
    # fail the checker with exactly the C-step guard failure (the exact
    # guard line is pinned inside the C step region, not searched
    # block-globally).
    repo = _mutate_step_guard(
        tmp_path,
        "Run audited PyArrow 24 sensitive regression surface",
        old_fragment,
        new_fragment,
    )
    failures = assert_check_fails(
        _check_release.check_ci_pr8,
        repo,
        "C step must keep the exact fail-closed heavy guard",
    )
    assert len(failures) == 1, failures


def test_release_checker_fails_when_reuse_marker_guard_inverted(tmp_path):
    # Mutation: inverting only the verified-reuse marker step's own guard
    # must fail the checker with exactly the marker-step guard failure
    # (the marker may only sit behind a PROVEN POST_MERGE_REUSE ==
    # 'true', bound to its own step region).
    repo = _mutate_step_guard(
        tmp_path,
        "FULL tests reused from verified PR",
        "env.POST_MERGE_REUSE == 'true'",
        "env.POST_MERGE_REUSE != 'true'",
    )
    failures = assert_check_fails(
        _check_release.check_ci_pr8,
        repo,
        "verified-reuse marker step must keep the exact guard",
    )
    assert len(failures) == 1, failures


def test_release_checker_fails_when_c_step_duplicated(tmp_path):
    # Mutation: duplicating the C step inside the portability job must
    # fail closed (a duplicated step must never validate an arbitrary
    # region).
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    text = ci.read_text(encoding="utf-8")
    marker = "- name: Run audited PyArrow 24 sensitive regression surface"
    assert text.count(marker) == 1
    ci.write_text(
        text.replace(
            marker,
            marker + "\n        run: echo duplicate\n" + marker,
            1,
        ),
        encoding="utf-8",
    )
    failures = assert_check_fails(
        _check_release.check_ci_pr8,
        repo,
        "is duplicated in the job block",
    )
    assert len(failures) == 1, failures


def test_ci_step_region_helper_semantics():
    # The step-region helper must return None for a missing step, return
    # exactly the named step's YAML (never leaking the next step), and
    # raise ValueError on a duplicated step so the checker fails closed.
    block = (
        "      - name: Alpha\n"
        "        run: echo 1\n"
        "      - name: Beta\n"
        "        run: echo 2\n"
    )
    assert _check_release._ci_step_region(block, "Gamma") is None
    alpha = _check_release._ci_step_region(block, "Alpha")
    assert alpha.startswith("- name: Alpha")
    assert "Beta" not in alpha
    with pytest.raises(ValueError):
        _check_release._ci_step_region(block + block, "Alpha")


def test_release_checker_fails_when_package_job_loses_portability_dependency(
    tmp_path,
):
    # Mutation: dropping the portability-pyarrow24 dependency of the
    # package job must fail the checker (the formal job topology stays
    # unchanged).
    repo = copy_repo(tmp_path)
    path = repo / ".github" / "workflows" / "ci.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "needs: [test, portability-pyarrow24]",
            "needs: test",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_ci_pr8,
        repo,
        "must depend on [test, portability-pyarrow24]",
    )


# --- V0.7.0 PR-5 guards: integrated E2E / usability / examples -------------


def test_release_checker_fails_without_usage_doc(tmp_path):
    # PR-5 guard: deleting the Python client usage document must fail the
    # checker.
    repo = copy_repo(tmp_path)
    (repo / "docs" / "v0_7_0_python_client_usage.md").unlink()
    assert_check_fails(
        _check_release.check_v070_python_client_usage_doc,
        repo,
        'docs/v0_7_0_python_client_usage.md is missing',
    )


def test_release_checker_fails_without_examples_readme(tmp_path):
    # PR-5 guard: deleting the source-tree examples README must fail the
    # checker.
    repo = copy_repo(tmp_path)
    (repo / "examples" / "python_client" / "README.md").unlink()
    assert_check_fails(
        _check_release.check_v070_python_client_examples,
        repo,
        'examples/python_client/README.md is missing',
    )


def test_release_checker_fails_without_executable_example(tmp_path):
    # PR-5 guard: deleting the executable example must fail the checker.
    repo = copy_repo(tmp_path)
    (repo / "examples" / "python_client" / "read_verified_artifacts.py").unlink()
    assert_check_fails(
        _check_release.check_v070_python_client_examples,
        repo,
        'examples/python_client/read_verified_artifacts.py is missing',
    )


def test_release_checker_fails_when_direction_regresses_pr5_to_not_started(
    tmp_path,
):
    # PR-6 guard: regressing the merged PR-5 stage back to NOT STARTED
    # must fail the checker — PR-5 is COMPLETE / MERGED / MAIN VERIFIED.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_7_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-5: COMPLETE / MERGED / MAIN VERIFIED",
            "PR-5: NOT STARTED",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_direction,
        repo,
        "contains the false implementation/release claim 'PR-5: NOT STARTED'",
    )


def test_release_checker_fails_when_direction_regresses_pr4_to_current(
    tmp_path,
):
    # PR-5 guard: regressing the merged PR-4 stage back to CURRENT must
    # fail the checker — PR-4 is merged history.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_7_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-4: COMPLETE / MERGED / MAIN VERIFIED",
            "PR-4: CURRENT",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_direction,
        repo,
        "contains the false implementation/release claim 'PR-4: CURRENT'",
    )


def test_release_checker_fails_when_direction_regresses_v070_to_not_released(
    tmp_path,
):
    # Post-release guard: the direction document regressing the formally
    # released v0.7.0 state back to a bare unqualified RELEASED claim or
    # to the preparation-time NOT RELEASED state must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_7_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "v0.7.0: FORMALLY RELEASED",
            "v0.7.0: NOT RELEASED",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_direction,
        repo,
        "contains the false implementation/release claim 'v0.7.0: NOT RELEASED'",
    )


def test_release_checker_fails_when_usage_doc_loses_explicit_path_contract(
    tmp_path,
):
    # PR-5 guard: the usage document losing the explicit-path contract
    # must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_7_0_python_client_usage.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "Every artifact path is EXPLICIT",
            "Every artifact path is IMPLICIT",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_python_client_usage_doc,
        repo,
        "does not state the fact 'Every artifact path is EXPLICIT'",
    )


def test_release_checker_fails_when_usage_doc_loses_jupyter_post_verification(
    tmp_path,
):
    # PR-5 guard: the usage document losing the Jupyter consumer-side
    # post-verification marker must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_7_0_python_client_usage.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "pd.DataFrame(dataset.rows",
            "pd.DataFrame(rows",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_python_client_usage_doc,
        repo,
        "does not state the fact 'pd.DataFrame(dataset.rows'",
    )


def test_release_checker_fails_when_usage_doc_gains_ml_implementation(
    tmp_path,
):
    # PR-5 guard: the usage document gaining ML implementation code must
    # fail the checker — the guide documents a handoff, never an ML
    # implementation.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_7_0_python_client_usage.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n```python\nmodel.fit(X_train, y_train)\n```\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_python_client_usage_doc,
        repo,
        "contains the false discovery/ML claim 'model.fit('",
    )


def test_release_checker_fails_when_example_gains_forbidden_import(
    tmp_path,
):
    # PR-5 guard: the executable example gaining a discovery / settings /
    # network / write / parse import (here `os`) must fail the checker —
    # the example is stdlib + market_vault only.
    repo = copy_repo(tmp_path)
    example = (
        repo / "examples" / "python_client" / "read_verified_artifacts.py"
    )
    example.write_text(
        example.read_text(encoding="utf-8")
        + "\nimport os\n",
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_python_client_examples,
        repo,
        'the example must import only stdlib plus the market_vault top level',
    )


def test_release_checker_fails_when_example_argument_loses_required(
    tmp_path,
):
    # PR-5 guard: an example path argument dropping required=True must
    # fail the checker — all three arguments are explicit and mandatory.
    repo = copy_repo(tmp_path)
    example = (
        repo / "examples" / "python_client" / "read_verified_artifacts.py"
    )
    example.write_text(
        example.read_text(encoding="utf-8").replace(
            "--catalog-snapshot-dir\", required=True",
            "--catalog-snapshot-dir\", required=False",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_v070_python_client_examples,
        repo,
        'each example path argument must be required=True',
    )


def test_release_checker_fails_when_ci_loses_v070_integrated_acceptance_ok(
    tmp_path,
):
    # PR-5 guard: the CI losing the V070_INTEGRATED_ACCEPTANCE_OK marker
    # must fail the checker.
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8").replace(
            "V070_INTEGRATED_ACCEPTANCE_OK",
            "V070_INTEGRATED_ACCEPTANCE_MISSING",
        ),
        encoding="utf-8",
    )
    assert_check_fails(
        _check_release.check_ci_auditability,
        repo,
        "CI package audit chain is missing 'V070_INTEGRATED_ACCEPTANCE_OK'",
    )

# --- Registry wiring guards (A-F) -------------------------------------------
# The mutation tests invoke individual production checks directly. These
# guards pin the CHECKS registry contract so the direct-invocation harness
# cannot drift from the full-checker behavior they replace: the exact label
# set and order (A), label uniqueness (B), collect_failures() invoking every
# entry (C), aggregation in registry order (D), and the CLI main() using the
# same single collection path (E). If a production check is removed from the
# registry, test_check_registry_matches_pinned_labels_and_order fails (F).

EXPECTED_CHECKS = (
    ("pyproject version", "check_pyproject_version"),
    ("package __version__", "check_package_version"),
    ("README title", "check_readme_title"),
    ("CHANGELOG entry", "check_changelog"),
    ("README wording", "check_readme_no_stale_wording"),
    ("README maintenance section", "check_readme_maintenance_section"),
    ("README v0.6.1 section", "check_readme_v061_section"),
    ("direction status", "check_direction_status"),
    ("release notes", "check_release_notes"),
    ("v0.5.1 release notes", "check_v051_release_notes"),
    ("v0.6.0 release notes", "check_v060_release_notes"),
    ("v0.5.1 direction", "check_v051_direction"),
    ("v0.6.0 direction", "check_v060_direction"),
    ("v0.6.1 direction", "check_v061_direction"),
    ("v0.6.1 release notes", "check_v061_release_notes"),
    ("v0.6.1 CLI usability audit", "check_v061_cli_usability_audit"),
    ("v0.7.0 release notes", "check_v070_release_notes"),
    ("v0.7.0 direction", "check_v070_direction"),
    ("v0.7.0 Python client contract", "check_v070_python_client_contract"),
    ("v0.7.0 Python API audit", "check_v070_python_api_audit"),
    ("v0.7.0 ArtifactClient foundation", "check_v070_artifact_client_foundation"),
    ("v0.7.0 ArtifactClient readers", "check_v070_artifact_client_readers"),
    ("v0.7.0 ArtifactClient catalog", "check_v070_artifact_client_catalog"),
    ("v0.7.0 Python client usage doc", "check_v070_python_client_usage_doc"),
    ("v0.7.0 Python client examples", "check_v070_python_client_examples"),
    ("CI auditability", "check_ci_auditability"),
    ("v0.6.1 CI package audit", "check_v061_ci_package_audit"),
    ("v0.6.0 ADR", "check_v060_adr"),
    ("sample generation modules", "check_sample_generation_modules"),
    ("sample generation contract", "check_sample_generation_contract"),
    ("sample generator core", "check_sample_generation_core"),
    ("sample generation cli", "check_sample_generation_cli"),
    ("dataset catalog contract", "check_dataset_catalog_contract"),
    ("dataset catalog", "check_dataset_catalog"),
    ("dataset catalog pr6", "check_dataset_catalog_pr6"),
    ("dataset catalog cli", "check_dataset_catalog_cli"),
    ("v0.6.0 acceptance", "check_v060_acceptance"),
    ("v0.6.0 frozen fixture", "check_v060_frozen_fixture"),
    ("pyarrow dependency", "check_pyarrow_dependency"),
    ("CI PR-8 portability", "check_ci_pr8"),
    ("CI v0.7.0 released state", "check_ci_v070_released_state"),
    ("CI v0.7.0 public API smoke", "check_ci_v070_public_api_smoke"),
    ("old release notes", "check_old_release_notes"),
    ("warning guard", "check_warning_guard"),
    ("examples", "check_examples"),
    ("README upgrade notes", "check_readme_upgrade_sections"),
    ("README dataset builder", "check_readme_dataset_builder_section"),
    ("README explicit plan", "check_readme_explicit_build_plan"),
    ("README adjustment boundary", "check_readme_adjustment_none"),
    ("README dataset boundaries", "check_readme_dataset_boundaries"),
    ("CI version assertions", "check_ci_version_assertions"),
    ("build artifacts untracked", "check_build_artifacts_untracked"),
    ("PEP 440 version", "check_pep440"),
    ("CLI version output", "check_cli_version"),
)


def test_check_registry_matches_pinned_labels_and_order():
    """Guards A and F: the registry preserves the exact production check
    labels in their exact order; removing, reordering, or renaming any
    registry entry fails this test."""
    assert tuple((label, fn.__name__) for label, fn in _check_release.CHECKS) == EXPECTED_CHECKS


def test_check_registry_labels_are_unique():
    """Guard B: no two registry entries share a label, and the registry is
    exactly the pinned check set."""
    labels = [label for label, _ in _check_release.CHECKS]
    assert len(labels) == len(set(labels))
    assert len(labels) == len(EXPECTED_CHECKS)


def test_collect_failures_invokes_every_check_in_registry_order(monkeypatch):
    """Guards C and D: collect_failures() runs every registry entry exactly
    once and aggregates failures in registry order (no fail-fast, no
    omission).

    The registry itself is swapped for sentinel entries (collect_failures
    reads the module-level CHECKS name), because some production checks
    call each other by module attribute; patching attributes would not
    intercept the registry references."""
    calls = []

    def sentinel(root, _label):
        calls.append(_label)
        return [f"{_label}: injected"]

    sentinel_checks = [
        (label, (lambda root, _l=label: sentinel(root, _l)))
        for label, _ in _check_release.CHECKS
    ]
    monkeypatch.setattr(_check_release, "CHECKS", tuple(sentinel_checks))
    failures = _check_release.collect_failures(ROOT)
    assert calls == [label for label, _ in _check_release.CHECKS]
    assert failures == [f"{label}: injected" for label, _ in _check_release.CHECKS]


def test_main_uses_collect_failures(monkeypatch, capsys):
    """Guard E: the CLI entry point aggregates through the same production
    path (collect_failures), so the registry guards cover the CLI output."""
    marker = {"called": False}

    def fake_collect(root):
        marker["called"] = True
        return ["injected failure"]

    monkeypatch.setattr(_check_release, "collect_failures", fake_collect)
    assert _check_release.main() == 1
    out = capsys.readouterr().out
    assert marker["called"]
    assert out.startswith("RELEASE_CHECK_FAILED")
    assert "- injected failure" in out
