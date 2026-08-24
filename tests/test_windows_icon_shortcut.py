from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from market_vault import windows_launcher


ROOT = Path(__file__).resolve().parents[1]
PNG_SHA256 = "2319f14f6acae05e3ae02ba3d5cd258ee1f0f8194103a9a031173141ddb3f616"
ICO_SHA256 = "010f4f7ce5108bc6bdbbe710f470da8319775951571e910dc26a85e708dfa068"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_approved_windows_icon_assets_are_exact() -> None:
    png = ROOT / "assets" / "windows" / "market-vault-icon.png"
    ico = ROOT / "assets" / "windows" / "market-vault.ico"
    assert png.is_file()
    assert ico.is_file()
    assert _sha256(png) == PNG_SHA256
    assert _sha256(ico) == ICO_SHA256


def test_pyinstaller_uses_approved_icon_without_changing_onedir_mode() -> None:
    spec = (ROOT / "packaging" / "MarketVault.spec").read_text(encoding="utf-8")
    assert 'WINDOWS_ICON = PROJECT_ROOT / "assets" / "windows" / "market-vault.ico"' in spec
    assert '[(str(WINDOWS_ICON), "assets/windows")]' in spec
    assert "icon=str(WINDOWS_ICON)" in spec
    assert "COLLECT(" in spec
    assert "console=False" in spec


def test_frozen_window_icon_resolution_is_cwd_independent(tmp_path: Path) -> None:
    runtime_root = tmp_path / "bundle" / "_internal"
    first_cwd = tmp_path / "first"
    second_cwd = tmp_path / "second"
    first_cwd.mkdir()
    second_cwd.mkdir()
    original = Path.cwd()
    try:
        os.chdir(first_cwd)
        first = windows_launcher.resolve_window_icon_path(
            frozen=True, runtime_root=runtime_root
        )
        os.chdir(second_cwd)
        second = windows_launcher.resolve_window_icon_path(
            frozen=True, runtime_root=runtime_root
        )
    finally:
        os.chdir(original)
    expected = runtime_root.resolve() / "assets" / "windows" / "market-vault.ico"
    assert first == second == expected


def test_source_window_icon_resolution_uses_repository_root() -> None:
    assert windows_launcher.resolve_window_icon_path(frozen=False) == (
        ROOT / "assets" / "windows" / "market-vault.ico"
    ).resolve()


def test_configure_window_icon_calls_tk_with_exact_approved_path(tmp_path: Path) -> None:
    icon = tmp_path / "assets" / "windows" / "market-vault.ico"
    icon.parent.mkdir(parents=True)
    icon.write_bytes(b"ico")

    class FakeRoot:
        def __init__(self) -> None:
            self.default: str | None = None

        def iconbitmap(self, *, default: str) -> None:
            self.default = default

    root = FakeRoot()
    assert windows_launcher.configure_window_icon(
        root, frozen=True, runtime_root=tmp_path
    ) == icon.resolve()
    assert root.default == str(icon.resolve())


def test_source_mode_missing_window_icon_is_safe(tmp_path: Path) -> None:
    class FakeRoot:
        def iconbitmap(self, *, default: str) -> None:
            raise AssertionError(f"unexpected icon call: {default}")

    assert windows_launcher.configure_window_icon(
        FakeRoot(), frozen=False, source_root=tmp_path
    ) is None


def test_frozen_mode_missing_window_icon_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="window icon not found"):
        windows_launcher.configure_window_icon(
            object(), frozen=True, runtime_root=tmp_path
        )


def test_shortcut_script_is_no_overwrite_and_desktop_is_api_resolved() -> None:
    script = (ROOT / "scripts" / "install_windows_shortcut.ps1").read_text(
        encoding="utf-8"
    )
    assert "WScript.Shell" in script
    assert "[Environment]::GetFolderPath" in script
    assert 'IconLocation = "$ResolvedExe,0"' in script
    assert 'Description = "MarketVault Console"' in script
    assert "Refusing to overwrite an existing shortcut" in script
    assert "C:\\Users\\Administrator\\Desktop" not in script
    assert "Remove-Item" not in script


def _powershell() -> str | None:
    return shutil.which("powershell") or shutil.which("pwsh")


def _run_shortcut_script(
    exe: Path, shortcut: Path, *, use_app_root: bool = False
) -> subprocess.CompletedProcess[str]:
    powershell = _powershell()
    assert powershell is not None
    target_arguments = (
        ["-AppRoot", str(exe.parent)] if use_app_root else ["-ExePath", str(exe)]
    )
    return subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "install_windows_shortcut.ps1"),
            *target_arguments,
            "-ShortcutPath",
            str(shortcut),
        ],
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows WScript.Shell is required")
def test_shortcut_metadata_is_exact_and_existing_file_is_refused(tmp_path: Path) -> None:
    app_root = tmp_path / "MarketVault App"
    app_root.mkdir()
    exe = app_root / "MarketVault.exe"
    exe.write_bytes(b"MZ")
    shortcut = tmp_path / "MarketVault.lnk"

    created = _run_shortcut_script(exe, shortcut, use_app_root=True)
    assert created.returncode == 0, created.stderr
    evidence = json.loads(next(line for line in created.stdout.splitlines() if line.startswith("{")))
    assert Path(evidence["shortcut_path"]) == shortcut.resolve()
    assert Path(evidence["target_path"]) == exe.resolve()
    assert Path(evidence["working_directory"]) == app_root.resolve()
    assert evidence["icon_location"] == f"{exe.resolve()},0"
    assert evidence["description"] == "MarketVault Console"
    assert "MARKET_VAULT_SHORTCUT_OK" in created.stdout

    original = shortcut.read_bytes()
    refused = _run_shortcut_script(exe, shortcut, use_app_root=True)
    assert refused.returncode != 0
    assert "Refusing to overwrite an existing shortcut" in refused.stderr
    assert shortcut.read_bytes() == original


@pytest.mark.skipif(os.name != "nt", reason="Windows WScript.Shell is required")
def test_shortcut_script_refuses_missing_executable(tmp_path: Path) -> None:
    shortcut = tmp_path / "MarketVault.lnk"
    result = _run_shortcut_script(tmp_path / "missing" / "MarketVault.exe", shortcut)
    assert result.returncode != 0
    assert "MarketVault.exe does not exist" in result.stderr
    assert not shortcut.exists()
