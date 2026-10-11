"""Real QML admission of one compact joint study to the three ML diagnostics."""

from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys

import pytest

# Qt-free CI skips before importing or constructing the shared research source.
pytest.importorskip("PySide6")

from market_vault.research import intraday_research as research
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.intraday_joint_selection import run_intraday_joint_selection
from market_vault.research.strategy_experiment import write_strategy_experiment
from test_strategy_intraday_joint_selection import joint_case, quadratic_dev_case  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]


def test_native_joint_three_methods_complete_evidence_and_recovery(joint_case, tmp_path):
    data, source, source_path, _, _, saved, _ = joint_case
    short_plan = deepcopy(source.as_dict()["plan"]["comparison_plan"])
    short_plan["walk_forward"]["minimum_train_days"] = 10
    short_plan["strategies"] = [short_plan["strategies"][0]]
    short = create_intraday_experiment(plan=short_plan, report=research.run_intraday_research(short_plan))
    short_path = write_strategy_experiment(short, path=tmp_path / "short-source.json").path
    unavailable = run_intraday_joint_selection(short_path, expected_experiment_id=short.experiment_id,
        cost_index=0, candidate_index=0,
        expected_candidate_id=short.as_dict()["report"]["groups"][0]["results"][0]["candidate_id"])
    unavailable_path = write_strategy_experiment(unavailable, path=tmp_path / "unavailable.json").path
    (tmp_path / "settings.yaml").write_text("storage:\n  root_dir: ./data\n")
    script = r'''
import json, math, sys, threading, time
from fractions import Fraction
from pathlib import Path
from PySide6.QtCore import QObject, QMetaObject, QPointF, QUrl, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QJSValue
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from market_vault.application import build_application_context
from market_vault.backtest import intraday as execution
from market_vault.desktop.bootstrap import create_qml_application_session
from market_vault.desktop.intraday_research import risk_value
from market_vault.desktop.localization import translation_keys_match
from market_vault.desktop.preferences import DesktopPreferenceStore
from market_vault.research import intraday_ml_diagnostics as quality_api
from market_vault.research import intraday_inner_objective_sensitivity as sensitivity
from market_vault.research import intraday_procedure_return_uncertainty as uncertainty
from market_vault.research import intraday_inner_selection as inner
from market_vault.research import intraday_joint_selection as joint
from market_vault.research import intraday_research as research
from market_vault.research import intraday_threshold_selection as threshold

root, source_path, study_path, data_path, unavailable_path = map(Path, sys.argv[1:])
original_bytes = {path: path.read_bytes() for path in (source_path, study_path, data_path, unavailable_path)}
saved = json.loads(original_bytes[study_path])['report']
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
controller = session.context_properties['quantResearchController'].intradayMLDiagnosticsController
assert session.i18n.setLanguage('en') and session.shell.selectPage('quant_research')

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
    scroll = find('intradayMLScroll')
    if not scroll.property('visible'): return
    flick = scroll.property('contentItem')
    top = scroll.mapToScene(QPointF(0, 0)).y()
    center = obj.mapToScene(obj.boundingRect().center()).y()
    height = scroll.property('availableHeight')
    if center < top + 10 or center > top + height - 10:
        target = flick.property('contentY') + center - top - height / 2
        flick.setProperty('contentY', max(0, min(target, flick.property('contentHeight') - height)))
        app.processEvents()

def click_obj(obj):
    reveal(obj)
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
        # Commit one choice in the real popup without running intervening views.
        QTest.keyClick(window, Qt.Key_Space)
        assert combo.property('down')
        QTest.keyClick(window, Qt.Key_Home)
        for _ in range(index): QTest.keyClick(window, Qt.Key_Down)
        QTest.keyClick(window, Qt.Key_Return)
    app.processEvents()
    assert obj.property('currentIndex') == index, (name, obj.property('currentIndex'))

def complete(status='SUCCESS'):
    deadline = time.monotonic() + 60
    while controller.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    app.processEvents()
    assert not controller.busy and controller.status == status, (controller.status, controller.error, warnings)

def open_source(path, browse=False):
    if browse:
        click('intradayMLSourceBrowse')
        dialog = find('intradayMLSourceDialog')
        assert dialog.property('visible')
        assert dialog.setProperty('selectedFile', QUrl.fromLocalFile(str(path)))
        assert QMetaObject.invokeMethod(dialog, 'accepted', Qt.DirectConnection)
        QMetaObject.invokeMethod(dialog, 'close', Qt.DirectConnection)
    else:
        assert find('intradayMLSourcePath').setProperty('text', str(path))
        click('intradayMLOpenButton')
    complete()

def evidence():
    click('intradayMLEvidenceButton')
    text = find('intradayMLEvidenceText')
    assert text.property('readOnly') and text.property('selectByMouse')
    assert engine.newQObject(text).property('wrapMode').toInt() != 0
    result = json.loads(text.property('text'))
    QTest.keyClick(window, Qt.Key_Escape); app.processEvents()
    assert not find('intradayMLEvidenceDialog').property('visible')
    assert find('intradayMLEvidenceText').property('text') == ''
    return result

def displayed(value):
    return find('intradayMLTable').property('cellFormatter').call([QJSValue(value)]).toString()

gui_thread, calls = threading.get_ident(), []
def observed(function, kind):
    def invoke(snapshot, *args, **kwargs):
        assert threading.get_ident() != gui_thread
        if kind != 'quality': assert not args and not kwargs
        result = function(snapshot, *args, **kwargs)
        calls.append((kind, snapshot.experiment_id, result))
        return result
    return invoke

actual_quality = quality_api.analyze_intraday_ml_prediction_quality
measured_quality = observed(actual_quality, 'quality')
quality_api.analyze_intraday_ml_prediction_quality = measured_quality
sensitivity.analyze_intraday_inner_objective_sensitivity = observed(
    sensitivity.analyze_intraday_inner_objective_sensitivity, 'sensitivity')
actual_uncertainty = uncertainty.analyze_intraday_procedure_return_uncertainty
measured_uncertainty = observed(actual_uncertainty, 'uncertainty')
uncertainty.analyze_intraday_procedure_return_uncertainty = measured_uncertainty

click('quantIntradayTab'); click('intradayMLDiagnosticsTab'); QTest.qWait(30)
open_source(source_path)
choose('intradayMLCost', 1); choose('intradayMLCandidate', 1)
assert controller.ordinarySource and controller.costIndex == controller.candidateIndex == 1
for mode in (1, 2):
    choose('intradayMLMode', mode)
    assert not controller.canRun and not find('intradayMLRunButton').property('enabled')
choose('intradayMLMode', 0)
open_source(study_path, browse=True)
assert controller.draftSource['source_kind'] == 'JOINT_ECONOMIC_SELECTION'
assert controller.canRun and not controller.ordinarySource and controller.costIndex == controller.candidateIndex == 0
assert not find('intradayMLCost').property('visible') and not find('intradayMLCandidate').property('visible')
click('intradayMLRunButton'); complete()
quality = controller._report
assert quality == calls[-1][2] and quality['source_kind'] == 'JOINT_ECONOMIC_SELECTION'
assert quality['selection_id'] == saved['joint_selection_id']
assert tuple(quality['source_selection'][key] for key in ('cost_index', 'candidate_index')) == (1, 1)
assert len(quality['folds']) == len(saved['outer_folds'])
assert [row['forecast'] for row in quality['forecasts']] == ['SELECTED', 'FIXED_REFERENCE', 'ZERO', 'TRAIN_MEAN']
assert len(quality['bins']) == 5 and quality['predictions']
for fold, outer in zip(quality['folds'], saved['outer_folds'], strict=True):
    assert fold['model'] == outer['refit']['model'] and fold['strategy'] == outer['refit']['strategy']
    context = next(item for item in saved['source_experiment']['report']['context']['folds'] if item['fold_id'] == outer['fold_id'])
    assert fold['training_keys'] == context['training_keys']
choose('intradayMLScope', 1); choose('intradayMLView', 4)
quality_evidence = evidence()
assert quality_evidence['complete_fold_evidence'] == quality['folds'][0]
assert [row['complete_model'] for row in controller._evidence_rows if 'complete_model' in row] == [
    quality['folds'][0]['model'], quality['folds'][0]['reference_model']]
assert "historical winner's actual refit" in find('intradayMLInterpretation').property('text')
assert window.grabWindow().save(str(root / 'q37-joint-quality-en.png'))

# A failed reconstruction and a stale completed worker preserve captured Q33.
assert find('intradayMLDataPath').setProperty('text', str(root / 'missing-q5.json'))
click('intradayMLRunButton'); complete('FAILED')
assert controller.studyError and controller._report == quality and evidence() == quality_evidence
click('intradayMLDataClear')
ready, release = threading.Event(), threading.Event()
def delayed(snapshot, *args, **kwargs):
    result = measured_quality(snapshot, *args, **kwargs)
    ready.set(); assert release.wait(30)
    return result
quality_api.analyze_intraday_ml_prediction_quality = delayed
click('intradayMLRunButton')
deadline = time.monotonic() + 60
while not ready.is_set() and time.monotonic() < deadline:
    app.processEvents(); time.sleep(.01)
assert ready.is_set()
for value in (str(root / 'different-source.json'), str(study_path)):
    assert find('intradayMLSourcePath').setProperty('text', value)
assert find('intradayMLDataPath').setProperty('text', str(data_path))
click('intradayMLDataClear')
release.set(); complete()
assert controller.notice == 'STALE_INPUT' and controller._report == quality and evidence() == quality_evidence
quality_api.analyze_intraday_ml_prediction_quality = measured_quality
click('intradayMLRunButton'); complete()
assert controller._report == quality and not controller.draftChanged and not controller.studyError
choose('intradayMLScope', 1)

# The two recorded-only methods must ignore even an invalid Q5 draft and must
# not read Q5/the ordinary source or enter any reconstruction/fit/Q6 path.
assert find('intradayMLDataPath').setProperty('text', 'not/an/absolute/q5/path')
choose('intradayMLMode', 1)
assert controller.canRun and controller.recordedOnlyMode and not controller.completedSensitivity
assert not find('intradayMLDataRow').property('visible')
assert evidence()['complete_fold_evidence'] == quality['folds'][0]
actual_open, forbidden_paths = Path.open, {source_path.resolve(), data_path.resolve()}
def guarded_open(path, mode='r', *args, **kwargs):
    assert path.resolve() not in forbidden_paths or not ('r' in mode or '+' in mode), 'Recorded-only source/Q5 read'
    return actual_open(path, mode, *args, **kwargs)
Path.open = guarded_open
def forbidden(*args, **kwargs): raise AssertionError('Recorded-only diagnostic recomputed research or execution')
for module, names in ((research, ('load_intraday_dataset', '_prepare_intraday_research', '_fit', 'run_intraday_execution')),
                      (inner, ('_fit', '_evaluate', 'run_intraday_execution')),
                      (threshold, ('_fit', '_evaluate', 'run_intraday_execution')),
                      (joint, ('_fit', '_evaluate', 'run_intraday_execution')),
                      (execution, ('run_intraday_execution',))):
    for name in names: setattr(module, name, forbidden)
click('intradayMLRunButton'); complete()
report = controller._report
assert report == calls[-1][2] and report['source_kind'] == 'JOINT_ECONOMIC_SELECTION'
assert controller.completedSensitivity and controller.scopeIndex == controller.viewIndex == 0
assert tuple(report['source_selection'][key] for key in ('cost_index', 'candidate_index')) == (1, 1)
details = json.loads(controller.completedDetails)
assert details['source_path'] == str(study_path) and details['selection_id'] == saved['joint_selection_id']
assert not any(key in details for key in ('requested_data_locator', 'requested_cost_index', 'requested_candidate_index'))
assert not any(details['evidence'][key] for key in ('source_reconstructed', 'models_refitted', 'execution_replayed'))
originals = [row['inner'] for row in saved['outer_folds']] + [saved['final_dev']]
assert [row['fixed_evidence'] for row in report['windows']] == originals
view_calls = len(calls)
choose('intradayMLScope', 1); choose('intradayMLView', 1)
selected_window, fixed = report['windows'][0], originals[0]
assert controller.tableModel.totalRows == 24
assert [row['complete_objective'] for row in controller._evidence_rows] == selected_window['original']['objectives']
assert [row['complete_objective']['recipe'] for row in controller._evidence_rows] == [
    member['strategy'] for member in fixed['family_results']]
assert [(row['strategy_kind'], row['alpha'], row['threshold']) for row in controller._evidence_rows] == [
    (kind, alpha, risk_value(value, 'RATIO')) for kind in ('RIDGE', 'QUADRATIC_RIDGE')
    for alpha in (.1, 1, 10) for value in (0, .0005, .001, .002)]
assert '24' in find('intradayMLInterpretation').property('text')
assert 'source threshold' in find('intradayMLInterpretation').property('text')
assert window.grabWindow().save(str(root / 'q37-joint-24-recipes-en.png'))
choose('intradayMLView', 2)
assert controller.tableModel.totalRows == 5
for row, omission in zip(controller._evidence_rows, selected_window['omissions'], strict=True):
    assert row['complete_omission'] == omission and row['runner_up_index'] == omission['runner_up_index']
    assert row['margin'] == risk_value(omission['margin']['value'], 'RATIO')
    assert row['strategy_kind'] == omission['selected_recipe']['kind']
    assert row['alpha'] == omission['selected_recipe']['alpha']
    assert row['threshold'] == risk_value(omission['selected_recipe']['threshold'], 'RATIO')
    assert row['remaining_complete_target_count'] is None
choose('intradayMLView', 3)
assert controller.tableModel.totalRows == 120
assert [row['complete_objective'] for row in controller._evidence_rows] == [
    objective for omission in selected_window['omissions'] for objective in omission['objectives']]
choose('intradayMLView', 5)
rows = controller._evidence_rows
models = [row for row in rows if 'complete_model' in row]
assert [row['complete_model'] for row in models] == [member['model'] for member in fixed['models']]
assert [row['joint_model_index'] for row in models] == list(range(6))
assert [row['complete_recipe'] for row in models] == [member['strategy'] for member in fixed['models']]
assert all(row['candidate_index'] is None and row['model_threshold_bps'] == -10000 for row in models)
predictions = [row for row in rows if 'complete_prediction' in row]
assert [row['complete_prediction'] for row in predictions] == [
    prediction for member in fixed['models'] for prediction in member['predictions']]
assert all(row['ml_evidence_role'] == 'fixed_shared_prediction' and row['complete_recipe']['threshold'] == -1
           for row in predictions)
daily = [row for row in rows if 'complete_daily_cash' in row]
assert len(daily) == 24 * 5 and {row['candidate_index'] for row in daily} == set(range(24))
for row in daily:
    member = fixed['family_results'][row['candidate_index']]
    assert row['joint_model_index'] == member['model_index'] and row['complete_recipe'] == member['strategy']
    assert row['threshold'] == risk_value(member['strategy']['threshold'], 'RATIO')
assert [row['complete_daily_cash'] for row in daily] == [
    day for member in fixed['family_results'] for day in member['execution']['daily']]
raw = evidence()
assert raw['complete_window_evidence']['fixed_evidence'] == fixed
assert all(field in member['execution'] for member in raw['complete_window_evidence']['fixed_evidence']['family_results']
           for field in ('decisions', 'trades', 'daily', 'ledger', 'transactions'))
assert any(a['target'] != b['target'] for a, b in zip(
    fixed['models'][0]['predictions'], fixed['family_results'][3]['execution']['decisions']))
choose('intradayMLScope', len(report['windows']))
assert evidence()['complete_window_evidence']['fixed_evidence'] == saved['final_dev']
assert len(calls) == view_calls

# Language and pagination expose the complete shared-model evidence, with the
# source prediction threshold distinct from a member's actual account threshold.
assert session.i18n.setLanguage('zh-CN')
assert '联合' in find('intradayMLSummary').property('text')
assert '来源原阈值' in find('intradayMLInterpretation').property('text')
assert displayed('fixed_shared_model') != 'fixed_shared_model'
assert displayed('fixed_shared_prediction') != 'fixed_shared_prediction'
model_position = next(index for index, row in enumerate(controller._evidence_rows) if 'complete_model' in row)
while controller.tableModel.page < model_position // 100 + 1:
    pagination = nested(find('intradayMLTable'), 'PixelPagination')
    click_obj(next(child for child in pagination.findChildren(QObject) if child.property('glyph') == 'next'))
assert window.grabWindow().save(str(root / 'q37-joint-shared-models-zh.png'))
window.setWidth(1024); window.setHeight(600); QTest.qWait(80)
assert find('intradayMLScroll').property('contentItem').property('contentHeight') > find('intradayMLScroll').property('availableHeight')
start = controller.tableModel.page * 100
pagination = nested(find('intradayMLTable'), 'PixelPagination')
click_obj(next(child for child in pagination.findChildren(QObject) if child.property('glyph') == 'next'))
assert evidence()['rows'] == controller._evidence_rows[start:start + 100]
assert window.grabWindow().save(str(root / 'q37-joint-compact-zh.png'))
window.setWidth(1280); window.setHeight(1100); QTest.qWait(50)
before, captured = controller._report, evidence()
choose('intradayMLMode', 2)
assert controller.completedSensitivity and controller._report == before and evidence() == captured
assert '来源原阈值' in find('intradayMLInterpretation').property('text')
click('intradayMLRunButton'); complete()
returns = controller._report
assert controller.completedUncertainty and not controller.completedSensitivity
assert returns == calls[-1][2] and returns['source_kind'] == 'JOINT_ECONOMIC_SELECTION'
assert returns['status'] == 'AVAILABLE' and returns['sample']['sample_count'] == 10 and returns['basis']['matches']
reference = saved['source_experiment']['report']['groups'][1]['results'][1]
assert returns['accounts'] == {'procedure': saved['selected_account'], 'fixed_reference': reference, 'benchmark': saved['benchmark']}
assert all(row['mean'] is not None and row['lower'] is row['upper'] is None
    and row['interval_unavailable_reason'] in ('INSUFFICIENT_DAILY_RETURNS', 'ZERO_SAMPLE_VARIATION')
    for row in returns['statistics'])
assert [row['complete_record'] for row in controller._evidence_rows] == returns['statistics']
values = {name: [float(Fraction(day['cash_close']) / Fraction(day['cash_open']) - 1)
    for day in account['execution']['daily']] for name, account in returns['accounts'].items()}
for name in ('fixed_reference', 'benchmark'):
    values['procedure_minus_' + name] = [a - b for a, b in zip(values['procedure'], values[name], strict=True)]
for index, day in enumerate(returns['daily']):
    assert all(math.isclose(day['values'][name], raw[index], rel_tol=1e-12, abs_tol=1e-15)
               for name, raw in values.items())
choose('intradayMLView', 1)
assert [row['complete_record'] for row in controller._evidence_rows] == returns['daily']
choose('intradayMLView', 3)
for index, name in enumerate(('procedure', 'fixed_reference', 'benchmark'), 1):
    choose('intradayMLEvidenceAccount', index)
    for field in ('decisions', 'ledger', 'transactions'):
        section = 'execution.' + field
        choose('intradayMLEvidenceSection', controller.evidenceSectionOptions.index(section))
        assert [row['complete_record'] for row in controller._evidence_rows] == returns['accounts'][name]['execution'][field]
        actual = evidence()
        assert actual['account'] == name and actual['section'] == section and actual['rows'] == controller._evidence_rows[:100]
        assert all(row['record_path'].startswith('/accounts/' + name + '/execution/' + field + '/') for row in actual['rows'])
assert session.i18n.setLanguage('en')
assert window.grabWindow().save(str(root / 'q37-joint-outer-account-en.png'))
before, captured = controller._report, evidence()
def failed(snapshot): raise ValueError('Joint native recorded-only recovery probe')
uncertainty.analyze_intraday_procedure_return_uncertainty = failed
click('intradayMLRunButton'); complete('FAILED')
assert controller.studyError and controller._report == before and evidence() == captured
uncertainty.analyze_intraday_procedure_return_uncertainty = measured_uncertainty
click('intradayMLRunButton'); complete()
assert controller._report == before and not controller.studyError and not controller.draftChanged

open_source(unavailable_path)
for mode in (1, 2):
    choose('intradayMLMode', mode); click('intradayMLRunButton'); complete()
    assert controller.resultSummary['status'] == 'UNAVAILABLE' and controller.resultSummary['sample'] is None
    assert controller.tableModel.totalRows == 0 and len(controller.scopeOptions) == 1
    assert controller._report['windows'] == [] if mode == 1 else controller._report['accounts'] == {}
    assert json.loads(controller.completedDetails)['unavailable_reasons']
    assert 'Unavailable' in find('intradayMLSummary').property('text')
Path.open = actual_open
assert all(path.read_bytes() == content for path, content in original_bytes.items())
assert not any('IntradayMLDiagnosticsPanel' in warning or 'IntradayWorkspacePanel' in warning for warning in warnings), warnings
(root / 'q37-native-warnings.json').write_text(json.dumps(warnings, indent=2))
(root / 'q37-native-evidence.json').write_text(json.dumps({
    'quality': quality, 'sensitivity': report, 'returns': returns}, ensure_ascii=False))
assert session.shutdown()
engine.deleteLater(); app.processEvents()
print('NATIVE_JOINT_ML_DIAGNOSTICS_PASS')
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(source_path), str(saved),
        str(data.path), str(unavailable_path)], cwd=ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software",
             "PYTHONPATH": str(ROOT / "src")}, text=True, capture_output=True, timeout=240)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NATIVE_JOINT_ML_DIAGNOSTICS_PASS" in result.stdout
