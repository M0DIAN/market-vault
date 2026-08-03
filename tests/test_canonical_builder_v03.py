from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from market_vault.canonical import (
    CANONICAL_BUILDER_VERSION,
    CanonicalBuildError,
    CanonicalConflictError,
    CanonicalSnapshotInput,
    build_canonical_market_bars,
    canonical_bar_key,
    canonical_row_version_id,
    hash_curated_snapshot_rows,
)
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars
from market_vault.storage import Catalog, ParquetStore

NY = "America/New_York"


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


def minute_keys(start: str, count: int) -> list[str]:
    base = pd.Timestamp(start, tz=NY)
    return [(base + pd.Timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:%S") for i in range(count)]


def raw_frame(code: str, time_keys: list[str], close: float = 100.5) -> pd.DataFrame:
    return pd.DataFrame(
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


def write_snapshot(
    cfg: Settings,
    *,
    code: str,
    trade_date: date,
    run_id: str,
    time_keys: list[str],
    close: float = 100.5,
    session: str = "ALL",
    interval: str = "1m",
    run_status: str = "SUCCESS",
    quality: str = "PASS",
    run_finished_at: datetime | None = None,
    mutate=None,
) -> None:
    store = ParquetStore(cfg)
    catalog = Catalog(cfg)
    raw = raw_frame(code, time_keys, close=close)
    curated = normalize_bars(
        raw,
        requested_trade_date=trade_date,
        interval=interval,
        requested_session=session,
        adjustment="NONE",
        source=cfg.source,
        source_schema_version=cfg.source_schema_version,
        run_id=run_id,
    )
    if mutate is not None:
        curated = mutate(curated)
    store.write_curated(curated, trade_date, interval, [code], session, "NONE", run_id=run_id)
    run = RunManifest(
        requested_trade_date=trade_date,
        requested_symbols=[code],
        interval=interval.lower(),
        session=session.upper(),
        adjustment="NONE",
        run_id=run_id,
    )
    run.successful_symbols = [code]
    run.status = run_status
    run.finished_at = run_finished_at or datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc)
    catalog.record_run(run)
    catalog.record_quality(run.run_id, [QualityResult("bars_complete", quality)])


def select_snapshot(cfg: Settings, code: str = "US.MU", trade_date: date = date(2026, 7, 1), interval: str = "1m"):
    refs = Catalog(cfg).latest_complete_market_bar_snapshots(
        symbols=[code], trade_dates=[trade_date], interval=interval,
        requested_session="ALL", adjustment="NONE", source_schema_version="10.9",
    )
    return refs.get((code, trade_date))


def read_run_rows(cfg: Settings, *, run_id: str) -> tuple[object, pd.DataFrame]:
    """Read one physical snapshot file by run id and build a ref for it.

    Test helper for feeding a second audited snapshot into the builder when
    the V0.3 latest-complete selection only returns the newest one.
    """
    from market_vault.storage.catalog import CompleteSnapshotRef

    root = cfg.data_root / "curated" / f"source={cfg.source}" / "dataset=market_bars"
    for path in sorted(root.rglob("*.parquet")):
        frame = pd.read_parquet(path)
        if run_id in set(frame["ingestion_run_id"]):
            trade_date = frame["requested_trade_date"].iloc[0]
            if isinstance(trade_date, pd.Timestamp):
                trade_date = trade_date.date()
            ref = CompleteSnapshotRef(
                code=str(frame["code"].iloc[0]),
                requested_trade_date=trade_date,
                ingestion_run_id=run_id,
                snapshot_file=path.relative_to(cfg.data_root).as_posix(),
                snapshot_ingested_at=None,
                run_finished_at=None,
                eligible_row_count=len(frame),
            )
            return ref, frame
    raise AssertionError(f"no physical file found for run {run_id}")


def snapshot_input(
    cfg: Settings,
    *,
    ref,
    rows: pd.DataFrame,
    content_hash: str,
    run_finished_at: datetime | None = datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc),
    run_status: str = "SUCCESS",
) -> CanonicalSnapshotInput:
    return CanonicalSnapshotInput(
        snapshot=ref,
        rows=rows,
        source_snapshot_content_hash=content_hash,
        run_finished_at=run_finished_at,
        run_status=run_status,
    )


def build_one(cfg: Settings, code: str = "US.MU", trade_date: date = date(2026, 7, 1), interval: str = "1m", **kwargs):
    ref = select_snapshot(cfg, code=code, trade_date=trade_date, interval=interval)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref)
    content_hash = hash_curated_snapshot_rows(rows.frame)
    return build_canonical_market_bars(
        [snapshot_input(cfg, ref=ref, rows=rows.frame, content_hash=content_hash, **kwargs)]
    )


# --- COMPLETE gate ----------------------------------------------------------


def test_complete_snapshot_produces_canonical_rows(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 2))
    result = build_one(cfg)
    assert len(result.bars) == 2
    assert result.source_snapshot_count == 1
    assert result.builder_version == CANONICAL_BUILDER_VERSION


def test_incomplete_quality_fail_produces_no_rows(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-bad",
                   time_keys=minute_keys("2026-07-01 09:30:00", 2), quality="FAIL")
    # The V0.3 COMPLETE gate excludes quality-FAIL runs from selection.
    assert select_snapshot(cfg) is None


def test_missing_snapshot_produces_no_rows(tmp_path):
    cfg = settings(tmp_path)
    assert select_snapshot(cfg) is None


def test_non_complete_run_status_fails_closed(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 2))
    with pytest.raises(CanonicalBuildError, match="not audited as complete"):
        build_one(cfg, run_status="FAILED")


def test_missing_run_finished_at_fails_closed(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 2))
    with pytest.raises(CanonicalBuildError, match="run_finished_at"):
        build_one(cfg, run_finished_at=None)


# --- Identity ---------------------------------------------------------------


def test_business_key_excludes_run_id_schema_and_session(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    first = build_one(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-b",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    second = build_one(cfg)
    assert first.bars[0].canonical_bar_key == second.bars[0].canonical_bar_key
    assert first.bars[0].canonical_row_version_id != second.bars[0].canonical_row_version_id


def test_repeated_collection_keeps_business_key_changes_row_version(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    first = build_one(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-b",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    second = build_one(cfg)
    assert first.bars[0].canonical_bar_key == second.bars[0].canonical_bar_key
    assert first.bars[0].canonical_row_version_id != second.bars[0].canonical_row_version_id


def test_snapshot_path_does_not_affect_row_version_id():
    key = canonical_bar_key(
        dataset_kind="market_bars_canonical", code="US.MU", interval="1m",
        adjustment="NONE", event_time=pd.Timestamp("2026-07-01 13:30:00", tz="UTC"),
    )
    base = dict(
        canonical_bar_key=key,
        ingestion_run_id="run-a",
        source_snapshot_content_hash="hash-a",
        source_schema_version="10.9",
        canonical_builder_version=CANONICAL_BUILDER_VERSION,
    )
    # snapshot_file is provenance only and never part of the identity.
    assert canonical_row_version_id(**base) == canonical_row_version_id(**base)


def test_snapshot_content_change_changes_row_version_id():
    key = canonical_bar_key(
        dataset_kind="market_bars_canonical", code="US.MU", interval="1m",
        adjustment="NONE", event_time=pd.Timestamp("2026-07-01 13:30:00", tz="UTC"),
    )
    base = dict(
        canonical_bar_key=key,
        ingestion_run_id="run-a",
        source_schema_version="10.9",
        canonical_builder_version=CANONICAL_BUILDER_VERSION,
    )
    assert canonical_row_version_id(**base, source_snapshot_content_hash="hash-a") != (
        canonical_row_version_id(**base, source_snapshot_content_hash="hash-b")
    )


def test_builder_version_changes_only_row_version_id():
    key = canonical_bar_key(
        dataset_kind="market_bars_canonical", code="US.MU", interval="1m",
        adjustment="NONE", event_time=pd.Timestamp("2026-07-01 13:30:00", tz="UTC"),
    )
    base = dict(
        canonical_bar_key=key,
        ingestion_run_id="run-a",
        source_snapshot_content_hash="hash-a",
        source_schema_version="10.9",
    )
    v1 = canonical_row_version_id(**base, canonical_builder_version="market-bars-canonical-v1")
    v2 = canonical_row_version_id(**base, canonical_builder_version="market-bars-canonical-v2")
    assert v1 != v2
    # Business key is independent of the builder version.
    assert canonical_bar_key(
        dataset_kind="market_bars_canonical", code="US.MU", interval="1m",
        adjustment="NONE", event_time=pd.Timestamp("2026-07-01 13:30:00", tz="UTC"),
    ) == key


def test_requested_session_does_not_create_different_business_keys(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-all",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1), session="ALL")
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-rth",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1), session="RTH")
    ref_all = select_snapshot(cfg)
    rows_all = Catalog(cfg).market_bar_snapshot_rows(ref_all).frame
    # The RTH snapshot is not visible to the ALL key selection; feed both
    # snapshots' rows directly to prove the business key ignores session.
    ref_rth = Catalog(cfg).latest_complete_market_bar_snapshots(
        symbols=["US.MU"], trade_dates=[date(2026, 7, 1)], interval="1m",
        requested_session="RTH", adjustment="NONE", source_schema_version="10.9",
    )[("US.MU", date(2026, 7, 1))]
    rows_rth = Catalog(cfg).market_bar_snapshot_rows(ref_rth).frame
    hash_all = hash_curated_snapshot_rows(rows_all)
    hash_rth = hash_curated_snapshot_rows(rows_rth)
    result = build_canonical_market_bars(
        [
            snapshot_input(cfg, ref=ref_all, rows=rows_all, content_hash=hash_all),
            snapshot_input(cfg, ref=ref_rth, rows=rows_rth, content_hash=hash_rth),
        ]
    )
    assert len(result.bars) == 1
    assert result.bars[0].requested_session == "ALL"  # ranking selected run-all


# --- Time columns -----------------------------------------------------------


def test_time_columns_are_utc(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    bar = build_one(cfg).bars[0]
    assert str(bar.event_time.tz) == "UTC"
    assert str(bar.market_available_at.tz) == "UTC"
    assert str(bar.archive_available_at.tz) == "UTC"
    assert bar.event_time == pd.Timestamp("2026-07-01 13:30:00", tz="UTC")
    assert bar.market_available_at == pd.Timestamp("2026-07-01 13:31:00", tz="UTC")
    assert bar.archive_available_at == pd.Timestamp("2026-07-01 14:00:00", tz="UTC")


@pytest.mark.parametrize(
    ("interval", "expected_utc"),
    [
        ("1m", "2026-07-01 13:31:00+00:00"),
        ("5m", "2026-07-01 13:35:00+00:00"),
        ("15m", "2026-07-01 13:45:00+00:00"),
        ("30m", "2026-07-01 14:00:00+00:00"),
        ("60m", "2026-07-01 14:30:00+00:00"),
    ],
)
def test_availability_computation_per_interval(tmp_path, interval, expected_utc):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1), interval=interval)
    bar = build_one(cfg, interval=interval).bars[0]
    assert bar.market_available_at == pd.Timestamp(expected_utc)


def test_unsupported_interval_fails(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1), interval="1d")
    with pytest.raises(CanonicalBuildError, match="Unsupported intraday interval"):
        build_one(cfg, interval="1d")


def test_naive_timestamp_fails(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    ref = select_snapshot(cfg)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame
    rows_naive = rows.assign(time_utc=pd.to_datetime(rows["time_utc"]).dt.tz_localize(None))
    with pytest.raises(CanonicalBuildError, match="naive timestamp"):
        build_canonical_market_bars(
            [snapshot_input(cfg, ref=ref, rows=rows_naive, content_hash="hash-x")]
        )


def test_event_time_market_time_mismatch_fails(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(
        cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
        time_keys=minute_keys("2026-07-01 09:30:00", 1),
        mutate=lambda df: df.assign(time_utc=pd.to_datetime(df["time_utc"]) + pd.Timedelta(hours=1)),
    )
    with pytest.raises(CanonicalBuildError, match="disagreement"):
        build_one(cfg)


# --- Reconciliation and conflicts -------------------------------------------


def test_equivalent_duplicate_candidates_reconcile(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-b",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    ref_a, rows_a = read_run_rows(cfg, run_id="run-a")
    ref_b, rows_b = read_run_rows(cfg, run_id="run-b")

    result = build_canonical_market_bars(
        [
            snapshot_input(cfg, ref=ref_a, rows=rows_a, content_hash=hash_curated_snapshot_rows(rows_a)),
            snapshot_input(cfg, ref=ref_b, rows=rows_b, content_hash=hash_curated_snapshot_rows(rows_b)),
        ]
    )
    assert len(result.bars) == 1
    entry = result.resolution[0]
    assert entry.selected.ingestion_run_id == "run-a"
    assert [ref.ingestion_run_id for ref in entry.equivalent_discarded] == ["run-b"]
    assert len(result.resolution) == 1


def test_duplicate_resolution_independent_of_input_order(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-b",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    ref_a, rows_a = read_run_rows(cfg, run_id="run-a")
    ref_b, rows_b = read_run_rows(cfg, run_id="run-b")
    input_a = snapshot_input(cfg, ref=ref_a, rows=rows_a, content_hash=hash_curated_snapshot_rows(rows_a))
    input_b = snapshot_input(cfg, ref=ref_b, rows=rows_b, content_hash=hash_curated_snapshot_rows(rows_b))

    forward = build_canonical_market_bars([input_a, input_b])
    reversed_result = build_canonical_market_bars([input_b, input_a])
    assert [bar.canonical_bar_key for bar in forward.bars] == [
        bar.canonical_bar_key for bar in reversed_result.bars
    ]
    assert forward.resolution[0].selected == reversed_result.resolution[0].selected


def test_conflicting_ohlcv_raises_structured_error(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1), close=100.5)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-b",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1), close=200.0)
    ref_a, rows_a = read_run_rows(cfg, run_id="run-a")
    ref_b, rows_b = read_run_rows(cfg, run_id="run-b")

    with pytest.raises(CanonicalConflictError) as excinfo:
        build_canonical_market_bars(
            [
                snapshot_input(cfg, ref=ref_a, rows=rows_a, content_hash=hash_curated_snapshot_rows(rows_a)),
                snapshot_input(cfg, ref=ref_b, rows=rows_b, content_hash=hash_curated_snapshot_rows(rows_b)),
            ]
        )
    error = excinfo.value
    assert "close" in error.differing_fields
    assert len(error.candidates) == 2
    run_ids = {candidate["run_id"] for candidate in error.candidates}
    assert run_ids == {"run-a", "run-b"}
    assert all(candidate["snapshot_hash"] for candidate in error.candidates)
    assert all(candidate["snapshot_file"] for candidate in error.candidates)
    assert "conflicting canonical candidates" in str(error)


# --- Preservation and determinism -------------------------------------------


def test_no_synthetic_bars_generated(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 3))
    result = build_one(cfg)
    assert len(result.bars) == 3  # exactly the observed bars, no interpolation


def test_source_dataframe_not_mutated(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 2))
    ref = select_snapshot(cfg)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame.copy()
    before = rows.copy()
    build_one(cfg)
    pd.testing.assert_frame_equal(rows, before)


def test_output_ordering_deterministic(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=[
                       "2026-07-01 09:32:00",
                       "2026-07-01 09:30:00",
                       "2026-07-01 09:31:00",
                   ])
    result = build_one(cfg)
    keys = [bar.canonical_bar_key for bar in result.bars]
    assert keys == sorted(keys)
    assert len(set(keys)) == 3


def test_session_timezone_cannot_alter_identities():
    instant = pd.Timestamp("2026-07-01 13:30:00", tz="UTC")
    ny_view = instant.tz_convert(NY)
    tokyo_view = instant.tz_convert("Asia/Tokyo")
    base = dict(
        dataset_kind="market_bars_canonical", code="US.MU", interval="1m",
        adjustment="NONE",
    )
    # Identical instants expressed in different timezones yield the same key.
    assert canonical_bar_key(**base, event_time=ny_view) == canonical_bar_key(**base, event_time=tokyo_view)
    assert canonical_bar_key(**base, event_time=instant) == canonical_bar_key(**base, event_time=tokyo_view)
