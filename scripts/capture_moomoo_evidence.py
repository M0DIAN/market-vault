"""Bounded quote-only capture. No database writes, accounts, orders, or training.

Run from a source checkout using its existing Python environment. A new output
folder is mandatory; interrupted runs are retained, never resumed or replaced.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Iterator
import zipfile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = (
    "scripts/capture_moomoo_evidence.py",
    "src/market_vault/models.py",
    "src/market_vault/moomoo_sdk.py",
    "src/market_vault/collectors/moomoo_history.py",
    "src/market_vault/collectors/moomoo_calendar.py",
    "src/market_vault/normalization/calendar.py",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def append_event(path: Path, value: Any) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def source_identity() -> dict[str, Any]:
    result: dict[str, Any] = {
        "git_head": None, "source_dirty": None,
        "sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                   for name in SOURCE_FILES if (ROOT / name).is_file()},
        "python": sys.version.split()[0], "installed_sdk_distributions": {},
    }
    for name in ("moomoo-api", "moomoo", "futu-api"):
        try:
            result["installed_sdk_distributions"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    try:
        head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=5, check=False)
        dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", *SOURCE_FILES],
                               capture_output=True, text=True, timeout=5, check=False)
        if head.returncode == 0:
            result["git_head"] = head.stdout.strip()
        if dirty.returncode == 0:
            result["source_dirty"] = bool(dirty.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass  # File hashes still identify available source; no invented commit.
    return result


@contextmanager
def open_collectors(output: Path, port: int) -> Iterator[tuple[Any, Any]]:
    # Imports are deliberately lazy: --help works without OpenD or its SDK.
    sys.path.insert(0, str(ROOT / "src"))
    from market_vault.collectors.moomoo_calendar import MoomooCalendarCollector
    from market_vault.collectors.moomoo_history import MoomooHistoryCollector
    from market_vault.models import Settings

    settings = Settings(
        project_root=ROOT, opend_host="127.0.0.1", opend_port=port,
        data_root=output, catalog_path=output / "unused_catalog.sqlite",
        manifest_dir=output, report_dir=output, default_session="RTH",
        default_adjustment="NONE", request_pause_seconds=0.6,
    )
    with MoomooCalendarCollector(settings) as calendar, MoomooHistoryCollector(settings) as history:
        yield calendar, history


def save_frame(output: Path, name: str, frame: Any) -> dict[str, Any]:
    from pandas import DataFrame

    if not isinstance(frame, DataFrame):
        raise TypeError("SDK snapshot must be a DataFrame")
    path = output / name
    # Preserve SDK row order, duplicate rows, columns and numeric values. This is
    # an SDK-table snapshot, NOT a byte-for-byte wire/protobuf packet capture.
    frame.to_csv(path, index=False, mode="x", encoding="utf-8", lineterminator="\n")
    return {
        "file": name, "rows": len(frame), "columns": list(frame.columns),
        "dtypes": {str(key): str(value) for key, value in frame.dtypes.items()},
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def calendar_dates(frame: Any, start: date, end: date) -> list[date]:
    column = "time" if "time" in frame.columns else "trade_date"
    days = [date.fromisoformat(str(value)) for value in frame[column]]
    if not days or len(set(days)) != len(days) or any(not start <= day <= end for day in days):
        raise ValueError("Empty, duplicate, or out-of-range provider calendar")
    return sorted(days)


def capture(args: argparse.Namespace) -> tuple[int, Path]:
    output = args.output.expanduser().resolve()
    if output.is_relative_to(ROOT):
        raise ValueError("Output must be outside the source checkout")
    output.mkdir(parents=True, exist_ok=False)
    event_path = output / "events.jsonl"
    event_path.touch(exist_ok=False)
    request = {
        "schema": "moomoo_primary_capture_v1", "created_at_utc": utc_now(),
        "symbols": args.symbols, "start": args.start.isoformat(), "end": args.end.isoformat(),
        "interval": "1m", "session": "RTH", "adjustment": "NONE", "market": "US",
        "timestamp_timezone": "America/New_York", "source": "moomoo_or_futu_sdk",
        "scope": "SDK_TABLE_SNAPSHOTS_ONLY", "source_identity": source_identity(),
        "independent_reference": "NOT_SUPPLIED", "data_evidence_gate": "NOT_EVALUATED",
    }
    write_json(output / "request.json", request)  # Fixed before connecting.
    snapshots: list[dict[str, Any]] = []
    completed = empty = 0
    planned: int | None = None
    operation: dict[str, Any] = {"kind": "connect"}
    failure: dict[str, Any] | None = None
    code = 0
    try:
        with open_collectors(output, args.port) as (calendar, history):
            operation = {"kind": "calendar", "started_at_utc": utc_now()}
            append_event(event_path, {**operation, "status": "STARTED"})
            frame = calendar.fetch_trading_calendar(args.start, args.end, market="US")
            record = save_frame(output, "calendar.csv", frame)
            snapshots.append(record)
            append_event(event_path, {**operation, **record, "finished_at_utc": utc_now(),
                                      "status": "RETURNED"})
            days = calendar_dates(frame, args.start, args.end)
            planned = len(days) * len(args.symbols)
            write_json(output / "provider_schedule.json", {
                "dates": [day.isoformat() for day in days], "planned_history_requests": planned,
                "basis": "PRIMARY_PROVIDER_CALENDAR_ONLY", "independently_verified": False,
                "expected_bar_count": None,
            })
            for day in days:
                for symbol in args.symbols:
                    time.sleep(0.6)
                    operation = {"kind": "history", "symbol": symbol, "date": day.isoformat(),
                                 "started_at_utc": utc_now()}
                    append_event(event_path, {**operation, "status": "STARTED"})
                    frame = history.fetch_history(symbol, day, interval="1m", adjustment="NONE", session="RTH")
                    record = save_frame(output, f"{symbol}_{day.isoformat()}.csv", frame)
                    snapshots.append(record)
                    completed += 1
                    empty += int(frame.empty)
                    append_event(event_path, {
                        **operation, **record, "finished_at_utc": utc_now(),
                        "status": "EMPTY" if frame.empty else "RETURNED",
                        "request_capability": history.last_request_evidence,
                    })
            operation = {"kind": "close_contexts"}
    except (Exception, KeyboardInterrupt) as exc:
        code = 130 if isinstance(exc, KeyboardInterrupt) else 1
        # SDK exceptions can include environment/account/session details. Keep
        # the type and request identity, not arbitrary error text or tracebacks.
        failure = {**operation, "status": "INTERRUPTED" if code == 130 else "FAILED",
                   "error_type": type(exc).__name__, "finished_at_utc": utc_now()}
        append_event(event_path, failure)
    if code == 0 and empty:
        code = 2
    manifest = {
        "capture_status": ("FAILED" if failure else "COMPLETE_WITH_EMPTY_REQUESTS" if empty else "COMPLETE"),
        "finished_at_utc": utc_now(), "planned_history_requests": planned,
        "completed_history_requests": completed, "empty_history_requests": empty,
        "not_completed_history_requests": None if planned is None else planned - completed,
        "snapshots": snapshots, "failure": failure,
        "coverage": "NOT_EVALUATED", "independent_reference": "NOT_SUPPLIED",
        "revisions": "RETAIN_EARLIER_RUNS_FOR_COMPARISON", "data_evidence_gate": "NOT_EVALUATED",
        "partial_pages_of_failed_request_preserved": False,
    }
    write_json(output / "manifest.json", manifest)
    names = ["request.json", "events.jsonl", "manifest.json", *[item["file"] for item in snapshots]]
    if (output / "provider_schedule.json").exists():
        names.append("provider_schedule.json")
    archive = output / "upload.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in names:
            bundle.write(output / name, name)
    return code, archive


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=["US.SPY", "US.QQQ"])
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New folder outside the source checkout")
    parser.add_argument("--port", type=int, default=11111, help="Local OpenD port; host is always 127.0.0.1")
    args = parser.parse_args(argv)
    if not 0 <= (args.end - args.start).days < 31:
        parser.error("Require start <= end and at most 31 calendar days")
    if args.end >= datetime.now(ZoneInfo("America/New_York")).date():
        parser.error("Use dates strictly before today in America/New_York")
    if not 1 <= len(args.symbols) <= 3 or len(set(args.symbols)) != len(args.symbols):
        parser.error("Require one to three unique US symbols")
    if any(re.fullmatch(r"US\.[A-Z0-9][A-Z0-9.]{0,15}", symbol) is None for symbol in args.symbols):
        parser.error("Use explicit US symbols such as US.SPY")
    if not 1 <= args.port <= 65535:
        parser.error("Invalid local OpenD port")
    try:
        code, archive = capture(args)
    except (OSError, ValueError) as exc:
        print(f"Capture could not finish: {type(exc).__name__}. Keep any created folder; use a new output path.", file=sys.stderr)
        return 1
    print(f"UPLOAD_FILE={archive}")
    print(f"EXIT_CODE={code}; DATA_EVIDENCE_GATE=NOT_EVALUATED")
    if code:
        print("Capture is incomplete or contains empty responses. Upload its bundle for diagnosis; do not overwrite it.")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
