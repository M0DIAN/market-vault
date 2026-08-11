# Python 3.14 Compatibility Surface Canary — Measurement Report (PR #73)

Measurement-only canary for the Python 3.14 compatibility surface proposed
as P1-1 in `docs/test_portfolio_audit_v1.md` (§9 / §9.1 / §14 / §17).

- **Frozen base:** `9aec7a204614f1a65066a2ed25dfb8857a72bb44` (origin/main, "tests: exercise control-plane fast path (#72)")
- **Temporary measurement head:** `2d1ee775a5163ba3989b5d8eb77e9d2726f60d47`
  (one commit on top of base: the canary step + the frozen manifest)
- **Final head (this PR):** docs-only revert of the temporary changes, so the
  final base→head diff is exactly this file.

**Audit source:** `docs/test_portfolio_audit_v1.md` §9 (Python 3.14
compatibility analysis), §9.1 (A/B/C quantities), §14 (P1-1), §17 (risks).

**Mode: measurement only.** No production Python 3.14 CI narrowing survives
in the final tree. The temporary workflow step and manifest were removed and
`.github/workflows/ci.yml` was restored byte-identical to the frozen base
(zero diff verified against `9aec7a2`). If evidence supports narrowing, the
production implementation belongs to PR #74.

---

## 1. Temporary measurement head

The temporary head `2d1ee77` added exactly two files over the base:

1. `ci/python314_compatibility_surface_canary.txt` — the frozen candidate
   manifest (one exact test path per line, sorted, unique, tracked files
   only; no globs, no `-k`, no markers, no directories).
2. `.github/workflows/ci.yml` — one additive step
   `Measure Python 3.14 compatibility candidate`, placed after
   `Compile Python` and before the existing unchanged `Run offline tests`,
   guarded by
   `env.CI_TIER == 'full' && matrix.python-version == '3.14' && env.POST_MERGE_REUSE != 'true'`.

The step read only the frozen manifest (`mapfile` + `grep -Ev` comment/blank
filter), printed the exact list (`PY314_SURFACE_FILES=42`), and ran:

```
python -m pytest "${PY314_FILES[@]}" -q --durations=200
```

The existing `Run offline tests` (FULL pytest) was unchanged and executed
after the canary step on the 3.14 leg.

**Classifier gate (§10):** the real classifier run locally on
base → temporary head returned `tier=full`, `full_matrix_required=true`
(`reason=changed_path_not_in_docs_scope`; the manifest path
`ci/python314_compatibility_surface_canary.txt` is outside the control-plane
allowlist — only `ci/components.toml` is eligible). CI logs on both attempts
confirm `tier=full` / `full_matrix_required=true` on the 3.14 leg. The
temporary head therefore executed genuine FULL.

---

## 2. Candidate surface derivation

### 2.1 Mandatory explicit core (§4 of the brief)

All 26 required files are present in the candidate (see §4 list below).

### 2.2 Static-sensitivity expansion method (§5 of the brief)

Mechanical inspection of every tracked `tests/test_*.py` (51 files) for
families A–F:

| Family | Pattern | Evidence |
|---|---|---|
| A. identity/hash | `hashlib`, `sha256`, `sha1`, `digest/hexdigest` where identity semantics are tested | literal/frozen digests, committed static artifacts, cross-version identity contracts |
| B. binary/runtime deps | direct imports of `pandas`, `duckdb`, `pyarrow`, `numpy` | direct consumers of binary-wheel behavior on 3.14 |
| C. filesystem/runtime | `pathlib`, `symlink`, `junction`, `os.link`, `os.replace`, relocation | symlink/junction/link creation, detection, skip semantics |
| D. timezone/runtime | `time.tzset`, `zoneinfo`, `timezone`, datetime conversion | local-timezone/tzset/zoneinfo semantics and conversions (fixture clocks excluded) |
| E. import/lazy-import | `sys.modules`, `importlib`, `__all__`, module loading | lazy-import guarantees, module-machinery tests, public-API pins |
| F. subprocess/CLI | `subprocess`, `python -m market_vault` | CLI process invocation |

Per-file disposition: **INCLUDE** when any family has genuine evidence,
**EXCLUDE** only with a documented concrete reason (below). Default INCLUDE
when uncertain — safety beats hitting a percentage target.

### 2.3 Included additions (16 files beyond the mandatory core)

| File | Evidence |
|---|---|
| `test_v060_portability.py` | A: frozen `FROZEN_RELATIVE_PLAN_SHA256` reproducibility contract |
| `test_chronological_splits.py` | A: 5 literal sha256 digests; D: `zoneinfo`/local-timezone fixture behavior |
| `test_sample_generation_contract.py` | A: frozen `BASE_IDENTITY` / `PIT_SAMPLE_KEY` constants |
| `test_sample_generation_core.py` | A: frozen `FIXTURE_GENERATION_ID` + static PyArrow25-produced base64 canonical artifact ("runtime- and machine-independent" contract) |
| `test_dataset_feature_execution.py` | D: `time.tzset()` local-timezone-independence test; E: `importlib`/`sys.modules` module-machinery tests; A: content pins |
| `test_dataset_label_execution.py` | E: `__all__` public-API pin; A: content pins |
| `test_dataset_transform_registry.py` | E: `test_resolve_never_imports_transform_ref` `sys.modules` lazy-import assertion |
| `test_dataset_manifest_core.py` | E: `test_public_api_keeps_internals_private` `__all__`/`hasattr` pins; D: timezone-aware error contracts; B: numpy |
| `test_feature_label_specs.py` | E: `__all__` pins (`dataset`, `spec_models`, `specs`); B: numpy; A: content-id identity |
| `test_dataset_materialization.py` | C: symlink/junction creation + skip semantics; B: direct `pyarrow` import; A: hashlib |
| `test_dataset_catalog_builder.py` | C: symlink/junction creation semantics; E: `__all__` pin |
| `test_dataset_catalog_materialization.py` | C: success-path symlink assertion; E: `__all__` pin; A: hashlib |
| `test_dataset_catalog_reader.py` | C: symlink/junction/rename semantics; E: `__all__` pin; A: hashlib |
| `test_canonical_reader.py` | B: direct `pyarrow.parquet` import, parquet read behavior; pairs with the core canonical reader family |
| `test_options_v02.py` | B: direct `duckdb` import (SQL-engine wheel interaction); §11 KEEP_COMPAT v02 legacy-format contract |
| `test_moomoo_sdk.py` | E: `importlib` lazy-load machinery tests |

### 2.4 Excluded files with documented reasons (9 files)

| File | Reason the matches are not Python-version-sensitive |
|---|---|
| `test_audit_v03.py` | UTC fixture-clock datetimes (`datetime.now(timezone.utc)`) + in-process pandas fixture construction only; no tzset/zoneinfo semantics, no hard-coded identity, no symlink, no module machinery; audit §9 does not name it |
| `test_backfill_v03.py` | same as `test_audit_v03.py` |
| `test_inventory_v03.py` | same as `test_audit_v03.py` |
| `test_canonical_builder_v03.py` | all hash assertions self-consistent within the run (0 literal digests); the cross-version canonical-build identity is pinned by the static-artifact test in `test_sample_generation_core.py` (included) and `test_canonical_materialization_v03.py` (core) |
| `test_dataset_catalog_contract.py` | audit §9's explicit non-sensitive bulk ("catalog contract/docs"); sha256 matches are format-level assertions; datetimes are fixed-offset; no symlink/literals/module machinery |
| `test_dataset_orchestration.py` | sha256 pins self-consistent; fixture datetimes; in-process pandas; no symlink/junction, no zoneinfo/tzset, no `sys.modules`/`__all__`, no subprocess |
| `test_collector.py` | pandas fixture construction only |
| `test_normalization.py` | pandas fixture construction only |
| `test_quality.py` | pandas fixture construction only |

### 2.5 Frozen manifest

`ci/python314_compatibility_surface_canary.txt` (temporary, removed):

- `PY314_SURFACE_FILE_COUNT` = **42**
- `PY314_SURFACE_SHA256` = **11208a62a7c4c4ced26330a5a265157596d64b6ca662b3dbeea4c5eea59217ed**

Exact list (sorted, one per line):

```
tests/test_audit_pr.py
tests/test_calendar_v03.py
tests/test_canonical_materialization_v03.py
tests/test_canonical_reader.py
tests/test_chronological_splits.py
tests/test_ci_post_merge_reuse.py
tests/test_ci_risk_tier.py
tests/test_component_aware_tiers.py
tests/test_dataset_catalog_builder.py
tests/test_dataset_catalog_cli.py
tests/test_dataset_catalog_materialization.py
tests/test_dataset_catalog_reader.py
tests/test_dataset_cli.py
tests/test_dataset_end_to_end_regression.py
tests/test_dataset_feature_execution.py
tests/test_dataset_label_execution.py
tests/test_dataset_manifest_core.py
tests/test_dataset_materialization.py
tests/test_dataset_transform_registry.py
tests/test_deprecation_compatibility_v051.py
tests/test_feature_label_specs.py
tests/test_intraday_audit_v03.py
tests/test_leakage_threat_model.py
tests/test_moomoo_sdk.py
tests/test_options_v02.py
tests/test_pit_sample_assembly.py
tests/test_release_v061.py
tests/test_sample_generation_cli.py
tests/test_sample_generation_contract.py
tests/test_sample_generation_core.py
tests/test_snapshot_safety.py
tests/test_timestamp_semantics_v03.py
tests/test_v060_integrated_e2e.py
tests/test_v060_portability.py
tests/test_v061_ci_auditability.py
tests/test_v061_cli_usability.py
tests/test_v070_artifact_client_catalog.py
tests/test_v070_artifact_client_foundation.py
tests/test_v070_artifact_client_readers.py
tests/test_v070_integrated_e2e.py
tests/test_v070_python_client_examples.py
tests/test_verified_dataset_reader.py
```

### 2.6 Collection counts

Local collect-only on the frozen base (Python 3.14, ambient deps):

- `PY314_SURFACE_COLLECTED` = **3340**
- `FULL_COLLECTED` = **3807**
- `SURFACE_COLLECTION_SHARE` = **87.7%** (3340 / 3807)

The audit's §9.1 design estimated 60–70%. The mechanically derived,
safety-first surface is larger because genuine evidence (literal digests,
`sys.modules` lazy-import pins, `__all__` public-API pins, `tzset`/zoneinfo
behavior) was found in 4 of the 5 file categories the audit's estimate had
flagged as droppable bulk (`chronological_splits`, `transform_registry`,
`manifest_core`, `sample_generation_contract`); only `dataset_catalog_contract`
stayed excluded. The 87.7% share is the actual mechanical result — no tests
were removed to hit a percentage target.

### 2.7 Mandatory sensitivity family coverage (§3 of the brief)

| Family | Represented by |
|---|---|
| Syntax / import sensitivity | `v070_artifact_client_*` (sys.modules lazy-import), `release_v061`, `dataset_transform_registry`, `dataset_feature_execution`, `moomoo_sdk` |
| pathlib / filesystem | `dataset_cli` (junction/symlink), `canonical_materialization_v03` (symlink skips), `verified_dataset_reader` (symlink relocation), `v061_cli_usability`, `dataset_materialization`, `dataset_catalog_builder/materialization/reader` |
| datetime / timezone | `timestamp_semantics_v03`, `intraday_audit_v03`, `calendar_v03`, `pit_sample_assembly` (two-clock), `dataset_end_to_end_regression` (tzset), `dataset_feature_execution` (tzset), `chronological_splits` (zoneinfo) |
| subprocess / CLI | `release_v061`, `v060_integrated_e2e`, `sample_generation_cli`, `dataset_cli`, `dataset_catalog_cli`, `v070_integrated_e2e`, `ci_risk_tier`, `component_aware_tiers`, `audit_pr`, `v061_ci_auditability`, `ci_post_merge_reuse` |
| Serialization / identity stability | every hashlib-bearing data file; literal/frozen digests: `v060_portability`, `chronological_splits`, `sample_generation_contract`, `sample_generation_core` |
| Release / package / public API | `release_v061`, `v070_python_client_examples`, `v070_artifact_client_*` |
| Dependency interaction | `deprecation_compatibility_v051` (numpy), `options_v02` (duckdb), `dataset_materialization` / `canonical_reader` (pyarrow) |
| PIT / leakage safety | `pit_sample_assembly`, `leakage_threat_model`, `snapshot_safety` |
| Representative deep E2E | `v060_integrated_e2e`, `dataset_end_to_end_regression`, `v070_integrated_e2e` |

---

## 3. Attempt 1 — run 31446440052 (temporary head `2d1ee77`)

All four formal jobs **SUCCESS**:

| Job | Duration (s) |
|---|---|
| test (3.11) | 247 |
| test (3.14) | 468 |
| portability-pyarrow24 | 164 |
| package | 59 |
| **Workflow raw wall** (started 00:33:13Z → updated 00:42:05Z) | **532** |

Tier on the 3.14 leg (from CI log): `tier=full`, `full_matrix_required=true`.

3.14 steps — canary ran FIRST, then FULL:

| Step | Wall (s) | pytest |
|---|---|---|
| Measure Python 3.14 compatibility candidate | 199 (00:33:46→00:37:05) | 3333 passed, 7 skipped in **196.98s** |
| Run offline tests (FULL, unchanged) | 237 (00:37:05→00:41:02) | 3800 passed, 7 skipped in **236.30s** |

3.11 FULL: 3800 passed, 7 skipped in 217.27s (step wall 218s).

Package: `RELEASE_CHECK_OK version=0.7.0`; V1 attestation created
(artifact 9084876135).

### 3.1 Derived A/B/C (attempt 1)

- `MODELLED_CURRENT_314_JOB` = 468 − 199 (surface wall) = **269s**
- `MODELLED_NARROWED_314_JOB` = 468 − 237 (FULL wall) = **231s**
- `A_JOB_LOCAL_SAVING` = 269 − 231 = **38s** (≈ FULL wall − surface wall = 38s ✓)
- `B_RUNNER_SAVING` = **38s** (P1-1 replaces only the 3.14 FULL leg)
- CURRENT model wall = max(247, 269, 164) + 59 = **328s**
- NARROWED model wall = max(247, 231, 164) + 59 = **306s**
- `C_WALL_SAVING` = **22s** (MODELLED / NOT YET PRODUCTION-MEASURED)

---

## 4. Attempt 2 — run 31446440052 attempt 2 (same exact head `2d1ee77`)

Complete rerun of the same workflow/head; no commit.

All four formal jobs **SUCCESS**:

| Job | Duration (s) |
|---|---|
| test (3.11) | 259 |
| test (3.14) | 442 |
| portability-pyarrow24 | 104 |
| package | 57 |
| **Workflow raw wall** (started 00:43:57Z → updated 00:52:29Z) | **512** |

Tier on the 3.14 leg: `tier=full`, `full_matrix_required=true`.

3.14 steps:

| Step | Wall (s) | pytest |
|---|---|---|
| Measure Python 3.14 compatibility candidate | 186 (00:44:28→00:47:34) | 3333 passed, 7 skipped in **183.97s** |
| Run offline tests (FULL, unchanged) | 226 (00:47:34→00:51:20) | 3800 passed, 7 skipped in **226.08s** |

3.11 FULL: 3800 passed, 7 skipped in 223.23s (step wall 224s).

Package: `RELEASE_CHECK_OK version=0.7.0`; V1 attestation created
(artifact 9085082478).

### 4.1 Derived A/B/C (attempt 2)

- `MODELLED_CURRENT_314_JOB` = 442 − 186 = **256s**
- `MODELLED_NARROWED_314_JOB` = 442 − 226 = **216s**
- `A_JOB_LOCAL_SAVING` = 256 − 216 = **40s** (≈ 226 − 186 = 40s ✓)
- `B_RUNNER_SAVING` = **40s**
- CURRENT model wall = max(259, 256, 104) + 57 = **316s**
- NARROWED model wall = max(259, 216, 104) + 57 = **316s**
- `C_WALL_SAVING` = **0s** (3.11 is the bottleneck; narrowing 3.14 does not
  reduce workflow wall on this run — consistent with audit §9.1's bounded
  estimate) (MODELLED / NOT YET PRODUCTION-MEASURED)

---

## 5. Two-run observed range

Never a stable benchmark — an observed range over two runs only:

| Quantity | Range |
|---|---|
| Candidate pytest | 183.97–196.98s |
| Candidate step wall | 186–199s |
| Modelled narrowed 3.14 job | 216–231s |
| 3.14 runner saving (A = B) | 38–40s |
| Modelled workflow saving (C) | 0–22s |

FULL 3.14 pytest (236.30s / 226.08s) is faster than the audit §9 baseline
(275.66s); runner variance plus the §6 cache/order effect explain the
difference. The audit's P1-1 estimate was −100–125s runner saving; the
measured saving of this surface is 38–40s — under half the estimate.

---

## 6. Cache / order caveat (§16)

The candidate step ran before FULL in the same 3.14 job by design (it makes
the candidate execution representative of the future narrowed path). It may
have warmed filesystem/import state before the following FULL pytest, so the
FULL 3.14 executions here may be slightly optimistic versus an isolated FULL
execution. This biases the estimated replacement saving conservatively (a
faster FULL shrinks the measured 3.14-vs-surface gap). The raw temporary
workflow wall includes candidate + FULL and is not a production performance
number.

## 7. Runner variance caveat (§17.6)

Two exact-head runs showed job-level variance (3.14 job 442s vs 468s,
portability 104s vs 164s, 3.11 247s vs 259s). All acceptance figures must be
read as two-run ranges, not stable benchmarks. The portability swing (104s ↔
164s) also demonstrates how much single-run whole-workflow numbers can move.

---

## 8. V1 attestation boundary (§17 / §10.1)

The temporary measurement head really ran the complete existing formal FULL
contract (FULL pytest ×3 plus the full package chain) in addition to the
canary step. The normal PR FULL V1 attestation was therefore generated by
the existing package job:

**Attempt-2 attestation** (artifact **9085082478**):

| Field | Value |
|---|---|
| schema_version | 1 |
| pr_number | 73 |
| base_sha | 9aec7a204614f1a65066a2ed25dfb8857a72bb44 (exact frozen base) |
| head_sha | 2d1ee775a5163ba3989b5d8eb77e9d2726f60d47 (exact temp measurement head) |
| tier / full_matrix_required | full / true |
| run_id / run_attempt | 31446440052 / 2 |

The Python-3.14 canary step introduced **no new V1 schema meaning**; there
are **no V2 fields** and no V2 evidence artifact of any kind. The attestation
proves the existing formal FULL contract completed — not that the candidate
surface itself is FULL evidence. Attempt-1 attestation: artifact 9084876135
(same head, run_attempt 1).

---

## 9. No production CI behavior change

The final PR tree contains exactly one file: this report. `.github/workflows/ci.yml`
is byte-identical to the frozen base (verified: zero diff against
`9aec7a2`), the temporary manifest is deleted, and no test/scripts/src/package
file changed. The final-head classification is `docs_fast` (expected).
Historical estimates in `docs/test_portfolio_audit_v1.md` are untouched.

---

## 10. Decision and recommendation for PR #74

### Decision: **B — CANDIDATE SURFACE NEEDS EXPANSION / REDESIGN**

The mechanically derived conservative surface (3340/3807 = 87.7% of FULL)
passed both exact-head candidate executions and both exact-head formal FULL
executions, covered every §9 sensitivity family, and weakened no checker /
V1 / product contract. However, per §18, decision A additionally requires
that the candidate be *materially* smaller than FULL and produce a
*meaningful* 3.14 runner saving. Measured:

- the candidate is 87.7% of FULL by collection count (not materially smaller);
- the 3.14 runner saving is 38–40s per FULL (the audit's P1-1 estimate was
  −100–125s; the measured saving is under half of it);
- the modelled workflow saving is 0–22s (3.11 is the bottleneck on attempt 2).

The safety-first derivation kept files the audit's §9.1 design had priced as
droppable non-sensitive bulk, because they carry genuine static evidence
(literal digests, `sys.modules`/`__all__` pins, tzset/zoneinfo behavior). The
resulting surface saves too little runner time to justify the redesign cost.

**Recommendation for #74:** redesign the 3.14 compatibility surface around
the distinction this canary established — genuine cross-version identity
contracts (frozen digests / committed static artifacts, `sys.modules` /
lazy-import semantics, tzset / zoneinfo behavior, `__all__` / public-API
pins, symlink/junction semantics, CLI subprocess wiring, direct
binary-wheel consumers) versus self-consistent in-run content tests whose
assertions cannot differ across Python versions — with a documented
per-file reason for every exclusion, targeting the audit's 60–70% design,
and re-measure with TWO fresh attempts on a NEW head before any production
narrowing. Alternatively, if the conservative surface is preferred, accept
the smaller (−38–40s runner) saving and price #74 accordingly. Do not mix
measurements from different candidate manifests.

---

## 11. Record of local preflight checks (frozen base)

- Candidate collect-only: 3340 collected ✓
- Focused smoke (`release_v061`, `deprecation_compatibility_v051`,
  `timestamp_semantics_v03`, `v060_integrated_e2e`, `pit_sample_assembly`):
  658 passed, 2 skipped ✓
- `python scripts/check_release.py` → `RELEASE_CHECK_OK version=0.7.0` ✓
  (also run after adding the measurement step — the additive step passed the
  checker unchanged, so no checker/contract weakening was needed)
- `python scripts/check_repo_hygiene.py` → passed ✓
- `git diff --check` → clean ✓
- pytest temp preflight: `PYTEST_TEMP_BEFORE_BYTES=2136855855`,
  `PYTEST_TEMP_AFTER_BYTES=0`, `PYTEST_TEMP_REMOVED_BYTES=2136855855`,
  `C_FREE_GB=19.31` ✓

Final status: **PYTHON 3.14 COMPATIBILITY SURFACE MEASUREMENT — READY FOR
INDEPENDENT REVIEW. STOP BEFORE MERGE.**
