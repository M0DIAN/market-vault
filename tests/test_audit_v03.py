from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

import market_vault.cli as cli_module
from market_vault import MarketVault
from market_vault.audit import run_audit
from market_vault.cli import build_parser
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars, normalize_trading_calendar
from market_vault.storage import Catalog, ParquetStore


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
    trade_date_types: list[str] | None = None,
    run_id: str = "cal-run",
) -> None:
    frame = pd.DataFrame(
        {
            "time": [item.isoformat() for item in trade_dates],
            "trade_date_type": trade_date_types or ["WHOLE"] * len(trade_dates),
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
        run_id=run_id,
    )
    ParquetStore(cfg).write_trading_calendar_curated(
        curated,
        "MARKET",
        market.upper(),
        requested_start_date,
        requested_end_date,
        run_id,
    )
    Catalog(cfg).refresh_trading_calendar_views()


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
    interval: str = "1m",
    session: str = "ALL",
    adjustment: str = "NONE",
    schema: str = "10.9",
    run_status: str = "SUCCESS",
    quality: str = "PASS",
    include_session: bool = True,
    include_schema: bool = True,
    legacy_filename: bool = False,
    record_run: bool = True,
    run_trade_date: date | None = None,
    run_interval: str | None = None,
    run_session: str | None = None,
    run_adjustment: str | None = None,
) -> None:
    store = ParquetStore(cfg)
    catalog = Catalog(cfg)
    raw = history_raw_frame(code, trade_date)
    raw["requested_trade_date"] = trade_date
    raw["interval"] = interval.lower()
    raw["adjustment"] = adjustment.upper()
    raw["requested_session"] = session.upper()
    raw["ingestion_run_id"] = run_id
    curated = normalize_bars(
        raw,
        requested_trade_date=trade_date,
        interval=interval,
        requested_session=session,
        adjustment=adjustment,
        source=cfg.source,
        source_schema_version=schema,
        run_id=run_id,
    )
    if not include_session:
        curated = curated.drop(columns=["requested_session"])
    if not include_schema:
        curated = curated.drop(columns=["source_schema_version"])
    if legacy_filename:
        batch_key = ParquetStore._batch_key([code], interval.lower(), session.upper(), adjustment.upper())
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
        store.write_curated(curated, trade_date, interval, [code], session, adjustment, run_id=run_id)
    if not record_run:
        return
    run = RunManifest(
        requested_trade_date=run_trade_date or trade_date,
        requested_symbols=[code],
        interval=(run_interval or interval).lower(),
        session=(run_session or session).upper(),
        adjustment=(run_adjustment or adjustment).upper(),
        run_id=run_id,
    )
    run.successful_symbols = [code]
    run.status = run_status
    run.finished_at = datetime.now(timezone.utc)
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


def us_calendar(cfg: Settings, end: date = date(2026, 7, 7)) -> None:
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3), date(2026, 7, 6), date(2026, 7, 7)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=end,
    )


def audit_mu(cfg: Settings, **kwargs) -> object:
    params = {
        "symbols": ["US.MU"],
        "start_date": date(2026, 7, 1),
        "end_date": date(2026, 7, 7),
        "calendar_market": "US",
        "today": date(2026, 8, 2),
    }
    params.update(kwargs)
    return run_audit(cfg, **params)


# --- Audit calendar semantics ----------------------------------------------


def test_audit_expected_dates_from_local_calendar(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    report = audit_mu(cfg)
    assert report.calendar.expected_trade_dates == [
        "2026-07-01",
        "2026-07-02",
        "2026-07-03",
        "2026-07-06",
        "2026-07-07",
    ]
    assert report.calendar.expected_trade_date_count == 5


def test_audit_weekend_not_expected(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    report = audit_mu(cfg)
    assert "2026-07-04" not in report.calendar.expected_trade_dates
    assert "2026-07-05" not in report.calendar.expected_trade_dates


def test_audit_morning_afternoon_single_expected_date(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1), date(2026, 7, 2)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 2),
        trade_date_types=["MORNING", "AFTERNOON"],
    )
    report = audit_mu(cfg, end_date=date(2026, 7, 2))
    # MORNING and AFTERNOON rows describe the same trading day: one expected date.
    assert report.calendar.expected_trade_dates == ["2026-07-01", "2026-07-02"]


def test_audit_calendar_coverage_complete_passes(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    for day in [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3), date(2026, 7, 6), date(2026, 7, 7)]:
        write_snapshot(cfg, code="US.MU", trade_date=day, run_id=f"run-{day.isoformat()}")
    report = audit_mu(cfg)
    assert report.calendar.coverage_complete is True
    assert report.calendar.coverage_gaps == []
    assert report.status == "PASS"


def test_audit_adjacent_ranges_merge(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 10),
        run_id="cal-1",
    )
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 11)],
        requested_start_date=date(2026, 7, 11),
        requested_end_date=date(2026, 7, 31),
        run_id="cal-2",
    )
    report = audit_mu(cfg, end_date=date(2026, 7, 31))
    assert report.calendar.coverage_complete is True
    assert report.calendar.coverage_gaps == []


def test_audit_middle_gap_failed(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 10),
        run_id="cal-1",
    )
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 12)],
        requested_start_date=date(2026, 7, 12),
        requested_end_date=date(2026, 7, 31),
        run_id="cal-2",
    )
    report = audit_mu(cfg, end_date=date(2026, 7, 31))
    assert report.status == "FAILED"
    assert report.calendar.coverage_complete is False
    assert report.calendar.coverage_gaps == [{"start_date": "2026-07-11", "end_date": "2026-07-11"}]
    # No summary and no classification when the calendar is incomplete.
    assert report.summary is None
    assert report.symbols == []
    assert report.calendar.expected_trade_date_count == 0
    assert report.calendar.expected_trade_dates == []


def test_audit_empty_calendar_failed(tmp_path):
    cfg = settings(tmp_path)
    report = audit_mu(cfg)
    assert report.status == "FAILED"
    assert report.calendar.coverage_complete is False
    assert report.calendar.coverage_gaps
    assert report.summary is None
    assert report.symbols == []
    assert report.calendar.expected_trade_date_count == 0
    assert report.calendar.expected_trade_dates == []


def test_audit_coverage_failure_does_not_report_fake_missing_dates(tmp_path):
    cfg = settings(tmp_path)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-1")
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 3),
        run_id="cal-1",
    )
    report = audit_mu(cfg)
    assert report.status == "FAILED"
    assert report.summary is None
    assert report.symbols == []
    assert report.calendar.expected_trade_date_count == 0
    assert report.calendar.expected_trade_dates == []


def test_audit_does_not_touch_open_d(monkeypatch, tmp_path):
    class Raiser:
        def __init__(self, settings):
            raise AssertionError("OpenD collector must not be constructed")

    monkeypatch.setattr("market_vault.collectors.MoomooCalendarCollector", Raiser)
    monkeypatch.setattr("market_vault.collectors.MoomooHistoryCollector", Raiser)
    cfg = settings(tmp_path)
    us_calendar(cfg)
    for day in [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3), date(2026, 7, 6), date(2026, 7, 7)]:
        write_snapshot(cfg, code="US.MU", trade_date=day, run_id=f"run-{day.isoformat()}")
    report = audit_mu(cfg)
    assert report.status == "PASS"


# --- Audit classification ---------------------------------------------------


def test_audit_complete_item(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-ok")
    report = audit_mu(cfg)
    symbol = report.symbols[0]
    assert symbol.complete_trade_date_count == 1
    assert symbol.incomplete_trade_date_count == 0
    assert symbol.missing_trade_date_count == 4
    assert symbol.first_complete_date == "2026-07-01"
    assert symbol.last_complete_date == "2026-07-01"
    assert report.status == "WARN"


def test_audit_missing_item(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    report = audit_mu(cfg)
    symbol = report.symbols[0]
    assert symbol.missing_dates == [
        "2026-07-01",
        "2026-07-02",
        "2026-07-03",
        "2026-07-06",
        "2026-07-07",
    ]
    assert symbol.incomplete_dates == []
    assert report.status == "WARN"


def test_audit_quality_fail_incomplete(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-bad", quality="FAIL")
    report = audit_mu(cfg)
    symbol = report.symbols[0]
    assert symbol.complete_trade_date_count == 0
    assert symbol.incomplete_dates == ["2026-07-01"]
    assert symbol.incomplete_reasons == {"2026-07-01": ["QUALITY_FAIL"]}
    assert report.status == "WARN"


def test_audit_run_failed_incomplete(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-failed", run_status="FAILED")
    report = audit_mu(cfg)
    assert report.symbols[0].incomplete_reasons == {"2026-07-01": ["RUN_FAILED"]}


def test_audit_run_running_incomplete(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-running", run_status="RUNNING")
    report = audit_mu(cfg)
    assert report.symbols[0].incomplete_reasons == {"2026-07-01": ["RUN_RUNNING"]}


def test_audit_orphaned_run_incomplete(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="ghost-run", record_run=False)
    report = audit_mu(cfg)
    assert report.symbols[0].incomplete_reasons == {"2026-07-01": ["ORPHANED_RUN"]}


def test_audit_multiple_reasons_dedup_sorted(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    # Two failing snapshots for the same key: one run FAILED, one quality FAIL.
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-failed", run_status="FAILED")
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-bad", quality="FAIL")
    report = audit_mu(cfg)
    assert report.symbols[0].incomplete_reasons == {
        "2026-07-01": ["QUALITY_FAIL", "RUN_FAILED"]
    }


def test_audit_failed_snapshot_plus_complete_is_complete(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-bad", quality="FAIL")
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-ok")
    report = audit_mu(cfg)
    symbol = report.symbols[0]
    assert symbol.complete_trade_date_count == 1
    assert symbol.incomplete_dates == []
    assert "2026-07-01" not in symbol.missing_dates


def test_audit_different_interval_not_complete(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-5m", interval="5m")
    report = audit_mu(cfg)
    symbol = report.symbols[0]
    # A 5m snapshot never satisfies the exact 1m key: every expected date is
    # missing for the audited key.
    assert symbol.complete_trade_date_count == 0
    assert symbol.incomplete_trade_date_count == 0
    assert symbol.missing_dates == [
        "2026-07-01",
        "2026-07-02",
        "2026-07-03",
        "2026-07-06",
        "2026-07-07",
    ]


def test_audit_different_session_not_complete(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-rth", session="RTH")
    report = audit_mu(cfg)
    symbol = report.symbols[0]
    assert symbol.complete_trade_date_count == 0
    assert symbol.incomplete_trade_date_count == 0
    assert "2026-07-01" in symbol.missing_dates


def test_audit_different_adjustment_not_complete(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-qfq", adjustment="QFQ")
    report = audit_mu(cfg)
    symbol = report.symbols[0]
    assert symbol.complete_trade_date_count == 0
    assert symbol.incomplete_trade_date_count == 0
    assert "2026-07-01" in symbol.missing_dates


def test_audit_different_schema_not_complete(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-108", schema="10.8")
    report = audit_mu(cfg)
    symbol = report.symbols[0]
    assert symbol.complete_trade_date_count == 0
    assert symbol.incomplete_trade_date_count == 0
    assert "2026-07-01" in symbol.missing_dates


def test_audit_legacy_metadata_not_complete_current_key(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(
        cfg,
        code="US.MU",
        trade_date=date(2026, 7, 1),
        run_id="legacy-run",
        legacy_filename=True,
        include_session=False,
        include_schema=False,
    )
    report = audit_mu(cfg)
    symbol = report.symbols[0]
    # Legacy rows lack the exact requested_session/source_schema_version key:
    # they are conservatively MISSING for the current key, never COMPLETE.
    assert symbol.complete_trade_date_count == 0
    assert symbol.incomplete_trade_date_count == 0
    assert "2026-07-01" in symbol.missing_dates


def test_audit_run_trade_date_mismatch_incomplete(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    # Curated row is dated 2026-07-01 but the linked run says 2026-07-02.
    write_snapshot(
        cfg,
        code="US.MU",
        trade_date=date(2026, 7, 1),
        run_id="run-a",
        run_trade_date=date(2026, 7, 2),
    )
    report = audit_mu(cfg)
    symbol = report.symbols[0]
    assert symbol.incomplete_dates == ["2026-07-01"]
    assert symbol.incomplete_reasons == {"2026-07-01": ["RUN_METADATA_MISMATCH"]}


def test_audit_run_interval_mismatch_incomplete(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    # Curated rows are 1m but the linked run was recorded as 5m.
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a", run_interval="5m")
    report = audit_mu(cfg)
    assert report.symbols[0].incomplete_reasons == {"2026-07-01": ["RUN_METADATA_MISMATCH"]}


def test_audit_run_session_mismatch_incomplete(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    # Curated rows are ALL but the linked run was recorded as RTH.
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a", run_session="RTH")
    report = audit_mu(cfg)
    assert report.symbols[0].incomplete_reasons == {"2026-07-01": ["RUN_METADATA_MISMATCH"]}


def test_audit_run_adjustment_mismatch_incomplete(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    # Curated rows are NONE but the linked run was recorded as QFQ.
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a", run_adjustment="QFQ")
    report = audit_mu(cfg)
    assert report.symbols[0].incomplete_reasons == {"2026-07-01": ["RUN_METADATA_MISMATCH"]}


def test_audit_mismatch_snapshot_plus_complete_is_complete(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-bad", run_interval="5m")
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-good")
    report = audit_mu(cfg)
    symbol = report.symbols[0]
    # Any complete snapshot makes the whole key COMPLETE.
    assert symbol.complete_trade_date_count == 1
    assert symbol.incomplete_dates == []
    assert "2026-07-01" not in symbol.missing_dates


def test_audit_mismatch_priority_after_quality_fail(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-q", quality="FAIL")
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-m", run_interval="5m")
    report = audit_mu(cfg)
    assert report.symbols[0].incomplete_reasons == {
        "2026-07-01": ["QUALITY_FAIL", "RUN_METADATA_MISMATCH"]
    }


def test_snapshot_incomplete_reason_matching_metadata_is_none():
    from market_vault.storage.catalog import _snapshot_incomplete_reason

    # A run whose metadata exactly matches the curated row is eligible for
    # completion: the reason must be None, not RUN_METADATA_MISMATCH. The
    # tuple field order (trade date, interval, session, adjustment) must stay
    # aligned between both sides for this to hold.
    reason = _snapshot_incomplete_reason(
        run_id="run-ok",
        run_status="SUCCESS",
        has_quality_fail=False,
        run_metadata=(date(2026, 7, 1), "1m", "ALL", "NONE"),
        curated_metadata=(date(2026, 7, 1), "1m", "ALL", "NONE"),
    )
    assert reason is None


def test_catalog_incomplete_reasons_empty_for_complete_snapshot(tmp_path):
    cfg = settings(tmp_path)
    # A fully matching SUCCESS snapshot must yield no reasons at the Catalog
    # layer itself -- the audit's complete-key filtering must not be the
    # only thing hiding a wrong RUN_METADATA_MISMATCH.
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-ok")

    reasons = Catalog(cfg).incomplete_market_bar_item_reasons(
        symbols=["US.MU"],
        trade_dates=[date(2026, 7, 1)],
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source_schema_version="10.9",
    )
    assert reasons == {}


def test_audit_every_incomplete_date_has_reasons(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    # One incomplete date per reason family; every date must carry reasons.
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-q", quality="FAIL")
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 2), run_id="run-f", run_status="FAILED")
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 3), run_id="run-r", run_status="RUNNING")
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 6), run_id="run-m", run_trade_date=date(2026, 7, 7))
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 7), run_id="run-o", record_run=False)

    report = audit_mu(cfg)
    symbol = report.symbols[0]
    assert symbol.incomplete_dates == [
        "2026-07-01",
        "2026-07-02",
        "2026-07-03",
        "2026-07-06",
        "2026-07-07",
    ]
    for day in symbol.incomplete_dates:
        assert symbol.incomplete_reasons[day], f"no reasons reported for {day}"
    assert symbol.incomplete_reasons["2026-07-01"] == ["QUALITY_FAIL"]
    assert symbol.incomplete_reasons["2026-07-02"] == ["RUN_FAILED"]
    assert symbol.incomplete_reasons["2026-07-03"] == ["RUN_RUNNING"]
    assert symbol.incomplete_reasons["2026-07-06"] == ["RUN_METADATA_MISMATCH"]
    assert symbol.incomplete_reasons["2026-07-07"] == ["ORPHANED_RUN"]


# --- Audit summary ----------------------------------------------------------


def test_audit_all_complete_pass(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    for day in [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3), date(2026, 7, 6), date(2026, 7, 7)]:
        write_snapshot(cfg, code="US.MU", trade_date=day, run_id=f"run-{day.isoformat()}")
    report = audit_mu(cfg)
    assert report.status == "PASS"


def test_audit_missing_warns(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-ok")
    report = audit_mu(cfg)
    assert report.status == "WARN"


def test_audit_incomplete_warns(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-bad", quality="FAIL")
    report = audit_mu(cfg)
    assert report.status == "WARN"


def test_audit_coverage_percentage(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    for day in [date(2026, 7, 1), date(2026, 7, 2)]:
        write_snapshot(cfg, code="US.MU", trade_date=day, run_id=f"run-{day.isoformat()}")
    report = audit_mu(cfg)
    assert report.symbols[0].coverage_percentage == 40.0
    assert report.summary.coverage_percentage == 40.0


def test_audit_multi_symbol_separate(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    for day in [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3), date(2026, 7, 6), date(2026, 7, 7)]:
        write_snapshot(cfg, code="US.MU", trade_date=day, run_id=f"mu-{day.isoformat()}")
    write_snapshot(cfg, code="US.NVDA", trade_date=date(2026, 7, 1), run_id="nvda-1")
    report = run_audit(
        cfg,
        symbols=["US.MU", "US.NVDA"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 7),
        calendar_market="US",
        today=date(2026, 8, 2),
    )
    by_code = {symbol.code: symbol for symbol in report.symbols}
    assert by_code["US.MU"].complete_trade_date_count == 5
    assert by_code["US.NVDA"].complete_trade_date_count == 1
    assert by_code["US.NVDA"].missing_trade_date_count == 4
    assert report.status == "WARN"


def test_audit_overall_summary(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    for day in [date(2026, 7, 1), date(2026, 7, 2)]:
        write_snapshot(cfg, code="US.MU", trade_date=day, run_id=f"run-{day.isoformat()}")
    report = audit_mu(cfg)
    assert report.summary.total_expected_items == 5
    assert report.summary.complete_item_count == 2
    assert report.summary.incomplete_item_count == 0
    assert report.summary.missing_item_count == 3
    assert report.summary.coverage_percentage == 40.0


def test_audit_missing_dates_ascending(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 7), run_id="run-7")
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-1")
    report = audit_mu(cfg)
    assert report.symbols[0].missing_dates == [
        "2026-07-02",
        "2026-07-03",
        "2026-07-06",
    ]
    assert report.symbols[0].complete_dates == []


def test_audit_incomplete_dates_ascending(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 7), run_id="run-7", quality="FAIL")
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-1", quality="FAIL")
    report = audit_mu(cfg)
    assert report.symbols[0].incomplete_dates == ["2026-07-01", "2026-07-07"]


def test_audit_complete_dates_omitted_by_default(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-1")
    report = audit_mu(cfg)
    assert report.symbols[0].complete_dates == []


def test_audit_include_complete_dates(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    for day in [date(2026, 7, 1), date(2026, 7, 3)]:
        write_snapshot(cfg, code="US.MU", trade_date=day, run_id=f"run-{day.isoformat()}")
    report = audit_mu(cfg, include_complete_dates=True)
    assert report.symbols[0].complete_dates == ["2026-07-01", "2026-07-03"]


def test_audit_zero_expected_dates_coverage_100(tmp_path):
    cfg = settings(tmp_path)
    # Calendar snapshot fully covers 07-01..07-03 but has a trading-day row
    # only on 07-01; auditing 07-02..07-03 expects zero trade dates.
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 3),
    )
    report = audit_mu(cfg, start_date=date(2026, 7, 2), end_date=date(2026, 7, 3))
    assert report.status == "PASS"
    assert report.summary.total_expected_items == 0
    assert report.summary.coverage_percentage == 100.0
    assert report.symbols[0].coverage_percentage == 100.0


def test_audit_report_json_written(tmp_path):
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-1")
    report = audit_mu(cfg)
    assert report.report_file is not None
    path = Path(report.report_file)
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["run_id"] == report.run_id
    assert payload["report_type"] == "MARKET_BARS_COVERAGE_AUDIT"
    assert payload["status"] == "WARN"
    assert payload["summary"]["missing_item_count"] == 4


# --- CLI and API ------------------------------------------------------------


def test_cli_inventory_parses():
    args = build_parser().parse_args(
        [
            "inventory",
            "--symbols",
            "US.MU",
            "--interval",
            "1m",
            "--session",
            "ALL",
            "--adjustment",
            "NONE",
            "--include-files",
        ]
    )
    assert args.command == "inventory"
    assert args.symbols == ["US.MU"]
    assert args.interval == "1m"
    assert args.include_files is True


def test_cli_audit_parses():
    args = build_parser().parse_args(
        [
            "audit",
            "--calendar-market",
            "US",
            "--start-date",
            "2026-07-01",
            "--end-date",
            "2026-07-31",
            "--symbols",
            "US.MU",
            "--fail-on-gaps",
        ]
    )
    assert args.command == "audit"
    assert args.calendar_market == "US"
    assert args.start_date == date(2026, 7, 1)
    assert args.fail_on_gaps is True


def test_cli_audit_rejects_market_and_code():
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            [
                "audit",
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


def test_audit_rejects_start_after_end(tmp_path):
    with pytest.raises(ValueError, match="on or before"):
        run_audit(
            settings(tmp_path),
            symbols=["US.MU"],
            start_date=date(2026, 7, 2),
            end_date=date(2026, 7, 1),
            calendar_market="US",
            today=date(2026, 8, 2),
        )


@pytest.mark.parametrize("end_date", [date(2026, 8, 2), date(2026, 8, 3)])
def test_audit_rejects_current_or_future_end_date(tmp_path, end_date):
    with pytest.raises(ValueError, match="before today's UTC date"):
        run_audit(
            settings(tmp_path),
            symbols=["US.MU"],
            start_date=date(2026, 7, 1),
            end_date=end_date,
            calendar_market="US",
            today=date(2026, 8, 2),
        )


def test_cli_audit_rejects_no_symbols(tmp_path):
    cfg_path = write_settings_file(tmp_path)
    with pytest.raises(SystemExit):
        cli_module.main(
            [
                "--settings",
                str(cfg_path),
                "audit",
                "--calendar-market",
                "US",
                "--start-date",
                "2026-07-01",
                "--end-date",
                "2026-07-31",
            ]
        )


def test_inventory_no_symbols_means_all(tmp_path):
    cfg = settings(tmp_path)
    from market_vault.audit import run_inventory

    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-mu")
    write_snapshot(cfg, code="US.NVDA", trade_date=date(2026, 7, 1), run_id="run-nvda")
    report = run_inventory(cfg)
    assert report.summary.symbol_count == 2


def test_audit_settings_defaults_session_adjustment(tmp_path):
    cfg = replace(settings(tmp_path), default_session="RTH", default_adjustment="QFQ")
    us_calendar(cfg)
    report = audit_mu(cfg)
    assert report.parameters["requested_session"] == "RTH"
    assert report.parameters["adjustment"] == "QFQ"


def test_audit_explicit_overrides_settings_defaults(tmp_path):
    cfg = replace(settings(tmp_path), default_session="RTH", default_adjustment="QFQ")
    us_calendar(cfg)
    report = audit_mu(cfg, requested_session="ALL", adjustment="NONE")
    assert report.parameters["requested_session"] == "ALL"
    assert report.parameters["adjustment"] == "NONE"


def test_cli_audit_warn_exits_zero(tmp_path):
    cfg_path = write_settings_file(tmp_path)
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-1")

    exit_code = cli_module.main(
        [
            "--settings",
            str(cfg_path),
            "audit",
            "--calendar-market",
            "US",
            "--start-date",
            "2026-07-01",
            "--end-date",
            "2026-07-07",
            "--symbols",
            "US.MU",
        ]
    )
    assert exit_code == 0


def test_cli_audit_fail_on_gaps_warn_exits_two(tmp_path):
    cfg_path = write_settings_file(tmp_path)
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-1")

    exit_code = cli_module.main(
        [
            "--settings",
            str(cfg_path),
            "audit",
            "--calendar-market",
            "US",
            "--start-date",
            "2026-07-01",
            "--end-date",
            "2026-07-07",
            "--symbols",
            "US.MU",
            "--fail-on-gaps",
        ]
    )
    assert exit_code == 2


def test_cli_audit_failed_exits_one(tmp_path):
    cfg_path = write_settings_file(tmp_path)
    # No local calendar data at all -> calendar coverage FAILED.
    exit_code = cli_module.main(
        [
            "--settings",
            str(cfg_path),
            "audit",
            "--calendar-market",
            "US",
            "--start-date",
            "2026-07-01",
            "--end-date",
            "2026-07-07",
            "--symbols",
            "US.MU",
        ]
    )
    assert exit_code == 1


def test_api_pure_local(monkeypatch, tmp_path):
    class Raiser:
        def __init__(self, settings):
            raise AssertionError("OpenD collector must not be constructed")

    monkeypatch.setattr("market_vault.collectors.MoomooCalendarCollector", Raiser)
    monkeypatch.setattr("market_vault.collectors.MoomooHistoryCollector", Raiser)
    cfg = settings(tmp_path)
    us_calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-1")

    vault = MarketVault(cfg)
    inventory = vault.inventory_market_bars(symbols=["US.MU"])
    assert inventory.status == "SUCCESS"
    assert inventory.summary.snapshot_row_count == 1

    audit = vault.audit_market_bars(
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 7),
        calendar_market="US",
        today=date(2026, 8, 2),
    )
    assert audit.status == "WARN"
    assert audit.summary.missing_item_count == 4


def test_cli_audit_invalid_range_structured_error_no_traceback(tmp_path, capsys):
    cfg_path = write_settings_file(tmp_path)

    exit_code = cli_module.main(
        [
            "--settings",
            str(cfg_path),
            "audit",
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

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert payload["report_type"] == "MARKET_BARS_COVERAGE_AUDIT"
    assert payload["status"] == "FAILED"
    assert payload["error"] == "start_date must be on or before end_date"
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err


def test_cli_audit_future_end_date_structured_error_no_traceback(tmp_path, capsys):
    cfg_path = write_settings_file(tmp_path)
    future = datetime.now(timezone.utc).date() + timedelta(days=1)

    exit_code = cli_module.main(
        [
            "--settings",
            str(cfg_path),
            "audit",
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

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert payload["status"] == "FAILED"
    assert "before today's UTC date" in payload["error"]
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err


def test_api_audit_still_raises_value_error(tmp_path):
    cfg = settings(tmp_path)
    with pytest.raises(ValueError, match="on or before"):
        MarketVault(cfg).audit_market_bars(
            symbols=["US.MU"],
            start_date=date(2026, 7, 2),
            end_date=date(2026, 7, 1),
            calendar_market="US",
            today=date(2026, 8, 2),
        )
# P2_CLOSED_WORLD_BUILD_CANARY_B
