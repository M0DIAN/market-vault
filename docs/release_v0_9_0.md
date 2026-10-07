# MarketVault v0.9.0 Release Notes

## Formal release status

The v0.9.0 release is formally released and sealed.

```text
V090_RELEASE_STATUS=FORMALLY_RELEASED_AND_SEALED
release commit: 5a796f0d4290b50291993dfcdfcacccb0c8dcb69
release tree: 62f051f0c5a59edf35e7ec3fa3d74206407b7773
main HEAD at release sealing: 5a796f0d4290b50291993dfcdfcacccb0c8dcb69
main CI: 37556656352
tag: v0.9.0
tag type: annotated
tag object: 029890e4d857e3db98e9ed104d9ec5dfe81c8ea0
peeled tag commit: 5a796f0d4290b50291993dfcdfcacccb0c8dcb69
GitHub Release: MarketVault v0.9.0
release ID: 405290783
publishedAt: 2026-10-07T01:46:35Z
draft: false
prerelease: false
latest: true
PyPI: NOT PUBLISHED
TestPyPI: NOT PUBLISHED
```

The annotated `v0.9.0` tag points at the release commit above. The formal
GitHub Release contains exactly the wheel, sdist, and `SHA256SUMS.txt` assets
sealed below.

```text
market_vault-0.9.0-py3-none-any.whl
SHA-256:
71de59c5170384a7f22115761077fd525d2190ff666108888950e081d33ccc99

market_vault-0.9.0.tar.gz
SHA-256:
0ae6f46144d66fdc85e0ecb96191bb6f68a90bdc16f3aea3eab908c09dc17ef5

SHA256SUMS.txt
SHA-256:
10f96d62ef0f55148e9e0948e926c5fb28f2b8ff1a1cc9d595f2f50fb7146d8d

Contents:
71de59c5170384a7f22115761077fd525d2190ff666108888950e081d33ccc99  market_vault-0.9.0-py3-none-any.whl
0ae6f46144d66fdc85e0ecb96191bb6f68a90bdc16f3aea3eab908c09dc17ef5  market_vault-0.9.0.tar.gz
```

### Main CI and formal gate

The authoritative post-merge main push CI was run `37556656352` at release
commit `5a796f0d4290b50291993dfcdfcacccb0c8dcb69` and completed successfully.
Formal assets were then rebuilt fresh from that exact release commit. The
draft Release assets were downloaded and verified byte-for-byte before
publication, and the published assets were downloaded again and reverified.

## Historical release-preparation record

Status: Stage 2 release-preparation candidate; formal release gate pending.

```text
V090_RELEASE_STATUS=RELEASE_PREPARATION_CANDIDATE
RELEASE_PREPARATION_BASE_SHA=d01bcf22f9b6d526cff90f3aceb7e3ef441a1a1e
RELEASE_PREPARATION_BASE_TREE=a961df4fa31c722122c0e891d0bb89f60acbd21f
FORMAL_V080_RELEASE_SHA=90230ce1b55e63da0c583eaac8e94b64f6f4c2f9
CANDIDATE_VERSION=0.9.0
TARGET_VERSION=0.9.0
SEMVER_CLASS=MINOR
RELEASE_MODEL=MODEL_RELEASE_FIRST
FORMAL_RELEASE_REQUIRES_SEPARATE_EXPLICIT_GATE=true
FORMAL_V090_RELEASED=false
PYPI_PUBLICATION_DECISION=SEPARATE_EXPLICIT_GATE
TESTPYPI_PUBLICATION_DECISION=SEPARATE_EXPLICIT_GATE
WINDOWS_PRODUCTION_DEPLOYMENT_IS_GITHUB_RELEASE_ASSET=false
```

This document is the Stage-2 candidate record. It deliberately contains no
future v0.9.0 release commit, annotated-tag object, GitHub Release ID,
publication timestamp, or formal asset SHA-256. Those identities can exist
only after this candidate merges, exact-main CI succeeds, and a separate
formal-release gate is authorized.

## 1. Candidate scope

### Verified research data pipeline

v0.9.0 adds the post-v0.8 research-data chain: Observation PIT,
Multi-Source Features/Datasets, TS2, Cross-Day `TRADING_DAYS` Labels,
Multi-Source Cross-Day Dataset artifacts, and the Research Dataset Builder
with explicit plan/CLI.

### Quant Feature Library V1

The fixed built-in research Feature surface includes:

- SMA / EMA;
- RSI;
- MACD line / signal / histogram;
- ATR;
- OBV; and
- KDJ K / D / J with fixed 17-bar semantics.

The original eight TS2 implementation pins remain the compatibility baseline.
Extension pins participate in an execution identity only when their Features
are actually requested.

### Label Library and execution-safe PnL

The research Label library provides 1/3/5/10 trading-day presets for forward
return, direction, MFE, MAE, and execution-safe future-open-to-horizon-close
return.

The execution-safe return prevents research Backtest PnL from assuming a fill
at a close that was already consumed to form the signal.

### Backtest

Backtest Engine V1 is deterministic, single-symbol, Long/Flat and
full-notional. It supports explicit commission/slippage, non-overlapping
trades, split-aware execution, deterministic identities, and a strict
settings-independent Plan/CLI.

It is a research engine only; it does not place live orders.

### ML and research evaluation

v0.9.0 includes:

- verified ML Dataset Adapter;
- Feature Research, Stability and Selection;
- Experiment Metadata;
- leakage-safe Walk-Forward;
- deterministic Ridge regression;
- validation-only alpha selection;
- permanent TEST evaluation;
- validation-only trading-threshold selection;
- fixed-zero and selected-threshold TEST trading evaluation;
- final Ridge comparison; and
- immutable final Ridge evaluation artifact plus Plan/CLI.

TEST remains outside model/threshold selection authority.

## 2. Compatibility and migration

```text
PUBLIC_API_CHANGE=BACKWARD_COMPATIBLE_ADDITIVE
RUNTIME_DEPENDENCY_CHANGE=false
REQUIRES_PYTHON=>=3.11

RAW_CURATED_ARTIFACT_REWRITE_REQUIRED=false
CANONICAL_ARTIFACT_MIGRATION_REQUIRED=false
LEGACY_DATASET_ARTIFACT_MIGRATION_REQUIRED=false
DATASET_CATALOG_ARTIFACT_MIGRATION_REQUIRED=false

TS2_ORIGINAL_EIGHT_PIN_BASELINE_PRESERVED=true
QFQ_PIT_ALLOWED=false
HFQ_PIT_ALLOWED=false
AUTOMATIC_TRADING_INCLUDED=false
BROKER_EXECUTION_INCLUDED=false
```

The formal v0.8.0 release remains immutable. Its release commit, tag, assets,
and release record are not changed by v0.9.0 preparation.

## 3. Release-preparation validation contract

Before merge, the candidate must pass:

- version consistency across `pyproject.toml`, runtime `__version__`, CLI,
  and installed wheel metadata;
- `scripts/check_release.py`;
- dedicated v0.9.0 release-preparation regressions;
- repository hygiene and destructive-operation design gate;
- Python 3.11 FULL tests;
- audited Python 3.14 compatibility surface;
- audited PyArrow 24 compatibility surface;
- fresh wheel/sdist build and `twine check`;
- fresh-wheel CLI/import/research-surface smoke; and
- SHA-256 package-manifest generation.

Candidate CI artifacts and hashes are validation evidence only. They are not
formal release asset identities.

## 4. Formal release gate pending at preparation time

At preparation time, formal v0.9.0 release required a future explicit gate
after the candidate merged and exact-main CI succeeded. That gate had to
create a fresh build from the exact release commit, create the annotated
`v0.9.0` tag, publish exactly one wheel, one sdist, and `SHA256SUMS.txt`, and
verify the downloaded published assets byte-for-byte. The Formal release
status section above records the completed gate.

At that preparation time:

```text
V090_TAG_CREATED=false
V090_GITHUB_RELEASE_PUBLISHED=false
FORMAL_V090_RELEASED=false
CURRENT_FORMAL_RELEASE=v0.8.0
```

## 5. Known boundaries

- adjusted-price PIT remains NONE-only; no QFQ/HFQ corporate-action authority;
- Backtest V1 is not an order-book, margin, shorting, or portfolio simulator;
- research Ridge is not a general-purpose ML/MLOps framework;
- no live broker execution or automatic trading;
- no REST/cloud/distributed execution; and
- no live microstructure reconstruction for data that was never captured.
