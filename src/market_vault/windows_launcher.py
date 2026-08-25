from __future__ import annotations

import argparse
import ctypes
import sys
from pathlib import Path
from typing import Any


WINDOWS_ICON_RELATIVE_PATH = Path("assets/windows/market-vault.ico")


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def application_root(*, frozen: bool | None = None, executable: str | None = None) -> Path:
    """Return the installed application directory for a frozen executable."""
    frozen_value = is_frozen() if frozen is None else frozen
    if not frozen_value:
        raise RuntimeError("application_root is defined only for frozen applications")
    return Path(executable or sys.executable).resolve().parent


def resolve_settings_path(
    explicit: str | None = None,
    *,
    frozen: bool | None = None,
    executable: str | None = None,
) -> Path:
    """Resolve Console settings without depending on CWD in frozen mode."""
    frozen_value = is_frozen() if frozen is None else frozen
    if explicit:
        candidate = Path(explicit).expanduser()
        if frozen_value and not candidate.is_absolute():
            return application_root(frozen=True, executable=executable) / candidate
        return candidate
    if frozen_value:
        return application_root(frozen=True, executable=executable) / "config" / "settings.yaml"
    return Path("config/settings.yaml")


def resolve_window_icon_path(
    *,
    frozen: bool | None = None,
    executable: str | None = None,
    runtime_root: str | Path | None = None,
    source_root: str | Path | None = None,
) -> Path:
    """Resolve the approved window icon without depending on process CWD."""
    frozen_value = is_frozen() if frozen is None else frozen
    if frozen_value:
        bundled_root = runtime_root or getattr(sys, "_MEIPASS", None)
        root = (
            Path(bundled_root)
            if bundled_root is not None
            else application_root(frozen=True, executable=executable)
        )
    else:
        root = (
            Path(source_root)
            if source_root is not None
            else Path(__file__).resolve().parents[2]
        )
    return root.resolve() / WINDOWS_ICON_RELATIVE_PATH


def configure_window_icon(
    root: Any,
    *,
    frozen: bool | None = None,
    executable: str | None = None,
    runtime_root: str | Path | None = None,
    source_root: str | Path | None = None,
) -> Path | None:
    """Apply the approved ICO, failing closed for a broken frozen bundle."""
    frozen_value = is_frozen() if frozen is None else frozen
    icon_path = resolve_window_icon_path(
        frozen=frozen_value,
        executable=executable,
        runtime_root=runtime_root,
        source_root=source_root,
    )
    if not icon_path.is_file():
        if frozen_value:
            raise FileNotFoundError(f"MarketVault window icon not found: {icon_path}")
        return None
    try:
        root.iconbitmap(default=str(icon_path))
    except Exception:
        if frozen_value:
            raise
        return None
    return icon_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch MarketVault Console")
    parser.add_argument(
        "--settings",
        default=None,
        help="Settings file. Frozen relative paths resolve from the executable directory.",
    )
    return parser


def _show_frozen_error(message: str) -> None:
    ctypes.windll.user32.MessageBoxW(0, message, "MarketVault startup error", 0x10)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings_path = resolve_settings_path(args.settings)
    try:
        from market_vault.console.ui import run_console

        return run_console(str(settings_path))
    except Exception as exc:
        if not is_frozen():
            raise
        _show_frozen_error(
            "MarketVault could not start.\n\n"
            f"{exc.__class__.__name__}: {exc}\n\n"
            f"Settings: {settings_path}"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
