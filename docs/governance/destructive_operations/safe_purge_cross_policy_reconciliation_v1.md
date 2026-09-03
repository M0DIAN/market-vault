# Safe Purge Cross-Policy Reconciliation V1

## Status

This document is an approved design boundary for a future implementation. It
does not itself implement reconciliation, move files, change Catalog schema,
or authorize a production purge. The governing destructive operation remains
`safe_purge_v01`.

## Defect

Successful Safe Purge execution retains `ingestion_runs` and
`market_bar_snapshot_pairs` as historical evidence. Their Raw and Curated
paths remain original collection provenance even after the files move to
`quarantine/purge_id=<plan_id>/...`.

The current `EXACT_SCOPE` planner interprets every matching historical binding
as an active pair and immediately opens its original paths. After a valid
`SUPERSEDED_ONLY` operation quarantines older versions, a later `EXACT_SCOPE`
review can therefore report `UNSAFE_OR_MISSING_TARGET` even though committed
Safe Purge evidence fully explains the absence. Active discovery and
historical provenance are being conflated.

The correction is strict read-only evidence reconciliation. It does not
rewrite historical paths, adopt files by location, or add a mutation owner.

## Non-Goals

This work does not authorize:

- a new destructive executor or result-publication path;
- permanent deletion, restore, quarantine expiry, or garbage collection;
- Catalog path rewriting or persistent lifecycle flags;
- Parquet rewriting, splitting, or row deletion;
- changes to `SUPERSEDED_ONLY` winner selection;
- a new Storage & Cleanup control or QML layout;
- OpenD use, collection, schema migration, or production data testing.

## Historical Authority and Physical Units

Historical run and registry rows remain authoritative provenance. They do not
alone prove that their files are active.

For `REGISTERED_PER_SYMBOL`, one lifecycle unit is the exact `(run_id,
symbol)` registry row and its Raw+Curated pair. No state inferred for one
symbol applies to a sibling symbol in the same run.

For legacy authority, the lifecycle unit is the complete indivisible
Raw+Curated pair. Every physically contained symbol belongs to that same unit
and must resolve through the same prior purge operation. Reconciliation never
synthesizes per-symbol state for a legacy pair.

Every logical/request comparison is exact across:

```text
source
code
requested_trade_date
interval
requested_session
adjustment
source_schema_version
```

Evidence from another session, schema, source, symbol, date, interval, or
adjustment cannot explain a missing unit.

## Derived Lifecycle States

The following states are derived during planning and v4 execution
revalidation. They are not stored in a new table or column.

### ACTIVE

`ACTIVE` requires:

- valid historical run authority and, when registered, the exact registry
  binding;
- both expected Raw and Curated files as safe regular files in their active
  roots;
- exact relative path, byte size, SHA-256, row count, symbols, dates, request
  facts, run ID, source, and source schema facts;
- no one-sided physical state; and
- no committed purge authority claiming the same original unit.

### VERIFIED_QUARANTINED

`VERIFIED_QUARANTINED` requires both active paths to be absent and exactly one
complete, non-conflicting committed-success authority chain:

1. the exact historical run/registry binding is valid;
2. the prior immutable plan occupies its canonical evidence path, has
   canonical bytes, and hashes to the Catalog `plan_hash`;
3. the prior plan is a supported v2, v3, or, after implementation, v4 schema;
4. `purge_operations.state` is exactly `SUCCESS`;
5. the Catalog plan, precommit, expected result paths, plan hash, and result
   hash are path-safe and mutually consistent;
6. the immutable precommit has canonical bytes and a valid precommit hash;
7. its plan ID and plan hash equal the Catalog row and prior plan;
8. its embedded terminal result is canonical and validates against the
   Catalog result hash;
9. that terminal result contains exactly one Raw and one Curated moved entry
   matching the historical lifecycle unit and prior plan target;
10. each quarantine destination is exactly
    `quarantine/purge_id=<prior-plan-id>/<original-relative-path>`;
11. both quarantine files are safe regular files and match sealed SHA-256,
    byte size, and physical facts; and
12. no active claim or second successful purge authority conflicts with the
    unit.

A quarantine pathname alone is not authority. A Catalog `SUCCESS` row alone
is not authority. Arbitrary directory search is not an authority source.

### MISSING_UNEXPLAINED

`MISSING_UNEXPLAINED` means the historical binding is valid, at least one
active side is absent, and no complete committed-success chain explains the
absence. It always refuses `EXACT_SCOPE`.

### AMBIGUOUS

`AMBIGUOUS` includes active bytes plus a successful quarantine claim, more
than one successful operation claiming the original unit, or Raw and Curated
being claimed by different operations. It always refuses.

### INVALID

`INVALID` includes malformed or unsupported evidence, unsafe paths, a
one-sided quarantine pair, noncanonical JSON, hash or size drift, physical-fact
drift, request-identity mismatch, or inconsistent run/registry authority. It
always refuses.

## Committed Success and Absent Final Results

Catalog `SUCCESS` is the existing durable commit point. The immutable
precommit contains the complete proposed terminal result and binds its hash.

If the final result file exists, the reconciliation reader must verify its
canonical bytes, result hash, expected path, and exact equality with the
precommitted terminal result. A conflict is `INVALID`.

If the expected final result is absent, Catalog `SUCCESS`, a valid canonical
precommit, its valid embedded terminal result, the matching Catalog result
hash, and exact quarantine identities are sufficient for read-only lifecycle
reconciliation. The reader must not call the existing helper that stages or
publishes the result. Normal idempotent `purge_execute` retry remains the sole
publication-recovery path.

Final-result presence is not part of v4 destructive authority. Later
publication of the exact precommitted bytes and hash is not drift. A newly
present conflicting result is drift and refuses execution.

## Additive Plan Version

Plan-version meanings remain:

```text
market-vault-safe-purge-plan-v2 = historical or ordinary EXACT_SCOPE
market-vault-safe-purge-plan-v3 = SUPERSEDED_ONLY
market-vault-safe-purge-plan-v4 = reconciled EXACT_SCOPE
```

An ordinary `EXACT_SCOPE` plan with no material prior-quarantine exclusion may
continue to emit v2. If safe planning depends on excluding at least one
`VERIFIED_QUARANTINED` historical unit, it must emit v4. V2 and v3 are never
repurposed.

V4 continues to use the existing EXACT_SCOPE precommit and result versions.
Those records bind the complete v4 plan hash, and execution still moves only
ordinary exact Raw+Curated targets. No precommit or result version bump is
required.

## Canonical V4 Schema

Canonical JSON uses the existing Safe Purge encoding: UTF-8 JSON with keys
sorted, separators `,` and `:`, ASCII escaping enabled, and one trailing
newline. Unknown or missing keys fail closed.

The exact v4 top-level key set is the v2 key set plus
`cleanup_policy` and `reconciled_quarantined_units`:

```text
plan_version
plan_id
content_hash
status
scope
targets
summary
dependency_state
retained_evidence
refusal_reasons
quarantine_root_template
cleanup_policy
reconciled_quarantined_units
```

Required constants are:

```text
plan_version = market-vault-safe-purge-plan-v4
cleanup_policy = EXACT_SCOPE
```

`targets` preserves the exact existing v2 target schema. Every v4
`reconciled_quarantined_units` entry has exactly these keys:

```text
lifecycle_state
binding_mode
ingestion_run_id
symbols
logical_keys
run_binding
snapshot_pair_binding
raw
curated
prior_purge_authority
```

Rules for those fields are:

- `lifecycle_state` is exactly `VERIFIED_QUARANTINED`;
- `binding_mode` is `REGISTERED_PER_SYMBOL` or `LEGACY_INGESTION_RUN`;
- `symbols` is a sorted unique list, exactly one symbol for registered mode
  and the complete physical symbol set for legacy mode;
- `logical_keys` is sorted by canonical JSON bytes and contains the complete
  request key for every physical symbol;
- `run_binding` is the same complete binding structure used by current Safe
  Purge target evidence;
- `snapshot_pair_binding` is the exact registry row in registered mode and
  JSON `null` in legacy mode; and
- entries are sorted by Curated original relative path and ingestion run ID.

Both `raw` and `curated` have exactly:

```text
identity
quarantine_relative_path
```

`identity` is the prior plan target identity and exact moved-file identity. It
has the existing keys:

```text
layer
relative_path
byte_size
sha256
facts
```

`facts` has exactly:

```text
row_count
symbols
dates
intervals
requested_sessions
adjustments
ingestion_run_ids
sources
source_schema_versions
```

The terminal result moved entry must equal `identity` plus the same
`quarantine_relative_path`; v4 does not duplicate a second copy of that
identity.

`prior_purge_authority` has exactly:

```text
plan_id
plan_version
cleanup_policy
plan_hash
plan_evidence_relative_path
precommit_version
precommit_evidence_relative_path
precommit_hash
terminal_result_version
terminal_result_expected_relative_path
terminal_result_hash
```

Evidence paths are normalized paths relative to `manifest_dir`, not arbitrary
or installation-specific paths. At revalidation, each must resolve to the
exact canonical location recorded by the Catalog row and remain beneath the
expected plan-specific evidence directory. `cleanup_policy` is derived as
`EXACT_SCOPE` for historical v2 and is explicit for v3/v4.

The v4 schema intentionally contains no `final_result_present` field. It also
does not duplicate the Catalog state: revalidation requires the live Catalog
row to remain exactly `SUCCESS`.

## Plan-Time Algorithm

Under the existing planning lifecycle lock:

1. enumerate matching historical run and registry authority without assuming
   original paths remain active;
2. construct exact physical lifecycle units, preserving registered and legacy
   boundaries;
3. enumerate matching active Raw and Curated files using existing path and
   unregistered-file checks;
4. fully validate units with both active files and classify them `ACTIVE`,
   refusing any conflicting successful quarantine claim;
5. for a unit absent from active roots, enumerate Catalog `SUCCESS` operations
   through a narrow read-only query and validate complete candidate chains;
6. classify exactly one valid chain as `VERIFIED_QUARANTINED`, no chain as
   `MISSING_UNEXPLAINED`, conflicting chains as `AMBIGUOUS`, and malformed or
   drifted evidence as `INVALID`;
7. refuse the plan for every missing, ambiguous, or invalid unit;
8. build destructive targets only from `ACTIVE` units;
9. if at least one verified prior quarantine materially excludes a historical
   unit, seal all such units in v4; otherwise retain ordinary v2 emission; and
10. preserve current unregistered, RUNNING, one-sided, co-located, path-safety,
    and exact-scope checks.

For the canonical three-version scenario, OLD_A and OLD_B are sealed
non-target `VERIFIED_QUARANTINED` entries and CURRENT_C is the sole target.
The plan is `PLANNED` with one active target. The destructive review table may
remain target-only; the sealed plan and summary provide reconciliation audit
evidence without a new QML layout.

If no active target remains and every matching historical unit is verified
quarantined, planning returns `REFUSED`, `NO_MATCHING_DATA`, and zero targets.
It does not create a successful no-op execution.

## Execution-Time Revalidation

Before the first new movement under a v4 plan, `purge_execute` holds
`MarketBarLifecycleLock` and must:

1. reload the exact canonical v4 plan and verify plan ID, hash, policy, scope,
   target list, and reconciliation list;
2. re-resolve every target's run/registry binding and active Raw/Curated
   identity through existing EXACT_SCOPE checks;
3. re-resolve each historical binding in
   `reconciled_quarantined_units`;
4. re-read the exact sealed prior Catalog row, plan, precommit, embedded
   terminal result, and any present final result without publishing;
5. verify the same prior plan/precommit/result versions, paths, and hashes;
6. verify both quarantine files and exact moved identities;
7. prove no second successful operation or active file now conflicts;
8. refuse any new matching active, unregistered, one-sided, or RUNNING
   authority; and
9. prove that every unit still has its sealed lifecycle classification before
   delegating movement to the existing implementation.

Any failure occurs before the first new file movement. Existing movement,
rollback, Catalog commit, view refresh, and result publication remain owned by
`purge_execute`.

## Refusal Taxonomy

Reconciliation failures use specific stable codes:

- `QUARANTINE_EVIDENCE_MISSING`: missing active bytes have no complete
  committed-success chain;
- `QUARANTINE_EVIDENCE_HASH_MISMATCH`: canonical plan, precommit, terminal
  result, Catalog hash, or quarantine SHA/size does not match;
- `QUARANTINE_PAIR_INCOMPLETE`: only one Raw/Curated side is active or valid in
  quarantine;
- `PURGE_RESULT_AUTHORITY_MISMATCH`: prior scope, target, moved entry,
  destination, run/registry binding, or supported evidence version does not
  prove the historical unit; and
- `CONFLICTING_PURGE_AUTHORITY`: active and quarantine claims conflict,
  multiple committed successes claim the unit, or Raw and Curated resolve to
  different operations.

Existing more specific path, binding, mode, co-location, unregistered, and
RUNNING refusal codes remain applicable. Errors are not collapsed into a
generic missing-file message after the evidence layer identifies a precise
cause.

## Compatibility

- Historical v2 plans retain implicit `EXACT_SCOPE`, their canonical schema,
  loader, and execution rules.
- Historical v3 plans retain explicit `SUPERSEDED_ONLY`, retained-winner
  evidence, loader, and execution rules.
- V4 is accepted only for explicit `EXACT_SCOPE` with canonical reconciliation
  evidence.
- A successful v2, v3, or v4 operation may explain a future missing active
  unit only through the same complete committed-success chain.
- Unknown future plan, precommit, or result schemas fail closed until a later
  governance authorization explicitly supports them.
- No new Catalog table or column is required. A future read-only method may
  enumerate successful purge rows without storing derived lifecycle state.

## Required Implementation Tests

The implementation PR must use disposable roots and cover at least:

A. Three complete versions; `SUPERSEDED_ONLY` quarantines two; v4
   `EXACT_SCOPE` review targets only the remaining active version.
B. Executing A quarantines only that active pair successfully.
C. Missing active bytes without prior purge evidence refuse.
D. Missing quarantine Raw refuses.
E. Missing quarantine Curated refuses.
F. Quarantine SHA or byte-size drift refuses.
G. Prior result, plan, or precommit tampering refuses.
H. Catalog plan/result hash mismatch refuses.
I. `PLANNED`, `REFUSED`, `EXECUTING`, or `FAILED` prior operations do not
   establish authority.
J. Catalog `SUCCESS` with valid precommit and absent final result reconciles
   read-only without publishing; later exact publication remains valid.
K. Registered sibling symbols reconcile independently.
L. Legacy multi-symbol files reconcile only as one whole physical pair through
   one prior authority.
M. Different requested sessions cannot cross-reconcile.
N. Different source schema versions cannot cross-reconcile; source, symbol,
   date, interval, and adjustment isolation are also exact.
O. Quarantine or prior-evidence drift after Review refuses v4 execution before
   movement.
P. A new matching active, unregistered, or RUNNING unit after Review refuses.
Q. Historical v2 EXACT_SCOPE execution remains unchanged.
R. Historical v3 SUPERSEDED_ONLY execution remains unchanged.
S. Repeated review after all units are successfully quarantined is stably
   `REFUSED` with `NO_MATCHING_DATA` and zero targets.
T. Active plus successful quarantine authority refuses as ambiguous.
U. Multiple successful operations claiming one original unit refuse.
V. Raw and Curated claimed by different operations refuse.
W. Unsafe evidence paths, unknown evidence schemas, one-sided active state,
   and conflicting final result bytes refuse without publication or movement.

Repository and pull-request destructive gates must continue to report the
existing three contracts, sixteen exemptions, and thirty-eight surfaces. The
implementation must not rename functions to evade detection or add another
destructive signal, occurrence, contract, or public executor.

## Implementation Boundary

The future implementation is limited to:

- read-only successful-purge enumeration in the Catalog boundary;
- lifecycle interpretation, v4 schema parsing, and evidence validation in
  Safe Purge;
- v4 EXACT_SCOPE planning and under-lock revalidation;
- focused v2/v3/v4 and cross-policy regression tests; and
- directly affected Safe Purge contract documentation.

Physical mutation remains exclusively
`src/market_vault/purge.py::purge_execute`. Production validation, OpenD,
collection, schema cutover, restore, and permanent deletion remain outside the
authorized work.
