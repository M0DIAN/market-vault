# MarketVault v0.5.0 Direction: Deterministic Dataset Builder

Status: proposed (PR-1 of the v0.5.0 sequence; no runtime code changes)

This document defines the scope, non-goals, and design direction for the
V0.5.0 "Deterministic Dataset Builder" phase. It is a planning document; no
code, schema, CLI, or version changes are part of this PR. The authoritative
boundary decision is captured separately in
[ADR 0002](adr/0002-deterministic-dataset-builder-boundary.md). The v0.4.0
foundation this phase builds on is documented in
[v0_4_0_direction.md](v0_4_0_direction.md) and its contracts under
[contracts/](contracts/).

## 1. V0.4.0 current capabilities

V0.4.0 shipped the Canonical Dataset and ML Foundation:

- **Immutable Canonical builds**: deterministic in-memory builder over
  audited COMPLETE snapshots, explicit Parquet schema, conservative gap
  sidecar, resolution JSONL, immutable manifest, atomic commit, EMPTY
  builds, and deterministic identities (`canonical_content_id`,
  `resolution_content_id`, `gap_content_id`, `canonical_build_id`) —
  [contracts/canonical_market_bar_materialization.md](contracts/canonical_market_bar_materialization.md).
- **Verified Canonical reader**: `load_verified_canonical_build` — the only
  public read path into committed builds, strict fail-closed verification
  (schema, identities, provenance binding, gap re-derivation, counts).
- **Two-clock PIT sample assembly**: `assemble_point_in_time_samples` with
  `market_available_at` (market clock) and `archive_available_at` (archive
  clock), half-open windows, `dataset_as_of` cutoffs, cross-build
  reconciliation, `sample_key` / `sample_version_id`, and the fixed
  sample-to-row association content contract —
  [contracts/point_in_time_sample_assembly.md](contracts/point_in_time_sample_assembly.md).
- **Versioned Feature/Label spec contracts**: frozen typed `FeatureSpec` /
  `LabelSpec`, strict fail-closed YAML parsing, deterministic semantic
  content IDs, conversion to `SpecPin` / `DatasetIdentityInput` —
  [contracts/feature_label_spec_versioning.md](contracts/feature_label_spec_versioning.md).
- **Chronological splits and actual-label-end purging**: frozen
  `ChronologicalSplitSpec`, explicit caller-provided `label_status`,
  TRAIN/VALIDATION purge by `actual_label_end_time` against DST-safe
  exclusive boundaries, fixed split-assignment logical content, deterministic
  split result identity —
  [contracts/chronological_splits_and_purging.md](contracts/chronological_splits_and_purging.md).
- **Dataset identity/manifest core**: explicit logical `DatasetSchema`
  model, `dataset_schema_id`, `logical_dataset_content_id`, `dataset_id`
  over all identity-bearing `DatasetIdentityInput` fields, the versioned
  `DatasetManifest`, deterministic serialization, strict validation, and
  atomic standalone manifest writing —
  [contracts/derived_dataset_manifest.md](contracts/derived_dataset_manifest.md).
- **Eight-threat leakage regression suite**: offline cross-contract matrix
  covering future-bar, archive-time, label-cross-split,
  adjustment/corporate-action, snapshot-substitution, spec-drift,
  completion-ambiguity, and timezone-misattribution threats —
  [contracts/leakage_threat_model_regression.md](contracts/leakage_threat_model_regression.md).

## 2. What v0.4.0 does not do yet

- No Feature or Label value is computed; no transform is imported, executed,
  or hashed into an `ImplementationPin` by the runtime.
- No final Dataset builder orchestration exists: nothing connects verified
  Canonical builds, PIT assembly, specs, and splits into one build.
- No Dataset build directory, no `_SUCCESS`, no Dataset Parquet output.
- No actual `actual_label_end_time` is produced by a Label computation; the
  split layer receives explicit caller-provided facts only.
- No Dataset CLI (`dataset-build` / `dataset-verify` / `dataset-inspect`).
- No label completeness inference: "some label rows were seen" never proves
  a complete horizon; the gap sidecar records only confirmable internal
  nominal-spacing gaps and cannot prove full coverage.

## 3. V0.5.0 overall goal

Turn the v0.4.0 contract chain into one executable, verifiable, reproducible
pipeline:

```text
Verified Canonical Builds
    -> PIT sample assembly
    -> Feature transform execution
    -> Label transform execution
    -> label status / actual_label_end_time
    -> chronological split and purge
    -> logical dataset content
    -> deterministic dataset_id
    -> immutable Dataset materialization
    -> verified Dataset reader
    -> Dataset CLI
```

The goal is a **Deterministic Dataset Builder**: a documented, pinned,
fail-closed pipeline that materializes immutable Dataset artifacts whose
logical content, identity, and verification are reproducible from the
declared inputs alone — with no hidden "latest directory" scanning, no
runtime magic, and no network.

## 4. Non-goals

- ML training, model selection, hyperparameter tuning.
- Backtesting, walk-forward frameworks, feature importance.
- Online feature store, real-time inference, automatic trading.
- Adjusted-price PIT and corporate-action reconstruction
  (`adjustment = NONE` remains the only policy).
- Cross-trading-day labels (opt-in is designed but not executed in v0.5).
- A Yahoo provider, any second market-data provider, or multi-provider
  Canonical reconciliation.
- Automatic re-collection or repair of Raw/Curated/Canonical data at build
  time.
- Arbitrary user-code execution from specs (see the transform registry).
- A large indicator catalog; v0.5 starts with the minimal OHLCV transform
  set from ADR 0002, and implementation PRs may narrow it further.

## 5. Dataset build inputs and outputs

Inputs (explicit, pinned per build, per ADR 0002 decision 2):

```text
one or more verified Canonical builds
FeatureSpec per feature
LabelSpec per label
ChronologicalSplitSpec
optional dataset_as_of (UTC)
dataset scope (code, trade dates, interval, adjustment NONE, requested_session)
transform implementation versions (registry-bound)
output schema version
serialization format version
```

All identity-bearing inputs enter `DatasetIdentityInput` and therefore
`dataset_id`. The builder never scans "the latest Canonical directory".

Outputs (initial materialized layout):

```text
data/datasets/<dataset_id>/
    dataset.parquet       # the sample matrix, fixed schema
    manifest.json         # versioned DatasetManifest (dataset_id recomputed)
    build_report.json     # recorded facts only, never identity-bearing
    feature_spec.yaml     # normalized feature spec content + content ID
    label_spec.yaml       # normalized label spec content + content ID
    split_spec.yaml       # normalized split spec content + content ID
```

## 6. Transform registry

- Built-in, registered, versioned transforms only; the registry is the sole
  resolution authority for `transform_ref`.
- Each implementation declares: stable transform name; implementation
  version; input requirements; output column names and dtypes; parameter
  schema; lookback / lookforward requirement; session / trading-day boundary
  policy; null / incomplete policy; and a deterministic implementation
  fingerprint (stable SHA-256 over canonical source and registration
  metadata, never a memory address).
- The registry emits `ImplementationPin(name, version, content_sha256)`
  entries into `DatasetIdentityInput.implementations`.
- Forbidden: YAML-imported arbitrary modules, `eval`, `exec`, dynamic user
  code, unversioned callbacks, and any memory-address-based identity.

## 7. Feature execution

- Input rows must satisfy `market_available_at <= feature_window_close`
  (and `archive_available_at <= dataset_as_of` when `dataset_as_of` is set);
  the PIT assembly contract already enforces this, and the builder re-uses
  it instead of implementing a second clock check.
- Features compute over the assembled PIT feature rows of each sample; the
  declared lookback must be satisfiable by the window, and warm-up rows
  follow the transform's declared null policy (never silent fabrication).
- Output columns are named and typed by the `FeatureSpec`; the output
  logical type must match the spec, and any drift fails the build.
- Non-finite output (NaN, +Inf, -Inf) fails the build — it never enters the
  Dataset silently.

## 8. Label execution

- Labels read real future rows after the feature window close, subject to
  the `LabelSpec` horizon, the default no-cross-trading-day policy, and
  `adjustment = NONE`.
- The label's actual inputs are the PIT label rows of the sample; missing
  required actual inputs produce `label_status: INCOMPLETE`.
- `actual_label_end_time` is the market availability instant of the last
  actual label input row — the label window never fabricates an end from the
  nominal horizon.
- INCOMPLETE labels are excluded from TRAIN/VALIDATION/TEST samples by
  default (`incomplete_label_policy: EXCLUDE` in the split spec).

## 9. `actual_label_end_time` and INCOMPLETE

- `actual_label_end_time`: the market-clock instant at which the last actual
  label input row became available (its `market_available_at`), normalized
  to UTC microseconds. It must not precede `feature_window_close`.
- `label_status`: COMPLETE or INCOMPLETE, decided by the Label execution
  from actual inputs — never by the absence of gap records, never inferred
  from PIT diagnostics alone.
- These are the exact facts the split layer requires on
  `ChronologicalSplitSample`; the builder constructs them explicitly from
  PIT + Label results (the construction path documented in the v0.4.0 split
  contract).

## 10. Split / purge integration

- `assign_chronological_splits` consumes the per-sample
  `ChronologicalSplitSample` facts: `sample_key`, `sample_version_id`,
  `feature_window_close`, `label_status`, `actual_label_end_time`.
- TRAIN/VALIDATION purge by the actual label end against DST-safe
  next-local-midnight exclusive boundaries; TEST has no fourth-split purge.
- Every sample row in the Dataset carries its assignment status, reason
  code, and purge boundary (when applicable); the fixed split-assignment
  content identity and `chronological_split_result_id` become part of the
  Dataset provenance.

## 11. Dataset logical schema

The Dataset sample matrix uses a fixed logical `DatasetSchema` with
authoritative field order grouped as:

```text
sample identity     sample_key, sample_version_id
timing facts        feature_window_close, actual_label_end_time (nullable),
                    label_status, dataset_as_of (when enabled)
feature outputs     <per FeatureSpec, fixed name/type>
label outputs       <per LabelSpec, fixed name/type>
split assignment    feature_window_close_date, nominal_split, final_split,
                    assignment_status, reason_code, purge_boundary
```

- Fixed column order; fixed dtypes (the v0.4.0 scalar set: string, int64,
  float64, bool, date32, timestamp_us_utc); time fields UTC only.
- Null representation is `null`, never NaN; NaN / ±Infinity fail closed.
- Row order is deterministic: sort by `code`, then `feature_window_close`,
  then `sample_key`.
- The logical content hash is the existing `logical_dataset_content_id`
  over this schema and its rows.

## 12. Logical content hash

- `logical_dataset_content_id` (v0.4.0) is the final content hash: a
  versioned SHA-256 over `dataset_schema_id` and every logical row encoded
  under that schema; row order never affects it, row multiplicity does.
- It never depends on Parquet bytes, file paths, `built_at`, or local
  timezone.
- The builder computes it in staging from the actual rows and feeds it into
  `DatasetIdentityInput` for `dataset_id` finalization.

## 13. `dataset_id` finalization

Per ADR 0002 decision 9, resolving the content-hash cycle:

1. execute the complete build in staging;
2. compute the final logical content hash;
3. construct `DatasetIdentityInput` with all pins and compute `dataset_id`;
4. build and verify the final manifest (`build_dataset_manifest` recomputes
   `dataset_id` independently);
5. atomically commit under the `dataset_id` directory name.

Never: timestamped directories as identity; `built_at` in `dataset_id`;
absolute output paths in `dataset_id`.

## 14. Atomic materialization

- Staging directory on the same filesystem; write dataset.parquet,
  manifest.json, spec files; compute and record file SHA-256s; commit with
  an atomic rename; `_SUCCESS` semantics follow the Canonical pattern.
- Immutable final directories, no overwrite.
- Existing verified identical build -> idempotent return
  (`created_new_build=False`), nothing rewritten.
- Existing conflicting build -> fail closed; the conflict is reported, never
  silently overwritten.
- Staging residue (a leftover staging directory from a crashed build) is
  detected and reported as a failure condition, never silently adopted.

## 15. Verified Dataset reader

One public read entry point (planned: `load_verified_dataset(build_dir)`),
fail-closed on:

- directory name vs `dataset_id`;
- manifest schema version and shape;
- recomputed `dataset_id` from identity-bearing fields;
- recomputed logical content hash from the actual Parquet rows;
- Parquet schema, column order, dtypes, row count;
- recorded file SHA-256s vs actual bytes;
- spec pins, canonical pins, gap references, split identity;
- exact file whitelist — unexpected files fail;
- NaN / Infinity presence — any occurrence fails (per the final contract).

The reader never writes, repairs, or rewrites anything.

## 16. Dataset CLI

Planned commands (not implemented in this PR):

- `dataset-build` — execute a pinned Dataset build (explicit inputs; never
  auto-download, never auto-refresh Canonical).
- `dataset-verify` — run the verified reader against a Dataset directory.
- `dataset-inspect` — print the manifest and logical summary.

The CLI never trains, backtests, or trades.

## 17. Failure model

Fail-closed, never "warn then look successful". At least:

```text
unknown transform
transform version mismatch
invalid parameters
missing required input columns
incompatible interval
insufficient lookback
insufficient label horizon
cross-day label violation
unsupported adjustment
archive cutoff violation
non-finite output
duplicate sample identity
output dtype mismatch
output column collision
logical hash mismatch
dataset_id mismatch
existing conflicting final directory
corrupted Canonical pin
corrupted spec pin
inconsistent split result
staging residue
```

Every condition either fails the build with a structured error before any
formal artifact is published, or produces the designed explicit outcome
(INCOMPLETE label status, EXCLUDED/PURGED split assignment). A warning that
leads to a "seemingly successful" formal Dataset is forbidden.

## 18. Determinism model

- Identical pinned inputs (verified Canonical builds, spec content hashes,
  implementation versions, scope, `dataset_as_of`, schema/format versions)
  produce identical logical content, identical `dataset_id`, and identical
  verification outcomes.
- Deterministic: normalized rows, column order, dtypes, row sort,
  JSON serialization, UTC time fields, hash encodings.
- Byte-identical Parquet is promised only with pinned PyArrow and writer
  options; without that pin, only the logical content contract holds.
- Input order, filesystem mtimes, `created_at`/`built_at`, local timezone,
  and memory addresses never participate in any identity.

## 19. PIT / leakage safety requirements

The v0.4.0 eight-threat model is extended by execution-layer regressions:

- future-feature leakage (`market_available_at` clock),
- archive cutoff (`archive_available_at` / `dataset_as_of`),
- incomplete labels (INCOMPLETE never silently COMPLETE),
- actual label end (never nominal horizon close),
- cross-day rejection (default policy, no hidden override),
- split-crossing purge (actual-label-end rule),
- transform drift (implementation fingerprint / version changes change
  `dataset_id`),
- spec drift (semantic content ID),
- source snapshot substitution (Canonical pins),
- row/column order and dtype stability,
- timezone / DST correctness (declared boundary timezone, UTC microseconds).

## 20. Compatibility

- V0.1-V0.4 CLI behavior unchanged; Raw/Curated data and the DuckDB catalog
  untouched.
- Canonical builds, their readers, and all published v0.4.0 identities
  unchanged; existing manifests remain valid.
- The v0.4.0 tag and Release remain as-is; no existing identity algorithm or
  version constant is modified.
- Package version stays 0.4.0 through PR-9 of this sequence; the bump to
  0.5.0 happens only in PR-10.

## 21. Test strategy

All tests offline and deterministic:

- micro Canonical fixtures (fixed dates, run IDs, hashes); no OpenD, no
  network, no real market data as a CI requirement;
- DST spring-forward / fall-back; session boundaries; early-close behavior
  without unsupported completeness inference;
- actual label input availability; INCOMPLETE handling; actual label end;
- deterministic rebuild equivalence; input-permutation equivalence;
- corrupted artifacts (Parquet, manifest, `_SUCCESS`, spec files); no-write
  boundary; V0.3/V0.4 compatibility assertions;
- the leakage items of section 19 each with a positive control and a defense
  test, extending the v0.4.0 regression matrix.

## 22. Proposed PR sequence

Each PR is independent and reviewable, runs the full offline suite, and is
executed in its own Claude Code session; no two phases share one PR:

```text
PR-1   docs: plan v0.5.0 deterministic dataset builder
       (this PR: ADR 0002 + direction document only)

PR-2   feat: transform implementation registry and execution contracts
       - registry protocol, registration metadata, parameter validation,
         implementation fingerprints; no Dataset computation

PR-3   feat: execute deterministic built-in Feature transforms
       - the minimal OHLCV feature set; strict
         market_available_at / dataset_as_of enforcement

PR-4   feat: execute deterministic built-in Label transforms
       - the minimal label set; real label_status and
         actual_label_end_time; no cross-trading-day by default

PR-5   feat: orchestrate end-to-end Dataset builds
       - connects verified Canonical, PIT, Feature, Label, Split/Purge,
         DatasetIdentityInput

PR-6   feat: materialize immutable Dataset artifacts
       - staging, logical content hash, dataset_id finalization, Parquet,
         manifest, atomic commit, idempotency and conflict handling

PR-7   feat: add verified Dataset reader

PR-8   feat: add Dataset CLI (dataset-build / dataset-verify /
       dataset-inspect)

PR-9   test: add end-to-end Dataset determinism and leakage regression
       - future-feature leakage, archive cutoff, incomplete labels,
         actual label end, cross-day rejection, split crossing purge,
         transform drift, spec drift, source snapshot substitution,
         row/column order, staging crash recovery, immutable conflict,
         rebuild equivalence, corrupted Parquet, corrupted manifest,
         NaN/Infinity, timezone/DST

PR-10  chore: prepare v0.5.0 release
       - version sync, README, CHANGELOG, release notes, package smoke
```

Until PR-10, the package version remains 0.4.0. A Dataset builder, CLI, and
ML are never implemented in the same PR.

## 23. Acceptance criteria

- A pinned build over micro fixtures produces a Dataset directory whose
  manifest verifies end-to-end with `load_verified_dataset` (or the
  equivalent public reader).
- Rebuilding from identical inputs reproduces the identical logical content,
  identical `dataset_id`, and an idempotent result; any input change that
  matters changes `dataset_id` or fails closed.
- Feature rows satisfy the PIT clocks; labels carry real
  `actual_label_end_time` and `label_status`; INCOMPLETE labels are excluded
  from TRAIN/VALIDATION/TEST by default; cross-day labels fail closed.
- NaN / Infinity never appear in a final Dataset; corrupted or conflicting
  artifacts fail closed.
- All V0.3/V0.4 tests keep passing unchanged; no runtime identity algorithm
  or version constant changed; package version stays 0.4.0 until PR-10.

## 24. Shipped-versus-remaining

The shipped v0.4.0 foundation implements the contracts and models — verified
Canonical builds, PIT assembly, versioned Feature/Label specs, chronological
split/purge, Dataset identity/manifest — but no final Dataset builder, no
Dataset Parquet output, and no Dataset CLI exist. This v0.5.0 direction
proposes the executable pipeline that connects them. After PR-10, v0.5.0
ships the pipeline itself; ML training, backtesting, and trading remain out
of scope for the project.
