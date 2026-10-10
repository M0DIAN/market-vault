# Frozen intraday selection and final TEST (Q8 / Q26)

This workflow completes the path from [development research](intraday_development_research.md)
to an independent TEST account. A user freezes one explicit saved recipe and
its actual costs, then evaluates it on the already declared TEST dates. The
supported sources are:

| Saved source | Explicit choice | Frozen artifact |
| --- | --- | --- |
| Original Q7 V1 comparison or diagnostics | One FeatureRule, CompositeRule or linear Ridge cost/candidate | Original Selection V1 and TEST V1 |
| Q24 ordinary V2 comparison or diagnostics | One fixed `QUADRATIC_RIDGE` cost/candidate | Selection V2 and TEST V2 |
| Q25 available inner-selection study | Its recorded final DEV recipe | Selection V2 and TEST V2, retaining all six final DEV results |

All paths use the same [Q5 data](intraday_research_v1.md) and
[execution V2](intraday_execution_v2.md). The Q25 source is the independently
saved [inner-selection study](intraday_inner_selection.md), which already
contains its ordinary development source.

The selected strategy, Feature order, Ridge alpha/threshold, execution windows,
holding limit, costs, data identity and actual TRAIN/VALIDATION/TEST day groups
are fixed before TEST. Changing the development editor or choosing another
development candidate does not change an existing selection. There is no
automatic winner selection, parameter search on TEST or automatic promotion.

## Distinct actions

| Action | Source and calculation | Result |
| --- | --- | --- |
| Freeze candidate | Read one saved ordinary experiment, verify the expected experiment/candidate IDs and extract one actual cost/candidate result; no Q5 reads or fitting | Immutable fixed selection |
| Freeze final DEV recipe | Read one saved AVAILABLE Q25 study, verify its expected experiment ID and extract its final recipe, method and complete six-member evidence; no Q5 reads, reselection or fitting | Immutable selection with final DEV evidence |
| Run frozen TEST | Verify the saved source and complete frozen configuration; strictly load Q5 once; fit the fixed linear/quadratic Ridge recipe once on TRAIN + VALIDATION, or fit no model for rules | One complete TEST result |
| FullReplay selection | Strictly load Q5 once, recompute the entire ordinary development source and the complete Q25 study when applicable, then compare the frozen extraction | Source/selection report match; no TEST fit or execution |
| FullReplay TEST | Complete the source/selection checks above, then recompute the final fit and complete TEST report using the same verified data | Source, selection and final report matches |

Normal Run checks the source's identity, grammar and configuration binding; it
does not recompute development or select among the six Q25 family members.
FullReplay also checks all applicable development computations. Hashes and
recorded replay labels are not cryptographic execution proofs.

## Freezing the actual selected candidate

For ordinary candidate Freeze, the source must be a saved comparison or
finite-diagnostics experiment. The original V1 path retains all three existing
strategy kinds. An ordinary V2 source admits its fixed quadratic Ridge
candidate; other candidates in that V2 source are not silently converted into
V1 selections.
Freezing requires an explicit zero-based cost index, candidate index within that
cost group, expected source experiment ID and expected candidate ID. These
checks prevent an old UI selection or stale CLI command from silently selecting
another result. A diagnostics selection retains the expanded strategy and its
actual axis values; it does not reconstruct a candidate from current drafts.

The original V1 selection plan has exactly:

- `plan_schema_version`
- `source_experiment`: absolute recorded `path`, `experiment_id`, `research_id`
- `selection`: `cost_index`, `candidate_index`, `candidate_id`

Every selection report stores the data ID, source context ID, Q5 locator, symbol,
interval, common Feature projection, training target horizon, actual three
trading-day groups, actual strategy, axis values, full execution policy and
benchmark definition. Ordinary fixed selections do not copy the development
grid, predictions, returns, fold models or a fitted final model.

### Q26 V2 source and final DEV evidence

The V2 plan retains the same three top-level fields. Its `source_experiment`
records the absolute path, experiment ID, artifact schema version and
`report_id`: the ordinary research ID or Q25 inner-selection ID. Ordinary
selection uses the explicit cost/candidate fields above. A Q25 selection uses
only `final_dev_index`, which must equal the saved final DEV winner.

For Q25, Freeze requires the whole study to be AVAILABLE. It preserves the
fixed six-member family, trailing-five-day inner holdout, minimum ten earlier
TRAIN days, pooled COMPLETE MSE and first-declared exact-tie rule. It copies the
complete `final_dev` window: history, training and validation days and keys,
actual target-end evidence, all six models and predictions/losses, selected
index and fixed recipe. It also records the original ordinary source IDs,
cost/candidate identity and fixed-reference strategy/diagnostic axes.

The final recipe retains the original ordered Features, threshold and
execution policy. Its alpha and representation come from the saved final DEV
choice. The original reference's diagnostic axes remain reference evidence;
the newly selected recipe has no invented ordinary diagnostic coordinates.
No part of Freeze reruns selection, reads Q5 or fits a model. An unavailable
study, stale expected ID, incompatible algorithm or inconsistent stored
evidence fails explicitly.

All copied inner models belong to final DEV selection, before the first TEST
open. TEST subsequently creates its own single fitted model. The V2 report's
`dev_selection` is null for a fixed ordinary quadratic candidate and contains
the complete evidence above for a Q25 source.

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

Linear and quadratic Ridge use every eligible row from nominal TRAIN + VALIDATION, including
development dates that were not evaluated in a complete Q7 walk-forward fold.
Eligibility requires READY Features and a COMPLETE target whose actual target
end is strictly before the first TEST session's official open. Equality is
purged. The target horizon or observation timestamp cannot replace this check.

One final model is fitted with the frozen Feature order and alpha.
Its training keys, purged keys, exact boundary, means, scales, intercept and
coefficients are recorded. For linear Ridge, as in the existing implementation, coefficients
are in the original Feature scale; prediction does not standardize a second
time. No TEST row enters fitting or parameter selection.

Quadratic Ridge reuses the Q23/Q24 model: normalize original Features using
the admitted final TRAIN rows, keep TRAIN-constant Features exactly zero,
construct linear terms followed by all degree-two products in declared order,
and fit the second TRAIN-only normalization and Ridge regression. Both
transforms and the full term order are recorded and reused unchanged for TEST.
The fixed bound is 1–6 original Features, at most 27 terms. A Q25 final recipe
may select either linear or quadratic Ridge; its six-way search is not repeated
during ordinary TEST.

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
Each Run/FullReplay action loads its Q5 source once; private verified contexts are
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
immutable selection root, including Q25 final DEV evidence when applicable,
and its complete final context, one model or
null, every READY prediction, target-error metrics, full execution trades,
transactions, OPEN/CLOSE ledger, daily cash, risk and benchmark. It does not
embed the full ordinary development grid or the Q25 outer-fold study. Offline
Open remains possible when the selection file, saved source experiment or Q5
source is unavailable.

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
For a Q25 source it also reconstructs every outer inner-selection window,
outer refit/account and all six final DEV results. The embedded ordinary source
is reconstructed with the same Q5 admission. The original ordinary file is not
an additional dependency: the required saved source is the Q25 study itself.

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

For a fixed Q24 quadratic candidate, use the same `research-intraday-freeze`
command and its actual cost/candidate indices and IDs. For Q25, explicitly
freeze the saved study's final DEV recipe:

```console
market-vault research-experiment-open --experiment /absolute/inner-selection.json
market-vault research-intraday-freeze-inner-selection --source-experiment /absolute/inner-selection.json --expected-experiment-id INNER_SELECTION_EXPERIMENT_ID --experiment /absolute/inner-frozen.json
market-vault research-experiment-open --experiment /absolute/inner-frozen.json
market-vault research-intraday-test --selection /absolute/inner-frozen.json --experiment /absolute/inner-test.json
market-vault research-experiment-replay --experiment /absolute/inner-frozen.json
market-vault research-experiment-replay --experiment /absolute/inner-test.json
```

`INNER_SELECTION_EXPERIMENT_ID` is the Q25 root's `experiment_id`, not its
report's `inner_selection_id` or the original ordinary experiment ID. This
command takes no new cost/candidate choice; the saved study already fixes them.

Normal TEST and selection/TEST Replay accept two independent loader overrides:
`--source-experiment-file` for the direct saved source (ordinary development or
Q25 inner-selection experiment) and
`--intraday-data-file` for Q5. Both identities must match; neither override
rewrites the frozen locators, plan, result or IDs. For example:

```console
market-vault research-experiment-replay --experiment /absolute/test.json --source-experiment-file /relocated/development.json --intraday-data-file /relocated/intraday.json
market-vault research-experiment-replay --experiment /absolute/inner-test.json --source-experiment-file /relocated/inner-selection.json --intraday-data-file /relocated/intraday.json
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
3. Run frozen TEST. Inspect the single final model, including both transformations
   for quadratic Ridge, all READY predictions,
   trades, complete ledger and daily returns. The overview includes the daily
   benchmark chart; detail views give that space to the table.
   At the supported minimum window size, the panel scrolls vertically so the
   result header, rows and pagination retain usable space in both languages.
4. Save TEST. Opening it restores the embedded selection and full result without
   reading source files. The embedded selection has no invented save path.
5. Use Replay selection to reproduce its full development source, or Replay TEST
   to reproduce both the source and final evaluation.

For Q25, use **Open selection study** in **Freeze / TEST**, or first open/save an
AVAILABLE study in **Inner ML selection** and switch back. Use **Freeze final
DEV recipe**, then
continue with the same Save/Open, TEST and full Replay workflow. The captured final
recipe, original fixed reference and method remain distinct. Inspect all six
final DEV results and their model evidence before running TEST; these records
also remain available in the frozen selection and embedded saved TEST.

Source locations provides two optional file fields. Choosing files only fills
the overrides; a Run/Replay button starts the requested operation. A visible
notice indicates active overrides. Opening/freezing a new selection, or opening
a TEST artifact, clears the old overrides. Blank fields use recorded locations.

Selection and TEST have separate verification states. Freeze shows FROZEN,
fresh TEST shows COMPUTED, offline Open shows RECORDED and successful full
Replay shows REPLAY_MATCH for that action. Replaying selection does not imply a
TEST replay; replaying TEST does not rewrite the separate selection UI state.
A failed latest replay clears that artifact's previous match status.
If source-location inputs change while TEST or replay is running, its stale
result is not applied; the completed selection/TEST stays bound to its captured
source. A stale replay cannot become a successful proof for the changed input.

All actions capture immutable inputs before scheduling the worker. A later
candidate change or form draft cannot alter the frozen request. Failed actions
keep the last successful snapshots and pages. A successfully applied new
selection clears the old TEST display binding; saved files remain intact.

## Additive versions and validation

| Surface | Original Q8 V1 | New-ML Q26 V2 |
| --- | --- | --- |
| Selection root and algorithm | `market-vault-intraday-selection-v1` | `market-vault-intraday-selection-v2` |
| Selection plan | `market-vault-intraday-selection-plan-v1` | `market-vault-intraday-selection-plan-v2` |
| Selection report | `market-vault-intraday-selection-result-v1` | `market-vault-intraday-selection-result-v2` |
| TEST root | `market-vault-intraday-test-v1` | `market-vault-intraday-test-v2` |
| TEST plan | `market-vault-intraday-test-plan-v1` | `market-vault-intraday-test-plan-v2` |
| Final evaluation algorithm | `market-vault-intraday-final-test-v1` | `market-vault-intraday-final-test-v2` |
| Final context | `market-vault-intraday-final-context-v1` | `market-vault-intraday-final-context-v2` |
| Final report | `market-vault-intraday-final-test-result-v1` | `market-vault-intraday-final-test-result-v2` |

Modes stay `INTRADAY_SELECTION` and `INTRADAY_TEST`. The Freeze/TEST CLI envelope
remains `market-vault-intraday-final-cli-result-v1`; common Open/Replay keeps
`market-vault-strategy-experiment-cli-result-v3`. V1 retains its original enum,
model grammar, values and identities. New records do not migrate old files or
promise readability by older readers. Existing saved TEST comparison, risk and
performance views accept the explicit V2 account without changing their metrics
or matched-sample rules.

The Q5/Q6/Q7 data, execution and research semantics remain available, as do the
older Dataset-based experiment and final-evaluation workflows. Runtime/package
version remains 0.9.0. This is research functionality, with no formal release,
deployment, live order handling or later-roadmap implementation.

Legacy Q8 tests use actual verified Canonical/Q5 fixtures and independent final Ridge
oracles. Their 36-session fixture gives 2130 final training rows, 444 READY TEST
predictions and 426 complete TEST targets. It checks final-model independence
from TEST-only source changes, strict actual-end purge, cash days, missing TEST
prices before fitting, concrete second-cost/nonfirst-candidate freezing, offline
Save/Open, malformed re-signed records and full raw source/final replay.
Real QML coverage exercises the complete saved-selection/TEST workflow, both
source-file pickers, pagination, model views, separate proof states and frozen
configuration persistence through draft/candidate/language changes.

Q26 adds focused evidence for both new sources: no-Q5/no-fit extraction,
one final learned fit, strict target-end purge, READY tails, TEST intervention
isolation, complete six-member evidence, malformed/re-signed model rejection
and complete replay. Real CLI/native workflows exercise both paths and source
relocation recovery. Fixed V1 linear and rule references compare complete
selection, TEST and replay bytes under identical inputs and environment.
