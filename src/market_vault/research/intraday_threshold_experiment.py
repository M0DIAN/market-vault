"""Pure recorded-evidence validation for Q31; no source reads, fits or Q6 runs."""

from __future__ import annotations

from .intraday_backtest import parse_execution_policy
from .intraday_data import digest, finite_number, object_fields
from .intraday_experiment import INTRADAY_EXPERIMENT_VERSIONS, _array, _clock, _count, _execution, _hash, _risk
from .intraday_inner_experiment import _keys, _metrics, _model, _predictions
from .intraday_research import _identity, fold_cash_contributions
from .intraday_risk_diagnostics import summarize_intraday_risk_diagnostics
from .intraday_threshold_selection import (
    INTRADAY_THRESHOLD_SELECTION_RESULT_VERSION, INTRADAY_THRESHOLD_SELECTION_VERSION,
    METHOD, PRICE_FIELDS, RETURN_BASIS, TARGET_FIELDS, THRESHOLDS, _equal, _execution_input_status,
    _selected, normalize_threshold_selection_plan, threshold_predictions,
)
from .strategy_experiment import StrategyExperiment, canonical_json


_WINDOW_FIELDS = {"history_days", "history_boundary", "history_training_keys", "history_purged_keys", "history_targets",
    "training_days", "validation_days", "training_boundary", "training_keys", "purged_keys", "validation_keys",
    "sessions", "prices", "execution_input", "unavailable_reason", "model", "predictions", "family_results",
    "selected_index", "selected_recipe"}
_SESSION_FIELDS = {"trading_day", "open_time", "close_time", "profile", "bar_count", "missing_bar_count",
                   "warmup_bar_count", "observation_count"}
_PRICE_PATH_FIELDS = ("trading_day", "slot", "timestamp", "phase", "row_version_id", "mark_price")


def _account(execution, *, policy, days, interval, versions):
    _execution(execution, policy=policy, days=days, interval=interval, versions=versions)
    # Reuse cash/trade/ordered-equity reconciliation. Hashes alone do not
    # establish whether a larger recorded final cash is economically consistent.
    summarize_intraday_risk_diagnostics(execution)


def validate_threshold_window(window, *, days, boundary, history_keys, history_purged,
                              features, strategy, versions, policy, interval, fitted):
    """Reusable final-DEV evidence grammar, independent of the ordinary file."""
    object_fields(window, _WINDOW_FIELDS, "threshold inner window")
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
    validation = set(window["validation_keys"])
    if history.intersection(window["history_purged_keys"]):
        raise ValueError("threshold history admitted and purged keys overlap")
    _equal(window["training_days"], days[:-5], "inner TRAIN days")
    _equal(window["validation_days"], days[-5:], "inner holdout days")
    inner_clock = _clock(window["training_boundary"], "inner training boundary")
    if not days or inner_clock.date().isoformat() != days[-5:][0] or inner_clock >= history_clock:
        raise ValueError("inner training boundary must precede the historical cutoff")
    targets = _array(window["history_targets"], "historically admitted targets")
    for row in targets:
        object_fields(row, set(TARGET_FIELDS), "historically admitted target")
        if (row["trading_day"] not in days
                or _clock(row["actual_label_end_time"], "actual target end") >= history_clock):
            raise ValueError("threshold history target is not available before its cutoff")
        finite_number(row["value"], "history target")
    _equal([row["observation_key"] for row in targets], window["history_training_keys"], "history target keys")
    train = [row["observation_key"] for row in targets if row["trading_day"] in window["training_days"]
             and _clock(row["actual_label_end_time"], "actual target end") < inner_clock]
    purged = [row["observation_key"] for row in targets if row["trading_day"] in window["training_days"]
              and _clock(row["actual_label_end_time"], "actual target end") >= inner_clock]
    _equal(window["training_keys"], train, "inner admitted keys")
    _equal(window["purged_keys"], purged, "inner purged keys")
    if (set(train) | set(purged)) & validation:
        raise ValueError("inner TRAIN and holdout keys overlap")
    sessions, prices = _array(window["sessions"], "inner sessions"), _array(window["prices"], "inner prices")
    _equal([row["trading_day"] for row in sessions], window["validation_days"], "inner session dates")
    for session in sessions:
        object_fields(session, _SESSION_FIELDS, "recorded Q5 inner session")
        for key in ("bar_count", "missing_bar_count", "warmup_bar_count", "observation_count"):
            _count(session[key], key)
        if type(session["profile"]) is not str or not session["profile"]:
            raise ValueError("recorded session profile is required")
    _equal(sessions[0]["open_time"], window["training_boundary"], "inner session opening boundary")
    if any(_clock(row["close_time"], "inner close") >= history_clock for row in sessions):
        raise ValueError("inner trading sessions must complete before the historical cutoff")
    for price in prices:
        object_fields(price, set(PRICE_FIELDS), "recorded inner price")
        _identity(price["row_version_id"], "inner price row ID")
    inputs = _execution_input_status(sessions, prices, interval, parse_execution_policy(policy))
    _equal(window["execution_input"], inputs, "inner execution input status")
    reason = ("INSUFFICIENT_INNER_HISTORY" if len(days[-5:]) != 5 or len(days[:-5]) < 10
              else "NO_INNER_TRAINING_ROWS" if not train else inputs["reason"])
    _equal(window["unavailable_reason"], reason, "window availability")
    family = _array(window["family_results"], "four threshold accounts")
    if not fitted:
        if (family or window["model"] is not None or window["predictions"] or window["selected_index"] is not None
                or window["selected_recipe"] is not None):
            raise ValueError("an unavailable study cannot contain partial fits or accounts")
        return
    if reason or len(family) != len(THRESHOLDS):
        raise ValueError("each available window requires all four threshold accounts")
    _model(window["model"], strategy, features, train, window["training_boundary"], versions)
    _predictions(window["predictions"], window["validation_days"], window["validation_keys"], strategy["threshold"])
    expected_prices = [{"trading_day": row["trading_day"], "slot": row["slot"],
                        "timestamp": row["event_time" if phase == "OPEN" else "available_at"], "phase": phase,
                        "row_version_id": row["row_version_id"], "mark_price": row["open" if phase == "OPEN" else "close"]}
                       for row in prices for phase in ("OPEN", "CLOSE")]
    price_id = None
    for index, (threshold, member) in enumerate(zip(THRESHOLDS, family, strict=True)):
        object_fields(member, {"candidate_index", "threshold", "execution"}, "threshold member")
        if (_count(member["candidate_index"], "threshold index") != index
                or finite_number(member["threshold"], "threshold") != threshold):
            raise ValueError("threshold family must retain fixed values and order")
        execution = member["execution"]
        _account(execution, policy=policy, days=window["validation_days"], interval=interval, versions=versions)
        _equal(execution["decisions"], threshold_predictions(window["predictions"], threshold), "inner threshold decisions")
        _equal([{key: row[key] for key in _PRICE_PATH_FIELDS} for row in execution["ledger"]], expected_prices,
               "inner complete price path")
        if index and execution["price_evidence_id"] != price_id:
            raise ValueError("all four threshold accounts must share one price identity")
        price_id = execution["price_evidence_id"]
    chosen = max(range(len(THRESHOLDS)), key=lambda index: family[index]["execution"]["metrics"]["total_return"])
    if _count(window["selected_index"], "selected threshold index") != chosen:
        raise ValueError("threshold winner must maximize net account return with first-declared ties")
    _equal(window["selected_recipe"], {**strategy, "threshold": THRESHOLDS[chosen]}, "chosen fixed recipe")


def validate_intraday_threshold_selection_root(root):
    if root["evaluation_mode"] != "INTRADAY_THRESHOLD_SELECTION":
        raise ValueError("threshold-selection artifact mode differs")
    _hash(root, "experiment_id")
    _identity(root["dataset_id"], "data ID")
    plan = normalize_threshold_selection_plan(root["plan"])
    report = object_fields(root["report"], {"result_schema_version", "version", "status", "evaluation_scope", "data_id",
        "plan_sha256", "method", "source_experiment", "source_reconstruction", "fixed_reference", "benchmark",
        "outer_folds", "final_dev", "selected_account", "unavailable_reasons", "return_basis", "threshold_selection_id"},
        "threshold-selection report")
    _hash(report, "threshold_selection_id")
    source = report["source_experiment"]
    if type(source) is not dict or source.get("artifact_schema_version") not in INTRADAY_EXPERIMENT_VERSIONS:
        raise ValueError("threshold study must embed an ordinary DEV source, never another selection")
    StrategyExperiment(canonical_json(source))
    group, reference = _selected(source, plan)
    versions = object_fields(root["algorithm_versions"], {*source["algorithm_versions"], "threshold_selection"}, "threshold versions")
    environment = object_fields(root["environment"], {"market_vault", "python", "pandas", "pyarrow"}, "environment")
    if any(type(value) is not str or not value for value in (*versions.values(), *environment.values())):
        raise ValueError("recorded versions must be nonempty strings")
    for key, value in source["algorithm_versions"].items():
        _equal(versions[key], value, "embedded source algorithm")
    if type(root["name"]) is not str or type(root["notes"]) is not str:
        raise ValueError("experiment name and notes must be strings")
    if (root["artifact_schema_version"] != INTRADAY_THRESHOLD_SELECTION_VERSION
            or report["result_schema_version"] != INTRADAY_THRESHOLD_SELECTION_RESULT_VERSION
            or report["version"] != versions["threshold_selection"]
            or report["evaluation_scope"] != "DEVELOPMENT_INNER_ECONOMIC_THRESHOLD_SELECTION_ONLY"
            or report["source_reconstruction"] != "COMPLETE_REPORT_RECONSTRUCTED"
            or root["dataset_id"] != source["dataset_id"] or report["data_id"] != root["dataset_id"]
            or report["plan_sha256"] != digest(plan)):
        raise ValueError("threshold-selection source, version, data or plan binding differs")
    _equal(report["method"], METHOD, "fixed method")
    _equal(report["return_basis"], RETURN_BASIS, "return basis")
    _equal(report["fixed_reference"], plan["selection"], "fixed source reference")
    _equal(report["benchmark"], group["benchmark"], "original benchmark")
    context = source["report"]["context"]
    outer = _array(report["outer_folds"], "outer threshold folds")
    if len(outer) != len(context["folds"]):
        raise ValueError("threshold selection must retain every original outer fold")
    if report["status"] not in ("AVAILABLE", "UNAVAILABLE"):
        raise ValueError("unsupported threshold-selection availability")
    fitted = report["status"] == "AVAILABLE"
    predictions, reasons = [], []
    shared = {"features": context["feature_fields"], "strategy": reference["strategy"], "versions": versions,
              "policy": group["execution_policy"], "interval": context["interval"], "fitted": fitted}
    for index, (record, fold, model) in enumerate(zip(outer, context["folds"], reference["fold_models"], strict=True)):
        object_fields(record, {"fold_id", "inner", "application"}, "outer threshold application")
        _equal(record["fold_id"], fold["fold_id"], "original outer fold")
        validate_threshold_window(record["inner"], days=fold["training_days"], boundary=fold["training_boundary"],
                                  history_keys=fold["training_keys"], history_purged=fold["purged_keys"], **shared)
        if record["inner"]["unavailable_reason"]:
            reasons.append({"scope": "OUTER_FOLD", "fold_index": index, "reason": record["inner"]["unavailable_reason"]})
        if not fitted:
            if record["application"] is not None:
                raise ValueError("an unavailable study cannot partially apply outer thresholds")
            continue
        application = object_fields(record["application"], {"strategy", "model", "predictions", "prediction_metrics"}, "outer application")
        _equal(application["strategy"], record["inner"]["selected_recipe"], "outer selected threshold recipe")
        _equal(application["model"], model["model"], "original outer fixed model")
        expected = threshold_predictions([row for row in reference["predictions"] if row["trading_day"] in fold["validation_days"]],
                                         application["strategy"]["threshold"])
        _equal(application["predictions"], expected, "original outer scores and chosen threshold")
        _metrics(application["prediction_metrics"], len(expected))
        predictions.extend(expected)
    final = report["final_dev"]
    validate_threshold_window(final, days=context["split"]["TRAIN"] + context["split"]["VALIDATION"], boundary=None,
                              history_keys=None, history_purged=None, **shared)
    if (_clock(final["history_boundary"], "final DEV boundary").date().isoformat() != context["split"]["TEST"][0]
            or any(not set(fold["training_keys"]).issubset(final["history_training_keys"]) for fold in context["folds"])):
        raise ValueError("final DEV history must retain prior admitted training rows before TEST")
    if final["unavailable_reason"]:
        reasons.append({"scope": "FINAL_DEV", "fold_index": None, "reason": final["unavailable_reason"]})
    _equal(report["unavailable_reasons"], reasons, "whole-study unavailable reasons")
    if fitted == bool(reasons):
        raise ValueError("any unavailable window makes the entire threshold study unavailable")
    account = report["selected_account"]
    if not fitted:
        if account is not None:
            raise ValueError("an unavailable threshold study cannot invent a cash account")
        return
    object_fields(account, {"predictions", "prediction_metrics", "execution", "risk", "fold_contributions"}, "selected account")
    _equal(account["predictions"], predictions, "complete selected outer predictions")
    _equal(account["prediction_metrics"], reference["prediction_metrics"], "fixed-score prediction metrics")
    execution = account["execution"]
    _account(execution, policy=group["execution_policy"], days=context["evaluated_days"], interval=context["interval"], versions=versions)
    _equal(execution["decisions"], predictions, "selected outer decisions")
    for key in ("windows", "price_evidence_id"):
        _equal(execution[key], reference["execution"][key], "source " + key)
    _equal([[row[key] for key in _PRICE_PATH_FIELDS] for row in execution["ledger"]],
           [[row[key] for key in _PRICE_PATH_FIELDS] for row in reference["execution"]["ledger"]], "source complete outer price path")
    _risk(account["risk"], execution, versions)
    _equal(account["fold_contributions"], fold_cash_contributions(context, execution), "continuous outer fold contributions")
