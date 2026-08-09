# MarketVault v0.7.0 Release Notes

## Release preparation status

V0.7.0 is NOT formally released. This document records the PR-6 release
preparation stage: PR-6 is the current release-preparation stage, OPEN /
UNMERGED. The release base commit is
`5ec437d37bb2cde0b716aa5dc1f84538b4bc6215` (the post-PR-5 merged main,
verified by PR #52's main CI run `31307554050`). The future merge commit
of PR-6 is UNKNOWN and is never predicted here.

## PR sequence

```text
PR-1: PR #48 MERGED bad62ee51e8eda03c7c5f20ac858973923e5f93d
PR-2: PR #49 MERGED 42c63ebfb0c2dfc91b1d61860bed2106faf1bba0
PR-3: PR #50 MERGED 61a2b055163815d463d5b261f5b6a94e54e515bd
PR-4: PR #51 MERGED 8b6bb12355c64d02c7e4f73fc67b6222ff2af6ed
PR-5: PR #52 MERGED 5ec437d37bb2cde0b716aa5dc1f84538b4bc6215
PR-6: current release-preparation stage, OPEN / UNMERGED
```

## Release state

```text
package version in PR-6: 0.7.0
v0.7.0 tag:            NOT CREATED
GitHub Release v0.7.0: NOT PUBLISHED
PyPI:                  NOT PUBLISHED
TestPyPI:              NOT PUBLISHED
```

## Candidate validation only

The PR-6 candidate package artifacts are validated for release readiness
only (candidate validation only). No future merge SHA was claimed and no formal artifact SHA256 values are claimed. PR candidate hashes: not reused as formal release asset hashes; they are never reused as formal
release asset hashes.

## Formal release gate

The formal v0.7.0 release is a separate explicit gate. The formal v0.7.0 release requires 5 independent conditions, all performed only after PR-6 merges and an independent review:

1. v0.7.0 tag creation;
2. GitHub Release publication;
3. PyPI publication decision;
4. TestPyPI publication decision;
5. independent review of the final artifacts.

## Scope of PR-6

new product capabilities = 0: PR-6 changes only the package version
(0.6.1 -> 0.7.0), the lifecycle documents, this release notes document,
and the release checker / release regression guards / CI release-state
marker.
