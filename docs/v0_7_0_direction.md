# MarketVault v0.7.0 Direction: Python Client and Read-only Artifact Access

Status: released on 2026-08-09

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
PR-2: COMPLETE / MERGED / MAIN VERIFIED
PR-3: COMPLETE / MERGED / MAIN VERIFIED
PR-4: COMPLETE / MERGED / MAIN VERIFIED
PR-5: COMPLETE / MERGED / MAIN VERIFIED
PR-6: COMPLETE / MERGED / RELEASED
package: 0.7.0
v0.7.0: FORMALLY RELEASED
```

PR-1 record:

```text
PR #48 merged at 2026-08-08T23:50:24Z
squash/main: bad62ee51e8eda03c7c5f20ac858973923e5f93d
main CI: 31284875166 SUCCESS
package: 0.6.1
```

PR-2 record:

```text
PR #49 merged at 2026-08-09T01:24:46Z
final head: 1a3ca95a6765e4418e753f1fec6d5c79b8e49e2f
squash/main: 42c63ebfb0c2dfc91b1d61860bed2106faf1bba0
main CI: 31288212317 SUCCESS
package: 0.6.1
ArtifactClient foundation: IMPLEMENTED
Canonical / Dataset / Catalog reads at PR-2: NOT IMPLEMENTED
```

PR-3 record:

```text
PR #50 merged at 2026-08-09T05:34:20Z
final head: 01d40bd9a090dc1e23d9539aa57a8649c0d64b7c
squash/main: 61a2b055163815d463d5b261f5b6a94e54e515bd
main CI: 31296976872 SUCCESS
package: 0.6.1
ArtifactClient Canonical verified read: IMPLEMENTED
ArtifactClient Dataset verified read: IMPLEMENTED
Dataset Catalog client read at PR-3: NOT IMPLEMENTED
```

PR-4 record:

```text
PR #51 merged at 2026-08-09T07:42:17Z
final head: 49dbc9fdc53d40d0955febe61c87e9cb71dcc159
squash/main: 8b6bb12355c64d02c7e4f73fc67b6222ff2af6ed
main CI: 31301770295 SUCCESS
package: 0.6.1
ArtifactClient Canonical verified read: IMPLEMENTED
ArtifactClient Dataset verified read: IMPLEMENTED
ArtifactClient Dataset Catalog verified read: IMPLEMENTED
```

PR-5 record:

```text
PR #52 merged at 2026-08-09T10:07:06Z
final head: 2f7ee8dd6c7c3ce07f677be99cdd8afb8f2c68d4
squash/main: 5ec437d37bb2cde0b716aa5dc1f84538b4bc6215
main CI: 31307554050 SUCCESS
package before PR-6: 0.6.1
ArtifactClient integrated E2E acceptance: IMPLEMENTED
consumer usability docs and source-tree examples: IMPLEMENTED
```

PR-6 record:

```text
PR #53 merged at 2026-08-09T12:16:49Z
squash/main: f25a50481b5ee718881acf5cb5ea5aa05bd32d93
main CI: 31312887229 SUCCESS
package: 0.7.0
v0.7.0: FORMALLY RELEASED
```

The v0.7.0 release is sealed at the release commit
`f25a50481b5ee718881acf5cb5ea5aa05bd32d93`: the main push CI run
`31312887229` succeeded, the annotated `v0.7.0` tag points at the release commit,
and the GitHub Release `MarketVault v0.7.0` is published on
2026-08-09T12:54:26Z with exactly the wheel, the sdist, and the
`SHA256SUMS.txt` manifest assets. PyPI: NOT PUBLISHED. TestPyPI: NOT PUBLISHED.
The CI release-state marker is `V070_RELEASED_OK` (the preparation-time
marker `V070_RELEASE_PREP_OK` was superseded at the formal release).

This document defines the scope, non-goals, and fixed PR sequence for the
V0.7.0 "Python Client and Read-only Artifact Access" feature release.
V0.7.0 delivers a settings-independent Python artifact client that serves
verified immutable artifacts through the existing formal verified
readers. PR-1 established the post-v0.6.1 release baseline, the existing
Python API audit (`docs/v0_7_0_python_api_audit.md`), and the Python
Client boundary contract (`docs/contracts/python_client.md`). PR-2
implemented the settings-independent `ArtifactClient` foundation (merged
PR #49). PR-3 added the Canonical + Dataset verified read-only client
access (merged PR #50). PR-4 added the Dataset Catalog verified read-only
client access (merged PR #51). PR-5 added the integrated offline
end-to-end acceptance, the explicit-path Python / Jupyter / ML-consumer
usability documentation, the source-tree examples, and the backward
compatibility hardening (merged PR #52). PR-6 performed the v0.7.0
release preparation and is complete (merged PR #53 at the release commit
`f25a50481b5ee718881acf5cb5ea5aa05bd32d93`). V0.7.0 is formally released:
the annotated `v0.7.0` tag is created, the GitHub Release `MarketVault
v0.7.0` is published, and PyPI / TestPyPI are NOT PUBLISHED.

The planning and boundary sections below are the historical v0.7.0
planning record; they describe the plan as it was fixed at planning time,
and the authoritative current state is the released state recorded above.

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
- PR-3 does not implement any PR-4/PR-5 content;
- PR-4 does not implement any PR-5 content;
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

PR-2 (the merged foundation PR, #49) implemented only:

- the `ArtifactClient` class foundation;
- a stateless zero-argument constructor;
- the lazy top-level package export;
- foundation tests and the fresh-wheel public API smoke.

PR-2 did not implement:

- Canonical reader methods;
- Dataset reader methods;
- Dataset Catalog reader methods;
- filesystem artifact access;
- settings;
- discovery / latest;
- network / OpenD;
- future method stubs.

## 6.2 PR-3 boundary (merged PR #50)

PR-3 (the merged reader PR, #50) implemented only:

- `load_canonical_build`;
- `load_dataset`;
- direct formal verified reader delegation;
- reader-access tests;
- contract/direction/checker changes;
- fresh-wheel API smoke updates.

PR-3 did not implement:

- Dataset Catalog client access;
- Catalog lookup/filter;
- any writer/builder;
- discovery/latest;
- settings;
- OpenD/network;
- current-time behavior;
- CLI;
- PR-4/5/6 work.

## 6.3 PR-4 boundary (merged PR #51)

PR-4 (the merged Catalog-read PR, #51) implemented only:

- `load_dataset_catalog`;
- direct formal verified Catalog reader delegation;
- Catalog reader access tests;
- contract/direction/checker changes;
- fresh-wheel smoke updates.

PR-4 did not implement:

- Catalog builder;
- Catalog materialization;
- Catalog list/filter/query convenience API;
- new CLI;
- dataset-catalog-query CLI;
- Canonical/Dataset production changes;
- artifact format change;
- schema change;
- identity change;
- migration;
- settings;
- discovery/latest;
- network/OpenD;
- current time;
- PR-5 usability/examples;
- PR-6 release prep;
- version bump.

## 6.4 PR-5 boundary

PR-5 (this PR) MAY ONLY:

- add integrated offline E2E acceptance;
- add explicit-path Python consumer documentation;
- add Jupyter-friendly consumer documentation;
- add ML-consumer handoff documentation without ML implementation;
- add source-tree examples;
- harden backward compatibility tests;
- harden release checker;
- add existing-job CI smoke for PR-5 examples/acceptance.

PR-5 MUST NOT:

- modify src/;
- modify dependencies;
- modify version;
- add ArtifactClient capabilities;
- add CLI;
- add discovery/latest;
- add settings;
- add network/OpenD;
- add current time;
- add visualization product code;
- add ML/training/evaluation;
- perform PR-6 release preparation.

## 6.5 PR-6 boundary

PR-6 (this PR) MAY ONLY:

- bump the package version from 0.6.1 to 0.7.0;
- sync the lifecycle documents (direction, contract, README, CHANGELOG);
- add the v0.7.0 release notes (`docs/release_v0_7_0.md`);
- harden the release checker / release regression guards;
- sync the CI release-state marker to `V070_RELEASE_PREP_OK`.

PR-6 MUST NOT:

- modify `src/` except the `_version.py` version bump;
- modify dependencies;
- add ArtifactClient capabilities;
- add CLI;
- add discovery/latest;
- add settings;
- add network/OpenD;
- add current time;
- create the v0.7.0 tag;
- publish a GitHub Release;
- publish to PyPI / TestPyPI.

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
