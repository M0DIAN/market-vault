# MarketVault v0.5.1 Direction: Stability and Usability Maintenance

Status: implementation complete; v0.5.1 release preparation

This document defines the scope, non-goals, and PR sequence for the V0.5.1
"Stability and Usability Maintenance" patch release. It is the single
maintenance direction for everything after the v0.5.0 release; v0.6 has not
started and is not planned in this document.

## 1. Baseline

```text
base version: v0.5.0
base commit: 3b4d03c785123e204885faea08df7b9d7ed07ec0
package version at planning time: 0.5.0
```

- The v0.5.0 Deterministic Dataset Builder is formally released: PR #29
  merged, the annotated `v0.5.0` tag created, and the GitHub Release
  `MarketVault v0.5.0` published with the wheel and sdist assets; PyPI is
  not published.
- V0.5.1 is a maintenance patch. It does not change Dataset identity,
  Canonical identity, or any existing public contract.
- V0.5.1 does not move into Sample Generator, Dataset Catalog, Python
  Client, or ML Experiment work.

## 2. V0.5.1 goals

V0.5.1 contains exactly three categories of work.

### A. Compatibility and warning cleanup

- Clean up the pandas / NumPy deprecation warnings produced by MarketVault's
  own source and tests.
- Prioritize the warnings exposed by the Python 3.14 CI jobs.
- Keep time semantics, Dataset content, identity, and output byte contracts
  unchanged.
- Forbidden: pretending success by globally ignoring warnings, filtering all
  DeprecationWarnings, or disabling pytest warning reporting.
- Third-party library warnings are classified separately; they are never
  reported as "fixed by MarketVault".

### B. Dataset CLI usability

- Provide reproducible Dataset build-plan examples.
- Provide FeatureSpec, LabelSpec, and ChronologicalSplitSpec examples.
- Provide a complete Windows PowerShell usage flow.
- Provide minimal offline COMPLETE and EMPTY examples.
- Document common errors.
- Examples must use the existing formal CLI and schema only.
- No Sample Generator; no automatic `latest` scanning; no automatic Canonical
  discovery; no implicit defaults; the fail-closed boundaries are not
  relaxed.

### C. Maintenance release

- V0.5.1 version sync.
- CHANGELOG.
- Release notes.
- Release checker / release tests / package smoke.
- Tag and GitHub Release.
- PyPI publication remains a separate, explicit decision.

## 3. Explicit non-goals

V0.5.1 does not implement any of the following; each remains a future
direction outside this maintenance release:

- Sample Generator
- Dataset Catalog
- Python Client
- REST API
- ML training
- Experiment Runner
- Model Registry
- backtest
- signal
- automatic trading
- adjusted-price PIT
- cross-trading-day Label
- TRADING_DAYS Label execution
- arbitrary user transforms
- identity algorithm changes
- dependency modernization
- large refactor

## 4. Proposed PR sequence

The sequence is fixed:

```text
PR-1 — post-release state alignment and v0.5.1 direction
PR-2 — pandas/NumPy deprecation compatibility cleanup
PR-3 — Dataset CLI examples and usability documentation
PR-4 — v0.5.1 release preparation
```

Each PR is independent: one PR implements one stage only and does not start
the next PR. PR-2 does not modify documentation examples; PR-3 does not
change production behavior; PR-4 adds no new feature. The version is bumped
to 0.5.1 only in PR-4.

## 5. Acceptance principles

The v0.5.1 release must keep, unchanged:

- Python 3.11 support
- Python 3.14 support
- offline deterministic tests
- one PR at a time
- targeted -> related -> full pytest -> CI verification
- a clean worktree
- the release checker
- the package smoke
- the public API smoke
- wheel contents hygiene
- no unrequested merge

## 6. Progress

- **PR-1** (`docs: define v0.5.1 maintenance direction`) — merged (GitHub
  PR #30, squash merge commit
  `8de57d497ae5d922e3df29d9475f14b9407865f0`): post-release state alignment
  of the v0.5.0 direction and release notes, this direction document, and
  the release checker / release tests switched to verifying the released
  state.
- **PR-2** (`fix: remove NumPy timedelta deprecation warnings`) — merged
  (GitHub PR #31, squash merge commit
  `2d9c8a539f04ee2d75e5482c858ec6c3364af135`): explicit-unit
  `pd.Timedelta` construction in production and tests, the precise
  warning-as-error pytest guard, and the
  `tests/test_deprecation_compatibility_v051.py` regression suite.
- **PR-3** (`docs: add verified Dataset CLI examples`) — merged (GitHub
  PR #32, squash merge commit
  `240f7ccac89a773366a510f10a13d6de801051ea`): verified FeatureSpec /
  LabelSpec / split-spec examples, COMPLETE and EMPTY build-plan templates,
  the stdlib-only `examples/dataset_cli/render_plans.py` renderer, the
  Windows PowerShell usage flow, common-error documentation, example
  regression tests, and the renderer hardening follow-up
  (`1f48efde963a5aee2b9bf55fd093db677e296abe`).
- **PR-4** (`chore: prepare v0.5.1 release`) — in progress on the
  `release/v0.5.1` branch: version sync to **0.5.1**, README, CHANGELOG,
  release notes, direction document, release checker, release tests, and
  CI package updates.
- The package version is now **0.5.1**; no dependency changes.
- The `v0.5.1` tag has not been created; no GitHub Release exists; PyPI is
  not published.
- Sample Generator, Dataset Catalog, Python Client, and ML Experiment have not started.
