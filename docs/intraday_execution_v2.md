# Intraday execution V2 (Q6)

This additive execution contract consumes verified
[`market-vault-intraday-data-v1`](intraday_research_v1.md). Existing Research
Dataset, Label, Backtest V1 and cost semantics remain unchanged. Training target
horizon is not a holding period or an execution return. This is local research
simulation; no broker, deployment, release, or live order path is introduced.

## Input authority and shared opportunity

The research entry point normalizes the entire explicit plan before loading
data. Loading re-executes the Q5 source validation once, including immutable
Canonical/TS2 evidence and every stored field. Desktop execution also compares
the loaded data ID with the previously selected snapshot. Changing a file at the
same location cannot silently change the data used by an existing selection.

The numerical kernel is separate from source I/O. Its explicit sessions, price
grid and decisions are not an alternative Canonical reader. It validates every
declared session's complete planned price flow before any trading, including
warmup, unsampled bars and end-of-day bars. A missing price invalidates the run,
even when a rule requests Flat throughout. It never skips a bad date for one
strategy, advances an order to the next available price, or imputes a price.

Supported intervals are 1m, 5m, 15m and 30m, with the verified US RTH/NONE
calendar. Session boundaries come from calendar evidence, including early
closes and daylight-saving changes. Sixty-minute tail geometry remains outside
this version.

## Decisions, ordering and execution windows

Only READY Feature observations produce a fresh Long/Flat target. FeatureRule
and CompositeRule use the existing finite comparators and ALL/ANY semantics.
True means Long, false means Flat. Composite conditions must all use the
explicit Feature projection, even when an earlier condition decides ALL/ANY.
Targets may be disabled or incomplete without removing READY decisions.
Ridge requires fold training and is provided by the subsequent research task;
the single-rule adapter refuses to fit on the entire data simply to produce a
prediction.

The order at a shared timestamp is the previous bar's close, its new decision,
then the next **planned bar's open**. Thus a decision at 09:55 may fill at the
09:55 open following the bar that just closed. Its observed close is never the
fill price. The ledger retains both phases, in their event order, even if their
UTC timestamps are equal.

The default explicit policy is:

| Field | Default | Meaning |
| --- | ---: | --- |
| `entry_delay_minutes` | 15 | No entry before session open plus this delay; READY warmup is also required |
| `stop_new_minutes` | 30 | No new entry at or after session close minus this interval |
| `flatten_minutes` | 5 | Exit at the last planned open no later than close minus this interval |
| `max_hold_bars` | 12 | Maximum number of underlying price bars held, independent of observation stride |
| `commission_bps` | explicit | Fee on each simulated fill's notional |
| `slippage_bps` | explicit | Adverse adjustment of each raw open |

Windows must fit each declared session and precede the rounded forced-flat
open. No silent adjustment makes an invalid policy fit an early-close day.
Costs are finite numbers in `[0, 10000)` individually. Boolean values are not
numbers. Time and holding parameters are bounded integers.

For a 16:00 close, the forced-flat opens are 15:55 for 1m/5m, 15:45 for 15m,
and 15:30 for 30m. At a 13:00 close they are 12:55, 12:45 and 12:30 respectively.

At each open, priority is **EOD, maximum holding period, fresh Flat, allowed
fresh Long**. An exit consumes the current decision and cannot re-enter at that
same open. It waits for a later fresh decision. With 5m stride 3, entry at slot
5 and maximum hold 12 exits at slot 17; the next possible sampled decision
permits entry at slot 20, not slot 18 or 19. An absent observation does not
create a remembered target. Every session ends flat with no pending overnight
order; account cash continues across evaluated dates.

## Cash and costs

Initial normalized cash is 1. There is at most one full-cash long position;
fractional shares are allowed. With commission rate `c`, slippage rate `s`,
raw buy open `P_buy` and cash `C`:

```text
buy_fill = P_buy * (1 + s)
quantity = C / (buy_fill * (1 + c))
entry_commission = quantity * buy_fill * c
entry_slippage = quantity * (buy_fill - P_buy)
cash_after_buy = 0

sell_fill = P_sell * (1 - s)
exit_commission = quantity * sell_fill * c
exit_slippage = quantity * (P_sell - sell_fill)
cash_after_sell = quantity * sell_fill * (1 - c)
quantity_after_sell = 0
```

V1's combined return deduction is not applied again. Prices, quantities and
account equity must stay finite and positive. Each trade records the before
and after cash, quantity, raw and simulated fills, separate costs, row IDs,
decision reference, held bars and exit reason. Buy and sell transactions have
their own cash state. The ledger marks raw open and close equity as
`cash + quantity * mark_price`; it is not a hypothetical liquidation value.
Observed drawdown uses these ordered marks and the initial equity of 1. It
does not claim to measure intra-bar extrema from high/low prices.

Daily rows record opening cash, closing cash and their ratio minus one,
including the first evaluated day. Annualized daily risk and a daily benchmark
belong to Q7, not this single-strategy output.

## CLI and desktop

```console
market-vault research-intraday-backtest --plan /absolute/path/backtest.json
```

Example (the numeric costs here are illustrative explicit inputs):

```json
{
  "plan_schema_version": "market-vault-intraday-backtest-plan-v2",
  "intraday_data_path": "intraday.json",
  "strategy": {
    "kind": "FEATURE_RULE", "name": "Trend",
    "signal_field": "return_2", "comparator": "GT", "threshold": 0.0
  },
  "execution": {
    "commission_bps": 10.0, "slippage_bps": 5.0,
    "entry_delay_minutes": 15, "stop_new_minutes": 30,
    "flatten_minutes": 5, "max_hold_bars": 12
  }
}
```

Paths are explicit local files, relative to the plan's legal parent or
absolute, following the existing lexical path/symlink checks. Invalid input
produces a versioned JSON FAILED envelope on stderr and exit code 1.
Success prints the complete versioned result, including normalized plan,
data ID, execution ID, decisions, windows, trades, transactions, ledger, daily
settlements and summary metrics. Economic execution does not include training
targets in its inputs or identity: fixed prices and decisions produce the same
execution when only target horizon changes. The parent data/backtest IDs may
change because they bind the distinct upstream artifact.

Desktop: Quant Research → Intraday → Data → open/build verified data →
Execution V2. Select the Feature comparator and threshold, explicitly enter
commission and slippage, and run. Trades, the complete paged bar ledger and
daily settlement use the same adapter as the CLI. A failed run retains the last
successful result and its own data ID. Language switching, pagination and
ordinary form edits preserve drafts. All displayed times are UTC; raw CLI
output retains full numeric precision beyond the desktop display formatting.
