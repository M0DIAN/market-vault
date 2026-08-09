# MarketVault Python Client Contract

Status: PR-6 v0.7.0 release preparation in unreleased v0.7.0 development

Target release: v0.7.0

Public root: `ArtifactClient`

Formal v0.6.1 GitHub Release artifacts DO NOT contain `ArtifactClient`.
Current unreleased v0.7.0 development introduces the `ArtifactClient`
foundation (PR-2), the Canonical + Dataset verified read-only access
(PR-3), the Dataset Catalog verified read-only access (PR-4), and the
integrated acceptance / usability / consumer examples (PR-5, merged
PR #52). The PR-6 release preparation bumps the package metadata to 0.7.0
under the frozen version policy.

PR-2: foundation implemented (`ArtifactClient()` constructs a stateless,
settings-independent client).
PR-3: Canonical + Dataset verified read-only access implemented
(`ArtifactClient.load_canonical_build(build_dir)` and
`ArtifactClient.load_dataset(build_dir)` delegate to the formal verified
readers and return their verified objects directly).
PR-4: Dataset Catalog verified read-only access implemented
(`ArtifactClient.load_dataset_catalog(snapshot_dir)` delegates to the
formal verified Catalog reader and returns its verified object directly;
see `docs/v0_7_0_direction.md`).
PR-5: integrated acceptance/usability/examples COMPLETE / MERGED / MAIN VERIFIED (offline
end-to-end acceptance over real committed artifacts, explicit-path
Python / Jupyter / ML-consumer usage documentation, source-tree
examples, and backward-compatibility hardening; see
`docs/v0_7_0_python_client_usage.md` and `examples/python_client/README.md`).
PR-6: release preparation CURRENT.
package: 0.7.0
v0.7.0: NOT RELEASED

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

Implemented capabilities (PR-3 / PR-4):

- Canonical verified access: `ArtifactClient.load_canonical_build(build_dir)`;
- Dataset verified access: `ArtifactClient.load_dataset(build_dir)`;
- Dataset Catalog verified access:
  `ArtifactClient.load_dataset_catalog(snapshot_dir)`.

Not implemented (convenience API):

- No Catalog list convenience;
- No Catalog show convenience;
- No Catalog filter convenience;
- No Catalog query convenience;
- no Python-side read-only Catalog lookup/filter access beyond the one
  formal verified Catalog reader.

The public business methods are exactly `load_canonical_build`,
`load_dataset` and `load_dataset_catalog`.
No build / materialize / generate / repair / write APIs.

## 13.4 Trust boundary

`ArtifactClient` must delegate to:

- `load_verified_canonical_build`
- `load_verified_dataset`
- `load_verified_dataset_catalog`

Exact formal delegation:

- `ArtifactClient.load_canonical_build(build_dir)` ->
  `market_vault.canonical.reader.load_verified_canonical_build(build_dir)`
  -> exact `VerifiedCanonicalBuild`
- `ArtifactClient.load_dataset(build_dir)` ->
  `market_vault.dataset.reader.load_verified_dataset(build_dir)`
  -> exact `VerifiedDatasetBuild`
- `ArtifactClient.load_dataset_catalog(snapshot_dir)` ->
  `market_vault.dataset.dataset_catalog_reader.load_verified_dataset_catalog(snapshot_dir)`
  -> exact `VerifiedDatasetCatalogSnapshot`

The client returns the direct formal verified objects. There is
no client-side artifact parsing, no client-side validation, and
no exception wrapping and no second trust path. Reader imports
occur at the method-call boundary.

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

The client returns the formal verified objects directly:
`load_canonical_build` returns exactly
`VerifiedCanonicalBuild`; `load_dataset` returns exactly
`VerifiedDatasetBuild`; `load_dataset_catalog` returns exactly
`VerifiedDatasetCatalogSnapshot`. No thin views and no client-side result
construction. The client must not expose unverified raw-file facts as
trusted results.

## 13.8 Error boundary

Do not create a second artifact-validation universe. The client does not
catch or wrap formal reader errors: Canonical reader failures remain the
exact existing `CanonicalArtifactValidationError` behavior, Dataset
reader failures remain the exact existing
`DatasetArtifactValidationError` behavior, and Catalog reader failures
remain the exact existing `DatasetCatalogArtifactValidationError`
behavior. No client-specific replacement error universe.
No warn-and-continue. No partial success from a corrupt artifact. The exact
`build_dir` / `snapshot_dir` value supplied by the caller is passed to
the formal reader without client-side coercion.

## 13.9 Lightweight import

Plain `import market_vault` must remain lightweight. The `ArtifactClient`
export stays lazy. It must never eagerly import `duckdb`, `pandas`, `moomoo`, or `futu`.
The `artifact_client.py` module has no module-level production import
except `__future__.annotations`; reader imports happen at the actual
method-call boundary, so accessing or binding
`client.load_canonical_build` / `client.load_dataset` /
`client.load_dataset_catalog` loads nothing heavy — only actual method
invocation crosses the reader import boundary.

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

## 13.11 PR-5 consumer-side usability boundary

The v0.7.0 usage documentation and the source-tree examples
(`docs/v0_7_0_python_client_usage.md`, `examples/python_client/`) are
CONSUMER-SIDE only. They do not create a second trust path: no example
and no documentation introduces its own artifact parsing, validation,
discovery, settings, environment-derived root, network/OpenD, or
current-time behavior. The formal verified readers remain the only
validation authority; examples only call `ArtifactClient` with explicit
paths and print trusted fields from the returned verified objects.

Consumer transformations performed AFTER an ArtifactClient verified read,
for example constructing an in-memory pandas DataFrame from the already
verified Dataset rows, are not artifact verification and are not part of
the ArtifactClient trust contract. Such transformations are plain
consumer-side data handling on top of already verified facts; they never
re-verify artifacts, never bypass the formal verified readers (for
example by parsing `dataset.parquet` directly), and never write back into
artifact directories.
