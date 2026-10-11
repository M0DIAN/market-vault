# Joint intraday economic selection: Q36–Q38

## Baseline and decision

The package begins at verified Q35 main
`9c287eb25da4429398a882a18804709a2884ef8b` in `M0DIAN/market-vault`.
Q1–Q35 already provide immutable Q5 data, actual-label-end purging, historical
DEV folds, linear and quadratic Ridge, six-model inner MSE selection (Q25),
fixed-model economic threshold selection (Q31), explicit Freeze/TEST, and
prediction, objective-sensitivity and return-uncertainty diagnostics (Q33–Q35).

The next useful strategy capability is one **joint economic selection
procedure**. Q25 fixes the source threshold while minimizing prediction MSE.
Q31 fixes the source representation and alpha while comparing four execution
thresholds. Q31 rejects Q25 studies; composing the two would not evaluate the
same 24-member economic rule. Neither existing entry supplies this capability.

| Direction | Decision and reason |
| --- | --- |
| Joint model/alpha/threshold economic selection | Q36: evaluate one fixed, bounded procedure on the original outer DEV folds. |
| Evidence for the new procedure | Q37: admit Q36 to the existing Q33–Q35 diagnostic entry points; no new statistical engine or separate report platform. |
| Explicit independent TEST of the chosen final recipe | Q38: a new Selection/TEST V4 path preserving V1–V3. |
| Fixed Feature subsets | Already supported by ordinary plans and Freeze/TEST; do not implement again. |
| More Feature-omission reports or another learner | Defer; neither connects the existing prediction and economic choices. |
| Automatic history-window or Feature search | Defer; Q30 history sensitivity remains descriptive, and these axes would enlarge the declared family. |
| New labels or execution prices | Defer; Q5 target horizon and Q6 position exits have different declared purposes, not a demonstrated implementation defect. |
| Global PBO/DSR or profitability claims | Excluded; the repository does not have a complete inventory of all research attempts or new empirical market evidence. |

The owner's 2026-10-11 request authorizes implementation, in-scope repairs,
focused tests, commits, push, PRs, independent final-candidate review and squash
merge of these three items. Each starts from the preceding verified main.
Before merging, the final independent review, required natural CI and current
PR head/base/tree identities must agree. Verify natural CI on the exact merged
main SHA before continuing. Release, deployment and live trading are excluded.

## Shared contract

- Retain the source Q5 identity, ordered Features, original outer folds,
  evaluated dates, execution policy, cost group, and fixed-reference indices
  and candidate ID. The source reference may use an alpha or threshold outside
  the joint family; it is never silently replaced by a family member.
- Admit one to six Features before Q5 access because every available window
  must fit the quadratic members. No Feature or data-universe selection.
- Use COMPLETE training labels whose actual end is strictly before the
  corresponding historical boundary. Transforms are fit on those training
  rows only. Economic holdouts execute all READY decisions, including rows
  without COMPLETE scoring labels, on their complete session price grid.
- Preserve the ordinary source, Q25/Q31, old report formats and IDs, and
  Selection/TEST V1–V3. New persisted objects use explicit new versions.
- API, settings-independent CLI and native desktop expose captured source
  identities, complete evidence, unavailable reasons, and failed/stale action
  recovery. Saving remains immutable through the existing save primitive.
- Keep the existing Q6 account, single-instrument long/flat policy, cash-only
  days, raw-price/corporate-action limitations and package version 0.9.0.
- No new dependency, learner, generic optimizer, source overwrite, automatic
  winner promotion, TEST ranking, market-data collection or live execution.

## Q36 — fixed 24-member joint economic selection

### Goal and method

From one explicitly selected ordinary saved linear/quadratic DEV candidate,
run the same bounded chronological choice in each original outer fold and in
a separately labelled final-DEV window. This is a new saved study, not an
ordinary fixed strategy and not a reinterpretation of Q25 or Q31.

The family order is representation `RIDGE`, `QUADRATIC_RIDGE`, then alpha
`0.1`, `1.0`, `10.0`, then strict score thresholds `0`, `0.0005`, `0.001`,
`0.002` (0, 5, 10 and 20 bp). Each history uses its last five days as inner
holdout and requires at least ten earlier inner-training days. Fit the six
model configurations once each and run four independent Q6 threshold accounts
per model. Choose maximum inner net compounded account return; exact ties use
the first declared member. Zero-trade cash accounts are valid, with zero return.

Refit only the winning recipe on the original purged outer-training rows and
predict the original outer validation observations. Execute one complete outer
account from those historical choices. Final DEV records the selected recipe
and full inner evidence; it does not fit or evaluate TEST. Preserve all six
inner models and predictions and all 24 complete accounts without copying the
same fitted model four times. Any required history or inner execution-input
unavailability makes the whole study UNAVAILABLE; no partial reduced family.

The implementation reuses Q25's model fitting, Q31's temporal economic-window
and account primitives, ordinary complete-source reconstruction, and existing
immutable `StrategyExperiment` saving. The new schema is
`market-vault-intraday-joint-selection-v1`, mode `INTRADAY_JOINT_SELECTION`.
Public functions are `run_intraday_joint_selection` and
`replay_intraday_joint_selection`; CLI commands are
`research-intraday-joint-selection` and
`research-intraday-joint-selection-replay`.

### Acceptance and exclusions

Independently check the 24-member ordering, six-fit sharing, exact tie rule,
manual net-return winner, complete outer account, source indices and reference,
training/holdout/outer/TEST causality, purging and quadratic transform boundaries.
Exercise real saved-source run/save/open/replay, Q5 relocation, source-evidence
rejection, short/gapped inner-window unavailability, CLI and native recovery.
No altered assertion or weakened prior validation may supply passing evidence.

Exclude alpha/threshold customization, family pruning, Feature/history search,
24 outer refits per fold, 24 TEST evaluations, transaction-cost recalibration,
changing the objective after inspecting results, and automatic Freeze.

## Q37 — existing diagnostics for the joint procedure

### Goal and method

Extend the current ML diagnostics API/CLI/page to recognize Q36 explicitly.
Reuse Q33's complete-source reconstruction and common COMPLETE outer target
pairs for selected, original fixed reference, zero and true outer-training
mean forecasts. Preserve the fixed five score intervals and all READY rows.

Reuse Q34's recorded-only objective sensitivity: omit each original holdout day
once from each of the 24 recorded account-return products, with all six fitted
models, raw scores and account paths held fixed. Recompute the economic winner
using the entire fixed family and original order. Keep outer-inner and final
DEV windows distinct, full recipes, runner-up margins and unavailability.

Reuse Q35's source-bound original procedure/reference/benchmark accounts and
two synchronous paired daily-return increments. Retain its shared sampling
stream, 5,000 replications, seed 0, 95% intervals, cube-root expected block
length, 100-day and ten-expected-block minima, and gap/numerical gates.

The source is identified explicitly as `JOINT_ECONOMIC_SELECTION`. A joint
study has one selected outer account, so diagnostic cost/candidate indices
must both be zero; the report separately retains the original ordinary
source's actual cost index, candidate index and candidate ID. Existing derived
report versions and numerical definitions remain unchanged, and this new
source does not alter reports or IDs produced for ordinary, Q25 or Q31 inputs.

| Existing CLI entry | Q36 behavior |
| --- | --- |
| `research-intraday-ml-prediction-quality --experiment joint.json` | Reconstruct the complete ordinary source and joint procedure with one Q5 admission, then describe actual outer refit forecasts. Optional `--intraday-data` relocates the same bound Q5. |
| `research-intraday-inner-objective-sensitivity --experiment joint.json` | Derive all 24 full-recipe objectives and five day-omission choices per saved inner window; no Q5 or model/execution recomputation. |
| `research-intraday-procedure-return-uncertainty --experiment joint.json` | Derive the existing five synchronized daily series from the saved outer accounts, using the existing sampling controls and defaults. |

The native **Quant Research → Intraday → ML diagnostics** page uses these
same three methods. Joint fixed-evidence views identify all six shared models
by model index and full recipe, and each of the 24 daily-account members by
its complete recipe. Shared prediction targets retain their recorded source
threshold meaning; actual member decisions remain in that member's account.
These diagnostics do not create a new immutable experiment eligible for Freeze.

### Acceptance and exclusions

Prove the new source's metrics use each actual outer refit; detect recipes
with the correct threshold but wrong representation/alpha; independently
recalculate a changed 24-member omission winner and synchronized daily-return
increments. Q34/Q35 paths require only saved bytes, with Q5/fit/Q6 prohibited.
Legacy ordinary/Q25/Q31 results and IDs remain unchanged. Validate actual CLI,
native method switches, complete evidence, captured inputs and failure recovery.

The three analyses are conditional descriptions of the recorded procedure.
They are not refit jackknife inference, probabilities of choosing a member,
corrections for unknown research searches, future-profit probabilities,
simultaneous family bounds or automatic selection rules. No new cost/delay grid
or separate statistics engine is introduced.

## Q38 — explicit joint-selection Freeze and TEST V4

### Goal and method

Add an explicit Freeze action for an AVAILABLE Q36 study. Bind its saved source,
joint method, all final-DEV model/account evidence, selected full recipe,
original fixed reference, Features, execution and cost policy. Introduce
Selection/TEST V4 with independent validation; do not upgrade old saved bytes.

Run one independent TEST using the frozen recipe, fit once on all eligible DEV
rows before the first TEST session open, and preserve existing TEST-only price,
decision, account and benchmark boundaries. Source admission checks the bound
saved study and configuration. Explicit full replay additionally reconstructs
the complete ordinary source, joint study and TEST; it must not select based
on TEST. Explicit relocation must match bound source/data identities. Persist, open and replay through existing
immutable operations and the current final-test page.

### Acceptance and exclusions

Verify final-DEV winner binding, one frozen recipe and one final fit, true DEV
purging, unchanged decisions under later TEST-label changes, source/data
relocation, exact complete replay, source preservation, stale action rejection,
failure/retry, and actual native/CLI Freeze-to-TEST use. Necessary V1–V3
compatibility tests retain their original assertions. An unavailable study
cannot freeze; a mismatched method/model/alpha/threshold/account cannot pass
offline admission or replay.

Exclude refitting selection during TEST, best-TEST ranking, repeated TEST search,
ensemble weights, live deployment and claims of profitable market performance.

## Validation cost and references

Use compact real-source fixtures shared within each focused test file, numerical
oracles that distinguish the actual risks, and independent read-only review of
the final candidate. Qt validation runs locally because the ordinary CI dev
installation omits PySide6. Preserve natural FULL CI, complete test ownership,
3.14 compatibility and the checked-in post-merge tree-equivalence proof.

The last Q35 FULL run had one 702-second strategy partition, with broader
runner slowdown relative to the same tests on its predecessor. Observe this
package's actual durations before changing CI controls. A justified rebalance
must preserve all collected tests, ownership and acceptance conditions; do not
drop tests or manufacture evidence with a forced tier.

Q36's natural FULL `38107747598/1` measured strategy at 737 seconds and
intraday_research at 540 seconds. The logged Q33–Q35 diagnostic hotspots
suggest about 153 seconds of potential savings from moving those three files
to an existing lighter partition, subject to runner and shared-fixture effects.
That control-plane change would also require an additional normal FULL on
main; the estimate needs roughly four to five future FULL runs to offset it.
The remaining two PR runs in this package do not justify that added wait, so
Q36–Q38 retain the current partitions and verified post-merge reuse contract.

Method references:

- [scikit-learn: nested and non-nested cross-validation](https://scikit-learn.org/stable/auto_examples/model_selection/plot_nested_cross_validation_iris.html)
  explains why selection and its held-out evaluation are separate operations.
  MarketVault uses its existing chronological and label-availability contract,
  not the example's shuffled folds.
- [scikit-learn: common pitfalls](https://scikit-learn.org/stable/common_pitfalls.html)
  documents training-only preprocessing and avoidance of test-data selection.
- Existing numerical, execution and uncertainty meanings remain those in
  [Q24–Q26](intraday_ml_strategy_next.md),
  [Q30–Q32](intraday_training_policy_next.md) and
  [Q33–Q35](intraday_ml_evidence_next.md).
