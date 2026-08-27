from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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
from PySide6.QtCore import QCoreApplication, QThread

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


def _snapshot(*, status: str = "SUCCESS"):
    return SimpleNamespace(
        status=status,
        metrics={name: f"value:{index}" for index, name in enumerate(DASHBOARD_METRIC_NAMES)},
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

    assert controller.refresh() is True
    _wait_until(qt_app, lambda: not controller.busy)
    assert created == [settings]
    assert runner.submissions == 2
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
