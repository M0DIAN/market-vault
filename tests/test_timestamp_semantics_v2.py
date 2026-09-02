from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import market_vault.service as service_module
from market_vault import MarketVault
from market_vault.audit import run_inventory
from market_vault.console.backend import ConsoleBackend
from market_vault.models import Settings
from market_vault.normalization import (
    MOOMOO_TIMESTAMP_SEMANTICS_V2_SCHEMA,
    market_session_label,
    normalize_bars,
)
from market_vault.storage import Catalog, ParquetStore


TRADE_DATE = date(2026, 8, 20)
NY = "America/New_York"


def settings(tmp_path: Path, schema: str = MOOMOO_TIMESTAMP_SEMANTICS_V2_SCHEMA) -> Settings:
    return Settings(
        project_root=tmp_path,
        opend_host="127.0.0.1",
        opend_port=11111,
        data_root=tmp_path / "data",
        catalog_path=tmp_path / "catalog" / "market_vault.duckdb",
        manifest_dir=tmp_path / "manifests",
        report_dir=tmp_path / "reports",
        source="moomoo",
        source_schema_version=schema,
        request_pause_seconds=0,
    )


def provider_times(interval: str, session: str) -> list[pd.Timestamp]:
    midnight = pd.Timestamp(f"{TRADE_DATE.isoformat()} 00:00:00", tz=NY)
    regular_open = pd.Timestamp(f"{TRADE_DATE.isoformat()} 09:30:00", tz=NY)
    regular_close = pd.Timestamp(f"{TRADE_DATE.isoformat()} 16:00:00", tz=NY)
    minutes = int(interval.removesuffix("m"))
    if session == "RTH":
        if interval == "60m":
            return [
                pd.Timestamp(f"{TRADE_DATE.isoformat()} {clock}:00", tz=NY)
                for clock in (
                    "10:30",
                    "11:30",
                    "12:30",
                    "13:30",
                    "14:30",
                    "15:30",
                    "16:00",
                )
            ]
        return list(
            pd.date_range(
                regular_open + pd.Timedelta(minutes, unit="m"),
                regular_close,
                freq=f"{minutes}min",
            )
        )
    if interval == "60m":
        clocks = [
            *(f"{hour:02d}:00" for hour in range(0, 10)),
            "09:30",
            "10:30",
            "11:30",
            "12:30",
            "13:30",
            "14:30",
            "15:30",
            *(f"{hour:02d}:00" for hour in range(16, 24)),
        ]
        return [
            pd.Timestamp(f"{TRADE_DATE.isoformat()} {clock}:00", tz=NY)
            for clock in clocks
        ]
    return list(
        pd.date_range(
            midnight,
            midnight + pd.Timedelta(1, unit="D"),
            freq=f"{minutes}min",
            inclusive="left",
        )
    )


def canonical_times(interval: str, session: str) -> list[pd.Timestamp]:
    provider = provider_times(interval, session)
    if session == "ALL":
        return provider
    regular_open = pd.Timestamp(f"{TRADE_DATE.isoformat()} 09:30:00", tz=NY)
    return [regular_open, *provider[:-1]]


def raw_frame(times: list[pd.Timestamp], code: str = "US.SPY") -> pd.DataFrame:
    count = len(times)
    return pd.DataFrame(
        {
            "code": [code] * count,
            "name": [code] * count,
            "time_key": [value.strftime("%Y-%m-%d %H:%M:%S") for value in times],
            "open": [100.0 + index for index in range(count)],
            "high": [101.0 + index for index in range(count)],
            "low": [99.0 + index for index in range(count)],
            "close": [100.5 + index for index in range(count)],
            "volume": [1000 + index for index in range(count)],
        }
    )


def normalize(
    frame: pd.DataFrame,
    *,
    interval: str,
    session: str,
    schema: str = MOOMOO_TIMESTAMP_SEMANTICS_V2_SCHEMA,
    source: str = "moomoo",
    run_id: str = "run-ts2",
) -> pd.DataFrame:
    return normalize_bars(
        frame,
        requested_trade_date=TRADE_DATE,
        interval=interval,
        requested_session=session,
        adjustment="NONE",
        source=source,
        source_schema_version=schema,
        run_id=run_id,
    )


@pytest.mark.parametrize(
    ("session", "interval", "expected_rows", "expected_sessions"),
    [
        ("RTH", "1m", 390, {"REGULAR": 390}),
        ("RTH", "5m", 78, {"REGULAR": 78}),
        ("RTH", "15m", 26, {"REGULAR": 26}),
        ("RTH", "30m", 13, {"REGULAR": 13}),
        ("RTH", "60m", 7, {"REGULAR": 7}),
        ("ALL", "1m", 1440, {"OVERNIGHT": 480, "PRE_MARKET": 330, "REGULAR": 390, "AFTER_HOURS": 240}),
        ("ALL", "5m", 288, {"OVERNIGHT": 96, "PRE_MARKET": 66, "REGULAR": 78, "AFTER_HOURS": 48}),
        ("ALL", "15m", 96, {"OVERNIGHT": 32, "PRE_MARKET": 22, "REGULAR": 26, "AFTER_HOURS": 16}),
        ("ALL", "30m", 48, {"OVERNIGHT": 16, "PRE_MARKET": 11, "REGULAR": 13, "AFTER_HOURS": 8}),
        ("ALL", "60m", 25, {"OVERNIGHT": 8, "PRE_MARKET": 6, "REGULAR": 7, "AFTER_HOURS": 4}),
    ],
)
def test_verified_moomoo_ts2_intraday_matrix(
    session: str,
    interval: str,
    expected_rows: int,
    expected_sessions: dict[str, int],
) -> None:
    provider = provider_times(interval, session)
    original = raw_frame(provider)
    curated = normalize(original, interval=interval, session=session)

    assert len(curated) == len(original) == expected_rows
    assert curated["time_key"].tolist() == original["time_key"].tolist()
    assert curated["time_market"].tolist() == canonical_times(interval, session)
    assert curated["time_utc"].tolist() == [
        value.tz_convert("UTC") for value in canonical_times(interval, session)
    ]
    assert set(curated["market_calendar_date"]) == {TRADE_DATE}
    assert curated["session"].value_counts().to_dict() == expected_sessions
    assert set(curated["source_schema_version"]) == {
        MOOMOO_TIMESTAMP_SEMANTICS_V2_SCHEMA
    }
    pd.testing.assert_frame_equal(
        curated[["open", "high", "low", "close", "volume"]].reset_index(drop=True),
        original[["open", "high", "low", "close", "volume"]].reset_index(drop=True),
        check_dtype=False,
    )


def test_rth_60m_pins_truncated_final_interval_sequence() -> None:
    provider = provider_times("60m", "RTH")
    curated = normalize(raw_frame(provider), interval="60m", session="RTH")
    assert [value.strftime("%H:%M") for value in provider] == [
        "10:30",
        "11:30",
        "12:30",
        "13:30",
        "14:30",
        "15:30",
        "16:00",
    ]
    assert curated["time_market"].dt.strftime("%H:%M").tolist() == [
        "09:30",
        "10:30",
        "11:30",
        "12:30",
        "13:30",
        "14:30",
        "15:30",
    ]


def test_legacy_109_normalization_remains_provider_labeled() -> None:
    provider = provider_times("1m", "RTH")
    original = raw_frame(provider)
    curated = normalize(original, interval="1m", session="RTH", schema="10.9")
    assert curated["time_key"].tolist() == original["time_key"].tolist()
    assert curated["time_market"].tolist() == provider
    assert curated.iloc[-1]["session"] == "AFTER_HOURS"
    assert len(curated) == 390


def test_ts2_does_not_change_daily_timestamp_semantics() -> None:
    frame = raw_frame([pd.Timestamp(f"{TRADE_DATE.isoformat()} 00:00:00", tz=NY)])
    curated = normalize(frame, interval="day", session="RTH")
    assert curated.iloc[0]["time_market"] == pd.Timestamp(
        f"{TRADE_DATE.isoformat()} 00:00:00", tz=NY
    )
    assert curated.iloc[0]["time_key"] == f"{TRADE_DATE.isoformat()} 00:00:00"


def test_true_canonical_1600_remains_after_hours() -> None:
    assert (
        market_session_label(pd.Timestamp(f"{TRADE_DATE.isoformat()} 16:00:00", tz=NY))
        == "AFTER_HOURS"
    )


@pytest.mark.parametrize(
    ("interval", "session", "source", "times", "message"),
    [
        ("2m", "RTH", "moomoo", ["10:00"], "Unsupported.*interval"),
        ("1m", "ETH", "moomoo", ["10:00"], "Unsupported.*requested_session"),
        ("1m", "RTH", "other", ["10:00"], "requires source='moomoo'"),
        ("60m", "RTH", "moomoo", ["10:30", "11:30", "12:30", "13:30", "14:30", "15:30"], "geometry mismatch"),
        ("60m", "RTH", "moomoo", ["10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "15:45"], "geometry mismatch"),
        ("60m", "RTH", "moomoo", ["10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "15:30"], "duplicate"),
        ("60m", "RTH", "moomoo", ["10:30", "11:30", "12:30", "14:30", "13:30", "15:30", "16:00"], "non-monotonic"),
    ],
)
def test_ts2_rejects_unsupported_or_ambiguous_geometry(
    interval: str,
    session: str,
    source: str,
    times: list[str],
    message: str,
) -> None:
    frame = raw_frame(
        [
            pd.Timestamp(f"{TRADE_DATE.isoformat()} {clock}:00", tz=NY)
            for clock in times
        ]
    )
    with pytest.raises(ValueError, match=message):
        normalize(frame, interval=interval, session=session, source=source)


def test_ts2_rejects_unverified_early_close_geometry() -> None:
    frame = raw_frame(provider_times("1m", "RTH")[:-30])
    with pytest.raises(ValueError, match="geometry mismatch"):
        normalize(frame, interval="1m", session="RTH")


class InvalidGeometryCollector:
    def __init__(self, _settings: Settings):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def fetch_history(self, **_kwargs) -> pd.DataFrame:
        return raw_frame(provider_times("60m", "RTH")[:-1])


def test_service_does_not_publish_normalization_failure(monkeypatch, tmp_path: Path) -> None:
    cfg = settings(tmp_path)
    monkeypatch.setattr(service_module, "MoomooHistoryCollector", InvalidGeometryCollector)
    manifest = service_module.collect_history(
        cfg,
        trade_date=TRADE_DATE,
        symbols=["US.SPY"],
        interval="60m",
        session="RTH",
        adjustment="NONE",
    )

    assert manifest.status == "FAILED"
    assert manifest.snapshot_binding_mode == "REGISTERED_PER_SYMBOL"
    assert manifest.successful_symbols == []
    assert manifest.snapshot_pairs == []
    assert manifest.raw_file is None
    assert manifest.curated_file is None
    assert "geometry mismatch" in manifest.failed_symbols["US.SPY"]
    assert list(cfg.data_root.rglob("*.parquet")) == []
    catalog = Catalog(cfg)
    assert catalog.market_bar_snapshot_pair_count(manifest.run_id) == 0
    assert catalog.completed_market_bar_items(
        symbols=["US.SPY"],
        trade_dates=[TRADE_DATE],
        interval="60m",
        requested_session="RTH",
        adjustment="NONE",
        source_schema_version=MOOMOO_TIMESTAMP_SEMANTICS_V2_SCHEMA,
    ) == set()


def _write_cohort(
    cfg: Settings,
    *,
    schema: str,
    run_id: str,
) -> tuple[Path, Path]:
    provider = provider_times("1m", "RTH")
    raw = raw_frame(provider)
    raw["requested_trade_date"] = TRADE_DATE
    raw["interval"] = "1m"
    raw["requested_session"] = "RTH"
    raw["adjustment"] = "NONE"
    raw["ingestion_run_id"] = run_id
    curated = normalize(
        raw,
        interval="1m",
        session="RTH",
        schema=schema,
        run_id=run_id,
    )
    store = ParquetStore(cfg)
    return (
        store.write_raw(raw, TRADE_DATE, "1m", ["US.SPY"], "RTH", "NONE", run_id),
        store.write_curated(
            curated,
            TRADE_DATE,
            "1m",
            ["US.SPY"],
            "RTH",
            "NONE",
            run_id,
        ),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_mixed_archive_isolates_current_view_query_inventory_and_dashboard(tmp_path: Path) -> None:
    cfg_ts2 = settings(tmp_path)
    Catalog(cfg_ts2).initialize()
    legacy_paths = _write_cohort(cfg_ts2, schema="10.9", run_id="run-legacy")
    _write_cohort(
        cfg_ts2,
        schema=MOOMOO_TIMESTAMP_SEMANTICS_V2_SCHEMA,
        run_id="run-ts2",
    )
    legacy_hashes = {path: _sha256(path) for path in legacy_paths}

    vault_ts2 = MarketVault(cfg_ts2)
    assert vault_ts2.catalog.refresh_market_bars_view()
    with vault_ts2.catalog.connect() as con:
        archive_rows = con.execute("SELECT COUNT(*) FROM market_bars_snapshots").fetchone()[0]
        current_rows = con.execute("SELECT COUNT(*) FROM market_bars").fetchone()[0]
        archive_1600 = con.execute(
            "SELECT COUNT(*) FROM market_bars_snapshots "
            "WHERE source_schema_version = '10.9' "
            "AND strftime(time_market AT TIME ZONE 'America/New_York', '%H:%M') = '16:00'"
        ).fetchone()[0]
        current_1600 = con.execute(
            "SELECT COUNT(*) FROM market_bars "
            "WHERE strftime(time_market AT TIME ZONE 'America/New_York', '%H:%M') = '16:00'"
        ).fetchone()[0]
    assert (archive_rows, current_rows, archive_1600, current_1600) == (780, 390, 1, 0)

    loaded = vault_ts2.load_bars(
        "US.SPY",
        trade_date=TRADE_DATE,
        interval="1m",
        session="REGULAR",
        adjustment="NONE",
    )
    page = vault_ts2.load_bars_page(
        code="US.SPY",
        start_date=TRADE_DATE,
        end_date=TRADE_DATE,
        interval="1m",
        requested_session="RTH",
        bar_session="REGULAR",
        adjustment="NONE",
        page_size=1000,
    )
    assert len(loaded) == page.total_rows == len(page.data) == 390
    assert loaded["time_market"].dt.tz_convert(NY).dt.strftime("%H:%M").iloc[
        [0, -1]
    ].tolist() == [
        "09:30",
        "15:59",
    ]

    archive_inventory = run_inventory(cfg_ts2, persist_report=False)
    assert {item.source_schema_version for item in archive_inventory.items} == {
        "10.9",
        MOOMOO_TIMESTAMP_SEMANTICS_V2_SCHEMA,
    }
    assert archive_inventory.summary.snapshot_row_count == 780
    assert archive_inventory.summary.latest_query_row_count == 390
    ts2_inventory = run_inventory(
        cfg_ts2,
        source_schema_version=MOOMOO_TIMESTAMP_SEMANTICS_V2_SCHEMA,
        persist_report=False,
    )
    assert len(ts2_inventory.items) == 1
    assert ts2_inventory.items[0].snapshot_row_count == 390

    dashboard = ConsoleBackend(vault_ts2).dashboard()
    assert dashboard.metrics["Symbols"] == "1"
    assert dashboard.metrics["Snapshots"] == "1"
    assert dashboard.metrics["Latest rows"] == "390"

    cfg_legacy = replace(cfg_ts2, source_schema_version="10.9")
    vault_legacy = MarketVault(cfg_legacy)
    assert vault_legacy.catalog.refresh_market_bars_view()
    legacy = vault_legacy.load_bars(
        "US.SPY",
        trade_date=TRADE_DATE,
        interval="1m",
        adjustment="NONE",
    )
    assert len(legacy) == 390
    assert legacy["time_market"].dt.tz_convert(NY).dt.strftime("%H:%M").iloc[
        [0, -1]
    ].tolist() == [
        "09:31",
        "16:00",
    ]
    assert {path: _sha256(path) for path in legacy_paths} == legacy_hashes


def test_schema_less_archive_rows_are_not_promoted_to_current_cohort(tmp_path: Path) -> None:
    cfg = settings(tmp_path)
    Catalog(cfg).initialize()
    _write_cohort(
        cfg,
        schema=MOOMOO_TIMESTAMP_SEMANTICS_V2_SCHEMA,
        run_id="run-ts2",
    )
    schema_less = normalize(
        raw_frame([pd.Timestamp(f"{TRADE_DATE.isoformat()} 08:00:00", tz=NY)]),
        interval="day",
        session="ALL",
        schema="10.9",
        run_id="run-schema-less",
    ).drop(columns=["source_schema_version"])
    ParquetStore(cfg).write_curated(
        schema_less,
        TRADE_DATE,
        "day",
        ["US.SPY"],
        "ALL",
        "NONE",
        "run-schema-less",
    )
    catalog = Catalog(cfg)
    assert catalog.refresh_market_bars_view()
    with catalog.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM market_bars_snapshots").fetchone()[0] == 391
        assert con.execute("SELECT COUNT(*) FROM market_bars").fetchone()[0] == 390
        assert con.execute(
            "SELECT COUNT(*) FROM market_bars_snapshots WHERE source_schema_version IS NULL"
        ).fetchone()[0] == 1


def test_entirely_schema_less_archive_produces_empty_current_view(tmp_path: Path) -> None:
    cfg = settings(tmp_path)
    frame = normalize(
        raw_frame([pd.Timestamp(f"{TRADE_DATE.isoformat()} 00:00:00", tz=NY)]),
        interval="day",
        session="ALL",
        schema="10.9",
    ).drop(columns=["source_schema_version"])
    ParquetStore(cfg).write_curated(
        frame,
        TRADE_DATE,
        "day",
        ["US.SPY"],
        "ALL",
        "NONE",
        "run-schema-less",
    )
    cfg.catalog_path.parent.mkdir(parents=True)
    catalog = Catalog(cfg)
    assert catalog.refresh_market_bars_view()
    with catalog.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM market_bars_snapshots").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM market_bars").fetchone()[0] == 0


def test_current_view_sql_literals_are_exact_escaped_and_nonblank() -> None:
    assert Catalog._sql_string_literal("moo'moo", "source") == "'moo''moo'"
    assert Catalog._sql_string_literal("10.9%_", "schema") == "'10.9%_'"
    with pytest.raises(ValueError, match="cannot be blank"):
        Catalog._sql_string_literal("  ", "schema")
