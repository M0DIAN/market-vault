from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import market_vault.cli as cli_module
from market_vault import MarketVault
from market_vault.audit import run_inventory
from market_vault.console.backend import ConsoleBackend
from market_vault.models import Settings
from market_vault.normalization import (
    MOOMOO_TIMESTAMP_SEMANTICS_V2_SCHEMA,
    normalize_bars,
)
from market_vault.storage import Catalog, ParquetStore


TRADE_DATE = date(2026, 8, 20)
NY = "America/New_York"


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=tmp_path,
        opend_host="127.0.0.1",
        opend_port=1,
        data_root=tmp_path / "data",
        catalog_path=tmp_path / "catalog" / "market_vault.duckdb",
        manifest_dir=tmp_path / "manifests",
        report_dir=tmp_path / "reports",
        source="moomoo",
        source_schema_version=MOOMOO_TIMESTAMP_SEMANTICS_V2_SCHEMA,
        request_pause_seconds=0,
    )


def _provider_times(requested_session: str) -> list[pd.Timestamp]:
    if requested_session == "RTH":
        return list(
            pd.date_range(
                f"{TRADE_DATE.isoformat()} 09:31:00",
                f"{TRADE_DATE.isoformat()} 16:00:00",
                freq="min",
                tz=NY,
            )
        )
    return list(
        pd.date_range(
            f"{TRADE_DATE.isoformat()} 00:00:00",
            f"{TRADE_DATE.isoformat()} 23:59:00",
            freq="min",
            tz=NY,
        )
    )


def _write_snapshot(
    cfg: Settings,
    *,
    requested_session: str,
    run_id: str,
    ingested_at: str,
    close_offset: float = 0.0,
) -> Path:
    times = _provider_times(requested_session)
    count = len(times)
    raw = pd.DataFrame(
        {
            "code": ["US.SPY"] * count,
            "name": ["SPY"] * count,
            "time_key": [value.strftime("%Y-%m-%d %H:%M:%S") for value in times],
            "open": [100.0 + close_offset] * count,
            "high": [101.0 + close_offset] * count,
            "low": [99.0 + close_offset] * count,
            "close": [100.5 + close_offset] * count,
            "volume": list(range(1, count + 1)),
        }
    )
    curated = normalize_bars(
        raw,
        requested_trade_date=TRADE_DATE,
        interval="1m",
        requested_session=requested_session,
        adjustment="NONE",
        source=cfg.source,
        source_schema_version=cfg.source_schema_version,
        run_id=run_id,
    )
    curated["ingested_at"] = pd.Timestamp(ingested_at)
    return ParquetStore(cfg).write_curated(
        curated,
        TRADE_DATE,
        "1m",
        ["US.SPY"],
        requested_session,
        "NONE",
        run_id,
    )


def _counts(catalog: Catalog, view: str) -> dict[str, int]:
    with catalog.connect() as con:
        rows = con.execute(
            f"""
            SELECT requested_session, COUNT(*)
            FROM {view}
            GROUP BY requested_session
            ORDER BY requested_session
            """
        ).fetchall()
    return {str(session): int(count) for session, count in rows}


def test_requested_sessions_coexist_in_current_view_and_queries_fail_closed(
    tmp_path: Path,
) -> None:
    cfg = _settings(tmp_path)
    Catalog(cfg).initialize()
    _write_snapshot(
        cfg,
        requested_session="RTH",
        run_id="run-rth",
        ingested_at="2026-08-21T00:00:00Z",
    )
    _write_snapshot(
        cfg,
        requested_session="ALL",
        run_id="run-all",
        ingested_at="2026-08-21T00:00:00Z",
    )
    catalog = Catalog(cfg)
    assert catalog.refresh_market_bars_view()
    assert _counts(catalog, "market_bars_snapshots") == {"ALL": 1440, "RTH": 390}
    assert _counts(catalog, "market_bars") == {"ALL": 1440, "RTH": 390}

    vault = MarketVault(cfg)
    with pytest.raises(ValueError, match="specify requested_session explicitly"):
        vault.load_bars(
            "US.SPY",
            trade_date=TRADE_DATE,
            interval="1m",
            session="REGULAR",
        )
    with pytest.raises(ValueError, match="specify requested_session explicitly"):
        vault.load_bars_page(
            code="US.SPY",
            start_date=TRADE_DATE,
            end_date=TRADE_DATE,
            interval="1m",
            bar_session="REGULAR",
        )

    rth = vault.load_bars(
        "US.SPY",
        trade_date=TRADE_DATE,
        requested_session="rth",
    )
    all_rows = vault.load_bars(
        "US.SPY",
        trade_date=TRADE_DATE,
        requested_session="all",
    )
    assert len(rth) == 390
    assert len(all_rows) == 1440
    assert len(
        vault.load_bars(
            "US.SPY",
            trade_date=TRADE_DATE,
            requested_session="RTH",
            session="REGULAR",
        )
    ) == 390
    assert len(
        vault.load_bars(
            "US.SPY",
            trade_date=TRADE_DATE,
            requested_session="ALL",
            session="REGULAR",
        )
    ) == 390

    rth_page = vault.load_bars_page(
        code="US.SPY",
        start_date=TRADE_DATE,
        end_date=TRADE_DATE,
        requested_session="RTH",
        page_size=1000,
    )
    all_page = vault.load_bars_page(
        code="US.SPY",
        start_date=TRADE_DATE,
        end_date=TRADE_DATE,
        requested_session="ALL",
        page_size=1000,
    )
    assert rth_page.total_rows == 390
    assert all_page.total_rows == 1440

    inventory = run_inventory(cfg, persist_report=False)
    assert inventory.summary.latest_query_row_count == 1830
    dashboard = ConsoleBackend(vault).dashboard()
    assert dashboard.metrics["Latest rows"] == "1830"


def test_same_requested_session_latest_wins_by_ingested_at(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    _write_snapshot(
        cfg,
        requested_session="RTH",
        run_id="run-old",
        ingested_at="2026-08-21T00:00:00Z",
        close_offset=0.0,
    )
    _write_snapshot(
        cfg,
        requested_session="RTH",
        run_id="run-new",
        ingested_at="2026-08-22T00:00:00Z",
        close_offset=50.0,
    )
    catalog = Catalog(cfg)
    assert catalog.refresh_market_bars_view()
    assert _counts(catalog, "market_bars_snapshots") == {"RTH": 780}
    current = MarketVault(cfg).load_bars(
        "US.SPY",
        trade_date=TRADE_DATE,
        requested_session="RTH",
    )
    assert len(current) == 390
    assert set(current["ingestion_run_id"]) == {"run-new"}
    assert set(current["close"]) == {150.5}


def test_equal_ingested_at_uses_run_id_only_as_deterministic_tiebreak(
    tmp_path: Path,
) -> None:
    cfg = _settings(tmp_path)
    for run_id, close_offset in (("run-a", 0.0), ("run-b", 25.0)):
        _write_snapshot(
            cfg,
            requested_session="RTH",
            run_id=run_id,
            ingested_at="2026-08-21T00:00:00Z",
            close_offset=close_offset,
        )
    current = MarketVault(cfg).load_bars(
        "US.SPY",
        trade_date=TRADE_DATE,
        requested_session="RTH",
    )
    assert len(current) == 390
    assert set(current["ingestion_run_id"]) == {"run-b"}
    assert set(current["close"]) == {125.5}


def test_current_view_refresh_refuses_indistinguishable_duplicate_evidence(
    tmp_path: Path,
) -> None:
    cfg = _settings(tmp_path)
    path = _write_snapshot(
        cfg,
        requested_session="RTH",
        run_id="run-duplicate",
        ingested_at="2026-08-21T00:00:00Z",
    )
    original = pd.read_parquet(path)
    pd.concat([original, original], ignore_index=True).to_parquet(path, index=False)

    catalog = Catalog(cfg)
    assert catalog.refresh_market_bars_view() is False
    with catalog.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM market_bars_snapshots").fetchone()[0] == 780


def test_single_requested_session_preserves_unscoped_api_compatibility(
    tmp_path: Path,
) -> None:
    cfg = _settings(tmp_path)
    _write_snapshot(
        cfg,
        requested_session="RTH",
        run_id="run-rth",
        ingested_at="2026-08-21T00:00:00Z",
    )
    vault = MarketVault(cfg)
    assert len(
        vault.load_bars(
            "US.SPY",
            trade_date=TRADE_DATE,
            session="REGULAR",
        )
    ) == 390
    assert (
        vault.load_bars_page(
            code="US.SPY",
            start_date=TRADE_DATE,
            end_date=TRADE_DATE,
            bar_session="REGULAR",
            page_size=1000,
        ).total_rows
        == 390
    )
    assert vault.load_bars("US.QQQ", trade_date=TRADE_DATE).empty


def test_query_cli_separates_request_and_bar_sessions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = _settings(tmp_path)
    monkeypatch.setattr(cli_module, "load_settings", lambda _path: cfg)
    _write_snapshot(
        cfg,
        requested_session="RTH",
        run_id="run-rth",
        ingested_at="2026-08-21T00:00:00Z",
    )

    assert cli_module.main(["query", "--code", "US.SPY", "--session", "regular"]) == 0
    capsys.readouterr()
    assert (
        cli_module.main(
            [
                "query",
                "--code",
                "US.SPY",
                "--requested-session",
                "rth",
                "--bar-session",
                "regular",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        cli_module.main(
            [
                "query",
                "--code",
                "US.SPY",
                "--requested-session",
                "RTH",
                "--session",
                "REGULAR",
                "--bar-session",
                "REGULAR",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert (
        cli_module.main(
            [
                "query",
                "--code",
                "US.SPY",
                "--session",
                "REGULAR",
                "--bar-session",
                "AFTER_HOURS",
            ]
        )
        == 2
    )
    assert "must match" in capsys.readouterr().err

    _write_snapshot(
        cfg,
        requested_session="ALL",
        run_id="run-all",
        ingested_at="2026-08-21T00:00:00Z",
    )
    assert cli_module.main(["query", "--code", "US.SPY", "--session", "REGULAR"]) == 2
    assert "specify requested_session explicitly" in capsys.readouterr().err
