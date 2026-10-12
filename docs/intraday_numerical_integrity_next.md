# Intraday numerical integrity and fitting efficiency: Q61–Q63

## Verified baseline and authorized package

Start from main `b0b554a3ee4387a95a9977fd5cade37ede183204`, tree
`a8e9257f5a6ff632535eec8a370c040fdf32d645`, in `M0DIAN/market-vault`.
[Q60 PR #330](https://github.com/M0DIAN/market-vault/pull/330) is merged;
its exact-main natural push
[38236215470/1](https://github.com/M0DIAN/market-vault/actions/runs/38236215470/attempts/1)
is terminal SUCCESS through the existing verified FULL PR tree-reuse path.
Remote main, local/origin main and a clean worktree were verified before
creating the Q61 feature branch.

The owner's 2026-10-12 request authorizes these three tasks, including in-scope
repairs, tests, commits, push, PRs, independent final-candidate review,
conditional squash merge and exact-main CI verification. Follow the supplied
Development Workflow v2, Personal Local Tool Workflow v1, AGENTS.md and checked-in
governance. Version remains 0.9.0. Implementation order is **Q61 → Q62 → Q63**;
each begins only after the preceding merged-main gate succeeds. Read-only
preparation may overlap. Each worktree has one writer; a final reviewer must
not have designed or implemented that candidate.

## Assessment and counterevidence

Q1–Q60 already provide verified intraday data, actual-label-end purging,
linear/quadratic Ridge, chronological model/threshold/joint selection,
explicit Freeze/TEST, paired and family uncertainty, execution stress, market
and sample evidence, one-source procedure execution and native inspection.
Q55/Q58 repaired constant Features and R²; Q59/Q60 reduced TS2 leaf hashing
and PIT candidate scans. These completed capabilities are not repeated here.

| Candidate | Decision based on current code and bounded evidence |
|---|---|
| Constant TRAIN targets | Q61. `_fit` can round a constant target mean away from its common value, then amplify the false residual through a small but real Feature scale. |
| Constant Feature Research statistics | Q62. Fractional constants can produce nonzero standard deviation and Pearson IC 1, which Feature Stability counts as three stable available correlations. |
| Repeated symmetric Ridge Gram entries | Q63. The shared fitter computes both halves independently. Reusing each identical dot product preserves accumulation order and reduces work, especially at quadratic width 27. |
| CI repartition | Not needed now. Q60 final PR FULL `38234612849/1` passed all 16 jobs; its longest partition was 544 s. Q59's last actual main FULL had a longest partition of 561 s. |
| TS2 digest-string validation | Defer. A bounded Q5 prototype retained bytes while reducing single-run build/load observations by roughly 7–14%; this does not outrank the two correctness fixes and fitting work. No validator is weakened. |
| More learners, Features, search axes or reports | Excluded. The inspected repository evidence establishes software defects and costs, not a market-study need for a larger search space. |

All numerical examples and timings below are offline software evidence, not
claims of observed market profitability or live performance.

## Shared defaults and exclusions

- Keep ordered Features, recipes, alphas, thresholds, complete candidate support,
  chronological windows, actual-end purging, FIRST_DECLARED ties, execution
  costs/rules and TEST isolation.
- Q61/Q62 correct erroneous numbers. Historical artifacts remain immutable and
  readable; strict replay of an affected old result may correctly report a
  mismatch. Fresh reports bind corrected numbers in their existing identities.
  Do not relabel, overwrite or silently accept old erroneous results.
- Q63 must preserve complete model/report bytes, predictions and identities.
  Reuse is local to a single matrix calculation and never substitutes for
  current source admission or changes fit-reuse scope.
- No new dependency, learner, Feature, epsilon-based constant policy, persistent
  cache, storage format, data collection, source overwrite, release, deployment
  or live trade. No general solver/conditioning or statistical-library rewrite.
- CI follows the actual classifier. Preserve all required coverage and existing
  post-merge proof/fallback behavior. No permanent wall-clock test threshold.

## Q61 — constant TRAIN target mean and reference forecasts

### Goal and technical plan

Use the exact common value when all admitted TRAIN targets compare equal;
otherwise retain `math.fsum(values) / len(values)`. Apply the same small shared
helper to Ridge centering and the two existing TRAIN_MEAN forecast paths in
Q21 and ML prediction diagnostics. The single-Feature ablation already consumes
Q21's recorded training mean and needs no new fitting mechanism. Retain positive
zero conventions and the existing solver, Feature scaling and alpha.

The public baseline accepts `X=(1, 1, nextafter(1, 2))`, `y=(.1, .1, .1)`.
On the base it produces a coefficient about -0.046875 instead of zero. An actual
intraday fit with 67 copies of the Q5-computable target `1.03 / 1 - 1` and an
adjacent-float Feature produces about 77–154 bps of spurious forecast deviation.
These are legal fitter-input counterexamples, not a claim that this complete
input combination has been observed in market history. Q55 protects X and Q58
protects metrics; neither covers this target-centering defect.

### Acceptance and scope

1. The same public baseline and actual linear/quadratic intraday fitter
   regressions fail on the base for the target defect and pass after repair.
   Constant targets give exact zero coefficients and constant predictions.
2. Both forecast-reference paths retain the exact same TRAIN-only mean; the
   sole-Feature ablation and zero-baseline-error availability remain consistent.
3. Nonconstant adjacent-float targets retain their real variation and original
   arithmetic. Existing temporal intervention, purging, source reconstruction,
   recorded-model and CLI checks remain authoritative.
4. Final-candidate independent review, natural required PR CI and exact-main
   verification pass; no historical artifact is rewritten.

Scope: `research/ridge_baseline.py`, `research/intraday_prediction_quality.py`,
`research/intraday_ml_diagnostics.py`, directly related existing numerical and
diagnostic tests, and this task record. No UI redesign or change to model
selection, economic objectives, schema/version labels or TEST eligibility.

### Q61 local evidence

On the original production code, the six added cases gave **5 failed, 1 passed
in 0.44 s**: both signed public-baseline constants, both actual intraday
representations and the forecast-reference mean reached the defect; the
nonconstant adjacent-target oracle already passed. The unchanged cases gave
**6 passed in 0.10 s** after repair, including the single-Feature ablation
consumer and zero-baseline-error availability. The existing complete ML
diagnostics test file gave **5 passed in 41.48 s**, covering real saved sources,
ordinary/selected forecasts, source rejection and installed-CLI recovery.
These observations use Python 3.11.17. Hygiene, whitespace and release/version
0.9.0 checks pass. Broader affected regression, final independent review and
exact remote gate identities are recorded in the associated PR. The historical
artifact compatibility statement is a reader/replay code assessment, not a
claim of a separate historical bad-artifact end-to-end replay.

### Q61 completed main gate

[PR #331](https://github.com/M0DIAN/market-vault/pull/331) passed independent
final-candidate review at `86d68c6667a8383fde4f300f9018f0a86cbe91a6`, tree
`ce97099c720e6a455cfda3743c8cf26020d4f4ab`. Its natural FULL
[38244145781/1](https://github.com/M0DIAN/market-vault/actions/runs/38244145781/attempts/1)
passed all 16 required jobs; the current `check_jobs` returned `(True, None)`.
The longest job was diagnostics at 457 s. The broader local affected selection
passed 56 tests; independent base/candidate replay, nonconstant complete-byte
comparisons and temporal/Open/Replay checks also passed.

Authorized squash produced main `541d7e35f81779757f5adfa168b26092d53db8a2`,
with one parent equal to the declared base and the same complete tree. Its
natural push
[38245512709/1](https://github.com/M0DIAN/market-vault/actions/runs/38245512709/attempts/1)
is terminal SUCCESS. The actual plan proved `POST_MERGE_REUSE=true`, reason
`verified_full_pr_tree_equivalence`, bound to that PR, head, run and tree.
All five active jobs passed; the partition placeholder was skipped by this
proof. This is verified FULL reuse, not a second FULL execution. Independent
post-merge review returned PASS / COMPLETE. Q62 started from this verified
main with local/origin/remote identities equal and a clean worktree.

## Q62 — constant Feature Research statistics

### Goal and technical plan

In the existing Feature Research implementation, exact constants retain their
common mean and zero population standard deviation. Pearson correlation is
undefined when either vector is constant, independent of rounded means. Keep
the current nonconstant arithmetic, rank ties and tail membership. Existing
Feature Stability and native/CLI consumers receive the corrected values
through the same interfaces.

Three `.1` Feature values paired with three `.1` labels currently give mean
`.10000000000000002`, standard deviation about `1.388e-17` and Pearson IC 1.
Three identical splits then give availability count 3 and sign consistency
true. Rank IC is already unavailable and current Feature Selection uses Rank
IC; this is not evidence that automatic Feature selection chose the constant.
Q21's own correlation guard already handles constants and is not reimplemented.

### Acceptance and scope

1. Public `analyze_features` returns the exact mean, standard deviation 0 and
   Pearson null for the fractional-constant counterexample. Either constant
   side independently makes Pearson unavailable.
2. Public `compare_feature_stability` retains split identities while reporting
   zero available Pearson ICs and unavailable consistency/range for this case.
3. Normal positive/negative relationships, adjacent nonconstant floats, rank
   ties, tail statistics, empty support and existing split permissions retain
   their specified behavior. Check the actual output consumer without adding
   new GUI behavior or a separate statistics framework.
4. Final-candidate review, actual required PR CI and exact-main CI succeed.

Scope: `research/feature_research.py`, existing Feature Research/Stability
tests and directly relevant entry tests if needed, plus this record. Q61 is
the delivery dependency; no new business dependency or Feature-selection rule.
No new score, selection criterion, TEST access, generic overflow policy or
correlation algorithm for nonconstant inputs.

### Q62 implementation and local evidence

The existing `_mean` now returns the exact common float for an exact constant,
with canonical positive zero; empty input remains unavailable. `_pearson`
rejects either constant vector before calculating centered deviations.
Nonconstant mean/correlation arithmetic, rank ties and tail membership remain
unchanged. No Feature Stability or Feature Selection implementation changed.

The six new public-analysis cases produced **5 failed, 1 passed in 0.23 s**
on the Q61 base, then **6 passed in 0.07 s** after repair. They cover both or
either constant side, signed fractional Features, constant tail means,
adjacent nonconstant floats and three-split stability. The complete Feature
Research/Stability/Selection and their existing CLI files passed **84 tests
in 0.72 s**. Two existing correlation boundary cases passed in 50.05 s.
Actual CLI dispatch, real analysis and JSON serialization also preserved
the corrected values and null availability; only the existing source-load
and ML-adapter boundary was substituted with an immutable ML bundle for this
bounded consumer check. It is not a full-Q5 data-admission test. Hygiene,
whitespace and release/version 0.9.0 checks passed on Python 3.11.17.
Exact candidate review and remote gate identities belong in the associated PR.

### Q62 completed main gate

[PR #332](https://github.com/M0DIAN/market-vault/pull/332) passed independent
final-candidate review at `e6b8f97d7ac7dbc2ed22f7a4cf4a2b4466e1b926`, tree
`fa8d1e2ea014590254b7ad158dce7e14e3243ee4`. Natural PR
[38246241885/1](https://github.com/M0DIAN/market-vault/actions/runs/38246241885/attempts/1)
was RESEARCH_FAST / SUCCESS, including the 1,042-test Python 3.11 portfolio
and the existing Python 3.14 compatibility surface. This was subset evidence.
Independent comparison also retained identical complete bytes across 43
nonconstant cases, with the declared constant/availability boundaries passing.

Authorized squash produced main `f8310f84833a401a3a6d94c2744db71a93eda021`,
with one parent equal to Q61 main and the same complete tree. Natural push
[38246705548/1](https://github.com/M0DIAN/market-vault/actions/runs/38246705548/attempts/1)
is terminal SUCCESS. The actual plan classified FULL and refused subset
reuse (`POST_MERGE_REUSE=false`, `jobs_missing_surface`); all 16 required
physical jobs actually executed successfully. The current `check_jobs`
returned `(True, None)`. Longest job: Dataset/Features, 494 s. Version 0.9.0,
new package builds, fresh-wheel checks and SHA256 verification passed.
Independent post-merge review returned PASS / COMPLETE. Q63 began only after
this gate, equal local/origin/remote main identities and a clean worktree.

## Q63 — compute each symmetric Ridge Gram entry once

### Goal and technical plan

Construct the existing standardized Gram matrix from one triangle, assigning
each computed entry to both symmetric positions. Each dot product retains
the original row order, multiplication, `math.fsum` and diagonal alpha addition.
The target vector, Gaussian elimination, normalization, coefficient conversion
and predictions stay unchanged. No BLAS dependency, parallel reduction,
cross-fit cache or new public numerical API is needed.

A pre-implementation call to the actual `fit_quadratic_rows` with six Features,
3,000 TRAIN rows and 600 validation rows measured 0.315660 s on the base versus
0.182278 s for an in-memory prototype. Width 27 requires 729 dot products on
the base and 378 after triangular construction. The complete model, model ID
and every forecast were equal. This is one bounded raw-fit observation, not
a promised end-to-end study speed or a permanent timing gate.

### Acceptance and scope

1. Compare complete coefficients, intercepts, transforms and predictions with
   an independent full-matrix oracle, including mixed signs, constant/duplicate
   columns, width one, quadratic expansion and supported alpha values.
2. Prove the reduced dot-product work without asserting elapsed time. Preserve
   existing failure behavior and no cross-call reuse.
3. Actual saved intraday reconstruction retains complete report bytes and IDs;
   observe the same raw fitting entry before/after without profiler distortion.
4. Existing Ridge, quadratic and selected-procedure regressions plus actual
   required PR CI pass, followed by final independent and exact-main checks.

Scope: the shared Ridge matrix construction, directly related existing Ridge
and intraday numerical tests, and this record. Q62 is the delivery dependency;
Q61's corrected target centering is the fitting baseline. Do not add a new
solver, change numerical summation order, trim family evidence or reopen
accepted Q49–Q51 fit ownership and source-verification boundaries.

### Q63 implementation and local evidence

Only the shared fitter's Gram construction changed: build the upper triangle,
copy each value to its symmetric position, then preserve the tuple-of-tuples
solver input. The target vector, row-ordered `math.fsum`, alpha addition,
solver, transforms and forecast calculations retain their original behavior.

The new operation-count and independent dense-matrix oracle spans width one,
mixed/duplicate/constant columns and actual six-Feature quadratic width 27,
each at alpha 0.1, 1 and 10. On the Q62 base it gave **6 failed, 3 passed in
0.16 s**: the failures were redundant-product counts, not numerical errors.
The candidate gave **9 passed in 0.06 s**, including exact matrix/vector and
complete model/forecast canonical-byte equality to the dense oracle. The
complete Ridge baseline/alpha/final-test/threshold files passed **66 tests
in 0.42 s**. Existing intraday linear/quadratic and constant-target checks
passed **14 tests in 98.83 s**; actual three-procedure equivalence, an
outside-family alpha, fit identity and raw-score isolation passed **5 tests
in 44.76 s**. There is no elapsed-time assertion or persisted fitted cache.

A read-only baseline used the unchanged actual `quadratic_dev_case` fixture
at Q62 candidate tree `fa8d1e2ea014590254b7ad158dce7e14e3243ee4`, which is also
the completed Q62 main tree. The candidate reconstructed the same saved
Canonical/Q5 source with its full 36-session 30m calendar, 324 observations,
two DEV folds and all three ordinary linear/quadratic candidates. Complete
report bytes (721,930) and artifact bytes (723,646) remained equal. The artifact
SHA256 stayed `9c8cf65ed520e3bcdb0c2de0aafd23662ecfed49eae6a1429ff08100e2eb8c08`;
all original source/baseline file hashes were rechecked and remained unchanged.

The same separately saved synthetic raw-fit input (3,000 TRAIN, 600 validation,
six Features, alpha 1) retained its entire model and forecast bytes, including
model ID `1b0a0dd9b1945a330eaf4df08d4c2c740747271b08c81ffff4b04d750ef9ffbd`.
One unprofiled baseline fit measured **0.303562 s**, and one candidate fit
**0.195099 s**. Gram dot products fell from **729 to 378** (48.1% fewer);
this raw-fit timing was about 35.7% shorter. The observation is bounded to
that input and entry, not an end-to-end study or production latency claim.
Final related regressions, candidate review and exact remote gates are recorded
in the associated PR. Version remains 0.9.0.
