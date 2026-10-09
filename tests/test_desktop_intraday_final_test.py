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
from test_intraday_final_test import final_case, selection_case  # noqa: F401
from test_intraday_research import diagnostic_plan, research_case  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]


def test_actual_qml_execution_scenarios_export_freeze_and_small_window(research_case, tmp_path):
    data, _, _ = research_case
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
root, data_path = Path(sys.argv[1]), Path(sys.argv[2])
QQuickStyle.setStyle('Basic')
app = QGuiApplication([])
engine = QQmlApplicationEngine()
session = create_qml_application_session(build_application_context(root / 'settings.yaml'), engine,
    preference_store=DesktopPreferenceStore(root=root / 'preferences'))
engine.load(QUrl.fromLocalFile(str(Path.cwd() / 'src/market_vault/desktop/qml/Main.qml')))
assert engine.rootObjects()
window = engine.rootObjects()[0]
window.setWidth(1024); window.setHeight(600)
owner = session.context_properties['quantResearchController']
development, final = owner.intradayResearchController, owner.intradayFinalController
assert session.shell.selectPage('quant_research')
def find(name):
    obj = window.findChild(QObject, name)
    if obj is None:
        pending = [window.contentItem()]
        while pending:
            item = pending.pop()
            if item.objectName() == name: obj = item; break
            pending.extend(item.childItems())
    assert obj is not None, name
    return obj
def reveal(item, scroll_name):
    if scroll_name is None: return
    flick = find(scroll_name).property('contentItem')
    rect = item.mapRectToItem(flick, item.boundingRect())
    dy = rect.top() if rect.top() < 0 else max(0, rect.bottom() - flick.height())
    limit = max(0, flick.property('contentHeight') - flick.height())
    flick.setProperty('contentY', min(max(0, flick.property('contentY') + dy), limit))
    QTest.qWait(30)
    rect = item.mapRectToItem(flick, item.boundingRect())
    assert rect.left() >= -1 and rect.right() <= flick.width() + 1, (item.objectName(), rect, flick.width())
    assert rect.top() >= -1 and rect.bottom() <= flick.height() + 1, (item.objectName(), rect, flick.height())
def click(name, scroll_name=None):
    item = find(name)
    app.processEvents(); reveal(item, scroll_name)
    assert item.property('visible') and item.property('enabled'), name
    point = item.mapToScene(item.boundingRect().center()).toPoint()
    assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), (name, point)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.qWait(30)
def nested(item, kind):
    if kind in item.metaObject().className(): return item
    return next(child for child in item.findChildren(QObject) if kind in child.metaObject().className())
def fill(name, value, scroll_name=None):
    item = find(name); reveal(item, scroll_name)
    window.requestActivate(); QTest.qWait(20)
    edit = nested(item, 'PixelTextField')
    edit.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClick(window, Qt.Key_Backspace)
    for char in value:
        QGuiApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, ord(char.upper()), Qt.NoModifier, char))
    app.processEvents()
    assert item.property('text') == value, (name, item.property('text'))
def choose(name, index, scroll_name=None):
    item = find(name); reveal(item, scroll_name)
    combo = nested(item, 'PixelComboBox')
    window.requestActivate(); QTest.qWait(20)
    combo.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_Home)
    for _ in range(index): QTest.keyClick(window, Qt.Key_Down)
    QTest.qWait(30)
    assert item.property('currentIndex') == index, (name, item.property('currentIndex'))
def complete(target=development):
    deadline = time.monotonic() + 150
    while target.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    app.processEvents()
    assert not target.busy and target.status == 'SUCCESS', (target.status, target.error)
def file_selected(name, path):
    dialog = find(name)
    assert dialog.setProperty('selectedFile', QUrl.fromLocalFile(str(path)))
    assert QMetaObject.invokeMethod(dialog, 'accepted', Qt.DirectConnection)
    QMetaObject.invokeMethod(dialog, 'close', Qt.DirectConnection)
    complete()
panel_scroll = 'intradayResearchScroll'
editor_scroll = 'intradayScenariosEditorScroll'
click('quantIntradayTab')
fill('intradayDataPath', str(data_path))
click('intradayInspectButton'); complete(owner)
click('intradayComparisonTab')
click('intradayOpenScenariosButton', panel_scroll)
assert find('intradayResearchCommission').property('text') == ''
assert find('intradayResearchSlippage').property('text') == ''
fill('intradayScenarioName', 'Baseline', editor_scroll)
fill('intradayScenarioCommission', '10', editor_scroll)
fill('intradayScenarioSlippage', '5', editor_scroll)
click('intradayScenarioAdd', editor_scroll)
fill('intradayScenarioName', 'Shorter', editor_scroll)
for name, value in (('EntryDelay', '30'), ('StopNew', '45'), ('Flatten', '10'),
                    ('MaxHold', '6'), ('Commission', '20'), ('Slippage', '7')):
    fill('intradayScenario' + name, value, editor_scroll)
assert '2 × 3 = 6' in find('intradayScenariosEvaluationCount').property('text')
assert session.i18n.setLanguage('zh-CN'); assert session.i18n.setLanguage('en')
assert find('intradayScenarioMaxHold').property('text') == '6'
choose('intradayScenarioEditorChoice', 0, editor_scroll)
assert find('intradayScenarioName').property('text') == 'Baseline'
choose('intradayScenarioEditorChoice', 1, editor_scroll)
assert find('intradayScenarioMaxHold').property('text') == '6'
assert window.grabWindow().save(str(root / 'execution-scenarios-editor.png'))
click('intradayScenariosRun'); complete()
assert development.scenariosLoaded and development.scenarioNames == ['Baseline', 'Shorter']
assert development.tableModel.totalRows == 6 and development.resultSummary['evaluation_count'] == '6'
assert not final.canFreeze and development.experimentPath == ''
assert find('intradayResearchCommission').property('text') == ''
assert find('intradayResearchSlippage').property('text') == ''
choose('intradayResearchScenario', 1, panel_scroll)
choose('intradayResearchCandidate', 2, panel_scroll)
assert development.scenarioIndex == 1 and development.candidateIndex == 2
click('intradayResearchSettingsButton', panel_scroll)
fill('intradayResearchMaxHold', '99', 'intradaySettingsScroll')
click('intradayResearchSettingsDone', 'intradaySettingsScroll')
all_path, child_path = root / 'all-scenarios.json', root / 'selected-scenario.json'
click('intradayExperimentSaveButton', panel_scroll)
file_selected('intradayExperimentSaveDialog', all_path)
record = json.loads(all_path.read_bytes())
assert record['evaluation_mode'] == 'INTRADAY_EXECUTION_SCENARIOS'
assert len(record['report']['scenarios']) == 2
assert not final.canFreeze and development.collectionPath == str(all_path)
assert development.experimentPath == ''
click('intradayExperimentReplayButton', panel_scroll); complete()
assert development.collectionProof == 'REPLAY_MATCH'
assert find('intradayResearchMaxHold').property('text') == '99'
choose('intradayResearchView', 7, panel_scroll)
assert development.tableModel.totalRows == 17
click('intradayScenarioExportButton', panel_scroll)
file_selected('intradayScenarioExportDialog', child_path)
child = json.loads(child_path.read_bytes())
assert child == record['report']['scenarios'][1]['experiment']
assert child['plan']['execution']['max_hold_bars'] == 6
assert final.canFreeze and development.experimentPath == str(child_path)
choose('intradayResearchScenario', 0, panel_scroll)
assert not final.canFreeze and development.experimentPath == ''
choose('intradayResearchScenario', 1, panel_scroll)
assert final.canFreeze and development.candidateIndex == 2
click('intradayFinalTab')
click('intradayFreezeButton', 'intradayFinalScroll'); complete(final)
assert final.frozenCandidate['strategy']['name'] == 'Ridge'
assert final.frozenCandidate['execution_policy'] == child['plan']['execution']
click('intradayRunTestButton', 'intradayFinalScroll'); complete(final)
assert final._test_root['report']['execution_policy'] == child['plan']['execution']
assert len(final._test_root['report']['predictions']) == 444
click('intradayComparisonTab')
click('intradayExperimentOpenButton', panel_scroll)
file_selected('intradayExperimentOpenDialog', all_path)
assert development.collectionProof == 'RECORDED' and development.scenarioIndex == 0
assert not final.canFreeze and find('intradayResearchMaxHold').property('text') == '12'
choose('intradayResearchScenario', 1, panel_scroll)
assert not final.canFreeze  # Open does not invent child export paths
click('intradayOpenScenariosButton', panel_scroll)
choose('intradayScenarioEditorChoice', 1, editor_scroll)
assert find('intradayScenarioMaxHold').property('text') == '6'
click('intradayScenariosKeep')
choose('intradayResearchCandidate', 2, panel_scroll)
for language in ('en', 'zh-CN'):
    assert session.i18n.setLanguage(language)
    choose('intradayResearchView', 0, panel_scroll)
    table = find('intradayResearchTable')
    flick = find(panel_scroll).property('contentItem')
    flick.setProperty('contentY', max(0, flick.property('contentHeight') - flick.height()))
    QTest.qWait(80)
    assert table.height() >= 120
    header = find('intradayResearchTableHeader')
    viewport = next(item for item in table.findChildren(QObject)
        if item.metaObject().className().startswith('QQuickTableView') and item.property('height') is not None)
    assert viewport.height() >= 32
    assert header.mapToScene(header.boundingRect().topLeft()).y() >= find(panel_scroll).mapToScene(find(panel_scroll).boundingRect().topLeft()).y()
    assert window.grabWindow().save(str(root / ('execution-scenarios-' + language + '.png')))
    viewport.setProperty('contentX', min(9 * 145, max(0, viewport.property('contentWidth') - viewport.width())))
    QTest.qWait(80)
    caption = session.i18n.columnLabel('scenario_return_change')
    pending, labels = [header], []
    while pending:
        item = pending.pop()
        if item.property('text') == caption: labels.append(item)
        pending.extend(item.childItems())
    assert any(label.property('visible') and not label.property('truncated')
        and label.mapRectToItem(header, label.boundingRect()).left() >= 0
        and label.mapRectToItem(header, label.boundingRect()).right() <= header.width() for label in labels), caption
    assert window.grabWindow().save(str(root / ('execution-scenarios-units-' + language + '.png')))
    choose('intradayResearchView', 7, panel_scroll)
    assert development.tableModel.totalRows == 17 and table.height() >= 170
assert development._collection_content == all_path.read_bytes()
assert development.collectionProof == 'RECORDED'
assert session.runtime.backend_if_initialized is None and session.shutdown()
print('REAL_EXECUTION_SCENARIOS_FREEZE_WORKFLOW_OK')
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(data.path)],
        cwd=ROOT, env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software", "PYTHONPATH": str(ROOT / "src")},
        capture_output=True, text=True, timeout=360)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "REAL_EXECUTION_SCENARIOS_FREEZE_WORKFLOW_OK" in result.stdout
    assert "ReferenceError" not in result.stderr and "TypeError" not in result.stderr


def test_actual_qml_offline_performance_views_in_both_languages(intraday_experiment, final_case, tmp_path):
    source, test_path = tmp_path / "development.json", tmp_path / "test.json"
    write_strategy_experiment(intraday_experiment, path=source)
    write_strategy_experiment(final_case[1], path=test_path)
    (tmp_path / "settings.yaml").write_text("storage:\n  root_dir: ./data\n")
    script = r'''
import sys, time
from pathlib import Path
from PySide6.QtCore import QObject, QUrl, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from market_vault.application import build_application_context
from market_vault.desktop.bootstrap import create_qml_application_session
from market_vault.desktop.preferences import DesktopPreferenceStore
root, source, test_path = map(Path, sys.argv[1:])
QQuickStyle.setStyle('Basic')
app = QGuiApplication([])
engine = QQmlApplicationEngine()
session = create_qml_application_session(build_application_context(root / 'settings.yaml'), engine,
    preference_store=DesktopPreferenceStore(root=root / 'preferences'))
engine.load(QUrl.fromLocalFile(str(Path.cwd() / 'src/market_vault/desktop/qml/Main.qml')))
assert engine.rootObjects()
window = engine.rootObjects()[0]
window.setWidth(1024); window.setHeight(600)
owner = session.context_properties['quantResearchController']
development, final = owner.intradayResearchController, owner.intradayFinalController
assert session.shell.selectPage('quant_research')
def visual():
    pending = [window.contentItem()]
    while pending:
        item = pending.pop()
        yield item
        pending.extend(item.childItems())
def find(name):
    result = window.findChild(QObject, name)
    if result is None:
        result = next((item for item in visual() if item.objectName() == name), None)
    assert result is not None, name
    return result
def click(name):
    item = find(name)
    app.processEvents()
    assert item.isVisible() and item.isEnabled(), name
    point = item.mapToScene(item.boundingRect().center()).toPoint()
    assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), point
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.qWait(30)
def choose(name, index):
    item = find(name)
    combo = next(c for c in item.findChildren(QObject) if 'PixelComboBox' in c.metaObject().className())
    window.requestActivate(); QTest.qWait(20)
    combo.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_Home)
    for _ in range(index): QTest.keyClick(window, Qt.Key_Down)
    QTest.qWait(30)
    assert item.property('currentIndex') == index
def complete(controller):
    deadline = time.monotonic() + 30
    while controller.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    assert controller.status == 'SUCCESS', (controller.status, controller.error)
click('quantIntradayTab'); click('intradayComparisonTab')
assert development.openExperiment(str(source)); complete(development)
assert final.openTest(str(test_path)); complete(final)
before = (development._content, final._test_content)
for tab, controller, selector, first, table_name, day_count in (
    ('intradayComparisonTab', development, 'intradayResearchView', 7, 'intradayResearchTable', 10),
    ('intradayFinalTab', final, 'intradayTestView', 6, 'intradayTestTable', 6)):
    click(tab)
    for language, label in (('en', 'Trades'), ('zh-CN', '交易次数')):
        assert session.i18n.setLanguage(language)
        choose(selector, first)
        assert controller.tableModel.totalRows == 17
        QTest.qWait(80)
        table = find(table_name)
        assert table.height() >= 130, (tab, language, table.height())
        assert any(item.isVisible() and item.property('text') == label for item in visual()), (tab, language)
        assert window.grabWindow().save(str(root / (tab + '-' + language + '.png')))
        for offset in (1, 2, 3):
            choose(selector, first + offset)
            if offset == 3: assert controller.tableModel.totalRows == day_count
        choose(selector, first)
assert (development._content, final._test_content) == before
assert development.resultSummary['intraday_verification'] == 'RECORDED'
assert final.resultSummary['intraday_test_proof'] == 'RECORDED'
assert session.runtime.backend_if_initialized is None
assert session.shutdown()
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(source), str(test_path)],
                            cwd=ROOT, env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QSG_RHI_BACKEND": "software"},
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


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
    for width, height in ((1000, 650), (1024, 600), (1100, 700)):
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
