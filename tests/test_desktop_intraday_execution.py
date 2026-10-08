"""Real source-to-execution controller and rendered QML entry point."""

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
VALUES = {"signal_field": "return_2", "comparator": "GT", "threshold": "0",
          "commission_bps": "10", "slippage_bps": "5", "max_hold_bars": "12"}


def test_controller_complete_ledger_snapshot_guard_and_last_success(qt_app, tmp_path):
    plan = input_plan(tmp_path)
    data = build_intraday_dataset(plan)
    path = write_intraday_dataset(data, path=tmp_path / "data.json")
    calls = []
    runtime, runner = _runtime(tmp_path, calls)
    controller = QuantResearchController(runtime)
    assert not controller.runIntradayBacktest(VALUES)
    assert controller.inspectIntraday(str(path))
    runtime._poll()
    assert not controller.runIntradayBacktest({**VALUES, "commission_bps": ""})
    assert controller.runIntradayBacktest(VALUES)
    runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    assert int(controller.intradayBacktestSummary["trade_count"]) > 0
    assert controller.intradayBacktestDataId == data.data_id
    assert controller.selectIntradayBacktestView(1)
    assert controller.intradayBacktestModel.totalRows == 156
    assert controller.changeIntradayBacktestPage(1)
    assert controller.intradayBacktestModel.rowCount() == 56
    assert not controller.changeIntradayBacktestPage(1)
    previous = controller._intraday_backtest_tables
    # Replace only the test fixture with another valid snapshot at the same path.
    plan["target_horizon_bars"] = 6
    path.write_bytes(build_intraday_dataset(plan).content)
    assert controller.runIntradayBacktest(VALUES)
    runtime._poll()
    assert controller.status != "SUCCESS" and "identity" in controller.error
    assert controller._intraday_backtest_tables == previous
    assert controller.intradayBacktestModel.page == 2
    assert controller.intradayBacktestDataId == data.data_id
    assert not calls and runtime.backend_if_initialized is None
    assert runtime.shutdown()


def test_actual_qml_run_ledger_pagination_and_language_drafts(tmp_path):
    data = build_intraday_dataset(input_plan(tmp_path))
    path = write_intraday_dataset(data, path=tmp_path / "data.json")
    (tmp_path / "settings.yaml").write_text("storage:\n  root_dir: ./data\n", encoding="utf-8")
    script = r'''
import sys
import time
from pathlib import Path
from PySide6.QtCore import QObject, QUrl, Qt, QEvent
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from market_vault.application import build_application_context
from market_vault.desktop.bootstrap import create_qml_application_session
from market_vault.desktop.preferences import DesktopPreferenceStore
root = Path(sys.argv[1])
QQuickStyle.setStyle('Basic')
app = QGuiApplication([])
engine = QQmlApplicationEngine()
context = build_application_context(root / 'settings.yaml')
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
    if obj is None:
        pending = [window.contentItem()]
        while pending:
            candidate = pending.pop()
            if candidate.objectName() == name:
                obj = candidate
                break
            pending.extend(candidate.childItems())
    assert obj is not None, name
    return obj
def click_obj(obj):
    assert obj.property('visible') and obj.property('enabled'), obj.objectName()
    point = obj.mapToScene(obj.boundingRect().center()).toPoint()
    assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), point
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    app.processEvents()
def click(name):
    click_obj(find(name))
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
    assert obj.property('text') == text
def complete():
    for _ in range(2000):
        app.processEvents()
        # Allow the real Python worker to import lazy business dependencies;
        # a tight native qWait loop can starve it of the GIL in this harness.
        time.sleep(0.01)
        if not controller.busy:
            break
    assert not controller.busy and controller.status == 'SUCCESS', (controller.status, controller.error)
click('quantIntradayTab')
fill('intradayDataPath', str(root / 'data.json'))
click('intradayInspectButton')
complete()
click('intradayExecutionTab')
QTest.qWait(50)
assert find('intradaySignalFeature').property('currentText') == 'return_2'
assert find('intradayCommission').property('text') == ''
assert find('intradaySlippage').property('text') == ''
click('intradayRunBacktestButton')
assert controller.status != 'SUCCESS' and not controller.busy
fill('intradayCommission', '10')
fill('intradaySlippage', '5')
click('intradayRunBacktestButton')
complete()
assert int(controller.intradayBacktestSummary['trade_count']) > 0
click('intradayView1')
QTest.qWait(50)
assert controller.intradayBacktestModel.totalRows == 156
table = find('intradayBacktestTable')
assert table.height() >= 100, table.height()
buttons = [obj for obj in table.findChildren(QObject) if obj.property('glyph') == 'next'
           and obj.metaObject().indexOfSignal('clicked()') >= 0]
assert len(buttons) == 1
click_obj(buttons[0])
assert controller.intradayBacktestModel.page == 2 and controller.intradayBacktestModel.rowCount() == 56
fill('intradayThreshold', '0.125')
assert session.i18n.setLanguage('en')
assert session.i18n.setLanguage('zh-CN')
assert find('intradayThreshold').property('text') == '0.125'
assert find('intradayCommission').property('text') == '10'
assert find('intradaySignalFeature').property('currentText') == 'return_2'
assert controller.intradayBacktestModel.page == 2
assert window.grabWindow().save(str(root / 'intraday-execution-ui.png'))
click('intradayView2')
assert controller.intradayBacktestModel.totalRows == 1
assert session.runtime.backend_if_initialized is None
assert session.runtime.shutdown()
engine.deleteLater()
app.processEvents()
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], cwd=ROOT,
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software",
                                 "PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
