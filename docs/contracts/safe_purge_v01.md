# Safe Purge v0.1 Contract

## Scope

Safe Purge applies only to immutable historical `market_bars` Raw and Curated
Parquet snapshots. A request must name the configured source, one or more
exact symbols, an inclusive date range, interval, requested session,
adjustment, and source schema version. There is no wildcard scope, arbitrary
path target, Raw-only operation, Curated-only operation, permanent deletion,
or cascade into another dataset kind.

## Physical Lifecycle Unit

Safe Purge supports two fail-closed discovery modes using the nullable
`ingestion_runs.snapshot_binding_mode` as the durable protocol discriminator.
Every P0-3 run stores `REGISTERED_PER_SYMBOL`, even with zero successful pairs.
For that mode, registry rows are authoritative and each row binds one
independently purgeable per-symbol Raw+Curated pair. Zero rows means no
authoritative pair, never permission to use compatibility pointers.

Legacy classification requires both null mode and zero registry rows. For a
proven legacy run, its complete `ingestion_runs.raw_file` and `curated_file`
pair remains one lifecycle unit. Null mode with nonzero rows is inconsistent
and refused. Any unknown non-null mode fails closed.

Planning inspects the files' actual columns and values and seals their relative
paths, SHA-256 hashes, byte sizes, row counts, symbols, dates, request key, and
run ID. Partial logical scope in a legacy co-located file remains `REFUSED`
with `COLOCATED_SYMBOLS` or `COLOCATED_DATA`. Zero registry rows is a necessary
legacy condition, not permission to adopt unregistered files: intersecting
active files without an authoritative legacy pointer or registry binding remain
`UNREGISTERED_SNAPSHOT` and refuse the plan.

Execution re-resolves and compares every sealed run row and, in registered
mode, the exact `(run_id, symbol)` registry row under the lifecycle lock.
Registered targets seal and revalidate exact mode. Explicit legacy targets and
historical v2 targets without `binding_mode` revalidate both null run mode and
zero registry rows. Deletion or any path, mode, status, metadata, registry, or
file-fact drift refuses mutation. Matching active Parquet without an
authoritative binding is `UNREGISTERED_SNAPSHOT`. A `FAILED` run with neither
physical path nor pair row remains evidence but is not a target. A one-sided
pair is always refused.
Immutable Parquet files are never split or rewritten. The complete physical
model is defined by
[`market_bar_physical_snapshots_v1.md`](market_bar_physical_snapshots_v1.md).

## Cross-Policy Lifecycle Reconciliation

Historical run and `market_bar_snapshot_pairs` paths remain original
collection provenance after a successful purge. They are never rewritten to
quarantine paths. A future planner may therefore derive, without writing
Catalog state, one of five lifecycle interpretations for each authoritative
physical unit:

- `ACTIVE`: the exact bound Raw and Curated files both exist in the active
  roots, their identities and physical facts verify, and no successful purge
  authority conflicts with active ownership;
- `VERIFIED_QUARANTINED`: both active files are absent and one complete,
  non-conflicting committed-success chain proves that exact Raw and Curated
  pair now exists at the quarantine destinations derived from the same purge
  plan ID;
- `MISSING_UNEXPLAINED`: historical binding exists, but missing active bytes
  have no valid committed-success explanation;
- `AMBIGUOUS`: active and quarantine claims conflict, multiple successful
  operations claim the same original unit, or Raw and Curated are attributed
  to different operations; or
- `INVALID`: binding, canonical evidence, path safety, hash, size, physical
  facts, request identity, or pair completeness cannot be proved.

`VERIFIED_QUARANTINED` requires the exact historical run/registry binding, a
canonical immutable prior plan and matching plan hash, Catalog
`purge_operations.state == SUCCESS`, a canonical immutable precommit whose
plan identity and hash match, an embedded canonical terminal result matching
the Catalog result hash, exact Raw and Curated moved entries, same-plan
quarantine destinations, and both quarantine files matching sealed SHA-256,
byte size, and physical facts. A quarantine pathname alone and a Catalog
`SUCCESS` row alone are never authority. `PLANNED`, `REFUSED`, `EXECUTING`, and
`FAILED` operations, non-terminal precommit or staging residue, rolled-back
movement, and partial quarantine are not successful quarantine authority.

If a final terminal result exists, it must be canonical, match the Catalog
result hash, and equal the terminal result sealed by the precommit. If it is
absent after Catalog `SUCCESS`, the valid precommit, its embedded terminal
result, the Catalog-bound result hash, and verified quarantine identities are
sufficient for read-only reconciliation. The reconciliation reader must not
publish the absent result; normal idempotent `purge_execute` retry remains the
only result-publication recovery path. Later publication of those exact sealed
bytes is not lifecycle drift.

Registered reconciliation is limited to the exact `(run_id, symbol)` pair and
does not confer state on sibling symbols. A legacy multi-symbol pair remains
indivisible: every contained symbol resolves through the same physical pair
and the same prior purge authority. Reconciliation never crosses source,
symbol, requested trade date, interval, requested session, adjustment, or
source schema version.

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
reinterpreted as registered plans. Under the lifecycle lock, execution of every
legacy target MUST re-query the exact run mode and its
`market_bar_snapshot_pairs` rows, proving null mode and zero rows before
mutation. This includes historical v2 targets without `binding_mode`. Any
non-null mode or newly present row is mode/authority drift and refuses
execution before files move.

Plan-version meanings are additive and permanent:

- `market-vault-safe-purge-plan-v2` is historical and ordinary `EXACT_SCOPE`;
- `market-vault-safe-purge-plan-v3` is `SUPERSEDED_ONLY`; and
- `market-vault-safe-purge-plan-v4` is `EXACT_SCOPE` whose reviewed authority
  materially depends on at least one sealed `VERIFIED_QUARANTINED` exclusion.

An ordinary `EXACT_SCOPE` review with no reconciled exclusion may continue to
emit v2. A v4 plan preserves every v2 field, explicitly seals
`cleanup_policy: EXACT_SCOPE`, and adds `reconciled_quarantined_units` with the
exact historical physical unit, prior committed-success authority, moved-file
identity, and quarantine destination needed for execution-time revalidation.
It never retargets an already quarantined unit. `ACTIVE` units remain normal
`EXACT_SCOPE` candidates; `MISSING_UNEXPLAINED`, `AMBIGUOUS`, and `INVALID`
units refuse the plan. If all matching historical units are
`VERIFIED_QUARANTINED`, the plan is `REFUSED` with `NO_MATCHING_DATA` and zero
targets rather than becoming a successful no-op.

Before v4 execution moves any new target, `purge_execute` must revalidate under
`MarketBarLifecycleLock` the canonical plan and scope, every active target,
every sealed prior plan/precommit/result binding, every quarantine Raw and
Curated identity, historical run/registry bindings, absence of conflicting
successful authority, and absence of new matching active or unregistered
units. Any changed lifecycle classification refuses before the first new file
movement. A successful v4 operation may later serve as prior authority through
the same committed-success chain. Unknown plan, precommit, or result schemas
fail closed.

V4 continues to use the existing `EXACT_SCOPE` precommit and result schemas.
Those records bind the complete v4 plan hash and the ordinary newly moved
Raw/Curated targets, so no precommit or result version change is authorized.
No Catalog lifecycle column or table is introduced.

For new-format collection runs, `successful_symbols` and compatibility pointers
are authoritative only after exact pair verification and registry insertion.
Their manifests and terminal `ingestion_runs` rows always carry
`snapshot_binding_mode: REGISTERED_PER_SYMBOL`, including zero-success runs.
Files left behind by a failed insertion are unregistered evidence: they do not
make a symbol successful, do not populate compatibility pointers, and are not
adopted as a legacy pair. If one symbol is registered and another symbol's
insertion fails, registered mode remains authoritative for the run and the
unregistered symbol's files cause lifecycle refusal.

A single-symbol registered run may retain compatibility pointers. If its pair
row later disappears, the durable registered mode prevents legacy fallback and
the files are refused as unregistered evidence.

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
