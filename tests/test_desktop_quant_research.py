from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication

from market_vault.console.models import TablePage
from market_vault.desktop.quant_research import (
    QuantResearchController,
    _BacktestView,
    _DatasetView,
    _FeatureResearchView,
)
from market_vault.desktop.runtime import DesktopOperationRuntime


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


class _Runner:
    def __init__(self):
        self.names = []

    def submit(self, name, operation):
        self.names.append(name)
        future = Future()
        try:
            future.set_result(operation())
        except Exception as exc:
            future.set_exception(exc)
        return future

    def close(self):
        pass


def _runtime(tmp_path, backend_calls):
    runner = _Runner()
    runtime = DesktopOperationRuntime(
        settings_path=(tmp_path / "settings.yaml").resolve(),
        backend_factory=lambda path: backend_calls.append(path),
        runner_factory=lambda: runner,
    )
    return runtime, runner


def test_quant_controller_rejects_relative_dataset_path_without_backend(qt_app, tmp_path):
    backend_calls = []
    runtime, runner = _runtime(tmp_path, backend_calls)
    controller = QuantResearchController(runtime)

    assert controller.inspectDataset("relative/path") is False
    assert controller.status == "VALIDATION_ERROR"
    assert "absolute" in controller.error
    assert controller.datasetLoaded is False
    assert backend_calls == []
    assert runner.names == []
    assert runtime.backend_if_initialized is None
    assert runtime.shutdown() is True


def test_quant_controller_runs_views_without_initializing_console_backend(
    qt_app, tmp_path, monkeypatch
):
    backend_calls = []
    runtime, runner = _runtime(tmp_path, backend_calls)
    controller = QuantResearchController(runtime)
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()

    monkeypatch.setattr(
        "market_vault.desktop.quant_research._inspect_dataset",
        lambda path: _DatasetView(
            str(dataset_dir.resolve()),
            {"dataset_id": "d" * 64, "rows": "3", "features": "2"},
            ("rsi_14", "macd_line"),
            ("forward_return_1d",),
            ("forward_return_1d",),
        ),
    )
    assert controller.inspectDataset(str(dataset_dir.resolve())) is True
    runtime._poll()
    assert controller.datasetLoaded is True
    assert controller.featureNames == ["rsi_14", "macd_line"]
    assert controller.returnLabelNames == ["forward_return_1d"]
    assert controller.datasetSummary["dataset_id"] == "d" * 64
    assert backend_calls == []
    assert runtime.backend_if_initialized is None

    feature_page = TablePage(
        columns=(
            "feature_name",
            "sample_count",
            "pearson_ic",
            "rank_ic",
            "top_bottom_spread",
            "feature_mean",
            "feature_std",
        ),
        rows=(("rsi_14", "3", "0.1", "0.2", "0.01", "50", "5"),),
        page_size=1,
        total_rows=1,
    )
    monkeypatch.setattr(
        "market_vault.desktop.quant_research._run_feature_research",
        lambda path, **kwargs: _FeatureResearchView(
            {"best_feature": "rsi_14", "best_rank_ic": "0.2"},
            feature_page,
        ),
    )
    assert controller.runFeatureResearch(
        {"label_field": "forward_return_1d", "split": "TRAIN", "quantile_count": "5"}
    ) is True
    runtime._poll()
    assert controller.featureSummary["best_feature"] == "rsi_14"
    assert controller.featureModel.rowCount() == 1
    assert backend_calls == []

    monkeypatch.setattr(
        "market_vault.desktop.quant_research._run_backtest",
        lambda path, **kwargs: _BacktestView(
            {"trade_count": "2", "total_return": "3.00%"},
            (
                ("US.SPY", "s1", "e1", "x1", "1", "1.00%", "0.90%", "1.009"),
                ("US.SPY", "s2", "e2", "x2", "2", "2.00%", "1.90%", "1.028"),
            ),
            (1.0, 1.009, 1.028),
        ),
    )
    assert controller.runBacktest(
        {
            "signal_field": "rsi_14",
            "comparator": "GT",
            "threshold": "50",
            "return_label": "forward_return_1d",
            "split": "TEST",
            "commission_bps": "1",
            "slippage_bps": "2",
        }
    ) is True
    runtime._poll()
    assert controller.backtestSummary["trade_count"] == "2"
    assert controller.equitySeries == [1.0, 1.009, 1.028]
    assert controller.tradesModel.rowCount() == 2
    assert runner.names == ["quant_inspect", "feature_research", "backtest"]
    assert backend_calls == []
    assert runtime.backend_if_initialized is None
    assert runtime.shutdown() is True


def test_quant_qml_is_functional_workflow_not_placeholder():
    qml = (
        ROOT / "src" / "market_vault" / "desktop" / "qml" / "pages"
        / "QuantResearchPage.qml"
    ).read_text(encoding="utf-8")
    for marker in (
        "FolderDialog",
        "inspectDataset",
        "runFeatureResearch",
        "runBacktest",
        'objectName: "quantFeatureTable"',
        'objectName: "quantTradesTable"',
        'objectName: "quantEquityCanvas"',
    ):
        assert marker in qml
    assert "Placeholder" not in qml


def test_quant_controller_source_keeps_business_imports_lazy():
    source = (
        ROOT / "src" / "market_vault" / "desktop" / "quant_research.py"
    ).read_text(encoding="utf-8")
    prefix = source.split("def _load_verified_dataset", 1)[0]
    assert "market_vault.cross_day_dataset" not in prefix
    assert "market_vault.research" not in prefix
    assert "market_vault.backtest" not in prefix
