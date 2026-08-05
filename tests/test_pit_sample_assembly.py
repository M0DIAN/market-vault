"""Offline deterministic tests for two-clock point-in-time sample assembly.

Covers the verified Canonical build reader, PIT request normalization,
market-clock and archive-clock selection, Feature/Label window boundaries,
cross-build reconciliation, sample identities, association logical content,
provenance pins and gap references, and strict artifact validation. No
network, no OpenD, no stored market data beyond offline synthetic fixtures.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from market_vault.canonical import (
    CanonicalArtifactValidationError,
    CanonicalRequestKey,
    VerifiedCanonicalRequest,
    canonical_bar_key,
    canonical_build_id,
    canonical_row_version_id,
    gap_content_id,
    load_verified_canonical_build,
    materialize_canonical_market_bars,
    resolution_content_id,
)
from market_vault.canonical.gaps import GAP_POLICY_VERSION, GapRange
from market_vault.canonical.materialization import GAP_COLUMNS, gap_schema
from market_vault.canonical.models import CanonicalResolutionEntry, CanonicalSourceRef
from market_vault.canonical.schema import canonical_bars_schema
from market_vault.dataset import (
    PIT_ASSEMBLER_VERSION,
    PIT_ASSOCIATION_SCHEMA_VERSION,
    PIT_ROLE_FEATURE,
    PIT_ROLE_LABEL,
    PITAssemblyError,
    PITSampleRequest,
    assemble_point_in_time_samples,
    pit_association_content_id,
    pit_association_schema,
    pit_sample_key,
    pit_sample_version_id,
)
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars, normalize_trading_calendar
from market_vault.storage import Catalog, ParquetStore

UTC = timezone.utc
NY = "America/New_York"
DEFAULT_KEY = CanonicalRequestKey(
    interval="1m", requested_session="ALL", adjustment="NONE", source_schema_version="10.9"
)
CREATED_AT = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Offline canonical-build fixtures (mirrors the materialization tests).
# ---------------------------------------------------------------------------


def settings(tmp_path) -> Settings:
    return Settings(
        project_root=tmp_path,
        opend_host="127.0.0.1",
        opend_port=11111,
        data_root=tmp_path / "data",
        catalog_path=tmp_path / "catalog" / "market_vault.duckdb",
        manifest_dir=tmp_path / "manifests",
        report_dir=tmp_path / "reports",
        request_pause_seconds=0,
    )


def calendar(cfg: Settings, *, trade_date: date = date(2026, 7, 1)) -> None:
    frame = pd.DataFrame({"time": [trade_date.isoformat()], "trade_date_type": ["WHOLE"]})
    curated = normalize_trading_calendar(
        frame, market="US", code=None,
        requested_start_date=trade_date, requested_end_date=trade_date,
        captured_at=pd.Timestamp("2026-08-01T01:00:00Z"), source="moomoo",
        source_schema_version=cfg.source_schema_version, run_id="cal",
    )
    ParquetStore(cfg).write_trading_calendar_curated(
        curated, "MARKET", "US", trade_date, trade_date, "cal"
    )
    Catalog(cfg).refresh_trading_calendar_views()


def minute_keys(start: str, count: int) -> list[str]:
    base = pd.Timestamp(start, tz=NY)
    return [
        (base + pd.Timedelta(int(i), unit="m")).strftime("%Y-%m-%d %H:%M:%S")
        for i in range(count)
    ]


def write_snapshot(
    cfg: Settings,
    *,
    code: str,
    trade_date: date,
    run_id: str,
    time_keys: list[str],
    close: float = 100.5,
    run_finished_at: datetime | None = None,
) -> None:
    store = ParquetStore(cfg)
    catalog = Catalog(cfg)
    raw = pd.DataFrame(
        {
            "code": [code] * len(time_keys),
            "name": [code] * len(time_keys),
            "time_key": time_keys,
            "open": [100.0] * len(time_keys),
            "high": [101.0] * len(time_keys),
            "low": [99.0] * len(time_keys),
            "close": [close] * len(time_keys),
            "volume": [100] * len(time_keys),
        }
    )
    curated = normalize_bars(
        raw, requested_trade_date=trade_date, interval="1m",
        requested_session="ALL", adjustment="NONE", source=cfg.source,
        source_schema_version=cfg.source_schema_version, run_id=run_id,
    )
    store.write_curated(curated, trade_date, "1m", [code], "ALL", "NONE", run_id=run_id)
    run = RunManifest(
        requested_trade_date=trade_date, requested_symbols=[code],
        interval="1m", session="ALL", adjustment="NONE", run_id=run_id,
    )
    run.successful_symbols = [code]
    run.status = "SUCCESS"
    run.finished_at = run_finished_at or datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
    catalog.record_run(run)
    catalog.record_quality(run.run_id, [QualityResult("bars_complete", "PASS")])


def output_root(cfg: Settings) -> Path:
    return cfg.data_root / "canonical" / "dataset=market_bars_canonical"


def materialize(cfg: Settings, *, symbols=None, trade_dates=None, root=None,
                created_at=CREATED_AT):
    return materialize_canonical_market_bars(
        Catalog(cfg),
        symbols=symbols or ["US.MU"],
        trade_dates=trade_dates or [date(2026, 7, 1)],
        request_key=DEFAULT_KEY,
        output_root=root or output_root(cfg),
        created_at=created_at,
    )


def verified(build_result):
    return load_verified_canonical_build(build_result.build_path)


def make_builds(tmp_path):
    """Four canonical builds with controlled availability instants:

    A: US.MU 2026-07-01 rows 09:30..09:33 NY, archived 14:00Z
    B: US.NVDA 2026-07-01 rows 09:30..09:31 NY, archived 16:00Z
    C: US.MU 2026-07-01 rows 09:34..09:35 NY, archived 18:00Z
    D: US.NVDA 2026-07-02 rows 09:30..09:31 NY, archived 2026-07-02T14:00Z
    """
    cfg = settings(tmp_path)
    calendar(cfg)
    calendar(cfg, trade_date=date(2026, 7, 2))
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 4),
                   run_finished_at=datetime(2026, 7, 1, 14, 0, tzinfo=UTC))
    build_a = materialize(cfg)
    write_snapshot(cfg, code="US.NVDA", trade_date=date(2026, 7, 1), run_id="run-b",
                   time_keys=minute_keys("2026-07-01 09:30:00", 2),
                   run_finished_at=datetime(2026, 7, 1, 16, 0, tzinfo=UTC))
    build_b = materialize(cfg, symbols=["US.NVDA"])
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-c",
                   time_keys=minute_keys("2026-07-01 09:34:00", 2),
                   run_finished_at=datetime(2026, 7, 1, 18, 0, tzinfo=UTC))
    build_c = materialize(cfg)
    write_snapshot(cfg, code="US.NVDA", trade_date=date(2026, 7, 2), run_id="run-d",
                   time_keys=minute_keys("2026-07-02 09:30:00", 2),
                   run_finished_at=datetime(2026, 7, 2, 14, 0, tzinfo=UTC))
    build_d = materialize(cfg, symbols=["US.NVDA"], trade_dates=[date(2026, 7, 2)])
    return (cfg, *(verified(build) for build in (build_a, build_b, build_c, build_d)))


def make_second_run_build(tmp_path):
    """Build A plus a second build with the same bars from a different run."""
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 4),
                   run_finished_at=datetime(2026, 7, 1, 14, 0, tzinfo=UTC))
    build_a = materialize(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a2",
                   time_keys=minute_keys("2026-07-01 09:30:00", 4),
                   run_finished_at=datetime(2026, 7, 1, 15, 0, tzinfo=UTC))
    build_a2 = materialize(cfg)
    return verified(build_a), verified(build_a2)


def make_duplicate_build_artifacts(tmp_path):
    """The same logical build materialized into two output roots."""
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 4),
                   run_finished_at=datetime(2026, 7, 1, 14, 0, tzinfo=UTC))
    first = materialize(cfg, root=output_root(cfg) / "root-one")
    second = materialize(cfg, root=output_root(cfg) / "root-two")
    return verified(first), verified(second)


def make_gap_build(tmp_path):
    """Build with one internal gap: rows 09:30 and 09:32 (09:31 missing)."""
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-gap",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1)
                   + minute_keys("2026-07-01 09:32:00", 1),
                   run_finished_at=datetime(2026, 7, 1, 14, 0, tzinfo=UTC))
    return verified(materialize(cfg))


def make_multi_symbol_gap_build(tmp_path):
    """Build with one internal gap per symbol (US.MU and US.NVDA)."""
    cfg = settings(tmp_path)
    calendar(cfg)
    gap_keys = minute_keys("2026-07-01 09:30:00", 1) + minute_keys("2026-07-01 09:32:00", 1)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-gap",
                   time_keys=gap_keys,
                   run_finished_at=datetime(2026, 7, 1, 14, 0, tzinfo=UTC))
    write_snapshot(cfg, code="US.NVDA", trade_date=date(2026, 7, 1), run_id="run-gap-nvda",
                   time_keys=gap_keys,
                   run_finished_at=datetime(2026, 7, 1, 14, 0, tzinfo=UTC))
    return verified(materialize(cfg, symbols=["US.MU", "US.NVDA"]))


def make_jul2_gap_build(tmp_path):
    """Build with one internal gap on market-calendar date 2026-07-02."""
    cfg = settings(tmp_path)
    calendar(cfg)
    calendar(cfg, trade_date=date(2026, 7, 2))
    write_snapshot(cfg, code="US.NVDA", trade_date=date(2026, 7, 2), run_id="run-gap-d2",
                   time_keys=minute_keys("2026-07-02 09:30:00", 1)
                   + minute_keys("2026-07-02 09:32:00", 1),
                   run_finished_at=datetime(2026, 7, 2, 14, 0, tzinfo=UTC))
    return verified(materialize(cfg, symbols=["US.NVDA"], trade_dates=[date(2026, 7, 2)]))


def make_duplicate_gap_artifacts(tmp_path):
    """The same gap build materialized into two output roots."""
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-gap",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1)
                   + minute_keys("2026-07-01 09:32:00", 1),
                   run_finished_at=datetime(2026, 7, 1, 14, 0, tzinfo=UTC))
    first = materialize(cfg, root=output_root(cfg) / "root-one")
    second = materialize(cfg, root=output_root(cfg) / "root-two")
    return verified(first), verified(second)


def make_two_symbol_build(tmp_path):
    """Build whose bars come from two different source snapshots (one per
    symbol), so resolution entries carry distinct selected sources."""
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 2),
                   run_finished_at=datetime(2026, 7, 1, 14, 0, tzinfo=UTC))
    write_snapshot(cfg, code="US.NVDA", trade_date=date(2026, 7, 1), run_id="run-b",
                   time_keys=minute_keys("2026-07-01 09:30:00", 2),
                   run_finished_at=datetime(2026, 7, 1, 16, 0, tzinfo=UTC))
    return verified(materialize(cfg, symbols=["US.MU", "US.NVDA"]))


def make_empty_build(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    result = materialize(cfg, symbols=["US.XYZ"])
    assert result.status == "EMPTY"
    return verified(result)


def request(
    *,
    code: str = "US.MU",
    interval: str = "1m",
    adjustment: str = "NONE",
    requested_session: str = "ALL",
    anchor: date = date(2026, 7, 1),
    feature_start=datetime(2026, 7, 1, 13, 30, tzinfo=UTC),
    feature_close=datetime(2026, 7, 1, 13, 32, tzinfo=UTC),
    label_start=None,
    label_close=None,
) -> PITSampleRequest:
    return PITSampleRequest(
        code=code,
        interval=interval,
        adjustment=adjustment,
        requested_session=requested_session,
        anchor_market_calendar_date=anchor,
        feature_window_start=feature_start,
        feature_window_close=feature_close,
        label_window_start=label_start,
        label_window_close=label_close,
    )


def assemble(builds, requests, *, dataset_as_of=None):
    return assemble_point_in_time_samples(builds, requests, dataset_as_of=dataset_as_of)


def mutate_manifest(build, mutate) -> None:
    manifest_path = build.build_path / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    mutate(payload)
    manifest_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def set_column(frame: pd.DataFrame, name: str, values) -> pd.DataFrame:
    frame = frame.copy()
    frame[name] = values
    return frame


def rewrite_bars(build, mutate) -> None:
    """Rewrite every bars parquet through a mutator and re-sync the manifest
    byte sizes and hashes so only the mutation remains."""
    payload = json.loads((build.build_path / "manifest.json").read_text(encoding="utf-8"))
    for record in payload["output_files"]:
        if record["file_role"] != "bars":
            continue
        path = build.build_path / record["relative_path"]
        frame = pd.read_parquet(path)
        frame = mutate(frame)
        table = pa.Table.from_pandas(frame, schema=canonical_bars_schema(), preserve_index=False)
        pq.write_table(table, path, compression="zstd")
        record["byte_size"] = path.stat().st_size
        record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path = build.build_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def recompute_and_rewrite_bars(build, mutate) -> None:
    """Rewrite bars parquets through a mutator, then recompute every row's
    canonical_bar_key / canonical_row_version_id from its own (mutated)
    fields and re-sync the manifest hashes, so the rows remain internally
    consistent and only the mutated fields are left inconsistent with the
    manifest/request contract."""
    payload = json.loads((build.build_path / "manifest.json").read_text(encoding="utf-8"))
    for record in payload["output_files"]:
        if record["file_role"] != "bars":
            continue
        path = build.build_path / record["relative_path"]
        frame = pd.read_parquet(path)
        frame = mutate(frame)
        frame = frame.copy()
        keys = []
        versions = []
        for _, row in frame.iterrows():
            key = canonical_bar_key(
                dataset_kind=row["dataset_kind"],
                code=row["code"],
                interval=row["interval"],
                adjustment=row["adjustment"],
                event_time=pd.Timestamp(row["event_time"]),
            )
            version = canonical_row_version_id(
                canonical_bar_key=key,
                ingestion_run_id=row["ingestion_run_id"],
                source_snapshot_content_hash=row["physical_snapshot_hash"],
                source_schema_version=row["source_schema_version"],
                canonical_builder_version=row["canonical_builder_version"],
            )
            keys.append(key)
            versions.append(version)
        frame["canonical_bar_key"] = keys
        frame["canonical_row_version_id"] = versions
        table = pa.Table.from_pandas(frame, schema=canonical_bars_schema(), preserve_index=False)
        pq.write_table(table, path, compression="zstd")
        record["byte_size"] = path.stat().st_size
        record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path = build.build_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _ref_from_json(ref: dict) -> CanonicalSourceRef:
    return CanonicalSourceRef(
        ingestion_run_id=ref["ingestion_run_id"],
        physical_snapshot_hash=ref["physical_snapshot_hash"],
        logical_source_rows_hash=ref["logical_source_rows_hash"],
        source_schema_version=ref["source_schema_version"],
        snapshot_file=ref["snapshot_file"],
        requested_trade_date=date.fromisoformat(ref["requested_trade_date"]),
        requested_session=ref["requested_session"],
    )


def _entry_from_json(row: dict) -> CanonicalResolutionEntry:
    return CanonicalResolutionEntry(
        canonical_bar_key=row["canonical_bar_key"],
        selected=_ref_from_json(row["selected"]),
        equivalent_discarded=tuple(
            _ref_from_json(ref) for ref in row["equivalent_discarded_sources"]
        ),
    )


def _recompute_build_id(payload: dict, root: Path) -> str:
    req = payload["normalized_request"]
    request_key = CanonicalRequestKey(
        req["interval"], req["requested_session"], req["adjustment"], req["source_schema_version"]
    )
    versions = sorted(
        {
            version
            for path in root.rglob("bars/**/*.parquet")
            for version in pd.read_parquet(path)["canonical_row_version_id"]
        }
    )
    return canonical_build_id(
        symbols=req["symbols"],
        trade_dates=[date.fromisoformat(item) for item in req["trade_dates"]],
        request_key=request_key,
        canonical_content_id=payload["canonical_content_id"],
        resolution_content_id=payload["resolution_content_id"],
        gap_content_id=payload["gap_content_id"],
        selected_row_version_ids=versions,
        canonical_builder_version=payload["canonical_builder_version"],
        canonical_schema_version=payload["canonical_schema_version"],
        materializer_version=payload["materializer_version"],
        gap_policy_version=payload["gap_policy_version"],
    )


def _write_manifest_and_rename(root: Path, payload: dict) -> Path:
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    new_root = root.parent / f"build_id={payload['canonical_build_id']}"
    root.rename(new_root)
    return new_root


def resync_resolution(build, mutated_rows) -> Path:
    """Rewrite resolution.jsonl with swapped rows and re-sync every identity:
    resolution_content_id, canonical_build_id, output hashes, and the build
    directory name, so only the per-key binding is left wrong."""
    root = build.build_path
    payload = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    (root / "resolution.jsonl").write_text(
        "\n".join(
            json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            for row in mutated_rows
        )
        + "\n",
        encoding="utf-8",
    )
    for record in payload["output_files"]:
        if record["file_role"] != "resolution":
            continue
        record["row_count"] = len(mutated_rows)
        record["byte_size"] = (root / "resolution.jsonl").stat().st_size
        record["sha256"] = hashlib.sha256((root / "resolution.jsonl").read_bytes()).hexdigest()
    payload["resolution_content_id"] = resolution_content_id(
        tuple(_entry_from_json(row) for row in mutated_rows)
    )
    payload["canonical_build_id"] = _recompute_build_id(payload, root)
    return _write_manifest_and_rename(root, payload)


def _gap_from_row(row: dict) -> GapRange:
    return GapRange(
        gap_id=row["gap_id"],
        gap_policy_version=row["gap_policy_version"],
        dataset_kind=row["dataset_kind"],
        code=row["code"],
        interval=row["interval"],
        adjustment=row["adjustment"],
        market_calendar_date=row["market_calendar_date"],
        session=row["session"],
        previous_event_time=pd.Timestamp(row["previous_event_time"]),
        next_event_time=pd.Timestamp(row["next_event_time"]),
        missing_from_event_time=pd.Timestamp(row["missing_from_event_time"]),
        missing_to_event_time=pd.Timestamp(row["missing_to_event_time"]),
        missing_bar_count=row["missing_bar_count"],
    )


def _gap_table(rows: list[dict]) -> pa.Table:
    arrays = []
    for field in gap_schema():
        arrays.append(pa.array([row[field.name] for row in rows], type=field.type))
    return pa.table(arrays, schema=gap_schema())


def resync_gap_sidecar(build, gap_rows) -> Path:
    """Rewrite the gap parquet and re-sync gap_content_id, canonical_build_id,
    output hashes/counts, and the build directory name, so the sidecar stays
    internally consistent and only the mismatch against the bars remains."""
    root = build.build_path
    payload = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    gap_file = next(root.rglob("gaps/**/part-00000.parquet"))
    pq.write_table(_gap_table(gap_rows), gap_file, compression="zstd")
    for record in payload["output_files"]:
        if record["file_role"] != "gaps":
            continue
        record["row_count"] = len(gap_rows)
        record["byte_size"] = gap_file.stat().st_size
        record["sha256"] = hashlib.sha256(gap_file.read_bytes()).hexdigest()
    gaps = tuple(_gap_from_row(row) for row in gap_rows)
    payload["gap_range_count"] = len(gaps)
    payload["gap_content_id"] = gap_content_id(gaps, GAP_POLICY_VERSION)
    payload["canonical_build_id"] = _recompute_build_id(payload, root)
    return _write_manifest_and_rename(root, payload)


def relocate_snapshot_files(build) -> None:
    """Consistently relocate snapshot_file across bars parquet, resolution
    JSONL, and manifest provenance (path is descriptive everywhere)."""
    rewrite_bars(build, lambda frame: set_column(frame, "snapshot_file", "curated/moved.parquet"))
    root = build.build_path
    payload = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in (root / "resolution.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    for row in rows:
        row["selected"]["snapshot_file"] = "curated/moved.parquet"
        for ref in row["equivalent_discarded_sources"]:
            ref["snapshot_file"] = "curated/moved.parquet"
    (root / "resolution.jsonl").write_text(
        "\n".join(
            json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            for row in rows
        )
        + "\n",
        encoding="utf-8",
    )
    for row in payload["source_snapshot_provenance"]:
        row["snapshot_file"] = "curated/moved.parquet"
    for record in payload["output_files"]:
        path = root / record["relative_path"]
        record["byte_size"] = path.stat().st_size
        record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / "manifest.json").write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def version_id(
    *,
    sample_key: str | None = None,
    dataset_as_of=None,
    feature=(),
    label=(),
    considered=(),
    assembler_version: str | None = None,
    association_schema_version: str | None = None,
) -> str:
    return pit_sample_version_id(
        sample_key=sample_key or sha("sample"),
        dataset_as_of=dataset_as_of,
        feature_canonical_row_version_ids=feature,
        label_canonical_row_version_ids=label,
        considered_canonical_build_ids=considered,
        assembler_version=assembler_version or PIT_ASSEMBLER_VERSION,
        association_schema_version=association_schema_version
        or PIT_ASSOCIATION_SCHEMA_VERSION,
    )


# ---------------------------------------------------------------------------
# A. Time boundaries.
# ---------------------------------------------------------------------------


def test_event_time_equal_feature_window_start_included(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    result = assemble([a], [request()])
    sample = result.samples[0]
    assert sample.diagnostics.feature_candidate_count == 2
    # Rows at 09:30 and 09:31 NY (13:30/13:31Z) enter the [13:30, 13:32) window.
    assert sample.diagnostics.feature_selected_count == 2
    assert [row["event_time"] for row in result.association_rows if row["role"] == PIT_ROLE_FEATURE] == [
        pd.Timestamp("2026-07-01T13:30:00Z"),
        pd.Timestamp("2026-07-01T13:31:00Z"),
    ]


def test_event_time_equal_feature_window_close_excluded(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    sample = assemble([a], [request()]).samples[0]
    event_times = {bar.event_time for bar in a.bars}
    assert pd.Timestamp("2026-07-01T13:32:00Z") in event_times
    assert all(
        row["event_time"] != pd.Timestamp("2026-07-01T13:32:00Z")
        for row in assemble([a], [request()]).association_rows
    )


def test_market_available_at_equal_feature_window_close_included(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    # The 09:31 row's market_available_at is exactly 09:32 (13:32Z) == close.
    sample = assemble([a], [request()]).samples[0]
    assert sample.diagnostics.feature_market_future_excluded_count == 0
    assert any(
        bar.market_available_at == pd.Timestamp("2026-07-01T13:32:00Z")
        for bar in a.bars
        if bar.event_time == pd.Timestamp("2026-07-01T13:31:00Z")
    )


def test_market_available_at_after_feature_window_close_excluded(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    # Window [13:30:00, 13:31:30): the 09:31 row is a candidate (event < close)
    # but its market_available_at (13:32) is after the close.
    result = assemble(
        [a],
        [request(feature_close=datetime(2026, 7, 1, 13, 31, 30, tzinfo=UTC))],
    )
    sample = result.samples[0]
    assert sample.diagnostics.feature_candidate_count == 2
    assert sample.diagnostics.feature_selected_count == 1
    assert sample.diagnostics.feature_market_future_excluded_count == 1
    assert [row["event_time"] for row in result.association_rows] == [
        pd.Timestamp("2026-07-01T13:30:00Z")
    ]


def test_archive_available_at_equal_dataset_as_of_included(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    sample = assemble(
        [a], [request()], dataset_as_of=datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
    ).samples[0]
    assert sample.diagnostics.feature_selected_count == 2
    assert sample.diagnostics.feature_archive_future_excluded_count == 0


def test_archive_available_at_after_dataset_as_of_excluded(tmp_path):
    _, a, b, *_ = make_builds(tmp_path)
    sample = assemble(
        [a, b],
        [request(code="US.NVDA")],
        dataset_as_of=datetime(2026, 7, 1, 14, 0, tzinfo=UTC),
    ).samples[0]
    assert sample.diagnostics.feature_candidate_count == 2
    assert sample.diagnostics.feature_selected_count == 0
    assert sample.diagnostics.feature_archive_future_excluded_count == 2


def test_no_dataset_as_of_skips_archive_cutoff(tmp_path):
    _, a, b, *_ = make_builds(tmp_path)
    sample = assemble([a, b], [request(code="US.NVDA")]).samples[0]
    assert sample.diagnostics.feature_selected_count == 2
    assert sample.diagnostics.feature_archive_future_excluded_count == 0


def test_feature_never_contains_label_future_rows(tmp_path):
    _, a, b, c, _ = make_builds(tmp_path)
    result = assemble(
        [a, b, c],
        [
            request(
                label_start=datetime(2026, 7, 1, 13, 33, tzinfo=UTC),
                label_close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
            )
        ],
    )
    sample = result.samples[0]
    label_versions = set(sample.label_canonical_row_version_ids)
    assert label_versions
    assert not (set(sample.feature_canonical_row_version_ids) & label_versions)
    assert all(
        row["event_time"] < pd.Timestamp("2026-07-01T13:32:00Z")
        for row in result.association_rows
        if row["role"] == PIT_ROLE_FEATURE
    )


def test_label_row_can_be_after_feature_close(tmp_path):
    _, a, b, c, _ = make_builds(tmp_path)
    label_req = request(
        label_start=datetime(2026, 7, 1, 13, 34, tzinfo=UTC),
        label_close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
    )
    sample = assemble([a, b, c], [label_req]).samples[0]
    # Label rows 13:34/13:35Z (09:34/09:35 NY) are later than the feature close.
    assert sample.diagnostics.label_selected_count == 2
    assert [row["event_time"] for row in assemble([a, b, c], [label_req]).association_rows
            if row["role"] == PIT_ROLE_LABEL] == [
        pd.Timestamp("2026-07-01T13:34:00Z"),
        pd.Timestamp("2026-07-01T13:35:00Z"),
    ]


def test_naive_window_timestamp_fails(tmp_path):
    with pytest.raises(PITAssemblyError):
        PITSampleRequest(
            code="US.MU", interval="1m", adjustment="NONE", requested_session="ALL",
            anchor_market_calendar_date=date(2026, 7, 1),
            feature_window_start=datetime(2026, 7, 1, 13, 30),
            feature_window_close=datetime(2026, 7, 1, 13, 32, tzinfo=UTC),
        )


def test_naive_dataset_as_of_fails(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    with pytest.raises(PITAssemblyError):
        assemble([a], [request()], dataset_as_of=datetime(2026, 7, 1, 14, 0))


def test_equivalent_utc_and_non_utc_representations_identical(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    utc_req = request(
        label_start=datetime(2026, 7, 1, 13, 34, tzinfo=UTC),
        label_close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
    )
    ny_req = request(
        feature_start=datetime(2026, 7, 1, 9, 30, tzinfo=ZoneInfo(NY)),
        feature_close=datetime(2026, 7, 1, 9, 32, tzinfo=ZoneInfo(NY)),
        label_start=datetime(2026, 7, 1, 9, 34, tzinfo=ZoneInfo(NY)),
        label_close=datetime(2026, 7, 1, 9, 36, tzinfo=ZoneInfo(NY)),
    )
    assert pit_sample_key(utc_req) == pit_sample_key(ny_req)
    assert assemble([a], [utc_req]) == assemble([a], [ny_req])


def test_microsecond_precision_normalized(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    nano = request(
        feature_start=pd.Timestamp("2026-07-01T13:30:00.123456789Z"),
        feature_close=pd.Timestamp("2026-07-01T13:32:00.987654321Z"),
    )
    micro = request(
        feature_start=datetime(2026, 7, 1, 13, 30, 0, 123456, tzinfo=UTC),
        feature_close=datetime(2026, 7, 1, 13, 32, 0, 987654, tzinfo=UTC),
    )
    assert nano.feature_window.start == micro.feature_window.start
    assert nano.feature_window.close == micro.feature_window.close
    assert pit_sample_key(nano) == pit_sample_key(micro)


# ---------------------------------------------------------------------------
# B. Label safety.
# ---------------------------------------------------------------------------


def test_label_window_start_before_feature_close_fails():
    with pytest.raises(PITAssemblyError, match="label_window_start"):
        request(
            label_start=datetime(2026, 7, 1, 13, 31, tzinfo=UTC),
            label_close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
        )


def test_single_label_boundary_fails():
    with pytest.raises(PITAssemblyError, match="both boundaries"):
        request(
            label_start=datetime(2026, 7, 1, 13, 33, tzinfo=UTC),
            label_close=None,
        )


def test_cross_market_calendar_date_label_row_fails(tmp_path):
    _, a, b, c, d = make_builds(tmp_path)
    # Build D holds US.NVDA rows of market-calendar date 2026-07-02; the label
    # window selects the 13:31Z row, which is not on the anchor date.
    with pytest.raises(PITAssemblyError, match="cross-market-calendar-date"):
        assemble(
            [a, b, c, d],
            [
                request(
                    code="US.NVDA",
                    feature_start=datetime(2026, 7, 2, 13, 30, tzinfo=UTC),
                    feature_close=datetime(2026, 7, 2, 13, 31, tzinfo=UTC),
                    label_start=datetime(2026, 7, 2, 13, 31, tzinfo=UTC),
                    label_close=datetime(2026, 7, 2, 13, 32, tzinfo=UTC),
                )
            ],
        )


def test_adjustment_not_none_fails():
    with pytest.raises(PITAssemblyError, match="NONE"):
        request(adjustment="ADJ")


def test_label_horizon_not_claimed_complete(tmp_path):
    _, a, b, c, _ = make_builds(tmp_path)
    result = assemble(
        [a, b, c],
        [
            request(
                label_start=datetime(2026, 7, 1, 13, 34, tzinfo=UTC),
                label_close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
            )
        ],
    )
    sample = result.samples[0]
    # The sample records observed rows and known gaps only; no completion
    # claim about the label horizon is exposed anywhere on the result.
    assert not hasattr(sample, "label_status")
    assert not hasattr(result, "completion")
    assert not hasattr(result, "label_completion")
    assert sample.diagnostics.label_selected_count == 2


# ---------------------------------------------------------------------------
# C. Determinism.
# ---------------------------------------------------------------------------


def test_build_input_order_irrelevant(tmp_path):
    _, a, b, *_ = make_builds(tmp_path)
    first = assemble([a, b], [request(), request(code="US.NVDA")])
    second = assemble([b, a], [request(code="US.NVDA"), request()])
    assert first == second


def test_request_input_order_irrelevant(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    req_short = request()
    req_long = request(
        feature_close=datetime(2026, 7, 1, 13, 34, tzinfo=UTC)
    )
    first = assemble([a], [req_short, req_long])
    second = assemble([a], [req_long, req_short])
    assert first == second


def test_row_input_order_irrelevant(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    reversed_build = replace(a, bars=tuple(reversed(a.bars)))
    first = assemble([a], [request()])
    second = assemble([reversed_build], [request()])
    assert first == second


def test_association_row_order_fixed(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    first = assemble([a], [request()])
    second = assemble([a], [request()])
    assert first.association_rows == second.association_rows


def test_positions_fixed(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    rows = assemble([a], [request()]).association_rows
    feature_rows = [row for row in rows if row["role"] == PIT_ROLE_FEATURE]
    assert [row["position"] for row in feature_rows] == [0, 1]


def test_sample_key_stable_across_paths(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    moved = tmp_path / f"build_id={a.canonical_build_id}"
    shutil.copytree(a.build_path, moved)
    moved_build = load_verified_canonical_build(moved)
    assert pit_sample_key(request()) == pit_sample_key(request())
    first = assemble([a], [request()])
    second = assemble([moved_build], [request()])
    assert first.samples[0].sample_key == second.samples[0].sample_key
    assert first.association_content_id == second.association_content_id


def test_row_version_change_changes_sample_version_id(tmp_path):
    a, a2 = make_second_run_build(tmp_path)
    first = assemble([a], [request()])
    second = assemble([a2], [request()])
    assert first.samples[0].sample_key == second.samples[0].sample_key
    assert first.samples[0].sample_version_id != second.samples[0].sample_version_id
    assert first.association_content_id != second.association_content_id


def test_dataset_as_of_change_changes_sample_version_id(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    first = assemble([a], [request()], dataset_as_of=datetime(2026, 7, 1, 14, 0, tzinfo=UTC))
    second = assemble([a], [request()], dataset_as_of=datetime(2026, 7, 1, 16, 0, tzinfo=UTC))
    assert first.samples[0].sample_key == second.samples[0].sample_key
    assert first.samples[0].sample_version_id != second.samples[0].sample_version_id
    third = assemble([a], [request()])
    assert first.samples[0].sample_version_id != third.samples[0].sample_version_id


def test_build_created_at_change_does_not_change_identity(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 4),
                   run_finished_at=datetime(2026, 7, 1, 14, 0, tzinfo=UTC))
    first = materialize(cfg, root=output_root(cfg) / "root-one",
                         created_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    second = materialize(cfg, root=output_root(cfg) / "root-two",
                         created_at=datetime(2026, 8, 2, 12, 0, tzinfo=UTC))
    assert first.canonical_build_id == second.canonical_build_id
    result_one = assemble([verified(first)], [request()])
    result_two = assemble([verified(second)], [request()])
    assert result_one == result_two


def test_zero_row_result_stable_and_schema_tied(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    empty_req = request(code="US.QQQ")
    first = assemble([a], [empty_req])
    second = assemble([a], [empty_req])
    assert first == second
    assert first.association_rows == ()
    assert first.association_content_id == pit_association_content_id(())
    assert first.association_content_id == second.association_content_id
    assert first.samples[0].diagnostics.empty_observation_window is True
    # The zero-row content ID is schema-tied, not request-dependent.
    other = assemble([a], [request(code="US.AAA")])
    assert other.association_content_id == first.association_content_id


# ---------------------------------------------------------------------------
# D. Cross-build overlap and conflicts.
# ---------------------------------------------------------------------------


def test_identical_row_versions_deduplicated(tmp_path):
    first, second = make_duplicate_build_artifacts(tmp_path)
    result = assemble([first, second], [request()])
    sample = result.samples[0]
    assert sample.diagnostics.feature_selected_count == 2
    assert len(sample.feature_canonical_row_version_ids) == 2
    assert len(result.canonical_build_pins) == 1
    assert len(result.gap_references) == 1


def test_different_row_versions_fail(tmp_path):
    a, a2 = make_second_run_build(tmp_path)
    with pytest.raises(PITAssemblyError, match="conflicting canonical candidates"):
        assemble([a, a2], [request()])


def test_same_version_different_market_values_fail(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    tampered = replace(a, bars=tuple(replace(bar, close=999.0) for bar in a.bars))
    with pytest.raises(PITAssemblyError, match="conflicting canonical candidates"):
        assemble([a, tampered], [request()])


def test_duplicate_sample_key_fails(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    with pytest.raises(PITAssemblyError, match="duplicate sample_key"):
        assemble([a], [request(), request()])


def test_row_not_belonging_to_declared_build_fails(tmp_path):
    _, a, b, c, _ = make_builds(tmp_path)
    foreign = replace(a, bars=a.bars + (c.bars[0],))
    with pytest.raises(PITAssemblyError, match="not covered by the declared provenance"):
        assemble([foreign], [request()])


def test_row_version_not_covered_by_build_provenance_fails(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    stripped = replace(a, canonical_row_version_ids=a.canonical_row_version_ids[1:])
    with pytest.raises(PITAssemblyError, match="not covered by the declared provenance"):
        assemble([stripped], [request()])


# ---------------------------------------------------------------------------
# E. Verified Canonical artifact reader.
# ---------------------------------------------------------------------------


def test_valid_complete_build_loads(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    payload = json.loads(a.manifest_payload)
    assert a.status == "COMPLETE"
    assert len(a.bars) == 4
    assert a.gap_count == 0
    assert a.canonical_build_id == payload["canonical_build_id"]
    assert a.canonical_content_id == payload["canonical_content_id"]
    assert a.resolution_content_id == payload["resolution_content_id"]
    assert a.gap_content_id == payload["gap_content_id"]
    assert tuple(sorted(a.canonical_row_version_ids)) == a.canonical_row_version_ids
    assert {bar.canonical_row_version_id for bar in a.bars} == set(a.canonical_row_version_ids)
    assert a.normalized_request.symbols == ("US.MU",)
    assert a.normalized_request.trade_dates == (date(2026, 7, 1),)
    assert len(a.source_snapshot_provenance) == 1
    assert payload["source_snapshot_count"] == 1
    # Bars are in deterministic event_time order.
    assert [bar.event_time for bar in a.bars] == sorted(bar.event_time for bar in a.bars)


def test_valid_empty_build_loads(tmp_path):
    empty = make_empty_build(tmp_path)
    assert empty.status == "EMPTY"
    assert empty.bars == ()
    assert empty.canonical_row_version_ids == ()
    assert empty.gap_ranges == ()
    assert empty.gap_count == 0
    assert empty.source_snapshot_provenance == ()
    # An EMPTY build assembles deterministically with zero associations.
    result = assemble([empty], [request()])
    assert result.samples[0].diagnostics.feature_selected_count == 0
    assert result.association_rows == ()
    assert result.canonical_build_pins[0].status == "EMPTY"
    assert result.canonical_build_pins[0].canonical_row_version_ids == ()


def test_missing_success_fails(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    (a.build_path / "_SUCCESS").unlink()
    with pytest.raises(CanonicalArtifactValidationError, match="_SUCCESS"):
        load_verified_canonical_build(a.build_path)


def test_wrong_manifest_schema_version_fails(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    mutate_manifest(a, lambda payload: payload.__setitem__("manifest_schema_version", "x"))
    with pytest.raises(CanonicalArtifactValidationError, match="schema mismatch"):
        load_verified_canonical_build(a.build_path)


def test_build_dir_id_mismatch_fails(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    build_id = json.loads(a.manifest_payload)["canonical_build_id"]
    wrong = a.build_path.parent / f"build_id={sha('wrong')}"
    a.build_path.rename(wrong)
    with pytest.raises(CanonicalArtifactValidationError, match="does not match manifest"):
        load_verified_canonical_build(wrong)


def test_manifest_sha_mismatch_fails(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    mutate_manifest(
        a,
        lambda payload: payload.__setitem__(
            "output_files", [dict(record, sha256=sha("tampered")) for record in payload["output_files"]]
        ),
    )
    with pytest.raises(CanonicalArtifactValidationError, match="sha256 mismatch"):
        load_verified_canonical_build(a.build_path)


def test_byte_size_mismatch_fails(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    mutate_manifest(
        a,
        lambda payload: payload.__setitem__(
            "output_files", [dict(record, byte_size=record["byte_size"] + 1) for record in payload["output_files"]]
        ),
    )
    with pytest.raises(CanonicalArtifactValidationError, match="byte size mismatch"):
        load_verified_canonical_build(a.build_path)


def test_row_count_mismatch_fails(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    mutate_manifest(
        a,
        lambda payload: payload.__setitem__(
            "output_files", [dict(record, row_count=record["row_count"] + 1) for record in payload["output_files"]]
        ),
    )
    with pytest.raises(CanonicalArtifactValidationError, match="row count mismatch"):
        load_verified_canonical_build(a.build_path)


def test_parquet_schema_mismatch_fails(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    bar_file = next(a.build_path.rglob("bars/**/part-00000.parquet"))
    table = pq.read_table(bar_file)
    reordered = table.select(list(reversed(table.column_names)))
    pq.write_table(reordered, bar_file, compression="zstd")
    mutate_manifest(
        a,
        lambda payload: payload.__setitem__(
            "output_files", [dict(record, byte_size=(a.build_path / record["relative_path"]).stat().st_size,
                                  sha256=hashlib.sha256((a.build_path / record["relative_path"]).read_bytes()).hexdigest())
                             for record in payload["output_files"]]
        ),
    )
    with pytest.raises(CanonicalArtifactValidationError, match="schema mismatch"):
        load_verified_canonical_build(a.build_path)


def test_tampered_canonical_bar_key_fails(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    rewrite_bars(
        a,
        lambda frame: set_column(
            frame, "canonical_bar_key",
            [sha("tampered") if i == 0 else value for i, value in enumerate(frame["canonical_bar_key"])],
        ),
    )
    with pytest.raises(CanonicalArtifactValidationError, match="does not match its recomputed"):
        load_verified_canonical_build(a.build_path)


def test_tampered_canonical_row_version_id_fails(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    rewrite_bars(
        a,
        lambda frame: set_column(
            frame, "canonical_row_version_id",
            [sha("tampered") if i == 0 else value for i, value in enumerate(frame["canonical_row_version_id"])],
        ),
    )
    with pytest.raises(CanonicalArtifactValidationError, match="does not match its recomputed"):
        load_verified_canonical_build(a.build_path)


def test_tampered_canonical_content_id_fails(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    mutate_manifest(a, lambda payload: payload.__setitem__("canonical_content_id", sha("tampered")))
    with pytest.raises(CanonicalArtifactValidationError, match="canonical_content_id"):
        load_verified_canonical_build(a.build_path)


def test_tampered_canonical_build_id_fails(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    tampered = sha("tampered")
    mutate_manifest(a, lambda payload: payload.__setitem__("canonical_build_id", tampered))
    moved = a.build_path.parent / f"build_id={tampered}"
    a.build_path.rename(moved)
    with pytest.raises(CanonicalArtifactValidationError, match="canonical_build_id"):
        load_verified_canonical_build(moved)


def test_bool_top_level_count_fails(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    mutate_manifest(a, lambda payload: payload.__setitem__("canonical_row_count", True))
    with pytest.raises(CanonicalArtifactValidationError, match="non-negative integer"):
        load_verified_canonical_build(a.build_path)


def test_path_traversal_output_record_fails(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    mutate_manifest(
        a,
        lambda payload: payload["output_files"].append(
            {
                "relative_path": "../outside.parquet",
                "file_role": "bars",
                "row_count": 0,
                "byte_size": 0,
                "sha256": sha("x"),
                "content_role": "x",
            }
        ),
    )
    with pytest.raises(CanonicalArtifactValidationError, match="unsafe output file relative_path"):
        load_verified_canonical_build(a.build_path)


def test_symlinked_file_fails(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    bar_file = next(a.build_path.rglob("bars/**/part-00000.parquet"))
    outside = tmp_path / "outside.parquet"
    outside.write_bytes(b"x")
    try:
        os.remove(bar_file)
        os.symlink(outside, bar_file)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available in this environment")
    with pytest.raises(CanonicalArtifactValidationError, match="symlink"):
        load_verified_canonical_build(a.build_path)


def test_malformed_utf8_manifest_fails(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    (a.build_path / "manifest.json").write_bytes(b"\xff\xfe\x00")
    with pytest.raises(CanonicalArtifactValidationError, match="not valid UTF-8"):
        load_verified_canonical_build(a.build_path)


def test_invalid_json_manifest_fails(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    (a.build_path / "manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(CanonicalArtifactValidationError, match="not valid JSON"):
        load_verified_canonical_build(a.build_path)


def test_unknown_manifest_field_fails(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    mutate_manifest(a, lambda payload: payload.__setitem__("unexpected", 1))
    with pytest.raises(CanonicalArtifactValidationError, match="unknown top-level"):
        load_verified_canonical_build(a.build_path)


def test_unknown_output_record_field_fails(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    mutate_manifest(
        a,
        lambda payload: payload["output_files"][0].__setitem__("unexpected", 1),
    )
    with pytest.raises(CanonicalArtifactValidationError, match="unknown field"):
        load_verified_canonical_build(a.build_path)


def test_missing_manifest_fails(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    (a.build_path / "manifest.json").unlink()
    with pytest.raises(CanonicalArtifactValidationError, match="manifest.json"):
        load_verified_canonical_build(a.build_path)


def test_nonexistent_build_dir_fails(tmp_path):
    with pytest.raises(CanonicalArtifactValidationError, match="does not exist"):
        load_verified_canonical_build(tmp_path / "nope")


# ---------------------------------------------------------------------------
# F. Provenance outputs.
# ---------------------------------------------------------------------------


def test_selected_rows_produce_canonical_build_pins(tmp_path):
    _, a, b, c, _ = make_builds(tmp_path)
    result = assemble(
        [a, b, c],
        [
            request(
                label_start=datetime(2026, 7, 1, 13, 33, tzinfo=UTC),
                label_close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
            )
        ],
    )
    pins = {pin.canonical_build_id: pin for pin in result.canonical_build_pins}
    assert set(pins) == {build.canonical_build_id for build in (a, b, c)}
    pin_a = pins[a.canonical_build_id]
    assert pin_a.canonical_content_id == a.canonical_content_id
    assert pin_a.canonical_builder_version == a.canonical_builder_version
    assert pin_a.canonical_schema_version == a.canonical_schema_version
    assert pin_a.materializer_version == a.materializer_version
    assert pin_a.gap_policy_version == a.gap_policy_version
    assert pin_a.gap_content_id == a.gap_content_id
    assert pin_a.status == "COMPLETE"
    # Pin A records only the rows this assembly actually selected from build
    # A: the 13:30/13:31Z features plus the 13:33Z label row. The 13:32Z row
    # falls outside every window. Pin C records the two label rows; pin B
    # selected nothing.
    assert set(pin_a.canonical_row_version_ids) == {
        bar.canonical_row_version_id for bar in a.bars
        if bar.event_time != pd.Timestamp("2026-07-01T13:32:00Z")
    }
    assert set(pin_c := pins[c.canonical_build_id].canonical_row_version_ids) == {
        bar.canonical_row_version_id for bar in c.bars
    }
    assert pins[b.canonical_build_id].canonical_row_version_ids == ()
    assert pins[b.canonical_build_id].source_snapshots == ()
    # Source snapshot pins come from the selected rows' own provenance.
    assert {snap.ingestion_run_id for snap in pin_a.source_snapshots} == {"run-a"}
    assert {snap.ingestion_run_id for snap in pins[c.canonical_build_id].source_snapshots} == {"run-c"}


def test_selected_row_ids_covered_by_pins(tmp_path):
    _, a, b, c, _ = make_builds(tmp_path)
    result = assemble(
        [a, b, c],
        [
            request(
                label_start=datetime(2026, 7, 1, 13, 33, tzinfo=UTC),
                label_close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
            )
        ],
    )
    pinned = {
        version
        for pin in result.canonical_build_pins
        for version in pin.canonical_row_version_ids
    }
    for row in result.association_rows:
        assert row["canonical_row_version_id"] in pinned
    assert set(result.canonical_row_version_ids) == pinned


def test_unselected_source_snapshots_excluded_from_pins(tmp_path):
    _, a, b, *_ = make_builds(tmp_path)
    result = assemble([a, b], [request()])
    pin_b = next(
        pin for pin in result.canonical_build_pins
        if pin.canonical_build_id == b.canonical_build_id
    )
    assert pin_b.canonical_row_version_ids == ()
    assert pin_b.source_snapshots == ()


def test_snapshot_path_change_does_not_affect_identity(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    # Relocate snapshot_file consistently across the whole artifact; the
    # reader re-verifies the fully relocated artifact (an inconsistent
    # relocation would fail the per-key resolution binding).
    relocate_snapshot_files(a)
    moved = load_verified_canonical_build(a.build_path)
    first = assemble([a], [request()])
    second = assemble([moved], [request()])
    assert first == second


def test_gap_reference_matches_manifest(tmp_path):
    gap_build = make_gap_build(tmp_path)
    payload = json.loads(gap_build.manifest_payload)
    assert gap_build.gap_count == 1
    result = assemble([gap_build], [request()])
    ref = result.gap_references[0]
    assert ref.canonical_build_id == gap_build.canonical_build_id
    assert ref.gap_content_id == gap_build.gap_content_id == payload["gap_content_id"]
    assert ref.gap_range_count == 1 == payload["gap_range_count"]
    # With a window that closes exactly at the next boundary bar's market
    # availability, the overlapping gap is recorded as a known gap ID.
    sample = assemble(
        [gap_build],
        [request(feature_close=datetime(2026, 7, 1, 13, 33, tzinfo=UTC))],
    ).samples[0]
    assert sample.diagnostics.known_feature_gap_ids == tuple(
        gap.gap_id for gap in gap_build.gap_ranges
    )


def test_no_duplicate_gap_reference_per_build(tmp_path):
    _, a, b, *_ = make_builds(tmp_path)
    result = assemble([a, b, a], [request()])
    ref_ids = [ref.canonical_build_id for ref in result.gap_references]
    assert ref_ids == sorted(set(ref_ids))
    assert len(ref_ids) == 2


def test_pit_sample_version_id_helpers_deterministic(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    first = assemble([a], [request()])
    sample = first.samples[0]
    recomputed = pit_sample_version_id(
        sample_key=sample.sample_key,
        dataset_as_of=sample.dataset_as_of,
        feature_canonical_row_version_ids=sample.feature_canonical_row_version_ids,
        label_canonical_row_version_ids=sample.label_canonical_row_version_ids,
        considered_canonical_build_ids=sample.considered_canonical_build_ids,
    )
    assert recomputed == sample.sample_version_id
    # The feature/label order is identity-bearing (deterministic position
    # order), while reversing the input considered-build list does not change
    # the ID (build IDs are sorted before encoding).
    reordered_considered = pit_sample_version_id(
        sample_key=sample.sample_key,
        dataset_as_of=sample.dataset_as_of,
        feature_canonical_row_version_ids=sample.feature_canonical_row_version_ids,
        label_canonical_row_version_ids=sample.label_canonical_row_version_ids,
        considered_canonical_build_ids=list(reversed(sample.considered_canonical_build_ids)),
    )
    assert reordered_considered == recomputed
    reordered_feature = pit_sample_version_id(
        sample_key=sample.sample_key,
        dataset_as_of=sample.dataset_as_of,
        feature_canonical_row_version_ids=list(reversed(sample.feature_canonical_row_version_ids)),
        label_canonical_row_version_ids=sample.label_canonical_row_version_ids,
        considered_canonical_build_ids=sample.considered_canonical_build_ids,
    )
    assert reordered_feature != recomputed


def test_association_schema_contract(tmp_path):
    schema = pit_association_schema()
    assert [field.name for field in schema.fields] == [
        "sample_key", "sample_version_id", "role", "position",
        "canonical_build_id", "canonical_bar_key", "canonical_row_version_id",
        "code", "event_time", "market_available_at", "archive_available_at",
    ]
    roles = {
        row["role"]
        for row in assemble([make_builds(tmp_path)[1]], [request()]).association_rows
    }
    assert roles <= {PIT_ROLE_FEATURE, PIT_ROLE_LABEL}


def test_roles_and_positions_in_association_rows(tmp_path):
    _, a, b, c, _ = make_builds(tmp_path)
    rows = assemble(
        [a, b, c],
        [
            request(
                label_start=datetime(2026, 7, 1, 13, 34, tzinfo=UTC),
                label_close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
            )
        ],
    ).association_rows
    feature_rows = [row for row in rows if row["role"] == PIT_ROLE_FEATURE]
    label_rows = [row for row in rows if row["role"] == PIT_ROLE_LABEL]
    assert [row["position"] for row in feature_rows] == [0, 1]
    assert [row["position"] for row in label_rows] == [0, 1]
    assert all(row["code"] == "US.MU" for row in rows)
    assert all(row["canonical_build_id"] in (a.canonical_build_id, c.canonical_build_id) for row in rows)


# ---------------------------------------------------------------------------
# G. Reader semantic contract (request / bar / resolution / gap re-derivation).
# ---------------------------------------------------------------------------


def test_swapped_resolution_selected_fails(tmp_path):
    build = make_two_symbol_build(tmp_path)
    rows = [
        json.loads(line)
        for line in (build.build_path / "resolution.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    mu_bar = next(bar for bar in build.bars if bar.code == "US.MU")
    nvda_bar = next(bar for bar in build.bars if bar.code == "US.NVDA")
    mu_idx = next(i for i, row in enumerate(rows) if row["canonical_bar_key"] == mu_bar.canonical_bar_key)
    nvda_idx = next(i for i, row in enumerate(rows) if row["canonical_bar_key"] == nvda_bar.canonical_bar_key)
    rows[mu_idx]["selected"], rows[nvda_idx]["selected"] = (
        rows[nvda_idx]["selected"],
        rows[mu_idx]["selected"],
    )
    new_root = resync_resolution(build, rows)
    with pytest.raises(CanonicalArtifactValidationError, match="does not match its canonical bar"):
        load_verified_canonical_build(new_root)


def test_bar_code_not_in_manifest_symbols_fails(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    recompute_and_rewrite_bars(
        a,
        lambda frame: set_column(
            frame, "code", ["US.ZZZ" if i == 0 else value for i, value in enumerate(frame["code"])]
        ),
    )
    with pytest.raises(CanonicalArtifactValidationError, match="not in the normalized request symbols"):
        load_verified_canonical_build(a.build_path)


def test_bar_trade_date_not_in_manifest_dates_fails(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    recompute_and_rewrite_bars(
        a,
        lambda frame: set_column(
            frame, "requested_trade_date",
            [date(2026, 7, 2) if i == 0 else value for i, value in enumerate(frame["requested_trade_date"])],
        ),
    )
    with pytest.raises(CanonicalArtifactValidationError, match="not in the normalized request trade dates"):
        load_verified_canonical_build(a.build_path)


def test_bar_request_key_field_mismatch_fails(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    recompute_and_rewrite_bars(
        a,
        lambda frame: set_column(
            frame, "interval", ["5m" if i == 0 else value for i, value in enumerate(frame["interval"])]
        ),
    )
    with pytest.raises(CanonicalArtifactValidationError, match="does not match the normalized request interval"):
        load_verified_canonical_build(a.build_path)


def test_bar_builder_version_mismatch_fails(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    recompute_and_rewrite_bars(
        a,
        lambda frame: set_column(
            frame, "canonical_builder_version",
            ["market-bars-canonical-x-v1" if i == 0 else value for i, value in enumerate(frame["canonical_builder_version"])],
        ),
    )
    with pytest.raises(CanonicalArtifactValidationError, match="does not match the manifest canonical_builder_version"):
        load_verified_canonical_build(a.build_path)


def test_non_normalized_request_symbols_fail(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    mutate_manifest(
        a,
        lambda payload: payload["normalized_request"].__setitem__("symbols", ["US.MU", "US.MU"]),
    )
    with pytest.raises(CanonicalArtifactValidationError, match="deduplicated"):
        load_verified_canonical_build(a.build_path)
    _, b, *_ = make_builds(tmp_path)
    mutate_manifest(
        b,
        lambda payload: payload["normalized_request"].__setitem__("symbols", ["US.NVDA", "US.MU"]),
    )
    with pytest.raises(CanonicalArtifactValidationError, match="sorted ascending"):
        load_verified_canonical_build(b.build_path)


def test_non_normalized_request_trade_dates_fail(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    mutate_manifest(
        a,
        lambda payload: payload["normalized_request"].__setitem__(
            "trade_dates", ["2026-07-02", "2026-07-01"]
        ),
    )
    with pytest.raises(CanonicalArtifactValidationError, match="sorted ascending"):
        load_verified_canonical_build(a.build_path)


def test_gap_sidecar_tampered_with_synced_identity_fails(tmp_path):
    gap_build = make_gap_build(tmp_path)
    gap_file = next(gap_build.build_path.rglob("gaps/**/part-00000.parquet"))
    rows = pq.read_table(gap_file).to_pylist()
    rows[0]["missing_bar_count"] = 2
    new_root = resync_gap_sidecar(gap_build, rows)
    with pytest.raises(CanonicalArtifactValidationError, match="re-derived from the bars"):
        load_verified_canonical_build(new_root)


def test_gap_sidecar_removed_with_synced_identity_fails(tmp_path):
    gap_build = make_gap_build(tmp_path)
    new_root = resync_gap_sidecar(gap_build, [])
    with pytest.raises(CanonicalArtifactValidationError, match="re-derived from the bars"):
        load_verified_canonical_build(new_root)


# ---------------------------------------------------------------------------
# H. Known-gap dimensions and PIT clocks.
# ---------------------------------------------------------------------------


def test_known_gap_other_symbol_excluded(tmp_path):
    gap_build = make_multi_symbol_gap_build(tmp_path)
    sample = assemble(
        [gap_build],
        [request(feature_close=datetime(2026, 7, 1, 13, 33, tzinfo=UTC))],
    ).samples[0]
    mu_gap_id = next(gap.gap_id for gap in gap_build.gap_ranges if gap.code == "US.MU")
    nvda_gap_id = next(gap.gap_id for gap in gap_build.gap_ranges if gap.code == "US.NVDA")
    assert sample.diagnostics.known_feature_gap_ids == (mu_gap_id,)
    assert nvda_gap_id not in sample.diagnostics.known_feature_gap_ids


def test_known_gap_other_date_excluded(tmp_path):
    gap_build = make_jul2_gap_build(tmp_path)
    sample = assemble(
        [gap_build],
        [
            request(
                code="US.NVDA",
                feature_start=datetime(2026, 7, 2, 13, 30, tzinfo=UTC),
                feature_close=datetime(2026, 7, 2, 13, 33, tzinfo=UTC),
            )
        ],
    ).samples[0]
    # Rows on 2026-07-02 are visible as features, but the gap's
    # market-calendar date differs from the 2026-07-01 anchor, so it is not
    # a known gap of this sample.
    assert sample.diagnostics.feature_selected_count == 2
    assert sample.diagnostics.known_feature_gap_ids == ()


def test_known_gap_other_session_excluded(tmp_path):
    gap_build = make_gap_build(tmp_path)
    sample = assemble(
        [gap_build],
        [request(requested_session="MORNING",
                 feature_close=datetime(2026, 7, 1, 13, 33, tzinfo=UTC))],
    ).samples[0]
    assert sample.diagnostics.known_feature_gap_ids == ()


def test_known_gap_other_interval_excluded(tmp_path):
    gap_build = make_gap_build(tmp_path)
    sample = assemble(
        [gap_build],
        [request(interval="5m",
                 feature_close=datetime(2026, 7, 1, 13, 33, tzinfo=UTC))],
    ).samples[0]
    assert sample.diagnostics.known_feature_gap_ids == ()


def test_known_gap_requires_next_boundary_market_available(tmp_path):
    gap_build = make_gap_build(tmp_path)
    # The next boundary bar (09:32) is market-available at 13:33Z; a window
    # closing before that never sees the gap as known.
    early = assemble([gap_build], [request()]).samples[0]
    assert early.diagnostics.known_feature_gap_ids == ()
    # A window closing exactly at the next boundary's market availability
    # records the gap.
    boundary = assemble(
        [gap_build],
        [request(feature_close=datetime(2026, 7, 1, 13, 33, tzinfo=UTC))],
    ).samples[0]
    assert boundary.diagnostics.known_feature_gap_ids == tuple(
        gap.gap_id for gap in gap_build.gap_ranges
    )


def test_known_gap_archive_cutoff(tmp_path):
    gap_build = make_gap_build(tmp_path)
    close = datetime(2026, 7, 1, 13, 33, tzinfo=UTC)
    before = assemble(
        [gap_build], [request(feature_close=close)],
        dataset_as_of=datetime(2026, 7, 1, 13, 0, tzinfo=UTC),
    ).samples[0]
    assert before.diagnostics.known_feature_gap_ids == ()
    # Boundary bars archived exactly at the cutoff allow the gap.
    at_cutoff = assemble(
        [gap_build], [request(feature_close=close)],
        dataset_as_of=datetime(2026, 7, 1, 14, 0, tzinfo=UTC),
    ).samples[0]
    assert at_cutoff.diagnostics.known_feature_gap_ids == tuple(
        gap.gap_id for gap in gap_build.gap_ranges
    )


def test_known_gap_identical_across_builds_deduped(tmp_path):
    first, second = make_duplicate_gap_artifacts(tmp_path)
    sample = assemble(
        [first, second],
        [request(feature_close=datetime(2026, 7, 1, 13, 33, tzinfo=UTC))],
    ).samples[0]
    assert sample.diagnostics.known_feature_gap_ids == tuple(
        gap.gap_id for gap in first.gap_ranges
    )
    assert len(sample.diagnostics.known_feature_gap_ids) == 1


def test_known_gap_conflicting_facts_fail(tmp_path):
    gap_build = make_gap_build(tmp_path)
    tampered = replace(
        gap_build,
        gap_boundaries=(
            replace(
                gap_build.gap_boundaries[0],
                next_archive_available_at=pd.Timestamp("2026-07-01T16:00:00Z"),
            ),
        ),
    )
    with pytest.raises(PITAssemblyError, match="conflicting facts for known gap id"):
        assemble(
            [gap_build, tampered],
            [request(feature_close=datetime(2026, 7, 1, 13, 33, tzinfo=UTC))],
        )


# ---------------------------------------------------------------------------
# I. Public sample-version-id input validation.
# ---------------------------------------------------------------------------


def test_sample_version_id_rejects_non_hash_values():
    with pytest.raises(PITAssemblyError, match="SHA-256"):
        version_id(feature=("a", "b"))


def test_sample_version_id_rejects_separator_values():
    with pytest.raises(PITAssemblyError, match="SHA-256"):
        version_id(feature=("\x1e" * 64,))


def test_sample_version_id_rejects_non_hex():
    with pytest.raises(PITAssemblyError, match="SHA-256"):
        version_id(considered=("z" * 64,))


def test_sample_version_id_rejects_uppercase_hash():
    with pytest.raises(PITAssemblyError, match="SHA-256"):
        version_id(label=(sha("x").upper(),))


def test_sample_version_id_rejects_duplicate_feature_ids():
    with pytest.raises(PITAssemblyError, match="duplicate"):
        version_id(feature=(sha("a"), sha("a")))


def test_sample_version_id_rejects_duplicate_label_ids():
    with pytest.raises(PITAssemblyError, match="duplicate"):
        version_id(label=(sha("a"), sha("a")))


def test_sample_version_id_rejects_duplicate_considered_ids():
    with pytest.raises(PITAssemblyError, match="duplicate"):
        version_id(considered=(sha("a"), sha("a")))


def test_sample_version_id_rejects_feature_label_overlap():
    with pytest.raises(PITAssemblyError, match="both the feature and label"):
        version_id(feature=(sha("a"),), label=(sha("a"),))


def test_sample_version_id_rejects_bad_assembler_version():
    with pytest.raises(PITAssemblyError, match="assembler_version"):
        version_id(assembler_version="market-vault-pit-assembler-v1\x1f")


# ---------------------------------------------------------------------------
# J. Association schema contract version.
# ---------------------------------------------------------------------------


def test_association_schema_version_changes_sample_version_id():
    base = version_id(feature=(sha("a"),))
    changed = version_id(
        feature=(sha("a"),), association_schema_version="pit-association-schema-v2"
    )
    assert base != changed


def test_association_schema_version_pinned():
    assert PIT_ASSOCIATION_SCHEMA_VERSION == "pit-association-schema-v1"
    assert version_id(feature=(sha("a"),)) == pit_sample_version_id(
        sample_key=sha("sample"),
        dataset_as_of=None,
        feature_canonical_row_version_ids=(sha("a"),),
        label_canonical_row_version_ids=(),
        considered_canonical_build_ids=(),
    )


# ---------------------------------------------------------------------------
# K. Empty observation semantics.
# ---------------------------------------------------------------------------


def test_empty_observation_when_no_candidates(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    sample = assemble([a], [request(code="US.QQQ")]).samples[0]
    assert sample.diagnostics.feature_candidate_count == 0
    assert sample.diagnostics.empty_observation_window is True


def test_empty_observation_when_all_market_excluded(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    sample = assemble(
        [a],
        [
            request(
                feature_start=datetime(2026, 7, 1, 13, 31, tzinfo=UTC),
                feature_close=datetime(2026, 7, 1, 13, 31, 30, tzinfo=UTC),
            )
        ],
    ).samples[0]
    assert sample.diagnostics.feature_candidate_count == 1
    assert sample.diagnostics.feature_selected_count == 0
    assert sample.diagnostics.feature_market_future_excluded_count == 1
    assert sample.diagnostics.empty_observation_window is True


def test_empty_observation_when_all_archive_excluded(tmp_path):
    _, a, b, *_ = make_builds(tmp_path)
    sample = assemble(
        [a, b], [request(code="US.NVDA")],
        dataset_as_of=datetime(2026, 7, 1, 14, 0, tzinfo=UTC),
    ).samples[0]
    assert sample.diagnostics.feature_candidate_count == 2
    assert sample.diagnostics.feature_selected_count == 0
    assert sample.diagnostics.feature_archive_future_excluded_count == 2
    assert sample.diagnostics.empty_observation_window is True


def test_empty_observation_false_when_selected(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    sample = assemble([a], [request()]).samples[0]
    assert sample.diagnostics.feature_selected_count == 2
    assert sample.diagnostics.empty_observation_window is False


# ---------------------------------------------------------------------------
# L. Deep immutability of the verified build.
# ---------------------------------------------------------------------------


def test_normalized_request_deeply_immutable(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    assert isinstance(a.normalized_request, VerifiedCanonicalRequest)
    assert isinstance(a.normalized_request.symbols, tuple)
    assert isinstance(a.normalized_request.trade_dates, tuple)
    with pytest.raises(FrozenInstanceError):
        a.normalized_request.symbols = ("US.NVDA",)


def test_manifest_payload_immutable_bytes(tmp_path):
    _, a, *_ = make_builds(tmp_path)
    assert isinstance(a.manifest_payload, bytes)
    with pytest.raises(TypeError):
        a.manifest_payload[0] = ord("x")
    payload = json.loads(a.manifest_payload)
    assert payload["canonical_build_id"] == a.canonical_build_id
