# MarketVault v0.7.0 Direction: Python Client and Read-only Artifact Access

Status: active feature development; PR-2 ArtifactClient foundation stage

Baseline:

```text
base version: v0.6.1
release commit: 37614d539171ef7b738e47415f3cd6ca2de332d1
tag: v0.6.1
GitHub Release: MarketVault v0.6.1
package version at planning time: 0.6.1
```

Progress / current state:

```text
PR-1: COMPLETE / MERGED / MAIN VERIFIED
PR-2: CURRENT
PR-3: NOT STARTED
PR-4: NOT STARTED
PR-5: NOT STARTED
PR-6: NOT STARTED
package: 0.6.1
v0.7.0: NOT RELEASED
```

PR-1 record:

```text
PR #48 merged at 2026-08-08T23:50:24Z
squash/main: bad62ee51e8eda03c7c5f20ac858973923e5f93d
main CI: 31284875166 SUCCESS
package: 0.6.1
```

This document defines the scope, non-goals, and fixed PR sequence for the
V0.7.0 "Python Client and Read-only Artifact Access" feature release.
V0.7.0 delivers a settings-independent Python artifact client that serves
verified immutable artifacts through the existing formal verified
readers. PR-1 established the post-v0.6.1 release baseline, the existing
Python API audit (`docs/v0_7_0_python_api_audit.md`), and the Python
Client boundary contract (`docs/contracts/python_client.md`). PR-2
implements the settings-independent `ArtifactClient` foundation.

## 1. Goals

The fixed goals are exactly:

1. Post-v0.6.1 lifecycle truth and baseline.
2. Existing Python API compatibility audit.
3. Settings-independent Python artifact client.
4. Read-only verified Canonical and Dataset access.
5. Read-only verified Dataset Catalog access.
6. Integrated Python/Jupyter/ML-consumer usability without implementing
   ML itself.

## 2. Fixed PR sequence

The strict 6-PR sequence:

```text
PR-1 — Post-v0.6.1 release baseline
       + existing Python API audit
       + Python Client contract/direction

PR-2 — Settings-independent ArtifactClient foundation

PR-3 — Canonical + Dataset verified read-only client access

PR-4 — Dataset Catalog verified read-only client access

PR-5 — Integrated E2E
       + usability
       + Python/Jupyter/ML-consumer examples
       + compatibility hardening

PR-6 — v0.7.0 release preparation
```

Then a separate explicit GitHub Release gate.

Each PR is independent:

- one PR completes exactly one stage;
- a PR never starts the next stage as a side effect;
- PR-1 does not implement any PR-2/PR-3/PR-4/PR-5 content;
- PR-2 does not implement any PR-3/PR-4/PR-5 content;
- PR-5 does not implement the release preparation;
- the version is bumped to 0.7.0 only in PR-6.

## 3. Version rules

```text
PR-1: 0.6.1
PR-2: 0.6.1
PR-3: 0.6.1
PR-4: 0.6.1
PR-5: 0.6.1
PR-6: 0.6.1 -> 0.7.0
```

The package version stays 0.6.1 through PR-5 and is bumped to 0.7.0 only
in PR-6. No early 0.7.0 version bump.

## 4. Product boundaries

The v0.7 product capability is Python Client / read-only artifact serving
only:

- No new CLI command.
- No REST API.
- No HTTP.
- No ML training.
- No backtesting.
- No signals.
- No trading.
- No writes through ArtifactClient.

None of these may be smuggled into any v0.7.0 PR.

## 5. Frozen technical invariants

V0.7.0 freezes the following invariants:

```text
Canonical identity unchanged
Dataset identity unchanged
Sample Generation identity unchanged
Catalog content identity unchanged
Catalog snapshot identity unchanged
schemas unchanged
artifact formats unchanged
existing artifacts require no migration
existing MarketVault API compatible
verified readers remain trust boundaries
explicit path only
no hidden latest
no current time
no settings requirement for ArtifactClient
no OpenD/network for ArtifactClient
normal CI Python 3.11 + 3.14 EXACT
PyArrow24 full-suite compatibility KEEP
pyarrow>=16 KEEP
dependency change = 0 by default
PyPI/TestPyPI deferred
```

## 6. PR-1 boundary

PR-1 (the merged baseline PR) may:

- seal the v0.6.1 formal GitHub release state;
- audit the existing Python public API;
- establish the v0.7.0 direction;
- establish the Python Client boundary contract;
- upgrade the release checker / release regression guards;
- sync the CI release-state marker;
- correct the README lifecycle truth.

PR-1 must not:

- implement `ArtifactClient` or any Python Client production module;
- add any new CLI command;
- modify any existing MarketVault production behavior;
- change any identity, schema, artifact, or contract;
- bump the package version (stays 0.6.1);
- change dependencies;
- create the v0.7.0 tag or GitHub Release.

## 6.1 PR-2 boundary

PR-2 (this PR) may implement only:

- the `ArtifactClient` class foundation;
- a stateless zero-argument constructor;
- the lazy top-level package export;
- foundation tests and the fresh-wheel public API smoke.

PR-2 must not implement:

- Canonical reader methods;
- Dataset reader methods;
- Dataset Catalog reader methods;
- filesystem artifact access;
- settings;
- discovery / latest;
- network / OpenD;
- future method stubs.

## 7. Acceptance principles

V0.7.0 keeps, unchanged:

- Python 3.11
- Python 3.14
- offline deterministic tests
- fail closed
- no current time
- no hidden latest
- no network / OpenD / settings for ArtifactClient
- targeted -> related -> full pytest -> CI
- one PR at a time
- immutable artifacts
- verified readers as trust boundaries
- clean worktree
- package smoke
- public API smoke
- wheel hygiene
- no unrequested merge
