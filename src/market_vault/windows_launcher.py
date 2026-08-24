from __future__ import annotations

import argparse
import ctypes
import sys
from pathlib import Path


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
