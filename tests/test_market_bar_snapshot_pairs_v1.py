from __future__ import annotations

import json
import hashlib
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from market_vault import service as service_module
from market_vault.audit import run_inventory
from market_vault.models import MarketBarSnapshotPair, QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars
from market_vault.purge import PurgeError, purge_execute, purge_plan
from market_vault.storage import Catalog, ParquetStore


TRADE_DATE = date(2026, 8, 3)


def settings(tmp_path: Path) -> Settings:
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


def raw_frame(symbol: str, *, close: float = 100.5) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "code": [symbol, symbol],
            "name": [symbol, symbol],
            "time_key": [
                f"{TRADE_DATE.isoformat()} 09:30:00",
                f"{TRADE_DATE.isoformat()} 09:31:00",
            ],
            "open": [100.0, 100.5],
            "high": [101.0, 101.5],
            "low": [99.0, 99.5],
            "close": [close, close + 0.5],
            "volume": [100, 120],
        }
    )


def install_collector(monkeypatch, responses: dict[str, pd.DataFrame | Exception]) -> None:
    class FakeCollector:
        def __init__(self, _settings):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def fetch_history(self, code, **_kwargs):
            response = responses[code]
            if isinstance(response, Exception):
                raise response
            return response.copy()

    monkeypatch.setattr(service_module, "MoomooHistoryCollector", FakeCollector)


def collect(monkeypatch, cfg: Settings, responses: dict[str, pd.DataFrame | Exception]):
    install_collector(monkeypatch, responses)
    return service_module.collect_history(
        cfg,
        TRADE_DATE,
        list(responses),
        "1m",
        "ALL",
        "NONE",
    )


def legacy_pair(
    cfg: Settings,
    symbols: list[str],
    *,
    run_id: str = "legacy-run",
) -> tuple[RunManifest, Path, Path]:
    raw = pd.concat([raw_frame(symbol) for symbol in symbols], ignore_index=True)
    raw["requested_trade_date"] = TRADE_DATE
    raw["interval"] = "1m"
    raw["requested_session"] = "ALL"
    raw["adjustment"] = "NONE"
    raw["ingestion_run_id"] = run_id
    curated = normalize_bars(
        raw,
        requested_trade_date=TRADE_DATE,
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source=cfg.source,
        source_schema_version=cfg.source_schema_version,
        run_id=run_id,
    )
    store = ParquetStore(cfg)
    raw_path = store.write_raw(raw, TRADE_DATE, "1m", symbols, "ALL", "NONE", run_id)
    curated_path = store.write_curated(
        curated, TRADE_DATE, "1m", symbols, "ALL", "NONE", run_id
    )
    manifest = RunManifest(
        requested_trade_date=TRADE_DATE,
        requested_symbols=symbols,
        interval="1m",
        session="ALL",
        adjustment="NONE",
        run_id=run_id,
    )
    manifest.successful_symbols = symbols
    manifest.raw_file = str(raw_path)
    manifest.curated_file = str(curated_path)
    manifest.row_count = len(curated)
    manifest.status = "SUCCESS"
    manifest.finished_at = datetime(2026, 8, 4, tzinfo=timezone.utc)
    catalog = Catalog(cfg)
    catalog.record_run(manifest)
    catalog.record_quality(run_id, [QualityResult("fixture", "PASS")])
    return manifest, raw_path, curated_path


def purge_for(cfg: Settings, symbols: list[str]):
    return purge_plan(
        cfg,
        source=cfg.source,
        symbols=symbols,
        start_date=TRADE_DATE,
        end_date=TRADE_DATE,
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source_schema_version=cfg.source_schema_version,
    )


def test_multi_symbol_collection_publishes_independent_registered_pairs(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    manifest = collect(
        monkeypatch,
        cfg,
        {"US.SPY": raw_frame("US.SPY"), "US.QQQ": raw_frame("US.QQQ")},
    )

    assert manifest.status == "SUCCESS"
    assert manifest.snapshot_binding_mode == "REGISTERED_PER_SYMBOL"
    assert manifest.successful_symbols == ["US.QQQ", "US.SPY"]
    assert [pair.symbol for pair in manifest.snapshot_pairs] == ["US.QQQ", "US.SPY"]
    assert manifest.raw_file is None and manifest.curated_file is None
    assert manifest.row_count == 4
    assert len(list((cfg.data_root / "raw").rglob("*.parquet"))) == 2
    assert len(list((cfg.data_root / "curated").rglob("*.parquet"))) == 2
    pairs = Catalog(cfg).market_bar_snapshot_pairs_for_run(manifest.run_id)
    assert pairs == manifest.snapshot_pairs
    assert [item["symbol"] for item in manifest.as_dict()["snapshot_pairs"]] == [
        "US.QQQ",
        "US.SPY",
    ]
    assert set(manifest.as_dict()["snapshot_pairs"][0]) == {
        "run_id",
        "symbol",
        "requested_trade_date",
        "interval",
        "session",
        "adjustment",
        "source",
        "source_schema_version",
        "raw_file",
        "curated_file",
        "row_count",
    }
    for pair in manifest.snapshot_pairs:
        batch_key = hashlib.sha256(
            f"{pair.symbol}|1m|ALL|NONE".encode("utf-8")
        ).hexdigest()[:16]
        assert Path(pair.raw_file).name == f"batch-{batch_key}-{manifest.run_id}.parquet"
        assert Path(pair.curated_file).name == f"batch-{batch_key}-{manifest.run_id}.parquet"
    with Catalog(cfg).connect() as con:
        assert con.execute(
            "SELECT snapshot_binding_mode FROM ingestion_runs WHERE run_id = ?",
            [manifest.run_id],
        ).fetchone() == ("REGISTERED_PER_SYMBOL",)


def test_fetch_failure_publishes_only_successful_symbol(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    manifest = collect(
        monkeypatch,
        cfg,
        {"US.SPY": raw_frame("US.SPY"), "US.QQQ": RuntimeError("provider failure")},
    )
    assert manifest.status == "PARTIAL"
    assert manifest.successful_symbols == ["US.SPY"]
    assert set(manifest.failed_symbols) == {"US.QQQ"}
    assert len(manifest.snapshot_pairs) == 1
    assert manifest.raw_file == manifest.snapshot_pairs[0].raw_file
    assert manifest.curated_file == manifest.snapshot_pairs[0].curated_file


def test_registry_failure_leaves_unregistered_files_and_no_success(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    install_collector(monkeypatch, {"US.SPY": raw_frame("US.SPY")})
    monkeypatch.setattr(
        Catalog,
        "register_market_bar_snapshot_pair",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("registry unavailable")),
    )
    manifest = service_module.collect_history(
        cfg, TRADE_DATE, ["US.SPY"], "1m", "ALL", "NONE"
    )
    assert manifest.status == "FAILED"
    assert manifest.snapshot_binding_mode == "REGISTERED_PER_SYMBOL"
    assert manifest.successful_symbols == []
    assert manifest.snapshot_pairs == []
    assert manifest.raw_file is None and manifest.curated_file is None
    assert manifest.row_count == 0
    assert len(list(cfg.data_root.rglob("*.parquet"))) == 2
    with Catalog(cfg).connect() as con:
        assert con.execute("SELECT count(*) FROM market_bar_snapshot_pairs").fetchone() == (0,)
        assert con.execute(
            "SELECT snapshot_binding_mode FROM ingestion_runs WHERE run_id = ?",
            [manifest.run_id],
        ).fetchone() == ("REGISTERED_PER_SYMBOL",)


def test_partial_registry_failure_keeps_only_registered_pair_successful(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    install_collector(
        monkeypatch,
        {"US.SPY": raw_frame("US.SPY"), "US.QQQ": raw_frame("US.QQQ")},
    )
    real_register = Catalog.register_market_bar_snapshot_pair

    def register(self, pair):
        if pair.symbol == "US.QQQ":
            raise RuntimeError("QQQ registration failed")
        return real_register(self, pair)

    monkeypatch.setattr(Catalog, "register_market_bar_snapshot_pair", register)
    manifest = service_module.collect_history(
        cfg, TRADE_DATE, ["US.SPY", "US.QQQ"], "1m", "ALL", "NONE"
    )
    assert manifest.status == "PARTIAL"
    assert manifest.successful_symbols == ["US.SPY"]
    assert set(manifest.failed_symbols) == {"US.QQQ"}
    assert [pair.symbol for pair in manifest.snapshot_pairs] == ["US.SPY"]
    assert len(list(cfg.data_root.rglob("*.parquet"))) == 4
    assert [pair.symbol for pair in Catalog(cfg).market_bar_snapshot_pairs_for_run(manifest.run_id)] == [
        "US.SPY"
    ]
    assert not Catalog(cfg).completed_market_bar_items(
        symbols=["US.QQQ"],
        trade_dates=[TRADE_DATE],
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source_schema_version=cfg.source_schema_version,
    )


def test_pair_registration_is_exact_idempotent_and_conflicts_fail(tmp_path):
    cfg = settings(tmp_path)
    pair = MarketBarSnapshotPair.create(
        run_id="run-a",
        symbol=" us.spy ",
        requested_trade_date=TRADE_DATE,
        interval="1M",
        session="all",
        adjustment="none",
        source="moomoo",
        source_schema_version="10.9",
        raw_file="raw-a.parquet",
        curated_file="curated-a.parquet",
        row_count=2,
    )
    catalog = Catalog(cfg)
    catalog.register_market_bar_snapshot_pair(pair)
    catalog.register_market_bar_snapshot_pair(pair)
    assert catalog.market_bar_snapshot_pair_count("run-a") == 1
    conflicting = MarketBarSnapshotPair.create(
        **{**pair.__dict__, "curated_file": "different.parquet"}
    )
    with pytest.raises(RuntimeError, match="conflict"):
        catalog.register_market_bar_snapshot_pair(conflicting)


def test_historical_catalog_rows_keep_null_mode(tmp_path):
    cfg = settings(tmp_path)
    cfg.catalog_path.parent.mkdir(parents=True, exist_ok=True)
    with Catalog(cfg).connect() as con:
        con.execute(
            """
            CREATE TABLE ingestion_runs (
                run_id VARCHAR PRIMARY KEY, started_at TIMESTAMPTZ,
                finished_at TIMESTAMPTZ, requested_trade_date DATE,
                requested_symbols JSON, interval VARCHAR, session VARCHAR,
                adjustment VARCHAR, successful_symbols JSON,
                failed_symbols JSON, raw_file VARCHAR, curated_file VARCHAR,
                row_count BIGINT, status VARCHAR, config_hash VARCHAR
            )
            """
        )
        con.execute(
            """
            INSERT INTO ingestion_runs VALUES (
                'legacy-run', NULL, NULL, '2026-08-03', '["US.SPY"]',
                '1m', 'ALL', 'NONE', '["US.SPY"]', '{}', NULL, NULL,
                0, 'SUCCESS', ''
            )
            """
        )
    Catalog(cfg).initialize()
    with Catalog(cfg).connect() as con:
        row = con.execute(
            "SELECT snapshot_binding_mode FROM ingestion_runs WHERE run_id = 'legacy-run'"
        ).fetchone()
    assert row == (None,)


def test_registered_symbol_can_be_purged_without_sibling(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    manifest = collect(
        monkeypatch,
        cfg,
        {"US.SPY": raw_frame("US.SPY"), "US.QQQ": raw_frame("US.QQQ")},
    )
    by_symbol = {pair.symbol: pair for pair in manifest.snapshot_pairs}
    sealed = purge_for(cfg, ["US.SPY"])
    assert sealed.executable
    assert len(sealed.targets) == 1
    assert sealed.targets[0]["binding_mode"] == "REGISTERED_PER_SYMBOL"
    assert sealed.targets[0]["snapshot_pair_binding"]["symbol"] == "US.SPY"
    purge_execute(cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}")
    assert not Path(by_symbol["US.SPY"].raw_file).exists()
    assert not Path(by_symbol["US.SPY"].curated_file).exists()
    assert Path(by_symbol["US.QQQ"].raw_file).exists()
    assert Path(by_symbol["US.QQQ"].curated_file).exists()
    assert Catalog(cfg).market_bar_snapshot_pair_count(manifest.run_id) == 2


def test_registered_binding_disappearance_and_mode_drift_refuse(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    manifest = collect(monkeypatch, cfg, {"US.SPY": raw_frame("US.SPY")})
    sealed = purge_for(cfg, ["US.SPY"])
    with Catalog(cfg).connect() as con:
        con.execute(
            "DELETE FROM market_bar_snapshot_pairs WHERE run_id = ? AND symbol = 'US.SPY'",
            [manifest.run_id],
        )
    with pytest.raises(PurgeError, match="binding drifted"):
        purge_execute(cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}")
    assert Path(manifest.raw_file).exists() and Path(manifest.curated_file).exists()
    refused = purge_for(cfg, ["US.SPY"])
    assert refused.status == "REFUSED"
    assert any(item["code"] == "UNREGISTERED_SNAPSHOT" for item in refused.refusal_reasons)
    assert not Catalog(cfg).completed_market_bar_items(
        symbols=["US.SPY"],
        trade_dates=[TRADE_DATE],
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source_schema_version=cfg.source_schema_version,
    )


def test_legacy_authority_requires_null_mode_and_zero_registry_rows(tmp_path):
    cfg = settings(tmp_path)
    manifest, raw_path, curated_path = legacy_pair(cfg, ["US.SPY"])
    sealed = purge_for(cfg, ["US.SPY"])
    assert sealed.executable and sealed.targets[0]["binding_mode"] == "LEGACY_INGESTION_RUN"
    pair = MarketBarSnapshotPair.create(
        run_id=manifest.run_id,
        symbol="US.SPY",
        requested_trade_date=TRADE_DATE,
        interval="1m",
        session="ALL",
        adjustment="NONE",
        source=cfg.source,
        source_schema_version=cfg.source_schema_version,
        raw_file=str(raw_path),
        curated_file=str(curated_path),
        row_count=manifest.row_count,
    )
    Catalog(cfg).register_market_bar_snapshot_pair(pair)
    with pytest.raises(PurgeError, match="authority drifted"):
        purge_execute(cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}")
    assert raw_path.exists() and curated_path.exists()
    replanned = purge_for(cfg, ["US.SPY"])
    assert any(
        item["code"] == "INCONSISTENT_SNAPSHOT_AUTHORITY"
        for item in replanned.refusal_reasons
    )


def test_unknown_registered_mode_refuses_without_legacy_fallback(tmp_path):
    cfg = settings(tmp_path)
    manifest, raw_path, curated_path = legacy_pair(cfg, ["US.SPY"])
    with Catalog(cfg).connect() as con:
        con.execute(
            "UPDATE ingestion_runs SET snapshot_binding_mode = 'FUTURE_MODE' WHERE run_id = ?",
            [manifest.run_id],
        )
    sealed = purge_for(cfg, ["US.SPY"])
    assert sealed.status == "REFUSED"
    assert any(
        item["code"] == "UNKNOWN_SNAPSHOT_BINDING_MODE"
        for item in sealed.refusal_reasons
    )
    assert raw_path.exists() and curated_path.exists()


def test_symbol_persistence_failure_leaves_only_unregistered_raw(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    install_collector(
        monkeypatch,
        {"US.SPY": raw_frame("US.SPY"), "US.QQQ": raw_frame("US.QQQ")},
    )
    real_write = ParquetStore.write_curated

    def write_curated(self, frame, trade_date, interval, symbols, session, adjustment, run_id):
        if symbols == ["US.QQQ"]:
            raise RuntimeError("curated publication failed")
        return real_write(
            self, frame, trade_date, interval, symbols, session, adjustment, run_id
        )

    monkeypatch.setattr(ParquetStore, "write_curated", write_curated)
    manifest = service_module.collect_history(
        cfg, TRADE_DATE, ["US.SPY", "US.QQQ"], "1m", "ALL", "NONE"
    )
    assert manifest.status == "PARTIAL"
    assert manifest.successful_symbols == ["US.SPY"]
    assert [pair.symbol for pair in manifest.snapshot_pairs] == ["US.SPY"]
    raw_symbols = [set(pd.read_parquet(path)["code"]) for path in cfg.data_root.rglob("*.parquet")]
    assert {"US.QQQ"} in raw_symbols
    assert [pair.symbol for pair in Catalog(cfg).market_bar_snapshot_pairs_for_run(manifest.run_id)] == [
        "US.SPY"
    ]


def test_recollection_creates_another_immutable_pair(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    first = collect(monkeypatch, cfg, {"US.SPY": raw_frame("US.SPY", close=100.0)})
    first_bytes = {
        "raw": Path(first.raw_file).read_bytes(),
        "curated": Path(first.curated_file).read_bytes(),
    }
    second = collect(monkeypatch, cfg, {"US.SPY": raw_frame("US.SPY", close=200.0)})
    assert first.run_id != second.run_id
    assert Path(first.raw_file).read_bytes() == first_bytes["raw"]
    assert Path(first.curated_file).read_bytes() == first_bytes["curated"]
    assert Path(second.raw_file).exists() and Path(second.curated_file).exists()
    assert len(list((cfg.data_root / "raw").rglob("*.parquet"))) == 2
    assert len(list((cfg.data_root / "curated").rglob("*.parquet"))) == 2


def test_mixed_legacy_and_registered_archive_remains_readable(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    legacy_pair(cfg, ["US.SPY"])
    current = collect(monkeypatch, cfg, {"US.QQQ": raw_frame("US.QQQ")})
    catalog = Catalog(cfg)
    completed = catalog.completed_market_bar_items(
        symbols=["US.SPY", "US.QQQ"],
        trade_dates=[TRADE_DATE],
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source_schema_version=cfg.source_schema_version,
    )
    assert completed == {("US.SPY", TRADE_DATE), ("US.QQQ", TRADE_DATE)}
    refs = catalog.latest_complete_market_bar_snapshots(
        symbols=["US.SPY", "US.QQQ"],
        trade_dates=[TRADE_DATE],
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source_schema_version=cfg.source_schema_version,
    )
    assert set(refs) == completed
    assert refs[("US.QQQ", TRADE_DATE)].ingestion_run_id == current.run_id
    assert not catalog.market_bar_snapshot_rows(refs[("US.SPY", TRADE_DATE)]).frame.empty
    assert not catalog.market_bar_snapshot_rows(refs[("US.QQQ", TRADE_DATE)]).frame.empty
    inventory = run_inventory(cfg, symbols=["US.SPY", "US.QQQ"])
    assert inventory.status == "SUCCESS"
    assert {item.code for item in inventory.items} == {"US.SPY", "US.QQQ"}


def test_registered_pair_catalog_drift_refuses_before_mutation(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    manifest = collect(monkeypatch, cfg, {"US.SPY": raw_frame("US.SPY")})
    sealed = purge_for(cfg, ["US.SPY"])
    with Catalog(cfg).connect() as con:
        con.execute(
            "UPDATE market_bar_snapshot_pairs SET row_count = row_count + 1 "
            "WHERE run_id = ? AND symbol = 'US.SPY'",
            [manifest.run_id],
        )
    with pytest.raises(PurgeError, match="snapshot-pair binding drifted"):
        purge_execute(cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}")
    assert Path(manifest.raw_file).exists() and Path(manifest.curated_file).exists()


def test_extra_intersecting_unregistered_parquet_refuses_registered_plan(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    collect(monkeypatch, cfg, {"US.SPY": raw_frame("US.SPY")})
    stray = raw_frame("US.SPY", close=999.0)
    stray["requested_trade_date"] = TRADE_DATE
    stray["interval"] = "1m"
    stray["requested_session"] = "ALL"
    stray["adjustment"] = "NONE"
    stray["ingestion_run_id"] = "stray-run"
    curated = normalize_bars(
        stray,
        requested_trade_date=TRADE_DATE,
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source=cfg.source,
        source_schema_version=cfg.source_schema_version,
        run_id="stray-run",
    )
    store = ParquetStore(cfg)
    store.write_raw(stray, TRADE_DATE, "1m", ["US.SPY"], "ALL", "NONE", "stray-run")
    store.write_curated(
        curated, TRADE_DATE, "1m", ["US.SPY"], "ALL", "NONE", "stray-run"
    )
    sealed = purge_for(cfg, ["US.SPY"])
    assert sealed.status == "REFUSED"
    assert sum(
        item["code"] == "UNREGISTERED_SNAPSHOT" for item in sealed.refusal_reasons
    ) == 2


def _historical_v2_plan(cfg: Settings, current_plan):
    payload = json.loads(Path(current_plan.plan_file).read_text(encoding="utf-8"))
    for target in payload["targets"]:
        target.pop("binding_mode", None)
        target.pop("snapshot_pair_binding", None)
        full = target["run_binding"]
        target["run_binding"] = {
            key: full[key]
            for key in (
                "run_id",
                "requested_trade_date",
                "requested_symbols",
                "interval",
                "requested_session",
                "adjustment",
                "raw_relative_path",
                "curated_relative_path",
                "status",
            )
        }
    content = {key: value for key, value in payload.items() if key not in {"plan_id", "content_hash"}}
    canonical = (
        json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    plan_id = digest[:32]
    payload["plan_id"] = plan_id
    payload["content_hash"] = digest
    plan_path = cfg.manifest_dir / "purge" / "plans" / f"{plan_id}.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n",
        encoding="utf-8",
        newline="",
    )
    Catalog(cfg).record_purge_plan(
        plan_id=plan_id,
        plan_hash=digest,
        state="PLANNED",
        scope_json=json.dumps(payload["scope"], sort_keys=True, separators=(",", ":")),
        plan_file=str(plan_path),
        planned_at=datetime.now(timezone.utc),
    )
    return plan_id


def test_historical_v2_legacy_plan_revalidates_mode_before_execute(tmp_path):
    cfg = settings(tmp_path)
    manifest, raw_path, curated_path = legacy_pair(cfg, ["US.SPY"])
    historical_id = _historical_v2_plan(cfg, purge_for(cfg, ["US.SPY"]))
    with Catalog(cfg).connect() as con:
        con.execute(
            "UPDATE ingestion_runs SET snapshot_binding_mode = 'REGISTERED_PER_SYMBOL' "
            "WHERE run_id = ?",
            [manifest.run_id],
        )
    with pytest.raises(PurgeError, match="historical legacy target authority drifted"):
        purge_execute(cfg, plan_id=historical_id, confirmation=f"PURGE {historical_id}")
    assert raw_path.exists() and curated_path.exists()


def test_historical_v2_legacy_plan_revalidates_zero_registry_rows(tmp_path):
    cfg = settings(tmp_path)
    manifest, raw_path, curated_path = legacy_pair(cfg, ["US.SPY"])
    historical_id = _historical_v2_plan(cfg, purge_for(cfg, ["US.SPY"]))
    Catalog(cfg).register_market_bar_snapshot_pair(
        MarketBarSnapshotPair.create(
            run_id=manifest.run_id,
            symbol="US.SPY",
            requested_trade_date=TRADE_DATE,
            interval="1m",
            session="ALL",
            adjustment="NONE",
            source=cfg.source,
            source_schema_version=cfg.source_schema_version,
            raw_file=str(raw_path),
            curated_file=str(curated_path),
            row_count=manifest.row_count,
        )
    )
    with pytest.raises(PurgeError, match="historical legacy target authority drifted"):
        purge_execute(cfg, plan_id=historical_id, confirmation=f"PURGE {historical_id}")
    assert raw_path.exists() and curated_path.exists()


def test_registered_physical_fact_drift_refuses_before_move(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    manifest = collect(monkeypatch, cfg, {"US.SPY": raw_frame("US.SPY")})
    sealed = purge_for(cfg, ["US.SPY"])
    curated = pd.read_parquet(manifest.curated_file)
    curated.loc[0, "code"] = "US.QQQ"
    curated.to_parquet(manifest.curated_file, index=False)
    with pytest.raises(PurgeError, match="identity changed|physical snapshot facts drifted"):
        purge_execute(cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}")
    assert Path(manifest.raw_file).exists() and Path(manifest.curated_file).exists()
