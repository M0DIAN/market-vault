"""Explicit, offline comparison of two declared US RTH bar snapshots.

Agreement on a declared grid is not market accuracy or source independence.
Neither inspection nor comparison repairs, fills, deduplicates or writes inputs.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..market_values import is_nonnegative_volume, is_positive_price
from ..normalization.rth_calendar import resolve_exchange_rth_session

SNAPSHOT_SCHEMA_VERSION = "market-vault-market-data-snapshot-v1"
COMPARISON_SCHEMA_VERSION = "market-vault-market-data-comparison-v1"
PRICE_FIELDS = ("open", "high", "low", "close")
VALUE_FIELDS = (*PRICE_FIELDS, "volume")
BAR_FIELDS = ("start", "end", *VALUE_FIELDS)
SOURCE_FIELDS = ("provider", "version", "captured_at", "data_kind", "upstream_id", "upstream_evidence")
SCOPE_FIELDS = ("symbol", "asset_class", "adjustment", "session", "interval", "currency",
                "aggregation", "volume_basis", "window_start", "window_end")
INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30}
UTC = timezone.utc
NY = ZoneInfo("America/New_York")


def require_fields(value: Any, fields, *, optional=(), label="object") -> dict:
    if type(value) is not dict:
        raise ValueError(f"{label} must be an object")
    missing, extra = set(fields) - value.keys(), value.keys() - set(fields) - set(optional)
    if missing or extra:
        raise ValueError(f"{label} fields: missing={sorted(missing)}, extra={sorted(extra)}")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError(f"{label} must be a nonempty string without surrounding whitespace or controls")
    return value


def parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", value
    ):
        raise ValueError("timestamp must be explicit UTC ISO text with seconds (Z or +00:00)")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must have a timezone")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"non-finite JSON literal: {value}")


def json_bytes(payload: Any) -> bytes:
    """Stable UTF-8 JSON; no current clock, NaN or Infinity encoding."""
    return (json.dumps(payload, sort_keys=True, ensure_ascii=True, allow_nan=False,
                       separators=(",", ":")) + "\n").encode("utf-8")


def read_json_file(path: str | Path) -> Any:
    return json.loads(Path(path).read_bytes().decode("utf-8"),
                      object_pairs_hook=_no_duplicates, parse_constant=_reject_constant)


def write_market_data_json(path: str | Path, payload: Any) -> Path:
    """Publish a new report/export, refusing every existing destination."""
    from ..storage.atomic_file import _write_file_no_replace

    encoded = json_bytes(payload)
    return _write_file_no_replace(Path(path), lambda stream: stream.write(encoded))


def normalize_scope(scope: dict) -> dict:
    require_fields(scope, SCOPE_FIELDS, label="scope")
    result = {key: _text(scope[key], f"scope.{key}") for key in SCOPE_FIELDS}
    if not re.fullmatch(r"US\.[A-Z0-9][A-Z0-9._-]*", result["symbol"]):
        raise ValueError("scope.symbol must be an explicit uppercase US symbol")
    if result["asset_class"] not in {"EQUITY", "ETF"}:
        raise ValueError("scope.asset_class must declare EQUITY or ETF")
    if result["adjustment"] != "NONE" or result["session"] != "RTH":
        raise ValueError("only adjustment=NONE and session=RTH are supported")
    if result["interval"] not in INTERVAL_MINUTES:
        raise ValueError("interval must be 1m, 5m, 15m or 30m")
    start, end = parse_utc(result["window_start"]), parse_utc(result["window_end"])
    day = start.astimezone(NY).date()
    if end <= start or end.astimezone(NY).date() != day:
        raise ValueError("scope must declare a positive, same-day continuous RTH window")
    calendar = resolve_exchange_rth_session(day)
    if calendar.classification not in {"NORMAL", "EARLY_CLOSE"}:
        raise ValueError(f"exchange calendar {calendar.classification}: {calendar.reason}")
    opening = datetime.combine(day, calendar.open_time, NY).astimezone(UTC)
    closing = datetime.combine(day, calendar.close_time, NY).astimezone(UTC)
    step = timedelta(minutes=INTERVAL_MINUTES[result["interval"]])
    if not opening <= start < end <= closing or (start - opening) % step or (end - start) % step:
        raise ValueError("scope window must fit exchange RTH and align to its interval-start grid")
    result.update(window_start=utc_text(start), window_end=utc_text(end))
    return result


def expected_grid(scope: dict) -> list[tuple[str, str]]:
    """Enumerate every declared slot, including slots absent from both inputs."""
    scope = normalize_scope(scope)
    start, end = parse_utc(scope["window_start"]), parse_utc(scope["window_end"])
    step = timedelta(minutes=INTERVAL_MINUTES[scope["interval"]])
    return [(utc_text(start + i * step), utc_text(start + (i + 1) * step))
            for i in range((end - start) // step)]


def normalize_source(source: dict) -> dict:
    require_fields(source, SOURCE_FIELDS, label="source")
    result = {key: _text(source[key], f"source.{key}")
              for key in ("provider", "version", "captured_at", "data_kind")}
    if result["data_kind"] not in {"OBSERVED", "SYNTHETIC", "UNKNOWN"}:
        raise ValueError("source.data_kind must be OBSERVED, SYNTHETIC or UNKNOWN")
    result["captured_at"] = utc_text(parse_utc(result["captured_at"]))
    for key in ("upstream_id", "upstream_evidence"):
        result[key] = None if source[key] is None else _text(source[key], f"source.{key}")
    return result


def normalize_tolerances(tolerances: dict | None = None) -> dict:
    fields = ("price_absolute", "price_relative", "volume_absolute")
    if tolerances is None:
        return dict.fromkeys(fields, 0)
    require_fields(tolerances, fields, label="tolerances")
    if any(type(tolerances[key]) not in (int, float) or not is_nonnegative_volume(tolerances[key])
           for key in fields):
        raise ValueError("tolerances must be finite nonnegative numbers, not booleans")
    return {key: tolerances[key] for key in fields}


@dataclass
class _Snapshot:
    payload: dict
    records: dict[str, list[dict]]
    report: dict

    def slot(self, start: str) -> dict:
        records = self.records.get(start, [])
        state = ("MISSING" if not records else "DUPLICATE" if len(records) > 1
                 else "INVALID" if records[0]["errors"] else "VALID_UNIQUE")
        return {"state": state, "row_indices": [record["index"] for record in records],
                "bar": records[0]["bar"] if state == "VALID_UNIQUE" else None}


def _inspect_snapshot(payload: Any) -> _Snapshot:
    # The API accepts the same JSON values as the file format. Copy before
    # normalization, and refuse values a strict report cannot represent.
    payload = json.loads(json_bytes(payload))
    require_fields(payload, ("schema_version", "source", "scope", "bars"),
                   optional=("origin",), label="snapshot")
    if payload["schema_version"] != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError("unsupported snapshot schema_version")
    payload["source"] = normalize_source(payload["source"])
    payload["scope"] = normalize_scope(payload["scope"])
    if type(payload["bars"]) is not list or ("origin" in payload and type(payload["origin"]) is not dict):
        raise ValueError("snapshot bars must be an array and optional origin must be an object")
    grid = dict(expected_grid(payload["scope"]))
    start_bound = parse_utc(payload["scope"]["window_start"])
    end_bound = parse_utc(payload["scope"]["window_end"])
    records: dict[str, list[dict]] = {}
    invalid = []
    for index, raw in enumerate(payload["bars"]):
        errors, key, end = [], None, None
        try:
            require_fields(raw, BAR_FIELDS, optional=("origin",), label="bar")
        except ValueError as exc:
            errors.append(str(exc))
        if type(raw) is dict:
            try:
                instant = parse_utc(raw.get("start"))
                key = utc_text(instant)
                if not start_bound <= instant < end_bound:
                    errors.append("start: OUTSIDE_WINDOW")
                elif key not in grid:
                    errors.append("start: OFF_GRID")
            except ValueError as exc:
                errors.append(f"start: {exc}")
            try:
                end = utc_text(parse_utc(raw.get("end")))
                if key in grid and end != grid[key]:
                    errors.append("end: must equal start plus the declared interval")
            except ValueError as exc:
                errors.append(f"end: {exc}")
            prices_valid = True
            for field in PRICE_FIELDS:
                if type(raw.get(field)) not in (int, float) or not is_positive_price(raw.get(field)):
                    errors.append(f"{field}: requires a finite positive number")
                    prices_valid = False
            if type(raw.get("volume")) not in (int, float) or not is_nonnegative_volume(raw.get("volume")):
                errors.append("volume: requires a finite nonnegative number")
            if prices_valid and (raw["high"] < max(raw["open"], raw["low"], raw["close"])
                                 or raw["low"] > min(raw["open"], raw["high"], raw["close"])):
                errors.append("OHLC: high/low do not contain open and close")
            if "origin" in raw and type(raw["origin"]) is not dict:
                errors.append("origin: must be an object")
        record = {"index": index, "row": raw, "errors": errors, "bar": None}
        if not errors:
            record["bar"] = {**raw, "start": key, "end": end}
        if key is not None:
            records.setdefault(key, []).append(record)
        if errors:
            invalid.append({"index": index, "row": raw, "errors": errors})
    duplicates = [{"start": key, "row_indices": [r["index"] for r in group],
                   "rows": [r["row"] for r in group]}
                  for key, group in sorted(records.items()) if len(group) > 1]
    valid = sum(len(records.get(key, [])) == 1 and not records[key][0]["errors"] for key in grid)
    count = len(payload["bars"])
    excess = sum(len(item["row_indices"]) - 1 for item in duplicates)
    calendar = resolve_exchange_rth_session(start_bound.astimezone(NY).date())
    report = {"status": "INVALID_INPUT" if invalid or duplicates else "VALID",
              "source": payload["source"], "scope": payload["scope"], "origin": payload.get("origin"),
              "content_sha256": hashlib.sha256(json_bytes(payload)).hexdigest(),
              "file_sha256": None, "locator": None,
              "summary": {"input_rows": count, "valid_unique_slots": valid,
                          "invalid_rows": len(invalid), "duplicate_keys": len(duplicates),
                          "duplicate_rows": sum(len(item["row_indices"]) for item in duplicates),
                          "duplicate_excess_rows": excess,
                          "declared_grid_coverage": {"numerator": valid, "denominator": len(grid),
                                                     "ratio": valid / len(grid)},
                          "duplicate_rate": {"numerator": excess, "denominator": count,
                                             "ratio": excess / count if count else None}},
              "calendar": {"trade_date": calendar.trade_date.isoformat(),
                           "classification": calendar.classification,
                           "authority_version": calendar.authority_version,
                           "authority_reference": calendar.authority_reference},
              "invalid_rows": invalid, "duplicate_keys": duplicates}
    return _Snapshot(payload, records, report)


def _input(payload: Any, *, file_sha256=None, locator=None) -> tuple[_Snapshot | None, dict]:
    try:
        snapshot = _inspect_snapshot(payload)
        snapshot.report.update(file_sha256=file_sha256, locator=locator)
        return snapshot, snapshot.report
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        return None, {"status": "INVALID_INPUT", "error": str(exc),
                      "file_sha256": file_sha256, "locator": locator}


def _file_input(path: str | Path | None) -> tuple[_Snapshot | None, dict]:
    if path is None:
        return None, {"status": "NOT_RUN", "error": "input path not provided", "locator": None}
    digest = None
    try:
        raw = Path(path).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates,
                             parse_constant=_reject_constant)
        return _input(payload, file_sha256=digest, locator=str(path))
    except FileNotFoundError as exc:
        status, error = "NOT_RUN", str(exc)
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError) as exc:
        status, error = "INVALID_INPUT", str(exc)
    return None, {"status": status, "error": error, "file_sha256": digest, "locator": str(path)}


def _independence(inputs: list[dict]) -> dict:
    sources = [item["source"] for item in inputs if "source" in item]
    if any(source["data_kind"] == "SYNTHETIC" for source in sources):
        status = "SYNTHETIC"
    elif len(sources) != 2 or any(source["data_kind"] == "UNKNOWN" or not source["upstream_id"] for source in sources):
        status = "UNKNOWN"
    elif sources[0]["upstream_id"] == sources[1]["upstream_id"]:
        status = "SHARED_UPSTREAM"
    elif all(source["upstream_evidence"] for source in sources):
        status = "DECLARED_DISTINCT_UPSTREAM"
    else:
        status = "UNKNOWN"
    return {"status": status, "evidence_scope": "SOURCE_DECLARATIONS_ONLY"}


def _display_number(value: Decimal) -> int | float | None:
    number = float(value)
    if not math.isfinite(number) or (number == 0 and value != 0):
        return None
    return int(value) if value == value.to_integral_value() else number


def _differences(left: dict, right: dict, tolerances: dict) -> dict:
    result = {}
    # Finite binary64 inputs span at most ~632 decimal places; the products
    # and sums below also fit this bounded precision. Do not overflow a float
    # tolerance or collapse distinct large integer values before comparison.
    with localcontext() as context:
        context.prec = 1100
        for field in VALUE_FIELDS:
            a, b = Decimal(str(left[field])), Decimal(str(right[field]))
            difference = a - b
            limit = Decimal(str(tolerances["volume_absolute"])) if field == "volume" else (
                Decimal(str(tolerances["price_absolute"])) + Decimal(str(tolerances["price_relative"])) * abs(b)
            )
            item = {"left": left[field], "right": right[field], "signed": _display_number(difference),
                    "absolute": _display_number(abs(difference)), "within_tolerance": abs(difference) <= limit}
            if field != "volume":
                relative = _display_number(difference / b)
                item.update(relative=relative,
                            relative_unavailable_reason="OUTSIDE_FLOAT_RANGE" if relative is None else None)
            result[field] = item
    return result


def _compare(left_input, right_input, tolerances: dict) -> dict:
    left, left_report = left_input
    right, right_report = right_input
    report = {"report_schema_version": COMPARISON_SCHEMA_VERSION, "status": "NOT_RUN",
              "validation_scope": "DECLARED_BAR_GRID_COMPARISON", "market_accuracy_certified": False,
              "scope": None, "tolerances": tolerances, "expected_slots": None, "counts": None,
              "inputs": {"left": left_report, "right": right_report},
              "independence": _independence([left_report, right_report]), "rows": [],
              "limitations": ["Missing bars mean absent input records; their trading/activity cause is unknown.",
                              "Source and event claims require external evidence review.",
                              "captured_at is a declared observation time, not first publication or revision time.",
                              "MATCH is agreement on the declared grid, not market accuracy certification."]}
    if any(item["status"] == "NOT_RUN" for item in (left_report, right_report)):
        return report
    if left is None or right is None:
        report["status"] = "INVALID_INPUT"
        return report
    if left.payload["scope"] != right.payload["scope"]:
        report.update(status="NOT_COMPARABLE", scope_differences=[key for key in SCOPE_FIELDS
                      if left.payload["scope"][key] != right.payload["scope"][key]])
        return report
    report["scope"] = left.payload["scope"]
    grid = expected_grid(report["scope"])
    counts = dict.fromkeys(("matched", "different", "left_only", "right_only", "both_missing", "blocked"), 0)
    for start, end in grid:
        a, b = left.slot(start), right.slot(start)
        differences = {}
        if a["state"] in {"INVALID", "DUPLICATE"} or b["state"] in {"INVALID", "DUPLICATE"}:
            status, counter = "BLOCKED", "blocked"
        elif a["state"] == b["state"] == "MISSING":
            status, counter = "BOTH_MISSING", "both_missing"
        elif a["state"] == "MISSING":
            status, counter = "RIGHT_ONLY", "right_only"
        elif b["state"] == "MISSING":
            status, counter = "LEFT_ONLY", "left_only"
        else:
            differences = _differences(a["bar"], b["bar"], tolerances)
            matches = all(value["within_tolerance"] for value in differences.values())
            status, counter = ("MATCH", "matched") if matches else ("DIFFERENT", "different")
        counts[counter] += 1
        report["rows"].append({"start": start, "end": end, "status": status,
                               "left": a, "right": b, "differences": differences})
    report.update(expected_slots=len(grid), counts=counts)
    if left_report["status"] == "INVALID_INPUT" or right_report["status"] == "INVALID_INPUT":
        report["status"] = "INVALID_INPUT"
    elif any(counts[key] for key in ("left_only", "right_only", "both_missing")):
        report["status"] = "INCOMPLETE"
    else:
        report["status"] = "DIFFERENT" if counts["different"] else "MATCH"
    return report


def compare_snapshots(left: dict, right: dict, tolerances: dict | None = None) -> dict:
    """Compare JSON snapshot values. Invalid comparison options raise ValueError."""
    return _compare(_input(left), _input(right), normalize_tolerances(tolerances))


def compare_snapshot_files(left_path: str | Path | None, right_path: str | Path | None,
                           tolerances: dict | None = None) -> dict:
    """Compare only the two explicit files; missing input is a recorded NOT_RUN."""
    return _compare(_file_input(left_path), _file_input(right_path), normalize_tolerances(tolerances))
