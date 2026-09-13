# MarketVault v0.8.0 Release Notes

Status: Stage 2 release-preparation candidate; formal release gate pending.

```text
RELEASE_PREPARATION_BASE_SHA=1eb3dec68816b133bb97e05d7422184d3815e9dc
RELEASE_PREPARATION_BASE_TREE=9f3f811606b1329b4e5565d42065419d5377bb2b
RELEASE_BLOCKER_PR_153=CLOSED
WINDOWS_PY311_REPARSE_RELEASE_BLOCKER=CLOSED
FORMAL_V070_RELEASE_SHA=f25a50481b5ee718881acf5cb5ea5aa05bd32d93
CANDIDATE_VERSION=0.8.0
TARGET_VERSION=0.8.0
SEMVER_CLASS=MINOR
RELEASE_MODEL=MODEL_RELEASE_FIRST
FORMAL_RELEASE_REQUIRES_SEPARATE_EXPLICIT_GATE=true
```

This document records stable v0.8.0 scope and the release-preparation
candidate contract. It deliberately contains no future merge commit, tag
object, GitHub Release ID, publication timestamp, or formal asset hash. Those
identities can exist only after this candidate merges, exact main is verified,
and a separate formal-release authorization is granted.

## 1. Stable product scope

### Desktop and Windows

- production PySide6/QML desktop and retirement of the legacy Tk production
  presentation;
- desktop parity, hardening, English/Simplified Chinese localization, date
  controls, and product-visible interaction fixes;
- native Windows chrome/icon handling; and
- audited Windows onedir packaging, launcher, and shortcut support.

### Storage and data safety

- registered per-symbol market-bar Raw/Curated snapshot pairs with exact
  physical identities and bindings;
- backward-compatible mixed legacy/new archive reads;
- two-phase Safe Purge into quarantine;
- superseded-snapshot cleanup and cross-policy reconciliation; and
- destructive-operation contracts and fail-closed design gates.

### Market-data correctness

- Timestamp Semantics V2 canonical interval starts in the isolated
  `10.9-mv-ts2` cohort;
- requested-session-safe current market-bar view selection and ambiguous
  duplicate refusal;
- exact bundled-authority US RTH early-close geometry; and
- historical UI business-status semantics that do not report failed backfill
  results as success.

### Python and Dataset consumption

- `select_verified_dataset_catalog_entry(...)` for exact in-memory
  `dataset_id` selection from an already verified Catalog snapshot;
- `ArtifactClient.select_dataset_catalog_entry(...)` as the fourth current
  public business method; and
- one shared exact-selection authority for Python and `dataset-catalog-show`,
  with the existing CLI output contract preserved.

### CI and governance

- risk-tier classification and FULL evidence/reuse controls;
- Python 3.14 and PyArrow 24 compatibility surfaces;
- repository, release, dependency, scope, and destructive-operation gates;
  and
- reviewed production qualification/evidence boundaries for the included
  runtime capabilities.

### PIT policy

Adjusted-Price PIT remains `MODEL_C_NONE_ONLY`. QFQ and HFQ PIT use are not
enabled by v0.8.0.

## 2. Compatibility and migration

```text
PUBLIC_PYTHON_API=BACKWARD_COMPATIBLE_ADDITIVE
ARTIFACTCLIENT_BUSINESS_METHOD_COUNT=4

CANONICAL_ARTIFACT_MIGRATION_REQUIRED=false
DATASET_ARTIFACT_MIGRATION_REQUIRED=false
DATASET_CATALOG_ARTIFACT_MIGRATION_REQUIRED=false
RAW_CURATED_ARTIFACT_REWRITE_REQUIRED=false

DUCKDB_CATALOG_SCHEMA_INITIALIZATION_REQUIRED=true
DUCKDB_CATALOG_SCHEMA_CHANGE_KIND=ADDITIVE_IDEMPOTENT

TS2_MODEL=NEW_SCHEMA_COHORT
LEGACY_10_9_REWRITTEN=false

QFQ_PIT_ALLOWED=false
HFQ_PIT_ALLOWED=false
```

The three v0.7.0 `ArtifactClient` load methods retain their signatures and
behavior. The exact Dataset Catalog selector is additive. Canonical, Dataset,
and Dataset Catalog artifacts and identities are not rewritten.

New market-bar publication uses registered per-symbol pairs, while legacy
single- and multi-symbol physical files remain readable and are not migrated
automatically. Catalog initialization adds the required binding column/table
idempotently; that additive Catalog schema initialization is distinct from an
immutable artifact migration.

TS2 data uses `10.9-mv-ts2`. Legacy `10.9` data remains immutable and separate.
Production schema-cohort activation, collection, recollection, view refresh,
and Safe Purge execution are separately governed operational actions and are
not performed by installing the source package.

## 3. Release-preparation candidate evidence

The Stage 2 candidate must pass all of the following before independent
review:

- version consistency across `pyproject.toml`, package runtime, CLI, and
  installed distribution metadata;
- release checker and dedicated release/version regressions;
- repository hygiene, destructive-operation gates, Python 3.11 FULL tests,
  Python 3.14 compatibility, and PyArrow 24 compatibility;
- fresh wheel and sdist build plus `twine check`;
- fresh-wheel CLI and four-method `ArtifactClient` smoke tests; and
- candidate SHA-256 manifest generation.

Any hashes produced in Stage 2 are PR candidate hashes only. They are not
formal release asset identities and cannot be reused as such.

PR #153 closed the Windows Python 3.11 reparse release blocker before this
candidate baseline was re-established. The correctness and safety fix declares
the `GetFileAttributesW` ABI, distinguishes confirmed absent paths from
attribute-query failures, and rejects Canonical junctions even when their
resolved targets remain inside the build root. This is release-blocker closure,
not an additional v0.8.0 product feature.

## 4. Historical v0.7.0 baseline

The formal v0.7.0 release is immutable at
`f25a50481b5ee718881acf5cb5ea5aa05bd32d93`. Its `ArtifactClient` exposed
exactly:

```text
load_canonical_build
load_dataset
load_dataset_catalog
```

It did not ship the post-v0.7 QML production desktop, Safe Purge, TS2,
qualified early-close RTH geometry, or
`ArtifactClient.select_dataset_catalog_entry(...)`. Historical v0.7.0
direction, usage, contract, and release records retain that truth.

## 5. Formal release gate remains pending

The formal release requires a future explicit gate after candidate merge and
exact-main CI. That gate must build fresh artifacts from the exact release
commit, create the annotated `v0.8.0` tag, publish exactly one wheel, one
sdist, and `SHA256SUMS.txt`, then download and re-hash those assets.

PyPI and TestPyPI publication remain separate explicit decisions. The Windows
production executable remains outside the formal GitHub Release asset set:

```text
PYPI_PUBLICATION_DECISION=SEPARATE_EXPLICIT_GATE
TESTPYPI_PUBLICATION_DECISION=SEPARATE_EXPLICIT_GATE
WINDOWS_PRODUCTION_DEPLOYMENT_IS_GITHUB_RELEASE_ASSET=false
```

## 6. Known boundaries

V0.8.0 does not implement cross-day, `TRADING_DAYS`, or `MINUTES` Label
execution; QFQ/HFQ PIT enablement; corporate-action PIT authority; custom
transforms; Dataset Catalog Python list/filter conveniences; REST; ML
training; backtesting; signals; automatic trading; or live microstructure
capture. These remain outside the frozen v0.8.0 scope.
