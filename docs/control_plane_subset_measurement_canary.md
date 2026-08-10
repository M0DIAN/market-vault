# Control-plane subset measurement canary (PR #70)

## Purpose / non-production scope

Measurement canary only. This PR measures the runtime of a **conservative
control-plane validation surface** (six test files) on the
CURRENT OPTIMIZED FULL CI BASELINE POST P0-1 + P0-2.

It is NOT the P1-2 control-plane tier implementation. No production CI policy
change survives in this PR's tree: the temporary measurement step in
`.github/workflows/ci.yml` was removed again and the final diff is
documentation-only.

The canary answers five questions:

1. How many tests does the conservative control-plane surface collect?
2. How long does it take on Python 3.11 on a real GitHub runner?
3. Is running the ENTIRE `tests/test_release_v061.py` cheap enough to avoid a
   brittle `-k` / hand-picked release-checker selector in the future P1-2
   implementation?
4. What runner reduction would such a surface imply relative to the sealed
   current FULL baseline?
5. Is the result strong enough to proceed to a real control-plane-tier
   implementation canary?

## Exact frozen base

`12d78b21a008d7ed9665b9d5b21bb639c6517394`
(tree `ad77af6435af9c1e552bff3c9202c8366fecafc7`)

## Temporary measurement head

`1a2d8cb52178c75aabab468fdf609c3facabd6ca`
(one temporary workflow change: a single measurement step in the `test` job,
after `Compile Python`, before `Run offline tests`, Python 3.11 only, guarded
to skip docs-fast / package-docs / post-merge-reuse runs)

An earlier head `b049f8b2cff8bcba240fc27b1eff6077000a2894` carried the same
step with a YAML authoring bug (plain scalar folded the `\` continuations into
one argument), causing the step itself to fail instantly (`file or directory
not found`) on its only run (run 31409877341, failure recorded, no evidence
collected). The step was fixed without touching anything else; all measurement
evidence below comes from the corrected exact head `1a2d8cb…`.

## Exact six-file conservative surface

- `tests/test_ci_risk_tier.py`
- `tests/test_component_aware_tiers.py`
- `tests/test_ci_post_merge_reuse.py`
- `tests/test_audit_pr.py`
- `tests/test_v061_ci_auditability.py`
- `tests/test_release_v061.py`

None of these test files was modified.

## Why whole `test_release_v061.py` was intentionally included

The first five files are the audited control-plane cluster. Instead of a
hand-picked ~40–60-test `-k` selector from `test_release_v061.py`, the canary
measures the ENTIRE current file — the conservative superset. If the whole file
is still cheap, future P1-2 should prefer the whole-file conservative contract
over a fragile hand-maintained selector expression.

## Local result (same machine, before pushing)

`808 passed in 141.95s` (collected 808, passed 808, skipped 0).
Local cold runs are not comparable to the runner; they bound the surface size,
not the CI time.

## Classifier (temporary head)

`tier=full`, `reason=workflow_or_registry_mutation_requires_full`,
`full_matrix_required=true` — the current classifier's actual workflow/registry
mutation label (recorded as observed, not assumed).

## Attempt 1 — run 31410427548, attempt 1, exact head `1a2d8cb…`

Synthetic merge SHA `34dd6eb22b985e05adf1b441da09b9e30b24334a`.
All four formal jobs SUCCESS.

| Job | Whole s | Detail |
|---|---|---|
| test (3.11) | 283 | conservative subset: **808 passed, 40.28s pytest, 40s step wall** · FULL offline: 3753 passed / 7 skipped, 216.65s pytest |
| test (3.14) | 273 | FULL offline: 3753 passed / 7 skipped, 291.15s pytest |
| portability-pyarrow24 | 127 | A: 10 passed / 0.86s · B: 3 passed / 1.11s + 178 passed / 43.62s · C: 706 passed / 5 skipped / 45.27s (exact six-file surface, 711 collected) |
| package | 60 | release checker `RELEASE_CHECK_OK version=0.7.0` · built `market_vault-0.7.0.tar.gz` + `market_vault-0.7.0-py3-none-any.whl` · SHA256SUMS verification OK · V061_PACKAGE_AUDIT_OK |

Runner total **743s** · workflow wall **406s**.
V1 attestation artifact created (CI-only, 451 B):
`market-vault-full-ci-attestation-1a2d8cb…-attempt-1`.
Package artifact CI-only: `market-vault-package-1a2d8cb…-attempt-1`.
These are NOT formal v0.7.0 release assets/hashes.

## Attempt 2 — run 31410427548, attempt 2, SAME exact head (one complete rerun, no new commit)

All four formal jobs SUCCESS.

| Job | Whole s | Detail |
|---|---|---|
| test (3.11) | 299 | conservative subset: **808 passed, 40.53s pytest, 41s step wall** · FULL offline: 3753 passed / 7 skipped, 225.00s pytest |
| test (3.14) | 230 | FULL offline: 3753 passed / 7 skipped, 204.25s pytest |
| portability-pyarrow24 | 106 | A: 10 passed / 0.92s · B: 3 passed / 1.02s + 178 passed / 34.62s · C: 706 passed / 5 skipped / 39.78s (exact six-file surface, 711 collected) |
| package | 62 | release checker `RELEASE_CHECK_OK version=0.7.0` · built tar.gz + whl · SHA256SUMS verification OK · V061_PACKAGE_AUDIT_OK |

Runner total **697s** · workflow wall **369s**.
V1 attestation artifact created (CI-only):
`market-vault-full-ci-attestation-1a2d8cb…-attempt-2`.

## Measurement interpretation

### CONSERVATIVE CONTROL-PLANE PYTEST SURFACE — two-run observed range

**808 collected · 808 passed · 0 skipped · 40.28–40.53s pytest
(step wall 40–41s)**

Two executions are not a stable benchmark; treat as observed range only.

### Comparison against CURRENT OPTIMIZED FULL CI BASELINE POST P0-1 + P0-2

CURRENT OPTIMIZED FULL CI BASELINE POST P0-1 + P0-2 two-run observed range:

| Metric | Range | Midpoint |
|---|---|---|
| test (3.11) | 254–264s | ~259s |
| test (3.14) | 265–283s | ~274s |
| portability | 108–111s | ~109.5s |
| package | 52s | 52s |
| runner total | 689–700s | ~694.5s |
| workflow wall | 332–355s | ~343.5s |

Python 3.11 FULL pytest observations: 227.05s, 237.16s (and 216.65s / 225.00s
on this canary's FULL runs — all observed, none a stable guarantee).

The old 989 runner-second / 387s Test Portfolio Audit result is historical
reference only. The legacy ~63 minute observation is historical context only.

### Measured reduction (subset vs FULL on the same runner, same run)

| Run | FULL 3.11 pytest | subset pytest | pytest saving | % reduction |
|---|---|---|---|---|
| Attempt 1 | 216.65s | 40.28s | 176.37s | ~81% |
| Attempt 2 | 225.00s | 40.53s | 184.47s | ~82% |

Two-run observed range: saving ~176–184s, ~81–82% of FULL 3.11 pytest time.

### MODELLED 3.11 control-plane job duration (MODELLED / NOT YET PRODUCTION-MEASURED)

Observed 3.11 whole-job overhead (job wall minus FULL pytest): attempt 1
283 − 216.65 ≈ 66s; attempt 2 299 − 225.00 ≈ 74s (two-run overhead range
~66–74s). Adding the measured subset pytest (~40.3–40.5s) gives a MODELLED
3.11 control-plane job of roughly **107–115s** — approximately the observed
portability job (106–127s) in scale.

This is explicitly MODELLED, not a production measurement: the real P1-2
topology does not exist yet, and its package lightweight closure / dependency
shape has not been measured as a production control-plane tier. The old audit
hypothesis of 2.5–3.5 minutes remains a hypothesis until the actual
implementation canary.

### Runner-variance caveat

Runner wall-clock is subject to queue, cache, and machine variance; the
portability job alone varied 106–127s across the four FULL runs observed this
session. Do not read precision into two-sample ranges.

### Warm/cold cache caveat

Package-install caching and pip cache warmth vary between runs; the subset
step itself imports no external heavy state (same deps as FULL), so its
40s class is stable relative to FULL, but absolute wall times remain observed.

## No production behavior changed

- `.github/workflows/ci.yml` restored byte-identical to the frozen base
  (zero diff vs `12d78b2…:ci.yml`; removal commit, no rewrite).
- No V1/V2 evidence-contract change, no release change, no tag/Release change.
- v0.7.0 remains immutable; canary artifacts are CI-only.

## Recommendation

**A. CONSERVATIVE WHOLE-FILE SURFACE ACCEPTABLE** — proceed with a
conservative whole-file control-plane tier design for P1-2:

- the six-file surface (808 tests) is materially smaller than FULL
  (~81–82% pytest-time reduction on 3.11),
- both exact-head executions pass with 808/808 green,
- `test_release_v061.py` does not make the surface disproportionately
  expensive (whole six-file run ≈ 40.3–40.5s; the release checker itself is a
  separate ~1s-scale step and is not a driver of the surface cost),
- no safety contract was weakened.

Avoiding a brittle `-k` selector is justified: the entire file is cheap enough
that the whole-file conservative contract is the better P1-2 shape. The
narrower release-v061 selector study (option B) is not needed.

This document does not overwrite `docs/test_portfolio_audit_v1.md`; that
document remains historical evidence.
