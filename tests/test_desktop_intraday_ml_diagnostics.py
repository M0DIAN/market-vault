"""Real native source admission, ML evidence, captured inputs and compact use."""

from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys

import pytest

# Qt-free CI must skip before building the real immutable market-data fixtures.
pytest.importorskip("PySide6")

from market_vault.research import intraday_inner_selection as inner
from market_vault.research import intraday_research as research
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.strategy_experiment import write_strategy_experiment
from test_strategy_intraday_ml import quadratic_dev_case  # noqa: F401
from test_strategy_intraday_inner_selection import inner_case  # noqa: F401
from test_strategy_intraday_threshold_selection import threshold_case  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]


def test_native_ml_sources_quality_evidence_recovery_stale_and_compact(
        quadratic_dev_case, inner_case, threshold_case, tmp_path):
    data, plan, _, _, _, _ = quadratic_dev_case
    _, _, ordinary_path, _, _, inner_path = inner_case
    _, _, _, _, _, threshold_path = threshold_case
    short_plan = deepcopy(plan)
    short_plan["walk_forward"]["minimum_train_days"] = 14
    short_plan["strategies"] = [short_plan["strategies"][0]]
    short = create_intraday_experiment(plan=short_plan, report=research.run_intraday_research(short_plan))
    short_path = write_strategy_experiment(short, path=tmp_path / "short-source.json").path
    unavailable = inner.run_intraday_inner_selection(short_path, expected_experiment_id=short.experiment_id,
        cost_index=0, candidate_index=0, expected_candidate_id=short.as_dict()["report"]["groups"][0]["results"][0]["candidate_id"])
    unavailable_path = write_strategy_experiment(unavailable, path=tmp_path / "unavailable.json").path
    (tmp_path / "settings.yaml").write_text("storage:\n  root_dir: ./data\n")
    script = r'''
import json, sys, time, threading
from pathlib import Path
from PySide6.QtCore import QObject, QUrl, Qt, QEvent, QMetaObject, QPointF
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtQml import QQmlApplicationEngine, QJSValue
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from market_vault.application import build_application_context
from market_vault.desktop.bootstrap import create_qml_application_session
from market_vault.desktop.preferences import DesktopPreferenceStore
from market_vault.desktop.localization import translation_keys_match
from market_vault.research import intraday_ml_diagnostics as diagnostics

root, ordinary_path, inner_path, threshold_path, unavailable_path, data_path = map(Path, sys.argv[1:])
paths = (ordinary_path, inner_path, threshold_path, unavailable_path, data_path)
original_bytes = {path: path.read_bytes() for path in paths}
relocated = root / 'relocated-q5.json'
relocated.write_bytes(data_path.read_bytes())
assert translation_keys_match()
QQuickStyle.setStyle('Basic')
app = QGuiApplication([])
engine = QQmlApplicationEngine()
warnings = []
engine.warnings.connect(lambda messages: warnings.extend(message.toString() for message in messages))
session = create_qml_application_session(build_application_context(root / 'settings.yaml'), engine,
    preference_store=DesktopPreferenceStore(root=root / 'preferences'))
engine.load(QUrl.fromLocalFile(str(Path.cwd() / 'src/market_vault/desktop/qml/Main.qml')))
assert engine.rootObjects(), warnings
window = engine.rootObjects()[0]
window.setWidth(1200); window.setHeight(1000)
controller = session.context_properties['quantResearchController'].intradayMLDiagnosticsController
assert session.i18n.setLanguage('en')
assert session.shell.selectPage('quant_research')

def find(name):
    result = window.findChild(QObject, name)
    if result is not None: return result
    pending = [window.contentItem()]
    while pending:
        obj = pending.pop()
        if obj.objectName() == name: return obj
        pending.extend(obj.childItems())
    raise AssertionError(name)

def click_obj(obj):
    app.processEvents()
    assert obj.property('visible') and obj.property('enabled'), obj.objectName()
    point = obj.mapToScene(obj.boundingRect().center()).toPoint()
    assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), (obj.objectName(), point)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    app.processEvents()

def click(name): click_obj(find(name))

def nested(obj, kind):
    if kind in obj.metaObject().className(): return obj
    return next(child for child in obj.findChildren(QObject) if kind in child.metaObject().className())

def choose(name, index):
    obj = find(name)
    window.requestActivate(); QTest.qWait(20)
    combo = nested(obj, 'PixelComboBox'); combo.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_Home)
    for _ in range(index): QTest.keyClick(window, Qt.Key_Down)
    app.processEvents()
    assert obj.property('currentIndex') == index, (name, obj.property('currentIndex'))

def fill(name, value):
    obj = find(name)
    window.requestActivate(); QTest.qWait(20)
    nested(obj, 'PixelTextField').forceActiveFocus()
    QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClick(window, Qt.Key_Backspace)
    for char in str(value):
        QGuiApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, ord(char.upper()), Qt.NoModifier, char))
    app.processEvents()
    assert obj.property('text') == str(value)

def complete(status='SUCCESS'):
    deadline = time.monotonic() + 90
    while controller.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    app.processEvents()
    assert not controller.busy and controller.status == status, (controller.status, controller.error, warnings)

def open_source(path):
    click('intradayMLSourceBrowse')
    dialog = find('intradayMLSourceDialog')
    assert dialog.setProperty('selectedFile', QUrl.fromLocalFile(str(path)))
    assert QMetaObject.invokeMethod(dialog, 'accepted', Qt.DirectConnection)
    QMetaObject.invokeMethod(dialog, 'close', Qt.DirectConnection)
    complete()

def evidence():
    click('intradayMLEvidenceButton')
    text = find('intradayMLEvidenceText')
    assert text.property('readOnly') and text.property('selectByMouse')
    assert engine.newQObject(text).property('wrapMode').toInt() != 0
    result = json.loads(text.property('text'))
    QTest.keyClick(window, Qt.Key_Escape); app.processEvents()
    assert not find('intradayMLEvidenceDialog').property('visible')
    return result

def displayed(value):
    return find('intradayMLTable').property('cellFormatter').call([QJSValue(value)]).toString()

# One real API boundary, called on the worker, supplies every completed view.
actual, calls = diagnostics.analyze_intraday_ml_prediction_quality, []
gui_thread = threading.get_ident()
def measured(*args, **kwargs):
    assert threading.get_ident() != gui_thread
    result = actual(*args, **kwargs)
    calls.append((args[0].experiment_id, kwargs, result))
    return result
diagnostics.analyze_intraday_ml_prediction_quality = measured
click('quantIntradayTab'); click('intradayMLDiagnosticsTab'); QTest.qWait(50)
open_source(ordinary_path)
assert not calls and not controller.resultLoaded and controller.ordinarySource
choose('intradayMLCost', 1); choose('intradayMLCandidate', 1)
fill('intradayMLDataPath', relocated)
click('intradayMLRunButton'); complete()
report = controller._report
assert report == calls[-1][2] and report['source_kind'] == 'ORDINARY'
assert report['source_selection']['cost_index'] == report['source_selection']['candidate_index'] == 1
assert calls[-1][1]['cost_index'] == calls[-1][1]['candidate_index'] == 1
assert report['folds'][0]['model']['kind'] == 'QUADRATIC_BASIS_RIDGE'
assert report['source_locator']['used'] == str(relocated) and report['source_locator']['override_used']
details = json.loads(controller.completedDetails)
assert details['requested_cost_index'] == details['requested_candidate_index'] == 1
assert details['source_experiment_id'] == report['experiment_id']
assert details['method'] == report['method'] and details['context'] == report['context']
assert [row['forecast'] for row in report['forecasts']] == ['SELECTED', 'FIXED_REFERENCE', 'ZERO', 'TRAIN_MEAN']
assert not controller.draftChanged
assert displayed('mse') != 'mse' and displayed('BIN_1') == '0 < score ≤ 5 bp'
assert evidence()['rows'][0]['complete_metric'] == next(iter(report['forecasts'][0]['metrics'].values()))
assert window.grabWindow().save(str(root / 'q33-native-quality-en.png'))

view_calls = len(calls)
choose('intradayMLView', 1)
assert len(report['bins']) == 5
assert {row['ml_bin'] for row in controller._evidence_rows} == {'BIN_' + str(i) for i in range(5)}
assert evidence()['rows'][0]['complete_bin'] == report['bins'][0]
choose('intradayMLScope', 1)
assert evidence()['complete_fold_evidence'] == report['folds'][0]
choose('intradayMLView', 4)
page = evidence()
assert page['complete_fold_evidence']['model'] == report['folds'][0]['model']
assert page['complete_fold_evidence']['reference_model'] == report['folds'][0]['reference_model']
assert report['folds'][0]['training_keys'][0] in json.dumps(page)
click('intradayMLEvidenceButton')
text = find('intradayMLEvidenceText').property('text')
assert report['folds'][0]['model_id'] in text
assert find('intradayMLEvidenceScroll').property('contentItem').property('contentHeight') > find('intradayMLEvidenceScroll').property('availableHeight')
assert window.grabWindow().save(str(root / 'q33-native-model-evidence.png'))
QTest.keyClick(window, Qt.Key_Escape); app.processEvents()
choose('intradayMLScope', 0); choose('intradayMLView', 3)
assert controller.tableModel.totalRows == len(report['predictions'])
assert controller.tableModel.totalRows == report['sample']['prediction_count']
assert report['sample']['incomplete_target_count'] > 0
assert [row['complete_prediction'] for row in evidence()['rows']] == report['predictions'][:100]
assert len(calls) == view_calls

# Failed opens and computations leave the complete prior result available.
before = controller._report
fill('intradayMLSourcePath', root / 'missing-source.json')
click('intradayMLOpenButton'); complete('FAILED')
assert controller._report == before and controller.studyError and not controller.canRun
open_source(ordinary_path)
choose('intradayMLCost', 1); choose('intradayMLCandidate', 1)
fill('intradayMLDataPath', root / 'missing-q5.json')
click('intradayMLRunButton'); complete('FAILED')
assert controller._report == before and controller.studyError and controller.draftChanged
fill('intradayMLDataPath', relocated)
click('intradayMLRunButton'); complete()
assert not controller.studyError and not controller.draftChanged and controller._report == before

# Each input is independently edited and restored while a real result awaits
# delivery. Revision tracking must reject even this return-to-original draft.
for changed_input in ('candidate', 'source', 'data'):
    ready, release = threading.Event(), threading.Event()
    def delayed(*args, **kwargs):
        result = measured(*args, **kwargs)
        ready.set()
        assert release.wait(30)
        return result
    diagnostics.analyze_intraday_ml_prediction_quality = delayed
    click('intradayMLRunButton')
    deadline = time.monotonic() + 90
    while not ready.is_set() and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    assert ready.is_set()
    if changed_input == 'candidate':
        choose('intradayMLCandidate', 0); choose('intradayMLCandidate', 1)
    elif changed_input == 'source':
        previous = controller.sourcePath
        fill('intradayMLSourcePath', root / 'other-source.json'); fill('intradayMLSourcePath', previous)
    else:
        fill('intradayMLDataPath', root / 'other-q5.json'); fill('intradayMLDataPath', relocated)
    release.set(); complete()
    diagnostics.analyze_intraday_ml_prediction_quality = measured
    assert controller.notice == 'STALE_INPUT' and controller._report == before, changed_input
    assert json.loads(controller.completedDetails)['requested_candidate_index'] == 1

# Both saved procedures use their one complete outer account, with their
# original nonzero fixed-reference indices preserved in completed evidence.
for source_path, kind in ((inner_path, 'INNER_MODEL_SELECTION'), (threshold_path, 'ECONOMIC_THRESHOLD_SELECTION')):
    open_source(source_path)
    assert not controller.ordinarySource and controller.costIndex == controller.candidateIndex == 0
    assert controller.costNames == [] and controller.candidateNames == []
    click('intradayMLRunButton'); complete()
    report = controller._report
    assert report['source_kind'] == kind and report['evidence']['execution_replayed']
    assert report['cost_index'] == report['candidate_index'] == 0
    assert report['sample']['prediction_count'] == len(report['context']['validation_keys'])
    assert not controller.notice and not controller.draftChanged
    assert all(row['trading_day'] not in report['context']['split']['TEST'] for row in report['predictions'])
    assert json.loads(controller.completedDetails)['source_path'] == str(source_path)
    if kind == 'INNER_MODEL_SELECTION':
        assert report['source_selection']['cost_index'] == report['source_selection']['candidate_index'] == 1
    else:
        assert report['forecasts'][0]['metrics'] == report['forecasts'][1]['metrics']
        assert any(row['decision'] != row['reference_decision'] for row in report['predictions'])
        assert 'raw forecasts and prediction errors match' in find('intradayMLInterpretation').property('text')
choose('intradayMLView', 1)
view_calls = len(calls)
assert session.i18n.setLanguage('zh-CN')
assert displayed('BIN_1') == '0 < 分数 ≤ 5 bp'
assert find('intradayMLView').property('currentIndex') == 1
assert find('intradayMLDiagnosticsTab').property('text') == 'ML 诊断'
assert window.grabWindow().save(str(root / 'q33-native-bands-zh.png'))
assert len(calls) == view_calls
assert session.i18n.setLanguage('en')

# Compact viewport retains a real scroll route to the full model/key pages.
# This compact real source has fewer than 100 predictions, but hundreds of
# complete training keys; pagination is exercised without inflating its data.
choose('intradayMLView', 4)
expected_page = controller._evidence_rows[100:200]
window.setWidth(1024); window.setHeight(600); QTest.qWait(100)
scroll = find('intradayMLScroll')
flick = scroll.property('contentItem')
assert flick.property('contentHeight') > scroll.property('availableHeight')
bar = find('intradayMLScrollBar')
thumb = bar.property('contentItem')
start = thumb.mapToScene(thumb.boundingRect().center()).toPoint()
end = bar.mapToScene(QPointF(bar.width() / 2, bar.height() - 2)).toPoint()
QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
QTest.mouseMove(window, end, 50)
QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
QTest.qWait(50)
assert flick.property('contentY') > 0
pagination = nested(find('intradayMLTable'), 'PixelPagination')
next_button = next(child for child in pagination.findChildren(QObject) if child.property('glyph') == 'next')
assert controller.tableModel.page == 1 and controller.tableModel.hasNext
click_obj(next_button)
assert controller.tableModel.page == 2
assert json.loads(controller.currentPageEvidence)['rows'] == expected_page
assert json.loads(controller.currentPageEvidence)['complete_fold_evidence']
assert window.grabWindow().save(str(root / 'q33-native-compact-keys.png'))

# A real unavailable study is a completed, explicit unavailable result.
window.setWidth(1200); window.setHeight(1000); QTest.qWait(50)
flick.setProperty('contentY', 0); app.processEvents()
open_source(unavailable_path)
click('intradayMLRunButton'); complete()
assert controller.resultSummary['status'] == 'UNAVAILABLE' and controller.resultSummary['sample'] is None
assert controller._report['evidence']['scope'] == 'RECORDED_UNAVAILABLE_SOURCE'
assert controller.tableModel.totalRows == 0 and controller.foldCount == 0
assert 'Unavailable' in find('intradayMLSummary').property('text')
assert json.loads(controller.completedDetails)['unavailable_reasons']
assert not controller.studyError
assert all(path.read_bytes() == content for path, content in original_bytes.items())
assert not any('IntradayMLDiagnosticsPanel' in warning or 'IntradayWorkspacePanel' in warning for warning in warnings), warnings
diagnostics.analyze_intraday_ml_prediction_quality = actual
assert session.shutdown()
engine.deleteLater(); app.processEvents()
print('NATIVE_ML_DIAGNOSTICS_PASS')
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(ordinary_path), str(inner_path),
        str(threshold_path), str(unavailable_path), str(data.path)], cwd=ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software", "PYTHONPATH": str(ROOT / "src")},
        text=True, capture_output=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NATIVE_ML_DIAGNOSTICS_PASS" in result.stdout
