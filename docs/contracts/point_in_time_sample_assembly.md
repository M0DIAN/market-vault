# Point-in-Time Sample Assembly Contract

Status: implemented in the v0.4.0 two-clock point-in-time sample assembly
foundation (`market_vault.canonical.reader` and `market_vault.dataset.pit`).

This contract defines the verified read path for immutable Canonical build
artifacts and the deterministic assembly of point-in-time samples: binding
Canonical rows to explicit Feature/Label observation windows under the market
clock and the optional archive clock, reconciling candidates across builds,
and recording the sample-to-row association in a fixed logical content
contract. Related decisions are in
[ADR 0001](../adr/0001-canonical-ml-dataset-boundary.md); timestamp semantics
are pinned by [market_bar_timestamp_semantics.md](market_bar_timestamp_semantics.md);
the Canonical materialization contract is
[canonical_market_bar_materialization.md](canonical_market_bar_materialization.md);
the Dataset manifest/identity core is
[derived_dataset_manifest.md](derived_dataset_manifest.md).

This PR does **not** compute Feature or Label values, parse Feature/Label
spec files, assign splits, purge by actual label end, export Dataset Parquet,
build a Dataset build directory or its `_SUCCESS`, build the final
DatasetManifest, create CLI commands, create DuckDB views, call OpenD, access
the network, or train models. No Raw / Curated data is modified, no Canonical
build is written or repaired, and the package version and dependencies are
unchanged.

## 1. The two clocks

Every Canonical row carries two availability instants in addition to
`event_time`:

- **`market_available_at`** (market clock): the earliest instant the complete
  bar could have been known on the market clock (`event_time + interval`,
  exact for full-interval bars, otherwise a conservative not-before bound).
  This is the clock point-in-time feature assembly uses to decide whether a
  row could have been observed at a feature window close.
- **`archive_available_at`** (archive clock): the instant the source snapshot
  became available inside MarketVault (`run_finished_at`). Archive-as-of
  reconstruction additionally uses this clock.

An optional **`dataset_as_of`** selects archive-time reproducibility: a row
may only be consumed when `archive_available_at <= dataset_as_of`, so a later
re-collection cannot change the assembled content.

## 2. Verified Canonical build reader

`load_verified_canonical_build(build_dir)` is the only public read path into
committed Canonical build artifacts. It returns a frozen
`VerifiedCanonicalBuild` carrying the manifest identities and versions, the
normalized request, the reconstructed canonical rows, the row-version set,
typed source provenance, gap ranges and count, the raw manifest payload, and
the build path (descriptive metadata only, never identity-bearing).

Verification is strict and fail-closed; any inconsistency raises
`CanonicalArtifactValidationError`, and low-level `OSError`,
`UnicodeDecodeError`, JSON, PyArrow, hash, or identity exceptions are never
part of the public contract:

1. the build directory, `manifest.json`, and `_SUCCESS` must exist;
2. the manifest, `_SUCCESS`, every output file, and every path component may
   not be a symlink (or Windows junction);
3. `manifest_schema_version` must be the current Canonical manifest version,
   `dataset_kind` and `gap_policy_limitations` must match the contract, and
   unknown top-level manifest fields fail;
4. the build directory name must carry the manifest `canonical_build_id`;
5. `status` may only be COMPLETE or EMPTY and must agree with the actual row
   count; EMPTY builds must have zero bars, zero resolution entries, zero
   source snapshots, and null timestamp ranges;
6. every `output_files` record is checked for exact fields, safe relative
   paths (no absolute paths, backslashes, ".", ".."), matching file role and
   path, actual byte size, actual SHA-256, and actual row count (Parquet
   metadata / JSONL lines);
7. bars Parquet schemas must exactly equal `canonical_bars_schema()`
   (column order and types fixed); gap Parquet schemas must exactly equal the
   gap schema;
8. every row is reconstructed and validated; `canonical_bar_key` and
   `canonical_row_version_id` must be unique, valid, and equal to their
   recomputed values;
9. `canonical_content_id`, `resolution_content_id`, `gap_content_id`, and
   `canonical_build_id` are recomputed from the actual contents and must
   match the manifest;
10. source provenance must be strictly shaped and must exactly match the
    resolution source identities, and every row's stable source identity must
    be referenced by resolution;
11. manifest counts and min/max event/archive timestamps must match the
    actual contents.

The file-level validation reuses the exact validators of the materialization
idempotency path, so the read side and the write side share one artifact
contract. The reader never writes, repairs, or rewrites anything.

## 3. PIT request model

`PITSampleRequest` is frozen and normalized at construction:

- `code` strip + uppercase, `interval` strip + lowercase, `adjustment` and
  `requested_session` strip + uppercase; empty strings, control characters,
  and reserved encoding separators fail;
- `anchor_market_calendar_date` is the market-calendar date the sample is
  anchored to;
- the feature window is half-open `[feature_window_start, feature_window_close)`;
- the label window is either absent or complete (both boundaries or neither);
  it may not start before the feature window close;
- all instants must be timezone-aware and normalize to UTC microseconds;
  naive timestamps fail; equivalent timezone representations are identical;
- **default adjustment policy: `adjustment == "NONE"` only.** The
  corporate-action as-of policy for adjusted prices is not implemented yet,
  so adjusted requests fail closed. There is deliberately no temporary
  override; future support must arrive as a separate versioned policy.

## 4. Window boundaries

Canonical `event_time` is the interval start (see the timestamp-semantics
contract).

**Feature rows** enter the half-open Feature window when:

```text
code/interval/adjustment/requested_session match
feature_window_start <= event_time < feature_window_close
market_available_at <= feature_window_close
dataset_as_of is None or archive_available_at <= dataset_as_of
```

So a row whose `event_time` equals `feature_window_close` never enters the
Feature set; a row whose `market_available_at` equals `feature_window_close`
may enter; a row available after the close is excluded.

**Label rows** use the same rules against the label window:

```text
label_window_start <= event_time < label_window_close
market_available_at <= label_window_close
dataset_as_of is None or archive_available_at <= dataset_as_of
market_calendar_date == anchor_market_calendar_date
```

Labels are future observations, so their rows may be available after the
feature window close, but they never enter the Feature row set.

**Default no-cross-trading-day label policy:** every Label row must belong to
`anchor_market_calendar_date`. Any label candidate on another
market-calendar date fails closed; there is no `allow_cross_day` temporary
switch in this PR.

**No completeness claim:** without an authoritative session schedule, this PR
only records the actually observed rows, the known internal gaps, the counts
of rows excluded by each clock, and whether the observation window was empty.
Absence of known gaps never implies a complete session.

## 5. `dataset_as_of` semantics

`dataset_as_of` is optional, timezone-aware, normalized to UTC microseconds,
and participates in `sample_version_id`. When set, rows archived after the
cutoff are excluded and counted as archive-clock exclusions; a row archived
exactly at the cutoff is allowed. With `dataset_as_of = None` no archive
cutoff is applied. `dataset_as_of` is **not** part of `sample_key` (the
stable logical sample definition); it binds the physical version.

## 6. Cross-build reconciliation

The assembler accepts multiple `VerifiedCanonicalBuild`s. All candidate rows
are reconciled deterministically:

1. input build and request order never matters (both are sorted internally);
2. every row of a build must be covered by that build's declared
   `canonical_row_version_ids`;
3. rows sharing a `canonical_bar_key` are deduplicated only when they are
   completely identical — same `canonical_row_version_id`, same market
   values, same classification, and same stable source provenance;
4. any other combination (different row version, or same version with
   different values) **fails closed** with a structured error;
5. the "newest build", filesystem mtimes, manifest `created_at`, and input
   order are never used to pick a winner;
6. no synthetic bars are generated and nothing is interpolated,
   forward-filled, or zero-filled.

## 7. Sample identities

**`sample_key`** is the stable logical sample definition. It covers code,
interval, adjustment, requested_session, anchor market-calendar date, feature
window boundaries, optional label window boundaries, and the sample key
version. It never contains canonical build paths, manifest paths,
`built_at`/`created_at`, filesystem metadata, input list order, or local
timezone representations. Equivalent requests in any construction order or
timezone produce the same key; duplicate sample keys in one assembly fail.

**`sample_version_id`** binds the sample to its physical content. It covers
the sample key, the normalized `dataset_as_of`, the ordered Feature and Label
`canonical_row_version_id`s (deterministic position order), the considered
Canonical build IDs, the assembler version, and the version-ID version.
Changing any actual row version, `dataset_as_of`, or build pin changes the
version ID; the same logical inputs in any input order or equivalent timezone
produce the same ID.

Both use the versioned canonical identity encoding of the Dataset manifest
core; Python `hash()`, `repr()`, locale formatting, insertion order, and
filesystem paths are never used.

## 8. Association logical content

The sample-to-row association uses one fixed logical `DatasetSchema`
(PR-12 `DatasetField`/`DatasetSchema` model) in authoritative field order:

```text
sample_key                  string
sample_version_id           string
role                        string   (FEATURE | LABEL only)
position                    int64
canonical_build_id          string
canonical_bar_key           string
canonical_row_version_id    string
code                        string
event_time                  timestamp_us_utc
market_available_at         timestamp_us_utc
archive_available_at        timestamp_us_utc
```

- `position` restarts at 0 per sample and role and follows the deterministic
  time sort `(event_time, market_available_at, canonical_bar_key,
  canonical_row_version_id)`, never the input order.
- `pit_association_schema_id` and `pit_association_content_id` reuse the
  existing PR-12 `dataset_schema_id` / `logical_dataset_content_id`
  encodings; no second logical dataset hash scheme is introduced. Zero
  association rows produce a deterministic, request-independent content ID
  tied to the schema; no placeholder row is fabricated.

## 9. Provenance outputs for the future Dataset builder

`PITAssemblyResult` exposes everything the future Dataset builder needs
without building the final DatasetManifest:

- `canonical_build_pins`: one `CanonicalBuildPin` per considered build,
  built from the verified manifest identities/versions and the rows this
  assembly actually selected. A pin records only the selected row versions
  and only the source snapshots those rows reference; EMPTY builds produce
  pins with zero row versions and zero snapshots. Paths and `created_at`
  never participate.
- `canonical_row_version_ids`: the sorted, deduplicated row versions selected
  across all samples; every selected row version is covered by its build pin.
- `gap_references`: strictly one `GapReference` per considered build with the
  verified `gap_content_id` and `gap_range_count`; gap rows are never copied
  into the Dataset layer. Per-sample diagnostics additionally record the
  known internal gap IDs overlapping each window.
- `association_schema` / `association_rows` / `association_schema_id` /
  `association_content_id`.
- `samples`: the assembled `PITSample`s with their identities, ordered row
  versions, considered build IDs, and deterministic diagnostics
  (candidate/selected/market-excluded/archive-excluded counts per role, known
  gap IDs, empty-observation-window flag). Candidate counts cover only rows
  that already match code/interval/adjustment/requested_session and the event
  window; wrong-symbol or unrelated rows are never counted.

## 10. Non-goals of this PR

- Feature/Label YAML spec parsing and calculations;
- train/validation/test splits and actual-label-end purging;
- DatasetManifest final build orchestration, Dataset Parquet export, Dataset
  build directory and `_SUCCESS`;
- CLI commands, DuckDB views, OpenD calls, network access;
- automatic gap filling, synthetic OHLCV, interpolation, forward-fill;
- adjusted-price as-of policy (only `adjustment = NONE` is allowed);
- Raw / Curated schema changes, package version bump, dependency changes,
  release preparation.
