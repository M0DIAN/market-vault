# Chronological Splits and Actual-Label-End Purging Contract

Status: implemented in the v0.4.0 chronological split foundation
(`market_vault.dataset.split_models` and `market_vault.dataset.splits`).

This contract defines the deterministic chronological train/validation/test
split and actual-label-end purge foundation: the frozen
`ChronologicalSplitSpec`, the explicit caller-provided label status and
actual label end facts, nominal assignment by the local-market date of the
feature window close under an explicitly declared IANA boundary timezone,
exclusion of INCOMPLETE labels, TRAIN/VALIDATION purge by the actual label
end against DST-safe next-local-midnight exclusive boundaries, the fixed
split-assignment logical schema and content, the deterministic split result
identity, and the existing
[SpecPin](derived_dataset_manifest.md) /
`dataset_id` integration. Related decisions are in
[ADR 0001](../adr/0001-canonical-ml-dataset-boundary.md) and
[v0_4_0_direction.md](../v0_4_0_direction.md) (sections 11-12); the sample
assembly contract is
[point_in_time_sample_assembly.md](point_in_time_sample_assembly.md).

This PR implements the **split/purge contract foundation only**. It does not
compute Feature or Label values, execute transforms, read `LabelSpec.horizon`
or any nominal horizon, infer label completeness from PIT diagnostics, build
samples, build the final DatasetManifest, write Dataset Parquet or a Dataset
build directory, create a `_SUCCESS`, add CLI commands, create DuckDB views,
access OpenD or the network, or modify Raw / Curated / Canonical data. The
package version and dependencies are unchanged.

## 1. Scope / non-goals

**In scope:** frozen split spec; explicit boundary timezone; feature-window-
close local-date assignment; explicit caller-provided `label_status`;
`actual_label_end_time` purge for TRAIN and VALIDATION; DST-safe exclusive
boundaries; deterministic schema/content/result identities; SpecPin
(kind=SPLIT) integration; fail-closed validation.

**Out of scope (explicit):**

- Feature/Label value computation and transform execution;
- automatic label-completeness inference (PIT rows never become COMPLETE);
- final Dataset builder, DatasetManifest orchestration, Dataset Parquet
  writer, Dataset build directory, `_SUCCESS`;
- Dataset CLI, DuckDB views, OpenD calls, network access;
- random / group / stratified split, walk-forward / rolling CV, embargo;
- the PR-9 full leakage threat-model regression suite;
- package version bump, dependency changes, CI workflow changes.

## 2. Data-flow boundary

```text
explicit split sample timing facts
    -> chronological nominal assignment
    -> incomplete-label exclusion
    -> actual-label-end purge
    -> deterministic split-assignment content
```

## 3. Frozen SplitSpec

`ChronologicalSplitSpec` is frozen and validates at construction:

- `kind` is fixed to `SPLIT`; it is not a constructor parameter and cannot be
  forged with `dataclasses.replace`.
- `spec_schema_version` must be exactly
  `market-vault-chronological-split-spec-v1`. Unknown, future, or old schema
  versions fail closed.
- `name` matches `^[a-z][a-z0-9_]*$`; `version` matches `^v[1-9][0-9]*$`.
- `boundary_timezone` must be a non-empty safe string loadable by
  `zoneinfo.ZoneInfo`. There is no system-local-timezone fallback and no
  naive/implicit interpretation.
- The boundary dates accept `datetime.date` or a strict ISO `YYYY-MM-DD`
  string; a `datetime` is rejected and never silently truncated to its date.
- Strict ordering: `train_end_date < validation_end_date < test_end_date`.
- v1 accepts exactly the four fixed rule values:
  `assignment_rule = FEATURE_WINDOW_CLOSE_DATE`,
  `purge_rule = ACTUAL_LABEL_END`,
  `incomplete_label_policy = EXCLUDE`,
  `out_of_range_policy = EXCLUDE`. No hidden defaults; every field enters the
  content identity.

## 4. Explicit boundary timezone

Nominal assignment and the purge boundaries are interpreted in the IANA
timezone explicitly declared by the split spec (e.g.
`America/New_York`). The UTC date of an instant is **never** used as a
substitute for the declared market-local date, and the local timezone of the
machine running the splitter never participates.

## 5. Feature-window-close local-date assignment

For each sample, `feature_window_close` is converted to the spec's boundary
timezone and its local date is taken:

```text
local_date <= train_end_date                 -> TRAIN
train_end_date < local_date <= validation_end_date -> VALIDATION
validation_end_date < local_date <= test_end_date  -> TEST
local_date > test_end_date                   -> EXCLUDED
                                             (FEATURE_CLOSE_AFTER_TEST_END)
```

There is no randomization, no shuffling, no grouping by input row number, and
no grouping by sample-key hash. Assignment is purely chronological.

## 6. Exact date intervals

- TRAIN covers local dates `[..., train_end_date]`.
- VALIDATION covers local dates `(train_end_date, validation_end_date]`.
- TEST covers local dates `(validation_end_date, test_end_date]`.
- Anything after `test_end_date` is out of range and EXCLUDED.

## 7. Explicit caller-provided label status

`label_status` is declared by the caller (`COMPLETE` or `INCOMPLETE`) on every
`ChronologicalSplitSample`; this layer never infers it. In particular, PIT
assembly only records observed rows, known internal gaps, and clock exclusion
counts — it has no authoritative session schedule, so "some label rows were
seen" never proves a complete horizon. The future Label computation / Dataset
builder constructs `ChronologicalSplitSample` explicitly from PIT + Label
results.

## 8. `actual_label_end_time` definition

`actual_label_end_time` is the market instant the last label input actually
becomes available, as produced by the real Label generation/observation
process. It must be timezone-aware (normalized to UTC microseconds) and must
not be before `feature_window_close`.

- COMPLETE labels **must** carry an `actual_label_end_time`.
- INCOMPLETE labels may carry none (no actual label-end fact at all) or a
  partial observation; either way v1 excludes them.

## 9. Why nominal-horizon purge is forbidden

A nominal horizon (`LabelSpec.horizon.value`, an observation-window nominal
end, a `request.label_window_close` substitute, a fixed maximum horizon, a
fixed bar count, a fixed-minute purge, or an empirical embargo) is a
**specification**, not an **observation**. Purge decisions must use the fact
of when the label actually ended, so:

```text
actual_label_end_time is the only purge time fact.
```

`LabelSpec.horizon` is never read by this layer, and no fixed minutes, bars,
or embargo lengths are configured or used.

## 10. Next-local-midnight exclusive boundaries

To avoid "last instant of the day" and DST ambiguity, the TRAIN and
VALIDATION purge boundaries are the exclusive instants of **local midnight on
the day after the boundary date**, converted to UTC:

```text
train_boundary_exclusive      = local midnight at (train_end_date + 1 day)
                                in spec.boundary_timezone, converted to UTC
validation_boundary_exclusive = local midnight at (validation_end_date + 1 day)
                                in spec.boundary_timezone, converted to UTC
```

Semantics:

- `actual_label_end_time < boundary_exclusive` — did not cross; kept.
- `actual_label_end_time >= boundary_exclusive` — has entered the next split
  date range; purged.

So ending exactly at the last representable microsecond of the boundary date
is allowed, and ending exactly at the next local midnight is purged.

## 11. DST-safe boundary construction

The next calendar date is constructed first (`end_date + 1 day` on the local
calendar) and then its local midnight is converted to UTC. A fixed
`timedelta(hours=24)` is never used, because a DST day is not 24 hours:

- spring-forward: the next local midnight is `00:00` of the pre-transition
  offset (e.g. `2024-03-10 00:00 EST` in `America/New_York`, `05:00 UTC`), not
  `+24h` (which would land on `00:00 EDT`, `04:00 UTC`);
- fall-back: the next local midnight is the first (fold=0) occurrence (e.g.
  `2024-11-03 00:00 EDT`, `04:00 UTC`), not `+24h` (which would land on
  `00:00 EST`, `05:00 UTC`).

Fold-ambiguous midnights deterministically use the first occurrence.

## 12. INCOMPLETE labels are excluded by default

Under the v1 `EXCLUDE` policy, any sample with `label_status == INCOMPLETE`
is EXCLUDED with reason `INCOMPLETE_LABEL` — even when it carries a partial
`actual_label_end_time`. An INCOMPLETE label is never purged (exclusion
precedes purge) and never assigned.

## 13. TRAIN/VALIDATION purge

Fixed per-sample processing order:

1. nominal split by feature close local date;
2. local date after `test_end_date` -> EXCLUDED,
   `FEATURE_CLOSE_AFTER_TEST_END`;
3. `label_status == INCOMPLETE` -> EXCLUDED, `INCOMPLETE_LABEL`;
4. nominal TRAIN with `actual_label_end_time >= train_boundary_exclusive`
   -> PURGED, `ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY`,
   `purge_boundary = train_boundary_exclusive`;
5. nominal VALIDATION with
   `actual_label_end_time >= validation_boundary_exclusive`
   -> PURGED, `ACTUAL_LABEL_END_CROSSES_VALIDATION_BOUNDARY`,
   `purge_boundary = validation_boundary_exclusive`;
6. otherwise ASSIGNED with `final_split == nominal_split`.

## 14. TEST has no fourth-split purge

A TEST sample is never purged for an actual label end after `test_end_date`:
there is no fourth split for its label window to leak into. Label integrity
of TEST samples is controlled exclusively by the explicit `label_status`.
This PR introduces no outer Dataset-scope completeness inference.

## 15. Assignment status and reason codes

Stable machine codes only (never free-form text or error stacks):

```text
SPLIT_STATUS_ASSIGNED / PURGED / EXCLUDED

INCOMPLETE_LABEL
FEATURE_CLOSE_AFTER_TEST_END
ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY
ACTUAL_LABEL_END_CROSSES_VALIDATION_BOUNDARY
```

Assignment invariants (enforced at construction):

- ASSIGNED: `final_split == nominal_split`, `reason_code` and
  `purge_boundary` are None, label COMPLETE;
- PURGED: nominal TRAIN or VALIDATION only, `final_split` None, the matching
  crossing reason, a purge boundary, label COMPLETE;
- EXCLUDED: `final_split` None, `INCOMPLETE_LABEL` (nominal split present,
  label INCOMPLETE) or `FEATURE_CLOSE_AFTER_TEST_END` (nominal split None).

`ChronologicalSplitDiagnostics` verifies:
`sample_count == assigned + purged + excluded`;
`assigned == train + validation + test assigned`;
`purged == train_purged + validation_purged`;
`excluded == incomplete_label_excluded + out_of_range_excluded`. Counts are
real ints; bools never pass.

## 16. Deterministic schema, content, and result identities

The fixed split-assignment logical schema (authoritative field order):

```text
sample_key                    string, non-null
sample_version_id             string, non-null
feature_window_close          timestamp_us_utc, non-null
feature_window_close_date     date32, non-null
label_status                  string, non-null
actual_label_end_time         timestamp_us_utc, nullable
nominal_split                 string, nullable
final_split                   string, nullable
assignment_status             string, non-null
reason_code                   string, nullable
purge_boundary                timestamp_us_utc, nullable
```

- `split_assignment_schema_id` and `split_assignment_content_id` reuse the
  existing `dataset_schema_id` / `logical_dataset_content_id` encodings; no
  second logical dataset hash scheme is introduced.
- Row order never affects the content ID; row multiplicity does. The assign
  API rejects duplicate sample keys before any row is produced. Zero samples
  produce a deterministic zero-row content ID; no placeholder row is
  fabricated.
- `chronological_split_result_id` is a versioned SHA-256 binding
  `CHRONOLOGICAL_SPLIT_RESULT_ID_VERSION`, `CHRONOLOGICAL_SPLITTER_VERSION`,
  `SPLIT_ASSIGNMENT_SCHEMA_VERSION`, the split spec content ID, the split
  assignment schema ID, the split assignment content ID, and the sample
  count. It never contains input order, `built_at`, current time, local
  timezone, file paths, manifest paths, or Python `repr()`.
- `ChronologicalSplitResult` recomputes every identity at construction: the
  spec pin, the per-sample `feature_window_close_date` (re-derived from the
  spec boundary timezone), PURGED `purge_boundary` values (re-derived from
  the spec dates), the schema, the schema/content/result IDs, the assignment
  rows, and the diagnostics. A manually constructed or
  `dataclasses.replace`-modified inconsistent result fails closed.

## 17. SpecPin / dataset_id integration

`chronological_split_spec_pin(spec)` converts a split spec to the existing

```python
SpecPin(kind="SPLIT", name=..., version=..., content_sha256=...)
```

No new pin model is introduced, `SpecPin` is unchanged, and the `dataset_id`
algorithm is unchanged. Pins enter `DatasetIdentityInput.split_spec`
directly; container semantics are enforced by the identity core (a SPLIT pin
may not sit in `feature_specs` / `label_specs`, and a non-SPLIT pin may not
sit in `split_spec`). Identical split semantics produce identical pins and
identical `dataset_id`; any boundary/timezone/rule semantic change changes
both.

## 18. Duplicate sample handling

Duplicate `sample_key` values in one split result fail closed — even when the
`sample_version_id` or content differs. There is no silent deduplication.

## 19. Fail-closed behavior

All split-layer failures surface as `SplitValidationError` (a subclass of the
existing `DatasetError`). `ZoneInfoNotFoundError`, `TypeError`, `ValueError`,
`KeyError`, and unexpected `DatasetError` shapes never leak. Unknown schema
versions, invalid timezones, naive instants, malformed sample identities,
inconsistent assignments, tampered IDs, and tampered diagnostics all fail
closed.

## 20. No random split / no shuffle

There is no randomness, no shuffling, no stratification, no grouping, and no
walk-forward/rolling window logic. Input order is never semantic.

## 21. PIT completeness boundary

This PR does not modify `PITSample` or `PITAssemblyResult`, does not add a
convenience function that auto-declares COMPLETE from a `PITAssemblyResult`,
and never executes `PITSample -> label_status COMPLETE`. The future caller
constructs `ChronologicalSplitSample` explicitly from PIT + Label results
(`sample_key`, `sample_version_id`, `feature_window_close`, `label_status`,
`actual_label_end_time`); this PR only documents that construction path.

## 22. Remaining non-goals

Feature/Label computation; the final Dataset builder; DatasetManifest
orchestration; the Dataset Parquet writer; the Dataset CLI; walk-forward /
rolling CV; embargo; and the PR-9 full leakage threat-model regression suite.
