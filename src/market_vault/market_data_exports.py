"""Small explicit input bridges for the market-data comparator."""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
from datetime import datetime, timedelta
from pathlib import Path

from .quality.market_data_comparison import (
    BAR_FIELDS, INTERVAL_MINUTES, NY, SNAPSHOT_SCHEMA_VERSION, UTC,
    normalize_scope, normalize_source, parse_utc, require_fields, utc_text,
)


def _metadata(metadata: dict) -> dict:
    require_fields(metadata, ("source", "scope"), label="export metadata")
    return {"schema_version": SNAPSHOT_SCHEMA_VERSION,
            "source": normalize_source(metadata["source"]),
            "scope": normalize_scope(metadata["scope"]), "bars": []}


def _csv_number(value: str | None):
    if value is None:
        return None
    try:
        text = value.strip()
        number = int(text) if re.fullmatch(r"[+-]?\d+", text) else float(text)
        if math.isfinite(float(number)):
            return number
    except (ValueError, OverflowError):
        pass
    # Invalid values remain reportable JSON strings, not NaN/Infinity floats.
    return value


def snapshot_from_csv(csv_path: str | Path, metadata: dict) -> dict:
    """Read the exact fixed header; preserve every subsequent CSV record."""
    result = _metadata(metadata)
    raw = Path(csv_path).read_bytes()
    try:
        reader = csv.reader(io.StringIO(raw.decode("utf-8"), newline=""), strict=True)
        if next(reader, None) != list(BAR_FIELDS):
            raise ValueError("CSV header must be exactly start,end,open,high,low,close,volume")
        for values in reader:
            row = {key: values[i] if i < len(values) else None for i, key in enumerate(BAR_FIELDS)}
            for key in BAR_FIELDS[2:]:
                row[key] = _csv_number(row[key])
            if len(values) > len(BAR_FIELDS):
                row["csv_extra_fields"] = values[len(BAR_FIELDS):]
            result["bars"].append(row)
    except csv.Error as exc:
        raise ValueError(f"invalid CSV syntax: {exc}") from exc
    result["origin"] = {"kind": "CSV_EXPORT", "original_csv_sha256": hashlib.sha256(raw).hexdigest()}
    return result


def snapshot_from_canonical(build_path: str | Path, metadata: dict) -> dict:
    """Reload one explicit verified artifact and export its entire declared window.

    Canonical identities qualify the artifact, not the caller's vendor/lineage
    declarations. Its archive and market-availability times keep their names.
    """
    from .canonical.reader import load_verified_canonical_build
    from .normalization.rth_session_geometry import resolve_rth_session_geometry

    result = _metadata(metadata)
    build = load_verified_canonical_build(build_path)
    request, scope = build.normalized_request, result["scope"]
    start, end = parse_utc(scope["window_start"]), parse_utc(scope["window_end"])
    day = start.astimezone(NY).date()
    if (request.source_schema_version != "10.9-mv-ts2" or request.requested_session != "RTH"
            or request.adjustment != "NONE" or request.interval != scope["interval"]):
        raise ValueError("Canonical export requires matching NONE/RTH interval and 10.9-mv-ts2 source schema")
    if scope["symbol"] not in request.symbols or day not in request.trade_dates:
        raise ValueError("declared symbol/date is outside the explicit Canonical request")
    geometry = resolve_rth_session_geometry(day)
    opening = datetime.combine(day, geometry.open_time, NY).astimezone(UTC)
    closing = datetime.combine(day, geometry.close_time, NY).astimezone(UTC)
    step = timedelta(minutes=INTERVAL_MINUTES[scope["interval"]])
    for bar in build.bars:
        if bar.code != scope["symbol"]:
            continue
        event_day = bar.event_time.astimezone(NY).date()
        if day not in (event_day, bar.requested_trade_date, bar.market_calendar_date):
            continue
        if (bar.session != "RTH" or event_day != day or bar.requested_trade_date != day
                or bar.market_calendar_date != day or not opening <= bar.event_time < closing
                or (bar.event_time - opening) % step or bar.event_time + step > closing):
            raise ValueError("Canonical row does not satisfy the qualified RTH interval-start geometry")
        if start <= bar.event_time < end:
            result["bars"].append({
                "start": utc_text(bar.event_time), "end": utc_text(bar.event_time + step),
                "open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close, "volume": bar.volume,
                "origin": {"canonical_bar_key": bar.canonical_bar_key,
                           "canonical_row_version_id": bar.canonical_row_version_id,
                           "ingestion_run_id": bar.ingestion_run_id,
                           "physical_snapshot_hash": bar.physical_snapshot_hash,
                           "logical_source_rows_hash": bar.logical_source_rows_hash,
                           "source_schema_version": bar.source_schema_version,
                           "snapshot_file": bar.snapshot_file,
                           "market_available_at": utc_text(bar.market_available_at),
                           "archive_available_at": utc_text(bar.archive_available_at)},
            })
    result["origin"] = {
        "kind": "CANONICAL_EXPORT", "canonical_build_id": build.canonical_build_id,
        "canonical_content_id": build.canonical_content_id, "resolution_content_id": build.resolution_content_id,
        "canonical_schema_version": build.canonical_schema_version,
        "canonical_builder_version": build.canonical_builder_version,
        "normalized_request": {"symbols": list(request.symbols),
                               "trade_dates": [value.isoformat() for value in request.trade_dates],
                               "interval": request.interval, "requested_session": request.requested_session,
                               "adjustment": request.adjustment, "source_schema_version": request.source_schema_version},
        "provider_geometry_authority_version": geometry.authority_version,
        "provider_profile_version": geometry.provider_profile_version,
        "source_snapshot_provenance": [
            {"ingestion_run_id": ref.ingestion_run_id, "physical_snapshot_hash": ref.physical_snapshot_hash,
             "logical_source_rows_hash": ref.logical_source_rows_hash,
             "source_schema_version": ref.source_schema_version, "snapshot_file": ref.snapshot_file,
             "requested_trade_date": ref.requested_trade_date.isoformat(), "requested_session": ref.requested_session}
            for ref in build.source_snapshot_provenance
        ],
    }
    return result
