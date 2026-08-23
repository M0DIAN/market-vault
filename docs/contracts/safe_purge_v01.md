# Safe Purge v0.1 Contract

## Scope

Safe Purge applies only to immutable historical `market_bars` Raw and Curated
Parquet snapshots. A request must name the configured source, one or more
exact symbols, an inclusive date range, interval, requested session,
adjustment, and source schema version. There is no wildcard scope, arbitrary
path target, Raw-only operation, Curated-only operation, permanent deletion,
or cascade into another dataset kind.

## Physical Lifecycle Unit

One ingestion run's complete Raw and Curated files form one lifecycle unit.
Planning inspects the files' actual columns and values and seals their relative
paths, SHA-256 hashes, byte sizes, row counts, symbols, dates, request key, and
run ID. If either file contains a symbol, date, or request-key value outside
the requested scope, the entire plan is `REFUSED` with `COLOCATED_SYMBOLS` or
`COLOCATED_DATA`. Immutable Parquet files are never split or rewritten.

## Derived Artifact Retention

Committed Verified Canonical builds are self-contained and retain embedded
source snapshot hashes and provenance. Committed Dataset artifacts are read
and verified without reloading Canonical. Committed Dataset Catalog snapshots
are read and verified without reloading recorded Dataset paths. These official
derived artifacts are therefore retained, non-blocking provenance dependents
when source Raw/Curated files move to quarantine. No cascade is permitted.

Arbitrary external programs and user-managed output paths are outside the
MarketVault lifecycle guarantee. Safe Purge neither claims to discover them
nor uses their discoverability as a false safety proof.

## Sealed Two-Phase Operation

`purge_plan` is local and does not modify active market data. It writes an
immutable deterministic plan under `manifests/purge/plans/` and indexes its
state in DuckDB. `purge_execute` accepts only the exact confirmation
`PURGE <plan_id>`, reloads and hashes the sealed plan, acquires the shared
market-bar lifecycle lock, and revalidates every file before mutation. New,
missing, changed, unsafe, unpaired, or unplanned files fail closed.

Eligible files move on the same filesystem to:

```text
data/quarantine/purge_id=<plan_id>/<original path below data/>
```

The original relative path and bytes are preserved. Quarantine has no expiry
or permanent-delete operation in v0.1.

## State and Evidence

The backward-compatible `purge_operations` Catalog table indexes `PLANNED`,
`REFUSED`, `EXECUTING`, `SUCCESS`, and `FAILED` operations. Immutable plan and
result JSON are the detailed evidence. Ingestion runs, collection manifests,
and quality reports remain intact. Interrupted or partially rolled-back work
never becomes `SUCCESS`; an exact completed retry is idempotent.

`collect_history`, purge planning, and purge execution share an exclusive
cross-process directory lock under `data/.lifecycle/`. A stale lock is not
automatically reclaimed. Read-only queries do not take this lock; during a
short lifecycle transition they may fail or retry, but they must not infer
missing data as a successful purge. Views are refreshed after movement or
rollback, and quarantined files are outside every active Raw/Curated glob.
