# MarketVault v0.5.1 Release Notes

## Formal release status

The v0.5.1 maintenance release is formally released and sealed.

```text
PR #33: MERGED
mergedAt: 2026-08-05T17:22:15Z
release commit: a978eef291d5e26d20e5cf977bc76609c227cb52
main HEAD: a978eef291d5e26d20e5cf977bc76609c227cb52
tag: v0.5.1
GitHub Release: MarketVault v0.5.1
publishedAt: 2026-08-05T17:33:12Z
draft: false
prerelease: false
PyPI: not published
TestPyPI: not published
```

The annotated `v0.5.1` tag was created after the merge and points at the
release commit: the peeled tag commit equals the release commit. The GitHub
Release assets are exactly the wheel and the sdist.

```text
market_vault-0.5.1-py3-none-any.whl
SHA-256:
80965A671AEEF75F315386D9BD4B62EC5DC08E552CB3430AEF92F83C562248C1

market_vault-0.5.1.tar.gz
SHA-256:
FE82FB4FD254C493EC00519EDEB438533C0C5E8D5A7690E1F14AEA39DE4CCDAB
```

### Main CI

The main push CI run succeeded (run `31029709970`, event `push`, head
`a978eef291d5e26d20e5cf977bc76609c227cb52`):

```text
Python 3.11: 2286 passed, 7 skipped
Python 3.14: 2286 passed, 7 skipped
package: success
```

### Verification distinction

- The main push CI validation (run `31029709970`) is the authoritative
  post-merge run.
- The release-preparation branch validation below is a historical record.
- The formal artifacts are the GitHub Release assets with the SHA-256s
  above. The release-preparation branch and PR CI built and validated
  release candidates. After PR #33 merged and the main push CI succeeded,
  the formal wheel and sdist were rebuilt from the exact release commit
  `a978eef291d5e26d20e5cf977bc76609c227cb52`, twine-checked, fresh-wheel
  validated, uploaded as GitHub Release assets, downloaded again, and
  SHA-256 verified.
- release-preparation branch artifacts: candidate validation only.
- formal GitHub Release assets: rebuilt after merge from the exact
  release commit.
- PyPI and TestPyPI are not published; publication remains a separate,
  explicit decision.

## Historical release-preparation record

The sections below record the release preparation work and the state of the
release-preparation PR at the time it was opened. This is the v0.5.1 release
preparation history; the preparation merged as GitHub PR #33, and the
tag and GitHub Release were created after the merge. The Formal release
status section above is authoritative.

## Release preparation boundary

- The package version was bumped to 0.5.1 by the release-preparation PR.
- No Dataset / Canonical identity, schema, contract, or CLI behavior
  changes; no dependency changes; `requires-python >=3.11` unchanged.
- No Sample Generator, Dataset Catalog, Python Client, REST API, ML
  training, or trading work.

## V0.5.0 base

```text
v0.5.0 release commit:
3b4d03c785123e204885faea08df7b9d7ed07ec0
```

## Merged maintenance PRs

GitHub PR numbers (not the internal roadmap PR-1..PR-4 sequence):

- PR #30 — docs: define v0.5.1 maintenance direction
  (merged 2026-08-05T14:38:11Z, squash merge commit
  `8de57d497ae5d922e3df29d9475f14b9407865f0`): post-release state
  alignment, the v0.5.1 direction document, and the release checker /
  release tests switched to the released-state verification.
- PR #31 — fix: remove NumPy timedelta deprecation warnings
  (merged 2026-08-05T15:36:33Z, squash merge commit
  `2d9c8a539f04ee2d75e5482c858ec6c3364af135`): explicit-unit
  `pd.Timedelta` construction in production and tests, the precise
  warning-as-error pytest guard, and the deprecation-compatibility
  regression suite.
- PR #32 — docs: add verified Dataset CLI examples
  (merged 2026-08-05T16:33:55Z, squash merge commit
  `240f7ccac89a773366a510f10a13d6de801051ea`): the verified example
  FeatureSpec / LabelSpec / split spec files, COMPLETE and EMPTY plan
  templates, the stdlib-only renderer, the PowerShell usage flow, common
  error documentation, and the example regression tests, plus the renderer
  hardening follow-up commit (`1f48efde963a5aee2b9bf55fd093db677e296abe`).
- PR #33 — chore: prepare v0.5.1 release
  (merged 2026-08-05T17:22:15Z, squash merge commit
  `a978eef291d5e26d20e5cf977bc76609c227cb52`): the v0.5.1 release
  preparation. See the Formal release status section for the final state.

## PR-4 release-preparation history

PR-4 (`chore: prepare v0.5.1 release`) was the release-preparation PR on
the `release/v0.5.1` branch. It merged as GitHub PR #33 at
2026-08-05T17:22:15Z with the squash merge commit
`a978eef291d5e26d20e5cf977bc76609c227cb52`. At the time the PR was opened,
the `v0.5.1` tag and the GitHub Release had not yet been created; both were
created after the merge.

## Compatibility cleanup

- The NumPy generic-timedelta `DeprecationWarning` from MarketVault's own
  production code and tests is removed.
- `bar_available_at` and `derive_internal_gap_ranges` now construct
  `pd.Timedelta` with explicit values and units; Python `int` and NumPy
  integer inputs are equivalent.
- Gap content, gap identity, Canonical schema, and Dataset identity are
  unchanged.
- A precise warning-as-error guard turns the exact warning into a test
  error.
- GitHub Actions' own Node deprecations are runner-environment messages,
  not MarketVault warnings.

## Dataset CLI examples

- Verified FeatureSpec (`simple_return`), LabelSpec (`forward_return`),
  and ChronologicalSplitSpec examples.
- COMPLETE and EMPTY build-plan templates.
- A stdlib-only plan renderer (`examples/dataset_cli/render_plans.py`).
- A complete Windows PowerShell usage flow and 24 documented common
  errors.

## Renderer hardening

- Fixed UTC six-digit microsecond serialization for `built_at` and
  `dataset_as_of`.
- Fail-closed behavior for existing destinations, regular-file
  destinations, blank path arguments, and filesystem errors.

## Compatibility

- V0.1–v0.5.0 CLI behavior is unchanged.
- Dataset and Canonical identity, schema versions, and the build-plan /
  Feature / Label / split contracts are unchanged.
- Runtime dependencies are unchanged; `requires-python >=3.11` unchanged;
  Python 3.11 and 3.14 remain supported.
- Existing v0.5.0 Dataset and Canonical artifacts are never migrated,
  overwritten, or rewritten.

## Historical validation records

The local and release-preparation-branch CI results are reported separately
because platform-dependent skips differ between Windows and Linux; the
authoritative post-merge run is the main push CI in the Formal release
status section.

### Local validation

Recorded on the release-preparation branch before opening the PR (Windows):

```text
Full offline pytest: 2282 passed, 11 skipped
Focused release tests: 115 passed
Explicit warning-as-error suite: 2282 passed, 11 skipped
compileall (src tests scripts examples): passed
repository hygiene: passed
git diff --check: passed
release checker: RELEASE_CHECK_OK version=0.5.1
CLI version: market-vault 0.5.1
wheel/sdist: market_vault-0.5.1-py3-none-any.whl and
             market_vault-0.5.1.tar.gz, both twine-checked
fresh-wheel install: module and distribution metadata assert 0.5.1
Dataset CLI help smoke: dataset-build / dataset-verify / dataset-inspect
public API smoke: V051_PUBLIC_API_IMPORT_OK
pip check: no broken requirements
wheel contents: WHEEL_CONTENTS_OK
```

### GitHub Actions validation

Recorded by the final CI run on the release-preparation branch
(ubuntu-latest); the run corresponds to the final head after the release
notes were updated. This is a release-preparation-branch record; the
authoritative post-merge run is the main push CI
(run `31029709970`).

```text
test (3.11): 2286 passed, 7 skipped
test (3.14): 2286 passed, 7 skipped
package: success
    RELEASE_CHECK_OK version=0.5.1
    market-vault 0.5.1
    market_vault-0.5.1-py3-none-any.whl
    market_vault-0.5.1.tar.gz
    twine check: PASSED
    V051_PUBLIC_API_IMPORT_OK
    WHEEL_CONTENTS_OK
    render_plans.py --help smoke: success
```

## Packaging

Final artifacts (the GitHub Release assets):

```text
market_vault-0.5.1-py3-none-any.whl
market_vault-0.5.1.tar.gz
```

- `examples/` is repository source documentation; the examples renderer is
  not part of the wheel public API.
- The wheel installs only the `market_vault` package.
- Nothing is claimed as installed from PyPI.

## Known boundaries

- No Sample Generator, Dataset Catalog, Python Client, REST API, ML
  training, backtesting, or automatic trading.
- No arbitrary user transforms, no adjusted-price PIT
  (`adjustment = NONE` only), no cross-trading-day Label execution, and no
  `TRADING_DAYS` Label horizon.
- No `latest`-directory discovery and no automatic Canonical discovery.

## Non-actions

The release-preparation PR itself did not create the `v0.5.1` tag and did
not create the GitHub Release; both were created after the merge (see the
Formal release status section). PyPI publication remains a separate,
explicit decision.

## Release checklist

- [x] Version synced to 0.5.1 (pyproject, `_version.py`, checker, tests,
      CI, examples README).
- [x] README, CHANGELOG, release notes, and direction document updated.
- [x] Release checker and release tests updated to 0.5.1.
- [x] Wheel and sdist built and twine-checked; fresh-wheel validated.
- [x] Tag `v0.5.1` created (annotated, points at the release commit).
- [x] GitHub Release `MarketVault v0.5.1` published with the wheel and
      sdist assets.
- [ ] PyPI publication (separate, explicit decision).
