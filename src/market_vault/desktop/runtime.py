"""Shared lazy operation runtime for the PySide6/QML desktop."""

from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Property, QObject, QThread, QTimer, Signal, Slot


POLL_INTERVAL_MS = 20


def _production_backend_factory(settings_path: Path) -> Any:
    from market_vault.console.backend import ConsoleBackend

    return ConsoleBackend.from_settings(settings_path)


def _production_runner_factory() -> Any:
    from market_vault.console.tasks import SerialTaskRunner

    return SerialTaskRunner()


class DesktopOperationRuntime(QObject):
    """Serialize desktop work and publish every completion on the GUI thread."""

    busyChanged = Signal()
    statusChanged = Signal()
    errorChanged = Signal()
    operationStarted = Signal(str)
    operationFinished = Signal(str)

    def __init__(
        self,
        *,
        application_context: Any | None = None,
        settings_path: Path | None = None,
        backend_factory: Callable[[Path], Any] | None = None,
        runner_factory: Callable[[], Any] | None = None,
        poll_interval_ms: int = POLL_INTERVAL_MS,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if application_context is not None and any(
            value is not None
            for value in (settings_path, backend_factory, runner_factory)
        ):
            raise ValueError(
                "Application context cannot be combined with runtime factories."
            )
        if application_context is not None and application_context.closed:
            raise ValueError("Application context is already closed.")
        if application_context is not None:
            settings_path = application_context.settings_path
        if settings_path is not None and not Path(settings_path).is_absolute():
            raise ValueError("Desktop settings path must be absolute.")
        if poll_interval_ms < 1:
            raise ValueError("poll_interval_ms must be positive")
        self._settings_path = Path(settings_path) if settings_path is not None else None
        self._application_context = application_context
        self._backend_factory = backend_factory or _production_backend_factory
        self._runner_factory = runner_factory or _production_runner_factory
        self._backend: Any | None = None
        self._runner: Any | None = None
        self._owns_runner = application_context is None
        self._future: Future[Any] | None = None
        self._success: Callable[[Any], None] | None = None
        self._failure: Callable[[Exception], None] | None = None
        self._active_operation = ""
        self._status = "READY" if self._settings_path is not None else "UNCONFIGURED"
        self._error = ""
        self._closed = False
        self._timer = QTimer(self)
        self._timer.setInterval(poll_interval_ms)
        self._timer.timeout.connect(self._poll)

    def _assert_thread(self) -> None:
        if QThread.currentThread() != self.thread():
            raise RuntimeError("Desktop runtime state must be updated on its owning thread.")

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._future is not None

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @Property(str, notify=errorChanged)
    def error(self) -> str:
        return self._error

    @Property(str, notify=busyChanged)
    def activeOperation(self) -> str:  # noqa: N802
        return self._active_operation

    @Property(bool, constant=True)
    def backendConfigured(self) -> bool:  # noqa: N802
        return self._settings_path is not None

    @property
    def settings_path(self) -> Path | None:
        return self._settings_path

    @property
    def backend_if_initialized(self) -> Any | None:
        return self._backend

    @property
    def application_context(self) -> Any | None:
        return self._application_context

    @property
    def task_runner_if_initialized(self) -> Any | None:
        return self._runner

    def _backend_operation(self, operation: Callable[[Any], Any]) -> Any:
        if self._backend is None:
            if self._application_context is not None:
                self._backend = self._application_context.get_backend()
            elif self._settings_path is None:
                raise RuntimeError("Desktop settings are not configured.")
            else:
                self._backend = self._backend_factory(self._settings_path)
        return operation(self._backend)

    def submit(
        self,
        name: str,
        operation: Callable[[Any], Any],
        success: Callable[[Any], None],
        failure: Callable[[Exception], None],
    ) -> bool:
        self._assert_thread()
        if self._closed or self.busy:
            return False
        if self._settings_path is None:
            exc = RuntimeError("Desktop settings are not configured.")
            self._deliver_failure(failure, exc)
            return False
        self._error = ""
        self._status = "RUNNING"
        self._active_operation = name
        self.errorChanged.emit()
        self.statusChanged.emit()
        try:
            if self._runner is None:
                if self._application_context is not None:
                    self._runner = self._application_context.get_task_runner()
                else:
                    self._runner = self._runner_factory()
            self._future = self._runner.submit(
                name, lambda: self._backend_operation(operation)
            )
        except Exception as exc:
            self._future = None
            self._active_operation = ""
            self._status = "FAILED"
            self._error = str(exc).strip() or exc.__class__.__name__
            self.errorChanged.emit()
            self.statusChanged.emit()
            self._deliver_failure(failure, exc)
            return False
        self._success = success
        self._failure = failure
        self.busyChanged.emit()
        self.operationStarted.emit(name)
        self._timer.start()
        return True

    def _deliver_failure(
        self,
        failure: Callable[[Exception], None] | None,
        exc: Exception,
    ) -> None:
        if failure is None:
            return
        try:
            failure(exc)
        except Exception as callback_exc:
            self._status = "FAILED"
            self._error = (
                str(callback_exc).strip()
                or callback_exc.__class__.__name__
            )

    def _poll(self) -> None:
        self._assert_thread()
        future = self._future
        if future is None or not future.done():
            return
        self._timer.stop()
        name = self._active_operation
        success = self._success
        failure = self._failure
        try:
            result = future.result()
        except Exception as exc:
            self._status = "FAILED"
            self._error = str(exc).strip() or exc.__class__.__name__
            self._deliver_failure(failure, exc)
        else:
            self._status = "SUCCESS"
            self._error = ""
            if success is not None:
                try:
                    success(result)
                except Exception as exc:
                    self._status = "FAILED"
                    self._error = str(exc).strip() or exc.__class__.__name__
                    self._deliver_failure(failure, exc)
        finally:
            self._future = None
            self._success = None
            self._failure = None
            self._active_operation = ""
            self.errorChanged.emit()
            self.statusChanged.emit()
            self.busyChanged.emit()
            self.operationFinished.emit(name)

    @Slot(result=bool)
    def requestShutdown(self) -> bool:  # noqa: N802
        """Close the idle runtime, or veto shutdown while work is active."""

        self._assert_thread()
        if self._closed:
            return True
        if self.busy:
            return False
        self._closed = True
        self._timer.stop()
        if self._runner is not None and self._owns_runner:
            self._runner.close()
        self._runner = None
        return True

    def shutdown(self) -> bool:
        return self.requestShutdown()
