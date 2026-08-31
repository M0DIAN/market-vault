from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from market_vault import service as service_module
from market_vault import purge as purge_module
from market_vault.console.backend import ConsoleBackend
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars
from market_vault.purge import (
    EXACT_SCOPE,
    PURGE_PLAN_VERSION,
    PURGE_PLAN_VERSION_V3,
    PURGE_RESULT_VERSION_V3,
    SUPERSEDED_ONLY,
    PurgeError,
    purge_execute,
    purge_plan,
)
from market_vault.storage import Catalog, ParquetStore


TRADE_DATE = date(2026, 8, 3)


def settings(tmp_path: Path, *, schema: str = "10.9") -> Settings:
    return Settings(
        project_root=tmp_path,
        opend_host="127.0.0.1",
        opend_port=11111,
        data_root=tmp_path / "data",
        catalog_path=tmp_path / "catalog" / "market_vault.duckdb",
        manifest_dir=tmp_path / "manifests",
        report_dir=tmp_path / "reports",
        source_schema_version=schema,
        request_pause_seconds=0,
    )


def raw_frame(symbol: str, close: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "code": [symbol, symbol],
            "name": [symbol, symbol],
            "time_key": [
                f"{TRADE_DATE.isoformat()} 09:30:00",
                f"{TRADE_DATE.isoformat()} 09:31:00",
            ],
            "open": [close, close + 0.1],
            "high": [close + 1, close + 1.1],
            "low": [close - 1, close - 0.9],
            "close": [close, close + 0.5],
            "volume": [100, 120],
        }
    )


def collect(
    monkeypatch: pytest.MonkeyPatch,
    cfg: Settings,
    *,
    symbol: str = "US.SPY",
    close: float,
    interval: str = "1m",
    session: str = "ALL",
    adjustment: str = "NONE",
):
    frame = raw_frame(symbol, close)

    class Collector:
        def __init__(self, _settings):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def fetch_history(self, code, **_kwargs):
            assert code == symbol
            return frame.copy()

    monkeypatch.setattr(service_module, "MoomooHistoryCollector", Collector)
    return service_module.collect_history(
        cfg, TRADE_DATE, [symbol], interval, session, adjustment
    )


def legacy_pair(
    cfg: Settings,
    symbols: list[str],
    *,
    run_id: str = "legacy-old",
) -> tuple[RunManifest, Path, Path]:
    raw = pd.concat(
        [raw_frame(symbol, 50 + index) for index, symbol in enumerate(symbols)],
        ignore_index=True,
    )
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
    manifest.finished_at = datetime(2026, 8, 3, tzinfo=timezone.utc)
    catalog = Catalog(cfg)
    catalog.record_run(manifest)
    catalog.record_quality(run_id, [QualityResult("fixture", "PASS")])
    return manifest, raw_path, curated_path


def collect_multi(
    monkeypatch: pytest.MonkeyPatch,
    cfg: Settings,
    responses: dict[str, pd.DataFrame | Exception],
):
    class Collector:
        def __init__(self, _settings):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def fetch_history(self, code, **_kwargs):
            result = responses[code]
            if isinstance(result, Exception):
                raise result
            return result.copy()

    monkeypatch.setattr(service_module, "MoomooHistoryCollector", Collector)
    return service_module.collect_history(
        cfg, TRADE_DATE, list(responses), "1m", "ALL", "NONE"
    )


def plan(cfg: Settings, *, cleanup_policy: str = SUPERSEDED_ONLY):
    return purge_plan(
        cfg,
        source=cfg.source,
        symbols=["US.SPY"],
        start_date=TRADE_DATE,
        end_date=TRADE_DATE,
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source_schema_version=cfg.source_schema_version,
        cleanup_policy=cleanup_policy,
    )


def test_one_complete_version_has_one_retained_and_zero_targets(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    current = collect(monkeypatch, cfg, close=100)

    sealed = plan(cfg)

    assert sealed.plan_version == PURGE_PLAN_VERSION_V3
    assert sealed.cleanup_policy == SUPERSEDED_ONLY
    assert sealed.status == "PLANNED"
    assert sealed.targets == ()
    assert len(sealed.retained_current_snapshots) == 1
    assert sealed.retained_current_snapshots[0]["ingestion_run_id"] == current.run_id
    assert sealed.summary["logical_key_count"] == 1
    assert sealed.summary["retained_snapshot_count"] == 1
    assert sealed.summary["superseded_snapshot_count"] == 0


def test_two_complete_versions_target_old_and_keep_latest(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    old = collect(monkeypatch, cfg, close=100)
    current = collect(monkeypatch, cfg, close=200)

    sealed = plan(cfg)

    assert sealed.status == "PLANNED"
    assert [item["ingestion_run_id"] for item in sealed.targets] == [old.run_id]
    assert [item["ingestion_run_id"] for item in sealed.retained_current_snapshots] == [
        current.run_id
    ]
    assert len(sealed.target_to_retained) == 1
    assert sealed.target_to_retained[0]["superseded_run_id"] == old.run_id
    assert sealed.target_to_retained[0]["retained_run_id"] == current.run_id
    assert sealed.summary["superseded_snapshot_count"] == 1
    assert sealed.summary["raw_file_count"] == 1
    assert sealed.summary["curated_file_count"] == 1
    assert sealed.summary["raw_bytes"] == Path(old.raw_file).stat().st_size
    assert sealed.summary["curated_bytes"] == Path(old.curated_file).stat().st_size
    assert sealed.summary["total_quarantine_bytes"] == (
        Path(old.raw_file).stat().st_size + Path(old.curated_file).stat().st_size
    )


def test_three_complete_versions_target_two_and_execute_without_latest_loss(
    monkeypatch, tmp_path
):
    cfg = settings(tmp_path)
    old_a = collect(monkeypatch, cfg, close=100)
    old_b = collect(monkeypatch, cfg, close=200)
    current = collect(monkeypatch, cfg, close=300)
    sealed = plan(cfg)
    old_paths = {
        Path(old_a.raw_file),
        Path(old_a.curated_file),
        Path(old_b.raw_file),
        Path(old_b.curated_file),
    }
    assert len(sealed.targets) == 2
    assert len({item["snapshot_id"] for item in sealed.targets}) == 2
    assert len({item["retained_snapshot_id"] for item in sealed.target_to_retained}) == 1
    complete = Catalog(cfg).complete_market_bar_snapshots(
        symbols=["US.SPY"],
        trade_dates=[TRADE_DATE],
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source_schema_version=cfg.source_schema_version,
    )
    assert [item.ingestion_run_id for item in complete] == [
        current.run_id,
        old_b.run_id,
        old_a.run_id,
    ]

    result = purge_execute(
        cfg,
        plan_id=sealed.plan_id,
        confirmation=f"PURGE {sealed.plan_id}",
    )

    assert result.result_version == PURGE_RESULT_VERSION_V3
    assert result.cleanup_policy == SUPERSEDED_ONLY
    assert result.status == "SUCCESS"
    assert all(not path.exists() for path in old_paths)
    assert Path(current.raw_file).exists()
    assert Path(current.curated_file).exists()
    assert len(list((cfg.data_root / "quarantine").rglob("*.parquet"))) == 4
    refs = Catalog(cfg).latest_complete_market_bar_snapshots(
        symbols=["US.SPY"],
        trade_dates=[TRADE_DATE],
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source_schema_version=cfg.source_schema_version,
    )
    assert refs[("US.SPY", TRADE_DATE)].ingestion_run_id == current.run_id


def test_default_exact_scope_still_writes_v2(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    collect(monkeypatch, cfg, close=100)

    sealed = plan(cfg, cleanup_policy=EXACT_SCOPE)
    payload = json.loads(Path(sealed.plan_file).read_text(encoding="utf-8"))

    assert sealed.plan_version == PURGE_PLAN_VERSION
    assert sealed.cleanup_policy == EXACT_SCOPE
    assert "cleanup_policy" not in payload
    assert "retained_current_snapshots" not in payload
    assert "target_to_retained" not in payload


def test_unknown_cleanup_policy_rejected_before_plan_write(tmp_path):
    cfg = settings(tmp_path)
    with pytest.raises(ValueError, match="unknown cleanup_policy"):
        plan(cfg, cleanup_policy="FUTURE")
    assert not list(cfg.manifest_dir.rglob("*.json"))


def test_wrong_confirmation_remains_rejected(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    collect(monkeypatch, cfg, close=100)
    collect(monkeypatch, cfg, close=200)
    sealed = plan(cfg)
    with pytest.raises(PurgeError, match="confirmation must be exactly"):
        purge_execute(cfg, plan_id=sealed.plan_id, confirmation="PURGE WRONG")


@pytest.mark.parametrize(
    ("changed", "value"),
    [
        ("interval", "5m"),
        ("session", "RTH"),
        ("adjustment", "QFQ"),
    ],
)
def test_different_request_dimension_forms_a_separate_group(
    monkeypatch, tmp_path, changed, value
):
    cfg = settings(tmp_path)
    collect(monkeypatch, cfg, close=100)
    arguments = {"interval": "1m", "session": "ALL", "adjustment": "NONE"}
    arguments[changed] = value
    collect(monkeypatch, cfg, close=200, **arguments)

    sealed = plan(cfg)

    assert sealed.status == "PLANNED"
    assert sealed.summary["logical_key_count"] == 1
    assert sealed.summary["superseded_snapshot_count"] == 0


def test_different_schema_version_forms_a_separate_group(monkeypatch, tmp_path):
    old_cfg = settings(tmp_path, schema="10.9")
    collect(monkeypatch, old_cfg, close=100)
    new_cfg = settings(tmp_path, schema="11.0")
    collect(monkeypatch, new_cfg, close=200)

    old_plan = plan(old_cfg)
    new_plan = plan(new_cfg)

    assert old_plan.summary["superseded_snapshot_count"] == 0
    assert new_plan.summary["superseded_snapshot_count"] == 0


def test_failed_newer_run_does_not_supersede_complete_snapshot(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    current = collect(monkeypatch, cfg, close=100)
    failed = RunManifest(
        requested_trade_date=TRADE_DATE,
        requested_symbols=["US.SPY"],
        interval="1m",
        session="ALL",
        adjustment="NONE",
        snapshot_binding_mode="REGISTERED_PER_SYMBOL",
    )
    failed.status = "FAILED"
    failed.finished_at = datetime.now(timezone.utc)
    Catalog(cfg).record_run(failed)

    sealed = plan(cfg)

    assert sealed.status == "PLANNED"
    assert sealed.targets == ()
    assert sealed.retained_current_snapshots[0]["ingestion_run_id"] == current.run_id


def test_quality_fail_newer_run_does_not_supersede_or_become_unregistered(
    monkeypatch, tmp_path
):
    cfg = settings(tmp_path)
    old = collect(monkeypatch, cfg, close=100)
    newer = collect(monkeypatch, cfg, close=200)
    Catalog(cfg).record_quality(newer.run_id, [QualityResult("fixture", "FAIL")])

    sealed = plan(cfg)

    assert sealed.status == "PLANNED"
    assert sealed.targets == ()
    assert sealed.retained_current_snapshots[0]["ingestion_run_id"] == old.run_id
    assert not any(
        item["code"] == "UNREGISTERED_SNAPSHOT" for item in sealed.refusal_reasons
    )


def test_partial_run_registered_symbol_uses_existing_complete_eligibility(
    monkeypatch, tmp_path
):
    cfg = settings(tmp_path)
    old = collect(monkeypatch, cfg, close=100)
    partial = collect_multi(
        monkeypatch,
        cfg,
        {
            "US.SPY": raw_frame("US.SPY", 200),
            "US.QQQ": RuntimeError("fetch failed"),
        },
    )

    sealed = plan(cfg)

    assert partial.status == "PARTIAL"
    assert [item["ingestion_run_id"] for item in sealed.targets] == [old.run_id]
    assert sealed.retained_current_snapshots[0]["ingestion_run_id"] == partial.run_id


def test_registered_symbol_is_targeted_without_sibling_from_same_run(
    monkeypatch, tmp_path
):
    cfg = settings(tmp_path)
    old = collect_multi(
        monkeypatch,
        cfg,
        {
            "US.SPY": raw_frame("US.SPY", 100),
            "US.QQQ": raw_frame("US.QQQ", 110),
        },
    )
    old_pairs = {
        pair.symbol: pair
        for pair in Catalog(cfg).market_bar_snapshot_pairs_for_run(old.run_id)
    }
    collect(monkeypatch, cfg, close=200)

    sealed = plan(cfg)

    assert len(sealed.targets) == 1
    assert sealed.targets[0]["snapshot_pair_binding"]["symbol"] == "US.SPY"
    purge_execute(
        cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}"
    )
    assert Path(old_pairs["US.QQQ"].raw_file).exists()
    assert Path(old_pairs["US.QQQ"].curated_file).exists()


def test_matching_unregistered_snapshot_refuses(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    collect(monkeypatch, cfg, close=100)
    stray = raw_frame("US.SPY", 999)
    stray["requested_trade_date"] = TRADE_DATE
    stray["interval"] = "1m"
    stray["requested_session"] = "ALL"
    stray["adjustment"] = "NONE"
    stray["ingestion_run_id"] = "unregistered"
    curated = normalize_bars(
        stray,
        requested_trade_date=TRADE_DATE,
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source=cfg.source,
        source_schema_version=cfg.source_schema_version,
        run_id="unregistered",
    )
    store = ParquetStore(cfg)
    store.write_raw(
        stray, TRADE_DATE, "1m", ["US.SPY"], "ALL", "NONE", "unregistered"
    )
    store.write_curated(
        curated, TRADE_DATE, "1m", ["US.SPY"], "ALL", "NONE", "unregistered"
    )

    sealed = plan(cfg)

    assert sealed.status == "REFUSED"
    assert sum(
        item["code"] == "UNREGISTERED_SNAPSHOT"
        for item in sealed.refusal_reasons
    ) == 2


def test_matching_running_run_refuses(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    collect(monkeypatch, cfg, close=100)
    running = RunManifest(
        requested_trade_date=TRADE_DATE,
        requested_symbols=["US.SPY"],
        interval="1m",
        session="ALL",
        adjustment="NONE",
        snapshot_binding_mode="REGISTERED_PER_SYMBOL",
    )
    running.status = "RUNNING"
    Catalog(cfg).record_run(running)

    sealed = plan(cfg)

    assert sealed.status == "REFUSED"
    assert any(item["code"] == "ACTIVE_RUN" for item in sealed.refusal_reasons)


def test_retained_winner_disappears_after_review_refuses_before_movement(
    monkeypatch, tmp_path
):
    cfg = settings(tmp_path)
    old = collect(monkeypatch, cfg, close=100)
    current = collect(monkeypatch, cfg, close=200)
    sealed = plan(cfg)
    Path(current.curated_file).unlink()

    with pytest.raises(PurgeError, match="retained|missing"):
        purge_execute(
            cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}"
        )

    assert Path(old.raw_file).exists() and Path(old.curated_file).exists()


def test_new_complete_snapshot_after_review_makes_plan_stale(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    old = collect(monkeypatch, cfg, close=100)
    collect(monkeypatch, cfg, close=200)
    sealed = plan(cfg)
    collect(monkeypatch, cfg, close=300)

    with pytest.raises(PurgeError, match="new or unplanned|winner changed"):
        purge_execute(
            cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}"
        )

    assert Path(old.raw_file).exists() and Path(old.curated_file).exists()


def test_unregistered_snapshot_appearing_after_review_refuses_before_movement(
    monkeypatch, tmp_path
):
    cfg = settings(tmp_path)
    old = collect(monkeypatch, cfg, close=100)
    collect(monkeypatch, cfg, close=200)
    sealed = plan(cfg)
    stray = raw_frame("US.SPY", 999)
    stray["requested_trade_date"] = TRADE_DATE
    stray["interval"] = "1m"
    stray["requested_session"] = "ALL"
    stray["adjustment"] = "NONE"
    stray["ingestion_run_id"] = "late-unregistered"
    curated = normalize_bars(
        stray,
        requested_trade_date=TRADE_DATE,
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source=cfg.source,
        source_schema_version=cfg.source_schema_version,
        run_id="late-unregistered",
    )
    store = ParquetStore(cfg)
    store.write_raw(
        stray,
        TRADE_DATE,
        "1m",
        ["US.SPY"],
        "ALL",
        "NONE",
        "late-unregistered",
    )
    store.write_curated(
        curated,
        TRADE_DATE,
        "1m",
        ["US.SPY"],
        "ALL",
        "NONE",
        "late-unregistered",
    )

    with pytest.raises(PurgeError, match="unregistered or unplanned"):
        purge_execute(
            cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}"
        )

    assert Path(old.raw_file).exists() and Path(old.curated_file).exists()


def test_running_run_appearing_after_review_refuses_before_movement(
    monkeypatch, tmp_path
):
    cfg = settings(tmp_path)
    old = collect(monkeypatch, cfg, close=100)
    collect(monkeypatch, cfg, close=200)
    sealed = plan(cfg)
    running = RunManifest(
        requested_trade_date=TRADE_DATE,
        requested_symbols=["US.SPY"],
        interval="1m",
        session="ALL",
        adjustment="NONE",
        snapshot_binding_mode="REGISTERED_PER_SYMBOL",
    )
    running.status = "RUNNING"
    Catalog(cfg).record_run(running)

    with pytest.raises(PurgeError, match="RUNNING"):
        purge_execute(
            cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}"
        )

    assert Path(old.raw_file).exists() and Path(old.curated_file).exists()


@pytest.mark.parametrize("which", ["target", "retained"])
def test_target_or_retained_registry_binding_drift_refuses_before_movement(
    monkeypatch, tmp_path, which
):
    cfg = settings(tmp_path)
    old = collect(monkeypatch, cfg, close=100)
    current = collect(monkeypatch, cfg, close=200)
    sealed = plan(cfg)
    run_id = old.run_id if which == "target" else current.run_id
    with Catalog(cfg).connect() as con:
        con.execute(
            "UPDATE market_bar_snapshot_pairs SET row_count = row_count + 1 "
            "WHERE run_id = ? AND symbol = 'US.SPY'",
            [run_id],
        )

    with pytest.raises(PurgeError, match="snapshot-pair binding drifted"):
        purge_execute(
            cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}"
        )

    assert Path(old.raw_file).exists() and Path(old.curated_file).exists()


@pytest.mark.parametrize("which", ["target", "retained"])
def test_target_or_retained_identity_drift_refuses_before_movement(
    monkeypatch, tmp_path, which
):
    cfg = settings(tmp_path)
    old = collect(monkeypatch, cfg, close=100)
    current = collect(monkeypatch, cfg, close=200)
    sealed = plan(cfg)
    path = Path(old.curated_file if which == "target" else current.curated_file)
    frame = pd.read_parquet(path)
    frame.loc[0, "close"] = 9999.0
    frame.to_parquet(path, index=False)

    with pytest.raises(PurgeError, match="identity changed"):
        purge_execute(
            cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}"
        )

    assert Path(old.raw_file).exists()


def test_legacy_multisymbol_pair_targets_only_when_every_symbol_is_superseded(
    monkeypatch, tmp_path
):
    cfg = settings(tmp_path)
    legacy, raw_path, curated_path = legacy_pair(cfg, ["US.SPY", "US.QQQ"])
    current = collect_multi(
        monkeypatch,
        cfg,
        {
            "US.SPY": raw_frame("US.SPY", 200),
            "US.QQQ": raw_frame("US.QQQ", 300),
        },
    )

    sealed = plan(cfg)

    assert sealed.status == "PLANNED"
    assert len(sealed.targets) == 1
    assert sealed.targets[0]["ingestion_run_id"] == legacy.run_id
    assert {item["logical_key"]["code"] for item in sealed.target_to_retained} == {
        "US.SPY",
        "US.QQQ",
    }
    assert {item["retained_run_id"] for item in sealed.target_to_retained} == {
        current.run_id
    }
    assert raw_path.exists() and curated_path.exists()


def test_legacy_multisymbol_pair_refuses_when_one_symbol_is_not_superseded(
    monkeypatch, tmp_path
):
    cfg = settings(tmp_path)
    _, raw_path, curated_path = legacy_pair(cfg, ["US.SPY", "US.QQQ"])
    collect(monkeypatch, cfg, close=200)

    sealed = plan(cfg)

    assert sealed.status == "REFUSED"
    reason = next(
        item
        for item in sealed.refusal_reasons
        if item["code"] == "LEGACY_PAIR_NOT_FULLY_SUPERSEDED"
    )
    assert reason["symbols"] == ["US.QQQ"]
    assert raw_path.exists() and curated_path.exists()


def test_legacy_multisymbol_whole_pair_executes_once_and_keeps_both_winners(
    monkeypatch, tmp_path
):
    cfg = settings(tmp_path)
    _, raw_path, curated_path = legacy_pair(cfg, ["US.SPY", "US.QQQ"])
    current = collect_multi(
        monkeypatch,
        cfg,
        {
            "US.SPY": raw_frame("US.SPY", 200),
            "US.QQQ": raw_frame("US.QQQ", 300),
        },
    )
    sealed = plan(cfg)

    result = purge_execute(
        cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}"
    )

    assert result.status == "SUCCESS"
    assert not raw_path.exists() and not curated_path.exists()
    assert len(result.moved_files) == 2
    refs = Catalog(cfg).latest_complete_market_bar_snapshots(
        symbols=["US.SPY", "US.QQQ"],
        trade_dates=[TRADE_DATE],
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source_schema_version=cfg.source_schema_version,
    )
    assert {ref.ingestion_run_id for ref in refs.values()} == {current.run_id}


def test_one_sided_candidate_pair_refuses_planning(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    old = collect(monkeypatch, cfg, close=100)
    collect(monkeypatch, cfg, close=200)
    Path(old.raw_file).unlink()

    sealed = plan(cfg)

    assert sealed.status == "REFUSED"
    assert any(
        item["code"] == "UNSAFE_OR_MISSING_TARGET"
        for item in sealed.refusal_reasons
    )


def test_precommit_failure_rolls_back_superseded_pair(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    old = collect(monkeypatch, cfg, close=100)
    current = collect(monkeypatch, cfg, close=200)
    sealed = plan(cfg)

    def fail_commit(self, *args, **kwargs):
        raise RuntimeError("injected Catalog commit failure")

    monkeypatch.setattr(Catalog, "commit_purge_operation", fail_commit)
    with pytest.raises(PurgeError, match="injected Catalog commit failure"):
        purge_execute(
            cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}"
        )

    assert Path(old.raw_file).exists() and Path(old.curated_file).exists()
    assert Path(current.raw_file).exists() and Path(current.curated_file).exists()
    assert not list((cfg.data_root / "quarantine").rglob("*.parquet"))
    assert Catalog(cfg).purge_operation(sealed.plan_id)["state"] != "SUCCESS"


def test_postcommit_retry_republishes_exact_v3_result(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    old = collect(monkeypatch, cfg, close=100)
    collect(monkeypatch, cfg, close=200)
    sealed = plan(cfg)
    real_publish = purge_module._publish_terminal_result
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("injected publication crash")
        return real_publish(*args, **kwargs)

    monkeypatch.setattr(purge_module, "_publish_terminal_result", fail_once)
    with pytest.raises(PurgeError, match="committed.*idempotent retry"):
        purge_execute(
            cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}"
        )
    assert not Path(old.raw_file).exists() and not Path(old.curated_file).exists()

    recovered = purge_execute(
        cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}"
    )
    repeated = purge_execute(
        cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}"
    )

    assert recovered.as_dict() == repeated.as_dict()
    assert recovered.result_version == PURGE_RESULT_VERSION_V3


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.pop("cleanup_policy"),
        lambda payload: payload.__setitem__("cleanup_policy", "FUTURE"),
        lambda payload: payload.__setitem__("retained_current_snapshots", []),
        lambda payload: payload.__setitem__("target_to_retained", []),
    ],
)
def test_v3_malformed_or_missing_authority_fails_closed(
    monkeypatch, tmp_path, mutation
):
    cfg = settings(tmp_path)
    collect(monkeypatch, cfg, close=100)
    collect(monkeypatch, cfg, close=200)
    sealed = plan(cfg)
    payload = json.loads(Path(sealed.plan_file).read_text(encoding="utf-8"))
    mutation(payload)
    with pytest.raises(PurgeError):
        purge_module._validate_plan_payload(payload)


def test_v2_cannot_claim_superseded_policy(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    collect(monkeypatch, cfg, close=100)
    sealed = plan(cfg, cleanup_policy=EXACT_SCOPE)
    payload = json.loads(Path(sealed.plan_file).read_text(encoding="utf-8"))
    payload["cleanup_policy"] = SUPERSEDED_ONLY
    with pytest.raises(PurgeError, match="v2 purge plan"):
        purge_module._validate_plan_payload(payload)


def test_v3_rejects_retained_snapshot_that_is_also_a_target(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    collect(monkeypatch, cfg, close=100)
    collect(monkeypatch, cfg, close=200)
    sealed = plan(cfg)
    payload = json.loads(Path(sealed.plan_file).read_text(encoding="utf-8"))
    payload["retained_current_snapshots"] = [payload["targets"][0]]
    with pytest.raises(PurgeError, match="target and retained"):
        purge_module._validate_plan_payload(payload)


def test_backend_preview_passes_policy_and_exposes_old_to_kept_review_rows(
    monkeypatch, tmp_path
):
    cfg = settings(tmp_path)
    collect(monkeypatch, cfg, close=100)
    collect(monkeypatch, cfg, close=200)
    sealed = plan(cfg)

    class Vault:
        settings = SimpleNamespace(
            source=cfg.source,
            source_schema_version=cfg.source_schema_version,
        )

        def __init__(self):
            self.calls = []

        def purge_plan(self, **kwargs):
            self.calls.append(kwargs)
            return sealed

    vault = Vault()
    backend = ConsoleBackend(vault)
    view = backend.preview_purge(
        source=cfg.source,
        symbols="US.SPY",
        start_date=TRADE_DATE.isoformat(),
        end_date=TRADE_DATE.isoformat(),
        interval="1m",
        session="ALL",
        adjustment="NONE",
        source_schema_version=cfg.source_schema_version,
        cleanup_policy=SUPERSEDED_ONLY,
    )

    assert vault.calls[0]["cleanup_policy"] == SUPERSEDED_ONLY
    assert view.items.total_rows == 1
    assert set(view.items.columns) == {
        "code",
        "requested_trade_date",
        "interval",
        "requested_session",
        "adjustment",
        "source_schema_version",
        "superseded_run_id",
        "retained_run_id",
        "superseded_ingested_at",
        "retained_ingested_at",
        "raw_bytes",
        "curated_bytes",
    }
