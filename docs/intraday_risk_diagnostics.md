# Saved intraday risk and fold diagnostics (Q12)

Q12 describes the risk path and return distribution of one explicitly selected
saved Q7 development or Q8 TEST result. It consumes the recorded account, trades,
daily cash and, for DEV, the complete declared validation folds. It does not
load Q5/Canonical sources, fit, trade, edit an experiment or change Open/Replay
evidence. The evidence label is `RECORDED_LEDGER_DERIVATION`.

## Selection and availability

Cost and candidate indices are zero-based and default to **0**. The Python API
requires actual nonnegative integers; booleans are not indices. TEST contains
one frozen candidate and accepts only zero indices. Ordinary Q7 comparisons and
finite diagnostics are supported. The API and CLI require an exported ordinary
child when starting from a Q10 collection. The desktop's existing scenario
detail already presents a validated embedded ordinary Q7 child and can derive
its risk directly; the collection and child verification states are preserved.
A frozen selection without an execution has no risk path.

The strategy and its same-window benchmark have independent availability.
Supported execution and fill-cost versions are required. Q9's trade/daily/final
cash reconciliation runs first. Q12 also checks recorded ledger equity against
cash plus marked holdings, recomputed drawdowns against the recorded marks and
maximum, flat session-boundary cash/equity against the daily account, and fold
contributions against the continuous account. A historical
execution/cost version, cash inconsistency or intermediate numeric overflow
makes only that side unavailable; the other side and source identities remain
visible. These are consistency checks on records, not proof of execution.

The reasons distinguish `UNSUPPORTED_EXECUTION_OR_COST_VERSION`, Q9's
`RECORDED_CASH_RECONCILIATION_FAILED`,
`RECORDED_LEDGER_RECONCILIATION_FAILED`,
`RECORDED_FOLD_RECONCILIATION_FAILED` and `NUMERIC_OVERFLOW`. Finite inputs can
still overflow during multiplication or aggregation. No NaN or infinity is
published as a successful numerical result. These additional availability
constraints belong only to Q12. For example, consistently scaling every ledger
cash/quantity/equity mark while retaining the original daily cash can remain
viewable through the existing immutable reader and Q9; Q12 refuses to combine
those contradictory account representations. Old Open, Q9 and Replay semantics
and source files/report IDs are not repaired or rewritten.

## Observed drawdown episodes

The path begins with initial cash at the first evaluated session's official
open, followed by every saved OPEN/CLOSE equity mark in original sequence.
Equal clocks retain their sequence order; no timestamp-only sorting collapses
the CLOSE of one bar with the next OPEN. The synthetic initial position has
`peak_sequence = -1` if it remains the peak.

The latest mark equal to the running peak becomes the new peak position. An
episode begins when equity falls below that peak and recovers at the first mark
at or above it. The first occurrence of the lowest trough is retained when
several marks have the same lowest value. Depth is a nonnegative loss ratio,
`1 - trough_equity / peak_equity`. It describes observed marks, not intrabar
high/low extrema. Recovery comparisons do not use the return-sign tolerance.

Every episode includes peak, trough and recovery sequence/time/equity, depth,
calendar duration and recovery status. An unfinished final episode keeps all
recovery fields null, with duration through the last observed mark. Durations
convert aware timestamps to UTC before subtraction and report elapsed calendar
minutes, including overnight, weekends, DST and unevaluated gaps. They are not
holding minutes or a count of trading minutes. The summary contains episode
counts, maximum observed depth, longest duration and the last observed depth.

## Return distributions

Daily returns use each evaluated day's `cash_close / cash_open - 1`, including
cash-only days. Missing development dates are not inserted as zero returns.
Trade returns use each closed trade's `cash_after / cash_before - 1`. Daily and
trade samples remain separate and are not added to obtain account return.

Both distributions report sample count, positive/zero/negative counts, minimum,
maximum and fixed **5%, 25%, 50%, 75%, 95%** quantiles. For sorted values and
probability `p`, use position `(n - 1) * p` and linear interpolation between its
floor and ceiling. A single value supplies every quantile. An empty trade
sample has count zero, null statistics and `NO_TRADES`; an empty day sample is
likewise unavailable, though admitted Q7/Q8 executions have evaluated sessions.

Positive/zero/negative return classification uses the recorded absolute
tolerance **1e-12**: values within the closed interval `[-1e-12, 1e-12]` are zero.
The raw values remain unchanged in quantiles, cash attribution and compounding.
These are empirical descriptions; no confidence interval, significance result
or population-tail probability is inferred from a small sample.

## Cash concentration

Each evaluated day's contribution is `cash_close - cash_open`, in the original
normalized initial-cash unit. Positive and negative days form separate groups
using the actual strict cash sign, including tiny nonzero contributions.

For each group, report the total absolute cash contribution and the largest
one and largest three absolute contributions, divided by that group's total.
With fewer than three days, use all available days. Equal contributions retain
their original trading-day order. The three displayed source days preserve
their signed cash contributions. Without positive/negative contributions, the
corresponding shares are null with `NO_POSITIVE_CASH_CONTRIBUTIONS` or
`NO_NEGATIVE_CASH_CONTRIBUTIONS`; count and absolute totals remain zero.

The denominator is gross positive cash or absolute negative cash, not net
portfolio profit. These ratios describe concentration without constructing a
counterfactual account in which profitable or losing days were removed.

## Development fold diagnostics

The saved complete validation windows partition the evaluated DEV days. For
each fold, report its first day's opening cash, last day's closing cash,
compound return `cash_close / cash_open - 1`, continuous-account cash
contribution, evaluated day count, trade count and cash-only day count. Cash
contributions reconcile across days and folds to final minus initial cash.
The account is never restarted, and fold percentage returns are never summed.

For example, +10% then -10% in one fold gives a compound return of -1%, with
cash contributions +0.10 and -0.11 from initial cash 1. Fold summaries report
positive/zero/negative counts and worst, median and best compound returns. The
median uses the same linear quantile rule. Folds are chronological descriptions,
not independent statistical trials or an automatic selection criterion.

TEST has no development-fold report: `fold_diagnostics.status` and its reason
are `NOT_APPLICABLE`. No synthetic TEST folds or DEV/TEST aggregation is created.

## CLI and desktop

```console
market-vault research-intraday-risk-diagnostics --experiment /absolute/development.json --cost-index 1 --candidate-index 2
market-vault research-intraday-risk-diagnostics --experiment /absolute/test.json
```

Success uses `market-vault-intraday-risk-diagnostics-v1` and exit 0. Each side's
local unavailable result still forms a successful descriptive report. Invalid
files, unsupported artifact types or parsed out-of-range indices return a
structured FAILED envelope on stderr and exit 1; noninteger argparse inputs
exit 2. No settings or OpenD initialization is needed. JSON preserves full
numeric precision, explicit units and unavailable reasons.

In **Intraday → Development research** or **Freeze / TEST**, use the result-view
selector for risk summary, drawdown episodes, return distributions, cash
concentration and fold diagnostics. Strategy and benchmark rows are labelled
separately. Ratios display as percentages, cash as initial-cash units, and
durations as calendar minutes. Candidate/file changes bind the views to the
new explicit selection; view and language changes do not rerun research or
upgrade verification. Existing result pagination and immutable Save/Open rules
remain in force.

The public Python functions are
`analyze_intraday_risk_diagnostics(snapshot, *, cost_index=0, candidate_index=0)`
and `summarize_intraday_risk_diagnostics(execution, *, folds=None)` in
`research.intraday_risk_diagnostics`. The latter accepts a V2 numerical result
or an execution from the immutable reader. It raises on inconsistent inputs;
the saved-experiment API wraps supported per-side failures explicitly.

Q5/Q6/Q7/Q8/Q9 files, execution formulas, old report IDs and runtime/package
version **0.9.0** are unchanged. The additional diagnostics have their own
version and full-content identity.
