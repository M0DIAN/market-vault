# MarketVault

MarketVault is a local-first historical market-data and verified
research-data pipeline for moomoo OpenD. It collects and audits historical
market data, builds immutable and verifiable research artifacts, and
exposes deterministic Dataset / Catalog / Python read surfaces for
research and ML consumers.

## What MarketVault is

MarketVault runs against a locally installed moomoo OpenD instance. It
collects historical candlesticks, option contract metadata, daily option
volatility, and trading-calendar data; keeps immutable Raw / Curated
snapshots; audits coverage and intraday integrity; and derives verified
Canonical builds and deterministic Datasets that research code can consume
safely. It does not train models, produce signals, or trade automatically.

## Core capabilities

- Historical stock / ETF / option market-data collection through moomoo OpenD
- Local trading calendar and resumable historical backfill
- Immutable Raw / Curated snapshots
- Inventory, coverage, and intraday integrity auditing
- Verified immutable Canonical builds
- Deterministic point-in-time-safe Dataset construction
- Deterministic Sample Generation and immutable Dataset Catalog
- Verified CLI and Python ArtifactClient read access

## Data flow

```text
moomoo OpenD
    ↓
Raw / Curated snapshots
    ↓
Audit
    ↓
Verified Canonical
    ↓
Deterministic Dataset
    ↓
Dataset Catalog
    ↓
Python / research / ML consumers
```

## Design principles

- **Deterministic** — identical inputs produce identical artifacts and identities
- **Immutable** — snapshots, builds, and Datasets are never rewritten
- **Explicit inputs** — no `latest` discovery, no hidden scans, no auto-chosen artifacts
- **Fail-closed verification** — every read goes through a verified reader that rejects any inconsistency
- **Point-in-time safety** — leakage-safe clocks, chronological splits, actual-label-end purging
- **Read-only verified consumption** — readers never repair, rewrite, or delete

## Quick start

Requires Python >= 3.11, plus moomoo OpenD (running and logged in) for
OpenD-backed collection commands. PyPI is not published, so install from
the source tree:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

Then check the CLI:

```powershell
market-vault --version
market-vault --help
```

For the full workflow (`init-catalog` → `calendar` → `backfill` →
`inventory` → `audit` → `intraday-audit` → `query`), see the
[MarketVault 使用说明](docs/USER_GUIDE.md).

## Python access

```python
from pathlib import Path
from market_vault import ArtifactClient

client = ArtifactClient()

dataset = client.load_dataset(Path(r"D:\data\datasets\<dataset_id>"))
print(dataset.dataset_id, dataset.status, len(dataset.rows))
```

`ArtifactClient` is settings-independent and strictly read-only: pass the
exact final artifact directory, and there is no `latest` discovery, no
settings lookup, and no network / OpenD / current-time behavior. Full
details in the [user guide](docs/USER_GUIDE.md) and the
[Python Client usage guide](docs/v0_7_0_python_client_usage.md).

## Data boundaries

- Historical data availability depends on OpenD and the account's
  market-data permissions and historical quota.
- Historical minute-by-minute Bid/Ask, order-book depth, complete intraday
  Greeks, and IV cannot be reconstructed after the fact if they were never
  captured; those fields need a live capture and subscription pipeline.
- MarketVault does not provide automatic trading, signals, or ML model
  training.
- `ArtifactClient` is read-only, and verified artifact reads never
  auto-discover a "latest" artifact.

## Documentation

- Full user guide: [docs/USER_GUIDE.md](docs/USER_GUIDE.md)
- Version history: [CHANGELOG.md](CHANGELOG.md)
- Formal v0.7.0 release record: [docs/release_v0_7_0.md](docs/release_v0_7_0.md)
- Python Client detailed guide: [docs/v0_7_0_python_client_usage.md](docs/v0_7_0_python_client_usage.md)
- Contracts: [docs/contracts/](docs/contracts/)
- Development / governance: [docs/governance/](docs/governance/)

## Current release

- Current formal release: v0.7.0
- GitHub Release: published
- PyPI: not published
- TestPyPI: not published

Release commit SHAs, tag objects, asset hashes, and release audit evidence
belong in the formal release records, not in this README.

## License

MIT — see [LICENSE](LICENSE).
