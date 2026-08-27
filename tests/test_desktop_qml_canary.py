from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys

import pytest

from market_vault.desktop import app


ROOT = Path(__file__).resolve().parents[1]
DESKTOP_ROOT = ROOT / "src" / "market_vault" / "desktop"
BUSINESS_MODULES = {
    "market_vault.console.backend",
    "market_vault.service",
    "market_vault.storage.catalog",
}
RUNTIME_NAMES = {
    "catalog",
    "data",
    "manifests",
    "reports",
    "quarantine",
}


def test_qml_resolver_source_mode_is_cwd_independent(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    resolved = app.resolve_qml_path()

    assert resolved == DESKTOP_ROOT / "qml" / "Main.qml"
    assert resolved.is_file()
    assert tmp_path not in resolved.parents


def test_qml_resolver_frozen_mode_is_cwd_independent(monkeypatch, tmp_path):
    bundle_root = tmp_path / "bundle root"
    unrelated = tmp_path / "unrelated cwd"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_root), raising=False)

    assert app.resolve_qml_path() == (
        bundle_root / "market_vault" / "desktop" / "qml" / "Main.qml"
    )


@pytest.mark.parametrize("value", ["0", "-1", "60001", "not-an-integer"])
def test_smoke_exit_argument_rejects_invalid_values(value):
    with pytest.raises(SystemExit):
        app.build_parser().parse_args(["--smoke-exit-ms", value])


@pytest.mark.parametrize("value", ["1", "500", "60000"])
def test_smoke_exit_argument_accepts_bounded_values(value):
    assert app.build_parser().parse_args(["--smoke-exit-ms", value]).smoke_exit_ms == int(
        value
    )


def test_desktop_import_does_not_eagerly_initialize_business_modules(tmp_path):
    script = """
import json
import sys
import market_vault.desktop
import market_vault.desktop.app
blocked = sorted(name for name in sys.modules if name in {
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


def test_canary_startup_source_has_no_business_imports():
    imported = set()
    for path in (DESKTOP_ROOT / "app.py", DESKTOP_ROOT / "bridge.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    assert imported.isdisjoint(BUSINESS_MODULES)


def test_main_qml_is_minimal_and_exercises_bridge():
    qml = (DESKTOP_ROOT / "qml" / "Main.qml").read_text(encoding="utf-8")
    assert "import QtQuick\n" in qml
    assert "import QtQuick.Controls\n" in qml
    assert "import QtQuick.Layouts\n" in qml
    assert "desktopBridge.ping()" in qml
    assert "text: desktopBridge.status" in qml
    assert "ApplicationWindow" in qml
    for forbidden in (
        "ConsoleBackend",
        "Catalog",
        "Safe Purge",
        "Backfill",
        "AmbientNumericField",
        "market_vault.service",
        "market_vault.storage",
    ):
        assert forbidden not in qml


def test_bridge_property_signal_and_slot_round_trip():
    pytest.importorskip("PySide6")
    from market_vault.desktop.bridge import DesktopBridge

    bridge = DesktopBridge()
    notifications = []
    bridge.statusChanged.connect(lambda: notifications.append(bridge.status))

    assert bridge.status == "QML ready"
    bridge.ping()
    assert bridge.status == "Python bridge OK"
    assert notifications == ["Python bridge OK"]


def test_source_smoke_is_cwd_independent_and_side_effect_free(tmp_path):
    pytest.importorskip("PySide6")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QSG_RHI_BACKEND"] = "software"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "market_vault.desktop.app",
            "--smoke-exit-ms",
            "100",
        ],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert not (RUNTIME_NAMES & {path.name for path in tmp_path.iterdir()})
    assert not list(tmp_path.rglob("*.duckdb"))
    assert not list(tmp_path.rglob("*.parquet"))


def test_parallel_spec_and_build_script_do_not_cut_over_production():
    production_spec = (ROOT / "packaging" / "MarketVault.spec").read_text(
        encoding="utf-8"
    )
    production_build = (ROOT / "scripts" / "build_windows_console.ps1").read_text(
        encoding="utf-8"
    )
    production_launcher = (
        ROOT / "src" / "market_vault" / "windows_launcher.py"
    ).read_text(encoding="utf-8")
    canary_spec = (ROOT / "packaging" / "MarketVaultQmlCanary.spec").read_text(
        encoding="utf-8"
    )
    canary_build = (
        ROOT / "scripts" / "build_windows_qml_canary.ps1"
    ).read_text(encoding="utf-8")
    canary_hook = (
        ROOT / "packaging" / "hooks" / "hook-PySide6.QtQml.py"
    ).read_text(encoding="utf-8")

    assert 'name="MarketVault"' in production_spec
    assert "MarketVaultQmlCanary" not in production_spec
    assert "MarketVaultQmlCanary" not in production_build
    assert "market_vault.desktop" not in production_launcher
    assert 'name="MarketVaultQmlCanary"' in canary_spec
    assert "MarketVaultQmlCanary.exe" in canary_build
    assert "collect_all" not in canary_spec
    assert 'hookspath=[str(HOOKS_ROOT)]' in canary_spec
    assert "collect_qtqml_files" not in canary_hook
    assert '"QtQuick/Controls/Basic"' in canary_hook
    assert '("QtQuick", "Controls", "designer")' in canary_hook
    assert "$BundledForbiddenQml.Count -gt 0" in canary_build
    for unneeded_style in ("Fusion", "Imagine", "Material", "Universal"):
        assert f'"QtQuick/Controls/{unneeded_style}"' not in canary_hook
    assert "$OriginalPath = $env:PATH" in canary_build
    assert "$env:PATH = $OriginalPath" in canary_build
    assert "build_path_sanitized = $true" in canary_build
    for excluded in (
        '"market_vault.api"',
        '"market_vault.artifact_client"',
        '"duckdb"',
        '"pandas"',
        '"pyarrow"',
    ):
        assert excluded in canary_spec


def test_pyproject_keeps_qt_optional_and_packages_only_canary_qml():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'desktop = [\n  "PySide6==6.11.2",\n]' in text
    core_dependencies = text.split("[project.optional-dependencies]", 1)[0]
    assert "PySide6" not in core_dependencies
    assert '"market_vault.desktop" = ["qml/*.qml"]' in text
