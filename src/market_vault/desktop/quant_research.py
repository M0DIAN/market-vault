"""Functional Quant Research / Backtest controller for the QML desktop.

The desktop is a presentation layer over the already-validated v0.9 research
authorities. This module does not implement Feature calculations or Backtest
math. Worker operations load one explicit verified Research Dataset and call
the existing ML adapter, Feature Research, and Backtest Engine V1 directly.

Business imports stay inside worker functions so normal desktop startup remains
lazy and does not initialize research/storage authorities merely by showing the
navigation shell.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from market_vault.desktop.controllers import PageController
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
    path = Path(text).expanduser()
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


class QuantResearchController(PageController):
    """Expose verified Feature Research and Backtest Engine V1 to QML."""

    researchChanged = Signal()

    def __init__(self, runtime, *, parent: QObject | None = None) -> None:
        super().__init__(runtime, parent=parent)
        self._dataset_path = ""
        self._dataset_summary: dict[str, str] = {}
        self._feature_summary: dict[str, str] = {}
        self._backtest_summary: dict[str, str] = {}
        self._feature_names: tuple[str, ...] = ()
        self._label_names: tuple[str, ...] = ()
        self._return_label_names: tuple[str, ...] = ()
        self._feature_model = QtTableModel(parent=self)
        self._trade_model = QtTableModel(parent=self)
        self._trade_rows: tuple[tuple[str, ...], ...] = ()
        self._equity_series: tuple[float, ...] = ()
        self._set_feature_page(())
        self._set_trade_page(1)

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
    def featureSummary(self) -> dict[str, str]:
        return dict(self._feature_summary)

    @Property("QVariantMap", notify=researchChanged)
    def backtestSummary(self) -> dict[str, str]:
        return dict(self._backtest_summary)

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
    def featureModel(self) -> QObject:
        return self._feature_model

    @Property(QObject, constant=True)
    def tradesModel(self) -> QObject:
        return self._trade_model

    def _clear_results(self) -> None:
        self._feature_summary = {}
        self._backtest_summary = {}
        self._trade_rows = ()
        self._equity_series = ()
        self._set_feature_page(())
        self._set_trade_page(1)

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
            self._clear_results()
            self.researchChanged.emit()

        return self._submit(
            "quant_inspect",
            lambda backend: _inspect_dataset(path),
            apply,
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
        )

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
