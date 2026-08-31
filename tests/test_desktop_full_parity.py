from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event
import time
from types import SimpleNamespace

import pytest
import pandas as pd


pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication, QThread

from market_vault.console.backend import ConsoleBackend
from market_vault.console.models import BackfillPlanView, PurgePlanView, TablePage
from market_vault.desktop.controllers import (
    AuditController,
    HistoricalDataController,
    InventoryController,
    MarketDataController,
    RunsController,
    TradingCalendarController,
)
from market_vault.desktop.runtime import DesktopOperationRuntime
from market_vault.desktop.storage_cleanup import StorageCleanupController
from market_vault.api import MarketVault
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars
from market_vault.storage import Catalog, ParquetStore


ROOT = Path(__file__).resolve().parents[1]


class _Runner:
    def __init__(self) -> None:
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.submissions: list[str] = []
        self.closed = False

    def submit(self, name, operation):
        self.submissions.append(name)
        return self.executor.submit(operation)

    def close(self):
        self.closed = True
        self.executor.shutdown(wait=False, cancel_futures=True)


@pytest.fixture(scope="module")
def qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


def _wait(qt_app, predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        qt_app.processEvents()
        if time.monotonic() >= deadline:
            raise AssertionError("Qt condition did not become true")
        time.sleep(0.005)
    qt_app.processEvents()


def _settings(path: Path) -> Path:
    path.parent.mkdir(parents=True)
    path.write_text(
        "\n".join(
            (
                "opend:",
                '  host: "127.0.0.9"',
                "  port: 22334",
                "storage:",
                f'  root_dir: "{(path.parent / "data").as_posix()}"',
                "collector:",
                '  source: "moomoo"',
                '  source_schema_version: "10.9"',
                "",
            )
        ),
        encoding="utf-8",
    )
    return path.resolve()


def _page(page: int = 1, total: int = 2) -> TablePage:
    return TablePage(
        columns=("code", "value"),
        rows=((f"US.PAGE{page}", str(page)),),
        page=page,
        page_size=1,
        total_rows=total,
    )


def test_runtime_is_lazy_global_serial_and_applies_on_gui_thread(qt_app, tmp_path):
    release = Event()
    runner = _Runner()
    created = []
    worker_threads = []
    applied_threads = []

    class Backend:
        pass

    runtime = DesktopOperationRuntime(
        settings_path=(tmp_path / "settings.yaml").resolve(),
        backend_factory=lambda path: created.append(path) or Backend(),
        runner_factory=lambda: runner,
        poll_interval_ms=1,
    )

    assert runtime.backendConfigured is True
    assert runtime.backend_if_initialized is None
    assert runner.submissions == []

    def operation(backend):
        assert isinstance(backend, Backend)
        worker_threads.append(QThread.currentThread())
        assert release.wait(timeout=5)
        return "ok"

    assert runtime.submit(
        "first",
        operation,
        lambda result: applied_threads.append(QThread.currentThread()),
        lambda exc: pytest.fail(str(exc)),
    )
    assert runtime.busy is True
    assert runtime.submit("second", lambda backend: None, lambda value: None, lambda exc: None) is False
    release.set()
    _wait(qt_app, lambda: not runtime.busy)

    assert created == [(tmp_path / "settings.yaml").resolve()]
    assert runner.submissions == ["first"]
    assert worker_threads == [worker_threads[0]]
    assert worker_threads[0] != runtime.thread()
    assert applied_threads == [runtime.thread()]
    runtime.shutdown()
    runtime.shutdown()
    assert runner.closed is True


def test_runtime_failure_recovers_without_recreating_backend(qt_app, tmp_path):
    runner = _Runner()
    attempts = 0
    created = 0
    errors = []

    class Backend:
        pass

    def factory(path):
        nonlocal created
        created += 1
        return Backend()

    runtime = DesktopOperationRuntime(
        settings_path=(tmp_path / "settings.yaml").resolve(),
        backend_factory=factory,
        runner_factory=lambda: runner,
        poll_interval_ms=1,
    )

    def operation(backend):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("expected failure")
        return "recovered"

    assert runtime.submit("failure", operation, lambda value: None, errors.append)
    _wait(qt_app, lambda: not runtime.busy)
    assert runtime.status == "FAILED"
    assert str(errors[0]) == "expected failure"

    results = []
    assert runtime.submit("retry", operation, results.append, errors.append)
    _wait(qt_app, lambda: not runtime.busy)
    assert results == ["recovered"]
    assert created == 1
    runtime.shutdown()


def test_network_confirmation_is_single_use_and_reject_is_zero_calls(qt_app, tmp_path):
    settings = _settings(tmp_path / "config" / "settings.yaml")
    runner = _Runner()

    class Backend:
        def __init__(self):
            self.calendar_calls = 0
            self.calendar_queries = 0
            self.backfill_calls = 0

        def collect_calendar(self, **values):
            self.calendar_calls += 1
            return {"status": "SUCCESS"}

        def query_calendar(self, **values):
            self.calendar_queries += 1
            return _page()

        def execute_backfill(self, **values):
            self.backfill_calls += 1
            return {"status": "SUCCESS", "run_id": "run-1"}

    backend = Backend()
    runtime = DesktopOperationRuntime(
        settings_path=settings,
        backend_factory=lambda path: backend,
        runner_factory=lambda: runner,
        poll_interval_ms=1,
    )
    calendar = TradingCalendarController(runtime)
    historical = HistoricalDataController(runtime)
    prompts = []
    calendar.confirmationRequested.connect(
        lambda operation, host, port: prompts.append((operation, host, port))
    )

    calendar_values = {
        "market": "US",
        "code": "",
        "start_date": "2026-08-01",
        "end_date": "2026-08-02",
        "page": 1,
        "page_size": 1,
    }
    assert calendar.requestCollect(calendar_values)
    assert backend.calendar_calls == 0
    assert prompts == [("calendar_collect", "127.0.0.9", 22334)]
    assert calendar.resolveConfirmation(False) is False
    assert backend.calendar_calls == 0

    assert calendar.requestCollect(calendar_values)
    assert calendar.resolveConfirmation(True)
    assert calendar.resolveConfirmation(True) is False
    _wait(qt_app, lambda: not runtime.busy and backend.calendar_queries == 1)
    assert backend.calendar_calls == 1

    backfill_values = {
        "symbols": "US.SPY",
        "end_date": "2026-08-02",
        "calendar_market": "US",
        "calendar_code": "",
        "interval": "1m",
        "session": "ALL",
        "adjustment": "NONE",
        "max_retries": 2,
        "retry_backoff_seconds": 2.0,
    }
    assert historical.requestExecute(backfill_values)
    assert backend.backfill_calls == 0
    assert historical.resolveConfirmation(False) is False
    assert historical.requestExecute(backfill_values)
    assert historical.resolveConfirmation(True)
    _wait(qt_app, lambda: not runtime.busy)
    assert backend.backfill_calls == 1
    runtime.shutdown()


def test_pagination_keeps_model_and_last_good_page_on_failure(qt_app, tmp_path):
    runner = _Runner()
    calls = []

    class Backend:
        def query_bars(self, **values):
            calls.append(dict(values))
            if values["page"] == 2 and len(calls) > 2:
                raise RuntimeError("page unavailable")
            return _page(values["page"])

    runtime = DesktopOperationRuntime(
        settings_path=(tmp_path / "settings.yaml").resolve(),
        backend_factory=lambda path: Backend(),
        runner_factory=lambda: runner,
        poll_interval_ms=1,
    )
    controller = MarketDataController(runtime)
    model = controller.tableModel
    values = {
        "code": "US.SPY",
        "interval": "1m",
        "adjustment": "NONE",
        "page": 1,
        "page_size": 1,
    }
    assert controller.query(values)
    _wait(qt_app, lambda: not runtime.busy)
    assert controller.page == 1
    assert controller.previousPage() is False
    assert controller.nextPage()
    _wait(qt_app, lambda: not runtime.busy)
    assert controller.page == 2
    assert controller.tableModel is model
    assert controller.nextPage() is False
    assert controller.previousPage()
    _wait(qt_app, lambda: not runtime.busy)
    assert controller.page == 1
    assert controller.nextPage()
    _wait(qt_app, lambda: not runtime.busy)
    assert controller.status == "FAILED"
    assert controller.page == 1
    assert model.data(model.index(0, 0)) == "US.PAGE1"
    assert all(call["code"] == "US.SPY" for call in calls)
    runtime.shutdown()


def test_storage_review_scope_invalidation_and_exact_execution(qt_app, tmp_path):
    runner = _Runner()

    class Backend:
        def __init__(self):
            self.invalidations = 0
            self.executions = []
            self.review_scopes = []

        def preview_purge(self, **scope):
            self.review_scopes.append(scope)
            return PurgePlanView(
                plan_id="plan-1",
                status="PLANNED",
                executable=True,
                summary={"targets": 1},
                refusal_reasons=(),
                items=_page(total=1),
            )

        def invalidate_purge_preview(self):
            self.invalidations += 1

        def execute_purge(self, *, plan_id, confirmation):
            self.executions.append((plan_id, confirmation))
            return {"status": "SUCCESS", "plan_id": plan_id}

    backend = Backend()
    runtime = DesktopOperationRuntime(
        settings_path=(tmp_path / "settings.yaml").resolve(),
        backend_factory=lambda path: backend,
        runner_factory=lambda: runner,
        poll_interval_ms=1,
    )
    controller = StorageCleanupController(runtime)
    controller.setScopeField("start_date", "2026-08-01")
    controller.setScopeField("end_date", "2026-08-01")
    assert controller.review()
    _wait(qt_app, lambda: not runtime.busy)
    assert controller.planId == "plan-1"
    assert controller.planExecutable is True
    assert controller.executeEnabled is False
    assert backend.review_scopes[-1]["cleanup_policy"] == "EXACT_SCOPE"

    controller.setConfirmation("PURGE plan-1")
    assert controller.executeEnabled is True
    controller.setScopeField("cleanup_policy", "SUPERSEDED_ONLY")
    assert controller.planId == ""
    assert controller.confirmation == ""
    assert controller.executeEnabled is False
    assert backend.invalidations == 1

    assert controller.review()
    _wait(qt_app, lambda: not runtime.busy)
    assert backend.review_scopes[-1]["cleanup_policy"] == "SUPERSEDED_ONLY"
    controller.setConfirmation("PURGE plan-1")
    assert controller.execute_purge("wrong-plan", "PURGE plan-1") is False
    assert backend.executions == []

    controller.setScopeField("symbols", "US.QQQ")
    assert controller.planId == ""
    assert controller.confirmation == ""
    assert controller.executeEnabled is False
    assert backend.invalidations == 2

    assert controller.review()
    _wait(qt_app, lambda: not runtime.busy)
    controller.setConfirmation("PURGE plan-1")
    assert controller.execute_purge("plan-1", "PURGE plan-1")
    _wait(qt_app, lambda: not runtime.busy)
    assert backend.executions == [("plan-1", "PURGE plan-1")]
    assert controller.planExecutable is False
    runtime.shutdown()


def test_storage_discards_review_completed_after_scope_change(qt_app, tmp_path):
    release = Event()
    runner = _Runner()

    class Backend:
        def __init__(self):
            self.invalidations = 0

        def preview_purge(self, **scope):
            assert release.wait(timeout=5)
            return PurgePlanView(
                plan_id="stale-plan",
                status="PLANNED",
                executable=True,
                summary={},
                refusal_reasons=(),
                items=_page(total=1),
            )

        def invalidate_purge_preview(self):
            self.invalidations += 1

    backend = Backend()
    runtime = DesktopOperationRuntime(
        settings_path=(tmp_path / "settings.yaml").resolve(),
        backend_factory=lambda path: backend,
        runner_factory=lambda: runner,
        poll_interval_ms=1,
    )
    controller = StorageCleanupController(runtime)
    assert controller.review()
    assert controller.setScopeField("symbols", "US.QQQ")
    release.set()
    _wait(qt_app, lambda: not runtime.busy)
    assert controller.status == "FAILED"
    assert controller.planId == ""
    assert controller.executeEnabled is False
    assert backend.invalidations == 1
    runtime.shutdown()


def test_desktop_controller_construction_does_not_import_business_stack(tmp_path):
    script = """
import json
from PySide6.QtCore import QCoreApplication
from market_vault.desktop.controllers import AuditController, HistoricalDataController, InventoryController, MarketDataController, RunsController, TradingCalendarController
from market_vault.desktop.dashboard import DashboardController
from market_vault.desktop.runtime import DesktopOperationRuntime
from market_vault.desktop.storage_cleanup import StorageCleanupController
app = QCoreApplication([])
runtime = DesktopOperationRuntime()
controllers = [DashboardController(runtime=runtime), HistoricalDataController(runtime), TradingCalendarController(runtime), MarketDataController(runtime), InventoryController(runtime), AuditController(runtime, method_name='coverage_audit'), RunsController(runtime), StorageCleanupController(runtime)]
import sys
blocked = sorted(name for name in sys.modules if name in {'market_vault.console.backend', 'market_vault.api', 'market_vault.storage.catalog'})
print(json.dumps(blocked))
runtime.shutdown()
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []
    assert list(tmp_path.iterdir()) == []


def test_backfill_plan_model_uses_existing_backend_view(qt_app, tmp_path):
    runner = _Runner()

    class Backend:
        def plan_backfill(self, **values):
            return BackfillPlanView(
                scope="MARKET:US",
                symbols=("US.SPY",),
                trading_date_count=2,
                pending_count=1,
                skipped_count=1,
                items=_page(total=1),
            )

    runtime = DesktopOperationRuntime(
        settings_path=(tmp_path / "settings.yaml").resolve(),
        backend_factory=lambda path: Backend(),
        runner_factory=lambda: runner,
        poll_interval_ms=1,
    )
    controller = HistoricalDataController(runtime)
    model = controller.planModel
    assert controller.plan({"symbols": "US.SPY", "end_date": "2026-08-01"})
    _wait(qt_app, lambda: not runtime.busy)
    assert controller.planModel is model
    assert controller.summary["pending"] == "1"
    assert model.rowCount() == 1
    runtime.shutdown()


def test_all_local_page_controllers_delegate_without_network(qt_app, tmp_path):
    runner = _Runner()
    calls = []

    class Backend:
        def inventory(self, **values):
            calls.append("inventory")
            return {"symbol_count": 1}, _page(total=1)

        def coverage_audit(self, **values):
            calls.append("coverage_audit")
            return {"status": "PASS"}, _page(total=1)

        def intraday_audit(self, **values):
            calls.append("intraday_audit")
            return {"status": "WARN"}, _page(total=1)

        def runs(self, **values):
            calls.append("runs")
            return _page(total=1)

    runtime = DesktopOperationRuntime(
        settings_path=(tmp_path / "settings.yaml").resolve(),
        backend_factory=lambda path: Backend(),
        runner_factory=lambda: runner,
        poll_interval_ms=1,
    )
    inventory = InventoryController(runtime)
    coverage = AuditController(runtime, method_name="coverage_audit")
    intraday = AuditController(runtime, method_name="intraday_audit")
    runs = RunsController(runtime)

    assert inventory.refresh({})
    _wait(qt_app, lambda: not runtime.busy)
    assert coverage.run({})
    _wait(qt_app, lambda: not runtime.busy)
    assert intraday.run({})
    _wait(qt_app, lambda: not runtime.busy)
    assert runs.refresh({"page": 1, "page_size": 1})
    _wait(qt_app, lambda: not runtime.busy)

    assert calls == ["inventory", "coverage_audit", "intraday_audit", "runs"]
    assert inventory.summary == {"symbol_count": "1"}
    assert coverage.summary == {"status": "PASS"}
    assert intraday.summary == {"status": "WARN"}
    assert runs.tableModel.rowCount() == 1
    runtime.shutdown()


def test_export_uses_existing_backend_and_rejects_non_local_destinations(
    qt_app, tmp_path
):
    runner = _Runner()
    export_backend = ConsoleBackend(SimpleNamespace())

    class Backend:
        def query_bars(self, **values):
            return _page(total=1)

        def export_page(self, table, destination, format_name):
            return export_backend.export_page(table, destination, format_name)

    runtime = DesktopOperationRuntime(
        settings_path=(tmp_path / "settings.yaml").resolve(),
        backend_factory=lambda path: Backend(),
        runner_factory=lambda: runner,
        poll_interval_ms=1,
    )
    controller = MarketDataController(runtime)
    assert controller.query(
        {"code": "US.SPY", "page": 1, "page_size": 1, "adjustment": "NONE"}
    )
    _wait(qt_app, lambda: not runtime.busy)

    csv_path = (tmp_path / "loaded page.csv").resolve()
    json_path = (tmp_path / "loaded page.json").resolve()
    assert controller.exportPage(str(csv_path), "csv")
    _wait(qt_app, lambda: not runtime.busy)
    assert controller.exportPage(json_path.as_uri(), "json")
    _wait(qt_app, lambda: not runtime.busy)
    assert csv_path.read_text(encoding="utf-8-sig").splitlines()[1] == "US.PAGE1,1"
    assert json.loads(json_path.read_text(encoding="utf-8")) == [
        {"code": "US.PAGE1", "value": "1"}
    ]

    assert controller.exportPage("https://example.com/result.csv", "csv") is False
    assert controller.exportPage("", "csv") is False
    missing = (tmp_path / "missing" / "result.csv").resolve()
    assert controller.exportPage(str(missing), "csv")
    _wait(qt_app, lambda: not runtime.busy)
    assert controller.status == "FAILED"
    assert not missing.exists()
    runtime.shutdown()


def test_real_local_backend_roundtrip_through_all_read_controllers(qt_app, tmp_path):
    cfg = Settings(
        project_root=tmp_path,
        opend_host="127.0.0.1",
        opend_port=1,
        data_root=tmp_path / "data",
        catalog_path=tmp_path / "catalog" / "market_vault.duckdb",
        manifest_dir=tmp_path / "manifests",
        report_dir=tmp_path / "reports" / "data_quality",
        request_pause_seconds=0,
    )
    trade_date = date(2026, 7, 1)
    run_id = "qml-local-run"
    raw = pd.DataFrame(
        {
            "code": ["US.SPY", "US.SPY"],
            "name": ["SPY", "SPY"],
            "time_key": ["2026-07-01 09:30:00", "2026-07-01 09:31:00"],
            "open": [100.0, 100.5],
            "high": [101.0, 101.5],
            "low": [99.0, 99.5],
            "close": [100.5, 101.0],
            "volume": [100, 120],
            "requested_trade_date": [trade_date, trade_date],
            "interval": ["1m", "1m"],
            "adjustment": ["NONE", "NONE"],
            "requested_session": ["ALL", "ALL"],
            "ingestion_run_id": [run_id, run_id],
        }
    )
    curated = normalize_bars(
        raw,
        requested_trade_date=trade_date,
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source=cfg.source,
        source_schema_version=cfg.source_schema_version,
        run_id=run_id,
    )
    store = ParquetStore(cfg)
    raw_path = store.write_raw(
        raw, trade_date, "1m", ["US.SPY"], "ALL", "NONE", run_id
    )
    curated_path = store.write_curated(
        curated, trade_date, "1m", ["US.SPY"], "ALL", "NONE", run_id
    )
    manifest = RunManifest(
        requested_trade_date=trade_date,
        requested_symbols=["US.SPY"],
        interval="1m",
        session="ALL",
        adjustment="NONE",
        run_id=run_id,
        status="SUCCESS",
        successful_symbols=["US.SPY"],
        raw_file=str(raw_path),
        curated_file=str(curated_path),
        row_count=2,
        finished_at=datetime(2026, 7, 2, tzinfo=timezone.utc),
    )
    catalog = Catalog(cfg)
    catalog.record_run(manifest)
    catalog.record_quality(run_id, [QualityResult("qml_fixture", "PASS")])
    catalog.refresh_market_bars_view()

    calendar_root = (
        cfg.data_root
        / "curated"
        / "trading_calendar"
        / "scope_type=MARKET"
        / "scope_value=US"
        / "start_date=2026-07-01"
        / "end_date=2026-07-01"
    )
    calendar_root.mkdir(parents=True)
    pd.DataFrame(
        {
            "scope_type": ["MARKET"],
            "scope_value": ["US"],
            "market": ["US"],
            "reference_code": [None],
            "trade_date": [trade_date],
            "trade_date_type": ["WHOLE"],
            "requested_start_date": [trade_date],
            "requested_end_date": [trade_date],
            "captured_at": [pd.Timestamp("2026-07-02", tz="UTC")],
            "source": [cfg.source],
            "source_schema_version": [cfg.source_schema_version],
            "ingestion_run_id": ["calendar-run"],
        }
    ).to_parquet(calendar_root / "calendar.parquet", index=False)
    assert catalog.refresh_trading_calendar_views()

    backend = ConsoleBackend(MarketVault(cfg))
    runner = _Runner()
    runtime = DesktopOperationRuntime(
        settings_path=(tmp_path / "settings.yaml").resolve(),
        backend_factory=lambda path: backend,
        runner_factory=lambda: runner,
        poll_interval_ms=1,
    )
    from market_vault.desktop.dashboard import DashboardController

    dashboard = DashboardController(runtime=runtime)
    historical = HistoricalDataController(runtime)
    calendar = TradingCalendarController(runtime)
    market = MarketDataController(runtime)
    inventory = InventoryController(runtime)
    coverage = AuditController(runtime, method_name="coverage_audit")
    intraday = AuditController(runtime, method_name="intraday_audit")
    runs = RunsController(runtime)

    assert dashboard.refresh()
    _wait(qt_app, lambda: not runtime.busy)
    assert historical.plan(
        {
            "symbols": "US.SPY",
            "start_date": "2026-07-01",
            "end_date": "2026-07-01",
            "calendar_market": "US",
            "interval": "1m",
            "session": "ALL",
            "adjustment": "NONE",
        }
    )
    _wait(qt_app, lambda: not runtime.busy)
    assert calendar.query(
        {"market": "US", "page": 1, "page_size": 100}
    )
    _wait(qt_app, lambda: not runtime.busy)
    assert market.query(
        {"code": "US.SPY", "page": 1, "page_size": 100, "adjustment": "NONE"}
    )
    _wait(qt_app, lambda: not runtime.busy)
    assert inventory.refresh(
        {"symbols": "US.SPY", "start_date": "2026-07-01", "end_date": "2026-07-01"}
    )
    _wait(qt_app, lambda: not runtime.busy)
    audit_values = {
        "symbols": "US.SPY",
        "start_date": "2026-07-01",
        "end_date": "2026-07-01",
        "calendar_market": "US",
        "calendar_code": "",
        "interval": "1m",
        "session": "ALL",
        "adjustment": "NONE",
    }
    assert coverage.run(audit_values)
    _wait(qt_app, lambda: not runtime.busy)
    assert intraday.run(audit_values)
    _wait(qt_app, lambda: not runtime.busy)
    assert runs.refresh({"page": 1, "page_size": 100})
    _wait(qt_app, lambda: not runtime.busy)

    assert dashboard.metrics["Symbols"] == "1"
    assert historical.summary["skipped"] == "1"
    assert calendar.tableModel.rowCount() == 1
    assert market.tableModel.rowCount() == 2
    assert inventory.tableModel.rowCount() == 1
    assert coverage.summary["status"] in {"PASS", "WARN"}
    assert intraday.summary["status"] in {"PASS", "WARN"}
    assert runs.tableModel.rowCount() >= 1
    assert not list(tmp_path.rglob("quarantine"))
    runtime.shutdown()
