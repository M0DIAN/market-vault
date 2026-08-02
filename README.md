# MarketVault v0.2

MarketVault is a reproducible historical market-data archive for moomoo OpenD. V0.1 focused on closed-date stock, ETF, and option candlesticks. V0.2 adds option contract static metadata and daily option volatility datasets while preserving the existing historical K-line interface.

## What this version does

- Connects to a locally running moomoo OpenD instance.
- Pages through `request_history_kline` results.
- Supports daily and intraday candlesticks, including `Session.ALL` where the installed SDK supports it.
- Keeps a raw Parquet layer and a normalized curated layer.
- Adds US Eastern and UTC timestamps plus market-session labels.
- Generates a JSON manifest and data-quality report for every run.
- Maintains DuckDB metadata tables and a deduplicated `market_bars` view.
- Continues collecting other symbols if one symbol fails.
- Collects option-chain static contract metadata from `get_option_chain`.
- Collects daily option volatility analysis rows from `get_option_volatility`.
- Maintains `option_contracts`, `option_contracts_latest`, and `option_volatility_daily` DuckDB views.

## Important data boundary

This project can backfill historical candlesticks, option-chain static metadata, and daily volatility analysis where OpenD and the account permissions allow it. It cannot reconstruct historical minute-by-minute Bid/Ask, order-book depth, Greeks, or complete intraday IV after the fact. Those fields require a live capture and subscription pipeline.

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
├─ curated/source=moomoo/dataset=market_bars/...
├─ curated/option_contracts/underlying_code=US.MU/capture_date=YYYY-MM-DD/...
└─ curated/option_volatility_daily/start_date=YYYY-MM-DD/end_date=YYYY-MM-DD/...
catalog/market_vault.duckdb
manifests/*.json
reports/data_quality/*.json
```

A deterministic batch filename is used for the same date/symbol-set/interval/session/adjustment combination. Re-running the identical request overwrites that batch file. The DuckDB view deduplicates bars by `(code, interval, adjustment, time_utc)`. The `option_volatility_daily` view deduplicates by `(option_code, trade_date, source)` and chooses the latest row by `captured_at DESC NULLS LAST`, with `ingestion_run_id` only as a secondary tie-breaker.

## Tests

```powershell
pytest
```

The tests are offline and do not require OpenD.

## Known limitations

- `requested_trade_date` preserves the date requested from moomoo. `market_calendar_date` preserves each returned Eastern-time calendar date. This deliberately avoids pretending that overnight bars can be assigned to an exchange session date without an exchange-calendar layer.
- The option-code parser supports the common moomoo US option format such as `US.MU260807C120000`. Unusual roots should be validated before relying on automatic underlying inference.
- Option-chain metadata is static contract information. Dynamic quotes, trading status changes, Greeks, minute-level Bid/Ask, and complete historical intraday IV are outside V0.2.
- OpenD must be running, logged in, and entitled for the underlying market, option chain, and option volatility data. Permission or quota failures are recorded per request in the run manifest.
