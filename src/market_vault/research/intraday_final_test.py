"""Explicit candidate freezing and one independent intraday TEST evaluation.

Freeze reads a saved development experiment, without data I/O or training.
Run verifies the frozen source and Q5 data, then fits at most one final model.
FullReplay additionally reproduces every raw development result.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from ..backtest.intraday import _inputs, run_intraday_execution
from . import intraday_research as research
from .intraday_backtest import execution_views, intraday_data_path, parse_execution_policy, rule_decisions
from .intraday_data import digest, load_intraday_dataset
from .intraday_experiment import INTRADAY_EXPERIMENT_VERSION, _count
from .strategy_comparison import RidgeStrategy
from .strategy_config import parse_strategy_specs
from .strategy_experiment import StrategyExperiment, canonical_json, environment_versions, load_strategy_experiment


INTRADAY_SELECTION_VERSION = "market-vault-intraday-selection-v1"
INTRADAY_SELECTION_PLAN_VERSION = "market-vault-intraday-selection-plan-v1"
INTRADAY_SELECTION_RESULT_VERSION = "market-vault-intraday-selection-result-v1"
INTRADAY_TEST_EXPERIMENT_VERSION = "market-vault-intraday-test-v1"
INTRADAY_TEST_PLAN_VERSION = "market-vault-intraday-test-plan-v1"
INTRADAY_FINAL_TEST_VERSION = "market-vault-intraday-final-test-v1"
INTRADAY_FINAL_CONTEXT_VERSION = "market-vault-intraday-final-context-v1"
INTRADAY_FINAL_RESULT_VERSION = "market-vault-intraday-final-test-result-v1"
SOURCE_VERSIONS = {
    "data": research.INTRADAY_DATA_VERSION, "research": research.INTRADAY_RESEARCH_VERSION,
    "walk_forward": research.INTRADAY_WALK_FORWARD_VERSION, "execution": research.INTRADAY_EXECUTION_VERSION,
    "cost": research.INTRADAY_COST_VERSION, "daily_risk": research.INTRADAY_DAILY_RISK_VERSION,
    "benchmark": research.INTRADAY_BENCHMARK_VERSION,
}
OPTIONAL_SOURCE_VERSIONS = {"ridge": research.RIDGE_BASELINE_VERSION, "composite": research.COMPOSITE_RULE_VERSION}


def _new_experiment(*, version, mode, data_id, versions, plan, report, name="", notes=""):
    root = {"artifact_schema_version": version, "dataset_id": data_id, "evaluation_mode": mode,
            "algorithm_versions": versions, "environment": environment_versions(),
            "plan": plan, "report": report, "name": name, "notes": notes}
    root["experiment_id"] = digest(root)
    return StrategyExperiment(canonical_json(root))


def _selection_root(selection: StrategyExperiment) -> dict:
    if type(selection) is not StrategyExperiment:
        raise ValueError("an immutable selection experiment is required")
    root = selection.as_dict()
    if root["artifact_schema_version"] != INTRADAY_SELECTION_VERSION:
        raise ValueError("a frozen intraday selection experiment is required")
    return root


def current_selection_versions(recorded: dict) -> dict:
    return {**SOURCE_VERSIONS, **{key: value for key, value in OPTIONAL_SOURCE_VERSIONS.items() if key in recorded},
            "selection": INTRADAY_SELECTION_VERSION}


def final_algorithm_versions(selection_root: dict) -> dict:
    """Keys follow the selected strategy; source-wide versions stay in selection."""
    source = selection_root["algorithm_versions"]
    versions = {key: source[key] for key in ("data", "execution", "cost", "daily_risk", "benchmark", "selection")}
    kind = selection_root["report"]["candidate"]["strategy"]["kind"]
    if kind == "RIDGE":
        versions["ridge"] = source["ridge"]
    elif kind == "COMPOSITE_RULE":
        versions["composite"] = source["composite"]
    return {**versions, "final_test": INTRADAY_FINAL_TEST_VERSION, "final_context": INTRADAY_FINAL_CONTEXT_VERSION}


def _selection_report(source: dict, plan: dict) -> dict:
    if source["artifact_schema_version"] != INTRADAY_EXPERIMENT_VERSION:
        raise ValueError("the selection source must be an intraday development experiment")
    reference, selected = plan["source_experiment"], plan["selection"]
    report = source["report"]
    if reference["experiment_id"] != source["experiment_id"] or reference["research_id"] != report["research_id"]:
        raise ValueError("source experiment identity differs from the frozen selection")
    cost, index = selected["cost_index"], selected["candidate_index"]
    if cost >= len(report["groups"]) or index >= len(report["groups"][cost]["results"]):
        raise ValueError("selected cost or candidate index is outside the saved experiment")
    group = report["groups"][cost]
    candidate = group["results"][index]
    if candidate["candidate_id"] != selected["candidate_id"]:
        raise ValueError("selected candidate identity differs from the saved experiment")
    context = report["context"]
    comparison = source["plan"].get("comparison_plan", source["plan"])
    result = {
        "result_schema_version": INTRADAY_SELECTION_RESULT_VERSION, "version": INTRADAY_SELECTION_VERSION,
        "status": "FROZEN", "evaluation_scope": "DEVELOPMENT_MANUAL_SINGLE_SELECTION",
        "data_id": source["dataset_id"], "plan_sha256": digest(plan),
        "context": {"source_context_id": context["context_id"], "intraday_data_path": comparison["intraday_data_path"],
                    **{key: context[key] for key in ("symbol", "interval", "feature_fields", "target_horizon_bars", "split")}},
        "candidate": {"strategy": candidate["strategy"], "axis_values": candidate["axis_values"],
                      "execution_policy": group["execution_policy"]},
        "benchmark_definition": dict(research.BENCHMARK_DEFINITION),
    }
    result["selection_id"] = digest(result)
    return result


def _source_path(value: str | Path) -> Path:
    if not isinstance(value, (str, Path)):
        raise ValueError("an explicit source experiment file is required")
    return intraday_data_path(str(value))


def freeze_intraday_candidate(source_experiment_path: str | Path, *, expected_experiment_id: str,
                              cost_index: int, candidate_index: int, expected_candidate_id: str,
                              name: str = "", notes: str = "") -> StrategyExperiment:
    """Freeze one manually selected saved result, not an editor draft or winner."""
    research._identity(expected_experiment_id, "expected source experiment ID")
    research._identity(expected_candidate_id, "expected candidate ID")
    _count(cost_index, "cost index")
    _count(candidate_index, "candidate index")
    path = _source_path(source_experiment_path)
    source = load_strategy_experiment(path).as_dict()
    if source["artifact_schema_version"] != INTRADAY_EXPERIMENT_VERSION:
        raise ValueError("freeze requires a saved intraday development experiment")
    if source["algorithm_versions"] != research.research_algorithm_versions(source["plan"]):
        raise ValueError("recorded source algorithms differ; no data was read or model fitted")
    plan = {"plan_schema_version": INTRADAY_SELECTION_PLAN_VERSION,
            "source_experiment": {"path": str(path), "experiment_id": expected_experiment_id,
                                  "research_id": source["report"]["research_id"]},
            "selection": {"cost_index": cost_index, "candidate_index": candidate_index, "candidate_id": expected_candidate_id}}
    report = _selection_report(source, plan)
    return _new_experiment(version=INTRADAY_SELECTION_VERSION, mode="INTRADAY_SELECTION",
                           data_id=source["dataset_id"], versions={**source["algorithm_versions"], "selection": INTRADAY_SELECTION_VERSION},
                           plan=plan, report=report, name=name, notes=notes)


def _bound_source(root: dict, *, source_experiment_file=None) -> dict:
    """Current-version and complete source/config binding, before data or fit."""
    if root["algorithm_versions"] != current_selection_versions(root["algorithm_versions"]):
        raise ValueError("recorded selection algorithms differ; no source was read or model fitted")
    path = source_experiment_file if source_experiment_file is not None else root["plan"]["source_experiment"]["path"]
    source = load_strategy_experiment(_source_path(path)).as_dict()
    actual = _selection_report(source, root["plan"])
    if root["algorithm_versions"] != {**source["algorithm_versions"], "selection": INTRADAY_SELECTION_VERSION}:
        raise ValueError("source algorithm versions differ from the frozen selection")
    if source["algorithm_versions"] != research.research_algorithm_versions(source["plan"]):
        raise ValueError("recorded source algorithms differ; no data was read or model fitted")
    if canonical_json(actual) != canonical_json(root["report"]):
        raise ValueError("complete frozen selection report differs from its source")
    return source


def _load_bound_data(root: dict, *, intraday_data_file=None):
    locator = root["report"]["context"]["intraday_data_path"]
    data = load_intraday_dataset(intraday_data_file if intraday_data_file is not None else locator)
    if data.data_id != root["dataset_id"]:
        raise ValueError("intraday data identity differs from the frozen selection; no model was fitted")
    return data


def _evaluate_final_test(root: dict, data) -> dict:
    """Internal evaluation with data verified in this action, never a public bypass."""
    frozen = root["report"]
    recorded = frozen["context"]
    data_root = data.as_dict()
    report = data_root["report"]
    ends = dict(zip(("train_end_day", "validation_end_day", "test_end_day"),
                    (recorded["split"][part][-1] for part in ("TRAIN", "VALIDATION", "TEST")), strict=True))
    parts = research.day_partitions(report, ends)
    if (data.data_id != root["dataset_id"] or parts != recorded["split"]
            or report["symbol"] != recorded["symbol"] or report["interval"] != recorded["interval"]
            or data_root["plan"]["target_horizon_bars"] != recorded["target_horizon_bars"]
            or any(f not in report["feature_names"] for f in recorded["feature_fields"])):
        raise ValueError("verified intraday context differs from the frozen selection; no model was fitted")
    days = tuple(parts["TEST"])
    sessions, prices = execution_views(report, trading_days=days)
    boundary = sessions[0]["open_time"]
    rows, purged = research.training_rows(report, tuple(parts["TRAIN"] + parts["VALIDATION"]), boundary)
    observations = tuple(r for r in report["observations"] if r["status"] == "READY" and r["trading_day"] in days)
    if not observations:
        raise ValueError("TEST has no READY observations")
    policy = parse_execution_policy(frozen["candidate"]["execution_policy"])
    _inputs(sessions, prices, (), report["interval"], policy)
    context = {"version": INTRADAY_FINAL_CONTEXT_VERSION, "data_id": data.data_id,
               "selection_id": frozen["selection_id"], "symbol": report["symbol"], "interval": report["interval"],
               "feature_fields": recorded["feature_fields"], "target_horizon_bars": recorded["target_horizon_bars"],
               "split": parts, "training_boundary": boundary,
               "training_keys": [row["observation_key"] for row, _ in rows], "purged_keys": list(purged),
               "test_keys": [r["observation_key"] for r in observations]}
    context["context_id"] = digest(context)
    strategy = parse_strategy_specs([frozen["candidate"]["strategy"]])[0]
    model, errors = None, None
    if type(strategy) is RidgeStrategy:
        model, scores = research.fit_ridge_rows(rows, observations, recorded["feature_fields"], strategy.alpha, boundary=boundary)
        predictions = [{**{key: row[key] for key in ("observation_key", "trading_day", "slot", "decision_time")},
                        "score": score, "target": "LONG" if score > strategy.threshold else "FLAT"}
                       for row, score in zip(observations, scores, strict=True)]
        errors = research.prediction_metrics(predictions, report)
    else:
        predictions = list(rule_decisions(list(observations), strategy, feature_names=tuple(recorded["feature_fields"])))
    execution = run_intraday_execution(sessions=sessions, prices=prices, decisions=tuple(predictions),
                                       interval=report["interval"], policy=policy)
    result = {"result_schema_version": INTRADAY_FINAL_RESULT_VERSION, "version": INTRADAY_FINAL_TEST_VERSION,
              "status": "SUCCESS", "evaluation_scope": "FROZEN_SINGLE_CANDIDATE_TEST",
              "selection_experiment_id": root["experiment_id"], "selection_id": frozen["selection_id"],
              "data_id": data.data_id, "context": context, "strategy": frozen["candidate"]["strategy"],
              "execution_policy": asdict(policy), "model": model, "predictions": predictions,
              "prediction_metrics": errors, "execution": execution, "risk": research.intraday_daily_risk(execution),
              "benchmark": research.benchmark_execution(report, days, policy)}
    result["final_test_id"] = digest(result)
    return result


def run_intraday_final_test(selection: StrategyExperiment, *, source_experiment_file: str | Path | None = None,
                           intraday_data_file: str | Path | None = None) -> dict:
    """Verify source/config, load Q5 once, then fit one TRAIN+VALIDATION model."""
    root = _selection_root(selection)
    _bound_source(root, source_experiment_file=source_experiment_file)
    data = _load_bound_data(root, intraday_data_file=intraday_data_file)
    return _evaluate_final_test(root, data)


def create_intraday_test_experiment(selection: StrategyExperiment, report: dict, *,
                                   name: str = "", notes: str = "") -> StrategyExperiment:
    root = _selection_root(selection)
    return _new_experiment(version=INTRADAY_TEST_EXPERIMENT_VERSION, mode="INTRADAY_TEST",
                           data_id=root["dataset_id"], versions=final_algorithm_versions(root),
                           plan={"plan_schema_version": INTRADAY_TEST_PLAN_VERSION, "selection": root},
                           report=report, name=name, notes=notes)


def replay_intraday_final_experiment(snapshot: StrategyExperiment, *, source_experiment_file: str | Path | None = None,
                                    intraday_data_file: str | Path | None = None) -> dict:
    """Compare whole source development and, for TEST, the whole final report."""
    if type(snapshot) is not StrategyExperiment:
        raise ValueError("an immutable selection or TEST experiment is required")
    saved = snapshot.as_dict()
    if saved["artifact_schema_version"] not in (INTRADAY_SELECTION_VERSION, INTRADAY_TEST_EXPERIMENT_VERSION):
        raise ValueError("a frozen intraday selection or TEST experiment is required")
    is_test = saved["artifact_schema_version"] == INTRADAY_TEST_EXPERIMENT_VERSION
    selection = saved["plan"]["selection"] if is_test else saved
    if is_test and saved["algorithm_versions"] != final_algorithm_versions(selection):
        raise ValueError("recorded final TEST algorithms differ; no source was read or model fitted")
    source = _bound_source(selection, source_experiment_file=source_experiment_file)
    data = _load_bound_data(selection, intraday_data_file=intraday_data_file)
    normalized, children, values = research.expand_intraday_plan(source["plan"], recorded=True)
    prepared = research._prepare_intraday_research(children[0], data=data)
    actual_source = research._evaluate_intraday_research(normalized, children, values, prepared)
    if canonical_json(actual_source) != canonical_json(source["report"]):
        raise ValueError("replay complete source development report mismatch")
    actual_selection = _selection_report(source, selection["plan"])
    if canonical_json(actual_selection) != canonical_json(selection["report"]):
        raise ValueError("replay complete selection report mismatch")
    result = {"experiment_id": saved["experiment_id"], "data_id": data.data_id, "report_matches": True,
              "source_report_matches": True, "selection_report_matches": True,
              "source_report_sha256": digest(actual_source), "selection_report_sha256": digest(actual_selection)}
    if is_test:
        actual = _evaluate_final_test(selection, data)
        if canonical_json(actual) != canonical_json(saved["report"]):
            raise ValueError("replay complete final TEST report mismatch")
        result.update(final_report_matches=True, expected_report_sha256=digest(saved["report"]),
                      actual_report_sha256=digest(actual), final_test_id=actual["final_test_id"])
    else:
        result.update(expected_report_sha256=digest(saved["report"]), actual_report_sha256=digest(actual_selection))
    return result
