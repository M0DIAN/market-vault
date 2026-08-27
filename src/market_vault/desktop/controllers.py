"""Non-destructive page controllers for the QML desktop."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from PySide6.QtCore import Property, QObject, QThread, QTimer, QUrl, Signal, Slot

from market_vault.desktop.runtime import DesktopOperationRuntime
from market_vault.desktop.table_model import QtTableModel


if TYPE_CHECKING:
    from market_vault.console.models import TablePage


def _values(values: dict[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in dict(values).items()}


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
        if not text or not path.is_absolute():
            self._status = "FAILED"
            self._error = "Export destination must be an absolute local path."
            self.stateChanged.emit()
            return False
        return self._submit(
            "export",
            lambda backend: backend.export_page(self._page, path, format_name),
            lambda result: setattr(
                self, "_summary", {"path": result.path, "rows": str(result.row_count)}
            ),
        )


class MarketDataController(TablePageController):
    @Slot("QVariantMap", result=bool)
    def query(self, values: dict[str, Any]) -> bool:
        self._last_values = _values(values)
        return self._query_page(int(self._last_values.get("page", 1)))

    def _query_page(self, page: int) -> bool:
        values = dict(self._last_values)
        values["page"] = page
        values["page_size"] = int(values.get("page_size", 100))
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
        arguments = _values(values)

        def apply(result: tuple[dict[str, Any], TablePage]) -> None:
            summary, page = result
            self._set_page(page)
            self._summary = {str(k): str(v) for k, v in summary.items()}

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
        arguments = _values(values)

        def operation(backend: Any) -> Any:
            return getattr(backend, self._method_name)(**arguments)

        def apply(result: tuple[dict[str, Any], TablePage]) -> None:
            summary, page = result
            self._set_page(page)
            self._summary = {str(k): str(v) for k, v in summary.items()}

        return self._submit(self._method_name, operation, apply)


class RunsController(TablePageController):
    @Slot("QVariantMap", result=bool)
    def refresh(self, values: dict[str, Any]) -> bool:
        self._last_values = _values(values)
        return self._query_page(int(self._last_values.get("page", 1)))

    def _query_page(self, page: int) -> bool:
        values = dict(self._last_values)
        values["page"] = page
        values["page_size"] = int(values.get("page_size", 100))
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

    def __init__(self, runtime: DesktopOperationRuntime, *, parent: QObject | None = None):
        super().__init__(runtime, parent=parent)
        self._pending: tuple[str, dict[str, Any], Callable[[Any], Any]] | None = None

    def _request_network(
        self,
        name: str,
        values: dict[str, Any],
        apply: Callable[[Any], Any],
    ) -> bool:
        self._assert_thread()
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
        self.confirmationRequested.emit(name, settings.opend_host, settings.opend_port)
        return True

    @Slot(bool, result=bool)
    def resolveConfirmation(self, accepted: bool) -> bool:  # noqa: N802
        self._assert_thread()
        pending = self._pending
        self._pending = None
        if pending is None or not accepted:
            return False
        name, values, apply = pending
        method_name = "collect_calendar" if name == "calendar_collect" else "execute_backfill"
        return self._submit(
            name,
            lambda backend: getattr(backend, method_name)(**values),
            apply,
        )


class TradingCalendarController(NetworkController):
    @Slot("QVariantMap", result=bool)
    def query(self, values: dict[str, Any]) -> bool:
        self._last_values = _values(values)
        return self._query_page(int(self._last_values.get("page", 1)))

    def _query_page(self, page: int) -> bool:
        values = dict(self._last_values)
        values["page"] = page
        values["page_size"] = int(values.get("page_size", 100))
        return self._submit(
            "calendar_query",
            lambda backend: backend.query_calendar(**values),
            self._set_page,
        )

    @Slot("QVariantMap", result=bool)
    def requestCollect(self, values: dict[str, Any]) -> bool:  # noqa: N802
        self._last_values = _values(values)
        arguments = dict(self._last_values)
        for key in ("page", "page_size"):
            arguments.pop(key, None)
        def apply(result: dict[str, Any]) -> None:
            self._summary = {str(k): str(v) for k, v in result.items()}
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
        arguments = _values(values)

        def apply(plan: Any) -> None:
            self._set_page(plan.items)
            self._summary = {
                "scope": plan.scope,
                "symbols": ", ".join(plan.symbols),
                "trading_dates": str(plan.trading_date_count),
                "pending": str(plan.pending_count),
                "skipped": str(plan.skipped_count),
            }

        return self._submit(
            "backfill_plan", lambda backend: backend.plan_backfill(**arguments), apply
        )

    @Slot("QVariantMap", result=bool)
    def requestExecute(self, values: dict[str, Any]) -> bool:  # noqa: N802
        return self._request_network(
            "backfill_execute",
            _values(values),
            lambda result: setattr(
                self, "_summary", {str(k): str(v) for k, v in result.items()}
            ),
        )
