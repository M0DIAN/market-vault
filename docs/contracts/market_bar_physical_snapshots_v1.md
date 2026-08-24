# Market-Bar Physical Snapshots v1

## 1. Status and Scope

This contract defines the physical storage model for newly collected
`market_bars` snapshots. It is a design contract for a later implementation
PR. It does not alter the current implementation by itself.

An ingestion run is the logical attempt represented by one `run_id`. A run MAY
request multiple symbols through one public collection operation and one
collector context. The writer MUST NOT create a separate logical run merely to
obtain physical isolation. Each successfully collected symbol is instead one
independent immutable physical lifecycle unit consisting of exactly one Raw
Parquet file and exactly one Curated Parquet file.

## 2. Physical Pair Contract

For every successful normalized symbol in a new run, the writer MUST:

- write exactly one Raw file and one Curated file;
- place exactly one normalized symbol in each file;
- place the same symbol and `ingestion_run_id` in both files;
- place the exact requested trade date, interval, requested session, and
  adjustment in both files;
- place the exact source and source schema version in the Curated file;
- preserve equal physical scope and row count across the pair; and
- register the pair only after both immutable files exist and their facts have
  been verified.

A failed symbol MUST NOT produce or register a successful pair. Recollection,
including forced collection, MUST use a new `run_id`, create another pair, and
MUST NOT overwrite an earlier file.

### New-format publication invariant

For every P0-3 run, a symbol MUST NOT enter `RunManifest.successful_symbols`
until all of the following have succeeded in order:

1. Raw publication;
2. Curated publication;
3. verification that Raw and Curated facts form one exact pair; and
4. insertion, or exact-idempotent validation, of the corresponding
   `market_bar_snapshot_pairs` row.

For a terminal new-format run, the normalized set in `successful_symbols`
MUST equal the normalized symbol set represented by its verified registered
`snapshot_pairs`. `RunManifest.snapshot_pairs` MUST contain exactly those
registered successful pairs and no unregistered physical evidence.

The compatibility pointers MUST be derived only from that registered list:

- zero registered pairs: `raw_file` and `curated_file` are both null;
- one registered pair: both point to that exact registered pair;
- more than one registered pair: both are null.

If registry insertion fails after both files were written, the symbol MUST NOT
be published as successful, the failure MUST be represented in the run's
failed-symbol evidence, and those paths MUST NOT populate the compatibility
pointers. The files remain immutable unregistered physical evidence. They MAY
be reported by inventory, but completion and lifecycle operations MUST refuse
to infer a successful or legacy pair from them.

The existing hierarchy is unchanged:

```text
<data_root>/<raw|curated>/
  source=<source>/
  dataset=market_bars/
  interval=<interval>/
  requested_trade_date=<YYYY-MM-DD>/
  batch-<batch-key>-<run-id>.parquet
```

There MUST NOT be a Hive `symbol=` or `code=` partition. For one normalized
symbol `S`, the filename algorithm is frozen as follows:

```text
payload = "|".join(sorted([S]) + [interval.lower(),
                                  session.upper(),
                                  adjustment.upper()])
batch_key = sha256(payload encoded as UTF-8).hexdigest()[0:16]
filename = "batch-" + batch_key + "-" + run_id + ".parquet"
```

The existing safe partition-value validation applies to `run_id`. No writer
MAY split or rewrite an immutable file after publication.

## 3. Physical-Pair Registry

Catalog initialization MUST add the following backward-compatible table
without destructively migrating `ingestion_runs`:

```sql
CREATE TABLE IF NOT EXISTS market_bar_snapshot_pairs (
    run_id                 VARCHAR NOT NULL,
    symbol                 VARCHAR NOT NULL,
    requested_trade_date   DATE NOT NULL,
    interval               VARCHAR NOT NULL,
    session                VARCHAR NOT NULL,
    adjustment             VARCHAR NOT NULL,
    source                 VARCHAR NOT NULL,
    source_schema_version  VARCHAR NOT NULL,
    raw_file               VARCHAR NOT NULL,
    curated_file           VARCHAR NOT NULL,
    row_count              BIGINT NOT NULL,
    PRIMARY KEY (run_id, symbol)
);
```

`symbol` is stripped and uppercased, `interval` is lowercase, and `session`
and `adjustment` are uppercase. `row_count` is the verified row count shared by
the Raw and Curated files. One row binds exactly one physical pair.
`ingestion_runs` remains authoritative for the run ID, requested/successful/
failed symbols, status, request metadata, configuration hash, and timestamps.

Registration MUST use insert-with-validation semantics. A missing key MAY be
inserted. Re-registering `(run_id, symbol)` is idempotent only when every field
is semantically identical after the contract's normalization. Path strings and
all other non-normalized strings MUST match exactly. A conflicting field MUST
fail. Wildcards, destructive replacement, and overwrite-on-conflict are
forbidden. The registry `session` column means the requested session, not a
normalized bar's intraday `session` label.

## 4. Manifest and Legacy Pointers

`RunManifest` JSON MUST add a top-level `snapshot_pairs` list. Entries MUST be
sorted by `symbol` ascending and each entry MUST have exactly this shape:

```json
{
  "run_id": "<run-id>",
  "symbol": "US.SPY",
  "requested_trade_date": "2026-08-03",
  "interval": "1m",
  "session": "ALL",
  "adjustment": "NONE",
  "source": "moomoo",
  "source_schema_version": "<configured-version>",
  "raw_file": "<same path recorded in the registry>",
  "curated_file": "<same path recorded in the registry>",
  "row_count": 960
}
```

The list contains only verified, registered successful pairs and its symbol set
MUST equal terminal `successful_symbols`. Its path strings MUST equal the
corresponding registry fields. Existing top-level fields remain backward
compatible and are derived only from this list:

- exactly one pair: `raw_file` and `curated_file` point to that pair;
- more than one pair: both fields MUST be null;
- zero pairs: both fields MUST be null.

Run-level `row_count` remains the sum of all registered pair row counts.
Run-level quality attribution is unchanged by this contract.

## 5. Readers and Legacy Archive

Legacy single- and multi-symbol files, including names without a `run_id`,
MUST remain readable and MUST NOT be migrated, split, or rewritten. Recursive
Raw/Curated readers and the public logical `market_bars` view MUST read a mixed
archive of legacy and per-symbol files with unchanged logical semantics.

`completed_market_bar_items`, `latest_completed_market_bar_dates`, inventory,
intraday audit, Canonical materialization, and Dataset materialization MUST
continue to operate over the mixed archive. This contract changes no Canonical
schema, Dataset schema, timestamp meaning, or source schema.

## 6. Safe Purge Interaction

Safe Purge has two mutually exclusive discovery modes per ingestion run:

1. **REGISTERED_PER_SYMBOL**: if the run has one or more
   `market_bar_snapshot_pairs` rows, those rows are authoritative. A selected
   symbol's exact pair MAY be planned independently. The plan seals both the
   run metadata and the complete registry row.
2. **LEGACY_INGESTION_RUN**: a run is eligible for legacy classification only
   if it has zero registry rows. For a proven legacy run, current
   `ingestion_runs.raw_file` / `curated_file` discovery remains authoritative.
   A legacy co-located file remains one immutable unit, so partial symbol or
   data scope is refused.

Zero registry rows is necessary, but not sufficient, for an executable legacy
target: planning MUST also prove the existing legacy pair and absence of
intersecting unregistered evidence. Registered mode MUST NOT fall back to
legacy pointers. A matching active file without a resolvable registry binding
is `UNREGISTERED_SNAPSHOT` and causes refusal. Registry rows are retained
historical provenance after quarantine; their active paths are not rewritten
to quarantine paths and no cascade cleanup occurs.

Under the shared lifecycle lock, execution of a registered target MUST prove:

- the exact run still exists and its sealed metadata is unchanged;
- the exact `(run_id, symbol)` row still exists and every field is unchanged;
- Raw and Curated paths are exact regular, non-reparse files within the active
  configured roots;
- size, SHA-256, row count, symbol, date, request key, source, schema version,
  and pair equality match the sealed facts; and
- no unplanned active Parquet intersects the requested scope.

Any uncertainty or drift MUST fail before mutation.

For every legacy target, execution MUST re-query
`market_bar_snapshot_pairs` for the exact run while holding the lifecycle lock
and MUST prove the result is still empty before moving any file. The appearance
of any row is mode/authority drift. This rule applies both to targets carrying
`binding_mode: "LEGACY_INGESTION_RUN"` and to historical v2 targets with no
`binding_mode` field.

### Sealed plan compatibility

`market-vault-safe-purge-plan-v2` remains the plan version. Existing v2 targets
without a binding-mode field retain their exact legacy interpretation and
remain executable only when all existing legacy proofs pass and execution
again proves that the run has zero registry rows. New legacy targets
MAY state `binding_mode: "LEGACY_INGESTION_RUN"`; new registered targets MUST
state `binding_mode: "REGISTERED_PER_SYMBOL"` and add a
`snapshot_pair_binding` object containing all eleven registry fields. Their
`run_binding` MUST also seal the current run metadata and the actual legacy
pointer values, including nulls. Parsers MUST reject unknown modes or a
registered target lacking either binding. This additive target union avoids a
gratuitous version change and does not weaken old plan verification.

For a new registered target, `run_binding` MUST contain the exact current
`ingestion_runs` values for `run_id`, `started_at`, `finished_at`,
`requested_trade_date`, sorted normalized `requested_symbols`, `interval`,
`requested_session` (the Catalog `session` value), `adjustment`, sorted
normalized `successful_symbols`, canonical `failed_symbols`, `raw_file`,
`curated_file`, `row_count`, `status`, and `config_hash`. Null compatibility
pointers remain explicit nulls. `snapshot_pair_binding` MUST contain exactly
the registry columns in Section 3, with `requested_trade_date` serialized as
ISO `YYYY-MM-DD`. The target's existing `raw` and `curated` file-identity
objects continue to seal resolved data-root-relative paths and physical facts.

## 7. Incomplete Publication

Filesystem and DuckDB publication are not a distributed transaction in v1.
The following states are incomplete and MUST NOT be guessed into a valid pair:

- Raw exists but Curated publication failed: one-sided physical evidence;
- Raw and Curated exist but registry insertion failed: unregistered evidence;
- a registry row exists but the run record is absent, non-terminal, or
  inconsistent: orphaned or ambiguous evidence;
- a process stops between symbols: only pairs with exact registry rows and a
  consistent terminal run record can become eligible.

Readers and inventory MAY expose physical evidence. Completion logic and Safe
Purge MUST fail closed when the required run/pair binding is incomplete.
Fail-closed recoverability, rather than a filesystem/Catalog distributed
transaction, is the v1 boundary.

A registered pair is eligible for lifecycle operations only when its symbol is
present in the run's `successful_symbols`, the run is terminal `SUCCESS` or
`PARTIAL`, and all request metadata agrees. Other physical evidence remains
visible to inventory but is not silently promoted to a valid pair.

## 8. Required Adversarial Outcomes

1. SPY and QQQ succeed in one new run: two Raw files, two Curated files, and
   two registry rows.
2. SPY succeeds and QQQ fetch fails: only SPY has a pair and registry row.
3. SPY is recollected: the old pair remains and a new run creates a new pair.
4. SPY-only purge from a registered SPY+QQQ run may target SPY; QQQ is untouched.
5. SPY-only purge from a legacy multi-symbol file is `COLOCATED_SYMBOLS`.
6. Exact whole-scope purge of that legacy physical unit remains supported.
7. A matching new active file without a row is `UNREGISTERED_SNAPSHOT`.
8. A registry row whose files contain another symbol fails closed.
9. A registry path changed after planning is execution-time drift.
10. An extra intersecting active Parquet beside registered files fails closed.
11. A multi-pair run with arbitrary non-null legacy pointers is invalid writer
    behavior and MUST be prevented by implementation tests.
12. A mixed legacy SPY and new per-symbol QQQ archive remains readable and
    auditable.
13. A single-symbol new run writes Raw and Curated but registry insertion
    fails: the symbol is not successful, `snapshot_pairs` is empty, both
    compatibility pointers are null, and completion and Safe Purge refuse the
    unregistered files rather than treating them as legacy.
14. SPY registration succeeds while QQQ registration fails after its files
    are written: only SPY is registered and successful, registered mode remains
    authoritative for the run, and QQQ files are unregistered evidence whose
    lifecycle operations refuse.
15. A legacy plan is sealed with zero registry rows and a row appears before
    execution: under-lock mode revalidation refuses before mutation.

## 9. Non-Goals

This contract does not design or implement per-symbol quality results,
restore, garbage collection, permanent deletion, legacy migration,
compaction, Parquet rewrite, a Hive symbol partition, Canonical or Dataset
changes, source-schema changes, OpenD protocol changes, real-data collection,
long-running backfill, or any version, tag, or Release mutation.
