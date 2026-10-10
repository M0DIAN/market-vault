# Intraday prediction research package: Q21–Q23

This package was selected against main
`8dd4bf305368a9def50599ca90a658f949e1b41d`, after Q1–Q20. The sequence is
**Q21 selected Ridge prediction quality → Q22 leave-one-Feature-out refits →
Q23 bounded quadratic-basis Ridge comparison**. Each task has a separate PR,
fresh independent review of its final candidate, required CI, an authorized
squash merge, and verification of the exact natural main-push CI before the
next implementation starts. The package authorizes source development and
integration; releases, deployment and live trading are outside its scope.

## Why these three tasks

The [Q7 development contract](intraday_development_research.md) already has
chronological expanding fits, actual-target-end purging, a common READY
prediction universe, saved fold models, and Ridge alongside Feature and
Composite rules. [Q8](intraday_final_test.md) adds a frozen-candidate TEST
workflow. [Q15–Q17](intraday_research_quality.md) and
[Q18–Q20](intraday_research_quality_next.md) cover dependent daily-return
uncertainty, a declared family's joint bounds, sequential candidate selection,
signal-delay stress, and two explicit portfolio capital models.

The cross-day Dataset workflow already contains Feature IC/stability/selection
and Ridge alpha selection. Those capabilities are not a missing global ML
subsystem. The narrower gap is the intraday saved-candidate workflow: Q7 keeps
aggregate prediction MAE/RMSE/R² and each prediction, but does not compare those
errors with simple historical forecasts or expose fold-level prediction
quality, Feature removal refits, or a nonlinear learned representation.

| Direction | Current evidence and remaining value | Decision |
| --- | --- | --- |
| Predictive robustness | Execution outcomes and return intervals do not show whether Ridge predicts the subsequent numeric target better than zero or a historical mean. Existing folds can expose changes over time. | Q21 first. |
| Feature sensitivity | Saved coefficients depend on scaling and correlated inputs. Refit under each single omission to answer a specific prediction question. | Q22, reusing Q21 source admission and scoring. |
| Nonlinear ML | Intraday's only fitted family is linear Ridge. One fixed quadratic representation tests curvature and pair interactions with the existing solver. | Q23, after the linear diagnostic and sensitivity tools. |
| Additional overfitting control | Q16 and Q18 already address a declared family and a historical selection rule. A full nested Feature/model search would introduce another fitting and selection contract. | Defer until an actual automatic selection workflow is in scope. |
| Additional portfolio research | Q17 and Q20 already distinguish drifting initial sleeves and daily target cash reallocation. Shared capital, optimized weights and multi-asset execution need new account and selection evidence. | Outside this package. |
| More stress grids or return displays | Costs, execution windows, per-signal delay, parameter neighbors, risk paths and fold outcomes already have concrete tools. | No duplicate main task. |
| PBO, DSR and global search tracking | Saved candidates do not recover unknown historical trials or their dependence. | No invented global overfitting probability or trial count. |
| Trees, boosting and deep learning | They need a new learner/dependency or a larger implementation and tuning surface. A small polynomial experiment answers a useful narrower question first. | Defer; no new dependency or model framework. |

Q22 and Q23 technically reuse Q21's narrowly scoped preparation and scoring.
Q23 does not automatically consume a Feature selection from Q22: the original
saved projection remains explicit, and Q22 never selects a winning omission.
The tasks are exploratory DEV studies. Choosing a representation after viewing
these reports is a new research decision, not an unbiased estimate of the
performance of that choice.

## Shared source and numerical contract

- Input is an immutable ordinary saved Q7 DEV comparison or diagnostics
  record and one explicit `RIDGE` cost/candidate pair. An existing Q10
  collection must first use its ordinary-child export. Defaults are cost
  index 0 and candidate index 0; a rule at that position is an error, not an
  instruction to silently choose another candidate.
- Q7 predictions do not contain the numeric targets or Feature vectors.
  Each action therefore strictly loads the corresponding Q5 data once,
  using an explicit relocation override or the saved plan's original path,
  and requires the exact recorded `data_id`.
- Rebuild the complete existing common context, actual folds, purged training
  keys and all-READY validation keys. Refit only the selected Ridge using its
  saved ordered projection and alpha, then require complete agreement of the
  selected fold models, predictions and original prediction metrics.
- This evidence is **selected forecast reconstruction**. It neither reruns
  the entire Q7 family/accounts nor grants full Replay proof. Q5 whole-file
  verification may inspect TEST representation; TEST observations and targets
  never enter these studies' fitting or scoring.
- Every READY prediction remains visible, including an incomplete target at a
  session tail. Error metrics use the same COMPLETE target keys for all
  forecasts. No missing targets become zero and no variant recovers rows that
  the original common projection excluded.
- The existing temporal folds, original target horizon, actual target-end
  purge boundary and historical-only scaling are retained. There is no random
  split, additional generic embargo, resampling or new training origin.
- Prediction returns are raw ratios. MAE, RMSE and bias have return units;
  MSE has squared-return units; R², correlations and MSE skill are unitless.
  These are row-weighted prediction diagnostics, not daily trading returns.
- Invalid source/arguments or a reconstruction mismatch fail the action.
  Valid but undefined statistics retain `null` and an explicit reason.
  Nonfinite arithmetic is never emitted as NaN/Infinity, clipped or silently
  removed. Existing experiment bytes and original identities are immutable.
- Each derived report has its own version and content identity. Package
  version remains 0.9.0. Existing Q5/Q7/Q8 schemas, plan grammar, Freeze/TEST
  eligibility, CI architecture and dependencies remain unchanged.

## Q21 — selected Ridge prediction quality

### Goal and method

Compare the source-verified selected Ridge with `ZERO` and `TRAIN_MEAN`.
The latter predicts the arithmetic mean of each fold's admitted, purged
training targets for every validation observation in that fold. It is never
calculated from validation or TEST targets.

For each forecast, report pooled and original-fold MAE, MSE, RMSE, R², mean
prediction, mean actual target, bias (prediction minus target), Pearson
correlation and tie-aware Spearman correlation. Show READY prediction counts,
COMPLETE scored counts, actual day counts and the scored keys. Preserve
fold identities and training-mean evidence.

For a selected forecast `p`, observed targets `y` and a baseline `b`, MSE
skill is `1 - sum((y-p)^2) / sum((y-b)^2)`. Positive means lower squared error
than that baseline on exactly the same pairs. A zero baseline denominator is
unavailable. Pool the row losses/counts before deriving statistics; do not
average fold RMSEs or fold skill values. Constant forecasts or targets retain
explicit correlation/R² unavailability where applicable.

### Acceptance

Cover a small absolute error that still loses to zero, a temporal reversal
hidden by pooled results, hand-computed pooled losses, tied ranks, constant
series, and incomplete session-tail targets. A future-target intervention must
change only the relevant evaluation and later historical fits, not an earlier
training mean or model. A structurally valid, re-signed modified selected
model/prediction must fail actual reconstruction. Invalid indices/kinds/versions
must fail before Q5 I/O. Verify an actual saved Ridge through the CLI and
rendered bilingual desktop, including nonfirst selection, missing source,
explicit relocation and captured-result behavior.

### Exclusions

Fitted calibration, probability calibration metrics, reliability-bin search,
significance tests, confidence intervals, trading thresholds or execution,
TEST scoring, automatic model choice, model export and new Freeze eligibility.

### API, CLI and desktop

`research.intraday_prediction_quality.analyze_intraday_prediction_quality`
accepts an immutable `StrategyExperiment`, `cost_index=0`,
`candidate_index=0` and an optional `intraday_data_file`. Its report version is
`market-vault-intraday-prediction-quality-v1`, bound by `prediction_quality_id`.
The result retains source identities, recorded/used Q5 locators, reconstruction
evidence, full common context, pooled/fold forecasts and every paired prediction.
Each metric exposes its value, unit and unavailable reason.

```console
market-vault research-intraday-prediction-quality --experiment /absolute/development.json --cost-index 1 --candidate-index 1
market-vault research-intraday-prediction-quality --experiment /absolute/development.json --intraday-data /relocated/intraday.json
```

The settings-independent command emits ASCII-safe JSON to standard output;
ordinary shell redirection can retain that report. The desktop's Development
view **ML · Prediction quality** offers pooled comparisons, original-fold
comparisons and paired predictions. Choose a saved Ridge explicitly, optionally
locate its Q5 source, and press Analyze/Refresh. Numeric unavailable reasons,
source identities, coverage and the narrower reconstruction scope remain
visible; switching views or language does not repeat fitting.

## Q22 — exhaustive leave-one-Feature-out refits

### Goal and method

Retain the verified full Ridge and exactly one alternative for each omitted
Feature, in the original projection order. Every alternative refits its own
scaler and Ridge coefficients using the same admitted training rows, alpha,
fold boundary and original READY validation sample. Record omitted and
retained Features, complete fold model evidence and every prediction.

Removing the only selected Feature produces an explicit intercept-only
`TRAIN_MEAN` forecast. It uses Q21's historical mean; an empty matrix is not
passed to the Ridge solver and no fake constant Feature is introduced.

Use Q21's pooled/fold diagnostics and paired error changes. The sign convention
is **ablated minus full**: a positive MSE difference means the omission
worsened prediction. All alternatives use identical COMPLETE pairs. Preserve
declared Feature order rather than ranking or automatically dropping Features.
An action costs the baseline reconstruction plus at most one refit per Feature
per fold; the intercept-only case needs no additional solver.

### Acceptance

An omitted constant Feature leaves predictions unchanged; removing a unique
informative Feature worsens held-out error in a controlled example. The sole
Feature omission equals the historical training mean. Check projection order,
identical prediction/scored keys, fold-level differences and training-only
temporal intervention. Exercise the actual CLI and desktop on a saved
multi-Feature candidate, including a nonfirst cost/candidate selection.

### Exclusions

Automatic Feature selection, arbitrary subsets/groups, permutation tests,
causal importance, hyperparameter retuning, changed row eligibility, trading
reruns and general selection infrastructure. Correlated Features can substitute
for one another. Removing a duplicate column also changes Ridge's penalty
geometry at fixed alpha, so exact prediction invariance is not promised.

### API, CLI and desktop

`research.intraday_feature_ablation.analyze_intraday_feature_ablation` accepts
the same immutable saved experiment, explicit cost/candidate indices and
optional Q5 relocation as Q21. The derived report uses version
`market-vault-intraday-feature-ablation-v1` and `feature_ablation_id`.
It includes the verified full model, each omission's retained projection and
complete fold models, pooled/fold forecasts and every original READY prediction.
`DROP_0`, `DROP_1` and subsequent forecast keys follow the saved Feature order;
they are stable identifiers within this report, not ranks.

```console
market-vault research-intraday-feature-ablation --experiment /absolute/development.json --cost-index 1 --candidate-index 1
market-vault research-intraday-feature-ablation --experiment /absolute/development.json --intraday-data /relocated/intraday.json
```

The settings-independent command emits ASCII-safe JSON. Both pooled and
original-fold `paired_error_changes` contain each omission's MAE, MSE and RMSE
differences against full Ridge, using the same COMPLETE pairs and Q21's explicit
units/unavailable reasons. A pooled RMSE difference is the difference of the two
pooled RMSEs; it is not an average of fold RMSE differences.

In the existing Development ML view, choose the leave-one-Feature-out method
and press Analyze/Refresh. The method selector and optional Q5 locator edit the
next request. An already completed result retains its own method and source
labels until another explicit analysis completes. Pooled/fold tables show the
signed error changes; MAE/RMSE differences display in percentage points, while
MSE differences retain raw squared-return-ratio units. Full row details include
every omission's prediction, including unscored session tails. Choosing a method,
page or language does not fit a model or select a winning Feature set.

## Q23 — bounded quadratic-basis Ridge comparator

### Goal and method

Compare one fixed degree-two representation with the source-verified linear
Ridge. For each fold, learn means and population scales of the original
Features only from its admitted training rows. A training-constant Feature maps
to zero. Apply this transform unchanged to validation observations.

Generate the original standardized terms first, then products `z_i*z_j` in
lexicographic index order for `i <= j`. This includes every square and distinct
pair interaction, with no explicit bias column. Reuse the existing Ridge
solver, including its own normalization of these generated columns and its
intercept. Record both normalization stages, ordered term definitions, alpha,
training keys, models and all predictions.

| Setting | Fixed default and limit |
| --- | --- |
| Degree | 2; originals, squares and pair products |
| Input projection | The selected saved ordered Features; at most 6 |
| Expanded width | `p * (p + 3) / 2`; at most 27 |
| Alpha | The selected saved Ridge alpha; no search |
| Sample and folds | Exactly the same Q21 admitted rows and original folds |
| Comparison | Original Ridge plus ZERO/TRAIN_MEAN references, paired pooled/fold losses |

The input-size limit is an engineering bound for the current pure-Python
normal-equation solver, not a theorem about adequate sample size. Reject an
oversized projection before Q5 reconstruction; do not trim it. The same numeric
alpha does not mean exactly equivalent regularization across representations.
This is a quadratic-basis Ridge experiment, not a general nonlinear-model
benchmark or a claim that prediction improvement yields higher trading profit.

### Acceptance

Use a held-out symmetric quadratic target and a pair-interaction example to
verify the added representation. Check exact term order/arithmetic, both
training-only normalization stages, constant Features, a one-Feature case,
finite-input overflow failure and the dimension bound before source access.
Future changes must leave earlier transforms and fits unchanged. Verify paired
keys and actual CLI/desktop presentation on the same saved source as Q21/Q22.

### Exclusions

Degree/alpha/representation search, automatic Feature selection, trees,
boosting, neural networks, sklearn or another dependency, new Q7 strategy
grammar, Q6 execution, native candidate export and Freeze/TEST integration.

### API, CLI and desktop

`research.intraday_quadratic_ridge.analyze_intraday_quadratic_ridge` accepts
the same immutable `StrategyExperiment`, explicit cost/candidate indices and
optional `intraday_data_file` as Q21/Q22. It rejects a saved projection larger
than six before Q5 is read. The report version is
`market-vault-intraday-quadratic-ridge-v1`, with its own `quadratic_ridge_id`.

```console
market-vault research-intraday-quadratic-ridge --experiment /absolute/development.json --cost-index 1 --candidate-index 1
market-vault research-intraday-quadratic-ridge --experiment /absolute/development.json --intraday-data /relocated/intraday.json
```

The `quadratic` record retains the saved `input_features`, fixed `degree`,
`expanded_width`, ordered `terms` and `fold_models`. A term's `name` is `z_i`
or `z_i*z_j`; `input_indices` refer to the saved Feature order. Each composite
model records its original-Feature `input_transform` (means, population scales,
constant-to-zero policy), terms, original alpha, training keys/boundary and the
complete existing `ridge_model`. The latter includes the generated columns'
training means/scales and the existing solver's coefficients/intercept in
generated-term units. Predict by applying the original-Feature transform,
constructing the ordered terms and using that intercept/coefficients; do not
apply the second normalization a second time to these returned coefficients.

Every row and fold retains the verified linear `model_id` and a separate
`quadratic_model_id` binding both stages of the quadratic fit. Forecasts are
`RIDGE`, `ZERO`, `TRAIN_MEAN` and `QUADRATIC_RIDGE`, with identical READY and
COMPLETE keys. `paired_error_changes` records quadratic minus linear Ridge
MAE/MSE/RMSE for each original fold and the pooled rows. Positive means larger
error; a pooled RMSE difference is derived from the two pooled RMSEs.

In Development ML, choose **Quadratic-basis Ridge** and explicitly analyze.
The bilingual view shows all four forecasts, signed changes, degree, expanded
width, ordered terms and distinct model identities. MAE/RMSE changes display
in percentage points; MSE changes retain squared-return-ratio units. The full
row picker includes incomplete session tails. A completed result keeps its
own method/source labels when the next-action draft changes; changing a view,
language or draft does not fit or select a model. Full model and normalization
records remain available in the CLI report.

## Desktop workflow and validation boundary

The existing Development candidate selector supplies the immutable saved
selection. An ML analysis area offers an explicit Analyze/Refresh action and
a separate optional Q5 locator. A blank locator means the saved path. It does
not use the currently open data workspace, edited research parameters or the
full-Replay relocation callback.

Background work captures saved content, selected identities/indices, locator
and method. Results apply only to that captured selection. A completed result
retains its own source labels; editing the draft locator, choosing a table or
switching language cannot relabel or refit it. Each new explicit analysis
revalidates the source rather than trusting a previous displayed report.

Focused tests cover the new mathematical and user-workflow risks. Existing
required CI remains authoritative; no CI scope reduction, weak mirror tests,
new evidence platform or unrelated data/release test expansion is part of this
package. Independent reviewers must not have designed or implemented the
candidate they approve.

## Method references

- [Chronological forecasting example, scikit-learn](https://scikit-learn.org/stable/auto_examples/applications/plot_time_series_lagged_features.html): demonstrates why shuffled evaluation can be optimistic for an ordered forecasting task. This package preserves the repository's own financial time and target-end contracts, not that example's dataset or numerical settings.
- [PolynomialFeatures, scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.PolynomialFeatures.html): documents a degree-two basis and the feature-count/overfitting growth of polynomial expansion. The implementation reuses MarketVault's existing solver and adds no sklearn dependency.
- [Permutation importance, scikit-learn](https://scikit-learn.org/stable/modules/permutation_importance.html): discusses how correlated variables can substitute for one another. Q22 uses retraining after omission, a distinct sensitivity experiment; its interpretation remains model- and sample-dependent.
