# Intraday training and decision policy package: Q30–Q32

The completed package is followed by [Q33–Q35 ML evidence](intraday_ml_evidence_next.md):
outer score diagnostics, fixed inner-objective sensitivity and selected-procedure
incremental return uncertainty. The Q30–Q32 source and TEST meanings below remain unchanged.

## Baseline, scope and delivery

The implementation baseline is verified Q29 main
`5cd24afedc6dd52239b4937c62ea05fb0310575f` in `M0DIAN/market-vault`.
The owner's 2026-10-11 JST request authorizes this three-item package's
implementation, in-scope repairs, tests, commits, push, PRs, independent
final-candidate review, conditional squash merge and exact-main CI verification.
It does not authorize releases, deployment or live trading.

Each item begins on a feature branch from the preceding verified main. Its
final candidate must pass independent review and required natural PR CI for
the same SHA, with the actual PR head/base checked before squash merge.
After terminal successful CI on the exact merged main SHA, continue to the
next item without another routine authorization request. A scope-local fix or
new candidate receives the necessary incremental review and verification.

Q1–Q29 already provide verified immutable data, actual-label-end purging,
expanding DEV folds, linear/quadratic Ridge execution, bounded inner MSE model
selection and explicit Freeze/TEST. Return uncertainty, family bounds,
feature omission, parameter neighborhoods, signal-delay stress and portfolio
cash models also exist. Q27–Q29 add calendar support, immutable publication /
forward recovery and NONE return-basis/event-window disclosure. Those are
accepted foundations, not new tasks in this package.

| Direction | Decision based on the current code |
| --- | --- |
| History sensitivity | Q30. Ordinary DEV always trains on `dev[:start]`; existing fold displays do not refit with older history removed. |
| Economic decision selection | Q31. Q25 selects representation/alpha by pooled MSE and copies the source threshold; it does not choose a threshold using inner Q6 accounts. |
| Held-out evaluation of that decision | Q32. Q26's source grammar binds the existing six-member MSE procedure, not a new economic threshold procedure. |
| More prediction views | Q21 already supplies pooled/fold errors and references. Extending its reader to another source is deferred; it does not replace the history question. |
| New learners or broad search | No new learner dependency, feature search, model registry, optimizer, 24-member model/threshold family or online training. |

The delivery order is **Q30 history sensitivity → Q31 economic threshold
selection → Q32 explicit final DEV Freeze/TEST**. Q30 and Q31 address separate
questions; Q31 does not automatically use a hindsight winner from Q30. Q32
depends directly on the complete Q31 saved evidence.

Cross-day `ridge_trading_selection` already selects thresholds for its separate
dataset/trading authority. Q31 adds the intraday fixed-model outer/inner Q6
path; it does not redo that cross-day engine or inherit its higher-threshold
tie-break. This package fixes ties to FIRST_DECLARED.

## Shared defaults

- Sources are explicit ordinary saved DEV comparison/diagnostics candidates.
  Preserve their Q5 identity, Feature order, original folds, evaluated dates,
  execution costs/windows and target meaning. A Q10 collection must first be
  exported as its ordinary child. TEST is never a development selection set.
- Preserve all original READY validation predictions, including incomplete
  target tails. Prediction losses use COMPLETE targets only; Q6 accounts use
  every READY decision and the full selected session/price grid.
- Training requires READY Features and COMPLETE targets whose **actual label
  end is strictly before** the relevant training boundary. Fit transformations
  using only that particular admitted training sample.
- Linear Ridge retains its current allowed projection. Only quadratic Ridge
  inherits its existing 1–6 input-Feature / at-most-27-term bound and two-stage
  TRAIN-only normalization. No general six-Feature limit is added to linear
  sources.
- Returns use NONE unadjusted prices. Prediction target return and simulated
  account cash change have different meanings. Split-share adjustments and
  cash-dividend accounting remain absent; event coverage remains UNKNOWN
  without explicit assessment. No total-return or corporate-action clearance
  claim is introduced.
- Existing saved artifacts, algorithm versions, IDs and replay semantics keep
  their meaning. New derived/selection contracts use explicit versions rather
  than quietly expanding historical grammar. No source overwrite or migration.
- Explicit actions capture source contents/identity, indices and relocation
  inputs before a worker starts. Input changes prevent stale results from
  replacing the completed evidence. Errors retain the previous completed
  result and allow a deliberate retry.
- Package/runtime version stays 0.9.0. Tests are offline; no data-provider,
  execution-kernel or live-account changes are required.

## Q30 — fixed-recipe history sensitivity

### Goal and implementation

For one selected ordinary `RIDGE` or `QUADRATIC_RIDGE` candidate, compare the
fixed ordered histories `EXPANDING`, `TRAILING_10_DAYS`, `TRAILING_20_DAYS`.
The fixed recipe includes representation, alpha, ordered Features and threshold;
the selected cost and execution policy also stay fixed.

Read verified Q5 once. Reconstruct the complete selected expanding models,
predictions, original prediction metrics, Q6 account, risk and fold cash
contributions, plus the selected same-source benchmark. Any difference fails
before a comparison is returned. This is explicit selected-candidate and
benchmark verification; it does not claim to replay unselected source
candidates or cost groups.

For each original fold, a trailing history uses the last N entries of its
original `training_days`, then applies the existing actual-end purge. N counts
declared training trading days, including days with no eligible rows, rather
than the number of observation-bearing dates. Every model records actual
training/purged keys, boundary, Feature order and complete fitted transforms.
Action-local fits can be reused only when their recipe, actual training keys,
validation keys and cutoff agree.

If any original fold has fewer than N history days, or no eligible training
rows after purge, the **entire corresponding variant** is `UNAVAILABLE`.
It retains every original fold and concrete reasons, but has no fitted models,
partial prediction series or shortened account. Other complete variants remain
available. The report is `PARTIAL` when a recent variant is unavailable.

All available variants predict the same original READY keys and execute a
separate continuous cash-1 Q6 account over the same original evaluated days.
They retain full transactions, trades, OPEN/CLOSE ledger, daily cash, risk and
fold contributions. The benchmark stays common. Pooled and fold prediction
quality uses COMPLETE row-weighted pairs; error differences are variant minus
expanding, so positive means worse. MSE uses squared return ratios; MAE/RMSE
differences use return ratios (percentage points when displayed as percentages).
The study is descriptive and does not select a window.

### API, CLI and native entry

`research.intraday_training_history.analyze_intraday_training_history` accepts
an immutable `StrategyExperiment`, explicit zero-based `cost_index` and
`candidate_index` (both default 0), and optional `intraday_data_file` relocation.
The report version is `market-vault-intraday-training-history-v1`, with its own
`training_history_id`. It includes the exact selected source IDs, fixed recipe,
execution policy, return basis, source locator, verification scope, method,
original context/sample, benchmark and all three variants. Each available
variant includes complete models, prediction metrics and account evidence.

```console
market-vault research-intraday-training-history --experiment /absolute/development.json --cost-index 0 --candidate-index 1
market-vault research-intraday-training-history --experiment /absolute/development.json --candidate-index 1 --intraday-data /relocated/intraday.json
```

The settings-independent command returns deterministic ASCII-safe JSON on
stdout. Successful computation, including explicit unavailable recent
histories, returns exit 0; invalid source/options or computation failure
returns a FAILED JSON envelope on stderr and exit 1. Argparse usage errors
retain exit 2. The command opens no output path and cannot overwrite its input.
This derived report is not an ordinary strategy, saved experiment, Freeze
selection or TEST artifact.

In **Quant Research → Intraday → Training history**, choose the saved DEV
candidate, optionally set a relocated Q5 path, then explicitly Analyze/Refresh.
The completed result shows all-history account/prediction comparisons and
curves. Select a history for fold errors, complete keys, model/scaler evidence,
READY predictions, trades, daily cash, ledger, transactions and fold cash
contributions. Select the benchmark for its complete account views; model and
forecast views explicitly state that they do not apply. The visible return
basis reads the completed report's NONE, split, dividend and coverage fields.
Full-page evidence opens selectable, wrapped, scrollable text with complete
keys, boundaries and complete fold model records, without table elision. Captured-source
details identify the actual completed candidate, costs and data location.
Views and language changes do not rerun calculations. The panel and tab row
adapt to the supported compact window; table pagination stays reachable.
Complete machine-readable evidence is available from the CLI JSON.

### Acceptance

- A historical slope reversal has independent expected Ridge predictions;
  recent/expanding histories differ using actual refits, not renamed outputs.
- Older-than-window changes do not alter a recent model; future validation
  changes do not alter that fold's fit. Strict boundary equality is purged,
  and neither the extreme purged row nor future values enter the scalers.
- Same actual keys produce the same model; different recent windows cannot
  collide in the fit cache. Linear and quadratic sources both work.
- Too-short history and an empty post-purge sample make only that entire
  variant unavailable. No fold is silently dropped.
- One real saved Q5 source proves a single data admission, complete source /
  benchmark reconstruction, all-READY common execution, deterministic CLI,
  relocation, failure and retry. A real Qt/QML run exercises result views,
  captured-input stale rejection and compact pagination.

### Exclusions

Automatic history selection, promoting a recent window into ordinary plans,
rolling-window Freeze/TEST, time decay, online refitting, Q25 window search,
Feature/alpha/threshold/cost changes and inference about future profitability.

## Q31 — bounded inner economic threshold selection

### Goal and technical approach

Select only the decision threshold for one fixed saved ordinary linear or
quadratic recipe. Keep its representation, alpha, Features, original outer
schedule and Q6 execution policy/costs. In every original outer TRAIN history,
use its last five trading days as inner holdout and at least ten preceding
training trading days. Fit the fixed recipe once on that purged inner TRAIN.

Evaluate the ordered thresholds **0, 5, 10, 20 basis points**, represented as
`0.0, 0.0005, 0.0010, 0.0020`, using strict `score > threshold`. All four use
the same fitted scores and complete inner READY/session grid, with independent
cash-1 Q6 accounts. Select maximum inner net compounded account return; exact
ties use **FIRST_DECLARED** in that fixed order. Do not search the grid,
tie-break, costs, model representation or alpha. This is a prediction-return
threshold family, not a claimed theoretical break-even transaction cost.

Economic selection uses actual Q6 execution and does not require COMPLETE
inner scoring labels. A READY incomplete-target tail remains eligible for
execution; an inner period with no COMPLETE scoring target may still provide
a valid trading selection when training and prices are sufficient. No-trade
accounts are legitimate. No minimum-trade penalty or Sharpe objective is added.

Apply the chosen threshold to the original outer fixed-recipe model's complete
prediction set. Reuse its verified scores where possible; a threshold cannot
change the fitted model. Produce one continuous selected-procedure Q6 outer
account on all original evaluated days and a same-sample fixed-threshold source
reference. Repeat the declared inner procedure once over all TRAIN + VALIDATION
history to retain a final DEV threshold and all four candidate account records.

Use a new independent threshold-selection artifact with complete boundaries,
keys, fitted model, scores, four inner accounts, chosen index/threshold,
outer outcomes and final DEV evidence. Include save/open/full replay, CLI and
native entry. Any insufficient required history/training/execution input makes
the study unavailable as a whole; do not discard folds or fill with cash.

### Saved evidence and command line

The independent schema is `market-vault-intraday-threshold-selection-v1`, with
evaluation mode `INTRADAY_THRESHOLD_SELECTION`. Capture an ordinary saved
`INTRADAY_COMPARISON` or `INTRADAY_DIAGNOSTICS` experiment ID, cost index,
candidate index and candidate ID explicitly. The selected candidate must be
fixed `RIDGE` or `QUADRATIC_RIDGE`; a Q25 procedure with changing per-fold
models is not an ordinary source. Linear sources retain their existing Feature
width; only a quadratic source uses the six-input / 27-term representation
bound. The original source threshold is a fixed reference, even when it is
outside the four-value selection family.

Each saved window retains the complete historical and purged keys, admitted
targets with actual end times, inner days/boundary, one model and one shared
prediction set. Its four ordered members each retain a complete Q6 account
on the same saved session/price grid. Shared predictions retain the original
source threshold; each account's decisions apply that member's threshold.
The outer application copies the verified original fold model and raw scores,
then changes only its decision threshold. The selected outer account carries
cash across every original evaluated day, with the original fixed reference
and benchmark available on the same sample. Final DEV retains the same full
window evidence without making a TEST prediction or introducing Selection V3.

Run and FullReplay each admit Q5 once and reconstruct the complete ordinary
source before evaluating the threshold procedure. Recorded Open performs
structural, boundary, fixed-method, account and economic-winner consistency
checks without reading Q5, fitting or rerunning Q6. Open does not establish
the origin of a fully self-consistent saved fit; FullReplay reconstructs the
fit and complete source to detect that case. Missing valid inner price coverage
or execution windows that do not fit a valid inner session produce whole-study
`UNAVAILABLE`; invalid source/data and unexpected numerical failures remain
errors. Save uses the existing immutable writer and cannot replace a different
artifact at the same path.

```console
market-vault research-intraday-threshold-selection \
  --source-experiment /absolute/source.json \
  --expected-experiment-id SOURCE_ID \
  --cost-index 0 --candidate-index 1 \
  --expected-candidate-id CANDIDATE_ID \
  --experiment /absolute/threshold-study.json
market-vault research-experiment-open --experiment /absolute/threshold-study.json
market-vault research-experiment-replay --experiment /absolute/threshold-study.json
```

An explicit `--intraday-data` for Run, or `--intraday-data-file` for FullReplay,
can relocate the verified Q5 source. Replay uses the embedded ordinary
experiment; an optional `--source-experiment-file` replacement must equal that
saved source completely.
Changing a source path does not rewrite saved identities or original locators.
The Python entry is `run_intraday_threshold_selection`; the shared experiment
writer, loader and replay dispatcher support its independent contract.

### Native workflow

In **Quant Research → Intraday → Economic thresholds**, first open or save an
ordinary DEV Ridge in Development research. Choose the saved DEV cost /
candidate, then explicitly Run threshold selection. Evidence range selects the
original outer evaluation, an outer fold's inner holdout, or the final DEV
holdout. Account selection exposes the selected procedure, fixed source and
benchmark on the outer sample, or all four thresholds on an inner sample.

Result views retain account metrics, dates, complete keys and both boundaries,
historical target evidence, fixed models, actual execution decisions, trades,
daily cash, ledger, transactions, continuous outer fold contributions, and
inner sessions/prices. Full page evidence opens selectable, wrapped, scrollable
JSON with complete model IDs, transforms and keys. Inner shared predictions
keep the source threshold; the decisions view uses the chosen account's actual
execution decisions. The final DEV model remains an inner-training model.

Save threshold study uses the immutable writer. Open threshold study records
`RECORDED` verification; only Verify full replay can establish a fresh
`REPLAY_MATCH`. Optional Q5 and ordinary-source relocation fields are captured
together when that action starts. Changing an input prevents a stale delivery
from replacing completed evidence; errors preserve the previous result and
allow an explicit retry. Completed-source details retain the verified paths.
The panel supports both languages and compact-window scrolling/pagination;
views and language changes do not rerun the study. Q31 has no Freeze/TEST
control.

### Acceptance and exclusions

An independent cost-reversal example changes the economically selected
threshold; an inner/outer reversal detects hindsight selection. Four candidates
share one fit, actual costs and dates, deterministic ties and READY tails.
Outer/TEST interventions cannot change the current historical choice.
Saved CLI/native workflows replay the complete study and retain failures.

Exclude the 6-model × 4-threshold economic family, arbitrary threshold grids,
Feature/alpha/history/cost searches, automated Freeze, TEST optimization, live
inference and global overfitting-probability claims. Existing Q25 remains the
separate unchanged six-member **MSE** procedure.

## Q32 — economic-selection Freeze / TEST

### Goal and explicit contracts

Freeze the complete Q31 final DEV threshold evidence and fixed recipe using
explicit **Selection / TEST V3** contracts. The implementation starts from
Q31's verified main `1dc871ccd71539658a096f5f4a0be866166b637e`.
V1 retains Q8's ordinary DEV meaning; V2 remains closed around Q26's ordinary
quadratic and Q25 six-member MSE sources. V3 admits only an `AVAILABLE` saved
`market-vault-intraday-threshold-selection-v1` experiment. It does not convert
an existing selection, ordinary source, Q25 study or unavailable Q31 study.

| V3 surface | Explicit version |
| --- | --- |
| Selection artifact / plan / result | `market-vault-intraday-selection-v3` / `market-vault-intraday-selection-plan-v3` / `market-vault-intraday-selection-result-v3` |
| TEST artifact / plan | `market-vault-intraday-test-v3` / `market-vault-intraday-test-plan-v3` |
| Final algorithm / context / result | `market-vault-intraday-final-test-v3` / `market-vault-intraday-final-context-v3` / `market-vault-intraday-final-test-result-v3` |

Each TEST version embeds exactly its matching Selection version. A V3 root
cannot fall back to V1 handling or embed a V2 selection. The Selection retains
the complete ordinary/Q31 algorithm versions; the final TEST version set
contains only the selected representation's required model algorithms. Linear
Ridge preserves projections wider than six Features. Quadratic Ridge retains
the existing six-input / 27-term bound. The existing final fitter, Q6 engine,
benchmark, risk calculations, immutable writer and replay dispatcher are reused.

### Freeze evidence and fixed defaults

`freeze_intraday_threshold_selection(path, expected_experiment_id=...)` reads
and validates the saved Q31 file, then extracts its saved final DEV winner.
It does not read Q5, fit, recompute the four accounts or select a winner again.
The source reference binds the **direct Q31 file**, its experiment ID, its
artifact schema and its `threshold_selection_id`. The explicit selection is
`final_dev_index`, and the scope is
`DEVELOPMENT_INNER_ECONOMIC_THRESHOLD_FINAL_RECIPE`.

The frozen candidate is exactly `final_dev.selected_recipe`, with empty
candidate axes and the original Q6 execution policy. `dev_selection` retains
the method, complete ordinary-source identity, original cost/candidate indices
and candidate ID, original reference strategy/axes, and the complete final DEV
window. That window includes all four ordered threshold accounts, the shared
inner model and scores, complete sessions/prices, admitted targets, all keys,
both boundaries, chosen index and recipe. The fixed source threshold remains
visible even when outside the four-value family. The economic metric remains
net compounded account return, ties remain FIRST_DECLARED, and decisions remain
strictly `score > threshold`.

The Selection and TEST V3 reports each retain Q31's exact `return_basis`:
NONE unadjusted prices, no split-share adjustment, no cash-dividend accounting,
simulated account cash change and UNKNOWN corporate-action coverage. This
disclosure does not broaden Q29's event-assessment source grammar or claim
corporate-action clearance.

### One independent TEST evaluation

Normal TEST validates the current algorithm versions and complete saved Q31
source/config binding, then admits Q5 once. It derives the final training
sample from all eligible TRAIN + VALIDATION observations, with actual label
end strictly before the first TEST session open. Before any fitter runs, it
must match all three frozen history fields exactly:

| Actual final context | Frozen Q31 final DEV field |
| --- | --- |
| `training_boundary` | `history_boundary` |
| `training_keys` | `history_training_keys` |
| `purged_keys` | `history_purged_keys` |

The same binding is enforced when opening a saved TEST. The inner window's
`training_keys`, `training_boundary` and `model` are evidence for threshold
selection; they are not the final TEST training sample or fitted model.
Final TEST fits the fixed representation/alpha once using all admitted DEV
rows, keeps the frozen threshold, and predicts every READY TEST observation,
including incomplete target tails. Prediction errors use only COMPLETE TEST
targets; execution uses every READY decision and the complete TEST price grid.
The strategy and fixed benchmark each begin an independent cash-1 Q6 account,
carry cash across all TEST days, and retain complete costs, trades, daily cash,
ledger and risk. No four-way TEST comparison or threshold retuning occurs.

Normal TEST does not reconstruct DEV or Q31. FullReplay separately reads Q5
once, reconstructs the complete embedded ordinary DEV source and Q31 procedure,
and then reconstructs the Selection and, for a TEST artifact, the final TEST.
The same verified Q5 object is reused within that action. A selection-only
FullReplay reconstructs its sources without fitting a final TEST model.
Recorded Open performs pure saved grammar/account consistency checks. Neither
Open nor normal TEST establishes that a structurally consistent saved inner
fit was calculated from Q5; FullReplay establishes that stronger comparison.

### Saved command line and relocation

```console
market-vault research-intraday-freeze-threshold-selection \
  --source-experiment /absolute/threshold-study.json \
  --expected-experiment-id THRESHOLD_STUDY_ID \
  --experiment /absolute/economic-selection.json
market-vault research-intraday-test \
  --selection /absolute/economic-selection.json \
  --experiment /absolute/economic-test.json
market-vault research-experiment-open --experiment /absolute/economic-test.json
market-vault research-experiment-replay --experiment /absolute/economic-test.json
```

For V3, `--source-experiment-file` means a relocated **direct Q31 saved file**
whose frozen identity and contents must match. It does not replace the ordinary
DEV file embedded inside Q31. `--intraday-data-file` relocates the verified Q5
file with the same data identity. Both options work on normal TEST and shared
FullReplay. A wrong ordinary-file override fails before reading Q5 or fitting.
No third source alias, saved-path rewrite or migration is introduced. Save is
exclusive and idempotent for identical content; a different artifact cannot
overwrite a completed selection or TEST at that path.

Q12's saved TEST risk derivation and the native raw Q6 performance view accept
the V3 TEST account. Public Q9 saved performance, Q11 saved A/B comparison and
Q29 return assessment keep their existing V1/V2 TEST source boundaries. A V3
Selection is not a TEST account and cannot enter those account readers.

### Native workflow

In **Quant Research → Intraday → Freeze / TEST**, use **Open threshold study**
to read a saved Q31 study, or use the completed and saved study already open
in Economic thresholds. Review its captured source path and identity, then
explicitly choose **Freeze economic threshold**. Opening a source does not
freeze it. Unsaved and UNAVAILABLE studies cannot be frozen.

V3 initially displays **Final DEV · four threshold accounts**. Its account
selector exposes all four saved accounts and their actual decisions, trades,
daily cash, ledger and transactions. Changing the displayed account does not
change the frozen winner. Separate views retain the single shared inner model,
all historical and inner keys/purges, both cutoffs, admitted target evidence,
sessions and prices. Shared source prediction targets and each account's actual
LONG/FLAT actions remain distinguishable. Full page evidence provides exact,
selectable, wrapped and scrollable JSON for the selected evidence page, with
complete model payloads. Pagination exposes the remaining recorded rows.

Run TEST reuses the final account, benchmark, model, performance and risk views.
The final model is fitted on all admitted DEV keys; the saved inner model
remains selection evidence. Save/Open and FullReplay retain separate Selection
and TEST paths and verification states. Open records RECORDED; each successful
FullReplay establishes only its own REPLAY_MATCH. A computed TEST does not
upgrade the Selection's historical replay proof.

For V3, the Locations source field explicitly identifies the **Q31 threshold
study file**; the Q5 field is separate. Both are captured before Run or Replay.
Freeze also binds the completed Q31 path, artifact identity/revision and current
Selection binding, including same-content reopen and Save As path changes.
Stale deliveries and failures preserve completed evidence and allow retry.
The existing V2 six-model MSE views retain their original meaning. Both
languages and compact-window scrolling/pagination remain supported.

### Acceptance and exclusions

Acceptance requires no-Q5/no-fit/no-reselection Freeze with the complete saved
four-account evidence; exact pre-fit and recorded history binding; TEST target,
Feature and price intervention isolation of the frozen choice/final model;
one final fit; all READY tails; independent raw-price/cost/cash and benchmark
oracles; seven-Feature linear compatibility; rejected cross-version and
resealed inconsistent evidence; and full reconstruction rejecting a false
saved inner fit. Real CLI/native Freeze-save/open-TEST-replay paths must retain
source relocation, immutable files, failure recovery and separate Selection /
TEST verification states. Focused existing Q8/Q26 paths remain compatible.

Exclude threshold retuning after TEST, four-way TEST scoring, rolling-window
TEST, changes to the Q31 family, broad search, online adaptation, automatic
Freeze/promotion, new event assessment, deployment, releases and live orders.

## Bounded CI follow-through

The Q29 baseline natural FULL run `38068988258/1` recorded the strategy job at
610 seconds and final-evaluation job at 637 seconds. This is a concrete reason
to rebalance work without weakening coverage. Move
`test_strategy_return_assessment.py` to the diagnostics partition. Move the
two independent final-data-boundary tests unchanged into
`test_intraday_final_data_boundaries.py`, owned by intraday research. New Q30
tests retain exactly one explicit functional owner. Update the existing owner
registry and its assertions, compare full versus union-of-partitions collection,
and preserve all old assertions and required success semantics.

Registry changes require natural FULL verification after merge; do not claim
the normal source-only tree-equivalence reuse shortcut for that change. The
Python 3.14 compatibility arrangement (135 seconds at this baseline) remains
unchanged. No shorter timeout, dropped test, forced CI tier or parallel
replacement for independent review is introduced.

## Method references

- [scikit-learn TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)
  describes chronological and bounded training-window principles. The
  repository continues to implement its own original trading-day / actual-end
  purge contract; it does not adopt that splitter or add its dependency.
- [scikit-learn decision-threshold tuning](https://scikit-learn.org/stable/modules/classification_threshold.html)
  distinguishes prediction from the downstream decision rule and emphasizes
  separate validation data. Q31 uses continuous return forecasts and Q6 cash
  outcomes, not the page's classification estimators.
