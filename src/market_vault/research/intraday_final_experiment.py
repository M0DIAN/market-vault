"""Offline grammar for the small selection and self-contained TEST artifacts."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path, PureWindowsPath

from . import intraday_final_test as final
from .intraday_backtest import parse_execution_policy
from .intraday_data import digest, finite_number, object_fields, positive_int
from .intraday_experiment import _array, _clock, _count, _decisions, _execution, _hash, _risk, _strings
from .intraday_research import BENCHMARK_DEFINITION, _day, _identity
from .strategy_comparison import CompositeRuleStrategy, FeatureRuleStrategy
from .strategy_config import parse_strategy_specs, strategy_plan_fields
from .strategy_experiment import StrategyExperiment, canonical_json


def _metadata(root, keys):
    _identity(root["dataset_id"], "data_id")
    _hash(root, "experiment_id")
    versions = object_fields(root["algorithm_versions"], keys, "algorithm versions")
    environment = object_fields(root["environment"], {"market_vault", "python", "pandas", "pyarrow"}, "environment")
    if any(type(value) is not str or not value for value in (*versions.values(), *environment.values())):
        raise ValueError("recorded algorithm/environment versions must be nonempty strings")
    if type(root["name"]) is not str or type(root["notes"]) is not str:
        raise ValueError("experiment name and notes must be strings")
    return versions


def _recorded_path(value):
    if type(value) is not str or not value.strip() or not (Path(value).is_absolute() or PureWindowsPath(value).is_absolute()):
        raise ValueError("a recorded source locator must be absolute")
    if any(part in (".", "..") for part in value.replace("\\", "/").split("/")):
        raise ValueError("a recorded source locator must not contain dot segments")


def _split(value):
    parts = object_fields(value, {"TRAIN", "VALIDATION", "TEST"}, "frozen day split")
    days = []
    for name in ("TRAIN", "VALIDATION", "TEST"):
        group = _strings(parts[name], name)
        if not group:
            raise ValueError("TRAIN, VALIDATION and TEST must all contain trading days")
        for day in group:
            _day(day, "trading day")
        days.extend(group)
    if days != sorted(set(days)):
        raise ValueError("frozen split dates must increase without overlap")


def _feature_context(context):
    if type(context["symbol"]) is not str or not context["symbol"].startswith("US.") or context["interval"] not in ("1m", "5m", "15m", "30m"):
        raise ValueError("unsupported intraday context scope")
    features = _strings(context["feature_fields"], "Feature projection")
    if not features or any(value != value.strip() for value in features):
        raise ValueError("an explicit ordered common Feature projection is required")
    if context["target_horizon_bars"] is not None:
        positive_int(context["target_horizon_bars"], "target horizon")
    _split(context["split"])
    return features


def validate_intraday_selection_root(root):
    """No source reads, model training, or TEST execution during Open."""
    if root["evaluation_mode"] != "INTRADAY_SELECTION":
        raise ValueError("selection artifact mode differs")
    recorded = root["algorithm_versions"]
    if type(recorded) is not dict or not set(final.SOURCE_VERSIONS).issubset(recorded):
        raise ValueError("selection must retain the source algorithm versions")
    keys = {*final.SOURCE_VERSIONS, "selection", *(set(recorded) & set(final.OPTIONAL_SOURCE_VERSIONS))}
    versions = _metadata(root, keys)
    plan = object_fields(root["plan"], {"plan_schema_version", "source_experiment", "selection"}, "selection plan")
    if plan["plan_schema_version"] != final.INTRADAY_SELECTION_PLAN_VERSION:
        raise ValueError("unsupported selection plan version")
    source = object_fields(plan["source_experiment"], {"path", "experiment_id", "research_id"}, "source experiment")
    _recorded_path(source["path"])
    for key in ("experiment_id", "research_id"):
        _identity(source[key], key)
    selected = object_fields(plan["selection"], {"cost_index", "candidate_index", "candidate_id"}, "explicit selection")
    _count(selected["cost_index"], "cost index")
    _count(selected["candidate_index"], "candidate index")
    _identity(selected["candidate_id"], "candidate_id")
    report = object_fields(root["report"], {
        "result_schema_version", "version", "status", "evaluation_scope", "data_id", "plan_sha256",
        "context", "candidate", "benchmark_definition", "selection_id",
    }, "selection report")
    _hash(report, "selection_id")
    if (report["result_schema_version"] != final.INTRADAY_SELECTION_RESULT_VERSION or report["version"] != versions["selection"]
            or report["status"] != "FROZEN" or report["evaluation_scope"] != "DEVELOPMENT_MANUAL_SINGLE_SELECTION"
            or report["data_id"] != root["dataset_id"] or report["plan_sha256"] != digest(plan)
            or report["benchmark_definition"] != BENCHMARK_DEFINITION):
        raise ValueError("selection report plan, scope or version binding differs")
    context = object_fields(report["context"], {
        "source_context_id", "intraday_data_path", "symbol", "interval", "feature_fields", "target_horizon_bars", "split",
    }, "frozen context")
    _identity(context["source_context_id"], "source context")
    _recorded_path(context["intraday_data_path"])
    features = _feature_context(context)
    candidate = object_fields(report["candidate"], {"strategy", "axis_values", "execution_policy"}, "frozen candidate")
    strategy = parse_strategy_specs([candidate["strategy"]])[0]
    if canonical_json(candidate["strategy"]) != canonical_json(strategy_plan_fields(strategy)):
        raise ValueError("frozen strategy must be normalized")
    rules = ((strategy.rule,) if type(strategy) is FeatureRuleStrategy else
             strategy.conditions if type(strategy) is CompositeRuleStrategy else ())
    if any(rule.signal_field not in features for rule in rules):
        raise ValueError("frozen rules must use the common Feature projection")
    required = {"RIDGE": "ridge", "COMPOSITE_RULE": "composite"}.get(candidate["strategy"]["kind"])
    if required is not None and required not in versions:
        raise ValueError("selected strategy algorithm version is missing")
    axes = _array(candidate["axis_values"], "selected axis values")
    if len(axes) > 2:
        raise ValueError("at most two selected axis values are supported")
    for value in axes:
        finite_number(value, "selected axis value")
    if canonical_json(candidate["execution_policy"]) != canonical_json(asdict(parse_execution_policy(candidate["execution_policy"]))):
        raise ValueError("frozen execution policy must be normalized")


def _model(value, *, context, strategy, version):
    model = object_fields(value, {"version", "alpha", "feature_fields", "training_keys", "training_boundary",
                                  "intercept", "coefficients", "means", "scales", "model_id"}, "final Ridge model")
    _hash(model, "model_id")
    if (model["version"] != version or finite_number(model["alpha"], "model alpha") != strategy["alpha"]
            or model["feature_fields"] != context["feature_fields"] or model["training_keys"] != context["training_keys"]
            or model["training_boundary"] != context["training_boundary"] or not model["training_keys"]):
        raise ValueError("final model must bind its complete TRAIN+VALIDATION context")
    finite_number(model["intercept"], "model intercept")
    for key in ("coefficients", "means", "scales"):
        if len(_array(model[key], key)) != len(context["feature_fields"]):
            raise ValueError("final model vectors differ from the Feature order")
        for number in model[key]:
            if finite_number(number, key) < 0 and key == "scales":
                raise ValueError("final Feature scales cannot be negative")


def _errors(value, count):
    errors = object_fields(value, {"prediction_count", "complete_target_count", "mae", "rmse", "r2", "unavailable_reason"}, "TEST target errors")
    complete = _count(errors["complete_target_count"], "complete TEST targets")
    if _count(errors["prediction_count"], "prediction count") != count or complete > count:
        raise ValueError("TEST target error counts differ from all READY predictions")
    for key in ("mae", "rmse", "r2"):
        if errors[key] is not None and finite_number(errors[key], key) < 0 and key != "r2":
            raise ValueError("TEST absolute and squared errors cannot be negative")
    if ((not complete and (errors["unavailable_reason"] != "NO_COMPLETE_TARGETS" or any(errors[k] is not None for k in ("mae", "rmse", "r2"))))
            or (complete and (errors["unavailable_reason"] is not None or errors["mae"] is None or errors["rmse"] is None))):
        raise ValueError("TEST target error availability differs from complete target count")


def validate_intraday_test_root(root):
    if root["evaluation_mode"] != "INTRADAY_TEST":
        raise ValueError("TEST artifact mode differs")
    plan = object_fields(root["plan"], {"plan_schema_version", "selection"}, "TEST plan")
    if plan["plan_schema_version"] != final.INTRADAY_TEST_PLAN_VERSION:
        raise ValueError("unsupported TEST plan version")
    embedded = plan["selection"]
    # Reject nested TEST/other roots before construction, so this cannot recurse.
    if type(embedded) is not dict or embedded.get("artifact_schema_version") != final.INTRADAY_SELECTION_VERSION:
        raise ValueError("TEST must embed exactly one selection artifact")
    selection = StrategyExperiment(canonical_json(embedded)).as_dict()
    expected_versions = final.final_algorithm_versions(selection)
    versions = _metadata(root, expected_versions)
    if any(versions[k] != v for k, v in expected_versions.items() if k not in ("final_test", "final_context")):
        raise ValueError("final TEST algorithms differ from the frozen selection")
    frozen = selection["report"]
    report = object_fields(root["report"], {
        "result_schema_version", "version", "status", "evaluation_scope", "selection_experiment_id", "selection_id",
        "data_id", "context", "strategy", "execution_policy", "model", "predictions", "prediction_metrics",
        "execution", "risk", "benchmark", "final_test_id",
    }, "final TEST report")
    _hash(report, "final_test_id")
    if (report["result_schema_version"] != final.INTRADAY_FINAL_RESULT_VERSION or report["version"] != versions["final_test"]
            or report["status"] != "SUCCESS" or report["evaluation_scope"] != "FROZEN_SINGLE_CANDIDATE_TEST"
            or report["selection_experiment_id"] != selection["experiment_id"] or report["selection_id"] != frozen["selection_id"]
            or root["dataset_id"] != selection["dataset_id"] or report["data_id"] != root["dataset_id"]
            or canonical_json(report["strategy"]) != canonical_json(frozen["candidate"]["strategy"])
            or canonical_json(report["execution_policy"]) != canonical_json(frozen["candidate"]["execution_policy"])):
        raise ValueError("final TEST report differs from its frozen candidate")
    context = object_fields(report["context"], {
        "version", "data_id", "selection_id", "symbol", "interval", "feature_fields", "target_horizon_bars",
        "split", "training_boundary", "training_keys", "purged_keys", "test_keys", "context_id",
    }, "final training context")
    _hash(context, "context_id")
    _feature_context(context)
    if (context["version"] != versions["final_context"] or context["data_id"] != root["dataset_id"]
            or context["selection_id"] != frozen["selection_id"]
            or any(context[key] != frozen["context"][key] for key in ("symbol", "interval", "feature_fields", "target_horizon_bars", "split"))):
        raise ValueError("final training context differs from the frozen context")
    _clock(context["training_boundary"], "final training boundary")
    key_sets = []
    for key in ("training_keys", "purged_keys", "test_keys"):
        values = _strings(context[key], key)
        for identity in values:
            _identity(identity, key)
        key_sets.append(set(values))
    if not context["test_keys"] or any(key_sets[i] & key_sets[j] for i in range(3) for j in range(i + 1, 3)):
        raise ValueError("training, purged and TEST identities must be disjoint; TEST cannot be empty")
    days, policy = context["split"]["TEST"], report["execution_policy"]
    predictions = _array(report["predictions"], "TEST predictions")
    _decisions(predictions, days)
    if [row["observation_key"] for row in predictions] != context["test_keys"]:
        raise ValueError("all READY TEST predictions must be retained")
    for row in predictions:
        finite_number(row["score"], "TEST prediction score")
    execution = report["execution"]
    _execution(execution, policy=policy, days=days, interval=context["interval"], versions=versions)
    if execution["decisions"] != predictions or execution["daily"][0]["open_time"] != context["training_boundary"]:
        raise ValueError("TEST execution decisions or initial boundary differ")
    _risk(report["risk"], execution, versions)
    if report["strategy"]["kind"] == "RIDGE":
        _model(report["model"], context=context, strategy=report["strategy"], version=versions["ridge"])
        _errors(report["prediction_metrics"], len(predictions))
        if any(row["target"] != ("LONG" if row["score"] > report["strategy"]["threshold"] else "FLAT") for row in predictions):
            raise ValueError("TEST decisions must use the frozen Ridge threshold")
    elif report["model"] is not None or report["prediction_metrics"] is not None:
        raise ValueError("rule TEST must not invent a fitted model or target errors")
    benchmark = object_fields(report["benchmark"], {"version", "definition", "execution", "risk"}, "TEST benchmark")
    if benchmark["version"] != versions["benchmark"] or benchmark["definition"] != frozen["benchmark_definition"]:
        raise ValueError("TEST benchmark definition differs from the frozen selection")
    # Derive the limit from TEST's complete recorded grid, never the DEV grid.
    counts = {day: sum(row["phase"] == "OPEN" and row["trading_day"] == day for row in execution["ledger"]) for day in days}
    benchmark_policy = {**policy, "max_hold_bars": max(counts.values())}
    _execution(benchmark["execution"], policy=benchmark_policy, days=days, interval=context["interval"], versions=versions)
    if (benchmark["execution"]["price_evidence_id"] != execution["price_evidence_id"]
            or any(row["trade_count"] > 1 for row in benchmark["execution"]["daily"])):
        raise ValueError("TEST benchmark must share prices and trade at most once each day")
    _risk(benchmark["risk"], benchmark["execution"], versions)
