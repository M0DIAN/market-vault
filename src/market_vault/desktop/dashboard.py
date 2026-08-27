"""Qt-safe dashboard controller for the parallel QML desktop."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Property, QObject, QThread, Signal, Slot

from market_vault.desktop.runtime import (
    POLL_INTERVAL_MS,
    DesktopOperationRuntime,
    _production_backend_factory,
    _production_runner_factory,
)
from market_vault.desktop.table_model import QtTableModel


DASHBOARD_METRIC_NAMES = (
    "Symbols",
    "Snapshots",
    "Latest rows",
    "Completed dates",
    "Incomplete dates",
    "Latest trade date",
)


class DashboardController(QObject):
    """Run the existing dashboard service through the shared desktop runtime."""

    busyChanged = Signal()
    statusChanged = Signal()
    errorChanged = Signal()
    metricsChanged = Signal()
    dashboardLoaded = Signal()
    dashboardFailed = Signal()

    def __init__(
        self,
        *,
        runtime: DesktopOperationRuntime | None = None,
        settings_path: Path | None = None,
        backend_factory: Callable[[Path], Any] | None = None,
        runner_factory: Callable[[], Any] | None = None,
        poll_interval_ms: int = POLL_INTERVAL_MS,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if runtime is not None and any(
            value is not None
            for value in (settings_path, backend_factory, runner_factory)
        ):
            raise ValueError("Shared runtime cannot be combined with runtime factories.")
        self._owns_runtime = runtime is None
        self._runtime = runtime or DesktopOperationRuntime(
            settings_path=settings_path,
            backend_factory=backend_factory,
            runner_factory=runner_factory,
            poll_interval_ms=poll_interval_ms,
            parent=self,
        )
        self._busy = False
        self._status = "READY" if self._runtime.backendConfigured else "UNCONFIGURED"
        self._error = ""
        self._metrics = {name: "-" for name in DASHBOARD_METRIC_NAMES}
        self._recent_runs_model = QtTableModel(parent=self)
        self._closed = False

    def _assert_controller_thread(self) -> None:
        if QThread.currentThread() != self.thread():
            raise RuntimeError("Dashboard Qt state must be updated on the controller thread.")

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @Property(str, notify=errorChanged)
    def error(self) -> str:
        return self._error

    @Property("QVariantMap", notify=metricsChanged)
    def metrics(self) -> dict[str, str]:
        return dict(self._metrics)

    @Property(QObject, constant=True)
    def recentRunsModel(self) -> QObject:  # noqa: N802
        return self._recent_runs_model

    @Property(bool, constant=True)
    def backendConfigured(self) -> bool:  # noqa: N802
        return self._runtime.backendConfigured

    def _set_busy(self, value: bool) -> None:
        if self._busy != value:
            self._busy = value
            self.busyChanged.emit()

    def _finish_failure(self, exc: Exception) -> None:
        self._assert_controller_thread()
        self._status = "FAILED"
        self._error = str(exc).strip() or exc.__class__.__name__
        self._set_busy(False)
        self.statusChanged.emit()
        self.errorChanged.emit()
        self.dashboardFailed.emit()

    @Slot(result=bool)
    def refresh(self) -> bool:
        self._assert_controller_thread()
        if self._closed:
            self._finish_failure(RuntimeError("Dashboard controller is closed."))
            return False
        if self._busy or self._runtime.busy:
            return False
        if not self._runtime.backendConfigured:
            self._finish_failure(RuntimeError("Dashboard settings are not configured."))
            return False
        self._status = "RUNNING"
        self._error = ""
        self._set_busy(True)
        self.statusChanged.emit()
        self.errorChanged.emit()

        def apply(snapshot: Any) -> None:
            self._metrics = {
                name: str(snapshot.metrics.get(name, "-"))
                for name in DASHBOARD_METRIC_NAMES
            }
            self._recent_runs_model.set_page(snapshot.recent_runs)
            self._status = str(snapshot.status)
            self._error = ""
            self._set_busy(False)
            self.metricsChanged.emit()
            self.statusChanged.emit()
            self.errorChanged.emit()
            self.dashboardLoaded.emit()

        accepted = self._runtime.submit(
            "dashboard",
            lambda backend: backend.dashboard(),
            apply,
            self._finish_failure,
        )
        if not accepted and self._busy:
            self._set_busy(False)
        return accepted

    @Slot()
    def shutdown(self) -> None:
        self._assert_controller_thread()
        if self._closed:
            return
        self._closed = True
        if self._owns_runtime:
            self._runtime.shutdown()
