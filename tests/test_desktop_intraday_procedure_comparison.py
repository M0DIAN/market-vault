"""Actual native A/B entry, recorded accounts and immutable-input recovery."""

from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys

import pytest

# Qt-free shards skip before creating the shared real 100-day studies.
pytest.importorskip("PySide6")

from market_vault.research.intraday_procedure_comparison import compare_intraday_procedures
from market_vault.research import intraday_research as research
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.intraday_inner_selection import run_intraday_inner_selection
from market_vault.research.intraday_threshold_selection import run_intraday_threshold_selection
from market_vault.research.strategy_experiment import canonical_json, write_strategy_experiment
from test_intraday_ml_procedures_comparison import reseal_procedure_benchmark


ROOT = Path(__file__).resolve().parents[1]


def test_native_procedure_pair_paths_evidence_stale_recovery_and_compact(procedure_comparison_case, tmp_path):
    case = procedure_comparison_case
    for name, (snapshot, _) in case.studies.items():
        (tmp_path / (name + ".json")).write_bytes(snapshot.content)
    for name, kinds in (("expected", ("q25", "q31")), ("joint-expected", ("q31", "q36"))):
        report = compare_intraday_procedures(*(case.studies[kind][0] for kind in kinds))
        (tmp_path / (name + ".json")).write_bytes(canonical_json(report))

    def price(execution, reference):
        execution["ledger"][0]["mark_price"] += 1
    for side, kind in (("a", "q25"), ("b", "q31")):
        blocked = reseal_procedure_benchmark(case.studies[kind][0], price)
        write_strategy_experiment(blocked, path=tmp_path / ("blocked-" + side + ".json"))
    short_plan = deepcopy(case.plan)
    short_plan["walk_forward"]["minimum_train_days"] = 10
    short = create_intraday_experiment(plan=short_plan, report=research.run_intraday_research(short_plan))
    short_path = write_strategy_experiment(short, path=tmp_path / "short-source.json").path
    short_args = {"expected_experiment_id": short.experiment_id, "cost_index": 0, "candidate_index": 0,
                  "expected_candidate_id": short.as_dict()["report"]["groups"][0]["results"][0]["candidate_id"]}
    for side, run in (("a", run_intraday_inner_selection), ("b", run_intraday_threshold_selection)):
        unavailable = run(short_path, **short_args)
        write_strategy_experiment(unavailable, path=tmp_path / ("short-" + side + ".json"))
    (tmp_path / "ordinary.json").write_bytes(case.source.content)
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
from market_vault.research import intraday_procedure_comparison as comparison
from market_vault.research import strategy_experiment as experiments
from test_intraday_ml_procedures_comparison import _no_recompute

root = Path(sys.argv[1])
paths = {name: root / (name + '.json') for name in ('q25', 'q31', 'q36', 'ordinary', 'blocked-a', 'blocked-b', 'short-a', 'short-b')}
original = {path: path.read_bytes() for path in paths.values()}
expected = json.loads((root / 'expected.json').read_bytes())
joint_expected = json.loads((root / 'joint-expected.json').read_bytes())
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
window.setWidth(1280); window.setHeight(1050)
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
    text = find('intradayProcedureEvidenceText').property('text')
    result = json.loads(text)
    QTest.keyClick(window, Qt.Key_Escape); app.processEvents()
    assert find('intradayProcedureEvidenceText').property('text') == ''
    return result

def displayed(value):
    return find('intradayProcedureTable').property('cellFormatter').call([QJSValue(value)]).toString()

click('quantIntradayTab'); click('intradayProcedureTab'); QTest.qWait(30)
assert not controller.resultLoaded and not controller.canRun
assert not owner.intradayFinalController.selectionLoaded
assert 'same complete ordinary DEV source' in find('intradayProcedureMethod').property('text')
browse('Left', paths['q25']); browse('Right', paths['q31'])
assert not controller.leftSource and not controller.rightSource and not controller.canRun
click('intradayProcedureOpenPairButton'); complete()
assert controller.canRun and not controller.resultLoaded
assert controller.leftSource['source_kind'] == 'INNER_MODEL_SELECTION'
assert controller.rightSource['source_kind'] == 'ECONOMIC_THRESHOLD_SELECTION'
# A file edit after Open must never silently replace the captured snapshot.
paths['q25'].write_bytes(b'changed after Open')
loader = experiments.load_strategy_experiment
experiments.load_strategy_experiment = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('Compare reopened a saved file'))
click('intradayProcedureRunButton'); complete()
experiments.load_strategy_experiment = loader
paths['q25'].write_bytes(original[paths['q25']])
assert controller._report == expected and not controller.draftChanged
bound = controller.boundSources
assert [row['experiment_id'] for row in bound] == [row['experiment_id'] for row in expected['members']]
assert [row['path'] for row in bound] == [str(paths[name]) for name in ('q25', 'q31')]
assert controller.resultSummary['sampling']['replications'] == 5000
assert controller.resultSummary['sampling']['seed'] == 0
assert [row['complete_record'] for row in controller._evidence_rows] == expected['statistics']
assert displayed('B_MINUS_A') == 'B − A · paired daily increment'
assert displayed('RATIO') == '%' and displayed('PERCENTAGE_POINTS') == 'pp'
assert 'percentage points' in find('intradayProcedureInterpretation').property('text')
assert window.grabWindow().save(str(root / 'q39-native-summary-en.png'))
print('NATIVE_PROCEDURE_PAIR_COMPLETE', flush=True)

choose('intradayProcedureView', 1)
assert controller.tableModel.totalRows == 100
assert [row['complete_record'] for row in evidence()['rows']] == expected['daily']
choose('intradayProcedureView', 2)
assert controller.tableModel.totalRows == 8
rows = evidence()['rows']
assert [row['complete_record'] for row in rows] == [fold for member in expected['members'] for fold in member['outer_folds']]
assert all(row['model_id'] for row in rows)
assert all(row['strategy_kind'] == row['complete_record']['selected_recipe']['kind'] for row in rows)
assert any('application' in row['complete_record'] for row in rows)
choose('intradayProcedureView', 4)
assert controller.tableModel.totalRows == 3 + sum(len(member['checks']) for member in expected['basis']['members'])
assert any(row['basis_check'] == 'shared_benchmark' for row in controller._evidence_rows)

# Full evidence preserves every field, while native field filters and pages
# expose actual records without truncating or recomputing the source account.
choose('intradayProcedureView', 3)
for member_index, member in enumerate(expected['members'], 1):
    choose('intradayProcedureMember', member_index)
    for section in ('predictions', 'fold_contributions', 'execution.daily', 'execution.ledger', 'execution.transactions'):
        choose('intradayProcedureSection', controller.sectionOptions.index(section))
        actual = evidence()['rows']
        source = member['selected_account']
        for key in section.split('.'): source = source[key]
        assert controller.tableModel.totalRows == len(source)
        assert [row['complete_record'] for row in actual] == source[:100]
        assert all(row['record_path'].startswith('/members/' + str(member_index - 1) + '/selected_account/') for row in actual)
choose('intradayProcedureView', 0)
click('intradayProcedureReportButton')
assert find('intradayProcedureReportDialog').property('visible')
details = json.loads(find('intradayProcedureReportText').property('text'))
assert details['comparison_id'] == expected['comparison_id'] and details['sources'] == bound
assert details['statistics'] == expected['statistics'] and details['method'] == expected['method']
assert find('intradayProcedureReportText').property('readOnly') and find('intradayProcedureReportText').property('selectByMouse')
click_obj(find('intradayProcedureCopyReportButton'), scroll=False)
assert json.loads(QGuiApplication.clipboard().text()) == expected
QTest.keyClick(window, Qt.Key_Escape); app.processEvents()
assert find('intradayProcedureReportText').property('text') == ''

# Presentation switches retain the exact finished result and both A/B labels.
assert session.i18n.setLanguage('zh-CN')
assert find('intradayProcedureTab').property('text') == '程序对比'
assert displayed('B_MINUS_A') == 'B − A · 配对每日增量'
assert displayed('PERCENTAGE_POINTS') == '百分点'
assert controller._report == expected and controller.boundSources == bound and not controller.draftChanged
click('intradayJointTab'); click('intradayProcedureTab')
assert controller._report == expected and not controller.draftChanged
assert window.grabWindow().save(str(root / 'q39-native-summary-zh.png'))
assert session.i18n.setLanguage('en')
print('NATIVE_PROCEDURE_EVIDENCE_COMPLETE', flush=True)

# Open-pair failure cannot partially replace A; a corrected retry admits both.
fill('intradayProcedureLeftPath', paths['q36'])
fill('intradayProcedureRightPath', root / 'missing-study.json')
click('intradayProcedureOpenPairButton'); complete('FAILED')
assert controller._report == expected and controller.boundSources == bound and controller.studyError
assert controller.leftSource['experiment_id'] == expected['members'][0]['experiment_id']
fill('intradayProcedureLeftPath', paths['ordinary'])
click('intradayProcedureOpenLeftButton'); complete('FAILED')
assert 'Q25' in controller.studyError and controller._report == expected
fill('intradayProcedureLeftPath', paths['q25'])
fill('intradayProcedureRightPath', paths['q31'])
click('intradayProcedureOpenPairButton'); complete()
assert controller.canRun and not controller.studyError and controller.draftChanged

# A real in-flight comparison uses captured bytes. Editing B rejects its
# completion while a page/language switch preserves the old source labels.
run, ready, release, calls = comparison.compare_intraday_procedures, threading.Event(), threading.Event(), []
def delayed(a, b, **kwargs):
    calls.append((a.content, b.content))
    result = run(a, b, **kwargs)
    ready.set(); assert release.wait(30)
    return result
comparison.compare_intraday_procedures = delayed
click('intradayProcedureRunButton')
deadline = time.monotonic() + 60
while not ready.is_set() and time.monotonic() < deadline:
    app.processEvents(); time.sleep(.01)
assert ready.is_set()
fill('intradayProcedureRightPath', paths['q36'])
assert session.i18n.setLanguage('zh-CN')
click('intradayMLDiagnosticsTab'); click('intradayProcedureTab')
release.set(); complete()
comparison.compare_intraday_procedures = run
assert calls == [(original[paths['q25']], original[paths['q31']])]
assert controller.notice == 'STALE_INPUT' and controller.draftChanged
assert controller._report == expected and controller.boundSources == bound
assert expected['members'][1]['experiment_id'] in find('intradayProcedureSummary').property('text')
assert 'ECONOMIC_THRESHOLD_SELECTION' in json.dumps(controller.boundSources)
assert not controller.canRun
assert session.i18n.setLanguage('en')

# Retry through separate Open actions reaches Q31 versus Q36 and all actual
# joint refits. No source or TEST study is automatically created or selected.
fill('intradayProcedureLeftPath', paths['q31'])
click('intradayProcedureOpenLeftButton'); complete()
click('intradayProcedureOpenRightButton'); complete()
click('intradayProcedureRunButton'); complete()
assert controller._report == joint_expected and not controller.draftChanged and not controller.notice
assert not owner.intradayFinalController.selectionLoaded
choose('intradayProcedureView', 2); choose('intradayProcedureMember', 2)
assert [row['complete_record'] for row in evidence()['rows']] == joint_expected['members'][1]['outer_folds']
assert all('refit' in row['complete_record'] and row['model_id'] for row in controller._evidence_rows)
print('NATIVE_PROCEDURE_RECOVERY_COMPLETE', flush=True)

# Compact height still exposes the account ledger and real next-page action.
choose('intradayProcedureView', 3)
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
assert [row['complete_record'] for row in json.loads(controller.currentPageEvidence)['rows']] == joint_expected['members'][1]['selected_account']['execution']['ledger'][100:200]
assert window.grabWindow().save(str(root / 'q39-native-compact-ledger.png'))
print('NATIVE_PROCEDURE_COMPACT_COMPLETE', flush=True)

# An unavailable paired result remains a complete readable derived report;
# no numeric zero substitutes for missing paired daily returns or intervals.
window.setWidth(1280); window.setHeight(1050); QTest.qWait(50)
fill('intradayProcedureLeftPath', paths['blocked-a'])
fill('intradayProcedureRightPath', paths['blocked-b'])
click('intradayProcedureOpenPairButton'); complete()
click('intradayProcedureRunButton'); complete()
assert controller.resultSummary['status'] == 'UNAVAILABLE'
assert controller.resultSummary['unavailable_reason'] == 'BASIS_MISMATCH'
choose('intradayProcedureView', 0)
assert controller._evidence_rows[2]['return_mean'] == '—'
assert displayed(controller._evidence_rows[2]['mean_unavailable_reason']) == 'Common basis differs'
choose('intradayProcedureView', 1)
assert controller.tableModel.totalRows == 100
assert all(row['procedure_b_minus_a'] == '—' for row in controller._evidence_rows)
choose('intradayProcedureView', 4)
assert any(row['basis_matches'] == 'NO' for row in controller._evidence_rows)
fill('intradayProcedureLeftPath', paths['short-a'])
fill('intradayProcedureRightPath', paths['short-b'])
click('intradayProcedureOpenPairButton'); complete()
click('intradayProcedureRunButton'); complete()
assert controller.resultSummary['status'] == 'UNAVAILABLE'
assert controller.resultSummary['unavailable_reason'] == 'SOURCE_STUDY_UNAVAILABLE'
assert controller.resultSummary['sample'] is None and controller._report['statistics'] == []
assert 'undefined' not in find('intradayProcedureSummary').property('text')
choose('intradayProcedureView', 1)
assert controller.tableModel.totalRows == 0
choose('intradayProcedureView', 2)
assert controller.tableModel.totalRows > 0
assert all(row['model_id'] is None and row['strategy_kind'] is None for row in controller._evidence_rows)
choose('intradayProcedureView', 3)
assert controller.sectionOptions == ['all_fields']
assert len(evidence()['rows']) == 2
assert all(row['complete_record'] is None for row in controller._evidence_rows)
assert window.grabWindow().save(str(root / 'q39-native-unavailable.png'))
assert all(path.read_bytes() == content for path, content in original.items())
(root / 'q39-native-warnings.json').write_text(json.dumps(warnings, ensure_ascii=False, indent=2))
assert not any('IntradayProcedureComparisonPanel' in value or 'IntradayWorkspacePanel' in value for value in warnings), warnings
patch.undo()
assert session.shutdown()
engine.deleteLater(); app.processEvents()
print('NATIVE_PROCEDURE_COMPARISON_PASS')
'''
    completed = subprocess.run([sys.executable, "-c", script, str(tmp_path)], cwd=ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software",
             "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT / "tests")))},
        text=True, capture_output=True, timeout=360)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "NATIVE_PROCEDURE_COMPARISON_PASS" in completed.stdout
