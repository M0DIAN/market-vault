# MarketVault v0.6.0 Release Notes

## Release preparation status

- This document describes the **v0.6.0 release preparation** stage.
- **PR-9** is the current release-preparation stage; the package version in
  PR-9 is **0.6.0**.
- PR-9 is open and **not merged**.
- The v0.6.0 tag does **not** exist yet.
- No GitHub Release exists yet.
- PyPI is not published.
- TestPyPI is not published.
- No merge SHA is recorded here yet: the final release artifacts are built
  from the exact release commit only after PR-9 is merged and the formal
  main push CI passes.

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

The PR-9 branch wheel/sdist are **release candidate validation only**.

The formal release artifacts must be rebuilt after PR-9 is merged, from the
exact release commit.

Therefore the PR-9 candidate SHA256 values must not be called formal
release asset SHA256 values.

The v0.6.0 tag and the GitHub Release can only be created by an explicit
action after the merge; PyPI publication remains a separate explicit
decision.

## 6. Runtime and compatibility facts

- `pyarrow>=16` remains the supported dependency range; only PyArrow
  24.0.0 and 25.0.0 were the two audited runtime/reader environments for
  the static reference artifact, with the PyArrow24 full-suite CI gate.
- `requires-python >=3.11` is unchanged; Python 3.11 and 3.14 are the
  normal CI matrix.
- Existing Canonical identity algorithms, Dataset identity algorithms, and
  the Dataset build-plan contract are unchanged.
- No migration or rewrite of existing artifacts.
