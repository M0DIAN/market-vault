from __future__ import annotations

import json
import hashlib
from datetime import date, datetime, timezone
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
import yaml

from market_vault import service as service_module
from market_vault import MarketVault
from market_vault.cli import main as cli_main
from market_vault.lifecycle import LifecycleLockError, MarketBarLifecycleLock
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


def _source_failure(monkeypatch, cfg: Settings, fault: str) -> Path:
    with monkeypatch.context() as patch:
        install_collector(patch, {"US.SPY": raw_frame("US.SPY")})
        owner, name = {
            "raw_only": (ParquetStore, "write_curated"),
            "pair_unregistered": (Catalog, "register_market_bar_snapshot_pair"),
            "run_publication": (Catalog, "record_run"),
        }[fault]

        def fail(*_args, **_kwargs):
            raise RuntimeError(f"injected {fault} failure")

        patch.setattr(owner, name, fail)
        if fault == "run_publication":
            with pytest.raises(RuntimeError, match="run_publication"):
                service_module.collect_history(cfg, TRADE_DATE, ["US.SPY"], "1m", "ALL", "NONE")
        else:
            original = service_module.collect_history(cfg, TRADE_DATE, ["US.SPY"], "1m", "ALL", "NONE")
            assert original.status == "FAILED"
    return next(cfg.manifest_dir.glob(f"{TRADE_DATE}_*.json"))


def _forbid_opend(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Offline recovery must not construct an OpenD history collector")
    monkeypatch.setattr(service_module, "MoomooHistoryCollector", forbidden)


def _old_catalog_rows(cfg: Settings, run_id: str) -> dict:
    with Catalog(cfg).connect() as con:
        return {
            table: con.execute(f"SELECT * FROM {table} WHERE run_id = ? ORDER BY ALL", [run_id]).fetchall()
            for table in ("ingestion_runs", "market_bar_snapshot_pairs", "quality_results")
        }


def _recovery_settings_file(cfg: Settings) -> Path:
    path = cfg.project_root / "config" / "settings.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(yaml.safe_dump({
        "storage": {
            "root_dir": str(cfg.data_root), "catalog_path": str(cfg.catalog_path),
            "manifest_dir": str(cfg.manifest_dir), "report_dir": str(cfg.report_dir),
        },
        "collector": {"source": cfg.source, "source_schema_version": cfg.source_schema_version},
    }), encoding="utf-8")
    return path


@pytest.mark.parametrize("fault,surface", [
    ("raw_only", "service"), ("pair_unregistered", "api"), ("run_publication", "cli"),
])
def test_offline_recovery_replays_real_failure_into_new_run_preserving_history(
    monkeypatch, tmp_path, capsys, fault, surface
):
    cfg = settings(tmp_path)
    source_path = _source_failure(monkeypatch, cfg, fault)
    source = json.loads(source_path.read_bytes())
    source_run_id = source["run_id"]
    old_files = {
        path: path.read_bytes()
        for directory in (cfg.data_root, cfg.manifest_dir, cfg.report_dir)
        for path in directory.rglob("*") if path.is_file()
    }
    old_rows = _old_catalog_rows(cfg, source_run_id)
    if fault == "run_publication":
        assert old_rows["ingestion_runs"] == []
        assert len(old_rows["market_bar_snapshot_pairs"]) == 1
    else:
        assert source["status"] == "FAILED"
        assert old_rows["market_bar_snapshot_pairs"] == []
    _forbid_opend(monkeypatch)
    recovery_started = datetime.now(timezone.utc)
    if surface == "service":
        recovered = service_module.recover_history_from_raw(cfg, source_path).as_dict()
    elif surface == "api":
        recovered = MarketVault(cfg).recover_history_from_raw(source_path).as_dict()
    else:
        settings_path = _recovery_settings_file(cfg)
        assert cli_main(["--settings", str(settings_path), "recover-history", "--manifest", str(source_path)]) == 0
        recovered = json.loads(capsys.readouterr().out)
    assert recovered["status"] == "SUCCESS"
    assert recovered["run_id"] != source_run_id
    assert recovered["snapshot_binding_mode"] == "REGISTERED_PER_SYMBOL"
    assert recovered["successful_symbols"] == ["US.SPY"]
    assert set(recovered) == set(source)  # No RunManifest schema extension.
    assert all(path.read_bytes() == before for path, before in old_files.items())
    assert _old_catalog_rows(cfg, source_run_id) == old_rows
    lineage_path = cfg.manifest_dir / f"{TRADE_DATE}_{recovered['run_id']}.recovery.json"
    lineage = json.loads(lineage_path.read_bytes())
    original_raw = ParquetStore(cfg)._path("raw", TRADE_DATE, "1m", ["US.SPY"], "ALL", "NONE", source_run_id)
    assert lineage == {
        "schema_version": "market-vault-raw-history-recovery-lineage-v1",
        "replay_version": "market-bars-raw-replay-v1",
        "run_id": recovered["run_id"],
        "started_at": recovered["started_at"],
        "source": cfg.source,
        "source_schema_version": cfg.source_schema_version,
        "config_hash": recovered["config_hash"],
        "source_manifest": {
            "path": str(source_path), "sha256": hashlib.sha256(old_files[source_path]).hexdigest(),
            "run_id": source_run_id,
        },
        "raw_inputs": [{
            "symbol": "US.SPY", "path": str(original_raw),
            "sha256": hashlib.sha256(old_files[original_raw]).hexdigest(),
        }],
    }
    new_raw = pd.read_parquet(recovered["raw_file"])
    new_curated = pd.read_parquet(recovered["curated_file"])
    assert set(new_raw["ingestion_run_id"]) == {recovered["run_id"]}
    assert set(new_curated["ingestion_run_id"]) == {recovered["run_id"]}
    assert new_raw["close"].tolist() == pd.read_parquet(original_raw)["close"].tolist()
    assert new_curated["ingested_at"].min() >= pd.Timestamp(recovery_started)
    catalog = Catalog(cfg)
    assert [pair.as_dict() for pair in catalog.market_bar_snapshot_pairs_for_run(recovered["run_id"])] == recovered["snapshot_pairs"]
    assert catalog.completed_market_bar_items(
        symbols=["US.SPY"], trade_dates=[TRADE_DATE], interval="1m", requested_session="ALL",
        adjustment="NONE", source_schema_version=cfg.source_schema_version,
    ) == {("US.SPY", TRADE_DATE)}


def test_recovery_subset_can_select_retained_raw_when_other_requested_raw_is_missing(monkeypatch, tmp_path, capsys):
    cfg = settings(tmp_path)
    original = collect(monkeypatch, cfg, {
        "US.SPY": raw_frame("US.SPY"), "US.QQQ": RuntimeError("no source Raw"),
    })
    path = cfg.manifest_dir / f"{TRADE_DATE}_{original.run_id}.json"
    _forbid_opend(monkeypatch)
    with pytest.raises(FileNotFoundError):
        MarketVault(cfg).recover_history_from_raw(path)
    settings_path = _recovery_settings_file(cfg)
    assert cli_main([
        "--settings", str(settings_path), "recover-history", "--manifest", str(path),
        "--symbols", " us.spy ",
    ]) == 0
    recovered = json.loads(capsys.readouterr().out)
    assert recovered["requested_symbols"] == ["US.SPY"]
    assert recovered["run_id"] != original.run_id
    assert recovered["config_hash"] != original.config_hash
    lineage = json.loads((cfg.manifest_dir / f"{TRADE_DATE}_{recovered['run_id']}.recovery.json").read_bytes())
    assert [item["symbol"] for item in lineage["raw_inputs"]] == ["US.SPY"]


def test_recovery_hashes_exact_consumed_buffers_when_sources_change_after_capture(monkeypatch, tmp_path):
    from market_vault import raw_recovery

    cfg = settings(tmp_path)
    source_path = _source_failure(monkeypatch, cfg, "raw_only")
    manifest_bytes = source_path.read_bytes()
    source = json.loads(manifest_bytes)
    raw_path = ParquetStore(cfg)._path("raw", TRADE_DATE, "1m", ["US.SPY"], "ALL", "NONE", source["run_id"])
    raw_bytes = raw_path.read_bytes()
    actual_loads = json.loads
    actual_parquet = raw_recovery.pq.ParquetFile
    changed = {"manifest": False, "raw": False}

    def parse_manifest(value, *args, **kwargs):
        if isinstance(value, bytes) and value == manifest_bytes and not changed["manifest"]:
            changed["manifest"] = True
            source_path.write_bytes(b"external change after manifest capture")
        return actual_loads(value, *args, **kwargs)

    def parse_raw(value, *args, **kwargs):
        if not changed["raw"]:
            changed["raw"] = True
            raw_path.write_bytes(b"external change after Raw capture")
        return actual_parquet(value, *args, **kwargs)

    _forbid_opend(monkeypatch)
    monkeypatch.setattr(raw_recovery.json, "loads", parse_manifest)
    monkeypatch.setattr(raw_recovery.pq, "ParquetFile", parse_raw)
    recovered = MarketVault(cfg).recover_history_from_raw(source_path)
    assert recovered.status == "SUCCESS"
    assert changed == {"manifest": True, "raw": True}
    lineage = json.loads((cfg.manifest_dir / f"{TRADE_DATE}_{recovered.run_id}.recovery.json").read_bytes())
    assert lineage["source_manifest"]["sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    assert lineage["raw_inputs"][0]["sha256"] == hashlib.sha256(raw_bytes).hexdigest()
    assert pd.read_parquet(recovered.raw_file)["close"].tolist() == [100.5, 101.0]


@pytest.mark.parametrize("binding", [None, "missing", "LEGACY_INGESTION_RUN", "UNKNOWN"])
def test_recovery_refuses_unbound_source_manifest(monkeypatch, tmp_path, binding):
    cfg = settings(tmp_path)
    original_path = _source_failure(monkeypatch, cfg, "raw_only")
    payload = json.loads(original_path.read_bytes())
    if binding == "missing":
        payload.pop("snapshot_binding_mode")
    else:
        payload["snapshot_binding_mode"] = binding
    source = tmp_path / "unbound.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    old_files = {path: path.read_bytes() for path in cfg.data_root.rglob("*.parquet")}
    _forbid_opend(monkeypatch)
    with pytest.raises(ValueError, match="REGISTERED_PER_SYMBOL"):
        MarketVault(cfg).recover_history_from_raw(source)
    assert {path: path.read_bytes() for path in cfg.data_root.rglob("*.parquet")} == old_files


@pytest.mark.parametrize("field,value", [
    ("code", "US.QQQ"), ("requested_trade_date", date(2026, 8, 4)), ("interval", "5m"),
    ("requested_session", "RTH"), ("adjustment", "FORWARD"), ("ingestion_run_id", "different-run"),
    ("source", "other"), ("source_schema_version", "different-schema"),
])
def test_recovery_refuses_original_raw_identity_before_rebasing(monkeypatch, tmp_path, field, value):
    cfg = settings(tmp_path)
    source_path = _source_failure(monkeypatch, cfg, "raw_only")
    source = json.loads(source_path.read_bytes())
    raw_path = ParquetStore(cfg)._path("raw", TRADE_DATE, "1m", ["US.SPY"], "ALL", "NONE", source["run_id"])
    frame = pd.read_parquet(raw_path)
    frame[field] = value
    frame.to_parquet(raw_path, index=False)
    before = raw_path.read_bytes()
    old_rows = _old_catalog_rows(cfg, source["run_id"])
    _forbid_opend(monkeypatch)
    with pytest.raises(ValueError, match=f"mismatched {field}"):
        MarketVault(cfg).recover_history_from_raw(source_path)
    assert raw_path.read_bytes() == before
    assert list(cfg.data_root.rglob("*.parquet")) == [raw_path]
    assert _old_catalog_rows(cfg, source["run_id"]) == old_rows


@pytest.mark.parametrize("change", ["schema", "source", "status", "finished_at", "config_hash", "pair_path", "catalog_run", "catalog_pair"])
def test_recovery_refuses_incompatible_source_authority(monkeypatch, tmp_path, change):
    cfg = settings(tmp_path)
    original = collect(monkeypatch, cfg, {"US.SPY": raw_frame("US.SPY")})
    original_path = cfg.manifest_dir / f"{TRADE_DATE}_{original.run_id}.json"
    payload = json.loads(original_path.read_bytes())
    selected_settings = cfg
    if change == "schema":
        selected_settings = replace(cfg, source_schema_version="different-schema")
    elif change == "source":
        selected_settings = replace(cfg, source="other")
    elif change == "status":
        payload["status"] = "RUNNING"
    elif change == "finished_at":
        payload["finished_at"] = None
    elif change == "config_hash":
        payload["config_hash"] = "0" * 64
    elif change == "pair_path":
        payload["snapshot_pairs"][0]["raw_file"] = str(tmp_path / "substitute.parquet")
    else:
        with Catalog(cfg).connect() as con:
            if change == "catalog_run":
                con.execute("UPDATE ingestion_runs SET config_hash = 'drift' WHERE run_id = ?", [original.run_id])
            else:
                con.execute("UPDATE market_bar_snapshot_pairs SET source_schema_version = 'drift' WHERE run_id = ?", [original.run_id])
    source_path = tmp_path / "source.json"
    source_path.write_text(json.dumps(payload), encoding="utf-8")
    before = {path: path.read_bytes() for path in cfg.data_root.rglob("*.parquet")}
    _forbid_opend(monkeypatch)
    with pytest.raises(ValueError):
        MarketVault(selected_settings).recover_history_from_raw(source_path)
    assert {path: path.read_bytes() for path in cfg.data_root.rglob("*.parquet")} == before


def test_recovery_refuses_missing_evidence_invalid_subset_and_stale_lock(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    source_path = _source_failure(monkeypatch, cfg, "raw_only")
    _forbid_opend(monkeypatch)
    with pytest.raises(FileNotFoundError):
        MarketVault(cfg).recover_history_from_raw(tmp_path / "missing.json")
    for symbols in ([], [""], ["US.QQQ"]):
        with pytest.raises(ValueError):
            MarketVault(cfg).recover_history_from_raw(source_path, symbols=symbols)
    with MarketBarLifecycleLock(cfg.data_root, "unresolved-owner") as lock:
        before = lock.owner_path.read_bytes()
        with pytest.raises(LifecycleLockError, match="already held"):
            MarketVault(cfg).recover_history_from_raw(source_path)
        assert lock.owner_path.read_bytes() == before


@pytest.mark.parametrize("content", [b"truncated Parquet", b""])
def test_recovery_refuses_unreadable_raw_without_new_publication(monkeypatch, tmp_path, content):
    cfg = settings(tmp_path)
    source_path = _source_failure(monkeypatch, cfg, "raw_only")
    raw_path = next(cfg.data_root.rglob("*.parquet"))
    raw_path.write_bytes(content)
    _forbid_opend(monkeypatch)
    with pytest.raises(ValueError, match="Cannot parse source Raw"):
        MarketVault(cfg).recover_history_from_raw(source_path)
    assert raw_path.read_bytes() == content
    assert list(cfg.data_root.rglob("*.parquet")) == [raw_path]


def test_recovery_refuses_original_run_id_without_changing_history(monkeypatch, tmp_path):
    from market_vault import models

    cfg = settings(tmp_path)
    source_path = _source_failure(monkeypatch, cfg, "raw_only")
    source_bytes = source_path.read_bytes()
    run_id = json.loads(source_bytes)["run_id"]
    old_rows = _old_catalog_rows(cfg, run_id)
    monkeypatch.setattr(models, "uuid4", lambda: run_id)
    _forbid_opend(monkeypatch)
    with pytest.raises(ValueError, match="fresh run ID"):
        MarketVault(cfg).recover_history_from_raw(source_path)
    assert source_path.read_bytes() == source_bytes
    assert _old_catalog_rows(cfg, run_id) == old_rows
    assert len(list(cfg.data_root.rglob("*.parquet"))) == 1


def test_recovery_exclusive_manifest_creation_refuses_target_appearing_after_preflight(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    source_path = _source_failure(monkeypatch, cfg, "raw_only")
    original_id = json.loads(source_path.read_bytes())["run_id"]
    old_rows = _old_catalog_rows(cfg, original_id)
    actual_register = Catalog.register_market_bar_snapshot_pair
    new_pairs = []

    def competing_evidence(self, pair):
        actual_register(self, pair)
        new_pairs.append(pair)
        (cfg.manifest_dir / f"{TRADE_DATE}_{pair.run_id}.json").write_bytes(b"competing evidence")

    monkeypatch.setattr(Catalog, "register_market_bar_snapshot_pair", competing_evidence)
    _forbid_opend(monkeypatch)
    with pytest.raises(FileExistsError):
        MarketVault(cfg).recover_history_from_raw(source_path)
    assert len(new_pairs) == 1
    run_id = new_pairs[0].run_id
    assert (cfg.manifest_dir / f"{TRADE_DATE}_{run_id}.json").read_bytes() == b"competing evidence"
    assert _old_catalog_rows(cfg, run_id)["ingestion_runs"] == []
    assert _old_catalog_rows(cfg, original_id) == old_rows


@pytest.mark.parametrize("directory,suffix", [("manifest_dir", ".json"), ("report_dir", ".json"), ("manifest_dir", ".recovery.json")])
def test_recovery_refuses_preexisting_evidence_even_dangling_links(monkeypatch, tmp_path, directory, suffix):
    from market_vault import models

    cfg = settings(tmp_path)
    source_path = _source_failure(monkeypatch, cfg, "raw_only")
    run_id = "forced-recovery-id"
    target = getattr(cfg, directory) / f"{TRADE_DATE}_{run_id}{suffix}"
    missing = tmp_path / "must-not-be-created"
    try:
        target.symlink_to(missing)
    except OSError as exc:
        pytest.skip(f"Symlink creation unavailable: {exc}")
    monkeypatch.setattr(models, "uuid4", lambda: run_id)
    _forbid_opend(monkeypatch)
    with pytest.raises(FileExistsError):
        MarketVault(cfg).recover_history_from_raw(source_path)
    assert target.is_symlink()
    assert not missing.exists()
    assert len(list(cfg.data_root.rglob("*.parquet"))) == 1


def test_collection_quality_failure_never_publishes_terminal_catalog_run(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    install_collector(monkeypatch, {"US.SPY": raw_frame("US.SPY")})
    recorded = []

    def fail_quality(_self, run_id, _results):
        recorded.append(run_id)
        raise RuntimeError("quality recording failed")

    monkeypatch.setattr(Catalog, "record_quality", fail_quality)
    with pytest.raises(RuntimeError, match="quality recording failed"):
        service_module.collect_history(cfg, TRADE_DATE, ["US.SPY"], "1m", "ALL", "NONE")
    rows = _old_catalog_rows(cfg, recorded[0])
    assert rows["ingestion_runs"] == []
    assert len(rows["market_bar_snapshot_pairs"]) == 1
    assert not Catalog(cfg).completed_market_bar_items(
        symbols=["US.SPY"], trade_dates=[TRADE_DATE], interval="1m", requested_session="ALL",
        adjustment="NONE", source_schema_version=cfg.source_schema_version,
    )


@pytest.mark.parametrize("fault", ["lineage", "quality"])
def test_recovery_lineage_and_quality_precede_terminal_run(monkeypatch, tmp_path, fault):
    cfg = settings(tmp_path)
    source_path = _source_failure(monkeypatch, cfg, "raw_only")
    source_id = json.loads(source_path.read_bytes())["run_id"]
    old_rows = _old_catalog_rows(cfg, source_id)
    _forbid_opend(monkeypatch)
    actual_quality = Catalog.record_quality
    actual_run = Catalog.record_run
    terminal_calls = []
    quality_calls = []

    def record_quality(self, run_id, results):
        lineage_path = cfg.manifest_dir / f"{TRADE_DATE}_{run_id}.recovery.json"
        assert lineage_path.is_file()
        quality_calls.append(run_id)
        if fault == "quality":
            raise RuntimeError("recovery quality failed")
        return actual_quality(self, run_id, results)

    def record_run(self, manifest):
        terminal_calls.append(manifest.run_id)
        return actual_run(self, manifest)

    monkeypatch.setattr(Catalog, "record_quality", record_quality)
    monkeypatch.setattr(Catalog, "record_run", record_run)
    if fault == "lineage":
        def fail_lineage(*_args, **_kwargs):
            raise RuntimeError("lineage publication failed")
        monkeypatch.setattr(service_module, "_write_file_no_replace", fail_lineage)
    with pytest.raises(RuntimeError, match="failed"):
        MarketVault(cfg).recover_history_from_raw(source_path)
    assert terminal_calls == []
    assert len(quality_calls) == (1 if fault == "quality" else 0)
    assert _old_catalog_rows(cfg, source_id) == old_rows
    assert not Catalog(cfg).completed_market_bar_items(
        symbols=["US.SPY"], trade_dates=[TRADE_DATE], interval="1m", requested_session="ALL",
        adjustment="NONE", source_schema_version=cfg.source_schema_version,
    )


def test_recovery_quality_fail_result_is_not_completion(monkeypatch, tmp_path, capsys):
    cfg = settings(tmp_path)
    source_path = _source_failure(monkeypatch, cfg, "raw_only")
    _forbid_opend(monkeypatch)
    monkeypatch.setattr(service_module, "run_bar_quality_checks", lambda _frame: [QualityResult("replay", "FAIL")])
    settings_path = _recovery_settings_file(cfg)
    assert cli_main(["--settings", str(settings_path), "recover-history", "--manifest", str(source_path)]) == 2
    recovered = json.loads(capsys.readouterr().out)
    assert recovered["status"] == "PARTIAL"
    assert _old_catalog_rows(cfg, recovered["run_id"])["quality_results"][0][2] == "FAIL"
    assert not Catalog(cfg).completed_market_bar_items(
        symbols=["US.SPY"], trade_dates=[TRADE_DATE], interval="1m", requested_session="ALL",
        adjustment="NONE", source_schema_version=cfg.source_schema_version,
    )


def test_recovery_cli_refusal_is_structured_and_nonzero(monkeypatch, tmp_path, capsys):
    cfg = settings(tmp_path)
    settings_path = _recovery_settings_file(cfg)
    _forbid_opend(monkeypatch)
    assert cli_main([
        "--settings", str(settings_path), "recover-history", "--manifest", str(tmp_path / "missing.json"),
    ]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "FAILED"
    assert "missing.json" in result["error"]


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


def test_record_run_replacement_rolls_back_atomically_and_retries(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    catalog = Catalog(cfg)
    original = RunManifest(
        requested_trade_date=TRADE_DATE,
        requested_symbols=["US.SPY"],
        interval="1m",
        session="ALL",
        adjustment="NONE",
        run_id="replace-run",
        status="FAILED",
        config_hash="original-config",
    )
    unrelated = RunManifest(
        requested_trade_date=TRADE_DATE,
        requested_symbols=["US.QQQ"],
        interval="1m",
        session="ALL",
        adjustment="NONE",
        run_id="unrelated-run",
        status="SUCCESS",
        config_hash="unrelated-config",
    )
    catalog.record_run(original)
    catalog.record_run(unrelated)

    replacement = RunManifest(
        requested_trade_date=TRADE_DATE,
        requested_symbols=["US.SPY"],
        interval="1m",
        session="ALL",
        adjustment="NONE",
        run_id="replace-run",
        status="SUCCESS",
        successful_symbols=["US.SPY"],
        row_count=2,
        config_hash="replacement-config",
        snapshot_binding_mode="REGISTERED_PER_SYMBOL",
    )

    def fail_after_delete(_con, _manifest):
        raise RuntimeError("injected insert failure")

    with monkeypatch.context() as patch:
        patch.setattr(
            Catalog,
            "_insert_ingestion_run_row",
            staticmethod(fail_after_delete),
        )
        with pytest.raises(RuntimeError, match="injected insert failure"):
            catalog.record_run(replacement)

    with catalog.connect() as con:
        rows = con.execute(
            """
            SELECT run_id, status, config_hash, snapshot_binding_mode
            FROM ingestion_runs
            ORDER BY run_id
            """
        ).fetchall()
    assert rows == [
        ("replace-run", "FAILED", "original-config", None),
        ("unrelated-run", "SUCCESS", "unrelated-config", None),
    ]

    catalog.record_run(replacement)
    with catalog.connect() as con:
        rows = con.execute(
            """
            SELECT run_id, status, successful_symbols, row_count, config_hash,
                   snapshot_binding_mode
            FROM ingestion_runs
            ORDER BY run_id
            """
        ).fetchall()
    assert rows == [
        (
            "replace-run",
            "SUCCESS",
            '["US.SPY"]',
            2,
            "replacement-config",
            "REGISTERED_PER_SYMBOL",
        ),
        (
            "unrelated-run",
            "SUCCESS",
            "[]",
            0,
            "unrelated-config",
            None,
        ),
    ]


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


def test_registered_run_completion_rejects_all_symbols_when_one_pair_disappears(
    monkeypatch, tmp_path
):
    cfg = settings(tmp_path)
    manifest = collect(
        monkeypatch,
        cfg,
        {"US.SPY": raw_frame("US.SPY"), "US.QQQ": raw_frame("US.QQQ")},
    )
    catalog = Catalog(cfg)
    completion_kwargs = {
        "symbols": ["US.SPY", "US.QQQ"],
        "interval": "1m",
        "requested_session": "ALL",
        "adjustment": "NONE",
        "source_schema_version": cfg.source_schema_version,
    }
    expected_items = {("US.SPY", TRADE_DATE), ("US.QQQ", TRADE_DATE)}

    assert catalog.completed_market_bar_items(
        **completion_kwargs, trade_dates=[TRADE_DATE]
    ) == expected_items
    assert set(
        catalog.latest_complete_market_bar_snapshots(
            **completion_kwargs, trade_dates=[TRADE_DATE]
        )
    ) == expected_items
    assert catalog.latest_completed_market_bar_dates(
        **completion_kwargs, end_date=TRADE_DATE
    ) == {"US.SPY": TRADE_DATE, "US.QQQ": TRADE_DATE}

    with catalog.connect() as con:
        con.execute(
            "DELETE FROM market_bar_snapshot_pairs WHERE run_id = ? AND symbol = 'US.QQQ'",
            [manifest.run_id],
        )

    assert not catalog.completed_market_bar_items(
        **completion_kwargs, trade_dates=[TRADE_DATE]
    )
    assert not catalog.latest_complete_market_bar_snapshots(
        **completion_kwargs, trade_dates=[TRADE_DATE]
    )
    assert not catalog.latest_completed_market_bar_dates(
        **completion_kwargs, end_date=TRADE_DATE
    )
    assert catalog.incomplete_market_bar_item_reasons(
        **completion_kwargs, trade_dates=[TRADE_DATE]
    ) == {
        ("US.SPY", TRADE_DATE): ["SNAPSHOT_BINDING_INVALID"],
        ("US.QQQ", TRADE_DATE): ["SNAPSHOT_BINDING_INVALID"],
    }
    refused = purge_for(cfg, ["US.SPY"])
    assert refused.status == "REFUSED"
    assert any(
        item["code"] == "REGISTERED_RUN_SYMBOL_MISMATCH"
        for item in refused.refusal_reasons
    )


def test_registered_run_completion_rejects_registry_symbol_absent_from_success_set(
    monkeypatch, tmp_path
):
    cfg = settings(tmp_path)
    manifest = collect(
        monkeypatch,
        cfg,
        {"US.SPY": raw_frame("US.SPY"), "US.QQQ": raw_frame("US.QQQ")},
    )
    catalog = Catalog(cfg)
    with catalog.connect() as con:
        con.execute(
            "UPDATE ingestion_runs SET successful_symbols = '[\"US.SPY\"]' "
            "WHERE run_id = ?",
            [manifest.run_id],
        )

    completion_kwargs = {
        "symbols": ["US.SPY", "US.QQQ"],
        "interval": "1m",
        "requested_session": "ALL",
        "adjustment": "NONE",
        "source_schema_version": cfg.source_schema_version,
    }
    assert not catalog.completed_market_bar_items(
        **completion_kwargs, trade_dates=[TRADE_DATE]
    )
    assert not catalog.latest_complete_market_bar_snapshots(
        **completion_kwargs, trade_dates=[TRADE_DATE]
    )
    assert not catalog.latest_completed_market_bar_dates(
        **completion_kwargs, end_date=TRADE_DATE
    )
    assert catalog.incomplete_market_bar_item_reasons(
        **completion_kwargs, trade_dates=[TRADE_DATE]
    ) == {
        ("US.SPY", TRADE_DATE): ["SNAPSHOT_BINDING_INVALID"],
        ("US.QQQ", TRADE_DATE): ["SNAPSHOT_BINDING_INVALID"],
    }


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


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("raw_file", "wrong-raw.parquet"),
        ("symbol", "US.WRONG"),
    ],
)
def test_registered_pair_identity_drift_refuses_before_mutation(
    monkeypatch, tmp_path, column, value
):
    cfg = settings(tmp_path)
    manifest = collect(monkeypatch, cfg, {"US.SPY": raw_frame("US.SPY")})
    sealed = purge_for(cfg, ["US.SPY"])
    with Catalog(cfg).connect() as con:
        con.execute(
            f"UPDATE market_bar_snapshot_pairs SET {column} = ? "
            "WHERE run_id = ? AND symbol = 'US.SPY'",
            [value, manifest.run_id],
        )
    with pytest.raises(PurgeError, match="snapshot-pair binding drifted"):
        purge_execute(cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}")
    assert Path(manifest.raw_file).exists() and Path(manifest.curated_file).exists()


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("DELETE FROM ingestion_runs WHERE run_id = ?", "UNREGISTERED_SNAPSHOT"),
        ("UPDATE ingestion_runs SET status = 'RUNNING' WHERE run_id = ?", "ACTIVE_RUN"),
        (
            "UPDATE ingestion_runs SET successful_symbols = '[]' WHERE run_id = ?",
            "REGISTERED_RUN_SYMBOL_MISMATCH",
        ),
    ],
)
def test_registered_run_authority_corruption_refuses_planning(
    monkeypatch, tmp_path, mutation, expected_code
):
    cfg = settings(tmp_path)
    collect(monkeypatch, cfg, {"US.SPY": raw_frame("US.SPY")})
    catalog = Catalog(cfg)
    with catalog.connect() as con:
        run_id = con.execute(
            "SELECT run_id FROM ingestion_runs WHERE snapshot_binding_mode = ?",
            ["REGISTERED_PER_SYMBOL"],
        ).fetchone()[0]
        con.execute(mutation, [run_id])
    refused = purge_for(cfg, ["US.SPY"])
    assert refused.status == "REFUSED"
    assert any(item["code"] == expected_code for item in refused.refusal_reasons)


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
