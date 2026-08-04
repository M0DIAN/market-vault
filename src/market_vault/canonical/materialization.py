"""Immutable canonical market-bar build materialization.

Loads audited COMPLETE snapshots through the V0.3 latest-complete selector,
runs the in-memory canonical builder, derives internal-gap and resolution
metadata, and atomically commits one immutable build directory:

    data/canonical/dataset=market_bars_canonical/build_id=<id>/
      bars/.../part-00000.parquet
      gaps/.../part-00000.parquet
      resolution.jsonl
      manifest.json
      _SUCCESS

Final build directories are immutable; existing committed builds are never
overwritten and repeated identical materialization is idempotent. No DuckDB
registration, no mutable latest pointer, no CLI, no OpenD.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ..storage import Catalog
from .bars import DEFAULT_DATASET_KIND, build_canonical_market_bars, parse_intraday_interval
from .gaps import GAP_POLICY_VERSION, derive_internal_gap_ranges
from .identity import (
    canonical_build_id,
    canonical_content_id,
    gap_content_id,
    resolution_content_id,
)
from .manifest import (
    GAP_POLICY_LIMITATIONS,
    MANIFEST_SCHEMA_VERSION,
    STATUS_COMPLETE,
    STATUS_EMPTY,
    build_manifest,
    write_manifest_json,
)
from .models import (
    CanonicalMaterializationError,
    CanonicalMaterializationRequest,
    CanonicalMaterializationResult,
    CanonicalRequestKey,
    CanonicalSnapshotInput,
)
from .schema import (
    CANONICAL_BAR_COLUMNS,
    CANONICAL_MATERIALIZER_VERSION,
    CANONICAL_SCHEMA_VERSION,
    canonical_bars_schema,
)

DATASET_DIR_NAME = "dataset=market_bars_canonical"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_CANONICAL_SEPARATORS = ("\x1e", "\x1f", "|")


def _reject_unsafe_string(value: str, label: str) -> None:
    if any(ord(character) < 32 for character in value):
        raise CanonicalMaterializationError(
            f"control character in {label}: {value!r}"
        )
    for separator in _CANONICAL_SEPARATORS:
        if separator in value:
            raise CanonicalMaterializationError(
                f"canonical encoding separator in {label}: {value!r}"
            )


def _require_string(value, label: str) -> str:
    if not isinstance(value, str):
        raise CanonicalMaterializationError(
            f"{label} must be a string, got {type(value).__name__}"
        )
    return value


def _normalize_symbol(value: str, label: str) -> str:
    text = _require_string(value, label).strip().upper()
    if not text:
        raise CanonicalMaterializationError(f"empty {label}")
    _reject_unsafe_string(text, label)
    return text


def _normalize_upper(value: str, label: str) -> str:
    text = _require_string(value, label).strip().upper()
    if not text:
        raise CanonicalMaterializationError(f"empty {label}")
    _reject_unsafe_string(text, label)
    return text


def _normalize_interval(value: str) -> str:
    text = _require_string(value, "interval").strip().lower()
    if not text:
        raise CanonicalMaterializationError("empty interval")
    _reject_unsafe_string(text, "interval")
    try:
        parse_intraday_interval(text)
    except ValueError as exc:
        raise CanonicalMaterializationError(str(exc)) from exc
    return text


def _normalize_schema(value: str) -> str:
    text = _require_string(value, "source_schema_version").strip()
    if not text:
        raise CanonicalMaterializationError("empty source_schema_version")
    _reject_unsafe_string(text, "source_schema_version")
    return text


def _normalize_trade_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise CanonicalMaterializationError(f"invalid trade date: {value!r}") from exc


def normalize_materialization_request(
    symbols: list[str],
    trade_dates: list[date],
    request_key,
) -> CanonicalMaterializationRequest:
    """Normalize the public request once and validate every string value."""
    normalized_symbols = sorted({_normalize_symbol(symbol, "symbol") for symbol in symbols})
    if not normalized_symbols:
        raise CanonicalMaterializationError("at least one symbol is required")
    normalized_dates = sorted({_normalize_trade_date(value) for value in trade_dates})
    if not normalized_dates:
        raise CanonicalMaterializationError("at least one trade date is required")
    normalized_key = CanonicalRequestKey(
        interval=_normalize_interval(request_key.interval),
        requested_session=_normalize_upper(request_key.requested_session, "requested_session"),
        adjustment=_normalize_upper(request_key.adjustment, "adjustment"),
        source_schema_version=_normalize_schema(request_key.source_schema_version),
    )
    return CanonicalMaterializationRequest(
        symbols=normalized_symbols,
        trade_dates=normalized_dates,
        request_key=normalized_key,
    )


def _normalize_created_at(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise CanonicalMaterializationError("created_at must be timezone-aware")
    return value.astimezone(timezone.utc)


def _validate_build_result(build_result, request: CanonicalMaterializationRequest) -> None:
    """Validate the canonical build result against the normalized request.

    Every emitted bar key must be unique; resolution must contain exactly one
    entry per emitted bar whose selected provenance is the emitting bar's own
    source; and source_snapshot_count must equal the number of stable
    physical source identities referenced by resolution (selected and
    discarded, deduplicated).
    """
    builder_version = build_result.builder_version
    if not builder_version:
        raise CanonicalMaterializationError("build_result.builder_version must be non-empty")
    if build_result.source_snapshot_count < 0:
        raise CanonicalMaterializationError("source_snapshot_count cannot be negative")
    bars = build_result.bars
    resolution = build_result.resolution
    if not bars:
        if resolution:
            raise CanonicalMaterializationError(
                "an empty build must have no resolution entries"
            )
        if build_result.source_snapshot_count != 0:
            raise CanonicalMaterializationError(
                "an empty build must have zero source snapshots"
            )
        return
    if len({bar.canonical_bar_key for bar in bars}) != len(bars):
        raise CanonicalMaterializationError(
            "build result contains duplicate canonical_bar_key values"
        )
    if len(resolution) != len(bars):
        raise CanonicalMaterializationError(
            "resolution must contain exactly one entry per emitted bar"
        )
    emitted_keys = {bar.canonical_bar_key for bar in bars}
    resolution_keys = {entry.canonical_bar_key for entry in resolution}
    if resolution_keys != emitted_keys:
        raise CanonicalMaterializationError(
            "resolution canonical_bar_key values do not exactly match emitted bar keys"
        )
    entry_by_key = {entry.canonical_bar_key: entry for entry in resolution}
    requested_symbols = set(request.symbols)
    requested_dates = set(request.trade_dates)
    key = request.request_key
    source_identities: set[tuple] = set()
    for bar in bars:
        entry = entry_by_key[bar.canonical_bar_key]
        selected = entry.selected
        if (
            selected.ingestion_run_id != bar.ingestion_run_id
            or selected.physical_snapshot_hash != bar.physical_snapshot_hash
            or selected.logical_source_rows_hash != bar.logical_source_rows_hash
            or selected.source_schema_version != bar.source_schema_version
            or selected.requested_trade_date != bar.requested_trade_date
            or selected.requested_session != bar.requested_session
            or selected.snapshot_file != bar.snapshot_file
        ):
            raise CanonicalMaterializationError(
                "resolution selected provenance does not match its canonical bar"
            )
        source_identities.add(
            (
                selected.ingestion_run_id,
                selected.physical_snapshot_hash,
                selected.logical_source_rows_hash,
                selected.requested_trade_date,
                selected.requested_session,
            )
        )
        for ref in entry.equivalent_discarded:
            source_identities.add(
                (
                    ref.ingestion_run_id,
                    ref.physical_snapshot_hash,
                    ref.logical_source_rows_hash,
                    ref.requested_trade_date,
                    ref.requested_session,
                )
            )
        if bar.canonical_builder_version != builder_version:
            raise CanonicalMaterializationError(
                "bar canonical_builder_version does not match build result version"
            )
        if bar.dataset_kind != DEFAULT_DATASET_KIND:
            raise CanonicalMaterializationError(
                f"unexpected dataset_kind {bar.dataset_kind!r}"
            )
        if bar.code not in requested_symbols:
            raise CanonicalMaterializationError(
                f"bar code {bar.code!r} not in requested symbols"
            )
        if bar.requested_trade_date not in requested_dates:
            raise CanonicalMaterializationError(
                f"bar requested_trade_date {bar.requested_trade_date} not in requested dates"
            )
        if (
            bar.interval != key.interval
            or bar.adjustment != key.adjustment
            or bar.requested_session != key.requested_session
            or bar.source_schema_version != key.source_schema_version
        ):
            raise CanonicalMaterializationError(
                "bar request-key fields do not match the normalized request"
            )
    if build_result.source_snapshot_count != len(source_identities):
        raise CanonicalMaterializationError(
            "source_snapshot_count does not match the stable physical source identity count"
        )


def _safe_partition_value(value: str, label: str) -> str:
    text = str(value)
    if not text:
        raise CanonicalMaterializationError(f"empty partition value for {label}")
    if any(character in text for character in ("/", "\\", "\x00", "=")) or ".." in text:
        raise CanonicalMaterializationError(f"unsafe partition value for {label}: {text!r}")
    if any(ord(character) < 32 for character in text):
        raise CanonicalMaterializationError(f"control character in partition value for {label}")
    return text


def load_canonical_snapshot_inputs(
    catalog: Catalog,
    *,
    symbols: list[str],
    trade_dates: list[date],
    request_key,
) -> tuple[CanonicalSnapshotInput, ...]:
    """Load audited COMPLETE snapshots into builder inputs.

    The public request is normalized exactly once here, the same way
    materialization normalizes it, so direct loading and full
    materialization always agree on one request semantics. Uses
    Catalog.latest_complete_market_bar_snapshots exactly (no second
    definition of COMPLETE). Reads only each selected physical snapshot,
    computes its full byte SHA-256 before and after the read, wraps hash and
    read I/O failures as structured errors, and fails closed if the file
    changes while it is being read. A selected snapshot whose file is
    missing is an error, never an EMPTY result; missing or incomplete
    request items are omitted.
    """
    request = normalize_materialization_request(symbols, trade_dates, request_key)
    refs = catalog.latest_complete_market_bar_snapshots(
        symbols=request.symbols,
        trade_dates=request.trade_dates,
        interval=request.request_key.interval,
        requested_session=request.request_key.requested_session,
        adjustment=request.request_key.adjustment,
        source_schema_version=request.request_key.source_schema_version,
    )
    inputs: list[CanonicalSnapshotInput] = []
    for key in sorted(refs):
        ref = refs[key]
        try:
            path = catalog.resolve_snapshot_file(ref.snapshot_file)
        except ValueError as exc:
            raise CanonicalMaterializationError(str(exc)) from exc
        if not path.exists():
            raise CanonicalMaterializationError(
                f"selected snapshot file is missing: {ref.snapshot_file!r}"
            )
        try:
            hash_before = _file_sha256(path)
        except OSError as exc:
            raise CanonicalMaterializationError(
                f"failed to hash selected snapshot {ref.snapshot_file!r}: {exc}"
            ) from exc
        try:
            rows = catalog.market_bar_snapshot_rows(ref).frame
        except Exception as exc:
            raise CanonicalMaterializationError(
                f"failed to read selected snapshot {ref.snapshot_file!r}: {exc}"
            ) from exc
        try:
            hash_after = _file_sha256(path)
        except OSError as exc:
            raise CanonicalMaterializationError(
                f"failed to hash selected snapshot {ref.snapshot_file!r}: {exc}"
            ) from exc
        if hash_before != hash_after:
            raise CanonicalMaterializationError(
                f"snapshot file changed while being read: {ref.snapshot_file!r}"
            )
        inputs.append(
            CanonicalSnapshotInput(
                snapshot=ref,
                rows=rows,
                physical_snapshot_hash=hash_before,
                request_key=request.request_key,
            )
        )
    return tuple(inputs)


def _bars_dataframe(bars) -> pd.DataFrame:
    rows = []
    for bar in bars:
        extra = dict(bar.extra_fields)
        row = {
            "canonical_bar_key": bar.canonical_bar_key,
            "canonical_row_version_id": bar.canonical_row_version_id,
            "dataset_kind": bar.dataset_kind,
            "code": bar.code,
            "interval": bar.interval,
            "adjustment": bar.adjustment,
            "event_time": bar.event_time,
            "market_available_at": bar.market_available_at,
            "archive_available_at": bar.archive_available_at,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "turnover": extra.get("turnover"),
            "last_close": extra.get("last_close"),
            "change_rate": extra.get("change_rate"),
            "pe_ratio": extra.get("pe_ratio"),
            "turnover_rate": extra.get("turnover_rate"),
            "ingestion_run_id": bar.ingestion_run_id,
            "physical_snapshot_hash": bar.physical_snapshot_hash,
            "logical_source_rows_hash": bar.logical_source_rows_hash,
            "source_schema_version": bar.source_schema_version,
            "canonical_builder_version": bar.canonical_builder_version,
            "requested_trade_date": bar.requested_trade_date,
            "requested_session": bar.requested_session,
            "market_calendar_date": bar.market_calendar_date,
            "session": bar.session,
            "snapshot_file": bar.snapshot_file,
        }
        rows.append(row)
    frame = pd.DataFrame(rows, columns=list(CANONICAL_BAR_COLUMNS))
    return frame


def _write_bars_partition(partition_dir: Path, frame: pd.DataFrame) -> Path:
    partition_dir.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(frame, schema=canonical_bars_schema(), preserve_index=False)
    path = partition_dir / "part-00000.parquet"
    pq.write_table(table, path, compression="zstd")
    return path


def _write_bars(build_dir: Path, bars) -> list[tuple[Path, int]]:
    """Write bars partitions; returns (path, actual row count) per file."""
    if not bars:
        return []
    groups: dict[tuple, list] = {}
    for bar in bars:
        key = (
            bar.interval,
            bar.adjustment,
            bar.code,
            bar.market_calendar_date,
        )
        groups.setdefault(key, []).append(bar)
    written: list[tuple[Path, int]] = []
    for key in sorted(groups, key=lambda item: (item[0], item[1], item[2], item[3])):
        interval_value, adjustment, code, market_calendar_date = key
        group_bars = sorted(groups[key], key=lambda bar: (bar.event_time, bar.canonical_bar_key))
        frame = _bars_dataframe(group_bars)
        partition_dir = (
            build_dir
            / "bars"
            / f"interval={_safe_partition_value(interval_value, 'interval')}"
            / f"adjustment={_safe_partition_value(adjustment, 'adjustment')}"
            / f"code={_safe_partition_value(code, 'code')}"
            / f"market_calendar_date={market_calendar_date.isoformat()}"
        )
        written.append((_write_bars_partition(partition_dir, frame), len(frame)))
    return written


GAP_COLUMNS = (
    "gap_id",
    "gap_policy_version",
    "dataset_kind",
    "code",
    "interval",
    "adjustment",
    "market_calendar_date",
    "session",
    "previous_event_time",
    "next_event_time",
    "missing_from_event_time",
    "missing_to_event_time",
    "missing_bar_count",
)


def gap_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("gap_id", pa.string(), nullable=False),
            pa.field("gap_policy_version", pa.string(), nullable=False),
            pa.field("dataset_kind", pa.string(), nullable=False),
            pa.field("code", pa.string(), nullable=False),
            pa.field("interval", pa.string(), nullable=False),
            pa.field("adjustment", pa.string(), nullable=False),
            pa.field("market_calendar_date", pa.date32(), nullable=False),
            pa.field("session", pa.string(), nullable=False),
            pa.field("previous_event_time", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("next_event_time", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("missing_from_event_time", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("missing_to_event_time", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("missing_bar_count", pa.int64(), nullable=False),
        ]
    )


def _gap_dataframe(gaps) -> pd.DataFrame:
    rows = []
    for gap in gaps:
        rows.append(
            {
                "gap_id": gap.gap_id,
                "gap_policy_version": gap.gap_policy_version,
                "dataset_kind": gap.dataset_kind,
                "code": gap.code,
                "interval": gap.interval,
                "adjustment": gap.adjustment,
                "market_calendar_date": gap.market_calendar_date,
                "session": gap.session,
                "previous_event_time": gap.previous_event_time,
                "next_event_time": gap.next_event_time,
                "missing_from_event_time": gap.missing_from_event_time,
                "missing_to_event_time": gap.missing_to_event_time,
                "missing_bar_count": gap.missing_bar_count,
            }
        )
    return pd.DataFrame(rows, columns=list(GAP_COLUMNS))


def _write_gaps(build_dir: Path, gaps) -> list[tuple[Path, int]]:
    """Write gaps partitions; returns (path, actual row count) per file."""
    if not gaps:
        return []
    groups: dict[tuple, list] = {}
    for gap in gaps:
        key = (gap.interval, gap.adjustment, gap.code, gap.market_calendar_date)
        groups.setdefault(key, []).append(gap)
    written: list[tuple[Path, int]] = []
    for key in sorted(groups, key=lambda item: (item[0], item[1], item[2], item[3])):
        interval_value, adjustment, code, market_calendar_date = key
        group_gaps = sorted(
            groups[key], key=lambda gap: (gap.previous_event_time, gap.gap_id)
        )
        frame = _gap_dataframe(group_gaps)
        partition_dir = (
            build_dir
            / "gaps"
            / f"interval={_safe_partition_value(interval_value, 'interval')}"
            / f"adjustment={_safe_partition_value(adjustment, 'adjustment')}"
            / f"code={_safe_partition_value(code, 'code')}"
            / f"market_calendar_date={market_calendar_date.isoformat()}"
        )
        partition_dir.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pandas(frame, schema=gap_schema(), preserve_index=False)
        path = partition_dir / "part-00000.parquet"
        pq.write_table(table, path, compression="zstd")
        written.append((path, len(frame)))
    return written


def _resolution_jsonl_rows(resolution) -> list[dict]:
    rows = []
    for entry in resolution:
        rows.append(
            {
                "canonical_bar_key": entry.canonical_bar_key,
                "selected": _source_ref_dict(entry.selected),
                "equivalent_discarded_sources": [
                    _source_ref_dict(ref) for ref in entry.equivalent_discarded
                ],
            }
        )
    return rows


def _source_ref_dict(ref) -> dict:
    return {
        "ingestion_run_id": ref.ingestion_run_id,
        "physical_snapshot_hash": ref.physical_snapshot_hash,
        "logical_source_rows_hash": ref.logical_source_rows_hash,
        "source_schema_version": ref.source_schema_version,
        "requested_trade_date": ref.requested_trade_date.isoformat(),
        "requested_session": ref.requested_session,
        # Descriptive provenance only; never part of any identity.
        "snapshot_file": ref.snapshot_file,
    }


def _write_resolution_jsonl(build_dir: Path, resolution) -> Path:
    path = build_dir / "resolution.jsonl"
    lines = []
    for row in _resolution_jsonl_rows(resolution):
        lines.append(
            json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        )
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


def _source_provenance_rows(resolution) -> list[dict]:
    """Ordered, deduplicated source snapshot provenance from resolution entries.

    ``snapshot_file`` is descriptive provenance only; identities are
    path-independent.
    """
    rows = []
    seen: set = set()
    for entry in resolution:
        refs = (entry.selected,) + tuple(entry.equivalent_discarded)
        for ref in refs:
            identity = (
                ref.ingestion_run_id,
                ref.physical_snapshot_hash,
                ref.logical_source_rows_hash,
                ref.requested_trade_date,
                ref.requested_session,
            )
            if identity in seen:
                continue
            seen.add(identity)
            rows.append(
                {
                    "ingestion_run_id": ref.ingestion_run_id,
                    "physical_snapshot_hash": ref.physical_snapshot_hash,
                    "logical_source_rows_hash": ref.logical_source_rows_hash,
                    "requested_trade_date": ref.requested_trade_date.isoformat(),
                    "requested_session": ref.requested_session,
                    "snapshot_file": ref.snapshot_file,
                }
            )
    rows.sort(
        key=lambda row: (
            row["ingestion_run_id"],
            row["physical_snapshot_hash"],
            row["requested_trade_date"],
        )
    )
    return rows


def _file_record(path: Path, build_root: Path, *, file_role: str, row_count: int | None, content_role: str) -> dict:
    return {
        "relative_path": path.relative_to(build_root).as_posix(),
        "file_role": file_role,
        "row_count": row_count,
        "byte_size": path.stat().st_size,
        "sha256": _file_sha256(path),
        "content_role": content_role,
    }


def _materialize_build(
    build_result,
    request: CanonicalMaterializationRequest,
    *,
    output_root: Path,
    created_at: datetime,
) -> CanonicalMaterializationResult:
    _validate_build_result(build_result, request)
    builder_version = build_result.builder_version
    created_at = _normalize_created_at(created_at)

    interval_seconds = int(parse_intraday_interval(request.request_key.interval).total_seconds())
    bars = build_result.bars
    gaps = (
        derive_internal_gap_ranges(bars, interval_seconds)
        if bars
        else ()
    )
    content_id = canonical_content_id(bars)
    resolution_id = resolution_content_id(build_result.resolution)
    gap_id = gap_content_id(gaps, GAP_POLICY_VERSION)
    selected_row_version_ids = sorted({bar.canonical_row_version_id for bar in bars})
    build_id = canonical_build_id(
        symbols=request.symbols,
        trade_dates=request.trade_dates,
        request_key=request.request_key,
        canonical_content_id=content_id,
        resolution_content_id=resolution_id,
        gap_content_id=gap_id,
        selected_row_version_ids=selected_row_version_ids,
        canonical_builder_version=builder_version,
        canonical_schema_version=CANONICAL_SCHEMA_VERSION,
        materializer_version=CANONICAL_MATERIALIZER_VERSION,
        gap_policy_version=GAP_POLICY_VERSION,
    )

    build_root = output_root / f"build_id={build_id}"
    if build_root.exists():
        return _existing_build_result(
            build_root,
            expected={
                "build_id": build_id,
                "content_id": content_id,
                "resolution_id": resolution_id,
                "gap_id": gap_id,
                "builder_version": builder_version,
                "schema_version": CANONICAL_SCHEMA_VERSION,
                "materializer_version": CANONICAL_MATERIALIZER_VERSION,
                "gap_policy_version": GAP_POLICY_VERSION,
                "request": request,
                "source_snapshot_count": build_result.source_snapshot_count,
                "row_count": len(bars),
                "gap_count": len(gaps),
                "resolution_count": len(build_result.resolution),
                "min_event_time": min((bar.event_time for bar in bars), default=None),
                "max_event_time": max((bar.event_time for bar in bars), default=None),
                "min_archive_available_at": min((bar.archive_available_at for bar in bars), default=None),
                "max_archive_available_at": max((bar.archive_available_at for bar in bars), default=None),
            },
        )

    temp_dir = output_root / f".{build_id}.tmp-{uuid.uuid4().hex[:12]}"
    temp_dir.mkdir(parents=True, exist_ok=False)
    try:
        bar_files = _write_bars(temp_dir, bars)
        gap_files = _write_gaps(temp_dir, gaps)
        resolution_path = _write_resolution_jsonl(temp_dir, build_result.resolution)

        file_records = []
        file_records.extend(
            _file_record(path, temp_dir, file_role="bars", row_count=count, content_role=CANONICAL_SCHEMA_VERSION)
            for path, count in bar_files
        )
        file_records.extend(
            _file_record(path, temp_dir, file_role="gaps", row_count=count, content_role="canonical-internal-gaps")
            for path, count in gap_files
        )
        file_records.append(
            _file_record(resolution_path, temp_dir, file_role="resolution", row_count=len(build_result.resolution), content_role="canonical-resolution-jsonl")
        )

        min_event = min((bar.event_time for bar in bars), default=None)
        max_event = max((bar.event_time for bar in bars), default=None)
        min_archive = min((bar.archive_available_at for bar in bars), default=None)
        max_archive = max((bar.archive_available_at for bar in bars), default=None)

        manifest_payload = build_manifest(
            status=STATUS_COMPLETE if bars else STATUS_EMPTY,
            dataset_kind=DEFAULT_DATASET_KIND,
            canonical_build_id=build_id,
            canonical_content_id=content_id,
            resolution_content_id=resolution_id,
            gap_content_id=gap_id,
            canonical_builder_version=builder_version,
            canonical_schema_version=CANONICAL_SCHEMA_VERSION,
            materializer_version=CANONICAL_MATERIALIZER_VERSION,
            gap_policy_version=GAP_POLICY_VERSION,
            created_at=created_at,
            symbols=request.symbols,
            trade_dates=request.trade_dates,
            request_key=request.request_key,
            source_snapshot_count=build_result.source_snapshot_count,
            canonical_row_count=len(bars),
            gap_range_count=len(gaps),
            resolution_row_count=len(build_result.resolution),
            min_event_time=min_event,
            max_event_time=max_event,
            min_archive_available_at=min_archive,
            max_archive_available_at=max_archive,
            source_snapshot_provenance=_source_provenance_rows(build_result.resolution),
            output_files=file_records,
        )
        manifest_path = temp_dir / "manifest.json"
        write_manifest_json(manifest_path, manifest_payload)
        success_path = temp_dir / "_SUCCESS"
        success_path.write_text("", encoding="utf-8")

        temp_dir.rename(build_root)
    except BaseException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    return CanonicalMaterializationResult(
        canonical_build_id=build_id,
        canonical_content_id=content_id,
        status=STATUS_COMPLETE if bars else STATUS_EMPTY,
        build_path=build_root.resolve(),
        manifest_path=(build_root / "manifest.json").resolve(),
        row_count=len(bars),
        gap_count=len(gaps),
        source_snapshot_count=build_result.source_snapshot_count,
        created_new_build=True,
    )


_FILE_RECORD_FIELDS = (
    "relative_path",
    "file_role",
    "row_count",
    "byte_size",
    "sha256",
    "content_role",
)

_FILE_ROLES = ("bars", "gaps", "resolution")


def _validate_existing_output_files(build_root: Path, payload: dict) -> list[dict]:
    """Strictly validate manifest output file records and actual files.

    Every record is checked for exactly the required fields with strict
    types; the file_role must match the canonical path location; neither the
    file itself nor any path component may be a symlink; and the recorded
    byte size, actual row count (Parquet metadata / JSONL lines), and SHA-256
    must match the real files. Returns the parsed resolution entries for
    provenance validation.
    """
    output_files = payload.get("output_files")
    if not isinstance(output_files, list):
        raise CanonicalMaterializationError(
            f"existing build output_files must be a list: {build_root}"
        )
    seen_paths: set[str] = set()
    resolution_entries: list[dict] = []
    for record in output_files:
        if not isinstance(record, dict):
            raise CanonicalMaterializationError(
                f"malformed output file record: {build_root}"
            )
        missing = sorted(field for field in _FILE_RECORD_FIELDS if field not in record)
        if missing:
            raise CanonicalMaterializationError(
                f"output file record missing required field(s): {', '.join(missing)}"
            )
        unknown = sorted(set(record) - set(_FILE_RECORD_FIELDS))
        if unknown:
            raise CanonicalMaterializationError(
                f"output file record unknown field(s): {', '.join(unknown)}"
            )
        relative = record["relative_path"]
        file_role = record["file_role"]
        row_count = record["row_count"]
        byte_size = record["byte_size"]
        sha256 = record["sha256"]
        content_role = record["content_role"]
        if not isinstance(relative, str) or not relative:
            raise CanonicalMaterializationError(
                f"output file record relative_path must be a non-empty string: {build_root}"
            )
        if file_role not in _FILE_ROLES:
            raise CanonicalMaterializationError(
                f"output file record unknown file_role {file_role!r}: {build_root}"
            )
        if (
            not isinstance(row_count, int)
            or isinstance(row_count, bool)
            or row_count < 0
        ):
            raise CanonicalMaterializationError(
                f"output file record row_count must be a non-negative integer: {build_root}"
            )
        if (
            not isinstance(byte_size, int)
            or isinstance(byte_size, bool)
            or byte_size < 0
        ):
            raise CanonicalMaterializationError(
                f"output file record byte_size must be a non-negative integer: {build_root}"
            )
        if not isinstance(sha256, str) or not sha256:
            raise CanonicalMaterializationError(
                f"output file record sha256 must be a non-empty string: {build_root}"
            )
        if not isinstance(content_role, str) or not content_role:
            raise CanonicalMaterializationError(
                f"output file record content_role must be a non-empty string: {build_root}"
            )
        if relative in seen_paths:
            raise CanonicalMaterializationError(
                f"duplicate output file relative_path {relative!r}: {build_root}"
            )
        seen_paths.add(relative)
        parts = relative.split("/")
        if (
            relative.startswith("/")
            or "\\" in relative
            or not parts
            or any(part in ("", ".", "..") for part in parts)
            or any(part.startswith("/") for part in parts)
        ):
            raise CanonicalMaterializationError(
                f"unsafe output file relative_path {relative!r}: {build_root}"
            )
        if file_role == "resolution":
            if relative != "resolution.jsonl":
                raise CanonicalMaterializationError(
                    f"file_role resolution does not match path {relative!r}: {build_root}"
                )
        elif not relative.startswith(file_role + "/"):
            raise CanonicalMaterializationError(
                f"file_role {file_role!r} does not match path {relative!r}: {build_root}"
            )
        # Reject a symlink (or Windows directory junction) in the file itself
        # and in every path component; a resolved link inside the root would
        # otherwise pass the escape check.
        current = build_root
        for part in parts:
            current = current / part
            if current.is_symlink() or (
                hasattr(current, "is_junction") and current.is_junction()
            ):
                raise CanonicalMaterializationError(
                    f"output file path contains a symlink: {relative!r}"
                )
        resolved = current.resolve()
        if not resolved.is_relative_to(build_root.resolve()):
            raise CanonicalMaterializationError(
                f"output file path escapes build root: {relative!r}"
            )
        if not current.is_file():
            raise CanonicalMaterializationError(
                f"output file is not a regular file: {relative!r}"
            )
        try:
            actual_size = current.stat().st_size
        except OSError as exc:
            raise CanonicalMaterializationError(
                f"failed to stat output file {relative!r}: {exc}"
            ) from exc
        if actual_size != byte_size:
            raise CanonicalMaterializationError(
                f"output file byte size mismatch: {relative!r}"
            )
        if file_role in ("bars", "gaps"):
            try:
                actual_rows = pq.read_metadata(current).num_rows
            except OSError as exc:
                raise CanonicalMaterializationError(
                    f"failed to read output file {relative!r}: {exc}"
                ) from exc
        else:
            try:
                text = current.read_text(encoding="utf-8")
            except OSError as exc:
                raise CanonicalMaterializationError(
                    f"failed to read output file {relative!r}: {exc}"
                ) from exc
            lines = text.splitlines()
            actual_rows = len(lines)
            for line_number, line in enumerate(lines, start=1):
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise CanonicalMaterializationError(
                        f"resolution.jsonl line {line_number} is not valid JSON: {relative!r}"
                    ) from exc
                if not isinstance(parsed, dict):
                    raise CanonicalMaterializationError(
                        f"resolution.jsonl line {line_number} is not an object: {relative!r}"
                    )
                resolution_entries.append(parsed)
        if actual_rows != row_count:
            raise CanonicalMaterializationError(
                f"output file row count mismatch: {relative!r}"
            )
        try:
            digest = _file_sha256(current)
        except OSError as exc:
            raise CanonicalMaterializationError(
                f"failed to hash output file {relative!r}: {exc}"
            ) from exc
        if digest != sha256:
            raise CanonicalMaterializationError(
                f"output file sha256 mismatch: {relative!r}"
            )
    roles = {record["file_role"] for record in output_files}
    if "resolution" not in roles:
        raise CanonicalMaterializationError(
            f"existing build is missing its resolution file: {build_root}"
        )
    return resolution_entries


def _validate_manifest_provenance(
    payload: dict, resolution_entries: list[dict], build_root: Path
) -> None:
    """source_snapshot_provenance must be strictly shaped and must exactly
    match the stable physical source identities referenced by resolution."""
    provenance = payload.get("source_snapshot_provenance")
    if not isinstance(provenance, list):
        raise CanonicalMaterializationError(
            f"existing build source_snapshot_provenance must be a list: {build_root}"
        )
    expected_fields = (
        "ingestion_run_id",
        "physical_snapshot_hash",
        "logical_source_rows_hash",
        "requested_trade_date",
        "requested_session",
        "snapshot_file",
    )
    identities: set[tuple] = set()
    for row in provenance:
        if not isinstance(row, dict):
            raise CanonicalMaterializationError(
                f"malformed source_snapshot_provenance record: {build_root}"
            )
        missing = sorted(field for field in expected_fields if field not in row)
        if missing:
            raise CanonicalMaterializationError(
                f"source_snapshot_provenance record missing field(s): {', '.join(missing)}"
            )
        for field in (
            "ingestion_run_id",
            "physical_snapshot_hash",
            "logical_source_rows_hash",
            "requested_session",
            "snapshot_file",
        ):
            value = row[field]
            if not isinstance(value, str) or not value:
                raise CanonicalMaterializationError(
                    f"source_snapshot_provenance {field} must be a non-empty string: {build_root}"
                )
        trade_date = row["requested_trade_date"]
        try:
            date.fromisoformat(trade_date)
        except (TypeError, ValueError) as exc:
            raise CanonicalMaterializationError(
                f"source_snapshot_provenance requested_trade_date must be an ISO date: {build_root}"
            ) from exc
        identities.add(
            (
                row["ingestion_run_id"],
                row["physical_snapshot_hash"],
                row["logical_source_rows_hash"],
                trade_date,
                row["requested_session"],
            )
        )
    resolution_identities: set[tuple] = set()
    for entry in resolution_entries:
        refs = [entry.get("selected")] + list(entry.get("equivalent_discarded_sources") or ())
        for ref in refs:
            if not isinstance(ref, dict):
                raise CanonicalMaterializationError(
                    f"resolution source reference is not an object: {build_root}"
                )
            resolution_identities.add(
                (
                    ref.get("ingestion_run_id"),
                    ref.get("physical_snapshot_hash"),
                    ref.get("logical_source_rows_hash"),
                    ref.get("requested_trade_date"),
                    ref.get("requested_session"),
                )
            )
    if identities != resolution_identities:
        raise CanonicalMaterializationError(
            f"source_snapshot_provenance does not match resolution sources: {build_root}"
        )


def _existing_build_result(build_root: Path, expected: dict) -> CanonicalMaterializationResult:
    manifest_path = build_root / "manifest.json"
    success_path = build_root / "_SUCCESS"
    if not (manifest_path.exists() and success_path.exists()):
        raise CanonicalMaterializationError(
            f"existing build directory is incomplete: {build_root}"
        )
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise CanonicalMaterializationError(
            f"existing build manifest is unreadable: {build_root}"
        ) from exc
    if payload.get("manifest_schema_version") != MANIFEST_SCHEMA_VERSION:
        raise CanonicalMaterializationError(
            f"existing build manifest schema mismatch: {build_root}"
        )
    _require_equal(payload, "dataset_kind", DEFAULT_DATASET_KIND, build_root)
    _require_equal(
        payload,
        "gap_policy_limitations",
        list(GAP_POLICY_LIMITATIONS),
        build_root,
    )
    _require_equal(payload, "canonical_build_id", expected["build_id"], build_root)
    _require_equal(payload, "canonical_content_id", expected["content_id"], build_root)
    _require_equal(payload, "resolution_content_id", expected["resolution_id"], build_root)
    _require_equal(payload, "gap_content_id", expected["gap_id"], build_root)
    _require_equal(payload, "canonical_builder_version", expected["builder_version"], build_root)
    _require_equal(payload, "canonical_schema_version", expected["schema_version"], build_root)
    _require_equal(payload, "materializer_version", expected["materializer_version"], build_root)
    _require_equal(payload, "gap_policy_version", expected["gap_policy_version"], build_root)
    _require_equal(payload, "source_snapshot_count", expected["source_snapshot_count"], build_root)
    _require_equal(payload, "canonical_row_count", expected["row_count"], build_root)
    _require_equal(payload, "gap_range_count", expected["gap_count"], build_root)
    _require_equal(payload, "resolution_row_count", expected["resolution_count"], build_root)
    _require_equal(payload, "min_event_time", _utc_iso_or_none(expected["min_event_time"]), build_root)
    _require_equal(payload, "max_event_time", _utc_iso_or_none(expected["max_event_time"]), build_root)
    _require_equal(payload, "min_archive_available_at", _utc_iso_or_none(expected["min_archive_available_at"]), build_root)
    _require_equal(payload, "max_archive_available_at", _utc_iso_or_none(expected["max_archive_available_at"]), build_root)

    request = expected["request"]
    request_section = payload.get("normalized_request")
    if not isinstance(request_section, dict):
        raise CanonicalMaterializationError(
            f"existing build missing normalized_request: {build_root}"
        )
    expected_request = {
        "symbols": request.symbols,
        "trade_dates": sorted(value.isoformat() for value in request.trade_dates),
        "interval": request.request_key.interval,
        "requested_session": request.request_key.requested_session,
        "adjustment": request.request_key.adjustment,
        "source_schema_version": request.request_key.source_schema_version,
    }
    if request_section != expected_request:
        raise CanonicalMaterializationError(
            f"existing build normalized_request mismatch: {build_root}"
        )

    status = payload.get("status")
    _require_equal(payload, "status", expected["status"] if "status" in expected else (STATUS_COMPLETE if expected["row_count"] else STATUS_EMPTY), build_root)
    resolution_entries = _validate_existing_output_files(build_root, payload)
    _validate_manifest_provenance(payload, resolution_entries, build_root)
    bar_files = [r for r in payload["output_files"] if r.get("file_role") == "bars"]
    gap_files = [r for r in payload["output_files"] if r.get("file_role") == "gaps"]
    if status == STATUS_COMPLETE:
        if not bar_files:
            raise CanonicalMaterializationError(
                f"COMPLETE build must contain bar files: {build_root}"
            )
        if gap_files and expected["gap_count"] == 0:
            raise CanonicalMaterializationError(
                f"unexpected gap files in build: {build_root}"
            )
    elif status == STATUS_EMPTY:
        if bar_files or gap_files:
            raise CanonicalMaterializationError(
                f"EMPTY build must contain no bar/gap files: {build_root}"
            )

    return CanonicalMaterializationResult(
        canonical_build_id=payload["canonical_build_id"],
        canonical_content_id=payload["canonical_content_id"],
        status=status,
        build_path=build_root.resolve(),
        manifest_path=manifest_path.resolve(),
        row_count=int(payload["canonical_row_count"]),
        gap_count=int(payload["gap_range_count"]),
        source_snapshot_count=int(payload["source_snapshot_count"]),
        created_new_build=False,
    )


def _require_equal(payload: dict, key: str, expected, build_root: Path) -> None:
    if payload.get(key) != expected:
        raise CanonicalMaterializationError(
            f"existing build {key} mismatch: {build_root}"
        )


def _utc_iso_or_none(value) -> str | None:
    if value is None:
        return None
    return value.tz_convert("UTC").isoformat()


def materialize_canonical_market_bars(
    catalog: Catalog,
    *,
    symbols: list[str],
    trade_dates: list[date],
    request_key,
    output_root: Path | None = None,
    created_at: datetime | None = None,
) -> CanonicalMaterializationResult:
    """High-level immutable canonical build materialization.

    Loads COMPLETE snapshots, builds canonical rows, derives gaps and
    identities, and atomically commits one immutable build directory. An
    empty COMPLETE selection produces a valid explicit EMPTY build. The
    public request is normalized once and used for selection, builder inputs,
    validation, identities, the manifest, and partitioning.
    """
    request = normalize_materialization_request(symbols, trade_dates, request_key)
    inputs = load_canonical_snapshot_inputs(
        catalog,
        symbols=request.symbols,
        trade_dates=request.trade_dates,
        request_key=request.request_key,
    )
    build_result = build_canonical_market_bars(list(inputs))
    root = output_root or (
        catalog.settings.data_root / "canonical" / DATASET_DIR_NAME
    )
    return _materialize_build(
        build_result,
        request,
        output_root=root,
        created_at=created_at,
    )


def materialize_build_result(
    build_result,
    request: CanonicalMaterializationRequest,
    *,
    output_root: Path,
    created_at: datetime,
) -> CanonicalMaterializationResult:
    """Lower-level writer accepting an existing CanonicalBuildResult.

    Provided for deterministic offline tests and callers that already hold a
    built result. The request is normalized again so equivalent casing or
    whitespace cannot change the build identity.
    """
    normalized_request = normalize_materialization_request(
        request.symbols,
        request.trade_dates,
        request.request_key,
    )
    return _materialize_build(
        build_result,
        normalized_request,
        output_root=output_root,
        created_at=created_at,
    )
