# Leakage Threat-Model Regression Contract

Status: implemented in the v0.4.0 offline leakage threat-model regression
suite (`tests/test_leakage_threat_model.py`).

This contract defines the eight stable leakage threats of the V0.4.0 threat
model (ADR 0001, section 11; direction document section 13) as a **cross-
contract, cross-layer offline regression matrix**: canonical materialization
and the verified reader, two-clock point-in-time sample assembly, Feature /
Label spec identity, chronological splits with actual-label-end purging, and
the derived dataset identity layer. Related contracts:
[market_bar_timestamp_semantics.md](market_bar_timestamp_semantics.md),
[canonical_market_bar_materialization.md](canonical_market_bar_materialization.md),
[derived_dataset_manifest.md](derived_dataset_manifest.md),
[point_in_time_sample_assembly.md](point_in_time_sample_assembly.md),
[feature_label_spec_versioning.md](feature_label_spec_versioning.md),
[chronological_splits_and_purging.md](chronological_splits_and_purging.md).

This PR is tests and documentation only: it adds no production API, no
identity algorithm change, no version-constant change, no new dependency, no
ML, no OpenD, no network, no CLI, and no Dataset writer. It does not build
the final Dataset builder and does not construct a DatasetManifest or write
Dataset Parquet.

## 1. Status

Implemented as an offline regression suite covering the eight stable threat
IDs below, each with at least one positive control test and one defense test,
tracked by a fixed coverage matrix inside the suite (the matrix guard fails
the suite if an entire category is ever deleted).

## 2. Scope / non-goals

**In scope:** regression coverage of the eight threats against the currently
implemented contracts, exercised through public APIs with minimal deterministic
fixtures; a cross-layer canary chaining Canonical -> PIT -> SpecPin ->
Split/Purge -> DatasetIdentityInput -> `dataset_id`; an offline /
no-network / no-write boundary assertion; and this documentation.

**Out of scope (explicit):** any runtime change; Feature or Label value
computation; the final Dataset builder or Dataset Parquet writer;
adjusted-price PIT support or corporate-action as-of reconstruction;
cross-day Label execution; label-completeness inference; synthetic bars or
filling/interpolation; ML / backtest; Dataset CLI; OpenD or network;
package version, dependency, or CI changes; and PR-10 release preparation.

## 3. Eight stable Threat IDs

```text
LEAKAGE_FUTURE_BAR
LEAKAGE_ARCHIVE_TIME
LEAKAGE_LABEL_CROSS_SPLIT
LEAKAGE_ADJUSTMENT_CORPORATE_ACTION
LEAKAGE_SNAPSHOT_SUBSTITUTION
LEAKAGE_SPEC_DRIFT
LEAKAGE_COMPLETION_AMBIGUITY
LEAKAGE_TIMEZONE_MISATTRIBUTION
```

These IDs are machine identifiers shared by the tests and this document; they
introduce no production API.

## 4. Threat -> enforcing contract/API -> expected defense matrix

| Threat ID | Enforcing contract / API | Expected defense |
| --- | --- | --- |
| LEAKAGE_FUTURE_BAR | PIT assembly; half-open windows; `market_available_at` | Rows available after the feature close never enter FEATURE; rows with `event_time == close` are excluded by the half-open window; market-clock exclusions are counted before archive-clock exclusions; `sample_key` is stable while `sample_version_id`/association content track physical rows; one row version never enters both roles. |
| LEAKAGE_ARCHIVE_TIME | `dataset_as_of`; `archive_available_at` | No cutoff without `dataset_as_of`; rows archived strictly after the cutoff are excluded and counted after passing the market clock; every selected row satisfies the cutoff; `dataset_as_of` never enters `sample_key` but binds `sample_version_id`; known gaps require both boundary bars archived; input order / `created_at` / mtime / "newest build" never override the cutoff. |
| LEAKAGE_LABEL_CROSS_SPLIT | PIT cross-day rule; `label_status`; `actual_label_end_time`; split purge | Cross-market-calendar-date label candidates fail closed with no hidden override; INCOMPLETE labels are EXCLUDED by default (even with a partial actual end); TRAIN/VALIDATION purge by the actual label end against the DST-safe exclusive boundary; TEST has no fourth-split purge; purge never uses a nominal horizon; forged assignments fail closed. |
| LEAKAGE_ADJUSTMENT_CORPORATE_ACTION | `adjustment = NONE` fail-closed policy | Adjusted modes fail closed at the PIT request; no temporary override parameters exist; scope `adjustment` stays identity-bearing; mismatched request adjustment selects no rows; spec models carry no adjustment field. |
| LEAKAGE_SNAPSHOT_SUBSTITUTION | Verified reader; PIT reconciliation; `dataset_id` pins | Byte-substituted bars, tampered manifest identities, and tampered provenance fail closed; conflicting rows for one `canonical_bar_key` fail closed (no "newest"/last-wins); source-pin changes change `dataset_id`; relocated builds keep identity while path-binding inconsistency is rejected; uncovered row versions and bad gap references fail closed. |
| LEAKAGE_SPEC_DRIFT | Spec content identity; SpecPin containers; ImplementationPin | Semantically identical YAML hashes identically; every semantic change changes content ID / pin / `dataset_id`; duplicate `(kind, name, version)` pins fail; pins reject wrong containers; `transform_ref` is a declaration that is never imported or executed; unknown schema versions fail closed. |
| LEAKAGE_COMPLETION_AMBIGUITY | COMPLETE gate; gap sidecar; explicit label facts | Quality-FAIL and MISSING keys never produce complete references or rows; only observed bars exist (no synthetic/interpolated/filled rows; gaps are sidecar records); absence of known gaps never implies completeness; PIT carries no `label_status`; the split layer requires explicit caller-provided label facts; completion/gap semantics are identity-bearing; forged counts fail closed. |
| LEAKAGE_TIMEZONE_MISATTRIBUTION | UTC-microsecond normalization; declared boundary timezone | Naive instants fail closed; equivalent timezone representations produce identical identities; splits use the declared timezone's local date, never the UTC date; DST boundaries are constructed on the local calendar, never fixed +24h; invalid IANA names fail closed with no system-local fallback; sub-microsecond precision truncates consistently. |

## 5. Boundary equality semantics

- Feature rows: `event_time < feature_window_close` (half-open window);
  `market_available_at <= feature_window_close` is selectable.
- Label rows: `event_time < label_window_close`; rows available exactly at a
  window close are allowed; rows available after it are excluded and counted.
- Archive rows: `archive_available_at <= dataset_as_of` is selectable; later
  rows are excluded and counted (after passing the market clock).
- Split purge boundaries are exclusive: `actual_label_end_time <
  boundary_exclusive` is kept; `>= boundary_exclusive` is purged. Ending
  exactly at the last representable microsecond of the boundary date is
  allowed; ending exactly at the next local midnight is purged.

## 6. Market clock vs archive clock

The market clock (`market_available_at`) decides whether a row could have
been observed at the window close; the archive clock
(`archive_available_at`) decides archive-time reproducibility under
`dataset_as_of`. Exclusions are counted in that fixed order: a row later
than both the market close and the archive cutoff is counted once as a
market-clock exclusion. Later-archived rows can never cross the cutoff
through build input order, manifest `created_at`, file mtime, or a "newest
build" rule.

## 7. Label role separation

Label rows are future observations: they may occur after the feature close,
enter only the LABEL role, and never pollute the FEATURE row set. One
`canonical_row_version_id` never appears in both the feature and label lists
of the same sample (fail closed). Cross-market-calendar-date label
candidates fail closed against the explicit `anchor_market_calendar_date`;
there is no `allow_cross_day` parameter and no hidden override.

## 8. Actual-label-end purge

The split layer purges TRAIN/VALIDATION samples whose actual
`actual_label_end_time` crosses the DST-safe next-local-midnight exclusive
boundary. TEST samples are never purged for an actual label end past
`test_end_date` (there is no fourth split). `actual_label_end_time` is the
only purge time fact: `LabelSpec.horizon`, nominal observation-window ends,
`request.label_window_close`, fixed minutes/bars, and embargo never
participate. Label completeness is always caller-declared
(`label_status`); INCOMPLETE labels are EXCLUDED by default, even when a
partial actual end exists. A forged assignment fails closed even when every
identity, row, and diagnostic count is recomputed to match.

## 9. Adjustment NONE fail-closed policy

v1 PIT requests accept `adjustment = NONE` only; `QFQ`, `HFQ`, `FORWARD`,
`BACKWARD`, and `SPLIT_ADJUSTED` fail closed, and no temporary
`allow_adjusted` / `ignore_adjustment_policy` / `unsafe_adjusted_override`
parameter exists. The DatasetScope `adjustment` remains identity-bearing
(different adjustment scopes never collide in `dataset_id`). The current
defense is **fail closed, NONE only** — it is **not** an implemented
historical corporate-action point-in-time reconstruction.

## 10. Snapshot / content / provenance pinning

Verified Canonical builds read cleanly; byte-substituted bars Parquet,
tampered manifest identities (`canonical_build_id`, `canonical_content_id`,
output file hashes), tampered source provenance, and renamed build
directories all fail closed. Conflicting candidates for one
`canonical_bar_key` (different row version, market value, or stable source
provenance) fail closed instead of choosing the newest or last input; build
input order never matters. Source-pin changes (`physical_snapshot_hash`,
`logical_source_rows_hash`, `ingestion_run_id`) change `dataset_id`; path
relocation and `created_at` never do. Row versions not covered by a
`CanonicalBuildPin` and gap references naming an unpinned build or
disagreeing with the pinned gap content fail closed.

## 11. Feature / Label / implementation spec drift

Semantically identical YAML (key order, comments, blank lines, LF/CRLF,
non-semantic requirements-list order) hashes identically. Every semantic
change — input fields or their authoritative order, `transform_ref`,
parameter values/types, required versions, output logical type/nullability,
observation window, horizon, alignment rule, cross-trading-day policy and
boundary rule — changes the content ID, the SpecPin, and `dataset_id`.
Duplicate `(kind, name, version)` pins fail closed; pins reject wrong
containers (FEATURE/LABEL/SPLIT). `ImplementationPin` hash or version
changes change `dataset_id`. `transform_ref` is a declaration only: never
imported, never executed, never network-fetched. Unknown/future schema
versions fail closed.

## 12. Completion and known-gap limitations

Quality-FAIL and fully MISSING keys never produce complete snapshot
references or canonical rows; COMPLETE snapshots do. Canonical/PIT never
generate synthetic OHLCV, interpolation, forward fill, zero fill, or
placeholder bars; internal gaps are sidecar records, never rows. Absence of
known gaps never implies a complete session or label horizon: PIT samples
and diagnostics carry no `label_status` and no completeness inference, and
the split layer requires explicit caller-provided `label_status` and
`actual_label_end_time`. CompletionSummary and GapReference semantics are
identity-bearing; forged counts fail closed.

## 13. Timezone and DST semantics

Naive Feature/Label/PIT/Split instants fail closed. Equivalent timezone
representations of one instant normalize to the same UTC microsecond and
produce identical `sample_key` / content / split identities. Splits assign
by the declared boundary timezone's local date, never the UTC date. The
cross-day label check uses the explicit stored `market_calendar_date`, never
the system local timezone. DST spring-forward and fall-back next-local-
midnight boundaries are constructed on the local calendar date (never a
fixed `+24h`), and invalid IANA names fail closed with no system-local
fallback. Sub-microsecond precision truncates to the contract's microsecond
precision consistently.

## 14. Cross-layer canary

The suite chains, fully offline:

```text
audited COMPLETE synthetic snapshot
    -> Canonical materialization
    -> verified Canonical reader
    -> PIT sample assembly
    -> Feature / Label SpecPin
    -> explicit ChronologicalSplitSample
    -> chronological split assignment
    -> DatasetIdentityInput
    -> dataset_id
```

The canary asserts: Feature association rows are exactly the PIT-visible
rows; Label rows are separated from Feature rows; selected canonical row
versions are covered by the build pins; `adjustment == NONE`; the label
status is explicit; the actual label end decides the purge; Feature/Label/
Split pins enter the correct containers; `dataset_id` is a 64-character
lowercase SHA-256; identical inputs (including input-order changes) produce
identical results; and any identity-bearing threat mutation changes
`dataset_id` or fails closed. This is an offline combination check of
existing contracts — it is not the final Dataset builder and it neither
constructs a DatasetManifest nor writes Dataset Parquet.

## 15. Deterministic / offline test guarantees

Fixed dates, fixed run IDs, fixed hashes; `tmp_path`-isolated files; no
current time, randomness, mtime dependence, input-order dependence, or
local-timezone dependence; no OpenD, no network, no real market data, no
repo-directory writes, no model training, no trading signals. Private test
helpers are never imported from other test modules; each test file builds
its own minimal deterministic fixtures.

## 16. What this suite does not prove

- It does not prove that adjusted-price data has historical
  corporate-action point-in-time correctness (the current defense is
  fail-closed NONE only).
- It does not prove that leading/trailing/session gaps unobservable from the
  current data do not exist.
- It does not compute or validate any ML model.
- It does not prove that the future Dataset builder is complete.
- It does not exhaustively prove that every economically meaningful leak is
  covered.
- It never accesses real markets or OpenD.
