# Dataset Catalog Contract (v0.6.0 PR-5 + PR-6 + PR-7)

Status: Dataset Catalog contract, frozen models, metadata projection,
Catalog content identity, the immutable snapshot builder, the snapshot
materializer, the verified snapshot reader implemented by PR-5 and
PR-6, and the Dataset Catalog CLI (build / verify / list / show)
implemented by PR-7
Target release: v0.6.0
Not available in released v0.5.1. The Dataset Catalog is not implemented in v0.5.1.

This document is the precise formal contract of the Dataset Catalog
layer. Part A (PR-5) fixes the exact Catalog entry schema, the structural
split between content facts and non-content metadata, the versioned
Catalog content identity and its normalization rules, the duplicate /
conflict policy, the trust boundary of the metadata projection, and the
fail-closed validation rules. Part B (PR-6) fixes the deterministic
Catalog builder, the exact physical snapshot schema, the separation of
the Catalog content identity from the physical snapshot identity, the
materialization transaction, and the verified snapshot reader. Part C
(PR-7) fixes the Dataset Catalog CLI: the four formal commands,
the settings-independent dispatch, the exact build / verify / list /
show surfaces, the deterministic JSON output, and the exit-code
contract. PR-7 completed the CLI; PR-8 completed integrated acceptance;
PR-9 is the v0.6.0 release preparation. There is no standalone
`dataset-catalog-query` command: the query surface is fixed as the
read-only list filters of `dataset-catalog-list` over one verified
snapshot.

The PR-5 production modules are:

```text
src/market_vault/dataset/dataset_catalog_models.py
src/market_vault/dataset/dataset_catalog_identity.py
src/market_vault/dataset/dataset_catalog_projection.py
```

The PR-6 production modules are:

```text
src/market_vault/dataset/dataset_catalog_builder.py
src/market_vault/dataset/dataset_catalog_builder_models.py
src/market_vault/dataset/dataset_catalog_serialization.py
src/market_vault/dataset/dataset_catalog_snapshot_identity.py
src/market_vault/dataset/dataset_catalog_materialization.py
src/market_vault/dataset/dataset_catalog_materialization_models.py
src/market_vault/dataset/dataset_catalog_reader.py
src/market_vault/dataset/dataset_catalog_reader_models.py
```

The PR-7 production modules are:

```text
src/market_vault/dataset/dataset_catalog_cli.py
src/market_vault/dataset/dataset_catalog_cli_models.py
```

---

# Part A — PR-5 logical contract

## 1. Distinction from the legacy Catalog

The new Dataset Catalog layer is fully independent of the existing
`market_vault.storage.catalog.Catalog`:

- the legacy Catalog keeps its responsibilities: ingestion runs, quality
  results, snapshot views, the trading calendar, and Raw / Curated
  queries, backed by DuckDB views;
- the new Dataset Catalog indexes verified immutable Dataset builds:
  Dataset discovery, Dataset metadata filtering, and Catalog snapshot
  verification;
- the new Catalog never reuses the legacy Catalog's tables, schema, views,
  identity, or behavior, and `init-catalog` remains the legacy ingestion
  catalog command;
- the new Catalog defines no DuckDB table and no view; the physical
  Catalog snapshot is a plain immutable filesystem directory (PR-6).

## 2. Trust boundary and projection entry point

The metadata projection has exactly one public entry point:

```python
project_dataset_catalog_entry(build: VerifiedDatasetBuild) -> DatasetCatalogEntry
```

- the projection accepts exactly a `VerifiedDatasetBuild` — the frozen,
  deeply immutable result of `load_verified_dataset`;
- a manifest dict, a manifest path, an arbitrary build directory, and any
  other object fail closed with `DatasetCatalogError`;
- the projection never calls `load_verified_dataset` itself and never
  scans the filesystem; the PR-6 builder calls the verified reader on
  every candidate and passes the verified builds into this projection;
- the projection is a pure function over verified typed facts: it never
  re-derives the Dataset, never executes Feature or Label work, never
  reads the Dataset Parquet, and never accesses OpenD, the network,
  settings, or the current time.

## 3. Catalog entry schema

PR-5 defines three frozen typed models.

### 3.1 `DatasetCatalogDatasetFacts` (content facts)

The identity-bearing normalized verified Dataset facts. Exactly these
fields enter the Catalog content identity:

```text
dataset_id                      # 64-char lowercase SHA-256
dataset_kind                    # normalized text
status                          # COMPLETE | EMPTY
logical_row_count               # real non-negative int; EMPTY requires 0
dataset_schema_id               # 64-char lowercase SHA-256
logical_dataset_content_id      # 64-char lowercase SHA-256
dataset_as_of                   # UTC microsecond instant or null
scope                           # frozen DatasetScope (symbols, trade_dates,
                                #   interval, adjustment, requested_session)
feature_spec_pins               # frozen SpecPin tuple, kind FEATURE
label_spec_pins                 # frozen SpecPin tuple, kind LABEL
split_spec_pin                  # frozen SpecPin (kind SPLIT) or null
canonical_build_pins            # frozen CanonicalBuildPin tuple
canonical_row_version_ids       # sorted deduplicated 64-hex tuple
completion                      # frozen CompletionSummary
```

`canonical_row_version_ids` is included because it has long-term
discovery value (the exact canonical row versions covered by the Dataset)
and is already a verified, deterministically normalized fact of the
manifest identity contract. **Coverage direction (identical to the
existing `DatasetIdentityInput` contract):** the Catalog-level
`canonical_row_version_ids` must be a subset of the union of the pinned
canonical builds' row versions — every Catalog-level row-version ID must
be covered by `canonical_build_pins`. A `CanonicalBuildPin` may declare
more row versions than the Dataset-level list uses; the Catalog contract
never adds a private "every pinned row version must be used" restriction.
No other manifest facts are copied into the Catalog record:
`implementations`, `gap_references`, `manifest_schema_version`,
`serialization_format`, and `serialization_format_version` remain
Dataset-internal build facts and are not indexed.

### 3.2 `DatasetCatalogObservedMetadata` (non-content metadata)

```text
built_at       # UTC microsecond instant
build_path     # lexically absolute Path of the verified build directory
```

These facts are recorded for observability only. The type is
structurally disjoint from `DatasetCatalogDatasetFacts` — no field name
is shared — so the metadata can never be accidentally mixed into the
content identity.

### 3.3 `DatasetCatalogEntry` (projection)

```text
dataset_facts        # DatasetCatalogDatasetFacts
observed_metadata    # DatasetCatalogObservedMetadata
content_id           # 64-char lowercase SHA-256, recomputed and
                     #   self-validated at construction
```

The entry combines the two without making the metadata identity-bearing.
`content_id` binds only `dataset_facts` and is recomputed at construction,
so `dataclasses.replace` tampering with the content ID or the facts fails
closed. A legal observed-metadata change never changes `content_id`: a
different `built_at` or a move to another parent directory (same
`dataset_id` basename) is accepted and keeps the same content ID.
Metadata fails closed only when its own shape is invalid (naive `built_at`,
relative or unclean `build_path`) or when the `build_path` basename does
not equal `dataset_facts.dataset_id`.

## 4. Content facts vs non-content metadata: the boundary

The following never enter Catalog content identity, by contract and by
model structure. Physical paths and location metadata are recorded only
as non-content observed metadata:

```text
Dataset built_at
Dataset build_path / physical paths / location metadata
Catalog output_root
Catalog snapshot path
machine / hostname
cwd
filesystem separator / representation
mtime
current time
scan order
candidate input order
```

moving the same verified Dataset to another parent directory never
changes its content facts or the Catalog content identity; `build_path`
changes only the observed metadata.

## 5. Catalog content identity

PR-5 defines a new, fully independent versioned Catalog content identity.
No Dataset ID, Canonical ID, Sample Generation ID, or existing
identity/version constant is modified, and the Catalog identity never
flows back into any Dataset or Canonical identity.

### 5.1 Per-Dataset content digest

`catalog_dataset_content_id(facts)` is the 64-character lowercase SHA-256
of one `DatasetCatalogDatasetFacts` record under the versioned canonical
encoding. It binds the entry schema version and every normalized content
fact.

### 5.2 Catalog content identity

`dataset_catalog_content_id(entries)` is the 64-character lowercase
SHA-256 over:

```text
Catalog contract version
Catalog content identity version
normalized set of per-Dataset content digests, keyed and sorted by dataset_id
```

### 5.3 Normalization

Normalization is deterministic and happens at the formal boundaries,
following the existing Dataset identity contract:

- every SHA-256 field is normalized to lowercase 64-hex;
- raw identity text (`dataset_kind`) is NFC-normalized, deterministically
  stripped, and rejected when it contains control characters or reserved
  encoding separators;
- set-like facts (canonical row-version IDs) are normalized and
  deduplicated as a set;
- structures with a business unique key — spec pins under
  `(kind, name, version)`, canonical build pins under
  `canonical_build_id`, completion entries under their key — are sorted
  deterministically and fail closed on duplicate or conflicting entries;
  conflicting entries are never silently deduplicated. Spec pins with the
  same `(kind, name, version)` but different content hashes are
  conflicting duplicates and fail closed;
- every instant is normalized to UTC microseconds, so timezone-equivalent
  representations of the same instant produce the same identity;
- nested pins use the existing frozen typed models
  (`DatasetScope`, `SpecPin`, `CanonicalBuildPin`, `CompletionSummary`)
  whose own normalized semantics are trusted and never re-implemented;
- the digest payload is ordered by the frozen `dataset_id` key, so
  candidate input order, scan order, host, cwd, and output location never
  change the identity.

### 5.4 Duplicate `dataset_id` policy (fixed by PR-5)

- exactly identical normalized content facts for the same `dataset_id`
  merge under set semantics into one Dataset record;
- any conflicting content fact for the same `dataset_id` fails closed
  with `DatasetCatalogError`;
- first-wins, last-wins, and path-wins are never used.

### 5.5 Physical snapshot identity

The physical Catalog snapshot identity is defined by PR-6
(Part B, section 12). It is fully independent of the Catalog content
identity and never flows back into any Dataset fact.

## 6. Fail-closed validation

The frozen models fail closed at construction on:

```text
invalid SHA-256 IDs
unsupported status
negative / non-real counts
wrong pin kinds
duplicate or conflicting spec pins (same kind/name/version)
duplicate conflicting pins / facts
scope inconsistency (completion entries outside the scope)
Catalog row-version IDs not covered by the pinned canonical builds
malformed / non-UTC datetimes
unsafe identity text (control characters / reserved separators)
untyped / invalid element payloads
non-iterable container inputs
content ID mismatch
wrong build_path basename (not equal to dataset_id)
unsupported contract or entry schema versions
```

`DatasetCatalogError` (a subclass of `DatasetError`) is the unified
failure type for formal input validation. Low-level documented validation
exceptions (``DatasetError``, ``TypeError`` from a non-iterable container,
``ValueError``, ``KeyError``) are converted to it; `AssertionError` /
`RuntimeError` and other programming errors are never swallowed and never
converted to business errors. Iterable container input is accepted at the
construction boundary and frozen into immutable tuples; the models never
store a mutable container.

---

# Part B — PR-6 immutable snapshot contract

## 7. Builder

```python
build_dataset_catalog(
    *,
    dataset_root=None,
    candidate_build_dirs=None,
) -> DatasetCatalogBuildResult
```

### 7.1 Input modes

Exactly one of `dataset_root` or `candidate_build_dirs` must be provided;
both or neither fail closed with `DatasetCatalogBuildError`. cwd,
settings, a latest pointer, a default Dataset root, and environment
variables are never implicit inputs.

- **`dataset_root` mode — explicit bounded discovery root.** Only the
  direct children are enumerated (a single non-recursive scan; never
  recursive, never `rglob`, never the parent directory, never other
  disks). A direct child whose name strictly matches `^[0-9a-f]{64}$` is
  a candidate. Every non-candidate child — ordinary files, ordinary
  directories, `.staging-*` residue, documentation, any other name — is
  ignored but never entered or followed. A 64-hex named child that is a
  symlink, junction, reparse point, ordinary file, or special file fails
  closed. `dataset_root` itself must be a lexically absolute safe path,
  and it and every existing parent component must be a real, regular,
  non-link directory; `resolve()` is never used to mask a link.
- **`candidate_build_dirs` mode — explicit candidate set.** An explicit
  iterable frozen at the boundary; input order never matters; an exactly
  identical lexical candidate path listed twice is processed once. Every
  candidate must be a lexically absolute safe path.
- **No relative formal input.** `dataset_root` and every explicit
  candidate must already be lexically absolute; the builder never reads
  `Path.cwd()` to complete a formal input, so cwd — like settings, a
  latest pointer, a default Dataset root, and environment variables — is
  never an implicit input. A relative `dataset_root` or a relative
  explicit candidate fails closed with `DatasetCatalogBuildError`.
- **Empty Catalog.** `candidate_build_dirs=()` and a root with no 64-hex
  candidate both produce a legal empty Catalog
  (`dataset_count == 0`, `entries == ()`, a legal content identity).
  An empty Catalog is never an error.

### 7.2 Trust boundary

Every candidate must pass the formal `load_verified_dataset(candidate)`;
only after it returns a `VerifiedDatasetBuild` is
`project_dataset_catalog_entry(build)` called. The builder never parses a
manifest itself, never trusts an unverified manifest, never reads Dataset
Parquet, and never repairs an invalid Dataset.

### 7.3 Duplicate location policy

Two different physical paths that yield the same `dataset_id` fail closed
as an **ambiguous duplicate Dataset location** — a Catalog snapshot
records exactly one observed location per Dataset, so first-wins,
last-wins, shortest-path-wins, and lexicographical-path-wins are never
used. The same `dataset_id` with different content facts fails closed the
same way.

### 7.4 Determinism

The same set of verified Datasets always produces the same entry order
(`dataset_id` ascending), the same Catalog content ID, and the same
logical payload, regardless of candidate order, root enumeration order,
cwd, machine, or invocation time. Moving a verified Dataset to another
parent keeps `DatasetCatalogDatasetFacts`, the per-entry content ID, and
the Catalog content ID identical and changes only the observed build
location. The builder never reads the current time, never accesses the
network / OpenD / settings, and never writes files.

### 7.5 Result model

`DatasetCatalogBuildResult` is frozen and self-validating: it carries
`entries` (frozen tuple sorted by `dataset_id`, unique), the recomputed
`catalog_content_id` (PR-5 identity over the entries), the recomputed
`dataset_count`, and `builder_version`. Construction re-validates every
invariant, so a `dataclasses.replace` tamper fails closed.

## 8. Exact physical layout

One final snapshot directory is fixed as:

```text
<output_root>/<snapshot_id>/
    catalog.json
    manifest.json
    _SUCCESS
```

Only these three files are ever allowed. There is no `latest`, no current
pointer, no timestamp or random-UUID directory name, no symlink pointer,
no DuckDB table, no Parquet, no extra index, and no hidden metadata file.
Staging is fixed at `<output_root>/.staging-<snapshot_id>` — never a
random name.

## 9. catalog.json exact schema

`catalog.json` is UTF-8 without BOM, canonical JSON with a fixed field
set, strict unknown / missing rejection, and deterministic key
serialization. It carries the complete lossless PR-5 entry payload and
nothing else. The same `DatasetCatalogBuildResult` always produces
byte-identical `catalog.json`; the current time, `output_root`, the
snapshot path, the host, cwd, mtimes, and scan / candidate order never
enter it. The snapshot `built_at` is deliberately absent — it belongs to
the physical manifest only.

```json
{
  "snapshot_schema_version": "market-vault-dataset-catalog-snapshot-v1",
  "catalog_contract_version": "market-vault-dataset-catalog-contract-v1",
  "catalog_entry_schema_version": "market-vault-dataset-catalog-entry-v1",
  "catalog_content_id_version": "market-vault-dataset-catalog-content-v1",
  "builder_version": "market-vault-dataset-catalog-builder-v1",
  "catalog_content_id": "<64-hex>",
  "dataset_count": 0,
  "datasets": []
}
```

Every dataset record:

```json
{
  "content_id": "<64-hex>",
  "dataset_facts": {
    "dataset_id": "...",
    "dataset_kind": "...",
    "status": "COMPLETE | EMPTY",
    "logical_row_count": 0,
    "dataset_schema_id": "...",
    "logical_dataset_content_id": "...",
    "dataset_as_of": "... | null",
    "scope": {
      "symbols": ["..."],
      "trade_dates": ["YYYY-MM-DD"],
      "interval": "...",
      "adjustment": "...",
      "requested_session": "..."
    },
    "feature_spec_pins": [{"kind": "FEATURE", "name": "...", "version": "...", "content_sha256": "..."}],
    "label_spec_pins": [{"kind": "LABEL", ...}],
    "split_spec_pin": {"kind": "SPLIT", ...} | null,
    "canonical_build_pins": [{
      "canonical_build_id": "...",
      "canonical_content_id": "...",
      "canonical_builder_version": "...",
      "canonical_schema_version": "...",
      "materializer_version": "...",
      "gap_policy_version": "...",
      "gap_content_id": "...",
      "status": "...",
      "canonical_row_version_ids": ["..."],
      "source_snapshots": [{
        "ingestion_run_id": "...",
        "physical_snapshot_hash": "...",
        "logical_source_rows_hash": "...",
        "source_schema_version": "...",
        "requested_trade_date": "YYYY-MM-DD",
        "requested_session": "..."
      }]
    }],
    "canonical_row_version_ids": ["..."],
    "completion": {
      "complete_count": 0,
      "incomplete_count": 0,
      "missing_count": 0,
      "entries": [{"code": "...", "trade_date": "YYYY-MM-DD", "status": "...", "reason_code": "... | null"}]
    }
  },
  "observed_metadata": {
    "built_at": "YYYY-MM-DDTHH:MM:SS+00:00",
    "build_path": "<forward-slash recorded location text>"
  }
}
```

`dataset_facts` is the exact PR-5 field set — no manifest-internal field
is ever copied. All nested models (`DatasetScope`, `SpecPin`,
`CanonicalBuildPin`, `SourceSnapshotPin`, `CompletionSummary`,
`CompletionEntry`) are serialized with their formal fields. The `datasets`
array is strictly `dataset_id`-ascending and unique. `dataset_count` and
`catalog_content_id` are recomputed at serialization time.

### 9.1 Recorded `build_path` representation

`observed_metadata.build_path` is non-content metadata written as
`entry.observed_metadata.build_path.as_posix()` — canonical forward-slash
text (`C:/Users/.../<dataset_id>` on Windows, `/home/.../<dataset_id>` on
POSIX). Requirements: forward-slash canonical text, no backslash, no
`.` / `..` component, final component == `dataset_id`, UTF-8. The
snapshot verified reader treats it as **historical observed location
text**, never as a live Dataset path to revisit: it is never resolved,
stat'ed, checked for existence, or passed to `load_verified_dataset`.
This keeps snapshot verification independent of the original Dataset
directories (PR-8 portability boundary).

## 10. manifest.json exact schema

```json
{
  "manifest_schema_version": "market-vault-dataset-catalog-snapshot-manifest-v1",
  "snapshot_id_version": "market-vault-dataset-catalog-snapshot-id-v1",
  "materializer_version": "market-vault-dataset-catalog-materializer-v1",
  "builder_version": "market-vault-dataset-catalog-builder-v1",
  "snapshot_id": "<64-hex>",
  "catalog_content_id": "<64-hex>",
  "built_at": "YYYY-MM-DDTHH:MM:SS+00:00",
  "dataset_count": 0,
  "catalog_file": {
    "relative_path": "catalog.json",
    "byte_size": 0,
    "sha256": "<64-hex>"
  }
}
```

Exact field set; UTC microsecond `built_at`;
`catalog_file.relative_path` is always `catalog.json`; `byte_size` is a
real non-negative integer; `sha256` is lowercase 64-hex;
`dataset_count` and `catalog_content_id` agree with `catalog.json`;
`builder_version` agrees with `catalog.json`. The manifest never records
the `output_root`, the snapshot absolute path, the machine name, cwd, or
the current time.

## 11. Content identity vs snapshot identity

PR-5 froze the Catalog content identity as normalized verified Dataset
facts only. PR-6 adds a separate materialization or snapshot identity —
an independent physical snapshot identity:

```python
DATASET_CATALOG_SNAPSHOT_ID_VERSION = market-vault-dataset-catalog-snapshot-id-v1
```

`snapshot_id = encode_identity(snapshot_id_version, {...})` over:

```text
snapshot_schema_version    market-vault-dataset-catalog-snapshot-v1
manifest_schema_version    market-vault-dataset-catalog-snapshot-manifest-v1
snapshot_id_version        market-vault-dataset-catalog-snapshot-id-v1
builder_version            market-vault-dataset-catalog-builder-v1
materializer_version       market-vault-dataset-catalog-materializer-v1
catalog_content_id         (PR-5 content identity)
dataset_count
built_at                   explicit snapshot built_at (UTC microseconds)
catalog_file_byte_size
catalog_file_sha256
```

Therefore: the same Catalog logical facts + the same observed metadata +
the same explicit `built_at` -> the same snapshot ID; a different
`output_root` -> the same snapshot ID; moving the Catalog snapshot to
another parent -> the same snapshot ID; a Dataset path change -> the same
Catalog content ID, different `catalog.json` bytes, different snapshot
ID; a snapshot `built_at` change -> the same Catalog content ID,
different snapshot ID. These PR-6 version constants never enter
`dataset_id`, the Canonical identity, the Sample Generation identity, or
the PR-5 Catalog content identity.

## 12. Materialization transaction

```python
materialize_dataset_catalog_snapshot(
    result: DatasetCatalogBuildResult,
    *,
    output_root,
    built_at: datetime,
) -> DatasetCatalogMaterializationResult
```

`built_at` is always explicit (never the current time). One commit
executes the fixed sequence:

```text
1.  validate / revalidate the DatasetCatalogBuildResult
2.  normalize the explicit built_at (UTC microseconds)
3.  generate the canonical catalog.json bytes
4.  compute the catalog byte size and SHA-256
5.  compute the snapshot_id
6.  derive the final / staging paths
7.  verify output_root safety (no symlink / junction path component)
8.  existing final: full strict idempotency verification
9.  reject pre-existing staging (never deleted, never adopted)
10. create staging (output_root / .staging-<snapshot_id>)
11. exclusive-write catalog.json
12. readback exact bytes
13. construct manifest.json
14. serialize + validate manifest.json
15. exclusive-write manifest.json
16. readback exact bytes
17. full strict private staging verification (without _SUCCESS)
18. exclusive-write empty _SUCCESS LAST
19. verify _SUCCESS
20. true no-replace atomic publication
21. return the frozen result
```

### 12.1 Write validation

Every artifact writer validates the `handle.write` return value
(`type(written) is int` and `written == len(payload)`; `None`, bool,
zero, short, long, and other types fail closed), flushes, then readbacks
the exact bytes. `_SUCCESS` is an exact empty regular file, not a
symlink.

### 12.2 `_SUCCESS` written last

`_SUCCESS` is the last artifact write of every commit; it is written only
after the full private staging verification of `catalog.json` and
`manifest.json`.

### 12.3 Staging cleanup

After this call created the staging directory, any exception —
documented business error, `OSError`, Unicode error, formal
`TypeError` / `ValueError`, `RuntimeError`, `AssertionError`, or any
other programming error — best-effort deletes **only** the staging
directory created by this call and propagates the original exception
semantics: documented errors are converted to
`DatasetCatalogMaterializationError` at the public boundary with
`__cause__` preserved; programming errors propagate unchanged. An
existing final, a pre-existing staging directory, and every other
directory are never deleted.

### 12.4 Existing-final idempotency

An existing final directory is never trusted by its name alone: it is
strictly verified through the public verified reader and bound to the
requested result (snapshot ID, Catalog content ID, dataset count,
`built_at`, per-entry facts, catalog byte facts). An identical existing
snapshot returns `created_new_snapshot=False` with zero rewrites and zero
mtime touches; any difference or corruption fails closed. No overwrite
ever happens.

### 12.5 Atomic no-overwrite publication

The publication primitive itself refuses an existing destination:
Windows native atomic directory-move semantics or Linux
`renameat2(..., RENAME_NOREPLACE)` — the same primitive as the Dataset
materializer. Platforms or filesystems without a safe primitive fail
closed; `os.replace`, plain overwriting `os.rename`, `shutil.move`, and
delete-then-rename are never used. A final directory that appears
concurrently during staging is verified the same way: identical ->
`created_new_snapshot=False` after our own staging is removed; corrupt or
conflicting -> fail closed without deleting or overwriting the final.

## 13. Verified reader

```python
load_verified_dataset_catalog(snapshot_dir) -> VerifiedDatasetCatalogSnapshot
```

Accepts exactly one explicit final snapshot directory
(`<output_root>/<snapshot_id>`); the directory name must be the lowercase
64-hex `snapshot_id` carried by the manifest. The path must be lexically
absolute, free of `.` / `..` components, and no path component may be a
symlink / junction / reparse point (`resolve()` is never used to mask a
link; a path whose link status cannot be verified fails closed).

The reader verifies only the snapshot itself:

```text
1.  coerce the explicit snapshot_dir
2.  lexical absolute path
3.  parent-chain symlink / junction safety
4.  snapshot_dir is a real regular directory
5.  dirname is a strict 64-hex snapshot_id
6.  exact whitelist (catalog.json, manifest.json, _SUCCESS only)
7.  reject every symlink / junction / reparse / special entry
8.  _SUCCESS exactly empty
9.  read manifest bytes
10. strict parse of manifest (exact fields, fixed versions, types)
11. canonical manifest bytes equality
12. snapshot_id == directory name
13. read catalog.json bytes
14. size / SHA-256 == manifest catalog_file record
15. strict parse of catalog.json (exact fields, fixed versions,
    typed nested reconstruction)
16. canonical catalog bytes equality
17. reconstruct typed DatasetCatalogDatasetFacts per entry
18. recompute each entry content_id over its facts
19. verify dataset ordering / uniqueness
20. recompute the PR-5 Catalog content identity over the facts
21. compare with the top-level catalog_content_id
22. verify the dataset counts
23. recompute the physical snapshot_id
24. verify the manifest snapshot_id
25. second pass: path safety, whitelist, _SUCCESS, manifest re-read,
    catalog bytes / hash re-read
26. construct the VerifiedDatasetCatalogSnapshot
```

The second pass rejects mixed-instant concurrent mutation; no partial
snapshot is ever returned. The reader never calls `load_verified_dataset`,
never accesses a recorded Dataset build path, never verifies the original
Datasets still exist, never scans the Dataset root or the Catalog
`output_root`, never connects to OpenD / the network, never loads
settings, and never reads the current time. A Dataset that later moved,
went offline, was deleted, or sits on an unmounted disk never makes an
intact snapshot unverifiable.

All corruption and tamper failures — missing artifacts, extra files or
directories, non-empty `_SUCCESS`, symlinked artifacts, a symlinked /
junctioned snapshot directory, wrong directory name, catalog hash or
byte-size mismatch, manifest snapshot-ID / content-ID / `built_at`
tampering, catalog top-level content-ID tampering, entry content-ID
tampering, dataset-facts tampering, dataset-count tampering, dataset
order tampering, duplicate `dataset_id`, unknown / missing JSON fields,
BOM, non-canonical whitespace / key order / timestamp text, unsupported
versions, and invalid recorded location text — raise
`DatasetCatalogArtifactValidationError` with `__cause__` preserved;
programming errors are never converted.

## 14. Security and recovery

- **Snapshot relocation.** A complete verified snapshot moved from
  `<root-A>/<snapshot_id>` to `<root-B>/<snapshot_id>` still verifies
  with the same snapshot ID and Catalog content ID: the Catalog
  `output_root` and the snapshot parent path never enter the snapshot
  identity. A changed directory name fails closed.
- **Dataset relocation.** The same verified Dataset moved from
  `A/<dataset_id>` to `B/<dataset_id>` and re-indexed keeps identical
  facts, per-entry content IDs, and the Catalog content identity; the
  recorded observed path, the `catalog.json` bytes, and therefore the
  snapshot ID change. This is a formal regression requirement.
- **Empty Catalog.** `candidate_build_dirs=()` and a root without any
  64-hex candidate produce a legal empty Catalog: `dataset_count == 0`,
  `entries == ()`, a legal content identity, a legal `catalog.json` /
  `manifest.json` / snapshot ID, and a successful verified read. An empty
  Catalog is never an error.
- **No side effects.** The builder and the reader never write, delete,
  repair, or rewrite anything; the materializer writes only inside the
  explicit `output_root`. No current time, no network, no OpenD, no
  settings.
- **No latest, no auto-repair.** `latest` is never implicit and no
  snapshot is ever repaired; a corrupt snapshot fails closed and stays
  untouched. The Catalog never scans for a latest snapshot and there is
  no latest pointer anywhere in the physical layout.

## 15. PR-6 boundary: the CLI is PR-7

PR-6 does not implement any Catalog CLI; the Catalog CLI is implemented
by PR-7 and fixed in Part C:

```text
dataset-catalog-build CLI       -> implemented by PR-7 (Part C, section 19)
dataset-catalog-verify CLI      -> implemented by PR-7 (Part C, section 20)
dataset-catalog-list CLI        -> implemented by PR-7 (Part C, section 21)
dataset-catalog-show CLI        -> implemented by PR-7 (Part C, section 22)
```

The following remain not implemented and outside v0.6.0 scope:

```text
any standalone Catalog query CLI  (the query surface is fixed as the
                                  read-only list filters of
                                  dataset-catalog-list)
Python Client                    (a v0.7 direction)
REST API
latest pointer
DuckDB Catalog tables / views
legacy Catalog integration
```

PR-8 integrated acceptance completed; no standalone
`dataset-catalog-query` exists because `dataset-catalog-list` filters are
the fixed query surface.

## 16. Version constants

```text
# PR-5
DATASET_CATALOG_CONTRACT_VERSION      = market-vault-dataset-catalog-contract-v1
DATASET_CATALOG_ENTRY_SCHEMA_VERSION  = market-vault-dataset-catalog-entry-v1
DATASET_CATALOG_CONTENT_ID_VERSION    = market-vault-dataset-catalog-content-v1

# PR-6
DATASET_CATALOG_BUILDER_VERSION       = market-vault-dataset-catalog-builder-v1
DATASET_CATALOG_SNAPSHOT_SCHEMA_VERSION    = market-vault-dataset-catalog-snapshot-v1
DATASET_CATALOG_SNAPSHOT_MANIFEST_VERSION = market-vault-dataset-catalog-snapshot-manifest-v1
DATASET_CATALOG_SNAPSHOT_ID_VERSION   = market-vault-dataset-catalog-snapshot-id-v1
DATASET_CATALOG_MATERIALIZER_VERSION  = market-vault-dataset-catalog-materializer-v1
DATASET_CATALOG_READER_CONTRACT_VERSION = market-vault-verified-dataset-catalog-reader-v1

# PR-7
DATASET_CATALOG_CLI_CONTRACT_VERSION        = market-vault-dataset-catalog-cli-v1
DATASET_CATALOG_CLI_RESULT_SCHEMA_VERSION   = market-vault-dataset-catalog-cli-result-v1
```

Changing a version constant changes every Catalog identity that
references it; it never changes any Dataset or Canonical identity. The
PR-6 constants never enter the PR-5 Catalog content identity, and the
PR-7 constants bind the CLI result JSON only — they never enter the
Catalog content identity, the snapshot identity, or any Dataset or
Canonical identity.

---

# Part C — PR-7 Dataset Catalog CLI

## 17. CLI scope and versioned result contract

The PR-7 CLI is a thin formal command surface over the PR-6 verified
chain. It defines exactly four commands:

```text
market-vault dataset-catalog-build
market-vault dataset-catalog-verify
market-vault dataset-catalog-list
market-vault dataset-catalog-show
```

There is no standalone `dataset-catalog-query` command: the query
surface is fixed as the read-only list filters of
`dataset-catalog-list` over one verified snapshot. The CLI never
implements a second builder, validator, or reader: the build command
calls exactly the formal chain `build_dataset_catalog` ->
`materialize_dataset_catalog_snapshot` ->
`load_verified_dataset_catalog`; verify, list, and show call exactly
`load_verified_dataset_catalog`. The CLI never parses a manifest, never
reads `catalog.json` or `manifest.json` itself, never reads Dataset
Parquet, never calls `load_verified_dataset`, never uses DuckDB, never
runs SQL, never uses pandas, and never accesses the network.

The CLI is governed by two version constants (defined in
`dataset_catalog_cli_models.py`):

```text
DATASET_CATALOG_CLI_CONTRACT_VERSION      = market-vault-dataset-catalog-cli-v1
DATASET_CATALOG_CLI_RESULT_SCHEMA_VERSION = market-vault-dataset-catalog-cli-result-v1
```

Every CLI result JSON — success and failure — carries
`result_schema_version` and `cli_contract_version` as its first two
keys. The formal failure type is `DatasetCatalogCLIError`, a subclass of
`DatasetCatalogError`.

## 18. Settings-independent dispatch

The four Catalog commands are settings-independent, exactly like the
Dataset commands and the Sample Generation CLI: they never load
settings.yaml, never connect to OpenD, and never access the network.
The top-level `market-vault` parser dispatches
`DATASET_CATALOG_COMMANDS` **before** `load_settings(args.settings)`, so
a missing or invalid settings file can never block a Catalog command.
The commands never resolve a default Dataset root, never scan for a
`latest` snapshot, and never consult environment variables.

## 19. `dataset-catalog-build`

```text
market-vault dataset-catalog-build
    --dataset-root <PATH>
    | (--candidate-build-dir <PATH> repeated)
    --output-root <PATH>
    --built-at <ISO8601>
```

- **Exactly one candidate mode.** `--dataset-root` and repeated
  `--candidate-build-dir` are mutually exclusive; exactly one must be
  given (argparse exit 2 otherwise). `--candidate-build-dir` must be
  given at least once; candidate input order never matters.
- **`--output-root`** is required and explicit; the committed snapshot
  is `<output_root>/<snapshot_id>`.
- **`--built-at`** is required and must be a timezone-aware ISO 8601
  instant; a naive datetime or an empty value is an argparse error
  (exit 2). The CLI never supplies the current time — `datetime.now()`
  is never used.
- **CLI path boundary.** Every CLI path is coerced lexically: `.` and
  `..` lexical components are rejected before `Path` construction as a
  formal CLI path-validation failure (exit 1); a relative path is made
  lexically absolute against `Path.cwd()`, and `resolve()` /
  `expanduser()` / `expandvars()` / globbing / scanning are never used
  by the CLI. The builder's absolute-input contract is unchanged: the
  CLI completes relative inputs at the CLI boundary only, and the
  formal builder functions still receive lexically absolute paths.
- **Forbidden options.** The build command never accepts `--latest`,
  `--force`, `--overwrite`, `--repair`, or any repair / overwrite /
  latest pointer flag: there is no latest pointer and no snapshot is
  ever repaired or overwritten.
- **Idempotency.** A second identical build against the same
  `output_root` and the same explicit `built_at` verifies the existing
  final snapshot and returns `created_new_snapshot = false` with zero
  rewrites and zero mtime touches; the output root is never modified in
  that case.
- **Success JSON** (stdout, exit 0): the fixed result envelope with
  `command` `dataset-catalog-build`, `result` `SUCCESS`, and the facts
  of the final verified snapshot — `created_new_snapshot` (the one fact
  from the materialization result), `snapshot_id`,
  `catalog_content_id`, `dataset_count`, `snapshot_path` (lexical
  forward-slash text), `built_at` (UTC microseconds),
  `builder_version`, `materializer_version`, and
  `reader_contract_version`.
- An empty Catalog (empty root or zero candidates) is a legal build and
  exits 0; it is never an error.

## 20. `dataset-catalog-verify`

```text
market-vault dataset-catalog-verify --snapshot-dir <PATH>
```

`--snapshot-dir` is the only option: one explicit final snapshot
directory. The command runs the full verified reader
(`load_verified_dataset_catalog`) and prints a summary only — it never
carries entries. The success JSON (stdout, exit 0) has `result`
`VERIFIED` with the same snapshot facts as the build success payload
minus `created_new_snapshot`. Any corruption of the snapshot — missing
artifacts, extra files, non-empty `_SUCCESS`, hash / byte-size /
identity mismatches, symlinked artifacts — is a formal failure (exit 1,
stderr JSON); the snapshot itself is never modified.

## 21. `dataset-catalog-list`

```text
market-vault dataset-catalog-list
    --snapshot-dir <PATH>
    [--status COMPLETE|EMPTY]
    [--dataset-kind <TEXT>]
    [--symbol <TEXT>]
    [--trade-date YYYY-MM-DD]
    [--interval <TEXT>]
    [--adjustment <TEXT>]
    [--requested-session <TEXT>]
    [--offset N] [--limit N]
```

- **Read-only query boundary.** The list command loads one verified
  snapshot through `load_verified_dataset_catalog` and filters
  `verified.entries` purely in memory. It never re-reads
  `catalog.json` / `manifest.json`, never stats or scans the snapshot,
  never calls `load_verified_dataset`, never touches the recorded build
  paths (historical text), never uses DuckDB, SQL, pandas, or the
  network, and never writes anything.
- **Filter semantics.** `--status`, `--dataset-kind`, `--interval`,
  `--adjustment`, and `--requested-session` are exact equality against
  the stored facts; `--symbol` is membership in `scope.symbols`;
  `--trade-date` is strict `YYYY-MM-DD` membership in
  `scope.trade_dates`. There is no case folding and no substring
  matching. A stored `None` `requested_session` never matches a string
  filter. All provided filters are combined with **AND semantics**.
- **Pagination.** `--offset` defaults to 0, `--limit` defaults to 20;
  `--limit 0` is legal (returns no entries); `--limit` above 1000 or a
  negative `--offset` / `--limit` is an argparse error (exit 2). The
  page is a slice of the filtered list: the underlying order stays
  `dataset_id`-ascending and is never reordered.
- **Success JSON** (stdout, exit 0): the fixed envelope with `result`
  `LISTED`, the fixed `filters` object (every filter key always present,
  unused filters `null`, `trade_date` as strict `YYYY-MM-DD`),
  `matched_count`, `offset`, `limit`, `returned_count`, and `datasets` —
  each item is the discovery summary (dataset_id, content_id,
  dataset_kind, status, logical_row_count, dataset_as_of, scope,
  recorded_built_at, recorded_build_path). The full facts record with
  the nested pins belongs to `dataset-catalog-show` only.
- An empty snapshot or a zero-match filter result is a legal empty page
  and exits 0.

## 22. `dataset-catalog-show`

```text
market-vault dataset-catalog-show
    --snapshot-dir <PATH>
    --dataset-id <64-hex>
```

`--dataset-id` must match the strict pattern `^[0-9a-f]{64}$` (argparse
exit 2 otherwise — uppercase, short, long, or non-hex ids are rejected
before any snapshot access). The command performs an exact
`dataset_id` lookup in `verified.entries`; a missing id is a formal
failure (exit 1, stderr JSON) with an empty stdout. The success JSON
(stdout, exit 0) carries the complete lossless record for that one
entry: the full 14-field `dataset_facts` (dataset_id, dataset_kind,
status, logical_row_count, dataset_schema_id,
logical_dataset_content_id, dataset_as_of, scope, feature_spec_pins,
label_spec_pins, split_spec_pin, canonical_build_pins,
canonical_row_version_ids, completion) with every nested pin
(`SpecPin`, `SourceSnapshotPin`, `CanonicalBuildPin`,
`CompletionSummary`, `CompletionEntry`) serialized with its formal
fields, plus `content_id` and `observed_metadata`. The
`observed_metadata` contains `built_at` (UTC microseconds) and
`build_path` — the **historical recorded location text**. The typed
reader model names these fields `recorded_built_at` /
`recorded_build_path`; the CLI presentation schema maps them to
`built_at` / `build_path`. The recorded build path is never resolved,
never stat'ed, never checked for existence, and never passed to
`load_verified_dataset`. Show never accesses the original Dataset
directories. The `dataset` object is a lossless typed presentation of
the verified snapshot entry: every formal entry fact is preserved.
CLI presentation bytes are governed by the PR-7 result JSON contract
and are not claimed to be byte-identical to the canonical
`catalog.json` artifact bytes.

## 23. Deterministic JSON output

Every CLI JSON result is deterministic:

- UTF-8 text with `ensure_ascii=False`, `indent=2`, and a trailing
  newline;
- fixed key insertion order fixed by the contract of each result type;
- no current-time or machine-derived facts: `built_at` values always
  come from the verified snapshot's recorded explicit instants
  (UTC microseconds), and paths are the snapshot's recorded lexical
  text;
- identical inputs always produce byte-identical output on every
  platform.

The CLI never uses `datetime.now()`, `datetime.utcnow()`, or
`time.time()`.

## 24. Exit-code contract (exit 0 / 1 / 2)

```text
exit 0   a single success JSON on stdout; stderr stays empty
exit 1   a single failure JSON on stderr; stdout stays empty
exit 2   argparse-level errors (unknown options, missing required
         options, invalid argument values, forbidden combinations)
```

The failure JSON (stderr) has the fixed shape:

```json
{
  "result_schema_version": "market-vault-dataset-catalog-cli-result-v1",
  "cli_contract_version": "market-vault-dataset-catalog-cli-v1",
  "command": "<the failing command>",
  "result": "FAILED",
  "error_type": "DatasetCatalogCLIError",
  "error": "<message>"
}
```

Documented failures — `DatasetCatalogError` (including every
`DatasetCatalogBuildError`, `DatasetCatalogMaterializationError`, and
`DatasetCatalogArtifactValidationError`), `OSError`, `UnicodeError`,
`TypeError`, `ValueError`, and `KeyError` — are converted to
`DatasetCatalogCLIError` at the CLI boundary with the `__cause__`
preserved and never double-wrapped. Real programming errors
(`AssertionError`, `RuntimeError`, and everything else) are never
swallowed and never converted.

## 25. Read-only query boundary and non-goals

- verify / list / show are strictly read-only: they never write,
  delete, repair, or rewrite anything, never follow the **historical**
  recorded build path, and never verify the original Datasets still
  exist.
- There is no latest pointer, no implicit snapshot selection, and no
  auto-repair; a corrupt snapshot fails closed and stays untouched.
- The CLI never references the legacy Catalog
  (`market_vault.storage.catalog.Catalog`), never creates DuckDB
  tables or views, and `init-catalog` remains the legacy ingestion
  catalog command.
- The CLI never changes Dataset identity, Canonical identity, or any
  PR-5 / PR-6 Catalog identity.
- The Python Client is a v0.7 direction and is not part of v0.6.0;
  PR-8 integrated acceptance completed in PR #42.
