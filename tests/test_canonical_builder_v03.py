from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from market_vault.canonical import (
    CANONICAL_BUILDER_VERSION,
    CanonicalBuildError,
    CanonicalConflictError,
    CanonicalRequestKey,
    CanonicalSnapshotInput,
    build_canonical_market_bars,
    canonical_bar_key,
    canonical_row_version_id,
)
from market_vault.canonical.bars import _differing_classification_names
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars
from market_vault.storage import Catalog, ParquetStore
from market_vault.storage.catalog import CompleteSnapshotRef

NY = "America/New_York"
DEFAULT_KEY = CanonicalRequestKey(
    interval="1m", requested_session="ALL", adjustment="NONE", source_schema_version="10.9"
)


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
    code: str | None = None,
    codes: list[str] | None = None,
    trade_date: date,
    run_id: str,
    time_keys: list[str],
    close: float = 100.5,
    session: str = "ALL",
    interval: str = "1m",
    quality: str = "PASS",
    run_finished_at: datetime | None = None,
    mutate=None,
) -> None:
    store = ParquetStore(cfg)
    catalog = Catalog(cfg)
    symbol_codes = codes or [code or "US.MU"]
    frames = []
    for symbol in symbol_codes:
        raw = raw_frame(symbol, time_keys, close=close)
        frames.append(
            normalize_bars(
                raw,
                requested_trade_date=trade_date,
                interval=interval,
                requested_session=session,
                adjustment="NONE",
                source=cfg.source,
                source_schema_version=cfg.source_schema_version,
                run_id=run_id,
            )
        )
    curated = pd.concat(frames, ignore_index=True)
    if mutate is not None:
        curated = mutate(curated)
    store.write_curated(curated, trade_date, interval, symbol_codes, session, "NONE", run_id=run_id)
    run = RunManifest(
        requested_trade_date=trade_date,
        requested_symbols=list(symbol_codes),
        interval=interval.lower(),
        session=session.upper(),
        adjustment="NONE",
        run_id=run_id,
    )
    run.successful_symbols = list(symbol_codes)
    run.status = "SUCCESS"
    run.finished_at = run_finished_at or datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc)
    catalog.record_run(run)
    catalog.record_quality(run.run_id, [QualityResult("bars_complete", quality)])


def select_snapshot(
    cfg: Settings,
    code: str = "US.MU",
    trade_date: date = date(2026, 7, 1),
    interval: str = "1m",
    session: str = "ALL",
):
    refs = Catalog(cfg).latest_complete_market_bar_snapshots(
        symbols=[code], trade_dates=[trade_date], interval=interval,
        requested_session=session, adjustment="NONE", source_schema_version="10.9",
    )
    return refs.get((code, trade_date))


def read_run_rows(cfg: Settings, *, run_id: str) -> tuple[CompleteSnapshotRef, pd.DataFrame]:
    """Read one physical snapshot file by run id and build a ref for it."""
    root = cfg.data_root / "curated" / f"source={cfg.source}" / "dataset=market_bars"
    for path in sorted(root.rglob("*.parquet")):
        frame = pd.read_parquet(path)
        if run_id in set(frame["ingestion_run_id"]):
            trade_date = frame["requested_trade_date"].iloc[0]
            if isinstance(trade_date, pd.Timestamp):
                trade_date = trade_date.date()
            with Catalog(cfg).connect() as con:
                row = con.execute(
                    "SELECT finished_at FROM ingestion_runs WHERE run_id = ?", [run_id]
                ).fetchone()
            finished = pd.Timestamp(row[0]) if row and row[0] is not None else None
            ref = CompleteSnapshotRef(
                code=str(frame["code"].iloc[0]),
                requested_trade_date=trade_date,
                ingestion_run_id=run_id,
                snapshot_file=path.relative_to(cfg.data_root).as_posix(),
                snapshot_ingested_at=None,
                run_finished_at=finished,
                eligible_row_count=len(frame),
            )
            return ref, frame
    raise AssertionError(f"no physical file found for run {run_id}")


def file_hash(cfg: Settings, ref) -> str:
    path = cfg.data_root / ref.snapshot_file
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_input(
    cfg: Settings,
    *,
    ref,
    rows: pd.DataFrame,
    request_key: CanonicalRequestKey = DEFAULT_KEY,
    physical_hash: str | None = None,
) -> CanonicalSnapshotInput:
    if physical_hash is None:
        physical_hash = file_hash(cfg, ref)
    return CanonicalSnapshotInput(
        snapshot=ref,
        rows=rows,
        physical_snapshot_hash=physical_hash,
        request_key=request_key,
    )


def build_one(cfg: Settings, code: str = "US.MU", trade_date: date = date(2026, 7, 1), **kwargs):
    ref = select_snapshot(cfg, code=code, trade_date=trade_date)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame
    return build_canonical_market_bars([make_input(cfg, ref=ref, rows=rows, **kwargs)])


def build_inputs(cfg: Settings, inputs: list[CanonicalSnapshotInput]):
    return build_canonical_market_bars(inputs)


# --- Empty input and COMPLETE gate ------------------------------------------


def test_empty_input_returns_empty_result(tmp_path):
    result = build_canonical_market_bars([])
    assert result.bars == ()
    assert result.resolution == ()
    assert result.source_snapshot_count == 0
    assert result.builder_version == CANONICAL_BUILDER_VERSION


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
    assert select_snapshot(cfg) is None


def test_missing_snapshot_produces_no_rows(tmp_path):
    cfg = settings(tmp_path)
    assert select_snapshot(cfg) is None


# --- Row-set consistency validations ----------------------------------------


def test_mismatched_snapshot_code_fails(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    ref = select_snapshot(cfg)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame.assign(code="US.NVDA")
    with pytest.raises(CanonicalBuildError, match="does not match snapshot code"):
        build_inputs(cfg, [make_input(cfg, ref=ref, rows=rows)])


def test_mismatched_run_id_fails(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    ref = select_snapshot(cfg)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame.assign(ingestion_run_id="run-other")
    with pytest.raises(CanonicalBuildError, match="does not match snapshot run"):
        build_inputs(cfg, [make_input(cfg, ref=ref, rows=rows)])


def test_mismatched_requested_trade_date_fails(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    ref = select_snapshot(cfg)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame.assign(
        requested_trade_date=pd.Timestamp("2026-07-02")
    )
    with pytest.raises(CanonicalBuildError, match="does not match snapshot"):
        build_inputs(cfg, [make_input(cfg, ref=ref, rows=rows)])


@pytest.mark.parametrize(
    ("column", "bad_value"),
    [
        ("interval", "5m"),
        ("requested_session", "RTH"),
        ("adjustment", "QFQ"),
        ("source_schema_version", "10.8"),
    ],
)
def test_mismatched_request_key_field_fails(tmp_path, column, bad_value):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    ref = select_snapshot(cfg)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame.assign(**{column: bad_value})
    with pytest.raises(CanonicalBuildError, match="does not match"):
        build_inputs(cfg, [make_input(cfg, ref=ref, rows=rows)])


def test_mixed_interval_rows_fail(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 2))
    ref = select_snapshot(cfg)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame.copy()
    rows.loc[1, "interval"] = "5m"
    with pytest.raises(CanonicalBuildError, match="mixed interval rows"):
        build_inputs(cfg, [make_input(cfg, ref=ref, rows=rows)])


def test_eligible_row_count_mismatch_fails(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 2))
    ref = select_snapshot(cfg)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame.iloc[:1]
    with pytest.raises(CanonicalBuildError, match="eligible_row_count"):
        build_inputs(cfg, [make_input(cfg, ref=ref, rows=rows)])


@pytest.mark.parametrize(
    ("column", "bad_value"),
    [("open", float("nan")), ("high", float("inf")), ("close", "not-a-number")],
)
def test_invalid_market_values_fail_closed(tmp_path, column, bad_value):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    ref = select_snapshot(cfg)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame.assign(**{column: bad_value})
    with pytest.raises(CanonicalBuildError):
        build_inputs(cfg, [make_input(cfg, ref=ref, rows=rows)])


# --- Hashing ----------------------------------------------------------------


def test_physical_snapshot_hash_validated(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    ref = select_snapshot(cfg)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame
    with pytest.raises(CanonicalBuildError, match="SHA-256"):
        build_inputs(cfg, [make_input(cfg, ref=ref, rows=rows, physical_hash="")])
    with pytest.raises(CanonicalBuildError, match="SHA-256"):
        build_inputs(cfg, [make_input(cfg, ref=ref, rows=rows, physical_hash="not-a-hash")])
    # Uppercase hex is normalized to lowercase and accepted.
    upper = file_hash(cfg, ref).upper()
    result = build_inputs(cfg, [make_input(cfg, ref=ref, rows=rows, physical_hash=upper)])
    assert len(result.bars) == 1


def test_optional_field_change_changes_logical_hash(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    ref = select_snapshot(cfg)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame
    base = build_inputs(cfg, [make_input(cfg, ref=ref, rows=rows)]).bars[0]

    with_turnover = build_inputs(cfg, [
        make_input(cfg, ref=ref, rows=rows.assign(turnover=1234.5))
    ]).bars[0]
    assert with_turnover.logical_source_rows_hash != base.logical_source_rows_hash
    assert with_turnover.extra_fields == (("turnover", 1234.5),)


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


def test_repeated_collection_keeps_key_changes_row_version(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    first = build_one(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-b",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    second = build_one(cfg)
    assert first.bars[0].canonical_bar_key == second.bars[0].canonical_bar_key
    assert first.bars[0].canonical_row_version_id != second.bars[0].canonical_row_version_id


def test_builder_version_changes_only_row_version_id():
    key = canonical_bar_key(
        dataset_kind="market_bars_canonical", code="US.MU", interval="1m",
        adjustment="NONE", event_time=pd.Timestamp("2026-07-01 13:30:00", tz="UTC"),
    )
    base = dict(
        canonical_bar_key=key,
        ingestion_run_id="run-a",
        source_snapshot_content_hash="a" * 64,
        source_schema_version="10.9",
    )
    v1 = canonical_row_version_id(**base, canonical_builder_version="market-bars-canonical-v1")
    v2 = canonical_row_version_id(**base, canonical_builder_version="market-bars-canonical-v2")
    assert v1 != v2
    assert canonical_bar_key(
        dataset_kind="market_bars_canonical", code="US.MU", interval="1m",
        adjustment="NONE", event_time=pd.Timestamp("2026-07-01 13:30:00", tz="UTC"),
    ) == key


def test_snapshot_path_does_not_affect_identities(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    ref_a = select_snapshot(cfg)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref_a).frame
    # Two inputs with the same run/content but different descriptive paths.
    ref_b = CompleteSnapshotRef(
        code=ref_a.code,
        requested_trade_date=ref_a.requested_trade_date,
        ingestion_run_id=ref_a.ingestion_run_id,
        snapshot_file="curated/source=moomoo/dataset=market_bars/interval=1m/requested_trade_date=2026-07-01/relocated.parquet",
        snapshot_ingested_at=None,
        run_finished_at=ref_a.run_finished_at,
        eligible_row_count=ref_a.eligible_row_count,
    )
    result = build_inputs(cfg, [
        make_input(cfg, ref=ref_a, rows=rows),
        make_input(cfg, ref=ref_b, rows=rows, physical_hash=file_hash(cfg, ref_a)),
    ])
    assert len(result.bars) == 1
    bar = result.bars[0]
    # Identities are path-independent; snapshot_file is descriptive only.
    assert bar.snapshot_file == ref_a.snapshot_file  # ranking selected run-a's path
    single = build_one(cfg).bars[0]
    assert bar.canonical_bar_key == single.canonical_bar_key
    assert bar.canonical_row_version_id == single.canonical_row_version_id


def test_session_timezone_cannot_alter_identities():
    instant = pd.Timestamp("2026-07-01 13:30:00", tz="UTC")
    base = dict(
        dataset_kind="market_bars_canonical", code="US.MU", interval="1m",
        adjustment="NONE",
    )
    assert canonical_bar_key(**base, event_time=instant) == canonical_bar_key(
        **base, event_time=instant.tz_convert(NY)
    )
    assert canonical_bar_key(**base, event_time=instant) == canonical_bar_key(
        **base, event_time=instant.tz_convert("Asia/Tokyo")
    )


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
    request_key = CanonicalRequestKey(
        interval=interval, requested_session="ALL", adjustment="NONE", source_schema_version="10.9"
    )
    ref = select_snapshot(cfg, interval=interval)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame
    bar = build_inputs(cfg, [make_input(cfg, ref=ref, rows=rows, request_key=request_key)]).bars[0]
    assert bar.market_available_at == pd.Timestamp(expected_utc)


def test_unsupported_interval_fails(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1), interval="1d")
    request_key = CanonicalRequestKey(
        interval="1d", requested_session="ALL", adjustment="NONE", source_schema_version="10.9"
    )
    ref = select_snapshot(cfg, interval="1d")
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame
    with pytest.raises(CanonicalBuildError, match="Unsupported intraday interval"):
        build_inputs(cfg, [make_input(cfg, ref=ref, rows=rows, request_key=request_key)])


def test_naive_timestamp_fails(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    ref = select_snapshot(cfg)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame.assign(
        time_utc=pd.to_datetime(pd.Series(["2026-07-01 13:30:00"]))
    )
    with pytest.raises(CanonicalBuildError, match="naive timestamp"):
        build_inputs(cfg, [make_input(cfg, ref=ref, rows=rows)])


def test_event_time_market_time_mismatch_fails(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    ref = select_snapshot(cfg)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame.assign(
        time_utc=pd.to_datetime(
            Catalog(cfg).market_bar_snapshot_rows(ref).frame["time_utc"]
        ) + pd.Timedelta(hours=1)
    )
    with pytest.raises(CanonicalBuildError, match="disagreement"):
        build_inputs(cfg, [make_input(cfg, ref=ref, rows=rows)])


# --- Reconciliation and conflicts -------------------------------------------


def test_equivalent_duplicates_reconcile_with_documented_ranking(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1),
                   run_finished_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc))
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-b",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1),
                   run_finished_at=datetime(2026, 7, 1, 13, 0, tzinfo=timezone.utc))
    ref_a, rows_a = read_run_rows(cfg, run_id="run-a")
    ref_b, rows_b = read_run_rows(cfg, run_id="run-b")

    result = build_inputs(cfg, [
        make_input(cfg, ref=ref_a, rows=rows_a),
        make_input(cfg, ref=ref_b, rows=rows_b),
    ])
    assert len(result.bars) == 1
    entry = result.resolution[0]
    # run_finished_at descending: run-b is newer and selected.
    assert entry.selected.ingestion_run_id == "run-b"
    assert [ref.ingestion_run_id for ref in entry.equivalent_discarded] == ["run-a"]


def test_duplicate_resolution_independent_of_input_order(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-b",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    ref_a, rows_a = read_run_rows(cfg, run_id="run-a")
    ref_b, rows_b = read_run_rows(cfg, run_id="run-b")
    input_a = make_input(cfg, ref=ref_a, rows=rows_a)
    input_b = make_input(cfg, ref=ref_b, rows=rows_b)

    forward = build_inputs(cfg, [input_a, input_b])
    reversed_result = build_inputs(cfg, [input_b, input_a])
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
        build_inputs(cfg, [
            make_input(cfg, ref=ref_a, rows=rows_a),
            make_input(cfg, ref=ref_b, rows=rows_b),
        ])
    error = excinfo.value
    assert "close" in error.differing_fields
    assert len(error.candidates) == 2
    assert {candidate["run_id"] for candidate in error.candidates} == {"run-a", "run-b"}
    assert all(candidate["snapshot_hash"] for candidate in error.candidates)
    assert all(candidate["snapshot_file"] for candidate in error.candidates)
    assert "conflicting canonical candidates" in str(error)


def test_conflicting_derived_classification_detected():
    # Derived classification is a function of the instant, so legal inputs
    # cannot produce a conflict; the reconciliation comparison still guards
    # against drift by treating any difference as a conflict.
    reference = ("2026-07-01", "REGULAR")
    assert _differing_classification_names(reference, ("2026-07-02", "REGULAR")) == (
        "market_calendar_date",
    )
    assert _differing_classification_names(reference, ("2026-07-01", "AFTER_HOURS")) == (
        "session",
    )
    assert _differing_classification_names(reference, reference) == ()


def test_same_key_same_instant_different_tz_not_conflict(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    ref = select_snapshot(cfg)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame
    rows_tokyo = rows.assign(
        time_market=pd.to_datetime(rows["time_market"]).dt.tz_convert("Asia/Tokyo")
    )
    result = build_inputs(cfg, [
        make_input(cfg, ref=ref, rows=rows),
        make_input(cfg, ref=ref, rows=rows_tokyo),
    ])
    assert len(result.bars) == 1


# --- Determinism and counting -----------------------------------------------


def test_source_snapshot_count_counts_physical_files(tmp_path):
    cfg = settings(tmp_path)
    # Two physical files carrying the same run id (different symbol sets
    # produce different batch keys): one run, two physical snapshots.
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-x",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    write_snapshot(cfg, codes=["US.MU", "US.NVDA"], trade_date=date(2026, 7, 1), run_id="run-x",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    root = cfg.data_root / "curated" / f"source={cfg.source}" / "dataset=market_bars"
    paths = sorted(root.rglob("*.parquet"))
    assert len(paths) == 2
    inputs = []
    for path in paths:
        frame = pd.read_parquet(path)
        frame_mu = frame[frame["code"] == "US.MU"].reset_index(drop=True)
        with Catalog(cfg).connect() as con:
            row = con.execute(
                "SELECT finished_at FROM ingestion_runs WHERE run_id = ?", ["run-x"]
            ).fetchone()
        finished = pd.Timestamp(row[0]) if row and row[0] is not None else None
        ref = CompleteSnapshotRef(
            code="US.MU",
            requested_trade_date=date(2026, 7, 1),
            ingestion_run_id="run-x",
            snapshot_file=path.relative_to(cfg.data_root).as_posix(),
            snapshot_ingested_at=None,
            run_finished_at=finished,
            eligible_row_count=len(frame_mu),
        )
        inputs.append(make_input(cfg, ref=ref, rows=frame_mu))
    result = build_inputs(cfg, inputs)
    # Distinct physical identities (files), not distinct run ids.
    assert result.source_snapshot_count == 2
    assert len(result.bars) == 1  # same business key reconciled


def test_actual_dataframe_not_mutated(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 2))
    ref = select_snapshot(cfg)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame.copy()
    before = rows.copy()
    build_one(cfg)
    pd.testing.assert_frame_equal(rows, before)


def test_duplicate_dataframe_index_handled(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 2))
    ref = select_snapshot(cfg)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame.copy()
    duplicated = rows.copy()
    duplicated.index = [0, 0]  # duplicate labels must not break positional lookup
    result = build_inputs(cfg, [make_input(cfg, ref=ref, rows=duplicated)])
    assert len(result.bars) == 2


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


def test_full_result_independent_of_input_order(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-b",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    ref_a, rows_a = read_run_rows(cfg, run_id="run-a")
    ref_b, rows_b = read_run_rows(cfg, run_id="run-b")
    input_a = make_input(cfg, ref=ref_a, rows=rows_a)
    input_b = make_input(cfg, ref=ref_b, rows=rows_b)

    forward = build_inputs(cfg, [input_a, input_b])
    reversed_result = build_inputs(cfg, [input_b, input_a])
    for a, b in zip(forward.bars, reversed_result.bars):
        assert a.canonical_bar_key == b.canonical_bar_key
        assert a.canonical_row_version_id == b.canonical_row_version_id
        assert a.event_time == b.event_time
        assert a.snapshot_file == b.snapshot_file  # descriptive provenance is stable


def test_no_synthetic_bars_generated(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 3))
    result = build_one(cfg)
    assert len(result.bars) == 3


# --- Targeted corrections ---------------------------------------------------


def test_ranking_run_id_descending_when_timestamps_tied(tmp_path):
    cfg = settings(tmp_path)
    # Identical ingested_at and run_finished_at: run-b must rank before run-a
    # (descending lexicographic run id).
    shared_ingested = pd.Timestamp("2026-07-01 13:00:00", tz="UTC")
    shared_finished = datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1),
                   run_finished_at=shared_finished)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-b",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1),
                   run_finished_at=shared_finished)
    ref_a, rows_a = read_run_rows(cfg, run_id="run-a")
    ref_b, rows_b = read_run_rows(cfg, run_id="run-b")
    input_a = make_input(cfg, ref=ref_a, rows=rows_a)
    input_b = make_input(cfg, ref=ref_b, rows=rows_b)
    # Same ingested_at and finished_at on both refs.
    for ref in (ref_a, ref_b):
        object.__setattr__(ref, "snapshot_ingested_at", shared_ingested)
        object.__setattr__(ref, "run_finished_at", shared_finished)

    result = build_inputs(cfg, [input_a, input_b])
    assert len(result.bars) == 1
    assert result.resolution[0].selected.ingestion_run_id == "run-b"
    assert [ref.ingestion_run_id for ref in result.resolution[0].equivalent_discarded] == ["run-a"]


def test_stored_session_case_insensitive_equivalence(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(
        cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
        time_keys=minute_keys("2026-07-01 09:30:00", 1),
        mutate=lambda df: df.assign(session="regular"),
    )
    ref = select_snapshot(cfg)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame
    result = build_inputs(cfg, [make_input(cfg, ref=ref, rows=rows)])
    assert len(result.bars) == 1
    assert result.bars[0].session == "REGULAR"


def test_missing_market_calendar_date_fails_closed(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(
        cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
        time_keys=minute_keys("2026-07-01 09:30:00", 1),
        mutate=lambda df: df.assign(market_calendar_date=None),
    )
    ref = select_snapshot(cfg)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame
    with pytest.raises(CanonicalBuildError, match="market_calendar_date is required"):
        build_inputs(cfg, [make_input(cfg, ref=ref, rows=rows)])


def test_classification_conflict_field_order():
    from market_vault.canonical.bars import _differing_classification_names

    reference = ("2026-07-01", "REGULAR")
    assert _differing_classification_names(reference, ("2026-07-01", "AFTER_HOURS")) == (
        "session",
    )
    assert _differing_classification_names(reference, ("2026-07-02", "AFTER_HOURS")) == (
        "market_calendar_date",
        "session",
    )


def test_source_snapshot_count_path_independent(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    ref = select_snapshot(cfg)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame
    relocated = CompleteSnapshotRef(
        code=ref.code,
        requested_trade_date=ref.requested_trade_date,
        ingestion_run_id=ref.ingestion_run_id,
        snapshot_file="curated/source=moomoo/dataset=market_bars/interval=1m/requested_trade_date=2026-07-01/relocated.parquet",
        snapshot_ingested_at=ref.snapshot_ingested_at,
        run_finished_at=ref.run_finished_at,
        eligible_row_count=ref.eligible_row_count,
    )
    physical = file_hash(cfg, ref)
    # Same stable identity, different descriptive path: count stays 1.
    result = build_inputs(cfg, [
        make_input(cfg, ref=ref, rows=rows),
        make_input(cfg, ref=relocated, rows=rows, physical_hash=physical),
    ])
    assert result.source_snapshot_count == 1


@pytest.mark.parametrize(
    ("column", "bad_value"),
    [
        ("turnover", float("inf")),
        ("turnover", float("-inf")),
        ("turnover", "not-a-number"),
    ],
)
def test_malformed_optional_field_fails_closed(tmp_path, column, bad_value):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    ref = select_snapshot(cfg)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame.assign(**{column: bad_value})
    with pytest.raises(CanonicalBuildError):
        build_inputs(cfg, [make_input(cfg, ref=ref, rows=rows)])


@pytest.mark.parametrize(
    ("column", "null_value"),
    [("turnover", None), ("turnover", float("nan")), ("turnover", pd.NA)],
)
def test_null_optional_field_allowed(tmp_path, column, null_value):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    ref = select_snapshot(cfg)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame
    rows_null = rows.copy()
    rows_null[column] = null_value
    result = build_inputs(cfg, [make_input(cfg, ref=ref, rows=rows_null)])
    assert result.bars[0].extra_fields == ()


def test_naive_snapshot_ingested_at_fails_closed(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    ref = select_snapshot(cfg)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame
    object.__setattr__(ref, "snapshot_ingested_at", pd.Timestamp("2026-07-01 13:00:00"))
    with pytest.raises(CanonicalBuildError, match="snapshot_ingested_at must be timezone-aware"):
        build_inputs(cfg, [make_input(cfg, ref=ref, rows=rows)])


def test_ranking_independent_of_local_timezone_representation(tmp_path):
    cfg = settings(tmp_path)
    instant = pd.Timestamp("2026-07-01 13:00:00", tz="UTC")
    finished = datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1),
                   run_finished_at=finished)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-b",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1),
                   run_finished_at=finished)
    ref_a, rows_a = read_run_rows(cfg, run_id="run-a")
    ref_b, rows_b = read_run_rows(cfg, run_id="run-b")
    object.__setattr__(ref_a, "snapshot_ingested_at", instant)
    object.__setattr__(ref_b, "snapshot_ingested_at", instant.tz_convert("Asia/Tokyo"))

    result = build_inputs(cfg, [
        make_input(cfg, ref=ref_a, rows=rows_a),
        make_input(cfg, ref=ref_b, rows=rows_b),
    ])
    # Same instant expressed in different timezones must rank identically:
    # run_b descends before run-a (run id tie-break).
    assert result.resolution[0].selected.ingestion_run_id == "run-b"


def test_logical_hash_computed_once_per_snapshot(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 3))
    ref = select_snapshot(cfg)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame
    calls = []

    import market_vault.canonical.bars as bars_module

    original = bars_module._hash_normalized_records
    monkeypatch.setattr(
        bars_module,
        "_hash_normalized_records",
        lambda records: calls.append(len(records)) or original(records),
    )
    result = build_inputs(cfg, [make_input(cfg, ref=ref, rows=rows)])
    assert len(result.bars) == 3
    assert calls == [3]  # once per snapshot, not once per candidate


def test_ranking_prefix_run_ids_descending(tmp_path):
    cfg = settings(tmp_path)
    # "run-a" > "run" lexicographically: descending order picks run-a.
    shared_ingested = pd.Timestamp("2026-07-01 13:00:00", tz="UTC")
    shared_finished = datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1),
                   run_finished_at=shared_finished)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1),
                   run_finished_at=shared_finished)
    ref_a, rows_a = read_run_rows(cfg, run_id="run")
    ref_b, rows_b = read_run_rows(cfg, run_id="run-a")
    for ref in (ref_a, ref_b):
        object.__setattr__(ref, "snapshot_ingested_at", shared_ingested)
        object.__setattr__(ref, "run_finished_at", shared_finished)

    result = build_inputs(cfg, [
        make_input(cfg, ref=ref_a, rows=rows_a),
        make_input(cfg, ref=ref_b, rows=rows_b),
    ])
    assert result.resolution[0].selected.ingestion_run_id == "run-a"
    # Input order must not affect the selected source.
    swapped = build_inputs(cfg, [
        make_input(cfg, ref=ref_b, rows=rows_b),
        make_input(cfg, ref=ref_a, rows=rows_a),
    ])
    assert swapped.resolution[0].selected.ingestion_run_id == "run-a"


def test_nat_ranking_timestamp_ranks_nulls_last(tmp_path):
    cfg = settings(tmp_path)
    finished = datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1),
                   run_finished_at=finished)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-b",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1),
                   run_finished_at=finished)
    ref_a, rows_a = read_run_rows(cfg, run_id="run-a")
    ref_b, rows_b = read_run_rows(cfg, run_id="run-b")
    object.__setattr__(ref_a, "snapshot_ingested_at", pd.NaT)  # nulls last
    object.__setattr__(ref_b, "snapshot_ingested_at", pd.Timestamp("2026-07-01 13:00:00", tz="UTC"))

    result = build_inputs(cfg, [
        make_input(cfg, ref=ref_a, rows=rows_a),
        make_input(cfg, ref=ref_b, rows=rows_b),
    ])
    # run-b has a present ingested_at and wins; run-a (NaT) ranks last.
    assert result.resolution[0].selected.ingestion_run_id == "run-b"


def test_logical_hash_normalizes_equivalent_semantics(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1))
    ref = select_snapshot(cfg)
    rows = Catalog(cfg).market_bar_snapshot_rows(ref).frame
    base = build_inputs(cfg, [make_input(cfg, ref=ref, rows=rows)]).bars[0]

    # Equivalent casing/whitespace and timezone representation must produce
    # the same logical source-row hash.
    rows_equiv = rows.copy()
    rows_equiv["session"] = " regular "
    rows_equiv["time_market"] = pd.to_datetime(rows_equiv["time_market"]).dt.tz_convert("Asia/Tokyo")
    result = build_inputs(cfg, [make_input(cfg, ref=ref, rows=rows_equiv)]).bars[0]
    assert result.logical_source_rows_hash == base.logical_source_rows_hash
    assert result.canonical_row_version_id == base.canonical_row_version_id
