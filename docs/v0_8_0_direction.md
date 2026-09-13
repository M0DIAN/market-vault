# MarketVault v0.8.0 Release Direction

Status: scope frozen on main; Stage 2 release-preparation candidate.

```text
FORMAL_V070_RELEASE_SHA=f25a50481b5ee718881acf5cb5ea5aa05bd32d93
V080_DIRECTION_BASE_SHA=1f4da9154cdbe4a9b48e025a4777562fed0ef305
V080_DIRECTION_BASE_TREE=1914566269b84ac31b9bf2fe4fc210daaf1cd133
COMMITS_SINCE_V070=93
DIRECTION_BASE_PACKAGE_VERSION=0.7.0
CURRENT_PACKAGE_VERSION=0.8.0
TARGET_VERSION=0.8.0
SEMVER_CLASS=MINOR
RELEASE_MODEL=MODEL_RELEASE_FIRST
DIRECTION_DOCUMENT_SELF_AUTHORIZATION=false
RELEASE_PREPARATION_REQUIRES_POST_MERGE_AUTHORIZATION=true
RELEASE_PREPARATION_STAGE=STAGE_2_CANDIDATE
FORMAL_RELEASE_REQUIRES_SEPARATE_EXPLICIT_GATE=true
```

This document freezes the intended next formal release boundary. The direction
base is a reviewed product baseline, not a release commit, tag, package, or
published v0.8.0 artifact. This document alone does not authorize release
preparation, a version change, tagging, publication, or production work.

## 1. Historical boundary

### FORMAL_V070_RELEASE

The immutable v0.7.0 release is identified by commit
`f25a50481b5ee718881acf5cb5ea5aa05bd32d93`. Its released
`ArtifactClient` had exactly these public business methods:

```text
load_canonical_build
load_dataset
load_dataset_catalog
```

The v0.7.0 release did not contain the later QML production desktop, Safe
Purge lifecycle, Timestamp Semantics V2, qualified early-close RTH support,
or explicit Dataset Catalog selection API. Those facts must not be rewritten
in historical v0.7.0 direction, audit, usage, or release records.

### POST_V070_CURRENT_MAIN

The direction base contains 93 commits after the formal v0.7.0 release and
was frozen while package version was still `0.7.0`. Stage 2 changes only the
release-preparation surface and sets the candidate package version to `0.8.0`;
it does not publish v0.8.0. The reviewed capabilities listed in section 3 are
the product baseline proposed for formal release.

### V080_RELEASE_SCOPE

V0.8.0 consolidates the reviewed post-v0.7 current-main increment. Release
preparation may make only the version, release-documentation, checker, and
validation changes needed to release that increment. Any substantive product
feature discovered after this scope freeze belongs in a dedicated blocker-fix
PR or a post-v0.8 workstream.

### V080_NON_GOALS

V0.8.0 does not include the deferred capabilities in section 5. Their absence
from this release is not a declaration that they are permanent product
non-goals unless an existing authoritative contract already says so.

### FUTURE_POST_V080_WORK

The first expected product-design candidate after v0.8.0 is
`CROSS_DAY_AND_TRADING_DAYS_LABEL_DESIGN`. That work requires a separate
design authority and must not begin through this direction PR.

## 2. Version decision

`0.8.0` is a SemVer minor release. The baseline adds multiple
backward-compatible product, runtime, Python API, storage, safety, desktop,
and governance capabilities. It is therefore broader than a `0.7.1` patch.
No intentional incompatible public-contract reset has been approved, so
`1.0.0` is not justified by this scope.

The `0.7.0` to `0.8.0` version change is confined to the explicitly
authorized Stage 2 release-preparation PR. Tagging, GitHub Release publication,
and distribution publication remain later explicit gates.

## 3. V0.8.0 included scope

### A. Desktop and Windows product

- the production PySide6/QML desktop and production QML cutover;
- retirement of the legacy Tk presentation as a supported production UI;
- desktop parity, hardening, live English/Simplified Chinese localization,
  product-visible date controls, and related interaction polish;
- native Windows chrome and icon handling; and
- the audited Windows desktop PyInstaller onedir packaging, launcher, and
  shortcut support.

### B. Storage and data safety

- registered physical per-symbol market-bar Raw/Curated snapshot pairs and
  their exact run, manifest, and Catalog bindings;
- physical snapshot identity and fail-closed binding checks while retaining
  legacy archive readability;
- two-phase Safe Purge into same-volume quarantine, without permanent
  deletion;
- quarantine lifecycle evidence, superseded-snapshot cleanup, and
  cross-policy reconciliation;
- explicit exact-scope and superseded-only plan versions with preserved
  historical meanings; and
- destructive-operation contracts, ownership assertions, and repository
  design gates.

### C. Market-data correctness

- Timestamp Semantics V2 canonical interval-start semantics and isolated
  `10.9-mv-ts2` source-schema cohort handling;
- the reviewed production TS2 qualification and activation record;
- requested-session-safe current market-bar view selection, including
  `requested_trade_date` and `requested_session` in the current-row identity
  and fail-closed ambiguous-duplicate behavior; and
- qualified US RTH early-close geometry for the exact bundled special-session
  authority and sealed Moomoo provider profile, while preserving the normal
  09:30-16:00 profile for absent dates.

### D. Python and Dataset consumption

- the exact in-memory Dataset Catalog entry selection authority
  `select_verified_dataset_catalog_entry(...)`;
- `ArtifactClient.select_dataset_catalog_entry(...)`, bringing the
  current-main public business-method count to four;
- exact `dataset_id` equality, fail-closed zero/multiple/malformed selection,
  and exact entry-object identity preservation; and
- `dataset-catalog-show` reuse of the formal selector without changing its
  external output or failure contract.

### E. CI and development governance

- path/risk-based CI classification and FULL-matrix evidence/reuse controls;
- Python 3.14 and PyArrow 24 compatibility surfaces;
- the destructive-operation design gate and exact ownership contracts; and
- release, dependency, repository-hygiene, scope, and development-governance
  hardening accumulated after v0.7.0.

### F. PIT safety policy

- Adjusted-Price PIT As-Of Policy V1;
- `MODEL_C_NONE_ONLY` as the current policy; and
- continued fail-closed rejection of QFQ and HFQ PIT samples until a separate
  corporate-action knowledge-clock and authority qualification exists.

## 4. Compatibility audit

The classifications below are scoped to upgrading from the formal v0.7.0
release to the proposed v0.8.0 baseline. `NO_MIGRATION_REQUIRED` means no
operator-driven rewrite of the named artifact or state. It does not erase an
explicit additive Catalog initialization step where one is identified.

| Surface | Classification | Exact effect |
|---|---|---|
| Public Python API | `BACKWARD_COMPATIBLE`, `NEW_CAPABILITY`, `NO_MIGRATION_REQUIRED` | The three released v0.7.0 load methods retain their signatures and behavior. The exact Dataset Catalog selection method is additive; `ArtifactClient()` remains stateless. |
| Dataset package API | `BACKWARD_COMPATIBLE`, `NEW_CAPABILITY` | The formal selector and selection error are exported from `market_vault.dataset`, not top-level `market_vault`; lightweight top-level import behavior is preserved. |
| CLI | `BACKWARD_COMPATIBLE`, `NEW_CAPABILITY` | Post-v0.7 operational commands are additive. `dataset-catalog-show` delegates to one formal selector while retaining arguments, success JSON, stderr/stdout behavior, and exit codes. |
| Canonical artifact schema and identities | `BACKWARD_COMPATIBLE`, `NO_MIGRATION_REQUIRED` | Existing Canonical schemas, bar keys, row-version IDs, content IDs, build IDs, and manifests are not rewritten by the included selection or PIT-policy work. Explicit source-schema evidence continues to bind materialization. |
| Dataset artifact schema and identities | `BACKWARD_COMPATIBLE`, `NO_MIGRATION_REQUIRED` | Dataset manifests, Dataset IDs, sample identities, and verified readers remain unchanged. Adjusted-price PIT remains NONE-only, so no adjusted artifact is newly qualified or reinterpreted. |
| Dataset Catalog schema and identities | `BACKWARD_COMPATIBLE`, `NO_MIGRATION_REQUIRED` | Catalog content IDs, snapshot IDs, files, and reader validation remain unchanged. Selection consumes an already verified snapshot and performs no rewrite or path resolution. |
| Raw/Curated physical layout | `BACKWARD_COMPATIBLE`, `NEW_CAPABILITY`, `NO_MIGRATION_REQUIRED` | New market-bar publication uses registered per-symbol physical pairs. Legacy single- and multi-symbol files remain readable in mixed archives and are not split, moved, or rewritten merely for upgrade. |
| Run manifests and physical binding | `BACKWARD_COMPATIBLE`, `NEW_CAPABILITY` | New-format manifests add `snapshot_binding_mode` and exact `snapshot_pairs`. Legacy manifests without those fields retain their legacy meaning; null legacy run bindings remain supported under exact proofs. |
| DuckDB/Catalog schema | `BACKWARD_COMPATIBLE`, `NEW_CAPABILITY`, `MIGRATION_REQUIRED` | Catalog initialization performs additive, idempotent schema evolution for physical snapshot binding, including `ingestion_runs.snapshot_binding_mode` and `market_bar_snapshot_pairs`. This is a Catalog schema initialization migration, not a Raw/Curated or research-artifact rewrite. |
| Market-bar source schema | `NEW_SCHEMA_COHORT`, `NO_MIGRATION_REQUIRED` | Corrected TS2 rows use `10.9-mv-ts2`. Legacy `10.9` files remain immutable and independently queryable through archive-oriented surfaces; they are never relabeled as TS2. Production configuration cutover and any recollection are separate operational actions, not release installation side effects. |
| Current DuckDB market-bar view | `BACKWARD_COMPATIBLE` for unambiguous requests; fail-closed correctness tightening for ambiguity | The current view selects only the configured source/schema cohort and partitions current rows by requested trade date and requested session. Single-cohort omitted-session queries remain compatible; multi-cohort unscoped or exact duplicate ambiguity now refuses instead of selecting unsafely. The archive view remains physical-history authority. |
| Timestamp/session semantics | `NEW_CAPABILITY`, `NO_MIGRATION_REQUIRED` | TS2 maps qualified provider endpoint geometry to canonical interval starts in a separate cohort. Existing accepted `10.9` data is not reinterpreted. Normal RTH geometry remains exact; only bundled, independently qualified early-close dates use the 13:00 profile. |
| Safe Purge artifacts and lifecycle | `BACKWARD_COMPATIBLE`, `NEW_CAPABILITY`, `NO_MIGRATION_REQUIRED` | Historical plan versions retain exact meanings. New superseded-only and reconciled plans add explicit evidence; execution still moves sealed whole Raw/Curated pairs to quarantine and never grants permanent-delete authority. Existing data is not purged by upgrade. |
| Desktop preferences | `NEW_CAPABILITY`, `NO_MIGRATION_REQUIRED` | QML desktop language preference is stored at `%LOCALAPPDATA%\MarketVault\desktop-preferences.json`. Absence uses the documented default; package-local settings and market-data state are not used as preference storage. |
| Production desktop packaging | `NEW_CAPABILITY`, `NOT_APPLICABLE` to wheel/sdist compatibility | The Windows QML onedir executable, launcher, shortcut, icon, and deployment procedure form a separate production lifecycle. They do not change the formal source-package asset contract. |
| Existing v0.7.0 artifacts | `BACKWARD_COMPATIBLE`, `NO_MIGRATION_REQUIRED` | Previously built immutable Canonical, Dataset, and Dataset Catalog artifacts remain historical evidence and are consumed through their explicit versioned readers and identities. No v0.8 direction step rewrites them. |
| CI and governance | `NEW_CAPABILITY`, `NOT_APPLICABLE` to persisted product data | Classification, FULL evidence, Python/PyArrow portability, destructive-operation, and release checks change development/release gates, not artifact bytes or production state. |
| Adjusted-price PIT | `BACKWARD_COMPATIBLE` current behavior | The policy records and preserves the existing NONE-only guard. QFQ/HFQ remain disabled; there is no identity, schema, or migration change in v0.8.0. |

The Catalog migration row is intentionally distinct from physical/archive
migration. Upgrading runtime code may initialize additive DuckDB columns or
tables; it must not rewrite immutable Raw, Curated, Canonical, Dataset, or
Dataset Catalog artifacts. Production deployment, schema-cohort activation,
collection, recollection, Safe Purge execution, and view refresh remain
separately governed operational actions.

## 5. V0.8.0 exclusions

The release-first model freezes all of the following as
`OUT_OF_V080_SCOPE` and `DEFERRED_POST_V080`:

- Cross-Trading-Day Label execution;
- `TRADING_DAYS` Label execution;
- `MINUTES` Label execution;
- QFQ or HFQ PIT enablement;
- corporate-action PIT authority and its third knowledge clock;
- custom or arbitrary transformation execution;
- Dataset Catalog list/filter convenience Python APIs;
- a REST API;
- ML training, backtesting, signal generation, or automatic trading; and
- live microstructure capture.

Current label runtime remains fail closed:

```text
CROSS_DAY_LABEL_IMPLEMENTED=false
TRADING_DAYS_LABEL_IMPLEMENTED=false
MINUTES_LABEL_IMPLEMENTED=false
```

The first expected post-v0.8 design candidate is:

```text
POST_V080_PRIORITY_1=CROSS_DAY_AND_TRADING_DAYS_LABEL_DESIGN
```

## 6. Adjusted-price boundary

V0.8.0 freezes the current policy without enabling adjusted-price PIT use:

```text
ADJUSTED_PRICE_PIT_POLICY=MODEL_C_NONE_ONLY
QFQ_PIT_ALLOWED=false
HFQ_PIT_ALLOWED=false
```

Future QFQ/HFQ enablement requires separate corporate-action authority,
knowledge-clock, provider-evidence, identity-impact, and migration analysis.
It is not a v0.8.0 release blocker because the current runtime already fails
closed in conformance with the policy.

## 7. Distribution boundary

The current distribution facts are:

```text
PYPI=NOT_PUBLISHED
TESTPYPI=NOT_PUBLISHED
PYPI_PUBLICATION_DECISION=SEPARATE_EXPLICIT_GATE
TESTPYPI_PUBLICATION_DECISION=SEPARATE_EXPLICIT_GATE
```

PyPI or TestPyPI publication is not a prerequisite for a formal v0.8.0
GitHub Release and is not implied by a tag or GitHub Release.

The existing Release Playbook defines the formal GitHub Release assets as
exactly one wheel, one sdist, and `SHA256SUMS.txt`. The Windows production EXE
and onedir deployment remain a separate production lifecycle:

```text
WINDOWS_PRODUCTION_DEPLOYMENT_IS_GITHUB_RELEASE_ASSET=false
```

Adding an EXE to a formal GitHub Release would require a separately reviewed
release-governance change.

## 8. Release sequence

### STAGE_1: direction and compatibility scope freeze

This docs-only PR records the intended v0.8.0 scope, compatibility effects,
non-goals, and sequence. It does not change the package version or authorize
later stages.

### STAGE_2: release preparation

After Stage 1 independent review, merge, and separate post-merge
authorization, a focused release-preparation PR may include:

- package version `0.7.0` to `0.8.0`;
- a v0.8.0 CHANGELOG section;
- `docs/release_v0_8_0.md`;
- README current-release/lifecycle preparation state where appropriate;
- checker and regression changes required by the actual v0.8.0 surface; and
- exact FULL CI and package validation.

### STAGE_3: exact-main verification

After the release-preparation PR merges, verify the exact formal main commit,
its tree, single-parent identity as applicable, and natural main push CI. Any
drift invalidates downstream release authorization.

### STAGE_4: immutable formal release gate

Only after a separate formal release authorization:

1. create a clean detached checkout at the exact release commit;
2. build and validate a fresh wheel and sdist;
3. create the annotated `v0.8.0` tag at that exact commit;
4. produce the per-package `SHA256SUMS.txt`;
5. publish the GitHub Release with exactly those three assets; and
6. download and re-hash the published assets to close identity.

PyPI and TestPyPI remain separate explicit decisions after the formal release
gate.

## 9. Blocker rule

If scope freeze or release preparation exposes a real release blocker, fix it
in a dedicated blocker-fix PR. Do not add unrelated product work to release
preparation. After any blocker fix, re-establish and independently verify the
exact release-preparation base before continuing.

## 10. Direction invariants

This direction freezes the following durable boundaries:

```text
TARGET_VERSION=0.8.0
SEMVER_CLASS=MINOR
RELEASE_MODEL=MODEL_RELEASE_FIRST
CROSS_DAY_LABEL_IN_V080=false
TRADING_DAYS_LABEL_IN_V080=false
MINUTES_LABEL_IN_V080=false
QFQ_HFQ_ENABLEMENT_IN_V080=false
POST_V080_PRIORITY_1=CROSS_DAY_AND_TRADING_DAYS_LABEL_DESIGN
PYPI_PUBLICATION_DECISION=SEPARATE_EXPLICIT_GATE
TESTPYPI_PUBLICATION_DECISION=SEPARATE_EXPLICIT_GATE
WINDOWS_PRODUCTION_DEPLOYMENT_IS_GITHUB_RELEASE_ASSET=false
```

The Stage 2 source/package candidate version is `0.8.0`. This version identity
does not assert that the tag or formal GitHub Release exists.
