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
             from audited complete physical snapshots (the V0.4 boundary)
Feature   -- deterministic, versioned transforms of canonical rows into
             numeric/categorical inputs (spec-versioned, not stored per row)
Label     -- deterministic, versioned outcome definitions (spec-versioned,
             not stored per row)
Sample    -- (canonical row identity, feature window, label window) tuple
             assembled under point-in-time rules
Dataset   -- versioned collection of samples with a manifest and a
             deterministic dataset ID
```

Only **Canonical** is materialized as new stored data in V0.4. Feature, Label,
Sample, and Dataset are generated artifacts: their definitions are versioned
specs, and the dataset manifest records the exact spec versions and source
snapshot IDs used.

## 4. Canonical row identity and required provenance

A canonical row must be identifiable by:

```text
dataset_kind        -- e.g. "market_bars_canonical"
code                -- normalized symbol
interval            -- normalized interval (1m/5m/15m/30m/60m)
requested_trade_date
requested_session
adjustment
source_schema_version
event_time          -- the instant the row describes (see section 5)
ingestion_run_id    -- the physical snapshot the row came from
```

Every canonical row carries provenance:

- `ingestion_run_id` and `snapshot_file` of the source physical snapshot.
- `snapshot_ingested_at` and `run_finished_at` of the source run.
- The `COMPLETE` audit state of the source (symbol, trade date) at build time.
- The canonical builder version and its input spec versions.

Canonical rows must only be derived from **audited complete physical
snapshots** selected by the V0.3 `latest_complete_market_bar_snapshots`
semantics. INCOMPLETE or MISSING keys never produce canonical rows; they are
recorded as gaps in the dataset manifest.

## 5. event_time versus available_at

- **event_time**: the instant a bar describes (its interval start, in
  America/New_York, converted to UTC for storage). It is immutable for a given
  bar and independent of collection timing.
- **available_at**: the earliest instant at which the row's information could
  have been known at collection time — in practice derived from the source
  snapshot's `ingested_at`/`run_finished_at`. It is a property of the
  collection run, not of the market event.

Point-in-time assembly must use `available_at` (not `event_time`) to decide
whether a row could have been observed when a sample's feature window closes,
and label computation must use only rows whose `available_at` predates the
label observation time.

**Unresolved (requires source-code inspection):** the exact semantics of
`ingested_at` (per-row stamping time, precision, and timezone representation
after Parquet round trips — DuckDB may surface timestamps in the session
timezone) and the relationship between `run_finished_at` and the last
`ingested_at` of a run must be confirmed by inspecting
`src/market_vault/normalization/bars.py` and the catalog query layer before
canonicalization. Until then, `available_at` is defined conservatively as
`run_finished_at` when present.

## 6. Point-in-time correctness requirements

1. **No future leakage**: a sample's features may only include canonical rows
   whose `available_at <= feature_window_close`.
2. **Label horizon containment**: labels use only rows available at label
   observation time; incomplete label horizons are recorded, not silently
   filled (see section 9).
3. **Determinism**: the same (source snapshot IDs, spec versions, sample
   selection rules) must produce byte-identical samples.
4. **Provenance completeness**: every sample references the canonical rows it
   consumed; a dataset build that cannot resolve a source row fails loudly.
5. **Audit-gated input**: canonicalization only consumes snapshots that pass
   the V0.3 COMPLETE gate at build time.

## 7. Feature specification versioning

- Feature definitions live as versioned spec documents (e.g.
  `features/close_return_v1.spec.yaml`), not as code constants.
- A feature spec pins: input canonical fields, transform function reference,
  parameter values, and the canonical/source-schema versions it requires.
- The dataset manifest records every feature spec version used.
- Changing a feature definition creates a new spec version; it never mutates
  an existing spec in place.

## 8. Label specification versioning

- Label definitions follow the same versioned-spec pattern
  (`labels/next_day_ret_v1.spec.yaml`).
- A label spec pins: observation window, horizon, alignment rule, missing-data
  policy, and required canonical versions.
- **Default no-cross-trading-day label policy**: labels must not span a
  trading-day boundary unless the label spec explicitly opts in and defines
  the boundary rule. The default policy forbids, for example, deriving a label
  from bars of trade date D+1 when the feature window belongs to trade date D.
  Any opt-in must be declared in the label spec and recorded in the manifest.
- Label versioning follows the same no-mutation rule as features.

## 9. Missing-bar and incomplete-horizon behavior

- Missing bars are never invented. Internal gaps inside a segment are
  WARN-level in V0.3 and must be represented in canonical rows as explicit
  absent records (or an explicit gap marker), never as interpolated values.
- An incomplete label horizon (e.g. a horizon that extends past the last
  audited complete trade date) produces a sample with a declared
  `label_status: INCOMPLETE`; such samples are excluded from training splits
  by default and included only when a dataset spec opts in and records the
  policy.
- Dataset-level completeness: the manifest records which (symbol, trade date)
  keys were COMPLETE, INCOMPLETE, or MISSING at build time, so a downstream
  consumer can distinguish "no data" from "data exists but not used".

## 10. Dataset manifest and deterministic dataset ID

Each generated dataset carries a manifest:

```text
dataset_id        -- deterministic hash over (spec versions, source snapshot
                     IDs, sample selection rules, split config)
dataset_kind
built_at
source_snapshot_ids (ordered, deduplicated)
feature_spec_versions
label_spec_versions
canonical_builder_version
split_spec
per-key completion summary (COMPLETE/INCOMPLETE/MISSING counts)
gaps (symbol, trade date) list
```

`dataset_id` must be reproducible from the manifest inputs alone; two builds
from identical inputs produce the identical ID and identical sample bytes.
The manifest itself is written atomically with the existing reporting helper.

## 11. Chronological train/validation/test splits

- Splits are defined over **canonical event_time**, never randomly over rows.
- Split boundaries are dates: `train < validation < test` with no overlap and
  no shuffling across boundaries.
- The split spec records the boundary dates and the rule (e.g. "all samples
  whose feature window closes on or before boundary X go to split Y").

## 12. Purging at split boundaries based on maximum label horizon

- Because labels can look forward, samples near a split boundary can leak
  information across the boundary. The default rule: a sample is excluded from
  a split when its label horizon crosses the split boundary.
- Concretely, when the maximum label horizon is `H` canonical intervals (or
  `H` trading days), the effective training window ends at
  `split_boundary - H`; samples whose label observation time exceeds the
  boundary are dropped from the earlier split (and logged in the manifest).
- The purge rule is part of the split spec and must be recorded per dataset.

## 13. Data leakage threat model

Threats the dataset layer must defend against:

1. **Future-bar leakage**: feature rows observed after the feature window
   close (mitigated by `available_at` checks).
2. **Label leakage across splits**: label horizons crossing split boundaries
   (mitigated by section 12 purging).
3. **Snapshot substitution**: a rebuild silently consuming a different source
   snapshot (mitigated by pinning source snapshot IDs in the manifest and
   failing on mismatch).
4. **Spec drift**: feature/label definitions changing without a version bump
   (mitigated by spec versioning and manifest recording).
5. **Completion ambiguity**: using data that V0.3 would classify INCOMPLETE or
   MISSING (mitigated by the COMPLETE gate and manifest gap recording).
6. **Timezone misattribution**: interpreting instants in the wrong timezone
   (mitigated by canonicalization in UTC and NY-local market time with
   explicit offsets, pending resolution of the timestamp semantics noted in
   section 5).

## 14. Proposed PR sequence

```text
PR-1  docs: canonical dataset boundary ADR + direction (this PR)
PR-2  feat: canonical builder core (row identity, provenance, COMPLETE gate)
PR-3  feat: canonical materialization + builder versioning
PR-4  feat: dataset manifest and deterministic dataset ID
PR-5  feat: point-in-time sample assembly (event_time/available_at rules)
PR-6  feat: feature and label spec versioning framework (no ML libraries)
PR-7  feat: chronological splits and boundary purging
PR-8  tests: leakage threat-model regression suite
PR-9  chore: v0.4.0 release prep (docs, changelog, version bump)
```

Each PR keeps the V0.3 compatibility contract unchanged and runs the full
offline test suite.

## 15. V0.4.0 acceptance criteria

- Canonical rows are derivable from audited complete physical snapshots only;
  a deterministic test set proves INCOMPLETE/MISSING keys never produce rows.
- `event_time`/`available_at` semantics are implemented, tested, and the
  unresolved timestamp questions from section 5 are resolved in code.
- Feature/label specs are versioned and recorded in every manifest.
- The default no-cross-trading-day label policy is enforced and tested.
- Dataset ID is deterministic; identical inputs produce identical IDs.
- Chronological splits and boundary purging behave exactly per the split
  spec, with a regression suite covering the leakage threat model.
- No ML library is added; no runtime dependency changes for ML purposes.
- All V0.3 offline tests continue to pass unchanged; V0.3 data and CLI
  behavior are untouched.
- V0.4.0 version bump happens only in the release-prep PR, not in feature
  PRs.
