"""One real native chain for explicit Q31 Freeze and independent TEST V3."""

from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys

import pytest

from market_vault.research import intraday_research as research
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.intraday_final_test import freeze_intraday_inner_selection
from market_vault.research.intraday_threshold_selection import run_intraday_threshold_selection
from market_vault.research.strategy_experiment import write_strategy_experiment
from test_strategy_intraday_inner_selection import inner_case  # noqa: F401
from test_strategy_intraday_ml import quadratic_dev_case  # noqa: F401
from test_strategy_intraday_threshold_selection import threshold_case  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]


def test_native_threshold_freeze_test_evidence_proofs_relocations_and_stale_inputs(request, tmp_path):
    # The CI Qt skip must happen before creating any expensive saved Q5 source.
    pytest.importorskip("PySide6")
    data, ordinary, ordinary_path, _, study, study_path = request.getfixturevalue("threshold_case")
    _, _, _, _, inner, inner_path = request.getfixturevalue("inner_case")
    legacy = freeze_intraday_inner_selection(inner_path, expected_experiment_id=inner.experiment_id)
    write_strategy_experiment(legacy, path=tmp_path / "legacy-selection-v2.json")
    short_plan = deepcopy(ordinary.as_dict()["plan"])
    short_plan["walk_forward"]["minimum_train_days"] = 10
    short_plan["strategies"] = [short_plan["strategies"][0]]
    short = create_intraday_experiment(plan=short_plan, report=research.run_intraday_research(short_plan))
    short_path = write_strategy_experiment(short, path=tmp_path / "short-source.json").path
    unavailable = run_intraday_threshold_selection(short_path, expected_experiment_id=short.experiment_id,
        cost_index=0, candidate_index=0,
        expected_candidate_id=short.as_dict()["report"]["groups"][0]["results"][0]["candidate_id"])
    assert unavailable.as_dict()["report"]["status"] == "UNAVAILABLE"
    write_strategy_experiment(unavailable, path=tmp_path / "unavailable-threshold.json")
    (tmp_path / "settings.yaml").write_text("storage:\n  root_dir: ./data\n")
    script = r'''
import json, sys, time, threading
from pathlib import Path
from PySide6.QtCore import QObject, QUrl, Qt, QEvent, QMetaObject, QPointF
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from market_vault.application import build_application_context
from market_vault.desktop.bootstrap import create_qml_application_session
from market_vault.desktop.preferences import DesktopPreferenceStore
from market_vault.desktop.localization import translation_keys_match
from market_vault.research import intraday_final_test as core
from market_vault.research import intraday_research as research
from market_vault.research import intraday_threshold_selection as threshold
from market_vault.research import strategy_experiment as experiments

root, original_ordinary, original_study, original_data = map(Path, sys.argv[1:])
originals = {path: path.read_bytes() for path in (original_ordinary, original_study, original_data)}
ordinary, study, data = root/'ordinary.json', root/'threshold.json', root/'q5.json'
for target, source in ((ordinary, original_ordinary), (study, original_study), (data, original_data)):
    target.write_bytes(originals[source])
expected = json.loads(study.read_bytes())
frozen_window = expected['report']['final_dev']
assert translation_keys_match()
QQuickStyle.setStyle('Basic')
app = QGuiApplication([]); engine = QQmlApplicationEngine(); warnings = []
engine.warnings.connect(lambda values: warnings.extend(value.toString() for value in values))
session = create_qml_application_session(build_application_context(root/'settings.yaml'), engine,
    preference_store=DesktopPreferenceStore(root=root/'preferences'))
engine.load(QUrl.fromLocalFile(str(Path.cwd()/'src/market_vault/desktop/qml/Main.qml')))
assert engine.rootObjects(), warnings
window = engine.rootObjects()[0]; window.setWidth(1280); window.setHeight(1000)
owner = session.context_properties['quantResearchController']
development, controller = owner.intradayResearchController, owner.intradayFinalController
source_ui, comparison = owner.intradayThresholdSelectionController, owner.intradaySavedComparisonController
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
    for name in ('intradayFinalScroll', 'intradaySavedComparisonScroll'):
        scroll = find(name)
        if not scroll.property('visible'): continue
        flick = scroll.property('contentItem')
        top = scroll.mapToScene(QPointF(0, 0)).y()
        center = obj.mapToScene(obj.boundingRect().center()).y()
        height = scroll.property('availableHeight')
        if center < top + 10 or center > top + height - 10:
            target = flick.property('contentY') + center - top - height/2
            flick.setProperty('contentY', max(0, min(target, flick.property('contentHeight') - height)))
            app.processEvents()

def click_obj(obj):
    reveal(obj); app.processEvents()
    assert obj.property('visible') and obj.property('enabled'), obj.objectName()
    point = obj.mapToScene(obj.boundingRect().center()).toPoint()
    assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), (obj.objectName(), point)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point); app.processEvents()

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
    QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier); QTest.keyClick(window, Qt.Key_Backspace)
    for char in str(value):
        QGuiApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, ord(char.upper()), Qt.NoModifier, char))
    app.processEvents()
    assert obj.property('text') == str(value)

def complete(target=controller, status='SUCCESS'):
    deadline = time.monotonic() + 90
    while target.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    app.processEvents()
    assert not target.busy and target.status == status, (target.status, target.error, warnings)

def file_action(button, dialog_name, path, target=controller, status='SUCCESS'):
    click(button); dialog = find(dialog_name)
    assert dialog.property('visible')
    assert dialog.setProperty('selectedFile', QUrl.fromLocalFile(str(path)))
    assert QMetaObject.invokeMethod(dialog, 'accepted', Qt.DirectConnection)
    QMetaObject.invokeMethod(dialog, 'close', Qt.DirectConnection)
    complete(target, status)

def page_evidence():
    click('intradayFinalPageEvidenceButton')
    assert find('intradayFinalPageEvidenceDialog').property('visible')
    obj = find('intradayFinalPageEvidenceText'); text = obj.property('text')
    assert obj.property('readOnly') and obj.property('selectByMouse')
    result = json.loads(text)
    QTest.keyClick(window, Qt.Key_Escape); app.processEvents()
    assert not find('intradayFinalPageEvidenceDialog').property('visible')
    assert obj.property('text') == ''
    return result, text

def locations(source, q5):
    click('intradayFinalLocationsButton')
    assert find('intradayFinalSourcePath').property('label') == session.i18n.catalog['final.threshold_source_override']
    fill('intradayFinalSourcePath', source); fill('intradayFinalDataPath', q5)
    click('intradayFinalLocationsDone')

def shot(name):
    QTest.qWait(40); app.processEvents()
    assert window.grabWindow().save(str(root/(name+'.png')))

def wait_ready(ready):
    deadline = time.monotonic() + 90
    while not ready.is_set() and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    assert ready.is_set()

def proof_state():
    return (controller._selection_content, controller._test_content, controller.selectionPath,
            controller.testPath, controller._selection_proof, controller._test_proof)

click('quantIntradayTab'); click('intradayFinalTab'); app.processEvents()
assert not controller.canFreezeThreshold and not controller.selectionLoaded
source_ui._apply(experiments.load_strategy_experiment(study))
assert source_ui.resultLoaded and source_ui.experimentPath == ''
assert not controller.canFreezeThreshold and not controller.freezeThresholdSelection()
assert not controller.selectionLoaded
file_action('intradayFinalThresholdOpenButton', 'intradayFinalThresholdSourceDialog', ordinary, status='FAILED')
assert source_ui.experimentPath == '' and not controller.selectionLoaded
file_action('intradayFinalThresholdOpenButton', 'intradayFinalThresholdSourceDialog', root/'unavailable-threshold.json')
assert not controller.canFreezeThreshold and not controller.selectionLoaded
assert not find('intradayFreezeThresholdButton').property('enabled')
file_action('intradayFinalThresholdOpenButton', 'intradayFinalThresholdSourceDialog', study)
assert controller.canFreezeThreshold and not controller.selectionLoaded and not controller.testLoaded
assert str(study) in controller.thresholdSourceDetails and expected['experiment_id'] in controller.thresholdSourceDetails

# Freeze and Open remain saved-record operations with no fit or reselection.
def forbidden(*args, **kwargs): raise AssertionError('Unexpected Q5 access, fit or reselection')
blocked = [(core, 'load_intraday_dataset'), (research, 'load_intraday_dataset'),
    (core, 'fit_quadratic_rows'), (research, 'fit_ridge_rows'), (threshold, '_fit'),
    (threshold, '_select'), (threshold, '_threshold_accounts')]
original_functions = [(module, key, getattr(module, key)) for module, key in blocked]
for module, key in blocked: setattr(module, key, forbidden)
click('intradayFreezeThresholdButton'); complete()
assert controller._selection_root['artifact_schema_version'] == core.INTRADAY_SELECTION_V3_VERSION
assert controller._selection_root['report']['dev_selection']['final_dev'] == frozen_window
assert controller._selection_root['plan']['source_experiment']['path'] == str(study)
assert controller._selection_proof == 'FROZEN' and not controller.testLoaded
assert controller._view_index == 15 and controller.tableModel.totalRows == 4
assert 'FIRST_DECLARED' in find('intradayFinalMethod').property('text')
assert 'MSE' not in find('intradayFinalMethod').property('text')
assert 'NONE unadjusted' in find('intradayFinalReturnBasis').property('text')
selected = root/'selection-v3.json'
file_action('intradaySelectionSaveButton', 'intradaySelectionSaveDialog', selected)
selected_bytes = selected.read_bytes()
file_action('intradaySelectionOpenButton', 'intradaySelectionOpenDialog', selected)
assert controller._selection_proof == 'RECORDED' and not controller.testLoaded
for module, key, value in original_functions: setattr(module, key, value)
assert selected_bytes == controller._selection_content
assert str(selected) in find('intradayFinalCompletedPaths').property('text')
print('Q32_NATIVE_EXPLICIT_FREEZE_NO_DATA_FIT_RESELECTION_OK', flush=True)

# All four detail accounts must display their own actual decisions and cash.
accounts = frozen_window['family_results']
assert controller.thresholdAccountOptions == [{'threshold_bps': member['threshold']*10000,
    'chosen': member['candidate_index'] == frozen_window['selected_index']} for member in accounts]
choose('intradayTestView', 15)
overview, _ = page_evidence()
assert overview['execution_input'] == frozen_window['execution_input']
assert overview['unavailable_reason'] == frozen_window['unavailable_reason']
assert [row['total_return'] for row in overview['rows']] == [row['execution']['metrics']['total_return'] for row in accounts]
assert [row['final_cash'] for row in overview['rows']] == [row['execution']['metrics']['final_cash'] for row in accounts]
for key in ('total_return', 'observed_max_drawdown'):
    assert all(row[controller._columns.index(key)].endswith('%') for row in controller._rows)
reveal(find('intradayTestTable'))
shot('q32-native-four-dev-accounts-en')
different_target = False
for account_index, member in enumerate(accounts):
    choose('intradayFinalThresholdAccount', account_index)
    for view, key in ((18, 'decisions'), (19, 'trades'), (20, 'daily'), (21, 'ledger'), (22, 'transactions')):
        choose('intradayTestView', view)
        assert controller.tableModel.totalRows == len(member['execution'][key])
        shown, _ = page_evidence()
        assert shown['execution_metadata']['metrics'] == member['execution']['metrics']
        rows = shown['rows']
        if key == 'decisions':
            assert [{k: v for k, v in row.items() if k != 'shared_prediction_target'} for row in rows] == member['execution'][key][:100]
            for row in rows:
                assert row['target'] == ('LONG' if row['score'] > member['threshold'] else 'FLAT')
                different_target |= row['target'] != row['shared_prediction_target']
        else:
            assert rows == member['execution'][key][:100]
assert different_target
choose('intradayTestView', 16)
model_evidence, text = page_evidence()
assert model_evidence['complete_model'] == frozen_window['model']
assert frozen_window['model']['training_keys'] == frozen_window['training_keys']
assert {row['model_stage'] for row in model_evidence['rows']} == {'INPUT_TRANSFORM', 'GENERATED_TERMS'}
click('intradayFinalPageEvidenceButton')
assert find('intradayFinalPageEvidenceScroll').property('contentItem').property('contentHeight') > 500
shot('q32-native-shared-model-full-evidence-en')
QTest.keyClick(window, Qt.Key_Escape); app.processEvents()
choose('intradayTestView', 17)
keys = controller._evidence_rows
for key in ('history_training_keys', 'history_purged_keys', 'training_keys', 'purged_keys', 'validation_keys'):
    assert [row['value'] for row in keys if row['threshold_role'] == key] == frozen_window[key]
assert [row['label_return'] for row in keys if row['threshold_role'] == 'HISTORY_TARGET'] == [row['value'] for row in frozen_window['history_targets']]
assert {row['value'] for row in keys if row['threshold_role'].endswith('boundary')} == {frozen_window['history_boundary'], frozen_window['training_boundary']}
for view, key in ((23, 'sessions'), (24, 'prices')):
    choose('intradayTestView', view)
    assert page_evidence()[0]['rows'] == frozen_window[key][:100]
print('Q32_NATIVE_FOUR_ACTUAL_ACCOUNTS_MODEL_BOUNDARIES_FULL_EVIDENCE_OK', flush=True)

# A changed ordinary draft or a Q31 view choice is not an input to Freeze.
assert development.openExperiment(str(ordinary)); complete(development)
real_freeze, ready, release = core.freeze_intraday_threshold_selection, threading.Event(), threading.Event()
def delayed_freeze(*args, **kwargs):
    result = real_freeze(*args, **kwargs); ready.set(); assert release.wait(30); return result
core.freeze_intraday_threshold_selection = delayed_freeze
click('intradayFreezeThresholdButton'); wait_ready(ready)
assert development.selectCandidate(0)
assert source_ui.selectScope(len(expected['report']['outer_folds'])+1)
release.set(); complete(); core.freeze_intraday_threshold_selection = real_freeze
assert controller.notice == '' and controller._selection_proof == 'FROZEN' and not controller.testLoaded
file_action('intradaySelectionOpenButton', 'intradaySelectionOpenDialog', selected)

# Relocate the direct Q31 source, then run one actual final fit on all DEV.
moved_study = root/'relocated-q31-study.json'; study.rename(moved_study)
moved_data = root/'relocated-q5.json'; data.rename(moved_data)
click('intradayRunTestButton'); complete(status='FAILED')
assert controller._selection_content == selected_bytes and not controller.testLoaded
locations(ordinary, moved_data)
click('intradayRunTestButton'); complete(status='FAILED')
assert not controller.testLoaded and controller._selection_proof == 'RECORDED'
locations(moved_study, moved_data)
loads, fits = [], []
real_load, real_fit, real_threshold_fit = core.load_intraday_dataset, core.fit_quadratic_rows, threshold._fit
def counted_load(path): loads.append(str(path)); return real_load(path)
def counted_fit(*args, **kwargs): fits.append(1); return real_fit(*args, **kwargs)
core.load_intraday_dataset, core.fit_quadratic_rows, threshold._fit = counted_load, counted_fit, forbidden
click('intradayRunTestButton'); complete()
core.load_intraday_dataset, core.fit_quadratic_rows, threshold._fit = real_load, real_fit, real_threshold_fit
assert loads == [str(moved_data)] and fits == [1]
assert controller._selection_proof == 'RECORDED' and controller._test_proof == 'COMPUTED'
report = controller._test_root['report']
assert controller._test_root['artifact_schema_version'] == core.INTRADAY_TEST_EXPERIMENT_V3_VERSION
assert report['context']['training_keys'] == frozen_window['history_training_keys']
assert report['context']['purged_keys'] == frozen_window['history_purged_keys']
assert report['model']['training_keys'] == frozen_window['history_training_keys'] != frozen_window['training_keys']
assert report['model']['training_boundary'] == frozen_window['history_boundary'] != frozen_window['training_boundary']
assert report['strategy'] == frozen_window['selected_recipe']
assert report['return_basis'] == expected['report']['return_basis']
assert report['execution']['daily'][0]['cash_open'] == 1 and report['benchmark']['execution']['daily'][0]['cash_open'] == 1
assert len(report['predictions']) == 54
assert report['prediction_metrics']['prediction_count'] > report['prediction_metrics']['complete_target_count']
choose('intradayTestView', 0)
test_evidence, _ = page_evidence()
assert test_evidence['complete_execution'] == report['execution'] and test_evidence['complete_benchmark'] == report['benchmark']
reveal(find('intradayTestTable'))
shot('q32-native-test-account-en')
choose('intradayTestView', 4)
assert page_evidence()[0]['complete_model'] == report['model']
assert controller.selectionEvidence['final_training_count'] == 180
assert controller.selectionEvidence['inner_training_count'] == 150
reveal(find('intradayTestTable'))
shot('q32-native-final-fit-en')
for view in (6, 7, 8, 9, 10, 11, 12, 13, 14):
    choose('intradayTestView', view)
    assert controller.tableModel.totalRows > 0
assert controller._risk_report['experiment_id'] == controller._test_root['experiment_id']
assert controller._risk_report['strategy_diagnostics']['status'] == controller._risk_report['benchmark_diagnostics']['status'] == 'AVAILABLE'
tested = root/'test-v3.json'
file_action('intradayTestSaveButton', 'intradayTestSaveDialog', tested)
test_bytes = tested.read_bytes()
core.load_intraday_dataset, research.load_intraday_dataset = forbidden, forbidden
file_action('intradayTestOpenButton', 'intradayTestOpenDialog', tested)
core.load_intraday_dataset, research.load_intraday_dataset = real_load, original_functions[1][2]
assert controller._selection_proof == controller._test_proof == 'RECORDED'
assert find('intradayFinalSourcePath').property('text') == find('intradayFinalDataPath').property('text') == ''
assert controller._locators == ('', '') and controller._test_content == test_bytes
assert str(tested) in find('intradayFinalCompletedPaths').property('text')
print('Q32_NATIVE_ONE_FINAL_FIT_FULL_TEST_ACCOUNT_MODEL_RISK_OPEN_OK', flush=True)

# Selection and TEST each require their own full replay proof.
locations(ordinary, moved_data)
click('intradayTestReplayButton'); complete(status='FAILED')
assert controller._selection_proof == 'RECORDED' and controller._test_proof == 'REPLAY_FAILED'
assert controller._test_content == test_bytes
locations(moved_study, moved_data)
loads.clear(); core.load_intraday_dataset = counted_load; research.load_intraday_dataset = forbidden
click('intradaySelectionReplayButton'); complete()
assert loads == [str(moved_data)] and controller._selection_proof == 'REPLAY_MATCH'
assert controller._test_proof == 'REPLAY_FAILED'
loads.clear()
click('intradayTestReplayButton'); complete()
core.load_intraday_dataset, research.load_intraday_dataset = real_load, original_functions[1][2]
assert loads == [str(moved_data)]
assert controller._selection_proof == controller._test_proof == 'REPLAY_MATCH'
assert controller._test_content == test_bytes and selected.read_bytes() == selected_bytes and tested.read_bytes() == test_bytes

# A real final computation can complete after its two location inputs change.
before = proof_state()
real_run, ready, release = core.run_intraday_final_test, threading.Event(), threading.Event()
def delayed_run(*args, **kwargs):
    result = real_run(*args, **kwargs); ready.set(); assert release.wait(30); return result
core.run_intraday_final_test = delayed_run
click('intradayRunTestButton'); wait_ready(ready)
locations(moved_study, root/'missing-q5.json')
release.set(); complete(); core.run_intraday_final_test = real_run
assert controller.notice == 'STALE_INPUT' and proof_state() == before
click('intradayRunTestButton'); complete(status='FAILED')
assert proof_state() == before
locations(moved_study, moved_data)
click('intradayRunTestButton'); complete()
assert controller._selection_proof == 'REPLAY_MATCH' and controller._test_proof == 'COMPUTED'
assert controller._test_content == test_bytes and not controller.notice

# Save-as changes path without artifact revision; same-ID Open changes revision.
# Delay only delivery of a real Freeze, then simulate those completed source updates.
file_action('intradayFinalThresholdOpenButton', 'intradayFinalThresholdSourceDialog', moved_study)
alias = root/'same-id-q31-copy.json'; alias.write_bytes(moved_study.read_bytes())
for change in ('save_as_path', 'same_id_reopen', 'final_selection_binding'):
    before = proof_state()
    prior_revision, prior_id = source_ui._artifact_revision, source_ui._root['experiment_id']
    ready, release = threading.Event(), threading.Event()
    core.freeze_intraday_threshold_selection = delayed_freeze
    click('intradayFreezeThresholdButton'); wait_ready(ready)
    if change == 'save_as_path':
        source_ui._path = str(alias); source_ui.changed.emit()
        assert source_ui._artifact_revision == prior_revision
    elif change == 'same_id_reopen':
        source_ui._apply(experiments.load_strategy_experiment(alias), path=str(alias), opened=True)
        assert source_ui._artifact_revision == prior_revision + 1
    else:
        controller._binding_revision += 1; controller.changed.emit()
    assert source_ui._root['experiment_id'] == prior_id
    release.set(); complete(); core.freeze_intraday_threshold_selection = real_freeze
    assert controller.notice == 'STALE_INPUT' and proof_state() == before
print('Q32_NATIVE_REPLAY_PROOF_LOCATION_AND_FREEZE_CAPTURE_RECOVERY_OK', flush=True)

# Switching from a V3-only view to an ordinary Selection must restore its menu.
choose('intradayTestView', 16)
assert development.selectCandidate(1)
click('intradayFreezeButton'); complete()
assert not controller.hasDevSelection and not controller.hasThresholdSelection
assert controller._selection_root['artifact_schema_version'] == core.INTRADAY_SELECTION_V2_VERSION
assert controller.viewIndex == find('intradayTestView').property('currentIndex') == 0
assert not controller.selectView(15)
click('intradayRunTestButton'); complete()
assert controller._test_root['artifact_schema_version'] == core.INTRADAY_TEST_EXPERIMENT_V2_VERSION
assert controller.viewIndex == 0 and controller.tableModel.totalRows == 1
# The existing Q25 six-MSE display needs only a narrow compatibility sentinel.
file_action('intradaySelectionOpenButton', 'intradaySelectionOpenDialog', root/'legacy-selection-v2.json')
assert controller.hasDevSelection and not controller.hasThresholdSelection
choose('intradayTestView', 15)
assert controller.tableModel.totalRows == 6 and 'inner_mse' in controller._columns
assert 'Lowest pooled COMPLETE MSE' in find('intradayFinalMethod').property('text')
choose('intradayTestView', 16)
assert controller.tableModel.totalRows == 27
assert not find('intradayFinalThresholdAccount').property('visible')
assert not controller.selectView(19)
file_action('intradayTestOpenButton', 'intradayTestOpenDialog', tested)

# Actual compact scrolling, a second ledger page, bilingual labels and full JSON.
window.setWidth(1024); window.setHeight(600); app.processEvents()
assert session.i18n.setLanguage('zh-CN'); app.processEvents()
assert find('intradayFreezeThresholdButton').property('text') == '冻结经济阈值'
assert 'NONE 未复权' in find('intradayFinalReturnBasis').property('text')
choose('intradayTestView', 21); choose('intradayFinalThresholdAccount', 0)
scroll = find('intradayFinalScroll'); flick = scroll.property('contentItem')
assert flick.property('contentHeight') > scroll.property('availableHeight')
bar = find('intradayFinalScrollBar'); thumb = bar.property('contentItem')
start = thumb.mapToScene(thumb.boundingRect().center()).toPoint()
end = bar.mapToScene(QPointF(bar.width()/2, bar.height()-2)).toPoint()
before_y = flick.property('contentY')
QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
QTest.mouseMove(window, end, 60); QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
app.processEvents()
assert flick.property('contentY') > before_y
pager = nested(find('intradayTestTable'), 'PixelPagination')
next_button = next(child for child in pager.findChildren(QObject) if child.property('glyph') == 'next')
assert controller.tableModel.page == 1 and controller.tableModel.totalPages > 1
click_obj(next_button)
assert controller.tableModel.page == 2
assert json.loads(controller.currentPageEvidence)['rows'] == accounts[0]['execution']['ledger'][100:200]
shot('q32-native-compact-dev-ledger-page2-zh')
choose('intradayTestView', 4)
click('intradayFinalPageEvidenceButton')
shown = json.loads(find('intradayFinalPageEvidenceText').property('text'))
assert shown['complete_model'] == report['model']
shot('q32-native-compact-final-model-json-zh')
QTest.keyClick(window, Qt.Key_Escape); app.processEvents()
choose('intradayTestView', 10); reveal(find('intradayTestTable'))
assert controller.tableModel.totalRows > 0
shot('q32-native-compact-test-risk-zh')
assert session.i18n.setLanguage('en'); app.processEvents()
assert 'one shared inner model' in find('intradayTestView').property('model')[16]
# Q87 opens the saved economic TEST through the actual A/B QML entry.
window.setWidth(1280); window.setHeight(1000); app.processEvents()
click('intradaySavedComparisonTab')
file_action('intradaySavedLeftOpen', 'intradaySavedOpenLeftDialog', ordinary, comparison)
file_action('intradaySavedRightOpen', 'intradaySavedOpenRightDialog', ordinary, comparison)
click('intradaySavedCompareButton'); complete(comparison)
file_action('intradaySavedLeftOpen', 'intradaySavedOpenLeftDialog', tested, comparison)
click('intradaySavedCompareButton'); complete(comparison)
assert comparison.leftSource['is_test'] and not comparison.canAnalyzePortfolio
assert comparison._result['left']['experiment_id'] == json.loads(test_bytes)['experiment_id']
assert not comparison._result['delta_allowed']
assert all(row['delta']['value'] is None and row['delta']['unavailable_reason'] == 'TEST_DESCRIPTIVE_ONLY'
           for group in ('strategy_metrics', 'benchmark_metrics') for row in comparison._result[group])
comparison_before = (comparison._sources.copy(), comparison._result.copy(), comparison._bound_sources.copy())
file_action('intradaySavedLeftOpen', 'intradaySavedOpenLeftDialog', selected, comparison, 'FAILED')
assert (comparison._sources, comparison._result, comparison._bound_sources) == comparison_before
assert comparison.error and controller._test_content == test_bytes
file_action('intradaySavedLeftOpen', 'intradaySavedOpenLeftDialog', tested, comparison)
click('intradaySavedCompareButton'); complete(comparison)
assert not comparison._result['delta_allowed'] and not comparison.error
assert selected.read_bytes() == selected_bytes and tested.read_bytes() == test_bytes
assert all(path.read_bytes() == content for path, content in originals.items())
(root/'q32-native-warnings.json').write_text(json.dumps(warnings, ensure_ascii=False, indent=2))
assert sum('Main.qml:199' in item for item in warnings) == 2, warnings
assert sum('HomePage.qml:74' in item for item in warnings) == 3, warnings
assert all('Main.qml:199' in item or 'HomePage.qml:74' in item for item in warnings), warnings
assert session.shutdown()
engine.deleteLater(); app.processEvents()
print('NATIVE_THRESHOLD_FINAL_PASS', flush=True)
'''
    completed = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(ordinary_path), str(study_path), str(data.path)],
        cwd=ROOT, env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software",
                      "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT / "tests")))},
        text=True, capture_output=True, timeout=480)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "NATIVE_THRESHOLD_FINAL_PASS" in completed.stdout
