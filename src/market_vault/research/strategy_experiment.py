"""Explicit immutable experiment records, offline viewing and verified replay.

The file digest detects corruption and binds the complete saved input/output.
It is not proof of execution: replay reloads the verified Dataset and compares
the complete raw result. No scan, latest pointer, overwrite or database exists.
"""

from __future__ import annotations

import codecs
from dataclasses import dataclass, fields
from datetime import date, datetime
from hashlib import sha256
from importlib import metadata
import json
import os
from pathlib import Path, PureWindowsPath
import platform
import re

from .._version import __version__
from ..backtest.models import BACKTEST_ENGINE_VERSION, BacktestMetrics, BacktestTrade, _finite_number
from ..backtest.equity import EQUITY_VERSION, BUY_AND_HOLD_VERSION, EquityPoint
from ..backtest.risk import DAILY_RISK_VERSION, DailyRisk, DailyEquity, DailyReturn
from ..backtest_cli import BacktestCLIError
from ..dataset.cli import DatasetCLIError, _no_duplicate_pairs, _resolve_plan_path
from ..strategy_comparison_io import (
    STRATEGY_COMPARISON_CLI_VERSION, STRATEGY_EQUITY_CLI_VERSION, STRATEGY_RISK_CLI_VERSION,
    _cli_result_version, canonical_json, evaluate_comparison_payload, normalized_comparison_plan,
    parse_strategy_comparison_plan_bytes,
)
from .experiment import EXPERIMENT_METADATA_VERSION
from .ml import ML_DATASET_ADAPTER_VERSION
from .ridge_baseline import RIDGE_BASELINE_VERSION
from .strategy_comparison import (
    COMPOSITE_RULE_VERSION, EVALUATION_SCOPE, STRATEGY_COMPARISON_VERSION,
    STRATEGY_COMPARISON_V2_VERSION, CompositeRuleStrategy, RidgeStrategy, _strategy_fields,
)
from .strategy_equity import STRATEGY_EQUITY_VERSION
from .strategy_risk import STRATEGY_RISK_VERSION, BENCHMARK_DEFINITION, StrategyRiskResult
from .walk_forward import WALK_FORWARD_VERSION


STRATEGY_EXPERIMENT_VERSION = "market-vault-strategy-experiment-v1"
STRATEGY_EXPERIMENT_V2_VERSION = "market-vault-strategy-experiment-v2"
_ROOT_FIELDS = {
    "artifact_schema_version", "experiment_id", "dataset_id", "evaluation_mode",
    "algorithm_versions", "environment", "plan", "report", "name", "notes",
}
_REPORT_FIELDS = {
    "result_schema_version", "status", "version", "comparison_id", "engine_version",
    "evaluation_scope", "dataset_id", "walk_forward_id", "feature_names", "return_label",
    "costs", "minimum_train_periods", "validation_periods", "step_periods",
    "held_out_test_sample_count", "validation_sample_keys", "folds", "results",
}
_SHA = re.compile(r"^[0-9a-f]{64}$")
_MODES = {"COMPARISON": STRATEGY_COMPARISON_CLI_VERSION,
          "EQUITY": STRATEGY_EQUITY_CLI_VERSION, "RISK": STRATEGY_RISK_CLI_VERSION}


def _object(value, expected, label):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError(f"{label} must have exactly these fields: {', '.join(sorted(expected))}")
    return value


def _array(value, label, *, nonempty=False):
    if type(value) is not list or (nonempty and not value):
        raise ValueError(f"{label} must be a {'non-empty ' if nonempty else ''}JSON array")
    return value


def _string(value, label):
    if type(value) is not str or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _identity(value, label):
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 identity")
    return value


def _count(value, label):
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _time(value):
    parsed = datetime.fromisoformat(_string(value, "timestamp"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must carry a timezone")
    return parsed


def _record(value, model, label):
    return _object(value, {field.name for field in fields(model)}, label)


def algorithm_versions(config: dict, mode: str) -> dict[str, str]:
    """Only algorithms applicable to this explicit experiment are replay gates."""
    if mode not in _MODES:
        raise ValueError("unsupported experiment evaluation_mode")
    composite = any(type(item) is CompositeRuleStrategy for item in config["strategies"])
    versions = {
        "ml_adapter": ML_DATASET_ADAPTER_VERSION, "experiment": EXPERIMENT_METADATA_VERSION,
        "walk_forward": WALK_FORWARD_VERSION, "backtest": BACKTEST_ENGINE_VERSION,
        "comparison": STRATEGY_COMPARISON_V2_VERSION if composite else STRATEGY_COMPARISON_VERSION,
    }
    if composite:
        versions["composite_rule"] = COMPOSITE_RULE_VERSION
    if any(type(item) is RidgeStrategy for item in config["strategies"]):
        versions["ridge"] = RIDGE_BASELINE_VERSION
    if mode in ("EQUITY", "RISK"):
        versions.update(equity=EQUITY_VERSION, strategy_equity=STRATEGY_EQUITY_VERSION)
    if mode == "RISK":
        versions.update(buy_and_hold=BUY_AND_HOLD_VERSION, daily_risk=DAILY_RISK_VERSION,
                        strategy_risk=STRATEGY_RISK_VERSION)
    return versions


def environment_versions() -> dict[str, str]:
    result = {"market_vault": __version__, "python": platform.python_version()}
    for package in ("pandas", "pyarrow"):
        try:
            result[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            result[package] = "unavailable"
    return result


def _validate_curve(curve, *, version, start, end, strategy_result=False):
    expected = {"version", "curve_id", "final_equity", "bar_close_max_drawdown",
                "transaction_cost_total", "points"}
    _object(curve, expected | ({"strategy_result_id"} if strategy_result else set()), "curve")
    if curve["version"] != version:
        raise ValueError("curve differs from recorded algorithm version")
    _identity(curve["curve_id"], "curve_id")
    for key in ("final_equity", "bar_close_max_drawdown", "transaction_cost_total"):
        if _finite_number(curve[key], key) < 0:
            raise ValueError(f"curve {key} must be non-negative")
    points = _array(curve["points"], "curve points", nonempty=True)
    clocks = []
    for point in points:
        _record(point, EquityPoint, "equity point")
        clocks.append(_time(point["timestamp"]))
        if point["event"] not in ("INITIAL", "ENTRY", "BAR_CLOSE", "EXIT"):
            raise ValueError("unsupported equity event")
        for key in ("cash", "quantity", "market_value", "equity", "drawdown", "transaction_cost"):
            if _finite_number(point[key], key) < 0:
                raise ValueError(f"equity point {key} must be non-negative")
        if point["equity"] <= 0:
            raise ValueError("equity must remain positive")
        if point["mark_price"] is not None and _finite_number(point["mark_price"], "mark_price") <= 0:
            raise ValueError("mark_price must be positive or null")
        for key in ("sample_key", "row_version_id"):
            if point[key] is not None:
                _identity(point[key], key)
    if clocks != sorted(clocks) or clocks[0] != start or clocks[-1] != end:
        raise ValueError("curve clocks must cover the recorded valuation window in order")
    if curve["final_equity"] != points[-1]["equity"]:
        raise ValueError("curve final_equity differs from its final point")


def _validate_daily_risk(value, version):
    _record(value, DailyRisk, "daily risk")
    if value["version"] != version:
        raise ValueError("daily risk differs from recorded algorithm version")
    _identity(value["risk_id"], "risk_id")
    if _count(value["annualization_factor"], "annualization_factor") == 0:
        raise ValueError("annualization_factor must be positive")
    _finite_number(value["risk_free_rate"], "risk_free_rate")
    for key in ("mean_daily_return", "annualized_volatility", "sharpe_ratio"):
        if value[key] is not None:
            _finite_number(value[key], key)
    if value["unavailable_reason"] not in (None, "INSUFFICIENT_DAILY_RETURNS", "ZERO_VOLATILITY"):
        raise ValueError("unsupported daily risk availability reason")
    observations = _array(value["observations"], "daily observations")
    returns = _array(value["returns"], "daily returns")
    if (_count(value["observation_count"], "observation_count") != len(observations)
            or _count(value["return_count"], "return_count") != len(returns)
            or len(returns) != max(0, len(observations) - 1)):
        raise ValueError("daily risk counts differ from the complete saved series")
    count, reason = len(returns), value["unavailable_reason"]
    volatility, sharpe = value["annualized_volatility"], value["sharpe_ratio"]
    if ((count == 0) != (value["mean_daily_return"] is None)
            or (count < 2 and (reason != "INSUFFICIENT_DAILY_RETURNS" or volatility is not None or sharpe is not None))
            or (count >= 2 and reason == "INSUFFICIENT_DAILY_RETURNS")
            or (reason == "ZERO_VOLATILITY" and (volatility != 0 or sharpe is not None))
            or (reason is None and (volatility is None or volatility <= 0 or sharpe is None))):
        raise ValueError("daily risk availability differs from its counts and nullable statistics")
    if volatility is not None and volatility < 0:
        raise ValueError("annualized_volatility must be non-negative")
    clocks, days = [], []
    for item in observations:
        _record(item, DailyEquity, "daily observation")
        days.append(date.fromisoformat(item["trading_day"]))
        clocks.append(_time(item["timestamp"]))
        if _finite_number(item["equity"], "daily equity") <= 0:
            raise ValueError("daily equity must be positive")
    if clocks != sorted(set(clocks)) or days != sorted(set(days)):
        raise ValueError("daily observations must have unique increasing clocks and days")
    for index, item in enumerate(returns):
        _record(item, DailyReturn, "daily return")
        date.fromisoformat(item["start_day"])
        date.fromisoformat(item["end_day"])
        if _time(item["start_time"]) >= _time(item["end_time"]):
            raise ValueError("daily return clocks must increase")
        _finite_number(item["value"], "daily return")
        first, last = observations[index:index + 2]
        if (item["start_day"] != first["trading_day"] or item["end_day"] != last["trading_day"]
                or item["start_time"] != first["timestamp"] or item["end_time"] != last["timestamp"]):
            raise ValueError("daily returns must join consecutive saved observations")
    if (value["start_time"] != (observations[0]["timestamp"] if observations else None)
            or value["end_time"] != (observations[-1]["timestamp"] if observations else None)):
        raise ValueError("daily risk endpoints differ from saved observations")


def _validate_report(report, config, dataset_id, mode, versions):
    extras = {"equity", "risk"} if mode == "RISK" else {"equity"} if mode == "EQUITY" else set()
    _object(report, _REPORT_FIELDS | extras, "saved report")
    extended = any(type(item) is CompositeRuleStrategy for item in config["strategies"])
    if (report["status"] != "SUCCESS" or report["evaluation_scope"] != EVALUATION_SCOPE
            or report["result_schema_version"] != _cli_result_version(_MODES[mode], extended)
            or report["version"] != versions["comparison"] or report["engine_version"] != versions["backtest"]):
        raise ValueError("saved report mode, status or algorithm binding is invalid")
    for key in ("minimum_train_periods", "validation_periods", "step_periods"):
        _count(report[key], key)
    for key, value in _object(report["costs"], {"commission_bps", "slippage_bps"}, "costs").items():
        _finite_number(value, key)
    if (report["dataset_id"] != dataset_id or report["feature_names"] != list(config["feature_fields"])
            or report["return_label"] != config["return_label"]
            or any(report[key] != config[key] for key in
                   ("minimum_train_periods", "validation_periods", "step_periods"))
            or report["costs"] != {key: config[key] for key in ("commission_bps", "slippage_bps")}):
        raise ValueError("saved plan and report disagree on Dataset, Features, Label, windows or costs")
    for key in ("comparison_id", "walk_forward_id"):
        _identity(report[key], key)
    _count(report["held_out_test_sample_count"], "held_out_test_sample_count")
    keys = _array(report["validation_sample_keys"], "validation sample keys", nonempty=True)
    for key in keys:
        _identity(key, "validation sample key")
    if len(set(keys)) != len(keys):
        raise ValueError("validation sample keys must be unique")
    fold_keys, fold_indices = [], []
    for fold in _array(report["folds"], "folds", nonempty=True):
        _object(fold, {"fold_index", "fold_id", "validation_start_time", "validation_end_time",
                       "train_count", "purged_train_count", "validation_sample_keys"}, "fold")
        fold_indices.append(_count(fold["fold_index"], "fold_index"))
        _identity(fold["fold_id"], "fold_id")
        _count(fold["train_count"], "train_count")
        _count(fold["purged_train_count"], "purged_train_count")
        if _time(fold["validation_start_time"]) > _time(fold["validation_end_time"]):
            raise ValueError("fold clocks are reversed")
        fold_keys.extend(_array(fold["validation_sample_keys"], "fold sample keys", nonempty=True))
    if fold_keys != keys or fold_indices != sorted(set(fold_indices)):
        raise ValueError("folds must partition the ordered common validation samples")
    results = _array(report["results"], "results", nonempty=True)
    if len(results) != len(config["strategies"]):
        raise ValueError("saved plan and report strategy counts differ")
    result_ids = []
    for result, strategy in zip(results, config["strategies"], strict=True):
        _object(result, {"strategy", "result_id", "metrics", "trades"}, "strategy result")
        descriptor = _strategy_fields(strategy)
        if "model_version" in descriptor:
            descriptor["model_version"] = versions["ridge"]
        if "rule_version" in descriptor:
            descriptor["rule_version"] = versions["composite_rule"]
        if canonical_json(result["strategy"]) != canonical_json(descriptor):
            raise ValueError("saved strategy order or configuration differs from plan")
        rules = ([descriptor] if descriptor["kind"] == "FEATURE_RULE" else descriptor.get("conditions", []))
        if any(rule["signal_field"] not in config["feature_fields"] for rule in rules):
            raise ValueError("saved rule Feature lies outside the common projection")
        result_ids.append(_identity(result["result_id"], "result_id"))
        metrics = BacktestMetrics(**_record(result["metrics"], BacktestMetrics, "metrics"))
        trades = _array(result["trades"], "trades")
        if metrics.trade_count != len(trades) or metrics.candidate_count != len(keys):
            raise ValueError("saved trade/candidate counts differ from complete records")
        trade_keys = []
        for trade in trades:
            _record(trade, BacktestTrade, "trade")
            parsed = BacktestTrade(**{**trade, **{key: _time(trade[key]) for key in
                                                 ("signal_time", "entry_time", "exit_time")}})
            trade_keys.append(parsed.sample_key)
        if len(set(trade_keys)) != len(trade_keys) or not set(trade_keys).issubset(keys):
            raise ValueError("saved trades must refer to unique common validation samples")
    if len(set(result_ids)) != len(result_ids):
        raise ValueError("strategy result identities must be unique")
    if mode == "COMPARISON":
        return
    equity = _object(report["equity"], {"version", "equity_comparison_id", "interval", "start_time",
                                      "end_time", "price_evidence_id", "results"}, "equity report")
    if equity["version"] != versions["strategy_equity"]:
        raise ValueError("equity report algorithm version differs")
    for key in ("equity_comparison_id", "price_evidence_id"):
        _identity(equity[key], key)
    _string(equity["interval"], "interval")
    start, end = _time(equity["start_time"]), _time(equity["end_time"])
    if start >= end:
        raise ValueError("equity window must be positive")
    curves = _array(equity["results"], "equity results", nonempty=True)
    if any(type(item) is not dict for item in curves):
        raise ValueError("equity results must be objects")
    if [item.get("strategy_result_id") for item in curves] != result_ids:
        raise ValueError("equity result identities differ from comparison")
    for curve in curves:
        _validate_curve(curve, version=versions["equity"], start=start, end=end, strategy_result=True)
    if mode != "RISK":
        return
    risk = _object(report["risk"], {"version", "risk_report_id", "benchmark_definition", "sampling",
                                  "benchmark", "results"}, "risk report")
    if (risk["version"] != versions["strategy_risk"] or risk["benchmark_definition"] != BENCHMARK_DEFINITION
            or risk["sampling"] != "COMPLETE_RECORDED_SESSION_CLOSE_TO_CLOSE"):
        raise ValueError("risk report algorithm or sampling differs")
    _identity(risk["risk_report_id"], "risk_report_id")
    benchmark = _object(risk["benchmark"], {"curve", "total_return", "daily_risk"}, "benchmark")
    _finite_number(benchmark["total_return"], "benchmark return")
    _validate_curve(benchmark["curve"], version=versions["buy_and_hold"], start=start, end=end)
    _validate_daily_risk(benchmark["daily_risk"], versions["daily_risk"])
    risk_results = _array(risk["results"], "risk results", nonempty=True)
    if any(type(item) is not dict for item in risk_results):
        raise ValueError("risk results must be objects")
    if [item.get("strategy_result_id") for item in risk_results] != result_ids:
        raise ValueError("risk result identities differ from comparison")
    for result in risk_results:
        _record(result, StrategyRiskResult, "strategy risk result")
        for key in ("total_return", "return_difference", "bar_close_max_drawdown"):
            _finite_number(result[key], key)
        _validate_daily_risk(result["daily_risk"], versions["daily_risk"])


def _validate_root(root):
    _object(root, _ROOT_FIELDS, "experiment snapshot")
    if root["artifact_schema_version"] == "market-vault-intraday-experiment-v1":
        from .intraday_experiment import validate_intraday_experiment_root
        validate_intraday_experiment_root(root)
        return
    if root["artifact_schema_version"] == STRATEGY_EXPERIMENT_V2_VERSION:
        _validate_diagnostics_root(root)
        return
    if root["artifact_schema_version"] != STRATEGY_EXPERIMENT_VERSION:
        raise ValueError("unsupported experiment artifact_schema_version")
    if root["evaluation_mode"] not in _MODES:
        raise ValueError("unsupported experiment evaluation_mode")
    _identity(root["dataset_id"], "dataset_id")
    _identity(root["experiment_id"], "experiment_id")
    expected_id = sha256(canonical_json({k: v for k, v in root.items() if k != "experiment_id"})).hexdigest()
    if root["experiment_id"] != expected_id:
        raise ValueError("experiment content digest does not match experiment_id")
    config = parse_strategy_comparison_plan_bytes(canonical_json(root["plan"]))
    locator = config["dataset_build_dir"]
    if not (Path(locator).is_absolute() or PureWindowsPath(locator).is_absolute()):
        raise ValueError("saved Dataset locator must be absolute")
    if canonical_json(root["plan"]) != canonical_json(normalized_comparison_plan(config, dataset_build_dir=locator)):
        raise ValueError("saved plan must contain normalized explicit inputs")
    versions = _object(root["algorithm_versions"], algorithm_versions(config, root["evaluation_mode"]),
                       "algorithm versions")
    environment = _object(root["environment"], {"market_vault", "python", "pandas", "pyarrow"}, "environment")
    for key, value in {**versions, **environment}.items():
        _string(value, key)
    if type(root["name"]) is not str or type(root["notes"]) is not str:
        raise ValueError("experiment name and notes must be strings")
    _validate_report(root["report"], config, root["dataset_id"], root["evaluation_mode"], versions)


def _diagnostic_versions(plan: dict) -> dict[str, str]:
    from .strategy_diagnostics import STRATEGY_DIAGNOSTICS_VERSION, expand_strategy_diagnostics_plan
    _, children, _ = expand_strategy_diagnostics_plan(plan)
    config = parse_strategy_comparison_plan_bytes(canonical_json(children[0]))
    return {**algorithm_versions(config, "RISK"), "diagnostics": STRATEGY_DIAGNOSTICS_VERSION}


def _validate_diagnostics_root(root):
    from .strategy_diagnostics import (
        STRATEGY_DIAGNOSTICS_RESULT_VERSION, diagnostic_candidate_records,
        diagnostic_common_context, diagnostics_report_identity, expand_strategy_diagnostics_plan,
    )
    if root["evaluation_mode"] != "DIAGNOSTICS":
        raise ValueError("experiment-v2 requires DIAGNOSTICS evaluation_mode")
    _identity(root["dataset_id"], "dataset_id")
    _identity(root["experiment_id"], "experiment_id")
    if root["experiment_id"] != sha256(canonical_json(
        {key: value for key, value in root.items() if key != "experiment_id"},
    )).hexdigest():
        raise ValueError("experiment content digest does not match experiment_id")
    plan, children, values = expand_strategy_diagnostics_plan(root["plan"])
    if canonical_json(plan) != canonical_json(root["plan"]):
        raise ValueError("saved diagnostics plan must contain normalized explicit inputs")
    locator = plan["comparison_plan"]["dataset_build_dir"]
    if not (Path(locator).is_absolute() or PureWindowsPath(locator).is_absolute()):
        raise ValueError("saved Dataset locator must be absolute")
    versions = _object(root["algorithm_versions"], _diagnostic_versions(plan), "algorithm versions")
    environment = _object(root["environment"], {"market_vault", "python", "pandas", "pyarrow"}, "environment")
    for key, value in {**versions, **environment}.items():
        _string(value, key)
    if type(root["name"]) is not str or type(root["notes"]) is not str:
        raise ValueError("experiment name and notes must be strings")
    report = _object(root["report"], {
        "result_schema_version", "status", "version", "dataset_id", "evaluation_scope",
        "plan_sha256", "evaluation_count", "variant_count", "groups", "diagnostics_id",
    }, "diagnostics report")
    _identity(report["diagnostics_id"], "diagnostics_id")
    _identity(report["plan_sha256"], "plan_sha256")
    if (report["result_schema_version"] != STRATEGY_DIAGNOSTICS_RESULT_VERSION
            or report["status"] != "SUCCESS" or report["version"] != versions["diagnostics"]
            or report["evaluation_scope"] != EVALUATION_SCOPE
            or report["dataset_id"] != root["dataset_id"]
            or report["plan_sha256"] != sha256(canonical_json(plan)).hexdigest()
            or report["diagnostics_id"] != diagnostics_report_identity(report)):
        raise ValueError("diagnostics report identity, scope, plan or algorithm binding is invalid")
    if (_count(report["evaluation_count"], "evaluation_count") != len(children) * len(values)
            or _count(report["variant_count"], "variant_count") != len(values)):
        raise ValueError("diagnostics report must cover every parameter and cost combination")
    groups = _array(report["groups"], "diagnostics groups", nonempty=True)
    if len(groups) != len(children):
        raise ValueError("diagnostics cost group coverage differs from the plan")
    context = None
    for index, (group, child) in enumerate(zip(groups, children, strict=True)):
        _object(group, {"cost_index", "comparison_plan", "report", "candidates"}, "cost group")
        if (_count(group["cost_index"], "cost_index") != index
                or canonical_json(group["comparison_plan"]) != canonical_json(child)):
            raise ValueError("diagnostics cost order or expanded child plan differs")
        config = parse_strategy_comparison_plan_bytes(canonical_json(child))
        _validate_report(group["report"], config, root["dataset_id"], "RISK", versions)
        current = diagnostic_common_context(group["report"])
        if context is not None and context != current:
            raise ValueError("diagnostics cost groups must share the same Dataset, folds and prices")
        context = current
        expected = diagnostic_candidate_records(group["report"], values, groups[0]["report"])
        if canonical_json(group["candidates"]) != canonical_json(expected):
            raise ValueError("diagnostics candidate mapping, cost delta or fold contributions differ")


@dataclass(frozen=True, slots=True)
class StrategyExperiment:
    """Canonical immutable bytes; callers receive detached dictionaries only."""

    content: bytes

    def __post_init__(self):
        if type(self.content) is not bytes or self.content.startswith(codecs.BOM_UTF8):
            raise ValueError("experiment must be UTF-8 bytes without a BOM")
        try:
            root = json.loads(self.content.decode("utf-8"), object_pairs_hook=_no_duplicate_pairs)
            _validate_root(root)
        except (DatasetCLIError, BacktestCLIError) as exc:
            raise ValueError(f"invalid experiment JSON: {exc}") from exc
        object.__setattr__(self, "content", canonical_json(root))

    def as_dict(self) -> dict:
        return json.loads(self.content)

    @property
    def experiment_id(self) -> str:
        return self.as_dict()["experiment_id"]


def create_strategy_experiment(*, plan: dict, report: dict, mode: str,
                               name: str = "", notes: str = "") -> StrategyExperiment:
    config = parse_strategy_comparison_plan_bytes(canonical_json(plan))
    root = {"artifact_schema_version": STRATEGY_EXPERIMENT_VERSION,
            "dataset_id": report["dataset_id"], "evaluation_mode": mode,
            "plan": plan, "report": report, "algorithm_versions": algorithm_versions(config, mode),
            "environment": environment_versions(), "name": name, "notes": notes}
    root["experiment_id"] = sha256(canonical_json(root)).hexdigest()
    return StrategyExperiment(canonical_json(root))


def create_strategy_diagnostics_experiment(*, plan: dict, report: dict,
                                           name: str = "", notes: str = "") -> StrategyExperiment:
    from .strategy_diagnostics import normalize_strategy_diagnostics_plan
    normalized = normalize_strategy_diagnostics_plan(plan)
    root = {
        "artifact_schema_version": STRATEGY_EXPERIMENT_V2_VERSION,
        "dataset_id": report["dataset_id"], "evaluation_mode": "DIAGNOSTICS",
        "plan": normalized, "report": report, "algorithm_versions": _diagnostic_versions(normalized),
        "environment": environment_versions(), "name": name, "notes": notes,
    }
    root["experiment_id"] = sha256(canonical_json(root)).hexdigest()
    return StrategyExperiment(canonical_json(root))


def _explicit_path(path) -> Path:
    if not isinstance(path, (str, Path)) or not str(path):
        raise ValueError("experiment path must be an explicit str or Path")
    result = Path(path)
    return result if result.is_absolute() else Path.cwd() / result


def _read_file(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("experiment path must be a regular file, not a symlink")
    return path.read_bytes()


def load_strategy_experiment(path: str | Path) -> StrategyExperiment:
    """Read one named file; never load its Dataset or execute an algorithm."""
    return StrategyExperiment(_read_file(_explicit_path(path)))


@dataclass(frozen=True, slots=True)
class StrategyExperimentWriteResult:
    path: Path
    experiment_id: str
    content_sha256: str
    created_new_file: bool


def write_strategy_experiment(snapshot: StrategyExperiment, *, path: str | Path) -> StrategyExperimentWriteResult:
    """Exclusive creation, byte-identical reuse and strict readback; no replacement."""
    if type(snapshot) is not StrategyExperiment:
        raise ValueError("an immutable StrategyExperiment is required")
    file_path = _explicit_path(path)
    if file_path.parent.is_symlink() or not file_path.parent.is_dir():
        raise ValueError("experiment parent must be an existing regular directory")
    data = snapshot.content

    def reuse():
        existing = _read_file(file_path)
        parsed = StrategyExperiment(existing)
        if existing != data or parsed != snapshot:
            raise ValueError("existing experiment differs; choose a new file path")
        return StrategyExperimentWriteResult(file_path, snapshot.experiment_id, sha256(data).hexdigest(), False)

    if file_path.exists() or file_path.is_symlink():
        return reuse()
    try:
        with file_path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        return reuse()
    readback = _read_file(file_path)
    if readback != data or StrategyExperiment(readback) != snapshot:
        raise ValueError("experiment readback differs from the requested snapshot")
    return StrategyExperimentWriteResult(file_path, snapshot.experiment_id, sha256(data).hexdigest(), True)


def replay_strategy_experiment(snapshot: StrategyExperiment, *, dataset_build_dir: str | Path | None = None,
                               intraday_data_file: str | Path | None = None) -> dict:
    """Verify versions and Dataset identity before fitting, then compare every raw value."""
    if type(snapshot) is not StrategyExperiment:
        raise ValueError("an immutable StrategyExperiment is required")
    root = snapshot.as_dict()
    if root["artifact_schema_version"] == "market-vault-intraday-experiment-v1":
        if dataset_build_dir is not None:
            raise ValueError("intraday replay requires intraday_data_file, not a Dataset directory")
        from .intraday_experiment import replay_intraday_experiment
        return replay_intraday_experiment(snapshot, intraday_data_file=intraday_data_file)
    if intraday_data_file is not None:
        raise ValueError("intraday_data_file applies only to an intraday experiment")
    diagnostics = root["evaluation_mode"] == "DIAGNOSTICS"
    config = parse_strategy_comparison_plan_bytes(canonical_json(
        root["plan"]["comparison_plan"] if diagnostics else root["plan"],
    ))
    current_versions = (_diagnostic_versions(root["plan"]) if diagnostics
                        else algorithm_versions(config, root["evaluation_mode"]))
    if root["algorithm_versions"] != current_versions:
        raise ValueError("recorded algorithm versions differ; experiment cannot be replayed by this implementation")
    recorded_path = config.pop("dataset_build_dir")
    path = _resolve_plan_path(str(dataset_build_dir) if dataset_build_dir is not None else recorded_path,
                              base=Path.cwd(), label="Replay Research Dataset build")
    from ..cross_day_dataset import load_verified_multi_source_cross_day_dataset
    dataset = load_verified_multi_source_cross_day_dataset(path)
    if dataset.dataset_id != root["dataset_id"]:
        raise ValueError("replay Dataset ID differs from the saved experiment; no strategy was fitted")
    if diagnostics:
        from .strategy_diagnostics import run_strategy_diagnostics
        actual = run_strategy_diagnostics(dataset, plan=root["plan"])
    else:
        actual = evaluate_comparison_payload(dataset, config, root["evaluation_mode"])
    expected_bytes, actual_bytes = canonical_json(root["report"]), canonical_json(actual)
    expected_digest, actual_digest = sha256(expected_bytes).hexdigest(), sha256(actual_bytes).hexdigest()
    if actual_bytes != expected_bytes:
        raise ValueError(f"replay complete report mismatch: expected {expected_digest}, actual {actual_digest}")
    identity = "diagnostics_id" if diagnostics else "comparison_id"
    return {"experiment_id": snapshot.experiment_id, "dataset_id": dataset.dataset_id,
            identity: actual[identity], "report_matches": True,
            "expected_report_sha256": expected_digest, "actual_report_sha256": actual_digest}
