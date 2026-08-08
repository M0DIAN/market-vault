# MarketVault v0.6.1 Release Notes

## Formal release status

The v0.6.1 release is formally released and sealed.

```text
PR-4: PR #47 MERGED
mergedAt: 2026-08-08T12:20:16Z
release commit: 37614d539171ef7b738e47415f3cd6ca2de332d1
main HEAD: 37614d539171ef7b738e47415f3cd6ca2de332d1
main CI: 31257004716
tag: v0.6.1
tag type: annotated
tag object: 0e0508065a6330d643e7801823e908fee881afc9
GitHub Release: MarketVault v0.6.1
release id: 367204479
publishedAt: 2026-08-08T13:06:51Z
draft: false
prerelease: false
latest: true
PyPI: NOT PUBLISHED
TestPyPI: NOT PUBLISHED
```

The annotated `v0.6.1` tag was created after the merge and points at the
release commit: the peeled tag commit equals the release commit. The GitHub
Release assets are exactly the wheel and the sdist.

```text
market_vault-0.6.1-py3-none-any.whl
SHA-256:
8fd8ec510a7724742d6e3e9fbca5c73b07e991cb3fa35002af792a8dd64ed550

market_vault-0.6.1.tar.gz
SHA-256:
0cadd537a0980978a9a0878766cb2234f5b419f3f5d3874ef92e300c76c756f1
```

### Main CI

The main push CI run succeeded (run `31257004716`, event `push`, head
`37614d539171ef7b738e47415f3cd6ca2de332d1`):

```text
test 3.11 SUCCESS
test 3.14 SUCCESS
portability-pyarrow24 SUCCESS
package SUCCESS
```

### Verification distinction

- The main push CI validation (run `31257004716`) is the authoritative
  post-merge run.
- The release-preparation branch validation below is a historical record.
- The formal assets were rebuilt from the exact release commit
  `37614d539171ef7b738e47415f3cd6ca2de332d1` after PR #47 merged and the
  main push CI succeeded, twine-checked, fresh-wheel validated, uploaded as
  GitHub Release assets, downloaded again, and SHA-256 verified.
- PR candidate hashes: not reused as formal release asset hashes.
- main CI artifact hashes: not formal release hashes. The retained GitHub
  Actions package artifact is a CI audit artifact, not a GitHub Release
  asset, not a PyPI artifact, and not a formal release asset.
- PyPI and TestPyPI are not published; publication is deferred until
  project maturity and remains a separate, explicit decision.

## Historical release-preparation record

The sections below record the v0.6.1 release-preparation state at the time
PR-4 was opened. They are historical records, not the current release
state; the Formal release status section above is authoritative.

### Release-preparation state (as recorded in PR-4)

At the time PR-4 was opened, the release preparation recorded:

- PR-4 was the release-preparation stage, OPEN / UNMERGED; the package
  version in PR-4 was 0.6.1.
- PR-4 was open and not merged.
- The v0.6.1 tag was not created.
- The GitHub Release v0.6.1 was not published.
- PyPI was not published; TestPyPI was not published.
- No future merge SHA was claimed, and no formal artifact SHA256 values
  were predicted.
- The PR-4 branch wheel/sdist were candidate validation only; the formal
  v0.6.1 release assets were to be created only after PR-4 merged, the
  exact main release commit was verified, the main push CI succeeded, and
  explicit release authorization was given, to be built from the exact
  future v0.6.1 release commit; PR branch candidate hashes were never to
  be reused as formal release asset hashes.

The recorded preparation-time state block was:

```text
base / development completion commit: 99c2e7bd445333740806dedec4aed03f82f32b11

PR-1: PR #44 MERGED 6bb9a9500fae53511ff964f47e5ccea20f3d91f7
PR-2: PR #45 MERGED 33d7f5856bf060527ccf4d2ab679df4429009ce6
PR-3: PR #46 MERGED 99c2e7bd445333740806dedec4aed03f82f32b11
PR-4: current release-preparation stage, OPEN / UNMERGED

package version in PR-4: 0.6.1

v0.6.1 tag:            NOT CREATED
GitHub Release v0.6.1: NOT PUBLISHED
PyPI:                  NOT PUBLISHED
TestPyPI:              NOT PUBLISHED
```

## 1. Maintenance summary

V0.6.1 is a maintenance release. It adds NO new product capability
(new product capabilities = 0). The fixed 4-PR sequence delivered exactly
three maintenance stages:

- PR-1 (PR #44, merged): post-release baseline + v0.6.1 maintenance
  direction.
- PR-2 (PR #45, merged): CLI / help / error / usability consistency
  polish.
- PR-3 (PR #46, merged): CI/package auditability + maintenance hardening.
- PR-4 (PR #47, merged): v0.6.1 release preparation.

The CI package artifact retention mechanism is a CI audit mechanism, not a
MarketVault product feature.

## 2. Compatibility

- No new product capability.
- CLI command set unchanged.
- Identity and schema unchanged.
- Formal contracts unchanged.
- Runtime dependencies unchanged.
- `pyarrow>=16` unchanged.
- `requires-python >=3.11` unchanged.
- No artifact migration or rewrite.

## 3. Known boundaries

- No Python Client.
- No REST API.
- No `dataset-catalog-query`.
- No ML training.
- No backtesting.
- No signals.
- No automatic trading.
- No Trading Execution.
