from __future__ import annotations

import os
from pathlib import Path

import pytest

from market_vault import windows_launcher


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


def test_build_definition_is_onedir_and_external_config() -> None:
    root = Path(__file__).resolve().parents[1]
    spec = (root / "packaging" / "MarketVault.spec").read_text(encoding="utf-8")
    build_script = (root / "scripts" / "build_windows_console.ps1").read_text(
        encoding="utf-8"
    )
    assert "COLLECT(" in spec
    assert "PROJECT_ROOT = Path(SPECPATH).resolve().parent" in spec
    assert 'name="MarketVault"' in spec
    assert "console=False" in spec
    assert "config/settings.yaml" not in spec
    assert 'startswith("pyarrow/tests/")' in spec
    assert '("moomoo.examples", "moomoo.tools")' in spec
    assert "Copy-Item -LiteralPath $ConfigTemplate" in build_script
    assert "Refusing to overwrite an existing distributable" in build_script
    assert "Remove-Item" not in build_script
