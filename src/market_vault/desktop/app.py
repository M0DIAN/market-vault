"""Production-like bootstrap for the parallel PySide6/QML desktop."""

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


def resolve_desktop_settings_path(
    explicit: str | None = None,
    *,
    frozen: bool | None = None,
    executable: str | None = None,
) -> Path:
    """Resolve settings independently of CWD for source and frozen launches."""

    from market_vault.application import resolve_application_settings_path

    frozen_value = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    return resolve_application_settings_path(
        explicit,
        frozen=frozen_value,
        executable=executable,
        source_default=Path(__file__).resolve().parents[3]
        / "config"
        / "settings.yaml",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the MarketVault QML desktop.")
    parser.add_argument(
        "--smoke-exit-ms",
        type=smoke_exit_milliseconds,
        default=None,
        help="Exit automatically after a bounded number of milliseconds.",
    )
    parser.add_argument(
        "--settings",
        default=None,
        help="Settings file. Frozen relative paths resolve from the executable directory.",
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
    """Create the Qt application over one shared production backend context."""

    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle

    from market_vault.application import build_application_context
    from market_vault.desktop.bootstrap import create_qml_application_session

    qml_path = resolve_qml_path()
    if not qml_path.is_file():
        raise RuntimeError(f"QML entry point is missing: {qml_path}")
    resolved_settings = settings_path or resolve_desktop_settings_path()
    context = build_application_context(resolved_settings)

    QQuickStyle.setStyle("Basic")
    try:
        application = QGuiApplication([sys.argv[0]])
        application.setApplicationName("MarketVault QML")
        engine = QQmlApplicationEngine()
        session = create_qml_application_session(context, engine)
    except Exception:
        context.shutdown()
        raise
    try:
        engine.load(QUrl.fromLocalFile(str(qml_path)))
        if not engine.rootObjects():
            raise RuntimeError(f"QML failed to create a root object: {qml_path}")
        session.validate_wiring()
    except Exception:
        session.shutdown()
        raise

    application.aboutToQuit.connect(session.shutdown)
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
            print(
                f"Dashboard smoke failed: {session.dashboard.error}",
                file=sys.stderr,
            )
            finish_dashboard_smoke(3)

        def dashboard_timed_out() -> None:
            print("Dashboard smoke timed out.", file=sys.stderr)
            finish_dashboard_smoke(4)

        def dashboard_loaded() -> None:
            if (
                dashboard_smoke_require_recent_runs
                and session.dashboard.recentRunsModel.rowCount() < 1
            ):
                print("Dashboard smoke requires recent-run rows.", file=sys.stderr)
                finish_dashboard_smoke(5)
                return
            finish_dashboard_smoke(0)

        session.dashboard.dashboardLoaded.connect(dashboard_loaded)
        session.dashboard.dashboardFailed.connect(dashboard_failed)
        dashboard_smoke_timer = QTimer(engine)
        dashboard_smoke_timer.setSingleShot(True)
        dashboard_smoke_timer.timeout.connect(dashboard_timed_out)
        dashboard_smoke_timer.start(dashboard_smoke_timeout_ms)
        engine._market_vault_dashboard_smoke_timer = dashboard_smoke_timer
        QTimer.singleShot(0, session.dashboard.refresh)

    if smoke_exit_ms is not None:
        QTimer.singleShot(smoke_exit_ms, application.quit)
    try:
        return application.exec()
    finally:
        session.shutdown()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.dashboard_smoke and args.smoke_exit_ms is not None:
        parser.error("--dashboard-smoke cannot be combined with --smoke-exit-ms")
    if args.dashboard_smoke_require_recent_runs and not args.dashboard_smoke:
        parser.error("--dashboard-smoke-require-recent-runs requires --dashboard-smoke")
    try:
        settings_path = resolve_desktop_settings_path(args.settings)
        return run_application(
            smoke_exit_ms=args.smoke_exit_ms,
            settings_path=settings_path,
            dashboard_smoke=args.dashboard_smoke,
            dashboard_smoke_timeout_ms=args.dashboard_smoke_timeout_ms,
            dashboard_smoke_require_recent_runs=(
                args.dashboard_smoke_require_recent_runs
            ),
        )
    except Exception as exc:
        print(f"MarketVault QML startup failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
