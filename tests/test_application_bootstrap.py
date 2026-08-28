from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

from market_vault.application import (
    LOGGER_NAME,
    build_application_context,
    configure_application_logging,
    resolve_application_settings_path,
)


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


def test_application_context_constructs_dependencies_lazily_and_closes_once(tmp_path):
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
    assert seen == [("settings", settings_path.resolve())]
    assert context.backend_if_initialized is None
    assert context.task_runner_if_initialized is None

    backend = context.get_backend()
    assert context.get_backend() is backend
    assert context.get_task_runner() is runner
    assert context.get_task_runner() is runner
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


def test_ui_neutral_settings_resolver_handles_source_and_frozen_paths(tmp_path):
    source_default = tmp_path / "source" / "config" / "settings.yaml"
    executable = tmp_path / "bundle" / "MarketVault.exe"

    assert resolve_application_settings_path(
        source_default=source_default
    ) == source_default.resolve()
    assert resolve_application_settings_path(
        "custom/settings.yaml",
        frozen=True,
        executable=str(executable),
    ) == (executable.parent / "custom" / "settings.yaml").resolve()
    assert resolve_application_settings_path(
        frozen=True,
        executable=str(executable),
    ) == (executable.parent / "config" / "settings.yaml").resolve()


def test_production_context_construction_is_filesystem_side_effect_free_and_lazy(
    tmp_path,
):
    sandbox = tmp_path / "bootstrap sandbox"
    settings_path = _write_settings(sandbox)

    context = build_application_context(settings_path)
    try:
        assert context.settings_path == settings_path.resolve()
        assert context.backend_if_initialized is None
        assert context.task_runner_if_initialized is None
        assert not (sandbox / "data").exists()
        assert not (sandbox / "catalog").exists()
        assert not (sandbox / "manifests").exists()
        assert not (sandbox / "reports").exists()
        assert not list(sandbox.rglob("*.parquet"))
    finally:
        context.shutdown()

    assert context.backend_if_initialized is None
    assert context.task_runner_if_initialized is None


def test_uninitialized_context_shutdown_does_not_construct_dependencies(tmp_path):
    calls = []
    context = build_application_context(
        tmp_path / "settings.yaml",
        settings_loader=lambda path: object(),
        backend_factory=lambda settings: calls.append("backend"),
        runner_factory=lambda: calls.append("runner"),
    )

    context.shutdown()
    context.shutdown()

    assert context.closed is True
    assert calls == []


def test_application_logging_is_initialized_without_file_handler():
    logger = configure_application_logging()

    assert logger.name == LOGGER_NAME
    assert logger.level == logging.INFO
    assert not any(isinstance(handler, logging.FileHandler) for handler in logger.handlers)


def test_production_desktop_consumes_the_shared_application_context():
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "market_vault"
        / "desktop"
        / "app.py"
    ).read_text(encoding="utf-8")

    assert "context = build_application_context(resolved_settings)" in source
    assert "create_qml_application_session(context, engine)" in source
    assert "application.aboutToQuit.connect(session.shutdown)" in source
    assert "session.shutdown()" in source
