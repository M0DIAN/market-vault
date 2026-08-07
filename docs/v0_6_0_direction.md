# MarketVault v0.6.0 Direction: Deterministic Sample Generation and Dataset Catalog

Status: planned

This document defines the scope, non-goals, and fixed PR sequence for the
V0.6.0 "Deterministic Sample Generation and Dataset Catalog" minor feature
release. It fixes the architecture boundary for v0.6.0 and the two product
capabilities: the Deterministic Sample Generator and the immutable Dataset
Catalog. The direction PR itself is documentation only and implements no
product code; the precise schemas are defined by the subsequent contract
PRs, and the Catalog query CLI (PR-7) has not started.

## 1. Baseline

```text
base version: v0.5.1
base commit: a978eef291d5e26d20e5cf977bc76609c227cb52
package version at planning time: 0.5.1
```

- The v0.5.1 maintenance release is formally released and sealed (GitHub
  PR #33 merged, the annotated `v0.5.1` tag created, and the GitHub Release
  `MarketVault v0.5.1` published with the wheel and sdist assets; PyPI is
  not published).
- V0.6.0 is a minor feature release. It does not modify the existing
  Dataset or Canonical identity algorithms.
- V0.6.0 does not rewrite any existing artifacts and does not change the
  existing `dataset-build` formal contract
  (`market-vault-dataset-build-plan-v1`).
- The package version stays 0.5.1 through PR-8 and is bumped to 0.6.0 only
  in PR-9 (the final release-preparation PR).

## 2. V0.6.0 goals

V0.6.0 contains exactly two product capabilities.

### A. Deterministic Sample Generator

Responsibility:

```text
verified Canonical builds
+ explicit generation plan
+ explicit scope
+ explicit window / stride rules
+ explicit Dataset build facts
→ deterministic PITSampleRequest sequence
→ ordinary market-vault-dataset-build-plan-v1
```

The generator must:

- generate only requests and an ordinary Dataset build-plan;
- never compute Feature values;
- never compute Label values;
- never build a Dataset;
- never train a model;
- never modify Canonical;
- produce output that can be handed directly to the existing
  `market-vault dataset-build --plan <PATH>` command;
- neither upgrade nor replace the current
  `market-vault-dataset-build-plan-v1`;
- not add a second implicit input set for `dataset-build`;
- keep every input explicit;
- never read the current time;
- never scan for `latest`;
- never connect to OpenD automatically;
- never access the network;
- never load settings;
- never automatically collect or repair data;
- never generate cross-trading-day Labels;
- keep the v1 boundary that only `adjustment = NONE` is supported;
- restrict the v1 generation rules to the currently formally supported
  BARS-style research boundary;
- produce a byte-identical request order and build-plan content for the
  same verified inputs and the same generation plan;
- construct every request as a formal `PITSampleRequest` and pass its
  validation;
- sort the output requests by a stable key and reject duplicates.

This direction only fixes the boundary; PR-1 does not determine all JSON
fields. The precise schema is defined by PR-2.

### B. Immutable Dataset Catalog

Responsibility:

```text
explicit Dataset root / explicit candidate set
→ load_verified_dataset for every candidate
→ extract verified metadata
→ deterministic immutable Catalog snapshot
→ verified Catalog reader
→ read-only discovery and query
```

The new Dataset Catalog must:

- be fully independent of the existing
  `market_vault.storage.catalog.Catalog`;
- leave the legacy Catalog responsible for ingestion runs, quality,
  snapshot views, and DuckDB views;
- index only formal immutable Dataset builds;
- admit a build into the Catalog only when it passes
  `load_verified_dataset`;
- never trust an unverified manifest directly;
- never repair a Dataset;
- never rewrite a Dataset;
- never delete a Dataset;
- never auto-select `latest`;
- never scan the whole disk; the scan scope must be bounded by an explicit
  root or an explicit candidate set;
- have queries read an explicit Catalog snapshot;
- never allow a Catalog snapshot to be overwritten;
- produce the same Catalog content identity for the same verified Dataset
  set;
- never let paths, machine names, or the current time pollute Dataset
  identity;
- never let Catalog identity flow back into Dataset identity;
- not modify an original Dataset when it is moved or re-indexed;
- fail closed on invalid, corrupted, conflicting, or symlink /
  reparse-point candidates;
- keep discovery and query strictly read-only.

**Catalog content identity.** Catalog content identity is determined only
by the normalized set of verified Dataset facts under the versioned
Catalog contract. `built_at`, the Catalog `output_root`, the Catalog
snapshot path, Dataset build paths / location metadata, the machine name,
host-specific filesystem representation, the current time, scan order,
and candidate input order never enter Catalog content identity. The same
verified Dataset facts under the same Catalog contract version always
produce the same Catalog content identity, even when the Dataset or the
Catalog snapshot is moved to another directory.

**Materialization / snapshot metadata.** `built_at`, the output directory,
and location metadata may be recorded as non-content metadata, or PR-5 may
define a separate materialization or snapshot identity. They never enter
Catalog content identity, never enter any Dataset identity, never change
an indexed Dataset, and never make the same Dataset set produce a
different content identity merely because the directory changed.

The precise Catalog schema, identity, and physical layout are defined by
the subsequent PRs.

## 3. CLI direction

The following command names are reserved as v0.6.0 planning targets; they
are not implemented in the current PR:

```text
market-vault sample-generate
market-vault dataset-catalog-build
market-vault dataset-catalog-verify
market-vault dataset-catalog-list
market-vault dataset-catalog-show
```

- The command names are v0.6.0 planning goals; the commands do not exist
  in the current PR.
- Subsequent contract PRs may finalize the parameters without changing the
  responsibility boundaries.
- These commands must not be confused with the existing `init-catalog`
  command; `init-catalog` remains the legacy ingestion DuckDB catalog
  command (`market_vault.storage.catalog.Catalog`).

## 4. Relationship to future projects

The adopted three-project boundary:

```text
MarketVault
→ trusted data, Canonical, Feature/Label, Dataset,
  Sample Generator, Dataset Catalog, future Python Client

Future Quant Research repository
→ experiment management, training, evaluation, prediction,
  research backtests

Future Trading Execution repository
→ signal consumption, risk management, paper trading,
  order and live execution
```

- The Quant Research repository does not exist yet and has not been
  created.
- The Trading Execution repository does not exist yet and has not been
  created.
- The project names are not yet final.
- V0.6.0 does not create any new repository.
- V0.6.0 does not implement research or trading functionality.

## 5. V0.6.0 explicit non-goals

The following are explicit v0.6.0 non-goals; none is implemented:

- Python Client — fixed as a later v0.7 direction; it is not part of v0.6
- REST API
- ML Experiment
- Experiment Runner
- model training
- hyperparameter tuning
- feature importance
- Model Registry
- prediction service
- backtesting
- walk-forward
- signal
- position sizing
- risk engine
- paper trading
- live execution
- broker order API
- real-time subscription
- automatic trading
- arbitrary user transforms
- adjusted-price PIT
- cross-trading-day Label
- TRADING_DAYS Label execution
- Dataset identity algorithm changes
- Canonical identity algorithm changes
- schema migration
- dependency modernization
- PyPI publication

Python Client is fixed as a later v0.7 direction and is not part of v0.6.

## 6. Fixed PR sequence

```text
PR-1 — post-release alignment, v0.6.0 direction, architecture boundary

PR-2 — Sample Generation contract, strict schema, frozen models,
       normalization and content identity

PR-3 — deterministic Sample Generator core over verified Canonical builds

PR-4 — Sample Generator CLI, ordinary build-plan output,
       COMPLETE / EMPTY / determinism E2E

PR-5 — Dataset Catalog contract, strict schema, frozen models,
       metadata projection and Catalog identity

PR-6 — immutable Dataset Catalog builder, materializer,
       verified Catalog reader

PR-7 — Dataset Catalog verify/list/show/query CLI

PR-8 — integrated determinism, corruption, recovery, portability,
       security and usability E2E documentation

PR-9 — v0.6.0 release preparation
```

Each PR is independent:

- one PR completes exactly one stage;
- a PR never starts the next stage as a side effect;
- PR-2 does not implement the engine;
- PR-3 does not implement the CLI;
- PR-4 does not implement the Catalog;
- PR-5 does not implement Catalog writes;
- PR-6 does not implement the Query CLI;
- PR-7 does not implement the Python Client;
- PR-8 does not expand the product scope;
- the version is bumped to 0.6.0 only in PR-9.

## 7. Acceptance principles

V0.6.0 keeps, unchanged:

- Python 3.11
- Python 3.14
- offline deterministic tests
- fail closed
- no current time
- no hidden latest
- no network / OpenD / settings
- targeted -> related -> full pytest -> CI
- one PR at a time
- immutable artifacts
- verified readers as trust boundaries
- clean worktree
- package smoke
- public API smoke
- wheel hygiene
- no unrequested merge

## 8. Progress

- PR #34 (`docs: define v0.6.0 sample and catalog direction`) was merged
  on 2026-08-05T22:50:10Z via the squash commit
  `6bc03d76078c8355322e65d6ca05cc986b4dbe23`; the v0.6.0 direction, the
  three-project boundary ADR, and the two boundary contracts are now on
  main.
- PR #35 (`feat: define deterministic sample generation contract`) was
  merged on 2026-08-06T00:37:13Z via the squash commit
  `0f66c61407c8ba4f122ad1e5d0463ab2f8f66883`; the Sample Generation
  contract foundation (strict schema, frozen models, normalization,
  canonical serialization, semantic content identity) is on main.
- PR #36 (`feat: implement deterministic sample generator core`) was
  merged on 2026-08-06T06:59:35Z via the squash commit
  `4d5124fa1f1c30db5dcc5b8bb72c7e4f04f1109c`; the deterministic Sample
  Generator core is complete: the verified input chain, the BARS
  window-coverage preflight, the contiguous-segment traversal, the
  stride-based candidate anchors, the exact half-open window geometry, the
  duplicate rejection, the Generation content identity, and the frozen
  `SampleGenerationResult`. PR-3 is complete.
- PR #37 (`feat: add deterministic sample generation CLI`) was merged on
  2026-08-06T23:23:50Z via the squash commit
  `ca486a19e6795940f21a9a22053fc59175510d91`; PR-4 is complete: the Sample
  Generation CLI (`market-vault sample-generate --plan`), the pure
  ordinary `market-vault-dataset-build-plan-v1` renderer, the shared
  split-spec loading authority, the safe / idempotent no-overwrite output
  materialization, and the COMPLETE / EMPTY / determinism end-to-end
  proof. PR #38 (`fix: read canonical parquet files without partition
  inference`) was also merged on 2026-08-07T03:10:49Z via the squash
  commit `b4c3618d631b2950934acbae4a72e00b2adf7350`; it is a standalone
  verified-reader fix outside the fixed v0.6.0 PR sequence.
- PR-5 merged (GitHub PR #39, `feat: define Dataset Catalog contract,
  frozen models, projection and Catalog identity`) on
  2026-08-07T08:54:32Z via the squash commit
  `2958697dd434c536c39267b6a654dabb762c74f9`; PR-5 is complete: the
  Dataset Catalog contract, strict entry schema, frozen models, the
  metadata projection, and the Catalog content identity are on main.
- PR-6 (this PR, branch `feat/v0.6.0-dataset-catalog-snapshot`) is the
  current implementation stage: the immutable Dataset Catalog builder
  (explicit Dataset root / explicit candidate set), the snapshot
  materializer (catalog.json / manifest.json / _SUCCESS, staging,
  _SUCCESS written last, atomic no-replace publication, existing-snapshot
  idempotency), and the verified Catalog snapshot reader (historical
  recorded build locations, never reloaded). PR-7 (Dataset Catalog verify/list/show/query CLI) has not started; the Catalog query CLI is
  not implemented.
- The package version remains 0.5.1; the bump to 0.6.0 happens only in
  PR-9. V0.6.0 as a whole is not released.
