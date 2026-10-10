"""Finite DEV execution policies over one verified common research context.

Each saved scenario contains an ordinary Q7 experiment. The collection adds
cross-scenario bindings, not a new execution kernel or a second TEST workflow.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from . import intraday_research as research
from .intraday_backtest import execution_views, parse_execution_policy
from .intraday_data import digest, object_fields
from .intraday_experiment import (INTRADAY_EXPERIMENT_VERSION, INTRADAY_EXPERIMENT_V2_VERSION,
                                  _array, _count, _hash, create_intraday_experiment)
from .strategy_experiment import StrategyExperiment, canonical_json, environment_versions


INTRADAY_EXECUTION_SCENARIOS_VERSION = "market-vault-intraday-execution-scenarios-v1"
INTRADAY_EXECUTION_SCENARIOS_PLAN_VERSION = "market-vault-intraday-execution-scenarios-plan-v1"
INTRADAY_EXECUTION_SCENARIOS_RESULT_VERSION = "market-vault-intraday-execution-scenarios-result-v1"
INTRADAY_EXECUTION_SCENARIOS_V2_VERSION = "market-vault-intraday-execution-scenarios-v2"
INTRADAY_EXECUTION_SCENARIOS_PLAN_V2_VERSION = "market-vault-intraday-execution-scenarios-plan-v2"
INTRADAY_EXECUTION_SCENARIOS_RESULT_V2_VERSION = "market-vault-intraday-execution-scenarios-result-v2"
INTRADAY_EXECUTION_SCENARIOS_VERSIONS = (INTRADAY_EXECUTION_SCENARIOS_VERSION, INTRADAY_EXECUTION_SCENARIOS_V2_VERSION)
INTRADAY_EXECUTION_SCENARIOS_PLAN_VERSIONS = (INTRADAY_EXECUTION_SCENARIOS_PLAN_VERSION, INTRADAY_EXECUTION_SCENARIOS_PLAN_V2_VERSION)


def _version(plan):
    return (INTRADAY_EXECUTION_SCENARIOS_V2_VERSION if research.is_intraday_plan_v2(plan["comparison_plan"])
            else INTRADAY_EXECUTION_SCENARIOS_VERSION)


def _result_version(plan):
    return (INTRADAY_EXECUTION_SCENARIOS_RESULT_V2_VERSION if research.is_intraday_plan_v2(plan["comparison_plan"])
            else INTRADAY_EXECUTION_SCENARIOS_RESULT_VERSION)


def normalize_intraday_execution_scenarios_plan(plan: dict, *, base: Path | None = None,
                                               recorded: bool = False) -> dict:
    """Validate every explicit scenario and the 64-evaluation bound before I/O."""
    object_fields(plan, {"plan_schema_version", "comparison_plan", "execution_scenarios"}, "execution-scenarios plan")
    if plan["plan_schema_version"] not in INTRADAY_EXECUTION_SCENARIOS_PLAN_VERSIONS:
        raise ValueError("unsupported execution-scenarios plan version")
    comparison = research.normalize_intraday_research_plan(plan["comparison_plan"], base=base, recorded=recorded)
    if ((plan["plan_schema_version"] == INTRADAY_EXECUTION_SCENARIOS_PLAN_V2_VERSION)
            != research.is_intraday_plan_v2(comparison)):
        raise ValueError("execution-scenarios and comparison plan versions must agree")
    scenarios = _array(plan["execution_scenarios"], "execution scenarios")
    if not scenarios or len(scenarios) * len(comparison["strategies"]) > research.MAX_DIAGNOSTIC_EVALUATIONS:
        raise ValueError("explicit execution scenarios require between 1 and 64 strategy evaluations")
    result, names, policies = [], set(), set()
    for scenario in scenarios:
        object_fields(scenario, {"name", "execution"}, "execution scenario")
        name = scenario["name"]
        if type(name) is not str or not name or name != name.strip() or name in names:
            raise ValueError("scenario names must be unique nonempty trimmed strings")
        policy = asdict(parse_execution_policy(scenario["execution"]))
        key = canonical_json(policy)
        if key in policies:
            raise ValueError("execution scenario policies must be unique after normalization")
        names.add(name)
        policies.add(key)
        result.append({"name": name, "execution": policy})
    return {"plan_schema_version": plan["plan_schema_version"],
            "comparison_plan": comparison, "execution_scenarios": result}


def _children(plan):
    return tuple({**plan["comparison_plan"], "execution": scenario["execution"]}
                 for scenario in plan["execution_scenarios"])


def _versions(plan):
    return {**research.research_algorithm_versions(plan["comparison_plan"]),
            "execution_scenarios": _version(plan)}


def _shared_evidence(child):
    report = child["report"]
    group = report["groups"][0]
    prices = None
    for value in [*group["results"], group["benchmark"]]:
        execution = value["execution"]
        evidence = {"price_evidence_id": execution["price_evidence_id"],
                    "sessions": [{key: day[key] for key in ("trading_day", "open_time", "close_time")}
                                 for day in execution["daily"]],
                    "bars": [{key: row[key] for key in
                              ("trading_day", "slot", "timestamp", "phase", "row_version_id", "mark_price")}
                             for row in execution["ledger"]]}
        if prices is not None and canonical_json(evidence) != canonical_json(prices):
            raise ValueError("all candidates and benchmarks must share complete recorded prices and session clocks")
        prices = evidence
    return {"context": report["context"],
            "predictions": [{key: result[key] for key in ("predictions", "fold_models", "prediction_metrics")}
                            for result in group["results"]],
            "prices_and_sessions": prices}


def validate_intraday_execution_scenarios_root(root):
    """Offline grammar and complete common-context bindings for every child."""
    if root["evaluation_mode"] != "INTRADAY_EXECUTION_SCENARIOS":
        raise ValueError("execution-scenarios artifact mode differs")
    _hash(root, "experiment_id")
    research._identity(root["dataset_id"], "data_id")
    plan = normalize_intraday_execution_scenarios_plan(root["plan"], recorded=True)
    if root["artifact_schema_version"] != _version(plan):
        raise ValueError("execution-scenarios artifact and plan versions must agree")
    if canonical_json(plan) != canonical_json(root["plan"]):
        raise ValueError("saved execution-scenarios plan must be normalized")
    versions = object_fields(root["algorithm_versions"], _versions(plan), "algorithm versions")
    environment = object_fields(root["environment"], {"market_vault", "python", "pandas", "pyarrow"}, "environment")
    if any(type(value) is not str or not value for value in (*versions.values(), *environment.values())):
        raise ValueError("recorded algorithm/environment versions must be nonempty strings")
    if type(root["name"]) is not str or type(root["notes"]) is not str:
        raise ValueError("experiment name and notes must be strings")
    report = object_fields(root["report"], {"result_schema_version", "version", "status", "evaluation_scope",
        "data_id", "plan_sha256", "evaluation_count", "scenarios", "scenarios_id"}, "execution-scenarios report")
    _hash(report, "scenarios_id")
    children = _children(plan)
    if (report["result_schema_version"] != _result_version(plan)
            or report["version"] != versions["execution_scenarios"] or report["status"] != "SUCCESS"
            or report["evaluation_scope"] != "DEVELOPMENT_WALK_FORWARD_ONLY"
            or report["data_id"] != root["dataset_id"] or report["data_id"] != plan["comparison_plan"]["data_id"]
            or report["plan_sha256"] != digest(plan)
            or _count(report["evaluation_count"], "evaluation count") != len(children) * len(children[0]["strategies"])):
        raise ValueError("execution-scenarios report plan, count, data or scope binding differs")
    scenarios = _array(report["scenarios"], "saved scenarios")
    if len(scenarios) != len(children):
        raise ValueError("every declared scenario must have one complete child experiment")
    common = None
    for index, (scenario, child_plan) in enumerate(zip(scenarios, children, strict=True)):
        object_fields(scenario, {"scenario_index", "name", "experiment"}, "saved scenario")
        if (_count(scenario["scenario_index"], "scenario index") != index
                or scenario["name"] != plan["execution_scenarios"][index]["name"]):
            raise ValueError("saved scenario names and indices must preserve input order")
        child = scenario["experiment"]
        # Check the narrow child type before invoking the generic reader: no
        # recursive collections, diagnostics, selection or TEST can be nested.
        child_version = INTRADAY_EXPERIMENT_V2_VERSION if research.is_intraday_plan_v2(child_plan) else INTRADAY_EXPERIMENT_VERSION
        if (type(child) is not dict or child.get("artifact_schema_version") != child_version
                or child.get("evaluation_mode") != "INTRADAY_COMPARISON"):
            raise ValueError("a scenario must contain an ordinary Q7 development comparison")
        StrategyExperiment(canonical_json(child))
        if (canonical_json(child["plan"]) != canonical_json(child_plan)
                or child["dataset_id"] != root["dataset_id"]
                or child["algorithm_versions"] != {key: value for key, value in versions.items() if key != "execution_scenarios"}):
            raise ValueError("child plan, data or algorithm binding differs from its scenario")
        evidence = canonical_json(_shared_evidence(child))
        if common is not None and evidence != common:
            raise ValueError("all execution scenarios must share context, predictions, models and complete prices")
        common = evidence


def _evaluate(plan, *, data_file=None, recorded_scenarios=None):
    children = _children(plan)
    # The base policy is not an implicit evaluated scenario. In particular,
    # preflight the first actual child, not an unused base window.
    prepared = research._prepare_intraday_research(children[0], data_file=data_file)
    sessions, prices = execution_views(prepared.report, trading_days=tuple(prepared.context["evaluated_days"]))
    for child in children:
        research._inputs(sessions, prices, (), prepared.report["interval"], parse_execution_policy(child["execution"]))
    cache, scenarios = {}, []
    for index, child_plan in enumerate(children):
        report = research._evaluate_intraday_research(child_plan, (child_plan,),
            tuple(() for _ in child_plan["strategies"]), prepared, fit_cache=cache)
        metadata = recorded_scenarios[index]["experiment"] if recorded_scenarios is not None else None
        child = create_intraday_experiment(plan=child_plan, report=report,
            name=metadata["name"] if metadata is not None else plan["execution_scenarios"][index]["name"],
            notes=metadata["notes"] if metadata is not None else "").as_dict()
        if metadata is not None:
            # Environment is diagnostic metadata, not a numerical replay gate.
            child["environment"] = metadata["environment"]
            child["experiment_id"] = digest({key: value for key, value in child.items() if key != "experiment_id"})
        scenarios.append({"scenario_index": index, "name": plan["execution_scenarios"][index]["name"], "experiment": child})
    result = {"result_schema_version": _result_version(plan),
              "version": _version(plan), "status": "SUCCESS",
              "evaluation_scope": "DEVELOPMENT_WALK_FORWARD_ONLY", "data_id": prepared.data.data_id,
              "plan_sha256": digest(plan), "evaluation_count": len(children) * len(children[0]["strategies"]),
              "scenarios": scenarios}
    result["scenarios_id"] = digest(result)
    return result


def run_intraday_execution_scenarios(plan: dict, *, base: Path | None = None,
                                   name: str = "", notes: str = "") -> StrategyExperiment:
    """Evaluate DEV only, once per explicit policy, sharing per-fold/alpha fits."""
    normalized = normalize_intraday_execution_scenarios_plan(plan, base=base)
    if type(name) is not str or type(notes) is not str:
        raise ValueError("experiment name and notes must be strings")
    report = _evaluate(normalized)
    root = {"artifact_schema_version": _version(normalized),
            "evaluation_mode": "INTRADAY_EXECUTION_SCENARIOS", "dataset_id": report["data_id"],
            "plan": normalized, "report": report, "algorithm_versions": _versions(normalized),
            "environment": environment_versions(), "name": name, "notes": notes}
    root["experiment_id"] = digest(root)
    return StrategyExperiment(canonical_json(root))


def _collection_root(snapshot):
    if type(snapshot) is not StrategyExperiment:
        raise ValueError("an immutable StrategyExperiment is required")
    root = snapshot.as_dict()
    if root["artifact_schema_version"] not in INTRADAY_EXECUTION_SCENARIOS_VERSIONS:
        raise ValueError("an intraday execution-scenarios collection is required")
    return root


def extract_intraday_execution_scenario(snapshot: StrategyExperiment, *, expected_experiment_id: str,
                                      scenario_index: int, expected_child_experiment_id: str) -> StrategyExperiment:
    """Extract one explicitly bound ordinary Q7 child without I/O or recompute."""
    root = _collection_root(snapshot)
    if root["experiment_id"] != research._identity(expected_experiment_id, "expected collection ID"):
        raise ValueError("collection identity differs from the explicitly selected experiment")
    index = _count(scenario_index, "scenario index")
    if index >= len(root["report"]["scenarios"]):
        raise ValueError("selected scenario index is outside the saved collection")
    child = root["report"]["scenarios"][index]["experiment"]
    if child["experiment_id"] != research._identity(expected_child_experiment_id, "expected child ID"):
        raise ValueError("child identity differs from the explicitly selected scenario")
    return StrategyExperiment(canonical_json(child))


def replay_intraday_execution_scenarios(snapshot: StrategyExperiment, *, intraday_data_file: str | Path | None = None) -> dict:
    """Recompute and compare every raw child; a selected/displayed child is irrelevant."""
    root = _collection_root(snapshot)
    if root["algorithm_versions"] != _versions(root["plan"]):
        raise ValueError("recorded execution-scenarios algorithm versions differ; no source was read or model fitted")
    actual = _evaluate(root["plan"], data_file=intraday_data_file, recorded_scenarios=root["report"]["scenarios"])
    if canonical_json(actual) != canonical_json(root["report"]):
        raise ValueError("replay complete execution-scenarios report mismatch")
    return {"experiment_id": root["experiment_id"], "data_id": root["dataset_id"], "scenarios_id": actual["scenarios_id"],
            "report_matches": True, "expected_report_sha256": digest(root["report"]), "actual_report_sha256": digest(actual)}
