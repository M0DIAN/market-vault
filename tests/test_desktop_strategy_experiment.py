"""Offline snapshot state and real QML Save/Open/Replay transport."""

from __future__ import annotations

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
from test_strategy_experiment import experiment_snapshots, resign  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]


def test_snapshot_controller_keeps_completed_results_through_failures_and_relocation(
    qt_app, experiment_snapshots, tmp_path, monkeypatch,
):
    snapshot = experiment_snapshots["RISK"]
    root = snapshot.as_dict()
    original_dir = tmp_path / "original-dataset"
    original_dir.mkdir()
    root["plan"]["dataset_build_dir"] = str(original_dir)
    snapshot = artifacts.StrategyExperiment(resign(root))
    runtime, runner = _runtime(tmp_path, [])
    controller = quant.QuantResearchController(runtime)
    assert controller.saveComparisonExperiment(str(tmp_path / "early.json")) is False
    relocated = tmp_path / "relocated"
    relocated.mkdir()
    other = tmp_path / "other"
    other.mkdir()

    def inspect(path):
        return quant._DatasetView(str(path), {"dataset_id": root["dataset_id"] if path != other else "a" * 64},
                                  tuple(root["plan"]["feature_fields"]), (root["plan"]["return_label"],),
                                  (root["plan"]["return_label"],))

    monkeypatch.setattr(quant, "_inspect_dataset", inspect)
    monkeypatch.setattr(quant, "_run_strategy_comparison", lambda *a, **k:
                        quant._comparison_payload_view(root["report"], experiment=snapshot.content))
    assert controller.inspectDataset(str(original_dir))
    runtime._poll()
    assert controller.runStrategyComparison({**root["plan"], "risk_report": True})
    runtime._poll()
    assert controller.comparisonExperimentInfo["experiment_id"] == snapshot.experiment_id
    detached = controller.comparisonExperimentPlan
    detached["strategies"][0]["threshold"] = 999
    assert controller.comparisonExperimentPlan["strategies"][0]["threshold"] == 0
    archive = tmp_path / "saved.json"
    assert controller.saveComparisonExperiment(archive.as_uri())
    runtime._poll()
    assert archive.read_bytes() == snapshot.content
    assert controller.inspectDataset(str(other))
    runtime._poll()
    assert controller.datasetLoaded and controller.datasetSummary["dataset_id"] == "a" * 64
    assert controller.openComparisonExperiment(archive.as_uri())
    runtime._poll()
    assert not controller.datasetLoaded and controller.datasetPath == "" and controller.featureNames == []
    assert controller.comparisonSummary["comparison_id"] == root["report"]["comparison_id"]
    assert controller.comparisonRestoreRevision == 1
    assert controller.runStrategyComparison(root["plan"]) is False
    assert controller.selectComparisonEquity(2)
    summary = controller.comparisonSummary
    assert controller.inspectDataset(str(relocated))
    runtime._poll()
    assert controller.datasetLoaded and controller.datasetPath == str(relocated)
    assert controller.comparisonSummary == summary and controller.comparisonEquityIndex == 2
    assert controller.comparisonRestoreRevision == 1
    assert controller.comparisonExperimentPlan["dataset_build_dir"] == str(original_dir)
    corrupt = tmp_path / "bad.json"
    broken = snapshot.as_dict()
    broken["report"]["equity"]["results"][0]["points"][101]["timestamp"] = "invalid"
    corrupt.write_bytes(resign(broken))
    assert controller.openComparisonExperiment(str(corrupt))
    runtime._poll()
    assert controller.status == "FAILED"
    assert controller.comparisonSummary == summary and controller.comparisonEquityIndex == 2
    assert controller.comparisonRestoreRevision == 1
    assert controller.saveComparisonExperiment(str(corrupt))
    runtime._poll()
    assert controller.status == "FAILED" and corrupt.read_bytes() == resign(broken)

    def fail(*a, **k):
        raise ValueError("deliberate computation or inspection failure")

    monkeypatch.setattr(quant, "_run_strategy_comparison", fail)
    assert controller.runStrategyComparison({**root["plan"], "risk_report": True})
    runtime._poll()
    assert controller.status == "FAILED" and controller.comparisonSummary == summary
    monkeypatch.setattr(quant, "_inspect_dataset", fail)
    assert controller.inspectDataset(str(other))
    runtime._poll()
    assert controller.status == "FAILED" and controller.datasetPath == str(relocated)
    monkeypatch.setattr(artifacts, "replay_strategy_experiment", fail)
    assert controller.replayComparisonExperiment(str(relocated))
    runtime._poll()
    assert controller.status == "FAILED"
    assert controller.comparisonSummary == summary and controller.comparisonEquityIndex == 2
    assert controller.comparisonRestoreRevision == 1
    assert controller._comparison_experiment == snapshot.content
    assert runtime.backend_if_initialized is None
    assert runtime.shutdown()


def test_real_qml_open_restore_edit_save_and_replay_are_separate(experiment_snapshots, tmp_path):
    risk = experiment_snapshots["RISK"].as_dict()
    risk["plan"]["dataset_build_dir"] = str(tmp_path / "absent-dataset")
    snapshot = artifacts.StrategyExperiment(resign(risk))
    archive = tmp_path / "archived.json"
    artifacts.write_strategy_experiment(snapshot, path=archive)
    comparison = tmp_path / "comparison.json"
    artifacts.write_strategy_experiment(experiment_snapshots["COMPARISON"], path=comparison)
    moved = tmp_path / "relocated"
    moved.mkdir()
    (tmp_path / "settings.yaml").write_text("storage:\n  root_dir: ./data\n", encoding="utf-8")
    script = f'''
import json
import sys
from pathlib import Path
from hashlib import sha256
from PySide6.QtCore import QObject, QMetaObject, QUrl, Qt, QEvent
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
archive = Path({str(archive)!r})
saved = artifacts.load_strategy_experiment(archive)
expected = saved.as_dict()
backend_calls = []
context = build_application_context(root_path / 'settings.yaml',
    backend_factory=lambda value: backend_calls.append(value), runner_factory=lambda: _Runner())
QQuickStyle.setStyle('Basic')
app = QGuiApplication([])
engine = QQmlApplicationEngine()
session = create_qml_application_session(context, engine,
    preference_store=DesktopPreferenceStore(root=root_path / 'preferences'))
engine.load(QUrl.fromLocalFile({str(ROOT / "src/market_vault/desktop/qml/Main.qml")!r}))
assert engine.rootObjects()
window = engine.rootObjects()[0]
controller = session.context_properties['quantResearchController']
session.shell.selectPage('quant_research')
assert QMetaObject.invokeMethod(window.findChild(QObject, 'quantComparisonTab'), 'clicked', Qt.DirectConnection)
app.processEvents()
panel = window.findChild(QObject, 'quantStrategyComparisonPanel')

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
    QTest.qWait(20)
    control = item(name)
    control = next((c for c in control.children() if 'PixelTextField' in c.metaObject().className()), control)
    control.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
    for character in text:
        QGuiApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, ord(character.upper()), Qt.NoModifier, character))
    app.processEvents()
    assert control.property('text') == text, (name, control.property('text'), text, control.property('activeFocus'))

def forbidden(*a, **k):
    raise AssertionError('Open/Save must not load Dataset or compute')

quant._load_verified_dataset = forbidden
artifacts.evaluate_comparison_payload = forbidden
assert item('quantExperimentOpenButton').property('enabled')
assert not item('quantExperimentSaveButton').property('enabled')
click('quantExperimentOpenButton')
choose_file('quantExperimentOpenDialog', archive)
assert controller.status == 'SUCCESS', controller.error
assert not controller.datasetLoaded and not item('quantRunComparisonButton').property('enabled')
assert controller.comparisonRestoreRevision == 1
assert controller.comparisonRiskModel.rowCount() == 5
assert controller.comparisonEquityModel.rowCount() == 100
assert item('quantComparisonFeatures').property('text') == ','.join(expected['plan']['feature_fields'])
assert item('quantComparisonReturnLabel').property('currentText') == expected['plan']['return_label']
assert item('quantComparisonCommission').property('text') == '10'
assert item('quantComparisonSlippage').property('text') == '5'
assert item('quantComparisonRiskToggle').property('checked')
editor = item('quantStrategyListEditor')
engine.globalObject().setProperty('editor', engine.newQObject(editor))
result = engine.evaluate('editor.select(3)')
assert not result.isError()
assert item('quantStrategyMatch').property('currentIndex') == 1
engine.evaluate('editor.select(0)')
click('quantComparisonInputsButton')
QTest.qWait(30)
type_text('quantConditionThreshold0', '2.5')
type_text('quantComparisonFeatures', ','.join(reversed(expected['plan']['feature_fields'])))
controller.selectComparisonEquity(2)
app.processEvents()
assert item('quantConditionThreshold0').property('text') == '2.5'
quant._inspect_dataset = lambda path: quant._DatasetView(str(path), {{'dataset_id': expected['dataset_id']}},
    ('unused',) + tuple(expected['plan']['feature_fields']),
    ('another_label', expected['plan']['return_label']), ('another_label', expected['plan']['return_label']))
assert controller.inspectDataset({str(moved)!r})
session.runtime._poll()
app.processEvents()
assert controller.datasetLoaded
assert controller.comparisonRestoreRevision == 1
assert item('quantConditionThreshold0').property('text') == '2.5'
assert item('quantComparisonReturnLabel').property('currentText') == expected['plan']['return_label']
assert item('quantComparisonReturnLabel').property('currentIndex') == 1
assert item('quantComparisonFeatures').property('text') == ','.join(reversed(expected['plan']['feature_fields']))
output = root_path / 'saved-copy.json'
click('quantExperimentSaveButton')
choose_file('quantExperimentSaveDialog', output)
assert controller.status == 'SUCCESS', controller.error
assert output.read_bytes() == archive.read_bytes()
assert item('quantConditionThreshold0').property('text') == '2.5'
assert controller.comparisonRestoreRevision == 1
replayed = []
def replay(snapshot, *, dataset_build_dir=None):
    replayed.append((snapshot.content, dataset_build_dir))
    return {{'actual_report_sha256': sha256(artifacts.canonical_json(snapshot.as_dict()['report'])).hexdigest()}}
artifacts.replay_strategy_experiment = replay
click('quantExperimentReplayButton')
session.runtime._poll()
app.processEvents()
assert replayed == [(saved.content, None)]
assert controller.comparisonExperimentInfo['replay_verified']
assert item('quantConditionThreshold0').property('text') == '2.5'
click('quantExperimentRelocateButton')
dialog = item('quantExperimentReplayDatasetDialog')
assert dialog.setProperty('selectedFolder', QUrl.fromLocalFile({str(moved)!r}))
assert QMetaObject.invokeMethod(dialog, 'accepted', Qt.DirectConnection)
QMetaObject.invokeMethod(dialog, 'close', Qt.DirectConnection)
session.runtime._poll()
app.processEvents()
assert replayed[-1] == (saved.content, Path({str(moved)!r}))
assert controller.comparisonExperimentPlan['dataset_build_dir'] == expected['plan']['dataset_build_dir']
assert controller.comparisonRestoreRevision == 1
assert session.i18n.setLanguage('zh-CN')
app.processEvents()
assert window.grabWindow().save(str(root_path / 'experiment-editor-ui.png'))
click('quantExperimentOpenButton')
choose_file('quantExperimentOpenDialog', archive)
assert controller.comparisonRestoreRevision == 2
assert not controller.datasetLoaded
assert item('quantConditionThreshold0').property('text') == '0'
assert item('quantComparisonFeatures').property('text') == ','.join(expected['plan']['feature_fields'])
click('quantComparisonRiskButton')
app.processEvents()
assert window.grabWindow().save(str(root_path / 'experiment-risk-ui.png'))
click('quantExperimentOpenButton')
choose_file('quantExperimentOpenDialog', Path({str(comparison)!r}))
assert controller.comparisonRestoreRevision == 3
assert not item('quantComparisonRiskToggle').property('checked')
assert not item('quantComparisonEquityToggle').property('checked')
assert controller.comparisonRiskModel.rowCount() == 0
assert controller.comparisonBenchmarkSeries == [] and controller.comparisonEquityNames == []
assert panel.property('resultsView') == 0
assert backend_calls == [] and session.runtime.backend_if_initialized is None
assert session.shutdown()
print(json.dumps({{'snapshot_workflow': True}}))
'''
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QSG_RHI_BACKEND": "software", "PYTHONPATH": str(ROOT / "src")}
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=40, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["snapshot_workflow"]
    assert "ReferenceError" not in result.stderr
    assert "TypeError" not in result.stderr
