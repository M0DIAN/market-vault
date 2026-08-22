from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch MarketVault Console")
    parser.add_argument("--settings", default="config/settings.yaml")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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

    return run_console(args.settings)


if __name__ == "__main__":
    raise SystemExit(main())
