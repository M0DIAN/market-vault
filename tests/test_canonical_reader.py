"""Regression tests for the explicit single-file canonical bars reader
(v0.6.0 post-merge hotfix).

``load_verified_canonical_build`` must read every manifest-listed bars
Parquet file as one explicit file. The bars files live under Hive-style
``key=value`` parent directories (``interval=1m/adjustment=NONE/code=...``)
and carry the same-named business columns inside the file; on some PyArrow
versions ``pq.read_table(path)`` inspects those parent directories and
merges the inferred dictionary-encoded partition columns with the file's
string columns, failing with ``Unable to merge: Field interval has
incompatible types: string vs dictionary<...>``. The reader therefore uses
:class:`pyarrow.parquet.ParquetFile` — the explicit single-file reader — for
both the schema and the rows.

These tests pin that contract with real Parquet files under Hive-style
parent directories: the real verified build chain reads them, the reader
never falls back to a partition-inferring entry point, the schema stays
strictly equal to :func:`canonical_bars_schema`, and a truly corrupt file
still fails closed with the unchanged error contract.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from market_vault.canonical import (
    CanonicalArtifactValidationError,
    CanonicalRequestKey,
    load_verified_canonical_build,
    materialize_canonical_market_bars,
)
from market_vault.canonical.schema import canonical_bars_schema
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars, normalize_trading_calendar
from market_vault.storage import Catalog, ParquetStore

NY = "America/New_York"
DEFAULT_KEY = CanonicalRequestKey(
    interval="1m", requested_session="ALL", adjustment="NONE", source_schema_version="10.9"
)
CREATED_AT = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Real canonical-build fixtures (mirrors the materialization tests).
# ---------------------------------------------------------------------------


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


def calendar(cfg: Settings, *, trade_date: date = date(2026, 7, 1)) -> None:
    frame = pd.DataFrame({"time": [trade_date.isoformat()], "trade_date_type": ["WHOLE"]})
    curated = normalize_trading_calendar(
        frame, market="US", code=None,
        requested_start_date=trade_date, requested_end_date=trade_date,
        captured_at=pd.Timestamp("2026-08-01T01:00:00Z"), source="moomoo",
        source_schema_version=cfg.source_schema_version, run_id="cal",
    )
    ParquetStore(cfg).write_trading_calendar_curated(
        curated, "MARKET", "US", trade_date, trade_date, "cal"
    )
    Catalog(cfg).refresh_trading_calendar_views()


def minute_keys(start: str, count: int) -> list[str]:
    base = pd.Timestamp(start, tz=NY)
    return [
        (base + pd.Timedelta(int(i), unit="m")).strftime("%Y-%m-%d %H:%M:%S")
        for i in range(count)
    ]


def write_snapshot(
    cfg: Settings,
    *,
    code: str,
    trade_date: date,
    run_id: str,
    time_keys: list[str],
) -> None:
    store = ParquetStore(cfg)
    catalog = Catalog(cfg)
    raw = pd.DataFrame(
        {
            "code": [code] * len(time_keys),
            "name": [code] * len(time_keys),
            "time_key": time_keys,
            "open": [100.0] * len(time_keys),
            "high": [101.0] * len(time_keys),
            "low": [99.0] * len(time_keys),
            "close": [100.5] * len(time_keys),
            "volume": [100] * len(time_keys),
        }
    )
    curated = normalize_bars(
        raw, requested_trade_date=trade_date, interval="1m",
        requested_session="ALL", adjustment="NONE", source=cfg.source,
        source_schema_version=cfg.source_schema_version, run_id=run_id,
    )
    store.write_curated(curated, trade_date, "1m", [code], "ALL", "NONE", run_id=run_id)
    run = RunManifest(
        requested_trade_date=trade_date, requested_symbols=[code],
        interval="1m", session="ALL", adjustment="NONE", run_id=run_id,
    )
    run.successful_symbols = [code]
    run.status = "SUCCESS"
    run.finished_at = datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc)
    catalog.record_run(run)
    catalog.record_quality(run.run_id, [QualityResult("bars_complete", "PASS")])


def output_root(cfg: Settings) -> Path:
    return cfg.data_root / "canonical" / "dataset=market_bars_canonical"


def materialize(cfg: Settings, *, symbols=None, trade_dates=None):
    return materialize_canonical_market_bars(
        Catalog(cfg),
        symbols=symbols or ["US.MU"],
        trade_dates=trade_dates or [date(2026, 7, 1)],
        request_key=DEFAULT_KEY,
        output_root=output_root(cfg),
        created_at=CREATED_AT,
    )


def build(cfg: Settings):
    """One real materialized canonical build with six 1m bars on
    2026-07-01, returned as the verified build."""
    calendar(cfg)
    write_snapshot(
        cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
        time_keys=minute_keys("2026-07-01 09:30:00", 6),
    )
    result = materialize(cfg, symbols=["US.MU"], trade_dates=[date(2026, 7, 1)])
    return load_verified_canonical_build(result.build_path), result


# ---------------------------------------------------------------------------
# 1. Hive-style parent directories with same-named business columns.
# ---------------------------------------------------------------------------


def test_verified_build_chain_reads_hive_style_partitions(tmp_path):
    """The real materialize -> verified-read chain succeeds: bars files live
    under ``interval=1m/adjustment=NONE/...`` parent directories, the file
    internally carries the same-named ``interval`` / ``adjustment`` /
    ``session`` business columns, and the read must never treat the parent
    directory components as partition fields."""
    cfg = settings(tmp_path)
    verified, result = build(cfg)
    assert verified.bars
    assert len(verified.bars) == 6

    # The bars file really sits under Hive-style key=value parent
    # directories and carries the same-named columns inside the file.
    bars_files = sorted((result.build_path / "bars").rglob("*.parquet"))
    assert bars_files
    relative_parts = bars_files[0].relative_to(result.build_path).parts
    assert "interval=1m" in relative_parts
    assert "adjustment=NONE" in relative_parts
    assert "code=US.MU" in relative_parts

    # The strict schema contract is unchanged: the on-disk schema exactly
    # equals the formal canonical bars schema.
    schema = pq.ParquetFile(bars_files[0]).schema_arrow
    assert schema.equals(canonical_bars_schema(), check_metadata=False)
    field_names = {field.name for field in schema}
    assert {"interval", "adjustment", "session"} <= field_names


# ---------------------------------------------------------------------------
# 2. The reader never uses a partition-inferring entry point.
# ---------------------------------------------------------------------------


def test_bars_reader_never_uses_partition_inferring_entry(tmp_path, monkeypatch):
    """``pq.read_table`` (whose dataset path can infer Hive partition
    columns from the parent directories) must never be called; the verified
    chain must read through the explicit single-file reader."""
    import market_vault.canonical.reader as reader

    monkeypatch.setattr(
        reader.pq,
        "read_table",
        lambda *a, **k: pytest.fail("read_table must never be called"),
    )
    cfg = settings(tmp_path)
    verified, _ = build(cfg)
    assert verified.bars


# ---------------------------------------------------------------------------
# 3. A truly corrupt bars Parquet still fails closed.
# ---------------------------------------------------------------------------


def test_corrupt_bars_parquet_fails_closed(tmp_path):
    """A corrupt bars Parquet file must still surface as
    :class:`CanonicalArtifactValidationError` with the unchanged
    ``failed to read bars parquet`` message: the fix must not relax
    corruption detection."""
    import market_vault.canonical.reader as reader

    cfg = settings(tmp_path)
    _, result = build(cfg)
    bars_files = sorted((result.build_path / "bars").rglob("*.parquet"))
    assert bars_files
    target = bars_files[0]
    with target.open("wb") as handle:
        handle.write(b"NOT-A-PARQUET-FILE")
    with pytest.raises(CanonicalArtifactValidationError) as excinfo:
        reader._read_bars(
            result.build_path,
            [
                {
                    "relative_path": str(
                        target.relative_to(result.build_path)
                    ).replace("\\", "/"),
                    "file_role": "bars",
                }
            ],
        )
    assert "failed to read bars parquet" in str(excinfo.value)
