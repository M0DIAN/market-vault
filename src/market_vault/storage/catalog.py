from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Iterable

import duckdb

from ..models import DatasetRunManifest, QualityResult, RunManifest, Settings


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
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS dataset_ingestion_runs (
                    run_id VARCHAR PRIMARY KEY,
                    dataset VARCHAR,
                    started_at TIMESTAMPTZ,
                    finished_at TIMESTAMPTZ,
                    status VARCHAR,
                    parameters JSON,
                    requested_items JSON,
                    successful_items JSON,
                    failed_items JSON,
                    raw_file VARCHAR,
                    curated_file VARCHAR,
                    quality_report VARCHAR,
                    row_count BIGINT,
                    config_hash VARCHAR
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

    def record_dataset_run(self, manifest: DatasetRunManifest) -> None:
        self.initialize()
        with self.connect() as con:
            con.execute("DELETE FROM dataset_ingestion_runs WHERE run_id = ?", [manifest.run_id])
            con.execute(
                """
                INSERT INTO dataset_ingestion_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    manifest.run_id,
                    manifest.dataset,
                    manifest.started_at,
                    manifest.finished_at,
                    manifest.status,
                    json.dumps(manifest.parameters),
                    json.dumps(manifest.requested_items),
                    json.dumps(manifest.successful_items),
                    json.dumps(manifest.failed_items),
                    manifest.raw_file,
                    manifest.curated_file,
                    manifest.quality_report,
                    manifest.row_count,
                    manifest.config_hash,
                ],
            )

    def refresh_market_bars_view(self) -> bool:
        curated_root = self.settings.data_root / "curated" / f"source={self.settings.source}" / "dataset=market_bars"
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

    def trading_calendar_dates(
        self,
        scope_type: str,
        scope_value: str,
        start_date: date,
        end_date: date,
    ) -> list[date]:
        if not self.refresh_trading_calendar_views():
            return []
        sql = """
            SELECT DISTINCT trade_date
            FROM trading_calendar_latest
            WHERE scope_type = ?
              AND scope_value = ?
              AND trade_date >= ?
              AND trade_date <= ?
            ORDER BY trade_date
        """
        with self.connect() as con:
            rows = con.execute(sql, [scope_type, scope_value, start_date, end_date]).fetchall()
        return [row[0] for row in rows]

    def trading_calendar_requested_ranges(
        self,
        scope_type: str,
        scope_value: str,
        start_date: date,
        end_date: date,
    ) -> list[tuple[date, date]]:
        if not self.refresh_trading_calendar_views():
            return []
        sql = """
            SELECT DISTINCT requested_start_date, requested_end_date
            FROM trading_calendar_latest
            WHERE scope_type = ?
              AND scope_value = ?
              AND requested_end_date >= ?
              AND requested_start_date <= ?
            ORDER BY requested_start_date, requested_end_date
        """
        with self.connect() as con:
            rows = con.execute(sql, [scope_type, scope_value, start_date, end_date]).fetchall()
        return [(row[0], row[1]) for row in rows]

    def completed_market_bar_items(
        self,
        *,
        symbols: list[str],
        trade_dates: list[date],
        interval: str,
        requested_session: str,
        adjustment: str,
        source_schema_version: str,
    ) -> set[tuple[str, date]]:
        curated_root = self.settings.data_root / "curated" / f"source={self.settings.source}" / "dataset=market_bars"
        curated_files = list(curated_root.rglob("*.parquet")) if curated_root.exists() else []
        if not curated_files or not symbols or not trade_dates:
            return set()
        min_date = min(trade_dates)
        max_date = max(trade_dates)
        codes_clause = ", ".join("?" for _ in symbols)
        with self.connect() as con:
            has_requested_session = self._parquet_files_have_column(con, curated_files, "requested_session")
            has_source_schema_version = self._parquet_files_have_column(con, curated_files, "source_schema_version")
            requested_session_expr = (
                "requested_session"
                if has_requested_session
                else "NULL::VARCHAR AS requested_session"
            )
            source_schema_expr = (
                "source_schema_version"
                if has_source_schema_version
                else "NULL::VARCHAR AS source_schema_version"
            )
            curated_glob = (curated_root / "**" / "*.parquet").as_posix().replace("'", "''")
            sql = f"""
                WITH failed_runs AS (
                    SELECT DISTINCT run_id
                    FROM quality_results
                    WHERE result = 'FAIL'
                ),
                eligible_runs AS (
                    SELECT run_id, requested_trade_date, interval, session, adjustment
                    FROM ingestion_runs
                    WHERE status IN ('SUCCESS', 'PARTIAL')
                      AND run_id NOT IN (SELECT run_id FROM failed_runs)
                ),
                curated AS (
                    SELECT
                        code,
                        requested_trade_date,
                        interval,
                        adjustment,
                        {requested_session_expr},
                        {source_schema_expr},
                        ingestion_run_id
                    FROM read_parquet('{curated_glob}', union_by_name = true, hive_partitioning = true)
                    WHERE requested_trade_date >= ?
                      AND requested_trade_date <= ?
                      AND code IN ({codes_clause})
                )
                SELECT DISTINCT c.code, c.requested_trade_date
                FROM curated c
                JOIN eligible_runs r
                  ON r.run_id = c.ingestion_run_id
                 AND r.requested_trade_date = c.requested_trade_date
                 AND r.interval = c.interval
                 AND r.adjustment = c.adjustment
                 AND r.session = c.requested_session
                WHERE c.interval = ?
                  AND c.adjustment = ?
                  AND c.requested_session = ?
                  AND c.source_schema_version = ?
            """
            params: list[object] = [min_date, max_date, *symbols, interval, adjustment, requested_session, source_schema_version]
            rows = con.execute(sql, params).fetchall()
        requested_dates = set(trade_dates)
        return {(row[0], row[1]) for row in rows if row[1] in requested_dates}

    def latest_completed_market_bar_dates(
        self,
        *,
        symbols: list[str],
        interval: str,
        requested_session: str,
        adjustment: str,
        source_schema_version: str,
        end_date: date,
    ) -> dict[str, date]:
        curated_root = self.settings.data_root / "curated" / f"source={self.settings.source}" / "dataset=market_bars"
        curated_files = list(curated_root.rglob("*.parquet")) if curated_root.exists() else []
        if not curated_files or not symbols:
            return {}
        codes_clause = ", ".join("?" for _ in symbols)
        with self.connect() as con:
            has_requested_session = self._parquet_files_have_column(con, curated_files, "requested_session")
            has_source_schema_version = self._parquet_files_have_column(con, curated_files, "source_schema_version")
            requested_session_expr = (
                "requested_session"
                if has_requested_session
                else "NULL::VARCHAR AS requested_session"
            )
            source_schema_expr = (
                "source_schema_version"
                if has_source_schema_version
                else "NULL::VARCHAR AS source_schema_version"
            )
            curated_glob = (curated_root / "**" / "*.parquet").as_posix().replace("'", "''")
            sql = f"""
                WITH failed_runs AS (
                    SELECT DISTINCT run_id
                    FROM quality_results
                    WHERE result = 'FAIL'
                ),
                eligible_runs AS (
                    SELECT run_id, requested_trade_date, interval, session, adjustment
                    FROM ingestion_runs
                    WHERE status IN ('SUCCESS', 'PARTIAL')
                      AND run_id NOT IN (SELECT run_id FROM failed_runs)
                ),
                curated AS (
                    SELECT
                        code,
                        requested_trade_date,
                        interval,
                        adjustment,
                        {requested_session_expr},
                        {source_schema_expr},
                        ingestion_run_id
                    FROM read_parquet('{curated_glob}', union_by_name = true, hive_partitioning = true)
                    WHERE requested_trade_date <= ?
                      AND code IN ({codes_clause})
                )
                SELECT c.code, max(c.requested_trade_date) AS latest_trade_date
                FROM curated c
                JOIN eligible_runs r
                  ON r.run_id = c.ingestion_run_id
                 AND r.requested_trade_date = c.requested_trade_date
                 AND r.interval = c.interval
                 AND r.adjustment = c.adjustment
                 AND r.session = c.requested_session
                WHERE c.interval = ?
                  AND c.adjustment = ?
                  AND c.requested_session = ?
                  AND c.source_schema_version = ?
                GROUP BY c.code
            """
            params: list[object] = [end_date, *symbols, interval, adjustment, requested_session, source_schema_version]
            rows = con.execute(sql, params).fetchall()
        return {row[0]: row[1] for row in rows}

    def refresh_option_contract_views(self) -> bool:
        raw_root = self.settings.data_root / "raw" / f"source={self.settings.source}" / "dataset=option_chain"
        curated_root = self.settings.data_root / "curated" / "option_contracts"
        raw_files = list(raw_root.rglob("*.parquet")) if raw_root.exists() else []
        curated_files = list(curated_root.rglob("*.parquet")) if curated_root.exists() else []
        if not raw_files and not curated_files:
            return False
        with self.connect() as con:
            if raw_files:
                raw_glob = (raw_root / "**" / "*.parquet").as_posix().replace("'", "''")
                con.execute(
                    f"""
                    CREATE OR REPLACE VIEW option_contracts_raw AS
                    SELECT *
                    FROM read_parquet('{raw_glob}', union_by_name = true, hive_partitioning = true)
                    """
                )
            if curated_files:
                curated_glob = (curated_root / "**" / "*.parquet").as_posix().replace("'", "''")
                con.execute(
                    f"""
                    CREATE OR REPLACE VIEW option_contracts AS
                    SELECT *
                    FROM read_parquet('{curated_glob}', union_by_name = true, hive_partitioning = true)
                    """
                )
                con.execute(
                    f"""
                    CREATE OR REPLACE VIEW option_contracts_latest AS
                    SELECT * EXCLUDE (_rn)
                    FROM (
                        SELECT *,
                               row_number() OVER (
                                   PARTITION BY option_code
                                   ORDER BY captured_at DESC, ingestion_run_id DESC
                               ) AS _rn
                        FROM read_parquet('{curated_glob}', union_by_name = true, hive_partitioning = true)
                    )
                    WHERE _rn = 1
                    """
                )
        return True

    def refresh_option_volatility_views(self) -> bool:
        raw_root = self.settings.data_root / "raw" / f"source={self.settings.source}" / "dataset=option_volatility_daily"
        curated_root = self.settings.data_root / "curated" / "option_volatility_daily"
        raw_files = list(raw_root.rglob("*.parquet")) if raw_root.exists() else []
        curated_files = list(curated_root.rglob("*.parquet")) if curated_root.exists() else []
        if not raw_files and not curated_files:
            return False
        with self.connect() as con:
            if raw_files:
                raw_glob = (raw_root / "**" / "*.parquet").as_posix().replace("'", "''")
                con.execute(
                    f"""
                    CREATE OR REPLACE VIEW option_volatility_daily_raw AS
                    SELECT *
                    FROM read_parquet('{raw_glob}', union_by_name = true, hive_partitioning = true)
                    """
                )
            if curated_files:
                curated_glob = (curated_root / "**" / "*.parquet").as_posix().replace("'", "''")
                has_captured_at = self._parquet_files_have_column(con, curated_files, "captured_at")
                order_clause = (
                    "captured_at DESC NULLS LAST, ingestion_run_id DESC"
                    if has_captured_at
                    else "ingestion_run_id DESC"
                )
                con.execute(
                    f"""
                    CREATE OR REPLACE VIEW option_volatility_daily AS
                    SELECT * EXCLUDE (_rn)
                    FROM (
                        SELECT *,
                               row_number() OVER (
                                   PARTITION BY option_code, trade_date, source
                                   ORDER BY {order_clause}
                               ) AS _rn
                        FROM read_parquet('{curated_glob}', union_by_name = true, hive_partitioning = true)
                    )
                    WHERE _rn = 1
                    """
                )
        return True

    def refresh_trading_calendar_views(self) -> bool:
        raw_root = self.settings.data_root / "raw" / f"source={self.settings.source}" / "dataset=trading_calendar"
        curated_root = self.settings.data_root / "curated" / "trading_calendar"
        raw_files = list(raw_root.rglob("*.parquet")) if raw_root.exists() else []
        curated_files = list(curated_root.rglob("*.parquet")) if curated_root.exists() else []
        if not raw_files and not curated_files:
            return False
        with self.connect() as con:
            if raw_files:
                raw_glob = (raw_root / "**" / "*.parquet").as_posix().replace("'", "''")
                con.execute(
                    f"""
                    CREATE OR REPLACE VIEW trading_calendar_raw AS
                    SELECT *
                    FROM read_parquet('{raw_glob}', union_by_name = true, hive_partitioning = true)
                    """
                )
            if curated_files:
                curated_glob = (curated_root / "**" / "*.parquet").as_posix().replace("'", "''")
                has_captured_at = self._parquet_files_have_column(con, curated_files, "captured_at")
                has_requested_start = self._parquet_files_have_column(con, curated_files, "requested_start_date")
                has_requested_end = self._parquet_files_have_column(con, curated_files, "requested_end_date")
                order_clause = (
                    "captured_at DESC NULLS LAST, ingestion_run_id DESC"
                    if has_captured_at
                    else "ingestion_run_id DESC"
                )
                effective_start_expr = (
                    "COALESCE(requested_start_date, trade_date)" if has_requested_start else "trade_date"
                )
                effective_end_expr = (
                    "COALESCE(requested_end_date, trade_date)" if has_requested_end else "trade_date"
                )
                public_requested_start_expr = (
                    "COALESCE(requested_start_date, trade_date) AS requested_start_date"
                    if has_requested_start
                    else "trade_date AS requested_start_date"
                )
                public_requested_end_expr = (
                    "COALESCE(requested_end_date, trade_date) AS requested_end_date"
                    if has_requested_end
                    else "trade_date AS requested_end_date"
                )
                public_columns = f"""
                    scope_type,
                    scope_value,
                    market,
                    reference_code,
                    trade_date,
                    trade_date_type,
                    {public_requested_start_expr},
                    {public_requested_end_expr},
                    captured_at,
                    source,
                    source_schema_version,
                    ingestion_run_id
                """
                con.execute(
                    f"""
                    CREATE OR REPLACE VIEW trading_calendar AS
                    SELECT {public_columns}
                    FROM read_parquet('{curated_glob}', union_by_name = true, hive_partitioning = true)
                    """
                )
                con.execute(
                    f"""
                    CREATE OR REPLACE VIEW trading_calendar_latest AS
                    WITH all_rows AS (
                        SELECT {public_columns}
                        FROM read_parquet('{curated_glob}', union_by_name = true, hive_partitioning = true)
                    ),
                    snapshots AS (
                        SELECT DISTINCT
                            scope_type,
                            scope_value,
                            source,
                            ingestion_run_id,
                            captured_at,
                            {effective_start_expr} AS effective_start_date,
                            {effective_end_expr} AS effective_end_date
                        FROM all_rows
                    ),
                    historical_dates AS (
                        SELECT DISTINCT scope_type, scope_value, trade_date, source
                        FROM all_rows
                    ),
                    latest_covering_snapshot AS (
                        SELECT * EXCLUDE (_rn)
                        FROM (
                            SELECT
                                d.scope_type,
                                d.scope_value,
                                d.trade_date,
                                d.source,
                                s.ingestion_run_id,
                                s.captured_at,
                                row_number() OVER (
                                    PARTITION BY d.scope_type, d.scope_value, d.trade_date, d.source
                                    ORDER BY {order_clause}
                                ) AS _rn
                            FROM historical_dates d
                            JOIN snapshots s
                              ON s.scope_type = d.scope_type
                             AND s.scope_value = d.scope_value
                             AND s.source = d.source
                             AND s.effective_start_date <= d.trade_date
                             AND s.effective_end_date >= d.trade_date
                        )
                        WHERE _rn = 1
                    )
                    SELECT
                        r.scope_type,
                        r.scope_value,
                        r.market,
                        r.reference_code,
                        r.trade_date,
                        r.trade_date_type,
                        r.requested_start_date,
                        r.requested_end_date,
                        r.captured_at,
                        r.source,
                        r.source_schema_version,
                        r.ingestion_run_id
                    FROM all_rows r
                    JOIN latest_covering_snapshot s
                      ON s.scope_type = r.scope_type
                     AND s.scope_value = r.scope_value
                     AND s.trade_date = r.trade_date
                     AND s.source = r.source
                     AND s.ingestion_run_id = r.ingestion_run_id
                     AND s.captured_at IS NOT DISTINCT FROM r.captured_at
                    """
                )
        return True

    def _parquet_files_have_column(self, con, files: list[Path], column: str) -> bool:
        for file in files:
            path = file.as_posix().replace("'", "''")
            try:
                columns = [row[0] for row in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{path}')").fetchall()]
            except duckdb.Error:
                continue
            if column in columns:
                return True
        return False
