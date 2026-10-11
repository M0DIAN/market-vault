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

## Q48 — recorded ML sample-use evidence and research entry

**Goal:** show whether disputed/unassessed dependencies occur in the sample
sets actually recorded for a learned candidate or selection procedure, even
when those dates never produced a trade.

**Method:** admit an explicit ordinary learned DEV candidate or saved Q25,
Q31 or Q36 study using existing immutable readers. Bind the exact Q5 data ID
and complete original context. Project Q47 observation evidence onto recorded
outer training, purged rows, outer predictions/scored targets, inner training,
inner holdout/scored targets and final DEV history/holdout sets, as applicable.
Keep stages, fold/window IDs, READY versus COMPLETE support, actual selected
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
no fit, source selection, Q6 execution, TEST scoring or data writes occur.

**Exclusions:** TEST ranking or new TEST lifecycle, automated research gate,
general experiment registry, new report platform, revised forecast/PnL estimates,
new inference or model/history/Feature search.

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

## Method references

- [TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html): chronological evaluation and optional bounded training size; not adopted as a replacement for the Q5 trading-day and label-end purge rules.
- [Common pitfalls](https://scikit-learn.org/stable/common_pitfalls.html): preprocessing must be learned from training data, and test data must not drive model decisions.
- [Q42–Q45 market-data trust](market_data_acceptance_next.md), [Q30–Q32 training policy](intraday_training_policy_next.md), and [Q39–Q41 procedure robustness](intraday_procedure_robustness_next.md) retain their accepted meanings.
