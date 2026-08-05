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
            "Status: implementation complete; v0.5.1 release preparation",
            "Status: planned",
        ),
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert (
        "does not state the fact "
        "'Status: implementation complete; v0.5.1 release preparation'"
    ) in result.stdout
    assert "still contains the stale wording 'Status: planned'" in result.stdout


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


# --- V0.5.1 release preparation facts ---------------------------------------


def test_direction_document_is_release_preparation():
    text = (ROOT / "docs" / "v0_5_1_direction.md").read_text(encoding="utf-8")
    assert "Status: implementation complete; v0.5.1 release preparation" in text
    assert "Status: planned" not in text
    assert "Status: proposed" not in text
    assert "have not started" in text


def test_release_notes_v051_contain_pr_facts():
    text = (ROOT / "docs" / "release_v0_5_1.md").read_text(encoding="utf-8")
    assert "PR #30" in text
    assert "PR #31" in text
    assert "PR #32" in text
    assert "8de57d497ae5d922e3df29d9475f14b9407865f0" in text
    assert "2d9c8a539f04ee2d75e5482c858ec6c3364af135" in text
    assert "240f7ccac89a773366a510f10a13d6de801051ea" in text
    assert "3b4d03c785123e204885faea08df7b9d7ed07ec0" in text


def test_release_notes_v051_contain_expected_artifacts():
    text = (ROOT / "docs" / "release_v0_5_1.md").read_text(encoding="utf-8")
    assert "market_vault-0.5.1-py3-none-any.whl" in text
    assert "market_vault-0.5.1.tar.gz" in text
    assert "PyPI" in text
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
