from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from market_vault.api import MarketVault
from market_vault.backfill import BackfillItem, BackfillPlan, collect_history_backfill
from market_vault.console.backend import ConsoleBackend
from market_vault.console.ui import ConsoleApp
from market_vault.cli import build_parser
from market_vault.lifecycle import LifecycleLockError, MarketBarLifecycleLock
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars
from market_vault.purge import PurgeError, purge_execute, purge_plan
from market_vault.storage import Catalog, ParquetStore


TRADE_DATE = date(2026, 7, 1)


def settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=tmp_path,
        opend_host="127.0.0.1",
        opend_port=11111,
        data_root=tmp_path / "data",
        catalog_path=tmp_path / "catalog" / "market_vault.duckdb",
        manifest_dir=tmp_path / "manifests",
        report_dir=tmp_path / "reports" / "data_quality",
        request_pause_seconds=0,
    )


def write_batch(
    cfg: Settings,
    *,
    symbols: list[str],
    trade_date: date = TRADE_DATE,
    run_id: str = "run-a",
) -> tuple[Path, Path]:
    frames = []
    for offset, symbol in enumerate(symbols):
        frames.append(
            pd.DataFrame(
                {
                    "code": [symbol, symbol],
                    "name": [symbol, symbol],
                    "time_key": [
                        f"{trade_date.isoformat()} 09:{30 + offset * 2:02d}:00",
                        f"{trade_date.isoformat()} 09:{31 + offset * 2:02d}:00",
                    ],
                    "open": [100.0, 100.5],
                    "high": [101.0, 101.5],
                    "low": [99.0, 99.5],
                    "close": [100.5, 101.0],
                    "volume": [100, 120],
                }
            )
        )
    source = pd.concat(frames, ignore_index=True)
    raw = source.copy()
    raw["requested_trade_date"] = trade_date
    raw["interval"] = "1m"
    raw["adjustment"] = "NONE"
    raw["requested_session"] = "ALL"
    raw["ingestion_run_id"] = run_id
    curated = normalize_bars(
        raw,
        requested_trade_date=trade_date,
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source=cfg.source,
        source_schema_version=cfg.source_schema_version,
        run_id=run_id,
    )
    store = ParquetStore(cfg)
    raw_path = store.write_raw(raw, trade_date, "1m", symbols, "ALL", "NONE", run_id)
    curated_path = store.write_curated(
        curated, trade_date, "1m", symbols, "ALL", "NONE", run_id
    )
    manifest = RunManifest(
        requested_trade_date=trade_date,
        requested_symbols=symbols,
        interval="1m",
        session="ALL",
        adjustment="NONE",
        run_id=run_id,
    )
    manifest.successful_symbols = list(symbols)
    manifest.raw_file = str(raw_path)
    manifest.curated_file = str(curated_path)
    manifest.row_count = len(curated)
    manifest.status = "SUCCESS"
    manifest.finished_at = datetime(2026, 7, 2, tzinfo=timezone.utc)
    catalog = Catalog(cfg)
    catalog.record_run(manifest)
    catalog.record_quality(run_id, [QualityResult("fixture", "PASS")])
    catalog.refresh_market_bars_view()
    cfg.manifest_dir.mkdir(parents=True, exist_ok=True)
    (cfg.manifest_dir / f"{trade_date}_{run_id}.json").write_text(
        json.dumps(manifest.as_dict()), encoding="utf-8"
    )
    cfg.report_dir.mkdir(parents=True, exist_ok=True)
    (cfg.report_dir / f"{trade_date}_{run_id}.json").write_text("[]", encoding="utf-8")
    return raw_path, curated_path


def plan(cfg: Settings, symbols: list[str], *, start=TRADE_DATE, end=TRADE_DATE):
    return purge_plan(
        cfg,
        source="moomoo",
        symbols=symbols,
        start_date=start,
        end_date=end,
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source_schema_version="10.9",
    )


def test_exact_whole_physical_batch_moves_pair_without_rewriting(tmp_path):
    cfg = settings(tmp_path)
    raw, curated = write_batch(cfg, symbols=["US.SPY"])
    original = {"raw": raw.read_bytes(), "curated": curated.read_bytes()}
    sealed = plan(cfg, ["US.SPY"])
    assert sealed.executable
    assert sealed.summary["affected_snapshot_count"] == 1

    result = purge_execute(
        cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}"
    )

    assert result.status == "SUCCESS"
    assert not raw.exists() and not curated.exists()
    quarantine = cfg.data_root / "quarantine" / f"purge_id={sealed.plan_id}"
    assert (quarantine / raw.relative_to(cfg.data_root)).read_bytes() == original["raw"]
    assert (quarantine / curated.relative_to(cfg.data_root)).read_bytes() == original["curated"]
    assert MarketVault(cfg).load_bars(code="US.SPY").empty
    assert list(cfg.manifest_dir.glob("2026-07-01_run-a.json"))
    assert list(cfg.report_dir.glob("2026-07-01_run-a.json"))


def test_partial_symbol_selection_of_multi_symbol_file_is_refused(tmp_path):
    cfg = settings(tmp_path)
    raw, curated = write_batch(cfg, symbols=["US.SPY", "US.QQQ"])
    sealed = plan(cfg, ["US.SPY"])
    assert sealed.status == "REFUSED"
    reason = next(item for item in sealed.refusal_reasons if item["code"] == "COLOCATED_SYMBOLS")
    assert reason["symbols"] == ["US.QQQ"]
    with pytest.raises(PurgeError, match="REFUSED"):
        purge_execute(cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}")
    assert raw.exists() and curated.exists()


def test_complete_multi_symbol_scope_succeeds(tmp_path):
    cfg = settings(tmp_path)
    raw, curated = write_batch(cfg, symbols=["US.SPY", "US.QQQ"])
    sealed = plan(cfg, ["US.QQQ", "US.SPY"])
    assert sealed.executable
    purge_execute(cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}")
    assert not raw.exists() and not curated.exists()


def test_multi_date_range_moves_each_complete_pair(tmp_path):
    cfg = settings(tmp_path)
    first = write_batch(cfg, symbols=["US.SPY"], run_id="run-a")
    second = write_batch(
        cfg,
        symbols=["US.SPY"],
        trade_date=date(2026, 7, 2),
        run_id="run-b",
    )
    sealed = plan(cfg, ["US.SPY"], start=TRADE_DATE, end=date(2026, 7, 2))
    assert sealed.executable
    assert sealed.summary["affected_snapshot_count"] == 2
    purge_execute(cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}")
    assert all(not path.exists() for path in (*first, *second))


def test_no_matching_data_and_pair_mismatch_are_refused(tmp_path):
    cfg = settings(tmp_path)
    empty = plan(cfg, ["US.SPY"])
    assert empty.status == "REFUSED"
    assert any(reason["code"] == "NO_MATCHING_SYMBOL_DATA" for reason in empty.refusal_reasons)

    raw, _ = write_batch(cfg, symbols=["US.SPY"])
    raw.unlink()
    mismatch = plan(cfg, ["US.SPY"])
    assert mismatch.status == "REFUSED"
    assert any(reason["code"] == "UNSAFE_OR_MISSING_TARGET" for reason in mismatch.refusal_reasons)


def test_bad_confirmation_unknown_id_and_plan_tampering_fail_closed(tmp_path):
    cfg = settings(tmp_path)
    write_batch(cfg, symbols=["US.SPY"])
    sealed = plan(cfg, ["US.SPY"])
    with pytest.raises(PurgeError, match="confirmation"):
        purge_execute(cfg, plan_id=sealed.plan_id, confirmation="PURGE wrong")
    with pytest.raises(PurgeError, match="unknown"):
        purge_execute(cfg, plan_id="0" * 32, confirmation=f"PURGE {'0' * 32}")
    path = Path(sealed.plan_file)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["summary"]["affected_row_count"] += 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PurgeError, match="hash mismatch"):
        purge_execute(cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}")


def test_artifact_drift_after_plan_fails_without_moving_pair(tmp_path):
    cfg = settings(tmp_path)
    raw, curated = write_batch(cfg, symbols=["US.SPY"])
    sealed = plan(cfg, ["US.SPY"])
    frame = pd.read_parquet(curated)
    frame.loc[0, "close"] = 999.0
    frame.to_parquet(curated, index=False)
    with pytest.raises(PurgeError, match="identity changed"):
        purge_execute(cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}")
    assert raw.exists() and curated.exists()


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("delete", "disappeared"),
        ("raw_path", "metadata drifted"),
        ("status", "metadata drifted"),
        ("request_metadata", "metadata drifted"),
    ],
)
def test_ingestion_run_binding_drift_fails_before_move(tmp_path, mutation, expected):
    cfg = settings(tmp_path)
    raw, curated = write_batch(cfg, symbols=["US.SPY"])
    sealed = plan(cfg, ["US.SPY"])
    with Catalog(cfg).connect() as con:
        if mutation == "delete":
            con.execute("DELETE FROM ingestion_runs WHERE run_id = 'run-a'")
        elif mutation == "raw_path":
            con.execute(
                "UPDATE ingestion_runs SET raw_file = ? WHERE run_id = 'run-a'",
                [str(cfg.data_root / "raw" / "replacement.parquet")],
            )
        elif mutation == "status":
            con.execute("UPDATE ingestion_runs SET status = 'FAILED' WHERE run_id = 'run-a'")
        else:
            con.execute(
                "UPDATE ingestion_runs SET requested_symbols = ?::JSON WHERE run_id = 'run-a'",
                [json.dumps(["US.QQQ"])],
            )
    with pytest.raises(PurgeError, match=expected):
        purge_execute(cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}")
    assert raw.exists() and curated.exists()


def test_failed_no_file_attempt_is_retained_but_successful_retry_pair_purges(tmp_path):
    cfg = settings(tmp_path)
    failed = RunManifest(
        requested_trade_date=TRADE_DATE,
        requested_symbols=["US.SPY"],
        interval="1m",
        session="ALL",
        adjustment="NONE",
        run_id="run-failed",
    )
    failed.status = "FAILED"
    failed.failed_symbols = {"US.SPY": "provider failure"}
    failed.finished_at = datetime(2026, 7, 2, tzinfo=timezone.utc)
    Catalog(cfg).record_run(failed)
    raw, curated = write_batch(cfg, symbols=["US.SPY"], run_id="run-retry")

    sealed = plan(cfg, ["US.SPY"])
    assert sealed.executable
    assert [target["ingestion_run_id"] for target in sealed.targets] == ["run-retry"]
    purge_execute(cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}")
    assert not raw.exists() and not curated.exists()
    with Catalog(cfg).connect() as con:
        assert con.execute(
            "SELECT status, raw_file, curated_file FROM ingestion_runs WHERE run_id = 'run-failed'"
        ).fetchone() == ("FAILED", None, None)


def test_one_sided_failed_run_remains_a_hard_refusal(tmp_path):
    cfg = settings(tmp_path)
    raw, _ = write_batch(cfg, symbols=["US.SPY"], run_id="run-failed")
    with Catalog(cfg).connect() as con:
        con.execute(
            "UPDATE ingestion_runs SET status = 'FAILED', curated_file = NULL WHERE run_id = 'run-failed'"
        )
    sealed = plan(cfg, ["US.SPY"])
    assert sealed.status == "REFUSED"
    assert any(item["code"] == "RAW_CURATED_MISMATCH" for item in sealed.refusal_reasons)
    assert raw.exists()


def test_lifecycle_lock_conflict_blocks_plan_and_supported_writer(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    write_batch(cfg, symbols=["US.SPY"])
    with MarketBarLifecycleLock(cfg.data_root, "fixture"):
        with pytest.raises(LifecycleLockError, match="already held"):
            plan(cfg, ["US.SPY"])
        from market_vault import service

        monkeypatch.setattr(service, "MoomooHistoryCollector", lambda settings: None)
        with pytest.raises(LifecycleLockError, match="already held"):
            service.collect_history(cfg, TRADE_DATE, ["US.SPY"], "1m", "ALL", "NONE")


def test_backfill_holds_lifecycle_lock_across_all_child_writes(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    raw, curated = write_batch(cfg, symbols=["US.SPY"])
    sealed = plan(cfg, ["US.SPY"])
    from market_vault import backfill as backfill_module

    dates = [TRADE_DATE, date(2026, 7, 2)]
    monkeypatch.setattr(
        backfill_module,
        "plan_history_backfill",
        lambda *args, **kwargs: BackfillPlan(
            symbols=["US.SPY"],
            trading_dates=dates,
            pending_items=[BackfillItem("US.SPY", value) for value in dates],
            skipped_items=[],
            calendar_scope_type="MARKET",
            calendar_scope_value="US",
            start_date_by_symbol={"US.SPY": TRADE_DATE},
        ),
    )
    calls = []

    def fake_child(settings, trade_date, symbols, interval, session, adjustment):
        calls.append(trade_date)
        with pytest.raises(LifecycleLockError, match="already held"):
            purge_execute(
                cfg,
                plan_id=sealed.plan_id,
                confirmation=f"PURGE {sealed.plan_id}",
            )
        child = RunManifest(
            requested_trade_date=trade_date,
            requested_symbols=symbols,
            interval=interval,
            session=session,
            adjustment=adjustment,
        )
        child.successful_symbols = list(symbols)
        child.status = "SUCCESS"
        child.finished_at = datetime.now(timezone.utc)
        return child

    monkeypatch.setattr(backfill_module, "_collect_history_locked", fake_child)
    manifest = collect_history_backfill(
        cfg,
        symbols=["US.SPY"],
        start_date=TRADE_DATE,
        end_date=dates[-1],
        calendar_market="US",
        max_retries=0,
        retry_backoff_seconds=0,
        today=date(2026, 8, 1),
    )
    assert calls == dates
    assert manifest.status == "SUCCESS"
    assert raw.exists() and curated.exists()


def test_partial_move_failure_rolls_back_and_records_failed(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    raw, curated = write_batch(cfg, symbols=["US.SPY"])
    sealed = plan(cfg, ["US.SPY"])
    from market_vault import purge as purge_module

    real_move = purge_module._move_file
    calls = 0

    def fail_second(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated second move failure")
        real_move(source, destination)

    monkeypatch.setattr(purge_module, "_move_file", fail_second)
    with pytest.raises(PurgeError, match="simulated second move failure"):
        purge_execute(cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}")
    assert raw.exists() and curated.exists()
    assert Catalog(cfg).purge_operation(sealed.plan_id)["state"] == "FAILED"


def test_interrupted_link_unlink_move_removes_only_transient_duplicate(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    raw, curated = write_batch(cfg, symbols=["US.SPY"])
    sealed = plan(cfg, ["US.SPY"])
    from market_vault import purge as purge_module

    def duplicate_then_fail(source, destination):
        os.link(source, destination)
        raise OSError("simulated interruption before source unlink")

    monkeypatch.setattr(purge_module, "_move_file", duplicate_then_fail)
    with pytest.raises(PurgeError, match="simulated interruption"):
        purge_execute(cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}")
    assert raw.exists() and curated.exists()
    quarantine = cfg.data_root / "quarantine" / f"purge_id={sealed.plan_id}"
    assert not list(quarantine.rglob("*.parquet"))


def test_catalog_success_failure_rolls_back_and_never_reports_success(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    raw, curated = write_batch(cfg, symbols=["US.SPY"])
    sealed = plan(cfg, ["US.SPY"])
    def fail_commit(self, plan_id, **kwargs):
        raise RuntimeError("simulated catalog transaction failure")

    monkeypatch.setattr(Catalog, "commit_purge_operation", fail_commit)
    with pytest.raises(PurgeError, match="catalog transaction failure"):
        purge_execute(cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}")
    assert raw.exists() and curated.exists()
    assert Catalog(cfg).purge_operation(sealed.plan_id)["state"] == "FAILED"
    result_dir = cfg.manifest_dir / "purge" / "results" / sealed.plan_id
    terminal_payloads = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in result_dir.glob("result-*.json")
    ]
    assert terminal_payloads
    assert all(payload["status"] != "SUCCESS" for payload in terminal_payloads)


def test_committed_result_publication_recovers_idempotently(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    raw, curated = write_batch(cfg, symbols=["US.SPY"])
    sealed = plan(cfg, ["US.SPY"])
    from market_vault import purge as purge_module

    real_write = purge_module._write_immutable
    blocked = True

    def fail_terminal_success(path, payload):
        nonlocal blocked
        if blocked and payload.get("status") == "SUCCESS":
            blocked = False
            raise OSError("simulated terminal publication interruption")
        return real_write(path, payload)

    monkeypatch.setattr(purge_module, "_write_immutable", fail_terminal_success)
    with pytest.raises(PurgeError, match="committed.*idempotent retry"):
        purge_execute(cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}")
    record = Catalog(cfg).purge_operation(sealed.plan_id)
    assert record["state"] == "SUCCESS"
    assert not Path(record["result_file"]).exists()
    assert not raw.exists() and not curated.exists()

    recovered = purge_execute(
        cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}"
    )
    assert recovered.status == "SUCCESS"
    assert Path(recovered.result_file).is_file()
    assert recovered.evidence_hash == record["result_hash"]


def test_successful_plan_retry_is_idempotent(tmp_path):
    cfg = settings(tmp_path)
    write_batch(cfg, symbols=["US.SPY"])
    sealed = plan(cfg, ["US.SPY"])
    first = purge_execute(cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}")
    second = purge_execute(cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}")
    assert second.as_dict() == first.as_dict()


def test_completed_result_tampering_blocks_idempotent_retry(tmp_path):
    cfg = settings(tmp_path)
    write_batch(cfg, symbols=["US.SPY"])
    sealed = plan(cfg, ["US.SPY"])
    result = purge_execute(
        cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}"
    )
    payload = json.loads(Path(result.result_file).read_text(encoding="utf-8"))
    payload["message"] = "tampered unverified message"
    content = {key: value for key, value in payload.items() if key != "evidence_hash"}
    canonical_content = (
        json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")
    import hashlib

    payload["evidence_hash"] = hashlib.sha256(canonical_content).hexdigest()
    Path(result.result_file).write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n",
        encoding="utf-8",
        newline="",
    )
    with pytest.raises(PurgeError, match="hash mismatch"):
        purge_execute(cfg, plan_id=sealed.plan_id, confirmation=f"PURGE {sealed.plan_id}")


def test_repeated_plan_is_deterministic_and_catalog_migration_is_idempotent(tmp_path):
    cfg = settings(tmp_path)
    write_batch(cfg, symbols=["US.SPY"])
    first = plan(cfg, ["US.SPY"])
    second = plan(cfg, ["US.SPY"])
    assert second.plan_id == first.plan_id
    assert second.content_hash == first.content_hash
    assert Path(second.plan_file).read_bytes() == Path(first.plan_file).read_bytes()
    Catalog(cfg).initialize()
    Catalog(cfg).initialize()
    with Catalog(cfg).connect() as con:
        assert con.execute(
            "SELECT COUNT(*) FROM purge_operations WHERE plan_id = ?", [first.plan_id]
        ).fetchone()[0] == 1
    with pytest.raises(RuntimeError, match="commit_purge_operation"):
        Catalog(cfg).update_purge_operation(first.plan_id, state="SUCCESS")


def test_catalog_target_outside_data_root_is_refused_without_touching_file(tmp_path):
    cfg = settings(tmp_path)
    raw, _ = write_batch(cfg, symbols=["US.SPY"])
    outside = tmp_path / "outside.parquet"
    raw.replace(outside)
    with Catalog(cfg).connect() as con:
        con.execute(
            "UPDATE ingestion_runs SET raw_file = ? WHERE run_id = 'run-a'",
            [str(outside)],
        )
    sealed = plan(cfg, ["US.SPY"])
    assert sealed.status == "REFUSED"
    assert any(reason["code"] == "UNSAFE_OR_MISSING_TARGET" for reason in sealed.refusal_reasons)
    assert outside.exists()


def test_symlink_snapshot_escape_is_refused(tmp_path):
    cfg = settings(tmp_path)
    raw, _ = write_batch(cfg, symbols=["US.SPY"])
    outside = tmp_path / "outside.parquet"
    outside.write_bytes(raw.read_bytes())
    raw.unlink()
    try:
        os.symlink(outside, raw)
    except OSError:
        pytest.skip("symlink creation is unavailable in this environment")
    sealed = plan(cfg, ["US.SPY"])
    assert sealed.status == "REFUSED"
    assert any(reason["code"] == "UNSAFE_OR_MISSING_TARGET" for reason in sealed.refusal_reasons)
    assert outside.exists()


def test_reparse_point_detection_refuses_snapshot(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    raw, _ = write_batch(cfg, symbols=["US.SPY"])
    from market_vault import lifecycle

    real_check = lifecycle.is_junction_or_reparse
    monkeypatch.setattr(
        lifecycle,
        "is_junction_or_reparse",
        lambda path: Path(path) == raw or real_check(Path(path)),
    )
    sealed = plan(cfg, ["US.SPY"])
    assert sealed.status == "REFUSED"
    assert any(reason["code"] == "UNSAFE_OR_MISSING_TARGET" for reason in sealed.refusal_reasons)


def test_windows_reparse_attribute_wins_when_is_junction_is_false(monkeypatch):
    from market_vault import lifecycle

    class FalseJunctionPath:
        def is_junction(self):
            return False

        def __str__(self):
            return r"C:\data\snapshot.parquet"

    attribute_reads = []
    monkeypatch.setattr(lifecycle, "_running_on_windows", lambda: True)
    monkeypatch.setattr(
        lifecycle,
        "_windows_file_attributes",
        lambda path: attribute_reads.append(str(path))
        or lifecycle.FILE_ATTRIBUTE_REPARSE_POINT,
    )
    assert lifecycle.is_junction_or_reparse(FalseJunctionPath())
    assert attribute_reads == [r"C:\data\snapshot.parquet"]


def test_windows_invalid_file_attributes_preserves_native_error(monkeypatch):
    from market_vault import lifecycle

    monkeypatch.setattr(lifecycle, "_running_on_windows", lambda: True)

    def invalid_attributes(path):
        raise LifecycleLockError(
            f"cannot verify Windows file attributes for {path}: "
            "INVALID_FILE_ATTRIBUTES (Windows error 5)"
        )

    monkeypatch.setattr(lifecycle, "_windows_file_attributes", invalid_attributes)
    with pytest.raises(
        LifecycleLockError, match=r"INVALID_FILE_ATTRIBUTES \(Windows error 5\)"
    ):
        lifecycle.is_junction_or_reparse(Path(r"C:\data\snapshot.parquet"))


def test_catalog_running_state_is_an_explicit_refusal(tmp_path):
    cfg = settings(tmp_path)
    write_batch(cfg, symbols=["US.SPY"])
    with Catalog(cfg).connect() as con:
        con.execute("UPDATE ingestion_runs SET status = 'RUNNING' WHERE run_id = 'run-a'")
    sealed = plan(cfg, ["US.SPY"])
    assert sealed.status == "REFUSED"
    assert any(reason["code"] == "ACTIVE_RUN" for reason in sealed.refusal_reasons)


def test_purge_cli_requires_explicit_scope_and_confirmation():
    parser = build_parser()
    args = parser.parse_args(
        [
            "purge-plan",
            "--source",
            "moomoo",
            "--symbols",
            "US.SPY",
            "US.QQQ",
            "--start-date",
            "2026-07-01",
            "--end-date",
            "2026-07-02",
            "--interval",
            "1m",
            "--session",
            "ALL",
            "--adjustment",
            "NONE",
            "--source-schema-version",
            "10.9",
        ]
    )
    assert args.symbols == ["US.SPY", "US.QQQ"]
    execute = parser.parse_args(
        [
            "purge-execute",
            "--plan-id",
            "a" * 32,
            "--confirmation",
            f"PURGE {'a' * 32}",
        ]
    )
    assert execute.confirmation == f"PURGE {'a' * 32}"


class FakePurgeVault:
    def __init__(self, purge_plan_value):
        self.settings = SimpleNamespace(source="moomoo", source_schema_version="10.9")
        self.plan = purge_plan_value
        self.execute_calls = []

    def purge_plan(self, **kwargs):
        return self.plan

    def purge_execute(self, **kwargs):
        self.execute_calls.append(kwargs)
        return SimpleNamespace(as_dict=lambda: {"status": "SUCCESS", **kwargs})


def test_console_requires_preview_and_does_not_expose_permanent_delete():
    fake_plan = SimpleNamespace(
        plan_id="a" * 32,
        status="PLANNED",
        executable=True,
        summary={"affected_snapshot_count": 1},
        refusal_reasons=(),
        targets=(),
    )
    backend = ConsoleBackend(FakePurgeVault(fake_plan))
    with pytest.raises(ValueError, match="Preview"):
        backend.execute_purge(plan_id="a" * 32, confirmation=f"PURGE {'a' * 32}")
    view = backend.preview_purge(
        source="moomoo",
        symbols="US.SPY",
        start_date="2026-07-01",
        end_date="2026-07-01",
        interval="1m",
        session="ALL",
        adjustment="NONE",
        source_schema_version="10.9",
    )
    assert view.executable
    result = backend.execute_purge(
        plan_id=view.plan_id, confirmation=f"PURGE {view.plan_id}"
    )
    assert result["status"] == "SUCCESS"
    assert not hasattr(backend, "delete_quarantine")
    assert not hasattr(backend, "permanent_delete")


def test_console_refused_colocated_plan_never_enables_execution():
    refused = SimpleNamespace(
        plan_id="b" * 32,
        status="REFUSED",
        executable=False,
        summary={"affected_snapshot_count": 1},
        refusal_reasons=(
            {"code": "COLOCATED_SYMBOLS", "message": "co-located", "symbols": ["US.QQQ"]},
        ),
        targets=(),
    )
    backend = ConsoleBackend(FakePurgeVault(refused))
    view = backend.preview_purge(
        source="moomoo",
        symbols="US.SPY",
        start_date="2026-07-01",
        end_date="2026-07-01",
        interval="1m",
        session="ALL",
        adjustment="NONE",
        source_schema_version="10.9",
    )
    assert view.status == "REFUSED"
    assert view.refusal_reasons[0]["symbols"] == ["US.QQQ"]
    with pytest.raises(ValueError, match="Preview"):
        backend.execute_purge(plan_id=view.plan_id, confirmation=f"PURGE {view.plan_id}")


def test_console_scope_edit_invalidates_preview_confirmation_and_execute():
    fake_plan = SimpleNamespace(
        plan_id="c" * 32,
        status="PLANNED",
        executable=True,
        summary={"affected_snapshot_count": 1},
        refusal_reasons=(),
        targets=(),
    )
    backend = ConsoleBackend(FakePurgeVault(fake_plan))
    view = backend.preview_purge(
        source="moomoo",
        symbols="US.SPY",
        start_date="2026-07-01",
        end_date="2026-07-01",
        interval="1m",
        session="ALL",
        adjustment="NONE",
        source_schema_version="10.9",
    )

    class FakeVar:
        def __init__(self, value=""):
            self.value = value
            self.callbacks = []

        def trace_add(self, mode, callback):
            assert mode == "write"
            self.callbacks.append(callback)

        def set(self, value):
            self.value = value

    class FakeButton:
        def __init__(self):
            self.state = "normal"

        def configure(self, *, state):
            self.state = state

    app = ConsoleApp.__new__(ConsoleApp)
    app.backend = backend
    app.purge_vars = {name: FakeVar() for name in (
        "source",
        "symbols",
        "start_date",
        "end_date",
        "interval",
        "session",
        "adjustment",
        "source_schema_version",
    )}
    app.purge_confirmation = FakeVar(f"PURGE {view.plan_id}")
    app.purge_summary = FakeVar("PLANNED")
    app.purge_refusals = FakeVar("old")
    app.purge_execute_button = FakeButton()
    app._purge_plan_id = view.plan_id
    app._bind_purge_scope_invalidation()
    assert all(len(variable.callbacks) == 1 for variable in app.purge_vars.values())

    app.purge_vars["symbols"].callbacks[0]()
    assert app._purge_plan_id is None
    assert app.purge_confirmation.value == ""
    assert app.purge_execute_button.state == "disabled"
    assert app.purge_summary.value == "Scope changed; run Preview again"
    with pytest.raises(ValueError, match="Preview"):
        backend.execute_purge(plan_id=view.plan_id, confirmation=f"PURGE {view.plan_id}")
