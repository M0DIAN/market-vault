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
run ID. It also seals the exact `ingestion_runs` Raw/Curated paths, request
metadata, and status. Execution re-resolves and compares every run row under
the lifecycle lock; deletion or any path, status, or metadata drift refuses
mutation. A `FAILED` run with neither physical path remains evidence but is
not a target. A one-sided pair is always refused. If either file contains a
symbol, date, or request-key value outside
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
result JSON are the detailed evidence. SUCCESS uses an explicit protocol:

1. write an immutable, non-terminal precommit containing the complete proposed
   canonical result and its hash;
2. atomically commit the Catalog `SUCCESS` row and exact result hash/path;
3. write, flush, fsync, and integrity-check a temporary result in the same
   directory, then atomically publish it without replacing an existing final
   result.

Catalog commit is the operation commit point. A commit failure rolls back the
files and can leave only non-terminal precommit plus `FAILED` evidence, never a
terminal `SUCCESS` result. If publication is interrupted after commit, an
idempotent retry validates the run bindings, quarantine identities, Catalog
hash, and precommit hash before staging and publishing exactly the
precommitted bytes. The final `result-*.json` name is never used as a write
target: it becomes visible only after complete canonical bytes pass integrity
verification. A byte-identical existing final result is accepted
idempotently; a conflicting existing result is retained and execution fails
closed without overwrite. Interrupted staging files are non-terminal residue.
The complete result schema, including message and timestamps, is integrity-bound.

Ingestion runs, collection manifests,
and quality reports remain intact. Interrupted or partially rolled-back work
never becomes `SUCCESS`; an exact completed retry is idempotent.

`collect_history`, the complete `collect_history_backfill` operation, purge
planning, and purge execution share an exclusive cross-process directory lock
under `data/.lifecycle/`. Backfill holds one reservation from local planning
through every child write and calls the locked collector core, so purge cannot
run between children. A stale lock is not
automatically reclaimed. Read-only queries do not take this lock; during a
short lifecycle transition they may fail or retry, but they must not infer
missing data as a successful purge. Views are refreshed after movement or
rollback, and quarantined files are outside every active Raw/Curated glob.
