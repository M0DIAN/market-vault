"""Settings-independent entry points for explicit market-data evidence."""

from __future__ import annotations

import json
import sys

from .lifecycle import LifecycleLockError
from .market_data_exports import snapshot_from_canonical, snapshot_from_csv
from .quality.market_data_comparison import (
    compare_snapshot_files, read_json_file, write_market_data_json,
)
from .storage.atomic_file import AtomicFilePublicationError

MARKET_DATA_COMMANDS = frozenset({"market-data-compare", "market-data-snapshot-from-csv",
                                 "market-data-snapshot-from-canonical"})


def add_market_data_subparsers(subparsers) -> None:
    compare = subparsers.add_parser("market-data-compare", help="Compare two explicit local bar snapshots")
    compare.add_argument("--left", required=True, metavar="PATH")
    compare.add_argument("--right", required=True, metavar="PATH")
    compare.add_argument("--output", required=True, metavar="NEW_PATH")
    for name in ("price-absolute", "price-relative", "volume-absolute"):
        compare.add_argument("--" + name, type=float, default=0)
    for command, source in (("market-data-snapshot-from-csv", "csv"),
                            ("market-data-snapshot-from-canonical", "build")):
        parser = subparsers.add_parser(command, help="Export an explicit input with declared source/scope metadata")
        parser.add_argument("--" + source, required=True, metavar="PATH")
        parser.add_argument("--metadata", required=True, metavar="PATH")
        parser.add_argument("--output", required=True, metavar="NEW_PATH")


def market_data_main(args, *, command: str) -> int:
    try:
        if command == "market-data-compare":
            payload = compare_snapshot_files(args.left, args.right, {
                "price_absolute": args.price_absolute, "price_relative": args.price_relative,
                "volume_absolute": args.volume_absolute,
            })
        elif command == "market-data-snapshot-from-csv":
            payload = snapshot_from_csv(args.csv, read_json_file(args.metadata))
        elif command == "market-data-snapshot-from-canonical":
            payload = snapshot_from_canonical(args.build, read_json_file(args.metadata))
        else:
            raise ValueError(f"unsupported market-data command: {command}")
        output = write_market_data_json(args.output, payload)
        print(json.dumps({"status": "SUCCESS", "output": str(output), "report": payload},
                         ensure_ascii=True, allow_nan=False))
        return 0
    except AtomicFilePublicationError as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc), "published": exc.published},
                         ensure_ascii=True), file=sys.stderr)
        return 1
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError, RecursionError,
            LifecycleLockError) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1
