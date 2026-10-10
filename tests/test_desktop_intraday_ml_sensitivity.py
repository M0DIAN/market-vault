"""Native fixed-objective evidence and draft/completed method separation."""

from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys

import pytest

# Qt-free CI must skip before creating the shared, real research fixtures.
pytest.importorskip("PySide6")

from market_vault.research import intraday_inner_selection as inner
from market_vault.research import intraday_research as research
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.strategy_experiment import write_strategy_experiment
from test_strategy_intraday_ml import quadratic_dev_case  # noqa: F401
from test_strategy_intraday_inner_selection import inner_case  # noqa: F401
from test_strategy_intraday_threshold_selection import threshold_case  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]


def test_native_fixed_inner_windows_mode_capture_full_evidence_and_compact(
        quadratic_dev_case, inner_case, threshold_case, tmp_path):
    data, plan, _, _, _, _ = quadratic_dev_case
    _, _, ordinary_path, _, _, inner_path = inner_case
    _, _, threshold_source_path, _, _, threshold_path = threshold_case
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
import json, sys, threading, time
from pathlib import Path
from PySide6.QtCore import QObject, QPointF, QUrl, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QJSValue
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from market_vault.application import build_application_context
from market_vault.backtest import intraday as execution
from market_vault.desktop.bootstrap import create_qml_application_session
from market_vault.desktop.preferences import DesktopPreferenceStore
from market_vault.desktop.localization import translation_keys_match
from market_vault.research import intraday_inner_objective_sensitivity as sensitivity
from market_vault.research import intraday_inner_selection as inner
from market_vault.research import intraday_research as research
from market_vault.research import intraday_threshold_selection as threshold

root, ordinary_path, inner_path, threshold_path, unavailable_path, data_path, threshold_source_path = map(Path, sys.argv[1:])
original_bytes = {path: path.read_bytes() for path in
                  (ordinary_path, inner_path, threshold_path, unavailable_path, data_path, threshold_source_path)}
saved_inner = json.loads(original_bytes[inner_path])['report']
saved_threshold = json.loads(original_bytes[threshold_path])['report']
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
assert session.i18n.setLanguage('en') and session.shell.selectPage('quant_research')

def find(name):
    result = window.findChild(QObject, name)
    if result is not None: return result
    pending = [window.contentItem()]
    while pending:
        obj = pending.pop()
        if obj.objectName() == name: return obj
        pending.extend(obj.childItems())
    raise AssertionError(name)

def nested(obj, kind):
    if kind in obj.metaObject().className(): return obj
    return next(child for child in obj.findChildren(QObject) if kind in child.metaObject().className())

def click_obj(obj):
    app.processEvents()
    assert obj.property('visible') and obj.property('enabled'), obj.objectName()
    point = obj.mapToScene(obj.boundingRect().center()).toPoint()
    assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), (obj.objectName(), point)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    app.processEvents()

def click(name): click_obj(find(name))

def choose(name, index):
    obj = find(name)
    window.requestActivate(); QTest.qWait(20)
    nested(obj, 'PixelComboBox').forceActiveFocus()
    QTest.keyClick(window, Qt.Key_Home)
    for _ in range(index): QTest.keyClick(window, Qt.Key_Down)
    app.processEvents()
    assert obj.property('currentIndex') == index, (name, obj.property('currentIndex'))

def complete(status='SUCCESS'):
    deadline = time.monotonic() + 90
    while controller.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    app.processEvents()
    assert not controller.busy and controller.status == status, (controller.status, controller.error, warnings)

def open_source(path):
    assert find('intradayMLSourcePath').setProperty('text', str(path))
    click('intradayMLOpenButton'); complete()

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

click('quantIntradayTab'); click('intradayMLDiagnosticsTab'); QTest.qWait(50)
open_source(ordinary_path)
click('intradayMLRunButton'); complete()
quality = controller._report
choose('intradayMLScope', 1); choose('intradayMLView', 4)
quality_evidence = evidence()
quality_scope, quality_views = controller.scopeOptions, controller.viewOptions
assert quality_evidence['prediction_quality_id'] == quality['prediction_quality_id']

# A Q34 draft cannot reinterpret completed Q33 evidence. A Q5 draft that is
# invalid even as a locator is deliberately retained, hidden and never parsed.
assert find('intradayMLDataPath').setProperty('text', 'not/an/absolute/q5/path')
choose('intradayMLMode', 1)
assert controller.sensitivityMode and not controller.completedSensitivity and not controller.canRun
assert not find('intradayMLRunButton').property('enabled')
assert not find('intradayMLDataRow').property('visible')
assert 'requires an inner ML selection study' in find('intradayMLNotice').property('text')
assert controller._report == quality and controller.scopeOptions == quality_scope and controller.viewOptions == quality_views
assert controller.scopeIndex == 1 and controller.viewIndex == 4
assert evidence() == quality_evidence
assert 'Outer DEV prediction quality' in find('intradayMLSummary').property('text')
assert 'Errors and paired means' in find('intradayMLInterpretation').property('text')

# Guard both source I/O and every relevant reconstruction/fit/Q6 entry point
# throughout real native Q34 actions. Only the saved study may be opened.
forbidden_paths = {data_path.resolve(), ordinary_path.resolve(), threshold_source_path.resolve()}
actual_open = Path.open
def guarded_open(path, mode='r', *args, **kwargs):
    assert path.resolve() not in forbidden_paths or not ('r' in mode or '+' in mode), 'Q34 read an original source or Q5'
    return actual_open(path, mode, *args, **kwargs)
Path.open = guarded_open
def forbidden(*args, **kwargs):
    raise AssertionError('Q34 accessed Q5, fitted a model or replayed execution')
for module, names in ((research, ('load_intraday_dataset', '_prepare_intraday_research', '_fit', 'run_intraday_execution')),
                      (inner, ('_fit', '_evaluate', 'run_intraday_execution')),
                      (threshold, ('_fit', '_evaluate', 'run_intraday_execution')),
                      (execution, ('run_intraday_execution',))):
    for name in names: setattr(module, name, forbidden)
actual, calls = sensitivity.analyze_intraday_inner_objective_sensitivity, []
gui_thread = threading.get_ident()
def measured(snapshot, *args, **kwargs):
    assert threading.get_ident() != gui_thread and not args and not kwargs
    result = actual(snapshot)
    calls.append((snapshot.experiment_id, result))
    return result
sensitivity.analyze_intraday_inner_objective_sensitivity = measured
open_source(inner_path)
assert controller.canRun and not controller.ordinarySource
assert controller._report == quality and controller.viewIndex == 4

# An actual completed Q34 calculation held on the worker must be discarded
# even when the draft method is changed and then restored before delivery.
ready, release = threading.Event(), threading.Event()
def delayed(snapshot):
    result = measured(snapshot)
    ready.set()
    assert release.wait(30)
    return result
sensitivity.analyze_intraday_inner_objective_sensitivity = delayed
click('intradayMLRunButton')
deadline = time.monotonic() + 90
while not ready.is_set() and time.monotonic() < deadline:
    app.processEvents(); time.sleep(.01)
assert ready.is_set()
choose('intradayMLMode', 0); choose('intradayMLMode', 1)
release.set(); complete()
assert controller.notice == 'STALE_INPUT' and controller._report == quality
assert controller.scopeOptions == quality_scope and controller.viewOptions == quality_views
assert evidence() == quality_evidence
sensitivity.analyze_intraday_inner_objective_sensitivity = measured
click('intradayMLRunButton'); complete()
assert controller.completedSensitivity and controller.viewIndex == controller.scopeIndex == 0

for source_path, saved, kind, member_count, unit, reference in (
        (inner_path, saved_inner, 'INNER_MODEL_SELECTION', 6, 'SQUARED_RATIO', (1, 1)),
        (threshold_path, saved_threshold, 'ECONOMIC_THRESHOLD_SELECTION', 4, 'RATIO', (0, 1))):
    if source_path != inner_path:
        open_source(source_path)
        click('intradayMLRunButton'); complete()
    report = controller._report
    assert report == calls[-1][1] and report['source_kind'] == kind
    assert report['version'] == sensitivity.INTRADAY_INNER_OBJECTIVE_SENSITIVITY_VERSION
    assert controller.completedSensitivity and not controller.draftChanged
    assert tuple(report['source_selection'][key] for key in ('cost_index', 'candidate_index')) == reference
    details = json.loads(controller.completedDetails)
    assert details['source_path'] == str(source_path) and details['sensitivity_id'] == report['sensitivity_id']
    assert details['diagnostic_mode'] == 'INNER_OBJECTIVE_SENSITIVITY'
    assert not any(key in details for key in ('requested_data_locator', 'requested_cost_index', 'requested_candidate_index'))
    assert not any(details['evidence'][key] for key in ('source_reconstructed', 'models_refitted', 'execution_replayed'))
    assert report['sample']['omission_count'] == 5 * len(report['windows'])
    assert [row['kind'] for row in controller.scopeOptions] == ['all_inner_windows'] + ['OUTER_INNER'] * len(saved['outer_folds']) + ['FINAL_DEV']
    assert controller.scopeOptions[-1]['fold_index'] is None
    originals = [row['inner'] for row in saved['outer_folds']] + [saved['final_dev']]
    assert [row['fixed_evidence'] for row in report['windows']] == originals
    view_calls = len(calls)
    choose('intradayMLView', 0)
    assert controller.tableModel.totalRows == len(report['windows'])
    choose('intradayMLView', 1)
    assert controller.tableModel.totalRows == member_count * len(report['windows'])
    assert [row['complete_objective'] for row in controller._evidence_rows] == [
        member for item in report['windows'] for member in item['original']['objectives']]
    assert {row['unit'] for row in controller._evidence_rows} == {unit}
    choose('intradayMLScope', 1)
    selected_window = report['windows'][0]
    assert controller.tableModel.totalRows == member_count
    assert evidence()['complete_window_evidence'] == selected_window
    choose('intradayMLView', 2)
    assert controller.tableModel.totalRows == 5
    assert [row['complete_omission'] for row in controller._evidence_rows] == selected_window['omissions']
    assert [row['omitted_day'] for row in controller._evidence_rows] == originals[0]['validation_days']
    assert {row['unit'] for row in controller._evidence_rows} == {unit}
    if kind == 'ECONOMIC_THRESHOLD_SELECTION':
        assert all(row['remaining_complete_target_count'] is None for row in controller._evidence_rows)
        assert 'cash-return factors minus one' in find('intradayMLInterpretation').property('text')
    else:
        assert all(row['remaining_complete_target_count'] > 0 for row in controller._evidence_rows)
        assert 'COMPLETE-row-weighted MSE' in find('intradayMLInterpretation').property('text')
    choose('intradayMLView', 3)
    assert controller.tableModel.totalRows == 5 * member_count
    assert [row['complete_objective'] for row in controller._evidence_rows] == [
        member for omission in selected_window['omissions'] for member in omission['objectives']]
    choose('intradayMLView', 4)
    assert controller.tableModel.totalRows == member_count
    assert [row['selection_count'] for row in controller._evidence_rows] == [row['count'] for row in selected_window['selection_counts']]
    assert all(row['available_omission_count'] == selected_window['available_omission_count'] for row in controller._evidence_rows)
    choose('intradayMLView', 5)
    rows = controller._evidence_rows
    if kind == 'INNER_MODEL_SELECTION':
        assert [row['complete_model'] for row in rows if 'complete_model' in row] == [member['model'] for member in originals[0]['family_results']]
        assert [row['complete_prediction'] for row in rows if 'complete_prediction' in row] == [
            prediction for member in originals[0]['family_results'] for prediction in member['predictions']]
        assert [row['complete_target'] for row in rows if 'complete_target' in row] == originals[0]['scored_targets']
    else:
        assert [row['complete_model'] for row in rows if 'complete_model' in row] == [originals[0]['model']]
        assert [row['complete_prediction'] for row in rows if 'complete_prediction' in row] == originals[0]['predictions']
        assert [row['complete_daily_cash'] for row in rows if 'complete_daily_cash' in row] == [
            day for member in originals[0]['family_results'] for day in member['execution']['daily']]
    assert evidence()['complete_window_evidence']['fixed_evidence'] == originals[0]
    click('intradayMLEvidenceButton')
    assert find('intradayMLEvidenceScroll').property('contentItem').property('contentHeight') > find('intradayMLEvidenceScroll').property('availableHeight')
    assert window.grabWindow().save(str(root / ('q34-fixed-models-en.png' if member_count == 6 else 'q34-fixed-cash-en.png')))
    QTest.keyClick(window, Qt.Key_Escape); app.processEvents()
    choose('intradayMLScope', len(report['windows']))
    assert find('intradayMLScope').property('currentText') == 'Final DEV inner window'
    assert evidence()['complete_window_evidence']['fixed_evidence'] == saved['final_dev']
    assert len(calls) == view_calls

# A draft Q33 choice cannot relabel the finished Q34 report. A worker failure
# also preserves its selected window, page data and complete source evidence.
before, before_evidence = controller._report, evidence()
completed_scope, completed_views = controller.scopeOptions, controller.viewOptions
choose('intradayMLMode', 0)
assert controller.completedSensitivity and controller.scopeOptions == completed_scope and controller.viewOptions == completed_views
assert 'cash-return factors minus one' in find('intradayMLInterpretation').property('text')
assert evidence() == before_evidence and controller._report == before
choose('intradayMLMode', 1)
def failed(snapshot):
    assert threading.get_ident() != gui_thread
    raise ValueError('Native sensitivity failure recovery probe')
sensitivity.analyze_intraday_inner_objective_sensitivity = failed
click('intradayMLRunButton'); complete('FAILED')
assert controller.studyError and controller._report == before and evidence() == before_evidence
sensitivity.analyze_intraday_inner_objective_sensitivity = measured
click('intradayMLRunButton'); complete()
assert not controller.studyError and not controller.notice and not controller.draftChanged
assert controller._report == before

# The same six views survive translation and a compact window. Pagination
# reaches full recorded inputs instead of restricting evidence to the first page.
assert session.i18n.setLanguage('zh-CN')
assert find('intradayMLMode').property('currentText') == '固定内层目标的单日贡献敏感性'
assert displayed('FINAL_DEV') == '最终 DEV 内层窗口'
assert find('intradayMLView').property('currentText') == '完整固定模型、键与输入'
assert 'Q31 最大化' in find('intradayMLInterpretation').property('text')
assert window.grabWindow().save(str(root / 'q34-inner-window-zh.png'))
expected_page = controller._evidence_rows[100:200]
window.setWidth(1024); window.setHeight(600); QTest.qWait(100)
scroll = find('intradayMLScroll')
flick = scroll.property('contentItem')
assert flick.property('contentHeight') > scroll.property('availableHeight')
bar = find('intradayMLScrollBar'); thumb = bar.property('contentItem')
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
assert controller.tableModel.page == 2 and json.loads(controller.currentPageEvidence)['rows'] == expected_page
assert json.loads(controller.currentPageEvidence)['complete_window_evidence']
assert window.grabWindow().save(str(root / 'q34-compact-fixed-inputs-zh.png'))

window.setWidth(1200); window.setHeight(1000); QTest.qWait(50)
flick.setProperty('contentY', 0); app.processEvents()
open_source(unavailable_path)
click('intradayMLRunButton'); complete()
assert controller.completedSensitivity and controller.resultSummary['status'] == 'UNAVAILABLE'
assert controller.resultSummary['sample'] is None and controller._report['windows'] == []
assert len(controller.scopeOptions) == 1 and controller.tableModel.totalRows == 0
assert json.loads(controller.completedDetails)['unavailable_reasons']
assert '不可用' in find('intradayMLSummary').property('text') and not controller.studyError
assert json.loads(controller.currentPageEvidence)['complete_window_evidence'] == []
Path.open = actual_open
assert all(path.read_bytes() == content for path, content in original_bytes.items())
assert not any('IntradayMLDiagnosticsPanel' in warning or 'IntradayWorkspacePanel' in warning for warning in warnings), warnings
sensitivity.analyze_intraday_inner_objective_sensitivity = actual
assert session.shutdown()
engine.deleteLater(); app.processEvents()
print('NATIVE_ML_SENSITIVITY_PASS')
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(ordinary_path), str(inner_path),
        str(threshold_path), str(unavailable_path), str(data.path), str(threshold_source_path)], cwd=ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software", "PYTHONPATH": str(ROOT / "src")},
        text=True, capture_output=True, timeout=240)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NATIVE_ML_SENSITIVITY_PASS" in result.stdout
