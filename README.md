# MarketVault v0.5

MarketVault is a local historical market database for moomoo OpenD. V0.1 focused on closed-date stock, ETF, and option candlesticks. V0.2 added option contract static metadata and daily option volatility datasets. V0.3 adds the trading-calendar-driven collection and audit toolchain: a local trading calendar, resumable historical backfill, immutable snapshots, inventory reports, trading-day coverage audits, and intraday integrity audits. V0.4 adds the Canonical Dataset and ML Foundation: immutable Canonical builds from audited COMPLETE snapshots, a verified Canonical reader, three-clock market-bar semantics, two-clock point-in-time sample assembly, versioned Feature/Label spec contracts, deterministic Dataset identity/manifest contracts, chronological splits with actual-label-end purging, and the leakage threat-model regression suite. V0.5 adds the Deterministic Dataset Builder: an executable, verified, fail-closed pipeline that runs built-in Feature and Label transforms over verified Canonical builds, computes real `label_status` and `actual_label_end_time`, assigns chronological splits with actual-label-end purge, orchestrates immutable Dataset materialization, and reads the results back through a verified Dataset reader and three formal CLI commands.

## What this version does

- Connects to a locally running moomoo OpenD instance.
- Pages through `request_history_kline` results.
- Supports daily and intraday candlesticks, including `Session.ALL` where the installed SDK supports it.
- Keeps a raw Parquet layer and a normalized curated layer.
- Adds US Eastern and UTC timestamps plus market-session labels.
- Generates a JSON manifest and data-quality report for every run.
- Maintains DuckDB metadata tables, a `market_bars_snapshots` view with every snapshot, and a deduplicated `market_bars` view.
- Continues collecting other symbols if one symbol fails.
- Collects option-chain static contract metadata from `get_option_chain`.
- Collects daily option volatility analysis rows from `get_option_volatility`.
- Maintains `option_contracts`, `option_contracts_latest`, and `option_volatility_daily` DuckDB views.
- Collects a local trading calendar from `request_trading_days`.
- Runs resumable standard and incremental history backfills driven by the local calendar.
- Writes immutable Raw/Curated snapshots; a `--force` re-collection never overwrites an older snapshot.
- Reports local storage, snapshot, and per-combination coverage through `inventory`.
- Audits trading-day coverage with COMPLETE / INCOMPLETE / MISSING classification through `audit`.
- Selects the latest complete physical snapshot and audits intraday structure, timestamps, timezones, session labels, duplicate bars, minute-grid alignment, and internal gaps through `intraday-audit`.
- Builds immutable Canonical market-bar builds from audited COMPLETE snapshots and reads them back through a strict verified reader.
- Adds `event_time` / `market_available_at` / `archive_available_at` three-clock semantics with an optional `dataset_as_of` archive cutoff.
- Provides deterministic Dataset schema/content/dataset identities and the versioned Dataset manifest contracts.
- Provides versioned Feature and Label spec contracts with strict fail-closed YAML parsing and semantic content IDs.
- Assembles point-in-time Feature/Label observation associations under the market and archive clocks.
- Assigns chronological TRAIN / VALIDATION / TEST splits and purges samples by actual label end.
- Adds an eight-threat offline leakage regression suite.
- Executes the deterministic Dataset pipeline: verified Canonical builds → PIT sample assembly → built-in Feature execution → built-in Label execution → real `label_status` / `actual_label_end_time` → chronological split / purge → Dataset orchestration → immutable Dataset materialization → verified Dataset reader → Dataset CLI.
- Runs the fixed built-in Feature and Label transform registries with versioned deterministic implementation fingerprints.
- Provides `dataset-build`, `dataset-verify`, and `dataset-inspect` as settings-independent CLI commands.
- Adds a seventeen-category end-to-end Dataset determinism and leakage regression suite.
- Runs CI on Python 3.11 and 3.14, plus a package build/install job.

## Recommended collection and audit workflow

```text
1. init-catalog
2. calendar
3. backfill
4. inventory
5. audit
6. intraday-audit
7. query
```

- `calendar` and `backfill` may connect to OpenD.
- `inventory`, `audit`, `intraday-audit`, and `query` are pure-local reads.
- Audit commands never modify data and never trigger automatic re-collection.

## Important data boundary

This project can backfill historical candlesticks, option-chain static metadata, and daily volatility analysis where OpenD and the account permissions allow it. It cannot reconstruct historical minute-by-minute Bid/Ask, order-book depth, Greeks, or complete intraday IV after the fact. Those fields require a live capture and subscription pipeline.

MarketVault does not include real-time subscriptions, live Bid/Ask, live Greeks, positions, signals, execution, or automatic trading.

## V0.5 deterministic Dataset builder

V0.5 turns the V0.4 contract chain into one executable, verifiable, reproducible pipeline:

```text
verified Canonical builds
    → PIT sample assembly
    → built-in Feature execution
    → built-in Label execution
    → label_status / actual_label_end_time
    → chronological split / purge
    → Dataset orchestration
    → immutable Dataset materialization
    → verified Dataset reader
    → Dataset CLI
```

### The three formal commands

```text
market-vault dataset-build --plan <PATH>
market-vault dataset-verify --build-dir <PATH>
market-vault dataset-inspect --build-dir <PATH>
```

- `dataset-build` executes one pinned, immutable Dataset build from a single explicit, fixed, versioned build-plan JSON document (`market-vault-dataset-build-plan-v1`). Every formal input — verified Canonical build directories, Feature/Label spec files, sample requests, scope, split spec, optional `dataset_as_of`, and `output_root` — is declared in the plan. The CLI is a thin wrapper over the formal public chain and never duplicates PIT, Feature, Label, Split, Parquet, manifest, staging, or rename logic.
- `dataset-verify` runs the verified Dataset reader against one explicit final Dataset directory (`<output_root>/<dataset_id>`) and is strictly read-only.
- `dataset-inspect` verifies the same way and additionally prints the scope, schema, spec pins, split spec, split diagnostics, build report, and an offset/limit slice of the logical rows as deterministic JSON.

The Dataset commands never load `settings.yaml`, never connect to OpenD, and never access the network.

**Verified Dataset CLI examples** — copyable FeatureSpec / LabelSpec / split-spec files, COMPLETE and EMPTY build-plan templates, a stdlib-only renderer, and a full Windows PowerShell flow live in [examples/dataset_cli/](examples/dataset_cli/README.md). The examples document the current formal CLI and schema only; they add no new Dataset capability.

### How a build works

- `dataset-build` accepts only `--plan`. There is no `--output-root`, `--latest`, `--force`, `--repair`, or any other override: every formal fact comes from the plan, so the command line and the file can never be two sources of truth.
- The plan is explicit and fixed: no parent directory is scanned, no `latest` directory is ever selected, no Canonical build is auto-chosen, and no feature/label/split spec is inferred. Relative plan paths are anchored to the plan file's parent directory.
- The build never auto-refreshes or re-collects data, never repairs Raw/Curated/Canonical inputs, and never connects to OpenD or the network. It reads only the pinned local inputs and writes only through the materializer.
- The final Dataset directory is named by the deterministic `dataset_id` (`<output_root>/<dataset_id>`), never by a timestamp. Materialization is atomic: staging on the same filesystem, `_SUCCESS` written last, then a no-overwrite rename. An existing conflicting final directory fails closed and is never overwritten; an identical existing build returns idempotently without rewriting anything.
- Every build ends with exactly one `load_verified_dataset` call on the committed build path; SUCCESS is printed only when that verification passes and the orchestration / materialization / reader `dataset_id` binding holds.
- `dataset-verify` and `dataset-inspect` are read-only: they never write, repair, or delete any artifact. The verified Dataset reader never fixes or rewrites anything and never scans for a `latest` directory.

### Built-in transforms only

- Features and Labels are executed only through the fixed built-in Transform Implementation Registry, which is the sole resolution authority for `transform_ref` and emits versioned `ImplementationPin` entries (with deterministic implementation fingerprints) into the Dataset identity.
- The eight built-in Feature transforms: `simple_return`, `log_return`, `rolling_mean`, `rolling_std`, `rolling_volume_mean`, `volume_ratio`, `candle_range`, `candle_body`.
- The four built-in Label transforms: `forward_return`, `forward_direction`, `maximum_favorable_excursion`, `maximum_adverse_excursion`.
- No arbitrary user code is ever executed: no YAML-imported modules, no `eval`/`exec`, no dynamic callbacks. Unknown or unregistered transforms fail the build.

### Leakage-safe dataset policy

- `adjustment = NONE` is the only dataset policy; adjusted-price PIT reconstruction is not implemented.
- Labels never span trading days: no cross-trading-day Label execution, and a `TRADING_DAYS` Label horizon fails closed as unsupported.
- `label_status` (COMPLETE / INCOMPLETE) is decided from the actual label input rows; INCOMPLETE labels are excluded from TRAIN/VALIDATION/TEST samples by default.
- `actual_label_end_time` is the market-availability instant of the last actual label input row — never a nominal horizon guess.
- TRAIN/VALIDATION samples are purged by the real `actual_label_end_time` against DST-safe split boundaries; TEST has no fourth-split purge.
- NaN and ±Infinity never enter a Dataset; non-finite Feature or Label output fails the build.

### What the Dataset layer is not

- No ML training, model selection, or hyperparameter tuning.
- No backtesting, walk-forward frameworks, or feature importance.
- No signals, online feature store, real-time inference, or automatic trading.
- No API server and no Python client in this release.

### Dataset contracts

- [ADR 0002: Deterministic Dataset Builder boundary](docs/adr/0002-deterministic-dataset-builder-boundary.md)
- [Transform implementation registry](docs/contracts/transform_implementation_registry.md)
- [Built-in Feature execution](docs/contracts/built_in_feature_execution.md)
- [Built-in Label execution](docs/contracts/built_in_label_execution.md)
- [Dataset orchestration](docs/contracts/dataset_orchestration.md)
- [Dataset materialization](docs/contracts/dataset_materialization.md)
- [Verified Dataset reader](docs/contracts/verified_dataset_reader.md)
- [Dataset CLI](docs/contracts/dataset_cli.md)
- [Dataset E2E determinism and leakage regression](docs/contracts/dataset_end_to_end_regression.md)

## V0.4 canonical and dataset foundation

V0.4 delivered the Canonical Dataset and ML Foundation that V0.5 executes:

```text
Raw / Curated
    → audited COMPLETE snapshots
    → immutable Canonical builds
    → verified PIT sample assembly
    → Feature / Label specs
    → chronological split and purge
    → deterministic Dataset identity / manifest contracts
```

- Canonical builds are derived only from audited COMPLETE snapshots. INCOMPLETE or MISSING keys never produce Canonical rows. A request with no eligible COMPLETE snapshots produces a deterministic EMPTY build; completion states are not converted into synthetic rows or internal-gap sidecar entries.
- The Canonical gap sidecar records only confirmable internal nominal-spacing gaps between observed Canonical bars; it never infers leading/trailing/session gaps and never generates synthetic bars.
- A strict verified Canonical reader (`load_verified_canonical_build`) is the only public read path into committed Canonical builds; it fails closed on any inconsistency.
- Bars carry three instants: `event_time` (the adopted interval-start instant, UTC), `market_available_at` (computed as `event_time + nominal interval`; exact for bars known to span the complete nominal interval, and a conservative leakage-safe not-before bound for bars that may be truncated at a session boundary or an early close — the market clock used by point-in-time feature assembly), and `archive_available_at` (`run_finished_at`, the archive clock). An optional `dataset_as_of` selects archive-time reproducibility.
- Deterministic Dataset schema/content/dataset identities and the versioned Dataset manifest bind every derived Dataset to its inputs; the V0.5 builder executes this foundation end to end.
- Feature and Label definitions are versioned spec contracts with deterministic semantic content IDs; V0.5 executes values through the fixed built-in registry.
- PIT sample assembly binds verified Canonical rows to Feature/Label observation windows under the market clock and the optional archive clock.
- Chronological TRAIN / VALIDATION / TEST splits are assigned by feature window close; samples whose actual label end crosses a boundary are purged.
- Eight leakage threats (future-bar, archive-time, label-cross-split, adjustment/corporate-action, snapshot substitution, spec drift, completion ambiguity, timezone misattribution) are pinned by an offline regression suite. The default leakage-safe dataset policy is `adjustment = NONE`; adjusted-price PIT reconstruction is not implemented.

V0.4 contracts:

- [ADR 0001: Canonical ML Dataset Boundary](docs/adr/0001-canonical-ml-dataset-boundary.md)
- [Market-bar timestamp semantics](docs/contracts/market_bar_timestamp_semantics.md)
- [Canonical market-bar materialization](docs/contracts/canonical_market_bar_materialization.md)
- [Derived dataset manifest](docs/contracts/derived_dataset_manifest.md)
- [Point-in-time sample assembly](docs/contracts/point_in_time_sample_assembly.md)
- [Feature/Label spec versioning](docs/contracts/feature_label_spec_versioning.md)
- [Chronological splits and purging](docs/contracts/chronological_splits_and_purging.md)
- [Leakage threat-model regression](docs/contracts/leakage_threat_model_regression.md)

## Requirements

- Python 3.11 or newer
- moomoo OpenD installed, logged in, and running
- The moomoo account must have the required market-data permissions and historical quota

## Install on Windows

Open PowerShell in this project directory:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

The official Python package is installed from PyPI as `moomoo-api`. MarketVault first imports the SDK through the current `moomoo` namespace and falls back to the older `futu` namespace for compatibility.

## Fast Windows setup

From PowerShell in the project directory:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup_windows.ps1
```

After OpenD is running, collect a closed trading date:

```powershell
.\scripts\first_collection.ps1 -TradeDate 2026-07-31
```

## Configure OpenD

Edit `config/settings.yaml` when OpenD is not using the default endpoint:

```yaml
opend:
  host: "127.0.0.1"
  port: 11111
```

## Initialize the catalog

```powershell
market-vault --settings config/settings.yaml init-catalog
```

## First collection

Collect the core universe for the closed US trading date 2026-07-31:

```powershell
market-vault --settings config/settings.yaml collect `
  --date 2026-07-31 `
  --groups core_universe `
  --interval 1m `
  --session ALL `
  --adjustment NONE
```

Or provide symbols directly:

```powershell
market-vault --settings config/settings.yaml collect `
  --date 2026-07-31 `
  --symbols US.MU US.SPY US.QQQ `
  --interval 1m
```

## Option chain metadata

Collect static option contracts for an underlying and expiration-date range:

```powershell
market-vault --settings config/settings.yaml option-chain `
  --underlying US.MU `
  --start-date 2026-08-07 `
  --end-date 2026-09-18 `
  --option-type ALL `
  --option-cond-type ALL
```

`--option-cond-type` supports only the filters exposed by the official moomoo option-chain API: `ALL`, `ITM` mapped to `OptionCondType.WITHIN`, and `OTM` mapped to `OptionCondType.OUTSIDE`. The API does not provide an ATM filter. Future analysis code can calculate ATM contracts from the underlying's current price and strike distance after collection.

The curated dataset standardizes `option_code`, `option_name`, `underlying_code`, `option_type`, `strike_price`, `expiry_date`, `contract_size`, `lot_size`, `exchange`, `exercise_type`, `suspension`, `delisting`, `captured_at`, `source`, `source_schema_version`, and `ingestion_run_id`. Fields not returned by moomoo are kept as null rather than inferred.

The moomoo option-chain endpoint limits each request to a maximum 30-day span. MarketVault automatically splits longer `--start-date` / `--end-date` ranges into non-overlapping 30-day chunks, retries no hidden ranges, and merges successful chunks into one raw file, one curated file, one manifest, and one quality report. Users do not need to split long expiration ranges manually.

## Daily option volatility

Collect daily volatility analysis for one or more option contracts:

```powershell
market-vault --settings config/settings.yaml option-volatility `
  --codes US.MU260807C120000 US.MU260807P100000 `
  --start-date 2026-07-01 `
  --end-date 2026-07-31
```

The moomoo response fields are normalized as follows: `timestamp_str` to `trade_date`, `implied_volatility` to `implied_volatility`, `history_volatility` to `historical_volatility`, `volatility_premium` to `volatility_premium`, `average_impvol` to `average_implied_volatility`, `impvol_status` to nullable integer `volatility_status`, and `analysis` to nullable string `analysis`. The curated dataset also includes `option_code`, UTC `captured_at`, `source`, `source_schema_version`, and `ingestion_run_id`. Optional volatility fields may be null when OpenD does not return a value.

The official volatility endpoint accepts a lookback period, not direct start and end dates. MarketVault selects the smallest official period that covers the requested start date from the collection date: `WEEK`, `MONTH`, `QUARTER`, `HALF_YEAR`, or `YEAR`, then filters returned rows to the requested date range. Some moomoo SDK builds do not export `OptionVolatilityTimePeriodType`; in that case MarketVault uses official integer period values (`WEEK=1`, `MONTH=2`, `QUARTER=3`, `HALF_YEAR=4`, `YEAR=5`). This does not affect `get_option_volatility` availability. Requests older than the maximum `YEAR` period are rejected before OpenD is called. Coverage is calculated per option code using a weekday-boundary heuristic; it does not know NYSE/Nasdaq holidays. A formal exchange calendar is planned for a later version.

Run manifests keep the top-level `request_count` as the number of requested items for compatibility. The actual OpenD call count is recorded in `parameters.api_request_count`; successful and failed calls are recorded as `parameters.successful_api_request_count` and `parameters.failed_api_request_count`.

## Doctor

Check local SDK and OpenD capability without writing market data:

```powershell
market-vault --settings config/settings.yaml doctor
```

The command reports Python version, SDK import/version, OpenD host and port, socket connectivity, whether `get_option_chain` and `get_option_volatility` are exposed by the installed SDK, and whether volatility periods use SDK enums or integer fallback.

## Trading calendar

Collect historical trading-calendar rows from OpenD `request_trading_days` by market:

```powershell
market-vault --settings config/settings.yaml calendar `
  --market US `
  --start-date 2026-01-01 `
  --end-date 2026-12-31
```

Or by reference code:

```powershell
market-vault --settings config/settings.yaml calendar `
  --code US.MU `
  --start-date 2026-01-01 `
  --end-date 2026-12-31
```

Query the local DuckDB/Parquet dataset without connecting to OpenD:

```powershell
market-vault --settings config/settings.yaml calendar-query `
  --market US `
  --start-date 2026-01-01 `
  --end-date 2026-12-31 `
  --limit 30
```

The curated `trading_calendar` dataset stores `scope_type`, `scope_value`, `market`, `reference_code`, `trade_date`, `trade_date_type`, `requested_start_date`, `requested_end_date`, UTC `captured_at`, `source`, `source_schema_version`, and `ingestion_run_id`. The calendar returned by OpenD excludes weekends and regular holidays and preserves `WHOLE`, `MORNING`, or `AFTERNOON` trading-day types. It is not described as an absolute official exchange calendar and may not identify every temporary market closure.

OpenD `request_trading_days` has its own range and rate limits: historical calendar data is available for roughly the past 10 years, future dates are limited to the current calendar year's December 31, and the endpoint allows at most 30 requests per 30 seconds. MarketVault fetches this data dynamically from OpenD and does not hard-code exchange holidays.

## Resumable history backfill

The `backfill` command plans and executes historical K-line collection for a range of trading dates derived from the local trading calendar. Re-running the same command resumes the work: items that already have completed data are skipped, and only failed or missing items are collected. Multiple symbols are supported in a single run.

### Before you start

- Collect the local trading calendar first with the `calendar` command. Backfill refuses to run when the calendar has no coverage for the requested range and prints the missing dates.
- Choose the calendar scope with `--calendar-market US` or `--calendar-code US.MU` (exactly one is required). Trading dates are planned from the selected scope.
- Calendar coverage must span the complete requested natural-date range. Coverage gaps are detected on natural dates, so run `calendar` once over the whole range instead of in disjoint chunks: a gap between two chunks is reported as missing coverage even when the gap only contains a weekend.
- Only dates before today's UTC date are accepted.
- Run one backfill process at a time per dataset; concurrent processes may collect the same items.

### Standard backfill

Collect a date range for several symbols:

```powershell
market-vault --settings config/settings.yaml backfill `
  --calendar-market US `
  --start-date 2026-01-01 `
  --end-date 2026-07-31 `
  --symbols US.MU US.SPY US.QQQ `
  --interval 1m `
  --session ALL `
  --adjustment NONE
```

Or expand symbols from the universe groups:

```powershell
market-vault --settings config/settings.yaml backfill `
  --calendar-code US.MU `
  --start-date 2026-01-01 `
  --end-date 2026-07-31 `
  --groups core_universe
```

`--symbols` accepts any number of codes, and `--groups` accepts `core_universe`, `trade_universe`, `event_universe`, or `option_universe`. Items are planned per (symbol, trade date) and collected date by date. `--interval` defaults to `1m`; `--session` and `--adjustment` fall back to the `default_session` and `default_adjustment` values in `config/settings.yaml` when omitted.

### Incremental mode

Continue collecting from each symbol's latest completed date:

```powershell
market-vault --settings config/settings.yaml backfill `
  --calendar-market US `
  --incremental `
  --end-date 2026-07-31 `
  --symbols US.MU US.SPY
```

Incremental mode asks the local trading calendar for the first trading date strictly after each symbol's latest completed date; it never advances by a natural day `+1` and never guesses weekends or holidays on its own. It cannot be combined with `--start-date`. Symbols that have no completed history require a bootstrap start:

```powershell
market-vault --settings config/settings.yaml backfill `
  --calendar-market US `
  --incremental `
  --bootstrap-start-date 2026-01-01 `
  --end-date 2026-07-31 `
  --symbols US.NVDA
```

### Resume semantics

- Re-running a standard backfill with the same range re-plans that range and collects only the failed or missing items; already-completed items are skipped.
- `--incremental` only continues after each symbol's latest completed date and never re-examines earlier history.
- If one date failed while a later date succeeded, incremental mode does not pick up that middle gap. Fill gaps by re-running a standard backfill with the explicit range, optionally with `--force`.
- `--force` skips the completed-item check and re-collects the whole planned range. It does not change the incremental starting point: `--force` combined with `--incremental` is still bounded by each symbol's latest completed date.

### Retry and recovery

Failed items are retried up to `--max-retries` times (default 2) with exponential backoff starting at `--retry-backoff-seconds` (default 2.0, capped at 60 seconds). Only failed symbols of a date are retried; successful ones are not. A failing date does not stop the remaining dates or symbols.

A Ctrl-C interruption may leave no top-level backfill manifest, but every completed child run is already recorded, so re-running the command resumes from the recorded state.

### Python API

```python
from datetime import date

from market_vault import MarketVault

vault = MarketVault("config/settings.yaml")

plan = vault.plan_backfill(
    symbols=["US.MU", "US.SPY"],
    start_date=date(2026, 1, 1),
    end_date=date(2026, 7, 31),
    calendar_market="US",
)
print([(item.code, item.trade_date) for item in plan.pending_items])

manifest = vault.backfill(
    symbols=["US.MU", "US.SPY"],
    start_date=date(2026, 1, 1),
    end_date=date(2026, 7, 31),
    calendar_market="US",
    max_retries=2,
    retry_backoff_seconds=2.0,
)
print(manifest.status)
```

When `session` or `adjustment` is omitted, the settings defaults (`default_session`, `default_adjustment`) are used; explicit values override them. `plan_backfill` previews the plan without collecting anything — the CLI has no dry-run flag, so use the Python API to preview.

### Run manifest

Each backfill run writes `manifests/market_bars_backfill_<run_id>.json` and a quality report under `reports/`. The manifest records, per symbol:

- successful dates (`successful_dates_by_symbol`),
- skipped dates (`skipped_dates_by_symbol`),
- failed dates with error messages (`failed_dates_by_symbol`),
- the child run IDs of the underlying collection runs (`child_run_ids`),
- the total collected rows (`row_count`) and the final `status` (`SUCCESS`, `PARTIAL`, or `FAILED`).

### Known limitations

- "Completed" currently means that curated rows exist, the run status is `SUCCESS` or `PARTIAL`, and no quality check `FAIL`ed. The expected number of bars is not validated, so non-empty but partial data may be treated as completed.
- Incremental mode does not re-examine gaps before a symbol's latest completed date; fill them with a standard range backfill.
- A Ctrl-C interruption may leave no top-level PARTIAL manifest; recovery relies on the recorded child runs.
- The CLI has no dry-run flag; use `plan_backfill` to preview a plan.

## Inventory and coverage audit

Two pure-local commands inspect the local market-bar store without touching OpenD or modifying any data file. Both write structured JSON reports under `reports/data_quality` (`market_bars_inventory_<run_id>.json` and `market_bars_audit_<run_id>.json`).

### Inventory

Summarize local Raw/Curated files, snapshot and row counts, parameter combinations, per-symbol covered dates, and completion counts:

```powershell
market-vault --settings config/settings.yaml inventory
```

Filter by symbol:

```powershell
market-vault --settings config/settings.yaml inventory `
  --symbols US.MU `
  --interval 1m `
  --session ALL `
  --adjustment NONE
```

Include the physical file list in the report:

```powershell
market-vault --settings config/settings.yaml inventory `
  --include-files
```

`--symbols`, `--universe`, and `--groups` filter by symbol; `--start-date`/`--end-date` filter by trade date; `--interval`, `--session`, `--adjustment`, and `--source-schema-version` filter by request key. Without filters, the report covers every local symbol and combination. An empty database reports `status: EMPTY` with zero counts. File entries (only with `--include-files`) list `layer`, `relative_path`, `size_bytes`, `modified_at`, and whether the filename is a legacy `batch-<batch_key>.parquet` name.

### Audit

Audit trading-day coverage for a date range against the local trading calendar:

```powershell
market-vault --settings config/settings.yaml audit `
  --calendar-market US `
  --start-date 2026-07-01 `
  --end-date 2026-07-31 `
  --symbols US.MU `
  --interval 1m `
  --session ALL `
  --adjustment NONE
```

Strict mode for scripts and CI:

```powershell
market-vault --settings config/settings.yaml audit `
  --calendar-market US `
  --start-date 2026-07-01 `
  --end-date 2026-07-31 `
  --symbols US.MU `
  --fail-on-gaps
```

Exit codes: `PASS` exits 0, `WARN` exits 0 (or 2 with `--fail-on-gaps`), `FAILED` exits 1.

### Audit report semantics

- The audit only checks trading-day-level coverage. It does not validate how many bars a trading day should contain.
- Expected dates come from the local `trading_calendar_latest` dataset, never from weekday or holiday rules. The calendar snapshot's `requested_start_date`/`requested_end_date` ranges must fully cover `--start-date` to `--end-date`; otherwise the audit fails with `calendar_coverage_gaps` and does not compute bar-level missing dates.
- A (symbol, trade date) is `COMPLETE` when curated rows match the exact `code / requested_trade_date / interval / requested_session / adjustment / source_schema_version` key, the run status is `SUCCESS` or `PARTIAL`, and no quality check `FAIL`ed — the same semantics as the backfill completion check.
- `INCOMPLETE` means curated rows exist for the exact key but no snapshot satisfies the completion criteria; the report lists sorted, deduplicated reasons (`QUALITY_FAIL`, `RUN_FAILED`, `RUN_RUNNING`, `RUN_METADATA_MISMATCH`, `ORPHANED_RUN`, `RUN_STATUS_UNKNOWN`). `RUN_METADATA_MISMATCH` means the linked run exists, its status allows completion, and it has no quality `FAIL`, but the run's request metadata (trade date, interval, session, adjustment) does not match the curated row.
- `MISSING` means no curated rows exist for the exact key. Missing and incomplete dates are always reported; complete dates are included only with `--include-complete-dates`.
- Every operation is pure local: no OpenD connection, no writes to Parquet, no deletion or renaming of files, and no entries in the ingestion metadata tables. Fixing gaps remains a separate, explicit `backfill` run.

## Intraday integrity audit

The `intraday-audit` command checks the intraday structure of the latest complete immutable snapshot for each (symbol, trade date) in a range:

```powershell
market-vault --settings config/settings.yaml intraday-audit `
  --calendar-market US `
  --start-date 2026-07-30 `
  --end-date 2026-07-31 `
  --symbols US.MU `
  --interval 1m `
  --session ALL `
  --adjustment NONE
```

Strict mode for scripts and CI (WARN exits 2):

```powershell
market-vault --settings config/settings.yaml intraday-audit `
  --calendar-market US `
  --start-date 2026-07-30 `
  --end-date 2026-07-31 `
  --symbols US.MU `
  --fail-on-warn
```

### What it validates

- The command is pure local: no OpenD connection, no Parquet modification, no automatic repair or re-collection.
- For every COMPLETE item it selects the newest complete physical snapshot (never the deduplicated `market_bars` view) and validates: exact request metadata, timestamp validity, UTC/market instant consistency, `market_calendar_date` consistency, session labels, requested-session scope, duplicate bars, minute-boundary alignment, interval-grid deltas, and internal gaps inside contiguous observed session segments.
- Session labels come from the shared `market_session_label()` used by normalization (OVERNIGHT / PRE_MARKET / REGULAR / AFTER_HOURS).
- Internal gaps are reported as WARN (never FAIL): halts, circuit breakers, and no-trade periods can legitimately leave empty bars.

### What it does not claim

> Internal gaps are detected only inside contiguous observed session segments. Leading or trailing session coverage is not evaluated in this stage.

- No fixed daily bar counts (no 1440/390/1201 hardcoding) and no early-close calendar; 2026-07-30 (1440 rows) and 2026-07-31 (1201 rows) can both pass.
- Session boundary coverage (start-of-session to first bar, last bar to end-of-session, wholly missing sessions) is not evaluated.
- Reports go to `reports/data_quality/market_bars_intraday_audit_<run_id>.json`; the report records `boundary_coverage: {evaluated: false}`.
- Fixing gaps stays an explicit `backfill` run.

## Query data

```powershell
market-vault --settings config/settings.yaml query `
  --code US.MU `
  --trade-date 2026-07-31 `
  --interval 1m `
  --session REGULAR
```

Python API:

```python
from market_vault import MarketVault

vault = MarketVault("config/settings.yaml")
bars = vault.load_bars(
    code="US.MU",
    trade_date="2026-07-31",
    interval="1m",
    session="REGULAR",
)
print(bars.head())
```

## Storage layout

```text
data/
├─ raw/source=moomoo/dataset=market_bars/...
├─ raw/source=moomoo/dataset=option_chain/...
├─ raw/source=moomoo/dataset=option_volatility_daily/...
├─ raw/source=moomoo/dataset=trading_calendar/scope_type=MARKET/scope_value=US/...
├─ curated/source=moomoo/dataset=market_bars/...
├─ curated/option_contracts/underlying_code=US.MU/capture_date=YYYY-MM-DD/...
├─ curated/option_volatility_daily/start_date=YYYY-MM-DD/end_date=YYYY-MM-DD/...
├─ curated/trading_calendar/scope_type=MARKET/scope_value=US/...
└─ datasets/<dataset_id>/
    ├─ dataset.parquet
    ├─ manifest.json
    ├─ build_report.json
    ├─ feature_specs/
    ├─ label_specs/
    ├─ split_spec.yaml
    └─ _SUCCESS
catalog/market_vault.duckdb
manifests/*.json
reports/data_quality/*.json
```

Market-bar raw and curated files are written as `batch-<batch_key>-<run_id>.parquet`: each collection run gets its own immutable snapshot, so re-collecting the same date/parameters never overwrites an earlier snapshot. Files from before the snapshot naming (`batch-<batch_key>.parquet`) remain readable and are treated as legacy snapshots. The DuckDB view `market_bars_snapshots` exposes every snapshot row; the public `market_bars` view deduplicates bars by `(code, interval, adjustment, time_utc)` and keeps the newest `ingested_at` row, so the query layer always returns the latest snapshot. The `option_volatility_daily` view deduplicates by `(option_code, trade_date, source)` and chooses the latest row by `captured_at DESC NULLS LAST`, with `ingestion_run_id` only as a secondary tie-breaker.

Dataset final directories live under `data/datasets/<dataset_id>/`; the directory name is the deterministic `dataset_id` itself. The final directory is written only through the atomic materializer, `_SUCCESS` is written last, and a conflicting final directory is never overwritten.

## Tests

```powershell
pytest
```

The tests are offline and do not require OpenD.

## Upgrade from v0.4

- No destructive data migration. V0.4 Raw/Curated data, Canonical builds, the DuckDB catalog, manifests, and CLI continue to work unchanged.
- Existing data does not need to be deleted or rebuilt.
- V0.4 Canonical builds, their readers, and all published identities are unchanged; existing manifests remain valid.
- The v0.4.0 Dataset identity core, its algorithms, and version constants are unchanged; the V0.5 builder computes through the existing identity contracts.
- Dataset builds are new, independent immutable artifacts; V0.5 never modifies old Raw/Curated/Canonical data.
- Legacy `batch-<batch_key>.parquet` compatibility is preserved.
- Existing CLI names and behavior do not change because of the V0.5 pipeline; users can keep using only the V0.1–V0.4 collection/audit workflow.
- V0.5 capabilities never run automatically in the background.

## Upgrade from v0.3

- No destructive data migration. V0.3 Raw/Curated data, the DuckDB catalog, manifests, and CLI continue to work unchanged.
- Existing data does not need to be deleted or rebuilt.
- Canonical builds are new, independent immutable artifacts; v0.4 and v0.5 never modify old Raw/Curated data.
- Legacy `batch-<batch_key>.parquet` compatibility is preserved.
- Existing CLI names and behavior do not change because of the v0.4/v0.5 layers; users can keep using only the V0.3 collection/audit workflow.
- V0.4/V0.5 capabilities never run automatically in the background.

## Upgrade from v0.2

- No data directory deletion or rebuild is required, and no existing Parquet needs conversion.
- `init-catalog` stays idempotent and works on already-initialized catalogs.
- V0.2 Raw/Curated data keeps working, and legacy `batch-<batch_key>.parquet` filenames stay supported; new snapshots use run-ID filenames.
- Legacy files missing the newer metadata columns are handled conservatively: `inventory` still counts them (for example as `legacy_metadata_row_count`), and the exact-key coverage audit never fabricates schema metadata from directory paths.
- No automatic migration or deletion is performed.

## Known limitations

- `requested_trade_date` preserves the date requested from moomoo. `market_calendar_date` preserves each returned Eastern-time calendar date. This deliberately avoids pretending that overnight bars can be assigned to an exchange session date without an exchange-calendar layer.
- The option-code parser supports the common moomoo US option format such as `US.MU260807C120000`. Unusual roots should be validated before relying on automatic underlying inference.
- Option-chain metadata is static contract information. Dynamic quotes, trading status changes, Greeks, minute-level Bid/Ask, and complete historical intraday IV are outside V0.3.
- OpenD must be running, logged in, and entitled for the underlying market, option chain, and option volatility data. Permission or quota failures are recorded per request in the run manifest.
- The option-volatility coverage check uses a weekday-boundary heuristic. It does not identify all US exchange holidays; a formal NYSE/Nasdaq exchange calendar is planned for a later version.
- The trading calendar depends on OpenD `request_trading_days` and should not be treated as a complete official exchange-calendar authority.
- Trading-day coverage (`audit`) classifies each requested date as COMPLETE, INCOMPLETE, or MISSING; `intraday-audit` validates the structure of the latest complete physical snapshot and the internal continuity of observed session segments. Session leading/trailing boundaries are still not validated, wholly missing sessions are not judged, no fixed daily bar counts (390, 1201, 1440) are assumed, and early closes are not recognized. Internal gaps are reported as WARN and are never automatically re-collected.
- Incremental mode never re-examines gaps before a symbol's latest completed date; fill them with an explicit range backfill.
- Run one backfill process at a time per dataset; concurrent processes may collect the same items.
- Dataset transforms are limited to the fixed built-in registry: no arbitrary user transforms, no YAML-imported modules, and no cross-trading-day or `TRADING_DAYS` Label execution.
- Dataset builds never auto-refresh or auto-collect data; they consume only the pinned local inputs declared in the build plan.
- The Dataset layer is a data-pipeline interface only: no ML training, no backtest, no signals, and no automatic trading in this release.
