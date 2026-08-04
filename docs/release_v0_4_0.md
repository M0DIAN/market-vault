# MarketVault v0.4.0 Release Notes

## Release scope

```text
base tag: v0.3.0
base tag commit: 458b29f521518c9b6420ed8e1309b01847b2345d
release preparation base: 6d3e8d255f082fb8fef1324e87d18804d57d3ae1

release version: 0.4.0
release date: 2026-08-05
```

## Merged development PRs

GitHub PR numbers (not the internal roadmap PR-1..PR-10 sequence):

- PR #8 — docs: plan v0.4.0 canonical dataset and ML foundation
  (merge commit `d09158a40614e2ce7f8c91d069b6a2abdc7bea63`)
- PR #9 — test/docs: resolve market-bar timestamp and archive-clock semantics
  (merge commit `f8190f2e1c7d809c92503d2f8de22b74147a8136`)
- PR #10 — feat: add canonical market-bar builder core
  (merge commit `b9c0ec0d213f457b4877c0405537343ff2d087f8`)
- PR #11 — feat: materialize immutable canonical market-bar builds
  (merge commit `b7a35fcce9d177d3fc98ac6a8cdbd6d6341b9fb4`)
- PR #12 — feat: add deterministic derived-dataset manifest core
  (merge commit `fa32976b67c05a3da0643335f172fe1742053bbe`)
- PR #13 — feat: add two-clock point-in-time sample assembly
  (merge commit `be9b286e0e206245d0e308128419ffbec16292c6`)
- PR #14 — chore: simplify Python CI matrix
  (merge commit `6a2fed0ec5ecc6432d532aee033ea4d36ab3a89c`)
- PR #15 — feat: add versioned feature and label spec contracts
  (merge commit `ed5cd526609348ae47e5a94af20c62b70af1a28e`)
- PR #16 — chore: add copyright holder to MIT license
  (merge commit `6f489124a5a1e770041f7b7d00183ab8a58a2e11`)
- PR #17 — feat: add chronological splits and actual-label-end purging
  (merge commit `8254de0d13015263c64ea18550ba4c86159d7eb5`)
- PR #18 — test: add leakage threat-model regression suite
  (merge commit `6d3e8d255f082fb8fef1324e87d18804d57d3ae1`)

## Released foundation

```text
Canonical
    → verified PIT assembly
    → versioned Feature/Label specs
    → chronological splits
    → actual-label-end purging
    → deterministic Dataset identity/manifest contracts
    → leakage regression
```

- Canonical market-bar builder core with audited-COMPLETE-only input gating.
- Immutable Canonical materialization with deterministic build identities.
- Strict verified Canonical artifact reader.
- Two-clock point-in-time sample assembly foundation.
- Versioned Feature/Label typed spec contracts.
- Chronological split foundation with actual-label-end purging.
- Deterministic Dataset schema/content/dataset identity and manifest core.
- Eight-threat leakage threat-model regression suite.
- MIT License with the M0DIAN copyright holder.

## Determinism and leakage controls

- Canonical business keys (`canonical_bar_key`) and physical row versions
  (`canonical_row_version_id`) are deterministic and free of request-level
  provenance fields.
- Market clock (`market_available_at`) and archive clock
  (`archive_available_at`) separate market observability from archive
  availability; `dataset_as_of` selects archive-time reproducibility.
- Half-open observation windows keep boundary rows leakage-safe.
- `adjustment = NONE` is the default and adjusted modes fail closed in PIT.
- Label completeness is explicit; labels never span trading days by default.
- Actual-label-end purge removes TRAIN/VALIDATION samples whose label end
  crosses the split boundary.
- Provenance pins (Canonical build pins, SourceSnapshot pins, SpecPins,
  Implementation pins) bind every dataset identity to its inputs.
- Spec/implementation drift is detected through content IDs and versioned
  identities.
- Eight stable leakage threats are pinned by the offline regression matrix.

## Offline validation before release-prep PR

Verified baseline before the release-preparation PR:

```text
Stable base: 6d3e8d255f082fb8fef1324e87d18804d57d3ae1
GitHub CI:   1139 passed on Python 3.11
             1139 passed on Python 3.14
             package job passed
compileall passed
repository hygiene passed
git diff --check passed
```

This is the baseline measured before the release-prep PR; the final test
count is whatever the release-prep PR's own CI run reports.

## Local release-prep validation

```text
Local environment: Python 3.14.4, PyArrow 25.0.0
Release-prep branch: 1157 passed / 2 skipped / 0 failed
Baseline 6d3e8d2:    1137 passed / 2 skipped / 0 failed
```

- The release-prep branch passes 20 more tests than the baseline commit
  under the same environment; those extra tests are the release-prep tests
  added by this PR.
- No new failures appeared and no previously passing test regressed.
- No PIT/leakage tests were modified, no tests were skipped or xfailed, and
  PyArrow is neither pinned nor downgraded.

## Historical PyArrow 24 environment note

- A previous local environment (Python 3.14.4, PyArrow 24.0.0) observed 113
  failures with the same signature
  (`pyarrow.lib.ArrowTypeError: Field interval has incompatible types:
  string vs dictionary<values=string, indices=int32, ordered=0>`) in known
  reader/PIT/leakage fixtures, caused by a local PyArrow dictionary-encoded
  partition/string schema merge difference.
- That difference did not reproduce in the current PyArrow 25.0.0
  environment; this is not the result of a code fix in this PR.
- The project keeps `pyarrow>=16` and does not pin a version for this.
- This historical record documents a previous local environment difference;
  it does not describe the current release-prep test result.

## Compatibility

- V0.3 CLI behavior is unchanged.
- V0.3 Raw/Curated data, the DuckDB catalog, and manifests are not migrated,
  overwritten, or repaired.
- V0.2 legacy `batch-<batch_key>.parquet` filenames remain supported.
- Canonical builds are new, independent immutable artifacts.
- No runtime ML dependency is added; `requires-python` remains `>=3.11`.

## Explicit boundaries

- No final Dataset builder orchestration.
- No Feature/Label value computation or transform execution.
- No Dataset Parquet writer and no Dataset CLI.
- PIT supports `adjustment = NONE` only; no adjusted-price corporate-action
  reconstruction.
- No cross-trading-day Label execution.
- No label-completeness inference.
- No authoritative per-date exchange session schedule.
- No automatic gap repair, synthetic OHLCV, interpolation, or forward fill.
- No ML training, inference, or backtest framework.
- No automatic trading.

v0.4.0 is the foundation for ML datasets; it cannot yet train models.

## Final release checklist

- [ ] PR-10 CI passes
- [ ] All GitHub offline tests pass
- [ ] release checker passes
- [ ] wheel/sdist build and twine check pass
- [ ] wheel installs in clean environment
- [ ] CLI version is 0.4.0
- [ ] package metadata version is 0.4.0
- [ ] README/CHANGELOG/release notes agree
- [ ] main working tree clean after merge
- [ ] Only then create v0.4.0 tag
- [ ] GitHub Release remains a separate explicit action
- [ ] PyPI publication remains a separate explicit action
