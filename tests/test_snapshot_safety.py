from __future__ import annotations

from datetime import date, datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pandas as pd
import pytest

import market_vault.backfill as backfill_module
from market_vault.backfill import collect_history_backfill
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars, normalize_trading_calendar
from market_vault.storage import Catalog, ParquetStore
from market_vault.storage import atomic_file
from market_vault.lifecycle import LifecycleLockError


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


def curated_bars_frame(
    cfg: Settings,
    code: str,
    trade_date: date,
    run_id: str,
    close: float = 100.5,
) -> pd.DataFrame:
    raw = history_raw_frame(code, trade_date, close=close)
    raw["requested_trade_date"] = trade_date
    raw["interval"] = "1m"
    raw["adjustment"] = "NONE"
    raw["requested_session"] = "ALL"
    raw["ingestion_run_id"] = run_id
    return normalize_bars(
        raw,
        requested_trade_date=trade_date,
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source=cfg.source,
        source_schema_version=cfg.source_schema_version,
        run_id=run_id,
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


def write_old_snapshot(
    cfg: Settings,
    *,
    code: str,
    trade_date: date,
    run_id: str,
    close: float = 100.5,
) -> None:
    """Simulate a pre-fix snapshot written under the legacy batch name."""
    store = ParquetStore(cfg)
    catalog = Catalog(cfg)
    curated = curated_bars_frame(cfg, code, trade_date, run_id, close=close)
    raw = history_raw_frame(code, trade_date, close=close)
    raw["requested_trade_date"] = trade_date
    raw["interval"] = "1m"
    raw["adjustment"] = "NONE"
    raw["requested_session"] = "ALL"
    raw["ingestion_run_id"] = run_id
    store.write_raw(raw, trade_date, "1m", [code], "ALL", "NONE", run_id=run_id)
    store.write_curated(curated, trade_date, "1m", [code], "ALL", "NONE", run_id=run_id)
    run = RunManifest(
        requested_trade_date=trade_date,
        requested_symbols=[code],
        interval="1m",
        session="ALL",
        adjustment="NONE",
        run_id=run_id,
    )
    run.successful_symbols = [code]
    run.status = "SUCCESS"
    run.finished_at = datetime.now(timezone.utc)
    catalog.record_run(run)
    catalog.record_quality(run.run_id, [QualityResult("bars_complete", "PASS")])


def test_market_bars_raw_paths_include_run_id_and_do_not_collide(tmp_path):
    cfg = settings(tmp_path)
    store = ParquetStore(cfg)
    trade_date = date(2026, 7, 1)
    frame = history_raw_frame("US.MU", trade_date)

    raw_a = store.write_raw(frame, trade_date, "1m", ["US.MU"], "ALL", "NONE", run_id="run-aaa")
    raw_b = store.write_raw(frame, trade_date, "1m", ["US.MU"], "ALL", "NONE", run_id="run-bbb")

    assert raw_a != raw_b
    assert raw_a.exists() and raw_b.exists()
    assert raw_a.name == f"batch-{ParquetStore._batch_key(['US.MU'], '1m', 'ALL', 'NONE')}-run-aaa.parquet"
    assert raw_b.name == f"batch-{ParquetStore._batch_key(['US.MU'], '1m', 'ALL', 'NONE')}-run-bbb.parquet"


def test_market_bars_curated_paths_include_run_id_and_do_not_collide(tmp_path):
    cfg = settings(tmp_path)
    store = ParquetStore(cfg)
    trade_date = date(2026, 7, 1)
    frame = curated_bars_frame(cfg, "US.MU", trade_date, "run-ccc")

    curated_a = store.write_curated(frame, trade_date, "1m", ["US.MU"], "ALL", "NONE", run_id="run-ccc")
    curated_b = store.write_curated(frame, trade_date, "1m", ["US.MU"], "ALL", "NONE", run_id="run-ddd")

    assert curated_a != curated_b
    assert curated_a.exists() and curated_b.exists()
    assert "run-ccc" in curated_a.name
    assert "run-ddd" in curated_b.name


def test_market_bars_reject_unsafe_run_id(tmp_path):
    cfg = settings(tmp_path)
    store = ParquetStore(cfg)
    trade_date = date(2026, 7, 1)
    frame = history_raw_frame("US.MU", trade_date)

    with pytest.raises(ValueError, match="Unsafe partition value"):
        store.write_raw(frame, trade_date, "1m", ["US.MU"], "ALL", "NONE", run_id="../../evil")
    with pytest.raises(ValueError, match="Unsafe partition value"):
        store.write_curated(frame, trade_date, "1m", ["US.MU"], "ALL", "NONE", run_id="..")


@pytest.mark.parametrize("writer_name", ["write_raw", "write_curated"])
@pytest.mark.parametrize("changed", [False, True])
def test_market_bar_existing_target_is_always_refused(tmp_path, writer_name, changed):
    cfg = settings(tmp_path)
    trade_date = date(2026, 7, 1)
    writer = getattr(ParquetStore(cfg), writer_name)
    original = curated_bars_frame(cfg, "US.MU", trade_date, "same-run")
    path = writer(original, trade_date, "1m", ["US.MU"], "ALL", "NONE", "same-run")
    original_bytes = path.read_bytes()
    unrelated = path.parent / ".unrelated.tmp"
    unrelated.write_bytes(b"another invocation")
    retry = original.copy()
    if changed:
        retry["close"] = 200.0
    with pytest.raises(FileExistsError, match="existing publication target"):
        writer(retry, trade_date, "1m", ["US.MU"], "ALL", "NONE", "same-run")
    assert path.read_bytes() == original_bytes
    assert unrelated.read_bytes() == b"another invocation"
    assert set(path.parent.iterdir()) == {path, unrelated}


@pytest.mark.parametrize("writer_name", ["write_raw", "write_curated"])
@pytest.mark.parametrize("interruption", [RuntimeError, KeyboardInterrupt])
def test_market_bar_interrupted_serialization_never_exposes_final(
    monkeypatch, tmp_path, writer_name, interruption
):
    cfg = settings(tmp_path)
    store = ParquetStore(cfg)
    trade_date = date(2026, 7, 1)
    layer = "raw" if writer_name == "write_raw" else "curated"
    final = store._path(layer, trade_date, "1m", ["US.MU"], "ALL", "NONE", "interrupted")
    final.parent.mkdir(parents=True)
    unrelated = final.parent / ".earlier-crash.tmp"
    unrelated.write_bytes(b"retain")

    def interrupted(_frame, stream, **_kwargs):
        stream.write(b"incomplete parquet serialization")
        assert not final.exists()
        assert not list(final.parent.glob("*.parquet"))
        raise interruption("serialization interrupted")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", interrupted)
    with pytest.raises(interruption, match="serialization interrupted"):
        getattr(store, writer_name)(
            history_raw_frame("US.MU", trade_date), trade_date, "1m", ["US.MU"], "ALL", "NONE", "interrupted"
        )
    assert not final.exists()
    assert set(final.parent.iterdir()) == {unrelated}
    assert unrelated.read_bytes() == b"retain"


def test_market_bar_real_no_replace_publication_race_has_one_winner(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    trade_date = date(2026, 7, 1)
    barrier = Barrier(2)
    actual_link = atomic_file.os.link

    def race_link(source, target, **kwargs):
        barrier.wait(timeout=10)
        return actual_link(source, target, **kwargs)

    monkeypatch.setattr(atomic_file.os, "link", race_link)

    def publish(close):
        try:
            path = ParquetStore(cfg).write_raw(
                history_raw_frame("US.MU", trade_date, close), trade_date,
                "1m", ["US.MU"], "ALL", "NONE", "racing-run",
            )
            return close, path
        except FileExistsError:
            return close, None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(publish, [100.5, 200.5]))
    winners = [(close, path) for close, path in results if path is not None]
    assert len(winners) == 1
    close, path = winners[0]
    assert pd.read_parquet(path)["close"].tolist() == [close]
    assert set(path.parent.iterdir()) == {path}


def test_atomic_publication_preserves_committed_final_on_cleanup_failure(monkeypatch, tmp_path):
    final = tmp_path / "snapshot.parquet"
    actual_unlink = Path.unlink

    def cannot_cleanup(path, *args, **kwargs):
        if path.name.endswith(".tmp"):
            raise PermissionError("temporary cleanup denied")
        return actual_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", cannot_cleanup)
    with pytest.raises(atomic_file.AtomicFilePublicationError, match="published") as error:
        atomic_file._write_file_no_replace(final, lambda stream: stream.write(b"complete"))
    assert error.value.published is True
    assert error.value.path == final
    assert final.read_bytes() == b"complete"
    assert error.value.temporary_path.read_bytes() == b"complete"
    assert not error.value.temporary_path.name.endswith(".parquet")


def test_atomic_publication_refuses_replaced_temporary_without_deleting_it(tmp_path):
    final = tmp_path / "snapshot.parquet"
    retained = tmp_path / "retained-owned-object.tmp"

    def substitute(stream):
        stream.write(b"owned data")
        temporary = next(tmp_path.glob(".snapshot.parquet.*.tmp"))
        temporary.rename(retained)
        temporary.write_bytes(b"foreign replacement")

    with pytest.raises(atomic_file.AtomicFilePublicationError, match="ownership changed") as error:
        atomic_file._write_file_no_replace(final, substitute)
    assert error.value.published is False
    assert not final.exists()
    assert retained.read_bytes() == b"owned data"
    assert error.value.temporary_path.read_bytes() == b"foreign replacement"


def test_atomic_publication_refuses_changed_parent_without_cleanup(tmp_path):
    parent = tmp_path / "parent"
    retained_parent = tmp_path / "retained-parent"
    final = parent / "snapshot.parquet"

    def replace_parent(stream):
        stream.write(b"owned data")
        name = next(parent.iterdir()).name
        parent.rename(retained_parent)
        parent.mkdir()
        (parent / name).write_bytes(b"foreign object")

    with pytest.raises(atomic_file.AtomicFilePublicationError, match="parent identity changed") as error:
        atomic_file._write_file_no_replace(final, replace_parent)
    assert not error.value.published
    assert not final.exists()
    assert error.value.temporary_path.read_bytes() == b"foreign object"
    assert (retained_parent / error.value.temporary_path.name).read_bytes() == b"owned data"


def test_atomic_publication_unsupported_link_has_no_overwrite_fallback(monkeypatch, tmp_path):
    final = tmp_path / "snapshot.parquet"

    def unsupported(*_args, **_kwargs):
        raise OSError("hard links unsupported on this filesystem")

    monkeypatch.setattr(atomic_file.os, "link", unsupported)
    with pytest.raises(OSError, match="hard links unsupported"):
        atomic_file._write_file_no_replace(final, lambda stream: stream.write(b"complete"))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("kind", ["directory", "symlink", "dangling_symlink", "ancestor_link", "reparse", "unverifiable"])
def test_atomic_publication_refuses_unsafe_or_existing_paths(monkeypatch, tmp_path, kind):
    from market_vault import lifecycle

    final = tmp_path / "snapshot.parquet"
    if kind == "directory":
        final.mkdir()
    elif kind in {"symlink", "dangling_symlink", "ancestor_link"}:
        target = tmp_path / "target"
        if kind == "symlink":
            target.write_bytes(b"pre-existing")
        elif kind == "ancestor_link":
            target.mkdir()
        try:
            final.symlink_to(target, target_is_directory=kind == "ancestor_link")
        except OSError as exc:
            pytest.skip(f"Symlink creation unavailable: {exc}")
        if kind == "ancestor_link":
            final = final / "child.parquet"
    elif kind == "reparse":
        monkeypatch.setattr(lifecycle, "is_junction_or_reparse", lambda path: path == final)
    else:
        def unverifiable(_path):
            raise LifecycleLockError("cannot verify Windows file attributes")
        monkeypatch.setattr(lifecycle, "is_junction_or_reparse", unverifiable)

    def forbidden_serialization(_stream):
        pytest.fail("Refused paths must not reach serialization")

    with pytest.raises((LifecycleLockError, FileExistsError)):
        atomic_file._write_file_no_replace(final, forbidden_serialization)
    assert not list(tmp_path.rglob("*.tmp"))
    if kind == "symlink":
        assert target.read_bytes() == b"pre-existing"


def test_legacy_market_bars_file_without_run_id_still_readable(tmp_path):
    cfg = settings(tmp_path)
    store = ParquetStore(cfg)
    catalog = Catalog(cfg)
    trade_date = date(2026, 7, 1)
    run_id = "legacy-run"

    # Pre-fix snapshots were written as batch-<batch_key>.parquet without a
    # run id; write one manually to prove old files keep working.
    curated = curated_bars_frame(cfg, "US.MU", trade_date, run_id)
    legacy_path = (
        cfg.data_root
        / "curated"
        / f"source={cfg.source}"
        / "dataset=market_bars"
        / "interval=1m"
        / f"requested_trade_date={trade_date.isoformat()}"
        / f"batch-{ParquetStore._batch_key(['US.MU'], '1m', 'ALL', 'NONE')}.parquet"
    )
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    curated.to_parquet(legacy_path, index=False, compression="zstd")
    run = RunManifest(
        requested_trade_date=trade_date,
        requested_symbols=["US.MU"],
        interval="1m",
        session="ALL",
        adjustment="NONE",
        run_id=run_id,
    )
    run.successful_symbols = ["US.MU"]
    run.status = "SUCCESS"
    run.finished_at = datetime.now(timezone.utc)
    catalog.record_run(run)
    catalog.record_quality(run.run_id, [QualityResult("bars_complete", "PASS")])

    completed = catalog.completed_market_bar_items(
        symbols=["US.MU"],
        trade_dates=[trade_date],
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source_schema_version=cfg.source_schema_version,
    )
    assert completed == {("US.MU", trade_date)}

    assert catalog.refresh_market_bars_view()
    with catalog.connect() as con:
        rows = con.execute(
            "SELECT code, close FROM market_bars WHERE requested_trade_date = ?",
            [trade_date],
        ).fetchall()
    assert rows == [("US.MU", 100.5)]


def test_force_recollect_does_not_overwrite_old_snapshots(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    trade_date = date(2026, 7, 1)
    write_calendar_snapshot(
        cfg,
        market="US",
        trade_dates=[trade_date],
        requested_start_date=trade_date,
        requested_end_date=trade_date,
    )
    # Old complete snapshots for both symbols.
    write_old_snapshot(cfg, code="US.MU", trade_date=trade_date, run_id="old-mu", close=100.5)
    write_old_snapshot(cfg, code="US.NVDA", trade_date=trade_date, run_id="old-nvda", close=100.5)

    new_run_ids: list[str] = []
    call_log: list[tuple[date, tuple[str, ...]]] = []

    def fake_collect_history(settings, trade_date, symbols, interval, session, adjustment):
        call_log.append((trade_date, tuple(symbols)))
        manifest = RunManifest(
            requested_trade_date=trade_date,
            requested_symbols=list(symbols),
            interval=interval.lower(),
            session=session.upper(),
            adjustment=adjustment.upper(),
        )
        # US.MU succeeds with fresh data; US.NVDA fails after the snapshot
        # was taken, mirroring a --force re-collection where the old complete
        # snapshot must survive.
        manifest.successful_symbols = ["US.MU"]
        manifest.failed_symbols = {"US.NVDA": "boom"}
        manifest.status = "PARTIAL"
        manifest.finished_at = datetime.now(timezone.utc)
        raw = history_raw_frame("US.MU", trade_date, close=200.0)
        raw["requested_trade_date"] = trade_date
        raw["interval"] = interval.lower()
        raw["adjustment"] = adjustment.upper()
        raw["requested_session"] = session.upper()
        raw["ingestion_run_id"] = manifest.run_id
        curated = normalize_bars(
            raw,
            requested_trade_date=trade_date,
            interval=interval,
            requested_session=session,
            adjustment=adjustment,
            source=settings.source,
            source_schema_version=settings.source_schema_version,
            run_id=manifest.run_id,
        )
        store = ParquetStore(settings)
        manifest.raw_file = str(store.write_raw(raw, trade_date, interval, ["US.MU"], session, adjustment, run_id=manifest.run_id))
        manifest.curated_file = str(
            store.write_curated(curated, trade_date, interval, ["US.MU"], session, adjustment, run_id=manifest.run_id)
        )
        manifest.row_count = len(curated)
        Catalog(settings).record_run(manifest)
        Catalog(settings).record_quality(manifest.run_id, [QualityResult("bars_complete", "PASS")])
        new_run_ids.append(manifest.run_id)
        return manifest

    monkeypatch.setattr(backfill_module, "_collect_history_locked", fake_collect_history)

    manifest = collect_history_backfill(
        cfg,
        symbols=["US.MU", "US.NVDA"],
        start_date=trade_date,
        end_date=trade_date,
        calendar_market="US",
        force=True,
        max_retries=0,
        retry_backoff_seconds=0,
        today=date(2026, 8, 2),
    )

    assert call_log == [(trade_date, ("US.MU", "US.NVDA"))]
    assert manifest.status == "PARTIAL"
    assert manifest.parameters["successful_dates_by_symbol"]["US.MU"] == ["2026-07-01"]
    assert manifest.parameters["failed_dates_by_symbol"]["US.NVDA"] == [
        {"date": "2026-07-01", "error": "boom"}
    ]

    store = ParquetStore(cfg)
    mu_batch_key = ParquetStore._batch_key(["US.MU"], "1m", "ALL", "NONE")
    nvda_batch_key = ParquetStore._batch_key(["US.NVDA"], "1m", "ALL", "NONE")
    old_mu_curated = (
        cfg.data_root
        / "curated"
        / f"source={cfg.source}"
        / "dataset=market_bars"
        / "interval=1m"
        / f"requested_trade_date={trade_date.isoformat()}"
        / f"batch-{mu_batch_key}-old-mu.parquet"
    )
    old_nvda_curated = old_mu_curated.parent / f"batch-{nvda_batch_key}-old-nvda.parquet"
    old_mu_raw = (
        cfg.data_root
        / "raw"
        / f"source={cfg.source}"
        / "dataset=market_bars"
        / "interval=1m"
        / f"requested_trade_date={trade_date.isoformat()}"
        / f"batch-{mu_batch_key}-old-mu.parquet"
    )
    old_nvda_raw = old_mu_raw.parent / f"batch-{nvda_batch_key}-old-nvda.parquet"

    # Old snapshot files are neither deleted nor overwritten: both the old
    # curated (close=100.5) and the raw files still exist untouched.
    assert old_mu_curated.exists()
    assert old_nvda_curated.exists()
    assert old_mu_raw.exists()
    assert old_nvda_raw.exists()
    old_mu_df = pd.read_parquet(old_mu_curated)
    assert float(old_mu_df["close"].iloc[0]) == 100.5
    assert set(old_mu_df["ingestion_run_id"]) == {"old-mu"}
    old_nvda_df = pd.read_parquet(old_nvda_curated)
    assert float(old_nvda_df["close"].iloc[0]) == 100.5
    assert set(old_nvda_df["ingestion_run_id"]) == {"old-nvda"}

    # The new snapshot exists as its own file carrying the new run id.
    assert len(new_run_ids) == 1
    new_mu_curated = old_mu_curated.parent / f"batch-{mu_batch_key}-{new_run_ids[0]}.parquet"
    assert new_mu_curated.exists()
    new_mu_df = pd.read_parquet(new_mu_curated)
    assert float(new_mu_df["close"].iloc[0]) == 200.0
    assert set(new_mu_df["ingestion_run_id"]) == {new_run_ids[0]}

    # The local query layer reads the new MU data and the old NVDA data.
    catalog = Catalog(cfg)
    assert catalog.refresh_market_bars_view()
    with catalog.connect() as con:
        rows = con.execute(
            "SELECT code, close, ingestion_run_id FROM market_bars WHERE requested_trade_date = ? ORDER BY code",
            [trade_date],
        ).fetchall()
    assert rows == [
        ("US.MU", 200.0, new_run_ids[0]),
        ("US.NVDA", 100.5, "old-nvda"),
    ]
