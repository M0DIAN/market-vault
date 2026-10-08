"""Real controller and visible QML freeze / final TEST / replay workflows."""

from concurrent.futures import Future
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytest.importorskip("PySide6")

from market_vault.desktop.quant_research import QuantResearchController
from market_vault.research import intraday_final_test as final
from market_vault.research import intraday_research as research
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.strategy_experiment import write_strategy_experiment
from test_desktop_quant_research import _runtime, qt_app  # noqa: F401
from test_intraday_experiment import intraday_experiment  # noqa: F401
from test_intraday_research import diagnostic_plan, research_case  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]


def test_controller_freezes_nonfirst_candidate_in_second_cost(qt_app, research_case, tmp_path):
    _, plan, _ = research_case
    diagnostic = diagnostic_plan(plan)
    snapshot = create_intraday_experiment(plan=diagnostic, report=research.run_intraday_research(diagnostic))
    runtime, runner = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    development, controller = owner.intradayResearchController, owner.intradayFinalController
    development._apply(snapshot)
    assert development.saveExperiment(str(tmp_path / "diagnostics.json"))
    runtime._poll()
    assert development.selectCandidate(6)  # actual position (cost 1, candidate 2)
    assert controller.freezeSelected()
    runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    candidate = controller.frozenCandidate
    assert candidate["axis_values"] == [1000, 0]
    assert candidate["strategy"]["alpha"] == 1000
    assert candidate["execution_policy"]["commission_bps"] == 10
    assert candidate["execution_policy"]["slippage_bps"] == 5
    assert controller._selection_root["plan"]["selection"]["cost_index"] == 1
    assert controller._selection_root["plan"]["selection"]["candidate_index"] == 2
    assert not controller.testLoaded and runtime.backend_if_initialized is None and runtime.shutdown()


def test_controller_capture_immutable_selection_and_independent_proofs(qt_app, intraday_experiment, tmp_path, monkeypatch):
    runtime, runner = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    development, controller = owner.intradayResearchController, owner.intradayFinalController
    development._apply(intraday_experiment)
    assert not controller.canFreeze and not controller.freezeSelected()
    assert controller.status == "VALIDATION_ERROR"
    assert development.saveExperiment(str(tmp_path / "development.json"))
    runtime._poll()
    assert development.status == "SUCCESS" and controller.canFreeze
    assert development.selectCandidate(2)
    pending = []
    def deferred(name, operation):
        future = Future()
        pending.append((future, operation))
        return future
    with monkeypatch.context() as patch:
        patch.setattr(runner, "submit", deferred)
        assert controller.freezeSelected()
        assert controller.busy
        assert development.selectCandidate(0)
        future, operation = pending.pop()
        future.set_result(operation())
        runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    assert controller.frozenCandidate["strategy"]["name"] == "Ridge"
    frozen = controller._selection_content
    detached = controller.frozenCandidate
    detached["strategy"]["alpha"] = 10000
    assert controller.frozenCandidate["strategy"]["alpha"] == 1
    assert controller.saveSelection(str(tmp_path / "selection.json"))
    runtime._poll()
    assert (tmp_path / "selection.json").read_bytes() == frozen
    assert controller.runTest("", "")
    runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    assert controller._selection_content == frozen
    assert controller.selectView(4) and controller.tableModel.totalRows == 1
    assert controller.selectView(5) and controller.tableModel.totalRows == 444
    assert controller.changePage(1) and controller.tableModel.page == 2
    assert controller.saveTest(str(tmp_path / "test.json"))
    runtime._poll()
    previous = controller._test_content
    assert controller.tableModel.page == 2 and (tmp_path / "test.json").read_bytes() == previous
    assert controller.runTest(str(tmp_path / "missing-source.json"), "")
    runtime._poll()
    assert controller.status == "FAILED" and controller._test_content == previous
    assert controller.tableModel.page == 2
    assert controller.freezeSelected()
    runtime._poll()
    assert controller.status == "SUCCESS" and controller.frozenCandidate["strategy"]["name"] == "Flat"
    assert not controller.testLoaded and controller.testPath == "" and controller.tableModel.totalRows == 0
    assert (tmp_path / "test.json").read_bytes() == previous
    with monkeypatch.context() as patch:
        patch.setattr(final, "load_intraday_dataset", lambda *a: pytest.fail("Open TEST read data"))
        patch.setattr(final, "load_strategy_experiment", lambda *a: pytest.fail("Open TEST read development"))
        patch.setattr(research, "_fit", lambda *a: pytest.fail("Open TEST fitted"))
        assert controller.openTest(str(tmp_path / "test.json"))
        runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    assert controller.frozenCandidate["strategy"]["name"] == "Ridge"
    assert controller.selectionPath == "" and controller.testLoaded
    assert controller.resultSummary["intraday_selection_proof"] == "RECORDED"
    assert controller.resultSummary["intraday_test_proof"] == "RECORDED"
    assert controller.replaySelection(str(tmp_path / "missing-source.json"), "")
    runtime._poll()
    assert controller.resultSummary["intraday_selection_proof"] == "REPLAY_FAILED"
    assert controller.resultSummary["intraday_test_proof"] == "RECORDED"
    assert controller.replayTest(str(tmp_path / "missing-source.json"), "")
    runtime._poll()
    assert controller.resultSummary["intraday_test_proof"] == "REPLAY_FAILED"
    assert controller._test_content == previous
    assert controller.openSelection(str(tmp_path / "missing-selection.json"))
    runtime._poll()
    assert controller.status == "FAILED" and controller._test_content == previous
    assert runtime.backend_if_initialized is None and runtime.shutdown()


def test_actual_qml_freeze_save_open_final_test_and_two_file_replay(intraday_experiment, research_case, tmp_path):
    data, _, _ = research_case
    source = tmp_path / "development.json"
    write_strategy_experiment(intraday_experiment, path=source)
    (tmp_path / "settings.yaml").write_text("storage:\n  root_dir: ./data\n")
    script = r'''
import sys, time, json
from pathlib import Path
from PySide6.QtCore import QObject, QUrl, Qt, QEvent, QMetaObject
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from market_vault.application import build_application_context
from market_vault.desktop.bootstrap import create_qml_application_session
from market_vault.desktop.preferences import DesktopPreferenceStore
root, source, data_path = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
QQuickStyle.setStyle('Basic')
app = QGuiApplication([])
engine = QQmlApplicationEngine()
session = create_qml_application_session(build_application_context(root / 'settings.yaml'), engine,
    preference_store=DesktopPreferenceStore(root=root / 'preferences'))
engine.load(QUrl.fromLocalFile(str(Path.cwd() / 'src/market_vault/desktop/qml/Main.qml')))
assert engine.rootObjects()
window = engine.rootObjects()[0]
window.setWidth(1100); window.setHeight(700)
owner = session.context_properties['quantResearchController']
development, controller = owner.intradayResearchController, owner.intradayFinalController
assert session.shell.selectPage('quant_research')
def find(name):
    obj = window.findChild(QObject, name)
    if obj is None:
        pending = [window.contentItem()]
        while pending:
            candidate = pending.pop()
            if candidate.objectName() == name: obj = candidate; break
            pending.extend(candidate.childItems())
    assert obj is not None, name
    return obj
def click_obj(obj):
    app.processEvents()
    assert obj.property('visible') and obj.property('enabled'), obj.objectName()
    point = obj.mapToScene(obj.boundingRect().center()).toPoint()
    assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), point
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    app.processEvents()
def click(name): click_obj(find(name))
def nested(obj, kind):
    if kind in obj.metaObject().className(): return obj
    return next(c for c in obj.findChildren(QObject) if kind in c.metaObject().className())
def choose(name, index):
    obj = find(name)
    combo = nested(obj, 'PixelComboBox')
    window.requestActivate(); QTest.qWait(30)
    combo.forceActiveFocus(); app.processEvents()
    QTest.keyClick(window, Qt.Key_Home)
    for _ in range(index): QTest.keyClick(window, Qt.Key_Down)
    app.processEvents()
    assert obj.property('currentIndex') == index, (name, obj.property('currentIndex'))
def fill(name, text):
    obj = find(name)
    window.requestActivate(); QTest.qWait(30)
    edit = nested(obj, 'PixelTextField')
    edit.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
    for ch in text:
        QGuiApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, ord(ch.upper()), Qt.NoModifier, ch))
    app.processEvents()
    assert obj.property('text') == text, (name, obj.property('text'))
def complete(target=controller):
    deadline = time.monotonic() + 150
    while target.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    app.processEvents()
    assert not target.busy and target.status == 'SUCCESS', (target.status, target.error)
def file_selected(name, path, target=controller):
    dialog = find(name)
    assert dialog.setProperty('selectedFile', QUrl.fromLocalFile(str(path)))
    assert QMetaObject.invokeMethod(dialog, 'accepted', Qt.DirectConnection)
    QMetaObject.invokeMethod(dialog, 'close', Qt.DirectConnection)
    complete(target)
click('quantIntradayTab'); click('intradayComparisonTab')
click('intradayExperimentOpenButton')
file_selected('intradayExperimentOpenDialog', source, development)
assert not owner.intradayLoaded
click('intradayFinalTab'); QTest.qWait(50)
choose('intradayFinalCandidate', 2)
click('intradayFreezeButton'); complete()
frozen = controller._selection_content
assert controller.frozenCandidate['strategy']['name'] == 'Ridge'
choose('intradayFinalCandidate', 0)
assert controller._selection_content == frozen
saved_selection, saved_test = root / 'selection.json', root / 'test.json'
click('intradaySelectionSaveButton'); file_selected('intradaySelectionSaveDialog', saved_selection)
click('intradaySelectionOpenButton'); file_selected('intradaySelectionOpenDialog', saved_selection)
assert controller.resultSummary['intraday_selection_proof'] == 'RECORDED'
assert not controller.testLoaded and controller._selection_content == frozen
click('intradayComparisonTab')
click('intradayResearchSettingsButton'); QTest.qWait(30)
fill('intradayResearchMaxHold', '9')
click('intradayResearchSettingsDone')
click('intradayFinalTab')
click('intradayRunTestButton'); complete()
assert controller._test_root['report']['execution_policy']['max_hold_bars'] == 12
assert controller._test_root['report']['model']['alpha'] == 1
assert controller.resultSummary['intraday_test_proof'] == 'COMPUTED'
choose('intradayTestView', 4)
assert controller.tableModel.totalRows == 1
choose('intradayTestView', 5)
assert controller.tableModel.totalRows == 444
choose('intradayTestView', 2)
assert controller.tableModel.totalRows == 936
table = find('intradayTestTable')
assert table.height() >= 170, table.height()
next_button = next(obj for obj in table.findChildren(QObject) if obj.property('glyph') == 'next' and obj.metaObject().indexOfSignal('clicked()') >= 0)
click_obj(next_button)
assert controller.tableModel.page == 2
click('intradayTestSaveButton'); file_selected('intradayTestSaveDialog', saved_test)
original = saved_test.read_bytes()
assert controller.tableModel.page == 2
click('intradayTestOpenButton'); file_selected('intradayTestOpenDialog', saved_test)
assert controller.selectionPath == '' and controller.frozenCandidate['strategy']['name'] == 'Ridge'
assert controller.resultSummary['intraday_test_proof'] == 'RECORDED'
# Opened proof labels are longer than freshly computed labels. At the actual
# supported minimum, scroll the panel instead of crushing its only metrics row.
for language in ('en', 'zh-CN'):
    assert session.i18n.setLanguage(language)
    for width, height in ((1000, 650), (1100, 700)):
        window.setWidth(width); window.setHeight(height)
        choose('intradayTestView', 0); QTest.qWait(100)
        scroll = find('intradayFinalScroll')
        flickable = scroll.property('contentItem')
        assert table.height() >= 120, (language, width, height, table.height())
        bottom = max(0, flickable.property('contentHeight') - flickable.height())
        assert flickable.setProperty('contentY', bottom)
        QTest.qWait(50)
        header = find('intradayTestTableHeader')
        viewport = next(obj for obj in table.findChildren(QObject)
                        if obj.metaObject().className().startswith('QQuickTableView') and obj.property('height') is not None)
        assert viewport.height() >= 32, (language, viewport.height())
        header_top = header.mapToScene(header.boundingRect().topLeft()).y()
        header_bottom = header.mapToScene(header.boundingRect().bottomLeft()).y()
        row_top = viewport.mapToScene(viewport.boundingRect().topLeft()).y()
        scroll_top = scroll.mapToScene(scroll.boundingRect().topLeft()).y()
        scroll_bottom = scroll.mapToScene(scroll.boundingRect().bottomLeft()).y()
        assert scroll_top <= header_top < header_bottom <= row_top + 1
        assert row_top + 32 <= scroll_bottom
        footer_top = next_button.mapToScene(next_button.boundingRect().topLeft()).y()
        assert row_top + 32 <= footer_top < scroll_bottom
        assert window.grabWindow().save(str(root / f'final-{language}-{width}-{height}.png'))
        choose('intradayTestView', 2); QTest.qWait(50)
        assert table.height() >= 170
window.setWidth(1100); window.setHeight(700)
assert session.i18n.setLanguage('en')
choose('intradayTestView', 2)
assert flickable.setProperty('contentY', 0)
QTest.qWait(50)
# Relocate this test's private source file; the shared Q5/Canonical fixture stays
# intact. Both override values are exercised through visible file dialogs.
moved_source, moved_data = root / 'moved-development.json', root / 'moved-data.json'
source.rename(moved_source)
moved_data.write_bytes(data_path.read_bytes())
click('intradayFinalLocationsButton'); QTest.qWait(30)
click('intradayFinalSourceBrowse'); file_selected('intradayFinalSourceDialog', moved_source)
click('intradayFinalDataBrowse'); file_selected('intradayFinalDataDialog', moved_data)
assert find('intradayFinalSourcePath').property('text').endswith('/moved-development.json')
assert find('intradayFinalDataPath').property('text').endswith('/moved-data.json')
assert window.grabWindow().save(str(root / 'intraday-final-locations.png'))
click('intradayFinalLocationsDone')
click('intradayTestReplayButton'); complete()
assert controller.resultSummary['intraday_test_proof'] == 'REPLAY_MATCH'
assert controller._test_content == original
assert controller.resultSummary['intraday_selection_proof'] == 'RECORDED'
click('intradaySelectionReplayButton'); complete()
assert controller.resultSummary['intraday_selection_proof'] == 'REPLAY_MATCH'
assert controller.resultSummary['intraday_test_proof'] == 'REPLAY_MATCH'
assert session.i18n.setLanguage('zh-CN')
choose('intradayTestView', 0)
assert find('intradayTestEquity').property('visible')
assert window.grabWindow().save(str(root / 'intraday-final-overview.png'))
choose('intradayTestView', 2)
assert not find('intradayTestEquity').property('visible')
assert window.grabWindow().save(str(root / 'intraday-final-ui.png'))
click('intradayFinalLocationsButton')
fill('intradayFinalSourcePath', 'relative/source.json')
click('intradayFinalLocationsDone')
click('intradayTestReplayButton')
assert controller.status == 'VALIDATION_ERROR'
assert controller.resultSummary['intraday_test_proof'] == 'REPLAY_FAILED'
assert controller.resultSummary['intraday_selection_proof'] == 'REPLAY_MATCH'
assert controller._test_content == original
click('intradaySelectionOpenButton'); file_selected('intradaySelectionOpenDialog', saved_selection)
assert not controller.testLoaded
assert find('intradayFinalSourcePath').property('text') == '' and find('intradayFinalDataPath').property('text') == ''
assert saved_test.read_bytes() == original
assert session.runtime.backend_if_initialized is None and session.runtime.shutdown()
engine.deleteLater(); app.processEvents()
print('REAL_INTRADAY_FINAL_WORKFLOW_OK')
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(source), str(data.path)], cwd=ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software", "PYTHONPATH": str(ROOT / "src")},
        capture_output=True, text=True, timeout=420)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "REAL_INTRADAY_FINAL_WORKFLOW_OK" in result.stdout
    assert "ReferenceError" not in result.stderr and "TypeError" not in result.stderr
