# MarketVault v0.9.0 Release Direction

Status: scope frozen on main; Stage 2 release-preparation candidate.

```text
V090_DIRECTION_BASE_SHA=d01bcf22f9b6d526cff90f3aceb7e3ef441a1a1e
V090_DIRECTION_BASE_TREE=a961df4fa31c722122c0e891d0bb89f60acbd21f
FORMAL_V080_RELEASE_SHA=90230ce1b55e63da0c583eaac8e94b64f6f4c2f9
CURRENT_PACKAGE_VERSION=0.9.0
TARGET_VERSION=0.9.0
SEMVER_CLASS=MINOR
RELEASE_MODEL=MODEL_RELEASE_FIRST
V090_SCOPE_FROZEN=true
RELEASE_PREPARATION_STAGE=STAGE_2_CANDIDATE
FORMAL_RELEASE_REQUIRES_SEPARATE_EXPLICIT_GATE=true
FORMAL_V090_RELEASED=false
```

This document freezes the intended v0.9.0 release boundary. The direction
base is the verified product mainline immediately before release preparation;
it is not the future release commit, tag, GitHub Release, or formal package
asset identity.

## 1. Release objective

v0.9.0 turns the post-v0.8 research foundations into a coherent local quant
research workflow:

```text
Verified market data
  -> PIT / Observation / Multi-Source / TS2
  -> Cross-Day Research Dataset
  -> Feature + Label research
  -> ML Dataset / Experiment metadata
  -> Walk-Forward
  -> Ridge selection / permanent TEST
  -> research Backtest / trading-threshold evaluation
  -> final immutable evaluation artifact
```

The release remains local-first, deterministic, explicit-input, and
fail-closed. It does not add broker execution or automatic live trading.

## 2. Frozen v0.9.0 product scope

### Research data authority

- Observation artifacts and PIT sidecars;
- Multi-Source Feature and Dataset authority;
- Cross-Day `TRADING_DAYS` Label execution and explicit verified schedule;
- TS2 Feature execution;
- immutable verified Multi-Source Cross-Day Dataset artifacts;
- Research Dataset Builder V1 and strict plan/CLI.

### Feature and Label libraries

Feature Library V1:

- SMA / EMA;
- RSI;
- MACD line / signal / histogram;
- ATR;
- OBV; and
- fixed 17-bar KDJ K / D / J.

Label Library V1:

- forward return 1/3/5/10 trading days;
- forward direction 1/3/5/10 trading days;
- maximum favorable/adverse excursion 1/3/5/10 trading days; and
- execution-safe future-open-to-horizon-close return 1/3/5/10 trading days.

### Backtest and ML research

- deterministic single-symbol Long/Flat Backtest Engine V1;
- explicit commission/slippage and non-overlapping trades;
- Backtest Plan + CLI V1;
- verified ML Dataset Adapter V1;
- Feature Research, Stability, and leakage-safe Selection;
- Experiment Metadata and leakage-safe Walk-Forward;
- deterministic Ridge regression baseline and validation alpha selection;
- permanent TEST evaluation;
- validation-only trading-threshold selection;
- fixed-zero and selected-threshold TEST trading evaluation;
- final Ridge comparison report;
- immutable final Ridge evaluation artifact and explicit Plan/CLI.

### CI

- `research_fast` targeted validation for the bounded research surface;
- no duplicate feature-branch push CI;
- stale PR runs cancelled by concurrency;
- unknown/shared/high-risk changes fail closed to FULL;
- main retains final FULL integration validation.

## 3. Compatibility and migration

```text
PUBLIC_API_CHANGE=BACKWARD_COMPATIBLE_ADDITIVE
RUNTIME_DEPENDENCY_CHANGE=false
REQUIRES_PYTHON_CHANGE=false

RAW_CURATED_ARTIFACT_REWRITE_REQUIRED=false
CANONICAL_ARTIFACT_MIGRATION_REQUIRED=false
LEGACY_DATASET_ARTIFACT_MIGRATION_REQUIRED=false
DATASET_CATALOG_ARTIFACT_MIGRATION_REQUIRED=false

TS2_ORIGINAL_EIGHT_PIN_BASELINE_PRESERVED=true
LEGACY_DATASET_IDENTITY_CHURN_FROM_UNUSED_FEATURES=false

QFQ_PIT_ALLOWED=false
HFQ_PIT_ALLOWED=false
AUTOMATIC_TRADING_INCLUDED=false
BROKER_EXECUTION_INCLUDED=false
```

v0.8.0 artifacts are never rewritten merely by installing or using v0.9.0.
The newer Cross-Day/Research artifact families are additive.

## 4. Release sequence

### STAGE_2: release preparation

The focused release-preparation candidate may contain only release-surface
changes:

- package version 0.8.0 -> 0.9.0;
- v0.9.0 CHANGELOG entry;
- README lifecycle/scope synchronization;
- v0.9.0 direction and release-preparation records;
- release checker / release regression updates; and
- fresh-wheel CI assertions and v0.9.0 release-prep markers.

No new product capability is authorized by this stage.

### STAGE_3: exact-main verification

After the release-preparation PR merges, the exact resulting main commit and
natural main push CI must be verified. Any product drift after that point
invalidates release authorization and requires a new release candidate.

### STAGE_4: immutable formal release gate

Only after a separate explicit formal-release authorization:

1. use a clean checkout at the exact verified release commit;
2. build one fresh wheel and one fresh sdist;
3. run `twine check` and fresh-wheel smoke validation;
4. generate `SHA256SUMS.txt`;
5. create an annotated `v0.9.0` tag at the exact release commit;
6. create a GitHub Release `MarketVault v0.9.0` with exactly the wheel,
   sdist, and `SHA256SUMS.txt`;
7. download and re-hash the published assets; and
8. record the immutable formal identities in the release record.

PyPI and TestPyPI remain separate explicit decisions.

## 5. Blocker rule

Any failure in release checker, FULL Python 3.11 tests, Python 3.14
compatibility, PyArrow 24 compatibility, package build/install, fresh-wheel
smoke, repository hygiene, or destructive-operation gates blocks formal
v0.9.0 release.
