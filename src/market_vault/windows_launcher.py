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
    """Resolve MarketVault settings without depending on CWD in frozen mode."""
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
    from market_vault.desktop.app import add_application_arguments

    parser = argparse.ArgumentParser(description="Launch MarketVault")
    return add_application_arguments(parser, hide_internal_smoke_options=True)


def _show_frozen_error(message: str) -> None:
    ctypes.windll.user32.MessageBoxW(0, message, "MarketVault startup error", 0x10)


def main(argv: list[str] | None = None) -> int:
    settings_path: Path | None = None
    try:
        parser = build_parser()
        args = parser.parse_args(argv)
        from market_vault.desktop.app import (
            run_application,
            validate_application_arguments,
        )

        validate_application_arguments(parser, args)
        settings_path = resolve_settings_path(args.settings)
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
        if not is_frozen():
            raise
        _show_frozen_error(
            "MarketVault could not start.\n\n"
            f"{exc.__class__.__name__}: {exc}\n\n"
            f"Settings: {settings_path or 'unresolved'}"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
