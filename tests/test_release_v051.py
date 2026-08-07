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

import market_vault
from market_vault import MarketVault
from market_vault._version import __version__
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars, normalize_trading_calendar
from market_vault.storage import Catalog, ParquetStore

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
EXPECTED_VERSION = "0.5.1"
PUBLIC_API_IMPORT_CODE = "\n".join(
    [
        "from market_vault.canonical import load_verified_canonical_build",
        "from market_vault.dataset import (",
        "    orchestrate_dataset_build,",
        "    materialize_dataset_artifacts,",
        "    load_verified_dataset,",
        ")",
        "print('V051_PUBLIC_API_IMPORT_OK')",
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


def test_readme_title_is_v051():
    first_line = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()[0]
    assert first_line.strip() == "# MarketVault v0.5.1"


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


def test_changelog_contains_051():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [0.5.1] - 2026-08-06" in text


def test_changelog_still_contains_050():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [0.5.0] - 2026-08-05" in text


def test_changelog_still_contains_040():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [0.4.0] - 2026-08-05" in text


def test_changelog_contains_051_compare_link():
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


def test_readme_does_not_claim_v06():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "v0.6" not in text


def test_direction_document_is_released():
    text = (ROOT / "docs" / "v0_5_0_direction.md").read_text(encoding="utf-8")
    assert "Status: released" in text
    assert "Status: proposed" not in text
    assert "PR-10 has not started" not in text
    assert "Status: implementation complete; v0.5.0 release preparation" not in text
    assert "3b4d03c785123e204885faea08df7b9d7ed07ec0" in text


def test_readme_describes_ci_matrix():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Runs CI on Python 3.11 and 3.14" in text


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


# --- V0.5 public API imports ------------------------------------------------


def test_v051_public_api_imports_succeed(tmp_path):
    result = run_code_in(tmp_path, PUBLIC_API_IMPORT_CODE)
    assert result.returncode == 0, result.stderr
    assert "V051_PUBLIC_API_IMPORT_OK" in result.stdout


def test_v051_public_api_imports_do_not_connect_opend(tmp_path):
    # The imports run from an empty directory without any settings file or
    # OpenD host; a collector connection attempt would fail loudly.
    result = run_code_in(tmp_path, PUBLIC_API_IMPORT_CODE)
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr


def test_v051_public_api_imports_do_not_write_data(tmp_path):
    result = run_code_in(tmp_path, PUBLIC_API_IMPORT_CODE)
    assert result.returncode == 0, result.stderr
    leftovers = {p.name for p in tmp_path.iterdir()}
    assert "data" not in leftovers
    assert "catalog" not in leftovers
    assert "manifests" not in leftovers
    assert "reports" not in leftovers


def test_v051_dataset_exports_are_public():
    import market_vault.dataset as dataset

    for name in ("orchestrate_dataset_build", "materialize_dataset_artifacts", "load_verified_dataset"):
        assert name in dataset.__all__


# --- Release checker --------------------------------------------------------


def run_check_release(repo: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo / "src")
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / "check_release.py")],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
    )


def test_release_checker_passes_on_current_repo():
    result = run_check_release(ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"RELEASE_CHECK_OK version={EXPECTED_VERSION}" in result.stdout


def test_release_checker_output_is_exactly_release_check_ok_v051():
    result = run_check_release(ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "RELEASE_CHECK_OK version=0.5.1"


def test_release_checker_fails_on_version_mismatch(tmp_path):
    repo = copy_repo(tmp_path)
    pyproject = repo / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    pyproject.write_text(text.replace('version = "0.5.1"', 'version = "9.9.9"'), encoding="utf-8")
    version_file = repo / "src" / "market_vault" / "_version.py"
    version_file.write_text(
        version_file.read_text(encoding="utf-8").replace('"0.5.1"', '"9.9.9"'),
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
        version_file.read_text(encoding="utf-8").replace('"0.5.1"', '"9.9.9"'),
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "CLI --version output" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "final Dataset builder is not implemented" in result.stdout


def test_release_checker_fails_without_changelog(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "CHANGELOG.md").unlink()
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "CHANGELOG.md" in result.stdout


def test_release_checker_fails_without_v05_release_notes(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "docs" / "release_v0_5_0.md").unlink()
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "release_v0_5_0.md" in result.stdout


def test_release_checker_fails_without_v04_release_notes(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "docs" / "release_v0_4_0.md").unlink()
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "release_v0_4_0.md" in result.stdout


def test_release_checker_fails_on_readme_title_mismatch(tmp_path):
    repo = copy_repo(tmp_path)
    readme = repo / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8").replace(
            "# MarketVault v0.5", "# MarketVault v9.9"
        ),
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "README first line" in result.stdout


def test_release_checker_fails_on_old_ci_version_assertion(tmp_path):
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    text = ci.read_text(encoding="utf-8")
    ci.write_text(text.replace("'0.5.1'", "'0.3.0'"), encoding="utf-8")
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
            "assert market_vault.__version__ == '0.5.1'",
            "assert market_vault.__version__ == '9.9.9'",
        ),
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "package module version assertion" in result.stdout
    assert "distribution metadata assertion" not in result.stdout
    assert "old version 0.3.0" not in result.stdout


def test_release_checker_fails_on_wrong_metadata_assertion_only(tmp_path):
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    text = ci.read_text(encoding="utf-8")
    ci.write_text(
        text.replace(
            "assert version('market-vault') == '0.5.1'",
            "assert version('market-vault') == '9.9.9'",
        ),
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "distribution metadata assertion" in result.stdout
    assert "package module version assertion" not in result.stdout
    assert "old version 0.3.0" not in result.stdout


def test_release_checker_fails_on_wrong_public_api_marker(tmp_path):
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    text = ci.read_text(encoding="utf-8")
    ci.write_text(text.replace("V051_PUBLIC_API_IMPORT_OK", "V040_PUBLIC_API_IMPORT_OK"), encoding="utf-8")
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "public API smoke marker" in result.stdout


def test_release_checker_fails_on_tracked_artifact(tmp_path):
    repo = copy_repo(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    tracked = repo / "data" / "tracked.txt"
    tracked.parent.mkdir(parents=True, exist_ok=True)
    tracked.write_text("x", encoding="utf-8")
    # data/ is gitignored; -f is required to make the artifact tracked.
    subprocess.run(["git", "add", "-f", "data/tracked.txt"], cwd=repo, check=True)
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "tracked build artifact" in result.stdout


def test_release_checker_reports_all_failures_at_once(tmp_path):
    repo = copy_repo(tmp_path)
    pyproject = repo / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace('version = "0.5.1"', 'version = "9.9.9"'),
        encoding="utf-8",
    )
    (repo / "CHANGELOG.md").unlink()
    readme = repo / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8").replace(
            "# MarketVault v0.5", "# MarketVault v9.9"
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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "does not state the released fact 'Status: released'" in result.stdout
    assert (
        "still contains the stale wording "
        "'Status: implementation complete; v0.5.0 release preparation'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the released fact '3b4d03c785123e204885faea08df7b9d7ed07ec0'"
    ) in result.stdout


def test_release_checker_fails_when_release_notes_missing_pr29_merged(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_5_0.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("MERGED", "OPEN"),
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "does not state the release fact 'MERGED'" in result.stdout


def test_release_checker_fails_when_release_notes_claim_pr29_still_open(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_5_0.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nGitHub PR #29 is still OPEN and not merged.\n",
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "GitHub PR #29 is still OPEN" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the release fact 'market_vault-0.5.0-py3-none-any.whl'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "does not state the release fact 'market_vault-0.5.0.tar.gz'" in result.stdout


def test_release_checker_fails_without_v051_direction(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "docs" / "v0_5_1_direction.md").unlink()
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "docs/v0_5_1_direction.md is missing" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the fact 'Status: released on 2026-08-06 JST'"
    ) in result.stdout
    assert "still contains the stale wording 'Status: planned'" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the fact 'Status: released on 2026-08-06 JST'"
    ) in result.stdout
    assert (
        "still contains the stale wording "
        "'Status: implementation complete; v0.5.1 release preparation'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the fact 'a978eef291d5e26d20e5cf977bc76609c227cb52'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "does not state the fact '31029709970'" in result.stdout


def test_release_checker_fails_when_release_notes_missing_pr33_merged(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "release_v0_5_1.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("MERGED", "OPEN"),
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "does not state the fact 'MERGED'" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "PR-4 is open and not merged" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the fact "
        "'80965A671AEEF75F315386D9BD4B62EC5DC08E552CB3430AEF92F83C562248C1'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the fact "
        "'FE82FB4FD254C493EC00519EDEB438533C0C5E8D5A7690E1F14AEA39DE4CCDAB'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the fact 'rebuilt from the exact release commit'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 0, result.stdout + result.stderr


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
    result = run_check_release(repo)
    assert result.returncode == 0, result.stdout + result.stderr


def test_release_checker_fails_without_v060_direction(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "docs" / "v0_6_0_direction.md").unlink()
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "docs/v0_6_0_direction.md is missing" in result.stdout


def test_release_checker_fails_when_v060_direction_missing_planned_status(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "Status: planned",
            "Status: released",
        ),
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "does not state the fact 'Status: planned'" in result.stdout


def test_release_checker_fails_when_v060_direction_claims_pr9_started(
    tmp_path,
):
    # PR-8 is the current stage; claiming PR-9 has started in the
    # direction document must fail the checker.
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        .replace("PR-9 not started", "PR-9 has started")
        .replace("PR-9 has not started", "PR-9 has started"),
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "must state that PR-9 has not started"
    ) in result.stdout
    assert (
        "does not state the PR-8 progress fact 'PR-9 not started'"
    ) in result.stdout
    assert "contains the false PR-8 claim 'PR-9 has started'" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "does not state the fact 'not part of v0.6'" in result.stdout


def test_release_checker_fails_when_v060_direction_missing_pr_number(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("PR-5", "PX-5"),
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "does not state the fact 'PR-5'" in result.stdout


def test_release_checker_fails_without_v060_adr(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "docs" / "adr" / "0003-project-boundaries-and-v060-data-discovery.md").unlink()
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "docs/adr/0003-project-boundaries-and-v060-data-discovery.md is missing"
    ) in result.stdout


def test_release_checker_fails_without_sample_generation_contract(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "docs" / "contracts" / "sample_generation.md").unlink()
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "docs/contracts/sample_generation.md is missing" in result.stdout


def test_release_checker_fails_without_dataset_catalog_contract(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "docs" / "contracts" / "dataset_catalog.md").unlink()
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "docs/contracts/dataset_catalog.md is missing" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "false claim 'Sample Generator is implemented'" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "false claim 'Dataset Catalog is implemented'" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the plural input fact "
        "'one or more explicit verified Canonical build directories'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the plural input fact "
        "'one or more explicit Feature spec file paths'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the plural input fact "
        "'one or more explicit Label spec file paths'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "affirmative 'implemented in v0.5.1'" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "stale claim 'available now'" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "false identity claim 'built_at enters Catalog content identity'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "false identity claim "
        "'physical output directory enters Catalog content identity'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the Catalog identity fact "
        "'separate materialization or snapshot identity'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the planned-contract marker 'not implemented in v0.5.1'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the planned-contract marker 'not implemented in v0.5.1'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "does not mark the future capabilities as non-goals" in result.stdout


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


def test_v060_direction_document_exists_and_is_planned():
    text = (ROOT / "docs" / "v0_6_0_direction.md").read_text(encoding="utf-8")
    assert "Status: planned" in text
    assert "Deterministic Sample Generation and Dataset Catalog" in text
    assert "a978eef291d5e26d20e5cf977bc76609c227cb52" in text
    assert "not part of v0.6" in text
    for number in range(1, 10):
        assert f"PR-{number}" in text
    assert "PR-9 not started" in text
    assert "Quant Research" in text
    assert "Trading Execution" in text


def test_v060_direction_records_pr7_merged_and_pr8_stage():
    text = (ROOT / "docs" / "v0_6_0_direction.md").read_text(encoding="utf-8")
    assert "PR #41" in text
    assert "2026-08-07T13:25:52Z" in text
    assert "15ce0ef" in text
    assert "PR-7 COMPLETE" in text
    assert "main verified" in text
    assert "PR-8" in text
    assert "PR-9 not started" in text
    assert "0.5.1" in text
    assert "not released" in text


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
    assert "market-vault 0.5.1" in text


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


def test_ci_contains_051_assertions_and_marker():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "assert market_vault.__version__ == '0.5.1'" in text
    assert "assert version('market-vault') == '0.5.1'" in text
    assert "V051_PUBLIC_API_IMPORT_OK" in text
    assert "compileall -q src tests scripts examples" in text
    assert "render_plans.py --help" in text


def test_release_checker_fails_without_v051_release_notes(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "docs" / "release_v0_5_1.md").unlink()
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "docs/release_v0_5_1.md is missing" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "warning-as-error guard" in result.stdout
    assert "must not ignore DeprecationWarnings" in result.stdout


# --- V0.6.0 Sample Generation contract (PR-2) -------------------------------


def test_release_checker_fails_without_sample_generation_modules(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "src" / "market_vault" / "dataset" / "sample_generation.py").unlink()
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "sample_generation.py is missing" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not define the exact version constant "
        "'market-vault-sample-generation-plan-v1'"
    ) in result.stdout


def test_release_checker_fails_when_rule_schema_version_constant_removed(tmp_path):
    # Mutation 2: deleting the generation-rule schema version constant must
    # fail the checker.
    repo = copy_repo(tmp_path)
    _mutate_models_version(
        repo,
        "market-vault-sample-generation-rule-v1",
        "market-vault-sample-generation-rule-v9",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not define the exact version constant "
        "'market-vault-sample-generation-rule-v1'"
    ) in result.stdout


def test_release_checker_fails_when_content_id_version_constant_removed(tmp_path):
    # Mutation 3: deleting the content-ID version constant must fail the
    # checker.
    repo = copy_repo(tmp_path)
    _mutate_models_version(
        repo,
        "market-vault-sample-generation-content-v1",
        "market-vault-sample-generation-content-v9",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not define the exact version constant "
        "'market-vault-sample-generation-content-v1'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 0, result.stdout + result.stderr


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
    result = run_check_release(repo)
    assert result.returncode == 0, result.stdout + result.stderr


def test_release_checker_fails_without_generator_core_module(tmp_path):
    # Mutation 11: deleting the Sample Generator core module must fail the
    # checker.
    repo = copy_repo(tmp_path)
    (repo / "src" / "market_vault" / "dataset" / "sample_generation_core.py").unlink()
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "sample_generation_core.py is missing" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not define the exact core version constant "
        "'market-vault-sample-generator-core-v1'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "false core claim 'the generator writes the Dataset build plan'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "false core claim 'gaps are skipped'" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "false core claim 'gaps are filled'" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "false core claim 'cross-day windows are allowed'" in result.stdout




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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the plural input fact "
        "'one or more explicit Feature spec file paths'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the plural input fact "
        "'one or more explicit Label spec file paths'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "false claim 'Paths enter the Sample Generation content identity'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "false claim 'built_at enters the Sample Generation content identity'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "false claim 'Generation content ID enters dataset_id'" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the core fact 'explicit absolute path_base'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the core fact 'Overlapping Canonical rows never "
        "become a segment boundary'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the core fact 'Shared Label configuration contract'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the core fact 'recomputes the Generation content ID'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "sample_generation_cli.py is missing" in result.stdout


def test_release_checker_fails_without_sample_generation_output_module(tmp_path):
    # Mutation: deleting the pure renderer module must fail the checker.
    repo = copy_repo(tmp_path)
    (repo / "src" / "market_vault" / "dataset" / "sample_generation_output.py").unlink()
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "sample_generation_output.py is missing" in result.stdout


def test_release_checker_fails_when_cli_contract_version_removed(tmp_path):
    # Mutation: changing the CLI contract version constant must fail the
    # checker.
    repo = copy_repo(tmp_path)
    _mutate_cli_models_version(
        repo,
        "market-vault-sample-generation-cli-v1",
        "market-vault-sample-generation-cli-v9",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not define the exact CLI version constant "
        "'market-vault-sample-generation-cli-v1'"
    ) in result.stdout


def test_release_checker_fails_when_cli_result_schema_version_removed(tmp_path):
    # Mutation: changing the CLI result schema version constant must fail
    # the checker.
    repo = copy_repo(tmp_path)
    _mutate_cli_models_version(
        repo,
        "market-vault-sample-generation-cli-result-v1",
        "market-vault-sample-generation-cli-result-v9",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not define the exact CLI version constant "
        "'market-vault-sample-generation-cli-result-v1'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "does not register sample-generate" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "registers the business option '--output'" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "must never call orchestrate_dataset_build" in result.stdout


def test_release_checker_fails_when_contract_doc_claims_generator_builds_dataset(
    tmp_path,
):
    # Mutation: a contract document claiming the Sample Generator builds the
    # Dataset must fail the checker.
    repo = copy_repo(tmp_path)
    _mutate_contract_doc(repo, "The Sample Generator builds the Dataset.")
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "contains the false PR-4 claim 'Sample Generator builds the Dataset'"
    ) in result.stdout


def test_release_checker_fails_when_contract_doc_claims_cli_builds_dataset(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    _mutate_contract_doc(repo, "the CLI builds the Dataset.")
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "contains the false PR-4 claim 'the CLI builds the Dataset'" in result.stdout


def test_release_checker_fails_when_contract_doc_claims_cli_calls_orchestration(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    _mutate_contract_doc(repo, "the CLI calls orchestrate_dataset_build.")
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "contains the false PR-4 claim 'the CLI calls orchestrate_dataset_build'"
    ) in result.stdout


def test_release_checker_fails_when_contract_doc_claims_cli_implements_catalog(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    _mutate_contract_doc(repo, "the CLI implements Dataset Catalog.")
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "contains the false PR-4 claim 'the CLI implements Dataset Catalog'"
    ) in result.stdout


def test_release_checker_fails_when_contract_doc_claims_output_overwrites(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    _mutate_contract_doc(repo, "The output plan overwrites existing files.")
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "contains the false PR-4 claim 'output plan overwrites existing files'"
    ) in result.stdout


def test_release_checker_fails_when_contract_doc_claims_relative_paths_move(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    _mutate_contract_doc(repo, "relative paths may move to another parent.")
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "contains the false PR-4 claim 'relative paths may move to another parent'"
    ) in result.stdout


def test_release_checker_fails_when_contract_doc_claims_current_time_built_at(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    _mutate_contract_doc(repo, "The current time supplies built_at.")
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "contains the false PR-4 claim 'current time supplies built_at'" in result.stdout


def test_release_checker_fails_when_contract_doc_claims_output_path_enters_identity(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    _mutate_contract_doc(
        repo, "The output_plan_path enters the Generation content identity."
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "contains the false PR-4 claim "
        "'output_plan_path enters the Generation content identity'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the formal v1 contract marker 'Status: Sample "
        "Generation contract, generator core, and CLI implemented'"
    ) in result.stdout
    assert "contains the false PR-4 claim 'CLI not implemented'" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "does not state the PR-4 progress fact 'PR-4 is complete'" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the PR-6 progress fact 'PR-6 is complete'"
    ) in result.stdout


def test_release_checker_fails_when_direction_claims_v060_released(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_direction.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\nV0.6.0 is released.\n",
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "contains the false PR-4 claim 'V0.6.0 is released'" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "fresh-wheel smoke must cover 'market-vault sample-generate --help'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "dataset_catalog_models.py is missing" in result.stdout


def test_release_checker_fails_without_catalog_identity_module(tmp_path):
    # Mutation: deleting the identity module must fail the checker.
    repo = copy_repo(tmp_path)
    (repo / "src" / "market_vault" / "dataset" / "dataset_catalog_identity.py").unlink()
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "dataset_catalog_identity.py is missing" in result.stdout


def test_release_checker_fails_without_catalog_projection_module(tmp_path):
    # Mutation: deleting the projection module must fail the checker.
    repo = copy_repo(tmp_path)
    (repo / "src" / "market_vault" / "dataset" / "dataset_catalog_projection.py").unlink()
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "dataset_catalog_projection.py is missing" in result.stdout


def test_release_checker_fails_when_catalog_contract_version_removed(tmp_path):
    # Mutation: changing the Catalog contract version constant must fail.
    repo = copy_repo(tmp_path)
    _mutate_catalog_models_version(
        repo,
        "market-vault-dataset-catalog-contract-v1",
        "market-vault-dataset-catalog-contract-v9",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not define the exact version constant "
        "'market-vault-dataset-catalog-contract-v1'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not define the exact version constant "
        "'market-vault-dataset-catalog-entry-v1'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not define the exact version constant "
        "'market-vault-dataset-catalog-content-v1'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "dataset_catalog_identity.py is missing def dataset_catalog_content_id" in (
        result.stdout
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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "must bind the trust boundary to VerifiedDatasetBuild" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "must never import the legacy Catalog" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "market_vault.dataset does not export the PR-5 public API "
        "'project_dataset_catalog_entry'"
    ) in result.stdout


def test_release_checker_fails_without_catalog_cli_module(tmp_path):
    # Mutation: removing the PR-7 CLI production module must fail the
    # checker.
    repo = copy_repo(tmp_path)
    (repo / "src" / "market_vault" / "dataset" / "dataset_catalog_cli.py").unlink()
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "src/market_vault/dataset/dataset_catalog_cli.py is missing"
    ) in result.stdout


def test_release_checker_fails_when_contract_trusts_manifest_directly(
    tmp_path,
):
    # Mutation: claiming the Catalog can trust a manifest directly must
    # fail the checker.
    repo = copy_repo(tmp_path)
    _mutate_catalog_contract_doc(
        repo, "The Dataset Catalog trusts manifests directly."
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "contains the false PR-5 claim 'trusts manifests directly'"
    ) in result.stdout


def test_release_checker_fails_when_contract_claims_builder_implemented(
    tmp_path,
):
    # Mutation: claiming the PR-6 builder is already implemented must fail.
    repo = copy_repo(tmp_path)
    _mutate_catalog_contract_doc(repo, "The Dataset Catalog builder is implemented.")
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "contains the false PR-5 claim 'Dataset Catalog builder is implemented'"
    ) in result.stdout


def test_release_checker_fails_when_contract_claims_reader_implemented(
    tmp_path,
):
    # Mutation: claiming the verified Catalog reader is already implemented
    # must fail.
    repo = copy_repo(tmp_path)
    _mutate_catalog_contract_doc(repo, "The verified Catalog reader is implemented.")
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "contains the false PR-5 claim 'verified Catalog reader is implemented'"
    ) in result.stdout


def test_release_checker_fails_when_contract_claims_path_enters_identity(
    tmp_path,
):
    # Mutation: claiming a physical output directory enters the content
    # identity must fail the checker.
    repo = copy_repo(tmp_path)
    _mutate_catalog_contract_doc(
        repo, "physical output directory enters Catalog content identity"
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "contains the false identity claim" in result.stdout


def test_release_checker_fails_when_contract_claims_built_at_enters_identity(
    tmp_path,
):
    # Mutation: claiming built_at enters the content identity must fail.
    repo = copy_repo(tmp_path)
    _mutate_catalog_contract_doc(
        repo, "built_at enters Catalog content identity"
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "contains the false identity claim 'built_at enters Catalog content identity'" in (
        result.stdout
    )


def test_release_checker_fails_when_contract_reuses_legacy_catalog_tables(
    tmp_path,
):
    # Mutation: an affirmative reuse claim must fail (the legitimate
    # "never reuses" wording is preserved in the real document).
    repo = copy_repo(tmp_path)
    _mutate_catalog_contract_doc(repo, "The new Catalog reuses the legacy Catalog's tables.")
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "reuses the legacy Catalog's tables" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the exact facts field 'canonical_row_version_ids'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "does not state the PR-6 progress fact 'PR-6 merged'" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the PR-7 progress fact 'PR-7 merged'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "src/market_vault/dataset/dataset_catalog_cli_models.py is missing"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "dataset_catalog_cli.py does not register dataset-catalog-build"
    ) in result.stdout


def test_release_checker_fails_when_catalog_cli_adds_query_command(
    tmp_path,
):
    # Mutation: adding a fifth dataset-catalog-query command must fail the
    # checker.
    repo = copy_repo(tmp_path)
    _mutate_catalog_cli_append(
        repo, 'subparsers.add_parser("dataset-catalog-query")'
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "must never register a fifth dataset-catalog-query command"
    ) in result.stdout


def test_release_checker_fails_when_catalog_cli_dispatched_after_settings(
    tmp_path,
):
    # Mutation: moving the Dataset Catalog dispatch below load_settings
    # must fail the checker.
    repo = copy_repo(tmp_path)
    _move_catalog_dispatch_after_settings(repo)
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "must dispatch the Dataset Catalog commands before load_settings"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "must not contain the forbidden pattern 'load_verified_dataset('"
    ) in result.stdout


def test_release_checker_fails_when_catalog_cli_reads_catalog_json(
    tmp_path,
):
    # Mutation: the CLI reading the raw catalog.json must fail the checker.
    repo = copy_repo(tmp_path)
    _mutate_catalog_cli_append(repo, 'raw = snapshot_dir / "catalog.json"')
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        'must not contain the forbidden pattern \'"catalog.json"\''
    ) in result.stdout


def test_release_checker_fails_when_catalog_cli_gains_latest(tmp_path):
    repo = copy_repo(tmp_path)
    _mutate_catalog_cli_append(repo, 'parser.add_argument("--latest")')
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "must not contain the forbidden pattern '--latest'"
    ) in result.stdout


def test_release_checker_fails_when_catalog_cli_gains_force(tmp_path):
    repo = copy_repo(tmp_path)
    _mutate_catalog_cli_append(repo, 'parser.add_argument("--force")')
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "must not contain the forbidden pattern '--force'"
    ) in result.stdout


def test_release_checker_fails_when_catalog_cli_gains_overwrite(tmp_path):
    repo = copy_repo(tmp_path)
    _mutate_catalog_cli_append(repo, 'parser.add_argument("--overwrite")')
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "must not contain the forbidden pattern '--overwrite'"
    ) in result.stdout


def test_release_checker_fails_when_catalog_cli_loads_settings(tmp_path):
    repo = copy_repo(tmp_path)
    _mutate_catalog_cli_append(repo, "settings = load_settings(args.settings)")
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "must not contain the forbidden pattern 'load_settings('"
    ) in result.stdout


def test_release_checker_fails_when_catalog_cli_references_legacy_storage(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    _mutate_catalog_cli_append(
        repo, "legacy = market_vault.storage.catalog.Catalog"
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "must not contain the forbidden pattern 'storage.catalog'"
    ) in result.stdout


def test_release_checker_fails_when_catalog_cli_uses_duckdb(tmp_path):
    repo = copy_repo(tmp_path)
    _mutate_catalog_cli_append(repo, "import duckdb")
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "must not contain the forbidden pattern 'duckdb'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the PR-7 fact 'AND semantics'"
    ) in result.stdout


def test_release_checker_fails_when_contract_doc_claims_pr8_started(
    tmp_path,
):
    # Mutation: claiming PR-8 has started in the contract document must
    # fail the checker (the "PR-8 has not started" fact disappears).
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "contracts" / "dataset_catalog.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR-8 has not started",
            "PR-8 has started",
        ),
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the PR-7 fact 'PR-8 has not started'"
    ) in result.stdout


def test_release_checker_fails_when_contract_doc_claims_repairs(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    _mutate_catalog_contract_doc(repo, "The CLI repairs the snapshot.")
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "contains the false PR-7 claim 'repairs the snapshot'"
    ) in result.stdout


def test_release_checker_fails_when_contract_doc_gains_latest_pointer(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    _mutate_catalog_contract_doc(repo, "The CLI maintains a latest pointer.")
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "contains the false PR-7 claim 'maintains a latest pointer'"
    ) in result.stdout


def test_release_checker_fails_when_ci_loses_pr7_smoke(tmp_path):
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8").replace(
            "PR7_CATALOG_CLI_HELP_OK", "PR7_MISSING_MARKER"
        ),
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "PR-7 CLI help smoke marker" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "must cover 'market-vault dataset-catalog-show --help'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "is missing the independent-review hardening marker "
        "'set(canonical_row_version_ids) - covered'"
    ) in result.stdout


def test_release_checker_fails_when_specpin_business_key_drifts(tmp_path):
    # Mutation: content_sha256 joining the SpecPin duplicate business key
    # must fail the checker.
    repo = copy_repo(tmp_path)
    _mutate_catalog_models_marker(
        repo,
        "key = (pin.kind, pin.name, pin.version)",
        "key = (pin.kind, pin.name, pin.version, pin.content_sha256)",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "is missing the independent-review hardening marker "
        "'key = (pin.kind, pin.name, pin.version)'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "is missing the independent-review hardening marker "
        "'reject_unsafe_text(text, label)'"
    ) in result.stdout


def test_release_checker_fails_when_location_binding_lost(tmp_path):
    # Mutation: dropping the build_path basename binding must fail.
    repo = copy_repo(tmp_path)
    _mutate_catalog_models_marker(
        repo,
        "!= self.dataset_facts.dataset_id",
        "== self.dataset_facts.dataset_id",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "is missing the independent-review hardening marker "
        "'!= self.dataset_facts.dataset_id'"
    ) in result.stdout


def test_release_checker_fails_when_contract_claims_metadata_enters_identity(
    tmp_path,
):
    # Mutation: a document claim that metadata enters the content identity
    # must fail (the legitimate wording never claims this).
    repo = copy_repo(tmp_path)
    _mutate_catalog_contract_doc(
        repo, "built_at enters Catalog content identity"
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "contains the false identity claim" in result.stdout


# --- V0.6.0 Dataset Catalog snapshot layer (PR-6) ----------------------------


def _mutate_catalog_builder(repo: Path, old: str, new: str) -> None:
    path = repo / "src" / "market_vault" / "dataset" / "dataset_catalog_builder.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8"
    )


def test_release_checker_fails_without_pr6_builder_module(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "src" / "market_vault" / "dataset" / "dataset_catalog_builder.py").unlink()
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "dataset_catalog_builder.py is missing" in result.stdout


def test_release_checker_fails_without_pr6_reader_module(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "src" / "market_vault" / "dataset" / "dataset_catalog_reader.py").unlink()
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "dataset_catalog_reader.py is missing" in result.stdout


def test_release_checker_fails_without_pr6_materializer_module(tmp_path):
    repo = copy_repo(tmp_path)
    (
        repo
        / "src"
        / "market_vault"
        / "dataset"
        / "dataset_catalog_materialization.py"
    ).unlink()
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "dataset_catalog_materialization.py is missing" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not define the exact builder version constant "
        "'market-vault-dataset-catalog-builder-v1'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not define the exact version constant "
        "'market-vault-dataset-catalog-snapshot-id-v1'"
    ) in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not define the exact version constant "
        "'market-vault-verified-dataset-catalog-reader-v1'"
    ) in result.stdout


def test_release_checker_fails_when_builder_trusts_manifest_directly(
    tmp_path,
):
    repo = copy_repo(tmp_path)
    _mutate_catalog_builder(
        repo,
        "verified = load_verified_dataset(candidate)",
        "verified = _parse_manifest(candidate)",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "missing the contract marker 'load_verified_dataset(candidate)'" in (
        result.stdout
    )


def test_release_checker_fails_when_builder_skips_verified_reader(tmp_path):
    repo = copy_repo(tmp_path)
    _mutate_catalog_builder(
        repo,
        "project_dataset_catalog_entry(verified)",
        "project_dataset_catalog_entry(None)",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "missing the contract marker 'project_dataset_catalog_entry(verified)'"
    ) in result.stdout


def test_release_checker_fails_when_root_scan_becomes_recursive(tmp_path):
    repo = copy_repo(tmp_path)
    _mutate_catalog_builder(
        repo,
        "with os.scandir(dataset_root) as iterator:",
        "for entry in dataset_root.rglob('*'):",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "must not contain the forbidden pattern 'rglob'" in result.stdout
    assert "missing the contract marker 'os.scandir(dataset_root)'" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "must not contain the forbidden pattern 'Path.cwd()'" in result.stdout


def test_release_checker_fails_when_content_identity_includes_path(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "src" / "market_vault" / "dataset" / "dataset_catalog_identity.py"
    path.write_text(
        path.read_text(encoding="utf-8") + '\n    "build_path": facts.build_path,\n',
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "must not contain the forbidden pattern '\"build_path\":'" in (
        result.stdout
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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "must not contain the forbidden pattern '\"built_at\":'" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "must not contain the forbidden pattern '\"output_root\"'" in (
        result.stdout
    )


def test_release_checker_fails_when_reader_reloads_recorded_paths(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "src" / "market_vault" / "dataset" / "dataset_catalog_reader.py"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nload_verified_dataset(entry.recorded_build_path)\n",
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "must not contain the forbidden pattern 'load_verified_dataset('" in (
        result.stdout
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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "missing the contract marker 'historical observed location'" in (
        result.stdout
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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "must write _SUCCESS before the atomic publication" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "must not contain the forbidden pattern 'os.replace('" in result.stdout
    assert "missing the contract marker '_atomic_rename_directory_no_replace(" in (
        result.stdout
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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "must not contain the forbidden pattern '\"latest\"'" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "missing the contract marker 'type(written) is not int" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "market_vault.dataset does not export the PR-6 public API "
        "'build_dataset_catalog'"
    ) in result.stdout


def test_release_checker_fails_when_ci_loses_pr6_smoke(tmp_path):
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8").replace(
            "PR6_CATALOG_API_IMPORT_OK", "PR6_MISSING_MARKER"
        ),
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "PR-6 public API smoke marker" in result.stdout


# --- V0.6.0 integrated acceptance (PR-8) ------------------------------------


def test_release_checker_fails_without_acceptance_doc(tmp_path):
    # Mutation: the acceptance document must exist.
    repo = copy_repo(tmp_path)
    (repo / "docs" / "v0_6_0_acceptance.md").unlink()
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "docs/v0_6_0_acceptance.md is missing" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "false claim 'v0.6.0 is released'" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "does not state the fact 'PyArrow 25.0.0'" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "false claim 'byte-identical across writers'" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "false claim 'physical_snapshot_hash is not part of'" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "must record the frozen generation content id" in result.stdout


def test_release_checker_fails_when_acceptance_doc_claims_pr9_started(tmp_path):
    repo = copy_repo(tmp_path)
    path = repo / "docs" / "v0_6_0_acceptance.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\nPR-9 has started.\n",
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "false claim 'PR-9 has started'" in result.stdout


def test_release_checker_fails_without_acceptance_helpers(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "tests" / "v060_acceptance_helpers.py").unlink()
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "tests/v060_acceptance_helpers.py is missing" in result.stdout


def test_release_checker_fails_without_fixture_bundle(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "tests" / "fixtures" / "v060_portability" / "canonical_fixture.b64").unlink()
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "canonical_fixture.b64 is missing" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "the frozen FIXTURE_GENERATION_ID must not change" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "the frozen FROZEN_RELATIVE_PLAN_SHA256 must not change" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "must keep the pyarrow>=16 dependency" in result.stdout
    assert "must never pin a PyArrow writer version" in result.stdout


def test_release_checker_fails_when_ci_matrix_changes(tmp_path):
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8").replace(
            '["3.11", "3.14"]', '["3.11", "3.13", "3.14"]'
        ),
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "CI python matrix must stay exactly" in result.stdout


def test_release_checker_fails_without_portability_job(tmp_path):
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8").replace(
            "portability-pyarrow24", "portability-pyarrow25"
        ),
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "portability-pyarrow24 job" in result.stdout


def test_release_checker_fails_when_portability_job_unpinned(tmp_path):
    # Mutation: the portability job installing a non-pinned pyarrow must
    # fail the checker.
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8").replace(
            'pip install "pyarrow==24.0.0"',
            'pip install "pyarrow>=24.0.0"',
        ),
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "must install pyarrow==24.0.0" in result.stdout


def test_release_checker_fails_when_ci_loses_acceptance_marker(tmp_path):
    repo = copy_repo(tmp_path)
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8").replace(
            "PR8_INTEGRATED_ACCEPTANCE_OK", "PR8_MISSING_MARKER"
        ),
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "PR8_INTEGRATED_ACCEPTANCE_OK" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 0, result.stdout + result.stderr


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "does not state the fact 'upstream source / curated'" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "does not state the fact 'Canonical output Parquet'" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "does not state the fact 'exactly empty'" in result.stdout


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
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "false claim 'every supported PyArrow writer'" in result.stdout


def test_release_checker_fails_when_portability_job_loses_full_suite_step(
    tmp_path,
):
    # Mutation: removing the PyArrow 24 full offline suite step must fail
    # the checker.
    repo = copy_repo(tmp_path)
    path = repo / ".github" / "workflows" / "ci.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "Run full offline suite under PyArrow 24.0.0",
            "Run full offline suite",
        ),
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "must include the full offline suite step" in result.stdout


def test_release_checker_fails_when_portability_full_suite_step_loses_pytest(
    tmp_path,
):
    # Mutation: the PyArrow 24 full offline suite step must run the plain
    # `python -m pytest` (the whole suite, not a subset).
    repo = copy_repo(tmp_path)
    path = repo / ".github" / "workflows" / "ci.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "Run full offline suite under PyArrow 24.0.0\n"
            "        run: python -m pytest\n",
            "Run full offline suite under PyArrow 24.0.0\n"
            "        run: python -m pytest tests/test_v060_portability.py -q\n",
        ),
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "full-suite step must run python -m pytest" in result.stdout
