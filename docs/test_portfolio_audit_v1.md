# Test Portfolio Audit v1 — MarketVault CI Test Portfolio & Duplication Analysis

**Type:** measurement / analysis only.
**Base tree audited:** `6ba8f055afbe0f018a1a8c935f77d53c2aa03db1` (main after PR #65).
**Primary CI evidence:** run `31368693999` (main FULL after PR #65), run `31367431272` (PR #65 FULL),
plus earlier FULL runs from the #59 profiling, #60 release-checker optimization, #61 reuse gate,
#62/#64 reuse canaries, and #63 lightweight closure series.
**Portfolio size at base:** 3,737 collected tests across 50 `tests/test_*.py` files
(3,730 passed + 7 environment-dependent skips per FULL environment).

**This document changes nothing.** No tests are deleted, skipped, or modified; no workflow, script,
product, release, or packaging file is touched. Every recommendation below is a proposal for a
future implementation PR and is labelled P0 / P1 / P2 accordingly.

---

## 1. Executive summary

1. **FULL CI currently executes ~3,737 tests up to three times per run** (Python 3.11 FULL, Python 3.14 FULL, PyArrow 24 FULL), plus a dedicated PyArrow-targeted surface and a frozen canonical/frozen regression surface inside the PyArrow job.
2. **Measured FULL behavior at the base tree (run 31368693999):**
   - `test (3.11)`: whole job **4m53s** (pytest 262.90s)
   - `test (3.14)`: whole job **5m15s** (pytest 275.66s)
   - `portability-pyarrow24`: whole job **5m27s** (pytest 263.36s) — **wall-clock bottleneck**
   - `package`: **54s**, starts when the slowest of `test`/`portability` completes
   - workflow wall clock: **6m27s**; critical path = portability whole job + package tail
3. **The largest single test-file hotspot is `tests/test_pit_sample_assembly.py` (~39–42s per environment)**, followed by `tests/test_release_v061.py` (~23–27s within the slowest-200 report, 452 tests), `tests/test_v060_integrated_e2e.py` (~10–11s), and the backfill / sample-generation-cli / audit clusters. The cost is per-test fixture construction (Parquet writes + DuckDB materialization + verified-build loading), **not** redundant assertions.
4. **Historical optimization precedent exists:** PR #60 replaced per-test subprocess invocations of `scripts/check_release.py` with an in-process checker harness and cut `test_release_v061.py` from **166–204s to 23–27s per environment (≈8×) with zero coverage loss**. That is the template for the P0 harness work proposed here.
5. **Runner variance is large and must bound all claims:** the same tree showed portability pytest at **263s (run 31368693999) vs 521s (run 31367431272)** and test 3.11 whole-job at **4m19s vs 7m36s** across near-identical trees. No single timing sample is stable truth.
6. **The PyArrow24 FULL duplicate is the highest-confidence topology reduction**, but its *wall-clock* saving is small (~12–18s) because the critical path simply moves to Python 3.14; its *runner-minute* saving is large (~263–299s per FULL). This distinction is quantified in §6 and §16.
7. **No `DELETE_CANDIDATE` recommendation is made anywhere.** All version-labelled files (`*_v02/v03/v051/v060/v061/v070`) protect currently promised contracts; none can be called obsolete from filename age alone. `test_options_v02.py` protects a *legacy snapshot format still read by current inventory* — backward compatibility, not dead code.
8. **Realistic safe targets:** control-plane PRs ≈ **2.5–3.5 minutes wall-clock** after P1 segmentation (2–3 minutes is plausible but not forced by the evidence); ordinary product FULL ≈ **5m45s–6m wall-clock** and **~700 runner-seconds** after P0+P1 (from 6m27s / ~989s). Post-merge verified reuse (~13–24s jobs, run 31366165407) is a different metric and unchanged by this audit.
9. **Any CI topology change must be coordinated with `scripts/check_release.py`** — its regression tests (`test_release_v061.py`, `test_v061_ci_auditability.py`) pin the exact workflow shape (job names, step names, literal `run: python -m pytest` adjacency, PyArrow pin, action majors). This is the dominant false-optimization trap (§17).

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

**Duplicate-execution accounting (FULL):** the portability job executes `test_sample_generation_core.py` + `test_sample_generation_cli.py` (178 tests, 35.1s) as its frozen regression surface **and again** inside its FULL step. Every test in the suite runs three times per FULL (once per environment), plus 178 of them run four times.

---

## 3. Current test inventory

Source of truth: `python -m pytest --collect-only -q` at the exact base → **3,737 tests** in **50 files** (CI FULL confirms: 3,730 passed, 7 skipped — the skips are environment-dependent `pytest.skip` on symlink/junction/tzset availability, e.g. `test_canonical_materialization_v03.py`, `test_dataset_cli.py`, `test_dataset_end_to_end_regression.py`).

**Count by subsystem cluster:**

| Cluster | Files | Tests | Share |
|---|---|---|---|
| Canonical bars (build/materialize/read/split) | 4 (`builder_v03`, `materialization_v03`, `reader`, `chronological_splits`) | 280 | 7.5% |
| Dataset orchestration/materialization/manifest/CLI | 6 (`orchestration`, `materialization`, `cli`, `manifest_core`, `feature_execution`, `label_execution`) | 800 | 21.4% |
| Dataset verification / E2E regression | 2 (`verified_dataset_reader`, `end_to_end_regression`) | 331 | 8.9% |
| Transform registry / feature-label specs | 2 (`transform_registry`, `feature_label_specs`) | 156 | 4.2% |
| Dataset Catalog (v0.6.0) | 5 (`builder`, `cli`, `contract`, `materialization`, `reader`) | 294 | 7.9% |
| Sample generation (v0.6.0) | 3 (`core`, `cli`, `contract`) | 294 | 7.9% |
| PIT / leakage safety | 3 (`pit_sample_assembly`, `leakage_threat_model`, `snapshot_safety`) | 211 | 5.6% |
| Storage-era v03 contracts (audit/backfill/calendar/intraday/inventory/timestamps) | 6 (`audit_v03`, `backfill_v03`, `calendar_v03`, `intraday_audit_v03`, `inventory_v03`, `timestamp_semantics_v03`) | 343 | 9.2% |
| Collectors / normalization / quality / moomoo SDK | 4 (`collector`, `normalization`, `quality`, `moomoo_sdk`) | 10 | 0.3% |
| Options legacy (v02) | 1 (`options_v02`) | 46 | 1.2% |
| Release/version/CLI/package contract | 4 (`release_v061`, `v061_cli_usability`, `v070_python_client_examples`, `v070_artifact_client_foundation/catalog/readers` split below) | ~567 | 15.2% |
| ArtifactClient v0.7.0 | 3 (`foundation`, `catalog`, `readers`) | 59 | 1.6% |
| Integrated acceptance (v0.6/v0.7 E2E, portability) | 4 (`v060_integrated_e2e`, `v060_portability`, `v070_integrated_e2e`, `v070_python_client_examples` merged above) | 89 | 2.4% |
| CI control-plane | 5 (`ci_risk_tier`, `component_aware_tiers`, `ci_post_merge_reuse`, `v061_ci_auditability`, `audit_pr`) | 333 | 8.9% |

Non-test assets in `tests/`: `v060_acceptance_helpers.py` (imported acceptance helper — the release checker asserts it exists) and `tests/fixtures/` (frozen bundle; the release checker asserts its frozen generation id / plan sha do not change).

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

Timing evidence = observed file totals within the top-200 `--durations` report (so *minimum* observed file cost; the full file cost is higher for files with many sub-0.3s tests). Runner: `3.11/3.14/PA24` = per-environment cost; variance across runs noted in §7.

### 5.1 Product data pipeline (keep in FULL)

| File | Tests | Subsystem | v-label | PyArrow | Py-ver | Ctrl-plane | Pkg/rel | Timing (top-200, 3.11) | Categories | Recommendation | Rationale |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `test_canonical_builder_v03.py` | 60 | canonical bars builder | yes (v03) | indirect | possible | no | no | ~0.4–4.9s | PRODUCT_CORE, DATA_INTEGRITY, LEGACY_NAMED_CURRENT_CONTRACT | KEEP_EVERY_FULL | Current canonical build identity; v03 name is era label only. |
| `test_canonical_materialization_v03.py` | 78 | canonical materialization | yes (v03) | **direct** | possible (symlink skips) | no | no | ~1.6–6.2s | PRODUCT_CORE, DATA_INTEGRITY, PYARROW_COMPATIBILITY | KEEP_EVERY_FULL | Parquet write identity; genuinely PyArrow-sensitive. |
| `test_canonical_reader.py` | 3 | canonical single-file reader | no | **direct** | possible | no | no | 0.92s (targeted step) | PRODUCT_CORE, PYARROW_COMPATIBILITY | KEEP_CURRENT | Runs in portability targeted + FULL; tiny. |
| `test_chronological_splits.py` | 139 | chronological split / sessions | no | none | possible | no | no | <0.3s each | PRODUCT_CORE, DATA_INTEGRITY | KEEP_EVERY_FULL | Pure pandas; fast. |
| `test_dataset_orchestration.py` | 145 | dataset orchestration | no | indirect | possible | no | no | ~0.9–1.7s | PRODUCT_CORE | KEEP_EVERY_FULL | |
| `test_dataset_materialization.py` | 143 | dataset materialization | no | **direct** | possible | no | no | ~0.9–2.4s | PRODUCT_CORE, DATA_INTEGRITY, PYARROW_COMPATIBILITY | KEEP_EVERY_FULL | |
| `test_dataset_cli.py` | 148 | dataset CLI | no | indirect | **yes** (junctions) | no | no | ~0.4–1.8s | CLI_CONTRACT, PRODUCT_CORE | KEEP_EVERY_FULL | Subprocess CLI; Windows-skip paths. |
| `test_dataset_manifest_core.py` | 128 | derived-dataset manifest | no | none | possible | no | no | <0.3s each | PRODUCT_CORE | KEEP_EVERY_FULL | |
| `test_dataset_feature_execution.py` | 119 | feature transforms | no | indirect | possible | no | no | ~1.0–1.6s | PRODUCT_CORE | KEEP_EVERY_FULL | |
| `test_dataset_label_execution.py` | 117 | label transforms | no | indirect | possible | no | no | ~1.0–1.7s | PRODUCT_CORE | KEEP_EVERY_FULL | |
| `test_dataset_transform_registry.py` | 86 | transform registry | no | none | possible | no | no | <0.3s each | PRODUCT_CORE | KEEP_EVERY_FULL | |
| `test_dataset_end_to_end_regression.py` | 96 | full-chain determinism/leakage E2E | no | **direct** | **yes** (tzset) | no | no | ~2.1–3.0s | PRODUCT_INTEGRATION, DATA_INTEGRITY | KEEP_CURRENT | Deep E2E; P2 candidate for redundancy review, not deletion. |
| `test_verified_dataset_reader.py` | 235 | verified dataset reader | no | **direct** | **yes** (symlinks, tz) | no | no | ~0.9–1.7s | PRODUCT_CORE, PYARROW_COMPATIBILITY | KEEP_EVERY_FULL | |
| `test_sample_generation_core.py` | 99 | sample generator core | no | indirect | possible | no | no | ~3.7–4.3s | PRODUCT_CORE, DATA_INTEGRITY | KEEP_EVERY_FULL | Also runs in portability frozen surface (see §8). |
| `test_sample_generation_cli.py` | 79 | sample gen CLI | no | indirect | possible | no | no | ~6.2–8.7s | CLI_CONTRACT, PRODUCT_CORE | KEEP_EVERY_FULL | Subprocess + Parquet/DuckDB fixture chains; also in portability frozen surface. |
| `test_sample_generation_contract.py` | 116 | sample-gen contract docs | no | none | possible | no | **yes** | <0.3s each | PACKAGE_CONTRACT, RELEASE_CONTRACT | KEEP_CURRENT | Contract doc assertions, fast. |
| `test_feature_label_specs.py` | 70 | feature/label spec versioning | no | none | possible | no | no | <0.3s each | PRODUCT_CORE, BACKWARD_COMPATIBILITY | KEEP_EVERY_FULL | |
| `test_dataset_catalog_builder.py` | 38 | catalog builder | no | indirect | possible | no | no | ~0.3–0.8s | PRODUCT_CORE, DATA_INTEGRITY | KEEP_EVERY_FULL | |
| `test_dataset_catalog_cli.py` | 85 | catalog CLI | no | indirect | possible | no | no | ~2.9–3.2s | CLI_CONTRACT, PRODUCT_CORE | KEEP_EVERY_FULL | |
| `test_dataset_catalog_contract.py` | 84 | catalog contract docs | no | none | possible | no | **yes** | ~0.3s | PACKAGE_CONTRACT | KEEP_CURRENT | |
| `test_dataset_catalog_materialization.py` | 31 | catalog snapshot materialization | no | indirect | possible | no | no | ~0.3s | PRODUCT_CORE, DATA_INTEGRITY | KEEP_EVERY_FULL | |
| `test_dataset_catalog_reader.py` | 56 | verified catalog reader | no | indirect | possible | no | no | ~0.3s | PRODUCT_CORE | KEEP_EVERY_FULL | |

### 5.2 PIT / leakage safety (keep, optimize harness)

| File | Tests | Subsystem | v-label | PyArrow | Py-ver | Ctrl-plane | Pkg/rel | Timing (top-200, 3.11) | Categories | Recommendation | Rationale |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `test_pit_sample_assembly.py` | 99 | two-clock PIT sample assembly | no | **direct** | possible | no | no | **~38.9–42.0s (67 of 99 in top-200; ~0.58s each)** | PIT_LEAKAGE_SAFETY, DATA_INTEGRITY | **HARNESS_OPTIMIZE** | Biggest single-file hotspot; cost is per-test `tmp_path` fixture chains (Parquet writes + DuckDB catalog + materialize + verified-load), see §7/§11. |
| `test_leakage_threat_model.py` | 107 | cross-contract leakage threat model | no | indirect | possible | no | no | ~0.6–1.3s (was 18.2s pre-#60-era run contention) | PIT_LEAKAGE_SAFETY, DATA_INTEGRITY | KEEP_EVERY_FULL | High-value safety surface; already cheap. |
| `test_snapshot_safety.py` | 5 | pre-fix legacy batch-name snapshot | no | indirect | possible | no | no | ~0.4–2.3s | BACKWARD_COMPATIBILITY, PIT_LEAKAGE_SAFETY | KEEP_COMPAT | Legacy snapshot must not silently change PIT results. |

### 5.3 Storage-era v03 contracts (current contracts, version-labelled names)

| File | Tests | Subsystem | v-label | PyArrow | Py-ver | Ctrl-plane | Pkg/rel | Timing (top-200, 3.11) | Categories | Recommendation | Rationale |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `test_audit_v03.py` | 60 | storage audit views/status | yes (v03) | indirect | possible | no | no | ~4.6–6.2s | PRODUCT_CORE, DATA_INTEGRITY, LEGACY_NAMED_CURRENT_CONTRACT | KEEP_EVERY_FULL (later RENAME_LEGACY_NAME candidate) | Current audit contract; name is era label. |
| `test_backfill_v03.py` | 80 | backfill retry/quality semantics | yes (v03) | indirect | possible | no | no | ~6.5–7.4s | PRODUCT_CORE, DATA_INTEGRITY | KEEP_EVERY_FULL | |
| `test_calendar_v03.py` | 23 | trading calendar | yes (v03) | indirect | possible | no | no | ~0.8–1.6s | PRODUCT_CORE | KEEP_EVERY_FULL | |
| `test_intraday_audit_v03.py` | 129 | intraday audit gap/overlap | yes (v03) | indirect | possible | no | no | ~3.9–5.8s | PRODUCT_CORE, DATA_INTEGRITY | KEEP_EVERY_FULL | |
| `test_inventory_v03.py` | 34 | snapshot inventory | yes (v03) | indirect | possible | no | no | ~0.4–2.6s | PRODUCT_CORE, BACKWARD_COMPATIBILITY | KEEP_EVERY_FULL | Reads legacy v02 snapshots too (§11). |
| `test_timestamp_semantics_v03.py` | 17 | timestamp semantics | yes (v03) | indirect | **yes** (tz) | no | no | <0.3s each | PRODUCT_CORE, PYTHON_COMPATIBILITY | KEEP_EVERY_FULL | |

### 5.4 Backward compatibility (keep; nothing to delete)

| File | Tests | Subsystem | v-label | PyArrow | Py-ver | Ctrl-plane | Pkg/rel | Timing | Categories | Recommendation | Rationale |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `test_options_v02.py` | 46 | legacy v02 options snapshots | yes (v02) | indirect | possible | no | no | ~1.9–3.1s | BACKWARD_COMPATIBILITY, LEGACY_NAMED_CURRENT_CONTRACT | KEEP_COMPAT | v02 snapshots still read by inventory; `test_release_v061` asserts v02 files are detected and **not** deleted by audits. |
| `test_deprecation_compatibility_v051.py` | 5 | NumPy generic-timedelta deprecation | yes (v051) | none | **yes** (NumPy behavior) | no | no | <0.3s | PYTHON_COMPATIBILITY, BACKWARD_COMPATIBILITY | KEEP_COMPAT | Pins the exact `filterwarnings` guard contract; may be NumPy-version sensitive. |

### 5.5 CLI / release / package contracts

| File | Tests | Subsystem | v-label | PyArrow | Py-ver | Ctrl-plane | Pkg/rel | Timing (top-200, 3.11) | Categories | Recommendation | Rationale |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `test_release_v061.py` | 452 | release checker + CLI/version/docs/package invariants | yes (v061) | **policy** (pin facts) | **yes** (subprocess CLI) | no | **yes** | ~23.2–27.6s (33 entries in top-200) | RELEASE_CONTRACT, CLI_CONTRACT, PACKAGE_CONTRACT, BACKWARD_COMPATIBILITY, LEGACY_NAMED_CURRENT_CONTRACT | KEEP_CURRENT; see §10 for per-group disposition | The authoritative regression for `scripts/check_release.py` and the workflow/release boundary. Post-#60 harness already cut it ~8×. |
| `test_v061_cli_usability.py` | 34 | CLI help/error wording freeze | yes (v061) | none | **yes** | no | no | <0.3s each | CLI_CONTRACT | KEEP_CURRENT | |
| `test_v061_ci_auditability.py` | 40 | CI/package auditability (workflow shape) | yes (v061) | policy | possible | **yes** | **yes** | <0.3s each | CONTROL_PLANE, PACKAGE_CONTRACT, RELEASE_CONTRACT | CONTROL_PLANE_ONLY | Pins workflow majors/matrix/job count/artifact chain; only meaningful when control plane changes. |
| `test_v060_integrated_e2e.py` | 47 | v0.6 integrated acceptance (real CLI chain) | yes (v060) | indirect | **yes** (subprocess) | no | no | ~9.8–11.1s (3 tests ≈ 3.7s each) | PRODUCT_INTEGRATION, CLI_CONTRACT | KEEP_CURRENT (RUN_LESS_OFTEN possible) | Genuine subprocess CLI E2E; expensive but real. |
| `test_v060_portability.py` | 10 | PyArrow 24/25 static portability | yes (v060) | **direct** (runtime) | possible | no | no | 0.87s targeted | PYARROW_COMPATIBILITY | TARGETED_ENV_ONLY (keep in portability job; drop from 3.11/3.14 FULL) | Reads frozen PyArrow-25-produced fixtures under PyArrow 24 — only meaningful under the audited pin. |
| `test_v070_integrated_e2e.py` | 13 | v0.7 integrated acceptance | yes (v070) | indirect | **yes** (subprocess) | no | no | ~0.9–1.0s | PRODUCT_INTEGRATION | KEEP_CURRENT | |
| `test_v070_python_client_examples.py` | 19 | example/doc guardrails | yes (v070) | indirect | possible | no | **yes** | <0.3s each | PACKAGE_CONTRACT | KEEP_CURRENT | |
| `test_v070_artifact_client_foundation.py` | 17 | ArtifactClient lazy foundation | yes (v070) | indirect | **yes** (import/sys.modules) | no | **yes** | ~0.5s | PACKAGE_CONTRACT, PRODUCT_CORE | KEEP_CURRENT | |
| `test_v070_artifact_client_catalog.py` | 16 | ArtifactClient catalog read | yes (v070) | indirect | possible | no | **yes** | ~0.3–1.1s | PRODUCT_CORE, PACKAGE_CONTRACT | KEEP_CURRENT | |
| `test_v070_artifact_client_readers.py` | 26 | ArtifactClient verified readers | yes (v070) | indirect | possible | no | **yes** | ~1.9–2.1s | PRODUCT_CORE, PACKAGE_CONTRACT | KEEP_CURRENT | |

### 5.6 Collectors / normalization / quality / SDK

| File | Tests | Subsystem | v-label | PyArrow | Py-ver | Ctrl-plane | Pkg/rel | Timing | Categories | Recommendation | Rationale |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `test_collector.py` | 1 | moomoo history collector | no | none | possible | no | no | <0.3s | PRODUCT_CORE | KEEP_EVERY_FULL | Tiny. |
| `test_normalization.py` | 2 | bars normalization | no | none | possible | no | no | <0.3s | PRODUCT_CORE | KEEP_EVERY_FULL | Tiny. |
| `test_quality.py` | 1 | bar quality checks | no | none | possible | no | no | <0.3s | PRODUCT_CORE | KEEP_EVERY_FULL | Tiny. |
| `test_moomoo_sdk.py` | 6 | moomoo SDK lazy loading | no | none | possible | no | no | <0.3s | PRODUCT_CORE | KEEP_EVERY_FULL | Tiny. |

### 5.7 Control-plane (should not run under product FULL ×3)

| File | Tests | Subsystem | v-label | PyArrow | Py-ver | Ctrl-plane | Pkg/rel | Timing | Categories | Recommendation | Rationale |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `test_ci_risk_tier.py` | 17 | risk-tier classifier | no | none | possible | **yes** | no | <0.3s each | CONTROL_PLANE | CONTROL_PLANE_ONLY | Tiny git-repo fixtures, seconds-range by design. |
| `test_component_aware_tiers.py` | 19 | component-aware classifier | no | none | possible | **yes** | no | ~0.7–0.8s | CONTROL_PLANE | CONTROL_PLANE_ONLY | |
| `test_ci_post_merge_reuse.py` | 241 | post-merge FULL reuse gate | no | none | possible | **yes** | no | <0.3s each (122 fns + params) | CONTROL_PLANE | CONTROL_PLANE_ONLY | Verifier proof/attestation logic; no product surface. |
| `test_audit_pr.py` | 16 | automated PR scope audit (DP2) | no | none | possible | **yes** | no | <0.3s each | CONTROL_PLANE | CONTROL_PLANE_ONLY | |
| `test_v061_ci_auditability.py` | 40 | CI/package auditability | yes (v061) | policy | possible | **yes** | **yes** | <0.3s each | CONTROL_PLANE, PACKAGE_CONTRACT | CONTROL_PLANE_ONLY (+ package closure) | |

**Aggregate:** 333 control-plane tests (8.9%) currently execute in FULL ×3 with zero product-surface value; they were explicitly designed ("stay in the seconds range") for focused execution.

---

## 6. Critical-path analysis (run 31368693999, main FULL after PR #65)

**Whole-job durations (started → completed):**

| Job | Start | End | Whole-job | pytest (FULL step) | Job overhead beyond pytest |
|---|---|---|---|---|---|
| `test (3.11)` | 08:07:36 | 08:12:29 | **4m53s** | 262.90s | ~30s (checkout/setup/classify/install/compile) |
| `test (3.14)` | 08:07:37 | 08:12:52 | **5m15s** | 275.66s | ~39s |
| `portability-pyarrow24` | 08:07:36 | 08:13:03 | **5m27s** | 263.36s | ~64s (incl. PyArrow pin install ~15s, targeted 0.87s, canonical/frozen surface ~36s) |
| `package` | 08:13:06 | 08:14:00 | **0m54s** | — | — |

**Workflow wall clock:** 08:07:33 → 08:14:00 = **6m27s**.

**Critical path:** `portability-pyarrow24` whole job (5m27s) is the *slowest* of the three test jobs and is the last dependency of `package` (`needs: [test, portability-pyarrow24]`; both `test` jobs finished by 08:12:52, portability at 08:13:03 — portability gates the package start). Critical path = portability 5m27s + package 54s + ~6s scheduling slack = **6m27s**. The wall-clock bottleneck surface is the **portability-pyarrow24 whole job**.

**Why portability is the bottleneck — and what removing its FULL would do:**

- The portability job's FULL pytest (263.36s) is *not* slower than the others (3.14: 275.66s; 3.11: 262.90s). The job wins the bottleneck only by its extra steps: PyArrow pin install, the 10-test targeted step (0.87s), and the canonical/frozen regression surface (**35.10s** for 178 tests that run *again* in its FULL step).
- **If the portability FULL duplicate were removed** (keeping the targeted + canonical/frozen surface), the portability job would shrink to ≈ 60–65s, and the critical path would move to **`test (3.14)` whole job (5m15s) + package (54s) ≈ 6m09s**. The wall-clock saving is **≈ 12–18s**, not the full 263s of its pytest duration. Claiming the latter would be wrong.
- The runner-minute saving is real and large: **−263–299s per FULL** (the FULL step + its duplicate surface execution), because those minutes are charged on a third runner that currently runs a byte-identical suite to 3.11.

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

**Possible future compatibility surface (design only — NOT implemented here):** the portability job keeps (a) the pin + assert, (b) `test_v060_portability.py`, (c) `test_canonical_reader.py`, (d) the canonical/frozen regression surface (sample_generation_core/cli — they build canonical Parquet identity chains), plus a **PyArrow-sensitive subset marker** over the direct/indirect-sensitive files (canonical materialization, dataset materialization, verified dataset reader, PIT, end-to-end regression). Everything else drops out of the PyArrow job. This preserves *all meaningful* PyArrow-24 coverage while removing the unrelated control-plane/release tests from the third environment.

**Quantified expectations (per FULL):**
- Runner-minutes: **−263s** (FULL step) **− 0s** (targeted/frozen surfaces retained) ≈ **−4.4 min**; the 178-test frozen double-run also disappears from the FULL step but remains once in the frozen step.
- Wall-clock: **−12–18s** (critical path moves to `test (3.14)`, §6). Stated explicitly: **removing the PyArrow FULL does NOT save its 263s from wall-clock**; the wall-clock ceiling is the 3.14 job afterwards.
- Rollback/fail-closed: the change is a step-set change in `portability-pyarrow24`; the release checker's workflow-shape tests must be updated in the same PR (they currently pin the FULL step's literal adjacency). If the narrowed surface fails, revert the step-set; the other two FULL jobs were unaffected.

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

**Analysis of A (FULL forever) vs B (compatibility surface):** the set of plausibly-sensitive files covers most of the suite by count, but by *value* the FULL triple-run's marginal gain on 3.14 is the ~5%-slower re-execution of behavior already proven on 3.11, plus genuine 3.14-only risk concentrated in the surfaces above. A defensible 3.14 surface is: **all of the above sensitivity families + the release/package contract + one representative deep E2E (`v060_integrated_e2e` or `dataset_end_to_end_regression`) + PIT/leakage safety** — roughly 60–70% of tests by count but *all* version-sensitive families, dropping the redundant non-sensitive bulk (`chronological_splits`, `transform_registry`, `manifest_core`, catalog contract/docs, most of `sample_generation_contract`, etc.).

**Guardrail (per the brief):** do not narrow 3.14 without a replacement compatibility surface. The P2 proposal (§15) is exactly that: a named compatibility suite, not an ad-hoc drop. 3.14 must also keep executing the release checker contract — `test_release_v061`'s version/CLI/package assertions are part of the packaging contract on modern Python.

---

## 10. Control-plane segmentation analysis

**Control-plane files** (5): `test_ci_post_merge_reuse.py` (241), `test_v061_ci_auditability.py` (40), `test_ci_risk_tier.py` (17), `test_component_aware_tiers.py` (19), `test_audit_pr.py` (16) = **333 tests**; plus `test_release_v061.py`'s CI-shape/checker-self-test groups (§11/§12; ~40–60 of its 452).

**Forward question — should a normal product-code PR execute these under 3.11, 3.14, and PyArrow24?** No. None of them touches a product surface, reads a Parquet file, or executes product code beyond `market_vault` import paths that the product FULL already exercises. Distinct safety value per environment is ≈ zero (they pass in 0.1–0.8s per env today because they are pure control-plane logic). Minimum environments with distinct value: **one** (3.11, the CI runtime).

**Inverse question — does a CI/control-plane-only PR need every expensive PIT/dataset/intraday product regression under 3 environments?** No. The control-plane change surface (`ci.yml`, `scripts/`, `ci/components.toml`, classifier) is validated by the control-plane suite + the release checker; the product regression FULL adds no signal to a workflow-only change. But the release checker contract itself must still run on every tier (it validates docs/package/version state — that is tier-independent and already unconditional).

**Proposed fail-closed segmentation policy (P1, design only):**
1. **Control-plane tier** (changed paths ⊆ control-plane surface): run the 5 control-plane files + `test_release_v061` checker-self-test/CI-shape subset + release checker, on 3.11 only; `package` runs its normal tail (release checker + attestation, since the FULL attestation contract requires the FULL matrix on PRs — see §17 trap #4).
2. **Product tier** (changed paths ⊆ `src/`, `tests/`): full current behavior (FULL ×3 + package) — unchanged.
3. **Unknown/mixed**: fail closed to full (current classifier default).
4. Any unset/unknown `CI_TIER` keeps every heavy guard true (current fail-closed behavior) — preserved verbatim.

**Realistic control-plane wall clock (target §18):** control-plane subset ≈ 333 tests + checker subset, all "seconds-range" design ≈ **60–120s** of pytest on 3.11 + package tail ≈ 54s + overhead ≈ **2.5–3.5 minutes total**. The evidence supports ~2–3 min as plausible but the package tail + scheduling slack makes 3–4 min the honest upper band; we do not force the 2–3 min conclusion.

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
| `test_v070_*` (5 files) | Current v0.7.0 ArtifactClient + example contracts. | **KEEP**. |

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
1. **PyArrow job FULL step vs its own targeted/frozen steps** — the portability job runs 181 tests (targeted + frozen) and then runs the *entire suite*, re-executing those 181 plus 3,549 unrelated tests. The FULL step under PyArrow24 is the clearest topology duplicate: its meaningful margin over 3.11 is a pin-version delta already asserted by the targeted + frozen steps.
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

| # | Proposal | Files/surfaces affected | Safety argument | Wall-clock impact (per FULL) | Runner-minute impact (per FULL) | Rollback / fail-closed | Evidence still needed |
|---|---|---|---|---|---|---|---|
| P0-1 | **PyArrow job runs targeted + canonical/frozen + PyArrow-sensitive subset only** (drop its FULL step; keep pin + assert). Sensitive subset: direct/indirect-sensitive files from §8 (canonical materialization/reader, dataset materialization, verified reader, PIT, E2E regression, sample generation core/cli already present). | `ci.yml` `portability-pyarrow24`; coordinated `check_release.py` workflow-shape pins + `test_v061_ci_auditability`/`release_v061` CI-shape tests in the same PR | No PyArrow-24 coverage loss: pin assert + 10 targeted + 181 frozen + every genuinely sensitive file still run under 24. Unrelated release/control-plane tests had zero Arrow value. | **−12–18s** (bottleneck moves to 3.14) | **−263–299s** | Step-set change; revert = restore FULL step. Fail-closed default (unset tier → full) unchanged. | One independent FULL after change; confirm the subset list via an import/sensitivity scan against the durations report. |
| P0-2 | **Harness-optimize `test_pit_sample_assembly.py`**: session/module-scoped shared immutable base builds (snapshots + catalog + materialized builds), per-test in-place mutations (the pattern already used by `mutate_manifest`/`rewrite_bars`), keeping every assertion. | `tests/test_pit_sample_assembly.py` only | Same 99 assertions; only fixture construction is shared. PIT safety cases unchanged. | −25–30s on each env job that still runs it (≈ −30s on the 3.14 critical path post-P0-1) | −75–90s | Revert the fixture refactor; assertions untouched. | Local timing before/after on the file; one FULL. |
| P0-3 | **Drop `test_v060_portability.py` from 3.11/3.14 FULL** (portability-job targeted run is the only meaningful environment; the fixture is static and pin-asserted there). | pytest invocation scope / `ci.yml` markers; checker pins in same PR | The 10 tests assert PyArrow-24-vs-25 reader behavior; 3.11/3.14 run them against ambient pyarrow with no audited pin — zero distinct signal. | ~0 | −20s (10 × 3 runs ≈ 0.87s each env — minor) | Revert markers. | None beyond a FULL. |
| P0-4 | **Control-plane files move to a control-plane suite** run once on 3.11 (see P1-2 — same change, listed under P1 because it introduces a new tier). | — | — | — | — | — | — |

## 14. P1 recommendations — low-risk segmentation

| # | Proposal | Files/surfaces affected | Safety argument | Wall-clock impact | Runner-minute impact | Rollback / fail-closed | Evidence still needed |
|---|---|---|---|---|---|---|---|
| P1-1 | **Python 3.14 compatibility surface** replacing the 3.14 FULL duplicate: all Python-version-sensitive families from §9 + release/package contract + one deep E2E + PIT/leakage safety (≈60–70% of tests, all sensitive families). | `ci.yml` `test (3.14)` invocation; new compatibility marker; checker pins | No promised compatibility family loses coverage; the drop list is the *non-sensitive* bulk only. | −120–165s (3.14 job 5m15s → ~3m30s; critical path moves to 3.11) | −100–125s | Revert marker → FULL. Fail-closed default unchanged. | One FULL with the surface; a second independent FULL after; compare against a concurrent 3.11 FULL for drift. |
| P1-2 | **Control-plane tier**: control-plane-only PRs run the 5 control-plane files + release-v061 checker-self-test/CI-shape subset on 3.11 + normal package tail (release checker + attestation). Product PRs unchanged. Unknown → full. | `ci_risk_tier.py` rules, `ci.yml` guards, control-plane suite definition | Fail-closed by construction: only exact control-plane path sets take the fast branch; any unknown/unset tier → full. Release checker still runs on every tier. | Control-plane PRs: 6m27s → **~2.5–3.5 min** | ~989s → ~90–150s per control-plane PR | The classifier default remains full; remove the rule → full. | One control-plane PR canary + one product PR canary. |
| P1-3 | **Package tail stays on the critical path unchanged** — no change; the package job (release checker + attestation) is the reuse-gate's foundation and must not be split. | — | — | — | — | — | — |

## 15. P2 recommendations — require more evidence

| # | Proposal | Files/surfaces affected | Safety argument | Wall-clock impact | Runner-minute impact | Rollback / fail-closed | Evidence still needed |
|---|---|---|---|---|---|---|---|
| P2-1 | **Split `test_release_v061.py`** into: authoritative release contract (mutation + version + CLI + docs groups — stays in release/package surface) vs checker self-tests (control-plane-only). Rename-away from `v061` label. | `test_release_v061.py` (structure only) | Checker remains authoritative; only the checker-wiring self-tests move. | 0 (already post-#60-optimized) | ~0 | File split is a rename — revertable. | Evidence that self-tests never fail on product-only changes (checker-change history). |
| P2-2 | **Reduce deep E2E redundancy** — evaluate whether `dataset_end_to_end_regression` (96) + `v060_integrated_e2e` (47) + `v070_integrated_e2e` (13) can share one altitude while preserving the three distinct failure modes; possible module-level shared chain fixtures. | The 3 E2E files | Keep all failure modes; share only fixture construction. | −15–20s (v060_integrated_e2e is per-test the most expensive) | −45–60s | Revert fixture sharing. | Failure-mode separation proof; a controlled experiment. |
| P2-3 | **`test_release_v061` CLI subprocess block** (≈20 tests at 0.58–1.8s) — evaluate a single subprocess that snapshots all helps in one CLI process vs the current per-command spawns. | `test_release_v061.py` CLI group | Same assertions, one interpreter startup. | −10–15s per env | −30–45s | Revert to per-command. | Verify the CLI has no cross-command state. |
| P2-4 | **Delete-candidate evidence file** — none proposed today; this slot stays open for any future file whose contract demonstrably retires, with the §4 test as the gate. | — | — | — | — | — | Requires explicit proof of unreachable behavior + no dependent contract + no release-boundary narrowing. |

---

## 16. Estimated savings matrix

**Per ordinary product PR (FULL):**

| Scenario | pytest runner-minutes | Whole-job runner-minutes | Wall clock | Notes |
|---|---|---|---|---|
| Current (run 31368693999) | 802s (13.4 min) | ~989s (16.5 min) | 6m27s | 3 jobs × ~263–276s pytest |
| +P0-1 (PyArrow FULL → sensitive surface) | −263s | −263–299s | −12–18s | bottleneck moves to 3.14 |
| +P0-2 (PIT harness) | −75–90s | −75–90s | −25–30s | on the 3.14 critical path after P0-1 |
| +P0-3 (portability out of FULL) | −20s | −20s | ~0 | minor |
| +P1-1 (3.14 compatibility surface) | −100–125s | −100–125s | −120–165s | critical path moves to 3.11 |
| **P0+P1 total** | **≈ −460–500s** | **≈ −460–535s** | **≈ −40s–2m** | **runner-minutes −47–54%; wall clock 6m27s → ≈5m45s–6m** |
| +P2-2/P2-3 (E2E + CLI block) | −75–105s | −75–105s | −15–20s | later, evidence-gated |

**Per control-plane PR (after P1-2):** wall clock **6m27s → ~2.5–3.5 min**; runner-minutes **~989s → ~90–150s** (−85–90%).

**Post-merge reuse path (unchanged by this audit):** jobs 13–24s (run 31366165407), `POST_MERGE_REUSE=true`. Separate metric from PR/control-plane FULL — verified-reuse attestations still require the FULL matrix on PRs, so nothing above reduces what a PR must prove.

**Honest statement of the wall-clock ceiling:** the product FULL wall clock cannot go below ≈ max(3.11 whole job, 3.14 surface job, package tail) ≈ **5m45s** without either (a) shrinking the 3.11 job itself or (b) moving the package tail off the critical path — both are further P2 work. The dominant saving of P0/P1 is runner-minutes and the control-plane PR path, not product-PR wall clock.

---

## 17. Risks / false-optimization traps

1. **"Removing PyArrow FULL saves its entire pytest duration"** — false. The critical path moves to `test (3.14)` (§6): the wall-clock saving is 12–18s; the runner-minute saving is 263–299s. Any implementation PR must quote the right number.
2. **Filename age ≠ obsolete** — every `*_v02/v03/v051/v060/v061/v070` file protects a reachable current contract (§11). `test_options_v02.py` is backward compatibility for a format still read; `test_release_v061.py` is the live release-checker contract. No `DELETE_CANDIDATE` is justified today.
3. **The release checker pins the CI topology** — `test_release_v061.py` (`release_checker_fails_when_ci_matrix_changes`, `portability_job_loses_full_suite_step`, `...full_suite_step_loses_pytest`, pin assertions) and `test_v061_ci_auditability.py` assert the exact workflow shape, step names, and the literal `run: python -m pytest` adjacency. **Every topology change must update the checker contract in the same PR** or CI fails closed — by design. This is the main implementation cost of P0-1/P1-1.
4. **The reuse gate depends on the FULL shape** — the attestation (`ci_full_attestation.json`) is created only on PR FULL runs; the post-merge verifier proves tree equivalence to a verified PR FULL. Narrowing an environment's *contents* is fine (same tree, different validation); narrowing the *attestation* (e.g., declaring a control-plane PR FULL when it ran a subset) would silently weaken the gate. Control-plane PRs must keep creating attestations only when they truly ran FULL.
5. **Runner variance can mask regressions and fake wins** — 2× portability variance and 4m19s↔7m36s 3.11 variance observed. All P0/P1 acceptance must use ≥2 independent FULL runs.
6. **The 35.1s frozen regression surface in the PyArrow job is deliberate** — sample-generation fixture chains build canonical Parquet identity; that is PyArrow-sensitive work, not a duplicate to delete (its *second* execution inside the FULL step is the duplicate).
7. **`v060_integrated_e2e`'s 3.7s subprocess tests are genuine integration** — collapsing them into in-process tests would change the failure mode (CLI wiring). Only fixture-level sharing (P2-2) is on the table.
8. **docs_fast package closure is load-bearing** — run 31361918221 failed at the release checker under docs_fast pre-#63 (`ModuleNotFoundError: pandas`); #63's runtime bootstrap is what makes docs-only CI pass today. Segmentation must never assume the checker can run without its runtime.
9. **7 skipped tests are environment-dependent, not portfolio noise** — symlink/junction/tzset skips differ per OS; counts are stable (3,730 passed everywhere) and are not a reduction lever.
10. **"2–3 minutes" for control-plane is not forced** — the evidence floor is ~60–120s subset + ~54s package tail + slack ≈ 2.5–3.5 min. Claim less than the floor and the rollout will miss its own estimate.

---

## 18. Proposed rollout sequence (report only)

1. **This audit** — docs-only (no behavior change). Baseline recorded at run 31368693999.
2. **P0-1 (PyArrow narrowing) + its checker-contract updates in one PR** — highest-confidence, no-coverage-loss; includes the `v060_portability` out-of-FULL change. Requires: release-checker contract update in the same PR, 2 independent FULL validations, durations comparison vs this audit's numbers.
3. **P0-2 (PIT harness) alone** — same assertions, cheaper fixtures; local timing + 1 FULL.
4. **Measure again** (durations + whole-job table, ≥2 runs) before any P1 work.
5. **P1-2 (control-plane tier) alone** — classifier rule + suite definition + canaries (1 control-plane PR, 1 product PR, 1 docs PR).
6. **P1-1 (3.14 compatibility surface) alone** — after control-plane tier is stable; requires the §9 surface definition and 2 FULLs.
7. **Measure again; then P2 evidence-gathering** (release_v061 split, E2E fixture sharing, CLI single-process block) — each as its own PR with independent validation.
8. **Resume Partial Reuse V2 evidence/gating work** on top of the new measured baseline.

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

The single changed file in this PR is `docs/test_portfolio_audit_v1.md`.
