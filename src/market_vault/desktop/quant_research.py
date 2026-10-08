"""Functional Quant Research / Backtest controller for the QML desktop.

The desktop is a presentation layer over the already-validated v0.9 research
authorities. This module does not implement Feature calculations or Backtest
math. Workers verify explicit local data and call the versioned research and
execution adapters, including the independent intraday V2 path.

Business imports stay inside worker functions so normal desktop startup remains
lazy and does not initialize research/storage authorities merely by showing the
navigation shell.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import math
import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot

from market_vault.desktop.controllers import NetworkController
from market_vault.desktop.table_model import QtTableModel


TRADE_PAGE_SIZE = 100
MAX_FEATURE_ROWS = 1000
_SPLITS = ("TRAIN", "VALIDATION", "TEST")
_COMPARATORS = ("GT", "GE", "LT", "LE")
_EXECUTION_SAFE_RETURN_REF = (
    "market_vault.dataset.label_transforms.forward_open_to_close_return:"
    "forward_open_to_close_return"
)


@dataclass(frozen=True, slots=True)
class _DatasetView:
    path: str
    summary: dict[str, str]
    feature_names: tuple[str, ...]
    label_names: tuple[str, ...]
    return_label_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _FeatureResearchView:
    summary: dict[str, str]
    page: Any


@dataclass(frozen=True, slots=True)
class _BacktestView:
    summary: dict[str, str]
    trade_rows: tuple[tuple[str, ...], ...]
    equity_series: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class _ComparisonEquityView:
    name: str
    rows: tuple[tuple[str, ...], ...]
    series: tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class _ComparisonView:
    summary: dict[str, str]
    page: Any
    equity: tuple[_ComparisonEquityView, ...] = ()
    risk_page: Any = None
    benchmark_series: tuple[tuple[float, float], ...] = ()
    experiment: bytes = b""
    diagnostics: _DiagnosticsView | None = None


@dataclass(frozen=True, slots=True)
class _DiagnosticsView:
    summary: dict[str, str]
    page: Any
    labels: tuple[str, ...]
    positions: tuple[tuple[int, int], ...]
    groups: tuple[_ComparisonView, ...]
    fold_rows: tuple[tuple[tuple[str, ...], ...], ...]


def _finite_float(value: Any, field_name: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite number")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} must be a finite number") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{field_name} must be a finite number")
    if nonnegative and parsed < 0.0:
        raise ValueError(f"{field_name} must be non-negative")
    return 0.0 if parsed == 0.0 else parsed


def _bounded_int(value: Any, field_name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if not math.isfinite(numeric) or not numeric.is_integer():
        raise ValueError(f"{field_name} must be an integer")
    parsed = int(numeric)
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{field_name} must be between {minimum} and {maximum}")
    return parsed


def _dataset_directory(value: str) -> Path:
    text = str(value).strip()
    if not text:
        raise ValueError("Research Dataset directory is required.")
    direct_path = Path(text).expanduser()
    if direct_path.is_absolute():
        path = direct_path
    else:
        url = QUrl(text)
        if url.scheme():
            if not url.isLocalFile():
                raise ValueError("Research Dataset directory must be a local path.")
            path = Path(url.toLocalFile()).expanduser()
        else:
            path = direct_path
    if not path.is_absolute():
        raise ValueError("Research Dataset directory must be an absolute local path.")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError(f"Research Dataset directory does not exist: {resolved}")
    return resolved


def _load_verified_dataset(path: Path):
    from market_vault.cross_day_dataset import (
        load_verified_multi_source_cross_day_dataset,
    )
    return load_verified_multi_source_cross_day_dataset(path)


def _table_page(
    columns: tuple[str, ...],
    rows: tuple[tuple[str, ...], ...],
    *,
    page: int = 1,
    page_size: int | None = None,
):
    from market_vault.console.models import TablePage
    size = page_size or max(1, min(1000, len(rows) or 1))
    return TablePage(
        columns=columns,
        rows=rows,
        page=page,
        page_size=size,
        total_rows=len(rows),
    )


def _format_number(value: float | int | None, digits: int = 6) -> str:
    if value is None:
        return "—"
    return f"{float(value):.{digits}g}"


def _format_percent(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{float(value) * 100.0:.2f}%"


def _feature_and_label_names(dataset) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    schema_types = {field.name: field.logical_type for field in dataset.schema.fields}
    ts2 = tuple(spec.name for spec in dataset.ts2_features.feature_specs)
    observation = tuple(
        spec.name for spec in dataset.identity_input.observation_feature_specs
    )
    ordered_features = ts2 + observation
    if len(ordered_features) != len(set(ordered_features)):
        raise ValueError("Research Dataset contains duplicate Feature names.")
    feature_names = tuple(
        name for name in ordered_features
        if schema_types.get(name) in ("float64", "int64")
    )
    specs = tuple(dataset.cross_day_labels.label_specs)
    labels = tuple(
        spec.name for spec in specs
        if schema_types.get(spec.name) in ("float64", "int64")
    )
    return_labels = tuple(
        spec.name
        for spec in specs
        if (
            spec.transform_ref == _EXECUTION_SAFE_RETURN_REF
            and spec.output.logical_type == "float64"
            and spec.input_canonical_fields == ("open", "close")
        )
    )
    return feature_names, labels, return_labels


def _split_counts(dataset) -> dict[str, int]:
    fields = tuple(field.name for field in dataset.schema.fields)
    index = {name: position for position, name in enumerate(fields)}
    if "assignment_status" not in index or "final_split" not in index:
        return {split: 0 for split in _SPLITS}
    counts = {split: 0 for split in _SPLITS}
    for row in dataset.rows:
        if row[index["assignment_status"]] != "ASSIGNED":
            continue
        split = row[index["final_split"]]
        if split in counts:
            counts[split] += 1
    return counts


def _inspect_dataset(path: Path) -> _DatasetView:
    dataset = _load_verified_dataset(path)
    features, labels, return_labels = _feature_and_label_names(dataset)
    counts = _split_counts(dataset)
    symbols = tuple(str(item) for item in dataset.scope.symbols)
    summary = {
        "dataset_id": dataset.dataset_id,
        "symbols": ", ".join(symbols),
        "rows": str(len(dataset.rows)),
        "features": str(len(features)),
        "labels": str(len(labels)),
        "train_rows": str(counts["TRAIN"]),
        "validation_rows": str(counts["VALIDATION"]),
        "test_rows": str(counts["TEST"]),
        "artifact_status": str(dataset.status),
    }
    return _DatasetView(
        str(Path(dataset.build_path).resolve()),
        summary,
        features,
        labels,
        return_labels,
    )


def _run_feature_research(
    path: Path,
    *,
    label_field: str,
    split: str,
    quantile_count: int,
) -> _FeatureResearchView:
    from market_vault.research import analyze_features, build_ml_dataset

    dataset = _load_verified_dataset(path)
    features, labels, _ = _feature_and_label_names(dataset)
    if label_field not in labels:
        raise ValueError("Selected Label is not an admitted numeric Dataset Label.")
    bundle = build_ml_dataset(dataset, label_field=label_field, feature_fields=features)
    report = analyze_features(
        bundle,
        split=split,
        feature_names=features,
        quantile_count=quantile_count,
    )
    rows = tuple(
        (
            metric.feature_name,
            str(metric.sample_count),
            _format_number(metric.pearson_ic),
            _format_number(metric.rank_ic),
            _format_number(metric.top_bottom_spread),
            _format_number(metric.feature_mean),
            _format_number(metric.feature_std),
        )
        for metric in report.metrics[:MAX_FEATURE_ROWS]
    )
    ranked = tuple(metric for metric in report.metrics if metric.rank_ic is not None)
    best = max(ranked, key=lambda item: abs(float(item.rank_ic))) if ranked else None
    summary = {
        "split": report.split,
        "label": report.label_name,
        "feature_count": str(len(report.metrics)),
        "sample_count": str(report.metrics[0].sample_count if report.metrics else 0),
        "best_feature": best.feature_name if best is not None else "—",
        "best_rank_ic": _format_number(best.rank_ic if best is not None else None),
        "quantiles": str(report.quantile_count),
    }
    return _FeatureResearchView(
        summary,
        _table_page(
            (
                "feature_name",
                "sample_count",
                "pearson_ic",
                "rank_ic",
                "top_bottom_spread",
                "feature_mean",
                "feature_std",
            ),
            rows,
        ),
    )


def _run_backtest(
    path: Path,
    *,
    signal_field: str,
    comparator: str,
    threshold: float,
    return_label: str,
    split: str,
    commission_bps: float,
    slippage_bps: float,
) -> _BacktestView:
    from market_vault.backtest import run_backtest

    dataset = _load_verified_dataset(path)
    result = run_backtest(
        dataset,
        signal_field=signal_field,
        comparator=comparator,
        threshold=threshold,
        return_label=return_label,
        split=split,
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
    )
    metrics = result.metrics
    summary = {
        "backtest_id": result.backtest_id,
        "split": result.split,
        "trade_count": str(metrics.trade_count),
        "signal_count": str(metrics.signal_count),
        "total_return": _format_percent(metrics.total_return),
        "max_drawdown": _format_percent(metrics.realized_max_drawdown),
        "win_rate": _format_percent(metrics.win_rate),
        "avg_trade_return": _format_percent(metrics.average_trade_return),
        "profit_factor": _format_number(metrics.profit_factor),
        "exposure": _format_percent(metrics.exposure),
    }
    rows = tuple(
        (
            trade.code,
            trade.signal_time.isoformat(),
            trade.entry_time.isoformat(),
            trade.exit_time.isoformat(),
            _format_number(trade.signal_value),
            _format_percent(trade.gross_return),
            _format_percent(trade.net_return),
            _format_number(trade.equity_after),
        )
        for trade in result.trades
    )
    equity = (1.0,) + tuple(float(trade.equity_after) for trade in result.trades)
    return _BacktestView(summary, rows, equity)


def _run_strategy_comparison(path: Path, **values) -> _ComparisonView:
    from market_vault.backtest import BacktestRule
    from market_vault.research.strategy_comparison import (
        FeatureRuleStrategy, RidgeStrategy,
    )

    with_risk = values.pop("risk_report", False)
    with_equity = values.pop("equity_curve", False) or with_risk
    if "strategies" in values:
        configuration = dict(values)
    else:
        # Preserve the original controller/worker interface for existing callers.
        trend = values.pop("trend_feature")
        reversion = values.pop("reversion_feature")
        strategies = (
            FeatureRuleStrategy("Trend", BacktestRule(trend, "GT", values.pop("trend_threshold"))),
            FeatureRuleStrategy("MeanReversion", BacktestRule(reversion, "LT", values.pop("reversion_threshold"))),
            RidgeStrategy("Ridge", values.pop("ridge_alpha"), values.pop("ridge_threshold")),
        )
        configuration = dict(
            feature_fields=tuple(dict.fromkeys((trend, reversion))), strategies=strategies, **values,
        )
    from market_vault.strategy_comparison_io import evaluate_comparison_payload, normalized_comparison_plan
    from market_vault.research.strategy_experiment import create_strategy_experiment

    dataset = _load_verified_dataset(path)
    mode = "RISK" if with_risk else "EQUITY" if with_equity else "COMPARISON"
    payload = evaluate_comparison_payload(dataset, configuration, mode)
    snapshot = create_strategy_experiment(
        plan=normalized_comparison_plan(configuration, dataset_build_dir=str(path.resolve())),
        report=payload, mode=mode,
    )
    return _comparison_payload_view(payload, experiment=snapshot.content)


def _comparison_payload_view(payload: dict, *, experiment: bytes = b"") -> _ComparisonView:
    """Pure presentation shared by computed and reopened complete raw reports."""
    results = payload["results"]
    rows = tuple((
        result["strategy"]["name"], str(result["metrics"]["trade_count"]),
        _format_percent(result["metrics"]["total_return"]),
        _format_percent(result["metrics"]["gross_total_return"]),
        _format_percent(result["metrics"]["realized_max_drawdown"]),
        _format_percent(result["metrics"]["win_rate"]),
        _format_number(result["metrics"]["profit_factor"]),
        str(result["metrics"]["overlap_skipped_count"]),
        _format_percent(result["metrics"]["exposure"]),
    ) for result in results)
    summary = {
        "comparison_id": payload["comparison_id"], "fold_count": str(len(payload["folds"])),
        "common_validation_rows": str(len(payload["validation_sample_keys"])),
        "held_out_test_rows": str(payload["held_out_test_sample_count"]),
    }
    equity_views = ()
    equity = payload.get("equity")
    if equity is not None:
        summary["equity_comparison_id"] = equity["equity_comparison_id"]
        rows = tuple(row + (_format_percent(curve["bar_close_max_drawdown"]),)
                     for row, curve in zip(rows, equity["results"], strict=True))
        equity_views = tuple(_comparison_curve_view(result["strategy"]["name"], curve)
                             for result, curve in zip(results, equity["results"], strict=True))
    risk_page, benchmark_series = None, ()
    risk = payload.get("risk")
    if risk is not None:
        summary["risk_report_id"] = risk["risk_report_id"]
        benchmark = risk["benchmark"]
        benchmark_view = _comparison_curve_view("Buy & Hold", benchmark["curve"])
        equity_views += (benchmark_view,)
        benchmark_series = benchmark_view.series
        risk_rows = tuple(_risk_row(
            result["strategy"]["name"], value["total_return"], value["return_difference"],
            value["bar_close_max_drawdown"], value["daily_risk"],
        ) for result, value in zip(results, risk["results"], strict=True))
        risk_rows += (_risk_row("Buy & Hold", benchmark["total_return"], 0.0,
                               benchmark["curve"]["bar_close_max_drawdown"], benchmark["daily_risk"]),)
        risk_page = _comparison_risk_page(risk_rows)
    return _ComparisonView(summary, _comparison_page(rows, with_equity=equity is not None),
                           equity_views, risk_page, benchmark_series, experiment)


def _run_strategy_diagnostics(path: Path, *, plan: dict) -> _ComparisonView:
    from market_vault.research.strategy_diagnostics import run_strategy_diagnostics
    from market_vault.research.strategy_experiment import create_strategy_diagnostics_experiment

    dataset = _load_verified_dataset(path)
    report = run_strategy_diagnostics(dataset, plan=plan)
    snapshot = create_strategy_diagnostics_experiment(plan=plan, report=report)
    return _diagnostics_payload_view(report, plan=plan, experiment=snapshot.content)


def _diagnostics_page(rows):
    return _table_page(("diagnostic_candidate", "parameters", "commission_bps", "slippage_bps",
                        "total_return", "return_change_from_first_cost", "trade_count",
                        "bar_close_max_drawdown", "annualized_volatility", "sharpe_ratio"), rows)


def _fold_contribution_page(rows, *, page=1):
    from market_vault.console.models import TablePage
    pages = max(1, (len(rows) + TRADE_PAGE_SIZE - 1) // TRADE_PAGE_SIZE)
    page = max(1, min(page, pages))
    offset = (page - 1) * TRADE_PAGE_SIZE
    return TablePage(columns=("fold_index", "validation_start_time", "validation_end_time",
                              "validation_sample_count", "trade_count", "cash_contribution"),
                     rows=rows[offset:offset + TRADE_PAGE_SIZE], page=page,
                     page_size=TRADE_PAGE_SIZE, total_rows=len(rows))


def _diagnostics_payload_view(payload: dict, *, plan: dict, experiment: bytes = b"") -> _ComparisonView:
    """Present every candidate; selecting a group never substitutes its child report for the bundle."""
    groups, rows, labels, positions, fold_rows = [], [], [], [], []
    for group in payload["groups"]:
        report = group["report"]
        groups.append(_comparison_payload_view(report))
        costs = group["comparison_plan"]
        commission, slippage = str(costs["commission_bps"]), str(costs["slippage_bps"])
        for candidate, result, risk in zip(group["candidates"], report["results"],
                                            report["risk"]["results"], strict=True):
            parameters = ", ".join(
                (f"condition {axis['condition_index'] + 1}" if axis["parameter"] == "condition_threshold"
                 else axis["parameter"]) + "=" + str(value)
                for axis, value in zip(plan["parameter_axes"], candidate["axis_values"], strict=True)
            ) or "—"
            number = str(len(labels) + 1)
            labels.append(f"{number}: {parameters} · {commission}/{slippage} bps")
            positions.append((group["cost_index"], candidate["variant_index"]))
            rows.append((number, parameters, commission, slippage,
                         _format_percent(result["metrics"]["total_return"]),
                         _format_percent(candidate["return_change_from_first_cost"]),
                         str(result["metrics"]["trade_count"]),
                         _format_percent(risk["bar_close_max_drawdown"]),
                         _format_percent(risk["daily_risk"]["annualized_volatility"]),
                         _format_number(risk["daily_risk"]["sharpe_ratio"])))
            fold_rows.append(tuple((
                str(fold["fold_index"] + 1),
                datetime.fromisoformat(fold["validation_start_time"]).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                datetime.fromisoformat(fold["validation_end_time"]).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                str(fold["validation_sample_count"]), str(fold["trade_count"]),
                _format_number(fold["cash_contribution"], 12),
            ) for fold in candidate["fold_contributions"]))
    diagnostics = _DiagnosticsView({
        "evaluation_count": str(payload["evaluation_count"]),
        "variant_count": str(payload["variant_count"]),
        "cost_scenario_count": str(len(groups)),
    }, _diagnostics_page(tuple(rows)), tuple(labels), tuple(positions), tuple(groups), tuple(fold_rows))
    return replace(groups[0], experiment=experiment, diagnostics=diagnostics)


def _experiment_payload_view(snapshot) -> _ComparisonView:
    root = snapshot.as_dict()
    if root["evaluation_mode"] == "DIAGNOSTICS":
        return _diagnostics_payload_view(root["report"], plan=root["plan"], experiment=snapshot.content)
    return _comparison_payload_view(root["report"], experiment=snapshot.content)


def _comparison_curve_view(name, curve):
    return _ComparisonEquityView(name, tuple((
        datetime.fromisoformat(point["timestamp"]).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        _format_number(point["equity"]), _format_percent(point["drawdown"]),
        _format_number(point["cash"]), _format_number(point["quantity"]),
        _format_number(point["mark_price"]), _format_number(point["market_value"]),
        _format_number(point["transaction_cost"]), point["event"],
    ) for point in curve["points"]), tuple((datetime.fromisoformat(point["timestamp"]).timestamp() * 1000, point["equity"])
                                          for point in curve["points"]))


def _risk_row(name, total, difference, drawdown, risk):
    status = {None: "OK", "INSUFFICIENT_DAILY_RETURNS": "n < 2", "ZERO_VOLATILITY": "σ = 0"}
    return (name, _format_percent(total), _format_percent(difference), _format_percent(drawdown),
            _format_percent(risk["annualized_volatility"]), _format_number(risk["sharpe_ratio"]),
            str(risk["return_count"]), status[risk["unavailable_reason"]])


def _comparison_risk_page(rows):
    return _table_page(("strategy", "total_return", "return_difference", "bar_close_max_drawdown",
                        "annualized_volatility", "sharpe_ratio", "daily_return_count", "risk_status"), rows)


def _comparison_page(rows, *, with_equity=False):
    return _table_page((
        "strategy", "trade_count", "total_return", "gross_total_return",
        "realized_max_drawdown", "win_rate", "profit_factor",
        "overlap_skipped_count", "exposure",
    ) + (("bar_close_max_drawdown",) if with_equity else ()), rows)


def _parse_comparison_strategies(values, admitted_features):
    from market_vault.research.strategy_config import parse_strategy_specs, strategy_plan_fields

    fields = values.get("feature_fields")
    if type(fields) not in (tuple, list) or not fields:
        raise ValueError("Select an explicit common Feature projection.")
    if any(type(field) is not str or field not in admitted_features for field in fields):
        raise ValueError("Common Features must be admitted numeric Dataset Features.")
    if len(set(fields)) != len(fields):
        raise ValueError("Common Features must be unique.")
    raw = values.get("strategies")
    if type(raw) is not list:
        raise ValueError("strategies must be a list")
    specs = []
    for item in raw:
        if type(item) is not dict:
            raise ValueError("strategy must be an object")
        item = dict(item)
        for key in ("alpha", "threshold"):
            if key in item:
                item[key] = _finite_float(item[key], key)
        if "conditions" in item:
            if type(item["conditions"]) is not list:
                raise ValueError("conditions must be a list")
            conditions = []
            for condition in item["conditions"]:
                if type(condition) is not dict:
                    raise ValueError("condition must be an object")
                condition = dict(condition)
                condition["threshold"] = _finite_float(condition.get("threshold"), "condition threshold")
                conditions.append(condition)
            item["conditions"] = conditions
        specs.append(item)
    strategies = parse_strategy_specs(specs)
    for strategy in strategies:
        spec = strategy_plan_fields(strategy)
        rules = ([spec] if spec["kind"] == "FEATURE_RULE" else spec.get("conditions", []))
        if any(rule["signal_field"] not in fields for rule in rules):
            raise ValueError("Every rule Feature must belong to the common projection.")
    return {"feature_fields": tuple(fields), "strategies": strategies}


def _parse_comparison_windows(values, admitted_labels):
    parsed = {}
    for field in ("minimum_train_periods", "validation_periods", "step_periods"):
        parsed[field] = _bounded_int(values.get(field), field, 1, 1_000_000)
    if parsed["step_periods"] < parsed["validation_periods"]:
        raise ValueError("step_periods must be at least validation_periods")
    for field in ("commission_bps", "slippage_bps"):
        parsed[field] = _finite_float(values.get(field, 0), field, nonnegative=True)
    if parsed["commission_bps"] + parsed["slippage_bps"] >= 10_000:
        raise ValueError("per-side costs must be below 10000 bps")
    parsed["return_label"] = str(values.get("return_label", "")).strip()
    if parsed["return_label"] not in admitted_labels:
        raise ValueError("Select an execution-safe forward-open-to-close return Label.")
    return parsed


def _parse_diagnostics_input(values, *, path, admitted_features, admitted_labels):
    from market_vault.research.strategy_diagnostics import (
        STRATEGY_DIAGNOSTICS_PLAN_VERSION, normalize_strategy_diagnostics_plan,
    )
    from market_vault.strategy_comparison_io import normalized_comparison_plan

    if type(values) is not dict or set(values) != {
        "comparison", "strategy_name", "parameter_axes", "cost_scenarios",
    }:
        raise ValueError("Diagnostics require comparison, strategy_name, parameter_axes and cost_scenarios.")
    comparison = values["comparison"]
    if type(comparison) is not dict:
        raise ValueError("comparison must be an object")
    config = {**_parse_comparison_strategies(comparison, admitted_features),
              **_parse_comparison_windows(comparison, admitted_labels)}
    if type(values["parameter_axes"]) is not list:
        raise ValueError("parameter_axes must be a list")
    axes = []
    for raw in values["parameter_axes"]:
        if type(raw) is not dict:
            raise ValueError("Each parameter axis must be an object")
        axis = dict(raw)
        if type(axis.get("values")) is str:
            axis["values"] = [_finite_float(item.strip(), "axis value") for item in axis["values"].split(",")]
        axes.append(axis)
    costs = values["cost_scenarios"]
    if type(costs) is str:
        pairs = [item.split("/") for item in costs.split(",")]
        if any(len(pair) != 2 for pair in pairs):
            raise ValueError("Costs use commission/slippage pairs separated by commas.")
        costs = [{"commission_bps": _finite_float(pair[0].strip(), "commission_bps"),
                  "slippage_bps": _finite_float(pair[1].strip(), "slippage_bps")} for pair in pairs]
    return normalize_strategy_diagnostics_plan({
        "plan_schema_version": STRATEGY_DIAGNOSTICS_PLAN_VERSION,
        "comparison_plan": normalized_comparison_plan(config, dataset_build_dir=str(path)),
        "strategy_name": values["strategy_name"], "parameter_axes": axes, "cost_scenarios": costs,
    })


def _experiment_file_path(raw_path: str) -> Path:
    text = str(raw_path).strip()
    if not text:
        raise ValueError("An experiment file path is required.")
    path = Path(text).expanduser()
    if not path.is_absolute():
        url = QUrl(text)
        if not url.isLocalFile():
            raise ValueError("Experiment file must be an absolute local path.")
        path = Path(url.toLocalFile()).expanduser()
    if not path.is_absolute():
        raise ValueError("Experiment file must be an absolute local path.")
    return path


class QuantResearchController(NetworkController):
    """Build, inspect, research, and backtest verified local Research Datasets."""

    researchChanged = Signal()
    datasetBuilt = Signal()
    _NETWORK_METHODS = {
        **NetworkController._NETWORK_METHODS,
        "research_backfill_execute": "execute_research_backfill",
    }

    def __init__(self, runtime, *, parent: QObject | None = None) -> None:
        super().__init__(runtime, parent=parent)
        self._dataset_path = ""
        self._intraday_path = ""
        self._intraday_data = b""
        self._intraday_feature_names: tuple[str, ...] = ()
        self._intraday_summary: dict[str, str] = {}
        self._intraday_preview_summary: dict[str, str] = {}
        self._intraday_rows: tuple[tuple[str, ...], ...] = ()
        self._intraday_columns: tuple[str, ...] = ()
        self._intraday_page = 1
        self._intraday_model = QtTableModel(parent=self)
        self._intraday_preview_model = QtTableModel(parent=self)
        self._intraday_model.set_page(_table_page((), ()))
        self._intraday_preview_model.set_page(_table_page((), ()))
        self._intraday_backtest_summary: dict[str, str] = {}
        self._intraday_backtest_data_id = ""
        self._intraday_backtest_tables: tuple = ()
        self._intraday_backtest_view = 0
        self._intraday_backtest_page = 1
        self._intraday_backtest_model = QtTableModel(parent=self)
        self._intraday_backtest_model.set_page(_table_page((), ()))
        self._dataset_summary: dict[str, str] = {}
        self._builder_summary: dict[str, str] = {}
        self._builder_values: dict[str, Any] = {}
        self._feature_summary: dict[str, str] = {}
        self._backtest_summary: dict[str, str] = {}
        self._comparison_summary: dict[str, str] = {}
        self._comparison_experiment = b""
        self._comparison_experiment_info: dict[str, Any] = {}
        self._comparison_plan_json = "{}"
        self._comparison_opened = False
        self._comparison_restore_revision = 0
        self._diagnostics_view: _DiagnosticsView | None = None
        self._diagnostic_index = 0
        self._diagnostics_plan_json = "{}"
        self._comparison_diagnostics_model = QtTableModel(parent=self)
        self._comparison_diagnostics_model.set_page(_diagnostics_page(()))
        self._comparison_fold_model = QtTableModel(parent=self)
        self._comparison_fold_model.set_page(_fold_contribution_page(()))
        self._feature_names: tuple[str, ...] = ()
        self._label_names: tuple[str, ...] = ()
        self._return_label_names: tuple[str, ...] = ()
        self._builder_model = QtTableModel(parent=self)
        self._feature_model = QtTableModel(parent=self)
        self._trade_model = QtTableModel(parent=self)
        self._comparison_model = QtTableModel(parent=self)
        self._comparison_model.set_page(_comparison_page(()))
        self._comparison_risk_model = QtTableModel(parent=self)
        self._comparison_risk_model.set_page(_comparison_risk_page(()))
        self._comparison_benchmark_series: tuple[tuple[float, float], ...] = ()
        self._comparison_equity: tuple[_ComparisonEquityView, ...] = ()
        self._comparison_equity_index = 0
        self._comparison_equity_model = QtTableModel(parent=self)
        self._set_comparison_equity_page(1)
        self._trade_rows: tuple[tuple[str, ...], ...] = ()
        self._equity_series: tuple[float, ...] = ()
        self._builder_model.set_page(
            _table_page(
                ("trade_date", "calendar_profile", "research_data", "role"),
                (),
            )
        )
        self._set_feature_page(())
        self._set_trade_page(1)

    @Property(str, notify=researchChanged)
    def intradayPath(self) -> str:
        return self._intraday_path

    @Property(bool, notify=researchChanged)
    def intradayLoaded(self) -> bool:
        return bool(self._intraday_data)

    @Property("QStringList", notify=researchChanged)
    def intradayFeatureNames(self) -> list[str]:
        return list(self._intraday_feature_names)

    @Property("QVariantMap", notify=researchChanged)
    def intradayBacktestSummary(self) -> dict:
        return dict(self._intraday_backtest_summary)

    @Property(str, notify=researchChanged)
    def intradayBacktestDataId(self) -> str:
        return self._intraday_backtest_data_id

    @Property(int, notify=researchChanged)
    def intradayBacktestView(self) -> int:
        return self._intraday_backtest_view

    @Property(QObject, constant=True)
    def intradayBacktestModel(self) -> QObject:
        return self._intraday_backtest_model

    def _set_intraday_backtest_page(self) -> None:
        from ..console.models import TablePage
        columns, rows = self._intraday_backtest_tables[self._intraday_backtest_view] if self._intraday_backtest_tables else ((), ())
        start = (self._intraday_backtest_page - 1) * TRADE_PAGE_SIZE
        self._intraday_backtest_model.set_page(TablePage(columns, rows[start:start + TRADE_PAGE_SIZE],
            self._intraday_backtest_page, TRADE_PAGE_SIZE, len(rows)))

    @Slot(int, result=bool)
    def selectIntradayBacktestView(self, index: int) -> bool:
        if index not in (0, 1, 2):
            return False
        self._intraday_backtest_view, self._intraday_backtest_page = index, 1
        self._set_intraday_backtest_page()
        self.researchChanged.emit()
        return True

    @Slot(int, result=bool)
    def changeIntradayBacktestPage(self, offset: int) -> bool:
        count = self._intraday_backtest_model.totalRows
        page = self._intraday_backtest_page + offset
        if not 1 <= page <= max(1, (count + TRADE_PAGE_SIZE - 1) // TRADE_PAGE_SIZE):
            return False
        self._intraday_backtest_page = page
        self._set_intraday_backtest_page()
        return True

    def _intraday_execution_values(self, values: dict) -> dict:
        defaults = {"entry_delay_minutes": 15, "stop_new_minutes": 30, "flatten_minutes": 5, "max_hold_bars": 12}
        return {**{name: _finite_float(values.get(name), name, nonnegative=True)
                   for name in ("commission_bps", "slippage_bps")},
                **{name: _bounded_int(values.get(name, default), name, 0 if name == "entry_delay_minutes" else 1, 2**31 - 1)
                   for name, default in defaults.items()}}

    def _apply_intraday_backtest(self, result: dict) -> None:
        execution = result["execution"]
        columns_by_view = (
            ("entry_time", "exit_time", "exit_reason", "held_bars", "quantity", "entry_fill_price", "exit_fill_price",
             "cash_before", "cash_after", "net_return", "commission_total", "slippage_total"),
            ("timestamp", "phase", "action", "reason", "slot", "mark_price", "cash", "quantity", "equity", "drawdown"),
            ("trading_day", "cash_open", "cash_close", "return", "trade_count"),
        )
        self._intraday_backtest_tables = tuple((columns, tuple(tuple(
            _format_number(row[name]) if type(row[name]) in (float, int) else str(row[name])
            for name in columns) for row in execution[key]))
            for columns, key in zip(columns_by_view, ("trades", "ledger", "daily")))
        metrics = execution["metrics"]
        self._intraday_backtest_summary = {
            "trade_count": str(metrics["trade_count"]), "final_cash": _format_number(metrics["final_cash"]),
            "total_return": _format_percent(metrics["total_return"]),
            "observed_max_drawdown": _format_percent(metrics["observed_max_drawdown"]),
        }
        self._intraday_backtest_data_id = result["data_id"]
        self._intraday_backtest_page = 1
        self._set_intraday_backtest_page()
        self.researchChanged.emit()

    @Slot("QVariantMap", result=bool)
    def runIntradayBacktest(self, values: dict) -> bool:
        try:
            if not self._intraday_data:
                raise ValueError("Open verified intraday data before running execution V2.")
            plan = {"plan_schema_version": "market-vault-intraday-backtest-plan-v2",
                    "intraday_data_path": self._intraday_path,
                    "strategy": {"name": "Intraday rule", "kind": "FEATURE_RULE", "signal_field": str(values.get("signal_field", "")),
                                 "comparator": str(values.get("comparator", "GT")),
                                 "threshold": _finite_float(values.get("threshold"), "threshold")},
                    "execution": self._intraday_execution_values(values)}
            expected_data_id = json.loads(self._intraday_data)["data_id"]
        except (TypeError, ValueError) as exc:
            return self._reject_input(exc)
        def operation(backend):
            from ..research.intraday_backtest import run_intraday_backtest
            return run_intraday_backtest(plan, expected_data_id=expected_data_id)
        return self._submit("intraday_backtest", operation, self._apply_intraday_backtest, requires_backend=False)

    @Property("QVariantMap", notify=researchChanged)
    def intradaySummary(self) -> dict:
        return self._intraday_summary

    @Property("QVariantMap", notify=researchChanged)
    def intradayPreviewSummary(self) -> dict:
        return self._intraday_preview_summary

    @Property(QObject, constant=True)
    def intradayModel(self) -> QObject:
        return self._intraday_model

    @Property(QObject, constant=True)
    def intradayPreviewModel(self) -> QObject:
        return self._intraday_preview_model

    def _intraday_arguments(self, values: dict) -> dict:
        horizon = str(values.get("target_horizon_bars", "3")).strip()
        return {"symbol": str(values.get("symbol", "")).strip().upper(),
                "start_date": str(values.get("start_date", "")).strip(),
                "end_date": str(values.get("end_date", "")).strip(),
                "interval": str(values.get("interval", "5m")),
                "preset": str(values.get("preset", "LIGHT_TECHNICAL")),
                "stride_bars": _bounded_int(values.get("stride_bars", 1), "stride_bars", 1, 2**31 - 1),
                "target_horizon_bars": None if not horizon else _bounded_int(horizon, "target_horizon_bars", 1, 2**31 - 1)}

    @Slot("QVariantMap", result=bool)
    def previewIntraday(self, values: dict) -> bool:
        try:
            arguments = self._intraday_arguments(values)
        except (TypeError, ValueError) as exc:
            return self._reject_input(exc)
        def apply(result):
            self._intraday_preview_summary = result[0]
            self._intraday_preview_model.set_page(result[1])
            self.researchChanged.emit()
        return self._submit("intraday_preview", lambda backend: backend.preview_intraday_workspace(**arguments), apply)

    def _apply_intraday(self, snapshot) -> None:
        from ..research.intraday_data import intraday_summary
        self._intraday_path = str(snapshot.path)
        self._intraday_data = snapshot.content
        self._intraday_summary = intraday_summary(snapshot)
        report = snapshot.as_dict()["report"]
        self._intraday_feature_names = tuple(report["feature_names"])
        targets = {row["observation_key"]: row for row in report["targets"]}
        self._intraday_columns = ("decision_time", "status", "target_status", "target_value", "reason", *report["feature_names"])
        self._intraday_rows = tuple(
            (row["decision_time"], row["status"], targets.get(row["observation_key"], {}).get("status", "DISABLED"),
             _format_number(targets.get(row["observation_key"], {}).get("value")),
             row["reason"] or targets.get(row["observation_key"], {}).get("reason") or "",
             *(_format_number(row["features"][name]) for name in report["feature_names"]))
            for row in report["observations"])
        self._intraday_page = 1
        self._set_intraday_page()
        self.researchChanged.emit()

    def _set_intraday_page(self) -> None:
        from ..console.models import TablePage
        start = (self._intraday_page - 1) * 100
        self._intraday_model.set_page(TablePage(self._intraday_columns, self._intraday_rows[start:start + 100],
                                               self._intraday_page, 100, len(self._intraday_rows)))

    @Slot(int, result=bool)
    def changeIntradayPage(self, offset: int) -> bool:
        page = self._intraday_page + offset
        if not 1 <= page <= max(1, (len(self._intraday_rows) + 99) // 100):
            return False
        self._intraday_page = page
        self._set_intraday_page()
        return True

    @Slot("QVariantMap", str, result=bool)
    def buildIntraday(self, values: dict, raw_path: str) -> bool:
        try:
            arguments = self._intraday_arguments(values)
            path = _experiment_file_path(raw_path)
        except (OSError, TypeError, ValueError) as exc:
            return self._reject_input(exc)
        def operation(backend):
            from ..research.intraday_data import load_intraday_dataset
            result = backend.build_intraday_workspace(output_path=str(path), **arguments)
            return load_intraday_dataset(result["data_path"])
        return self._submit("intraday_build", operation, self._apply_intraday)

    @Slot(str, result=bool)
    def inspectIntraday(self, raw_path: str) -> bool:
        try:
            path = _experiment_file_path(raw_path)
        except (OSError, TypeError, ValueError) as exc:
            return self._reject_input(exc)
        def operation(backend):
            from ..research.intraday_data import load_intraday_dataset
            return load_intraday_dataset(path)
        return self._submit("intraday_inspect", operation, self._apply_intraday, requires_backend=False)

    @Property(str, notify=researchChanged)
    def datasetPath(self) -> str:
        return self._dataset_path

    @Property(bool, notify=researchChanged)
    def datasetLoaded(self) -> bool:
        return bool(self._dataset_path)

    @Property("QVariantMap", notify=researchChanged)
    def datasetSummary(self) -> dict[str, str]:
        return dict(self._dataset_summary)

    @Property("QVariantMap", notify=researchChanged)
    def builderSummary(self) -> dict[str, str]:
        return dict(self._builder_summary)

    @Property("QVariantMap", notify=researchChanged)
    def featureSummary(self) -> dict[str, str]:
        return dict(self._feature_summary)

    @Property("QVariantMap", notify=researchChanged)
    def backtestSummary(self) -> dict[str, str]:
        return dict(self._backtest_summary)

    @Property("QVariantMap", notify=researchChanged)
    def comparisonSummary(self) -> dict[str, str]:
        return dict(self._comparison_summary)

    @Property("QVariantMap", notify=researchChanged)
    def comparisonExperimentInfo(self) -> dict:
        return dict(self._comparison_experiment_info)

    @Property("QVariantMap", notify=researchChanged)
    def comparisonExperimentPlan(self) -> dict:
        return json.loads(self._comparison_plan_json)

    @Property(int, notify=researchChanged)
    def comparisonRestoreRevision(self) -> int:
        return self._comparison_restore_revision

    @Property("QVariantMap", notify=researchChanged)
    def comparisonDiagnosticsPlan(self) -> dict:
        return json.loads(self._diagnostics_plan_json)

    @Property("QVariantMap", notify=researchChanged)
    def comparisonDiagnosticsSummary(self) -> dict:
        return dict(self._diagnostics_view.summary) if self._diagnostics_view else {}

    @Property("QVariantList", notify=researchChanged)
    def comparisonDiagnosticCandidates(self) -> list[str]:
        return list(self._diagnostics_view.labels) if self._diagnostics_view else []

    @Property(int, notify=researchChanged)
    def comparisonDiagnosticIndex(self) -> int:
        return self._diagnostic_index

    @Property(QObject, constant=True)
    def comparisonDiagnosticsModel(self) -> QObject:
        return self._comparison_diagnostics_model

    @Property(QObject, constant=True)
    def comparisonFoldModel(self) -> QObject:
        return self._comparison_fold_model

    @Property(QObject, constant=True)
    def comparisonModel(self) -> QObject:
        return self._comparison_model

    @Property(QObject, constant=True)
    def comparisonRiskModel(self) -> QObject:
        return self._comparison_risk_model

    @Property("QVariantList", notify=researchChanged)
    def comparisonBenchmarkSeries(self) -> list:
        return [list(point) for point in self._comparison_benchmark_series]

    @Property("QVariantList", notify=researchChanged)
    def comparisonEquityNames(self) -> list[str]:
        return [view.name for view in self._comparison_equity]

    @Property(int, notify=researchChanged)
    def comparisonEquityIndex(self) -> int:
        return self._comparison_equity_index

    @Property("QVariantList", notify=researchChanged)
    def comparisonEquitySeries(self) -> list:
        if not self._comparison_equity:
            return []
        return [list(point) for point in self._comparison_equity[self._comparison_equity_index].series]

    @Property(QObject, constant=True)
    def comparisonEquityModel(self) -> QObject:
        return self._comparison_equity_model

    @Property("QVariantList", notify=researchChanged)
    def featureNames(self) -> list[str]:
        return list(self._feature_names)

    @Property("QVariantList", notify=researchChanged)
    def labelNames(self) -> list[str]:
        return list(self._label_names)

    @Property("QVariantList", notify=researchChanged)
    def returnLabelNames(self) -> list[str]:
        return list(self._return_label_names)

    @Property("QVariantList", notify=researchChanged)
    def equitySeries(self) -> list[float]:
        return list(self._equity_series)

    @Property(QObject, constant=True)
    def builderModel(self) -> QObject:
        return self._builder_model

    @Property(QObject, constant=True)
    def featureModel(self) -> QObject:
        return self._feature_model

    @Property(QObject, constant=True)
    def tradesModel(self) -> QObject:
        return self._trade_model

    def _clear_results(self) -> None:
        self._feature_summary = {}
        self._backtest_summary = {}
        self._comparison_summary = {}
        self._comparison_experiment = b""
        self._comparison_experiment_info = {}
        self._comparison_plan_json = "{}"
        self._comparison_opened = False
        self._clear_diagnostics()
        self._comparison_model.set_page(_comparison_page(()))
        self._comparison_risk_model.set_page(_comparison_risk_page(()))
        self._comparison_benchmark_series = ()
        self._comparison_equity = ()
        self._comparison_equity_index = 0
        self._set_comparison_equity_page(1)
        self._trade_rows = ()
        self._equity_series = ()
        self._set_feature_page(())
        self._set_trade_page(1)

    def _clear_diagnostics(self) -> None:
        self._diagnostics_view = None
        self._diagnostic_index = 0
        self._diagnostics_plan_json = "{}"
        self._comparison_diagnostics_model.set_page(_diagnostics_page(()))
        self._comparison_fold_model.set_page(_fold_contribution_page(()))

    def _set_feature_page(self, rows: tuple[tuple[str, ...], ...]) -> None:
        self._feature_model.set_page(
            _table_page(
                (
                    "feature_name",
                    "sample_count",
                    "pearson_ic",
                    "rank_ic",
                    "top_bottom_spread",
                    "feature_mean",
                    "feature_std",
                ),
                rows,
            )
        )

    def _set_trade_page(self, page: int) -> None:
        total = len(self._trade_rows)
        total_pages = max(1, (total + TRADE_PAGE_SIZE - 1) // TRADE_PAGE_SIZE)
        page = max(1, min(page, total_pages))
        start = (page - 1) * TRADE_PAGE_SIZE
        rows = self._trade_rows[start : start + TRADE_PAGE_SIZE]
        from market_vault.console.models import TablePage
        self._trade_model.set_page(
            TablePage(
                columns=(
                    "code",
                    "signal_time",
                    "entry_time",
                    "exit_time",
                    "signal_value",
                    "gross_return",
                    "net_return",
                    "equity_after",
                ),
                rows=rows,
                page=page,
                page_size=TRADE_PAGE_SIZE,
                total_rows=total,
            )
        )

    def _builder_arguments(self, values: dict[str, Any]) -> dict[str, Any]:
        arguments = dict(values)
        horizon = _bounded_int(
            arguments.get("horizon_trading_days", 1),
            "horizon_trading_days",
            1,
            20,
        )
        return {
            "symbol": str(arguments.get("symbol", "")).strip().upper(),
            "start_date": str(arguments.get("start_date", "")).strip(),
            "end_date": str(arguments.get("end_date", "")).strip(),
            "interval": str(arguments.get("interval", "1m")).strip().lower(),
            "preset": str(arguments.get("preset", "CORE_TECHNICAL")).strip().upper(),
            "horizon_trading_days": horizon,
        }

    @Slot("QVariantMap", result=bool)
    def previewBuilder(self, values: dict[str, Any]) -> bool:
        try:
            arguments = self._builder_arguments(values)
        except (TypeError, ValueError) as exc:
            return self._reject_input(exc)
        self._builder_values = dict(arguments)

        def apply(result: Any) -> None:
            summary, page = result
            self._builder_summary = {str(k): str(v) for k, v in summary.items()}
            self._builder_model.set_page(page)
            self.researchChanged.emit()

        return self._submit(
            "research_workspace_preview",
            lambda backend: backend.preview_research_workspace(**arguments),
            apply,
        )

    @Slot("QVariantMap", result=bool)
    def requestPrepareResearchData(self, values: dict[str, Any]) -> bool:
        try:
            arguments = self._builder_arguments(values)
        except (TypeError, ValueError) as exc:
            return self._reject_input(exc)
        self._builder_values = dict(arguments)
        network_arguments = {
            key: arguments[key]
            for key in ("symbol", "start_date", "end_date", "interval")
        }

        def result_status(result: Any) -> str:
            if not isinstance(result, dict):
                raise TypeError("research backfill result must be a mapping")
            status = str(result.get("status", "")).strip().upper()
            if status not in {"SUCCESS", "PARTIAL", "FAILED"}:
                raise ValueError("invalid research backfill status")
            return status

        def apply(result: Any) -> None:
            self._builder_summary = {
                "research_data_prepare": str(result.get("status", "")),
                "successful_items": str(
                    len(result.get("successful_items", ()) or ())
                ),
                "failed_items": str(
                    len(result.get("failed_items", {}) or {})
                ),
            }
            self.researchChanged.emit()
            if str(result.get("status", "")).upper() == "SUCCESS":
                QTimer.singleShot(
                    0,
                    lambda: self.previewBuilder(dict(self._builder_values)),
                )

        return self._request_network(
            "research_backfill_execute",
            network_arguments,
            apply,
            result_status=result_status,
        )

    @Slot("QVariantMap", result=bool)
    def buildDataset(self, values: dict[str, Any]) -> bool:
        try:
            arguments = self._builder_arguments(values)
        except (TypeError, ValueError) as exc:
            return self._reject_input(exc)
        self._builder_values = dict(arguments)

        def operation(backend: Any):
            result = backend.build_research_workspace(**arguments)
            path = _dataset_directory(str(result["dataset_build_path"]))
            return result, _inspect_dataset(path)

        def apply(payload: Any) -> None:
            result, view = payload
            self._builder_summary = {
                str(k): str(v) for k, v in dict(result).items()
            }
            self._dataset_path = view.path
            self._dataset_summary = dict(view.summary)
            self._feature_names = view.feature_names
            self._label_names = view.label_names
            self._return_label_names = view.return_label_names
            self._clear_results()
            self._builder_model.set_page(
                _table_page(
                    ("trade_date", "calendar_profile", "research_data", "role"),
                    (),
                )
            )
            self.researchChanged.emit()
            self.datasetBuilt.emit()

        return self._submit(
            "research_workspace_build",
            operation,
            apply,
        )

    @Slot(str, result=bool)
    def inspectDataset(self, raw_path: str) -> bool:
        try:
            path = _dataset_directory(raw_path)
        except (OSError, TypeError, ValueError) as exc:
            return self._reject_input(exc)

        def apply(view: _DatasetView) -> None:
            self._dataset_path = view.path
            self._dataset_summary = dict(view.summary)
            self._feature_names = view.feature_names
            self._label_names = view.label_names
            self._return_label_names = view.return_label_names
            if not (self._comparison_opened and view.summary.get("dataset_id") ==
                    self._comparison_experiment_info.get("dataset_id")):
                self._clear_results()
            self.researchChanged.emit()

        return self._submit(
            "quant_inspect",
            lambda backend: _inspect_dataset(path),
            apply,
            requires_backend=False,
        )

    @Slot("QVariantMap", result=bool)
    def runFeatureResearch(self, values: dict[str, Any]) -> bool:
        if not self._dataset_path:
            return self._reject_input(ValueError("Inspect a Research Dataset first."))
        try:
            values = dict(values)
            label = str(values.get("label_field", "")).strip()
            split = str(values.get("split", "TRAIN")).strip().upper()
            quantiles = _bounded_int(values.get("quantile_count", 5), "quantile_count", 2, 10)
            if label not in self._label_names:
                raise ValueError("Select one Dataset Label.")
            if split not in _SPLITS:
                raise ValueError("split must be TRAIN, VALIDATION, or TEST")
            path = Path(self._dataset_path)
        except (TypeError, ValueError) as exc:
            return self._reject_input(exc)

        def apply(view: _FeatureResearchView) -> None:
            self._feature_summary = dict(view.summary)
            self._feature_model.set_page(view.page)
            self.researchChanged.emit()

        return self._submit(
            "feature_research",
            lambda backend: _run_feature_research(
                path,
                label_field=label,
                split=split,
                quantile_count=quantiles,
            ),
            apply,
            requires_backend=False,
        )

    @Slot("QVariantMap", result=bool)
    def runBacktest(self, values: dict[str, Any]) -> bool:
        if not self._dataset_path:
            return self._reject_input(ValueError("Inspect a Research Dataset first."))
        try:
            values = dict(values)
            signal = str(values.get("signal_field", "")).strip()
            comparator = str(values.get("comparator", "GT")).strip().upper()
            return_label = str(values.get("return_label", "")).strip()
            split = str(values.get("split", "TEST")).strip().upper()
            threshold = _finite_float(values.get("threshold", 0.0), "threshold")
            commission = _finite_float(values.get("commission_bps", 0.0), "commission_bps", nonnegative=True)
            slippage = _finite_float(values.get("slippage_bps", 0.0), "slippage_bps", nonnegative=True)
            if signal not in self._feature_names:
                raise ValueError("Select one admitted numeric Feature.")
            if comparator not in _COMPARATORS:
                raise ValueError("comparator must be GT, GE, LT, or LE")
            if return_label not in self._return_label_names:
                raise ValueError("Select an execution-safe forward-open-to-close return Label.")
            if split not in _SPLITS:
                raise ValueError("split must be TRAIN, VALIDATION, or TEST")
            path = Path(self._dataset_path)
        except (TypeError, ValueError) as exc:
            return self._reject_input(exc)

        def apply(view: _BacktestView) -> None:
            self._backtest_summary = dict(view.summary)
            self._trade_rows = view.trade_rows
            self._equity_series = view.equity_series
            self._set_trade_page(1)
            self.researchChanged.emit()

        return self._submit(
            "backtest",
            lambda backend: _run_backtest(
                path,
                signal_field=signal,
                comparator=comparator,
                threshold=threshold,
                return_label=return_label,
                split=split,
                commission_bps=commission,
                slippage_bps=slippage,
            ),
            apply,
            requires_backend=False,
        )

    @Slot("QVariantMap", result=bool)
    def runStrategyComparison(self, values: dict[str, Any]) -> bool:
        if not self._dataset_path:
            return self._reject_input(ValueError("Inspect a Research Dataset first."))
        try:
            values = dict(values)
            parsed = {}
            with_equity = values.get("equity_curve", False)
            with_risk = values.get("risk_report", False)
            if type(with_equity) is not bool:
                raise ValueError("equity_curve must be a boolean")
            if type(with_risk) is not bool:
                raise ValueError("risk_report must be a boolean")
            if with_risk:
                parsed["risk_report"] = True
            if with_equity:
                parsed["equity_curve"] = True
            if "strategies" in values:
                parsed.update(_parse_comparison_strategies(values, self._feature_names))
            else:
                for field in ("trend_feature", "reversion_feature"):
                    parsed[field] = str(values.get(field, "")).strip()
                    if parsed[field] not in self._feature_names:
                        raise ValueError("Select admitted numeric Features for both rules.")
                for field in ("trend_threshold", "reversion_threshold", "ridge_threshold"):
                    parsed[field] = _finite_float(values.get(field, 0), field)
                parsed["ridge_alpha"] = _finite_float(values.get("ridge_alpha", 1), "ridge_alpha")
                if parsed["ridge_alpha"] <= 0:
                    raise ValueError("ridge_alpha must be strictly positive")
            parsed.update(_parse_comparison_windows(values, self._return_label_names))
            path = Path(self._dataset_path)
        except (TypeError, ValueError) as exc:
            return self._reject_input(exc)

        def apply(view: _ComparisonView) -> None:
            self._apply_comparison_view(view)
            self.researchChanged.emit()

        return self._submit(
            "strategy_comparison",
            lambda backend: _run_strategy_comparison(path, **parsed),
            apply,
            requires_backend=False,
        )

    @Slot("QVariantMap", result=bool)
    def runStrategyDiagnostics(self, values: dict[str, Any]) -> bool:
        if not self._dataset_path:
            return self._reject_input(ValueError("Inspect a Research Dataset first."))
        try:
            path = Path(self._dataset_path)
            plan = _parse_diagnostics_input(values, path=path,
                                           admitted_features=self._feature_names,
                                           admitted_labels=self._return_label_names)
        except (TypeError, ValueError) as exc:
            return self._reject_input(exc)

        def apply(view):
            self._apply_comparison_view(view)
            self.researchChanged.emit()

        return self._submit("strategy_diagnostics", lambda backend: _run_strategy_diagnostics(path, plan=plan),
                            apply, requires_backend=False)

    @Slot(str, result=bool)
    def saveComparisonExperiment(self, raw_path: str) -> bool:
        if not self._comparison_experiment:
            return self._reject_input(ValueError("Complete or open a strategy experiment first."))
        try:
            path = _experiment_file_path(raw_path)
        except (TypeError, ValueError) as exc:
            return self._reject_input(exc)
        captured = self._comparison_experiment

        def operation(backend):
            from market_vault.research.strategy_experiment import StrategyExperiment, write_strategy_experiment
            return write_strategy_experiment(StrategyExperiment(captured), path=path)

        def apply(result):
            self._comparison_experiment_info = {**self._comparison_experiment_info, "path": str(result.path)}
            self.researchChanged.emit()

        return self._submit("strategy_experiment_save", operation, apply, requires_backend=False)

    @Slot(str, result=bool)
    def openComparisonExperiment(self, raw_path: str) -> bool:
        try:
            path = _experiment_file_path(raw_path)
        except (TypeError, ValueError) as exc:
            return self._reject_input(exc)

        def operation(backend):
            from market_vault.research.strategy_experiment import load_strategy_experiment
            snapshot = load_strategy_experiment(path)
            return _experiment_payload_view(snapshot)

        def apply(view):
            # An archived locator is not a verified Dataset context.
            self._dataset_path = ""
            self._dataset_summary = {}
            self._feature_names = self._label_names = self._return_label_names = ()
            self._clear_results()
            self._apply_comparison_view(view, opened_path=str(path))
            self._comparison_restore_revision += 1
            self.researchChanged.emit()

        return self._submit("strategy_experiment_open", operation, apply, requires_backend=False)

    @Slot(str, result=bool)
    def replayComparisonExperiment(self, raw_dataset_path: str = "") -> bool:
        if not self._comparison_experiment:
            return self._reject_input(ValueError("Complete or open a strategy experiment first."))
        try:
            path = _dataset_directory(raw_dataset_path) if raw_dataset_path.strip() else None
        except (OSError, TypeError, ValueError) as exc:
            return self._reject_input(exc)
        captured = self._comparison_experiment

        def operation(backend):
            from market_vault.research.strategy_experiment import StrategyExperiment, replay_strategy_experiment
            return replay_strategy_experiment(StrategyExperiment(captured), dataset_build_dir=path)

        def apply(result):
            self._comparison_experiment_info = {**self._comparison_experiment_info,
                "replay_verified": True, "report_sha256": result["actual_report_sha256"]}
            self.researchChanged.emit()

        return self._submit("strategy_experiment_replay", operation, apply, requires_backend=False)

    def _apply_comparison_tables(self, view: _ComparisonView) -> None:
        selected = (self._comparison_equity[self._comparison_equity_index].name
                    if self._comparison_equity else None)
        self._comparison_summary = dict(view.summary)
        self._comparison_model.set_page(view.page)
        self._comparison_risk_model.set_page(view.risk_page if view.risk_page is not None
                                            else _comparison_risk_page(()))
        self._comparison_benchmark_series = view.benchmark_series
        self._comparison_equity = view.equity
        names = [item.name for item in view.equity]
        self._comparison_equity_index = names.index(selected) if selected in names else 0
        self._set_comparison_equity_page(1)

    def _apply_comparison_view(self, view: _ComparisonView, *, opened_path: str = "") -> None:
        self._apply_comparison_tables(view)
        self._clear_diagnostics()
        if view.diagnostics is not None:
            self._diagnostics_view = view.diagnostics
            self._comparison_diagnostics_model.set_page(view.diagnostics.page)
            self._comparison_fold_model.set_page(_fold_contribution_page(view.diagnostics.fold_rows[0]))
            self._comparison_equity_index = 0
            self._set_comparison_equity_page(1)
        self._comparison_experiment = view.experiment
        self._comparison_opened = bool(opened_path)
        root = json.loads(view.experiment) if view.experiment else None
        plan = root["plan"] if root else {}
        if root and root["evaluation_mode"] == "DIAGNOSTICS":
            self._diagnostics_plan_json = json.dumps(plan)
            plan = plan["comparison_plan"]
        self._comparison_plan_json = json.dumps(plan)
        self._comparison_experiment_info = ({
            "experiment_id": root["experiment_id"], "dataset_id": root["dataset_id"],
            "dataset_build_dir": plan["dataset_build_dir"],
            "evaluation_mode": root["evaluation_mode"], "path": opened_path,
            "opened_snapshot": bool(opened_path),
            "name": root["name"], "notes": root["notes"], "replay_verified": False,
        } if root else {})

    @Slot(int, result=bool)
    def selectStrategyDiagnostic(self, index: int) -> bool:
        view = self._diagnostics_view
        if view is None or not 0 <= index < len(view.positions):
            return False
        group, variant = view.positions[index]
        # Only replace presentation. The complete experiment, saved path, replay
        # status and form restoration revision continue to refer to the bundle.
        self._apply_comparison_tables(view.groups[group])
        self._diagnostic_index = index
        self._comparison_equity_index = variant
        self._set_comparison_equity_page(1)
        self._comparison_fold_model.set_page(_fold_contribution_page(view.fold_rows[index]))
        self.researchChanged.emit()
        return True

    @Slot(int, result=bool)
    def changeComparisonFoldPage(self, offset: int) -> bool:
        page = self._comparison_fold_model.page + offset
        if (self._diagnostics_view is None or offset not in (-1, 1)
                or not 1 <= page <= self._comparison_fold_model.totalPages):
            return False
        self._comparison_fold_model.set_page(_fold_contribution_page(
            self._diagnostics_view.fold_rows[self._diagnostic_index], page=page))
        self.researchChanged.emit()
        return True

    def _set_comparison_equity_page(self, page: int) -> None:
        from market_vault.console.models import TablePage
        rows = (self._comparison_equity[self._comparison_equity_index].rows
                if self._comparison_equity else ())
        pages = max(1, (len(rows) + TRADE_PAGE_SIZE - 1) // TRADE_PAGE_SIZE)
        page = max(1, min(page, pages))
        offset = (page - 1) * TRADE_PAGE_SIZE
        self._comparison_equity_model.set_page(TablePage(
            columns=("timestamp", "equity", "drawdown", "cash", "quantity",
                     "mark_price", "market_value", "transaction_cost", "event"),
            rows=rows[offset:offset + TRADE_PAGE_SIZE], page=page,
            page_size=TRADE_PAGE_SIZE, total_rows=len(rows),
        ))

    @Slot(int, result=bool)
    def selectComparisonEquity(self, index: int) -> bool:
        if not 0 <= index < len(self._comparison_equity):
            return False
        if self._diagnostics_view is not None and index < len(self._comparison_equity) - 1:
            group = self._diagnostics_view.positions[self._diagnostic_index][0]
            return self.selectStrategyDiagnostic(self._diagnostics_view.positions.index((group, index)))
        self._comparison_equity_index = index
        self._set_comparison_equity_page(1)
        self.researchChanged.emit()
        return True

    @Slot(int, result=bool)
    def changeComparisonEquityPage(self, offset: int) -> bool:
        page = self._comparison_equity_model.page + offset
        if offset not in (-1, 1) or not 1 <= page <= self._comparison_equity_model.totalPages:
            return False
        self._set_comparison_equity_page(page)
        self.researchChanged.emit()
        return True

    @Slot(result=bool)
    def previousTradesPage(self) -> bool:
        page = self._trade_model.page
        if page <= 1:
            return False
        self._set_trade_page(page - 1)
        self.researchChanged.emit()
        return True

    @Slot(result=bool)
    def nextTradesPage(self) -> bool:
        page = self._trade_model.page
        if page >= self._trade_model.totalPages:
            return False
        self._set_trade_page(page + 1)
        self.researchChanged.emit()
        return True
