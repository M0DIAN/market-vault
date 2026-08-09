# MarketVault v0.7.0 Release Notes

## Formal release status

The v0.7.0 release is formally released and sealed.

```text
PR #53: MERGED
release commit: f25a50481b5ee718881acf5cb5ea5aa05bd32d93
main HEAD: f25a50481b5ee718881acf5cb5ea5aa05bd32d93
main CI: 31312887229
tag: v0.7.0
tag type: annotated
tag object: 563e8f94d6fc4c1717ed1cb9683c76df1802ed85
GitHub Release: MarketVault v0.7.0
release ID: 367478271
publishedAt: 2026-08-09T12:54:26Z
draft: false
prerelease: false
PyPI: NOT PUBLISHED
TestPyPI: NOT PUBLISHED
```

The annotated `v0.7.0` tag was created after the merge and points at the
release commit: the peeled tag commit equals the release commit. The GitHub
Release assets are exactly the wheel, the sdist, and the per-package
`SHA256SUMS.txt` manifest.

```text
market_vault-0.7.0-py3-none-any.whl
SHA-256:
C9B94D451B614FF4DEA16A495258085F11C58F138F3F44C0A20E47D2309BA47F

market_vault-0.7.0.tar.gz
SHA-256:
604AD74EAF5E98C5FAED930548E4346A7C1C4455B050295A2D82A43CBC6B21E1

SHA256SUMS.txt
SHA-256:
c9b94d451b614ff4dea16a495258085f11c58f138f3f44c0a20e47d2309ba47f  market_vault-0.7.0-py3-none-any.whl
604ad74eaf5e98c5faed930548e4346a7c1c4455b050295a2d82a43cbc6b21e1  market_vault-0.7.0.tar.gz
```

### Main CI

The main push CI run succeeded (run `31312887229`, event `push`, head
`f25a50481b5ee718881acf5cb5ea5aa05bd32d93`):

```text
test 3.11 SUCCESS
test 3.14 SUCCESS
portability-pyarrow24 SUCCESS
package SUCCESS
```

### Verification distinction

- The main push CI validation (run `31312887229`) is the authoritative
  post-merge run.
- The release-preparation branch validation below is a historical record.
- The formal artifacts are the GitHub Release assets with the SHA-256s
  above. The release-preparation branch and PR CI built and validated
  release candidates. After PR #53 merged and the main push CI succeeded,
  the formal wheel and sdist were rebuilt from the exact release commit
  `f25a50481b5ee718881acf5cb5ea5aa05bd32d93`, twine-checked, fresh-wheel
  validated, uploaded as GitHub Release assets, downloaded again, and
  SHA-256 verified.
- release-preparation branch artifacts: candidate validation only.
- formal GitHub Release assets: rebuilt after merge from the exact
  release commit.
- PyPI and TestPyPI are not published; publication remains a separate,
  explicit decision.

## Historical release-preparation record

The sections below record the v0.7.0 release-preparation state at the time
PR-6 was opened. They are historical records, not the current release
state; the Formal release status section above is authoritative.

### Release-preparation status (as recorded in PR-6)

At the time PR-6 was opened, the release preparation recorded:

- V0.7.0 was NOT formally released; PR-6 was the current
  release-preparation stage, OPEN / UNMERGED.
- The release base commit was
  `5ec437d37bb2cde0b716aa5dc1f84538b4bc6215` (the post-PR-5 merged main,
  verified by PR #52's main CI run `31307554050`).
- The future merge commit of PR-6 was UNKNOWN and was never predicted.
- The v0.7.0 tag was NOT CREATED, the GitHub Release v0.7.0 was NOT
  PUBLISHED, and PyPI / TestPyPI were NOT PUBLISHED.
- The PR-6 candidate package artifacts were validated for release
  readiness only (candidate validation only). No future merge SHA was
  claimed and no formal artifact SHA256 values were claimed. PR candidate
  hashes were not reused as formal release asset hashes.
- The formal v0.7.0 release was a separate explicit gate requiring 5
  independent conditions, all performed only after PR-6 merged and an
  independent review: (1) v0.7.0 tag creation; (2) GitHub Release
  publication; (3) PyPI publication decision; (4) TestPyPI publication
  decision; (5) independent review of the final artifacts.

## PR sequence

```text
PR-1: PR #48 MERGED bad62ee51e8eda03c7c5f20ac858973923e5f93d
PR-2: PR #49 MERGED 42c63ebfb0c2dfc91b1d61860bed2106faf1bba0
PR-3: PR #50 MERGED 61a2b055163815d463d5b261f5b6a94e54e515bd
PR-4: PR #51 MERGED 8b6bb12355c64d02c7e4f73fc67b6222ff2af6ed
PR-5: PR #52 MERGED 5ec437d37bb2cde0b716aa5dc1f84538b4bc6215
PR-6: PR #53 MERGED f25a50481b5ee718881acf5cb5ea5aa05bd32d93
```

## Scope of PR-6

new product capabilities = 0: PR-6 changed only the package version
(0.6.1 -> 0.7.0), the lifecycle documents, the release notes document,
and the release checker / release regression guards / CI release-state
marker. After PR-6 merged, the separate explicit GitHub Release gate
created the annotated `v0.7.0` tag, published the GitHub Release
`MarketVault v0.7.0`, and sealed the formal assets recorded above.
