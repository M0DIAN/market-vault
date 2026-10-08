"""Intraday experiment grammar over the existing immutable experiment writer.

Open checks the saved structure and internal bindings without executing models
or opening source data. Replay verifies source identity and every raw result.
"""

from __future__ import annotations

from hashlib import sha256
from datetime import datetime, timedelta
from pathlib import Path

from ..backtest.intraday import _digest as execution_digest
from .intraday_data import digest, finite_number, object_fields
from .intraday_research import (
    INTRADAY_DIAGNOSTICS_PLAN_VERSION, INTRADAY_RESEARCH_RESULT_VERSION,
    _day, _evaluate_intraday_research, _identity, _prepare_intraday_research,
    expand_intraday_plan, fold_cash_contributions, research_algorithm_versions,
)
from .strategy_experiment import StrategyExperiment, canonical_json, environment_versions


INTRADAY_EXPERIMENT_VERSION = "market-vault-intraday-experiment-v1"
_CONTEXT_FIELDS = {"version", "data_id", "symbol", "interval", "feature_fields", "target_horizon_bars", "split", "folds",
                   "evaluated_days", "unevaluated_development_days", "validation_keys", "held_out_test_observation_count", "context_id"}
_EXECUTION_FIELDS = {"version", "cost_version", "event_order", "interval", "policy", "price_evidence_id", "windows", "decisions",
                     "trades", "transactions", "ledger", "daily", "metrics", "execution_id"}
_CANDIDATE_FIELDS = {"candidate_index", "strategy", "axis_values", "context_id", "predictions", "fold_models", "prediction_metrics",
                     "execution", "risk", "fold_contributions", "return_change_from_first_cost", "candidate_id"}


def _array(value, label):
    if type(value) is not list:
        raise ValueError(f"{label} must be an array")
    return value


def _count(value, label):
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return value


def _hash(value, key, *, function=digest):
    _identity(value[key], key)
    if value[key] != function({k: v for k, v in value.items() if k != key}):
        raise ValueError(f"saved {key} does not bind complete content")


def _strings(value, label, *, unique=True):
    values = _array(value, label)
    if any(type(v) is not str or not v for v in values) or (unique and len(set(values)) != len(values)):
        raise ValueError(f"{label} must contain nonempty unique strings")
    return values


def _clock(value, label):
    if type(value) is not str:
        raise ValueError(f"{label} must be an aware timestamp")
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError(f"{label} must be an aware timestamp")
    return result


def _decisions(values, days):
    clocks, keys = [], []
    for row in _array(values, "decisions"):
        object_fields(row, {"observation_key", "trading_day", "slot", "decision_time", "target", "score"}, "decision")
        keys.append(_identity(row["observation_key"], "observation_key"))
        clocks.append(_clock(row["decision_time"], "decision_time"))
        _count(row["slot"], "decision slot")
        if row["target"] not in ("LONG", "FLAT") or row["trading_day"] not in days:
            raise ValueError("decision target or day is invalid")
        if row["score"] is not None:
            finite_number(row["score"], "decision score")
    if clocks != sorted(set(clocks)) or len(keys) != len(set(keys)):
        raise ValueError("decisions must have unique increasing clocks and identities")


def _risk(risk, execution, versions):
    object_fields(risk, {"version", "execution_id", "annualization_factor", "risk_free_rate", "ddof", "zero_volatility_tolerance",
                         "return_count", "mean_daily_return", "annualized_volatility", "sharpe_ratio", "unavailable_reason", "risk_id"}, "intraday risk")
    _hash(risk, "risk_id")
    count = _count(risk["return_count"], "daily return_count")
    if (risk["version"] != versions["daily_risk"] or risk["execution_id"] != execution["execution_id"]
            or count != len(execution["daily"]) or risk["annualization_factor"] != 252
            or type(risk["annualization_factor"]) is not int or risk["risk_free_rate"] != 0
            or type(risk["risk_free_rate"]) not in (int, float) or type(risk["ddof"]) is not int or risk["ddof"] != 1):
        raise ValueError("intraday risk must bind every evaluated day's open-to-close return")
    if finite_number(risk["zero_volatility_tolerance"], "zero tolerance") < 0:
        raise ValueError("risk tolerance cannot be negative")
    for key in ("mean_daily_return", "annualized_volatility", "sharpe_ratio"):
        if risk[key] is not None:
            finite_number(risk[key], key)
    reason, vol, sharpe = risk["unavailable_reason"], risk["annualized_volatility"], risk["sharpe_ratio"]
    if ((count == 0) != (risk["mean_daily_return"] is None)
            or (count < 2 and (reason != "INSUFFICIENT_DAILY_RETURNS" or vol is not None or sharpe is not None))
            or (count >= 2 and reason not in (None, "ZERO_VOLATILITY"))
            or (reason == "ZERO_VOLATILITY" and (vol != 0 or sharpe is not None))
            or (reason is None and (vol is None or vol <= 0 or sharpe is None))):
        raise ValueError("intraday risk availability differs from its day count")


def _execution(value, *, policy, days, interval, versions):
    object_fields(value, _EXECUTION_FIELDS, "intraday execution")
    _hash(value, "execution_id", function=execution_digest)
    _identity(value["price_evidence_id"], "price_evidence_id")
    if (value["version"] != versions["execution"] or value["cost_version"] != versions["cost"]
            or value["interval"] != interval or value["policy"] != policy
            or value["event_order"] != "BAR_CLOSE_THEN_DECISION_THEN_NEXT_PLANNED_OPEN"):
        raise ValueError("execution version, policy or phase binding differs")
    daily = _array(value["daily"], "daily")
    if [r["trading_day"] for r in daily] != days:
        raise ValueError("all candidates must share the complete evaluated dates")
    previous, trade_count = 1.0, 0
    for row in daily:
        object_fields(row, {"trading_day", "open_time", "close_time", "cash_open", "cash_close", "return", "trade_count"}, "daily cash")
        if _clock(row["open_time"], "daily open") >= _clock(row["close_time"], "daily close"):
            raise ValueError("daily session clocks must increase")
        for key in ("cash_open", "cash_close", "return"):
            finite_number(row[key], key)
        if row["cash_open"] != previous or row["cash_close"] <= 0 or row["return"] != row["cash_close"] / previous - 1:
            raise ValueError("daily cash must form one continuous positive account")
        previous = row["cash_close"]
        trade_count += _count(row["trade_count"], "daily trade count")
    metrics = object_fields(value["metrics"], {"initial_cash", "final_cash", "total_return", "trade_count", "observed_max_drawdown",
                                                "commission_total", "slippage_total"}, "execution metrics")
    for key in metrics:
        finite_number(metrics[key], key)
    if (metrics["initial_cash"] != 1 or metrics["final_cash"] != previous or metrics["total_return"] != previous - 1
            or _count(metrics["trade_count"], "trade count") != trade_count):
        raise ValueError("execution summary differs from its daily account")
    trades, transactions, ledger = (_array(value[key], key) for key in ("trades", "transactions", "ledger"))
    if len(trades) != trade_count or len(transactions) != 2 * trade_count or not ledger:
        raise ValueError("complete trades, transactions and ledger are required")
    for trade in trades:
        object_fields(trade, {"trading_day", "signal_time", "entry_time", "entry_slot", "entry_observation_key",
            "entry_row_version_id", "entry_raw_open", "entry_fill_price", "quantity", "cash_before", "entry_commission",
            "entry_slippage", "exit_time", "exit_slot", "exit_row_version_id", "exit_reason", "exit_observation_key",
            "exit_raw_open", "exit_fill_price", "cash_after", "commission_total", "slippage_total", "held_bars",
            "gross_return", "net_return", "trade_id"}, "trade")
        _hash(trade, "trade_id", function=execution_digest)
        for key in ("entry_observation_key", "entry_row_version_id", "exit_row_version_id"):
            _identity(trade[key], key)
        if trade["exit_observation_key"] is not None:
            _identity(trade["exit_observation_key"], "exit observation")
        if trade["trading_day"] not in days or trade["exit_reason"] not in ("EOD", "MAX_HOLD", "TARGET_FLAT"):
            raise ValueError("trade day or exit reason is invalid")
        for key in ("entry_raw_open", "entry_fill_price", "quantity", "cash_before", "exit_raw_open", "exit_fill_price", "cash_after"):
            if finite_number(trade[key], key) <= 0:
                raise ValueError("trade prices, quantity and settled cash must be positive")
        for key in ("entry_commission", "entry_slippage", "commission_total", "slippage_total"):
            if finite_number(trade[key], key) < 0:
                raise ValueError("trade costs cannot be negative")
        for key in ("gross_return", "net_return"):
            finite_number(trade[key], key)
        if (_count(trade["exit_slot"], "exit slot") - _count(trade["entry_slot"], "entry slot") != _count(trade["held_bars"], "held bars")
                or trade["held_bars"] < 1 or not _clock(trade["signal_time"], "signal time") <= _clock(trade["entry_time"], "entry time") < _clock(trade["exit_time"], "exit time")):
            raise ValueError("trade holding slots or clocks are invalid")
    transaction_clocks = []
    for index, row in enumerate(transactions):
        object_fields(row, {"trading_day", "slot", "timestamp", "row_version_id", "side", "reason", "raw_open", "fill_price",
                            "quantity", "commission", "slippage", "cash_before", "cash_after"}, "transaction")
        _count(row["slot"], "transaction slot")
        _identity(row["row_version_id"], "transaction price row")
        transaction_clocks.append(_clock(row["timestamp"], "transaction time"))
        if (row["trading_day"] not in days or row["side"] != ("BUY" if index % 2 == 0 else "SELL")
                or row["reason"] not in (("TARGET_LONG",) if index % 2 == 0 else ("EOD", "MAX_HOLD", "TARGET_FLAT"))):
            raise ValueError("transactions must preserve ordered entry and exit pairs")
        for key in ("raw_open", "fill_price", "quantity", "commission", "slippage", "cash_before", "cash_after"):
            if finite_number(row[key], key) < 0 or (key in ("raw_open", "fill_price", "quantity") and row[key] == 0):
                raise ValueError("transaction amount is invalid")
    if transaction_clocks != sorted(set(transaction_clocks)):
        raise ValueError("transaction clocks must increase")
    ledger_fields = {"sequence", "trading_day", "slot", "timestamp", "phase", "action", "reason", "observation_key",
                     "row_version_id", "mark_price", "cash", "quantity", "equity", "drawdown"}
    seen, last_clock = {}, None
    for index, row in enumerate(ledger):
        object_fields(row, ledger_fields, "ledger point")
        clock = _clock(row["timestamp"], "ledger time")
        if last_clock is not None and clock < last_clock:
            raise ValueError("ledger must preserve aware chronological event phases")
        last_clock = clock
        if type(row["sequence"]) is not int or row["sequence"] != index or row["trading_day"] not in days:
            raise ValueError("ledger sequence or day coverage differs")
        slot = _count(row["slot"], "ledger slot")
        phase_index = seen.get(row["trading_day"], 0)
        if slot != phase_index // 2 or row["phase"] != ("OPEN" if phase_index % 2 == 0 else "CLOSE"):
            raise ValueError("ledger must retain each ordered OPEN and CLOSE")
        seen[row["trading_day"]] = phase_index + 1
        _identity(row["row_version_id"], "ledger row ID")
        if row["observation_key"] is not None:
            _identity(row["observation_key"], "ledger observation")
        if row["action"] not in ("CASH", "HOLD", "BUY", "SELL", "MARK") or type(row["reason"]) is not str:
            raise ValueError("ledger action or reason is invalid")
        for key in ("mark_price", "cash", "quantity", "equity", "drawdown"):
            if finite_number(row[key], key) < 0:
                raise ValueError("ledger prices and account values cannot be negative")
    if set(seen) != set(days) or any(n % 2 for n in seen.values()):
        raise ValueError("ledger has an incomplete evaluated day")
    if [r["trading_day"] for r in _array(value["windows"], "windows")] != days:
        raise ValueError("execution windows differ from evaluated days")
    for window, day in zip(value["windows"], daily, strict=True):
        object_fields(window, {"trading_day", "earliest_entry_time", "stop_new_time", "forced_flat_time", "forced_flat_slot"}, "entry window")
        opened, closed = _clock(day["open_time"], "daily open"), _clock(day["close_time"], "daily close")
        delta = timedelta(minutes=int(interval[:-1]))
        if (seen[day["trading_day"]] != 2 * ((closed - opened) // delta)
                or _clock(window["earliest_entry_time"], "earliest entry") != opened + timedelta(minutes=policy["entry_delay_minutes"])
                or _clock(window["stop_new_time"], "stop new") != closed - timedelta(minutes=policy["stop_new_minutes"])
                or _count(window["forced_flat_slot"], "forced flat slot") != (closed - timedelta(minutes=policy["flatten_minutes"]) - opened) // delta
                or _clock(window["forced_flat_time"], "forced flat time") != opened + window["forced_flat_slot"] * delta):
            raise ValueError("entry windows or complete ledger grid differ from the recorded session")
    _decisions(value["decisions"], days)


def validate_intraday_experiment_root(root):
    """Offline structural validation; hashes alone are not execution proof."""
    if type(root["plan"]) is not dict:
        raise ValueError("saved intraday plan must be an object")
    mode = "INTRADAY_DIAGNOSTICS" if root["plan"].get("plan_schema_version") == INTRADAY_DIAGNOSTICS_PLAN_VERSION else "INTRADAY_COMPARISON"
    if root["evaluation_mode"] != mode:
        raise ValueError("intraday experiment mode differs from the plan")
    _identity(root["dataset_id"], "data_id")
    _hash(root, "experiment_id", function=lambda v: sha256(canonical_json(v)).hexdigest())
    normalized, children, axis_values = expand_intraday_plan(root["plan"], recorded=True)
    if canonical_json(normalized) != canonical_json(root["plan"]) or normalized.get("data_id", children[0]["data_id"]) != root["dataset_id"]:
        raise ValueError("saved normalized plan or data binding differs")
    versions = object_fields(root["algorithm_versions"], research_algorithm_versions(normalized), "intraday algorithm versions")
    environment = object_fields(root["environment"], {"market_vault", "python", "pandas", "pyarrow"}, "environment")
    if any(type(v) is not str or not v for v in (*versions.values(), *environment.values())):
        raise ValueError("recorded algorithm/environment versions must be nonempty strings")
    if type(root["name"]) is not str or type(root["notes"]) is not str:
        raise ValueError("experiment name and notes must be strings")
    report = object_fields(root["report"], {"result_schema_version", "version", "status", "evaluation_scope", "data_id",
                                            "plan_sha256", "context", "groups", "evaluation_count", "research_id"}, "intraday research report")
    _hash(report, "research_id")
    if (report["status"] != "SUCCESS" or report["evaluation_scope"] != "DEVELOPMENT_WALK_FORWARD_ONLY"
            or report["result_schema_version"] != INTRADAY_RESEARCH_RESULT_VERSION or report["version"] != versions["research"]
            or report["data_id"] != root["dataset_id"] or report["plan_sha256"] != digest(normalized)):
        raise ValueError("intraday report plan, scope or version binding differs")
    context = object_fields(report["context"], _CONTEXT_FIELDS, "intraday common context")
    _hash(context, "context_id")
    if context["data_id"] != root["dataset_id"] or context["version"] != versions["walk_forward"] or context["feature_fields"] != children[0]["feature_fields"]:
        raise ValueError("intraday common context differs from the plan")
    if type(context["symbol"]) is not str or not context["symbol"].startswith("US.") or context["interval"] not in ("1m", "5m", "15m", "30m"):
        raise ValueError("unsupported intraday context scope")
    if context["target_horizon_bars"] is not None and _count(context["target_horizon_bars"], "target horizon") < 1:
        raise ValueError("training target horizon must be positive or null")
    parts = object_fields(context["split"], {"TRAIN", "VALIDATION", "TEST"}, "split days")
    all_days = []
    for part in ("TRAIN", "VALIDATION", "TEST"):
        values = _strings(parts[part], part)
        if not values or values[-1] != children[0]["split"][{"TRAIN": "train_end_day", "VALIDATION": "validation_end_day", "TEST": "test_end_day"}[part]]:
            raise ValueError("split actual boundaries differ from the plan")
        all_days.extend(values)
        for day in values:
            _day(day, "split day")
    if all_days != sorted(set(all_days)):
        raise ValueError("split dates must increase without overlap")
    days = _strings(context["evaluated_days"], "evaluated days")
    dev = parts["TRAIN"] + parts["VALIDATION"]
    folds, joined_days, joined_keys = _array(context["folds"], "folds"), [], []
    walk = children[0]["walk_forward"]
    starts = list(range(walk["minimum_train_days"], len(dev) - walk["validation_days"] + 1, walk["step_days"]))
    if len(folds) != len(starts) or not folds:
        raise ValueError("saved folds must cover the explicit development walk-forward")
    for index, (fold, start) in enumerate(zip(folds, starts, strict=True)):
        object_fields(fold, {"fold_index", "training_days", "validation_days", "training_boundary", "training_keys", "purged_keys", "validation_keys", "fold_id"}, "day fold")
        _hash(fold, "fold_id")
        _clock(fold["training_boundary"], "training boundary")
        if _count(fold["fold_index"], "fold index") != index or fold["training_days"] != dev[:start] or fold["validation_days"] != dev[start:start + walk["validation_days"]]:
            raise ValueError("fold day boundaries differ from expanding plan")
        for key in ("training_keys", "purged_keys", "validation_keys"):
            for identity in _strings(fold[key], key):
                _identity(identity, key)
        if set(fold["training_keys"]) & set(fold["purged_keys"]):
            raise ValueError("purged rows cannot enter training")
        if not fold["validation_keys"]:
            raise ValueError("validation fold has no READY observations")
        joined_days.extend(fold["validation_days"])
        joined_keys.extend(fold["validation_keys"])
    if (joined_days != days or joined_keys != _strings(context["validation_keys"], "validation keys")
            or context["unevaluated_development_days"] != [day for day in dev if day not in days]):
        raise ValueError("common evaluated dates or READY keys differ from the folds")
    _count(context["held_out_test_observation_count"], "held out TEST count")
    groups = _array(report["groups"], "cost groups")
    if len(groups) != len(children) or _count(report["evaluation_count"], "evaluation count") != len(children) * len(axis_values):
        raise ValueError("the report must retain every declared evaluation")
    price_id = None
    for cost_index, (group, child) in enumerate(zip(groups, children, strict=True)):
        object_fields(group, {"cost_index", "execution_policy", "results", "benchmark"}, "cost group")
        if _count(group["cost_index"], "cost index") != cost_index or group["execution_policy"] != child["execution"]:
            raise ValueError("cost scenario order or policy differs")
        results = _array(group["results"], "candidate results")
        if len(results) != len(child["strategies"]):
            raise ValueError("candidate coverage differs from the actual expanded plan")
        for index, (candidate, strategy) in enumerate(zip(results, child["strategies"], strict=True)):
            object_fields(candidate, _CANDIDATE_FIELDS, "candidate")
            _hash(candidate, "candidate_id")
            if _count(candidate["candidate_index"], "candidate index") != index or candidate["strategy"] != strategy or candidate["axis_values"] != list(axis_values[index]) or candidate["context_id"] != context["context_id"]:
                raise ValueError("candidate identity must bind its actual strategy, axes and context")
            predictions = _array(candidate["predictions"], "predictions")
            if [r["observation_key"] for r in predictions] != context["validation_keys"]:
                raise ValueError("all candidates must predict the common READY observations")
            for row in predictions:
                object_fields(row, {"observation_key", "trading_day", "slot", "decision_time", "target", "score"}, "prediction")
                finite_number(row["score"], "prediction score")
                if row["target"] not in ("LONG", "FLAT") or row["trading_day"] not in days:
                    raise ValueError("prediction target or day is invalid")
            execution = candidate["execution"]
            _execution(execution, policy=child["execution"], days=days, interval=context["interval"], versions=versions)
            if execution["decisions"] != predictions:
                raise ValueError("execution decisions differ from the complete predictions")
            if price_id is not None and execution["price_evidence_id"] != price_id:
                raise ValueError("candidates must share the same price evidence")
            price_id = execution["price_evidence_id"]
            _risk(candidate["risk"], execution, versions)
            if candidate["fold_contributions"] != fold_cash_contributions(context, execution):
                raise ValueError("fold contributions differ from actual daily cash changes")
            expected_delta = execution["metrics"]["total_return"] - groups[0]["results"][index]["execution"]["metrics"]["total_return"]
            if finite_number(candidate["return_change_from_first_cost"], "cost return change") != expected_delta:
                raise ValueError("cost difference does not use the corresponding first-cost candidate")
            models = _array(candidate["fold_models"], "fold models")
            if strategy["kind"] == "RIDGE":
                if len(models) != len(folds):
                    raise ValueError("every Ridge fold needs its own training model")
                for record, fold in zip(models, folds, strict=True):
                    object_fields(record, {"fold_id", "model"}, "fold model")
                    model = object_fields(record["model"], {"version", "alpha", "feature_fields", "training_keys", "training_boundary", "intercept", "coefficients", "means", "scales", "model_id"}, "Ridge model")
                    _hash(model, "model_id")
                    if (record["fold_id"] != fold["fold_id"] or model["version"] != versions["ridge"] or model["alpha"] != strategy["alpha"]
                            or model["training_keys"] != fold["training_keys"] or model["training_boundary"] != fold["training_boundary"] or model["feature_fields"] != context["feature_fields"]):
                        raise ValueError("Ridge model differs from its own training fold")
                    finite_number(model["intercept"], "intercept")
                    for key in ("coefficients", "means", "scales"):
                        if len(_array(model[key], key)) != len(context["feature_fields"]):
                            raise ValueError("Ridge vector differs from explicit Feature order")
                        for number in model[key]:
                            finite_number(number, key)
                errors = object_fields(candidate["prediction_metrics"], {"prediction_count", "complete_target_count", "mae", "rmse", "r2", "unavailable_reason"}, "prediction metrics")
                count = _count(errors["complete_target_count"], "complete targets")
                if _count(errors["prediction_count"], "prediction count") != len(predictions) or count > len(predictions):
                    raise ValueError("prediction and target-error counts differ")
                for key in ("mae", "rmse", "r2"):
                    if errors[key] is not None:
                        finite_number(errors[key], key)
            elif models or candidate["prediction_metrics"] is not None:
                raise ValueError("rule execution must not invent a training model")
            if cost_index and (predictions != groups[0]["results"][index]["predictions"] or models != groups[0]["results"][index]["fold_models"]):
                raise ValueError("cost scenarios cannot change model training or predictions")
        benchmark = object_fields(group["benchmark"], {"version", "definition", "execution", "risk"}, "daily benchmark")
        if benchmark["version"] != versions["benchmark"] or benchmark["definition"] != {"entry": "FIRST_ELIGIBLE_READY", "exit": "EOD", "max_hold_rule": "FULL_EVALUATED_SESSION_GRID"}:
            raise ValueError("daily benchmark definition differs")
        counts = {day: sum(row["phase"] == "OPEN" and row["trading_day"] == day for row in benchmark["execution"]["ledger"]) for day in days}
        policy = {**child["execution"], "max_hold_bars": max(counts.values())}
        _execution(benchmark["execution"], policy=policy, days=days, interval=context["interval"], versions=versions)
        if benchmark["execution"]["price_evidence_id"] != price_id or any(r["trade_count"] > 1 for r in benchmark["execution"]["daily"]):
            raise ValueError("benchmark must use the same prices and at most one trade per day")
        _risk(benchmark["risk"], benchmark["execution"], versions)


def create_intraday_experiment(*, plan: dict, report: dict, name: str = "", notes: str = "") -> StrategyExperiment:
    normalized, _, _ = expand_intraday_plan(plan, recorded=True)
    root = {"artifact_schema_version": INTRADAY_EXPERIMENT_VERSION, "dataset_id": report["data_id"],
            "evaluation_mode": "INTRADAY_DIAGNOSTICS" if normalized["plan_schema_version"] == INTRADAY_DIAGNOSTICS_PLAN_VERSION else "INTRADAY_COMPARISON",
            "algorithm_versions": research_algorithm_versions(normalized), "environment": environment_versions(),
            "plan": normalized, "report": report, "name": name, "notes": notes}
    root["experiment_id"] = sha256(canonical_json(root)).hexdigest()
    return StrategyExperiment(canonical_json(root))


def replay_intraday_experiment(snapshot: StrategyExperiment, *, intraday_data_file: str | Path | None = None) -> dict:
    root = snapshot.as_dict()
    if root["algorithm_versions"] != research_algorithm_versions(root["plan"]):
        raise ValueError("recorded intraday algorithm versions differ; no source was read or model fitted")
    normalized, children, values = expand_intraday_plan(root["plan"], recorded=True)
    prepared = _prepare_intraday_research(children[0], data_file=intraday_data_file)
    actual = _evaluate_intraday_research(normalized, children, values, prepared)
    expected_bytes, actual_bytes = canonical_json(root["report"]), canonical_json(actual)
    if expected_bytes != actual_bytes:
        raise ValueError("replay complete intraday report mismatch")
    return {"experiment_id": snapshot.experiment_id, "data_id": prepared.data.data_id, "research_id": actual["research_id"],
            "report_matches": True, "expected_report_sha256": sha256(expected_bytes).hexdigest(), "actual_report_sha256": sha256(actual_bytes).hexdigest()}
