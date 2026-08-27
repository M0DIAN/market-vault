"""Side-effect-free bootstrap for the parallel PySide6/QML canary."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence


MAX_SMOKE_EXIT_MS = 60_000
DEFAULT_DASHBOARD_SMOKE_TIMEOUT_MS = 30_000
MAX_DASHBOARD_SMOKE_TIMEOUT_MS = 120_000


def smoke_exit_milliseconds(value: str) -> int:
    """Parse a bounded positive smoke-test timeout."""

    try:
        milliseconds = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if not 1 <= milliseconds <= MAX_SMOKE_EXIT_MS:
        raise argparse.ArgumentTypeError(
            f"must be between 1 and {MAX_SMOKE_EXIT_MS} milliseconds"
        )
    return milliseconds


def dashboard_smoke_timeout_milliseconds(value: str) -> int:
    """Parse a bounded dashboard smoke timeout."""

    try:
        milliseconds = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if not 1 <= milliseconds <= MAX_DASHBOARD_SMOKE_TIMEOUT_MS:
        raise argparse.ArgumentTypeError(
            f"must be between 1 and {MAX_DASHBOARD_SMOKE_TIMEOUT_MS} milliseconds"
        )
    return milliseconds


def absolute_settings_path(value: str) -> Path:
    """Accept only an explicit absolute settings path for backend use."""

    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("must be an absolute path")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the MarketVault QML canary.")
    parser.add_argument(
        "--smoke-exit-ms",
        type=smoke_exit_milliseconds,
        default=None,
        help="Exit automatically after a bounded number of milliseconds.",
    )
    parser.add_argument(
        "--settings",
        type=absolute_settings_path,
        default=None,
        help="Absolute settings path used only after an explicit dashboard refresh.",
    )
    parser.add_argument(
        "--dashboard-smoke",
        action="store_true",
        help="Refresh the dashboard once and exit according to the result.",
    )
    parser.add_argument(
        "--dashboard-smoke-timeout-ms",
        type=dashboard_smoke_timeout_milliseconds,
        default=DEFAULT_DASHBOARD_SMOKE_TIMEOUT_MS,
        help="Bounded timeout for --dashboard-smoke.",
    )
    parser.add_argument(
        "--dashboard-smoke-require-recent-runs",
        action="store_true",
        help="Require at least one recent-run row before dashboard smoke succeeds.",
    )
    return parser


def resolve_qml_path(*, frozen_root: Path | None = None) -> Path:
    """Resolve Main.qml without consulting the current working directory."""

    if frozen_root is not None:
        root = Path(frozen_root)
        return root / "market_vault" / "desktop" / "qml" / "Main.qml"
    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", None)
        if not bundle_root:
            raise RuntimeError("Frozen QML root is unavailable.")
        return resolve_qml_path(frozen_root=Path(bundle_root))
    return Path(__file__).resolve().parent / "qml" / "Main.qml"


def run_application(
    *,
    smoke_exit_ms: int | None = None,
    settings_path: Path | None = None,
    dashboard_smoke: bool = False,
    dashboard_smoke_timeout_ms: int = DEFAULT_DASHBOARD_SMOKE_TIMEOUT_MS,
    dashboard_smoke_require_recent_runs: bool = False,
) -> int:
    """Create the Qt application and load the minimal QML scene."""

    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle

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

    qml_path = resolve_qml_path()
    if not qml_path.is_file():
        raise RuntimeError(f"QML entry point is missing: {qml_path}")

    QQuickStyle.setStyle("Basic")
    application = QGuiApplication([sys.argv[0]])
    application.setApplicationName("MarketVault QML Canary")
    engine = QQmlApplicationEngine()
    bridge = DesktopBridge(parent=engine)
    runtime = DesktopOperationRuntime(settings_path=settings_path, parent=engine)
    dashboard = DashboardController(runtime=runtime, parent=engine)
    historical = HistoricalDataController(runtime, parent=engine)
    calendar = TradingCalendarController(runtime, parent=engine)
    market_data = MarketDataController(runtime, parent=engine)
    inventory = InventoryController(runtime, parent=engine)
    coverage = AuditController(
        runtime, method_name="coverage_audit", parent=engine
    )
    intraday = AuditController(
        runtime, method_name="intraday_audit", parent=engine
    )
    runs = RunsController(runtime, parent=engine)
    storage = StorageCleanupController(runtime, parent=engine)
    preferences = DesktopPreferenceStore()
    i18n = I18nBridge(preference_store=preferences, parent=engine)
    shell = ShellController(parent=engine)
    engine.rootContext().setContextProperty("desktopBridge", bridge)
    engine.rootContext().setContextProperty("operationRuntime", runtime)
    engine.rootContext().setContextProperty("dashboardController", dashboard)
    engine.rootContext().setContextProperty("historicalDataController", historical)
    engine.rootContext().setContextProperty("tradingCalendarController", calendar)
    engine.rootContext().setContextProperty("marketDataController", market_data)
    engine.rootContext().setContextProperty("inventoryController", inventory)
    engine.rootContext().setContextProperty("coverageAuditController", coverage)
    engine.rootContext().setContextProperty("intradayAuditController", intraday)
    engine.rootContext().setContextProperty("runsController", runs)
    engine.rootContext().setContextProperty("storageCleanupController", storage)
    engine.rootContext().setContextProperty("i18nBridge", i18n)
    engine.rootContext().setContextProperty("shellController", shell)
    engine._market_vault_desktop_bridge = bridge
    engine._market_vault_operation_runtime = runtime
    engine._market_vault_dashboard_controller = dashboard
    engine._market_vault_page_controllers = (
        historical,
        calendar,
        market_data,
        inventory,
        coverage,
        intraday,
        runs,
        storage,
    )
    engine._market_vault_i18n_bridge = i18n
    engine._market_vault_shell_controller = shell
    engine.load(QUrl.fromLocalFile(str(qml_path)))
    if not engine.rootObjects():
        runtime.shutdown()
        raise RuntimeError(f"QML failed to create a root object: {qml_path}")

    application.aboutToQuit.connect(runtime.shutdown)
    dashboard_smoke_timer = None
    if dashboard_smoke:
        completed = False

        def finish_dashboard_smoke(exit_code: int) -> None:
            nonlocal completed
            if completed:
                return
            completed = True
            if dashboard_smoke_timer is not None:
                dashboard_smoke_timer.stop()
            application.exit(exit_code)

        def dashboard_failed() -> None:
            print(f"Dashboard smoke failed: {dashboard.error}", file=sys.stderr)
            finish_dashboard_smoke(3)

        def dashboard_timed_out() -> None:
            print("Dashboard smoke timed out.", file=sys.stderr)
            finish_dashboard_smoke(4)

        def dashboard_loaded() -> None:
            if (
                dashboard_smoke_require_recent_runs
                and dashboard.recentRunsModel.rowCount() < 1
            ):
                print("Dashboard smoke requires recent-run rows.", file=sys.stderr)
                finish_dashboard_smoke(5)
                return
            finish_dashboard_smoke(0)

        dashboard.dashboardLoaded.connect(dashboard_loaded)
        dashboard.dashboardFailed.connect(dashboard_failed)
        dashboard_smoke_timer = QTimer(engine)
        dashboard_smoke_timer.setSingleShot(True)
        dashboard_smoke_timer.timeout.connect(dashboard_timed_out)
        dashboard_smoke_timer.start(dashboard_smoke_timeout_ms)
        engine._market_vault_dashboard_smoke_timer = dashboard_smoke_timer
        QTimer.singleShot(0, dashboard.refresh)

    if smoke_exit_ms is not None:
        QTimer.singleShot(smoke_exit_ms, application.quit)
    try:
        return application.exec()
    finally:
        runtime.shutdown()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.dashboard_smoke and args.settings is None:
        parser.error("--dashboard-smoke requires --settings")
    if args.dashboard_smoke and args.smoke_exit_ms is not None:
        parser.error("--dashboard-smoke cannot be combined with --smoke-exit-ms")
    if args.dashboard_smoke_require_recent_runs and not args.dashboard_smoke:
        parser.error("--dashboard-smoke-require-recent-runs requires --dashboard-smoke")
    try:
        return run_application(
            smoke_exit_ms=args.smoke_exit_ms,
            settings_path=args.settings,
            dashboard_smoke=args.dashboard_smoke,
            dashboard_smoke_timeout_ms=args.dashboard_smoke_timeout_ms,
            dashboard_smoke_require_recent_runs=(
                args.dashboard_smoke_require_recent_runs
            ),
        )
    except Exception as exc:
        print(f"MarketVault QML canary startup failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
