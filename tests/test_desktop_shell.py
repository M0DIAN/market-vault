from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication

from market_vault.desktop.dashboard import DashboardController
from market_vault.desktop.controllers import (
    AuditController,
    HistoricalDataController,
    InventoryController,
    MarketDataController,
    RunsController,
    TradingCalendarController,
)
from market_vault.desktop.localization import I18nBridge
from market_vault.desktop.preferences import DesktopPreferenceStore
from market_vault.desktop.runtime import DesktopOperationRuntime
from market_vault.desktop.shell import PAGE_IDS, ShellController
from market_vault.desktop.storage_cleanup import StorageCleanupController


ROOT = Path(__file__).resolve().parents[1]
DESKTOP_ROOT = ROOT / "src" / "market_vault" / "desktop"
EXPECTED_PAGE_IDS = (
    "home",
    "historical_data",
    "trading_calendar",
    "market_data",
    "inventory",
    "coverage_audit",
    "intraday_audit",
    "runs",
    "storage_cleanup",
)


@pytest.fixture(scope="module")
def qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


def test_shell_exposes_exact_stable_page_identities(qt_app):
    shell = ShellController()

    assert PAGE_IDS == EXPECTED_PAGE_IDS
    assert tuple(page["id"] for page in shell.pages) == EXPECTED_PAGE_IDS
    assert shell.currentPage == "home"
    assert shell.currentPageLabelKey == "nav.home"
    assert shell.currentPageIndex == 0


def test_selects_every_page_and_unknown_page_fails_closed(qt_app):
    shell = ShellController()
    changes = []
    shell.currentPageChanged.connect(lambda: changes.append(shell.currentPage))

    for expected_index, page_id in enumerate(EXPECTED_PAGE_IDS):
        assert shell.selectPage(page_id) is True
        assert shell.currentPageIndex == expected_index
    assert changes == list(EXPECTED_PAGE_IDS[1:])

    previous = shell.currentPage
    assert shell.selectPage("unknown") is False
    assert shell.currentPage == previous
    assert changes == list(EXPECTED_PAGE_IDS[1:])


def test_language_and_navigation_do_not_initialize_dashboard_backend(qt_app, tmp_path):
    backend_calls = []
    runner_calls = []
    dashboard = DashboardController(
        settings_path=(tmp_path / "settings.yaml").resolve(),
        backend_factory=lambda path: backend_calls.append(path),
        runner_factory=lambda: runner_calls.append(True),
    )
    shell = ShellController()
    i18n = I18nBridge(
        preference_store=DesktopPreferenceStore(root=tmp_path / "preferences")
    )
    model = dashboard.recentRunsModel

    assert shell.selectPage("inventory") is True
    assert i18n.setLanguage("zh-CN") is True
    assert shell.currentPage == "inventory"
    assert i18n.setLanguage("en") is True
    assert dashboard.recentRunsModel is model
    assert backend_calls == []
    assert runner_calls == []
    dashboard.shutdown()


def test_componentized_qml_navigation_localization_and_model_identity(tmp_path):
    script = f"""
import json
from PySide6.QtCore import QObject, QUrl
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
app.processEvents()
sidebar = root.findChild(QObject, 'sidebar')
switcher = root.findChild(QObject, 'languageSwitcher')
title = root.findChild(QObject, 'pageTitle')
content = root.findChild(QObject, 'pageContent')
home_before = root.findChild(QObject, 'homePage')
table_before = root.findChild(QObject, 'recentRunsTable')
model = dashboard.recentRunsModel
model.set_page(TablePage(columns=('run_id', 'status'), rows=(('run-1', 'SUCCESS'),), total_rows=1))
app.processEvents()
shell.selectPage('inventory')
app.processEvents()
inventory_title_en = title.property('text')
i18n.setLanguage('zh-CN')
app.processEvents()
inventory_title_zh = title.property('text')
current_after_language = shell.currentPage
i18n.setLanguage('en')
shell.selectPage('home')
app.processEvents()
home_after = root.findChild(QObject, 'homePage')
table_after = root.findChild(QObject, 'recentRunsTable')
market_code = root.findChild(QObject, 'marketDataCode')
market_code.setProperty('text', 'US.QQQ')
shell.selectPage('market_data')
shell.selectPage('runs')
shell.selectPage('market_data')
app.processEvents()
market_code_after = root.findChild(QObject, 'marketDataCode').property('text')
storage_execute = root.findChild(QObject, 'storageExecuteButton')
table_connections = {{
    'calendar': root.findChild(QObject, 'calendarTable').property('tableModel') == calendar.tableModel,
    'market': root.findChild(QObject, 'marketDataTable').property('tableModel') == market_data.tableModel,
    'inventory': root.findChild(QObject, 'inventoryTable').property('tableModel') == inventory.tableModel,
    'coverage': root.findChild(QObject, 'coverageAuditTable').property('tableModel') == coverage.tableModel,
    'intraday': root.findChild(QObject, 'intradayAuditTable').property('tableModel') == intraday.tableModel,
    'runs': root.findChild(QObject, 'runsTable').property('tableModel') == runs.tableModel,
    'backfill': root.findChild(QObject, 'backfillPlanTable').property('tableModel') == historical.tableModel,
    'storage': root.findChild(QObject, 'storageReviewTable').property('tableModel') == storage.tableModel,
}}
page_names = {{page_id: root.findChild(QObject, object_name) is not None for page_id, object_name in {{
    'home': 'homePage', 'historical_data': 'historicalDataPage',
    'trading_calendar': 'tradingCalendarPage', 'market_data': 'marketDataPage',
    'inventory': 'inventoryPage', 'coverage_audit': 'coverageAuditPage',
    'intraday_audit': 'intradayAuditPage', 'runs': 'runsPage',
    'storage_cleanup': 'storageCleanupPage'
}}.items()}}
print(json.dumps({{
    'root': root is not None,
    'sidebar': sidebar is not None,
    'switcher': switcher is not None,
    'content': content is not None,
    'home_initial': home_before is not None,
    'inventory_title_en': inventory_title_en,
    'inventory_title_zh': inventory_title_zh,
    'page_names': page_names,
    'placeholder_absent': root.findChild(QObject, 'placeholderMessage') is None,
    'current_after_language': current_after_language,
    'home_returned': home_after is not None,
    'same_model': dashboard.recentRunsModel is model,
    'table_model_connected': table_after.property('tableModel') == model,
    'rows_preserved': model.rowCount(),
    'table_available_before': table_before is not None,
    'market_code_preserved': market_code_after,
    'storage_execute_disabled': not bool(storage_execute.property('enabled')),
    'table_connections': table_connections,
}}))
runtime.shutdown()
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QSG_RHI_BACKEND"] = "software"
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
        "root": True,
        "sidebar": True,
        "switcher": True,
        "content": True,
        "home_initial": True,
        "inventory_title_en": "Inventory",
        "inventory_title_zh": "数据库存",
        "page_names": {page_id: True for page_id in EXPECTED_PAGE_IDS},
        "placeholder_absent": True,
        "current_after_language": "inventory",
        "home_returned": True,
        "same_model": True,
        "table_model_connected": True,
        "rows_preserved": 1,
        "table_available_before": True,
        "market_code_preserved": "US.QQQ",
        "storage_execute_disabled": True,
        "table_connections": {
            "calendar": True,
            "market": True,
            "inventory": True,
            "coverage": True,
            "intraday": True,
            "runs": True,
            "backfill": True,
            "storage": True,
        },
    }
