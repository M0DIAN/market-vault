from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src" / "market_vault"


def test_legacy_presentation_and_canary_are_retired_but_adapters_remain() -> None:
    absent = (
        SOURCE_ROOT / "console" / "__main__.py",
        SOURCE_ROOT / "console" / "ui.py",
        SOURCE_ROOT / "console" / "i18n.py",
        SOURCE_ROOT / "console" / "preferences.py",
        SOURCE_ROOT / "console" / "shell.py",
        ROOT / "packaging" / "MarketVaultQmlCanary.spec",
        ROOT / "scripts" / "build_windows_qml_canary.ps1",
        ROOT / "scripts" / "build_windows_console.ps1",
    )
    assert all(not path.exists() for path in absent)

    retained = (
        SOURCE_ROOT / "console" / "backend.py",
        SOURCE_ROOT / "console" / "models.py",
        SOURCE_ROOT / "console" / "tasks.py",
        ROOT / "packaging" / "MarketVault.spec",
        ROOT / "scripts" / "build_windows_desktop.ps1",
    )
    assert all(path.is_file() for path in retained)


def test_importing_console_package_is_business_and_gui_lazy(tmp_path: Path) -> None:
    probe = """
import json
import sys
import market_vault.console
blocked_roots = ('PySide6', 'duckdb', 'futu', 'moomoo', 'tkinter')
blocked = sorted(
    name for name in sys.modules
    if name == 'market_vault.api'
    or any(name == root or name.startswith(root + '.') for root in blocked_roots)
)
print(json.dumps(blocked))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []
    assert list(tmp_path.iterdir()) == []


def test_console_public_adapter_exports_remain_available() -> None:
    from market_vault.console import (
        ConsoleBackend,
        DashboardSnapshot,
        ExportResult,
        PurgePlanView,
        TablePage,
    )

    assert ConsoleBackend.__module__ == "market_vault.console.backend"
    assert {
        DashboardSnapshot.__name__,
        ExportResult.__name__,
        PurgePlanView.__name__,
        TablePage.__name__,
    } == {"DashboardSnapshot", "ExportResult", "PurgePlanView", "TablePage"}


def test_active_production_source_has_no_tkinter_imports() -> None:
    findings: list[str] = []
    for path in SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            if any(name == "tkinter" or name.startswith("tkinter.") for name in names):
                findings.append(str(path.relative_to(ROOT)))
    assert findings == []


def test_safe_purge_governance_names_only_production_qml_presentation() -> None:
    contract = (
        ROOT / "docs" / "governance" / "destructive_operations" / "safe_purge_v01.json"
    ).read_text(encoding="utf-8")

    assert "Legacy Tk" not in contract
    assert "Future QML" not in contract
    assert "future QML" not in contract
    assert "Production PySide6/QML" in contract
    assert "Production QML" in contract
