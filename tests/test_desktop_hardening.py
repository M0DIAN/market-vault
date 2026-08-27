from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
from threading import Event
import time
from types import SimpleNamespace

import pytest


pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication

from market_vault.console.models import PurgePlanView, TablePage
from market_vault.desktop.controllers import (
    HistoricalDataController,
    InventoryController,
    MarketDataController,
    RunsController,
    TradingCalendarController,
)
from market_vault.desktop.dashboard import DASHBOARD_METRIC_NAMES, DashboardController
from market_vault.desktop.localization import I18nBridge
from market_vault.desktop.preferences import DesktopPreferenceStore
from market_vault.desktop.runtime import DesktopOperationRuntime
from market_vault.desktop.storage_cleanup import StorageCleanupController


ROOT = Path(__file__).resolve().parents[1]


class _Runner:
    def __init__(self) -> None:
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.closed = False

    def submit(self, name, operation):
        return self.executor.submit(operation)

    def close(self) -> None:
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


def _page(code: str = "US.SPY") -> TablePage:
    return TablePage(
        columns=("code", "value"),
        rows=((code, "1"),),
        page=1,
        page_size=100,
        total_rows=1,
    )


def _malformed_page() -> TablePage:
    return TablePage(
        columns=("code", "value"),
        rows=(("US.BAD",),),
        page=1,
        page_size=100,
        total_rows=1,
    )


def test_busy_shutdown_veto_preserves_runner_until_completion(qt_app, tmp_path):
    release = Event()
    runner = _Runner()
    runtime = DesktopOperationRuntime(
        settings_path=(tmp_path / "settings.yaml").resolve(),
        backend_factory=lambda path: object(),
        runner_factory=lambda: runner,
        poll_interval_ms=1,
    )

    assert runtime.submit(
        "blocked",
        lambda backend: release.wait(timeout=5) or "done",
        lambda result: None,
        lambda exc: pytest.fail(str(exc)),
    )
    assert runtime.requestShutdown() is False
    assert runner.closed is False
    assert runtime.busy is True

    release.set()
    _wait(qt_app, lambda: not runtime.busy)
    assert runtime.requestShutdown() is True
    assert runtime.requestShutdown() is True
    assert runner.closed is True


@pytest.mark.parametrize("operation_fails", [False, True])
def test_callback_failure_is_contained_and_runtime_recovers(
    qt_app, tmp_path, operation_fails
):
    runner = _Runner()
    runtime = DesktopOperationRuntime(
        settings_path=(tmp_path / "settings.yaml").resolve(),
        backend_factory=lambda path: object(),
        runner_factory=lambda: runner,
        poll_interval_ms=1,
    )
    finished = []
    runtime.operationFinished.connect(finished.append)

    def operation(backend):
        if operation_fails:
            raise RuntimeError("operation failed")
        return "ok"

    def success(result):
        raise RuntimeError("success callback failed")

    def failure(exc):
        raise RuntimeError("failure callback failed")

    assert runtime.submit("first", operation, success, failure)
    _wait(qt_app, lambda: not runtime.busy)
    assert runtime.status == "FAILED"
    assert runtime.error == "failure callback failed"
    assert runtime.activeOperation == ""
    assert finished == ["first"]

    recovered = []
    assert runtime.submit(
        "recovery", lambda backend: "recovered", recovered.append, lambda exc: None
    )
    _wait(qt_app, lambda: not runtime.busy)
    assert recovered == ["recovered"]
    assert runtime.status == "SUCCESS"
    assert finished == ["first", "recovery"]
    runtime.shutdown()


def test_dashboard_malformed_refresh_retains_complete_last_good_state(qt_app, tmp_path):
    runner = _Runner()
    attempts = 0
    good_metrics = {name: f"old:{name}" for name in DASHBOARD_METRIC_NAMES}
    bad_metrics = {name: f"new:{name}" for name in DASHBOARD_METRIC_NAMES}

    class Backend:
        def dashboard(self):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return SimpleNamespace(
                    status="SUCCESS", metrics=good_metrics, recent_runs=_page()
                )
            return SimpleNamespace(
                status="SUCCESS", metrics=bad_metrics, recent_runs=_malformed_page()
            )

    controller = DashboardController(
        settings_path=(tmp_path / "settings.yaml").resolve(),
        backend_factory=lambda path: Backend(),
        runner_factory=lambda: runner,
        poll_interval_ms=1,
    )
    assert controller.refresh()
    _wait(qt_app, lambda: not controller.busy)
    assert controller.metrics == good_metrics
    assert controller.recentRunsModel.data(controller.recentRunsModel.index(0, 0)) == "US.SPY"

    assert controller.refresh()
    _wait(qt_app, lambda: not controller.busy)
    assert controller.status == "FAILED"
    assert controller.metrics == good_metrics
    assert controller.recentRunsModel.data(controller.recentRunsModel.index(0, 0)) == "US.SPY"
    controller.shutdown()


def test_table_and_summary_are_transactional_on_malformed_result(qt_app, tmp_path):
    runner = _Runner()
    attempts = 0

    class Backend:
        def inventory(self, **values):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return {"state": "old"}, _page()
            return {"state": "new"}, _malformed_page()

    runtime = DesktopOperationRuntime(
        settings_path=(tmp_path / "settings.yaml").resolve(),
        backend_factory=lambda path: Backend(),
        runner_factory=lambda: runner,
        poll_interval_ms=1,
    )
    controller = InventoryController(runtime)
    assert controller.refresh({})
    _wait(qt_app, lambda: not runtime.busy)
    assert controller.summary == {"state": "old"}

    assert controller.refresh({})
    _wait(qt_app, lambda: not runtime.busy)
    assert controller.status == "FAILED"
    assert controller.summary == {"state": "old"}
    assert controller.tableModel.data(controller.tableModel.index(0, 0)) == "US.SPY"
    runtime.shutdown()


@pytest.mark.parametrize("page_size", ["", "abc", 0, 1001, float("nan")])
def test_invalid_page_size_slots_fail_without_submission(qt_app, tmp_path, page_size):
    runner = _Runner()

    class Backend:
        def __getattr__(self, name):
            raise AssertionError(f"backend must not be called: {name}")

    runtime = DesktopOperationRuntime(
        settings_path=(tmp_path / "settings.yaml").resolve(),
        backend_factory=lambda path: Backend(),
        runner_factory=lambda: runner,
        poll_interval_ms=1,
    )
    controllers = (
        (MarketDataController(runtime), "query", {"page": 1, "page_size": page_size}),
        (TradingCalendarController(runtime), "query", {"page": 1, "page_size": page_size}),
        (
            TradingCalendarController(runtime),
            "requestCollect",
            {"page": 1, "page_size": page_size},
        ),
        (RunsController(runtime), "refresh", {"page": 1, "page_size": page_size}),
    )
    for controller, method_name, values in controllers:
        assert getattr(controller, method_name)(values) is False
        assert controller.status == "VALIDATION_ERROR"
        assert controller.error
    assert runtime.backend_if_initialized is None
    runtime.shutdown()


@pytest.mark.parametrize(
    "values",
    [
        {"max_retries": "", "retry_backoff_seconds": "2"},
        {"max_retries": "abc", "retry_backoff_seconds": "2"},
        {"max_retries": "2", "retry_backoff_seconds": "abc"},
        {"max_retries": "-1", "retry_backoff_seconds": "2"},
    ],
)
def test_invalid_backfill_numeric_slots_fail_without_submission(qt_app, tmp_path, values):
    runner = _Runner()
    runtime = DesktopOperationRuntime(
        settings_path=(tmp_path / "settings.yaml").resolve(),
        backend_factory=lambda path: pytest.fail("backend must not initialize"),
        runner_factory=lambda: runner,
        poll_interval_ms=1,
    )
    controller = HistoricalDataController(runtime)
    assert controller.plan(values) is False
    assert controller.requestExecute(values) is False
    assert controller.status == "VALIDATION_ERROR"
    assert runtime.backend_if_initialized is None
    runtime.shutdown()


def test_network_confirmation_is_pending_sealed_and_exact(qt_app, tmp_path):
    settings = tmp_path / "settings.yaml"
    settings.write_text('opend:\n  host: "127.0.0.1"\n  port: 11111\n', encoding="utf-8")
    runner = _Runner()
    calls = []

    class Backend:
        def execute_backfill(self, **values):
            calls.append(dict(values))
            return {"status": "SUCCESS"}

    runtime = DesktopOperationRuntime(
        settings_path=settings.resolve(),
        backend_factory=lambda path: Backend(),
        runner_factory=lambda: runner,
        poll_interval_ms=1,
    )
    controller = HistoricalDataController(runtime)
    values = {"symbols": "US.SPY", "max_retries": "2", "retry_backoff_seconds": "1"}
    assert controller.resolveConfirmation(True) is False
    assert controller.requestExecute(values) is True
    assert controller.confirmationPending is True
    values["symbols"] = "US.QQQ"
    assert controller.requestExecute(values) is False
    assert controller.resolveConfirmation(True) is True
    assert controller.confirmationPending is False
    assert controller.resolveConfirmation(True) is False
    _wait(qt_app, lambda: not runtime.busy)
    assert calls[0]["symbols"] == "US.SPY"
    assert controller._request_network("unknown", {}, lambda result: None) is False
    assert controller.status == "VALIDATION_ERROR"
    runtime.shutdown()


def test_storage_malformed_review_retains_last_good_review(qt_app, tmp_path):
    runner = _Runner()
    attempts = 0

    class Backend:
        def preview_purge(self, **scope):
            nonlocal attempts
            attempts += 1
            return PurgePlanView(
                plan_id="plan-good" if attempts == 1 else "plan-bad",
                status="PLANNED",
                executable=True,
                summary={"state": "old" if attempts == 1 else "new"},
                refusal_reasons=(),
                items=_page() if attempts == 1 else _malformed_page(),
            )

        def invalidate_purge_preview(self):
            pass

    runtime = DesktopOperationRuntime(
        settings_path=(tmp_path / "settings.yaml").resolve(),
        backend_factory=lambda path: Backend(),
        runner_factory=lambda: runner,
        poll_interval_ms=1,
    )
    controller = StorageCleanupController(runtime)
    assert controller.review()
    _wait(qt_app, lambda: not runtime.busy)
    assert controller.planId == "plan-good"
    assert controller.review()
    _wait(qt_app, lambda: not runtime.busy)
    assert controller.status == "FAILED"
    assert controller.planId == "plan-good"
    assert controller.summary == {"state": "old"}
    runtime.shutdown()


@pytest.mark.parametrize("scale", ["1.0", "1.25", "1.5", "2.0"])
def test_source_qml_loads_at_supported_scale_from_unrelated_cwd(tmp_path, scale):
    cwd = tmp_path / f"cwd-{scale}"
    cwd.mkdir()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QSG_RHI_BACKEND"] = "software"
    env["QT_SCALE_FACTOR"] = scale
    result = subprocess.run(
        [sys.executable, "-m", "market_vault.desktop.app", "--smoke-exit-ms", "100"],
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert list(cwd.iterdir()) == []


def test_qml_close_keyboard_and_destructive_activation_contracts_are_explicit():
    qml_root = ROOT / "src" / "market_vault" / "desktop" / "qml"
    main = (qml_root / "Main.qml").read_text(encoding="utf-8")
    confirmation = (qml_root / "components" / "OpenDConfirmDialog.qml").read_text(
        encoding="utf-8"
    )
    storage = (qml_root / "pages" / "StorageCleanupPage.qml").read_text(
        encoding="utf-8"
    )
    assert "operationRuntime.requestShutdown()" in main
    assert "close.accepted = false" in main
    assert "closePolicy: Popup.CloseOnEscape" in main
    assert "closePolicy: Popup.CloseOnEscape" in confirmation
    assert "activeFocusOnTab: true" in storage
    assert "Keys.onReturnPressed" not in storage
    assert "Keys.onEnterPressed" not in storage
