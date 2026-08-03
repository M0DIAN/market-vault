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
from .bars import CANONICAL_BUILDER_VERSION, DEFAULT_DATASET_KIND, build_canonical_market_bars, parse_intraday_interval
from .gaps import GAP_POLICY_VERSION, derive_internal_gap_ranges
from .identity import (
    canonical_build_id,
    canonical_content_id,
    gap_content_id,
    resolution_content_id,
)
from .manifest import (
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

    Uses Catalog.latest_complete_market_bar_snapshots exactly (no second
    definition of COMPLETE). Reads only each selected physical snapshot,
    computes its full byte SHA-256, and fails closed if the file changes
    while it is being read. A selected snapshot whose file is missing is an
    error, never an EMPTY result; missing or incomplete request items are
    omitted.
    """
    refs = catalog.latest_complete_market_bar_snapshots(
        symbols=symbols,
        trade_dates=trade_dates,
        interval=request_key.interval,
        requested_session=request_key.requested_session,
        adjustment=request_key.adjustment,
        source_schema_version=request_key.source_schema_version,
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
        hash_before = _file_sha256(path)
        try:
            rows = catalog.market_bar_snapshot_rows(ref).frame
        except Exception as exc:
            raise CanonicalMaterializationError(
                f"failed to read selected snapshot {ref.snapshot_file!r}: {exc}"
            ) from exc
        hash_after = _file_sha256(path)
        if hash_before != hash_after:
            raise CanonicalMaterializationError(
                f"snapshot file changed while being read: {ref.snapshot_file!r}"
            )
        inputs.append(
            CanonicalSnapshotInput(
                snapshot=ref,
                rows=rows,
                physical_snapshot_hash=hash_before,
                request_key=request_key,
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


def _write_bars(build_dir: Path, bars) -> list[Path]:
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
    written: list[Path] = []
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
        written.append(_write_bars_partition(partition_dir, frame))
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


def _write_gaps(build_dir: Path, gaps) -> list[Path]:
    if not gaps:
        return []
    groups: dict[tuple, list] = {}
    for gap in gaps:
        key = (gap.interval, gap.adjustment, gap.code, gap.market_calendar_date)
        groups.setdefault(key, []).append(gap)
    written: list[Path] = []
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
        written.append(path)
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
        canonical_builder_version=CANONICAL_BUILDER_VERSION,
        canonical_schema_version=CANONICAL_SCHEMA_VERSION,
        materializer_version=CANONICAL_MATERIALIZER_VERSION,
        gap_policy_version=GAP_POLICY_VERSION,
    )

    build_root = output_root / f"build_id={build_id}"
    if build_root.exists():
        return _existing_build_result(build_root, build_id)

    created_at = created_at.astimezone(timezone.utc)
    temp_dir = output_root / f".{build_id}.tmp-{uuid.uuid4().hex[:12]}"
    temp_dir.mkdir(parents=True, exist_ok=False)
    try:
        bar_files = _write_bars(temp_dir, bars)
        gap_files = _write_gaps(temp_dir, gaps)
        resolution_path = _write_resolution_jsonl(temp_dir, build_result.resolution)

        file_records = []
        file_records.extend(
            _file_record(path, temp_dir, file_role="bars", row_count=None, content_role=CANONICAL_SCHEMA_VERSION)
            for path in bar_files
        )
        file_records.extend(
            _file_record(path, temp_dir, file_role="gaps", row_count=None, content_role="canonical-internal-gaps")
            for path in gap_files
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
            canonical_builder_version=CANONICAL_BUILDER_VERSION,
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


def _existing_build_result(build_root: Path, build_id: str) -> CanonicalMaterializationResult:
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
    if payload.get("canonical_build_id") != build_id:
        raise CanonicalMaterializationError(
            f"existing build conflicts with the expected build id: {build_root}"
        )
    # Optionally validate recorded file hashes against actual bytes.
    for record in payload.get("output_files", []):
        relative = record.get("relative_path")
        expected = record.get("sha256")
        if not relative or not expected:
            continue
        path = build_root / relative
        if not path.exists() or _file_sha256(path) != expected:
            raise CanonicalMaterializationError(
                f"existing build file hash mismatch: {build_root / relative}"
            )
    return CanonicalMaterializationResult(
        canonical_build_id=payload.get("canonical_build_id", build_id),
        canonical_content_id=payload.get("canonical_content_id", ""),
        status=payload.get("status", STATUS_EMPTY),
        build_path=build_root.resolve(),
        manifest_path=manifest_path.resolve(),
        row_count=int(payload.get("canonical_row_count", 0)),
        gap_count=int(payload.get("gap_range_count", 0)),
        source_snapshot_count=int(payload.get("source_snapshot_count", 0)),
        created_new_build=False,
    )


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
    empty COMPLETE selection produces a valid explicit EMPTY build.
    """
    inputs = load_canonical_snapshot_inputs(
        catalog,
        symbols=symbols,
        trade_dates=trade_dates,
        request_key=request_key,
    )
    build_result = build_canonical_market_bars(list(inputs))
    request = CanonicalMaterializationRequest(
        symbols=sorted(set(symbols)),
        trade_dates=sorted(set(trade_dates)),
        request_key=request_key,
    )
    root = output_root or (
        catalog.settings.data_root / "canonical" / DATASET_DIR_NAME
    )
    return _materialize_build(
        build_result,
        request,
        output_root=root,
        created_at=created_at or datetime.now(timezone.utc),
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
    built result.
    """
    return _materialize_build(
        build_result,
        request,
        output_root=output_root,
        created_at=created_at,
    )
