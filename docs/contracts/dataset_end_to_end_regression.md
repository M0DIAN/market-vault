# End-to-End Dataset Determinism and Leakage Regression Contract

Status: implemented in the v0.5.0 execution-layer regression suite
(`tests/test_dataset_end_to_end_regression.py`).

This contract defines the seventeen stable end-to-end regression categories
of the v0.5.0 execution layer as one offline, deterministic, cross-layer
matrix that exercises the complete public chain:

```text
verified Canonical builds
    -> PIT sample assembly
    -> Feature execution
    -> Label execution
    -> split / purge
    -> Dataset orchestration
    -> immutable materialization
    -> verified Dataset reader
```

and optionally the Dataset CLI entry combination (`dataset-build` ->
`dataset-verify` -> `dataset-inspect`). Related contracts:
[leakage_threat_model_regression.md](leakage_threat_model_regression.md),
[dataset_orchestration.md](dataset_orchestration.md),
[dataset_materialization.md](dataset_materialization.md),
[verified_dataset_reader.md](verified_dataset_reader.md),
[dataset_cli.md](dataset_cli.md).

This PR is tests and documentation only: it adds no production API, no
identity algorithm or version-constant change, no Dataset repair path, no
dependency, no version, no CI workflow change, no ML, no backtest, no
trading logic, no OpenD, and no network. No `src/market_vault/**` file is
modified.

## 1. Status

Implemented as an offline regression suite covering the seventeen fixed
regression IDs below, each with at least one positive control test and one
defense test, tracked by the fixed coverage matrix inside the suite (the
matrix guard fails the suite if a whole category is ever deleted or a
declared test function is renamed/removed).

## 2. Relationship to the v0.4.0 leakage threat model

The v0.4.0 suite (`tests/test_leakage_threat_model.py`, eight `LEAKAGE_*`
threat IDs) proves the *contract-layer* defenses: PIT assembly clocks,
spec content identity, split/purge facts, and `dataset_id` sensitivity. It
stops before Feature/Label value execution, Dataset orchestration,
materialization, and the verified Dataset reader.

This v0.5.0 suite extends those threats through the **execution layer to
the final Dataset row and the verified reader result**: future bars must be
provably absent from the final Feature values, archive cutoffs must be
provable from the materialized Dataset, label-boundary facts must be
re-verifiable through `load_verified_dataset`, and drift in any identity
factor must change `dataset_id` of the shipped artifact. The suite never
re-implements a layer; it always goes through the shipped public APIs.

## 3. Scope / non-goals

**In scope:** end-to-end regression coverage of the seventeen categories
against the shipped v0.5.0 chain, exercised through public APIs with
minimal deterministic micro fixtures (verified Canonical builds produced
by the public builder -> materializer -> verified reader chain); a full
COMPLETE canary; a full EMPTY canary; a CLI entry-combination canary; and
this documentation.

**Out of scope (explicit):** any runtime change; Dataset identity
algorithm or version-constant changes; PIT / Feature / Label / Split /
Orchestration / Materialization / Reader / CLI / Canonical changes; new
dependencies; `pyproject.toml` or package-version changes; CI workflow
changes; any Dataset repair or re-generation path (the suite asserts the
fail-closed *absence* of repair); network or OpenD; an API server or
Python client; ML / backtest / trading; tags, Releases, or PyPI; and
PR-10 / v0.5.1 / v0.6 work.

## 4. Seventeen stable regression IDs

```text
E2E_FUTURE_FEATURE_LEAKAGE
E2E_ARCHIVE_CUTOFF
E2E_INCOMPLETE_LABEL
E2E_ACTUAL_LABEL_END
E2E_CROSS_DAY_REJECTION
E2E_SPLIT_CROSSING_PURGE
E2E_TRANSFORM_DRIFT
E2E_SPEC_DRIFT
E2E_SOURCE_SNAPSHOT_SUBSTITUTION
E2E_ROW_COLUMN_ORDER
E2E_STAGING_RESIDUE
E2E_IMMUTABLE_CONFLICT
E2E_REBUILD_EQUIVALENCE
E2E_CORRUPTED_PARQUET
E2E_CORRUPTED_MANIFEST
E2E_NON_FINITE
E2E_TIMEZONE_DST
```

These IDs are machine identifiers shared by the tests and this document;
they introduce no production API.

## 5. Category -> enforcing layer -> expected defense matrix

| ID | Enforcing layer(s) | Expected defense |
| --- | --- | --- |
| E2E_FUTURE_FEATURE_LEAKAGE | PIT market clock; Feature execution; final Dataset rows | Rows available after the feature close never enter FEATURE; rows available exactly at the close are selected (boundary equality); input order never leaks a future bar; the final Feature value is computed from PIT Feature rows only (verified through the materialized row). |
| E2E_ARCHIVE_CUTOFF | PIT archive clock; Dataset orchestration; materialization | Rows archived at or before `dataset_as_of` are visible; later-archived rows never reach the Dataset (EMPTY build through the full chain); conflicting same-bar rows from two runs fail closed in either order; different legal `dataset_as_of` values change content and `dataset_id`; naive `dataset_as_of` fails closed. |
| E2E_INCOMPLETE_LABEL | Label execution; split; final rows | Full horizon -> COMPLETE; partial observed rows never silently become COMPLETE (`MISSING_TARGET_ROW`); the final row carries `label_status INCOMPLETE`, null label output and null actual end; the split is EXCLUDED with `INCOMPLETE_LABEL`. |
| E2E_ACTUAL_LABEL_END | Label execution; final rows | `actual_label_end_time` equals the last actually consumed Label row's `market_available_at` (UTC microseconds), never its event_time, never the nominal horizon, never `label_window_close`. |
| E2E_CROSS_DAY_REJECTION | PIT cross-date gate; label registry preflight | A label window reaching a later market calendar date fails closed at assembly; `cross_trading_day.allow=true` and `TRADING_DAYS` horizons fail closed at orchestration; nothing (no Dataset directory, no `_SUCCESS`) is ever published; the window is never truncated or rewritten to one day. |
| E2E_SPLIT_CROSSING_PURGE | split / purge | TRAIN and VALIDATION purge by the actual label end against the next-local-midnight exclusive boundary with exact reason codes and purge boundary; TEST has no fourth boundary; the nominal horizon never substitutes for the actual end; a non-crossing TRAIN sample stays ASSIGNED through the full chain. |
| E2E_TRANSFORM_DRIFT | ImplementationPin; `dataset_id` | A registration implementation-version change (same transform semantics, same spec, compatible output) changes the ImplementationPin and `dataset_id` while execution output stays identical; Label implementation drift is equally identity-bearing. |
| E2E_SPEC_DRIFT | spec content ID; SpecPin; `dataset_id` | YAML key order / whitespace / equivalent normalized forms do not change identity; Feature/Label spec input order never changes identity; any semantic change (parameters, horizon, transform_ref) changes SpecPin -> `DatasetIdentityInput` -> `dataset_id`. |
| E2E_SOURCE_SNAPSHOT_SUBSTITUTION | Canonical pins; provenance; reader | A substituted physical snapshot with identical logical bars changes the Canonical pins and `dataset_id`; relocating a build directory never changes identity; mixing another source's pins into a manifest is rejected by the verified reader. |
| E2E_ROW_COLUMN_ORDER | materialization; reader | Semantically identical input permutations produce identical rows / content ID / `dataset_id`; the physical Parquet keeps `code`, `feature_window_close`, `sample_key` ASC and the exact authoritative column order; reordered rows, reordered columns, and dtype changes are rejected by the reader. |
| E2E_STAGING_RESIDUE | materialization | Any staging residue under `.staging-<dataset_id>` (empty, partial, missing `_SUCCESS`, corrupt `_SUCCESS`, or a complete-but-uncommitted copy) fails closed, is never adopted, never repaired, never deleted, and never published; a foreign staging directory never blocks the materializer. |
| E2E_IMMUTABLE_CONFLICT | materialization | A valid final Dataset is never overwritten: tampered bytes, missing files, extra files, and manifest/artifact mismatches fail closed; hashes, sizes, mtimes, and entry sets are untouched; identical rebuilds stay idempotent. |
| E2E_REBUILD_EQUIVALENCE | materialization; reader | Identical pinned inputs rebuild idempotently (`created_new_build` True then False) with identical `dataset_id`, logical content, verified rows, build path, and byte-identical artifacts; a different `built_at` never conflicts and the verified result reports the existing build's `built_at`; a different `output_root` never changes identity. |
| E2E_CORRUPTED_PARQUET | reader | Arbitrary bytes, one changed logical value, reordered rows, reordered columns, dtype changes, and metadata changes are all rejected; nothing is written, repaired, or regenerated; the original failure is preserved through the documented error chain (including the underlying `pa.ArrowException`); no partial `VerifiedDatasetBuild` is returned. |
| E2E_CORRUPTED_MANIFEST | reader | Non-canonical JSON bytes, schema-version changes, `dataset_id` changes, logical-content changes, output hash/size changes, spec-pin changes, canonical-pin changes, unknown fields, and removed required fields all fail closed. |
| E2E_NON_FINITE | Feature/Label execution; reader | A Feature transform returning NaN / +Inf / -Inf fails the build before anything is published; a non-finite-producing Label implementation cannot enter the v0.5 chain (the fixed catalog boundary fails closed); a tampered Parquet carrying NaN is rejected by the reader (NaN is never silently null). |
| E2E_TIMEZONE_DST | split; identity; reader | Equivalent timezone representations of one absolute instant share identity; process `TZ` never changes results; output timing columns are exact UTC microseconds; naive datetimes fail closed; spring-forward / fall-back boundaries use the declared IANA timezone's next local midnight (never fixed +24h); nominal split uses the declared local date; invalid IANA names fail closed. |

## 6. Full-chain canaries

- **COMPLETE canary**: micro Canonical -> verified Canonical -> PIT ->
  Feature -> Label -> split -> orchestration -> materialization ->
  verified reader, on a Dataset with real Feature values, a real Label
  value, and a real split assignment; the verified reader's schema, rows,
  manifest, scope, pins, and identities equal the orchestration result.
- **EMPTY canary**: the same public chain on a Dataset with no assignable
  sample; `STATUS_EMPTY`, zero rows, full authoritative schema in the
  zero-row Parquet.
- **CLI canary**: `dataset-build` -> `dataset-verify` -> `dataset-inspect`
  as a public-entry combination test only; the CLI argument and JSON field
  contracts stay in the dedicated CLI suite.

No mock replaces a core production function anywhere on these paths; the
only test-controlled seams are (a) the immutable built-in registry
functions (`built_in_feature_registry` / `built_in_label_registry`) which
may be monkeypatched to a `TransformRegistry` built from public
`TransformRegistration` objects, and (b) `TransformRegistration`
construction, both used to prove transform-drift and non-finite fail-closed
behavior without touching production source.

## 7. Offline and deterministic boundary

Every test is offline and deterministic:

- no OpenD, no network, no real market data, no reads of any pre-existing
  data directory (all storage lives under `tmp_path`);
- fixed dates, fixed run IDs, fixed `built_at`/`created_at`, explicit
  timezone-aware UTC datetimes; no `datetime.now()`, no randomness, no
  sleep;
- no filesystem mtime participates in any identity (the immutable-conflict
  tests assert mtimes are *untouched*, never that they matter);
- no test-execution-order dependence, no local-system-timezone dependence
  (the `TZ` test sets the process environment to prove non-dependence);
- no repo-directory writes, no model training, no backtesting, no trading
  signals.

Symlink/junction environment limitations are documented in the suites that
need them; a capability-limited environment may skip a symlink-specific
case with its exact reason, never converting a failure into a pseudo
success.

## 8. Provenance rules

- Canonical fixtures are produced by the public chain
  (`materialize_canonical_market_bars` -> `load_verified_canonical_build`);
  `VerifiedCanonicalBuild` objects are never hand-constructed.
- Positive Datasets go through `orchestrate_dataset_build` ->
  `materialize_dataset_artifacts` -> `load_verified_dataset`; no second
  builder, materializer, or reader exists in the suite.
- Private fixtures/helpers of other test modules are never imported; all
  helpers live inside this file.
- `tests/test_leakage_threat_model.py` is untouched.

## 9. No production API / no identity change / no repair

The regression IDs, the coverage matrix, and all assertions are test and
documentation artifacts only. No identity algorithm, version constant,
`DatasetIdentityInput` field, or manifest contract is modified, and no
Dataset repair, re-generation, or auto-fix path is introduced or relied
upon: the suite proves that corruption, residue, and conflict fail closed
without repair.
