"""In-memory canonical market-bar builder core (ADR 0001).

Derives deterministic canonical rows from audited complete physical snapshots
selected by the V0.3 latest-complete semantics. This module performs no
materialization: it never writes Parquet, never touches DuckDB, and never
modifies source data.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime

import pandas as pd

from ..intraday_audit import parse_intraday_interval
from ..normalization import bar_available_at, market_session_label
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

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def _is_null_scalar(value) -> bool:
    """Safe scalar-null check: None, NaN, pd.NA, and NaT are all null."""
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _validate_physical_snapshot_hash(value: str) -> str:
    if not value or not isinstance(value, str):
        raise CanonicalBuildError("physical_snapshot_hash must be a SHA-256 hex digest")
    normalized = value.lower()
    if not _SHA256_HEX_RE.match(normalized):
        raise CanonicalBuildError(
            "physical_snapshot_hash must be a 64-character lowercase SHA-256 hex digest"
        )
    return normalized


def _typed_row_value(column: str, value) -> str:
    """Explicitly typed canonical serialization for one logical row field."""
    if _is_null_scalar(value):
        return f"{column}:z"  # z = absent/null
    if isinstance(value, (pd.Timestamp, datetime)):
        stamp = pd.Timestamp(value)
        if stamp.tzinfo is None:
            return f"{column}:t:{stamp.isoformat()}"
        return f"{column}:t:{stamp.tz_convert('UTC').isoformat()}"
    if isinstance(value, (date,)):
        return f"{column}:d:{value.isoformat()}"
    if isinstance(value, float):
        return f"{column}:f:{float(value)!r}"
    if isinstance(value, (int,)):
        return f"{column}:i:{int(value)}"
    return f"{column}:s:{value}"


def hash_canonical_source_rows(rows: pd.DataFrame) -> str:
    """Deterministic logical content hash of source curated rows.

    Covers every field that can affect canonical output or conflict
    resolution: normalized code/interval/adjustment, the market instant,
    OHLCV, supported optional market fields, request/provenance fields, and
    classification fields. Rows are encoded with an explicitly typed
    canonical serialization (never repr() as the primary encoding) and the
    set of row digests is sorted before hashing, so identical logical content
    with different row orders hashes identically. SHA-256 is collision-
    resistant; it is not claimed to be collision-free.
    """
    fields = (
        "code",
        "interval",
        "adjustment",
        "time_market",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "turnover",
        "last_close",
        "change_rate",
        "pe_ratio",
        "turnover_rate",
        "requested_trade_date",
        "requested_session",
        "market_calendar_date",
        "session",
        "ingestion_run_id",
        "source_schema_version",
    )
    row_digests = []
    for _, row in rows.iterrows():
        parts = [
            _typed_row_value(column, row.get(column) if column in rows.columns else None)
            for column in fields
        ]
        row_digests.append(hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest())
    row_digests.sort()
    return hashlib.sha256("\x1e".join(row_digests).encode("utf-8")).hexdigest()


def _hash_normalized_records(records: list[dict], interval_seconds: int) -> str:
    """Deterministic logical hash over normalized canonical records.

    Encodes the already-normalized semantics -- canonical code/interval/
    adjustment, the UTC event instant, OHLCV, supported optional values,
    request/classification fields, run id, and schema version -- never raw
    unnormalized DataFrame values. Equivalent casing, whitespace, and
    timezone representations that normalize to the same canonical semantics
    produce the same hash; the physical_snapshot_hash continues to preserve
    exact file-byte identity. Row digests are sorted, so the hash is
    independent of row order. SHA-256 is collision-resistant, not
    collision-free.
    """
    row_digests = []
    for record in records:
        parts = [
            f"code:s:{record['code']}",
            f"interval:s:{record['interval']}",
            f"adjustment:s:{record['adjustment']}",
            f"event_time:t:{record['event_time'].tz_convert('UTC').isoformat()}",
            f"open:f:{record['open']!r}",
            f"high:f:{record['high']!r}",
            f"low:f:{record['low']!r}",
            f"close:f:{record['close']!r}",
            f"volume:f:{record['volume']!r}",
        ]
        for column, value in record["optional_fields"]:
            parts.append(f"{column}:f:{value!r}")
        parts.extend(
            [
                f"requested_trade_date:d:{record['requested_trade_date'].isoformat()}",
                f"requested_session:s:{record['requested_session']}",
                f"market_calendar_date:d:{record['market_calendar_date'].isoformat()}",
                f"session:s:{record['session']}",
                f"ingestion_run_id:s:{record['ingestion_run_id']}",
                f"source_schema_version:s:{record['source_schema_version']}",
            ]
        )
        row_digests.append(hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest())
    row_digests.sort()
    return hashlib.sha256("\x1e".join(row_digests).encode("utf-8")).hexdigest()


def _required_timestamp(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        raise CanonicalBuildError(f"missing required timestamp column {column!r}")
    parsed = pd.to_datetime(frame[column], errors="raise")
    if not parsed.notna().all():
        raise CanonicalBuildError(f"invalid timestamp values in column {column!r}")
    if parsed.dt.tz is None:
        raise CanonicalBuildError(f"naive timestamp column {column!r} is not allowed")
    return parsed


def _normalize_code(value) -> str:
    text = str(value).strip().upper()
    if not text:
        raise CanonicalBuildError("empty code value")
    return text


def _normalize_adjustment(value) -> str:
    text = str(value).strip().upper()
    if not text:
        raise CanonicalBuildError("empty adjustment value")
    return text


def _normalize_session(value) -> str:
    text = str(value).strip().upper()
    if not text:
        raise CanonicalBuildError("empty requested_session value")
    return text


def _as_date(value) -> date:
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def _finite_market_number(value, column: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CanonicalBuildError(f"non-numeric {column}: {value!r}") from exc
    if pd.isna(number):
        raise CanonicalBuildError(f"null {column} value")
    if number in (float("inf"), float("-inf")) or number != number:
        raise CanonicalBuildError(f"non-finite {column} value")
    return number


def _optional_fields(row: pd.Series) -> tuple[tuple[str, float], ...]:
    """Supported optional market fields.

    A missing column is allowed; None, NaN, pd.NA, and NaT are null and
    allowed; finite numeric values are preserved; non-null non-numeric values
    and positive/negative infinity fail closed instead of being silently
    treated as absent.
    """
    result = []
    for column in OPTIONAL_MARKET_FIELDS:
        if column not in row.index:
            continue  # missing column allowed
        raw = row[column]
        if _is_null_scalar(raw):
            continue  # null allowed
        try:
            number = float(raw)
        except (TypeError, ValueError) as exc:
            raise CanonicalBuildError(
                f"non-numeric optional field {column}: {raw!r}"
            ) from exc
        if number in (float("inf"), float("-inf")):
            raise CanonicalBuildError(f"non-finite optional field {column}: {raw!r}")
        result.append((column, number))
    return tuple(result)


def _classification_value(market_calendar_date: date, canonical_session: str) -> tuple:
    """Canonical classification fields in contract order.

    Both values are normalized (market_calendar_date from the validated
    market instant, canonical_session from market_session_label), never the
    raw stored strings. A different derived classification for the same
    business key is a conflict, while a different requested_session is only
    provenance.
    """
    return (
        market_calendar_date.isoformat(),
        canonical_session,
    )


def _normalize_ranking_timestamp(value, label: str) -> pd.Timestamp | None:
    if _is_null_scalar(value):
        return None
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        raise CanonicalBuildError(f"{label} must be timezone-aware")
    return stamp.tz_convert("UTC")


def _source_rank_key(candidate: dict) -> tuple:
    """Natural ascending rank tuple for selection with max().

    The documented order is: snapshot_ingested_at present first then timestamp
    DESC; run_finished_at present first then timestamp DESC; ingestion_run_id
    DESC; physical_snapshot_hash DESC as the final path-independent
    tie-breaker. Because max() picks the largest key, ascending tuple
    comparison encodes that order exactly: presence flags put nulls last, and
    the plain string fields select their lexicographically largest value,
    which is the DESC winner. snapshot_file never participates; timestamps are
    already normalized to UTC, so the order is independent of the local
    machine timezone.
    """
    ingested = candidate["snapshot_ingested_at"]
    finished = candidate["run_finished_at"]
    return (
        0 if ingested is None else 1,
        ingested if ingested is not None else pd.Timestamp.min,
        0 if finished is None else 1,
        finished if finished is not None else pd.Timestamp.min,
        candidate["ingestion_run_id"],
        candidate["physical_snapshot_hash"],
    )


def _validate_and_normalize_snapshot(
    source: CanonicalSnapshotInput,
) -> dict:
    """Validate one audited snapshot input and return normalized row records.

    The ``CompleteSnapshotRef`` from latest_complete_market_bar_snapshots is
    the COMPLETE gate; completion is never redefined here. Every source row
    is validated against the selected ref and the exact request key, and the
    whole row set is normalized before any candidate is produced.
    """
    snapshot = source.snapshot
    rows = source.rows
    physical_hash = _validate_physical_snapshot_hash(source.physical_snapshot_hash)
    request_key = source.request_key

    if rows is None or rows.empty:
        raise CanonicalBuildError("snapshot produced no rows to canonicalize")

    required_columns = (
        "code", "interval", "adjustment", "requested_trade_date",
        "requested_session", "market_calendar_date", "session",
        "ingestion_run_id", "source_schema_version", "open", "high",
        "low", "close", "volume", "time_utc", "time_market",
    )
    missing = [column for column in required_columns if column not in rows.columns]
    if missing:
        raise CanonicalBuildError(f"missing required columns: {sorted(missing)}")

    # Row count must match the selected snapshot's eligible row count.
    if len(rows) != snapshot.eligible_row_count:
        raise CanonicalBuildError(
            f"row count {len(rows)} does not match the selected snapshot's "
            f"eligible_row_count {snapshot.eligible_row_count}"
        )

    time_utc = _required_timestamp(rows, "time_utc").dt.tz_convert("UTC")
    time_market = _required_timestamp(rows, "time_market")

    # Work on a private copy with a reset index so duplicate DataFrame index
    # labels can never break positional lookup; the caller's frame is not
    # mutated.
    work = rows.reset_index(drop=True)
    time_utc = time_utc.reset_index(drop=True)
    time_market = time_market.reset_index(drop=True)

    interval_seconds: int | None = None
    normalized_records: list[dict] = []
    for position in range(len(work)):
        row = work.iloc[position]

        code = _normalize_code(row["code"])
        if code != snapshot.code:
            raise CanonicalBuildError(
                f"row {position} code {code!r} does not match snapshot code {snapshot.code!r}"
            )
        interval_value = str(row["interval"]).strip().lower()
        try:
            parsed_interval = parse_intraday_interval(interval_value)
        except ValueError as exc:
            raise CanonicalBuildError(str(exc)) from exc
        interval_seconds_value = int(parsed_interval.total_seconds())
        if interval_seconds is None:
            interval_seconds = interval_seconds_value
        elif interval_seconds != interval_seconds_value:
            raise CanonicalBuildError(
                "mixed interval rows within one snapshot: "
                f"{interval_seconds}s and {interval_seconds_value}s"
            )
        if interval_value != request_key.interval:
            raise CanonicalBuildError(
                f"row {position} interval {interval_value!r} does not match "
                f"request key {request_key.interval!r}"
            )
        adjustment = _normalize_adjustment(row["adjustment"])
        if adjustment != request_key.adjustment:
            raise CanonicalBuildError(
                f"row {position} adjustment {adjustment!r} does not match "
                f"request key {request_key.adjustment!r}"
            )
        requested_session = _normalize_session(row["requested_session"])
        if requested_session != request_key.requested_session:
            raise CanonicalBuildError(
                f"row {position} requested_session {requested_session!r} does not "
                f"match request key {request_key.requested_session!r}"
            )
        schema_version = str(row["source_schema_version"]).strip()
        if not schema_version:
            raise CanonicalBuildError("empty source_schema_version")
        if schema_version != request_key.source_schema_version:
            raise CanonicalBuildError(
                f"row {position} source_schema_version {schema_version!r} does not "
                f"match request key {request_key.source_schema_version!r}"
            )
        run_id = str(row["ingestion_run_id"]).strip()
        if not run_id:
            raise CanonicalBuildError("empty ingestion_run_id")
        if run_id != snapshot.ingestion_run_id:
            raise CanonicalBuildError(
                f"row {position} ingestion_run_id {run_id!r} does not match "
                f"snapshot run {snapshot.ingestion_run_id!r}"
            )
        requested_trade_date = _as_date(row["requested_trade_date"])
        if requested_trade_date != snapshot.requested_trade_date:
            raise CanonicalBuildError(
                f"row {position} requested_trade_date {requested_trade_date} does "
                f"not match snapshot {snapshot.requested_trade_date}"
            )

        event_time = time_utc.iloc[position]
        market_time = time_market.iloc[position]
        if market_time.tz_convert("UTC") != event_time:
            raise CanonicalBuildError(
                f"row {position} event_time/time_market disagreement"
            )

        # Derived classification is a function of the instant in market
        # time: normalize to America/New_York so any session-timezone
        # representation of the same instant yields identical values.
        market_time_ny = market_time.tz_convert("America/New_York")
        raw_calendar_date = row["market_calendar_date"]
        if raw_calendar_date is None or pd.isna(raw_calendar_date):
            raise CanonicalBuildError(
                f"row {position} market_calendar_date is required canonical metadata"
            )
        market_calendar_date = _as_date(raw_calendar_date)
        if market_calendar_date != market_time_ny.date():
            raise CanonicalBuildError(
                f"row {position} market_calendar_date {market_calendar_date} does not "
                f"match market instant date {market_time_ny.date()}"
            )
        stored_session = str(row["session"]).strip().upper()
        canonical_session = market_session_label(market_time_ny)
        if stored_session != canonical_session:
            raise CanonicalBuildError(
                f"row {position} stored session {stored_session!r} does not match "
                f"derived session {canonical_session!r}"
            )

        normalized_records.append(
            {
                "position": position,
                "code": code,
                "interval": interval_value,
                "adjustment": adjustment,
                "requested_session": requested_session,
                "source_schema_version": schema_version,
                "ingestion_run_id": run_id,
                "requested_trade_date": requested_trade_date,
                "market_calendar_date": market_calendar_date,
                "session": canonical_session,
                "event_time": event_time,
                "market_time": market_time,
                "open": _finite_market_number(row["open"], "open"),
                "high": _finite_market_number(row["high"], "high"),
                "low": _finite_market_number(row["low"], "low"),
                "close": _finite_market_number(row["close"], "close"),
                "volume": _finite_market_number(row["volume"], "volume"),
                "optional_fields": _optional_fields(row),
                "classification": _classification_value(market_calendar_date, canonical_session),
            }
        )

    assert interval_seconds is not None
    return {
        "physical_hash": physical_hash,
        "interval_seconds": interval_seconds,
        "logical_source_rows_hash": _hash_normalized_records(normalized_records, interval_seconds),
        "records": normalized_records,
    }


def build_canonical_market_bars(
    snapshots: list[CanonicalSnapshotInput],
    *,
    canonical_builder_version: str = CANONICAL_BUILDER_VERSION,
    dataset_kind: str = DEFAULT_DATASET_KIND,
) -> CanonicalBuildResult:
    """Build deterministic in-memory canonical rows for audited snapshots.

    An empty input list is the normal result when every requested key is
    MISSING or INCOMPLETE and returns an empty result (no rows, no
    resolution, zero source snapshots).

    Input contract (ADR 0001 COMPLETE gate):
    - Each ``snapshot`` must come from the V0.3 latest-complete selection
      (``Catalog.latest_complete_market_bar_snapshots``); that ref is the
      gate. The builder validates that the supplied rows actually match the
      selected ref and the exact request key and fails closed on mismatch;
      it never redefines quality/run completion.
    - ``rows`` must be the audited snapshot's curated rows for the snapshot's
      symbol (e.g. from ``Catalog.market_bar_snapshot_rows``).
    - ``physical_snapshot_hash`` is the SHA-256 of the complete physical
      snapshot file bytes.

    Multiple snapshots may contribute rows for the same ``canonical_bar_key``;
    equivalent candidates are reconciled deterministically into one business
    row and conflicting candidates raise ``CanonicalConflictError``.

    Failures raise ``CanonicalBuildError`` (invalid inputs) or
    ``CanonicalConflictError`` (duplicate business keys with conflicting
    market or classification values). Output ordering, identities, conflict
    fields, and resolution metadata are fully deterministic and independent
    of input row order, snapshot order, filesystem paths, DuckDB session
    timezone, and local machine timezone.
    """
    if not snapshots:
        return CanonicalBuildResult(
            bars=(),
            resolution=(),
            builder_version=canonical_builder_version,
            source_snapshot_count=0,
        )

    candidates: list[dict] = []
    physical_identities: set[tuple] = set()
    for source in snapshots:
        normalized = _validate_and_normalize_snapshot(source)
        # Stable physical source identity: path-independent (no snapshot_file).
        physical_identities.add(
            (
                source.snapshot.code,
                source.snapshot.requested_trade_date,
                source.snapshot.ingestion_run_id,
                normalized["physical_hash"],
                (
                    source.request_key.interval,
                    source.request_key.requested_session,
                    source.request_key.adjustment,
                    source.request_key.source_schema_version,
                ),
            )
        )
        ingested = _normalize_ranking_timestamp(
            source.snapshot.snapshot_ingested_at, "snapshot_ingested_at"
        )
        finished = _normalize_ranking_timestamp(
            source.snapshot.run_finished_at, "snapshot.run_finished_at"
        )
        archive_available_at = _archive_available_at(source)
        for record in normalized["records"]:
            business_key = canonical_bar_key(
                dataset_kind=dataset_kind,
                code=record["code"],
                interval=record["interval"],
                adjustment=record["adjustment"],
                event_time=record["event_time"],
            )
            version_id = canonical_row_version_id(
                canonical_bar_key=business_key,
                ingestion_run_id=record["ingestion_run_id"],
                source_snapshot_content_hash=normalized["physical_hash"],
                source_schema_version=record["source_schema_version"],
                canonical_builder_version=canonical_builder_version,
            )
            candidates.append(
                {
                    "canonical_bar_key": business_key,
                    "canonical_row_version_id": version_id,
                    "event_time": record["event_time"],
                    "market_available_at": bar_available_at(
                        record["market_time"], normalized["interval_seconds"]
                    ),
                    "archive_available_at": archive_available_at,
                    "market_value": _market_value_tuple_from_record(record),
                    "optional_fields": record["optional_fields"],
                    "classification": record["classification"],
                    "physical_snapshot_hash": normalized["physical_hash"],
                    "snapshot_ingested_at": ingested,
                    "run_finished_at": finished,
                    "snapshot_file": source.snapshot.snapshot_file,
                    "ingestion_run_id": record["ingestion_run_id"],
                    "requested_trade_date": record["requested_trade_date"],
                    "requested_session": record["requested_session"],
                    # Computed once per snapshot, reused by every candidate.
                    "logical_source_rows_hash": normalized["logical_source_rows_hash"],
                    "record": record,
                }
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
        reference_classification = group[0]["classification"]
        differing: set[str] = set()
        for candidate in group[1:]:
            differing.update(_differing_field_names(reference_value, candidate["market_value"]))
            if candidate["classification"] != reference_classification:
                differing.update(_differing_classification_names(reference_classification, candidate["classification"]))
        if differing:
            raise CanonicalConflictError(
                canonical_bar_key=business_key,
                differing_fields=tuple(sorted(differing)),
                candidates=tuple(_conflict_candidate(group)),
            )

        selected = _select_primary(group)
        discarded = sorted(
            (candidate for candidate in group if candidate is not selected),
            key=_source_rank_key,
            reverse=True,
        )
        record = selected["record"]
        bars.append(
            CanonicalBar(
                canonical_bar_key=business_key,
                canonical_row_version_id=selected["canonical_row_version_id"],
                dataset_kind=dataset_kind,
                code=record["code"],
                interval=record["interval"],
                adjustment=record["adjustment"],
                event_time=selected["event_time"],
                market_available_at=selected["market_available_at"],
                archive_available_at=selected["archive_available_at"],
                open=record["open"],
                high=record["high"],
                low=record["low"],
                close=record["close"],
                volume=record["volume"],
                extra_fields=selected["optional_fields"],
                ingestion_run_id=selected["ingestion_run_id"],
                physical_snapshot_hash=selected["physical_snapshot_hash"],
                logical_source_rows_hash=selected["logical_source_rows_hash"],
                source_schema_version=record["source_schema_version"],
                canonical_builder_version=canonical_builder_version,
                requested_trade_date=record["requested_trade_date"],
                requested_session=record["requested_session"],
                market_calendar_date=record["market_calendar_date"],
                session=record["session"],
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
        source_snapshot_count=len(physical_identities),
    )


def _archive_available_at(source: CanonicalSnapshotInput) -> pd.Timestamp:
    finished = source.snapshot.run_finished_at
    if finished is None:
        raise CanonicalBuildError(
            "snapshot.run_finished_at is required for archive_available_at"
        )
    stamp = pd.Timestamp(finished)
    if stamp.tzinfo is None:
        raise CanonicalBuildError("snapshot.run_finished_at must be timezone-aware")
    return stamp.tz_convert("UTC")


def _market_value_tuple_from_record(record: dict) -> tuple:
    values = [record["open"], record["high"], record["low"], record["close"], record["volume"]]
    optional = dict(record["optional_fields"])
    for column in OPTIONAL_MARKET_FIELDS:
        values.append(optional.get(column))
    return tuple(values)


def _differing_field_names(reference: tuple, candidate: tuple) -> tuple[str, ...]:
    names = OHLCV_COLUMNS + OPTIONAL_MARKET_FIELDS
    return tuple(name for name, a, b in zip(names, reference, candidate) if a != b)


def _differing_classification_names(reference: tuple, candidate: tuple) -> tuple[str, ...]:
    names = ("market_calendar_date", "session")
    return tuple(name for name, a, b in zip(names, reference, candidate) if a != b)


def _conflict_candidate(group: list[dict]) -> list[dict]:
    result = []
    for candidate in sorted(group, key=_source_rank_key):
        result.append(
            {
                "run_id": candidate["ingestion_run_id"],
                "snapshot_hash": candidate["physical_snapshot_hash"],
                "snapshot_file": candidate["snapshot_file"],
            }
        )
    return result


def _select_primary(group: list[dict]) -> dict:
    # max() selects the documented DESC winner; see _source_rank_key.
    return max(group, key=_source_rank_key)


def _source_ref(candidate: dict) -> CanonicalSourceRef:
    return CanonicalSourceRef(
        ingestion_run_id=candidate["ingestion_run_id"],
        physical_snapshot_hash=candidate["physical_snapshot_hash"],
        logical_source_rows_hash=candidate["logical_source_rows_hash"],
        snapshot_file=candidate["snapshot_file"],
        requested_trade_date=candidate["requested_trade_date"],
        requested_session=candidate["requested_session"],
    )
