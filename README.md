# MarketVault v0.1

MarketVault is a reproducible historical market-data archive for moomoo OpenD. V0.1 focuses on closed-date stock, ETF, and option candlesticks, then stores both source-preserving and normalized Parquet datasets with a DuckDB catalog.

## What this version does

- Connects to a locally running moomoo OpenD instance.
- Pages through `request_history_kline` results.
- Supports daily and intraday candlesticks, including `Session.ALL` where the installed SDK supports it.
- Keeps a raw Parquet layer and a normalized curated layer.
- Adds US Eastern and UTC timestamps plus market-session labels.
- Generates a JSON manifest and data-quality report for every run.
- Maintains DuckDB metadata tables and a deduplicated `market_bars` view.
- Continues collecting other symbols if one symbol fails.

## Important V0.1 boundary

This project can backfill historical candlesticks. It cannot reconstruct historical minute-by-minute Bid/Ask, order-book depth, or option Greeks after the fact. Those fields belong in a later live-capture pipeline.

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

The official Python package is installed from PyPI as `moomoo-api`, while the SDK's import namespace is `futu`.

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
└─ curated/source=moomoo/dataset=market_bars/...
catalog/market_vault.duckdb
manifests/*.json
reports/data_quality/*.json
```

A deterministic batch filename is used for the same date/symbol-set/interval/session/adjustment combination. Re-running the identical request overwrites that batch file. The DuckDB view also deduplicates bars by `(code, interval, adjustment, time_utc)`.

## Tests

```powershell
pytest
```

The tests are offline and do not require OpenD.

## Known limitations

- `requested_trade_date` preserves the date requested from moomoo. `market_calendar_date` preserves each returned Eastern-time calendar date. This deliberately avoids pretending that overnight bars can be assigned to an exchange session date without an exchange-calendar layer.
- The option-code parser supports the common moomoo US option format such as `US.MU260807C120000`. Unusual roots should be validated before relying on automatic underlying inference.
- V0.1 does not yet collect option-chain metadata or daily option volatility; those are the next collector modules.
