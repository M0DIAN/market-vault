# MarketVault v0.9.0 Release Notes

## Release-preparation status

Status: release-preparation candidate; formal release gate pending.

```text
V090_RELEASE_STATUS=RELEASE_PREPARATION_CANDIDATE
RELEASE_PREPARATION_BASE_SHA=d01bcf22f9b6d526cff90f3aceb7e3ef441a1a1e
RELEASE_PREPARATION_BASE_TREE=a961df4fa31c722122c0e891d0bb89f60acbd21f
CANDIDATE_VERSION=0.9.0
CURRENT_FORMAL_RELEASE=v0.8.0
SEMVER_CLASS=MINOR
V090_SCOPE_FROZEN=true
FORMAL_RELEASE_REQUIRES_SEPARATE_EXPLICIT_GATE=true
PyPI: NOT PUBLISHED
TestPyPI: NOT PUBLISHED
```

This document describes the v0.9.0 release candidate. It deliberately does
not contain a future release commit, annotated tag object, GitHub Release ID,
publication timestamp, or formal package-asset hashes. Those facts can exist
only after the candidate is merged, exact main is verified, and a separate
formal-release action is authorized.

## 1. Research Dataset pipeline

v0.9.0 turns the post-v0.8 research work into a usable deterministic pipeline:

- high-level Research Dataset Builder over verified PIT, TS2, Observation,
  Multi-Source and Cross-Day authorities;
- strict versioned Research Build Plan and `research-build` CLI;
- PIT-safe Cross-Day `TRADING_DAYS` labels and immutable Cross-Day Dataset
  artifacts/readers;
- stable TS2 implementation identity: the original compatibility baseline
  remains stable and extension Feature pins enter an execution identity only
  when those Features are actually used.

No input is selected through a hidden `latest` pointer.

## 2. Quant Feature Library V1

The built-in deterministic research Feature set now includes:

- SMA and window-local EMA;
- RSI;
- MACD line, signal and histogram;
- ATR and OBV;
- fixed KDJ K/D/J.

Every added Feature is PIT-safe and uses an explicit bounded input window.
Recursive indicators use deterministic in-window seeds rather than hidden
pre-window state.

## 3. Research Label Library V1

Standard research Label presets include 1/3/5/10 trading-day forms of:

- forward return;
- forward direction;
- maximum favorable excursion (MFE);
- maximum adverse excursion (MAE);
- execution-safe forward open-to-close return.

The execution-safe return family enters at the first future same-slot bar open
and exits at the requested future same-slot close. It is the PnL authority for
the v0.9.0 backtest/Ridge trading path and avoids assuming a fill at an already
observed Feature close.

## 4. Backtest Engine V1

v0.9.0 adds a deterministic single-symbol Long/Flat research backtest:

- Feature-threshold signals;
- explicit TRAIN / VALIDATION / TEST split selection;
- non-overlapping full-notional trades;
- fixed per-side commission and slippage;
- execution-safe return Labels only;
- deterministic backtest identity;
- gross/net return, realized trade-close drawdown, win rate, profit factor,
  holding-time and exposure metrics;
- explicit `research-backtest --plan ...` CLI.

This is offline research evaluation. It does not submit broker orders or run
automatic/live trading.

## 5. ML Dataset and Feature research

The new research layer provides:

- verified ML Dataset Adapter with immutable chronological TRAIN / VALIDATION /
  TEST projections;
- explicit Feature subsets and one selected Label;
- detached pandas convenience views without making DataFrames identity
  authority;
- Feature Research reports;
- Feature Stability analysis;
- leakage-safe Feature Selection;
- explicit experiment metadata.

The adapter does not shuffle, impute, fit models, or invent a second split.

## 6. Walk-Forward and Ridge research

The v0.9.0 Ridge pipeline is an offline deterministic baseline workflow:

- Walk-Forward TRAIN/VALIDATION experiments;
- Ridge regression baseline and Plan/CLI;
- validation-only Ridge alpha selection;
- one frozen permanent TEST model/evaluation;
- fixed-zero TEST trading evaluation;
- validation-only trading-threshold selection;
- application of that already-selected threshold to permanent TEST;
- read-only final comparison between the fixed-zero and
  validation-selected-threshold TEST policies.

Permanent TEST is reporting only. The final evaluation API has no winner,
decision, recommendation, or TEST-stage threshold/model selection.

## 7. Final evaluation artifact

The frozen final Ridge evaluation can be serialized as one lightweight
canonical JSON artifact:

- the existing `report_id` remains the sole semantic report identity;
- duplicate keys and unexpected fields are rejected;
- the report identity is reconstructed/revalidated on every read;
- writing uses one explicit file path, exclusive create, byte-identical reuse,
  strict read-back and content SHA-256;
- `research-ridge-final-evaluation-artifact --plan ...` composes the frozen
  evaluation pipeline once and writes that unchanged report.

This artifact is intentionally not a return to the removed heavy
artifact/governance stack.

## 8. CLI research workflow

The principal v0.9.0 research commands are:

```text
research-build
research-backtest
research-feature-report
research-feature-stability
research-feature-select
research-walk-forward
research-ridge
research-ridge-final
research-ridge-final-trading
research-ridge-trading-select
research-ridge-selected-final-trading
research-ridge-final-evaluation
research-ridge-final-evaluation-artifact
```

All research commands are settings-independent and use explicit input paths.
They do not connect to OpenD or discover a latest artifact while performing
offline research.

## 9. CI development acceleration

Research development uses an explicit bounded `research_fast` PR tier with:

- fixed Python 3.11/3.14 focused regressions;
- downstream Dataset identity/artifact regressions;
- no duplicate feature-branch push CI;
- cancellation of stale PR runs.

Unknown/shared/high-risk paths fail closed to FULL. Main integration still
receives FULL validation or verified post-merge FULL reuse.

## 10. Compatibility and migration

```text
PUBLIC_PYTHON_API=BACKWARD_COMPATIBLE_ADDITIVE
ARTIFACTCLIENT_BUSINESS_METHOD_COUNT=4

CANONICAL_ARTIFACT_MIGRATION_REQUIRED=false
LEGACY_DATASET_ARTIFACT_MIGRATION_REQUIRED=false
DATASET_CATALOG_ARTIFACT_MIGRATION_REQUIRED=false
RAW_CURATED_ARTIFACT_REWRITE_REQUIRED=false

RESEARCH_ARTIFACTS=NEW_VERSIONED_CAPABILITIES
LEGACY_TS2_EXECUTION_IDENTITIES_PRESERVED=true

RUNTIME_DEPENDENCY_SET_CHANGED=false
QFQ_PIT_ALLOWED=false
HFQ_PIT_ALLOWED=false
```

The existing four `ArtifactClient` business methods remain unchanged.
v0.8.0 Canonical, legacy Dataset, Dataset Catalog and Raw/Curated artifacts
are not rewritten or migrated by installing v0.9.0. The new Cross-Day,
research, experiment and final-evaluation records are additive versioned
capabilities.

## 11. Known boundaries

- Adjusted-price PIT remains NONE-only; QFQ/HFQ research PIT is not enabled.
- Backtest V1 is single-symbol Long/Flat and reports realized trade-close
  drawdown, not a full intraholding mark-to-market equity curve.
- Ridge is a research baseline, not a general model zoo or model-serving
  platform.
- No live order routing, broker execution, automatic trading, MLOps, REST
  research service, distributed backtest cluster, or GPU training platform is
  part of v0.9.0.
- Historical microstructure fields cannot be reconstructed when they were not
  captured live.
- The Windows production executable remains a separate deployment lifecycle
  from the formal source-package GitHub Release assets.

## 12. Formal release gate

Before v0.9.0 is called formally released:

1. the release-preparation candidate must merge;
2. exact main must pass the required CI/package gates;
3. formal release assets must be built fresh from the exact release commit;
4. asset SHA-256 values must be verified;
5. an annotated `v0.9.0` tag and GitHub Release require a separate explicit
   release action;
6. this document must then be updated with only the identities actually
   observed during that formal release.

Until then, v0.8.0 remains the current formal release.
