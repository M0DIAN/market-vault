"""Real intraday research controller and visible QML development workflow."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

pytest.importorskip("PySide6")

from market_vault.desktop.quant_research import QuantResearchController
from market_vault.research import intraday_research as research
from market_vault.research.strategy_experiment import write_strategy_experiment
from test_desktop_quant_research import _runtime, qt_app  # noqa: F401
from test_intraday_experiment import intraday_experiment  # noqa: F401
from test_intraday_research import research_case  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def test_offline_controller_views_drafts_failure_and_replay_state(qt_app, intraday_experiment, tmp_path, monkeypatch):
    path = tmp_path / "saved.json"
    write_strategy_experiment(intraday_experiment, path=path)
    runtime, runner = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    controller = owner.intradayResearchController
    with monkeypatch.context() as patch:
        patch.setattr(research, "load_intraday_dataset", lambda *a: pytest.fail("Open read data"))
        patch.setattr(research, "_fit", lambda *a: pytest.fail("Open fitted"))
        assert controller.openExperiment(str(path))
        runtime._poll()
        assert controller.status == "SUCCESS", controller.error
        assert controller.resultSummary["intraday_verification"] == "RECORDED"
        assert not controller.dataLoaded and controller.restoreRevision == 1
        view = controller.restoredPlan
        view["strategies"][0]["threshold"] = 123
        assert controller.restoredPlan["strategies"][0]["threshold"] == 1000000
        assert controller.selectCandidate(2) and controller.selectView(4)
        assert controller.tableModel.totalRows == 2
        assert controller.selectView(5) and controller.tableModel.totalRows == 740
        assert controller.changePage(1) and controller.tableModel.page == 2
        assert controller.saveExperiment(str(tmp_path / "copy.json"))
        runtime._poll()
        assert controller.status == "SUCCESS"
        assert (tmp_path / "copy.json").read_bytes() == path.read_bytes()
        assert controller.candidateIndex == 2 and controller.tableModel.page == 2
    assert controller.replayExperiment("")
    runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    assert controller.resultSummary["intraday_verification"] == "REPLAY_MATCH"
    previous = controller._content
    assert controller.replayExperiment(str(tmp_path / "missing-source.json"))
    runtime._poll()
    assert controller.status == "FAILED"
    assert controller.resultSummary["intraday_verification"] == "REPLAY_FAILED"
    assert controller._content == previous and controller.candidateIndex == 2 and controller.tableModel.page == 2
    assert controller.openExperiment(str(tmp_path / "missing-experiment.json"))
    runtime._poll()
    assert controller.status == "FAILED" and controller._content == previous and controller.restoreRevision == 1
    assert runtime.backend_if_initialized is None and runtime.shutdown()


def test_actual_qml_compare_models_pagination_save_open_replay_and_language(research_case, tmp_path):
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
root, data_path = Path(sys.argv[1]), sys.argv[2]
QQuickStyle.setStyle('Basic')
app = QGuiApplication([])
engine = QQmlApplicationEngine()
context = build_application_context(root / 'settings.yaml')
session = create_qml_application_session(context, engine, preference_store=DesktopPreferenceStore(root=root / 'preferences'))
engine.load(QUrl.fromLocalFile(str(Path.cwd() / 'src/market_vault/desktop/qml/Main.qml')))
assert engine.rootObjects()
window = engine.rootObjects()[0]
window.setWidth(1100); window.setHeight(700)
owner = session.context_properties['quantResearchController']
controller = owner.intradayResearchController
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
def choose(name, index):
    obj = find(name)
    combo = nested(obj, 'PixelComboBox')
    window.requestActivate(); QTest.qWait(30)
    combo.forceActiveFocus()
    app.processEvents()
    QTest.keyClick(window, Qt.Key_Home)
    for _ in range(index): QTest.keyClick(window, Qt.Key_Down)
    app.processEvents()
    assert obj.property('currentIndex') == index, (name, obj.property('currentIndex'))
def complete(target=controller):
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
click('quantIntradayTab')
fill('intradayDataPath', data_path)
click('intradayInspectButton'); complete(owner)
click('intradayComparisonTab'); QTest.qWait(50)
assert '2025-03-10' in find('intradayResearchBoundaries').property('text')
assert '2025-03-25' in find('intradayResearchBoundaries').property('text')
click('intradayRunComparisonButton')
assert controller.status == 'VALIDATION_ERROR' and not controller.busy
click('intradayResearchSettingsButton'); QTest.qWait(50)
assert find('intradayResearchCommission').property('text') == ''
assert find('intradayResearchSlippage').property('text') == ''
fill('intradayResearchCommission', '10'); fill('intradayResearchSlippage', '5')
assert window.grabWindow().save(str(root / 'intraday-research-settings.png'))
click('intradayResearchSettingsDone')
click('intradayRunComparisonButton'); complete()
assert len(controller.candidateNames) == 3 and controller.resultSummary['intraday_eval_days'] == '10'
assert controller.resultSummary['intraday_verification'] == 'COMPUTED'
choose('intradayResearchCandidate', 2)
assert controller.candidateIndex == 2
choose('intradayResearchView', 4)
assert controller.tableModel.totalRows == 2
choose('intradayResearchView', 2)
assert controller.tableModel.totalRows == 1560
table = find('intradayResearchTable')
assert table.height() >= 100, table.height()
next_button = next(obj for obj in table.findChildren(QObject) if obj.property('glyph') == 'next' and obj.metaObject().indexOfSignal('clicked()') >= 0)
click_obj(next_button)
assert controller.tableModel.page == 2
click('intradayResearchSettingsButton'); QTest.qWait(30)
fill('intradayResearchMaxHold', '9')
assert session.i18n.setLanguage('zh-CN'); assert session.i18n.setLanguage('en')
assert find('intradayResearchMaxHold').property('text') == '9'
assert controller.tableModel.page == 2 and controller.candidateIndex == 2
click('intradayResearchSettingsDone')
saved = root / 'research.json'
click('intradayExperimentSaveButton'); file_selected('intradayExperimentSaveDialog', saved)
record = json.loads(saved.read_bytes())
assert record['plan']['execution']['max_hold_bars'] == 12
assert controller.tableModel.page == 2
click('intradayExperimentReplayButton'); complete()
assert controller.resultSummary['intraday_verification'] == 'REPLAY_MATCH'
assert find('intradayResearchMaxHold').property('text') == '9'
assert controller.tableModel.page == 2 and controller.candidateIndex == 2
click('intradayExperimentOpenButton'); file_selected('intradayExperimentOpenDialog', saved)
assert controller.restoreRevision == 1 and controller.resultSummary['intraday_verification'] == 'RECORDED'
assert find('intradayResearchMaxHold').property('text') == '12'
assert find('intradayResearchCommission').property('text') == '10'
# Presentation-only A -> B -> A source/default notifications, after the real
# source/research/Save/Open/Replay workflow above. No synthetic source is read
# or offered to the execution API by this UI state regression.
settings = find('intradayResearchSettings')
options = settings.property('featureOptions')
if hasattr(options, 'toVariant'): options = options.toVariant()
assert options == controller.featureNames
original_id, original_defaults = controller.sourceId, controller.defaults
controller._source_id = 'b' * 64
controller._defaults = {**original_defaults, 'data_id': controller._source_id}
controller.changed.emit(); app.processEvents()
assert settings.property('dataId') == 'b' * 64
controller._source_id, controller._defaults = 'c' * 64, {}
controller.changed.emit(); app.processEvents()
assert settings.property('dataId') == 'c' * 64
assert find('intradayResearchTrainEnd').property('text') == ''
assert find('intradayResearchFeatures').property('text') == 'return_2'
controller._source_id, controller._defaults = original_id, original_defaults
controller.changed.emit(); app.processEvents()
assert settings.property('dataId') == original_id
assert session.i18n.setLanguage('zh-CN')
choose('intradayResearchCandidate', 2); choose('intradayResearchView', 2)
assert window.grabWindow().save(str(root / 'intraday-research-ui.png'))
assert session.runtime.backend_if_initialized is None and session.runtime.shutdown()
engine.deleteLater(); app.processEvents()
print('REAL_INTRADAY_RESEARCH_WORKFLOW_OK')
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(data.path)], cwd=ROOT,
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software", "PYTHONPATH": str(ROOT / "src")},
                            capture_output=True, text=True, timeout=360)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "REAL_INTRADAY_RESEARCH_WORKFLOW_OK" in result.stdout
    assert "ReferenceError" not in result.stderr and "TypeError" not in result.stderr
