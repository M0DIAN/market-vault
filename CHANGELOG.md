# Changelog

All notable changes to MarketVault are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.4.0]: https://github.com/M0DIAN/market-vault/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/M0DIAN/market-vault/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/M0DIAN/market-vault/releases/tag/v0.2.0
