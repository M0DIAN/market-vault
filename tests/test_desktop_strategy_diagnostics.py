"""Complete diagnostic presentation, immutable bundle selection and real QML transport."""

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytest.importorskip("PySide6")

from market_vault.desktop import quant_research as quant
from market_vault.research import strategy_experiment as artifacts
from test_desktop_quant_research import _runtime, qt_app  # noqa: F401
from test_strategy_comparison import verified_workspace_dataset  # noqa: F401
from test_strategy_diagnostics import diagnostic_case  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]


def test_controller_selects_every_candidate_without_replacing_bundle_or_restoring_draft(
    qt_app, diagnostic_case, tmp_path, monkeypatch,
):
    dataset, plan, report, snapshot = diagnostic_case
    view = quant._experiment_payload_view(snapshot)
    runtime, runner = _runtime(tmp_path, [])
    controller = quant.QuantResearchController(runtime)
    values = {"comparison": plan["comparison_plan"], "strategy_name": "ridge",
              "parameter_axes": [{"parameter": "alpha", "values": "0.1,1"},
                                 {"parameter": "threshold", "values": "-1000000,0,1000000"}],
              "cost_scenarios": "0/0,10/5"}
    assert controller.runStrategyDiagnostics(values) is False
    local = tmp_path / "verified"
    local.mkdir()
    monkeypatch.setattr(quant, "_inspect_dataset", lambda path: quant._DatasetView(
        str(dataset.build_path), {"dataset_id": dataset.dataset_id}, tuple(plan["comparison_plan"]["feature_fields"]),
        (plan["comparison_plan"]["return_label"],), (plan["comparison_plan"]["return_label"],)))
    assert controller.inspectDataset(str(local))
    runtime._poll()
    calls = []

    def run(path, *, plan):
        calls.append((path, plan))
        return view

    monkeypatch.setattr(quant, "_run_strategy_diagnostics", run)
    assert controller.runStrategyDiagnostics(values)
    runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    assert calls == [(Path(dataset.build_path), plan)]
    assert controller.comparisonDiagnosticsModel.rowCount() == 12
    assert len(controller.comparisonDiagnosticCandidates) == 12
    assert controller.comparisonRestoreRevision == 0
    for index in range(12):
        assert controller.selectStrategyDiagnostic(index)
        group, variant = divmod(index, 6)
        assert controller.comparisonSummary["risk_report_id"] == report["groups"][group]["report"]["risk"]["risk_report_id"]
        assert controller.comparisonEquityIndex == variant
        assert controller.comparisonFoldModel.totalRows == len(report["groups"][group]["report"]["folds"])
        assert controller._comparison_experiment == snapshot.content
        assert controller.comparisonRestoreRevision == 0
    assert controller.selectComparisonEquity(2)
    assert controller.comparisonDiagnosticIndex == 8
    assert controller.selectComparisonEquity(6)  # Benchmark has no signal-fold attribution.
    assert controller.comparisonDiagnosticIndex == 8
    assert not controller.selectStrategyDiagnostic(12)
    assert controller.selectStrategyDiagnostic(11)
    detached = controller.comparisonDiagnosticsPlan
    detached["parameter_axes"][0]["values"][0] = 999
    assert controller.comparisonDiagnosticsPlan == plan
    archive = tmp_path / "all-candidates.json"
    assert controller.saveComparisonExperiment(str(archive))
    runtime._poll()
    assert archive.read_bytes() == snapshot.content
    assert controller.comparisonDiagnosticIndex == 11
    malformed = {**values, "parameter_axes": [{"parameter": "alpha", "values": ","}]}
    names = list(runner.names)
    assert controller.runStrategyDiagnostics(malformed) is False
    assert controller.status == "VALIDATION_ERROR" and runner.names == names
    assert controller.comparisonDiagnosticIndex == 11 and controller._comparison_experiment == snapshot.content
    assert controller.openComparisonExperiment(str(archive))
    runtime._poll()
    assert controller.status == "SUCCESS" and not controller.datasetLoaded
    assert controller.comparisonDiagnosticIndex == 0 and controller.comparisonRestoreRevision == 1
    assert controller.comparisonExperimentPlan == plan["comparison_plan"]
    assert controller.comparisonDiagnosticsPlan == plan
    replayed = []

    def replay(value, **kwargs):
        replayed.append(value.content)
        return {"actual_report_sha256": "a" * 64}

    monkeypatch.setattr(artifacts, "replay_strategy_experiment", replay)
    assert controller.replayComparisonExperiment("")
    runtime._poll()
    assert replayed == [snapshot.content]
    info = controller.comparisonExperimentInfo
    assert info["replay_verified"]
    assert controller.selectStrategyDiagnostic(11)
    assert controller.comparisonExperimentInfo == info
    assert controller.comparisonRestoreRevision == 1
    # Ordinary V1 results clear only the diagnostic presentation; the common
    # artifact path is still governed by the existing Save/Open/Replay workflow.
    controller._apply_comparison_view(quant._comparison_payload_view(report["groups"][0]["report"]))
    assert controller.comparisonDiagnosticCandidates == [] and controller.comparisonDiagnosticsPlan == {}
    assert controller.comparisonDiagnosticsModel.rowCount() == controller.comparisonFoldModel.rowCount() == 0
    assert runtime.backend_if_initialized is None and runtime.shutdown()


def test_worker_uses_existing_risk_authority_and_retains_the_complete_snapshot(diagnostic_case, monkeypatch):
    dataset, plan, report, _ = diagnostic_case
    monkeypatch.setattr(quant, "_load_verified_dataset", lambda path: dataset)
    view = quant._run_strategy_diagnostics(Path(dataset.build_path), plan=plan)
    snapshot = artifacts.StrategyExperiment(view.experiment)
    assert snapshot.as_dict()["report"] == report
    assert view.diagnostics.page.total_rows == 12
    assert all(not child.experiment for child in view.diagnostics.groups)


def test_fold_pagination_preserves_full_rows_and_candidate_selection(qt_app, diagnostic_case, tmp_path):
    view = quant._experiment_payload_view(diagnostic_case[3])
    original = view.diagnostics.fold_rows[0][0]
    rows = tuple((str(index + 1), *original[1:]) for index in range(1001))
    presentation = replace(view, diagnostics=replace(view.diagnostics, fold_rows=(rows,) + view.diagnostics.fold_rows[1:]))
    runtime, _ = _runtime(tmp_path, [])
    controller = quant.QuantResearchController(runtime)
    controller._apply_comparison_view(presentation)
    assert controller.comparisonFoldModel.totalRows == 1001
    assert controller.comparisonFoldModel.rowCount() == 100
    for _ in range(10):
        assert controller.changeComparisonFoldPage(1)
    assert controller.comparisonFoldModel.rowCount() == 1
    assert controller.comparisonFoldModel.data(controller.comparisonFoldModel.index(0, 0)) == "1001"
    assert not controller.changeComparisonFoldPage(1)
    assert controller._comparison_experiment == view.experiment
    assert controller.selectStrategyDiagnostic(1)
    assert controller.comparisonFoldModel.page == 1
    assert runtime.shutdown()


def test_real_qml_restores_grid_selects_last_candidate_and_saves_whole_bundle(diagnostic_case, tmp_path):
    snapshot = diagnostic_case[3]
    archive = tmp_path / "diagnostic.json"
    artifacts.write_strategy_experiment(snapshot, path=archive)
    moved = tmp_path / "verified"
    moved.mkdir()
    (tmp_path / "settings.yaml").write_text("storage:\n  root_dir: ./data\n", encoding="utf-8")
    script = f'''
import json
import sys
from pathlib import Path
from PySide6.QtCore import QObject, QMetaObject, QUrl, Qt, QEvent, Q_ARG
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from market_vault.application import build_application_context
from market_vault.desktop.bootstrap import create_qml_application_session
from market_vault.desktop.preferences import DesktopPreferenceStore
from market_vault.desktop import quant_research as quant
from market_vault.research import strategy_experiment as artifacts
sys.path.insert(0, {str(ROOT / "tests")!r})
from test_desktop_quant_research import _Runner
root_path = Path({str(tmp_path)!r})
snapshot = artifacts.load_strategy_experiment(Path({str(archive)!r}))
saved = snapshot.as_dict()
base = saved['plan']['comparison_plan']
backend_calls = []
context = build_application_context(root_path / 'settings.yaml', backend_factory=lambda value: backend_calls.append(value),
                                    runner_factory=lambda: _Runner())
QQuickStyle.setStyle('Basic')
app = QGuiApplication([])
engine = QQmlApplicationEngine()
session = create_qml_application_session(context, engine,
    preference_store=DesktopPreferenceStore(root=root_path / 'preferences'))
engine.load(QUrl.fromLocalFile({str(ROOT / "src/market_vault/desktop/qml/Main.qml")!r}))
assert engine.rootObjects()
window = engine.rootObjects()[0]
window.setWidth(1100)
window.setHeight(700)
controller = session.context_properties['quantResearchController']
session.shell.selectPage('quant_research')

def item(name):
    found = window.findChild(QObject, name)
    if found is not None: return found
    pending = [window.contentItem()]
    while pending:
        value = pending.pop()
        if value.objectName() == name: return value
        pending.extend(value.childItems())
    raise AssertionError(name)

def click(name):
    assert item(name).property('enabled'), name
    assert QMetaObject.invokeMethod(item(name), 'clicked', Qt.DirectConnection)
    app.processEvents()

def choose_file(name, path):
    dialog = item(name)
    assert dialog.setProperty('selectedFile', QUrl.fromLocalFile(str(path)))
    assert QMetaObject.invokeMethod(dialog, 'accepted', Qt.DirectConnection)
    QMetaObject.invokeMethod(dialog, 'close', Qt.DirectConnection)
    session.runtime._poll()
    app.processEvents()
    QTest.qWait(30)

def type_text(name, text):
    window.requestActivate()
    QTest.qWait(10)
    control = item(name)
    control = next((c for c in control.children() if 'PixelTextField' in c.metaObject().className()), control)
    control.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
    for character in text:
        QGuiApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, ord(character.upper()), Qt.NoModifier, character))
    app.processEvents()
    assert control.property('text') == text, (name, control.property('text'))

def select(name, index):
    control = item(name)
    control = next((c for c in control.children() if 'PixelComboBox' in c.metaObject().className()), control)
    assert control.setProperty('currentIndex', index)
    assert QMetaObject.invokeMethod(control, 'activated', Qt.DirectConnection, Q_ARG(int, index))
    app.processEvents()

def forbidden(*a, **k):
    raise AssertionError('Offline Open/Save must not read Dataset or calculate')

quant._load_verified_dataset = forbidden
click('quantComparisonTab')
click('quantExperimentOpenButton')
choose_file('quantExperimentOpenDialog', Path({str(archive)!r}))
assert controller.status == 'SUCCESS', controller.error
panel = item('quantStrategyComparisonPanel')
assert panel.property('resultsView') == 3
assert item('quantDiagnosticsTable').property('visible')
assert window.grabWindow().save(str(root_path / 'diagnostic-initial-ui.png'))
assert item('quantDiagnosticsTable').property('height') >= 100, item('quantDiagnosticsTable').property('height')
assert not item('quantOpenDiagnosticsButton').property('enabled')
assert controller.comparisonDiagnosticsModel.rowCount() == 12
assert item('quantComparisonRiskToggle').property('checked')
select('quantDiagnosticCandidate', 11)
assert controller.comparisonDiagnosticIndex == 11 and controller.comparisonEquityIndex == 5
assert '1000000' in item('quantDiagnosticCandidate').property('currentText')
assert '10.0/5.0' in item('quantDiagnosticCandidate').property('currentText')
click('quantDiagnosticsFoldsButton')
assert item('quantDiagnosticsFoldTable').property('visible')
assert controller.comparisonFoldModel.totalRows == len(saved['report']['groups'][1]['candidates'][5]['fold_contributions'])
click('quantComparisonLedgerButton')
assert controller.comparisonEquityModel.rowCount() == 100
assert controller.changeComparisonEquityPage(1)
assert controller.comparisonEquityModel.page == 2
click('quantComparisonInputsButton')
type_text('quantComparisonCommission', '7')
select('quantDiagnosticCandidate', 10)
assert item('quantComparisonCommission').property('text') == '7'
output = root_path / 'saved-all.json'
click('quantExperimentSaveButton')
choose_file('quantExperimentSaveDialog', output)
assert output.read_bytes() == snapshot.content
assert controller.comparisonRestoreRevision == 1
assert item('quantComparisonCommission').property('text') == '7'
replayed = []
def replay(value, **kwargs):
    replayed.append(value.content)
    return {{'actual_report_sha256': 'a' * 64}}
artifacts.replay_strategy_experiment = replay
click('quantExperimentReplayButton')
session.runtime._poll()
app.processEvents()
assert replayed == [snapshot.content] and controller.comparisonExperimentInfo['replay_verified']
select('quantDiagnosticCandidate', 11)
assert controller.comparisonExperimentInfo['replay_verified']
quant._inspect_dataset = lambda path: quant._DatasetView(base['dataset_build_dir'],
    {{'dataset_id': saved['dataset_id']}}, tuple(base['feature_fields']), (base['return_label'],), (base['return_label'],))
assert controller.inspectDataset({str(moved)!r})
session.runtime._poll()
app.processEvents()
assert item('quantComparisonCommission').property('text') == '7'
click('quantOpenDiagnosticsButton')
dialog = item('quantDiagnosticsDialog')
assert dialog.property('visible')
assert item('quantDiagnosticsStrategy').property('currentText') == 'ridge'
assert item('quantDiagnosticsFirstAxis').property('currentText') == 'alpha'
assert item('quantDiagnosticsSecondAxis').property('currentText') == 'threshold'
assert item('quantDiagnosticsFirstValues').property('text') == '0.1,1'
assert item('quantDiagnosticsSecondValues').property('text') == '-1000000,0,1000000'
assert item('quantDiagnosticsCosts').property('text') == '0/0,10/5'
assert dialog.property('evaluationCount') == 12
type_text('quantDiagnosticsFirstValues', '0.2,2')
type_text('quantDiagnosticsCosts', '0/0,20/5')
assert session.i18n.setLanguage('zh-CN')
app.processEvents()
assert item('quantDiagnosticsFirstAxis').property('currentText') == 'alpha'
assert item('quantDiagnosticsFirstValues').property('text') == '0.2,2'
assert window.grabWindow().save(str(root_path / 'diagnostic-grid-ui.png'))
click('quantDiagnosticsCancelButton')
click('quantOpenDiagnosticsButton')
assert item('quantDiagnosticsFirstValues').property('text') == '0.2,2'
captured = []
def fail(path, *, plan):
    captured.append(plan)
    raise ValueError('deliberate worker failure after capturing actual QML values')
quant._run_strategy_diagnostics = fail
click('quantDiagnosticsRunButton')
session.runtime._poll()
app.processEvents()
assert controller.status == 'FAILED'
assert captured[0]['strategy_name'] == 'ridge'
assert captured[0]['parameter_axes'] == [{{'parameter': 'alpha', 'values': [0.2, 2.0]}},
    {{'parameter': 'threshold', 'values': [-1000000.0, 0.0, 1000000.0]}}]
assert captured[0]['cost_scenarios'][1] == {{'commission_bps': 20.0, 'slippage_bps': 5.0}}
assert captured[0]['comparison_plan']['commission_bps'] == 7.0
assert controller._comparison_experiment == snapshot.content and controller.comparisonDiagnosticIndex == 11
click('quantOpenDiagnosticsButton')
type_text('quantDiagnosticsFirstValues', ',')
click('quantDiagnosticsRunButton')
assert controller.status == 'VALIDATION_ERROR'
assert dialog.property('visible') and len(captured) == 1
type_text('quantDiagnosticsFirstValues', ','.join(str(index + 1) for index in range(33)))
assert dialog.property('evaluationCount') == 198
assert not item('quantDiagnosticsRunButton').property('enabled')
select('quantDiagnosticsFirstAxis', 0)
select('quantDiagnosticsSecondAxis', 0)
assert dialog.property('evaluationCount') == 2
assert not item('quantDiagnosticsFirstValues').property('enabled')
click('quantDiagnosticsRunButton')
session.runtime._poll()
app.processEvents()
assert captured[1]['parameter_axes'] == []
assert controller._comparison_experiment == snapshot.content
click('quantOpenDiagnosticsButton')
select('quantDiagnosticsStrategy', 3)
select('quantDiagnosticsSecondAxis', 2)
type_text('quantDiagnosticsFirstValues', '-1000000,1000000')
type_text('quantDiagnosticsSecondValues', '-1000000,1000000')
type_text('quantDiagnosticsCosts', '5/2,2/5')
assert dialog.property('evaluationCount') == 8
click('quantDiagnosticsRunButton')
session.runtime._poll()
app.processEvents()
assert captured[2]['strategy_name'] == base['strategies'][3]['name']
assert captured[2]['parameter_axes'] == [{{'parameter': 'condition_threshold', 'condition_index': index,
    'values': [-1000000.0, 1000000.0]}} for index in range(2)]
assert controller._comparison_experiment == snapshot.content and controller.comparisonDiagnosticIndex == 11
click('quantOpenDiagnosticsButton')
click('quantDiagnosticsCancelButton')
click('quantDiagnosticsResultsButton')
app.processEvents()
assert window.grabWindow().save(str(root_path / 'diagnostic-results-ui.png'))
click('quantDiagnosticsFoldsButton')
app.processEvents()
assert window.grabWindow().save(str(root_path / 'diagnostic-folds-ui.png'))
click('quantExperimentOpenButton')
choose_file('quantExperimentOpenDialog', Path({str(archive)!r}))
assert controller.comparisonRestoreRevision == 2 and not controller.datasetLoaded
assert float(item('quantComparisonCommission').property('text')) == base['commission_bps']
assert controller.comparisonDiagnosticIndex == 0
assert controller.inspectDataset({str(moved)!r})
session.runtime._poll()
app.processEvents()
click('quantOpenDiagnosticsButton')
assert item('quantDiagnosticsStrategy').property('currentText') == 'ridge'
assert item('quantDiagnosticsFirstAxis').property('currentText') == 'alpha'
assert item('quantDiagnosticsFirstValues').property('text') == '0.1,1'
assert item('quantDiagnosticsCosts').property('text') == '0/0,10/5'
click('quantDiagnosticsCancelButton')
assert backend_calls == [] and session.runtime.backend_if_initialized is None
assert session.shutdown()
print(json.dumps({{'diagnostics_transport': True}}))
'''
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QSG_RHI_BACKEND": "software", "PYTHONPATH": str(ROOT / "src")}
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=50, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["diagnostics_transport"]
    assert "ReferenceError" not in result.stderr and "TypeError" not in result.stderr
