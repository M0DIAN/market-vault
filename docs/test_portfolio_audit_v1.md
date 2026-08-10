# Test Portfolio Audit v1 — MarketVault CI Test Portfolio & Duplication Analysis

**Type:** measurement / analysis only.
**Base tree audited:** `6ba8f055afbe0f018a1a8c935f77d53c2aa03db1` (main after PR #65).
**Primary CI evidence:** run `31368693999` (main FULL after PR #65), run `31367431272` (PR #65 FULL),
plus earlier FULL runs from the #59 profiling, #60 release-checker optimization, #61 reuse gate,
#62/#64 reuse canaries, and #63 lightweight closure series.
**Portfolio size at base (mechanically verified):** **3,737 collected tests across 51 unique
`tests/test_*.py` files** (3,730 passed + 7 environment-dependent skips per FULL environment;
`git ls-files "tests/test_*.py"` = 51 paths; `python -m pytest --collect-only -q` = 3737 collected).

**This document changes nothing.** No tests are deleted, skipped, or modified; no workflow, script,
product, release, or packaging file is touched. Every recommendation below is a proposal for a
future implementation PR and is labelled P0 / P1 / P2 accordingly.

---

## 1. Executive summary

1. **FULL CI currently executes ~3,737 tests up to three times per run** (Python 3.11 FULL, Python 3.14 FULL, PyArrow 24 FULL), plus a dedicated PyArrow-targeted surface and a frozen canonical/frozen regression surface inside the PyArrow job — 191 of the tests (10 targeted + 181 canonical/frozen) execute a fourth time per run.
2. **Measured FULL behavior at the base tree (run 31368693999):**
   - `test (3.11)`: whole job **4m53s** (pytest 262.90s)
   - `test (3.14)`: whole job **5m15s** (pytest 275.66s)
   - `portability-pyarrow24`: whole job **5m27s** (pytest 263.36s) — **wall-clock bottleneck**
   - `package`: **54s**, starts when the slowest of `test`/`portability` completes
   - workflow wall clock: **6m27s**; critical path = portability whole job + package tail
   - whole-job runner-seconds: **989** (293 + 315 + 327 + 54); pytest-only: **802**
3. **The largest single test-file hotspot is `tests/test_pit_sample_assembly.py` (~39–42s per environment)**, followed by `tests/test_release_v061.py` (~23–27s within the slowest-200 report, 452 tests), `tests/test_v060_integrated_e2e.py` (~10–11s), and the backfill / sample-generation-cli / audit clusters. The cost is per-test fixture construction (Parquet writes + DuckDB materialization + verified-build loading), **not** redundant assertions.
4. **Historical optimization precedent exists:** PR #60 replaced per-test subprocess invocations of `scripts/check_release.py` with an in-process checker harness and cut `test_release_v061.py` from **166–204s to 23–27s per environment (≈7–9×) with zero coverage loss**. That is the template for the P0 harness work proposed here.
5. **Runner variance is large and must bound all claims:** the same tree showed portability pytest at **263s (run 31368693999) vs 521s (run 31367431272)** and test 3.11 whole-job at **4m19s vs 7m36s** across near-identical trees. No single timing sample is stable truth.
6. **The PyArrow24 FULL duplicate is the highest-confidence topology-reduction candidate**, but its *net* runner saving is **not** the full 263s: the replacement PyArrow-sensitive subset costs non-zero time. Current estimate ≈ 195–215 whole-job runner-seconds (upper bound 263s), TBD pending a replacement-surface canary. Its *wall-clock* saving is small (~12–18s) because the critical path simply moves to Python 3.14 (§6, §8, §13).
7. **No `DELETE_CANDIDATE` recommendation is made anywhere.** All version-labelled files (`*_v02/v03/v051/v060/v061/v070`) protect currently promised contracts; none can be called obsolete from filename age alone. `test_options_v02.py` protects a *legacy snapshot format still read by current inventory* — backward compatibility, not dead code.
8. **Realistic safe targets (candidate hypotheses, not acceptance baselines):** control-plane PRs ≈ **2.5–3.5 minutes wall-clock** after P1 segmentation — a plausible design target from current component timings, **not yet an acceptance baseline** (the control-plane subset does not exist yet). Ordinary product FULL: measured baseline **6m27s wall-clock / 989 whole-job runner-seconds**; with P0+P1 materialized, an *estimated* ≈ **5m16–5m21s wall-clock / 590–640 runner-seconds (−35% to −40%)**, **TBD pending implementation canaries** — nothing is proven until a real subset is measured. Post-merge verified reuse (~13–24s jobs, run 31366165407) is a different metric and unchanged by this audit.
9. **Any CI topology change must be coordinated with `scripts/check_release.py`** — its regression tests (`test_release_v061.py`, `test_v061_ci_auditability.py`) pin the exact workflow shape (job names, step names, literal `run: python -m pytest` adjacency, PyArrow pin, action majors). This is the dominant false-optimization trap (§17).
10. **The V1 FULL attestation is a safety boundary (§10, §14, §17):** it may be created **only** when the PR actually ran the complete V1 FULL validation contract. A control-plane / compatibility / partial subset MUST NOT produce an artifact the V1 verifier can interpret as "FULL CI successfully completed" — for such subsets the attestation is SKIPPED and no V1 post-merge FULL reuse authorization may be derived. Future Partial Reuse V2 evidence from subsets requires a **separate evidence contract** that the V1 verifier can never accept.

---

## 2. Current CI topology

Single workflow `.github/workflows/ci.yml`, four formal jobs (`test` matrix 3.11/3.14, `portability-pyarrow24`, `package`). Trigger: push to `main`/`feature/**`, PRs to `main`. Read-only `permissions` (contents/pull-requests/actions).

**Per-job structure (FULL tier):**

| Job | Environment | Heavy steps (FULL tier) |
|---|---|---|
| `test` | 3.11, 3.14 (matrix, `fail-fast: false`) | checkout → tier classify → (main) reuse proof → whitespace → hygiene → install `.[dev]` → `compileall` → **`python -m pytest`** (`--durations=200`) |
| `portability-pyarrow24` | 3.11 | checkout → tier classify → (main) reuse proof → install `.[dev]` → **pin `pyarrow==24.0.0`** → assert version → **targeted: `test_v060_portability.py`** (10 tests) → **canonical/frozen surface: `test_canonical_reader.py` + `test_sample_generation_core.py` + `test_sample_generation_cli.py`** (181 tests) → **`python -m pytest` FULL** |
| `package` | 3.11, `needs: [test, portability-pyarrow24]` | checkout → tier classify → (main) reuse proof → install build tooling → **release checker (always)** → example help smokes → build wheel/sdist → twine check → fresh-venv wheel install + 8 CLI helps + version assertions → public-API import smokes → wheel-contents check → SHA256SUMS build/verify → artifact upload → attestation create/upload (PR FULL only) |

**Fast tiers (docs_fast / package_docs):** all three heavy guard groups skip; each job keeps checkout + classify + (whitespace/hygiene) + the release checker in `package` (with the #63 runtime bootstrap). Measured docs_fast / reuse-path jobs: **0m13s–0m24s** (runs 31366165407, 31361918221).

**Tier model (`scripts/ci_risk_tier.py`):** `docs_fast | package_docs | full`. Control-plane paths (`.github/workflows/`, `scripts/ci_risk_tier.py`, `scripts/audit_pr.py`, `ci/components.toml`, `pyproject.toml`) always force `full`; everything else except the docs scope is `full` (unknown → fail-closed full). **Today a `tests/**`-only PR and a `src/**`-only PR both run FULL ×3.** No component in `ci/components.toml` makes anything faster yet (foundation only).

**Duplicate-execution accounting (FULL):** the portability job executes `test_sample_generation_core.py` + `test_sample_generation_cli.py` (178 tests, 35.1s) as its frozen regression surface **and again** inside its FULL step; the targeted 10 tests also run in the FULL step. Every test in the suite runs three times per FULL (once per environment); **191 of them run a fourth time** (10 targeted + 181 canonical/frozen re-executed inside the portability FULL step).

---

## 3. Current test inventory

Source of truth (mechanically verified at the exact base): `git ls-files "tests/test_*.py"` → **51 unique files**; `python -m pytest --collect-only -q` → **3737 collected tests** (CI FULL confirms: 3,730 passed, 7 skipped — the skips are environment-dependent `pytest.skip` on symlink/junction/tzset availability, e.g. `test_canonical_materialization_v03.py`, `test_dataset_cli.py`, `test_dataset_end_to_end_regression.py`).

### 3.1 Exclusive primary clusters (every file in exactly one cluster)

| # | Primary cluster | Files | Tests | Share |
|---|---|---|---|---|
| 1 | Canonical bars | 4 (`canonical_builder_v03`, `canonical_materialization_v03`, `canonical_reader`, `chronological_splits`) | 280 | 7.5% |
| 2 | Dataset pipeline | 8 (`dataset_orchestration`, `dataset_materialization`, `dataset_cli`, `dataset_manifest_core`, `dataset_feature_execution`, `dataset_label_execution`, `dataset_transform_registry`, `feature_label_specs`) | 956 | 25.6% |
| 3 | Dataset verification & E2E regression | 2 (`verified_dataset_reader`, `dataset_end_to_end_regression`) | 331 | 8.9% |
| 4 | Dataset Catalog (v0.6.0) | 5 (`dataset_catalog_builder`, `dataset_catalog_cli`, `dataset_catalog_contract`, `dataset_catalog_materialization`, `dataset_catalog_reader`) | 294 | 7.9% |
| 5 | Sample generation (v0.6.0) | 3 (`sample_generation_core`, `sample_generation_cli`, `sample_generation_contract`) | 294 | 7.9% |
| 6 | PIT / leakage safety | 3 (`pit_sample_assembly`, `leakage_threat_model`, `snapshot_safety`) | 211 | 5.6% |
| 7 | Storage-era v03 contracts | 6 (`audit_v03`, `backfill_v03`, `calendar_v03`, `intraday_audit_v03`, `inventory_v03`, `timestamp_semantics_v03`) | 343 | 9.2% |
| 8 | Options legacy (v02) | 1 (`options_v02`) | 46 | 1.2% |
| 9 | Deprecation compatibility | 1 (`deprecation_compatibility_v051`) | 5 | 0.1% |
| 10 | Release / CLI / package contract | 2 (`release_v061`, `v061_cli_usability`) | 486 | 13.0% |
| 11 | Integrated acceptance & portability | 3 (`v060_integrated_e2e`, `v070_integrated_e2e`, `v060_portability`) | 70 | 1.9% |
| 12 | ArtifactClient (v0.7.0) | 4 (`v070_artifact_client_foundation`, `v070_artifact_client_catalog`, `v070_artifact_client_readers`, `v070_python_client_examples`) | 78 | 2.1% |
| 13 | Collectors / normalization / quality / SDK | 4 (`collector`, `normalization`, `quality`, `moomoo_sdk`) | 10 | 0.3% |
| 14 | CI control-plane | 5 (`ci_risk_tier`, `component_aware_tiers`, `ci_post_merge_reuse`, `audit_pr`, `v061_ci_auditability`) | 333 | 8.9% |
| **Total** | — | **51** | **3737** | 100.0%* |

\* Percentages rounded to 1 decimal place; file/test sums are exact. (Sum of displayed percentages is 100.1% due to rounding of rows 9 and 10; the count closure below is exact.)

**Inventory closure:**
```
UNIQUE TEST FILES = 51
COLLECTED TESTS    = 3737
Exclusive primary-cluster closure: sum(files) = 51, sum(tests) = 3737 — exact.
```

### 3.2 Non-exclusive analytical labels (overlap allowed; never summed)

Secondary lenses such as `CONTROL_PLANE`, `PYARROW_COMPATIBILITY`, `PACKAGE_CONTRACT`, `BACKWARD_COMPATIBILITY`, `PYTHON_COMPATIBILITY`, `CLI_CONTRACT`, `DATA_INTEGRITY` are **analytical labels that intentionally overlap** (e.g. `test_release_v061.py` is simultaneously release/package/backward-compat/CLI-relevant; `test_v061_ci_auditability.py` is both control-plane and package). They are applied per-file in §5 and are **not** a summable partition. Only the primary clusters in §3.1 may be summed, and they close exactly at 51 files / 3737 tests.

Non-test assets in `tests/`: `v060_acceptance_helpers.py` (imported acceptance helper — the release checker asserts it exists) and `tests/fixtures/` (frozen bundle; the release checker asserts its frozen generation id / plan sha do not change). Neither is a `test_*.py` collection unit.

---

## 4. Contract classification methodology

Each file is classified against the contract categories below using **static analysis** (module docstrings, imports, subprocess/CLI usage, fixture chains) plus **observed CI timing** (top-200 `--durations` reports across runs 31368693999, 31367431272, 31366165407-era, 31363971895, 31353223614, 31346375621).

**Current-contract test (mandatory for any possible-obsolete consideration):** *"If this test failed today, would we consider current MarketVault broken, or a currently promised compatibility contract violated?"* If yes → current test. No file fails this test at the base tree.

| Category | Meaning |
|---|---|
| `PRODUCT_CORE` | Validates shipped product behavior (canonical/dataset/catalog/sample pipelines, storage, normalization, quality, collectors). |
| `PRODUCT_INTEGRATION` | Full-chain / cross-layer behavior through real surfaces (CLI subprocess chains, example execution). |
| `DATA_INTEGRITY` | Determinism, identity hashes, point-in-time correctness, leakage isolation, audit invariants. |
| `PIT_LEAKAGE_SAFETY` | Point-in-time sample assembly and leakage threat model — high-value safety surface. |
| `CLI_CONTRACT` | CLI command/help/exit-code/version behavior. |
| `PACKAGE_CONTRACT` | Wheel/sdist contents, public API exports, lazy imports, example/doc guardrails. |
| `RELEASE_CONTRACT` | Release checker behavior and the release documentation/version/CI-policy invariants it enforces. |
| `CONTROL_PLANE` | CI workflow/classifier/reuse-gate/audit tooling behavior — no product surface. |
| `PYTHON_COMPATIBILITY` | Behavior plausibly varying with Python version (3.11 vs 3.14). |
| `PYARROW_COMPATIBILITY` | Behavior plausibly varying with PyArrow version (24 vs 25); includes direct `pyarrow` imports and Parquet write/read identity. |
| `BACKWARD_COMPATIBILITY` | Legacy formats/behavior still read or promised (v02 options snapshots, legacy batch-name snapshots, old release notes presence). |
| `LEGACY_NAMED_CURRENT_CONTRACT` | Version-labelled filename whose content is the *current* contract (v03 storage, v051 deprecation, v061 release, v070 client). |
| `POSSIBLE_OBSOLETE` | Not used at the base tree: every file protects a reachable current contract (see §11). |

**Recommendation states:** `KEEP_EVERY_FULL` · `KEEP_CURRENT` · `KEEP_COMPAT` · `TARGETED_ENV_ONLY` · `CONTROL_PLANE_ONLY` · `RUN_LESS_OFTEN` · `HARNESS_OPTIMIZE` · `RENAME_LEGACY_NAME` (later, not in this PR) · `DELETE_CANDIDATE` (none) · `NEEDS_MORE_EVIDENCE`.

**PyArrow sensitivity labels:** `direct` (imports `pyarrow` itself), `indirect` (exercises product code that writes/reads Parquet via pandas→pyarrow, e.g. `ParquetStore`/`Catalog`), `none` (no Arrow interaction beyond the fixture plumbing), `policy` (asserts the CI pin / wheel facts rather than exercising Arrow).

---

## 5. Per-file inventory matrix

All **51 files** appear exactly once, grouped by the §3.1 primary clusters. Test counts are the mechanically verified collected counts. Timing evidence = observed file totals within the top-200 `--durations` report (so *minimum* observed file cost; the full file cost is higher for files with many sub-0.3s tests). Runner: `3.11/3.14/PA24` = per-environment cost; variance across runs noted in §6.

### 5.1 Canonical bars (4 files, 280 tests)

| File | Tests | v-label | PyArrow | Py-ver | Ctrl-plane | Pkg/rel | Timing (top-200, 3.11) | Categories | Recommendation | Rationale |
|---|---|---|---|---|---|---|---|---|---|---|
| `test_canonical_builder_v03.py` | 60 | yes (v03) | indirect | possible | no | no | ~0.4–4.9s | PRODUCT_CORE, DATA_INTEGRITY, LEGACY_NAMED_CURRENT_CONTRACT | KEEP_EVERY_FULL | Current canonical build identity; v03 name is era label only. |
| `test_canonical_materialization_v03.py` | 78 | yes (v03) | **direct** | possible (symlink skips) | no | no | ~1.6–6.2s | PRODUCT_CORE, DATA_INTEGRITY, PYARROW_COMPATIBILITY | KEEP_EVERY_FULL | Parquet write identity; genuinely PyArrow-sensitive. |
| `test_canonical_reader.py` | 3 | no | **direct** | possible | no | no | 0.92s (targeted step) | PRODUCT_CORE, PYARROW_COMPATIBILITY | KEEP_CURRENT | Runs in portability targeted + FULL; tiny. |
| `test_chronological_splits.py` | 139 | no | none | possible | no | no | <0.3s each | PRODUCT_CORE, DATA_INTEGRITY | KEEP_EVERY_FULL | Pure pandas; fast. |

### 5.2 Dataset pipeline (8 files, 956 tests)

| File | Tests | v-label | PyArrow | Py-ver | Ctrl-plane | Pkg/rel | Timing (top-200, 3.11) | Categories | Recommendation | Rationale |
|---|---|---|---|---|---|---|---|---|---|---|
| `test_dataset_orchestration.py` | 145 | no | indirect | possible | no | no | ~0.9–1.7s | PRODUCT_CORE | KEEP_EVERY_FULL | |
| `test_dataset_materialization.py` | 143 | no | **direct** | possible | no | no | ~0.9–2.4s | PRODUCT_CORE, DATA_INTEGRITY, PYARROW_COMPATIBILITY | KEEP_EVERY_FULL | |
| `test_dataset_cli.py` | 148 | no | indirect | **yes** (junctions) | no | no | ~0.4–1.8s | CLI_CONTRACT, PRODUCT_CORE | KEEP_EVERY_FULL | Subprocess CLI; Windows-skip paths. |
| `test_dataset_manifest_core.py` | 128 | no | none | possible | no | no | <0.3s each | PRODUCT_CORE | KEEP_EVERY_FULL | |
| `test_dataset_feature_execution.py` | 119 | no | indirect | possible | no | no | ~1.0–1.6s | PRODUCT_CORE | KEEP_EVERY_FULL | |
| `test_dataset_label_execution.py` | 117 | no | indirect | possible | no | no | ~1.0–1.7s | PRODUCT_CORE | KEEP_EVERY_FULL | |
| `test_dataset_transform_registry.py` | 86 | no | none | possible | no | no | <0.3s each | PRODUCT_CORE | KEEP_EVERY_FULL | |
| `test_feature_label_specs.py` | 70 | no | none | possible | no | no | <0.3s each | PRODUCT_CORE, BACKWARD_COMPATIBILITY | KEEP_EVERY_FULL | |

### 5.3 Dataset verification & E2E regression (2 files, 331 tests)

| File | Tests | v-label | PyArrow | Py-ver | Ctrl-plane | Pkg/rel | Timing (top-200, 3.11) | Categories | Recommendation | Rationale |
|---|---|---|---|---|---|---|---|---|---|---|
| `test_verified_dataset_reader.py` | 235 | no | **direct** | **yes** (symlinks, tz) | no | no | ~0.9–1.7s | PRODUCT_CORE, PYARROW_COMPATIBILITY | KEEP_EVERY_FULL | |
| `test_dataset_end_to_end_regression.py` | 96 | no | **direct** | **yes** (tzset) | no | no | ~2.1–3.0s | PRODUCT_INTEGRATION, DATA_INTEGRITY | KEEP_CURRENT | Deep E2E; P2 candidate for redundancy review, not deletion. |

### 5.4 Dataset Catalog v0.6.0 (5 files, 294 tests)

| File | Tests | v-label | PyArrow | Py-ver | Ctrl-plane | Pkg/rel | Timing (top-200, 3.11) | Categories | Recommendation | Rationale |
|---|---|---|---|---|---|---|---|---|---|---|
| `test_dataset_catalog_builder.py` | 38 | no | indirect | possible | no | no | ~0.3–0.8s | PRODUCT_CORE, DATA_INTEGRITY | KEEP_EVERY_FULL | |
| `test_dataset_catalog_cli.py` | 85 | no | indirect | possible | no | no | ~2.9–3.2s | CLI_CONTRACT, PRODUCT_CORE | KEEP_EVERY_FULL | |
| `test_dataset_catalog_contract.py` | 84 | no | none | possible | no | **yes** | ~0.3s | PACKAGE_CONTRACT | KEEP_CURRENT | |
| `test_dataset_catalog_materialization.py` | 31 | no | indirect | possible | no | no | ~0.3s | PRODUCT_CORE, DATA_INTEGRITY | KEEP_EVERY_FULL | |
| `test_dataset_catalog_reader.py` | 56 | no | indirect | possible | no | no | ~0.3s | PRODUCT_CORE | KEEP_EVERY_FULL | |

### 5.5 Sample generation v0.6.0 (3 files, 294 tests)

| File | Tests | v-label | PyArrow | Py-ver | Ctrl-plane | Pkg/rel | Timing (top-200, 3.11) | Categories | Recommendation | Rationale |
|---|---|---|---|---|---|---|---|---|---|---|
| `test_sample_generation_core.py` | 99 | no | indirect | possible | no | no | ~3.7–4.3s | PRODUCT_CORE, DATA_INTEGRITY | KEEP_EVERY_FULL | Also runs in portability frozen surface (see §8). |
| `test_sample_generation_cli.py` | 79 | no | indirect | possible | no | no | ~6.2–8.7s | CLI_CONTRACT, PRODUCT_CORE | KEEP_EVERY_FULL | Subprocess + Parquet/DuckDB fixture chains; also in portability frozen surface. |
| `test_sample_generation_contract.py` | 116 | no | none | possible | no | **yes** | <0.3s each | PACKAGE_CONTRACT, RELEASE_CONTRACT | KEEP_CURRENT | Contract doc assertions, fast. |

### 5.6 PIT / leakage safety (3 files, 211 tests)

| File | Tests | v-label | PyArrow | Py-ver | Ctrl-plane | Pkg/rel | Timing (top-200, 3.11) | Categories | Recommendation | Rationale |
|---|---|---|---|---|---|---|---|---|---|---|
| `test_pit_sample_assembly.py` | 99 | no | **direct** | possible | no | no | **~38.9–42.0s (67 of 99 in top-200; ~0.58s each)** | PIT_LEAKAGE_SAFETY, DATA_INTEGRITY | **HARNESS_OPTIMIZE** | Biggest single-file hotspot; cost is per-test `tmp_path` fixture chains (Parquet writes + DuckDB catalog + materialize + verified-load), see §7/§11. |
| `test_leakage_threat_model.py` | 107 | no | indirect | possible | no | no | ~0.6–1.3s (was 18.2s pre-#60-era run contention) | PIT_LEAKAGE_SAFETY, DATA_INTEGRITY | KEEP_EVERY_FULL | High-value safety surface; already cheap. |
| `test_snapshot_safety.py` | 5 | no | indirect | possible | no | no | ~0.4–2.3s | BACKWARD_COMPATIBILITY, PIT_LEAKAGE_SAFETY | KEEP_COMPAT | Legacy snapshot must not silently change PIT results. |

### 5.7 Storage-era v03 contracts (6 files, 343 tests)

| File | Tests | v-label | PyArrow | Py-ver | Ctrl-plane | Pkg/rel | Timing (top-200, 3.11) | Categories | Recommendation | Rationale |
|---|---|---|---|---|---|---|---|---|---|---|
| `test_audit_v03.py` | 60 | yes (v03) | indirect | possible | no | no | ~4.6–6.2s | PRODUCT_CORE, DATA_INTEGRITY, LEGACY_NAMED_CURRENT_CONTRACT | KEEP_EVERY_FULL (later RENAME_LEGACY_NAME candidate) | Current audit contract; name is era label. |
| `test_backfill_v03.py` | 80 | yes (v03) | indirect | possible | no | no | ~6.5–7.4s | PRODUCT_CORE, DATA_INTEGRITY | KEEP_EVERY_FULL | |
| `test_calendar_v03.py` | 23 | yes (v03) | indirect | possible | no | no | ~0.8–1.6s | PRODUCT_CORE | KEEP_EVERY_FULL | |
| `test_intraday_audit_v03.py` | 129 | yes (v03) | indirect | possible | no | no | ~3.9–5.8s | PRODUCT_CORE, DATA_INTEGRITY | KEEP_EVERY_FULL | |
| `test_inventory_v03.py` | 34 | yes (v03) | indirect | possible | no | no | ~0.4–2.6s | PRODUCT_CORE, BACKWARD_COMPATIBILITY | KEEP_EVERY_FULL | Reads legacy v02 snapshots too (§11). |
| `test_timestamp_semantics_v03.py` | 17 | yes (v03) | indirect | **yes** (tz) | no | no | <0.3s each | PRODUCT_CORE, PYTHON_COMPATIBILITY | KEEP_EVERY_FULL | |

### 5.8 Options legacy v02 + deprecation compatibility (2 files, 51 tests)

| File | Tests | v-label | PyArrow | Py-ver | Ctrl-plane | Pkg/rel | Timing | Categories | Recommendation | Rationale |
|---|---|---|---|---|---|---|---|---|---|---|
| `test_options_v02.py` | 46 | yes (v02) | indirect | possible | no | no | ~1.9–3.1s | BACKWARD_COMPATIBILITY, LEGACY_NAMED_CURRENT_CONTRACT | KEEP_COMPAT | v02 snapshots still read by inventory; `test_release_v061` asserts v02 files are detected and **not** deleted by audits. |
| `test_deprecation_compatibility_v051.py` | 5 | yes (v051) | none | **yes** (NumPy behavior) | no | no | <0.3s | PYTHON_COMPATIBILITY, BACKWARD_COMPATIBILITY | KEEP_COMPAT | Pins the exact `filterwarnings` guard contract; may be NumPy-version sensitive. |

### 5.9 Release / CLI / package contract (2 files, 486 tests)

| File | Tests | v-label | PyArrow | Py-ver | Ctrl-plane | Pkg/rel | Timing (top-200, 3.11) | Categories | Recommendation | Rationale |
|---|---|---|---|---|---|---|---|---|---|---|
| `test_release_v061.py` | 452 | yes (v061) | **policy** (pin facts) | **yes** (subprocess CLI) | no | **yes** | ~23.2–27.6s (33 entries in top-200) | RELEASE_CONTRACT, CLI_CONTRACT, PACKAGE_CONTRACT, BACKWARD_COMPATIBILITY, LEGACY_NAMED_CURRENT_CONTRACT | KEEP_CURRENT; see §11 for per-group disposition | The authoritative regression for `scripts/check_release.py` and the workflow/release boundary. Post-#60 harness already cut it ~7–9×. |
| `test_v061_cli_usability.py` | 34 | yes (v061) | none | **yes** | no | no | <0.3s each | CLI_CONTRACT | KEEP_CURRENT | |

Note: `test_v061_ci_auditability.py` (40 tests) also pins release/CI-policy facts but is tabulated once, under its primary cluster §5.14 Control-plane; its `PACKAGE_CONTRACT`/`RELEASE_CONTRACT` labels are non-exclusive.

### 5.10 Integrated acceptance & portability (3 files, 70 tests)

| File | Tests | v-label | PyArrow | Py-ver | Ctrl-plane | Pkg/rel | Timing (top-200, 3.11) | Categories | Recommendation | Rationale |
|---|---|---|---|---|---|---|---|---|---|---|
| `test_v060_integrated_e2e.py` | 47 | yes (v060) | indirect | **yes** (subprocess) | no | no | ~9.8–11.1s (3 tests ≈ 3.7s each) | PRODUCT_INTEGRATION, CLI_CONTRACT | KEEP_CURRENT (RUN_LESS_OFTEN possible) | Genuine subprocess CLI E2E; expensive but real. |
| `test_v070_integrated_e2e.py` | 13 | yes (v070) | indirect | **yes** (subprocess) | no | no | ~0.9–1.0s | PRODUCT_INTEGRATION | KEEP_CURRENT | |
| `test_v060_portability.py` | 10 | yes (v060) | **direct** (runtime) | possible | no | no | 0.87s targeted | PYARROW_COMPATIBILITY | TARGETED_ENV_ONLY (keep in portability job; drop from 3.11/3.14 FULL) | Reads frozen PyArrow-25-produced fixtures under PyArrow 24 — only meaningful under the audited pin. |

### 5.11 ArtifactClient v0.7.0 (4 files, 78 tests)

| File | Tests | v-label | PyArrow | Py-ver | Ctrl-plane | Pkg/rel | Timing (top-200, 3.11) | Categories | Recommendation | Rationale |
|---|---|---|---|---|---|---|---|---|---|---|
| `test_v070_artifact_client_foundation.py` | 17 | yes (v070) | indirect | **yes** (import/sys.modules) | no | **yes** | ~0.5s | PACKAGE_CONTRACT, PRODUCT_CORE | KEEP_CURRENT | |
| `test_v070_artifact_client_catalog.py` | 16 | yes (v070) | indirect | possible | no | **yes** | ~0.3–1.1s | PRODUCT_CORE, PACKAGE_CONTRACT | KEEP_CURRENT | |
| `test_v070_artifact_client_readers.py` | 26 | yes (v070) | indirect | possible | no | **yes** | ~1.9–2.1s | PRODUCT_CORE, PACKAGE_CONTRACT | KEEP_CURRENT | |
| `test_v070_python_client_examples.py` | 19 | yes (v070) | indirect | possible | no | **yes** | <0.3s each | PACKAGE_CONTRACT | KEEP_CURRENT | |

### 5.12 Collectors / normalization / quality / SDK (4 files, 10 tests)

| File | Tests | v-label | PyArrow | Py-ver | Ctrl-plane | Pkg/rel | Timing | Categories | Recommendation | Rationale |
|---|---|---|---|---|---|---|---|---|---|---|
| `test_collector.py` | 1 | no | none | possible | no | no | <0.3s | PRODUCT_CORE | KEEP_EVERY_FULL | Tiny. |
| `test_normalization.py` | 2 | no | none | possible | no | no | <0.3s | PRODUCT_CORE | KEEP_EVERY_FULL | Tiny. |
| `test_quality.py` | 1 | no | none | possible | no | no | <0.3s | PRODUCT_CORE | KEEP_EVERY_FULL | Tiny. |
| `test_moomoo_sdk.py` | 6 | no | none | possible | no | no | <0.3s | PRODUCT_CORE | KEEP_EVERY_FULL | Tiny. |

### 5.13 Control-plane (5 files, 333 tests)

| File | Tests | v-label | PyArrow | Py-ver | Ctrl-plane | Pkg/rel | Timing | Categories | Recommendation | Rationale |
|---|---|---|---|---|---|---|---|---|---|---|
| `test_ci_risk_tier.py` | 17 | no | none | possible | **yes** | no | <0.3s each | CONTROL_PLANE | CONTROL_PLANE_ONLY | Tiny git-repo fixtures, seconds-range by design. |
| `test_component_aware_tiers.py` | 19 | no | none | possible | **yes** | no | ~0.7–0.8s | CONTROL_PLANE | CONTROL_PLANE_ONLY | |
| `test_ci_post_merge_reuse.py` | 241 | no | none | possible | **yes** | no | <0.3s each (122 fns + params) | CONTROL_PLANE | CONTROL_PLANE_ONLY | Verifier proof/attestation logic; no product surface. |
| `test_audit_pr.py` | 16 | no | none | possible | **yes** | no | <0.3s each | CONTROL_PLANE | CONTROL_PLANE_ONLY | |
| `test_v061_ci_auditability.py` | 40 | yes (v061) | policy | possible | **yes** | **yes** | <0.3s each | CONTROL_PLANE, PACKAGE_CONTRACT, RELEASE_CONTRACT | CONTROL_PLANE_ONLY (+ package closure) | Pins workflow majors/matrix/job count/artifact chain; also release/package facts (non-exclusive labels). |

**Aggregate:** 333 control-plane tests (333 / 3737 = 8.9%) currently execute in FULL ×3 with zero product-surface value; they were explicitly designed ("stay in the seconds range") for focused execution.

---

## 6. Critical-path analysis (run 31368693999, main FULL after PR #65)

**Whole-job durations (started → completed):**

| Job | Start | End | Whole-job | pytest (FULL step) | Job overhead beyond pytest |
|---|---|---|---|---|---|
| `test (3.11)` | 08:07:36 | 08:12:29 | **4m53s** | 262.90s | ~30s (checkout/setup/classify/install/compile) |
| `test (3.14)` | 08:07:37 | 08:12:52 | **5m15s** | 275.66s | ~39s |
| `portability-pyarrow24` | 08:07:36 | 08:13:03 | **5m27s** | 263.36s | ~64s (incl. PyArrow pin install ~15s, targeted 0.87s, canonical/frozen surface ~36s) |
| `package` | 08:13:06 | 08:14:00 | **0m54s** | — | — |

**Workflow wall clock:** 08:07:33 → 08:14:00 = **6m27s**. Whole-job runner-seconds: 293 + 315 + 327 + 54 = **989**.

**Critical path:** `portability-pyarrow24` whole job (5m27s) is the *slowest* of the three test jobs and is the last dependency of `package` (`needs: [test, portability-pyarrow24]`; both `test` jobs finished by 08:12:52, portability at 08:13:03 — portability gates the package start). Critical path = portability 5m27s + package 54s + ~6s scheduling slack = **6m27s**. The wall-clock bottleneck surface is the **portability-pyarrow24 whole job**.

**Why portability is the bottleneck — and what removing its FULL would do:**

- The portability job's FULL pytest (263.36s) is *not* slower than the others (3.14: 275.66s; 3.11: 262.90s). The job wins the bottleneck only by its extra steps: PyArrow pin install, the 10-test targeted step (0.87s), and the canonical/frozen regression surface (**35.10s** for 178 tests that run *again* in its FULL step). The FULL step itself executes the **same test suite selection as the 3.11 job, under a deliberately different dependency environment** (PyArrow 24 pinned vs ambient) — that difference is the job's purpose, and the same-selection point is why most of its pytest duration is duplicative of 3.11.
- **If the portability FULL duplicate were removed** (keeping the targeted + canonical/frozen surface and adding the PyArrow-sensitive subset of §8.1), the portability job would shrink to ≈ 116–131s (overhead ~30s + targeted 0.87s + frozen 35.10s + sensitivity subset ≈ 50–65s, all estimated), and the critical path would move to **`test (3.14)` whole job (5m15s) + package (54s) ≈ 6m09s**. The wall-clock saving is **≈ 12–18s**, not the full 263s of its pytest duration. Claiming the latter would be wrong.
- The runner-minute saving is real: the gross saving is the FULL step's ~263–299s of pytest (including its duplicate execution of the targeted + frozen tests), but the **net** saving subtracts the replacement sensitivity subset's runtime — estimated **≈ 195–215 whole-job runner-seconds, upper bound 263s, TBD pending a replacement-surface canary** (those minutes are charged on a third runner that currently runs a suite selection substantially overlapping 3.11's).

**Comparable full-run snapshots (whole jobs) across the evidence set:**

| Run | Context | test 3.11 | test 3.14 | portability | package |
|---|---|---|---|---|---|
| 31346375621 | PR #59 (pre-#60) | 9m24s | 10m43s | 11m29s | 1m04s |
| 31347409816 | main #59 (pre-#60) | 9m24s | 10m28s | 10m15s | 0m55s |
| 31352080511 | PR #60 | 4m46s | 5m25s | 6m04s | 0m48s |
| 31353223614 | main #60 | **7m36s*** | 4m57s | 5m36s | 0m57s |
| 31358275770 | main #61 | 4m42s | 5m14s | 5m35s | 0m56s |
| 31360715033 | PR #62 canary | 4m47s | 5m07s | 5m29s | 0m53s |
| 31363121627 | PR #63 | 4m59s | 5m02s | 5m26s | 0m56s |
| 31363971895 | main #63 | 4m58s | 5m16s | 5m34s | 0m52s |
| 31364943183 | PR #64 canary-2 | 5m11s | 5m00s | 5m37s | 1m01s |
| 31367431272 | PR #65 | 4m19s | 5m14s | **10m01s*** | 1m05s |
| **31368693999** | **main #65 (primary)** | **4m53s** | **5m15s** | **5m27s** | **0m54s** |

`*` contended-runner outliers (3.11 7m36s; portability 10m01s) — same-era trees. Post-#60 typical FULL: 3.11 4m19–5m11, 3.14 4m57–5m25, portability 5m26–6m04, package 0m45–1m05. **Portability is the usual wall-clock bottleneck; 3.14 is the second; both are runner-variance-adjacent.**

**Fast paths for contrast (not the same metric as PR/control-plane FULL):**
- Post-merge verified reuse (run 31366165407, `POST_MERGE_REUSE=true`, reason `verified_full_pr_tree_equivalence`): jobs 0m13–0m24s.
- docs_fast (run 31361918221, pre-#63 — package release checker failed; fixed by #63): jobs 0m08–0m13s.

---

## 7. Top runtime hotspots

Per-file totals *within the top-200 slowest report* (3.11, run 31368693999; cross-run ranges below). These are lower bounds of file cost — the tail beyond the report is sub-0.3s per test.

| Rank | File | Top-200 sum | Cost shape |
|---|---|---|---|
| 1 | `test_pit_sample_assembly.py` | **38.9–42.0s** (67–68 entries, ~0.58s each) | Per-test `tmp_path` fixture chains: Parquet snapshot writes (`write_snapshot` → `ParquetStore`), DuckDB catalog refresh, `materialize_canonical_market_bars`, `load_verified_canonical_build` re-verification, then the PIT `assemble`. Every test rebuilds the world. |
| 2 | `test_release_v061.py` | **23.2–27.6s** (33 entries) | Subprocess CLI checks (0.58–1.8s each: `each_subcommand_help_parses[×15+]`, `cli_version_*`, `help_and_version_do_not_construct_collectors` 1.79s, `dataset_cli_helps_do_not_require_settings` 1.77s) + end-to-end `run_check_release(ROOT)` (0.66–0.87s). Mutation tests are already in-process post-#60. |
| 3 | `test_v060_integrated_e2e.py` | **9.8–11.1s** (3 entries) | Three real subprocess CLI chains through all six commands (~3.5–3.7s each) — genuine integration work. |
| 4 | `test_backfill_v03.py` | **6.5–7.4s** | DuckDB + Parquet fixture chains per test (~0.36–0.63s each; 17–21 entries). |
| 5 | `test_sample_generation_cli.py` | **6.2–8.7s** | Subprocess CLI E2E (1.3s each) + Parquet/DuckDB fixture construction. |
| 6 | `test_audit_v03.py` | **4.6–6.2s** | DuckDB view/status computation per test (~0.3–0.6s each). |
| 7 | `test_intraday_audit_v03.py` | **3.9–5.8s** | DuckDB intraday gap/overlap work (129 tests; ~0.3–0.45s each). |
| 8 | `test_sample_generation_core.py` | **3.7–4.3s** | Canonical + generation fixture chains (~0.3s each). |
| 9 | `test_dataset_catalog_cli.py` | **2.9–3.2s** | CLI subprocess + catalog fixtures. |
| 10 | `test_dataset_end_to_end_regression.py` | **2.1–3.0s** | Full-chain determinism; setup-heavy (1.18s setup on one). |
| 11 | `test_v070_artifact_client_readers.py` | **1.9–2.1s** | Reader fixture chains. |
| 12 | `test_leakage_threat_model.py` | **0.6–1.3s** (107 tests) | Cheapest high-value safety surface; per-test duckdb/catalog fixtures. |

**Diagnosis per required axis (§9 of the brief):**
- Subprocess cost: real and dominant in `release_v061` CLI group, `v060_integrated_e2e`, `sample_generation_cli`, `dataset_catalog_cli`. For `release_v061` it is *already minimized* by #60; remaining subprocess tests are the CLI-behavior surface (must exercise the real CLI) — legitimate.
- Repeated filesystem fixture construction: dominant in `pit_sample_assembly` (every test rebuilds snapshots + catalog + materialized builds in a fresh `tmp_path`), `backfill_v03`, `audit_v03`, `intraday_audit_v03`. The PIT case is the one with a clear optimization path (shared immutable base builds, mutations applied per test — the same pattern #60 applied to the checker: same assertions, cheaper fixture/harness).
- Parquet writes: present in every data-pipeline file; small per write, additive across ~800 fixture chains. PIT is the aggregate champion.
- DuckDB work: the catalog refresh + materialization queries are the second leg of the PIT/backfill/audit cost.
- Repeated immutable-build generation: `pit_sample_assembly` rebuilds canonical builds per test; `sample_generation_core/cli` rebuild generation chains per test; `verified_dataset_reader`/`end_to_end_regression` share helpers but still rebuild per test.
- Repeated checker mutation/copy: `release_v061` still `copy_repo`s the whole tree per mutation test (`shutil.copytree` of the repo minus caches) — ~0.1–0.2s each across ~150+ mutation tests. Further optimization possible (rsync-style or sparse copy, or in-place single copy per session).
- Pure CPU: negligible — no single test exceeds ~4s wall.
- Genuinely necessary integration work: `v060_integrated_e2e` (real CLI ×6), `v070_integrated_e2e` (example execution against a real chain), `dataset_end_to_end_regression` (full-chain determinism), PIT assembly (the safety assertions themselves).

**Variance guard:** PR #65's portability run showed PIT at 111.6s and backfill at 39.2s (≈2–3× their typical) under runner contention, while the same tree's 3.11 showed 34.8s for PIT. All hotspot claims above use the cross-run typical range, not single samples.

---

## 8. PyArrow24 duplication analysis

**Current PyArrow24 job execution order (FULL tier):** pin `pyarrow==24.0.0` → assert version → targeted `test_v060_portability.py` (10 tests, 0.87s) → canonical/frozen surface `test_canonical_reader.py` (3) + `test_sample_generation_core.py` (99) + `test_sample_generation_cli.py` (79) = 35.10s → **FULL `python -m pytest` (3,730 tests, 263.36s)**.

**Direct `pyarrow` importers (static scan):** `test_canonical_materialization_v03.py`, `test_canonical_reader.py`, `test_dataset_end_to_end_regression.py`, `test_dataset_materialization.py`, `test_pit_sample_assembly.py`, `test_verified_dataset_reader.py`, `test_release_v061.py` (policy-only: asserts the pin and wheel facts, not Arrow behavior).

**Indirect (via product Parquet I/O — `ParquetStore` uses `df.to_parquet(..., compression="zstd")`, pandas default engine = pyarrow):** every data-pipeline file that constructs fixtures: dataset catalog suite, sample generation suite, backfill/audit/calendar/intraday/inventory/timestamp suite, options_v02, snapshot_safety, leakage_threat_model, moomoo fixtures.

**Genuinely PyArrow-version-sensitive (write/read identity may change across 24↔25):** canonical builder/materialization/reader, verified dataset reader, dataset materialization, PIT assembly (reads materialized builds), sample generation (fixture identity chains), v060_portability (frozen PyArrow-25 artifacts read under 24). This is exactly the surface already selected for the portability job's targeted + frozen steps.

**No meaningful Arrow interaction:** all five control-plane files, `deprecation_compatibility_v051`, `normalization`, `quality`, `collector`, `moomoo_sdk`, `feature_label_specs`, `transform_registry`, `chronological_splits`, `feature/label_execution`, `manifest_core`, `orchestration`, `dataset_cli` (mostly), `v061_cli_usability`, `v070_python_client_examples` (fixture plumbing only).

### 8.1 Proposed retained PyArrow24 surface inventory (design only — NOT implemented here)

For every file that would remain in the narrowed PyArrow24 job, origin tag:

| Tag | Origin | Files (count) |
|---|---|---|
| A | existing targeted surface | `test_v060_portability.py` (10) |
| B | existing frozen surface | `test_canonical_reader.py` (3), `test_sample_generation_core.py` (99), `test_sample_generation_cli.py` (79) → 181 |
| C | newly retained sensitivity subset | `test_canonical_materialization_v03.py` (78), `test_canonical_builder_v03.py` (60), `test_dataset_materialization.py` (143), `test_verified_dataset_reader.py` (235), `test_pit_sample_assembly.py` (99), `test_dataset_end_to_end_regression.py` (96) → 711 |

**Deduplicated retained test count under PyArrow24: 10 + 181 + 711 = 902** (vs 3,737 in the current FULL step). The **unique replacement test count is 711** (tag C). No file appears under two tags; tags A and B are already executed in the portability job today, so the only *new* runtime added by the change is tag C.

**Runtime estimate for tag C** (from the §7 top-200 window, lower bounds): materialization_v03 1.6–6.2s + builder_v03 0.4–4.9s + dataset_materialization 0.9–2.4s + verified_reader 0.9–1.7s + pit_sample_assembly 38.9–42.0s + end_to_end_regression 2.1–3.0s ≈ 45–60s; full-file cost is higher for the files with sub-0.3s tails, so a conservative planning figure is **≈ 50–65s**. Exact value unmeasured.

### 8.2 Quantified expectations (per FULL, estimated unless noted)

- **Runner seconds (net):** current FULL step 263.36s (pytest) minus the retained surfaces already inside it (targeted 0.87s + frozen 35.10s are *still run*, now only once) and minus tag C (≈ 50–65s) → net saving ≈ **198–213s of pytest; whole-job ≈ 195–215s (327 → ≈ 116–131s)**. **Upper bound 263s** (achievable only if the replacement subset cost zero, which it does not). **TBD pending a replacement-surface canary.**
- **Wall clock:** **−12–18s** (critical path moves to `test (3.14)` at 5m15s + package; §6). Stated explicitly: **removing the PyArrow FULL does NOT save its 263s from wall-clock**; the wall-clock ceiling is the 3.14 job afterwards.
- **Rollback/fail-closed:** the change is a step-set change in `portability-pyarrow24`; the release checker's workflow-shape tests must be updated in the same PR (they currently pin the FULL step's literal adjacency). If the narrowed surface fails, revert the step-set; the other two FULL jobs were unaffected.

---

## 9. Python 3.14 compatibility analysis

`requires-python = ">=3.11"` — 3.14 is a real, promised product contract, and its FULL job passes today (275.66s). Treating 3.14 as higher-risk than PyArrow narrowing is correct: modern-Python compatibility is a supported-surface promise.

**Observed 3.14-vs-3.11 delta at the base tree:** pytest 275.66s vs 262.90s (+4.9%); per-file deltas are within noise (±1s per file) except `release_v061` (+3.2s) and `pit_sample_assembly` (+1.5s). The 3.14 FULL adds ~13s of pytest over 3.11.

**Plausibly Python-version-sensitive surfaces (with file evidence):**
- Syntax/import: `v070_artifact_client_*` lazy-import guarantees (`sys.modules` assertions), `release_v061` version/import tests.
- pathlib/filesystem: `dataset_cli` (junction/symlink paths), `canonical_materialization_v03` (symlink skips), `verified_dataset_reader` (symlink relocation), `v061_cli_usability`.
- datetime/timezone: `timestamp_semantics_v03`, `intraday_audit_v03`, `calendar_v03`, `pit_sample_assembly` (two-clock), `dataset_end_to_end_regression` (`time.tzset`).
- subprocess/CLI: `release_v061` CLI group, `v060_integrated_e2e`, `sample_generation_cli`, `dataset_cli`, `dataset_catalog_cli`, `v070_integrated_e2e`, control-plane classifiers.
- serialization/identity: every hashlib-bearing data file (hash stability across Python versions is a real contract).
- packaging/public API: `release_v061` version/`__all__` assertions, `v070_python_client_examples`, wheel-import behavior.
- dependency interaction: `deprecation_compatibility_v051` (NumPy generic-timedelta), pandas/duckdb/pyarrow binary-wheel behavior on 3.14.

### 9.1 Three separate quantities (job-local vs runner-minutes vs workflow wall-clock)

The 3.14 FULL reduction must be reported as three distinct metrics. All figures are estimates pending a canary; scenario-relative wording only.

- **A. Job-local duration reduction (3.14 whole job, 315s → ≈ 190–215s):** **−100 to −125s** — the 3.14 job's own duration shrinks by the runtime of the dropped non-sensitive bulk (see the proposed surface below).
- **B. Runner-minute reduction:** **−100 to −125s per FULL** — the 3.14 runner is charged for exactly the job-local reduction; no other runner is affected.
- **C. Whole-workflow critical-path reduction:** scenario-relative:
  - CURRENT: `max(3.11 ≈ 293, 3.14 ≈ 315, portability ≈ 327) + package ≈ 54` → wall ≈ 6m27s.
  - AFTER P0-1 (portability removed from the critical path): `max(3.11 ≈ 293, 3.14 ≈ 315, narrowed portability ≈ 116–131) + 54` → wall ≈ 6m09s; **3.14 is now the max**.
  - AFTER P0-1 + P1-1: `max(3.11 ≈ 293, narrowed 3.14 ≈ 190–215, portability ≈ 116–131) + 54` → wall ≈ 5m47s → **workflow reduction ≈ −22s (bounded; 3.11 becomes the max)**.
  - **Once 3.11 becomes the max, further 3.14 reductions save runner-minutes but NOT workflow wall-clock.** If portability were still the bottleneck (P0-1 not applied), shrinking 3.14 would produce **zero** workflow improvement.
  - Exact values TBD pending canary; the workflow gain is bounded by the gap between 3.14 and 3.11 (≈ 22s) plus the 3.11-vs-3.14 delta after narrowing — do not infer a 100–125s workflow gain from the 100–125s job-local gain.

**Analysis of A (FULL forever) vs B (compatibility surface):** the set of plausibly-sensitive files covers most of the suite by count, but by *value* the FULL triple-run's marginal gain on 3.14 is the ~5%-slower re-execution of behavior already proven on 3.11, plus genuine 3.14-only risk concentrated in the surfaces above. A defensible 3.14 surface is: **all of the above sensitivity families + the release/package contract + one representative deep E2E (`v060_integrated_e2e` or `dataset_end_to_end_regression`) + PIT/leakage safety** — roughly 60–70% of tests by count but *all* version-sensitive families, dropping the redundant non-sensitive bulk (`chronological_splits`, `transform_registry`, `manifest_core`, catalog contract/docs, most of `sample_generation_contract`, etc.).

**Guardrail (per the brief):** do not narrow 3.14 without a replacement compatibility surface. The P2 proposal (§15) is exactly that: a named compatibility suite, not an ad-hoc drop. 3.14 must also keep executing the release checker contract — `test_release_v061`'s version/CLI/package assertions are part of the packaging contract on modern Python.

---

## 10. Control-plane segmentation analysis

**Control-plane files** (5): `test_ci_post_merge_reuse.py` (241), `test_v061_ci_auditability.py` (40), `test_ci_risk_tier.py` (17), `test_component_aware_tiers.py` (19), `test_audit_pr.py` (16) = **333 tests** (333 / 3737 = 8.9%); plus `test_release_v061.py`'s CI-shape/checker-self-test groups (§11/§12; ~40–60 of its 452).

**Forward question — should a normal product-code PR execute these under 3.11, 3.14, and PyArrow24?** No. None of them touches a product surface, reads a Parquet file, or executes product code beyond `market_vault` import paths that the product FULL already exercises. Distinct safety value per environment is ≈ zero (they pass in 0.1–0.8s per env today because they are pure control-plane logic). Minimum environments with distinct value: **one** (3.11, the CI runtime).

**Inverse question — does a CI/control-plane-only PR need every expensive PIT/dataset/intraday product regression under 3 environments?** No. The control-plane change surface (`ci.yml`, `scripts/`, `ci/components.toml`, classifier) is validated by the control-plane suite + the release checker; the product regression FULL adds no signal to a workflow-only change. But the release checker contract itself must still run on every tier (it validates docs/package/version state — that is tier-independent and already unconditional).

### 10.1 V1 FULL-attestation boundary (safety rule)

- The **V1 FULL CI attestation may be created ONLY when the PR actually ran the complete V1 FULL validation contract** (FULL pytest on Python 3.11, Python 3.14, and PyArrow 24, plus the full package chain) and all of it passed.
- **CONTROL-PLANE SUBSET:** the release checker remains authoritative; **V1 FULL CI attestation = SKIPPED**; **no V1 post-merge FULL reuse authorization may be derived from that subset** — the subset's results are validation evidence for the subset only.
- If future **Partial Reuse V2** needs evidence from such a subset, it requires a **SEPARATE evidence contract**: a different schema, a different artifact name/type, per-surface identity, and a consumer that cannot be confused with the V1 FULL attestation.
- **A V2 surface-evidence artifact MUST NOT be accepted by the V1 FULL reuse verifier.** (This is the current-state contract already: `POST_MERGE_REUSE=true` is only granted on a PR that produced a verified FULL attestation; a subset run must never satisfy that predicate.)

### 10.2 Proposed fail-closed segmentation policy (P1, design only)

1. **Control-plane tier** (changed paths ⊆ control-plane surface): run the 5 control-plane files + `test_release_v061` checker-self-test/CI-shape subset + release checker, on 3.11 only; the `package` job runs its release-checker tail. **V1 FULL attestation = SKIPPED** (§10.1); if the post-merge verifier predicates require a FULL attestation for the branch, the control-plane PR either (a) continues to require a prior verified FULL attestation from a product FULL, or (b) ships the separate V2 evidence contract before any reuse participation is claimed.
2. **Product tier** (changed paths ⊆ `src/`, `tests/`): full current behavior (FULL ×3 + package) — unchanged.
3. **Unknown/mixed**: fail closed to full (current classifier default).
4. Any unset/unknown `CI_TIER` keeps every heavy guard true (current fail-closed behavior) — preserved verbatim.

**Realistic control-plane wall clock (candidate target, not acceptance baseline):** control-plane subset ≈ 333 tests + checker subset, all "seconds-range" design ≈ **60–120s** of pytest on 3.11 + package tail ≈ 54s + overhead ≈ **2.5–3.5 minutes total** — a plausible design target from current component timings, **not yet an acceptance baseline** (the actual control-plane subset does not exist; measure it before promising the number).

---

## 11. Version-labelled / legacy contract audit

Every version-labelled file, with its actual current contract:

| Historical name | Actual current contract today | Verdict |
|---|---|---|
| `test_options_v02.py` | Legacy v02 options snapshot format is **still read** by current inventory; `test_release_v061` asserts v02 files are detected by inventory and **not deleted** by audits. Release checker guards the v02 leg. | **KEEP_COMPAT** — backward compatibility, not obsolete. |
| `test_deprecation_compatibility_v051.py` | NumPy generic-timedelta deprecation guard matching the live `filterwarnings` policy; public functions must keep the exact warning-free behavior. | **KEEP_COMPAT** — active dependency-compat contract. |
| `test_audit_v03.py` / `test_backfill_v03.py` / `test_calendar_v03.py` / `test_intraday_audit_v03.py` / `test_inventory_v03.py` / `test_timestamp_semantics_v03.py` | The **current** storage/audit/calendar/backfill contracts (v0.3-era surface, still the shipped behavior; nothing replaced them). | **KEEP** — possibly `RENAME_LEGACY_NAME` later (not in this PR). |
| `test_canonical_builder_v03.py` / `test_canonical_materialization_v03.py` | The **current** canonical build/materialization contract (identity, schema, Parquet). | **KEEP** — same as above. |
| `test_release_v061.py` | The **current** release-checker + CLI + package + docs-version contract (v0.7.0 state enforced). | **KEEP** — possibly split later (§12); never call obsolete from the name. |
| `test_v061_ci_auditability.py` / `test_v061_cli_usability.py` | Current workflow-shape pin and CLI wording freeze. | **KEEP** (control-plane grouping only). |
| `test_v060_integrated_e2e.py` / `test_v060_portability.py` | Current v0.6 integrated acceptance and PyArrow-24/25 static portability. | **KEEP** (TARGETED_ENV_ONLY for portability). |
| `test_v070_*` (4 files) | Current v0.7.0 ArtifactClient + example contracts. | **KEEP**. |

**`test_release_v061.py` — v061 special review (§10 of the brief).** Conceptual groups and disposition:

| Group | Examples (count) | Must stay authoritative? | Notes |
|---|---|---|---|
| Release-checker mutation/invariant tests | `release_checker_fails_on_*` / `_fails_when_*` (~250) | **Yes** | The authoritative regression for `scripts/check_release.py`. Post-#60 they are in-process (fast). They must run whenever `scripts/check_release.py` / workflow / release policy changes — and currently run in every FULL ×3. |
| CLI help/version current behavior | `cli_version_output`, `cli_version_exit_zero`, `each_subcommand_help_parses` (~20) | **Yes** | Real subprocess CLI contract; ~0.58–1.8s each (the file's remaining expensive block). |
| Lazy import / public API guarantees | `import_does_not_load_moomoo`, `import_does_not_load_duckdb`, `v061_public_api_imports_succeed`, `market_vault_remains_lazy` | **Yes** | Packaging contract; must also run on 3.14 (modern-Python packaging promise). |
| Version / pyproject / README / changelog / release-notes assertions | `pyproject_version`, `readme_title_is_v070`, `changelog_contains_061` (~80) | **Yes** | The release documentation state machine; the checker enforces the same facts — these are defense-in-depth at a different layer (pytest in-process vs checker subprocess). |
| Historical-only assertions | `changelog_still_contains_060/051/050/040`, `release_notes_v051_exist`, `release_notes_v04_still_present`, `v02_legacy_file_not_deleted_by_audits` | **Yes, as backward-compat pins** | They pin that *past* release records remain present — a release-history contract. Not removable while the checker enforces the same invariants. |
| Checker self-tests | `check_registry_matches_pinned_labels_and_order`, `collect_failures_invokes_every_check_in_registry_order`, `main_uses_collect_failures` | **Yes** | Verify the checker's own registry wiring. Only meaningful when `check_release.py` changes — the strongest RUN_LESS_OFTEN candidate. |

**Do the checker-self-tests need to run on every ordinary PRODUCT FULL in every environment?** No — their only failure mode is a change to `scripts/check_release.py` / workflow / release policy. They can move to the control-plane/release-specific suite without weakening the authoritative checker itself (the authoritative `python scripts/check_release.py` CI step is unchanged and runs on every tier). The mutation/invariant group is the borderline: it is also checker-wiring, but it protects the release boundary and is cheap post-#60; keeping it in the release-specific suite is the recommended middle ground.

---

## 12. Semantic duplication findings

**REDUNDANT DUPLICATE (same failure mode, same layer, same surface):**
1. **PyArrow job FULL step vs its own targeted/frozen steps** — the portability job runs 191 tests (10 targeted + 181 canonical/frozen) and then runs the *entire suite*, re-executing those 191 plus 3,546 unrelated tests. The FULL step under PyArrow24 is the clearest topology duplicate: its meaningful margin over 3.11 is a pin-version delta already asserted by the targeted + frozen steps (and the §8.1 sensitivity subset, once implemented).
2. **`test_sample_generation_core`/`cli` in portability ×2 per run** — once in the frozen surface, once in the FULL step (35.1s duplicated).
3. **`test_v060_portability.py` in FULL ×3 + targeted** — the same 10 static-portability tests under 3.11, 3.14, and PyArrow24, where only the PyArrow24 execution asserts the audited pin (the 3.11/3.14 runs assert nothing version-specific: the fixture is static).
4. **Control-plane files ×3** — 333 tests with zero product surface executed in three environments (§10).

**DEFENSE-IN-DEPTH WITH DIFFERENT FAILURE MODE (keep):**
1. **CLI `--help`/version smoke in 4 places** — pytest subprocess CLI tests (source tree), `v061_cli_usability` (wording freeze), package fresh-wheel 8-command help (installed wheel), example-renderer help (docs example). Distinct failure modes: source wiring vs wheel content vs example drift. **Not collapsible.**
2. **Release checker facts vs pytest doc assertions** — the checker runs as a subprocess in CI and validates the same release docs the pytest files assert in-process. Different layers (authoritative CI gate vs fast in-process regression); the checker must never be weakened.
3. **`test_v060_integrated_e2e` (subprocess CLI chain) vs `test_dataset_end_to_end_regression` (in-process full chain) vs `test_v070_integrated_e2e` (example execution)** — same conceptual chain at three altitudes. Each has a distinct failure mode (CLI subprocess wiring / in-process data integrity / shipped-example drift). The E2E trio is a P2 "reduce deep redundancy" candidate **only** if per-altitude failure modes are proven separate — the evidence so far says they are.
4. **Canonical reader + verified reader + PIT verification** — all call `load_verified_canonical_build`; distinct assertion targets (reader regression / dataset verify / PIT identity). Keep.
5. **`test_ci_post_merge_reuse.py` vs `test_release_v061` CI-shape tests vs `test_v061_ci_auditability.py`** — three files pin overlapping workflow facts (reuse gate markers, action majors, matrix shape). These are genuinely overlapping but at different altitudes (verifier logic / release-checker pins / auditability doc). Candidates for a single control-plane suite, not for deletion.

**Cheapest wins from overlap analysis:** the portability FULL step (item 1), the v060_portability triple-run (item 3), and the control-plane triple-run (item 4) account for most of the *recoverable* duplication. Everything in the defense-in-depth list is kept.

---

## 13. P0 recommendations — safe, no coverage loss

| # | Proposal | Files/surfaces affected | Safety argument | Wall-clock impact (per FULL) | Runner impact (per FULL) | Rollback / fail-closed | Confidence |
|---|---|---|---|---|---|---|---|
| P0-1 | **PyArrow job runs targeted + canonical/frozen + PyArrow-sensitive subset only** (drop its FULL step; keep pin + assert). Exact retained surface in §8.1: A = 10 targeted, B = 181 frozen, C = 711 newly retained sensitivity files (canonical materialization/builder, dataset materialization, verified reader, PIT, E2E regression). | `ci.yml` `portability-pyarrow24`; coordinated `check_release.py` workflow-shape pins + `test_v061_ci_auditability`/`release_v061` CI-shape tests in the same PR | No PyArrow-24 coverage loss: pin assert + 10 targeted + 181 frozen + every direct-importer/sensitivity file (711 tests, incl. all of PIT and E2E) still run under 24. Unrelated release/control-plane tests had zero Arrow value. | **−12–18s** (bottleneck moves to 3.14) | gross ≈ −263–299s (pytest, incl. duplicate targeted/frozen executions); **net ≈ −195–215 whole-job runner-seconds, upper bound 263s, TBD pending replacement-surface canary** (§8.2) | Step-set change; revert = restore FULL step. Fail-closed default (unset tier → full) unchanged. | **High-confidence topology candidate; exact savings require replacement-surface measurement** |
| P0-2 | **Harness-optimize `test_pit_sample_assembly.py`**: session/module-scoped shared immutable base builds (snapshots + catalog + materialized builds), per-test in-place mutations (the pattern already used by `mutate_manifest`/`rewrite_bars`), keeping every assertion. | `tests/test_pit_sample_assembly.py` only | Same 99 assertions; only fixture construction is shared. PIT safety cases unchanged. | −25–30s on each env job that still runs it (≈ −25–30s on the 3.14 critical path post-P0-1) | −75–90s (3 envs × 25–30s) | Revert the fixture refactor; assertions untouched. | **High-confidence harness candidate; requires before/after same-assertion timing** |
| P0-3 | **Drop `test_v060_portability.py` from 3.11/3.14 FULL** (portability-job targeted run is the only meaningful environment; the fixture is static and pin-asserted there). | pytest invocation scope / `ci.yml` markers; checker pins in same PR | The 10 tests assert PyArrow-24-vs-25 reader behavior; 3.11/3.14 run them against ambient pyarrow with no audited pin — zero distinct signal. | effectively ~0 | **~1–2s total** (targeted suite totals 0.87s under the audited pin; ambient runs comparable). Per-environment timing not independently isolated — call it **negligible / low-single-digit runner-seconds; topology cleanup rather than a meaningful performance lever** | Revert markers. | **Safe topology cleanliness; performance impact negligible** |
| P0-4 | **Control-plane files move to a control-plane suite** run once on 3.11 (see P1-2 — same change, listed under P1 because it introduces a new tier). | — | — | — | — | — | — |

---

## 14. P1 recommendations — low-risk segmentation

| # | Proposal | Files/surfaces affected | Safety argument | Wall-clock impact | Runner impact | Rollback / fail-closed | Confidence |
|---|---|---|---|---|---|---|---|
| P1-1 | **Python 3.14 compatibility surface** replacing the 3.14 FULL duplicate: all Python-version-sensitive families from §9 + release/package contract + one deep E2E + PIT/leakage safety (≈60–70% of tests, all sensitive families). | `ci.yml` `test (3.14)` invocation; new compatibility marker; checker pins | No promised compatibility family loses coverage; the drop list is the *non-sensitive* bulk only. | **A. Job-local:** −100 to −125s (315 → ≈190–215s, est.). **C. Workflow:** ≈ −22s (3.14 is the max only marginally; after P0-1 the workflow gain is bounded by the 3.14-vs-3.11 gap; once 3.11 is max, further 3.14 cuts save nothing wall-clock) — see §9.1 | **B. Runner:** −100 to −125s per FULL (3.14 env only) | Revert marker → FULL. Fail-closed default unchanged. | **Potentially high runner saving; workflow saving bounded by critical path** |
| P1-2 | **Control-plane tier**: control-plane-only PRs run the 5 control-plane files + release-v061 checker-self-test/CI-shape subset on 3.11 + package release-checker tail. Product PRs unchanged. Unknown → full. **V1 FULL attestation = SKIPPED on subset runs; no V1 post-merge reuse authorization derivable; reuse participation requires a separate V2 evidence contract (§10.1).** | `ci_risk_tier.py` rules, `ci.yml` guards, control-plane suite definition | Fail-closed by construction: only exact control-plane path sets take the fast branch; any unknown/unset tier → full. Release checker still runs on every tier. Attestation boundary per §10.1. | Control-plane PRs: 6m27s → **~2.5–3.5 min (candidate design target; not yet an acceptance baseline)** | ~989s → ~90–150s per control-plane PR (**−84.8% to −90.9%**) | The classifier default remains full; remove the rule → full. | **Large control-plane opportunity; requires a NEW evidence/attestation strategy if subset results are to participate in post-merge reuse — connects directly to Partial Reuse V2** |
| P1-3 | **Package tail stays on the critical path unchanged** — no change; the package job (release checker + attestation) is the reuse-gate's foundation and must not be split. | — | — | — | — | — | — |

---

## 15. P2 recommendations — require more evidence

| # | Proposal | Files/surfaces affected | Safety argument | Wall-clock impact | Runner impact | Rollback / fail-closed | Evidence still needed |
|---|---|---|---|---|---|---|---|
| P2-1 | **Split `test_release_v061.py`** into: authoritative release contract (mutation + version + CLI + docs groups — stays in release/package surface) vs checker self-tests (control-plane-only). Rename-away from `v061` label. | `test_release_v061.py` (structure only) | Checker remains authoritative; only the checker-wiring self-tests move. | 0 (already post-#60-optimized) | ~0 | File split is a rename — revertable. | Evidence that self-tests never fail on product-only changes (checker-change history). |
| P2-2 | **Reduce deep E2E redundancy** — evaluate whether `dataset_end_to_end_regression` (96) + `v060_integrated_e2e` (47) + `v070_integrated_e2e` (13) can share one altitude while preserving the three distinct failure modes; possible module-level shared chain fixtures. | The 3 E2E files | Keep all failure modes; share only fixture construction. | −15–20s (v060_integrated_e2e is per-test the most expensive) | −45–60s | Revert fixture sharing. | Failure-mode separation proof; a controlled experiment. |
| P2-3 | **`test_release_v061` CLI subprocess block** (≈20 tests at 0.58–1.8s) — evaluate a single subprocess that snapshots all helps in one CLI process vs the current per-command spawns. | `test_release_v061.py` CLI group | Same assertions, one interpreter startup. | −10–15s per env | −30–45s | Revert to per-command. | Verify the CLI has no cross-command state. |
| P2-4 | **Delete-candidate evidence file** — none proposed today; this slot stays open for any future file whose contract demonstrably retires, with the §4 test as the gate. | — | — | — | — | — | Requires explicit proof of unreachable behavior + no dependent contract + no release-boundary narrowing. |

---

## 16. Estimated savings — one canonical model

**Single savings model used everywhere in this document.** All runner figures are whole-job runner-seconds unless noted; all are **estimates pending implementation canaries** except the measured baseline.

**MEASURED BASELINE (run 31368693999, FULL):** 989 whole-job runner-seconds (3.11 293 + 3.14 315 + portability 327 + package 54); pytest-only 802s; workflow wall clock 6m27s.

**KNOWN savings (mechanically supported):**
- P0-3: ≈ 1–2s runner-seconds (10 static-portability tests out of 3.11/3.14 FULL; targeted suite totals 0.87s under the audited pin). Negligible; topology cleanup, not a performance lever.

**ESTIMATED savings (unmeasured; each requires its own canary):**

| Proposal | Runner-seconds (whole-job) | Wall-clock | Basis / caveat |
|---|---|---|---|
| P0-1 | ≈ 195–215 (upper bound 263) | −12–18s | 327 → ≈ 116–131s narrowed portability job (overhead + targeted 0.87 + frozen 35.10 + sensitivity subset ≈ 50–65). Exact subset runtime unmeasured. |
| P0-2 | ≈ 75–90 (3 envs × 25–30) | −25–30s | Before/after same-assertion timing required; 3.14 is the critical-path env post-P0-1. |
| P0-3 | ≈ 1–2 | ~0 | See KNOWN. |
| P1-1 | ≈ 100–125 (3.14 env only) | ≈ −22s (bounded) | 315 → ≈ 190–215s job-local; workflow gain capped by 3.14-vs-3.11 gap (§9.1); zero if portability still dominates. |
| P1-2 (control-plane PRs only) | ≈ 840–900 (989 → ~90–150) | 6m27 → ~2.5–3.5 min (candidate) | Subset unmeasured; requires V2 evidence strategy for reuse participation (§10.1). |

**POST-OPTIMIZATION TOTAL (product FULL, P0+P1-1 materialized):** per-environment build-up: 3.11 ≈ 262–268 (293 − P0-2 25–30 − P0-3 1–2), 3.14 ≈ 159–189 (315 − P0-2 25–30 − P0-3 1–2 − P1-1 100–125), portability ≈ 116–131, package 54 → **≈ 590–640 whole-job runner-seconds (−35% to −40%)**; **workflow wall clock ≈ 5m16–5m21s (−66 to −71s, −17% to −18%)** with the bottleneck = 3.11 whole job. **TBD pending implementation canaries — the range is an estimate, not an acceptance baseline.**

**Consistency rule:** no overlap is double-counted — P0-1 only touches the portability job; P0-2/P0-3 touch 3.11 and 3.14; P1-1 touches only 3.14. The scenario build-up below is the single source of truth; §1, §6, §8, §9, §13, §14 and this section use the same numbers.

**Scenario table (whole-job runner-seconds and workflow wall clock):**

| Scenario | 3.11 | 3.14 | portability | package | Total runner-s | Workflow wall clock |
|---|---|---|---|---|---|---|
| CURRENT (measured) | 293 | 315 | 327 | 54 | 989 | 6m27s |
| +P0-1 (est.) | 293 | 315 | 116–131 | 54 | 778–793 | ≈6m09s |
| +P0-1 +P0-2 +P0-3 (est.) | 262–267 | 284–289 | 116–131 | 54 | 716–741 | ≈5m38–5m43s |
| +P1-1 (est.) | 262–267 | 159–189 | 116–131 | 54 | 591–641 | ≈5m16–5m21s |

**Per control-plane PR (after P1-2, est.):** runner-seconds 989 → ~90–150 (−84.8% to −90.9%); wall clock 6m27 → **~2.5–3.5 min (candidate design target — not yet an acceptance baseline)**.

**Post-merge reuse path (unchanged by this audit):** jobs 13–24s (run 31366165407), `POST_MERGE_REUSE=true`. Separate metric from PR/control-plane FULL — verified-reuse attestations still require the FULL matrix on PRs, so nothing above reduces what a PR must prove, and subset results never satisfy the V1 verifier (§10.1).

**Honest statement of the wall-clock ceiling:** the product FULL wall clock cannot go below ≈ max(3.11 whole job ≈ 262–267s, package tail ≈ 54s) ≈ **5m16–5m21s** without either (a) shrinking the 3.11 job itself or (b) moving the package tail off the critical path — both are further P2 work. The dominant saving of P0/P1 is runner-seconds and the control-plane PR path, not product-PR wall clock.

---

## 17. Risks / false-optimization traps

1. **"Removing PyArrow FULL saves its entire pytest duration"** — false in two ways. Wall-clock: the critical path moves to `test (3.14)` (§6): saving ≈ 12–18s. Runner-seconds: the FULL step's 263s is gross, not net — the retained targeted/frozen surfaces and the replacement sensitivity subset (§8.1) cost non-zero time; net ≈ 195–215s (est.), upper bound 263s. Any implementation PR must quote the right number and measure the replacement surface.
2. **Filename age ≠ obsolete** — every `*_v02/v03/v051/v060/v061/v070` file protects a reachable current contract (§11). `test_options_v02.py` is backward compatibility for a format still read; `test_release_v061.py` is the live release-checker contract. No `DELETE_CANDIDATE` is justified today.
3. **The release checker pins the CI topology** — `test_release_v061.py` (`release_checker_fails_when_ci_matrix_changes`, `portability_job_loses_full_suite_step`, `...full_suite_step_loses_pytest`, pin assertions) and `test_v061_ci_auditability.py` assert the exact workflow shape, step names, and the literal `run: python -m pytest` adjacency. **Every topology change must update the checker contract in the same PR** or CI fails closed — by design. This is the main implementation cost of P0-1/P1-1.
4. **The V1 FULL attestation is a safety boundary, not a dial** — the attestation may be created **only** when the PR actually ran the complete V1 FULL validation contract. A control-plane/compatibility/partial subset must not produce an artifact the V1 verifier could interpret as "FULL CI successfully completed": for such subsets the attestation is **SKIPPED** and **no V1 post-merge FULL reuse authorization may be derived**. Future Partial Reuse V2 evidence from subsets requires a **separate evidence contract** — different schema, different artifact name/type, per-surface identity, a consumer that cannot be confused with V1 — and **a V2 surface-evidence artifact MUST NOT be accepted by the V1 FULL reuse verifier** (§10.1). Narrowing an environment's *contents* is fine; narrowing the *attestation* is not.
5. **"Byte-identical" is wrong wording** — the portability job runs the **same test suite selection under a different dependency environment** (PyArrow 24 pinned vs ambient). That difference is the job's purpose; claiming byte-identity ignores it. Same-selection duplication is still real (most of the FULL step's 263s re-executes 3.11's suite under a different pin) but must be described accurately.
6. **Runner variance can mask regressions and fake wins** — 2× portability variance and 4m19s↔7m36s 3.11 variance observed. All P0/P1 acceptance must use ≥2 independent FULL runs.
7. **The 35.1s frozen regression surface in the PyArrow job is deliberate** — sample-generation fixture chains build canonical Parquet identity; that is PyArrow-sensitive work, not a duplicate to delete (its *second* execution inside the FULL step is the duplicate).
8. **`v060_integrated_e2e`'s 3.7s subprocess tests are genuine integration** — collapsing them into in-process tests would change the failure mode (CLI wiring). Only fixture-level sharing (P2-2) is on the table.
9. **docs_fast package closure is load-bearing** — run 31361918221 failed at the release checker under docs_fast pre-#63 (`ModuleNotFoundError: pandas`); #63's runtime bootstrap is what makes docs-only CI pass today. Segmentation must never assume the checker can run without its runtime.
10. **7 skipped tests are environment-dependent, not portfolio noise** — symlink/junction/tzset skips differ per OS; counts are stable (3,730 passed everywhere) and are not a reduction lever.
11. **"2–3 minutes" for control-plane is not forced** — the evidence floor is ≈ 60–120s subset + ≈ 54s package tail + slack ≈ 2.5–3.5 min. That is a **plausible design target, not an acceptance baseline**; claim less than the floor and the rollout will miss its own estimate; claim it as measured and the rollout will have skipped measurement.

---

## 18. Proposed rollout sequence (report only)

1. **This audit** — docs-only (no behavior change). Baseline recorded at run 31368693999.
2. **P0-1 (PyArrow narrowing) + its checker-contract updates in one PR** — highest-confidence, no-coverage-loss; includes the `v060_portability` out-of-FULL change. Requires: release-checker contract update in the same PR, a **replacement-surface canary first** (measure tag C of §8.1 to price the net saving), 2 independent FULL validations, durations comparison vs this audit's numbers.
3. **P0-2 (PIT harness) alone** — same assertions, cheaper fixtures; local timing + 1 FULL.
4. **Measure again** (durations + whole-job table, ≥2 runs) before any P1 work.
5. **P1-2 (control-plane tier) alone** — classifier rule + suite definition + canaries (1 control-plane PR, 1 product PR, 1 docs PR). **V1 FULL attestation = SKIPPED on subset runs; no V1 reuse authorization derivable; if subset results are ever to participate in post-merge reuse, ship the separate V2 evidence contract first (§10.1) — a V2 surface-evidence artifact must never be accepted by the V1 verifier.**
6. **P1-1 (3.14 compatibility surface) alone** — after control-plane tier is stable; requires the §9 surface definition, a 3.14-surface canary (measures A/B/C of §9.1 separately), and 2 FULLs.
7. **Measure again; then P2 evidence-gathering** (release_v061 split, E2E fixture sharing, CLI single-process block) — each as its own PR with independent validation.
8. **Resume Partial Reuse V2 evidence/gating work** on top of the new measured baseline, with the V2 evidence contract designed so that no V2 artifact can satisfy the V1 FULL verifier.

**Rule: one major CI reduction per implementation PR; never bundle P0+P1+P2 into one change.** Each step must ship with its checker-contract updates and a fail-closed fallback (tier/guard semantics unchanged).

---

## 19. Explicit non-actions

This audit authorizes **nothing**. Concretely, in this PR and at this base:

- **NO tests deleted** — no `DELETE_CANDIDATE` exists; no file is removed.
- **NO tests skipped** — no test, file, or environment is excluded from any run.
- **NO workflow changed** — `.github/workflows/ci.yml` is untouched.
- **NO production code changed** — `src/` is untouched.
- **NO release contract changed** — `scripts/check_release.py` and every release/version/CI invariant it enforces are untouched.
- **NO package/packaging change** — `pyproject.toml`, `README.md`, release notes, and version files are untouched.
- **NO rename** — version-labelled filenames stay as they are.
- **NO new CI tier** — the P0/P1 proposals are designs for future PRs; `scripts/ci_risk_tier.py` and `ci/components.toml` are untouched.
- **NO new attestation path** — the V1 FULL attestation keeps its exact current contract; no subset artifact of any kind is created or blessed (§10.1).

The single changed file in this PR is `docs/test_portfolio_audit_v1.md`.
