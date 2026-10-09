"""Real controller and visible QML freeze / final TEST / replay workflows."""

from concurrent.futures import Future
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytest.importorskip("PySide6")

from market_vault.desktop.quant_research import QuantResearchController
from market_vault.research import intraday_final_test as final
from market_vault.research import intraday_research as research
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.strategy_experiment import StrategyExperiment, canonical_json, write_strategy_experiment
from test_desktop_quant_research import _runtime, qt_app  # noqa: F401
from test_intraday_experiment import intraday_experiment, parameter_grid_experiment, signed  # noqa: F401
from test_intraday_final_test import final_case, selection_case  # noqa: F401
from test_intraday_research import diagnostic_plan, execution_scenarios_case, research_case, research_data  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]


def _intraday_plan_form(plan, *, bound=True):
    return {"data_id": plan["data_id"], "intraday_data_path": plan["intraday_data_path"],
        "execution_policy_bound": bound, "feature_fields": deepcopy(plan["feature_fields"]),
        "strategies": deepcopy(plan["strategies"]), **plan["split"], **plan["walk_forward"], **plan["execution"]}


def _intraday_plan_inputs(plan):
    if "comparison_plan" not in plan:
        return "comparison", _intraday_plan_form(plan)
    values = {"comparison": _intraday_plan_form(plan["comparison_plan"])}
    if "parameter_axes" in plan:
        return "diagnostics", {**values, **{key: deepcopy(plan[key]) for key in
            ("strategy_name", "parameter_axes", "cost_scenarios")}}
    return "scenarios", {**values, "execution_scenarios": deepcopy(plan["execution_scenarios"])}


def _intraday_scenarios_draft(comparison):
    from market_vault.research.intraday_execution_scenarios import INTRADAY_EXECUTION_SCENARIOS_PLAN_VERSION
    common = deepcopy(comparison)
    common["execution"].update(commission_bps=7.5, slippage_bps=2.25, max_hold_bars=4)
    return {"plan_schema_version": INTRADAY_EXECUTION_SCENARIOS_PLAN_VERSION, "comparison_plan": common,
        "execution_scenarios": [{"name": "Original", "execution": deepcopy(comparison["execution"])},
            {"name": "Later", "execution": {**comparison["execution"], "entry_delay_minutes": 60,
                "max_hold_bars": 3, "commission_bps": 10, "slippage_bps": 5}}]}


def test_plan_draft_controller_offline_capture_and_failure_retention(qt_app, parameter_grid_experiment,
        tmp_path, monkeypatch):
    from market_vault.research.intraday_plan import serialize_intraday_plan, load_intraday_plan, write_intraday_plan
    root = parameter_grid_experiment.as_dict()
    comparison, diagnostics = root["plan"]["comparison_plan"], root["plan"]
    plans = [comparison, diagnostics, _intraday_scenarios_draft(comparison)]
    runtime, runner = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    controller = owner.intradayResearchController
    controller._apply(parameter_grid_experiment, path=str(tmp_path / "result.json"), opened=True)
    result_before = (controller._content, controller._proof, controller.experimentPath, controller.restoreRevision)
    def forbidden(*args, **kwargs):
        pytest.fail("offline plan work loaded Q5, fitted or executed")
    for name in ("load_intraday_dataset", "_fit", "fit_ridge_rows", "run_intraday_execution"):
        monkeypatch.setattr(research, name, forbidden)
    assert not controller.dataLoaded and not controller.draftLoaded
    for index, plan in enumerate(plans):
        source = tmp_path / f"plan-{index}.json"
        write_intraday_plan(serialize_intraday_plan(plan), path=source)
        assert controller.loadPlan(str(source)); runtime._poll()
        assert controller.status == "SUCCESS", controller.error
        assert controller.draftPlan == load_intraday_plan(source)
        assert controller.draftRevision == index + 1 and controller.draftSource == {"kind": "FILE", "path": str(source)}
        kind, values = _intraday_plan_inputs(plan)
        common = values.get("comparison", values)
        common["commission_bps"] = "8.25"
        assert controller.preparePlanSave(kind, values)
        captured = controller._plan_save_pending["content"]
        common["commission_bps"] = "9.25"
        output = tmp_path / f"captured-{index}.json"
        assert controller.savePreparedPlan(str(output)); runtime._poll()
        assert controller.status == "SUCCESS", controller.error
        assert output.read_bytes() == captured and not controller.pendingPlanKind
        saved = load_intraday_plan(output)
        assert saved.get("comparison_plan", saved)["execution"]["commission_bps"] == 8.25
        if kind == "scenarios":
            assert saved["comparison_plan"]["execution"]["max_hold_bars"] == 4
            assert saved["execution_scenarios"] == plan["execution_scenarios"]
        if kind == "diagnostics":
            assert saved["cost_scenarios"] == plan["cost_scenarios"]
        common["commission_bps"] = "8.25"
        assert controller.preparePlanSave(kind, values) and controller.savePreparedPlan(str(output))
        runtime._poll()
        assert controller.status == "SUCCESS" and controller.planSaveReceipt["created_new_file"] is False
        common["commission_bps"] = "9.25"
        assert controller.preparePlanSave(kind, values) and controller.savePreparedPlan(str(output))
        runtime._poll()
        assert controller.status == "FAILED" and output.read_bytes() == captured
        assert controller.draftPlan == load_intraday_plan(source)
    draft_before = (controller.draftPlan, controller.draftSource, controller.draftRevision)
    bad = tmp_path / "bad.json"
    bad.write_text('{"not": "a plan"}')
    assert controller.loadPlan(str(bad)); runtime._poll()
    assert controller.status == "FAILED" and (controller.draftPlan, controller.draftSource, controller.draftRevision) == draft_before
    values = _intraday_plan_form(comparison)
    assert controller.preparePlanSave("comparison", values)
    controller.cancelPlanSave()
    assert not controller.pendingPlanKind and not controller.savePreparedPlan(str(tmp_path / "cancelled.json"))
    assert controller.preparePlanSave("comparison", values)
    assert not controller.preparePlanSave("comparison", {**values, "max_hold_bars": "invalid"})
    assert not controller.pendingPlanKind
    assert (controller._content, controller._proof, controller.experimentPath, controller.restoreRevision) == result_before
    assert (controller.draftPlan, controller.draftSource, controller.draftRevision) == draft_before
    # First-scenario fallback is only for missing costs in a valid initial form.
    _, scenarios = _intraday_plan_inputs(plans[2])
    scenarios["comparison"].update(execution_policy_bound=False, commission_bps="", slippage_bps="")
    assert controller.preparePlanSave("scenarios", scenarios)
    captured = json.loads(controller._plan_save_pending["content"])
    assert captured["comparison_plan"]["execution"] == plans[2]["execution_scenarios"][0]["execution"]
    for changes in ({"max_hold_bars": "not-an-int"}, {"entry_delay_minutes": -1},
                    {"commission_bps": "invalid"}, {"execution_policy_bound": True}):
        invalid = deepcopy(scenarios)
        invalid["comparison"].update(changes)
        assert not controller.preparePlanSave("scenarios", invalid) and not controller.pendingPlanKind
    assert runtime.backend_if_initialized is None and runtime.shutdown()


def test_continue_candidate_controller_captures_ids_and_requires_export(qt_app, parameter_grid_experiment,
        execution_scenarios_case, tmp_path, monkeypatch):
    from market_vault.research import intraday_plan as plans
    runtime, runner = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    controller = owner.intradayResearchController
    source = tmp_path / "grid.json"
    write_strategy_experiment(parameter_grid_experiment, path=source)
    controller._apply(parameter_grid_experiment, path=str(source), opened=True)
    assert controller.selectCandidate(7)
    captured_source = controller.selection_source()
    calls, extract = [], plans.extract_intraday_candidate_plan
    def recorded(path, **kwargs):
        calls.append((path, kwargs))
        return extract(path, **kwargs)
    monkeypatch.setattr(plans, "extract_intraday_candidate_plan", recorded)
    pending = []
    def deferred(name, operation):
        future = Future(); pending.append((future, operation)); return future
    with monkeypatch.context() as patch:
        patch.setattr(runner, "submit", deferred)
        assert controller.continueCandidate()
        assert controller.selectCandidate(0)
        pending[0][0].set_result(pending[0][1]()); runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    group = parameter_grid_experiment.as_dict()["report"]["groups"][1]
    assert controller.draftPlan["strategies"] == [group["results"][1]["strategy"]]
    assert controller.draftPlan["execution"] == group["execution_policy"]
    assert controller.draftSource["cost_index"] == controller.draftSource["candidate_index"] == 1
    assert calls[-1] == (str(source), {"cost_index": 1, "candidate_index": 1,
        "expected_experiment_id": captured_source["experiment_id"], "expected_candidate_id": captured_source["candidate_id"]})
    before = (controller.draftPlan, controller.draftRevision, controller._content, controller._proof)
    source.write_bytes(_named_saved_experiment(parameter_grid_experiment, "Changed source").content)
    assert controller.continueCandidate(); runtime._poll()
    assert controller.status == "FAILED" and (controller.draftPlan, controller.draftRevision, controller._content, controller._proof) == before
    collection = execution_scenarios_case[2]
    controller._apply(collection, path=str(tmp_path / "collection.json"), opened=True)
    assert not controller.canContinueCandidate and not controller.continueCandidate()
    assert controller.exportScenario(str(tmp_path / "child.json")); runtime._poll()
    assert controller.status == "SUCCESS" and controller.canContinueCandidate
    assert controller.selectCandidate(1) and controller.continueCandidate(); runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    assert len(controller.draftPlan["strategies"]) == 1
    assert controller.draftSource["path"] == str(tmp_path / "child.json")
    assert controller.collectionProof == controller._proof == "RECORDED"
    assert runtime.backend_if_initialized is None and runtime.shutdown()


def test_plan_run_admission_keeps_original_locator_and_projection(qt_app, parameter_grid_experiment,
        tmp_path, monkeypatch):
    runtime, _ = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    controller = owner.intradayResearchController
    comparison = parameter_grid_experiment.as_dict()["plan"]["comparison_plan"]
    values = _intraday_plan_form(comparison)
    admitted = []
    monkeypatch.setattr(controller, "_run", lambda plan: admitted.append(plan) or True)
    assert not controller.runComparison(values) and not admitted
    owner._intraday_data = b"opened source state"
    owner._intraday_path = str(tmp_path / "different-open-locator.json")
    controller._source_id = "0" * 64
    assert not controller.runComparison(values) and not admitted
    controller._source_id = comparison["data_id"]
    owner._intraday_feature_names = tuple(comparison["feature_fields"])
    assert controller.runComparison(values)
    assert admitted[-1]["intraday_data_path"] == comparison["intraday_data_path"]
    assert admitted[-1]["feature_fields"] == comparison["feature_fields"]
    assert not controller.runComparison({**values, "feature_fields": ["missing_feature"]})
    if os.name != "nt":
        portable = {**values, "intraday_data_path": r"C:\portable\original.json"}
        assert controller.preparePlanSave("comparison", portable)
        assert not controller.runComparison(portable) and "this host" in controller.error
        assert json.loads(controller._plan_save_pending["content"])["intraday_data_path"] == portable["intraday_data_path"]
    assert len(admitted) == 1 and runtime.backend_if_initialized is None and runtime.shutdown()


@pytest.fixture(scope="session")
def mismatched_plan_data(tmp_path_factory):
    """A different, real Q5 identity; no research or model fitting."""
    return research_data(tmp_path_factory.mktemp("plan-mismatched-data"), test_change=True)


def test_actual_qml_plan_drafts_capture_editors_and_keep_original_run_locator(parameter_grid_experiment,
        execution_scenarios_case, final_case, mismatched_plan_data, tmp_path):
    from market_vault.research.intraday_plan import serialize_intraday_plan, write_intraday_plan
    diagnostic = deepcopy(parameter_grid_experiment.as_dict()["plan"])
    diagnostic["parameter_axes"][0]["values"] = [130, 130.000000000001]
    diagnostic["cost_scenarios"] = [{"commission_bps": 1, "slippage_bps": 2}, {"commission_bps": 3, "slippage_bps": 4}]
    comparison = diagnostic["comparison_plan"]
    for name, plan in (("comparison", comparison), ("diagnostics", diagnostic),
                       ("scenarios", _intraday_scenarios_draft(comparison))):
        write_intraday_plan(serialize_intraday_plan(plan), path=tmp_path / (name + "-plan.json"))
    for name, snapshot in (("grid", parameter_grid_experiment), ("collection", execution_scenarios_case[2]),
                           ("test", final_case[1])):
        write_strategy_experiment(snapshot, path=tmp_path / (name + ".json"))
    original = Path(comparison["intraday_data_path"])
    assert original.is_file()
    alternate = tmp_path / "same-id-other-locator.json"
    alternate.write_bytes(original.read_bytes())
    (tmp_path / "settings.yaml").write_text("storage:\n  root_dir: ./data\n", encoding="utf-8")
    (tmp_path / "bad-plan.json").write_text('{"not": "a plan"}', encoding="utf-8")
    script = r'''
import hashlib, json, sys, time
from pathlib import Path
from PySide6.QtCore import QObject, QUrl, Qt, QEvent, QMetaObject
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from market_vault.application import build_application_context
from market_vault.desktop.bootstrap import create_qml_application_session
from market_vault.desktop.preferences import DesktopPreferenceStore
from market_vault.research import intraday_research as research, intraday_data
from market_vault.research.intraday_plan import load_intraday_plan, serialize_intraday_plan, write_intraday_plan
root, mismatch_path = Path(sys.argv[1]), Path(sys.argv[2])
sources = {name: root / (name + '.json') for name in ('grid', 'collection', 'test')}
before = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sources.items()}
diagnostic_plan = load_intraday_plan(root / 'diagnostics-plan.json')
original = diagnostic_plan['comparison_plan']['intraday_data_path']
original_digest = hashlib.sha256(Path(original).read_bytes()).hexdigest()
QQuickStyle.setStyle('Basic')
app = QGuiApplication([])
engine = QQmlApplicationEngine()
session = create_qml_application_session(build_application_context(root / 'settings.yaml'), engine,
    preference_store=DesktopPreferenceStore(root=root / 'preferences'))
engine.load(QUrl.fromLocalFile(str(Path.cwd() / 'src/market_vault/desktop/qml/Main.qml')))
assert engine.rootObjects()
window = engine.rootObjects()[0]
window.setWidth(1024); window.setHeight(600)
owner = session.context_properties['quantResearchController']
controller, final = owner.intradayResearchController, owner.intradayFinalController
assert session.shell.selectPage('quant_research')
def descendants(parent):
    pending = [parent]
    while pending:
        item = pending.pop()
        yield item
        if hasattr(item, 'childItems'): pending.extend(item.childItems())
def find(name, parent=None):
    base = parent or window
    item = base.findChild(QObject, name)
    if item is None:
        visual = window.contentItem() if base is window else base
        if not hasattr(visual, 'childItems'):
            visual = base.property('contentItem') or base
        item = next((obj for obj in descendants(visual)
            if obj.objectName() == name), None)
    assert item is not None, name
    return item
def value(obj, name):
    result = obj.property(name)
    return result.toVariant() if hasattr(result, 'toVariant') else result
def reveal(item, scroll=None, scope=None):
    if scroll is None: return
    flick = find(scroll, scope).property('contentItem')
    rect = item.mapRectToItem(flick, item.boundingRect())
    for axis, start, end, size in (('X', rect.left(), rect.right(), flick.width()),
            ('Y', rect.top(), rect.bottom(), flick.height())):
        delta = start if start < 0 else max(0, end - size)
        limit = max(0, flick.property('contentWidth' if axis == 'X' else 'contentHeight') - size)
        flick.setProperty('content' + axis, min(max(0, flick.property('content' + axis) + delta), limit))
    QTest.qWait(25)
    rect = item.mapRectToItem(flick, item.boundingRect())
    assert rect.left() >= -1 and rect.right() <= flick.width() + 1, (item.objectName(), rect, flick.width())
    assert rect.top() >= -1 and rect.bottom() <= flick.height() + 1, (item.objectName(), rect, flick.height())
def click(name, scroll=None, scope=None):
    item = find(name, scope); app.processEvents(); reveal(item, scroll, scope)
    assert item.isVisible() and item.isEnabled(), name
    point = item.mapToScene(item.boundingRect().center()).toPoint()
    assert 0 <= point.x() < 1024 and 0 <= point.y() < 600, (name, point)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point); QTest.qWait(30)
def nested(item, kind):
    if kind in item.metaObject().className(): return item
    return next(child for child in item.findChildren(QObject) if kind in child.metaObject().className())
def fill(name, text, scroll=None, scope=None):
    item = find(name, scope); reveal(item, scroll, scope)
    window.requestActivate(); QTest.qWait(15)
    edit = nested(item, 'PixelTextField'); edit.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier); QTest.keyClick(window, Qt.Key_Backspace)
    for char in text:
        QGuiApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, ord(char.upper()), Qt.NoModifier, char))
    app.processEvents()
    assert item.property('text') == text, (name, item.property('text'))
def choose(name, index, scroll=None, scope=None):
    item = find(name, scope); reveal(item, scroll, scope)
    combo = nested(item, 'PixelComboBox')
    window.requestActivate(); QTest.qWait(15); combo.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_Space); QTest.keyClick(window, Qt.Key_Home)
    for _ in range(index): QTest.keyClick(window, Qt.Key_Down)
    QTest.keyClick(window, Qt.Key_Return); QTest.qWait(30)
    assert item.property('currentIndex') == index, (name, index, item.property('currentIndex'))
def complete(target=controller, status='SUCCESS'):
    deadline = time.monotonic() + 150
    while target.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    assert not target.busy and target.status == status, (target.status, target.error)
    QTest.qWait(35)
def selected(name, path, target=controller, status='SUCCESS'):
    dialog = find(name)
    assert dialog.property('visible'), name
    assert dialog.setProperty('selectedFile', QUrl.fromLocalFile(str(path)))
    assert QMetaObject.invokeMethod(dialog, 'accepted', Qt.DirectConnection)
    QMetaObject.invokeMethod(dialog, 'close', Qt.DirectConnection)
    complete(target, status)
def close(dialog):
    assert QMetaObject.invokeMethod(dialog, 'close', Qt.DirectConnection)
    QTest.qWait(25)
def screenshot(name):
    QTest.qWait(60)
    assert window.grabWindow().save(str(root / (name + '.png')))
def open_plan(name, status='SUCCESS'):
    click('intradayPlanLoadButton', panel_scroll)
    selected('intradayPlanOpenDialog', root / name, status=status)
def open_record(name):
    click('intradayExperimentOpenButton', panel_scroll)
    selected('intradayExperimentOpenDialog', sources[name])
def proof():
    return controller._content, controller._proof, controller.experimentPath, controller.restoreRevision
def draft():
    return controller.draftPlan, controller.draftSource, controller.draftRevision
def forbidden(*args, **kwargs):
    raise AssertionError('offline draft action loaded Q5, fitted or executed')
data_loader, research_loader, execution = intraday_data.load_intraday_dataset, research.load_intraday_dataset, research.run_intraday_execution
intraday_data.load_intraday_dataset = research.load_intraday_dataset = forbidden
research._fit = research.fit_ridge_rows = research.run_intraday_execution = forbidden
panel_scroll, settings_scroll = 'intradayResearchScroll', 'intradaySettingsScroll'
click('quantIntradayTab'); click('intradayComparisonTab')
settings, diagnostics = find('intradayResearchSettings'), find('intradayDiagnosticsDialog')
scenarios, editor = find('intradayExecutionScenariosDialog'), find('intradayStrategyEditor')
open_record('grid')
assert controller.restoreRevision == 1 and not controller.draftLoaded and not controller.dataLoaded
recorded_proof = proof()
click('intradayOpenDiagnosticsButton', panel_scroll)
assert diagnostics.property('restoreRevision') == 'result:1'
close(diagnostics)
open_plan('diagnostics-plan.json')
assert controller.draftRevision == 1 and proof() == recorded_proof
click('intradayPlanEditButton', panel_scroll)
assert diagnostics.property('restoreRevision') == 'draft:1'
assert find('quantDiagnosticsFirstValues', diagnostics).property('text') == '130,130.000000000001'
assert find('quantDiagnosticsCosts', diagnostics).property('text') == '1/2,3/4'
for language, caption in (('en', 'Save diagnostics plan'), ('zh-CN', '保存参数诊断计划')):
    assert session.i18n.setLanguage(language); QTest.qWait(35)
    button = find('quantDiagnosticsSavePlan', diagnostics)
    reveal(button, 'strategyDiagnosticsScroll', diagnostics)
    assert button.property('text') == caption and not button.property('truncated')
    screenshot('plan-diagnostics-' + language)
fill('quantDiagnosticsCosts', '1.5/2.5,3/4', 'strategyDiagnosticsScroll', diagnostics)
click('quantDiagnosticsSavePlan', 'strategyDiagnosticsScroll', diagnostics)
assert controller.pendingPlanKind == 'diagnostics' and find('intradayPlanSaveDialog').property('visible')
screenshot('plan-save-dialog-zh-CN')
captured = controller._plan_save_pending['content']
find('quantDiagnosticsCosts', diagnostics).setProperty('text', '9/9')
selected('intradayPlanSaveDialog', root / '参数诊断-captured.json')
saved = load_intraday_plan(root / '参数诊断-captured.json')
assert (root / '参数诊断-captured.json').read_bytes() == captured
assert saved['cost_scenarios'][0] == {'commission_bps': 1.5, 'slippage_bps': 2.5}
assert find('quantDiagnosticsCosts', diagnostics).property('text') == '9/9'
click('quantDiagnosticsSavePlan', 'strategyDiagnosticsScroll', diagnostics)
assert controller.pendingPlanKind == 'diagnostics'
assert QMetaObject.invokeMethod(find('intradayPlanSaveDialog'), 'rejected', Qt.DirectConnection)
close(find('intradayPlanSaveDialog'))
assert not controller.pendingPlanKind
fill('quantDiagnosticsCosts', 'invalid', 'strategyDiagnosticsScroll', diagnostics)
click('quantDiagnosticsSavePlan', 'strategyDiagnosticsScroll', diagnostics)
assert controller.status == 'VALIDATION_ERROR' and not controller.pendingPlanKind
assert not find('intradayPlanSaveDialog').property('visible') and proof() == recorded_proof
fill('quantDiagnosticsCosts', '9/9', 'strategyDiagnosticsScroll', diagnostics)
close(diagnostics)
open_plan('scenarios-plan.json')
click('intradayPlanEditButton', panel_scroll)
assert scenarios.property('restoreRevision') == 'draft:2'
fill('intradayScenarioMaxHold', '6', 'intradayScenariosEditorScroll')
for language, caption in (('en', 'Save scenarios plan'), ('zh-CN', '保存执行情景计划')):
    assert session.i18n.setLanguage(language); QTest.qWait(35)
    assert find('intradayScenariosSavePlan').property('text') == caption
    screenshot('plan-scenarios-' + language)
click('intradayScenariosSavePlan')
captured = controller._plan_save_pending['content']
find('intradayScenarioMaxHold').setProperty('text', '7')
selected('intradayPlanSaveDialog', root / 'scenarios-captured.json')
saved = load_intraday_plan(root / 'scenarios-captured.json')
assert (root / 'scenarios-captured.json').read_bytes() == captured
assert saved['comparison_plan']['execution']['max_hold_bars'] == 4
assert saved['comparison_plan']['execution']['commission_bps'] == 7.5
assert saved['execution_scenarios'][0]['execution']['max_hold_bars'] == 6
assert find('intradayScenarioMaxHold').property('text') == '7'
close(scenarios)
open_plan('comparison-plan.json')
click('intradayPlanEditButton', panel_scroll)
fill('quantStrategyName', 'Edited Flat', settings_scroll, settings)
fill('quantConditionThreshold0', '999999', settings_scroll, settings)
for language, caption in (('en', 'Save comparison plan'), ('zh-CN', '保存比较计划')):
    assert session.i18n.setLanguage(language); QTest.qWait(35)
    button = find('intradayComparisonPlanSave')
    reveal(button, settings_scroll)
    assert button.property('text') == caption
    assert original in find('intradayPlanLocator').property('text')
    screenshot('plan-comparison-' + language)
click('intradayComparisonPlanSave', settings_scroll)
captured = controller._plan_save_pending['content']
assert json.loads(captured)['strategies'][0]['name'] == 'Edited Flat'
assert json.loads(captured)['strategies'][0]['threshold'] == 999999
find('intradayResearchCommission').setProperty('text', '12.5')
selected('intradayPlanSaveDialog', root / 'comparison-captured.json')
assert (root / 'comparison-captured.json').read_bytes() == captured
assert find('intradayResearchCommission').property('text') == '12.5'
# An offline projection edit keeps the existing rule visible, then fails validation.
fill('intradayResearchFeatures', 'missing_feature', settings_scroll)
assert value(settings, 'featureOptions') == ['missing_feature', 'sma_5']
assert find('quantConditionFeature0', editor).property('currentText') == 'sma_5'
click('intradayComparisonPlanSave', settings_scroll)
assert controller.status == 'VALIDATION_ERROR' and not controller.pendingPlanKind
assert not find('intradayPlanSaveDialog').property('visible')
fill('intradayResearchFeatures', 'sma_5', settings_scroll)
click('intradayResearchSettingsDone', settings_scroll)
assert proof() == recorded_proof
retained_draft = draft()
open_plan('bad-plan.json', status='FAILED')
assert draft() == retained_draft and proof() == recorded_proof
assert find('intradayResearchCommission').property('text') == '12.5'
assert value(editor, 'strategies')[0]['name'] == 'Edited Flat'
open_record('collection')
assert draft() == retained_draft and not controller.canContinueCandidate
assert not find('intradayPlanContinueButton').isEnabled()
choose('intradayResearchScenario', 1, panel_scroll)
assert draft() == retained_draft and find('intradayResearchCommission').property('text') == '12.5'
click('intradayResearchSettingsButton', panel_scroll)
assert value(editor, 'strategies')[0]['name'] == 'Edited Flat'
click('intradayResearchSettingsDone', settings_scroll)
click('intradayScenarioExportButton', panel_scroll)
selected('intradayScenarioExportDialog', root / 'ordinary-child.json')
assert controller.canContinueCandidate
choose('intradayResearchCandidate', 1, panel_scroll)
click('intradayPlanContinueButton', panel_scroll); complete()
assert controller.draftSource['path'] == str(root / 'ordinary-child.json')
assert controller.draftPlan['execution'] == controller._root['report']['groups'][0]['execution_policy']
open_record('grid')
choose('intradayResearchCandidate', 7, panel_scroll)
click('intradayPlanContinueButton', panel_scroll); complete()
expected = controller._root['report']['groups'][1]
continued = controller.draftPlan
assert continued['strategies'] == [expected['results'][1]['strategy']]
assert continued['execution'] == expected['execution_policy']
assert controller.draftSource['cost_index'] == controller.draftSource['candidate_index'] == 1
assert continued['intraday_data_path'] == original
retained_draft, retained_proof = draft(), proof()
for language, caption in (('en', 'Independent plan draft'), ('zh-CN', '独立计划草稿')):
    assert session.i18n.setLanguage(language); QTest.qWait(35)
    notice = find('intradayPlanDraftNotice'); reveal(notice, panel_scroll)
    assert caption in notice.property('text') and controller.draftSource['candidate_id'] in notice.property('text')
    assert not notice.property('truncated')
    screenshot('plan-candidate-source-' + language)
# The shared non-intraday dialog keeps its optional Save hidden and accepts numeric revisions.
normal = find('quantDiagnosticsDialog')
assert normal.property('preserveCosts') is False
form = {'strategies': [{'kind': 'FEATURE_RULE', 'name': 'Normal', 'signal_field': 'sma_5',
    'comparator': 'GT', 'threshold': 1}], 'commission_bps': '0', 'slippage_bps': '0'}
expr = QQmlExpression(engine.rootContext(), normal, 'prepare(' + json.dumps(form) + ', {}, 1)')
expr.evaluate(); assert not expr.hasError(), expr.error().toString()
assert normal.property('restoreRevision') == 1
assert not find('quantDiagnosticsSavePlan', normal).isVisible()
close(normal)
assert draft() == retained_draft and proof() == retained_proof
# Real Q5 Open is now allowed; fitting remains forbidden for the single Composite Run.
load_calls = []
def checked_data(path):
    load_calls.append(('open', str(path))); return data_loader(path)
def checked_research(path):
    load_calls.append(('run', str(path))); return research_loader(path)
intraday_data.load_intraday_dataset = checked_data
research.load_intraday_dataset = checked_research
research.run_intraday_execution = execution
click('intradayDataTab')
fill('intradayDataPath', str(mismatch_path)); click('intradayInspectButton'); complete(owner)
assert controller.sourceId != continued['data_id']
click('intradayComparisonTab')
assert draft() == retained_draft and proof() == retained_proof
assert settings.property('dataLocator') == original
click('intradayRunComparisonButton', panel_scroll)
assert controller.status == 'VALIDATION_ERROR' and 'matching' in controller.error
assert not any(kind == 'run' for kind, _ in load_calls)
click('intradayDataTab')
fill('intradayDataPath', str(root / 'same-id-other-locator.json'))
click('intradayInspectButton'); complete(owner)
assert controller.sourceId == continued['data_id'] and controller.dataPath != original
click('intradayComparisonTab')
assert draft() == retained_draft and proof() == retained_proof
assert settings.property('dataLocator') == original
missing = dict(continued, intraday_data_path=str(root / 'missing-original.json'))
write_intraday_plan(serialize_intraday_plan(missing), path=root / 'missing-plan.json')
open_plan('missing-plan.json')
missing_draft = draft()
click('intradayRunComparisonButton', panel_scroll); complete(status='FAILED')
assert draft() == missing_draft and proof() == retained_proof
assert load_calls[-1] == ('run', str(root / 'missing-original.json'))
click('intradayPlanContinueButton', panel_scroll); complete()
run_draft = draft()
click('intradayRunComparisonButton', panel_scroll); complete()
assert controller._proof == 'COMPUTED' and len(controller._root['report']['groups'][0]['results']) == 1
assert controller._root['plan']['intraday_data_path'] == original
assert controller._root['plan']['strategies'] == continued['strategies']
assert controller._root['plan']['execution'] == continued['execution']
assert load_calls[-1] == ('run', original) and draft() == run_draft
assert [kind for kind, _ in load_calls] == ['open', 'open', 'run', 'run']
notice = find('intradayPlanDraftNotice'); reveal(notice, panel_scroll)
screenshot('plan-original-locator-run-zh-CN')
assert final.openTest(str(sources['test'])); complete(final)
click('intradayFinalTab')
assert final._test_proof == 'RECORDED' and not find('intradayPlanContinueButton').isVisible()
assert draft() == run_draft
assert {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sources.items()} == before
assert hashlib.sha256(Path(original).read_bytes()).hexdigest() == original_digest
assert session.runtime.backend_if_initialized is None and session.runtime.shutdown()
print('REAL_PLAN_DRAFT_QML_OK')
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(mismatched_plan_data.path)],
        cwd=ROOT, env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"},
        capture_output=True, text=True, timeout=300)
    (tmp_path / "qml-process.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "REAL_PLAN_DRAFT_QML_OK" in result.stdout


@pytest.fixture(scope="session")
def saved_comparison_diagnostics(research_case):
    _, plan, _ = research_case
    diagnostic = diagnostic_plan(plan)
    return create_intraday_experiment(plan=diagnostic, report=research.run_intraday_research(diagnostic))


def _named_saved_experiment(snapshot, name):
    from market_vault.research.intraday_data import digest
    root = snapshot.as_dict()
    root["name"] = name
    root["experiment_id"] = digest({key: value for key, value in root.items() if key != "experiment_id"})
    return StrategyExperiment(canonical_json(root))


def _unavailable_saved_candidate(snapshot):
    root = snapshot.as_dict()
    root["report"]["groups"][0]["results"][1]["execution"]["trades"][0]["commission_total"] += .01
    return StrategyExperiment(signed(root))


@pytest.fixture(scope="session")
def small_parameter_grids(research_case):
    """Cover zero/one axis using the same verified data and rule execution only."""
    data, comparison, _ = research_case
    snapshots = []
    for axes in ([], [{"parameter": "threshold", "values": [130, 130.000000000001]}]):
        plan = {"plan_schema_version": research.INTRADAY_DIAGNOSTICS_PLAN_VERSION,
            "comparison_plan": comparison, "strategy_name": "Flat", "parameter_axes": axes,
            "cost_scenarios": [{"commission_bps": 0, "slippage_bps": 0}]}
        normalized, children, coordinates = research.expand_intraday_plan(plan, recorded=True)
        prepared = research._prepare_intraday_research(children[0], data=data)
        report = research._evaluate_intraday_research(normalized, children, coordinates, prepared)
        snapshots.append(create_intraday_experiment(plan=normalized, report=report))
    return tuple(snapshots)


def _grid_unavailable_center(snapshot):
    root = snapshot.as_dict()
    for point in root["report"]["groups"][1]["results"][1]["execution"]["ledger"]:
        for key in ("cash", "quantity", "equity"):
            point[key] *= 2
    return StrategyExperiment(signed(root))


def test_parameter_grid_controller_preserves_selection_cache_and_proof(qt_app, parameter_grid_experiment,
        small_parameter_grids, intraday_experiment, tmp_path, monkeypatch):
    from market_vault.research import intraday_parameter_grid as grid
    second = _named_saved_experiment(parameter_grid_experiment, "Same shape, another saved record")
    partial = _grid_unavailable_center(parameter_grid_experiment)
    runtime, runner = _runtime(tmp_path, [])
    controller = QuantResearchController(runtime).intradayResearchController
    calls, analyze = [], grid.analyze_intraday_parameter_grid
    def captured(snapshot, **indices):
        calls.append((snapshot, indices))
        return analyze(snapshot, **indices)
    def forbidden(*args, **kwargs):
        pytest.fail("Grid selection revalidated, loaded data, fitted, or executed")
    monkeypatch.setattr(grid, "analyze_intraday_parameter_grid", captured)
    monkeypatch.setattr(StrategyExperiment, "__post_init__", forbidden)
    for name in ("load_intraday_dataset", "_fit", "fit_ridge_rows", "run_intraday_execution"):
        monkeypatch.setattr(research, name, forbidden)
    assert not controller.gridAvailable and not controller.selectGridCandidate(0)
    controller._apply(parameter_grid_experiment, path=str(tmp_path / "grid.json"), opened=True)
    assert controller.gridCostIndex == controller.candidateIndex == controller.gridMetricIndex == 0
    assert not calls and controller._grid_snapshot is parameter_grid_experiment
    # A previous explicit choice is the center when entering the new view.
    assert controller.selectCandidate(7) and controller.selectView(16)
    first = controller.parameterGrid
    assert first["selection"]["cost_index"] == 1 and first["selection"]["center_candidate_index"] == 1
    assert first["selection"]["metric"] == "total_return"
    assert [row["candidate_index"] for row in first["cells"]] == list(range(6))
    assert [axis["condition_index"] for axis in first["axes"]] == [0, 1]
    assert first["axes"][0]["values"][-1] == "130.000000000001"
    assert [(n["axis_index"], n["direction"], n["candidate_index"]) for n in first["neighbors"]] == [
        (0, "LOWER", 3), (0, "HIGHER", 5), (1, "HIGHER", 0)]
    assert first["neighborhood_summary"]["available_count"] == 3
    assert all(row["delta"]["unit"] == "PERCENTAGE_POINTS" for row in first["neighbors"])
    original = (controller._content, controller.experimentPath, controller.restoredPlan, controller._proof)
    first["cells"][1]["candidate_id"] = "changed detached view"
    assert controller.parameterGrid["center"]["candidate_id"] != "changed detached view"
    count = len(calls)
    assert controller.selectView(1) and controller.selectView(16)
    assert len(calls) == count
    for index, metric in enumerate(grid.PARAMETER_GRID_METRICS):
        assert controller.selectGridMetric(index)
        assert controller.parameterGrid["selection"]["metric"] == metric
        assert controller.candidateIndex == 7
    assert controller.selectGridCost(0) and controller.candidateIndex == 1
    assert controller.selectGridCandidate(4) and controller.candidateIndex == 4
    selected = controller.selection_source()
    assert (selected["cost_index"], selected["candidate_index"]) == (0, 4)
    assert selected["candidate_id"] == controller.parameterGrid["center"]["candidate_id"]
    assert controller.openGridCandidateDetails() and controller.viewIndex == 1
    assert controller.tableModel.totalRows == len(controller._selected()[1]["execution"]["trades"])
    assert controller.selectView(16) and controller.candidateIndex == 4 and controller.gridMetricIndex == 5
    assert (controller._content, controller.experimentPath, controller.restoredPlan, controller._proof) == original
    assert all(snapshot is parameter_grid_experiment for snapshot, _ in calls)
    for action in (controller.selectGridCost, controller.selectGridCandidate, controller.selectGridMetric):
        assert not action(-1) and not action(True) and not action(99)
    # Reopening a same-shaped record clears both immutable object and derived cache.
    controller._apply(second, path=str(tmp_path / "second.json"), opened=True)
    assert controller.candidateIndex == controller.gridCostIndex == controller.gridMetricIndex == 0
    assert calls[-1][0] is second and controller._grid_snapshot is second
    assert controller.parameterGrid["experiment_id"] == second.experiment_id
    assert controller._proof == "RECORDED"
    controller._apply(partial, path=str(tmp_path / "partial.json"), opened=True)
    assert controller.selectGridCost(1) and controller.selectGridCandidate(1) and controller.selectGridMetric(4)
    unavailable = controller.parameterGrid
    assert unavailable["center"]["metric"]["display"] == "—"
    assert unavailable["center"]["metric"]["unavailable_reason"] == "RECORDED_LEDGER_RECONCILIATION_FAILED"
    assert all(row["delta"]["unavailable_reason"] == "LEFT_UNAVAILABLE" for row in unavailable["neighbors"])
    assert unavailable["neighborhood_summary"]["available_count"] == 3
    for dimension, snapshot in enumerate(small_parameter_grids):
        controller._apply(snapshot, opened=True)
        assert len(controller.parameterGrid["axes"]) == dimension
        assert len(controller.parameterGrid["cells"]) == dimension + 1
        if dimension == 0:
            assert controller.parameterGrid["neighborhood_summary"]["unavailable_reason"] == "NO_NEIGHBORS"
    controller._apply(intraday_experiment, opened=True)
    assert not controller.gridAvailable and controller.parameterGrid == {} and controller._grid_snapshot is None
    assert not controller.selectGridMetric(0) and not controller.openGridCandidateDetails()
    assert controller._proof == "RECORDED" and not runner.names
    assert runtime.backend_if_initialized is None and runtime.shutdown()


def test_actual_qml_parameter_grid_selection_precision_and_offline_identity(parameter_grid_experiment,
        small_parameter_grids, intraday_experiment, final_case, tmp_path):
    mismatch_root = parameter_grid_experiment.as_dict()
    mismatch_root["report"]["groups"][1]["benchmark"]["execution"]["ledger"][0]["mark_price"] += .01
    snapshots = {"grid": parameter_grid_experiment,
        "second": _named_saved_experiment(parameter_grid_experiment, "Same-shaped second file"),
        "partial": _grid_unavailable_center(parameter_grid_experiment),
        "mismatch": StrategyExperiment(signed(mismatch_root)),
        "zero": small_parameter_grids[0], "one": small_parameter_grids[1],
        "ordinary": intraday_experiment, "test": final_case[1]}
    for name, snapshot in snapshots.items():
        write_strategy_experiment(snapshot, path=tmp_path / (name + ".json"))
    (tmp_path / "settings.yaml").write_text("storage:\n  root_dir: ./data\n")
    script = r'''
import hashlib, sys, time
from pathlib import Path
from PySide6.QtCore import QObject, QUrl, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from market_vault.application import build_application_context
from market_vault.desktop.bootstrap import create_qml_application_session
from market_vault.desktop.preferences import DesktopPreferenceStore
from market_vault.research import intraday_research as research
from market_vault.research.strategy_experiment import StrategyExperiment
root = Path(sys.argv[1])
sources = {name: root / (name + '.json') for name in ('grid', 'second', 'partial', 'mismatch', 'zero', 'one', 'ordinary', 'test')}
before = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sources.items()}
QQuickStyle.setStyle('Basic')
app = QGuiApplication([])
engine = QQmlApplicationEngine()
session = create_qml_application_session(build_application_context(root / 'settings.yaml'), engine,
    preference_store=DesktopPreferenceStore(root=root / 'preferences'))
engine.load(QUrl.fromLocalFile(str(Path.cwd() / 'src/market_vault/desktop/qml/Main.qml')))
assert engine.rootObjects()
window = engine.rootObjects()[0]
window.setWidth(1024); window.setHeight(600)
owner = session.context_properties['quantResearchController']
controller, final = owner.intradayResearchController, owner.intradayFinalController
assert session.shell.selectPage('quant_research')
def descendants(parent):
    pending = [parent]
    while pending:
        item = pending.pop()
        yield item
        pending.extend(item.childItems())
def find(name):
    result = window.findChild(QObject, name)
    if result is None:
        result = next((item for item in descendants(window.contentItem()) if item.objectName() == name), None)
    assert result is not None, name
    return result
def reveal(item):
    flick = find('intradayResearchScroll').property('contentItem')
    rect = item.mapRectToItem(flick, item.boundingRect())
    delta = rect.top() if rect.top() < 0 else max(0, rect.bottom() - flick.height())
    flick.setProperty('contentY', min(max(0, flick.property('contentY') + delta),
        max(0, flick.property('contentHeight') - flick.height())))
    QTest.qWait(25)
    rect = item.mapRectToItem(flick, item.boundingRect())
    assert rect.top() >= -1 and rect.bottom() <= flick.height() + 1, (item.objectName(), rect, flick.height())
def click(name):
    item = find(name)
    app.processEvents()
    assert item.isVisible() and item.isEnabled(), name
    point = item.mapToScene(item.boundingRect().center()).toPoint()
    assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), (name, point)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.qWait(30)
def choose(name, index):
    item = find(name)
    reveal(item)
    combo = next(c for c in item.findChildren(QObject) if 'PixelComboBox' in c.metaObject().className())
    window.requestActivate(); QTest.qWait(15)
    combo.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_Space)
    QTest.keyClick(window, Qt.Key_Home)
    for _ in range(index): QTest.keyClick(window, Qt.Key_Down)
    QTest.keyClick(window, Qt.Key_Return)
    QTest.qWait(35)
    assert item.property('currentIndex') == index, (name, index, item.property('currentIndex'))
def complete(operation):
    deadline = time.monotonic() + 30
    while operation.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    assert operation.status == 'SUCCESS', (operation.status, operation.error)
    QTest.qWait(40)
def open_record(name):
    assert controller.openExperiment(str(sources[name])); complete(controller)
def inside(item, parent):
    assert item.isVisible() and not item.property('truncated'), item.objectName()
    rect = item.mapRectToItem(parent, item.boundingRect())
    assert rect.left() >= -1 and rect.right() <= parent.width() + 1, (item.objectName(), rect, parent.width())
    assert rect.top() >= -1 and rect.bottom() <= parent.height() + 1, (item.objectName(), rect, parent.height())
def reveal_cell(index):
    viewport = find('intradayParameterGridScroll')
    reveal(viewport)
    item = find('intradayGridCell' + str(index))
    rect = item.mapRectToItem(viewport, item.boundingRect())
    for axis, start, end, size in (('X', rect.left(), rect.right(), viewport.width()),
            ('Y', rect.top(), rect.bottom(), viewport.height())):
        delta = start if start < 0 else max(0, end - size)
        viewport.setProperty('content' + axis, max(0, viewport.property('content' + axis) + delta))
    QTest.qWait(35)
    inside(item, viewport)
    label = find('intradayGridCoordinates' + str(index))
    inside(label, item); inside(label, viewport)
    return label
def screenshot(name):
    assert window.grabWindow().save(str(root / (name + '.png')))
def forbidden(*args, **kwargs):
    raise AssertionError('Parameter grid cannot load Q5, fit, execute, or write records')
for name in ('load_intraday_dataset', '_fit', 'fit_ridge_rows', 'run_intraday_execution'):
    setattr(research, name, forbidden)
built, validated = [], StrategyExperiment.__post_init__
def validate(snapshot):
    built.append(id(snapshot))
    validated(snapshot)
StrategyExperiment.__post_init__ = validate
click('quantIntradayTab'); click('intradayComparisonTab')
open_record('grid')
assert controller.gridCostIndex == controller.candidateIndex == controller.gridMetricIndex == 0
choose('intradayResearchCandidate', 7)
find('intradayResearchCommission').setProperty('text', '17.25')
saved = (controller._content, controller.experimentPath, controller._proof)
choose('intradayResearchView', 16)
assert controller._grid_report['selection']['cost_index'] == 1
assert controller._grid_report['selection']['center_candidate_index'] == 1
assert controller._grid_report['selection']['metric'] == 'total_return'
validation_count = len(built)
snapshot = controller._grid_snapshot
for language, axis_caption in (('en', 'Condition threshold'), ('zh-CN', '条件阈值')):
    assert session.i18n.setLanguage(language); QTest.qWait(40)
    assert (controller.gridCostIndex, controller.candidateIndex, controller.gridMetricIndex) == (1, 7, 0)
    assert find('intradayResearchView').property('currentIndex') == 16
    text = reveal_cell(4).property('text')
    assert axis_caption in text and '130.000000000001' in text
    assert 'strategy.condition_threshold' not in text
    screenshot('grid-composite-' + language)
click('intradayGridCell4')
assert controller.candidateIndex == 10 and find('intradayResearchCandidate').property('currentIndex') == 10
selected = controller.selection_source()
assert (selected['cost_index'], selected['candidate_index']) == (1, 4)
assert controller._grid_report['selection']['center_candidate_id'] == selected['candidate_id']
identity = find('intradayGridCenterIdentity')
reveal(identity)
assert selected['experiment_id'] in identity.property('text') and selected['candidate_id'] in identity.property('text')
inside(identity, find('intradayResearchScroll').property('contentItem'))
screenshot('grid-center-identity-zh-CN')
reveal(find('intradayGridOpenDetails')); click('intradayGridOpenDetails')
assert controller.viewIndex == 1 and find('intradayResearchView').property('currentIndex') == 1
assert find('intradayResearchTable').isVisible()
assert controller.tableModel.totalRows == len(controller._selected()[1]['execution']['trades'])
assert controller.selection_source() == selected
choose('intradayResearchView', 16)
choose('intradayGridMetric', 2)
assert controller._grid_report['cells'][4]['metric']['unit'] == 'COUNT'
choose('intradayGridMetric', 4)
assert controller._grid_report['selection']['metric'] == 'median_fold_return'
assert controller._grid_report['cells'][4]['metric']['evidence'] == 'RECORDED_LEDGER_DERIVATION'
choose('intradayGridCost', 0)
assert controller.candidateIndex == 4 and controller.gridMetricIndex == 4
reveal(find('intradayGridSelectNeighbor0')); click('intradayGridSelectNeighbor0')
assert controller.candidateIndex == 0
assert [(n['axis_index'], n['direction'], n['candidate_index']) for n in controller._grid_report['neighbors']] == [
    (0, 'LOWER', 2), (0, 'HIGHER', 4), (1, 'LOWER', 1)]
summary = find('intradayGridSummary'); reveal(summary)
assert '不含中心' in summary.property('text') and '纳入值数: 3' in summary.property('text')
inside(summary, find('intradayResearchScroll').property('contentItem'))
screenshot('grid-neighbor-summary-zh-CN')
assert len(built) == validation_count and controller._grid_snapshot is snapshot
assert find('intradayResearchCommission').property('text') == '17.25'
assert (controller._content, controller.experimentPath, controller._proof) == saved

open_record('partial')
choose('intradayGridCost', 1); reveal_cell(1); click('intradayGridCell1')
choose('intradayGridMetric', 4)
assert controller.parameterGrid['center']['metric']['display'] == '—'
assert controller._grid_report['cells'][1]['metric']['value'] is None
assert controller._grid_report['neighborhood_summary']['available_count'] == 3
identity = find('intradayGridCenterIdentity'); reveal(identity)
assert '账本记录不一致' in identity.property('text')
delta = find('intradayGridDelta3'); reveal(delta)
assert '中心指标不可用' in delta.property('text') and '百分点' in delta.property('text')
inside(delta, find('intradayResearchScroll').property('contentItem'))
screenshot('grid-unavailable-center-zh-CN')
assert controller._proof == 'RECORDED'
open_record('mismatch')
choose('intradayGridCost', 1); reveal_cell(1); click('intradayGridCell1')
assert all(cell['metric']['value'] is not None for cell in controller._grid_report['cells'])
assert controller._grid_report['neighborhood_summary']['unavailable_reason'] == 'NO_MATCHING_BASIS'
delta = find('intradayGridDelta3'); reveal(delta)
assert '基础不同' in delta.property('text') and '原始价格序列' in delta.property('text')
screenshot('grid-basis-mismatch-zh-CN')

old_snapshot = controller._grid_snapshot
open_record('second')
assert controller._grid_snapshot is not old_snapshot
assert controller._grid_report['experiment_id'] == controller._root['experiment_id']
assert controller._grid_report['experiment_id'] != selected['experiment_id']
assert (controller.gridCostIndex, controller.candidateIndex, controller.gridMetricIndex) == (0, 0, 0)
assert controller._proof == 'RECORDED'
open_record('one')
assert controller.parameterGrid['axes'][0]['values'] == ['130.0', '130.000000000001']
assert len(controller._grid_report['cells']) == 2
for language in ('en', 'zh-CN'):
    assert session.i18n.setLanguage(language); QTest.qWait(40)
    first = reveal_cell(0).property('text')
    second = reveal_cell(1).property('text')
    assert first != second and '130.0' in first and '130.000000000001' in second
    assert '130.000000000001' not in first
    inside(find('intradayGridCoordinates0'), find('intradayParameterGridScroll'))
    screenshot('grid-close-coordinates-' + language)
open_record('zero')
assert controller.parameterGrid['axes'] == [] and len(controller.parameterGrid['cells']) == 1
assert controller._grid_report['neighbors'] == []
summary = find('intradayGridSummary'); reveal(summary)
assert '无轴向邻居' in summary.property('text') and '—' in summary.property('text')
screenshot('grid-zero-axis-zh-CN')
open_record('ordinary')
assert not controller.gridAvailable and controller.parameterGrid == {} and controller._grid_snapshot is None
notice = find('intradayParameterGridNotice'); reveal(notice)
assert '普通比较、情景子项和 TEST' in notice.property('text')
assert not find('intradayParameterGridScroll').isVisible()
screenshot('grid-ordinary-unavailable-zh-CN')
assert final.openTest(str(sources['test'])); complete(final)
click('intradayFinalTab')
assert not find('intradayParameterGridPanel').isVisible()
test_view = find('intradayTestView')
test_views = test_view.property('model')
if hasattr(test_views, 'toVariant'):
    test_views = test_views.toVariant()
assert session.i18n.catalog['quant.parameter_grid'] not in test_views
assert not final.selectView(15)
assert final._test_proof == 'RECORDED' and controller._proof == 'RECORDED'
assert {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sources.items()} == before
assert session.runtime.backend_if_initialized is None and session.runtime.shutdown()
print('REAL_PARAMETER_GRID_QML_OK')
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], cwd=ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"},
        capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "REAL_PARAMETER_GRID_QML_OK" in result.stdout


def test_saved_portfolio_timestamp_is_displayed_in_utc():
    from market_vault.desktop.intraday_saved_comparison import utc_time
    assert utc_time("2025-02-10T10:00:00-05:00") == utc_time("2025-02-10T15:00:00+00:00") == "15:00:00"


def test_saved_portfolio_captures_action_and_keeps_comparison_results_independent(qt_app,
        intraday_experiment, tmp_path, monkeypatch):
    from market_vault.desktop.intraday_saved_comparison import metric_value
    snapshots = [intraday_experiment, _named_saved_experiment(intraday_experiment, "Second saved source")]
    paths = [tmp_path / "a.json", tmp_path / "b.json"]
    for snapshot, path in zip(snapshots, paths, strict=True):
        write_strategy_experiment(snapshot, path=path)
    runtime, runner = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    controller = owner.intradaySavedComparisonController
    for name in ("load_intraday_dataset", "_fit", "fit_ridge_rows", "run_intraday_execution"):
        monkeypatch.setattr(research, name, lambda *a, **k: pytest.fail("saved portfolio loaded Q5, fitted or executed"))
    assert not controller.canAnalyzePortfolio and not controller.analyzePortfolio()
    assert controller.openLeft(str(paths[0])); runtime._poll()
    assert controller.openRight(str(paths[1])); runtime._poll()
    assert controller.weightAText == controller.weightBText == "0.5" and controller.draftCashWeight == "0%"
    assert controller.compare(); runtime._poll()
    comparison_before, comparison_bound = canonical_json(controller._result), controller.boundSources
    assert controller.selectLeftCandidate(1) and controller.selectRightCandidate(2)
    assert controller.setWeightA("0.35") and controller.setWeightB("0.45")
    pending = []
    def deferred(name, operation):
        future = Future()
        pending.append((future, operation))
        return future
    with monkeypatch.context() as patch:
        patch.setattr(runner, "submit", deferred)
        assert controller.analyzePortfolio() and controller.busy
        assert controller.selectLeftCandidate(0) and controller.selectRightCandidate(1)
        assert controller.setWeightA("0") and controller.setWeightB("0")
        future, operation = pending.pop()
        future.set_result(operation())
        runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    report = controller._portfolio_result
    assert report["availability"]["status"] == "AVAILABLE"
    assert report["allocation"]["weight_a"] == .35 and report["allocation"]["weight_b"] == .45
    assert report["allocation"]["cash_weight"] == pytest.approx(.2)
    assert controller.weightAText == controller.weightBText == "0" and controller.draftCashWeight == "100.0%"
    assert controller.portfolioView and controller.displayedResultLoaded
    captured = controller.displayedBoundSources
    assert [(row["cost_index"], row["candidate_index"]) for row in captured] == [(0, 1), (0, 2)]
    assert [row["path"] for row in captured] == list(map(str, paths))
    assert [row["experiment_id"] for row in captured] == [row.experiment_id for row in snapshots]
    assert controller.boundSources == comparison_bound and canonical_json(controller._result) == comparison_before
    assert controller.leftSource["candidate_index"] == 0 and controller.rightSource["candidate_index"] == 1
    portfolio_before = canonical_json(report)
    operations_before = list(runner.names)
    detached = controller.portfolioContext
    detached["allocation"]["weight_a"] = 1
    assert controller.portfolioContext["allocation"]["weight_a"] == .35
    assert controller.selectView(5)
    row = next(row for row in controller._rows if row[:2] == ("portfolio", "total_return"))
    assert row[2] == metric_value(report["portfolio"]["summary"]["total_return"]["value"], "RATIO")
    assert controller.selectView(6) and controller.tableModel.totalRows == len(report["path"])
    assert [(row[0], row[4]) for row in controller._rows[:4]] == [
        (str(row["sequence"]), row["phase"]) for row in report["path"][:4]]
    assert controller.changePage(1) and controller.tableModel.page == 2
    assert controller.selectView(7) and controller.tableModel.totalRows == 36
    assert {row[1] for row in controller._rows} == {"A", "B", "CASH"}
    assert len(controller.portfolioPolicyRows) == 4
    assert controller.selectView(0) and controller.displayedBoundSources == comparison_bound
    assert runner.names == operations_before and canonical_json(controller._portfolio_result) == portfolio_before
    assert controller.compare(); runtime._poll()
    assert [(row["cost_index"], row["candidate_index"]) for row in controller.boundSources] == [(0, 0), (0, 1)]
    assert canonical_json(controller._portfolio_result) == portfolio_before
    assert controller.selectView(4) and controller.displayedBoundSources == captured
    assert controller.openRight(str(paths[0])); runtime._poll()
    assert controller.rightSource["experiment_id"] == snapshots[0].experiment_id
    assert controller.displayedBoundSources == captured and canonical_json(controller._portfolio_result) == portfolio_before
    assert all(path.read_bytes() == snapshot.content for path, snapshot in zip(paths, snapshots, strict=True))
    assert runtime.backend_if_initialized is None and runtime.shutdown()


def test_saved_portfolio_invalid_drafts_failure_and_retry_retain_result(qt_app,
        intraday_experiment, tmp_path, monkeypatch):
    from market_vault.research import intraday_portfolio as portfolio
    path = tmp_path / "source.json"
    write_strategy_experiment(intraday_experiment, path=path)
    runtime, runner = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    controller = owner.intradaySavedComparisonController
    assert controller.openLeft(str(path)); runtime._poll()
    assert controller.openRight(str(path)); runtime._poll()
    assert controller.selectLeftCandidate(1) and controller.selectRightCandidate(1)
    assert controller.analyzePortfolio(); runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    previous, captured = canonical_json(controller._portfolio_result), controller.displayedBoundSources
    names = list(runner.names)
    for a, b in (("", "0.5"), ("nan", "0.5"), ("inf", "0"), ("-0.1", ".5"),
                 (".6", ".5"), ("1e308", "1e308")):
        assert controller.setWeightA(a) and controller.setWeightB(b)
        assert controller.portfolioInputReason == "INVALID_WEIGHTS" and controller.draftCashWeight == "—"
        assert not controller.canAnalyzePortfolio and not controller.analyzePortfolio()
        assert controller.status == "VALIDATION_ERROR" and runner.names == names
        assert canonical_json(controller._portfolio_result) == previous and controller.displayedBoundSources == captured
    assert controller.setWeightA(".8") and controller.setWeightB(".2")
    assert controller.canAnalyzePortfolio and controller.draftCashWeight == "0%"
    with monkeypatch.context() as patch:
        patch.setattr(portfolio, "analyze_intraday_portfolio", lambda *a, **k: (_ for _ in ()).throw(ValueError("portfolio worker failed")))
        assert controller.analyzePortfolio(); runtime._poll()
    assert controller.status == "FAILED" and controller.error == "portfolio worker failed"
    assert canonical_json(controller._portfolio_result) == previous and controller.displayedBoundSources == captured
    assert controller.openLeft(str(tmp_path / "missing.json")); runtime._poll()
    assert controller.status == "FAILED" and controller.leftSource["path"] == str(path)
    assert canonical_json(controller._portfolio_result) == previous and controller.displayedBoundSources == captured
    assert controller.setWeightA("0") and controller.setWeightB("0")
    assert controller.analyzePortfolio(); runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    report = controller._portfolio_result
    assert report["allocation"]["cash_weight"] == 1 and report["portfolio"]["summary"]["total_return"]["value"] == 0
    assert report["complementarity"]["correlation"] == json.loads(previous)["complementarity"]["correlation"]
    assert controller.selectView(5)
    rows = {row[1]: row for row in controller._rows if row[0] == "portfolio"}
    assert rows["mean_daily_return"][2] == "0%" and rows["sharpe_ratio"][2:] == ("—", "NUMBER", "ZERO_VOLATILITY")
    assert not controller.resultLoaded and controller.portfolioResultLoaded
    assert path.read_bytes() == intraday_experiment.content
    assert runtime.backend_if_initialized is None and runtime.shutdown()


def test_saved_portfolio_keeps_statistic_and_account_na_visible_without_changing_test_comparison(qt_app,
        intraday_experiment, final_case, tmp_path, monkeypatch):
    snapshots = (intraday_experiment, _unavailable_saved_candidate(intraday_experiment), final_case[1])
    paths = [tmp_path / name for name in ("ordinary.json", "partial.json", "test.json")]
    for snapshot, path in zip(snapshots, paths, strict=True):
        write_strategy_experiment(snapshot, path=path)
    runtime, _ = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    controller = owner.intradaySavedComparisonController
    owner.intradayResearchController._proof = owner.intradayFinalController._test_proof = "REPLAY_MATCH"
    for name in ("load_intraday_dataset", "_fit", "fit_ridge_rows", "run_intraday_execution"):
        monkeypatch.setattr(research, name, lambda *a, **k: pytest.fail("saved portfolio loaded Q5, fitted or executed"))
    monkeypatch.setattr(final, "load_intraday_dataset", lambda *a, **k: pytest.fail("saved portfolio loaded TEST data"))
    assert controller.openLeft(str(paths[0])); runtime._poll()
    assert controller.openRight(str(paths[0])); runtime._poll()
    assert controller.selectRightCandidate(1)
    assert controller.analyzePortfolio(); runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    assert controller.portfolioContext["availability"]["status"] == "AVAILABLE"
    assert controller._rows[0] == ("correlation", "—", "NUMBER", "ZERO_VOLATILITY")
    assert controller._rows[1][1] != "—" and controller._portfolio_result["path"]
    assert controller.openRight(str(paths[1])); runtime._poll()
    assert controller.selectRightCandidate(1) and controller.analyzePortfolio(); runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    assert controller.portfolioContext["availability"]["status"] == "UNAVAILABLE"
    assert controller.portfolioContext["availability"]["unavailable_reason"] == "SOURCE_ACCOUNT_UNAVAILABLE"
    assert all(row[1] == "—" and row[3] == "SOURCE_ACCOUNT_UNAVAILABLE" for row in controller._rows)
    warning, = controller.portfolioWarnings
    assert (warning["side"], warning["part"], warning["reason"]) == ("B", "STRATEGY", "RECORDED_CASH_RECONCILIATION_FAILED")
    assert warning["detail"]
    assert controller.selectView(6) and controller.tableModel.totalRows == 0
    captured, previous = controller.displayedBoundSources, canonical_json(controller._portfolio_result)
    assert controller.openRight(str(paths[2])); runtime._poll()
    assert controller.canCompare and not controller.canAnalyzePortfolio and controller.portfolioInputReason == "DEV_ONLY"
    assert not controller.analyzePortfolio() and controller.displayedBoundSources == captured
    assert controller.compare(); runtime._poll()
    assert controller.comparisonNotice == "TEST_DESCRIPTIVE_ONLY"
    assert controller.selectView(0) and controller.displayedBoundSources == controller.boundSources
    assert all(row[5] == "—" and row[9] == "TEST_DESCRIPTIVE_ONLY" for row in controller._rows)
    assert controller.selectView(4) and controller.displayedBoundSources == captured
    assert canonical_json(controller._portfolio_result) == previous
    assert owner.intradayResearchController._proof == owner.intradayFinalController._test_proof == "REPLAY_MATCH"
    assert all(path.read_bytes() == snapshot.content for path, snapshot in zip(paths, snapshots, strict=True))
    assert runtime.backend_if_initialized is None and runtime.shutdown()


def test_saved_comparison_captures_sources_and_indices_with_offline_failure_retention(qt_app,
        saved_comparison_diagnostics, intraday_experiment, tmp_path, monkeypatch):
    from market_vault.desktop.intraday_saved_comparison import metric_value
    from market_vault.research import intraday_saved_comparison as comparison
    a = _named_saved_experiment(saved_comparison_diagnostics, "Saved A")
    b = _named_saved_experiment(saved_comparison_diagnostics, "Saved B")
    a_path, b_path = tmp_path / "a.json", tmp_path / "b.json"
    write_strategy_experiment(a, path=a_path)
    write_strategy_experiment(b, path=b_path)
    runtime, runner = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    controller = owner.intradaySavedComparisonController
    monkeypatch.setattr(research, "load_intraday_dataset", lambda *a, **k: pytest.fail("comparison read Q5"))
    monkeypatch.setattr(final, "load_intraday_dataset", lambda *a, **k: pytest.fail("comparison read TEST data"))
    monkeypatch.setattr(research, "_fit", lambda *a, **k: pytest.fail("comparison fitted"))
    assert not controller.canCompare and not controller.compare()
    assert controller.openLeft(str(a_path))
    runtime._poll()
    assert controller.openRight(str(b_path))
    runtime._poll()
    assert controller.canCompare and controller.status == "SUCCESS", controller.error
    assert controller.selectLeftCost(1) and controller.selectLeftCandidate(2)
    assert controller.selectRightCost(0) and controller.selectRightCandidate(3)
    pending = []
    def deferred(name, operation):
        future = Future()
        pending.append((future, operation))
        return future
    with monkeypatch.context() as patch:
        patch.setattr(runner, "submit", deferred)
        assert controller.compare() and controller.busy
        assert controller.selectLeftCost(0) and controller.selectLeftCandidate(0)
        assert controller.selectRightCandidate(1)
        detached = controller.leftSource
        detached["candidate_names"][0] = "Changed draft copy"
        assert "Changed draft copy" not in controller.leftSource["candidate_names"]
        future, operation = pending.pop()
        future.set_result(operation())
        runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    bound = controller.boundSources
    assert [(row["cost_index"], row["candidate_index"]) for row in bound] == [(1, 2), (0, 3)]
    assert [row["experiment_id"] for row in bound] == [a.experiment_id, b.experiment_id]
    assert [row["name"] for row in bound] == ["Saved A", "Saved B"]
    assert [row["path"] for row in bound] == [str(a_path), str(b_path)]
    assert controller.leftSource["cost_index"] == 0 and controller.leftSource["candidate_index"] == 0
    assert controller.comparisonNotice == "COMPARABLE_DEV" and controller._result["basis_matches"]
    assert controller._result["evidence"] == "RECORDED_LEDGER_DERIVATION"
    rows = {row[0]: row for row in controller._rows}
    values = {row["metric"]: row for row in controller._result["strategy_metrics"]}
    assert rows["mae"][2] == "RATIO" and rows["mae"][1].endswith("%")
    assert float(rows["mae"][1][:-1]) == pytest.approx(values["mae"]["left"]["value"] * 100, rel=1e-5)
    assert rows["mae"][1] != "0.00%" and float(rows["mae"][1][:-1]) > 0
    assert rows["r2"][2] == "NUMBER" and "%" not in rows["r2"][1]
    assert float(rows["r2"][1]) == pytest.approx(values["r2"]["left"]["value"], rel=1e-5)
    assert rows["total_return"][6] == "PERCENTAGE_POINTS"
    assert float(rows["total_return"][5]) == pytest.approx(values["total_return"]["delta"]["value"], rel=1e-5)
    assert float(metric_value(1e-14, "RATIO")[:-1]) == 1e-12
    assert metric_value(2.5, "NUMBER") == "2.5"
    recorded = canonical_json(controller._result)
    assert controller.selectView(2) and controller.configurationRows
    assert any(row["key"] == "execution_policy.commission_bps" for row in controller.configurationRows)
    assert controller.selectView(3)
    basis = {row[0]: row for row in controller._rows}
    assert " · " in basis["raw_prices"][1] and len(basis["raw_prices"][1]) < 32
    assert len(controller._result["basis_checks"]) == 26
    assert canonical_json(controller._result) == recorded
    changed_path = tmp_path / "new-draft.json"
    write_strategy_experiment(intraday_experiment, path=changed_path)
    assert controller.openRight(str(changed_path))
    runtime._poll()
    assert controller.rightSource["experiment_id"] == intraday_experiment.experiment_id
    assert controller.boundSources == bound and canonical_json(controller._result) == recorded
    assert controller.openLeft(str(tmp_path / "missing.json"))
    runtime._poll()
    assert controller.status == "FAILED" and controller.boundSources == bound
    assert canonical_json(controller._result) == recorded and controller.viewIndex == 3
    with monkeypatch.context() as patch:
        patch.setattr(comparison, "compare_saved_intraday_experiments", lambda *a, **k: (_ for _ in ()).throw(ValueError("comparison failed")))
        assert controller.compare()
        runtime._poll()
    assert controller.status == "FAILED" and controller.boundSources == bound
    assert canonical_json(controller._result) == recorded
    assert a_path.read_bytes() == a.content and b_path.read_bytes() == b.content
    assert runtime.backend_if_initialized is None and runtime.shutdown()


def test_saved_comparison_keeps_individual_unavailable_values_and_test_descriptive(qt_app,
        intraday_experiment, final_case, tmp_path, monkeypatch):
    partial = _unavailable_saved_candidate(intraday_experiment)
    a_path, b_path, test_path = tmp_path / "a.json", tmp_path / "partial.json", tmp_path / "test.json"
    for snapshot, path in ((intraday_experiment, a_path), (partial, b_path), (final_case[1], test_path)):
        write_strategy_experiment(snapshot, path=path)
    runtime, _ = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    controller = owner.intradaySavedComparisonController
    owner.intradayResearchController._proof = "REPLAY_MATCH"
    owner.intradayFinalController._test_proof = "REPLAY_MATCH"
    monkeypatch.setattr(research, "load_intraday_dataset", lambda *a, **k: pytest.fail("comparison read Q5"))
    monkeypatch.setattr(final, "load_intraday_dataset", lambda *a, **k: pytest.fail("comparison read TEST data"))
    monkeypatch.setattr(research, "_fit", lambda *a, **k: pytest.fail("comparison fitted"))
    assert controller.openLeft(str(a_path))
    runtime._poll()
    assert controller.openRight(str(b_path))
    runtime._poll()
    assert controller.selectLeftCandidate(1) and controller.selectRightCandidate(1)
    assert controller.compare()
    runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    assert controller._result["left"]["candidate_performance"]["status"] == "AVAILABLE"
    assert controller._result["right"]["candidate_performance"]["status"] == "UNAVAILABLE"
    assert controller._result["right"]["benchmark_performance"]["status"] == "AVAILABLE"
    assert [(row["side"], row["part"]) for row in controller.performanceWarnings] == [("B", "candidate")]
    rows = {row[0]: row for row in controller._rows}
    assert rows["win_rate"][3] == "—" and rows["win_rate"][8] == "RECORDED_CASH_RECONCILIATION_FAILED"
    assert rows["win_rate"][9] == "RIGHT_UNAVAILABLE"
    assert rows["total_return"][3] != "—" and rows["total_return"][11] == "RECORDED"
    assert controller.selectView(1)
    assert {row[0]: row for row in controller._rows}["trade_count"][3] != "—"
    assert controller.openRight(str(test_path))
    runtime._poll()
    assert controller.rightSource["is_test"] and not controller.selectRightCandidate(1)
    assert controller.compare()
    runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    assert controller.comparisonNotice == "TEST_DESCRIPTIVE_ONLY"
    assert controller.comparisonReasons[0] == "TEST_DESCRIPTIVE_ONLY"
    for view in (0, 1):
        assert controller.selectView(view)
        assert all(row[5] == "—" and row[9] == "TEST_DESCRIPTIVE_ONLY" for row in controller._rows)
    assert "REPLAY_MATCH" not in canonical_json(controller._result).decode()
    assert owner.intradayResearchController._proof == owner.intradayFinalController._test_proof == "REPLAY_MATCH"
    assert runtime.backend_if_initialized is None and runtime.shutdown()


def test_actual_qml_saved_comparison_captured_identity_units_and_test_boundary(saved_comparison_diagnostics,
        intraday_experiment, final_case, tmp_path):
    paths = [tmp_path / name for name in ("a.json", "b.json", "ordinary.json", "partial.json", "test.json")]
    snapshots = (_named_saved_experiment(saved_comparison_diagnostics, "Saved A"),
        _named_saved_experiment(saved_comparison_diagnostics, "Saved B"), intraday_experiment,
        _unavailable_saved_candidate(intraday_experiment), final_case[1])
    for snapshot, path in zip(snapshots, paths, strict=True):
        write_strategy_experiment(snapshot, path=path)
    (tmp_path / "settings.yaml").write_text("storage:\n  root_dir: ./data\n")
    script = r'''
import hashlib, json, sys, time
from pathlib import Path
from PySide6.QtCore import QObject, QUrl, Qt, QMetaObject
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from market_vault.application import build_application_context
from market_vault.desktop.bootstrap import create_qml_application_session
from market_vault.desktop.preferences import DesktopPreferenceStore
from market_vault.research import intraday_research, intraday_final_test
from market_vault.research.strategy_experiment import canonical_json
root, a_path, b_path, ordinary_path, partial_path, test_path = map(Path, sys.argv[1:])
originals = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (a_path, b_path, ordinary_path, partial_path, test_path)}
def forbidden(*args, **kwargs): raise AssertionError('Saved comparison read Q5 or fitted a model')
intraday_research.load_intraday_dataset = forbidden
intraday_final_test.load_intraday_dataset = forbidden
intraday_research._fit = forbidden
QQuickStyle.setStyle('Basic')
app = QGuiApplication([])
engine = QQmlApplicationEngine()
session = create_qml_application_session(build_application_context(root / 'settings.yaml'), engine,
    preference_store=DesktopPreferenceStore(root=root / 'preferences'))
engine.load(QUrl.fromLocalFile(str(Path.cwd() / 'src/market_vault/desktop/qml/Main.qml')))
assert engine.rootObjects()
window = engine.rootObjects()[0]
window.setWidth(1024); window.setHeight(600)
owner = session.context_properties['quantResearchController']
controller = owner.intradaySavedComparisonController
assert session.i18n.setLanguage('en')
assert session.shell.selectPage('quant_research')
def visual(parent):
    pending = [parent]
    while pending:
        item = pending.pop()
        yield item
        pending.extend(item.childItems())
def find(name):
    item = window.findChild(QObject, name)
    if item is None: item = next((item for item in visual(window.contentItem()) if item.objectName() == name), None)
    assert item is not None, name
    return item
def reveal(item):
    flick = find('intradaySavedComparisonScroll').property('contentItem')
    rect = item.mapRectToItem(flick, item.boundingRect())
    offset = rect.top() if rect.top() < 0 else max(0, rect.bottom() - flick.height())
    limit = max(0, flick.property('contentHeight') - flick.height())
    flick.setProperty('contentY', min(max(0, flick.property('contentY') + offset), limit))
    QTest.qWait(30)
    rect = item.mapRectToItem(flick, item.boundingRect())
    assert rect.left() >= -1 and rect.right() <= flick.width() + 1, (item.objectName(), rect, flick.width())
    assert rect.top() >= -1 and rect.bottom() <= flick.height() + 1, (item.objectName(), rect, flick.height())
def click(name, inside=True):
    item = find(name)
    app.processEvents()
    if inside: reveal(item)
    assert item.property('visible') and item.property('enabled'), name
    point = item.mapToScene(item.boundingRect().center()).toPoint()
    assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), (name, point)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.qWait(30)
def choose(name, index):
    item = find(name); reveal(item)
    combo = next(item for item in visual(item) if 'PixelComboBox' in item.metaObject().className())
    window.requestActivate(); QTest.qWait(20)
    combo.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_Home)
    for _ in range(index): QTest.keyClick(window, Qt.Key_Down)
    QTest.qWait(30)
    assert item.property('currentIndex') == index, (name, item.property('currentIndex'))
def complete(status='SUCCESS'):
    deadline = time.monotonic() + 90
    while controller.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    app.processEvents()
    assert not controller.busy and controller.status == status, (controller.status, controller.error)
def open_file(side, path, status='SUCCESS'):
    click('intradaySaved' + side + 'Open')
    dialog = find('intradaySavedOpen' + side + 'Dialog')
    assert dialog.setProperty('selectedFile', QUrl.fromLocalFile(str(path)))
    assert QMetaObject.invokeMethod(dialog, 'accepted', Qt.DirectConnection)
    QMetaObject.invokeMethod(dialog, 'close', Qt.DirectConnection)
    complete(status)
def visible_label(parent, caption):
    for label in visual(parent):
        if label.property('text') != caption or not label.property('visible') or label.property('truncated'): continue
        rect = label.mapRectToItem(parent, label.boundingRect())
        if rect.left() >= 0 and rect.right() <= parent.width() and rect.top() >= 0 and rect.bottom() <= parent.height(): return label
    raise AssertionError(('visible complete label', caption))
def check_source_selection(side):
    source = controller.leftSource if side == 'Left' else controller.rightSource
    for suffix, index_key, names_key in (('Cost', 'cost_index', 'cost_names'), ('Candidate', 'candidate_index', 'candidate_names')):
        selector = find('intradaySaved' + side + suffix); reveal(selector)
        combo = next(item for item in visual(selector) if 'PixelComboBox' in item.metaObject().className())
        expected = source[names_key][source[index_key]]
        assert selector.property('currentIndex') == combo.property('currentIndex') == source[index_key], (side, suffix, source)
        assert selector.property('currentText') == combo.property('currentText') == combo.property('displayText') == expected
        visible_label(combo, expected)
    return {key: source[key] for key in ('cost_index', 'candidate_index', 'experiment_id', 'candidate_id')}
def check_view_selection(index):
    selector = find('intradaySavedComparisonView'); reveal(selector)
    combo = next(item for item in visual(selector) if 'PixelComboBox' in item.metaObject().className())
    key = ('quant.saved_strategy_metrics', 'quant.saved_benchmark_metrics', 'quant.saved_config_differences', 'quant.saved_basis_checks')[index]
    expected = session.i18n.catalog[key]
    assert controller.viewIndex == selector.property('currentIndex') == combo.property('currentIndex') == index
    assert selector.property('currentText') == combo.property('currentText') == combo.property('displayText') == expected
    visible_label(combo, expected)
def compare_visible_selections():
    expected = [check_source_selection(side) for side in ('Left', 'Right')]
    click('intradaySavedCompareButton'); complete()
    for captured, selected in zip(controller.boundSources, expected, strict=True):
        assert all(captured[key] == value for key, value in selected.items()), (captured, selected)
    return expected
click('quantIntradayTab', False)
click('intradaySavedComparisonTab', False)
assert not find('intradaySavedCompareButton').property('enabled')
open_file('Left', a_path)
open_file('Right', b_path)
choose('intradaySavedLeftCost', 1)
choose('intradaySavedLeftCandidate', 2)
choose('intradaySavedRightCost', 0)
choose('intradaySavedRightCandidate', 3)
click('intradaySavedCompareButton'); complete()
bound, recorded = controller.boundSources, canonical_json(controller._result)
assert [(row['cost_index'], row['candidate_index']) for row in bound] == [(1, 2), (0, 3)]
assert [row['name'] for row in bound] == ['Saved A', 'Saved B']
assert controller.comparisonNotice == 'COMPARABLE_DEV' and controller._result['delta_allowed']
for side, path in (('A', a_path), ('B', b_path)):
    identity = find('intradaySavedBound' + side + 'Identity')
    reveal(identity)
    assert str(path) in identity.property('text') and not identity.property('truncated')
    assert bound[0 if side == 'A' else 1]['experiment_id'] in identity.property('text')
assert window.grabWindow().save(str(root / 'saved-ab-sources.png'))
for language in ('en', 'zh-CN'):
    assert session.i18n.setLanguage(language)
    choose('intradaySavedComparisonView', 0)
    assert controller.leftSource['cost_index'] == 1 and controller.leftSource['candidate_index'] == 2
    assert controller.rightSource['candidate_index'] == 3 and controller.boundSources == bound
    table, header = find('intradaySavedComparisonTable'), find('intradaySavedComparisonTableHeader')
    flick = find('intradaySavedComparisonScroll').property('contentItem')
    flick.setProperty('contentY', max(0, flick.property('contentHeight') - flick.height()))
    QTest.qWait(60)
    assert table.height() >= 220
    viewport = next(item for item in visual(table) if item.metaObject().className().startswith('QQuickTableView'))
    assert viewport.height() >= 120
    viewport.setProperty('contentY', max(0, viewport.property('contentHeight') - viewport.height()))
    viewport.setProperty('contentX', 0)
    QTest.qWait(80)
    rows = {row[0]: row for row in controller._rows}
    assert rows['mae'][1].endswith('%') and rows['mae'][1] != '0.00%' and float(rows['mae'][1][:-1]) > 0
    visible_label(viewport, rows['mae'][1])
    visible_label(viewport, rows['r2'][1])
    visible_label(header, session.i18n.columnLabel('compare_left_unit'))
    assert window.grabWindow().save(str(root / ('saved-ab-values-' + language + '.png')))
    viewport.setProperty('contentX', min(5 * 145, max(0, viewport.property('contentWidth') - viewport.width())))
    QTest.qWait(80)
    visible_label(header, session.i18n.columnLabel('compare_delta_unit'))
    visible_label(viewport, session.i18n.catalog['comparison.PERCENTAGE_POINTS'])
    assert window.grabWindow().save(str(root / ('saved-ab-units-' + language + '.png')))
    choose('intradaySavedComparisonView', 2)
    assert find('intradaySavedConfigurationDifferences').property('visible')
    assert not table.property('visible')
    assert any(row['key'] == 'execution_policy.commission_bps' and row['left'] == '10.0' and row['right'] == '0.0'
        for row in controller.configurationRows)
    choose('intradaySavedComparisonView', 3)
    assert controller.tableModel.totalRows == 26
    basis = {row[0]: row for row in controller._rows}
    assert ' · ' in basis['raw_prices'][1] and len(basis['raw_prices'][1]) < 32
    assert canonical_json(controller._result) == recorded
choose('intradaySavedLeftCost', 0)
choose('intradaySavedLeftCandidate', 0)
open_file('Right', test_path)
assert controller.rightSource['is_test']
assert not find('intradaySavedRightCost').property('enabled') and not find('intradaySavedRightCandidate').property('enabled')
assert controller.boundSources == bound and canonical_json(controller._result) == recorded
assert controller.comparisonNotice == 'COMPARABLE_DEV'
assert 'Saved B' in find('intradaySavedBoundBSelection').property('text')
invalid_path = root / 'invalid.json'
invalid_path.write_text('not valid JSON', encoding='utf-8')
open_file('Left', invalid_path, 'FAILED')
assert controller.boundSources == bound and canonical_json(controller._result) == recorded
click('intradaySavedCompareButton'); complete()
assert controller.comparisonNotice == 'TEST_DESCRIPTIVE_ONLY'
for view in (0, 1):
    choose('intradaySavedComparisonView', view)
    assert all(row[5] == '—' and row[9] == 'TEST_DESCRIPTIVE_ONLY' for row in controller._rows)
assert controller.boundSources[1]['evaluation_mode'] == 'INTRADAY_TEST'
reveal(find('intradaySavedComparisonNotice'))
assert window.grabWindow().save(str(root / 'saved-ab-test-descriptive.png'))
open_file('Left', ordinary_path)
open_file('Right', partial_path)
choose('intradaySavedLeftCandidate', 1)
choose('intradaySavedRightCandidate', 1)
click('intradaySavedCompareButton'); complete()
choose('intradaySavedComparisonView', 0)
assert [(row['side'], row['part']) for row in controller.performanceWarnings] == [('B', 'candidate')]
warning = find('intradaySavedWarningBcandidate'); reveal(warning)
assert warning.property('visible') and not warning.property('truncated')
rows = {row[0]: row for row in controller._rows}
assert rows['win_rate'][3] == '—' and rows['win_rate'][8] == 'RECORDED_CASH_RECONCILIATION_FAILED'
assert rows['total_return'][3] != '—'
assert controller._result['right']['benchmark_performance']['status'] == 'AVAILABLE'
selector = find('intradaySavedComparisonView'); reveal(selector)
combo = next(item for item in visual(selector) if 'PixelComboBox' in item.metaObject().className())
expected = session.i18n.catalog['quant.saved_strategy_metrics']
QTest.qWait(80); app.processEvents()
assert controller.viewIndex == selector.property('currentIndex') == combo.property('currentIndex') == 0
assert selector.property('currentText') == combo.property('currentText') == combo.property('displayText') == expected
visible_label(combo, expected)
print('SAVED_AB_FINAL_SELECTOR', json.dumps({'controller_index': controller.viewIndex,
    'visible_index': selector.property('currentIndex'), 'text': combo.property('currentText')}, ensure_ascii=True))
assert window.grabWindow().save(str(root / 'saved-ab-partial-unavailable.png'))
for side, original, reopened, candidate in (('Left', a_path, b_path, 2), ('Right', b_path, a_path, 3)):
    open_file(side, original)
    choose('intradaySaved' + side + 'Cost', 1)
    choose('intradaySaved' + side + 'Candidate', candidate)
    before = check_source_selection(side)
    assert (before['cost_index'], before['candidate_index']) == (1, candidate)
    bound_before, result_before = controller.boundSources, canonical_json(controller._result)
    open_file(side, reopened)
    after = check_source_selection(side)
    assert (after['cost_index'], after['candidate_index']) == (0, 0)
    assert before['experiment_id'] != after['experiment_id']
    assert controller.boundSources == bound_before and canonical_json(controller._result) == result_before
    print('SAVED_AB_REOPEN_SELECTION', json.dumps({'side': side, 'before': before, 'after': after}, ensure_ascii=True))
assert [(row['cost_index'], row['candidate_index']) for row in compare_visible_selections()] == [(0, 0), (0, 0)]
for side, candidate in (('Left', 2), ('Right', 3)):
    choose('intradaySaved' + side + 'Cost', 1)
    choose('intradaySaved' + side + 'Candidate', candidate)
for language in ('en', 'zh-CN'):
    choose('intradaySavedComparisonView', 2)
    assert session.i18n.setLanguage(language)
    QTest.qWait(50)
    for side in ('Left', 'Right'):
        check_source_selection(side)
    check_view_selection(2)
    assert controller.selectView(3)
    check_view_selection(3)
    reveal(find('intradaySavedBoundASelection'))
    assert window.grabWindow().save(str(root / ('saved-ab-binding-language-' + language + '.png')))
assert [(row['cost_index'], row['candidate_index']) for row in compare_visible_selections()] == [(1, 2), (1, 3)]
assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in originals.items())
assert 'REPLAY_MATCH' not in canonical_json(controller._result).decode()
assert session.runtime.backend_if_initialized is None and session.shutdown()
print('REAL_SAVED_INTRADAY_COMPARISON_OK')
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), *(str(path) for path in paths)],
        cwd=ROOT, env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software", "PYTHONPATH": str(ROOT / "src")},
        capture_output=True, text=True, timeout=360)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "REAL_SAVED_INTRADAY_COMPARISON_OK" in result.stdout
    assert "ReferenceError" not in result.stderr and "TypeError" not in result.stderr


def test_actual_qml_execution_scenarios_export_freeze_and_small_window(research_case, tmp_path):
    data, _, _ = research_case
    (tmp_path / "settings.yaml").write_text("storage:\n  root_dir: ./data\n")
    script = r'''
import sys, time, json
from pathlib import Path
from PySide6.QtCore import QObject, QUrl, Qt, QEvent, QMetaObject
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from market_vault.application import build_application_context
from market_vault.desktop.bootstrap import create_qml_application_session
from market_vault.desktop.preferences import DesktopPreferenceStore
root, data_path = Path(sys.argv[1]), Path(sys.argv[2])
QQuickStyle.setStyle('Basic')
app = QGuiApplication([])
engine = QQmlApplicationEngine()
session = create_qml_application_session(build_application_context(root / 'settings.yaml'), engine,
    preference_store=DesktopPreferenceStore(root=root / 'preferences'))
engine.load(QUrl.fromLocalFile(str(Path.cwd() / 'src/market_vault/desktop/qml/Main.qml')))
assert engine.rootObjects()
window = engine.rootObjects()[0]
window.setWidth(1024); window.setHeight(600)
owner = session.context_properties['quantResearchController']
development, final = owner.intradayResearchController, owner.intradayFinalController
assert session.shell.selectPage('quant_research')
def find(name):
    obj = window.findChild(QObject, name)
    if obj is None:
        pending = [window.contentItem()]
        while pending:
            item = pending.pop()
            if item.objectName() == name: obj = item; break
            pending.extend(item.childItems())
    assert obj is not None, name
    return obj
def reveal(item, scroll_name):
    if scroll_name is None: return
    flick = find(scroll_name).property('contentItem')
    rect = item.mapRectToItem(flick, item.boundingRect())
    dy = rect.top() if rect.top() < 0 else max(0, rect.bottom() - flick.height())
    limit = max(0, flick.property('contentHeight') - flick.height())
    flick.setProperty('contentY', min(max(0, flick.property('contentY') + dy), limit))
    QTest.qWait(30)
    rect = item.mapRectToItem(flick, item.boundingRect())
    assert rect.left() >= -1 and rect.right() <= flick.width() + 1, (item.objectName(), rect, flick.width())
    assert rect.top() >= -1 and rect.bottom() <= flick.height() + 1, (item.objectName(), rect, flick.height())
def click(name, scroll_name=None):
    item = find(name)
    app.processEvents(); reveal(item, scroll_name)
    assert item.property('visible') and item.property('enabled'), name
    point = item.mapToScene(item.boundingRect().center()).toPoint()
    assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), (name, point)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.qWait(30)
def nested(item, kind):
    if kind in item.metaObject().className(): return item
    return next(child for child in item.findChildren(QObject) if kind in child.metaObject().className())
def fill(name, value, scroll_name=None):
    item = find(name); reveal(item, scroll_name)
    window.requestActivate(); QTest.qWait(20)
    edit = nested(item, 'PixelTextField')
    edit.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClick(window, Qt.Key_Backspace)
    for char in value:
        QGuiApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, ord(char.upper()), Qt.NoModifier, char))
    app.processEvents()
    assert item.property('text') == value, (name, item.property('text'))
def choose(name, index, scroll_name=None):
    item = find(name); reveal(item, scroll_name)
    combo = nested(item, 'PixelComboBox')
    window.requestActivate(); QTest.qWait(20)
    combo.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_Home)
    for _ in range(index): QTest.keyClick(window, Qt.Key_Down)
    QTest.qWait(30)
    assert item.property('currentIndex') == index, (name, item.property('currentIndex'))
def complete(target=development):
    deadline = time.monotonic() + 150
    while target.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    app.processEvents()
    assert not target.busy and target.status == 'SUCCESS', (target.status, target.error)
def file_selected(name, path):
    dialog = find(name)
    assert dialog.setProperty('selectedFile', QUrl.fromLocalFile(str(path)))
    assert QMetaObject.invokeMethod(dialog, 'accepted', Qt.DirectConnection)
    QMetaObject.invokeMethod(dialog, 'close', Qt.DirectConnection)
    complete()
panel_scroll = 'intradayResearchScroll'
editor_scroll = 'intradayScenariosEditorScroll'
click('quantIntradayTab')
fill('intradayDataPath', str(data_path))
click('intradayInspectButton'); complete(owner)
click('intradayComparisonTab')
click('intradayOpenScenariosButton', panel_scroll)
assert find('intradayResearchCommission').property('text') == ''
assert find('intradayResearchSlippage').property('text') == ''
fill('intradayScenarioName', 'Baseline', editor_scroll)
fill('intradayScenarioCommission', '10', editor_scroll)
fill('intradayScenarioSlippage', '5', editor_scroll)
click('intradayScenarioAdd', editor_scroll)
fill('intradayScenarioName', 'Shorter', editor_scroll)
for name, value in (('EntryDelay', '30'), ('StopNew', '45'), ('Flatten', '10'),
                    ('MaxHold', '6'), ('Commission', '20'), ('Slippage', '7')):
    fill('intradayScenario' + name, value, editor_scroll)
assert '2 × 3 = 6' in find('intradayScenariosEvaluationCount').property('text')
assert session.i18n.setLanguage('zh-CN'); assert session.i18n.setLanguage('en')
assert find('intradayScenarioMaxHold').property('text') == '6'
choose('intradayScenarioEditorChoice', 0, editor_scroll)
assert find('intradayScenarioName').property('text') == 'Baseline'
choose('intradayScenarioEditorChoice', 1, editor_scroll)
assert find('intradayScenarioMaxHold').property('text') == '6'
assert window.grabWindow().save(str(root / 'execution-scenarios-editor.png'))
click('intradayScenariosRun'); complete()
assert development.scenariosLoaded and development.scenarioNames == ['Baseline', 'Shorter']
assert development.tableModel.totalRows == 6 and development.resultSummary['evaluation_count'] == '6'
assert not final.canFreeze and development.experimentPath == ''
assert find('intradayResearchCommission').property('text') == ''
assert find('intradayResearchSlippage').property('text') == ''
choose('intradayResearchScenario', 1, panel_scroll)
choose('intradayResearchCandidate', 2, panel_scroll)
assert development.scenarioIndex == 1 and development.candidateIndex == 2
click('intradayResearchSettingsButton', panel_scroll)
fill('intradayResearchMaxHold', '99', 'intradaySettingsScroll')
click('intradayResearchSettingsDone', 'intradaySettingsScroll')
all_path, child_path = root / 'all-scenarios.json', root / 'selected-scenario.json'
click('intradayExperimentSaveButton', panel_scroll)
file_selected('intradayExperimentSaveDialog', all_path)
record = json.loads(all_path.read_bytes())
assert record['evaluation_mode'] == 'INTRADAY_EXECUTION_SCENARIOS'
assert len(record['report']['scenarios']) == 2
assert not final.canFreeze and development.collectionPath == str(all_path)
assert development.experimentPath == ''
click('intradayExperimentReplayButton', panel_scroll); complete()
assert development.collectionProof == 'REPLAY_MATCH'
assert find('intradayResearchMaxHold').property('text') == '99'
choose('intradayResearchView', 7, panel_scroll)
assert development.tableModel.totalRows == 17
click('intradayScenarioExportButton', panel_scroll)
file_selected('intradayScenarioExportDialog', child_path)
child = json.loads(child_path.read_bytes())
assert child == record['report']['scenarios'][1]['experiment']
assert child['plan']['execution']['max_hold_bars'] == 6
assert final.canFreeze and development.experimentPath == str(child_path)
choose('intradayResearchScenario', 0, panel_scroll)
assert not final.canFreeze and development.experimentPath == ''
choose('intradayResearchScenario', 1, panel_scroll)
assert final.canFreeze and development.candidateIndex == 2
click('intradayFinalTab')
click('intradayFreezeButton', 'intradayFinalScroll'); complete(final)
assert final.frozenCandidate['strategy']['name'] == 'Ridge'
assert final.frozenCandidate['execution_policy'] == child['plan']['execution']
click('intradayRunTestButton', 'intradayFinalScroll'); complete(final)
assert final._test_root['report']['execution_policy'] == child['plan']['execution']
assert len(final._test_root['report']['predictions']) == 444
click('intradayComparisonTab')
click('intradayExperimentOpenButton', panel_scroll)
file_selected('intradayExperimentOpenDialog', all_path)
assert development.collectionProof == 'RECORDED' and development.scenarioIndex == 0
assert not final.canFreeze and find('intradayResearchMaxHold').property('text') == '12'
choose('intradayResearchScenario', 1, panel_scroll)
assert not final.canFreeze  # Open does not invent child export paths
click('intradayOpenScenariosButton', panel_scroll)
choose('intradayScenarioEditorChoice', 1, editor_scroll)
assert find('intradayScenarioMaxHold').property('text') == '6'
click('intradayScenariosKeep')
choose('intradayResearchCandidate', 2, panel_scroll)
for language in ('en', 'zh-CN'):
    assert session.i18n.setLanguage(language)
    choose('intradayResearchView', 0, panel_scroll)
    table = find('intradayResearchTable')
    flick = find(panel_scroll).property('contentItem')
    flick.setProperty('contentY', max(0, flick.property('contentHeight') - flick.height()))
    QTest.qWait(80)
    assert table.height() >= 120
    header = find('intradayResearchTableHeader')
    viewport = next(item for item in table.findChildren(QObject)
        if item.metaObject().className().startswith('QQuickTableView') and item.property('height') is not None)
    assert viewport.height() >= 32
    assert header.mapToScene(header.boundingRect().topLeft()).y() >= find(panel_scroll).mapToScene(find(panel_scroll).boundingRect().topLeft()).y()
    assert window.grabWindow().save(str(root / ('execution-scenarios-' + language + '.png')))
    viewport.setProperty('contentX', min(9 * 145, max(0, viewport.property('contentWidth') - viewport.width())))
    QTest.qWait(80)
    caption = session.i18n.columnLabel('scenario_return_change')
    pending, labels = [header], []
    while pending:
        item = pending.pop()
        if item.property('text') == caption: labels.append(item)
        pending.extend(item.childItems())
    assert any(label.property('visible') and not label.property('truncated')
        and label.mapRectToItem(header, label.boundingRect()).left() >= 0
        and label.mapRectToItem(header, label.boundingRect()).right() <= header.width() for label in labels), caption
    assert window.grabWindow().save(str(root / ('execution-scenarios-units-' + language + '.png')))
    choose('intradayResearchView', 7, panel_scroll)
    assert development.tableModel.totalRows == 17 and table.height() >= 170
assert development._collection_content == all_path.read_bytes()
assert development.collectionProof == 'RECORDED'
assert session.runtime.backend_if_initialized is None and session.shutdown()
print('REAL_EXECUTION_SCENARIOS_FREEZE_WORKFLOW_OK')
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(data.path)],
        cwd=ROOT, env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software", "PYTHONPATH": str(ROOT / "src")},
        capture_output=True, text=True, timeout=360)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "REAL_EXECUTION_SCENARIOS_FREEZE_WORKFLOW_OK" in result.stdout
    assert "ReferenceError" not in result.stderr and "TypeError" not in result.stderr


def test_risk_views_keep_selected_accounts_and_offline_proofs(qt_app, saved_comparison_diagnostics,
        intraday_experiment, final_case, tmp_path, monkeypatch):
    from market_vault.research import intraday_risk_diagnostics as diagnostics
    from market_vault.desktop.intraday_research import risk_value
    calls = []
    analyze = diagnostics.analyze_intraday_risk_diagnostics

    def captured(snapshot, **indices):
        calls.append((snapshot.experiment_id, indices))
        return analyze(snapshot, **indices)

    def forbidden(*args, **kwargs):
        raise AssertionError("Risk display must not load, fit, or execute")

    monkeypatch.setattr(diagnostics, "analyze_intraday_risk_diagnostics", captured)
    for name in ("load_intraday_dataset", "fit_ridge_rows", "run_intraday_execution"):
        monkeypatch.setattr(research, name, forbidden)
    backend_calls = []
    runtime, runner = _runtime(tmp_path, backend_calls)
    owner = QuantResearchController(runtime)
    development, controller = owner.intradayResearchController, owner.intradayFinalController
    development._apply(saved_comparison_diagnostics, path=str(tmp_path / "diagnostic.json"), opened=True)
    assert development.selectCandidate(6)  # cost 1, candidate 2, not the first result
    source = development.selection_source()
    assert development.selectView(11)
    report = development._risk_report
    assert (report["cost_index"], report["candidate_index"], report["candidate_id"]) == (
        1, 2, source["candidate_id"])
    before = (development._content, development.experimentPath, development.restoredPlan,
              development.restoreRevision, development.resultSummary)
    for view in range(11, 16):
        assert development.selectView(view)
        assert {row[0] for row in development._rows} == {"STRATEGY", "BENCHMARK"}
    assert len(calls) == 1 and development._risk_report is report
    assert (development._content, development.experimentPath, development.restoredPlan,
            development.restoreRevision, development.resultSummary) == before
    assert development.selectCandidate(4)
    assert development._risk_report["candidate_id"] != report["candidate_id"]
    assert development._risk_report["candidate_index"] == 0

    development._apply(intraday_experiment, opened=True)
    assert development.selectCandidate(0) and development.selectView(13)
    rows = {(row[0], row[1], row[2]): row for row in development._rows}
    assert rows["STRATEGY", "TRADE_RETURNS", "sample_count"][3:5] == ("0", "COUNT")
    assert rows["STRATEGY", "TRADE_RETURNS", "p05"][3:] == ("—", "RATIO", "NO_TRADES")
    assert rows["STRATEGY", "DAILY_RETURNS", "p05"][3:] == ("0%", "RATIO", "")
    assert rows["BENCHMARK", "TRADE_RETURNS", "sample_count"][3] != "0"
    assert risk_value(1e-9, "RATIO") != "0%"
    assert "Infinity" not in risk_value(1e308, "RATIO")

    partial = _unavailable_saved_candidate(intraday_experiment)
    development._apply(partial, opened=True)
    assert development.selectCandidate(1) and development.selectView(11)
    assert development._risk_report["strategy_diagnostics"]["status"] == "UNAVAILABLE"
    assert development._risk_report["benchmark_diagnostics"]["status"] == "AVAILABLE"
    assert next(row for row in development._rows if row[0] == "STRATEGY")[-1] == "RECORDED_CASH_RECONCILIATION_FAILED"
    assert any(row[0] == "BENCHMARK" and row[2] == "maximum_drawdown" for row in development._rows)

    controller._apply_test(final_case[1], opened=True)
    bound_test = (controller._test_content, controller._selection_content, controller.resultSummary)
    for view in range(10, 15):
        assert controller.selectView(view)
        assert {row[0] for row in controller._rows} == {"STRATEGY", "BENCHMARK"}
    assert controller._rows == (("STRATEGY", "fold_diagnostics", "NOT_APPLICABLE"),
                               ("BENCHMARK", "fold_diagnostics", "NOT_APPLICABLE"))
    assert (controller._test_content, controller._selection_content, controller.resultSummary) == bound_test
    assert development.resultSummary["intraday_verification"] == "RECORDED"
    assert controller.resultSummary["intraday_test_proof"] == "RECORDED"
    assert not backend_calls and not runner.names and runtime.backend_if_initialized is None
    assert runtime.shutdown()


def test_actual_qml_offline_performance_views_in_both_languages(intraday_experiment, final_case,
        saved_comparison_diagnostics, tmp_path):
    source, test_path = tmp_path / "development.json", tmp_path / "test.json"
    write_strategy_experiment(intraday_experiment, path=source)
    write_strategy_experiment(final_case[1], path=test_path)
    diagnostic_path, partial_path = tmp_path / "diagnostic.json", tmp_path / "partial.json"
    write_strategy_experiment(saved_comparison_diagnostics, path=diagnostic_path)
    write_strategy_experiment(_unavailable_saved_candidate(intraday_experiment), path=partial_path)
    (tmp_path / "settings.yaml").write_text("storage:\n  root_dir: ./data\n")
    script = r'''
import sys, time
from pathlib import Path
from PySide6.QtCore import QObject, QUrl, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from market_vault.application import build_application_context
from market_vault.desktop.bootstrap import create_qml_application_session
from market_vault.desktop.preferences import DesktopPreferenceStore
root, source, test_path, diagnostic_path, partial_path = map(Path, sys.argv[1:])
QQuickStyle.setStyle('Basic')
app = QGuiApplication([])
engine = QQmlApplicationEngine()
session = create_qml_application_session(build_application_context(root / 'settings.yaml'), engine,
    preference_store=DesktopPreferenceStore(root=root / 'preferences'))
engine.load(QUrl.fromLocalFile(str(Path.cwd() / 'src/market_vault/desktop/qml/Main.qml')))
assert engine.rootObjects()
window = engine.rootObjects()[0]
window.setWidth(1024); window.setHeight(600)
owner = session.context_properties['quantResearchController']
development, final = owner.intradayResearchController, owner.intradayFinalController
assert session.shell.selectPage('quant_research')
def visual():
    pending = [window.contentItem()]
    while pending:
        item = pending.pop()
        yield item
        pending.extend(item.childItems())
def find(name):
    result = window.findChild(QObject, name)
    if result is None:
        result = next((item for item in visual() if item.objectName() == name), None)
    assert result is not None, name
    return result
def click(name):
    item = find(name)
    app.processEvents()
    assert item.isVisible() and item.isEnabled(), name
    point = item.mapToScene(item.boundingRect().center()).toPoint()
    assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), point
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.qWait(30)
def choose(name, index):
    item = find(name)
    combo = next(c for c in item.findChildren(QObject) if 'PixelComboBox' in c.metaObject().className())
    window.requestActivate(); QTest.qWait(20)
    combo.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_Home)
    for _ in range(index): QTest.keyClick(window, Qt.Key_Down)
    QTest.qWait(30)
    assert item.property('currentIndex') == index
def complete(controller):
    deadline = time.monotonic() + 30
    while controller.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    assert controller.status == 'SUCCESS', (controller.status, controller.error)
click('quantIntradayTab'); click('intradayComparisonTab')
assert development.openExperiment(str(source)); complete(development)
assert final.openTest(str(test_path)); complete(final)
before = (development._content, final._test_content)
for tab, controller, selector, first, table_name, day_count in (
    ('intradayComparisonTab', development, 'intradayResearchView', 7, 'intradayResearchTable', 10),
    ('intradayFinalTab', final, 'intradayTestView', 6, 'intradayTestTable', 6)):
    click(tab)
    for language, label in (('en', 'Trades'), ('zh-CN', '交易次数')):
        assert session.i18n.setLanguage(language)
        choose(selector, first)
        assert controller.tableModel.totalRows == 17
        QTest.qWait(80)
        table = find(table_name)
        assert table.height() >= 130, (tab, language, table.height())
        assert any(item.isVisible() and item.property('text') == label for item in visual()), (tab, language)
        assert window.grabWindow().save(str(root / (tab + '-' + language + '.png')))
        for offset in (1, 2, 3):
            choose(selector, first + offset)
            if offset == 3: assert controller.tableModel.totalRows == day_count
        choose(selector, first)
assert (development._content, final._test_content) == before

# Exercise the new diagnostics on the actual rendered pages and controls.
def descendants(parent):
    pending = [parent]
    while pending:
        item = pending.pop()
        yield item
        pending.extend(item.childItems())
def reveal(item, scroll_name):
    flick = find(scroll_name).property('contentItem')
    rect = item.mapRectToItem(flick, item.boundingRect())
    delta = rect.top() if rect.top() < 0 else max(0, rect.bottom() - flick.height())
    flick.setProperty('contentY', min(max(0, flick.property('contentY') + delta),
        max(0, flick.property('contentHeight') - flick.height())))
    QTest.qWait(30)
    rect = item.mapRectToItem(flick, item.boundingRect())
    assert rect.top() >= -1 and rect.bottom() <= flick.height() + 1, (item.objectName(), rect, flick.height())
def risk_choose(selector, index, scroll_name):
    reveal(find(selector), scroll_name)
    choose(selector, index)
def visible_label(parent, caption):
    for label in descendants(parent):
        if label.property('text') != caption or not label.isVisible() or label.property('truncated'): continue
        rect = label.mapRectToItem(parent, label.boundingRect())
        if rect.left() >= 0 and rect.right() <= parent.width() and rect.top() >= 0 and rect.bottom() <= parent.height(): return label
    raise AssertionError(('visible complete label', caption))
def visible_table(table_name, scroll_name):
    table = find(table_name)
    reveal(table, scroll_name)
    assert table.height() >= 170
    viewport = next(item for item in descendants(table) if item.metaObject().className().startswith('QQuickTableView'))
    assert viewport.height() >= 70
    viewport.setProperty('contentX', 0); viewport.setProperty('contentY', 0)
    QTest.qWait(60)
    return table, viewport
def forbidden(*args, **kwargs):
    raise AssertionError('Risk view cannot load sources, fit, execute, or rewrite records')
from market_vault.research import intraday_research as research
research.load_intraday_dataset = research.fit_ridge_rows = research.run_intraday_execution = forbidden
content_before = {path: path.read_bytes() for path in (source, test_path, diagnostic_path, partial_path)}
click('intradayComparisonTab')
assert development.openExperiment(str(diagnostic_path)); complete(development)
risk_choose('intradayResearchCandidate', 6, 'intradayResearchScroll')
selected = development.selection_source()
assert (selected['cost_index'], selected['candidate_index']) == (1, 2)
view_keys = ('quant.risk_summary', 'quant.risk_drawdowns', 'quant.risk_distributions', 'quant.risk_concentration', 'quant.risk_folds')
for tab, controller, selector, first, table_name, scroll_name in (
    ('intradayComparisonTab', development, 'intradayResearchView', 11, 'intradayResearchTable', 'intradayResearchScroll'),
    ('intradayFinalTab', final, 'intradayTestView', 10, 'intradayTestTable', 'intradayFinalScroll')):
    click(tab)
    bound = (controller._content, controller.resultSummary) if controller is development else (
        controller._test_content, controller._selection_content, controller.resultSummary)
    for language in ('en', 'zh-CN'):
        previous_view = controller._view_index
        assert session.i18n.setLanguage(language)
        assert find(selector).property('currentIndex') == previous_view
        for offset, view_key in enumerate(view_keys):
            risk_choose(selector, first + offset, scroll_name)
            assert controller._view_index == first + offset
            assert find(selector).property('currentText') == session.i18n.catalog[view_key]
            assert {row[0] for row in controller._rows} == {'STRATEGY', 'BENCHMARK'}
            table, viewport = visible_table(table_name, scroll_name)
            visible_label(viewport, session.i18n.catalog['risk.STRATEGY'])
            if offset == 0:
                visible_label(viewport, session.i18n.catalog['risk.drawdown_episode_count'])
            if offset == 2:
                assert any(row[2] == 'p05' and row[4] == 'RATIO' for row in controller._rows)
                assert any(row[2] == 'sample_count' and row[4] == 'COUNT' for row in controller._rows)
                visible_label(viewport, session.i18n.catalog['risk.DAILY_RETURNS'])
            if offset == 4 and controller is final:
                assert all(row[-1] == 'NOT_APPLICABLE' for row in controller._rows)
                visible_label(viewport, 'Not applicable' if language == 'en' else '不适用')
            if offset in (0, 1, 4):
                assert window.grabWindow().save(str(root / (tab + '-risk-' + str(offset) + '-' + language + '.png')))
            viewport.setProperty('contentY', max(0, viewport.property('contentHeight') - viewport.height()))
            QTest.qWait(50)
            visible_label(viewport, session.i18n.catalog['risk.BENCHMARK'])
        current = (controller._content, controller.resultSummary) if controller is development else (
            controller._test_content, controller._selection_content, controller.resultSummary)
        assert current == bound
    if controller is development:
        assert controller._risk_report['candidate_id'] == selected['candidate_id']
        assert (controller._risk_report['cost_index'], controller._risk_report['candidate_index']) == (1, 2)

# Reopening same-shaped records and selecting another candidate must replace
# the derived identity while preserving the captured TEST and verification.
click('intradayComparisonTab')
assert development.openExperiment(str(source)); complete(development)
risk_choose('intradayResearchCandidate', 1, 'intradayResearchScroll')
risk_choose('intradayResearchView', 12, 'intradayResearchScroll')
assert development._risk_report['candidate_id'] == development.selection_source()['candidate_id']
assert development._risk_report['strategy_diagnostics']['status'] == 'AVAILABLE'
table, viewport = visible_table('intradayResearchTable', 'intradayResearchScroll')
assert any(row[2] == 'TROUGH' for row in development._rows)
assert any(row[2] in ('RECOVERY', 'UNRECOVERED') for row in development._rows)
if development.tableModel.hasNext:
    button = next(item for item in descendants(table) if 'PixelButton' in item.metaObject().className()
        and item.property('text') == session.i18n.catalog['common.next'])
    reveal(button, 'intradayResearchScroll')
    point = button.mapToScene(button.boundingRect().center()).toPoint()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point); QTest.qWait(50)
    assert development.tableModel.page == 2
    assert development.tableModel._page.rows == development._rows[100:200]
    assert window.grabWindow().save(str(root / 'development-risk-drawdown-page-2.png'))
risk_choose('intradayResearchCandidate', 0, 'intradayResearchScroll')
risk_choose('intradayResearchView', 13, 'intradayResearchScroll')
rows = {(row[0], row[1], row[2]): row for row in development._rows}
assert rows['STRATEGY', 'TRADE_RETURNS', 'p05'][3:] == ('—', 'RATIO', 'NO_TRADES')
assert rows['STRATEGY', 'DAILY_RETURNS', 'p05'][3:] == ('0%', 'RATIO', '')
assert development.openExperiment(str(partial_path)); complete(development)
risk_choose('intradayResearchCandidate', 1, 'intradayResearchScroll')
risk_choose('intradayResearchView', 11, 'intradayResearchScroll')
assert development._risk_report['strategy_diagnostics']['status'] == 'UNAVAILABLE'
assert development._risk_report['benchmark_diagnostics']['status'] == 'AVAILABLE'
assert next(row for row in development._rows if row[0] == 'STRATEGY')[-1] == 'RECORDED_CASH_RECONCILIATION_FAILED'
table, viewport = visible_table('intradayResearchTable', 'intradayResearchScroll')
visible_label(viewport, '现金对账不一致')
assert window.grabWindow().save(str(root / 'development-risk-partial-zh-CN.png'))
assert final._test_content == before[1]
assert all(path.read_bytes() == content for path, content in content_before.items())
assert development.resultSummary['intraday_verification'] == 'RECORDED'
assert final.resultSummary['intraday_test_proof'] == 'RECORDED'
assert session.runtime.backend_if_initialized is None
assert session.shutdown()
print('REAL_INTRADAY_RISK_VIEWS_OK')
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(source), str(test_path),
                             str(diagnostic_path), str(partial_path)],
                            cwd=ROOT, env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QSG_RHI_BACKEND": "software"},
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "REAL_INTRADAY_RISK_VIEWS_OK" in result.stdout


def test_controller_freezes_nonfirst_candidate_in_second_cost(qt_app, saved_comparison_diagnostics, tmp_path):
    snapshot = saved_comparison_diagnostics
    runtime, runner = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    development, controller = owner.intradayResearchController, owner.intradayFinalController
    development._apply(snapshot)
    assert development.saveExperiment(str(tmp_path / "diagnostics.json"))
    runtime._poll()
    assert development.selectCandidate(6)  # actual position (cost 1, candidate 2)
    assert controller.freezeSelected()
    runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    candidate = controller.frozenCandidate
    assert candidate["axis_values"] == [1000, 0]
    assert candidate["strategy"]["alpha"] == 1000
    assert candidate["execution_policy"]["commission_bps"] == 10
    assert candidate["execution_policy"]["slippage_bps"] == 5
    assert controller._selection_root["plan"]["selection"]["cost_index"] == 1
    assert controller._selection_root["plan"]["selection"]["candidate_index"] == 2
    assert not controller.testLoaded and runtime.backend_if_initialized is None and runtime.shutdown()


def test_controller_capture_immutable_selection_and_independent_proofs(qt_app, intraday_experiment, tmp_path, monkeypatch):
    runtime, runner = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    development, controller = owner.intradayResearchController, owner.intradayFinalController
    development._apply(intraday_experiment)
    assert not controller.canFreeze and not controller.freezeSelected()
    assert controller.status == "VALIDATION_ERROR"
    assert development.saveExperiment(str(tmp_path / "development.json"))
    runtime._poll()
    assert development.status == "SUCCESS" and controller.canFreeze
    assert development.selectCandidate(2)
    pending = []
    def deferred(name, operation):
        future = Future()
        pending.append((future, operation))
        return future
    with monkeypatch.context() as patch:
        patch.setattr(runner, "submit", deferred)
        assert controller.freezeSelected()
        assert controller.busy
        assert development.selectCandidate(0)
        future, operation = pending.pop()
        future.set_result(operation())
        runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    assert controller.frozenCandidate["strategy"]["name"] == "Ridge"
    frozen = controller._selection_content
    detached = controller.frozenCandidate
    detached["strategy"]["alpha"] = 10000
    assert controller.frozenCandidate["strategy"]["alpha"] == 1
    assert controller.saveSelection(str(tmp_path / "selection.json"))
    runtime._poll()
    assert (tmp_path / "selection.json").read_bytes() == frozen
    assert controller.runTest("", "")
    runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    assert controller._selection_content == frozen
    assert controller.selectView(4) and controller.tableModel.totalRows == 1
    assert controller.selectView(5) and controller.tableModel.totalRows == 444
    assert controller.changePage(1) and controller.tableModel.page == 2
    assert controller.saveTest(str(tmp_path / "test.json"))
    runtime._poll()
    previous = controller._test_content
    assert controller.tableModel.page == 2 and (tmp_path / "test.json").read_bytes() == previous
    assert controller.runTest(str(tmp_path / "missing-source.json"), "")
    runtime._poll()
    assert controller.status == "FAILED" and controller._test_content == previous
    assert controller.tableModel.page == 2
    assert controller.freezeSelected()
    runtime._poll()
    assert controller.status == "SUCCESS" and controller.frozenCandidate["strategy"]["name"] == "Flat"
    assert not controller.testLoaded and controller.testPath == "" and controller.tableModel.totalRows == 0
    assert (tmp_path / "test.json").read_bytes() == previous
    with monkeypatch.context() as patch:
        patch.setattr(final, "load_intraday_dataset", lambda *a: pytest.fail("Open TEST read data"))
        patch.setattr(final, "load_strategy_experiment", lambda *a: pytest.fail("Open TEST read development"))
        patch.setattr(research, "_fit", lambda *a: pytest.fail("Open TEST fitted"))
        assert controller.openTest(str(tmp_path / "test.json"))
        runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    assert controller.frozenCandidate["strategy"]["name"] == "Ridge"
    assert controller.selectionPath == "" and controller.testLoaded
    assert controller.resultSummary["intraday_selection_proof"] == "RECORDED"
    assert controller.resultSummary["intraday_test_proof"] == "RECORDED"
    assert controller.replaySelection(str(tmp_path / "missing-source.json"), "")
    runtime._poll()
    assert controller.resultSummary["intraday_selection_proof"] == "REPLAY_FAILED"
    assert controller.resultSummary["intraday_test_proof"] == "RECORDED"
    assert controller.replayTest(str(tmp_path / "missing-source.json"), "")
    runtime._poll()
    assert controller.resultSummary["intraday_test_proof"] == "REPLAY_FAILED"
    assert controller._test_content == previous
    assert controller.openSelection(str(tmp_path / "missing-selection.json"))
    runtime._poll()
    assert controller.status == "FAILED" and controller._test_content == previous
    assert runtime.backend_if_initialized is None and runtime.shutdown()


def test_actual_qml_freeze_save_open_final_test_and_two_file_replay(intraday_experiment, research_case, tmp_path):
    data, _, _ = research_case
    source = tmp_path / "development.json"
    write_strategy_experiment(intraday_experiment, path=source)
    (tmp_path / "settings.yaml").write_text("storage:\n  root_dir: ./data\n")
    script = r'''
import sys, time, json
from pathlib import Path
from PySide6.QtCore import QObject, QUrl, Qt, QEvent, QMetaObject
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from market_vault.application import build_application_context
from market_vault.desktop.bootstrap import create_qml_application_session
from market_vault.desktop.preferences import DesktopPreferenceStore
root, source, data_path = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
QQuickStyle.setStyle('Basic')
app = QGuiApplication([])
engine = QQmlApplicationEngine()
session = create_qml_application_session(build_application_context(root / 'settings.yaml'), engine,
    preference_store=DesktopPreferenceStore(root=root / 'preferences'))
engine.load(QUrl.fromLocalFile(str(Path.cwd() / 'src/market_vault/desktop/qml/Main.qml')))
assert engine.rootObjects()
window = engine.rootObjects()[0]
window.setWidth(1100); window.setHeight(700)
owner = session.context_properties['quantResearchController']
development, controller = owner.intradayResearchController, owner.intradayFinalController
assert session.shell.selectPage('quant_research')
def find(name):
    obj = window.findChild(QObject, name)
    if obj is None:
        pending = [window.contentItem()]
        while pending:
            candidate = pending.pop()
            if candidate.objectName() == name: obj = candidate; break
            pending.extend(candidate.childItems())
    assert obj is not None, name
    return obj
def click_obj(obj):
    app.processEvents()
    assert obj.property('visible') and obj.property('enabled'), obj.objectName()
    point = obj.mapToScene(obj.boundingRect().center()).toPoint()
    assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), point
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    app.processEvents()
def click(name): click_obj(find(name))
def nested(obj, kind):
    if kind in obj.metaObject().className(): return obj
    return next(c for c in obj.findChildren(QObject) if kind in c.metaObject().className())
def choose(name, index):
    obj = find(name)
    combo = nested(obj, 'PixelComboBox')
    window.requestActivate(); QTest.qWait(30)
    combo.forceActiveFocus(); app.processEvents()
    QTest.keyClick(window, Qt.Key_Home)
    for _ in range(index): QTest.keyClick(window, Qt.Key_Down)
    app.processEvents()
    assert obj.property('currentIndex') == index, (name, obj.property('currentIndex'))
def fill(name, text):
    obj = find(name)
    window.requestActivate(); QTest.qWait(30)
    edit = nested(obj, 'PixelTextField')
    edit.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
    for ch in text:
        QGuiApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, ord(ch.upper()), Qt.NoModifier, ch))
    app.processEvents()
    assert obj.property('text') == text, (name, obj.property('text'))
def complete(target=controller):
    deadline = time.monotonic() + 150
    while target.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    app.processEvents()
    assert not target.busy and target.status == 'SUCCESS', (target.status, target.error)
def file_selected(name, path, target=controller):
    dialog = find(name)
    assert dialog.setProperty('selectedFile', QUrl.fromLocalFile(str(path)))
    assert QMetaObject.invokeMethod(dialog, 'accepted', Qt.DirectConnection)
    QMetaObject.invokeMethod(dialog, 'close', Qt.DirectConnection)
    complete(target)
click('quantIntradayTab'); click('intradayComparisonTab')
click('intradayExperimentOpenButton')
file_selected('intradayExperimentOpenDialog', source, development)
assert not owner.intradayLoaded
click('intradayFinalTab'); QTest.qWait(50)
choose('intradayFinalCandidate', 2)
click('intradayFreezeButton'); complete()
frozen = controller._selection_content
assert controller.frozenCandidate['strategy']['name'] == 'Ridge'
choose('intradayFinalCandidate', 0)
assert controller._selection_content == frozen
saved_selection, saved_test = root / 'selection.json', root / 'test.json'
click('intradaySelectionSaveButton'); file_selected('intradaySelectionSaveDialog', saved_selection)
click('intradaySelectionOpenButton'); file_selected('intradaySelectionOpenDialog', saved_selection)
assert controller.resultSummary['intraday_selection_proof'] == 'RECORDED'
assert not controller.testLoaded and controller._selection_content == frozen
click('intradayComparisonTab')
click('intradayResearchSettingsButton'); QTest.qWait(30)
fill('intradayResearchMaxHold', '9')
click('intradayResearchSettingsDone')
click('intradayFinalTab')
click('intradayRunTestButton'); complete()
assert controller._test_root['report']['execution_policy']['max_hold_bars'] == 12
assert controller._test_root['report']['model']['alpha'] == 1
assert controller.resultSummary['intraday_test_proof'] == 'COMPUTED'
choose('intradayTestView', 4)
assert controller.tableModel.totalRows == 1
choose('intradayTestView', 5)
assert controller.tableModel.totalRows == 444
choose('intradayTestView', 2)
assert controller.tableModel.totalRows == 936
table = find('intradayTestTable')
assert table.height() >= 170, table.height()
next_button = next(obj for obj in table.findChildren(QObject) if obj.property('glyph') == 'next' and obj.metaObject().indexOfSignal('clicked()') >= 0)
click_obj(next_button)
assert controller.tableModel.page == 2
click('intradayTestSaveButton'); file_selected('intradayTestSaveDialog', saved_test)
original = saved_test.read_bytes()
assert controller.tableModel.page == 2
click('intradayTestOpenButton'); file_selected('intradayTestOpenDialog', saved_test)
assert controller.selectionPath == '' and controller.frozenCandidate['strategy']['name'] == 'Ridge'
assert controller.resultSummary['intraday_test_proof'] == 'RECORDED'
# Opened proof labels are longer than freshly computed labels. At the actual
# supported minimum, scroll the panel instead of crushing its only metrics row.
for language in ('en', 'zh-CN'):
    assert session.i18n.setLanguage(language)
    for width, height in ((1000, 650), (1024, 600), (1100, 700)):
        window.setWidth(width); window.setHeight(height)
        choose('intradayTestView', 0); QTest.qWait(100)
        scroll = find('intradayFinalScroll')
        flickable = scroll.property('contentItem')
        assert table.height() >= 120, (language, width, height, table.height())
        bottom = max(0, flickable.property('contentHeight') - flickable.height())
        assert flickable.setProperty('contentY', bottom)
        QTest.qWait(50)
        header = find('intradayTestTableHeader')
        viewport = next(obj for obj in table.findChildren(QObject)
                        if obj.metaObject().className().startswith('QQuickTableView') and obj.property('height') is not None)
        assert viewport.height() >= 32, (language, viewport.height())
        header_top = header.mapToScene(header.boundingRect().topLeft()).y()
        header_bottom = header.mapToScene(header.boundingRect().bottomLeft()).y()
        row_top = viewport.mapToScene(viewport.boundingRect().topLeft()).y()
        scroll_top = scroll.mapToScene(scroll.boundingRect().topLeft()).y()
        scroll_bottom = scroll.mapToScene(scroll.boundingRect().bottomLeft()).y()
        assert scroll_top <= header_top < header_bottom <= row_top + 1
        assert row_top + 32 <= scroll_bottom
        footer_top = next_button.mapToScene(next_button.boundingRect().topLeft()).y()
        assert row_top + 32 <= footer_top < scroll_bottom
        assert window.grabWindow().save(str(root / f'final-{language}-{width}-{height}.png'))
        choose('intradayTestView', 2); QTest.qWait(50)
        assert table.height() >= 170
window.setWidth(1100); window.setHeight(700)
assert session.i18n.setLanguage('en')
choose('intradayTestView', 2)
assert flickable.setProperty('contentY', 0)
QTest.qWait(50)
# Relocate this test's private source file; the shared Q5/Canonical fixture stays
# intact. Both override values are exercised through visible file dialogs.
moved_source, moved_data = root / 'moved-development.json', root / 'moved-data.json'
source.rename(moved_source)
moved_data.write_bytes(data_path.read_bytes())
click('intradayFinalLocationsButton'); QTest.qWait(30)
click('intradayFinalSourceBrowse'); file_selected('intradayFinalSourceDialog', moved_source)
click('intradayFinalDataBrowse'); file_selected('intradayFinalDataDialog', moved_data)
assert find('intradayFinalSourcePath').property('text').endswith('/moved-development.json')
assert find('intradayFinalDataPath').property('text').endswith('/moved-data.json')
assert window.grabWindow().save(str(root / 'intraday-final-locations.png'))
click('intradayFinalLocationsDone')
click('intradayTestReplayButton'); complete()
assert controller.resultSummary['intraday_test_proof'] == 'REPLAY_MATCH'
assert controller._test_content == original
assert controller.resultSummary['intraday_selection_proof'] == 'RECORDED'
click('intradaySelectionReplayButton'); complete()
assert controller.resultSummary['intraday_selection_proof'] == 'REPLAY_MATCH'
assert controller.resultSummary['intraday_test_proof'] == 'REPLAY_MATCH'
assert session.i18n.setLanguage('zh-CN')
choose('intradayTestView', 0)
assert find('intradayTestEquity').property('visible')
assert window.grabWindow().save(str(root / 'intraday-final-overview.png'))
choose('intradayTestView', 2)
assert not find('intradayTestEquity').property('visible')
assert window.grabWindow().save(str(root / 'intraday-final-ui.png'))
click('intradayFinalLocationsButton')
fill('intradayFinalSourcePath', 'relative/source.json')
click('intradayFinalLocationsDone')
click('intradayTestReplayButton')
assert controller.status == 'VALIDATION_ERROR'
assert controller.resultSummary['intraday_test_proof'] == 'REPLAY_FAILED'
assert controller.resultSummary['intraday_selection_proof'] == 'REPLAY_MATCH'
assert controller._test_content == original
click('intradaySelectionOpenButton'); file_selected('intradaySelectionOpenDialog', saved_selection)
assert not controller.testLoaded
assert find('intradayFinalSourcePath').property('text') == '' and find('intradayFinalDataPath').property('text') == ''
assert saved_test.read_bytes() == original
assert session.runtime.backend_if_initialized is None and session.runtime.shutdown()
engine.deleteLater(); app.processEvents()
print('REAL_INTRADAY_FINAL_WORKFLOW_OK')
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(source), str(data.path)], cwd=ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software", "PYTHONPATH": str(ROOT / "src")},
        capture_output=True, text=True, timeout=420)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "REAL_INTRADAY_FINAL_WORKFLOW_OK" in result.stdout
    assert "ReferenceError" not in result.stderr and "TypeError" not in result.stderr
