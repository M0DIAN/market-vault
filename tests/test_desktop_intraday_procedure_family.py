"""Native complete-family inputs, completed-mode semantics and recovery."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

# Keep Qt-free shards from building otherwise shared saved studies.
pytest.importorskip("PySide6")

from market_vault.research.intraday_procedure_comparison import compare_intraday_procedures
from market_vault.research.intraday_procedure_family import analyze_intraday_procedure_family
from market_vault.research.strategy_experiment import canonical_json, write_strategy_experiment
from test_intraday_ml_procedures_comparison import reseal_procedure_benchmark


ROOT = Path(__file__).resolve().parents[1]


def test_native_three_procedure_family_mode_identity_evidence_and_recovery(procedure_comparison_case, tmp_path):
    case = procedure_comparison_case
    snapshots = tuple(case.studies[name][0] for name in ("q25", "q31", "q36"))
    for name, snapshot in zip(("q25", "q31", "q36"), snapshots, strict=True):
        (tmp_path / (name + ".json")).write_bytes(snapshot.content)
    (tmp_path / "expected.json").write_bytes(canonical_json(analyze_intraday_procedure_family(snapshots)))
    (tmp_path / "pair-expected.json").write_bytes(canonical_json(compare_intraday_procedures(*snapshots[:2])))

    def price(execution, reference):
        execution["ledger"][0]["mark_price"] += 1
    for name, snapshot in zip(("q25", "q31", "q36"), snapshots, strict=True):
        altered = reseal_procedure_benchmark(snapshot, price)
        write_strategy_experiment(altered, path=tmp_path / ("blocked-" + name + ".json"))
    (tmp_path / "settings.yaml").write_text("storage:\n  root_dir: ./data\n")
    script = r'''
import json, sys, time, threading
from pathlib import Path
import pytest
from PySide6.QtCore import QObject, QUrl, Qt, QEvent, QMetaObject, QPointF
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtQml import QQmlApplicationEngine, QJSValue
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from market_vault.application import build_application_context
from market_vault.desktop.bootstrap import create_qml_application_session
from market_vault.desktop.preferences import DesktopPreferenceStore
from market_vault.desktop.localization import translation_keys_match
from market_vault.research import intraday_procedure_family as family
from market_vault.research import strategy_experiment as experiments
from test_intraday_ml_procedures_comparison import _no_recompute

root = Path(sys.argv[1])
paths = {name: root / (name + '.json') for name in ('q25', 'q31', 'q36', 'blocked-q25', 'blocked-q31', 'blocked-q36')}
original = {path: path.read_bytes() for path in paths.values()}
expected = json.loads((root / 'expected.json').read_bytes())
pair_expected = json.loads((root / 'pair-expected.json').read_bytes())
assert translation_keys_match()
QQuickStyle.setStyle('Basic')
app = QGuiApplication([])
engine = QQmlApplicationEngine()
warnings = []
engine.warnings.connect(lambda values: warnings.extend(value.toString() for value in values))
session = create_qml_application_session(build_application_context(root / 'settings.yaml'), engine,
    preference_store=DesktopPreferenceStore(root=root / 'preferences'))
engine.load(QUrl.fromLocalFile(str(Path.cwd() / 'src/market_vault/desktop/qml/Main.qml')))
assert engine.rootObjects(), warnings
window = engine.rootObjects()[0]
window.setWidth(1280); window.setHeight(1100)
owner = session.context_properties['quantResearchController']
controller = owner.intradayProcedureComparisonController
assert session.i18n.setLanguage('en') and session.shell.selectPage('quant_research')
patch = pytest.MonkeyPatch(); _no_recompute(patch)

def find(name):
    result = window.findChild(QObject, name)
    if result is not None: return result
    pending = [window.contentItem()]
    while pending:
        item = pending.pop()
        if item.objectName() == name: return item
        pending.extend(item.childItems())
    raise AssertionError(name)

def nested(obj, kind):
    if kind in obj.metaObject().className(): return obj
    return next(child for child in obj.findChildren(QObject) if kind in child.metaObject().className())

def reveal(obj):
    app.processEvents()
    scroll = find('intradayProcedureScroll')
    if not scroll.property('visible'): return
    flick = scroll.property('contentItem')
    top = scroll.mapToScene(QPointF(0, 0)).y()
    center = obj.mapToScene(obj.boundingRect().center()).y()
    height = scroll.property('availableHeight')
    if center < top + 10 or center > top + height - 10:
        target = flick.property('contentY') + center - top - height / 2
        flick.setProperty('contentY', max(0, min(target, flick.property('contentHeight') - height)))
        app.processEvents()

def click_obj(obj, scroll=True):
    if scroll: reveal(obj)
    app.processEvents()
    assert obj.property('visible') and obj.property('enabled'), obj.objectName()
    point = obj.mapToScene(obj.boundingRect().center()).toPoint()
    assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), (obj.objectName(), point)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    app.processEvents()

def click(name): click_obj(find(name))

def choose(name, index):
    obj = find(name); reveal(obj)
    window.requestActivate(); QTest.qWait(20)
    combo = nested(obj, 'PixelComboBox'); combo.forceActiveFocus()
    if obj.property('currentIndex') != index:
        QTest.keyClick(window, Qt.Key_Space)
        assert combo.property('down')
        QTest.keyClick(window, Qt.Key_Home)
        for _ in range(index): QTest.keyClick(window, Qt.Key_Down)
        QTest.keyClick(window, Qt.Key_Return)
    app.processEvents()
    assert obj.property('currentIndex') == index, (name, obj.property('currentIndex'))

def fill(name, value):
    obj = find(name); reveal(obj)
    window.requestActivate(); QTest.qWait(20)
    nested(obj, 'PixelTextField').forceActiveFocus()
    QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClick(window, Qt.Key_Backspace)
    for char in str(value):
        QGuiApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, ord(char.upper()), Qt.NoModifier, char))
    app.processEvents()
    assert obj.property('text') == str(value)

def complete(status='SUCCESS'):
    deadline = time.monotonic() + 60
    while controller.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    app.processEvents()
    assert not controller.busy and controller.status == status, (controller.status, controller.error, warnings)

def browse(side, path):
    click('intradayProcedure' + side + 'Browse')
    dialog = find('intradayProcedure' + side + 'Dialog')
    assert dialog.property('visible')
    assert dialog.setProperty('selectedFile', QUrl.fromLocalFile(str(path)))
    assert QMetaObject.invokeMethod(dialog, 'accepted', Qt.DirectConnection)
    QMetaObject.invokeMethod(dialog, 'close', Qt.DirectConnection)
    app.processEvents()
    assert not controller.busy

def evidence():
    click('intradayProcedureEvidenceButton')
    assert find('intradayProcedureEvidenceDialog').property('visible')
    result = json.loads(find('intradayProcedureEvidenceText').property('text'))
    QTest.keyClick(window, Qt.Key_Escape); app.processEvents()
    assert find('intradayProcedureEvidenceText').property('text') == ''
    return result

def displayed(value):
    return find('intradayProcedureTable').property('cellFormatter').call([QJSValue(value)]).toString()

click('quantIntradayTab'); click('intradayProcedureTab'); QTest.qWait(30)
assert controller.modeIndex == 0 and not find('intradayProcedureThirdRow').property('visible')
browse('Left', paths['q25']); browse('Right', paths['q31'])
click('intradayProcedureOpenPairButton'); complete()
click('intradayProcedureRunButton'); complete()
assert controller._report == pair_expected and not controller.completedFamily
pair_bound = controller.boundSources
choose('intradayProcedureMode', 1)
assert find('intradayProcedureThirdRow').property('visible')
assert controller.familyMode and not controller.completedFamily and not controller.canRun
assert controller._report == pair_expected and controller.boundSources == pair_bound
assert controller.viewOptions[0] == 'intervals'
assert 'B − A is an arithmetic daily return difference' in find('intradayProcedureInterpretation').property('text')
assert 'not a fourth family member' in find('intradayProcedureMethod').property('text')
browse('Left', paths['q36']); browse('Right', paths['q25']); browse('Third', paths['q31'])
assert not controller.thirdSource and not controller.canRun
click('intradayProcedureOpenPairButton'); complete()
assert controller.canRun and controller.thirdSource['source_kind'] == 'ECONOMIC_THRESHOLD_SELECTION'
# Compare uses captured originals even when one on-disk source changes.
paths['q31'].write_bytes(b'changed after explicit Open')
loader = experiments.load_strategy_experiment
experiments.load_strategy_experiment = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('family reopened a saved source'))
click('intradayProcedureRunButton'); complete()
experiments.load_strategy_experiment = loader
paths['q31'].write_bytes(original[paths['q31']])
assert controller._report == expected and controller.completedFamily and not controller.draftChanged
bound = controller.boundSources
assert [source['role'] for source in bound] == ['Q25', 'Q31', 'Q36']
assert [source['input_slot'] for source in bound] == ['B', 'C', 'A']
assert [source['experiment_id'] for source in bound] == [member['experiment_id'] for member in expected['members']]
assert controller.resultSummary['family_size'] == 3
assert controller.resultSummary['historical_search_coverage'] == 'UNKNOWN'
assert controller.resultSummary['sampling']['replications'] == 5000 and controller.resultSummary['sampling']['seed'] == 0
assert float(controller.resultSummary['deduction_display']) == pytest.approx(expected['family_inference']['deduction'] * 100, rel=1e-5)
assert controller.tableModel.totalRows == 3
for row, raw in zip(controller._evidence_rows, expected['statistics'], strict=True):
    assert row['complete_record'] == raw and row['unit'] == 'PERCENTAGE_POINTS'
    assert float(row['family_mean_excess']) == pytest.approx(raw['mean_excess'] * 100, rel=1e-5)
    assert float(row['family_lower_95']) == pytest.approx(raw['lower'] * 100, rel=1e-5)
assert displayed('PERCENTAGE_POINTS') == 'pp'
assert 'constant columns and every declared member' in find('intradayProcedureInterpretation').property('text')
assert window.grabWindow().save(str(root / 'q40-native-family-en.png'))
print('NATIVE_FAMILY_BOUNDS_COMPLETE', flush=True)

choose('intradayProcedureView', 1)
assert controller.tableModel.totalRows == 100
assert [row['complete_record'] for row in evidence()['rows']] == expected['daily']
assert all('%' not in row['family_q25_excess'] for row in controller._evidence_rows)
choose('intradayProcedureView', 2)
assert controller.memberOptions == ['ALL_FAMILY', 'Q25', 'Q31', 'Q36']
assert [row['complete_record'] for row in controller._evidence_rows] == [fold for member in expected['members'] for fold in member['outer_folds']]
choose('intradayProcedureMember', 3)
assert [row['complete_record'] for row in evidence()['rows']] == expected['members'][2]['outer_folds']
assert all(row['model_id'] and row['strategy_kind'] for row in controller._evidence_rows)
choose('intradayProcedureView', 3)
assert controller.memberOptions == ['ALL_FAMILY', 'Q25', 'Q31', 'Q36', 'FAMILY_REFERENCE', 'FAMILY_BENCHMARK']
choose('intradayProcedureMember', 4)
assert 'outside family' in find('intradayProcedureMember').property('currentText')
choose('intradayProcedureSection', controller.sectionOptions.index('execution.daily'))
actual = evidence()['rows']
assert [row['complete_record'] for row in actual] == expected['reference']['account']['execution']['daily']
assert all(row['record_path'].startswith('/reference/account/execution/daily/') for row in actual)
choose('intradayProcedureMember', 5)
choose('intradayProcedureSection', controller.sectionOptions.index('execution.policy'))
actual = evidence()['rows']
assert {row['record_path'].split('/')[-1]: row['complete_record'] for row in actual} == expected['benchmark']['execution']['policy']
choose('intradayProcedureView', 2)
assert controller.memberIndex == 0 and controller.tableModel.totalRows == 12
choose('intradayProcedureView', 4)
assert controller.tableModel.totalRows == 3 + sum(len(member['checks']) for member in expected['basis']['members'])
assert {row['account_role'] for row in controller._evidence_rows} == {'ALL_FAMILY', 'Q25', 'Q31', 'Q36'}
choose('intradayProcedureView', 0)
click('intradayProcedureReportButton')
details = json.loads(find('intradayProcedureReportText').property('text'))
assert details['family_bounds_id'] == expected['family_bounds_id'] and details['sources'] == bound
assert details['family_inference'] == expected['family_inference'] and 'account' not in details['reference']
click_obj(find('intradayProcedureCopyReportButton'), scroll=False)
assert json.loads(QGuiApplication.clipboard().text()) == expected
QTest.keyClick(window, Qt.Key_Escape); app.processEvents()
assert find('intradayProcedureReportText').property('text') == ''
assert session.i18n.setLanguage('zh-CN')
assert displayed('PERCENTAGE_POINTS') == '百分点'
assert '不是第四个族内成员' in find('intradayProcedureMethod').property('text')
assert '共同扣减量' in find('intradayProcedureSummary').property('text')
assert window.grabWindow().save(str(root / 'q40-native-family-zh.png'))
click('intradayMLDiagnosticsTab'); click('intradayProcedureTab')
assert controller._report == expected and controller.boundSources == bound and not controller.draftChanged
assert session.i18n.setLanguage('en')
choose('intradayProcedureMode', 0)
assert not controller.familyMode and controller.completedFamily and controller.draftChanged
assert controller.viewOptions[0] == 'family_bounds'
assert 'all three one-sided 95% lower bounds' in find('intradayProcedureInterpretation').property('text')
assert controller._report == expected and controller.boundSources == bound
choose('intradayProcedureMode', 1)
# Reordered slots produce exactly the same canonical report and fresh bindings.
for side, name in (('Left', 'q25'), ('Right', 'q31'), ('Third', 'q36')):
    fill('intradayProcedure' + side + 'Path', paths[name])
click('intradayProcedureOpenPairButton'); complete()
click('intradayProcedureRunButton'); complete()
assert controller._report == expected and [row['input_slot'] for row in controller.boundSources] == ['A', 'B', 'C']
bound = controller.boundSources
print('NATIVE_FAMILY_EVIDENCE_COMPLETE', flush=True)

# Duplicates remain visible input errors; a failed open never partly applies
# a different group and a source mismatch keeps the last completed report.
fill('intradayProcedureThirdPath', paths['q25'])
click('intradayProcedureOpenThirdButton'); complete()
assert controller.inputReason == 'COMPLETE_FAMILY_REQUIRED' and not controller.canRun
assert controller._report == expected and controller.boundSources == bound
fill('intradayProcedureThirdPath', root / 'missing.json')
click('intradayProcedureOpenPairButton'); complete('FAILED')
assert controller.studyError and controller._report == expected
fill('intradayProcedureThirdPath', paths['blocked-q36'])
click('intradayProcedureOpenThirdButton'); complete()
click('intradayProcedureRunButton'); complete('FAILED')
assert 'same complete ordinary source' in controller.studyError
assert controller._report == expected and controller.boundSources == bound
fill('intradayProcedureThirdPath', paths['q36'])
click('intradayProcedureOpenThirdButton'); complete()

real = family.analyze_intraday_procedure_family
def pending_family():
    ready, release, calls = threading.Event(), threading.Event(), []
    def delayed(snapshots, **kwargs):
        calls.append(tuple(snapshot.content for snapshot in snapshots))
        result = real(snapshots, **kwargs)
        ready.set(); assert release.wait(30)
        return result
    family.analyze_intraday_procedure_family = delayed
    click('intradayProcedureRunButton')
    deadline = time.monotonic() + 60
    while not ready.is_set() and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    assert ready.is_set()
    return release, calls

# Changing only the method must invalidate an in-flight family completion.
release, calls = pending_family()
choose('intradayProcedureMode', 0)
release.set(); complete()
family.analyze_intraday_procedure_family = real
assert calls == [tuple(original[paths[name]] for name in ('q25', 'q31', 'q36'))]
assert controller.notice == 'STALE_INPUT' and controller._report == expected and controller.completedFamily
assert controller.boundSources == bound and controller.viewOptions[0] == 'family_bounds'
choose('intradayProcedureMode', 1)
# Editing only C must also invalidate the completion; its bytes were captured.
release, calls = pending_family()
fill('intradayProcedureThirdPath', root / 'changed-while-running.json')
release.set(); complete()
family.analyze_intraday_procedure_family = real
assert controller.notice == 'STALE_INPUT' and not controller.canRun
assert controller._report == expected and controller.boundSources == bound
fill('intradayProcedureThirdPath', paths['q36'])
click('intradayProcedureRunButton'); complete()
assert controller._report == expected and not controller.draftChanged and not controller.studyError and not controller.notice
assert not owner.intradayFinalController.selectionLoaded
print('NATIVE_FAMILY_RECOVERY_COMPLETE', flush=True)

choose('intradayProcedureView', 3); choose('intradayProcedureMember', 3)
choose('intradayProcedureSection', controller.sectionOptions.index('execution.ledger'))
window.setWidth(1024); window.setHeight(600); QTest.qWait(100)
scroll = find('intradayProcedureScroll'); flick = scroll.property('contentItem')
assert flick.property('contentHeight') > scroll.property('availableHeight')
bar = find('intradayProcedureScrollBar'); thumb = bar.property('contentItem')
start = thumb.mapToScene(thumb.boundingRect().center()).toPoint()
end = bar.mapToScene(QPointF(bar.width() / 2, bar.height() - 2)).toPoint()
QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
QTest.mouseMove(window, end, 50)
QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
QTest.qWait(50)
assert flick.property('contentY') > 0
pagination = nested(find('intradayProcedureTable'), 'PixelPagination')
next_button = next(child for child in pagination.findChildren(QObject) if child.property('glyph') == 'next')
assert controller.tableModel.page == 1 and controller.tableModel.hasNext
click_obj(next_button, scroll=False)
assert controller.tableModel.page == 2
assert [row['complete_record'] for row in json.loads(controller.currentPageEvidence)['rows']] == expected['members'][2]['selected_account']['execution']['ledger'][100:200]
assert window.grabWindow().save(str(root / 'q40-native-family-compact.png'))

# Invalid shared account evidence does not shrink the family or replace
# unavailable lower bounds with zeros. All three declared rows remain.
window.setWidth(1280); window.setHeight(1100); QTest.qWait(50)
for side, name in (('Left', 'blocked-q25'), ('Right', 'blocked-q31'), ('Third', 'blocked-q36')):
    fill('intradayProcedure' + side + 'Path', paths[name])
click('intradayProcedureOpenPairButton'); complete()
click('intradayProcedureRunButton'); complete()
assert controller.resultSummary['status'] == 'UNAVAILABLE'
assert controller.resultSummary['family_size'] == 3
assert controller.resultSummary['family_inference']['status'] == 'UNAVAILABLE'
choose('intradayProcedureView', 0)
assert controller.tableModel.totalRows == 3
assert all(row['family_mean_excess'] == row['family_lower_95'] == '—' for row in controller._evidence_rows)
assert all(row['bound_unavailable_reason'] != '—' for row in controller._evidence_rows)
assert [row['family_role'] for row in controller._evidence_rows] == ['Q25', 'Q31', 'Q36']
assert 'undefined' not in find('intradayProcedureSummary').property('text')
assert window.grabWindow().save(str(root / 'q40-native-family-unavailable.png'))
# Returning to A/B ignores the draft C source and replaces completed family
# roles only after a successful explicit two-source analysis.
choose('intradayProcedureView', 3); choose('intradayProcedureMember', 5)
choose('intradayProcedureMode', 0)
assert controller.completedFamily and controller.memberIndex == 5
fill('intradayProcedureLeftPath', paths['q25']); fill('intradayProcedureRightPath', paths['q31'])
click('intradayProcedureOpenPairButton'); complete()
click('intradayProcedureRunButton'); complete()
assert controller._report == pair_expected and not controller.completedFamily and not controller.draftChanged
assert controller.memberIndex == 0 and controller.memberOptions == ['ALL', 'A', 'B']
assert [row['role'] for row in controller.boundSources] == ['A', 'B']
choose('intradayProcedureView', 0)
assert controller.viewOptions[0] == 'intervals'
assert [row['complete_record'] for row in controller._evidence_rows] == pair_expected['statistics']
assert all(path.read_bytes() == content for path, content in original.items())
(root / 'q40-native-warnings.json').write_text(json.dumps(warnings, ensure_ascii=False, indent=2))
assert not any('IntradayProcedureComparisonPanel' in value or 'IntradayWorkspacePanel' in value for value in warnings), warnings
patch.undo()
assert session.shutdown()
engine.deleteLater(); app.processEvents()
print('NATIVE_PROCEDURE_FAMILY_PASS')
'''
    completed = subprocess.run([sys.executable, "-c", script, str(tmp_path)], cwd=ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software",
             "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT / "tests")))},
        text=True, capture_output=True, timeout=420)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "NATIVE_PROCEDURE_FAMILY_PASS" in completed.stdout
