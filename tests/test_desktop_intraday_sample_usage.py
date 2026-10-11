"""Real compact native sample-use evidence, immutable capture and recovery."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

# Qt-free CI skips before constructing the existing real Q5 fixture.
pytest.importorskip("PySide6")

from market_vault.quality import market_data_comparison as comparison
from market_vault.research import intraday_inner_selection as inner
from market_vault.research import intraday_research as research
from market_vault.research import intraday_threshold_selection as threshold
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.intraday_market_evidence import INTRADAY_MARKET_EVIDENCE_PLAN_VERSION
from market_vault.research.strategy_experiment import write_strategy_experiment
from test_strategy_intraday_ml import quadratic_dev_case  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]


def test_native_sample_usage_capture_stages_dependencies_save_and_compact(quadratic_dev_case, tmp_path):
    data, saved_plan, _, _, _, _ = quadratic_dev_case
    plan = deepcopy(saved_plan)
    plan["strategies"] = [
        {"kind": "FEATURE_RULE", "name": "Rule0", "signal_field": "return_2", "comparator": "GT", "threshold": 1},
        {"kind": "RIDGE", "name": "Ridge1", "alpha": 1, "threshold": 1},
    ]
    source = create_intraday_experiment(plan=plan, report=research.run_intraday_research(plan), name="Captured Rule0 / Ridge1")
    source_path = write_strategy_experiment(source, path=tmp_path / "ordinary.json").path
    # Open binds canonical snapshot content, independent of the file's whitespace.
    source_path.write_text(json.dumps(source.as_dict(), indent=2), encoding="utf-8")
    candidate = source.as_dict()["report"]["groups"][0]["results"][1]
    assert candidate["execution"]["metrics"]["trade_count"] == 0
    args = {"expected_experiment_id": source.experiment_id, "cost_index": 0, "candidate_index": 1,
            "expected_candidate_id": candidate["candidate_id"]}
    study = threshold.run_intraday_threshold_selection(source_path, **args)
    assert study.as_dict()["report"]["status"] == "AVAILABLE"
    write_strategy_experiment(study, path=tmp_path / "q31.json")
    short_plan = deepcopy(plan)
    short_plan["walk_forward"]["minimum_train_days"] = 14
    short = create_intraday_experiment(plan=short_plan, report=research.run_intraday_research(short_plan))
    short_path = write_strategy_experiment(short, path=tmp_path / "short.json").path
    unavailable = inner.run_intraday_inner_selection(short_path, expected_experiment_id=short.experiment_id,
        cost_index=0, candidate_index=1,
        expected_candidate_id=short.as_dict()["report"]["groups"][0]["results"][1]["candidate_id"])
    assert unavailable.as_dict()["report"]["status"] == "UNAVAILABLE"
    write_strategy_experiment(unavailable, path=tmp_path / "unavailable.json")
    manifest_dir = tmp_path / "evidence"
    manifest_dir.mkdir()
    declared = {"provider": "native-synthetic-local", "version": "v1", "captured_at": "2026-01-03T00:00:00Z",
                "data_kind": "SYNTHETIC", "upstream_id": "local", "upstream_evidence": "synthetic fixture"}
    basis = {"asset_class": "ETF", "currency": "USD", "aggregation": "TRADE_OHLCV", "volume_basis": "SHARES"}
    q5_report, references = data.as_dict()["report"], []
    for session in q5_report["sessions"]:
        day = session["trading_day"]
        scope = {"symbol": q5_report["symbol"], "interval": q5_report["interval"], "adjustment": "NONE", "session": "RTH",
                 **basis, "window_start": comparison.utc_text(comparison.parse_utc(session["open_time"])),
                 "window_end": comparison.utc_text(comparison.parse_utc(session["close_time"]))}
        bars = [{"start": comparison.utc_text(comparison.parse_utc(row["event_time"])),
                 "end": comparison.utc_text(comparison.parse_utc(row["available_at"])),
                 **{field: row[field] for field in comparison.VALUE_FIELDS}}
                for row in q5_report["prices"] if row["trading_day"] == day]
        bars[0]["volume"] += 1  # Feature/grid exposure, with unchanged numerical open/close endpoints.
        snapshot = {"schema_version": comparison.SNAPSHOT_SCHEMA_VERSION, "scope": scope,
                    "source": {**declared, "provider": "native-synthetic-reference", "upstream_id": "reference"}, "bars": bars}
        (manifest_dir / f"{day}.json").write_bytes(comparison.json_bytes(snapshot))
        references.append({"scope": scope, "snapshot": f"{day}.json"})
    (manifest_dir / "plan.json").write_bytes(comparison.json_bytes({"schema_version": INTRADAY_MARKET_EVIDENCE_PLAN_VERSION,
        "source": declared, "basis": basis, "references": references}))
    (tmp_path / "settings.yaml").write_text("storage:\n  root_dir: ./data\n")
    script = r'''
import hashlib, json, sys, threading, time
from pathlib import Path
import pytest
from PySide6.QtCore import QObject, QUrl, Qt, QEvent, QMetaObject, QPointF
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from market_vault.application import build_application_context
from market_vault.desktop.bootstrap import create_qml_application_session
from market_vault.desktop.preferences import DesktopPreferenceStore
from market_vault.desktop.localization import translation_keys_match
from market_vault.quality import market_data_comparison as market
from market_vault.research import intraday_data as q5, intraday_sample_usage as usage
from market_vault.research import intraday_research as research, intraday_inner_selection as inner
from market_vault.research import intraday_threshold_selection as threshold, intraday_joint_selection as joint
from market_vault.research import strategy_experiment as experiments
from market_vault.backtest import intraday as execution

root, data_path = map(Path, sys.argv[1:])
paths = {name: root / (name + '.json') for name in ('ordinary', 'q31', 'unavailable')}
manifest = root / 'evidence' / 'plan.json'
relocated = root / 'relocated-q5.json'; relocated.write_bytes(data_path.read_bytes())
original = {path: path.read_bytes() for path in (*paths.values(), data_path, relocated, *manifest.parent.glob('*.json'))}
assert translation_keys_match()
QQuickStyle.setStyle('Basic')
app = QGuiApplication([]); engine = QQmlApplicationEngine(); warnings = []
engine.warnings.connect(lambda values: warnings.extend(value.toString() for value in values))
context = build_application_context(root / 'settings.yaml')
session = create_qml_application_session(context, engine, preference_store=DesktopPreferenceStore(root=root / 'preferences'))
engine.load(QUrl.fromLocalFile(str(Path.cwd() / 'src/market_vault/desktop/qml/Main.qml')))
assert engine.rootObjects(), warnings
window = engine.rootObjects()[0]; window.setWidth(1280); window.setHeight(1100)
controller = session.context_properties['quantResearchController'].intradaySampleUsageController
assert session.i18n.setLanguage('en') and session.shell.selectPage('quant_research')

def find(name):
    found = window.findChild(QObject, name)
    if found is not None: return found
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
    scroll = find('intradaySampleUsageScroll')
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
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point); app.processEvents()

def click(name): click_obj(find(name))

def choose(name, index):
    obj = find(name); reveal(obj); window.requestActivate(); QTest.qWait(20)
    combo = nested(obj, 'PixelComboBox'); combo.forceActiveFocus()
    if obj.property('currentIndex') != index:
        QTest.keyClick(window, Qt.Key_Space)
        QTest.keyClick(window, Qt.Key_Home)
        for _ in range(index): QTest.keyClick(window, Qt.Key_Down)
        QTest.keyClick(window, Qt.Key_Return)
    app.processEvents()
    assert obj.property('currentIndex') == index, (name, obj.property('currentIndex'))

def fill(name, value):
    obj = find(name); reveal(obj); window.requestActivate(); QTest.qWait(20)
    nested(obj, 'PixelTextField').forceActiveFocus()
    QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier); QTest.keyClick(window, Qt.Key_Backspace)
    for char in str(value):
        QGuiApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, ord(char.upper()), Qt.NoModifier, char))
    app.processEvents()
    assert obj.property('text') == str(value)

def complete(status='SUCCESS'):
    deadline = time.monotonic() + 90
    while controller.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    app.processEvents()
    assert not controller.busy and controller.status == status, (controller.status, controller.error, warnings)

def browse(kind, path):
    click('intradaySampleUsage' + kind + ('Button' if kind == 'Save' else 'Browse'))
    dialog = find('intradaySampleUsage' + kind + 'Dialog')
    assert dialog.property('visible')
    assert dialog.setProperty('selectedFile', QUrl.fromLocalFile(str(path)))
    assert QMetaObject.invokeMethod(dialog, 'accepted', Qt.DirectConnection)
    QMetaObject.invokeMethod(dialog, 'close', Qt.DirectConnection); app.processEvents()

def open_source(path):
    browse('Source', path)
    assert not controller.busy
    click('intradaySampleUsageOpenButton'); complete()

def page_evidence():
    click('intradaySampleUsageEvidenceButton')
    text = find('intradaySampleUsageEvidenceText')
    assert text.property('readOnly') and text.property('selectByMouse')
    result = json.loads(text.property('text'))
    QTest.keyClick(window, Qt.Key_Escape); app.processEvents()
    assert text.property('text') == ''
    return result

# Saved fixtures are constructed before these forbidden fitting/execution gates.
patch = pytest.MonkeyPatch()
def forbidden(*args, **kwargs): raise AssertionError('native evidence must not fit/select/replay/execute')
for module, names in ((research, ('_fit', 'candidate_predictions', '_evaluate_intraday_research', 'run_intraday_execution')),
                      (inner, ('_fit', '_select', '_evaluate')),
                      (threshold, ('_fit', '_select', '_evaluate')),
                      (joint, ('_fit', '_select', '_evaluate')),
                      (execution, ('run_intraday_execution',)), (experiments, ('replay_strategy_experiment',))):
    for name in names: patch.setattr(module, name, forbidden)
actual, reads, verifications, calls = usage.analyze_intraday_sample_usage, [], [], []
read, verify, gui_thread = market.read_json_file, q5.verify_intraday_dataset, threading.get_ident()
def read_once(path):
    reads.append(str(path)); return read(path)
def verified(snapshot):
    verifications.append(snapshot.data_id); return verify(snapshot)
def analyzed(*args, **kwargs):
    assert threading.get_ident() != gui_thread
    result = actual(*args, **kwargs); calls.append((args[0].experiment_id, kwargs, result)); return result
patch.setattr(market, 'read_json_file', read_once)
patch.setattr(q5, 'verify_intraday_dataset', verified)
patch.setattr(usage, 'analyze_intraday_sample_usage', analyzed)
click('quantIntradayTab'); click('intradaySampleUsageTab'); QTest.qWait(30)
assert not controller.resultLoaded and not controller.canRun
browse('Source', paths['ordinary'])
assert not controller.sourceInfo and not reads and not verifications
click('intradaySampleUsageOpenButton'); complete()
assert controller.ordinarySource and controller.candidateIndex == 0 and not controller.canRun
assert controller.inputReason == 'LEARNED_CANDIDATE_REQUIRED' and 'Rule0' in controller.candidateNames[0]
canonical_sha = hashlib.sha256(experiments.StrategyExperiment(original[paths['ordinary']]).content).hexdigest()
assert controller.sourceInfo['content_sha256'] == canonical_sha
assert canonical_sha != hashlib.sha256(original[paths['ordinary']]).hexdigest()
choose('intradaySampleUsageCandidate', 1)
assert controller.inputReason == 'MANIFEST_REQUIRED'
browse('Manifest', manifest); browse('Data', relocated)
assert controller.canRun and not reads and not verifications and not calls
loader = experiments.load_strategy_experiment
paths['ordinary'].write_bytes(b'changed after explicit Open')
experiments.load_strategy_experiment = forbidden
click('intradaySampleUsageRunButton'); complete()
experiments.load_strategy_experiment = loader
paths['ordinary'].write_bytes(original[paths['ordinary']])
report = controller._report
assert len(calls) == len(reads) == len(verifications) == 1 and reads == [str(manifest)]
assert report == calls[0][2] and report['source']['source_kind'] == 'ORDINARY' and report['status'] == 'AVAILABLE'
assert report['source']['source_selection']['candidate_index'] == 1
assert report['dependency_evidence']['market_evidence']['data']['locator'] == str(relocated)
assert report['analysis_actions']['q5_strict_verification_count'] == 1
assert not any(report['analysis_actions'][key] for key in ('models_refitted', 'selection_rerun', 'execution_replayed', 'full_research_replay'))
assert context.backend_if_initialized is None
bound = controller.boundSource
assert bound['requested_candidate_index'] == 1 and bound['opened_source_content_sha256'] == report['source']['content_sha256']
assert bound['opened_source_path'] == str(paths['ordinary'])
assert bound['requested_manifest_path'] == QUrl.fromLocalFile(str(manifest)).toString()
assert bound['requested_data_locator'] == QUrl.fromLocalFile(str(relocated)).toString()
assert not controller.draftChanged
training = next(stage for stage in report['stages'] if stage['stage_kind'] == 'OUTER_MODEL_TRAINING')
assert training['support_counts']['feature_window']['different_sample_count'] > 0
assert training['support_counts']['target_endpoints']['different_sample_count'] == 0
choose('intradaySampleUsageView', 1)
assert page_evidence()['rows'] == report['stages'][:100]
choose('intradaySampleUsageView', 2)
choose('intradaySampleUsageStage', training['stage_index'])
assert controller.tableModel.totalRows == training['recorded_sample_count'] > 100
first_page = page_evidence()
assert [row['sample_ref'] for row in first_page['rows']] == training['sample_refs'][:100]
assert first_page['rows'][0]['observation'] == report['dependency_evidence']['observations'][training['sample_refs'][0]]
choose('intradaySampleUsageView', 3)
assert page_evidence()['sample']['sample_ref'] == training['sample_refs'][0]
bar = page_evidence()['rows'][0]['bar']
assert bar['local_state'] == 'PRESENT' and bar['status'] == 'DIFFERENT'
assert bar['differences']['open']['within_tolerance'] and not bar['differences']['volume']['within_tolerance']
assert page_evidence()['references']

# Full report/copy/save all use the completed chain, including after draft edits.
click('intradaySampleUsageReportButton')
assert json.loads(find('intradaySampleUsageReportText').property('text'))['capture'] == bound
choose('intradaySampleUsageReportSection', 1)
assert json.loads(find('intradaySampleUsageReportText').property('text')) == report
QTest.keyClick(window, Qt.Key_Escape); app.processEvents()
assert find('intradaySampleUsageReportText').property('text') == ''
click('intradaySampleUsageCopyReportButton')
assert json.loads(QGuiApplication.clipboard().text()) == report
fill('intradaySampleUsageManifestPath', root / 'new-draft.json')
assert controller.draftChanged and controller.boundSource == bound and controller._report is report
output = root / 'saved-evidence.json'; browse('Save', output); complete()
assert json.loads(output.read_bytes()) == report and controller.savedPath == str(output)
saved_bytes = output.read_bytes()
assert controller.saveReport(str(output)); complete('FAILED')
assert output.read_bytes() == saved_bytes and controller._report is report and controller.studyError
fill('intradaySampleUsageManifestPath', manifest)
click('intradaySampleUsageRunButton'); complete()
report, bound = controller._report, controller.boundSource
assert not controller.studyError and not controller.draftChanged

# Every retained input has monotonic revision semantics, even edit -> restore.
for changed_input in ('candidate', 'source', 'manifest', 'data'):
    ready, release = threading.Event(), threading.Event()
    def delayed(*args, **kwargs):
        value = analyzed(*args, **kwargs); ready.set(); assert release.wait(30); return value
    usage.analyze_intraday_sample_usage = delayed
    click('intradaySampleUsageRunButton')
    deadline = time.monotonic() + 90
    while not ready.is_set() and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    assert ready.is_set()
    if changed_input == 'candidate':
        choose('intradaySampleUsageCandidate', 0); choose('intradaySampleUsageCandidate', 1)
    else:
        names = {'source': ('SourcePath', paths['ordinary']), 'manifest': ('ManifestPath', manifest), 'data': ('DataPath', relocated)}
        field, previous = names[changed_input]
        fill('intradaySampleUsage' + field, root / ('edited-' + changed_input + '.json'))
        fill('intradaySampleUsage' + field, previous)
    release.set(); complete(); usage.analyze_intraday_sample_usage = analyzed
    assert controller.notice == 'STALE_INPUT' and controller._report is report and controller.boundSource == bound
# A failed stale worker also cannot replace the completed evidence or current error.
ready, release = threading.Event(), threading.Event()
def delayed_failure(*args, **kwargs):
    ready.set(); assert release.wait(30); raise ValueError('late analysis failure')
usage.analyze_intraday_sample_usage = delayed_failure
click('intradaySampleUsageRunButton')
deadline = time.monotonic() + 90
while not ready.is_set() and time.monotonic() < deadline:
    app.processEvents(); time.sleep(.01)
assert ready.is_set()
fill('intradaySampleUsageManifestPath', root / 'edited-failure.json')
fill('intradaySampleUsageManifestPath', manifest)
release.set(); complete('STALE_INPUT'); usage.analyze_intraday_sample_usage = analyzed
assert controller.notice == 'STALE_INPUT' and not controller.studyError and not controller.error
assert controller._report is report and controller.boundSource == bound
fill('intradaySampleUsageManifestPath', root / 'missing.json')
click('intradaySampleUsageRunButton'); complete('FAILED')
assert controller.studyError and controller._report is report
fill('intradaySampleUsageManifestPath', manifest)
fill('intradaySampleUsageSourcePath', root / 'missing-source.json')
click('intradaySampleUsageOpenButton'); complete('FAILED')
assert not controller.canRun and controller._report is report and controller.boundSource == bound
open_source(paths['q31'])
assert not controller.ordinarySource and controller.costNames == controller.candidateNames == []
assert controller.costIndex == controller.candidateIndex == 0 and controller._report is report
click('intradaySampleUsageRunButton'); complete()
report = controller._report
assert report['source']['source_kind'] == 'ECONOMIC_THRESHOLD_SELECTION'
assert report['source']['source_selection']['candidate_index'] == 1 and report['status'] == 'AVAILABLE'
training = next(stage for stage in report['stages'] if stage['stage_kind'] == 'OUTER_MODEL_TRAINING')
assert training['usage'] == 'ACTUAL' and training['fit_origin'] == 'REUSED_FIXED_SOURCE_MODEL' and not training['recorded_fit_executed']
economic = next(stage for stage in report['stages'] if stage['stage_kind'] == 'INNER_ECONOMIC_HOLDOUT')
assert economic['label_usage'] == 'NOT_USED_BY_OBJECTIVE'
assert economic['recorded_price_slot_count'] == economic['actual_used_price_slot_count'] > 0
assert economic['price_support_counts']['comparison_status_counts']['DIFFERENT'] > 0
assert all(value['different_links'] == 0 for value in economic['price_support_counts']['field_comparison_counts'].values())
choose('intradaySampleUsageView', 3); choose('intradaySampleUsageStage', economic['stage_index'])
choose('intradaySampleUsageBarScope', 1)
assert controller.tableModel.totalRows == economic['recorded_price_slot_count']
assert [row['bar_index'] for row in page_evidence()['rows']] == economic['price_row_refs'][:100]
assert page_evidence()['stage']['label_usage'] == 'NOT_USED_BY_OBJECTIVE'

# Both real compact languages retain a scroll route, pageable rows and details.
before_calls = len(calls)
choose('intradaySampleUsageView', 2); choose('intradaySampleUsageStage', training['stage_index'])
window.setWidth(1024); window.setHeight(600); QTest.qWait(100)
for language in ('en', 'zh-CN'):
    assert session.i18n.setLanguage(language)
    assert controller.tableModel.totalRows == training['recorded_sample_count']
    scroll = find('intradaySampleUsageScroll'); flick = scroll.property('contentItem')
    assert flick.property('contentHeight') > scroll.property('availableHeight')
    bar = find('intradaySampleUsageScrollBar'); thumb = bar.property('contentItem')
    start = thumb.mapToScene(thumb.boundingRect().center()).toPoint()
    end = bar.mapToScene(QPointF(bar.width() / 2, bar.height() - 2)).toPoint()
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(window, end, 50); QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end); QTest.qWait(50)
    assert flick.property('contentY') > 0
    pagination = nested(find('intradaySampleUsageTable'), 'PixelPagination')
    glyph = 'next' if controller.tableModel.page == 1 else 'previous'
    button = next(item for item in pagination.findChildren(QObject) if item.property('glyph') == glyph)
    click_obj(button)
    page = controller.tableModel.page
    expected = training['sample_refs'][(page - 1) * 100:page * 100]
    assert [row['sample_ref'] for row in page_evidence()['rows']] == expected
    table = next(item for item in find('intradaySampleUsageTable').findChildren(QObject)
                 if item.metaObject().className() == 'QQuickTableView')
    horizontal = next(item for item in table.findChildren(QObject)
                      if 'PixelScrollBar' in item.metaObject().className() and item.property('orientation') == Qt.Horizontal)
    assert table.property('contentWidth') > table.property('width') and horizontal.property('visible')
    thumb = horizontal.property('contentItem')
    start = thumb.mapToScene(thumb.boundingRect().center()).toPoint()
    end = horizontal.mapToScene(QPointF(horizontal.width() - 2, horizontal.height() / 2)).toPoint()
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(window, end, 50); QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end); QTest.qWait(50)
    assert table.property('contentX') > 0
    # Return to the leading columns for the compact QA capture.
    table.setProperty('contentX', 0); QTest.qWait(50)
    assert window.grabWindow().save(str(root / ('q48-native-compact-' + language + '.png')))
    assert 'undefined' not in find('intradaySampleUsageSummary').property('text')
    assert 'undefined' not in find('intradaySampleUsageStageSummary').property('text')
assert len(calls) == before_calls
window.setWidth(1280); window.setHeight(1100); QTest.qWait(50)
open_source(paths['unavailable']); click('intradaySampleUsageRunButton'); complete()
unavailable = controller._report
assert unavailable['status'] == 'DECLARED_ONLY' and unavailable['source']['study_status'] == 'UNAVAILABLE'
assert unavailable['stages'] and all(stage['actual_used_count'] == stage['actual_used_price_slot_count'] == 0 for stage in unavailable['stages'])
assert controller.resultLoaded and not controller.studyError and not controller.draftChanged
choose('intradaySampleUsageView', 1)
assert page_evidence()['rows'] == unavailable['stages'][:100]
assert all(path.read_bytes() == content for path, content in original.items())
assert context.backend_if_initialized is None
assert not any('IntradaySampleUsagePanel' in warning or 'IntradayWorkspacePanel' in warning for warning in warnings), warnings
(root / 'q48-native-warnings.json').write_text(json.dumps(warnings, ensure_ascii=False, indent=2))
patch.undo(); assert session.shutdown(); engine.deleteLater(); app.processEvents()
print('NATIVE_SAMPLE_USAGE_PASS', flush=True)
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(data.path)], cwd=ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software",
             "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT / "tests")))},
        text=True, capture_output=True, timeout=360)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NATIVE_SAMPLE_USAGE_PASS" in result.stdout
