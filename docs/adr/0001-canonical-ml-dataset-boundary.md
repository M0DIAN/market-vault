# ADR 0001: Canonical ML Dataset Boundary

- Status: accepted
- Deciders: MarketVault maintainers
- Date: 2026-08-04
- Related: [V0.4.0 direction](../v0_4_0_direction.md)

## Context

V0.3 stores audited, immutable Raw/Curated market-bar snapshots and classifies
each (symbol, trade date) as COMPLETE, INCOMPLETE, or MISSING against the exact
request key. Consumers who want to build machine-learning datasets today must
re-implement completion semantics, snapshot selection, point-in-time rules,
and versioning themselves. V0.4 introduces a **canonical dataset layer** that
owns those decisions once.

The open question is where the boundary sits: what becomes materialized,
versioned source-of-truth data (Canonical), what is generated on demand
(Feature / Label / Sample / Dataset), and what explicitly stays out of scope.

Constraints:

- No machine-learning libraries and no model training.
- No reconstruction of historical Bid/Ask, Greeks, order book, or intraday IV.
- No automatic repair or deletion of source data.
- V0.3 compatibility (schema, views, Parquet layout, CLI, completion
  semantics) must remain unchanged.
- Canonical data must prefer audited complete physical snapshots.

## Decision

1. **Canonical is the only new source-of-truth materialized data layer.**
   Canonical rows are resolved, point-in-time-consistent, versioned rows
   derived exclusively from audited COMPLETE physical snapshots selected with
   the V0.3 `latest_complete_market_bar_snapshots` semantics. Feature, Label,
   and Sample are generated computations defined by versioned specs; they are
   never stored as long-lived row data. Exported Dataset Parquet files are
   immutable build artifacts derived from canonical rows, not another
   source-of-truth storage layer: a dataset is never authoritative input to
   another dataset build.

2. **Two identity levels.**

   - **Canonical business identity** (`canonical_bar_key`):
     `(dataset_kind, code, interval, adjustment, event_time)` — stable,
     version-free, and **without `ingestion_run_id`, `source_schema_version`,
     `requested_trade_date`, or `requested_session`**. Two rows with the same
     key describe the same market event. Request-level fields
     (`requested_trade_date`, `requested_session`, `market_calendar_date`,
     `session`) are provenance, audit, partition, or classification fields
     only. When different source requests resolve to the same key, the
     builder reconciles them deterministically: on conflicting market values
     it fails the build or records an explicit conflict — it never silently
     emits two canonical business rows.
   - **Physical row version identity** (`canonical_row_version_id`):
     `canonical_bar_key + ingestion_run_id + source_snapshot_content_hash +
     source_schema_version + canonical_builder_version`. `snapshot_file` is
     **not** part of the version identity because file paths can change; it
     is carried only as provenance metadata. This identity is used for
     provenance, rebuild comparison, and auditability.

   Every canonical row carries provenance: `snapshot_file` (metadata only),
   `snapshot_ingested_at`, `run_finished_at`, the source COMPLETE audit state,
   and the canonical builder version.

3. **Three-clock time model.**

   - `event_time`: the instant a bar describes. V0.4 adopts interval-start as
     the interpretation of `time_key` (evidence-supported; the official
     Moomoo documentation does not explicitly distinguish interval start/end,
     so a re-verification requirement applies on SDK change). `event_time` is
     the normalized market timestamp converted to UTC.
   - `market_available_at`: the earliest market-time instant at which the
     complete bar could be used; point-in-time **feature assembly must use
     this clock**.
   - `archive_available_at`: the instant the snapshot became available inside
     MarketVault, normally `run_finished_at`; **archive-as-of reconstruction
     must additionally use this clock**, with an optional `dataset_as_of`
     parameter selecting archive-time reproducibility.

   Unresolved timestamp semantics (per-row `ingested_at` precision and
   timezone representation after Parquet round trips) are flagged for
   source-code inspection before canonicalization; until then
   `market_available_at` is provisionally `event_time + interval` and
   `archive_available_at = run_finished_at` when present.

4. **Determinism contract, not byte identity.** Canonicalization and dataset
   builds promise deterministic normalized rows, deterministic column
   ordering and dtypes, a deterministic logical content hash, and a
   deterministic `dataset_id`. Byte-identical Parquet output may only be
   promised when the serializer version and all writer options are pinned;
   without that pin, only the logical content contract holds.

5. **Dataset ID inputs** include: canonical builder version; normalized
   feature/label spec content hashes; transform implementation or code
   version; source snapshot content hashes; manifest schema version; output
   schema/column order; serialization format version. `dataset_id` is
   reproducible from the manifest inputs alone.

6. **Spec versioning**: feature and label definitions are versioned spec
   documents whose content is hashed into the manifest together with the
   transform implementation version; a change creates a new version and never
   mutates an existing one.

7. **Default no-cross-trading-day labels**: labels must not span a
   trading-day boundary unless a label spec explicitly opts in and defines
   the boundary rule.

8. **Default adjustment NONE**: the default leakage-safe dataset policy uses
   `adjustment = NONE`, because adjusted prices embed corporate-action
   information that can leak forward. Any adjusted-price dataset must declare
   and version its adjustment and corporate-action as-of policy in the
   manifest.

9. **Missing and incomplete data**: canonical market bars contain only
   observed bars — no synthetic OHLCV rows and no interpolation. Gaps are
   recorded in a separate manifest section or canonical gap sidecar. V0.3
   cannot detect every leading/trailing/session gap without an authoritative
   per-date session schedule, so the gap sidecar records only gaps the audits
   can establish. Incomplete label horizons are declared
   `label_status: INCOMPLETE` and excluded from training splits by default.

10. **Chronological splits with actual-label-end purging**: splits are
    date-ordered over canonical `event_time`; a sample is purged from the
    earlier split when its **actual `label_end_time`** crosses the split
    boundary (logged in the manifest). A nominal maximum-horizon purge is
    only an optimization when it provably equals the actual-label-end rule.

11. **Leakage threat model** (future-bar leakage via `market_available_at`,
    archive-time leakage via `archive_available_at`/`dataset_as_of`,
    cross-split label leakage via `label_end_time`, adjustment/corporate-
    action leakage via the `adjustment = NONE` default, snapshot
    substitution, spec drift, completion ambiguity, timezone
    misattribution) is a tested contract of the dataset layer.

12. **Out of scope for V0.4.0**: ML libraries, model training/inference,
    reconstruction of unavailable historical fields, gap repair, source-data
    mutation, and any change to V0.3 runtime behavior.

## Consequences

### Positive

- One canonical implementation of completion gating, snapshot selection, and
  point-in-time rules, tested once and reused by every dataset build.
- Deterministic, auditable datasets: every sample is traceable to a physical
  snapshot, spec versions, and content hashes.
- V0.3 storage remains the single source of truth; canonicalization is a
  pure read, and dataset exports are derived artifacts, never another
  authority.

### Negative

- A new layer of stored data (canonical rows) adds storage overhead and a new
  builder that must be kept audited.
- Point-in-time strictness and the `adjustment = NONE` default can exclude
  usable data (incomplete horizons, cross-split purging, adjusted prices);
  consumers must opt in explicitly for relaxed rules.

### Neutral

- Feature/Label/Sample/Dataset remain generated, so ML-specific code lives
  outside the runtime package unless a later decision materializes it.
- The exact `market_available_at` definition depends on resolving the flagged
  timestamp semantics in code inspection.

## Unresolved questions

1. Exact semantics of per-row `ingested_at` (stamp time, precision, timezone
   after Parquet round trips) — requires reading
   `src/market_vault/normalization/bars.py` and the catalog query layer.
2. The official Moomoo documentation does not explicitly distinguish
   interval start from interval end; the adopted interval-start
   interpretation (see the implementation note) carries a mandatory
   re-verification requirement on SDK change.
3. Whether canonical rows are stored as one Parquet file per
   (dataset_kind, builder_version) or partitioned per trade date — deferred
   to PR-4 of the proposed sequence.
4. Whether the default no-cross-trading-day policy should also forbid
   overnight (OVERNIGHT-session) labels — deferred to label-spec review.

## Implementation note: timestamp semantics verified

The timestamp-semantics prerequisite (PR-2 of the proposed sequence) is
resolved; conclusions are pinned by deterministic offline tests
(`tests/test_timestamp_semantics_v03.py`) and documented in
[contracts/market_bar_timestamp_semantics.md](../contracts/market_bar_timestamp_semantics.md).

- `time_key`: the official Moomoo documentation defines the candlestick time
  in the market timezone without explicitly distinguishing interval start
  from interval end; MarketVault adopts **interval-start** as its
  evidence-supported interpretation (API behavior examples, normalization
  path, stored-data consistency) with a mandatory re-verification requirement
  on SDK change.
- `event_time` = normalized market timestamp converted to UTC.
- `market_available_at` = `event_time + interval` (pure function
  `market_vault.normalization.bar_available_at`); exact only for bars known
  to span their full nominal interval, and a conservative leakage-safe
  not-before bound for bars that may be truncated at session boundaries or
  early closes.
- `archive_available_at` = `run_finished_at` (the run's `finished_at`, UTC,
  present for SUCCESS/PARTIAL/FAILED).
- DST: naive `time_key` values are localized to America/New_York with
  `ambiguous="raise"` and `nonexistent="raise"`.
- `ingested_at`: stamped once per normalize call, identical across the batch,
  microseconds, UTC.
- Parquet preserves timezones via PyArrow; DuckDB surfaces instants in the
  session timezone — consumers must convert both sides to UTC.

### Implementation note: immutable materialization verified

The canonical materialization layer
([contracts/canonical_market_bar_materialization.md](../contracts/canonical_market_bar_materialization.md))
is implemented: COMPLETE snapshots are loaded through the V0.3
latest-complete selector, canonical bars/gaps/resolution are derived by the
in-memory builder, and each build is committed atomically as an immutable
directory (`bars/`, `gaps/`, `resolution.jsonl`, `manifest.json`, `_SUCCESS`)
keyed by a deterministic `canonical_build_id`. Logical identities
(`canonical_content_id`, `resolution_content_id`, `gap_content_id`,
`canonical_build_id`) are path- and byte-layout-independent; `snapshot_file`
remains descriptive provenance. EMPTY builds are explicit, idempotency is
enforced, and no mutable latest pointer or DuckDB view is registered yet.
