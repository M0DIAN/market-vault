# Dataset Catalog Boundary Contract

Status: planned contract boundary; not implemented in v0.5.1
Target release: v0.6.0

This document fixes the high-level contract boundary for the immutable
Dataset Catalog planned for v0.6.0. It is a boundary contract only: no
Dataset Catalog production code exists, and this document does not invent
the final schema fields. The precise Catalog schema, identity, and physical
layout are defined by the v0.6.0 Dataset Catalog contract PR (PR-5).

## 1. Distinction from the legacy Catalog

The new Dataset Catalog layer is fully independent of the existing
`market_vault.storage.catalog.Catalog`:

- the legacy Catalog keeps its responsibilities: ingestion runs, quality
  results, snapshot views, the trading calendar, and Raw / Curated
  queries, backed by DuckDB views;
- the new Dataset Catalog indexes verified immutable Dataset builds:
  Dataset discovery, Dataset metadata filtering, and Catalog snapshot
  verification;
- the new Catalog never reuses the legacy Catalog's tables, schema, or
  identity, and `init-catalog` remains the legacy ingestion catalog
  command.

## 2. Candidate trust

- every candidate must pass `load_verified_dataset`;
- a manifest is never trusted directly;
- partial staging is never read;
- a build without `_SUCCESS` is never accepted;
- symlink / junction / reparse-point candidates are never accepted;
- corrupted builds are never repaired;
- any conflict among the formal candidates fails closed.

## 3. Indexed facts

The future Catalog may index the following verified facts (high-level
list; the exact schema is determined by PR-5):

```text
dataset_id
status
logical_row_count
dataset_schema_id
logical_dataset_content_id
built_at
dataset_as_of
scope
feature spec pins
label spec pins
split spec pin
canonical build pins
completion summary
build path/location metadata
```

## 4. Identity

- the Catalog has its own versioned identity;
- a Dataset path never enters Dataset identity;
- Catalog identity never enters Dataset identity;
- the same verified Dataset set under the same Catalog contract produces
  the same Catalog content identity;
- whether `built_at` and the physical output directory enter Catalog
  identity is decided by PR-5, but they must never pollute Dataset
  identity;
- a duplicate `dataset_id` with conflicting metadata fails closed.

## 5. Materialization

The future Catalog snapshot must be:

- immutable;
- written through staging;
- `_SUCCESS` written last;
- committed by a no-overwrite atomic rename;
- readable only through a verified Catalog reader;
- rebuild-identical idempotently;
- fail closed on a conflicting final;
- never based on `latest`; no latest is ever implicit.

## 6. Query

Future Catalog query must:

- read an explicit Catalog snapshot;
- be strictly read-only;
- use deterministic ordering;
- never modify a Dataset;
- never auto-rebuild the Catalog;
- never auto-scan parent directories.
