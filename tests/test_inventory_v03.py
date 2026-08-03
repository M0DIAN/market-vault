from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

import market_vault.cli as cli_module
from market_vault.audit import run_inventory
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars
from market_vault.storage import Catalog, ParquetStore


def write_settings_file(tmp_path) -> Path:
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / "settings.yaml"
    cfg_path.write_text(
        "opend:\n"
        "  host: 127.0.0.1\n"
        "  port: 11111\n"
        "storage:\n"
        "  root_dir: ./data\n"
        "  catalog_path: ./catalog/market_vault.duckdb\n"
        "  manifest_dir: ./manifests\n"
        "  report_dir: ./reports\n"
        "collector:\n"
        "  source: moomoo\n"
        "  source_schema_version: \"10.9\"\n"
        "  default_session: ALL\n"
        "  default_adjustment: NONE\n",
        encoding="utf-8",
    )
    return cfg_path


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


def history_raw_frame(code: str, trade_date: date, close: float = 100.5) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "code": [code],
            "name": [code],
            "time_key": [f"{trade_date.isoformat()} 09:30:00"],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [close],
            "volume": [100],
        }
    )


def write_snapshot(
    cfg: Settings,
    *,
    code: str,
    trade_date: date,
    run_id: str,
    **kwargs,
) -> None:
    write_multi_snapshot(cfg, codes=[code], trade_date=trade_date, run_id=run_id, **kwargs)


def write_multi_snapshot(
    cfg: Settings,
    *,
    codes: list[str],
    trade_date: date,
    run_id: str,
    interval: str = "1m",
    session: str = "ALL",
    adjustment: str = "NONE",
    schema: str = "10.9",
    close: float = 100.5,
    run_status: str = "SUCCESS",
    quality: str = "PASS",
    include_session: bool = True,
    include_schema: bool = True,
    legacy_filename: bool = False,
    record_run: bool = True,
) -> None:
    """Write one real Parquet file whose rows carry the same run id for every
    symbol, mirroring a single child run that collected several symbols."""
    store = ParquetStore(cfg)
    catalog = Catalog(cfg)
    raw_frames: list[pd.DataFrame] = []
    curated_frames: list[pd.DataFrame] = []
    for code in codes:
        raw = history_raw_frame(code, trade_date, close=close)
        raw["requested_trade_date"] = trade_date
        raw["interval"] = interval.lower()
        raw["adjustment"] = adjustment.upper()
        raw["requested_session"] = session.upper()
        raw["ingestion_run_id"] = run_id
        raw_frames.append(raw)
        curated_frames.append(
            normalize_bars(
                raw,
                requested_trade_date=trade_date,
                interval=interval,
                requested_session=session,
                adjustment=adjustment,
                source=cfg.source,
                source_schema_version=schema,
                run_id=run_id,
            )
        )
    raw = pd.concat(raw_frames, ignore_index=True)
    curated = pd.concat(curated_frames, ignore_index=True)
    if not include_session:
        raw = raw.drop(columns=["requested_session"])
        curated = curated.drop(columns=["requested_session"])
    if not include_schema:
        # Raw frames never carry source_schema_version; only curated does.
        curated = curated.drop(columns=["source_schema_version"])

    batch_key = ParquetStore._batch_key(codes, interval.lower(), session.upper(), adjustment.upper())
    if legacy_filename:
        raw_path = (
            cfg.data_root
            / "raw"
            / f"source={cfg.source}"
            / "dataset=market_bars"
            / f"interval={interval.lower()}"
            / f"requested_trade_date={trade_date.isoformat()}"
            / f"batch-{batch_key}.parquet"
        )
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw.to_parquet(raw_path, index=False, compression="zstd")
        curated_path = (
            cfg.data_root
            / "curated"
            / f"source={cfg.source}"
            / "dataset=market_bars"
            / f"interval={interval.lower()}"
            / f"requested_trade_date={trade_date.isoformat()}"
            / f"batch-{batch_key}.parquet"
        )
        curated_path.parent.mkdir(parents=True, exist_ok=True)
        curated.to_parquet(curated_path, index=False, compression="zstd")
    else:
        store.write_raw(raw, trade_date, interval, codes, session, adjustment, run_id=run_id)
        store.write_curated(curated, trade_date, interval, codes, session, adjustment, run_id=run_id)

    if not record_run:
        return
    run = RunManifest(
        requested_trade_date=trade_date,
        requested_symbols=list(codes),
        interval=interval.lower(),
        session=session.upper(),
        adjustment=adjustment.upper(),
        run_id=run_id,
    )
    run.successful_symbols = list(codes)
    run.status = run_status
    run.finished_at = datetime.now(timezone.utc)
    catalog.record_run(run)
    catalog.record_quality(run.run_id, [QualityResult("bars_complete", quality)])


def curated_glob(cfg: Settings) -> str:
    root = cfg.data_root / "curated" / f"source={cfg.source}" / "dataset=market_bars"
    return (root / "**" / "*.parquet").as_posix().replace("'", "''")


# --- DuckDB views -----------------------------------------------------------


def test_refresh_market_bars_view_false_without_files(tmp_path):
    catalog = Catalog(settings(tmp_path))
    assert catalog.refresh_market_bars_view() is False


def test_snapshots_view_contains_all_snapshots(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a")
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-b")
    catalog = Catalog(cfg)
    assert catalog.refresh_market_bars_view()
    with catalog.connect() as con:
        rows = con.execute("SELECT ingestion_run_id FROM market_bars_snapshots ORDER BY ingestion_run_id").fetchall()
    assert [row[0] for row in rows] == ["run-a", "run-b"]


def test_market_bars_view_returns_latest_snapshot_only(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a", close=100.5)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-b", close=200.0)
    catalog = Catalog(cfg)
    assert catalog.refresh_market_bars_view()
    with catalog.connect() as con:
        rows = con.execute(
            "SELECT code, close, ingestion_run_id FROM market_bars WHERE requested_trade_date = ?",
            [date(2026, 7, 1)],
        ).fetchall()
    # Both snapshots have the same time_utc; the view keeps the newest
    # ingested_at row only.
    assert rows == [("US.MU", 200.0, "run-b")]


def test_old_and_new_files_both_readable(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="legacy-run", legacy_filename=True)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-new")
    catalog = Catalog(cfg)
    assert catalog.refresh_market_bars_view()
    with catalog.connect() as con:
        rows = con.execute("SELECT DISTINCT ingestion_run_id FROM market_bars_snapshots").fetchall()
    assert {row[0] for row in rows} == {"legacy-run", "run-new"}


def test_legacy_files_missing_columns_do_not_break_views(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(
        cfg,
        code="US.MU",
        trade_date=date(2026, 7, 1),
        run_id="legacy-run",
        legacy_filename=True,
        include_session=False,
        include_schema=False,
    )
    catalog = Catalog(cfg)
    assert catalog.refresh_market_bars_view()
    with catalog.connect() as con:
        count = con.execute("SELECT COUNT(*) FROM market_bars_snapshots").fetchone()[0]
    assert count == 1


# --- Inventory --------------------------------------------------------------


def test_inventory_empty_database_returns_empty(tmp_path):
    report = run_inventory(settings(tmp_path))
    assert report.status == "EMPTY"
    assert report.summary.snapshot_count == 0
    assert report.summary.snapshot_row_count == 0
    assert report.summary.present_trade_date_count == 0
    assert report.physical_storage.raw_file_count == 0
    assert report.items == []


def test_inventory_raw_and_curated_file_counts(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a")
    report = run_inventory(cfg)
    assert report.physical_storage.raw_file_count == 1
    assert report.physical_storage.curated_file_count == 1


def test_inventory_total_bytes(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a")
    report = run_inventory(cfg)
    raw_root = cfg.data_root / "raw" / f"source={cfg.source}" / "dataset=market_bars"
    curated_root = cfg.data_root / "curated" / f"source={cfg.source}" / "dataset=market_bars"
    expected_raw = sum(p.stat().st_size for p in raw_root.rglob("*.parquet"))
    expected_curated = sum(p.stat().st_size for p in curated_root.rglob("*.parquet"))
    assert report.physical_storage.raw_total_bytes == expected_raw
    assert report.physical_storage.curated_total_bytes == expected_curated


def test_inventory_include_files_off_by_default(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a")
    report = run_inventory(cfg)
    assert report.files == []


def test_inventory_include_files_lists_relative_paths(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a")
    report = run_inventory(cfg, include_files=True)
    assert len(report.files) == 2
    assert {entry.layer for entry in report.files} == {"raw", "curated"}
    for entry in report.files:
        assert not Path(entry.relative_path).is_absolute()
        assert "market_bars" in entry.relative_path
        assert entry.size_bytes > 0
        assert entry.modified_at


def test_inventory_legacy_filename_detection(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="legacy-run", legacy_filename=True)
    report = run_inventory(cfg, include_files=True)
    assert all(entry.legacy_filename for entry in report.files)


def test_inventory_snapshot_filename_detection(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a")
    report = run_inventory(cfg, include_files=True)
    assert all(not entry.legacy_filename for entry in report.files)
    assert any("run-a" in entry.relative_path for entry in report.files)


def test_inventory_symbol_filter(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-mu")
    write_snapshot(cfg, code="US.NVDA", trade_date=date(2026, 7, 1), run_id="run-nvda")
    report = run_inventory(cfg, symbols=["US.MU"])
    assert [item.code for item in report.items] == ["US.MU"]
    assert report.summary.symbol_count == 1


def test_inventory_date_filter(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-1")
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 2), run_id="run-2")
    report = run_inventory(cfg, start_date=date(2026, 7, 2), end_date=date(2026, 7, 2))
    item = report.items[0]
    assert item.first_trade_date == "2026-07-02"
    assert item.last_trade_date == "2026-07-02"
    assert item.present_trade_date_count == 1


def test_inventory_interval_filter(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-1m", interval="1m")
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-5m", interval="5m")
    report = run_inventory(cfg, interval="5m")
    assert [item.interval for item in report.items] == ["5m"]


def test_inventory_session_filter(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-all", session="ALL")
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-rth", session="RTH")
    report = run_inventory(cfg, requested_session="RTH")
    assert [item.requested_session for item in report.items] == ["RTH"]


def test_inventory_adjustment_filter(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-none", adjustment="NONE")
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-qfq", adjustment="QFQ")
    report = run_inventory(cfg, adjustment="QFQ")
    assert [item.adjustment for item in report.items] == ["QFQ"]


def test_inventory_schema_filter(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-109", schema="10.9")
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-108", schema="10.8")
    report = run_inventory(cfg, source_schema_version="10.8")
    assert [item.source_schema_version for item in report.items] == ["10.8"]


def test_inventory_snapshot_count(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a")
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-b")
    report = run_inventory(cfg)
    assert report.items[0].snapshot_count == 2
    assert report.summary.snapshot_count == 2


def test_inventory_snapshot_row_count(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a")
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-b")
    report = run_inventory(cfg)
    assert report.items[0].snapshot_row_count == 2
    assert report.summary.snapshot_row_count == 2


def test_inventory_latest_query_row_count(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a")
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-b")
    report = run_inventory(cfg)
    # Both snapshots contain the same single bar; the public query view
    # deduplicates to one row.
    assert report.summary.latest_query_row_count == 1


def test_inventory_present_date_count(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-1")
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 2), run_id="run-2")
    report = run_inventory(cfg)
    assert report.items[0].present_trade_date_count == 2
    assert report.summary.present_trade_date_count == 2


def test_inventory_completed_date_count(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-ok")
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 2), run_id="run-bad", quality="FAIL")
    report = run_inventory(cfg)
    assert report.items[0].completed_trade_date_count == 1
    assert report.summary.completed_trade_date_count == 1


def test_inventory_incomplete_date_count(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-ok")
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 2), run_id="run-bad", quality="FAIL")
    report = run_inventory(cfg)
    assert report.items[0].incomplete_trade_date_count == 1
    assert report.summary.incomplete_trade_date_count == 1
    assert report.summary.completed_trade_date_count + report.summary.incomplete_trade_date_count == 2


def test_inventory_legacy_metadata_row_count(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(
        cfg,
        code="US.MU",
        trade_date=date(2026, 7, 1),
        run_id="legacy-run",
        legacy_filename=True,
        include_session=False,
        include_schema=False,
    )
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-new")
    report = run_inventory(cfg)
    assert report.summary.legacy_metadata_row_count == 1


def test_inventory_multi_symbol_sorted_stable(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.NVDA", trade_date=date(2026, 7, 1), run_id="run-nvda")
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-mu")
    report = run_inventory(cfg)
    assert [item.code for item in report.items] == ["US.MU", "US.NVDA"]


def test_inventory_report_json_written(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a")
    report = run_inventory(cfg)
    assert report.report_file is not None
    path = Path(report.report_file)
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["run_id"] == report.run_id
    assert payload["report_type"] == "MARKET_BARS_INVENTORY"
    assert payload["summary"]["snapshot_row_count"] == 1


def test_inventory_report_atomic_no_temp_files(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a")
    run_inventory(cfg)
    leftovers = [p for p in cfg.report_dir.rglob("*.tmp")] if cfg.report_dir.exists() else []
    assert leftovers == []


def test_inventory_does_not_touch_open_d(monkeypatch, tmp_path):
    class Raiser:
        def __init__(self, settings):
            raise AssertionError("OpenD collector must not be constructed")

    monkeypatch.setattr("market_vault.collectors.MoomooHistoryCollector", Raiser)
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a")
    report = run_inventory(cfg)
    assert report.status == "SUCCESS"


def test_inventory_earliest_and_latest_trade_date_across_combinations(tmp_path):
    cfg = settings(tmp_path)
    # Combination A (1m) spans 2026-01-01 .. 2026-07-31.
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 1, 1), run_id="run-a1", interval="1m")
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 31), run_id="run-a2", interval="1m")
    # Combination B (5m) spans 2026-03-01 .. 2026-05-31.
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 3, 1), run_id="run-b1", interval="5m")
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 5, 31), run_id="run-b2", interval="5m")

    report = run_inventory(cfg)

    # earliest comes from the minimum first date; latest from the maximum
    # last date -- not from a single min/max over first dates.
    assert report.summary.earliest_trade_date == "2026-01-01"
    assert report.summary.latest_trade_date == "2026-07-31"
    assert len(report.items) == 2


def test_inventory_global_snapshot_count_multi_symbol_same_run(tmp_path):
    cfg = settings(tmp_path)
    # One real Parquet file, one run id, two symbols in the same child run.
    write_multi_snapshot(
        cfg,
        codes=["US.MU", "US.NVDA"],
        trade_date=date(2026, 7, 1),
        run_id="run-shared",
    )

    report = run_inventory(cfg)
    by_code = {item.code: item for item in report.items}
    assert by_code["US.MU"].snapshot_count == 1
    assert by_code["US.NVDA"].snapshot_count == 1
    assert report.summary.snapshot_count == 1
    assert report.summary.snapshot_row_count == 2


def test_inventory_global_snapshot_count_overlapping_runs(tmp_path):
    cfg = settings(tmp_path)
    # run-a collects both symbols; run-b only US.MU.
    write_multi_snapshot(
        cfg,
        codes=["US.MU", "US.NVDA"],
        trade_date=date(2026, 7, 1),
        run_id="run-a",
    )
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-b")

    report = run_inventory(cfg)

    # Two distinct run ids globally -- never a sum over per-item counts (3).
    assert report.summary.snapshot_count == 2
    by_code = {item.code: item for item in report.items}
    assert by_code["US.MU"].snapshot_count == 2
    assert by_code["US.NVDA"].snapshot_count == 1


def test_inventory_normalizes_filter_parameters(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a")

    report = run_inventory(
        cfg,
        requested_session="all",
        adjustment="none",
        interval="1M",
        source_schema_version=" 10.9 ",
    )

    assert report.parameters["interval"] == "1m"
    assert report.parameters["requested_session"] == "ALL"
    assert report.parameters["adjustment"] == "NONE"
    assert report.parameters["source_schema_version"] == "10.9"
    assert len(report.items) == 1
    assert report.items[0].snapshot_row_count == 1


def test_cli_inventory_normalized_filters_match_stored_case(tmp_path, capsys):
    cfg_path = write_settings_file(tmp_path)
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a")

    exit_code = cli_module.main(
        [
            "--settings",
            str(cfg_path),
            "inventory",
            "--symbols",
            "US.MU",
            "--session",
            "all",
            "--adjustment",
            "none",
            "--interval",
            "1M",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "SUCCESS"
    assert payload["parameters"]["interval"] == "1m"
    assert payload["parameters"]["requested_session"] == "ALL"
    assert payload["parameters"]["adjustment"] == "NONE"
    assert payload["summary"]["snapshot_row_count"] == 1
