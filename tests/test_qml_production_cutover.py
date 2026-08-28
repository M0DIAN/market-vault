from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_SPEC = ROOT / "packaging" / "MarketVault.spec"
PRODUCTION_BUILD = ROOT / "scripts" / "build_windows_desktop.ps1"
PRODUCTION_LAUNCHER = ROOT / "src" / "market_vault" / "windows_launcher.py"
QML_ROOT = ROOT / "src" / "market_vault" / "desktop" / "qml"
FONT = (
    ROOT
    / "src"
    / "market_vault"
    / "desktop"
    / "assets"
    / "fonts"
    / "fusion-pixel-12px-proportional-zh_hans-v2026.07.20"
    / "fusion-pixel-12px-proportional-zh_hans.otf"
)


def _quoted_qml_names(text: str) -> set[str]:
    return set(re.findall(r'"([^"/]+\.qml)"', text))


def test_production_spec_has_exact_qml_asset_inventory() -> None:
    production = PRODUCTION_SPEC.read_text(encoding="utf-8")

    expected_qml = {path.name for path in QML_ROOT.rglob("*.qml")}
    assert _quoted_qml_names(production) == expected_qml
    assert len(expected_qml) == 35
    for asset in (
        "qmldir",
        "fusion-pixel-12px-proportional-zh_hans.otf",
        "NOTICE.md",
        "OFL.txt",
    ):
        assert production.count(f'"{asset}"') >= 1
    for runtime_import in (
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickControls2",
        "market_vault.application",
        "market_vault.api",
        "market_vault.console.backend",
        "market_vault.console.tasks",
        "market_vault.desktop.bootstrap",
        "duckdb",
        "pandas",
        "pyarrow",
        "pyarrow.parquet",
        "yaml",
    ):
        assert f'"{runtime_import}"' in production
    assert "collect_all" not in production
    assert 'hookspath=[str(HOOKS_ROOT)]' in production


def test_production_identity_and_tk_exclusions_are_explicit() -> None:
    production = PRODUCTION_SPEC.read_text(encoding="utf-8")
    launcher = PRODUCTION_LAUNCHER.read_text(encoding="utf-8")

    assert 'ENTRY_POINT = SOURCE_ROOT / "market_vault" / "windows_launcher.py"' in production
    assert production.count('name="MarketVault"') == 2
    for excluded in ("_tkinter", "tkinter", "market_vault.console.ui"):
        assert f'"{excluded}"' in production
    for excluded in (
        "PySide6.QtWidgets",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtWebEngineWidgets",
    ):
        assert f'"{excluded}"' in production
    assert "market_vault.desktop.app" in launcher
    assert "run_application" in launcher
    assert "run_console" not in launcher
    assert not (ROOT / "packaging" / "MarketVaultQmlCanary.spec").exists()
    assert not (ROOT / "scripts" / "build_windows_qml_canary.ps1").exists()


def test_production_build_audits_qml_identity_laziness_and_tk_absence() -> None:
    script = PRODUCTION_BUILD.read_text(encoding="utf-8")

    for evidence in (
        'desktop_ui = "pyside6-qml"',
        'application_context = "shared-lazy"',
        'packaging_mode = "pyinstaller-onedir"',
        "pyside6_version = $PySideVersion",
        "qt_version = $QtVersion",
        "pyinstaller_version = $PyInstallerVersion",
        '"--smoke-exit-ms", "500"',
        '"--dashboard-smoke"',
        "startup_runtime_mutation = $false",
        "Tk runtime content entered the production QML bundle",
        "Tk UI modules entered the production executable archive",
        "Required production QML assets are missing",
        "Bundled Fusion Pixel hash mismatch",
        "Unapproved QtWidgets/WebEngine content entered the production bundle",
    ):
        assert evidence in script
    assert "$OriginalPath = $env:PATH" in script
    assert "$env:PATH = $OriginalPath" in script
    assert "$OriginalLocalAppData = $env:LOCALAPPDATA" in script
    assert "$env:LOCALAPPDATA = $OriginalLocalAppData" in script
    assert "Remove-Item" not in script


def test_production_launcher_import_remains_business_lazy(tmp_path: Path) -> None:
    script = """
import json
import sys
import market_vault.windows_launcher
blocked = sorted(name for name in sys.modules if name in {
    'market_vault.api',
    'market_vault.console.backend',
    'market_vault.service',
    'market_vault.storage.catalog',
})
print(json.dumps(blocked))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"
    assert list(tmp_path.iterdir()) == []


def test_production_bundle_font_is_the_approved_fusion_pixel_asset() -> None:
    assert hashlib.sha256(FONT.read_bytes()).hexdigest() == (
        "9955f9e20abd758316418a2942aa6ee773754060da4a3f9286581fd11312f6c3"
    )
    assert (FONT.parent / "NOTICE.md").is_file()
    assert (FONT.parent / "OFL.txt").is_file()
