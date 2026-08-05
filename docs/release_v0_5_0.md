# MarketVault v0.5.0 Release Notes

## Release scope

```text
base tag: v0.4.0
v0.4.0 release merge/base: 1225b0ae0c96ef7a27b4eae92d676c65394ee85e
latest main after PR-9: 583db37b4f04014674a51b9908bf2409767fb291
PR-10 base (this branch): 583db37b4f04014674a51b9908bf2409767fb291

release version: 0.5.0
release date: 2026-08-05
```

## Merged development PRs

GitHub PR numbers (not the internal roadmap PR-1..PR-10 sequence):

- PR #20 — docs: plan v0.5.0 deterministic dataset builder
  (merge commit `3a1e5d3954514f20b44001ef3781851959f7e664`)
- PR #21 — feat: add transform implementation registry contracts
  (merge commit `6d05eafdeed03d52997cbd0c3aa3b9dd30ea0f3c`)
- PR #22 — feat: execute deterministic built-in feature transforms
  (merge commit `31ec13de0602a1eee9f725c887e107d0c9b77b4f`)
- PR #23 — feat: execute deterministic built-in label transforms
  (merge commit `b1b8581169c9e1c2e6040734c72eb9b6f079aebc`)
- PR #24 — feat: orchestrate deterministic dataset builds
  (merge commit `fe81774ce4d4cd49d728ce2d7d24e4a19d8d156c`)
- PR #25 — feat: materialize immutable dataset artifacts
  (merge commit `1aaed888add70619170c3f224e9e76ea7f409cba`)
- PR #26 — feat: add verified Dataset reader
  (merge commit `5210dba0699ef7608d86154bba46ddc64689f162`)
- PR #27 — feat: add Dataset CLI
  (merge commit `6c17ce130656ba343ce49690017e01a332b96744`)
- PR #28 — test: add end-to-end Dataset determinism and leakage regression
  (merge commit `583db37b4f04014674a51b9908bf2409767fb291`)

PR #28 was squash-merged into main on 2026-08-05; the resulting main HEAD
is `583db37b4f04014674a51b9908bf2409767fb291`, which is the base of the
PR-10 release-preparation branch.

## PR-10 release preparation status

PR-10 is the current release-preparation branch `release/v0.5.0` (commit
`chore: prepare v0.5.0 release`); it syncs the package version to 0.5.0 and
updates the README, CHANGELOG, release notes, direction document, release
checker, release tests, and CI package smoke. GitHub PR #29 is still
**OPEN** and **not merged**; the release-preparation branch has completed
its GitHub Actions validation with all three jobs successful — test
(3.11), test (3.14), and package. No `v0.5.0` tag exists, no GitHub
Release is published, and nothing is uploaded to PyPI: those remain
separate, explicit actions after PR-10 merges.

## Shipped architecture

The executable V0.5 pipeline connects the V0.4 contracts end to end:

```text
verified Canonical builds
    → PIT sample assembly
    → built-in Feature execution
    → built-in Label execution
    → label_status / actual_label_end_time
    → chronological split / purge
    → Dataset orchestration
    → immutable Dataset materialization
    → verified Dataset reader
    → Dataset CLI
```

- **Transform Implementation Registry** (PR-2): the sole resolution
  authority for `transform_ref`; exact v1 `module.path:function` lookup
  keys; frozen registration models; strict FeatureSpec/LabelSpec
  compatibility preflight; exact parameter-schema validation; versioned
  deterministic implementation fingerprints
  (`TRANSFORM_IMPLEMENTATION_FINGERPRINT_VERSION`) emitted as
  `ImplementationPin` entries.
- **Feature execution** (PR-3): pure in-memory execution over PIT-bound
  rows under the market/archive clocks; trailing-window contiguity,
  output-type, and finite-value validation; explicit COMPLETE / EXCLUDED
  result models.
- **Label execution** (PR-4): exact Feature-close anchor binding; BARS /
  FEATURE_CLOSE_ALIGNED alignment; real `label_status` with fixed reason
  codes; `actual_label_end_time` from the last actually consumed label row.
- **Orchestration** (PR-5): connects verified Canonical, PIT, Feature,
  Label, and Split/Purge; computes the authoritative logical schema, final
  logical rows under the fixed physical sort, CompletionSummary, merged
  ImplementationPins, `logical_dataset_content_id`, and the deterministic
  `dataset_id`.
- **Materialization** (PR-6): immutable Dataset build directories with
  explicit Parquet schema and writer options, `manifest.json`,
  `build_report.json`, spec artifacts, `_SUCCESS` written last, atomic
  no-overwrite rename, idempotent identical rebuilds, fail-closed
  conflicts and staging residue, and empty-Dataset materialization.
- **Verified Dataset reader** (PR-7): `load_verified_dataset(build_dir)`
  — the one public, read-only, fail-closed read path into a committed
  Dataset directory; never re-executes pipeline work, never scans for
  `latest`, never writes or repairs.
- **Dataset CLI** (PR-8): `dataset-build` / `dataset-verify` /
  `dataset-inspect` as a thin settings-independent wrapper over the formal
  public chain.
- **E2E regression** (PR-9): the seventeen fixed `E2E_*` regression IDs
  with positive controls and defenses tracked by a fixed coverage-matrix
  guard.

## Built-in Feature catalog

The eight built-in Feature transforms (immutable registrations,
`market_available_at <= feature_window_close` enforced by the PIT
contract):

```text
simple_return
log_return
rolling_mean
rolling_std
rolling_volume_mean
volume_ratio
candle_range
candle_body
```

## Built-in Label catalog

The four built-in Label transforms (BARS horizon,
FEATURE_CLOSE_ALIGNED only):

```text
forward_return
forward_direction
maximum_favorable_excursion
maximum_adverse_excursion
```

## Identity and determinism boundaries

- `dataset_id` is computed from the existing V0.4 identity contracts over
  the pinned inputs (verified Canonical pins, spec content hashes,
  implementation pins, scope, `dataset_as_of`, schema/format versions).
- The plan document, its path, `output_root`, `built_at`, CLI versions,
  JSON whitespace, and key order never enter any identity.
- No `latest`-directory scanning, no timestamped directories, no
  `built_at` in identity, no absolute output paths in identity.
- Identical pinned inputs produce identical logical content, identical
  `dataset_id`, and identical verification outcomes.
- Byte-identical Parquet is promised only with pinned PyArrow and writer
  options; without that pin, only the logical content contract holds.

## Materialized layout

Each final Dataset directory is named by the deterministic `dataset_id`
and contains exactly the whitelisted artifacts:

```text
<output_root>/<dataset_id>/
    dataset.parquet       # the sample matrix, fixed schema
    manifest.json         # versioned DatasetManifest (dataset_id recomputed)
    build_report.json     # recorded facts only, never identity-bearing
    feature_specs/        # one normalized spec file per FeatureSpec
    label_specs/          # one normalized spec file per LabelSpec
    split_spec.yaml       # normalized split spec content
    _SUCCESS              # marker written last, before the atomic rename
```

## Dataset CLI

```text
market-vault dataset-build --plan <PATH>
market-vault dataset-verify --build-dir <PATH>
market-vault dataset-inspect --build-dir <PATH> [--offset N] [--limit N]
```

- `dataset-build` accepts only `--plan`; every formal fact comes from the
  explicit, pinned, versioned build-plan JSON
  (`market-vault-dataset-build-plan-v1`).
- `dataset-verify` and `dataset-inspect` are strictly read-only.
- No settings, no OpenD, no network; relative plan paths are anchored to
  the plan file's parent; symlinks and junctions fail closed.

## Verification / fail-closed model

Every build ends with exactly one `load_verified_dataset` call on the
committed build path; SUCCESS is printed only when the
orchestration / materialization / reader `dataset_id` binding holds.
Corrupted, conflicting, or unexpected artifacts fail closed; a warning
that leads to a "seemingly successful" formal Dataset is forbidden.
`label_status: COMPLETE` is declared only when completeness is provable
from the actual label input rows; otherwise the label is INCOMPLETE and
excluded from TRAIN/VALIDATION/TEST by default. NaN and ±Infinity never
enter a final Dataset.

## E2E regression coverage

PR-9 pins seventeen `E2E_*` regression categories through final Dataset
rows and verified-reader results: future-feature leakage, archive cutoff,
incomplete labels, actual label end, cross-day rejection, split-crossing
purge, transform drift, spec drift, source snapshot substitution,
row/column order, staging crash residue, immutable conflict, rebuild
equivalence, corrupted Parquet, corrupted manifest, NaN/Infinity, and
timezone/DST — plus a full COMPLETE canary, a full EMPTY canary, and a
`dataset-build` -> `dataset-verify` -> `dataset-inspect` CLI
entry-combination canary.

## Compatibility

- V0.1-V0.4 CLI behavior is unchanged.
- Raw/Curated data, the DuckDB catalog, and manifests are not migrated,
  overwritten, or repaired.
- V0.4 Canonical builds, their readers, and all published identities are
  unchanged; existing manifests remain valid.
- The v0.4.0 Dataset identity core, its algorithms, and version constants
  are unchanged.
- `requires-python` remains `>=3.11`; runtime dependencies do not change.
- `adjustment = NONE` remains the default leakage-safe dataset policy.

## Known boundaries

- No arbitrary user transforms: only the fixed built-in registry executes;
  no YAML-imported modules, `eval`, `exec`, or dynamic callbacks.
- No cross-trading-day Label execution; a `TRADING_DAYS` Label horizon
  fails closed as unsupported.
- No adjusted-price PIT reconstruction (`adjustment = NONE` only).
- No automatic repair or re-collection of Raw/Curated/Canonical data at
  build time.
- No automatic sample generation; requests are explicit and never inferred
  from the scope.
- No `latest`-directory inference.
- No ML training, model selection, or hyperparameter tuning.
- No backtesting, walk-forward frameworks, or feature importance.
- No API server and no Python client.
- No automatic trading.

## Release validation

Local and GitHub Actions results are reported separately because
platform-dependent skips differ between Windows and Linux.

### Local validation

Verified on the PR-10 branch before opening the PR (Windows):

```text
Full offline pytest: 2226 passed, 11 skipped
Focused release tests: 93 passed
V0.5 key regressions: 1143 passed, 9 skipped
compileall: passed
repository hygiene: passed
git diff --check: passed
release checker: RELEASE_CHECK_OK version=0.5.0
CLI version: market-vault 0.5.0
wheel/sdist: market_vault-0.5.0-py3-none-any.whl and
             market_vault-0.5.0.tar.gz, both twine-checked
fresh-wheel install: module and distribution metadata assert 0.5.0
Dataset CLI help smoke: dataset-build / dataset-verify / dataset-inspect
public API smoke: V050_PUBLIC_API_IMPORT_OK
pip check: no broken requirements
wheel contents: WHEEL_CONTENTS_OK
```

### GitHub Actions validation

Verified on the release-preparation branch by the PR-10 CI workflow
(ubuntu-latest):

```text
test (3.11): 2230 passed, 7 skipped
test (3.14): 2230 passed, 7 skipped
package: success
    RELEASE_CHECK_OK version=0.5.0
    market-vault 0.5.0
    market_vault-0.5.0-py3-none-any.whl
    market_vault-0.5.0.tar.gz
    twine check: PASSED
    V050_PUBLIC_API_IMPORT_OK
    WHEEL_CONTENTS_OK
```

## Explicit non-actions

PR-10 does not create the `v0.5.0` tag, does not create a GitHub Release,
does not publish to PyPI, does not upload any package, and does not start
v0.5.1 or v0.6 work. Those remain separate, explicit actions after the
release PR merges.
