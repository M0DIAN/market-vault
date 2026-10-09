# Saved DEV research quality: Q15–Q17

This task package was selected against main
`777bfad359afb1dae3b58fa271aa303460a623e4` after Q1–Q14. The sequence is
**Q15 return uncertainty → Q16 declared-family simultaneous bounds → Q17
two-strategy complementarity and fixed initial capital sleeves**. Each item
has its own implementation PR, final-candidate independent review, required
CI, squash merge and verification of the resulting natural main-push CI before
implementation of the next item begins. This is source development and
integration; release, deployment and live trading are outside this package.

## Why these three tasks

The existing system already provides rule/Composite/Ridge comparisons,
point-in-time Features, explicit chronological splits, actual-target-end
purging, expanding walk-forward fits, complete intraday execution accounts,
immutable records and a frozen-candidate TEST workflow. The recent additions
cover [cash and cost attribution](intraday_performance.md),
[execution-policy scenarios](intraday_execution_scenarios.md),
[complete saved A/B comparison basis](intraday_saved_comparison.md),
[risk paths and fold descriptions](intraday_risk_diagnostics.md),
[numeric parameter neighbors](intraday_parameter_grid.md) and
[complete plan reuse](intraday_plan_reuse.md).

Those capabilities do not estimate the uncertainty of a saved daily advantage,
adjust a declared set of candidate estimates jointly, or describe the benefit
and capital meaning of combining two saved strategies. The next tasks add
those outcomes using recorded DEV evidence; they do not require new model
training, source access or changes to the execution engine.

| Direction | Research value and current evidence | Package decision |
| --- | --- | --- |
| Paired dependent-return uncertainty | Q7 already saves every daily cash account and its policy-matched benchmark. Q12 describes the sample, without a confidence interval for its mean. | Q15 first: establish an explicit, reusable daily sampling policy. |
| Multiple comparisons within a declared family | One saved Q7 cost group already contains synchronized candidate returns. Looking at each candidate's marginal interval does not account for looking across the group. | Q16 second: use all recorded candidates and joint resampling. |
| Strategy complementarity and capital allocation | Q11 supplies a complete common evaluation basis; Q6 accounts allow fractional positions and proportional costs, with flat session boundaries. | Q17 third: two explicit candidates and fixed initial capital sleeves. |
| New purge/embargo layer | Q7 and Q8 already purge on actual target end strictly before the evaluation open. Historical-only training and same-session targets do not establish a missing-embargo defect. | No duplicate training-boundary work. Reassess if a future CV design includes future training segments. |
| PBO/CSCV | Synchronized returns exist, but symmetric train/test recombinations answer a different selection question from the causal expanding walk-forward procedure. | Defer; do not label a reordered shortlist result a global overfitting probability. |
| Deflated Sharpe ratio | The complete historical search and effective independent trial count are unknown. The number of saved grid cells is not that count. | Defer rather than invent trial inputs. |
| Nested walk-forward selection | It can evaluate the entire parameter-selection procedure on future outer folds, but requires inner/outer windows, repeated selection/fits and new selection evidence. | Defer until the research history and selection use case justify the additional data and computation. |
| Multi-asset/shared-capital execution | Current Q5/Q6 accounts contain one symbol, and Q7 executes candidates independently. Shared order priority, netting and capital constraints are not recorded. | Defer the new execution contract. No optimizer or portfolio platform. |

Q8 protects the data flow for a given frozen candidate. It does not maintain a
global history of TEST views or prove that a researcher never used a previous
TEST result to choose another candidate. This package neither makes that claim
nor adds a global TEST lock or experiment-history database.

## Common scope and evidence

The new statistics use ordinary saved Q7 comparison/diagnostics records. A Q10
scenario must first be exported as its existing ordinary Q7 child. TEST is not
used to select candidates, assess a family or construct these portfolios.
Existing Q11 descriptive TEST comparisons retain their current behavior.

Inputs remain immutable `StrategyExperiment` records. Derived results retain
the actual experiment/data/candidate/execution identities, selected positions,
policies and method parameters. Their evidence is recorded-ledger derivation,
not source verification, Replay or a new execution. None of these actions
reads Q5/Canonical data, fits, trades, mutates a source file, automatically
chooses a candidate, or promotes a result into Freeze/TEST. Existing saved
schemas, identities and package version 0.9.0 remain compatible.

Q9 cash reconciliation, Q12 ledger/fold checks and the relevant complete Q11
comparison basis are reused. Invalid files and invalid arguments fail; valid
but unsupported or insufficient recorded evidence gives explicit unavailable
derived values. Missing observations never become invented zero returns.
Actual saved cash days remain in the sample.

## Q15 — paired DEV return uncertainty

### Goal and method

For a selected cost/candidate, recompute daily net returns from recorded cash:

```text
strategy_return[t]  = strategy_cash_close[t] / strategy_cash_open[t] - 1
benchmark_return[t] = benchmark_cash_close[t] / benchmark_cash_open[t] - 1
paired_excess[t]    = strategy_return[t] - benchmark_return[t]
```

The three estimands are arithmetic means per evaluated trading day. Excess is
an arithmetic return difference, not a compound relative-wealth path. In
particular, multiplying `1 + paired_excess[t]` does not produce the ratio of
strategy wealth to benchmark wealth.

Use the same stationary-bootstrap day indices for all three series. A sample
starts at a uniformly selected day. Each subsequent index restarts uniformly
with probability `1 / block_days`, otherwise moves to the next original day,
wrapping the final index to the first. Each replicate has the original day
count. Blocks may cross recorded walk-forward fold boundaries; the analysis
conditions on the saved fitted strategies and does not refit or repeat the
original selection process.

The interval is the 2.5%/97.5% percentile interval of bootstrap sample means,
with linear `(B - 1) * p` interpolation. It is an approximate interval under
stationarity, weak dependence and adequate moment/sample conditions. Those
conditions are assumptions, not outcomes verified by this command. It is not
a prediction interval for a future day or a probability of profitable trading.

### Defaults and availability

| Setting | Default or rule |
| --- | --- |
| Replicates | 5,000; explicit integer values from 1,000 through 20,000 |
| Seed | 0; explicit integer from 0 through 2^32 - 1 |
| Mean block length | `max(2, ceil(n^(1/3)))`; optional explicit integer at least 2 |
| Nominal interval level | 95%, fixed in this version |
| Minimum evaluated history | At least 100 evaluated trading days |
| Minimum expected sampled blocks | `1 + (n - 1) / block_days >= 10` |
| Sample time axis | One continuous slice of the saved TRAIN + VALIDATION trading-day sequence |
| Cash return denominator | Finite and strictly positive |
| Output scale | Unannualized return ratios; percentage formatting only in presentation |

The block rule is a transparent heuristic, not an estimate of an optimal block
length. The 100-day and 10-block thresholds are conservative engineering
admission rules, not a theorem establishing statistical sufficiency. Increasing
the number of bootstrap replicates improves simulation resolution; it does
not add independent market history.

Initial training days before the first evaluated day and an incomplete tail
after the last evaluated day do not create a gap. An omitted declared trading
day between evaluated days does. Weekends and closures absent from the saved
trading-day sequence are not gaps. A gap preserves valid sample means but
makes inference unavailable; there is no filling, truncation or ad hoc
segmented resampling.

Each series keeps its mean separately from interval availability. Insufficient
history and an exactly constant sample retain their valid means and have null
intervals. A constant sample receives `ZERO_SAMPLE_VARIATION`; no zero-width
interval is presented as statistical certainty. A nonconstant series whose
resampled means degenerate has a separate reason. The small-return sign
tolerance used in Q12 is not applied to the numbers used for inference.

A failed strategy or benchmark cash/ledger check affects that side and the
paired excess, while the other valid side remains describable. Pairing also
requires a matching common basis; mismatching recorded prices or session
clocks cannot produce a paired difference.

### Acceptance and exclusions

Acceptance requires a numerical oracle for the block mechanism, wraparound,
paired means and quantiles; preservation of cash days and finite small returns;
and explicit handling of gaps, short history, constant data, historical
versions and local reconciliation failure. A real saved DEV file with enough
history must reach the actual console and desktop success path. A short file
must retain means while refusing inference. Selected nonfirst cost/candidate
positions, bilingual display and cache invalidation must bind the displayed
result to the correct record. Derivation must leave input bytes unchanged and
avoid source loading, fitting and execution.

No Sharpe/bootstrap drawdown interval, synthetic path forecast, strategy
ranking, automatic block optimization or new training procedure is included.

### API, console and desktop

`research.intraday_return_uncertainty.analyze_intraday_return_uncertainty`
accepts an immutable snapshot and keyword arguments `cost_index=0`,
`candidate_index=0`, `block_days=None`, `replications=5000`, `seed=0`.
`None` selects the cube-root block default. Indices use recorded zero-based
positions; boolean and noninteger parameter values are rejected.

```console
market-vault research-intraday-return-uncertainty --experiment /absolute/development.json --cost-index 1 --candidate-index 2
market-vault research-intraday-return-uncertainty --experiment /absolute/development.json --block-days 5 --replications 5000 --seed 0
```

The settings-independent command returns a `SUCCESS` envelope containing the
report, with version `market-vault-intraday-return-uncertainty-v1`. The report
has `statistics` rows for `strategy`, `benchmark` and `paired_excess`. Each
row separates `mean_unavailable_reason` from `interval_unavailable_reason`;
`lower` and `upper` are null when inference is unavailable. `sample` retains
evaluated dates, gaps, fold and prediction coverage. `sampling` records the
actual method, PRNG, seed, block rule, repetitions and admission thresholds.
`basis` gives matching status and failed check names. `uncertainty_id` binds
the complete derived report.

Unavailable inference is a successful analysis of limited recorded evidence.
Invalid files, unsupported artifact kinds and invalid integer argument values
return structured stderr `FAILED` with exit 1; noninteger CLI tokens are
argparse errors with exit 2. JSON envelopes use ASCII escapes for non-ASCII
names and paths, including on a strict legacy-code-page console.

In **Quant Research → Intraday → Development research**, save or open an
ordinary DEV experiment, select the recorded cost/candidate, then select
**DEV return uncertainty** in the details view. The desktop uses the fixed
defaults above and displays the actual sample and sampling parameters. It
runs the calculation through the existing background worker. Changing the
candidate or loaded result invalidates the current cached report; an old
in-flight result cannot replace the new selection. View/language changes
preserve a completed report. Analysis errors are explicit and retryable.
The desktop formats paired excess as percentage points; API/CLI values remain
raw ratios. An unsaved result or a Q10 collection must first become an ordinary
saved DEV experiment.

## Q16 — complete declared-family simultaneous lower bounds

### Goal, dependency and method

This task follows Q15 and reuses its daily admission, sampling and numerical
rules. Input is one explicit cost group and **every candidate in that saved
group**, in recorded order. The output identifies the entire family and says
`SAVED_COST_GROUP_ONLY`; coverage of other historical research is `UNKNOWN`.
It does not accept a handpicked list of winners or combine other files/costs.

For each candidate `j`, compute its arithmetic daily net excess over the
group's recorded policy-matched benchmark. Apply one common set of resampled
date indices to the complete vector. For bootstrap replicate `b`:

```text
delta[b, j] = resampled_mean_excess[b, j] - observed_mean_excess[j]
maximum[b]  = max_j(delta[b, j])
deduction   = max(0, percentile_95(maximum))
lower[j]    = observed_mean_excess[j] - deduction
```

Report this single-step, unstudentized, nominal 95% one-sided simultaneous
lower bound. This uses the first joint-region construction in Romano–Wolf;
it does not implement their subsequent step-down procedure. The common
unstudentized deduction avoids estimating an effective trial count or a
long-run variance for each strategy. A volatile member can make all bounds
more conservative. No finite-sample 95% coverage guarantee is asserted.

All members must have compatible, valid daily evidence. A bad member makes
family inference unavailable, with its reason retained; it is never silently
removed. Constant excess columns stay in the declared family and in the
centered maximum as zeros, but their own lower bounds are unavailable. Other
nondegenerate members may receive bounds, with their availability explicit.
If all columns or the joint resampled statistic degenerate, the family bounds
are unavailable. There is no inferred positive result for a constant sample.

### Acceptance and exclusions

An independent small-matrix oracle must verify centering, joint maxima,
quantiles and lower bounds. Adding a duplicate return column must not change
the mathematical deduction. Reordering candidates may change row order, but
not their mathematical bounds. A hidden invalid member cannot disappear from
the family. The actual CLI/desktop must show all members, selected cost,
family scope, sample/method parameters and availability without a new fit/run.

No global overfitting probability, p-value panel, quality score, winner,
automatic Freeze, PBO, DSR, studentization, step-down, arbitrary multi-file
registry or reconstruction of unseen historical trials is included.

## Q17 — A/B complementarity and fixed initial capital sleeves

### Goal, dependency and admission

After Q16, extend the existing Saved A/B workflow for two explicitly selected
ordinary DEV candidates. Q11's complete common basis must match, including
data/symbol, actual days, decision/fold identity, and the common raw price and
session projections of both candidates and both policy-matched benchmarks.
Use the existing Q9/Q12 consistency checks. Do not weaken Q11 or silently
take a date intersection. Different Features, strategies or execution policies
remain permissible when the complete recorded evaluation basis matches.

Complementarity describes Pearson correlation of net daily returns, joint
loss days and actual simultaneous holding minutes. Include cash days; never
correlate cumulative equity or scores with different meanings. Fewer than two
days or zero return variance makes correlation unavailable. Loss-day
classification uses the existing 1e-12 sign tolerance without rounding input
returns. Holding overlap uses each shared OPEN→CLOSE interval's real elapsed
minutes and divides by all evaluated session minutes, preserving early closes.

### Fixed initial capital convention

Start total capital at 1. Defaults are `weight_a = 0.5`, `weight_b = 0.5` and
`cash_weight = 1 - weight_a - weight_b`. All weights are finite, nonnegative;
the sum of A and B cannot exceed 1. Do not automatically normalize them.
Allow 1/0, 0/1 and 0/0. Cash earns zero interest. Each sleeve retains its own
profit, loss and idle cash; no capital is transferred between sleeves.

At every common recorded OPEN/CLOSE position:

```text
portfolio_equity = cash_weight + weight_a * equity_a + weight_b * equity_b
portfolio_cash   = cash_weight + weight_a * cash_a   + weight_b * cash_b
daily_return     = portfolio_cash_close / portfolio_cash_open - 1
```

This fixed scaling is supported by the current fractional-position,
proportional-cost account. Fees already included in each sleeve's equity are
weighted for attribution and are not deducted again. Preserve both original
policies. Construct the comparison benchmark using the same initial weights
and each sleeve's own policy-matched benchmark.

Recompute total return, daily risk and observed drawdown from the combined
path. Never average drawdowns or compound constant-weight daily returns.
Preserve distinct same-clock CLOSE/OPEN sequence positions. Sleeve cash
contributions must sum to final combined cash minus 1. Initial capital shares
stay fixed while the sleeves' proportions of current wealth drift.

### Acceptance and exclusions

The distinguishing two-day oracle is A returns +100%, then -50%, with B in
cash: 50/50 fixed initial sleeves produce equity `1 → 1.5 → 1`, final return
0%. Daily resetting to 50/50 would instead produce 12.5%, and is not this
operation. Verify source-account endpoints, all-cash behavior, no double fee
deduction, actual holding overlap and contribution reconciliation. Same-source
50/50 must reproduce the original path. Actual console and bilingual desktop
actions must bind sources/weights to results; later draft changes or failures
preserve the last successful result and its captured identities.

No daily/periodic rebalancing, leverage, shorting, capital borrowing,
cross-strategy cash reuse, netted orders, multi-asset/FX alignment, transaction
capacity model, automatic weighting or N-strategy matrix is included. Under
the current idealized account, daily reallocation could also be derived from
saved daily returns if its capital-transfer assumptions were explicitly
adopted; it remains a different deferred model. True shared-capital/netted
execution requires a separate order and cost contract.

## Method references

- Politis, [Bootstrap Methods for Time Series: A Selective Overview](https://www.math.ucsd.edu/~politis/TALKS/slidesCyprusBOOT2004.pdf):
  blocking assumptions and the stationary-bootstrap construction.
- White (2000), [A Reality Check for Data Snooping](https://users.ssc.wisc.edu/~behansen/718/White2000.pdf):
  joint dependent-return resampling and the stationary-bootstrap algorithm.
- Romano and Wolf, [Stepwise Multiple Testing as Formalized Data Snooping](https://econ-papers.upf.edu/papers/712.pdf),
  October 2003 working paper, section 3, equations (8) and (10): first-step
  simultaneous lower confidence region; its validity is asymptotic and
  conditional on the resampling assumptions.
- Bailey and López de Prado, [The Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf):
  trial-count and selection inputs not supplied by a saved shortlist.
- Bailey et al., [The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf):
  the different CSCV selection/rank experiment considered for later work.
