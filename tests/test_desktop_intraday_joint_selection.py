"""Real native joint-family accounts, refits and immutable action recovery."""

from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys

import pytest

# CI without Qt skips before importing research helpers or creating saved Q5.
pytest.importorskip("PySide6")

from market_vault.research import intraday_research as research
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.intraday_joint_selection import run_intraday_joint_selection
from market_vault.research.strategy_experiment import canonical_json, write_strategy_experiment
from test_strategy_intraday_joint_selection import joint_case, quadratic_dev_case  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]


def test_native_joint_family_refits_artifacts_replay_and_recovery(joint_case, tmp_path):
    data, source, source_path, _, study, _, _ = joint_case
    expected = study.as_dict()["report"]
    (tmp_path / "expected.json").write_bytes(canonical_json(expected))
    short_plan = deepcopy(source.as_dict()["plan"]["comparison_plan"])
    short_plan["walk_forward"]["minimum_train_days"] = 10
    short_plan["strategies"] = [short_plan["strategies"][0]]
    short = create_intraday_experiment(plan=short_plan, report=research.run_intraday_research(short_plan))
    short_path = write_strategy_experiment(short, path=tmp_path / "short-source.json").path
    unavailable = run_intraday_joint_selection(short_path, expected_experiment_id=short.experiment_id, cost_index=0,
        candidate_index=0, expected_candidate_id=short.as_dict()["report"]["groups"][0]["results"][0]["candidate_id"])
    write_strategy_experiment(unavailable, path=tmp_path / "unavailable.json")
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
from market_vault.research import intraday_research as research
from market_vault.research import intraday_joint_selection as joint
from market_vault.research import strategy_experiment as experiments

root, source_path, data_path = map(Path, sys.argv[1:])
source_bytes, data_bytes = source_path.read_bytes(), data_path.read_bytes()
expected = json.loads((root / 'expected.json').read_bytes())
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
research_ui, controller = owner.intradayResearchController, owner.intradayJointSelectionController
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
    scroll = find('intradayJointScroll')
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
    current = obj.property('currentIndex')
    if current != index:
        # Select one destination in the real popup. Closed-combo arrows would
        # apply every intervening view, multiplying unrelated layout work.
        QTest.keyClick(window, Qt.Key_Space)
        assert combo.property('down')  # Popup is open; QQuickPopup* has no Python converter.
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

def complete(target=controller, status='SUCCESS'):
    deadline = time.monotonic() + 60
    while target.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    app.processEvents()
    assert not target.busy and target.status == status, (target.status, target.error, warnings)

def file_action(button, dialog_name, path, target=controller):
    click(button)
    dialog = find(dialog_name)
    assert dialog.property('visible')
    assert dialog.setProperty('selectedFile', QUrl.fromLocalFile(str(path)))
    assert QMetaObject.invokeMethod(dialog, 'accepted', Qt.DirectConnection)
    QMetaObject.invokeMethod(dialog, 'close', Qt.DirectConnection)
    complete(target)

def evidence():
    click('intradayJointEvidenceButton')
    assert find('intradayJointEvidenceDialog').property('visible')
    text = find('intradayJointEvidenceText').property('text')
    result = json.loads(text)
    QTest.keyClick(window, Qt.Key_Escape); app.processEvents()
    assert not find('intradayJointEvidenceDialog').property('visible')
    assert find('intradayJointEvidenceText').property('text') == ''
    return result, text

def displayed(value):
    return find('intradayJointTable').property('cellFormatter').call([QJSValue(value)]).toString()

click('quantIntradayTab'); click('intradayComparisonTab'); QTest.qWait(30)
file_action('intradayExperimentOpenButton', 'intradayExperimentOpenDialog', source_path, research_ui)
click('intradayJointTab'); QTest.qWait(30)
choose('intradayJointCandidate', 3)
assert controller.canRun and not controller.resultLoaded
assert controller.draftSource['cost_index'] == controller.draftSource['candidate_index'] == 1
click('intradayJointRunButton'); complete()
assert controller._root['report'] == expected and controller.proof == 'COMPUTED'
assert controller.resultSummary['strategy']['kind'] == 'QUADRATIC_RIDGE'
assert len(controller.equitySeries) == 3 and controller.returnBasis == expected['return_basis']
assert 'FIRST_DECLARED' in find('intradayJointMethod').property('text')
assert 'COMPLETE holdout labels are not required' in find('intradayJointMethod').property('text')
assert 'does not run Freeze or TEST' in find('intradayJointMethod').property('text')
assert '24-member family' in find('intradayJointMethod').property('text')
assert 'Six fitted models' in find('intradayJointMethod').property('text')
assert 'undefined' not in find('intradayJointScope').property('currentText')
basis = find('intradayJointReturnBasis').property('text')
assert all(text in basis for text in ('NONE unadjusted', 'Split-share adjustment: Not applied',
    'Cash-dividend accounting: Not applied', 'Corporate-action coverage: Unknown'))
assert displayed('total_return') == 'Net compounded account return'
assert displayed('initial_cash') == 'Initial cash' and displayed('final_cash') == 'Final cash'
assert displayed('observed_max_drawdown') != 'observed_max_drawdown'
assert window.grabWindow().save(str(root / 'q36-native-outer-en.png'))

# Every outer account is reachable, including the benchmark's actual decisions.
context = expected['source_experiment']['report']['context']
reference = expected['source_experiment']['report']['groups'][1]['results'][1]
for index, account in enumerate((expected['selected_account'], reference, expected['benchmark'])):
    choose('intradayJointAccount', index)
    for view, field in ((3, 'decisions'), (4, 'trades'), (5, 'daily'), (6, 'ledger'), (7, 'transactions')):
        choose('intradayJointView', view)
        assert controller.tableModel.totalRows == len(account['execution'][field])
        assert evidence()[0]['rows'] == account['execution'][field][:100]
    choose('intradayJointView', 8)
    assert evidence()[0]['rows'] == account.get('fold_contributions', [])
choose('intradayJointView', 2)
assert controller.tableModel.totalRows == 0 and 'Not applicable' in find('intradayJointViewNotice').property('text')
choose('intradayJointAccount', 0)
assert evidence()[0]['complete_models'][0]['model'] == expected['outer_folds'][0]['refit']['model']
choose('intradayJointView', 1)
assert displayed('OUTER_VALIDATION_KEYS') == 'All original outer READY keys'
assert context['folds'][0]['training_boundary'] in evidence()[1]

# Every declared recipe has its own actual account; six shared models are
# complete inspectable evidence instead of four duplicated copies per model.
assert len(controller.scopeOptions) == len(expected['outer_folds']) + 2
for scope_index, inner in ((1, expected['outer_folds'][0]['inner']),
                           (len(expected['outer_folds']) + 1, expected['final_dev'])):
    choose('intradayJointScope', scope_index)
    assert controller.accountIndex == inner['selected_index']
    options = controller.accountOptions
    assert len(options) == 24
    assert [(row['strategy_kind'], row['alpha'], row['threshold_bps']) for row in options] == [
        (kind, alpha, bp) for kind in ('RIDGE', 'QUADRATIC_RIDGE') for alpha in (.1, 1, 10) for bp in (0, 5, 10, 20)]
    assert controller.scopeSummary['training_boundary'] == inner['training_boundary']
    assert controller.scopeSummary['history_boundary'] == inner['history_boundary']
    assert controller.scopeSummary['selected_recipe'] == inner['selected_recipe']
    choose('intradayJointView', 0)
    assert len(controller.equitySeries) == 1
    actual = evidence()[0]
    assert {row['candidate_index'] for row in controller._evidence_rows} == set(range(24))
    assert all(row['strategy_kind'] == inner['family_results'][row['candidate_index']]['strategy']['kind']
        and row['alpha'] == inner['family_results'][row['candidate_index']]['strategy']['alpha']
        for row in controller._evidence_rows)
    assert window.grabWindow().save(str(root / ('q36-native-inner-accounts.png' if scope_index == 1 else 'q36-native-final-accounts.png')))
    # One complete 24-account range proves all account indices reach every
    # execution view; final DEV reuses that binding and checks the last member.
    indices = range(24) if scope_index == 1 else (23,)
    for account_index in indices:
        member = inner['family_results'][account_index]
        choose('intradayJointAccount', account_index)
        assert f"alpha={member['strategy']['alpha']:g}" in find('intradayJointAccount').property('currentText')
        for view, field in ((3, 'decisions'), (4, 'trades'), (5, 'daily'), (6, 'ledger'), (7, 'transactions')):
            choose('intradayJointView', view)
            actual, _ = evidence()
            assert actual['rows'] == member['execution'][field][:100]
            assert actual['execution_metadata']['execution_id'] == member['execution']['execution_id']
            assert actual['account']['model_index'] == member['model_index']
            assert controller.tableModel.totalRows == len(member['execution'][field])
    choose('intradayJointAccount', 3); choose('intradayJointView', 3)
    assert any(left['target'] != right['target'] for left, right in zip(
        inner['models'][0]['predictions'], inner['family_results'][3]['execution']['decisions']))
    assert evidence()[0]['rows'] == inner['family_results'][3]['execution']['decisions'][:100]
    choose('intradayJointView', 1)
    assert inner['training_boundary'] in evidence()[1] and inner['history_training_keys'][0] in evidence()[1]
    choose('intradayJointView', 9)
    assert evidence()[0]['rows'] == inner['sessions']
    choose('intradayJointView', 10)
    assert evidence()[0]['rows'] == inner['prices'][:100]
    choose('intradayJointView', 2)
    actual, text = evidence()
    assert len(actual['complete_models']) == 6
    for recorded, raw in zip(actual['complete_models'], inner['models'], strict=True):
        assert all(recorded[key] == raw[key] for key in ('model_index', 'strategy', 'model', 'predictions'))
        model = raw['model']
        assert all(value in text for value in (model['model_id'], model['training_boundary'], model['training_keys'][0]))
    assert {row['strategy_kind'] for row in controller._evidence_rows} == {'RIDGE', 'QUADRATIC_RIDGE'}
    assert {row['model_stage'] for row in controller._evidence_rows} == {'LINEAR_FEATURES', 'INPUT_TRANSFORM', 'GENERATED_TERMS'}
    assert {row['joint_model_index'] for row in controller._evidence_rows} == set(range(6))

assert session.i18n.setLanguage('zh-CN')
assert controller.scopeIndex == len(expected['outer_folds']) + 1 and controller.viewIndex == 2
assert find('intradayJointTab').property('text') == '联合经济选参'
assert 'NONE 未复权' in find('intradayJointReturnBasis').property('text')
assert displayed('history_boundary') == '历史可用性截止时间'
assert window.grabWindow().save(str(root / 'q36-native-final-model-zh.png'))
click('intradayJointEvidenceButton')
assert find('intradayJointEvidenceDialog').property('visible')
full_text = find('intradayJointEvidenceText').property('text')
assert model['model_id'] in full_text and model['training_keys'][-1] in full_text
assert find('intradayJointEvidenceText').property('readOnly')
assert find('intradayJointEvidenceText').property('selectByMouse')
assert find('intradayJointEvidenceScroll').property('contentItem').property('contentHeight') > 500
assert window.grabWindow().save(str(root / 'q36-native-model-evidence.png'))
QTest.keyClick(window, Qt.Key_Escape); app.processEvents()
assert session.i18n.setLanguage('en')

# Failure keeps the finished artifact. Retry uses captured cost/candidate IDs;
# delaying a real calculation lets an actual source-combo change reject it.
before = controller._content
fill('intradayJointDataPath', root / 'missing-q5.json')
click('intradayJointRunButton'); complete(status='FAILED')
assert controller._content == before and controller.studyError and controller.draftChanged
click('intradayJointDataClear')
actual_run, ready, release, calls = joint.run_intraday_joint_selection, threading.Event(), threading.Event(), []
def delayed_run(*args, **kwargs):
    calls.append(kwargs)
    value = actual_run(*args, **kwargs)
    ready.set(); assert release.wait(30)
    return value
joint.run_intraday_joint_selection = delayed_run
click('intradayJointRunButton')
deadline = time.monotonic() + 60
while not ready.is_set() and time.monotonic() < deadline:
    app.processEvents(); time.sleep(.01)
assert ready.is_set()
choose('intradayJointCandidate', 2)
release.set(); complete()
joint.run_intraday_joint_selection = actual_run
assert calls[0]['cost_index'] == calls[0]['candidate_index'] == 1
assert controller.notice == 'STALE_INPUT' and controller._content == before
assert json.loads(controller.completedDetails)['fixed_reference']['candidate_index'] == 1
choose('intradayJointCandidate', 3)
click('intradayJointRunButton'); complete()
assert controller._content == before and not controller.notice and not controller.studyError and not controller.draftChanged

# Actual native Save/Open are pure recorded-evidence actions. Open must not
# turn a saved source-reconstruction statement into a fresh replay proof.
saved = root / 'native-joint.json'
file_action('intradayJointSaveButton', 'intradayJointSaveDialog', saved)
assert saved.read_bytes() == before
# Q31 and Q36 have independent controllers and completed artifacts.
click('intradayThresholdTab')
assert not owner.intradayThresholdSelectionController.resultLoaded
assert 'fixed' in find('intradayThresholdMethod').property('text')
click('intradayJointTab')
assert controller._content == before and controller.proof == 'COMPUTED'
real_load, real_fit = research.load_intraday_dataset, joint._fit
def forbidden(*args, **kwargs): raise AssertionError('Open must not read Q5 or fit')
research.load_intraday_dataset = joint._fit = forbidden
file_action('intradayJointOpenButton', 'intradayJointOpenDialog', saved)
research.load_intraday_dataset, joint._fit = real_load, real_fit
assert controller._content == before and controller.proof == 'RECORDED'
assert 'Q36 record' in find('intradayJointSummary').property('text')
assert 'full replay not verified' in find('intradayJointSummary').property('text')
fill('intradayJointDataPath', root / 'missing-q5.json')
click('intradayJointReplayButton'); complete(status='FAILED')
assert controller._content == before and controller.proof == 'REPLAY_FAILED' and controller.studyError
relocated = root / 'relocated-q5.json'; relocated.write_bytes(data_bytes)
fill('intradayJointDataPath', relocated)
relocated_source = root / 'relocated-source.json'; relocated_source.write_bytes(source_bytes)
fill('intradayJointSourcePath', root / 'short-source.json')
click('intradayJointReplayButton'); complete(status='FAILED')
assert controller._content == before and controller.proof == 'REPLAY_FAILED' and 'explicit ordinary source' in controller.studyError
fill('intradayJointSourcePath', relocated_source)
actual_replay, ready, release, replay_calls = experiments.replay_strategy_experiment, threading.Event(), threading.Event(), []
def delayed_replay(*args, **kwargs):
    replay_calls.append(kwargs)
    value = actual_replay(*args, **kwargs)
    ready.set(); assert release.wait(30)
    return value
experiments.replay_strategy_experiment = delayed_replay
click('intradayJointReplayButton')
deadline = time.monotonic() + 60
while not ready.is_set() and time.monotonic() < deadline:
    app.processEvents(); time.sleep(.01)
assert ready.is_set()
fill('intradayJointSourcePath', root / 'changed-during-replay.json')
release.set(); complete()
experiments.replay_strategy_experiment = actual_replay
assert replay_calls[0]['intraday_data_file'] == relocated and replay_calls[0]['source_experiment_file'] == relocated_source
assert controller.proof == 'REPLAY_STALE_INPUT' and controller.notice == 'STALE_INPUT' and controller._content == before
fill('intradayJointSourcePath', relocated_source)
click('intradayJointReplayButton'); complete()
assert controller.proof == 'REPLAY_MATCH' and not controller.studyError and not controller.notice
click('intradayJointDetailsButton')
details = json.loads(find('intradayJointDetailsText').property('text'))
assert details['verified_replay_data_path'] == str(relocated)
assert details['verified_replay_source_path'] == str(relocated_source)
assert details['source_experiment']['experiment_id'] == expected['source_experiment']['experiment_id']
assert details['fixed_reference']['cost_index'] == details['fixed_reference']['candidate_index'] == 1
assert details['joint_selection_id'] == expected['joint_selection_id']
assert details['method'] == expected['method']
assert details['final_dev_recipe'] == expected['final_dev']['selected_recipe']
assert details['evaluation_mode'] == 'INTRADAY_JOINT_SELECTION'
assert all(row['selected_recipe'] == original['inner']['selected_recipe']
    and row['refit_model_id'] == original['refit']['model']['model_id']
    for row, original in zip(details['outer_choices'], expected['outer_folds'], strict=True))
QTest.keyClick(window, Qt.Key_Escape); app.processEvents()

# The supported compact panel has an actual scrollbar; its complete ledger
# pagination remains on screen and responds to a real mouse click.
choose('intradayJointScope', 0); choose('intradayJointAccount', 0); choose('intradayJointView', 6)
window.setWidth(1024); window.setHeight(600); QTest.qWait(100)
scroll = find('intradayJointScroll'); flick = scroll.property('contentItem')
assert flick.property('contentHeight') > scroll.property('availableHeight')
bar = find('intradayJointScrollBar'); thumb = bar.property('contentItem')
start = thumb.mapToScene(thumb.boundingRect().center()).toPoint()
end = bar.mapToScene(QPointF(bar.width() / 2, bar.height() - 2)).toPoint()
QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
QTest.mouseMove(window, end, 50)
QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
QTest.qWait(50)
assert flick.property('contentY') > 0
pagination = nested(find('intradayJointTable'), 'PixelPagination')
next_button = next(child for child in pagination.findChildren(QObject) if child.property('glyph') == 'next')
assert controller.tableModel.page == 1 and controller.tableModel.hasNext
click_obj(next_button, scroll=False)
assert controller.tableModel.page == 2
assert window.grabWindow().save(str(root / 'q36-native-compact-ledger.png'))

# Valid UNAVAILABLE artifacts retain every window's evidence but no partial
# models/accounts, even when a particular window has no local reason.
window.setWidth(1280); window.setHeight(1100); QTest.qWait(50)
file_action('intradayJointOpenButton', 'intradayJointOpenDialog', root / 'unavailable.json')
assert controller._root['report']['status'] == 'UNAVAILABLE' and controller.proof == 'RECORDED'
assert find('intradayJointUnavailable').property('visible')
assert 'no inner models' in find('intradayJointUnavailable').property('text')
assert len(controller.equitySeries) == 2  # The saved source and benchmark only.
choose('intradayJointScope', len(controller._root['report']['outer_folds']) + 1)
assert controller._window()['unavailable_reason'] is None
assert controller.scopeSummary['status'] == 'UNAVAILABLE'
choose('intradayJointView', 2)
assert evidence()[0]['complete_models'] == [] and controller.tableModel.totalRows == 0
assert len(controller.accountOptions) == 24 and not any(row['chosen'] for row in controller.accountOptions)
assert controller.scopeSummary['model_count'] == controller.scopeSummary['account_count'] == 0
assert not controller.equitySeries
choose('intradayJointView', 6)
assert controller.tableModel.totalRows == 0
choose('intradayJointView', 1)
assert controller.tableModel.totalRows > 0 and controller._window()['history_boundary'] in evidence()[1]
assert window.grabWindow().save(str(root / 'q36-native-unavailable.png'))
assert saved.read_bytes() == before and source_path.read_bytes() == source_bytes and data_path.read_bytes() == data_bytes
(root / 'q36-native-warnings.json').write_text(json.dumps(warnings, ensure_ascii=False, indent=2))
assert not any('IntradayThresholdSelectionPanel' in item or 'IntradayWorkspacePanel' in item for item in warnings), warnings
assert session.shutdown()
engine.deleteLater(); app.processEvents()
print('NATIVE_JOINT_SELECTION_PASS')
'''
    completed = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(source_path), str(data.path)], cwd=ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software",
             "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT / "tests")))},
        text=True, capture_output=True, timeout=360)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "NATIVE_JOINT_SELECTION_PASS" in completed.stdout
