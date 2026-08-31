# Superseded Snapshot Cleanup V1

## Status and Authority

This document is the design-only authorization for a future Safe Purge planning
policy. It does not implement data movement and does not create a new mutation
authority.

The future implementation MUST preserve this execution chain:

```text
StorageCleanupController.execute_purge
  -> ConsoleBackend.execute_purge
  -> MarketVault.purge_execute
  -> purge_execute
```

`src/market_vault/purge.py::purge_execute` remains the only physical mutation
owner. The exact confirmation remains `PURGE <plan_id>`. The implementation
MUST NOT add another destructive executor, permanent-delete API, restore API,
garbage collector, or destructive Catalog replacement path.

## Purpose

Superseded Snapshot Cleanup V1 allows an operator to review and quarantine old
COMPLETE market-bar snapshot pairs only after a different COMPLETE active
snapshot is proven to be the deterministic current winner for the same exact
logical key.

The feature removes eligible old pairs from active Raw and Curated globs. It
does not erase historical evidence and does not permanently delete bytes.

## Cleanup Policies

The future planner supports exactly these policies:

- `EXACT_SCOPE`: existing Safe Purge behavior, unchanged.
- `SUPERSEDED_ONLY`: the policy authorized by this document.

`EXACT_SCOPE` MUST remain the default at every public, backend, controller, and
presentation boundary. Missing policy input MUST mean `EXACT_SCOPE`; it MUST
NOT silently select `SUPERSEDED_ONLY`.

The policy affects planning only. Both policies use the same sealed Review,
plan ID, exact confirmation, execution, lifecycle lock, quarantine, commit,
and evidence publication authority.

## Exact Logical Key

A version group is identified by all of:

```text
source
code
requested_trade_date
interval
requested_session
adjustment
source_schema_version
```

`code` is the exact normalized market-bar symbol/code used by the existing
Catalog completion authority. Grouping by only code and date is forbidden.
Different source, schema version, interval, requested session, or adjustment
values MUST form different groups.

## COMPLETE Eligibility

Only snapshots satisfying the current Catalog completion contract may
participate. Eligibility MUST be equivalent to the predicate used by
`Catalog.latest_complete_market_bar_snapshots()` and MUST retain all existing
requirements, including:

- terminal run status is `SUCCESS` or eligible `PARTIAL`;
- no `FAIL` quality result applies;
- request metadata exactly matches the physical snapshot;
- ingestion-run authority is valid;
- registered-per-symbol authority is valid where applicable;
- physical and Curated-file bindings are valid.

The future implementation MAY add a narrow read-only enumeration method for
all complete versions, but that method MUST share the same eligibility
predicate. It MUST NOT create a second definition of COMPLETE.

Failed, running, quality-failed, orphaned, metadata-mismatched, unregistered,
or unverifiable snapshots are evidence, not automatically disposable old data.
They MUST NOT be selected by `SUPERSEDED_ONLY`.

## Deterministic Retained Winner

For every exact logical key with at least one COMPLETE snapshot, the planner
MUST retain exactly one winner. It MUST use the same ordering as
`Catalog.latest_complete_market_bar_snapshots()`:

1. `snapshot_ingested_at DESC NULLS LAST`
2. `run_finished_at DESC NULLS LAST`
3. `ingestion_run_id DESC`
4. `snapshot_file DESC`

The first row under that exact ordering is the retained winner. No second
latest algorithm, wall-clock shortcut, filename-only rule, or run-ID-only rule
is permitted.

```text
RETAINED_WINNER_COUNT_PER_KEY = 1
```

One COMPLETE version produces zero targets. With three COMPLETE versions, the
ranked winner is retained and the other two may be candidates.

## Superseded Target Rule

A snapshot is a `SUPERSEDED_ONLY` candidate only when all of the following are
true:

1. the candidate is COMPLETE;
2. another COMPLETE snapshot exists for the same exact logical key;
3. that other snapshot is the deterministic retained winner;
4. the candidate is not the retained winner;
5. the candidate's complete physical lifecycle unit can be proven safe under
   the binding-mode rules below.

The planner MUST NOT target the latest winner even when the operator's logical
scope includes it.

## Registered Per-Symbol Units

For a run with `snapshot_binding_mode = REGISTERED_PER_SYMBOL`, each exact
`(run_id, symbol)` registry row binds one Raw plus Curated lifecycle unit.

The planner MAY target that exact pair independently from sibling symbols in
the same logical run only when:

- the registered symbol snapshot is independently COMPLETE;
- its exact logical key has a different COMPLETE retained winner;
- every registry and physical fact verifies;
- no unregistered matching active Parquet intersects the scope.

The plan MUST seal the complete `market_bar_snapshot_pairs` row. Execution MUST
re-query and byte/semantically compare every field under
`MarketBarLifecycleLock`. Sibling symbols are never implied targets.

## Legacy Multi-Symbol Units

A legacy Raw plus Curated pair remains indivisible. It MUST NOT be rewritten,
split, compacted, or partially extracted.

A legacy pair containing multiple symbols may be targeted only if every
physically contained symbol has a different newer COMPLETE retained winner for
that symbol's exact logical key. Each symbol needs an independent proof.

If one contained symbol still relies on the legacy pair, or if any proof is
missing, the entire pair MUST be retained. The plan MUST expose a dedicated
refusal such as `LEGACY_PAIR_NOT_FULLY_SUPERSEDED`. Presence of that refusal
makes the complete sealed plan non-executable; the planner MUST NOT silently
skip the ambiguous pair and present a partially reviewed operation as safe.

## Sealed Retention Evidence

A `SUPERSEDED_ONLY` plan MUST seal both:

- `targets_to_quarantine`;
- `retained_current_snapshots`.

For each target-to-winner relationship, the evidence MUST contain:

- the complete exact logical key;
- target run ID and binding mode;
- target Raw and Curated relative paths, SHA-256, byte size, row/symbol/date
  facts, registry or legacy binding, and ranking facts;
- retained run ID and binding mode;
- retained Raw and Curated relative paths, SHA-256, byte size, row/symbol/date
  facts, registry or legacy binding, and ranking facts;
- the exact ordered values proving `OLD_RUN -> RETAINED_RUN`.

A shared retained winner MAY be referenced by multiple older targets, but its
canonical identity MUST be sealed once and every target reference MUST resolve
to it exactly.

The summary MUST include:

```text
logical_key_count
retained_snapshot_count
superseded_snapshot_count
raw_file_count
raw_bytes
curated_file_count
curated_bytes
total_quarantine_bytes
```

The review table MUST show at least:

```text
code
requested_trade_date
interval
requested_session
adjustment
source_schema_version
superseded_run_id
retained_run_id
superseded_ingested_at
retained_ingested_at
raw_bytes
curated_bytes
```

## Plan Compatibility and Versioning

Existing sealed `market-vault-safe-purge-plan-v2` plans remain readable and
executable under their original `EXACT_SCOPE` semantics. A historical v2 plan
without `cleanup_policy` MUST be interpreted as `EXACT_SCOPE`. It MUST never be
upgraded or reinterpreted as `SUPERSEDED_ONLY`.

Future `EXACT_SCOPE` planning MUST continue to produce the existing v2 evidence
without changing its semantics. Future `SUPERSEDED_ONLY` planning MUST use
`market-vault-safe-purge-plan-v3`, with explicit `cleanup_policy`, target
evidence, retained-winner evidence, summary, and target-to-winner mappings.
The corresponding precommit and result evidence MUST retain the policy and
retention proof through an additive v3 schema.

`purge_execute` may support both versions, but it MUST reject:

- v2 evidence claiming `SUPERSEDED_ONLY`;
- v3 evidence with missing or unknown policy;
- v3 `SUPERSEDED_ONLY` evidence missing any retained-winner proof;
- any attempt to downgrade v3 evidence to v2 semantics.

This compatibility rule prevents old evidence from being stranded while
keeping the new destructive intent explicit and integrity-bound.

## Execution-Time Revalidation

Execution MUST acquire `MarketBarLifecycleLock` and revalidate all evidence
before moving any file. For `SUPERSEDED_ONLY`, it MUST prove:

- the plan ID, canonical content hash, policy, scope, targets, retained winners,
  and plan path are unchanged;
- every target physical identity and run/registry binding is unchanged;
- every retained winner physical identity and run/registry binding is
  unchanged;
- every retained winner remains COMPLETE and active;
- re-enumeration with the current COMPLETE predicate and exact ranking still
  selects the sealed winner;
- no newly completed version changed the winner;
- no matching unregistered snapshot appeared;
- no matching `RUNNING` writer exists;
- every legacy target remains fully superseded for all physically contained
  symbols;
- moving the targets leaves at least one COMPLETE active snapshot for every
  affected exact logical key.

Any mismatch is authority drift and MUST fail before mutation. Execution MUST
NOT silently adopt a different winner and MUST require a newly reviewed plan.

## No Latest-Snapshot Loss

Before the Catalog `SUCCESS` commit, execution MUST prove for every affected
logical key:

```text
complete_active_snapshot_count >= 1
active_winner == sealed_retained_winner
```

The sealed retained Raw and Curated pair MUST remain active. If the proof fails
after some target movement but before commit, existing precommit rollback rules
apply. The attempt MUST NOT become `SUCCESS`.

## Quarantine and Evidence Retention

Targets use the existing destination:

```text
quarantine/purge_id=<plan_id>/<original data-root-relative path>
```

Raw and Curated always move as an exact pair. Original relative paths and bytes
are preserved. There is no permanent deletion, quarantine garbage collection,
or restore operation in this feature.

The following evidence remains retained and unchanged:

- `ingestion_runs`;
- `market_bar_snapshot_pairs`;
- `quality_results`;
- collection manifests and quality reports;
- immutable purge plan, precommit, and result evidence.

Registry and run paths remain historical provenance even after quarantine.

Verified Canonical builds, Dataset artifacts, and Dataset Catalog snapshots
remain retained non-blocking dependents under
`RETAIN_VERIFIED_DERIVED_ARTIFACTS_V1`. No cascade is permitted.

## Storage and Cleanup UI

The existing Storage & Cleanup page remains the only destructive workspace.
It may add one policy selector with these values:

| Policy | English | Simplified Chinese |
| --- | --- | --- |
| `EXACT_SCOPE` | Exact Scope | 精确范围清理 |
| `SUPERSEDED_ONLY` | Superseded Only | 仅清理旧快照 |

The default MUST be `EXACT_SCOPE`. The existing Review, plan ID, status,
confirmation, and Execute Safe Purge flow remains unchanged.

`cleanup_policy` is part of the reviewed scope fingerprint. Changing it or any
of source, symbols, start date, end date, interval, session, adjustment, or
schema MUST invalidate Review, clear confirmation, and disable execution until
a new Review succeeds.

The UI MUST make retained winners visible. Navigation or language switching
must not create a second executor or bypass the reviewed plan state.

## Required Future Test Matrix

The implementation PR MUST use disposable data roots and include at least:

| Case | Expected result |
| --- | --- |
| A. One complete snapshot | zero targets |
| B. Two complete snapshots, same exact key | old target one; latest retained one |
| C. Three complete snapshots | old targets two; latest retained one |
| D. Different session | separate groups |
| E. Different adjustment | separate groups |
| F. Different interval | separate groups |
| G. Different schema version | separate groups |
| H. Failed newer run | does not supersede older complete run |
| I. Quality-FAIL newer run | does not supersede older complete run |
| J. Eligible symbol in PARTIAL run | may be complete only through existing predicate |
| K. Matching unregistered snapshot | refused |
| L. Matching RUNNING run | refused |
| M. Retained winner disappears after Review | execution refused before mutation |
| N. New complete snapshot appears after Review | stale plan refused |
| O. Target SHA or size drift | execution refused |
| P. Retained-winner SHA or size drift | execution refused |
| Q. Legacy pair with all symbols superseded | whole pair may be targeted |
| R. Legacy pair with one unsuperseded symbol | plan refused; pair retained |
| S. Successful execution | sealed latest winner remains active and queryable |
| T. Quarantine contents | only sealed superseded target pairs |
| U. Existing `EXACT_SCOPE` | behavior unchanged |
| V. Historical sealed v2 plan | compatibility unchanged; missing policy means `EXACT_SCOPE` |

Tests MUST also prove exact summary counts and bytes, policy-driven Review
invalidation, bad confirmation refusal, retained derived-artifact verification,
rollback, retry, reparse safety, and absence of a second destructive surface.

## Implementation Acceptance Gate

The later implementation PR MUST start from a base containing the unchanged
approved machine contract. It MUST:

1. modify no destructive signal or occurrence count unless a separate prior
   design-only contract approves that exact transition;
2. keep `purge_execute` as the sole movement authority;
3. run repository and exact-base pull-request destructive gates;
4. keep the destructive inventory fully classified;
5. run all new tests with temporary data roots only;
6. run the authoritative classifier and the required CI tier without manual
   downgrade;
7. perform no real OpenD collection or production-data mutation.

If implementation requires a new destructive primitive, executor, contract,
or incompatible evidence strategy, it MUST stop for a separate design review.

## Non-Goals

This design does not authorize:

- permanent deletion;
- restore;
- quarantine expiry or garbage collection;
- automatic cleanup scheduling;
- legacy Parquet migration, rewrite, split, or compaction;
- per-symbol quality redesign;
- Canonical or Dataset mutation;
- OpenD protocol changes;
- a new CLI/API destructive executor;
- production data movement in this design PR.
