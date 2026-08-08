# MarketVault v0.7.0 Existing Python API Audit

Audit of the existing Python public API surface at the v0.6.1 release
commit `37614d539171ef7b738e47415f3cd6ca2de332d1`. Every statement below
was taken from the source at that commit; nothing is inferred from memory
or documentation.

## A. Top-level package

`src/market_vault/__init__.py` currently declares:

```python
__all__ = ["MarketVault", "__version__"]
```

`MarketVault` is loaded through a module-level `__getattr__` lazy-load
hook: plain `import market_vault` imports no heavy dependency. A plain
package import must stay lightweight and must never eagerly import
`duckdb`, `pandas`, `moomoo`, or `futu`.

## B. Existing MarketVault

`src/market_vault/api.py` defines:

```python
class MarketVault:
    def __init__(
        self,
        settings: Settings | str | Path = "config/settings.yaml",
    ):
```

The constructor calls `load_settings(...)` (unless a `Settings` object is
passed directly) and then constructs `Catalog(self.settings)`. The
existing `market_vault.MarketVault` is therefore a **settings-backed,
legacy local-database client**: it binds to `settings.yaml`, a DuckDB
Catalog, the local data root, and OpenD collection through `backfill`;
`plan_backfill` is local Catalog-backed planning with no OpenD/network.
It is NOT a settings-independent artifact client.

## C. Current MarketVault method surface

The full public method surface of `MarketVault` at the v0.6.1 release
commit, with signatures and side-effect categories taken from source:

| Method | Signature (source) | Side-effect category |
| --- | --- | --- |
| `load_bars` | `(code, start=None, end=None, trade_date=None, interval="1m", session=None, adjustment="NONE") -> pd.DataFrame` | read-local (DuckDB view over curated market bars) |
| `load_trading_calendar` | `(market=None, code=None, start_date=None, end_date=None) -> pd.DataFrame` | read-local (DuckDB view over curated trading calendar) |
| `plan_backfill` | `(*, symbols, end_date, calendar_market=None, calendar_code=None, start_date=None, interval="1m", session=None, adjustment=None, force=False, incremental=False, bootstrap_start_date=None, today=None)` | local planning / read-local (reads Catalog; no OpenD/network; uses current UTC date when today is omitted) |
| `backfill` | `(*, symbols, end_date, calendar_market=None, calendar_code=None, start_date=None, interval="1m", session=None, adjustment=None, force=False, incremental=False, bootstrap_start_date=None, max_retries=2, retry_backoff_seconds=2.0, today=None)` | collection (network / OpenD-capable, writes local data) |
| `inventory_market_bars` | `(*, symbols=None, start_date=None, end_date=None, interval=None, session=None, adjustment=None, source_schema_version=None, include_files=False, today=None) -> InventoryReport` | audit / read-local (no OpenD, no mutation) |
| `audit_market_bars` | `(*, symbols, start_date, end_date, calendar_market=None, calendar_code=None, interval="1m", session=None, adjustment=None, source_schema_version=None, include_complete_dates=False, today=None) -> AuditReport` | audit / read-local (no OpenD, no mutation) |
| `audit_intraday_market_bars` | `(*, symbols, start_date, end_date, calendar_market=None, calendar_code=None, interval="1m", session=None, adjustment=None, source_schema_version=None, include_pass_checks=False, max_gap_details=100, today=None) -> IntradayAuditReport` | audit / read-local (no OpenD, no mutation, no repair) |

Notes:

- `backfill` / `plan_backfill` fall back to `settings.default_session` /
  `settings.default_adjustment` when omitted — the settings binding is
  structural, not incidental.
- The audit methods document "Pure local: no OpenD connection and no data
  mutation"; they are already read-only, but they are still
  settings-backed and Catalog-backed.
- None of the methods above reads a verified artifact directory: they read
  through the legacy local database (Catalog + DuckDB views).

## D. Modern verified artifact public authorities

The verified artifact readers are the formal trust boundaries for
immutable artifacts. They are the only public authorities that recompute
every content / physical identity from the artifact's own bytes, reject
symlinks, and never write, repair, or rewrite:

- `market_vault.canonical.load_verified_canonical_build(build_dir)`
  → `VerifiedCanonicalBuild` (frozen dataclass: canonical_build_id,
  canonical_content_id, resolution_content_id, gap_content_id,
  canonical_builder_version, canonical_schema_version,
  materializer_version, gap_policy_version, status,
  `normalized_request: VerifiedCanonicalRequest`,
  `bars: tuple[CanonicalBar]`, canonical_row_version_ids,
  source_snapshot_provenance, gap_ranges, gap_boundaries, gap_count,
  `manifest_payload: bytes`, `build_path: Path`); errors →
  `CanonicalArtifactValidationError`.
  Source: `src/market_vault/canonical/reader.py`.
- `market_vault.dataset.load_verified_dataset(build_dir)`
  → `VerifiedDatasetBuild` (frozen dataclass: reader_contract_version,
  dataset_id, dataset_kind, status, built_at, dataset_as_of,
  `schema: DatasetSchema`, rows, manifest, feature_specs, label_specs,
  split_spec, split_result, build_report, `manifest_payload: bytes`,
  `build_report_payload: bytes`, `build_path: Path`); errors →
  `DatasetArtifactValidationError`.
  Source: `src/market_vault/dataset/reader.py`.
- `market_vault.dataset.load_verified_dataset_catalog(snapshot_dir)`
  → `VerifiedDatasetCatalogSnapshot` (frozen dataclass:
  reader_contract_version, snapshot_schema_version,
  catalog_contract_version, catalog_entry_schema_version,
  catalog_content_id_version, builder_version, snapshot_id,
  catalog_content_id, dataset_count, built_at, `snapshot_dir: Path`,
  manifest, entries); errors →
  `DatasetCatalogArtifactValidationError`.
  Source: `src/market_vault/dataset/dataset_catalog_reader.py`.

Finding: these three readers are the formal trust boundaries. A future
client must delegate to them and must never re-implement verification,
never parse `manifest.json` / `catalog.json` itself, and never read
Dataset Parquet through a second validation path.

## E. Compatibility finding

`market_vault.MarketVault` is an existing public compatibility surface.
v0.7.0 MUST NOT:

- remove it;
- rename it;
- change its existing constructor default
  (`settings: Settings | str | Path = "config/settings.yaml"`);
- silently make settings optional;
- change existing method semantics;
- replace the legacy Catalog behavior.

PR-1 makes no change to any of these surfaces. `git diff
V070_PR1_BASE_SHA -- src/` is empty.

## F. Recommended v0.7 architecture

The recommended architecture is a **separate, settings-independent
artifact client** living beside the existing settings-backed
`MarketVault`, never replacing it.

- public planned name: `ArtifactClient`;
- future intended import: `from market_vault import ArtifactClient`;
- PR-1 does not define that symbol; it is a planned name only.

PR-1 found no public-name collision, architecture contradiction, or
compatibility blocker for the planned `ArtifactClient` name: the name is
not present anywhere in `src/` at the v0.6.1 release commit. If a later
PR finds such a collision, it must stop and report separately; it must
not rename the planned public name on its own.
