from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import duckdb

from ..models import QualityResult, RunManifest, Settings


class Catalog:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.catalog_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self):
        return duckdb.connect(str(self.settings.catalog_path))

    def initialize(self) -> None:
        with self.connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_runs (
                    run_id VARCHAR PRIMARY KEY,
                    started_at TIMESTAMPTZ,
                    finished_at TIMESTAMPTZ,
                    requested_trade_date DATE,
                    requested_symbols JSON,
                    interval VARCHAR,
                    session VARCHAR,
                    adjustment VARCHAR,
                    successful_symbols JSON,
                    failed_symbols JSON,
                    raw_file VARCHAR,
                    curated_file VARCHAR,
                    row_count BIGINT,
                    status VARCHAR,
                    config_hash VARCHAR
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS quality_results (
                    run_id VARCHAR,
                    check_name VARCHAR,
                    result VARCHAR,
                    expected_value VARCHAR,
                    actual_value VARCHAR,
                    details VARCHAR
                )
                """
            )

    def record_run(self, manifest: RunManifest) -> None:
        self.initialize()
        with self.connect() as con:
            con.execute("DELETE FROM ingestion_runs WHERE run_id = ?", [manifest.run_id])
            con.execute(
                """
                INSERT INTO ingestion_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    manifest.run_id,
                    manifest.started_at,
                    manifest.finished_at,
                    manifest.requested_trade_date,
                    json.dumps(manifest.requested_symbols),
                    manifest.interval,
                    manifest.session,
                    manifest.adjustment,
                    json.dumps(manifest.successful_symbols),
                    json.dumps(manifest.failed_symbols),
                    manifest.raw_file,
                    manifest.curated_file,
                    manifest.row_count,
                    manifest.status,
                    manifest.config_hash,
                ],
            )

    def record_quality(self, run_id: str, results: Iterable[QualityResult]) -> None:
        self.initialize()
        rows = [
            [run_id, r.check_name, r.result, r.expected_value, r.actual_value, r.details]
            for r in results
        ]
        with self.connect() as con:
            con.execute("DELETE FROM quality_results WHERE run_id = ?", [run_id])
            if rows:
                con.executemany("INSERT INTO quality_results VALUES (?, ?, ?, ?, ?, ?)", rows)

    def refresh_market_bars_view(self) -> bool:
        curated_root = self.settings.data_root / "curated"
        files = list(curated_root.rglob("*.parquet")) if curated_root.exists() else []
        if not files:
            return False
        glob_path = (curated_root / "**" / "*.parquet").as_posix().replace("'", "''")
        with self.connect() as con:
            con.execute(
                f"""
                CREATE OR REPLACE VIEW market_bars AS
                SELECT * EXCLUDE (_rn)
                FROM (
                    SELECT *,
                           row_number() OVER (
                               PARTITION BY code, interval, adjustment, time_utc
                               ORDER BY ingested_at DESC
                           ) AS _rn
                    FROM read_parquet('{glob_path}', union_by_name = true, hive_partitioning = true)
                )
                WHERE _rn = 1
                """
            )
        return True
