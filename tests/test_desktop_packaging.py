from __future__ import annotations

import ast
import json
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


def test_qml_settings_resolution_is_cwd_independent_in_source_and_frozen_modes(
    tmp_path,
):
    relative = Path("config/settings.yaml")
    args = app.build_parser().parse_args(["--settings", str(relative)])
    assert args.settings == str(relative)
    assert app.resolve_desktop_settings_path() == ROOT / relative
    assert app.resolve_desktop_settings_path(
        str(relative),
        frozen=True,
        executable=str(tmp_path / "bundle" / "MarketVault.exe"),
    ) == (tmp_path / "bundle" / relative).resolve()

    with pytest.raises(SystemExit):
        app.main(["--dashboard-smoke-require-recent-runs"])
    with pytest.raises(SystemExit):
        app.main(
            [
                "--settings",
                str(tmp_path / "settings.yaml"),
                "--dashboard-smoke",
                "--smoke-exit-ms",
                "100",
            ]
        )


@pytest.mark.parametrize("value", ["0", "-1", "120001", "not-an-integer"])
def test_dashboard_smoke_timeout_rejects_invalid_values(value):
    with pytest.raises(SystemExit):
        app.build_parser().parse_args(["--dashboard-smoke-timeout-ms", value])


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


def test_production_startup_source_has_no_eager_business_imports():
    imported = set()
    for path in (
        DESKTOP_ROOT / "app.py",
        DESKTOP_ROOT / "bridge.py",
        DESKTOP_ROOT / "controllers.py",
        DESKTOP_ROOT / "dashboard.py",
        DESKTOP_ROOT / "localization.py",
        DESKTOP_ROOT / "preferences.py",
        DESKTOP_ROOT / "runtime.py",
        DESKTOP_ROOT / "shell.py",
        DESKTOP_ROOT / "storage_cleanup.py",
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        top_level = tree.body
        for node in top_level:
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    assert imported.isdisjoint(BUSINESS_MODULES)


def test_componentized_qml_exercises_dashboard_controller_and_generic_table():
    qml_root = DESKTOP_ROOT / "qml"
    main = (qml_root / "Main.qml").read_text(encoding="utf-8")
    home = (qml_root / "pages" / "HomePage.qml").read_text(encoding="utf-8")
    sidebar = (qml_root / "components" / "Sidebar.qml").read_text(encoding="utf-8")
    switcher = (qml_root / "components" / "LanguageSwitcher.qml").read_text(
        encoding="utf-8"
    )
    data_table = (qml_root / "components" / "DataTable.qml").read_text(
        encoding="utf-8"
    )
    assert "import QtQuick\n" in main
    assert 'import "components" as Components' in main
    assert 'import "pages" as Pages' in main
    assert "Pages.HomePage" in main
    assert "StackLayout" in main
    assert "if (!operationRuntime.requestShutdown())" in main
    assert "close.accepted = false" in main
    assert "Pages.PlaceholderPage" not in main
    assert not (qml_root / "pages" / "PlaceholderPage.qml").exists()
    for page in (
        "HistoricalDataPage",
        "TradingCalendarPage",
        "MarketDataPage",
        "InventoryPage",
        "AuditPage",
        "RunsPage",
        "StorageCleanupPage",
    ):
        assert f"Pages.{page}" in main
    assert "dashboardController.refresh()" not in main
    assert "home.desktop.ping()" in home
    assert "text: home.desktop.status" in home
    assert "home.dashboard.refresh()" in home
    assert "home.dashboard.backendConfigured && !home.dashboard.busy" in home
    for metric in (
        "Symbols",
        "Snapshots",
        "Latest rows",
        "Completed dates",
        "Incomplete dates",
        "Latest trade date",
    ):
        assert f'"{metric}"' in home
    assert "dashboardController.recent_runs" not in main + home
    assert "home.dashboard.recent_runs" not in home
    assert "Components.DataTable" in home
    assert "HorizontalHeaderView" in data_table
    assert "TableView" in data_table
    assert 'objectName: "recentRunsTable"' in home
    assert 'objectName: root.objectName + "Header"' in data_table
    assert 'objectName: root.objectName + "EmptyState"' in data_table
    assert "home.dashboard.recentRunsModel" in home
    assert "ApplicationWindow" in main
    assert "shell.selectPage(modelData.id)" in sidebar
    assert "i18n.setLanguage(currentValue)" in switcher
    assert "later migration phase" not in main + home + data_table
    for forbidden in (
        "ConsoleBackend",
        "Catalog",
        "Safe Purge",
        "Backfill",
        "AmbientNumericField",
        "market_vault.service",
        "market_vault.storage",
    ):
        assert forbidden not in main + home + sidebar + switcher + data_table


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


def test_qml_loads_table_objects_and_tracks_empty_state(tmp_path):
    pytest.importorskip("PySide6")
    script = f"""
import json
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from market_vault.console.models import TablePage
from market_vault.desktop.bridge import DesktopBridge
from market_vault.desktop.dashboard import DashboardController
from market_vault.desktop.controllers import AuditController, HistoricalDataController, InventoryController, MarketDataController, RunsController, TradingCalendarController
from market_vault.desktop.localization import I18nBridge
from market_vault.desktop.preferences import DesktopPreferenceStore
from market_vault.desktop.runtime import DesktopOperationRuntime
from market_vault.desktop.shell import ShellController
from market_vault.desktop.storage_cleanup import StorageCleanupController

QQuickStyle.setStyle('Basic')
app = QGuiApplication([])
engine = QQmlApplicationEngine()
bridge = DesktopBridge(parent=engine)
runtime = DesktopOperationRuntime(parent=engine)
dashboard = DashboardController(runtime=runtime, parent=engine)
historical = HistoricalDataController(runtime, parent=engine)
calendar = TradingCalendarController(runtime, parent=engine)
market_data = MarketDataController(runtime, parent=engine)
inventory = InventoryController(runtime, parent=engine)
coverage = AuditController(runtime, method_name='coverage_audit', parent=engine)
intraday = AuditController(runtime, method_name='intraday_audit', parent=engine)
runs = RunsController(runtime, parent=engine)
storage = StorageCleanupController(runtime, parent=engine)
i18n = I18nBridge(preference_store=DesktopPreferenceStore(root={str(tmp_path / 'preferences')!r}), parent=engine)
shell = ShellController(parent=engine)
engine.rootContext().setContextProperty('desktopBridge', bridge)
engine.rootContext().setContextProperty('operationRuntime', runtime)
engine.rootContext().setContextProperty('dashboardController', dashboard)
engine.rootContext().setContextProperty('historicalDataController', historical)
engine.rootContext().setContextProperty('tradingCalendarController', calendar)
engine.rootContext().setContextProperty('marketDataController', market_data)
engine.rootContext().setContextProperty('inventoryController', inventory)
engine.rootContext().setContextProperty('coverageAuditController', coverage)
engine.rootContext().setContextProperty('intradayAuditController', intraday)
engine.rootContext().setContextProperty('runsController', runs)
engine.rootContext().setContextProperty('storageCleanupController', storage)
engine.rootContext().setContextProperty('i18nBridge', i18n)
engine.rootContext().setContextProperty('shellController', shell)
engine.load(QUrl.fromLocalFile({str(DESKTOP_ROOT / 'qml' / 'Main.qml')!r}))
root = engine.rootObjects()[0]
table = root.findChild(object, 'recentRunsTable')
header = root.findChild(object, 'recentRunsTableHeader')
empty = root.findChild(object, 'recentRunsTableEmptyState')
app.processEvents()
empty_before = bool(empty.property('visible'))
model = dashboard.recentRunsModel
model.set_page(TablePage(
    columns=('run_id', 'status'),
    rows=(('qml-run-1', 'SUCCESS'),),
    total_rows=1,
))
app.processEvents()
print(json.dumps({{
    'table': table is not None,
    'header': header is not None,
    'empty': empty is not None,
    'model_connected': table.property('tableModel') == model,
    'empty_before': empty_before,
    'empty_after': bool(empty.property('visible')),
    'rows': model.rowCount(),
    'columns': model.columnCount(),
}}))
runtime.shutdown()
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QSG_RHI_BACKEND"] = "software"
    env["LOCALAPPDATA"] = str(tmp_path / "local app data")
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout.strip())
    assert evidence == {
        "table": True,
        "header": True,
        "empty": True,
        "model_connected": True,
        "empty_before": True,
        "empty_after": False,
        "rows": 1,
        "columns": 2,
    }


def test_source_smoke_is_cwd_independent_and_side_effect_free(tmp_path):
    pytest.importorskip("PySide6")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QSG_RHI_BACKEND"] = "software"
    env["LOCALAPPDATA"] = str(tmp_path / "local app data")
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
    assert not list(tmp_path.rglob("desktop-preferences.json"))


def test_source_startup_with_settings_remains_lazy_and_side_effect_free(tmp_path):
    pytest.importorskip("PySide6")
    settings = (tmp_path / "sandbox" / "config" / "settings.yaml").resolve()
    settings.parent.mkdir(parents=True)
    settings.write_text(
        """
storage:
  root_dir: ./data
  catalog_path: ./catalog/market_vault.duckdb
  manifest_dir: ./manifests
  report_dir: ./reports/data_quality
""".lstrip(),
        encoding="utf-8",
    )
    cwd = tmp_path / "unrelated cwd"
    cwd.mkdir()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QSG_RHI_BACKEND"] = "software"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "market_vault.desktop.app",
            "--settings",
            str(settings),
            "--smoke-exit-ms",
            "100",
        ],
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert settings.is_file()
    assert not (settings.parent.parent / "catalog" / "market_vault.duckdb").exists()
    assert list(cwd.iterdir()) == []
    assert not list(tmp_path.rglob("desktop-preferences.json"))


def test_production_packaging_retains_complete_qml_runtime_contract():
    production_spec = (ROOT / "packaging" / "MarketVault.spec").read_text(
        encoding="utf-8"
    )
    production_build = (
        ROOT / "scripts" / "build_windows_desktop.ps1"
    ).read_text(encoding="utf-8")
    production_launcher = (
        ROOT / "src" / "market_vault" / "windows_launcher.py"
    ).read_text(encoding="utf-8")
    qml_launcher = (DESKTOP_ROOT / "app.py").read_text(encoding="utf-8")
    production_hook = (
        ROOT / "packaging" / "hooks" / "hook-PySide6.QtQml.py"
    ).read_text(encoding="utf-8")

    assert 'name="MarketVault"' in production_spec
    assert "MarketVaultQmlCanary" not in production_spec + production_build
    assert "market_vault.desktop.app" in production_launcher
    assert "run_application" in production_launcher
    assert "market_vault.console.ui" not in production_launcher
    assert "market_vault.windows_launcher" not in qml_launcher
    for component in (
        "DataTable.qml",
        "LanguageSwitcher.qml",
        "OpenDConfirmDialog.qml",
        "SaveExportDialog.qml",
        "Sidebar.qml",
    ):
        assert f'"{component}"' in production_spec
    for page in (
        "AuditPage.qml",
        "HistoricalDataPage.qml",
        "HomePage.qml",
        "InventoryPage.qml",
        "MarketDataPage.qml",
        "RunsPage.qml",
        "StorageCleanupPage.qml",
        "TradingCalendarPage.qml",
    ):
        assert f'"{page}"' in production_spec
    assert "PlaceholderPage.qml" not in production_spec
    assert '"market_vault/desktop/qml/components"' in production_spec
    assert '"market_vault/desktop/qml/pages"' in production_spec
    assert "collect_all" not in production_spec
    assert 'hookspath=[str(HOOKS_ROOT)]' in production_spec
    assert "collect_qtqml_files" not in production_hook
    assert '"QtQuick/Controls/Basic"' in production_hook
    assert '"QtQuick/Dialogs"' in production_hook
    assert '"QtQuick/Dialogs/quickimpl"' in production_hook
    assert '("QtQuick", "Controls", "designer")' in production_hook
    for unneeded_style in ("Fusion", "Imagine", "Material", "Universal"):
        assert f'"QtQuick/Controls/{unneeded_style}"' not in production_hook
    assert "$OriginalPath = $env:PATH" in production_build
    assert "$env:PATH = $OriginalPath" in production_build
    assert "build_path_sanitized = $true" in production_build
    for packaged in (
        '"market_vault.application"',
        '"market_vault.api"',
        '"market_vault.console.backend"',
        '"market_vault.console.tasks"',
        '"market_vault.desktop.bootstrap"',
        '"market_vault.desktop.windows_chrome"',
        '"duckdb"',
        '"pandas"',
        '"pyarrow"',
        '"yaml"',
    ):
        assert packaged in production_spec
    assert '$ConfigTemplate = Join-Path $ProjectRoot "config\\settings.yaml"' in production_build
    assert 'Copy-Item -LiteralPath $ConfigTemplate' in production_build
    assert 'application_context = "shared-lazy"' in production_build
    assert 'collect_submodules(' in production_spec
    assert 'collect_data_files("moomoo"' in production_spec
    assert "$DashboardSmokeSettings" in production_build
    assert "$DashboardSmokeRequireRecentRuns" in production_build
    assert '"--dashboard-smoke"' in production_build
    assert '"--dashboard-smoke-require-recent-runs"' in production_build


def test_pyproject_keeps_qt_optional_and_packages_production_qml():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'desktop = [\n  "PySide6==6.11.2",\n]' in text
    assert (
        'windows-exe = [\n  "pyinstaller==6.22.2",\n'
        '  "PySide6==6.11.2",\n]'
    ) in text
    core_dependencies = text.split("[project.optional-dependencies]", 1)[0]
    assert "PySide6" not in core_dependencies
    assert '"qml/*.qml"' in text
    assert '"qml/components/*.qml"' in text
    assert '"qml/pages/*.qml"' in text
