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
EXPECTED_VERSION = "0.3.0"
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


def test_readme_title_is_v03():
    first_line = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()[0]
    assert first_line.strip() == "# MarketVault v0.3"


def test_readme_no_development_wording():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "V0.3 development" not in text
    assert "V0.3 remains under development" not in text


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


def test_changelog_contains_030():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [0.3.0] - 2026-08-04" in text


def test_release_notes_contain_real_validation():
    text = (ROOT / "docs" / "release_v0_3_0.md").read_text(encoding="utf-8")
    assert "1440" in text
    assert "1201" in text


def test_upgrade_notes_contain_legacy_compatibility():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Upgrade from v0.2" in text
    assert "batch-<batch_key>.parquet" in text


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


def test_release_checker_fails_on_version_mismatch(tmp_path):
    repo = copy_repo(tmp_path)
    pyproject = repo / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    pyproject.write_text(text.replace('version = "0.3.0"', 'version = "9.9.9"'), encoding="utf-8")
    version_file = repo / "src" / "market_vault" / "_version.py"
    version_file.write_text(
        version_file.read_text(encoding="utf-8").replace('"0.3.0"', '"9.9.9"'),
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "pyproject.toml version" in result.stdout
    assert "package __version__" in result.stdout


def test_release_checker_fails_on_development_wording(tmp_path):
    repo = copy_repo(tmp_path)
    readme = repo / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8") + "\nV0.3 development leftover\n",
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "V0.3 development" in result.stdout


def test_release_checker_fails_without_changelog(tmp_path):
    repo = copy_repo(tmp_path)
    (repo / "CHANGELOG.md").unlink()
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "CHANGELOG.md" in result.stdout


def test_release_checker_reports_all_failures_at_once(tmp_path):
    repo = copy_repo(tmp_path)
    pyproject = repo / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace('version = "0.3.0"', 'version = "9.9.9"'),
        encoding="utf-8",
    )
    (repo / "CHANGELOG.md").unlink()
    readme = repo / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8").replace(
            "# MarketVault v0.3", "# MarketVault v9.9"
        ),
        encoding="utf-8",
    )
    result = run_check_release(repo)
    assert result.returncode == 1
    assert "pyproject.toml version" in result.stdout
    assert "CHANGELOG.md" in result.stdout
    assert "README first line" in result.stdout


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
