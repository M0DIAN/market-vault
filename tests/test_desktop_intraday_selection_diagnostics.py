"""Actual compact Main.qml diagnostics, immutable captures and late callbacks."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

# Qt-free shards must not build the otherwise shared real training fixture.
pytest.importorskip("PySide6")

from market_vault.backtest.intraday import _digest as execution_digest
from market_vault.research.strategy_experiment import StrategyExperiment
from test_intraday_ml_procedures_comparison import reseal_procedure_benchmark
from test_intraday_ml_procedures_stress import _short_study
from test_strategy_intraday_threshold_selection import resigned


ROOT = Path(__file__).resolve().parents[1]


def _sources(case, root):
    for kind, (study, _) in case.studies.items():
        (root / (kind + ".json")).write_bytes(study.content)
    (root / "ordinary.json").write_bytes(case.source.content)
    (root / "settings.yaml").write_text("storage:\n  root_dir: ./data\n")


_NATIVE = r'''
from copy import deepcopy
import gc, hashlib, json, sys, threading, time
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
from market_vault.desktop import intraday_selection_diagnostics as presentation
from market_vault.backtest import intraday as execution
from market_vault.research import intraday_procedure_risk_diagnostics as risk
from market_vault.research import intraday_inner_cost_sensitivity as cost
from market_vault.research import strategy_experiment as experiments
from test_intraday_ml_procedures_inner_cost_sensitivity import _prohibit_source_fit_and_test

root = Path(sys.argv[1])
paths = {path.stem: path for path in root.glob('*.json')}
original = {path: path.read_bytes() for path in paths.values()}
assert translation_keys_match()
QQuickStyle.setStyle('Basic')
app = QGuiApplication([]); engine = QQmlApplicationEngine(); warnings = []
engine.warnings.connect(lambda values: warnings.extend(value.toString() for value in values))
context = build_application_context(root / 'settings.yaml')
session = create_qml_application_session(context, engine, preference_store=DesktopPreferenceStore(root=root / 'preferences'))
engine.load(QUrl.fromLocalFile(str(Path.cwd() / 'src/market_vault/desktop/qml/Main.qml')))
assert engine.rootObjects(), warnings
window = engine.rootObjects()[0]; window.setWidth(1024); window.setHeight(600)
owner = session.context_properties['quantResearchController']
controller = owner.intradaySelectionDiagnosticsController
assert session.i18n.setLanguage('en') and session.shell.selectPage('quant_research')
QTest.qWait(50)
assert window.width() == 1024 and window.height() == 600
patch, gui_thread = pytest.MonkeyPatch(), threading.get_ident()
_prohibit_source_fit_and_test(patch)
calls, reports, kernel_calls, serialized = [], {}, [], []
real_risk, real_cost, kernel, encode = risk.analyze_intraday_procedure_risk_diagnostics, cost.analyze_intraday_inner_cost_sensitivity, cost.run_intraday_execution, presentation._json

def forbidden(*args, **kwargs):
    raise AssertionError('outer risk executed a new account')

def measured_risk(snapshot):
    assert threading.get_ident() != gui_thread
    with pytest.MonkeyPatch.context() as no_execution:
        no_execution.setattr(execution, 'run_intraday_execution', forbidden)
        no_execution.setattr(cost, 'run_intraday_execution', forbidden)
        result = real_risk(snapshot)
    calls.append(('outer_risk', snapshot.content)); reports['outer_risk'] = result
    return result

def measured_cost(snapshot):
    assert threading.get_ident() != gui_thread
    before = len(kernel_calls)
    result = real_cost(snapshot)
    supports = {tuple(day['trading_day'] for day in item['fixed_evidence']['sessions']) for item in result['windows']}
    assert all(support in supports for support in kernel_calls[before:])
    calls.append(('inner_cost', snapshot.content)); reports['inner_cost'] = result
    return result

def measured_kernel(**kwargs):
    assert threading.get_ident() != gui_thread
    kernel_calls.append(tuple(day['trading_day'] for day in kwargs['sessions']))
    return kernel(**kwargs)

def measured_json(value):
    if any(value is report for report in reports.values()):
        assert threading.get_ident() != gui_thread, 'full report serialized on GUI thread'
        serialized.append(id(value))
    return encode(value)

patch.setattr(risk, 'analyze_intraday_procedure_risk_diagnostics', measured_risk)
patch.setattr(cost, 'analyze_intraday_inner_cost_sensitivity', measured_cost)
patch.setattr(cost, 'run_intraday_execution', measured_kernel)
patch.setattr(presentation, '_json', measured_json)

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
    top, height = scroll.mapToScene(QPointF(0, 0)).y(), scroll.property('availableHeight')
    center = obj.mapToScene(obj.boundingRect().center()).y()
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
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point); app.processEvents()

def click(name):
    click_obj(find(name))

def choose(suffix, index):
    obj = find('intradaySelectionDiagnostics' + suffix); reveal(obj)
    window.requestActivate(); QTest.qWait(20)
    assert obj.property('visible') and obj.property('enabled'), suffix
    combo = nested(obj, 'PixelComboBox'); combo.forceActiveFocus()
    if obj.property('currentIndex') != index:
        QTest.keyClick(window, Qt.Key_Space)
        assert combo.property('down'), suffix
        QTest.keyClick(window, Qt.Key_Home)
        for _ in range(index): QTest.keyClick(window, Qt.Key_Down)
        QTest.keyClick(window, Qt.Key_Return)
    app.processEvents()
    assert obj.property('currentIndex') == index, (suffix, obj.property('currentIndex'), index)
    if suffix == 'Section':
        assert obj.property('label') == ('Evidence section' if session.i18n.language == 'en' else '证据字段')

def view(key):
    choose('View', controller.viewOptions.index(key))

def fill(value):
    obj = find('intradaySelectionDiagnosticsPath'); reveal(obj)
    window.requestActivate(); QTest.qWait(20)
    nested(obj, 'PixelTextField').forceActiveFocus()
    QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier); QTest.keyClick(window, Qt.Key_Backspace)
    for char in str(value):
        QGuiApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, ord(char.upper()), Qt.NoModifier, char))
    app.processEvents(); assert obj.property('text') == str(value)

def complete(status='SUCCESS'):
    deadline = time.monotonic() + 90
    while controller.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    app.processEvents()
    assert not controller.busy and controller.status == status, (controller.status, controller.error, warnings)

def open_study(name):
    fill(paths[name]); click('intradaySelectionDiagnosticsOpenButton'); complete()
    assert controller.canRun

def run():
    click('intradaySelectionDiagnosticsRunButton'); complete()
    assert controller._report is reports[controller.completedMode]
    assert serialized.count(id(controller._report)) == 1
    return controller._report

def evidence():
    click('intradaySelectionDiagnosticsEvidenceButton')
    assert find('intradaySelectionDiagnosticsEvidenceDialog').property('visible')
    page = json.loads(find('intradaySelectionDiagnosticsEvidenceText').property('text'))
    QTest.keyClick(window, Qt.Key_Escape); app.processEvents()
    assert find('intradaySelectionDiagnosticsEvidenceText').property('text') == ''
    assert page['source'] == controller.boundSource and page['completed_mode'] == controller.completedMode
    assert len(page['rows']) <= 100 and page['page_size'] == 100
    id_key = 'sensitivity_id' if controller.completedMode == 'inner_cost' else 'diagnostics_id'
    assert page[id_key] == controller._report[id_key]
    return page

def copy_report(expected):
    click('intradaySelectionDiagnosticsReportButton')
    details = json.loads(find('intradaySelectionDiagnosticsReportText').property('text'))
    assert details['captured_source'] == controller.boundSource
    assert details['completed_mode'] == controller.completedMode
    assert not {'accounts', 'windows', 'diagnostics', 'procedure'} & details.keys()
    assert details['evidence'] == expected['evidence'] and details['method'] == expected['method']
    click_obj(find('intradaySelectionDiagnosticsCopyReportButton'), scroll=False)
    assert json.loads(QGuiApplication.clipboard().text()) == expected
    QGuiApplication.clipboard().clear(); gc.collect()
    QTest.keyClick(window, Qt.Key_Escape); app.processEvents()
    assert find('intradaySelectionDiagnosticsReportText').property('text') == ''

def scroll_bottom():
    scroll = find('intradaySelectionDiagnosticsScroll'); flick = scroll.property('contentItem')
    flick.setProperty('contentY', 0); QTest.qWait(20)
    bar = find('intradaySelectionDiagnosticsScrollBar'); thumb = bar.property('contentItem')
    start = thumb.mapToScene(thumb.boundingRect().center()).toPoint()
    end = bar.mapToScene(QPointF(bar.width() / 2, bar.height() - 2)).toPoint()
    assert 0 <= start.y() < 600 and 0 <= end.y() < 600
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(window, end, 50)
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end); QTest.qWait(30)
    assert flick.property('contentY') > 0

def page_two(expected):
    assert controller.tableModel.page == 1 and controller.tableModel.hasNext
    scroll_bottom()
    pagination = nested(find('intradaySelectionDiagnosticsTable'), 'PixelPagination')
    button = next(child for child in pagination.findChildren(QObject) if child.property('glyph') == 'next')
    click_obj(button, scroll=False)
    assert controller.tableModel.page == 2
    assert [row['complete_record'] for row in evidence()['rows']] == expected[100:200]

def screenshot(name, control=None):
    if control: reveal(find('intradaySelectionDiagnostics' + control))
    QTest.qWait(40)
    assert window.width() == 1024 and window.height() == 600
    for suffix in ('Summary', 'SelectionSummary'):
        assert 'undefined' not in find('intradaySelectionDiagnostics' + suffix).property('text'), suffix
    assert window.grabWindow().save(str(root / (name + '.png')))

def displayed(value):
    return find('intradaySelectionDiagnosticsTable').property('cellFormatter').call([QJSValue(value)]).toString()

def finish(marker):
    assert context.backend_if_initialized is None
    assert not owner.intradayFinalController.selectionLoaded and not owner.intradayFinalController.testLoaded
    assert all(path.read_bytes() == content for path, content in original.items())
    assert not any('IntradaySelectionDiagnosticsPanel' in value or 'IntradayWorkspacePanel' in value for value in warnings), warnings
    (root / 'qml-warnings.json').write_text(json.dumps(warnings, ensure_ascii=False, indent=2))
    patch.undo(); assert session.shutdown()
    engine.deleteLater(); app.processEvents()
    print(marker, flush=True)

click('quantIntradayTab'); click('intradaySelectionDiagnosticsTab'); QTest.qWait(30)
assert find('intradaySelectionDiagnosticsPanel').property('visible')
'''


def _run_native(root, body, marker):
    completed = subprocess.run([sys.executable, "-c", _NATIVE + body, str(root)], cwd=ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software",
             "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT / "tests")))},
        text=True, capture_output=True, timeout=300)
    (root / "native-stdout.txt").write_text(completed.stdout)
    (root / "native-stderr.txt").write_text(completed.stderr)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert marker in completed.stdout


def test_native_selection_diagnostics_both_modes_complete_evidence_and_compact_bilingual(procedure_comparison_case, tmp_path):
    _sources(procedure_comparison_case, tmp_path)
    body = r'''
assert not controller.canRun and not controller.resultLoaded
click('intradaySelectionDiagnosticsBrowse')
dialog = find('intradaySelectionDiagnosticsFileDialog')
assert dialog.property('visible')
assert dialog.setProperty('selectedFile', QUrl.fromLocalFile(str(paths['q36'])))
assert QMetaObject.invokeMethod(dialog, 'accepted', Qt.DirectConnection)
QMetaObject.invokeMethod(dialog, 'close', Qt.DirectConnection); app.processEvents()
assert not controller.canRun and not controller.sourceInfo
click('intradaySelectionDiagnosticsOpenButton'); complete()
assert controller.sourceInfo['sha256'] == hashlib.sha256(original[paths['q36']]).hexdigest()
# The filesystem is no longer the input after explicit Open.
paths['q36'].write_bytes(b'changed after explicit capture')
loader = experiments.load_strategy_experiment
experiments.load_strategy_experiment = lambda *a, **k: (_ for _ in ()).throw(AssertionError('Run reopened source'))
risk_report = run()
experiments.load_strategy_experiment = loader; paths['q36'].write_bytes(original[paths['q36']])
assert calls == [('outer_risk', original[paths['q36']])] and not kernel_calls
assert risk_report['account_availability']['available'] == 3 and risk_report['comparability']['comparable']
bound = controller.boundSource
for language in ('en', 'zh-CN'):
    assert session.i18n.setLanguage(language)
    view('risk_summary')
    for index, role in enumerate(controller.roleOptions):
        choose('Role', index)
        page = evidence(); raw = risk_report['diagnostics'][role]['report']
        assert page['role'] == role and page['role_diagnostics_id'] == raw['diagnostics_id']
        assert page['diagnostics_id'] != page['role_diagnostics_id']
        metric = next(row for row in page['rows'] if row['metric'] == 'maximum_drawdown')
        assert metric['complete_record'] == raw['summary']['maximum_drawdown'] and metric['unit'] == 'RATIO'
        assert float(metric['metric_value'].removesuffix('%')) == pytest.approx(raw['summary']['maximum_drawdown']['value'] * 100, rel=1e-5)
        duration = next(row for row in page['rows'] if row['metric'] == 'longest_drawdown_minutes')
        assert duration['unit'] == 'MINUTES' and float(duration['metric_value']) == pytest.approx(raw['summary']['longest_drawdown_minutes']['value'])
    scroll_bottom(); screenshot('q54-risk-metrics-' + language)
    view('drawdown_episodes'); choose('Role', 0)
    episode = risk_report['diagnostics']['procedure']['report']['drawdown_episodes'][0]
    rows = evidence()['rows'][:3]
    assert [row['complete_record'] for row in rows] == [episode] * 3
    assert [row['sequence'] for row in rows] == [episode[prefix + '_sequence'] for prefix in ('peak', 'trough', 'recovery')]
    assert episode['peak_time'] == episode['trough_time'] and episode['peak_sequence'] != episode['trough_sequence']
    view('return_distributions')
    assert evidence()['rows'][0]['complete_record']['distribution'] == risk_report['diagnostics']['procedure']['report']['daily_return_distribution']
    view('cash_concentration')
    assert evidence()['rows'][0]['complete_record'] == risk_report['diagnostics']['procedure']['report']['cash_concentration']['positive']
    view('risk_folds')
    assert [row['complete_record'] for row in evidence()['rows']] == risk_report['diagnostics']['procedure']['report']['fold_diagnostics']['rows']
    view('recipes'); page = evidence()
    assert page['role'] == 'procedure' and 'window_index' not in page
    assert [row['complete_record'] for row in page['rows']] == risk_report['procedure']['outer_folds']
    view('accounts'); choose('Role', 0); choose('Section', controller.sectionOptions.index('execution.ledger'))
    ledger = risk_report['accounts']['procedure']['execution']['ledger']
    assert controller.tableModel.totalRows == len(ledger) > 100
    assert [row['complete_record'] for row in evidence()['rows']] == ledger[:100]
    page_two(ledger); scroll_bottom(); screenshot('q54-risk-ledger-page2-' + language)
    copy_report(risk_report)
assert len(calls) == 1 and serialized.count(id(risk_report)) == 1

# Draft mode does not replace a completed risk report or its selectors.
choose('Mode', 1)
assert controller.draftChanged and controller.completedMode == 'outer_risk'
assert 'risk_summary' in controller.viewOptions and controller.boundSource == bound
cost_report = run()
assert controller.completedMode == 'inner_cost' and not controller.draftChanged
assert cost_report['sample']['family_size'] == 24 and cost_report['status'] == 'AVAILABLE'
for language in ('en', 'zh-CN'):
    assert session.i18n.setLanguage(language)
    view('scenarios'); choose('Window', len(controller.windowOptions) - 1)
    assert 'FINAL_DEV' in find('intradaySelectionDiagnosticsWindow').property('currentText')
    assert 'undefined' not in find('intradaySelectionDiagnosticsWindow').property('currentText')
    final_window = cost_report['windows'][-1]
    assert final_window['scope'] == 'FINAL_DEV' and final_window['fold_index'] is None
    scenarios = evidence()['rows']
    assert [row['additional_slippage_bps'] for row in scenarios] == [0, 5, 10]
    assert [row['applied_slippage_bps'] for row in scenarios] == [2, 7, 12]
    for row, scenario in zip(scenarios, final_window['scenarios'], strict=True):
        assert float(row['gap_pp']) == pytest.approx(scenario['best_runner_up_gap'] * 100, rel=1e-5)
        assert row['complete_record']['selected_recipe'] == scenario['selected_recipe']
    assert displayed('PERCENTAGE_POINTS') == ('pp' if language == 'en' else '百分点')
    view('members'); choose('Scenario', 2)
    members = final_window['scenarios'][2]['members']
    assert controller.tableModel.totalRows == 24 and len(controller.memberOptions) == 24
    assert [row['candidate_index'] for row in evidence()['rows']] == [row['candidate_index'] for row in members]
    last = evidence()['rows'][-1]
    assert last['complete_record']['recipe'] == members[-1]['recipe']
    for key in ('commission_total', 'slippage_total', 'initial_cash', 'final_cash'):
        assert float(last[key]) == pytest.approx(members[-1]['metrics'][key], rel=1e-5)
    scroll_bottom(); screenshot('q54-inner-members-' + language)
    view('accounts'); choose('Member', 23); choose('Section', controller.sectionOptions.index('execution.ledger'))
    assert '#23' in find('intradaySelectionDiagnosticsMember').property('currentText')
    screenshot('q54-final-dev-member23-' + language, 'SelectionSummary')
    ledger = members[-1]['execution']['ledger']
    first = evidence()
    assert first['scope'] == 'FINAL_DEV' and first['fold_index'] is None
    assert first['candidate_index'] == members[-1]['candidate_index'] and first['additional_slippage_bps'] == 10
    assert 'role' not in first and [row['complete_record'] for row in first['rows']] == ledger[:100]
    page_two(ledger); scroll_bottom(); screenshot('q54-inner-ledger-page2-' + language)
    view('fixed_evidence'); choose('Section', controller.sectionOptions.index('family_results'))
    page = evidence()
    assert page['window_index'] == len(cost_report['windows']) - 1
    assert not {'scenario_index', 'additional_slippage_bps', 'member_index', 'candidate_index', 'role'} & page.keys()
    assert [row['complete_record'] for row in page['rows']] == final_window['fixed_evidence']['family_results']
    view('baseline'); page = evidence()
    assert [row['complete_record'] for row in page['rows'][2:]] == final_window['baseline']['member_checks']
    assert page['rows'][0]['complete_record']['excluded_identity_fields'] == []
    view('choice_changes'); page = evidence()
    assert not {'window_index', 'scope', 'scenario_index', 'member_index', 'candidate_index', 'role', 'section'} & page.keys()
    assert [row['complete_record'] for row in page['rows']] == cost_report['choice_changes']
    copy_report(cost_report)
assert len(calls) == 2 and serialized.count(id(cost_report)) == 1
view('accounts'); choose('Member', 23)
open_study('q25')
assert controller.modeOptions == ['outer_risk'] and not controller.selectMode(1)
assert controller.completedMode == 'inner_cost' and controller._report is cost_report
assert len(controller.memberOptions) == 24 and controller.boundSource == bound
assert controller.draftChanged and 'inner_cost' not in controller.modeOptions
assert 'scenarios' in controller.viewOptions
copy_report(cost_report)
# One actual Q31 run verifies the native selector follows its four-member family.
open_study('q31'); choose('Mode', 1); q31 = run(); view('members')
assert len(controller.memberOptions) == controller.tableModel.totalRows == q31['sample']['family_size'] == 4
assert [row['candidate_index'] for row in evidence()['rows']] == [0, 1, 2, 3]
assert [mode for mode, _ in calls] == ['outer_risk', 'inner_cost', 'inner_cost']
assert calls[-1][1] == original[paths['q31']] and all(serialized.count(id(report)) == 1 for report in reports.values())
# Existing workspace sections remain reachable without replacing the new result.
for tab in ('intradayMLDiagnosticsTab', 'intradayProcedureTab', 'intradayProcedureStressTab', 'intradaySampleUsageTab', 'intradaySuiteTab'):
    click(tab); click('intradaySelectionDiagnosticsTab')
    assert controller._report is q31
print(json.dumps({'real_risk_runs': 1, 'real_inner_cost_runs': 2, 'locales': ['en', 'zh-CN'],
    'window': [1024, 600], 'risk_ledger_rows': len(risk_report['accounts']['procedure']['execution']['ledger']),
    'inner_kernel_calls': len(kernel_calls), 'full_report_serializations': len(serialized)}), flush=True)
finish('NATIVE_SELECTION_DIAGNOSTICS_EVIDENCE_PASS')
'''
    _run_native(tmp_path, body, "NATIVE_SELECTION_DIAGNOSTICS_EVIDENCE_PASS")


def test_native_selection_diagnostics_availability_stale_callbacks_and_retry(procedure_comparison_case, tmp_path, monkeypatch):
    case = procedure_comparison_case
    _sources(case, tmp_path)
    for name, key, field, delta in (("basis", "q31", "mark_price", 1), ("ledger", "q25", "cash", .01)):
        def change(execution, reference, field=field, delta=delta):
            execution["ledger"][0][field] += delta
        (tmp_path / (name + ".json")).write_bytes(reseal_procedure_benchmark(case.studies[key][0], change).content)
    blocked = case.studies["q31"][0].as_dict()
    account = blocked["report"]["outer_folds"][0]["inner"]["family_results"][0]["execution"]
    account["ledger"][0]["reason"] = "Changed saved semantic evidence"
    account["execution_id"] = execution_digest({key: value for key, value in account.items() if key != "execution_id"})
    (tmp_path / "blocked.json").write_bytes(StrategyExperiment(resigned(blocked)).content)
    short = tmp_path / "short"
    short.mkdir()
    unavailable, _, _ = _short_study(case, short, monkeypatch, kind="q31", minimum=14)
    (tmp_path / "unavailable.json").write_bytes(unavailable.content)
    body = r'''
open_study('q31'); prior = run(); bound, text = controller.boundSource, controller.completeReport
def retained():
    assert controller._report is prior and controller.boundSource == bound
    assert controller.completedMode == 'outer_risk' and controller.completeReport == text
    assert 'risk_summary' in controller.viewOptions

def change_back(axis):
    if axis == 'mode':
        choose('Mode', 1); choose('Mode', 0)
    else:
        fill(root / 'changed-while-running.json'); fill(paths['q31'])

def pending(failure=False):
    ready, release = threading.Event(), threading.Event()
    def delayed(snapshot):
        assert threading.get_ident() != gui_thread and snapshot.content == original[paths['q31']]
        ready.set(); assert release.wait(30)
        if failure: raise ValueError('controlled late risk failure')
        # A fresh result distinguishes accidental application without another fit or diagnostic run.
        return deepcopy(prior)
    risk.analyze_intraday_procedure_risk_diagnostics = delayed
    click('intradaySelectionDiagnosticsRunButton')
    deadline = time.monotonic() + 30
    while not ready.is_set() and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    assert ready.is_set() and controller.busy
    return release

for axis in ('path', 'mode'):
    release = pending(); change_back(axis); retained()
    release.set(); complete(); retained()
    assert controller.notice == 'STALE_INPUT' and controller.draftChanged
release = pending(failure=True); change_back('path'); release.set(); complete('STALE_INPUT')
assert not controller.studyError and not controller.error and controller.notice == 'STALE_INPUT'
retained(); risk.analyze_intraday_procedure_risk_diagnostics = measured_risk

# An Open also has a revision, including path A -> B -> A during the read.
ready, release = threading.Event(), threading.Event()
loader = experiments.load_strategy_experiment
def delayed_open(path):
    snapshot = loader(path); ready.set(); assert release.wait(30); return snapshot
experiments.load_strategy_experiment = delayed_open
click('intradaySelectionDiagnosticsOpenButton')
deadline = time.monotonic() + 30
while not ready.is_set() and time.monotonic() < deadline:
    app.processEvents(); time.sleep(.01)
assert ready.is_set(); change_back('path'); release.set(); complete()
experiments.load_strategy_experiment = loader
assert controller.notice == 'STALE_INPUT' and not controller.canRun
retained()
for path in (root / 'missing.json', paths['ordinary']):
    fill(path); click('intradaySelectionDiagnosticsOpenButton'); complete('FAILED')
    assert controller.studyError and not controller.canRun
    retained()
open_study('q31')
risk.analyze_intraday_procedure_risk_diagnostics = lambda snapshot: (_ for _ in ()).throw(ValueError('controlled current risk failure'))
click('intradaySelectionDiagnosticsRunButton'); complete('FAILED')
assert controller.studyError == 'controlled current risk failure' and controller.canRun
retained(); risk.analyze_intraday_procedure_risk_diagnostics = measured_risk
recovered = run()
assert recovered is not prior and recovered == prior
assert not controller.studyError and not controller.notice and not controller.draftChanged
copy_report(recovered)

# Individual role availability is independent of common-basis comparability.
open_study('basis'); partial = run()
assert partial['status'] == 'PARTIAL' and partial['account_availability']['available'] == 3
assert partial['comparability']['status'] == 'UNAVAILABLE'
for language in ('en', 'zh-CN'):
    assert session.i18n.setLanguage(language)
    assert session.i18n.catalog['selection_diagnostics.comparability'] in find('intradaySelectionDiagnosticsSummary').property('text')
    screenshot('q54-common-basis-partial-' + language, 'Summary')
    for index, role in enumerate(controller.roleOptions):
        choose('Role', index)
        assert controller.selectionSummary['status'] == 'AVAILABLE'
        assert any(row['metric'] == 'maximum_drawdown' for row in evidence()['rows'])
open_study('ledger'); failed_role = run()
assert failed_role['status'] == 'PARTIAL' and failed_role['account_availability']['available'] == 2
assert controller.modeOptions == ['outer_risk']
choose('Role', 2); page = evidence()
assert page['rows'][0]['status'] == 'UNAVAILABLE' and page['rows'][0]['complete_record']['report'] is None
assert controller.selectionSummary['role_diagnostics_id'] is None
assert 'RECORDED_LEDGER_RECONCILIATION_FAILED' == page['rows'][0]['unavailable_reason']
choose('Role', 0); assert controller.selectionSummary['status'] == 'AVAILABLE'

# One signed inner baseline mismatch retains the complete failed scenario family.
open_study('blocked'); choose('Mode', 1); blocked = run()
assert blocked['status'] == 'PARTIAL' and blocked['windows'][0]['status'] == 'UNAVAILABLE'
view('baseline'); page = evidence()
assert page['rows'][0]['matches'] is True and page['rows'][1]['matches'] is True
check = page['rows'][2]['complete_record']
assert check['matches'] is False and check['different_fields'] == ['execution_id', 'ledger']
view('members'); choose('Scenario', 1)
assert controller.selectionSummary['scenario']['status'] == 'UNAVAILABLE'
assert controller.selectionSummary['scenario']['selected_index'] is None and controller.selectionSummary['gap_display'] == '—'
assert controller.tableModel.totalRows == len(controller.memberOptions) == 4
assert all(row['total_return'] == row['commission_total'] == '—' for row in evidence()['rows'])
view('accounts'); choose('Section', controller.sectionOptions.index('execution'))
assert evidence()['rows'][0]['complete_record'] is None

# A legal unavailable Q31 source can be opened in both modes, with literal nulls.
open_study('unavailable'); unavailable_cost = run()
assert unavailable_cost['source_status'] == unavailable_cost['status'] == 'UNAVAILABLE'
for language in ('en', 'zh-CN'):
    assert session.i18n.setLanguage(language)
    view('choice_changes'); page = evidence()
    assert len(page['rows']) == 6
    assert all(row['eligible_window_count'] == 0 and row['changed_choice_rate'] == '—' and row['changed_choice_count'] is None for row in page['rows'])
    assert all(row['complete_record']['changed_choice_count'] is row['complete_record']['changed_choice_rate'] is None for row in page['rows'])
    assert all(row['unavailable_reason'] == 'NO_ELIGIBLE_WINDOWS' for row in page['rows'])
    scroll_bottom(); screenshot('q54-no-eligible-windows-' + language)
    view('members'); choose('Window', len(controller.windowOptions) - 1); choose('Scenario', 2)
    assert not controller.memberOptions and controller.tableModel.totalRows == 0
    assert controller.selectionSummary['scenario']['member_counts'] == {'declared': 4, 'recorded': 0, 'executed': 0, 'available': 0}
    assert 'undefined' not in find('intradaySelectionDiagnosticsSelectionSummary').property('text')
    view('accounts')
    assert not find('intradaySelectionDiagnosticsMember').property('enabled')
    page = evidence()
    assert page['member_index'] is page['candidate_index'] is None
    assert page['rows'][0]['complete_record'] == [] and page['rows'][0]['record_path'].endswith('/members')
    copy_report(unavailable_cost)
choose('Mode', 0); unavailable_risk = run()
assert unavailable_risk['status'] == 'UNAVAILABLE' and unavailable_risk['accounts']['procedure'] is None
assert controller.selectionSummary['status'] == 'UNAVAILABLE'
assert evidence()['rows'][0]['complete_record']['report'] is None
assert not controller.draftChanged and not controller.studyError
print(json.dumps({'stale_success_axes': ['path', 'mode', 'open_path'], 'stale_failure_axis': 'path',
    'risk_basis_partial_available_roles': 3, 'risk_ledger_partial_available_roles': 2,
    'inner_failed_baseline_family_size': 4, 'unavailable_change_rates_are_null': True}), flush=True)
finish('NATIVE_SELECTION_DIAGNOSTICS_RECOVERY_PASS')
'''
    _run_native(tmp_path, body, "NATIVE_SELECTION_DIAGNOSTICS_RECOVERY_PASS")
