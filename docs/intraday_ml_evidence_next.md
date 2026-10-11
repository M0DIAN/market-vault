# Intraday ML evidence package: Q33–Q35

## Baseline, decision and delivery

The package starts from verified Q32 main
`594f909b191761916b6b4093b9f4090a59be201f` in `M0DIAN/market-vault`.
PR #302's final head `0fb302f837c62ac6e190cab329fb86c42b8a811d` passed
natural FULL CI `38082698052/1`; exact-main push `38083737064/1` passed
with the existing verified tree-equivalence reuse contract. All fifteen
physical PR jobs succeeded; the longest partition took 582 seconds.

Q1–Q32 already provide verified intraday inputs, actual-label-end purging,
outer historical fits, linear/quadratic Ridge execution, finite inner model
and economic-threshold selection, and explicit immutable Freeze/TEST. They
also provide cost/delay/history sensitivity, fixed portfolios, ordinary
prediction diagnostics, daily-return intervals and saved-family bounds.

The remaining gap is evidence about the **existing selected procedures**.
Q21's full forecast-quality entry admits ordinary linear Ridge only. Q15
admits ordinary DEV only. Q25 and Q31 retain complete outer accounts and
inner objectives, but these do not yet answer which score ranges contain
target information, whether one inner day changes the choice, or how uncertain
the procedure's incremental outer return is relative to its fixed source.

| Direction | Decision |
| --- | --- |
| Prediction information by score range | Q33: common outer forecast baselines and five fixed intervals for ordinary learned candidates, Q25 and Q31. |
| Sensitivity of the actual inner decision | Q34: remove each original holdout day's objective contribution with saved fits and scores held fixed. |
| Incremental economic value of the procedure | Q35: compare the complete selected outer account with its original fixed source and benchmark, with synchronous daily-return intervals. |
| Another nonlinear learner or larger model/threshold family | Defer: Q23–Q26 already added a nonlinear path; more search does not close these evaluation gaps. |
| Automatic use of a Q30 history-window winner | Defer: capability to compare histories is not empirical evidence for changing the production research default. |
| More general purging, portfolios, cost grids or saved-family bounds | Existing capabilities; no duplicate task. |
| Global PBO/DSR, TEST ranking, fitted calibration, live execution | Excluded from this package. |

The owner's 2026-10-11 JST instruction authorizes implementation, in-scope
repairs, tests, commits, push, PRs, independent review and conditional squash
merge for this three-item package. Each starts from the previous verified
main. The exact final candidate must pass independent review and required
natural CI, with head/base/tree/run/attempt identities checked before merge.
After successful natural CI for the exact resulting main SHA, continue to the
next item. Release, deployment, live trading and runtime-data mutation are
outside this authorization.

## Shared meaning and compatibility

- Preserve each source's Q5 identity, ordered Features, outer folds, full
  evaluated dates, COMPLETE-label admission and actual end-time purging.
- Predictions include every original READY observation, including target
  tails. Prediction losses use COMPLETE pairs only. Inner/final-DEV samples
  never become outer predictions; TEST is never a development selection set.
- Q31 changes actions, not the ordinary source's raw model scores. Its
  forecast metrics and score-bin descriptions must equal the corresponding
  fixed source while its recorded LONG/FLAT decisions may differ.
- A source-verified analysis may perform the existing reconstruction needed
  to substantiate its stated scope. A recorded-only analysis performs no
  Q5 read, fit, source replay or Q6 execution. Neither silently upgrades the
  source experiment's saved/replay proof state.
- New derived reports have explicit new versions. Existing Q21, Q15,
  ordinary, Selection and TEST formats, IDs, algorithms and immutable saved
  bytes retain their meanings. No conversion or overwrite is introduced.
- API, settings-independent CLI and native desktop expose actual inputs,
  captured source/index/location identity, full evidence and unavailability.
  A failed or stale background action must preserve completed results.
- No new dependency, learner, Feature search, market-data provider or Q6
  accounting change. Package version remains 0.9.0.

## Q33 — common outer ML prediction quality and fixed score intervals

### Goal and implementation

`analyze_intraday_ml_prediction_quality` in
`research/intraday_ml_diagnostics.py` accepts an immutable ordinary DEV
linear/quadratic Ridge candidate, or an AVAILABLE Q25/Q31 saved study. Ordinary
inputs use explicit cost/candidate indices; a study has one selected outer
account and requires both indices to be zero. The report separately records
the actual indices and candidate ID of the study's embedded fixed reference.

Ordinary analysis reconstructs its complete context, selected fold models,
predictions and prediction metrics. It does not rerun its execution account.
Q25/Q31 analysis reuses the existing full procedure evaluator, checking the
complete embedded ordinary source, inner choices, outer applications and final
DEV evidence. Both routes admit Q5 exactly once per action. The stronger
procedure reconstruction does not score inner, final-DEV or TEST predictions.

Each outer fold compares SELECTED, FIXED_REFERENCE, ZERO and TRAIN_MEAN on the
same COMPLETE target pairs, using Q21's existing metrics. TRAIN_MEAN is the
mean of the actual purged **outer** training targets, never the inner mean or
a full-DEV hindsight mean. Ordinary SELECTED and FIXED_REFERENCE coincide.
Reports preserve complete models, recipes, training/validation keys, purges,
cutoffs, pooled/fold metrics and every READY prediction with actual actions.

The fixed, upper-inclusive score intervals are:

| Index | Return-ratio range | Display |
| --- | --- | --- |
| 0 | score <= 0 | <= 0 bp |
| 1 | 0 < score <= 0.0005 | (0, 5] bp |
| 2 | 0.0005 < score <= 0.001 | (5, 10] bp |
| 3 | 0.001 < score <= 0.002 | (10, 20] bp |
| 4 | score > 0.002 | > 20 bp |

Each interval reports READY/COMPLETE/incomplete counts, actual scored trading
day count, COMPLETE-pair mean prediction/target/bias and errors, and target
sign counts. A separate READY-score mean makes tail coverage explicit. Empty
intervals retain null metrics and reasons. Boundaries are never learned from
the sample, and these continuous-return descriptions are not calibrated
probabilities, five independently tradable strategies or fitted calibration.

An UNAVAILABLE source study produces an explicit unavailable report with its
saved reasons and no partial scores, source access or fits. Unsupported
sources, bad indices, source mismatches or inconsistent reconstructions fail.

```console
market-vault research-intraday-ml-prediction-quality \
  --experiment /absolute/saved-study.json \
  --intraday-data /absolute/relocated-q5.json
```

`--intraday-data` is optional and must identify the same verified Q5 source.
The original ordinary file need not be present for a study because its
complete source is embedded. The command returns a derived JSON report; it
does not create a new experiment eligible for Freeze.

The native **Quant Research → Intraday → ML diagnostics** entry opens the
saved source explicitly and offers the same calculation. It keeps source
drafts separate from completed evidence, supports ordinary candidate choice
and Q5 relocation, and provides pooled/fold/bin/READY-row views plus complete
model and key evidence with pagination and selectable wrapped JSON. Both
languages and compact-window scrolling are part of the workflow.

### Acceptance and exclusions

Independent numerical evidence checks all five exact boundaries, pooled row
weighting, distinct READY versus paired means, true outer training means and
empty intervals. Real ordinary, Q25 and Q31 sources must reconstruct with one
Q5 read. Q25 uses each actual outer refit; Q31 metrics/bins equal its fixed
reference while decisions may differ. Wrong complete-procedure evidence must
fail. Existing causal fitter/selection tests remain applicable and run in
natural CI. Real CLI/native source relocation, failure/retry, complete evidence
and input-capture behavior are required. Source bytes and legacy Q21 remain
unchanged.

Exclude refitted calibration, new thresholds, probability metrics, execution
attribution by bin, selecting the best bin and TEST diagnostics.

## Q34 — fixed inner-objective single-day sensitivity

### Goal and method

For an AVAILABLE Q25 or Q31 study, inspect every original outer inner window
and the separately labelled final-DEV window. For each original five-day
holdout, remove each declared day from the objective once, holding saved
models, predictions and accounts fixed. Preserve the original winner and all
six/four original member objectives. Record every perturbed objective, winner,
runner-up margin, changed-choice flag and availability; show selection counts
as descriptive counts, not probabilities.

Q25 reuses `pooled_mse` over remaining saved `scored_targets`, joined by
observation key. Losses remain COMPLETE-row-weighted, not equal-day-weighted.
A day with no scored targets has an explicit unchanged perturbation; removing
the only scored day yields NO_REMAINING_COMPLETE_TARGETS.

Q31 uses each original daily cash ratio and computes the ordered product of
the remaining `(1 + daily_return)` values minus one. It does not subtract
absolute cash PnL or sum returns, and retains cash-only days. It needs no
COMPLETE target labels. Original winners use saved verified objectives;
perturbed winners use the new declared product arithmetic. Finite arithmetic
and FIRST_DECLARED exact ties remain explicit. The original account is never
edited or rerun.

### Acceptance and exclusions

Use a Q25 unequal-row-count example and Q31 cash-compounding example where
one day's removal changes the choice. Check ties, zero-target/cash days and
no-remaining-target unavailability. Both real saved formats must complete
CLI/native analysis with Q5, fit and Q6 calls prohibited, preserve source
bytes and retain failed/stale-result recovery. An unavailable whole study
cannot expose apparently available but uncomputed windows.

This is fixed-fit objective sensitivity. It is not leave-day-out retraining,
jackknife inference, a probability of selection or a replacement choice for
Freeze. No optimizer, additional family member, new TEST format or automatic
promotion is introduced.

The API is `analyze_intraday_inner_objective_sensitivity(snapshot)` in
`research/intraday_inner_objective_sensitivity.py`. Its derived report version
is `market-vault-intraday-inner-objective-sensitivity-v1`. It accepts only an
immutable Q25/Q31 study, with no alternative source, candidate or Q5 parameter.
All six/four members remain in every comparison; an unavailable member blocks
that perturbed choice instead of reducing the family. A numeric failure has an
explicit unavailable reason. Each window retains its entire original inner
evidence, its original winner and objective values, all five perturbed member
objectives, positive winner-to-runner-up margin (zero for ties), and counts
over explicitly available omissions. FINAL_DEV remains separately labelled.

```console
market-vault research-intraday-inner-objective-sensitivity \
  --experiment /absolute/saved-study.json
```

The native **ML diagnostics** page adds the fixed inner-objective method to
the existing source workflow. Choosing a draft method does not reinterpret a
previously completed report. Q34 offers window, original member, omitted-day,
omitted-day member, selection-count and full fixed-evidence views. Ordinary
candidates and Q5 relocation are not inputs to this method. All models, keys,
scores, targets and original daily cash evidence remain available in paginated,
selectable JSON; no target or account is recomputed by the desktop.

## Q35 — selected-procedure incremental outer returns

### Goal and method

For an AVAILABLE Q25/Q31 saved study, derive three complete recorded daily
return paths: its selected outer procedure, the originally bound fixed source
candidate, and that source group's benchmark. Add synchronous paired series
`procedure - fixed_reference` and `procedure - benchmark`. Bind the study's
original reference indices/ID; do not choose a new reference after seeing
results or masquerade the selected procedure as an ordinary fixed strategy.

Check the common full outer dates, sessions, price evidence, decision support,
execution/cost definitions and cash reconciliation. Preserve cash-only days
and original fold contribution evidence. Reuse Q15's stationary-bootstrap
implementation for all five series with the same indices: 5,000 replications,
seed 0, 95% percentile intervals, existing cube-root expected block length,
at least 100 dates, at least ten expected blocks and the existing internal-gap
gate. Short samples keep observed values and unavailable interval reasons.

The API is `analyze_intraday_procedure_return_uncertainty(snapshot, *,
block_days=None, replications=5000, seed=0)` in
`research/intraday_procedure_return_uncertainty.py`. Its new derived version is
`market-vault-intraday-procedure-return-uncertainty-v1`. The only source input
is an immutable Q25/Q31 study. The source view comes from Q33; Q15 supplies
daily-cash reconciliation, coverage, means, shared sampling settings and the
existing interval engine. Q34 precedes this task in delivery but its sensitivity
result is not a new input or selection rule.

The five ordered series are `procedure`, `fixed_reference`, `benchmark`,
`procedure_minus_fixed_reference` and `procedure_minus_benchmark`. Daily
returns are `cash_close / cash_open - 1`; the last two subtract synchronized
daily returns. Their arithmetic means and 95% intervals are in RATIO units,
not differences of compound returns or investable synthetic accounts. The
three complete original accounts and fold contributions remain in the report.

The common basis compares actual full dates, session clocks, raw price rows,
execution windows, price IDs, cost/execution versions, initial cash, risk
definitions and original source bindings. Procedure and fixed reference share
all READY identities and their original execution policy. The benchmark keeps
its different declared full-session `max_hold_bars` and must contain exactly
each day's first eligible READY decision. Full raw price/decision projections
are compared before compact digest/count evidence is displayed; this is
recorded consistency, not an execution replay. A failed common basis blocks
both paired series while valid individual means remain descriptive.

Unavailable accounts retain Q15's explicit reasons. An unavailable whole
study has no account paths or statistics. Constant, short, gapped, numerically
invalid and insufficient-expected-block samples retain existing interval
reasons; the 100-day/ten-block requirements are engineering minima, not a
claim of statistical adequacy. Explicit replication counts are integers from
1,000 through 20,000; seeds are integers from 0 through `2**32 - 1`; explicit
block lengths are integers of at least two evaluated days.

```console
market-vault research-intraday-procedure-return-uncertainty \
  --experiment /absolute/saved-study.json
```

The CLI optionally accepts `--block-days`, `--replications` and `--seed`.
The native ML diagnostics page adds the outer-return method with the same
defaults and separate views for statistics, daily returns, common-basis checks
and complete original account evidence. Pagination and account/section filters
only affect reading. They never alter the analyzed sample, captured inputs or
report identity. Accounts display percentages and paired differences display
percentage points; complete JSON retains the original RATIO values.

### Acceptance and exclusions

Independent daily-cash and paired-difference oracles must detect reversed
subtraction, independent instead of synchronous resampling, missing cash days
and mismatched reference/baseline evidence. Preserve existing short-sample,
gap, constant and numeric reasons. CLI/native real sources must complete with
no Q5 read, model fit, Q6 run or saved-file write.

The intervals describe the recorded outer daily-return process conditional on
block-resampling assumptions. They do not resample training and selection,
correct unknown research attempts, supply a future-profit probability or
constitute a family-wide correction. Inner/final-DEV/TEST accounts, arbitrary
study ranking and automatic promotion are excluded.

## Verification cost and method references

Reuse existing numerical engines and one compact real-source fixture across
related checks. New tests use existing file-ownership prefixes; the ten
Python 3.11 partitions, 3.14 compatibility and package gates remain in force.
Native Qt is validated locally because GitHub's dev install omits PySide6.
Monitor natural job durations; rebalance only for measured overload, with full
test collection and unchanged success conditions. Do not manufacture a shorter
job by dropping tests or shortening a timeout.

- [scikit-learn: common pitfalls](https://scikit-learn.org/stable/common_pitfalls.html)
  documents the training-only preprocessing and held-out-data boundaries
  already enforced by the repository.
- [scikit-learn: prediction and decision thresholds](https://scikit-learn.org/stable/modules/classification_threshold.html)
  separates prediction from action and illustrates how changing thresholds
  can leave raw predictions unchanged. This package uses continuous returns
  and the existing intraday account, not that page's classifier implementation.
- Q35's numerical method, assumptions and sample gates are the existing
  [Q15 contract](intraday_research_quality.md), not a new statistical engine.
