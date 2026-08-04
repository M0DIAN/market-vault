# ADR 0002: Deterministic Dataset Builder Boundary

- Status: accepted
- Deciders: MarketVault maintainers
- Date: 2026-08-05
- Related: [ADR 0001](0001-canonical-ml-dataset-boundary.md),
  [v0.4.0 direction](../v0_4_0_direction.md),
  [v0.5.0 direction](../v0_5_0_direction.md)

## Context

V0.4.0 shipped the contracts and foundations: immutable verified Canonical
builds with deterministic identities, the verified Canonical reader, two-clock
point-in-time sample assembly, versioned Feature/Label spec documents,
chronological splits with actual-label-end purging, the Dataset manifest core
with `DatasetIdentityInput` and the deterministic `dataset_id`, and the
eight-threat leakage regression suite. No Feature or Label value is computed,
no transform is executed, no final Dataset build directory or Dataset Parquet
is produced.

V0.5.0 closes that gap with a single executable pipeline: verified Canonical
builds in, immutable Datasets out. The open question is where the builder's
boundary sits: what it may read, how transforms may execute, what the outputs
must guarantee, and what stays out of scope.

Constraints:

- The Canonical layer remains the only new source-of-truth materialized data
  layer; Dataset artifacts are derived build products.
- No ML libraries, no model training, no backtesting, no trading signals.
- No OpenD or network access at build time; no automatic re-collection.
- V0.1-V0.4 data, CLI behavior, identities, and published contracts remain
  unchanged; no existing identity algorithm or version constant is modified.
- Every Dataset must be deterministic, leakage-safe, and verifiable
  fail-closed from documented inputs alone.

## Decision

1. **Dataset authority boundary.** Canonical remains the only new
   long-lived source-of-truth data layer. A Dataset is an immutable derived
   build artifact: it is never authoritative input to another Dataset build,
   and no Dataset is consumed as a builder input. Feature, Label, and Sample
   are computed results defined by versioned specs (FeatureSpec, LabelSpec,
   ChronologicalSplitSpec); they are not another storage layer.

2. **Builder inputs are explicit and pinned.** The Dataset builder must
   receive and pin, per build:

   - one or more **verified Canonical builds** (build directory paths that
     pass `load_verified_canonical_build`, or their verified identities and
     contents),
   - a `FeatureSpec` per feature,
   - a `LabelSpec` per label,
   - a `ChronologicalSplitSpec`,
   - an optional `dataset_as_of` (UTC, normalized),
   - the dataset scope (symbols, trade dates, interval, adjustment,
     requested_session),
   - transform implementation versions (registry-bound),
   - the final `DatasetSchema` (fields, order, types, and nullability;
     its `dataset_schema_id` is derived by the existing v0.4 identity
     contract and enters the existing
     `DatasetIdentityInput.dataset_schema_id` — no new identity input field
     is added and no existing identity algorithm or identity version is
     modified),
   - the serialization format and serialization format version (existing
     `DatasetIdentityInput` fields).

   The builder never scans for "the latest directory" and builds from
   whatever it finds; every input is pinned into `DatasetIdentityInput` and
   therefore into `dataset_id`.

3. **Transform execution boundary.** V0.5 executes only **built-in,
   registered, versioned transforms** from the project's transform registry.
   Forbidden: importing arbitrary Python modules named by YAML; `eval`;
   `exec`; dynamically executing arbitrary user code; unversioned callbacks;
   and any identity derived from a function's memory address
   (`id()`, `repr()`, or object identity). `transform_ref` in a spec is a
   declaration that resolves only against the registry, never against the
   filesystem or the network. Every registered implementation declares:

   - stable transform name,
   - implementation version,
   - input requirements (canonical fields and clocks),
   - output column names,
   - output dtypes,
   - parameter schema (validated, fail-closed),
   - lookback / lookforward requirement,
   - session / trading-day boundary policy,
   - null / incomplete policy (including warm-up handling),
   - deterministic implementation fingerprint (see below).

   **Registry lookup key.** The exact lookup key is the complete
   `transform_ref` string of the existing FeatureSpec/LabelSpec v1 format
   (`module.path:function`). The v1 YAML format is unchanged; short names
   such as `simple_return` are never reinterpreted as a new `transform_ref`
   syntax. Built-in transforms register under stable full references;
   registry metadata may carry a human-readable display name, but that name
   never replaces the identity-bearing `transform_ref`.

   **Implementation fingerprint versioning.** PR-2 must define a versioned
   fingerprint payload contract, including a constant such as
   `TRANSFORM_IMPLEMENTATION_FINGERPRINT_VERSION`. The fingerprint is a
   stable SHA-256 over the implementation's canonical source bytes and its
   registration metadata under that contract. It must exclude: absolute
   file paths, the checkout directory, memory addresses, `repr()`, import
   order, filesystem mtimes, and local newline differences — a normalized
   byte contract is required; "hash the source code" alone is not
   sufficient.

   The registry produces `ImplementationPin(name, version, content_sha256)`
   entries that enter `DatasetIdentityInput.implementations`.

4. **Feature PIT rules.** A Feature transform may only consume rows with

   ```text
   market_available_at <= feature_window_close
   ```

   and, when `dataset_as_of` is set, additionally

   ```text
   archive_available_at <= dataset_as_of
   ```

   A bar whose information only becomes fully visible after the feature
   window close is never consumed — even a single such bar. These rules reuse
   the v0.4.0 PIT assembly contract; the builder does not implement a second
   clock check.

5. **Label rules.** Labels may read real future data after the feature
   window close, subject to:

   - the horizon is explicitly defined by the `LabelSpec` (observation
     window + horizon);
   - the default policy forbids crossing a trading-day boundary
     (`cross_trading_day.allow: false` is the default and the PIT cross-day
     check fails closed);
   - `adjustment = NONE` is the default and the only supported adjustment
     policy in v0.5;
   - `actual_label_end_time` is the market availability instant of the last
     actual label input row — never the nominal horizon close;
   - missing required actual label inputs mark the label
     `label_status: INCOMPLETE`;
   - INCOMPLETE labels are excluded from training, validation, and test
     samples by default;
   - label completeness is never inferred from the absence of gap records.

   **COMPLETE proof boundary.** Label execution may declare
   `label_status: COMPLETE` only when completeness can be proved from the
   actual label input rows: each Label transform registration declares its
   required-input semantics, and the builder must verify the required
   cardinality, alignment, and target/end input are all satisfied. Observed
   partial PIT rows alone never prove completeness, and early-close or
   session-boundary cases are never completed by unsupported inference;
   when completeness cannot be proved, the label is INCOMPLETE.

   **Unsupported in v0.5 (fail closed).** A `LabelSpec` with a
   `TRADING_DAYS` horizon, or with `cross_trading_day.allow: true`, fails
   closed as unsupported at build configuration time: the v1 opt-in
   mechanism exists in the spec contract, but no execution path implements
   it in v0.5. `actual_label_end_time` remains the market availability
   instant of the last actually consumed label input; the nominal horizon
   close can never substitute for it.

6. **Initial built-in transform scope.** The first v0.5 longitudinal
   pipeline covers only basic OHLCV transforms; it does not attempt a large
   indicator catalog at once.

   Candidate initial Feature transform catalog: `simple_return`,
   `log_return`, `rolling_mean`, `rolling_std`, `rolling_volume_mean`,
   `volume_ratio`, `candle_range`, `candle_body`, `time_of_day`, `session`.

   Candidate initial Label transform catalog: `forward_return`,
   `forward_direction`, `maximum_favorable_excursion`,
   `maximum_adverse_excursion`.

   Each implementation PR may deliver a reviewed subset of the candidate
   catalog while the v0.5.0 acceptance scope is finalized explicitly; the
   catalog is a starting point, not a binding minimum. No TA-Lib, no model
   library, and no subjective trading signal is added. Transform outputs are
   numeric facts (returns, ratios, ranges, times, sessions), never
   "bullish/bearish" advice.

7. **Sample output traceability.** Every Dataset sample must be traceable
   to at least:

   - `sample_key`,
   - `sample_version_id`,
   - Canonical row / row-version associations (via the PIT association
     content and the pinned `CanonicalBuildPin`s),
   - the Feature spec pin,
   - the Label spec pin,
   - the transform implementation pins,
   - `feature_window_close`,
   - `actual_label_end_time`,
   - `label_status`,
   - the split assignment,
   - the purge status / reason code (when purged or excluded),
   - `dataset_as_of` (when enabled).

8. **Dataset logical content.** The Dataset sample matrix uses a fixed
   logical `DatasetSchema` (v0.4.0 model) with authoritative field order:
   sample identity (including `code`), timing facts, Feature outputs, Label
   outputs, and split assignment. `code` is a formal Dataset column in every
   row's sample identity — never reconstructed by parsing `sample_key` — so
   a multi-symbol Dataset can always distinguish symbols directly. The
   physical row sort is fixed: `code` ASC, then `feature_window_close` ASC,
   then `sample_key` ASC; the physical sort exists for stable Parquet output
   and a stable reading experience and never modifies any identity algorithm
   (`logical_dataset_content_id` remains row-order-independent per the v0.4
   contract). The materialized column order, dtypes, UTC time fields, and
   null representation (`null`, never NaN) are fixed. NaN and
   positive/negative Infinity are never allowed to enter the final training
   Dataset silently: non-finite Feature or Label output fails the build. The
   logical content hash is the existing `logical_dataset_content_id` over
   the final schema and rows.

9. **`dataset_id` lifecycle.** The builder resolves the potential cycle
   (content hash depends on the build; the ID depends on the content hash)
   as follows:

   1. execute the complete build in staging,
   2. compute the final logical content hash from the actual rows,
   3. construct `DatasetIdentityInput` with the final content hash and all
      pins, and compute `dataset_id`,
   4. build and verify the final `DatasetManifest`
      (`build_dataset_manifest` independently recomputes `dataset_id`),
   5. atomically commit the verified directory under the `dataset_id`
      directory name.

   Forbidden: using a timestamped directory as the final identity;
   `built_at` entering `dataset_id`; absolute output file paths entering
   `dataset_id`.

10. **Dataset materialization.** Formal layout:

    ```text
    data/datasets/<dataset_id>/
        dataset.parquet
        manifest.json
        build_report.json
        feature_specs/
            <name>--<version>--<content_sha256>.yaml
        label_specs/
            <name>--<version>--<content_sha256>.yaml
        split_spec.yaml
        _SUCCESS
    ```

    **Plural spec artifacts.** Each `feature_specs/` and `label_specs/`
    file corresponds to exactly one existing `FeatureSpec` / `LabelSpec`.
    The file content is the normalized deterministic serialization of the
    typed model (including the spec schema version and the semantic content
    ID). The file name is built only from the verified safe `name`,
    `version`, and `content_sha256`; the file set is generated in the stable
    `SpecPin` order, and the manifest `SpecPin`s correspond one-to-one with
    the stored files — missing, duplicate, extra, or hash-mismatched files
    fail closed. Raw YAML bytes and raw file paths never enter the Dataset
    identity. `SpecPin` records only `kind`, `name`, `version`, and
    `content_sha256` — never a path — and nothing in the Dataset directory
    is addressed by a raw source path. `split_spec.yaml` follows the same
    normalized-content rule for the single `ChronologicalSplitSpec`.

    **`_SUCCESS` contract.** `_SUCCESS` is a marker file written **last**,
    after every other artifact, with the same fixed empty UTF-8 format the
    Canonical layer uses; the atomic rename happens only after all files
    including `_SUCCESS` are complete. `_SUCCESS` is **not** an entry in
    `DatasetOutputFile`, which records data artifacts with row counts and
    content roles (mirroring the Canonical manifest). Staging without a
    valid `_SUCCESS` is never adopted; a formal directory with a missing or
    corrupt `_SUCCESS` fails closed in the verified reader.

    **Build report.** `build_report.json` is a recorded, human-readable
    build report and may contain `built_at`, elapsed time, and diagnostics;
    none of these fields ever enter `dataset_id` or any identity. Rebuild
    idempotency is decided by identity and the formal artifacts (`dataset_id`
    directory, manifest, `_SUCCESS`, verified content): when the builder
    finds a verified directory for the same `dataset_id`, it discards the
    new staging report and returns idempotently — the new staging report is
    never identity-compared with the existing report, and non-identity
    timing differences are never misjudged as a conflicting Dataset. The
    contract further fixes: a staging directory (same filesystem), an
    atomic commit (rename), an immutable final directory, no overwrite,
    idempotent return of an existing verified identical build, and
    fail-closed rejection of an existing conflicting build.

11. **Parquet determinism boundary.** Continuing v0.4: logical content
    determinism is guaranteed; schema, column order, row order, and dtypes
    are fixed; the file SHA-256 is recorded in the manifest
    (`DatasetOutputFile`). Byte-identical Parquet across environments is
    never claimed unless PyArrow and every writer option are pinned;
    `dataset_id` never depends on Parquet file bytes.

12. **Verified Dataset reader.** One public read entry point (planned:
    `load_verified_dataset(build_dir)`). The reader fails closed on:
    directory name vs `dataset_id`; manifest schema; `_SUCCESS` presence
    and fixed format (regular file, not a symlink); recomputed `dataset_id`;
    logical content hash; Parquet schema; column order; row count; file
    SHA-256; spec pins; canonical pins; split identity; and — per the
    contract decision — **no unexpected files** and **no NaN/Infinity** in
    the Dataset Parquet. The exact file whitelist is derived from the
    contract: `dataset.parquet`, `manifest.json`, `build_report.json`,
    `_SUCCESS`, `split_spec.yaml`, and exactly the spec files implied by
    the manifest `SpecPin`s — any other file fails.

13. **CLI boundary.** Planned, not implemented by this ADR:
    `dataset-build`, `dataset-verify`, `dataset-inspect`. The CLI never
    auto-downloads market data, auto-refreshes Canonical, trains models,
    backtests, or trades. It wraps explicit user actions only.

14. **Compatibility.** V0.5 preserves: V0.1-V0.4 CLI behavior; Raw/Curated
    data; the DuckDB catalog; Canonical builds and their readers;
    published V0.4.0 identities (`canonical_build_id`, `dataset_id`,
    content IDs, spec content IDs, split result IDs); the v0.4.0 tag and
    Release; and existing manifests. No existing identity algorithm or
    version constant is modified; new v0.5 algorithms (transform
    fingerprints, dataset build identities) are additive.

15. **Explicit non-goals.** ML training; model selection; hyperparameter
    tuning; backtesting; walk-forward frameworks; feature importance;
    online feature stores; real-time inference; automatic trading;
    adjusted-price PIT; corporate-action reconstruction; cross-trading-day
    labels; a Yahoo provider; multi-provider Canonical reconciliation.

## Consequences

### Positive

- The v0.4.0 contracts become executable: one pipeline connects verified
  Canonical builds, PIT assembly, spec-versioned transforms, splits, the
  identity core, and immutable materialization.
- Fail-closed semantics everywhere: a Dataset directory either verifies
  completely or does not exist; there is no "warning then silently succeed"
  path.
- Determinism is the contract: identical pinned inputs produce identical
  logical content, identical `dataset_id`, and an idempotent build.

### Negative

- Only built-in registered transforms execute; arbitrary user functions
  cannot be plugged into a build until a future versioned extension point is
  designed.
- Transform execution adds a real compute layer over Canonical storage; a
  poorly written transform can now slow down or fail a Dataset build, so the
  registry contract must be enforced before execution.
- Strict non-finite rejection and INCOMPLETE exclusion can reject whole
  samples; consumers must design features/labels that satisfy the policy.

### Neutral

- The registry, spec documents, and Dataset directories remain plain
  versioned artifacts; no ML-specific code enters the runtime package.
- The exact initial transform subset and the exact Parquet writer option
  pinning are deferred to implementation PRs of the v0.5.0 sequence.

## Unresolved questions

1. Exact PyArrow writer-option pinning (compression, row-group size,
   dictionary encoding) and whether v0.5 claims byte-identical Parquet
   within one pinned environment.
2. Whether `dataset.parquet` stays a single file in v0.5 or partitions by
   code / split; the initial scope plans a single file, partitioning is
   deferred.
3. Whether the Dataset sample matrix also physically exports the PIT
   association rows, or keeps them as provenance referenced by content ID
   (the initial plan references them by content ID; physical association
   export is deferred).
4. The `session` Feature transform's output vocabulary, and whether
   `time_of_day` uses the declared split boundary timezone or
   America/New_York directly — resolved by the implementing PR.
