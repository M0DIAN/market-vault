"""Native five-series outer returns, fixed defaults and complete account records."""

from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys

import pytest

# Skip before importing or constructing the real short and 100-day fixtures.
pytest.importorskip("PySide6")

from market_vault.research import intraday_inner_selection as inner
from market_vault.research import intraday_research as research
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.strategy_experiment import write_strategy_experiment
from test_strategy_intraday_ml import quadratic_dev_case  # noqa: F401
from test_strategy_intraday_inner_selection import inner_case  # noqa: F401
from test_strategy_intraday_threshold_selection import threshold_case  # noqa: F401
from test_strategy_intraday_procedure_return_uncertainty import procedure_return_case  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]


def test_native_procedure_returns_defaults_records_modes_intervals_and_compact(
        quadratic_dev_case, inner_case, threshold_case, procedure_return_case, tmp_path):
    data, plan, _, _, _, _ = quadratic_dev_case
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
import copy, json, sys, threading, time
from decimal import Decimal
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
from market_vault.research import intraday_procedure_return_uncertainty as procedure
from market_vault.research import intraday_inner_selection as inner
from market_vault.research import intraday_research as research
from market_vault.research import intraday_threshold_selection as threshold

root, ordinary_path, inner_path, threshold_path, unavailable_path, data_path, threshold_source_path, long_path, long_source, long_data = map(Path, sys.argv[1:])
original_bytes = {path: path.read_bytes() for path in
    (ordinary_path, inner_path, threshold_path, unavailable_path, data_path, threshold_source_path, long_path, long_source, long_data)}
series_order = ['procedure', 'fixed_reference', 'benchmark', 'procedure_minus_fixed_reference', 'procedure_minus_benchmark']
assert translation_keys_match()
QQuickStyle.setStyle('Basic')
app = QGuiApplication([]); engine = QQmlApplicationEngine()
warnings = []
engine.warnings.connect(lambda messages: warnings.extend(message.toString() for message in messages))
session = create_qml_application_session(build_application_context(root / 'settings.yaml'), engine,
    preference_store=DesktopPreferenceStore(root=root / 'preferences'))
engine.load(QUrl.fromLocalFile(str(Path.cwd() / 'src/market_vault/desktop/qml/Main.qml')))
assert engine.rootObjects(), warnings
window = engine.rootObjects()[0]; window.setWidth(1200); window.setHeight(1000)
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
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point); app.processEvents()

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

def reconstruct(rows):
    # Rebuild every original account from the exported record paths. This
    # detects missing keys/empty collections, not just matching row counts.
    result = {}
    for row in rows:
        parts = [part.replace('~1', '/').replace('~0', '~') for part in row['record_path'].split('/')[1:]]
        cursor = result
        for index, part in enumerate(parts):
            last = index == len(parts) - 1
            key = int(part) if isinstance(cursor, list) else part
            if isinstance(cursor, list):
                while len(cursor) <= key: cursor.append(None)
            if last:
                cursor[key] = copy.deepcopy(row['complete_record'])
            else:
                if (isinstance(cursor, dict) and key not in cursor) or cursor[key] is None:
                    cursor[key] = [] if parts[index + 1].isdigit() else {}
                cursor = cursor[key]
    return result['accounts']

click('quantIntradayTab'); click('intradayMLDiagnosticsTab'); QTest.qWait(50)
open_source(ordinary_path); click('intradayMLRunButton'); complete()
choose('intradayMLView', 4); choose('intradayMLScope', 1)
quality, quality_evidence = controller._report, evidence()
assert find('intradayMLDataPath').setProperty('text', 'ignored/relative/q5')
choose('intradayMLMode', 2)
assert controller.uncertaintyMode and controller.recordedOnlyMode and not controller.canRun
assert not find('intradayMLDataRow').property('visible') and not find('intradayMLCost').property('visible')
assert controller._report == quality and evidence() == quality_evidence
assert 'Outer DEV prediction quality' in find('intradayMLSummary').property('text')

# Every subsequent analysis consumes only a saved study, including the long
# interval case. Guard the real source paths as well as Q5/fit/Q6 entry points.
actual_open = Path.open
forbidden_paths = {path.resolve() for path in (ordinary_path, data_path, threshold_source_path, long_source, long_data)}
def guarded_open(path, mode='r', *args, **kwargs):
    assert path.resolve() not in forbidden_paths or not ('r' in mode or '+' in mode), 'Read an original source or Q5'
    return actual_open(path, mode, *args, **kwargs)
Path.open = guarded_open
def forbidden(*args, **kwargs): raise AssertionError('Refitted or replayed a recorded-only diagnostic')
for module, names in ((research, ('load_intraday_dataset', '_prepare_intraday_research', '_fit', 'run_intraday_execution')),
                      (inner, ('_fit', '_evaluate', 'run_intraday_execution')),
                      (threshold, ('_fit', '_evaluate', 'run_intraday_execution')),
                      (execution, ('run_intraday_execution',))):
    for name in names: setattr(module, name, forbidden)
actual, calls = procedure.analyze_intraday_procedure_return_uncertainty, []
gui_thread = threading.get_ident()
def measured(snapshot, *args, **kwargs):
    assert threading.get_ident() != gui_thread and not args and not kwargs
    result = actual(snapshot)
    calls.append(result)
    return result
procedure.analyze_intraday_procedure_return_uncertainty = measured
open_source(inner_path)
assert controller.canRun and controller._report == quality
click('intradayMLRunButton'); complete()
assert controller.completedUncertainty and controller.viewIndex == controller.scopeIndex == 0

# Real Q34 completion followed by Q35 must change the completed result type;
# changing only a draft method in either direction must leave it untouched.
first_return = controller._report
choose('intradayMLMode', 1)
assert controller._report == first_return and controller.completedUncertainty
assert controller.viewOptions == ['return_intervals', 'daily_returns', 'return_basis', 'outer_accounts']
click('intradayMLRunButton'); complete()
assert controller.completedSensitivity and not controller.completedUncertainty
choose('intradayMLScope', len(controller._report['windows'])); choose('intradayMLView', 5)
sensitivity_report, sensitivity_evidence = controller._report, evidence()
choose('intradayMLMode', 2)
assert controller._report == sensitivity_report and evidence() == sensitivity_evidence
ready, release = threading.Event(), threading.Event()
def delayed(snapshot):
    result = measured(snapshot); ready.set()
    assert release.wait(30)
    return result
procedure.analyze_intraday_procedure_return_uncertainty = delayed
click('intradayMLRunButton')
deadline = time.monotonic() + 90
while not ready.is_set() and time.monotonic() < deadline:
    app.processEvents(); time.sleep(.01)
assert ready.is_set()
choose('intradayMLMode', 0); choose('intradayMLMode', 2)
release.set(); complete()
assert controller.notice == 'STALE_INPUT' and controller._report == sensitivity_report
assert evidence() == sensitivity_evidence
procedure.analyze_intraday_procedure_return_uncertainty = measured
click('intradayMLRunButton'); complete()
assert controller.completedUncertainty and controller.viewIndex == controller.scopeIndex == 0

for path, expected_kind, reference in ((inner_path, 'INNER_MODEL_SELECTION', (1, 1)),
                                      (threshold_path, 'ECONOMIC_THRESHOLD_SELECTION', (0, 1))):
    if path != inner_path:
        open_source(path); click('intradayMLRunButton'); complete()
    report = controller._report
    assert report == calls[-1] and report['source_kind'] == expected_kind
    assert report['parameters'] == {'block_days': None, 'replications': 5000, 'seed': 0}
    assert report['sampling']['confidence_level'] == .95 and report['sampling']['block_days_source'] == 'CUBE_ROOT_HEURISTIC'
    assert tuple(report['source_selection'][key] for key in ('cost_index', 'candidate_index')) == reference
    assert not controller.draftChanged and not controller.notice and controller.scopeOptions == [{'kind': 'all_outer_returns', 'fold_index': None}]
    assert controller.selectScope(1) is False
    details = json.loads(controller.completedDetails)
    assert details['uncertainty_id'] == report['uncertainty_id'] and details['source_path'] == str(path)
    assert details['sampling'] == report['sampling'] and details['parameters'] == report['parameters']
    assert not any(key in details for key in ('requested_data_locator', 'requested_cost_index', 'requested_candidate_index'))
    assert not any(details['evidence'][key] for key in ('source_reconstructed', 'models_refitted', 'execution_replayed'))
    choose('intradayMLView', 0)
    assert controller.tableModel.totalRows == 5
    assert [row['complete_record'] for row in controller._evidence_rows] == report['statistics']
    assert [row['return_series'] for row in controller._evidence_rows] == series_order
    assert [row['unit'] for row in controller._evidence_rows] == ['RATIO'] * 3 + ['PERCENTAGE_POINTS'] * 2
    assert all(row['mean'] is not None and row['lower'] is row['upper'] is None for row in report['statistics'])
    assert all(row['interval_unavailable_reason'] in ('INSUFFICIENT_DAILY_RETURNS', 'ZERO_SAMPLE_VARIATION') for row in report['statistics'])
    assert evidence()['rows'][3]['complete_record']['unit'] == 'RATIO'
    choose('intradayMLView', 1)
    assert controller.tableModel.totalRows == report['sample']['sample_count']
    assert [row['complete_record'] for row in controller._evidence_rows] == report['daily']
    assert controller._columns[-5:] == tuple(series_order)
    choose('intradayMLView', 2)
    assert report['basis']['matches'] and controller.tableModel.totalRows == len(report['basis']['checks'])
    assert [row['complete_record'] for row in controller._evidence_rows] == report['basis']['checks']
    assert all(displayed(row['basis_check']) != row['basis_check'] for row in controller._evidence_rows)
    choose('intradayMLView', 3)
    all_rows = copy.deepcopy(controller._evidence_rows)
    assert reconstruct(all_rows) == report['accounts']
    assert controller.evidenceAccountOptions == ['all_accounts', *report['accounts']]
    call_count, captured = len(calls), controller._key()
    choose('intradayMLEvidenceAccount', 2)
    choose('intradayMLEvidenceSection', controller.evidenceSectionOptions.index('execution.daily'))
    assert [row['complete_record'] for row in controller._evidence_rows] == report['accounts']['fixed_reference']['execution']['daily']
    selected_rows = copy.deepcopy(controller._evidence_rows)
    page = evidence()
    assert page['account'] == 'fixed_reference' and page['section'] == 'execution.daily'
    assert page['rows'] == selected_rows and 'accounts' not in page
    choose('intradayMLView', 1)
    assert len(controller._evidence_rows) == len(report['daily']) and controller._columns[-5:] == tuple(series_order)
    choose('intradayMLView', 3)
    assert controller._evidence_rows == selected_rows
    choose('intradayMLEvidenceAccount', 0)
    assert controller.evidenceSectionIndex == 0 and controller._evidence_rows == all_rows
    assert controller._key() == captured and controller._report == report and len(calls) == call_count

# Draft Q33/Q34 choices and a failed Q35 worker leave the complete Q35 result
# and readable filtered subset intact; default analysis can then recover.
before = controller._report
choose('intradayMLEvidenceAccount', 3)
choose('intradayMLEvidenceSection', controller.evidenceSectionOptions.index('execution.policy'))
before_evidence = evidence()
for mode in (0, 1, 2):
    choose('intradayMLMode', mode)
    assert controller.completedUncertainty and controller._report == before and evidence() == before_evidence
    assert 'Approximate 95% intervals' in find('intradayMLInterpretation').property('text')
def failed(snapshot):
    assert threading.get_ident() != gui_thread
    raise ValueError('Native procedure return failure recovery probe')
procedure.analyze_intraday_procedure_return_uncertainty = failed
click('intradayMLRunButton'); complete('FAILED')
assert controller.studyError and controller._report == before and evidence() == before_evidence
procedure.analyze_intraday_procedure_return_uncertainty = measured
click('intradayMLRunButton'); complete()
assert not controller.studyError and not controller.draftChanged and controller._report == before

# A real four-fold, 100-day study exercises available intervals at the API's
# unchanged production defaults; the two short studies above cannot do this.
open_source(long_path); click('intradayMLRunButton'); complete()
report = controller._report
assert report['sample']['sample_count'] == 100 and report['sample']['fold_count'] == 4
assert report['sampling']['replications'] == 5000 and report['sampling']['seed'] == 0
choose('intradayMLView', 0)
paired = next(row for row in report['statistics'] if row['series'] == 'procedure_minus_fixed_reference')
assert paired['lower'] is not None and paired['upper'] is not None and paired['interval_unavailable_reason'] is None
shown = next(row for row in controller._evidence_rows if row['return_series'] == paired['series'])
assert shown['return_lower_95'] == f"{Decimal(str(paired['lower'])) * 100:.6g}"
assert shown['return_upper_95'] == f"{Decimal(str(paired['upper'])) * 100:.6g}"
assert shown['unit'] == 'PERCENTAGE_POINTS' and shown['complete_record'] == paired
assert window.grabWindow().save(str(root / 'q35-available-intervals-en.png'))
assert session.i18n.setLanguage('zh-CN')
assert find('intradayMLMode').property('currentText') == '程序外层收益与增量区间'
assert displayed('procedure_minus_fixed_reference') == '程序 − 固定参照'
assert displayed('INSUFFICIENT_DAILY_RETURNS') == '不足 100 个评估日'
assert window.grabWindow().save(str(root / 'q35-available-intervals-zh.png'))
choose('intradayMLView', 3)
choose('intradayMLEvidenceAccount', 2)
choose('intradayMLEvidenceSection', controller.evidenceSectionOptions.index('execution.ledger'))
assert find('intradayMLEvidenceSection').property('currentText') == '完整原始账本'
assert [row['complete_record'] for row in controller._evidence_rows] == report['accounts']['fixed_reference']['execution']['ledger']
expected_page = controller._evidence_rows[100:200]
window.setWidth(1024); window.setHeight(600); QTest.qWait(100)
scroll = find('intradayMLScroll'); flick = scroll.property('contentItem')
assert flick.property('contentHeight') > scroll.property('availableHeight')
bar = find('intradayMLScrollBar'); thumb = bar.property('contentItem')
start = thumb.mapToScene(thumb.boundingRect().center()).toPoint()
end = bar.mapToScene(QPointF(bar.width() / 2, bar.height() - 2)).toPoint()
QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
QTest.mouseMove(window, end, 50); QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end); QTest.qWait(50)
assert flick.property('contentY') > 0 and controller.tableModel.hasNext
pagination = nested(find('intradayMLTable'), 'PixelPagination')
click_obj(next(child for child in pagination.findChildren(QObject) if child.property('glyph') == 'next'))
assert controller.tableModel.page == 2 and json.loads(controller.currentPageEvidence)['rows'] == expected_page
assert window.grabWindow().save(str(root / 'q35-compact-ledger-zh.png'))
page_state = controller.currentPageEvidence
assert session.i18n.setLanguage('en')
assert controller.currentPageEvidence == page_state and controller.tableModel.page == 2
assert controller._report == report and controller._report['uncertainty_id'] == calls[-1]['uncertainty_id']

window.setWidth(1200); window.setHeight(1000); QTest.qWait(50)
flick.setProperty('contentY', 0); app.processEvents()
click('intradayMLEvidenceButton')
assert window.grabWindow().save(str(root / 'q35-full-ledger-record-en.png'))
QTest.keyClick(window, Qt.Key_Escape); app.processEvents()
open_source(unavailable_path); click('intradayMLRunButton'); complete()
assert controller.completedUncertainty and controller.resultSummary['status'] == 'UNAVAILABLE'
assert controller._report['sample'] is controller._report['sampling'] is controller._report['basis'] is None
assert controller._report['accounts'] == {} and controller._report['daily'] == controller._report['statistics'] == []
assert controller.tableModel.totalRows == 0 and controller.evidenceAccountOptions == ['all_accounts']
assert json.loads(controller.completedDetails)['unavailable_reasons'] and not controller.studyError
Path.open = actual_open
assert all(path.read_bytes() == content for path, content in original_bytes.items())
assert not any('IntradayMLDiagnosticsPanel' in warning or 'IntradayWorkspacePanel' in warning for warning in warnings), warnings
procedure.analyze_intraday_procedure_return_uncertainty = actual
assert session.shutdown(); engine.deleteLater(); app.processEvents()
print('NATIVE_PROCEDURE_RETURNS_PASS')
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(inner_case[2]), str(inner_case[5]),
        str(threshold_case[5]), str(unavailable_path), str(data.path), str(threshold_case[2]),
        str(procedure_return_case.studies["q25"][1]), str(procedure_return_case.path), str(procedure_return_case.data.path)],
        cwd=ROOT, env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software", "PYTHONPATH": str(ROOT / "src")},
        text=True, capture_output=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NATIVE_PROCEDURE_RETURNS_PASS" in result.stdout
