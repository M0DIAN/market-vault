# Dataset Catalog Contract (v0.6.0 PR-5)

Status: Dataset Catalog contract, frozen models, metadata projection, and
Catalog content identity implemented; the Catalog snapshot builder,
materializer, verified reader, and query CLI are not implemented (PR-6 /
PR-7)
Target release: v0.6.0
Not available in released v0.5.1. The Dataset Catalog is not implemented in v0.5.1.

This document is the precise formal contract of the PR-5 Dataset Catalog
contract layer. It fixes the exact Catalog entry schema, the structural
split between content facts and non-content metadata, the versioned
Catalog content identity and its normalization rules, the duplicate /
conflict policy, the trust boundary of the metadata projection, and the
fail-closed validation rules. It also fixes what PR-5 deliberately does
not implement: PR-6 (the immutable Catalog snapshot builder, materializer,
and verified reader) and PR-7 (the Catalog query CLI).

The PR-5 production modules are:

```text
src/market_vault/dataset/dataset_catalog_models.py
src/market_vault/dataset/dataset_catalog_identity.py
src/market_vault/dataset/dataset_catalog_projection.py
```

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
- PR-5 defines no DuckDB table, no view, no directory layout, and no
  filesystem snapshot: those belong to PR-6.

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
  scans the filesystem; the future PR-6 builder is responsible for
  calling the verified reader on every candidate and passing the verified
  builds into this projection;
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
manifest identity contract. No other manifest facts are copied into the
Catalog record: `implementations`, `gap_references`,
`manifest_schema_version`, `serialization_format`, and `serialization_format_version`
remain Dataset-internal build facts and are not indexed.

### 3.2 `DatasetCatalogObservedMetadata` (non-content metadata)

```text
built_at       # UTC microsecond instant
build_path     # lexically absolute Path of the verified build directory
```

These facts are recorded for observability only. The type is structurally
disjoint from `DatasetCatalogDatasetFacts` — no field name is shared — so
the metadata can never be accidentally mixed into the content identity.
The two types are structurally disjoint by construction: no field of the
observed-metadata type exists on the facts type.

### 3.3 `DatasetCatalogEntry` (projection)

```text
dataset_facts        # DatasetCatalogDatasetFacts
observed_metadata    # DatasetCatalogObservedMetadata
content_id           # 64-char lowercase SHA-256, recomputed and
                     #   self-validated at construction
```

The entry combines the two without making the metadata identity-bearing:
`content_id` is recomputed from `dataset_facts` only at construction, so
`dataclasses.replace` tampering (a substituted content ID, substituted
facts, or substituted metadata) fails closed.

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

Normalization is deterministic and happens at the formal boundaries:

- every SHA-256 field is normalized to lowercase 64-hex;
- every sequence (scope symbols / trade dates, spec pins, canonical build
  pins, canonical row-version IDs, completion entries) is sorted and
  deduplicated at construction, so input order never matters;
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

PR-5 defines no separate materialization or snapshot identity: physical
Catalog snapshot identity is deferred to PR-6. Whatever PR-6 defines,
physical metadata never flows into the Catalog content identity and never
changes an indexed Dataset.

## 6. Fail-closed validation

The frozen models fail closed at construction on:

```text
invalid SHA-256 IDs
unsupported status
negative / non-real counts
wrong pin kinds
duplicate conflicting pins / facts
scope inconsistency (completion entries outside the scope)
canonical row-version coverage loss
malformed / non-UTC datetimes
mutable / untyped payloads
content ID mismatch
unsupported contract or entry schema versions
```

`DatasetCatalogError` (a subclass of `DatasetError`) is the unified
failure type. Low-level documented validation exceptions are converted to
it; `AssertionError` / `RuntimeError` and other programming errors are
never swallowed.

## 7. Not implemented by PR-5 (PR-6 / PR-7)

PR-5 does not implement any of the following; they remain PR-6 / PR-7
work:

```text
Dataset Catalog builder
directory scanning / candidate discovery
Catalog snapshot filesystem materialization
staging / atomic rename / _SUCCESS
verified Catalog reader
verify / list / show / query CLI
```

The future Catalog snapshot will still be immutable, written through
staging with `_SUCCESS` written last, committed by a no-overwrite atomic
rename, readable only through a verified reader, rebuild-identical
idempotently, fail-closed on a conflicting final, and never based on
`latest`; no latest is ever implicit.

## 8. Version constants

```text
DATASET_CATALOG_CONTRACT_VERSION     = market-vault-dataset-catalog-contract-v1
DATASET_CATALOG_ENTRY_SCHEMA_VERSION = market-vault-dataset-catalog-entry-v1
DATASET_CATALOG_CONTENT_ID_VERSION   = market-vault-dataset-catalog-content-v1
```

Changing a version constant changes every Catalog identity that
references it; it never changes any Dataset or Canonical identity.
