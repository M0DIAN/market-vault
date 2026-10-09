# Intraday development research (Q7)

This additive research workflow compares FeatureRule, CompositeRule and Ridge
on [verified intraday data](intraday_research_v1.md), using the same
[execution V2 account](intraday_execution_v2.md). A development result contains
the complete candidate predictions, fold models, execution ledger, daily risk
and benchmark evidence. It does not evaluate the held-out TEST period, select a
winner automatically or introduce release, deployment or live trading.

For two explicitly selected saved records, see
[saved experiment A/B comparison](intraday_saved_comparison.md). Matching DEV
evaluation evidence permits neutral differences; TEST remains descriptive.

## Explicit trading-day boundaries

`research-intraday-plan` proposes a plan before evaluation. From the verified
ordered sessions, TRAIN receives `floor(N * 70 / 100)` days, VALIDATION receives
`floor(N * 15 / 100)`, and TEST receives the remaining days. Each group must be
nonempty. The proposal records actual inclusive last trading dates; evaluation
requires those explicit dates and never silently chooses a different split.
The last TEST date must cover the final data session. Days are actual declared
sessions, rather than civil-day counts or percentages of observation rows.

The default expanding walk-forward uses **20 minimum training days, 5 validation
days, and a 5-day step** over TRAIN + VALIDATION. At each fold the training
window starts at the beginning of the development period and ends immediately
before that fold's validation window. Thus some development validation folds
can lie inside nominal TRAIN. TEST never enters a development fit or candidate
evaluation. Only complete validation windows run; a trailing partial window is
recorded among the unevaluated development dates.

Custom positive integer day windows are allowed. Step must be at least the
validation length so evaluation days do not overlap. With a larger step,
unevaluated dates remain explicit gaps; they are not inserted as zero returns.
Every candidate and cost scenario shares exactly the same evaluated days and
READY observation keys. A complete fold with no READY observations is rejected.
A single day without observations stays in the common account as a cash day.
Having observations but choosing Flat throughout remains a valid result.

## Training, predictions and price authority

All plans specify an ordered, unique common Feature projection. Every rule
condition must use it. Feature and Composite rules consume READY Features only;
the target horizon and target completeness do not remove their observations.

Ridge uses the existing implementation and numerical conventions. Each fold
fits its own scaler and model solely on its training rows with READY Features
and COMPLETE targets. Actual target end time must be **strictly before** the
first validation session's open. Equality is purged; observation time or the
nominal target horizon cannot substitute for that actual end time. Training
keys, purged keys, boundary, Feature order, alpha, intercept, coefficients,
means and scales are recorded. The coefficients are in the original Feature
scale, as in the existing Ridge implementation; prediction does not standardize
them a second time.

Ridge predicts every READY validation observation, including the incomplete
target tail at session end. MAE, RMSE and R² use only the subset with COMPLETE
targets. Prediction count and error-sample count are distinct. A missing target
does not remove a potential execution decision. Rule candidates do not invent
regression error metrics or a fitted model.

Each public research action strictly reconstructs and verifies the Q5 data
once. The selected data ID must match before a model is fitted. Before fitting
or trading, the shared evaluated sessions must have every required price slot,
including warmup and unsampled bars. Missing common prices invalidate the whole
run, including an all-Flat candidate. Private prepared contexts are internal
reuse within one already verified action, not an alternative source-admission
API. No persistent fit or data-validation cache bypasses future verification.

## Account, daily benchmark and risk

Each candidate starts with normalized cash 1 and carries settled cash through
all evaluated dates. Each session ends flat. Entry delay, stop-new window,
forced flattening, maximum hold, fresh decisions and costs retain Q6 semantics.
The training target is neither the execution return nor the holding period.

The benchmark takes at most one long trade per evaluated day: the first READY
observation whose next planned open is eligible under the same entry windows,
then the EOD forced-flat open. It uses the same complete prices, costs and day
boundaries as the candidate. Its maximum-hold limit is derived from the full
evaluated session grid, independently of the strategy's 12-bar default. A day
without an eligible observation stays in cash. This definition is recorded as
`FIRST_ELIGIBLE_READY` → `EOD`, with `FULL_EVALUATED_SESSION_GRID` holding rule.

Daily return is `cash_close / cash_open - 1` for **every evaluated day, including
the first day**. Annualized volatility is sample standard deviation (`ddof=1`)
times `sqrt(252)`. Sharpe uses mean daily return, risk-free rate 0 and that same
sample deviation. Fewer than two daily returns gives
`INSUFFICIENT_DAILY_RETURNS`; zero deviation within the recorded numerical
tolerance gives volatility 0 and unavailable Sharpe (`ZERO_VOLATILITY`).
The raw return count and availability reason are retained. Daily risk does not
infer a return from differences between sparse displayed endpoints.

Observed maximum drawdown includes the initial cash and the ordered OPEN/CLOSE
marks from execution V2. It does not assert intrabar high/low extrema. Fold cash
contributions are sums of actual daily cash changes in the continuous account;
they reconcile to final cash minus 1 and do not restart cash at each fold.

## Finite diagnostics

Diagnostics selects one declared development strategy and applies zero, one or
two finite parameter axes. The Q4 axis validation, value normalization,
Cartesian order and candidate naming are reused. Supported axes are rule
threshold, one indexed Composite condition threshold, and Ridge threshold or
alpha. Execution windows and maximum hold are explicit plan settings, not
search axes in this version.

Explicit unique commission/slippage scenarios multiply the candidate grid.
The product must be at most **64 evaluations**, checked before source I/O.
All raw candidates and their coordinates are retained. For the same candidate,
the report records the return change from its first cost scenario. Costs cannot
alter predictions or fitted models. Within one action, equal fold/alpha fits
are reused across threshold variants and costs; different folds or alpha values
receive their own models. There is no optimizer or automatic candidate choice.

After saving diagnostics, use the [parameter grid and neighbor view](intraday_parameter_grid.md)
to inspect exact coordinates and nearby recorded candidates without running
additional evaluations.

[Complete plan reuse and candidate continuation](intraday_plan_reuse.md) saves
comparison, diagnostics or execution-scenarios plans and starts an editable
single-candidate comparison from an explicitly selected saved DEV result.

[Saved DEV research quality](intraday_research_quality.md) adds Q15 paired mean
intervals, Q16 simultaneous lower bounds for every candidate in a saved cost
group, and Q17 two-strategy complementarity and fixed initial capital sleeves.
Q17 extends Saved A/B with explicit initial weights, a combined ordered account
path and cost attribution. Its descriptive calculations use the complete Q11
basis; they do not inherit Q15/Q16's statistical sample gates. The sampling and
capital assumptions remain explicit and separate from the recorded metrics
above.

The [Q18–Q20 research-quality package](intraday_research_quality_next.md)
evaluates a declared sequential selection rule, stresses each saved signal's
arrival time and adds an explicit daily cash-reallocation model. These
derived DEV studies retain their own evidence and do not change Freeze/TEST
eligibility or the original Q7 account.

## CLI and plan grammar

Commands work offline, without settings or OpenD initialization:

```console
market-vault research-intraday-plan --data /absolute/intraday.json --commission-bps 10 --slippage-bps 5
market-vault research-intraday-compare --plan /absolute/research-plan.json --experiment /absolute/development.json --name "Development comparison"
market-vault research-intraday-diagnose --plan /absolute/diagnostics-plan.json --experiment /absolute/diagnostics.json
market-vault research-experiment-open --experiment /absolute/development.json
market-vault research-experiment-replay --experiment /absolute/development.json
market-vault research-experiment-replay --experiment /absolute/development.json --intraday-data-file /relocated/intraday.json
```

The illustrative 10/5 costs above are explicit inputs, not a market assumption
or silent default. The proposal command prints a SUCCESS envelope containing a
`plan` object. Save that object as the research plan; the entire result envelope
is not a plan. The desktop likewise leaves cost fields blank until entered.

The comparison plan contains exactly:

| Field | Required content |
| --- | --- |
| `plan_schema_version` | `market-vault-intraday-research-plan-v1` |
| `intraday_data_path` | Explicit local file, relative to the legal plan parent or absolute |
| `data_id` | Exact Q5 data ID |
| `feature_fields` | Ordered, unique, nonempty Feature names |
| `split` | `train_end_day`, `validation_end_day`, `test_end_day` |
| `walk_forward` | `minimum_train_days`, `validation_days`, `step_days` |
| `strategies` | Existing FeatureRule, CompositeRule or Ridge descriptors |
| `execution` | Explicit commission/slippage and the four Q6 window/hold fields |

The diagnostics plan contains exactly `plan_schema_version` (value
`market-vault-intraday-diagnostics-plan-v1`), `comparison_plan`, `strategy_name`,
`parameter_axes` and `cost_scenarios`. Each cost scenario has `commission_bps`
and `slippage_bps`. Axis syntax follows the existing Q4 finite diagnostics.

Wrong command/plan combinations, unsupported fields, duplicate JSON keys,
nonfinite values and invalid paths fail with a structured FAILED envelope on
stderr and exit code 1. `--name` or `--notes` requires `--experiment`; metadata
is never silently discarded. The research CLI envelope is
`market-vault-intraday-research-cli-result-v1`. Common experiment Open/Replay
uses its additive `market-vault-strategy-experiment-cli-result-v3` envelope for
these intraday artifacts; previous experiment envelopes remain unchanged.

## Immutable experiments and replay

`market-vault-intraday-experiment-v1` uses the existing `StrategyExperiment`
exclusive writer. It binds the complete normalized plan, data ID, algorithm
versions, environment information and raw report. It preserves source paths,
all prediction rows and full precision beyond the desktop's formatting and
100-row pages. Hashes for context, folds, models, candidates, execution, risk
and the full report bind their complete content.

Open validates the saved grammar, finite values, aware clocks, complete arrays,
indices, identities and internal bindings. It reads only the named experiment;
it does not fit a model or access source data. Historical algorithm strings
can remain viewable as recorded results. Open is not evidence that the recorded
computation was executed, and re-signing JSON does not create such evidence.

Replay first requires matching current algorithm versions, then verifies the
Q5 source and data ID, reruns development research and compares the **entire raw
report**. Changes outside the visible page or below display rounding cannot
pass by matching the displayed metrics. A relocated data file is an explicit
loader override with the same data ID; the recorded plan and path remain
unchanged. An offline experiment may preserve a Windows absolute locator on a
different operating system. The original Canonical references inside Q5 must
still be available; relocating the outer file does not relocate its sources.

Save experiment captures the last completed immutable result, regardless of
current form drafts. The writer creates a new named file, or reuses
byte-identical existing content. Different content at that destination is an
error. No existing file is overwritten. Saved replay status is not a
cryptographic execution proof.
Save plan instead captures a complete valid normalized configuration before
its file dialog opens; it does not save unfinished editor text or a result.

## Desktop workflow and evidence

Use **Quant Research → Intraday → Data**, then **Development research**. Research
settings expose actual split dates, day windows, common Features, the existing
strategy editor and all Q6 execution parameters. The proposed dates and entered
costs stay visible before Run. A saved plan's data identity and original locator
remain bound to its settings. Run requires the currently opened Q5 identity and
Features to match, and still reads the plan's own host-absolute locator. A
same-ID file opened at another path never replaces that locator silently.

Comparison and finite diagnostics use the same research adapter as the CLI.
Select any completed cost/candidate result to inspect trades, all OPEN/CLOSE
marks, daily cash, per-fold Ridge model/scaler, all READY predictions, and fold
cash contributions. The daily chart shows the candidate and its daily benchmark
on their actual time axis. Pagination and language changes preserve drafts and
do not recompute results. Load plan and Continue selected candidate bind an
independent editable draft without changing results or evidence. That draft
survives result/Q5 changes, Open experiment, scenario changes, language changes
and editor reopening; only explicit Load or Continue replaces its binding.
Without a bound draft, Open experiment retains its original settings-restoration
behavior. Save experiment and Replay preserve current drafts; failed operations,
including a Run whose original locator is unavailable, preserve the draft and
last result with its page. A failed latest replay cannot retain a previous
replay-match status.

The focused suite uses real 36-day Canonical input with DST, independently
calculated Ridge coefficients, means/scales and benchmark cash/risk. It checks
validation/TEST nonintervention, actual target-end purge, tail predictions,
common missing-price failure, grid/cost ordering and fit reuse. Artifact tests
cover offline access, malformed nested records, full raw replay and relocation.
Actual rendered QML tests exercise research, model/ledger views, pagination,
immutable Save, Open, full Replay and bilingual draft preservation.

Continue with [frozen candidate selection and final TEST](intraday_final_test.md)
after saving the development experiment. Q8 uses the already declared TEST
dates and keeps its final account separate from this development result.

Use the [trade-performance and cash-attribution views](intraday_performance.md)
to inspect a recorded candidate without fitting or replaying it.

Use [saved risk and fold diagnostics](intraday_risk_diagnostics.md) to inspect
drawdown episodes, return distributions, daily contribution concentration and
compound fold returns from the same recorded account.

Use [finite execution scenarios](intraday_execution_scenarios.md) to compare
explicit execution conditions on the same development context and export one
ordinary Q7 child for the existing Freeze / TEST handoff.
