from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

import market_vault.service as service_module
from market_vault.models import Settings
from market_vault.normalization import (
    bar_available_at,
    normalize_bars,
    parse_market_time_key,
)
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


def raw_frame(codes: list[str], time_keys: list[str]) -> pd.DataFrame:
    rows = []
    for code in codes:
        for time_key in time_keys:
            rows.append(
                {
                    "code": code,
                    "name": code,
                    "time_key": time_key,
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 100,
                }
            )
    return pd.DataFrame(rows)


def normalize(cfg: Settings, codes: list[str], time_keys: list[str]) -> pd.DataFrame:
    return normalize_bars(
        raw_frame(codes, time_keys),
        requested_trade_date=date(2026, 7, 1),
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source=cfg.source,
        source_schema_version=cfg.source_schema_version,
        run_id="run-a",
    )


# --- time_key interval interpretation ---------------------------------------


def test_time_key_parsed_as_whole_minute_market_time(tmp_path):
    cfg = settings(tmp_path)
    times = ["2026-07-01 09:30:00", "2026-07-01 09:31:00"]
    parsed = parse_market_time_key(pd.Series(times))
    assert parsed.dt.tz is not None
    assert str(parsed.dt.tz) == NY
    assert parsed.dt.second.tolist() == [0, 0]
    assert parsed.dt.microsecond.tolist() == [0, 0]
    assert parsed.iloc[0] == pd.Timestamp("2026-07-01 09:30:00", tz=NY)


def test_time_key_preserves_consecutive_market_instants(tmp_path):
    # Pins MarketVault's normalization behavior on synthetic fixtures; it
    # does not claim to validate external OpenD time_key semantics.
    cfg = settings(tmp_path)
    curated = normalize(cfg, ["US.MU"], ["2026-07-01 09:30:00", "2026-07-01 09:31:00"])
    deltas = curated["time_market"].diff().dropna()
    assert (deltas == pd.Timedelta(minutes=1)).all()
    assert curated["time_market"].iloc[0] == pd.Timestamp("2026-07-01 09:30:00", tz=NY)


def test_time_key_aware_input_converted_to_market_time(tmp_path):
    cfg = settings(tmp_path)
    parsed = parse_market_time_key(pd.Series([pd.Timestamp("2026-07-01 13:30:00", tz="UTC")]))
    assert parsed.iloc[0] == pd.Timestamp("2026-07-01 09:30:00", tz=NY)


# --- market_available_at ----------------------------------------------------


def test_bar_available_at_is_interval_end_in_utc():
    market_time = pd.Timestamp("2026-07-01 09:30:00", tz=NY)
    assert bar_available_at(market_time, 60) == pd.Timestamp("2026-07-01 13:31:00", tz="UTC")
    assert bar_available_at(market_time, 300) == pd.Timestamp("2026-07-01 13:35:00", tz="UTC")
    assert bar_available_at(market_time, 3600) == pd.Timestamp("2026-07-01 14:30:00", tz="UTC")


def test_market_available_at_consistent_with_normalized_event_time(tmp_path):
    cfg = settings(tmp_path)
    curated = normalize(cfg, ["US.MU"], ["2026-07-01 09:30:00"])
    event_time = curated["time_market"].iloc[0].tz_convert("UTC")
    assert bar_available_at(curated["time_market"].iloc[0], 60) == event_time + pd.Timedelta(minutes=1)


# --- UTC / NY conversion and DST --------------------------------------------


@pytest.mark.parametrize(
    ("market_time", "expected_utc"),
    [
        ("2026-01-15 09:30:00", "2026-01-15 14:30:00+00:00"),  # EST -05:00
        ("2026-07-01 09:30:00", "2026-07-01 13:30:00+00:00"),  # EDT -04:00
    ],
)
def test_utc_conversion_across_seasons(market_time, expected_utc):
    parsed = parse_market_time_key(pd.Series([market_time])).iloc[0]
    assert parsed.tz_convert("UTC") == pd.Timestamp(expected_utc)


def test_nonexistent_dst_time_raises():
    with pytest.raises(Exception):
        parse_market_time_key(pd.Series(["2026-03-08 02:30:00"]))


def test_ambiguous_dst_time_raises():
    with pytest.raises(Exception):
        parse_market_time_key(pd.Series(["2026-11-01 01:30:00"]))


def test_dst_transition_dates_convert_correctly():
    # 2026-03-08 03:30 EDT exists; 2026-11-01 01:30 EST exists via zoneinfo's
    # default fold only if disambiguated -- naive input must raise instead.
    spring = parse_market_time_key(pd.Series(["2026-03-08 03:30:00"])).iloc[0]
    assert spring == pd.Timestamp("2026-03-08 03:30:00", tz=NY)
    assert spring.tz_convert("UTC") == pd.Timestamp("2026-03-08 07:30:00", tz="UTC")
    with pytest.raises(Exception):
        parse_market_time_key(pd.Series(["2026-11-01 01:30:00"]))


# --- ingested_at batch semantics --------------------------------------------


def test_ingested_at_identical_within_one_normalize_batch(tmp_path):
    cfg = settings(tmp_path)
    curated = normalize(cfg, ["US.MU", "US.NVDA"], ["2026-07-01 09:30:00", "2026-07-01 09:31:00"])
    assert curated["ingested_at"].nunique() == 1
    assert curated["ingested_at"].dt.tz is not None
    assert str(curated["ingested_at"].dt.tz) == "UTC"


def test_ingested_at_precision_microseconds(tmp_path):
    cfg = settings(tmp_path)
    curated = normalize(cfg, ["US.MU"], ["2026-07-01 09:30:00"])
    assert curated["ingested_at"].dtype == "datetime64[us, UTC]"
    assert curated["ingested_at"].iloc[0].nanosecond == 0


# --- run_finished_at semantics ----------------------------------------------


class FakeCollector:
    def __init__(self, settings):
        self.settings = settings

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        pass

    def fetch_history(self, code, trade_date, interval="1m", adjustment="NONE", session="ALL"):
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


def test_run_finished_at_present_and_utc(monkeypatch, tmp_path):
    monkeypatch.setattr(service_module, "MoomooHistoryCollector", FakeCollector)
    manifest = service_module.collect_history(
        settings(tmp_path),
        trade_date=date(2026, 7, 31),
        symbols=["US.MU"],
        interval="1m",
        session="ALL",
        adjustment="NONE",
    )
    assert manifest.finished_at is not None
    assert manifest.finished_at.tzinfo is not None
    assert manifest.finished_at.utcoffset() == timedelta(0)


def test_run_finished_at_after_ingested_at(monkeypatch, tmp_path):
    monkeypatch.setattr(service_module, "MoomooHistoryCollector", FakeCollector)
    cfg = settings(tmp_path)
    manifest = service_module.collect_history(
        cfg,
        trade_date=date(2026, 7, 31),
        symbols=["US.MU"],
        interval="1m",
        session="ALL",
        adjustment="NONE",
    )
    catalog = Catalog(cfg)
    with catalog.connect() as con:
        row = con.execute(
            "SELECT ingested_at FROM read_parquet('" + _curated_glob(cfg) + "')"
        ).fetchone()
    ingested = pd.Timestamp(row[0]).tz_convert("UTC")
    assert manifest.finished_at >= ingested.to_pydatetime()


def _curated_glob(cfg: Settings) -> str:
    root = cfg.data_root / "curated" / f"source={cfg.source}" / "dataset=market_bars"
    return (root / "**" / "*.parquet").as_posix().replace("'", "''")


# --- Parquet / DuckDB round-trip --------------------------------------------


def test_parquet_round_trip_preserves_timezone(tmp_path):
    cfg = settings(tmp_path)
    curated = normalize(cfg, ["US.MU"], ["2026-07-01 09:30:00"])
    ParquetStore(cfg).write_curated(
        curated, date(2026, 7, 1), "1m", ["US.MU"], "ALL", "NONE", run_id="run-a"
    )
    path = next((cfg.data_root / "curated").rglob("*.parquet"))
    back = pd.read_parquet(path)
    assert str(back["time_market"].dt.tz) == NY
    assert back["time_market"].iloc[0] == curated["time_market"].iloc[0]
    assert str(back["time_utc"].dt.tz) == "UTC"


@pytest.mark.parametrize("session_tz", ["UTC", "America/New_York"])
def test_duckdb_round_trip_surfaces_session_timezone(tmp_path, session_tz):
    cfg = settings(tmp_path)
    curated = normalize(cfg, ["US.MU"], ["2026-07-01 09:30:00"])
    ParquetStore(cfg).write_curated(
        curated, date(2026, 7, 1), "1m", ["US.MU"], "ALL", "NONE", run_id="run-a"
    )
    path = next((cfg.data_root / "curated").rglob("*.parquet"))
    escaped = path.as_posix().replace("'", "''")
    with Catalog(cfg).connect() as con:
        con.execute(f"SET TimeZone = '{session_tz}'")
        row = con.execute(
            f"SELECT time_market, time_utc FROM read_parquet('{escaped}')"
        ).fetchone()
    market = pd.Timestamp(row[0])
    utc = pd.Timestamp(row[1])
    # The surfaced wall clocks may differ per session timezone, but the
    # instants converted back to UTC must agree with the normalized values.
    assert market.tz_convert("UTC") == curated["time_market"].iloc[0].tz_convert("UTC")
    assert utc == curated["time_utc"].iloc[0]
