# Walk-forward strategy comparison V1

MarketVault can compare multiple explicit Feature rules and fixed-alpha Ridge
models against one verified, single-symbol Research Dataset. The CLI command
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

Load the Dataset, open **策略比较**, select a trend Feature and a mean-reversion
Feature, and enter the thresholds, Ridge alpha, windows and costs. The desktop
compares three named research rules: `Trend` (`Feature > threshold`),
`MeanReversion` (`Feature < threshold`) and `Ridge` (`prediction > threshold`).
Their common Feature projection is the ordered union of the two selections;
choosing the same Feature twice gives Ridge one input column.

The table shows trade count, net/gross return, realized drawdown, win rate,
profit factor, overlap skips and exposure. The summary shows comparison ID,
fold count, common validation sample count and held-out TEST count. For more
rule variants or complete trade/fold details, use the CLI plan.

The Python entry is `market_vault.research.strategy_comparison.compare_strategies`
with explicit `FeatureRuleStrategy` / `RidgeStrategy` tuples. New signal types
should reuse the common verified evidence and execution kernel; they should
not introduce another PnL or cost implementation.
