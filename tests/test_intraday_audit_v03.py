from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

import market_vault.cli as cli_module
from market_vault import MarketVault
from market_vault.audit import run_audit
from market_vault.coverage import load_market_bar_coverage_state
from market_vault.intraday_audit import parse_intraday_interval, run_intraday_audit
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import market_session_label, normalize_bars, normalize_trading_calendar
from market_vault.storage import Catalog, ParquetStore

TODAY = date(2026, 8, 2)


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


def write_calendar_snapshot(
    cfg: Settings,
    *,
    market: str,
    trade_dates: list[date],
    requested_start_date: date,
    requested_end_date: date,
) -> None:
    frame = pd.DataFrame(
        {
            "time": [item.isoformat() for item in trade_dates],
            "trade_date_type": ["WHOLE"] * len(trade_dates),
        }
    )
    curated = normalize_trading_calendar(
        frame,
        market=market,
        code=None,
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
        captured_at=pd.Timestamp("2026-08-01T01:00:00Z"),
        source="moomoo",
        source_schema_version=cfg.source_schema_version,
        run_id="cal-run",
    )
    ParquetStore(cfg).write_trading_calendar_curated(
        curated,
        "MARKET",
        market.upper(),
        requested_start_date,
        requested_end_date,
        "cal-run",
    )
    Catalog(cfg).refresh_trading_calendar_views()


def us_calendar(cfg: Settings) -> None:
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 3),
    )


def minute_keys(start: str, count: int, step_minutes: int = 1) -> list[str]:
    base = pd.Timestamp(start, tz="America/New_York")
    return [
        (base + pd.Timedelta(int(step_minutes * index), unit="m")).strftime("%Y-%m-%d %H:%M:%S")
        for index in range(count)
    ]


def write_snapshot(
    cfg: Settings,
    *,
    codes: list[str],
    trade_date: date,
    run_id: str,
    time_keys: list[str],
    interval: str = "1m",
    session: str = "ALL",
    adjustment: str = "NONE",
    schema: str = "10.9",
    run_status: str = "SUCCESS",
    quality: str = "PASS",
    record_run: bool = True,
    mutate=None,
    run_trade_date: date | None = None,
    run_finished_at: datetime | None = None,
    ingested_at: str | None = None,
) -> None:
    store = ParquetStore(cfg)
    catalog = Catalog(cfg)
    frames: list[pd.DataFrame] = []
    for code in codes:
        raw = pd.DataFrame(
            {
                "code": [code] * len(time_keys),
                "name": [code] * len(time_keys),
                "time_key": time_keys,
                "open": [100.0] * len(time_keys),
                "high": [101.0] * len(time_keys),
                "low": [99.0] * len(time_keys),
                "close": [100.5] * len(time_keys),
                "volume": [100] * len(time_keys),
            }
        )
        frames.append(
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
    curated = pd.concat(frames, ignore_index=True)
    if ingested_at is not None:
        curated["ingested_at"] = pd.Timestamp(ingested_at, tz="UTC")
    if mutate is not None:
        curated = mutate(curated)
    store.write_curated(curated, trade_date, interval, codes, session, adjustment, run_id=run_id)
    if not record_run:
        return
    run = RunManifest(
        requested_trade_date=run_trade_date or trade_date,
        requested_symbols=list(codes),
        interval=interval.lower(),
        session=session.upper(),
        adjustment=adjustment.upper(),
        run_id=run_id,
    )
    run.successful_symbols = list(codes)
    run.status = run_status
    run.finished_at = run_finished_at or datetime.now(timezone.utc)
    catalog.record_run(run)
    catalog.record_quality(run.run_id, [QualityResult("bars_complete", quality)])


def write_settings_file(tmp_path: Path) -> Path:
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


def intraday_mu(cfg: Settings, **kwargs) -> object:
    params = {
        "symbols": ["US.MU"],
        "start_date": date(2026, 7, 1),
        "end_date": date(2026, 7, 1),
        "calendar_market": "US",
        "today": TODAY,
    }
    params.update(kwargs)
    return run_intraday_audit(cfg, **params)


# --- Shared coverage --------------------------------------------------------


def test_shared_coverage_complete_set_matches_audit(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-ok",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5))

    state = load_market_bar_coverage_state(
        cfg, scope_type="MARKET", scope_value="US", symbols=["US.MU"],
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 1),
        interval="1m", requested_session="ALL", adjustment="NONE", source_schema_version="10.9",
    )
    report = run_audit(cfg, symbols=["US.MU"], start_date=date(2026, 7, 1), end_date=date(2026, 7, 1),
                       calendar_market="US", today=TODAY)

    assert state.complete_items == {("US.MU", date(2026, 7, 1))}
    assert state.expected_trade_dates == [date(2026, 7, 1)]
    assert report.symbols[0].complete_trade_date_count == 1


def test_shared_coverage_incomplete_set_matches_audit(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-bad",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5), quality="FAIL")

    state = load_market_bar_coverage_state(
        cfg, scope_type="MARKET", scope_value="US", symbols=["US.MU"],
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 1),
        interval="1m", requested_session="ALL", adjustment="NONE", source_schema_version="10.9",
    )
    report = run_audit(cfg, symbols=["US.MU"], start_date=date(2026, 7, 1), end_date=date(2026, 7, 1),
                       calendar_market="US", today=TODAY)

    assert state.incomplete_items == {("US.MU", date(2026, 7, 1))}
    assert state.incomplete_reasons[("US.MU", date(2026, 7, 1))] == ["QUALITY_FAIL"]
    assert report.symbols[0].incomplete_dates == ["2026-07-01"]


def test_shared_coverage_missing_set_matches_audit(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)

    state = load_market_bar_coverage_state(
        cfg, scope_type="MARKET", scope_value="US", symbols=["US.MU"],
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 1),
        interval="1m", requested_session="ALL", adjustment="NONE", source_schema_version="10.9",
    )
    report = run_audit(cfg, symbols=["US.MU"], start_date=date(2026, 7, 1), end_date=date(2026, 7, 1),
                       calendar_market="US", today=TODAY)

    assert state.complete_items == set()
    assert state.present_items == set()
    assert report.symbols[0].missing_dates == ["2026-07-01"]


def test_shared_coverage_calendar_gap_matches_audit(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 2),
    )
    state = load_market_bar_coverage_state(
        cfg, scope_type="MARKET", scope_value="US", symbols=["US.MU"],
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 3),
        interval="1m", requested_session="ALL", adjustment="NONE", source_schema_version="10.9",
    )
    report = run_audit(cfg, symbols=["US.MU"], start_date=date(2026, 7, 1), end_date=date(2026, 7, 3),
                       calendar_market="US", today=TODAY)

    assert state.calendar_coverage_gaps == [(date(2026, 7, 3), date(2026, 7, 3))]
    assert state.expected_trade_dates == []
    assert report.status == "FAILED"


def test_shared_coverage_empty_trading_range_matches_audit(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 3),
    )
    state = load_market_bar_coverage_state(
        cfg, scope_type="MARKET", scope_value="US", symbols=["US.MU"],
        start_date=date(2026, 7, 2), end_date=date(2026, 7, 3),
        interval="1m", requested_session="ALL", adjustment="NONE", source_schema_version="10.9",
    )
    assert state.calendar_coverage_gaps == []
    assert state.expected_trade_dates == []
    report = run_audit(cfg, symbols=["US.MU"], start_date=date(2026, 7, 2), end_date=date(2026, 7, 3),
                       calendar_market="US", today=TODAY)
    assert report.status == "PASS"
    assert report.summary.total_expected_items == 0


# --- Snapshot selection -----------------------------------------------------


def test_snapshot_selection_single_complete(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-ok",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5))
    catalog = Catalog(cfg)
    refs = catalog.latest_complete_market_bar_snapshots(
        symbols=["US.MU"], trade_dates=[date(2026, 7, 1)], interval="1m",
        requested_session="ALL", adjustment="NONE", source_schema_version="10.9",
    )
    assert refs[( "US.MU", date(2026, 7, 1))].ingestion_run_id == "run-ok"
    assert refs[("US.MU", date(2026, 7, 1))].eligible_row_count == 5


def test_snapshot_selection_newest_ingested_at(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5),
                   ingested_at="2026-07-01T12:00:00Z")
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-b",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5),
                   ingested_at="2026-07-01T13:00:00Z")
    refs = Catalog(cfg).latest_complete_market_bar_snapshots(
        symbols=["US.MU"], trade_dates=[date(2026, 7, 1)], interval="1m",
        requested_session="ALL", adjustment="NONE", source_schema_version="10.9",
    )
    assert refs[("US.MU", date(2026, 7, 1))].ingestion_run_id == "run-b"


def test_snapshot_selection_falls_back_to_run_finished_at(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5),
                   ingested_at="2026-07-01T12:00:00Z",
                   run_finished_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc))
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-b",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5),
                   ingested_at="2026-07-01T12:00:00Z",
                   run_finished_at=datetime(2026, 7, 1, 13, 0, tzinfo=timezone.utc))
    refs = Catalog(cfg).latest_complete_market_bar_snapshots(
        symbols=["US.MU"], trade_dates=[date(2026, 7, 1)], interval="1m",
        requested_session="ALL", adjustment="NONE", source_schema_version="10.9",
    )
    assert refs[("US.MU", date(2026, 7, 1))].ingestion_run_id == "run-b"


def test_snapshot_selection_tie_breaks_by_run_id(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    finished = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5),
                   ingested_at="2026-07-01T12:00:00Z", run_finished_at=finished)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-b",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5),
                   ingested_at="2026-07-01T12:00:00Z", run_finished_at=finished)
    refs = Catalog(cfg).latest_complete_market_bar_snapshots(
        symbols=["US.MU"], trade_dates=[date(2026, 7, 1)], interval="1m",
        requested_session="ALL", adjustment="NONE", source_schema_version="10.9",
    )
    assert refs[("US.MU", date(2026, 7, 1))].ingestion_run_id == "run-b"


def test_snapshot_selection_excludes_quality_fail(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-bad",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5), quality="FAIL")
    refs = Catalog(cfg).latest_complete_market_bar_snapshots(
        symbols=["US.MU"], trade_dates=[date(2026, 7, 1)], interval="1m",
        requested_session="ALL", adjustment="NONE", source_schema_version="10.9",
    )
    assert refs == {}


def test_snapshot_selection_excludes_failed_run(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-f",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5), run_status="FAILED")
    refs = Catalog(cfg).latest_complete_market_bar_snapshots(
        symbols=["US.MU"], trade_dates=[date(2026, 7, 1)], interval="1m",
        requested_session="ALL", adjustment="NONE", source_schema_version="10.9",
    )
    assert refs == {}


def test_snapshot_selection_excludes_running_run(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-r",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5), run_status="RUNNING")
    refs = Catalog(cfg).latest_complete_market_bar_snapshots(
        symbols=["US.MU"], trade_dates=[date(2026, 7, 1)], interval="1m",
        requested_session="ALL", adjustment="NONE", source_schema_version="10.9",
    )
    assert refs == {}


def test_snapshot_selection_excludes_metadata_mismatch(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-m",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5),
                   run_trade_date=date(2026, 7, 2))
    refs = Catalog(cfg).latest_complete_market_bar_snapshots(
        symbols=["US.MU"], trade_dates=[date(2026, 7, 1)], interval="1m",
        requested_session="ALL", adjustment="NONE", source_schema_version="10.9",
    )
    assert refs == {}


def test_snapshot_selection_excludes_other_session(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-rth",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5), session="RTH")
    refs = Catalog(cfg).latest_complete_market_bar_snapshots(
        symbols=["US.MU"], trade_dates=[date(2026, 7, 1)], interval="1m",
        requested_session="ALL", adjustment="NONE", source_schema_version="10.9",
    )
    assert refs == {}


def test_snapshot_selection_excludes_other_adjustment(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-qfq",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5), adjustment="QFQ")
    refs = Catalog(cfg).latest_complete_market_bar_snapshots(
        symbols=["US.MU"], trade_dates=[date(2026, 7, 1)], interval="1m",
        requested_session="ALL", adjustment="NONE", source_schema_version="10.9",
    )
    assert refs == {}


def test_snapshot_selection_excludes_other_schema(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-108",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5), schema="10.8")
    refs = Catalog(cfg).latest_complete_market_bar_snapshots(
        symbols=["US.MU"], trade_dates=[date(2026, 7, 1)], interval="1m",
        requested_session="ALL", adjustment="NONE", source_schema_version="10.9",
    )
    assert refs == {}


def test_snapshot_selection_multi_symbol_same_run(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU", "US.NVDA"], trade_date=date(2026, 7, 1), run_id="run-shared",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5))
    refs = Catalog(cfg).latest_complete_market_bar_snapshots(
        symbols=["US.MU", "US.NVDA"], trade_dates=[date(2026, 7, 1)], interval="1m",
        requested_session="ALL", adjustment="NONE", source_schema_version="10.9",
    )
    assert set(refs) == {("US.MU", date(2026, 7, 1)), ("US.NVDA", date(2026, 7, 1))}
    assert refs[("US.MU", date(2026, 7, 1))].ingestion_run_id == "run-shared"
    assert refs[("US.NVDA", date(2026, 7, 1))].ingestion_run_id == "run-shared"


def test_snapshot_selection_empty_without_complete_snapshot(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-bad",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5), quality="FAIL")
    refs = Catalog(cfg).latest_complete_market_bar_snapshots(
        symbols=["US.MU"], trade_dates=[date(2026, 7, 1)], interval="1m",
        requested_session="ALL", adjustment="NONE", source_schema_version="10.9",
    )
    assert refs == {}


# --- Snapshot reading -------------------------------------------------------


def snapshot_ref(cfg: Settings, code: str = "US.MU", trade_date: date = date(2026, 7, 1)) -> object:
    refs = Catalog(cfg).latest_complete_market_bar_snapshots(
        symbols=[code], trade_dates=[trade_date], interval="1m",
        requested_session="ALL", adjustment="NONE", source_schema_version="10.9",
    )
    return refs[(code, trade_date)]


def test_snapshot_rows_exact_run_id(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5))
    rows = Catalog(cfg).market_bar_snapshot_rows(snapshot_ref(cfg))
    assert len(rows.frame) == 5
    assert set(rows.frame["ingestion_run_id"]) == {"run-a"}


def test_snapshot_rows_keep_duplicate_timestamps(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(
        cfg,
        codes=["US.MU"],
        trade_date=date(2026, 7, 1),
        run_id="run-a",
        time_keys=minute_keys("2026-07-01 09:30:00", 5),
        mutate=lambda df: pd.concat([df, df.iloc[[0]]], ignore_index=True),
    )
    rows = Catalog(cfg).market_bar_snapshot_rows(snapshot_ref(cfg))
    assert len(rows.frame) == 6


def test_snapshot_rows_do_not_mix_old_snapshot(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5))
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-b",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5))
    rows = Catalog(cfg).market_bar_snapshot_rows(snapshot_ref(cfg))
    assert set(rows.frame["ingestion_run_id"]) == {"run-b"}


def test_snapshot_rows_do_not_mix_other_symbol(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU", "US.NVDA"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5))
    rows = Catalog(cfg).market_bar_snapshot_rows(snapshot_ref(cfg))
    assert set(rows.frame["code"]) == {"US.MU"}


def test_snapshot_rows_do_not_mix_other_date(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-1",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5))
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 2), run_id="run-2",
                   time_keys=minute_keys("2026-07-02 09:30:00", 5))
    rows = Catalog(cfg).market_bar_snapshot_rows(snapshot_ref(cfg, trade_date=date(2026, 7, 1)))
    # DuckDB reads DATE columns back as midnight timestamps.
    assert {value.date() for value in rows.frame["requested_trade_date"]} == {date(2026, 7, 1)}


def test_snapshot_rows_do_not_mix_other_request_key(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-1m",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5), interval="1m")
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-5m",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5), interval="5m")
    rows = Catalog(cfg).market_bar_snapshot_rows(snapshot_ref(cfg))
    assert set(rows.frame["interval"]) == {"1m"}


def test_snapshot_rows_sorted_by_time_utc(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=list(reversed(minute_keys("2026-07-01 09:30:00", 5))))
    rows = Catalog(cfg).market_bar_snapshot_rows(snapshot_ref(cfg))
    times = pd.to_datetime(rows.frame["time_utc"])
    assert times.is_monotonic_increasing


# --- Interval parsing -------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "seconds"),
    [("1m", 60), ("5m", 300), ("15m", 900), ("30m", 1800), ("60m", 3600)],
)
def test_parse_intraday_interval_supported(value, seconds):
    assert parse_intraday_interval(value) == timedelta(seconds=seconds)


@pytest.mark.parametrize("value", ["1d", "day", "k_day", "", "unknown", "0m", "-5m"])
def test_parse_intraday_interval_rejects(value):
    with pytest.raises(ValueError):
        parse_intraday_interval(value)


def test_parse_intraday_interval_normalizes_case_and_whitespace():
    assert parse_intraday_interval(" 1M ") == timedelta(seconds=60)


# --- Session label helper ---------------------------------------------------


@pytest.mark.parametrize(
    ("market_time", "expected"),
    [
        ("2026-07-01 03:59:00", "OVERNIGHT"),
        ("2026-07-01 04:00:00", "PRE_MARKET"),
        ("2026-07-01 09:29:00", "PRE_MARKET"),
        ("2026-07-01 09:30:00", "REGULAR"),
        ("2026-07-01 15:59:00", "REGULAR"),
        ("2026-07-01 16:00:00", "AFTER_HOURS"),
        ("2026-07-01 19:59:00", "AFTER_HOURS"),
        ("2026-07-01 20:00:00", "OVERNIGHT"),
    ],
)
def test_market_session_label_boundaries(market_time, expected):
    ts = pd.Timestamp(market_time, tz="America/New_York")
    assert market_session_label(ts) == expected


def test_normalize_bars_uses_shared_session_label(tmp_path):
    cfg = settings(tmp_path)
    raw = pd.DataFrame(
        {
            "code": ["US.MU"],
            "name": ["US.MU"],
            "time_key": ["2026-07-01 09:30:00"],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [100],
        }
    )
    curated = normalize_bars(
        raw,
        requested_trade_date=date(2026, 7, 1),
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source="moomoo",
        source_schema_version="10.9",
        run_id="run-a",
    )
    assert curated["session"].iloc[0] == "REGULAR"
    assert market_session_label(pd.Timestamp("2026-07-01 09:30:00", tz="America/New_York")) == "REGULAR"


# --- Structural checks ------------------------------------------------------


def test_structure_legal_snapshot_passes(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-ok",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5))
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    assert item.source_state == "COMPLETE"
    assert item.audit_status == "PASS"
    assert all(check.status == "PASS" for check in item.checks)
    assert report.status == "PASS"


def test_structure_missing_required_columns_fails(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5),
                   mutate=lambda df: df.drop(columns=["time_utc"]))
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    assert item.audit_status == "FAILED"
    required = next(check for check in item.checks if check.name == "REQUIRED_COLUMNS")
    assert required.status == "FAIL"
    assert "time_utc" in required.details
    not_evaluated = [check for check in item.checks if check.status == "INFO"]
    assert any(check.details == "NOT_EVALUATED" for check in not_evaluated)


def test_structure_empty_snapshot_fails(tmp_path):
    from market_vault.intraday_audit import _audit_snapshot_structure
    from market_vault.storage.catalog import CompleteSnapshotRef

    # An empty snapshot has no rows at all, so the trading-day coverage layer
    # classifies the key as MISSING and never reaches the structural audit
    # through the selection path. Drive the structure function directly to
    # prove an empty snapshot is reported as a NON_EMPTY failure.
    cfg = settings(tmp_path)
    curated = normalize_bars(
        pd.DataFrame(
            {
                "code": ["US.MU"],
                "name": ["US.MU"],
                "time_key": ["2026-07-01 09:30:00"],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [100],
            }
        ),
        requested_trade_date=date(2026, 7, 1),
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source="moomoo",
        source_schema_version="10.9",
        run_id="run-a",
    ).iloc[0:0]
    ref = CompleteSnapshotRef(
        code="US.MU",
        requested_trade_date=date(2026, 7, 1),
        ingestion_run_id="run-a",
        snapshot_file="curated/source=moomoo/dataset=market_bars/interval=1m/requested_trade_date=2026-07-01/batch-x-run-a.parquet",
        snapshot_ingested_at=None,
        run_finished_at=None,
        eligible_row_count=0,
    )
    structure = _audit_snapshot_structure(
        curated,
        ref,
        physical_columns=set(curated.columns),
        interval_value="1m",
        interval_seconds=60,
        requested_session="ALL",
        adjustment="NONE",
        schema="10.9",
    )
    check = next(c for c in structure["checks"] if c.name == "NON_EMPTY")
    assert check.status == "FAIL"
    assert any(c.details == "NOT_EVALUATED" for c in structure["checks"])


def test_structure_request_metadata_mismatch_fails(tmp_path):
    from market_vault.intraday_audit import _audit_snapshot_structure
    from market_vault.storage.catalog import CompleteSnapshotRef

    # The snapshot reader filters on the exact request key, so a mismatched
    # row never reaches the structural audit through the selection path. This
    # unit test drives the structure function directly to prove the metadata
    # check itself flags every differing row.
    cfg = settings(tmp_path)
    raw = pd.DataFrame(
        {
            "code": ["US.MU"] * 5,
            "name": ["US.MU"] * 5,
            "time_key": minute_keys("2026-07-01 09:30:00", 5),
            "open": [100.0] * 5,
            "high": [101.0] * 5,
            "low": [99.0] * 5,
            "close": [100.5] * 5,
            "volume": [100] * 5,
        }
    )
    curated = normalize_bars(
        raw,
        requested_trade_date=date(2026, 7, 1),
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source="moomoo",
        source_schema_version="10.9",
        run_id="run-a",
    ).assign(requested_session="RTH")
    ref = CompleteSnapshotRef(
        code="US.MU",
        requested_trade_date=date(2026, 7, 1),
        ingestion_run_id="run-a",
        snapshot_file="curated/source=moomoo/dataset=market_bars/interval=1m/requested_trade_date=2026-07-01/batch-x-run-a.parquet",
        snapshot_ingested_at=None,
        run_finished_at=None,
        eligible_row_count=5,
    )
    structure = _audit_snapshot_structure(
        curated,
        ref,
        physical_columns=set(curated.columns),
        interval_value="1m",
        interval_seconds=60,
        requested_session="ALL",
        adjustment="NONE",
        schema="10.9",
    )
    check = next(c for c in structure["checks"] if c.name == "EXACT_REQUEST_METADATA")
    assert check.status == "FAIL"
    assert check.mismatch_count == 5
    assert check.field_mismatch_counts["requested_session"] == 5


def test_structure_invalid_time_utc_fails(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5),
                   mutate=lambda df: df.assign(time_utc=[pd.NaT] * len(df)))
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    check = next(c for c in item.checks if c.name == "VALID_TIMESTAMPS")
    assert check.status == "FAIL"
    assert item.audit_status == "FAILED"


def test_structure_invalid_time_market_fails(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5),
                   mutate=lambda df: df.assign(time_market=[None] * len(df)))
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    check = next(c for c in item.checks if c.name == "VALID_TIMESTAMPS")
    assert check.status == "FAIL"


def test_structure_timezone_instant_mismatch_fails(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5),
                   mutate=lambda df: df.assign(time_utc=pd.to_datetime(df["time_utc"]) + pd.Timedelta(1, unit="h")))
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    check = next(c for c in item.checks if c.name == "TIMEZONE_INSTANT_CONSISTENCY")
    assert check.status == "FAIL"
    assert item.audit_status == "FAILED"


def test_structure_market_calendar_date_mismatch_fails(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5),
                   mutate=lambda df: df.assign(market_calendar_date=date(2026, 7, 2)))
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    check = next(c for c in item.checks if c.name == "MARKET_CALENDAR_DATE_CONSISTENCY")
    assert check.status == "FAIL"


def test_structure_session_label_mismatch_fails(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5),
                   mutate=lambda df: df.assign(session="AFTER_HOURS"))
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    check = next(c for c in item.checks if c.name == "SESSION_LABEL_CONSISTENCY")
    assert check.status == "FAIL"


def test_structure_unknown_session_fails(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5),
                   mutate=lambda df: df.assign(session="UNKNOWN"))
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    check = next(c for c in item.checks if c.name == "SESSION_LABEL_CONSISTENCY")
    assert check.status == "FAIL"


def test_structure_rth_rejects_pre_market_rows(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5), session="RTH",
                   mutate=lambda df: df.assign(session="PRE_MARKET"))
    report = intraday_mu(cfg, requested_session="RTH")
    item = report.symbols[0].items[0]
    check = next(c for c in item.checks if c.name == "REQUESTED_SESSION_SCOPE")
    assert check.status == "FAIL"


def test_structure_all_accepts_four_sessions(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(
        cfg,
        codes=["US.MU"],
        trade_date=date(2026, 7, 1),
        run_id="run-a",
        time_keys=[
            "2026-07-01 21:00:00",
            "2026-07-02 05:00:00",
            "2026-07-02 09:30:00",
            "2026-07-02 17:00:00",
        ],
    )
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    check = next(c for c in item.checks if c.name == "REQUESTED_SESSION_SCOPE")
    assert check.status == "PASS"


def test_structure_unknown_requested_session_informs(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5), session="XX")
    report = intraday_mu(cfg, requested_session="XX")
    item = report.symbols[0].items[0]
    check = next(c for c in item.checks if c.name == "REQUESTED_SESSION_SCOPE")
    assert check.status == "INFO"
    assert check.details == "SESSION_SCOPE_NOT_EVALUATED"


def test_structure_duplicate_timestamps_fail(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5),
                   mutate=lambda df: pd.concat([df, df.iloc[[0]]], ignore_index=True))
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    check = next(c for c in item.checks if c.name == "DUPLICATE_TIMESTAMPS")
    assert check.status == "FAIL"
    assert report.summary.duplicate_timestamp_count == 2


def test_structure_non_zero_seconds_fail(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(
        cfg,
        codes=["US.MU"],
        trade_date=date(2026, 7, 1),
        run_id="run-a",
        time_keys=minute_keys("2026-07-01 09:30:00", 5),
        mutate=lambda df: df.assign(
            time_utc=pd.to_datetime(df["time_utc"]) + pd.Timedelta(30, unit="s"),
            time_market=pd.to_datetime(df["time_market"]) + pd.Timedelta(30, unit="s"),
        ),
    )
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    check = next(c for c in item.checks if c.name == "MINUTE_BOUNDARY_ALIGNMENT")
    assert check.status == "FAIL"


def test_structure_non_zero_microseconds_fail(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(
        cfg,
        codes=["US.MU"],
        trade_date=date(2026, 7, 1),
        run_id="run-a",
        time_keys=minute_keys("2026-07-01 09:30:00", 5),
        mutate=lambda df: df.assign(
            time_utc=pd.to_datetime(df["time_utc"]) + pd.Timedelta(500, unit="ms"),
            time_market=pd.to_datetime(df["time_market"]) + pd.Timedelta(500, unit="ms"),
        ),
    )
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    check = next(c for c in item.checks if c.name == "MINUTE_BOUNDARY_ALIGNMENT")
    assert check.status == "FAIL"


def _shift_row_30s(df: pd.DataFrame) -> pd.DataFrame:
    """Shift only the second row by 30s so adjacent deltas stop being an
    integer multiple of the 1m interval while all other checks stay valid."""
    time_utc = pd.to_datetime(df["time_utc"]).copy()
    time_market = pd.to_datetime(df["time_market"]).copy()
    time_utc.iloc[1] = time_utc.iloc[1] + pd.Timedelta(30, unit="s")
    time_market.iloc[1] = time_market.iloc[1] + pd.Timedelta(30, unit="s")
    return df.assign(time_utc=time_utc, time_market=time_market)


def test_structure_non_grid_delta_fails(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(
        cfg,
        codes=["US.MU"],
        trade_date=date(2026, 7, 1),
        run_id="run-a",
        time_keys=minute_keys("2026-07-01 09:30:00", 3),
        mutate=_shift_row_30s,
    )
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    check = next(c for c in item.checks if c.name == "DELTA_GRID_ALIGNMENT")
    assert check.status == "FAIL"


# --- Segments and gaps ------------------------------------------------------


def test_gap_continuous_one_minute_no_gap(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5))
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    assert item.internal_gaps == []
    check = next(c for c in item.checks if c.name == "INTERNAL_GAPS")
    assert check.status == "PASS"
    assert len(item.segments) == 1


def test_gap_two_minutes_estimates_one_missing_bar(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=["2026-07-01 09:30:00", "2026-07-01 09:32:00"])
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    assert len(item.internal_gaps) == 1
    gap = item.internal_gaps[0]
    assert gap.delta_seconds == 120
    assert gap.estimated_missing_bars == 1
    check = next(c for c in item.checks if c.name == "INTERNAL_GAPS")
    assert check.status == "WARN"
    assert report.summary.estimated_missing_bar_count == 1


def test_gap_five_minutes_estimates_four_missing_bars(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=["2026-07-01 09:30:00", "2026-07-01 09:35:00"])
    report = intraday_mu(cfg)
    assert report.symbols[0].items[0].internal_gaps[0].estimated_missing_bars == 4


def test_gap_is_warn_not_fail(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=["2026-07-01 09:30:00", "2026-07-01 09:32:00"])
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    assert item.audit_status == "WARN"
    assert report.status == "WARN"


def test_gap_session_switch_not_reported(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(
        cfg,
        codes=["US.MU"],
        trade_date=date(2026, 7, 1),
        run_id="run-a",
        time_keys=[
            "2026-07-01 09:28:00",
            "2026-07-01 09:29:00",
            "2026-07-01 09:30:00",
            "2026-07-01 09:31:00",
        ],
    )
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    assert item.internal_gaps == []
    assert len(item.segments) == 2


def test_gap_two_overnight_segments_not_compared(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(
        cfg,
        codes=["US.MU"],
        trade_date=date(2026, 7, 1),
        run_id="run-a",
        time_keys=[
            "2026-07-01 20:00:00",
            "2026-07-01 20:01:00",
            "2026-07-02 04:00:00",
            "2026-07-02 20:00:00",
            "2026-07-02 20:01:00",
        ],
    )
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    assert [segment.session for segment in item.segments] == [
        "OVERNIGHT",
        "PRE_MARKET",
        "OVERNIGHT",
    ]
    # Segments 1 and 3 are separate OVERNIGHT observations; the 23h jump
    # between them is not a gap.
    assert item.internal_gaps == []


def test_gap_multi_segment_statistics(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(
        cfg,
        codes=["US.MU"],
        trade_date=date(2026, 7, 1),
        run_id="run-a",
        time_keys=[
            "2026-07-01 20:00:00",
            "2026-07-01 20:02:00",
            "2026-07-02 04:00:00",
            "2026-07-02 09:30:00",
            "2026-07-02 09:32:00",
        ],
    )
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    assert len(item.segments) == 3
    assert len(item.internal_gaps) == 2
    assert report.summary.internal_gap_count == 2
    assert report.summary.estimated_missing_bar_count == 2


def test_gap_details_sorted_ascending(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(
        cfg,
        codes=["US.MU"],
        trade_date=date(2026, 7, 1),
        run_id="run-a",
        time_keys=[
            "2026-07-01 09:30:00",
            "2026-07-01 09:32:00",
            "2026-07-01 09:34:00",
            "2026-07-01 09:36:00",
        ],
    )
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    previous = [gap.previous_time_market for gap in item.internal_gaps]
    assert previous == sorted(previous)


def test_gap_details_truncated_by_max_gap_details(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(
        cfg,
        codes=["US.MU"],
        trade_date=date(2026, 7, 1),
        run_id="run-a",
        time_keys=[
            "2026-07-01 09:30:00",
            "2026-07-01 09:32:00",
            "2026-07-01 09:34:00",
            "2026-07-01 09:36:00",
            "2026-07-01 09:38:00",
            "2026-07-01 09:40:00",
        ],
    )
    report = intraday_mu(cfg, max_gap_details=2)
    item = report.symbols[0].items[0]
    assert len(item.internal_gaps) == 2
    assert item.gap_details_truncated is True
    assert report.summary.internal_gap_count == 5


def test_gap_details_zero_hides_details_keeps_totals(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=["2026-07-01 09:30:00", "2026-07-01 09:32:00"])
    report = intraday_mu(cfg, max_gap_details=0)
    item = report.symbols[0].items[0]
    assert item.internal_gaps == []
    assert item.gap_details_truncated is True
    assert report.summary.internal_gap_count == 1
    assert report.summary.estimated_missing_bar_count == 1


def test_gap_non_grid_delta_no_fake_estimate(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(
        cfg,
        codes=["US.MU"],
        trade_date=date(2026, 7, 1),
        run_id="run-a",
        time_keys=minute_keys("2026-07-01 09:30:00", 2),
        mutate=_shift_row_30s,
    )
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    grid = next(c for c in item.checks if c.name == "DELTA_GRID_ALIGNMENT")
    assert grid.status == "FAIL"
    assert item.internal_gaps == []
    assert report.summary.estimated_missing_bar_count == 0


def test_gap_no_check_before_first_bar(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    # Only REGULAR bars from 09:30: no leading-session coverage checks.
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5))
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    assert item.audit_status == "PASS"
    assert item.boundary_coverage.evaluated is False


def test_gap_no_check_after_last_bar(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 15:50:00", 5))
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    assert item.audit_status == "PASS"
    assert item.boundary_coverage.evaluated is False


def test_gap_no_check_for_missing_session(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    # Only REGULAR rows exist; the absent OVERNIGHT session is not a gap.
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5))
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    assert item.audit_status == "PASS"
    assert "OVERNIGHT" not in [gap.session for gap in item.internal_gaps]


# --- Coverage and overall status -------------------------------------------


def test_overall_missing_item_not_audited(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    assert item.source_state == "MISSING"
    assert item.audit_status == "NOT_AUDITED"
    assert report.summary.missing_source_item_count == 1
    assert report.summary.audited_item_count == 0
    assert report.status == "WARN"


def test_overall_incomplete_item_with_reasons(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-bad",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5), quality="FAIL")
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    assert item.source_state == "INCOMPLETE"
    assert item.audit_status == "NOT_AUDITED"
    assert item.incomplete_reasons == ["QUALITY_FAIL"]
    assert report.summary.incomplete_source_item_count == 1
    assert report.status == "WARN"


def test_overall_complete_item_audited(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-ok",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5))
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    assert item.source_state == "COMPLETE"
    assert item.audit_status == "PASS"
    assert report.summary.audited_item_count == 1
    assert report.status == "PASS"


def test_overall_all_pass_is_pass(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    for day in [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)]:
        write_snapshot(cfg, codes=["US.MU"], trade_date=day, run_id=f"run-{day.isoformat()}",
                       time_keys=minute_keys(f"{day.isoformat()} 09:30:00", 5))
    report = intraday_mu(cfg, end_date=date(2026, 7, 3))
    assert report.status == "PASS"
    assert report.summary.total_expected_items == 3
    assert report.summary.audited_item_count == 3
    assert report.summary.pass_item_count == 3
    assert report.summary.coverage_percentage == 100.0


def test_overall_internal_gap_is_warn(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=["2026-07-01 09:30:00", "2026-07-01 09:32:00"])
    report = intraday_mu(cfg)
    assert report.status == "WARN"
    assert report.summary.warn_item_count == 1


def test_overall_missing_is_warn(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5))
    report = intraday_mu(cfg, end_date=date(2026, 7, 2))
    assert report.status == "WARN"
    assert report.summary.missing_source_item_count == 1


def test_overall_incomplete_is_warn(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-bad",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5), quality="FAIL")
    report = intraday_mu(cfg)
    assert report.status == "WARN"
    assert report.summary.incomplete_source_item_count == 1


def test_overall_structural_fail_is_failed(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5),
                   mutate=lambda df: df.drop(columns=["time_utc"]))
    report = intraday_mu(cfg)
    assert report.status == "FAILED"
    assert report.summary.fail_item_count == 1


def test_overall_calendar_gap_failed_and_no_bar_audit(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 2),
    )
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5))
    report = intraday_mu(cfg, end_date=date(2026, 7, 3))
    assert report.status == "FAILED"
    assert report.calendar.coverage_complete is False
    assert report.calendar.coverage_gaps == [{"start_date": "2026-07-03", "end_date": "2026-07-03"}]
    assert report.summary is None
    assert report.as_dict()["summary"] is None
    assert report.symbols == []


def test_overall_zero_expected_dates_pass(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 3),
    )
    report = intraday_mu(cfg, start_date=date(2026, 7, 2), end_date=date(2026, 7, 3))
    assert report.status == "PASS"
    assert report.summary.total_expected_items == 0
    assert report.summary.audited_item_count == 0
    assert report.summary.coverage_percentage == 100.0


def test_overall_selection_failure_is_failed(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-ok",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5))
    monkeypatch.setattr(
        Catalog,
        "latest_complete_market_bar_snapshots",
        lambda *args, **kwargs: {},
    )
    report = intraday_mu(cfg)
    assert report.status == "FAILED"
    item = report.symbols[0].items[0]
    assert item.source_state == "COMPLETE"
    assert item.audit_status == "FAILED"
    assert item.selection_failure_reason == "COMPLETE_SNAPSHOT_SELECTION_FAILED"
    assert report.summary.fail_item_count == 1


# --- CLI, API, and reports --------------------------------------------------


def test_cli_intraday_audit_parses():
    args = cli_module.build_parser().parse_args(
        [
            "intraday-audit",
            "--calendar-market",
            "US",
            "--start-date",
            "2026-07-30",
            "--end-date",
            "2026-07-31",
            "--symbols",
            "US.MU",
            "--include-pass-checks",
            "--max-gap-details",
            "50",
            "--fail-on-warn",
        ]
    )
    assert args.command == "intraday-audit"
    assert args.include_pass_checks is True
    assert args.max_gap_details == 50
    assert args.fail_on_warn is True


def test_cli_intraday_audit_rejects_market_and_code():
    with pytest.raises(SystemExit):
        cli_module.build_parser().parse_args(
            [
                "intraday-audit",
                "--calendar-market",
                "US",
                "--calendar-code",
                "US.MU",
                "--start-date",
                "2026-07-01",
                "--end-date",
                "2026-07-31",
                "--symbols",
                "US.MU",
            ]
        )


def test_cli_intraday_audit_rejects_no_symbols(tmp_path):
    cfg_path = write_settings_file(tmp_path)
    with pytest.raises(SystemExit):
        cli_module.main(
            [
                "--settings",
                str(cfg_path),
                "intraday-audit",
                "--calendar-market",
                "US",
                "--start-date",
                "2026-07-01",
                "--end-date",
                "2026-07-31",
            ]
        )


def test_cli_intraday_audit_invalid_range_structured_error(tmp_path, capsys):
    cfg_path = write_settings_file(tmp_path)
    exit_code = cli_module.main(
        [
            "--settings",
            str(cfg_path),
            "intraday-audit",
            "--calendar-market",
            "US",
            "--start-date",
            "2026-07-02",
            "--end-date",
            "2026-07-01",
            "--symbols",
            "US.MU",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["status"] == "FAILED"
    assert payload["error"] == "start_date must be on or before end_date"
    assert "Traceback" not in capsys.readouterr().err


def test_cli_intraday_audit_future_date_structured_error(tmp_path, capsys):
    cfg_path = write_settings_file(tmp_path)
    future = datetime.now(timezone.utc).date() + timedelta(days=1)
    exit_code = cli_module.main(
        [
            "--settings",
            str(cfg_path),
            "intraday-audit",
            "--calendar-market",
            "US",
            "--start-date",
            "2026-07-01",
            "--end-date",
            future.isoformat(),
            "--symbols",
            "US.MU",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["status"] == "FAILED"
    assert "before today's UTC date" in payload["error"]


def test_cli_intraday_audit_unsupported_interval_structured_error(tmp_path, capsys):
    cfg_path = write_settings_file(tmp_path)
    exit_code = cli_module.main(
        [
            "--settings",
            str(cfg_path),
            "intraday-audit",
            "--calendar-market",
            "US",
            "--start-date",
            "2026-07-01",
            "--end-date",
            "2026-07-01",
            "--symbols",
            "US.MU",
            "--interval",
            "1d",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["status"] == "FAILED"
    assert "Unsupported intraday interval" in payload["error"]


def test_api_intraday_audit_rejects_negative_max_gap_details(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    with pytest.raises(ValueError, match="max_gap_details"):
        run_intraday_audit(
            cfg,
            symbols=["US.MU"],
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 1),
            calendar_market="US",
            max_gap_details=-1,
            today=TODAY,
        )


def test_cli_intraday_audit_warn_exits_zero(tmp_path):
    cfg_path = write_settings_file(tmp_path)
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=["2026-07-01 09:30:00", "2026-07-01 09:32:00"])
    exit_code = cli_module.main(
        [
            "--settings",
            str(cfg_path),
            "intraday-audit",
            "--calendar-market",
            "US",
            "--start-date",
            "2026-07-01",
            "--end-date",
            "2026-07-01",
            "--symbols",
            "US.MU",
        ]
    )
    assert exit_code == 0


def test_cli_intraday_audit_fail_on_warn_exits_two(tmp_path):
    cfg_path = write_settings_file(tmp_path)
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=["2026-07-01 09:30:00", "2026-07-01 09:32:00"])
    exit_code = cli_module.main(
        [
            "--settings",
            str(cfg_path),
            "intraday-audit",
            "--calendar-market",
            "US",
            "--start-date",
            "2026-07-01",
            "--end-date",
            "2026-07-01",
            "--symbols",
            "US.MU",
            "--fail-on-warn",
        ]
    )
    assert exit_code == 2


def test_cli_intraday_audit_failed_exits_one(tmp_path, capsys):
    cfg_path = write_settings_file(tmp_path)
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5),
                   mutate=lambda df: df.drop(columns=["time_utc"]))
    exit_code = cli_module.main(
        [
            "--settings",
            str(cfg_path),
            "intraday-audit",
            "--calendar-market",
            "US",
            "--start-date",
            "2026-07-01",
            "--end-date",
            "2026-07-01",
            "--symbols",
            "US.MU",
        ]
    )
    assert exit_code == 1
    assert "Traceback" not in capsys.readouterr().err


def test_api_intraday_audit_raises_value_error(tmp_path):
    cfg = settings(tmp_path)
    with pytest.raises(ValueError, match="on or before"):
        MarketVault(cfg).audit_intraday_market_bars(
            symbols=["US.MU"],
            start_date=date(2026, 7, 2),
            end_date=date(2026, 7, 1),
            calendar_market="US",
            today=TODAY,
        )


def test_api_intraday_audit_pure_local(monkeypatch, tmp_path):
    class Raiser:
        def __init__(self, settings):
            raise AssertionError("OpenD collector must not be constructed")

    monkeypatch.setattr("market_vault.collectors.MoomooCalendarCollector", Raiser)
    monkeypatch.setattr("market_vault.collectors.MoomooHistoryCollector", Raiser)
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-ok",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5))
    report = MarketVault(cfg).audit_intraday_market_bars(
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        calendar_market="US",
        today=TODAY,
    )
    assert report.status == "PASS"


def test_cli_intraday_audit_pure_local(monkeypatch, tmp_path, capsys):
    class Raiser:
        def __init__(self, settings):
            raise AssertionError("OpenD collector must not be constructed")

    monkeypatch.setattr("market_vault.collectors.MoomooCalendarCollector", Raiser)
    monkeypatch.setattr("market_vault.collectors.MoomooHistoryCollector", Raiser)
    cfg_path = write_settings_file(tmp_path)
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-ok",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5))
    exit_code = cli_module.main(
        [
            "--settings",
            str(cfg_path),
            "intraday-audit",
            "--calendar-market",
            "US",
            "--start-date",
            "2026-07-01",
            "--end-date",
            "2026-07-01",
            "--symbols",
            "US.MU",
        ]
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "PASS"


def test_report_json_atomic_no_temp_files(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-ok",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5))
    report = intraday_mu(cfg)
    assert report.report_file is not None
    path = Path(report.report_file)
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["report_type"] == "MARKET_BARS_INTRADAY_INTEGRITY_AUDIT"
    assert payload["run_id"] == report.run_id
    leftovers = [p for p in cfg.report_dir.rglob("*.tmp")] if cfg.report_dir.exists() else []
    assert leftovers == []


def test_include_pass_checks_only_changes_details(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-ok",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5))
    default = intraday_mu(cfg, include_pass_checks=False)
    verbose = intraday_mu(cfg, include_pass_checks=True)

    assert default.summary.as_dict() == verbose.summary.as_dict()
    default_checks = default.symbols[0].items[0].as_dict(include_pass_checks=False)["checks"]
    verbose_checks = verbose.symbols[0].items[0].as_dict(include_pass_checks=True)["checks"]
    assert len(verbose_checks) > len(default_checks)
    assert all(check["status"] != "PASS" for check in default_checks)


# --- Physical snapshot isolation -------------------------------------------


def test_snapshot_same_run_two_files_not_merged(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    # Two physical files with the same run id and the same (code, date):
    # file-a only has US.MU, file-b has US.MU and US.NVDA.
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-x",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5),
                   ingested_at="2026-07-01T12:00:00Z")
    write_snapshot(cfg, codes=["US.MU", "US.NVDA"], trade_date=date(2026, 7, 1), run_id="run-x",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5),
                   ingested_at="2026-07-01T13:00:00Z")

    refs = Catalog(cfg).latest_complete_market_bar_snapshots(
        symbols=["US.MU"], trade_dates=[date(2026, 7, 1)], interval="1m",
        requested_session="ALL", adjustment="NONE", source_schema_version="10.9",
    )
    ref = refs[("US.MU", date(2026, 7, 1))]
    # Row counts are per physical file, never merged across the two files.
    assert ref.eligible_row_count == 5
    # The newest physical file (13:00 ingested_at) is selected; the file path
    # identifies exactly one of the two files.
    assert ref.snapshot_ingested_at is not None
    # DuckDB surfaces timestamps in the session timezone; compare in UTC.
    assert "T13:00" in ref.snapshot_ingested_at.astimezone(timezone.utc).isoformat()
    assert ref.snapshot_file.startswith("curated/source=moomoo/dataset=market_bars/")
    assert ref.snapshot_file.endswith(".parquet")
    rows = Catalog(cfg).market_bar_snapshot_rows(ref)
    assert len(rows.frame) == 5
    assert set(rows.frame["code"]) == {"US.MU"}


@pytest.mark.parametrize("dropped", ["open", "volume"])
def test_physical_schema_missing_column_not_masked_by_other_file(tmp_path, dropped):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    # The newest complete snapshot lacks one required column; an older file
    # still provides it, but the selected physical schema must not be masked.
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5),
                   ingested_at="2026-07-01T13:00:00Z",
                   mutate=lambda df: df.drop(columns=[dropped]))
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-b",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5),
                   ingested_at="2026-07-01T12:00:00Z")

    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    assert item.selected_snapshot.ingestion_run_id == "run-a"
    check = next(c for c in item.checks if c.name == "REQUIRED_COLUMNS")
    assert check.status == "FAIL"
    assert dropped in check.details
    assert "Missing columns" in check.details
    assert item.audit_status == "FAILED"


def test_physical_schema_missing_ingested_at_not_masked(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    # Both files lack ingested_at (legacy-style), so the tie breaks on
    # run_finished_at: run-a is newer and must be selected, and the audit
    # still reports the genuinely missing ingested_at column.
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5),
                   mutate=lambda df: df.drop(columns=["ingested_at"]),
                   run_finished_at=datetime(2026, 7, 1, 13, 0, tzinfo=timezone.utc))
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-b",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5),
                   mutate=lambda df: df.drop(columns=["ingested_at"]),
                   run_finished_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc))

    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    assert item.selected_snapshot.ingestion_run_id == "run-a"
    check = next(c for c in item.checks if c.name == "REQUIRED_COLUMNS")
    assert check.status == "FAIL"
    assert "ingested_at" in check.details
    assert item.audit_status == "FAILED"


def test_public_market_bars_unavailable_still_audits_physical_file(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    # A snapshot missing time_utc breaks the public dedup view but the
    # structural audit must still read the physical file and report the
    # actually missing column instead of an empty frame.
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5),
                   mutate=lambda df: df.drop(columns=["time_utc"]))

    assert Catalog(cfg).refresh_market_bars_view() is False
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    check = next(c for c in item.checks if c.name == "REQUIRED_COLUMNS")
    assert check.status == "FAIL"
    assert "time_utc" in check.details
    # Only the genuinely missing column is reported, not the whole schema.
    assert "Missing columns: ['time_utc']" == check.details


def test_selected_snapshot_reports_relative_file(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-ok",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5))
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    snapshot_file = item.selected_snapshot.snapshot_file
    assert not Path(snapshot_file).is_absolute()
    assert snapshot_file.startswith("curated/source=moomoo/dataset=market_bars/")
    assert snapshot_file.endswith(".parquet")


# --- Market-time segment/gap output -----------------------------------------


def test_segment_times_use_market_time_with_offset(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-ok",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5))
    report = intraday_mu(cfg)
    segment = report.symbols[0].items[0].segments[0]
    assert segment.first_time_market == "2026-07-01T09:30:00-04:00"
    assert segment.last_time_market == "2026-07-01T09:34:00-04:00"


def test_gap_times_use_market_time_with_offset(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-ok",
                   time_keys=["2026-07-01 09:30:00", "2026-07-01 09:32:00"])
    report = intraday_mu(cfg)
    gap = report.symbols[0].items[0].internal_gaps[0]
    assert gap.previous_time_market == "2026-07-01T09:30:00-04:00"
    assert gap.next_time_market == "2026-07-01T09:32:00-04:00"
    # delta stays a UTC-instant difference.
    assert gap.delta_seconds == 120


def test_segment_times_winter_offset_minus_five(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-ok",
                   time_keys=["2026-01-15 09:30:00"])
    report = intraday_mu(cfg)
    segment = report.symbols[0].items[0].segments[0]
    assert segment.first_time_market == "2026-01-15T09:30:00-05:00"


# --- Session occurrence segmentation ----------------------------------------


def test_segment_same_overnight_occurrence_connected(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    # 20:00 D through 03:59 D+1 belong to the same OVERNIGHT occurrence.
    write_snapshot(
        cfg,
        codes=["US.MU"],
        trade_date=date(2026, 7, 1),
        run_id="run-ok",
        time_keys=[
            "2026-07-01 20:00:00",
            "2026-07-01 20:01:00",
            "2026-07-02 03:58:00",
            "2026-07-02 03:59:00",
        ],
    )
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    assert len(item.segments) == 1
    assert item.segments[0].session == "OVERNIGHT"
    assert item.segments[0].row_count == 4


def test_segment_different_overnight_occurrences_not_connected(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(
        cfg,
        codes=["US.MU"],
        trade_date=date(2026, 7, 1),
        run_id="run-ok",
        time_keys=["2026-07-01 20:00:00", "2026-07-02 20:00:00"],
    )
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    assert [segment.session for segment in item.segments] == ["OVERNIGHT", "OVERNIGHT"]
    assert item.internal_gaps == []
    assert report.summary.internal_gap_count == 0


def test_segment_cross_day_regular_not_connected(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(
        cfg,
        codes=["US.MU"],
        trade_date=date(2026, 7, 1),
        run_id="run-ok",
        time_keys=["2026-07-01 09:30:00", "2026-07-02 09:30:00"],
    )
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    assert [segment.session for segment in item.segments] == ["REGULAR", "REGULAR"]
    assert item.internal_gaps == []
    assert report.summary.internal_gap_count == 0


# --- Calendar FAILED summary ------------------------------------------------


def test_intraday_empty_calendar_summary_none(tmp_path):
    cfg = settings(tmp_path)
    report = intraday_mu(cfg)
    assert report.status == "FAILED"
    assert report.summary is None
    assert report.as_dict()["summary"] is None
    assert report.symbols == []


# --- Metadata dedup and scope row counts ------------------------------------


def test_metadata_mismatch_dedup_rows_and_field_counts(tmp_path):
    from market_vault.intraday_audit import _audit_snapshot_structure
    from market_vault.storage.catalog import CompleteSnapshotRef

    cfg = settings(tmp_path)
    raw = pd.DataFrame(
        {
            "code": ["US.MU"] * 5,
            "name": ["US.MU"] * 5,
            "time_key": minute_keys("2026-07-01 09:30:00", 5),
            "open": [100.0] * 5,
            "high": [101.0] * 5,
            "low": [99.0] * 5,
            "close": [100.5] * 5,
            "volume": [100] * 5,
        }
    )
    curated = normalize_bars(
        raw,
        requested_trade_date=date(2026, 7, 1),
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source="moomoo",
        source_schema_version="10.9",
        run_id="run-a",
    )
    curated = curated.copy()
    # One row breaks three fields at once.
    curated.loc[0, ["requested_session", "interval", "adjustment"]] = ["RTH", "5m", "QFQ"]
    # A second row breaks one field.
    curated.loc[1, "source_schema_version"] = "10.8"
    ref = CompleteSnapshotRef(
        code="US.MU",
        requested_trade_date=date(2026, 7, 1),
        ingestion_run_id="run-a",
        snapshot_file="curated/source=moomoo/dataset=market_bars/interval=1m/requested_trade_date=2026-07-01/batch-x-run-a.parquet",
        snapshot_ingested_at=None,
        run_finished_at=None,
        eligible_row_count=5,
    )
    structure = _audit_snapshot_structure(
        curated,
        ref,
        physical_columns=set(curated.columns),
        interval_value="1m",
        interval_seconds=60,
        requested_session="ALL",
        adjustment="NONE",
        schema="10.9",
    )
    check = next(c for c in structure["checks"] if c.name == "EXACT_REQUEST_METADATA")
    assert check.status == "FAIL"
    # Two distinct rows are wrong, not 4 (3 fields on one row plus 1).
    assert check.mismatch_count == 2
    assert check.field_mismatch_counts["requested_session"] == 1
    assert check.field_mismatch_counts["interval"] == 1
    assert check.field_mismatch_counts["adjustment"] == 1
    assert check.field_mismatch_counts["source_schema_version"] == 1
    assert check.field_mismatch_counts["code"] == 0
    assert check.mismatch_count <= ref.eligible_row_count


def test_session_scope_mismatch_count_rows(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(
        cfg,
        codes=["US.MU"],
        trade_date=date(2026, 7, 1),
        run_id="run-a",
        time_keys=minute_keys("2026-07-01 09:30:00", 5),
        session="RTH",
        mutate=lambda df: df.assign(session=["PRE_MARKET"] * 3 + ["REGULAR"] * 2),
    )
    report = intraday_mu(cfg, requested_session="RTH")
    check = next(c for c in report.symbols[0].items[0].checks if c.name == "REQUESTED_SESSION_SCOPE")
    assert check.status == "FAIL"
    assert check.mismatch_count == 3
    assert "PRE_MARKET: 3" in check.details


def test_session_scope_mismatch_mixed_labels_row_counts(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(
        cfg,
        codes=["US.MU"],
        trade_date=date(2026, 7, 1),
        run_id="run-a",
        time_keys=minute_keys("2026-07-01 09:30:00", 6),
        session="RTH",
        mutate=lambda df: df.assign(
            session=["PRE_MARKET"] * 2 + ["REGULAR"] * 3 + ["AFTER_HOURS"] * 1
        ),
    )
    report = intraday_mu(cfg, requested_session="RTH")
    check = next(c for c in report.symbols[0].items[0].checks if c.name == "REQUESTED_SESSION_SCOPE")
    assert check.status == "FAIL"
    assert check.mismatch_count == 3
    assert "PRE_MARKET: 2" in check.details
    assert "AFTER_HOURS: 1" in check.details


# --- Hive partitioning isolation -------------------------------------------


def test_hive_partitioning_flag_controls_path_columns(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    # The physical file drops the interval column; the path still contains an
    # interval=1m partition directory that DuckDB may turn into a virtual
    # column when hive partitioning is enabled.
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5),
                   mutate=lambda df: df.drop(columns=["interval"]))
    market_bars_root = cfg.data_root / "curated" / f"source={cfg.source}" / "dataset=market_bars"
    file = next(market_bars_root.rglob("*.parquet"))
    escaped = file.as_posix().replace("'", "''")
    with Catalog(cfg).connect() as con:
        with_hive = {
            row[0]
            for row in con.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{escaped}', hive_partitioning = true)"
            ).fetchall()
        }
        without_hive = {
            row[0]
            for row in con.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{escaped}', hive_partitioning = false)"
            ).fetchall()
        }
    assert "interval" in with_hive
    assert "interval" not in without_hive


@pytest.mark.parametrize("dropped", ["interval", "requested_trade_date"])
def test_snapshot_rows_physical_columns_exclude_path_columns(tmp_path, dropped):
    from market_vault.intraday_audit import _audit_snapshot_structure
    from market_vault.storage.catalog import CompleteSnapshotRef

    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5),
                   mutate=lambda df: df.drop(columns=[dropped]))
    market_bars_root = cfg.data_root / "curated" / f"source={cfg.source}" / "dataset=market_bars"
    file = next(market_bars_root.rglob("*.parquet"))
    ref = CompleteSnapshotRef(
        code="US.MU",
        requested_trade_date=date(2026, 7, 1),
        ingestion_run_id="run-a",
        snapshot_file=file.relative_to(cfg.data_root).as_posix(),
        snapshot_ingested_at=None,
        run_finished_at=None,
        eligible_row_count=5,
    )
    rows = Catalog(cfg).market_bar_snapshot_rows(ref)
    assert dropped not in rows.physical_columns
    structure = _audit_snapshot_structure(
        rows.frame,
        ref,
        physical_columns=rows.physical_columns,
        interval_value="1m",
        interval_seconds=60,
        requested_session="ALL",
        adjustment="NONE",
        schema="10.9",
    )
    check = next(c for c in structure["checks"] if c.name == "REQUIRED_COLUMNS")
    assert check.status == "FAIL"
    assert dropped in check.details


# --- Malformed metadata rows reach the structural check ---------------------


def test_damaged_session_row_reaches_exact_check(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    # Two matching rows and one row whose requested_session is wrong; the
    # wrong row must reach EXACT_REQUEST_METADATA instead of being filtered
    # out before the structural audit.
    write_snapshot(
        cfg,
        codes=["US.MU"],
        trade_date=date(2026, 7, 1),
        run_id="run-a",
        time_keys=minute_keys("2026-07-01 09:30:00", 3),
        mutate=lambda df: df.assign(requested_session=["ALL", "ALL", "RTH"]),
    )
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    assert item.source_state == "COMPLETE"
    assert item.audit_status == "FAILED"
    check = next(c for c in item.checks if c.name == "EXACT_REQUEST_METADATA")
    assert check.status == "FAIL"
    assert check.mismatch_count == 1
    assert check.field_mismatch_counts["requested_session"] == 1
    assert item.selected_snapshot.eligible_row_count == 2
    assert item.selected_snapshot.audited_row_count == 3


def test_damaged_run_id_row_reaches_exact_check(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(
        cfg,
        codes=["US.MU"],
        trade_date=date(2026, 7, 1),
        run_id="run-a",
        time_keys=minute_keys("2026-07-01 09:30:00", 3),
        mutate=lambda df: df.assign(ingestion_run_id=["run-a", "run-a", "run-other"]),
    )
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    check = next(c for c in item.checks if c.name == "EXACT_REQUEST_METADATA")
    assert check.status == "FAIL"
    assert check.mismatch_count == 1
    assert check.field_mismatch_counts["ingestion_run_id"] == 1


def test_damaged_row_multiple_fields_counted_once(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)

    def mutate(df):
        df = df.copy()
        df.loc[0, ["requested_trade_date", "interval", "adjustment"]] = [
            date(2026, 7, 2),
            "5m",
            "QFQ",
        ]
        return df

    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 3), mutate=mutate)
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    check = next(c for c in item.checks if c.name == "EXACT_REQUEST_METADATA")
    assert check.status == "FAIL"
    assert check.mismatch_count == 1
    assert check.field_mismatch_counts["requested_trade_date"] == 1
    assert check.field_mismatch_counts["interval"] == 1
    assert check.field_mismatch_counts["adjustment"] == 1


def test_multi_symbol_file_audited_per_symbol(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    # One physical file holds US.MU and US.NVDA; the NVDA rows carry a wrong
    # requested_session. Auditing US.MU must not read NVDA rows at all.
    write_snapshot(
        cfg,
        codes=["US.MU", "US.NVDA"],
        trade_date=date(2026, 7, 1),
        run_id="run-shared",
        time_keys=minute_keys("2026-07-01 09:30:00", 5),
        mutate=lambda df: df.assign(
            requested_session=["ALL"] * 5 + ["RTH"] * 5
        ),
    )
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    assert item.source_state == "COMPLETE"
    assert item.audit_status == "PASS"
    assert item.selected_snapshot.audited_row_count == 5
    check = next(c for c in item.checks if c.name == "EXACT_REQUEST_METADATA")
    assert check.status == "PASS"


def test_eligible_and_audited_row_count_distinct(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(
        cfg,
        codes=["US.MU"],
        trade_date=date(2026, 7, 1),
        run_id="run-a",
        time_keys=minute_keys("2026-07-01 09:30:00", 3),
        mutate=lambda df: df.assign(requested_session=["ALL", "ALL", "RTH"]),
    )
    report = intraday_mu(cfg)
    item = report.symbols[0].items[0]
    # 2 rows match the exact key in the selection SQL; 3 rows are actually
    # audited because the damaged row is preserved for the structural check.
    assert item.selected_snapshot.eligible_row_count == 2
    assert item.selected_snapshot.audited_row_count == 3
    assert report.summary.total_snapshot_rows == 3


def test_report_sorting_stable(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, codes=["US.NVDA"], trade_date=date(2026, 7, 1), run_id="run-nvda",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5))
    write_snapshot(cfg, codes=["US.MU"], trade_date=date(2026, 7, 1), run_id="run-mu",
                   time_keys=minute_keys("2026-07-01 09:30:00", 5))
    report = run_intraday_audit(
        cfg,
        symbols=["US.MU", "US.NVDA"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        calendar_market="US",
        today=TODAY,
    )
    assert [symbol.code for symbol in report.symbols] == ["US.MU", "US.NVDA"]
    dates = [item.requested_trade_date for symbol in report.symbols for item in symbol.items]
    assert dates == sorted(dates)
