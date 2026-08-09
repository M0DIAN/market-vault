# MarketVault Python Client Contract

Status: PR-2 foundation implemented in v0.7.0 development; artifact read capabilities not implemented

Target release: v0.7.0

Public root: `ArtifactClient`

Formal v0.6.1 GitHub Release artifacts DO NOT contain `ArtifactClient`.
Current unreleased v0.7.0 development introduces the `ArtifactClient`
foundation while the package metadata remains 0.6.1 under the frozen version policy.

PR-2: foundation implemented (`ArtifactClient()` constructs a stateless,
settings-independent client).
PR-3: Canonical + Dataset verified read-only access.
PR-4: Dataset Catalog verified read-only access (see
`docs/v0_7_0_direction.md`).

## 13.1 Existing MarketVault compatibility

`market_vault.MarketVault` remains the existing settings-backed API.
The v0.7 `ArtifactClient` is separate. `ArtifactClient` must not alter:

- the `MarketVault` constructor;
- the `MarketVault` settings behavior;
- the `MarketVault` methods;
- the legacy Catalog behavior.

## 13.2 Constructor

PR-2 foundation implemented:

```python
ArtifactClient()
```

- Zero arguments.
- Stateless.
- No required settings.
- No default settings path.
- No implicit `config/settings.yaml`.
- No filesystem access in the constructor.
- No network.
- No OpenD.
- No current time.
- No cwd-derived artifact root.

## 13.3 Read-only scope

The v0.7 `ArtifactClient` only serves verified immutable artifacts.

Planned capabilities:

- Canonical verified access;
- Dataset verified access;
- Dataset Catalog verified access;
- Python-side read-only Catalog lookup/filter access, only if implemented
  through one shared verified authority.

PR-2 implements none of them.
PR-3: Canonical + Dataset verified read-only access.
PR-4: Dataset Catalog verified read-only access.

No build / materialize / generate / repair / write APIs.

## 13.4 Trust boundary

`ArtifactClient` must delegate to:

- `load_verified_canonical_build`
- `load_verified_dataset`
- `load_verified_dataset_catalog`

It must NEVER:

- parse `manifest.json` itself;
- parse `catalog.json` itself;
- read Dataset Parquet through a second validation path;
- trust stored identity without the formal reader;
- repair artifacts;
- rewrite artifacts;
- delete artifacts;
- adopt partial staging output.

## 13.5 Path contract

Explicit artifact paths only. No:

- `latest`;
- auto-discovery;
- glob discovery;
- environment-variable root;
- settings-derived root;
- cwd default root;
- recursive scan;
- search by guessing IDs.

Do not resolve symlinks to hide them. The formal readers remain
responsible for their security/trust checks.

## 13.6 Read semantics

Read only. No:

- current time;
- mtime mutation;
- metadata mutation;
- cache file writes;
- sidecar;
- index creation;
- DuckDB Catalog construction.

## 13.7 Return-value authority

The client must return formal verified objects, or immutable thin views
derived solely from formal verified objects. It must not expose
unverified raw-file facts as trusted results.

## 13.8 Error boundary

Do not create a second artifact-validation universe. Underlying public
formal reader validation errors must remain visible/preserved. If a
future client-only argument error type is introduced, it must be narrow
and must not swallow reader errors. No warn-and-continue.
No partial success from a corrupt artifact.

## 13.9 Lightweight import

Plain `import market_vault` must remain lightweight. The future
`ArtifactClient` export must be lazy. Plain package import must never
eagerly import `duckdb`, `pandas`, `moomoo`, or `futu`. Prefer reader
imports at the actual method-call boundary if required to keep the import
lightweight.

## 13.10 Explicit non-goals

- No REST API.
- No API server.
- No HTTP service.
- No new CLI command.
- No `dataset-catalog-query` CLI.
- No ML training.
- No model evaluation.
- No experiment tracking.
- No backtesting.
- No signals.
- No automatic trading.
- No Trading Execution.
- No new artifact format.
- No identity v2.
- No schema v2.
- No migration.
- No dependency modernization.
