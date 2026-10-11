"""Recorded joint economic evidence validation; no Q5 reads, fits or Q6 runs."""

from __future__ import annotations

from .intraday_data import digest, object_fields
from .intraday_experiment import INTRADAY_EXPERIMENT_VERSIONS, _array, _clock, _count, _hash, _risk
from .intraday_inner_experiment import _metrics, _model, _predictions
from .intraday_inner_selection import _recipe
from .intraday_joint_selection import (
    FAMILY, MODEL_FAMILY, METHOD, RETURN_BASIS, THRESHOLDS,
    INTRADAY_JOINT_SELECTION_RESULT_VERSION, INTRADAY_JOINT_SELECTION_VERSION,
    _equal, _selected, normalize_joint_selection_plan,
)
from .intraday_research import _identity, fold_cash_contributions
from .intraday_threshold_experiment import _account, _PRICE_PATH_FIELDS, validate_threshold_window
from .intraday_threshold_selection import threshold_predictions
from .strategy_experiment import StrategyExperiment, canonical_json


_WINDOW_FIELDS = {"history_days", "history_boundary", "history_training_keys", "history_purged_keys", "history_targets",
    "training_days", "validation_days", "training_boundary", "training_keys", "purged_keys", "validation_keys",
    "sessions", "prices", "execution_input", "unavailable_reason", "models", "family_results",
    "selected_index", "selected_recipe"}


def validate_joint_window(window, *, days, boundary, history_keys, history_purged,
                          features, strategy, versions, policy, interval, fitted):
    """Validate complete fixed-family evidence, also reusable by future Freeze."""
    object_fields(window, _WINDOW_FIELDS, "joint inner window")
    # Reuse only the unchanged Q31 history/session/input grammar. Its empty
    # fit projection cannot admit any joint model or family member; those are
    # validated independently below, without broadening the old four-family.
    admission = {key: value for key, value in window.items() if key != "models"}
    admission.update(model=None, predictions=[], family_results=[], selected_index=None, selected_recipe=None)
    validate_threshold_window(admission, days=days, boundary=boundary, history_keys=history_keys,
        history_purged=history_purged, features=features, strategy=strategy, versions=versions,
        policy=policy, interval=interval, fitted=False)
    models = _array(window["models"], "six shared inner fits")
    family = _array(window["family_results"], "24 joint accounts")
    if not fitted:
        if models or family or window["selected_index"] is not None or window["selected_recipe"] is not None:
            raise ValueError("an unavailable joint study cannot contain partial fits or accounts")
        return
    if window["unavailable_reason"] or len(models) != len(MODEL_FAMILY) or len(family) != len(FAMILY):
        raise ValueError("every available joint window requires six fits and all 24 accounts")
    for index, (member, record) in enumerate(zip(MODEL_FAMILY, models, strict=True)):
        object_fields(record, {"model_index", "strategy", "model", "predictions"}, "shared inner model")
        if _count(record["model_index"], "model index") != index:
            raise ValueError("joint model order differs")
        recipe = _recipe(member, strategy)
        _equal(record["strategy"], recipe, "shared model recipe")
        _model(record["model"], recipe, features, window["training_keys"], window["training_boundary"], versions)
        _predictions(record["predictions"], window["validation_days"], window["validation_keys"], recipe["threshold"])
    expected_prices = [{"trading_day": row["trading_day"], "slot": row["slot"],
        "timestamp": row["event_time" if phase == "OPEN" else "available_at"], "phase": phase,
        "row_version_id": row["row_version_id"], "mark_price": row["open" if phase == "OPEN" else "close"]}
        for row in window["prices"] for phase in ("OPEN", "CLOSE")]
    price_id = None
    for index, (member, record) in enumerate(zip(FAMILY, family, strict=True)):
        object_fields(record, {"candidate_index", "model_index", "threshold_index", "strategy", "execution"}, "joint family member")
        model_index, threshold_index = divmod(index, len(THRESHOLDS))
        if (_count(record["candidate_index"], "candidate index") != index
                or _count(record["model_index"], "model index") != model_index
                or _count(record["threshold_index"], "threshold index") != threshold_index):
            raise ValueError("joint family must retain model-outer threshold-inner order")
        recipe = {**member, "name": strategy["name"]}
        _equal(record["strategy"], recipe, "fixed joint recipe")
        execution = record["execution"]
        _account(execution, policy=policy, days=window["validation_days"], interval=interval, versions=versions)
        expected = threshold_predictions(models[model_index]["predictions"], recipe["threshold"])
        _equal(execution["decisions"], expected, "joint member decisions from shared scores")
        _equal([{key: row[key] for key in _PRICE_PATH_FIELDS} for row in execution["ledger"]],
            expected_prices, "inner complete price path")
        if index and execution["price_evidence_id"] != price_id:
            raise ValueError("all 24 joint accounts must share one price identity")
        price_id = execution["price_evidence_id"]
    chosen = max(range(len(FAMILY)), key=lambda index: family[index]["execution"]["metrics"]["total_return"])
    if _count(window["selected_index"], "joint selected index") != chosen:
        raise ValueError("joint winner must maximize net account return with first-declared ties")
    _equal(window["selected_recipe"], family[chosen]["strategy"], "joint chosen recipe")


def validate_intraday_joint_selection_root(root):
    if root["evaluation_mode"] != "INTRADAY_JOINT_SELECTION":
        raise ValueError("joint-selection artifact mode differs")
    _hash(root, "experiment_id")
    _identity(root["dataset_id"], "data ID")
    plan = normalize_joint_selection_plan(root["plan"])
    report = object_fields(root["report"], {"result_schema_version", "version", "status", "evaluation_scope", "data_id",
        "plan_sha256", "method", "source_experiment", "source_reconstruction", "fixed_reference", "benchmark",
        "outer_folds", "final_dev", "selected_account", "unavailable_reasons", "return_basis", "joint_selection_id"},
        "joint-selection report")
    _hash(report, "joint_selection_id")
    source = report["source_experiment"]
    if type(source) is not dict or source.get("artifact_schema_version") not in INTRADAY_EXPERIMENT_VERSIONS:
        raise ValueError("joint study must embed an ordinary DEV source, never another selection")
    StrategyExperiment(canonical_json(source))
    group, reference = _selected(source, plan)
    versions = object_fields(root["algorithm_versions"], {*source["algorithm_versions"], "quadratic", "joint_selection"},
        "joint versions")
    environment = object_fields(root["environment"], {"market_vault", "python", "pandas", "pyarrow"}, "environment")
    if any(type(value) is not str or not value for value in (*versions.values(), *environment.values())):
        raise ValueError("recorded versions must be nonempty strings")
    for key, value in source["algorithm_versions"].items():
        _equal(versions[key], value, "embedded source algorithm")
    if type(root["name"]) is not str or type(root["notes"]) is not str:
        raise ValueError("experiment name and notes must be strings")
    if (root["artifact_schema_version"] != INTRADAY_JOINT_SELECTION_VERSION
            or report["result_schema_version"] != INTRADAY_JOINT_SELECTION_RESULT_VERSION
            or report["version"] != versions["joint_selection"]
            or report["evaluation_scope"] != "DEVELOPMENT_INNER_JOINT_ECONOMIC_SELECTION_ONLY"
            or report["source_reconstruction"] != "COMPLETE_REPORT_RECONSTRUCTED"
            or root["dataset_id"] != source["dataset_id"] or report["data_id"] != root["dataset_id"]
            or report["plan_sha256"] != digest(plan)):
        raise ValueError("joint-selection source, version, data or plan binding differs")
    _equal(report["method"], METHOD, "fixed joint method")
    _equal(report["return_basis"], RETURN_BASIS, "return basis")
    _equal(report["fixed_reference"], plan["selection"], "fixed source reference")
    _equal(report["benchmark"], group["benchmark"], "original benchmark")
    context = source["report"]["context"]
    outer = _array(report["outer_folds"], "outer joint folds")
    if len(outer) != len(context["folds"]):
        raise ValueError("joint selection must retain every original outer fold")
    if report["status"] not in ("AVAILABLE", "UNAVAILABLE"):
        raise ValueError("unsupported joint-selection availability")
    fitted = report["status"] == "AVAILABLE"
    predictions, reasons = [], []
    shared = {"features": context["feature_fields"], "strategy": reference["strategy"], "versions": versions,
        "policy": group["execution_policy"], "interval": context["interval"], "fitted": fitted}
    for index, (record, fold) in enumerate(zip(outer, context["folds"], strict=True)):
        object_fields(record, {"fold_id", "inner", "refit"}, "outer joint refit")
        _equal(record["fold_id"], fold["fold_id"], "original outer fold")
        validate_joint_window(record["inner"], days=fold["training_days"], boundary=fold["training_boundary"],
            history_keys=fold["training_keys"], history_purged=fold["purged_keys"], **shared)
        if record["inner"]["unavailable_reason"]:
            reasons.append({"scope": "OUTER_FOLD", "fold_index": index, "reason": record["inner"]["unavailable_reason"]})
        if not fitted:
            if record["refit"] is not None:
                raise ValueError("an unavailable joint study cannot partially refit outer models")
            continue
        refit = object_fields(record["refit"], {"strategy", "model", "predictions", "prediction_metrics"}, "outer winner refit")
        _equal(refit["strategy"], record["inner"]["selected_recipe"], "outer selected joint recipe")
        _model(refit["model"], refit["strategy"], context["feature_fields"], fold["training_keys"], fold["training_boundary"], versions)
        _predictions(refit["predictions"], fold["validation_days"], fold["validation_keys"], refit["strategy"]["threshold"])
        _metrics(refit["prediction_metrics"], len(refit["predictions"]))
        predictions.extend(refit["predictions"])
    final = report["final_dev"]
    validate_joint_window(final, days=context["split"]["TRAIN"] + context["split"]["VALIDATION"], boundary=None,
        history_keys=None, history_purged=None, **shared)
    if (_clock(final["history_boundary"], "final DEV boundary").date().isoformat() != context["split"]["TEST"][0]
            or any(not set(fold["training_keys"]).issubset(final["history_training_keys"]) for fold in context["folds"])):
        raise ValueError("final DEV history must retain prior admitted training rows before TEST")
    if final["unavailable_reason"]:
        reasons.append({"scope": "FINAL_DEV", "fold_index": None, "reason": final["unavailable_reason"]})
    _equal(report["unavailable_reasons"], reasons, "whole-study unavailable reasons")
    if fitted == bool(reasons):
        raise ValueError("any unavailable window makes the entire joint study unavailable")
    account = report["selected_account"]
    if not fitted:
        if account is not None:
            raise ValueError("an unavailable joint study cannot invent a cash account")
        return
    object_fields(account, {"predictions", "prediction_metrics", "execution", "risk", "fold_contributions"}, "selected joint account")
    _equal(account["predictions"], predictions, "complete selected outer predictions")
    _metrics(account["prediction_metrics"], len(predictions),
        complete_count=reference["prediction_metrics"]["complete_target_count"])
    execution = account["execution"]
    _account(execution, policy=group["execution_policy"], days=context["evaluated_days"], interval=context["interval"], versions=versions)
    _equal(execution["decisions"], predictions, "selected outer decisions")
    for key in ("windows", "price_evidence_id"):
        _equal(execution[key], reference["execution"][key], "source " + key)
    _equal([[row[key] for key in _PRICE_PATH_FIELDS] for row in execution["ledger"]],
        [[row[key] for key in _PRICE_PATH_FIELDS] for row in reference["execution"]["ledger"]], "source complete outer price path")
    _risk(account["risk"], execution, versions)
    _equal(account["fold_contributions"], fold_cash_contributions(context, execution), "continuous outer fold contributions")
