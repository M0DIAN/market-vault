"""Non-destructive page controllers for the QML desktop."""

from __future__ import annotations

from collections.abc import Mapping
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from PySide6.QtCore import Property, QObject, QThread, QTimer, QUrl, Signal, Slot

from market_vault.desktop.runtime import DesktopOperationRuntime
from market_vault.desktop.table_model import QtTableModel, validate_table_page


if TYPE_CHECKING:
    from market_vault.console.models import TablePage


def _values(values: dict[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in dict(values).items()}


def _bounded_int(value: Any, field_name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        raise ValueError(f"{field_name} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{field_name} must be between {minimum} and {maximum}")
    return parsed


def _nonnegative_float(value: Any, field_name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} must be a non-negative number") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(f"{field_name} must be a non-negative number")
    return parsed


def _summary_values(summary: Any) -> dict[str, str]:
    if not isinstance(summary, Mapping):
        raise TypeError("result summary must be a mapping")
    return {str(key): str(value) for key, value in summary.items()}


def _paged_values(values: dict[str, Any]) -> tuple[dict[str, Any], int]:
    arguments = _values(values)
    page = _bounded_int(arguments.get("page", 1), "page", 1, 2_147_483_647)
    arguments["page"] = page
    arguments["page_size"] = _bounded_int(
        arguments.get("page_size", 100), "page_size", 1, 1000
    )
    return arguments, page


def _backfill_values(values: dict[str, Any]) -> dict[str, Any]:
    arguments = _values(values)
    arguments["max_retries"] = _bounded_int(
        arguments.get("max_retries", 2), "max_retries", 0, 2_147_483_647
    )
    arguments["retry_backoff_seconds"] = _nonnegative_float(
        arguments.get("retry_backoff_seconds", 2.0), "retry_backoff_seconds"
    )
    return arguments


class PageController(QObject):
    stateChanged = Signal()
    operationSucceeded = Signal()
    operationFailed = Signal()

    def __init__(self, runtime: DesktopOperationRuntime, *, parent: QObject | None = None):
        super().__init__(parent)
        self._runtime = runtime
        self._busy = False
        self._status = "READY"
        self._error = ""
        self._summary: dict[str, str] = {}

    def _assert_thread(self) -> None:
        if QThread.currentThread() != self.thread():
            raise RuntimeError("Page controller state must be updated on its owning thread.")

    @Property(bool, notify=stateChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=stateChanged)
    def status(self) -> str:
        return self._status

    @Property(str, notify=stateChanged)
    def error(self) -> str:
        return self._error

    @Property("QVariantMap", notify=stateChanged)
    def summary(self) -> dict[str, str]:
        return dict(self._summary)

    def _submit(
        self,
        name: str,
        operation: Callable[[Any], Any],
        apply: Callable[[Any], None],
    ) -> bool:
        self._assert_thread()
        if self._busy or self._runtime.busy:
            return False
        self._busy = True
        self._status = "RUNNING"
        self._error = ""
        self.stateChanged.emit()

        def success(result: Any) -> None:
            self._assert_thread()
            apply(result)
            self._busy = False
            self._status = "SUCCESS"
            self._error = ""
            self.stateChanged.emit()
            self.operationSucceeded.emit()

        def failure(exc: Exception) -> None:
            self._assert_thread()
            self._busy = False
            self._status = "FAILED"
            self._error = str(exc).strip() or exc.__class__.__name__
            self.stateChanged.emit()
            self.operationFailed.emit()

        accepted = self._runtime.submit(name, operation, success, failure)
        if not accepted and self._busy:
            self._busy = False
            if not self._error:
                self._status = "BUSY" if self._runtime.busy else "FAILED"
            self.stateChanged.emit()
        return accepted

    def _reject_input(self, exc: Exception) -> bool:
        self._assert_thread()
        self._status = "VALIDATION_ERROR"
        self._error = str(exc).strip() or exc.__class__.__name__
        self.stateChanged.emit()
        return False


class TablePageController(PageController):
    pageChanged = Signal()

    def __init__(self, runtime: DesktopOperationRuntime, *, parent: QObject | None = None):
        super().__init__(runtime, parent=parent)
        self._model = QtTableModel(parent=self)
        self._page: TablePage | None = None
        self._last_values: dict[str, Any] = {}

    @Property(QObject, constant=True)
    def tableModel(self) -> QObject:  # noqa: N802
        return self._model

    @Property(int, notify=pageChanged)
    def page(self) -> int:
        return self._page.page if self._page is not None else 1

    @Property(int, notify=pageChanged)
    def totalPages(self) -> int:  # noqa: N802
        return self._page.total_pages if self._page is not None else 1

    @Property(int, notify=pageChanged)
    def totalRows(self) -> int:  # noqa: N802
        return self._page.total_rows if self._page is not None else 0

    @Property(bool, notify=pageChanged)
    def hasPrevious(self) -> bool:  # noqa: N802
        return self._page.has_previous if self._page is not None else False

    @Property(bool, notify=pageChanged)
    def hasNext(self) -> bool:  # noqa: N802
        return self._page.has_next if self._page is not None else False

    def _set_page(self, page: TablePage) -> None:
        validate_table_page(page)
        self._model.set_page(page)
        self._page = page
        self.pageChanged.emit()

    @Slot(str, str, result=bool)
    def exportPage(self, destination: str, format_name: str) -> bool:  # noqa: N802
        if self._page is None:
            self._status = "FAILED"
            self._error = "Load a table page before exporting."
            self.stateChanged.emit()
            return False
        try:
            text = destination.strip()
            direct_path = Path(text).expanduser()
            url = QUrl(text)
            if direct_path.is_absolute():
                path = direct_path
            elif url.scheme():
                if not url.isLocalFile():
                    path = Path()
                else:
                    path = Path(url.toLocalFile())
            else:
                path = direct_path
        except (AttributeError, OSError, TypeError, ValueError) as exc:
            return self._reject_input(exc)
        if not text or not path.is_absolute():
            return self._reject_input(
                ValueError("Export destination must be an absolute local path.")
            )
        loaded_page = self._page
        return self._submit(
            "export",
            lambda backend: backend.export_page(loaded_page, path, format_name),
            lambda result: setattr(
                self, "_summary", {"path": result.path, "rows": str(result.row_count)}
            ),
        )


class MarketDataController(TablePageController):
    @Slot("QVariantMap", result=bool)
    def query(self, values: dict[str, Any]) -> bool:
        try:
            arguments, page = _paged_values(values)
        except (TypeError, ValueError) as exc:
            return self._reject_input(exc)
        self._last_values = arguments
        return self._query_page(page)

    def _query_page(self, page: int) -> bool:
        values = dict(self._last_values)
        values["page"] = page
        return self._submit(
            "market_data",
            lambda backend: backend.query_bars(**values),
            self._set_page,
        )

    @Slot(result=bool)
    def previousPage(self) -> bool:  # noqa: N802
        return self.hasPrevious and self._query_page(self.page - 1)

    @Slot(result=bool)
    def nextPage(self) -> bool:  # noqa: N802
        return self.hasNext and self._query_page(self.page + 1)


class InventoryController(TablePageController):
    @Slot("QVariantMap", result=bool)
    def refresh(self, values: dict[str, Any]) -> bool:
        try:
            arguments = _values(values)
        except (TypeError, ValueError) as exc:
            return self._reject_input(exc)

        def apply(result: tuple[dict[str, Any], TablePage]) -> None:
            summary, page = result
            prepared_summary = _summary_values(summary)
            validate_table_page(page)
            self._summary = prepared_summary
            self._set_page(page)

        return self._submit(
            "inventory", lambda backend: backend.inventory(**arguments), apply
        )


class AuditController(TablePageController):
    def __init__(
        self,
        runtime: DesktopOperationRuntime,
        *,
        method_name: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(runtime, parent=parent)
        self._method_name = method_name

    @Slot("QVariantMap", result=bool)
    def run(self, values: dict[str, Any]) -> bool:
        try:
            arguments = _values(values)
        except (TypeError, ValueError) as exc:
            return self._reject_input(exc)

        def operation(backend: Any) -> Any:
            return getattr(backend, self._method_name)(**arguments)

        def apply(result: tuple[dict[str, Any], TablePage]) -> None:
            summary, page = result
            prepared_summary = _summary_values(summary)
            validate_table_page(page)
            self._summary = prepared_summary
            self._set_page(page)

        return self._submit(self._method_name, operation, apply)


class RunsController(TablePageController):
    @Slot("QVariantMap", result=bool)
    def refresh(self, values: dict[str, Any]) -> bool:
        try:
            arguments, page = _paged_values(values)
        except (TypeError, ValueError) as exc:
            return self._reject_input(exc)
        self._last_values = arguments
        return self._query_page(page)

    def _query_page(self, page: int) -> bool:
        values = dict(self._last_values)
        values["page"] = page
        return self._submit(
            "runs", lambda backend: backend.runs(**values), self._set_page
        )

    @Slot(result=bool)
    def previousPage(self) -> bool:  # noqa: N802
        return self.hasPrevious and self._query_page(self.page - 1)

    @Slot(result=bool)
    def nextPage(self) -> bool:  # noqa: N802
        return self.hasNext and self._query_page(self.page + 1)


class NetworkController(TablePageController):
    confirmationRequested = Signal(str, str, int)
    confirmationPendingChanged = Signal()
    _NETWORK_METHODS = {
        "calendar_collect": "collect_calendar",
        "backfill_execute": "execute_backfill",
    }

    def __init__(self, runtime: DesktopOperationRuntime, *, parent: QObject | None = None):
        super().__init__(runtime, parent=parent)
        self._pending: tuple[str, dict[str, Any], Callable[[Any], Any]] | None = None

    @Property(bool, notify=confirmationPendingChanged)
    def confirmationPending(self) -> bool:  # noqa: N802
        return self._pending is not None

    def _request_network(
        self,
        name: str,
        values: dict[str, Any],
        apply: Callable[[Any], Any],
    ) -> bool:
        self._assert_thread()
        if name not in self._NETWORK_METHODS:
            return self._reject_input(ValueError("Unsupported network operation."))
        if self._pending is not None or self._runtime.busy:
            return False
        try:
            if self._runtime.settings_path is None:
                raise RuntimeError("Desktop settings are not configured.")
            from market_vault.config import load_settings

            settings = load_settings(self._runtime.settings_path)
        except Exception as exc:
            self._status = "FAILED"
            self._error = str(exc).strip() or exc.__class__.__name__
            self.stateChanged.emit()
            return False
        self._pending = (name, dict(values), apply)
        self.confirmationPendingChanged.emit()
        self.confirmationRequested.emit(name, settings.opend_host, settings.opend_port)
        return True

    @Slot(bool, result=bool)
    def resolveConfirmation(self, accepted: bool) -> bool:  # noqa: N802
        self._assert_thread()
        pending = self._pending
        if pending is None:
            return False
        self._pending = None
        self.confirmationPendingChanged.emit()
        if not accepted:
            return False
        name, values, apply = pending
        method_name = self._NETWORK_METHODS.get(name)
        if method_name is None:
            return self._reject_input(ValueError("Unsupported network operation."))
        return self._submit(
            name,
            lambda backend: getattr(backend, method_name)(**values),
            apply,
        )


class TradingCalendarController(NetworkController):
    @Slot("QVariantMap", result=bool)
    def query(self, values: dict[str, Any]) -> bool:
        try:
            arguments, page = _paged_values(values)
        except (TypeError, ValueError) as exc:
            return self._reject_input(exc)
        self._last_values = arguments
        return self._query_page(page)

    def _query_page(self, page: int) -> bool:
        values = dict(self._last_values)
        values["page"] = page
        return self._submit(
            "calendar_query",
            lambda backend: backend.query_calendar(**values),
            self._set_page,
        )

    @Slot("QVariantMap", result=bool)
    def requestCollect(self, values: dict[str, Any]) -> bool:  # noqa: N802
        try:
            arguments_with_page, _ = _paged_values(values)
        except (TypeError, ValueError) as exc:
            return self._reject_input(exc)
        self._last_values = arguments_with_page
        arguments = dict(self._last_values)
        for key in ("page", "page_size"):
            arguments.pop(key, None)
        def apply(result: dict[str, Any]) -> None:
            self._summary = _summary_values(result)
            QTimer.singleShot(0, lambda: self._query_page(1))

        return self._request_network(
            "calendar_collect",
            arguments,
            apply,
        )

    @Slot(result=bool)
    def previousPage(self) -> bool:  # noqa: N802
        return self.hasPrevious and self._query_page(self.page - 1)

    @Slot(result=bool)
    def nextPage(self) -> bool:  # noqa: N802
        return self.hasNext and self._query_page(self.page + 1)


class HistoricalDataController(NetworkController):
    @Property(QObject, constant=True)
    def planModel(self) -> QObject:  # noqa: N802
        return self._model

    @Slot("QVariantMap", result=bool)
    def plan(self, values: dict[str, Any]) -> bool:
        try:
            arguments = _backfill_values(values)
        except (TypeError, ValueError) as exc:
            return self._reject_input(exc)

        def apply(plan: Any) -> None:
            prepared_summary = {
                "scope": str(plan.scope),
                "symbols": ", ".join(str(symbol) for symbol in plan.symbols),
                "trading_dates": str(plan.trading_date_count),
                "pending": str(plan.pending_count),
                "skipped": str(plan.skipped_count),
            }
            validate_table_page(plan.items)
            self._summary = prepared_summary
            self._set_page(plan.items)

        return self._submit(
            "backfill_plan", lambda backend: backend.plan_backfill(**arguments), apply
        )

    @Slot("QVariantMap", result=bool)
    def requestExecute(self, values: dict[str, Any]) -> bool:  # noqa: N802
        try:
            arguments = _backfill_values(values)
        except (TypeError, ValueError) as exc:
            return self._reject_input(exc)
        return self._request_network(
            "backfill_execute",
            arguments,
            lambda result: setattr(
                self, "_summary", _summary_values(result)
            ),
        )
