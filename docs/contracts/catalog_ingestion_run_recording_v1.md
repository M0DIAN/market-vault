# Catalog Ingestion-Run Recording v1

## Purpose

`Catalog.record_run` is the state authority for publishing one complete `ingestion_runs` row for one concrete `RunManifest.run_id`. This contract promotes its existing fingerprint exemption to an exact machine-reviewed destructive binding; it does not change runtime behavior.

## Authority Boundary

The method MAY transactionally replace the row whose `run_id` exactly equals the supplied manifest's `run_id`. Its destructive surface MUST remain exactly one `destructive_sql / sql.DELETE_FROM` occurrence, followed by insertion of the caller's complete current run evidence in the same DuckDB transaction.

The method MUST NOT accept wildcard or generic deletion scope. It MUST NOT delete or replace unrelated ingestion runs, `market_bar_snapshot_pairs`, `quality_results`, `dataset_ingestion_runs`, or `purge_operations`. It MUST NOT mutate Parquet, manifests, reports, Canonical or Dataset artifacts, quarantine, or other filesystem paths.

## Commit And Failure Semantics

The commit point is the successful DuckDB transaction commit containing the complete replacement row for the exact `run_id`. A failure before commit MUST leave no committed half-replacement. A retry MAY replace that same exact row with complete current evidence and MUST leave unrelated rows unchanged.

This contract creates no new external destructive API and does not broaden existing lifecycle locking. It does not authorize Safe Purge, garbage collection, cascade cleanup, or permanent deletion.
