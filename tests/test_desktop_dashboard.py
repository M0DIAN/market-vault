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


PySide6 = pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication, Qt, QThread

from market_vault.console.models import TablePage
from market_vault.desktop.dashboard import (
    DASHBOARD_METRIC_NAMES,
    DashboardController,
    _production_runner_factory,
)


ROOT = Path(__file__).resolve().parents[1]


class _Runner:
    def __init__(self) -> None:
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.submissions = 0
        self.closed = False

    def submit(self, name, operation):
        assert name == "dashboard"
        self.submissions += 1
        return self.executor.submit(operation)

    def close(self) -> None:
        self.closed = True
        self.executor.shutdown(wait=False, cancel_futures=True)


@pytest.fixture(scope="module")
def qt_app():
    application = QCoreApplication.instance() or QCoreApplication([])
    yield application


def _wait_until(qt_app, predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        qt_app.processEvents()
        if time.monotonic() >= deadline:
            raise AssertionError("Qt condition did not become true before timeout")
        time.sleep(0.005)
    qt_app.processEvents()


def _snapshot(
    *,
    status: str = "SUCCESS",
    rows: tuple[tuple[str, ...], ...] = (("run-1", "SUCCESS"),),
):
    return SimpleNamespace(
        status=status,
        metrics={name: f"value:{index}" for index, name in enumerate(DASHBOARD_METRIC_NAMES)},
        recent_runs=TablePage(
            columns=("run_id", "status"),
            rows=rows,
            page=1,
            page_size=20,
            total_rows=len(rows),
        ),
    )


def test_controller_is_lazy_and_unconfigured_refresh_fails_closed(qt_app, tmp_path):
    backend_calls = []
    runner_calls = []
    controller = DashboardController(
        backend_factory=lambda path: backend_calls.append(path),
        runner_factory=lambda: runner_calls.append(True),
    )
    failures = []
    controller.dashboardFailed.connect(lambda: failures.append(controller.error))

    assert controller.backendConfigured is False
    assert controller.recentRunsModel.rowCount() == 0
    assert controller.status == "UNCONFIGURED"
    assert controller.refresh() is False
    assert controller.status == "FAILED"
    assert controller.busy is False
    assert failures == ["Dashboard settings are not configured."]
    assert backend_calls == []
    assert runner_calls == []
    controller.shutdown()


def test_production_runner_factory_reuses_serial_task_runner():
    from market_vault.console.tasks import SerialTaskRunner

    runner = _production_runner_factory()
    try:
        assert isinstance(runner, SerialTaskRunner)
    finally:
        runner.close()


def test_success_is_consumed_on_controller_thread_and_backend_is_cached(qt_app, tmp_path):
    settings = (tmp_path / "settings.yaml").resolve()
    runner = _Runner()
    backend_threads = []
    created = []
    signal_threads = []

    class Backend:
        def dashboard(self):
            backend_threads.append(QThread.currentThread())
            return _snapshot()

    def backend_factory(path):
        assert path == settings
        created.append(path)
        return Backend()

    controller = DashboardController(
        settings_path=settings,
        backend_factory=backend_factory,
        runner_factory=lambda: runner,
        poll_interval_ms=1,
    )
    controller.metricsChanged.connect(lambda: signal_threads.append(QThread.currentThread()))
    model_identity = controller.recentRunsModel
    loaded_cells = []
    controller.dashboardLoaded.connect(
        lambda: loaded_cells.append(
            controller.recentRunsModel.data(controller.recentRunsModel.index(0, 0))
        )
    )

    assert created == []
    assert controller.refresh() is True
    assert controller.busy is True
    _wait_until(qt_app, lambda: not controller.busy)

    assert controller.status == "SUCCESS"
    assert controller.error == ""
    assert controller.metrics == _snapshot().metrics
    assert created == [settings]
    assert backend_threads[0] != controller.thread()
    assert signal_threads == [controller.thread()]
    assert controller.recentRunsModel is model_identity
    assert controller.recentRunsModel.rowCount() == 1
    assert loaded_cells == ["run-1"]

    assert controller.refresh() is True
    _wait_until(qt_app, lambda: not controller.busy)
    assert created == [settings]
    assert runner.submissions == 2
    assert controller.recentRunsModel is model_identity
    controller.shutdown()
    assert runner.closed is True


def test_slow_operation_blocks_duplicate_refresh(qt_app, tmp_path):
    release = Event()
    runner = _Runner()

    class Backend:
        def dashboard(self):
            assert release.wait(timeout=5)
            return _snapshot()

    controller = DashboardController(
        settings_path=(tmp_path / "settings.yaml").resolve(),
        backend_factory=lambda path: Backend(),
        runner_factory=lambda: runner,
        poll_interval_ms=1,
    )
    assert controller.refresh() is True
    assert controller.refresh() is False
    assert runner.submissions == 1
    release.set()
    _wait_until(qt_app, lambda: not controller.busy)
    controller.shutdown()


def test_failure_is_consumed_on_controller_thread_and_retry_is_safe(qt_app, tmp_path):
    runner = _Runner()
    attempts = 0
    failure_threads = []

    class Backend:
        def dashboard(self):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("dashboard unavailable")
            return _snapshot(status="EMPTY")

    controller = DashboardController(
        settings_path=(tmp_path / "settings.yaml").resolve(),
        backend_factory=lambda path: Backend(),
        runner_factory=lambda: runner,
        poll_interval_ms=1,
    )
    controller.dashboardFailed.connect(
        lambda: failure_threads.append(QThread.currentThread())
    )

    assert controller.refresh() is True
    _wait_until(qt_app, lambda: not controller.busy)
    assert controller.status == "FAILED"
    assert controller.error == "dashboard unavailable"
    assert failure_threads == [controller.thread()]

    assert controller.refresh() is True
    _wait_until(qt_app, lambda: not controller.busy)
    assert controller.status == "EMPTY"
    assert controller.error == ""
    controller.shutdown()


def test_successive_refreshes_reset_same_model_and_failure_retains_last_good(
    qt_app, tmp_path
):
    runner = _Runner()
    attempts = 0

    class Backend:
        def dashboard(self):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return _snapshot(rows=(("run-1", "SUCCESS"),))
            if attempts == 2:
                return _snapshot(
                    rows=(("run-2", "SUCCESS"), ("run-3", "FAILED"))
                )
            raise RuntimeError("later refresh failed")

    controller = DashboardController(
        settings_path=(tmp_path / "settings.yaml").resolve(),
        backend_factory=lambda path: Backend(),
        runner_factory=lambda: runner,
        poll_interval_ms=1,
    )
    model = controller.recentRunsModel
    reset_threads = []
    model.modelReset.connect(lambda: reset_threads.append(QThread.currentThread()))

    controller.refresh()
    _wait_until(qt_app, lambda: not controller.busy)
    assert model.data(model.index(0, 0)) == "run-1"

    controller.refresh()
    _wait_until(qt_app, lambda: not controller.busy)
    assert controller.recentRunsModel is model
    assert model.rowCount() == 2
    assert model.data(model.index(0, 0)) == "run-2"

    controller.refresh()
    _wait_until(qt_app, lambda: not controller.busy)
    assert controller.status == "FAILED"
    assert model.rowCount() == 2
    assert model.data(model.index(0, 0)) == "run-2"
    assert reset_threads == [controller.thread(), controller.thread()]
    controller.shutdown()


def test_shutdown_is_idempotent_after_idle_or_completed_operation(qt_app, tmp_path):
    runner = _Runner()
    controller = DashboardController(
        settings_path=(tmp_path / "settings.yaml").resolve(),
        backend_factory=lambda path: SimpleNamespace(dashboard=_snapshot),
        runner_factory=lambda: runner,
        poll_interval_ms=1,
    )
    controller.refresh()
    _wait_until(qt_app, lambda: not controller.busy)
    controller.shutdown()
    controller.shutdown()
    assert runner.closed is True


def test_controller_construction_with_settings_is_startup_side_effect_free(tmp_path):
    settings = (tmp_path / "config" / "settings.yaml").resolve()
    script = f"""
import json
import sys
from pathlib import Path
from PySide6.QtCore import QCoreApplication
from market_vault.desktop.dashboard import DashboardController
app = QCoreApplication([])
controller = DashboardController(settings_path=Path({str(settings)!r}))
blocked = sorted(name for name in sys.modules if name in {{
    'market_vault.console.backend',
    'market_vault.service',
    'market_vault.storage.catalog',
}})
print(json.dumps(blocked))
controller.shutdown()
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
    assert result.stdout.strip() == "[]"
    assert list(tmp_path.iterdir()) == []


def _write_sandbox_settings(root: Path) -> Path:
    settings = root / "config" / "settings.yaml"
    settings.parent.mkdir(parents=True)
    paths = {
        "data": root / "data",
        "catalog": root / "catalog" / "market_vault.duckdb",
        "manifests": root / "manifests",
        "reports": root / "reports" / "data_quality",
    }
    settings.write_text(
        "\n".join(
            [
                "opend:",
                '  host: "127.0.0.1"',
                "  port: 1",
                "storage:",
                f'  root_dir: "{paths["data"].as_posix()}"',
                f'  catalog_path: "{paths["catalog"].as_posix()}"',
                f'  manifest_dir: "{paths["manifests"].as_posix()}"',
                f'  report_dir: "{paths["reports"].as_posix()}"',
                "collector:",
                "  max_count: 1000",
                '  source: "moomoo"',
                '  source_schema_version: "10.9"',
                '  default_session: "ALL"',
                '  default_adjustment: "NONE"',
                "  request_pause_seconds: 0.0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return settings


def _seed_dashboard_run_history(settings: Path):
    from market_vault.api import MarketVault
    from market_vault.models import DatasetRunManifest, RunManifest

    vault = MarketVault(settings)
    collection = RunManifest(
        requested_trade_date=date(2026, 8, 21),
        requested_symbols=["US.SPY"],
        interval="1m",
        session="ALL",
        adjustment="NONE",
        run_id="qml-3-collection-run",
        started_at=datetime(2026, 8, 21, 19, 0, tzinfo=timezone.utc),
        status="SUCCESS",
        successful_symbols=["US.SPY"],
        row_count=2,
    )
    collection.finished_at = datetime(2026, 8, 21, 20, 0, tzinfo=timezone.utc)
    vault.catalog.record_run(collection)
    dataset = DatasetRunManifest(
        dataset="trading_calendar",
        requested_items=["US"],
        parameters={"fixture": "qml-3"},
        run_id="qml-3-calendar-run",
        started_at=datetime(2026, 8, 21, 19, 1, tzinfo=timezone.utc),
        status="SUCCESS",
        successful_items=["US"],
        row_count=1,
    )
    dataset.finished_at = datetime(2026, 8, 21, 20, 1, tzinfo=timezone.utc)
    vault.catalog.record_dataset_run(dataset)
    return vault


def test_source_dashboard_smoke_uses_real_backend_in_sandbox(tmp_path):
    sandbox = tmp_path / "dashboard sandbox"
    settings = _write_sandbox_settings(sandbox).resolve()
    unrelated_cwd = tmp_path / "unrelated cwd"
    unrelated_cwd.mkdir()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QSG_RHI_BACKEND"] = "software"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "market_vault.desktop.app",
            "--settings",
            str(settings),
            "--dashboard-smoke",
            "--dashboard-smoke-timeout-ms",
            "20000",
        ],
        cwd=unrelated_cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    reports = list((sandbox / "reports" / "data_quality").glob("*.json"))
    assert len(reports) == 1
    assert json.loads(reports[0].read_text(encoding="utf-8"))["status"] == "EMPTY"
    assert (sandbox / "catalog").is_dir()
    assert not (sandbox / "catalog" / "market_vault.duckdb").exists()
    assert not list(sandbox.rglob("*.parquet"))
    assert not (sandbox / "quarantine").exists()
    assert list(unrelated_cwd.iterdir()) == []


def test_source_dashboard_smoke_recent_runs_requirement_fails_on_empty_catalog(
    tmp_path,
):
    sandbox = tmp_path / "empty required dashboard sandbox"
    settings = _write_sandbox_settings(sandbox).resolve()
    unrelated_cwd = tmp_path / "empty required unrelated cwd"
    unrelated_cwd.mkdir()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QSG_RHI_BACKEND"] = "software"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "market_vault.desktop.app",
            "--settings",
            str(settings),
            "--dashboard-smoke",
            "--dashboard-smoke-require-recent-runs",
            "--dashboard-smoke-timeout-ms",
            "20000",
        ],
        cwd=unrelated_cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 5
    assert result.stderr.strip() == "Dashboard smoke requires recent-run rows."
    assert list(unrelated_cwd.iterdir()) == []
    assert not list(sandbox.rglob("*.parquet"))
    assert not (sandbox / "quarantine").exists()


def test_source_dashboard_smoke_requires_seeded_real_run_history(tmp_path):
    sandbox = tmp_path / "nonempty dashboard sandbox"
    settings = _write_sandbox_settings(sandbox).resolve()
    vault = _seed_dashboard_run_history(settings)

    unrelated_cwd = tmp_path / "nonempty unrelated cwd"
    unrelated_cwd.mkdir()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QSG_RHI_BACKEND"] = "software"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "market_vault.desktop.app",
            "--settings",
            str(settings),
            "--dashboard-smoke",
            "--dashboard-smoke-require-recent-runs",
            "--dashboard-smoke-timeout-ms",
            "20000",
        ],
        cwd=unrelated_cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    page = vault.load_run_history_page(page_size=20)
    assert page.total_rows == 2
    assert set(page.data["run_id"]) == {
        "qml-3-collection-run",
        "qml-3-calendar-run",
    }
    assert len(page.data.columns) > 1
    assert list(unrelated_cwd.iterdir()) == []
    assert not list(sandbox.rglob("*.parquet"))
    assert not (sandbox / "quarantine").exists()


def test_real_backend_roundtrip_populates_known_headers_and_cells(qt_app, tmp_path):
    sandbox = tmp_path / "real backend model sandbox"
    settings = _write_sandbox_settings(sandbox).resolve()
    _seed_dashboard_run_history(settings)
    runner = _Runner()
    controller = DashboardController(
        settings_path=settings,
        runner_factory=lambda: runner,
        poll_interval_ms=1,
    )

    assert controller.refresh() is True
    _wait_until(qt_app, lambda: not controller.busy)

    model = controller.recentRunsModel
    assert controller.status == "EMPTY"
    assert model.rowCount() == 2
    assert model.columnCount() == 9
    headers = [
        model.headerData(index, Qt.Orientation.Horizontal)
        for index in range(model.columnCount())
    ]
    assert headers == [
        "run_kind",
        "dataset",
        "run_id",
        "started_at",
        "finished_at",
        "status",
        "row_count",
        "requested_items",
        "errors",
    ]
    run_id_column = headers.index("run_id")
    assert {
        model.data(model.index(row, run_id_column))
        for row in range(model.rowCount())
    } == {"qml-3-collection-run", "qml-3-calendar-run"}
    assert model.totalRows == 2
    controller.shutdown()
