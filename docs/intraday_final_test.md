# Frozen intraday selection and final TEST (Q8)

This workflow completes the path from [development research](intraday_development_research.md)
to an independent TEST account. A user selects one saved development candidate,
freezes its actual configuration and costs, and evaluates exactly that candidate
on its already declared TEST dates. FeatureRule, CompositeRule and Ridge use the
same [Q5 data](intraday_research_v1.md) and [execution V2](intraday_execution_v2.md).

The selected strategy, Feature order, Ridge alpha/threshold, execution windows,
holding limit, costs, data identity and actual TRAIN/VALIDATION/TEST day groups
are fixed before TEST. Changing the development editor or choosing another
development candidate does not change an existing selection. There is no
automatic winner selection, parameter search on TEST or automatic promotion.

## Distinct actions

| Action | Source and calculation | Result |
| --- | --- | --- |
| Freeze candidate | Read one saved Q7 experiment, verify the expected experiment/candidate IDs and extract one actual cost/candidate result; no Q5 reads or fitting | Small immutable selection |
| Run frozen TEST | Verify the saved source and complete frozen configuration; strictly load Q5 once; fit Ridge once on TRAIN + VALIDATION, or fit no model for rules | One complete TEST result |
| FullReplay selection | Strictly load Q5 once, recompute the entire source development report and compare the complete frozen extraction | Source/selection report match; no final fit or TEST execution |
| FullReplay TEST | Complete the source/selection checks above, then recompute the final fit and complete TEST report using the same verified data | Source, selection and final report matches |

Normal Run checks the source's identity, grammar and configuration binding; it
does not recompute the development research. FullReplay is the operation that
also checks the development computation. Hashes and recorded replay labels are
not cryptographic execution proofs.

## Freezing the actual selected candidate

The source must be a saved comparison or finite-diagnostics experiment.
Freezing requires an explicit zero-based cost index, candidate index within that
cost group, expected source experiment ID and expected candidate ID. These
checks prevent an old UI selection or stale CLI command from silently selecting
another result. A diagnostics selection retains the expanded strategy and its
actual axis values; it does not reconstruct a candidate from current drafts.

The selection plan has exactly:

- `plan_schema_version`
- `source_experiment`: absolute recorded `path`, `experiment_id`, `research_id`
- `selection`: `cost_index`, `candidate_index`, `candidate_id`

The selection report stores the data ID, source context ID, Q5 locator, symbol,
interval, common Feature projection, training target horizon, actual three
trading-day groups, actual strategy, axis values, full execution policy and
benchmark definition. It does not copy the development grid, predictions,
returns, fold models or a fitted final model.

The benchmark definition freezes first eligible READY entry to EOD under
`FULL_EVALUATED_SESSION_GRID`. It does not freeze the development benchmark's
numeric hold limit; the TEST benchmark derives that limit from the TEST grid.

Selection and TEST both use the existing immutable ten-field
`StrategyExperiment` root: artifact version, experiment ID, data ID, evaluation
mode, algorithm versions, environment, plan, report, name and notes.
The selection keeps the source-wide algorithm versions. The TEST algorithm map
contains only its selected strategy's applicable algorithms; the source-wide
versions remain available in the embedded selection.

## Final training and TEST isolation

Ridge uses every eligible row from nominal TRAIN + VALIDATION, including
development dates that were not evaluated in a complete Q7 walk-forward fold.
Eligibility requires READY Features and a COMPLETE target whose actual target
end is strictly before the first TEST session's official open. Equality is
purged. The target horizon or observation timestamp cannot replace this check.

One final scaler/model is fitted with the frozen Feature order and alpha.
Its training keys, purged keys, exact boundary, means, scales, intercept and
coefficients are recorded. As in the existing Ridge implementation, coefficients
are in the original Feature scale; prediction does not standardize a second
time. No TEST row enters fitting or parameter selection.

The final model predicts every READY TEST observation. Session-end observations
with incomplete targets remain in the prediction and execution streams. MAE,
RMSE and R² use only COMPLETE TEST targets, with separate prediction and error
sample counts. Feature and Composite rules consume READY Features without a
fit and do not invent regression error metrics.

Every TEST price slot, including warmup and unsampled bars, is checked before
fitting or trading. Missing prices fail the run even for an all-Flat strategy.
An entirely empty READY TEST set fails. A single day without a decision remains
in the account as a cash day.

Q5 loading verifies the complete source artifact, including its TEST bytes.
This is input verification, not model training. The isolation guarantee is that
TEST Features/targets never enter the final fit or alter the frozen strategy.
Each public action loads its Q5 source once; private verified contexts are
action-local reuse and are not a public source-admission shortcut.

TEST starts with independent normalized cash 1 and uses all declared TEST
trading days. It does not continue development equity. It carries cash between
TEST days and ends every session flat under Q6. The benchmark uses the same
prices, costs, entry windows and TEST dates and holds its eligible daily trade
until EOD. A normal TEST session after early-close development therefore keeps
the full normal-session benchmark hold limit.

Daily risk includes the first TEST day's open-to-close return. Annualization is
252, risk-free rate 0 and sample standard deviation uses ddof 1. Fewer than two
days and zero volatility retain Q7's explicit unavailable reasons. Drawdown
uses the initial equity and ordered OPEN/CLOSE marks, not intrabar extrema.

## Immutable files, offline Open and full evidence

Selection can be saved and opened independently. A TEST artifact embeds that
small immutable selection root and its complete final context, one model or
null, every READY prediction, target-error metrics, full execution trades,
transactions, OPEN/CLOSE ledger, daily cash, risk and benchmark. It does not
embed the large source development grid. Offline Open remains possible when the
selection file, source development experiment or Q5 source is unavailable.

Open validates exact fields, identifiers, finite typed values, strategy and
execution grammar, model/context bindings, disjoint training/purged/TEST keys,
prediction coverage and complete execution/risk structure. Repeated numeric
configurations compare canonical JSON so booleans cannot impersonate numbers.
Each decision's day, bar slot and aware clock must agree with the recorded
session grid. These shared grammar checks also protect Q7 development records.

Open does not load data, fit or execute. Historical algorithm strings remain
viewable when they conform to the supported artifact grammar. Run/Replay reject
incompatible recorded algorithms before source/data reads or fitting.

FullReplay compares entire canonical raw reports, including unselected
development candidates/costs and values beyond UI rounding or pagination. A
matching final cash balance, model ID or selected candidate alone is insufficient.
Re-signing an altered unselected development prediction still fails source
FullReplay, even when ordinary frozen TEST would produce the same trades.

The common writer exclusively creates the explicitly named file, performs
readback, and permits byte-identical reuse. Different existing content is an
error requiring another path. There is no overwrite, latest pointer, directory
scan, database mutation or source migration.

## CLI

The commands use local files without settings or OpenD initialization. First
open a saved development experiment and choose a concrete candidate. Replace
`SOURCE_EXPERIMENT_ID` and `CANDIDATE_ID` below with its actual saved IDs;
the example indices select cost group 1, candidate 2 within that group.

```console
market-vault research-experiment-open --experiment /absolute/development.json
market-vault research-intraday-freeze --source-experiment /absolute/development.json --expected-experiment-id SOURCE_EXPERIMENT_ID --cost-index 1 --candidate-index 2 --expected-candidate-id CANDIDATE_ID --experiment /absolute/selection.json
market-vault research-experiment-open --experiment /absolute/selection.json
market-vault research-intraday-test --selection /absolute/selection.json --experiment /absolute/test.json --name "Frozen TEST"
market-vault research-experiment-open --experiment /absolute/test.json
market-vault research-experiment-replay --experiment /absolute/selection.json
market-vault research-experiment-replay --experiment /absolute/test.json
```

Freeze requires a save destination. TEST may print a result without saving;
`--name` and `--notes` require `--experiment`. Invalid IDs, indices, files,
unsupported artifact types or malformed values produce a FAILED JSON envelope
on stderr and exit code 1. Standard argparse usage errors retain exit code 2.

Normal TEST and selection/TEST Replay accept two independent loader overrides:
`--source-experiment-file` for the saved development experiment and
`--intraday-data-file` for Q5. Both identities must match; neither override
rewrites the frozen locators, plan, result or IDs. For example:

```console
market-vault research-experiment-replay --experiment /absolute/test.json --source-experiment-file /relocated/development.json --intraday-data-file /relocated/intraday.json
```

Recorded Windows absolute locators remain viewable on other operating systems.
The Canonical references inside Q5 must still be available; relocating the outer
Q5 file does not relocate its sources. The old Dataset experiment directory
override remains exclusive to the existing Dataset experiments. A Q7 development
experiment accepts only the intraday-data-file override; unrelated overrides
are rejected.

## Desktop workflow

Use **Quant Research → Intraday → Development research** to compare/diagnose and
save the completed development experiment. Then use **Freeze / TEST**:

1. Choose the development candidate and freeze it. Freezing is available for a
   saved/opened development experiment even when no Q5 file is open in the Data
   tab. Candidate names show actual commission/slippage costs.
2. Review the frozen parameters and date groups. Save the selection for later
   use; opening it does not train a model or run TEST.
3. Run frozen TEST. Inspect the single final model/scaler, all READY predictions,
   trades, complete ledger and daily returns. The overview includes the daily
   benchmark chart; detail views give that space to the table.
   At the supported minimum window size, the panel scrolls vertically so the
   result header, rows and pagination retain usable space in both languages.
4. Save TEST. Opening it restores the embedded selection and full result without
   reading source files. The embedded selection has no invented save path.
5. Use Replay selection to reproduce its full development source, or Replay TEST
   to reproduce both the source and final evaluation.

Source locations provides two optional file fields. Choosing files only fills
the overrides; a Run/Replay button starts the requested operation. A visible
notice indicates active overrides. Opening/freezing a new selection, or opening
a TEST artifact, clears the old overrides. Blank fields use recorded locations.

Selection and TEST have separate verification states. Freeze shows FROZEN,
fresh TEST shows COMPUTED, offline Open shows RECORDED and successful full
Replay shows REPLAY_MATCH for that action. Replaying selection does not imply a
TEST replay; replaying TEST does not rewrite the separate selection UI state.
A failed latest replay clears that artifact's previous match status.

All actions capture immutable inputs before scheduling the worker. A later
candidate change or form draft cannot alter the frozen request. Failed actions
keep the last successful snapshots and pages. A successfully applied new
selection clears the old TEST display binding; saved files remain intact.

## Additive versions and validation

| Surface | Version / mode |
| --- | --- |
| Selection root and algorithm | `market-vault-intraday-selection-v1` / `INTRADAY_SELECTION` |
| Selection plan | `market-vault-intraday-selection-plan-v1` |
| Selection report | `market-vault-intraday-selection-result-v1` |
| TEST root | `market-vault-intraday-test-v1` / `INTRADAY_TEST` |
| TEST plan | `market-vault-intraday-test-plan-v1` |
| Final evaluation algorithm | `market-vault-intraday-final-test-v1` |
| Final context | `market-vault-intraday-final-context-v1` |
| Final report | `market-vault-intraday-final-test-result-v1` |
| Freeze/TEST CLI envelope | `market-vault-intraday-final-cli-result-v1` |
| Common intraday Open/Replay envelope | Existing `market-vault-strategy-experiment-cli-result-v3` |

The Q5/Q6/Q7 data, execution and research semantics remain available, as do the
older Dataset-based experiment and final-evaluation workflows. Runtime/package
version remains 0.9.0. This is research functionality, with no formal release,
deployment, live order handling or later-roadmap implementation.

Tests use actual verified Canonical/Q5 fixtures and independent final Ridge
oracles. The 36-session fixture gives 2130 final training rows, 444 READY TEST
predictions and 426 complete TEST targets. It checks final-model independence
from TEST-only source changes, strict actual-end purge, cash days, missing TEST
prices before fitting, concrete second-cost/nonfirst-candidate freezing, offline
Save/Open, malformed re-signed records and full raw source/final replay.
Real QML coverage exercises the complete saved-selection/TEST workflow, both
source-file pickers, pagination, model views, separate proof states and frozen
configuration persistence through draft/candidate/language changes.
