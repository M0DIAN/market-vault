"""Native quadratic DEV, immutable V2 contracts and real workflow evidence."""

from copy import deepcopy
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import cross_day_helpers as cd
from market_vault.backtest.intraday import IntradayExecutionPolicy, run_intraday_execution
from market_vault.research import intraday_research as research
from market_vault.research.intraday_data import build_intraday_dataset, json_values, write_intraday_dataset
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.intraday_models import QuadraticRidgeStrategy
from market_vault.research.intraday_quadratic_ridge import _quadratic_predictions
from market_vault.research.strategy_config import parse_strategy_specs
from market_vault.research.strategy_experiment import (
    StrategyExperiment, canonical_json, load_strategy_experiment, replay_strategy_experiment, write_strategy_experiment,
)
from test_intraday_research_analysis import _quadratic_case


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def quadratic_dev_case(tmp_path_factory):
    """One compact 30m real source, still with full sessions, DST and tails."""
    root = tmp_path_factory.mktemp("quadratic-dev")
    entries, days, bars = [], [], []
    day = date(2025, 2, 3)
    while day <= date(2025, 3, 25):
        closed = day.weekday() >= 5 or day == date(2025, 2, 17)
        entries.append((day.isoformat(), "C" if closed else "N"))
        if not closed:
            days.append(day.isoformat())
        day += timedelta(days=1)
    for index, day in enumerate(days):
        for slot in range(13):
            price = 100 + index * .13 + slot * .06 + (slot % 4 - 1.5) ** 2 * .1
            bars.append(cd.bar(day, slot, interval="30m", code="US.SPY", open=price, close=price + .02))
    source = cd.build(root, bars, interval="30m")
    data = build_intraday_dataset({"plan_schema_version": "market-vault-intraday-data-plan-v1",
        "canonical_build_dirs": [str(source.build_path)], "schedule": json_values(asdict(cd.schedule(entries))),
        "symbol": "US.SPY", "interval": "30m", "preset": "LIGHT_TECHNICAL", "stride_bars": 1,
        "target_horizon_bars": 3, "dataset_as_of": cd.AS_OF.isoformat()})
    data = replace(data, path=write_intraday_dataset(data, path=root / "intraday.json"))
    plan = research.default_intraday_research_plan(data, commission_bps=10, slippage_bps=5)
    plan["plan_schema_version"] = research.INTRADAY_RESEARCH_PLAN_V2_VERSION
    plan["feature_fields"] = ["return_2", "sma_5"]
    plan["strategies"] = [
        {"kind": "RIDGE", "name": "Linear", "alpha": 1, "threshold": -1},
        {"kind": "QUADRATIC_RIDGE", "name": "Quadratic", "alpha": 1, "threshold": -1},
        {"kind": "QUADRATIC_RIDGE", "name": "Quadratic flat", "alpha": 1, "threshold": 1},
    ]
    plan = research.normalize_intraday_research_plan(plan, recorded=True)
    calls = []
    fit = research._fit
    def fitted(X, y, alpha):
        calls.append((len(X), len(X[0]), alpha))
        return fit(X, y, alpha)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(research, "_fit", fitted)
        report = research.run_intraday_research(plan)
    snapshot = create_intraday_experiment(plan=plan, report=report, name="Native quadratic DEV")
    path = write_strategy_experiment(snapshot, path=root / "quadratic.json").path
    (root / "plan.json").write_bytes(canonical_json(plan))
    return data, plan, report, snapshot, path, calls


def test_native_quadratic_matches_q23_and_distinguishes_linear_cache_and_decisions():
    prepared, baseline = _quadratic_case()
    q23_rows, _, q23 = _quadratic_predictions(prepared, baseline)
    shared_cache = {}
    linear, linear_models, _ = research.candidate_predictions(prepared,
        parse_strategy_specs([baseline["strategy"]])[0], shared_cache)
    learned = QuadraticRidgeStrategy("Quadratic", 2, 3)
    predictions, models, errors = research.candidate_predictions(prepared, learned, shared_cache)
    assert models == q23["fold_models"]
    assert [row["score"] for row in predictions] == [row["scores"]["QUADRATIC_RIDGE"] for row in q23_rows]
    assert [row["score"] for row in predictions] != [row["score"] for row in linear]
    assert models != linear_models and len(shared_cache) == 2 * len(prepared.context["folds"])
    assert [row["target"] for row in predictions[:4]] == ["LONG", "FLAT", "LONG", "LONG"]
    assert errors["complete_target_count"] < errors["prediction_count"] == len(predictions)
    assert prepared.context["folds"][0]["purged_keys"] == ["boundary-purged"]
    for altered in (_quadratic_case(future_target_shift=1000), _quadratic_case(future_feature_shift=100)):
        changed, changed_models, _ = research.candidate_predictions(altered[0], learned, {})
        assert models[0] == changed_models[0]
        assert models[1] != changed_models[1]
    test_predictions, test_models, test_errors = research.candidate_predictions(_quadratic_case(test_shift=1000)[0], learned, {})
    assert (test_predictions, test_models, test_errors) == (predictions, models, errors)
    # Feed the native decisions into the actual Q6 kernel with a hand-computed
    # two-trade account; the last READY score is intentionally unscored.
    opening = datetime.fromisoformat("2025-04-05T14:30:00+00:00")
    prices = [{"trading_day": "2025-04-05", "slot": slot,
        "event_time": (opening + timedelta(minutes=5 * slot)).isoformat(),
        "available_at": (opening + timedelta(minutes=5 * (slot + 1))).isoformat(),
        "open": price, "close": price, "row_version_id": f"price-{slot}"}
        for slot, price in enumerate((100, 100, 110, 100, 120, 120))]
    decisions = tuple({**row, "decision_time": prices[row["slot"]]["available_at"]} for row in predictions[:4])
    execution = run_intraday_execution(sessions=({"trading_day": "2025-04-05", "open_time": opening.isoformat(),
        "close_time": (opening + timedelta(minutes=30)).isoformat(), "bar_count": 6},), prices=tuple(prices),
        decisions=decisions, interval="5m", policy=IntradayExecutionPolicy(10, 5,
            entry_delay_minutes=0, stop_new_minutes=5, flatten_minutes=5))
    factor = (1 - .0005) * (1 - .001) / ((1 + .0005) * (1 + .001))
    assert execution["metrics"]["final_cash"] == pytest.approx(1.1 * 1.2 * factor ** 2)
    assert execution["metrics"]["trade_count"] == 2
    assert execution["metrics"]["commission_total"] > 0 and execution["metrics"]["slippage_total"] > 0
    assert execution["metrics"]["observed_max_drawdown"] > 0
    assert execution["decisions"][-1]["observation_key"] == predictions[3]["observation_key"]


def test_quadratic_explicit_version_and_width_fail_before_source():
    raw = {"kind": "QUADRATIC_RIDGE", "name": "Q", "alpha": 1, "threshold": 0}
    with pytest.raises(ValueError, match="unsupported strategy"):
        parse_strategy_specs([raw])  # Cross-day and historical V1 remain closed.
    assert type(parse_strategy_specs([raw], allow_quadratic=True)[0]) is QuadraticRidgeStrategy
    for value in (0, True, float("inf")):
        with pytest.raises(ValueError):
            parse_strategy_specs([{**raw, "alpha": value}], allow_quadratic=True)
    plan = {"plan_schema_version": research.INTRADAY_RESEARCH_PLAN_VERSION,
        "intraday_data_path": "/missing/q5.json", "data_id": "a" * 64, "feature_fields": ["x"],
        "strategies": [raw], "split": {"train_end_day": "2025-01-01", "validation_end_day": "2025-02-01", "test_end_day": "2025-03-01"},
        "walk_forward": {"minimum_train_days": 20, "validation_days": 5, "step_days": 5},
        "execution": asdict(IntradayExecutionPolicy(0, 0))}
    with pytest.raises(ValueError, match="unsupported strategy"):
        research.run_intraday_research(plan)
    plan["plan_schema_version"] = research.INTRADAY_RESEARCH_PLAN_V2_VERSION
    plan["feature_fields"] = [f"x{i}" for i in range(7)]
    with pytest.raises(ValueError, match="1 to 6"):
        research.run_intraday_research(plan)


def test_real_quadratic_v2_complete_account_legacy_content_and_replay(quadratic_dev_case, tmp_path):
    data, plan, report, snapshot, path, calls = quadratic_dev_case
    roots = report["groups"][0]["results"]
    folds = report["context"]["folds"]
    assert calls == [(len(fold["training_keys"]), width, 1) for width in (2, 5) for fold in folds]
    assert roots[1]["fold_models"] == roots[2]["fold_models"]
    assert [row["score"] for row in roots[1]["predictions"]] == [row["score"] for row in roots[2]["predictions"]]
    assert roots[1]["execution"]["metrics"]["trade_count"] > 0 and roots[2]["execution"]["metrics"]["trade_count"] == 0
    assert roots[1]["predictions"] != roots[0]["predictions"]
    assert snapshot.as_dict()["artifact_schema_version"] == "market-vault-intraday-experiment-v2"
    assert snapshot.as_dict()["algorithm_versions"]["quadratic"] == "market-vault-intraday-quadratic-ridge-v1"
    assert report["result_schema_version"] == research.INTRADAY_RESEARCH_RESULT_V2_VERSION
    original = path.read_bytes()
    assert load_strategy_experiment(path).content == original
    assert replay_strategy_experiment(snapshot)["report_matches"]
    assert path.read_bytes() == original
    legacy = {**deepcopy(plan), "plan_schema_version": research.INTRADAY_RESEARCH_PLAN_VERSION, "strategies": [plan["strategies"][0]]}
    prepared = research._prepare_intraday_research(legacy, data=data)
    legacy_report = research._evaluate_intraday_research(legacy, (legacy,), ((),), prepared)
    assert legacy_report["groups"][0]["results"][0] == roots[0]
    assert create_intraday_experiment(plan=legacy, report=legacy_report).as_dict()["artifact_schema_version"] == "market-vault-intraday-experiment-v1"
    assert "quadratic" not in research.research_algorithm_versions(legacy)
    (tmp_path / "legacy-plan.json").write_bytes(canonical_json(legacy))


def test_quadratic_saved_model_shape_and_versions_reject_resigned_corruption(quadratic_dev_case):
    _, _, _, snapshot, _, _ = quadratic_dev_case
    for change in ("terms", "transform", "nested_binding", "artifact_version"):
        root = snapshot.as_dict()
        candidate = root["report"]["groups"][0]["results"][1]
        model = candidate["fold_models"][0]["model"]
        if change == "terms":
            model["terms"][-1]["input_indices"] = [0, 1]
        elif change == "transform":
            model["input_transform"]["scales"] = [-1, 1]
        elif change == "nested_binding":
            nested = model["ridge_model"]
            nested["training_boundary"] = "2025-01-01T00:00:00+00:00"
            nested["model_id"] = research.digest({k: v for k, v in nested.items() if k != "model_id"})
        else:
            root["artifact_schema_version"] = "market-vault-intraday-experiment-v1"
        model["model_id"] = research.digest({k: v for k, v in model.items() if k != "model_id"})
        candidate["candidate_id"] = research.digest({k: v for k, v in candidate.items() if k != "candidate_id"})
        report = root["report"]
        report["research_id"] = research.digest({k: v for k, v in report.items() if k != "research_id"})
        root["experiment_id"] = research.digest({k: v for k, v in root.items() if k != "experiment_id"})
        with pytest.raises(ValueError):
            StrategyExperiment(canonical_json(root))


def test_quadratic_diagnostics_cli_saved_analytics_continuation_and_v1_freeze_boundary(quadratic_dev_case, tmp_path, monkeypatch):
    from market_vault.research.intraday_plan import extract_intraday_candidate_plan, serialize_intraday_plan, parse_intraday_plan_bytes
    from market_vault.research.intraday_parameter_grid import analyze_intraday_parameter_grid
    from market_vault.research.intraday_saved_comparison import compare_saved_intraday_experiments
    from market_vault.research.intraday_risk_diagnostics import analyze_intraday_risk_diagnostics
    from market_vault.research.intraday_performance import analyze_intraday_experiment
    from market_vault.research.intraday_final_test import freeze_intraday_candidate

    data, comparison, _, _, _, _ = quadratic_dev_case
    plan = {"plan_schema_version": research.INTRADAY_DIAGNOSTICS_PLAN_V2_VERSION,
        "comparison_plan": comparison, "strategy_name": "Quadratic",
        "parameter_axes": [{"parameter": "threshold", "values": [-1, 1]}],
        "cost_scenarios": [{"commission_bps": 0, "slippage_bps": 0}, {"commission_bps": 10, "slippage_bps": 5}]}
    plan_path, path = tmp_path / "diagnostics-plan.json", tmp_path / "diagnostics.json"
    plan_path.write_bytes(serialize_intraday_plan(plan))
    assert parse_intraday_plan_bytes(plan_path.read_bytes())["plan_schema_version"] == research.INTRADAY_DIAGNOSTICS_PLAN_V2_VERSION
    command = [str(Path(sys.executable).with_name("market-vault")), "research-intraday-diagnose", "--plan", str(plan_path), "--experiment", str(path)]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "SUCCESS"
    snapshot = load_strategy_experiment(path)
    root = snapshot.as_dict()
    assert root["evaluation_mode"] == "INTRADAY_DIAGNOSTICS" and root["report"]["evaluation_count"] == 4
    assert root["report"]["groups"][0]["results"][0]["fold_models"] == root["report"]["groups"][1]["results"][0]["fold_models"]
    original = path.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(research, "load_intraday_dataset", lambda *a, **k: pytest.fail("saved derivation read Q5"))
        patch.setattr(research, "_fit", lambda *a, **k: pytest.fail("saved derivation fitted"))
        candidate = root["report"]["groups"][1]["results"][1]
        draft = extract_intraday_candidate_plan(path, cost_index=1, candidate_index=1,
            expected_experiment_id=root["experiment_id"], expected_candidate_id=candidate["candidate_id"])
        assert draft["plan_schema_version"] == research.INTRADAY_RESEARCH_PLAN_V2_VERSION
        assert draft["strategies"] == [candidate["strategy"]] and draft["execution"]["commission_bps"] == 10
        assert analyze_intraday_parameter_grid(snapshot, cost_index=1, center_candidate_index=1)["cells"]
        assert analyze_intraday_experiment(snapshot, cost_index=1, candidate_index=1)["evaluation_scope"] == "DEVELOPMENT_WALK_FORWARD_ONLY"
        assert analyze_intraday_risk_diagnostics(snapshot, cost_index=1, candidate_index=1)
        assert compare_saved_intraday_experiments(snapshot, snapshot, left_cost_index=1, right_cost_index=1,
            left_candidate_index=0, right_candidate_index=1)
        with pytest.raises(ValueError):
            freeze_intraday_candidate(path, expected_experiment_id=root["experiment_id"], cost_index=1, candidate_index=1,
                                      expected_candidate_id=candidate["candidate_id"])
    assert path.read_bytes() == original


def test_quadratic_execution_scenarios_versioned_children_and_replay(quadratic_dev_case, tmp_path):
    from market_vault.research.intraday_execution_scenarios import (
        INTRADAY_EXECUTION_SCENARIOS_PLAN_V2_VERSION, extract_intraday_execution_scenario,
        normalize_intraday_execution_scenarios_plan, run_intraday_execution_scenarios,
    )
    from market_vault.research.intraday_plan import parse_intraday_plan_bytes, serialize_intraday_plan

    _, comparison, _, _, _, _ = quadratic_dev_case
    plan = {"plan_schema_version": INTRADAY_EXECUTION_SCENARIOS_PLAN_V2_VERSION, "comparison_plan": comparison,
        "execution_scenarios": [{"name": "Original", "execution": comparison["execution"]},
            {"name": "Short hold", "execution": {**comparison["execution"], "max_hold_bars": 2}}]}
    assert parse_intraday_plan_bytes(serialize_intraday_plan(plan)) == normalize_intraday_execution_scenarios_plan(plan)
    with pytest.raises(ValueError, match="versions must agree"):
        normalize_intraday_execution_scenarios_plan({**plan, "plan_schema_version": "market-vault-intraday-execution-scenarios-plan-v1"})
    snapshot = run_intraday_execution_scenarios(plan)
    assert snapshot.as_dict()["artifact_schema_version"] == "market-vault-intraday-execution-scenarios-v2"
    child = extract_intraday_execution_scenario(snapshot, expected_experiment_id=snapshot.experiment_id, scenario_index=1,
        expected_child_experiment_id=snapshot.as_dict()["report"]["scenarios"][1]["experiment"]["experiment_id"])
    assert child.as_dict()["artifact_schema_version"] == "market-vault-intraday-experiment-v2"
    assert child.as_dict()["report"]["groups"][0]["execution_policy"]["max_hold_bars"] == 2
    assert replay_strategy_experiment(snapshot)["report_matches"]


def test_native_qml_quadratic_edit_run_save_open_continue_replay_and_language(quadratic_dev_case, tmp_path):
    # Keep the complete numerical/core module collectible in CI without Qt.
    pytest.importorskip("PySide6")
    data, _, _, _, _, _ = quadratic_dev_case
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
root, data_path = Path(sys.argv[1]), sys.argv[2]
QQuickStyle.setStyle('Basic')
app = QGuiApplication([])
engine = QQmlApplicationEngine()
session = create_qml_application_session(build_application_context(root / 'settings.yaml'), engine,
    preference_store=DesktopPreferenceStore(root=root / 'preferences'))
engine.load(QUrl.fromLocalFile(str(Path.cwd() / 'src/market_vault/desktop/qml/Main.qml')))
assert engine.rootObjects()
window = engine.rootObjects()[0]
window.setWidth(1200); window.setHeight(800)
owner = session.context_properties['quantResearchController']
controller, final = owner.intradayResearchController, owner.intradayFinalController
assert session.shell.selectPage('quant_research')
def find(name):
    parent = window
    if name.startswith('quantStrategy'):
        parent = window.findChild(QObject, 'intradayStrategyEditor')
        assert parent is not None
    obj = parent.findChild(QObject, name)
    if obj is None:
        pending = [window.contentItem()]
        while pending:
            candidate = pending.pop()
            if candidate.objectName() == name: obj = candidate; break
            pending.extend(candidate.childItems())
    assert obj is not None, name
    return obj
def click(name):
    obj = find(name)
    app.processEvents()
    assert obj.property('visible') and obj.property('enabled'), name
    point = obj.mapToScene(obj.boundingRect().center()).toPoint()
    assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), (name, point)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    app.processEvents()
def nested(obj, kind):
    if kind in obj.metaObject().className(): return obj
    return next(c for c in obj.findChildren(QObject) if kind in c.metaObject().className())
def fill(name, text):
    obj = find(name)
    window.requestActivate(); QTest.qWait(30)
    edit = nested(obj, 'PixelTextField')
    edit.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClick(window, Qt.Key_Backspace)
    for ch in text:
        QGuiApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, ord(ch.upper()), Qt.NoModifier, ch))
    app.processEvents()
    assert obj.property('text') == text, (name, obj.property('text'))
def choose(name, index):
    obj = find(name)
    combo = nested(obj, 'PixelComboBox')
    window.requestActivate(); QTest.qWait(30)
    combo.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_Home)
    for _ in range(index): QTest.keyClick(window, Qt.Key_Down)
    app.processEvents()
    assert obj.property('currentIndex') == index, (name, obj.property('currentIndex'))
def complete(target=controller):
    deadline = time.monotonic() + 120
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
click('quantIntradayTab')
fill('intradayDataPath', data_path)
click('intradayInspectButton'); complete(owner)
click('intradayComparisonTab'); QTest.qWait(50)
click('intradayResearchSettingsButton'); QTest.qWait(50)
fill('intradayResearchFeatures', 'return_2,sma_5')
fill('intradayResearchCommission', '10'); fill('intradayResearchSlippage', '5')
choose('quantStrategySelector', 2)
fill('quantStrategyRidgeThreshold', '-1')
click('quantStrategyAddButton')
choose('quantStrategyKind', 3)
assert find('intradayStrategyEditor').property('selectedKind') == 'QUADRATIC_RIDGE'
fill('quantStrategyName', 'Quadratic')
fill('quantStrategyRidgeThreshold', '-1')
assert session.i18n.setLanguage('zh-CN'); assert session.i18n.setLanguage('en')
assert find('intradayStrategyEditor').property('selectedKind') == 'QUADRATIC_RIDGE'
assert find('quantStrategyRidgeThreshold').property('text') == '-1'
assert window.grabWindow().save(str(root / 'q24-native-settings.png'))
click('intradayResearchSettingsDone')
click('intradayRunComparisonButton'); complete()
assert len(controller.candidateNames) == 4
assert controller._root['artifact_schema_version'] == 'market-vault-intraday-experiment-v2'
choose('intradayResearchCandidate', 3)
choose('intradayResearchView', 4)
assert controller.tableModel.totalRows == 14
assert {row[1] for row in controller._rows} == {'INPUT_TRANSFORM', 'GENERATED_TERMS'}
assert not controller.predictionQualityAvailable
assert window.grabWindow().save(str(root / 'q24-native-models-en.png'))
assert session.i18n.setLanguage('zh-CN')
assert window.grabWindow().save(str(root / 'q24-native-models-zh.png'))
saved = root / 'native-dev.json'
click('intradayExperimentSaveButton'); file_selected('intradayExperimentSaveDialog', saved)
captured = saved.read_bytes()
assert not final.canFreeze and final.freezeUnsupported
assert not final.freezeSelected() and final.status == 'VALIDATION_ERROR'
choose('intradayResearchCandidate', 2)
assert controller.predictionQualityAvailable and not final.canFreeze
choose('intradayResearchCandidate', 3)
click('intradayExperimentReplayButton'); complete()
assert controller.resultSummary['intraday_verification'] == 'REPLAY_MATCH'
click('intradayExperimentOpenButton'); file_selected('intradayExperimentOpenDialog', saved)
choose('intradayResearchCandidate', 3)
click('intradayPlanContinueButton'); complete()
assert controller.draftPlan['plan_schema_version'] == 'market-vault-intraday-research-plan-v2'
assert controller.draftPlan['strategies'] == [json.loads(captured)['plan']['strategies'][3]]
click('intradayResearchSettingsButton'); QTest.qWait(50)
assert find('intradayStrategyEditor').property('selectedKind') == 'QUADRATIC_RIDGE'
assert float(find('quantStrategyRidgeThreshold').property('text')) == -1.0
click('intradayComparisonPlanSave')
plan_path = root / 'native-continued-plan.json'
file_selected('intradayPlanSaveDialog', plan_path)
assert json.loads(plan_path.read_bytes()) == controller.draftPlan
# Complete the continued plan through the real Run entry, preserving the old
# saved source, then repeat Open/Replay without overwriting any file.
QMetaObject.invokeMethod(find('intradayResearchSettings'), 'close', Qt.DirectConnection)
click('intradayRunComparisonButton'); complete()
assert len(controller.candidateNames) == 1 and controller._root['plan']['strategies'][0]['kind'] == 'QUADRATIC_RIDGE'
assert saved.read_bytes() == captured
click('intradayExperimentOpenButton'); file_selected('intradayExperimentOpenDialog', saved)
click('intradayExperimentReplayButton'); complete()
assert controller.resultSummary['intraday_verification'] == 'REPLAY_MATCH'
assert session.runtime.backend_if_initialized is None and session.runtime.shutdown()
engine.deleteLater(); app.processEvents()
print('NATIVE_QUADRATIC_DEV_WORKFLOW_OK')
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(data.path)], cwd=ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software", "PYTHONPATH": str(ROOT / "src")},
        capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NATIVE_QUADRATIC_DEV_WORKFLOW_OK" in result.stdout
