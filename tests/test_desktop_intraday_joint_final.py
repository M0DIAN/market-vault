"""Native explicit joint Freeze, recorded evidence and independent TEST V4."""

from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys

import pytest

# The standard Qt-free CI installation must skip before any research fixture.
pytest.importorskip("PySide6")

from market_vault.research import intraday_research as research
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.intraday_joint_selection import run_intraday_joint_selection
from market_vault.research.strategy_experiment import write_strategy_experiment
from test_strategy_intraday_joint_final import joint_quadratic_case  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]


def test_native_joint_freeze_accounts_test_replay_and_capture(joint_quadratic_case, tmp_path):
    data, source, source_path, _, _, study_path, _ = joint_quadratic_case
    plan = source.as_dict()["plan"]
    short_plan = deepcopy(plan.get("comparison_plan", plan))
    short_plan["walk_forward"]["minimum_train_days"] = 10
    short_plan["strategies"] = [short_plan["strategies"][0]]
    short = create_intraday_experiment(plan=short_plan, report=research.run_intraday_research(short_plan))
    short_path = write_strategy_experiment(short, path=tmp_path / "short-source.json").path
    unavailable = run_intraday_joint_selection(short_path, expected_experiment_id=short.experiment_id,
        cost_index=0, candidate_index=0,
        expected_candidate_id=short.as_dict()["report"]["groups"][0]["results"][0]["candidate_id"])
    write_strategy_experiment(unavailable, path=tmp_path / "unavailable-joint.json")
    (tmp_path / "settings.yaml").write_text("storage:\n  root_dir: ./data\n")
    script = r'''
import json, sys, threading, time
from pathlib import Path
from PySide6.QtCore import QObject, QMetaObject, QPointF, QUrl, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QJSValue
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from market_vault.application import build_application_context
from market_vault.desktop.bootstrap import create_qml_application_session
from market_vault.desktop.localization import translation_keys_match
from market_vault.desktop.preferences import DesktopPreferenceStore
from market_vault.research import intraday_final_test as core
from market_vault.research import intraday_joint_selection as joint
from market_vault.research import intraday_research as research
from market_vault.research import strategy_experiment as experiments

root, ordinary, study, data = map(Path, sys.argv[1:])
originals = {path: path.read_bytes() for path in (ordinary, study, data)}
expected = json.loads(originals[study])
frozen_window = expected['report']['final_dev']
assert frozen_window['selected_index'] == 12 and frozen_window['selected_recipe']['kind'] == 'QUADRATIC_RIDGE'
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
window = engine.rootObjects()[0]; window.setWidth(1280); window.setHeight(1100)
owner = session.context_properties['quantResearchController']
controller, source_ui = owner.intradayFinalController, owner.intradayJointSelectionController
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
    scroll = find('intradayFinalScroll')
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

def complete(status='SUCCESS'):
    deadline = time.monotonic() + 90
    while controller.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    app.processEvents()
    assert not controller.busy and controller.status == status, (controller.status, controller.error, warnings)

def file_action(button, dialog_name, path, status='SUCCESS'):
    click(button); dialog = find(dialog_name)
    assert dialog.property('visible')
    assert dialog.setProperty('selectedFile', QUrl.fromLocalFile(str(path)))
    assert QMetaObject.invokeMethod(dialog, 'accepted', Qt.DirectConnection)
    QMetaObject.invokeMethod(dialog, 'close', Qt.DirectConnection)
    complete(status)

def evidence():
    window.requestActivate(); QTest.qWait(20)
    click('intradayFinalPageEvidenceButton')
    assert find('intradayFinalPageEvidenceDialog').property('visible')
    obj = find('intradayFinalPageEvidenceText')
    assert obj.property('readOnly') and obj.property('selectByMouse')
    assert engine.newQObject(obj).property('wrapMode').toInt() != 0
    result = json.loads(obj.property('text'))
    QTest.keyClick(window, Qt.Key_Escape); app.processEvents()
    assert not find('intradayFinalPageEvidenceDialog').property('visible') and obj.property('text') == '', (
        find('intradayFinalPageEvidenceDialog').property('visible'), len(obj.property('text')))
    return result

def locations(source, q5):
    click('intradayFinalLocationsButton')
    assert find('intradayFinalSourcePath').property('label') == session.i18n.catalog['final.joint_source_override']
    assert find('intradayFinalSourcePath').setProperty('text', str(source))
    assert find('intradayFinalDataPath').setProperty('text', str(q5))
    click('intradayFinalLocationsDone')

def wait_ready(ready):
    deadline = time.monotonic() + 90
    while not ready.is_set() and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    assert ready.is_set()

def state():
    return (controller._selection_content, controller._test_content, controller.selectionPath, controller.testPath,
            controller._selection_proof, controller._test_proof)

def shot(name):
    reveal(find('intradayTestTable')); QTest.qWait(30)
    assert window.grabWindow().save(str(root / (name + '.png')))

def forbidden(*args, **kwargs): raise AssertionError('Unexpected Q5 access, fit, reselection or execution')

click('quantIntradayTab'); click('intradayFinalTab'); app.processEvents()
assert not controller.canFreezeJoint and not controller.selectionLoaded
source_ui._apply(experiments.load_strategy_experiment(study))
assert source_ui.resultLoaded and source_ui.experimentPath == ''
assert not controller.canFreezeJoint and not controller.freezeJointSelection()
file_action('intradayFinalJointOpenButton', 'intradayFinalJointSourceDialog', ordinary, 'FAILED')
assert source_ui.experimentPath == '' and not controller.selectionLoaded
file_action('intradayFinalJointOpenButton', 'intradayFinalJointSourceDialog', root / 'unavailable-joint.json')
assert not controller.canFreezeJoint and not find('intradayFreezeJointButton').property('enabled')
file_action('intradayFinalJointOpenButton', 'intradayFinalJointSourceDialog', study)
assert controller.canFreezeJoint and not controller.selectionLoaded and not controller.testLoaded
assert str(study) in controller.jointSourceDetails and expected['experiment_id'] in controller.jointSourceDetails

# Freeze/Open bind only saved evidence. No Q5, original source, fit or Q6 call.
blocked = [(core, 'load_intraday_dataset'), (research, 'load_intraday_dataset'), (core, 'fit_quadratic_rows'),
    (research, 'fit_ridge_rows'), (joint, '_fit'), (joint, '_select'), (joint, 'run_intraday_execution'),
    (core, 'run_intraday_execution')]
functions = [(module, key, getattr(module, key)) for module, key in blocked]
actual_open = Path.open
forbidden_paths = {ordinary.resolve(), data.resolve()}
def guarded_open(path, mode='r', *args, **kwargs):
    if path.resolve() in forbidden_paths and ('r' in mode or '+' in mode):
        raise FileNotFoundError('Original source or Q5 unavailable: ' + str(path))
    return actual_open(path, mode, *args, **kwargs)
Path.open = guarded_open
for module, key in blocked: setattr(module, key, forbidden)
gui_thread, freeze_calls = threading.get_ident(), []
real_freeze = core.freeze_intraday_joint_selection
def measured_freeze(path, **kwargs):
    assert threading.get_ident() != gui_thread
    freeze_calls.append((str(path), kwargs['expected_experiment_id']))
    return real_freeze(path, **kwargs)
core.freeze_intraday_joint_selection = measured_freeze
click('intradayFreezeJointButton'); complete()
assert freeze_calls == [(str(study), expected['experiment_id'])]
assert controller.hasJointSelection and controller.hasEconomicSelection and not controller.hasThresholdSelection
assert controller._selection_root['artifact_schema_version'] == core.INTRADAY_SELECTION_V4_VERSION
frozen = controller._selection_root
assert frozen['report']['dev_selection']['final_dev'] == frozen_window
assert frozen['report']['dev_selection']['method'] == expected['report']['method']
assert frozen['plan']['source_experiment']['path'] == str(study)
assert frozen['report']['candidate']['strategy'] == frozen_window['selected_recipe']
assert controller._selection_proof == 'FROZEN' and not controller.testLoaded
assert controller.viewIndex == 15 and controller.thresholdAccountIndex == frozen_window['selected_index']
assert controller.tableModel.totalRows == 24 and 'FIRST_DECLARED' in find('intradayFinalMethod').property('text')
assert 'NONE unadjusted' in find('intradayFinalReturnBasis').property('text')
selected, tested = root / 'selection-v4.json', root / 'test-v4.json'
file_action('intradaySelectionSaveButton', 'intradaySelectionSaveDialog', selected)
selected_bytes = selected.read_bytes()
file_action('intradaySelectionOpenButton', 'intradaySelectionOpenDialog', selected)
assert controller._selection_proof == 'RECORDED' and controller._selection_content == selected_bytes
for module, key, value in functions: setattr(module, key, value)
Path.open = actual_open
assert str(selected) in find('intradayFinalCompletedPaths').property('text')
print('Q38_NATIVE_FROZEN_SAVED_EVIDENCE_ONLY', flush=True)

accounts = frozen_window['family_results']
assert controller.thresholdAccountOptions == [{'candidate_index': member['candidate_index'], 'model_index': member['model_index'],
    'strategy_kind': member['strategy']['kind'], 'alpha': member['strategy']['alpha'],
    'threshold_bps': member['strategy']['threshold'] * 10000,
    'chosen': member['candidate_index'] == frozen_window['selected_index']} for member in accounts]
overview = evidence()
assert [row['complete_recipe'] for row in overview['rows']] == [member['strategy'] for member in accounts]
assert [row['joint_model_index'] for row in overview['rows']] == [member['model_index'] for member in accounts]
assert overview['feature_fields'] == frozen['report']['context']['feature_fields']
assert overview['source_selection'] == expected['plan']['selection']
assert overview['fixed_reference'] == frozen['report']['dev_selection']['fixed_reference']
assert overview['frozen_candidate'] == frozen['report']['candidate'] and overview['return_basis'] == expected['report']['return_basis']
assert overview['execution_input'] == frozen_window['execution_input']
shot('q38-native-24-frozen-recipes-en')
choose('intradayTestView', 16)
model_evidence = evidence()
assert model_evidence['complete_models'] == frozen_window['models']
assert {row['joint_model_index'] for row in controller._evidence_rows} == set(range(6))
assert {row['model_stage'] for row in controller._evidence_rows} == {'LINEAR_FEATURES', 'INPUT_TRANSFORM', 'GENERATED_TERMS'}
assert all(row['model_threshold_bps'] == member['strategy']['threshold'] * 10000
    for row in controller._evidence_rows for member in frozen_window['models'] if row['joint_model_index'] == member['model_index'])
shot('q38-native-six-shared-models-en')
choose('intradayTestView', 17)
keys = controller._evidence_rows
for key in ('history_training_keys', 'history_purged_keys', 'training_keys', 'purged_keys', 'validation_keys'):
    assert [row['value'] for row in keys if row['threshold_role'] == key] == frozen_window[key]
assert [row['actual_label_end_time'] for row in keys if row['threshold_role'] == 'HISTORY_TARGET'] == [
    row['actual_label_end_time'] for row in frozen_window['history_targets']]
assert {row['value'] for row in keys if row['threshold_role'].endswith('boundary')} == {
    frozen_window['history_boundary'], frozen_window['training_boundary']}

# Real account/view choices expose every member's raw records. The same JSON
# binding is opened above and below; browse all 24 without repeated large dialogs.
different_target = False
for account_index, member in enumerate(accounts):
    choose('intradayFinalThresholdAccount', account_index)
    shown = find('intradayFinalThresholdAccount').property('currentText')
    assert session.i18n.catalog['prediction_quality.' + member['strategy']['kind']] in shown and 'undefined' not in shown
    assert f"alpha={member['strategy']['alpha']:g}" in shown and f"{member['strategy']['threshold'] * 10000:g} bp" in shown
    for view, field in ((18, 'decisions'), (19, 'trades'), (20, 'daily'), (21, 'ledger'), (22, 'transactions')):
        choose('intradayTestView', view)
        assert controller.tableModel.totalRows == len(member['execution'][field])
        raw = json.loads(controller.currentPageEvidence)
        assert raw['account_strategy'] == member['strategy']
        assert raw['account']['candidate_index'] == account_index and raw['account']['model_index'] == member['model_index']
        assert raw['execution_metadata']['metrics'] == member['execution']['metrics']
        rows = raw['rows']
        if field == 'decisions':
            assert [{key: value for key, value in row.items()
                if key not in ('joint_model_index', 'model_threshold_bps', 'shared_prediction_target')} for row in rows] == member['execution'][field][:100]
            assert raw['shared_model_predictions'] == frozen_window['models'][member['model_index']]
            for row in rows:
                assert row['target'] == ('LONG' if row['score'] > member['strategy']['threshold'] else 'FLAT')
                different_target |= row['target'] != row['shared_prediction_target']
        else:
            assert rows == member['execution'][field][:100]
        assert controller._selection_content == selected_bytes and controller.frozenCandidate['strategy'] == frozen_window['selected_recipe']
assert different_target
for view, key in ((23, 'sessions'), (24, 'prices')):
    choose('intradayTestView', view)
    assert evidence()['rows'] == frozen_window[key][:100]
print('Q38_NATIVE_SIX_MODELS_ALL_24_ACCOUNTS_AND_FROZEN_BINDING', flush=True)

# Copies relocate the bound study/Q5 without moving or changing shared fixtures.
moved_study, moved_data = root / 'relocated-joint.json', root / 'relocated-q5.json'
moved_study.write_bytes(originals[study]); moved_data.write_bytes(originals[data])
forbidden_paths = {study.resolve(), data.resolve()}
Path.open = guarded_open
click('intradayRunTestButton'); complete('FAILED')
assert controller._selection_content == selected_bytes and not controller.testLoaded
locations(ordinary, moved_data)
click('intradayRunTestButton'); complete('FAILED')
assert controller._selection_proof == 'RECORDED' and not controller.testLoaded
locations(moved_study, moved_data)
loads, fits = [], []
real_load = core.load_intraday_dataset
real_fit, real_joint_fit = core.fit_quadratic_rows, joint._fit
def counted_load(path): loads.append(str(path)); return real_load(path)
def counted_fit(*args, **kwargs): fits.append(1); return real_fit(*args, **kwargs)
core.load_intraday_dataset, joint._fit = counted_load, forbidden
core.fit_quadratic_rows = counted_fit
click('intradayRunTestButton'); complete()
core.load_intraday_dataset, joint._fit = real_load, real_joint_fit
core.fit_quadratic_rows = real_fit
assert loads == [str(moved_data)] and fits == [1]
assert controller._test_root['artifact_schema_version'] == core.INTRADAY_TEST_EXPERIMENT_V4_VERSION
report = controller._test_root['report']
assert controller.viewIndex == find('intradayTestView').property('currentIndex') == 0
assert controller._selection_proof == 'RECORDED' and controller._test_proof == 'COMPUTED'
assert report['strategy'] == frozen_window['selected_recipe']
assert report['context']['training_keys'] == frozen_window['history_training_keys']
assert report['context']['purged_keys'] == frozen_window['history_purged_keys']
assert report['model']['training_keys'] == frozen_window['history_training_keys'] != frozen_window['training_keys']
assert report['model']['training_boundary'] == frozen_window['history_boundary'] != frozen_window['training_boundary']
assert report['return_basis'] == expected['report']['return_basis']
assert report['prediction_metrics']['prediction_count'] > report['prediction_metrics']['complete_target_count']
assert report['execution']['daily'][0]['cash_open'] == report['benchmark']['execution']['daily'][0]['cash_open'] == 1
assert len(controller.equitySeries) == 2
assert evidence()['complete_execution'] == report['execution']
assert evidence()['complete_benchmark'] == report['benchmark']
shot('q38-native-independent-test-en')
choose('intradayTestView', 4)
assert evidence()['complete_model'] == report['model'] and evidence()['final_context'] == report['context']
assert {row['model_stage'] for row in controller._evidence_rows} == {'INPUT_TRANSFORM', 'GENERATED_TERMS'}
choose('intradayTestView', 5)
assert evidence()['rows'] == report['predictions'][:100]
choose('intradayTestView', 10)
assert controller.tableModel.totalRows > 0 and controller._risk_report['experiment_id'] == controller._test_root['experiment_id']
file_action('intradayTestSaveButton', 'intradayTestSaveDialog', tested)
test_bytes = tested.read_bytes()
occupied = root / 'occupied.json'; occupied.write_bytes(originals[ordinary])
before = state()
file_action('intradayTestSaveButton', 'intradayTestSaveDialog', occupied, 'FAILED')
assert state() == before and occupied.read_bytes() == originals[ordinary]
for module, key in blocked: setattr(module, key, forbidden)
file_action('intradayTestOpenButton', 'intradayTestOpenDialog', tested)
for module, key, value in functions: setattr(module, key, value)
assert controller._selection_proof == controller._test_proof == 'RECORDED'
assert controller.viewIndex == 0 and controller._locators == ('', '')
assert find('intradayFinalSourcePath').property('text') == find('intradayFinalDataPath').property('text') == ''
assert controller._test_content == test_bytes
print('Q38_NATIVE_ONE_FINAL_FIT_TEST_SAVE_OPEN_IMMUTABILITY', flush=True)

locations(ordinary, moved_data)
click('intradayTestReplayButton'); complete('FAILED')
assert controller._selection_proof == 'RECORDED' and controller._test_proof == 'REPLAY_FAILED'
locations(moved_study, moved_data)
click('intradaySelectionReplayButton'); complete()
assert controller._selection_proof == 'REPLAY_MATCH' and controller._test_proof == 'REPLAY_FAILED'
click('intradayTestReplayButton'); complete()
assert controller._selection_proof == controller._test_proof == 'REPLAY_MATCH'
assert controller._test_content == test_bytes and selected.read_bytes() == selected_bytes and tested.read_bytes() == test_bytes

# Replay proof describes the captured inputs; a changed location cannot inherit
# a successful completion from the worker.
ready, release = threading.Event(), threading.Event()
real_replay = experiments.replay_strategy_experiment
def delayed_replay(*args, **kwargs):
    result = real_replay(*args, **kwargs); ready.set(); assert release.wait(30); return result
experiments.replay_strategy_experiment = delayed_replay
click('intradayTestReplayButton'); wait_ready(ready)
locations(moved_study, root / 'changed-q5.json')
release.set(); complete()
experiments.replay_strategy_experiment = real_replay
assert controller.notice == 'STALE_INPUT' and controller._test_proof == 'REPLAY_STALE_INPUT'
assert controller._selection_proof == 'REPLAY_MATCH' and controller._test_content == test_bytes
locations(moved_study, moved_data)
click('intradayTestReplayButton'); complete()
assert controller._test_proof == 'REPLAY_MATCH' and not controller.notice

# Hold an actual TEST computation, alter its location, then retry after failure.
before, real_run = state(), core.run_intraday_final_test
ready, release = threading.Event(), threading.Event()
def delayed_run(*args, **kwargs):
    result = real_run(*args, **kwargs); ready.set(); assert release.wait(30); return result
core.run_intraday_final_test = delayed_run
click('intradayRunTestButton'); wait_ready(ready)
locations(moved_study, root / 'missing-q5.json')
release.set(); complete(); core.run_intraday_final_test = real_run
assert controller.notice == 'STALE_INPUT' and state() == before
click('intradayRunTestButton'); complete('FAILED')
assert state() == before
locations(moved_study, moved_data)
click('intradayRunTestButton'); complete()
assert not controller.notice and controller._test_proof == 'COMPUTED' and controller._test_content == test_bytes

# Source save-as, same-ID reopening and a new final binding are distinct stale
# inputs; both successful and failed worker deliveries retain the prior result.
file_action('intradayFinalJointOpenButton', 'intradayFinalJointSourceDialog', moved_study)
alias = root / 'same-id-joint.json'; alias.write_bytes(originals[study])
for change in ('save_as_path', 'same_id_reopen', 'final_binding', 'stale_failure'):
    before = state()
    prior_revision, prior_id = source_ui._artifact_revision, source_ui._root['experiment_id']
    ready, release = threading.Event(), threading.Event()
    def delayed_freeze(*args, **kwargs):
        result = measured_freeze(*args, **kwargs)
        ready.set(); assert release.wait(30)
        if change == 'stale_failure': raise ValueError('Joint Freeze worker delivery failure')
        return result
    core.freeze_intraday_joint_selection = delayed_freeze
    click('intradayFreezeJointButton'); wait_ready(ready)
    if change == 'save_as_path':
        source_ui._path = str(alias); source_ui.changed.emit()
        assert source_ui._artifact_revision == prior_revision
    elif change in ('same_id_reopen', 'stale_failure'):
        source_ui._apply(experiments.load_strategy_experiment(alias), path=str(alias), opened=True)
        assert source_ui._artifact_revision == prior_revision + 1
    else:
        controller._binding_revision += 1; controller.changed.emit()
    assert source_ui._root['experiment_id'] == prior_id
    release.set(); complete('STALE_INPUT' if change == 'stale_failure' else 'SUCCESS')
    assert controller.notice == 'STALE_INPUT' and not controller.error and state() == before
before = state()
def failed_freeze(*args, **kwargs):
    measured_freeze(*args, **kwargs)
    raise ValueError('Joint Freeze current worker failure')
core.freeze_intraday_joint_selection = failed_freeze
click('intradayFreezeJointButton'); complete('FAILED')
assert 'Joint Freeze current worker failure' in controller.error and state() == before
core.freeze_intraday_joint_selection = measured_freeze
click('intradayFreezeJointButton'); complete()
assert not controller.notice and controller._selection_proof == 'FROZEN' and not controller.testLoaded
assert controller.thresholdAccountIndex == frozen_window['selected_index']
file_action('intradayTestOpenButton', 'intradayTestOpenDialog', tested)
before = state()
file_action('intradayTestOpenButton', 'intradayTestOpenDialog', ordinary, 'FAILED')
assert state() == before
print('Q38_NATIVE_RELOCATION_REPLAY_STALE_FAILURE_RETRY', flush=True)

window.setWidth(1024); window.setHeight(600); app.processEvents()
assert session.i18n.setLanguage('zh-CN')
assert find('intradayFreezeJointButton').property('text') == '冻结联合配方'
assert 'NONE 未复权' in find('intradayFinalReturnBasis').property('text')
choose('intradayTestView', 21); choose('intradayFinalThresholdAccount', 23)
scroll = find('intradayFinalScroll'); flick = scroll.property('contentItem')
assert flick.property('contentHeight') > scroll.property('availableHeight')
pager = nested(find('intradayTestTable'), 'PixelPagination')
assert controller.tableModel.page == 1 and controller.tableModel.totalPages > 1
click_obj(next(child for child in pager.findChildren(QObject) if child.property('glyph') == 'next'))
assert controller.tableModel.page == 2 and evidence()['rows'] == accounts[23]['execution']['ledger'][100:200]
assert '浏览账户不会改变冻结配方' in find('intradayFinalThresholdDecisionNote').property('text')
shot('q38-native-compact-account-page2-zh')
choose('intradayTestView', 16)
assert evidence()['complete_models'] == frozen_window['models']
shot('q38-native-compact-six-models-zh')
choose('intradayTestView', 4)
assert evidence()['complete_model'] == report['model']
shot('q38-native-compact-final-fit-zh')
assert controller._selection_root['report']['candidate']['strategy'] == frozen_window['selected_recipe']
Path.open = actual_open
assert all(path.read_bytes() == content for path, content in originals.items())
assert selected.read_bytes() == selected_bytes and tested.read_bytes() == test_bytes
assert all('Main.qml:199' in item or 'HomePage.qml:74' in item for item in warnings), warnings
(root / 'q38-native-warnings.json').write_text(json.dumps(warnings, ensure_ascii=False, indent=2))
(root / 'q38-native-evidence.json').write_text(json.dumps({
    'selection': json.loads(selected_bytes), 'test': json.loads(test_bytes),
    'freeze_calls': freeze_calls, 'normal_test_q5_loads': loads, 'normal_test_fit_count': len(fits)}, ensure_ascii=False))
core.freeze_intraday_joint_selection = real_freeze
assert session.shutdown()
engine.deleteLater(); app.processEvents()
print('NATIVE_JOINT_FINAL_PASS', flush=True)
'''
    completed = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(source_path), str(study_path),
        str(data.path)], cwd=ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software",
             "PYTHONPATH": str(ROOT / "src")}, text=True, capture_output=True, timeout=360)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "NATIVE_JOINT_FINAL_PASS" in completed.stdout
