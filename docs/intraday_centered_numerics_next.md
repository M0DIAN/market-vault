# Intraday research: centered numerical results and saved validation efficiency

## Baseline, authority and task order

Assessed base: `97397e61c39b36b1d0e5e104e121fba35941325a`, completed Q66,
version **0.9.0**. Remote main's natural push CI `38269833931/1` is successful.
The owner authorized this next three-task package on 2026-10-13 JST, including
in-scope implementation, repairs, tests, commits, push, PR, independent review,
conditional squash merge and exact-main CI verification. Apply the supplied
Development Workflow v2 and Personal Local Tool Workflow v1, together with
checked-in repository governance.

Delivery order is **Q67 -> Q68 -> Q69**. Each implementation starts after its
predecessor's exact-main gate succeeds; read-only preparation may overlap.
Each worktree has one writer. The final candidate reviewer must not have
designed or implemented that candidate. This file is the single task record;
exact review, PR and CI evidence belongs in each PR.

## Assessment and counterevidence

Q1-Q66 already supply verified intraday inputs, actual-label-end purging,
linear/quadratic Ridge, inner model/threshold/joint economic selection,
Freeze/TEST, execution stress, sample/market evidence, uncertainty, training
history sensitivity and the three-procedure suite. Q55-Q66 corrected exact
constants and several other numerical/efficiency defects. Those capabilities
are not repeated here. There is no new market study supporting another learner,
Feature or search axis.

| Candidate | Evidence and decision |
|---|---|
| Near-constant Feature statistics | Q67. A legal public ML bundle with X=(1,1,nextafter(1,2)), y=X-1 gives Pearson 0.8164965809277261; translating X by -1 gives 1. Feature Stability reports a false range of 0.18350341907227385. Q21's raw max-absolute prescaling still gives 0.9428090415820634. |
| Raw-scale Ridge prediction cancellation | Q68. Q66 documented a legal symmetric near-constant TRAIN example whose predictions cross the strict 5 bps threshold solely after translating X. The final raw intercept/coefficients lose low bits; merely changing the last addition is insufficient. |
| Decoded artifact hash copying | Q69. In a real 36-session, two-fold saved-source suite, recursive JSON conversion remains a material validator cost. A bounded default-hash prototype preserves all 12,623,886 suite bytes; two interleaved unprofiled observations are 3.497/3.745 seconds before and 3.378/3.449 after. |
| Further quadratic expansion cache | Defer. All 16 quadratic fits take only about 0.057 seconds in that profiled suite; more retained state is not justified by this fixture. |
| Another CI repartition | Defer unless new natural runs demonstrate a bottleneck. Q66 FULL PR `38267609926/1` had 16 successful physical jobs and its longest partition was 502 seconds. |
| Automatic Feature selection drift | Counterevidence: current Feature selection uses Rank IC, not Pearson; the affine fixture remains correctly selected. Q67 corrects descriptive statistics, not a demonstrated erroneous automatic selection. |

These are software counterexamples and bounded offline measurements, not claims
that these full numerical combinations were observed in market history, or
that a strategy has become profitable.

## Shared defaults

- Version remains 0.9.0; no release or tag action. No new dependency, learner,
  Feature, search dimension, live data collection, deployment or live trading.
- Keep the declared Q25 six-model MSE family, Q31 four-threshold economic
  family and Q36 24-member joint family. Preserve declaration order,
  FIRST_DECLARED ties and strict score > threshold LONG (otherwise FLAT).
- Alphas remain 0.1, 1.0, 10.0 in the model families; thresholds remain
  0, 5, 10, 20 bps in the economic families. Q25 inherits its source threshold;
  there is no new universal 5 bps default. Costs and execution inherit the
  captured source. Inner holdout remains the last five trading sessions,
  with at least ten preceding TRAIN sessions, not a fixed ten-session window.
- Keep TRAIN-only transforms, actual-label-end purge, all-READY predictions,
  COMPLETE-label metric support, DEV chronology and permanent TEST isolation.
  Strict reconstruction may verify the entire Q5 file; this does not admit
  held-out rows into training or selection.
- Existing saved files are never overwritten or migrated. Corrected numerical
  computations may change new report values/IDs; Q68 explicitly versions its
  new authoritative prediction representation. Q69 alone promises byte equality.
- Use the actual CI classifier and required checks, without a manually reduced
  tier. Timing observations are not pass/fail tests or latency guarantees.

## Q67 — centered Feature dispersion and Pearson correlation

**Goal.** Correct false changes in Feature population standard deviation and
Pearson IC caused by rounding a large-offset mean before subtracting it.
The public Feature Research/Stability paths and Q21/Q34 shared prediction
diagnostics must agree with the same mathematical definition.

**Plan.** In Feature Research, form differences from an observed origin, scale
those differences, then center in that smaller coordinate system. Use the
result for population standard deviation and Pearson. Opposite finite extremes
whose difference overflows retain a bounded scaling fallback. Q21 delegates
the original vectors to this shared path instead of scaling before centering.
Keep the reported float mean, exact-constant policy, rank ordering and tails.

**Acceptance.** Public positive/negative affine ML bundle cases return +/-1
within floating precision and no false split Pearson range. Population variance
agrees with an independent Fraction oracle. The existing adjacent-value test's
old `ulp**2/3` expectation is corrected to `2*ulp**2/9`: the earlier test used
the rounded mean, whereas the contract is population variance. This is an
explicit numerical correction, not removal of its nonconstant assertion.
Q21 also retains constant/insufficient/nonfinite reasons and finite very small
and large input handling. Existing Feature/CLI and relevant prediction
regressions pass; Q65's once-per-vector rank count remains intact.

**Scope.** `research/feature_research.py`,
`research/intraday_prediction_quality.py`, their existing focused tests and
this record. Q67 does not alter Ridge fitting, rank-based Feature selection,
tail membership, output shape or split permissions. It does not claim to
correct every numerical routine in the repository.

### Q67 local evidence

On the unchanged production base, the corrected adjacent-variance case and
six new parameterized correlation cases all fail on the target numerical
assertions (seven failures). After the patch, the existing Feature Research,
Stability, Selection and relevant prediction-quality selection passed
**71 tests in 82.18 seconds**; their three actual CLI files passed another
**34 tests in 0.26 seconds**, on Python 3.11.17. This includes the public ML
bundle/stability counterexample, Fraction variance oracle, Q21 actual saved
source/installed CLI path, source rejection and Q65 rank work-count guard.
Repository hygiene, whitespace and release/version 0.9.0 checks passed.
Final independent review and remote gates are recorded in the Q67 PR.

## Q68 — authoritative standardized-space Ridge predictions

**Goal.** Eliminate avoidable prediction cancellation when raw coefficients
and an opposing raw intercept are added. Saved numerical parameters must
describe the actual prediction formula used by DEV and final TEST.

**Plan.** Retain the solved standardized coefficients and TRAIN target mean.
Predict directly as target mean plus their dot product with the existing
TRAIN-standardized inputs. Preserve the raw coefficients/intercept as reported
interpretation fields, but stop using them to reconstruct scores. Introduce
an explicit Ridge algorithm/model version for this representation and bind
the authoritative parameters into saved model identities. Update all shared
baseline, strategy, intraday selection and final consumers together.

**Compatibility.** Existing saved model shapes remain readable as historical
records. New models require their complete standardized prediction fields.
Current replay/source reconstruction rejects historical algorithm versions
before fitting instead of silently reinterpreting an old model. No in-place
artifact rewrite, compatibility bypass, alternate legacy refit engine or
automatic TEST run is added.

**Acceptance.** The Q66 documented threshold counterexample is red on the
old code and agrees with an independently centered calculation after repair.
Newly saved parameters reconstruct predictions for linear and quadratic
models, selected procedures and final TEST. Historical saved inputs still
Open unchanged and fail current replay explicitly. Existing TRAIN/TEST,
constant-Feature/target, solver/Gram and suite reuse protections remain.

**Scope.** Shared Ridge fitting/reporting and its actual consumers
(`ridge_baseline`, `ridge_final_test`, `ridge_trading_selection`,
`strategy_comparison`, `intraday_research`, and shared intraday saved-model
validators), directly affected existing tests/CLI serialization and this
record. Q67 is a delivery dependency; Q66 preparation ownership is retained.
No new solver, epsilon threshold, float precision dependency, search change or
claim of exact translation invariance for every floating-point dataset.
Existing TRAIN means/scales and target-centering arithmetic remain in scope
only as inputs to the new prediction representation, not a general rewrite.

## Q69 — hash decoded saved objects without recursive recopying

**Goal.** Reduce the cost of opening/validating real saved research artifacts
without reducing a single required shape, identity or source check.

**Plan.** In the existing saved-object `_hash` helper, use the existing canonical
JSON encoder directly for its default, already-decoded JSON payload. Preserve
explicit custom/execution digest callbacks. The generic date-aware input
encoder remains unchanged for callers that actually need object conversion.

**Acceptance.** Saved ordinary, Q25/Q31/Q36, Freeze/TEST and execution-scenario
regressions continue to accept valid objects and reject changed identities.
The actual public suite retains every complete output byte and ID against
the post-Q68 baseline; strict source reconstruction and original files remain
unchanged. Count removed recursive conversion work and report bounded timing
separately. Do not claim that unrelated normalization paths have no conversions.

**Scope.** `research/intraday_experiment.py`'s shared hash helper, directly
relevant existing artifact tests and this record. Q68 must close first so the
byte comparison is against the corrected numerical model. No source cache,
cross-action state, schema change, hashing-domain change, missing validation,
generic serializer rewrite or unrelated TS2 optimization.
