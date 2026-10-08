"""Actual intraday source verification and Qt workspace interaction."""

from datetime import date
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytest.importorskip("PySide6")

from market_vault.desktop.quant_research import QuantResearchController
from market_vault.research.intraday_data import build_intraday_dataset, write_intraday_dataset
from test_intraday_data import input_plan
from test_desktop_quant_research import _runtime, qt_app  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def test_inspect_pages_all_observations_and_preserves_last_success(qt_app, tmp_path):
    data = build_intraday_dataset(input_plan(tmp_path, interval="1m"))
    path = write_intraday_dataset(data, path=tmp_path / "intraday.json")
    calls = []
    runtime, runner = _runtime(tmp_path, calls)
    controller = QuantResearchController(runtime)
    assert controller.inspectIntraday(str(path))
    runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    assert controller.intradaySummary["intraday_observations"] == "386"
    assert controller.intradayLoaded and not controller.datasetLoaded
    assert controller.intradayModel.totalRows == 386
    assert controller.intradayModel.rowCount() == 100
    assert controller.changeIntradayPage(3)
    assert controller.intradayModel.rowCount() == 86
    assert controller._intraday_rows[-1][0].endswith("21:00:00+00:00")
    assert not controller.changeIntradayPage(1)
    assert controller.inspectIntraday(str(tmp_path / "missing.json"))
    runtime._poll()
    assert controller.status != "SUCCESS"
    assert controller.intradayPath == str(path) and controller._intraday_data == data.content
    assert controller.intradayModel.page == 4
    assert not calls and runtime.backend_if_initialized is None
    assert runtime.shutdown()


def test_qml_real_local_build_reopen_and_form_defaults(tmp_path):
    from test_research_workspace import _settings, _write_real_calendar, _write_real_ts2_day
    from market_vault.research_workspace import research_ready_settings
    cfg = _settings(tmp_path)
    days = [date(2026, 1, 5), date(2026, 1, 6)]
    _write_real_calendar(cfg, days)
    for ordinal, day in enumerate(days):
        _write_real_ts2_day(research_ready_settings(cfg), day, ordinal=ordinal)
    (tmp_path / "settings.yaml").write_text("storage:\n  root_dir: ./data\n", encoding="utf-8")
    script = r'''
import sys
from pathlib import Path
from PySide6.QtCore import QObject, QMetaObject, QUrl, Qt, QEvent
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from market_vault.api import MarketVault
from market_vault.application import build_application_context
from market_vault.console.backend import ConsoleBackend
from market_vault.desktop.bootstrap import create_qml_application_session
from market_vault.desktop.preferences import DesktopPreferenceStore
sys.path.insert(0, str(Path.cwd() / 'tests'))
from test_research_workspace import _settings
root = Path(sys.argv[1])
context = build_application_context(root / 'settings.yaml', backend_factory=lambda path: ConsoleBackend(MarketVault(_settings(root))))
QQuickStyle.setStyle('Basic')
app = QGuiApplication([])
engine = QQmlApplicationEngine()
session = create_qml_application_session(context, engine, preference_store=DesktopPreferenceStore(root=root / 'preferences'))
engine.load(QUrl.fromLocalFile(str(Path.cwd() / 'src/market_vault/desktop/qml/Main.qml')))
assert engine.rootObjects()
window = engine.rootObjects()[0]
window.setWidth(1100)
window.setHeight(700)
controller = session.context_properties['quantResearchController']
assert session.shell.selectPage('quant_research')
def find(name):
    obj = window.findChild(QObject, name)
    assert obj is not None, name
    return obj
def click(name):
    obj = find(name)
    assert obj.property('visible') and obj.property('enabled'), name
    point = obj.mapToScene(obj.boundingRect().center()).toPoint()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    app.processEvents()
def fill(name, text):
    obj = find(name)
    window.requestActivate()
    QTest.qWait(30)
    pending = [obj]
    edit = obj
    while pending:
        candidate = pending.pop()
        if 'PixelTextField' in candidate.metaObject().className():
            edit = candidate
            break
        pending.extend(candidate.children())
    edit.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
    for ch in text:
        QGuiApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, ord(ch.upper()), Qt.NoModifier, ch))
    app.processEvents()
    assert obj.property('text') == text, (name, obj.property('text'), text)
def complete():
    for _ in range(900):
        QTest.qWait(20)
        if not controller.busy:
            break
    assert not controller.busy and controller.status == 'SUCCESS', (controller.status, controller.error)
click('quantIntradayTab')
QTest.qWait(50)
assert find('intradayInterval').property('currentText') == '5m'
assert find('intradayPreset').property('currentText') == 'LIGHT_TECHNICAL'
assert find('intradayStride').property('text') == '1'
assert find('intradayHorizon').property('text') == '3'
fill('intradayStartDate', '2026-01-05')
fill('intradayEndDate', '2026-01-06')
click('intradayPreviewButton')
complete()
assert controller.intradayPreviewSummary['intraday_observations'] == '148'
click('intradayBuildButton')
dialog = find('intradaySaveDialog')
assert dialog.property('visible')
out = root / 'from-ui.json'
dialog.setProperty('selectedFile', QUrl.fromLocalFile(str(out)))
# Accept the actual dialog with a deterministic local destination.
assert QMetaObject.invokeMethod(dialog, 'accepted', Qt.DirectConnection)
assert QMetaObject.invokeMethod(dialog, 'close', Qt.DirectConnection)
complete()
assert out.is_file() and controller.intradayLoaded and not controller.datasetLoaded
assert controller.intradaySummary['intraday_ready'] == '148'
assert controller.intradayModel.totalRows == 148
assert controller.changeIntradayPage(1) and controller.intradayModel.rowCount() == 48
old_data = controller._intraday_data
assert window.grabWindow().save(str(root / 'intraday-before-edit.png'))
fill('intradayHorizon', '6')
assert session.i18n.setLanguage('en')
assert session.i18n.setLanguage('zh-CN')
assert find('intradayHorizon').property('text') == '6'
assert find('intradayInterval').property('currentText') == '5m'
fill('intradayDataPath', str(out))
click('intradayInspectButton')
complete()
assert controller._intraday_data == old_data and controller.intradayModel.page == 1
assert find('intradayHorizon').property('text') == '6'
assert window.grabWindow().save(str(root / 'intraday-ui.png'))
assert session.runtime.shutdown()
engine.deleteLater()
app.processEvents()
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], cwd=ROOT,
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software",
                                 "PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
