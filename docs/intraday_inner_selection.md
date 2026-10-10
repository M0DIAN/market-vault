# Intraday bounded inner ML selection (Q25)

Q25 evaluates one fixed model-selection procedure using an existing saved
[DEV comparison or diagnostics experiment](intraday_development_research.md).
It keeps the original outer folds, ordered Features, threshold, selected cost
and Q6 execution policy. The procedure selects a representation and alpha
inside each outer TRAIN history, then refits that recipe on the original outer
TRAIN rows. Its outer result measures this declared procedure. It does not
select a model using the outer result.

This is the second item in the [Q24–Q26 package](intraday_ml_strategy_next.md).
It differs from Q18's selection among saved historical trading outcomes and
from Q23's fixed quadratic forecast comparison. No new dependency is required.

## Fixed method and data boundaries

Start with one explicitly saved `RIDGE` or `QUADRATIC_RIDGE` candidate from an
ordinary V1 or V2 DEV experiment. Supply its source experiment ID, cost index,
candidate index and candidate ID. The source's complete report is reconstructed
before selection, using one verified Q5 load shared with the new computation.
The selected common Feature projection must contain 1–6 ordered Features; a
wider linear source fails before fitting rather than dropping the quadratic
half of the family.

Every original outer training history follows the same rule:

1. Use its last five trading days as inner holdout; use all preceding history
   days as inner TRAIN, requiring at least ten such days.
2. Admit only READY/COMPLETE training pairs already admitted by the original
   outer TRAIN cutoff. For inner TRAIN, also require the actual label end to
   precede the first inner-holdout session open strictly.
3. Predict every READY inner-holdout row. Score only COMPLETE holdout labels
   whose actual end is strictly earlier than the current outer boundary. A
   label that finishes exactly at that boundary is unavailable for selection.
4. Fit the following complete ordered family. Each fit learns its transforms
   only from the same admitted inner TRAIN rows. Use the source threshold for
   every recipe. Select the lowest pooled per-row MSE on the common score
   sample; exact ties choose the first declared member.
5. Refit the chosen fixed recipe on all original admitted outer TRAIN rows.
   Predict every original READY outer-validation key, including incomplete
   target tails. Pool those original outer folds into one continuous Q6
   execution account; score prediction errors only on COMPLETE target pairs.

| Family index | Representation | Alpha |
| --- | --- | --- |
| 0 | Linear Ridge | 0.1 |
| 1 | Linear Ridge | 1 |
| 2 | Linear Ridge | 10 |
| 3 | Quadratic Ridge | 0.1 |
| 4 | Quadratic Ridge | 1 |
| 5 | Quadratic Ridge | 10 |

Quadratic fits reuse Q23/Q24's original TRAIN normalization, linear terms then
degree-two products in declared order, second TRAIN normalization, and existing
Ridge solver/intercept. TRAIN-constant input Features map to zero. The six-input
bound gives at most 27 terms. Both representations have separate fits, even at
the same alpha. MSE weights rows equally, not trading days equally; it is
prediction error in squared target-return units, not a trading return.

The report also runs this same six-member selection once on **all TRAIN plus
VALIDATION days**, including DEV days omitted by the outer evaluation schedule.
Its historical availability cutoff is the first TEST session open. The final
DEV record retains all six inner models, forecasts, losses and the chosen fixed
recipe. It does not refit a TEST model, alter previous outer choices or read
TEST targets into any training or selection sample. The Q5 loader still
verifies the complete immutable artifact, which includes its held-out rows.

Any outer window, or the final DEV window, with insufficient history, no
eligible inner TRAIN rows or no available COMPLETE score labels makes the
**whole study `UNAVAILABLE`**. The report retains every original fold and all
failed-window reasons, but contains no family fits, partial outer refits,
selected account or final recipe. It never drops a fold, substitutes cash or
reports a shortened sample. Invalid sources fail instead of becoming an
unavailable research result.

## Account and evidence

The selected procedure uses the source's chosen Q6 costs, opening/closing
windows, holding limit, strict `score > threshold` decision and long/flat
execution. Capital starts at one once for the entire outer sample; there is no
per-fold reset. The saved source candidate is a descriptive fixed reference
on precisely the same outer keys and dates. Its original benchmark is retained.
The procedure records forecasts, COMPLETE prediction metrics, trades, ledger,
daily equity/returns, risk and fold cash contributions.

Each inner window preserves its full history days, history cutoff/admitted and
purged keys, inner TRAIN/holdout dates, inner boundary, admitted/purged training
keys, all READY holdout keys, available score labels and their actual ends.
Each of six family members preserves its recipe, model, predictions and MSE;
each available outer fold also preserves its selected refit and predictions.

## Save, Open and complete Replay

The study uses its own `StrategyExperiment` envelope:

| Field | Value |
| --- | --- |
| `artifact_schema_version` | `market-vault-intraday-inner-selection-v1` |
| `evaluation_mode` | `INTRADAY_INNER_SELECTION` |
| `plan_schema_version` | `market-vault-intraday-inner-selection-plan-v1` |
| `result_schema_version` | `market-vault-intraday-inner-selection-result-v1` |

The plan binds the original source path/ID, explicit cost/candidate selection
and effective Q5 locator. The report embeds the complete ordinary source
snapshot. Open validates the saved grammar, hashes, source binding, fixed
method, family order/loss selection, models, original sample and account
consistency without reading Q5 or fitting. It is recorded evidence, not a
claim that the current source has been recomputed.

Full Replay verifies current algorithm identities, loads Q5 once, reconstructs
the entire embedded ordinary source and repeats every inner fit, selected
outer refit, final DEV selection and account. The result must match the complete
saved report. The original ordinary file is not required: its recorded path is
provenance. An explicitly supplied replacement source must match the embedded
snapshot exactly. A Q5 relocation override must retain the same verified data
identity and does not change any saved locator or study ID.

Save exclusively creates a new file, or reuses an existing byte-identical file.
Different content at that path fails; it never overwrites input or earlier
results. Old ordinary/selection/TEST artifacts keep their previous grammar and
meaning. Q25 cannot be opened as an ordinary fixed strategy or frozen through
the legacy final-evaluation entry.

```bash
market-vault research-intraday-inner-selection --source-experiment /absolute/dev.json --expected-experiment-id <saved-experiment-id> --cost-index 1 --candidate-index 1 --expected-candidate-id <saved-candidate-id> --experiment /absolute/inner-selection.json
market-vault research-experiment-open --experiment /absolute/inner-selection.json
market-vault research-experiment-replay --experiment /absolute/inner-selection.json
market-vault research-experiment-replay --experiment /absolute/inner-selection.json --intraday-data-file /relocated/intraday.json
```

Use the exact IDs/indices from the saved source. `--intraday-data` supplies an
explicit Q5 override during initial selection. `--name` and `--notes` require
`--experiment`. A valid `UNAVAILABLE` study exits successfully with that
explicit report status; invalid input or immutable-save conflicts exit 1.

## Native workflow and recovery

In **Quant Research → Intraday → Development research**, open or save an
ordinary source. In **Inner ML selection**, choose the saved cost/candidate and
Run. The method, availability, final DEV recipe and completed source details
remain visible. Views expose the original-sample accounts, all family losses,
keys/available labels, all inner models and outer refits, inner/outer READY
forecasts, trades, daily cash and the complete selected ledger. The overview
plots selected procedure, fixed reference and benchmark on their daily dates.

Use Save/Open selection study and Verify full replay for the independent file.
For a moved Q5 artifact, use the optional Q5 path field or Browse; Clear restores
the recorded locator. A failed replay displays `REPLAY_FAILED` and retains the
loaded result. Correct the locator and explicitly replay to obtain
`REPLAY_MATCH`. Changes to captured source selection or relocation while work
is running discard the stale completion and leave the displayed completed
source unchanged. English/Chinese switching preserves the selected view.
At compact window sizes, scroll within the selection panel to reach the lower
account views and table pagination; the table retains its own row scrolling.

## Explicit final DEV Freeze and TEST (Q26)

An AVAILABLE saved study can hand its final DEV recipe to the
[explicit Freeze / TEST workflow](intraday_final_test.md). Freeze reads the
saved study and verifies its expected root experiment ID, then copies the fixed
recipe, method and complete six-member final DEV evidence. It does not read Q5,
fit a model, rerun the family search or change any evaluated outer decision.
An UNAVAILABLE study has no recipe to freeze.

```console
market-vault research-intraday-freeze-inner-selection --source-experiment /absolute/inner-selection.json --expected-experiment-id INNER_SELECTION_EXPERIMENT_ID --experiment /absolute/inner-frozen.json
market-vault research-intraday-test --selection /absolute/inner-frozen.json --experiment /absolute/inner-test.json
market-vault research-experiment-replay --experiment /absolute/inner-test.json
```

Use the Q25 root's `experiment_id` for `INNER_SELECTION_EXPERIMENT_ID`. In the
native application, open/save the study, switch to **Freeze / TEST** and explicitly
freeze its final DEV recipe, then continue with Save/Open, TEST and full
Replay. TEST fits the frozen recipe once on all eligible TRAIN+VALIDATION rows,
purged at the first TEST open, and starts a separate cash-1 Q6 account. The six
inner models remain selection evidence; TEST records its own final model.

The frozen selection and TEST use explicit V2 artifacts while the original Q25
study stays V1 with unchanged content and replay semantics. During Q26 Run or
Replay, `--source-experiment-file` refers to the Q25 study. Its embedded ordinary
source means the original ordinary file is not a third required input. Q26
FullReplay reconstructs the complete ordinary report, whole selection study
and final TEST with one verified Q5 load.

## Limits

The method is a fixed retrospective experiment; lower inner MSE does not
establish higher economic return or correct unknown earlier research history.
There is no Feature/threshold/cost search, arbitrary nested-CV configuration,
new learner, optimizer, portfolio allocation or automatic promotion. Running a
Q25 study stops at DEV evidence. Freeze and held-out TEST are separate explicit
Q26 actions; they are never started automatically by selection or replay.
