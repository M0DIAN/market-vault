# Immutable market-bar publication and Raw recovery v1

## Scope and authority

Q28 strengthens the two market-bar `ParquetStore` writers and adds an offline
forward recovery entry point. It retains the layout, per-symbol pair facts,
registration, manifest schema, Catalog schema and completion authority in
[Market-Bar Physical Snapshots v1](market_bar_physical_snapshots_v1.md).
The separately approved
[atomic publication contract](../governance/destructive_operations/market_bar_atomic_file_publication_v1.json)
authorizes only the helper's invocation-owned temporary cleanup. This document
does not expand that destructive-operation authority.

The six option/calendar writers, historical artifact formats, legacy archive
readers and existing collection CLI exit behavior are outside this change.

## Single-file publication

`write_raw` and `write_curated` keep their existing final paths and Parquet
encoding (`index=False`, `compression="zstd"`). They serialize to an exclusively
created temporary sibling whose name ends in `.tmp`, rather than `.parquet`.
The helper flushes, syncs and closes the serialized file before publishing the
final pathname with `os.link`.

Every existing destination is a conflict, including an identical file, a
directory or a dangling link. An existence check is only an early refusal;
the hard-link operation supplies destination exclusion when publishers race.
Unsupported hard-link capability fails without an overwrite, replacement,
delete-then-publish or cross-filesystem fallback.

The helper retains the temporary object's identity from exclusive creation
and checks its type, identity, link count and relevant parent paths before
publication and cleanup. Cleanup may unlink only that invocation's still-owned
regular, non-reparse temporary object. Uncertain ownership or unsafe paths
leave the uncertain object untouched. It never adopts previous crash residue
or removes a published final file.

Successful linking is the physical commit point. A later cleanup failure raises
`AtomicFilePublicationError` with `published=True`, the final path and the
temporary path. The complete final file remains present. A caller must not
interpret that exception as a rollback or successful run completion.

This is a single-file publication guarantee at these writers. Raw, Curated,
lineage and Catalog remain separate publications; this is not a multi-file
transaction, protection against arbitrary external file mutation, or a
power-loss durability guarantee. Filesystem capability is checked by the
operation itself; this change does not claim new native platform qualification.

## Recovery entry points and defaults

The settings-backed API is:

```python
manifest = vault.recover_history_from_raw(source_manifest_path)
manifest = vault.recover_history_from_raw(
    source_manifest_path, symbols=["US.SPY"]
)
```

Here `vault` is an existing `MarketVault` instance configured for the source
store. The command-line equivalent is:

```bash
market-vault --settings config/settings.yaml recover-history \
  --manifest manifests/2026-08-03_original-run-id.json

market-vault --settings config/settings.yaml recover-history \
  --manifest manifests/2026-08-03_original-run-id.json --symbols US.SPY
```

The examples use placeholder source paths and run IDs. Recovery never creates
an OpenD collector or refetches data. It retains the existing market-bar
lifecycle lock and does not reclaim stale locks automatically.

Omitting `symbols` selects every symbol in the original request. An explicit
selection must be a nonempty subset; symbols are stripped, uppercased,
deduplicated and sorted. Every selected Raw input must pass preflight. A source
run with only some retained Raw can therefore be recovered with an explicit
valid subset; the default does not silently skip missing inputs.

| Exit code | Result |
| --- | --- |
| `0` | The new run returned terminal `SUCCESS`; stdout is its ordinary `RunManifest` JSON. |
| `2` | The new run returned terminal `PARTIAL` or `FAILED`; stdout still contains its complete `RunManifest` JSON. |
| `1` | Recovery was refused or raised an error; stdout contains a JSON error. An error after publication does not imply that no new physical evidence exists. |

## Source eligibility and preflight

Recovery requires one explicitly named source manifest with the complete
current `RunManifest` shape, terminal status `SUCCESS`, `PARTIAL` or `FAILED`,
and `snapshot_binding_mode` exactly `REGISTERED_PER_SYMBOL`. Missing, null,
legacy or unknown binding modes, incomplete terminal evidence and contradictory
request/outcome metadata are refused.

The original request must be canonical. Its configuration hash is reconstructed
from the original date, symbols, interval, session, adjustment and configured
source schema version. Settings must identify the original source store and
compatible schema. Available manifest pair and Catalog facts must agree with
that request, source, schema and deterministic file paths.

A source Catalog run row is not required: a real collection can write a
terminal manifest and then fail while recording that row. If the row or pair
records are present, recovery validates the retained facts. It does not create,
rewrite or promote the original run record to make recovery eligible.

For each selected symbol, the expected Raw pathname is derived from the frozen
`ParquetStore._path` layout and original run/request identity. Recovery does not
scan directories, select a latest snapshot or substitute an arbitrary orphan.
It reads the exact regular, non-reparse source file and verifies its original
code, requested trade date, interval, requested session, adjustment and
`ingestion_run_id` before assigning any new run metadata. Available source/schema
columns and retained pair row counts must also agree. Missing, empty,
unreadable or mismatched Raw is a refusal.

Manifest and Raw parsing use the same captured byte buffers that are hashed.
Path/object drift during reading is refused. This binds the lineage to the
bytes actually consumed, without a separate hash-then-reopen gap. It does not
invent an earlier trusted content hash for originally unregistered Raw.

## Fresh run, lineage and completion

After source preflight, recovery creates a fresh run and refuses a collision
with existing run, pair, quality, manifest, report or lineage evidence. Recovery
manifest and report files use exclusive creation; the lineage uses the same
no-replace publication helper as market-bar files.

The existing collection core performs normalization, Raw publication, Curated
publication, persisted-pair verification and registration for the new run.
Normalization assigns the actual recovery ingestion time. A symbol becomes
successful only after its persisted pair has been verified and registered.

The immutable lineage file is stored beside the new manifest as
`<trade-date>_<new-run-id>.recovery.json`. Its fields are:

| Field | Meaning |
| --- | --- |
| `schema_version` | `market-vault-raw-history-recovery-lineage-v1` |
| `replay_version` | `market-bars-raw-replay-v1` |
| `run_id`, `started_at`, `config_hash` | New recovery run identity and request binding. |
| `source`, `source_schema_version` | Configured source and schema used for replay. |
| `source_manifest` | Exact consumed manifest `path`, `sha256` and original `run_id`. |
| `raw_inputs` | Selected inputs, each with `symbol`, exact `path` and consumed-byte `sha256`. |

Recovery publishes this lineage and records quality before terminal
`Catalog.record_run`. Ordinary market-bar collection also records quality
before its terminal run record. A lineage or quality-recording failure must
therefore leave no new completed run authority, even when new physical files
or a terminal manifest already exist. The existing registered-pair and quality
checks remain authoritative for completion.

Original Raw, Curated, manifests, reports, Catalog rows and terminal statuses
remain unchanged. Repeating recovery creates another new run; it does not
return idempotent success for earlier output or replace old Curated data.

## Bounded failure recovery

Supported source evidence includes a terminal run with retained Raw after
Curated publication failed; a terminal run with both files but failed pair
registration; and a terminal manifest retained after terminal Catalog
publication failed. Eligibility still depends on the same preflight rules.

A process termination before a usable terminal manifest exists is outside
this entry point. Other exclusions are automatic unlocking, arbitrary orphan
adoption, garbage collection, runtime-data rollback or deletion, legacy
migration, repair of old run status, source relocation discovery and a
distributed transaction or recovery-registry framework.
