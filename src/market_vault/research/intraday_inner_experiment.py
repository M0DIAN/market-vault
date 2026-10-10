"""Offline grammar for the fixed inner-selection experiment; no fitting or I/O."""

from __future__ import annotations

from .intraday_data import digest, finite_number, object_fields
from .intraday_experiment import (INTRADAY_EXPERIMENT_VERSIONS, _array, _clock, _count, _decisions,
                                 _execution, _hash, _quadratic_model, _ridge_model, _risk, _strings)
from .intraday_inner_selection import (FAMILY, METHOD, INTRADAY_INNER_SELECTION_RESULT_VERSION,
    INTRADAY_INNER_SELECTION_VERSION, _equal, _recipe, _selected, normalize_inner_selection_plan, pooled_mse)
from .intraday_research import _identity, fold_cash_contributions
from .strategy_experiment import StrategyExperiment, canonical_json


_WINDOW_FIELDS = {"history_days", "history_boundary", "history_training_keys", "history_purged_keys",
    "training_days", "validation_days", "training_boundary", "training_keys", "purged_keys", "validation_keys",
    "scored_targets", "unavailable_reason", "family_results", "selected_index", "selected_recipe"}


def _keys(values, label):
    for value in _strings(values, label):
        _identity(value, label)
    return values


def _model(model, recipe, features, keys, boundary, versions):
    if recipe["kind"] == "QUADRATIC_RIDGE":
        _quadratic_model(model, features=features, training_keys=keys, boundary=boundary,
                         alpha=recipe["alpha"], versions=versions)
    else:
        _ridge_model(model, features=features, training_keys=keys, boundary=boundary,
                     alpha=recipe["alpha"], version=versions["ridge"])
        finite_number(model["alpha"], "model alpha")
        if any(value < 0 for value in model["scales"]):
            raise ValueError("inner Ridge scales cannot be negative")


def _predictions(predictions, days, keys, threshold):
    _decisions(predictions, days)
    _equal([row["observation_key"] for row in predictions], keys, "prediction keys")
    for row in predictions:
        score = finite_number(row["score"], "learned score")
        if row["target"] != ("LONG" if score > threshold else "FLAT"):
            raise ValueError("inner selection decision differs from the fixed strict threshold")


def _window(window, *, days, boundary, history_keys, history_purged, features, strategy, versions, fitted):
    object_fields(window, _WINDOW_FIELDS, "inner holdout evidence")
    _equal(window["history_days"], days, "history days")
    if boundary is not None:
        _equal(window["history_boundary"], boundary, "history boundary")
    history_clock = _clock(window["history_boundary"], "history boundary")
    if history_keys is not None:
        _equal(window["history_training_keys"], history_keys, "history keys")
        _equal(window["history_purged_keys"], history_purged, "history purged keys")
    for key in ("history_training_keys", "history_purged_keys", "training_keys", "purged_keys", "validation_keys"):
        _keys(window[key], key)
    history = set(window["history_training_keys"])
    training, purged, validation = (set(window[key]) for key in ("training_keys", "purged_keys", "validation_keys"))
    if (history.intersection(window["history_purged_keys"]) or training & purged or training & validation
            or purged & validation or not (training | purged).issubset(history)):
        raise ValueError("inner training, purged and validation identities are inconsistent")
    _equal(window["training_days"], days[:-5], "inner TRAIN days")
    _equal(window["validation_days"], days[-5:], "inner holdout days")
    inner_clock = _clock(window["training_boundary"], "inner training boundary")
    if inner_clock.date().isoformat() != days[-5:][0] or inner_clock >= history_clock:
        raise ValueError("inner boundary must precede the historical availability cutoff")
    targets = _array(window["scored_targets"], "inner scored targets")
    for row in targets:
        object_fields(row, {"observation_key", "trading_day", "actual_label_end_time", "value"}, "inner scored target")
        if (row["observation_key"] not in history & validation or row["trading_day"] not in window["validation_days"]
                or _clock(row["actual_label_end_time"], "inner label end") >= history_clock):
            raise ValueError("inner score target was not available before its historical cutoff")
        finite_number(row["value"], "inner target")
    scored = _keys([row["observation_key"] for row in targets], "inner scored keys")
    if scored != [key for key in window["history_training_keys"] if key in set(scored)]:
        raise ValueError("inner scored targets must retain original admitted row order")
    reason = ("INSUFFICIENT_INNER_HISTORY" if len(days[-5:]) != 5 or len(days[:-5]) < 10
              else "NO_INNER_TRAINING_ROWS" if not training else "NO_COMPLETE_INNER_SCORE_SAMPLE" if not targets else None)
    _equal(window["unavailable_reason"], reason, "inner availability")
    family = _array(window["family_results"], "inner family results")
    if not fitted:
        if family or window["selected_index"] is not None or window["selected_recipe"] is not None:
            raise ValueError("an unavailable study cannot contain partial selection results")
        return
    if reason or len(family) != len(FAMILY):
        raise ValueError("every available inner window must contain all six family fits")
    for index, (member, result) in enumerate(zip(FAMILY, family, strict=True)):
        object_fields(result, {"candidate_index", "strategy", "model", "predictions", "mse"}, "inner family result")
        if _count(result["candidate_index"], "family index") != index:
            raise ValueError("inner family order differs")
        recipe = _recipe(member, strategy)
        _equal(result["strategy"], recipe, "fixed family recipe")
        _model(result["model"], recipe, features, window["training_keys"], window["training_boundary"], versions)
        _predictions(result["predictions"], window["validation_days"], window["validation_keys"], recipe["threshold"])
        if finite_number(result["mse"], "inner MSE") != pooled_mse(result["predictions"], targets):
            raise ValueError("inner pooled MSE differs from the complete declared score rows")
    chosen = min(range(len(FAMILY)), key=lambda index: family[index]["mse"])
    if _count(window["selected_index"], "selected index") != chosen:
        raise ValueError("inner winner must minimize pooled MSE with first-declared ties")
    _equal(window["selected_recipe"], family[chosen]["strategy"], "chosen fixed recipe")


def _metrics(metrics, prediction_count, *, complete_count=None):
    object_fields(metrics, {"prediction_count", "complete_target_count", "mae", "rmse", "r2", "unavailable_reason"}, "prediction metrics")
    count = _count(metrics["complete_target_count"], "complete targets")
    if (_count(metrics["prediction_count"], "prediction count") != prediction_count or count > prediction_count
            or (complete_count is not None and count != complete_count)):
        raise ValueError("prediction metrics differ from the declared original sample")
    if count == 0:
        if any(metrics[key] is not None for key in ("mae", "rmse", "r2")) or metrics["unavailable_reason"] != "NO_COMPLETE_TARGETS":
            raise ValueError("empty prediction error sample must remain unavailable")
    else:
        if metrics["unavailable_reason"] is not None:
            raise ValueError("complete prediction errors cannot be unavailable")
        for key in ("mae", "rmse", "r2"):
            if metrics[key] is not None:
                finite_number(metrics[key], key)
        if metrics["mae"] is None or metrics["rmse"] is None or metrics["mae"] < 0 or metrics["rmse"] < 0:
            raise ValueError("complete MAE and RMSE must be finite and nonnegative")


def validate_intraday_inner_selection_root(root):
    if root["evaluation_mode"] != "INTRADAY_INNER_SELECTION":
        raise ValueError("inner selection mode differs")
    _hash(root, "experiment_id")
    _identity(root["dataset_id"], "data ID")
    plan = normalize_inner_selection_plan(root["plan"])
    report = object_fields(root["report"], {"result_schema_version", "version", "status", "evaluation_scope", "data_id",
        "plan_sha256", "method", "source_experiment", "source_reconstruction", "fixed_reference", "benchmark",
        "outer_folds", "final_dev", "selected_account", "unavailable_reasons", "inner_selection_id"}, "inner selection report")
    _hash(report, "inner_selection_id")
    source = report["source_experiment"]
    if type(source) is not dict or source.get("artifact_schema_version") not in INTRADAY_EXPERIMENT_VERSIONS:
        raise ValueError("inner selection must embed an ordinary source, never another selection or collection")
    StrategyExperiment(canonical_json(source))
    group, reference = _selected(source, plan)
    versions = object_fields(root["algorithm_versions"], {*source["algorithm_versions"], "quadratic", "inner_selection"}, "inner algorithm versions")
    environment = object_fields(root["environment"], {"market_vault", "python", "pandas", "pyarrow"}, "environment")
    if any(type(value) is not str or not value for value in (*versions.values(), *environment.values())):
        raise ValueError("recorded versions must be nonempty strings")
    for key, value in source["algorithm_versions"].items():
        _equal(versions[key], value, "embedded source algorithm")
    if type(root["name"]) is not str or type(root["notes"]) is not str:
        raise ValueError("experiment name and notes must be strings")
    if (root["artifact_schema_version"] != INTRADAY_INNER_SELECTION_VERSION
            or report["result_schema_version"] != INTRADAY_INNER_SELECTION_RESULT_VERSION
            or report["version"] != versions["inner_selection"]
            or report["evaluation_scope"] != "DEVELOPMENT_NESTED_HOLDOUT_SELECTION_ONLY"
            or report["source_reconstruction"] != "COMPLETE_REPORT_RECONSTRUCTED"
            or root["dataset_id"] != source["dataset_id"] or report["data_id"] != root["dataset_id"]
            or report["plan_sha256"] != digest(plan)):
        raise ValueError("inner selection source, version, data or plan binding differs")
    _equal(report["method"], METHOD, "fixed method")
    _equal(report["fixed_reference"], plan["selection"], "fixed source reference")
    _equal(report["benchmark"], group["benchmark"], "original benchmark")
    context = source["report"]["context"]
    outer = _array(report["outer_folds"], "outer selection folds")
    if len(outer) != len(context["folds"]):
        raise ValueError("selection must retain every original outer fold")
    fitted = report["status"] == "AVAILABLE"
    if report["status"] not in ("AVAILABLE", "UNAVAILABLE"):
        raise ValueError("unsupported inner selection availability")
    predictions, reasons = [], []
    for index, (record, fold) in enumerate(zip(outer, context["folds"], strict=True)):
        object_fields(record, {"fold_id", "inner", "refit"}, "outer selected fold")
        _equal(record["fold_id"], fold["fold_id"], "original outer fold")
        _window(record["inner"], days=fold["training_days"], boundary=fold["training_boundary"],
                history_keys=fold["training_keys"], history_purged=fold["purged_keys"], features=context["feature_fields"],
                strategy=reference["strategy"], versions=versions, fitted=fitted)
        if record["inner"]["unavailable_reason"]:
            reasons.append({"scope": "OUTER_FOLD", "fold_index": index, "reason": record["inner"]["unavailable_reason"]})
        if not fitted:
            if record["refit"] is not None:
                raise ValueError("an unavailable study cannot partially refit outer folds")
            continue
        refit = object_fields(record["refit"], {"strategy", "model", "predictions", "prediction_metrics"}, "outer refit")
        _equal(refit["strategy"], record["inner"]["selected_recipe"], "outer selected recipe")
        _model(refit["model"], refit["strategy"], context["feature_fields"], fold["training_keys"], fold["training_boundary"], versions)
        _predictions(refit["predictions"], fold["validation_days"], fold["validation_keys"], reference["strategy"]["threshold"])
        _metrics(refit["prediction_metrics"], len(fold["validation_keys"]))
        predictions.extend(refit["predictions"])
    final = report["final_dev"]
    _window(final, days=context["split"]["TRAIN"] + context["split"]["VALIDATION"], boundary=None,
            history_keys=None, history_purged=None, features=context["feature_fields"], strategy=reference["strategy"], versions=versions, fitted=fitted)
    if (_clock(final["history_boundary"], "final DEV boundary").date().isoformat() != context["split"]["TEST"][0]
            or any(not set(fold["training_keys"]).issubset(final["history_training_keys"]) for fold in context["folds"])):
        raise ValueError("final DEV history must retain all admitted prior training rows before TEST")
    if final["unavailable_reason"]:
        reasons.append({"scope": "FINAL_DEV", "fold_index": None, "reason": final["unavailable_reason"]})
    _equal(report["unavailable_reasons"], reasons, "whole-study unavailable reasons")
    if fitted == bool(reasons):
        raise ValueError("any unavailable inner window makes the entire study unavailable")
    account = report["selected_account"]
    if not fitted:
        if account is not None:
            raise ValueError("unavailable selection must not fabricate a cash account")
        return
    object_fields(account, {"predictions", "prediction_metrics", "execution", "risk", "fold_contributions"}, "selected account")
    _equal(account["predictions"], predictions, "complete outer predictions")
    _metrics(account["prediction_metrics"], len(predictions), complete_count=reference["prediction_metrics"]["complete_target_count"])
    execution = account["execution"]
    _execution(execution, policy=group["execution_policy"], days=context["evaluated_days"], interval=context["interval"], versions=versions)
    _equal(execution["decisions"], predictions, "executed selected decisions")
    _equal(execution["windows"], reference["execution"]["windows"], "source execution windows")
    _equal(execution["price_evidence_id"], reference["execution"]["price_evidence_id"], "source prices")
    price_fields = ("trading_day", "slot", "timestamp", "phase", "row_version_id", "mark_price")
    _equal([[row[key] for key in price_fields] for row in execution["ledger"]],
           [[row[key] for key in price_fields] for row in reference["execution"]["ledger"]], "source complete price path")
    _risk(account["risk"], execution, versions)
    _equal(account["fold_contributions"], fold_cash_contributions(context, execution), "continuous fold contributions")
