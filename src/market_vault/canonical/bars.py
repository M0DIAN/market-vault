"""In-memory canonical market-bar builder core (ADR 0001).

Derives deterministic canonical rows from audited complete physical snapshots
selected by the V0.3 latest-complete semantics. This module performs no
materialization: it never writes Parquet, never touches DuckDB, and never
modifies source data.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

import pandas as pd

from ..intraday_audit import parse_intraday_interval
from ..normalization import bar_available_at
from .identity import canonical_bar_key, canonical_row_version_id
from .models import (
    CanonicalBar,
    CanonicalBuildError,
    CanonicalBuildResult,
    CanonicalConflictError,
    CanonicalResolutionEntry,
    CanonicalSnapshotInput,
    CanonicalSourceRef,
)

#: Canonical builder contract version. Changing it changes row version IDs
#: but never business keys. Do not change the package version here.
CANONICAL_BUILDER_VERSION = "market-bars-canonical-v1"

DEFAULT_DATASET_KIND = "market_bars_canonical"

#: Core OHLCV columns preserved from curated rows.
OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")

#: Optional market fields preserved when present and non-null; absent values
#: are never invented.
OPTIONAL_MARKET_FIELDS = (
    "turnover",
    "last_close",
    "change_rate",
    "pe_ratio",
    "turnover_rate",
)

#: Stable source-ranking rule: within one canonical_bar_key, candidates are
#: ordered by (source_snapshot_content_hash, ingestion_run_id,
#: requested_trade_date, requested_session) ascending and the first one is
#: selected. Independent of input order and filesystem paths.
def _source_rank_key(candidate: dict) -> tuple:
    return (
        candidate["source_snapshot_content_hash"],
        str(candidate["row"]["ingestion_run_id"]),
        candidate["requested_trade_date"].isoformat(),
        candidate["requested_session"],
    )


def _to_market_value(value) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return number


def hash_curated_snapshot_rows(df: pd.DataFrame) -> str:
    """Deterministic content hash of curated snapshot rows.

    Order-independent: each row is normalized to a fixed field sequence and
    the set of row digests is sorted before hashing, so identical contents
    with different row orders hash identically and different contents never
    collide. Missing optional values are omitted from each row encoding.
    """
    fields = OHLCV_COLUMNS + ("code", "interval", "adjustment", "time_utc")
    row_digests = []
    for _, row in df.iterrows():
        parts = []
        for column in fields:
            value = row.get(column)
            if value is None or (isinstance(value, float) and pd.isna(value)):
                parts.append(f"{column}=")
            elif isinstance(value, (pd.Timestamp, datetime)):
                parts.append(f"{column}={_utc_iso(value)}")
            elif isinstance(value, (date,)):
                parts.append(f"{column}={value.isoformat()}")
            else:
                parts.append(f"{column}={value!r}")
        row_digests.append(hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest())
    row_digests.sort()
    payload = "\x1e".join(row_digests)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _utc_iso(value) -> str:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        raise ValueError(f"naive timestamp: {value!r}")
    return stamp.tz_convert("UTC").isoformat()


def _required_timestamp(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        raise CanonicalBuildError(f"missing required timestamp column {column!r}")
    parsed = pd.to_datetime(frame[column], errors="raise")
    if not parsed.notna().all():
        raise CanonicalBuildError(f"invalid timestamp values in column {column!r}")
    if parsed.dt.tz is None:
        raise CanonicalBuildError(f"naive timestamp column {column!r} is not allowed")
    return parsed


def _market_value_tuple(row: pd.Series) -> tuple:
    """Normalized market-value comparison key for duplicate reconciliation.

    Missing or NaN values normalize to None so equal-but-missing values never
    look like a conflict.
    """
    return tuple(_to_market_value(row.get(column)) for column in OHLCV_COLUMNS) + tuple(
        _to_market_value(row.get(column)) for column in OPTIONAL_MARKET_FIELDS
    )


def _optional_fields(row: pd.Series) -> tuple[tuple[str, float], ...]:
    result = []
    for column in OPTIONAL_MARKET_FIELDS:
        value = row.get(column)
        if value is None or (isinstance(value, float) and pd.isna(value)):
            continue
        result.append((column, float(value)))
    return tuple(result)


def build_canonical_market_bars(
    snapshots: list[CanonicalSnapshotInput],
    *,
    canonical_builder_version: str = CANONICAL_BUILDER_VERSION,
    dataset_kind: str = DEFAULT_DATASET_KIND,
) -> CanonicalBuildResult:
    """Build deterministic in-memory canonical rows for audited snapshots.

    Input contract (ADR 0001 COMPLETE gate):
    - Each ``snapshot`` must come from the V0.3 latest-complete selection
      (``Catalog.latest_complete_market_bar_snapshots``); the builder fails
      closed on missing or inconsistent metadata and never upgrades
      PARTIAL/FAILED data into COMPLETE.
    - Each ``rows`` frame must be the audited snapshot's curated rows for the
      snapshot's symbol (e.g. from ``Catalog.market_bar_snapshot_rows``).

    Multiple snapshots may contribute rows for the same ``canonical_bar_key``;
    equivalent candidates are reconciled deterministically into one business
    row and conflicting candidates raise ``CanonicalConflictError``.

    Failures raise ``CanonicalBuildError`` (invalid inputs) or
    ``CanonicalConflictError`` (duplicate business keys with conflicting
    market values). Output ordering, identities, conflict fields, and
    resolution metadata are fully deterministic and independent of input row
    order, snapshot order, filesystem paths, DuckDB session timezone, and
    local machine timezone.
    """
    if not snapshots:
        raise CanonicalBuildError("at least one audited snapshot input is required")

    candidates: list[dict] = []
    for source in snapshots:
        candidates.extend(
            _candidates_for_snapshot(
                source,
                canonical_builder_version=canonical_builder_version,
                dataset_kind=dataset_kind,
            )
        )

    # Reconcile duplicate business keys.
    by_key: dict[str, list[dict]] = {}
    for candidate in candidates:
        by_key.setdefault(candidate["canonical_bar_key"], []).append(candidate)

    bars: list[CanonicalBar] = []
    resolution: list[CanonicalResolutionEntry] = []
    for business_key in sorted(by_key):
        group = by_key[business_key]
        reference_value = group[0]["market_value"]
        differing_fields: list[str] = []
        for candidate in group[1:]:
            if candidate["market_value"] != reference_value:
                differing_fields.append(_differing_field_names(reference_value, candidate["market_value"]))
        if differing_fields:
            field_set: set[str] = set()
            for field_list in differing_fields:
                field_set.update(field_list)
            raise CanonicalConflictError(
                canonical_bar_key=business_key,
                differing_fields=tuple(sorted(field_set)),
                candidates=tuple(_conflict_candidate(group)),
            )

        selected = _select_primary(group)
        discarded = sorted(
            (candidate for candidate in group if candidate is not selected),
            key=_source_rank_key,
        )
        row = selected["row"]
        bars.append(
            CanonicalBar(
                canonical_bar_key=business_key,
                canonical_row_version_id=selected["canonical_row_version_id"],
                dataset_kind=dataset_kind,
                code=str(row["code"]),
                interval=str(row["interval"]),
                adjustment=str(row["adjustment"]),
                event_time=selected["event_time"],
                market_available_at=selected["market_available_at"],
                archive_available_at=selected["archive_available_at"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=row["volume"],
                extra_fields=selected["optional_fields"],
                ingestion_run_id=str(row["ingestion_run_id"]),
                source_snapshot_content_hash=selected["source_snapshot_content_hash"],
                source_schema_version=str(row["source_schema_version"]),
                canonical_builder_version=canonical_builder_version,
                requested_trade_date=_as_date(row["requested_trade_date"]),
                requested_session=str(row["requested_session"]),
                market_calendar_date=_as_date(row["market_calendar_date"]),
                session=str(row["session"]),
                snapshot_file=selected["snapshot_file"],
            )
        )
        resolution.append(
            CanonicalResolutionEntry(
                canonical_bar_key=business_key,
                selected=_source_ref(selected),
                equivalent_discarded=tuple(
                    _source_ref(candidate) for candidate in discarded
                ),
            )
        )

    bars.sort(key=lambda bar: bar.canonical_bar_key)
    resolution.sort(key=lambda entry: entry.canonical_bar_key)
    return CanonicalBuildResult(
        bars=tuple(bars),
        resolution=tuple(resolution),
        builder_version=canonical_builder_version,
        source_snapshot_count=len({candidate["row"]["ingestion_run_id"] for candidate in candidates}),
    )


def _candidates_for_snapshot(
    source: CanonicalSnapshotInput,
    *,
    canonical_builder_version: str,
    dataset_kind: str,
) -> list[dict]:
    """Validate one audited snapshot input and assemble its row candidates."""
    snapshot = source.snapshot
    rows = source.rows
    source_snapshot_content_hash = source.source_snapshot_content_hash
    if source.run_status not in ("SUCCESS", "PARTIAL"):
        raise CanonicalBuildError(
            f"run status {source.run_status!r} is not audited as complete; refusing "
            "to upgrade it into canonical output"
        )
    if source.run_finished_at is None:
        raise CanonicalBuildError("run_finished_at is required for archive_available_at")
    if rows is None or rows.empty:
        raise CanonicalBuildError("snapshot produced no rows to canonicalize")

    for column in ("code", "interval", "adjustment", "requested_trade_date",
                   "requested_session", "market_calendar_date", "session",
                   "ingestion_run_id", "source_schema_version", "open", "high",
                   "low", "close", "volume"):
        if column not in rows.columns:
            raise CanonicalBuildError(f"missing required column {column!r}")

    interval_value = str(rows["interval"].iloc[0])
    try:
        interval_delta = parse_intraday_interval(interval_value)
    except ValueError as exc:
        raise CanonicalBuildError(str(exc)) from exc
    interval_seconds = int(interval_delta.total_seconds())

    # DuckDB may surface timestamps in the session timezone; normalize the
    # UTC column to UTC so event_time is always a UTC instant regardless of
    # the reading session (contract, section 7).
    time_utc = _required_timestamp(rows, "time_utc").dt.tz_convert("UTC")
    time_market = _required_timestamp(rows, "time_market")
    if not (time_market.dt.tz_convert("UTC") == time_utc).all():
        raise CanonicalBuildError(
            "event_time/time_market disagreement: rows whose market instant "
            "does not equal the UTC instant"
        )

    archive_available_at = pd.Timestamp(source.run_finished_at)
    if archive_available_at.tzinfo is None:
        raise CanonicalBuildError("run_finished_at must be timezone-aware")
    archive_available_at = archive_available_at.tz_convert("UTC")

    candidates: list[dict] = []
    for _, row in rows.iterrows():
        event_time = time_utc.loc[row.name]
        if event_time.tzinfo is None or str(event_time.tz) != "UTC":
            raise CanonicalBuildError("event_time must be a UTC instant")
        business_key = canonical_bar_key(
            dataset_kind=dataset_kind,
            code=str(row["code"]),
            interval=str(row["interval"]),
            adjustment=str(row["adjustment"]),
            event_time=event_time,
        )
        version_id = canonical_row_version_id(
            canonical_bar_key=business_key,
            ingestion_run_id=str(row["ingestion_run_id"]),
            source_snapshot_content_hash=source_snapshot_content_hash,
            source_schema_version=str(row["source_schema_version"]),
            canonical_builder_version=canonical_builder_version,
        )
        candidates.append(
            {
                "canonical_bar_key": business_key,
                "canonical_row_version_id": version_id,
                "event_time": event_time,
                "market_available_at": bar_available_at(
                    time_market.loc[row.name], interval_seconds
                ),
                "archive_available_at": archive_available_at,
                "market_value": _market_value_tuple(row),
                "optional_fields": _optional_fields(row),
                "source_snapshot_content_hash": source_snapshot_content_hash,
                "snapshot_file": snapshot.snapshot_file,
                "requested_trade_date": _as_date(row["requested_trade_date"]),
                "requested_session": str(row["requested_session"]),
                "row": row,
            }
        )
    return candidates


def _differing_field_names(reference: tuple, candidate: tuple) -> tuple[str, ...]:
    names = OHLCV_COLUMNS + OPTIONAL_MARKET_FIELDS
    return tuple(name for name, a, b in zip(names, reference, candidate) if a != b)


def _conflict_candidate(group: list[dict]) -> list[dict]:
    result = []
    for candidate in sorted(group, key=_source_rank_key):
        row = candidate["row"]
        result.append(
            {
                "run_id": str(row["ingestion_run_id"]),
                "snapshot_hash": candidate["source_snapshot_content_hash"],
                "snapshot_file": candidate["snapshot_file"],
            }
        )
    return result


def _select_primary(group: list[dict]) -> dict:
    return min(group, key=_source_rank_key)


def _source_ref(candidate: dict) -> CanonicalSourceRef:
    row = candidate["row"]
    return CanonicalSourceRef(
        ingestion_run_id=str(row["ingestion_run_id"]),
        source_snapshot_content_hash=candidate["source_snapshot_content_hash"],
        snapshot_file=candidate["snapshot_file"],
        requested_trade_date=candidate["requested_trade_date"],
        requested_session=candidate["requested_session"],
    )


def _as_date(value) -> date:
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()
