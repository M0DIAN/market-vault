# Safe Purge v0.1 Contract

## Scope

Safe Purge applies only to immutable historical `market_bars` Raw and Curated
Parquet snapshots. A request must name the configured source, one or more
exact symbols, an inclusive date range, interval, requested session,
adjustment, and source schema version. There is no wildcard scope, arbitrary
path target, Raw-only operation, Curated-only operation, permanent deletion,
or cascade into another dataset kind.

## Physical Lifecycle Unit

Safe Purge supports two fail-closed discovery modes. If an ingestion run has
one or more rows in `market_bar_snapshot_pairs`, those rows are authoritative:
each row binds one independently purgeable per-symbol Raw+Curated pair. The
plan seals the run metadata and the complete registry row. It does not use an
`ingestion_runs` compatibility pointer as a substitute for registered pair
discovery. Selecting one exact registered symbol from a multi-symbol run is
therefore permitted when its two files contain only that exact scope.

If a run has zero registry rows, the run is legacy. Its complete
`ingestion_runs.raw_file` and `curated_file` pair remains one lifecycle unit.
Planning inspects the files' actual columns and values and seals their relative
paths, SHA-256 hashes, byte sizes, row counts, symbols, dates, request key, and
run ID. Partial logical scope in a legacy co-located file remains `REFUSED`
with `COLOCATED_SYMBOLS` or `COLOCATED_DATA`.

Execution re-resolves and compares every sealed run row and, in registered
mode, the exact `(run_id, symbol)` registry row under the lifecycle lock.
Deletion or any path, status, metadata, registry, or file-fact drift refuses
mutation. Matching active Parquet without an authoritative binding is
`UNREGISTERED_SNAPSHOT`. A `FAILED` run with neither physical path nor pair
row remains evidence but is not a target. A one-sided pair is always refused.
Immutable Parquet files are never split or rewritten. The complete physical
model is defined by
[`market_bar_physical_snapshots_v1.md`](market_bar_physical_snapshots_v1.md).

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

Existing `market-vault-safe-purge-plan-v2` targets without a binding mode keep
their legacy meaning. New registered targets use an additive
`REGISTERED_PER_SYMBOL` binding that seals the complete registry row as well as
run metadata; new legacy targets may identify `LEGACY_INGESTION_RUN`
explicitly. This does not bump the plan version. Unknown modes and incomplete
registered bindings are refused, so previously sealed legacy plans are not
reinterpreted as registered plans.

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

Ingestion runs, `market_bar_snapshot_pairs`, collection manifests, and quality
reports remain intact. Registry paths remain historical collection provenance
and are not rewritten to quarantine paths. Interrupted or partially
rolled-back work never becomes `SUCCESS`; an exact completed retry is
idempotent.

`collect_history`, the complete `collect_history_backfill` operation, purge
planning, and purge execution share an exclusive cross-process directory lock
under `data/.lifecycle/`. Backfill holds one reservation from local planning
through every child write and calls the locked collector core, so purge cannot
run between children. A stale lock is not
automatically reclaimed. Read-only queries do not take this lock; during a
short lifecycle transition they may fail or retry, but they must not infer
missing data as a successful purge. Views are refreshed after movement or
rollback, and quarantined files are outside every active Raw/Curated glob.
