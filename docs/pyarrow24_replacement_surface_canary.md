# PyArrow24 Replacement Surface Measurement Canary — PR #67

Measurement-only canary for Test Portfolio Audit V1 (#66) recommendation **P0-1**:
replace the `portability-pyarrow24` job's duplicate FULL pytest suite with the
PyArrow-sensitive replacement subset **C**.

**This PR is docs-only in its final tree.** The workflow modification used for
measurement was TEMPORARY and is fully reverted at the final head
(`git diff` vs base on `.github/workflows/ci.yml` is empty). No production CI
behavior change reaches main.

---

## 1. Purpose

Measure the exact proposed P0-1 replacement surface (six PyArrow-sensitive
files, 711 collected tests) on the actual GitHub Actions PyArrow 24 runner,
inside the real workflow, so the net P0-1 saving is derived from a same-run
measurement instead of the audit's unmeasured estimate.

## 2. Exact audited base

`0be7276b115dfe5d9703281838617137758f3c44` (main after PR #66, audit v1
merged). No base drift.

## 3. Temporary measurement head

`3042fa30d67cae2485feaccc166c18a01bcbb19d` — a single temporary commit
`ci: measure PyArrow24 sensitivity subset` that added exactly one measurement
step to `portability-pyarrow24`, placed immediately after the existing
release-checker-pinned FULL step (`Run full offline suite under PyArrow 24.0.0`)
and before `FULL tests reused from verified PR`. The existing production steps
remained byte-for-byte unchanged.

## 4. Exact GitHub Actions run

- **Run ID:** `31380992389` (attempt 1, `event=pull_request`, **success**)
- **Portability job ID:** `93430905373`
- **Package job ID:** `93432493834`
- **Tier:** `tier=full`, `full_matrix_required=true` (control-plane change path)
- **FULL attestation:** created and uploaded normally (this temporary head
  really ran the complete current V1 FULL contract); `Post-merge FULL reuse
  proof` skipped (PR event). Artifacts: `market-vault-full-ci-attestation-3042fa3…-attempt-1` + package audit artifact (total 2).

## 5. Environment

GitHub Actions `ubuntu-latest`, Python 3.11 (portability job), `pyarrow==24.0.0`
(pinned and asserted before measurement), package install `.[dev]`.

## 6. A/B/C surface definitions

| Tag | Surface | Files |
|---|---|---|
| A | existing targeted portability | `tests/test_v060_portability.py` |
| B | existing canonical/frozen regression | `tests/test_canonical_reader.py`, `tests/test_sample_generation_core.py`, `tests/test_sample_generation_cli.py` |
| C | proposed PyArrow-sensitive replacement subset (measured) | the six files in §7 |

A and B were **not modified**; the temporary canary ran `A + B + FULL + C` in
one portability job (production shape is `A + B + FULL`; proposed P0-1 shape is
`A + B + C`).

## 7. C exact file list

```
tests/test_canonical_materialization_v03.py
tests/test_canonical_builder_v03.py
tests/test_dataset_materialization.py
tests/test_verified_dataset_reader.py
tests/test_pit_sample_assembly.py
tests/test_dataset_end_to_end_regression.py
```

## 8. Expected vs actual collected count

Expected (audit inventory): 78 + 60 + 143 + 235 + 99 + 96 = **711 collected**.

Actual (CI): **711 collected → 706 passed, 5 skipped**. The 5 skips are the
known environment-dependent skips (symlink / timezone availability), consistent
with the FULL run's 7 skips; no unexpected compatibility failure. All six
intended files executed.

## 9. FULL PyArrow measurement

Step `Run full offline suite under PyArrow 24.0.0` (the release-checker-pinned
block, unmodified):

| Item | Value |
|---|---|
| start | 2026-08-10 10:53:14Z |
| end | 2026-08-10 10:57:37Z |
| **step wall duration** | **4m23s (263s)** |
| **pytest reported duration** | **262.92s** |
| result | 3730 passed, 7 skipped |

## 10. C subset measurement

Step `Measure proposed PyArrow24 sensitivity subset (canary only)`:

| Item | Value |
|---|---|
| start | 2026-08-10 10:57:37Z |
| end | 2026-08-10 10:59:03Z |
| **step wall duration** | **1m26s (86s)** |
| **pytest reported duration** | **85.07s** |
| result | **711 collected → 706 passed, 5 skipped** |

A/B durations recorded from the same run (logs): A = **10 passed in 0.89s**;
B = **3 passed in 0.95s** + **178 passed in 34.98s** (= 181 tests, ≈35.9s).

## 11. Same-run savings equation

The temporary job measured `A + B + FULL + C`; production is `A + B + FULL`;
proposed P0-1 is `A + B + C`. A and B exist before and after and **cancel** —
they are never subtracted.

- `measured_canary_job` (whole portability job) = **414s** (10:52:12 → 10:59:06)
- `projected_current_job ≈ canary_job − C_step = 414 − 86 = 328s` — sanity:
  matches the audit's measured main-baseline portability job (327s, run
  31368693999) → methodology consistent.
- `projected_narrowed_job ≈ canary_job − FULL_step = 414 − 263 = 151s`
- **`estimated_whole-job_saving ≈ FULL_step − C_step = 263 − 86 = 177s`**
- **`estimated_pytest_saving ≈ FULL_pytest − C_pytest = 262.92 − 85.07 = 177.85s`**

pytest runtime and step duration are reported separately throughout; the two
metrics agree to ≈1s and are never mixed.

## 12. Projected current vs narrowed portability duration

| Scenario | Portability whole job | Delta |
|---|---|---|
| current (audit baseline, run 31368693999) | 327s | — |
| current (same-run projection from canary) | ≈ 328s | +1s (variance, consistent) |
| **narrowed (P0-1, same-run projection)** | **≈ 151s** | **−177s (−54%)** |

Note: the audit's unmeasured estimate was 116–131s / net 195–215s; the
measurement contradicts the C-runtime estimate (C = 85–86s, not 50–65s) and
therefore the narrowed-job figure. **The measured net saving is ≈ 177s** (not
195–215s). The audit's gross upper bound (263s) is unchanged.

## 13. Runner-minute impact

Per FULL run, the portability environment is charged **−177s** (whole-job;
−177.85s pytest-only).

The canary total (1052s = 280 + 300 + 414 + 58) is **not** a production
baseline: it contains the extra C measurement step. Projected production
totals (same-run):

- canary total = **1052s**
- projected current production total: 1052 − 86 (C step) = **966s**
- projected narrowed production total: 1052 − 263 (FULL step) = **789s**
- **P0-1 net runner saving: 966 − 789 = 177s**
- **percentage: 177 / 966 ≈ 18.3%**

Audit-baseline statement (kept, separate): 989 → 989 − 177 = **812 (−17.9%)**.

No other environment is affected (A/B cancel; the 3.11/3.14 jobs are unchanged
by P0-1).

## 14. Workflow critical-path interpretation

The temporary 414s portability job is the **canary** job (it includes the
extra C step) — it is NOT the current production baseline.

Same-run projections (this run's other jobs: 3.11 = 280s, 3.14 = 300s,
package = 58s):

- projected current portability: 414 − 86 (C step) = **328s**
- projected narrowed portability: 414 − 263 (FULL step) = **151s**
- same-run current critical path: max(280, 300, 328) = **328s**
- same-run narrowed critical path: max(280, 300, 151) = **300s**
- **run-local pre-package critical-path improvement ≈ 28s**; the package tail
  (58s) is approximately unchanged.

Audit-baseline interpretation (retained): ≈ 12–18s in that sample (6m27s →
≈ 6m09s). **Runner variance explains the difference**: portability ran 414s
here vs 327s in the audit's primary sample, which is why the same-run
projected critical-path gain (~28s) exceeds the audit-baseline estimate
(~12–18s). A ~1m54s run-local wall-clock saving is NOT claimed — the canary
job's 414s is not a production baseline.

Consistent with the audit's wall-clock analysis: **the dominant P0-1 win is
runner-seconds (−177s), not workflow wall-clock**, which remains bounded by
the 3.14 job.

## 15. Warm-cache limitation

C ran **after** FULL in this canary (same job, same runner, OS/filesystem
caches warmed by the preceding 262s FULL suite). C-after-FULL may underestimate
cold replacement runtime and therefore may slightly overestimate savings.
This measurement is a **canary sample, not a stable acceptance baseline**;
the actual P0-1 implementation PR must measure the final natural ordering
(C without a preceding FULL) again before acceptance. One sample does not prove
stable performance.

## 16. Implementation recommendation

**Recommend proceeding to the actual P0-1 implementation**, subject to the
warm-cache caveat and the implementation PR's own re-measurement:

- C passes completely under PyArrow 24.0.0 — 706 passed, 5 environment-dependent
  skips, no unexpected compatibility failure.
- All six intended files executed; collected count exactly matches the audit
  inventory (711).
- Estimated runner saving remains materially positive (≈177s ≈ 3 minutes per
  FULL on the portability environment).

Required implementation-PR constraints (unchanged from audit v1): release
checker contract updates in the same PR (the checker pins the workflow shape),
keep the pin + assert + A + B steps, at least two independent FULL validation
runs, and fail-closed rollback semantics.

## 17. Explicit non-actions

- NO workflow change reaches main (the temporary measurement step is fully
  reverted; `.github/workflows/ci.yml` is byte-identical to base at the final
  head).
- NO test is deleted.
- NO test is skipped in production.
- NO release checker is changed.
- NO V1 attestation contract is changed.
- NO Partial Reuse V2 behavior is activated.
- NO release/tag/assets are touched.

The temporary workflow commit exists only in PR history as measurement
evidence. The final tree contains exactly one changed file:
`docs/pyarrow24_replacement_surface_canary.md`.
