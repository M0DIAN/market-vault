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

## Q72 - predivide active bootstrap series once per analysis

**Goal and technical plan.** In `_mean_intervals` and `_family_bounds`, compute
each active source value divided by the fixed sample count once per call.
Every draw still visits the same indices in the same order and passes the
same divided floating values to `math.fsum`. Keep constant-family deviations
as exact zero. Local tuples end with the call; no cache service is introduced.

**Defaults.** Preserve stationary bootstrap, synchronous PRNG stream, seed,
default 5,000 replications, block/sample/continuity gates, full candidate family,
declaration order, quantile interpolation and all unavailable reasons.

**Scope.** `research/intraday_return_uncertainty.py`,
`research/intraday_family_bounds.py`, their direct existing regression files
and this record. Procedure analyses reuse these helpers without a new engine.
Q71 is a delivery dependency; capture the byte baseline on its completed main.

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
