from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import duckdb
import pandas as pd

from ..models import DatasetRunManifest, QualityResult, RunManifest, Settings


@dataclass(frozen=True)
class CompleteSnapshotRef:
    """Reference to one immutable complete physical snapshot of a (code, trade date)."""

    code: str
    requested_trade_date: date
    ingestion_run_id: str
    snapshot_file: str
    snapshot_ingested_at: datetime | None
    run_finished_at: datetime | None
    row_count: int


@dataclass(frozen=True)
class SnapshotRows:
    """Rows of a single physical snapshot plus its own column schema."""

    frame: pd.DataFrame
    physical_columns: set[str]

#: Stable order for incomplete-item reasons reported to audits.
INCOMPLETE_REASON_PRIORITY = (
    "QUALITY_FAIL",
    "RUN_FAILED",
    "RUN_RUNNING",
    "RUN_METADATA_MISMATCH",
    "ORPHANED_RUN",
    "RUN_STATUS_UNKNOWN",
)


def _snapshot_incomplete_reason(
    run_id: str | None,
    run_status: str | None,
    has_quality_fail: bool,
    run_metadata: tuple | None,
    curated_metadata: tuple,
) -> str | None:
    """Reason why a single snapshot cannot satisfy the completion criteria.

    Returns None when the snapshot is complete: the run is SUCCESS or PARTIAL
    with no FAIL quality result and its request metadata (trade date,
    interval, session, adjustment) matches the curated row. Empty run ids
    cannot be attributed and are reported as RUN_STATUS_UNKNOWN; run ids
    missing from ingestion_runs are ORPHANED_RUN; runs whose metadata does
    not match the curated row are RUN_METADATA_MISMATCH.
    """
    if run_id is None or str(run_id).strip() == "":
        return "RUN_STATUS_UNKNOWN"
    if run_status is None:
        return "ORPHANED_RUN"
    if has_quality_fail:
        return "QUALITY_FAIL"
    if run_status == "FAILED":
        return "RUN_FAILED"
    if run_status == "RUNNING":
        return "RUN_RUNNING"
    if run_status not in ("SUCCESS", "PARTIAL"):
        return "RUN_STATUS_UNKNOWN"
    if run_metadata != curated_metadata:
        return "RUN_METADATA_MISMATCH"
    return None


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

    def run_has_quality_fail(self, run_id: str) -> bool:
        """Return True when a run has at least one FAIL quality result.

        Bar quality checks are recorded per run in quality_results, and the
        completion queries (completed_market_bar_items,
        latest_completed_market_bar_dates) treat any run with a FAIL result as
        not completed. The backfill must apply the same rule when deciding
        whether a child run's symbols are actually complete, instead of
        inferring it from the child run status (PARTIAL can also mean only
        some symbols failed their network requests).
        """
        self.initialize()
        if not run_id:
            return False
        with self.connect() as con:
            row = con.execute(
                "SELECT 1 FROM quality_results WHERE run_id = ? AND result = 'FAIL' LIMIT 1",
                [run_id],
            ).fetchone()
        return row is not None

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
                CREATE OR REPLACE VIEW market_bars_snapshots AS
                SELECT *
                FROM read_parquet('{glob_path}', union_by_name = true, hive_partitioning = true)
                """
            )
            try:
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
                        FROM market_bars_snapshots
                    )
                    WHERE _rn = 1
                    """
                )
            except duckdb.Error:
                # A snapshot file misses a column the dedup view requires
                # (e.g. time_utc). Keep the snapshots view so structural
                # audits can still report the missing column instead of
                # crashing, and report the public view as unavailable.
                return False
        return True

    def market_bars_snapshot_columns(self) -> set[str]:
        """Column names present in the union of all curated market-bar files."""
        curated_root = self.settings.data_root / "curated" / f"source={self.settings.source}" / "dataset=market_bars"
        files = list(curated_root.rglob("*.parquet")) if curated_root.exists() else []
        if not files:
            return set()
        glob_path = (curated_root / "**" / "*.parquet").as_posix().replace("'", "''")
        with self.connect() as con:
            rows = con.execute(
                f"""
                DESCRIBE SELECT * FROM read_parquet('{glob_path}', union_by_name = true, hive_partitioning = true)
                """
            ).fetchall()
        return {row[0] for row in rows}

    @staticmethod
    def _market_bars_curated_glob(settings: Settings) -> tuple[list[Path], str]:
        curated_root = settings.data_root / "curated" / f"source={settings.source}" / "dataset=market_bars"
        files = list(curated_root.rglob("*.parquet")) if curated_root.exists() else []
        if not files:
            return [], ""
        return files, (curated_root / "**" / "*.parquet").as_posix().replace("'", "''")

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
        self.initialize()
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

    def present_market_bar_items(
        self,
        *,
        symbols: list[str],
        trade_dates: list[date],
        interval: str,
        requested_session: str,
        adjustment: str,
        source_schema_version: str,
    ) -> set[tuple[str, date]]:
        """(code, trade_date) pairs with at least one curated row matching the
        exact request key, regardless of run status or quality results.

        Rows from legacy files missing requested_session or
        source_schema_version never match the exact key, so they are not
        reported as present.
        """
        files, curated_glob = self._market_bars_curated_glob(self.settings)
        if not curated_glob or not symbols or not trade_dates:
            return set()
        min_date = min(trade_dates)
        max_date = max(trade_dates)
        codes_clause = ", ".join("?" for _ in symbols)
        with self.connect() as con:
            session_expr = (
                "requested_session"
                if self._parquet_files_have_column(con, files, "requested_session")
                else "NULL::VARCHAR AS requested_session"
            )
            schema_expr = (
                "source_schema_version"
                if self._parquet_files_have_column(con, files, "source_schema_version")
                else "NULL::VARCHAR AS source_schema_version"
            )
            sql = f"""
                WITH curated AS (
                    SELECT
                        code,
                        requested_trade_date,
                        interval,
                        adjustment,
                        {session_expr},
                        {schema_expr}
                    FROM read_parquet('{curated_glob}', union_by_name = true, hive_partitioning = true)
                    WHERE requested_trade_date >= ?
                      AND requested_trade_date <= ?
                      AND code IN ({codes_clause})
                )
                SELECT DISTINCT c.code, c.requested_trade_date
                FROM curated c
                WHERE c.interval = ?
                  AND c.adjustment = ?
                  AND c.requested_session = ?
                  AND c.source_schema_version = ?
            """
            params: list[object] = [
                min_date,
                max_date,
                *symbols,
                interval,
                adjustment,
                requested_session,
                source_schema_version,
            ]
            rows = con.execute(sql, params).fetchall()
        return {(row[0], row[1]) for row in rows}

    def incomplete_market_bar_item_reasons(
        self,
        *,
        symbols: list[str],
        trade_dates: list[date],
        interval: str,
        requested_session: str,
        adjustment: str,
        source_schema_version: str,
    ) -> dict[tuple[str, date], list[str]]:
        """Per present (code, trade_date) the sorted, deduplicated reasons why
        no snapshot of that exact key satisfies the completion criteria.

        A key with any complete snapshot is not included in the result; the
        caller decides which keys are incomplete. Reasons follow
        INCOMPLETE_REASON_PRIORITY ordering.
        """
        files, curated_glob = self._market_bars_curated_glob(self.settings)
        if not curated_glob or not symbols or not trade_dates:
            return {}
        min_date = min(trade_dates)
        max_date = max(trade_dates)
        codes_clause = ", ".join("?" for _ in symbols)
        with self.connect() as con:
            session_expr = (
                "requested_session"
                if self._parquet_files_have_column(con, files, "requested_session")
                else "NULL::VARCHAR AS requested_session"
            )
            schema_expr = (
                "source_schema_version"
                if self._parquet_files_have_column(con, files, "source_schema_version")
                else "NULL::VARCHAR AS source_schema_version"
            )
            run_id_expr = (
                "ingestion_run_id"
                if self._parquet_files_have_column(con, files, "ingestion_run_id")
                else "NULL::VARCHAR AS ingestion_run_id"
            )
            sql = f"""
                WITH curated AS (
                    SELECT
                        code,
                        requested_trade_date,
                        interval,
                        adjustment,
                        {session_expr},
                        {schema_expr},
                        {run_id_expr}
                    FROM read_parquet('{curated_glob}', union_by_name = true, hive_partitioning = true)
                    WHERE requested_trade_date >= ?
                      AND requested_trade_date <= ?
                      AND code IN ({codes_clause})
                ),
                runs AS (
                    SELECT
                        run_id,
                        upper(status) AS status,
                        requested_trade_date,
                        interval,
                        session,
                        adjustment
                    FROM ingestion_runs
                ),
                failed AS (
                    SELECT DISTINCT run_id
                    FROM quality_results
                    WHERE result = 'FAIL'
                )
                SELECT
                    c.code,
                    c.requested_trade_date,
                    c.ingestion_run_id,
                    r.status,
                    f.run_id IS NOT NULL AS has_quality_fail,
                    r.requested_trade_date AS run_requested_trade_date,
                    r.interval AS run_interval,
                    r.session AS run_session,
                    r.adjustment AS run_adjustment
                FROM curated c
                LEFT JOIN runs r ON r.run_id = c.ingestion_run_id
                LEFT JOIN failed f ON f.run_id = c.ingestion_run_id
                WHERE c.interval = ?
                  AND c.adjustment = ?
                  AND c.requested_session = ?
                  AND c.source_schema_version = ?
            """
            params: list[object] = [
                min_date,
                max_date,
                *symbols,
                interval,
                adjustment,
                requested_session,
                source_schema_version,
            ]
            rows = con.execute(sql, params).fetchall()
        reasons: dict[tuple[str, date], set[str]] = {}
        for (
            code,
            trade_date,
            run_id,
            run_status,
            has_quality_fail,
            run_requested_trade_date,
            run_interval,
            run_session,
            run_adjustment,
        ) in rows:
            # Both tuples follow the same field order: trade date, interval,
            # session, adjustment -- expanding the request-key parameters
            # explicitly here so the comparison cannot drift out of sync.
            reason = _snapshot_incomplete_reason(
                run_id,
                run_status,
                has_quality_fail,
                run_metadata=(
                    run_requested_trade_date,
                    run_interval,
                    run_session,
                    run_adjustment,
                ),
                curated_metadata=(
                    trade_date,
                    interval,
                    requested_session,
                    adjustment,
                ),
            )
            if reason is not None:
                reasons.setdefault((code, trade_date), set()).add(reason)
        return {
            key: sorted(values, key=INCOMPLETE_REASON_PRIORITY.index)
            for key, values in reasons.items()
        }

    def latest_complete_market_bar_snapshots(
        self,
        *,
        symbols: list[str],
        trade_dates: list[date],
        interval: str,
        requested_session: str,
        adjustment: str,
        source_schema_version: str,
    ) -> dict[tuple[str, date], CompleteSnapshotRef]:
        """Latest complete physical snapshot per (code, trade_date) for the
        exact key.

        Snapshot eligibility is identical to completed_market_bar_items: exact
        curated key match, run linked to ingestion_runs, run status SUCCESS or
        PARTIAL, no FAIL quality result, and run metadata matching the curated
        row. The curated glob is read with ``filename = true`` so each Parquet
        file is its own physical snapshot; the same run id in two files yields
        two snapshots and their row counts are never merged. The newest wins
        by snapshot_ingested_at DESC NULLS LAST, run_finished_at DESC NULLS
        LAST, ingestion_run_id DESC, snapshot_file DESC -- stable and
        deterministic.
        """
        self.initialize()
        files, curated_glob = self._market_bars_curated_glob(self.settings)
        if not curated_glob or not symbols or not trade_dates:
            return {}
        min_date = min(trade_dates)
        max_date = max(trade_dates)
        codes_clause = ", ".join("?" for _ in symbols)
        with self.connect() as con:
            session_expr = (
                "requested_session"
                if self._parquet_files_have_column(con, files, "requested_session")
                else "NULL::VARCHAR AS requested_session"
            )
            schema_expr = (
                "source_schema_version"
                if self._parquet_files_have_column(con, files, "source_schema_version")
                else "NULL::VARCHAR AS source_schema_version"
            )
            run_id_expr = (
                "ingestion_run_id"
                if self._parquet_files_have_column(con, files, "ingestion_run_id")
                else "NULL::VARCHAR AS ingestion_run_id"
            )
            ingested_expr = (
                "ingested_at"
                if self._parquet_files_have_column(con, files, "ingested_at")
                else "NULL::TIMESTAMPTZ AS ingested_at"
            )
            sql = f"""
                WITH curated AS (
                    SELECT
                        code,
                        requested_trade_date,
                        interval,
                        adjustment,
                        {session_expr},
                        {schema_expr},
                        {run_id_expr},
                        {ingested_expr},
                        filename
                    FROM read_parquet(
                        '{curated_glob}',
                        union_by_name = true,
                        hive_partitioning = true,
                        filename = true
                    )
                    WHERE requested_trade_date >= ?
                      AND requested_trade_date <= ?
                      AND code IN ({codes_clause})
                ),
                eligible AS (
                    SELECT
                        c.code,
                        c.requested_trade_date,
                        c.ingestion_run_id,
                        c.filename AS snapshot_file,
                        MAX(c.ingested_at) AS snapshot_ingested_at,
                        COUNT(*) AS row_count,
                        r.finished_at AS run_finished_at
                    FROM curated c
                    JOIN ingestion_runs r
                      ON r.run_id = c.ingestion_run_id
                     AND r.requested_trade_date = c.requested_trade_date
                     AND r.interval = c.interval
                     AND r.adjustment = c.adjustment
                     AND r.session = c.requested_session
                    WHERE c.interval = ?
                      AND c.adjustment = ?
                      AND c.requested_session = ?
                      AND c.source_schema_version = ?
                      AND upper(r.status) IN ('SUCCESS', 'PARTIAL')
                      AND c.ingestion_run_id NOT IN (
                          SELECT run_id FROM quality_results WHERE result = 'FAIL'
                      )
                    GROUP BY
                        c.code,
                        c.requested_trade_date,
                        c.ingestion_run_id,
                        c.filename,
                        r.finished_at
                ),
                ranked AS (
                    SELECT *,
                           row_number() OVER (
                               PARTITION BY code, requested_trade_date
                               ORDER BY
                                   snapshot_ingested_at DESC NULLS LAST,
                                   run_finished_at DESC NULLS LAST,
                                   ingestion_run_id DESC,
                                   snapshot_file DESC
                           ) AS _rn
                    FROM eligible
                )
                SELECT
                    code,
                    requested_trade_date,
                    ingestion_run_id,
                    snapshot_file,
                    snapshot_ingested_at,
                    run_finished_at,
                    row_count
                FROM ranked
                WHERE _rn = 1
                ORDER BY requested_trade_date, code
            """
            params: list[object] = [
                min_date,
                max_date,
                *symbols,
                interval,
                adjustment,
                requested_session,
                source_schema_version,
            ]
            rows = con.execute(sql, params).fetchall()
        return {
            (row[0], row[1]): CompleteSnapshotRef(
                code=row[0],
                requested_trade_date=row[1],
                ingestion_run_id=row[2],
                snapshot_file=self._normalize_snapshot_file(row[3]),
                snapshot_ingested_at=row[4],
                run_finished_at=row[5],
                row_count=int(row[6]),
            )
            for row in rows
        }

    def market_bar_snapshot_rows(
        self,
        snapshot: CompleteSnapshotRef,
        *,
        interval: str,
        requested_session: str,
        adjustment: str,
        source_schema_version: str,
    ) -> SnapshotRows:
        """All rows of one physical snapshot file for the exact key.

        Reads only ``snapshot.snapshot_file`` -- never a glob or another
        curated file -- keeps duplicates, filters exactly on every request-key
        parameter plus the run id, and sorts by time_utc. ``physical_columns``
        reflects the schema of the selected file only, so other files cannot
        mask missing columns. Never modifies stored data and does not depend
        on the public market_bars view being creatable.
        """
        file_path = self._resolve_snapshot_file(snapshot.snapshot_file)
        if file_path is None or not file_path.exists():
            return SnapshotRows(frame=pd.DataFrame(), physical_columns=set())
        escaped = file_path.as_posix().replace("'", "''")
        with self.connect() as con:
            physical_columns = {
                row[0]
                for row in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{escaped}')").fetchall()
            }
            required_filters = {
                "code",
                "requested_trade_date",
                "interval",
                "adjustment",
                "requested_session",
                "source_schema_version",
                "ingestion_run_id",
            }
            if not required_filters.issubset(physical_columns):
                # The physical file lacks a filter column, so its rows cannot
                # be attributed to the request key; report the real schema.
                return SnapshotRows(frame=pd.DataFrame(), physical_columns=physical_columns)
            order_by = " ORDER BY time_utc" if "time_utc" in physical_columns else ""
            sql = f"""
                SELECT *
                FROM read_parquet('{escaped}')
                WHERE code = ?
                  AND requested_trade_date = ?
                  AND interval = ?
                  AND adjustment = ?
                  AND requested_session = ?
                  AND source_schema_version = ?
                  AND ingestion_run_id = ?
                {order_by}
            """
            params: list[object] = [
                snapshot.code,
                snapshot.requested_trade_date,
                interval,
                adjustment,
                requested_session,
                source_schema_version,
                snapshot.ingestion_run_id,
            ]
            frame = con.execute(sql, params).fetchdf()
        return SnapshotRows(frame=frame, physical_columns=physical_columns)

    def _normalize_snapshot_file(self, filename: str | None) -> str:
        """Normalize a DuckDB filename virtual column to a data-root relative path."""
        if not filename:
            return ""
        path = Path(str(filename))
        try:
            return path.relative_to(self.settings.data_root).as_posix()
        except ValueError:
            # Defensive: paths outside the data root keep only their filename.
            return path.name

    def _resolve_snapshot_file(self, snapshot_file: str) -> Path | None:
        """Resolve a snapshot file path, refusing paths outside the curated
        market-bars root."""
        curated_root = (
            self.settings.data_root / "curated" / f"source={self.settings.source}" / "dataset=market_bars"
        ).resolve()
        path = (self.settings.data_root / snapshot_file).resolve()
        if not path.is_relative_to(curated_root):
            return None
        return path

    def trading_dates_after(
        self,
        scope_type: str,
        scope_value: str,
        after_date: date,
        end_date: date,
    ) -> list[date]:
        """Local trading dates strictly after a date, at or before end_date.

        Dates come from trading_calendar_latest only: no weekday, weekend, or
        holiday rules are applied here.
        """
        if not self.refresh_trading_calendar_views():
            return []
        sql = """
            SELECT DISTINCT trade_date
            FROM trading_calendar_latest
            WHERE scope_type = ?
              AND scope_value = ?
              AND trade_date > ?
              AND trade_date <= ?
            ORDER BY trade_date
        """
        with self.connect() as con:
            rows = con.execute(sql, [scope_type, scope_value, after_date, end_date]).fetchall()
        return [row[0] for row in rows]

    def next_trading_date(
        self,
        scope_type: str,
        scope_value: str,
        after_date: date,
        end_date: date,
    ) -> date | None:
        """First local trading date strictly after a date and at or before end_date.

        Returns None when the local calendar has no such date (e.g. the
        symbol is already caught up through end_date, or the calendar
        snapshot does not extend past the latest completed date).
        """
        if not self.refresh_trading_calendar_views():
            return None
        sql = """
            SELECT MIN(trade_date)
            FROM trading_calendar_latest
            WHERE scope_type = ?
              AND scope_value = ?
              AND trade_date > ?
              AND trade_date <= ?
        """
        with self.connect() as con:
            row = con.execute(sql, [scope_type, scope_value, after_date, end_date]).fetchone()
        return row[0] if row is not None and row[0] is not None else None

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
