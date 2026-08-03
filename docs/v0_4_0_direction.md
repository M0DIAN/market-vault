# MarketVault v0.4.0 Direction: Canonical Dataset and ML Foundation

Status: proposed (planning only, no runtime changes)

This document defines the scope, non-goals, and design direction for the
V0.4.0 "Canonical Dataset and ML Foundation" phase. It is a planning document;
no code, schema, CLI, or version changes are part of this PR. The authoritative
boundary decision is captured separately in
[ADR 0001](adr/0001-canonical-ml-dataset-boundary.md).

## 1. Current V0.3 capabilities and boundaries

V0.3 provides a trading-calendar-driven collection and audit toolchain:

- **Local trading calendar** (`calendar`, `calendar-query`): trading days from
  OpenD `request_trading_days`, scoped by market or reference code.
- **Resumable history backfill** (`backfill`): standard, incremental, and
  `--force` modes with per-(symbol, trade date) completion tracking, retries,
  and re-run recovery.
- **Immutable snapshots**: each collection run writes
  `batch-<batch_key>-<run_id>.parquet`; `--force` never overwrites an older
  snapshot. Legacy `batch-<batch_key>.parquet` files remain readable.
- **Inventory** (`inventory`): physical storage statistics, per-combination
  coverage, snapshot counts, and legacy metadata accounting.
- **Coverage audit** (`audit`): COMPLETE / INCOMPLETE / MISSING classification
  per (symbol, trade date) against the exact request key, with calendar
  requested-range coverage checks.
- **Intraday integrity audit** (`intraday-audit`): structural checks of the
  latest complete physical snapshot — exact metadata, timestamps, timezones,
  session labels, duplicate bars, minute-grid alignment, and internal gaps
  inside contiguous observed session segments.
- **Completion semantics**: COMPLETE requires curated rows matching the exact
  request key, a linked run with status SUCCESS or PARTIAL, no quality FAIL,
  and matching run metadata.

V0.3 boundaries that V0.4 must preserve:

- No authoritative per-date session schedule; session leading/trailing
  boundaries are not validated and wholly missing sessions are not judged.
- No fixed daily bar counts (no 390/1201/1440 assumptions) and no early-close
  recognition.
- Internal gaps are WARN-only and never automatically re-collected.
- No real-time subscriptions, no historical Bid/Ask, order-book depth, Greeks,
  or intraday IV reconstruction.
- No automatic trading, signals, or execution.

## 2. V0.4 goal and explicit non-goals

### Goal

Provide a **canonical, versioned, point-in-time-correct dataset layer** on top
of the audited V0.3 storage so that reproducible ML datasets can be derived
without re-deriving raw history or re-implementing completion semantics.

### Non-goals (explicit)

- **No ML libraries.** No model training, inference, or experimentation
  framework is added as a runtime dependency.
- **No reconstruction claims.** V0.4 does not claim historical Bid/Ask,
  Greeks, order book, or intraday IV can be reconstructed from stored data.
- **No source-data mutation.** The canonical layer never repairs, deletes,
  or rewrites Raw/Curated data; it only reads audited snapshots.
- **No leakage repair.** Gap repair and automatic re-collection stay out of
  scope; the dataset layer records gaps, it does not fill them.
- **No schema migration.** V0.3 tables, views, Parquet layout, and CLI
  behavior remain unchanged; canonical datasets are new, separate artifacts.
- **No cross-trading-day labels by default** (see section 8).

## 3. Raw -> Curated -> Canonical -> Feature -> Label -> Sample -> Dataset

```text
Raw       -- immutable source payloads, one file per collection run
Curated   -- normalized bars/calendar/options, immutable snapshots,
             completion audited by V0.3
Canonical -- resolved, point-in-time-consistent, versioned row set derived
             from audited complete physical snapshots (the V0.4 boundary;
             the only new source-of-truth materialized data layer)
Feature   -- deterministic, versioned transforms of canonical rows into
             numeric/categorical inputs (spec-versioned computations,
             not stored as long-lived row data)
Label     -- deterministic, versioned outcome definitions (spec-versioned
             computations, not stored as long-lived row data)
Sample    -- (canonical row identity, feature window, label window) tuple
             assembled under point-in-time rules
Dataset   -- versioned collection of samples with a manifest and a
             deterministic dataset ID; exported Parquet files are immutable
             build artifacts, not another source-of-truth storage layer
```

Materialization clarification:

- **Canonical is the only new source-of-truth materialized data layer.**
- Feature, Label, and Sample are generated computations defined by versioned
  specs; they are not another storage layer.
- Exported Dataset Parquet files may be immutable build artifacts, but they
  are derived outputs: rebuilding from the same inputs must reproduce the
  same logical content, and a dataset is never treated as authoritative input
  to another dataset build.

## 4. Canonical identity: business key and physical row version

### 4.1 Canonical business identity (`canonical_bar_key`)

Stable, version-free, and **free of ingestion_run_id, source_schema_version,
requested_trade_date, and requested_session**:

```text
dataset_kind        -- e.g. "market_bars_canonical"
code                -- normalized symbol
interval            -- normalized interval (1m/5m/15m/30m/60m)
adjustment
event_time          -- the instant the row describes (see section 5)
```

Two canonical rows with the same `canonical_bar_key` describe the same market
event; they may differ in provenance or version. The request-level fields
`requested_trade_date`, `requested_session`, `market_calendar_date`, and
`session` are **not** part of the business identity; they are carried as
provenance, audit, partition, or classification fields.

**Key reconciliation rule**: when different source requests resolve to the
same `canonical_bar_key`, the builder must reconcile them deterministically.
If their market values conflict, the builder must fail the build or record an
explicit conflict in the manifest; it must never silently emit two canonical
business rows for one key.

### 4.2 Physical row version identity (`canonical_row_version_id`)

Captures which physical data and which builder produced the row:

```text
canonical_bar_key           -- the business identity above
ingestion_run_id            -- the physical snapshot the row came from
source_snapshot_content_hash -- content hash of the source snapshot
source_schema_version
canonical_builder_version
```

`snapshot_file` is **not** part of the version identity: file paths can
change, so it is carried only as provenance metadata. `canonical_row_version_id`
is the identity used for provenance, rebuild comparison, and auditability.

### 4.3 Provenance

Every canonical row carries, alongside `canonical_row_version_id`:

- `snapshot_file`, `snapshot_ingested_at`, and `run_finished_at` of the
  source run (path as metadata only).
- The `COMPLETE` audit state of the source (symbol, trade date) at build time.
- The canonical builder version and its input spec versions.

Canonical rows must only be derived from **audited complete physical
snapshots** selected by the V0.3 `latest_complete_market_bar_snapshots`
semantics. INCOMPLETE or MISSING keys never produce canonical rows; they are
recorded as gaps in the dataset manifest.

## 5. Time semantics: event_time and the two availability clocks

MarketVault records three distinct instants for every bar:

- **event_time**: the instant a bar describes. V0.4 treats this as the
  interval start in America/New_York converted to UTC **as a hypothesis to be
  verified**: do not assume `time_key` is definitely interval-start time until
  its OpenD and normalization semantics have been verified by inspecting the
  collector and `src/market_vault/normalization/bars.py`. Until verified,
  `event_time` is defined operationally as "the normalized market timestamp
  of the row converted to UTC", and canonical consumers must not rely on
  interval-start alignment.
- **market_available_at**: the earliest market-time instant at which the
  complete bar could be used — the instant the bar's information could have
  been known on the market clock. This is the clock that point-in-time
  feature assembly must use when deciding whether a row could have been
  observed at a feature window close.
- **archive_available_at**: the instant the snapshot became available inside
  MarketVault, normally `run_finished_at`. Archive-as-of reconstruction (an
  "as of archive time" dataset) must additionally use this clock.

An optional `dataset_as_of` parameter selects archive-time reproducibility:
a dataset built with `dataset_as_of = T` may only consume snapshots whose
`archive_available_at <= T`, so a later re-collection cannot change the
dataset's content.

**Verified (timestamp-semantics contract PR):** `time_key` is interpreted as
interval-start market time; `market_available_at = event_time + interval`;
`archive_available_at = run_finished_at`; DST-ambiguous and nonexistent naive
`time_key` values raise; `ingested_at` is stamped once per normalize call
(same value across the batch, microseconds, UTC); DuckDB surfaces timestamps
in the session timezone, so consumers must convert both sides to UTC. Full
details and the pinned offline tests are in
[contracts/market_bar_timestamp_semantics.md](contracts/market_bar_timestamp_semantics.md).
**Remaining evidence gap:** the OpenD documentation itself is not committed
in this repository; the interval-start interpretation rests on the SDK
convention, the normalization path, and stored-data consistency and must be
re-verified if SDK behavior changes.

## 6. Point-in-time correctness requirements

1. **No future leakage**: a sample's features may only include canonical rows
   whose `market_available_at <= feature_window_close`. Archive-as-of
   datasets must additionally satisfy `archive_available_at <= dataset_as_of`.
2. **Label horizon containment**: labels use only rows available at label
   observation time; incomplete label horizons are recorded, not silently
   filled (see section 9).
3. **Determinism**: the same (source snapshot IDs, spec versions and content,
   transform implementations, sample selection rules) must produce
   deterministic normalized rows, deterministic column ordering and dtypes,
   a deterministic logical content hash, and a deterministic `dataset_id`.
   Byte-identical Parquet output may only be promised when the serializer
   version and all writer options are pinned (see section 10).
4. **Provenance completeness**: every sample references the canonical rows it
   consumed; a dataset build that cannot resolve a source row fails loudly.
5. **Audit-gated input**: canonicalization only consumes snapshots that pass
   the V0.3 COMPLETE gate at build time.

## 7. Feature specification versioning

- Feature definitions live as versioned spec documents (e.g.
  `features/close_return_v1.spec.yaml`), not as code constants.
- A feature spec pins: input canonical fields, transform function reference,
  parameter values, and the canonical/source-schema versions it requires.
- The dataset manifest records every feature spec version **and the content
  hash of each spec**, plus the transform implementation or code version that
  produced the values.
- Changing a feature definition creates a new spec version; it never mutates
  an existing spec in place.

## 8. Label specification versioning

- Label definitions follow the same versioned-spec pattern
  (`labels/next_day_ret_v1.spec.yaml`).
- A label spec pins: observation window, horizon, alignment rule, missing-data
  policy, and required canonical versions. The manifest records spec content
  hashes and implementation versions like features.
- **Default no-cross-trading-day label policy**: labels must not span a
  trading-day boundary unless the label spec explicitly opts in and defines
  the boundary rule. The default policy forbids, for example, deriving a label
  from bars of trade date D+1 when the feature window belongs to trade date D.
  Any opt-in must be declared in the label spec and recorded in the manifest.
- Label versioning follows the same no-mutation rule as features.

## 9. Missing-bar and incomplete-horizon behavior

- **Canonical market bars contain only observed bars.** No synthetic OHLCV
  rows are ever generated, and missing bars are never interpolated.
- Gaps (internal gaps, and per-key INCOMPLETE/MISSING states) are recorded in
  a **separate manifest section or a canonical gap sidecar**, never as
  placeholder rows in the canonical bar stream.
- V0.3 cannot detect every leading/trailing/session gap without an
  authoritative per-date session schedule; the gap sidecar therefore records
  only the gaps the audits can actually establish, and consumers must not
  infer session-coverage completeness from the absence of gap records.
- An incomplete label horizon (e.g. a horizon that extends past the last
  audited complete trade date) produces a sample with a declared
  `label_status: INCOMPLETE`; such samples are excluded from training splits
  by default and included only when a dataset spec opts in and records the
  policy.
- Dataset-level completeness: the manifest records which (symbol, trade date)
  keys were COMPLETE, INCOMPLETE, or MISSING at build time.

## 10. Dataset manifest and deterministic dataset ID

Each generated dataset carries a manifest:

```text
dataset_id            -- deterministic hash over the inputs listed below
dataset_kind
built_at
dataset_as_of         -- optional archive-time cutoff, when used
canonical_builder_version
canonical_row_version_ids (ordered, deduplicated)
source snapshot IDs and source snapshot content hashes
feature spec versions and content hashes
label spec versions and content hashes
transform implementation / code versions
manifest schema version
output schema and column order
serialization format version
split_spec
per-key completion summary (COMPLETE/INCOMPLETE/MISSING counts)
gaps (symbol, trade date) list
```

`dataset_id` inputs therefore include:

1. canonical builder version
2. normalized feature/label spec content hashes
3. transform implementation or code version
4. source snapshot content hashes
5. manifest schema version
6. output schema/column order
7. serialization format version

`dataset_id` must be reproducible from the manifest inputs alone: two builds
from identical inputs produce the identical ID and the identical **logical
content** (deterministic normalized rows, column ordering, dtypes, and a
deterministic logical content hash). Byte-identical Parquet bytes are
promised only when the serializer version and all writer options are pinned;
without that pin, only the logical content contract holds. The manifest
itself is written atomically with the existing reporting helper.

## 11. Chronological train/validation/test splits

- Splits are defined over **canonical event_time**, never randomly over rows.
- Split boundaries are dates: `train < validation < test` with no overlap and
  no shuffling across boundaries.
- The split spec records the boundary dates and the rule (e.g. "all samples
  whose feature window closes on or before boundary X go to split Y").

## 12. Purging at split boundaries based on actual label end

- Because labels can look forward, samples near a split boundary can leak
  information across the boundary. The default rule: a sample is excluded from
  a split when **its actual `label_end_time`** crosses the split boundary —
  not a nominal horizon subtracted from the boundary.
- Concretely, each sample's label window has a concrete `label_end_time`
  (the market instant the last label input becomes available). If
  `label_end_time > split_boundary`, the sample is dropped from the earlier
  split and logged in the manifest.
- The purge rule is part of the split spec and must be recorded per dataset.
  A nominal maximum-horizon purge may be offered as an optimization only when
  it provably equals the actual-label-end rule.

## 13. Data leakage threat model

Threats the dataset layer must defend against:

1. **Future-bar leakage**: feature rows observed after the feature window
   close (mitigated by `market_available_at` checks).
2. **Archive-time leakage**: consuming snapshots archived after the dataset's
   `dataset_as_of` (mitigated by `archive_available_at` checks in
   archive-as-of datasets).
3. **Label leakage across splits**: label windows crossing split boundaries
   (mitigated by the actual-`label_end_time` purge of section 12).
4. **Adjustment / corporate-action leakage**: adjusted prices embed
   information about events that occurred after the feature window.
   **The default leakage-safe dataset policy uses `adjustment = NONE`.** Any
   adjusted-price dataset must declare and version its adjustment and
   corporate-action as-of policy in the dataset manifest.
5. **Snapshot substitution**: a rebuild silently consuming a different source
   snapshot (mitigated by pinning source snapshot IDs and content hashes in
   the manifest and failing on mismatch).
6. **Spec drift**: feature/label definitions changing without a version bump
   (mitigated by spec versioning, content hashes, and implementation
   versions recorded in the manifest).
7. **Completion ambiguity**: using data that V0.3 would classify INCOMPLETE or
   MISSING (mitigated by the COMPLETE gate and manifest gap recording).
8. **Timezone misattribution**: interpreting instants in the wrong timezone
   (mitigated by canonicalization in UTC and NY-local market time with
   explicit offsets, pending resolution of the timestamp semantics noted in
   section 5).

## 14. Proposed PR sequence

```text
PR-1   docs: canonical dataset boundary ADR + direction (this PR)
PR-2   feat: timestamp-semantics contract -- resolve and test the OpenD
       time_key interval-start versus interval-end semantics, interval
       completion / market_available_at, DST conversion behavior, per-row
       ingested_at semantics, run_finished_at semantics and precision, and
       DuckDB timestamp round-trip behavior. Must land before any canonical
       builder implementation.
PR-3   feat: canonical builder core (canonical_bar_key, canonical_row_version_id,
       key reconciliation, provenance, COMPLETE gate)
PR-4   feat: canonical materialization + builder versioning + gap sidecar
PR-5   feat: dataset manifest, deterministic dataset ID, content hashing
PR-6   feat: two-clock point-in-time sample assembly
       (market_available_at / archive_available_at / dataset_as_of)
PR-7   feat: feature and label spec versioning framework (no ML libraries)
PR-8   feat: chronological splits and actual-label-end purging
PR-9   tests: leakage threat-model regression suite (incl. adjustment policy)
PR-10  chore: v0.4.0 release prep (docs, changelog, version bump)
```

Each PR keeps the V0.3 compatibility contract unchanged and runs the full
offline test suite. PR-2 (timestamp-semantics contract) is a hard prerequisite
for PR-3 and later: `event_time`, `market_available_at`, and
`archive_available_at` cannot be implemented correctly until its tests pin
the six timestamp behaviors.

## 15. V0.4.0 acceptance criteria

- Canonical rows are derivable from audited complete physical snapshots only;
  a deterministic test set proves INCOMPLETE/MISSING keys never produce rows.
- `event_time`, `market_available_at`, and `archive_available_at` semantics
  are implemented and tested; the timestamp-semantics contract PR (PR-2)
  resolves and tests the six timestamp behaviors from section 5 before the
  canonical builder lands (or `event_time` remains operationally defined and
  documented as such).
- Feature/label specs are versioned, content-hashed, and recorded in every
  manifest together with transform implementation versions.
- The default no-cross-trading-day label policy and the default
  `adjustment = NONE` policy are enforced and tested; adjusted datasets
  declare and version their as-of policy.
- Canonical bars contain only observed bars; gaps live in the manifest/sidecar
  and never as synthetic OHLCV rows.
- Dataset ID is deterministic from its documented input set; identical inputs
  produce identical IDs and identical logical content.
- Chronological splits purge by actual `label_end_time`, with a regression
  suite covering the leakage threat model.
- No ML library is added; no runtime dependency changes for ML purposes.
- All V0.3 offline tests continue to pass unchanged; V0.3 data and CLI
  behavior are untouched.
- V0.4.0 version bump happens only in the release-prep PR, not in feature
  PRs.
