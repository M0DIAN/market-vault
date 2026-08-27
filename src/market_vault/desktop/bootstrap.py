"""Production-like PySide6/QML composition over the shared application context."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PySide6.QtQml import QQmlApplicationEngine

from market_vault.application import ApplicationContext
from market_vault.desktop.bridge import DesktopBridge
from market_vault.desktop.controllers import (
    AuditController,
    HistoricalDataController,
    InventoryController,
    MarketDataController,
    RunsController,
    TradingCalendarController,
)
from market_vault.desktop.dashboard import DashboardController
from market_vault.desktop.localization import I18nBridge
from market_vault.desktop.preferences import DesktopPreferenceStore
from market_vault.desktop.runtime import DesktopOperationRuntime
from market_vault.desktop.shell import ShellController
from market_vault.desktop.storage_cleanup import StorageCleanupController


@dataclass
class QmlApplicationSession:
    """Own the QML object graph while the application context owns resources."""

    context: ApplicationContext
    engine: QQmlApplicationEngine
    runtime: DesktopOperationRuntime
    dashboard: DashboardController
    controllers: tuple[Any, ...]
    bridge: DesktopBridge
    i18n: I18nBridge
    shell: ShellController
    context_properties: dict[str, Any]
    _closed: bool = field(default=False, init=False, repr=False)

    def validate_wiring(self) -> None:
        """Fail closed if QML is not bound to the exact shared object graph."""

        if self.runtime.application_context is not self.context:
            raise RuntimeError("QML runtime is not bound to the application context.")
        if (
            self.runtime.backend_if_initialized
            is not self.context.backend_if_initialized
        ):
            raise RuntimeError("QML runtime is not bound to the shared backend.")
        if (
            self.runtime.task_runner_if_initialized
            is not self.context.task_runner_if_initialized
        ):
            raise RuntimeError("QML runtime is not bound to the shared task runner.")
        qml_context = self.engine.rootContext()
        for name, value in self.context_properties.items():
            if qml_context.contextProperty(name) is not value:
                raise RuntimeError(f"QML context property is not bound: {name}")

    def shutdown(self) -> bool:
        """Shut down only when idle, then release the shared runner once."""

        if self._closed:
            return True
        if not self.runtime.requestShutdown():
            return False
        self.context.shutdown()
        self._closed = True
        return True


def create_qml_application_session(
    context: ApplicationContext,
    engine: QQmlApplicationEngine,
    *,
    preference_store: DesktopPreferenceStore | None = None,
) -> QmlApplicationSession:
    """Compose every QML controller over one backend and serial runner."""

    bridge = DesktopBridge(parent=engine)
    runtime = DesktopOperationRuntime(application_context=context, parent=engine)
    dashboard = DashboardController(runtime=runtime, parent=engine)
    historical = HistoricalDataController(runtime, parent=engine)
    calendar = TradingCalendarController(runtime, parent=engine)
    market_data = MarketDataController(runtime, parent=engine)
    inventory = InventoryController(runtime, parent=engine)
    coverage = AuditController(runtime, method_name="coverage_audit", parent=engine)
    intraday = AuditController(runtime, method_name="intraday_audit", parent=engine)
    runs = RunsController(runtime, parent=engine)
    storage = StorageCleanupController(runtime, parent=engine)
    i18n = I18nBridge(
        preference_store=preference_store or DesktopPreferenceStore(),
        parent=engine,
    )
    shell = ShellController(parent=engine)
    properties = {
        "desktopBridge": bridge,
        "operationRuntime": runtime,
        "dashboardController": dashboard,
        "historicalDataController": historical,
        "tradingCalendarController": calendar,
        "marketDataController": market_data,
        "inventoryController": inventory,
        "coverageAuditController": coverage,
        "intradayAuditController": intraday,
        "runsController": runs,
        "storageCleanupController": storage,
        "i18nBridge": i18n,
        "shellController": shell,
    }
    qml_context = engine.rootContext()
    for name, value in properties.items():
        qml_context.setContextProperty(name, value)

    controllers = (
        historical,
        calendar,
        market_data,
        inventory,
        coverage,
        intraday,
        runs,
        storage,
    )
    session = QmlApplicationSession(
        context=context,
        engine=engine,
        runtime=runtime,
        dashboard=dashboard,
        controllers=controllers,
        bridge=bridge,
        i18n=i18n,
        shell=shell,
        context_properties=properties,
    )
    engine._market_vault_application_session = session
    return session
