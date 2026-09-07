from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from market_vault import purge as purge_module
from market_vault import service as service_module
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars
from market_vault.purge import (
    EXACT_SCOPE,
    PURGE_PLAN_VERSION_V4,
    SUPERSEDED_ONLY,
    PurgeError,
    purge_execute,
    purge_plan,
)
from market_vault.storage import Catalog, ParquetStore


TRADE_DATE = date(2026, 8, 3)


def settings(
    tmp_path: Path, *, schema: str = "10.9", source: str = "moomoo"
) -> Settings:
    return Settings(
        project_root=tmp_path,
        opend_host="127.0.0.1",
        opend_port=11111,
        data_root=tmp_path / "data",
        catalog_path=tmp_path / "catalog" / "market_vault.duckdb",
        manifest_dir=tmp_path / "manifests",
        report_dir=tmp_path / "reports",
        source=source,
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
    close: float,
    symbol: str = "US.SPY",
    session: str = "ALL",
    interval: str = "1m",
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


def collect_multi(
    monkeypatch: pytest.MonkeyPatch,
    cfg: Settings,
    responses: dict[str, pd.DataFrame],
):
    class Collector:
        def __init__(self, _settings):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def fetch_history(self, code, **_kwargs):
            return responses[code].copy()

    monkeypatch.setattr(service_module, "MoomooHistoryCollector", Collector)
    return service_module.collect_history(
        cfg, TRADE_DATE, list(responses), "1m", "ALL", "NONE"
    )


def legacy_pair(
    cfg: Settings, symbols: list[str], *, run_id: str = "legacy-old"
) -> tuple[Path, Path]:
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
    raw_path = store.write_raw(
        raw, TRADE_DATE, "1m", symbols, "ALL", "NONE", run_id
    )
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
    return raw_path, curated_path


def plan(
    cfg: Settings,
    policy: str,
    *,
    symbols: list[str] | None = None,
    session: str = "ALL",
    interval: str = "1m",
    adjustment: str = "NONE",
):
    return purge_plan(
        cfg,
        source=cfg.source,
        symbols=symbols or ["US.SPY"],
        start_date=TRADE_DATE,
        end_date=TRADE_DATE,
        interval=interval,
        requested_session=session,
        adjustment=adjustment,
        source_schema_version=cfg.source_schema_version,
        cleanup_policy=policy,
    )


def execute(cfg: Settings, sealed):
    return purge_execute(
        cfg,
        plan_id=sealed.plan_id,
        confirmation=f"PURGE {sealed.plan_id}",
    )


def canonical_bytes(payload: dict) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def clone_success_authority(
    cfg: Settings,
    source_plan_id: str,
    *,
    variant: str,
    alter_raw: bool = False,
    alter_curated: bool = False,
) -> str:
    catalog = Catalog(cfg)
    source_record = catalog.purge_operation(source_plan_id)
    assert source_record is not None
    plan_payload = json.loads(Path(source_record["plan_file"]).read_bytes())
    target = plan_payload["targets"][0]
    for layer, altered in (("raw", alter_raw), ("curated", alter_curated)):
        if altered:
            path = Path(target[layer]["relative_path"])
            target[layer]["relative_path"] = (
                path.parent / f"split-{variant}-{path.name}"
            ).as_posix()
    plan_payload["summary"]["test_authority_variant"] = variant
    plan_content = {
        key: value
        for key, value in plan_payload.items()
        if key not in {"plan_id", "content_hash"}
    }
    plan_hash = hashlib.sha256(canonical_bytes(plan_content)).hexdigest()
    plan_id = plan_hash[:32]
    plan_payload["plan_id"] = plan_id
    plan_payload["content_hash"] = plan_hash
    plan_path = cfg.manifest_dir / "purge" / "plans" / f"{plan_id}.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_bytes(canonical_bytes(plan_payload))

    result_payload = json.loads(Path(source_record["result_file"]).read_bytes())
    result_root = cfg.manifest_dir / "purge" / "results" / plan_id
    result_root.mkdir(parents=True, exist_ok=True)
    result_path = result_root / Path(source_record["result_file"]).name
    result_payload["plan_id"] = plan_id
    result_payload["content_hash"] = plan_hash
    result_payload["result_file"] = str(result_path)
    result_payload["moved_files"] = [
        {
            **target[layer],
            "quarantine_relative_path": (
                Path("quarantine")
                / f"purge_id={plan_id}"
                / target[layer]["relative_path"]
            ).as_posix(),
        }
        for target in plan_payload["targets"]
        for layer in ("raw", "curated")
    ]
    result_content = {
        key: value for key, value in result_payload.items() if key != "evidence_hash"
    }
    result_hash = hashlib.sha256(canonical_bytes(result_content)).hexdigest()
    result_payload["evidence_hash"] = result_hash
    result_path.write_bytes(canonical_bytes(result_payload))

    precommit_payload = json.loads(Path(source_record["precommit_file"]).read_bytes())
    precommit_path = result_root / Path(source_record["precommit_file"]).name
    precommit_payload["plan_id"] = plan_id
    precommit_payload["plan_hash"] = plan_hash
    precommit_payload["terminal_result"] = result_payload
    precommit_payload["terminal_result_hash"] = result_hash
    precommit_content = {
        key: value
        for key, value in precommit_payload.items()
        if key != "precommit_hash"
    }
    precommit_payload["precommit_hash"] = hashlib.sha256(
        canonical_bytes(precommit_content)
    ).hexdigest()
    precommit_path.write_bytes(canonical_bytes(precommit_payload))

    source_plan = json.loads(Path(source_record["plan_file"]).read_bytes())
    source_targets = source_plan["targets"]
    for index, cloned_target in enumerate(plan_payload["targets"]):
        for layer in ("raw", "curated"):
            source = (
                cfg.data_root
                / "quarantine"
                / f"purge_id={source_plan_id}"
                / source_targets[index][layer]["relative_path"]
            )
            destination = (
                cfg.data_root
                / "quarantine"
                / f"purge_id={plan_id}"
                / cloned_target[layer]["relative_path"]
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    with catalog.connect() as con:
        con.execute(
            """
            INSERT INTO purge_operations (
                plan_id, plan_hash, state, scope_json, plan_file,
                precommit_file, result_file, result_hash, planned_at,
                started_at, finished_at, error
            ) VALUES (?, ?, 'SUCCESS', ?::JSON, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            [
                plan_id,
                plan_hash,
                source_record["scope_json"],
                str(plan_path),
                str(precommit_path),
                str(result_path),
                result_hash,
                datetime.now(timezone.utc),
                datetime.now(timezone.utc),
                datetime.now(timezone.utc),
            ],
        )
    return plan_id


def three_versions(monkeypatch: pytest.MonkeyPatch, cfg: Settings):
    old_a = collect(monkeypatch, cfg, close=100)
    old_b = collect(monkeypatch, cfg, close=200)
    current = collect(monkeypatch, cfg, close=300)
    superseded = plan(cfg, SUPERSEDED_ONLY)
    execute(cfg, superseded)
    return old_a, old_b, current, superseded


def fail_v4_after_movement_with_incomplete_rollback(
    monkeypatch: pytest.MonkeyPatch,
    cfg: Settings,
    sealed,
    *,
    rollback_failure_layers: tuple[str, ...],
) -> dict[str, Path]:
    real_prepare = purge_module._prepare_success_result
    real_move = purge_module._move_file
    quarantine_paths = {
        layer: (
            cfg.data_root
            / "quarantine"
            / f"purge_id={sealed.plan_id}"
            / sealed.targets[0][layer]["relative_path"]
        )
        for layer in ("raw", "curated")
    }
    rollback_failures = {
        quarantine_paths[layer] for layer in rollback_failure_layers
    }

    def fail_before_catalog_success(*_args, **_kwargs):
        raise RuntimeError("injected failure before Catalog SUCCESS")

    def move_with_incomplete_rollback(source: Path, destination: Path) -> None:
        if Path(source) in rollback_failures:
            raise OSError(f"injected rollback failure: {Path(source).name}")
        real_move(source, destination)

    monkeypatch.setattr(
        purge_module, "_prepare_success_result", fail_before_catalog_success
    )
    monkeypatch.setattr(purge_module, "_move_file", move_with_incomplete_rollback)
    with pytest.raises(PurgeError, match="injected failure before Catalog SUCCESS"):
        execute(cfg, sealed)
    monkeypatch.setattr(purge_module, "_prepare_success_result", real_prepare)
    monkeypatch.setattr(purge_module, "_move_file", real_move)

    record = Catalog(cfg).purge_operation(sealed.plan_id)
    assert record is not None
    assert record["state"] == "FAILED"
    return quarantine_paths


@pytest.mark.parametrize(
    "rollback_failure_layers",
    [("raw", "curated"), ("curated",)],
    ids=["both-sides-own-quarantine", "raw-active-curated-own-quarantine"],
)
def test_v4_failed_retry_recovers_exact_current_target_in_transit(
    monkeypatch, tmp_path, rollback_failure_layers
):
    cfg = settings(tmp_path)
    old_a, old_b, current, _ = three_versions(monkeypatch, cfg)
    sealed = plan(cfg, EXACT_SCOPE)
    assert sealed.plan_version == PURGE_PLAN_VERSION_V4
    assert [item["ingestion_run_id"] for item in sealed.targets] == [current.run_id]
    prior_run_ids = {
        item["ingestion_run_id"] for item in sealed.reconciled_quarantined_units
    }
    assert prior_run_ids == {old_a.run_id, old_b.run_id}
    prior_quarantine = {
        cfg.data_root / item[layer]["quarantine_relative_path"]
        for item in sealed.reconciled_quarantined_units
        for layer in ("raw", "curated")
    }
    prior_hashes = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in prior_quarantine
    }

    quarantine_paths = fail_v4_after_movement_with_incomplete_rollback(
        monkeypatch,
        cfg,
        sealed,
        rollback_failure_layers=rollback_failure_layers,
    )

    for layer in rollback_failure_layers:
        assert quarantine_paths[layer].is_file()
    for layer in ({"raw", "curated"} - set(rollback_failure_layers)):
        assert (cfg.data_root / sealed.targets[0][layer]["relative_path"]).is_file()

    result = execute(cfg, sealed)

    assert result.status == "SUCCESS"
    assert result.plan_id == sealed.plan_id
    assert Catalog(cfg).purge_operation(sealed.plan_id)["state"] == "SUCCESS"
    assert all(path.is_file() for path in quarantine_paths.values())
    assert all(
        hashlib.sha256(path.read_bytes()).hexdigest() == digest
        for path, digest in prior_hashes.items()
    )
    assert prior_run_ids == {
        item["ingestion_run_id"] for item in sealed.reconciled_quarantined_units
    }


def test_v4_failed_retry_rejects_tampered_own_quarantine_before_movement(
    monkeypatch, tmp_path
):
    cfg = settings(tmp_path)
    _, _, current, _ = three_versions(monkeypatch, cfg)
    sealed = plan(cfg, EXACT_SCOPE)
    quarantine_paths = fail_v4_after_movement_with_incomplete_rollback(
        monkeypatch,
        cfg,
        sealed,
        rollback_failure_layers=("raw", "curated"),
    )
    quarantine_paths["raw"].write_bytes(
        quarantine_paths["raw"].read_bytes() + b"tamper"
    )
    curated_before = hashlib.sha256(
        quarantine_paths["curated"].read_bytes()
    ).hexdigest()

    with pytest.raises(PurgeError, match="sealed target identity changed"):
        execute(cfg, sealed)

    record = Catalog(cfg).purge_operation(sealed.plan_id)
    assert record is not None
    assert record["state"] == "FAILED"
    assert not Path(current.raw_file).exists()
    assert not Path(current.curated_file).exists()
    assert (
        hashlib.sha256(quarantine_paths["curated"].read_bytes()).hexdigest()
        == curated_before
    )


def test_three_version_review_execution_and_fully_quarantined_review(
    monkeypatch, tmp_path
):
    cfg = settings(tmp_path)
    old_a, old_b, current, _ = three_versions(monkeypatch, cfg)

    sealed = plan(cfg, EXACT_SCOPE)

    assert sealed.plan_version == PURGE_PLAN_VERSION_V4
    assert sealed.status == "PLANNED", sealed.refusal_reasons
    assert [item["ingestion_run_id"] for item in sealed.targets] == [current.run_id]
    assert {
        item["ingestion_run_id"] for item in sealed.reconciled_quarantined_units
    } == {old_a.run_id, old_b.run_id}
    assert sealed.summary["reconciled_quarantined_count"] == 2

    result = execute(cfg, sealed)

    assert result.status == "SUCCESS"
    assert not Path(current.raw_file).exists()
    assert not Path(current.curated_file).exists()
    for historical in (old_a, old_b):
        assert not Path(historical.raw_file).exists()
        assert not Path(historical.curated_file).exists()

    repeated = plan(cfg, EXACT_SCOPE)
    assert repeated.status == "REFUSED"
    assert repeated.targets == ()
    assert {item["code"] for item in repeated.refusal_reasons} == {
        "NO_MATCHING_DATA"
    }


def test_absent_final_result_is_read_only_authority(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    collect(monkeypatch, cfg, close=100)
    collect(monkeypatch, cfg, close=200)
    collect(monkeypatch, cfg, close=300)
    superseded = plan(cfg, SUPERSEDED_ONLY)
    real_publish = purge_module._publish_terminal_result

    def fail_publication(*_args, **_kwargs):
        raise RuntimeError("injected publication interruption")

    monkeypatch.setattr(purge_module, "_publish_terminal_result", fail_publication)
    with pytest.raises(PurgeError, match="committed.*idempotent retry"):
        execute(cfg, superseded)
    record = purge_module.Catalog(cfg).purge_operation(superseded.plan_id)
    result_path = Path(record["result_file"])
    assert record["state"] == "SUCCESS"
    assert not result_path.exists()

    sealed = plan(cfg, EXACT_SCOPE)

    assert sealed.plan_version == PURGE_PLAN_VERSION_V4
    assert len(sealed.reconciled_quarantined_units) == 2
    assert not result_path.exists()

    monkeypatch.setattr(purge_module, "_publish_terminal_result", real_publish)
    execute(cfg, superseded)
    assert result_path.is_file()
    repeated = plan(cfg, EXACT_SCOPE)
    assert repeated.reconciled_quarantined_units == sealed.reconciled_quarantined_units


def test_quarantine_drift_after_review_refuses_before_new_movement(
    monkeypatch, tmp_path
):
    cfg = settings(tmp_path)
    _, _, current, superseded = three_versions(monkeypatch, cfg)
    sealed = plan(cfg, EXACT_SCOPE)
    prior = sealed.reconciled_quarantined_units[0]
    prior_raw = cfg.data_root / prior["raw"]["quarantine_relative_path"]
    prior_raw.write_bytes(prior_raw.read_bytes() + b"drift")

    with pytest.raises(PurgeError, match="reconciliation authority changed"):
        execute(cfg, sealed)

    assert Path(current.raw_file).is_file()
    assert Path(current.curated_file).is_file()
    assert superseded.status == "PLANNED"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("missing_raw", "QUARANTINE_PAIR_INCOMPLETE"),
        ("missing_curated", "QUARANTINE_PAIR_INCOMPLETE"),
        ("raw_hash", "QUARANTINE_EVIDENCE_HASH_MISMATCH"),
        ("curated_hash", "QUARANTINE_EVIDENCE_HASH_MISMATCH"),
        ("plan_tamper", "QUARANTINE_EVIDENCE_HASH_MISMATCH"),
        ("precommit_tamper", "QUARANTINE_EVIDENCE_HASH_MISMATCH"),
        ("catalog_plan_hash", "QUARANTINE_EVIDENCE_HASH_MISMATCH"),
        ("catalog_result_hash", "QUARANTINE_EVIDENCE_HASH_MISMATCH"),
        ("final_result_tamper", "QUARANTINE_EVIDENCE_HASH_MISMATCH"),
        ("unsafe_precommit_path", "PURGE_RESULT_AUTHORITY_MISMATCH"),
    ],
)
def test_prior_success_evidence_tamper_matrix(
    monkeypatch, tmp_path, mutation, expected_code
):
    cfg = settings(tmp_path)
    _, _, current, superseded = three_versions(monkeypatch, cfg)
    record = Catalog(cfg).purge_operation(superseded.plan_id)
    assert record is not None
    prior_payload = json.loads(Path(record["plan_file"]).read_text(encoding="utf-8"))
    target = prior_payload["targets"][0]
    raw_quarantine = (
        cfg.data_root
        / "quarantine"
        / f"purge_id={superseded.plan_id}"
        / target["raw"]["relative_path"]
    )
    curated_quarantine = (
        cfg.data_root
        / "quarantine"
        / f"purge_id={superseded.plan_id}"
        / target["curated"]["relative_path"]
    )
    if mutation == "missing_raw":
        raw_quarantine.unlink()
    elif mutation == "missing_curated":
        curated_quarantine.unlink()
    elif mutation == "raw_hash":
        raw_quarantine.write_bytes(raw_quarantine.read_bytes() + b"drift")
    elif mutation == "curated_hash":
        curated_quarantine.write_bytes(curated_quarantine.read_bytes() + b"drift")
    elif mutation == "plan_tamper":
        Path(record["plan_file"]).write_bytes(
            Path(record["plan_file"]).read_bytes() + b" "
        )
    elif mutation == "precommit_tamper":
        Path(record["precommit_file"]).write_bytes(
            Path(record["precommit_file"]).read_bytes() + b" "
        )
    elif mutation == "final_result_tamper":
        Path(record["result_file"]).write_bytes(
            Path(record["result_file"]).read_bytes() + b" "
        )
    else:
        with Catalog(cfg).connect() as con:
            if mutation == "catalog_plan_hash":
                con.execute(
                    "UPDATE purge_operations SET plan_hash = ? WHERE plan_id = ?",
                    ["0" * 64, superseded.plan_id],
                )
            elif mutation == "catalog_result_hash":
                con.execute(
                    "UPDATE purge_operations SET result_hash = ? WHERE plan_id = ?",
                    ["0" * 64, superseded.plan_id],
                )
            else:
                con.execute(
                    "UPDATE purge_operations SET precommit_file = ? WHERE plan_id = ?",
                    [str(cfg.manifest_dir / "outside.json"), superseded.plan_id],
                )

    refused = plan(cfg, EXACT_SCOPE)

    assert refused.status == "REFUSED"
    assert expected_code in {item["code"] for item in refused.refusal_reasons}
    assert Path(current.raw_file).exists()
    assert Path(current.curated_file).exists()


@pytest.mark.parametrize("state", ["PLANNED", "REFUSED", "EXECUTING", "FAILED"])
def test_non_success_catalog_state_never_establishes_quarantine_authority(
    monkeypatch, tmp_path, state
):
    cfg = settings(tmp_path)
    _, _, current, superseded = three_versions(monkeypatch, cfg)
    with Catalog(cfg).connect() as con:
        con.execute(
            "UPDATE purge_operations SET state = ? WHERE plan_id = ?",
            [state, superseded.plan_id],
        )

    refused = plan(cfg, EXACT_SCOPE)

    assert refused.status == "REFUSED"
    assert "QUARANTINE_EVIDENCE_MISSING" in {
        item["code"] for item in refused.refusal_reasons
    }
    assert Path(current.raw_file).exists()
    assert Path(current.curated_file).exists()


def test_active_and_committed_quarantine_claim_is_ambiguous(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    old_a, _, current, superseded = three_versions(monkeypatch, cfg)
    record = Catalog(cfg).purge_operation(superseded.plan_id)
    assert record is not None
    payload = json.loads(Path(record["plan_file"]).read_text(encoding="utf-8"))
    target = next(
        item for item in payload["targets"] if item["ingestion_run_id"] == old_a.run_id
    )
    for layer in ("raw", "curated"):
        active = cfg.data_root / target[layer]["relative_path"]
        quarantine = (
            cfg.data_root
            / "quarantine"
            / f"purge_id={superseded.plan_id}"
            / target[layer]["relative_path"]
        )
        active.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(quarantine, active)

    refused = plan(cfg, EXACT_SCOPE)

    assert refused.status == "REFUSED"
    assert "CONFLICTING_PURGE_AUTHORITY" in {
        item["code"] for item in refused.refusal_reasons
    }
    assert Path(current.raw_file).exists()
    assert Path(current.curated_file).exists()


def test_multiple_committed_success_claims_are_ambiguous(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    _, _, current, superseded = three_versions(monkeypatch, cfg)
    clone_success_authority(cfg, superseded.plan_id, variant="duplicate")

    refused = plan(cfg, EXACT_SCOPE)

    assert refused.status == "REFUSED"
    assert "CONFLICTING_PURGE_AUTHORITY" in {
        item["code"] for item in refused.refusal_reasons
    }
    assert Path(current.raw_file).exists()
    assert Path(current.curated_file).exists()


def test_raw_and_curated_split_across_success_operations_are_ambiguous(
    monkeypatch, tmp_path
):
    cfg = settings(tmp_path)
    _, _, current, superseded = three_versions(monkeypatch, cfg)
    clone_success_authority(
        cfg, superseded.plan_id, variant="raw-claim", alter_curated=True
    )
    clone_success_authority(
        cfg, superseded.plan_id, variant="curated-claim", alter_raw=True
    )
    with Catalog(cfg).connect() as con:
        con.execute(
            "UPDATE purge_operations SET state = 'FAILED' WHERE plan_id = ?",
            [superseded.plan_id],
        )

    refused = plan(cfg, EXACT_SCOPE)

    assert refused.status == "REFUSED"
    assert "CONFLICTING_PURGE_AUTHORITY" in {
        item["code"] for item in refused.refusal_reasons
    }
    assert Path(current.raw_file).exists()
    assert Path(current.curated_file).exists()


def test_successful_v4_can_be_future_prior_authority(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    _, _, previous_current, _ = three_versions(monkeypatch, cfg)
    first_v4 = plan(cfg, EXACT_SCOPE)
    execute(cfg, first_v4)
    next_current = collect(monkeypatch, cfg, close=400)

    later = plan(cfg, EXACT_SCOPE)

    assert later.plan_version == PURGE_PLAN_VERSION_V4
    assert later.status == "PLANNED"
    assert [item["ingestion_run_id"] for item in later.targets] == [
        next_current.run_id
    ]
    prior = next(
        item
        for item in later.reconciled_quarantined_units
        if item["ingestion_run_id"] == previous_current.run_id
    )
    assert prior["prior_purge_authority"]["plan_version"] == PURGE_PLAN_VERSION_V4
    assert prior["prior_purge_authority"]["plan_id"] == first_v4.plan_id


def test_v4_execution_does_not_rewrite_historical_catalog_paths(
    monkeypatch, tmp_path
):
    cfg = settings(tmp_path)
    three_versions(monkeypatch, cfg)
    catalog = Catalog(cfg)
    with catalog.connect() as con:
        before_runs = con.execute(
            "SELECT run_id, raw_file, curated_file FROM ingestion_runs ORDER BY run_id"
        ).fetchall()
        before_pairs = con.execute(
            """
            SELECT run_id, symbol, raw_file, curated_file
            FROM market_bar_snapshot_pairs ORDER BY run_id, symbol
            """
        ).fetchall()

    execute(cfg, plan(cfg, EXACT_SCOPE))

    with catalog.connect() as con:
        after_runs = con.execute(
            "SELECT run_id, raw_file, curated_file FROM ingestion_runs ORDER BY run_id"
        ).fetchall()
        after_pairs = con.execute(
            """
            SELECT run_id, symbol, raw_file, curated_file
            FROM market_bar_snapshot_pairs ORDER BY run_id, symbol
            """
        ).fetchall()
    assert after_runs == before_runs
    assert after_pairs == before_pairs


def test_registered_sibling_symbols_reconcile_independently(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    old = collect_multi(
        monkeypatch,
        cfg,
        {
            "US.SPY": raw_frame("US.SPY", 100),
            "US.QQQ": raw_frame("US.QQQ", 110),
        },
    )
    current_spy = collect(monkeypatch, cfg, close=200, symbol="US.SPY")
    superseded_spy = plan(cfg, SUPERSEDED_ONLY, symbols=["US.SPY"])
    execute(cfg, superseded_spy)

    spy = plan(cfg, EXACT_SCOPE, symbols=["US.SPY"])
    qqq = plan(cfg, EXACT_SCOPE, symbols=["US.QQQ"])

    assert spy.plan_version == PURGE_PLAN_VERSION_V4
    assert [item["ingestion_run_id"] for item in spy.targets] == [current_spy.run_id]
    assert len(spy.reconciled_quarantined_units) == 1
    assert spy.reconciled_quarantined_units[0]["symbols"] == ["US.SPY"]
    assert qqq.status == "PLANNED"
    assert qqq.plan_version != PURGE_PLAN_VERSION_V4
    assert [item["ingestion_run_id"] for item in qqq.targets] == [old.run_id]


def test_legacy_multisymbol_pair_reconciles_as_one_unit(monkeypatch, tmp_path):
    cfg = settings(tmp_path)
    legacy_raw, legacy_curated = legacy_pair(cfg, ["US.SPY", "US.QQQ"])
    current = collect_multi(
        monkeypatch,
        cfg,
        {
            "US.SPY": raw_frame("US.SPY", 200),
            "US.QQQ": raw_frame("US.QQQ", 210),
        },
    )
    superseded = plan(cfg, SUPERSEDED_ONLY, symbols=["US.SPY", "US.QQQ"])
    execute(cfg, superseded)

    sealed = plan(cfg, EXACT_SCOPE, symbols=["US.SPY", "US.QQQ"])

    assert not legacy_raw.exists() and not legacy_curated.exists()
    assert sealed.plan_version == PURGE_PLAN_VERSION_V4
    assert len(sealed.reconciled_quarantined_units) == 1
    unit = sealed.reconciled_quarantined_units[0]
    assert unit["binding_mode"] == "LEGACY_INGESTION_RUN"
    assert unit["snapshot_pair_binding"] is None
    assert unit["symbols"] == ["US.QQQ", "US.SPY"]
    assert len(unit["logical_keys"]) == 2
    assert {item["ingestion_run_id"] for item in sealed.targets} == {current.run_id}


def test_source_schema_isolation_prevents_cross_reconciliation(monkeypatch, tmp_path):
    old_cfg = settings(tmp_path, schema="10.9")
    collect(monkeypatch, old_cfg, close=100)
    collect(monkeypatch, old_cfg, close=200)
    old_superseded = plan(old_cfg, SUPERSEDED_ONLY)
    execute(old_cfg, old_superseded)

    new_cfg = settings(tmp_path, schema="10.9-mv-ts2")
    sealed = plan(new_cfg, EXACT_SCOPE)

    assert sealed.status == "REFUSED"
    assert sealed.plan_version != PURGE_PLAN_VERSION_V4
    assert {item["code"] for item in sealed.refusal_reasons} == {
        "NO_MATCHING_SYMBOL_DATA"
    }
    assert sealed.reconciled_quarantined_units == ()


def test_source_isolation_prevents_cross_reconciliation(monkeypatch, tmp_path):
    original = settings(tmp_path, source="moomoo")
    collect(monkeypatch, original, close=100)
    collect(monkeypatch, original, close=200)
    execute(original, plan(original, SUPERSEDED_ONLY))

    other = settings(tmp_path, source="other-source")
    sealed = plan(other, EXACT_SCOPE)

    assert sealed.status == "REFUSED"
    assert sealed.plan_version != PURGE_PLAN_VERSION_V4
    assert {item["code"] for item in sealed.refusal_reasons} == {
        "NO_MATCHING_SYMBOL_DATA"
    }


@pytest.mark.parametrize(
    ("dimension", "value"),
    [
        ("session", "RTH"),
        ("interval", "5m"),
        ("adjustment", "QFQ"),
    ],
)
def test_request_dimensions_do_not_cross_reconcile(
    monkeypatch, tmp_path, dimension, value
):
    cfg = settings(tmp_path)
    collect(monkeypatch, cfg, close=100)
    collect(monkeypatch, cfg, close=200)
    prior = plan(cfg, SUPERSEDED_ONLY)
    execute(cfg, prior)
    arguments = {"session": "ALL", "interval": "1m", "adjustment": "NONE"}
    arguments[dimension] = value
    current = collect(monkeypatch, cfg, close=300, **arguments)

    sealed = plan(cfg, EXACT_SCOPE, **arguments)

    assert sealed.status == "PLANNED"
    assert sealed.plan_version != PURGE_PLAN_VERSION_V4
    assert [item["ingestion_run_id"] for item in sealed.targets] == [current.run_id]


@pytest.mark.parametrize(
    "mutation",
    [
        "quarantine_hash",
        "quarantine_missing",
        "prior_precommit",
        "catalog_result_hash",
        "new_active",
        "new_unregistered",
        "new_running",
        "registry_binding",
    ],
)
def test_stale_v4_plan_refuses_before_first_movement(
    monkeypatch, tmp_path, mutation
):
    cfg = settings(tmp_path)
    _, _, current, superseded = three_versions(monkeypatch, cfg)
    sealed = plan(cfg, EXACT_SCOPE)
    prior_record = Catalog(cfg).purge_operation(superseded.plan_id)
    assert prior_record is not None
    prior_raw = (
        cfg.data_root
        / sealed.reconciled_quarantined_units[0]["raw"][
            "quarantine_relative_path"
        ]
    )
    if mutation == "quarantine_hash":
        prior_raw.write_bytes(prior_raw.read_bytes() + b"drift")
    elif mutation == "quarantine_missing":
        prior_raw.unlink()
    elif mutation == "prior_precommit":
        Path(prior_record["precommit_file"]).write_bytes(
            Path(prior_record["precommit_file"]).read_bytes() + b" "
        )
    elif mutation == "catalog_result_hash":
        with Catalog(cfg).connect() as con:
            con.execute(
                "UPDATE purge_operations SET result_hash = ? WHERE plan_id = ?",
                ["0" * 64, superseded.plan_id],
            )
    elif mutation in {"new_active", "new_running"}:
        extra = collect(monkeypatch, cfg, close=400)
        if mutation == "new_running":
            with Catalog(cfg).connect() as con:
                con.execute(
                    "UPDATE ingestion_runs SET status = 'RUNNING' WHERE run_id = ?",
                    [extra.run_id],
                )
    elif mutation == "new_unregistered":
        for path in (Path(current.raw_file), Path(current.curated_file)):
            shutil.copy2(path, path.with_name(f"unregistered-{path.name}"))
    else:
        with Catalog(cfg).connect() as con:
            con.execute(
                """
                UPDATE market_bar_snapshot_pairs
                SET raw_file = raw_file || '.drift'
                WHERE run_id = ? AND symbol = 'US.SPY'
                """,
                [current.run_id],
            )

    with pytest.raises(PurgeError):
        execute(cfg, sealed)

    assert Path(current.raw_file).exists()
    assert Path(current.curated_file).exists()
    assert not (
        cfg.data_root / "quarantine" / f"purge_id={sealed.plan_id}"
    ).exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_unit_field",
        "unknown_unit_field",
        "unsafe_evidence_path",
        "unknown_prior_plan_version",
        "unknown_prior_precommit_version",
        "unknown_prior_result_version",
    ],
)
def test_v4_canonical_schema_and_evidence_versions_fail_closed(
    monkeypatch, tmp_path, mutation
):
    cfg = settings(tmp_path)
    _, _, current, _ = three_versions(monkeypatch, cfg)
    sealed = plan(cfg, EXACT_SCOPE)
    path = Path(sealed.plan_file)
    payload = json.loads(path.read_bytes())
    unit = payload["reconciled_quarantined_units"][0]
    authority = unit["prior_purge_authority"]
    if mutation == "missing_unit_field":
        unit.pop("logical_keys")
    elif mutation == "unknown_unit_field":
        unit["future"] = False
    elif mutation == "unsafe_evidence_path":
        authority["plan_evidence_relative_path"] = "../outside.json"
    elif mutation == "unknown_prior_plan_version":
        authority["plan_version"] = "market-vault-safe-purge-plan-v99"
    elif mutation == "unknown_prior_precommit_version":
        authority["precommit_version"] = "market-vault-safe-purge-precommit-v99"
    else:
        authority["terminal_result_version"] = "market-vault-safe-purge-result-v99"
    path.write_bytes(canonical_bytes(payload))

    with pytest.raises(PurgeError):
        execute(cfg, sealed)

    assert Path(current.raw_file).exists()
    assert Path(current.curated_file).exists()
    assert not (
        cfg.data_root / "quarantine" / f"purge_id={sealed.plan_id}"
    ).exists()
