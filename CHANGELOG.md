# Changelog

All notable changes to MarketVault are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.0] - 2026-08-08

### Added

- Deterministic Sample Generation contract/core: frozen generation-plan
  models, strict plan parsing, deterministic semantic content identity, and
  the deterministic PITSampleRequest generator core over verified Canonical
  builds and explicit generation plans.
- `sample-generate` CLI: renders ordinary
  `market-vault-dataset-build-plan-v1` documents from one explicit
  generation plan, ready to hand directly to `dataset-build`.
- Immutable Dataset Catalog contract: verified Dataset facts projection,
  per-Dataset content digest, and normalized-set Catalog content identity
  with exact-duplicate merge / fail-closed conflict policy.
- Catalog builder / materializer / verified reader: deterministic Catalog
  content, immutable physical snapshots (`catalog.json` / `manifest.json` /
  `_SUCCESS`) with atomic no-replace publication, and a verified snapshot
  reader that recomputes every identity from the snapshot's own bytes.
- Catalog `dataset-catalog-build` / `dataset-catalog-verify` /
  `dataset-catalog-list` / `dataset-catalog-show` CLI with read-only
  discovery, filters, and pagination.
- Read-only Catalog filtering and pagination through
  `dataset-catalog-list`.
- Integrated acceptance suite: COMPLETE + EMPTY E2E, determinism,
  corruption fail-closed, recovery != repair, security/read-only, and
  usability coverage.
- PyArrow24 compatibility CI gate (`pyarrow==24.0.0`) running the full test
  suite.

### Fixed

- Canonical single-file Parquet verified-reader fix (GitHub PR #38):
  reads canonical parquet files directly and avoids Hive-style parent
  partition inference.
- PR-8 test-only Parquet portability hardening: two single-file reads in
  `tests/test_pit_sample_assembly.py` use `pq.ParquetFile(...).read()`
  instead of `pq.read_table(...)`, avoiding PyArrow 24.0.0 Hive-style
  parent partition inference in those regression helpers. Test-only;
  production behavior is unchanged.

### Compatibility

- Existing Canonical identity algorithms are unchanged.
- Existing Dataset identity algorithms are unchanged.
- The existing Dataset build-plan contract
  (`market-vault-dataset-build-plan-v1`) is unchanged; generated sample
  requests are ordinary build plans.
- No migration or rewrite of existing artifacts: existing Canonical builds,
  Datasets, manifests, and Catalog inputs are never modified.
- Runtime dependencies are unchanged.
- `pyarrow>=16` remains unchanged.
- `requires-python >=3.11` remains unchanged.
- Python 3.11 and Python 3.14 remain the normal CI matrix.
- PyArrow24 adds an additional full-suite compatibility gate.

### Known boundaries

- No Python Client.
- No REST API.
- No ML training.
- No backtesting.
- No automatic trading.
- No standalone `dataset-catalog-query`: `dataset-catalog-list` filters are
  the formal query surface.
- No `latest` pointer.
- No automatic repair.

## [0.5.1] - 2026-08-06

### Fixed

- Removed the NumPy generic-timedelta `DeprecationWarning` raised by
  MarketVault's own production code and tests: `pd.Timedelta` constructions
  now use explicit values and units, and Python `int` / NumPy integer inputs
  are equivalent (`bar_available_at`, `derive_internal_gap_ranges`).
- Added `tests/test_deprecation_compatibility_v051.py` regression tests
  proving Python `int` / NumPy integer equivalence, gap identity, and the
  non-multiple fail-closed boundary.
- Added a precise warning-as-error pytest guard for the exact NumPy
  generic-timedelta warning.
- Hardened the Dataset example renderer: fixed UTC six-digit microsecond
  serialization, rejection of existing destinations, regular-file
  destinations, blank path arguments, and clean filesystem error reporting.

### Added

- Verified Dataset CLI examples under
  [examples/dataset_cli/](examples/dataset_cli/README.md): FeatureSpec,
  LabelSpec, and ChronologicalSplitSpec example files, COMPLETE and EMPTY
  build-plan templates, a stdlib-only plan renderer, a complete Windows
  PowerShell flow, and 24 documented common errors.
- Example regression tests: static-file parser validation, deterministic
  rendering, no-overwrite behavior, and real COMPLETE / EMPTY / idempotent
  canaries through the formal CLI.

### Compatibility

- Dataset identity, Canonical identity, schema versions, and the
  build-plan / Feature / Label / split contracts are unchanged.
- CLI command surface, exit codes, and JSON output contracts are unchanged.
- Runtime dependencies and `requires-python >=3.11` are unchanged;
  Python 3.11 and Python 3.14 remain supported.
- Existing v0.5.0 Dataset and Canonical artifacts are never migrated,
  overwritten, or rewritten.

### Known boundaries

- No Sample Generator, Dataset Catalog, Python Client, REST API, ML
  training, backtesting, or automatic trading.
- No arbitrary user transforms, no adjusted-price PIT
  (`adjustment = NONE` only), no cross-trading-day Label execution, and no
  `TRADING_DAYS` Label horizon.
- No `latest`-directory discovery and no automatic Canonical discovery.

## [0.5.0] - 2026-08-05

### Added

- Immutable Transform Implementation Registry as the sole resolution
  authority for `transform_ref` (the complete v1 `module.path:function`
  string), with frozen registration models and strict FeatureSpec/LabelSpec
  compatibility preflight.
- Deterministic implementation fingerprints
  (`TRANSFORM_IMPLEMENTATION_FINGERPRINT_VERSION`) emitted as versioned
  `ImplementationPin` entries into the Dataset identity.
- Eight built-in Feature transforms: `simple_return`, `log_return`,
  `rolling_mean`, `rolling_std`, `rolling_volume_mean`, `volume_ratio`,
  `candle_range`, `candle_body`, with strict PIT clock binding, trailing
  contiguity, output-type, and finite-value validation.
- Four built-in Label transforms: `forward_return`, `forward_direction`,
  `maximum_favorable_excursion`, `maximum_adverse_excursion`, with exact
  Feature-close anchor binding and horizon/observation-window alignment
  (BARS, FEATURE_CLOSE_ALIGNED).
- Real `label_status` (COMPLETE / INCOMPLETE) decided from the actual label
  input rows with fixed reason codes — never inferred from partial PIT rows
  or the absence of gap records.
- Real `actual_label_end_time` from the last actually consumed label input
  row's `market_available_at`, normalized to UTC microseconds.
- End-to-end Dataset orchestration connecting verified Canonical builds,
  PIT sample assembly, built-in Feature execution, built-in Label execution,
  and chronological split / purge into one fail-closed pipeline with the
  deterministic `dataset_id`.
- Immutable Dataset Parquet materialization: explicit schema, fixed writer
  options, staging on the same filesystem, `_SUCCESS` written last, atomic
  no-overwrite rename, idempotent identical rebuilds, fail-closed conflict
  and staging-residue handling, and empty-Dataset materialization.
- Verified Dataset reader (`load_verified_dataset`) — the one public,
  read-only, fail-closed read path into committed Dataset artifacts; it
  never re-executes PIT / Feature / Label / materialization work, never
  scans for a `latest` directory, and never writes, repairs, or deletes.
- Dataset CLI (`dataset-build --plan`, `dataset-verify --build-dir`,
  `dataset-inspect --build-dir`) with the strict versioned build-plan JSON
  contract, settings-independent dispatch, deterministic JSON output,
  stable exit codes, and path/symlink/junction safety.
- Seventeen-category end-to-end Dataset determinism and leakage regression
  suite (`tests/test_dataset_end_to_end_regression.py`) with fixed
  `E2E_*` regression IDs, positive controls, and defenses tracked by a
  fixed coverage-matrix guard.
- Full COMPLETE canary, full EMPTY canary, and a
  `dataset-build` -> `dataset-verify` -> `dataset-inspect` CLI
  entry-combination canary.

### Changed

- Dataset contracts evolved from the V0.4 foundation into the executable
  V0.5 pipeline: the transform registry, Feature execution, Label
  execution, orchestration, materialization, verified reader, and Dataset
  CLI are now implemented and shipped.
- Package version moved to 0.5.0 (`pyproject.toml`, `_version.py`, release
  checker, CI assertions, release tests).
- README, CHANGELOG, v0.5.0 release notes, and the v0.5.0 direction document
  updated for the shipped pipeline; release checker, release tests, and CI
  package smoke updated to the V0.5 surface.

### Compatibility

- V0.1-V0.4 CLI behavior is unchanged; Raw/Curated data, the DuckDB
  catalog, and manifests are not migrated, overwritten, or repaired.
- V0.4 Canonical builds, their readers, and all published identities are
  unchanged; existing manifests remain valid.
- The v0.4.0 Dataset identity core, its algorithms, and version constants
  are unchanged; the V0.5 builder computes through the existing identity
  contracts.
- `requires-python` remains `>=3.11`; runtime dependencies do not change
  for this release preparation.
- `adjustment = NONE` remains the default leakage-safe dataset policy.

### Known boundaries

- No arbitrary user transforms: only the fixed built-in registry executes;
  no YAML-imported modules, `eval`, `exec`, or dynamic callbacks.
- No cross-trading-day Label execution; a `TRADING_DAYS` Label horizon
  fails closed as unsupported.
- No adjusted-price PIT reconstruction (`adjustment = NONE` only).
- No automatic repair or re-collection of Raw/Curated/Canonical data at
  build time.
- No automatic sample generation: requests are explicit and never inferred
  from the scope.
- No `latest`-directory inference: every build and read input is an
  explicit path.
- No ML training, model selection, or hyperparameter tuning.
- No backtesting, walk-forward frameworks, or feature importance.
- No API server or Python client.
- No automatic trading.

## [0.4.0] - 2026-08-05

### Added

- Canonical market-bar builder core: `canonical_bar_key` business identity
  and `canonical_row_version_id` physical row-version identity, deterministic
  reconciliation, provenance, and the COMPLETE audit gate.
- Immutable Canonical materialization: deterministic build identities,
  explicit Parquet schema, conservative gap sidecar, resolution JSONL,
  atomic commit, and EMPTY builds.
- Strict verified Canonical artifact reader (`load_verified_canonical_build`)
  with fail-closed validation.
- Three-clock market-bar semantics contract: `event_time`,
  `market_available_at`, and `archive_available_at`, plus the optional
  `dataset_as_of` archive cutoff.
- Deterministic derived Dataset schema/content/dataset identity core and the
  versioned Dataset manifest contract with provenance pins.
- Two-clock point-in-time sample assembly foundation binding Canonical rows
  to Feature/Label observation windows.
- Versioned Feature and Label spec contracts with strict fail-closed YAML
  parsing and semantic content IDs.
- Chronological TRAIN / VALIDATION / TEST split foundation with
  actual-label-end purging.
- Eight-threat leakage threat-model regression suite with cross-layer
  provenance canary.
- MIT License with the M0DIAN copyright holder.

### Changed

- CI matrix simplified from Python 3.11/3.12/3.13/3.14 to 3.11 and 3.14 plus
  the package build/install job.
- Dataset and Canonical public packages/exports added
  (`market_vault.canonical`, `market_vault.dataset`).
- V0.4 documentation and contracts added (ADR 0001, contract documents,
  direction document).

### Compatibility

- V0.3 CLI behavior is unchanged.
- V0.3 Raw/Curated data is not migrated, overwritten, or repaired.
- V0.2 legacy `batch-<batch_key>.parquet` filenames continue to be supported.
- No runtime ML dependency is added.
- `requires-python` remains `>=3.11`.
- Runtime dependencies do not change for this release preparation.

### Known boundaries

- No final Dataset builder orchestration.
- No Feature/Label value computation.
- No Dataset Parquet writer or Dataset CLI.
- PIT supports `adjustment = NONE` only; no adjusted-price corporate-action
  reconstruction.
- No cross-trading-day Label execution.
- No label-completeness inference.
- No authoritative per-date exchange session schedule.
- No automatic gap repair, synthetic OHLCV, or interpolation.
- No ML/backtest framework.
- No automatic trading.

## [0.3.0] - 2026-08-04

### Added

- Local trading calendar collection and query (`calendar`, `calendar-query`).
- Resumable standard and incremental history backfill driven by the local
  trading calendar (`backfill`), with per-(symbol, trade date) completion
  tracking, retries, and re-run recovery.
- Immutable Raw/Curated snapshots: every collection run writes its own
  `batch-<batch_key>-<run_id>.parquet` file, so a `--force` re-collection
  never overwrites an earlier snapshot.
- Inventory report (`inventory`) with physical file statistics, per-combination
  coverage, snapshot counts, and legacy metadata accounting.
- Trading-day coverage audit (`audit`) with COMPLETE / INCOMPLETE / MISSING
  classification and calendar requested-range coverage checks.
- Intraday integrity audit (`intraday-audit`) over the latest complete
  physical snapshot: exact metadata, timestamps, timezones, session labels,
  duplicate bars, minute-grid alignment, and internal gaps inside contiguous
  observed session segments.
- Shared coverage classification (`MarketBarCoverageState`) reused by the
  coverage and intraday audits.
- Atomic JSON report writing via a shared reporting helper.
- Python 3.11, 3.12, 3.13, and 3.14 CI matrix plus repository hygiene checks.
- `market-vault --version`, a release checker (`scripts/check_release.py`),
  and a package build/install CI job.

### Changed

- Incremental backfill starts each symbol at the first local trading date
  strictly after its latest completed date instead of `latest + 1 day`.
- Snapshot filenames include the run ID; `market_bars_snapshots` exposes every
  snapshot while `market_bars` keeps returning only the latest logical row.
- Session labeling is shared (`market_session_label`) between normalization
  and the intraday audit.
- Coverage audit and intraday audit share one trading-day classification
  implementation.

### Fixed

- `--force` re-collection overwrote deterministic Parquet files.
- Incremental mode used natural-day `+1` starts and could fail on weekends.
- Inventory `latest_trade_date` was computed from first dates.
- Inventory `snapshot_count` double-counted run IDs shared across symbols.
- Calendar-coverage FAILED audits reported a misleading 100% coverage.
- Inventory filter parameters were compared case-sensitively.
- INCOMPLETE classification lacked a `RUN_METADATA_MISMATCH` reason and the
  metadata comparison field order was wrong.
- Intraday audit mixed physical snapshots, let union schemas mask missing
  columns, wrote UTC instants into market-time fields, connected same-session
  observations across days, filtered malformed metadata rows before the
  structural check, and conflated eligible with audited row counts.
- Hive-partitioned reads could fabricate `interval`/`requested_trade_date`
  columns from directory paths.

### Compatibility

- No destructive data migration; V0.2 data remains readable.
- Legacy `batch-<batch_key>.parquet` files remain supported and are never
  deleted or renamed.
- Existing CLI commands keep their names and JSON output.
- `init-catalog` remains idempotent.

### Known boundaries

- No real-time subscriptions, live Bid/Ask, order-book depth, or complete
  intraday Greeks reconstruction.
- No automatic trading.
- No authoritative per-date session schedule; session leading/trailing
  boundaries are not validated and wholly missing sessions are not judged.
- Halts, circuit breakers, and early closes are not identified.
- Internal gaps are WARN-only and never automatically re-collected.

## [0.2.0]

- Option-chain static contract metadata collection (`option-chain`).
- Daily option volatility collection (`option-volatility`).
- Historical K-line collection for closed dates (`collect`), query layer
  (`query`), and option datasets.

[0.6.0]: https://github.com/M0DIAN/market-vault/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/M0DIAN/market-vault/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/M0DIAN/market-vault/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/M0DIAN/market-vault/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/M0DIAN/market-vault/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/M0DIAN/market-vault/releases/tag/v0.2.0
