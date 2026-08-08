# MarketVault v0.6.0 Release Notes

## Formal release status

The v0.6.0 release is formally released and sealed.

```text
PR #43: MERGED
mergedAt: 2026-08-07T23:41:36Z
release commit: 669c955abc0a234264964dfdb7fcafdf502a901a
main HEAD: 669c955abc0a234264964dfdb7fcafdf502a901a
main CI: 31227915770
tag: v0.6.0
tag type: annotated
GitHub Release: MarketVault v0.6.0
publishedAt: 2026-08-08T03:17:48Z
draft: false
prerelease: false
PyPI: NOT PUBLISHED
TestPyPI: NOT PUBLISHED
```

The annotated `v0.6.0` tag was created after the merge and points at the
release commit: the peeled tag commit equals the release commit. The GitHub
Release assets are exactly the wheel and the sdist.

```text
market_vault-0.6.0-py3-none-any.whl
SHA-256:
B1BC7D945A8DDF981AEB4AB2B973E5A8BD07919D7293DED15A7715BC03B262AF

market_vault-0.6.0.tar.gz
SHA-256:
DBA631EC71BD6FD56A436DEB1F82481FAA3E3E89BA5D03D207870F2C96AF3C37
```

### Main CI

The main push CI run succeeded (run `31227915770`, event `push`, head
`669c955abc0a234264964dfdb7fcafdf502a901a`):

```text
test 3.11 SUCCESS
test 3.14 SUCCESS
portability-pyarrow24 SUCCESS
package SUCCESS
```

### Verification distinction

- The main push CI validation (run `31227915770`) is the authoritative
  post-merge run.
- The release-preparation branch validation below is a historical record.
- The formal artifacts are the GitHub Release assets with the SHA-256s
  above. The release-preparation branch and PR CI built and validated
  release candidates. After PR #43 merged and the main push CI succeeded,
  the formal wheel and sdist were rebuilt from the exact release commit
  `669c955abc0a234264964dfdb7fcafdf502a901a`, twine-checked, fresh-wheel
  validated, uploaded as GitHub Release assets, downloaded again, and
  SHA-256 verified.
- release-preparation branch artifacts: candidate validation only.
- formal GitHub Release assets: rebuilt after merge from the exact
  release commit.
- PyPI and TestPyPI are not published; publication remains a separate,
  explicit decision.

## Historical release-preparation record

The sections below record the v0.6.0 release-preparation state at the time
PR-9 was opened. They are historical records, not the current release
state; the Formal release status section above is authoritative.

### Release-preparation state (as recorded in PR-9)

At the time PR-9 was opened, the release preparation recorded:

- PR-9 was the release-preparation stage; the package version in PR-9 was
  0.6.0.
- PR-9 was open and not merged.
- The v0.6.0 tag did not exist yet.
- No GitHub Release existed yet.
- PyPI was not published.
- TestPyPI was not published.
- No merge SHA was recorded yet: the final release artifacts were built
  from the exact release commit only after PR-9 was merged and the formal
  main push CI passed.
- The PR-9 branch wheel/sdist were candidate validation only; the formal
  release artifacts were rebuilt after the merge from the exact release
  commit.

## 1. Release development baseline

The v0.5.1 released baseline is:

```text
a978eef291d5e26d20e5cf977bc76609c227cb52
```

The PR-8-complete release-preparation base (the development baseline this
PR-9 branch is cut from) is:

```text
24a2243031b5f16fdbb9334f1a1722e56eb7a2f7
```

PR #42 (PR-8 integrated acceptance) was merged at:

```text
2026-08-07T18:32:32Z
```

PR-8 main was verified by CI run **31207428151**:

```text
test 3.11 SUCCESS
test 3.14 SUCCESS
portability-pyarrow24 SUCCESS
package SUCCESS
```

PyArrow24 full suite (run 31207428151):

```text
3103 passed
7 skipped
0 failed
```

This is the **pre-release product acceptance baseline**; it is not the
PR-9 final release CI.

## 2. v0.6.0 merged work

All v0.6.0 development work merged before PR-9, by GitHub PR number:

| PR | Stage | Squash commit |
| --- | --- | --- |
| #34 | PR-1 direction | `6bc03d76078c8355322e65d6ca05cc986b4dbe23` |
| #35 | PR-2 Sample Generation contract | `0f66c61407c8ba4f122ad1e5d0463ab2f8f66883` |
| #36 | PR-3 Sample Generator core | `4d5124fa1f1c30db5dcc5b8bb72c7e4f04f1109c` |
| #37 | PR-4 Sample Generator CLI | `ca486a19e6795940f21a9a22053fc59175510d91` |
| #38 | standalone Canonical reader hotfix | `b4c3618d631b2950934acbae4a72e00b2adf7350` |
| #39 | PR-5 Catalog contract | `2958697dd434c536c39267b6a654dabb762c74f9` |
| #40 | PR-6 Catalog snapshot | `997bb337f73f1205d9180c4c532a6679666a312f` |
| #41 | PR-7 Catalog CLI | `15ce0efc5a61a34772bf426f77386bd1bcfe449b` |
| #42 | PR-8 integrated acceptance | `24a2243031b5f16fdbb9334f1a1722e56eb7a2f7` |

PR #38 is a standalone verified-reader hotfix outside the fixed v0.6.0
PR sequence; it is not an internal roadmap stage such as PR-5.

## 3. The two product chains

v0.6.0 contains exactly **two product capabilities**.

### A. Deterministic Sample Generator

```text
verified Canonical
    → generation plan
    → deterministic requests
    → ordinary Dataset build-plan
    → existing dataset-build
```

Formal command: `market-vault sample-generate --plan <PATH>`.

- verified Canonical builds plus one explicit generation plan produce a
  deterministic PITSampleRequest sequence;
- the output is an ordinary `market-vault-dataset-build-plan-v1` document
  handed directly to the existing `dataset-build` command;
- no current time, no `latest`, no settings, no OpenD, no network.

### B. Immutable Dataset Catalog

```text
verified Dataset set
    → Catalog builder
    → immutable snapshot
    → verified Catalog reader
    → build / verify / list / show
```

Formal commands: `market-vault dataset-catalog-build`,
`market-vault dataset-catalog-verify`,
`market-vault dataset-catalog-list`,
`market-vault dataset-catalog-show`.

- verified immutable Datasets project into deterministic Catalog content
  and an immutable snapshot;
- the verified reader recomputes every content and physical identity from
  the snapshot's own bytes;
- discovery is read-only list/show; there is no standalone
  `dataset-catalog-query`, no repair, no `latest`, and no Dataset rewrite.

## 4. Integrated acceptance (PR-8)

PR-8 officially passed:

- COMPLETE E2E
- EMPTY E2E
- determinism
- corruption
- recovery
- security
- read-only
- usability
- PyArrow 24/25 audit

Precise portability wording:

- fixed static artifact: PyArrow 24.0.0 and PyArrow 25.0.0 audited
  readers/runtimes → frozen values unchanged;
- different source writer bytes: may create different physical source
  provenance/version identities;
- the Canonical output Parquet serializer/layout does not independently
  enter the Canonical logical identity.

The static artifact read-portability audit covers exactly the two audited
PyArrow environments (24.0.0 and 25.0.0); it does not claim that every
`pyarrow>=16` version was audited, and it never claims identity identical
across writers.

## 5. Candidate vs formal release artifacts

The PR-9 branch wheel/sdist were **release candidate validation only**.

The formal release artifacts were rebuilt after PR-9 was merged, from the
exact release commit `669c955abc0a234264964dfdb7fcafdf502a901a`.

Therefore the PR-9 candidate SHA256 values were never called formal
release asset SHA256 values. The formal GitHub Release asset SHA-256s are
recorded in the Formal release status section above.

The v0.6.0 tag and the GitHub Release were created by an explicit action
after the merge; PyPI publication remains a separate explicit decision.

## 6. Runtime and compatibility facts

- `pyarrow>=16` remains the supported dependency range; only PyArrow
  24.0.0 and 25.0.0 were the two audited runtime/reader environments for
  the static reference artifact, with the PyArrow24 full-suite CI gate.
- `requires-python >=3.11` is unchanged; Python 3.11 and 3.14 are the
  normal CI matrix.
- Existing Canonical identity algorithms, Dataset identity algorithms, and
  the Dataset build-plan contract are unchanged.
- No migration or rewrite of existing artifacts.
