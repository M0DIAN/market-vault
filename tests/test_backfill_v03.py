from __future__ import annotations

from argparse import Namespace
from dataclasses import replace
from datetime import date, datetime, timezone

import pandas as pd
import pytest

import market_vault.api as api_module
import market_vault.backfill as backfill_module
import market_vault.cli as cli_module
import market_vault.service as service_module
from market_vault import MarketVault
from market_vault.backfill import BackfillItem, BackfillPlan, collect_history_backfill, plan_history_backfill
from market_vault.cli import _resolve_symbols, build_parser
from market_vault.models import DatasetRunManifest, QualityResult, RunManifest, Settings
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


def history_raw_frame(code: str, trade_date: date) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "code": [code],
            "name": [code],
            "time_key": [f"{trade_date.isoformat()} 09:30:00"],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [100],
        }
    )


def write_calendar_snapshot(
    cfg: Settings,
    *,
    market: str | None = None,
    code: str | None = None,
    trade_dates: list[date],
    trade_date_types: list[str] | None = None,
    requested_start_date: date,
    requested_end_date: date,
    captured_at: str = "2026-08-01T01:00:00Z",
    run_id: str = "calendar-run",
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
        code=code,
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
        captured_at=pd.Timestamp(captured_at),
        source="moomoo",
        source_schema_version=cfg.source_schema_version,
        run_id=run_id,
    )
    ParquetStore(cfg).write_trading_calendar_curated(
        curated,
        "MARKET" if market else "CODE",
        (market or code or "").strip().upper(),
        requested_start_date,
        requested_end_date,
        run_id,
    )
    Catalog(cfg).refresh_trading_calendar_views()


def write_completed_bar(
    cfg: Settings,
    *,
    code: str,
    trade_date: date,
    interval: str = "1m",
    requested_session: str = "ALL",
    adjustment: str = "NONE",
    source_schema_version: str = "10.9",
    run_id: str | None = None,
    quality_fail: bool = False,
    write_curated: bool = True,
    include_requested_session: bool = True,
    include_source_schema_version: bool = True,
) -> RunManifest:
    store = ParquetStore(cfg)
    catalog = Catalog(cfg)
    run = RunManifest(
        requested_trade_date=trade_date,
        requested_symbols=[code],
        interval=interval.lower(),
        session=requested_session.upper(),
        adjustment=adjustment.upper(),
    )
    if run_id is not None:
        run.run_id = run_id
    raw = history_raw_frame(code, trade_date)
    raw["requested_trade_date"] = trade_date
    raw["interval"] = interval.lower()
    raw["adjustment"] = adjustment.upper()
    raw["requested_session"] = requested_session.upper()
    raw["ingestion_run_id"] = run.run_id
    curated = normalize_bars(
        raw,
        requested_trade_date=trade_date,
        interval=interval,
        requested_session=requested_session,
        adjustment=adjustment,
        source="moomoo",
        source_schema_version=source_schema_version,
        run_id=run.run_id,
    )
    if not include_requested_session:
        curated = curated.drop(columns=["requested_session"])
    if not include_source_schema_version:
        curated = curated.drop(columns=["source_schema_version"])
    if write_curated:
        store.write_curated(curated, trade_date, interval, [code], requested_session, adjustment, run_id=run.run_id)
    run.successful_symbols = [code]
    run.status = "SUCCESS"
    run.finished_at = datetime.now(timezone.utc)
    run.row_count = len(curated)
    catalog.record_run(run)
    quality_results = [QualityResult("bars_complete", "FAIL" if quality_fail else "PASS")]
    catalog.record_quality(run.run_id, quality_results)
    return run


def make_fake_collect_history(cfg: Settings, monkeypatch, responses: dict):
    call_log: list[tuple[date, tuple[str, ...]]] = []
    run_ids: list[str] = []

    def fake_collect_history(settings, trade_date, symbols, interval, session, adjustment):
        key = (trade_date, tuple(symbols))
        call_log.append(key)
        response = responses[key]
        # A list of responses yields one response per call in order; the
        # last response is kept as the tail for any further retries.
        if isinstance(response, list):
            response = response.pop(0) if len(response) > 1 else response[0]
        if "raise" in response:
            raise response["raise"]
        manifest = RunManifest(
            requested_trade_date=trade_date,
            requested_symbols=list(symbols),
            interval=interval.lower(),
            session=session.upper(),
            adjustment=adjustment.upper(),
        )
        manifest.successful_symbols = list(response.get("successful", []))
        manifest.failed_symbols = dict(response.get("failed", {}))
        manifest.status = (
            "FAILED"
            if not manifest.successful_symbols
            else "PARTIAL" if manifest.failed_symbols else "SUCCESS"
        )
        manifest.finished_at = datetime.now(timezone.utc)
        raw_frames = []
        curated_frames = []
        for code in manifest.successful_symbols:
            raw = history_raw_frame(code, trade_date)
            raw["requested_trade_date"] = trade_date
            raw["interval"] = interval.lower()
            raw["adjustment"] = adjustment.upper()
            raw["requested_session"] = session.upper()
            raw["ingestion_run_id"] = manifest.run_id
            raw_frames.append(raw)
            curated_frames.append(
                normalize_bars(
                    raw,
                    requested_trade_date=trade_date,
                    interval=interval,
                    requested_session=session,
                    adjustment=adjustment,
                    source="moomoo",
                    source_schema_version=cfg.source_schema_version,
                    run_id=manifest.run_id,
                )
            )
        if curated_frames:
            raw_all = pd.concat(raw_frames, ignore_index=True)
            curated_all = pd.concat(curated_frames, ignore_index=True)
            store = ParquetStore(cfg)
            manifest.raw_file = str(
                store.write_raw(raw_all, trade_date, interval, list(symbols), session, adjustment, run_id=manifest.run_id)
            )
            manifest.curated_file = str(
                store.write_curated(
                    curated_all, trade_date, interval, list(symbols), session, adjustment, run_id=manifest.run_id
                )
            )
            manifest.row_count = len(curated_all)
        Catalog(cfg).record_run(manifest)
        Catalog(cfg).record_quality(
            manifest.run_id,
            [QualityResult("bars_complete", "FAIL" if response.get("quality_fail") else "PASS")],
        )
        run_ids.append(manifest.run_id)
        return manifest

    monkeypatch.setattr(backfill_module, "collect_history", fake_collect_history)
    return call_log, run_ids


def test_collect_history_sleeps_between_symbols(monkeypatch, tmp_path):
    class FakeCollector:
        def __init__(self, settings):
            self.settings = settings

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            pass

        def fetch_history(self, code, trade_date, interval="1m", adjustment="NONE", session="ALL"):
            return history_raw_frame(code, trade_date)

    sleep_calls = []
    monkeypatch.setattr(service_module, "MoomooHistoryCollector", FakeCollector)
    monkeypatch.setattr(service_module.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    manifest = service_module.collect_history(
        settings(tmp_path),
        trade_date=date(2026, 7, 31),
        symbols=["US.MU", "US.NVDA"],
        interval="1m",
        session="ALL",
        adjustment="NONE",
    )

    assert manifest.status == "SUCCESS"
    assert sleep_calls == [0]


def test_plan_uses_local_trading_calendar_and_excludes_weekends(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 6)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 6),
    )

    plan = plan_history_backfill(
        cfg,
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 6),
        calendar_market="US",
        today=date(2026, 8, 2),
    )

    assert plan.trading_dates == [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 6)]
    assert plan.pending_items == [
        BackfillItem("US.MU", date(2026, 7, 1)),
        BackfillItem("US.MU", date(2026, 7, 2)),
        BackfillItem("US.MU", date(2026, 7, 6)),
    ]


def test_plan_includes_morning_and_afternoon_trade_dates(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1), date(2026, 7, 2)],
        trade_date_types=["MORNING", "AFTERNOON"],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 2),
    )

    plan = plan_history_backfill(
        cfg,
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        calendar_market="US",
        today=date(2026, 8, 2),
    )

    assert [item.trade_date for item in plan.pending_items] == [date(2026, 7, 1), date(2026, 7, 2)]


def test_plan_sorts_dates_and_symbols_stably(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 2), date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 2),
    )

    plan = plan_history_backfill(
        cfg,
        symbols=[" us.nvda ", "US.MU", "US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        calendar_market="US",
        today=date(2026, 8, 2),
    )

    assert plan.symbols == ["US.MU", "US.NVDA"]
    assert plan.pending_items == [
        BackfillItem("US.MU", date(2026, 7, 1)),
        BackfillItem("US.NVDA", date(2026, 7, 1)),
        BackfillItem("US.MU", date(2026, 7, 2)),
        BackfillItem("US.NVDA", date(2026, 7, 2)),
    ]


def test_blank_symbol_rejected(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 1),
    )

    with pytest.raises(ValueError, match="blank"):
        plan_history_backfill(
            cfg,
            symbols=["   "],
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 1),
            calendar_market="US",
            today=date(2026, 8, 2),
        )


def test_start_after_end_rejected(tmp_path):
    cfg = settings(tmp_path)
    with pytest.raises(ValueError, match="on or before"):
        plan_history_backfill(
            cfg,
            symbols=["US.MU"],
            start_date=date(2026, 7, 2),
            end_date=date(2026, 7, 1),
            calendar_market="US",
            today=date(2026, 8, 2),
        )


@pytest.mark.parametrize("candidate", [date(2026, 8, 2), date(2026, 8, 3)])
def test_current_or_future_dates_rejected(tmp_path, candidate):
    cfg = settings(tmp_path)
    with pytest.raises(ValueError, match="before today's UTC date"):
        plan_history_backfill(
            cfg,
            symbols=["US.MU"],
            start_date=date(2026, 7, 1),
            end_date=candidate,
            calendar_market="US",
            today=date(2026, 8, 2),
        )


def test_calendar_coverage_single_range_passes(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1), date(2026, 7, 31)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 31),
    )

    plan = plan_history_backfill(
        cfg,
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
        calendar_market="US",
        today=date(2026, 8, 2),
    )

    assert plan.calendar_scope_type == "MARKET"


def test_calendar_coverage_adjacent_ranges_merge(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 10),
        run_id="run-1",
    )
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 31)],
        requested_start_date=date(2026, 7, 11),
        requested_end_date=date(2026, 7, 31),
        run_id="run-2",
    )

    plan = plan_history_backfill(
        cfg,
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
        calendar_market="US",
        today=date(2026, 8, 2),
    )

    assert plan.trading_dates == [date(2026, 7, 1), date(2026, 7, 31)]


def test_calendar_coverage_gap_fails_and_does_not_create_collector(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 10),
        run_id="run-1",
    )
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 31)],
        requested_start_date=date(2026, 7, 12),
        requested_end_date=date(2026, 7, 31),
        run_id="run-2",
    )
    monkeypatch.setattr(backfill_module, "collect_history", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))

    manifest = collect_history_backfill(
        cfg,
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
        calendar_market="US",
        today=date(2026, 8, 2),
    )

    assert manifest.status == "FAILED"
    assert "Missing coverage" in manifest.failed_items["PLAN"]
    assert manifest.parameters["child_run_ids"] == []


def test_calendar_empty_fails(tmp_path):
    manifest = collect_history_backfill(
        settings(tmp_path),
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
        calendar_market="US",
        today=date(2026, 8, 2),
    )

    assert manifest.status == "FAILED"
    assert "no coverage" in manifest.failed_items["PLAN"].lower()


def test_exact_complete_key_is_skipped(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 1),
    )
    write_completed_bar(cfg, code="US.MU", trade_date=date(2026, 7, 1))

    plan = plan_history_backfill(
        cfg,
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        calendar_market="US",
        today=date(2026, 8, 2),
    )

    assert plan.pending_items == []
    assert plan.skipped_items == [BackfillItem("US.MU", date(2026, 7, 1))]


@pytest.mark.parametrize(
    ("interval", "requested_session", "adjustment", "source_schema_version"),
    [
        ("5m", "ALL", "NONE", "10.9"),
        ("1m", "RTH", "NONE", "10.9"),
        ("1m", "ALL", "QFQ", "10.9"),
        ("1m", "ALL", "NONE", "10.8"),
    ],
)
def test_non_matching_complete_key_does_not_skip(
    tmp_path,
    interval,
    requested_session,
    adjustment,
    source_schema_version,
):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 1),
    )
    write_completed_bar(cfg, code="US.MU", trade_date=date(2026, 7, 1))

    if source_schema_version != "10.9":
        # The plan derives source_schema_version from settings, so a
        # schema-version mismatch cannot be driven through plan_history_backfill;
        # assert it at the catalog query level instead.
        completed = Catalog(cfg).completed_market_bar_items(
            symbols=["US.MU"],
            trade_dates=[date(2026, 7, 1)],
            interval="1m",
            requested_session="ALL",
            adjustment="NONE",
            source_schema_version="10.8",
        )
        assert completed == set()
    else:
        plan = plan_history_backfill(
            cfg,
            symbols=["US.MU"],
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 1),
            calendar_market="US",
            interval=interval,
            session=requested_session,
            adjustment=adjustment,
            today=date(2026, 8, 2),
        )
        assert plan.pending_items == [BackfillItem("US.MU", date(2026, 7, 1))]


def test_quality_fail_run_does_not_skip(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 1),
    )
    write_completed_bar(cfg, code="US.MU", trade_date=date(2026, 7, 1), quality_fail=True)

    plan = plan_history_backfill(
        cfg,
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        calendar_market="US",
        today=date(2026, 8, 2),
    )

    assert plan.pending_items == [BackfillItem("US.MU", date(2026, 7, 1))]


def test_missing_curated_rows_do_not_skip(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 1),
    )
    write_completed_bar(cfg, code="US.MU", trade_date=date(2026, 7, 1), write_curated=False)

    plan = plan_history_backfill(
        cfg,
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        calendar_market="US",
        today=date(2026, 8, 2),
    )

    assert plan.pending_items == [BackfillItem("US.MU", date(2026, 7, 1))]


def test_old_curated_files_without_request_metadata_do_not_skip(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 1),
    )
    write_completed_bar(
        cfg,
        code="US.MU",
        trade_date=date(2026, 7, 1),
        include_requested_session=False,
        include_source_schema_version=False,
    )

    plan = plan_history_backfill(
        cfg,
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        calendar_market="US",
        today=date(2026, 8, 2),
    )

    assert plan.pending_items == [BackfillItem("US.MU", date(2026, 7, 1))]


def test_force_disables_skip(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 1),
    )
    write_completed_bar(cfg, code="US.MU", trade_date=date(2026, 7, 1))

    plan = plan_history_backfill(
        cfg,
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        calendar_market="US",
        force=True,
        today=date(2026, 8, 2),
    )

    assert plan.skipped_items == []
    assert plan.pending_items == [BackfillItem("US.MU", date(2026, 7, 1))]


def test_backfill_groups_pending_symbols_by_date(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1), date(2026, 7, 2)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 2),
    )
    calls, _ = make_fake_collect_history(
        cfg,
        monkeypatch,
        {
            (date(2026, 7, 1), ("US.MU", "US.NVDA")): {"successful": ["US.MU", "US.NVDA"]},
            (date(2026, 7, 2), ("US.MU", "US.NVDA")): {"successful": ["US.MU", "US.NVDA"]},
        },
    )

    manifest = collect_history_backfill(
        cfg,
        symbols=["US.NVDA", "US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        calendar_market="US",
        today=date(2026, 8, 2),
    )

    assert calls == [
        (date(2026, 7, 1), ("US.MU", "US.NVDA")),
        (date(2026, 7, 2), ("US.MU", "US.NVDA")),
    ]
    assert manifest.status == "SUCCESS"


def test_backfill_retries_only_failed_symbols(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 1),
    )
    calls, _ = make_fake_collect_history(
        cfg,
        monkeypatch,
        {
            (date(2026, 7, 1), ("US.MU", "US.NVDA")): {"successful": ["US.MU"], "failed": {"US.NVDA": "boom"}},
            (date(2026, 7, 1), ("US.NVDA",)): {"successful": ["US.NVDA"]},
        },
    )

    manifest = collect_history_backfill(
        cfg,
        symbols=["US.MU", "US.NVDA"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        calendar_market="US",
        retry_backoff_seconds=0,
        today=date(2026, 8, 2),
    )

    assert calls == [
        (date(2026, 7, 1), ("US.MU", "US.NVDA")),
        (date(2026, 7, 1), ("US.NVDA",)),
    ]
    assert manifest.parameters["successful_dates_by_symbol"]["US.MU"] == ["2026-07-01"]
    assert manifest.parameters["successful_dates_by_symbol"]["US.NVDA"] == ["2026-07-01"]


def test_backfill_stops_retrying_after_limit(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 1),
    )
    calls, _ = make_fake_collect_history(
        cfg,
        monkeypatch,
        {
            (date(2026, 7, 1), ("US.MU",)): {"failed": {"US.MU": "boom"}},
        },
    )

    manifest = collect_history_backfill(
        cfg,
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        calendar_market="US",
        max_retries=1,
        retry_backoff_seconds=0,
        today=date(2026, 8, 2),
    )

    assert calls == [(date(2026, 7, 1), ("US.MU",)), (date(2026, 7, 1), ("US.MU",))]
    assert manifest.status == "FAILED"
    assert "2026-07-01: boom" in manifest.failed_items["US.MU"]


def test_backfill_continues_after_date_level_exception(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1), date(2026, 7, 2)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 2),
    )
    calls, _ = make_fake_collect_history(
        cfg,
        monkeypatch,
        {
            (date(2026, 7, 1), ("US.MU",)): {"raise": RuntimeError("day failed")},
            (date(2026, 7, 2), ("US.MU",)): {"successful": ["US.MU"]},
        },
    )

    manifest = collect_history_backfill(
        cfg,
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        calendar_market="US",
        max_retries=0,
        today=date(2026, 8, 2),
    )

    assert calls == [(date(2026, 7, 1), ("US.MU",)), (date(2026, 7, 2), ("US.MU",))]
    assert manifest.status == "PARTIAL"
    assert manifest.parameters["successful_dates_by_symbol"]["US.MU"] == ["2026-07-02"]


def test_backfill_all_skip_makes_no_requests(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 1),
    )
    write_completed_bar(cfg, code="US.MU", trade_date=date(2026, 7, 1))
    monkeypatch.setattr(backfill_module, "collect_history", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))

    manifest = collect_history_backfill(
        cfg,
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        calendar_market="US",
        today=date(2026, 8, 2),
    )

    assert manifest.status == "SUCCESS"
    assert manifest.parameters["child_run_ids"] == []
    assert manifest.successful_items == ["US.MU"]


def test_same_command_second_run_only_executes_previous_failures(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 1),
    )
    first_calls, _ = make_fake_collect_history(
        cfg,
        monkeypatch,
        {
            (date(2026, 7, 1), ("US.MU", "US.NVDA")): {"successful": ["US.MU"], "failed": {"US.NVDA": "boom"}},
            (date(2026, 7, 1), ("US.NVDA",)): {"failed": {"US.NVDA": "boom"}},
        },
    )
    collect_history_backfill(
        cfg,
        symbols=["US.MU", "US.NVDA"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        calendar_market="US",
        max_retries=1,
        retry_backoff_seconds=0,
        today=date(2026, 8, 2),
    )
    second_calls, _ = make_fake_collect_history(
        cfg,
        monkeypatch,
        {
            (date(2026, 7, 1), ("US.NVDA",)): {"successful": ["US.NVDA"]},
        },
    )

    manifest = collect_history_backfill(
        cfg,
        symbols=["US.MU", "US.NVDA"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        calendar_market="US",
        max_retries=0,
        today=date(2026, 8, 2),
    )

    assert first_calls == [
        (date(2026, 7, 1), ("US.MU", "US.NVDA")),
        (date(2026, 7, 1), ("US.NVDA",)),
    ]
    assert second_calls == [(date(2026, 7, 1), ("US.NVDA",))]
    assert manifest.status == "SUCCESS"


def test_backfill_records_child_run_ids_and_row_count(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1), date(2026, 7, 2)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 2),
    )
    _, run_ids = make_fake_collect_history(
        cfg,
        monkeypatch,
        {
            (date(2026, 7, 1), ("US.MU",)): {"successful": ["US.MU"]},
            (date(2026, 7, 2), ("US.MU",)): {"successful": ["US.MU"]},
        },
    )

    manifest = collect_history_backfill(
        cfg,
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        calendar_market="US",
        today=date(2026, 8, 2),
    )

    assert manifest.parameters["child_run_ids"] == run_ids
    assert manifest.row_count == 2


def test_backfill_quality_fail_then_pass_is_success(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 1),
    )
    calls, _ = make_fake_collect_history(
        cfg,
        monkeypatch,
        {
            (date(2026, 7, 1), ("US.MU",)): [
                {"successful": ["US.MU"], "quality_fail": True},
                {"successful": ["US.MU"]},
            ],
        },
    )

    manifest = collect_history_backfill(
        cfg,
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        calendar_market="US",
        retry_backoff_seconds=0,
        today=date(2026, 8, 2),
    )

    # The quality-failing attempt must not count as success and must be
    # retried; the retry passes quality checks, so the run succeeds.
    assert calls == [
        (date(2026, 7, 1), ("US.MU",)),
        (date(2026, 7, 1), ("US.MU",)),
    ]
    assert manifest.status == "SUCCESS"
    assert manifest.parameters["successful_dates_by_symbol"]["US.MU"] == ["2026-07-01"]
    assert manifest.parameters["failed_dates_by_symbol"]["US.MU"] == []
    assert manifest.parameters["successful_item_count"] == 1
    assert manifest.parameters["failed_item_count"] == 0


def test_backfill_quality_fail_exhausted_retries_is_failed(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 1),
    )
    calls, _ = make_fake_collect_history(
        cfg,
        monkeypatch,
        {
            (date(2026, 7, 1), ("US.MU",)): {"successful": ["US.MU"], "quality_fail": True},
        },
    )

    manifest = collect_history_backfill(
        cfg,
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        calendar_market="US",
        max_retries=1,
        retry_backoff_seconds=0,
        today=date(2026, 8, 2),
    )

    assert calls == [
        (date(2026, 7, 1), ("US.MU",)),
        (date(2026, 7, 1), ("US.MU",)),
    ]
    assert manifest.status == "FAILED"
    assert manifest.parameters["successful_dates_by_symbol"]["US.MU"] == []
    assert manifest.parameters["failed_dates_by_symbol"]["US.MU"] == [
        {"date": "2026-07-01", "error": "Child run failed bar quality checks"}
    ]
    assert manifest.parameters["failed_item_count"] == 1
    assert "Child run failed bar quality checks" in manifest.failed_items["US.MU"]


def test_backfill_quality_fail_records_no_symbol_as_success_before_retry(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 1),
    )
    calls, _ = make_fake_collect_history(
        cfg,
        monkeypatch,
        {
            (date(2026, 7, 1), ("US.MU", "US.NVDA")): [
                {"successful": ["US.MU", "US.NVDA"], "quality_fail": True},
                {"successful": ["US.MU", "US.NVDA"]},
            ],
        },
    )

    manifest = collect_history_backfill(
        cfg,
        symbols=["US.MU", "US.NVDA"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        calendar_market="US",
        retry_backoff_seconds=0,
        today=date(2026, 8, 2),
    )

    # Both symbols are retried after the quality-failing attempt; neither is
    # recorded as successful from that attempt alone.
    assert calls == [
        (date(2026, 7, 1), ("US.MU", "US.NVDA")),
        (date(2026, 7, 1), ("US.MU", "US.NVDA")),
    ]
    assert len(manifest.parameters["child_run_ids"]) == 2
    assert manifest.status == "SUCCESS"
    assert manifest.parameters["successful_dates_by_symbol"]["US.MU"] == ["2026-07-01"]
    assert manifest.parameters["successful_dates_by_symbol"]["US.NVDA"] == ["2026-07-01"]


def test_backfill_quality_fail_retry_records_date_once(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 1),
    )
    calls, _ = make_fake_collect_history(
        cfg,
        monkeypatch,
        {
            (date(2026, 7, 1), ("US.MU", "US.NVDA")): [
                {"successful": ["US.MU"], "failed": {"US.NVDA": "boom"}, "quality_fail": True},
                {"successful": ["US.MU", "US.NVDA"]},
            ],
        },
    )

    manifest = collect_history_backfill(
        cfg,
        symbols=["US.MU", "US.NVDA"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        calendar_market="US",
        retry_backoff_seconds=0,
        today=date(2026, 8, 2),
    )

    assert calls == [
        (date(2026, 7, 1), ("US.MU", "US.NVDA")),
        (date(2026, 7, 1), ("US.MU", "US.NVDA")),
    ]
    # US.MU was reported successful by the quality-failing attempt too, but
    # the date must be recorded exactly once (after the passing retry).
    assert manifest.parameters["successful_dates_by_symbol"]["US.MU"] == ["2026-07-01"]
    assert manifest.parameters["successful_dates_by_symbol"]["US.NVDA"] == ["2026-07-01"]
    assert manifest.parameters["successful_item_count"] == 2
    assert manifest.status == "SUCCESS"


def test_backfill_unrecovered_quality_fail_records_clear_error(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 1),
    )
    calls, _ = make_fake_collect_history(
        cfg,
        monkeypatch,
        {
            (date(2026, 7, 1), ("US.MU", "US.NVDA")): {
                "successful": ["US.MU", "US.NVDA"],
                "quality_fail": True,
            },
        },
    )

    manifest = collect_history_backfill(
        cfg,
        symbols=["US.MU", "US.NVDA"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        calendar_market="US",
        max_retries=0,
        retry_backoff_seconds=0,
        today=date(2026, 8, 2),
    )

    assert calls == [(date(2026, 7, 1), ("US.MU", "US.NVDA"))]
    assert manifest.status == "FAILED"
    for symbol in ["US.MU", "US.NVDA"]:
        assert manifest.parameters["failed_dates_by_symbol"][symbol] == [
            {"date": "2026-07-01", "error": "Child run failed bar quality checks"}
        ]
        assert "2026-07-01" in manifest.failed_items[symbol]
        assert "Child run failed bar quality checks" in manifest.failed_items[symbol]


def test_backfill_partial_when_some_dates_quality_fail(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1), date(2026, 7, 2)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 2),
    )
    calls, _ = make_fake_collect_history(
        cfg,
        monkeypatch,
        {
            (date(2026, 7, 1), ("US.MU",)): {"successful": ["US.MU"], "quality_fail": True},
            (date(2026, 7, 2), ("US.MU",)): {"successful": ["US.MU"]},
        },
    )

    manifest = collect_history_backfill(
        cfg,
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        calendar_market="US",
        max_retries=0,
        retry_backoff_seconds=0,
        today=date(2026, 8, 2),
    )

    assert calls == [
        (date(2026, 7, 1), ("US.MU",)),
        (date(2026, 7, 2), ("US.MU",)),
    ]
    assert manifest.status == "PARTIAL"
    assert manifest.parameters["successful_dates_by_symbol"]["US.MU"] == ["2026-07-02"]
    assert manifest.parameters["failed_dates_by_symbol"]["US.MU"] == [
        {"date": "2026-07-01", "error": "Child run failed bar quality checks"}
    ]
    assert manifest.parameters["successful_item_count"] == 1
    assert manifest.parameters["failed_item_count"] == 1


def test_backfill_rerun_skips_quality_recovered_data(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 1),
    )
    first_calls, _ = make_fake_collect_history(
        cfg,
        monkeypatch,
        {
            (date(2026, 7, 1), ("US.MU",)): [
                {"successful": ["US.MU"], "quality_fail": True},
                {"successful": ["US.MU"]},
            ],
        },
    )

    first = collect_history_backfill(
        cfg,
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        calendar_market="US",
        retry_backoff_seconds=0,
        today=date(2026, 8, 2),
    )

    assert first.status == "SUCCESS"
    assert first_calls == [
        (date(2026, 7, 1), ("US.MU",)),
        (date(2026, 7, 1), ("US.MU",)),
    ]

    # The recovered data now passes the completion query, so a rerun of the
    # same range skips it entirely instead of planning it again.
    second_calls, _ = make_fake_collect_history(cfg, monkeypatch, {})

    second = collect_history_backfill(
        cfg,
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        calendar_market="US",
        max_retries=0,
        today=date(2026, 8, 2),
    )

    assert second_calls == []
    assert second.status == "SUCCESS"
    assert second.parameters["skipped_dates_by_symbol"]["US.MU"] == ["2026-07-01"]
    assert second.parameters["skipped_item_count"] == 1
    assert second.parameters["successful_item_count"] == 0


def test_backfill_status_and_counts_consistent_after_quality_fail(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1), date(2026, 7, 2)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 2),
    )
    calls, _ = make_fake_collect_history(
        cfg,
        monkeypatch,
        {
            (date(2026, 7, 1), ("US.MU", "US.NVDA")): [
                {"successful": ["US.MU", "US.NVDA"], "quality_fail": True},
                {"successful": ["US.MU", "US.NVDA"]},
            ],
            (date(2026, 7, 2), ("US.MU", "US.NVDA")): {
                "successful": ["US.MU", "US.NVDA"],
                "quality_fail": True,
            },
        },
    )

    manifest = collect_history_backfill(
        cfg,
        symbols=["US.MU", "US.NVDA"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        calendar_market="US",
        max_retries=1,
        retry_backoff_seconds=0,
        today=date(2026, 8, 2),
    )

    # 2026-07-01: quality fail then pass -> both symbols successful once.
    # 2026-07-02: quality fail on both attempts -> both symbols failed.
    assert calls == [
        (date(2026, 7, 1), ("US.MU", "US.NVDA")),
        (date(2026, 7, 1), ("US.MU", "US.NVDA")),
        (date(2026, 7, 2), ("US.MU", "US.NVDA")),
        (date(2026, 7, 2), ("US.MU", "US.NVDA")),
    ]
    assert manifest.status == "PARTIAL"
    for symbol in ["US.MU", "US.NVDA"]:
        assert manifest.parameters["successful_dates_by_symbol"][symbol] == ["2026-07-01"]
        assert manifest.parameters["failed_dates_by_symbol"][symbol] == [
            {"date": "2026-07-02", "error": "Child run failed bar quality checks"}
        ]
    assert manifest.parameters["successful_item_count"] == 2
    assert manifest.parameters["failed_item_count"] == 2
    assert manifest.successful_items == []
    assert sorted(manifest.failed_items) == ["US.MU", "US.NVDA"]


def test_incremental_uses_latest_completed_date_per_symbol(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 6), date(2026, 7, 7)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 7),
    )
    write_completed_bar(cfg, code="US.MU", trade_date=date(2026, 7, 2))
    write_completed_bar(cfg, code="US.NVDA", trade_date=date(2026, 7, 6))

    plan = plan_history_backfill(
        cfg,
        symbols=["US.MU", "US.NVDA"],
        end_date=date(2026, 7, 7),
        calendar_market="US",
        incremental=True,
        today=date(2026, 8, 2),
    )

    assert plan.pending_items == [
        BackfillItem("US.MU", date(2026, 7, 6)),
        BackfillItem("US.MU", date(2026, 7, 7)),
        BackfillItem("US.NVDA", date(2026, 7, 7)),
    ]


def test_incremental_uses_next_calendar_date_not_natural_day(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 3), date(2026, 7, 6)],
        requested_start_date=date(2026, 7, 3),
        requested_end_date=date(2026, 7, 6),
    )
    write_completed_bar(cfg, code="US.MU", trade_date=date(2026, 7, 3))

    plan = plan_history_backfill(
        cfg,
        symbols=["US.MU"],
        end_date=date(2026, 7, 6),
        calendar_market="US",
        incremental=True,
        today=date(2026, 8, 2),
    )

    assert plan.pending_items == [BackfillItem("US.MU", date(2026, 7, 6))]


def test_incremental_uses_bootstrap_for_symbols_without_history(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1), date(2026, 7, 2)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 2),
    )

    plan = plan_history_backfill(
        cfg,
        symbols=["US.MU"],
        end_date=date(2026, 7, 2),
        calendar_market="US",
        incremental=True,
        bootstrap_start_date=date(2026, 7, 1),
        today=date(2026, 8, 2),
    )

    assert plan.pending_items == [
        BackfillItem("US.MU", date(2026, 7, 1)),
        BackfillItem("US.MU", date(2026, 7, 2)),
    ]


def test_incremental_requires_bootstrap_for_symbols_without_history(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 1),
    )

    manifest = collect_history_backfill(
        cfg,
        symbols=["US.MU"],
        end_date=date(2026, 7, 1),
        calendar_market="US",
        incremental=True,
        today=date(2026, 8, 2),
    )

    assert manifest.status == "FAILED"
    assert "bootstrap_start_date" in manifest.failed_items["PLAN"]


def test_incremental_does_not_backfill_gaps_before_latest_completed(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3), date(2026, 7, 6)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 6),
    )
    write_completed_bar(cfg, code="US.MU", trade_date=date(2026, 7, 3))

    plan = plan_history_backfill(
        cfg,
        symbols=["US.MU"],
        end_date=date(2026, 7, 6),
        calendar_market="US",
        incremental=True,
        today=date(2026, 8, 2),
    )

    assert plan.pending_items == [BackfillItem("US.MU", date(2026, 7, 6))]


def test_incremental_starts_at_next_trading_day_across_weekend(tmp_path):
    # Latest completed trade date is Friday 2026-07-03; the local calendar
    # snapshot only covers the requested range 2026-07-06..2026-07-07. The
    # incremental start must be the next local trading day (2026-07-06), not
    # latest + 1 natural day (2026-07-04), so no false weekend coverage gap.
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 6), date(2026, 7, 7)],
        requested_start_date=date(2026, 7, 6),
        requested_end_date=date(2026, 7, 7),
    )
    write_completed_bar(cfg, code="US.MU", trade_date=date(2026, 7, 3))

    plan = plan_history_backfill(
        cfg,
        symbols=["US.MU"],
        end_date=date(2026, 7, 7),
        calendar_market="US",
        incremental=True,
        today=date(2026, 8, 2),
    )

    assert plan.start_date_by_symbol == {"US.MU": date(2026, 7, 6)}
    assert plan.pending_items == [
        BackfillItem("US.MU", date(2026, 7, 6)),
        BackfillItem("US.MU", date(2026, 7, 7)),
    ]


def test_incremental_next_trading_day_beyond_end_date_is_empty_success(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 6)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 6),
    )
    write_completed_bar(cfg, code="US.MU", trade_date=date(2026, 7, 6))
    monkeypatch.setattr(backfill_module, "collect_history", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))

    manifest = collect_history_backfill(
        cfg,
        symbols=["US.MU"],
        end_date=date(2026, 7, 6),
        calendar_market="US",
        incremental=True,
        today=date(2026, 8, 2),
    )

    # No trading day after the latest completed date within end_date: the
    # symbol is caught up, the plan is empty, and the run is SUCCESS.
    assert manifest.status == "SUCCESS"
    assert manifest.successful_items == ["US.MU"]
    assert manifest.parameters["trading_date_count"] == 0
    assert manifest.parameters["child_run_ids"] == []
    assert manifest.parameters["successful_item_count"] == 0


def test_incremental_symbols_use_their_own_next_trading_day(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3), date(2026, 7, 6), date(2026, 7, 7)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 7),
    )
    write_completed_bar(cfg, code="US.MU", trade_date=date(2026, 7, 1))
    write_completed_bar(cfg, code="US.NVDA", trade_date=date(2026, 7, 3))

    plan = plan_history_backfill(
        cfg,
        symbols=["US.MU", "US.NVDA"],
        end_date=date(2026, 7, 7),
        calendar_market="US",
        incremental=True,
        today=date(2026, 8, 2),
    )

    # US.MU resumes on 2026-07-02; US.NVDA resumes after Friday 2026-07-03
    # on the next trading day 2026-07-06. Items are sorted by (trade_date, code).
    assert plan.start_date_by_symbol == {
        "US.MU": date(2026, 7, 2),
        "US.NVDA": date(2026, 7, 6),
    }
    assert plan.pending_items == [
        BackfillItem("US.MU", date(2026, 7, 2)),
        BackfillItem("US.MU", date(2026, 7, 3)),
        BackfillItem("US.MU", date(2026, 7, 6)),
        BackfillItem("US.NVDA", date(2026, 7, 6)),
        BackfillItem("US.MU", date(2026, 7, 7)),
        BackfillItem("US.NVDA", date(2026, 7, 7)),
    ]


def test_incremental_mixes_bootstrap_and_history_symbols(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 6), date(2026, 7, 7)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 7),
    )
    write_completed_bar(cfg, code="US.MU", trade_date=date(2026, 7, 2))

    plan = plan_history_backfill(
        cfg,
        symbols=["US.MU", "US.NVDA"],
        end_date=date(2026, 7, 7),
        calendar_market="US",
        incremental=True,
        bootstrap_start_date=date(2026, 7, 1),
        today=date(2026, 8, 2),
    )

    # US.MU has history and resumes on the next trading day 2026-07-06;
    # US.NVDA has no history and keeps the bootstrap start date 2026-07-01.
    # Items are sorted by (trade_date, code).
    assert plan.start_date_by_symbol == {
        "US.MU": date(2026, 7, 6),
        "US.NVDA": date(2026, 7, 1),
    }
    assert plan.pending_items == [
        BackfillItem("US.NVDA", date(2026, 7, 1)),
        BackfillItem("US.NVDA", date(2026, 7, 2)),
        BackfillItem("US.MU", date(2026, 7, 6)),
        BackfillItem("US.NVDA", date(2026, 7, 6)),
        BackfillItem("US.MU", date(2026, 7, 7)),
        BackfillItem("US.NVDA", date(2026, 7, 7)),
    ]


def test_range_backfill_natural_date_coverage_unchanged(tmp_path):
    # Non-incremental backfill keeps validating natural-date coverage from
    # the requested start date; starting on a weekend day still reports the
    # missing natural-date coverage instead of silently skipping it.
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 6), date(2026, 7, 7)],
        requested_start_date=date(2026, 7, 6),
        requested_end_date=date(2026, 7, 7),
    )

    with pytest.raises(ValueError, match="Missing coverage"):
        plan_history_backfill(
            cfg,
            symbols=["US.MU"],
            start_date=date(2026, 7, 4),
            end_date=date(2026, 7, 7),
            calendar_market="US",
            today=date(2026, 8, 2),
        )


def test_backfill_cli_parses_standard_mode():
    parser = build_parser()
    args = parser.parse_args(
        [
            "backfill",
            "--calendar-market",
            "US",
            "--start-date",
            "2026-07-01",
            "--end-date",
            "2026-07-31",
            "--symbols",
            "US.MU",
            "US.NVDA",
            "--interval",
            "1m",
        ]
    )

    assert args.command == "backfill"
    assert args.calendar_market == "US"
    assert args.symbols == ["US.MU", "US.NVDA"]


def test_backfill_cli_parses_incremental_mode():
    parser = build_parser()
    args = parser.parse_args(
        [
            "backfill",
            "--incremental",
            "--calendar-market",
            "US",
            "--end-date",
            "2026-07-31",
            "--bootstrap-start-date",
            "2026-01-01",
            "--symbols",
            "US.MU",
        ]
    )

    assert args.incremental is True
    assert args.bootstrap_start_date == date(2026, 1, 1)


def test_backfill_cli_rejects_calendar_scope_conflicts():
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "backfill",
                "--calendar-market",
                "US",
                "--calendar-code",
                "US.MU",
                "--end-date",
                "2026-07-31",
            ]
        )


def test_backfill_cli_rejects_negative_retry_values():
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["backfill", "--calendar-market", "US", "--end-date", "2026-07-31", "--max-retries", "-1"])
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["backfill", "--calendar-market", "US", "--end-date", "2026-07-31", "--retry-backoff-seconds", "-0.1"]
        )


def test_backfill_symbol_resolution_matches_collect_groups(monkeypatch):
    monkeypatch.setattr(cli_module, "load_universe", lambda path: {"core_universe": ["US.MU"], "trade_universe": ["US.NVDA"]})

    symbols = _resolve_symbols(
        Namespace(
            symbols=[" us.mu "],
            universe="config/universe.yaml",
            groups=["core_universe", "trade_universe"],
        )
    )

    assert symbols == [" us.mu ", "US.MU", "US.NVDA"]


def test_merge_date_ranges_merges_adjacent_ranges():
    ranges = [
        (date(2026, 7, 1), date(2026, 7, 10)),
        (date(2026, 7, 11), date(2026, 7, 31)),
    ]
    assert backfill_module.merge_date_ranges(ranges) == [(date(2026, 7, 1), date(2026, 7, 31))]


def test_merge_date_ranges_merges_overlapping_ranges():
    ranges = [
        (date(2026, 7, 5), date(2026, 7, 20)),
        (date(2026, 7, 1), date(2026, 7, 10)),
    ]
    assert backfill_module.merge_date_ranges(ranges) == [(date(2026, 7, 1), date(2026, 7, 20))]


def test_merge_date_ranges_keeps_disjoint_ranges():
    ranges = [
        (date(2026, 7, 1), date(2026, 7, 10)),
        (date(2026, 7, 12), date(2026, 7, 31)),
    ]
    assert backfill_module.merge_date_ranges(ranges) == [
        (date(2026, 7, 1), date(2026, 7, 10)),
        (date(2026, 7, 12), date(2026, 7, 31)),
    ]


def test_merge_date_ranges_empty():
    assert backfill_module.merge_date_ranges([]) == []


def test_missing_coverage_ranges_full_coverage_no_gaps():
    ranges = [(date(2026, 7, 1), date(2026, 7, 31))]
    assert backfill_module.missing_coverage_ranges(date(2026, 7, 1), date(2026, 7, 31), ranges) == []


def test_missing_coverage_ranges_finds_middle_gap():
    ranges = [
        (date(2026, 7, 1), date(2026, 7, 10)),
        (date(2026, 7, 12), date(2026, 7, 31)),
    ]
    assert backfill_module.missing_coverage_ranges(date(2026, 7, 1), date(2026, 7, 31), ranges) == [
        (date(2026, 7, 11), date(2026, 7, 11))
    ]


def test_missing_coverage_ranges_finds_head_and_tail_gaps():
    ranges = [(date(2026, 7, 3), date(2026, 7, 10))]
    assert backfill_module.missing_coverage_ranges(date(2026, 7, 1), date(2026, 7, 15), ranges) == [
        (date(2026, 7, 1), date(2026, 7, 2)),
        (date(2026, 7, 11), date(2026, 7, 15)),
    ]


def test_missing_coverage_ranges_ignores_outside_ranges():
    ranges = [
        (date(2026, 6, 1), date(2026, 6, 30)),
        (date(2026, 8, 1), date(2026, 8, 31)),
    ]
    assert backfill_module.missing_coverage_ranges(date(2026, 7, 1), date(2026, 7, 31), ranges) == [
        (date(2026, 7, 1), date(2026, 7, 31))
    ]


def test_missing_coverage_ranges_empty_coverage():
    assert backfill_module.missing_coverage_ranges(date(2026, 7, 1), date(2026, 7, 31), []) == [
        (date(2026, 7, 1), date(2026, 7, 31))
    ]


def test_resolve_calendar_scope_market_normalizes():
    assert backfill_module.resolve_calendar_scope(" us ", None) == ("MARKET", "US")


def test_resolve_calendar_scope_code_normalizes():
    assert backfill_module.resolve_calendar_scope(None, " us.mu ") == ("CODE", "US.MU")


def test_resolve_calendar_scope_rejects_both():
    with pytest.raises(ValueError, match="exactly one"):
        backfill_module.resolve_calendar_scope("US", "US.MU")


def test_resolve_calendar_scope_rejects_neither():
    with pytest.raises(ValueError, match="exactly one"):
        backfill_module.resolve_calendar_scope(None, None)


def test_market_vault_plan_backfill_wraps_plan(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 1),
    )
    write_completed_bar(cfg, code="US.MU", trade_date=date(2026, 7, 1))

    plan = MarketVault(cfg).plan_backfill(
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        calendar_market="US",
        today=date(2026, 8, 2),
    )

    assert plan.pending_items == []
    assert plan.skipped_items == [BackfillItem("US.MU", date(2026, 7, 1))]


def test_market_vault_backfill_wraps_collection(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 1),
    )
    calls, _ = make_fake_collect_history(
        cfg,
        monkeypatch,
        {(date(2026, 7, 1), ("US.MU",)): {"successful": ["US.MU"]}},
    )

    manifest = MarketVault(cfg).backfill(
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        calendar_market="US",
        today=date(2026, 8, 2),
    )

    assert calls == [(date(2026, 7, 1), ("US.MU",))]
    assert manifest.status == "SUCCESS"


def test_incremental_ignores_completed_data_beyond_end_date(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1), date(2026, 7, 2)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 2),
    )
    write_completed_bar(cfg, code="US.MU", trade_date=date(2026, 7, 1))
    write_completed_bar(cfg, code="US.MU", trade_date=date(2026, 7, 2))

    plan = plan_history_backfill(
        cfg,
        symbols=["US.MU"],
        end_date=date(2026, 7, 1),
        calendar_market="US",
        incremental=True,
        today=date(2026, 8, 2),
    )

    # The start is derived from completed data at or before end_date only;
    # data beyond end_date creates no pending work.
    assert plan.start_date_by_symbol == {"US.MU": date(2026, 7, 2)}
    assert plan.pending_items == []
    assert plan.skipped_items == []


def test_incremental_only_out_of_range_data_requires_bootstrap(tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1), date(2026, 7, 2)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 2),
    )
    write_completed_bar(cfg, code="US.MU", trade_date=date(2026, 7, 2))

    manifest = collect_history_backfill(
        cfg,
        symbols=["US.MU"],
        end_date=date(2026, 7, 1),
        calendar_market="US",
        incremental=True,
        today=date(2026, 8, 2),
    )

    assert manifest.status == "FAILED"
    assert "bootstrap_start_date" in manifest.failed_items["PLAN"]


def test_empty_plan_no_trading_dates_manifest_success(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 2),
    )
    monkeypatch.setattr(backfill_module, "collect_history", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))

    manifest = collect_history_backfill(
        cfg,
        symbols=["US.MU"],
        start_date=date(2026, 7, 2),
        end_date=date(2026, 7, 2),
        calendar_market="US",
        today=date(2026, 8, 2),
    )

    assert manifest.status == "SUCCESS"
    assert manifest.successful_items == ["US.MU"]
    assert manifest.parameters["trading_date_count"] == 0
    assert manifest.parameters["child_run_ids"] == []


def test_incremental_caught_up_to_end_date_manifest_success(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1), date(2026, 7, 2)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 2),
    )
    write_completed_bar(cfg, code="US.MU", trade_date=date(2026, 7, 2))
    monkeypatch.setattr(backfill_module, "collect_history", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))

    manifest = collect_history_backfill(
        cfg,
        symbols=["US.MU"],
        end_date=date(2026, 7, 2),
        calendar_market="US",
        incremental=True,
        today=date(2026, 8, 2),
    )

    assert manifest.status == "SUCCESS"
    assert manifest.successful_items == ["US.MU"]
    assert manifest.parameters["child_run_ids"] == []


def test_skipped_dates_recorded_in_manifest(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1), date(2026, 7, 2)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 2),
    )
    write_completed_bar(cfg, code="US.MU", trade_date=date(2026, 7, 1))
    calls, _ = make_fake_collect_history(
        cfg,
        monkeypatch,
        {(date(2026, 7, 2), ("US.MU",)): {"successful": ["US.MU"]}},
    )

    manifest = collect_history_backfill(
        cfg,
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        calendar_market="US",
        today=date(2026, 8, 2),
    )

    assert manifest.parameters["skipped_dates_by_symbol"]["US.MU"] == ["2026-07-01"]
    assert manifest.parameters["skipped_item_count"] == 1
    assert calls == [(date(2026, 7, 2), ("US.MU",))]
    assert manifest.status == "SUCCESS"


def test_mixed_nothing_to_do_and_all_failed_is_failed(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[date(2026, 7, 1)],
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 1),
    )
    write_completed_bar(cfg, code="US.MU", trade_date=date(2026, 7, 1))
    calls, _ = make_fake_collect_history(
        cfg,
        monkeypatch,
        {(date(2026, 7, 1), ("US.NVDA",)): {"failed": {"US.NVDA": "boom"}}},
    )

    manifest = collect_history_backfill(
        cfg,
        symbols=["US.MU", "US.NVDA"],
        end_date=date(2026, 7, 1),
        calendar_market="US",
        incremental=True,
        bootstrap_start_date=date(2026, 7, 1),
        force=True,
        max_retries=0,
        retry_backoff_seconds=0,
        today=date(2026, 8, 2),
    )

    # US.MU is caught up (nothing to do) while US.NVDA failed everything:
    # the run is FAILED even though successful_items lists US.MU.
    assert manifest.status == "FAILED"
    assert manifest.successful_items == ["US.MU"]
    assert list(manifest.failed_items) == ["US.NVDA"]
    assert calls == [(date(2026, 7, 1), ("US.NVDA",))]


def fake_plan_for_capture(settings, **kwargs) -> BackfillPlan:
    return BackfillPlan(
        symbols=kwargs["symbols"],
        trading_dates=[],
        pending_items=[],
        skipped_items=[],
        calendar_scope_type="MARKET",
        calendar_scope_value="US",
    )


def fake_collect_for_capture(settings, **kwargs) -> DatasetRunManifest:
    manifest = DatasetRunManifest(
        dataset="market_bars_backfill",
        requested_items=kwargs["symbols"],
        parameters={},
    )
    manifest.status = "SUCCESS"
    manifest.successful_items = list(kwargs["symbols"])
    return manifest


def test_market_vault_plan_backfill_uses_settings_defaults(monkeypatch, tmp_path):
    cfg = replace(settings(tmp_path), default_session="RTH", default_adjustment="QFQ")
    captured = {}
    monkeypatch.setattr(
        api_module,
        "plan_history_backfill",
        lambda settings, **kwargs: captured.update(kwargs) or fake_plan_for_capture(settings, **kwargs),
    )

    MarketVault(cfg).plan_backfill(
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
        calendar_market="US",
    )

    assert captured["session"] == "RTH"
    assert captured["adjustment"] == "QFQ"


def test_market_vault_backfill_uses_settings_defaults(monkeypatch, tmp_path):
    cfg = replace(settings(tmp_path), default_session="RTH", default_adjustment="QFQ")
    captured = {}
    monkeypatch.setattr(
        api_module,
        "collect_history_backfill",
        lambda settings, **kwargs: captured.update(kwargs) or fake_collect_for_capture(settings, **kwargs),
    )

    MarketVault(cfg).backfill(
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
        calendar_market="US",
    )

    assert captured["session"] == "RTH"
    assert captured["adjustment"] == "QFQ"


def test_market_vault_plan_backfill_explicit_overrides_settings_defaults(monkeypatch, tmp_path):
    cfg = replace(settings(tmp_path), default_session="RTH", default_adjustment="QFQ")
    captured = {}
    monkeypatch.setattr(
        api_module,
        "plan_history_backfill",
        lambda settings, **kwargs: captured.update(kwargs) or fake_plan_for_capture(settings, **kwargs),
    )

    MarketVault(cfg).plan_backfill(
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
        calendar_market="US",
        session="ALL",
        adjustment="NONE",
    )

    assert captured["session"] == "ALL"
    assert captured["adjustment"] == "NONE"


def test_market_vault_backfill_explicit_overrides_settings_defaults(monkeypatch, tmp_path):
    cfg = replace(settings(tmp_path), default_session="RTH", default_adjustment="QFQ")
    captured = {}
    monkeypatch.setattr(
        api_module,
        "collect_history_backfill",
        lambda settings, **kwargs: captured.update(kwargs) or fake_collect_for_capture(settings, **kwargs),
    )

    MarketVault(cfg).backfill(
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
        calendar_market="US",
        session="ALL",
        adjustment="NONE",
    )

    assert captured["session"] == "ALL"
    assert captured["adjustment"] == "NONE"


def test_market_vault_backfill_passes_through_options(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    captured = {}
    monkeypatch.setattr(
        api_module,
        "collect_history_backfill",
        lambda settings, **kwargs: captured.update(kwargs) or fake_collect_for_capture(settings, **kwargs),
    )

    MarketVault(cfg).backfill(
        symbols=["US.MU"],
        end_date=date(2026, 7, 31),
        calendar_market="US",
        incremental=True,
        bootstrap_start_date=date(2026, 1, 1),
        max_retries=5,
        retry_backoff_seconds=1.5,
        force=True,
        today=date(2026, 8, 2),
    )

    assert captured["max_retries"] == 5
    assert captured["retry_backoff_seconds"] == 1.5
    assert captured["force"] is True
    assert captured["incremental"] is True
    assert captured["bootstrap_start_date"] == date(2026, 1, 1)
    assert captured["today"] == date(2026, 8, 2)
