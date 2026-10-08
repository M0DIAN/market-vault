from __future__ import annotations

from concurrent.futures import Future
import json
import os
from pathlib import Path
import subprocess
import sys

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


def test_quant_builder_calls_backend_and_autoloads_built_dataset(
    qt_app, tmp_path, monkeypatch
):
    backend_calls = []
    dataset_dir = tmp_path / "built-dataset"
    dataset_dir.mkdir()

    class Backend:
        def preview_research_workspace(self, **values):
            return (
                {
                    "build_ready": "true",
                    "missing_research_dates": "0",
                    "research_schema": "10.9-mv-ts2",
                },
                TablePage(
                    columns=("trade_date", "calendar_profile", "research_data", "role"),
                    rows=(("2026-01-05", "NORMAL", "READY", "TRAIN"),),
                    page_size=1,
                    total_rows=1,
                ),
            )

        def build_research_workspace(self, **values):
            return {
                "dataset_build_path": str(dataset_dir.resolve()),
                "dataset_id": "d" * 64,
                "dataset_status": "COMPLETE",
            }

    settings = tmp_path / "settings.yaml"
    settings.write_text(
        """
storage:
  root_dir: ./data
  catalog_path: ./catalog/market_vault.duckdb
  manifest_dir: ./manifests
  report_dir: ./reports
""".lstrip(),
        encoding="utf-8",
    )
    runner = _Runner()
    runtime = DesktopOperationRuntime(
        settings_path=settings.resolve(),
        backend_factory=lambda path: backend_calls.append(path) or Backend(),
        runner_factory=lambda: runner,
    )
    controller = QuantResearchController(runtime)
    values = {
        "symbol": "US.SPY",
        "start_date": "2026-01-05",
        "end_date": "2026-01-16",
        "interval": "5m",
        "preset": "LIGHT_TECHNICAL",
        "horizon_trading_days": "1",
    }

    assert controller.previewBuilder(values) is True
    runtime._poll()
    assert controller.builderSummary["build_ready"] == "true"
    assert controller.builderModel.rowCount() == 1
    assert len(backend_calls) == 1

    monkeypatch.setattr(
        "market_vault.desktop.quant_research._inspect_dataset",
        lambda path: _DatasetView(
            str(dataset_dir.resolve()),
            {"dataset_id": "d" * 64, "rows": "9"},
            ("rsi_5",),
            ("execution_return_1d",),
            ("execution_return_1d",),
        ),
    )
    built = []
    controller.datasetBuilt.connect(lambda: built.append(True))
    assert controller.buildDataset(values) is True
    runtime._poll()

    assert built == [True]
    assert controller.datasetLoaded is True
    assert controller.datasetPath == str(dataset_dir.resolve())
    assert controller.featureNames == ["rsi_5"]
    assert controller.returnLabelNames == ["execution_return_1d"]
    assert controller.builderSummary["dataset_status"] == "COMPLETE"
    assert runner.names == ["research_workspace_preview", "research_workspace_build"]
    assert runtime.shutdown() is True


def test_quant_qml_is_functional_workflow_not_placeholder():
    qml = (
        ROOT / "src" / "market_vault" / "desktop" / "qml" / "pages"
        / "QuantResearchPage.qml"
    ).read_text(encoding="utf-8")
    for marker in (
        "FolderDialog",
        "inspectDataset",
        "previewBuilder",
        "requestPrepareResearchData",
        "buildDataset",
        "runFeatureResearch",
        "runBacktest",
        'objectName: "quantBuilderTable"',
        'objectName: "quantBuilderPrepareButton"',
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


def test_comparison_qml_click_dispatches_form_values_and_shows_results(tmp_path):
    """Actual QML button/slot wiring; the financial worker has separate integration coverage."""
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    (tmp_path / "settings.yaml").write_text("storage:\n  root_dir: ./data\n", encoding="utf-8")
    script = f'''
import json
import sys
from pathlib import Path
from PySide6.QtCore import QObject, QMetaObject, QUrl, Qt, QEvent
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from market_vault.application import build_application_context
from market_vault.desktop.bootstrap import create_qml_application_session
from market_vault.desktop.preferences import DesktopPreferenceStore
from market_vault.desktop import quant_research as quant
sys.path.insert(0, {str(ROOT / "tests")!r})
from test_desktop_quant_research import _Runner

root_path = Path({str(tmp_path)!r})
dataset = Path({str(dataset_dir)!r})
runner = _Runner()
backend_calls = []
context = build_application_context(
    root_path / 'settings.yaml',
    backend_factory=lambda value: backend_calls.append(value),
    runner_factory=lambda: runner,
)
QQuickStyle.setStyle('Basic')
app = QGuiApplication([])
engine = QQmlApplicationEngine()
session = create_qml_application_session(
    context, engine,
    preference_store=DesktopPreferenceStore(root=root_path / 'preferences'),
)
engine.load(QUrl.fromLocalFile({str(ROOT / "src/market_vault/desktop/qml/Main.qml")!r}))
assert engine.rootObjects()
window = engine.rootObjects()[0]
controller = session.context_properties['quantResearchController']
assert session.shell.selectPage('quant_research')
tab = window.findChild(QObject, 'quantComparisonTab')
assert QMetaObject.invokeMethod(tab, 'clicked', Qt.DirectConnection)
app.processEvents()
panel = window.findChild(QObject, 'quantStrategyComparisonPanel')
button = window.findChild(QObject, 'quantRunComparisonButton')
assert panel.property('visible')
assert not button.property('enabled')
quant._inspect_dataset = lambda path: quant._DatasetView(
    str(path), {{'dataset_id': 'd' * 64}}, ('sma_5', 'return_2', 'rsi_5'),
    ('execution_return_1d', 'execution_return_2d'),
    ('execution_return_1d', 'execution_return_2d'),
)
assert controller.inspectDataset(str(dataset))
session.runtime._poll()
app.processEvents()
QTest.qWait(30)
def find_item(name):
    found = window.findChild(QObject, name)
    if found is not None:
        return found
    # ListView delegates belong to the visual tree, not necessarily QObject children.
    pending = [window.contentItem()]
    while pending:
        item = pending.pop()
        if item.objectName() == name:
            return item
        pending.extend(item.childItems())
    return None

def select_combo(name, key):
    QTest.qWait(20)
    field = find_item(name)
    assert field is not None, name
    combo = next((c for c in field.children() if 'PixelComboBox' in c.metaObject().className()), field)
    combo.forceActiveFocus()
    QTest.keyClick(window, key)
    app.processEvents()
    return field

def type_text(name, text):
    QTest.qWait(20)
    field = find_item(name)
    assert field is not None, name
    edit = next((c for c in field.children() if 'PixelTextField' in c.metaObject().className()), field)
    edit.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
    for character in text:
        QGuiApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, ord(character.upper()), Qt.NoModifier, character))
    app.processEvents()
    assert edit.property('text') == text

assert QMetaObject.invokeMethod(window.findChild(QObject, 'quantStrategyAddButton'), 'clicked', Qt.DirectConnection)
QTest.qWait(20)
assert find_item('quantConditionFeature0').property('currentText') == 'return_2'
assert QMetaObject.invokeMethod(window.findChild(QObject, 'quantStrategyRemoveButton'), 'clicked', Qt.DirectConnection)
app.processEvents()
select_combo('quantStrategySelector', Qt.Key_Up)
select_combo('quantStrategySelector', Qt.Key_Up)
type_text('quantComparisonFeatures', 'sma_5,rsi_5')
select_combo('quantConditionFeature0', Qt.Key_Up)
select_combo('quantStrategySelector', Qt.Key_Down)
select_combo('quantConditionFeature0', Qt.Key_Down)
add_strategy = window.findChild(QObject, 'quantStrategyAddButton')
assert QMetaObject.invokeMethod(add_strategy, 'clicked', Qt.DirectConnection)
app.processEvents()
select_combo('quantStrategyKind', Qt.Key_Down)
select_combo('quantStrategyKind', Qt.Key_Down)
type_text('quantStrategyName', 'Composite')
select_combo('quantStrategyMatch', Qt.Key_Down)
select_combo('quantConditionFeature1', Qt.Key_Down)
select_combo('quantConditionFeature1', Qt.Key_Down)
type_text('quantConditionThreshold1', '50')
conditions = window.findChild(QObject, 'quantStrategyConditions')
assert conditions.property('count') == 2
assert QMetaObject.invokeMethod(window.findChild(QObject, 'quantConditionAddButton'), 'clicked', Qt.DirectConnection)
app.processEvents()
assert conditions.property('count') == 3
QTest.qWait(20)
assert QMetaObject.invokeMethod(find_item('quantConditionRemove2'), 'clicked', Qt.DirectConnection)
app.processEvents()
assert conditions.property('count') == 2
assert QMetaObject.invokeMethod(add_strategy, 'clicked', Qt.DirectConnection)
app.processEvents()
assert window.findChild(QObject, 'quantStrategySelector').property('count') == 5
assert QMetaObject.invokeMethod(window.findChild(QObject, 'quantStrategyRemoveButton'), 'clicked', Qt.DirectConnection)
app.processEvents()
assert window.findChild(QObject, 'quantStrategySelector').property('count') == 4
assert window.findChild(QObject, 'quantStrategyName').property('text') == 'Composite'
selections = [('quantComparisonReturnLabel', Qt.Key_Down, 'execution_return_2d')]
for name, key, selected in selections:
    field = window.findChild(QObject, name)
    combo = next(c for c in field.children() if 'PixelComboBox' in c.metaObject().className())
    combo.forceActiveFocus()
    QTest.keyClick(window, key)
    app.processEvents()
    assert field.property('currentText') == selected
for name, text in [('Train', '3'), ('Validation', '2'), ('Step', '2')]:
    window.findChild(QObject, 'quantComparison' + name + 'Periods').setProperty('text', text)
captured = []
def compare(path, **values):
    captured.append((path, values))
    summary = {{'comparison_id': 'c' * 64, 'fold_count': '3', 'common_validation_rows': '6', 'held_out_test_rows': '2'}}
    rows = (('Trend', '3', '1%', '2%', '0%', '100%', '—', '0', '50%'),)
    equity = ()
    if values.get('equity_curve'):
        summary['equity_comparison_id'] = 'e' * 64
        rows = tuple(row + ('40%',) for row in rows)
        ledger_rows = tuple(('2026-01-05 14:35:00', '0.6', '40%', '0', '0.01', '60', '0.6', '0', 'BAR_CLOSE') for i in range(105))
        equity = (
            quant._ComparisonEquityView('Trend', ledger_rows, ((1767623400000.0, 1.0), (1767623700000.0, 0.6), (1767624000000.0, 1.1))),
            quant._ComparisonEquityView('Ridge', ledger_rows[:2], ((1767623400000.0, 1.0), (1767624000000.0, 1.02))),
        )
    risk_page, benchmark_series = None, ()
    if values.get('risk_report'):
        summary['risk_report_id'] = 'f' * 64
        benchmark_series = ((1767623400000.0, 1.0), (1767624000000.0, 1.15))
        equity += (quant._ComparisonEquityView('Buy & Hold', ledger_rows[:2], benchmark_series),)
        risk_page = quant._comparison_risk_page((
            ('Trend', '10%', '-5%', '40%', '12%', '0.5', '5', 'OK'),
            ('Buy & Hold', '15%', '0%', '10%', '15%', '0.7', '5', 'OK'),
        ))
    return quant._ComparisonView(
        summary, quant._comparison_page(rows, with_equity=bool(equity)), equity,
        risk_page, benchmark_series,
    )
quant._run_strategy_comparison = compare
assert button.property('enabled')
assert QMetaObject.invokeMethod(button, 'clicked', Qt.DirectConnection)
session.runtime._poll()
app.processEvents()
assert len(captured) == 1
path, values = captured[0]
assert path == dataset
from market_vault.research.strategy_config import strategy_plan_fields
expected_specs = [
    {{'kind': 'FEATURE_RULE', 'name': 'Trend', 'signal_field': 'sma_5', 'comparator': 'GT', 'threshold': 0.0}},
    {{'kind': 'FEATURE_RULE', 'name': 'MeanReversion', 'signal_field': 'rsi_5', 'comparator': 'LT', 'threshold': 0.0}},
    {{'kind': 'RIDGE', 'name': 'Ridge', 'alpha': 1.0, 'threshold': 0.0}},
    {{'kind': 'COMPOSITE_RULE', 'name': 'Composite', 'match': 'ANY', 'conditions': [
        {{'signal_field': 'sma_5', 'comparator': 'GT', 'threshold': 0.0}},
        {{'signal_field': 'rsi_5', 'comparator': 'GT', 'threshold': 50.0}},
    ]}},
]
assert [strategy_plan_fields(item) for item in values['strategies']] == expected_specs
assert {{key: value for key, value in values.items() if key != 'strategies'}} == {{
    'feature_fields': ('sma_5', 'rsi_5'), 'return_label': 'execution_return_2d',
    'minimum_train_periods': 3, 'validation_periods': 2, 'step_periods': 2,
    'commission_bps': 0.0, 'slippage_bps': 0.0,
}}
assert controller.comparisonModel.rowCount() == 1
assert controller.comparisonSummary['fold_count'] == '3'
assert runner.names == ['quant_inspect', 'strategy_comparison']
for name, key, selected in selections:
    assert window.findChild(QObject, name).property('currentText') == selected
assert QMetaObject.invokeMethod(button, 'clicked', Qt.DirectConnection)
session.runtime._poll()
app.processEvents()
assert len(captured) == 2
assert captured[1] == captured[0]
assert session.i18n.setLanguage('zh-CN')
app.processEvents()
assert button.property('text') == '比较策略'
assert window.findChild(QObject, 'quantStrategyKind').property('currentIndex') == 2
assert window.findChild(QObject, 'quantStrategyMatch').property('currentIndex') == 1
assert window.grabWindow().save(str(root_path / 'comparison-ui.png'))
toggle = window.findChild(QObject, 'quantComparisonEquityToggle')
toggle.forceActiveFocus()
QTest.keyClick(window, Qt.Key_Space)
app.processEvents()
assert toggle.property('checked')
assert QMetaObject.invokeMethod(button, 'clicked', Qt.DirectConnection)
session.runtime._poll()
app.processEvents()
assert captured[-1][1]['equity_curve'] is True
assert controller.comparisonModel.columnCount() == 10
assert controller.comparisonEquityNames == ['Trend', 'Ridge']
ledger_button = window.findChild(QObject, 'quantComparisonLedgerButton')
assert ledger_button.property('visible')
assert QMetaObject.invokeMethod(ledger_button, 'clicked', Qt.DirectConnection)
app.processEvents()
assert window.findChild(QObject, 'quantComparisonEquityCanvas').property('visible')
assert window.findChild(QObject, 'quantComparisonEquityTable').property('visible')
assert panel.property('showInputs') is False
assert window.findChild(QObject, 'quantComparisonEquityCanvas').property('height') >= 100
assert controller.comparisonEquityModel.rowCount() == 100
assert controller.changeComparisonEquityPage(1)
assert controller.comparisonEquityModel.rowCount() == 5
selector = window.findChild(QObject, 'quantComparisonEquityStrategy')
selector.forceActiveFocus()
QTest.keyClick(window, Qt.Key_Down)
app.processEvents()
assert selector.property('currentIndex') == controller.comparisonEquityIndex == 1
assert controller.comparisonEquityModel.page == 1
assert controller.comparisonEquityModel.rowCount() == 2
assert controller.comparisonEquitySeries[-1][1] == 1.02
# Repeating identical research preserves both form fields and selected curve.
assert QMetaObject.invokeMethod(button, 'clicked', Qt.DirectConnection)
session.runtime._poll()
app.processEvents()
assert len(captured) == 4
assert selector.property('currentIndex') == controller.comparisonEquityIndex == 1
assert window.grabWindow().save(str(root_path / 'comparison-equity-ui.png'))
risk_toggle = window.findChild(QObject, 'quantComparisonRiskToggle')
risk_toggle.forceActiveFocus()
QTest.keyClick(window, Qt.Key_Space)
app.processEvents()
assert risk_toggle.property('checked') and toggle.property('checked')
assert QMetaObject.invokeMethod(button, 'clicked', Qt.DirectConnection)
session.runtime._poll()
app.processEvents()
assert captured[-1][1]['risk_report'] is True
assert controller.comparisonEquityNames == ['Trend', 'Ridge', 'Buy & Hold']
assert controller.comparisonEquityIndex == 1
assert len(controller.comparisonBenchmarkSeries) == 2
assert controller.comparisonRiskModel.rowCount() == 2
risk_button = window.findChild(QObject, 'quantComparisonRiskButton')
assert risk_button.property('visible')
assert QMetaObject.invokeMethod(risk_button, 'clicked', Qt.DirectConnection)
app.processEvents()
QTest.qWait(30)
risk_table = window.findChild(QObject, 'quantComparisonRiskTable')
assert risk_table.property('visible') and risk_table.property('height') >= 100
assert panel.property('showInputs') is False
assert window.grabWindow().save(str(root_path / 'comparison-risk-ui.png'))
assert QMetaObject.invokeMethod(ledger_button, 'clicked', Qt.DirectConnection)
app.processEvents()
QTest.qWait(30)
assert window.grabWindow().save(str(root_path / 'comparison-benchmark-ui.png'))
# Turning risk off on the same equity identity must remove benchmark state.
assert QMetaObject.invokeMethod(risk_button, 'clicked', Qt.DirectConnection)
risk_toggle.forceActiveFocus()
QTest.keyClick(window, Qt.Key_Space)
app.processEvents()
assert QMetaObject.invokeMethod(button, 'clicked', Qt.DirectConnection)
session.runtime._poll()
app.processEvents()
assert controller.comparisonRiskModel.rowCount() == 0
assert controller.comparisonBenchmarkSeries == []
assert controller.comparisonEquityNames == ['Trend', 'Ridge']
assert controller.comparisonEquityIndex == 1
assert panel.property('resultsView') == 0
window.findChild(QObject, 'quantComparisonStepPeriods').setProperty('text', '1')
assert QMetaObject.invokeMethod(button, 'clicked', Qt.DirectConnection)
app.processEvents()
assert controller.status == 'VALIDATION_ERROR'
assert len(captured) == 6
assert backend_calls == []
assert session.runtime.backend_if_initialized is None
# Revalidating the same Dataset clears results without changing datasetKey.
# The form must become reachable again even though the result toolbar hides.
assert panel.property('showInputs') is False
assert controller.inspectDataset(str(dataset))
session.runtime._poll()
app.processEvents()
assert controller.comparisonSummary == {{}}
assert panel.property('showInputs') is True
assert window.findChild(QObject, 'quantComparisonFeatures').property('visible')
assert window.findChild(QObject, 'quantComparisonFeatures').property('text') == 'sma_5,rsi_5'
assert window.findChild(QObject, 'quantStrategySelector').property('count') == 4
assert window.findChild(QObject, 'quantStrategyName').property('text') == 'Composite'
assert window.findChild(QObject, 'quantStrategyMatch').property('currentIndex') == 1
assert window.grabWindow().save(str(root_path / 'comparison-strategy-editor-ui.png'))
assert panel.property('resultsView') == 0
assert controller.comparisonEquitySeries == []
assert controller.comparisonEquityModel.rowCount() == 0
assert controller.comparisonRiskModel.rowCount() == 0
assert controller.comparisonBenchmarkSeries == []
for name, key, selected in selections:
    assert window.findChild(QObject, name).property('currentText') == selected
other_dataset = root_path / 'other-dataset'
other_dataset.mkdir()
assert controller.inspectDataset(str(other_dataset))
session.runtime._poll()
app.processEvents()
assert window.findChild(QObject, 'quantComparisonFeatures').property('text') == 'return_2'
assert window.findChild(QObject, 'quantStrategySelector').property('count') == 3
assert window.findChild(QObject, 'quantStrategyName').property('text') == 'Trend'
QTest.qWait(20)
assert find_item('quantConditionFeature0').property('currentText') == 'return_2'
assert window.findChild(QObject, 'quantComparisonReturnLabel').property('currentText') == 'execution_return_1d'
assert controller.comparisonModel.rowCount() == 0
assert controller.comparisonEquityNames == []
assert controller.comparisonEquitySeries == []
assert controller.comparisonEquityModel.rowCount() == 0
assert panel.property('resultsView') == 0
assert panel.property('showInputs') is True
assert session.shutdown()
print(json.dumps({{'clicked': True, 'rows': controller.comparisonModel.rowCount()}}))
'''
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QSG_RHI_BACKEND"] = "software"
    env["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["clicked"] is True
    assert "ReferenceError" not in result.stderr
    assert "TypeError" not in result.stderr
