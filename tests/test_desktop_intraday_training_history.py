"""Real QML history analysis, captured sources, recovery and compact navigation."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

from market_vault.research.strategy_experiment import canonical_json
from test_intraday_training_history import history_case, quadratic_dev_case


ROOT = Path(__file__).resolve().parents[1]


def test_native_training_history_run_views_recovery_stale_and_compact(history_case, tmp_path):
    pytest.importorskip("PySide6")
    data, _, _, _, source_path, results = history_case
    (tmp_path / "settings.yaml").write_text("storage:\n  root_dir: ./data\n")
    (tmp_path / "expected.json").write_bytes(canonical_json(results[1]))
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
from market_vault.research import intraday_training_history as history
from market_vault.desktop.localization import translation_keys_match

root, source_path, data_path = map(Path, sys.argv[1:])
source_bytes, data_bytes = source_path.read_bytes(), data_path.read_bytes()
expected = json.loads((root / 'expected.json').read_bytes())
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
window.setWidth(1200); window.setHeight(900)
owner = session.context_properties['quantResearchController']
research, controller = owner.intradayResearchController, owner.intradayTrainingHistoryController
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
    window.requestActivate(); QTest.qWait(30)
    combo = nested(obj, 'PixelComboBox'); combo.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_Home)
    for _ in range(index): QTest.keyClick(window, Qt.Key_Down)
    app.processEvents()
    assert obj.property('currentIndex') == index, (name, obj.property('currentIndex'))

def fill(name, value):
    obj = find(name)
    window.requestActivate(); QTest.qWait(30)
    nested(obj, 'PixelTextField').forceActiveFocus()
    QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClick(window, Qt.Key_Backspace)
    for char in str(value):
        QGuiApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, ord(char.upper()), Qt.NoModifier, char))
    app.processEvents()
    assert obj.property('text') == str(value)

def complete(target=controller, status='SUCCESS'):
    deadline = time.monotonic() + 60
    while target.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    app.processEvents()
    assert not target.busy and target.status == status, (target.status, target.error, warnings)

def page_evidence(screenshot=False):
    click('intradayHistoryEvidenceButton')
    assert find('intradayHistoryEvidenceDialog').property('visible')
    text = find('intradayHistoryEvidenceText').property('text')
    assert json.loads(text)
    if screenshot:
        scroll = find('intradayHistoryEvidenceScroll')
        assert scroll.property('contentItem').property('contentHeight') > scroll.property('availableHeight')
        assert window.grabWindow().save(str(root / 'q30-native-model-evidence.png'))
    QTest.keyClick(window, Qt.Key_Escape); app.processEvents()
    assert not find('intradayHistoryEvidenceDialog').property('visible')
    return text

def displayed(value):
    return find('intradayHistoryTable').property('cellFormatter').call([QJSValue(value)]).toString()

click('quantIntradayTab'); click('intradayComparisonTab'); QTest.qWait(50)
click('intradayExperimentOpenButton')
dialog = find('intradayExperimentOpenDialog')
assert dialog.setProperty('selectedFile', QUrl.fromLocalFile(str(source_path)))
assert QMetaObject.invokeMethod(dialog, 'accepted', Qt.DirectConnection)
QMetaObject.invokeMethod(dialog, 'close', Qt.DirectConnection)
complete(research)
click('intradayHistoryTab'); QTest.qWait(50)
choose('intradayHistoryCandidate', 1)
assert controller.canRun and not controller.resultLoaded
click('intradayHistoryRunButton'); complete()
assert controller._report == expected
assert controller.completedDetails['candidate_index'] == 1
assert controller.resultSummary['strategy']['kind'] == 'QUADRATIC_RIDGE'
assert controller.equityNames == ['EXPANDING', 'TRAILING_10_DAYS', 'TRAILING_20_DAYS', 'BENCHMARK']
assert len(controller.equitySeries) == 4
assert 'does not choose a window or enter TEST' in find('intradayHistoryMethod').property('text')
basis_text = find('intradayHistoryReturnBasis').property('text')
assert controller.returnBasis == expected['return_basis']
assert all(value in basis_text for value in ('NONE unadjusted', 'Split-share adjustment: Not applied',
    'Cash-dividend accounting: Not applied', 'Corporate-action coverage: Unknown'))
assert displayed('mse') != 'mse' and displayed('SQUARED_RATIO') == 'Raw return ratio²'
assert displayed('NO_COMPLETE_TARGETS') != 'NO_COMPLETE_TARGETS'
assert displayed('PERCENTAGE_POINTS') == 'Percentage points'
assert displayed('initial_cash') == 'Initial cash'
assert window.grabWindow().save(str(root / 'q30-native-overview-en.png'))
choose('intradayHistoryVariant', 1)
choose('intradayHistoryView', 1)
assert controller._columns[5:7] == ('validation_complete', 'validation_mse')
assert controller.tableModel.totalRows == len(expected['variants'][1]['folds'])
choose('intradayHistoryView', 2)
assert displayed('training_days') == 'Selected historical TRAIN days'
assert displayed('validation_keys') == 'All original outer READY validation keys'
assert expected['variants'][1]['folds'][0]['training_keys'][0] in page_evidence()
choose('intradayHistoryView', 3)
assert {row[1] for row in controller._rows} == {'INPUT_TRANSFORM', 'GENERATED_TERMS'}
model = expected['variants'][1]['folds'][0]['model']
text = page_evidence(screenshot=True)
assert all(value in text for value in (model['model_id'], model['training_boundary'], model['training_keys'][0]))
assert json.loads(text)['complete_fold_models'][0]['model'] == model
assert session.i18n.setLanguage('zh-CN')
assert find('intradayHistoryView').property('currentIndex') == 3
assert find('intradayHistoryVariant').property('currentIndex') == 1
assert displayed('training_days') == '所选历史 TRAIN 交易日'
assert displayed('validation_keys') == '全部原外折 READY 验证键'
assert 'NONE 未复权' in find('intradayHistoryReturnBasis').property('text')
assert window.grabWindow().save(str(root / 'q30-native-models-zh.png'))
assert session.i18n.setLanguage('en')
for index, field in ((4, 'predictions'), (5, 'trades'), (6, 'daily'), (7, 'ledger'), (8, 'transactions')):
    choose('intradayHistoryView', index)
    account = expected['variants'][1]['account']
    values = account[field] if field == 'predictions' else account['execution'][field]
    assert controller.tableModel.totalRows == len(values), field
choose('intradayHistoryView', 9)
assert json.loads(page_evidence())['rows'] == expected['variants'][1]['account']['fold_contributions']
choose('intradayHistoryVariant', 3)
for index, field in ((5, 'trades'), (6, 'daily'), (7, 'ledger'), (8, 'transactions')):
    choose('intradayHistoryView', index)
    values = expected['benchmark']['execution'][field]
    assert controller.tableModel.totalRows == len(values), field
    assert json.loads(page_evidence())['rows'] == values[:100], field
choose('intradayHistoryView', 9)
assert json.loads(page_evidence())['rows'] == expected['benchmark_fold_contributions']
for index in (1, 2, 3, 4):
    choose('intradayHistoryView', index)
    assert controller.tableModel.totalRows == 0
    assert 'Not applicable' in find('intradayHistoryVariantNotice').property('text')
choose('intradayHistoryVariant', 1)

before = controller._report
fill('intradayHistoryDataPath', root / 'missing-q5.json')
click('intradayHistoryRunButton'); complete(status='FAILED')
assert controller.studyError and controller._report == before and controller.draftChanged
click('intradayHistoryDataClear')
click('intradayHistoryRunButton'); complete()
assert not controller.studyError and not controller.draftChanged and controller._report == expected

# Delay delivery of an actual worker calculation, then change the real source
# combo. The completed report must keep its captured candidate and be rejected.
actual, ready, release, calls = history.analyze_intraday_training_history, threading.Event(), threading.Event(), []
def delayed(*args, **kwargs):
    calls.append(kwargs)
    result = actual(*args, **kwargs)
    ready.set()
    assert release.wait(30)
    return result
history.analyze_intraday_training_history = delayed
click('intradayHistoryRunButton')
deadline = time.monotonic() + 60
while not ready.is_set() and time.monotonic() < deadline:
    app.processEvents(); time.sleep(.01)
assert ready.is_set()
choose('intradayHistoryCandidate', 0)
release.set(); complete()
history.analyze_intraday_training_history = actual
assert calls[0]['candidate_index'] == 1
assert controller.notice == 'STALE_INPUT' and controller._report == before
assert controller.completedDetails['candidate_index'] == 1
choose('intradayHistoryCandidate', 1)
click('intradayHistoryRunButton'); complete()
assert not controller.notice and not controller.draftChanged

# The real compact panel scrolls and its ledger pagination remains clickable.
window.setWidth(1024); window.setHeight(600); QTest.qWait(100)
choose('intradayHistoryView', 7)
scroll = find('intradayHistoryScroll')
flick = scroll.property('contentItem')
assert flick.property('contentHeight') > scroll.property('availableHeight')
bar = find('intradayHistoryScrollBar')
thumb = bar.property('contentItem')
start = thumb.mapToScene(thumb.boundingRect().center()).toPoint()
end = bar.mapToScene(QPointF(bar.width() / 2, bar.height() - 2)).toPoint()
QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
QTest.mouseMove(window, end, 50)
QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
QTest.qWait(50)
assert flick.property('contentY') > 0
pagination = nested(find('intradayHistoryTable'), 'PixelPagination')
next_button = next(child for child in pagination.findChildren(QObject) if child.property('glyph') == 'next')
assert controller.tableModel.page == 1 and controller.tableModel.hasNext
click_obj(next_button)
assert controller.tableModel.page == 2
assert window.grabWindow().save(str(root / 'q30-native-compact-ledger.png'))
assert source_path.read_bytes() == source_bytes and data_path.read_bytes() == data_bytes
assert not any('IntradayTrainingHistoryPanel' in warning or 'IntradayWorkspacePanel' in warning for warning in warnings), warnings
assert session.shutdown()
engine.deleteLater(); app.processEvents()
print('NATIVE_TRAINING_HISTORY_PASS')
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(source_path), str(data.path)], cwd=ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software", "PYTHONPATH": str(ROOT / "src")},
        text=True, capture_output=True, timeout=240)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NATIVE_TRAINING_HISTORY_PASS" in result.stdout
