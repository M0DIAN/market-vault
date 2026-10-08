# Walk-forward strategy comparison

MarketVault can compare explicit Feature rules, flat composite rules and
fixed-alpha Ridge models against one verified, single-symbol Research Dataset. The CLI command
is `research-compare-strategies`; the desktop entry is **Quant Research →
Strategy Comparison / 策略比较** after loading a Dataset.

## Evaluation contract

- One explicit Feature projection and execution-safe return Label define the
  Experiment. Rules may only select Features in that common projection.
- Expanding walk-forward folds use the original **TRAIN + VALIDATION** pool.
  Training rows whose selected Label ends at or after the validation boundary
  are purged. Periods count distinct sample feature-close timestamps, not bars.
- Every strategy receives the exact ordered union of fold validation samples.
  This can include original TRAIN rows and can have gaps when the step exceeds
  the validation window. Missing execution evidence fails the whole comparison.
- Each Ridge model fits and standardizes only on its fold's retained training
  rows. Its alpha and prediction threshold are supplied explicitly. There is
  no parameter search or automatic winner selection in this command.
- All signals run through Backtest Engine V1: single-symbol, full-notional
  Long/Flat, proven future entry open and Label exit, no overlapping positions.
  Positions and compounded equity continue across validation folds.
- The per-side rate is `(commission_bps + slippage_bps) / 10000`. A trade's net
  return is `(1 + gross_return) * (1 - per_side_rate)^2 - 1`.
- TEST is excluded from fitting and comparison calculations. Artifact
  verification and the Experiment adapter still read the complete Dataset;
  the output records the held-out TEST count.

These are **development validation results**, useful for comparing research
choices. Repeatedly inspecting them is model selection, not independent final
performance evidence. A zero-trade strategy is a valid result, with zero
realized return and the existing Backtest V1 undefined-metric conventions.

The drawdown is `realized_max_drawdown`, measured at trade exits. The engine
does not mark open positions to market, simulate a cash/share ledger, partial
fills, borrowing, margin or multi-asset allocation. Existing `research-backtest`
and Ridge threshold/final TEST commands retain their original contracts and
identities. In particular, legacy Ridge trading evaluates overlap at signal
time; this comparison uses Backtest V1's proven entry time for **all** strategies.
Do not combine those legacy metrics into the new comparison table.

## CLI

Save this as `comparison.json`, replacing `dataset_build_dir` with the existing
verified build directory. Relative paths resolve from the plan's directory.
Feature and Label names must exist in that Dataset; these examples are
available from the workspace's `LIGHT_TECHNICAL` preset and one-day horizon.
The thresholds are examples, not recommended or optimized trading parameters.

```json
{
  "plan_schema_version": "market-vault-strategy-comparison-plan-v1",
  "dataset_build_dir": "./dataset_id=REPLACE_WITH_VERIFIED_DATASET_ID",
  "feature_fields": ["return_2", "rsi_5"],
  "return_label": "execution_return_1d",
  "minimum_train_periods": 20,
  "validation_periods": 5,
  "step_periods": 5,
  "commission_bps": 1.5,
  "slippage_bps": 2.5,
  "strategies": [
    {"kind": "FEATURE_RULE", "name": "trend", "signal_field": "return_2", "comparator": "GT", "threshold": 0},
    {"kind": "FEATURE_RULE", "name": "reversion", "signal_field": "rsi_5", "comparator": "LT", "threshold": 30},
    {"kind": "RIDGE", "name": "ridge", "alpha": 1, "threshold": 0}
  ]
}
```

```bash
market-vault research-compare-strategies --plan comparison.json
```

The command runs offline without loading application settings or initializing
OpenD. It prints structured JSON with comparison and per-strategy identities,
all supplied strategies in input order, the shared sample keys, fold boundaries
and purge counts, common costs, realized metrics and complete trade records.
It does not write an evaluation artifact or freeze a final model.

Plans reject unknown or duplicate fields, unknown strategy kinds and duplicate
strategy names. Rule comparators are `GT`, `GE`, `LT`, `LE`; Ridge uses predicted
return `GT threshold`. Alpha must be positive, all numeric values finite, and
each period count a positive integer. Step must be at least the validation
window; the development pool must support at least one full fold after purge.
Combined per-side costs must be nonnegative and below 10000 bps.

## Desktop

Load the Dataset and open **策略比较**. Set an explicit comma-separated common
Feature projection, execution-safe return Label, windows and costs. The initial
list contains `Trend`, `MeanReversion` and `Ridge`, using `return_2` where that
Feature is available. Add, remove, rename or edit strategies in the list; at
least one strategy remains. The selected strategy's editor supports a single
Feature rule, Ridge alpha/threshold, or two-or-more ALL/ANY conditions. Rule
thresholds use the Dataset's raw units. Switching type starts that type's
default parameters, which remain visible for editing before the next run.

The common Feature projection is explicit and independent of the list. Every
rule condition must reference it; Ridge uses the same projection, including
when it is the only strategy. Editing a condition does not silently add an
input column or select every available Feature. Blank numbers, duplicate
strategy names and invalid/out-of-projection Features are rejected.

The table shows trade count, net/gross return, realized drawdown, win rate,
profit factor, overlap skips and exposure. The summary shows comparison ID,
fold count, common validation sample count and held-out TEST count. A new
successful comparison collapses the editor to leave room for results; use
**Expand parameters / 展开参数** to continue editing. Revalidating the same
Dataset preserves the configured list and clears results; selecting another
Dataset restores the default strategy list. Complete trade/fold details remain
available in the CLI JSON.

The Python entry is `market_vault.research.strategy_comparison.compare_strategies`
with explicit `FeatureRuleStrategy` / `RidgeStrategy` / `CompositeRuleStrategy`
tuples. New signal types
should reuse the common verified evidence and execution kernel; they should
not introduce another PnL or cost implementation.

## Composite rules and versioned configuration

`market-vault-strategy-comparison-plan-v1` keeps its original grammar, accepting
only `FEATURE_RULE` and `RIDGE`. For composite conditions use
`market-vault-strategy-comparison-plan-v2`, with the same top-level plan fields.
For example, set `feature_fields` to `["return_2", "volume_ratio_5"]` and include:

```json
{
  "kind": "COMPOSITE_RULE",
  "name": "MomentumWithVolume",
  "match": "ALL",
  "conditions": [
    {"signal_field": "return_2", "comparator": "GT", "threshold": 0},
    {"signal_field": "volume_ratio_5", "comparator": "GE", "threshold": 1.2}
  ]
}
```

`ALL` requires every condition; `ANY` requires at least one. Conditions are a
flat ordered list of at least two existing `GT`/`GE`/`LT`/`LE` rules. There is no
nested expression language, arbitrary import or executable expression. All
conditions are checked against the admitted common Feature projection before
short-circuit evaluation. Contradictory conditions are valid and may produce
zero trades. They do not change which samples are common to the comparison.

The signal adapter in `research/strategy_comparison.py` supplies numeric scores
and a rule to the existing execution kernel. Legacy Feature rules retain their
original numeric scores; Ridge retains its fold fitting and predictions.
Composite rules use an internal 0/1 score, without adding a synthetic Dataset
Feature. Their implementation version and complete ordered conditions enter
their result identity. Reordering conditions can preserve trades while changing
the configuration identity.

A comparison containing a composite rule uses `market-vault-strategy-comparison-v2`
and the corresponding `market-vault-strategy-comparison-cli-result-v2`,
`market-vault-strategy-equity-cli-result-v2` or
`market-vault-strategy-risk-cli-result-v2` envelope. The account and risk formulas
remain the Q1 versions below. A comparison containing only original strategy
types retains its complete V1 result payload and identities, even when loaded
from plan-v2. Adding a composite without changing the shared projection,
samples, windows or costs leaves the existing per-strategy result IDs unchanged.

Plan-input encoding is `research.strategy_config.strategy_plan_fields`; result
descriptors have additional implementation fields and are not plan inputs.
`parse_strategy_specs` is shared by the CLI and desktop. Failures before a valid
strategy list is admitted use the original selected error envelope; after a
composite list is admitted, execution failures use its V2 envelope.

## Optional bar-close equity and cash/share ledger V1

Use the same plan with the optional flag:

```bash
market-vault research-compare-strategies --plan comparison.json --equity-curve
```

The Python entry is
`market_vault.research.strategy_equity.compare_strategies_with_equity`.
It reruns the explicit V1 comparison and adds a versioned valuation report;
it does not accept an arbitrary caller-created report as trading authority.
The existing V1 comparison, strategy IDs, accepted trades, costs and metrics
remain unchanged. Without the flag, the original CLI JSON is unchanged. With
the flag, `result_schema_version` is
`market-vault-strategy-equity-cli-result-v1`; the additional `equity` object
binds the comparison, verified price evidence, valuation window and each curve.
The JSON includes every ledger point with UTC time, event, cash, fractional
shares, mark price, position value, total equity, drawdown and event cost.

In the desktop **Strategy Comparison** tab, check **Include bar-close valuation /
加入 K 线收盘估值** before running. The comparison table gains a bar-close maximum
drawdown column. Open **Equity & ledger / 净值与账本** to select a strategy, view
its equity path and page through its cash/share ledger. This view collapses
the parameter form to make room; **Show parameters / 展开参数** restores it.
The chart's time axis
uses elapsed UTC time and steps between observed account states. Complete
ledger values are available through the CLI, without display rounding.

### Accounting and clocks

Initial account equity is normalized to **1.0**. Every accepted trade uses
fractional shares and the same per-side cost rate `c` as Backtest V1:

- Entry: `fee = cash * c`; `quantity = (cash - fee) / entry_open`; cash becomes zero.
- Holding: `equity = quantity * current_close`.
- Exit: `fee = quantity * exit_close * c`; cash becomes the remaining proceeds,
  and quantity becomes zero.

The entry open and exit close are resolved from the exact Canonical row versions
selected by the execution-safe Label. Their price return and the ledger's exit
cash must reconcile with V1. This represents V1's proportional transaction-cost
model; it adds no broker fee schedule, actual fill slippage or order sizing.
The sum of paid event costs is reported separately; with compounding, it is not
the difference between separately simulated gross and net final equities.

The shared valuation window runs from the earliest candidate entry to the latest
candidate exit in the common validation stream. All strategies use the same
verified RTH session grid. An account continues across folds, validation gaps
and overnight holdings. At an equal timestamp the order is **close mark, exit
and its cost, then next entry and its cost**. The entry event uses the bar's open,
never its not-yet-available close.

The grid comes from the Dataset's verified complete trading-day schedule,
including closed dates and qualified early closes. Price evidence comes only
from that Dataset's recorded Canonical builds and respects `dataset_as_of`.
A missing price during a holding fails valuation, including missing whole
sessions or session edges. A cash-only point requires no price: an absent quote
is reported as null, with no forward-filled or interpolated quote.

Supported RTH intervals retain their recorded `market_available_at` clocks.
For the truncated final 60m bar, this is the existing conservative nominal end:
16:30 on a normal session or 13:30 on a qualified early-close session. Valuation
does not move that close earlier to the physical session boundary. See the
[timestamp contract](contracts/market_bar_timestamp_semantics.md).

### Interpreting drawdown

`bar_close_max_drawdown` includes recorded close marks and entry/exit cost events.
For example, with no costs, a trade entering at 100, marked down to 60, then
exiting at 110 has a 10% realized gain and zero realized maximum drawdown, but a
**40% bar-close maximum drawdown**. Both metrics remain visible.

OHLC bars do not establish the order of intrabar highs and lows. This curve
therefore does not claim tick-level or worst intrabar drawdown, liquidity,
partial fills, borrowing, margin, or multi-asset accounting. Valuation adds no
signals or model fitting and does not evaluate permanent TEST candidates.

## Optional benchmark and daily risk report V1

Run the same plan with `--risk-report` (which also includes the equity report):

```bash
market-vault research-compare-strategies --plan comparison.json --risk-report
```

The Python entry is
`market_vault.research.strategy_risk.compare_strategies_with_risk`. It recomputes
the explicit comparison and obtains one strictly admitted valuation context;
it accepts no caller-created report as execution authority. Existing V1 and
equity payloads and identities are retained inside the optional
`market-vault-strategy-risk-cli-result-v1` envelope.

The benchmark is **same-symbol buy-and-hold price return**: buy once at the
common window's first entry open, sell once at its final recorded close, and
pay the same per-side costs as the strategies. Its bars and row versions come
from the same verified Dataset, schedule and as-of price evidence. It shares
the cash/share arithmetic with strategy valuation but creates no strategy
signal or Label-backed trade. Its ledger and curve ID are separate from the
accepted strategy trades. Required holding prices must exist throughout the
window, even when a compared strategy is in cash. The benchmark retains the
Dataset's price convention; it does not include dividend reinvestment.

Daily observations use each trading session's **complete recorded closing
clock**, derived from the full schedule before clipping to the comparison
window. The conservative 60m tails stay at 16:30 or 13:30. At an equal timestamp
the last ledger event wins, so closing execution costs are included. Weekends
and closed dates add no artificial zero-return days. Missing declared session
equity is an error, not permission to bridge multiple days.

Only consecutive complete close endpoints form daily returns. The first close
can anchor the next full interval even when the valuation window starts during
that first day. INITIAL-to-first-close and last-close-to-partial-end changes
remain in total return and drawdown, but are excluded from daily statistics.
The report includes all daily observations, returns, actual timestamps and counts.

Statistics use arithmetic daily returns, sample standard deviation (`n - 1`),
an annualization factor of **252**, and an explicitly recorded risk-free rate
of **0**. Annualized volatility is `daily_std * sqrt(252)`; Sharpe is
`mean_daily_return / daily_std * sqrt(252)`. Fewer than two daily returns gives
null volatility/Sharpe with `INSUFFICIENT_DAILY_RETURNS`. Numerically zero daily
standard deviation (at most `1e-15`) gives zero volatility and null Sharpe with
`ZERO_VOLATILITY`. This fixed tolerance handles binary floating-point noise.
`return_difference` is strategy total return minus benchmark total return,
in return units, not a fitted alpha or a ratio of final wealth.

In the desktop, enable **Include benchmark & risk / 加入基准与风险**. The
**Benchmark & risk / 基准与风险** table shows all strategies and the benchmark.
The equity chart overlays the selected curve in gold and the benchmark in grey
on shared axes; selecting **Buy & Hold** opens its ledger. Switching risk off
removes its table and overlay while retaining the existing equity-only mode.
Desktop numbers are display-formatted; full-precision values remain in CLI JSON.
