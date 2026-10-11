"""Real native procedure stress: captured inputs, all cells and full evidence."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

# Qt-free CI does not construct the otherwise shared saved-source fixture.
pytest.importorskip("PySide6")

from market_vault.research.intraday_procedure_stress import analyze_intraday_procedure_stress
from market_vault.research.strategy_experiment import write_strategy_experiment
from test_intraday_ml_procedures_comparison import reseal_procedure_benchmark
from test_intraday_ml_procedures_stress import _short_study


ROOT = Path(__file__).resolve().parents[1]


def test_native_procedure_stress_capture_grid_evidence_and_recovery(procedure_comparison_case, tmp_path, monkeypatch):
    case = procedure_comparison_case
    for name in ("q25", "q31", "q36"):
        (tmp_path / (name + ".json")).write_bytes(case.studies[name][0].content)
    (tmp_path / "ordinary.json").write_bytes(case.source.content)
    report = analyze_intraday_procedure_stress(case.studies["q36"][0])
    (tmp_path / "expected-id.json").write_text(json.dumps({"stress_id": report["stress_id"]}))
    del report

    def semantic_mismatch(execution, reference):
        execution["ledger"][0]["reason"] = "CHANGED_SAVED_REASON"
    blocked = reseal_procedure_benchmark(case.studies["q36"][0], semantic_mismatch)
    write_strategy_experiment(blocked, path=tmp_path / "blocked.json")
    # Reuse the admitted Q5 fixture for small real unavailable/partial studies;
    # only the full 100-day Q36 report is used for large-account UI acceptance.
    for name, options in (("unavailable", {"kind": "q25", "minimum": 10}),
                          ("partial", {"kind": "q31", "slippage": 9996})):
        directory = tmp_path / name
        directory.mkdir()
        study, _, _ = _short_study(case, directory, monkeypatch, **options)
        (tmp_path / (name + ".json")).write_bytes(study.content)
    (tmp_path / "settings.yaml").write_text("storage:\n  root_dir: ./data\n")
    script = r'''
import gc, hashlib, json, sys, time, threading
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
from market_vault.research import intraday_procedure_stress as stress, intraday_signal_delay as delay_engine
from market_vault.research import strategy_experiment as experiments
from test_intraday_ml_procedures_stress import prohibit_sources_and_selection

root = Path(sys.argv[1])
paths = {name: root / (name + '.json') for name in ('q25', 'q31', 'q36', 'ordinary', 'blocked', 'unavailable', 'partial')}
original = {path: path.read_bytes() for path in paths.values()}
expected_id = json.loads((root / 'expected-id.json').read_text())['stress_id']
assert translation_keys_match()
QQuickStyle.setStyle('Basic')
app = QGuiApplication([]); engine = QQmlApplicationEngine(); warnings = []
engine.warnings.connect(lambda values: warnings.extend(value.toString() for value in values))
context = build_application_context(root / 'settings.yaml')
session = create_qml_application_session(context, engine, preference_store=DesktopPreferenceStore(root=root / 'preferences'))
engine.load(QUrl.fromLocalFile(str(Path.cwd() / 'src/market_vault/desktop/qml/Main.qml')))
assert engine.rootObjects(), warnings
window = engine.rootObjects()[0]
window.setWidth(1280); window.setHeight(1100)
owner = session.context_properties['quantResearchController']
controller = owner.intradayProcedureStressController
assert session.i18n.setLanguage('en') and session.shell.selectPage('quant_research')
patch = pytest.MonkeyPatch(); prohibit_sources_and_selection(patch)
calls, execute = [], stress.run_intraday_execution
def counted(**kwargs):
    calls.append(1)
    return execute(**kwargs)
patch.setattr(stress, 'run_intraday_execution', counted)
patch.setattr(delay_engine, 'run_intraday_execution', counted)

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
    scroll = find('intradayProcedureStressScroll')
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

def fill(value):
    obj = find('intradayProcedureStressPath'); reveal(obj)
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

def browse(path):
    click('intradayProcedureStressBrowse')
    dialog = find('intradayProcedureStressFileDialog')
    assert dialog.property('visible')
    assert dialog.setProperty('selectedFile', QUrl.fromLocalFile(str(path)))
    assert QMetaObject.invokeMethod(dialog, 'accepted', Qt.DirectConnection)
    QMetaObject.invokeMethod(dialog, 'close', Qt.DirectConnection)
    app.processEvents()
    assert not controller.busy

def evidence():
    click('intradayProcedureStressEvidenceButton')
    assert find('intradayProcedureStressEvidenceDialog').property('visible')
    result = json.loads(find('intradayProcedureStressEvidenceText').property('text'))
    QTest.keyClick(window, Qt.Key_Escape); app.processEvents()
    assert find('intradayProcedureStressEvidenceText').property('text') == ''
    return result

def displayed(value):
    return find('intradayProcedureStressTable').property('cellFormatter').call([QJSValue(value)]).toString()

click('quantIntradayTab'); click('intradayProcedureStressTab'); QTest.qWait(30)
assert not controller.resultLoaded and not controller.canRun
assert 'All three complete zero-stress accounts' in find('intradayProcedureStressMethod').property('text')
browse(paths['q36'])
assert not controller.sourceInfo and not controller.canRun
click('intradayProcedureStressOpenButton'); complete()
assert controller.canRun and not controller.resultLoaded
assert controller.sourceInfo['source_kind'] == 'JOINT_ECONOMIC_SELECTION'
assert controller.sourceInfo['sha256'] == hashlib.sha256(original[paths['q36']]).hexdigest()
# Run is bound to the captured bytes even after the same disk path changes.
paths['q36'].write_bytes(b'changed after explicit Open')
loader = experiments.load_strategy_experiment
experiments.load_strategy_experiment = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('stress reopened a saved study'))
click('intradayProcedureStressRunButton'); complete()
experiments.load_strategy_experiment = loader
paths['q36'].write_bytes(original[paths['q36']])
assert len(calls) == 27 and context.backend_if_initialized is None
report = controller._report
assert report['stress_id'] == expected_id and report['status'] == 'AVAILABLE'
assert report['scenario_counts'] == {'declared': 9, 'available': 9, 'unavailable': 0}
assert report['baseline']['excluded_identity_fields'] == ['price_evidence_id', 'execution_id']
assert len(report['baseline']['accounts']) == 3 and all(row['matches'] for row in report['baseline']['accounts'])
assert controller.resultSummary['sample_count'] == 100 and controller.resultSummary['baseline_status'] == 'AVAILABLE'
assert controller.roleOptions == ['procedure', 'fixed_reference', 'benchmark']
assert [(row['additional_slippage_bps'], row['delay_bars']) for row in controller.scenarioOptions] == [
    (slippage, delay) for slippage in (0, 5, 10) for delay in (0, 1, 2)]
assert 'recorded-price-grid' in find('intradayProcedureStressSummary').property('text').lower()
assert 'undefined' not in find('intradayProcedureStressScenarioSummary').property('text')
bound = controller.boundSource
assert not controller.draftChanged and bound['source_kind'] == 'JOINT_ECONOMIC_SELECTION'
assert window.grabWindow().save(str(root / 'q41-native-stress-en.png'))
print('NATIVE_STRESS_CAPTURE_AND_BASELINE_COMPLETE', flush=True)

# Every declared role and scenario has readable raw metrics, units and deltas.
for role_index, role in enumerate(controller.roleOptions):
    choose('intradayProcedureStressRole', role_index)
    assert controller.tableModel.totalRows == 9
    for row, scenario in zip(controller._evidence_rows, report['scenarios'], strict=True):
        assert row['complete_record']['role'] == role and row['complete_record']['metrics'] == scenario['accounts'][role]['metrics']
        assert float(row['return_change_pp']) == pytest.approx(scenario['accounts'][role]['delta_from_zero']['total_return']['value'], rel=1e-5)
choose('intradayProcedureStressView', 1)
for scenario_index, scenario in enumerate(report['scenarios']):
    choose('intradayProcedureStressScenario', scenario_index)
    for role_index, role in enumerate(controller.roleOptions):
        choose('intradayProcedureStressRole', role_index)
        side = scenario['accounts'][role]
        assert controller.tableModel.totalRows == len(side['metrics'])
        for row in json.loads(controller.currentPageEvidence)['rows']:
            metric = side['metrics'][row['metric']]; delta = side['delta_from_zero'][row['metric']]
            assert row['complete_record'] == {'metric': row['metric'], 'metric_record': metric, 'delta_from_zero': delta}
            if metric['value'] is not None:
                assert float(row['metric_value'].removesuffix('%')) == pytest.approx(metric['value'] * (100 if metric['unit'] == 'RATIO' else 1), rel=1e-5)
            if delta['value'] is not None:
                assert float(row['change_from_zero']) == pytest.approx(delta['value'], rel=1e-5)
            assert row['change_unit'] == delta['unit']
        assert controller.scenarioSummary['role'] == role
    assert float(controller.scenarioSummary['mean_display']) == pytest.approx(scenario['increment']['mean'] * 100, rel=1e-5)
    assert float(controller.scenarioSummary['delta_display']) == pytest.approx(scenario['increment']['delta_from_zero']['value'], rel=1e-5)
assert evidence()['rows'] == json.loads(controller.currentPageEvidence)['rows']
assert displayed('PERCENTAGE_POINTS') == 'pp'

choose('intradayProcedureStressView', 2)
assert controller.tableModel.totalRows == 100
assert [row['complete_record'] for row in evidence()['rows']] == report['scenarios'][8]['daily']
for row, raw in zip(controller._evidence_rows, report['scenarios'][8]['daily'], strict=True):
    assert float(row['increment_pp']) == pytest.approx(raw['procedure_minus_fixed_reference'] * 100, rel=1e-5)
    assert all(row[role + '_return'].endswith('%') for role in controller.roleOptions)
choose('intradayProcedureStressView', 3); choose('intradayProcedureStressRole', 0)
signals = report['scenarios'][8]['accounts']['procedure']['signals']['provenance']
assert controller.tableModel.totalRows == len(signals) > 100
assert {row['source_target'] for row in signals} == {'LONG', 'FLAT'}
assert {'FORWARDED', 'NO_NEXT_OPEN', 'OUTSIDE_SESSION'} <= {row['status'] for row in signals}
assert [row['complete_record'] for row in evidence()['rows']] == signals[:100]
assert controller.scenarioSummary['signal_counts']['outside_session_count'] > 0
choose('intradayProcedureStressView', 5)
assert [row['complete_record'] for row in evidence()['rows']] == report['member']['outer_folds']
assert all(row['model_id'] and row['strategy_kind'] for row in controller._evidence_rows)
choose('intradayProcedureStressView', 6)
assert [row['complete_record'] for row in evidence()['rows']] == report['basis']['checks']
choose('intradayProcedureStressView', 7)
assert controller.tableModel.totalRows == 7
checks = evidence()['rows']
assert [row['complete_record'] for row in checks if row['check_group'] == 'baseline'] == report['baseline']['accounts']
assert [row['complete_record'] for row in checks if row['check_group'] == 'projection'] == [report['projection']]

# Both complete derived and original accounts remain navigable for all roles.
choose('intradayProcedureStressView', 4)
for origin in (0, 1):
    choose('intradayProcedureStressOrigin', origin)
    for role_index, role in enumerate(controller.roleOptions):
        choose('intradayProcedureStressRole', role_index)
        choose('intradayProcedureStressSection', controller.sectionOptions.index('execution.daily'))
        expected = report['accounts'][role] if origin else report['scenarios'][8]['accounts'][role]
        actual = json.loads(controller.currentPageEvidence)['rows']
        assert [row['complete_record'] for row in actual] == expected['execution']['daily']
        prefix = '/accounts/' if origin else '/scenarios/8/accounts/'
        assert all(row['record_path'].startswith(prefix + role + '/execution/daily/') for row in actual)
assert not find('intradayProcedureStressScenario').property('visible')
assert not find('intradayProcedureStressScenarioSummary').property('visible')
assert 'Captured source' in find('intradayProcedureStressOrigin').property('currentText')
# Hidden source-account preferences must not relabel the next scenario view.
# Preserve origin=source throughout these real transitions, including returns.
for view in (1, 2, 3):
    choose('intradayProcedureStressView', view)
    page = evidence()
    assert controller.originIndex == 1 and page['account_origin'] == 'scenario_account'
    assert page['scenario_index'] == 8 and 'section' not in page
    if view == 2:
        assert page['roles'] == controller.roleOptions and 'role' not in page
        assert [row['complete_record'] for row in page['rows']] == report['scenarios'][8]['daily']
    else:
        assert page['role'] == 'benchmark' and 'roles' not in page
        side = report['scenarios'][8]['accounts']['benchmark']
        if view == 1:
            assert {row['metric']: row['complete_record']['metric_record'] for row in page['rows']} == side['metrics']
        else:
            assert [row['complete_record'] for row in page['rows']] == side['signals']['provenance'][:100]
    choose('intradayProcedureStressView', 4)
    page = evidence()
    assert controller.originIndex == 1 and page['account_origin'] == 'source_account'
    assert 'scenario_index' not in page and page['role'] == 'benchmark' and page['section'] == 'execution.daily'
    assert [row['complete_record'] for row in page['rows']] == report['accounts']['benchmark']['execution']['daily']
choose('intradayProcedureStressView', 0)
page = evidence()
assert controller.originIndex == 1 and page['account_origin'] == 'scenario_account' and page['role'] == 'benchmark'
assert 'scenario_index' not in page and 'section' not in page and len(page['rows']) == 9
choose('intradayProcedureStressView', 5)
page = evidence()
assert page['role'] == 'procedure' and all(key not in page for key in ('account_origin', 'scenario_index', 'section', 'roles'))
assert [row['complete_record'] for row in page['rows']] == report['member']['outer_folds']
for view in (6, 7):
    choose('intradayProcedureStressView', view)
    page = evidence()
    assert page['roles'] == controller.roleOptions
    assert all(key not in page for key in ('account_origin', 'scenario_index', 'section', 'role'))
choose('intradayProcedureStressView', 4)
assert controller.originIndex == 1
choose('intradayProcedureStressOrigin', 0); choose('intradayProcedureStressRole', 0)
choose('intradayProcedureStressSection', controller.sectionOptions.index('execution.ledger'))
assert controller.tableModel.totalRows == len(report['scenarios'][8]['accounts']['procedure']['execution']['ledger']) > 100
print('NATIVE_STRESS_ALL_CELLS_AND_EVIDENCE_COMPLETE', flush=True)

# The report dialog stays small; clipboard still includes the full 27 accounts.
click('intradayProcedureStressReportButton')
details_text = find('intradayProcedureStressReportText').property('text')
details = json.loads(details_text)
assert details['stress_id'] == expected_id and details['source'] == bound
assert 'scenarios' not in details and 'accounts' not in details and 'member' not in details
assert details['evidence'] == report['evidence'] and details['method'] == report['method']
assert details['baseline'] == report['baseline'] and details['sample'] == report['sample']
click_obj(find('intradayProcedureStressCopyReportButton'), scroll=False)
copied = json.loads(QGuiApplication.clipboard().text())
assert copied == report
assert sum(side['execution'] is not None for scenario in copied['scenarios'] for side in scenario['accounts'].values()) == 27
assert len(QGuiApplication.clipboard().text()) > 50_000_000
del copied; QGuiApplication.clipboard().clear(); gc.collect()
QTest.keyClick(window, Qt.Key_Escape); app.processEvents()
assert find('intradayProcedureStressReportText').property('text') == ''
assert session.i18n.setLanguage('zh-CN')
assert displayed('PERCENTAGE_POINTS') == '百分点'
assert '三个完整零压力账户必须全部复现' in find('intradayProcedureStressMethod').property('text')
assert '每日程序' in find('intradayProcedureStressScenarioSummary').property('text')
assert window.grabWindow().save(str(root / 'q41-native-stress-zh.png'))

window.setWidth(1024); window.setHeight(600); QTest.qWait(100)
scroll = find('intradayProcedureStressScroll'); flick = scroll.property('contentItem')
assert flick.property('contentHeight') > scroll.property('availableHeight')
bar = find('intradayProcedureStressScrollBar'); thumb = bar.property('contentItem')
start = thumb.mapToScene(thumb.boundingRect().center()).toPoint()
end = bar.mapToScene(QPointF(bar.width() / 2, bar.height() - 2)).toPoint()
QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
QTest.mouseMove(window, end, 50)
QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
QTest.qWait(50)
assert flick.property('contentY') > 0
pagination = nested(find('intradayProcedureStressTable'), 'PixelPagination')
next_button = next(child for child in pagination.findChildren(QObject) if child.property('glyph') == 'next')
assert controller.tableModel.page == 1 and controller.tableModel.hasNext
click_obj(next_button, scroll=False)
assert controller.tableModel.page == 2
assert [row['complete_record'] for row in json.loads(controller.currentPageEvidence)['rows']] == report['scenarios'][8]['accounts']['procedure']['execution']['ledger'][100:200]
assert window.grabWindow().save(str(root / 'q41-native-stress-compact-zh.png'))
assert session.i18n.setLanguage('en'); QTest.qWait(30)
assert window.grabWindow().save(str(root / 'q41-native-stress-compact-en.png'))
print('NATIVE_STRESS_CLIPBOARD_AND_COMPACT_COMPLETE', flush=True)

window.setWidth(1280); window.setHeight(1100); QTest.qWait(50)
click('intradayMLDiagnosticsTab'); click('intradayProcedureStressTab')
assert controller._report is report and controller.boundSource == bound and not controller.draftChanged
# Editing or opening another kind never relabels the previous completed report.
fill(paths['q25'])
assert controller.draftChanged and not controller.canRun
assert controller._report is report and controller.boundSource == bound
assert bound['experiment_id'] in find('intradayProcedureStressSummary').property('text')
assert 'JOINT_ECONOMIC_SELECTION' == controller.boundSource['source_kind']
click('intradayProcedureStressOpenButton'); complete()
assert controller.sourceInfo['source_kind'] == 'INNER_MODEL_SELECTION' and controller.canRun
assert controller.boundSource == bound and controller._report is report

real = stress.analyze_intraday_procedure_stress
def pending_run(fail=False):
    ready, release = threading.Event(), threading.Event()
    def delayed(snapshot):
        result = None if fail else real(snapshot)
        ready.set(); assert release.wait(30)
        if fail: raise ValueError('controlled late execution error')
        return result
    stress.analyze_intraday_procedure_stress = delayed
    click('intradayProcedureStressRunButton')
    deadline = time.monotonic() + 60
    while not ready.is_set() and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    assert ready.is_set()
    return release

release = pending_run()
fill(paths['q31']); release.set(); complete()
stress.analyze_intraday_procedure_stress = real
assert controller.notice == 'STALE_INPUT' and controller._report is report and controller.boundSource == bound
assert not controller.canRun
fill(paths['q25'])
release = pending_run(fail=True)
fill(root / 'changed-during-failure.json'); release.set(); complete('STALE_INPUT')
stress.analyze_intraday_procedure_stress = real
assert controller.notice == 'STALE_INPUT' and not controller.studyError and controller._report is report
# Failed opens reject invalid/unavailable inputs, preserve completed evidence,
# and require a successful Open before Run can be enabled again.
for path in (root / 'missing.json', paths['ordinary'], paths['unavailable']):
    fill(path); click('intradayProcedureStressOpenButton'); complete('FAILED')
    assert controller.studyError and not controller.canRun
    assert controller._report is report and controller.boundSource == bound
assert 'SOURCE_STUDY_UNAVAILABLE' in controller.studyError
fill(paths['q25']); click('intradayProcedureStressOpenButton'); complete()
stress.analyze_intraday_procedure_stress = lambda snapshot: (_ for _ in ()).throw(ValueError('controlled run failure'))
click('intradayProcedureStressRunButton'); complete('FAILED')
stress.analyze_intraday_procedure_stress = real
assert 'controlled run failure' in controller.studyError and controller._report is report and controller.canRun
click('intradayProcedureStressRunButton'); complete()
assert controller.boundSource['source_kind'] == 'INNER_MODEL_SELECTION'
assert controller._report['status'] == 'AVAILABLE' and controller._report['stress_id'] != expected_id
assert not controller.studyError and not controller.notice and not controller.draftChanged
del report; gc.collect()
print('NATIVE_STRESS_FAILURE_STALE_AND_RETRY_COMPLETE', flush=True)

# An admitted, signed semantic baseline mismatch preserves all nine empty cells.
fill(paths['blocked']); click('intradayProcedureStressOpenButton'); complete()
before = len(calls)
click('intradayProcedureStressRunButton'); complete()
blocked = controller._report
assert len(calls) - before == 3
assert blocked['status'] == 'UNAVAILABLE' and blocked['unavailable_reason'] == 'ZERO_DELAY_REPRODUCTION_FAILED'
assert blocked['basis']['matches'] and [row['matches'] for row in blocked['baseline']['accounts']] == [True, True, False]
choose('intradayProcedureStressView', 0)
assert controller.tableModel.totalRows == 9 and len(controller.scenarioOptions) == 9
assert all(row['total_return'] == row['return_change_pp'] == '—' for row in controller._evidence_rows)
assert all(row['unavailable_reason'] == 'ZERO_DELAY_REPRODUCTION_FAILED' for row in controller._evidence_rows)
choose('intradayProcedureStressScenario', 8)
choose('intradayProcedureStressView', 2)
assert controller.tableModel.totalRows == 100
assert all(row['increment_pp'] == row['procedure_return'] == row['fixed_reference_return'] == row['benchmark_return'] == '—'
           for row in controller._evidence_rows)
choose('intradayProcedureStressView', 4); choose('intradayProcedureStressRole', 2)
choose('intradayProcedureStressSection', controller.sectionOptions.index('execution'))
assert evidence()['rows'][0]['complete_record'] is None
choose('intradayProcedureStressView', 7)
assert next(row['complete_record'] for row in evidence()['rows'] if row['check_group'] == 'baseline' and row['account_role'] == 'benchmark')['differing_fields'] == ['ledger']
assert window.grabWindow().save(str(root / 'q41-native-stress-unavailable.png'))

# Real Q31 high-slippage source admits three cells and leaves six unavailable.
fill(paths['partial']); click('intradayProcedureStressOpenButton'); complete()
click('intradayProcedureStressRunButton'); complete()
partial = controller._report
assert partial['source_kind'] == 'ECONOMIC_THRESHOLD_SELECTION' and partial['status'] == 'PARTIAL'
assert controller.resultSummary['scenario_counts'] == {'declared': 9, 'available': 3, 'unavailable': 6}
choose('intradayProcedureStressView', 0)
assert controller.tableModel.totalRows == 9
assert all(row['status'] == 'AVAILABLE' for row in controller._evidence_rows[:3])
assert all(row['status'] == 'UNAVAILABLE' for row in controller._evidence_rows[3:])
choose('intradayProcedureStressScenario', 8); choose('intradayProcedureStressRole', 2)
assert controller.scenarioSummary['execution_policy']['slippage_bps'] == 10006
assert controller.scenarioSummary['mean_display'] == '—'
assert 'Partially available' in find('intradayProcedureStressSummary').property('text')
assert window.grabWindow().save(str(root / 'q41-native-stress-partial.png'))
assert not owner.intradayFinalController.selectionLoaded and context.backend_if_initialized is None
assert all(path.read_bytes() == content for path, content in original.items())
assert not any('IntradayProcedureStressPanel' in value or 'IntradayWorkspacePanel' in value for value in warnings), warnings
(root / 'q41-native-warnings.json').write_text(json.dumps(warnings, ensure_ascii=False, indent=2))
patch.undo()
assert session.shutdown()
engine.deleteLater(); app.processEvents()
print('NATIVE_PROCEDURE_STRESS_PASS')
'''
    completed = subprocess.run([sys.executable, "-c", script, str(tmp_path)], cwd=ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software",
             "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT / "tests")))},
        text=True, capture_output=True, timeout=420)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "NATIVE_PROCEDURE_STRESS_PASS" in completed.stdout
