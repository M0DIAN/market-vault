"""Discriminating causal selection cases and one compact real-source workflow."""

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from market_vault.research import intraday_inner_selection as inner
from market_vault.research import intraday_research as research
from market_vault.research.intraday_data import digest
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.strategy_experiment import (StrategyExperiment, canonical_json, load_strategy_experiment,
                                                     replay_strategy_experiment, write_strategy_experiment)
from test_strategy_intraday_ml import quadratic_dev_case  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]


def chronological_case(*, inner_flat=False, outer_shift=0, unknown_shift=0, constant=False, no_scores=False):
    days = [(date(2025, 1, 1) + timedelta(days=index)).isoformat() for index in range(30)]
    sessions, observations, targets = [], [], []
    for index, day in enumerate(days):
        opening = datetime.combine(date.fromisoformat(day), datetime.min.time(), timezone.utc) + timedelta(hours=14)
        sessions.append({"trading_day": day, "open_time": opening.isoformat()})
        count = 5 if index == 19 else 2 if index < 15 else 1
        for slot in range(count):
            x = index % 5 - 2
            key = f"{index}-{slot}"
            when = opening + timedelta(minutes=5 * (slot + 1))
            observations.append({"observation_key": key, "trading_day": day, "slot": slot,
                "decision_time": when.isoformat(), "status": "READY", "features": {"x": x + (outer_shift if index >= 20 else 0)}})
            value = 7.0 if constant else 2.0 if index >= 20 or (inner_flat and index >= 15) else float(x * x)
            end, status = when + timedelta(minutes=5), "COMPLETE"
            if key == "14-1":  # Equality is excluded from the earlier inner TRAIN.
                end = datetime.fromisoformat(sessions[0]["open_time"]) + timedelta(days=15)
            if key == "19-3":  # This label is not known until the outer boundary.
                end = datetime.fromisoformat(sessions[0]["open_time"]) + timedelta(days=20)
                value += unknown_shift
            if key == "19-4" or (no_scores and 15 <= index < 20):
                status = "INCOMPLETE"
            targets.append({"observation_key": key, "status": status, "value": value,
                            "actual_label_end_time": end.isoformat()})
    report = {"sessions": sessions, "observations": observations, "targets": targets}
    boundary = sessions[20]["open_time"]
    history_rows, purged = research.training_rows(report, tuple(days[:20]), boundary)
    prepared = SimpleNamespace(report=report)
    window = inner._window(prepared, days[:20], history_rows, purged, boundary)
    strategy = {"kind": "RIDGE", "name": "Reference", "alpha": 1.0, "threshold": 0.0}
    return prepared, window, history_rows, strategy, days


def test_inner_known_labels_pooled_loss_reversal_and_causal_interventions():
    prepared, window, rows, strategy, days = chronological_case()
    inner._select(window, ["x"], strategy)
    evidence = window[0]
    assert evidence["selected_recipe"]["kind"] == "QUADRATIC_RIDGE"
    assert len(evidence["family_results"]) == 6
    assert evidence["purged_keys"] == ["14-1"]
    assert evidence["history_purged_keys"] == ["19-3"]
    assert evidence["validation_keys"][-2:] == ["19-3", "19-4"]
    assert {row["observation_key"] for row in evidence["scored_targets"]}.isdisjoint({"19-3", "19-4"})
    member = evidence["family_results"][0]
    predicted = {row["observation_key"]: row["score"] for row in member["predictions"]}
    errors = [(row["trading_day"], (predicted[row["observation_key"]] - row["value"]) ** 2) for row in evidence["scored_targets"]]
    assert member["mse"] == pytest.approx(sum(error for _, error in errors) / len(errors))
    daily = [sum(error for day, error in errors if day == value) / sum(day == value for day, _ in errors) for value in days[15:20]]
    assert not math.isclose(member["mse"], sum(daily) / 5)
    outer_rows = tuple(row for row in prepared.report["observations"] if row["trading_day"] in days[20:25])
    outer_targets = [{"observation_key": row["observation_key"], "value": 2.0} for row in outer_rows]
    outer_losses = []
    for member in inner.FAMILY:
        _, predictions = inner._fit(rows, outer_rows, ["x"], inner._recipe(member, strategy), evidence["history_boundary"])
        outer_losses.append(inner.pooled_mse(predictions, outer_targets))
    assert min(range(6), key=lambda index: outer_losses[index]) < 3  # Hindsight would choose linear.
    assert evidence["selected_index"] >= 3
    changed = chronological_case(inner_flat=True)
    inner._select(changed[1], ["x"], strategy)
    assert changed[1][0]["selected_recipe"]["kind"] == "RIDGE"
    for altered in (chronological_case(outer_shift=100), chronological_case(unknown_shift=10000)):
        inner._select(altered[1], ["x"], strategy)
        assert altered[1][0] == evidence
        actual = inner._fit(altered[2], outer_rows, ["x"], evidence["selected_recipe"], evidence["history_boundary"])[0]
        expected = inner._fit(rows, outer_rows, ["x"], evidence["selected_recipe"], evidence["history_boundary"])[0]
        assert actual == expected


def test_exact_tie_keeps_declared_first_and_empty_score_is_explicit():
    _, window, _, strategy, _ = chronological_case(constant=True)
    inner._select(window, ["x"], strategy)
    assert [member["mse"] for member in window[0]["family_results"]] == [0.0] * 6
    assert window[0]["selected_index"] == 0
    assert window[0]["selected_recipe"]["kind"] == "RIDGE" and window[0]["selected_recipe"]["alpha"] == .1
    _, empty, _, _, _ = chronological_case(no_scores=True)
    assert empty[0]["unavailable_reason"] == "NO_COMPLETE_INNER_SCORE_SAMPLE"
    assert empty[0]["family_results"] == []


@pytest.fixture(scope="session")
def inner_case(quadratic_dev_case, tmp_path_factory):
    root = tmp_path_factory.mktemp("intraday-inner")
    data, comparison, _, _, _, _ = quadratic_dev_case
    plan = {"plan_schema_version": research.INTRADAY_DIAGNOSTICS_PLAN_V2_VERSION,
        "comparison_plan": comparison, "strategy_name": "Quadratic",
        "parameter_axes": [{"parameter": "alpha", "values": [.5, 2]}],
        "cost_scenarios": [{"commission_bps": 0, "slippage_bps": 0}, {"commission_bps": 10, "slippage_bps": 5}]}
    source = create_intraday_experiment(plan=plan, report=research.run_intraday_research(plan))
    source_path = write_strategy_experiment(source, path=root / "source-diagnostics.json").path
    candidate = source.as_dict()["report"]["groups"][1]["results"][1]
    args = dict(expected_experiment_id=source.experiment_id, cost_index=1, candidate_index=1, expected_candidate_id=candidate["candidate_id"])
    result = inner.run_intraday_inner_selection(source_path, **args)
    saved = write_strategy_experiment(result, path=root / "inner-selection.json").path
    return data, source, source_path, args, result, saved


def test_real_inner_full_source_final_dev_sample_account_and_embedded_replay(inner_case, monkeypatch):
    data, source, source_path, args, result, path = inner_case
    root, original = result.as_dict(), source.as_dict()
    report = root["report"]
    context = original["report"]["context"]
    assert root["evaluation_mode"] == "INTRADAY_INNER_SELECTION" and report["status"] == "AVAILABLE"
    assert report["source_experiment"] == original and root["plan"]["selection"] == {key: args[key] for key in ("cost_index", "candidate_index")} | {"candidate_id": args["expected_candidate_id"]}
    assert [row["fold_id"] for row in report["outer_folds"]] == [row["fold_id"] for row in context["folds"]]
    assert report["selected_account"]["prediction_metrics"]["prediction_count"] > report["selected_account"]["prediction_metrics"]["complete_target_count"]
    expected_keys = context["validation_keys"]
    assert [row["observation_key"] for row in report["selected_account"]["predictions"]] == expected_keys
    policy = original["report"]["groups"][1]["execution_policy"]
    assert report["selected_account"]["execution"]["policy"] == policy
    assert report["benchmark"] == original["report"]["groups"][1]["benchmark"]
    assert report["final_dev"]["history_days"] == context["split"]["TRAIN"] + context["split"]["VALIDATION"]
    assert len(report["final_dev"]["history_days"]) > len(context["evaluated_days"])
    first_test = next(row for row in data.as_dict()["report"]["sessions"] if row["trading_day"] == context["split"]["TEST"][0])
    assert report["final_dev"]["history_boundary"] == first_test["open_time"]
    for window in [row["inner"] for row in report["outer_folds"]] + [report["final_dev"]]:
        assert len(window["family_results"]) == 6
        assert all(datetime.fromisoformat(row["actual_label_end_time"]) < datetime.fromisoformat(window["history_boundary"]) for row in window["scored_targets"])
    from market_vault.research.intraday_backtest import execution_views, parse_execution_policy
    sessions, prices = execution_views(data.as_dict()["report"], trading_days=tuple(context["evaluated_days"]))
    actual = research.run_intraday_execution(sessions=sessions, prices=prices, decisions=tuple(report["selected_account"]["predictions"]),
        interval=context["interval"], policy=parse_execution_policy(policy))
    assert actual == report["selected_account"]["execution"]
    assert actual["metrics"]["commission_total"] > 0 and actual["metrics"]["slippage_total"] > 0
    assert actual["daily"][0]["cash_open"] == 1 and all(row["quantity"] == 0 for row in actual["ledger"] if row["phase"] == "CLOSE" and row["timestamp"] in {day["close_time"] for day in actual["daily"]})
    original_bytes, study_bytes = source_path.read_bytes(), path.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(inner, "load_strategy_experiment", lambda *a, **kw: pytest.fail("replay should use embedded ordinary source"))
        load = research.load_intraday_dataset
        calls = []
        def loaded(*args, **kwargs):
            calls.append(1)
            return load(*args, **kwargs)
        patch.setattr(research, "load_intraday_dataset", loaded)
        assert replay_strategy_experiment(result)["report_matches"]
        assert len(calls) == 1
    assert source_path.read_bytes() == original_bytes and path.read_bytes() == study_bytes


def test_inner_insufficient_first_outer_makes_whole_study_unavailable(quadratic_dev_case, tmp_path):
    _, plan, _, _, _, _ = quadratic_dev_case
    plan = deepcopy(plan)
    plan["walk_forward"]["minimum_train_days"] = 14
    plan["strategies"] = [plan["strategies"][0]]
    source = create_intraday_experiment(plan=plan, report=research.run_intraday_research(plan))
    path = write_strategy_experiment(source, path=tmp_path / "short-source.json").path
    candidate = source.as_dict()["report"]["groups"][0]["results"][0]
    study = inner.run_intraday_inner_selection(path, expected_experiment_id=source.experiment_id, cost_index=0,
        candidate_index=0, expected_candidate_id=candidate["candidate_id"])
    report = study.as_dict()["report"]
    assert report["status"] == "UNAVAILABLE" and report["selected_account"] is None
    assert report["unavailable_reasons"] == [{"scope": "OUTER_FOLD", "fold_index": 0, "reason": "INSUFFICIENT_INNER_HISTORY"}]
    assert len(report["outer_folds"]) == len(source.as_dict()["report"]["context"]["folds"])
    assert all(row["refit"] is None and row["inner"]["family_results"] == [] for row in report["outer_folds"])
    assert report["final_dev"]["selected_recipe"] is None
    saved = write_strategy_experiment(study, path=tmp_path / "unavailable.json").path
    assert load_strategy_experiment(saved).content == study.content
    assert replay_strategy_experiment(study)["report_matches"]


def resigned(root):
    report = root["report"]
    report["inner_selection_id"] = digest({key: value for key, value in report.items() if key != "inner_selection_id"})
    root["experiment_id"] = digest({key: value for key, value in root.items() if key != "experiment_id"})
    return canonical_json(root)


def test_inner_offline_bindings_and_full_replay_hidden_family_evidence(inner_case, monkeypatch):
    _, _, _, _, snapshot, _ = inner_case
    for case in ("drop_member", "chosen_recipe", "future_label", "refit_boundary", "final_days"):
        root = snapshot.as_dict()
        window = root["report"]["outer_folds"][0]["inner"]
        if case == "drop_member":
            window["family_results"].pop()
        elif case == "chosen_recipe":
            window["selected_recipe"]["alpha"] = 20
        elif case == "future_label":
            window["scored_targets"][0]["actual_label_end_time"] = window["history_boundary"]
        elif case == "refit_boundary":
            model = root["report"]["outer_folds"][0]["refit"]["model"]
            model["training_boundary"] = window["training_boundary"]
            model["model_id"] = digest({key: value for key, value in model.items() if key != "model_id"})
        else:
            root["report"]["final_dev"]["history_days"].pop()
        with pytest.raises(ValueError):
            StrategyExperiment(resigned(root))
    root = snapshot.as_dict()
    model = root["report"]["final_dev"]["family_results"][0]["model"]
    model["coefficients"][0] += 1e-8
    model["model_id"] = digest({key: value for key, value in model.items() if key != "model_id"})
    altered = StrategyExperiment(resigned(root))  # Shape/hash validation is not execution proof.
    with pytest.raises(ValueError, match="complete replay"):
        replay_strategy_experiment(altered)
    with monkeypatch.context() as patch:
        patch.setattr(research, "load_intraday_dataset", lambda *a, **k: pytest.fail("offline Open read Q5"))
        patch.setattr(inner, "_fit", lambda *a, **k: pytest.fail("offline Open fitted"))
        assert StrategyExperiment(snapshot.content).experiment_id == snapshot.experiment_id


def test_actual_inner_cli_identity_guard_immutable_save_open_and_replay(inner_case, tmp_path):
    _, source, source_path, args, _, _ = inner_case
    cli = str(Path(sys.executable).with_name("market-vault"))
    saved = tmp_path / "cli-inner.json"
    command = [cli, "research-intraday-inner-selection", "--source-experiment", str(source_path),
        "--expected-experiment-id", source.experiment_id, "--cost-index", "1", "--candidate-index", "1",
        "--expected-candidate-id", args["expected_candidate_id"], "--experiment", str(saved)]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["study"]["report"]["status"] == "AVAILABLE"
    original = saved.read_bytes()
    for action in ("research-experiment-open", "research-experiment-replay"):
        result = subprocess.run([cli, action, "--experiment", str(saved)], cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0 and not json.loads(result.stdout)["experiment"]["created_new_file"]
    result = subprocess.run(command + ["--name", "Different"], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 1 and saved.read_bytes() == original
    command[command.index("--expected-candidate-id") + 1] = "a" * 64
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 1 and "captured identity" in result.stderr


def test_native_inner_qml_source_evidence_save_replay_stale_and_recovery(inner_case, tmp_path):
    # Core contracts stay collectible in the CI dev environment without Qt.
    pytest.importorskip("PySide6")
    data, _, source_path, _, _, _ = inner_case
    (tmp_path / "settings.yaml").write_text("storage:\n  root_dir: ./data\n")
    script = r'''
import sys, time, json, threading
from pathlib import Path
from PySide6.QtCore import QObject, QUrl, Qt, QEvent
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from market_vault.application import build_application_context
from market_vault.desktop.bootstrap import create_qml_application_session
from market_vault.desktop.preferences import DesktopPreferenceStore
from market_vault.research import intraday_inner_selection as inner
root, source_path, data_path = map(Path, sys.argv[1:])
source_bytes, data_bytes = source_path.read_bytes(), data_path.read_bytes()
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
research, controller = owner.intradayResearchController, owner.intradayInnerSelectionController
assert session.shell.selectPage('quant_research')
def find(name):
    obj = window.findChild(QObject, name)
    if obj is not None: return obj
    pending = [window.contentItem()]
    while pending:
        obj = pending.pop()
        if obj.objectName() == name: return obj
        pending.extend(obj.childItems())
    raise AssertionError(name)
def click(name):
    obj = find(name)
    app.processEvents()
    assert obj.property('visible') and obj.property('enabled'), name
    point = obj.mapToScene(obj.boundingRect().center()).toPoint()
    assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), (name, point)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    app.processEvents()
def type_text(target, value):
    QTest.keyClick(target, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClick(target, Qt.Key_Backspace)
    for ch in str(value):
        QGuiApplication.sendEvent(target, QKeyEvent(QEvent.KeyPress, ord(ch.upper()), Qt.NoModifier, ch))
    app.processEvents()
def nested(obj, kind):
    if kind in obj.metaObject().className(): return obj
    return next(c for c in obj.findChildren(QObject) if kind in c.metaObject().className())
def choose(name, index):
    obj = find(name)
    window.requestActivate(); QTest.qWait(30)
    combo = nested(obj, 'PixelComboBox'); combo.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_Home)
    for _ in range(index): QTest.keyClick(window, Qt.Key_Down)
    app.processEvents()
    assert obj.property('currentIndex') == index, (name, obj.property('currentIndex'))
def fill(name, value):
    obj = find(name)
    window.requestActivate(); QTest.qWait(30)
    nested(obj, 'PixelTextField').forceActiveFocus()
    type_text(window, value)
    assert obj.property('text') == str(value), (name, obj.property('text'))
def complete(target=controller, expected='SUCCESS'):
    deadline = time.monotonic() + 120
    while target.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    app.processEvents()
    assert not target.busy and target.status == expected, (target.status, target.error)
def file_choice(button, path, target=controller):
    click(button); QTest.qWait(100)
    popup = next(w for w in app.topLevelWindows() if w != window and w.isVisible())
    popup.requestActivate(); QTest.qWait(30)
    QTest.keyClick(popup, Qt.Key_L, Qt.ControlModifier)
    type_text(popup, path)
    QTest.keyClick(popup, Qt.Key_Return); QTest.qWait(100)
    if popup.isVisible(): QTest.keyClick(popup, Qt.Key_Return)
    QTest.qWait(100)
    assert not popup.isVisible(), button
    complete(target)
click('quantIntradayTab'); click('intradayComparisonTab'); QTest.qWait(50)
file_choice('intradayExperimentOpenButton', source_path, research)
click('intradayInnerTab'); QTest.qWait(50)
choose('intradayInnerCandidate', 3)
assert research.selection_source()['cost_index'] == 1 and research.selection_source()['candidate_index'] == 1
assert controller.canRun
click('intradayInnerRunButton'); complete()
assert controller.resultSummary['inner_status'] == 'AVAILABLE' and controller.proof == 'COMPUTED'
assert controller.completedDetails['cost_index'] == controller.completedDetails['candidate_index'] == 1
assert len(controller.equitySeries) == 3 and controller.finalRecipe
overview = {row[1]: row for row in controller._rows if row[0] == 'SELECTED PROCEDURE'}
actual_return = controller._root['report']['selected_account']['execution']['metrics']['total_return']
assert overview['total_return'][2].endswith('%') and abs(float(overview['total_return'][2][:-1]) - actual_return * 100) < .0001
assert overview['final_cash'][3] == 'INITIAL_CASH_UNITS' and overview['trade_count'][3] == 'COUNT'
QTest.qWait(30)
assert window.grabWindow().save(str(root / 'q25-native-overview-en.png'))
choose('intradayInnerView', 1)
assert controller.tableModel.totalRows == 6 * (len(controller._root['report']['outer_folds']) + 1)
assert any(row[0] == 'FINAL DEV' for row in controller._rows)
assert window.grabWindow().save(str(root / 'q25-native-family-en.png'))
choose('intradayInnerView', 3)
assert {row[2] for row in controller._rows} == {'INPUT_TRANSFORM', 'GENERATED_TERMS', 'LINEAR_FEATURES'}
assert session.i18n.setLanguage('zh-CN')
assert controller.tableModel.totalRows > 0 and find('intradayInnerView').property('currentIndex') == 3
assert window.grabWindow().save(str(root / 'q25-native-models-zh.png'))
assert session.i18n.setLanguage('en')
saved = root / 'native-inner.json'
file_choice('intradayInnerSaveButton', saved)
saved_bytes = saved.read_bytes()
assert json.loads(saved_bytes)['plan']['selection'] == controller._root['plan']['selection']
file_choice('intradayInnerOpenButton', saved)
assert controller.proof == 'RECORDED'
click('intradayInnerReplayButton'); complete()
assert controller.proof == 'REPLAY_MATCH'
before = controller._content
fill('intradayInnerDataPath', root / 'missing-q5.json')
click('intradayInnerReplayButton'); complete(expected='FAILED')
assert controller.proof == 'REPLAY_FAILED' and controller.studyError and controller._content == before
# The actual Q5 file can be relocated while its immutable identity stays fixed.
relocated = root / 'relocated-q5.json'; relocated.write_bytes(data_bytes)
file_choice('intradayInnerDataBrowse', relocated, research)
assert controller.dataLocator
click('intradayInnerReplayButton'); complete()
assert controller.proof == 'REPLAY_MATCH' and not controller.studyError and controller._content == before
click('intradayInnerDataClear'); assert controller.dataLocator == ''
# Delay only delivery of a real computed result, then change the selected source
# through the actual combo. The worker must keep its captured indices, and its
# completed stale result must not replace the displayed immutable study.
real_run, ready, release, captured = inner.run_intraday_inner_selection, threading.Event(), threading.Event(), []
def delayed(*args, **kwargs):
    captured.append(kwargs)
    result = real_run(*args, **kwargs)
    ready.set()
    assert release.wait(30)
    return result
inner.run_intraday_inner_selection = delayed
click('intradayInnerRunButton')
deadline = time.monotonic() + 120
while not ready.is_set() and time.monotonic() < deadline:
    app.processEvents(); time.sleep(.01)
assert ready.is_set()
choose('intradayInnerCandidate', 0)
release.set(); complete()
inner.run_intraday_inner_selection = real_run
assert captured[0]['cost_index'] == captured[0]['candidate_index'] == 1
assert controller.notice == 'STALE_INPUT' and controller._content == before
assert controller.completedDetails['cost_index'] == controller.completedDetails['candidate_index'] == 1
assert window.grabWindow().save(str(root / 'q25-native-stale.png'))
choose('intradayInnerCandidate', 3)
click('intradayInnerRunButton'); complete()
assert not controller.notice and controller.proof == 'COMPUTED'
assert source_path.read_bytes() == source_bytes and data_path.read_bytes() == data_bytes and saved.read_bytes() == saved_bytes
assert session.runtime.backend_if_initialized is None and session.runtime.shutdown()
engine.deleteLater(); app.processEvents()
print('NATIVE_INNER_SELECTION_WORKFLOW_OK')
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(source_path), str(data.path)], cwd=ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software", "PYTHONPATH": str(ROOT / "src")},
        capture_output=True, text=True, timeout=240)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NATIVE_INNER_SELECTION_WORKFLOW_OK" in result.stdout
