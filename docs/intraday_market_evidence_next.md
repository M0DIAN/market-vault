# Actual research-data evidence and sample usage: Q46–Q48

## Verified baseline and task package

This package starts at Q45 main
`1e9e929eb8155c7cb26b54de3a29dd598c2a7264`, tree
`cfbe79761607785d7966894427aa21b2977fdbe9`, in `M0DIAN/market-vault`.
Q45 PR #315 completed natural FULL CI `38141083302/1`; exact-main natural
push `38142186862/1` completed through the existing verified tree-equivalence
reuse contract. Reuse is not a second execution of FULL.

The owner's 2026-10-12 Japan-time request authorizes the next three mainline
tasks, necessary repairs, tests, commits, push, PRs, independent final-candidate
review and conditional squash merge. Each task starts from the preceding
verified main. Merge requires independent review of the current committed
candidate, successful required natural PR CI, and matching head/base identities.
The resulting exact-main natural push must reach successful terminal CI before
the next task starts. Follow the supplied Development Workflow v2 and Personal
Local Tool Workflow v1 together with checked-in governance. Version stays 0.9.0.

### Q46 completed mainline gate

Q46 was independently reviewed at final head
`a3b8892a51030f3f06a1a43a800ea64552f1789e` and merged through
[PR #316](https://github.com/M0DIAN/market-vault/pull/316). Natural PR FULL
[38153626605/1](https://github.com/M0DIAN/market-vault/actions/runs/38153626605)
and resulting main FULL
[38154754691/1](https://github.com/M0DIAN/market-vault/actions/runs/38154754691)
both completed with all sixteen required jobs successful. The squash main is
`ab8f7a3ca7aff7894d21f269aa89dc30fa1002dd`; its tree and the reviewed candidate's
tree are both `86ea9cfdf6c6d5aeeb7bfd72a20ecc2bfebda020`. The main run explicitly
used FULL with `POST_MERGE_REUSE=false`, reason `control_plane_changed`.
Q47 implementation starts from this verified main, after that terminal result.

### Q47 completed mainline gate

Q47 was independently reviewed at final head
`fa2a415642304949f5313e1c9dd8f4e323124687` and merged through
[PR #317](https://github.com/M0DIAN/market-vault/pull/317). Natural PR FULL
[38156605646/1](https://github.com/M0DIAN/market-vault/actions/runs/38156605646)
completed with all sixteen required jobs successful. The squash main is
`bc01e4cb52539991603eff16816f8d59e45876ca`; its tree and the reviewed candidate's
tree are both `dd5f5f5477a70d97ac26aea70a34c1666ccb276f`.

Exact-main natural push
[38157680370/1](https://github.com/M0DIAN/market-vault/actions/runs/38157680370)
completed successfully with `POST_MERGE_REUSE=true`, reason
`verified_full_pr_tree_equivalence`, explicitly bound to PR #317, its final
head and PR FULL run `38156605646`. Five required non-partition jobs succeeded;
the unexpanded partition job was skipped as planned. This is verified reuse,
not a second execution of FULL. Q48 implementation starts from this exact main
only after that terminal result and a fresh current-main identity check.

## Why this direction

Q1–Q41 already provide verified Q5 inputs, actual-label-end purging, linear and
quadratic Ridge, nested six-model / four-threshold / joint 24-member selection,
Freeze/TEST V1–V4, prediction diagnostics, conditional return/family evidence,
and fixed-decision cost/delay stress. Q42–Q45 add numeric admission, explicit
SDK session semantics, same-basis two-source comparisons and fixed acceptance
cases with observed snapshot changes. Those capabilities are not repeated.

The remaining gap is between the two groups: Q44/Q45 do not identify which
prices actually admitted to a Q5 `data_id` were compared, or which recorded
training and evaluation samples depend on disputed or unassessed prices.
Q29's saved intraday return assessment covers holding/benchmark windows and
explicitly excludes training Features, training targets and unexecuted signals.

| Direction | Decision and reason |
|---|---|
| Bind external bar evidence to the actual verified Q5 data | Q46; a Canonical filename or declared row ID does not prove the research used that row version. |
| Identify Feature and target dependencies on those bars | Q47; distinguish conservative Feature exposure from target-price endpoints and completeness support. |
| Explain evidence coverage of actual fitted/scored sample sets | Q48; include inner/outer/final DEV usage, not just days with trades, and make the result usable from the research UI. |
| Promote fixed recent training windows through all selection/TEST versions | Deferred. Q30 already measures 10/20-day history sensitivity; no empirical finding currently establishes an improvement warranting that larger lifecycle change. |
| Add a learner, Features or more search axes | Deferred. Additional model search does not close the identified input-evidence gap. |
| Global TEST-use enforcement or live profitability qualification | Excluded; neither complete historical exposure nor independent real-market inputs are available. |

No direction is justified by an assertion that recent windows or more complex
models necessarily perform better. Time-ordered evaluation and training-only
preprocessing remain required; the existing trading-day/purge implementation
stays authoritative, without adding scikit-learn as a dependency.

## Shared scope and defaults

- US equity/ETF, NONE unadjusted prices, RTH, existing 1m/5m/15m/30m intervals.
- Explicit immutable Q5 file, explicit reference snapshots and economic/source
  declarations. No implicit latest file, download, subscription or data repair.
- Existing Q44 zero price/volume tolerances by default; supplied tolerances
  remain visible and bound to report identity, never fitted to obtain agreement.
- Read Q5 through its real verification path. Construct the local comparison
  side from its admitted prices after reconciliation/as-of selection, not from
  arbitrary external provenance fields or a previous report's MATCH label.
- Preserve complete session/slot/sample denominators. Unassessed, missing,
  duplicated, invalid, differing and agreeing evidence remain distinguishable.
  Never silently intersect dates, remove samples or turn missing evidence green.
- Source independence remains a declaration with its existing limitations;
  synthetic agreement proves software behavior only. No market-accuracy
  certification, clean-data gate, strategy promotion or profitability claim.
- New derived reports have explicit versions and identities. They do not
  mutate Q5/experiment bytes, IDs, fitting, predictions, execution or old readers.
  Output uses existing exclusive new-file publication; no state replacement.
- All work is offline engineering. Actual independent observed data must be
  supplied separately before any empirical agreement claim is possible.

## Q46 — actual Q5 price-grid comparison coverage

**Goal:** for one verified research dataset, identify exactly which admitted
prices have a same-basis external comparison and retain every unassessed slot.

**Method:** accept a small explicit manifest with Q5 source declarations,
asset class/currency/aggregation/volume basis and reference snapshot paths.
Each reference belongs to a distinct Q5 session; partial aligned windows are
allowed, with the rest of the session explicitly unassessed. Reject duplicate
reference days, scope outside Q5, or incompatible semantics instead of choosing
one source silently. An empty reference list is valid and produces unavailable
comparison evidence. Construct each left snapshot from verified Q5 prices and
reuse Q44 comparison/alignment. Retain data ID, source build IDs, actual
row-version IDs, full grid rows, per-session/overall counts, source declarations,
content identities and the complete Q44 comparisons.

**Dependencies:** Q42 numeric constraints, Q44 comparator and exclusive report
writer, existing Q5 reconstruction and original session geometry. No new
provider, calendar, schema migration or numerical comparison engine.

**Acceptance:** real Q5 build/load and CLI paths; independent full-grid/count
oracles; partial and absent reference coverage; price/volume differences;
duplicates, invalid rows and gaps; incompatible or duplicate reference scope;
precise row-version identity; stable rerun identity and changed-reference
identity; input bytes unchanged. No model fit or Q6 execution. Required CI and
independent final-candidate review close the task.

**Exclusions:** window/sample impact (Q47/Q48), reference conflict resolution,
automatic repair/selection, vendor accuracy or complete source independence.

### Q46 entry and manifest

```console
market-vault research-intraday-market-evidence --data /absolute/q5.json --manifest /absolute/evidence-plan.json --output /absolute/new-evidence.json
```

The API is `analyze_intraday_market_evidence(data, plan, base=None)`, where
`data` is an explicit Q5 path or an `IntradayDataset` that is strictly verified
again by the public entry. The CLI does not require an application settings
file. SUCCESS means an evidence report was produced, including PARTIAL or
UNAVAILABLE reports. Existing output files are refused, even for identical
content; choose a new report path for another observation.

| Manifest field | Exact meaning |
|---|---|
| `schema_version` | `market-vault-intraday-market-evidence-plan-v1` |
| `source` | Q44's six-field declaration for the actual Q5 source: provider, version, captured_at, data_kind, upstream_id, upstream_evidence. |
| `basis` | Explicit asset_class, currency, aggregation and volume_basis; these remain caller declarations. |
| `references` | Array of `{scope, snapshot}`; scope is a complete Q44 scope, snapshot is a local file path or null. Relative paths resolve beside the manifest. |
| `tolerances` | Optional complete Q44 tolerance object; omission gives zero tolerances. |

Q44's [snapshot contract](contracts/market_data_comparison.md) defines the
source/scope/tolerance values. A missing file/null reference keeps its declared
window as NOT_RUN; malformed input retains INVALID_INPUT and available input
byte identity. `references: []` keeps the whole Q5 grid UNASSESSED. AVAILABLE
means complete numerical comparison coverage, including any DIFFERENT rows;
it does not mean agreement, independence or market accuracy. Reference-level
status counts and `input_diagnostics_present` keep invalid rows visible even
when those rows cannot be attached to a particular Q5 slot.
The local `PRESENT`/`MISSING` state describes Q5 admission; the separate
`comparison_local_state` records Q44 validity when a paired grid was inspected.
Strict Q5 reconstruction does not imply valid OHLC ordering under Q44. Input
diagnostics remain visible even when an absent reference prevents comparison.

## Q47 — Feature-window and target dependency evidence

**Goal:** explain which original Q5 observations and targets potentially depend
on differing or unassessed input bars, without falsely claiming a numerical
feature, prediction or PnL change.

**Method:** reuse Q46's verified dataset and full grid in the same action.
For every original observation, map the complete recorded
`window_start <= bar_start < decision_time` support. Call this conservative
Feature-window exposure; do not infer per-Feature numerical sensitivity.
For each target, separately identify the next-open entry and last-close exit
by the actual row-version/slot evidence, and the whole future interval used
for target completeness. Only entry-open/exit-close differences can support
an endpoint-price disagreement; a middle-bar high/volume difference cannot.
Preserve original READY/unavailable observations and COMPLETE/incomplete/no-
target states, coverage denominators, boundary reasons and dependency details.

**Dependencies:** completed Q46; unchanged Q5 window, endpoint and actual-label-
end contracts. Output remains an explicitly versioned derived report, with a
settings-independent CLI and immutable output.

**Acceptance:** hand-derived slot/window cases distinguish just-outside and
inside Feature windows, entry-open/exit-close from unrelated fields, same-bar
entry/exit, incomplete tails and missing reference support. Every observation
and target reconciles to the original denominator and exact Q5 identity.
Changing a reference cannot change original labels or samples. No fitting,
reselections, hypothetical repaired data or profit recalculation.

**Exclusions:** exact formula-level Feature sensitivity, causal model impact,
dropping contaminated observations or automatically selecting a cleaner period.

### Q47 entry and dependency meanings

```console
market-vault research-intraday-market-dependencies --data /absolute/q5.json --manifest /absolute/evidence-plan.json --output /absolute/new-dependencies.json
```

The API is `analyze_intraday_market_dependencies(data, plan, base=None)`;
`run_intraday_market_dependencies(data_path, manifest_path)` is its file entry.
It uses the same Q46 manifest, relative-reference resolution and exclusive
new-file writer. One action strictly verifies Q5 once and derives Q46 once.
It does not trust a previously saved Q46 report as a substitute for those reads.
The complete Q46 report is embedded once; observation support uses indices into
its complete `rows` grid, including locally missing slots.

The derived report's `REPORTED` status means the dependency calculation finished.
Its version is `market-vault-intraday-market-dependencies-v1`; the
`market_dependencies_id` binds the complete derived content. `sampling` retains
the original preset, stride and target horizon, beside the original Feature
names and window length.
The embedded Q46 status still describes numerical comparison coverage. Neither
status certifies data quality. Every original observation keeps its key,
Feature value IDs, READY/UNAVAILABLE state and reason. A target retains its
original value, COMPLETE/INCOMPLETE state, reason and actual label-end time.
Reference changes cannot rewrite any of those original facts.

| Dependency | Included support | Interpretation |
|---|---|---|
| Feature window | All same-session slots in the recorded `[window_start, decision_time)` interval, including gaps. | Conservative exposure to differing or incompletely compared input bars; no claim that a particular Feature formula changed. |
| Target completeness | Same-session slots after the observation, bounded by the requested horizon and session end; excess horizon is an integer shortfall. | Full recorded support for target availability, separate from the price fields that determine a COMPLETE value. |
| Actual target endpoints | Original `entry_row_version_id` open and `exit_row_version_id` close, only for COMPLETE targets. | Field-level disagreement in the actual price dependencies; no recomputed external target and no inferred change to the return ratio. |

For observation slot `k` in a session with `N` slots and target horizon `H`,
the same-session future support has `min(H, N - k - 1)` slots. The remainder
is `session_end_shortfall`. Even a very large valid H never creates an H-sized
list or crosses into another session. The original Q5 `SESSION_END` reason
keeps precedence over `MISSING_PRICE`, while missing same-session support stays
visible. INCOMPLETE targets have no actual endpoint references. With H=1,
entry and exit share a bar but still refer to its distinct open/close fields;
with targets disabled, target evidence is null.

A high or volume disagreement in an intermediate bar may expose a Feature
window or target-completeness support. It is not an entry-open/exit-close
disagreement. A Q5-present bar that Q44 blocks for invalid OHLC remains PRESENT
with blocked comparison evidence; this layer does not compare selected fields
again to bypass the block. Even two differing endpoint prices can preserve
the same return ratio, so endpoint disagreement is not a changed target value.
The counts of targets with endpoint disagreement and targets without complete
endpoint comparison can overlap: one endpoint may differ while the other is
unassessed. They must not be added as if they were mutually exclusive groups.

Counts of support links can exceed the number of distinct bars because a bar
may support multiple observations. They are not independent samples. The
two-day 5m LIGHT-window-5, stride-1, H=3 acceptance case has 148 observations,
142 COMPLETE targets, six incomplete tails, 740 Feature links, 432 same-session
future links, total shortfall 12 and 284 actual endpoint field references.
Zero-observation datasets retain their complete Q46 session/grid evidence with
zero dependency counts.

## Q48 — recorded ML sample-use evidence and research entry

**Goal:** show whether disputed/unassessed dependencies occur in the sample
sets actually recorded for a learned candidate or selection procedure, even
when those dates never produced a trade.

**Method:** admit an explicit ordinary learned DEV candidate or saved Q25,
Q31 or Q36 study using existing immutable readers. Bind the exact Q5 data ID
and complete original context. Project Q47 observation evidence onto recorded
outer training, purged rows, outer predictions/scored targets, inner training,
inner holdout/scored targets and final DEV history/holdout sets, as applicable.
Keep stages, fold IDs and window boundaries, READY versus COMPLETE support, actual selected
recipes and original sample counts separate. Missing/unknown keys or mismatched
data/context fail binding; there is no silent intersection or reduced sample.
This is recorded sample-use derivation, not a fresh proof of the saved model's
fit. Normal source FullReplay remains the stronger reconstruction operation.

Q25's MSE objective uses its exact `scored_targets`. Q31/Q36 instead use all
READY holdout decisions and the complete recorded inner execution-price grid;
their history targets are not the economic objective's scoring sample. Keep
these meanings separate and include the latter price-grid exposure. Shared
six-model/24-member inputs do not count as six/24 independent samples. Q31
outer application reuses its fixed source model. Final DEV's complete history
is eligible for a later final fit, not a TEST fit already performed. An
UNAVAILABLE procedure's retained windows are declared inputs with no fits or
applications executed, even when individual windows have no local error.

Use the same verified Q5 object to reconstruct the ordinary context and each
inner/final window's non-fitted input fields. Compare keys, targets and cutoffs
exactly, without calling the fitting/evaluation entry points or rereading Q5.

Expose the complete chain through a settings-independent CLI and a compact
native research surface: explicit source/manifest inputs, captured completed
identities, coverage and stage tables, dependency detail and selectable full
evidence, with failure/retry, source relocation and language support. UI views
do not rerun models or reinterpret old results after draft changes.

**Dependencies:** Q46–Q47 plus existing ordinary/procedure sample grammars,
research context preparation and native asynchronous result-capture patterns.

**Acceptance:** real ordinary and Q25/Q31/Q36 saved fixtures prove correct
stage/key mapping, train-only evidence remains visible despite no outer trades,
purged/inner/outer/final DEV sets keep their actual denominators, and bad
bindings fail. An endpoint disagreement and volume-only Feature exposure stay
distinct through the sample projection. Real CLI/native run and result views,
failure recovery, captured identity, compact-window and language checks pass;
no fit, recipe reselection, Q6 execution, TEST scoring or data writes occur.

**Exclusions:** TEST ranking or new TEST lifecycle, automated research gate,
general experiment registry, new report platform, revised forecast/PnL estimates,
new inference or model/history/Feature search.

### Q48 entry and source binding

```console
market-vault research-intraday-sample-usage --experiment /absolute/saved-dev.json --manifest /absolute/evidence-plan.json --cost-index 0 --candidate-index 0 --output /absolute/new-sample-usage.json
```

The analysis API is `analyze_intraday_sample_usage(snapshot, plan, *,
cost_index=0, candidate_index=0, intraday_data_file=None, base=None)`, accepting
an immutable `StrategyExperiment` and the same Q46 evidence manifest. The file
entry is `run_intraday_sample_usage(source_path, manifest_path, *,
cost_index=0, candidate_index=0, intraday_data_file=None)`. The optional CLI
`--intraday-data` names an explicit relocated Q5 file; omission uses the source's
recorded locator. Relative reference snapshots resolve beside the manifest.

For an ordinary DEV comparison or diagnostic, indices select one cost group
and one RIDGE or QUADRATIC_RIDGE candidate; both default to zero. For Q25,
Q31 and Q36, requested indices must both be zero because the study has one
selected outer account. Its actual embedded source cost/candidate selection
remains visible, including nonzero recorded indices. The existing immutable
source readers and algorithm-version gates remain authoritative.

One action strictly reconstructs Q5 once, derives Q47 and Q46 once, and uses
that same verified Q5 object to reconstruct the complete ordinary research
context and all inner/final window input facts. The binding compares saved
keys, order, targets, cutoffs and economic execution-input grids. Unknown keys,
changed context, incompatible data or changed recorded window inputs fail the
action; they never yield a report with a smaller intersected sample. The
embedded ordinary source is read from the captured study, without reopening
its historical source filename.

The report version is `market-vault-intraday-sample-usage-v1`, with a
content-bound `sample_usage_id`. It retains source/content identities, original
selection, data/content identity, matched context, normalized manifest identity
and Q47/Q46 identities. `dependency_evidence` contains one complete Q47 report;
that report contains one complete Q46 report. Stage `sample_refs` are indices
into Q47 observations, while `price_row_refs` are indices into the Q46 full grid.
The source content SHA refers to canonical immutable snapshot bytes, not the
original file's whitespace or formatting.

`AVAILABLE` means binding completed for a source with recorded actual uses.
`DECLARED_ONLY` means binding completed for an UNAVAILABLE procedure whose
retained windows were not executed. Neither is a data-quality grade. The
embedded Q46 coverage status remains separate, including DIFFERENT and
unassessed evidence. CLI SUCCESS means the report was produced; both report
statuses may be successful outputs. Existing output files are refused.

### Q48 stage meanings and denominators

| Recorded stage | Feature / target use | What the fit fields mean |
|---|---|---|
| Ordinary outer training | Actual training Features and COMPLETE target labels. | The source records an ordinary fold fit. |
| Q25/Q36 outer training | Actual selected-recipe training dependencies. | The procedure records an outer refit. |
| Q31 outer training | Actual dependencies of the reused fixed source model. | The procedure did not perform another outer fit. |
| Outer prediction, and Q25 inner holdout prediction | Features are used for recorded predictions; their target labels are associated evidence only. | Prediction is not a fit stage. |
| Outer target score, and Q25 inner target score | Exact COMPLETE scoring labels, through recorded predictions. | Q25 uses its saved `scored_targets`; READY prediction counts remain separate. |
| Inner model training | Actual inner training Features and COMPLETE labels; the six-model family shares one input set. | Preserve each recorded model identity and recipe without multiplying sample counts by family size. |
| Q31/Q36 inner economic holdout | READY holdout decisions and the complete recorded execution-price grid. | Target labels are not used by the economic objective; a 24-member family does not create 24 independent input samples. |
| Purged rows | Retained excluded inputs with zero actual-use count. | Purge is not a fit. Empty original purge sets remain empty. |
| Final DEV complete history | History eligible for a later final fit, distinct from the actual final inner training/holdout split. | No final TEST fit is performed by this evidence action or asserted to have occurred in the source study. |
| Any UNAVAILABLE procedure's retained windows | Declared inputs with zero actual-use counts, even if an individual window has no local error. | The procedure's global unavailability means its fits, refits and applications were not executed. |

Stage membership counts can include the same observation in several roles or
folds. Summary fields therefore separate recorded memberships, actual-used
memberships and their distinct observation counts. They are not independent
statistical samples. Each stage preserves its source order and original
denominator; purged, eligible-only and unexecuted declarations are not counted
as actual fits or scores.

The shared 130-day synthetic saved-fixture acceptance case has the following
independently reconciled totals. These are engineering oracles, not observed
market results. Q25's final eligible history contributes 840 recorded
memberships without becoming an executed final fit; the same distinction
applies to Q31 and Q36.

| Source | Stages | Recorded sample memberships | Actual-used memberships | Unique actual observations | Economic price-slot memberships |
|---|---:|---:|---:|---:|---:|
| Ordinary | 16 | 3,210 | 3,210 | 1,040 | 0 |
| Q25 | 38 | 6,725 | 5,885 | 1,050 | 0 |
| Q31 | 33 | 6,550 | 5,710 | 1,050 | 325 |
| Q36 | 33 | 6,550 | 5,710 | 1,050 | 325 |

Three separate support summaries describe Feature windows, actual COMPLETE
target endpoints and target-completeness intervals. Each records applicable
and non-applicable samples, samples with differences and samples with incomplete
comparison evidence. Difference and incomplete-evidence counts can overlap.
Endpoint comparison uses Q47's exact field status, so volume/high-only changes
do not become open/close endpoint differences. Known session-end horizon
shortfall is an original label-boundary fact; it does not itself mean missing
external comparison evidence. The original target state and reason stay visible.

Economic holdout price evidence includes every slot of its original sessions,
not just trades, selected Feature windows or externally covered bars. Preserve
whole-slot status counts and separate open/close field comparison counts.
A bar's volume difference cannot become an execution-price disagreement.

The analysis records that Q5, context and window inputs were reconstructed.
It also explicitly records no model refit, selection rerun, execution replay
or complete research replay. Historical `recorded_fit_executed` and `fit_origin`
describe the saved research grammar; they are not a new proof of coefficients,
selected winners or account generation. Existing FullReplay is stronger.
Strict Q5 verification includes the saved data's full session grid, including
held-out dates; this action adds no TEST score, ranking or selection use.

### Q48 native capture and review flow

The intraday workspace appends a sample-use evidence entry without moving the
existing sections. Open captures one explicit source's immutable canonical
content, identity and content SHA. Ordinary sources can be opened when candidate
zero is not learned, so the user can explicitly choose a supported candidate.
UNAVAILABLE Q25/Q31/Q36 sources are also admitted for declared-input evidence.

Run reads the current manifest once, captures the selected indices and optional
Q5 override, and analyzes the already-opened source bytes in a background worker.
It does not reopen that source filename. Completed identities retain the opened
source path/content SHA, requested manifest/data locators and indices, together
with the actual report identity. Editing and restoring an input still invalidates
an in-flight result through a monotonic input revision. Draft edits, failed opens,
failed runs and stale completions leave the previous completed result intact.

Overview, stage, sample and bar evidence is projected from the completed report.
Language, selection and pagination changes do not reread files or rerun analysis.
Selectable evidence, copy and exclusive new-file save retain the full captured
chain. Compact 1024-by-600 English and Simplified Chinese validation uses the
actual Main.qml, native Qt controls and asynchronous worker. This is local Qt
engineering validation, not a Windows release or live-market qualification.

## CI cost and verification

Q45 natural FULL `38141083302/1` measured `intraday_ml_procedures` at 742
seconds (12m22s), versus 340 seconds for `strategy`. The three existing
comparison/family/stress files account for at least 179.49 seconds in the
reported slow-test table. Q46 moves those three files together to the existing
strategy partition with exact-file ownership, preserving their shared fixture,
tests and assertions. Retain eleven partitions, sixteen physical jobs, FULL
semantics, Python 3.14 compatibility and package gates. Compare complete
collection with the union of partitions. Registry changes force the existing
normal FULL fallback on the first resulting main; do not claim reuse for it.

Runtime estimates are not a ten-minute guarantee. Check actual natural FULL
durations and address a remaining bottleneck only when new evidence warrants it.
Use focused local behavior checks and mandatory remote CI; do not duplicate a
full local suite merely because a PR exists. Native validation uses real Qt in
the available development environment, not a claim of Windows release testing.

The completed natural FULL runs provide the measured result:

| Natural run | ML procedures | Strategy | Longest functional job |
|---|---:|---:|---:|
| Q45 PR `38141083302/1` | 742 s | 340 s | 742 s |
| Q46 final PR `38153626605/1` | 413 s | 646 s | 646 s |
| Q46 exact main `38154754691/1` | 411 s | 658 s | 658 s |
| Q47 PR `38156605646/1` | 544 s | 649 s | 649 s |

The longest functional job decreased by 96 seconds on the final PR and 84
seconds on main relative to that Q45 run. This is an observed improvement,
not a guaranteed runtime. Same-phase timing variation and the small new Q46
test contribution do not justify another speculative registry change. Q47's
new `test_feature_intraday_market_dependencies.py` belongs to the existing
`dataset_features` partition, which measured 353 seconds on the Q46 final PR
and 228 seconds on main. Existing ownership and FULL semantics remain intact.
Q47's actual `dataset_features` job completed in 358 seconds with the new
dependency tests included. The unchanged ML partition's 544-second Q47 run
also shows that runner timing varies; the measured results do not justify
further speculative repartitioning of the existing tests. Q48 adds a measured
new workload: its four focused tests completed locally in 240.35 seconds,
with 78.46 seconds of reported setup and 161.44 seconds of calls. Its global
session fixture is a different pytest FixtureDef from Q35's module-local
fixture, so the current ML job cannot amortize that preparation. Moving this
new file to `dataset_features` loses no existing fixture sharing and places
sample/dependency evidence beside Q47. Use one exact-file registry entry;
retain the general ML prefix and every test, fixture and assertion.

As a capacity model only, adding about 240 seconds to the Q47 baselines gives
about 784 seconds for ML or 598 seconds for `dataset_features`, versus the
unchanged 649-second strategy job. These mixed local/CI measurements justify
placement, not a runtime guarantee. Confirm actual final PR and main timings.
Keep eleven partitions and sixteen FULL jobs. The registry is control-plane
code, so this Q48 change requires a normal natural FULL on the resulting main,
with no post-merge reuse; account for that one-time verification cost.
The native test remains in `app_ops`; real local Qt acceptance supplements
the existing Qt-free natural CI environment.

## Method references

- [TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html): chronological evaluation and optional bounded training size; not adopted as a replacement for the Q5 trading-day and label-end purge rules.
- [Common pitfalls](https://scikit-learn.org/stable/common_pitfalls.html): preprocessing must be learned from training data, and test data must not drive model decisions.
- [Q42–Q45 market-data trust](market_data_acceptance_next.md), [Q30–Q32 training policy](intraday_training_policy_next.md), and [Q39–Q41 procedure robustness](intraday_procedure_robustness_next.md) retain their accepted meanings.
