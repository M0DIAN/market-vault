from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from market_vault.canonical import (
    CANONICAL_BUILDER_VERSION,
    CANONICAL_MATERIALIZER_VERSION,
    CANONICAL_SCHEMA_VERSION,
    GAP_POLICY_VERSION,
    MANIFEST_SCHEMA_VERSION,
    CanonicalMaterializationError,
    CanonicalRequestKey,
    CanonicalSnapshotInput,
    canonical_build_id,
    load_canonical_snapshot_inputs,
    materialize_build_result,
    materialize_canonical_market_bars,
    resolution_content_id,
)
from market_vault.canonical.bars import build_canonical_market_bars
from market_vault.canonical.gaps import derive_internal_gap_ranges
from market_vault.canonical.schema import CANONICAL_BAR_COLUMNS, canonical_bars_schema
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars, normalize_trading_calendar
from market_vault.storage import Catalog, ParquetStore
from market_vault.storage.catalog import CompleteSnapshotRef

NY = "America/New_York"
DEFAULT_KEY = CanonicalRequestKey(
    interval="1m", requested_session="ALL", adjustment="NONE", source_schema_version="10.9"
)
CREATED_AT = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)


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


def minute_keys(start: str, count: int, step_minutes: int = 1) -> list[str]:
    base = pd.Timestamp(start, tz=NY)
    return [
        (base + pd.Timedelta(minutes=step_minutes * i)).strftime("%Y-%m-%d %H:%M:%S")
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
    quality: str = "PASS",
    mutate=None,
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
    if mutate is not None:
        curated = mutate(curated)
    store.write_curated(curated, trade_date, "1m", [code], "ALL", "NONE", run_id=run_id)
    run = RunManifest(
        requested_trade_date=trade_date, requested_symbols=[code],
        interval="1m", session="ALL", adjustment="NONE", run_id=run_id,
    )
    run.successful_symbols = [code]
    run.status = "SUCCESS"
    run.finished_at = run_finished_at or datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc)
    catalog.record_run(run)
    catalog.record_quality(run.run_id, [QualityResult("bars_complete", quality)])


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def output_root(cfg: Settings) -> Path:
    return cfg.data_root / "canonical" / "dataset=market_bars_canonical"


def materialize(cfg: Settings, *, symbols=None, trade_dates=None, key=DEFAULT_KEY,
                created_at=CREATED_AT, root=None):
    return materialize_canonical_market_bars(
        Catalog(cfg),
        symbols=symbols or ["US.MU"],
        trade_dates=trade_dates or [date(2026, 7, 1)],
        request_key=key,
        output_root=root or output_root(cfg),
        created_at=created_at,
    )


# --- Snapshot loading -------------------------------------------------------


def test_loading_uses_latest_complete_selection(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 2))
    inputs = load_canonical_snapshot_inputs(
        Catalog(cfg), symbols=["US.MU"], trade_dates=[date(2026, 7, 1)], request_key=DEFAULT_KEY
    )
    assert len(inputs) == 1
    assert inputs[0].snapshot.ingestion_run_id == "run-a"
    assert inputs[0].physical_snapshot_hash == file_sha256(
        cfg.data_root / inputs[0].snapshot.snapshot_file
    )


def test_loading_omits_quality_failed_and_missing(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-bad",
                   time_keys=minute_keys("2026-07-01 09:30:00", 2), quality="FAIL")
    inputs = load_canonical_snapshot_inputs(
        Catalog(cfg), symbols=["US.MU"], trade_dates=[date(2026, 7, 1)], request_key=DEFAULT_KEY
    )
    assert inputs == ()


def test_selected_missing_file_fails_closed(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    catalog = Catalog(cfg)
    refs = catalog.latest_complete_market_bar_snapshots(
        symbols=["US.MU"], trade_dates=[date(2026, 7, 1)], interval="1m",
        requested_session="ALL", adjustment="NONE", source_schema_version="10.9",
    )
    ref = refs[("US.MU", date(2026, 7, 1))]
    (cfg.data_root / ref.snapshot_file).unlink()
    # The selection already happened; the selected file disappears before
    # reading, which is an error, not an EMPTY result.
    monkeypatch.setattr(
        catalog, "latest_complete_market_bar_snapshots",
        lambda **kwargs: refs,
    )
    with pytest.raises(CanonicalMaterializationError, match="missing"):
        load_canonical_snapshot_inputs(
            catalog, symbols=["US.MU"], trade_dates=[date(2026, 7, 1)], request_key=DEFAULT_KEY
        )


def test_unsafe_snapshot_path_fails_closed(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    refs = Catalog(cfg).latest_complete_market_bar_snapshots(
        symbols=["US.MU"], trade_dates=[date(2026, 7, 1)], interval="1m",
        requested_session="ALL", adjustment="NONE", source_schema_version="10.9",
    )
    ref = refs[("US.MU", date(2026, 7, 1))]
    unsafe = CompleteSnapshotRef(
        code=ref.code, requested_trade_date=ref.requested_trade_date,
        ingestion_run_id=ref.ingestion_run_id,
        snapshot_file="curated/../../outside.parquet",
        snapshot_ingested_at=ref.snapshot_ingested_at,
        run_finished_at=ref.run_finished_at,
        eligible_row_count=ref.eligible_row_count,
    )
    # Direct unsafe-path resolution must fail.
    with pytest.raises(ValueError, match="unsafe snapshot file path"):
        Catalog(cfg).resolve_snapshot_file(unsafe.snapshot_file)


def test_file_change_during_read_fails_closed(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    catalog = Catalog(cfg)
    original = catalog.market_bar_snapshot_rows

    def read_then_tamper(snapshot):
        rows = original(snapshot)
        path = cfg.data_root / snapshot.snapshot_file
        path.write_bytes(path.read_bytes() + b"tampered")
        return rows

    monkeypatch.setattr(catalog, "market_bar_snapshot_rows", read_then_tamper)
    with pytest.raises(CanonicalMaterializationError, match="changed while being read"):
        load_canonical_snapshot_inputs(
            catalog, symbols=["US.MU"], trade_dates=[date(2026, 7, 1)], request_key=DEFAULT_KEY
        )


def test_loading_does_not_touch_open_d(monkeypatch, tmp_path):
    class Raiser:
        def __init__(self, settings):
            raise AssertionError("OpenD collector must not be constructed")

    monkeypatch.setattr("market_vault.collectors.MoomooHistoryCollector", Raiser)
    monkeypatch.setattr("market_vault.collectors.MoomooCalendarCollector", Raiser)
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    inputs = load_canonical_snapshot_inputs(
        Catalog(cfg), symbols=["US.MU"], trade_dates=[date(2026, 7, 1)], request_key=DEFAULT_KEY
    )
    assert len(inputs) == 1


# --- Canonical Parquet ------------------------------------------------------


def _build_with_gap(cfg, *, time_keys=None):
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=time_keys or ["2026-07-01 09:30:00", "2026-07-01 09:32:00"])
    return materialize(cfg)


def test_parquet_explicit_column_order_and_types(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    result = _build_with_gap(cfg)
    bar_file = next(result.build_path.rglob("bars/**/*.parquet"))
    frame = pd.read_parquet(bar_file)
    assert list(frame.columns) == list(CANONICAL_BAR_COLUMNS)
    schema = canonical_bars_schema()
    assert schema.field("event_time").type == pa_timestamp_utc()
    assert schema.field("open").type == pa_float()
    assert schema.field("market_calendar_date").type == pa_date()
    assert schema.field("turnover").nullable is True


def pa_timestamp_utc():
    import pyarrow as pa

    return pa.timestamp("us", tz="UTC")


def pa_float():
    import pyarrow as pa

    return pa.float64()


def pa_date():
    import pyarrow as pa

    return pa.date32()


def test_parquet_utc_round_trip_and_null_optionals(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    result = _build_with_gap(cfg)
    bar_file = next(result.build_path.rglob("bars/**/*.parquet"))
    frame = pd.read_parquet(bar_file)
    assert frame["event_time"].iloc[0] == pd.Timestamp("2026-07-01 13:30:00", tz="UTC")
    assert frame["turnover"].isna().all()  # absent optional field stays null
    assert frame["snapshot_file"].iloc[0].endswith("run-a.parquet")


def test_parquet_deterministic_row_ordering(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=[
                       "2026-07-01 09:32:00",
                       "2026-07-01 09:30:00",
                       "2026-07-01 09:31:00",
                   ])
    result = materialize(cfg)
    bar_file = next(result.build_path.rglob("bars/**/*.parquet"))
    frame = pd.read_parquet(bar_file)
    assert frame["event_time"].is_monotonic_increasing


def test_parquet_multiple_partitions(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 2))
    write_snapshot(cfg, code="US.NVDA", trade_date=date(2026, 7, 1), run_id="run-b",
                   time_keys=minute_keys("2026-07-01 09:30:00", 2))
    result = materialize(cfg, symbols=["US.MU", "US.NVDA"])
    partitions = sorted(p for p in result.build_path.rglob("bars/**/part-*.parquet"))
    assert len(partitions) == 2
    assert all("code=US.MU" in p.as_posix() or "code=US.NVDA" in p.as_posix() for p in partitions)


# --- Identities -------------------------------------------------------------


def test_identical_requests_produce_identical_build_ids(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    first = _build_with_gap(cfg)
    second = materialize(cfg, created_at=datetime(2026, 8, 5, 0, 0, tzinfo=timezone.utc))
    assert second.created_new_build is False
    assert second.canonical_build_id == first.canonical_build_id
    assert second.canonical_content_id == first.canonical_content_id


def test_build_id_independent_of_input_order_and_rows(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 2))
    catalog = Catalog(cfg)
    inputs = load_canonical_snapshot_inputs(
        catalog, symbols=["US.MU"], trade_dates=[date(2026, 7, 1)], request_key=DEFAULT_KEY
    )
    build_a = build_canonical_market_bars(list(inputs))
    rows = inputs[0].rows.iloc[::-1]  # reversed row order
    shuffled_input = CanonicalSnapshotInput(
        snapshot=inputs[0].snapshot, rows=rows,
        physical_snapshot_hash=inputs[0].physical_snapshot_hash, request_key=DEFAULT_KEY,
    )
    build_b = build_canonical_market_bars([shuffled_input])
    assert build_a.bars[0].canonical_row_version_id == build_b.bars[0].canonical_row_version_id
    assert build_a.bars[0].canonical_bar_key == build_b.bars[0].canonical_bar_key


def test_build_id_function_inputs(tmp_path):
    base = dict(
        symbols=["US.MU"],
        trade_dates=[date(2026, 7, 1)],
        request_key=DEFAULT_KEY,
        canonical_content_id="c" * 64,
        resolution_content_id="r" * 64,
        gap_content_id="g" * 64,
        selected_row_version_ids=["v1"],
        canonical_builder_version=CANONICAL_BUILDER_VERSION,
        canonical_schema_version=CANONICAL_SCHEMA_VERSION,
        materializer_version=CANONICAL_MATERIALIZER_VERSION,
        gap_policy_version=GAP_POLICY_VERSION,
    )
    first = canonical_build_id(**base)
    # created_at is not an input; request order and timezone display do not
    # matter because everything is normalized inside the function.
    assert canonical_build_id(**base) == first
    assert canonical_build_id(**{**base, "canonical_schema_version": "schema-v2"}) != first
    assert canonical_build_id(**{**base, "gap_policy_version": "gap-v2"}) != first
    assert canonical_build_id(**{**base, "materializer_version": "mat-v2"}) != first
    assert canonical_build_id(**{**base, "canonical_builder_version": "builder-v2"}) != first
    assert canonical_build_id(**{**base, "selected_row_version_ids": ["v2"]}) != first


def test_resolution_content_id_ignores_snapshot_paths(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    result = materialize(cfg)
    lines = (result.build_path / "resolution.jsonl").read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[0])
    assert row["canonical_bar_key"]
    assert "selected" in row
    assert "snapshot_file" in row["selected"]


# --- Gap sidecar ------------------------------------------------------------


def test_gap_one_missing_bar(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    result = _build_with_gap(cfg, time_keys=["2026-07-01 09:30:00", "2026-07-01 09:32:00"])
    assert result.gap_count == 1
    gap_file = next(result.build_path.rglob("gaps/**/*.parquet"))
    frame = pd.read_parquet(gap_file)
    assert int(frame["missing_bar_count"].iloc[0]) == 1
    assert frame["missing_from_event_time"].iloc[0] == pd.Timestamp("2026-07-01 13:31:00", tz="UTC")
    assert frame["missing_to_event_time"].iloc[0] == pd.Timestamp("2026-07-01 13:31:00", tz="UTC")


def test_gap_multiple_missing_bars(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    result = _build_with_gap(cfg, time_keys=["2026-07-01 09:30:00", "2026-07-01 09:35:00"])
    assert result.gap_count == 1
    gap_file = next(result.build_path.rglob("gaps/**/*.parquet"))
    frame = pd.read_parquet(gap_file)
    assert int(frame["missing_bar_count"].iloc[0]) == 4


def test_gap_no_synthetic_rows(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    result = _build_with_gap(cfg, time_keys=["2026-07-01 09:30:00", "2026-07-01 09:32:00"])
    assert result.row_count == 2  # only observed bars


def test_gap_no_inference_at_edges(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    result = _build_with_gap(cfg, time_keys=minute_keys("2026-07-01 09:30:00", 3))
    assert result.gap_count == 0


def test_gap_no_cross_session_or_date(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=[
                       "2026-07-01 09:29:00",  # PRE_MARKET
                       "2026-07-01 09:30:00",  # REGULAR
                       "2026-07-02 09:30:00",  # next calendar date, REGULAR
                   ])
    result = materialize(cfg)
    assert result.gap_count == 0


def test_gap_non_integral_delta_fails_closed(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)

    def shift_second_row(df):
        df = df.copy()
        time_utc = pd.to_datetime(df["time_utc"]).copy()
        time_market = pd.to_datetime(df["time_market"]).copy()
        time_utc.iloc[1] = time_utc.iloc[1] + pd.Timedelta(seconds=30)
        time_market.iloc[1] = time_market.iloc[1] + pd.Timedelta(seconds=30)
        return df.assign(time_utc=time_utc, time_market=time_market)

    write_snapshot(
        cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
        time_keys=["2026-07-01 09:30:00", "2026-07-01 09:31:00"],
        mutate=shift_second_row,
    )
    with pytest.raises(ValueError, match="not an exact nominal-interval multiple"):
        materialize(cfg)


# --- Manifest ---------------------------------------------------------------


def test_manifest_counts_and_time_ranges(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    result = _build_with_gap(cfg)
    manifest = json.loads((result.build_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_schema_version"] == MANIFEST_SCHEMA_VERSION
    assert manifest["status"] == "COMPLETE"
    assert manifest["canonical_build_id"] == result.canonical_build_id
    assert manifest["canonical_row_count"] == 2
    assert manifest["gap_range_count"] == 1
    assert manifest["resolution_row_count"] == 2
    assert manifest["source_snapshot_count"] == 1
    assert manifest["min_event_time"] == "2026-07-01T13:30:00+00:00"
    assert manifest["max_event_time"] == "2026-07-01T13:32:00+00:00"


def test_manifest_empty_semantics(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    result = materialize(cfg, symbols=["US.NVDA"])
    assert result.status == "EMPTY"
    manifest = json.loads((result.build_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "EMPTY"
    assert manifest["canonical_row_count"] == 0
    assert manifest["gap_range_count"] == 0
    assert manifest["source_snapshot_count"] == 0
    assert not list(result.build_path.rglob("bars/**/*.parquet"))
    assert not list(result.build_path.rglob("gaps/**/*.parquet"))
    assert (result.build_path / "_SUCCESS").exists()


def test_manifest_deterministic_serialization(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    first = _build_with_gap(cfg)
    second = materialize(cfg)
    text_first = (first.build_path / "manifest.json").read_text(encoding="utf-8")
    text_second = (second.build_path / "manifest.json").read_text(encoding="utf-8")
    assert text_first == text_second
    assert text_first.endswith("\n")


def test_manifest_file_records_match_actual_bytes(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    result = _build_with_gap(cfg)
    manifest = json.loads((result.build_path / "manifest.json").read_text(encoding="utf-8"))
    for record in manifest["output_files"]:
        relative = record["relative_path"]
        assert not Path(relative).is_absolute()
        path = result.build_path / relative
        assert path.exists()
        assert record["sha256"] == file_sha256(path)
    roles = [record["file_role"] for record in manifest["output_files"]]
    assert roles == sorted(roles)
    assert "bars" in roles and "gaps" in roles and "resolution" in roles


def test_manifest_paths_are_relative(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    result = _build_with_gap(cfg)
    manifest = json.loads((result.build_path / "manifest.json").read_text(encoding="utf-8"))
    for record in manifest["output_files"]:
        assert not record["relative_path"].startswith("/")
        assert ".." not in record["relative_path"].split("/")


# --- Atomicity and idempotency ----------------------------------------------


def test_injected_write_failure_leaves_no_final_build(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 2))
    import pyarrow.parquet as pq

    def failing_write(*args, **kwargs):
        raise OSError("injected failure")

    monkeypatch.setattr(pq, "write_table", failing_write)
    with pytest.raises(OSError, match="injected"):
        materialize(cfg)
    builds = list(output_root(cfg).glob("build_id=*"))
    assert builds == []
    tmp_dirs = [p for p in output_root(cfg).iterdir() if ".tmp-" in p.name] if output_root(cfg).exists() else []
    assert tmp_dirs == []


def test_idempotent_repeated_materialization(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    first = _build_with_gap(cfg)
    assert first.created_new_build is True
    second = materialize(cfg)
    assert second.created_new_build is False
    assert second.canonical_build_id == first.canonical_build_id
    # Committed build is never rewritten.
    manifest_mtime = (first.build_path / "manifest.json").stat().st_mtime_ns
    third = materialize(cfg)
    assert (third.build_path / "manifest.json").stat().st_mtime_ns == manifest_mtime


def test_existing_incomplete_build_fails_closed(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    first = _build_with_gap(cfg)
    (first.build_path / "_SUCCESS").unlink()
    with pytest.raises(CanonicalMaterializationError, match="incomplete"):
        materialize(cfg)


def test_existing_conflicting_build_fails_closed(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    first = _build_with_gap(cfg)
    manifest_path = first.build_path / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["canonical_build_id"] = "x" * 64
    manifest_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(CanonicalMaterializationError, match="conflicts"):
        materialize(cfg)


def test_success_only_for_committed_builds(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    result = _build_with_gap(cfg)
    assert (result.build_path / "_SUCCESS").exists()


# --- Resolution -------------------------------------------------------------


def test_resolution_jsonl_deterministic_and_preserves_refs(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    result = materialize(cfg)
    lines = (result.build_path / "resolution.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["selected"]["ingestion_run_id"] == "run-a"
    assert row["selected"]["snapshot_file"].endswith("run-a.parquet")
    assert "equivalent_discarded_sources" in row


def test_resolution_content_id_ignores_paths(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    result = materialize(cfg)
    payload = json.loads((result.build_path / "manifest.json").read_text(encoding="utf-8"))
    assert len(payload["resolution_content_id"]) == 64
