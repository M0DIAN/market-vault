# Canonical Market-Bar Materialization Contract

Status: implemented in the v0.4.0 canonical materialization layer.

This contract defines the immutable canonical build format produced by
`market_vault.canonical.materialization`. Related decisions are in
[ADR 0001](../adr/0001-canonical-ml-dataset-boundary.md); timestamp semantics
are pinned by [market_bar_timestamp_semantics.md](market_bar_timestamp_semantics.md).

## 1. Immutable build layout

```text
data/canonical/
  dataset=market_bars_canonical/
    build_id=<canonical_build_id>/
      bars/
        interval=<interval>/adjustment=<adjustment>/code=<code>/
          market_calendar_date=<date>/part-00000.parquet
      gaps/
        interval=<interval>/adjustment=<adjustment>/code=<code>/
          market_calendar_date=<date>/part-00000.parquet
      resolution.jsonl
      manifest.json
      _SUCCESS
```

- Final build directories are immutable and never overwritten.
- All paths inside `manifest.json` are relative to the build root.
- Partition values are validated (no path traversal, separators, control
  characters, or unsafe values); partition ordering and file naming are
  deterministic. One file per logical partition is used in this version.
- There is no mutable `latest.json` and no DuckDB registration yet.

## 2. Explicit Canonical Parquet schema

`CANONICAL_SCHEMA_VERSION = "market-bars-canonical-schema-v1"` and
`CANONICAL_MATERIALIZER_VERSION = "market-bars-materializer-v1"` are declared
in `market_vault.canonical.schema`. The bars table uses an explicit PyArrow
schema in fixed column order:

- `canonical_bar_key`, `canonical_row_version_id`, `dataset_kind`, `code`,
  `interval`, `adjustment`: string
- `event_time`, `market_available_at`, `archive_available_at`:
  `timestamp[us, tz=UTC]`
- `open`, `high`, `low`, `close`: `float64`
- `volume`: `float64`
- `turnover`, `last_close`, `change_rate`, `pe_ratio`, `turnover_rate`:
  nullable `float64` (absent source fields become null, never fabricated)
- `ingestion_run_id`, `physical_snapshot_hash`, `logical_source_rows_hash`,
  `source_schema_version`, `canonical_builder_version`: string
- `requested_trade_date`, `market_calendar_date`: `date32`
- `requested_session`, `session`, `snapshot_file`: string

Row order inside every partition is deterministic: `event_time` ASC, then
`canonical_bar_key` ASC. Reading the Parquet preserves the same instants and
logical values. Byte-identical Parquet across unpinned serializer versions is
not promised.

## 3. Logical identities versus physical file hashes

- **Physical file hash**: SHA-256 of the complete physical snapshot file
  bytes; preserves exact file-byte identity.
- **`canonical_content_id`**: versioned SHA-256 over deterministic logical
  Canonical Bar contents — all authoritative logical row fields and canonical
  identities, excluding `created_at`, output paths, Parquet byte layout, file
  size, serializer metadata, and `snapshot_file` (movable descriptive
  provenance). Equivalent logical rows in different input orders or timezone
  displays produce the same ID.
- **`resolution_content_id`**: path-independent hash of resolution semantics
  (canonical_bar_key, selected and discarded stable source identities);
  `snapshot_file` never influences it.
- **`gap_content_id`**: hash of generated gap sidecar rows plus the
  gap-policy version.
- **`canonical_build_id`**: versioned SHA-256 over the normalized request,
  the three content IDs, selected `canonical_row_version_id`s, builder,
  schema, materializer, and gap-policy versions. It never depends on input
  order, local machine timezone, snapshot path relocation, generated file
  paths, Parquet byte hashes, or `created_at`. Changing the builder, schema,
  materializer, gap policy, selected physical source, or logical contents
  changes the build ID.

Why Parquet byte identity is not the dataset identity: identical logical
contents can serialize to different bytes across serializer versions or
writer options, and a byte change (e.g. compression metadata) carries no
logical meaning. The logical identities above are the authority.

## 4. Atomic commit protocol

1. create a unique temporary sibling directory on the same filesystem;
2. write bars;
3. write gaps;
4. write `resolution.jsonl`;
5. calculate actual file byte hashes;
6. write `manifest.json`;
7. write `_SUCCESS` last;
8. atomically rename the complete temporary directory to the final path.

Temporary directories are cleaned after exceptions; a partially committed
final build never appears; existing committed builds are never modified.

## 5. Idempotency

When the deterministic final build directory already exists:

- `manifest.json` and `_SUCCESS` are required;
- the manifest schema and `canonical_build_id` are validated;
- recorded file hashes are validated against actual bytes;
- the call returns an idempotent existing-build result
  (`created_new_build=False`) without rewriting anything.

An existing directory that is incomplete or conflicts with the expected
build identity fails closed.

## 6. EMPTY builds

A request with zero COMPLETE snapshots produces `status = EMPTY`: zero bars,
zero gaps, zero resolution rows, no bars/gaps Parquet files, a deterministic
request-specific `canonical_build_id`, `manifest.json`, and `_SUCCESS`. EMPTY
is never confused with COMPLETE data coverage; the request scope participates
in the build ID so different empty requests do not collapse into one build.

## 7. Manifest authority

`MANIFEST_SCHEMA_VERSION = "canonical-market-bars-manifest-v1"`. The manifest
records status, dataset kind, all logical identities, builder/schema/
materializer/gap-policy versions, `created_at` (UTC), the normalized request,
counts, time ranges, ordered source snapshot provenance, ordered output file
records (relative_path, file_role, row_count, byte_size, sha256, content
role), and the documented gap-policy limitations. JSON serialization is
deterministic: UTF-8, sorted keys, stable list ordering, compact separators,
trailing newline. `created_at` and observed file byte hashes are recorded
facts and never enter `canonical_build_id`. The manifest and its referenced
files together are the immutable build artifact.

## 8. Gap-policy limitations

The gap sidecar reports internal nominal spacing gaps only: adjacent observed
Canonical bars within the same (dataset_kind, code, interval, adjustment,
market_calendar_date, session) group whose delta is greater than one nominal
interval and an exact interval multiple. It never emits synthetic bars, never
infers missing bars before the first or after the last observed bar, never
infers cross-session or cross-date gaps, never judges whether the exchange was
officially open, early-close boundaries, or full-session completeness. An
adjacent delta that is not an exact interval multiple fails closed with a
structured materialization error.
