from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

from market_vault.application import (
    LOGGER_NAME,
    build_application_context,
    configure_application_logging,
)
from market_vault.console.backend import ConsoleBackend


def _write_settings(root: Path) -> Path:
    config = root / "config" / "settings.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(
        """
opend:
  host: 127.0.0.1
  port: 11111
storage:
  root_dir: ./data
  catalog_path: ./catalog/market_vault.duckdb
  manifest_dir: ./manifests
  report_dir: ./reports/data_quality
collector:
  source: moomoo
  source_schema_version: '10.9'
""".lstrip(),
        encoding="utf-8",
    )
    return config


class _Runner:
    def __init__(self) -> None:
        self.close_count = 0

    def close(self) -> None:
        self.close_count += 1


def test_application_context_constructs_one_dependency_graph_and_closes_once(tmp_path):
    settings_path = tmp_path / "deep path" / "settings.yaml"
    settings = SimpleNamespace(name="settings")
    runner = _Runner()
    seen = []

    context = build_application_context(
        settings_path,
        settings_loader=lambda path: seen.append(("settings", path)) or settings,
        backend_factory=lambda value: seen.append(("backend", value)) or object(),
        runner_factory=lambda: seen.append(("runner", None)) or runner,
        logging_factory=lambda: logging.getLogger("market-vault-test"),
    )

    assert context.settings_path == settings_path.resolve()
    assert context.settings is settings
    assert seen == [
        ("settings", settings_path.resolve()),
        ("backend", settings),
        ("runner", None),
    ]
    assert context.closed is False
    context.shutdown()
    context.shutdown()
    assert context.closed is True
    assert runner.close_count == 1


def test_production_context_uses_existing_backend_without_runtime_mutation(tmp_path):
    sandbox = tmp_path / "bootstrap sandbox"
    settings_path = _write_settings(sandbox)

    context = build_application_context(settings_path)
    try:
        assert isinstance(context.backend, ConsoleBackend)
        assert context.backend.vault.settings is context.settings
        assert context.settings_path == settings_path.resolve()
        assert context.backend.vault.catalog.settings is context.settings
        assert not (sandbox / "catalog" / "market_vault.duckdb").exists()
        assert not list(sandbox.rglob("*.parquet"))
    finally:
        context.shutdown()


def test_application_logging_is_initialized_without_file_handler():
    logger = configure_application_logging()

    assert logger.name == LOGGER_NAME
    assert logger.level == logging.INFO
    assert not any(isinstance(handler, logging.FileHandler) for handler in logger.handlers)


def test_tk_console_consumes_the_shared_application_context():
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "market_vault"
        / "console"
        / "ui.py"
    ).read_text(encoding="utf-8")

    assert "context = build_application_context(settings_path)" in source
    assert "context.backend" in source
    assert "task_runner=context.task_runner" in source
    assert "shutdown_callback=context.shutdown" in source
