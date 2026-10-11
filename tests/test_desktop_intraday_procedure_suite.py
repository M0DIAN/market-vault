"""Real compact batch research, recorded handoffs and immutable task recovery."""

from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys

import pytest

# Qt-free shards do not construct the shared real Q5 research fixtures.
pytest.importorskip("PySide6")

from market_vault.research import intraday_research as research
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.intraday_procedure_comparison import compare_intraday_procedures
from market_vault.research.intraday_procedure_family import analyze_intraday_procedure_family
from market_vault.research.strategy_experiment import canonical_json, write_strategy_experiment
from test_strategy_intraday_ml import quadratic_dev_case  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]


_NATIVE = r'''
import json, sys, time, threading
from pathlib import Path
import pytest
import shiboken6
from PySide6.QtCore import QObject, QUrl, Qt, QEvent, QMetaObject, QPointF
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from market_vault.application import build_application_context
from market_vault.desktop.bootstrap import create_qml_application_session
from market_vault.desktop.preferences import DesktopPreferenceStore
from market_vault.desktop.localization import translation_keys_match
from market_vault.research import intraday_procedure_suite as suite
from market_vault.research import strategy_experiment as experiments
from test_intraday_ml_procedures_comparison import _no_recompute

root, source_path, data_path = map(Path, sys.argv[1:])
source_bytes, data_bytes = source_path.read_bytes(), data_path.read_bytes()
source = experiments.StrategyExperiment(source_bytes)
assert translation_keys_match()
QQuickStyle.setStyle('Basic')
app = QGuiApplication([])
engine = QQmlApplicationEngine()
warnings = []
engine.warnings.connect(lambda values: warnings.extend(value.toString() for value in values))
context = build_application_context(root / 'settings.yaml')
session = create_qml_application_session(context, engine,
    preference_store=DesktopPreferenceStore(root=root / 'preferences'))
engine.load(QUrl.fromLocalFile(str(Path.cwd() / 'src/market_vault/desktop/qml/Main.qml')))
assert engine.rootObjects(), warnings
window = engine.rootObjects()[0]
window.setWidth(1024); window.setHeight(600)
owner = session.context_properties['quantResearchController']
research_ui, controller = owner.intradayResearchController, owner.intradayProcedureSuiteController
comparison, final = owner.intradayProcedureComparisonController, owner.intradayFinalController
roles = ('Q25', 'Q31', 'Q36')
prefixes = ('intradayInner', 'intradayThreshold', 'intradayJoint')
children = (owner.intradayInnerSelectionController, owner.intradayThresholdSelectionController,
            owner.intradayJointSelectionController)
sections, patch = [], pytest.MonkeyPatch()
controller.sectionRequested.connect(sections.append)
assert session.i18n.setLanguage('en') and session.shell.selectPage('quant_research')
QTest.qWait(50)
assert window.width() == 1024 and window.height() == 600

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
    scroll = obj.parentItem()
    while scroll is not None and not scroll.objectName().endswith('Scroll'):
        scroll = scroll.parentItem()
    if scroll is None: return
    flick = scroll.property('contentItem')
    top = scroll.mapToScene(QPointF(0, 0)).y()
    center = obj.mapToScene(obj.boundingRect().center()).y()
    height = scroll.property('availableHeight')
    if center < top + 10 or center > top + height - 10:
        target = flick.property('contentY') + center - top - height / 2
        flick.setProperty('contentY', max(0, min(target, flick.property('contentHeight') - height)))
        app.processEvents()

def reachable(name):
    obj = find(name); reveal(obj)
    point = obj.mapToScene(obj.boundingRect().center()).toPoint()
    assert obj.property('visible') and obj.property('enabled'), name
    assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), (name, point)
    return obj, point

def click(name):
    obj, point = reachable(name)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    app.processEvents()

def fill(name, value):
    obj, _ = reachable(name)
    window.requestActivate(); QTest.qWait(20)
    nested(obj, 'PixelTextField').forceActiveFocus()
    QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClick(window, Qt.Key_Backspace)
    for char in str(value):
        QGuiApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, ord(char.upper()), Qt.NoModifier, char))
    app.processEvents()
    assert obj.property('text') == str(value), name

def choose(name, index):
    obj, _ = reachable(name)
    window.requestActivate(); QTest.qWait(20)
    combo = nested(obj, 'PixelComboBox'); combo.forceActiveFocus()
    if obj.property('currentIndex') != index:
        QTest.keyClick(window, Qt.Key_Space)
        assert combo.property('down')
        QTest.keyClick(window, Qt.Key_Home)
        for _ in range(index): QTest.keyClick(window, Qt.Key_Down)
        QTest.keyClick(window, Qt.Key_Return)
    app.processEvents()
    assert obj.property('currentIndex') == index, name

def complete(target=controller, status='SUCCESS'):
    deadline = time.monotonic() + 90
    while target.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    app.processEvents()
    assert not target.busy and target.status == status, (target.status, target.error, warnings)

def file_action(button, dialog_name, path, target):
    click(button)
    dialog = find(dialog_name)
    assert dialog.property('visible')
    assert dialog.setProperty('selectedFile', QUrl.fromLocalFile(str(path)))
    assert QMetaObject.invokeMethod(dialog, 'accepted', Qt.DirectConnection)
    QMetaObject.invokeMethod(dialog, 'close', Qt.DirectConnection)
    complete(target)

def open_source():
    click('intradayComparisonTab')
    file_action('intradayExperimentOpenButton', 'intradayExperimentOpenDialog', source_path, research_ui)
    click('intradaySuiteTab')

def view(index):
    click('intradaySuite' + roles[index] + 'View')
    assert sections[-1] == (5, 7, 9)[index]
    assert find(prefixes[index] + 'Panel').property('visible')
    assert not find('intradaySuitePanel').property('visible')
    assert children[index]._content == controller._studies[index].content
    click('intradaySuiteTab')

def admissions(expected):
    assert (final.canFreezeInner, final.canFreezeThreshold, final.canFreezeJoint) == expected
    assert not final.selectionLoaded and not final.testLoaded

def finish(marker):
    assert source_path.read_bytes() == source_bytes and data_path.read_bytes() == data_bytes
    assert context.backend_if_initialized is None
    (root / 'native-warnings.json').write_text(json.dumps(warnings, ensure_ascii=False, indent=2))
    assert not any('IntradayProcedureSuitePanel' in value or 'IntradayWorkspacePanel' in value for value in warnings), warnings
    patch.undo(); assert session.shutdown(); engine.deleteLater(); app.processEvents()
    print(marker, flush=True)
    print('NATIVE_ARTIFACT_DIR=' + str(root), flush=True)

click('quantIntradayTab'); click('intradaySuiteTab')
assert not controller.canRun and not controller.resultLoaded
assert controller.studyResults == [] and controller.completedSource == {}
assert not find('intradaySuiteRun').property('enabled')
assert not controller.canCompare
'''


def _run_native(tmp_path, body, source_path, data_path, marker):
    (tmp_path / "settings.yaml").write_text("storage:\n  root_dir: ./data\n")
    script = tmp_path / "q51-native.py"
    script.write_text(_NATIVE + body, encoding="utf-8")
    completed = subprocess.run([sys.executable, str(script), str(tmp_path), str(source_path), str(data_path)],
        cwd=ROOT, env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software",
            "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT / "tests")))},
        text=True, capture_output=True, timeout=360)
    (tmp_path / "native-output.txt").write_text(completed.stdout + completed.stderr, encoding="utf-8")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert marker in completed.stdout
    print(completed.stdout, end="")


def test_native_suite_real_family_save_conflict_recorded_handoffs_and_compact(procedure_comparison_case, tmp_path):
    case = procedure_comparison_case
    snapshots = tuple(case.studies[name][0] for name in ("q25", "q31", "q36"))
    for role, snapshot in zip(("Q25", "Q31", "Q36"), snapshots, strict=True):
        (tmp_path / (role + "-expected.json")).write_bytes(snapshot.content)
    (tmp_path / "family-expected.json").write_bytes(canonical_json(analyze_intraday_procedure_family(snapshots)))
    (tmp_path / "pair-expected.json").write_bytes(canonical_json(compare_intraday_procedures(*snapshots[:2])))
    # A different valid artifact exercises the existing exclusive writer.
    write_strategy_experiment(case.source, path=tmp_path / "conflict.json")
    body = r'''
expected = tuple((root / (role + '-expected.json')).read_bytes() for role in roles)
family_expected = json.loads((root / 'family-expected.json').read_bytes())
pair_expected = json.loads((root / 'pair-expected.json').read_bytes())
open_source()
assert controller.canRun and controller.draftSource['source_id'] == source.experiment_id
captured, evaluate, calls = research_ui.selection_source(), suite.evaluate_intraday_procedure_suite, []
def evaluated(snapshot, **kwargs):
    calls.append((snapshot.content, dict(kwargs)))
    return evaluate(snapshot, **kwargs)
def forbidden_reopen(*args, **kwargs):
    raise AssertionError('suite reopened the captured ordinary source')
patch.setattr(suite, 'evaluate_intraday_procedure_suite', evaluated)
with pytest.MonkeyPatch.context() as capture_patch:
    capture_patch.setattr(experiments, '_read_file', forbidden_reopen)
    started = time.perf_counter()
    click('intradaySuiteRun'); complete()
    elapsed = time.perf_counter() - started
assert len(calls) == 1 and calls[0][0] == captured['content'] == source.content
arguments = calls[0][1]
assert Path(arguments['source_experiment_path']) == source_path
assert arguments['expected_experiment_id'] == captured['experiment_id']
assert arguments['expected_candidate_id'] == captured['candidate_id']
assert arguments['cost_index'] == arguments['candidate_index'] == 0
assert arguments.get('name', '') == arguments.get('notes', '') == ''
assert arguments.get('intraday_data_file') is None
assert type(controller._studies) is tuple and len(controller._studies) == 3
assert tuple(study.content for study in controller._studies) == expected
assert [row['experiment_id'] for row in controller.studyResults] == [json.loads(value)['experiment_id'] for value in expected]
assert [row['role'] for row in controller.studyResults] == list(roles)
assert all(row['status'] == 'AVAILABLE' and not row['unavailable_reason'] for row in controller.studyResults)
assert all(row['path'] == '' and row['save_state'] == 'UNSAVED' for row in controller.studyResults)
assert not controller.canCompare and not controller.draftChanged
bound = controller.completedSource
assert bound == {'source_path': str(source_path), 'source_id': captured['experiment_id'],
    'candidate_id': captured['candidate_id'], 'cost_index': 0, 'candidate_index': 0, 'data_locator': ''}
assert family_expected['sample']['sample_count'] == 100 and family_expected['sample']['fold_count'] == 4
print(json.dumps({'real_suite_seconds': round(elapsed, 3), 'real_suite_runs': len(calls),
    'canonical_bytes_equal': True, 'experiment_ids': [row['experiment_id'] for row in controller.studyResults]}), flush=True)

# Every following action uses the recorded tuple, including old readers and
# both comparison modes. A GUI shortcut must not quietly run a study again.
_no_recompute(patch)
fill('intradaySuiteDataPath', root / 'new-draft-q5.json')
assert controller.draftChanged and controller.completedSource == bound
assert controller.draftSource['data_locator'] != bound['data_locator']
assert find('intradaySuiteDraftChanged').property('visible')
for index, child in enumerate(children):
    if index:
        child.setDataLocator(str(root / 'different-old-page-draft.json'))
    view(index)
    assert child.experimentPath == '' and child.proof == 'COMPUTED'
    if index:
        assert child._completed_signature == ((str(source_path), captured['experiment_id'],
            captured['candidate_id'], 0, 0), '')
        assert child.draftChanged
admissions((False, False, False))

outputs = [root / 'saved-q25.json', root / 'saved-q31.json', root / 'saved-q36.json']
drafts = [outputs[0], root / 'conflict.json', outputs[2]]
conflict = drafts[1].read_bytes()
for role, path in zip(roles, drafts, strict=True):
    fill('intradaySuite' + role + 'SavePath', path)
fields = tuple(find('intradaySuite' + role + 'SavePath') for role in roles)
def retained_fields():
    for role, field, value in zip(roles, fields, drafts, strict=True):
        assert shiboken6.isValid(field) and find('intradaySuite' + role + 'SavePath') is field
        assert field.property('text') == str(value)

click('intradaySuiteQ25Save'); complete(); retained_fields()
assert controller.studyResults[0]['path'] == str(outputs[0])
click('intradaySuiteQ31Save'); complete(status='FAILED'); retained_fields()
assert 'existing experiment differs' in controller.studyError
assert [row['save_state'] for row in controller.studyResults] == ['SAVED', 'UNSAVED', 'UNSAVED']
assert [row['path'] for row in controller.studyResults] == [str(outputs[0]), '', '']
assert outputs[0].read_bytes() == expected[0] and drafts[1].read_bytes() == conflict
assert not outputs[1].exists() and not outputs[2].exists() and not controller.canCompare
drafts[1] = outputs[1]
fill('intradaySuiteQ31SavePath', outputs[1])
click('intradaySuiteQ31Save'); complete(); retained_fields()
click('intradaySuiteQ36Save'); complete(); retained_fields()
assert controller.canCompare and not controller.studyError
assert all(row['save_state'] == 'SAVED' for row in controller.studyResults)
assert [row['path'] for row in controller.studyResults] == [str(path) for path in outputs]
assert tuple(path.read_bytes() for path in outputs) == expected
assert controller.completedSource == bound

for index, (child, prefix, path) in enumerate(zip(children, prefixes, outputs, strict=True)):
    view(index)
    assert child.experimentPath == str(path)
    click(('intradayInnerTab', 'intradayThresholdTab', 'intradayJointTab')[index])
    file_action(prefix + 'OpenButton', prefix + 'OpenDialog', path, child)
    assert child._content == expected[index] and child.proof == 'RECORDED'
    click('intradaySuiteTab')
admissions((True, True, True))
click('intradayFinalTab')
for name in ('intradayFreezeInnerButton', 'intradayFreezeThresholdButton', 'intradayFreezeJointButton'):
    reachable(name)  # Admission only: no Freeze or TEST action is submitted.
assert not find('intradayRunTestButton').property('enabled')
click('intradaySuiteTab')

labels = []
for language in ('en', 'zh-CN'):
    assert session.i18n.setLanguage(language)
    retained_fields()
    labels.append(find('intradaySuiteRun').property('text'))
    assert controller.completedSource == bound and controller.draftChanged
    for name in ('intradaySuiteRun', 'intradaySuiteCompare'):
        reachable(name)
    for role in roles:
        assert 'undefined' not in find('intradaySuite' + role + 'Result').property('text')
        for suffix in ('SavePath', 'Save', 'View'):
            reachable('intradaySuite' + role + suffix)
    scroll = find('intradaySuiteScroll')
    assert scroll.property('contentItem').property('contentHeight') > scroll.property('availableHeight')
    assert window.grabWindow().save(str(root / ('q51-suite-compact-' + language + '.png')))
assert labels[0] and labels[1] and labels[0] != labels[1]
assert session.i18n.setLanguage('en')

click('intradaySuiteCompare'); complete(comparison)
assert sections[-1] == 10 and find('intradayProcedureScroll').property('visible')
assert comparison.completedFamily and comparison._report == family_expected
assert [row['role'] for row in comparison.boundSources] == list(roles)
assert [row['path'] for row in comparison.boundSources] == [str(path) for path in outputs]
assert [row['input_slot'] for row in comparison.boundSources] == ['A', 'B', 'C']
choose('intradayProcedureMode', 0)
click('intradayProcedureRunButton'); complete(comparison)
assert not comparison.completedFamily and comparison._report == pair_expected
assert [row['path'] for row in comparison.boundSources] == [str(path) for path in outputs[:2]]
assert len(calls) == 1 and tuple(path.read_bytes() for path in outputs) == expected
assert (root / 'conflict.json').read_bytes() == conflict
admissions((True, True, True))
finish('NATIVE_PROCEDURE_SUITE_HANDOFF_PASS')
'''
    _run_native(tmp_path, body, case.path, case.data.path, "NATIVE_PROCEDURE_SUITE_HANDOFF_PASS")


def test_native_suite_unavailable_stale_success_failure_and_retry(quadratic_dev_case, tmp_path):
    data, original = quadratic_dev_case[:2]
    plan = deepcopy(original)
    plan["walk_forward"]["minimum_train_days"] = 10
    plan["strategies"] = plan["strategies"][:2]
    source = create_intraday_experiment(plan=plan, report=research.run_intraday_research(plan))
    source_path = write_strategy_experiment(source, path=tmp_path / "short-source.json").path
    body = r'''
open_source()
click('intradayInnerTab'); choose('intradayInnerCandidate', 1); click('intradaySuiteTab')
locator = QUrl.fromLocalFile(str(data_path)).toString()
fill('intradaySuiteDataPath', locator)
evaluate, calls = suite.evaluate_intraday_procedure_suite, []
def evaluated(snapshot, **kwargs):
    calls.append((snapshot.content, dict(kwargs)))
    return evaluate(snapshot, **kwargs)
patch.setattr(suite, 'evaluate_intraday_procedure_suite', evaluated)
click('intradaySuiteRun'); complete()
assert len(calls) == 1 and calls[0][0] == source.content
assert calls[0][1]['candidate_index'] == 1 and Path(calls[0][1]['intraday_data_file']) == data_path
assert [row['role'] for row in controller.studyResults] == list(roles)
assert all(row['status'] == 'UNAVAILABLE' and row['unavailable_reason'] for row in controller.studyResults)
assert all(row['path'] == '' and row['save_state'] == 'UNSAVED' for row in controller.studyResults)
reports = [study.as_dict()['report'] for study in controller._studies]
fold_count = len(source.as_dict()['report']['context']['folds'])
for report, family_size in zip(reports, (6, 4, 24), strict=True):
    assert len(report['method'].get('family', report['method'].get('thresholds'))) == family_size
    assert len(report['outer_folds']) == fold_count and report['selected_account'] is None
    assert report['unavailable_reasons'] == [{'scope': 'OUTER_FOLD', 'fold_index': 0, 'reason': 'INSUFFICIENT_INNER_HISTORY'}]
    assert all(fold['inner']['family_results'] == [] for fold in report['outer_folds'])
    assert report['final_dev']['family_results'] == []

outputs = [root / (role + '-unavailable.json') for role in roles]
for index, (role, path) in enumerate(zip(roles, outputs, strict=True)):
    fill('intradaySuite' + role + 'SavePath', path)
    click('intradaySuite' + role + 'Save'); complete()
    view(index)
    assert children[index].experimentPath == str(path)
admissions((False, False, False))
assert controller.canCompare
click('intradaySuiteCompare'); complete(comparison)
assert comparison.completedFamily and comparison.resultSummary['status'] == 'UNAVAILABLE'
assert comparison.resultSummary['family_size'] == 3
assert [row['role'] for row in comparison.boundSources] == list(roles)
click('intradaySuiteTab')
prior, rows, bound = controller._studies, controller.studyResults, controller.completedSource
prior_bytes = tuple(study.content for study in prior)
assert bound['candidate_index'] == 1 and bound['data_locator'] == locator

def retained():
    assert controller._studies is prior and controller.studyResults == rows
    assert controller.completedSource == bound
    assert tuple(path.read_bytes() for path in outputs) == prior_bytes

def change_back(axis):
    if axis == 'candidate':
        click('intradayInnerTab')
        choose('intradayInnerCandidate', 0); choose('intradayInnerCandidate', 1)
        click('intradaySuiteTab')
    else:
        fill('intradaySuiteDataPath', root / 'changed-while-running.json')
        fill('intradaySuiteDataPath', locator)

def pending(failure=False):
    ready, release, captured = threading.Event(), threading.Event(), []
    def delayed(snapshot, **kwargs):
        captured.append((snapshot.content, kwargs))
        ready.set(); assert release.wait(30)
        if failure:
            raise ValueError('deliberate late suite failure')
        # Fresh immutable objects from the actual finished suite distinguish
        # a wrongly applied stale success without repeating the same fits.
        return tuple(experiments.StrategyExperiment(study.content) for study in prior)
    suite.evaluate_intraday_procedure_suite = delayed
    click('intradaySuiteRun')
    deadline = time.monotonic() + 30
    while not ready.is_set() and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    assert ready.is_set() and controller.busy
    assert captured[0][0] == source.content and captured[0][1]['candidate_index'] == 1
    return release

for axis in ('candidate', 'locator'):
    release = pending()
    change_back(axis)
    retained()
    release.set(); complete()
    assert controller.notice == 'STALE_INPUT'
    retained()
release = pending(failure=True)
change_back('locator')
release.set(); complete(status='STALE_INPUT')
assert controller.notice == 'STALE_INPUT' and not controller.studyError and not controller.error
retained()
suite.evaluate_intraday_procedure_suite = evaluated

# The real missing-file failure preserves the old saved group; one actual
# corrected run establishes recovery, independently of the delayed workers.
fill('intradaySuiteDataPath', root / 'missing-q5.json')
click('intradaySuiteRun'); complete(status='FAILED')
assert controller.studyError and controller.draftChanged
retained()
fill('intradaySuiteDataPath', locator)
click('intradaySuiteRun'); complete()
assert len(calls) == 3 and tuple(study.content for study in controller._studies) == prior_bytes
assert not controller.studyError and not controller.notice and not controller.draftChanged
assert controller.completedSource == bound
assert tuple(path.read_bytes() for path in outputs) == prior_bytes

# An old result keeps its actual candidate identity when the current ordinary
# selector changes. Q31/Q36 must not attach the new draft to the completed run.
click('intradayInnerTab'); choose('intradayInnerCandidate', 0); click('intradaySuiteTab')
assert controller.draftChanged and controller.draftSource['candidate_index'] == 0
for index in (1, 2):
    view(index)
    assert children[index]._completed_signature[0][4] == 1
    assert children[index].draftChanged
admissions((False, False, False))
for language in ('en', 'zh-CN'):
    assert session.i18n.setLanguage(language)
    assert controller.completedSource == bound
    for role in roles:
        assert 'undefined' not in find('intradaySuite' + role + 'Result').property('text')
        reachable('intradaySuite' + role + 'View')
    assert window.grabWindow().save(str(root / ('q51-suite-unavailable-' + language + '.png')))
assert len(calls) == 3
print(json.dumps({'real_suite_successes': 2, 'real_missing_q5_failures': 1,
    'stale_success_axes': ['candidate', 'locator'], 'stale_failure_axis': 'locator',
    'unavailable_roles': [row['role'] for row in controller.studyResults]}), flush=True)
finish('NATIVE_PROCEDURE_SUITE_RECOVERY_PASS')
'''
    _run_native(tmp_path, body, source_path, data.path, "NATIVE_PROCEDURE_SUITE_RECOVERY_PASS")
