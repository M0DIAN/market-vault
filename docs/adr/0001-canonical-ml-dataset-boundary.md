# ADR 0001: Canonical ML Dataset Boundary

- Status: proposed
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
versioned data (Canonical), what is generated on demand (Feature / Label /
Sample / Dataset), and what explicitly stays out of scope.

Constraints:

- No machine-learning libraries and no model training.
- No reconstruction of historical Bid/Ask, Greeks, order book, or intraday IV.
- No automatic repair or deletion of source data.
- V0.3 compatibility (schema, views, Parquet layout, CLI, completion
  semantics) must remain unchanged.
- Canonical data must prefer audited complete physical snapshots.

## Decision

1. **Canonical is the only new materialized layer.** Canonical rows are
   resolved, point-in-time-consistent, versioned rows derived exclusively from
   audited COMPLETE physical snapshots selected with the V0.3
   `latest_complete_market_bar_snapshots` semantics. Feature, Label, Sample,
   and Dataset are generated artifacts defined by versioned specs and recorded
   in a dataset manifest; they are never stored as long-lived row data.

2. **Canonical row identity** is
   `(dataset_kind, code, interval, requested_trade_date, requested_session,
   adjustment, source_schema_version, event_time, ingestion_run_id)`. Every
   row carries provenance: `snapshot_file`, `snapshot_ingested_at`,
   `run_finished_at`, the source COMPLETE audit state, and the canonical
   builder version.

3. **event_time vs available_at**: `event_time` is the interval start in
   America/New_York converted to UTC and is immutable; `available_at` is the
   earliest collection-time knowledge instant, derived from the source
   snapshot (`run_finished_at` by default). Point-in-time assembly and label
   computation may only consume rows whose `available_at` satisfies the
   window rules. Unresolved timestamp semantics (per-row `ingested_at`
   precision and timezone representation after Parquet round trips) are
   flagged for source-code inspection before canonicalization; until then
   `available_at = run_finished_at` when present.

4. **Spec versioning**: feature and label definitions are versioned spec
   documents; a change creates a new version and never mutates an existing
   one. The dataset manifest records every spec version used.

5. **Default no-cross-trading-day labels**: labels must not span a
   trading-day boundary unless a label spec explicitly opts in and defines
   the boundary rule.

6. **Missing and incomplete data**: missing bars are recorded, never
   interpolated; incomplete label horizons are declared
   `label_status: INCOMPLETE` and excluded from training splits by default.

7. **Deterministic datasets**: each generated dataset has a manifest with a
   deterministic `dataset_id` hash over (spec versions, source snapshot IDs,
   sample rules, split config). Identical inputs produce identical IDs and
   identical sample bytes.

8. **Chronological splits with boundary purging**: splits are date-ordered
   over canonical `event_time`; samples whose label horizon crosses a split
   boundary are purged from the earlier split (log of purged samples in the
   manifest).

9. **Leakage threat model** (future-bar leakage, cross-split label leakage,
   snapshot substitution, spec drift, completion ambiguity, timezone
   misattribution) is a tested contract of the dataset layer, not an
   afterthought.

10. **Out of scope for V0.4.0**: ML libraries, model training/inference,
    reconstruction of unavailable historical fields, gap repair, source-data
    mutation, and any change to V0.3 runtime behavior.

## Consequences

### Positive

- One canonical implementation of completion gating, snapshot selection, and
  point-in-time rules, tested once and reused by every dataset build.
- Deterministic, auditable datasets: every sample is traceable to a physical
  snapshot and spec versions.
- V0.3 storage remains the single source of truth; canonicalization is a
  pure read.

### Negative

- A new layer of stored data (canonical rows) adds storage overhead and a new
  builder that must be kept audited.
- Point-in-time strictness can exclude usable data (incomplete horizons,
  cross-split purging); consumers must opt in explicitly for relaxed rules.

### Neutral

- Feature/Label/Sample/Dataset remain generated, so ML-specific code lives
  outside the runtime package unless a later decision materializes it.
- The exact `available_at` definition depends on resolving the flagged
  timestamp semantics in code inspection.

## Unresolved questions

1. Exact semantics of per-row `ingested_at` (stamp time, precision, timezone
   after Parquet round trips) — requires reading
   `src/market_vault/normalization/bars.py` and the catalog query layer.
2. Whether canonical rows are stored as one Parquet file per
   (dataset_kind, builder_version) or partitioned per trade date — deferred
   to PR-3 of the proposed sequence.
3. Whether the default no-cross-trading-day policy should also forbid
   overnight (OVERNIGHT-session) labels — deferred to label-spec review.
