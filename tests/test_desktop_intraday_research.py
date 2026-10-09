"""Real intraday research controller and visible QML development workflow."""

import os
from concurrent.futures import Future
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

pytest.importorskip("PySide6")

from market_vault.desktop.quant_research import QuantResearchController
from market_vault.research import intraday_research as research
from market_vault.research.strategy_experiment import write_strategy_experiment
from test_desktop_quant_research import _runtime, qt_app  # noqa: F401
from test_intraday_experiment import intraday_experiment, parameter_grid_experiment  # noqa: F401
from test_intraday_research import research_case  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def desktop_execution_scenarios(research_case):
    from market_vault.research.intraday_execution_scenarios import (
        INTRADAY_EXECUTION_SCENARIOS_PLAN_VERSION, run_intraday_execution_scenarios,
    )
    _, comparison, _ = research_case
    scenarios = [
        {"name": "Baseline", "execution": {**comparison["execution"], "commission_bps": 10, "slippage_bps": 5}},
        {"name": "Shorter", "execution": {"entry_delay_minutes": 30, "stop_new_minutes": 45,
            "flatten_minutes": 10, "max_hold_bars": 6, "commission_bps": 20, "slippage_bps": 7}},
    ]
    return run_intraday_execution_scenarios({"plan_schema_version": INTRADAY_EXECUTION_SCENARIOS_PLAN_VERSION,
        "comparison_plan": comparison, "execution_scenarios": scenarios})


def test_scenarios_controller_offline_collection_export_and_replay(qt_app, desktop_execution_scenarios,
                                                                tmp_path, monkeypatch):
    from market_vault.strategy_comparison_io import canonical_json
    snapshot = desktop_execution_scenarios
    path = tmp_path / "all.json"
    write_strategy_experiment(snapshot, path=path)
    runtime, _ = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    controller, final = owner.intradayResearchController, owner.intradayFinalController
    with monkeypatch.context() as patch:
        patch.setattr(research, "load_intraday_dataset", lambda *a, **k: pytest.fail("offline action read Q5"))
        patch.setattr(research, "_fit", lambda *a, **k: pytest.fail("offline action fitted"))
        assert controller.openExperiment(str(path))
        runtime._poll()
        assert controller.status == "SUCCESS", controller.error
        assert controller.scenariosLoaded and controller.scenarioNames == ["Baseline", "Shorter"]
        assert controller.collectionPath == str(path) and controller.collectionProof == "RECORDED"
        assert controller.experimentPath == "" and not final.canFreeze
        assert controller.resultSummary["evaluation_count"] == "6" and controller.tableModel.totalRows == 6
        assert controller._columns[2:8] == ("entry_delay_minutes", "stop_new_minutes", "flatten_minutes", "max_hold_bars",
                                            "commission_bps", "slippage_bps")
        assert [row[:2] for row in controller._rows] == [(scenario, name) for scenario in ("Baseline", "Shorter")
                                                       for name in ("Flat", "Long", "Ridge")]
        from market_vault.desktop.quant_research import _format_number
        roots = snapshot.as_dict()["report"]["scenarios"]
        baseline, changed = [root["experiment"]["report"]["groups"][0]["results"] for root in roots]
        assert [row[10] for row in controller._rows[3:]] == [_format_number(100 * (
            b["execution"]["metrics"]["total_return"] - a["execution"]["metrics"]["total_return"]))
            for a, b in zip(baseline, changed, strict=True)]
        assert controller.saveExperiment(str(tmp_path / "all-copy.json"))
        runtime._poll()
        assert (tmp_path / "all-copy.json").read_bytes() == path.read_bytes()
        assert controller.experimentPath == "" and not final.canFreeze
        assert controller.selectScenario(1) and controller.selectCandidate(2)
        assert controller.selectView(7) and controller.tableModel.totalRows == 17
        detached = controller.scenarioPlan
        detached["execution_scenarios"][1]["execution"]["max_hold_bars"] = 999
        assert controller.scenarioPlan["execution_scenarios"][1]["execution"]["max_hold_bars"] == 6
        child_path = tmp_path / "selected.json"
        assert controller.exportScenario(str(child_path))
        runtime._poll()
        assert controller.status == "SUCCESS", controller.error
        child = roots[1]["experiment"]
        assert child_path.read_bytes() == canonical_json(child) == controller._content
        assert final.canFreeze and controller.selection_source()["candidate_index"] == 2
        assert controller.selection_source()["experiment_id"] == child["experiment_id"]
        assert controller.selectScenario(0) and not final.canFreeze and controller.candidateIndex == 2
        assert controller.selectScenario(1) and final.canFreeze and controller.experimentPath == str(child_path)
        assert controller.exportScenario(str(path))  # the collection cannot be overwritten by its child
        runtime._poll()
        assert controller.status == "FAILED" and controller._content == canonical_json(child)
        assert controller.experimentPath == str(child_path) and path.read_bytes() == snapshot.content
        assert final.freezeSelected()
        runtime._poll()
        assert final.status == "SUCCESS", final.error
        assert final.frozenCandidate["strategy"]["name"] == "Ridge"
        assert final.frozenCandidate["execution_policy"] == child["plan"]["execution"]
    assert controller.selectView(5) and controller.changePage(1)
    assert controller.replayExperiment("")
    runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    assert controller.collectionProof == controller.resultSummary["intraday_verification"] == "REPLAY_MATCH"
    assert controller.scenarioIndex == 1 and controller.candidateIndex == 2 and controller.tableModel.page == 2
    assert controller._collection_content == snapshot.content
    assert controller.replayExperiment(str(tmp_path / "missing.json"))
    runtime._poll()
    assert controller.status == "FAILED" and controller.collectionProof == "REPLAY_FAILED"
    assert controller._collection_content == snapshot.content and controller.tableModel.page == 2
    assert controller.selectScenario(0) and controller.resultSummary["intraday_verification"] == "REPLAY_FAILED"
    assert controller.openExperiment(str(path))
    runtime._poll()
    assert controller.collectionProof == "RECORDED" and not final.canFreeze
    assert controller.selectScenario(1) and controller.experimentPath == ""
    assert controller.openExperiment(str(child_path))
    runtime._poll()
    assert not controller.scenariosLoaded and final.canFreeze and controller.collectionPath == ""
    assert runtime.backend_if_initialized is None and runtime.shutdown()


def test_scenarios_capture_complete_explicit_policies_without_common_costs(qt_app, research_case,
                                                                        desktop_execution_scenarios,
                                                                        tmp_path, monkeypatch):
    data, comparison, _ = research_case
    runtime, runner = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    owner._apply_intraday(data)
    controller = owner.intradayResearchController
    values = {"comparison": {"data_id": data.data_id, "feature_fields": list(comparison["feature_fields"]),
        "strategies": deepcopy(comparison["strategies"]), **comparison["split"], **comparison["walk_forward"],
        **comparison["execution"], "commission_bps": "", "slippage_bps": ""},
        "execution_scenarios": deepcopy(desktop_execution_scenarios.as_dict()["plan"]["execution_scenarios"])}
    pending = []
    def deferred(name, operation):
        future = Future()
        pending.append((future, operation))
        return future
    with monkeypatch.context() as patch:
        patch.setattr(runner, "submit", deferred)
        assert controller.runScenarios(values) and controller.busy
        values["execution_scenarios"][1]["execution"]["max_hold_bars"] = 999
        values["comparison"]["strategies"][0]["threshold"] = -1000
        future, operation = pending.pop()
        future.set_result(operation())
        runtime._poll()
        assert controller.status == "SUCCESS", controller.error
        assert controller._collection_root["plan"]["comparison_plan"]["execution"]["commission_bps"] == 10
        assert controller.scenarioPlan["execution_scenarios"][1]["execution"]["max_hold_bars"] == 6
        assert controller.restoredPlan["strategies"][0]["threshold"] == 1000000
        assert values["comparison"]["commission_bps"] == values["comparison"]["slippage_bps"] == ""
        assert controller.selectScenario(1) and controller.selectCandidate(2)
        exported_id = controller._root["experiment_id"]
        assert controller.exportScenario(str(tmp_path / "captured.json"))
        assert not controller.selectScenario(0)  # scenario identity cannot change during an action
        assert controller.selectCandidate(0)  # exporting the complete child does not freeze a candidate
        future, operation = pending.pop()
        future.set_result(operation())
        runtime._poll()
        assert controller.status == "SUCCESS", controller.error
        assert json.loads((tmp_path / "captured.json").read_bytes())["experiment_id"] == exported_id
        assert controller.scenarioIndex == 1 and controller.experimentPath == str(tmp_path / "captured.json")
    previous = controller._collection_content
    incomplete = deepcopy(values)
    del incomplete["execution_scenarios"][0]["execution"]["flatten_minutes"]
    before = list(runner.names)
    assert not controller.runScenarios(incomplete)
    assert controller.status == "VALIDATION_ERROR" and runner.names == before
    assert controller._collection_content == previous
    assert runtime.backend_if_initialized is None and runtime.shutdown()


def test_offline_controller_views_drafts_failure_and_replay_state(qt_app, intraday_experiment, tmp_path, monkeypatch):
    path = tmp_path / "saved.json"
    write_strategy_experiment(intraday_experiment, path=path)
    runtime, runner = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    controller = owner.intradayResearchController
    with monkeypatch.context() as patch:
        patch.setattr(research, "load_intraday_dataset", lambda *a: pytest.fail("Open read data"))
        patch.setattr(research, "_fit", lambda *a: pytest.fail("Open fitted"))
        assert controller.openExperiment(str(path))
        runtime._poll()
        assert controller.status == "SUCCESS", controller.error
        assert controller.resultSummary["intraday_verification"] == "RECORDED"
        assert not controller.dataLoaded and controller.restoreRevision == 1
        view = controller.restoredPlan
        view["strategies"][0]["threshold"] = 123
        assert controller.restoredPlan["strategies"][0]["threshold"] == 1000000
        assert controller.selectCandidate(2) and controller.selectView(4)
        assert controller.tableModel.totalRows == 2
        assert controller.selectView(5) and controller.tableModel.totalRows == 740
        assert controller.changePage(1) and controller.tableModel.page == 2
        assert controller.saveExperiment(str(tmp_path / "copy.json"))
        runtime._poll()
        assert controller.status == "SUCCESS"
        assert (tmp_path / "copy.json").read_bytes() == path.read_bytes()
        assert controller.candidateIndex == 2 and controller.tableModel.page == 2
    assert controller.replayExperiment("")
    runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    assert controller.resultSummary["intraday_verification"] == "REPLAY_MATCH"
    previous = controller._content
    assert controller.replayExperiment(str(tmp_path / "missing-source.json"))
    runtime._poll()
    assert controller.status == "FAILED"
    assert controller.resultSummary["intraday_verification"] == "REPLAY_FAILED"
    assert controller._content == previous and controller.candidateIndex == 2 and controller.tableModel.page == 2
    assert controller.openExperiment(str(tmp_path / "missing-experiment.json"))
    runtime._poll()
    assert controller.status == "FAILED" and controller._content == previous and controller.restoreRevision == 1
    assert runtime.backend_if_initialized is None and runtime.shutdown()


def test_return_uncertainty_saved_selection_cache_units_and_proof(qt_app, parameter_grid_experiment,
                                                               tmp_path, monkeypatch):
    from market_vault.desktop.intraday_research import risk_value
    from market_vault.desktop.localization import I18nBridge
    from market_vault.desktop.preferences import DesktopPreferenceStore
    from market_vault.research import intraday_return_uncertainty as uncertainty

    path = tmp_path / "saved-grid.json"
    write_strategy_experiment(parameter_grid_experiment, path=path)
    analyze, calls = uncertainty.analyze_intraday_return_uncertainty, []

    def captured(snapshot, **indices):
        calls.append((snapshot.experiment_id, indices))
        return analyze(snapshot, **indices)

    def forbidden(*args, **kwargs):
        pytest.fail("Saved uncertainty must not load Q5, fit, or execute")

    monkeypatch.setattr(uncertainty, "analyze_intraday_return_uncertainty", captured)
    for name in ("load_intraday_dataset", "fit_ridge_rows", "run_intraday_execution"):
        monkeypatch.setattr(research, name, forbidden)
    runtime, _ = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    controller = owner.intradayResearchController
    assert controller.openExperiment(str(path))
    runtime._poll()
    assert controller.selectCandidate(8)  # cost 1, candidate 2 in the saved grid
    source = controller.selection_source()
    bound = (controller._content, controller.experimentPath, controller.resultSummary,
             controller.restoredPlan, controller.restoreRevision, owner.intradayFinalController.canFreeze)
    assert controller.selectView(17) and controller.busy
    assert controller._uncertainty_report is None  # completion applies on the owning thread
    runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    report = controller._uncertainty_report
    assert (report["cost_index"], report["candidate_index"], report["candidate_id"]) == (1, 2, source["candidate_id"])
    assert report["sample"]["sample_count"] == 10
    assert (report["sampling"]["block_days"], report["sampling"]["replications"], report["sampling"]["seed"]) == (3, 5000, 0)
    assert all(row["lower"] is None and row["upper"] is None and row["interval_unavailable_reason"]
               for row in report["statistics"])
    assert controller.tableModel.totalRows == 9
    paired = report["statistics"][2]
    row = next(row for row in controller._rows if row[:2] == ("PAIRED_EXCESS", "ARITHMETIC_MEAN"))
    assert row[2:4] == (risk_value(paired["mean"], "RATIO").removesuffix("%"), "PERCENTAGE_POINTS")
    assert next(row for row in controller._rows if row[:2] == ("STRATEGY", "ARITHMETIC_MEAN"))[2].endswith("%")
    summary = controller.uncertaintySummary
    summary["sampling"]["seed"] = 999
    assert controller.uncertaintySummary["sampling"]["seed"] == 0
    translations = I18nBridge(preference_store=DesktopPreferenceStore(root=tmp_path / "preferences"))
    for view, language in ((0, "en"), (17, "zh-CN"), (11, "en"), (17, "zh-CN")):
        assert controller.selectView(view) and translations.setLanguage(language)
    assert len(calls) == 1 and controller._uncertainty_report is report
    assert (controller._content, controller.experimentPath, controller.resultSummary,
            controller.restoredPlan, controller.restoreRevision, owner.intradayFinalController.canFreeze) == bound
    assert controller.selectCandidate(6) and controller.busy
    assert controller._uncertainty_report is None and controller.uncertaintySummary == {}
    runtime._poll()
    current = controller._uncertainty_report
    assert len(calls) == 2 and current["candidate_index"] == 0 and current["candidate_id"] != report["candidate_id"]
    assert controller.openExperiment(str(tmp_path / "missing.json"))
    runtime._poll()
    assert controller.status == "FAILED" and controller._uncertainty_report is current
    assert controller.uncertaintyError == "" and controller.experimentPath == str(path)
    assert controller.resultSummary["intraday_verification"] == "RECORDED"
    assert path.read_bytes() == parameter_grid_experiment.content
    assert runtime.backend_if_initialized is None and runtime.shutdown()


def test_return_uncertainty_worker_discards_stale_selection_and_recovers(qt_app, intraday_experiment,
                                                                      tmp_path, monkeypatch):
    runtime, runner = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    controller = owner.intradayResearchController
    controller._apply(intraday_experiment, opened=True)
    assert controller.selectView(17) and not controller.uncertaintyAvailable and not runner.names
    assert controller.saveExperiment(str(tmp_path / "saved.json"))
    runtime._poll()  # Save completes, then the now-saved selection can queue its analysis.
    assert controller.uncertaintyAvailable and controller.busy
    runtime._poll()
    assert controller._uncertainty_report["candidate_index"] == 0
    assert controller._uncertainty_report["statistics"][0]["mean"] == 0
    assert controller._uncertainty_report["statistics"][0]["interval_unavailable_reason"] == "ZERO_SAMPLE_VARIATION"
    pending = []

    def deferred(name, operation):
        future = Future()
        pending.append((name, future, operation))
        return future

    monkeypatch.setattr(runner, "submit", deferred)
    assert controller.selectCandidate(1) and len(pending) == 1
    assert controller.selectCandidate(2) and len(pending) == 1
    _, first, operation = pending.pop()
    first.set_result(operation())
    runtime._poll()
    assert controller._uncertainty_report is None and len(pending) == 1
    _, second, operation = pending.pop()
    second.set_result(operation())
    runtime._poll()
    assert controller._uncertainty_report["candidate_index"] == 2
    assert controller._uncertainty_report["candidate_id"] == controller.selection_source()["candidate_id"]
    assert controller.selectCandidate(1) and len(pending) == 1
    _, failed, _ = pending.pop()
    failed.set_exception(ValueError("uncertainty calculation failed"))
    runtime._poll()
    assert controller.status == "FAILED" and controller.uncertaintyError == "uncertainty calculation failed"
    assert controller._uncertainty_report is None and not pending
    assert controller.selectView(0) and controller.selectView(17) and not pending
    assert controller.retryUncertainty() and len(pending) == 1
    _, retried, operation = pending.pop()
    retried.set_result(operation())
    runtime._poll()
    assert controller.status == "SUCCESS" and controller.uncertaintyError == ""
    assert controller._uncertainty_report["candidate_index"] == 1
    assert controller.resultSummary["intraday_verification"] == "RECORDED"
    assert runtime.backend_if_initialized is None and runtime.shutdown()


def test_return_uncertainty_bad_account_and_exported_scenario_boundary(qt_app, intraday_experiment,
        desktop_execution_scenarios, tmp_path):
    from market_vault.research.strategy_experiment import StrategyExperiment
    from test_intraday_experiment import signed

    root = intraday_experiment.as_dict()
    root["report"]["groups"][0]["results"][1]["execution"]["trades"][0]["commission_total"] += .01
    partial = StrategyExperiment(signed(root))
    path = tmp_path / "partial.json"
    write_strategy_experiment(partial, path=path)
    runtime, runner = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    controller = owner.intradayResearchController
    assert controller.openExperiment(str(path))
    runtime._poll()
    assert controller.selectCandidate(1) and controller.selectView(17)
    runtime._poll()
    strategy, benchmark, paired = controller._uncertainty_report["statistics"]
    assert strategy["mean"] is None and strategy["mean_unavailable_reason"] == "RECORDED_CASH_RECONCILIATION_FAILED"
    assert benchmark["mean"] is not None and paired["mean_unavailable_reason"] == "STRATEGY_UNAVAILABLE"
    assert len(controller.uncertaintySummary["warnings"]) == 3
    controller._apply(desktop_execution_scenarios, path=str(tmp_path / "collection.json"), opened=True)
    before = list(runner.names)
    assert controller.selectView(17) and not controller.uncertaintyAvailable
    assert controller._uncertainty_report is None and runner.names == before
    child = tmp_path / "child.json"
    assert controller.exportScenario(str(child))
    runtime._poll()
    assert not controller.uncertaintyAvailable and controller._uncertainty_report is None
    assert controller.openExperiment(str(child))
    runtime._poll()
    assert controller.uncertaintyAvailable and controller.busy
    runtime._poll()
    assert controller.status == "SUCCESS" and controller._uncertainty_report["experiment_id"] == json.loads(child.read_bytes())["experiment_id"]
    assert not controller.scenariosLoaded and controller.resultSummary["intraday_verification"] == "RECORDED"
    assert runtime.backend_if_initialized is None and runtime.shutdown()


def test_family_bounds_complete_saved_cost_cache_units_and_source(qt_app, parameter_grid_experiment,
                                                                 tmp_path, monkeypatch):
    from market_vault.desktop.intraday_research import risk_value
    from market_vault.desktop.localization import I18nBridge
    from market_vault.desktop.preferences import DesktopPreferenceStore
    from market_vault.research import intraday_family_bounds as family
    from market_vault.research.strategy_experiment import StrategyExperiment
    from test_intraday_experiment import signed

    path, other_path = tmp_path / "family.json", tmp_path / "other-family.json"
    write_strategy_experiment(parameter_grid_experiment, path=path)
    root = parameter_grid_experiment.as_dict()
    root["name"] = "Another saved family"
    other = StrategyExperiment(signed(root))
    write_strategy_experiment(other, path=other_path)
    analyze, calls = family.analyze_intraday_family_bounds, []

    def captured(snapshot, **indices):
        calls.append((snapshot.experiment_id, indices))
        return analyze(snapshot, **indices)

    def forbidden(*args, **kwargs):
        pytest.fail("Saved family bounds must not load Q5, fit, or execute")

    monkeypatch.setattr(family, "analyze_intraday_family_bounds", captured)
    for name in ("load_intraday_dataset", "_fit", "fit_ridge_rows", "run_intraday_execution"):
        monkeypatch.setattr(research, name, forbidden)
    runtime, _ = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    controller = owner.intradayResearchController
    assert controller.openExperiment(str(path))
    runtime._poll()
    assert controller.selectCandidate(8)  # cost 1, candidate 2 does not define a subset
    bound = (controller._content, controller.experimentPath, controller.resultSummary,
             controller.restoredPlan, controller.restoreRevision, owner.intradayFinalController.canFreeze)
    assert controller.selectView(18) and controller.busy and controller._family_report is None
    runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    report = controller._family_report
    assert report["family_scope"] == "SAVED_COST_GROUP_ONLY" and report["historical_search_coverage"] == "UNKNOWN"
    assert report["cost_index"] == 1 and report["family_size"] == controller.tableModel.totalRows == 6
    assert [row["candidate_id"] for row in report["members"]] == [row["candidate_id"] for row in root["report"]["groups"][1]["results"]]
    assert [row["candidate_index"] for row in report["members"]] == list(range(6))
    assert report["sample"]["sample_count"] == 10 and report["family_inference"]["status"] == "UNAVAILABLE"
    assert report["family_inference"]["deduction"] is None
    assert (report["sampling"]["block_days"], report["sampling"]["replications"], report["sampling"]["seed"]) == (3, 5000, 0)
    assert all(row["mean_excess"] is not None and row["lower"] is None and row["bound_unavailable_reason"]
               for row in report["members"])
    for row, member in zip(controller._rows, report["members"], strict=True):
        assert row[0].startswith(str(member["candidate_index"]) + " · ") and row[1] == member["candidate_id"][:12]
        assert row[2] == risk_value(member["mean_excess"], "RATIO").removesuffix("%") and row[3] == "—"
        assert row[4:] == ("", member["bound_unavailable_reason"])
    summary = controller.familyBoundsSummary
    summary["sampling"]["seed"] = 99
    summary["members"].clear()
    assert controller.familyBoundsSummary["sampling"]["seed"] == 0 and len(controller.familyBoundsSummary["members"]) == 6
    translations = I18nBridge(preference_store=DesktopPreferenceStore(root=tmp_path / "preferences"))
    for view, language in ((0, "en"), (18, "zh-CN"), (11, "en"), (18, "zh-CN")):
        assert controller.selectView(view) and translations.setLanguage(language)
    assert len(calls) == 1 and controller._family_report is report
    assert (controller._content, controller.experimentPath, controller.resultSummary,
            controller.restoredPlan, controller.restoreRevision, owner.intradayFinalController.canFreeze) == bound
    assert controller.selectCandidate(11) and not controller.busy
    assert controller._family_report is report and len(calls) == 1
    assert controller.selectCandidate(2) and controller.busy and controller.familyBoundsSummary == {}
    runtime._poll()
    assert controller._family_report["cost_index"] == 0 and len(calls) == 2
    assert controller.openExperiment(str(other_path))
    runtime._poll()
    assert controller.busy and controller._family_report is None
    runtime._poll()
    current = controller._family_report
    assert current["experiment_id"] == other.experiment_id and len(calls) == 3
    assert controller.openExperiment(str(tmp_path / "missing.json"))
    runtime._poll()
    assert controller.status == "FAILED" and controller._family_report is current and controller.familyBoundsError == ""
    assert controller.experimentPath == str(other_path) and controller.resultSummary["intraday_verification"] == "RECORDED"
    assert path.read_bytes() == parameter_grid_experiment.content and other_path.read_bytes() == other.content
    assert runtime.backend_if_initialized is None and runtime.shutdown()


def test_family_bounds_worker_discards_stale_cost_and_retries(qt_app, parameter_grid_experiment,
                                                             tmp_path, monkeypatch):
    runtime, runner = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    controller = owner.intradayResearchController
    controller._apply(parameter_grid_experiment, opened=True)
    assert controller.selectView(18) and not controller.familyBoundsAvailable and not runner.names
    assert controller.saveExperiment(str(tmp_path / "saved.json"))
    runtime._poll()
    assert controller.familyBoundsAvailable and controller.busy
    runtime._poll()
    assert controller._family_report["cost_index"] == 0
    pending = []

    def deferred(name, operation):
        future = Future()
        pending.append((name, future, operation))
        return future

    monkeypatch.setattr(runner, "submit", deferred)
    assert controller.selectCandidate(6) and len(pending) == 1
    assert controller.selectCandidate(1) and len(pending) == 1
    _, stale, operation = pending.pop()
    stale.set_result(operation())
    runtime._poll()
    assert controller._family_report is None and len(pending) == 1
    assert controller.selectCandidate(2) and len(pending) == 1  # same cost while its family is in flight
    _, current, operation = pending.pop()
    current.set_result(operation())
    runtime._poll()
    assert controller._family_report["cost_index"] == 0 and controller._family_report["family_size"] == 6
    assert controller.selectCandidate(6) and len(pending) == 1
    _, failed, _ = pending.pop()
    failed.set_exception(ValueError("family analysis failed"))
    runtime._poll()
    assert controller.status == "FAILED" and controller.familyBoundsError == "family analysis failed"
    assert controller._family_report is None and not pending
    assert controller.selectCandidate(7) and controller.selectView(0) and controller.selectView(18) and not pending
    assert controller.familyBoundsError == "family analysis failed"
    assert controller.retryFamilyBounds() and len(pending) == 1
    _, retried, operation = pending.pop()
    retried.set_result(operation())
    runtime._poll()
    assert controller.status == "SUCCESS" and controller.familyBoundsError == ""
    assert controller._family_report["cost_index"] == 1 and controller._family_report["family_size"] == 6
    assert controller.resultSummary["intraday_verification"] == "RECORDED"
    assert runtime.backend_if_initialized is None and runtime.shutdown()


def test_family_bounds_unselected_invalid_member_is_retained(qt_app, parameter_grid_experiment, tmp_path):
    from market_vault.research.strategy_experiment import StrategyExperiment
    from test_intraday_experiment import signed

    root = parameter_grid_experiment.as_dict()
    members = root["report"]["groups"][1]["results"]
    bad_index = next(index for index, member in enumerate(members) if index != 0 and member["execution"]["trades"])
    members[bad_index]["execution"]["trades"][0]["commission_total"] += .01
    invalid = StrategyExperiment(signed(root))
    path, valid_path = tmp_path / "invalid-member.json", tmp_path / "valid-family.json"
    write_strategy_experiment(invalid, path=path)
    write_strategy_experiment(parameter_grid_experiment, path=valid_path)
    runtime, runner = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    controller = owner.intradayResearchController
    assert controller.openExperiment(str(path))
    runtime._poll()
    assert controller.selectCandidate(6) and controller.selectView(18)
    runtime._poll()
    report = controller._family_report
    assert report["family_inference"]["reason"] == "FAMILY_MEMBER_UNAVAILABLE"
    assert report["family_size"] == controller.tableModel.totalRows == 6
    assert all(member["lower"] is None for member in report["members"])
    assert report["members"][0]["mean_excess"] is not None
    bad = report["members"][bad_index]
    assert bad["mean_excess"] is None and bad["mean_unavailable_reason"] == "STRATEGY_UNAVAILABLE"
    assert "RECORDED_CASH_RECONCILIATION_FAILED" in bad["detail"]
    assert controller._rows[bad_index][4:] == ("STRATEGY_UNAVAILABLE", "STRATEGY_UNAVAILABLE")
    before = list(runner.names)
    assert controller.selectCandidate(6 + bad_index)
    assert controller._family_report is report and runner.names == before
    assert controller.openExperiment(str(valid_path))
    runtime._poll()
    runtime._poll()
    assert controller._family_report["experiment_id"] == parameter_grid_experiment.experiment_id
    assert controller._family_report["family_inference"]["reason"] == "INSUFFICIENT_DAILY_RETURNS"
    assert all(member["mean_excess"] is not None for member in controller._family_report["members"])
    assert path.read_bytes() == invalid.content and valid_path.read_bytes() == parameter_grid_experiment.content
    assert runtime.backend_if_initialized is None and runtime.shutdown()


def test_sequential_selection_complete_group_views_cache_and_source(qt_app, parameter_grid_experiment,
                                                                  tmp_path, monkeypatch):
    from market_vault.research import intraday_sequential_selection as sequential

    path = tmp_path / "saved-grid.json"
    write_strategy_experiment(parameter_grid_experiment, path=path)
    analyze, calls = sequential.analyze_intraday_sequential_selection, []

    def captured(snapshot, **options):
        calls.append((snapshot.experiment_id, options))
        return analyze(snapshot, **options)

    def forbidden(*args, **kwargs):
        pytest.fail("Saved sequential selection must not load Q5, fit, or execute")

    monkeypatch.setattr(sequential, "analyze_intraday_sequential_selection", captured)
    for name in ("load_intraday_dataset", "_fit", "fit_ridge_rows", "run_intraday_execution"):
        monkeypatch.setattr(research, name, forbidden)
    runtime, _ = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    controller = owner.intradayResearchController
    assert controller.openExperiment(str(path))
    runtime._poll()
    assert controller.selectCandidate(8)  # all six members of cost 1, not candidate 2 alone
    bound = (controller._content, controller.restoredPlan, controller.restoreRevision,
             controller.resultSummary, owner.intradayFinalController.canFreeze)
    assert controller.selectView(19) and controller.busy and controller._sequential_report is None
    runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    report = controller._sequential_report
    assert calls == [(parameter_grid_experiment.experiment_id, {"cost_index": 1, "minimum_history_days": 20})]
    assert report["family_size"] == 6 and report["family_scope"] == "SAVED_COST_GROUP_ONLY"
    assert report["historical_search_coverage"] == report["family_precommitment"] == "UNKNOWN"
    assert report["availability"]["unavailable_reason"] == "INSUFFICIENT_HISTORY_FOR_SELECTION"
    assert controller.selectSequentialView(1) and controller.tableModel.totalRows == 2
    assert all(row[8] == "WARMUP" and row[1:5] == ("—", "—", "—", "—") for row in controller._rows)
    assert controller.selectSequentialView(2) and controller.tableModel.totalRows == 12
    assert [row[2].split(" · ")[0] for row in controller._rows] == [str(i) for i in range(6)] * 2
    assert controller._rows[0][-1] == "NO_COMPLETED_HISTORY"
    assert controller.selectSequentialView(3) and controller.tableModel.totalRows == 48
    assert controller.selectSequentialView(4) and controller.tableModel.totalRows == 0
    assert controller.selectSequentialView(5) and controller.tableModel.totalRows == 0
    summary = controller.sequentialSummary
    assert summary["sequential_selection_id"] == report["sequential_selection_id"]
    assert [member["candidate_id"] for member in summary["members"]] == [member["candidate_id"] for member in report["members"]]
    summary["selection_rule"]["minimum_history_days"] = 999
    summary["folds"].clear()
    assert controller.sequentialSummary["selection_rule"]["minimum_history_days"] == 20
    assert len(controller.sequentialSummary["folds"]) == 2
    assert controller.selectCandidate(11) and controller.selectView(0) and controller.selectView(19)
    assert controller._sequential_report is report and len(calls) == 1
    assert (controller._content, controller.restoredPlan, controller.restoreRevision,
            controller.resultSummary, owner.intradayFinalController.canFreeze) == bound
    assert controller.selectCandidate(2) and controller.busy and controller.sequentialSummary == {}
    runtime._poll()
    assert controller._sequential_report["cost_index"] == 0 and len(calls) == 2
    current = controller._sequential_report
    assert controller.openExperiment(str(tmp_path / "missing.json"))
    runtime._poll()
    assert controller.status == "FAILED" and controller._sequential_report is current and controller.sequentialError == ""
    assert controller.experimentPath == str(path) and path.read_bytes() == parameter_grid_experiment.content
    assert runtime.backend_if_initialized is None and runtime.shutdown()


def test_sequential_selection_saved_boundary_stale_group_and_retry(qt_app, parameter_grid_experiment,
                                                                 tmp_path, monkeypatch):
    runtime, runner = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    controller = owner.intradayResearchController
    controller._apply(parameter_grid_experiment, opened=True)
    assert controller.selectView(19) and not controller.sequentialAvailable and not runner.names
    assert controller.saveExperiment(str(tmp_path / "saved.json"))
    runtime._poll()
    assert controller.sequentialAvailable and controller.busy
    runtime._poll()
    assert controller._sequential_report["cost_index"] == 0
    pending = []

    def deferred(name, operation):
        future = Future()
        pending.append((future, operation))
        return future

    monkeypatch.setattr(runner, "submit", deferred)
    assert controller.selectCandidate(6) and len(pending) == 1
    assert controller.selectCandidate(1) and len(pending) == 1
    stale, operation = pending.pop()
    stale.set_result(operation())
    runtime._poll()
    assert controller._sequential_report is None and len(pending) == 1
    assert controller.selectCandidate(2) and len(pending) == 1
    current, operation = pending.pop()
    current.set_result(operation())
    runtime._poll()
    assert controller._sequential_report["cost_index"] == 0
    assert controller.selectCandidate(6) and len(pending) == 1
    failed, _ = pending.pop()
    failed.set_exception(ValueError("sequential selection failed"))
    runtime._poll()
    assert controller.status == "FAILED" and controller.sequentialError == "sequential selection failed"
    assert controller._sequential_report is None and not pending
    assert controller.selectCandidate(7) and controller.selectSequentialView(2) and not pending
    assert controller.retrySequential() and len(pending) == 1
    retried, operation = pending.pop()
    retried.set_result(operation())
    runtime._poll()
    assert controller.status == "SUCCESS" and controller.sequentialError == ""
    assert controller._sequential_report["cost_index"] == 1 and controller.tableModel.totalRows == 12
    assert controller.resultSummary["intraday_verification"] == "RECORDED"
    assert runtime.backend_if_initialized is None and runtime.shutdown()


def test_signal_delay_saved_candidate_metrics_details_and_cache(qt_app, parameter_grid_experiment,
                                                               tmp_path, monkeypatch):
    from market_vault.research import intraday_signal_delay as delay

    path = tmp_path / "saved-grid.json"
    write_strategy_experiment(parameter_grid_experiment, path=path)
    analyze, calls = delay.analyze_intraday_signal_delay, []

    def captured(snapshot, **options):
        calls.append((snapshot.experiment_id, options))
        return analyze(snapshot, **options)

    def forbidden(*args, **kwargs):
        pytest.fail("Signal-delay stress must not load Q5 or fit; pure execution is required")

    monkeypatch.setattr(delay, "analyze_intraday_signal_delay", captured)
    for name in ("load_intraday_dataset", "_fit", "fit_ridge_rows"):
        monkeypatch.setattr(research, name, forbidden)
    runtime, _ = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    controller = owner.intradayResearchController
    assert controller.openExperiment(str(path))
    runtime._poll()
    assert controller.selectCandidate(8)  # cost 1, candidate 2
    bound = (controller._content, controller.restoredPlan, controller.restoreRevision,
             controller.resultSummary, owner.intradayFinalController.canFreeze)
    assert controller.selectView(20) and controller.busy and controller.signalDelaySummary == {}
    runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    report = controller._signal_delay_report
    assert calls == [(parameter_grid_experiment.experiment_id, {"cost_index": 1, "candidate_index": 2})]
    assert report["evidence"] == "RECORDED_PRICE_GRID_REEXECUTION"
    assert [row["delay_bars"] for row in report["scenarios"]] == [0, 1, 2]
    assert report["baseline"]["status"] == "AVAILABLE"
    assert all(row["matches"] for row in report["baseline"]["accounts"])
    assert controller.tableModel.totalRows == 60
    assert [(row[1], row[2]) for row in controller._rows[:6]] == [
        (str(i), side) for i in range(3) for side in ("STRATEGY", "BENCHMARK")]
    zero = report["scenarios"][0]["strategy"]["metrics"]["total_return"]["value"]
    delayed = report["scenarios"][1]["strategy"]["metrics"]["total_return"]["value"]
    assert controller._rows[2][3].endswith("%")
    assert controller._rows[2][4] == f"{(delayed - zero) * 100:.6g}"
    assert controller._rows[2][6] == "PERCENTAGE_POINTS"
    assert controller.selectSignalDelayDetail(2, 1)
    execution = report["scenarios"][2]["benchmark"]["execution"]
    assert controller.selectSignalDelayView(1) and controller.tableModel.totalRows == len(execution["daily"])
    assert controller.selectSignalDelayView(2) and controller.tableModel.totalRows == len(execution["trades"])
    assert controller._rows[0][7].endswith("%")
    assert controller.selectSignalDelayView(3) and controller.tableModel.totalRows == len(execution["ledger"])
    assert [(row[0], row[3]) for row in controller._rows[:4]] == [("0", "OPEN"), ("1", "CLOSE"), ("2", "OPEN"), ("3", "CLOSE")]
    assert controller.selectSignalDelayDetail(2, 0) and controller.selectSignalDelayView(4)
    signals = report["scenarios"][2]["strategy"]["signals"]["provenance"]
    assert controller.tableModel.totalRows == len(signals) == len(controller.signalDelaySignalNames)
    assert controller.selectSignalDelaySignal(len(signals) - 1)
    assert controller.signalDelayDetails["signal"] == signals[-1]
    summary = controller.signalDelaySummary
    summary["baseline"]["accounts"].clear()
    assert len(controller.signalDelaySummary["baseline"]["accounts"]) == 2
    assert controller.selectCandidate(8) and controller.selectView(0) and controller.selectView(20)
    assert controller._signal_delay_report is report and len(calls) == 1
    assert (controller._content, controller.restoredPlan, controller.restoreRevision,
            controller.resultSummary, owner.intradayFinalController.canFreeze) == bound
    assert controller.selectCandidate(9) and controller.busy and controller.signalDelaySummary == {}
    runtime._poll()
    assert controller._signal_delay_report["candidate_index"] == 3 and len(calls) == 2
    assert controller.signalDelaySignalIndex == 0
    assert controller.selectCandidate(3) and controller.busy  # same candidate, another cost
    runtime._poll()
    assert controller._signal_delay_report["cost_index"] == 0 and len(calls) == 3
    current = controller._signal_delay_report
    assert controller.openExperiment(str(tmp_path / "missing.json"))
    runtime._poll()
    assert controller.status == "FAILED" and controller._signal_delay_report is current and controller.signalDelayError == ""
    assert path.read_bytes() == parameter_grid_experiment.content
    assert controller.resultSummary["intraday_verification"] == "RECORDED"
    assert runtime.backend_if_initialized is None and runtime.shutdown()


def test_signal_delay_worker_saved_boundary_stale_candidate_source_and_retry(qt_app, parameter_grid_experiment,
                                                                           tmp_path, monkeypatch):
    from market_vault.research.strategy_experiment import StrategyExperiment
    from test_intraday_experiment import signed

    runtime, runner = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    controller = owner.intradayResearchController
    controller._apply(parameter_grid_experiment, opened=True)
    assert controller.selectView(20) and not controller.signalDelayAvailable and not runner.names
    assert controller.saveExperiment(str(tmp_path / "saved.json"))
    runtime._poll()
    assert controller.signalDelayAvailable and controller.busy
    runtime._poll()
    pending = []

    def deferred(name, operation):
        future = Future()
        pending.append((future, operation))
        return future

    monkeypatch.setattr(runner, "submit", deferred)
    assert controller.selectCandidate(1) and len(pending) == 1
    assert controller.selectCandidate(2) and len(pending) == 1
    stale, operation = pending.pop()
    stale.set_result(operation())
    runtime._poll()
    assert controller._signal_delay_report is None and len(pending) == 1
    current, operation = pending.pop()
    current.set_result(operation())
    runtime._poll()
    assert controller._signal_delay_report["candidate_index"] == 2
    assert controller.selectCandidate(8) and len(pending) == 1
    failed, _ = pending.pop()
    failed.set_exception(ValueError("delay stress failed"))
    runtime._poll()
    assert controller.status == "FAILED" and controller.signalDelayError == "delay stress failed"
    assert controller._signal_delay_report is None and not pending
    assert controller.selectSignalDelayDetail(2, 1) and controller.selectSignalDelayView(4) and not pending
    assert controller.selectView(0) and controller.selectView(20) and not pending
    assert controller.retrySignalDelay() and len(pending) == 1
    retried, operation = pending.pop()
    retried.set_result(operation())
    runtime._poll()
    assert controller.status == "SUCCESS" and controller.signalDelayError == ""
    assert controller._signal_delay_report["cost_index"] == 1
    assert controller.selectCandidate(9) and len(pending) == 1
    other_root = parameter_grid_experiment.as_dict()
    other_root["name"] = "Another saved DEV source"
    other = StrategyExperiment(signed(other_root))
    other_path = tmp_path / "other.json"
    write_strategy_experiment(other, path=other_path)
    controller._apply(other, path=str(other_path), opened=True)
    stale, _ = pending.pop()
    stale.set_exception(ValueError("obsolete source failed"))
    runtime._poll()
    assert controller.signalDelayError == "" and controller._signal_delay_report is None and len(pending) == 1
    current, operation = pending.pop()
    current.set_result(operation())
    runtime._poll()
    assert controller._signal_delay_report["experiment_id"] == other.experiment_id
    assert controller._content == other.content and controller.resultSummary["intraday_verification"] == "RECORDED"
    assert runtime.backend_if_initialized is None and runtime.shutdown()


def test_signal_delay_zero_reproduction_failure_keeps_all_scenarios(qt_app, parameter_grid_experiment,
                                                                  tmp_path):
    from market_vault.research.strategy_experiment import StrategyExperiment
    from test_intraday_experiment import signed

    source = parameter_grid_experiment.as_dict()
    source["report"]["groups"][1]["results"][2]["execution"]["ledger"][0]["reason"] = "CHANGED_SAVED_REASON"
    changed = StrategyExperiment(signed(source))
    path = tmp_path / "saved-grid.json"
    write_strategy_experiment(changed, path=path)
    runtime, _ = _runtime(tmp_path, [])
    owner = QuantResearchController(runtime)
    controller = owner.intradayResearchController
    assert controller.openExperiment(str(path))
    runtime._poll()
    assert controller.selectCandidate(8) and controller.selectView(20)
    runtime._poll()
    assert controller.status == "SUCCESS", controller.error
    summary = controller.signalDelaySummary
    assert summary["baseline"]["unavailable_reason"] == "ZERO_DELAY_REPRODUCTION_FAILED"
    assert summary["baseline"]["accounts"][0]["differing_fields"] == ["ledger"]
    assert summary["baseline"]["accounts"][1]["matches"]
    assert [row["delay_bars"] for row in summary["scenarios"]] == [0, 1, 2]
    assert all(row["status"] == "UNAVAILABLE" for row in summary["scenarios"])
    assert controller.tableModel.totalRows == 60
    assert all(row[3:5] == ("—", "—") and row[-1] == "ZERO_DELAY_REPRODUCTION_FAILED" for row in controller._rows)
    assert controller.selectSignalDelayDetail(2, 0)
    for index in (1, 2, 3):
        assert controller.selectSignalDelayView(index) and controller.tableModel.totalRows == 0
    assert controller.selectSignalDelayView(4) and controller.tableModel.totalRows > 0
    assert controller.signalDelayDetails["execution_id"] is None
    assert controller.signalDelayDetails["signals"]["source_count"] == controller.tableModel.totalRows
    assert path.read_bytes() == changed.content
    assert runtime.backend_if_initialized is None and runtime.shutdown()


def test_actual_qml_compare_models_pagination_save_open_replay_and_language(research_case, tmp_path):
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
root, data_path = Path(sys.argv[1]), sys.argv[2]
QQuickStyle.setStyle('Basic')
app = QGuiApplication([])
engine = QQmlApplicationEngine()
context = build_application_context(root / 'settings.yaml')
session = create_qml_application_session(context, engine, preference_store=DesktopPreferenceStore(root=root / 'preferences'))
engine.load(QUrl.fromLocalFile(str(Path.cwd() / 'src/market_vault/desktop/qml/Main.qml')))
assert engine.rootObjects()
window = engine.rootObjects()[0]
window.setWidth(1100); window.setHeight(700)
owner = session.context_properties['quantResearchController']
controller = owner.intradayResearchController
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
def choose(name, index):
    obj = find(name)
    combo = nested(obj, 'PixelComboBox')
    window.requestActivate(); QTest.qWait(30)
    combo.forceActiveFocus()
    app.processEvents()
    QTest.keyClick(window, Qt.Key_Home)
    for _ in range(index): QTest.keyClick(window, Qt.Key_Down)
    app.processEvents()
    assert obj.property('currentIndex') == index, (name, obj.property('currentIndex'))
def complete(target=controller):
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
click('quantIntradayTab')
fill('intradayDataPath', data_path)
click('intradayInspectButton'); complete(owner)
click('intradayComparisonTab'); QTest.qWait(50)
assert '2025-03-10' in find('intradayResearchBoundaries').property('text')
assert '2025-03-25' in find('intradayResearchBoundaries').property('text')
click('intradayRunComparisonButton')
assert controller.status == 'VALIDATION_ERROR' and not controller.busy
click('intradayResearchSettingsButton'); QTest.qWait(50)
assert find('intradayResearchCommission').property('text') == ''
assert find('intradayResearchSlippage').property('text') == ''
fill('intradayResearchCommission', '10'); fill('intradayResearchSlippage', '5')
assert window.grabWindow().save(str(root / 'intraday-research-settings.png'))
click('intradayResearchSettingsDone')
click('intradayRunComparisonButton'); complete()
assert len(controller.candidateNames) == 3 and controller.resultSummary['intraday_eval_days'] == '10'
assert controller.resultSummary['intraday_verification'] == 'COMPUTED'
choose('intradayResearchCandidate', 2)
assert controller.candidateIndex == 2
choose('intradayResearchView', 4)
assert controller.tableModel.totalRows == 2
choose('intradayResearchView', 2)
assert controller.tableModel.totalRows == 1560
table = find('intradayResearchTable')
assert table.height() >= 100, table.height()
next_button = next(obj for obj in table.findChildren(QObject) if obj.property('glyph') == 'next' and obj.metaObject().indexOfSignal('clicked()') >= 0)
click_obj(next_button)
assert controller.tableModel.page == 2
click('intradayResearchSettingsButton'); QTest.qWait(30)
fill('intradayResearchMaxHold', '9')
assert session.i18n.setLanguage('zh-CN'); assert session.i18n.setLanguage('en')
assert find('intradayResearchMaxHold').property('text') == '9'
assert controller.tableModel.page == 2 and controller.candidateIndex == 2
click('intradayResearchSettingsDone')
saved = root / 'research.json'
click('intradayExperimentSaveButton'); file_selected('intradayExperimentSaveDialog', saved)
record = json.loads(saved.read_bytes())
assert record['plan']['execution']['max_hold_bars'] == 12
assert controller.tableModel.page == 2
click('intradayExperimentReplayButton'); complete()
assert controller.resultSummary['intraday_verification'] == 'REPLAY_MATCH'
assert find('intradayResearchMaxHold').property('text') == '9'
assert controller.tableModel.page == 2 and controller.candidateIndex == 2
click('intradayExperimentOpenButton'); file_selected('intradayExperimentOpenDialog', saved)
assert controller.restoreRevision == 1 and controller.resultSummary['intraday_verification'] == 'RECORDED'
assert find('intradayResearchMaxHold').property('text') == '12'
assert find('intradayResearchCommission').property('text') == '10'
# Presentation-only A -> B -> A source/default notifications, after the real
# source/research/Save/Open/Replay workflow above. No synthetic source is read
# or offered to the execution API by this UI state regression.
settings = find('intradayResearchSettings')
options = settings.property('featureOptions')
if hasattr(options, 'toVariant'): options = options.toVariant()
assert options == controller.featureNames
original_id, original_defaults = controller.sourceId, controller.defaults
controller._source_id = 'b' * 64
controller._defaults = {**original_defaults, 'data_id': controller._source_id}
controller.changed.emit(); app.processEvents()
assert settings.property('dataId') == 'b' * 64
controller._source_id, controller._defaults = 'c' * 64, {}
controller.changed.emit(); app.processEvents()
assert settings.property('dataId') == 'c' * 64
assert find('intradayResearchTrainEnd').property('text') == ''
assert find('intradayResearchFeatures').property('text') == 'return_2'
controller._source_id, controller._defaults = original_id, original_defaults
controller.changed.emit(); app.processEvents()
assert settings.property('dataId') == original_id
assert session.i18n.setLanguage('zh-CN')
choose('intradayResearchCandidate', 2); choose('intradayResearchView', 2)
assert window.grabWindow().save(str(root / 'intraday-research-ui.png'))
# The saved 10-day DEV sample reaches Q18's real unavailable path at the fixed
# 20-day default. Use the open popup so traversing other detail views does not
# initiate their separate analyses.
combo = nested(find('intradayResearchView'), 'PixelComboBox')
click_obj(combo)
QTest.keyClick(window, Qt.Key_Home)
for _ in range(19): QTest.keyClick(window, Qt.Key_Down)
QTest.keyClick(window, Qt.Key_Return)
complete()
assert controller.viewIndex == 19 and controller.sequentialAvailable
assert controller._sequential_report['selection_rule']['minimum_history_days'] == 20
assert controller._sequential_report['availability']['unavailable_reason'] == 'INSUFFICIENT_HISTORY_FOR_SELECTION'
assert '所需历史之后没有后续折' in find('intradaySequentialAvailability').property('text')
assert '不能进入 Freeze/TEST' in find('intradaySequentialNotice').property('text')
flick = find('intradayResearchScroll').property('contentItem')
picker = find('intradaySequentialView')
for _ in range(2):
    rect = picker.mapRectToItem(flick, picker.boundingRect())
    flick.setProperty('contentY', min(max(0, flick.property('contentY') + rect.bottom() - flick.height()),
                                    max(0, flick.property('contentHeight') - flick.height())))
    QTest.qWait(30)
click_obj(nested(picker, 'PixelComboBox'))
QTest.keyClick(window, Qt.Key_Home)
QTest.keyClick(window, Qt.Key_Down); QTest.keyClick(window, Qt.Key_Down)
QTest.keyClick(window, Qt.Key_Return); QTest.qWait(30)
assert controller.sequentialViewIndex == 2 and controller.tableModel.totalRows == 6
captured_id = controller._sequential_report['sequential_selection_id']
assert session.i18n.setLanguage('en')
assert controller._sequential_report['sequential_selection_id'] == captured_id
assert 'cannot enter Freeze/TEST' in find('intradaySequentialNotice').property('text')
assert saved.read_bytes() == controller._content
assert session.runtime.backend_if_initialized is None and session.runtime.shutdown()
engine.deleteLater(); app.processEvents()
print('REAL_INTRADAY_RESEARCH_WORKFLOW_OK')
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(data.path)], cwd=ROOT,
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software", "PYTHONPATH": str(ROOT / "src")},
                            capture_output=True, text=True, timeout=360)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "REAL_INTRADAY_RESEARCH_WORKFLOW_OK" in result.stdout
    assert "ReferenceError" not in result.stderr and "TypeError" not in result.stderr
