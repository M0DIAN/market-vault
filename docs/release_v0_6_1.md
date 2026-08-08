# MarketVault v0.6.1 Release Notes

## Release preparation status

The v0.6.1 release is NOT formally released. PR-4 (this release
preparation stage) is the current stage of the fixed 4-PR sequence and is
OPEN / UNMERGED.

```text
base / development completion commit: 99c2e7bd445333740806dedec4aed03f82f32b11

PR-1: PR #44 MERGED 6bb9a9500fae53511ff964f47e5ccea20f3d91f7
PR-2: PR #45 MERGED 33d7f5856bf060527ccf4d2ab679df4429009ce6
PR-3: PR #46 MERGED 99c2e7bd445333740806dedec4aed03f82f32b11
PR-4: current release-preparation stage, OPEN / UNMERGED

package version in PR-4: 0.6.1
```

At preparation time:

```text
v0.6.1 tag:            NOT CREATED
GitHub Release v0.6.1: NOT PUBLISHED
PyPI:                  NOT PUBLISHED
TestPyPI:              NOT PUBLISHED
```

No future merge SHA is claimed, and no formal artifact SHA256 values are predicted.
The formal v0.6.1 release assets are created only after PR-4 merges, the
exact main release commit is verified, the main push CI succeeds, and
explicit release authorization is given; they must originate from the
exact future v0.6.1 release commit.

## 1. Maintenance summary

V0.6.1 is a maintenance release. It adds NO new product capability
(new product capabilities = 0). The fixed 4-PR sequence delivered exactly
three maintenance stages:

- PR-1 (PR #44, merged): post-release baseline + v0.6.1 maintenance
  direction.
- PR-2 (PR #45, merged): CLI / help / error / usability consistency
  polish.
- PR-3 (PR #46, merged): CI/package auditability + maintenance hardening.
- PR-4 (this PR): v0.6.1 release preparation.

The CI package artifact retention mechanism is a CI audit mechanism, not a
MarketVault product feature.

## 2. Candidate vs formal artifact distinction

The PR-4 branch and PR final-head CI wheel/sdist are candidate validation only.

The retained GitHub Actions package artifact is a CI audit artifact. It is
NOT a GitHub Release asset, NOT a PyPI artifact, and NOT a formal release
asset.

Formal v0.6.1 release assets are created only after PR-4 merges, after the
exact main release commit is verified, after main push CI succeeds, and
after explicit release authorization. They must originate from the exact
future v0.6.1 release commit. PR branch candidate hashes are never reused
as formal release asset hashes.

## 3. Compatibility

- No new product capability.
- CLI command set unchanged.
- Identity and schema unchanged.
- Formal contracts unchanged.
- Runtime dependencies unchanged.
- `pyarrow>=16` unchanged.
- `requires-python >=3.11` unchanged.
- No artifact migration or rewrite.

## 4. Known boundaries

- No Python Client.
- No REST API.
- No `dataset-catalog-query`.
- No ML training.
- No backtesting.
- No signals.
- No automatic trading.
- No Trading Execution.
