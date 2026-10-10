"""Q26 fixed ML Freeze/TEST, causal boundaries and real saved entry points."""

from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from market_vault.research import intraday_final_test as final
from market_vault.research import intraday_inner_selection as inner
from market_vault.research import intraday_research as research
from market_vault.research.intraday_data import digest
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.strategy_experiment import (StrategyExperiment, canonical_json, load_strategy_experiment,
                                                     replay_strategy_experiment, write_strategy_experiment)
from test_strategy_intraday_inner_selection import inner_case, quadratic_dev_case  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]


def bind(value, key):
    value[key] = digest({name: item for name, item in value.items() if name != key})


def signed_selection(root):
    root["report"]["plan_sha256"] = digest(root["plan"])
    bind(root["report"], "selection_id")
    bind(root, "experiment_id")
    return canonical_json(root)


@pytest.fixture(scope="session")
def ml_final_case(inner_case, tmp_path_factory):
    data, source, source_path, args, study, study_path = inner_case
    path = tmp_path_factory.mktemp("intraday-ml-final")
    blocked = lambda *a, **kw: pytest.fail("Freeze/Open read Q5 or fitted a model")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(final, "load_intraday_dataset", blocked)
        patch.setattr(research, "load_intraday_dataset", blocked)
        patch.setattr(research, "_fit", blocked)
        selections = {"fixed": final.freeze_intraday_candidate(source_path, **args),
                      "inner": final.freeze_intraday_inner_selection(study_path, expected_experiment_id=study.experiment_id)}
        for name, selection in selections.items():
            written = write_strategy_experiment(selection, path=path / f"{name}-selection.json")
            assert load_strategy_experiment(written.path).content == selection.content
    tests, calls = {}, {}
    loader, fitter = final.load_intraday_dataset, research._fit
    for name, selection in selections.items():
        captured = {"loads": 0, "fits": []}
        def load(value):
            captured["loads"] += 1
            return loader(value)
        def fit(X, y, alpha):
            captured["fits"].append((len(X), len(X[0]), alpha))
            return fitter(X, y, alpha)
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(final, "load_intraday_dataset", load)
            patch.setattr(research, "_fit", fit)
            patch.setattr(research, "load_intraday_dataset", blocked)
            patch.setattr(inner, "_fit", lambda *a, **kw: pytest.fail("normal TEST reselected an inner family"))
            patch.setattr(research, "_evaluate_intraday_research", lambda *a, **kw: pytest.fail("normal TEST recomputed DEV"))
            report = final.run_intraday_final_test(selection)
        tests[name] = final.create_intraday_test_experiment(selection, report)
        write_strategy_experiment(tests[name], path=path / f"{name}-test.json")
        calls[name] = captured
    return selections, tests, calls, path


def test_ml_freeze_preserves_fixed_reference_and_all_final_dev_evidence_no_q5_no_fit(inner_case, ml_final_case, monkeypatch, tmp_path):
    data, source, source_path, args, study, study_path = inner_case
    selections, tests, calls, _ = ml_final_case
    fixed, chosen = (selections[name].as_dict() for name in ("fixed", "inner"))
    source_candidate = source.as_dict()["report"]["groups"][1]["results"][1]
    assert fixed["artifact_schema_version"] == chosen["artifact_schema_version"] == final.INTRADAY_SELECTION_V2_VERSION
    assert fixed["report"]["candidate"]["strategy"] == source_candidate["strategy"]
    assert fixed["report"]["candidate"]["axis_values"] == [2.0] and fixed["report"]["dev_selection"] is None
    evidence = chosen["report"]["dev_selection"]
    assert evidence["final_dev"] == study.as_dict()["report"]["final_dev"]
    assert evidence["method"] == inner.METHOD and len(evidence["final_dev"]["family_results"]) == 6
    assert evidence["source_selection"] == study.as_dict()["plan"]["selection"]
    assert evidence["fixed_reference"] == {key: source_candidate[key] for key in ("strategy", "axis_values")}
    assert evidence["source_experiment"]["experiment_id"] == source.experiment_id
    assert chosen["plan"]["source_experiment"]["experiment_id"] == study.experiment_id
    assert chosen["report"]["candidate"]["strategy"] == evidence["final_dev"]["selected_recipe"]
    assert chosen["report"]["candidate"]["axis_values"] == []
    assert chosen["report"]["candidate"]["strategy"]["alpha"] == .1 != evidence["fixed_reference"]["strategy"]["alpha"]
    blocked = lambda *a, **kw: pytest.fail("guard/immutable Open read Q5 or fitted")
    monkeypatch.setattr(final, "load_intraday_dataset", blocked)
    monkeypatch.setattr(research, "_fit", blocked)
    for snapshot in (*selections.values(), *tests.values()):
        assert StrategyExperiment(snapshot.content).content == snapshot.content
    for kwargs in ({**args, "expected_experiment_id": "a" * 64}, {**args, "expected_candidate_id": "a" * 64}):
        with pytest.raises(ValueError):
            final.freeze_intraday_candidate(source_path, **kwargs)
    with pytest.raises(ValueError, match="identity differs"):
        final.freeze_intraday_inner_selection(study_path, expected_experiment_id="a" * 64)
    historical = study.as_dict()
    historical["algorithm_versions"]["inner_selection"] = historical["report"]["version"] = "historical-inner"
    bind(historical["report"], "inner_selection_id"); bind(historical, "experiment_id")
    old = StrategyExperiment(canonical_json(historical))
    old_path = write_strategy_experiment(old, path=tmp_path / "historical-inner.json").path
    with pytest.raises(ValueError, match="source algorithms differ"):
        final.freeze_intraday_inner_selection(old_path, expected_experiment_id=old.experiment_id)
    altered = chosen
    altered["report"]["dev_selection"]["fixed_reference"]["strategy"]["alpha"] = 3.0
    with pytest.raises(ValueError, match="complete frozen selection"):
        final.run_intraday_final_test(StrategyExperiment(signed_selection(altered)))


def test_ml_one_final_fit_all_ready_independent_account_and_full_replay_once(inner_case, ml_final_case, monkeypatch):
    data, source, _, _, study, _ = inner_case
    selections, tests, calls, _ = ml_final_case
    original_q25 = study.content
    ordinary = source.as_dict()["report"]
    for name, tested in tests.items():
        report = tested.as_dict()["report"]
        model, context, policy = report["model"], report["context"], report["execution_policy"]
        assert calls[name] == {"loads": 1, "fits": [(180, 5, 2.0 if name == "fixed" else .1)]}
        assert tested.as_dict()["artifact_schema_version"] == final.INTRADAY_TEST_EXPERIMENT_V2_VERSION
        assert report["strategy"] == selections[name].as_dict()["report"]["candidate"]["strategy"]
        assert policy == ordinary["groups"][1]["execution_policy"]
        assert len(report["predictions"]) == report["prediction_metrics"]["prediction_count"] == 54
        assert report["prediction_metrics"]["complete_target_count"] == 36
        assert model["training_keys"] == context["training_keys"] and model["training_boundary"] == context["training_boundary"]
        assert model["ridge_model"]["training_keys"] == model["training_keys"]
        assert len(model["input_features"]) == 2 and len(model["terms"]) == 5
        assert set(model["training_keys"]).isdisjoint(context["test_keys"])
        if name == "inner":
            final_dev = study.as_dict()["report"]["final_dev"]
            inner_model = final_dev["family_results"][final_dev["selected_index"]]["model"]
            assert set(inner_model["training_keys"]) < set(model["training_keys"])
            assert inner_model["model_id"] != model["model_id"]
            assert model["training_boundary"] == final_dev["history_boundary"] != inner_model["training_boundary"]
        for account in (report["execution"], report["benchmark"]["execution"]):
            assert account["daily"][0]["cash_open"] == 1
            assert all(day["cash_open"] == previous["cash_close"] for previous, day in zip(account["daily"], account["daily"][1:]))
            assert account["metrics"]["commission_total"] > 0 and account["metrics"]["slippage_total"] > 0
            assert all(row["quantity"] == 0 for row in account["ledger"] if row["timestamp"] in {day["close_time"] for day in account["daily"]})
            # Independent fill-cost oracle, cash 1 and full-position sequential trades.
            cash = 1.0
            factor = (1 - .0005) * (1 - .001) / ((1 + .0005) * (1 + .001))
            for trade in account["trades"]:
                cash *= trade["exit_raw_open"] / trade["entry_raw_open"] * factor
            assert account["metrics"]["final_cash"] == pytest.approx(cash)
        loader, loaded = final.load_intraday_dataset, []
        def load(path):
            loaded.append(path)
            return loader(path)
        with monkeypatch.context() as patch:
            patch.setattr(final, "load_intraday_dataset", load)
            patch.setattr(research, "load_intraday_dataset", lambda *a, **kw: pytest.fail("Replay admitted Q5 a second time"))
            patch.setattr(inner, "load_strategy_experiment", lambda *a, **kw: pytest.fail("Q25 Replay requested original ordinary source"))
            proof = replay_strategy_experiment(tested)
        assert len(loaded) == 1 and proof["source_report_matches"] and proof["final_report_matches"]
        assert proof["expected_report_sha256"] == proof["actual_report_sha256"]
    assert study.content == original_q25


def test_ml_strict_actual_end_purge_test_interventions_and_ready_tails(inner_case, ml_final_case):
    data = inner_case[0]
    selection = ml_final_case[0]["inner"].as_dict()
    baseline = ml_final_case[1]["inner"].as_dict()["report"]
    original = data.as_dict()
    first_key = baseline["context"]["training_keys"][0]
    boundary = baseline["context"]["training_boundary"]
    next(target for target in original["report"]["targets"] if target["observation_key"] == first_key)["actual_label_end_time"] = boundary
    # Deliberate internal admitted-row counterfactuals. These dictionaries are
    # never persisted or presented as verified Q5 artifacts.
    def evaluate(root):
        return final._evaluate_final_test(selection, SimpleNamespace(data_id=data.data_id, as_dict=lambda: root))
    purged = evaluate(original)
    assert purged["context"]["purged_keys"] == [first_key]
    assert len(purged["context"]["training_keys"]) == 179
    assert first_key not in purged["model"]["training_keys"]
    for mode in ("targets", "features", "unknown_dev_label"):
        changed = deepcopy(original)
        if mode == "unknown_dev_label":
            next(row for row in changed["report"]["targets"] if row["observation_key"] == first_key)["value"] += 10000
        elif mode == "targets":
            keys = set(purged["context"]["test_keys"])
            for row in changed["report"]["targets"]:
                if row["observation_key"] in keys and row["status"] == "COMPLETE":
                    row["value"] += 1
        else:
            for row in changed["report"]["observations"]:
                if row["observation_key"] in purged["context"]["test_keys"]:
                    row["features"]["sma_5"] += 2
        actual = evaluate(changed)
        assert actual["strategy"] == purged["strategy"] and actual["execution_policy"] == purged["execution_policy"]
        assert actual["model"] == purged["model"] and actual["context"] == purged["context"]
        if mode == "targets":
            assert actual["predictions"] == purged["predictions"] and actual["prediction_metrics"] != purged["prediction_metrics"]
        elif mode == "features":
            assert actual["predictions"] != purged["predictions"]
        else:
            assert actual == purged
    targets = {row["observation_key"]: row for row in original["report"]["targets"]}
    assert any(targets[row["observation_key"]]["status"] != "COMPLETE" for row in purged["predictions"])
    assert all(datetime.fromisoformat(targets[key]["actual_label_end_time"]) < datetime.fromisoformat(boundary)
               for key in purged["model"]["training_keys"])


def test_ml_resigned_evidence_grammar_and_full_hidden_source_reconstruction(inner_case, ml_final_case, tmp_path, monkeypatch):
    selections, tests, _, _ = ml_final_case
    fixed = selections["fixed"].as_dict()
    fixed["report"]["context"]["feature_fields"] = [f"feature_{index}" for index in range(7)]
    with pytest.raises(ValueError, match="1 to 6"):
        StrategyExperiment(signed_selection(fixed))
    fixed = selections["fixed"].as_dict()
    fixed["report"]["context"]["target_horizon_bars"] = None
    with pytest.raises(ValueError, match="ML target horizon"):
        StrategyExperiment(signed_selection(fixed))
    for case in ("missing_member", "future_label", "term_order", "negative_transform", "selected_recipe"):
        root = selections["inner"].as_dict()
        evidence = root["report"]["dev_selection"]["final_dev"]
        model = evidence["family_results"][3]["model"]
        if case == "missing_member":
            evidence["family_results"].pop()
        elif case == "future_label":
            evidence["scored_targets"][0]["actual_label_end_time"] = evidence["history_boundary"]
        elif case == "term_order":
            model["terms"].reverse(); bind(model, "model_id")
        elif case == "negative_transform":
            model["input_transform"]["scales"][0] = -1; bind(model, "model_id")
        else:
            root["report"]["candidate"]["strategy"]["alpha"] = 1.0
        with pytest.raises(ValueError):
            StrategyExperiment(signed_selection(root))
    # A hidden, well-shaped coefficient change is legal recorded evidence but
    # must fail the complete source rebuild, even though TEST uses another fit.
    source = inner_case[4].as_dict()
    hidden = source["report"]["final_dev"]["family_results"][0]["model"]
    hidden["coefficients"][0] += 1e-6
    bind(hidden, "model_id"); bind(source["report"], "inner_selection_id"); bind(source, "experiment_id")
    corrupted = StrategyExperiment(canonical_json(source))
    path = write_strategy_experiment(corrupted, path=tmp_path / "hidden-source.json").path
    frozen = final.freeze_intraday_inner_selection(path, expected_experiment_id=corrupted.experiment_id)
    with monkeypatch.context() as patch:
        patch.setattr(final, "_evaluate_final_test", lambda *a, **kw: pytest.fail("source mismatch reached TEST"))
        with pytest.raises(ValueError, match="complete source development report mismatch"):
            replay_strategy_experiment(frozen)
    root = tests["inner"].as_dict()
    root["report"]["model"]["ridge_model"]["training_boundary"] = "2025-01-01T00:00:00+00:00"
    bind(root["report"]["model"]["ridge_model"], "model_id"); bind(root["report"]["model"], "model_id")
    bind(root["report"], "final_test_id"); bind(root, "experiment_id")
    with pytest.raises(ValueError, match="training fold"):
        StrategyExperiment(canonical_json(root))


def test_ml_v1_inner_linear_tie_recipe_and_offline_test_v2_readers(quadratic_dev_case, ml_final_case, tmp_path, monkeypatch):
    from market_vault.research.intraday_performance import analyze_intraday_experiment
    from market_vault.research.intraday_risk_diagnostics import analyze_intraday_risk_diagnostics
    from market_vault.research.intraday_saved_comparison import compare_saved_intraday_experiments
    data, plan, _, _, _, _ = quadratic_dev_case
    plan = deepcopy(plan)
    plan.update(plan_schema_version=research.INTRADAY_RESEARCH_PLAN_VERSION, feature_fields=["volume_ratio_5"], strategies=[plan["strategies"][0]])
    prepared = research._prepare_intraday_research(plan, data=data)
    source = create_intraday_experiment(plan=plan, report=research._evaluate_intraday_research(plan, (plan,), ((),), prepared))
    path = write_strategy_experiment(source, path=tmp_path / "constant-linear-source.json").path
    candidate = source.as_dict()["report"]["groups"][0]["results"][0]
    study = inner.run_intraday_inner_selection(path, expected_experiment_id=source.experiment_id, cost_index=0, candidate_index=0,
                                               expected_candidate_id=candidate["candidate_id"])
    assert study.as_dict()["report"]["final_dev"]["selected_index"] == 0
    path = write_strategy_experiment(study, path=tmp_path / "linear-inner.json").path
    selection = final.freeze_intraday_inner_selection(path, expected_experiment_id=study.experiment_id)
    assert selection.as_dict()["report"]["candidate"]["strategy"] == {"kind": "RIDGE", "name": "Linear", "alpha": .1, "threshold": -1.0}
    report = final.run_intraday_final_test(selection)
    assert report["model"]["scales"] == [0.0] and report["model"]["coefficients"] == [0.0]
    tested = final.create_intraday_test_experiment(selection, report)
    assert replay_strategy_experiment(tested)["final_report_matches"]
    blocked = lambda *a, **kw: pytest.fail("offline TEST reader read source or fitted")
    monkeypatch.setattr(final, "load_intraday_dataset", blocked)
    monkeypatch.setattr(final, "load_strategy_experiment", blocked)
    monkeypatch.setattr(research, "load_intraday_dataset", blocked)
    monkeypatch.setattr(research, "_fit", blocked)
    for test in (tested, ml_final_case[1]["inner"]):
        assert analyze_intraday_experiment(test)["evaluation_scope"] == "FROZEN_SINGLE_CANDIDATE_TEST"
        risk = analyze_intraday_risk_diagnostics(test)
        assert risk["strategy_diagnostics"]["report"]["fold_diagnostics"] == {
            "status": "NOT_APPLICABLE", "unavailable_reason": "NOT_APPLICABLE", "rows": [], "summary": {}}
        comparison = compare_saved_intraday_experiments(test, test)
        assert not comparison["delta_allowed"]
        assert all(row["delta"]["unavailable_reason"] == "TEST_DESCRIPTIVE_ONLY" for row in comparison["strategy_metrics"])
        for analyze in (analyze_intraday_experiment, analyze_intraday_risk_diagnostics):
            with pytest.raises(ValueError, match="both indices must be zero"):
                analyze(test, candidate_index=1)
            with pytest.raises(ValueError):
                analyze(selection)


def test_actual_ml_final_cli_both_sources_relocation_failure_recovery_and_exclusive_save(inner_case, ml_final_case, tmp_path):
    data, source, source_path, args, study, study_path = inner_case
    cli = str(Path(sys.executable).with_name("market-vault"))
    def command(*args, ok=True):
        result = subprocess.run([cli, *map(str, args)], cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == (0 if ok else 1), result.stderr
        return json.loads(result.stdout if ok else result.stderr)
    for name, original, source_file in (("fixed", source, source_path), ("inner", study, study_path)):
        source_copy = tmp_path / f"{name}-source.json"
        data_copy = tmp_path / f"{name}-q5.json"
        source_copy.write_bytes(source_file.read_bytes()); data_copy.write_bytes(data.content)
        selected_path, test_path = tmp_path / f"{name}-selection.json", tmp_path / f"{name}-test.json"
        freeze = ["research-intraday-freeze" if name == "fixed" else "research-intraday-freeze-inner-selection",
                  "--source-experiment", source_copy, "--expected-experiment-id", original.experiment_id, "--experiment", selected_path]
        if name == "fixed":
            freeze.extend(["--cost-index", 1, "--candidate-index", 1, "--expected-candidate-id", args["expected_candidate_id"]])
        assert command(*freeze)["status"] == "SUCCESS"
        original_bytes = selected_path.read_bytes()
        assert not command(*freeze)["experiment"]["created_new_file"]
        assert command(*freeze, "--name", "Different", ok=False)["status"] == "FAILED"
        assert selected_path.read_bytes() == original_bytes
        relocated = source_copy.with_name(f"{name}-relocated-source.json")
        source_copy.rename(relocated)  # Move only this test's own disposable copy.
        assert command("research-intraday-test", "--selection", selected_path, ok=False)["status"] == "FAILED"
        command("research-intraday-test", "--selection", selected_path, "--source-experiment-file", relocated,
                "--intraday-data-file", data_copy, "--experiment", test_path)
        test = load_strategy_experiment(test_path)
        assert test.as_dict()["report"]["model"] == ml_final_case[1][name].as_dict()["report"]["model"]
        command("research-experiment-open", "--experiment", test_path)
        proof = command("research-experiment-replay", "--experiment", test_path,
                        "--source-experiment-file", relocated, "--intraday-data-file", data_copy)
        assert proof["report_matches"] and proof["source_report_matches"] and proof["final_report_matches"]
        assert selected_path.read_bytes() == original_bytes


def test_native_ml_final_both_sources_real_dialogs_model_evidence_compact_paging_and_recovery(inner_case, tmp_path):
    # Keep all core tests collected when the CI environment does not install Qt.
    pytest.importorskip("PySide6")
    data, _, source_path, _, _, study_path = inner_case
    (tmp_path / "settings.yaml").write_text("storage:\n  root_dir: ./data\n")
    script = r'''
import sys, time, json, threading
from pathlib import Path
from PySide6.QtCore import QObject, QUrl, Qt, QEvent, QPointF
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from market_vault.application import build_application_context
from market_vault.desktop.bootstrap import create_qml_application_session
from market_vault.desktop.preferences import DesktopPreferenceStore
from market_vault.research import intraday_final_test as core
root, original_source, original_study, original_data = map(Path, sys.argv[1:])
original_bytes = [path.read_bytes() for path in (original_source, original_study, original_data)]
source, study, data = root/'native-source.json', root/'native-study.json', root/'native-q5.json'
for path, content in zip((source, study, data), original_bytes): path.write_bytes(content)
QQuickStyle.setStyle('Basic')
app = QGuiApplication([])
engine = QQmlApplicationEngine()
session = create_qml_application_session(build_application_context(root/'settings.yaml'), engine,
    preference_store=DesktopPreferenceStore(root=root/'preferences'))
engine.load(QUrl.fromLocalFile(str(Path.cwd()/'src/market_vault/desktop/qml/Main.qml')))
assert engine.rootObjects()
window = engine.rootObjects()[0]
window.setWidth(1200); window.setHeight(800)
owner = session.context_properties['quantResearchController']
research, controller, comparison = owner.intradayResearchController, owner.intradayFinalController, owner.intradaySavedComparisonController
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
def nested(obj, kind):
    if kind in obj.metaObject().className(): return obj
    return next(c for c in obj.findChildren(QObject) if kind in c.metaObject().className())
def click_item(obj):
    assert obj.property('enabled') and obj.property('visible'), obj.objectName()
    point = obj.mapToScene(obj.boundingRect().center()).toPoint()
    assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), (obj.objectName(), point)
    window.requestActivate(); QTest.qWait(20)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point); QTest.qWait(30)
def click(name): click_item(find(name))
def type_text(target, value):
    QTest.keyClick(target, Qt.Key_A, Qt.ControlModifier); QTest.keyClick(target, Qt.Key_Backspace)
    for ch in str(value): QGuiApplication.sendEvent(target, QKeyEvent(QEvent.KeyPress, ord(ch.upper()), Qt.NoModifier, ch))
    app.processEvents()
def fill(name, value):
    obj = find(name)
    window.requestActivate(); QTest.qWait(20)
    nested(obj, 'PixelTextField').forceActiveFocus(); type_text(window, value)
    assert obj.property('text') == str(value), (name, obj.property('text'))
def choose(name, index):
    obj = find(name)
    point = obj.mapToScene(obj.boundingRect().center()).toPoint()
    assert 0 <= point.y() < window.height(), (name, point)
    window.requestActivate(); QTest.qWait(20)
    nested(obj, 'PixelComboBox').forceActiveFocus(); QTest.keyClick(window, Qt.Key_Home)
    for _ in range(index): QTest.keyClick(window, Qt.Key_Down)
    QTest.qWait(40)
    assert obj.property('currentIndex') == index, (name, obj.property('currentIndex'))
def complete(target=controller, expected='SUCCESS'):
    deadline = time.monotonic()+120
    while target.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    QTest.qWait(40)
    assert not target.busy and target.status == expected, (target.status, target.error)
def file_choice(button, path, target=None):
    click(button); QTest.qWait(100)
    popup = next(w for w in app.topLevelWindows() if w != window and w.isVisible())
    popup.requestActivate(); QTest.qWait(30)
    QTest.keyClick(popup, Qt.Key_L, Qt.ControlModifier); type_text(popup, path)
    QTest.keyClick(popup, Qt.Key_Return); QTest.qWait(100)
    if popup.isVisible(): QTest.keyClick(popup, Qt.Key_Return)
    QTest.qWait(100)
    assert not popup.isVisible(), button
    if target is not None: complete(target)
def drag_bar(name, bottom):
    bar = find(name)
    if bar.property('size') >= 1: return
    thumb = bar.property('contentItem')
    start = thumb.mapToScene(thumb.boundingRect().center()).toPoint()
    end = bar.mapToScene(QPointF(bar.width()/2, bar.height()-2 if bottom else 2)).toPoint()
    assert bar.property('visible') and bar.height() > 100, (name, bar.height())
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(window, end, 50); QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end); QTest.qWait(80)
def scroll(bottom): drag_bar('intradayFinalScrollBar', bottom)
def shot(name):
    QTest.qWait(50)
    assert window.grabWindow().save(str(root/(name+'.png')))
def locations(source_file, data_file):
    scroll(False); click('intradayFinalLocationsButton')
    file_choice('intradayFinalSourceBrowse', source_file)
    file_choice('intradayFinalDataBrowse', data_file)
    click('intradayFinalLocationsDone')
def unavailable_source(name):
    scroll(False); click('intradayFinalLocationsButton')
    missing = root/(name+'-never-existing-source.json')
    assert not missing.exists()
    fill('intradayFinalSourcePath', missing)
    click('intradayFinalLocationsDone')
click('quantIntradayTab'); click('intradayComparisonTab'); QTest.qWait(50)
file_choice('intradayExperimentOpenButton', source, research)
click('intradayFinalTab'); QTest.qWait(50)
choose('intradayFinalCandidate', 3)
assert research.selection_source()['cost_index'] == research.selection_source()['candidate_index'] == 1
assert controller.canFreeze and not controller.freezeUnsupported
click('intradayFreezeButton'); complete()
assert controller.frozenCandidate['strategy']['alpha'] == 2.0
captured = controller._selection_content
choose('intradayFinalCandidate', 0)
assert controller._selection_content == captured and controller.selectionEvidence['cost_index'] == 1
assert controller.selectionEvidence['candidate_index'] == 1
print('FIXED_CAPTURE_OK', flush=True)
saved_tests = {}
for name, source_file, expected_alpha in (('fixed', source, 2.0), ('inner', study, .1)):
    scroll(False)
    if name == 'inner':
        file_choice('intradayFinalInnerOpenButton', study, controller)
        assert controller.canFreezeInner
        click('intradayFreezeInnerButton'); complete()
        assert not controller.testLoaded and controller.hasDevSelection
        assert controller.selectionEvidence['reference'].startswith('QUADRATIC_RIDGE · alpha=2.0')
        assert controller.selectionEvidence['candidate_index'] == controller.selectionEvidence['cost_index'] == 1
        assert controller._selection_root['plan']['source_experiment']['experiment_id'] == json.loads(original_bytes[1])['experiment_id']
        scroll(True); choose('intradayTestView', 15)
        assert controller.tableModel.totalRows == 6
        shot('q26-final-dev-six-losses-en')
        choose('intradayTestView', 16)
        assert controller.tableModel.totalRows == 27
        assert {row[1] for row in controller._rows} == {'LINEAR_FEATURES', 'INPUT_TRANSFORM', 'GENERATED_TERMS'}
        shot('q26-final-dev-six-models-en')
        scroll(False)
    selected, tested = root/(name+'-native-selection.json'), root/(name+'-native-test.json')
    assert controller.frozenCandidate['strategy']['alpha'] == expected_alpha
    assert controller.frozenCandidate['execution_policy']['commission_bps'] == 10
    file_choice('intradaySelectionSaveButton', selected, controller)
    selected_bytes = selected.read_bytes()
    file_choice('intradaySelectionOpenButton', selected, controller)
    assert controller.resultSummary['intraday_selection_proof'] == 'RECORDED'
    assert controller._selection_content == selected_bytes
    relocated = root/(name+'-relocated-source.json')
    relocated.write_bytes(source_file.read_bytes())
    unavailable_source(name)
    click('intradayRunTestButton'); complete(expected='FAILED')
    assert not controller.testLoaded and controller._selection_content == selected_bytes
    locations(relocated, data)
    click('intradayRunTestButton'); complete()
    assert controller.testLoaded and controller.resultSummary['intraday_test_proof'] == 'COMPUTED'
    report = controller._test_root['report']
    assert report['model']['alpha'] == expected_alpha and len(report['model']['training_keys']) == 180
    assert report['execution']['daily'][0]['cash_open'] == 1 and len(report['predictions']) == 54
    scroll(True); choose('intradayTestView', 4)
    assert controller.tableModel.totalRows == 7
    assert {row[0] for row in controller._rows} == {'INPUT_TRANSFORM', 'GENERATED_TERMS'}
    assert [row[1] for row in controller._rows[:2]] == ['return_2', 'sma_5']
    assert [row[1] for row in controller._rows[2:]] == [term['name'] for term in report['model']['terms']]
    shot(name+'-q26-final-model-en')
    scroll(False); click('intradayFinalDetailsButton')
    assert find('intradayFinalDetailsDialog').property('visible')
    text = find('intradayFinalEvidenceText').property('text')
    assert report['model']['model_id'] in text and report['context']['training_boundary'] in text
    assert 'z_0*z_1' in text and 'return_2, sma_5' in text
    shot(name+'-q26-source-model-details-top')
    drag_bar('intradayFinalDetailsScrollBar', True); shot(name+'-q26-source-model-details-bottom')
    QTest.keyClick(window, Qt.Key_Escape); QTest.qWait(40)
    assert not find('intradayFinalDetailsDialog').property('visible')
    scroll(False); file_choice('intradayTestSaveButton', tested, controller)
    test_bytes = tested.read_bytes()
    file_choice('intradayTestOpenButton', tested, controller)
    assert controller._test_content == test_bytes and controller.resultSummary['intraday_test_proof'] == 'RECORDED'
    assert find('intradayFinalSourcePath').property('text') == find('intradayFinalDataPath').property('text') == ''
    assert controller._locators == ('', '')
    assert controller._selection_root['plan']['source_experiment']['path'] == str(source_file)
    unavailable_source(name)
    click('intradayTestReplayButton'); complete(expected='FAILED')
    assert controller._test_content == test_bytes and controller.resultSummary['intraday_test_proof'] == 'REPLAY_FAILED'
    locations(relocated, data)
    click('intradayTestReplayButton'); complete()
    assert controller.resultSummary['intraday_test_proof'] == 'REPLAY_MATCH' and controller._test_content == test_bytes
    assert selected.read_bytes() == selected_bytes and tested.read_bytes() == test_bytes
    saved_tests[name] = tested
    print(name.upper()+'_SAVE_OPEN_TEST_FULL_REPLAY_RECOVERY_OK', flush=True)
# Actual supported compact geometry, two model stages and reachable pagination.
window.setWidth(1024); window.setHeight(600); QTest.qWait(100)
scroll(True); choose('intradayTestView', 4)
assert session.i18n.setLanguage('zh-CN'); QTest.qWait(50)
assert '两级变换' in find('intradayFinalMethod').property('text')
scroll(True); shot('q26-compact-final-model-zh')
choose('intradayTestView', 17); scroll(True)
table = find('intradayTestTable'); pager = nested(table, 'PixelPagination')
next_button = next(child for child in pager.findChildren(QObject) if child.property('glyph') == 'next')
previous_button = next(child for child in pager.findChildren(QObject) if child.property('glyph') == 'previous')
viewport = find('adaptiveWorkspaceViewport')
visible_bottom = viewport.mapToScene(QPointF(0, viewport.height())).y()
assert next_button.mapToScene(QPointF(0, next_button.height())).y() <= visible_bottom
assert controller.tableModel.page == 1 and controller.tableModel.totalPages > 1
click_item(next_button); assert controller.tableModel.page == 2
shot('q26-compact-final-dev-keys-page2-zh')
click_item(previous_button); assert controller.tableModel.page == 1
choose('intradayTestView', 18); scroll(True)
assert controller.tableModel.totalRows == 270
click_item(next_button); assert controller.tableModel.page == 2
shot('q26-compact-final-dev-predictions-page2-zh')
assert session.i18n.setLanguage('en')
# Change a location through the real dialog while a real final fit is pending.
# Only delivery is delayed; the calculation, source verification and Q5 read run.
before, before_path = controller._test_content, controller.testPath
real_run, ready, release = core.run_intraday_final_test, threading.Event(), threading.Event()
def delayed(*args, **kwargs):
    result = real_run(*args, **kwargs); ready.set(); assert release.wait(30); return result
core.run_intraday_final_test = delayed
scroll(False); click('intradayRunTestButton')
deadline = time.monotonic()+120
while not ready.is_set() and time.monotonic() < deadline:
    app.processEvents(); time.sleep(.01)
assert ready.is_set()
click('intradayFinalLocationsButton'); fill('intradayFinalDataPath', root/'missing-q5.json')
click('intradayFinalLocationsDone'); release.set(); complete()
core.run_intraday_final_test = real_run
assert controller.notice == 'STALE_INPUT' and controller._test_content == before and controller.testPath == before_path
shot('q26-compact-stale-location')
click('intradayRunTestButton'); complete(expected='FAILED')
assert controller._test_content == before and controller.testPath == before_path
locations(root/'inner-relocated-source.json', data)
click('intradayRunTestButton'); complete()
assert not controller.notice and controller.resultSummary['intraday_test_proof'] == 'COMPUTED'
assert controller._test_content == before
print('NATIVE_ML_FINAL_STALE_RECOVERY_OK', flush=True)
# The directly affected saved A/B reader accepts TEST V2 and keeps TEST descriptive.
window.setWidth(1200); window.setHeight(800); QTest.qWait(80)
click('intradaySavedComparisonTab'); QTest.qWait(50)
file_choice('intradaySavedLeftOpen', saved_tests['fixed'], comparison)
file_choice('intradaySavedRightOpen', saved_tests['inner'], comparison)
click('intradaySavedCompareButton'); complete(comparison)
assert comparison._result['delta_allowed'] is False
assert all(row['delta']['unavailable_reason'] == 'TEST_DESCRIPTIVE_ONLY' for row in comparison._result['strategy_metrics'])
assert [path.read_bytes() for path in (original_source, original_study, original_data)] == original_bytes
assert session.runtime.backend_if_initialized is None and session.runtime.shutdown()
engine.deleteLater(); app.processEvents()
print('NATIVE_ML_FINAL_WORKFLOW_OK')
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(source_path), str(study_path), str(data.path)], cwd=ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software", "PYTHONPATH": str(ROOT / "src")},
        capture_output=True, text=True, timeout=360)
    (tmp_path / "native-workflow.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NATIVE_ML_FINAL_WORKFLOW_OK" in result.stdout
