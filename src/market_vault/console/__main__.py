from __future__ import annotations

import sys

from ..windows_launcher import build_parser, resolve_settings_path


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings_path = resolve_settings_path(args.settings, frozen=False)
    try:
        from .ui import run_console
    except ModuleNotFoundError as exc:
        if exc.name != "tkinter":
            raise
        print(
            "Unable to start MarketVault Console: this Python installation "
            "does not include Tkinter. Install or repair a standard Python "
            "distribution with Tkinter support.",
            file=sys.stderr,
        )
        return 1

    return run_console(str(settings_path))


if __name__ == "__main__":
    raise SystemExit(main())
