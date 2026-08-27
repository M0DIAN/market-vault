"""Side-effect-free bootstrap for the parallel PySide6/QML canary."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence


MAX_SMOKE_EXIT_MS = 60_000


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the MarketVault QML canary.")
    parser.add_argument(
        "--smoke-exit-ms",
        type=smoke_exit_milliseconds,
        default=None,
        help="Exit automatically after a bounded number of milliseconds.",
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


def run_application(*, smoke_exit_ms: int | None = None) -> int:
    """Create the Qt application and load the minimal QML scene."""

    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine

    from market_vault.desktop.bridge import DesktopBridge

    qml_path = resolve_qml_path()
    if not qml_path.is_file():
        raise RuntimeError(f"QML entry point is missing: {qml_path}")

    application = QGuiApplication([sys.argv[0]])
    application.setApplicationName("MarketVault QML Canary")
    engine = QQmlApplicationEngine()
    bridge = DesktopBridge(parent=engine)
    engine.rootContext().setContextProperty("desktopBridge", bridge)
    engine.load(QUrl.fromLocalFile(str(qml_path)))
    if not engine.rootObjects():
        raise RuntimeError(f"QML failed to create a root object: {qml_path}")

    if smoke_exit_ms is not None:
        QTimer.singleShot(smoke_exit_ms, application.quit)
    return application.exec()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run_application(smoke_exit_ms=args.smoke_exit_ms)
    except Exception as exc:
        print(f"MarketVault QML canary startup failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
