# MarketVault v0.6.1 Direction: Stability, Auditability, and Usability Maintenance

Status: planned maintenance release

This document defines the scope, non-goals, and fixed PR sequence for the
V0.6.1 "Stability, Auditability, and Usability Maintenance" patch release.
V0.6.1 is a maintenance release: it adds no new product capability and
changes no formal identity, schema, contract, or CLI behavior. V0.6.1
maintenance development is in PR-2; the direction PR (PR-1) was
documentation and process only and implemented no product code.
PR-1 is complete and merged as PR #44 at
6bb9a9500fae53511ff964f47e5ccea20f3d91f7.
PR-2 is the current CLI/help/error/usability consistency-polish stage.
V0.6.1 is not released.
PR-3 has not started.
The fixed PR sequence remains unchanged.

## 1. Baseline

```text
base version: v0.6.0
release commit: 669c955abc0a234264964dfdb7fcafdf502a901a
tag: v0.6.0
package version at planning time: 0.6.0
```

- The v0.6.0 minor feature release is formally released and sealed (PR
  #43 MERGED on 2026-08-07T23:41:36Z at the release commit
  `669c955abc0a234264964dfdb7fcafdf502a901a`, the annotated `v0.6.0` tag
  created, and the GitHub Release `MarketVault v0.6.0` published on
  2026-08-08T03:17:48Z with the wheel and sdist assets; PyPI and TestPyPI
  are not published).
- V0.6.1 is a maintenance patch. It does not change any identity
  algorithm, schema, contract, or CLI behavior.
- The package version stays 0.6.0 through PR-3 and is bumped to 0.6.1 only
  in PR-4 (the final release-preparation PR).

## 2. V0.6.1 goals

V0.6.1 is a maintenance release. It does not add any new product
capability. The fixed goals are exactly:

1. **Post-release documentation / lifecycle truth** — keep the
   repository-facing release and direction documentation aligned with the
   formal released v0.6.0 state, and record the v0.6.1 maintenance
   direction.
2. **CLI / help / error wording consistency and usability polish** —
   consistent help wording, error wording, terminology, and stdout/stderr
   behavior, plus obvious usability polish and docs/examples polish.
3. **CI / package auditability** — package and release auditability
   hardening.
4. **Maintenance regression hardening** — the existing frozen regression
   suites stay green across the maintenance window.
5. **Final v0.6.1 release preparation** — version sync, README, CHANGELOG,
   release notes, release checker / release tests / CI package assertions,
   and the tag and GitHub Release after explicit authorization.

## 3. V0.6.1 explicit non-goals

V0.6.1 does not implement any of the following; none is part of v0.6.1:

- Python Client
- REST API
- Dataset Catalog query command (`dataset-catalog-query`)
- new Catalog capability
- new Sample Generation capability
- identity v2
- schema v2
- new artifact format
- dependency modernization
- PyArrow runtime pin
- ML training
- backtesting
- signals
- automatic trading
- Trading Execution

None of these may be smuggled into any v0.6.1 PR.

## 4. V0.6.1 invariants

V0.6.1 freezes the following invariants:

```text
Canonical identity algorithms unchanged
Dataset identity algorithms unchanged
Sample Generation identity unchanged
Catalog content identity unchanged
Catalog snapshot identity unchanged
Dataset build-plan contract unchanged
Sample Generation contract unchanged
Catalog formal contract unchanged
existing immutable artifacts require no migration/rewrite
CLI command set unchanged
```

## 5. Fixed PR sequence

```text
PR-1 — Post-release baseline + maintenance direction

PR-2 — CLI/help/error/usability consistency polish

PR-3 — CI/package auditability + maintenance hardening

PR-4 — v0.6.1 release preparation
```

Then a separate release action.

Each PR is independent:

- one PR completes exactly one stage;
- a PR never starts the next stage as a side effect;
- PR-1 does not implement any PR-2/PR-3 content;
- PR-2 does not implement any PR-3 content;
- PR-3 does not implement the release preparation;
- the version is bumped to 0.6.1 only in PR-4.

### Version rules

```text
PR-1: 0.6.0
PR-2: 0.6.0
PR-3: 0.6.0
PR-4: 0.6.0 -> 0.6.1
```

The package version stays 0.6.0 through PR-3 and is bumped to 0.6.1 only
in PR-4. Early version bumps are forbidden.

## 6. PR-2 boundary

PR-2 may change:

- help wording
- error wording
- terminology consistency
- stdout/stderr consistency
- obvious UX polish
- docs/examples polish

PR-2 must not change:

- command names
- business arguments
- defaults
- exit-code semantics
- JSON schemas
- identity inputs
- output artifact format
- read/write behavior

If the PR-2 audit finds a fix that necessarily changes formal behavior,
PR-2 must stop and report separately; it must not expand the maintenance
scope on its own.

## 7. PR-3 boundary

PR-3 targets package / release auditability. Candidate content:

- rename the stale PyArrow24 CI wording from "writer" to the audited
  PyArrow 24.0.0 compatibility runtime;
- build a SHA256 manifest;
- preserve the wheel/sdist as GitHub Actions workflow artifacts;
- allow a later independent download / hash audit.

PR-1 does not implement these; PR-3 implements them.

PR-3 must not change:

- the normal CI matrix: 3.11 + 3.14 EXACT
- portability-pyarrow24: KEEP
- full pytest under pyarrow 24: KEEP

## 8. PR-4 boundary

Only PR-4 may:

- bump the version 0.6.0 -> 0.6.1;
- update README, CHANGELOG, the release checker, the release notes, and
  the CI package version assertions.

The formal tag and GitHub Release are still created only after PR-4 is
merged, the main push CI succeeds, and explicit authorization is given.

## 9. Acceptance principles

V0.6.1 keeps, unchanged:

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
