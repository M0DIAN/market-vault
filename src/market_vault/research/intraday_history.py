"""Explicit, bounded saved-research history; never a global TEST certificate.

Creation reads an ordinary DEV, frozen selection or TEST artifact through the
existing offline grammar. Assessment reads only the named artifact/event files:
no Q5 reconstruction, model fit, TEST replay, registry or directory discovery.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

from ..dataset.cli import DatasetCLIError
from ..quality.market_data_comparison import parse_utc, read_json_file, write_market_data_json
from ..lifecycle import LifecycleLockError
from ..storage.atomic_file import AtomicFilePublicationError
from .intraday_backtest import parse_execution_policy
from .intraday_data import digest, object_fields
from .intraday_experiment import INTRADAY_EXPERIMENT_VERSIONS, _hash
from .intraday_final_experiment import _feature_context
from .intraday_final_test import INTRADAY_SELECTION_VERSIONS, INTRADAY_TEST_SELECTION_VERSIONS
from .intraday_research import _day, _identity
from .strategy_config import parse_strategy_specs, strategy_plan_fields
from .strategy_experiment import load_strategy_experiment


DECLARATION_VERSION = "market-vault-intraday-history-declaration-v1"
EVENT_VERSION = "market-vault-intraday-history-event-v1"
ASSESSMENT_VERSION = "market-vault-intraday-test-history-v1"
_CONTEXT_FIELDS = {"symbol", "interval", "feature_fields", "target_horizon_bars", "split"}
_SOURCE_FIELDS = {"artifact_schema_version", "experiment_id", "data_id", "plan_id", "context",
                  "recipes", "recipe_set_id", "algorithm_versions", "environment", "basis"}
_BASIS = {"session": "RTH", "adjustment": "NONE", "matching": "SAME_US_SYMBOL_AND_NEW_YORK_TRADING_DAY"}
_SUPPORTED = (*INTRADAY_EXPERIMENT_VERSIONS, *INTRADAY_SELECTION_VERSIONS, *INTRADAY_TEST_SELECTION_VERSIONS)


def _days(value, label):
    if type(value) is not list:
        raise ValueError(f"{label} must be a sorted unique day array")
    for day in value:
        _day(day, label)
    if value != sorted(set(value)):
        raise ValueError(f"{label} must be a sorted unique day array")
    return value


def _declaration(value):
    object_fields(value, {"schema_version", "expected_experiment_id", "recorded_at", "purpose",
                          "observed_days", "code_commit", "notes"}, "history declaration")
    if value["schema_version"] != DECLARATION_VERSION:
        raise ValueError("unsupported history declaration version")
    _identity(value["expected_experiment_id"], "expected experiment ID")
    parse_utc(value["recorded_at"])
    purpose = value["purpose"]
    if purpose not in ("PLAN_ONLY", "INSPECT", "TUNE", "UNKNOWN"):
        raise ValueError("purpose must be PLAN_ONLY, INSPECT, TUNE or UNKNOWN")
    days = _days(value["observed_days"], "declared observed days")
    if bool(days) != (purpose in ("INSPECT", "TUNE")):
        raise ValueError("INSPECT/TUNE require observed days; PLAN_ONLY/UNKNOWN must leave them empty")
    commit = value["code_commit"]
    if commit is not None and (type(commit) is not str or re.fullmatch(r"[0-9a-f]{40}", commit) is None):
        raise ValueError("code_commit must be a declared full Git SHA or null (unknown)")
    if type(value["notes"]) is not str:
        raise ValueError("history notes must be a string")
    return value


def _source_summary(snapshot):
    root = snapshot.as_dict()
    schema = root["artifact_schema_version"]
    if schema not in _SUPPORTED:
        raise ValueError("history requires an ordinary intraday DEV, frozen selection or TEST artifact")
    context = root["report"]["context"]
    if schema in INTRADAY_EXPERIMENT_VERSIONS:
        recipes = [{"strategy": candidate["strategy"], "execution_policy": group["execution_policy"]}
                   for group in root["report"]["groups"] for candidate in group["results"]]
    elif schema in INTRADAY_SELECTION_VERSIONS:
        candidate = root["report"]["candidate"]
        recipes = [{key: candidate[key] for key in ("strategy", "execution_policy")}]
    else:
        recipes = [{key: root["report"][key] for key in ("strategy", "execution_policy")}]
    return {"artifact_schema_version": schema, "experiment_id": root["experiment_id"],
            "data_id": root["dataset_id"], "plan_id": digest(root["plan"]),
            "context": {key: context[key] for key in sorted(_CONTEXT_FIELDS)},
            "recipes": recipes, "recipe_set_id": digest(recipes),
            "algorithm_versions": root["algorithm_versions"], "environment": root["environment"],
            "basis": dict(_BASIS)}


def _validate_source(source):
    object_fields(source, _SOURCE_FIELDS, "history source summary")
    if source["artifact_schema_version"] not in _SUPPORTED or source["basis"] != _BASIS:
        raise ValueError("unsupported history source or economic matching basis")
    for key in ("experiment_id", "data_id", "plan_id", "recipe_set_id"):
        _identity(source[key], key)
    _feature_context(object_fields(source["context"], _CONTEXT_FIELDS, "history context"))
    recipes = source["recipes"]
    if type(recipes) is not list or not recipes or source["recipe_set_id"] != digest(recipes):
        raise ValueError("history recipe set identity differs")
    for recipe in recipes:
        object_fields(recipe, {"strategy", "execution_policy"}, "history recipe")
        parsed = parse_strategy_specs([recipe["strategy"]], allow_quadratic=True)[0]
        if recipe["strategy"] != strategy_plan_fields(parsed):
            raise ValueError("history strategy must be normalized")
        parse_execution_policy(recipe["execution_policy"])
    for key in ("algorithm_versions", "environment"):
        values = source[key]
        if type(values) is not dict or not values or any(type(k) is not str or not k or type(v) is not str or not v
                                                        for k, v in values.items()):
            raise ValueError("history version metadata must contain nonempty strings")
    return source


def _recorded_use_days(source):
    split = source["context"]["split"]
    # Conservative research-use exposure, not a claim about a human's screen:
    # every recorded DEV day; additionally every TEST day in a saved TEST result.
    return split["TRAIN"] + split["VALIDATION"] + (
        split["TEST"] if source["artifact_schema_version"] in INTRADAY_TEST_SELECTION_VERSIONS else [])


def create_intraday_history_event(experiment_path: str | Path, declaration: dict) -> dict:
    declared = _declaration(declaration)
    source = _source_summary(load_strategy_experiment(experiment_path))
    event = {"schema_version": EVENT_VERSION, "source": source, "declaration": declared}
    event["event_id"] = digest(event)
    return validate_intraday_history_event(event)


def validate_intraday_history_event(event: dict) -> dict:
    object_fields(event, {"schema_version", "source", "declaration", "event_id"}, "history event")
    if event["schema_version"] != EVENT_VERSION:
        raise ValueError("unsupported history event version")
    _hash(event, "event_id")
    source, declared = _validate_source(event["source"]), _declaration(event["declaration"])
    if declared["expected_experiment_id"] != source["experiment_id"]:
        raise ValueError("history declaration source identity differs")
    days = {day for group in source["context"]["split"].values() for day in group}
    if not set(declared["observed_days"]).issubset(days):
        raise ValueError("declared observed days must be in the named source scope")
    return event


def analyze_intraday_test_history(experiment_path: str | Path, event_paths: list[str | Path]) -> dict:
    source = _source_summary(load_strategy_experiment(experiment_path))
    if type(event_paths) not in (list, tuple):
        raise ValueError("history requires an explicit file list, not a directory or latest pointer")
    target_days = set(source["context"]["split"]["TEST"])
    own_overlap = sorted(target_days.intersection(_recorded_use_days(source)))
    known, unknown, seen, matches = set(own_overlap), set(), set(), []
    for path in event_paths:
        event = validate_intraday_history_event(read_json_file(path))
        if event["event_id"] in seen:
            continue
        seen.add(event["event_id"])
        previous, declared = event["source"], event["declaration"]
        same_symbol = previous["context"]["symbol"] == source["context"]["symbol"]
        recorded = sorted(target_days.intersection(_recorded_use_days(previous))) if same_symbol else []
        observed = sorted(target_days.intersection(declared["observed_days"])) if same_symbol else []
        uncertain = sorted(target_days.intersection(previous["context"]["split"]["TEST"])) if (
            same_symbol and declared["purpose"] == "UNKNOWN") else []
        known.update(recorded + observed)
        unknown.update(uncertain)
        matches.append({"event_id": event["event_id"], "source_experiment_id": previous["experiment_id"],
                        "same_symbol": same_symbol, "recorded_use_overlap_days": recorded,
                        "declared_exposure_overlap_days": observed, "unknown_overlap_days": uncertain})
    status = ("KNOWN_EXPOSURE" if known else "UNKNOWN_RECORDED_EXPOSURE" if unknown
              else "NO_RECORDED_EXPOSURE_IN_SUPPLIED_HISTORY")
    result = {"version": ASSESSMENT_VERSION, "status": status, "proposed_source": source,
              "input_count": len(event_paths), "unique_event_count": len(seen),
              "duplicate_event_count": len(event_paths) - len(seen), "matches": matches,
              "own_recorded_test_days": own_overlap, "known_exposure_days": sorted(known),
              "unknown_exposure_days": sorted(unknown), "external_history_coverage": "UNKNOWN",
              "independence_certified": False,
              "limitations": [
                  "Assessment covers only these explicit saved records, not global TEST use or lifetime trial counts.",
                  "Recorded DEV use conservatively includes TRAIN and VALIDATION; recorded TEST includes its TEST days even with PLAN_ONLY declarations.",
                  "Matching uses the same literal US symbol and New York trading day, not filenames, data hashes, Feature sets, recipes or bar interval.",
                  "Cross-symbol or undisclosed indirect information reuse is outside this matching scope.",
                  "Artifact metadata and caller statements are not proof of execution, authenticated timestamps or preregistration.",
                  "No recorded overlap is not proof that TEST was unseen. A user can omit or rewrite user-controlled history files.",
                  "No Q5 data, model fit, TEST replay, automatic launch gate or external service is used.",
              ]}
    return {**result, "history_assessment_id": digest(result)}


def main(argv=None) -> int:
    """Explicit module CLI; existing market-vault commands are unchanged."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    record = commands.add_parser("record", help="Create one new history event from an explicit saved artifact")
    record.add_argument("--declaration", required=True)
    assess = commands.add_parser("assess", help="Assess proposed TEST dates against explicitly named history events")
    assess.add_argument("--event", action="append", default=[])
    for command in (record, assess):
        command.add_argument("--experiment", required=True)
        command.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    version = EVENT_VERSION if args.command == "record" else ASSESSMENT_VERSION
    try:
        result = (create_intraday_history_event(args.experiment, read_json_file(args.declaration))
                  if args.command == "record" else analyze_intraday_test_history(args.experiment, args.event))
        output = write_market_data_json(args.output, result)
        status = "RECORDED" if args.command == "record" else result["status"]
        print(json.dumps({"version": version, "status": status, "output": str(output), "report": result}, allow_nan=False))
        return 0 if status in ("RECORDED", "NO_RECORDED_EXPOSURE_IN_SUPPLIED_HISTORY") else 2
    except (DatasetCLIError, OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError,
            LifecycleLockError, AtomicFilePublicationError) as exc:
        payload = {"version": version, "status": "FAILED", "error": str(exc)}
        if isinstance(exc, AtomicFilePublicationError):
            payload["published"] = exc.published
        print(json.dumps(payload), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
