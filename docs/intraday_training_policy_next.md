# Intraday training and decision policy package: Q30–Q32

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

## Q31 — bounded inner economic threshold selection (planned)

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

## Q32 — economic-selection Freeze / TEST (planned)

Freeze the complete Q31 final DEV threshold evidence and fixed recipe using
explicit **Selection / TEST V3** contracts. V2 remains closed around Q26's
ordinary quadratic and Q25 six-member MSE sources. Reuse the existing final
training and Q6 numerical implementation rather than creating a TEST engine.

Freeze is no-Q5/no-fit extraction of the saved final DEV choice, retaining
source identity, all four final threshold accounts, model/keys/boundaries,
ordered family, economic metric and FIRST_DECLARED tie rule. TEST then performs
one fixed-recipe fit on all eligible TRAIN + VALIDATION rows, strictly purged
at the first TEST open, and uses the frozen threshold for all READY TEST keys
and an independent cash-1 Q6 account. There is no four-way TEST comparison.

Normal TEST verifies the bound frozen source. FullReplay reconstructs the
complete applicable DEV source, Q31 procedure and final TEST. Preserve the
existing source-relocation and immutable-file behavior and separate native
selection/TEST verification states.

Acceptance requires exact no-fit Freeze evidence, TEST intervention isolation,
one final fit and one frozen decision policy, READY tails, full cash/cost /
benchmark reconciliation, real CLI/native Freeze-save/open-TEST-replay paths,
source relocation/failure recovery and legacy Q8/Q26 compatibility.
Exclude threshold retuning after TEST, rolling-window TEST, online adaptation,
automatic promotion, deployment, releases and live orders.

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
