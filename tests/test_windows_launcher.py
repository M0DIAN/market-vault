from __future__ import annotations

import os
from pathlib import Path

import pytest

from market_vault import windows_launcher
from market_vault.desktop import app


def test_source_mode_default_settings_remains_relative() -> None:
    assert windows_launcher.resolve_settings_path(frozen=False) == Path("config/settings.yaml")


def test_frozen_application_root_uses_executable_directory(tmp_path: Path) -> None:
    executable = tmp_path / "MarketVault" / "MarketVault.exe"
    assert windows_launcher.application_root(
        frozen=True, executable=str(executable)
    ) == executable.resolve().parent


def test_frozen_default_settings_is_external_to_executable(tmp_path: Path) -> None:
    executable = tmp_path / "MarketVault" / "MarketVault.exe"
    assert windows_launcher.resolve_settings_path(
        frozen=True, executable=str(executable)
    ) == executable.resolve().parent / "config" / "settings.yaml"


def test_frozen_default_settings_is_independent_of_cwd(tmp_path: Path) -> None:
    executable = tmp_path / "MarketVault" / "MarketVault.exe"
    first_cwd = tmp_path / "one"
    second_cwd = tmp_path / "two"
    first_cwd.mkdir()
    second_cwd.mkdir()
    original = Path.cwd()
    try:
        os.chdir(first_cwd)
        first = windows_launcher.resolve_settings_path(frozen=True, executable=str(executable))
        os.chdir(second_cwd)
        second = windows_launcher.resolve_settings_path(frozen=True, executable=str(executable))
    finally:
        os.chdir(original)
    assert first == second == executable.resolve().parent / "config" / "settings.yaml"


@pytest.mark.parametrize("explicit", ["custom/settings.yaml", "config/alternate.yaml"])
def test_frozen_relative_override_resolves_from_executable(
    tmp_path: Path, explicit: str
) -> None:
    executable = tmp_path / "MarketVault" / "MarketVault.exe"
    assert windows_launcher.resolve_settings_path(
        explicit,
        frozen=True,
        executable=str(executable),
    ) == executable.resolve().parent / explicit


def test_absolute_override_is_preserved(tmp_path: Path) -> None:
    settings = (tmp_path / "settings.yaml").resolve()
    assert windows_launcher.resolve_settings_path(
        str(settings), frozen=True, executable=str(tmp_path / "MarketVault.exe")
    ) == settings


def test_source_application_root_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="only for frozen"):
        windows_launcher.application_root(frozen=False)


def test_production_launcher_delegates_to_qml_runtime(monkeypatch, tmp_path) -> None:
    settings = (tmp_path / "settings.yaml").resolve()
    calls = []

    def fake_run_application(**kwargs):
        calls.append(kwargs)
        return 17

    monkeypatch.setattr(app, "run_application", fake_run_application)

    result = windows_launcher.main(
        [
            "--settings",
            str(settings),
            "--smoke-exit-ms",
            "250",
        ]
    )

    assert result == 17
    assert calls == [
        {
            "smoke_exit_ms": 250,
            "settings_path": settings,
            "dashboard_smoke": False,
            "dashboard_smoke_timeout_ms": 30_000,
            "dashboard_smoke_require_recent_runs": False,
        }
    ]


def test_production_launcher_preserves_dashboard_smoke_arguments(
    monkeypatch, tmp_path
) -> None:
    settings = (tmp_path / "settings.yaml").resolve()
    calls = []
    monkeypatch.setattr(
        app,
        "run_application",
        lambda **kwargs: calls.append(kwargs) or 0,
    )

    assert windows_launcher.main(
        [
            "--settings",
            str(settings),
            "--dashboard-smoke",
            "--dashboard-smoke-timeout-ms",
            "45000",
            "--dashboard-smoke-require-recent-runs",
        ]
    ) == 0
    assert calls[0]["dashboard_smoke"] is True
    assert calls[0]["dashboard_smoke_timeout_ms"] == 45_000
    assert calls[0]["dashboard_smoke_require_recent_runs"] is True


def test_production_help_hides_internal_smoke_flags() -> None:
    help_text = windows_launcher.build_parser().format_help()

    assert "--settings" in help_text
    assert "--smoke-exit-ms" not in help_text
    assert "--dashboard-smoke" not in help_text


def test_frozen_qml_startup_failure_uses_existing_error_boundary(
    monkeypatch, tmp_path
) -> None:
    settings = (tmp_path / "settings.yaml").resolve()
    messages = []

    def fail(**_kwargs):
        raise RuntimeError("qml failed")

    monkeypatch.setattr(app, "run_application", fail)
    monkeypatch.setattr(windows_launcher, "is_frozen", lambda: True)
    monkeypatch.setattr(windows_launcher, "_show_frozen_error", messages.append)

    assert windows_launcher.main(["--settings", str(settings)]) == 1
    assert len(messages) == 1
    assert "RuntimeError: qml failed" in messages[0]
    assert f"Settings: {settings}" in messages[0]


def test_source_qml_startup_failure_does_not_fall_back_to_tk(
    monkeypatch, tmp_path
) -> None:
    settings = (tmp_path / "settings.yaml").resolve()
    monkeypatch.setattr(
        app,
        "run_application",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("qml failed")),
    )
    monkeypatch.setattr(windows_launcher, "is_frozen", lambda: False)

    with pytest.raises(RuntimeError, match="qml failed"):
        windows_launcher.main(["--settings", str(settings)])


def test_build_definition_is_onedir_and_external_config() -> None:
    root = Path(__file__).resolve().parents[1]
    spec = (root / "packaging" / "MarketVault.spec").read_text(encoding="utf-8")
    build_script = (root / "scripts" / "build_windows_desktop.ps1").read_text(
        encoding="utf-8"
    )
    assert "COLLECT(" in spec
    assert "PROJECT_ROOT = Path(SPECPATH).resolve().parent" in spec
    assert 'name="MarketVault"' in spec
    assert "console=False" in spec
    assert '"market_vault.console.ui"' in spec
    assert '"tkinter"' in spec
    assert '"_tkinter"' in spec
    assert '"PySide6.QtQml"' in spec
    assert 'hookspath=[str(HOOKS_ROOT)]' in spec
    assert "config/settings.yaml" not in spec
    assert 'startswith("pyarrow/tests/")' in spec
    assert '("moomoo.examples", "moomoo.tools")' in spec
    assert "Copy-Item -LiteralPath $ConfigTemplate" in build_script
    assert "Refusing to overwrite an existing distributable" in build_script
    assert "Remove-Item" not in build_script
    assert 'desktop_ui = "pyside6-qml"' in build_script
    assert 'application_context = "shared-lazy"' in build_script
    assert "Tk runtime content entered the production QML bundle" in build_script
