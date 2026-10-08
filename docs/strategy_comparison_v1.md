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
By default it only prints the result. The explicit `--output` option below
saves that completed experiment; it does not freeze a final model.

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

## Save, open and replay an experiment

Save one completed comparison, equity report or risk report to an explicit
JSON file. Existing comparison output remains identical with and without
`--output`; saving uses the already-computed result and does not fit twice.

```bash
market-vault research-compare-strategies --plan comparison.json --risk-report \
  --output experiment-001.json --name "Momentum with volume" \
  --notes "Development validation; explicit parameters and costs"

market-vault research-experiment-open --experiment experiment-001.json
market-vault research-experiment-replay --experiment experiment-001.json

# If the same Dataset has moved, choose its new directory explicitly:
market-vault research-experiment-replay --experiment experiment-001.json \
  --dataset-build-dir /absolute/new/dataset-directory
```

`--name` and `--notes` are optional and require `--output`. All three commands
work without application settings or OpenD. Open returns the saved experiment
in a `market-vault-strategy-experiment-cli-result-v1` envelope; Replay returns
the Dataset/comparison identities and expected/actual complete-report digests.
Input, version, identity or result mismatch returns structured failure.

The `market-vault-strategy-experiment-v1` file includes:

- The actual Dataset identity and original absolute directory locator.
- The normalized plan: ordered common Features, return Label, complete ordered
  strategy/condition descriptors, fold windows and per-side cost inputs.
- The exact evaluation mode: `COMPARISON`, `EQUITY` or `RISK`.
- The full raw CLI report, including every strategy, fold and accepted trade;
  equity/risk modes also retain every ledger point, benchmark and daily series.
  The file does not use table paging or display rounding.
- Applicable ML adapter, Experiment, walk-forward, execution, signal/model,
  valuation and risk versions. Package, Python, pandas and PyArrow versions
  are recorded as environment context. A packaged runtime without distribution
  metadata records `unavailable` for that metadata.
- Optional name/notes and a SHA-256 experiment identity over all saved content.

The in-memory snapshot is immutable canonical UTF-8 JSON. Open checks duplicate
and unknown fields, finite numeric values, types, version/identity references,
plan/report bindings and the complete content digest. It validates the record
without reading its Dataset, fitting a model, calling OpenD or running a
comparison; a missing or relocated Dataset therefore does not prevent viewing.
Windows absolute locators also remain viewable on another operating system.

The file is a research record, not a signed execution attestation. A digest
detects changed content relative to its recorded identity; someone can create a
different record with a new digest. Some original strategy IDs also bind scores
that are not present in the report. Only explicit Replay establishes that the
current supported implementation reproduces the recorded computation: it
checks applicable algorithm versions before Dataset I/O, strictly loads the
chosen Dataset, checks its ID before fitting, then recomputes the saved mode
and compares the **entire canonical raw report**. Matching summary values or
existing result IDs alone is insufficient. Environment versions are diagnostic
metadata; this does not claim binary or Git-commit equivalence.

A historical algorithm version can be viewed if its file/report structure is
recognized; Replay refuses differing applicable algorithm versions. An explicit
relocated directory must contain the same verified Dataset ID. Replay never
changes the original locator, experiment file, plan or identity.

### Desktop workflow

Use **Save experiment / 保存实验**, **Open experiment / 打开实验**, **Verify replay /
重放核验**, and **Choose Dataset & replay / 换目录重放** in Strategy Comparison.
The status distinguishes a retained run from a complete matching replay; hover
over it for the experiment file and recorded Dataset identity/directory.

Save and Replay always capture the **last successful run or opened snapshot**.
Editing the visible parameters prepares a new comparison and does not change
that snapshot. Open restores parameters once, together with the report and
its display mode; it clears the active Dataset verification context so an
archived path cannot silently enable a new Run against an unrelated Dataset.
Inspecting the same Dataset ID at an explicitly chosen directory then updates
the verified context while preserving current edits and the original snapshot.
Selecting curves, paging, saving and replaying do not restore parameters again.
Explicitly opening the same file again does restore them. Normal comparison
re-inspection retains the pre-existing result-clearing behavior.

All file parsing and presentation preparation finish in the worker before an
Open replaces visible state. A failed Open, Save, Replay, inspection or new
comparison leaves the previous completed snapshot and results available.

Saving requires an existing parent directory and exclusively creates the
chosen regular file. A byte-identical existing file is reused; different
content, directories and symlinks are refused. The writer flushes and strictly
reads back the file. A failed write does not delete a partial file or replace
an existing one; choose another explicit path when the contents differ.
There is no experiment database, directory scan, `latest` pointer, automatic
overwrite, deletion, Dataset migration or final TEST selection.

The Python surface is `research.strategy_experiment`: `StrategyExperiment`,
`create_strategy_experiment`, `load_strategy_experiment`,
`write_strategy_experiment` and `replay_strategy_experiment`. The shared
`strategy_comparison_io` module preserves the existing plan and complete result
codecs used by both CLI and desktop.

## Finite parameter and cost diagnostics

`research-diagnose-strategy` evaluates one explicitly selected strategy across
zero, one or two finite parameter axes and an explicit list of cost scenarios.
Every candidate uses the existing risk comparison authority: the same verified
Dataset, Feature projection, execution-safe Label, purged expanding folds,
continuous Backtest V1 account, bar-close equity and cost-matched buy-and-hold
benchmark. TEST stays held out of fitting, signals and diagnostic selection.
Dataset verification still reads the complete artifact, including TEST records.

The diagnostic plan embeds a **complete comparison plan**, including its
original strategy list. `strategy_name` selects exactly one name from that
list. Unselected strategies are recorded as context but are not evaluated.
The available axes are:

| Selected strategy | Allowed parameter axes |
| --- | --- |
| `FEATURE_RULE` | `threshold`, preserving its Feature and comparator |
| `RIDGE` | `alpha` and/or `threshold` |
| `COMPOSITE_RULE` | `condition_threshold` with an explicit zero-based `condition_index`; the condition order, Features, comparators and ALL/ANY match remain fixed |

Values and cost scenarios preserve input order. Within each cost scenario the
last parameter axis varies fastest. Every variant gets the deterministic name
`<original name> [1]`, `[2]`, etc.; those exact evaluated names are part of the
existing result identities. Zero axes means one unchanged parameter variant,
which supports a cost-only diagnostic. No baseline cost or original parameter
value is silently added: include it explicitly when it is needed for comparison.

The total number of evaluations is the product of all axis lengths and the
number of cost scenarios, with a maximum of **64**. The plan is fully checked
before Dataset loading in the CLI or before queuing desktop work. Empty lists,
more than two axes, duplicate parameter targets, duplicate normalized values,
duplicate commission/slippage pairs, bools, nonfinite numbers, nonpositive
Ridge alpha and invalid per-side costs are rejected. Distinct pairs such as
`5/2` and `2/5` remain separate scenarios even though the current execution
kernel uses their sum. The two records preserve their different cost metadata.

### Diagnostic CLI example

Save the following as `diagnostics.json`, replacing the Dataset locator with
an existing verified directory. The example requests **2 × 3 × 2 = 12**
evaluations. Thresholds are illustrative explicit inputs.

```json
{
  "plan_schema_version": "market-vault-strategy-diagnostics-plan-v1",
  "comparison_plan": {
    "plan_schema_version": "market-vault-strategy-comparison-plan-v1",
    "dataset_build_dir": "./dataset_id=REPLACE_WITH_VERIFIED_DATASET_ID",
    "feature_fields": ["return_2", "rsi_5"],
    "return_label": "execution_return_1d",
    "minimum_train_periods": 20,
    "validation_periods": 5,
    "step_periods": 5,
    "commission_bps": 0,
    "slippage_bps": 0,
    "strategies": [
      {"kind": "RIDGE", "name": "ridge", "alpha": 1, "threshold": 0}
    ]
  },
  "strategy_name": "ridge",
  "parameter_axes": [
    {"parameter": "alpha", "values": [0.1, 1]},
    {"parameter": "threshold", "values": [-0.001, 0, 0.001]}
  ],
  "cost_scenarios": [
    {"commission_bps": 0, "slippage_bps": 0},
    {"commission_bps": 10, "slippage_bps": 5}
  ]
}
```

```bash
market-vault research-diagnose-strategy --plan diagnostics.json --output diagnostic-experiment.json --name "Ridge neighborhood"
market-vault research-experiment-open --experiment diagnostic-experiment.json
market-vault research-experiment-replay --experiment diagnostic-experiment.json
```

The command runs offline, without application settings or OpenD. Its stdout
is the complete `market-vault-strategy-diagnostics-result-v1` report, grouped
by cost scenario. Each group contains the complete actual child comparison
plan, raw risk report, all trades, all equity points, benchmark and daily risk,
plus an ordered mapping from parameter values to strategy result IDs. The
optional output saves the already-computed whole bundle exactly once.

For a composite axis the descriptor is, for example,
`{"parameter": "condition_threshold", "condition_index": 1, "values": [0.8, 1.2]}`.
The embedded comparison plan must use its existing V2 grammar. A diagnostic
of Ridge or Feature retains child result V1 even if the original, unselected
strategy list contains a composite; a selected composite uses child result V2.

### Interpreting cost and fold contributions

`return_change_from_first_cost` is the candidate's net return minus the net
return of the **same parameter variant in the first explicit cost scenario**.
It is zero for the first scenario. A later scenario can have lower costs and
a positive difference; the report does not presume that the first cost is zero
or that input order increases cost. It is a difference in return, not a relative
percentage change: a raw difference of `0.01` is one percentage point. Existing
returns and benchmark comparisons retain their original definitions.

Each accepted trade belongs to the validation fold containing its signal's
sample key, even if it exits in a later fold. Its `cash_contribution` is
`equity_after - equity_before` on the existing continuously compounded account
with initial equity 1. Each fold contains the sum of those cash contributions;
zero-trade folds remain present. For example, +10% followed by -10% gives cash
contributions +0.10 and -0.11, summing to -0.01. Fold returns are not added and
the account is never restarted at a fold boundary. Overlap-skipped signals do
not create trades or cash contributions.

The contribution sum reconciles to final net return and final equity at the
existing equity layer's accounting tolerance, comparing account wealth
(`1 + contribution sum`) to avoid an artificially strict near-zero-return
comparison. Fold attribution is realized cash by originating signal; it is not
calendar-period mark-to-market PnL, independent per-fold performance or an
attribution of benchmark returns.

All candidates are retained in input order. There is no optimizer, automatic
winner, final TEST evaluation, model promotion or live trading operation.
These reports reveal sensitivity, cost dependence and concentration in a few
folds; repeated inspection still consumes development validation information.

### Diagnostic desktop and complete experiment files

In Strategy Comparison choose **Diagnose / 策略诊断** after inspecting a Dataset.
The dialog takes the current common inputs and strategy list. Select one
strategy, enter comma-separated parameter values, and enter comma-separated
`commission/slippage` pairs such as `0/0,10/5`. The evaluation count is visible
before Run. The initial dialog uses the selected strategy's current threshold
and current common costs; both axes can be disabled for a cost-only run.

**All candidates / 全部候选** shows parameter and cost sensitivity. The candidate
selector switches the displayed cost group, selected equity curve and **Fold
contributions / 各折贡献**. The existing comparison, benchmark/risk and paged
equity ledger remain available for that cost group. Fold rows are also paged
without truncating the recorded result. Selecting the benchmark curve leaves
the explicitly labelled strategy candidate as the fold-attribution subject.

Save, offline Open and verified Replay operate on the **whole diagnostic
experiment**, including every cost group and candidate regardless of selection
or pagination. The explicit new file schema is
`market-vault-strategy-experiment-v2` with `evaluation_mode: "DIAGNOSTICS"`;
Open/Replay CLI responses for admitted diagnostic experiments use
`market-vault-strategy-experiment-cli-result-v2`. Ordinary comparison/equity/risk
experiments retain their V1 file, CLI response and numerical contracts.

The diagnostic file binds the normalized original plan, all actual child plans,
common sample/fold/equity evidence, complete raw reports and derived contribution
records. Both diagnostic identity and experiment identity cover their full
canonical records. The recorded Dataset locator is part of that binding.
Explicit relocated Replay loads the replacement directory but compares against
the original recorded plan and report, without changing their identities.
Only applicable algorithms are replay version gates; environment versions are
metadata. A digest and structural validation are not proof of calculation:
Replay reloads the verified Dataset and compares the **complete raw bundle**,
including values outside currently visible tables and cost groups.

Open restores the base strategy form and the recorded grid on the next dialog
open; it clears Dataset verification until explicit inspection. Candidate
selection, pagination, Save and Replay preserve current drafts, the complete
snapshot and any successful replay status. Explicit Open restores inputs again.
A failed new diagnostic or invalid grid leaves the previous completed bundle
available. The exclusive-create and byte-identical-reuse file policy above
applies unchanged.

The Python entry is `research.strategy_diagnostics.run_strategy_diagnostics`;
`normalize_strategy_diagnostics_plan` and `expand_strategy_diagnostics_plan`
provide strict preflight and ordered expansion. Whole-bundle construction uses
`research.strategy_experiment.create_strategy_diagnostics_experiment` and the
same explicit write/load/replay functions as ordinary experiments.
