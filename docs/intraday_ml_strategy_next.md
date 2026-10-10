# Intraday ML strategy package: Q24–Q26

## Baseline, priority and delivery

The package starts from verified main
`8f68b1361034bb08f4cc1b2d118353d1a1b1a9ba` (Q23, PR #292).
Q23's natural PR FULL run `38042626673/1` and exact-main push
`38043877682/1` are successful. The latter uses the existing verified FULL
tree-equivalence reuse contract. All fifteen physical PR jobs completed in
less than ten minutes; the longest was 547 seconds.

Q1–Q14 already provide verified intraday inputs, actual-target-end purging,
historical expanding fits, aligned execution accounts, frozen-candidate TEST,
cost/window scenarios, saved comparisons, risk diagnostics and reusable plans.
Q15–Q20 add dependent daily-return intervals, saved-family bounds, two portfolio
capital models, sequential saved-candidate selection and signal-delay stress.
Q21–Q23 add source-verified forecast quality, Feature-omission refits and one
bounded quadratic representation. The cross-day Dataset workflow separately
already contains Feature research and Ridge selection.

The remaining concrete gap is that Q23's quadratic forecasts are descriptive
DEV evidence: they do not enter Q6 trading, ordinary reusable strategy plans or
Q8's frozen TEST. This package closes that path and adds one bounded inner
selection experiment. It does not add a second general research framework.

| Direction | Decision and reason |
| --- | --- |
| Economic value of nonlinear forecasts | Q24: use the existing execution account and explicit policy. Lower prediction error alone does not establish a better trading result. |
| Selection of representation and regularization | Q25: evaluate a declared finite selection rule inside the existing outer training histories. Q18 selects from saved past trading results and does not perform these inner fits. |
| Final held-out evaluation of new ML candidates | Q26: freeze an explicit fixed recipe before TEST, retaining the existing source and temporal boundaries. |
| More return intervals, fold displays, ablation or polynomial variants | Already addressed by Q12/Q15/Q16/Q21–Q23; no duplicate main task. |
| Trees, boosting, deep learning and automatic Feature search | Defer until the simpler learned representations can complete the research workflow. No new learner dependency in this package. |
| Threshold search, optimized portfolios, global PBO/DSR and trial registries | Excluded. They introduce additional selection questions or require historical evidence not present in saved experiments. |

The sequence is **Q24 ordinary quadratic DEV → Q25 bounded inner selection →
Q26 explicit Freeze/TEST**. Each item has its own feature branch and PR.
Implementation of the next item begins after the preceding final candidate
passes independent review, required CI and the owner-authorized squash merge,
followed by successful natural CI on the exact resulting main SHA. Scope-local
fixes, tests, commits, push and PR updates are included in the owner's package
authorization. Release, deployment and live trading are not part of this work.

## Shared defaults and compatibility

- Reuse Q5's verified data, explicit ordered Feature projection and original
  TRAIN/VALIDATION/TEST boundaries. No random split, missing-row filling,
  implicit Feature selection or use of TEST targets for development.
- Train only on READY observations with COMPLETE targets whose actual target
  end precedes the relevant training boundary strictly. Fit both quadratic
  transformations only on those rows. Preserve incomplete-target READY tails
  in forecasts and execution; score prediction errors on COMPLETE pairs only.
- Reuse Q23's degree-two terms, TRAIN-constant-to-zero policy, two recorded
  normalization stages and existing Ridge solver/intercept. At most six input
  Features produce at most 27 terms. The bound controls computation; it is not
  a claim about adequate sample size or equal penalty geometry.
- Trading remains the Q6 long/flat, next-planned-open, flat-at-session-end
  account with explicit saved costs, windows and holding limits. Prediction
  returns and trading returns retain their distinct units and meanings.
- Existing saved files are immutable. Historical plans, algorithm bindings,
  models, reports and IDs must retain their old meaning and replay behavior.
  New strategy/selection contracts use explicit new plan/artifact versions and
  their own algorithm identities; V1 does not silently acquire a new enum or
  model grammar. Unsupported older readers are not promised to read new model
  types. No source migration or overwrite is introduced.
- API/CLI and the native desktop must expose the actual chosen inputs, method,
  evidence, sample and unavailable reasons. Background results retain captured
  input identity, including selection and source-relocation changes.
- New files use existing exclusive-create/readback behavior. Existing identical
  content may be reused; different content at the chosen path fails.
- Package version stays 0.9.0. No new dependency, market-data provider, Q6
  accounting semantics, release asset, tag or production operation is needed.

## Q24 — ordinary quadratic Ridge development strategy

The Q24 implementation uses the explicit V2 plan/artifact and desktop contracts
documented in [development research](intraday_development_research.md),
[plan reuse](intraday_plan_reuse.md) and
[execution scenarios](intraday_execution_scenarios.md). Q25 is documented in
[bounded inner selection](intraday_inner_selection.md); Q26 remains a separate
subsequent delivery. Q24 and Q25 do not enable new-ML Freeze/TEST.

### Goal and technical approach

Make the fixed Q23 representation an explicit intraday strategy that can be
edited, run alongside linear Ridge under the same common context, saved,
opened, exported into a complete plan and fully replayed. Reuse the existing
Q7 orchestration and Q6 account instead of adding a separate economic-comparison
report. Keep cross-day strategy admission unchanged unless explicitly supported.

The descriptor fixes the representation and includes an explicit name, alpha
and decision threshold. Linear and quadratic fits must have distinct cache
keys even at equal alpha. Cost or threshold changes can reuse the same fit;
representation changes cannot. Every fold records the full quadratic model,
both transforms, term order, training keys and boundary. Decisions use the same
strict `score > threshold` rule as linear Ridge.

### Defaults

New desktop drafts use alpha 1 and threshold 0, visibly editable. Existing
plans are not silently converted and their default candidate lists do not
acquire a new strategy. The saved Feature projection is unchanged and must
contain 1–6 Features for quadratic fitting. Existing diagnostics may vary only
their already supported explicit alpha/threshold axes and cost policies.

### Acceptance

- A controlled curvature example reproduces Q23's quadratic forecasts and
  models, then reaches actual Q6 trades, costs, cash and drawdown.
- An independent linear/quadratic same-alpha case detects cache collision;
  changing cost or threshold does not change fitted forecasts.
- Constant Features, actual-end purging and future/TEST interventions preserve
  the declared temporal behavior. No duplicate numerical test matrix is needed.
- A saved real-source example passes the installed CLI and native strategy
  editor through run, save, open, plan continuation and complete replay.
- Existing linear/rule saved records remain readable and replay identically;
  invalid model evidence and excessive projection width fail explicitly.

### Exclusions

Automatic model/alpha/threshold selection, new Feature combinations, new
execution assumptions and automatic Freeze/TEST. Q25 and Q26 add their own
explicit capabilities after this task is integrated.

## Q25 — bounded inner chronological model selection

The implemented API/CLI, native workflow, independent artifact, embedded source
and complete replay contract are documented in
[bounded inner ML selection](intraday_inner_selection.md).

### Goal and technical approach

Evaluate a declared selection procedure on the original outer DEV folds.
Select one saved learned candidate and retain its Feature order, threshold,
cost, data and outer schedule. At each outer training boundary, use the last
five trading days of that outer training history as one inner validation
holdout. All preceding training-history days form inner TRAIN, with at least
ten trading days required. Purge inner TRAIN against the first inner-validation
session open. Both representations use exactly those admitted rows and the
same COMPLETE inner-validation keys.

Compare the complete ordered family of linear then quadratic Ridge, each at
alpha 0.1, 1 and 10. Each of the six candidates learns its own TRAIN transforms.
Select the lowest pooled inner mean squared error; exact ties retain the first
declared family member. Refit that selected fixed recipe on all original
admitted outer TRAIN rows and evaluate every original outer validation key.
The source candidate remains a same-sample descriptive fixed reference.

The report preserves all inner boundaries/keys, six fitted candidates and
losses, the chosen recipe, its outer refit and forecasts, COMPLETE prediction
metrics and the selected procedure's Q6 account with its benchmark. A new
selection artifact must not masquerade as an ordinary fixed Q7 candidate.
Also apply the same inner holdout rule once to the entire DEV history and
record the six candidate losses/models and final fixed recipe. This final
selection does not affect the already evaluated outer decisions, and its
model is not a TEST-trained model. Q26 may explicitly freeze this saved recipe.
Saving/opening/replaying the selection experiment and native/CLI usage are
part of this task.

### Defaults and failure behavior

The family and 5-day/10-day rule are fixed in this first version; there is no
search over search settings. The maximum is six inner fits plus one outer
refit per original fold, plus six final-DEV selection fits and necessary source
reconstruction.
Any outer fold with insufficient inner history or no COMPLETE inner score
sample makes the selection experiment explicitly unavailable as a whole.
Do not silently discard an outer fold, substitute cash or report a shorter
series as the original sample. Invalid or inconsistent sources fail.

### Acceptance

- A future/outer-validation intervention cannot change the current inner
  choice or outer model; past inner-validation targets can change the choice.
- A reversal example distinguishes the inner winner from the outer hindsight
  winner. Pooled row losses, deterministic ties and both representation cache
  identities are independently checked.
- All six candidates and the outer refit use the declared keys/boundaries;
  incomplete target tails remain in outer execution.
- The selected procedure's cash, costs and daily returns reconcile with Q6;
  its fixed reference uses precisely the same outer dates.
- Real saved inputs pass CLI, native UI, save/open and complete replay;
  unavailable history and failure/recovery remain visible and source bytes
  stay unchanged.

### Exclusions

Arbitrary nested-CV engines, expanding inner grids, Feature/threshold/cost
search, optimizer libraries, probabilistic global overfitting claims, automatic
promotion and use of TEST. This remains a retrospective experiment on an
explicit family; unknown earlier research history is not corrected.

## Q26 — explicit new-ML Freeze and independent TEST

### Goal and technical approach

Extend the existing explicit final-evaluation workflow to (a) a fixed ordinary
quadratic Q24 candidate and (b) a Q25 selection experiment. For (a), Freeze
captures exactly the selected saved recipe and policy. For (b), the final
recipe is the saved Q25 final selection from the same six-member family using
the same trailing-five-day holdout rule on complete DEV history, before any
TEST fitting or scoring. Retain the entire final selection evidence and bind
it to the saved source.

Freeze produces an immutable selection of one fixed recipe. TEST then refits
that recipe once on every eligible TRAIN+VALIDATION row, purged at the first
TEST session open. It applies unchanged transforms and threshold to every
READY TEST observation, and runs an independent cash-1 Q6 TEST account.
No family comparison or retuning occurs on TEST. The benchmark and saved
costs/windows keep the existing Q8 meaning.

Keep Freeze as an explicit no-Q5-read/no-fit extraction of the saved fixed
recipe. Normal TEST verifies the frozen source/configuration. FullReplay verifies the
complete applicable DEV/selection and final TEST computations. Old Q8 paths
retain their existing behavior and identities.

### Acceptance

- Fixed quadratic Freeze binds the exact saved selection and performs no fit.
- Q25 Freeze preserves the DEV-only choice and all six final inner results and
  fails on stale source, insufficient history or incompatible evidence.
- TEST target/Feature intervention cannot change the selected recipe, final
  training keys or learned transforms; COMPLETE scoring changes appropriately.
- One final fit, all READY predictions, independent cash 1, EOD flatness,
  costs and benchmark are verified through actual final entry points.
- Installed CLI and native UI complete Freeze, save/open, TEST and full replay
  for both new paths, including source relocation and failure/recovery.
- Legacy rule/linear Freeze and TEST remain unchanged. No input overwrite,
  automatic selection after TEST or hidden re-evaluation is introduced.

### Exclusions

Online/adaptive TEST refitting, live inference/trading, automatic deployment,
TEST threshold tuning, automatic winner promotion and a new model registry.

## Validation and CI cost

Use small discriminating numerical examples and one necessary real-source
workflow per new contract, reusing verified fixture setup within that workflow.
Native Qt evidence is required separately because the current GitHub dev
environment omits PySide6. Tests remain offline.

The existing ten Python 3.11 partitions, compatibility and package gates remain
authoritative. New learned-strategy tests belong to the existing strategy
surface; every test file must retain exactly one discovered owner. Monitor
natural job durations. If a job becomes a concrete bottleneck, split/rebalance
its work without dropping coverage, weakening assertions or changing required
success semantics. Do not replace performance work with a shorter timeout.

## Method references

- [scikit-learn: nested versus non-nested cross-validation](https://scikit-learn.org/stable/auto_examples/model_selection/plot_nested_cross_validation_iris.html)
  explains why selecting a model and evaluating the selected procedure have
  different data roles. This package uses chronological inner holdouts, not
  the page's shuffled example.
- [scikit-learn: common pitfalls](https://scikit-learn.org/stable/common_pitfalls.html)
  describes training-only preprocessing and preventing evaluation data from
  influencing model choices. No scikit-learn dependency is added.
