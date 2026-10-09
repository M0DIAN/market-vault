# Research quality package: Q18–Q20

This package is based on the actual code and research contracts on main
`c52373cd3953b060923e3885c57cc20f79422d43`, after Q1–Q17. Its sequence is
**Q18 sequential candidate selection → Q19 per-signal bar-delay stress →
Q20 daily cash reallocation between two strategy sleeves**.

Each item is implemented in a separate PR. Its final published candidate must
pass fresh independent review and all required CI with matching code, tree and
version evidence. After the authorized squash merge, the exact natural main
push and its CI must be verified before implementation of the next item starts.
The repository's existing CI classifier, review gates and release process are
unchanged. This package covers source development and integration, not a
release, deployment or live trading.

## Selection of the three main tasks

Q1–Q14 already establish verified intraday data, point-in-time Features,
actual-target-end purging, historical-only expanding fits, common evaluation
dates, complete execution accounts, frozen-candidate TEST, finite cost and
execution-window scenarios, saved A/B comparison, risk/fold descriptions,
parameter neighbors and reusable plans. [Q15–Q17](intraday_research_quality.md)
add dependent daily-return intervals, simultaneous lower bounds for a complete
saved cost group and fixed initial capital portfolios.

The next package adds three different research questions. It does not infer a
single research-quality score from the existing reports.

| Direction | Actual remaining question | Decision |
| --- | --- | --- |
| Selection overfitting | How does a declared rule that selects candidates from past results perform on subsequent dates? Individual historical fits and Q16's joint bounds do not evaluate that rule. | Q18, first. |
| Execution robustness | Do the same signals retain their outcome when every signal arrives one or two bars later? Q10's `entry_delay_minutes` is an opening entry window, not a delay applied to every signal. | Q19, second. |
| Portfolio capital management | What changes when cash is returned to declared target weights before each evaluated session? Q17 lets the initial sleeves' wealth shares drift. | Q20, third. |
| Complete nested walk-forward | A different inner/outer training schedule or Feature search would require new fits and source-level selection evidence. The current fixed historical origins can already support Q18's narrower selection question. | Defer the general engine. |
| Cost headroom | A continuous break-even slippage threshold would quantify more than the existing finite cost grid, but Q7/Q10 already provide explicit cost stress. | Defer; prioritize the missing signal-delay assumption. |
| More fold/parameter/interval displays | Q12, Q13 and Q15 already expose these dimensions. An additional presentation alone does not create new validation evidence. | No separate main task. |
| PBO, DSR or global search history | Saved grid size does not establish the complete or effectively independent historical trial count; CSCV answers a different selection experiment. A new registry cannot recover earlier unseen research. | Defer; do not invent trial counts or global overfitting probabilities. |
| Additional purge/embargo layer | Current Q7/Q8 train on earlier dates and purge actual target ends. No new defect or future-training split is established by this package. | Preserve existing contracts. |
| Shared capital, netting or optimized weights | There are no joint orders, priority or market-impact records. Optimization also creates another selection procedure. | Outside this package. |

Q18 and Q19 are separate questions on ordinary saved DEV records. Q19 does not
consume the Q18 derived path. Q20 directly reuses Q17's source admission and
account conventions; its scheduling after Q18/Q19 is a research priority, not
an invented file-format dependency. This sequence examines selection and
execution assumptions before adding another capital-allocation model.

## Common defaults and boundaries

- Inputs are explicit ordinary saved Q7 DEV comparison/diagnostics records.
  An existing Q10 collection must first be exported as an ordinary child.
  TEST and frozen-selection files do not enter these new analyses.
- Existing experiment files are immutable. No input bytes, old saved schema,
  original identity, plan grammar, Freeze/TEST behavior, dependency, workflow
  or package version is changed. Package version remains 0.9.0; each new
  derived report has its own version and content identity.
- Reuse Q9/Q12 account checks and the relevant complete Q11 comparison basis.
  Do not silently intersect calendars, remove a bad family member, fill absent
  observations with zero returns, or bypass a bad zero-weight source.
- Use actual daily cash returns, including saved cash days and the first
  evaluated day. Return values are raw ratios in API/CLI. Display percentages
  and percentage-point differences with their distinct meanings.
- Each action decodes each input once and reuses verified account evidence
  only within that action. There is no persistent source-validation cache.
- Invalid arguments/files fail. Valid but insufficient, unsupported or
  incompatible recorded evidence produces explicit unavailable derived
  values. Known source identities and method parameters remain visible.
- Settings-independent CLI commands emit ASCII-safe JSON. Desktop background
  work captures its inputs; an old result cannot be labeled as a new selection.
  Bilingual presentation must expose the actual method, sample and reasons.

These are retrospective studies on a declared saved family and its fitted
strategies. No file establishes that the family, selection rule, execution
stress or weights were chosen before a researcher viewed the complete DEV
sample. The package does not repair unknown research history or establish live
profitability. Q8's separate frozen-candidate TEST contract remains unchanged.

## Q18 — sequential selection on a complete saved family

### Goal and technical contract

Evaluate one explicit selection procedure on subsequent complete Q7 folds.
Input is one cost group and **every recorded candidate in that group**, in
recorded order. There is no candidate-subset argument and no search over cost
assumptions.

At each fold opening, score all candidates using only the daily net excess
returns from earlier completed folds. After the required history exists,
select the greatest arithmetic mean and use that candidate for the entire
current fold. An exact tie goes to the lowest recorded candidate index. A
negative best score still selects that candidate; there is no implicit cash
filter. The current and later folds cannot influence the current decision.

| Setting | Default or rule |
| --- | --- |
| Selected cost | `cost_index=0`; explicit nonnegative integer |
| Minimum scoring history | `minimum_history_days=20`; explicit positive integer |
| History | Expanding, all earlier completed evaluated folds |
| Selection time | Current fold's first session open |
| Selection score | Mean net daily return minus the group's own daily benchmark return |
| Tie | Exact equality, lowest recorded candidate index |
| Holding period for selection | Entire next existing complete fold |
| Time axis | Continuous saved evaluated slice of TRAIN + VALIDATION; internal gaps make this version unavailable |
| Initial selected account | Cash 1 at the first post-history fold |
| Switching | Between flat session boundaries; no invented security transaction or additional fee |
| Inference | Descriptive forward selection results; no automatic bootstrap interval or probability |

Twenty days is an engineering default, not a statistical sufficiency theorem.
Do not reduce it automatically for a short input. With Q7's default 20 initial
training days and 5-day folds, at least 40 DEV days are consumed before the
first selection-following evaluation. A default-split 130-session dataset has
110 DEV days and at most 70 subsequent days under those defaults. Bars within
one session are not additional independent selection dates.

The saved historical fits are reused: each chosen fold already has its own
historical model and training keys. Check the saved fold opening against the
recorded session clock and retain model bindings. Do not refit, infer source
PIT validity from a saved result, or call this a complete nested-CV engine.

Construct the selected cash/equity path by scaling the chosen source account
relative to its opening cash on the selected period. Never join two source
accounts' absolute cash values. Preserve all ordered OPEN/CLOSE positions,
including distinct positions at the same UTC timestamp, and recompute the
combined observed drawdown and Q7 daily risk. The benchmark is independently
rebased over exactly the same subsequent dates. All fixed candidates may be
shown as descriptive references on that same subsequent sample; none is
labeled a hindsight winner or an estimate of overfitting loss.

Retain the complete family, full history dates and fold IDs, all scores at
every selection, selected candidate/model identities, warmup folds, selection
and switch counts, chosen fold/day counts, subsequent daily/path records and
same-sample static references. The report explicitly says
`SAVED_COST_GROUP_ONLY` and `historical_search_coverage=UNKNOWN`.

### Acceptance

The central oracle changes a current/future fold's returns and proves that
current/earlier choices do not change; changing past returns can change a
later choice. A reversal example must pick the past winner even when that
candidate subsequently loses. Hand-computed cash compounding, same-sample
references, exact ties, hidden invalid members, short history and internal
gaps must be exercised. A real saved file must pass through the installed CLI
and production desktop action at a nonfirst cost group. Verify source bytes
unchanged and no Q5 load, fit or execution. Test the changed workflow, not a
second copy of Q15/Q16's unrelated inference matrix.

### Exclusions

New Features, models or training origins; automatic history-window/score
search; global search correction; PBO/DSR; arbitrary inner/outer CV; inference
on the adaptive account; automatic Freeze/TEST; a final winning candidate;
and representing the derived account as an original Q7 execution.

### API, console and desktop

`research.intraday_sequential_selection.analyze_intraday_sequential_selection`
accepts an immutable `StrategyExperiment`, `cost_index=0` and
`minimum_history_days=20`. Integer validation excludes booleans. The API
returns report version `market-vault-intraday-sequential-selection-v1` and a
`sequential_selection_id` binding the full report.

```console
market-vault research-intraday-sequential-selection --experiment /absolute/development.json --cost-index 1
market-vault research-intraday-sequential-selection --experiment /absolute/development.json --minimum-history-days 40
```

An explicitly chosen history threshold is part of the procedure being
evaluated. Trying many thresholds and reporting the most favorable one is
another selection step, which this report does not correct.

The report separates `source_sample` from the subsequent `sample`, and
separates `basis`, `causality` and account `availability`. `folds` retains every
warmup/selection row; `members` retains the complete declared family.
`strategy` and `benchmark` contain the independently recomputed summary/risk
metrics. `static_references` uses exactly the same subsequent dates; `path`
and `daily_returns` retain chosen source bindings.

In saved ordinary DEV details, select **DEV sequential selection**. The
desktop uses the fixed 20-day history default and the selected cost group.
Its local views expose summary, selection timeline, all historical scores,
same-sample fixed references, daily results and ordered path. Candidate
changes within the cost group retain the completed report; source/cost changes
invalidate it. Full identities and history dates remain inspectable. A failed
analysis is explicit and retryable.

## Q19 — per-signal bar-delay stress

### Goal and technical contract

For one explicitly selected saved DEV candidate, measure the effect of
additional whole-bar signal delay. The desktop uses the finite **0, 1, 2 bar**
set, and the API/CLI use that same fixed set in this version. Delay is measured
on the session's full planned grid, including bars
without a new READY observation. It applies to both LONG and FLAT signals.
This is a coarse discrete stress assumption, not a measured real-world latency.

Shift a decision at the close of slot `i` to the close of slot `i + delay`.
The unchanged Q6 kernel consumes it at the following planned open. Preserve
the original observation key, score, slot and time in a provenance mapping;
delayed decision identities and arrival times are explicit derived values.
An arrival at the final session close has no following open and is marked
unconsumable. Arrivals outside the session are excluded with an explicit
reason. No signal moves to the next trading day. The zero-delay baseline
retains the original in-grid decision sequence, including its unconsumable
final-close signals.

Entry/stop windows, max-hold and EOD forced flattening keep their existing
calendar semantics. Risk controls are not delayed with signals. Apply the
same delay to the original policy-matched benchmark decisions; do not replace
a late benchmark entry with a newly selected later observation. All scenes
use the same saved sample, prices, policy, commission and slippage.

The input ledger contains the open/close price grid and row identities needed
by the pure Q6 numerical kernel. Reconstruct that minimal grid and session
geometry, check complete source account/basis evidence, and verify zero-delay
numerical reproduction before deriving stress results. Q5 session metadata
is not fully present in the Q7 ledger, so the reconstructed projection's
`price_evidence_id` and execution identity need not equal the source identity.
Compare all other complete execution fields, rather than claiming recovery of
unknown Q5 metadata. Preserve both source and derived projection identities.

The new report is **recorded-price-grid re-execution**, distinct from Q18/Q20's
ledger-only arithmetic and from source-verified Q7 Replay. It contains every
declared delay's complete strategy/benchmark execution, provenance and
unconsumable signals, plus same-sample return, risk, trade and cost changes.
There is no automatic preferred delay, Q7 child export or Freeze eligibility.
Delay can change entry eligibility and trade count, and its effect on net
return need not be monotonic. The report does not label a favorable delay as
an optimal setting or convert these scenarios into a research PASS/FAIL score.

### Acceptance

Require zero-delay agreement of every numerical/semantic execution field,
not just final cash. Use a price-reversal oracle where one-bar delay changes
profit into loss. Verify delayed exits, sparse observations, same-clock
ordering, max-hold and EOD precedence, early-close geometry and session-tail
signals. A bad reconstructed baseline cannot produce apparently valid stress
results. Exercise the real CLI and bilingual desktop on saved evidence;
verify source immutability and absence of Q5 loading/model fitting. Do not
claim that this operation avoids numerical execution: that is its purpose.

### Exclusions

Ticks/order books, measured latency distributions, partial fills, queue
priority, capacity/market impact, cross-session pending orders, changing the
old six-field execution policy, new model predictions, optimizing delays,
live execution, and promoting the derived paths into ordinary Q7 or TEST.

## Q20 — daily cash reallocation for two saved strategies

### Goal and technical contract

Extend the Saved A/B workflow with an explicit model that returns cash to
declared target weights before every **evaluated** session. Q17's fixed
initial sleeves remain the default and retain their existing behavior.

Use Q17's complete Q11 basis and all four account checks, including zero-weight
sources. Initial capital is 1; default target weights are A=0.5, B=0.5, with
`cash_weight = 1 - fsum((weight_a, weight_b))`. Weights are finite, nonboolean,
nonnegative and sum to at most 1; no automatic normalization. Cash earns zero.

At day `t`, allocate the previous combined cash `V` into `w_A * V`, `w_B * V`
and `w_C * V`. Scale every source OPEN/CLOSE cash/equity position and trade
cost by that sleeve's allocated cash divided by its original daily opening
cash. Daily return therefore equals `w_A * r_A + w_B * r_B`. The benchmark
uses its own independent compounded cash with the same targets. Preserve
all ordered intraday marks and recompute risk and observed maximum drawdown.

Before each day after the first, record each sleeve's previous closing cash,
new target cash and net transfer. Transfers sum to zero and do not alter
total cash. Initial allocation is not a transfer; do not add a rebalance after
the final close. Under this explicit model cash-only sleeve transfers cost
zero. They are not security trades or market turnover. Original commission
and slippage are scaled for attribution and never deducted twice.

The model is supported by Q6's fractional positions, proportional fees and
flat session ends. It does not prove broker cash availability or model taxes,
settlement, minimum lots or fixed charges. Unevaluated dates are not invented;
the report and UI retain the actual evaluation schedule and any gaps.

### Acceptance

The distinguishing two-day case is A=+100%, then -50%, with B in cash and
50/50 weights. Q17 ends at 1; daily cash reallocation ends at 1.125. Verify
the second-day transfers, each day's conservation, independently compounded
benchmark, proportional fee attribution, all-cash and one-source endpoints,
same-source equivalence and full-path drawdown. Actual CLI and Saved A/B
actions must retain their captured model, weights and source identities after
draft edits or failures. Reuse saved fixtures and Q17 admission checks; avoid
duplicating every already-closed complementarity test.

### Exclusions

Shared order cash, netting, leverage, shorting, borrowing, multiple symbols or
FX, fixed fees, capacity, settlement/transfer delays, automatic weights,
weekly/monthly/threshold schedules, N-strategy optimization, portfolio
confidence intervals and reinterpretation as an original Q7 execution.

## Implementation surfaces

Q18 adds one research module, one CLI module and its existing CLI dispatch;
Q19 follows the same pattern. Q20 adds a separate capital-model research/CLI
entry while reusing the existing Saved A/B controls. Small shared preparation
helpers are permitted only where needed to avoid duplicate account work.
Desktop changes stay in the existing intraday controllers, localization and
relevant comparison QML panels. Focused tests belong in the existing intraday
research/desktop test files, with fixtures, evidence and temporary outputs
outside worktrees. Documentation updates stay in these research contracts.

No CI/control-plane, dependency, release, Q5 source schema, original Q7/Q8
saved schema, or destructive persistent-state operation is in scope. Any
required repair must preserve these declared boundaries and be reviewed on
the final published candidate.

## Method reference

Cawley and Talbot, [On Over-fitting in Model Selection and Subsequent Selection
Bias in Performance Evaluation](https://jmlr.org/papers/volume11/cawley10a/cawley10a.pdf)
(2010), explains why the model-selection step itself belongs in performance
evaluation. Its experiments are not a finite-sample guarantee for financial
time series. Q18 uses a specific chronological saved-family procedure; the
report's scope and assumptions, not the name of a general validation method,
define the result.
