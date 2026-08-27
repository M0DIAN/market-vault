"""Qt-safe dashboard controller for the parallel QML canary."""

from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Property, QObject, QThread, QTimer, Signal, Slot

from market_vault.desktop.table_model import QtTableModel


DASHBOARD_METRIC_NAMES = (
    "Symbols",
    "Snapshots",
    "Latest rows",
    "Completed dates",
    "Incomplete dates",
    "Latest trade date",
)
POLL_INTERVAL_MS = 20


def _production_backend_factory(settings_path: Path) -> Any:
    from market_vault.console.backend import ConsoleBackend

    return ConsoleBackend.from_settings(settings_path)


def _production_runner_factory() -> Any:
    from market_vault.console.tasks import SerialTaskRunner

    return SerialTaskRunner()


class DashboardController(QObject):
    """Run the existing dashboard service off-thread and publish Qt state."""

    busyChanged = Signal()
    statusChanged = Signal()
    errorChanged = Signal()
    metricsChanged = Signal()
    dashboardLoaded = Signal()
    dashboardFailed = Signal()

    def __init__(
        self,
        *,
        settings_path: Path | None = None,
        backend_factory: Callable[[Path], Any] | None = None,
        runner_factory: Callable[[], Any] | None = None,
        poll_interval_ms: int = POLL_INTERVAL_MS,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if settings_path is not None and not Path(settings_path).is_absolute():
            raise ValueError("Dashboard settings path must be absolute.")
        if poll_interval_ms < 1:
            raise ValueError("poll_interval_ms must be positive")

        self._settings_path = Path(settings_path) if settings_path is not None else None
        self._backend_factory = backend_factory or _production_backend_factory
        self._runner_factory = runner_factory or _production_runner_factory
        self._backend: Any | None = None
        self._runner: Any | None = None
        self._future: Future[Any] | None = None
        self._busy = False
        self._status = "READY" if self._settings_path is not None else "UNCONFIGURED"
        self._error = ""
        self._metrics = {name: "-" for name in DASHBOARD_METRIC_NAMES}
        self._recent_runs_model = QtTableModel(parent=self)
        self._closed = False
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(poll_interval_ms)
        self._poll_timer.timeout.connect(self._poll_future)

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
    def recentRunsModel(self) -> QObject:  # noqa: N802 - QML property name
        return self._recent_runs_model

    @Property(bool, constant=True)
    def backendConfigured(self) -> bool:  # noqa: N802 - QML property name
        return self._settings_path is not None

    def _set_busy(self, value: bool) -> None:
        self._assert_controller_thread()
        if self._busy == value:
            return
        self._busy = value
        self.busyChanged.emit()

    def _set_status(self, value: str) -> None:
        self._assert_controller_thread()
        if self._status == value:
            return
        self._status = value
        self.statusChanged.emit()

    def _set_error(self, value: str) -> None:
        self._assert_controller_thread()
        if self._error == value:
            return
        self._error = value
        self.errorChanged.emit()

    def _set_metrics(self, values: dict[str, str]) -> None:
        self._assert_controller_thread()
        if self._metrics == values:
            return
        self._metrics = values
        self.metricsChanged.emit()

    def _dashboard_operation(self) -> Any:
        if self._backend is None:
            if self._settings_path is None:
                raise RuntimeError("Dashboard settings are not configured.")
            self._backend = self._backend_factory(self._settings_path)
        return self._backend.dashboard()

    @Slot(result=bool)
    def refresh(self) -> bool:
        self._assert_controller_thread()
        if self._closed:
            self._finish_failure(RuntimeError("Dashboard controller is closed."))
            return False
        if self._busy:
            return False
        if self._settings_path is None:
            self._finish_failure(RuntimeError("Dashboard settings are not configured."))
            return False

        self._set_error("")
        self._set_status("RUNNING")
        self._set_busy(True)
        try:
            if self._runner is None:
                self._runner = self._runner_factory()
            self._future = self._runner.submit("dashboard", self._dashboard_operation)
        except Exception as exc:
            self._finish_failure(exc)
            return False
        self._poll_timer.start()
        return True

    @Slot()
    def _poll_future(self) -> None:
        self._assert_controller_thread()
        future = self._future
        if future is None or not future.done():
            return
        self._poll_timer.stop()
        self._future = None
        try:
            snapshot = future.result()
        except Exception as exc:
            self._finish_failure(exc)
            return

        try:
            metrics = {
                name: str(snapshot.metrics.get(name, "-"))
                for name in DASHBOARD_METRIC_NAMES
            }
            self._set_metrics(metrics)
            self._recent_runs_model.set_page(snapshot.recent_runs)
        except Exception as exc:
            self._finish_failure(exc)
            return
        self._set_error("")
        self._set_status(str(snapshot.status))
        self._set_busy(False)
        self.dashboardLoaded.emit()

    def _finish_failure(self, exc: Exception) -> None:
        self._assert_controller_thread()
        message = str(exc).strip() or exc.__class__.__name__
        self._poll_timer.stop()
        self._future = None
        self._set_status("FAILED")
        self._set_error(message)
        self._set_busy(False)
        self.dashboardFailed.emit()

    @Slot()
    def shutdown(self) -> None:
        self._assert_controller_thread()
        if self._closed:
            return
        self._closed = True
        self._poll_timer.stop()
        if self._runner is not None:
            self._runner.close()
            self._runner = None
