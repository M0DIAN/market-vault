# Intraday trade performance and attribution (Q9)

Q7 development results and Q8 final TEST results contain full V2 trades and a
continuous cash account. The additional descriptive views summarize those
recorded values. They do not fit a model, load Canonical/Q5 data, rerun execution,
change a saved artifact, or upgrade its Open/Replay verification state.

## Definitions

| Metric | Definition |
| --- | --- |
| Win / loss / breakeven | Sign of each trade's `cash_after / cash_before - 1`; absolute returns at most `1e-12` count as breakeven to avoid floating-point dust |
| Win rate | Winning trades / all closed trades, including breakeven trades |
| Mean trade return | Arithmetic mean of individual net returns, not account return |
| Profit factor | Sum of winning trades' actual cash P&L / absolute sum of losing trades' actual cash P&L |
| Payoff ratio | Mean winning net return / absolute mean losing net return |
| Mean hold | Mean actual exit minus entry minutes, and mean underlying-bar count |
| Time exposure | Sum of actual holding minutes / all evaluated session minutes, including cash-only days |
| Cash-only days | Declared evaluated days with no trades |

Profit factor uses actual cash contributions in the continuous account. Payoff
ratio uses per-trade returns. They intentionally answer different questions.
No-trade win rate, average return and average holding are unavailable with
`NO_TRADES`. Profit factor without a losing trade is unavailable with
`NO_LOSING_TRADES`, never infinity. Payoff requires both a win and a loss.
An all-losing set has profit factor zero. An all-flat account has exposure zero.
Tiny breakeven P&L remains in cash attribution even when not counted as a win/loss.

For each trade, using the quantity actually bought:

```text
market_pnl = quantity * (exit_raw_open - entry_raw_open)
net_cash_pnl = cash_after - cash_before
market_pnl - commission_total - slippage_total = net_cash_pnl
```

This price contribution is not a counterfactual zero-cost backtest: entry costs
already affect actual quantity and later account size. Costs are not deducted
again. Every cash figure uses the original normalized cash unit (initial cash
1), so grouped cash P&L can be added and reconciles to final cash minus initial
cash. Individual percentage returns must not be added as portfolio return.

The summary checks trade arithmetic, daily cash and final cash reconciliation
with relative tolerance `1e-10` and absolute tolerance `1e-12`. A discrepancy
rejects the derived analysis; it does not alter the recorded artifact.

Attribution groups are exit reason, entry hour, and trading day. Entry hour is a
half-open 60-minute bucket measured from that day's official open, not UTC hour
or a hard-coded exchange clock. DST and early closes use the saved aware
session times. Daily attribution includes every evaluated cash-only day. Gaps
between development folds are not fabricated as evaluated days. Holding time
is elapsed time, not trade count divided by observation count.

## CLI and desktop

```console
market-vault research-intraday-performance --experiment /absolute/development.json --cost-index 1 --candidate-index 2
market-vault research-intraday-performance --experiment /absolute/test.json
```

Indices are zero-based and refer to the actual saved group/candidate order.
TEST has one frozen result and accepts only zero indices. A frozen selection
without a TEST result has no execution and cannot be analyzed. Invalid
indices, unsupported artifacts, arithmetic mismatches and unsupported execution
versions return a structured FAILED envelope and exit 1; argparse errors exit
2. Successful JSON uses `market-vault-intraday-performance-v1`, identifies the
source experiment, data, candidate and execution, and includes both candidate
and same-window benchmark analytics. `RECORDED_LEDGER_DERIVATION` is descriptive
evidence, not source or replay verification. JSON retains full numeric precision.

In **Intraday → Development research** and **Freeze / TEST**, the result-view
selector provides Trade performance, P&L by exit reason, P&L by entry hour, and
P&L by day. Summary rows show units and explicit unavailable reasons. Detail
tables retain the existing 100-row pagination, bilingual labels and immutable
result binding. The equity chart gives its space to detail views.

Existing Q5–Q8 artifacts and numerical algorithms remain unchanged. Run and
Replay retain their original verification meanings; no trading, release or
deployment is part of this feature.
