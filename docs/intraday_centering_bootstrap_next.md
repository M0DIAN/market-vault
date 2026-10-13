# Intraday research: complete centering and bootstrap efficiency

## Baseline, authority and delivery order

Assessed main: `81d515abb6b97e74ea584941235818cb5ea41151` (Q69), version
**0.9.0**. GitHub natural main push `38317705573/1` succeeded. The owner
authorized this three-task package on 2026-10-13 JST, including in-scope
repairs, tests, commits, push, PR, independent review, conditional squash
merge and exact-main CI verification. Apply the supplied Development Workflow
v2 and Personal Local Tool Workflow v1 with repository governance.

Delivery order is **Q70 -> Q71 -> Q72**. Start each implementation only after
its predecessor's exact-main gate succeeds. Read-only preparation may overlap;
each worktree has one writer. Final reviewers must not have designed or
implemented the candidate. This is the single task record; exact review and
remote gate evidence belongs in each PR.

## Assessment and counterevidence

Q1-Q69 already provide verified intraday inputs, purging by actual label end,
linear/quadratic Ridge, model/threshold/joint economic selection, Freeze/TEST,
execution stress, uncertainty, procedure comparison and shared preparation.
Q67 corrected Feature dispersion/Pearson; Q68 corrected raw prediction
cancellation and added an authoritative standardized representation; Q69
removed recursive copies from decoded-object hashing. Do not repeat them.

| Direction | Evidence and decision |
|---|---|
| Near-constant target R-squared | Q70. For actual `(a,a,nextafter(a,+inf))` and prediction `(a,a,a)`, exact binary64-input Fraction arithmetic gives -0.5. At a=0.01 the public Ridge fold/pooled metrics give 0 while Q21 gives +0.5. Symmetric and exactly constant tests do not cover this asymmetric mean rounding. |
| Incomplete TRAIN centering | Q71. With X=(1,1,nextafter(1,+inf)), y=(0,0,0.003), alpha=1, the existing score at X=1 is 0.001, while translating all X by -1 gives 0.00025: opposite strict 5 bps actions. Q68 explicitly retained the old means/scales; its symmetric regression does not prove general centering correctness. |
| Quadratic input centering | Include in Q71. X=origin+ulp(1)*(0,1,1,3), y=(0,0,0,0.003), alpha=1, evaluated at origin+2*ulp(1), gives about 0.00102038 vs 0.000935798 for origin 1 vs 0, crossing 10 bps. A simpler two-level input is counterevidence, since its generated columns are collinear. Both transform layers need the correction. |
| Bootstrap repeated division | Q72. Three public analyses on a saved 100-day source execute 45,009 means and about 4.55 million generated mean terms. A call-local predivision prototype preserves all output bytes and reduces two interleaved unprofiled totals from 1.036/1.046 to 0.886/0.872 seconds. |
| Additional string-validator optimization | Defer. The intraday identity prototype provides only a smaller 3-6% suite observation; Dataset text scanning shows no clear unprofiled benefit and has a broader impact surface. |
| More CI partitions | Defer. Q69 PR `38316173821/1` had all 16 physical jobs successful; its longest partition was 502 seconds. No observed job requires repartitioning now. |
| New learners, Features or search dimensions | Defer. Existing evidence supports correcting reported metrics, actual predictions and repeated computation; it does not establish a new market hypothesis. |

These are legal software counterexamples and bounded local measurements.
They do not establish that the numerical combinations occurred in market
history, that all floating-point translations are invariant, or that any
strategy is profitable.

## Shared defaults and exclusions

- Package version stays 0.9.0. No dependency, release/tag, installation,
  deployment, live collection or trading changes.
- Keep Q25's six-model MSE family, Q31's four-threshold economic family and
  Q36's 24-member joint family, declaration order and FIRST_DECLARED ties.
  Model-family alphas remain 0.1/1/10; economic thresholds remain 0/5/10/20
  bps. Q25 inherits its captured source threshold, not a universal 5 bps.
- Keep strict score > threshold LONG, otherwise FLAT, and captured source
  execution/cost assumptions. The last five trading sessions remain inner
  holdout, with all preceding eligible TRAIN history and at least ten TRAIN
  sessions. Ten remains a minimum, not a fixed history window.
- Preserve TRAIN-only transforms, actual-label-end purging, all-READY
  predictions, COMPLETE-label metrics, DEV chronology and isolated TEST.
  Source reconstruction can verify complete files without admitting TEST
  rows to training/selection. No automatic TEST execution is added.
- Saved files are not overwritten or migrated. Q70 changes newly computed
  numerical metrics when appropriate; Q71 explicitly versions authoritative
  model parameters; Q72 alone promises complete byte equality.
- Use the actual CI classifier and required checks. Timing observations are
  separate from correctness assertions and are not latency guarantees.

## Q70 - centered R-squared denominators

**Goal and technical plan.** Reuse Q67's origin-first, scaled centering for
target total variation. Use it in generic Ridge fold/pooled/final metrics and
Q21/Q34 prediction diagnostics. Q21 retains a scaled loss ratio, so tiny or
large representable ratios do not require representable individual sums of
squares. A rounded displayed mean is not the reference vector for R-squared.

**Scope.** `research/ridge_baseline.py`,
`research/intraday_prediction_quality.py`, directly affected existing tests
and this record. No model fitting, parameters, prediction scores, strategy
selection, result shape or algorithm-label change. Existing raw-error metrics
outside this denominator correction are not a general extreme-value rewrite.

**Acceptance.** The public asymmetric baseline case is red before repair and
agrees with a Fraction oracle afterward, including fold and pooled results.
Direct intraday prediction metrics use the same denominator and retain pairing
and coverage. Existing constant/no-complete/nonfinite reasons, small/large
ratio handling, unequal-fold pooling, public saved-source/CLI regression and
generic final consumers remain valid. Final-candidate review, required PR CI
and exact-main CI pass.

## Q71 - complete TRAIN centers in authoritative Ridge models

**Goal and technical plan.** Preserve the low-order TRAIN center missing from
the rounded mean. Retain reported means and add TRAIN-derived per-Feature
center offsets and a target center offset. Fit with
`z=((x-mean)-center_offset)/scale` and target residuals centered in the same
way; predict from the complete stored centers. The existing Gaussian solver,
positive alpha and action-local Q66 preparation remain authoritative.

The fixed quadratic basis needs the same per-input offsets before generating
linear/squared/interaction terms. Its nested Ridge fit also uses complete
centers. Advance Ridge baseline/model and generic final representations to v3,
quadratic representation to v2 and the affected CLI result schemas explicitly.
Input plan schemas and search families are unchanged. Bind every new
authoritative field into model IDs and serialize it for reconstruction.

**Compatibility.** Historical complete v1/v2 Ridge and v1 quadratic objects
remain readable without rewriting. New versions require complete offset
fields. Current replay/source admission rejects historical algorithm versions
before refitting; it must not silently reinterpret old saved predictions.
There is no legacy refit engine or migration.

**Scope.** Shared Ridge fit/report/final/selection and actual generic strategy,
intraday linear/quadratic consumers; shared saved-model validators; affected
CLI serialization and user guidance; direct existing regressions and this
record. This includes the quadratic input transform, rather than treating
only the nested fit as centered. Q70 is a delivery dependency.

**Acceptance.** Linear strict-5-bps and quadratic strict-10-bps counterexamples
fail on the old implementation and agree with independent centered arithmetic
after repair. Saved parameters reconstruct actual predictions through DEV,
selection and final TEST; historical Open/current Replay boundaries are
verified. Exact constants, nonconstant signals, TRAIN-only transforms, solver,
Gram symmetry and suite-local reuse retain their protections. Version/identity
changes are visible in the PR. Required CI and independent final-candidate
review pass before squash merge, followed by exact-main verification.

**Excluded.** New Features/learners, epsilon-based constant classification,
new solvers/precision libraries, broad overflow policy redesign, persistent
caches, alternate search, general translation-invariance guarantees and any
change to TEST permissions.

### Q71 implementation and local evidence

Implemented from Q70 main `3aa14ae67f0540268211ffe27b3efba9425d057b` after
its exact-main gate. The initial independent linear/quadratic/target-mean
regressions produced **10 failures and 5 passing controls** before repair.
Linear predictions now agree with the Fraction shrinkage oracle at alphas
0.1/1/10, including the strict 5 bps decision. The asymmetric quadratic
prediction agrees with a separate Fraction two-column normal equation that
eliminates both normalization square roots, and stays below 10 bps.

The shared TRAIN center helper keeps a rounded mean plus its offset. The
offset calculation feeds interleaved `(value, -mean)` terms directly to
`math.fsum`: first rounding individual residuals can incorrectly move the
already correct mean of `(0,0,ulp(1))` upward by one ULP. Fraction checks cover
this zero-origin case, half-ULP boundaries and nonconstant targets near
positive/negative 0.1. Q21, Q33 and intercept-only ablation use the same rounded
TRAIN mean. The previously supported opposite finite target pair
`(-1e308,1e308)` still has mean zero; the solver/variance range is unchanged.

Both new Ridge offset fields enter saved model IDs, alpha fold IDs, generic
final IDs and CLI results. Quadratic v2 records input `center_offsets` before
its nested Ridge v3. Saved parameters reconstruct the asymmetric linear
predictions in the declared operation order exactly. Current-version shape,
numeric type, width and identity corruptions are rejected. Regressions retain
TRAIN/TEST separation, complete-label metrics with all-READY predictions,
constant-column policy, symmetric Gram work counts and Q66 action-local reuse.

Focused local groups passed: core/CLI/configuration **148 passed, 2 GUI skips**;
the extended baseline/final center guards **70 passed** (overlapping core);
prediction diagnostics/ablation/quadratic **37 passed**;
saved DEV and final TEST **73 passed, 2 GUI skips**;
procedure suite/training history **17 passed**;
generic strategy/trading consumers **38 passed, 1 GUI skip**. GUI skips are
the existing PySide6 availability gates, not native GUI validation. A separate
read-only check opened six genuine historical v1/v2 files unchanged and
rejected all twelve default/explicit-locator Replay attempts before source,
Q5 or fitting entry points; original hashes remained unchanged.

Repository hygiene and release checks pass at package 0.9.0. The actual
classifier requires FULL CI. This local evidence is not independent final
review or remote CI proof; exact candidate, PR and merged-main gates are
recorded in the Q71 PR and the completed delivery gate below.

### Q71 independent-review correction

Review of candidate `f3933f5042d773fa783cad73c367b6276ee5e4be` found a
supported finite-target regression at the minimum binary64 spacing. With
`u=nextafter(0,1)` and TRAIN targets `(u,0)`, the correctly rounded mean is
zero, but an underflowed center correction retained `u`. An actual
constant-Feature Ridge fit consequently changed a strict zero-threshold
decision from FLAT to LONG. Direct Fraction/fit regressions first produced
**10 failures and 18 passing controls** on that candidate.

The helper now resolves an exact half-grid tie after its final mean/offset
feedback, using the even neighboring mean. Only an odd value at the minimum
binary64 spacing with zero stored offset needs the extra residual sum. The
post-feedback position also covers `(5*u,1,-1,-3*u)`, whose first correction
is nonzero but leaves the same unrepresentable half-grid remainder. A general
fallback to `fsum(targets)/n` would instead reintroduce double rounding at
ordinary magnitudes: for `(0.1,u,0.2)` it produces `0.10000000000000002`,
where Fraction gives a rounded mean of `0.1`. Both signs remain direct
controls. This correction does not alter model versions or offset fields,
constant classification, solver/variance range or historical replay policy.

The focused Fraction/actual-fit/strict-zero/saved-reconstruction group passes
**51 tests**, including adjacent even/odd ties, thirds, both signs, reversed
order, the subnormal/normal boundary and the mixed-magnitude case. The affected
baseline/final/alpha group passes **134 tests** (including that focused group),
and direct TRAIN-mean reference, ablation and quadratic consumers pass
**15 tests**. Earlier saved-file compatibility checks were not repeated for
this helper-only repair. The repair required new-head CI and independent
review; the earlier candidate's CI did not clear its review blocker.

### Q71 completed delivery gate

PR #341's repaired final head `2949ee62cbb62b4f105d7c9e086871f8d5fab309`
received independent MERGE-READY review and natural FULL CI
`38325216626/1`, with all 16 jobs successful. Squash merge produced main
`237ba1bb0ef1481d5e50d634ed6768b01e406ecd`, tree
`ce9ed98cf78f8cd0659e715ee7d7a0e89bee236d`. Its natural push CI
`38326428086/1` completed SUCCESS. Plan job `115066054239` proved
`POST_MERGE_REUSE=true`, `verified_full_pr_tree_equivalence` and matching
tested/main trees against PR run `38325216626`; the main closure jobs all
succeeded. Q72 began only after this exact-main gate.

## Q72 - predivide active bootstrap series once per analysis

**Goal and technical plan.** In `_mean_intervals` and `_family_bounds`, compute
each active source value divided by the fixed sample count once per call.
Every draw still visits the same indices in the same order and passes the
same divided floating values to `math.fsum`. Keep constant-family deviations
as exact zero. Local tuples end with the call; no cache service is introduced.

**Defaults.** Preserve stationary bootstrap with `PYTHON_RANDOM_MT19937`,
seed 0 and 5,000 replications. All active series share each draw's indices.
Return intervals use 95% percentile coverage (2.5th and 97.5th percentiles);
family bounds use the nonnegative 95th percentile of the complete family's
centered maximum. Both retain `LINEAR_N_MINUS_ONE` interpolation.

The default `block_days=max(2,ceil(cuberoot(n)))` retains its integer-cube
rounding correction, restart probability `1/block_days` and `CIRCULAR`
successors. Inference requires at least 100 daily returns, expected blocks
`1+(n-1)/block_days >= 10` and contiguous evaluated DEV trading days. For the
actual 100-day fixture, the default block length is 5 and expected block count
is 20.8. Keep the full candidate family, declaration order and all unavailable
reasons. These engineering gates do not establish statistical adequacy.

**Scope.** `research/intraday_return_uncertainty.py`,
`research/intraday_family_bounds.py`, their direct existing regression files
and this record. Procedure analyses reuse these helpers without a new engine.
Q71 is a delivery dependency; the byte baseline was captured on its completed
main before Q72 implementation.

**Acceptance.** Complete bytes/IDs match for ordinary return intervals, full
family bounds and a five-series procedure analysis from real saved fixtures.
A focused work-count check distinguishes once-per-active-input division from
once-per-replication division. Existing independent stationary-index/quantile,
joint-family, constants, tiny-return, overflow and actual entry checks pass.
Measure bounded timings separately; no wall-clock threshold. Final review,
required PR CI and exact-main CI succeed.

**Excluded.** A different PRNG, resampling method, NumPy/BLAS dependency,
family pruning, refitting during bootstrap, sample-policy changes, persistent
state, result schema or statistical-definition changes.

### Q72 implementation and local evidence

The two kernels now prepare only active, nonconstant columns after the
existing gates. Every replication feeds the same divided binary64 values,
in the original index order, to `math.fsum`. `_mean` and
`_stationary_indices` are unchanged. The family kernel retains both the
mean's finite check and the centered-deviation finite check; constants still
contribute exact zero. Tuples are local to each analysis, with no cross-call
state, version, dependency, schema or statistical-definition change.

Two existing independent Fraction/index/quantile oracles now count division
work separately from observed means. Before the implementation, both failed
at **200,000 divisions instead of 200** for 100 observations, two active
columns and 1,000 replications. Afterward they pass, including fresh
preparation on repeated calls and duplicate/reordered family members. The
original numerical assertions remain in place.

Formal baseline capture used the completed Q71 main above, with the actual
saved 100-day DEV ordinary source and Q31 study. These historical inputs were
opened through current `StrategyExperiment` validation without refitting or
rewriting. Candidate source/tests were frozen at
`b4b391e916077d6d996c2da99e56a308678bbb88`. Actual public Q13, Q16 and Q52
analysis results match the baseline byte for byte, including every result ID:

| Replications / seed | Result | Complete bytes | SHA256, identical before and after |
|---|---|---:|---|
| 5,000 / 0 | Q13 | 3,700 | `f630f46b35c3171def24d31a11b6efacdf11488dc92377f4feef5112355cf9fe` |
| 5,000 / 0 | Q16 | 3,543 | `855e99f46ef31a49fadf808f8c88391a6e5935132c1c04590c94203a3ed9e4ad` |
| 5,000 / 0 | Q52 | 5,151,696 | `058aed06e5994a58258cf66dac4e530228fc5c4abd7f268610e30ca1b833d090` |
| 1,000 / 17 | Q13 | 3,702 | `76370fd37b69a2b4a0ff9d9d14f533d8567b812860b0291750c6eba99bf37fa5` |
| 1,000 / 17 | Q16 | 3,543 | `eacbf1e88da8a39786cc44c8df87efaaaf562d26e6265366653a71f164ac82fc` |
| 1,000 / 17 | Q52 | 5,151,698 | `70f07ea50078d2ec8591cb769aed75a236b6b5da576b1c41cc17ee9628deb6e6` |

Both parameter sets also preserve the complete ordered indices-stream hashes,
one draw per replication and final RNG-state hashes for all three APIs. The
input bytes/hashes remain unchanged. The preserved baseline kernels were
replayed with surrounding source proved unchanged; only the two kernels and
the family module's required `math` import differ.

Before concurrent tests, two bounded alternating runs on Python 3.11.17
measured old/candidate totals of **1.109012/1.044429 seconds** and
**1.145637/0.970631 seconds**. Each total covers the three already-opened
snapshots' actual analysis entries, including internal decoding, ledger
derivation and bootstrap. It excludes initial Strict Open, result encoding
and file writing. These observations have no wall-clock acceptance threshold
and do not measure CLI end-to-end latency; the earlier prototype timings are
not the final acceptance evidence.

The disjoint focused regressions pass **40 tests, with no skips**: 26 ordinary
return-uncertainty/family tests, 13 procedure-uncertainty/procedure-family tests
and the actual Q53 synchronous-stream/reversed-pair entry. They retain the
independent numerical oracles, constants, tiny returns, overflow, full-family
gates and real public/installed-CLI coverage. All 688 source/test file hashes
remained unchanged throughout the frozen candidate checks. Only this record
was updated afterward. Final-candidate independent review, required PR CI and
exact-main verification remain the publication gates, recorded in the Q72 PR.
