# MarketVault Release Playbook

The repository-native release procedure for MarketVault. This document
records the formal release gates that every MarketVault release must
pass. The current procedure was refined across v0.3.0 through v0.7.0,
with v0.7.0 serving as the current fully audited reference procedure;
see [docs/release_v0_7_0.md](docs/release_v0_7_0.md) for the recorded
v0.7.0 example.

## 1. Formal release gates

A formal MarketVault release is the sequence of the following gates, in
order. A release is not complete until every gate has passed and the
final state is sealed in the release notes document.

### 1.1 Exact release commit

The release commit is the exact commit on `main` whose CI passed and
whose content is being released — for example the v0.7.0 release commit
`f25a50481b5ee718881acf5cb5ea5aa05bd32d93`. Verify the release commit
SHA explicitly before any release step.

### 1.2 Clean detached / fresh build environment

Package and release validation is performed from a clean detached
checkout of the exact release commit (`git checkout --detach <SHA>`),
never from a working branch with uncommitted changes and never from a
stale build directory. The wheel and sdist are built fresh in this
environment.

### 1.3 Tag creation only after required merge / main verification

The annotated release tag is created only after:

- the release PR merged, and
- the main CI run for the exact merge commit succeeded.

Never create the tag from PR-state, branch-state, or unverified main
state.

### 1.4 Annotated tag identity

The release tag is an annotated tag (`git tag -a <version> <SHA>`),
created after merge and main verification, pointing at the exact release
commit. The peeled tag commit must equal the release commit. Record the
tag name, the tag object SHA, and the tag type in the release notes.

### 1.5 Formal GitHub Release asset identity

The GitHub Release publishes exactly the wheel, the sdist, and the
per-package `SHA256SUMS.txt` manifest. Record the Release ID, the
`publishedAt` timestamp, and `draft: false` / `prerelease: false` in the
release notes.

### 1.6 Wheel / sdist validation

Before upload: exactly one wheel and one sdist exist, `twine check`
passes, the wheel installs in a fresh virtual environment, the CLI
`--version` / `--help` surface works from the fresh wheel, and the
fresh-wheel public API import smoke passes.

### 1.7 Fresh-wheel smoke

Every formal assertion about the released artifact is exercised against
the freshly built wheel, never against the editable source checkout.

### 1.8 SHA256 closure

Compute the SHA-256 of every formal asset, verify the per-package
`SHA256SUMS.txt` manifest against the actual bytes, upload the assets to
the GitHub Release, download them again, and re-verify the hashes. The
recorded hashes are those of the formal Release assets.

### 1.9 Hash identity — three distinct classes

Never conflate the three hash classes:

| Class | Meaning |
|---|---|
| PR candidate hashes | Hashes of artifacts built and validated on the release-preparation branch / PR. Candidate validation only. |
| Main CI audit hashes | Hashes produced by the main push CI package audit run for the exact merge commit. Post-merge validation record. |
| Formal Release asset hashes | Hashes of the final assets rebuilt from the exact release commit after merge and main verification, downloaded back and re-verified. The authoritative recorded hashes. |

PR candidate hashes are never reused as formal Release asset hashes. The
formal assets are rebuilt from the exact release commit after merge and
main verification, regardless of what the PR CI built.

### 1.10 PyPI / TestPyPI publication is always separate and explicit

Publishing to PyPI or TestPyPI is a separate, explicit decision made
after the formal release gates above, never an automatic consequence of
tagging or of the GitHub Release. Each publication decision is recorded
(PUBLISHED or NOT PUBLISHED) in the release notes.

### 1.11 No post-release rebuild / re-upload / tag move to fix documentation issues

A released tag, a published GitHub Release, and its assets are not
rebuilt, re-uploaded, or moved to fix documentation, wording, or
cosmetic issues. Fixes belong in later `main` changes and later
releases.

## 2. Immutable-release principle

Published / tagged release artifacts are immutable records.

Post-release corrections belong on later `main` unless the actual
released artifact is invalid. An invalid artifact means the released
bytes do not match the recorded identity or fail the formal gates — a
corrupt upload, a wrong file, a broken wheel. Wording, formatting, or
documentation quality issues are never grounds for mutating a release.

## 3. Release state recording

The release notes document in `docs/` records the sealed state:
release commit, main CI run ID and job conclusions, tag identity, GitHub
Release identity, asset list with SHA-256s, and PyPI / TestPyPI state.
Any statement that would become false immediately after the release is
sealed must be marked as historical, not authoritative — see the
Lifecycle-State Principle in
[docs/development_protocol_v1.md](docs/development_protocol_v1.md).

### 3.1 Lifecycle-state recording timing (no immutable-release paradox)

Mutable lifecycle facts must NOT be required to exist as authoritative
current truth inside the immutable release payload (the release commit,
the annotated tag, and the published package artifacts). These include:

- tag-created state
- tag object SHA
- GitHub Release publication state
- Release ID
- `publishedAt`
- PyPI / TestPyPI publication state
- current main HEAD

The immutable release payload carries stable source truth — version,
feature scope, API / contracts, compatibility, non-goals, release
procedure, artifact formats. It cannot simultaneously record the
lifecycle facts that only become true after it is sealed.

After publication, mutable release facts may be recorded as an explicit
point-in-time / historical release record on later `main` — the same
pattern [docs/release_v0_7_0.md](docs/release_v0_7_0.md) already
follows, with its formal status section and its historical
release-preparation record.

Post-release `main` may legitimately advance beyond the immutable
release tag: the tag and its payload are frozen at the release commit,
while later `main` carries the historical release record and subsequent
work.

DP1 does NOT design or implement a machine-readable release-state
payload (`release/state.json` or equivalent). That remains DP5 work
after the semantics are designed.

## 4. Release-related hygiene for regular PRs

- Version changes, dependency changes, and formal release-state claims
  belong to release-preparation PRs, not to feature PRs.
- A PR must not move or recreate release tags, and must not alter
  release assets or sealed release records (see
  [AGENT_HANDOFF.md](AGENT_HANDOFF.md) rules 6 and 7).
