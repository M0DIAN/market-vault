# Derived Dataset Manifest Contract

Status: implemented in the v0.4.0 dataset manifest/identity core
(`market_vault.dataset`).

This contract defines the deterministic identity and manifest foundation for
derived datasets: the explicit logical Dataset schema model,
`dataset_schema_id`, deterministic logical content hashing, canonical-build
provenance pins, Feature/Label/Split/Transform fingerprints, scope and
`dataset_as_of` normalization, completion and gap references, the versioned
Dataset manifest, deterministic serialization, strict validation, and atomic
standalone manifest writing. Related decisions are in
[ADR 0001](../adr/0001-canonical-ml-dataset-boundary.md); the Canonical
materialization contract is
[canonical_market_bar_materialization.md](canonical_market_bar_materialization.md).

This PR does **not** assemble market samples, compute features or labels,
parse Feature/Label spec files, assign train/validation/test splits, purge by
actual label end, export Dataset Parquet, read canonical bar Parquet for
sample generation, filter Canonical rows by `dataset_as_of`, create DuckDB
views, add CLI commands, or train models.

## 1. Manifest authority

The **Canonical manifest** (`canonical-market-bars-manifest-v1`) remains the
authority describing one immutable Canonical build and its physical files.
The **Dataset manifest** (`market-vault-dataset-manifest-v1`) is a separate,
versioned manifest describing one derived dataset build. The Dataset manifest
never reuses the Canonical manifest schema version, never replaces the
Canonical manifest as the Canonical authority, and never treats exported
Dataset files as a source of truth. The Dataset layer only **references**
immutable Canonical builds and their stable identities; it never mutates or
repairs them, and it never reinterprets the V0.3 COMPLETE gate (that gate
stays exactly as Canonical defines it).

Export semantics: exported Dataset Parquet files (future PR) are immutable
build artifacts, not another source-of-truth storage layer. A dataset is never
authoritative input to another dataset build.

## 2. Logical content identity versus file byte hashes

- **`logical_dataset_content_id`**: versioned SHA-256 over deterministic
  logical Dataset content (the schema ID and every logical row encoded under
  that schema). It never depends on row order, Parquet byte layout, file
  size, serializer metadata, output paths, or local timezone.
- **Output file byte hashes**: recorded facts in the manifest; they never
  enter `dataset_id`.

Cross-version byte-identical Parquet output is **not** promised: identical
logical contents can serialize to different bytes across serializer versions
or writer options. The logical identities are the authority. This ID
describes logical content only.

## 3. Explicit logical Dataset schema

`DatasetSchema` is a frozen tuple of `DatasetField(name, logical_type,
nullable)`. Field order is authoritative and participates in
`dataset_schema_id`. Only the explicit initial scalar type set is supported:

- `string`
- `int64`
- `float64`
- `bool`
- `date32`
- `timestamp_us_utc`

Rules: duplicate field names are rejected; names must be non-empty strings
without control characters or encoding separators, NFC-normalized; `nullable`
must be a real bool; no inferred schema; no object/JSON/list/map values yet;
no timezone other than UTC for `timestamp_us_utc`; missing values are `null`,
never NaN; float NaN and positive/negative infinity are rejected; negative
zero normalizes to ordinary zero; bool is never accepted as int64; datetime
values must be timezone-aware and are normalized to UTC; timestamp precision
is truncated to microseconds; `date32` accepts `date` but rejects `datetime`
unless deliberately converted before calling the identity layer.

## 4. `dataset_schema_id`

`dataset_schema_id` is a versioned SHA-256 over the ordered field names,
ordered logical types, ordered nullability flags, and the schema identity
version (`DATASET_SCHEMA_ID_VERSION = "dataset-logical-schema-v1"`). Changing
field order, type, name, or nullability changes the schema ID. Equivalent
Python object construction order outside the fields tuple never matters.

## 5. `logical_dataset_content_id`

Versioned SHA-256 over `dataset_schema_id` and every logical row encoded
under that exact schema, preserving row multiplicity:

- each row must contain exactly the schema fields (no missing, no unknown);
- non-nullable fields reject null;
- values must match the declared logical type;
- strings are not stripped or case-folded (but control characters and
  encoding separators fail);
- timestamps normalize to the same UTC microsecond instant;
- float NaN/Infinity fail closed;
- duplicate logical rows remain duplicate rows and affect the hash.

Row order is irrelevant: each row contributes one digest, and the digests are
sorted with duplicates preserved. Therefore reversing rows does not change
the ID; adding or removing one duplicate row does change it; equivalent
timezone representations of one instant do not change it; changing one value,
null state, field order, type, or nullability does change it. Zero-row
content has a deterministic, request-independent content ID tied to its
schema.

## 6. Canonical build and source pins

`CanonicalBuildPin` pins one immutable Canonical build: `canonical_build_id`,
`canonical_content_id`, `canonical_builder_version`,
`canonical_schema_version`, `materializer_version`, `gap_policy_version`,
`gap_content_id`, `status` (COMPLETE or EMPTY only), ordered
`canonical_row_version_ids`, and `source_snapshots`
(`SourceSnapshotPin`: `ingestion_run_id`, `physical_snapshot_hash`,
`logical_source_rows_hash`, `source_schema_version`, `requested_trade_date`,
`requested_session`).

Rules: paths (`snapshot_file`, build paths) and `created_at` are excluded;
all SHA-256 values are normalized to lowercase 64-character hex; canonical
row-version IDs are deduplicated and sorted; source snapshot pins are
deduplicated by stable identity and deterministically sorted; an EMPTY
Canonical pin must have zero row-version IDs. The caller constructs pins from
a previously verified Canonical manifest; filesystem verification and PIT row
loading happen in the later sample-assembly PR.

## 7. Feature/Label/Split/Transform fingerprints

`SpecPin(kind, name, version, content_sha256)` with kind
FEATURE | LABEL | SPLIT, and `ImplementationPin(name, version,
content_sha256 | None)`. Identifiers are non-empty normalized strings; hashes
are lowercase 64-character SHA-256; ordering is deterministic; duplicate
(kind, name, version) spec entries and duplicate (name, version)
implementation entries fail closed. No Feature/Label YAML syntax is defined
and no transform is executed by this PR. Empty Feature/Label/Split lists are
allowed so the low-level identity core can be tested before the spec
framework lands; the future real dataset builder must populate the pins
required by its dataset contract.

## 8. Scope and `dataset_as_of`

`DatasetScope` is normalized at construction: symbols strip + uppercase +
deduplicate + sort; trade dates validate as date + deduplicate + sort;
interval strip + lowercase; `adjustment` and `requested_session` strip +
uppercase; empty scope fails; unsafe/control characters fail. An optional
`dataset_as_of` must be timezone-aware, is normalized to UTC microseconds,
and participates in `dataset_id`. In this PR it is a **recorded cutoff only**:
no Canonical rows are filtered by `archive_available_at`.

## 9. Completion and gap references

`CompletionSummary` records `complete_count`, `incomplete_count`,
`missing_count`, and ordered per-key entries
(`code`, `trade_date`, `status`: COMPLETE | INCOMPLETE | MISSING, optional
stable `reason_code`). Counts must equal the actual entries; duplicate
(code, trade date) keys fail; ordering is canonical; unknown statuses fail;
reasons are stable codes, not free-form stack traces.

`GapReference(canonical_build_id, gap_content_id, gap_range_count)` records
ordered references to pinned Canonical gap sidecars. Each reference must name
a pinned build and agree with that build's `gap_content_id`; identical
duplicate references are deduplicated. Gap Parquet contents are never
duplicated into the Dataset manifest.

## 10. Deterministic `dataset_id`

`dataset_id` is a versioned SHA-256 over all identity-bearing normalized
fields of `DatasetIdentityInput`:

1. `dataset_kind`;
2. normalized `DatasetScope`;
3. optional normalized `dataset_as_of`;
4. `logical_dataset_content_id`;
5. `dataset_schema_id`;
6. ordered `CanonicalBuildPin`s (build ID, content ID, builder/schema/
   materializer/gap-policy versions, gap content ID, status, row versions,
   source snapshot identities);
7. explicitly pinned `canonical_row_version_ids`;
8. Feature spec pins;
9. Label spec pins;
10. optional Split spec pin;
11. implementation pins;
12. completion summary;
13. gap references;
14. manifest schema version;
15. serialization format and serialization format version;
16. the identity encoding version (`v1`).

`dataset_id` changes when any of these change: logical content; output
logical schema or field order; Canonical build/content/row version; source
physical snapshot identity; Feature/Label/Split spec content hash; transform
implementation version/hash; `dataset_as_of`; scope; completion state; gap
content reference; manifest schema version; serialization format/version;
identity encoding version.

`dataset_id` never depends on: `built_at`; output directories; manifest file
paths; Canonical `snapshot_file`; Canonical build paths; generated Parquet
file paths; Parquet byte hashes; local timezone; input list order; dictionary
insertion order.

Inconsistent inputs fail closed: a row-version ID not covered by the pinned
Canonical builds; duplicate Canonical build IDs (identical or conflicting);
duplicate specs or implementations; invalid hashes; naive `dataset_as_of`;
`dataset_schema_id` that does not match the declared schema; gap references
that disagree with their pinned build.

## 11. Dataset manifest

`DatasetManifest` is frozen and carries: `manifest_schema_version`,
`dataset_id`, `dataset_kind`, `status` (COMPLETE | EMPTY), `built_at` (UTC),
`dataset_as_of` (UTC or null), `logical_dataset_content_id`,
`dataset_schema_id`, schema fields in authoritative order, normalized scope,
Canonical build pins, canonical row-version IDs, Feature/Label spec pins,
Split spec pin or null, implementation pins, completion summary, gap
references, serialization format and version, `logical_row_count`, and
`output_files`.

- `output_files` may be empty in this core PR; no Dataset Parquet writer
  exists; output file byte hashes never enter `dataset_id`.
- status EMPTY requires `logical_row_count == 0`; status COMPLETE requires at
  least one logical row (zero rows must be EMPTY).
- `built_at` must be timezone-aware and is normalized to UTC; it never
  enters `dataset_id`.
- `build_dataset_manifest` independently recomputes `dataset_id` from the
  identity-bearing fields and never trusts a caller-supplied `dataset_id`.

`DatasetOutputFile(relative_path, file_role, row_count, byte_size, sha256,
content_role)` is the future-compatible immutable output record: safe
relative POSIX paths only (no absolute paths, backslashes, ".", "..", empty
components, control characters, or duplicates); non-negative integer counts
(bools rejected); lowercase 64-character hex SHA-256; records sorted
deterministically. File hashes are recorded facts, excluded from
`dataset_id`; no actual filesystem bytes are validated because no Dataset
artifact writer exists yet.

## 12. Deterministic serialization and strict validation

`serialize_dataset_manifest` produces deterministic UTF-8 JSON: sorted keys,
compact separators, `ensure_ascii=True` (fixed and documented), stable list
ordering, UTC microsecond ISO timestamps, trailing newline.

`validate_dataset_manifest` strictly validates a payload (bytes, str, or
already-parsed object): missing and unknown top-level fields fail; nested
record shapes are validated; `dataset_schema_id` is recomputed from the
declared schema; logical constraints are recomputed (completion counts,
status/count invariants, duplicate pins and output paths); `dataset_id` is
recomputed from the identity-bearing fields and must equal the stored value.

Round-tripping `manifest -> deterministic JSON -> validated manifest`
preserves every logical field and identity.

## 13. Atomic standalone manifest writing

`write_dataset_manifest_atomic(path, manifest, *, idempotent=False)`:

- the parent directory may be created deliberately;
- the payload is serialized before the destination is touched;
- a unique temporary sibling file is written, flushed, and closed;
- `os.replace` performs the atomic same-filesystem replacement;
- temporary files are cleaned after exceptions;
- an existing destination is refused by default;
- `idempotent=True` accepts an existing byte-identical manifest and never
  silently replaces different content;
- the destination is never partially overwritten on failure.

This helper writes exactly one manifest file. It does not commit a Dataset
build directory and does not create `_SUCCESS`.

## 14. Why output-file hashes do not enter `dataset_id`

Output file byte hashes are recorded facts of a particular physical
materialization. Identical logical content can serialize to different bytes
across serializer versions, writer options, compression, or file layout, and
a byte change (e.g. compression metadata) carries no logical meaning. If byte
hashes entered `dataset_id`, rebuilds of identical logical content would
produce different dataset IDs. The logical identities are the authority, so
output file facts are recorded but never identity-bearing.

## 15. Why exported Dataset files are derived artifacts

Rebuilding a dataset from the same inputs must reproduce the same logical
content and the same `dataset_id`. Exported Dataset Parquet files are
immutable build artifacts produced by the future builder; they are never
treated as authoritative input to another dataset build. The Canonical layer
remains the only new source-of-truth materialized data layer; the Dataset
manifest describes a derived build, not a storage layer.
